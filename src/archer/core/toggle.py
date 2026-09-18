"""
ARCHER Cloud/Local Toggle Service.

A single runtime setting — not a compile-time flag. Switchable mid-session
without restart. All components subscribe to mode changes via the event bus.

The toggle state is stored in SQLite (not in memory) so it survives restarts.
Each service reads the active mode before every request.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Literal

from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus


ModeType = Literal["cloud", "local"]


class ToggleService:
    """
    Manages the cloud/local toggle for all AI services.

    Each service (STT, TTS, LLM) has a cloud_backend and local_backend property.
    The ToggleService writes the active mode; each service reads it before every request.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._lock = threading.Lock()
        self._db_path = self._config.sqlite_db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the toggle state table in SQLite."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS toggle_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO toggle_state (key, value, updated_at)
                VALUES ('mode', ?, CURRENT_TIMESTAMP)
            """, (self._config.default_mode,))
            conn.execute("""
                INSERT OR IGNORE INTO toggle_state (key, value, updated_at)
                VALUES ('tts_mode', ?, CURRENT_TIMESTAMP)
            """, (self._config.default_tts_mode,))
            conn.commit()
        finally:
            conn.close()

    @property
    def mode(self) -> ModeType:
        """Get the current mode (cloud or local)."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    "SELECT value FROM toggle_state WHERE key = 'mode'"
                )
                row = cursor.fetchone()
                return row[0] if row else self._config.default_mode
            finally:
                conn.close()

    @mode.setter
    def mode(self, new_mode: ModeType) -> None:
        """
        Set the mode and notify all subscribers via the event bus.
        This is the central point where mode changes happen — all components
        react to the MODE_CHANGED event.
        """
        if new_mode not in ("cloud", "local"):
            raise ValueError(f"Invalid mode: {new_mode}. Must be 'cloud' or 'local'.")

        old_mode = self.mode

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO toggle_state (key, value, updated_at)
                    VALUES ('mode', ?, CURRENT_TIMESTAMP)
                """, (new_mode,))
                conn.commit()
            finally:
                conn.close()

        if old_mode != new_mode:
            logger.info(f"Mode changed: {old_mode} → {new_mode}")
            get_event_bus().publish(Event(
                type=EventType.MODE_CHANGED,
                source="toggle_service",
                data={"old_mode": old_mode, "new_mode": new_mode},
            ))

    @property
    def is_cloud(self) -> bool:
        """Check if currently in cloud mode."""
        return self.mode == "cloud"

    @property
    def is_local(self) -> bool:
        """Check if currently in local mode."""
        return self.mode == "local"

    def toggle(self) -> ModeType:
        """Toggle between cloud and local mode. Returns the new mode."""
        new_mode: ModeType = "local" if self.is_cloud else "cloud"
        self.mode = new_mode
        return new_mode

    # --- TTS mode: independent of the LLM/STT mode above (2026-09-16) ---
    # Col's setup runs conversation on the local gemma4:e4b model by
    # default while voice OUTPUT still defaults to ElevenLabs (cloud) —
    # a combination the single `mode` toggle above can't express, since it
    # ties LLM+STT+TTS together. Same SQLite-backed, event-notified pattern,
    # just a separate key so the two can differ.
    @property
    def tts_mode(self) -> ModeType:
        """Get the current TTS engine mode (cloud=ElevenLabs, local=Kokoro)."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    "SELECT value FROM toggle_state WHERE key = 'tts_mode'"
                )
                row = cursor.fetchone()
                return row[0] if row else self._config.default_tts_mode
            finally:
                conn.close()

    @tts_mode.setter
    def tts_mode(self, new_mode: ModeType) -> None:
        if new_mode not in ("cloud", "local"):
            raise ValueError(f"Invalid TTS mode: {new_mode}. Must be 'cloud' or 'local'.")

        old_mode = self.tts_mode

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO toggle_state (key, value, updated_at)
                    VALUES ('tts_mode', ?, CURRENT_TIMESTAMP)
                """, (new_mode,))
                conn.commit()
            finally:
                conn.close()

        if old_mode != new_mode:
            logger.info(f"TTS mode changed: {old_mode} → {new_mode}")
            get_event_bus().publish(Event(
                type=EventType.TTS_MODE_CHANGED,
                source="toggle_service",
                data={"old_mode": old_mode, "new_mode": new_mode},
            ))

    @property
    def is_cloud_tts(self) -> bool:
        """Check if TTS is currently set to cloud (ElevenLabs)."""
        return self.tts_mode == "cloud"

    def toggle_tts(self) -> ModeType:
        """Toggle TTS mode between cloud and local. Returns the new mode."""
        new_mode: ModeType = "local" if self.is_cloud_tts else "cloud"
        self.tts_mode = new_mode
        return new_mode

    def fallback_to_local(self, reason: str = "cloud_failure") -> None:
        """
        Auto-fallback to local mode when cloud fails.
        This is called when a cloud API call fails (timeout, rate limit, no internet).
        The user is notified once — it does not fail silently.
        """
        if self.is_cloud:
            logger.warning(f"Cloud fallback triggered: {reason}. Switching to local mode.")
            self.mode = "local"
            get_event_bus().publish(Event(
                type=EventType.SYSTEM_ERROR,
                source="toggle_service",
                data={
                    "error": "cloud_fallback",
                    "reason": reason,
                    "message": "Cloud service unavailable. Switched to local mode.",
                },
            ))

    def fallback_tts_to_local(self, reason: str = "tts_failure") -> None:
        """
        Auto-fallback to local TTS (Kokoro) when cloud TTS (ElevenLabs) fails.
        Separate from fallback_to_local() above -- flipping the TTS engine
        on a synthesis error must not also flip conversation/STT mode, now
        that TTS mode is its own independent setting (2026-09-16).
        """
        if self.is_cloud_tts:
            logger.warning(f"TTS cloud fallback triggered: {reason}. Switching TTS to local.")
            self.tts_mode = "local"
            get_event_bus().publish(Event(
                type=EventType.SYSTEM_ERROR,
                source="toggle_service",
                data={
                    "error": "tts_cloud_fallback",
                    "reason": reason,
                    "message": "Cloud TTS unavailable. Switched voice output to local.",
                },
            ))


# Global singleton
_toggle_service: ToggleService | None = None
_toggle_lock = threading.Lock()


def get_toggle_service() -> ToggleService:
    """Get the global toggle service singleton."""
    global _toggle_service
    if _toggle_service is None:
        with _toggle_lock:
            if _toggle_service is None:
                _toggle_service = ToggleService()
    return _toggle_service
