"""
ARCHER Voice Activity Detection (VAD).

Uses webrtcvad to determine when the user is speaking vs silence.
Prevents STT from processing silence — reduces unnecessary API calls
and GPU usage.

VAD runs inline with the audio pipeline (not its own thread) because
it needs to gate audio frames in real-time with < 10ms latency.
"""

from __future__ import annotations

import collections
import threading

import webrtcvad
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus


class VoiceActivityDetector:
    """
    Detects speech activity using webrtcvad.

    Uses a ring buffer of frames to smooth the detection. Fires
    VAD_SPEECH_START when speech begins and VAD_SPEECH_END when
    it stops (after a configurable silence duration).
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._bus = get_event_bus()

        # Initialize webrtcvad
        # Aggressiveness 3 rejects nearly all speech on low-gain mics.
        # Cap at 2 to ensure reliable detection across consumer hardware.
        aggressiveness = min(self._config.vad_aggressiveness, 2)
        self._vad = webrtcvad.Vad(aggressiveness)
        logger.debug(f"VAD initialized: aggressiveness={aggressiveness}")

        # State
        self._is_speaking = False
        self._ring_buffer: collections.deque[tuple[bytes, bool]] = collections.deque(
            maxlen=10  # ~300ms of frames at 30ms each (fast onset detection)
        )

        # Thresholds — tuned for consumer mics with moderate gain.
        # Speech onset: 50% of ring buffer (5/10 frames = 150ms of speech).
        # Silence offset: kept higher so brief pauses don't end the utterance.
        self._speech_threshold = 0.5
        self._silence_threshold = 0.8

        # Frame parameters
        self._sample_rate = self._config.sample_rate
        self._frame_duration_ms = self._config.audio_chunk_ms

    def process_audio(self, audio_chunk: bytes) -> bool:
        """
        Process an audio frame for voice activity.

        Args:
            audio_chunk: Raw PCM audio bytes (int16, 16kHz, mono).
                         Must be exactly 10, 20, or 30ms of audio.

        Returns:
            True if speech is currently active.
        """
        # webrtcvad requires specific frame sizes
        frame_length = 2 * int(self._sample_rate * self._frame_duration_ms / 1000)

        # Ensure we have the right frame size
        if len(audio_chunk) != frame_length:
            # Pad or truncate
            if len(audio_chunk) < frame_length:
                audio_chunk = audio_chunk + b"\x00" * (frame_length - len(audio_chunk))
            else:
                audio_chunk = audio_chunk[:frame_length]

        try:
            is_speech = self._vad.is_speech(audio_chunk, self._sample_rate)
        except Exception:
            return self._is_speaking

        self._ring_buffer.append((audio_chunk, is_speech))

        if not self._is_speaking:
            # Not currently speaking — check if speech has started
            num_voiced = sum(1 for _, speech in self._ring_buffer if speech)
            if num_voiced > self._speech_threshold * self._ring_buffer.maxlen:
                self._is_speaking = True
                logger.debug("VAD: Speech detected")
                self._bus.publish(Event(
                    type=EventType.VAD_SPEECH_START,
                    source="vad",
                ))
        else:
            # Currently speaking — check if silence has started
            num_unvoiced = sum(1 for _, speech in self._ring_buffer if not speech)
            if num_unvoiced > self._silence_threshold * self._ring_buffer.maxlen:
                self._is_speaking = False
                logger.debug("VAD: Silence detected")
                self._bus.publish(Event(
                    type=EventType.VAD_SPEECH_END,
                    source="vad",
                ))
                self._ring_buffer.clear()

        return self._is_speaking

    @property
    def is_speaking(self) -> bool:
        """Check if speech is currently active."""
        return self._is_speaking

    def reset(self) -> None:
        """Reset VAD state."""
        self._is_speaking = False
        self._ring_buffer.clear()
