"""
ARCHER Wake Word Detection.

Uses openWakeWord. Runs all available built-in models simultaneously
(alexa, hey_jarvis, hey_mycroft, hey_rhasspy) so you can use any of
those phrases to wake ARCHER. Runs on CPU continuously.

Wake word detection runs in its own thread, consuming audio from the
AudioManager queue and publishing WAKE_WORD_DETECTED events.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus


class WakeWordDetector:
    """
    Detects the 'Hey ARCHER' wake word using openWakeWord.

    Runs on CPU. Consumes audio chunks and fires events when
    the wake word is detected above the confidence threshold.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._threshold = self._config.wake_word_threshold
        self._running = threading.Event()
        self._model = None

    def initialize(self) -> None:
        """Load the wake word model. Must be called before start()."""
        try:
            import openwakeword
            from openwakeword.model import Model

            # Download default models if not present
            openwakeword.utils.download_models()

            # Run ALL available built-in models simultaneously.
            # Since there's no "hey_archer" model, any of these phrases will
            # trigger ARCHER: "Alexa", "Hey Jarvis", "Hey Mycroft", "Hey Rhasspy".
            _all_models = ["alexa", "hey_jarvis", "hey_mycroft", "hey_rhasspy"]

            self._model = Model(
                wakeword_models=_all_models,
                inference_framework="onnx",
            )
            logger.info(
                f"Wake word models loaded: {_all_models}. "
                "Say 'Alexa', 'Hey Jarvis', 'Hey Mycroft', or 'Hey Rhasspy' to wake ARCHER."
            )
        except Exception as e:
            logger.error(f"Failed to initialize wake word detector: {e}")
            raise

    def process_audio(self, audio_chunk: bytes) -> bool:
        """
        Process an audio chunk for wake word detection.

        Args:
            audio_chunk: Raw PCM audio bytes (int16, 16kHz, mono)

        Returns:
            True if wake word was detected above threshold.
        """
        if self._model is None:
            return False

        # Convert bytes to numpy array
        audio_array = np.frombuffer(audio_chunk, dtype=np.int16)

        # Feed to model
        self._model.predict(audio_array)

        # Check all wake word scores
        for model_name, score in self._model.prediction_buffer.items():
            current_score = score[-1] if len(score) > 0 else 0.0
            if current_score >= self._threshold:
                logger.info(f"Wake word detected! (model={model_name}, score={current_score:.3f})")
                self._model.reset()

                self._bus.publish(Event(
                    type=EventType.WAKE_WORD_DETECTED,
                    source="wake_word",
                    data={
                        "model": model_name,
                        "confidence": float(current_score),
                    },
                ))
                return True

        return False

    def reset(self) -> None:
        """Reset the wake word detection buffer."""
        if self._model is not None:
            self._model.reset()
