"""
ARCHER Audio I/O Management.

Manages microphone capture and speaker playback using sounddevice.
Runs the microphone capture in its own dedicated thread. Provides
thread-safe queues for audio data flow.

This module is the ONLY component that directly accesses audio hardware.
All other voice pipeline components receive audio data through queues.

Capture and playback run as two INDEPENDENT sounddevice streams, not one
shared duplex stream. They used to be combined into a single duplex
sd.Stream so acoustic echo cancellation (AEC) could subtract the exact
samples being played from what the mic picked up. That only makes sense
when the mic can physically hear the speaker output (open speakers). With
a Bluetooth headset/earbuds, there's no acoustic path from output back
into the mic, so AEC has nothing real to cancel — and forcing a wired USB
mic and a Bluetooth output through one duplex stream, on two unrelated
hardware clocks, was producing exactly the kind of buffer glitches
("input overflow"/"output underflow") that got misread as speech by the
VAD and wake-word detector every time something played. Splitting them
removes that coupling entirely.

Loopback reference (open-speaker echo/notification suppression): the
playback stream now opens at the output device's own native sample rate
(queried at start_capture, stored as _playback_rate) instead of being
forced to the 16kHz pipeline/STT rate. Forcing 16kHz on hardware that
doesn't natively run at 16kHz (e.g. an HDMI soundbar) was left over from
an earlier attempt (~Jan 2026) at real duplex AEC via pyaec, which needed
mic and reference audio at a matched rate — that attempt was abandoned
(see above), but the forced output rate stuck around.

Getting a reference of what the speakers are actually outputting needs a
second, separate capture path — sounddevice/PortAudio has NO loopback
support (WasapiSettings has no 'loopback' parameter; that was a mistaken
assumption in an earlier version of this module, confirmed live via
`WasapiSettings.__init__() got an unexpected keyword argument 'loopback'`).
Real Windows loopback capture instead goes through the separate
`soundcard` package (sc.get_microphone(id=<speaker name>,
include_loopback=True)), run on its own polling thread since soundcard's
Recorder.record() is blocking, not callback-based like sounddevice's
streams — see _start_loopback/_loopback_loop. It captures whatever is
actually being rendered on the same output device — ARCHER's own TTS, a
Windows notification chime, anything — as a short-time energy envelope
(get_loopback_envelope) the voice pipeline correlates against buffered
mic audio to veto barge-in/self-hearing based on whether the mic content
acoustically matches what just played — not on whether it transcribes to
a known phrase, which is what let notification sounds slip past the old
content-only check. Loopback capture is best-effort: if `soundcard` isn't
installed or the device doesn't support it, it's disabled and the
pipeline falls back to content-only matching, same as before.
"""

from __future__ import annotations

import collections
import os
import queue
import threading
import time
from math import gcd
from typing import Callable

import numpy as np
import sounddevice as sd
from loguru import logger
from scipy.signal import resample_poly

from archer.config import get_config, _save_device_to_env
from archer.core.event_bus import Event, EventType, get_event_bus


class AudioManager:
    """
    Manages audio input (microphone) and output (speakers).

    Audio capture runs in a dedicated thread. Audio data is pushed
    to subscribers via thread-safe queues.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._bus = get_event_bus()

        # Audio parameters
        self._sample_rate = self._config.sample_rate
        self._channels = self._config.audio_channels
        self._chunk_samples = int(self._sample_rate * self._config.audio_chunk_ms / 1000)
        # Actual rate/channel count the capture stream opened with. Normally
        # equal to self._sample_rate/self._channels (mono @ pipeline rate),
        # but WASAPI shared-mode devices commonly reject both an explicit
        # mono request AND the pipeline's 16kHz rate outright (PaErrorCode
        # -9998 / -9997) — confirmed live: JLab mic + LG soundbar both only
        # accept their native 48kHz WASAPI mix format. See _open_audio_stream.
        # When _capture_rate != _sample_rate, _input_callback resamples
        # every chunk down to the pipeline rate before queuing, and when
        # _capture_channels > 1 it downmixes to mono first — everything
        # downstream (VAD/STT/wake-word) always sees mono int16 @ _sample_rate.
        self._capture_rate: int = self._sample_rate
        self._capture_channels = self._channels

        # Thread-safe audio queue for downstream consumers
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)

        # Playback control
        self._is_playing = threading.Event()
        self._playback_lock = threading.Lock()

        # Capture control — separate input/output streams, see module docstring.
        self._is_capturing = threading.Event()
        self._capture_stream: sd.InputStream | None = None
        self._playback_stream: sd.OutputStream | None = None
        self._playback_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=10000)
        # Playback now opens at the output device's native rate (see module
        # docstring) instead of being forced to match the mic's pipeline
        # rate. Set once in start_capture(); play_audio() resamples to this.
        self._playback_rate: int = self._sample_rate
        self._playback_chunk_samples: int = self._chunk_samples
        # Actual channel count the playback stream opened with — see
        # _open_audio_stream (same WASAPI mono-rejection issue as capture).
        self._playback_channels: int = self._channels

        # WASAPI loopback reference — best-effort, see module docstring.
        # sounddevice/PortAudio has no loopback support (confirmed live:
        # WasapiSettings has no 'loopback' param in this build — that was
        # never a real sounddevice feature, just a mistaken assumption).
        # Real Windows loopback capture goes through the separate
        # `soundcard` package instead, via a dedicated polling thread (its
        # Recorder API is blocking/pull-based, not callback-based like
        # sounddevice) — see _start_loopback/_loopback_loop.
        self._loopback_thread: threading.Thread | None = None
        self._loopback_stop = threading.Event()
        self._loopback_available = False
        self._loopback_lock = threading.Lock()
        self._loopback_bin_seconds = 0.02
        # ~10s of 20ms bins — plenty for any barge-in snippet window.
        self._loopback_envelope: collections.deque[tuple[float, float]] = collections.deque(maxlen=500)

        # TTS mute
        self._tts_muted = threading.Event()

        # Mic mute
        self._mic_muted = threading.Event()

        # Register HALT handler
        self._bus.subscribe_halt(self._on_halt)

    def start_capture(self) -> None:
        """Start microphone capture and speaker playback as independent streams."""
        if self._is_capturing.is_set():
            logger.warning("Audio capture already running.")
            return

        self._is_capturing.set()

        device_index = self._config.mic_device_index
        speaker_index = self._config.speaker_device_index

        # Resolve concrete device indices/names up front (not just for
        # logging) — the loopback stream needs a real index to query native
        # rate/channels and to guarantee it targets the SAME physical device
        # that's actually rendering ARCHER's audio.
        mic_name = "Default System Mic"
        speaker_name = "Default System Speaker"
        effective_speaker_index = speaker_index
        try:
            devs = sd.query_devices()
            if device_index is not None and device_index < len(devs):
                mic_name = devs[device_index]["name"]
            elif sd.default.device[0] is not None and sd.default.device[0] < len(devs):
                mic_name = devs[sd.default.device[0]]["name"]

            if effective_speaker_index is None:
                effective_speaker_index = sd.default.device[1]
            if effective_speaker_index is not None and effective_speaker_index < len(devs):
                speaker_name = devs[effective_speaker_index]["name"]
        except Exception:
            pass

        # Found 2026-09-16 (Col's live web_main run): input and output used
        # to be opened inside ONE try/except, so a failure on EITHER side
        # took the whole audio system down -- even on a run where the mic
        # (a wired USB device) opened and started just fine, and only the
        # Bluetooth speaker's format negotiation failed. That's backwards:
        # losing TTS playback is a real problem, but it shouldn't also
        # kill a mic that's working, forcing "text-only mode" when voice
        # INPUT was never actually broken. Input and output now each get
        # their own retry ladder (still with the 1.5s-backoff retry below,
        # for the separate "device still being released by a just-exited
        # ARCHER process" case), and capture only counts as fully failed
        # if BOTH sides come up empty. A one-sided failure logs clearly
        # and leaves the working side running degraded rather than tearing
        # it down too.
        capture_error: Exception | None = None
        playback_error: Exception | None = None

        for attempt in range(2):
            if self._capture_stream is None:
                try:
                    self._capture_stream, self._capture_rate, self._capture_channels = self._open_audio_stream(
                        kind="input",
                        device_index=device_index,
                        preferred_rate=self._sample_rate,
                        preferred_channels=self._channels,
                        blocksize_ms=self._config.audio_chunk_ms,
                        callback=self._input_callback,
                    )
                    capture_error = None
                except Exception as e:
                    capture_error = e

            if self._playback_stream is None:
                try:
                    self._playback_stream, self._playback_rate, self._playback_channels = self._open_audio_stream(
                        kind="output",
                        device_index=effective_speaker_index,
                        preferred_rate=self._sample_rate,
                        preferred_channels=self._channels,
                        blocksize_ms=self._config.audio_chunk_ms,
                        callback=self._output_callback,
                    )
                    self._playback_chunk_samples = int(
                        self._playback_rate * self._config.audio_chunk_ms / 1000
                    )
                    playback_error = None
                except Exception as e:
                    playback_error = e

            if capture_error is None and playback_error is None:
                break
            if attempt == 0 and (capture_error is not None or playback_error is not None):
                logger.warning(
                    f"Audio stream startup incomplete on first attempt "
                    f"(capture_error={capture_error}, playback_error={playback_error}) -- "
                    f"retrying whichever side failed once in 1.5s in case this is a device "
                    f"still being released by a just-exited ARCHER process."
                )
                time.sleep(1.5)

        if capture_error is not None and playback_error is not None:
            # Neither side came up -- nothing usable, same hard failure as before.
            self._is_capturing.clear()
            logger.error(
                f"Failed to start audio streams after retry -- both input and output failed "
                f"(capture: {capture_error}; playback: {playback_error})"
            )
            raise capture_error

        if capture_error is not None:
            logger.error(
                f"Microphone failed to start after retry ({capture_error}) -- voice INPUT is "
                f"unavailable (text-only for listening), but speaker/TTS output is still working."
            )
        if playback_error is not None:
            logger.error(
                f"Speaker failed to start after retry ({playback_error}) -- TTS playback is "
                f"unavailable, but the microphone is still working (voice input/STT unaffected)."
            )

        logger.info(
            f"Audio streams started — independent input/output "
            f"(mic={device_index} ['{mic_name}']{' -- FAILED, see above' if capture_error else ''}, "
            f"speaker={effective_speaker_index} ['{speaker_name}']{' -- FAILED, see above' if playback_error else ''}, "
            f"capture_rate={self._capture_rate} (pipeline rate {self._sample_rate}), "
            f"playback_rate={self._playback_rate}, "
            f"chunk={self._chunk_samples}/{self._playback_chunk_samples} samples)"
        )

        # WASAPI loopback reference — best-effort, non-fatal. Lets the
        # pipeline tell "mic hearing the speakers" apart from genuine
        # speech for ANY system audio (ARCHER's own TTS, a Windows
        # notification, etc.), not just content that matches a known
        # phrase. See module docstring.
        self._start_loopback(effective_speaker_index, speaker_name)

    def _open_audio_stream(
        self,
        kind: str,
        device_index: int | None,
        preferred_rate: int,
        preferred_channels: int,
        blocksize_ms: float,
        callback: Callable,
    ) -> tuple[sd.InputStream | sd.OutputStream, int, int]:
        """
        Open an input or output stream, falling back through (rate,
        channels) combinations when the device/driver rejects the
        preferred pipeline rate and/or an explicit mono request — both
        confirmed live on WASAPI: PaErrorCode -9997 (invalid sample rate)
        when a device's WASAPI shared-mode mix format isn't the pipeline's
        16kHz (e.g. a device that's natively 48kHz), and -9998 (invalid
        channel count) when it won't accept mono. MME/DirectSound are
        generally permissive about both — this only kicks in for stricter
        drivers/host APIs.

        Returns (stream, actual_rate, actual_channels). When actual_rate
        differs from preferred_rate, the caller MUST resample: see
        _input_callback (mic → pipeline rate) and play_audio (TTS →
        _playback_rate).
        """
        native_rate = preferred_rate
        native_channels = preferred_channels
        try:
            idx = device_index
            if idx is None:
                idx = sd.default.device[0] if kind == "input" else sd.default.device[1]
            info = sd.query_devices(idx)
            native_rate = int(info.get("default_samplerate") or preferred_rate)
            max_ch_key = "max_input_channels" if kind == "input" else "max_output_channels"
            native_channels = max(1, int(info.get(max_ch_key, preferred_channels) or preferred_channels))
        except Exception:
            pass

        # Try the preferred config first (fast path, no resampling), then
        # widen one dimension at a time, then both — dedupe as we go.
        #
        # Always include channels=2 as an explicit candidate, not just
        # whatever native_channels resolved to. Confirmed live: when the
        # device-info query above fails (e.g. a stale device index after
        # Windows re-enumerates audio endpoints — happens on its own,
        # unrelated to anything ARCHER does) native_channels silently
        # falls back to preferred_channels, collapsing all 4 candidates
        # down to just 2 unique (rate, 1) pairs — the exact failure mode
        # seen live, where BOTH 16kHz/mono and 48kHz/mono were rejected
        # and channels=2 never got tried at all. WASAPI's own documented
        # behavior backs up 2 as a safe blind guess regardless: per the
        # `soundcard` package's docs, "Windows/WASAPI currently records
        # garbage if you record only a single channel" — mono requests
        # are unreliable on WASAPI even when a device reports supporting
        # them.
        candidates: list[tuple[int, int]] = []
        for cand in (
            (preferred_rate, preferred_channels),
            (preferred_rate, native_channels),
            (preferred_rate, 2),
            (native_rate, preferred_channels),
            (native_rate, native_channels),
            (native_rate, 2),
        ):
            if cand not in candidates:
                candidates.append(cand)

        # Found 2026-09-16 (Col's live web_main run): construction alone
        # isn't proof a candidate actually works -- WASAPI shared-mode
        # format negotiation can pass sd.InputStream/OutputStream()
        # construction cleanly and only reject the format once .start() is
        # called (AUDCLNT_E_UNSUPPORTED_FORMAT), which used to happen
        # AFTER this whole method returned, outside the retry ladder
        # entirely -- so a candidate that built fine but couldn't actually
        # start took down the whole audio system with zero fallback,
        # exactly like this candidate loop already does for construction
        # failures. Both construction and .start() now have to succeed
        # before a candidate counts as good; a start() failure closes that
        # stream and moves on to the next candidate same as a construction
        # failure would.
        last_error: Exception | None = None
        for rate, channels in candidates:
            blocksize = max(1, int(rate * blocksize_ms / 1000))
            stream = None
            try:
                if kind == "input":
                    stream = sd.InputStream(
                        samplerate=rate, channels=channels, dtype="int16",
                        blocksize=blocksize, device=device_index, callback=callback,
                    )
                else:
                    stream = sd.OutputStream(
                        samplerate=rate, channels=channels, dtype="int16",
                        blocksize=blocksize, device=device_index, callback=callback,
                    )
                stream.start()
                if (rate, channels) != (preferred_rate, preferred_channels):
                    logger.info(
                        f"{kind.capitalize()} stream opened at rate={rate}, channels={channels} "
                        f"(device rejected preferred rate={preferred_rate}, channels={preferred_channels})"
                    )
                return stream, rate, channels
            except Exception as e:
                last_error = e
                logger.warning(f"{kind.capitalize()} open/start failed at rate={rate}, channels={channels}: {e}")
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass

        assert last_error is not None
        raise last_error

    def _start_loopback(self, speaker_index: int | None, speaker_name: str) -> None:
        """
        Best-effort Windows loopback capture on the output device, via the
        `soundcard` package (sounddevice/PortAudio has no loopback support
        — see module docstring). Runs a dedicated polling thread since
        soundcard's Recorder.record() is blocking, not callback-based.
        """
        self._loopback_available = False
        if not speaker_name:
            logger.warning("Loopback capture skipped: no output device name resolved.")
            return
        try:
            import soundcard as sc
        except ImportError:
            logger.warning(
                "Loopback capture unavailable: the 'soundcard' package isn't installed "
                "(pip install soundcard) — falling back to content-only self-echo matching."
            )
            return

        try:
            # soundcard identifies devices by name (fuzzy-matched), not the
            # sounddevice/PortAudio integer index — reuse the name we
            # already resolved for the SAME physical device.
            loopback_mic = sc.get_microphone(id=speaker_name, include_loopback=True)
        except Exception as e:
            logger.warning(
                f"Loopback capture unavailable ({e}) — falling back to "
                f"content-only self-echo matching."
            )
            return

        self._loopback_stop.clear()
        self._loopback_thread = threading.Thread(
            target=self._loopback_loop,
            args=(loopback_mic, speaker_name),
            daemon=True,
            name="LoopbackCapture",
        )
        self._loopback_thread.start()

    def _loopback_loop(self, loopback_mic, speaker_name: str) -> None:
        """
        Polling loop for the loopback reference stream (see _start_loopback
        for why this can't be a callback like the other streams). Records
        small blocks continuously and stores a short-time RMS energy value
        per block — same envelope format/consumer (get_loopback_envelope)
        as originally planned for the callback-based approach.
        """
        rate = self._playback_rate
        block_frames = max(1, int(rate * self._loopback_bin_seconds))
        try:
            # Windows/WASAPI is known to record garbage on a single-channel
            # request (soundcard's own documented caveat) — let it use the
            # device's native channel count; energy is summed across
            # whatever channels come back either way.
            with loopback_mic.recorder(samplerate=rate, blocksize=block_frames) as rec:
                self._loopback_available = True
                logger.info(f"Loopback capture started on '{speaker_name}' (rate={rate})")
                while not self._loopback_stop.is_set():
                    data = rec.record(numframes=block_frames)
                    try:
                        energy = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
                    except Exception:
                        continue
                    with self._loopback_lock:
                        self._loopback_envelope.append((time.monotonic(), energy))
        except Exception as e:
            logger.warning(
                f"Loopback capture failed ({e}) — falling back to content-only self-echo matching."
            )
        finally:
            self._loopback_available = False

    def stop_capture(self) -> None:
        """Stop microphone capture and speaker playback."""
        self._is_capturing.clear()
        if self._capture_stream is not None:
            try:
                self._capture_stream.stop()
                self._capture_stream.close()
            except Exception as e:
                logger.warning(f"Error stopping audio capture: {e}")
            finally:
                self._capture_stream = None
        if self._playback_stream is not None:
            try:
                self._playback_stream.stop()
                self._playback_stream.close()
            except Exception as e:
                logger.warning(f"Error stopping audio playback stream: {e}")
            finally:
                self._playback_stream = None
        self._loopback_stop.set()
        if self._loopback_thread is not None:
            self._loopback_thread.join(timeout=2.0)
            self._loopback_thread = None
        self._loopback_available = False
        with self._loopback_lock:
            self._loopback_envelope.clear()
        logger.info("Audio capture stopped.")

    def switch_input_device(self, device_index: int) -> None:
        """Live hot-swap the microphone to a different device, without a
        process restart (2026-09-16, Col's call for the browser device
        dropdown). Tears down just the input stream and reopens it via the
        same _open_audio_stream path start_capture() already uses -- output
        stream and loopback reference are untouched. Persists the choice to
        .env via the same helper the one-time interactive first-run prompt
        already used, so it's also the default on the next full restart."""
        if not self._is_capturing.is_set():
            raise RuntimeError("Cannot switch microphone -- audio capture isn't running.")

        old_stream = self._capture_stream
        if old_stream is not None:
            try:
                old_stream.stop()
                old_stream.close()
            except Exception as e:
                logger.warning(f"Error closing previous capture stream during mic switch: {e}")

        self._capture_stream, self._capture_rate, self._capture_channels = self._open_audio_stream(
            kind="input",
            device_index=device_index,
            preferred_rate=self._sample_rate,
            preferred_channels=self._channels,
            blocksize_ms=self._config.audio_chunk_ms,
            callback=self._input_callback,
        )
        self._config.mic_device_index = device_index
        _save_device_to_env("ARCHER_MIC_DEVICE_INDEX", device_index)
        logger.info(f"Microphone hot-swapped to device {device_index} (capture_rate={self._capture_rate}).")

    def switch_output_device(self, device_index: int) -> None:
        """Live hot-swap the speaker to a different device -- same reasoning
        as switch_input_device. Also restarts the WASAPI loopback reference
        against the new speaker so barge-in detection keeps working against
        whichever device is actually rendering ARCHER's audio now."""
        if not self._is_capturing.is_set():
            raise RuntimeError("Cannot switch speaker -- audio capture isn't running.")

        old_stream = self._playback_stream
        if old_stream is not None:
            try:
                old_stream.stop()
                old_stream.close()
            except Exception as e:
                logger.warning(f"Error closing previous playback stream during speaker switch: {e}")

        self._playback_stream, self._playback_rate, self._playback_channels = self._open_audio_stream(
            kind="output",
            device_index=device_index,
            preferred_rate=self._sample_rate,
            preferred_channels=self._channels,
            blocksize_ms=self._config.audio_chunk_ms,
            callback=self._output_callback,
        )
        self._playback_chunk_samples = int(self._playback_rate * self._config.audio_chunk_ms / 1000)
        self._config.speaker_device_index = device_index
        _save_device_to_env("ARCHER_SPEAKER_DEVICE_INDEX", device_index)

        # Restart the loopback reference against the new output device --
        # best-effort, same as the initial start_capture() call.
        speaker_name = "Selected Speaker"
        try:
            devs = sd.query_devices()
            if device_index < len(devs):
                speaker_name = devs[device_index]["name"]
        except Exception:
            pass
        self._loopback_stop.set()
        if self._loopback_thread is not None:
            self._loopback_thread.join(timeout=2.0)
            self._loopback_thread = None
        self._loopback_available = False
        self._start_loopback(device_index, speaker_name)

        logger.info(f"Speaker hot-swapped to device {device_index} (playback_rate={self._playback_rate}).")

    @property
    def loopback_available(self) -> bool:
        """Whether loopback reference capture is active."""
        return self._loopback_available

    @property
    def loopback_bin_seconds(self) -> float:
        """Duration (seconds) each loopback envelope bin covers."""
        return self._loopback_bin_seconds

    def get_loopback_envelope(self, start: float, end: float) -> list[float] | None:
        """
        Return loopback RMS-energy bins (oldest first) timestamped within
        [start, end] (time.monotonic() seconds). None if loopback capture
        isn't available — callers should fall back to content-only checks.
        """
        if not self._loopback_available:
            return None
        with self._loopback_lock:
            return [e for (t, e) in self._loopback_envelope if start <= t <= end]

    def _input_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """
        Called by sounddevice for each captured mic chunk. Runs on its own
        stream, independent of playback — see module docstring for why.

        Normalizes whatever the device actually gave us (see
        _open_audio_stream — WASAPI may have forced a different channel
        count and/or sample rate than the pipeline wants) down to mono
        int16 @ self._sample_rate, which is what VAD/STT/wake-word all
        expect. When capture opened at the pipeline's preferred rate/mono
        (the common MME/DirectSound case), this is a straight passthrough
        with no extra work.
        """
        if status:
            logger.warning(f"Audio input callback status: {status}")

        if self._is_capturing.is_set() and not self._mic_muted.is_set():
            if self._capture_channels > 1:
                mono = indata.astype(np.int32).mean(axis=1).astype(np.int16)
            else:
                mono = indata.reshape(-1).astype(np.int16, copy=False)

            if self._capture_rate != self._sample_rate:
                # Resample down to the pipeline rate (typically 48kHz -> 16kHz
                # on WASAPI hardware that rejects 16kHz outright -- see
                # _open_audio_stream's fallback ladder). This USED to be a
                # naive np.interp linear resample with no anti-aliasing
                # filter, which is exactly the kind of thing that produces
                # aliasing noise when downsampling 3:1 -- high-frequency
                # content above the new 8kHz Nyquist folds back into the
                # audible band as noise-like energy. webrtcvad (real-time,
                # frame-energy based) was reading THAT noise as "speech",
                # flagging silence as a live utterance; faster-whisper's own
                # (much better, Silero-based) VAD then correctly found no
                # real speech in the same buffer and discarded it entirely
                # -- exactly the "0.00s speech survived VAD" pattern Col hit
                # repeatedly, and why he had to repeat the wake word. Fixed
                # by using scipy's resample_poly, which low-pass filters
                # before decimating (proper anti-aliasing), then padding/
                # trimming to exactly self._chunk_samples so VAD's fixed
                # 10/20/30ms frame requirement is still met regardless of
                # the driver's actual chunk size or rate cleanliness (2026-09-16).
                g = gcd(self._sample_rate, self._capture_rate)
                up, down = self._sample_rate // g, self._capture_rate // g
                resampled = resample_poly(mono.astype(np.float32), up, down)
                n_target = self._chunk_samples
                if len(resampled) < n_target:
                    resampled = np.pad(resampled, (0, n_target - len(resampled)))
                elif len(resampled) > n_target:
                    resampled = resampled[:n_target]
                mono = np.clip(resampled, -32768, 32767).astype(np.int16)

            audio_to_push = mono.tobytes()
            try:
                self._audio_queue.put_nowait(audio_to_push)
            except queue.Full:
                try:
                    self._audio_queue.get_nowait()
                    self._audio_queue.put_nowait(audio_to_push)
                except queue.Empty:
                    pass

    def _output_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """
        Called by sounddevice for each speaker chunk. Runs on its own
        stream, independent of capture.
        """
        if status:
            logger.warning(f"Audio output callback status: {status}")

        if self._is_playing.is_set():
            try:
                chunk = self._playback_queue.get_nowait()
                if chunk is not None:
                    outdata[:] = chunk
                else:
                    # End of sequence
                    self._is_playing.clear()
                    outdata.fill(0)
            except queue.Empty:
                # Underflow
                outdata.fill(0)
        else:
            outdata.fill(0)

    def set_mic_muted(self, muted: bool) -> None:
        """Mute or unmute microphone capture."""
        if muted:
            self._mic_muted.set()
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break
        else:
            self._mic_muted.clear()

        logger.info(f"Microphone mute state changed: muted={muted}")
        self._bus.publish(Event(
            type=EventType.MIC_MUTE_TOGGLED,
            source="audio_manager",
            data={"muted": muted}
        ))

    def is_mic_muted(self) -> bool:
        """Check if microphone capture is muted."""
        return self._mic_muted.is_set()

    def get_audio_chunk(self, timeout: float = 0.1) -> bytes | None:
        """Get the next audio chunk from the capture queue. Returns None on timeout or when muted."""
        if self._mic_muted.is_set():
            return None
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def play_audio(self, audio_data: np.ndarray, sample_rate: int | None = None) -> None:
        """
        Play audio through the speakers. Blocks until playback is complete.
        Respects HALT and TTS mute.

        During playback, publishes AUDIO_AMPLITUDE events at ~30fps so the
        orb can animate with the speech waveform.
        """
        if self._tts_muted.is_set():
            return

        if audio_data is None or len(audio_data) == 0:
            logger.warning("play_audio received empty or zero-length audio array — skipping playback.")
            return

        # Resample to the playback stream's own native device rate (set in
        # start_capture) — no longer forced to the 16kHz mic/pipeline rate.
        # See module docstring for why that forcing was removed.
        rate = self._playback_rate
        input_dtype = audio_data.dtype
        input_shape = audio_data.shape
        
        # If input rate doesn't match pipeline rate, resample in float32 FIRST.
        # Uses resample_poly (anti-aliased) rather than a naive np.interp --
        # same reasoning as _input_callback's mic downsample above: an
        # unfiltered resample leaves aliasing noise in the played-back
        # audio, which is exactly what the acoustic-bleed/loopback checks
        # in pipeline.py are trying to correlate against (2026-09-16).
        resample_executed = False
        if sample_rate and sample_rate != rate:
            resample_executed = True
            g = gcd(int(rate), int(sample_rate))
            up, down = int(rate) // g, int(sample_rate) // g
            audio_data = resample_poly(audio_data.astype(np.float32), up, down)
            sample_rate = rate

        # Ensure data is int16 for the callback
        if audio_data.dtype != np.int16:
            if audio_data.dtype == np.float32 or audio_data.dtype == np.float64:
                audio_data = (audio_data * 32767.0).astype(np.int16)

        logger.info(
            f"PLAY_AUDIO DUMP LOG:\n"
            f"  - input_dtype: {input_dtype}, input_shape: {input_shape}\n"
            f"  - audio_data.dtype: {audio_data.dtype}, audio_data.shape: {audio_data.shape}\n"
            f"  - sample_rate_param: {sample_rate}\n"
            f"  - rate (self._playback_rate): {rate}\n"
            f"  - resample_executed: {resample_executed}\n"
            f"  - first_20_values: {audio_data[:20].flatten().tolist()}"
        )

        # Write exact hardware playback audio array to disk for external media player verification
        try:
            import soundfile as sf
            os.makedirs("scratch", exist_ok=True)
            ts = int(time.time() * 1000)
            dump_filename = f"scratch/last_hardware_playback_{ts}.wav"
            sf.write(dump_filename, audio_data, rate)
            logger.info(f"Saved live hardware playback array to {dump_filename} ({len(audio_data)} samples @ {rate}Hz)")
        except Exception as e:
            logger.warning(f"Failed to dump hardware playback audio: {e}")

        with self._playback_lock:
            # Clear any stale data
            while not self._playback_queue.empty():
                try: self._playback_queue.get_nowait()
                except queue.Empty: break
            
            # Slice into chunks of self._playback_chunk_samples (native
            # output rate — see start_capture)
            # If mono, ensure (N, 1) shape for the output stream
            if audio_data.ndim == 1:
                audio_data = audio_data.reshape(-1, 1)

            # Stream opened at >1 channel (some WASAPI outputs reject a mono
            # request — see _open_playback_stream) — duplicate the mono
            # signal across all channels so it plays on every one.
            if self._playback_channels > 1 and audio_data.shape[1] == 1:
                audio_data = np.repeat(audio_data, self._playback_channels, axis=1)

            total_samples = len(audio_data)
            offset = 0

            # Set playing flag BEFORE chunking so the hardware callback can actively drain
            self._is_playing.set()

            while offset < total_samples:
                end = min(offset + self._playback_chunk_samples, total_samples)
                chunk = audio_data[offset:end]
                # Pad last chunk if needed
                if len(chunk) < self._playback_chunk_samples:
                    chunk = np.pad(chunk, ((0, self._playback_chunk_samples - len(chunk)), (0, 0)))
                
                try:
                    self._playback_queue.put(chunk, timeout=2.0)
                except queue.Full:
                    logger.error(f"Playback queue full on chunk offset {offset}/{total_samples} — aborting queue push.")
                    break

                offset = end
            
            # Add sentinel
            try:
                self._playback_queue.put(None, timeout=2.0)
            except queue.Full:
                pass
            
            logger.debug(f"Playback queued: {total_samples} samples")

            try:
                # Wait for playback to finish (callback will clear _is_playing)
                # Max wait: duration + 2s buffer
                duration = total_samples / rate
                start_wait = time.time()
                
                # While playing, calculate amplitude for GUI (mocking original loop)
                # In the duplex model, the hardware loop is running in the background.
                # Here we just track progress for the visualizer.
                current_offset = 0
                while self._is_playing.is_set() and (time.time() - start_wait) < (duration + 2.0):
                    # Estimate amplitude for visualizer
                    if current_offset < total_samples:
                        end = min(current_offset + self._playback_chunk_samples, total_samples)
                        v_chunk = audio_data[current_offset:end]
                        rms = float(np.sqrt(np.mean(v_chunk.astype(np.float64) ** 2)))
                        amplitude = min(1.0, (rms / 32768.0) * 3.0)
                        self._bus.publish(Event(
                            type=EventType.AUDIO_AMPLITUDE,
                            source="audio_manager",
                            data={"amplitude": amplitude},
                        ))
                        current_offset += self._playback_chunk_samples
                    
                    time.sleep(self._config.audio_chunk_ms / 1000.0)

                elapsed_wait = time.time() - start_wait
                logger.info(
                    f"PLAY_AUDIO BLOCKING WAIT COMPLETE: played {total_samples} samples "
                    f"(expected {duration:.2f}s, elapsed {elapsed_wait:.2f}s, is_playing={self._is_playing.is_set()})"
                )

            except Exception as e:
                logger.error(f"Audio playback error: {e}")
            finally:
                # Ensure amplitude is reset
                self._bus.publish(Event(
                    type=EventType.AUDIO_AMPLITUDE,
                    source="audio_manager",
                    data={"amplitude": 0.0},
                ))

    def play_audio_bytes(self, audio_bytes: bytes, sample_rate: int = 24000) -> None:
        if self._tts_muted.is_set():
            return

        if not audio_bytes or len(audio_bytes) == 0:
            logger.warning("play_audio_bytes received empty audio_bytes — skipping playback.")
            return

        import io
        import soundfile as sf

        try:
            audio_array, file_sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
            sample_rate = file_sample_rate
        except Exception:
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Skip play_audio_bytes device-rate resample: pass raw float32 array straight to play_audio
        self.play_audio(audio_array, sample_rate)

    def _get_output_device_rate(self, device_index: int | None = None) -> int | None:
        """Get the native sample rate of the given (or configured) output device."""
        try:
            if device_index is None:
                device_index = self._config.speaker_device_index
            if device_index is not None:
                info = sd.query_devices(device_index)
                return int(info["default_samplerate"])
        except Exception:
            pass
        return None

    def stop_playback(self) -> None:
        """Immediately stop any active audio playback."""
        # Clear playback queue
        while not self._playback_queue.empty():
            try: self._playback_queue.get_nowait()
            except queue.Empty: break
        self._is_playing.clear()

    @property
    def is_playing(self) -> bool:
        """Check if audio is currently being played."""
        return self._is_playing.is_set()

    def set_tts_muted(self, muted: bool) -> None:
        """Set TTS mute state."""
        if muted:
            self._tts_muted.set()
            self.stop_playback()
        else:
            self._tts_muted.clear()

    @property
    def is_tts_muted(self) -> bool:
        """Check if TTS is muted."""
        return self._tts_muted.is_set()

    def _on_halt(self, event: Event) -> None:
        """HALT handler — immediately stop all audio."""
        self.stop_playback()
        # Capture and playback are independent streams now, so this only
        # silences output — the mic keeps capturing uninterrupted.
        logger.info("HALT: Audio playback stopped (capture unaffected).")

    def shutdown(self) -> None:
        """Clean shutdown of all audio resources."""
        self.stop_playback()
        self.stop_capture()
        logger.info("AudioManager shut down.")


_audio_manager_instance: AudioManager | None = None
_audio_manager_lock = threading.Lock()


def get_audio_manager() -> AudioManager:
    """Get or create singleton AudioManager instance."""
    global _audio_manager_instance
    if _audio_manager_instance is None:
        with _audio_manager_lock:
            if _audio_manager_instance is None:
                _audio_manager_instance = AudioManager()
    return _audio_manager_instance
