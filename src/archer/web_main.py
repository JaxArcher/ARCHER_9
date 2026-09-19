"""
ARCHER — Web-Only Entry Point.

Runs the exact same backend as `python -m archer` (CoreAgent, VoicePipeline
with this machine's own mic/speaker, memory store, observer pipeline,
barehands bridge, FastAPI/WebSocket server) but never imports PyQt6 and
never opens the desktop window. Use this when the browser client
(http://127.0.0.1:8200/app, see web/CONTRACT.md) is all that's wanted —
the desktop GUI is a separate, optional front end, not a dependency of it.

Usage:
    python -m archer.web_main
    or
    archer-web   (via pyproject.toml entry point)
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from dotenv import load_dotenv
from loguru import logger

_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path, override=True)

from archer.__main__ import setup_logging, setup_latest_log_mirror  # reuses the exact same logging setup
from archer.config import get_config


def main() -> None:
    setup_logging()
    setup_latest_log_mirror()
    logger.info("=" * 60)
    logger.info("  ARCHER — Web-Only Mode (no desktop GUI)")
    logger.info("=" * 60)

    config = get_config()

    if not config.anthropic_api_key and config.default_mode == "cloud":
        logger.warning(
            "No ANTHROPIC_API_KEY set. Cloud mode won't work without it. "
            "Set it in .env or switch to local mode."
        )
    if not config.elevenlabs_api_key and config.default_mode == "cloud":
        logger.warning("No ELEVENLABS_API_KEY set. Cloud TTS/STT won't work without it.")

    # Auto-start both Ollama instances (main + observer/moondream) if
    # they're not already running -- Col no longer needs to manually run
    # `ollama serve` / start_observer_ollama.ps1 first (2026-09-16).
    from archer.integrations.ollama_bootstrap import start_ollama_instances
    start_ollama_instances()

    logger.info("Initializing memory store...")
    from archer.memory.sqlite_store import get_sqlite_store
    get_sqlite_store()

    logger.info("Initializing CoreAgent...")
    from archer.agents.core_agent import CoreAgent
    core_agent = CoreAgent()

    logger.info("Creating voice pipeline...")
    from archer.voice.pipeline import VoicePipeline
    pipeline = VoicePipeline(agent_streaming_callback=core_agent.process_turn_streaming)

    def _init_and_start_pipeline():
        import time as _time
        _time.sleep(0.5)
        try:
            pipeline.initialize()
        except Exception as e:
            logger.warning(f"Voice pipeline initialization warning: {e}")
            logger.info("Continuing with limited voice capabilities...")
        try:
            pipeline.start()
        except Exception as e:
            logger.warning(f"Voice pipeline start warning: {e}")
            logger.info("Voice pipeline will operate in text-only mode.")
        try:
            pipeline.precache_fillers()
        except Exception as e:
            logger.warning(f"Filler pre-cache failed (non-fatal): {e}")

    threading.Thread(target=_init_and_start_pipeline, daemon=True, name="PipelineInit").start()

    def _start_observer_containers():
        compose_file = Path(__file__).resolve().parents[2] / "docker-compose.yml"
        if not compose_file.exists():
            logger.debug("docker-compose.yml not found — skipping container startup.")
            return
        try:
            result = subprocess.run(
                ["docker-compose", "-f", str(compose_file), "--profile", "observer", "up", "-d"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(compose_file.parent),
            )
            if result.returncode == 0:
                logger.info("Observer containers started (MediaPipe, DeepFace).")
            else:
                logger.debug(f"docker-compose returned {result.returncode}: {result.stderr.strip()}")
        except FileNotFoundError:
            logger.debug("docker-compose not found on PATH — observer containers not started.")
        except Exception as e:
            logger.debug(f"Observer container startup failed (non-fatal): {e}")

    threading.Thread(target=_start_observer_containers, daemon=True, name="DockerStart").start()

    # Real ambient observation (analysis/decisions) belongs entirely to
    # the standalone archer/observer_service.py process (Col's call: the
    # observer shouldn't depend on this process or the desktop GUI). But
    # a lightweight, analysis-free ObserverPipeline instance is still
    # needed HERE too, now that the browser client has its own live
    # camera pane, ENROLL FACE button, and CAMERA release/reacquire
    # toggle (all added 2026-09-16, after this comment was first
    # written) — those all read/act on `_observer` in server.py, which
    # was `None` in this process until now, silently leaving all three
    # broken in browser-only mode even though they worked fine from the
    # desktop app. Mirrors __main__.py's own instance exactly:
    # run_analysis=False means it opens the camera but never runs its
    # own analysis thread, so it doesn't duplicate the observer service's
    # work or double-log every observation.
    observer = None
    try:
        from archer.observer.pipeline import ObserverPipeline
        from archer.observer.interventions import InterventionEngine

        observer = ObserverPipeline(
            analysis_interval=config.observer_analysis_frequency,
            run_analysis=False,
        )
        observer.start()
        InterventionEngine(speak_callback=lambda agent, text: pipeline._call_agent_with_filler(text))
        logger.info("Observer camera + intervention engine initialized (analysis runs in the separate observer service).")
    except ImportError as e:
        logger.info(f"Observer dependencies not available ({e}). Camera pane + proactive interventions disabled.")
    except Exception as e:
        logger.warning(f"Observer/intervention engine initialization failed (non-fatal): {e}")

    from archer.integrations.barehands_bridge import start_barehands_bridge
    start_barehands_bridge()

    # Nightly maintenance (daily consolidation + OpenMemory reflection) —
    # fully built but never actually scheduled anywhere until now
    # (2026-09-16). See memory/maintenance.py.
    from archer.memory.maintenance import start_maintenance_scheduler
    start_maintenance_scheduler()

    logger.info(f"Browser client will be at http://{config.api_host}:{config.api_port}/app")
    logger.info("ARCHER is ready. Say 'Hey ARCHER', open the browser client, or Ctrl+C to stop.")

    import uvicorn
    from archer.server import app, set_orchestrator, set_observer
    set_orchestrator(core_agent)
    set_observer(observer)

    try:
        uvicorn.run(app, host=config.api_host, port=config.api_port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down ARCHER...")
        if observer is not None:
            observer.stop()
        pipeline.stop()
        from archer.core.event_bus import get_event_bus
        get_event_bus().clear()
        logger.info("ARCHER shut down cleanly.")


if __name__ == "__main__":
    main()
