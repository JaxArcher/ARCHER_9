"""
Every request to ARCHER's main Ollama model asks for the same context size
and keep-alive (Claude, 2026-10-20). Ollama's log showed the model reloading
twice a turn (~13 s each) because requests disagreed (4096 against Ollama's
own default of 262,144), and at 4096 every chat prompt was cut to its last
2,051 tokens, losing the date and time and most tool descriptions.
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from archer.config import ArcherConfig
from archer.integrations import ollama_bootstrap
from archer.integrations.ollama_settings import (
    main_model_request,
    prompt_limit,
    prompt_was_cut,
    timing_summary,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "archer"
CONFIG = SimpleNamespace(ollama_num_ctx=32768, ollama_keep_alive="60m")
PRIMARY_MODEL_REQUESTS = {
    "agents/core_agent.py": 4,
    "observer/item_watcher.py": 1,
    "voice/pipeline.py": 1,
    "memory/pattern_learner.py": 1,
    "observer/staleness_reasoner.py": 1,
    "memory/consolidation.py": 1,
}
MODEL_LINES = ('"model": self.primary_model,', '"model": self._config.core_primary_model,',
               '"model": config.core_primary_model,', '"model": self._model,')


def test_defaults_leave_room_for_the_prompt():
    assert ArcherConfig.model_fields["ollama_num_ctx"].default == 32768
    assert ArcherConfig.model_fields["ollama_keep_alive"].default == "60m"


def test_request_gets_the_shared_settings_and_keeps_its_own_options():
    payload = {"model": "m", "options": {"num_predict": 24, "num_ctx": 4096}}
    out = main_model_request(payload, CONFIG, temperature=0.3)
    assert out is payload
    assert payload["options"] == {"num_predict": 24, "temperature": 0.3, "num_ctx": 32768}
    assert payload["keep_alive"] == "60m"


def test_request_without_options():
    payload = main_model_request({"model": "m"}, CONFIG)
    assert payload["options"] == {"num_ctx": 32768}


def test_every_primary_model_request_uses_the_shared_settings():
    for rel, expected in PRIMARY_MODEL_REQUESTS.items():
        lines = (SRC / rel).read_text(encoding="utf-8").splitlines()
        found = 0
        for i, line in enumerate(lines):
            if line.strip() in MODEL_LINES:
                window = "\n".join(lines[max(0, i - 4): i + 12])
                assert "main_model_request(" in window, f"{rel}:{i + 1} skips the shared settings"
                found += 1
        assert found == expected, (rel, found)
    for rel in PRIMARY_MODEL_REQUESTS:
        text = (SRC / rel).read_text(encoding="utf-8")
        assert '"num_ctx": 4096' not in text, rel
        assert '"keep_alive": "10m"' not in text, rel


def test_warm_up_loads_the_main_model_with_the_shared_settings(monkeypatch):
    sent = []

    class Resp:
        status_code = 200
        text = ""

    monkeypatch.setattr(ollama_bootstrap.httpx, "post", lambda url, json, timeout: sent.append(json) or Resp())
    monkeypatch.setattr(ollama_bootstrap, "_model_placement", lambda base, model: "loaded")
    ollama_bootstrap._warm_up_model("main", "http://x", "gemma", main_settings=True)
    ollama_bootstrap._warm_up_model("observer", "http://y", "moondream", force_cpu=True)
    assert sent[0]["options"]["num_ctx"] == ArcherConfig.model_fields["ollama_num_ctx"].default
    assert "keep_alive" in sent[0]
    assert sent[1] == {"model": "moondream", "options": {"num_gpu": 0}}


def test_pattern_learner_request(monkeypatch):
    from archer.memory import pattern_learner

    sent = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "{}"}

    monkeypatch.setattr(pattern_learner.httpx, "post", lambda url, json, timeout: sent.append(json) or Resp())
    learner = pattern_learner.PatternLearner(store=object())
    learner._run_extraction("hello there", "hi")
    assert sent[0]["options"]["num_ctx"] == learner._config.ollama_num_ctx
    assert sent[0]["options"]["temperature"] == 0.1


def test_timing_summary_flags_a_reload():
    final = {
        "done": True, "load_duration": 12_870_000_000, "prompt_eval_count": 4761,
        "prompt_eval_duration": 900_000_000, "eval_count": 40, "eval_duration": 500_000_000,
        "total_duration": 14_300_000_000,
    }
    text = timing_summary(final)
    assert "load 12.9 s" in text and "prompt 4761 tokens" in text and "reply 40 tokens" in text
    assert "reloaded" in text
    final["load_duration"] = 50_000_000
    assert "reloaded" not in timing_summary(final)
    assert timing_summary({"done": True}) is None


def test_prompt_cut_warning():
    assert prompt_limit(CONFIG) == 16384
    assert prompt_was_cut({"prompt_eval_count": 16380}, CONFIG)
    assert not prompt_was_cut({"prompt_eval_count": 4800}, CONFIG)
    assert not prompt_was_cut({}, CONFIG)


def test_cloud_overflow_threshold_follows_the_context():
    from archer.agents.core_agent import CoreAgent

    agent = SimpleNamespace(_config=CONFIG)
    assert CoreAgent.evaluate_cloud_delegation(agent, "hello", 5000) is None
    assert CoreAgent.evaluate_cloud_delegation(agent, "hello", 9000) == "context_overflow"
    small = SimpleNamespace(_config=SimpleNamespace(ollama_num_ctx=4096))
    assert CoreAgent.evaluate_cloud_delegation(small, "hello", 2500) == "context_overflow"


def test_vision_calls_col_you():
    from archer.agents import core_agent

    assert "col" in core_agent._OWNER_FACE_NAMES
    text = (SRC / "agents" / "core_agent.py").read_text(encoding="utf-8")
    assert "talk about him as 'you'" in text
    assert "Colby, the person talking to you" in text


def test_stt_warm_up(monkeypatch):
    from archer.voice import stt

    calls = []

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            calls.append((audio, kwargs))
            return iter([]), None

    local = stt.LocalSTT()
    monkeypatch.setattr(local, "_get_whisper_model", lambda: FakeModel())
    local.warm_up()
    audio, kwargs = calls[0]
    assert isinstance(audio, np.ndarray) and len(audio) == 16000
    assert kwargs["vad_filter"] is False

    def broken():
        raise RuntimeError("no GPU")

    monkeypatch.setattr(local, "_get_whisper_model", broken)
    local.warm_up()  # never raises


def test_pipeline_starts_the_stt_warm_up():
    text = (SRC / "voice" / "pipeline.py").read_text(encoding="utf-8")
    assert 'name="STTWarmUp"' in text
