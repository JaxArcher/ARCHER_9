"""
ARCHER ChromaDB Memory Store (Tier 3 — Semantic Memory).

Tier 3 stores user preferences, facts, habits, relationship graph, and
agent-derived insights. It is queryable by semantic similarity — agents
ask "what do I know about X?" and get relevant context back.

ChromaDB runs as a Docker container on port 8100. This module connects
via the HTTP client. If ChromaDB is not available, all operations fail
silently (non-fatal).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from archer.config import get_config


class ChromaDBStore:
    """
    Semantic memory store backed by ChromaDB.

    Stores conversation summaries, user facts, and agent observations
    as vector embeddings for semantic retrieval.
    """

    COLLECTION_NAME = "archer_memory"

    def __init__(self) -> None:
        self._config = get_config()
        self._client = None
        self._collection = None
        self._lock = threading.Lock()
        self._available = False
        self._connect()

    def _connect(self) -> None:
        """Connect to the ChromaDB container."""
        try:
            import chromadb
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )

            self._client = chromadb.HttpClient(
                host="127.0.0.1",
                port=8100,
            )

            # Verify connection
            self._client.heartbeat()

            # Use all-MiniLM-L6-v2 for embeddings (spec requirement)
            embedding_fn = SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2",
            )

            # Get or create the main collection with embedding function
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
                embedding_function=embedding_fn,
            )

            self._available = True
            count = self._collection.count()
            logger.info(
                f"ChromaDB connected — collection '{self.COLLECTION_NAME}' "
                f"({count} documents)"
            )

        except Exception as e:
            self._available = False
            logger.warning(
                f"ChromaDB not available (is Docker running?): {e}. "
                f"Tier 3 memory disabled — will retry on next access."
            )

    @property
    def is_available(self) -> bool:
        """Check if ChromaDB is connected and ready."""
        return self._available

    def _ensure_connected(self) -> bool:
        """Reconnect if needed. Returns True if connected."""
        if self._available and self._collection is not None:
            return True
        self._connect()
        return self._available

    def store(
        self,
        content: str,
        agent: str,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Store a piece of information in semantic memory.

        Args:
            content: The text to store and embed.
            agent: Which agent created this memory.
            session_id: The session this memory came from.
            metadata: Additional metadata to attach.

        Returns:
            True if stored successfully, False otherwise.
        """
        if not self._ensure_connected():
            return False

        with self._lock:
            try:
                doc_id = f"{agent}_{int(time.time() * 1000)}"
                now = datetime.now(timezone.utc).isoformat()

                doc_metadata = {
                    "agent": agent,
                    "session_id": session_id,
                    "timestamp": now,
                }
                if metadata:
                    doc_metadata.update(metadata)

                self._collection.add(
                    documents=[content],
                    ids=[doc_id],
                    metadatas=[doc_metadata],
                )

                logger.debug(
                    f"Stored in ChromaDB: [{agent}] '{content[:60]}...' (id={doc_id})"
                )
                return True

            except Exception as e:
                logger.warning(f"ChromaDB store failed: {e}")
                self._available = False
                return False

    def query(
        self,
        query_text: str,
        agent: str | None = None,
        n_results: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Query semantic memory by similarity.

        Args:
            query_text: The text to search for similar memories.
            agent: Optional — filter to only this agent's memories.
            n_results: Number of results to return.

        Returns:
            List of dicts with 'content', 'agent', 'timestamp', 'distance'.
        """
        if not self._ensure_connected():
            return []

        with self._lock:
            try:
                where_filter = None
                if agent:
                    where_filter = {"agent": agent}

                # Check if collection has any documents
                if self._collection.count() == 0:
                    return []

                results = self._collection.query(
                    query_texts=[query_text],
                    n_results=min(n_results, self._collection.count()),
                    where=where_filter,
                )

                memories = []
                if results["documents"] and results["documents"][0]:
                    for i, doc in enumerate(results["documents"][0]):
                        meta = results["metadatas"][0][i] if results["metadatas"] else {}
                        distance = (
                            results["distances"][0][i] if results["distances"] else 0.0
                        )
                        memories.append({
                            "content": doc,
                            "agent": meta.get("agent", "unknown"),
                            "timestamp": meta.get("timestamp", ""),
                            "session_id": meta.get("session_id", ""),
                            "distance": distance,
                        })

                return memories

            except Exception as e:
                logger.warning(f"ChromaDB query failed: {e}")
                self._available = False
                return []

    def store_conversation_summary(
        self,
        summary: str,
        agent: str,
        session_id: str,
    ) -> bool:
        """
        Store a conversation summary for long-term retrieval.

        Called after significant interactions to build up the
        semantic context that agents can query later.
        """
        return self.store(
            content=summary,
            agent=agent,
            session_id=session_id,
            metadata={"type": "conversation_summary"},
        )

    def store_user_fact(
        self,
        fact: str,
        agent: str,
        confidence: float = 1.0,
    ) -> bool:
        """
        Store a fact about the user (preference, habit, relationship).

        These are the core of Tier 3 — things ARCHER learns about the user
        over time that any agent can retrieve.
        """
        return self.store(
            content=fact,
            agent=agent,
            metadata={
                "type": "user_fact",
                "confidence": confidence,
            },
        )

    def count(self) -> int:
        """Get the number of documents in the collection."""
        if not self._ensure_connected():
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0


# Global singleton
_store: ChromaDBStore | None = None
_store_lock = threading.Lock()


def get_chromadb_store() -> ChromaDBStore:
    """Get the global ChromaDB store singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ChromaDBStore()
    return _store
