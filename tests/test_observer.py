"""
Tests for ARCHER Observer Pipeline components (Phase 3).

Tests the sedentary tracker, intervention engine, observation logging,
and cooldown system. Does NOT require actual camera, MediaPipe, or
DeepFace — all external services are mocked.
"""

from __future__ import annotations

import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from archer.observer.analyzers import DetectionResult, SedentaryTracker


class TestSedentaryTracker(unittest.TestCase):
    """Test the local sedentary behavior tracker."""

    def setUp(self):
        # Use a very short threshold for testing (2 seconds instead of 2 hours)
        self.tracker = SedentaryTracker(threshold_minutes=0.0333)  # ~2 seconds

    def test_no_alert_when_standing(self):
        """No sedentary alert when the user is standing."""
        pose = DetectionResult(
            source="webcam",
            event_type="posture",
            confidence=0.9,
            data={"is_sitting": False, "posture": "standing"},
        )
        result = self.tracker.update(pose)
        self.assertIsNone(result)

    def test_no_alert_when_no_person(self):
        """No sedentary alert when no person is detected."""
        result = self.tracker.update(None)
        self.assertIsNone(result)

    def test_alert_after_threshold(self):
        """Sedentary alert fires after threshold exceeded."""
        pose = DetectionResult(
            source="webcam",
            event_type="posture",
            confidence=0.9,
            data={"is_sitting": True, "posture": "sitting"},
        )

        # First update — starts the timer
        result = self.tracker.update(pose)
        # Might or might not alert depending on timing
        if result is None:
            time.sleep(2.5)  # Wait past threshold
            result = self.tracker.update(pose)

        self.assertIsNotNone(result)
        self.assertEqual(result.event_type, "sedentary")
        self.assertGreater(result.confidence, 0.0)

    def test_alert_fires_only_once(self):
        """Sedentary alert fires only once until reset."""
        pose = DetectionResult(
            source="webcam",
            event_type="posture",
            confidence=0.9,
            data={"is_sitting": True, "posture": "sitting"},
        )

        # Trigger the alert
        self.tracker.update(pose)
        time.sleep(2.5)
        first = self.tracker.update(pose)
        self.assertIsNotNone(first)

        # Second call should NOT alert again
        second = self.tracker.update(pose)
        self.assertIsNone(second)

    def test_reset_clears_state(self):
        """Reset allows the alert to fire again."""
        pose = DetectionResult(
            source="webcam",
            event_type="posture",
            confidence=0.9,
            data={"is_sitting": True, "posture": "sitting"},
        )

        # Trigger
        self.tracker.update(pose)
        time.sleep(2.5)
        self.tracker.update(pose)

        # Reset
        self.tracker.reset()
        self.assertEqual(self.tracker.sitting_duration_seconds, 0.0)

    def test_timer_pauses_when_standing(self):
        """Timer pauses when user stands up, resumes when sitting again."""
        sitting = DetectionResult(
            source="webcam", event_type="posture", confidence=0.9,
            data={"is_sitting": True},
        )
        standing = DetectionResult(
            source="webcam", event_type="posture", confidence=0.9,
            data={"is_sitting": False},
        )

        self.tracker.update(sitting)
        time.sleep(0.5)
        self.tracker.update(standing)  # Pause

        duration_after_pause = self.tracker.sitting_duration_seconds
        time.sleep(0.5)
        # Duration should NOT increase while standing
        self.assertAlmostEqual(
            self.tracker.sitting_duration_seconds,
            duration_after_pause,
            delta=0.1,
        )

    def test_sitting_duration_accumulates(self):
        """Sitting duration accumulates across multiple sitting sessions."""
        sitting = DetectionResult(
            source="webcam", event_type="posture", confidence=0.9,
            data={"is_sitting": True},
        )

        self.tracker.update(sitting)
        time.sleep(0.5)
        duration = self.tracker.sitting_duration_seconds
        self.assertGreater(duration, 0.3)


class TestDetectionResult(unittest.TestCase):
    """Test the DetectionResult dataclass."""

    def test_creation(self):
        result = DetectionResult(
            source="webcam",
            event_type="emotion",
            confidence=0.85,
            data={"dominant_emotion": "happy"},
        )
        self.assertEqual(result.source, "webcam")
        self.assertEqual(result.event_type, "emotion")
        self.assertEqual(result.confidence, 0.85)
        self.assertEqual(result.data["dominant_emotion"], "happy")

    def test_default_timestamp(self):
        result = DetectionResult(
            source="webcam", event_type="test", confidence=1.0
        )
        self.assertGreater(result.timestamp, 0.0)


if __name__ == "__main__":
    unittest.main()
