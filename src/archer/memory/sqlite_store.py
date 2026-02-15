"""
ARCHER SQLite Memory Store (Tier 1 + Tier 2).

Tier 1 — Working Memory: Current conversation context, active session state.
         Cleared on session end. (Implemented in LangGraph state for Phase 2)

Tier 2 — Episodic Memory: Conversation logs, observer event log, action audit
         trail, inventory, behavioral drift records. Permanent, queryable by
         date/agent/type.

This module handles all SQLite persistence for ARCHER. It creates and manages
the schema, provides typed access to all tables, and ensures thread-safe access.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from archer.config import get_config


class SQLiteStore:
    """
    Thread-safe SQLite store for ARCHER's Tier 2 episodic memory.

    Handles conversation logs, observation events, action audit trail,
    user inventory, and configuration state.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._config = get_config()
        self._db_path = db_path or self._config.sqlite_db_path
        self._lock = threading.Lock()
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a new SQLite connection (one per thread)."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent reads
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        """Initialize all database tables."""
        conn = self._get_connection()
        try:
            conn.executescript("""
                -- Toggle state (cloud/local mode)
                CREATE TABLE IF NOT EXISTS toggle_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Conversation logs (Tier 2 episodic)
                CREATE TABLE IF NOT EXISTS conversation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,  -- 'user', 'assistant', 'system'
                    agent_name TEXT,
                    content TEXT NOT NULL,
                    metadata TEXT,  -- JSON
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_conv_session
                    ON conversation_logs(session_id);
                CREATE INDEX IF NOT EXISTS idx_conv_timestamp
                    ON conversation_logs(timestamp);
                CREATE INDEX IF NOT EXISTS idx_conv_agent
                    ON conversation_logs(agent_name);

                -- Observation events (Tier 2 — Phase 3+ data, schema defined now)
                CREATE TABLE IF NOT EXISTS observation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,  -- 'webcam', 'mic', 'system'
                    event_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_pointer TEXT,
                    payload TEXT,  -- JSON
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_obs_source
                    ON observation_events(source);
                CREATE INDEX IF NOT EXISTS idx_obs_type
                    ON observation_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_obs_timestamp
                    ON observation_events(timestamp);

                -- Action audit trail
                CREATE TABLE IF NOT EXISTS action_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    description TEXT,
                    success INTEGER NOT NULL DEFAULT 1,
                    error TEXT,
                    metadata TEXT,  -- JSON
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- User inventory (Assistant agent)
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT NOT NULL,
                    category TEXT,
                    location TEXT,
                    last_confirmed TIMESTAMP,
                    notes TEXT,
                    confidence_score REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_inv_name
                    ON inventory(item_name);
                CREATE INDEX IF NOT EXISTS idx_inv_category
                    ON inventory(category);

                -- Voice enrollment (speaker verification)
                CREATE TABLE IF NOT EXISTS voice_enrollment (
                    user_id TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Scheduled tasks
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    cron_expression TEXT,
                    next_run TIMESTAMP,
                    payload TEXT,  -- JSON
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Agent intervention cooldowns
                CREATE TABLE IF NOT EXISTS intervention_cooldowns (
                    agent_name TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    last_intervention TIMESTAMP NOT NULL,
                    PRIMARY KEY (agent_name, topic)
                );
            """)
            conn.commit()
            logger.info(f"SQLite store initialized at {self._db_path}")

        finally:
            conn.close()

    # --- Conversation Logs ---

    def log_conversation(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_name: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Log a conversation entry."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO conversation_logs
                        (session_id, role, agent_name, content, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        role,
                        agent_name,
                        content,
                        json.dumps(metadata) if metadata else None,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_conversation_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get conversation history for a session."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT id, role, agent_name, content, metadata, timestamp
                FROM conversation_logs
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in reversed(rows)]
        finally:
            conn.close()

    # --- Inventory ---

    def add_inventory_item(
        self,
        item_name: str,
        location: str | None = None,
        category: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Add or update an inventory item."""
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            conn = self._get_connection()
            try:
                # Check if item exists
                cursor = conn.execute(
                    "SELECT id FROM inventory WHERE item_name = ?",
                    (item_name,),
                )
                existing = cursor.fetchone()

                if existing:
                    conn.execute(
                        """
                        UPDATE inventory
                        SET location = COALESCE(?, location),
                            category = COALESCE(?, category),
                            notes = COALESCE(?, notes),
                            last_confirmed = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (location, category, notes, now, now, existing["id"]),
                    )
                    conn.commit()
                    return existing["id"]
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO inventory
                            (item_name, location, category, notes, last_confirmed)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (item_name, location, category, notes, now),
                    )
                    conn.commit()
                    return cursor.lastrowid
            finally:
                conn.close()

    def get_inventory_items(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get all inventory items."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT id, item_name as name, category, location, notes,
                       confidence_score, last_confirmed, created_at, updated_at
                FROM inventory
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def search_inventory(self, query: str) -> list[dict[str, Any]]:
        """Search inventory by item name."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM inventory
                WHERE item_name LIKE ?
                ORDER BY last_confirmed DESC
                """,
                (f"%{query}%",),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_recent_conversations(
        self,
        limit: int = 10,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recent conversation entries, optionally filtered by session.

        Returns entries from any session (cross-session context retrieval).
        Used by the Orchestrator to load previous session context on startup.
        """
        conn = self._get_connection()
        try:
            if session_id:
                cursor = conn.execute(
                    """
                    SELECT id, session_id, role, agent_name, content, metadata, timestamp
                    FROM conversation_logs
                    WHERE session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT id, session_id, role, agent_name, content, metadata, timestamp
                    FROM conversation_logs
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            rows = cursor.fetchall()
            return [dict(row) for row in reversed(rows)]
        finally:
            conn.close()

    # --- Observation Events ---

    def log_observation(
        self,
        source: str,
        event_type: str,
        confidence: float,
        evidence_pointer: str | None = None,
        payload: dict | None = None,
    ) -> int:
        """Log an observation event from the Observer pipeline."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO observation_events
                        (source, event_type, confidence, evidence_pointer, payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        event_type,
                        confidence,
                        evidence_pointer,
                        json.dumps(payload) if payload else None,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_recent_observations(
        self,
        event_type: str | None = None,
        source: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get recent observation events, optionally filtered."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM observation_events"
            params: list = []
            conditions = []

            if event_type:
                conditions.append("event_type = ?")
                params.append(event_type)
            if source:
                conditions.append("source = ?")
                params.append(source)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # --- Intervention Cooldowns ---

    def set_cooldown(
        self,
        agent_name: str,
        topic: str,
    ) -> None:
        """Set or update an intervention cooldown for an agent+topic."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO intervention_cooldowns (agent_name, topic, last_intervention)
                    VALUES (?, ?, ?)
                    ON CONFLICT(agent_name, topic) DO UPDATE SET last_intervention = ?
                    """,
                    (agent_name, topic, now, now),
                )
                conn.commit()
            finally:
                conn.close()

    def check_cooldown(
        self,
        agent_name: str,
        topic: str,
        cooldown_minutes: float,
    ) -> bool:
        """
        Check if an agent is in cooldown for a topic.

        Returns True if the agent is STILL in cooldown (should NOT intervene),
        False if the cooldown has expired (OK to intervene).
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT last_intervention FROM intervention_cooldowns
                WHERE agent_name = ? AND topic = ?
                """,
                (agent_name, topic),
            )
            row = cursor.fetchone()
            if row is None:
                return False  # No previous intervention — OK to intervene

            last = datetime.fromisoformat(row["last_intervention"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            return elapsed < (cooldown_minutes * 60)
        finally:
            conn.close()

    def clear_cooldown(self, agent_name: str, topic: str) -> None:
        """Clear a specific cooldown."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "DELETE FROM intervention_cooldowns WHERE agent_name = ? AND topic = ?",
                    (agent_name, topic),
                )
                conn.commit()
            finally:
                conn.close()

    # --- Action Audit ---

    def log_action(
        self,
        agent_name: str,
        action_type: str,
        description: str | None = None,
        success: bool = True,
        error: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Log an action in the audit trail."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO action_audit
                        (agent_name, action_type, description, success, error, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_name,
                        action_type,
                        description,
                        1 if success else 0,
                        error,
                        json.dumps(metadata) if metadata else None,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()


# Global singleton
_store: SQLiteStore | None = None
_store_lock = threading.Lock()


def get_sqlite_store() -> SQLiteStore:
    """Get the global SQLite store singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SQLiteStore()
    return _store
