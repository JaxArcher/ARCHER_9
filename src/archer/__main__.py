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

import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Load .env with override=True so .env values win over stale system env vars.
# Must happen BEFORE ArcherConfig is instantiated (pydantic_settings reads os.environ).
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path, override=True)

from archer.config import get_config


def setup_logging() -> None:
    """Configure loguru for ARCHER."""
    config = get_config()

    # Remove default handler
    logger.remove()

    # Console handler
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File handler
    log_file = config.log_dir / "archer_{time:YYYY-MM-DD}.log"
    logger.add(
        str(log_file),
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )


def main() -> None:
    """Main entry point for ARCHER."""
    setup_logging()
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

    if not config.elevenlabs_api_key and config.default_mode == "cloud":
        logger.warning(
            "No ELEVENLABS_API_KEY set. Cloud TTS/STT won't work without it."
        )

    # Initialize memory store (creates DB tables)
    logger.info("Initializing memory store...")
    from archer.memory.sqlite_store import get_sqlite_store
    store = get_sqlite_store()

    # Initialize agent orchestrator
    logger.info("Initializing agent orchestrator...")
    from archer.agents.orchestrator import AgentOrchestrator
    orchestrator = AgentOrchestrator()

    # Initialize voice pipeline
    logger.info("Initializing voice pipeline...")
    from archer.voice.pipeline import VoicePipeline
    pipeline = VoicePipeline(
        agent_callback=orchestrator.process_request,
        agent_streaming_callback=orchestrator.process_request_streaming,
    )

    try:
        pipeline.initialize()
    except Exception as e:
        logger.warning(f"Voice pipeline initialization warning: {e}")
        logger.info("Continuing with limited voice capabilities...")

    # Start voice pipeline in background thread
    logger.info("Starting voice pipeline...")
    try:
        pipeline.start()
    except Exception as e:
        logger.warning(f"Voice pipeline start warning: {e}")
        logger.info("Voice pipeline will operate in text-only mode.")

    # Pre-cache conversational filler audio clips in a background thread
    # so they play instantly (no TTS latency) when the agent is slow.
    def _precache_fillers():
        try:
            pipeline.precache_fillers()
        except Exception as e:
            logger.warning(f"Filler pre-cache failed (non-fatal): {e}")

    threading.Thread(target=_precache_fillers, daemon=True, name="FillerCache").start()

    # Initialize Observer pipeline (Phase 3)
    logger.info("Initializing observer pipeline...")
    observer = None
    intervention_engine = None
    try:
        from archer.observer.pipeline import ObserverPipeline
        from archer.observer.interventions import InterventionEngine

        observer = ObserverPipeline(
            analysis_interval=5.0,
            camera_device=0,
        )

        # Create intervention engine with proactive delivery callback
        intervention_engine = InterventionEngine(
            speak_callback=orchestrator.deliver_proactive_message,
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

    # Start PyQt6 GUI (must be on main thread)
    logger.info("Starting GUI...")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

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

    # Wire up text input from GUI to pipeline
    def on_text_input(event):
        pipeline.process_text_input(event.data.get("text", ""))

    bus.subscribe(EventType.GUI_TEXT_INPUT, on_text_input)

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

        bus.subscribe(EventType.OBSERVATION, on_observation)

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
