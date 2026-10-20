"""
kokoro's __init__ calls loguru's logger.remove(), which used to drop
ARCHER's log files whenever the voice pipeline loaded (every run's
logs/archer_*.log stopped at "VAD initialized"). _import_kokoro_pipeline()
must keep ARCHER's handlers and not leave kokoro's extra console handler
behind (Claude, 2026-10-20). Uses a stand-in kokoro package; the real one
is never imported here.
"""

import sys
import textwrap

from loguru import logger

FAKE_KOKORO = textwrap.dedent('''
    from loguru import logger
    import sys
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.disable("kokoro")

    class KPipeline:
        def __init__(self, lang_code="a"):
            self.lang_code = lang_code
''')


def test_kokoro_import_keeps_archer_log_handlers(tmp_path, monkeypatch):
    pkg = tmp_path / "kokoro"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(FAKE_KOKORO, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "kokoro", raising=False)

    from archer.voice.tts import _import_kokoro_pipeline

    seen: list[str] = []
    handler_id = logger.add(lambda m: seen.append(m.record["message"]), level="DEBUG")
    try:
        before = set(logger._core.handlers)  # noqa: SLF001 (test-only peek)
        KPipeline = _import_kokoro_pipeline()
        after = set(logger._core.handlers)  # noqa: SLF001
        logger.info("still logging after kokoro")
    finally:
        logger.remove(handler_id)
        sys.modules.pop("kokoro", None)

    assert KPipeline(lang_code="a").lang_code == "a"
    assert "still logging after kokoro" in seen
    assert after == before, "kokoro's import removed a handler or left its own behind"
    assert "remove" not in vars(logger) and "add" not in vars(logger)
