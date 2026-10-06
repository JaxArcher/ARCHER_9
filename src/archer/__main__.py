"""
ARCHER Main Entry Point.

Starts the ARCHER system:
1. PyQt6 owns the main thread and its own event loop.
2. The voice pipeline runs in a dedicated background thread.
3. The agent orchestrator processes requests in a worker thread pool.
4. All inter-thread communication goes through thread-safe queues
   and the event bus.

Usage:
    python -m archer
    or
    archer  (via pyproject.toml entry point)
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

# CRITICAL ORDERING RULE 1 (PyTorch / ONNXRuntime Windows DLL Fix):
# Must set KMP_DUPLICATE_LIB_OK and pre-load torch/onnxruntime BEFORE importing PyQt6 modules.
# Qt 6 C++ runtime DLLs lock process OpenMP handles on import, causing WinError 1114 on lazy torch/onnxruntime DLL load.
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
try:
    import torch
    import onnxruntime
except ImportError:
    pass

from dotenv import load_dotenv
from loguru import logger

# Load .env with override=True so .env values win over stale system env vars.
# Must happen BEFORE ArcherConfig is instantiated (pydantic_settings reads os.environ).
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path, override=True)

from archer.config import get_config


class _FlushingFileSink:
    """
    Guarantees every log line is actually visible on disk immediately —
    to `tail`, to the GUI's Console tab, to anything else reading the
    file — rather than waiting on whatever Python's IO layer or the OS
    decides to buffer.

    loguru's own file sink already defaults to buffering=1 (line-buffered),
    which should have been enough, but in practice it wasn't: the log
    file's mtime sat completely frozen at the startup line through full
    conversation turns, across many separate ARCHER restarts. Rather than
    keep guessing at why line-buffering wasn't taking effect (Windows
    file-sharing semantics, an interaction with one of the many native
    ML libraries ARCHER loads, etc.), this sink just flushes AND fsyncs
    after every single write, removing the ambiguity entirely. The
    trade-off is losing loguru's built-in rotation/retention/compression
    (which need a path-string sink) — acceptable for a personal debug
    log at this volume; the date is baked into the filename at startup
    instead, same naming convention as before.
    """

    def __init__(self, path: Path, mode: str = "a") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, mode, encoding="utf-8", buffering=1)

    def write(self, message: str) -> None:
        self._file.write(message)
        self._file.flush()
        try:
            os.fsync(self._file.fileno())
        except OSError:
            pass  # Some filesystems don't support fsync; flush() already pushed it out of the Python buffer.

    def stop(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass


def setup_logging(log_basename: str = "archer") -> None:
    """Configure loguru for ARCHER.

    log_basename (2026-10-06): the standalone observer service passes
    "observer" so its dated file (logs/observer_YYYY-MM-DD.log) stays
    separate from the desktop/browser app's logs/archer_YYYY-MM-DD.log, now
    that both processes run from the project root and share logs/.
    """
    config = get_config()

    # Remove default handler
    logger.remove()

    # Console handler
    # Timestamp includes milliseconds (2026-09-17) -- second-only
    # resolution repeatedly made it impossible to tell true execution
    # order apart from same-second logging noise while chasing the voice
    # pipeline's turn-overlap bugs (multiple threads legitimately log
    # within the same wall-clock second; without sub-second precision
    # there's no way to tell which one actually happened first).
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File handler — see _FlushingFileSink for why this isn't a plain
    # path-string sink (loguru's built-in file sink wasn't reliably
    # flushing to disk in practice, which broke both `tail`-ing the log
    # and the GUI's live Console tab).
    import datetime as _datetime
    log_file_path = config.log_dir / f"{log_basename}_{_datetime.date.today():%Y-%m-%d}.log"
    logger.add(
        _FlushingFileSink(log_file_path),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    )


def setup_latest_log_mirror() -> None:
    """
    Fixed-name latest-run log mirror (2026-09-18, Col's request): the
    dated per-day file setup_logging() already writes is the durable
    history, but reporting an issue to Claude meant manually copy-pasting
    the terminal window's text into a fresh upload every time instead.
    This writes that same console content (INFO and up -- matching what
    was actually being copy-pasted; DEBUG would just be noise for a
    hand-off report) to one fixed path, truncated ("w") at the start of
    every run. The flushing sink means it's live on disk for the WHOLE
    run, not written only at shutdown -- so whatever's in the file when
    the program closes (cleanly, via Ctrl+C, or a crash) is already the
    complete record of that run.

    Deliberately NOT called from inside setup_logging() itself: that
    function is shared by all three entry points (__main__.py,
    web_main.py, observer_service.py), and the standalone observer
    service normally runs continuously in the background WHILE web_main.py
    is separately launched and closed -- two processes independently
    truncating the same fixed-name file would race and corrupt it. Call
    this only from the interactive entry points (desktop/browser) whose
    console output Col actually hands off; the standalone service's own
    dated file is unaffected and still gets written normally.
    """
    latest_log_path = Path("docs/reports/latest_session_log.log")
    logger.add(
        _FlushingFileSink(latest_log_path, mode="w"),
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    )


def main() -> None:
    """Main entry point for ARCHER."""
    # Set Qt attribute for QWebEngineView BEFORE any QCoreApplication/QApplication instance is created
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        if not QApplication.instance():
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    except Exception:
        pass

    setup_logging()
    setup_latest_log_mirror()
    logger.info("=" * 60)
    logger.info("  ARCHER — Advanced Responsive Computing Helper")
    logger.info("  Phase 4: PC Control + Finance + Full GUI")
    logger.info("=" * 60)

    config = get_config()

    # Validate critical configuration
    if not config.anthropic_api_key and config.default_mode == "cloud":
        logger.warning(
            "No ANTHROPIC_API_KEY set. Cloud mode won't work without it. "
            "Set it in .env or switch to local mode."
        )

    # Auto-start both Ollama instances (main + observer/moondream) if
    # they're not already running -- Col no longer needs to manually run
    # `ollama serve` / start_observer_ollama.ps1 first (2026-09-16).
    from archer.integrations.ollama_bootstrap import start_ollama_instances
    start_ollama_instances()

    # Initialize memory store (creates DB tables)
    logger.info("Initializing memory store...")
    from archer.memory.sqlite_store import get_sqlite_store
    store = get_sqlite_store()

    # Initialize CoreAgent (Single-Agent Core Engine)
    logger.info("Initializing CoreAgent...")
    from archer.agents.core_agent import CoreAgent
    core_agent = CoreAgent()

    # Initialize voice pipeline
    logger.info("Creating voice pipeline...")
    from archer.voice.pipeline import VoicePipeline
    pipeline = VoicePipeline(
        agent_streaming_callback=core_agent.process_turn_streaming,
    )

    # Initialize + start the voice pipeline in a background thread.
    # SpeechBrain may need to download models from HuggingFace on first run,
    # which can take 30–120 seconds. Running this off the main thread ensures
    # the GUI appears immediately without being blocked.
    def _init_and_start_pipeline():
        import time as _time
        # Brief pause so the GUI has time to fully render before heavy I/O.
        _time.sleep(1.5)
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
        # Pre-cache conversational filler audio clips so they play instantly.
        try:
            pipeline.precache_fillers()
        except Exception as e:
            logger.warning(f"Filler pre-cache failed (non-fatal): {e}")

    threading.Thread(target=_init_and_start_pipeline, daemon=True, name="PipelineInit").start()

    # Start observer Docker containers (MediaPipe, DeepFace) in the background
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

    # Initialize Observer pipeline (Phase 3) — camera-preview-only mode
    # (2026-09-16). Real ambient observation (analysis, SQLite logging,
    # Blindspot triggers) now belongs to the standalone
    # archer/observer_service.py, running as its own always-on process so
    # it doesn't depend on the desktop GUI being open at all (Col's call).
    # This instance exists purely to feed the GUI's own live webcam widget
    # and face-enrollment flow — run_analysis=False means it opens the
    # camera but never runs its own analysis thread, so it doesn't
    # duplicate the observer service's work or double-log every
    # observation. CoreAgent gets real observation data from the observer
    # service via Redis (see core_agent.py's subscriber), not from this
    # instance.
    logger.info("Initializing observer pipeline (camera-preview mode)...")
    observer = None
    intervention_engine = None
    try:
        from archer.observer.pipeline import ObserverPipeline
        from archer.observer.interventions import InterventionEngine

        observer = ObserverPipeline(
            analysis_interval=config.observer_analysis_frequency,
            run_analysis=False,
        )

        # Create intervention engine with proactive delivery callback
        intervention_engine = InterventionEngine(
            speak_callback=lambda agent, text: pipeline._call_agent_with_filler(text),
        )

        # Start the observer in a background thread
        def _start_observer():
            try:
                observer.start()
            except Exception as e:
                logger.warning(f"Observer start failed (non-fatal): {e}")
                logger.info("Observer features disabled. ARCHER continues without ambient observation.")

        threading.Thread(target=_start_observer, daemon=True, name="ObserverStart").start()
        logger.info("Observer pipeline initialized.")

    except ImportError as e:
        logger.info(f"Observer dependencies not available ({e}). Observer disabled.")
    except Exception as e:
        logger.warning(f"Observer initialization failed (non-fatal): {e}")
        logger.info("Observer features disabled.")

    from archer.integrations.barehands_bridge import start_barehands_bridge
    start_barehands_bridge()

    # Nightly maintenance (daily consolidation + OpenMemory reflection) —
    # fully built but never actually scheduled anywhere until now
    # (2026-09-16). See memory/maintenance.py.
    from archer.memory.maintenance import start_maintenance_scheduler
    start_maintenance_scheduler()

    # Start API Server (Phase 1 / Mobile Bridge)
    def _start_api_server():
        try:
            import uvicorn
            from archer.server import app, set_orchestrator, set_observer
            set_orchestrator(core_agent)
            set_observer(observer)
            logger.info(f"Starting API Server on {config.api_host}:{config.api_port}...")
            uvicorn.run(app, host=config.api_host, port=config.api_port, log_level="warning")
        except Exception as e:
            logger.warning(f"API Server failed to start: {e}")

    threading.Thread(target=_start_api_server, daemon=True, name="APIServer").start()

    # Start PyQt6 GUI (must be on main thread)
    logger.info("Starting GUI...")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("ARCHER")
    app.setApplicationDisplayName("ARCHER — Mission Control")

    # Set application-wide style
    app.setStyle("Fusion")

    # Import and create main window
    from archer.gui.main_window import MainWindow
    window = MainWindow()

    # Connect pipeline events to GUI
    from archer.core.event_bus import EventType, get_event_bus
    bus = get_event_bus()

    # --- Pipeline state → Orb + state label ---
    def on_pipeline_state_change(event):
        """Bridge pipeline state changes to the GUI orb and state label."""
        state = event.data.get("state")
        if state:
            window.update_state_signal.emit(state)

    bus.subscribe(EventType.PIPELINE_STATE_CHANGED, on_pipeline_state_change)

    # --- Cloud/local mode → Orb tint ---
    def on_mode_change_for_orb(event):
        """Forward mode changes to the orb for warm/cool tint."""
        new_mode = event.data.get("new_mode", "cloud")
        window.update_mode_signal.emit(new_mode)

    bus.subscribe(EventType.MODE_CHANGED, on_mode_change_for_orb)

    # --- Agent switch → Orb color + memory panel ---
    def on_agent_switch(event):
        """Forward agent switch events to the GUI."""
        new_agent = event.data.get("new_agent", "assistant")
        window.update_agent_signal.emit(new_agent)

    bus.subscribe(EventType.AGENT_SWITCH, on_agent_switch)

    # --- Audio amplitude → Orb animation ---
    def on_audio_amplitude(event):
        """Forward audio amplitude to the orb for speech animation."""
        amplitude = event.data.get("amplitude", 0.0)
        window.update_amplitude_signal.emit(amplitude)

    bus.subscribe(EventType.AUDIO_AMPLITUDE, on_audio_amplitude)

    # Text input: VoicePipeline subscribes to GUI_TEXT_INPUT internally
    # (in __init__), so no additional wiring needed here.

    # Wire up TTS mute
    def on_mute_tts(event):
        pipeline._audio.set_tts_muted(event.data.get("muted", False))

    bus.subscribe(EventType.GUI_MUTE_TTS, on_mute_tts)

    # --- Observer → GUI wiring ---
    if observer is not None:
        # Wire the tray "Pause Observer" toggle
        window.observer_pause_signal.connect(
            lambda paused: observer.pause() if paused else observer.resume()
        )

        # Forward observation events to the GUI status display
        def on_observation(event):
            event_type = event.data.get("event_type", "")
            confidence = event.data.get("confidence", 0.0)
            info = f"Observer: {event_type} (conf: {confidence:.0%})"
            window.update_observer_signal.emit(info)

        bus.subscribe(EventType.OBSERVATION_EVENT, on_observation)

        # Attach the observer's camera and detection overlay to the GUI webcam widget
        window._webcam_widget.set_camera(observer.camera)
        window._webcam_widget.set_detections_source(observer.get_latest_detections)

        # Forward vision/scene analysis results to the GUI
        def on_scene_observation(event):
            if event.data.get("event_type") == "scene":
                description = event.data.get("description", "")
                if description:
                    window.update_vision_signal.emit(description)

        bus.subscribe(EventType.OBSERVATION_EVENT, on_scene_observation)

        # Camera switching: local webcam when GUI visible, network cam when hidden
        def on_gui_visibility(visible: bool):
            if visible:
                # GUI shown → switch to local webcam, re-attach to widget
                new_cam = observer.switch_to_webcam()
                window._webcam_widget.set_camera(new_cam)
                window._webcam_widget.set_detections_source(observer.get_latest_detections)
            else:
                # GUI hidden → switch to network cam for background analysis
                window._webcam_widget.stop()
                observer.switch_to_network_cam()

        window.gui_visibility_signal.connect(on_gui_visibility)

    # Show window
    window.show()
    logger.info("ARCHER is ready. Say 'Hey ARCHER' or type a message.")

    # Run the Qt event loop (blocks until quit)
    exit_code = app.exec()

    # Cleanup
    logger.info("Shutting down ARCHER...")
    if observer is not None:
        observer.stop()
    pipeline.stop()
    bus.clear()

    logger.info("ARCHER shut down cleanly.")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
