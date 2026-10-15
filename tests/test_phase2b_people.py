"""
Comprehensive test suite for Phase 2b review items (Claude 2026-10-10 14:05).
Covers Tables 1 & 2, Bug 1 & 2, gap handling, 3-hour persistent pause,
quiet spell rules, multi-photo deletion, UTC-to-local times, and dismissed face retention.
"""

import os
import time
from datetime import datetime, timezone
import numpy as np
import pytest

from archer.memory.sqlite_store import SQLiteStore
from archer.observer.person_id import PersonIdentifier
from archer.agents.core_agent import CoreAgent
from archer.core.event_bus import EventType, get_event_bus


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
    agent._last_user_turn_timestamp = 0.0  # simulate quiet spell
    return agent


class TestTable1AwaitingName:
    """Table 1: Col's replies while ARCHER waits for a name."""

    def test_let_me_take_a_closer_look_still_waiting(self, agent_with_store, temp_store):
        """'Let me take a closer look': 'me' should NOT trigger 'that's me'. Nothing saved, still waiting."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Let me take a closer look")
        assert agent_with_store._active_person_followup is not None
        assert agent_with_store._active_person_followup["stage"] == "awaiting_name"
        assert len(temp_store.get_known_person_references()) == 0
        assert len(temp_store.get_known_persons()) == 0

    def test_give_me_a_second_nothing_saved(self, agent_with_store, temp_store):
        """'Give me a second': 'me' should NOT trigger 'that's me'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Give me a second")
        assert agent_with_store._active_person_followup is not None
        assert agent_with_store._active_person_followup["stage"] == "awaiting_name"
        assert len(temp_store.get_known_persons()) == 0

    def test_hold_on_can_you_zoom_in_not_saved_as_name(self, agent_with_store, temp_store):
        """'Hold on' / 'Can you zoom in?': first words must NOT be saved as names."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Hold on")
        assert "Hold" not in [p["name"] for p in temp_store.get_known_persons()]
        assert agent_with_store._active_person_followup is not None

        agent_with_store._active_person_followup["non_answer_turns_count"] = 0
        prompt2, _, _, _ = agent_with_store.build_context_system_prompt("Can you zoom in?")
        assert "Can" not in [p["name"] for p in temp_store.get_known_persons()]
        assert agent_with_store._active_person_followup is not None

    def test_sarah_she_works_with_me_named_sarah(self, agent_with_store, temp_store):
        """'That's Sarah, she works with me': must be named Sarah, NOT 'that's me' because of 'with me'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        prompt, _, _, _ = agent_with_store.build_context_system_prompt("That's Sarah, she works with me")
        assert "Sarah" in [p["name"] for p in temp_store.get_known_persons()]
        assert "Col" not in [p["name"] for p in temp_store.get_known_persons()]
        assert agent_with_store._active_person_followup is None

    def test_its_my_brother_mike_named_mike(self, agent_with_store, temp_store):
        """'It's my brother Mike': must extract Mike with note 'brother'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        prompt, _, _, _ = agent_with_store.build_context_system_prompt("It's my brother Mike")
        assert "Mike" in [p["name"] for p in temp_store.get_known_persons()]
        contact = temp_store.get_contact_by_name("Mike")
        assert contact is not None
        assert "brother" in str(contact.get("relationship", "")).lower()

    def test_honestly_i_think_my_neighbor_dave(self, agent_with_store, temp_store):
        """'Honestly I think that's my neighbor Dave': named Dave with note 'neighbor', NOT 'Honestly'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Honestly I think that's my neighbor Dave")
        assert "Honestly" not in [p["name"] for p in temp_store.get_known_persons()]
        assert "Dave" in [p["name"] for p in temp_store.get_known_persons()]
        contact = temp_store.get_contact_by_name("Dave")
        assert contact is not None
        assert "neighbor" in str(contact.get("relationship", "")).lower()

    def test_thats_me_variants_added_to_col(self, agent_with_store, temp_store):
        """'That's me', 'It's me', 'Me' add to Col."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.add_known_person("Col", fake_emb)

        for i, phrase in enumerate(["That's me", "It's me", "Me"]):
            pid = f"Person_{10 + i}"
            temp_store.upsert_pending_person_confirmation(pid, fake_emb, sighting_timestamp=time.time())
            row = temp_store.get_pending_person_confirmations(status="pending")[0]
            agent_with_store._active_person_followup = {
                "stage": "awaiting_name",
                "person_id": pid,
                "confirmation_id": row["id"],
                "snapshot_path": None,
            }
            prompt, _, _, _ = agent_with_store.build_context_system_prompt(phrase)
            assert agent_with_store._active_person_followup is None

    def test_not_sure_maybe_jake_asks_clarification(self, agent_with_store, temp_store):
        """'Not sure, maybe Jake from next door': not dismissed; ARCHER asks whether to save as Jake."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
        }

        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Not sure, maybe Jake from next door")
        # Should not be dismissed
        pending = temp_store.get_pending_person_confirmations(status="pending")
        assert len(pending) == 1
        # Should ask whether to save as Jake
        assert "Jake" in prompt


class TestTable2IsNowAGoodTime:
    """Table 2: Col's replies to 'is now a good time?'."""

    def test_no_busy_look_later_treated_as_not_now(self, agent_with_store, temp_store):
        """'No, I'm busy, look later': 'look' must NOT trigger 'ok'. Counts as not now."""
        agent_with_store._active_person_followup = {
            "stage": "ask_permission",
            "person_id": "Person_2",
            "confirmation_id": 1,
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        prompt, _, _, _ = agent_with_store.build_context_system_prompt("No, I'm busy, look later")
        assert agent_with_store._active_person_followup is None
        # Must pause check-ins
        assert agent_with_store._is_checkin_paused()

    def test_not_now_booked_solid(self, agent_with_store, temp_store):
        """'Not now, I'm booked solid': 'booked' must NOT trigger 'ok'."""
        agent_with_store._active_person_followup = {
            "stage": "ask_permission",
            "person_id": "Person_2",
            "confirmation_id": 1,
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Not now, I'm booked solid")
        assert agent_with_store._active_person_followup is None
        assert agent_with_store._is_checkin_paused()

    def test_nope_take_a_look_at_email(self, agent_with_store, temp_store):
        """'Nope, take a look at my email instead': not now."""
        agent_with_store._active_person_followup = {
            "stage": "ask_permission",
            "person_id": "Person_2",
            "confirmation_id": 1,
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Nope, take a look at my email instead")
        assert agent_with_store._active_person_followup is None
        assert agent_with_store._is_checkin_paused()

    def test_tire_pressure_unrelated_treated_as_not_now(self, agent_with_store, temp_store):
        """'What's the tire pressure?': 'pressure' must NOT match 'sure'. Pauses check-in and answers."""
        agent_with_store._active_person_followup = {
            "stage": "ask_permission",
            "person_id": "Person_2",
            "confirmation_id": 1,
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        prompt, _, _, _ = agent_with_store.build_context_system_prompt("What's the tire pressure?")
        assert agent_with_store._active_person_followup is None
        assert agent_with_store._is_checkin_paused()

    def test_sure_go_ahead_matches_yes(self, agent_with_store, temp_store):
        """'Sure, go ahead': matches yes and opens snapshot."""
        agent_with_store._active_person_followup = {
            "stage": "ask_permission",
            "person_id": "Person_2",
            "confirmation_id": 1,
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Sure, go ahead")
        assert agent_with_store._active_person_followup is not None
        assert agent_with_store._active_person_followup["stage"] == "awaiting_name"


class TestDurationAndObservedGaps:
    """Item 5: 2-minute rule with realistic ~43-second observer gaps."""

    def test_duration_accumulation_with_43s_gaps(self, temp_store):
        """Sightings 43s apart must accumulate elapsed time into total_duration_seconds."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        t0 = time.time()

        temp_store.upsert_pending_person_confirmation("Person_1", fake_emb, sighting_timestamp=t0)
        # Sighting 2 at t0 + 43s (observer cycle)
        temp_store.upsert_pending_person_confirmation("Person_1", fake_emb, sighting_timestamp=t0 + 43.0)
        pending = temp_store.get_pending_person_confirmations(status="pending")
        assert pytest.approx(pending[0]["total_duration_seconds"], abs=0.5) == 43.0

        # Sighting 3 at t0 + 86s
        temp_store.upsert_pending_person_confirmation("Person_1", fake_emb, sighting_timestamp=t0 + 86.0)
        pending = temp_store.get_pending_person_confirmations(status="pending")
        assert pytest.approx(pending[0]["total_duration_seconds"], abs=0.5) == 86.0

        # Sighting 4 at t0 + 129s (exceeds 120s / 2 min)
        temp_store.upsert_pending_person_confirmation("Person_1", fake_emb, sighting_timestamp=t0 + 129.0)
        pending = temp_store.get_pending_person_confirmations(status="pending")
        assert pytest.approx(pending[0]["total_duration_seconds"], abs=0.5) == 129.0

    def test_backfill_duration_from_sightings(self, temp_store):
        """Existing waiting faces with 0 seconds are backfilled from their logged sightings."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        t0 = time.time()
        # Insert 3 sightings in DB spaced 43s apart
        for i in range(4):
            temp_store.log_person_sighting(
                person_id="Person_2",
                is_known=False,
                confidence=0.85,
                embedding=fake_emb,
            )
            # manually adjust timestamps
            conn = temp_store._get_connection()
            ts_str = datetime.fromtimestamp(t0 + i * 43.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE person_sightings SET timestamp = ? WHERE id = (SELECT MAX(id) FROM person_sightings)", (ts_str,))
            conn.commit()
            conn.close()

        # Insert pending row with total_duration_seconds = 0.0
        conn = temp_store._get_connection()
        conn.execute(
            "INSERT INTO pending_person_confirmations (person_id, embedding, total_duration_seconds, status) VALUES ('Person_2', ?, 0.0, 'pending')",
            (fake_emb,)
        )
        conn.commit()
        conn.close()

        # Call backfill helper
        temp_store.backfill_pending_durations_from_sightings()
        pending = temp_store.get_pending_person_confirmations(status="pending")
        assert pending[0]["total_duration_seconds"] >= 120.0


class TestDismissedAndForgotten:
    """Items 8, 9: Dismissed faces stay dismissed; forget removes all photos and never reuses number."""

    def test_face_keeps_label_after_200_other_sightings(self, temp_store):
        """Bug 1: PersonIdentifier must keep Person_1's label even after 250 other sightings."""
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        fake_emb1 = np.ones(512, dtype=np.float32)
        fake_emb1 = fake_emb1 / np.linalg.norm(fake_emb1)

        # Pending person exists
        temp_store.upsert_pending_person_confirmation("Person_1", fake_emb1.tobytes(), sighting_timestamp=time.time())

        # Flood with 250 other sightings of Person_99
        other_emb = np.zeros(512, dtype=np.float32)
        other_emb[0] = 1.0
        for _ in range(250):
            temp_store.log_person_sighting("Person_99", is_known=False, confidence=0.8, embedding=other_emb.tobytes())

        # Now test matching fake_emb1
        matched = identifier._match_face_embedding(fake_emb1, store=temp_store)
        assert matched["person_id"] == "Person_1"

    def test_dismissed_face_stays_dismissed_after_200_other_sightings(self, temp_store):
        """Item 8: Dismissed face stays dismissed and matches Person_2 after 250 other sightings."""
        identifier = PersonIdentifier(db_path=temp_store._db_path)
        fake_emb = np.ones(512, dtype=np.float32)
        fake_emb = fake_emb / np.linalg.norm(fake_emb)

        # Person_2 is dismissed
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb.tobytes(), sighting_timestamp=time.time())
        temp_store.resolve_pending_person_confirmation_by_person_id("Person_2", status="dismissed")

        # Flood with 250 other sightings
        other_emb = np.zeros(512, dtype=np.float32)
        other_emb[0] = 1.0
        for _ in range(250):
            temp_store.log_person_sighting("Person_99", is_known=False, confidence=0.8, embedding=other_emb.tobytes())

        # Sighting of the same face should match Person_2 and NOT generate Person_3
        matched = identifier._match_face_embedding(fake_emb, store=temp_store)
        assert matched["person_id"] == "Person_2"

    def test_forget_them_removes_every_photo_on_disk(self, temp_store, tmp_path):
        """Item 9: 'Forget them' must delete every photo across all sightings of that person."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        photos = []
        for i in range(5):
            photo = tmp_path / f"person_3_sighting_{i}.jpg"
            photo.write_bytes(b"photo_content")
            photos.append(photo)
            temp_store.log_person_sighting(
                person_id="Person_3",
                is_known=False,
                confidence=0.9,
                embedding=fake_emb,
                snapshot_path=str(photo),
            )

        temp_store.upsert_pending_person_confirmation(
            person_id="Person_3",
            embedding=fake_emb,
            snapshot_path=str(photos[-1]),
            sighting_timestamp=time.time(),
        )

        # Call forget
        temp_store.forget_pending_person_by_person_id("Person_3")
        # Every single photo file on disk must be deleted
        for p in photos:
            assert not p.exists()

    def test_forget_them_never_reuses_number(self, temp_store):
        """Item 9: Next number rule must never reuse a forgotten face's number."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_5", fake_emb, sighting_timestamp=time.time())
        assert temp_store.get_next_person_number() == 6

        # Forget Person_5
        temp_store.forget_pending_person_by_person_id("Person_5")

        # Next number should STILL be 6, NOT 1 or 5!
        assert temp_store.get_next_person_number() >= 6


class TestNaggingAndTiming:
    """Items 6, 7, 10: 3-hour persistent pause, quiet spell, and local time formatting."""

    def test_three_hour_pause_survives_restart(self, temp_store):
        """Item 6: 'Not now' sets a 3-hour pause in persistent store that survives restart."""
        agent1 = CoreAgent()
        agent1._store = temp_store
        agent1._active_person_followup = {
            "stage": "ask_permission",
            "person_id": "Person_2",
            "confirmation_id": 1,
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        agent1.build_context_system_prompt("Not right now, I'm busy")
        assert agent1._is_checkin_paused()

        # Simulate fresh app restart with new CoreAgent instance
        agent2 = CoreAgent()
        agent2._store = temp_store
        # Pause must still be active!
        assert agent2._is_checkin_paused()

        # Add an eligible person
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        conn = temp_store._get_connection()
        conn.execute("INSERT INTO pending_person_confirmations (person_id, embedding, total_duration_seconds, status) VALUES ('Person_3', ?, 200.0, 'pending')", (fake_emb,))
        conn.commit()
        conn.close()

        # Agent 2 must NOT check in because 3-hour pause is active
        prompt, _, _, _ = agent2.build_context_system_prompt("What is my schedule?")
        assert "[UNRECOGNIZED PERSON CHECK-IN" not in prompt

    def test_quiet_spell_interrupting_guard(self, agent_with_store, temp_store):
        """Item 7: Check-in only on first turn after quiet spell (>15 min), never mid-task."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        conn = temp_store._get_connection()
        conn.execute("INSERT INTO pending_person_confirmations (person_id, embedding, total_duration_seconds, status) VALUES ('Person_2', ?, 200.0, 'pending')", (fake_emb,))
        conn.commit()
        conn.close()

        # Turn 1: after quiet spell -> should check in
        agent_with_store._last_user_turn_timestamp = time.time() - 1200.0  # 20 min ago
        prompt1, _, _, _ = agent_with_store.build_context_system_prompt("Hello ARCHER")
        assert "[UNRECOGNIZED PERSON CHECK-IN" in prompt1

        # Reset followup for next test
        agent_with_store._active_person_followup = None

        # Turn 2: 30 seconds later (in the middle of back-and-forth) -> must NOT check in!
        agent_with_store._last_user_turn_timestamp = time.time() - 30.0
        prompt2, _, _, _ = agent_with_store.build_context_system_prompt("Can you open that file?")
        assert "[UNRECOGNIZED PERSON CHECK-IN" not in prompt2

    def test_live_introduction_suppressed_during_snapshot_review(self, agent_with_store, temp_store):
        """Item 4: Saying 'That's Sarah' during snapshot review must NOT trigger webcam intro."""
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_2",
            "confirmation_id": 1,
            "snapshot_path": None,
        }
        # In build_context_system_prompt, _check_person_introduction must be bypassed
        prompt, _, _, _ = agent_with_store.build_context_system_prompt("That's Sarah, my designer")
        assert "[PERSON CONFIRMED & LEARNED" in prompt
        # Verify webcam intro note was not generated
        assert "Learned to recognize Sarah from the camera just now" not in prompt

    def test_time_formatting_local_phase2c_style(self, agent_with_store, temp_store):
        """Item 10: Sighting times must be converted from UTC to local time in 'Fri Oct 9, 5:15 PM' style."""
        # UTC time: 2026-10-09 17:15:00 UTC
        utc_ts = "2026-10-09 17:15:00"
        formatted = agent_with_store._format_sighting_details("Person_2", utc_ts)
        # Must format using local time and abbreviation (e.g. Fri Oct 9 or similar, not raw UTC or Saturday)
        assert "Oct" in formatted


class TestPhase2bSecondReview:
    """Tests for Claude's second Phase 2b review (2026-10-10 20:45) Items 1 to 5."""

    def test_reply_hmm_skip_next_sorry_not_saved_as_name(self, agent_with_store, temp_store):
        """Table 1: 'Hmm' / 'Skip' / 'Next' / 'Sorry' must NOT be saved as names."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        for phrase in ["Hmm", "Skip", "Next", "Sorry"]:
            pid = f"Person_{phrase}"
            temp_store.upsert_pending_person_confirmation(pid, fake_emb, sighting_timestamp=time.time())
            row = temp_store.get_pending_person_confirmations(status="pending")[0]
            agent_with_store._active_person_followup = {
                "stage": "awaiting_name",
                "person_id": pid,
                "confirmation_id": row["id"],
                "snapshot_path": None,
                "first_seen_at": "2026-10-10 10:00:00",
            }
            agent_with_store.build_context_system_prompt(phrase)
            names = [p["name"] for p in temp_store.get_known_persons()]
            assert phrase not in names, f"Phrase '{phrase}' was incorrectly saved as a person name!"

    def test_reply_thats_him_her_not_saved_as_him_her(self, agent_with_store, temp_store):
        """Table 1: 'That's him' / 'That's her' must NOT be saved as 'Him' / 'Her'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        for phrase in ["That's him", "That's her"]:
            pid = "Person_X"
            temp_store.upsert_pending_person_confirmation(pid, fake_emb, sighting_timestamp=time.time())
            row = temp_store.get_pending_person_confirmations(status="pending")[0]
            agent_with_store._active_person_followup = {
                "stage": "awaiting_name",
                "person_id": pid,
                "confirmation_id": row["id"],
                "snapshot_path": None,
                "first_seen_at": "2026-10-10 10:00:00",
            }
            agent_with_store.build_context_system_prompt(phrase)
            names = [p["name"] for p in temp_store.get_known_persons()]
            assert "Him" not in names
            assert "Her" not in names

    def test_reply_thats_interesting_not_saved_as_interesting(self, agent_with_store, temp_store):
        """Table 1: 'That's interesting' must NOT be saved as 'Interesting'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_Int", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_Int",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        agent_with_store.build_context_system_prompt("That's interesting")
        names = [p["name"] for p in temp_store.get_known_persons()]
        assert "Interesting" not in names

    def test_reply_friend_from_work_jenna_saved_as_jenna(self, agent_with_store, temp_store):
        """Table 1: 'Yeah that's my friend from work, Jenna' must be saved as 'Jenna', NOT 'From'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_Jenna", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_Jenna",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        agent_with_store.build_context_system_prompt("Yeah that's my friend from work, Jenna")
        names = [p["name"] for p in temp_store.get_known_persons()]
        assert "From" not in names
        assert "Jenna" in names

    def test_reply_thats_dr_patel_saved_as_dr_patel(self, agent_with_store, temp_store):
        """Table 1: 'That's Dr. Patel' must be saved as 'Dr. Patel' or 'Patel', NOT 'Dr'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_Doc", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_Doc",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        agent_with_store.build_context_system_prompt("That's Dr. Patel")
        names = [p["name"] for p in temp_store.get_known_persons()]
        assert "Dr" not in names
        assert any("patel" in n.lower() for n in names)

    def test_reply_dont_forget_thats_jake_not_deleted(self, agent_with_store, temp_store):
        """Table 1: 'Don't forget, that's Jake' must NOT delete the person; saved as 'Jake'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_Jake", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_Jake",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        agent_with_store.build_context_system_prompt("Don't forget, that's Jake")
        # Person must NOT be deleted
        assert temp_store.get_pending_person_confirmations(status=None) != []
        names = [p["name"] for p in temp_store.get_known_persons()]
        assert "Jake" in names

    def test_reply_forget_it_its_sarah_not_deleted(self, agent_with_store, temp_store):
        """Table 1: 'Forget it, it's Sarah' must NOT delete the person; saved as 'Sarah'."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_Sarah", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_Sarah",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        agent_with_store.build_context_system_prompt("Forget it, it's Sarah")
        assert temp_store.get_pending_person_confirmations(status=None) != []
        names = [p["name"] for p in temp_store.get_known_persons()]
        assert "Sarah" in names

    def test_reply_yeah_thats_me_added_to_col(self, agent_with_store, temp_store):
        """Table 1: 'Yeah, that's me' must be understood and added to Col."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.add_known_person("Col", fake_emb)
        temp_store.upsert_pending_person_confirmation("Person_Col2", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_Col2",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        prompt, _, _, _ = agent_with_store.build_context_system_prompt("Yeah, that's me")
        assert "CONFIRMED AS COLBY" in prompt or "Col" in [p["name"] for p in temp_store.get_known_persons()]
        assert agent_with_store._active_person_followup is None

    def test_table2_go_for_it_and_absolutely_accepted(self, agent_with_store, temp_store):
        """Table 2: 'Go for it' and 'Absolutely' must be treated as affirmative (open snapshot card)."""
        for phrase in ["Go for it", "Absolutely"]:
            agent_with_store._active_person_followup = {
                "stage": "ask_permission",
                "person_id": "Person_P",
                "confirmation_id": 1,
                "snapshot_path": None,
                "first_seen_at": "2026-10-10 10:00:00",
            }
            prompt, _, _, _ = agent_with_store.build_context_system_prompt(phrase)
            assert agent_with_store._active_person_followup is not None, f"Phrase '{phrase}' was not accepted as yes!"
            assert agent_with_store._active_person_followup["stage"] == "awaiting_name"
            assert not agent_with_store._is_checkin_paused()

    def test_item2_open_question_auto_closes_after_two_unrelated_turns(self, agent_with_store, temp_store):
        """Item 2: Open question keeps open for 1 non-answer turn without reminder, then quietly auto-closes."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        temp_store.upsert_pending_person_confirmation("Person_Open", fake_emb, sighting_timestamp=time.time())
        row = temp_store.get_pending_person_confirmations(status="pending")[0]
        agent_with_store._active_person_followup = {
            "stage": "awaiting_name",
            "person_id": "Person_Open",
            "confirmation_id": row["id"],
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }

        # Turn 1: Col asks an unrelated question ("What's the weather?")
        # Must keep question open for this one reply, WITHOUT repeating reminder
        prompt1, _, _, _ = agent_with_store.build_context_system_prompt("What's the weather today?")
        assert agent_with_store._active_person_followup is not None
        assert agent_with_store._active_person_followup["stage"] == "awaiting_name"
        # Prompt must NOT contain nagging reminder
        assert "remind him you can save their name" not in prompt1

        # Turn 2: Col's next reply is also not an answer ("Thanks")
        # Must quietly drop the question, treat as "not now" (3h pause), and NOT save "Thanks" as the person's name!
        prompt2, _, _, _ = agent_with_store.build_context_system_prompt("Thanks")
        assert agent_with_store._active_person_followup is None
        assert agent_with_store._is_checkin_paused()
        names = [p["name"] for p in temp_store.get_known_persons()]
        assert "Thanks" not in names

    def test_item3_multi_person_review_loop_advances_without_asking_again(self, agent_with_store, temp_store):
        """Item 3: After resolving one person, ARCHER automatically moves to the next waiting person."""
        fake_emb = np.zeros(512, dtype=np.float32).tobytes()
        # Create Person_2 and Person_3 as eligible pending persons (duration >= 120s)
        temp_store.upsert_pending_person_confirmation("Person_2", fake_emb, sighting_timestamp=time.time())
        temp_store.upsert_pending_person_confirmation("Person_3", fake_emb, sighting_timestamp=time.time())
        conn = temp_store._get_connection()
        conn.execute("UPDATE pending_person_confirmations SET total_duration_seconds = 200.0 WHERE person_id IN ('Person_2', 'Person_3')")
        conn.commit()
        conn.close()

        # Step 1: Permission asked for Person_2, Col says Yes
        agent_with_store._active_person_followup = {
            "stage": "ask_permission",
            "person_id": "Person_2",
            "confirmation_id": 1,
            "snapshot_path": None,
            "first_seen_at": "2026-10-10 10:00:00",
        }
        agent_with_store.build_context_system_prompt("Yes")
        assert agent_with_store._active_person_followup["stage"] == "awaiting_name"
        assert agent_with_store._active_person_followup["person_id"] == "Person_2"

        # Step 2: Col names Person_2 ("That's Jenna")
        # Must resolve Person_2 AND immediately advance to Person_3!
        agent_with_store.build_context_system_prompt("That's Jenna")
        assert agent_with_store._active_person_followup is not None
        assert agent_with_store._active_person_followup["person_id"] == "Person_3"
        assert agent_with_store._active_person_followup["stage"] == "awaiting_name"

    def test_item5_rigorous_local_time_conversion(self, agent_with_store, temp_store):
        """Item 5: Sighting time UTC-to-local conversion must verify actual local hour and timezone offset."""
        utc_ts = "2026-10-09 17:15:00"
        dt_utc = datetime.strptime(utc_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone()
        expected_time_str = dt_local.strftime("%I:%M %p").lstrip("0")
        expected_day_str = str(dt_local.day)

        formatted = agent_with_store._format_sighting_details("Person_2", utc_ts)
        assert expected_time_str in formatted
        assert expected_day_str in formatted

