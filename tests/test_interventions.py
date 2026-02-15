"""
Tests for ARCHER Intervention Engine and Cooldown System (Phase 3).

Tests proactive intervention triggers, cooldown enforcement,
ignore tracking, and observation event logging.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from archer.memory.sqlite_store import SQLiteStore


class TestObservationLogging(unittest.TestCase):
    """Test observation event logging in SQLiteStore."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = SQLiteStore(db_path=self._tmp.name)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_log_observation(self):
        """Observations are logged to the database."""
        row_id = self.store.log_observation(
            source="webcam",
            event_type="emotion",
            confidence=0.85,
            payload={"dominant_emotion": "sad"},
        )
        self.assertIsNotNone(row_id)
        self.assertGreater(row_id, 0)

    def test_get_recent_observations(self):
        """Recent observations are retrievable."""
        self.store.log_observation("webcam", "emotion", 0.8, payload={"e": "sad"})
        self.store.log_observation("webcam", "posture", 0.9, payload={"p": "sitting"})
        self.store.log_observation("webcam", "sedentary", 0.95, payload={"h": 2.1})

        all_obs = self.store.get_recent_observations()
        self.assertEqual(len(all_obs), 3)

    def test_filter_by_event_type(self):
        """Observations can be filtered by event type."""
        self.store.log_observation("webcam", "emotion", 0.8)
        self.store.log_observation("webcam", "posture", 0.9)
        self.store.log_observation("webcam", "emotion", 0.7)

        emotions = self.store.get_recent_observations(event_type="emotion")
        self.assertEqual(len(emotions), 2)

    def test_filter_by_source(self):
        """Observations can be filtered by source."""
        self.store.log_observation("webcam", "emotion", 0.8)
        self.store.log_observation("mic", "tone", 0.6)

        webcam_only = self.store.get_recent_observations(source="webcam")
        self.assertEqual(len(webcam_only), 1)

    def test_observation_payload_stored(self):
        """Observation payload JSON is stored correctly."""
        self.store.log_observation(
            source="webcam",
            event_type="emotion",
            confidence=0.85,
            payload={"dominant_emotion": "angry", "sustained_seconds": 120},
        )
        obs = self.store.get_recent_observations(event_type="emotion")
        self.assertEqual(len(obs), 1)
        # Payload is stored as JSON string
        import json
        payload = json.loads(obs[0]["payload"])
        self.assertEqual(payload["dominant_emotion"], "angry")
        self.assertEqual(payload["sustained_seconds"], 120)


class TestCooldownSystem(unittest.TestCase):
    """Test the intervention cooldown system in SQLiteStore."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = SQLiteStore(db_path=self._tmp.name)

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_no_cooldown_initially(self):
        """No cooldown exists for a new agent+topic."""
        in_cooldown = self.store.check_cooldown("trainer", "sedentary", 120.0)
        self.assertFalse(in_cooldown)

    def test_set_and_check_cooldown(self):
        """Setting a cooldown makes check_cooldown return True."""
        self.store.set_cooldown("trainer", "sedentary")
        in_cooldown = self.store.check_cooldown("trainer", "sedentary", 120.0)
        self.assertTrue(in_cooldown)

    def test_cooldown_expires(self):
        """Cooldown expires after the specified duration."""
        self.store.set_cooldown("trainer", "posture")
        # With a 0-minute cooldown, it should immediately expire
        # (0 minutes = always expired)
        # Use a very small cooldown value
        in_cooldown = self.store.check_cooldown("trainer", "posture", 0.0001)
        # This is tricky with timing — might still be in cooldown
        # Let's check with a reasonable cooldown
        import time
        time.sleep(0.1)
        expired = not self.store.check_cooldown("trainer", "posture", 0.001)
        self.assertTrue(expired)

    def test_different_topics_independent(self):
        """Different topics have independent cooldowns."""
        self.store.set_cooldown("trainer", "sedentary")
        self.store.set_cooldown("trainer", "posture")

        # Clear only sedentary
        self.store.clear_cooldown("trainer", "sedentary")

        sedentary_cd = self.store.check_cooldown("trainer", "sedentary", 120.0)
        posture_cd = self.store.check_cooldown("trainer", "posture", 120.0)

        self.assertFalse(sedentary_cd)  # Cleared
        self.assertTrue(posture_cd)     # Still active

    def test_different_agents_independent(self):
        """Different agents have independent cooldowns for the same topic."""
        self.store.set_cooldown("trainer", "general")
        self.store.set_cooldown("therapist", "general")

        self.store.clear_cooldown("trainer", "general")

        trainer_cd = self.store.check_cooldown("trainer", "general", 120.0)
        therapist_cd = self.store.check_cooldown("therapist", "general", 120.0)

        self.assertFalse(trainer_cd)
        self.assertTrue(therapist_cd)

    def test_update_cooldown(self):
        """Setting a cooldown again updates the timestamp."""
        self.store.set_cooldown("trainer", "sedentary")
        import time
        time.sleep(0.1)
        # Set again — should update timestamp
        self.store.set_cooldown("trainer", "sedentary")
        in_cooldown = self.store.check_cooldown("trainer", "sedentary", 120.0)
        self.assertTrue(in_cooldown)

    def test_clear_cooldown(self):
        """Clearing a cooldown removes it."""
        self.store.set_cooldown("trainer", "sedentary")
        self.store.clear_cooldown("trainer", "sedentary")
        in_cooldown = self.store.check_cooldown("trainer", "sedentary", 120.0)
        self.assertFalse(in_cooldown)


class TestInterventionEngine(unittest.TestCase):
    """Test the proactive intervention engine logic."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()

        # Patch the singletons so the intervention engine uses our test DB
        self._store_patcher = patch(
            "archer.observer.interventions.get_sqlite_store",
            return_value=SQLiteStore(db_path=self._tmp.name),
        )
        self._bus_patcher = patch(
            "archer.observer.interventions.get_event_bus",
        )
        self._mock_store_fn = self._store_patcher.start()
        self._mock_bus = self._bus_patcher.start()

        from archer.observer.interventions import InterventionEngine
        self.callback = MagicMock()
        self.engine = InterventionEngine(speak_callback=self.callback)
        self.store = self._mock_store_fn.return_value

    def tearDown(self):
        self._store_patcher.stop()
        self._bus_patcher.stop()
        os.unlink(self._tmp.name)

    def test_sedentary_triggers_callback(self):
        """Sedentary observation triggers trainer callback."""
        from archer.core.event_bus import Event, EventType

        event = Event(
            type=EventType.OBSERVATION,
            source="observer.sedentary",
            data={
                "event_type": "sedentary",
                "source": "webcam",
                "confidence": 0.95,
                "duration_minutes": 125,
                "duration_hours": 2.08,
            },
        )
        self.engine._on_observation(event)
        self.callback.assert_called_once()
        call_args = self.callback.call_args
        self.assertEqual(call_args[0][0], "trainer")  # agent name

    def test_emotion_triggers_therapist(self):
        """Sustained distress emotion triggers therapist callback."""
        from archer.core.event_bus import Event, EventType

        event = Event(
            type=EventType.OBSERVATION,
            source="observer.sustained_emotion",
            data={
                "event_type": "sustained_emotion",
                "source": "webcam",
                "confidence": 0.8,
                "dominant_emotion": "sad",
                "sustained_seconds": 1200,
            },
        )
        self.engine._on_observation(event)
        self.callback.assert_called_once()
        call_args = self.callback.call_args
        self.assertEqual(call_args[0][0], "therapist")

    def test_neutral_emotion_no_trigger(self):
        """Neutral or happy emotions don't trigger therapist."""
        from archer.core.event_bus import Event, EventType

        event = Event(
            type=EventType.OBSERVATION,
            source="observer.sustained_emotion",
            data={
                "event_type": "sustained_emotion",
                "confidence": 0.9,
                "dominant_emotion": "happy",
                "sustained_seconds": 1200,
            },
        )
        self.engine._on_observation(event)
        self.callback.assert_not_called()

    def test_low_confidence_ignored(self):
        """Low-confidence observations are ignored."""
        from archer.core.event_bus import Event, EventType

        event = Event(
            type=EventType.OBSERVATION,
            source="observer.sedentary",
            data={
                "event_type": "sedentary",
                "confidence": 0.3,  # Below threshold
                "duration_minutes": 125,
            },
        )
        self.engine._on_observation(event)
        self.callback.assert_not_called()

    def test_cooldown_prevents_repeat(self):
        """Cooldown prevents repeated interventions."""
        from archer.core.event_bus import Event, EventType

        event = Event(
            type=EventType.OBSERVATION,
            source="observer.sedentary",
            data={
                "event_type": "sedentary",
                "confidence": 0.95,
                "duration_minutes": 125,
            },
        )

        # First intervention
        self.engine._on_observation(event)
        self.assertEqual(self.callback.call_count, 1)

        # Second should be blocked by cooldown
        self.engine._on_observation(event)
        self.assertEqual(self.callback.call_count, 1)

    def test_mark_ignored_tracks_count(self):
        """mark_ignored increments the ignore counter."""
        self.engine.mark_ignored("trainer", "sedentary")
        self.engine.mark_ignored("trainer", "sedentary")

        # After 2 ignores, the key should have count 2
        key = "trainer:sedentary"
        self.assertEqual(self.engine._ignore_counts.get(key, 0), 2)

    def test_reset_ignores(self):
        """reset_ignores clears the counter for a topic."""
        self.engine.mark_ignored("trainer", "sedentary")
        self.engine.mark_ignored("trainer", "sedentary")
        self.engine.reset_ignores("trainer", "sedentary")

        key = "trainer:sedentary"
        self.assertNotIn(key, self.engine._ignore_counts)

    def test_hunched_posture_triggers_trainer(self):
        """Hunched posture triggers trainer callback."""
        from archer.core.event_bus import Event, EventType

        event = Event(
            type=EventType.OBSERVATION,
            source="observer.posture",
            data={
                "event_type": "posture",
                "confidence": 0.85,
                "is_hunched": True,
                "posture": "sitting",
            },
        )
        self.engine._on_observation(event)
        self.callback.assert_called_once()
        call_args = self.callback.call_args
        self.assertEqual(call_args[0][0], "trainer")


if __name__ == "__main__":
    unittest.main()
