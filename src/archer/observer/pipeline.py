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

import threading
import time

from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.redis_buffer import get_redis_buffer
from archer.memory.sqlite_store import get_sqlite_store
from archer.observer.camera import WebcamCapture
from archer.observer.analyzers import DetectionResult, SceneAnalyzer
from archer.observer.person_id import PersonIdentifier

# Single Redis channel for every observation this pipeline (or the
# staleness reasoner, a separate periodic pass -- see
# observer/staleness_reasoner.py) publishes. One channel is enough since
# every payload already carries its own event_type.
OBSERVER_REDIS_CHANNEL = "archer:observer:events"

# How often to check "did a motion window just open" while otherwise
# silent -- cheap (no camera/model work), just a clock check.
_IDLE_POLL_INTERVAL_S = 1.0


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
    ) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._store = get_sqlite_store()
        self._redis = get_redis_buffer()
        self._analysis_interval = analysis_interval or self._config.observer_analysis_frequency
        self._active_interval = self._config.observer_motion_active_interval
        self._motion_tail_s = self._config.observer_motion_tail_seconds

        # run_analysis=False: camera capture + person-detection overlay +
        # enroll_current_person still work (the desktop GUI's live preview
        # widget needs these), but the analysis thread never starts, so
        # this instance never logs/publishes observations. Added
        # 2026-09-16 so __main__.py's own ObserverPipeline (kept only for
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

        # Camera — start with local webcam (GUI mode default)
        self._camera = WebcamCapture(
            camera_source=self._config.webcam_device,
            capture_interval=0.5,
        )
        self._active_source: int | str = self._config.webcam_device

        # Analyzers
        self._scene_analyzer = SceneAnalyzer(cooldown_seconds=30.0)
        self._person_identifier = PersonIdentifier()

        # Control
        self._running = threading.Event()
        self._paused = threading.Event()  # Pause Observer (privacy)
        self._camera_released = threading.Event()  # Camera device fully released (see release_camera())
        self._analysis_thread: threading.Thread | None = None
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

        # Start camera
        camera_ok = self._camera.start()
        if not camera_ok:
            logger.info(
                "Observer running without camera. "
                "Only system-level observations will be available."
            )

        self._running.set()
        self._pipeline_started_at = time.monotonic()

        if self._run_analysis:
            # Start analysis thread regardless — it handles no-camera gracefully
            self._analysis_thread = threading.Thread(
                target=self._analysis_loop,
                name="ObserverAnalysis",
                daemon=True,
            )
            self._analysis_thread.start()
            logger.info(
                f"Observer pipeline started "
                f"(motion-gated: active interval {self._active_interval}s, "
                f"tail {self._motion_tail_s}s; "
                f"camera: {'active' if camera_ok else 'unavailable'})"
            )
        else:
            logger.info(
                f"Observer pipeline started in camera-only mode (no analysis "
                f"thread — camera: {'active' if camera_ok else 'unavailable'})"
            )
        return camera_ok

    def stop(self) -> None:
        """Stop the observer pipeline."""
        self._running.clear()
        self._camera.stop()

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

    def enroll_current_person(self, name: str = "Col", num_frames: int = 5) -> bool:
        """
        Enroll whoever is currently in front of the camera as a known
        person (default name "Col"), using the SAME already-open camera
        this pipeline is already running — unlike the standalone
        observer/enroll_person.py script, which opens its OWN separate
        WebcamCapture and would hit exactly the same "device in use"
        conflict barehands did if run while ARCHER is already running.

        This is why PersonIdentifier never actually recognized Col: the
        recognition/matching logic was correct and running the whole
        time, but `known_persons` was simply always empty — nothing
        anywhere ever called the one function (`store.add_known_person`)
        that populates it. This is that missing wire-up, exposed so it
        can be triggered live (see server.py's "enroll_face" WS message)
        instead of only via a manual script run.
        """
        if not self._person_identifier.is_available:
            logger.error("Cannot enroll — InsightFace is unavailable.")
            return False

        if self._camera_released.is_set():
            # e.g. the CAMERA toggle handed the device to barehands —
            # take it back for enrollment rather than failing silently
            # against a camera that's been intentionally shut off.
            logger.info("Camera was released — reacquiring it for enrollment.")
            self.reacquire_camera()

        embeddings = []
        for _ in range(50):
            frame, _ = self._camera.get_latest_frame()
            if frame is not None:
                emb = self._person_identifier.get_embedding(frame)
                if emb is not None:
                    embeddings.append(emb)
                    logger.info(f"Enrollment: captured face sample {len(embeddings)}/{num_frames}")
                    if len(embeddings) >= num_frames:
                        break
            time.sleep(0.3)

        if not embeddings:
            logger.error("Enrollment failed — no face detected. Make sure you're in frame and well lit.")
            return False

        import numpy as np
        avg_embedding = np.mean(embeddings, axis=0, dtype=np.float32)
        norm = np.linalg.norm(avg_embedding)
        if norm > 0:
            avg_embedding = avg_embedding / norm

        self._store.add_known_person(name=name, embedding=avg_embedding.tobytes())
        logger.info(f"Enrolled '{name}' with {len(embeddings)} face samples.")
        return True

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

        # --- Person Identification (InsightFace) ---
        person_detections = self._person_identifier.identify_persons(frame, camera_source=cam_source_str)
        gui_detections: list[dict] = []
        for pd in person_detections:
            gui_detections.append({
                "type": "person",
                "person_id": pd.get("person_id", "Person"),
                "is_known": pd.get("is_known", False),
                "box": pd.get("box", []),
                "confidence": pd.get("confidence", 0.0),
            })
            # Exclude the raw embedding BLOB (2026-09-21 finding) -- pd
            # carries it so CoreAgent can bind a live "this is Sarah" to
            # this exact face without a second InsightFace pass, but
            # _publish_observation JSON-serializes this payload for both
            # the observation_events log and the Redis publish, and bytes
            # isn't JSON serializable. Confirmed live: this was silently
            # failing every single person_sighting observation ("Failed to
            # log observation: Object of type bytes is not JSON
            # serializable") -- the embedding itself is already persisted
            # separately as a BLOB via log_person_sighting inside
            # identify_persons(), so it isn't lost, just correctly left out
            # of this JSON payload.
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

