"""
ARCHER Observer Pipeline.

The Observer Pipeline is the integration layer for all ambient observation.
It captures frames from the webcam, dispatches them to analyzers, and
publishes OBSERVATION events through the event bus.

The pipeline runs on a configurable analysis interval (default: every 5s)
to minimize CPU/GPU load. Frame capture runs faster (~2 FPS) so the
latest frame is always fresh when analysis fires.

Architecture:
  WebcamCapture (thread) → latest frame
  ObserverPipeline (thread) → grab latest frame every 5s
    → EmotionAnalyzer (HTTP → DeepFace container)
    → PoseAnalyzer (HTTP → MediaPipe container)
    → SedentaryTracker (local, no HTTP)
    → Publish OBSERVATION events via event bus
"""

from __future__ import annotations

import threading
import time

from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store
from archer.observer.camera import WebcamCapture
from archer.observer.analyzers import (
    DetectionResult,
    EmotionAnalyzer,
    PoseAnalyzer,
    SedentaryTracker,
)


class ObserverPipeline:
    """
    Ambient observation pipeline.

    Captures webcam frames and analyzes them for:
    - Facial emotion (via DeepFace container)
    - Body posture (via MediaPipe container)
    - Sedentary behavior (local tracker)

    All detected events are:
    1. Logged to SQLite (observation_events table)
    2. Published to the event bus (EventType.OBSERVATION)
    3. Consumed by the intervention engine for proactive agent triggers
    """

    def __init__(
        self,
        analysis_interval: float = 5.0,
        camera_device: int = 0,
    ) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._store = get_sqlite_store()
        self._analysis_interval = analysis_interval

        # Camera
        self._camera = WebcamCapture(
            device_index=camera_device,
            capture_interval=0.5,
        )

        # Analyzers
        self._emotion_analyzer = EmotionAnalyzer()
        self._pose_analyzer = PoseAnalyzer()
        self._sedentary_tracker = SedentaryTracker(threshold_minutes=120.0)

        # Control
        self._running = threading.Event()
        self._paused = threading.Event()  # Pause Observer (privacy)
        self._analysis_thread: threading.Thread | None = None

        # State tracking (for change detection — only publish on changes)
        self._last_emotion: str | None = None
        self._emotion_stable_since: float = 0.0
        self._emotion_stable_threshold: float = 60.0  # 60s of same emotion = event

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

        # Start analysis thread regardless — it handles no-camera gracefully
        self._running.set()
        self._analysis_thread = threading.Thread(
            target=self._analysis_loop,
            name="ObserverAnalysis",
            daemon=True,
        )
        self._analysis_thread.start()

        logger.info(
            f"Observer pipeline started "
            f"(analysis interval: {self._analysis_interval}s, "
            f"camera: {'active' if camera_ok else 'unavailable'})"
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

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def _analysis_loop(self) -> None:
        """
        Main analysis loop — runs every analysis_interval seconds.

        Grabs the latest frame, runs all analyzers, publishes results.
        """
        while self._running.is_set():
            # Sleep first (the first analysis doesn't need to be instant)
            time.sleep(self._analysis_interval)

            if not self._running.is_set():
                break

            if self._paused.is_set():
                continue

            try:
                self._run_analysis_cycle()
            except Exception as e:
                logger.error(f"Observer analysis cycle failed: {e}")

    def _run_analysis_cycle(self) -> None:
        """Run one analysis cycle: grab frame, run analyzers, publish events."""
        frame, timestamp = self._camera.get_latest_frame()
        self._analyses_run += 1

        if frame is None:
            # No camera — only run system-level checks
            return

        # --- Emotion Analysis ---
        emotion_results = self._emotion_analyzer.analyze(frame)
        for result in emotion_results:
            self._process_emotion(result)

        # --- Pose Analysis ---
        pose_results = self._pose_analyzer.analyze(frame)
        pose_for_sedentary = pose_results[0] if pose_results else None

        for result in pose_results:
            self._publish_observation(result)

        # --- Sedentary Tracking ---
        sedentary_result = self._sedentary_tracker.update(pose_for_sedentary)
        if sedentary_result is not None:
            self._publish_observation(sedentary_result)

    def _process_emotion(self, result: DetectionResult) -> None:
        """
        Process an emotion detection result.

        Only publishes events for sustained emotions (not momentary flickers).
        An emotion must be stable for _emotion_stable_threshold seconds
        before it becomes an observation event.
        """
        dominant = result.data.get("dominant_emotion", "neutral")

        if dominant == self._last_emotion:
            # Same emotion as last check — update duration
            elapsed = time.monotonic() - self._emotion_stable_since

            # Only publish after sustained detection (not flickers)
            if elapsed >= self._emotion_stable_threshold:
                # Publish sustained emotion event
                result.data["sustained_seconds"] = elapsed
                result.event_type = "sustained_emotion"
                self._publish_observation(result)
                # Reset to avoid re-publishing every cycle
                self._emotion_stable_since = time.monotonic()
        else:
            # Emotion changed — reset timer
            self._last_emotion = dominant
            self._emotion_stable_since = time.monotonic()

    def _publish_observation(self, result: DetectionResult) -> None:
        """Log to SQLite and publish to event bus."""
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

        # Publish to event bus
        self._bus.publish(Event(
            type=EventType.OBSERVATION,
            source=f"observer.{result.event_type}",
            data={
                "event_type": result.event_type,
                "source": result.source,
                "confidence": result.confidence,
                **result.data,
            },
        ))

        self._observations_published += 1
        logger.debug(
            f"Observation: {result.event_type} "
            f"(confidence: {result.confidence:.2f}, "
            f"data: {result.data})"
        )
