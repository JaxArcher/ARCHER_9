"""
Test archer.web_main startup sequence up to uvicorn.run.

Verifies that all configuration attributes and initialization calls succeed
without missing attributes (such as barehands_dir) or broken imports.
"""

from unittest.mock import MagicMock, patch
import pytest

from archer.config import get_config


class StartupStopException(Exception):
    """Exception raised by mocked uvicorn.run to halt startup test cleanly."""
    pass


def test_web_main_startup_up_to_uvicorn():
    """Verify that web_main.main() initializes all components and reaches uvicorn.run without error."""
    # Ensure barehands_dir is present on config
    cfg = get_config()
    assert hasattr(cfg, "barehands_dir"), "config.barehands_dir must exist"

    with patch("archer.web_main.setup_logging"), \
         patch("archer.web_main.setup_latest_log_mirror"), \
         patch("archer.integrations.ollama_bootstrap.start_ollama_instances"), \
         patch("archer.memory.sqlite_store.get_sqlite_store"), \
         patch("archer.agents.core_agent.CoreAgent") as mock_core_agent, \
         patch("archer.voice.pipeline.VoicePipeline") as mock_voice_pipeline, \
         patch("threading.Thread") as mock_thread, \
         patch("archer.integrations.telegram_line.get_telegram_line"), \
         patch("archer.memory.maintenance.start_maintenance_scheduler"), \
         patch("archer.server.set_orchestrator") as mock_set_orch, \
         patch("archer.server.set_observer") as mock_set_obs, \
         patch("uvicorn.run", side_effect=StartupStopException("Reached uvicorn.run")) as mock_uvicorn:

        from archer import web_main

        # Running main should proceed until uvicorn.run
        with pytest.raises(StartupStopException):
            web_main.main()

        assert mock_uvicorn.called
        assert mock_set_orch.called
        args, kwargs = mock_uvicorn.call_args
        assert kwargs.get("port") == cfg.api_port
