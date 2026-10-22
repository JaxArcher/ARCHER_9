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
        onvif_port: int | None = None,
    ) -> None:
        self._config = get_config()
        self._on_person_detected = on_person_detected
        # None (2026-09-21 finding) -- reolink_aio's own Host class defaults
        # its `port` constructor arg to None specifically to mean "figure it
        # out yourself" (tries 443, then 80, then asks the camera's own
        # protocol which ports are actually enabled). This used to hardcode
        # 8000, which isn't this camera's real HTTP(S) API port -- forcing
        # it meant every connection attempt failed the login on 8000 first
        # and only THEN started that auto-recovery dance, confirmed live via
        # reolink_aio's own log line: "HTTP(s) login failed while Baichuan
        # login succeeded, re-opening HTTP(s) port and looking up correct
        # port". Letting it auto-detect from the start skips that wasted
        # failed attempt entirely.
        self._onvif_port = onvif_port
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._host_client = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Set only after a real ONVIF connection succeeds (2026-09-19) --
        # start() returns True as soon as the background thread launches,
        # which says nothing about whether _listen_events() actually
        # connected. ObserverPipeline uses this to decide whether it's safe
        # to motion-gate on this camera at all, or whether it should fall
        # back to flat-interval polling instead of gating on a signal that
        # will never arrive. See is_connected().
        self._connected = threading.Event()

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
        self._connected.clear()

    def is_connected(self) -> bool:
        """True once _listen_events() has actually completed a successful
        ONVIF handshake with the camera -- as opposed to start() returning
        True, which only means the background thread launched."""
        return self._connected.is_set()

    def get_snapshot(self, timeout: float = 2.5) -> bytes | None:
        """
        Fetch high-resolution still snapshot (JPEG) from Reolink camera
        via the authenticated reolink-aio Host client. The item watcher
        (Phase 2d) allows longer: a main-stream still often takes more than
        2.5 s (2026-10-20 log).
        """
        if self._host_client and self._loop and self._connected.is_set():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._host_client.get_snapshot(0, stream="main"),
                    self._loop,
                )
                return future.result(timeout=timeout)
            except Exception as e:
                logger.debug(f"ReolinkSmartDetector: snapshot fetch failed ({e})")
        return None

    def _run_async_loop(self) -> None:
        """Run asyncio loop for reolink-aio Host subscription."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._listen_events())
        finally:
            self._loop.close()
            self._loop = None

    async def _listen_events(self) -> None:
        """Subscribe to Reolink camera ONVIF events using reolink-aio."""
        rtsp_url = self._config.network_camera_url
        if not rtsp_url:
            return

        # Extract host/ip from RTSP URL (rtsp://user:pass@host:port/path)
        try:
            from urllib.parse import urlparse, unquote
            parsed = urlparse(rtsp_url)
            host = parsed.hostname or "127.0.0.1"
            # unquote() is required here (2026-09-19 finding): urlparse's
            # .username/.password properties return the RAW, still percent-
            # encoded substring from the URL, not the decoded credential --
            # e.g. a password containing a literal "@" has to be written as
            # "%40" in the URL (so it isn't mistaken for the userinfo/host
            # separator), and without unquote() here, reolink-aio was being
            # handed the literal string "...%40" -- which DOES contain a
            # bare "%", a character its own password validator rejects --
            # instead of the real, fully-valid decoded password. Confirmed
            # live: this is exactly what "Reolink password contains
            # incompatible special character" was complaining about, even
            # though the actual camera password only uses characters
            # reolink-aio's own error message lists as allowed.
            username = unquote(parsed.username or "")
            password = unquote(parsed.password or "")
        except Exception:
            logger.warning("Failed to parse network camera URL for ONVIF listener.")
            return

        backoff_delay = 5.0
        while self._running.is_set():
            host_client = None
            try:
                try:
                    from reolink_aio.api import Host
                except ImportError:
                    logger.warning(
                        "Reolink ONVIF listener can't start: the 'reolink-aio' "
                        "package isn't installed (pip install reolink-aio). "
                        "network_camera_url is configured, so ObserverPipeline "
                        "will motion-gate on this listener anyway and fall back "
                        "to flat-interval polling once it gives up waiting for "
                        "a connection -- but until reolink-aio is installed, "
                        "there will never be a real motion signal from this camera."
                    )
                    return

                # use_https=None (2026-09-21, same finding as port above): the
                # library's own __init__ defaults this to None too, and its
                # auto-detect dance (_login_try_ports) tries HTTPS first, then
                # HTTP -- forcing False here skipped that first attempt for the
                # same reason forcing port=8000 did.
                host_client = Host(
                    host,
                    username=username,
                    password=password,
                    port=self._onvif_port,
                    use_https=None,
                )
                await asyncio.wait_for(host_client.get_host_data(), timeout=30.0)
                logger.info(f"Connected to Reolink camera '{host_client.nvr_name}' ({host_client.model}) via ONVIF.")
                self._connected.set()
                backoff_delay = 5.0

                from reolink_aio.enums import SubType
                await host_client.subscribe(sub_type=SubType.long_poll)
                self._host_client = host_client
                last_renew_time = time.time()

                while self._running.is_set():
                    # Periodic subscription renewal (Claude gap 4 fix)
                    # ONVIF long-poll subscriptions terminate after 15m; renew every 5m (300s)
                    now = time.time()
                    if now - last_renew_time >= 300.0:
                        try:
                            await host_client.renew(SubType.long_poll)
                            last_renew_time = now
                            logger.debug("Successfully renewed Reolink ONVIF long_poll subscription.")
                        except Exception as re:
                            logger.warning(f"Reolink subscription renewal error: {re}. Reconnecting...")
                            break

                    try:
                        changed_channels = await host_client.pull_point_request()
                    except Exception as pe:
                        # If pull_point_request raises SubscriptionError or connection drops, trigger reconnect
                        logger.warning(f"Reolink pull_point_request error: {pe}. Reconnecting...")
                        break

                    if not self._running.is_set():
                        break
                    for channel in (changed_channels or []):
                        if host_client.ai_detected(channel, "people"):
                            logger.info(f"Reolink camera native Person Detection event fired! (channel {channel})")
                            if self._on_person_detected:
                                try:
                                    self._on_person_detected()
                                except Exception as e:
                                    logger.error(f"Error in person detection callback: {e}")

            except Exception as e:
                err_str = str(e)
                if password and password in err_str:
                    err_str = err_str.replace(password, "***")
                logger.warning(f"Reolink ONVIF listener unavailable or degraded: {err_str}")
            finally:
                self._connected.clear()
                if host_client is not None:
                    try:
                        from reolink_aio.enums import SubType
                        await host_client.unsubscribe(SubType.long_poll)
                    except Exception:
                        pass
                    try:
                        await host_client.logout()
                    except Exception:
                        pass
                self._host_client = None

            if self._running.is_set():
                logger.info(f"Reolink ONVIF listener will attempt reconnect in {backoff_delay:.1f}s...")
                try:
                    await asyncio.sleep(backoff_delay)
                except asyncio.CancelledError:
                    break
                backoff_delay = min(60.0, backoff_delay * 2.0)
