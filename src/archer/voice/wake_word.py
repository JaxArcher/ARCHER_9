"""
ARCHER Wake Word Detection.

"Hey ARCHER" and "ARCHER" (Claude, 2026-10-20; Col approved the add-on):
sherpa-onnx's open-vocabulary keyword spotter, a small streaming speech model
(zipformer, GigaSpeech, ~3.3M parameters, Apache 2.0) that spots any phrase
without training. Model files live in data/models/kws (int8 encoder, decoder,
joiner and tokens.txt). In synthetic-voice tests (Piper, 4 voices) "Hey
ARCHER" was caught 8/8 with no false wakes; bare "ARCHER" 11/12, and it also
wakes when "archer" is really said (e.g. on TV). Switch the bare word off
with ARCHER_WAKE_BARE_ARCHER=false.

openWakeWord's stock "Hey Jarvis" stays as a backup (ARCHER_WAKE_STOCK_MODELS;
"Alexa", "Hey Mycroft" and "Hey Rhasspy" are no longer loaded by default).

Runs on CPU continuously. process_audio() is fed every 30 ms chunk by the
voice pipeline and publishes WAKE_WORD_DETECTED events.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus

KWS_MODEL_DIR = Path(__file__).resolve().parents[3] / "data" / "models" / "kws"
_KWS_FILES = {
    "tokens": "tokens.txt",
    "encoder": "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    "decoder": "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    "joiner": "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
}
# The phrases as the model's sub-word pieces (sherpa_onnx.text2token with the
# model's bpe.model, 2026-10-20), so no tokenizer is needed at run time.
_KWS_HEY_ARCHER = "\u2581HE Y \u2581A R CH ER @HEY_ARCHER"
_KWS_ARCHER = "\u2581A R CH ER @ARCHER"
# Heard within this long after ARCHER's own audio stopped, the name is ARCHER
# hearing itself ("ARCHER online"), not Col.
_OWN_AUDIO_GRACE_S = 1.5


def kws_keywords(bare_archer: bool) -> list[str]:
    """Keyword lines for the spotter: "Hey ARCHER", plus bare "ARCHER" if enabled."""
    return [_KWS_HEY_ARCHER] + ([_KWS_ARCHER] if bare_archer else [])


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
        self._kws = None
        self._kws_stream = None
        self._own_audio_at = 0.0  # last time ARCHER itself was playing audio

    def initialize(self) -> None:
        """Load the wake word models. Must be called before start()."""
        self._init_kws()
        stock = [m.strip() for m in str(getattr(self._config, "wake_stock_models", "hey_jarvis")).split(",") if m.strip()]
        if stock:
            try:
                import openwakeword
                from openwakeword.model import Model

                # Download default models if not present
                openwakeword.utils.download_models()
                self._model = Model(wakeword_models=stock, inference_framework="onnx")
                logger.info(f"Backup wake words (openWakeWord): {stock}.")
            except Exception as e:
                logger.error(f"Failed to initialize openWakeWord: {e}")
                if self._kws is None:
                    raise
        if self._kws is None and self._model is None:
            raise RuntimeError("No wake word detector could be loaded.")

    def _init_kws(self) -> None:
        """Load the "Hey ARCHER" keyword spotter; best-effort (the backup words still work)."""
        try:
            import sherpa_onnx

            files = {k: KWS_MODEL_DIR / v for k, v in _KWS_FILES.items()}
            missing = [str(p.name) for p in files.values() if not p.exists()]
            if missing:
                logger.warning(f"'Hey ARCHER' unavailable: model files missing in {KWS_MODEL_DIR} ({missing}).")
                return
            bare = bool(getattr(self._config, "wake_bare_archer", True))
            keywords_file = KWS_MODEL_DIR / "archer_keywords.txt"
            keywords_file.write_text("\n".join(kws_keywords(bare)) + "\n", encoding="utf-8")
            self._kws = sherpa_onnx.KeywordSpotter(
                tokens=str(files["tokens"]),
                encoder=str(files["encoder"]),
                decoder=str(files["decoder"]),
                joiner=str(files["joiner"]),
                keywords_file=str(keywords_file),
                num_threads=1,
                keywords_threshold=float(getattr(self._config, "wake_kws_threshold", 0.25)),
                keywords_score=1.0,
            )
            self._kws_stream = self._kws.create_stream()
            words = "'Hey ARCHER'" + (" and 'ARCHER'" if bare else "")
            logger.info(f"Wake words: {words} (sherpa-onnx keyword spotter).")
        except Exception as e:
            self._kws = None
            self._kws_stream = None
            logger.warning(f"'Hey ARCHER' unavailable ({type(e).__name__}: {e}); backup wake words only.")

    def process_audio(self, audio_chunk: bytes) -> bool:
        """
        Process an audio chunk for wake word detection.

        Args:
            audio_chunk: Raw PCM audio bytes (int16, 16kHz, mono)

        Returns:
            True if wake word was detected above threshold.
        """
        if self._model is None and self._kws is None:
            return False

        # Bypass wake word processing if mic is muted; note when ARCHER itself
        # is playing audio (its own "ARCHER online" mustn't wake it).
        try:
            from archer.voice import get_audio_manager
            manager = get_audio_manager()
            if manager.is_mic_muted():
                return False
            if manager.is_playing:
                self._own_audio_at = time.monotonic()
        except Exception:
            pass

        # Convert bytes to numpy array
        audio_array = np.frombuffer(audio_chunk, dtype=np.int16)

        # Removed 2026-09-17 (Col's report + reproduced from his log): a
        # prior "RMS energy floor guard" here skipped calling
        # self._model.predict() entirely on any near-silent chunk (<50
        # RMS), meant to "prevent model drift". openWakeWord's model is a
        # STREAMING classifier -- its melspectrogram/embedding stages
        # need a continuous run of predict() calls to build up their
        # internal rolling buffer before a score means anything. Skipping
        # inference during every quiet gap (which is most of the time,
        # including the brief pauses between syllables while actually
        # saying the wake phrase) starved that buffer, so the first
        # attempt after any silence never had enough context to cross
        # threshold -- reproduced exactly as Col described: first
        # "hey jarvis" does nothing, then a second attempt (even a minute
        # later, just "hey") fires instantly, because the buffer was left
        # sitting on partial state from the first attempt's non-skipped
        # frames with nothing since to refresh or clear it. Feeding every
        # chunk (silence included) is the model's normal, designed usage
        # -- it has its own internal smoothing and doesn't need this gate.
        if self._kws is not None and self._spot_archer(audio_array):
            return True
        if self._model is None:
            return False

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

    def _spot_archer(self, audio_array: np.ndarray) -> bool:
        """Feed the keyword spotter; publish and return True when "Hey ARCHER" / "ARCHER" is heard."""
        stream = self._kws_stream
        stream.accept_waveform(16000, audio_array.astype(np.float32) / 32768.0)
        while self._kws.is_ready(stream):
            self._kws.decode_stream(stream)
            keyword = self._kws.get_result(stream)
            if keyword:
                # A fresh stream rather than reset_stream(): resetting a
                # stream mid-way cost about a third of detections in tests.
                self._kws_stream = self._kws.create_stream()
                name = str(keyword).lower()
                if time.monotonic() - self._own_audio_at < _OWN_AUDIO_GRACE_S:
                    logger.debug(f"Wake word '{name}' ignored: ARCHER itself was speaking.")
                    return False
                if self._model is not None:
                    self._model.reset()
                logger.info(f"Wake word detected! (model={name}, sherpa-onnx)")
                self._bus.publish(Event(
                    type=EventType.WAKE_WORD_DETECTED,
                    source="wake_word",
                    data={"model": name, "confidence": 1.0},
                ))
                return True
        return False

    def reset(self) -> None:
        """Reset the wake word detection buffer."""
        if self._model is not None:
            self._model.reset()
        if self._kws is not None:
            self._kws_stream = self._kws.create_stream()
