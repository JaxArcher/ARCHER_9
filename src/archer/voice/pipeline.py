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

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.voice.audio import AudioManager
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
        self._audio = AudioManager()
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

        # Audio collection buffer (for collecting speech frames)
        self._speech_buffer: list[bytes] = []

        # Rolling buffer discarded on wake word detection (prevents wake word
        # phrase from leaking into the speech buffer and triggering early STT).
        self._pre_buffer: collections.deque[bytes] = collections.deque(maxlen=33)
        self._heard_speech: bool = False
        self._silence_frames: int = 0
        self._listen_start: float = 0.0

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

                    self._bus.publish(Event(
                        type=EventType.WAKE_WORD_DETECTED,
                        source="voice_pipeline",
                    ))

            elif self._state == VoicePipelineState.LISTENING:
                # Collect ALL audio while listening (speech + pauses).
                # The STT model handles noise/silence far better than
                # trying to gate audio frames ourselves.
                is_speech = self._vad.process_audio(audio_chunk)

                # Use the RAW per-frame result to track speech/silence.
                # The smoothed self._vad.is_speaking lags behind reality
                # (ring buffer needs 80% silent frames to flip) which
                # prevents the silence counter from ever reaching the
                # threshold on noisy mics.
                if is_speech:
                    self._heard_speech = True
                    self._silence_frames = 0
                elif self._heard_speech:
                    self._silence_frames += 1

                if self._heard_speech:
                    # Always buffer audio once speech has started
                    self._speech_buffer.append(audio_chunk)

                    # End utterance after ~1.0 seconds of continuous silence
                    # (33 frames × 30ms ≈ 1000ms). This tolerates mid-sentence
                    # pauses while still cutting off cleanly.
                    if self._silence_frames >= 33:
                        self._process_utterance()

                # Hard timeout: cap utterance at 30 seconds to prevent
                # getting stuck if the mic picks up ambient noise.
                elapsed = time.monotonic() - self._listen_start
                if self._heard_speech and elapsed > 30.0:
                    logger.warning("Max utterance duration reached (30s) — processing")
                    self._process_utterance()

                # Timeout: if no speech within 5 seconds of wake word, go idle
                if not self._heard_speech and (time.monotonic() - self._listen_start) > 5.0:
                    logger.info("No speech after wake word — returning to idle")
                    self._set_state(VoicePipelineState.IDLE)
                    self._speech_buffer.clear()

            elif self._state == VoicePipelineState.SPEAKING:
                # During TTS playback — monitor for barge-in
                is_speech = self._vad.process_audio(audio_chunk)
                if is_speech:
                    logger.info("🔇 Barge-in detected — stopping TTS")
                    self._audio.stop_playback()
                    self._tts.cancel()
                    self._bus.publish(Event(
                        type=EventType.BARGE_IN,
                        source="voice_pipeline",
                    ))
                    self._set_state(VoicePipelineState.LISTENING)
                    self._speech_buffer.clear()
                    self._vad.reset()
                    self._heard_speech = False
                    self._silence_frames = 0
                    self._listen_start = time.monotonic()

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
            self._speak_response_streaming(iter(["I heard you, but no agent is available."]))
            return

        # --- Sentence queue bridges the worker → main thread ---
        sentence_queue: queue.Queue[str | None] = queue.Queue()
        # Shared flag so main thread can check if the worker aborted early
        worker_aborted = threading.Event()

        def _worker():
            """Run auth + STT + agent in one shot, feeding sentences into the queue."""
            try:
                # --- Voice Authentication ---
                auth_audio = audio_data[:self._config.sample_rate * 2 * 2]
                is_verified, similarity = self._auth.verify(auth_audio)

                # --- Speech-to-Text ---
                text = self._stt.transcribe(audio_data)

                if not text or text.strip() == "":
                    logger.debug("STT returned empty text, ignoring.")
                    worker_aborted.set()
                    return

                logger.info(f"📝 STT: '{text}'")

                # Publish STT result for GUI conversation panel
                self._bus.publish(Event(
                    type=EventType.STT_FINAL,
                    source="voice_pipeline",
                    data={"text": text},
                ))

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
                    for sentence in self._agent_streaming_callback(text):
                        sentence_queue.put(sentence)
                else:
                    result = self._agent_callback(text)
                    for sentence in self._split_into_sentences(result):
                        sentence_queue.put(sentence)

            except Exception as e:
                logger.error(f"Utterance processing failed: {e}")
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
            self._set_state(VoicePipelineState.IDLE)
            return

        # Stream ended immediately with no sentences
        if first is None and not sentence_queue.empty():
            self._set_state(VoicePipelineState.IDLE)
            return

        # Play filler if no first sentence arrived in time
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

            # Now wait for the actual first sentence
            first = sentence_queue.get()

            # Check again in case worker aborted while filler was playing
            if worker_aborted.is_set():
                self._set_state(VoicePipelineState.IDLE)
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

        self._speak_response_streaming(sentence_stream())

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
                    for sentence in self._agent_streaming_callback(text):
                        sentence_queue.put(sentence)
                else:
                    result = self._agent_callback(text)
                    for sentence in self._split_into_sentences(result):
                        sentence_queue.put(sentence)
            except Exception as e:
                logger.error(f"Agent call failed: {e}")
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
        """Pre-generate and cache all filler audio clips on startup."""
        from archer.voice.tts import FILLER_PHRASES
        logger.info("Pre-caching filler audio clips...")
        for phrase in FILLER_PHRASES:
            try:
                result = self._tts.synthesize(phrase)
                if result:
                    self._filler_cache[phrase] = result
                    logger.debug(f"Cached filler: '{phrase}'")
            except Exception as e:
                logger.warning(f"Failed to cache filler '{phrase}': {e}")
        logger.info(f"Filler cache ready ({len(self._filler_cache)} clips)")

    def _speak_response_streaming(
        self, sentences: iter, full_text: str = ""
    ) -> None:
        """
        Synthesize and play sentences as they arrive from the LLM stream.

        Each sentence is sent to TTS immediately — sentence N plays while
        the LLM generates sentence N+1. This is the key to <800ms latency.
        """
        self._set_state(VoicePipelineState.SPEAKING)

        collected_text = []

        self._bus.publish(Event(
            type=EventType.AGENT_RESPONSE_START,
            source="voice_pipeline",
            data={"text": full_text},
        ))

        for sentence in sentences:
            if self._halted.is_set() or not self._running.is_set():
                break

            sentence = sentence.strip()
            if not sentence:
                continue

            collected_text.append(sentence)

            result = self._tts.synthesize(sentence)
            if result is None:
                break

            audio_bytes, sample_rate = result
            self._audio.play_audio_bytes(audio_bytes, sample_rate)

        response_text = " ".join(collected_text)
        self._bus.publish(Event(
            type=EventType.AGENT_RESPONSE_END,
            source="voice_pipeline",
            data={"text": response_text},
        ))

        # Transition to LISTENING (not IDLE) for continuous dialogue.
        # The user can keep talking without re-saying the wake word.
        # A 5-second silence timeout in the LISTENING state will
        # return to IDLE if no follow-up speech is detected.
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
        """Update pipeline state and notify via event bus."""
        old_state = self._state
        self._state = new_state

        if old_state != new_state:
            logger.debug(f"Pipeline state: {old_state} → {new_state}")

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
