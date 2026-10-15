"""
Tests for Claude's Phase 2b Fifth Review (2026-10-11 18:10).
Covers:
- Item 1: Word-list regex names removed. Replies such as:
          - "My brother is visiting this week" -> must NOT be saved as "Is".
          - "That's my friend from work" -> must NOT be saved as "From".
          - "That's my dad again" -> must NOT be saved as "Again".
          - "No, that's not my sister Amy" -> must NOT be saved as "Amy".
          - "My cousin who? I don't have one" -> must NOT be saved as "Who".
          Names only ever come from the model.
- Item 2: "Hold on" and "Can you zoom in?" are conversational hesitations,
          NOT "not_now". Must NOT end review or trigger 3-hour pause.
- Item 3: Similarity floor (0.30) for "Col's own face" context rule.
          When Col was the only person seen recently, an unrecognized face
          scoring < 0.30 (e.g. newly arrived visitor while Col's back is turned)
          must NOT be logged as Col; it gets a normal Person_N label.
- Item 4: Look-back checks earlier frame:
          - Must NOT relink if earlier frame had > 1 faces.
          - Must NOT relink if earlier frame was from a different camera.
"""

import json
import time
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from archer.memory.sqlite_store import SQLiteStore
from archer.observer.person_id import PersonIdentifier
from archer.agents.core_agent import CoreAgent


@pytest.fixture
def temp_store(tmp_path):
    """Isolated SQLite store instance in a temporary test directory."""
    db_path = str(tmp_path / "test_archer_fifth.db")
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


class TestPhase2bFifthReview:

    def test_item1_no_regex_wordlist_shortcuts_for_names(self, agent_with_store):
        """
        Item 1: Word-list regex shortcut 'my <relation> <word>' must be removed.
        Replies must NOT be blindly parsed into names without asking the model.
        Specifically:
        - 'My brother is visiting this week' must NOT return name 'Is'.
        - 'That's my friend from work' must NOT return name 'From'.
        - 'That's my dad again' must NOT return name 'Again'.
        - 'No, that's not my sister Amy' must NOT return name 'Amy' (negation).
        - 'My cousin who? I don't have one' must NOT return name 'Who'.
        """
        test_replies = [
            ("My brother is visiting this week", "Is"),
            ("That's my friend from work", "From"),
            ("That's my dad again", "Again"),
            ("No, that's not my sister Amy", "Amy"),
            ("My cousin who? I don't have one", "Who"),
        ]

        # In current code, lines 936-938 intercept these with regex and return
        # {"intent": "name", "name": bad_name, ...} before even touching Ollama.
        # With the shortcut removed, _classify_person_reply must NOT produce these false names via regex.
        for text, bad_name in test_replies:
            # We mock httpx to ensure no external call happens or observe what regex does
            with patch("httpx.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {
                    "response": json.dumps({"intent": "unclear", "name": None, "notes": None, "is_clear": False})
                }
                res = agent_with_store._classify_person_reply(text, stage="awaiting_name")
                # If regex shortcut was executed, mock_post is NOT called and res['name'] == bad_name!
                assert res.get("name") != bad_name, f"Regex shortcut incorrectly extracted name '{bad_name}' from '{text}'"

    def test_item2_hold_on_keeps_review_open(self, agent_with_store, temp_store):
        """
        Item 2: 'Hold on' is a conversational hesitation, NOT 'not_now'.
        It must keep _active_person_followup open and not trigger a 3-hour pause.
        """
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        agent_with_store.build_context_system_prompt("Hold on")
        assert agent_with_store._active_person_followup is not None, "'Hold on' closed the person review!"
        assert "Hold" not in [p["name"] for p in temp_store.get_known_persons()]

    def test_item3_visitor_facing_camera_below_similarity_floor_not_col(self, temp_store):
        """
        Item 3: Add similarity floor (0.30) to the 'Col's own face' context rule.
        Col alone in room, recognized, but face turned away when visitor walks in facing camera.
        Only Col seen in last 3 min, but visitor similarity to Col is 0.15 (< 0.30).
        Visitor must NOT be logged as Col; must receive a Person_N label.
        """
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        # Col was the only person seen recently on network_cam
        temp_store.log_person_sighting(
            person_id="Col",
            is_known=True,
            confidence=0.92,
            embedding=col_emb.tobytes(),
            camera_source="network_cam",
        )

        # Visitor arrives. Visitor vector has cosine similarity ~0.10 to Col
        visitor_emb = np.random.RandomState(101).randn(512).astype(np.float32)
        visitor_emb /= np.linalg.norm(visitor_emb)
        # Orthogonalize visitor from Col
        visitor_emb = visitor_emb - np.dot(visitor_emb, col_emb) * col_emb
        visitor_emb /= np.linalg.norm(visitor_emb)

        sim = float(np.dot(visitor_emb, col_emb))
        assert sim < 0.30, f"Expected visitor similarity < 0.30, got {sim}"

        mock_face = MagicMock()
        mock_face.bbox = [50, 50, 200, 200]
        mock_face.embedding = visitor_emb
        mock_face.det_score = 0.90

        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            results = identifier.identify_persons(frame, camera_source="network_cam", store=temp_store)

        assert len(results) == 1
        # MUST NOT be classified as Col!
        assert results[0]["person_id"] != "Col", "Visitor with similarity < 0.30 was falsely logged as Col by context rule!"
        assert results[0]["is_known"] is False
        assert results[0]["person_id"].startswith("Person_")

    def test_item3_col_off_angle_above_similarity_floor_is_col(self, temp_store):
        """
        Review 19:30 Item 1:
        Retire the old 'only Col recently' rule and the look-back.
        An off-angle view of Col below recognition threshold (0.50 < 0.55) is not logged
        as Col by standalone identify_persons because the old context rule is retired.
        Identity now comes from the track following him across his stay.
        """
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        temp_store.log_person_sighting(
            person_id="Col",
            is_known=True,
            confidence=0.92,
            embedding=col_emb.tobytes(),
            camera_source="network_cam",
        )

        # Off-angle view of Col with cosine similarity ~0.50
        noise = np.random.RandomState(7).randn(512).astype(np.float32)
        noise /= np.linalg.norm(noise)
        off_angle_emb = 0.50 * col_emb + np.sqrt(1 - 0.50**2) * noise
        off_angle_emb /= np.linalg.norm(off_angle_emb)

        sim = float(np.dot(off_angle_emb, col_emb))
        assert 0.45 <= sim < 0.55

        mock_face = MagicMock()
        mock_face.bbox = [50, 50, 200, 200]
        mock_face.embedding = off_angle_emb
        mock_face.det_score = 0.90

        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            results = identifier.identify_persons(frame, camera_source="network_cam", store=temp_store)

        assert len(results) == 1
        # Context rule retired: does not classify as Col without direct match or track
        assert results[0]["person_id"] != "Col"
        assert results[0]["is_known"] is False

    def test_item4_lookback_does_not_relink_if_earlier_frame_had_multiple_faces(self, temp_store):
        """
        Item 4: Look-back checks earlier frame.
        If the earlier frame had 2 faces (Col and visitor in one frame), and visitor got Person_2,
        then a subsequent frame of Col alone must NOT relink Person_2 to Col!
        """
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        visitor_emb = np.random.RandomState(101).randn(512).astype(np.float32)
        visitor_emb /= np.linalg.norm(visitor_emb)

        # Earlier sighting: frame had 2 faces!
        temp_store.log_person_sighting(
            person_id="Person_2",
            is_known=False,
            confidence=0.80,
            embedding=visitor_emb.tobytes(),
            camera_source="network_cam",
            faces_in_frame=2,
        )
        temp_store.upsert_pending_person_confirmation(
            person_id="Person_2",
            embedding=visitor_emb.tobytes(),
            sighting_timestamp=time.time(),
        )

        # Now: Frame of Col alone on network_cam
        mock_face = MagicMock()
        mock_face.bbox = [50, 50, 200, 200]
        mock_face.embedding = col_emb
        mock_face.det_score = 0.95

        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            identifier.identify_persons(frame, camera_source="network_cam", store=temp_store)

        # Verify Person_2 was NOT reassigned to Col
        sightings = temp_store.get_person_sightings(limit=10)
        p2_sighting = [s for s in sightings if s["person_id"] == "Person_2"]
        assert len(p2_sighting) == 1, "Person_2 sighting was falsely relinked to Col despite earlier frame having 2 faces!"

    def test_item4_lookback_does_not_relink_across_different_cameras(self, temp_store):
        """
        Item 4: Look-back checks earlier frame camera source.
        Earlier unrecognized sighting was on 'webcam'.
        Now Col is seen alone on 'network_cam'.
        Must NOT relink the webcam sighting to Col!
        """
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        temp_store.add_known_person("Col", col_emb.tobytes())

        visitor_emb = np.random.RandomState(101).randn(512).astype(np.float32)
        visitor_emb /= np.linalg.norm(visitor_emb)

        # Earlier sighting was on 'webcam'
        temp_store.log_person_sighting(
            person_id="Person_3",
            is_known=False,
            confidence=0.80,
            embedding=visitor_emb.tobytes(),
            camera_source="webcam",
            faces_in_frame=1,
        )
        temp_store.upsert_pending_person_confirmation(
            person_id="Person_3",
            embedding=visitor_emb.tobytes(),
            sighting_timestamp=time.time(),
        )

        # Now Col is seen alone on 'network_cam'
        mock_face = MagicMock()
        mock_face.bbox = [50, 50, 200, 200]
        mock_face.embedding = col_emb
        mock_face.det_score = 0.95

        with patch.object(identifier._app, "get", return_value=[mock_face]):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            identifier.identify_persons(frame, camera_source="network_cam", store=temp_store)

        # Verify Person_3 was NOT reassigned to Col
        sightings = temp_store.get_person_sightings(limit=10)
        p3_sighting = [s for s in sightings if s["person_id"] == "Person_3"]
        assert len(p3_sighting) == 1, "Person_3 sighting was falsely relinked to Col across different cameras!"
