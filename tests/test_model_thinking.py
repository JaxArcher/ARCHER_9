"""
Gemma 4 "thinks" (hidden reasoning) before answering unless Ollama is told
"think": false, which made ARCHER's first words take 27-84 s on 2026-10-20.
Every request to the primary model must carry the setting (Claude, 2026-10-20).
"""

from pathlib import Path

from archer.config import ArcherConfig

SRC = Path(__file__).resolve().parents[1] / "src" / "archer"
PRIMARY_MODEL_REQUESTS = {
    "agents/core_agent.py": 3,
    "voice/pipeline.py": 1,
    "memory/pattern_learner.py": 1,
    "observer/staleness_reasoner.py": 1,
    "memory/consolidation.py": 1,
}
MODEL_LINES = ('"model": self.primary_model,', '"model": self._config.core_primary_model,',
               '"model": config.core_primary_model,', '"model": self._model,')


def test_thinking_is_off_by_default():
    assert ArcherConfig.model_fields["core_think"].default is False


def test_every_primary_model_request_sends_the_setting():
    for rel, expected in PRIMARY_MODEL_REQUESTS.items():
        lines = (SRC / rel).read_text(encoding="utf-8").splitlines()
        found = 0
        for i, line in enumerate(lines):
            if line.strip() in MODEL_LINES:
                assert '"think": bool(getattr(' in lines[i + 1], f"{rel}:{i + 1} has no think setting"
                found += 1
        assert found == expected, (rel, found)
