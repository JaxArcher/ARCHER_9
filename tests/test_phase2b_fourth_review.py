"""
Tests for Claude's Phase 2b Fourth Review (2026-10-11 02:20).
Covers Item 6 Points 1 to 4 and Minor Items:
- Point 1: Col and a visitor seen in recent frames, then a frame with only the visitor's face:
           the visitor must NOT be logged as Col.
- Point 2: A visitor with several sightings, then Col alone: the visitor's record
           must NOT be resolved.
- Point 3: A reference is added at the new bar (e.g. 0.45 <= similarity < 0.55),
           and isn't added twice for the same face.
- Minor 1: "Skip this one for now" moves on to the next person and leaves this one
           waiting (does NOT pause the review for 3 hours).
- Minor 2: "Who was it?" in reply to "is now a good time?" reads as yes (proceeds
           to show snapshot, does NOT pause for 3 hours).
"""

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from archer.memory.sqlite_store import SQLiteStore
from archer.observer.person_id import PersonIdentifier
from archer.agents.core_agent import CoreAgent


@pytest.fixture
def temp_store(tmp_path):
    """Isolated SQLite store instance in a temporary test directory."""
    db_path = str(tmp_path / "test_archer_fourth.db")
    store = SQLiteStore(db_path=db_path)
    return store


@pytest.fixture
def agent_with_store(temp_store):
    agent = CoreAgent()
    agent._store = temp_store
    agent._active_person_followup = None
    agent._asked_person_ids_this_session = set()
    agent._last_user_turn_timestamp = 0.0
    return agent


class TestPhase2bFourthReview:

    def test_point1_visitor_alone_after_col_and_visitor_not_logged_as_col(self, temp_store):
        """
        Point 1 & Point 4: Col and a visitor seen in recent frames, then a frame with only the
        visitor's face: the visitor must NOT be logged as Col.
        """
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        visitor_emb = np.random.RandomState(99).randn(512).astype(np.float32)
        visitor_emb /= np.linalg.norm(visitor_emb)
        # Ensure visitor is orthogonal/distinct from Col
        visitor_emb = visitor_emb - np.dot(visitor_emb, col_emb) * col_emb
        visitor_emb /= np.linalg.norm(visitor_emb)

        # 30 seconds ago: Col was seen on network_cam
        temp_store.log_person_sighting(
            person_id="Col",
            is_known=True,
            confidence=0.95,
            embedding=col_emb.tobytes(),
            camera_source="network_cam",
        )

        # 15 seconds ago: Visitor was seen on network_cam
        temp_store.log_person_sighting(
            person_id="Person_2",
            is_known=False,
            confidence=0.85,
            embedding=visitor_emb.tobytes(),
            camera_source="network_cam",
        )
        temp_store.upsert_pending_person_confirmation(
            person_id="Person_2",
            embedding=visitor_emb.tobytes(),
            sighting_timestamp=time.time() - 15,
        )

        # Now: Frame contains ONLY the visitor's face (Col's face is turned away)
        mock_face = MagicMock()
        mock_face.bbox = [50, 50, 200, 200]
        mock_face.embedding = visitor_emb
        mock_face.det_score = 0.90

        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            results = identifier.identify_persons(frame, camera_source="network_cam", store=temp_store)

        assert len(results) == 1
        # The visitor must NOT be logged as Col!
        assert results[0]["person_id"] != "Col"
        assert results[0]["is_known"] is False
        assert results[0]["person_id"] == "Person_2"

    def test_point2_visitor_with_several_sightings_not_resolved_by_col_alone(self, temp_store):
        """
        Point 2 & Point 4: A visitor with several sightings, then Col alone: the visitor's record
        must NOT be resolved.
        """
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        visitor_emb = np.random.RandomState(77).randn(512).astype(np.float32)
        visitor_emb /= np.linalg.norm(visitor_emb)
        visitor_emb = visitor_emb - np.dot(visitor_emb, col_emb) * col_emb
        visitor_emb /= np.linalg.norm(visitor_emb)

        # Visitor Person_2 has several sightings (e.g. 3 sightings over 2 minutes)
        for i in range(3):
            temp_store.log_person_sighting(
                person_id="Person_2",
                is_known=False,
                confidence=0.88,
                embedding=visitor_emb.tobytes(),
                camera_source="network_cam",
            )
        temp_store.upsert_pending_person_confirmation(
            person_id="Person_2",
            embedding=visitor_emb.tobytes(),
            sighting_timestamp=time.time() - 20,
        )

        # Verify Person_2 is pending
        pending_before = temp_store.get_pending_person_confirmations(status="pending")
        assert len(pending_before) == 1
        assert pending_before[0]["person_id"] == "Person_2"

        # Now: Visitor just left, Col is seen alone on camera (single-face frame of Col)
        mock_face = MagicMock()
        mock_face.bbox = [50, 50, 200, 200]
        mock_face.embedding = col_emb
        mock_face.det_score = 0.95

        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            results = identifier.identify_persons(frame, camera_source="network_cam", store=temp_store)

        assert len(results) == 1
        assert results[0]["person_id"] == "Col"
        assert results[0]["is_known"] is True

        # Person_2's record must NOT be resolved as Col!
        pending_after = temp_store.get_pending_person_confirmations(status="pending")
        assert len(pending_after) == 1
        assert pending_after[0]["person_id"] == "Person_2"

        # Person_2's sightings must still belong to Person_2
        sightings = temp_store.get_person_sightings(limit=10)
        p2_sightings = [s for s in sightings if s["person_id"] == "Person_2"]
        assert len(p2_sightings) == 3

    def test_point3_reference_added_at_new_bar_and_not_added_twice(self, temp_store):
        """
        Point 3 & Point 4: A reference is added at the new bar (e.g. 0.48, between 0.45 and 0.55),
        and isn't added twice for the same face.
        """
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        # Col has been the only face seen recently on network_cam
        temp_store.log_person_sighting(
            person_id="Col",
            is_known=True,
            confidence=0.95,
            embedding=col_emb.tobytes(),
            camera_source="network_cam",
        )

        # Generate an off-angle face of Col with similarity 0.48 (between 0.45 and 0.55)
        noise = np.random.RandomState(101).randn(512).astype(np.float32)
        noise /= np.linalg.norm(noise)
        noise = noise - np.dot(noise, col_emb) * col_emb
        noise /= np.linalg.norm(noise)
        target_sim = 0.48
        off_angle_emb = (target_sim * col_emb + np.sqrt(1 - target_sim**2) * noise).astype(np.float32)

        actual_sim = float(np.dot(col_emb, off_angle_emb))
        assert 0.47 <= actual_sim <= 0.49

        mock_face = MagicMock()
        mock_face.bbox = [50, 50, 200, 200]
        mock_face.embedding = off_angle_emb
        mock_face.det_score = 0.88

        # Sighting 1: Off-angle face appears in single-face frame
        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            results1 = identifier.identify_persons(frame, camera_source="network_cam", store=temp_store)

        assert len(results1) == 1
        assert results1[0]["person_id"] == "Col"
        assert results1[0]["is_known"] is True

        # Reference must be added at the new bar (0.48 >= 0.45)
        refs = temp_store.get_known_person_references()
        assert len(refs) == 1
        assert refs[0]["name"] == "Col"
        assert refs[0]["source"] == "context_rule"

        # Check action audit log has plain language sentence
        actions = temp_store.get_action_audit(limit=10)
        assert len(actions) >= 1
        assert any("Col" in a["description"] for a in actions)

        # Sighting 2: Same off-angle face appears again in next cycle
        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            results2 = identifier.identify_persons(frame, camera_source="network_cam", store=temp_store)

        assert len(results2) == 1
        assert results2[0]["person_id"] == "Col"

        # Must NOT add duplicate reference for the same face!
        refs_after = temp_store.get_known_person_references()
        assert len(refs_after) == 1

    def test_minor1_skip_moves_to_next_person_without_pausing(self, agent_with_store, temp_store):
        """
        Minor item 1: 'Skip this one for now' moves on to the next person and leaves this one waiting,
        without pausing check-ins for 3 hours.
        """
        fake_emb1 = np.ones(512, dtype=np.float32).tobytes()
        fake_emb2 = (np.ones(512, dtype=np.float32) * 2).tobytes()

        # Two eligible waiting people: Person_2 and Person_3
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb1, sighting_timestamp=time.time() - 300)
        temp_store.upsert_pending_person_confirmation("Person_3", fake_emb2, sighting_timestamp=time.time() - 200)

        # Update their durations to >= 120s so both are eligible
        conn = temp_store._get_connection()
        conn.execute("UPDATE pending_person_confirmations SET total_duration_seconds = 150.0")
        conn.commit()
        conn.close()

        row2 = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row2["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-11 10:00:00",
        }

        # Mock classifier returning intent: "skip" for "Skip this one for now"
        with patch.object(agent_with_store, "_classify_person_reply", return_value={"intent": "skip", "is_clear": True}):
            prompt = agent_with_store.build_context_system_prompt("Skip this one for now")

        # 1. Must move to next person (Person_3)
        assert agent_with_store._active_person_followup is not None
        assert agent_with_store._active_person_followup["person_id"] == "Person_3"

        # 2. Person_2 must remain pending (not dismissed, not deleted)
        pending = temp_store.get_pending_person_confirmations(status="pending")
        pending_ids = [p["person_id"] for p in pending]
        assert "Person_2" in pending_ids

        # 3. Must NOT be paused for 3 hours!
        assert agent_with_store._is_checkin_paused() is False

    def test_minor2_who_was_it_reads_as_yes(self, agent_with_store, temp_store):
        """
        Minor item 2: 'Who was it?' in reply to 'is now a good time?' counts as yes (proceeds
        to show snapshot card, does not pause for 3 hours).
        """
        fake_emb = np.ones(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time() - 300)
        conn = temp_store._get_connection()
        conn.execute("UPDATE pending_person_confirmations SET total_duration_seconds = 150.0")
        conn.commit()
        conn.close()

        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "ask_permission",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-11 10:00:00",
        }

        with patch.object(agent_with_store, "_push_person_snapshot") as mock_push:
            # Col replies "Who was it?"
            # Under current code without the fix, "Who was it?" falls back/classifies as unrelated,
            # returns None, sets active_followup to None, and pauses for 3 hours.
            prompt = agent_with_store.build_context_system_prompt("Who was it?")

        # 1. Must advance to awaiting_name
        assert agent_with_store._active_person_followup is not None
        assert agent_with_store._active_person_followup["stage"] == "awaiting_name"

        # 2. Must not be paused
        assert agent_with_store._is_checkin_paused() is False

        # 3. Snapshot card must have been pushed
        assert mock_push.called
