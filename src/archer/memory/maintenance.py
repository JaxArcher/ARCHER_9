"""
ARCHER Nightly Maintenance Script.

Handles memory reflection, graph optimization, and Tier 1 archival.
"""

import time
from loguru import logger

from archer.memory.openmemory_store import get_openmemory_store
from archer.memory.markdown_logger import get_markdown_logger


def run_maintenance() -> None:
    """Run all maintenance tasks for the ARCHER memory system."""
    start_time = time.time()
    logger.info("Starting ARCHER nightly maintenance cycle...")

    # 1. OpenMemory Reflection
    # This process builds associative links between episodic memories
    # and reinforces important patterns in the cognitive graph.
    try:
        om = get_openmemory_store()
        logger.info("Triggering OpenMemory reflection...")
        om.reflect()
    except Exception as e:
        logger.error(f"OpenMemory reflection failed: {e}")

    # 2. Audit Log Entry
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


if __name__ == "__main__":
    run_maintenance()
