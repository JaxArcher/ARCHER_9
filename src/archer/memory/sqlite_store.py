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
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from archer.config import get_config


def format_room_transcript_timestamp(ts: float) -> str:
    """Format Unix timestamp as 'Tue Oct 14, 3:42 PM' (human readable, local time)."""
    dt = datetime.fromtimestamp(ts)
    day = str(dt.day)
    hour = str(int(dt.strftime("%I")))
    minute = dt.strftime("%M")
    ampm = dt.strftime("%p")
    return f"{dt.strftime('%a %b')} {day}, {hour}:{minute} {ampm}"


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

                -- Extra face references per known person (2026-10-06).
                -- known_persons holds exactly one embedding per name, and
                -- naming a face upserted over it -- so on 2026-09-19 naming
                -- "Person_2" as Col replaced Col's own enrollment with one
                -- poor early sighting, and after that Col matched from
                -- neither camera. The close-up webcam and the across-the-room
                -- Reolink see the same face very differently, so a person
                -- needs one reference per view. person_id.py matches against
                -- known_persons AND every row here.
                CREATE TABLE IF NOT EXISTS known_person_references (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    source TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_known_person_references_name
                    ON known_person_references(name);

                -- Person sightings (known & unrecognized repeat visitors)
                CREATE TABLE IF NOT EXISTS person_sightings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id TEXT NOT NULL,
                    is_known INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    embedding BLOB,
                    snapshot_path TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    camera_source TEXT NOT NULL DEFAULT 'webcam',
                    face_box TEXT,
                    faces_in_frame INTEGER DEFAULT 1
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

                -- Phase 3 Change Log
                CREATE TABLE IF NOT EXISTS change_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    what_changed TEXT NOT NULL,
                    prompted_by TEXT NOT NULL,
                    approval_status TEXT NOT NULL,
                    tool_name TEXT,
                    details TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_change_log_ts
                    ON change_log(timestamp);

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
                    total_duration_seconds REAL NOT NULL DEFAULT 0.0,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'confirmed' | 'dismissed'
                    confirmed_name TEXT,
                    resolved_at TIMESTAMP,
                    face_box TEXT
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

                -- High-water mark for strictly monotonic Person_N sequence numbers
                CREATE TABLE IF NOT EXISTS person_id_sequence (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    next_number INTEGER NOT NULL DEFAULT 1
                );

                -- Persistent key-value runtime state (e.g. checkin cooldown pauses)
                CREATE TABLE IF NOT EXISTS app_kv_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Stays record (Following people - Spec 5b, Review 19:30 Item 3)
                CREATE TABLE IF NOT EXISTS person_stays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stay_id TEXT NOT NULL UNIQUE,
                    person_id TEXT NOT NULL,
                    is_known INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    camera_source TEXT NOT NULL DEFAULT 'network_cam',
                    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    track_id INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_stays_person ON person_stays(person_id);
                CREATE INDEX IF NOT EXISTS idx_stays_stay_id ON person_stays(stay_id);
                CREATE INDEX IF NOT EXISTS idx_stays_started ON person_stays(started_at);
                CREATE INDEX IF NOT EXISTS idx_stays_ended ON person_stays(ended_at);

                -- --- PHASE 2C: ROOM TRANSCRIPTS & LISTENING (2026-10-15) ---
                CREATE TABLE IF NOT EXISTS room_transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    start_datetime TEXT NOT NULL,
                    end_datetime TEXT NOT NULL,
                    source TEXT NOT NULL,
                    people_in_view TEXT NOT NULL,
                    stay_id TEXT,
                    transcript TEXT NOT NULL,
                    is_archer INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_room_transcripts_start ON room_transcripts(start_time);
                CREATE INDEX IF NOT EXISTS idx_room_transcripts_end ON room_transcripts(end_time);
                CREATE INDEX IF NOT EXISTS idx_room_transcripts_stay ON room_transcripts(stay_id);
                CREATE INDEX IF NOT EXISTS idx_room_transcripts_archer ON room_transcripts(is_archer);

                -- FTS5 full-text search index for room transcripts
                CREATE VIRTUAL TABLE IF NOT EXISTS room_transcripts_fts USING fts5(
                    transcript,
                    people_in_view,
                    start_datetime,
                    content='room_transcripts',
                    content_rowid='id'
                );

                CREATE TRIGGER IF NOT EXISTS trg_room_transcripts_ai AFTER INSERT ON room_transcripts BEGIN
                    INSERT INTO room_transcripts_fts(rowid, transcript, people_in_view, start_datetime)
                    VALUES (new.id, new.transcript, new.people_in_view, new.start_datetime);
                END;

                CREATE TRIGGER IF NOT EXISTS trg_room_transcripts_ad AFTER DELETE ON room_transcripts BEGIN
                    INSERT INTO room_transcripts_fts(room_transcripts_fts, rowid, transcript, people_in_view, start_datetime)
                    VALUES ('delete', old.id, old.transcript, old.people_in_view, old.start_datetime);
                END;

                CREATE TRIGGER IF NOT EXISTS trg_room_transcripts_au AFTER UPDATE ON room_transcripts BEGIN
                    INSERT INTO room_transcripts_fts(room_transcripts_fts, rowid, transcript, people_in_view, start_datetime)
                    VALUES ('delete', old.id, old.transcript, old.people_in_view, old.start_datetime);
                    INSERT INTO room_transcripts_fts(rowid, transcript, people_in_view, start_datetime)
                    VALUES (new.id, new.transcript, new.people_in_view, new.start_datetime);
                END;

                -- Spoken output from ARCHER itself (for echo/self-transcription tagging)
                CREATE TABLE IF NOT EXISTS archer_speech_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at REAL NOT NULL,
                    ended_at REAL NOT NULL,
                    text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_archer_speech_log_started ON archer_speech_log(started_at);

                -- Persistent listening pause state (survives restarts)
                CREATE TABLE IF NOT EXISTS listening_control (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    paused_until REAL NOT NULL DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT OR IGNORE INTO listening_control (id, paused_until) VALUES (1, 0.0);

                -- Col's voice profile as heard through the room camera's mic
                -- (Phase 2c voice rule, Claude 2026-10-15). Separate from
                -- voice_enrollment (ARCHER's own desk-mic voice login).
                CREATE TABLE IF NOT EXISTS room_voice_profile (
                    name TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    samples INTEGER NOT NULL DEFAULT 0,
                    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Phase 3: Approval System Change Log (Spec Section 6)
                CREATE TABLE IF NOT EXISTS change_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    what_changed TEXT NOT NULL,
                    prompted_by TEXT NOT NULL,
                    approval_status TEXT NOT NULL,
                    tool_name TEXT,
                    details TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_change_log_timestamp ON change_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_change_log_status ON change_log(approval_status);

                -- Phase 4: Tool Pool Registry (Spec Section 7)
                CREATE TABLE IF NOT EXISTS tools_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    repo_url TEXT NOT NULL,
                    commit_hash TEXT NOT NULL,
                    install_folder TEXT NOT NULL,
                    env_path TEXT NOT NULL,
                    review_results TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_tools_registry_status ON tools_registry(status);
                CREATE INDEX IF NOT EXISTS idx_tools_registry_name ON tools_registry(name);
            """)
            try:
                conn.execute(
                    "ALTER TABLE pending_person_confirmations ADD COLUMN total_duration_seconds REAL NOT NULL DEFAULT 0.0"
                )
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE person_sightings ADD COLUMN face_box TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE pending_person_confirmations ADD COLUMN face_box TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE person_sightings ADD COLUMN faces_in_frame INTEGER DEFAULT 1")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE person_sightings ADD COLUMN stay_id TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE pending_person_confirmations ADD COLUMN stay_id TEXT")
            except Exception:
                pass
            # Phase 2c fixes (Claude 2026-10-15): whose voice each line is,
            # the observer's live listening state, the "forget that" window,
            # and "all systems go" launch requests -- all shared through this
            # database, since the observer service and ARCHER are separate
            # processes.
            for table, column, decl in (
                ("room_transcripts", "voice", "TEXT NOT NULL DEFAULT 'unchecked'"),
                ("room_transcripts", "voice_score", "REAL"),
                ("listening_control", "listener_state", "TEXT NOT NULL DEFAULT 'off'"),
                ("listening_control", "listener_heartbeat", "REAL NOT NULL DEFAULT 0.0"),
                ("listening_control", "forget_from", "REAL NOT NULL DEFAULT 0.0"),
                ("listening_control", "forget_until", "REAL NOT NULL DEFAULT 0.0"),
                ("listening_control", "launch_requested_at", "REAL NOT NULL DEFAULT 0.0"),
                ("listening_control", "launch_handled_at", "REAL NOT NULL DEFAULT 0.0"),
                ("listening_control", "audio_last_received_at", "REAL NOT NULL DEFAULT 0.0"),
                ("listening_control", "audio_stalled_seconds", "REAL NOT NULL DEFAULT 0.0"),
            ):
                existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            conn.commit()
            logger.info(f"SQLite store initialized at {self._db_path}")

            # Backfill any pending face durations from sightings on startup
            try:
                self.backfill_pending_durations_from_sightings()
            except Exception as e:
                logger.debug(f"Initial duration backfill skipped/failed (non-fatal): {e}")

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

    def add_known_person_reference(self, name: str, embedding: bytes, source: str | None = None) -> int:
        """Add an extra face reference for a known person without touching
        their primary enrollment (see known_person_references above)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "INSERT INTO known_person_references (name, embedding, source) VALUES (?, ?, ?)",
                    (name, embedding, source),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_known_person_references(self) -> list[dict[str, Any]]:
        """Every extra face reference, for person_id.py's matching."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM known_person_references ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def add_person_face(self, name: str, embedding: bytes, source: str | None = None) -> dict[str, Any]:
        """Name a face (2026-10-06). New name: becomes that person's primary
        record. Existing name: added as an extra reference instead of
        overwriting the one they already have -- the overwrite is what
        broke Col's recognition on 2026-09-19. Used by the "this is X"
        introduction path and Phase 2b conversational confirmations.
        Returns dict with action ('enrolled' or 'reference'), id, and name."""
        existing = {p["name"] for p in self.get_known_persons()}
        if name in existing:
            ref_id = self.add_known_person_reference(name, embedding, source)
            return {"action": "reference", "id": ref_id, "name": name}
        enrolled_id = self.add_known_person(name=name, embedding=embedding)
        return {"action": "enrolled", "id": enrolled_id, "name": name}

    def remove_known_person_reference(self, ref_id: int) -> None:
        """Remove a reference by id from known_person_references (Item 4)."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM known_person_references WHERE id = ?", (ref_id,))
                conn.commit()
            finally:
                conn.close()

    def remove_known_person(self, name: str) -> None:
        """Remove a person from known_persons and any associated extra references (Item 4)."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM known_persons WHERE name = ?", (name,))
                conn.execute("DELETE FROM known_person_references WHERE name = ?", (name,))
                conn.commit()
            finally:
                conn.close()

    def delete_contact(self, name: str) -> None:
        """Delete a contact by name from social_contacts (Item 4)."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute("SELECT id FROM social_contacts WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
                if row:
                    cid = row[0]
                    conn.execute("DELETE FROM social_interactions WHERE contact_id = ?", (cid,))
                    conn.execute("DELETE FROM social_commitments WHERE contact_id = ?", (cid,))
                    conn.execute("DELETE FROM social_contacts WHERE id = ?", (cid,))
                    conn.commit()
            finally:
                conn.close()

    def get_face_box_for_snapshot(self, snapshot_path: str) -> str | None:
        """Retrieve the exact bounding box saved with a specific snapshot photo (Item 5)."""
        if not snapshot_path:
            return None
        import os
        norm_path = os.path.normpath(snapshot_path)
        base_name = os.path.basename(snapshot_path)
        conn = self._get_connection()
        try:
            row = conn.execute(
                """
                SELECT face_box FROM person_sightings 
                WHERE (snapshot_path = ? OR snapshot_path = ? OR snapshot_path LIKE ?) 
                  AND face_box IS NOT NULL 
                ORDER BY id DESC LIMIT 1
                """,
                (snapshot_path, norm_path, f"%{base_name}"),
            ).fetchone()
            if row and row["face_box"]:
                return row["face_box"]
            return None
        finally:
            conn.close()

    def has_only_col_been_seen_recently(
        self,
        camera_source: str | None = None,
        within_seconds: float = 180.0,
        before_timestamp: float | None = None,
    ) -> bool:
        """
        Check if Col has been the ONLY face seen on camera_source for the last few minutes (Spec 5b / Item 6).
        Returns True if Col was seen within within_seconds on this camera, AND NO other person/face
        (unrecognized or other known person) was seen on this camera during that window.
        If camera_source has no recent sightings, falls back to checking across all cameras.
        """
        target_dt = (
            datetime.fromtimestamp(before_timestamp, tz=timezone.utc)
            if before_timestamp
            else datetime.now(timezone.utc)
        )
        cutoff_dt = target_dt - timedelta(seconds=within_seconds)

        conn = self._get_connection()
        try:
            # Query recent sightings
            if camera_source:
                rows = conn.execute(
                    """
                    SELECT id, person_id, is_known, timestamp, camera_source FROM person_sightings 
                    WHERE camera_source = ? 
                    ORDER BY id DESC LIMIT 500
                    """,
                    (camera_source,),
                ).fetchall()
            else:
                rows = []

            # If this camera has sightings, evaluate on this camera
            if rows:
                has_col = False
                for r in rows:
                    ts_str = str(r["timestamp"])[:19]
                    try:
                        s_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    except Exception:
                        continue
                    if s_dt < cutoff_dt:
                        break
                    pid = r["person_id"]
                    is_k = bool(r["is_known"])
                    if pid == "Col" and is_k:
                        has_col = True
                    else:
                        # Someone other than Col was seen on this camera
                        return False
                return has_col

            # Fallback: check across all cameras if this camera had no recent sightings
            all_rows = conn.execute(
                """
                SELECT id, person_id, is_known, timestamp FROM person_sightings 
                ORDER BY id DESC LIMIT 500
                """
            ).fetchall()
            if not all_rows:
                return False

            has_col = False
            for r in all_rows:
                ts_str = str(r["timestamp"])[:19]
                try:
                    s_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if s_dt < cutoff_dt:
                    break
                pid = r["person_id"]
                is_k = bool(r["is_known"])
                if pid == "Col" and is_k:
                    has_col = True
                else:
                    return False
            return has_col
        finally:
            conn.close()

    def count_sightings_for_person(self, person_id: str) -> int:
        """Count total sightings recorded for a person_id."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT count(*) as cnt FROM person_sightings WHERE person_id = ?",
                (person_id,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def count_context_references_today(self, person_name: str = "Col") -> int:
        """Count how many learned references were added for a person today (UTC day)."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                """
                SELECT count(*) as cnt FROM known_person_references
                WHERE name = ? AND source IN ('context_rule', 'sharp_crop')
                  AND date(added_at) = date('now')
                """,
                (person_name,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    count_learned_references_today = count_context_references_today

    def get_recent_known_sighting(
        self, person_id: str = "Col", within_seconds: float = 75.0, before_timestamp: float | None = None
    ) -> dict[str, Any] | None:
        """Check if person was recognized within within_seconds in person_sightings (Spec 5b / Item 6)."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                """
                SELECT * FROM person_sightings 
                WHERE person_id = ? AND is_known = 1 
                ORDER BY id DESC LIMIT 1
                """,
                (person_id,),
            ).fetchone()
            if not row:
                return None
            ts_str = str(row["timestamp"])[:19]
            try:
                last_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                target_dt = (
                    datetime.fromtimestamp(before_timestamp, tz=timezone.utc)
                    if before_timestamp
                    else datetime.now(timezone.utc)
                )
                diff = abs((target_dt - last_dt).total_seconds())
                if diff <= within_seconds:
                    return dict(row)
            except Exception as e:
                logger.debug(f"Error checking recent sighting timestamp: {e}")
            return None
        finally:
            conn.close()

    def get_recent_unrecognized_sighting(
        self, within_seconds: float = 75.0, before_timestamp: float | None = None, camera_source: str | None = None
    ) -> dict[str, Any] | None:
        """Check if an unrecognized single-person sighting occurred within within_seconds (Spec 5b retrospective link)."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM person_sightings WHERE is_known = 0 AND person_id LIKE 'Person_%' AND COALESCE(faces_in_frame, 1) = 1"
            params: list[Any] = []
            if camera_source:
                query += " AND camera_source = ?"
                params.append(camera_source)
            query += " ORDER BY id DESC LIMIT 1"
            row = conn.execute(query, tuple(params)).fetchone()
            if not row:
                return None
            ts_str = str(row["timestamp"])[:19]
            try:
                last_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                target_dt = (
                    datetime.fromtimestamp(before_timestamp, tz=timezone.utc)
                    if before_timestamp
                    else datetime.now(timezone.utc)
                )
                diff = abs((target_dt - last_dt).total_seconds())
                if diff <= within_seconds:
                    return dict(row)
            except Exception as e:
                logger.debug(f"Error checking recent unrecognized sighting timestamp: {e}")
            return None
        finally:
            conn.close()

    def reassign_sighting_to_col(self, sighting_id: int) -> None:
        """Update a past unrecognized sighting to Col (Spec 5b)."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE person_sightings SET person_id = 'Col', is_known = 1 WHERE id = ?",
                    (sighting_id,),
                )
                conn.commit()
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
        face_box: str | None = None,
        faces_in_frame: int = 1,
        stay_id: str | None = None,
    ) -> int:
        """Log a person sighting (known or unknown repeat visitor)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO person_sightings
                        (person_id, is_known, confidence, embedding, snapshot_path, camera_source, face_box, faces_in_frame, stay_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (person_id, 1 if is_known else 0, confidence, embedding, snapshot_path, camera_source, face_box, faces_in_frame, stay_id),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def backfill_stay_as_col(self, stay_id: str) -> int:
        """
        Backfill all sightings within a stay to Col once Col is recognized.
        Spec 5b (Following people): 'The first time ARCHER clearly recognizes a face,
        that person's whole stay in view counts as them, including the time before.
        Every face sighting is logged with the stay it belongs to.'
        """
        if not stay_id:
            return 0
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    UPDATE person_sightings
                    SET person_id = 'Col', is_known = 1
                    WHERE stay_id = ? AND person_id != 'Col'
                    """,
                    (stay_id,),
                )
                updated_count = cursor.rowcount

                # Also update person_stays record if present
                conn.execute(
                    """
                    UPDATE person_stays
                    SET person_id = 'Col', is_known = 1
                    WHERE stay_id = ?
                    """,
                    (stay_id,),
                )

                # Review 23:55 Item 2: Every label started during this stay is closed as Col,
                # as long as all of that label's sightings are in Col's stays.
                candidate_labels = conn.execute(
                    """
                    SELECT DISTINCT id, person_id FROM pending_person_confirmations
                    WHERE (stay_id = ? OR person_id IN (SELECT DISTINCT person_id FROM person_sightings WHERE stay_id = ?))
                      AND status = 'pending'
                    """,
                    (stay_id, stay_id),
                ).fetchall()

                for c_row in candidate_labels:
                    pid = c_row["person_id"]
                    # Check that all of this label's sightings are in Col's stays (including this stay)
                    other_sightings = conn.execute(
                        """
                        SELECT COUNT(*) as cnt FROM person_sightings ps
                        LEFT JOIN person_stays st ON ps.stay_id = st.stay_id
                        WHERE ps.person_id = ?
                          AND ps.stay_id != ?
                          AND (st.person_id IS NULL OR st.person_id != 'Col')
                        """,
                        (pid, stay_id),
                    ).fetchone()
                    if other_sightings is None or other_sightings["cnt"] == 0:
                        conn.execute(
                            """
                            UPDATE pending_person_confirmations
                            SET status = 'confirmed', confirmed_name = 'Col', resolved_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (c_row["id"],),
                        )
                        logger.info(f"SQLiteStore: Closed pending label {pid} as Col (all sightings in Col stays).")

                conn.commit()
                return updated_count
            finally:
                conn.close()

    def log_or_update_stay(
        self,
        stay_id: str,
        person_id: str,
        camera_source: str = "network_cam",
        started_at: str | None = None,
        ended_at: str | None = None,
        confidence: float = 0.0,
        is_known: bool = False,
        track_id: int | None = None,
    ) -> int:
        """
        Record or update an ongoing visit / stay in view.
        Spec 5b (Review 19:30 Item 3):
        'Add a stays record: who, which camera, when it started, when it ended (updated while it continues),
        and how sure ARCHER is of the identity. Keep it on the same retention as sightings.'
        """
        if not stay_id:
            return 0
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT id, person_id, is_known, confidence FROM person_stays WHERE stay_id = ?",
                    (stay_id,),
                ).fetchone()
                if row is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO person_stays (stay_id, person_id, is_known, confidence, camera_source, started_at, ended_at, track_id)
                        VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP), ?)
                        """,
                        (stay_id, person_id, 1 if is_known else 0, confidence, camera_source, started_at, ended_at, track_id),
                    )
                    conn.commit()
                    return cursor.lastrowid
                else:
                    cur_person = row["person_id"]
                    new_person = person_id if (person_id and (cur_person != "Col" or person_id == "Col")) else cur_person
                    new_is_known = 1 if (is_known or row["is_known"]) else 0
                    new_conf = max(confidence, float(row["confidence"]))
                    conn.execute(
                        """
                        UPDATE person_stays
                        SET ended_at = COALESCE(?, CURRENT_TIMESTAMP),
                            person_id = ?,
                            is_known = ?,
                            confidence = ?,
                            track_id = COALESCE(?, track_id)
                        WHERE stay_id = ?
                        """,
                        (ended_at, new_person, new_is_known, new_conf, track_id, stay_id),
                    )
                    conn.commit()
                    return row["id"]
            finally:
                conn.close()

    def get_stay(self, stay_id: str) -> dict[str, Any] | None:
        """Get stay record by stay_id."""
        if not stay_id:
            return None
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM person_stays WHERE stay_id = ?", (stay_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_recent_stays(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent stays ordered by started_at DESC."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM person_stays ORDER BY started_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def split_stay(
        self,
        old_stay_id: str,
        new_stay_id: str,
        new_person_id: str,
        split_time: str | None = None,
        camera_source: str = "network_cam",
        confidence: float = 0.0,
        is_known: bool = False,
        track_id: int | None = None,
    ) -> None:
        """
        Split a stay when a re-check discovers a track now belongs to someone else.
        Review 19:30 Item 2: 'If a clear face says it's someone else, split the stay at that point.'
        """
        if not old_stay_id or not new_stay_id:
            return
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE person_stays SET ended_at = COALESCE(?, CURRENT_TIMESTAMP) WHERE stay_id = ?",
                    (split_time, old_stay_id),
                )
                conn.execute(
                    """
                    INSERT INTO person_stays (stay_id, person_id, is_known, confidence, camera_source, started_at, ended_at, track_id)
                    VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP), ?)
                    """,
                    (new_stay_id, new_person_id, 1 if is_known else 0, confidence, camera_source, split_time, split_time, track_id),
                )
                conn.commit()
            finally:
                conn.close()

    def get_stay_sightings(self, stay_id: str) -> list[dict[str, Any]]:
        """Get all person sightings belonging to a specific stay."""
        if not stay_id:
            return []
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM person_sightings WHERE stay_id = ? ORDER BY id ASC",
                (stay_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
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

    def get_latest_sighting_for_person(self, person_id: str) -> dict[str, Any] | None:
        """Get the most recent sighting record for a given person_id."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM person_sightings WHERE person_id = ? ORDER BY id DESC LIMIT 1",
                (person_id,),
            ).fetchone()
            return dict(row) if row else None
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

    def get_recent_actions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent actions from action_audit."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM action_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    get_action_audit = get_recent_actions

    # --- Phase 3: Change Log ---

    def add_change_log(
        self,
        what_changed: str,
        prompted_by: str,
        approval_status: str,
        tool_name: str | None = None,
        details: str | None = None,
    ) -> int:
        """Add an entry to the Phase 3 change log."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO change_log
                        (what_changed, prompted_by, approval_status, tool_name, details)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (what_changed, prompted_by, approval_status, tool_name, details),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_change_logs(
        self,
        limit: int = 100,
        date_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent change log entries, newest first, optional date filter (YYYY-MM-DD)."""
        conn = self._get_connection()
        try:
            if date_filter:
                cursor = conn.execute(
                    "SELECT * FROM change_log WHERE date(timestamp) = date(?) ORDER BY id DESC LIMIT ?",
                    (date_filter, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM change_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
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
        sighting_timestamp: float | None = None,
        face_box: str | None = None,
        stay_id: str | None = None,
        status: str = "pending",
    ) -> None:
        """Record/bump an unrecognized face-cluster as waiting on a name.

        No-op once that person_id has already been resolved (confirmed or
        dismissed) unless updating with an explicit status like 'decor'.
        """
        now_ts = sighting_timestamp if sighting_timestamp is not None else time.time()
        now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S.%f")
        with self._lock:
            conn = self._get_connection()
            try:
                # Update monotonic sequence high-water mark if person_id is Person_N
                if person_id and str(person_id).startswith("Person_"):
                    try:
                        p_num = int(str(person_id).split("_")[1])
                        conn.execute(
                            """
                            INSERT INTO person_id_sequence (id, next_number) VALUES (1, ?)
                            ON CONFLICT(id) DO UPDATE SET next_number = MAX(next_number, excluded.next_number)
                            """,
                            (p_num + 1,),
                        )
                    except (ValueError, IndexError):
                        pass

                existing = conn.execute(
                    "SELECT id, status, last_seen_at, total_duration_seconds, face_box FROM pending_person_confirmations WHERE person_id = ?",
                    (person_id,),
                ).fetchone()
                if existing and existing["status"] != "pending" and status == "pending":
                    return

                if existing:
                    delta = 0.0
                    last_seen_str = existing["last_seen_at"]
                    if last_seen_str:
                        try:
                            last_dt = datetime.fromisoformat(str(last_seen_str))
                            if last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            diff = (now_dt - last_dt).total_seconds()
                            if 0.0 < diff <= 75.0:
                                delta = diff
                        except Exception:
                            try:
                                last_dt = datetime.strptime(str(last_seen_str)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                                diff = (now_dt - last_dt).total_seconds()
                                if 0.0 < diff <= 75.0:
                                    delta = diff
                            except Exception as e:
                                logger.debug(f"Error computing sighting duration delta: {e}")

                    curr_duration = float(existing["total_duration_seconds"] or 0.0) + delta
                    # Item 5: face_box must match the stored photo's own sighting, not later frames
                    box_to_save = face_box if snapshot_path else (existing["face_box"] or face_box)
                    target_status = status if status != "pending" else existing["status"]
                    conn.execute(
                        """
                        UPDATE pending_person_confirmations SET
                            embedding = ?,
                            snapshot_path = COALESCE(?, snapshot_path),
                            sighting_count = sighting_count + 1,
                            total_duration_seconds = ?,
                            last_seen_at = ?,
                            face_box = ?,
                            stay_id = COALESCE(stay_id, ?),
                            status = ?
                        WHERE id = ?
                        """,
                        (embedding, snapshot_path, curr_duration, now_iso, box_to_save, stay_id, target_status, existing["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO pending_person_confirmations
                            (person_id, embedding, snapshot_path, sighting_count, total_duration_seconds, first_seen_at, last_seen_at, face_box, stay_id, status)
                        VALUES (?, ?, ?, 1, 0.0, ?, ?, ?, ?, ?)
                        """,
                        (person_id, embedding, snapshot_path, now_iso, now_iso, face_box, stay_id, status),
                    )
                conn.commit()
            finally:
                conn.close()

    def get_next_person_number(self) -> int:
        """Return the next monotonic integer index N for Person_N, ensuring
        numbers are strictly incremented and never reused across sightings or
        confirmations, even when records are forgotten/deleted."""
        with self._lock:
            conn = self._get_connection()
            try:
                c1 = conn.execute(
                    "SELECT person_id FROM pending_person_confirmations WHERE person_id LIKE 'Person_%'"
                ).fetchall()
                c2 = conn.execute(
                    "SELECT person_id FROM person_sightings WHERE person_id LIKE 'Person_%'"
                ).fetchall()
                max_num = 0
                for row in list(c1) + list(c2):
                    pid = row["person_id"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
                    if pid and str(pid).startswith("Person_"):
                        try:
                            num = int(str(pid).split("_")[1])
                            if num > max_num:
                                max_num = num
                        except (ValueError, IndexError):
                            pass

                seq_val = 1
                try:
                    s_row = conn.execute("SELECT next_number FROM person_id_sequence WHERE id = 1").fetchone()
                    if s_row:
                        seq_val = int(s_row[0] if isinstance(s_row, (tuple, list)) else s_row["next_number"])
                except Exception:
                    pass

                next_num = max(seq_val, max_num + 1)
                try:
                    conn.execute(
                        """
                        INSERT INTO person_id_sequence (id, next_number) VALUES (1, ?)
                        ON CONFLICT(id) DO UPDATE SET next_number = MAX(next_number, excluded.next_number)
                        """,
                        (next_num,),
                    )
                    conn.commit()
                except Exception:
                    pass
                return next_num
            finally:
                conn.close()

    def forget_pending_person(self, confirmation_id: int) -> dict[str, Any] | None:
        """Delete a pending person confirmation, their sightings, all photo files
        on disk across all sightings of that person, and return the record dict."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM pending_person_confirmations WHERE id = ?", (confirmation_id,)
                ).fetchone()
                if not row:
                    return None
                row_dict = dict(row)
                person_id = row_dict["person_id"]

                paths_to_delete = set()
                if row_dict.get("snapshot_path"):
                    paths_to_delete.add(row_dict["snapshot_path"])

                s_rows = conn.execute(
                    "SELECT snapshot_path FROM person_sightings WHERE person_id = ? AND snapshot_path IS NOT NULL",
                    (person_id,),
                ).fetchall()
                for sr in s_rows:
                    p = sr[0] if isinstance(sr, (tuple, list)) else sr["snapshot_path"]
                    if p:
                        paths_to_delete.add(p)

                conn.execute("DELETE FROM pending_person_confirmations WHERE id = ?", (confirmation_id,))
                conn.execute("DELETE FROM person_sightings WHERE person_id = ?", (person_id,))
                conn.commit()

                for path_str in paths_to_delete:
                    try:
                        p_file = Path(path_str)
                        if p_file.exists():
                            p_file.unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning(f"Failed to delete photo {path_str}: {e}")

                return row_dict
            finally:
                conn.close()

    def forget_pending_person_by_person_id(self, person_id: str) -> dict[str, Any] | None:
        """Same as forget_pending_person but keyed by person_id (e.g. 'Person_2')."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM pending_person_confirmations WHERE person_id = ?", (person_id,)
                ).fetchone()
                row_dict = dict(row) if row else {"person_id": person_id}

                paths_to_delete = set()
                if row and row_dict.get("snapshot_path"):
                    paths_to_delete.add(row_dict["snapshot_path"])

                s_rows = conn.execute(
                    "SELECT snapshot_path FROM person_sightings WHERE person_id = ? AND snapshot_path IS NOT NULL",
                    (person_id,),
                ).fetchall()
                for sr in s_rows:
                    p = sr[0] if isinstance(sr, (tuple, list)) else sr["snapshot_path"]
                    if p:
                        paths_to_delete.add(p)

                conn.execute("DELETE FROM pending_person_confirmations WHERE person_id = ?", (person_id,))
                conn.execute("DELETE FROM person_sightings WHERE person_id = ?", (person_id,))
                conn.commit()

                for path_str in paths_to_delete:
                    try:
                        p_file = Path(path_str)
                        if p_file.exists():
                            p_file.unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning(f"Failed to delete photo {path_str}: {e}")

                return row_dict
            finally:
                conn.close()

    def get_pending_person_confirmations(
        self,
        status: str | list[str] | tuple[str, ...] | None = "pending",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Unrecognized face-clusters waiting on a name, most recently seen
        first -- for the browser MEMORY tab's 'Unrecognized People' pane.
        Supports filtering by a single status, multiple statuses, or None."""
        conn = self._get_connection()
        try:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM pending_person_confirmations ORDER BY last_seen_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            elif isinstance(status, (list, tuple, set)):
                placeholders = ",".join("?" for _ in status)
                rows = conn.execute(
                    f"SELECT * FROM pending_person_confirmations WHERE status IN ({placeholders}) ORDER BY last_seen_at DESC LIMIT ?",
                    (*list(status), limit),
                ).fetchall()
            else:
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

    def get_decor_embeddings(self) -> list[bytes]:
        """Fetch all face embeddings of entities marked as decor / not a person (Spec 5b & Review Addendum)."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT embedding FROM pending_person_confirmations WHERE status = 'decor' AND embedding IS NOT NULL"
                ).fetchall()
                return [r["embedding"] for r in rows if r["embedding"]]
            finally:
                conn.close()

    def get_recent_person_sightings(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the most recent person sightings."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT * FROM person_sightings ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()


    def backfill_pending_durations_from_sightings(self, continuous_threshold: float = 75.0) -> None:
        """Backfill total_duration_seconds on pending_person_confirmations from
        historical person_sightings timestamps for any rows where total_duration_seconds is 0.0 or low."""
        with self._lock:
            conn = self._get_connection()
            try:
                pending_rows = conn.execute(
                    "SELECT id, person_id, total_duration_seconds FROM pending_person_confirmations WHERE status = 'pending'"
                ).fetchall()
                for row in pending_rows:
                    pid = row["person_id"]
                    sightings = conn.execute(
                        "SELECT timestamp FROM person_sightings WHERE person_id = ? ORDER BY timestamp ASC",
                        (pid,),
                    ).fetchall()
                    if len(sightings) < 2:
                        continue
                    calc_duration = 0.0
                    prev_dt = None
                    for s in sightings:
                        ts_val = s[0] if isinstance(s, (tuple, list)) else s["timestamp"]
                        ts_str = str(ts_val)
                        try:
                            cur_dt = datetime.fromisoformat(ts_str)
                            if cur_dt.tzinfo is None:
                                cur_dt = cur_dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            try:
                                cur_dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                            except Exception:
                                continue
                        if prev_dt is not None:
                            diff = (cur_dt - prev_dt).total_seconds()
                            if 0.0 < diff <= continuous_threshold:
                                calc_duration += diff
                        prev_dt = cur_dt

                    curr_dur = float(row["total_duration_seconds"] or 0.0)
                    if calc_duration > curr_dur:
                        conn.execute(
                            "UPDATE pending_person_confirmations SET total_duration_seconds = ? WHERE id = ?",
                            (calc_duration, row["id"]),
                        )
                conn.commit()
            finally:
                conn.close()

    def update_pending_confirmation_duration(self, person_id: str, duration: float) -> None:
        """Update total_duration_seconds for a pending confirmation row from its tracked stay duration."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE pending_person_confirmations SET total_duration_seconds = MAX(total_duration_seconds, ?) WHERE person_id = ?",
                    (float(duration), person_id),
                )
                conn.commit()
            finally:
                conn.close()


    def count_snapshots_for_person(self, person_id: str) -> int:
        """Count how many sightings of this person have snapshot photos on disk."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM person_sightings WHERE person_id = ? AND snapshot_path IS NOT NULL",
                    (person_id,),
                ).fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()

    def set_kv_state(self, key: str, value: str) -> None:
        """Set a persistent key-value configuration or runtime state string."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO app_kv_state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, value),
                )
                conn.commit()
            finally:
                conn.close()

    def get_kv_state(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a persistent key-value configuration or runtime state string."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute("SELECT value FROM app_kv_state WHERE key = ?", (key,)).fetchone()
                if row:
                    return str(row[0] if isinstance(row, (tuple, list)) else row["value"])
                return default
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




    # =========================================================================
    # Phase 2c: Room Transcripts & Listening Control
    # (Antigravity 2026-10-15; reworked by Claude 2026-10-15 after review)
    # =========================================================================

    _ROOM_TRANSCRIPT_COLUMNS = (
        "id, start_time, end_time, start_datetime, end_datetime, source, "
        "people_in_view, stay_id, transcript, is_archer, voice, voice_score"
    )

    @staticmethod
    def _room_transcript_row_to_dict(row: Any) -> dict:
        try:
            piv = json.loads(row[6])
            if not isinstance(piv, list):
                piv = [piv]
        except Exception:
            piv = [row[6]] if row[6] else []
        return {
            "id": row[0],
            "start_time": row[1],
            "end_time": row[2],
            "start_datetime": row[3],
            "formatted_time": row[3],
            "end_datetime": row[4],
            "source": row[5],
            "people_in_view": piv,
            "stay_id": row[7],
            "transcript": row[8],
            "text": row[8],
            "is_archer": bool(row[9]),
            "voice": row[10],
            "voice_score": row[11],
        }

    def insert_room_transcript(
        self,
        text: str = "",
        start_time: float = 0.0,
        end_time: float = 0.0,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
        source: str = "room_cam",
        people_in_view: list[str] | str | None = None,
        stay_id: str | None = None,
        transcript: str = "",
        is_archer: bool = False,
        voice: str = "unchecked",
        voice_score: float | None = None,
        **kwargs,
    ) -> int:
        """Insert a transcribed line from room listening. Returns the row id, or -1."""
        actual_text = (transcript or text or kwargs.get("transcript") or kwargs.get("text") or "").strip()
        piv = people_in_view if people_in_view is not None else kwargs.get("persons_in_view", [])
        people_str = json.dumps(piv) if isinstance(piv, list) else json.dumps([str(piv)])

        if not start_datetime:
            start_datetime = format_room_transcript_timestamp(start_time)
        if not end_datetime:
            end_datetime = format_room_transcript_timestamp(end_time)

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO room_transcripts (
                        start_time, end_time, start_datetime, end_datetime,
                        source, people_in_view, stay_id, transcript, is_archer,
                        voice, voice_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        float(start_time),
                        float(end_time),
                        start_datetime,
                        end_datetime,
                        source,
                        people_str,
                        stay_id,
                        actual_text,
                        1 if is_archer else 0,
                        voice,
                        None if voice_score is None else float(voice_score),
                    ),
                )
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to insert room transcript: {e}")
            return -1
        finally:
            conn.close()

    def search_room_transcripts(
        self,
        query: str,
        limit: int = 5,
        since_timestamp: float | None = None,
        include_archer: bool = False,
        until_timestamp: float | None = None,
    ) -> list[dict]:
        """Search room transcripts by words (FTS5, falling back to LIKE)."""
        cleaned_query = re.sub(r"[^a-zA-Z0-9\s]", " ", query or "").strip()
        if not cleaned_query:
            return []

        terms = [t for t in cleaned_query.split() if len(t) > 2] or cleaned_query.split()
        fts_expr = " OR ".join(f'"{t}"' for t in terms)

        filters = ""
        params: list[Any] = []
        if not include_archer:
            filters += " AND t.is_archer = 0"
        if since_timestamp is not None:
            filters += " AND t.start_time >= ?"
            params.append(float(since_timestamp))
        if until_timestamp is not None:
            filters += " AND t.start_time < ?"
            params.append(float(until_timestamp))

        conn = self._get_connection()
        try:
            try:
                cursor = conn.execute(
                    f"""
                    SELECT t.id, t.start_time, t.end_time, t.start_datetime, t.end_datetime,
                           t.source, t.people_in_view, t.stay_id, t.transcript, t.is_archer,
                           t.voice, t.voice_score
                    FROM room_transcripts t
                    JOIN room_transcripts_fts fts ON t.id = fts.rowid
                    WHERE room_transcripts_fts MATCH ? {filters}
                    ORDER BY bm25(room_transcripts_fts) LIMIT ?
                    """,
                    tuple([fts_expr] + params + [int(limit)]),
                )
                return [self._room_transcript_row_to_dict(r) for r in cursor.fetchall()]
            except Exception as e:
                logger.debug(f"FTS search failed, falling back to LIKE: {e}")
                like_terms = " OR ".join("t.transcript LIKE ?" for _ in terms)
                cursor = conn.execute(
                    f"""
                    SELECT {", ".join("t." + c.strip() for c in self._ROOM_TRANSCRIPT_COLUMNS.split(","))}
                    FROM room_transcripts t
                    WHERE ({like_terms}) {filters}
                    ORDER BY t.start_time DESC LIMIT ?
                    """,
                    tuple([f"%{t}%" for t in terms] + params + [int(limit)]),
                )
                return [self._room_transcript_row_to_dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Room transcript search failed: {e}")
            return []
        finally:
            conn.close()

    def get_recent_room_transcripts(
        self,
        limit: int = 20,
        include_archer: bool = True,
    ) -> list[dict]:
        """Fetch recent room transcripts, newest first."""
        conn = self._get_connection()
        try:
            sql = f"SELECT {self._ROOM_TRANSCRIPT_COLUMNS} FROM room_transcripts"
            if not include_archer:
                sql += " WHERE is_archer = 0"
            sql += " ORDER BY start_time DESC LIMIT ?"
            cursor = conn.execute(sql, (int(limit),))
            return [self._room_transcript_row_to_dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to fetch recent room transcripts: {e}")
            return []
        finally:
            conn.close()

    def get_room_transcripts_range(
        self,
        start_time: float,
        end_time: float,
        include_archer: bool = False,
    ) -> list[dict]:
        """Fetch room transcripts that started within [start_time, end_time], oldest first."""
        conn = self._get_connection()
        try:
            sql = (
                f"SELECT {self._ROOM_TRANSCRIPT_COLUMNS} FROM room_transcripts "
                "WHERE start_time >= ? AND start_time <= ?"
            )
            if not include_archer:
                sql += " AND is_archer = 0"
            sql += " ORDER BY start_time ASC"
            cursor = conn.execute(sql, (float(start_time), float(end_time)))
            return [self._room_transcript_row_to_dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to fetch room transcripts range: {e}")
            return []
        finally:
            conn.close()

    # --- ARCHER's own speech (so the room listener can mark it) ---

    def log_archer_speech(self, started_at: float, ended_at: float, text: str) -> int:
        """Record when ARCHER spoke and what it said."""
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO archer_speech_log (started_at, ended_at, text) VALUES (?, ?, ?)",
                    (float(started_at), float(ended_at), (text or "").strip()),
                )
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to log ARCHER speech: {e}")
            return -1
        finally:
            conn.close()

    # Common words don't count when deciding whether a line repeats ARCHER.
    _COMMON_WORDS = frozenset(
        "the and you your for are was were with that this have has had not but "
        "what when where which who how why can will would could should there "
        "their they them then than its it's from just about into out our all "
        "any get got let lets yes yeah okay one two now here some more very "
        "been being did does doing say said see".split()
    )

    @classmethod
    def _content_words(cls, text: str) -> set[str]:
        return {
            w for w in re.findall(r"[a-z']{3,}", (text or "").lower())
            if w not in cls._COMMON_WORDS
        }

    def check_if_archer_speech(
        self,
        start_time: float,
        end_time: float,
        text: str,
        lag_seconds: float = 1.18,
    ) -> bool:
        """
        True when a room line is ARCHER's own voice: it overlaps a stretch of
        ARCHER's speech in time (after removing the camera's audio delay, with
        1.5 s slack) AND repeats its words (ignoring common words). A line that
        only overlaps in time is Col talking over ARCHER, and stays his.
        """
        line_words = self._content_words(text)
        if not line_words:
            return False
        adj_start = start_time - lag_seconds
        adj_end = end_time - lag_seconds

        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT text FROM archer_speech_log
                WHERE started_at <= ? AND ended_at >= ?
                ORDER BY id DESC LIMIT 10
                """,
                (adj_end + 1.5, adj_start - 1.5),
            ).fetchall()
        except Exception as e:
            logger.error(f"Error checking ARCHER speech: {e}")
            return False
        finally:
            conn.close()

        spoken_words: set[str] = set()
        for (spoken,) in rows:
            spoken_words |= self._content_words(spoken)
        if not spoken_words:
            return False
        overlap = len(line_words & spoken_words)
        return overlap >= 4 or overlap / len(line_words) >= 0.5

    # --- Listening control (pause, live state, "forget that", launch) ---

    def _listening_row(self) -> dict:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM listening_control WHERE id = 1").fetchone()
            return dict(row) if row else {}
        except Exception:
            return {}
        finally:
            conn.close()

    def _update_listening(self, **values: Any) -> None:
        if not values:
            return
        sets = ", ".join(f"{k} = ?" for k in values)
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("INSERT OR IGNORE INTO listening_control (id, paused_until) VALUES (1, 0.0)")
                conn.execute(
                    f"UPDATE listening_control SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                    tuple(values.values()),
                )
        except Exception as e:
            logger.error(f"Failed to update listening control: {e}")
        finally:
            conn.close()

    def set_listening_pause(
        self,
        paused_until: float | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        """
        Pause room listening.
        paused_until: 0.0 = listening, -1.0 = paused until resumed, >0 = paused until that time.
        duration_seconds: >0 = pause for that long, -1 = until resumed, 0 = resume.
        """
        if duration_seconds is not None:
            if duration_seconds == -1:
                target = -1.0
            elif duration_seconds <= 0:
                target = 0.0
            else:
                target = time.time() + float(duration_seconds)
        elif paused_until is not None:
            target = float(paused_until)
        else:
            target = 0.0
        self._update_listening(paused_until=target)

    def get_listening_pause(self) -> float:
        """The paused_until value (0.0 when not paused, -1.0 until resumed)."""
        try:
            return float(self._listening_row().get("paused_until", 0.0) or 0.0)
        except Exception:
            return 0.0

    def is_listening_paused(self, now: float | None = None) -> bool:
        curr = now if now is not None else time.time()
        p = self.get_listening_pause()
        return p == -1.0 or p > curr

    def set_listener_state(self, state: str, now: float | None = None) -> None:
        """The observer's room listener reports what it's doing (listening / paused / empty)."""
        self._update_listening(
            listener_state=state,
            listener_heartbeat=float(now if now is not None else time.time()),
        )

    def update_audio_received(self, now: float | None = None) -> None:
        """Record audio frame received and clear stall timer."""
        curr = float(now if now is not None else time.time())
        self._update_listening(audio_last_received_at=curr, audio_stalled_seconds=0.0)

    def update_audio_stalled(self, stalled_seconds: float, now: float | None = None) -> None:
        """Record audio stall duration in seconds."""
        self._update_listening(audio_stalled_seconds=float(stalled_seconds))

    def get_listening_status(self, now: float | None = None, stale_after: float = 45.0) -> dict:
        """
        What the page shows: state is 'paused', 'listening', 'empty' or 'off'
        (the observer isn't reporting), with 'until' for a timed pause
        (0 = no timed pause, -1 = until resumed).
        """
        curr = now if now is not None else time.time()
        row = self._listening_row()
        paused_until = float(row.get("paused_until", 0.0) or 0.0)
        if paused_until == -1.0 or paused_until > curr:
            return {"state": "paused", "until": paused_until}
        heartbeat = float(row.get("listener_heartbeat", 0.0) or 0.0)
        if curr - heartbeat > stale_after:
            return {"state": "off", "until": 0.0}
        state = row.get("listener_state") or "off"
        if state not in ("listening", "empty"):
            state = "listening" if state == "paused" else "off"
        return {"state": state, "until": 0.0}

    def forget_recent_room_transcripts(self, seconds: float = 120.0, now: float | None = None) -> int:
        """
        "Forget that": delete every line from the last `seconds` (default 2
        minutes) up to `now`, and remember that window, so a line from it that
        the observer is still transcribing is never saved. Returns rows deleted.
        """
        curr = now if now is not None else time.time()
        cutoff = curr - float(seconds)
        deleted = 0
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM room_transcripts WHERE end_time >= ? AND start_time <= ?",
                    (cutoff, curr),
                )
                deleted = cursor.rowcount
        except Exception as e:
            logger.error(f"Failed to forget recent room transcripts: {e}")
        finally:
            conn.close()
        row = self._listening_row()
        prev_from = float(row.get("forget_from", 0.0) or 0.0)
        prev_until = float(row.get("forget_until", 0.0) or 0.0)
        # Merge with an earlier window that touches this one.
        new_from = min(prev_from, cutoff) if prev_until >= cutoff and prev_from > 0 else cutoff
        self._update_listening(forget_from=new_from, forget_until=max(prev_until, curr))
        logger.info(f"Forget that: {deleted} room transcript lines deleted")
        return deleted

    def is_in_forgotten_window(self, start_time: float, end_time: float) -> bool:
        """True when a line overlaps the most recent "forget that" window."""
        row = self._listening_row()
        f_from = float(row.get("forget_from", 0.0) or 0.0)
        f_until = float(row.get("forget_until", 0.0) or 0.0)
        if f_until <= 0.0:
            return False
        return end_time >= f_from and start_time <= f_until

    def request_launch(self, now: float | None = None) -> None:
        """'All systems go' was heard: the launch task picks this up (scripts/launch_check.py)."""
        self._update_listening(launch_requested_at=float(now if now is not None else time.time()))

    # --- Col's voice profile through the room camera's mic ---

    def save_room_voice_profile(self, embedding: list[float], samples: int, name: str = "Col") -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO room_voice_profile (name, embedding, samples, enrolled_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(name) DO UPDATE SET
                        embedding = excluded.embedding,
                        samples = excluded.samples,
                        enrolled_at = CURRENT_TIMESTAMP
                    """,
                    (name, json.dumps([float(x) for x in embedding]), int(samples)),
                )
        finally:
            conn.close()

    def get_room_voice_profile(self, name: str = "Col") -> list[float] | None:
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT embedding FROM room_voice_profile WHERE name = ?", (name,)
            ).fetchone()
            return json.loads(row[0]) if row else None
        except Exception:
            return None
        finally:
            conn.close()

    # --- Phase 3: Change Log ---

    def add_change_log(
        self,
        what_changed: str,
        prompted_by: str,
        approval_status: str,
        tool_name: str = "",
        details: str = "",
    ) -> int:
        """Insert a row into change_log table."""
        conn = self._get_connection()
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO change_log (what_changed, prompted_by, approval_status, tool_name, details)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (what_changed, prompted_by, approval_status, tool_name, details),
                )
                return cur.lastrowid
        finally:
            conn.close()

    def get_change_logs(
        self, limit: int = 100, date_filter: str | None = None
    ) -> list[dict]:
        """Fetch change_log rows, optionally filtered by date (YYYY-MM-DD)."""
        conn = self._get_connection()
        try:
            if date_filter:
                rows = conn.execute(
                    """
                    SELECT id, timestamp, what_changed, prompted_by, approval_status, tool_name, details
                    FROM change_log
                    WHERE date(timestamp, 'localtime') = date(?) OR date(timestamp) = date(?)
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (date_filter, date_filter, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, timestamp, what_changed, prompted_by, approval_status, tool_name, details
                    FROM change_log
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

            return [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "what_changed": r[2],
                    "prompted_by": r[3],
                    "approval_status": r[4],
                    "tool_name": r[5],
                    "details": r[6],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # --- Phase 4 Tool Pool Registry (Spec Section 7) ---

    def register_tool_candidate(
        self,
        name: str,
        repo_url: str,
        commit_hash: str,
        install_folder: str = "",
        env_path: str = "",
        review_results: str = "{}",
        status: str = "proposed",
        reason: str = "",
    ) -> int:
        """Register a new candidate tool in tools_registry."""
        conn = self._get_connection()
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO tools_registry
                    (name, repo_url, commit_hash, install_folder, env_path, review_results, status, reason, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                    ON CONFLICT(name) DO UPDATE SET
                    repo_url=excluded.repo_url,
                    commit_hash=excluded.commit_hash,
                    install_folder=excluded.install_folder,
                    env_path=excluded.env_path,
                    review_results=excluded.review_results,
                    status=excluded.status,
                    reason=excluded.reason,
                    updated_at=datetime('now')
                    """,
                    (name, repo_url, commit_hash, install_folder, env_path, review_results, status, reason),
                )
                return cur.lastrowid
        finally:
            conn.close()

    def update_tool_candidate(
        self,
        tool_id_or_name: int | str,
        status: str,
        reason: str | None = None,
        review_results: str | None = None,
        install_folder: str | None = None,
        env_path: str | None = None,
    ) -> bool:
        """Update tool status and details in tools_registry."""
        conn = self._get_connection()
        try:
            with conn:
                updates = ["status = ?", "updated_at = datetime('now')"]
                params: list[Any] = [status]
                if reason is not None:
                    updates.append("reason = ?")
                    params.append(reason)
                if review_results is not None:
                    updates.append("review_results = ?")
                    params.append(review_results)
                if install_folder is not None:
                    updates.append("install_folder = ?")
                    params.append(install_folder)
                if env_path is not None:
                    updates.append("env_path = ?")
                    params.append(env_path)

                if isinstance(tool_id_or_name, int) or (isinstance(tool_id_or_name, str) and tool_id_or_name.isdigit()):
                    where = "id = ?"
                    params.append(int(tool_id_or_name))
                else:
                    where = "name = ?"
                    params.append(str(tool_id_or_name))

                cur = conn.execute(
                    f"UPDATE tools_registry SET {', '.join(updates)} WHERE {where}",
                    tuple(params),
                )
                return cur.rowcount > 0
        finally:
            conn.close()

    def get_tool_candidate(self, tool_id_or_name: int | str) -> dict | None:
        """Fetch a single tool from tools_registry by ID or name."""
        conn = self._get_connection()
        try:
            if isinstance(tool_id_or_name, int) or (isinstance(tool_id_or_name, str) and tool_id_or_name.isdigit()):
                where = "id = ?"
                param = int(tool_id_or_name)
            else:
                where = "name = ?"
                param = str(tool_id_or_name)

            row = conn.execute(
                f"SELECT id, name, repo_url, commit_hash, install_folder, env_path, review_results, status, reason, created_at, updated_at FROM tools_registry WHERE {where}",
                (param,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1],
                "repo_url": row[2],
                "commit_hash": row[3],
                "install_folder": row[4],
                "env_path": row[5],
                "review_results": row[6],
                "status": row[7],
                "reason": row[8],
                "created_at": row[9],
                "updated_at": row[10],
            }
        finally:
            conn.close()

    def list_tool_candidates(self, status: str | None = None) -> list[dict]:
        """List tools from tools_registry, optionally filtered by status."""
        conn = self._get_connection()
        try:
            if status:
                rows = conn.execute(
                    "SELECT id, name, repo_url, commit_hash, install_folder, env_path, review_results, status, reason, created_at, updated_at FROM tools_registry WHERE status = ? ORDER BY id DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, repo_url, commit_hash, install_folder, env_path, review_results, status, reason, created_at, updated_at FROM tools_registry ORDER BY id DESC"
                ).fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "repo_url": r[2],
                    "commit_hash": r[3],
                    "install_folder": r[4],
                    "env_path": r[5],
                    "review_results": r[6],
                    "status": r[7],
                    "reason": r[8],
                    "created_at": r[9],
                    "updated_at": r[10],
                }
                for r in rows
            ]
        finally:
            conn.close()

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