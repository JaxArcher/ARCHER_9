"""
ARCHER Nightly Maintenance Script.

Handles memory reflection, graph optimization, Tier 2 daily consolidation, and Tier 1 archival.

This module was fully implemented but never actually scheduled or called
by the running app -- only its own `if __name__ == "__main__"` block
referenced it (confirmed 2026-09-16, same "built but disconnected" pattern
found elsewhere in ARCHER this session). start_maintenance_scheduler()
below is what actually connects it: call it once from an entry point
(__main__.py, web_main.py) and it fires run_maintenance() once a day, in
the background, for as long as the process runs.
"""

import datetime
import threading
import time
from loguru import logger

from archer.config import get_config
from archer.memory.openmemory_store import get_openmemory_store
from archer.memory.markdown_logger import get_markdown_logger
from archer.memory.consolidation import run_consolidation


def run_maintenance() -> None:
    """Run all maintenance tasks for the ARCHER memory system."""
    start_time = time.time()
    logger.info("Starting ARCHER nightly maintenance cycle...")

    # 1. Daily Observer Behavioral Consolidation Pass (local-model synthesis -> OpenMemory)
    try:
        logger.info("Triggering daily observer consolidation pass...")
        run_consolidation()
    except Exception as e:
        logger.error(f"Observer consolidation pass failed: {e}")

    # 2. OpenMemory Reflection
    # This process builds associative links between episodic memories
    # and reinforces important patterns in the cognitive graph.
    try:
        om = get_openmemory_store()
        logger.info("Triggering OpenMemory reflection...")
        om.reflect()
    except Exception as e:
        logger.error(f"OpenMemory reflection failed: {e}")

    # 3. Audit Log Entry
    try:
        md = get_markdown_logger()
        duration = time.time() - start_time
        md.log_audit(
            action="nightly_maintenance",
            result="success",
            details=f"Duration: {duration:.2f}s. Cognitive graph synchronized."
        )
    except Exception as e:
        logger.error(f"Failed to log maintenance audit: {e}")

    logger.info(f"Maintenance cycle completed in {time.time() - start_time:.2f}s")


def _maintenance_loop(hour: int) -> None:
    """Background loop: fires run_maintenance() once per calendar day, the
    first time local wall-clock time reaches `hour`:00. Checked every 5
    minutes rather than computing an exact sleep-until-target duration --
    simpler, and entirely fine for a once-a-day job with no precision
    requirement. Tracks last-run date so a long-lived process doesn't
    re-fire every 5 minutes once past the target hour, and so a restart
    later the same day doesn't immediately re-run it.

    Bug fixed 2026-09-16 (confirmed live): the first check ran
    unconditionally if the current hour was already >= the target hour --
    which is true nearly any time of day, so starting ARCHER at, say,
    6:38am fired "nightly" maintenance immediately instead of waiting for
    the next real 3am. Now the very first check just records today as
    already accounted for if we're past the target hour, without running
    anything, so the next actual run is the next real occurrence of the
    target hour -- not "whenever ARCHER next happens to start."
    """
    last_run_date: str | None = None
    _CHECK_INTERVAL_S = 5 * 60
    first_check = True
    while True:
        try:
            now = datetime.datetime.now()
            today = now.strftime("%Y-%m-%d")
            if first_check:
                first_check = False
                if now.hour >= hour:
                    # Don't retroactively "catch up" a run just because the
                    # app started after today's target hour already passed.
                    last_run_date = today
            elif now.hour >= hour and last_run_date != today:
                last_run_date = today
                logger.info(f"Nightly maintenance window reached (hour={hour}) — running now.")
                run_maintenance()
        except Exception as e:
            logger.error(f"Nightly maintenance loop iteration failed (will retry): {e}")
        time.sleep(_CHECK_INTERVAL_S)


def start_maintenance_scheduler(hour: int | None = None) -> None:
    """Start the nightly maintenance background thread. Safe to call once
    from each process entry point (__main__.py, web_main.py) — daemon
    thread, so it never blocks shutdown."""
    config = get_config()
    target_hour = hour if hour is not None else config.maintenance_hour
    threading.Thread(
        target=_maintenance_loop,
        args=(target_hour,),
        daemon=True,
        name="archer-nightly-maintenance",
    ).start()
    logger.info(f"Nightly maintenance scheduler started (target hour: {target_hour}:00 local time).")


if __name__ == "__main__":
    run_maintenance()
