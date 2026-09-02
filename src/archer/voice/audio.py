"""
ARCHER Audio I/O Management.

Manages microphone capture and speaker playback using sounddevice.
Runs the microphone capture in its own dedicated thread. Provides
thread-safe queues for audio data flow.

This module is the ONLY component that directly accesses audio hardware.
All other voice pipeline components receive audio data through queues.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd
from loguru import logger

try:
    import pyaec
except ImportError:
    pyaec = None

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
        self._capture_stream: sd.Stream | None = None
        self._aec = None
        self._playback_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=10000)

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
            if pyaec:
                self._aec = pyaec.Aec(
                    frame_size=self._chunk_samples,
                    filter_length=self._chunk_samples * 10,  # 300ms filter
                    sample_rate=self._sample_rate,
                    enable_preprocess=False
                )
                logger.info("AEC initialized (Speex via pyaec, preprocess=False)")
            else:
                logger.warning("pyaec not found — Echo cancellation disabled")

            self._capture_stream = sd.Stream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                blocksize=self._chunk_samples,
                device=(device_index, self._config.speaker_device_index),
                callback=self._audio_callback,
            )
            self._capture_stream.start()
            mic_name = "Default System Mic"
            speaker_name = "Default System Speaker"
            try:
                devs = sd.query_devices()
                if device_index is not None and device_index < len(devs):
                    mic_name = devs[device_index]["name"]
                elif sd.default.device[0] is not None and sd.default.device[0] < len(devs):
                    mic_name = devs[sd.default.device[0]]["name"]
                
                spk_idx = self._config.speaker_device_index
                if spk_idx is not None and spk_idx < len(devs):
                    speaker_name = devs[spk_idx]["name"]
                elif sd.default.device[1] is not None and sd.default.device[1] < len(devs):
                    speaker_name = devs[sd.default.device[1]]["name"]
            except Exception:
                pass

            logger.info(
                f"Audio stream started (mic={device_index} ['{mic_name}'], "
                f"speaker={self._config.speaker_device_index} ['{speaker_name}'], "
                f"rate={self._sample_rate}, chunk={self._chunk_samples} samples)"
            )
        except Exception as e:
            self._is_capturing.clear()
            logger.error(f"Failed to start audio stream: {e}")
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
        outdata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """
        Called by sounddevice for each audio chunk.
        Handles both capture (with AEC) and playback from the queue.
        """
        if status:
            logger.warning(f"Audio callback status: {status}")

        # 1. Output (Playback)
        ref_chunk = np.zeros((frames, self._channels), dtype="int16")
        if self._is_playing.is_set():
            try:
                chunk = self._playback_queue.get_nowait()
                if chunk is not None:
                    # chunk is already resampled to 16k and sliced
                    ref_chunk[:] = chunk
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

        # 2. Input (Capture) + AEC
        if self._is_capturing.is_set():
            if self._aec and self._is_playing.is_set():
                # pyaec expects int16 bytes and returns a list of 8-bit byte ints
                clean_bytes_list = self._aec.cancel_echo(indata.tobytes(), ref_chunk.tobytes())
                clean_bytes = bytes(x & 0xFF for x in clean_bytes_list)
                audio_to_push = clean_bytes
            else:
                # No playback or no AEC — use raw mic input
                audio_to_push = indata.tobytes()

            try:
                self._audio_queue.put_nowait(audio_to_push)
            except queue.Full:
                try:
                    self._audio_queue.get_nowait()
                    self._audio_queue.put_nowait(audio_to_push)
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

        # Always work at the pipeline rate (16000) for AEC consistency
        rate = self._sample_rate
        input_dtype = audio_data.dtype
        input_shape = audio_data.shape
        
        # If input rate doesn't match pipeline rate, resample in float32 FIRST
        resample_executed = False
        if sample_rate and sample_rate != rate:
            resample_executed = True
            ratio = rate / sample_rate
            n_out = int(len(audio_data) * ratio)
            indices = np.linspace(0, len(audio_data) - 1, n_out)
            audio_data = np.interp(
                indices, np.arange(len(audio_data)), audio_data
            ).astype(np.float32)
            sample_rate = rate

        # Ensure data is int16 for the callback
        if audio_data.dtype != np.int16:
            if audio_data.dtype == np.float32 or audio_data.dtype == np.float64:
                audio_data = (audio_data * 32767.0).astype(np.int16)

        device_rate_val = self._get_output_device_rate()

        logger.info(
            f"PLAY_AUDIO DUMP LOG:\n"
            f"  - input_dtype: {input_dtype}, input_shape: {input_shape}\n"
            f"  - audio_data.dtype: {audio_data.dtype}, audio_data.shape: {audio_data.shape}\n"
            f"  - sample_rate_param: {sample_rate}\n"
            f"  - rate (self._sample_rate): {rate}\n"
            f"  - resample_executed: {resample_executed}\n"
            f"  - device_rate (_get_output_device_rate()): {device_rate_val}\n"
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
            
            # Slice into chunks of self._chunk_samples
            # If mono, ensure (N, 1) shape for sounddevice duplex
            if audio_data.ndim == 1:
                audio_data = audio_data.reshape(-1, 1)
            
            total_samples = len(audio_data)
            offset = 0

            # Set playing flag BEFORE chunking so the hardware callback can actively drain
            self._is_playing.set()

            while offset < total_samples:
                end = min(offset + self._chunk_samples, total_samples)
                chunk = audio_data[offset:end]
                # Pad last chunk if needed
                if len(chunk) < self._chunk_samples:
                    chunk = np.pad(chunk, ((0, self._chunk_samples - len(chunk)), (0, 0)))
                
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
                        end = min(current_offset + self._chunk_samples, total_samples)
                        v_chunk = audio_data[current_offset:end]
                        rms = float(np.sqrt(np.mean(v_chunk.astype(np.float64) ** 2)))
                        amplitude = min(1.0, (rms / 32768.0) * 3.0)
                        self._bus.publish(Event(
                            type=EventType.AUDIO_AMPLITUDE,
                            source="audio_manager",
                            data={"amplitude": amplitude},
                        ))
                        current_offset += self._chunk_samples
                    
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

        import io
        import soundfile as sf

        try:
            audio_array, file_sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
            sample_rate = file_sample_rate
        except Exception:
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Skip play_audio_bytes device-rate resample: pass raw float32 array straight to play_audio
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
        # No sd.stop() here as it would stop the capture stream too if using duplex.
        # Duplex stream stays open, but we send silence.
        logger.info("HALT: Audio playback stopped (AEC duplex retained).")

    def shutdown(self) -> None:
        """Clean shutdown of all audio resources."""
        self.stop_playback()
        self.stop_capture()
        logger.info("AudioManager shut down.")
