"""
ARCHER OpenMemory Cognitive Store (Layer 3 Memory).

Purpose: Graph-based associative memory with temporal knowledge graphs.
Sectors: Episodic, Semantic, Procedural, Emotional, Reflective.
"""

from typing import Any, Literal

from openmemory import OpenMemory
from loguru import logger

from archer.config import get_config

MemorySector = Literal["episodic", "semantic", "procedural", "emotional", "reflective"]


class OpenMemoryStore:
    """
    Layer 3: Cognitive storage using OpenMemory.
    Provides graph-based associative recall and sector-based classification.
    """

    def __init__(self) -> None:
        self._config = get_config()
        try:
            # Initialize OpenMemory with local SQLite storage
            self._om = OpenMemory(
                db_path=str(self._config.openmemory_db),
            )
            logger.info(f"OpenMemory store initialized at {self._config.openmemory_db}")
        except Exception as e:
            logger.error(f"Failed to initialize OpenMemory: {e}")
            raise

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
            # Note: openmemory-py v1.3.2 uses .remember() or .add() depending on the engine
            # but usually it's .add() for the SDK.
            memory_id = self._om.add(
                content=content,
                sector=sector,
                metadata=metadata or {},
            )
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
            # Hybrid search is the default in OpenMemory
            results = self._om.search(
                query=query,
                limit=limit,
            )
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
