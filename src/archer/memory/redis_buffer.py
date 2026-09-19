"""
ARCHER Redis Buffer (Tier 1 Memory).

Purpose: Crash recovery and session continuity.
Storage duration: 24 hours with auto-expiry.
Key pattern: archer:buffer:{user_id}:{session_id}
"""

import json
import threading
from datetime import timedelta
from typing import Any, Callable

import redis
from loguru import logger

from archer.config import get_config


class RedisBuffer:
    """
    Layer 1: Redis-based buffer for immediate session recovery.
    """

    def __init__(self) -> None:
        self._config = get_config()
        try:
            self._client = redis.from_url(self._config.redis_url, decode_responses=True)
            # Test connection
            self._client.ping()
            logger.info(f"Redis buffer connected at {self._config.redis_url}")
        except Exception as e:
            logger.warning(f"Redis connection failed (Buffer Layer 1 inactive): {e}")
            self._client = None

    def save_snapshot(self, session_id: str, data: dict[str, Any]) -> None:
        """Save a session state snapshot with 24-hour expiry."""
        if not self._client:
            return

        key = f"archer:buffer:colby:{session_id}"
        try:
            self._client.setex(
                key,
                timedelta(hours=24),
                json.dumps(data),
            )
            logger.debug(f"Saved session snapshot: {key}")
        except Exception as e:
            logger.error(f"Failed to save Redis snapshot: {e}")

    def load_snapshot(self, session_id: str) -> dict[str, Any] | None:
        """Load the latest snapshot for a session."""
        if not self._client:
            return None

        key = f"archer:buffer:colby:{session_id}"
        try:
            data = self._client.get(key)
            if data:
                return json.loads(data)  # type: ignore
        except Exception as e:
            logger.error(f"Failed to load Redis snapshot: {e}")
        return None

    def heartbeat(self, session_id: str, content_hash: str) -> None:
        """Store a heartbeat to track activity and prevent data loss."""
        if not self._client:
            return

        key = f"archer:heartbeat:colby:{session_id}"
        try:
            payload = {
                "timestamp": self._client.time()[0],
                "content_hash": content_hash,
            }
            self._client.setex(
                key,
                timedelta(hours=24),
                json.dumps(payload),
            )
        except Exception as e:
            logger.error(f"Redis heartbeat failed: {e}")

    # --- Pub/Sub (2026-09-16) ---
    # Added so the standalone observer service (archer/observer_service.py
    # -- its own OS process, decoupled from the desktop GUI / browser
    # server so observation doesn't depend on either being open) can reach
    # CoreAgent, wherever CoreAgent happens to be running. The in-process
    # EventBus only ever worked because everything used to share one
    # process; this is the cross-process equivalent, using infrastructure
    # (Redis) already running for session-recovery snapshots above.

    def publish(self, channel: str, data: dict[str, Any]) -> None:
        """Publish one JSON-encoded message to a channel. Best-effort --
        if Redis is unreachable this just logs and returns, same as every
        other method here; a dropped observer event is not worth crashing
        over."""
        if not self._client:
            return
        try:
            self._client.publish(channel, json.dumps(data))
        except Exception as e:
            logger.debug(f"Redis publish to {channel} failed (non-fatal): {e}")

    # --- Cross-process "is a live ARCHER session open" flag (2026-09-19) ---
    # Added so the standalone observer service (its own OS process, per
    # the 2026-09-16 decoupling above) can know whether server.py's
    # browser client is currently connected, even though they don't share
    # memory. Needed because moondream is moving back to CPU-only (Col's
    # call): CPU inference is fine in isolation, but it previously starved
    # STT/audio scheduling when it ran WHILE ARCHER was actively being
    # used. Process separation alone doesn't fix that -- both processes
    # still share the same physical CPU cores -- so this lets the
    # observer actually pause its own CPU-heavy analysis for the window
    # that matters, instead of relying on GPU isolation to sidestep the
    # problem entirely.
    #
    # TTL-based rather than an explicit start/stop message on purpose: if
    # ARCHER's process is killed or crashes instead of shutting down
    # cleanly, a one-shot "session ended" message would never arrive and
    # the observer would stay paused forever. A short-lived key that the
    # GUI side refreshes every few seconds just expires naturally instead.
    _GUI_ACTIVE_KEY = "archer:gui_active"
    _GUI_ACTIVE_TTL_S = 8  # server.py's heartbeat refreshes this every ~3s

    def mark_gui_active(self) -> None:
        """Call repeatedly (every few seconds) from whichever process owns
        the GUI/WS server, for as long as at least one client is
        connected. See server.py's heartbeat loop."""
        if not self._client:
            return
        try:
            self._client.setex(self._GUI_ACTIVE_KEY, self._GUI_ACTIVE_TTL_S, "1")
        except Exception as e:
            logger.debug(f"Redis mark_gui_active failed (non-fatal): {e}")

    def is_gui_active(self) -> bool:
        """Best-effort check of the flag above. Fails OPEN (returns False,
        i.e. "no session detected") if Redis is unreachable -- a Redis
        outage should degrade to the observer running as if it's alone,
        not to it staying permanently paused."""
        if not self._client:
            return False
        try:
            return bool(self._client.exists(self._GUI_ACTIVE_KEY))
        except Exception as e:
            logger.debug(f"Redis is_gui_active check failed (non-fatal): {e}")
            return False

    def subscribe(self, channel: str, callback: Callable[[dict[str, Any]], None]) -> None:
        """Subscribe to a channel and invoke callback(data) for every
        message, on a dedicated background daemon thread. Safe to call
        multiple times for different channels/callbacks -- each gets its
        own thread and its own pubsub connection."""
        if not self._client:
            logger.debug(f"Redis unavailable -- subscribe({channel}) is a no-op.")
            return

        def _listen():
            pubsub = self._client.pubsub()
            pubsub.subscribe(channel)
            logger.info(f"Redis subscribed to '{channel}'.")
            try:
                for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                    except Exception as e:
                        logger.debug(f"Redis message on {channel} was not valid JSON: {e}")
                        continue
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"Redis subscriber callback for {channel} failed: {e}")
            except Exception as e:
                logger.warning(f"Redis subscription to {channel} ended (non-fatal): {e}")

        threading.Thread(target=_listen, daemon=True, name=f"redis-sub-{channel}").start()


# Global singleton
_buffer: RedisBuffer | None = None


def get_redis_buffer() -> RedisBuffer:
    """Get the global Redis buffer singleton."""
    global _buffer
    if _buffer is None:
        _buffer = RedisBuffer()
    return _buffer
