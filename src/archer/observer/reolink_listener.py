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
            # Explicit timeout (2026-09-21 finding): get_host_data() has no
            # client-side timeout of its own, so an unreachable camera made
            # this hang silently forever instead of failing -- no "Connected"
            # log, but no exception/warning either, since nothing ever
            # returned to hit the except block below. Confirmed live: the
            # RTSP video connection to this same camera was ALSO timing out
            # (30s, in observer/camera.py) on every startup, which points at
            # a network-level problem reaching the camera itself rather than
            # anything ONVIF-specific -- but there's no reason THIS call
            # should be allowed to hang indefinitely just because that one
            # has its own timeout.
            #
            # 30s, not 10s (2026-09-21 revision): with port/use_https left
            # as None above, a failed first guess now falls all the way
            # through reolink_aio's own _login_try_ports() recovery dance
            # (try HTTPS on 443, then HTTP on 80, then query the camera's
            # Baichuan-protocol port list, then retry login on whatever it
            # finds) -- several sequential connection attempts, each of
            # which can itself take a few seconds against a closed/filtered
            # port. 10s was cutting this off mid-recovery; matching
            # observer/camera.py's own 30s RTSP timeout keeps both camera
            # paths on the same budget.
            await asyncio.wait_for(host_client.get_host_data(), timeout=30.0)
            # .nvr_name, not .name (2026-09-21 finding) -- Host has no bare
            # `name` attribute in this reolink-aio version; confirmed via
            # its own source that the actual property is nvr_name. This was
            # masking a fully successful connection as a failure the whole
            # time -- get_host_data() itself was succeeding, this f-string
            # was the only thing raising.
            logger.info(f"Connected to Reolink camera '{host_client.nvr_name}' ({host_client.model}) via ONVIF.")
            self._connected.set()

            # Rewritten (2026-09-21) to match this reolink-aio version's
            # real API, confirmed by reading its source -- the previous
            # version of this code assumed a plain synchronous callback
            # (host_client.subscribe(event_callback), a loop calling
            # poll_onvif()), but neither of those exist here: subscribe()
            # is async and defaults to PUSH-style subscription, which
            # expects a webhook_url the camera can call back to over HTTP
            # -- infrastructure this simple background-thread listener
            # doesn't have. Confirmed live: the old call created an
            # un-awaited coroutine that silently did nothing
            # (RuntimeWarning), and poll_onvif() doesn't exist at all
            # ('Host' object has no attribute 'poll_onvif').
            #
            # LONG_POLL avoids needing a webhook server entirely:
            # pull_point_request() itself blocks server-side (up to
            # LONG_POLL_TIMEOUT minutes) until an event arrives or it times
            # out, so this loop naturally paces itself -- no manual sleep
            # needed between calls. ai_detected(channel, "people") is the
            # library's own synchronous, cached lookup for exactly the
            # "was a person specifically detected" question (as opposed to
            # generic motion/vehicle/pet), reading state that
            # pull_point_request() just populated.
            from reolink_aio.enums import SubType
            await host_client.subscribe(sub_type=SubType.long_poll)
            self._host_client = host_client

            while self._running.is_set():
                changed_channels = await host_client.pull_point_request()
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

            await host_client.unsubscribe(SubType.long_poll)
            await host_client.logout()
        except Exception as e:
            # Was logger.debug (2026-09-19 finding: this made a totally dead
            # motion-gate -- e.g. reolink-aio not installed at all, or the
            # camera unreachable/ONVIF disabled -- completely invisible.
            # ObserverPipeline had been motion-gating on a signal that could
            # never arrive since 2026-09-16, with zero ambient observations
            # logged the entire time and nothing in the logs at INFO level
            # to explain why. This is exactly the kind of failure that needs
            # to be loud.
            logger.warning(f"Reolink ONVIF listener unavailable or degraded: {e}")
        finally:
            self._connected.clear()
