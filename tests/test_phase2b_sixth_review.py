"""
Tests for Claude's Phase 2b Sixth Review (2026-10-12 09:15).
Covers:
- Item 1: A relationship with no name is NOT ignored.
          "That's my dad" and "It's my neighbor" must keep the note and ask for the name.
          If Col says they have no name to give ("just Dad"), save them as that.
          Must not treat relationships as non-answers or auto-close after two turns.
- Item 2: A negation ("That's not Amy", "That isn't Bob") must NOT dismiss the face.
          Treat it as unclear and ask who it is.
          Only a clear "I don't know them" or "stranger" dismisses.
- Item 3: Prompt instructions must NOT contain the exact sentences from the review tables.
"""

import inspect
import json
import time
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from archer.memory.sqlite_store import SQLiteStore
from archer.agents.core_agent import CoreAgent


@pytest.fixture
def temp_store(tmp_path):
    """Isolated SQLite store instance in a temporary test directory."""
    db_path = str(tmp_path / "test_archer_sixth.db")
    store = SQLiteStore(db_path=db_path)
    return store


@pytest.fixture
def agent_with_store(temp_store):
    mock_om = MagicMock()
    mock_om.add_memory.return_value = "mock-test-mem-id"
    agent = CoreAgent(store=temp_store, om_store=mock_om)
    agent._active_person_followup = None
    agent._asked_person_ids_this_session = set()
    agent._last_user_turn_timestamp = 0.0
    return agent


class TestPhase2bSixthReview:

    def test_item1_relationship_without_name_asks_for_name_and_does_not_ignore(self, agent_with_store, temp_store):
        """
        Item 1: When Col says 'That's my dad', the handler must NOT treat it as a non-answer
        (returning None and incrementing non_answer_turns_count). It must keep the note and
        instruct the model to ask for their name.
        """
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_3", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_3",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "non_answer_turns_count": 0,
        }

        # Col says 'That's my dad'
        instr = agent_with_store._handle_conversational_person_followup("That's my dad")
        # In current code, this returns None because name is None, and non_answer_turns_count becomes 1!
        assert instr is not None, "Relationship 'That's my dad' was ignored and returned no prompt instruction!"
        assert "dad" in instr.lower() or "name" in instr.lower()
        # Verify followup is still active and notes are preserved
        assert agent_with_store._active_person_followup is not None
        assert agent_with_store._active_person_followup.get("pending_notes") is not None
        assert any(w in agent_with_store._active_person_followup["pending_notes"].lower() for w in ("dad", "father"))

    def test_item1_relationship_followed_by_just_dad_saves_as_dad(self, agent_with_store, temp_store):
        """
        Item 1: If Col says they have no name to give ('just Dad'), save them as that.
        """
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_3", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_3",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "pending_notes": "dad",
            "non_answer_turns_count": 0,
        }

        instr = agent_with_store._handle_conversational_person_followup("just Dad")
        # In current code, 'Just Dad' returns name: None, notes: 'Dad', which drops into Branch 7 and closes
        assert instr is not None, "'just Dad' was ignored and returned no instruction!"
        saved_persons = temp_store.get_known_persons()
        names = [p["name"] for p in saved_persons]
        assert "Dad" in names, f"Expected 'Dad' to be saved as known person, found {names}"

    def test_item2_negation_does_not_dismiss_face_treated_as_unclear(self, agent_with_store, temp_store):
        """
        Item 2: 'No, that's not my sister Amy' or 'That isn't Bob' must NOT dismiss the face for good.
        It must be treated as unclear and ask who it is.
        Only a clear 'I don't know them' or 'stranger' dismisses.
        """
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_4", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_4",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "non_answer_turns_count": 0,
        }

        # Check classification intent
        classified = agent_with_store._classify_person_reply("No, that's not my sister Amy", stage="awaiting_name")
        # In current code, this returns intent: 'dont_know'
        assert classified.get("intent") != "dont_know", "Negation 'not my sister Amy' was classified as dont_know!"

        # Check state machine handling
        instr = agent_with_store._handle_conversational_person_followup("No, that's not my sister Amy")
        # In current code, 'dont_know' resolves row as 'dismissed' and removes active followup
        pending_rows = temp_store.get_pending_person_confirmations(status="pending")
        assert len(pending_rows) == 1, "Negation caused pending face to be dismissed!"
        assert pending_rows[0]["status"] == "pending"

    def test_prompt_examples_do_not_contain_review_table_sentences(self, agent_with_store):
        """
        Item 2 & Review 6: The prompt instructions must NOT contain the exact sentences from
        Claude's review tables.
        """
        src = inspect.getsource(agent_with_store._classify_person_reply)
        review_sentences = [
            "my brother is visiting this week",
            "that's my friend from work",
            "that's my dad again",
            "No, that's not my sister Amy",
            "That isn't Bob",
            "Hold on, let me put my glasses on",
            "Can you pull up a clearer shot?",
            "Honestly I think that's my neighbor Dave",
            "Sarah, she works with me",
            "My brother Mike",
        ]
        found = [s for s in review_sentences if s.lower() in src.lower()]
        assert not found, f"Prompt instructions still contain review table sentences: {found}"

    def test_item_b_no_just_or_only_word_shortcut(self, agent_with_store, temp_store):
        """
        Item B: 'Just checking the weather today' and 'Only one thing, what time is it?'
        must NOT extract 'Checking' or 'One' as a name. Names only ever come from the model.
        """
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_5", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_5",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "non_answer_turns_count": 0,
        }

        # User says "Just checking the weather today"
        agent_with_store.build_context_system_prompt("Just checking the weather today")
        known_names = [p["name"] for p in temp_store.get_known_persons()]
        assert "Checking" not in known_names
        assert len(known_names) == 0

        # User says "Only one thing, what time is it?"
        agent_with_store._active_person_followup["non_answer_turns_count"] = 0
        agent_with_store.build_context_system_prompt("Only one thing, what time is it?")
        known_names = [p["name"] for p in temp_store.get_known_persons()]
        assert "One" not in known_names
        assert len(known_names) == 0

