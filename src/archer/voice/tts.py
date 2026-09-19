"""
ARCHER Text-to-Speech (TTS).

Supports two backends:
- Cloud: ElevenLabs streaming TTS (low latency)
- Local: Chatterbox via Docker container (GPU-accelerated)

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


import re

def sanitize_text_for_tts(text: str) -> str:
    """
    Sanitize text before TTS synthesis.
    Strips markdown formatting, headers, bullet points, asterisks, hash signs, and emojis
    to prevent TTS from reading raw formatting literal names ("asterisk", "hash", "smiley face").
    """
    if not text:
        return ""
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    t = re.sub(r'[\U00010000-\U0010ffff]', '', t)
    t = re.sub(r'^#+\s*', '', t, flags=re.MULTILINE)
    t = re.sub(r'[*_`~]+', '', t)
    t = re.sub(r'^\s*[-*+]\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'^\s*\d+\.\s+', '', t, flags=re.MULTILINE)
    # Normalize "smart"/typographic punctuation the LLM commonly emits
    # (curly quotes, en/em dashes, ellipsis character) down to plain ASCII.
    # Kokoro's phonemizer has occasionally raised on specific words when
    # they contain a curly apostrophe (e.g. "can't" with U+2019 instead of
    # a straight U+0027) — cheap to normalize up front rather than debug
    # per-word phonemizer failures.
    _SMART_PUNCT = {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "–": "-", "—": "-", "…": "...",
    }
    for smart, plain in _SMART_PUNCT.items():
        t = t.replace(smart, plain)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


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
        text = sanitize_text_for_tts(text)
        if not text:
            return b"", 24000
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
    """Local TTS backend using Kokoro-82M neural engine (with HTTP fallback)."""

    def __init__(self) -> None:
        self._config = get_config()
        self._kokoro_pipeline = None
        self._init_kokoro()

    def _init_kokoro(self) -> None:
        try:
            from kokoro import KPipeline
            self._kokoro_pipeline = KPipeline(lang_code="a")
            logger.info("LocalTTS initialized with Kokoro-82M neural engine.")
        except BaseException as e:
            logger.warning(f"Failed to initialize Kokoro pipeline: {e}. Falling back to HTTP.")

    @staticmethod
    def _strip_to_ascii_safe(text: str) -> str:
        """
        Last-resort fallback text: drop anything outside plain ASCII
        letters/digits/basic punctuation. Used only as a retry after the
        original (already-sanitized) text fails Kokoro's phonemizer —
        catches stray unicode Kokoro's G2P dictionary chokes on that
        sanitize_text_for_tts's known-character replacements didn't cover.
        """
        return re.sub(r"[^A-Za-z0-9 .,!?'\-]", "", text).strip()

    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Synthesize text using Kokoro-82M neural TTS engine."""
        text = sanitize_text_for_tts(text)
        if not text:
            return b"", 24000
        import io
        import time
        import numpy as np
        import soundfile as sf

        if self._kokoro_pipeline is not None:
            for attempt_text in (text, self._strip_to_ascii_safe(text)):
                if not attempt_text:
                    continue
                try:
                    generator = self._kokoro_pipeline(attempt_text, voice="am_onyx")
                    chunks = [chunk[2] for chunk in generator]
                    if not chunks:
                        logger.warning(f"Kokoro produced 0 audio chunks for text: '{attempt_text}'")
                        continue

                    audio_float = np.concatenate(chunks).astype(np.float32)
                    buf = io.BytesIO()
                    sf.write(buf, audio_float, 24000, format="WAV")
                    audio_bytes = buf.getvalue()

                    # Save unique debug dump with timestamp
                    try:
                        import os
                        os.makedirs("scratch", exist_ok=True)
                        ts = int(time.time() * 1000)
                        with open(f"scratch/raw_chatterbox_response_{ts}.wav", "wb") as f:
                            f.write(audio_bytes)
                    except Exception:
                        pass

                    return audio_bytes, 24000
                except Exception as e:
                    # Log the exact text that broke synthesis — this is the
                    # only way to root-cause phonemizer failures on specific
                    # words/punctuation rather than guessing after the fact.
                    logger.error(f"Kokoro neural synthesis error on text '{attempt_text}': {e}")
                    if attempt_text == text:
                        logger.info("Retrying Kokoro synthesis with ASCII-stripped text...")
                        continue
                    break

        # Fallback to HTTP server if Kokoro pipeline is unavailable
        import httpx
        try:
            response = httpx.post(
                f"{self._config.chatterbox_url}/synthesize",
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
        if self._kokoro_pipeline is not None:
            return True
        import httpx
        try:
            response = httpx.get(
                f"{self._config.chatterbox_url}/health",
                timeout=2.0,
            )
            return response.status_code == 200
        except Exception:
            return False


# Pre-recorded conversational fillers
FILLER_PHRASES = [
    "Let me think about that. Just a second.",
    "One moment while I look into this.",
    "Hummmmmmm... Let me check on that",
    "Hummmm",
    "Just a sec while I look into it",
    "I'm right on top of that",
    "One sec.... Checking...",
]

# Verbal acknowledgment played immediately after wake word detection —
# gives audible confirmation that ARCHER is listening, so the user isn't
# relying on the orb or a terminal log to know it heard them.
# Kept to at least 5 words each — a single word or two is easy to miss,
# especially if the user is still mid-sentence saying the wake word itself.
WAKE_ACK_PHRASES = [
    "Yeah, what's up? I'm listening.",
    "I'm here — how may I help you?",
    "How can I help you today?",
    "You rang? What's on your mind?",
    "Yes sir, what can I do for you?",
    "Go ahead, sir. I'm here.",
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

        if self._toggle.is_cloud_tts and self._cloud.is_available():
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
                self._toggle.fallback_tts_to_local(reason=f"tts_error: {e}")

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

    def get_wake_ack_text(self) -> str:
        """Get a random wake-word acknowledgment phrase."""
        return random.choice(WAKE_ACK_PHRASES)

    def cancel(self) -> None:
        """Cancel any pending TTS synthesis."""
        self._cancelled.set()

    def reset_cancel(self) -> None:
        """Clear a pending cancellation flag before a NEW turn starts
        speaking. Added 2026-09-17: _process_utterance() (pipeline.py)
        calls cancel() unconditionally at the start of every utterance to
        stop a PREVIOUS turn's straggling audio -- but the flag was only
        ever cleared lazily, inside synthesize() itself, on whichever call
        happened to run next. That meant it was silently eaten by the NEW
        turn's own first synthesize() call instead of the old turn it was
        meant for, dropping the first sentence of every single response
        (confirmed live: only sentence 2+ of each reply was ever spoken).
        _speak_response_streaming calls this once, right as a turn's
        speaking phase actually begins, before its first synthesize() call."""
        self._cancelled.clear()

    def _on_halt(self, event: Event) -> None:
        """HALT handler — cancel all TTS."""
        self.cancel()
        logger.info("HALT: TTS cancelled.")
