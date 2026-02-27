"""
ARCHER Observer Frame Analyzers.

Each analyzer receives a frame (numpy array in BGR format) and returns
structured detection results. The analyzers dispatch to containerized
services (MediaPipe, DeepFace) via HTTP to isolate dependency conflicts.

All analyzers are non-blocking and gracefully degrade if services
are unavailable.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from loguru import logger

from archer.config import get_config


@dataclass
class DetectionResult:
    """A single detection from a frame analyzer."""

    source: str          # 'webcam', 'mic', 'system'
    event_type: str      # e.g. 'emotion', 'posture', 'food', 'sedentary'
    confidence: float    # 0.0 - 1.0
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


def _frame_to_jpeg_b64(frame: np.ndarray, quality: int = 70) -> str:
    """Encode a BGR frame as base64 JPEG for HTTP dispatch."""
    try:
        import cv2
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer.tobytes()).decode('utf-8')
    except Exception as e:
        logger.error(f"Frame encoding failed: {e}")
        return ""


class EmotionAnalyzer:
    """
    Detect facial emotions via DeepFace container.

    Sends JPEG frames to the DeepFace HTTP service and returns
    emotion classification results.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._url = f"{self._config.deepface_url}/analyze"
        self._available = True
        self._last_check = 0.0
        self._check_interval = 60.0  # Re-check availability every 60s

    def analyze(self, frame: np.ndarray) -> list[DetectionResult]:
        """
        Analyze a frame for facial emotions.

        Returns a list of DetectionResult for each detected face.
        """
        if not self._is_available():
            return []

        try:
            import httpx

            b64_frame = _frame_to_jpeg_b64(frame)
            if not b64_frame:
                return []

            resp = httpx.post(
                self._url,
                json={
                    "image": b64_frame,
                    "actions": ["emotion"],
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for face in data.get("results", []):
                dominant = face.get("dominant_emotion", "neutral")
                emotions = face.get("emotion", {})
                confidence = emotions.get(dominant, 0.0) / 100.0

                results.append(DetectionResult(
                    source="webcam",
                    event_type="emotion",
                    confidence=confidence,
                    data={
                        "dominant_emotion": dominant,
                        "emotions": emotions,
                        "face_region": face.get("region", {}),
                    },
                ))
            return results

        except Exception as e:
            logger.debug(f"Emotion analysis unavailable: {e}")
            self._available = False
            self._last_check = time.monotonic()
            return []

    def _is_available(self) -> bool:
        """Check if DeepFace service is available (with cooldown)."""
        if self._available:
            return True
        if time.monotonic() - self._last_check > self._check_interval:
            self._available = True  # Try again
            return True
        return False


class PoseAnalyzer:
    """
    Detect body posture and sedentary behavior via MediaPipe container.

    Sends JPEG frames to the MediaPipe HTTP service and returns
    pose landmark data.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._url = f"{self._config.mediapipe_url}/pose"
        self._available = True
        self._last_check = 0.0
        self._check_interval = 60.0

    def analyze(self, frame: np.ndarray) -> list[DetectionResult]:
        """
        Analyze a frame for body posture.

        Returns a DetectionResult with pose landmark data.
        """
        if not self._is_available():
            return []

        try:
            import httpx

            b64_frame = _frame_to_jpeg_b64(frame)
            if not b64_frame:
                return []

            resp = httpx.post(
                self._url,
                json={"image": b64_frame},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            if data.get("detected"):
                posture = data.get("posture", "unknown")
                confidence = data.get("confidence", 0.0)

                results.append(DetectionResult(
                    source="webcam",
                    event_type="posture",
                    confidence=confidence,
                    data={
                        "posture": posture,
                        "landmarks": data.get("landmarks", []),
                        "is_sitting": data.get("is_sitting", False),
                        "is_hunched": data.get("is_hunched", False),
                    },
                ))
            return results

        except Exception as e:
            logger.debug(f"Pose analysis unavailable: {e}")
            self._available = False
            self._last_check = time.monotonic()
            return []

    def _is_available(self) -> bool:
        """Check if MediaPipe service is available (with cooldown)."""
        if self._available:
            return True
        if time.monotonic() - self._last_check > self._check_interval:
            self._available = True
            return True
        return False


class SedentaryTracker:
    """
    Track sedentary behavior based on pose analysis results.

    Does NOT dispatch to an external service — this runs locally by
    monitoring the presence/absence of the user in frame and whether
    they appear to be sitting.

    Triggers:
    - Sitting detected for 2+ hours without standing → sedentary alert
    - Person disappears from frame → timer pauses
    """

    def __init__(self, threshold_minutes: float = 120.0) -> None:
        self._threshold_seconds = threshold_minutes * 60.0
        self._sitting_since: float | None = None
        self._total_sitting_seconds: float = 0.0
        self._last_update: float = 0.0
        self._alerted = False

    def update(self, pose_result: DetectionResult | None) -> DetectionResult | None:
        """
        Update sedentary tracking with the latest pose analysis.

        Args:
            pose_result: A DetectionResult from PoseAnalyzer, or None if
                        no person detected in frame.

        Returns:
            A sedentary DetectionResult if the threshold is breached,
            or None otherwise.
        """
        now = time.monotonic()

        if pose_result is None or not pose_result.data.get("is_sitting", False):
            # Not sitting or not in frame — pause timer
            if self._sitting_since is not None:
                elapsed = now - self._sitting_since
                self._total_sitting_seconds += elapsed
                self._sitting_since = None
            self._last_update = now
            return None

        # Person is sitting
        if self._sitting_since is None:
            self._sitting_since = now

        elapsed_sitting = self._total_sitting_seconds
        if self._sitting_since is not None:
            elapsed_sitting += now - self._sitting_since

        self._last_update = now

        if elapsed_sitting >= self._threshold_seconds and not self._alerted:
            self._alerted = True
            hours = elapsed_sitting / 3600.0
            return DetectionResult(
                source="webcam",
                event_type="sedentary",
                confidence=0.95,
                data={
                    "duration_minutes": elapsed_sitting / 60.0,
                    "duration_hours": hours,
                    "message": f"Sitting for {hours:.1f} hours",
                },
            )

        return None

    def reset(self) -> None:
        """Reset the sedentary timer (e.g. after the user stands up)."""
        self._sitting_since = None
        self._total_sitting_seconds = 0.0
        self._alerted = False
        logger.debug("Sedentary tracker reset.")

    @property
    def sitting_duration_seconds(self) -> float:
        """Get current accumulated sitting duration in seconds."""
        total = self._total_sitting_seconds
        if self._sitting_since is not None:
            total += time.monotonic() - self._sitting_since
        return total


class SceneAnalyzer:
    """
    Semantic scene understanding via local Vision Language Model (Qwen2-VL).

    Sends JPEG frames to a local Ollama instance for identification of objects,
    scene description, and behavioral pattern detection. This is the Tier 1
    Observer layer, ensuring 100% local vision privacy as required by the spec.

    Runs on a configurable cooldown (default 30s) to manage VRAM/CPU load.
    """

    def __init__(self, cooldown_seconds: float = 30.0) -> None:
        self._config = get_config()
        self._cooldown = cooldown_seconds
        self._last_analysis: float = 0.0
        self._available = True
        self._last_check: float = 0.0
        self._check_interval = 60.0
        self._latest_description: str = ""
        self._model = self._config.observer_model
        self._ollama_url = f"{self._config.ollama_base_url}/api/generate"

    def analyze(self, frame: np.ndarray) -> list[DetectionResult]:
        """
        Analyze a frame using local Qwen2-VL.

        Returns a DetectionResult with a text description of the scene.
        Respects a cooldown and ensures zero cloud API calls for vision.
        """
        now = time.monotonic()

        if now - self._last_analysis < self._cooldown:
            return []

        if not self._is_available() or not self._config.use_local_vision:
            return []

        try:
            import httpx

            b64_frame = _frame_to_jpeg_b64(frame, quality=60)
            if not b64_frame:
                return []

            resp = httpx.post(
                self._ollama_url,
                json={
                    "model": self._model,
                    "prompt": (
                        "Describe what you see in this webcam frame. "
                        "Identify: people present, posture, and notable objects. "
                        "Keep it to 2-3 concise sentences."
                    ),
                    "images": [b64_frame],
                    "stream": False,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

            description = data.get("response", "").strip()
            self._last_analysis = now
            self._latest_description = description

            if description:
                return [DetectionResult(
                    source="webcam",
                    event_type="scene",
                    confidence=0.85,
                    data={
                        "description": description,
                        "model": self._model,
                        "local": True,
                    },
                )]
            return []

        except Exception as e:
            logger.debug(f"Local scene analysis (Ollama) failed: {e}")
            self._available = False
            self._last_check = time.monotonic()
            self._last_analysis = now
            return []

    @property
    def latest_description(self) -> str:
        """Get the most recent scene description."""
        return self._latest_description

    def _is_available(self) -> bool:
        """Check if local Ollama service is responsive."""
        if self._available:
            return True
        if time.monotonic() - self._last_check > self._check_interval:
            self._available = True
            return True
        return False

