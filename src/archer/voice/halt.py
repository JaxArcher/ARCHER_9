"""
ARCHER HALT Command Listener.

The HALT command is the highest-priority element in the voice processing loop.
It runs as a PARALLEL listener alongside the normal VAD/STT loop — it does NOT
wait for a wake word.

This is a second, lightweight, always-running speech detection thread dedicated
solely to the HALT phrase. If ARCHER is autonomously controlling the screen and
the user's hands are not on the keyboard, the voice HALT is their only reliable
escape.

When 'ARCHER HALT' is detected:
1. All queued TTS is stopped
2. All queued pyautogui actions are cancelled
3. All active Playwright sessions are closed
4. All pending agent calls are dropped
5. The orb turns red for 1 second then returns to idle
6. ARCHER confirms verbally: 'Stopped.' — one word, then silence

HALT does not clear conversation history or memory.
After a HALT, ARCHER is immediately ready for a new wake word.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus


class HaltListener:
    """
    Always-running listener for the HALT command.

    Uses a lightweight keyword detection approach. Runs in its own
    dedicated thread, separate from the main voice pipeline.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._halt_phrase = self._config.halt_phrase.lower()
        self._running = threading.Event()

        # Use a simple keyword spotter — openWakeWord with a custom model
        # For Phase 1, we use the STT engine to detect HALT in transcribed text
        self._model = None

    def initialize(self) -> None:
        """Initialize the HALT detection model."""
        # NOTE: Audio-based HALT keyword spotting is disabled for Phase 1.
        # It would need a custom "archer halt" wake word model to avoid
        # false triggers from the same hey_jarvis model used for wake word.
        # HALT still works via:
        #   1. Text-based detection in STT output (check_text_for_halt)
        #   2. GUI HALT button (trigger_halt_from_gui)
        self._model = None
        logger.info("HALT listener initialized (text-based + GUI button)")

    def check_text_for_halt(self, text: str) -> bool:
        """
        Check if transcribed text contains the HALT command.
        This is the primary HALT detection method — it runs on every
        STT result, even partial ones.
        """
        normalized = text.lower().strip()
        halt_variants = [
            "archer halt",
            "archer, halt",
            "archer stop",
            "halt",
        ]

        for variant in halt_variants:
            if variant in normalized:
                logger.warning(f"HALT detected in text: '{text}'")
                self._trigger_halt()
                return True

        return False

    def process_audio(self, audio_chunk: bytes) -> bool:
        """
        Process audio for HALT keyword detection (parallel to main pipeline).
        Returns True if HALT was detected.
        """
        if self._model is None:
            return False

        audio_array = np.frombuffer(audio_chunk, dtype=np.int16)

        try:
            self._model.predict(audio_array)
            # Check scores — in production this would check for "archer halt"
            for model_name, score in self._model.prediction_buffer.items():
                current_score = score[-1] if len(score) > 0 else 0.0
                if current_score >= 0.7:  # Higher threshold for HALT
                    self._trigger_halt()
                    self._model.reset()
                    return True
        except Exception:
            pass

        return False

    def _trigger_halt(self) -> None:
        """Execute the HALT sequence."""
        logger.warning("⛔ HALT TRIGGERED — Stopping all operations")

        self._bus.publish_halt(source="halt_listener")

        # The event bus HALT handlers in each component will:
        # 1. Stop TTS playback
        # 2. Cancel queued pyautogui actions
        # 3. Close Playwright sessions
        # 4. Drop pending agent calls

    def trigger_halt_from_gui(self) -> None:
        """Called when the GUI HALT button is pressed."""
        self._trigger_halt()
