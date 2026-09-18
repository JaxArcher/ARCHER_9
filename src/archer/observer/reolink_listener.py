"""
ARCHER Reolink Camera Smart Detection Listener (Tier 0).

Subscribes to ONVIF motion/person push-events from Reolink camera (RLC-520A)
via reolink-aio library. Fires high-priority analysis triggers to the
ObserverPipeline when camera firmware detects a person in frame.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable, Optional
from loguru import logger

from archer.config import get_config


class ReolinkSmartDetector:
    """
    Tier 0 ONVIF smart detection listener for Reolink cameras.
    """

    def __init__(
        self,
        on_person_detected: Callable[[], None] | None = None,
        onvif_port: int = 8000,
    ) -> None:
        self._config = get_config()
        self._on_person_detected = on_person_detected
        self._onvif_port = onvif_port
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._host_client = None

    def start(self) -> bool:
        """Start ONVIF event listener loop in background thread."""
        rtsp_url = self._config.network_camera_url
        if not rtsp_url:
            logger.info("No network camera URL configured — Reolink Tier 0 listener skipped.")
            return False

        if self._running.is_set():
            return True

        self._running.set()
        self._thread = threading.Thread(
            target=self._run_async_loop,
            name="ReolinkONVIFListener",
            daemon=True,
        )
        self._thread.start()
        logger.info("Reolink ONVIF Tier 0 smart detection listener started.")
        return True

    def stop(self) -> None:
        """Stop ONVIF listener."""
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _run_async_loop(self) -> None:
        """Run asyncio loop for reolink-aio Host subscription."""
        asyncio.run(self._listen_events())

    async def _listen_events(self) -> None:
        """Subscribe to Reolink camera ONVIF events using reolink-aio."""
        rtsp_url = self._config.network_camera_url
        if not rtsp_url:
            return

        # Extract host/ip from RTSP URL (rtsp://user:pass@host:port/path)
        try:
            from urllib.parse import urlparse
            parsed = urlparse(rtsp_url)
            host = parsed.hostname or "127.0.0.1"
            username = parsed.username or ""
            password = parsed.password or ""
        except Exception:
            logger.warning("Failed to parse network camera URL for ONVIF listener.")
            return

        try:
            from reolink_aio.api import Host
            host_client = Host(
                host,
                username=username,
                password=password,
                port=self._onvif_port,
                use_https=False,
            )
            await host_client.get_host_data()
            logger.info(f"Connected to Reolink camera '{host_client.name}' ({host_client.model}) via ONVIF.")

            # Event callback
            def event_callback(event_type: str, state: str) -> None:
                if "person" in event_type.lower() and (state.lower() in ("true", "on", "active", "1")):
                    logger.info(f"Reolink camera native Person Detection event fired! ({event_type}={state})")
                    if self._on_person_detected:
                        try:
                            self._on_person_detected()
                        except Exception as e:
                            logger.error(f"Error in person detection callback: {e}")

            # Subscribe to events
            host_client.subscribe(event_callback)
            self._host_client = host_client

            while self._running.is_set():
                await asyncio.sleep(2.0)
                await host_client.poll_onvif()

            await host_client.unsubscribe()
            await host_client.disconnect()
        except Exception as e:
            logger.debug(f"Reolink ONVIF listener unavailable or degraded: {e}")
