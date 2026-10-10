"""
ARCHER Voice Pipeline Orchestrator.

This is the central integration point for all voice components:
wake word → VAD → STT → agent → TTS → barge-in

The pipeline runs in its own thread with the following flow:
1. AudioManager captures mic audio continuously
2. HALT listener checks every frame (parallel, highest priority)
3. WakeWord detector checks every frame
4. On wake word: VAD gates audio collection
5. On speech end: STT transcribes the collected audio
6. Voice auth verifies the speaker
7. Agent processes the request (with 600ms filler timeout)
8. TTS synthesizes the response (sentence-level streaming)
9. During TTS playback: VAD monitors for barge-in

Target: <800ms first-word latency in cloud mode.
"""

from __future__ import annotations

import collections
import queue
import re
import threading
import time

import httpx
import numpy as np
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.voice.audio import AudioManager, get_audio_manager
from archer.voice.wake_word import WakeWordDetector
from archer.voice.vad import VoiceActivityDetector
from archer.voice.stt import STTService
from archer.voice.tts import TTSService
from archer.voice.halt import HaltListener
from archer.voice.auth import VoiceAuthenticator


class VoicePipelineState:
    """Tracks the current state of the voice pipeline."""
    IDLE = "idle"
    LISTENING = "listening"       # Wake word detected, collecting speech
    PROCESSING = "processing"     # STT + agent call in progress
    SPEAKING = "speaking"         # TTS playback
    ERROR = "error"


class VoicePipeline:
    """
    Orchestrates the complete voice pipeline.

    This is the integration layer that coordinates all voice components.
    It runs in its own background thread and communicates with the rest
    of the system exclusively through the event bus.
    """

    # How long to keep listening after the wake word (or after ARCHER finishes
    # speaking, for follow-up turns) before giving up and returning to idle if
    # no speech has started. Kept generous enough to cover the wake-ack phrase
    # playing (~2-3s) plus reaction time.
    _NO_SPEECH_TIMEOUT_SECONDS: float = 10.0

    def __init__(self, agent_callback=None, agent_streaming_callback=None) -> None:
        """
        Initialize the voice pipeline.

        Args:
            agent_callback: Function that takes a text query and returns
                          a response string. Signature: (str) -> str
            agent_streaming_callback: Generator function that takes a text query
                          and yields sentences as they arrive from the LLM.
                          Signature: (str) -> Generator[str, None, None]
        """
        self._config = get_config()
        self._bus = get_event_bus()

        # Components
        self._audio = get_audio_manager()
        self._wake_word = WakeWordDetector()
        self._vad = VoiceActivityDetector()
        self._stt = STTService()
        self._tts = TTSService()
        self._halt = HaltListener()
        self._auth = VoiceAuthenticator()

        # Agent callbacks
        self._agent_callback = agent_callback
        self._agent_streaming_callback = agent_streaming_callback

        # Pre-cached filler audio (generated on first use, then cached)
        self._filler_cache: dict[str, tuple[bytes, int]] = {}

        # State
        self._state = VoicePipelineState.IDLE
        self._running = threading.Event()
        self._halted = threading.Event()
        self._pipeline_thread: threading.Thread | None = None

        # Guards against a false-positive wake-word re-detection (or a
        # rapid double wake) queuing a second acknowledgment on top of one
        # already playing — this is not a mic/listening gate, so it doesn't
        # touch barge-in.
        self._wake_ack_playing = threading.Event()

        # Set the instant a genuine barge-in is detected during SPEAKING, so
        # the (now backgrounded) response-speaking thread can notice mid-loop
        # and stop cleanly instead of racing the pipeline loop's own
        # barge-in state transition/cleanup. See _speak_response_streaming
        # and the SPEAKING branch of _pipeline_loop.
        self._barge_in_event = threading.Event()

        # Self-echo rejection for barge-in (see SPEAKING branch below and
        # _is_self_echo). Without real acoustic echo cancellation, open
        # speakers mean the mic hears ARCHER's own voice — confirmed live:
        # it was transcribing its own filler phrases back as if the user
        # said them, then responding to itself in a runaway loop. Rather
        # than instantly interrupting on any detected speech, a short
        # snippet is buffered and transcribed first, then checked against
        # what ARCHER is currently saying before committing to a real
        # interrupt.
        self._barge_check_buffer: list[bytes] = []
        self._barge_check_heard_speech: bool = False
        self._barge_check_silence_frames: int = 0
        self._barge_check_start: float = 0.0
        # Running text of the response currently being spoken, updated
        # sentence-by-sentence by _speak_response_streaming, and the
        # previous response's text (covers a barge-in landing right at a
        # response's tail end). Compared against transcribed barge-in
        # snippets to reject self-hearing.
        self._current_speaking_text: str = ""
        self._last_spoken_text: str = ""

        # Audio collection buffer (for collecting speech frames)
        self._speech_buffer: list[bytes] = []

        # Rolling buffer discarded on wake word detection (prevents wake word
        # phrase from leaking into the speech buffer and triggering early STT).
        self._pre_buffer: collections.deque[bytes] = collections.deque(maxlen=33)
        self._heard_speech: bool = False
        self._silence_frames: int = 0
        self._listen_start: float = 0.0

        # Monotonically increasing turn counter. Bumped at the start of
        # every new turn (_process_utterance for voice, and internally by
        # _speak_response_streaming for callers that don't pass one, e.g.
        # the text-input path). Added 2026-09-17 after Col reported ARCHER
        # "keeps talking, hears itself, and keeps going" after a barge-in,
        # and separately a log showing self._state read IDLE at a moment
        # TTS chunks were still actively being emitted.
        #
        # Root cause: self._state (plus the vad/speech-buffer/listen-start
        # bookkeeping) is mutated from BOTH the main _pipeline_loop thread
        # AND each turn's own background "SpeakResponse" thread, with
        # nothing stopping two turns' threads from being alive at once. A
        # slow barge-in confirmation (STT round trip, ~150ms-1s+) on the
        # main thread can race a SpeakResponse thread that's naturally
        # finishing at the same moment; whichever thread's state write
        # landed last won, regardless of which turn was actually still
        # audible. That explains both symptoms: ARCHER's own audio still
        # playing while state had already flipped to LISTENING with no
        # self-echo guard active (the LISTENING branch's raw VAD has none —
        # by design, see _is_self_echo's include_recent_response comment),
        # and self._state reading IDLE mid-playback when an early-exit
        # branch of a *newer* _process_utterance call raced a *previous*
        # turn's still-finishing SpeakResponse thread.
        #
        # Every SpeakResponse thread now captures the turn id it started
        # with and checks it against self._turn_seq before touching any
        # shared state at each checkpoint -- a stale thread (superseded by
        # a newer turn) just exits quietly instead of racing.
        self._turn_seq: int = 0
        self._state_lock = threading.Lock()

        # The agent-streaming generator currently in flight for the active
        # turn's UtteranceWorker (or the text-input equivalent), if any.
        # Added 2026-09-17 after finding the real explanation for "it still
        # isn't responding to questions": CoreAgent.process_turn_streaming
        # holds a single GLOBAL lock (_turn_lock) for its entire duration,
        # released only once its generator is fully exhausted. When a turn
        # got superseded (barge-in, or the 30s hard-cap firing a new
        # utterance) nothing ever told that turn's worker thread to stop --
        # it kept calling `for sentence in gen: ...` in the background,
        # fully unaware nobody was listening anymore, which meant CoreAgent
        # kept the lock held the ENTIRE time that orphaned call was still
        # running. Every subsequent turn then had to wait behind it (up to
        # CoreAgent's own 60s acquire timeout) before it could even start --
        # a cascading pile-up that explains why later turns took *longer*,
        # not shorter, and why a real answer, even once generated, kept
        # racing (and losing) against the next superseding trigger.
        # _process_utterance now closes this out the instant a new turn
        # starts, which throws GeneratorExit into the old generator at
        # wherever it's suspended, unwinding it through CoreAgent's
        # streaming loop and releasing _turn_lock immediately instead of
        # whenever Ollama happens to finish on its own.
        self._active_agent_gen = None

        # Register HALT handler
        self._bus.subscribe_halt(self._on_halt)

        # Register text input handler
        self._bus.subscribe(EventType.GUI_TEXT_INPUT, self._on_text_input)

    def initialize(self) -> None:
        """Initialize all voice pipeline components."""
        logger.info("Initializing voice pipeline...")

        try:
            self._wake_word.initialize()
        except Exception as e:
            logger.warning(f"Wake word initialization failed (non-fatal): {e}")

        try:
            self._halt.initialize()
        except Exception as e:
            logger.warning(f"HALT listener initialization failed (non-fatal): {e}")

        try:
            self._auth.initialize()
        except Exception as e:
            logger.warning(f"Voice auth initialization failed (non-fatal): {e}")

        logger.info("Voice pipeline initialized.")

    def start(self) -> None:
        """Start the voice pipeline in a background thread."""
        if self._running.is_set():
            logger.warning("Voice pipeline already running.")
            return

        self._running.set()
        self._audio.start_capture()

        self._pipeline_thread = threading.Thread(
            target=self._pipeline_loop,
            name="VoicePipeline",
            daemon=True,
        )
        self._pipeline_thread.start()
        logger.info("Voice pipeline started.")

        self._bus.publish(Event(
            type=EventType.SYSTEM_START,
            source="voice_pipeline",
        ))

    def stop(self) -> None:
        """Stop the voice pipeline."""
        self._running.clear()
        self._audio.shutdown()

        if self._pipeline_thread is not None:
            self._pipeline_thread.join(timeout=5.0)
            self._pipeline_thread = None

        logger.info("Voice pipeline stopped.")

    def _pipeline_loop(self) -> None:
        """
        Main pipeline loop. Runs in a dedicated thread.

        Flow:
        1. Read audio chunk from mic
        2. Feed to HALT listener (always, highest priority)
        3. Feed to wake word detector (when idle)
        4. Feed to VAD (when listening)
        5. On speech end → process utterance
        """
        logger.info("Pipeline loop started.")

        while self._running.is_set():
            try:
                # Get next audio chunk
                audio_chunk = self._audio.get_audio_chunk(timeout=0.1)
                if audio_chunk is None:
                    continue

                # --- HALT check (always runs, parallel, highest priority) ---
                self._halt.process_audio(audio_chunk)

                if self._halted.is_set():
                    self._halted.clear()
                    self._set_state(VoicePipelineState.IDLE)
                    self._speech_buffer.clear()
                    self._barge_check_buffer.clear()
                    self._barge_check_heard_speech = False
                    self._barge_check_silence_frames = 0
                    self._vad.reset()
                    self._wake_word.reset()
                    continue

                # --- State machine ---
                if self._state == VoicePipelineState.IDLE:
                    # Waiting for wake word — keep a rolling buffer of recent audio
                    self._pre_buffer.append(audio_chunk)

                    detected = self._wake_word.process_audio(audio_chunk)
                    if detected:
                        self._set_state(VoicePipelineState.LISTENING)
                        self._vad.reset()
                        self._speech_buffer.clear()
                        self._heard_speech = False  # VAD hasn't detected speech yet
                        self._silence_frames = 0    # Consecutive silent frames after speech
                        self._listen_start = time.monotonic()
                        self._pre_buffer.clear()    # Discard wake word audio
                        logger.info("🎤 Wake word detected — listening...")
                        self._play_wake_ack()

                        self._bus.publish(Event(
                            type=EventType.WAKE_WORD_DETECTED,
                            source="voice_pipeline",
                        ))

                elif self._state == VoicePipelineState.LISTENING:
                    # Also check wake word if no speech has started yet
                    if not self._heard_speech:
                        if self._wake_word.process_audio(audio_chunk):
                            logger.info("🎤 Wake word detected during listening — resetting follow-up listener...")
                            self._play_wake_ack()
                            self._vad.reset()
                            self._speech_buffer.clear()
                            self._heard_speech = False
                            self._silence_frames = 0
                            self._listen_start = time.monotonic()
                            self._bus.publish(Event(
                                type=EventType.WAKE_WORD_DETECTED,
                                source="voice_pipeline",
                            ))
                            continue

                    # Ignore mic input entirely while ARCHER's own audio is
                    # still physically playing (the wake-ack that was just
                    # triggered, or the ack from a follow-up wake-word
                    # re-trigger above). Added 2026-09-17 after Col's log
                    # showed every single STT transcript coming back with
                    # ARCHER's own wake-ack phrase glued onto the front of
                    # (or entirely in place of) the real question -- e.g.
                    # "what's up, I'm listening. What's your capabilities
                    # and functions briefly?" and, on a later turn, "What's
                    # on your mind? Are you still checking on that
                    # question?" (the first sentence in each is ARCHER's
                    # own wake-ack, self-heard).
                    #
                    # Root cause: unlike the SPEAKING branch's barge-in
                    # check (which buffers, transcribes, and vetoes against
                    # self-echo before ever trusting a VAD hit), this
                    # LISTENING branch fed every mic chunk straight into the
                    # VAD and speech buffer below with NO gate at all. Since
                    # there's no acoustic echo cancellation (open speakers),
                    # the mic picks up the wake-ack playing through the
                    # speaker just as readily as it picks up the user's
                    # actual voice, and the VAD has no way to tell them
                    # apart -- so the entire ~2-3s wake-ack got folded into
                    # self._speech_buffer as if it were the start of the
                    # user's own utterance, with no silence gap separating
                    # it from whatever the user said next.
                    #
                    # Also pushes _listen_start forward so the no-speech
                    # timeout clock doesn't run down while ARCHER itself is
                    # the only thing making noise.
                    if self._wake_ack_playing.is_set() or self._audio.is_playing:
                        self._listen_start = time.monotonic()
                        continue

                    # Collect ALL audio while listening (speech + pauses).
                    # The STT model handles noise/silence far better than
                    # trying to gate audio frames ourselves.
                    is_speech = self._vad.process_audio(audio_chunk)

                    # Use the RAW per-frame result to track speech/silence.
                    if is_speech:
                        self._heard_speech = True
                        self._silence_frames = 0
                    elif self._heard_speech:
                        self._silence_frames += 1

                    if self._heard_speech:
                        # Always buffer audio once speech has started
                        self._speech_buffer.append(audio_chunk)

                        # End utterance after ~1.0 seconds of continuous silence
                        if self._silence_frames >= 33:
                            self._process_utterance()
                            # _process_utterance() blocks THIS thread (the
                            # pipeline loop) until the agent's first sentence
                            # is ready -- fine for a fast reply, but a slow
                            # local-model turn (confirmed 2026-09-17: visual
                            # Q&A regularly takes 50-90s) means it can return
                            # 30+ seconds after self._listen_start. Nothing
                            # above resets self._heard_speech/_listen_start
                            # while blocked, so falling through to the "Hard
                            # timeout" check below on THIS SAME iteration was
                            # firing a SECOND, spurious _process_utterance()
                            # call every single time -- bumping _turn_seq,
                            # stopping playback, and closing the turn we just
                            # dispatched before it ever got spoken (visible
                            # in the logs as "SpeakResponse for turn N
                            # superseded by turn N+1" on every slow turn,
                            # every time). continue skips the now-stale
                            # LISTENING-only checks below; state has already
                            # moved to PROCESSING inside _process_utterance().
                            continue

                    # Hard timeout: cap utterance at 30 seconds
                    elapsed = time.monotonic() - self._listen_start
                    if self._heard_speech and elapsed > 30.0:
                        logger.warning("Max utterance duration reached (30s) — processing")
                        self._process_utterance()
                        continue

                    # Timeout: if no speech within N seconds of wake word, go idle
                    if not self._heard_speech and (time.monotonic() - self._listen_start) > self._NO_SPEECH_TIMEOUT_SECONDS:
                        logger.info("No speech after wake word — returning to idle")
                        self._set_state(VoicePipelineState.IDLE)
                        self._speech_buffer.clear()

                elif self._state == VoicePipelineState.SPEAKING:
                    # During TTS playback — monitor for barge-in. This branch
                    # only actually runs now because _speak_response_streaming
                    # is dispatched on its own thread (see _process_utterance)
                    # instead of blocking this loop for the whole playback —
                    # previously this code was unreachable in practice, since
                    # a blocking play_audio() call on THIS thread meant the
                    # loop never got back around to check it.
                    #
                    # Without real acoustic echo cancellation (open speakers,
                    # no earbuds), the mic hears ARCHER's own voice, so a raw
                    # VAD hit is NOT trusted as a genuine interrupt on its
                    # own — confirmed live that doing so causes ARCHER to
                    # transcribe and respond to its own filler phrases in a
                    # runaway loop. Instead: buffer the detected speech,
                    # transcribe it once it ends, and only actually interrupt
                    # if it does NOT match what ARCHER itself is currently
                    # saying (or a known filler/wake-ack phrase). This adds
                    # roughly the STT round-trip (~150-300ms warm) plus the
                    # same ~1s silence-termination used elsewhere as latency
                    # before a genuine interruption takes effect — audio
                    # keeps playing during that check — but a real
                    # interruption still lands within about a second, and
                    # self-hearing no longer derails the conversation.
                    is_speech = self._vad.process_audio(audio_chunk)

                    if is_speech:
                        self._barge_check_heard_speech = True
                        self._barge_check_silence_frames = 0
                        if not self._barge_check_buffer:
                            self._barge_check_start = time.monotonic()
                    elif self._barge_check_heard_speech:
                        self._barge_check_silence_frames += 1

                    if self._barge_check_heard_speech:
                        self._barge_check_buffer.append(audio_chunk)

                    utterance_ended = self._barge_check_heard_speech and (
                        self._barge_check_silence_frames >= 33  # ~1.0s silence
                        or (time.monotonic() - self._barge_check_start) > 6.0  # hard cap
                    )

                    if utterance_ended:
                        snippet = b"".join(self._barge_check_buffer)
                        self._barge_check_buffer.clear()
                        self._barge_check_heard_speech = False
                        self._barge_check_silence_frames = 0

                        snippet_text = ""
                        if len(snippet) >= 3200:  # ~100ms minimum, same floor as _process_utterance
                            try:
                                # publish_event=False: this is a speculative probe
                                # to decide whether to interrupt, not a real user
                                # utterance. Publishing STT_FINAL here made the
                                # GUI show every probe (including ones later
                                # discarded as self-echo, or blank silence) as a
                                # "You:" line. The genuine follow-up utterance
                                # gets transcribed — and published — normally
                                # once we're back in LISTENING.
                                snippet_text = self._stt.transcribe(snippet, publish_event=False)
                            except Exception as e:
                                logger.warning(f"Barge-in check STT failed: {e}")

                        # Two independent vetoes, either one blocks the interrupt:
                        # content match (does it transcribe to ARCHER's own
                        # words?) and acoustic match (does the mic snippet's
                        # energy shape correlate with what the speakers were
                        # actually outputting during this window, via WASAPI
                        # loopback?). The acoustic check catches things content
                        # matching can't — e.g. a Windows notification chime,
                        # which doesn't transcribe to any known phrase but IS
                        # just the mic hearing the speakers.
                        is_echo = bool(snippet_text) and self._is_self_echo(snippet_text)
                        if not is_echo:
                            is_echo = self._is_acoustic_bleed(
                                snippet, self._barge_check_start, time.monotonic()
                            )

                        if snippet_text and not is_echo:
                            logger.info(f"🔇 Barge-in confirmed (not self-echo): '{snippet_text}' — stopping TTS")
                            self._barge_in_event.set()
                            self._audio.stop_playback()
                            self._tts.cancel()
                            self._bus.publish(Event(
                                type=EventType.BARGE_IN,
                                source="voice_pipeline",
                                data={"text": snippet_text},
                            ))
                            self._set_state(VoicePipelineState.LISTENING)
                            self._speech_buffer.clear()
                            self._vad.reset()
                            self._heard_speech = False
                            self._silence_frames = 0
                            self._listen_start = time.monotonic()
                        elif snippet_text:
                            logger.debug(f"Barge-in check discarded as self-echo: '{snippet_text}'")

            except Exception as e:
                logger.error(f"CRITICAL ERROR in VoicePipeline loop: {e}", exc_info=True)
                old_state = self._state
                self._speech_buffer.clear()
                try:
                    self._vad.reset()
                except Exception:
                    pass
                try:
                    self._wake_word.reset()
                except Exception:
                    pass

                self._set_state(VoicePipelineState.ERROR)
                self._bus.publish(Event(
                    type=EventType.SYSTEM_ERROR,
                    source="voice_pipeline",
                    data={
                        "message": f"Voice pipeline error: {e}",
                        "exception": str(e),
                        "old_state": old_state,
                    },
                ))
                time.sleep(0.5)
                self._set_state(VoicePipelineState.IDLE)

    def _process_utterance(self) -> None:
        """
        Process a complete speech utterance through auth + STT → agent → TTS.

        The filler timer starts the instant speech ends so the user hears
        acknowledgement quickly even while auth, STT, and the agent stream
        are still running.  The sentence queue bridges all stages:

        1. Background worker: auth → STT → agent streaming → sentences into queue
        2. Main thread: wait up to filler_timeout_ms for the first sentence
           → if nothing arrives, play a cached filler clip instantly
           → then stream sentences to TTS as they arrive
        """
        # New turn starting -- see _turn_seq comment in __init__. Bump the
        # counter FIRST, before anything else, so any still-finishing
        # SpeakResponse thread from a previous turn (e.g. one delayed by a
        # slow barge-in STT check) sees it's been superseded on its next
        # checkpoint and stops touching shared state instead of racing this
        # turn's own updates. Also defensively stop any leftover audio from
        # that previous turn -- a new turn starting means the user was just
        # talking again, so nothing old should still be audible underneath it.
        self._turn_seq += 1
        my_turn = self._turn_seq
        self._audio.stop_playback()
        self._tts.cancel()

        # Cancel any previous turn's still-running agent generator -- see
        # _active_agent_gen comment in __init__. Without this, an
        # abandoned turn's CoreAgent call keeps CoreAgent's global
        # _turn_lock held in the background until IT finishes on its own,
        # which is what was actually starving every later turn.
        stale_gen = self._active_agent_gen
        self._active_agent_gen = None
        if stale_gen is not None:
            try:
                stale_gen.close()
            except Exception as e:
                logger.debug(f"Closing superseded agent generator failed (non-fatal): {e}")

        self._set_state(VoicePipelineState.PROCESSING)

        # Combine speech buffer into single audio
        audio_data = b"".join(self._speech_buffer)
        self._speech_buffer.clear()

        if len(audio_data) < 3200:  # Less than ~100ms of audio — too short
            logger.debug("Audio too short, ignoring.")
            self._set_state(VoicePipelineState.IDLE)
            return

        if self._agent_streaming_callback is None and self._agent_callback is None:
            logger.warning("No agent callback registered — echoing input")
            self._speak_response_streaming(iter(["I heard you, but no agent is available."]), turn_id=my_turn)
            return

        # --- Sentence queue bridges the worker → main thread ---
        sentence_queue: queue.Queue[str | None] = queue.Queue()
        # Shared flag so main thread can check if the worker aborted early
        worker_aborted = threading.Event()
        # Distinguishes "STT came back empty" (likely a VAD/audio glitch —
        # e.g. an input-overflow blip right as playback stops, which
        # webrtcvad briefly mistakes for speech) from a real HALT. An empty
        # result shouldn't cost the user their whole follow-up window; only
        # a HALT should force an immediate return to idle.
        stt_was_empty = threading.Event()

        # Populated by _worker (via a further background thread, so it
        # doesn't delay the real agent call below) once STT text is
        # confirmed genuine. Raced against filler_timeout_ms below -- see
        # _generate_contextual_filler.
        contextual_filler: dict[str, str] = {}
        contextual_filler_done = threading.Event()

        def _worker():
            """Run auth + STT + agent in one shot, feeding sentences into the queue."""
            try:
                # --- Voice Authentication ---
                auth_audio = audio_data[:self._config.sample_rate * 2 * 2]
                is_verified, similarity = self._auth.verify(auth_audio)

                # --- Speech-to-Text ---
                # publish_event=False: don't show this on the GUI yet — it
                # might still turn out to be self-echo (ARCHER hearing its
                # own trailing audio) or empty. Publish STT_FINAL manually
                # below, only once the text has cleared both checks, so the
                # conversation panel never flashes a "You:" line for text
                # the user didn't actually say.
                text = self._stt.transcribe(audio_data, publish_event=False)

                if not text or text.strip() == "":
                    logger.debug("STT returned empty text, ignoring.")
                    stt_was_empty.set()
                    worker_aborted.set()
                    return

                logger.info(f"📝 STT: '{text}'")

                # --- Self-echo check ---
                # Catches ARCHER hearing its own trailing wake-ack/filler
                # audio right as it transitions into LISTENING. Deliberately
                # does NOT compare against ARCHER's own recent response
                # content here (include_recent_response=False) — confirmed
                # live that doing so silently ate genuine replies whenever
                # they echoed words from ARCHER's own last sentence (e.g.
                # ARCHER: "did you mean X?" / user: "yes, X" — high word
                # overlap with what ARCHER JUST said, but obviously real
                # speech). That comparison only belongs in the SPEAKING-
                # branch barge-in check, where actual acoustic bleed is
                # physically happening in real time. Treated the same as an
                # empty STT result — resume listening within the window
                # rather than acting on it.
                if self._is_self_echo(text, include_recent_response=False):
                    # INFO, not DEBUG (2026-10-09): a discarded turn means
                    # the user gets no reply at all, so it must be visible
                    # in the console when it happens.
                    logger.info(f"Ignoring STT result as possible self-echo (ARCHER hearing itself): '{text}'")
                    stt_was_empty.set()
                    worker_aborted.set()
                    return

                # Cleared both checks — this is genuine user speech. Now
                # tell the GUI, so "You:" only ever shows text the user
                # actually said.
                self._bus.publish(Event(
                    type=EventType.STT_FINAL,
                    source="voice_pipeline",
                    data={"text": text},
                ))

                # Kick off contextual-filler generation now, on its own
                # thread, in parallel with the real agent call below --
                # it's racing filler_timeout_ms (see the main-thread wait
                # further down), not blocking this worker's own progress.
                def _filler_worker():
                    result = self._generate_contextual_filler(text)
                    if result:
                        contextual_filler["text"] = result
                    contextual_filler_done.set()

                threading.Thread(target=_filler_worker, daemon=True, name="ContextualFiller").start()

                # --- HALT check ---
                if self._halt.check_text_for_halt(text):
                    worker_aborted.set()
                    return

                # --- Guest mode ---
                if not is_verified:
                    # Build guest response directly
                    response = self._get_guest_response(text)
                    self._bus.publish(Event(
                        type=EventType.AUTH_GUEST,
                        source="voice_pipeline",
                        data={"query": text, "response": response},
                    ))
                    sentence_queue.put(response)
                    return

                # --- Stream agent sentences ---
                if self._agent_streaming_callback is not None:
                    gen = self._agent_streaming_callback(text)
                    # Tracked so a LATER turn can cancel this one if it's
                    # still running when superseded -- see _active_agent_gen
                    # comment in __init__.
                    self._active_agent_gen = gen
                    try:
                        for sentence in gen:
                            sentence_queue.put(sentence)
                    finally:
                        if hasattr(gen, "close"):
                            try:
                                gen.close()
                            except Exception:
                                pass
                        # Only clear if it's still ours -- a newer turn may
                        # have already superseded and replaced/cleared this.
                        if self._active_agent_gen is gen:
                            self._active_agent_gen = None
                else:
                    result = self._agent_callback(text)
                    for sentence in self._split_into_sentences(result):
                        sentence_queue.put(sentence)

            except Exception as e:
                logger.error(f"Utterance processing failed: {e}")
                self._bus.publish(Event(
                    type=EventType.SYSTEM_ERROR,
                    source="voice_pipeline",
                    data={"message": f"Utterance processing failed: {e}"}
                ))
                sentence_queue.put("I'm sorry, I encountered an error.")
            finally:
                sentence_queue.put(None)  # Sentinel

        threading.Thread(target=_worker, daemon=True, name="UtteranceWorker").start()

        # --- Filler timeout starts NOW (overlaps with auth + STT + agent) ---
        try:
            first = sentence_queue.get(
                timeout=self._config.filler_timeout_ms / 1000.0
            )
        except queue.Empty:
            first = None

        # Worker aborted (empty STT, HALT, etc.) — no response needed
        if worker_aborted.is_set():
            self._resume_listening_or_idle(stt_was_empty.is_set())
            return

        # Stream ended immediately with no sentences
        if first is None and not sentence_queue.empty():
            self._set_state(VoicePipelineState.IDLE)
            return

        # Play filler if no first sentence arrived in time
        if first is None:
            # Give the contextual filler (kicked off in _worker as soon as
            # STT text was confirmed genuine) a brief extra grace window to
            # land, rather than jumping straight to the generic bank. Kept
            # short and on top of the timeout that already just elapsed --
            # this can't be allowed to grow into its own long wait, that
            # would defeat the entire point of a filler.
            contextual_filler_done.wait(timeout=0.6)
            filler_text = contextual_filler.get("text") or self._tts.get_filler_text()
            is_contextual = "text" in contextual_filler
            logger.info(f"Playing filler ({'contextual' if is_contextual else 'generic'}): '{filler_text}'")

            self._bus.publish(Event(
                type=EventType.FILLER_PLAY,
                source="voice_pipeline",
                data={"text": filler_text},
            ))

            # Contextual text is unique every time -- nothing to cache --
            # so it needs a live synth call, unlike the pre-cached generic
            # bank (see precache_fillers).
            #
            # reset_cancel() here (2026-09-19): this turn's own
            # self._tts.cancel() call, a few dozen lines up in
            # _process_utterance, unconditionally sets TTS's cancellation
            # flag to stop a PREVIOUS turn's straggling audio -- but that
            # flag is only ever cleared lazily, by whichever synthesize()
            # call happens to run next (see reset_cancel's own docstring for
            # the 2026-09-17 incident this same pattern already fixed once,
            # for _speak_response_streaming's first sentence). A CONTEXTUAL
            # filler's synthesize() call right below is EARLIER than that
            # fix's reset point, so it was the one silently eating the stale
            # flag and returning None instead -- confirmed live: the filler
            # text logged and published normally, but no audio ever played,
            # because a cached GENERIC filler skips synthesize() entirely
            # (see _get_cached_filler) and so never hit this, while a
            # contextual one always does.
            if is_contextual:
                self._tts.reset_cancel()
            filler_audio = self._tts.synthesize(filler_text) if is_contextual else self._get_cached_filler(filler_text)
            if filler_audio:
                audio_bytes, sample_rate = filler_audio
                self._audio.play_audio_bytes(audio_bytes, sample_rate)
            elif is_contextual:
                logger.warning(
                    f"Contextual filler synthesis returned no audio for "
                    f"'{filler_text[:60]}' -- filler text was logged/published "
                    f"but nothing was actually spoken."
                )

            # Now wait for the actual first sentence
            first = sentence_queue.get()

            # Check again in case worker aborted while filler was playing
            if worker_aborted.is_set():
                self._resume_listening_or_idle(stt_was_empty.is_set())
                return

        if first is None:
            self._set_state(VoicePipelineState.IDLE)
            return

        # Build a generator that yields first + remaining sentences
        def sentence_stream():
            yield first
            while True:
                sentence = sentence_queue.get()
                if sentence is None:
                    break
                yield sentence

        # Dispatched on its own thread rather than called directly: this
        # function runs on the main pipeline loop thread (called from the
        # LISTENING branch of _pipeline_loop), and _speak_response_streaming
        # blocks for the full duration of playback. Calling it inline here
        # would freeze the very loop that's supposed to be watching for
        # barge-in during SPEAKING, making that check unreachable in
        # practice — which is exactly what was happening before this fix.
        # The text-input path (_call_agent_with_filler) already runs on its
        # own thread via _on_text_input, so this brings voice-triggered
        # responses in line with it.
        threading.Thread(
            target=self._speak_response_streaming,
            args=(sentence_stream(),),
            kwargs={"turn_id": my_turn},
            daemon=True,
            name="SpeakResponse",
        ).start()

    def _is_self_echo(self, text: str, include_recent_response: bool = True) -> bool:
        """
        Check whether transcribed audio is actually ARCHER hearing its own
        voice (open speakers, no acoustic echo cancellation) rather than
        genuine speech from the user. Confirmed live: without this check,
        ARCHER would transcribe its own filler/wake-ack phrases back as if
        the user said them and respond to itself in a runaway loop.

        Compares word overlap against known filler/wake-ack phrases (a
        small fixed list) and, when include_recent_response=True, whatever
        ARCHER is currently saying / just finished saying. Not real AEC —
        just a content-based sanity check — but it's enough to kill
        exact-ish self-repeats without adding audio DSP work.

        include_recent_response must be False for the main LISTENING-path
        check (_process_utterance) — confirmed live this was silently
        eating genuine replies: ARCHER asked "did you mean X?", the user
        answered "yes, X", and that answer shared enough words with
        ARCHER's OWN just-spoken question to look like self-echo and get
        discarded with no response at all. Comparing against ARCHER's own
        recent content only makes sense while ARCHER is actively speaking
        and real acoustic bleed is physically possible — i.e. the SPEAKING-
        branch barge-in check, which is the only caller that should pass
        (or default to) True. Filler/wake-ack phrases are safe to always
        check — nobody naturally says "yeah, what's up, I'm listening."
        """
        from archer.voice.tts import FILLER_PHRASES, WAKE_ACK_PHRASES

        def _seq(s: str) -> list[str]:
            return re.findall(r"[a-z0-9']+", s.lower())

        def _words(s: str) -> set[str]:
            return set(_seq(s))

        def _is_contiguous_run(needle: list[str], haystack: list[str]) -> bool:
            n = len(needle)
            if n == 0 or n > len(haystack):
                return False
            return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))

        snippet_words = _words(text)
        if not snippet_words:
            return True  # nothing meaningful transcribed — don't act on it

        candidates = list(FILLER_PHRASES) + list(WAKE_ACK_PHRASES)
        if include_recent_response:
            candidates = [self._current_speaking_text, self._last_spoken_text] + candidates

        # 2026-10-09: the old rule (60% of the transcribed words appear
        # anywhere in a known phrase) threw away real questions. Confirmed
        # live: "What do you see?" shares "what", "do", "you" with the
        # wake-ack "Yes sir, what can I do for you?" (3 of 4 words), so it
        # was silently discarded as ARCHER hearing itself and Col got no
        # reply at all. Now it only counts as an echo if EITHER the words
        # appear in the same order as a run inside a known phrase (how a
        # trailing echo like "do for you" actually sounds), OR the overlap
        # is high in both directions (most of the known phrase came back,
        # e.g. a slightly garbled full echo). Both are strictly narrower
        # than the old rule, so nothing new is discarded.
        snippet_seq = _seq(text)
        for candidate in candidates:
            if not candidate:
                continue
            candidate_words = _words(candidate)
            if not candidate_words:
                continue
            if _is_contiguous_run(snippet_seq, _seq(candidate)):
                return True
            overlap = len(snippet_words & candidate_words)
            if (overlap / len(snippet_words) >= 0.6
                    and overlap / len(candidate_words) >= 0.6):
                return True

        return False

    def _is_acoustic_bleed(self, mic_pcm: bytes, window_start: float, window_end: float) -> bool:
        """
        WASAPI-loopback-based veto for barge-in/self-hearing — independent
        of what the audio transcribes to. _is_self_echo only catches mic
        pickup that transcribes close to a KNOWN phrase (ARCHER's own
        script, fillers, wake-acks); it has no way to recognize something
        like a Windows notification chime, since that doesn't match any
        known phrase but is still just the mic hearing the speakers.

        This instead compares the buffered mic snippet's short-time energy
        envelope against a loopback recording of whatever the speakers
        actually output during that same window (see AudioManager). A high
        correlation means the mic snippet IS what the speakers played —
        not independent speech — regardless of content. Best-effort: if
        loopback capture isn't available on this system, returns False and
        the content-based check remains the only line of defense.
        """
        if not self._audio.loopback_available:
            return False
        try:
            mic = np.frombuffer(mic_pcm, dtype=np.int16).astype(np.float64)
            bin_seconds = self._audio.loopback_bin_seconds
            bin_samples = int(self._config.sample_rate * bin_seconds)
            if bin_samples <= 0 or len(mic) < bin_samples * 3:
                return False  # too short to form a meaningful envelope

            n_bins = len(mic) // bin_samples
            mic_env = np.array([
                np.sqrt(np.mean(mic[i * bin_samples:(i + 1) * bin_samples] ** 2))
                for i in range(n_bins)
            ])

            # Pad the window slightly — mic hears the speaker with some
            # acoustic + processing lag, so the matching loopback energy
            # may trail just after window_start.
            loopback_env = self._audio.get_loopback_envelope(window_start - 0.05, window_end + 0.1)
            if not loopback_env or len(loopback_env) < 3:
                return False

            loopback_env = np.asarray(loopback_env, dtype=np.float64)

            def _norm(a: np.ndarray) -> np.ndarray:
                a = a - a.mean()
                std = a.std()
                return a / std if std > 1e-9 else a

            m = _norm(mic_env)
            if len(loopback_env) < len(m):
                return False

            best_corr = 0.0
            max_lag = max(0, len(loopback_env) - len(m))
            for lag in range(0, max_lag + 1):
                seg = _norm(loopback_env[lag:lag + len(m)])
                if len(seg) != len(m):
                    continue
                corr = float(np.mean(m * seg))
                if corr > best_corr:
                    best_corr = corr

            # Threshold is a starting point, same as _is_self_echo's 0.6
            # word-overlap figure — may need retuning against live audio.
            if best_corr >= 0.5:
                logger.debug(f"Acoustic-bleed veto: mic/loopback envelope correlation {best_corr:.2f}")
                return True
        except Exception as e:
            logger.debug(f"Acoustic-bleed check failed (non-fatal): {e}")

        return False

    def _resume_listening_or_idle(self, was_empty_stt: bool) -> None:
        """
        Decide what to do after an utterance was discarded (empty STT / HALT
        text check) instead of always snapping back to idle.

        A real HALT is handled entirely by the parallel HALT listener and
        never reaches here with was_empty_stt=True, so this only covers the
        "STT came back empty" case. That can legitimately mean the user
        hasn't started talking yet — e.g. a brief input-overflow glitch
        right as playback stops gets mistaken by webrtcvad for ~1s of
        speech, Whisper's own VAD then strips all of it back out, and we're
        left with an empty transcript within a second of entering LISTENING.
        Snapping straight to idle in that case silently eats the user's
        entire response window. Instead, keep listening as long as we're
        still within the no-speech timeout from when listening started.
        """
        if was_empty_stt and (time.monotonic() - self._listen_start) < self._NO_SPEECH_TIMEOUT_SECONDS:
            logger.debug("Empty STT within listening window — resuming listening instead of going idle.")
            self._set_state(VoicePipelineState.LISTENING)
            self._vad.reset()
            self._speech_buffer.clear()
            self._heard_speech = False
            self._silence_frames = 0
            return

        self._set_state(VoicePipelineState.IDLE)

    def _call_agent_with_filler(self, text: str) -> None:
        """
        Call the agent with streaming sentence-level TTS pipelining.

        Used by text input path (bypasses auth + STT).
        """
        if self._agent_streaming_callback is None and self._agent_callback is None:
            logger.warning("No agent callback registered — echoing input")
            self._speak_response_streaming(iter([f"I heard you say: {text}"]), text)
            return

        sentence_queue: queue.Queue[str | None] = queue.Queue()

        def agent_worker():
            try:
                if self._agent_streaming_callback is not None:
                    gen = self._agent_streaming_callback(text)
                    # See _active_agent_gen comment in __init__ -- same
                    # orphaned-generator/lock-starvation concern applies to
                    # the text-input path.
                    self._active_agent_gen = gen
                    try:
                        for sentence in gen:
                            sentence_queue.put(sentence)
                    finally:
                        if hasattr(gen, "close"):
                            try:
                                gen.close()
                            except Exception:
                                pass
                        if self._active_agent_gen is gen:
                            self._active_agent_gen = None
                else:
                    result = self._agent_callback(text)
                    for sentence in self._split_into_sentences(result):
                        sentence_queue.put(sentence)
            except Exception as e:
                logger.error(f"Agent call failed: {e}")
                self._bus.publish(Event(
                    type=EventType.SYSTEM_ERROR,
                    source="voice_pipeline",
                    data={"message": f"Agent call failed: {e}"}
                ))
                sentence_queue.put("I'm sorry, I encountered an error.")
            finally:
                sentence_queue.put(None)

        threading.Thread(target=agent_worker, daemon=True).start()

        # Wait for first sentence with filler timeout
        try:
            first = sentence_queue.get(
                timeout=self._config.filler_timeout_ms / 1000.0
            )
        except queue.Empty:
            first = None

        if first is None and not sentence_queue.empty():
            return

        if first is None:
            filler_text = self._tts.get_filler_text()
            logger.info(f"Playing filler: '{filler_text}'")

            self._bus.publish(Event(
                type=EventType.FILLER_PLAY,
                source="voice_pipeline",
                data={"text": filler_text},
            ))

            filler_audio = self._get_cached_filler(filler_text)
            if filler_audio:
                audio_bytes, sample_rate = filler_audio
                self._audio.play_audio_bytes(audio_bytes, sample_rate)

            first = sentence_queue.get()

        if first is None:
            return

        def sentence_stream():
            yield first
            while True:
                sentence = sentence_queue.get()
                if sentence is None:
                    break
                yield sentence

        self._speak_response_streaming(sentence_stream(), text)

    def _generate_contextual_filler(self, user_text: str) -> str | None:
        """
        Ask the LLM for a short, in-context "one moment" acknowledgment
        based on what the user just asked, instead of always falling back
        to the static FILLER_PHRASES bank. Added 2026-09-17 per Col's
        request: "remove the filler words after my turns... they need to
        be contextual sometimes so the cannon [canned] phrases aren't
        always applicable" -- e.g. "Let me think about that" reads oddly
        after "what time is it?".

        Deliberately bypasses CoreAgent entirely and hits Ollama directly
        with a tiny, history-free, tool-free prompt capped at a handful of
        tokens. This is racing the REAL answer for filler_timeout_ms (see
        _process_utterance) -- going through CoreAgent's full pipeline
        (conversation history, memory recall, tool-calling loop) would add
        exactly the latency this is trying to hide. Best-effort: returns
        None on any failure/slowness so the caller falls back to the
        static bank rather than leaving the user in silence.
        """
        try:
            resp = httpx.post(
                f"{self._config.ollama_base_url}/api/chat",
                json={
                    "model": self._config.core_primary_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You briefly acknowledge a request before answering "
                                "it in full a moment later. Reply with ONLY a short, "
                                "natural acknowledgment (5-10 words) that fits what "
                                "was just asked -- e.g. 'Let me check your calendar' "
                                "or 'One sec, pulling that up.' Do not answer the "
                                "question itself. Do not use quotation marks."
                            ),
                        },
                        {"role": "user", "content": user_text},
                    ],
                    "stream": False,
                    "options": {"num_predict": 24},
                },
                timeout=2.5,
            )
            if resp.status_code != 200:
                return None
            content = resp.json().get("message", {}).get("content", "").strip()
            if not content:
                return None

            # Sanity-check against the model ignoring "5-10 words, don't
            # answer the question" and just starting its real answer instead
            # -- confirmed live 2026-09-19: num_predict=24 then truncates
            # that mid-clause, producing something like "Let me check that
            # for you.\n\nI am an AI and do not have memory of..." which is
            # both a bad filler (reads as a real, if garbled, answer) and
            # bad TTS input (embedded blank line). Collapse whitespace and
            # bail out to the generic bank if it's clearly not a short
            # acknowledgment -- better to say nothing contextual than to
            # speak a truncated fragment of the actual response.
            content = " ".join(content.split())
            if len(content.split()) > 14 or len(content) > 90:
                logger.debug(
                    f"Contextual filler ignored length/format instructions "
                    f"('{content[:60]}...') -- falling back to generic bank."
                )
                return None
            return content
        except Exception as e:
            logger.debug(f"Contextual filler generation failed (non-fatal): {e}")
            return None

    def _get_cached_filler(self, filler_text: str) -> tuple[bytes, int] | None:
        """Get a cached filler audio clip, synthesizing on first use."""
        if filler_text in self._filler_cache:
            return self._filler_cache[filler_text]

        # Synthesize and cache for future use
        result = self._tts.synthesize(filler_text)
        if result:
            self._filler_cache[filler_text] = result
        return result

    def precache_fillers(self) -> None:
        """Pre-generate and cache all filler + wake-ack audio clips on startup."""
        from archer.voice.tts import FILLER_PHRASES, WAKE_ACK_PHRASES
        logger.info("Pre-caching filler and wake-ack audio clips...")
        for phrase in FILLER_PHRASES + WAKE_ACK_PHRASES:
            try:
                result = self._tts.synthesize(phrase)
                if result:
                    self._filler_cache[phrase] = result
                    logger.debug(f"Cached filler: '{phrase}'")
            except Exception as e:
                logger.warning(f"Failed to cache filler '{phrase}': {e}")
        logger.info(f"Filler cache ready ({len(self._filler_cache)} clips)")

    def _play_wake_ack(self) -> None:
        """
        Play a brief verbal acknowledgment that the wake word was heard.

        Runs in its own thread — same pattern as the HALT confirmation —
        so it doesn't block the pipeline loop. The orb already signals
        this visually; this gives an audible cue too so the user doesn't
        have to be looking at the screen to know ARCHER is listening.
        """
        # If a wake-ack is already playing, don't stack another one on top
        # of it (e.g. from a rapid double wake-word hit, or a false-positive
        # slipping past the threshold). This only guards re-entrant acks —
        # it doesn't touch mic input, so it has no effect on barge-in.
        if self._wake_ack_playing.is_set():
            return

        def _speak():
            self._wake_ack_playing.set()
            try:
                phrase = self._tts.get_wake_ack_text()

                # Let the GUI conversation panel show what ARCHER is about
                # to say, same as it does for the "One moment..." filler.
                self._bus.publish(Event(
                    type=EventType.WAKE_ACK_PLAY,
                    source="voice_pipeline",
                    data={"text": phrase},
                ))

                result = self._get_cached_filler(phrase)
                if result is None:
                    result = self._tts.synthesize(phrase)
                if result:
                    audio_bytes, sample_rate = result
                    self._audio.play_audio_bytes(audio_bytes, sample_rate)
            except Exception as e:
                logger.warning(f"Wake-ack playback failed (non-critical): {e}")
            finally:
                self._wake_ack_playing.clear()

        threading.Thread(target=_speak, daemon=True, name="WakeAck").start()

    def _speak_response_streaming(
        self, sentences: iter, full_text: str = "", turn_id: int | None = None
    ) -> None:
        """
        Synthesize and play sentences as they arrive from the LLM stream.

        Each sentence is sent to TTS immediately — sentence N plays while
        the LLM generates sentence N+1. This is the key to <800ms latency.

        turn_id: the turn counter value (see _turn_seq in __init__) this
        response belongs to. Callers that don't manage turns themselves
        (text input, guest mode, the no-agent-callback fallback) can omit
        it — a fresh turn is claimed here instead. If a NEWER turn starts
        elsewhere (self._turn_seq no longer equals turn_id) while this is
        still running -- e.g. a slow barge-in STT confirmation raced this
        thread's own natural completion -- every checkpoint below stops
        touching shared pipeline state rather than clobbering whatever the
        newer turn has already set up. Added 2026-09-17; see the _turn_seq
        comment in __init__ for the incident this fixes (ARCHER "keeps
        talking, hears itself" after a barge-in, and self._state observed
        as IDLE while TTS was still actively playing).
        """
        if turn_id is None:
            self._turn_seq += 1
            turn_id = self._turn_seq

        def _stale() -> bool:
            return turn_id != self._turn_seq

        if _stale():
            # INFO, not debug -- the console log Col captures is INFO-level
            # only (see __main__.py's setup_logging), and this is exactly
            # the signal needed to confirm/deny the turn-overlap race live.
            logger.info(
                f"SpeakResponse for turn {turn_id} superseded before it "
                f"started (current turn {self._turn_seq}) — not speaking."
            )
            return

        # Clear any stale flag from a previous turn before this one can
        # possibly be barged into.
        self._barge_in_event.clear()
        self._barge_check_buffer.clear()
        self._barge_check_heard_speech = False
        self._barge_check_silence_frames = 0
        self._current_speaking_text = ""
        # Also clear TTS's own cancellation flag -- _process_utterance()
        # (called at the very start of handling this turn) unconditionally
        # calls self._tts.cancel() to stop a PREVIOUS turn's straggling
        # audio, but that flag is only ever cleared lazily on whichever
        # synthesize() call runs next. Without this reset, THIS turn's own
        # first synthesize() call below eats that stale cancellation and
        # silently drops the first sentence of every response (confirmed
        # live 2026-09-17: only sentence 2+ was ever actually spoken).
        self._tts.reset_cancel()
        self._set_state(VoicePipelineState.SPEAKING)

        collected_text = []

        self._bus.publish(Event(
            type=EventType.AGENT_RESPONSE_START,
            source="voice_pipeline",
            data={"text": full_text},
        ))

        for sentence in sentences:
            if self._halted.is_set() or self._barge_in_event.is_set() or not self._running.is_set() or _stale():
                break

            sentence = sentence.strip()
            if not sentence:
                continue

            collected_text.append(sentence)
            # Keep the running text of what's actually being spoken visible
            # to the SPEAKING branch's self-echo check (see _is_self_echo).
            self._current_speaking_text = " ".join(collected_text)

            result = self._tts.synthesize(sentence)
            if result is None:
                logger.warning(f"TTS synthesis returned None for sentence '{sentence[:30]}...' — skipping sentence.")
                continue

            audio_bytes, sample_rate = result
            if not audio_bytes or len(audio_bytes) == 0:
                logger.warning(f"TTS synthesis returned 0 audio bytes for sentence '{sentence[:30]}...' — skipping sentence.")
                continue

            self._audio.play_audio_bytes(audio_bytes, sample_rate)

        response_text = " ".join(collected_text)
        self._last_spoken_text = response_text
        self._current_speaking_text = ""
        self._bus.publish(Event(
            type=EventType.AGENT_RESPONSE_END,
            source="voice_pipeline",
            data={"text": response_text},
        ))

        if _stale():
            # A newer turn has already started (and already stopped this
            # turn's playback + set its own state) — touching self._state
            # or the vad/speech-buffer bookkeeping here would race that
            # turn's own updates. This is exactly the mechanism behind the
            # 2026-09-17 "keeps talking / hears itself" + IDLE-during-
            # SPEAKING bugs; see _turn_seq comment in __init__.
            logger.info(
                f"SpeakResponse for turn {turn_id} superseded by turn "
                f"{self._turn_seq} during playback — not touching pipeline state."
            )
            return

        if self._barge_in_event.is_set():
            # The pipeline loop's SPEAKING branch already transitioned to
            # LISTENING and reset the speech buffer/VAD the instant it
            # detected the interruption — doing it again here would stomp on
            # whatever speech the user has already started giving it.
            logger.debug("Response speaking thread exiting after barge-in (state already handled).")
            return

        if self._halted.is_set() or not self._running.is_set():
            # HALT/shutdown already handled elsewhere too — same reasoning.
            return

        logger.info(f"Response streaming completed ({len(collected_text)} sentences). Transitioning pipeline state: SPEAKING -> LISTENING.")
        self._set_state(VoicePipelineState.LISTENING)
        self._vad.reset()
        self._speech_buffer.clear()
        self._heard_speech = False
        self._silence_frames = 0
        self._listen_start = time.monotonic()
        logger.info("🎤 Listening for follow-up...")

    def _get_guest_response(self, text: str) -> str:
        """Return a canned response for unverified (guest) speakers."""
        lower = text.lower()
        if any(word in lower for word in ["time", "date", "day"]):
            import datetime
            now = datetime.datetime.now()
            return f"The current time is {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d')}."
        elif any(word in lower for word in ["what are you", "who are you", "what is archer"]):
            return "I am ARCHER, an AI assistant. I can only provide limited information to unverified users."
        elif any(word in lower for word in ["weather"]):
            return "I'm sorry, I can only provide weather information to verified users."
        else:
            return "I'm sorry, I can only assist verified users with that request. Please verify your identity first."

    def _handle_guest_mode(self, text: str) -> None:
        """Handle requests from unverified speakers (guest mode)."""
        logger.info(f"Guest mode request: '{text}'")
        response = self._get_guest_response(text)

        self._bus.publish(Event(
            type=EventType.AUTH_GUEST,
            source="voice_pipeline",
            data={"query": text, "response": response},
        ))

        self._speak_response_streaming(iter([response]), response)

    def _split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences for streaming TTS."""
        # Split on sentence-ending punctuation
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s for s in sentences if s.strip()]

    def _set_state(self, new_state: str) -> None:
        """Update pipeline state and notify via event bus.

        Takes _state_lock for the read-modify-write — self._state is
        touched from both the main pipeline-loop thread and per-turn
        SpeakResponse threads (see _turn_seq comment in __init__), so this
        alone doesn't prevent the turn-ordering race (the turn_seq guard
        does that), but it does prevent a torn/lost update to old_state
        itself. Logs the calling thread name and current turn so a future
        reproduction of a state anomaly is traceable straight from the log.
        """
        with self._state_lock:
            old_state = self._state
            self._state = new_state
            changed = old_state != new_state

        if changed:
            # INFO, not debug -- the console log Col captures is INFO-level
            # only (see __main__.py's setup_logging); this exact line is
            # what will show a state anomaly (e.g. IDLE while TTS is still
            # playing) directly in the next test run's log.
            logger.info(
                f"Pipeline state: {old_state} → {new_state} "
                f"(thread={threading.current_thread().name}, turn={self._turn_seq})"
            )

            # Publish state change event so the GUI (orb, state label) can update.
            self._bus.publish(Event(
                type=EventType.PIPELINE_STATE_CHANGED,
                source="voice_pipeline",
                data={"state": new_state, "old_state": old_state},
            ))

    @property
    def state(self) -> str:
        """Get the current pipeline state."""
        return self._state

    def _on_halt(self, event: Event) -> None:
        """HALT handler — interrupt everything, then confirm verbally."""
        self._halted.set()
        self._speech_buffer.clear()
        logger.warning("HALT: Voice pipeline interrupted.")

        # Brief verbal confirmation: 'Stopped.' — one word, then silence.
        # Runs in its own thread so it doesn't block the HALT handler.
        def _confirm():
            try:
                result = self._get_cached_filler("Stopped.")
                if result is None:
                    result = self._tts.synthesize("Stopped.")
                if result:
                    audio_bytes, sample_rate = result
                    self._audio.play_audio_bytes(audio_bytes, sample_rate)
            except Exception:
                pass  # Non-critical — HALT itself already succeeded

        threading.Thread(target=_confirm, daemon=True, name="HaltConfirm").start()

    def _on_text_input(self, event: Event) -> None:
        """Handle text input from the GUI (bypasses wake word and STT)."""
        text = event.data.get("text", "").strip()
        if not text:
            return

        logger.info(f"📝 Text input: '{text}'")

        # New turn starting -- see _turn_seq comment in __init__. Bump this
        # immediately (before the callback even dispatches) so any voice
        # turn's SpeakResponse thread still finishing up in the background
        # sees it's been superseded rather than racing this one's state.
        self._turn_seq += 1

        # Stop active audio playback and cancel in-progress TTS (barge-in interrupt)
        self._audio.stop_playback()
        self._tts.cancel()

        # Cancel any previous turn's still-running agent generator -- see
        # _active_agent_gen comment in __init__ (same lock-starvation
        # concern applies whether the previous turn was voice or text).
        stale_gen = self._active_agent_gen
        self._active_agent_gen = None
        if stale_gen is not None:
            try:
                stale_gen.close()
            except Exception as e:
                logger.debug(f"Closing superseded agent generator failed (non-fatal): {e}")

        # Publish as STT_FINAL so conversation panel shows the user message
        self._bus.publish(Event(
            type=EventType.STT_FINAL,
            source="voice_pipeline",
            data={"text": text},
        ))

        # Check for HALT
        if self._halt.check_text_for_halt(text):
            return

        # Process through agent (no wake word, no STT, no voice auth needed)
        threading.Thread(
            target=self._call_agent_with_filler,
            args=(text,),
            daemon=True,
        ).start()

    def process_text_input(self, text: str) -> None:
        """
        Process a text input directly (bypasses wake word, VAD, STT).
        Routes through the same agent pipeline as voice input.
        """
        self._bus.publish(Event(
            type=EventType.GUI_TEXT_INPUT,
            source="gui",
            data={"text": text},
        ))
