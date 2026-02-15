"""
ARCHER Audio I/O Management.

Manages microphone capture and speaker playback using sounddevice.
Runs the microphone capture in its own dedicated thread. Provides
thread-safe queues for audio data flow.

This module is the ONLY component that directly accesses audio hardware.
All other voice pipeline components receive audio data through queues.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd
from loguru import logger

from archer.config import get_config
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

        # Thread-safe audio queue for downstream consumers
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)

        # Playback control
        self._is_playing = threading.Event()
        self._playback_lock = threading.Lock()

        # Capture control
        self._is_capturing = threading.Event()
        self._capture_stream: sd.InputStream | None = None

        # TTS mute
        self._tts_muted = threading.Event()

        # Register HALT handler
        self._bus.subscribe_halt(self._on_halt)

    def start_capture(self) -> None:
        """Start microphone capture. Runs in a dedicated thread."""
        if self._is_capturing.is_set():
            logger.warning("Audio capture already running.")
            return

        self._is_capturing.set()

        device_index = self._config.mic_device_index

        try:
            self._capture_stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                blocksize=self._chunk_samples,
                device=device_index,
                callback=self._audio_callback,
            )
            self._capture_stream.start()
            logger.info(
                f"Audio capture started (device={device_index}, "
                f"rate={self._sample_rate}, chunk={self._chunk_samples} samples)"
            )
        except Exception as e:
            self._is_capturing.clear()
            logger.error(f"Failed to start audio capture: {e}")
            raise

    def stop_capture(self) -> None:
        """Stop microphone capture."""
        self._is_capturing.clear()
        if self._capture_stream is not None:
            try:
                self._capture_stream.stop()
                self._capture_stream.close()
            except Exception as e:
                logger.warning(f"Error stopping audio capture: {e}")
            finally:
                self._capture_stream = None
        logger.info("Audio capture stopped.")

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """
        Called by sounddevice for each audio chunk.
        Converts to bytes and pushes to the audio queue.
        """
        if status:
            logger.warning(f"Audio callback status: {status}")

        if self._is_capturing.is_set():
            audio_bytes = indata.tobytes()
            try:
                self._audio_queue.put_nowait(audio_bytes)
            except queue.Full:
                # Drop oldest frame to avoid backpressure
                try:
                    self._audio_queue.get_nowait()
                    self._audio_queue.put_nowait(audio_bytes)
                except queue.Empty:
                    pass

    def get_audio_chunk(self, timeout: float = 0.1) -> bytes | None:
        """Get the next audio chunk from the capture queue. Returns None on timeout."""
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

        rate = sample_rate or self._sample_rate
        device_index = self._config.speaker_device_index

        with self._playback_lock:
            self._is_playing.set()
            try:
                sd.play(audio_data, samplerate=rate, device=device_index)

                # Compute and publish amplitude during playback (~30fps)
                total_samples = len(audio_data)
                duration = total_samples / rate
                chunk_duration = 1.0 / 30.0  # ~33ms per amplitude update
                chunk_size = int(rate * chunk_duration)
                offset = 0

                while self._is_playing.is_set() and offset < total_samples:
                    end = min(offset + chunk_size, total_samples)
                    chunk = audio_data[offset:end]

                    # RMS amplitude (0.0 – 1.0)
                    if len(chunk) > 0:
                        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
                        # Clamp to 0-1 range (float32 audio is already -1..1)
                        amplitude = min(1.0, rms * 3.0)  # Amplify for visual effect
                        self._bus.publish(Event(
                            type=EventType.AUDIO_AMPLITUDE,
                            source="audio_manager",
                            data={"amplitude": amplitude},
                        ))

                    offset = end
                    time.sleep(chunk_duration)

                # Reset amplitude to 0 when playback ends
                self._bus.publish(Event(
                    type=EventType.AUDIO_AMPLITUDE,
                    source="audio_manager",
                    data={"amplitude": 0.0},
                ))

                sd.wait()
            except Exception as e:
                logger.error(f"Audio playback error: {e}")
            finally:
                self._is_playing.clear()

    def play_audio_bytes(self, audio_bytes: bytes, sample_rate: int = 24000) -> None:
        """Play raw PCM audio bytes (int16, mono).

        If the source sample rate doesn't match the output device's native rate,
        the audio is resampled using linear interpolation to avoid
        PaErrorCode -9997 (Invalid sample rate) on WASAPI devices.
        """
        if self._tts_muted.is_set():
            return

        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Resample if the output device doesn't support the source rate.
        device_rate = self._get_output_device_rate()
        if device_rate and device_rate != sample_rate:
            ratio = device_rate / sample_rate
            n_out = int(len(audio_array) * ratio)
            indices = np.linspace(0, len(audio_array) - 1, n_out)
            audio_array = np.interp(
                indices, np.arange(len(audio_array)), audio_array
            ).astype(np.float32)
            sample_rate = device_rate

        self.play_audio(audio_array, sample_rate)

    def _get_output_device_rate(self) -> int | None:
        """Get the native sample rate of the configured output device."""
        try:
            device_index = self._config.speaker_device_index
            if device_index is not None:
                info = sd.query_devices(device_index)
                return int(info["default_samplerate"])
        except Exception:
            pass
        return None

    def stop_playback(self) -> None:
        """Immediately stop any active audio playback."""
        sd.stop()
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
        logger.info("HALT: Audio playback stopped.")

    def shutdown(self) -> None:
        """Clean shutdown of all audio resources."""
        self.stop_playback()
        self.stop_capture()
        logger.info("AudioManager shut down.")
