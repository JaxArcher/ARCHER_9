"""
ARCHER Speech-to-Text (STT).

Supports two backends:
- Cloud: ElevenLabs streaming STT
- Local: Faster-Whisper (CUDA, float16) running on RTX 5080

The active backend is determined by the ToggleService before every request.
Auto-fallback from cloud to local on failure.
"""

from __future__ import annotations

import io
import threading
import time
from abc import ABC, abstractmethod

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.core.toggle import get_toggle_service


class STTBackend(ABC):
    """Abstract base class for STT backends."""

    @abstractmethod
    def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """Transcribe audio data to text."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available."""
        ...


class CloudSTT(STTBackend):
    """ElevenLabs cloud STT backend."""

    def __init__(self) -> None:
        self._config = get_config()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from elevenlabs import ElevenLabs
            self._client = ElevenLabs(api_key=self._config.elevenlabs_api_key)
        return self._client

    def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """Transcribe using ElevenLabs cloud STT (Scribe v2)."""
        try:
            client = self._get_client()

            # Convert raw PCM to WAV format for the API
            import wave
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data)
            wav_buffer.seek(0)

            # Use the speech-to-text API (requires SDK v2.29.0+)
            result = client.speech_to_text.convert(
                file=wav_buffer,
                model_id="scribe_v2",
                language_code="eng",
            )

            text = result.text if hasattr(result, "text") else str(result)
            logger.debug(f"Cloud STT result: '{text}'")
            return text.strip()

        except Exception as e:
            logger.error(f"Cloud STT error: {e}")
            raise

    def is_available(self) -> bool:
        return bool(self._config.elevenlabs_api_key)


class LocalSTT(STTBackend):
    """Faster-Whisper local STT backend (CUDA, float16)."""

    def __init__(self) -> None:
        self._config = get_config()
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(
                        self._config.stt_model,
                        device="cuda",
                        compute_type="float16",
                    )
                    logger.info(f"Faster-Whisper model loaded: {self._config.stt_model}")
        return self._model

    def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """Transcribe using Faster-Whisper locally."""
        try:
            model = self._get_model()

            # Convert bytes to float32 numpy array
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            segments, info = model.transcribe(
                audio_array,
                beam_size=5,
                language="en",
                vad_filter=True,
            )

            text = " ".join(segment.text for segment in segments).strip()
            logger.debug(f"Local STT result: '{text}'")
            return text

        except Exception as e:
            logger.error(f"Local STT error: {e}")
            raise

    def is_available(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False


class STTService:
    """
    Speech-to-text service with cloud/local toggle and auto-fallback.

    Reads the active mode from ToggleService before every transcription.
    If cloud fails, automatically falls back to local and notifies the user.
    """

    def __init__(self) -> None:
        self._cloud = CloudSTT()
        self._local = LocalSTT()
        self._toggle = get_toggle_service()
        self._bus = get_event_bus()

    def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """
        Transcribe audio data to text using the currently active backend.

        Args:
            audio_data: Raw PCM audio bytes (int16, mono)
            sample_rate: Sample rate of the audio

        Returns:
            Transcribed text string.
        """
        start_time = time.monotonic()

        if self._toggle.is_cloud and self._cloud.is_available():
            try:
                text = self._cloud.transcribe(audio_data, sample_rate)
                elapsed = (time.monotonic() - start_time) * 1000
                logger.info(f"STT (cloud) completed in {elapsed:.0f}ms")

                self._bus.publish(Event(
                    type=EventType.STT_FINAL,
                    source="stt",
                    data={"text": text, "backend": "cloud", "latency_ms": elapsed},
                ))
                return text

            except Exception as e:
                logger.warning(f"Cloud STT failed, falling back to local: {e}")
                self._toggle.fallback_to_local(reason=f"stt_error: {e}")

        # Local fallback
        try:
            text = self._local.transcribe(audio_data, sample_rate)
            elapsed = (time.monotonic() - start_time) * 1000
            logger.info(f"STT (local) completed in {elapsed:.0f}ms")

            self._bus.publish(Event(
                type=EventType.STT_FINAL,
                source="stt",
                data={"text": text, "backend": "local", "latency_ms": elapsed},
            ))
            return text

        except Exception as e:
            logger.error(f"All STT backends failed: {e}")
            return ""
