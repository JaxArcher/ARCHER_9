"""
Tests for ARCHER Observer Pipeline components.

Tests the scene analyzer, person identifier, observation logging,
and ObserverPipeline singleton.
"""

from __future__ import annotations

import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from archer.observer.analyzers import DetectionResult, SceneAnalyzer


class TestDetectionResult(unittest.TestCase):
    """Test the DetectionResult dataclass."""

    def test_creation(self):
        result = DetectionResult(
            source="webcam",
            event_type="scene",
            confidence=0.85,
            data={"description": "Working at desk"},
        )
        self.assertEqual(result.source, "webcam")
        self.assertEqual(result.event_type, "scene")
        self.assertEqual(result.confidence, 0.85)
        self.assertEqual(result.data["description"], "Working at desk")

    def test_default_timestamp(self):
        result = DetectionResult(
            source="webcam", event_type="test", confidence=1.0
        )
        self.assertGreater(result.timestamp, 0.0)


class TestObserverPipelineSingleton(unittest.TestCase):
    """Test ObserverPipeline singleton pattern and camera property."""

    @patch("archer.observer.pipeline.WebcamCapture")
    def test_pipeline_singleton_and_camera_property(self, mock_webcam):
        from archer.observer.pipeline import ObserverPipeline, get_observer_pipeline

        pipeline = ObserverPipeline()
        self.assertIsNotNone(ObserverPipeline.get_instance())
        self.assertEqual(ObserverPipeline.get_instance(), pipeline)
        self.assertEqual(get_observer_pipeline(), pipeline)
        self.assertIsNotNone(pipeline.camera)


if __name__ == "__main__":
    unittest.main()

