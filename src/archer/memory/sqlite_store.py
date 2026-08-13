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

                -- --- BLINDSPOT AGENT TABLES ---

                -- User behavior baselines (learned over time)
                CREATE TABLE IF NOT EXISTS user_baselines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    calculated_value REAL,
                    observations_count INTEGER DEFAULT 0,
                    state TEXT DEFAULT 'calibrating', -- 'calibrating', 'active'
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(category, metric)
                );

                -- Detailed behavior observations (for baseline calculation)
                CREATE TABLE IF NOT EXISTS behavior_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    metadata TEXT, -- JSON
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- ADHD state tracking
                CREATE TABLE IF NOT EXISTS adhd_state_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    detected_state TEXT NOT NULL, -- 'hyperfocus', 'paralysis', etc.
                    confidence REAL,
                    trigger_context TEXT, -- JSON
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Task completion tracking (ADHD pattern)
                CREATE TABLE IF NOT EXISTS task_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity TEXT NOT NULL,
                    status TEXT DEFAULT 'active', -- 'active', 'completed', 'abandoned'
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    interruptions_count INTEGER DEFAULT 0,
                    metadata TEXT -- JSON
                );

                -- Relationship & Social Tracking
                CREATE TABLE IF NOT EXISTS social_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    relationship TEXT, -- 'family', 'friend', 'colleague'
                    typical_interval_days REAL,
                    last_interaction_at TIMESTAMP,
                    metadata TEXT, -- JSON
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS social_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_id INTEGER NOT NULL,
                    interaction_type TEXT, -- 'call', 'text', 'in-person'
                    sentiment_score REAL,
                    notes TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (contact_id) REFERENCES social_contacts(id)
                );

                CREATE TABLE IF NOT EXISTS social_commitments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_id INTEGER NOT NULL,
                    promise TEXT NOT NULL,
                    due_date TIMESTAMP,
                    fulfilled_at TIMESTAMP,
                    status TEXT DEFAULT 'pending', -- 'pending', 'fulfilled', 'failed'
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (contact_id) REFERENCES social_contacts(id)
                );

                -- --- INVENTORY MANAGER TABLES ---

                -- Storage locations (hierarchy)
                CREATE TABLE IF NOT EXISTS storage_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    location_name TEXT NOT NULL,
                    room TEXT,
                    furniture_type TEXT, -- 'table', 'shelf', 'drawer', etc.
                    level INTEGER,
                    is_visible BOOLEAN DEFAULT 1,
                    parent_location_id INTEGER,
                    coordinates TEXT, -- JSON
                    FOREIGN KEY (parent_location_id) REFERENCES storage_locations(id)
                );

                -- Master items (replaces simpler inventory table)
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT NOT NULL,
                    category TEXT,
                    brand TEXT,
                    model TEXT,
                    serial_number TEXT,
                    barcode TEXT,
                    estimated_value REAL,
                    is_consumable BOOLEAN DEFAULT 0,
                    persistent_object_id TEXT UNIQUE,
                    notes TEXT,
                    current_location_id INTEGER,
                    last_seen_at TIMESTAMP,
                    image_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (current_location_id) REFERENCES storage_locations(id)
                );

                CREATE INDEX IF NOT EXISTS idx_inv_items_name ON inventory_items(item_name);
                CREATE INDEX IF NOT EXISTS idx_inv_items_object_id ON inventory_items(persistent_object_id);

                -- Location history
                CREATE TABLE IF NOT EXISTS item_location_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    location_id INTEGER NOT NULL,
                    confidence REAL,
                    still_there BOOLEAN DEFAULT 1,
                    placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    removed_at TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES inventory_items(id),
                    FOREIGN KEY (location_id) REFERENCES storage_locations(id)
                );

                -- Consumables tracking
                CREATE TABLE IF NOT EXISTS consumables (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL UNIQUE,
                    unit TEXT, -- 'count', 'liters', etc.
                    current_quantity REAL,
                    low_threshold REAL,
                    ideal_quantity REAL,
                    usage_rate_per_day REAL,
                    estimated_days_remaining INTEGER,
                    last_restocked_at TIMESTAMP,
                    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES inventory_items(id)
                );

                -- Purchase records
                CREATE TABLE IF NOT EXISTS item_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    purchase_date DATE,
                    price REAL,
                    vendor TEXT,
                    receipt_path TEXT,
                    FOREIGN KEY (item_id) REFERENCES inventory_items(id)
                );

                -- Warranties
                CREATE TABLE IF NOT EXISTS item_warranties (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    warranty_type TEXT, -- 'manufacturer', 'extended'
                    start_date DATE,
                    end_date DATE,
                    document_path TEXT,
                    FOREIGN KEY (item_id) REFERENCES inventory_items(id)
                );

                -- Borrowed & Lent
                CREATE TABLE IF NOT EXISTS borrowed_lent_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    person_name TEXT NOT NULL,
                    transaction_type TEXT, -- 'borrowed', 'lent'
                    expected_return_date TIMESTAMP,
                    actual_return_date TIMESTAMP,
                    status TEXT DEFAULT 'active', -- 'active', 'returned'
                    notes TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES inventory_items(id)
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
    def search_conversations_fts(self, query: str, limit: int = 10) -> list:
        """Fast full-text search using FTS5."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT c.id, c.session_id, c.role, c.agent_name, c.content, 
                       c.metadata, c.timestamp, fts.rank 
                FROM conversation_logs_fts fts
                JOIN conversation_logs c ON c.id = fts.rowid
                WHERE conversation_logs_fts MATCH ?
                ORDER BY fts.rank
                LIMIT ?
                """,
                (query, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
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

    # --- Configuration / Toggle State ---

    def set_configuration(self, key: str, value: str) -> None:
        """Set a persistent configuration value."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO toggle_state (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, value, value),
                )
                conn.commit()
            finally:
                conn.close()

    def get_configuration(self, key: str) -> str | None:
        """Get a persistent configuration value."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT value FROM toggle_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None
        finally:
            conn.close()

    def get_therapist_status(self) -> dict[str, Any]:
        """
        Determine the current phase of the Therapist agent.
        
        Phases:
        - profiling: Week 1-2 (Initial assessment)
        - baseline: Week 3-4 (Passive observation)
        - active: Week 5+ (Proactive intervention)
        """
        start_date_str = self.get_configuration("therapist_enrollment_date")
        if not start_date_str:
            # First time running — set the enrollment date
            now = datetime.now(timezone.utc).isoformat()
            self.set_configuration("therapist_enrollment_date", now)
            start_date = datetime.now(timezone.utc)
        else:
            try:
                start_date = datetime.fromisoformat(start_date_str)
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)
            except ValueError:
                start_date = datetime.now(timezone.utc)

        elapsed_days = (datetime.now(timezone.utc) - start_date).days
        
        if elapsed_days < 14:
            phase = "profiling"
        elif elapsed_days < 28:
            phase = "baseline"
        else:
            phase = "active"
            
        return {
            "phase": phase,
            "days_active": elapsed_days,
            "start_date": start_date.isoformat()
        }


            # ====== ADD ALL THE NEW METHODS HERE ======
            
    def log_pending_confirmation(self, emotion: str, confidence: float, observation_id: int) -> int:
        """Log a pending emotion confirmation."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO emotion_confirmations 
            (timestamp, detected_emotion, confidence, observation_id)
            VALUES (?, ?, ?, ?)
            """,
            (time.time(), emotion, confidence, observation_id),
        )
        self._conn.commit()
        return cursor.lastrowid

    def update_emotion_confirmation(self, emotion: str, confidence: float, user_confirmed: bool, actual_emotion: str = None) -> None:
        """Update emotion confirmation with user response."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            UPDATE emotion_confirmations
            SET user_confirmed = ?, user_actual_emotion = ?
            WHERE detected_emotion = ? AND confidence = ?
            AND user_confirmed IS NULL
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (user_confirmed, actual_emotion, emotion, confidence),
        )
        self._conn.commit()

    def get_emotion_confirmation_stats(self, emotion: str) -> dict:
        """Get confirmation accuracy stats for an emotion."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT * FROM emotion_confirmation_stats
            WHERE detected_emotion = ?
            """,
            (emotion,),
        )
        row = cursor.fetchone()
        if not row:
            return {"total_detections": 0, "confirmed": 0, "accuracy": 0.0}
        return {
            "total_detections": row[1],
            "confirmed": row[2],
            "rejected": row[3],
            "accuracy": row[4],
            "avg_confidence": row[5],
        }

    def get_therapist_status(self) -> dict:
        """Get current therapist profiling status."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT phase, current_week, days_active, baseline_established
                    FROM therapist_profiling
                    WHERE id = 1
                    """
                )
                row = cursor.fetchone()
                if not row:
                    conn.execute(
                        """
                        INSERT INTO therapist_profiling 
                        (id, start_date, phase, current_week, last_updated)
                        VALUES (1, ?, 'profiling', 1, ?)
                        """,
                        (time.time(), time.time()),
                    )
                    conn.commit()
                    return {"phase": "profiling", "days_active": 0, "current_week": 1, "baseline_established": False}
                
                start_row = conn.execute("SELECT start_date FROM therapist_profiling WHERE id = 1").fetchone()
                start_date = start_row[0] if start_row else time.time()
                days_active = int((time.time() - start_date) / 86400)
                
                return {
                    "phase": row[0],
                    "current_week": row[1],
                    "days_active": days_active,
                    "baseline_established": bool(row[3]),
                }
            except Exception:
                return {"phase": "profiling", "days_active": 0, "current_week": 1, "baseline_established": False}

    def save_exercise_response(self, segment_id: str, question_id: str, response: str) -> None:
        """Save exercise response."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO exercise_responses
                    (segment_id, question_id, response, timestamp)
                    VALUES (?, ?, ?, ?)
                    """,
                    (segment_id, question_id, response, time.time()),
                )
                conn.execute(
                    """
                    UPDATE exercise_segments
                    SET questions_answered = questions_answered + 1
                    WHERE segment_id = ?
                    """,
                    (segment_id,),
                )
                conn.commit()
            except Exception as e:
                logger.debug(f"Failed to save exercise response: {e}")

    def get_profiling_start_date(self) -> float | None:
        """Get profiling start date timestamp."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("SELECT start_date FROM therapist_profiling WHERE id = 1")
                row = cursor.fetchone()
                return row[0] if row else None
            except Exception:
                return None

    def get_last_profiling_question_time(self) -> float | None:
        """Get timestamp of last profiling question."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("SELECT MAX(timestamp) FROM exercise_responses")
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
            except Exception:
                return None

    def log_pending_confirmation(self, emotion: str, confidence: float, observation_id: int) -> None:
        """Log a pending emotion confirmation."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS emotion_confirmations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        emotion TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        observation_id INTEGER,
                        confirmed INTEGER,
                        actual_emotion TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute(
                    """
                    INSERT INTO emotion_confirmations (emotion, confidence, observation_id)
                    VALUES (?, ?, ?)
                    """,
                    (emotion, confidence, observation_id),
                )
                conn.commit()
            except Exception as e:
                logger.debug(f"Failed to log pending confirmation: {e}")

    def update_emotion_confirmation(
        self, emotion: str, confidence: float, user_confirmed: bool, actual_emotion: str | None = None
    ) -> None:
        """Update an emotion confirmation result."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS emotion_confirmations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        emotion TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        observation_id INTEGER,
                        confirmed INTEGER,
                        actual_emotion TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute(
                    """
                    INSERT INTO emotion_confirmations (emotion, confidence, confirmed, actual_emotion)
                    VALUES (?, ?, ?, ?)
                    """,
                    (emotion, confidence, 1 if user_confirmed else 0, actual_emotion),
                )
                conn.commit()
            except Exception as e:
                logger.debug(f"Failed to update emotion confirmation: {e}")

    def get_emotion_confirmation_stats(self, emotion: str) -> dict:
        """Get historical accuracy stats for a given emotion."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT COUNT(*), SUM(CASE WHEN confirmed = 1 THEN 1 ELSE 0 END)
                    FROM emotion_confirmations
                    WHERE emotion = ? AND confirmed IS NOT NULL
                    """,
                    (emotion,),
                )
                row = cursor.fetchone()
                if not row or not row[0]:
                    return {"total_detections": 0, "confirmed": 0, "accuracy": 0.0}
                total, confirmed = row[0], row[1] or 0
                return {"total_detections": total, "confirmed": confirmed, "accuracy": confirmed / total}
            except Exception:
                return {"total_detections": 0, "confirmed": 0, "accuracy": 0.0}

# ====== END OF NEW METHODS ======


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