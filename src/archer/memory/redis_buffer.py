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
