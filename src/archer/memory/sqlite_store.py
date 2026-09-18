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

                -- Known enrolled persons (Person Identification)
                CREATE TABLE IF NOT EXISTS known_persons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    embedding BLOB NOT NULL,
                    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Person sightings (known & unrecognized repeat visitors)
                CREATE TABLE IF NOT EXISTS person_sightings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id TEXT NOT NULL,
                    is_known INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    embedding BLOB,
                    snapshot_path TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    camera_source TEXT NOT NULL DEFAULT 'webcam'
                );

                CREATE INDEX IF NOT EXISTS idx_sightings_person
                    ON person_sightings(person_id);
                CREATE INDEX IF NOT EXISTS idx_sightings_timestamp
                    ON person_sightings(timestamp);

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

                -- --- PATTERN RECOGNITION / RECURSIVE LEARNING (2026-09-16) ---
                -- Structured entity glossary extracted from conversation, in
                -- real time, per turn (Col's call) by memory/pattern_learner.py.
                -- Kept as real rows (not just OpenMemory vector search) so the
                -- Memory tab can list them as a plain list, and so ARCHER can
                -- deterministically resolve a nickname/abbreviation instead of
                -- relying on fuzzy semantic recall.
                CREATE TABLE IF NOT EXISTS learned_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL, -- 'person', 'organization', 'nickname', 'abbreviation'
                    resolves_to TEXT, -- for nickname/abbreviation: the canonical_name it refers to
                    definition TEXT, -- short note on what/who this is, if known
                    mention_count INTEGER DEFAULT 1,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(canonical_name, entity_type)
                );
                CREATE INDEX IF NOT EXISTS idx_learned_entities_type ON learned_entities(entity_type);

                -- Recurring conversational themes: verbal fillers, frustration
                -- triggers (esp. "AI lacked context"), and similar patterns
                -- the system notices repeating across turns.
                CREATE TABLE IF NOT EXISTS conversation_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_type TEXT NOT NULL, -- 'verbal_filler', 'frustration_trigger', 'other'
                    label TEXT NOT NULL, -- e.g. 'says "like" often', 'frustrated when context missing'
                    occurrence_count INTEGER DEFAULT 1,
                    last_example TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(pattern_type, label)
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_patterns_type ON conversation_patterns(pattern_type);

                -- Durable record of every intervention BlindspotAgent's
                -- DecisionEngine actually decided was worth surfacing
                -- (2026-09-16). Previously this only ever lived in a single
                -- in-memory string on CoreAgent (_pending_blindspot_flag) --
                -- overwritten by the next one, lost on restart, and never
                -- populated at all while CoreAgent's process wasn't running.
                -- Now BlindspotAgent runs inside archer/observer_service.py
                -- too (decision-making no longer depends on the GUI/browser
                -- session being open), and every decided intervention is
                -- written here first. delivered_at is set once it's been
                -- folded into a CoreAgent system prompt at least once (see
                -- core_agent.py's startup catch-up + build_context_system_
                -- prompt) -- rows stay here regardless, for the browser
                -- MEMORY tab's "while you were away" history.
                CREATE TABLE IF NOT EXISTS pending_interventions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    severity INTEGER,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT 'blindspot',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    delivered_at TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_pending_interventions_delivered ON pending_interventions(delivered_at);

                -- Recurring UNKNOWN faces waiting on a name (2026-09-16,
                -- Col's call: no manual enrollment step for anyone but
                -- himself). One row per distinct unrecognized face-cluster
                -- ("Person_2", "Person_3", ...) -- person_id.py upserts this
                -- every time identify_persons() sees a face it can't match
                -- to known_persons, so a stranger seen once still gets a
                -- row but a stranger seen repeatedly just bumps
                -- sighting_count instead of piling up duplicates. The
                -- browser MEMORY tab's "Unrecognized People" pane lets Col
                -- name one from its snapshot whenever he next looks -- that
                -- calls add_known_person() with THIS row's embedding and
                -- resolves the row. The other, faster path (a live "this is
                -- Sarah" while she's in frame) binds immediately via
                -- CoreAgent._check_person_introduction and resolves the row
                -- without Col ever visiting this pane.
                CREATE TABLE IF NOT EXISTS pending_person_confirmations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id TEXT NOT NULL UNIQUE,
                    embedding BLOB NOT NULL,
                    snapshot_path TEXT,
                    sighting_count INTEGER NOT NULL DEFAULT 1,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'confirmed' | 'dismissed'
                    confirmed_name TEXT,
                    resolved_at TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_pending_person_confirmations_status ON pending_person_confirmations(status);

                -- --- TASKS TAB (2026-09-16) ---
                -- Deliberately separate from scheduled_tasks (defined but
                -- never referenced anywhere) and task_tracking (used
                -- internally only by Blindspot's own ADHD pattern
                -- detection) -- neither is a real to-do system and both
                -- have incompatible shapes/purposes for one. Available to
                -- every agent persona via the tasks_SKILL.md tool set,
                -- same as every other tool (Col's call).
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    due_date TIMESTAMP,
                    status TEXT DEFAULT 'pending', -- 'pending', 'completed'
                    source TEXT DEFAULT 'user', -- 'user', 'assistant', 'therapist', ...
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

                -- Habits are in v1 alongside tasks, not a later add-on
                -- (Col's call). streak_count is the current consecutive-
                -- completion streak; last_completed_at is what
                -- complete_habit uses to decide whether today already
                -- counted, and whether a gap broke the streak.
                CREATE TABLE IF NOT EXISTS habits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    frequency TEXT DEFAULT 'daily', -- 'daily', 'weekly'
                    streak_count INTEGER DEFAULT 0,
                    last_completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Standing profile facts (2026-09-17, ARCHER "reflective
                -- mode" design -- see /areas/reflective-mode.md). Deliberately
                -- a plain deterministic SQLite table, NOT OpenMemory/Chroma
                -- similarity search -- same reasoning as pattern_learner's
                -- entity glossary: this needs to show up in EVERY relevant
                -- prompt regardless of whether this turn's text happens to
                -- be semantically similar to it, which a vector search
                -- can't guarantee. One row per distilled insight (domain +
                -- one/two sentences), not raw transcript -- written by
                -- CoreAgent._maybe_extract_profile_insight after a
                -- reflective-mode turn, gated behind
                -- config.profile_learning_enabled (default False) so this
                -- table stays empty until Col explicitly turns it on.
                -- Read by build_context_system_prompt to assemble a
                -- standing "## User Profile" block for LOCAL-ONLY prompts
                -- specifically -- see that function's profile_block
                -- handling for why this must never reach _stream_cloud.
                CREATE TABLE IF NOT EXISTS profile_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL, -- e.g. 'motivation', 'executive_function', 'criticism_response'
                    content TEXT NOT NULL,
                    source TEXT DEFAULT 'reflective_mode',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    def get_observations_since(
        self, event_type: str, since_hours: float, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Observation events of one type from the last `since_hours`
        hours, oldest first (chronological -- built for feeding an LLM a
        timeline, e.g. observer/staleness_reasoner.py)."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM observation_events
                WHERE event_type = ? AND julianday('now') - julianday(timestamp) <= ?
                ORDER BY timestamp ASC LIMIT ?
                """,
                (event_type, since_hours / 24.0, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # --- Person Identification ---

    def add_known_person(self, name: str, embedding: bytes) -> int:
        """Add or update an enrolled person with their face embedding BLOB."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO known_persons (name, embedding)
                    VALUES (?, ?)
                    ON CONFLICT(name) DO UPDATE SET embedding = excluded.embedding
                    """,
                    (name, embedding),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_known_persons(self) -> list[dict[str, Any]]:
        """Retrieve all enrolled known persons."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM known_persons ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def log_person_sighting(
        self,
        person_id: str,
        is_known: bool,
        confidence: float,
        embedding: bytes | None = None,
        snapshot_path: str | None = None,
        camera_source: str = "webcam",
    ) -> int:
        """Log a person sighting (known or unknown repeat visitor)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO person_sightings
                        (person_id, is_known, confidence, embedding, snapshot_path, camera_source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (person_id, 1 if is_known else 0, confidence, embedding, snapshot_path, camera_source),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_person_sightings(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent person sightings, including embeddings for matching unknown repeat visitors."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM person_sightings ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_day_observations(self, date_str: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """
        Pull all scene observations and person sightings for a given date (YYYY-MM-DD).
        If date_str is None, uses today's date in local time.
        """
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        conn = self._get_connection()
        try:
            obs_cursor = conn.execute(
                """
                SELECT * FROM observation_events
                WHERE (date(timestamp, 'localtime') = ? OR strftime('%Y-%m-%d', timestamp) = ?) AND event_type = 'scene'
                ORDER BY timestamp ASC
                """,
                (date_str, date_str),
            )
            observations = [dict(row) for row in obs_cursor.fetchall()]

            sightings_cursor = conn.execute(
                """
                SELECT * FROM person_sightings
                WHERE (date(timestamp, 'localtime') = ? OR strftime('%Y-%m-%d', timestamp) = ?)
                ORDER BY timestamp ASC
                """,
                (date_str, date_str),
            )
            sightings = [dict(row) for row in sightings_cursor.fetchall()]

            return {
                "date": date_str,
                "observations": observations,
                "sightings": sightings,
            }
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

    # --- Social / Relationship Tracking (2026-09-16) ---
    # social_contacts/social_interactions/social_commitments existed in the
    # schema since before this session but had zero accessor methods --
    # RelationshipTracker's methods were all stubs/logger.info calls with
    # nothing underneath. These make the tables real.

    def upsert_contact(
        self,
        name: str,
        relationship: str | None = None,
        typical_interval_days: float | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Create a contact, or update relationship/interval/metadata if one
        with this name already exists (name is UNIQUE)."""
        with self._lock:
            conn = self._get_connection()
            try:
                existing = conn.execute(
                    "SELECT id FROM social_contacts WHERE name = ?", (name,)
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE social_contacts
                        SET relationship = COALESCE(?, relationship),
                            typical_interval_days = COALESCE(?, typical_interval_days),
                            metadata = COALESCE(?, metadata)
                        WHERE id = ?
                        """,
                        (relationship, typical_interval_days,
                         json.dumps(metadata) if metadata else None, existing["id"]),
                    )
                    conn.commit()
                    return existing["id"]
                cursor = conn.execute(
                    """
                    INSERT INTO social_contacts (name, relationship, typical_interval_days, metadata)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, relationship, typical_interval_days,
                     json.dumps(metadata) if metadata else None),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_contacts(self) -> list[dict[str, Any]]:
        """List all known social contacts."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM social_contacts ORDER BY last_interaction_at DESC NULLS LAST, name ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_contact_by_name(self, name: str) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM social_contacts WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def log_interaction(
        self,
        contact_name: str,
        interaction_type: str,
        notes: str | None = None,
        sentiment_score: float | None = None,
    ) -> int:
        """Record an interaction and bump the contact's last_interaction_at.
        Auto-creates the contact if it doesn't exist yet."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT id FROM social_contacts WHERE name = ? COLLATE NOCASE", (contact_name,)
                ).fetchone()
                if row:
                    contact_id = row["id"]
                else:
                    cursor = conn.execute(
                        "INSERT INTO social_contacts (name) VALUES (?)", (contact_name,)
                    )
                    contact_id = cursor.lastrowid
                cursor = conn.execute(
                    """
                    INSERT INTO social_interactions (contact_id, interaction_type, sentiment_score, notes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (contact_id, interaction_type, sentiment_score, notes),
                )
                conn.execute(
                    "UPDATE social_contacts SET last_interaction_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (contact_id,),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_interactions(self, contact_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            if contact_name:
                rows = conn.execute(
                    """
                    SELECT si.*, sc.name AS contact_name
                    FROM social_interactions si
                    JOIN social_contacts sc ON sc.id = si.contact_id
                    WHERE sc.name = ? COLLATE NOCASE
                    ORDER BY si.timestamp DESC LIMIT ?
                    """,
                    (contact_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT si.*, sc.name AS contact_name
                    FROM social_interactions si
                    JOIN social_contacts sc ON sc.id = si.contact_id
                    ORDER BY si.timestamp DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def track_commitment(
        self,
        contact_name: str,
        promise: str,
        due_date: str | None = None,
    ) -> int:
        """Record a promise made to someone. Auto-creates the contact if
        unknown (so this works even when the name comes from a rough
        heuristic extraction, not a pre-enrolled contact)."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT id FROM social_contacts WHERE name = ? COLLATE NOCASE", (contact_name,)
                ).fetchone()
                if row:
                    contact_id = row["id"]
                else:
                    cursor = conn.execute(
                        "INSERT INTO social_contacts (name) VALUES (?)", (contact_name,)
                    )
                    contact_id = cursor.lastrowid
                cursor = conn.execute(
                    """
                    INSERT INTO social_commitments (contact_id, promise, due_date)
                    VALUES (?, ?, ?)
                    """,
                    (contact_id, promise, due_date),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_commitments(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            if status:
                rows = conn.execute(
                    """
                    SELECT scm.*, sc.name AS contact_name
                    FROM social_commitments scm
                    JOIN social_contacts sc ON sc.id = scm.contact_id
                    WHERE scm.status = ?
                    ORDER BY scm.timestamp DESC LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT scm.*, sc.name AS contact_name
                    FROM social_commitments scm
                    JOIN social_contacts sc ON sc.id = scm.contact_id
                    ORDER BY scm.timestamp DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def resolve_commitment(self, commitment_id: int, fulfilled: bool = True) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE social_commitments
                    SET status = ?, fulfilled_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE fulfilled_at END
                    WHERE id = ?
                    """,
                    ("fulfilled" if fulfilled else "failed", 1 if fulfilled else 0, commitment_id),
                )
                conn.commit()
            finally:
                conn.close()

    def find_neglected_contacts(self) -> list[dict[str, Any]]:
        """Contacts whose typical_interval_days has been exceeded since
        last_interaction_at. Only considers contacts with an interval set --
        one-off name mentions with no cadence expectation don't count as
        'neglected'."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT *,
                    CAST(julianday('now') - julianday(last_interaction_at) AS REAL) AS days_since
                FROM social_contacts
                WHERE typical_interval_days IS NOT NULL
                  AND (
                        last_interaction_at IS NULL
                        OR julianday('now') - julianday(last_interaction_at) > typical_interval_days
                      )
                ORDER BY days_since DESC NULLS FIRST
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def find_unfulfilled_commitments(self, grace_period_days: int = 3) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT scm.*, sc.name AS contact_name
                FROM social_commitments scm
                JOIN social_contacts sc ON sc.id = scm.contact_id
                WHERE scm.status = 'pending'
                  AND (
                        (scm.due_date IS NOT NULL AND julianday('now') - julianday(scm.due_date) > ?)
                        OR (scm.due_date IS NULL AND julianday('now') - julianday(scm.timestamp) > ?)
                      )
                ORDER BY scm.timestamp ASC
                """,
                (grace_period_days, grace_period_days),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # --- Pattern Recognition / Recursive Learning (2026-09-16) ---

    def upsert_learned_entity(
        self,
        canonical_name: str,
        entity_type: str,
        resolves_to: str | None = None,
        definition: str | None = None,
    ) -> int:
        """Record a mention of an entity, or bump its count if already known.
        entity_type: 'person' | 'organization' | 'nickname' | 'abbreviation'."""
        with self._lock:
            conn = self._get_connection()
            try:
                existing = conn.execute(
                    "SELECT id, mention_count FROM learned_entities WHERE canonical_name = ? AND entity_type = ?",
                    (canonical_name, entity_type),
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE learned_entities
                        SET mention_count = mention_count + 1,
                            last_seen = CURRENT_TIMESTAMP,
                            resolves_to = COALESCE(?, resolves_to),
                            definition = COALESCE(?, definition)
                        WHERE id = ?
                        """,
                        (resolves_to, definition, existing["id"]),
                    )
                    conn.commit()
                    return existing["id"]
                cursor = conn.execute(
                    """
                    INSERT INTO learned_entities (canonical_name, entity_type, resolves_to, definition)
                    VALUES (?, ?, ?, ?)
                    """,
                    (canonical_name, entity_type, resolves_to, definition),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_learned_entities(self, entity_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            if entity_type:
                rows = conn.execute(
                    """
                    SELECT * FROM learned_entities WHERE entity_type = ?
                    ORDER BY mention_count DESC, last_seen DESC LIMIT ?
                    """,
                    (entity_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM learned_entities
                    ORDER BY mention_count DESC, last_seen DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_pending_intervention(
        self,
        category: str,
        metric: str,
        content: str,
        severity: int | None = None,
        source: str = "blindspot",
    ) -> int:
        """Durably record a decided intervention (see the pending_interventions
        schema comment for why this exists). Returns the new row's id."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO pending_interventions (category, metric, severity, content, source)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (category, metric, severity, content, source),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()

    def get_undelivered_interventions(self, limit: int = 500) -> list[dict[str, Any]]:
        """Everything not yet folded into a CoreAgent system prompt at least
        once -- oldest first, so a startup catch-up reads them in the order
        they actually happened."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM pending_interventions
                WHERE delivered_at IS NULL
                ORDER BY created_at ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_interventions_delivered(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            conn = self._get_connection()
            try:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE pending_interventions SET delivered_at = CURRENT_TIMESTAMP "
                    f"WHERE id IN ({placeholders})",
                    ids,
                )
                conn.commit()
            finally:
                conn.close()

    def get_recent_interventions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Full history (delivered or not) for the browser MEMORY tab's
        'while you were away' list -- independent of whether CoreAgent has
        already folded a given row into conversation context."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM pending_interventions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_profile_fact(self, domain: str, content: str, source: str = "reflective_mode") -> int:
        """Store one distilled profile insight -- see the profile_facts
        schema comment for why this is a plain table rather than a vector
        store entry. Returns the new row's id."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "INSERT INTO profile_facts (domain, content, source) VALUES (?, ?, ?)",
                    (domain, content, source),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def get_profile_facts(self, limit: int = 30) -> list[dict[str, Any]]:
        """Everything in the standing profile, most recent first. Plain
        SELECT, no similarity scoring -- see build_context_system_prompt's
        profile_block for how this becomes a standing prompt block rather
        than something retrieved per-turn by relevance."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM profile_facts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def upsert_pending_person_confirmation(
        self,
        person_id: str,
        embedding: bytes,
        snapshot_path: str | None = None,
    ) -> None:
        """Record/bump an unrecognized face-cluster as waiting on a name.

        No-op once that person_id has already been resolved (confirmed or
        dismissed) -- otherwise a stranger Col dismissed once would just
        get re-queued on their next sighting, and a face he already named
        via the live-introduction path would briefly flicker back into the
        pane before its next sighting re-matches known_persons."""
        with self._lock:
            conn = self._get_connection()
            try:
                existing = conn.execute(
                    "SELECT status FROM pending_person_confirmations WHERE person_id = ?",
                    (person_id,),
                ).fetchone()
                if existing and existing["status"] != "pending":
                    return
                conn.execute(
                    """
                    INSERT INTO pending_person_confirmations (person_id, embedding, snapshot_path)
                    VALUES (?, ?, ?)
                    ON CONFLICT(person_id) DO UPDATE SET
                        embedding = excluded.embedding,
                        snapshot_path = COALESCE(excluded.snapshot_path, pending_person_confirmations.snapshot_path),
                        sighting_count = pending_person_confirmations.sighting_count + 1,
                        last_seen_at = CURRENT_TIMESTAMP
                    """,
                    (person_id, embedding, snapshot_path),
                )
                conn.commit()
            finally:
                conn.close()

    def get_pending_person_confirmations(self, status: str = "pending", limit: int = 50) -> list[dict[str, Any]]:
        """Unrecognized face-clusters waiting on a name, most recently seen
        first -- for the browser MEMORY tab's 'Unrecognized People' pane."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM pending_person_confirmations WHERE status = ? ORDER BY last_seen_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def resolve_pending_person_confirmation(
        self,
        confirmation_id: int,
        status: str,
        confirmed_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a pending person-confirmation row resolved. Returns the row
        AS IT WAS right before resolving (so the caller -- the WS handler
        confirming a name from the MEMORY tab -- can pull its embedding out
        to call add_known_person() with), or None if the id doesn't exist."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM pending_person_confirmations WHERE id = ?", (confirmation_id,)
                ).fetchone()
                if not row:
                    return None
                row_dict = dict(row)
                conn.execute(
                    "UPDATE pending_person_confirmations SET status = ?, confirmed_name = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, confirmed_name, confirmation_id),
                )
                conn.commit()
                return row_dict
            finally:
                conn.close()

    def resolve_pending_person_confirmation_by_person_id(
        self,
        person_id: str,
        status: str,
        confirmed_name: str | None = None,
    ) -> None:
        """Same as resolve_pending_person_confirmation but keyed by
        person_id (e.g. 'Person_2') rather than row id -- used by
        CoreAgent._check_person_introduction, which only knows the
        person_id InsightFace assigned this session, not the row id."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE pending_person_confirmations SET status = ?, confirmed_name = ?, resolved_at = CURRENT_TIMESTAMP WHERE person_id = ?",
                    (status, confirmed_name, person_id),
                )
                conn.commit()
            finally:
                conn.close()

    def upsert_conversation_pattern(
        self,
        pattern_type: str,
        label: str,
        example: str | None = None,
    ) -> int:
        """Record one occurrence of a recurring pattern (verbal filler,
        frustration trigger, etc.), or bump its count if already tracked."""
        with self._lock:
            conn = self._get_connection()
            try:
                existing = conn.execute(
                    "SELECT id FROM conversation_patterns WHERE pattern_type = ? AND label = ?",
                    (pattern_type, label),
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE conversation_patterns
                        SET occurrence_count = occurrence_count + 1,
                            last_seen = CURRENT_TIMESTAMP,
                            last_example = COALESCE(?, last_example)
                        WHERE id = ?
                        """,
                        (example, existing["id"]),
                    )
                    conn.commit()
                    return existing["id"]
                cursor = conn.execute(
                    """
                    INSERT INTO conversation_patterns (pattern_type, label, last_example)
                    VALUES (?, ?, ?)
                    """,
                    (pattern_type, label, example),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_conversation_patterns(self, pattern_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            if pattern_type:
                rows = conn.execute(
                    """
                    SELECT * FROM conversation_patterns WHERE pattern_type = ?
                    ORDER BY occurrence_count DESC, last_seen DESC LIMIT ?
                    """,
                    (pattern_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM conversation_patterns
                    ORDER BY occurrence_count DESC, last_seen DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # --- Tasks / Habits (2026-09-16) ---

    def add_task(self, title: str, due_date: str | None = None, source: str = "user") -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "INSERT INTO tasks (title, due_date, source) VALUES (?, ?, ?)",
                    (title, due_date, source),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_tasks(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM tasks WHERE status = ?
                    ORDER BY (due_date IS NULL), due_date ASC, created_at DESC LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM tasks
                    ORDER BY status ASC, (due_date IS NULL), due_date ASC, created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def complete_task(self, task_id: int) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE tasks SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (task_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_task(self, task_id: int) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()
            finally:
                conn.close()

    def add_habit(self, name: str, frequency: str = "daily") -> int:
        """Create a habit, or return the existing one's id if the name
        already exists (name is UNIQUE) -- adding "drink water" twice
        shouldn't spawn a duplicate tracker."""
        with self._lock:
            conn = self._get_connection()
            try:
                existing = conn.execute(
                    "SELECT id FROM habits WHERE name = ? COLLATE NOCASE", (name,)
                ).fetchone()
                if existing:
                    return existing["id"]
                cursor = conn.execute(
                    "INSERT INTO habits (name, frequency) VALUES (?, ?)",
                    (name, frequency),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_habits(self) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM habits ORDER BY streak_count DESC, name ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def complete_habit(self, name: str) -> dict[str, Any]:
        """Mark a habit done for the current period (day, for 'daily'
        habits). Streak logic: a gap of 0 days means it was already
        completed this period (no-op, streak unchanged); a gap within the
        habit's own frequency window continues the streak; a longer gap
        resets it to 1. Returns the updated row plus an 'already_done'
        flag so the UI can say "already logged today" instead of silently
        re-incrementing."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM habits WHERE name = ? COLLATE NOCASE", (name,)
                ).fetchone()
                if not row:
                    return {"error": f"No habit named '{name}'"}

                habit = dict(row)
                frequency_days = 7 if habit.get("frequency") == "weekly" else 1
                already_done = False

                if not habit["last_completed_at"]:
                    new_streak = 1
                else:
                    last_dt = conn.execute(
                        "SELECT julianday('now') - julianday(?) AS gap", (habit["last_completed_at"],)
                    ).fetchone()
                    gap_days = last_dt["gap"] if last_dt else 999
                    if gap_days < 1:
                        already_done = True
                        new_streak = habit["streak_count"]
                    elif gap_days <= frequency_days:
                        new_streak = habit["streak_count"] + 1
                    else:
                        new_streak = 1

                if not already_done:
                    conn.execute(
                        "UPDATE habits SET streak_count = ?, last_completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_streak, habit["id"]),
                    )
                    conn.commit()

                habit["streak_count"] = new_streak
                habit["already_done"] = already_done
                return habit
            finally:
                conn.close()

    def delete_habit(self, name: str) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM habits WHERE name = ? COLLATE NOCASE", (name,))
                conn.commit()
            finally:
                conn.close()

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