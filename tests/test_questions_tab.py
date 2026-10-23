"""
Tests for ARCHER Spec 5f: "I have questions" tab.
Validates question persistence, person and item question generation, review later/delete actions,
ARCHER_ITEMS_WATCH gating, suppression of chat interruptions, and server API endpoints.
"""

import os
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from archer.memory.sqlite_store import get_sqlite_store
from archer.agents.core_agent import CoreAgent
from archer.core.event_bus import EventType, get_event_bus
import archer.server as server_module


class TestQuestionsCRUD:
    """Test core database CRUD and open count logic."""

    def test_create_and_count(self):
        store = get_sqlite_store()
        initial_open = store.get_open_questions_count()
        q_row = store.create_question(
            source="person",
            text="A new visitor arrived in the living room. Who is this?",
            subject_ref="Person_1",
            context="Living Room Cam",
            image_refs=["/path/to/snap.jpg"],
        )
        assert q_row is not None
        qid = q_row["question_id"]
        assert store.get_open_questions_count() == initial_open + 1

        questions = store.get_questions()
        assert any(q["question_id"] == qid for q in questions)
        q = store.get_question(qid)
        assert q["question_id"] == qid
        assert q["source"] == "person"
        assert q["subject_ref"] == "Person_1"
        assert q["status"] == "open"
        assert "/path/to/snap.jpg" in q["image_refs"]

    def test_review_later_drops_open_count_keeps_card(self):
        """Marking a question 'later' removes it from amber badge count while keeping it in store."""
        store = get_sqlite_store()
        q_row = store.create_question(
            source="general",
            text="Need details on project deadline",
            subject_ref="project_1",
        )
        qid = q_row["question_id"]
        open_before = store.get_open_questions_count()

        # Move to review later
        ok = store.update_question_status(qid, "later")
        assert ok is True
        assert store.get_open_questions_count() == open_before - 1

        # Card is still returned in get_questions()
        q = store.get_question(qid)
        assert q["status"] == "later"

        # Can filter by status
        later_list = store.get_questions(status="later")
        assert any(item["question_id"] == qid for item in later_list)

    def test_answer_and_threads(self):
        store = get_sqlite_store()
        q_row = store.create_question(
            source="person",
            text="Who is this?",
            subject_ref="Person_2",
        )
        qid = q_row["question_id"]

        thread_q = store.add_question_thread(parent_question_id=qid, text="Could this be Mom?", source="archer")
        assert thread_q["thread_id"] == qid

        store.answer_question(qid, answer_text="Mom")
        q = store.get_question(qid)
        assert q["status"] == "answered"
        assert q["answer_text"] == "Mom"

    def test_delete_question(self):
        store = get_sqlite_store()
        q_row = store.create_question(
            source="person",
            text="Mistaken detection",
            subject_ref="Person_fake",
        )
        qid = q_row["question_id"]
        open_before = store.get_open_questions_count()

        ok = store.delete_question(qid)
        assert ok is True
        assert store.get_open_questions_count() == open_before - 1
        q = store.get_question(qid)
        assert q["status"] == "deleted"


class TestPersonAndItemQuestionCreation:
    """Test person and item specific question helpers and gating."""

    def test_create_or_update_person_question_deduplicates(self):
        store = get_sqlite_store()
        open_before = store.get_open_questions_count()

        q1 = store.create_or_update_person_question(
            person_id="Person_5",
            snapshot_path="/media/snap1.jpg",
            context="Office Cam",
        )
        assert q1 is not None
        qid1 = q1["question_id"]
        assert store.get_open_questions_count() == open_before + 1

        # Second sighting of same Person_5 updates image_refs without creating a duplicate question
        q2 = store.create_or_update_person_question(
            person_id="Person_5",
            snapshot_path="/media/snap2.jpg",
            context="Office Cam",
        )
        assert q2["question_id"] == qid1
        assert store.get_open_questions_count() == open_before + 1

        q_final = store.get_question(qid1)
        assert "/media/snap1.jpg" in q_final["image_refs"]
        assert "/media/snap2.jpg" in q_final["image_refs"]

    def test_item_questions_stay_off_when_watch_disabled(self, monkeypatch):
        """Spec: item questions stay off while ARCHER_ITEMS_WATCH=false."""
        store = get_sqlite_store()
        open_before = store.get_open_questions_count()

        monkeypatch.setenv("ARCHER_ITEMS_WATCH", "false")
        q = store.create_or_update_item_question(
            item_id="item_99",
            item={"place": "Desk", "image_path": "/media/item.jpg"},
        )
        assert q is None
        assert store.get_open_questions_count() == open_before

        # When explicitly enabled, item question is created
        monkeypatch.setenv("ARCHER_ITEMS_WATCH", "true")
        q_enabled = store.create_or_update_item_question(
            item_id="item_99",
            item={"place": "Desk", "image_path": "/media/item.jpg"},
        )
        assert q_enabled is not None
        assert store.get_open_questions_count() == open_before + 1

    def test_resolve_pending_person_auto_answers_question(self):
        """When confirming a person identity, open question cards for that person are auto-answered."""
        store = get_sqlite_store()
        q = store.create_or_update_person_question(
            person_id="Person_8",
            snapshot_path="/media/col_face.jpg",
            context="Desk Cam",
        )
        qid = q["question_id"]
        assert store.get_question(qid)["status"] == "open"

        # Resolving pending person confirmation resolves the open question card
        store.resolve_pending_person_confirmation_by_person_id("Person_8", status="confirmed", confirmed_name="Col")
        q_after = store.get_question(qid)
        assert q_after["status"] == "answered"
        assert q_after["answer_text"] == "Col"


class TestChatSuppression:
    """Ensure no ambient photos or questions pollute chat (Spec 5f / 16:35 addendum)."""

    def test_no_artifact_push_event_on_person_snapshot(self):
        agent = CoreAgent()
        published_events = []
        get_event_bus().subscribe(EventType.ARTIFACT_PUSH, lambda ev: published_events.append(ev))

        # Push person snapshot
        agent._push_person_snapshot("Person_10", "/tmp/face.jpg")
        # Should NOT emit ARTIFACT_PUSH to chat
        assert len(published_events) == 0

    def test_conversational_followup_suppressed_to_questions_tab(self):
        agent = CoreAgent()
        # Normal conversation does not produce ambient follow-up check-in interrupts
        res = agent._handle_conversational_person_followup("how are you doing")
        assert res is None


class TestQuestionsAPI:
    """Test FastAPI endpoints for Questions tab."""

    def test_questions_endpoints_flow(self):
        client = TestClient(server_module.app)
        store = get_sqlite_store()

        with patch("archer.server._get_store", return_value=store):
            # Create question in store
            q = store.create_question(
                source="person",
                text="Unrecognized person in office",
                subject_ref="Person_3",
                context="Office Cam",
            )
            qid = q["question_id"]

            # 1. GET /api/questions
            res = client.get("/api/questions")
            assert res.status_code == 200
            data = res.json()
            assert data["open_count"] >= 1
            assert any(item["question_id"] == qid or item.get("id") == qid for item in data["questions"])

            # 2. POST /api/questions/{qid}/later
            later_res = client.post(f"/api/questions/{qid}/later")
            assert later_res.status_code == 200
            assert later_res.json()["success"] is True

            # 3. POST /api/questions/{qid}/respond
            resp_res = client.post(f"/api/questions/{qid}/respond", json={"response": "That is Alice"})
            assert resp_res.status_code == 200
            assert resp_res.json()["success"] is True

            # 4. POST /api/questions/{qid}/delete
            del_res = client.post(f"/api/questions/{qid}/delete")
            assert del_res.status_code == 200
            assert del_res.json()["success"] is True
