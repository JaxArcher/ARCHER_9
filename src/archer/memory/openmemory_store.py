"""
ARCHER OpenMemory Cognitive Store (Layer 3 Memory).

Purpose: Graph-based associative memory with temporal knowledge graphs.
Sectors: Episodic, Semantic, Procedural, Emotional, Reflective.
"""

import os
import asyncio
from typing import Any, Literal
from loguru import logger
from archer.config import get_config

# Import openmemory after setting env if needed, 
# but we'll set it in __init__ just to be safe.
from openmemory import Memory

MemorySector = Literal["episodic", "semantic", "procedural", "emotional", "reflective"]


class OpenMemoryStore:
    """
    Layer 3: Cognitive storage using OpenMemory.
    Provides graph-based associative recall and sector-based classification.
    """

    def __init__(self) -> None:
        self._config = get_config()
        try:
            # Set the database path via environment variable for openmemory SDK
            os.environ["OM_DB_URL"] = f"sqlite:///{self._config.openmemory_db}"
            
            # Initialize Memory - it handles its own internal DB connection
            self._om = Memory(user="archer_user")
            logger.info(f"OpenMemory store initialized with DB at {self._config.openmemory_db}")
            
            # Helper to run async methods in a sync context
            self._loop = asyncio.new_event_loop()
            
        except Exception as e:
            logger.error(f"Failed to initialize OpenMemory: {e}")
            raise

    def _run_async(self, coro):
        """Helper to run async coroutines in the instance's event loop."""
        return self._loop.run_until_complete(coro)

    def add_memory(
        self,
        content: str,
        sector: MemorySector = "episodic",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add a new memory to the cognitive store.
        
        Args:
            content: The text content to store.
            sector: The cognitive sector (episodic, semantic, etc.)
            metadata: Optional structured metadata.
        """
        try:
            # openmemory-py v1.3.2 uses async .add()
            res = self._run_async(self._om.add(
                content=content,
                primary_sector=sector,
                meta=metadata or {},
                tags=[sector]
            ))
            memory_id = res.get("id")
            logger.debug(f"Stored {sector} memory: {memory_id}")
            return str(memory_id)
        except Exception as e:
            logger.error(f"Failed to add memory to OpenMemory: {e}")
            return ""

    def search(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.4,
    ) -> list[dict[str, Any]]:
        """
        Perform a hybrid search (vector + graph) for relevant memories.
        
        Args:
            query: The search terms.
            limit: Maximum number of results.
            min_score: Minimum confidence score.
        """
        try:
            # Hybrid search is the default in OpenMemory async .search()
            results = self._run_async(self._om.search(
                query=query,
                limit=limit,
            ))
            # Filter by score if needed, though search usually does this
            return [r for r in results if r.get("score", 0) >= min_score]
        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return []

    def reflect(self) -> None:
        """
        Trigger a reflection process (associative graph updates).
        Usually called during nightly maintenance.
        """
        try:
            self._om.reflect()
            logger.info("OpenMemory reflection cycle completed.")
        except Exception as e:
            logger.error(f"Reflection failed: {e}")


# Global singleton
_om_store: OpenMemoryStore | None = None


def get_openmemory_store() -> OpenMemoryStore:
    """Get the global OpenMemory store singleton."""
    global _om_store
    if _om_store is None:
        _om_store = OpenMemoryStore()
    return _om_store
