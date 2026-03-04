-- ARCHER Database Schema Additions for Emotion Confirmation & Profiling
-- Add these tables to your existing SQLite database

-- ============================================================================
-- EMOTION CONFIRMATION SYSTEM
-- ============================================================================

-- Track pending emotion confirmations
CREATE TABLE IF NOT EXISTS emotion_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    detected_emotion TEXT NOT NULL,
    confidence REAL NOT NULL,
    observation_id INTEGER,
    user_confirmed BOOLEAN DEFAULT NULL,
    user_actual_emotion TEXT DEFAULT NULL,
    notes TEXT,
    FOREIGN KEY (observation_id) REFERENCES observation_events(id)
);

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_emotion_conf_timestamp 
    ON emotion_confirmations(timestamp);
CREATE INDEX IF NOT EXISTS idx_emotion_conf_emotion 
    ON emotion_confirmations(detected_emotion);

-- ============================================================================
-- PROFILING EXERCISES SYSTEM
-- ============================================================================

-- Track profiling period status
CREATE TABLE IF NOT EXISTS therapist_profiling (
    id INTEGER PRIMARY KEY,
    start_date REAL NOT NULL,
    phase TEXT NOT NULL DEFAULT 'profiling',  -- profiling, baseline, active
    current_week INTEGER NOT NULL DEFAULT 1,
    days_active INTEGER NOT NULL DEFAULT 0,
    questions_asked TEXT,  -- JSON array of asked question IDs
    baseline_established BOOLEAN DEFAULT FALSE,
    notes TEXT,
    last_updated REAL NOT NULL
);

-- Store exercise segment progress
CREATE TABLE IF NOT EXISTS exercise_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id TEXT NOT NULL UNIQUE,
    exercise_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'not_started',  -- not_started, in_progress, completed, skipped
    started_at REAL,
    completed_at REAL,
    estimated_minutes INTEGER,
    questions_total INTEGER,
    questions_answered INTEGER DEFAULT 0
);

-- Store individual exercise responses
CREATE TABLE IF NOT EXISTS exercise_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    response TEXT NOT NULL,  -- JSON-encoded response
    timestamp REAL NOT NULL,
    FOREIGN KEY (segment_id) REFERENCES exercise_segments(segment_id)
);

CREATE INDEX IF NOT EXISTS idx_exercise_responses_segment 
    ON exercise_responses(segment_id);
CREATE INDEX IF NOT EXISTS idx_exercise_responses_timestamp 
    ON exercise_responses(timestamp);

-- ============================================================================
-- BASELINE DATA STORAGE
-- ============================================================================

-- Store learned baseline values for comparison
CREATE TABLE IF NOT EXISTS user_baseline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,  -- emotional, physical, social, sleep, work
    metric_name TEXT NOT NULL,
    baseline_value REAL,
    baseline_text TEXT,
    confidence REAL DEFAULT 0.0,
    sample_count INTEGER DEFAULT 0,
    last_updated REAL NOT NULL,
    UNIQUE(category, metric_name)
);

-- Examples of baseline entries:
-- category='emotional', metric_name='typical_stress_level', baseline_value=6.0
-- category='sleep', metric_name='typical_hours', baseline_value=7.5
-- category='social', metric_name='weekly_interactions', baseline_value=3.0

CREATE INDEX IF NOT EXISTS idx_baseline_category 
    ON user_baseline(category);

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Emotion confirmation accuracy by emotion type
CREATE VIEW IF NOT EXISTS emotion_confirmation_stats AS
SELECT 
    detected_emotion,
    COUNT(*) as total_detections,
    SUM(CASE WHEN user_confirmed = 1 THEN 1 ELSE 0 END) as confirmed,
    SUM(CASE WHEN user_confirmed = 0 THEN 1 ELSE 0 END) as rejected,
    ROUND(
        CAST(SUM(CASE WHEN user_confirmed = 1 THEN 1 ELSE 0 END) AS REAL) / 
        COUNT(*), 
        3
    ) as accuracy,
    AVG(confidence) as avg_confidence
FROM emotion_confirmations
WHERE user_confirmed IS NOT NULL
GROUP BY detected_emotion;

-- View: Profiling progress summary
CREATE VIEW IF NOT EXISTS profiling_progress AS
SELECT 
    p.phase,
    p.current_week,
    p.days_active,
    p.baseline_established,
    COUNT(DISTINCT es.segment_id) as total_segments,
    SUM(CASE WHEN es.status = 'completed' THEN 1 ELSE 0 END) as completed_segments,
    SUM(es.questions_answered) as total_questions_answered,
    p.last_updated
FROM therapist_profiling p
LEFT JOIN exercise_segments es ON 1=1
WHERE p.id = 1
GROUP BY p.id;

-- ============================================================================
-- HELPER FUNCTIONS (via application code)
-- ============================================================================

-- These would be implemented in Python SQLiteStore methods:

-- get_emotion_confirmation_stats(emotion: str) -> dict
--   Returns accuracy stats for specific emotion

-- get_therapist_status() -> dict
--   Returns current profiling phase and progress

-- get_recent_confirmations(emotion: str, hours: int) -> list
--   Returns recent confirmations for an emotion

-- save_exercise_response(segment_id, question_id, response) -> None
--   Stores exercise response

-- get_profiling_start_date() -> float
--   Returns timestamp when profiling started

-- get_last_profiling_question_time() -> float
--   Returns timestamp of last profiling question

-- update_baseline_value(category, metric_name, value) -> None
--   Updates or creates baseline value

-- ============================================================================
-- INITIAL DATA SETUP
-- ============================================================================

-- Initialize profiling record (run once on first setup)
INSERT OR IGNORE INTO therapist_profiling (id, start_date, phase, current_week, last_updated)
VALUES (1, strftime('%s', 'now'), 'profiling', 1, strftime('%s', 'now'));

-- ============================================================================
-- MIGRATION NOTES
-- ============================================================================

-- To add these to existing database:
-- 1. Back up current archer.db
-- 2. Run this SQL file: sqlite3 data/archer.db < database_schema_additions.sql
-- 3. Verify tables created: .tables
-- 4. Restart ARCHER

