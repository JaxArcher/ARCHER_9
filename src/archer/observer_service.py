"""
ARCHER Standalone Observer Service (2026-09-16).

Runs ONLY the ambient observation layer -- camera capture, Reolink motion
detection, scene analysis, person identification, and the staleness/
neglect reasoning pass. No GUI, no voice pipeline, no FastAPI/WS server,
no CoreAgent.

Why this exists: the observer's whole job is to be ARCHER's senses --
tracking Col and his environment continuously. Until now it was a thread
owned by whichever front-end process happened to be running (the desktop
GUI via __main__.py, or the browser server via web_main.py), which meant
observation stopped the moment you closed that window. That's backwards
for something meant to be always-on background infrastructure, and it
even meant the camera SOURCE followed GUI window visibility (local webcam
when the desktop window was shown, network cam when hidden) -- the
opposite of "shouldn't depend on the desktop or browser session" (Col's
words, 2026-09-16).

This process is meant to run independently, ideally started as a Windows
Service (see scripts/install_observer_service.ps1) so it comes up at PC
boot regardless of whether Col ever opens the desktop app or a browser
tab. It talks to the rest of ARCHER two ways:
  - SQLite (observation_events, person_sightings) -- durable history,
    already what every other component reads.
  - Redis pub/sub (archer:observer:events) -- live push, so CoreAgent
    (running inside __main__.py or web_main.py, in a DIFFERENT process)
    still gets Blindspot flags and activity updates in real time. See
    core_agent.py's Redis subscriber and observer/pipeline.py's
    _publish_observation.

Motion-gated, not a flat timer (Col's call): stays fully quiet until
Reolink's onboard person-detection AI reports someone present, then
analyzes at a tight cadence for as long as that keeps being reported,
plus at least observer_motion_tail_seconds after the last signal. See
observer/pipeline.py's _analysis_loop / notify_motion for the mechanics.

Also runs observer/staleness_reasoner.py on its own, separate,
motion-independent cadence -- noticing things that stayed the SAME for
too long (a dish left out, laundry piling up) is a different kind of
signal than noticing something MOVED, and by definition won't be caught
by a motion trigger.

Usage:
    python -m archer.observer_service
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from dotenv import load_dotenv
from loguru import logger

_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path, override=True)

from archer.__main__ import setup_logging  # reuses the exact same logging setup
from archer.config import get_config


def main() -> None:
    setup_logging()
    logger.info("=" * 60)
    logger.info("  ARCHER Observer Service — standalone, always-on")
    logger.info("=" * 60)

    config = get_config()

    # Auto-start both Ollama instances if not already running -- this
    # service specifically needs the observer instance (moondream) for
    # scene analysis and staleness reasoning; starting the main instance
    # too is harmless (helps whichever front-end process connects later).
    from archer.integrations.ollama_bootstrap import start_ollama_instances
    start_ollama_instances()

    logger.info("Initializing memory store...")
    from archer.memory.sqlite_store import get_sqlite_store
    get_sqlite_store()

    from archer.observer.pipeline import ObserverPipeline
    pipeline = ObserverPipeline(analysis_interval=config.observer_analysis_frequency)

    # BlindspotAgent's decision-making now lives here too (2026-09-16), not
    # just inside CoreAgent's process. Reasoning: detection (this pipeline)
    # already ran independent of the GUI/browser, but INTERPRETING that
    # detection into an actual worth-mentioning intervention only happened
    # if CoreAgent's process was open at that exact moment -- meaning
    # nothing was ever decided during any GUI-downtime window, no matter
    # how long. handle_utterances=False: there's no voice pipeline in this
    # process, so STT_FINAL/ACTION_COMPLETED never fire here anyway; that
    # half of BlindspotAgent's job stays with CoreAgent, which still has
    # real speech to react to.
    from archer.agents.blindspot_agent import BlindspotAgent
    blindspot = BlindspotAgent(handle_utterances=False)

    camera_ok = pipeline.start()
    if not camera_ok:
        logger.warning(
            "Observer camera unavailable at startup — the pipeline stays "
            "running and will pick up frames once one becomes available."
        )

    # This service's whole point is running independent of any UI session,
    # so there's no "GUI visible/hidden" signal to switch cameras on the
    # way __main__.py's desktop instance does. Go straight to the network
    # (Reolink) camera if one's configured -- that's the always-reachable
    # source this service is built around; fall back to the local device
    # only if no network camera is configured at all.
    if config.network_camera_url:
        pipeline.switch_to_network_cam()
        logger.info("Using network (Reolink) camera as the primary source.")
    else:
        logger.info(
            "No network_camera_url configured — staying on the local "
            "webcam. Motion-gating needs a Reolink camera; without one, "
            "this falls back to flat-interval polling (see pipeline.py)."
        )

    # Reolink ONVIF motion/person-detection listener — this is the actual
    # trigger for active analysis windows (see pipeline.notify_motion).
    # ReolinkSmartDetector was fully implemented long before this session
    # but never instantiated anywhere in the running app; this is that
    # wire-up.
    from archer.observer.reolink_listener import ReolinkSmartDetector
    reolink = ReolinkSmartDetector(on_person_detected=pipeline.notify_motion)
    reolink_started = reolink.start()
    if not reolink_started:
        logger.warning(
            "Reolink ONVIF listener did not start (no network_camera_url, "
            "or the camera/library is unavailable) — the observer will "
            "fall back to flat-interval analysis with no motion gating."
        )

    # Staleness/neglect reasoning — separate cadence, independent of
    # motion (see observer/staleness_reasoner.py's module docstring for
    # why: this is about things that stayed the same for too long, not
    # things that moved).
    from archer.observer.staleness_reasoner import start_staleness_reasoner
    start_staleness_reasoner()

    logger.info(
        "ARCHER Observer Service is running. Waiting for signals to stop "
        "(Ctrl+C interactively, or a service stop when run under NSSM)."
    )

    stop_event = threading.Event()

    def _handle_signal(signum, _frame) -> None:
        logger.info(f"Observer service received signal {signum} — shutting down.")
        stop_event.set()

    # SIGTERM is what NSSM sends on `nssm stop` / service shutdown;
    # SIGINT covers Ctrl+C when run interactively for testing.
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (ValueError, AttributeError):
        pass  # SIGTERM isn't available on every platform/thread context

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Stopping observer service...")
        try:
            reolink.stop()
        except Exception as e:
            logger.debug(f"Reolink listener stop raised (non-fatal): {e}")
        try:
            pipeline.stop()
        except Exception as e:
            logger.debug(f"Observer pipeline stop raised (non-fatal): {e}")
        logger.info("ARCHER Observer Service stopped cleanly.")


if __name__ == "__main__":
    main()
