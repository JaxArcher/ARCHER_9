"""
ARCHER Observer Pipeline.

The Observer Pipeline is the integration layer for ambient observation.
It captures frames from webcam or network cameras, dispatches them to
analyzers (Tier 1 local Qwen2-VL Scene Analysis and InsightFace Person ID),
and publishes OBSERVATION events through the event bus.

Architecture:
  WebcamCapture / RTSP Camera (thread) → latest frame
  ObserverPipeline (thread) → grab latest frame
    → PersonIdentifier (InsightFace local face identification & sighting log)
    → SceneAnalyzer (Tier 1 Ollama CPU Qwen2-VL behavioral scene analysis)
    → Publish OBSERVATION events via event bus AND Redis (see
      _publish_observation) -- Redis is what lets a CoreAgent running in a
      different OS process (the normal case now: this pipeline's real
      home is the standalone archer/observer_service.py, decoupled from
      the desktop GUI / browser session, per Col's call 2026-09-16) still
      receive these live.

Motion-gated since 2026-09-16 (Col's call): _analysis_loop no longer
polls on a flat timer regardless of activity. It stays fully quiet until
Reolink's ONVIF person-detection listener calls notify_motion(), which
opens an active analysis window; cycles run at observer_motion_active_
interval for as long as that keeps getting extended, then for at least
observer_motion_tail_seconds after the last signal, then goes quiet
again. Falls back to the old flat-timer behavior only when no
network_camera_url is configured at all, since there's nothing to
motion-gate on in that case.
"""

from __future__ import annotations

import json
import threading
import time
import uuid

import cv2
import numpy as np


from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.redis_buffer import get_redis_buffer
from archer.memory.sqlite_store import SQLiteStore, get_sqlite_store
from archer.observer.camera import WebcamCapture
from archer.observer.analyzers import DetectionResult, SceneAnalyzer
from archer.observer.person_id import PersonIdentifier
from archer.observer.person_tracker import PersonTracker
from archer.observer.room_listener import RoomListener
from archer.observer.item_watcher import ItemWatcher

# Single Redis channel for every observation this pipeline (or the
# staleness reasoner, a separate periodic pass -- see
# observer/staleness_reasoner.py) publishes. One channel is enough since
# every payload already carries its own event_type.
OBSERVER_REDIS_CHANNEL = "archer:observer:events"

# How often to check "did a motion window just open" while otherwise
# silent -- cheap (no camera/model work), just a clock check.
_IDLE_POLL_INTERVAL_S = 1.0

# Sharp looks (spec 5b, 2026-10-14): at most one full-resolution still per stay
# every few seconds, and only while the face is turned toward the camera.
_SHARP_LOOK_MIN_INTERVAL_S = 5.0
# Spread a waiting label's (up to 3) photos over the stay.
_WAITING_PHOTO_MIN_INTERVAL_S = 20.0


class ObserverPipeline:
    """
    Ambient observation pipeline.

    Captures camera frames and analyzes them for:
    - Person identification (Col vs unrecognized visitors, via InsightFace)
    - Scene description & behavioral analysis (via Qwen2-VL Ollama)

    All detected events are:
    1. Logged to SQLite (observation_events / person_sightings tables)
    2. Published to the event bus (EventType.OBSERVATION)
    """

    def __init__(
        self,
        analysis_interval: float | None = None,
        run_analysis: bool = True,
        open_camera: bool = True,
        db_path: str | None = None,
    ) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._db_path = db_path
        self._store = SQLiteStore(db_path) if db_path else get_sqlite_store()
        self._redis = get_redis_buffer()
        self._analysis_interval = analysis_interval or self._config.observer_analysis_frequency
        self._active_interval = self._config.observer_motion_active_interval
        self._motion_tail_s = self._config.observer_motion_tail_seconds
        self._open_camera = open_camera

        # run_analysis=False: camera capture and person-detection overlay
        # still work (the desktop GUI's live preview widget needs these),
        # but the analysis thread never starts, so this instance never logs/
        # publishes observations. Added 2026-09-16 so __main__.py's own
        # the GUI's camera widget) doesn't duplicate the standalone
        # observer service's analysis work and double-log every
        # observation.
        self._run_analysis = run_analysis

        # Motion window state (see notify_motion / _motion_active below).
        self._motion_active_until: float = 0.0
        self._motion_lock = threading.Lock()

        # Reolink connectivity (2026-09-19, see set_reolink_detector and
        # _has_working_motion_source): a configured network_camera_url used
        # to be treated as "has a motion source" unconditionally, even if
        # the ONVIF listener never actually connected -- which is exactly
        # what happened silently since 2026-09-16 (reolink-aio was never
        # installed), leaving _analysis_loop motion-gated on a signal that
        # could never arrive and zero ambient observations logged the
        # entire time.
        self._reolink_detector = None
        self._pipeline_started_at: float = 0.0
        self._motion_source_fallback_warned = False

        # Register global instance
        global _observer_pipeline_instance
        with _observer_pipeline_lock:
            _observer_pipeline_instance = self

        # Camera — start with network camera if configured, else local webcam (if open_camera is True)
        if self._open_camera:
            initial_source = self._config.network_camera_url if self._config.network_camera_url else self._config.webcam_device
            self._camera = WebcamCapture(
                camera_source=initial_source,
                capture_interval=0.5,
            )
            self._active_source: int | str = initial_source
        else:
            self._camera = None
            self._active_source = self._config.webcam_device

        # Analyzers
        self._scene_analyzer = SceneAnalyzer(cooldown_seconds=30.0)
        self._person_identifier = PersonIdentifier(db_path=db_path)
        self._person_tracker = PersonTracker()
        self._room_listener: RoomListener | None = RoomListener(
            pipeline=self, tracker=self._person_tracker, db_path=db_path
        )
        # Things that get moved (Phase 2d): watches the room camera beside the
        # people tracker; started with the tracker below.
        self._item_watcher: ItemWatcher | None = (
            ItemWatcher(
                snapshot=self._item_snapshot,
                is_at_exit=self._person_tracker.is_at_exit,
                notify=self._note_item_move,
            )
            if getattr(self._config, "items_watch", True) else None
        )

        # Control
        self._running = threading.Event()
        self._paused = threading.Event()  # Pause Observer (privacy)
        self._camera_released = threading.Event()  # Camera device fully released (see release_camera())
        self._analysis_thread: threading.Thread | None = None
        self._tracker_thread: threading.Thread | None = None
        self._face_check_thread: threading.Thread | None = None
        self._tracker_updates_count = 0
        self._tracker_last_update_ts = 0.0
        self._sharp_crops_count = 0
        self._fallback_crops_count = 0
        self._last_crop_stats_log_ts = time.time()
        self._camera_lock = threading.Lock()  # Protects camera swap during switching

        # Track voice pipeline state so the (CPU-bound, moondream-on-CPU)
        # analysis cycle can skip itself while the user is actively mid-turn.
        # This call is a blocking httpx POST that can take anywhere from a
        # couple seconds (warm) to 20-60s (cold model load) of real CPU
        # inference time — that was pinning the CPU hard enough to starve
        # faster-whisper (STT, also CPU) and general audio/thread scheduling,
        # producing multi-minute response delays and audio under/overflow
        # warnings on turns that had nothing to do with vision at all. Ambient
        # monitoring only actually needs to run while the user is IDLE/not
        # actively talking to ARCHER.
        #
        # This check went dead the moment observation moved into its own
        # standalone process (2026-09-16) -- self._voice_pipeline_state
        # only ever updates via the in-process EventBus subscription right
        # below, and the standalone observer_service.py has no VoicePipeline
        # publishing to it, so it just sat at "IDLE" forever, always passing.
        # Moondream got moved to GPU around the same time specifically to
        # route around that (see config.py's observer_ollama_url comment),
        # trading VRAM for safety. Reverted 2026-09-19 (Col's call): GPU
        # headroom matters more now, and a Redis-backed cross-process flag
        # (see _on_gui_active_check / RedisBuffer.is_gui_active) makes this
        # check work for real again even split across two OS processes, so
        # CPU is safe to use once more without the earlier contention.
        self._voice_pipeline_state = "IDLE"
        self._bus.subscribe(EventType.PIPELINE_STATE_CHANGED, self._on_voice_state_changed)

        # Latest detection results for GUI overlay drawing
        self._latest_detections: list[dict] = []
        self._detections_lock = threading.Lock()
        self._last_analyzed_timestamp: float = 0.0

        # Stats
        self._analyses_run = 0
        self._observations_published = 0

    def start(self) -> bool:
        """
        Start the observer pipeline (camera + analysis thread).

        Returns True if started successfully, False if camera unavailable.
        """
        if self._running.is_set():
            logger.warning("ObserverPipeline already running.")
            return True

        # Start camera if available
        if self._camera:
            camera_ok = self._camera.start()
            if not camera_ok:
                logger.info(
                    "Observer running without camera. "
                    "Only system-level observations will be available."
                )
        else:
            camera_ok = False
            logger.info("Observer running with camera disabled by configuration (browser camera mode).")

        self._running.set()
        self._pipeline_started_at = time.monotonic()

        if self._run_analysis:
            # Start dedicated person tracking thread at ~2 FPS (Spec 5b, Review 15:40 Item 1)
            self._tracker_thread = threading.Thread(
                target=self._tracker_loop,
                name="ObserverTracker",
                daemon=True,
            )
            self._tracker_thread.start()

            # Start face checks thread on its own schedule alongside tracker (Spec 5b & Review 23:55 Item 5)
            self._face_check_thread = threading.Thread(
                target=self._face_check_loop,
                name="ObserverFaceChecks",
                daemon=True,
            )
            self._face_check_thread.start()

            # Start analysis thread regardless — it handles no-camera gracefully
            self._analysis_thread = threading.Thread(
                target=self._analysis_loop,
                name="ObserverAnalysis",
                daemon=True,
            )
            self._analysis_thread.start()

            # Start ambient room listener (Phase 2c)
            if self._room_listener is not None:
                self._room_listener.start()

            # Things that get moved (Phase 2d)
            if self._item_watcher is not None:
                try:
                    self._item_watcher.start()
                except Exception as e:
                    logger.warning(f"ItemWatcher didn't start: {type(e).__name__}: {e}")
                    self._item_watcher = None

            logger.info(
                f"Observer pipeline started "
                f"(motion-gated: active interval {self._active_interval}s, "
                f"tail {self._motion_tail_s}s; "
                f"camera: {'active' if camera_ok else 'disabled/unavailable'})"
            )
        else:
            logger.info(
                f"Observer pipeline started in camera-only mode (no analysis "
                f"thread — camera: {'active' if camera_ok else 'disabled/unavailable'})"
            )
        return camera_ok

    def stop(self) -> None:
        """Stop the observer pipeline."""
        self._running.clear()
        if self._camera:
            self._camera.stop()

        if self._room_listener is not None:
            try:
                self._room_listener.stop()
            except Exception as e:
                logger.debug(f"RoomListener stop error: {e}")

        if self._item_watcher is not None:
            try:
                self._item_watcher.stop()
            except Exception as e:
                logger.debug(f"ItemWatcher stop error: {e}")

        if self._tracker_thread is not None:
            self._tracker_thread.join(timeout=3.0)
            self._tracker_thread = None

        if self._face_check_thread is not None:
            self._face_check_thread.join(timeout=3.0)
            self._face_check_thread = None

        if self._analysis_thread is not None:
            self._analysis_thread.join(timeout=5.0)
            self._analysis_thread = None

        logger.info(
            f"Observer pipeline stopped. "
            f"Analyses: {self._analyses_run}, "
            f"Observations: {self._observations_published}"
        )

    def pause(self) -> None:
        """Pause the observer (privacy mode). Camera keeps running but analysis stops."""
        self._paused.set()
        logger.info("Observer PAUSED (privacy mode).")

    def resume(self) -> None:
        """Resume the observer from privacy mode."""
        self._paused.clear()
        logger.info("Observer RESUMED.")

    def release_camera(self) -> None:
        """
        Fully release the camera device — unlike pause(), which stops
        analysis but leaves the OpenCV VideoCapture handle open (so the
        camera stays locked to this process). Windows/DirectShow generally
        only lets one process own a webcam at a time, so a still-open
        VideoCapture here is exactly what makes another app's camera
        request fail (e.g. barehands' getUserMedia erroring "device in
        use"). This actually closes the handle so another app can take it.
        The analysis thread keeps running and just sees stale/no frames
        (the same tolerant path switch_to_network_cam/switch_to_webcam
        already rely on) until reacquire_camera() is called.
        """
        if self._camera_released.is_set():
            return
        with self._camera_lock:
            self._camera.stop()
        self._camera_released.set()
        with self._detections_lock:
            self._latest_detections = []
        logger.info("Observer camera released — device is free for other apps.")

    def reacquire_camera(self) -> bool:
        """Re-open the camera after release_camera(), on whatever source was active before.

        Returns whether the device actually opened. On failure the camera
        now stays marked as released (2026-10-06) -- it used to be marked
        reacquired either way, which left the CAMERA button saying ARCHER
        had the webcam while nothing was open, and gave callers nothing to
        retry on. The usual transient cause is the browser not having
        finished closing the device yet after the Gesture tab (barehands)
        was left; server.py's camera_reacquire handler retries for that.
        """
        if not self._camera_released.is_set():
            return True
        logger.info(f"Reacquiring observer camera (source: {self._active_source})...")
        with self._camera_lock:
            self._camera = WebcamCapture(
                camera_source=self._active_source, capture_interval=0.5
            )
            ok = self._camera.start() if self._running.is_set() else True
        if ok:
            self._camera_released.clear()
        logger.info(f"Observer camera reacquired ({'ok' if ok else 'failed to open -- still released'}).")
        return ok

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def is_camera_released(self) -> bool:
        return self._camera_released.is_set()

    @property
    def camera(self) -> WebcamCapture:
        """Expose camera for GUI webcam feed display."""
        return self._camera

    @property
    def scene_analyzer(self) -> SceneAnalyzer:
        """Expose scene analyzer for GUI vision results."""
        return self._scene_analyzer

    @property
    def person_identifier(self) -> PersonIdentifier:
        """Expose person identifier."""
        return self._person_identifier

    @property
    def person_tracker(self) -> PersonTracker:
        """Expose person tracker for following people."""
        return self._person_tracker

    @property
    def room_listener(self) -> RoomListener | None:
        """Expose ambient room listener (Phase 2c)."""
        return self._room_listener

    @property
    def tracker_updates_count(self) -> int:
        return self._tracker_updates_count

    @property
    def sharp_crops_count(self) -> int:
        return self._sharp_crops_count

    @property
    def fallback_crops_count(self) -> int:
        return self._fallback_crops_count

    def get_latest_detections(self) -> list[dict]:
        """Get the latest detection results for GUI overlay drawing."""
        with self._detections_lock:
            return self._latest_detections.copy()

    def switch_to_network_cam(self) -> None:
        """
        Switch observer to the network RTSP camera.

        Called when the GUI is minimized/hidden. The observer continues
        analyzing frames from the network cam in the background.
        """
        url = self._config.network_camera_url
        if not url:
            logger.info("No network camera URL configured — staying on webcam.")
            return
        if self._active_source == url:
            return  # Already on network cam

        logger.info(f"Switching observer to network camera: {url}")
        with self._camera_lock:
            self._camera.stop()
            self._camera = WebcamCapture(camera_source=url, capture_interval=0.5)
            if self._running.is_set():
                self._camera.start()
            self._active_source = url
        with self._detections_lock:
            self._latest_detections = []

    def switch_to_webcam(self) -> WebcamCapture:
        """
        Switch observer to the local USB webcam.

        Called when the GUI becomes visible. Returns the new camera
        instance so the GUI webcam widget can re-attach to it.
        """
        device = self._config.webcam_device
        if self._active_source == device:
            return self._camera  # Already on local webcam

        logger.info(f"Switching observer to local webcam (device {device})")
        with self._camera_lock:
            self._camera.stop()
            self._camera = WebcamCapture(
                camera_source=device, capture_interval=0.5
            )
            if self._running.is_set():
                self._camera.start()
            self._active_source = device
        with self._detections_lock:
            self._latest_detections = []
        return self._camera

    def _on_voice_state_changed(self, event: Event) -> None:
        """Track voice pipeline state to gate ambient analysis (see __init__ comment).
        In the standalone observer service (the normal home for this class
        now) nothing ever publishes PIPELINE_STATE_CHANGED, so this stays
        "IDLE" forever there and never gates anything — this only matters
        if ObserverPipeline is ever run with run_analysis=True inside a
        process that also owns a VoicePipeline."""
        self._voice_pipeline_state = event.data.get("state", "IDLE")

    def set_reolink_detector(self, detector) -> None:
        """Wire in the ReolinkSmartDetector instance so _analysis_loop can
        tell a genuinely connected motion source apart from a configured-
        but-never-connected one (see is_connected's docstring). Optional --
        if never called, behavior falls back to the old "URL configured =
        treat as motion source" assumption."""
        self._reolink_detector = detector

    def _has_working_motion_source(self) -> bool:
        """Whether there's a network camera AND (once past a startup grace
        period) actual evidence its ONVIF listener is really connected --
        rather than just a URL sitting in config. Without the grace period,
        this would flap to flat-interval polling every time before the
        async ONVIF handshake (a few seconds) has had a chance to complete."""
        if not self._config.network_camera_url:
            return False
        if self._reolink_detector is None:
            # No detector wired in (e.g. __main__.py's GUI-preview instance,
            # which never runs the analysis thread anyway) -- old behavior.
            return True
        if self._reolink_detector.is_connected():
            return True
        # 45s (2026-09-21, widened from 30s): the listener's own internal
        # connection attempt can legitimately take up to 30s now that it's
        # allowed to run reolink_aio's full port/https auto-detect recovery
        # (see reolink_listener.py) rather than being forced onto a single
        # wrong port -- a matching 30s grace period here would race that,
        # firing the "never connected" fallback right as a real connection
        # was about to land.
        grace_s = 45.0
        if self._pipeline_started_at and (time.monotonic() - self._pipeline_started_at) < grace_s:
            return True  # still within the ONVIF handshake grace window
        if not self._motion_source_fallback_warned:
            logger.warning(
                "Reolink ONVIF listener never connected -- falling back to "
                "flat-interval analysis instead of staying motion-gated on "
                "a signal that isn't arriving. Check that reolink-aio is "
                "installed and the camera is reachable/ONVIF-enabled."
            )
            self._motion_source_fallback_warned = True
        return False

    def notify_motion(self) -> None:
        """Called by the Reolink ONVIF listener (observer/reolink_listener.py)
        whenever the camera's own onboard AI reports a person present.
        Opens or extends an active analysis window rather than being a
        plain on/off toggle -- repeated "still there" signals while
        someone stays in frame keep pushing the window out, and once
        signals stop, the window (and therefore active analysis) simply
        expires observer_motion_tail_seconds after the LAST one. That
        alone satisfies "keep monitoring for at least 30 seconds after
        motion stops" with no separate "motion stopped" event needed."""
        with self._motion_lock:
            self._motion_active_until = max(
                self._motion_active_until, time.monotonic() + self._motion_tail_s
            )
        logger.debug("Observer: motion window opened/extended.")

    def _motion_active(self) -> bool:
        with self._motion_lock:
            return time.monotonic() < self._motion_active_until

    def _tracker_loop(self) -> None:
        """
        Dedicated quick tracking loop (Spec 5b, Review 15:40 Item 1).
        Runs at ~2 FPS (~500ms) on the room camera, completely decoupled from
        the slow scene analysis cycle.
        """
        tracker_interval = 1.0 / self._person_tracker.fps  # ~0.50s (2 FPS)
        logger.info(f"ObserverTracker thread started (~{self._person_tracker.fps:.1f} FPS, {tracker_interval*1000:.0f}ms loop).")
        while self._running.is_set():
            time.sleep(tracker_interval)

            if not self._running.is_set() or self._paused.is_set():
                continue

            # Only track bodies on room camera
            is_room_cam = (
                self._active_source == self._config.network_camera_url
                or not self._config.network_camera_url
                or "network" in str(self._active_source).lower()
                or "room" in str(self._active_source).lower()
                or "rtsp" in str(self._active_source).lower()
            )
            if not is_room_cam:
                continue

            with self._camera_lock:
                if self._camera is None:
                    continue
                frame, timestamp = self._camera.get_latest_frame()

            if frame is None:
                continue

            try:
                self._person_tracker.update(frame, timestamp=timestamp, store=self._store)
                self._tracker_updates_count += 1
                self._tracker_last_update_ts = time.time()
            except Exception as e:
                logger.error(f"Observer tracker update failed: {e}")
                continue

            if self._item_watcher is not None:
                try:
                    self._item_watcher.observe(frame, timestamp or time.time(), self._person_tracker.active_tracks)
                except Exception as e:
                    logger.warning(f"ItemWatcher frame failed: {type(e).__name__}: {e}")

    def _item_snapshot(self) -> bytes | None:
        """A sharp still from the room camera's main stream, for the item watcher (Phase 2d)."""
        if self._reolink_detector is None:
            return None
        return self._reolink_detector.get_snapshot(timeout=8.0)

    def _note_item_move(self, text: str) -> None:
        """Someone other than Col moved an item: list it under While You Were Away (Phase 2d).
        Marked delivered at once: ARCHER mentions item moves itself (CoreAgent, from the item
        records), not through the Blindspot catch-up."""
        try:
            row_id = self._store.add_pending_intervention(
                category="items", metric="item_moved", content=text, source="items"
            )
            self._store.mark_interventions_delivered([row_id])
        except Exception as e:
            logger.debug(f"Couldn't add the item move to While You Were Away: {e}")

    def _face_check_loop(self) -> None:
        """
        Face checks run on their own schedule alongside the tracker (Spec 5b & Review 23:55 Item 5).
        Runs un-gated by motion alerts, slow scene descriptions, or ARCHER GUI state.
        Cadence:
        - Unconfirmed tracks: checks every 1.5–2.0 seconds.
        - Confirmed Col tracks: re-checks every 60 seconds.
        """
        logger.info("ObserverFaceChecks thread started (face check schedule).")
        while self._running.is_set():
            time.sleep(1.0)
            if not self._running.is_set() or self._paused.is_set():
                continue

            with self._camera_lock:
                if self._camera is None:
                    continue
                frame, timestamp = self._camera.get_latest_frame()

            if frame is None:
                continue

            try:
                self._run_tracker_face_checks(frame, timestamp=timestamp)
                # Must-fix 3: Publish presence every 30s for every identified stay
                self._publish_room_camera_presence(self._person_tracker.active_tracks, timestamp)
            except Exception as e:
                logger.error(f"Observer face check failed: {e}")

    def _select_track_face(self, track: Track, candidate_faces: list[Any]) -> Optional[Any]:
        """
        Select the correct face for a person track (Review 2026-10-13 Item 2 & 11).
        1. Filter out decor faces.
        2. When a box contains more than one face, pick the one at the person's head (lowest y / top of body box).
        """
        if not candidate_faces:
            return None
        tx, ty, tw, th = track.box
        inside_faces = []
        for f in candidate_faces:
            fb = f.bbox
            fcx = (fb[0] + fb[2]) / 2.0
            fcy = (fb[1] + fb[3]) / 2.0
            if tx <= fcx <= tx + tw and ty <= fcy <= ty + th:
                if hasattr(f, "embedding") and f.embedding is not None:
                    emb = np.array(f.embedding, dtype=np.float32)
                    if self._person_identifier and self._person_identifier.is_decor_face(emb, store=self._store):
                        continue
                inside_faces.append(f)

        if not inside_faces:
            return None

        # Pick the face at the person's head (lowest y / top of body box)
        return min(inside_faces, key=lambda f: f.bbox[1])

    def _publish_room_camera_presence(self, tracks: list[Track], now: Optional[float] = None) -> None:
        """
        Publish 'person seen' observation events from active room-camera stays (Review 2026-10-13 Item 5 & Must-fix 3).
        Keeps the Blindspot agent's time-in-the-room tracking and the chat's activity status updated.
        Publishes for every identified stay, every 30 seconds while it lasts.
        """
        curr_ts = now if now is not None else time.time()
        for track in tracks:
            if getattr(track, "is_known", False) and track.assigned_identity and track.state == "active":
                last_pub = getattr(track, "_last_presence_published_ts", 0.0)
                if (curr_ts - last_pub) >= 30.0:
                    self._publish_observation(DetectionResult(
                        source="network_cam",
                        event_type="person_sighting",
                        confidence=track.confidence,
                        data={
                            "person_id": track.assigned_identity,
                            "is_known": True,
                            "box": track.box,
                            "stay_id": track.stay_id,
                            "track_id": track.track_id,
                        },
                    ))
                    track._last_presence_published_ts = curr_ts

    def _run_tracker_face_checks(self, frame: np.ndarray, timestamp: Optional[float] = None) -> None:
        """
        Face checks run on their own schedule alongside the tracker (Spec 5b & Review 23:55 Item 5).
        Runs un-gated by motion alerts, slow scene descriptions, or ARCHER GUI state.
        Cadence:
        - Unconfirmed tracks: checks every 1.5–2.0 seconds.
        - Confirmed Col tracks: re-checks every 60 seconds.
        """
        if not self._person_identifier or not self._person_identifier.is_available:
            return

        now = timestamp if timestamp is not None else time.time()
        # Must-fix 3: Publish 'person seen' events for every identified stay every 30 seconds
        self._publish_room_camera_presence(self._person_tracker.active_tracks, now)

        # Should-fix 10: Check only tracks currently in view (state == "active")
        tracks = [t for t in self._person_tracker.active_tracks if t.state == "active"]
        if not tracks:
            return

        tracks_to_check = []
        for track in tracks:
            needs_initial_id = (not track.confirmed_known or track.assigned_identity is None) and (now - track.last_face_check_ts >= 1.5)
            needs_periodic_recheck = (track.confirmed_known and track.assigned_identity == "Col" and (now - track.last_face_check_ts >= 60.0))
            if needs_initial_id or needs_periodic_recheck:
                tracks_to_check.append((track, needs_initial_id, needs_periodic_recheck))

        if not tracks_to_check:
            return

        cam_source_str = "network_cam" if self._config.network_camera_url else "webcam"
        sub_faces = self._person_identifier.get_faces(frame, camera_source=cam_source_str)

        for track, needs_initial_id, needs_periodic_recheck in tracks_to_check:
            # Pick head face, skipping decor (Review 2026-10-13 Item 2 & 11)
            track_face = self._select_track_face(track, sub_faces)
            if track_face is None:
                continue

            fx1, fy1, fx2, fy2 = [int(v) for v in track_face.bbox]
            sub_face_box = [fx1, fy1, fx2 - fx1, fy2 - fy1]
            track.last_face_check_ts = now

            # Small-stream crop around the face (blur/brightness checks; never a photo).
            crop, crop_box, _ = self._person_tracker.capture_sharp_face_crop(
                track,
                frame_sub=frame,
                network_camera_url=self._config.network_camera_url,
                reolink_detector=self._reolink_detector,
                sub_face_box=sub_face_box,
                fetch_network_still=False,
            )

            # Sharp looks (spec 5b, 2026-10-14; Claude 2026-10-15): who a face belongs
            # to is judged from a sharp still from the main stream, taken only when the
            # face is turned toward the camera, at most once every few seconds per stay.
            analysis = None
            is_sharp = False
            if (
                self._config.network_camera_url
                and self._person_identifier.is_facing_camera(track_face)
                and (now - getattr(track, "_last_sharp_look_ts", 0.0)) >= _SHARP_LOOK_MIN_INTERVAL_S
            ):
                track._last_sharp_look_ts = now
                still_crop, still_box, got_still = self._person_tracker.capture_sharp_face_crop(
                    track,
                    frame_sub=frame,
                    network_camera_url=self._config.network_camera_url,
                    reolink_detector=self._reolink_detector,
                    sub_face_box=sub_face_box,
                    fetch_network_still=True,
                )
                if got_still and still_crop is not None:
                    analysis = self._person_identifier.analyze_face_crop(
                        still_crop,
                        store=self._store,
                        stay_id=track.stay_id,
                        camera_source=cam_source_str,
                    )
                    if analysis is not None:
                        is_sharp = True
                        crop, crop_box = still_crop, still_box

            if analysis is None:
                # Small-stream look: reuse the face already analysed in the whole
                # frame instead of running the face model again on the same pixels.
                analysis = self._person_identifier.analyze_detected_face(
                    track_face, crop, store=self._store
                )
            if analysis is None:
                continue

            if is_sharp:
                self._sharp_crops_count += 1
            else:
                self._fallback_crops_count += 1

            is_clear = analysis["is_clear"]
            col_sim = analysis["col_sim"]
            crop_emb = analysis["embedding"]
            match_res = analysis["match_res"]
            det_conf = analysis["det_score"]

            if needs_periodic_recheck:
                # Only a sharp, clear look can split Col's stay (small-stream faces of
                # Col have scored below 0.25 while clear; sharp ones haven't).
                self.recheck_track_face(track, crop_emb, is_clear=(is_clear and is_sharp), timestamp=now)
            elif needs_initial_id:
                pid = match_res.get("person_id")
                is_k = match_res.get("is_known", False)
                sim = match_res.get("sim", 0.0)

                stay_is_col = (track.assigned_identity == "Col" and track.confirmed_known)
                if stay_is_col:
                    is_clear_stranger = (
                        is_clear and (
                            (is_k and pid != "Col" and sim >= self._person_identifier._threshold)
                            or (col_sim < 0.25)
                        )
                    )
                    if is_clear_stranger:
                        # Must-fix 6: Single look < 0.25 does not split Col's stay
                        if col_sim < 0.25 and not is_k:
                            track._consecutive_stranger_looks = getattr(track, "_consecutive_stranger_looks", 0) + 1
                            if track._consecutive_stranger_looks >= 2:
                                self._person_tracker.resolve_track_identity(
                                    track, pid or "Person", is_known=is_k, confidence=sim, store=self._store
                                )
                        else:
                            self._person_tracker.resolve_track_identity(
                                track, pid or "Person", is_known=is_k, confidence=sim, store=self._store
                            )
                    else:
                        track.assigned_identity = "Col"
                        track.confirmed_known = True
                        track.is_known = True
                        track._consecutive_stranger_looks = 0
                else:
                    if is_k and pid == "Col":
                        self._person_tracker.resolve_track_identity(
                            track, "Col", is_known=True, confidence=col_sim, store=self._store
                        )
                        self._publish_room_camera_presence([track], now)
                    elif is_k and pid != "Col":
                        self._person_tracker.resolve_track_identity(
                            track, pid, is_known=True, confidence=sim, store=self._store
                        )
                        self._publish_room_camera_presence([track], now)
                    elif is_clear and is_sharp and not is_k:
                        # Must-fix 1: Unrecognized stranger gets one waiting label for the whole stay with photo (up to 3).
                        # Only a sharp, clear look starts or feeds a label (Claude 2026-10-15).
                        waiting_lbl = getattr(track, "waiting_label_id", None)
                        if not waiting_lbl:
                            # A face that matches a label already waiting keeps that label
                            # (spec 5b acceptance: same label on later sightings).
                            if pid and sim >= self._person_identifier._threshold:
                                waiting_lbl = pid
                            else:
                                next_n = self._store.get_next_person_number()
                                waiting_lbl = f"Person_{next_n}"
                            track.waiting_label_id = waiting_lbl
                            self._person_tracker.resolve_track_identity(
                                track, waiting_lbl, is_known=False, confidence=det_conf, store=self._store
                            )

                        snap_path = getattr(track, "_last_saved_snapshot_path", None)
                        waiting_photos = getattr(track, "_waiting_photos_count", 0)
                        last_photo_ts = getattr(track, "_last_waiting_photo_ts", None)
                        if waiting_photos < 3 and (last_photo_ts is None or (now - last_photo_ts) >= _WAITING_PHOTO_MIN_INTERVAL_S):
                            # `crop` is the sharp still taken for this look.
                            snap_filename = f"{int(now)}_{waiting_lbl}.jpg"
                            snap_path = self._person_identifier.save_snapshot(crop, snap_filename)
                            track._waiting_photos_count = waiting_photos + 1
                            track._last_waiting_photo_ts = now
                            track._last_saved_snapshot_path = snap_path

                        box_to_store = json.dumps(crop_box) if crop_box else None
                        self._store.upsert_pending_person_confirmation(
                            person_id=waiting_lbl,
                            embedding=crop_emb.tobytes() if crop_emb is not None else b"",
                            snapshot_path=snap_path,
                            sighting_timestamp=now,
                            face_box=box_to_store,
                            stay_id=track.stay_id,
                            status="pending",
                        )
                        self._store.update_pending_confirmation_duration(waiting_lbl, track.duration)
                        if hasattr(self._store, "create_or_update_person_question"):
                            try:
                                self._store.create_or_update_person_question(
                                    person_id=waiting_lbl,
                                    snapshot_path=snap_path,
                                    timestamp=now,
                                )
                            except Exception as e:
                                logger.debug(f"Failed to create/update person question card: {e}")

            # Should-fix Item 9: Throttle sighting logging for unconfirmed stays to at most once per 30s
            last_sight = getattr(track, "_last_sighting_log_ts", 0.0)
            id_changed = (track.assigned_identity != getattr(track, "_last_logged_identity", None))
            should_log_sight = (last_sight == 0.0 or id_changed or (now - last_sight >= 30.0))
            if should_log_sight and track.assigned_identity:
                try:
                    # Minor Item 1: Mark as stay_association only if face itself did not match Col
                    is_col_direct = (track.assigned_identity == "Col" and col_sim >= 0.55)
                    self._store.log_person_sighting(
                        person_id=track.assigned_identity,
                        is_known=track.is_known,
                        confidence=col_sim if (track.assigned_identity == "Col") else det_conf,
                        embedding=crop_emb.tobytes() if crop_emb is not None else None,
                        camera_source=cam_source_str if is_col_direct or track.assigned_identity != "Col" else f"{cam_source_str}:stay_association",
                        stay_id=track.stay_id,
                    )
                    track._last_sighting_log_ts = now
                    track._last_logged_identity = track.assigned_identity
                except Exception as e:
                    logger.debug(f"Failed logging throttled sighting: {e}")

            if is_sharp and is_clear and track.confirmed_known and track.assigned_identity == "Col":
                self.maybe_learn_col_face(
                    track=track,
                    face_embedding=crop_emb,
                    similarity_to_col=col_sim,
                    detector_confidence=det_conf,
                    is_sharp=is_sharp,
                    is_clear=is_clear,
                )

    def recheck_track_face(
        self,
        track: Track,
        face_embedding: np.ndarray,
        is_clear: bool,
        timestamp: Optional[float] = None,
    ) -> bool:
        """
        Re-check a track confirmed as Col (Spec 5b & Review 23:55 Item 1, Review 2026-10-13 Must-fix 6).
        Splits Col's stay only on a clear face that is someone else:
        - matches another named person (sim >= threshold), or
        - is plainly unlike Col (similarity to Col < 0.25).
        Per Must-fix 6: A single look under 0.25 does NOT split Col's stay; requires >= 2 consecutive stranger looks.
        Off-angle looks (0.25 <= similarity < 0.55) or unclear faces inside Col's stay do not split the stay.
        """
        now = timestamp if timestamp is not None else time.time()
        col_sim = self._person_identifier.get_similarity_to_col(face_embedding, store=self._store)
        match_res = self._person_identifier.match_face_embedding(face_embedding, store=self._store)
        pid = match_res.get("person_id")
        is_k = match_res.get("is_known", False)
        best_sim = match_res.get("sim", 0.0)

        is_clear_stranger = (
            is_clear and (
                (is_k and pid != "Col" and best_sim >= self._person_identifier._threshold)
                or (col_sim < 0.25)
            )
        )

        if is_clear_stranger:
            if col_sim < 0.25 and not is_k:
                track._consecutive_stranger_looks = getattr(track, "_consecutive_stranger_looks", 0) + 1
                if track._consecutive_stranger_looks < 2:
                    return False

            new_stay_id = f"stay_{uuid.uuid4().hex[:12]}"
            # Review 23:55 Item 9: UTC time for split_time
            split_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))
            self._store.split_stay(
                old_stay_id=track.stay_id,
                new_stay_id=new_stay_id,
                new_person_id=pid or "Stranger",
                split_time=split_ts,
                camera_source="network_cam",
                confidence=best_sim if is_k else col_sim,
                is_known=is_k,
                track_id=track.track_id,
            )
            logger.info(
                f"Observer: Re-check identified clear stranger ({pid}, col_sim: {col_sim:.2f}). "
                f"Split stay from Col ({track.stay_id}) to {new_stay_id}."
            )
            track.stay_id = new_stay_id
            track.assigned_identity = pid
            track.is_known = is_k
            track.confidence = best_sim if is_k else col_sim
            track.confirmed_known = is_k
            track._consecutive_stranger_looks = 0
            return True
        else:
            track.confidence = max(track.confidence, col_sim)
            track._consecutive_stranger_looks = 0
            return False


    def maybe_learn_col_face(
        self,
        track: Track,
        face_embedding: np.ndarray,
        similarity_to_col: float,
        detector_confidence: float = 0.90,
        is_sharp: bool = True,
        is_clear: bool = True,
    ) -> bool:
        """
        Learn sharp-photo samples of Col during stays clearly identified as him (Spec 5b & Review 23:55 Item 10).
        Gates learning on similarity to Col (0.45 <= similarity_to_col < 0.85), requiring a sharp, clear face.
        Logs plain English change log line: 'Learned a new view of Col's face from the room camera.'
        """
        if not (is_sharp and is_clear and track.confirmed_known and track.assigned_identity == "Col"):
            return False

        if 0.45 <= similarity_to_col < 0.85:
            try:
                learned_today = self._store.count_learned_references_today("Col")
                if learned_today < 3:
                    emb_bytes = (
                        face_embedding.tobytes()
                        if isinstance(face_embedding, np.ndarray)
                        else face_embedding
                    )
                    self._store.add_person_face(name="Col", embedding=emb_bytes, source="sharp_crop")
                    self._store.log_action(
                        agent_name="observer",
                        action_type="learned_reference",
                        description="Learned a new view of Col's face from the room camera.",
                        metadata={
                            "similarity": similarity_to_col,
                            "source": "sharp_crop",
                            "stay_id": track.stay_id,
                        },
                    )
                    logger.info(
                        f"Observer: Learned sharp-photo face reference for Col "
                        f"(similarity: {similarity_to_col:.2f}, learned today: {learned_today + 1}/3)."
                    )
                    return True
            except Exception as e:
                logger.debug(f"Failed learning sharp face reference for Col: {e}")
        return False

    def _analysis_loop(self) -> None:
        """
        Motion-gated analysis loop (see module docstring). While no
        network camera is configured at all, there's no motion signal to
        gate on, so this falls back to the previous flat-interval polling
        instead of running literally forever with zero observation. Same
        fallback applies (2026-09-19) if a network camera IS configured but
        its ONVIF listener never actually connects -- see
        _has_working_motion_source.
        """
        while self._running.is_set():
            if not self._has_working_motion_source():
                time.sleep(self._analysis_interval)
            elif self._motion_active():
                time.sleep(self._active_interval)
            else:
                # Fully quiet (Col's call) -- just keep checking the clock,
                # no camera grab, no analyzer calls, no cost.
                time.sleep(_IDLE_POLL_INTERVAL_S)
                continue

            if not self._running.is_set():
                break

            if self._paused.is_set():
                continue

            if self._voice_pipeline_state != "IDLE":
                # Only ever true if this pipeline happens to be co-located
                # with a VoicePipeline in the same process (not the case
                # for the standalone observer service) -- kept for that
                # case, but is_gui_active() below is what actually matters
                # for the normal deployment.
                logger.debug(
                    f"Observer analysis cycle skipped — voice pipeline active ({self._voice_pipeline_state})"
                )
                continue

            if self._redis.is_gui_active():
                # Cross-process equivalent of the check above (2026-09-19)
                # -- see RedisBuffer.is_gui_active's docstring. Moondream
                # runs on CPU again as of this change, so this is the thing
                # actually preventing it from starving STT/audio scheduling
                # while ARCHER's session is open, regardless of which OS
                # process is running it.
                logger.debug("Observer analysis cycle skipped — ARCHER GUI/browser session is active.")
                continue

            try:
                self._run_analysis_cycle()
            except Exception as e:
                logger.error(f"Observer analysis cycle failed: {e}")

    def _run_analysis_cycle(self) -> None:
        """Run one analysis cycle: grab frame, run analyzers, publish events."""
        with self._camera_lock:
            frame, timestamp = self._camera.get_latest_frame()

        if frame is None or timestamp == self._last_analyzed_timestamp:
            # No new camera frame — skip duplicate analysis
            return

        self._last_analyzed_timestamp = timestamp
        self._analyses_run += 1

        cam_source_str = "network_cam" if self._active_source == self._config.network_camera_url else "webcam"

        # --- Multi-Person Following & Identification (Spec 5b) ---
        gui_detections: list[dict] = []
        is_room_cam = (cam_source_str == "network_cam")

        if is_room_cam:
            # 1. Tracker runs in its own 2 FPS thread (_tracker_loop).
            # If tracker thread is not running (e.g. standalone test call), update now:
            if self._tracker_thread is None:
                tracks = self._person_tracker.update(frame, timestamp=timestamp, store=self._store)
            else:
                tracks = self._person_tracker.active_tracks

            now = time.time()

            # Record / maintain stay for every active track (Review 19:30 Item 3)
            for track in tracks:
                try:
                    self._store.log_or_update_stay(
                        stay_id=track.stay_id,
                        person_id=track.assigned_identity or "Person",
                        camera_source=cam_source_str,
                        confidence=track.confidence,
                        is_known=track.is_known,
                        track_id=track.track_id,
                    )
                except Exception as e:
                    logger.debug(f"Stay logging failed: {e}")

                gui_detections.append({
                    "type": "track",
                    "track_id": track.track_id,
                    "stay_id": track.stay_id,
                    "person_id": track.assigned_identity or "Tracking...",
                    "is_known": track.is_known,
                    "box": track.box,
                    "duration": track.duration,
                })

            # Face checks run on their own schedule in _tracker_loop (Review 23:55 Item 5).
            # Reflect active tracked persons to GUI detections.
            for track in tracks:
                gui_detections.append({
                    "type": "person",
                    "person_id": track.assigned_identity or "Tracking...",
                    "is_known": track.is_known,
                    "box": track.box,
                    "confidence": track.confidence,
                })

            # Periodically log INFO count of sharp crops vs fallbacks (never credentials)
            if now - self._last_crop_stats_log_ts >= 180.0:
                total_crops = self._sharp_crops_count + self._fallback_crops_count
                if total_crops > 0:
                    pct = (self._sharp_crops_count / total_crops) * 100.0
                    logger.info(
                        f"Face Crop Stats: {self._sharp_crops_count} sharp crops, "
                        f"{self._fallback_crops_count} fallbacks ({pct:.1f}% sharp success rate)."
                    )
                self._last_crop_stats_log_ts = now
        else:
            # Desk webcam: direct face identification without continuous body tracking
            person_detections = self._person_identifier.identify_persons(frame, camera_source=cam_source_str)
            for pd in person_detections:
                gui_detections.append({
                    "type": "person",
                    "person_id": pd.get("person_id", "Person"),
                    "is_known": pd.get("is_known", False),
                    "box": pd.get("box", []),
                    "confidence": pd.get("confidence", 0.0),
                })
                pd_for_log = {k: v for k, v in pd.items() if k != "embedding"}
                self._publish_observation(DetectionResult(
                    source=cam_source_str,
                    event_type="person_sighting",
                    confidence=pd.get("confidence", 0.9),
                    data=pd_for_log,
                ))

        with self._detections_lock:
            self._latest_detections = gui_detections

        # --- Scene Analysis (Tier 1 — slower cadence, VLM-powered) ---
        scene_results = self._scene_analyzer.analyze(frame, camera_source=cam_source_str)
        for result in scene_results:
            self._publish_observation(result)

    def _publish_observation(self, result: DetectionResult) -> None:
        """Log to SQLite, publish to the local event bus, AND publish to
        Redis (2026-09-16) -- the Redis publish is what a CoreAgent running
        in a different OS process actually receives; the local event-bus
        publish only matters if something in this same process is
        subscribed (e.g. a desktop GUI status label wired directly to this
        instance)."""
        payload = {
            "event_type": result.event_type,
            "source": result.source,
            "confidence": result.confidence,
            **result.data,
        }

        # Log to Tier 2 (observation_events table)
        try:
            self._store.log_observation(
                source=result.source,
                event_type=result.event_type,
                confidence=result.confidence,
                payload=result.data,
            )
        except Exception as e:
            logger.warning(f"Failed to log observation: {e}")

        # Publish to local event bus (same-process subscribers, if any)
        self._bus.publish(Event(
            type=EventType.OBSERVATION_EVENT,
            source=f"observer.{result.event_type}",
            data=payload,
        ))

        # Publish to Redis (cross-process subscribers -- CoreAgent, see
        # core_agent.py's Redis bridge)
        self._redis.publish(OBSERVER_REDIS_CHANNEL, payload)

        self._observations_published += 1
        logger.debug(
            f"Observation: {result.event_type} "
            f"(confidence: {result.confidence:.2f}, "
            f"data: {result.data})"
        )

    @classmethod
    def get_instance(cls) -> ObserverPipeline | None:
        """Get singleton ObserverPipeline instance."""
        return _observer_pipeline_instance


_observer_pipeline_instance: ObserverPipeline | None = None
_observer_pipeline_lock = threading.Lock()


def get_observer_pipeline() -> ObserverPipeline | None:
    """Get singleton ObserverPipeline instance."""
    return _observer_pipeline_instance

