"""
Tests for ARCHER Memory System (Tier 1-3).

Phase 2 success criterion: Memory persists across a session restart.
"""

import os
import sqlite3
import tempfile
import pytest

os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from archer.memory.sqlite_store import SQLiteStore


@pytest.fixture
def temp_store(tmp_path):
    """Create a SQLite store in a temporary location."""
    db_path = str(tmp_path / "test_archer.db")
    store = SQLiteStore(db_path)
    return store


class TestSQLiteConversationLogging:
    """Test Tier 2 conversation log persistence."""

    def test_log_and_retrieve(self, temp_store):
        """Basic log and retrieve."""
        temp_store.log_conversation(
            session_id="session-1",
            role="user",
            content="What time is it?",
        )
        temp_store.log_conversation(
            session_id="session-1",
            role="assistant",
            agent_name="assistant",
            content="It is 10:30 AM.",
        )

        recent = temp_store.get_recent_conversations(limit=10)
        assert len(recent) == 2
        assert recent[0]["role"] == "user"
        assert recent[0]["content"] == "What time is it?"
        assert recent[1]["role"] == "assistant"
        assert recent[1]["content"] == "It is 10:30 AM."
        assert recent[1]["agent_name"] == "assistant"

    def test_session_filtering(self, temp_store):
        """Conversations can be filtered by session."""
        temp_store.log_conversation(
            session_id="session-1", role="user", content="Hello from session 1"
        )
        temp_store.log_conversation(
            session_id="session-2", role="user", content="Hello from session 2"
        )

        session_1 = temp_store.get_recent_conversations(
            limit=10, session_id="session-1"
        )
        assert len(session_1) == 1
        assert session_1[0]["content"] == "Hello from session 1"

    def test_metadata_stored(self, temp_store):
        """Metadata (like routed_to agent) is stored as JSON."""
        temp_store.log_conversation(
            session_id="session-1",
            role="user",
            content="I need a workout",
            metadata={"routed_to": "trainer"},
        )

        recent = temp_store.get_recent_conversations(limit=1)
        assert len(recent) == 1
        # metadata is stored as JSON string
        import json
        meta = json.loads(recent[0]["metadata"])
        assert meta["routed_to"] == "trainer"

    def test_persistence_across_store_restart(self, tmp_path):
        """
        Phase 2 success criterion: Memory persists across a session restart.

        This test creates a store, writes data, closes it,
        creates a NEW store on the same DB, and verifies data is still there.
        """
        db_path = str(tmp_path / "persist_test.db")

        # Session 1: write some data
        store1 = SQLiteStore(db_path)
        store1.log_conversation(
            session_id="session-1",
            role="user",
            content="My name is Col and I prefer dark mode.",
        )
        store1.log_conversation(
            session_id="session-1",
            role="assistant",
            agent_name="assistant",
            content="Got it, Col. I'll remember your preference for dark mode.",
        )
        store1.log_conversation(
            session_id="session-1",
            role="user",
            content="I did 50 pushups today.",
        )
        store1.log_conversation(
            session_id="session-1",
            role="assistant",
            agent_name="trainer",
            content="Nice work. That's solid. How did your form feel on the last 10?",
        )
        # "Close" session 1 by discarding the store object
        del store1

        # Session 2: create a completely new store on the same DB
        store2 = SQLiteStore(db_path)
        recent = store2.get_recent_conversations(limit=10)

        # Verify ALL data from session 1 is still there
        assert len(recent) == 4
        assert recent[0]["content"] == "My name is Col and I prefer dark mode."
        assert recent[1]["agent_name"] == "assistant"
        assert recent[2]["content"] == "I did 50 pushups today."
        assert recent[3]["agent_name"] == "trainer"

        # The NEW session (session 2) can also write and read
        store2.log_conversation(
            session_id="session-2",
            role="user",
            content="What did I tell you about pushups?",
        )

        # Now there should be 5 total entries across both sessions
        all_entries = store2.get_recent_conversations(limit=20)
        assert len(all_entries) == 5

        # And session 2 entries are separate
        session2_only = store2.get_recent_conversations(
            limit=10, session_id="session-2"
        )
        assert len(session2_only) == 1

    def test_ordering_is_chronological(self, temp_store):
        """Entries should be returned in chronological order."""
        for i in range(5):
            temp_store.log_conversation(
                session_id="s1",
                role="user",
                content=f"Message {i}",
            )

        recent = temp_store.get_recent_conversations(limit=5)
        for i, entry in enumerate(recent):
            assert entry["content"] == f"Message {i}"


class TestSQLiteInventory:
    """Test Tier 2 inventory persistence."""

    def test_inventory_crud(self, temp_store):
        """Basic inventory CRUD operations."""
        # Add item
        temp_store.add_inventory_item(
            item_name="Blue wireless headphones",
            location="Office desk, left drawer",
            notes="Good condition",
        )

        # Retrieve
        items = temp_store.get_inventory_items()
        assert len(items) == 1
        assert items[0]["name"] == "Blue wireless headphones"
        assert items[0]["location"] == "Office desk, left drawer"

    def test_inventory_persists(self, tmp_path):
        """Inventory data persists across restarts."""
        db_path = str(tmp_path / "inv_test.db")

        store1 = SQLiteStore(db_path)
        store1.add_inventory_item(
            item_name="Laptop charger", location="Living room couch"
        )
        del store1

        store2 = SQLiteStore(db_path)
        items = store2.get_inventory_items()
        assert len(items) == 1
        assert items[0]["name"] == "Laptop charger"
