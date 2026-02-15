"""
ARCHER Text-to-Speech (TTS).

Supports two backends:
- Cloud: ElevenLabs streaming TTS (low latency)
- Local: IndexTTS2 via Docker container (GPU-accelerated)

Sentence-level streaming: pipe first sentence to TTS before the full
LLM response is complete. Do not wait for the full response.

If the agent call hasn't returned a first token in 600ms, play an audio
filler ('Let me think about that...', 'One moment...').
"""

from __future__ import annotations

import io
import os
import random
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.core.toggle import get_toggle_service


class TTSBackend(ABC):
    """Abstract base class for TTS backends."""

    @abstractmethod
    def synthesize(self, text: str) -> tuple[bytes, int]:
        """
        Synthesize text to audio.

        Returns:
            Tuple of (audio_bytes, sample_rate)
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available."""
        ...


class CloudTTS(TTSBackend):
    """ElevenLabs cloud TTS backend with streaming support."""

    def __init__(self) -> None:
        self._config = get_config()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from elevenlabs import ElevenLabs
            self._client = ElevenLabs(api_key=self._config.elevenlabs_api_key)
        return self._client

    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Synthesize text using ElevenLabs streaming TTS."""
        try:
            client = self._get_client()

            # Use streaming for low latency
            audio_generator = client.text_to_speech.convert(
                voice_id=self._config.elevenlabs_voice_id,
                text=text,
                model_id="eleven_turbo_v2_5",
                output_format="pcm_24000",
            )

            # Collect all audio chunks
            audio_chunks = []
            for chunk in audio_generator:
                if isinstance(chunk, bytes):
                    audio_chunks.append(chunk)

            audio_bytes = b"".join(audio_chunks)
            return audio_bytes, 24000

        except Exception as e:
            logger.error(f"Cloud TTS error: {e}")
            raise

    def is_available(self) -> bool:
        return bool(self._config.elevenlabs_api_key)


class LocalTTS(TTSBackend):
    """IndexTTS2 local TTS backend via Docker container."""

    def __init__(self) -> None:
        self._config = get_config()

    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Synthesize text using the local IndexTTS2 Docker container."""
        import httpx

        try:
            response = httpx.post(
                f"{self._config.indextts_url}/synthesize",
                json={"text": text},
                timeout=30.0,
            )
            response.raise_for_status()

            audio_bytes = response.content
            sample_rate = int(response.headers.get("X-Sample-Rate", "24000"))
            return audio_bytes, sample_rate

        except Exception as e:
            logger.error(f"Local TTS error: {e}")
            raise

    def is_available(self) -> bool:
        import httpx
        try:
            response = httpx.get(
                f"{self._config.indextts_url}/health",
                timeout=2.0,
            )
            return response.status_code == 200
        except Exception:
            return False


# Pre-recorded conversational fillers
FILLER_PHRASES = [
    "Let me think about that...",
    "One moment...",
    "Hmm...",
    "Let me check on that...",
    "Just a sec...",
]


class TTSService:
    """
    Text-to-speech service with cloud/local toggle, auto-fallback,
    and conversational filler support.

    Supports sentence-level streaming: each sentence is synthesized
    as soon as it's available from the LLM, not waiting for the full response.
    """

    def __init__(self) -> None:
        self._cloud = CloudTTS()
        self._local = LocalTTS()
        self._toggle = get_toggle_service()
        self._bus = get_event_bus()
        self._config = get_config()
        self._cancelled = threading.Event()

        # Register HALT handler
        self._bus.subscribe_halt(self._on_halt)

    def synthesize(self, text: str) -> tuple[bytes, int] | None:
        """
        Synthesize text to audio using the active backend.
        Returns None if cancelled by HALT.

        Returns:
            Tuple of (audio_bytes, sample_rate) or None if cancelled.
        """
        if self._cancelled.is_set():
            self._cancelled.clear()
            return None

        start_time = time.monotonic()

        self._bus.publish(Event(
            type=EventType.TTS_START,
            source="tts",
            data={"text": text},
        ))

        if self._toggle.is_cloud and self._cloud.is_available():
            try:
                audio_bytes, sample_rate = self._cloud.synthesize(text)
                elapsed = (time.monotonic() - start_time) * 1000
                logger.info(f"TTS (cloud) completed in {elapsed:.0f}ms")

                self._bus.publish(Event(
                    type=EventType.TTS_END,
                    source="tts",
                    data={"backend": "cloud", "latency_ms": elapsed},
                ))
                return audio_bytes, sample_rate

            except Exception as e:
                logger.warning(f"Cloud TTS failed, falling back to local: {e}")
                self._toggle.fallback_to_local(reason=f"tts_error: {e}")

        # Local fallback
        try:
            audio_bytes, sample_rate = self._local.synthesize(text)
            elapsed = (time.monotonic() - start_time) * 1000
            logger.info(f"TTS (local) completed in {elapsed:.0f}ms")

            self._bus.publish(Event(
                type=EventType.TTS_END,
                source="tts",
                data={"backend": "local", "latency_ms": elapsed},
            ))
            return audio_bytes, sample_rate

        except Exception as e:
            logger.error(f"All TTS backends failed: {e}")
            return None

    def get_filler_text(self) -> str:
        """Get a random conversational filler phrase."""
        return random.choice(FILLER_PHRASES)

    def cancel(self) -> None:
        """Cancel any pending TTS synthesis."""
        self._cancelled.set()

    def _on_halt(self, event: Event) -> None:
        """HALT handler — cancel all TTS."""
        self.cancel()
        logger.info("HALT: TTS cancelled.")
