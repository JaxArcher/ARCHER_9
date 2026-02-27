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

    def __init__(self) -> None:
        self._config = get_config()
        self._client = None
        self._collections = {}
        self._lock = threading.Lock()
        self._available = False
        self._connect()

    def _connect(self) -> None:
        """Connect to the ChromaDB container or a local persistent store."""
        try:
            import chromadb

            # Try Docker HTTP connection first
            try:
                self._client = chromadb.HttpClient(
                    host="127.0.0.1",
                    port=8100,
                )
                self._client.heartbeat()
                self._available = True
                logger.info("ChromaDB connected (HTTP 127.0.0.1:8100)")
            except Exception:
                # Fallback to local persistent client
                local_path = self._config.data_dir / "chromadb"
                local_path.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(local_path)
                )
                self._available = True
                logger.info(f"ChromaDB using local storage at {local_path}")

        except Exception as e:
            self._available = False
            logger.warning(
                f"ChromaDB not available: {e}. "
                f"Tier 3 memory disabled."
            )

    def _get_collection(self, name: str = "archer_memory"):
        """Get or create a named collection."""
        if not self._available or self._client is None:
            return None
        
        if name in self._collections:
            return self._collections[name]
        
        try:
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )
            # Use all-MiniLM-L6-v2 for embeddings (spec requirement)
            embedding_fn = SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2",
            )

            collection = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=embedding_fn,
            )
            self._collections[name] = collection
            return collection
        except Exception as e:
            logger.error(f"Failed to get collection {name}: {e}")
            return None

    @property
    def is_available(self) -> bool:
        """Check if ChromaDB is connected and ready."""
        return self._available

    def _ensure_connected(self) -> bool:
        """Reconnect if needed. Returns True if connected."""
        if self._available and self._client is not None:
            return True
        self._connect()
        return self._available

    def store(
        self,
        content: str,
        agent: str,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
        collection_name: str = "archer_memory",
    ) -> bool:
        """
        Store a piece of information in semantic memory.

        Args:
            content: The text to store and embed.
            agent: Which agent created this memory.
            session_id: The session this memory came from.
            metadata: Additional metadata to attach.
            collection_name: Target collection.

        Returns:
            True if stored successfully, False otherwise.
        """
        if not self._ensure_connected():
            return False

        collection = self._get_collection(collection_name)
        if not collection:
            return False

        with self._lock:
            try:
                doc_id = f"{agent}_{int(time.time() * 1000)}_{hash(content) % 1000}"
                now = datetime.now(timezone.utc).isoformat()

                doc_metadata = {
                    "agent": agent,
                    "session_id": session_id,
                    "timestamp": now,
                }
                if metadata:
                    doc_metadata.update(metadata)

                collection.add(
                    documents=[content],
                    ids=[doc_id],
                    metadatas=[doc_metadata],
                )

                logger.debug(
                    f"Stored in ChromaDB [{collection_name}]: [{agent}] '{content[:60]}...' (id={doc_id})"
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
        collection_name: str = "archer_memory",
    ) -> list[dict[str, Any]]:
        """
        Query semantic memory by similarity.

        Args:
            query_text: The text to search for similar memories.
            agent: Optional — filter to only this agent's memories.
            n_results: Number of results to return.
            collection_name: Collection to query.

        Returns:
            List of dicts with 'content', 'agent', 'timestamp', 'distance'.
        """
        if not self._ensure_connected():
            return []

        collection = self._get_collection(collection_name)
        if not collection:
            return []

        with self._lock:
            try:
                where_filter = None
                if agent:
                    where_filter = {"agent": agent}

                # Check if collection has any documents
                if collection.count() == 0:
                    return []

                results = collection.query(
                    query_texts=[query_text],
                    n_results=min(n_results, collection.count()),
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
                            "metadata": meta,
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
        Store a fact about the user.
        """
        return self.store(
            content=fact,
            agent=agent,
            metadata={
                "type": "user_fact",
                "confidence": confidence,
            },
        )

    def count(self, collection_name: str = "archer_memory") -> int:
        """Get the number of documents in a collection."""
        if not self._ensure_connected():
            return 0
        collection = self._get_collection(collection_name)
        if not collection:
            return 0
        try:
            return collection.count()
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
