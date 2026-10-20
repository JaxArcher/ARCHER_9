"""
"Hey ARCHER" / "ARCHER" wake words via sherpa-onnx's keyword spotter
(Claude, 2026-10-20). A fake sherpa_onnx stands in, so no model files or
audio devices are needed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import archer.voice as voice_pkg
import archer.voice.wake_word as ww

FILES = list(ww._KWS_FILES.values())


class FakeStream:
    def __init__(self):
        self.samples = 0
        self.pending = False

    def accept_waveform(self, rate, samples):
        assert rate == 16000 and samples.dtype == np.float32
        if np.abs(samples).max() > 0.01:
            self.samples += len(samples)
        self.pending = True


class FakeSpotter:
    """Hears the first keyword in its keywords file after 0.3 s of sound."""

    instances: list = []

    def __init__(self, **kw):
        self.kw = kw
        self.lines = Path(kw["keywords_file"]).read_text(encoding="utf-8").splitlines()
        self.streams = 0
        FakeSpotter.instances.append(self)

    def create_stream(self):
        self.streams += 1
        return FakeStream()

    def is_ready(self, s):
        return s.pending

    def decode_stream(self, s):
        s.pending = False

    def get_result(self, s):
        return self.lines[0].split("@")[1] if s.samples >= 4800 else ""


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    for name in FILES:
        (tmp_path / name).write_text("x")
    monkeypatch.setattr(ww, "KWS_MODEL_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(KeywordSpotter=FakeSpotter))
    playing = {"now": False}

    class Manager:
        def is_mic_muted(self):
            return False

        @property
        def is_playing(self):
            return playing["now"]

    monkeypatch.setattr(voice_pkg, "get_audio_manager", lambda: Manager())
    return tmp_path, playing


def detector(bare=True, stock=""):
    d = ww.WakeWordDetector.__new__(ww.WakeWordDetector)
    d._config = SimpleNamespace(wake_word_threshold=0.5, wake_stock_models=stock,
                                wake_bare_archer=bare, wake_kws_threshold=0.25)
    d._events = []
    d._bus = SimpleNamespace(publish=lambda e: d._events.append(e.data["model"]))
    d._threshold = 0.5
    d._model = None
    d._kws = None
    d._kws_stream = None
    d._own_audio_at = 0.0
    d.initialize()
    return d


def feed(d, seconds, level=3000):
    chunk = (np.ones(480) * level).astype(np.int16).tobytes()
    return any(d.process_audio(chunk) for _ in range(int(seconds / 0.03)))


def test_keyword_lines():
    assert ww.kws_keywords(True) == [ww._KWS_HEY_ARCHER, ww._KWS_ARCHER]
    assert ww.kws_keywords(False) == [ww._KWS_HEY_ARCHER]
    assert ww._KWS_HEY_ARCHER.startswith("▁HE Y ▁A R CH ER")


def test_hey_archer_wakes_archer(model_dir):
    d = detector()
    assert feed(d, 0.5)
    assert d._events == ["hey_archer"]
    assert FakeSpotter.instances[-1].kw["keywords_threshold"] == 0.25


def test_bare_archer_can_be_switched_off(model_dir):
    detector(bare=False)
    assert (model_dir[0] / "archer_keywords.txt").read_text(encoding="utf-8").splitlines() == [ww._KWS_HEY_ARCHER]


def test_archer_saying_its_own_name_doesnt_wake_it(model_dir):
    d = detector()
    model_dir[1]["now"] = True      # "ARCHER online." playing
    assert not feed(d, 0.5)
    model_dir[1]["now"] = False
    assert not feed(d, 0.5)          # still within the grace period
    d._own_audio_at = time.monotonic() - 5
    assert feed(d, 0.5)


def test_a_fresh_stream_after_each_wake_and_reset(model_dir):
    d = detector()
    spotter = FakeSpotter.instances[-1]
    feed(d, 0.5)
    d.reset()
    assert spotter.streams == 3      # start, after the wake, after reset


def test_missing_model_files_leave_the_backup_words(model_dir, monkeypatch):
    (model_dir[0] / FILES[1]).unlink()
    fake_oww = SimpleNamespace(utils=SimpleNamespace(download_models=lambda: None))
    model = SimpleNamespace(prediction_buffer={"hey_jarvis": [0.0]}, predict=lambda a: None, reset=lambda: None)
    monkeypatch.setitem(sys.modules, "openwakeword", fake_oww)
    monkeypatch.setitem(sys.modules, "openwakeword.model", SimpleNamespace(Model=lambda **kw: model))
    d = detector(stock="hey_jarvis")
    assert d._kws is None and d._model is model


def test_no_detector_at_all_is_an_error(model_dir):
    (model_dir[0] / FILES[0]).unlink()
    with pytest.raises(RuntimeError):
        detector(stock="")
