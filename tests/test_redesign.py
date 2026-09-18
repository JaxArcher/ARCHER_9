"""
Tests for ARCHER Observer Redesign (Person Identification & End-of-Day Consolidation).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from archer.memory.sqlite_store import SQLiteStore
from archer.observer.person_id import _cosine_similarity, PersonIdentifier
from archer.memory.consolidation import run_consolidation


class TestCosineSimilarity(unittest.TestCase):
    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        sim = _cosine_similarity(v, v)
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_orthogonal_vectors(self):
        v1 = np.array([1.0, 0.0], dtype=np.float32)
        v2 = np.array([0.0, 1.0], dtype=np.float32)
        sim = _cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, 0.0, places=5)


class TestPersonIDStoreIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = SQLiteStore(db_path=self._tmp.name)

    def tearDown(self):
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_known_person_storage(self):
        emb = np.random.rand(512).astype(np.float32)
        row_id = self.store.add_known_person("Col", emb.tobytes())
        self.assertGreater(row_id, 0)

        persons = self.store.get_known_persons()
        self.assertEqual(len(persons), 1)
        self.assertEqual(persons[0]["name"], "Col")
        loaded_emb = np.frombuffer(persons[0]["embedding"], dtype=np.float32)
        np.testing.assert_allclose(loaded_emb, emb)

    def test_person_sighting_with_embedding(self):
        emb = np.random.rand(512).astype(np.float32)
        row_id = self.store.log_person_sighting(
            person_id="Person_2",
            is_known=False,
            confidence=0.91,
            embedding=emb.tobytes(),
            snapshot_path="data/snapshots/test.jpg",
            camera_source="webcam",
        )
        self.assertGreater(row_id, 0)

        sightings = self.store.get_person_sightings()
        self.assertEqual(len(sightings), 1)
        self.assertEqual(sightings[0]["person_id"], "Person_2")
        self.assertFalse(sightings[0]["is_known"])
        self.assertIsNotNone(sightings[0]["embedding"])


class TestConsolidationPass(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()

        self._store_patcher = patch(
            "archer.memory.consolidation.get_sqlite_store",
            return_value=SQLiteStore(db_path=self._tmp.name),
        )
        self._om_patcher = patch(
            "archer.memory.consolidation.get_openmemory_store"
        )
        self._mock_store = self._store_patcher.start()
        self._mock_om = self._om_patcher.start()

    def tearDown(self):
        self._store_patcher.stop()
        self._om_patcher.stop()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_run_consolidation(self):
        store = self._mock_store.return_value
        obs_id = store.log_observation(
            source="webcam",
            event_type="scene",
            confidence=0.85,
            payload={"description": "Sitting at desk coding Python"},
        )
        store.log_person_sighting(
            person_id="Col",
            is_known=True,
            confidence=0.98,
        )

        obs = store.get_recent_observations(event_type="scene")
        target_date = obs[0]["timestamp"][:10] if obs else None

        success = run_consolidation(target_date=target_date)
        self.assertTrue(success)
        self._mock_om.return_value.add_memory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
