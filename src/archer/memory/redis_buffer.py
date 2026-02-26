"""
ARCHER Redis Buffer (Tier 1 Memory).

Purpose: Crash recovery and session continuity.
Storage duration: 24 hours with auto-expiry.
Key pattern: archer:buffer:{user_id}:{session_id}
"""

import json
from datetime import timedelta
from typing import Any

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


# Global singleton
_buffer: RedisBuffer | None = None


def get_redis_buffer() -> RedisBuffer:
    """Get the global Redis buffer singleton."""
    global _buffer
    if _buffer is None:
        _buffer = RedisBuffer()
    return _buffer
