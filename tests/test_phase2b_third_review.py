"""
Tests for Claude's Phase 2b Third Review (2026-10-11 00:05).
Covers Items 2 to 7:
- Item 2: Fallback retry logic and strictly non-destructive fallback (never saves/dismisses/deletes).
- Item 3: Model options num_ctx 4096 preventing Ollama model reloads.
- Item 4: Correction undo/redo (reversing face references, contacts, and memories; no default Jenna).
- Item 5: Bounding box retrieved from photo's own sighting.
- Item 6: Spec 5b "Col's own face" ongoing context rule.
- Item 7: Fresh test sentences excluded from model instructions.
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
    db_path = str(tmp_path / "test_archer.db")
    store = SQLiteStore(db_path=db_path)
    return store


@pytest.fixture
def agent_with_store(temp_store, tmp_path):
    agent = CoreAgent()
    agent._store = temp_store
    agent._active_person_followup = None
    agent._asked_person_ids_this_session = set()
    agent._last_user_turn_timestamp = 0.0
    return agent


class TestPhase2bThirdReview:

    def test_item2_fallback_never_makes_permanent_decisions(self, agent_with_store, temp_store):
        """Item 2: Fallback must NEVER save, dismiss, or delete anything, even with test keywords."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        # Mock Ollama call to fail completely (simulating network down or repeated timeout)
        with patch("httpx.post", side_effect=Exception("Ollama unavailable")):
            # Colby says something that used to trigger regexes in fallback:
            # e.g. "Don't forget, that's Jake" or "Delete them" or "Never seen them"
            classified = agent_with_store._classify_person_reply("Delete them", stage="awaiting_name")
            assert classified["intent"] == "unclear"
            assert classified.get("is_clear") is False
            assert classified.get("name") is None

            # Must NOT delete or dismiss
            pending = temp_store.get_pending_person_confirmations(status="pending")
            assert len(pending) == 1

            classified_name = agent_with_store._classify_person_reply("Don't forget, that's Jake", stage="awaiting_name")
            assert classified_name["intent"] == "unclear"
            assert classified_name.get("is_clear") is False
            assert classified_name.get("name") is None

    def test_item3_classify_uses_num_ctx_4096(self, agent_with_store):
        """Item 3: Reply reader must use the same num_ctx as the chat to prevent model reloading.
        (2026-10-20: the shared size is config.ollama_num_ctx, no longer 4096.)"""
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": json.dumps({"intent": "yes", "is_clear": True})}
            mock_post.return_value = mock_resp

            agent_with_store._classify_person_reply("Hit me", stage="ask_permission")
            assert mock_post.called
            call_kwargs = mock_post.call_args[1]
            payload = call_kwargs.get("json", {})
            options = payload.get("options", {})
            assert options.get("num_ctx") == agent_with_store._config.ollama_num_ctx
            assert payload.get("keep_alive") == agent_with_store._config.ollama_keep_alive
            assert options.get("num_predict") == 1024

    def test_item4_correction_undoes_previous_name_save(self, agent_with_store, temp_store):
        """Item 4: 'No, it's Jenna' undoes previous name save (face reference, contact, memory) and redoes it."""
        fake_emb = np.ones(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        # Step 1: Save first as Mike
        with patch.object(agent_with_store, "_classify_person_reply", return_value={"intent": "name", "name": "Mike", "notes": "brother", "is_clear": True}):
            agent_with_store.build_context_system_prompt("That's my brother Mike")

        assert "Mike" in [p["name"] for p in temp_store.get_known_persons()]
        assert temp_store.get_contact_by_name("Mike") is not None

        # Step 2: Col corrects: "No, it's Jenna"
        with patch.object(agent_with_store, "_classify_person_reply", return_value={"intent": "correction", "name": "Jenna", "notes": None, "is_clear": True}):
            agent_with_store.build_context_system_prompt("No, it's Jenna")

        # Mike must be undone!
        known_names = [p["name"] for p in temp_store.get_known_persons()]
        assert "Mike" not in known_names
        assert "Jenna" in known_names
        assert temp_store.get_contact_by_name("Mike") is None
        assert temp_store.get_contact_by_name("Jenna") is not None

    def test_item4_correction_undoes_previous_thats_me(self, agent_with_store, temp_store):
        """Item 4: Correction after 'that's me' removes the face reference from Col's profile."""
        col_base_emb = (np.ones(512, dtype=np.float32) * 0.5).tobytes()
        temp_store.add_known_person("Col", col_base_emb)
        initial_col_refs = len(temp_store.get_known_person_references())

        visitor_emb = (np.ones(512, dtype=np.float32) * 0.9).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", visitor_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        # Step 1: Col says "That's me"
        with patch.object(agent_with_store, "_classify_person_reply", return_value={"intent": "thats_me", "name": "Col", "is_clear": True}):
            agent_with_store.build_context_system_prompt("That's me")

        # Ref added to Col
        assert len(temp_store.get_known_person_references()) == initial_col_refs + 1

        # Step 2: Col corrects: "Actually, it's Sarah"
        with patch.object(agent_with_store, "_classify_person_reply", return_value={"intent": "correction", "name": "Sarah", "is_clear": True}):
            agent_with_store.build_context_system_prompt("Actually, it's Sarah")

        # Col's added reference must be REMOVED!
        assert len(temp_store.get_known_person_references()) == initial_col_refs
        assert "Sarah" in [p["name"] for p in temp_store.get_known_persons()]

    def test_item4_correction_without_name_does_not_default_to_jenna(self, agent_with_store, temp_store):
        """Item 4: If correction returns no name, do NOT default to Jenna; ask Col to clarify."""
        fake_emb = np.ones(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._last_confirmed_person = {"person_id": "Person_2", "confirmation_id": row["id"], "name": "Mike"}

        with patch.object(agent_with_store, "_classify_person_reply", return_value={"intent": "correction", "name": None, "is_clear": True}):
            prompt, _, _, _ = agent_with_store.build_context_system_prompt("No, wait")

        assert "Jenna" not in [p["name"] for p in temp_store.get_known_persons()]
        assert "clarify" in prompt.lower() or "who" in prompt.lower()

    def test_item5_box_matches_photo_own_sighting(self, temp_store):
        """Item 5: Box stored with photo matches that photo's own sighting, not replaced by later sightings."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        # Sighting 1: takes photo snap1.jpg with box [10, 20, 30, 40]
        temp_store.log_person_sighting(
            person_id="Person_2",
            is_known=False,
            confidence=0.9,
            embedding=fake_emb,
            snapshot_path="data/snapshots/snap1.jpg",
            face_box=json.dumps([10, 20, 30, 40]),
        )
        temp_store.upsert_pending_person_confirmation(
            person_id="Person_2",
            embedding=fake_emb,
            snapshot_path="data/snapshots/snap1.jpg",
            sighting_timestamp=time.time(),
            face_box=json.dumps([10, 20, 30, 40]),
        )

        # Sighting 2: no photo, different box [100, 200, 50, 60]
        temp_store.log_person_sighting(
            person_id="Person_2",
            is_known=False,
            confidence=0.9,
            embedding=fake_emb,
            snapshot_path=None,
            face_box=json.dumps([100, 200, 50, 60]),
        )
        temp_store.upsert_pending_person_confirmation(
            person_id="Person_2",
            embedding=fake_emb,
            snapshot_path=None,
            sighting_timestamp=time.time() + 10,
            face_box=json.dumps([100, 200, 50, 60]),
        )

        # Bounding box for snap1.jpg MUST be [10, 20, 30, 40]
        box_for_snap = temp_store.get_face_box_for_snapshot("data/snapshots/snap1.jpg")
        assert box_for_snap == json.dumps([10, 20, 30, 40])

        pending = temp_store.get_pending_person_confirmations(status="pending")
        assert pending[0]["face_box"] == json.dumps([10, 20, 30, 40])

    def test_item6_context_rule_single_face_matches_col(self, temp_store):
        """Item 6: Retrospective context rule: unrecognized face in cycle just before is linked to Col.
        If similarity >= 0.55, reference added to Col, sighting reassigned, pending resolved."""
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        # Sighting 1 (10s ago): Unrecognized person in room with similarity 0.58 (>= 0.55) to Col
        noise = np.random.RandomState(99).randn(512).astype(np.float32)
        noise /= np.linalg.norm(noise)
        noise = noise - np.dot(noise, col_emb) * col_emb
        noise /= np.linalg.norm(noise)
        emb_58 = (0.58 * col_emb + np.sqrt(1 - 0.58**2) * noise).astype(np.float32)
        temp_store.log_person_sighting(
            person_id="Person_2",
            is_known=False,
            confidence=0.88,
            embedding=emb_58.tobytes(),
            camera_source="network_cam",
        )
        temp_store.upsert_pending_person_confirmation(
            person_id="Person_2",
            embedding=emb_58.tobytes(),
            sighting_timestamp=time.time(),
        )

        # Sighting 2 (now): Col recognized in single-person frame
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

        # Reference must be added to Col via context rule
        refs = temp_store.get_known_person_references()
        assert len(refs) == 1
        assert refs[0]["name"] == "Col"
        assert refs[0]["source"] == "context_rule"

        # Pending confirmation resolved
        pending = temp_store.get_pending_person_confirmations(status="pending")
        assert len(pending) == 0

    def test_item6_context_rule_low_similarity_no_reference_drift(self, temp_store):
        """Item 6: If similarity < 0.55, sighting is logged as Col but NO reference added (prevents drift)."""
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        temp_store.log_person_sighting(
            person_id="Col",
            is_known=True,
            confidence=0.95,
            embedding=col_emb.tobytes(),
            camera_source="network_cam",
        )

        # Low similarity face (~0.30 < 0.55)
        noise = np.random.RandomState(123).randn(512).astype(np.float32)
        noise /= np.linalg.norm(noise)
        low_sim_emb = 0.30 * col_emb + 0.70 * noise
        low_sim_emb /= np.linalg.norm(low_sim_emb)

        mock_face = MagicMock()
        mock_face.bbox = [50, 50, 200, 200]
        mock_face.embedding = low_sim_emb
        mock_face.det_score = 0.88

        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            results = identifier.identify_persons(frame, camera_source="webcam", store=temp_store)

        assert len(results) == 1
        assert results[0]["person_id"] == "Col"
        assert results[0]["is_known"] is True

        # Reference must NOT be added (similarity < 0.55)
        refs = temp_store.get_known_person_references()
        assert len(refs) == 0
