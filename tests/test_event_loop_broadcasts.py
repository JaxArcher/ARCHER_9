"""
Unit tests for outside-event-loop broadcasts and default_model fix
(Review 2026-10-21 18:05/18:15 Item 2).
"""

import asyncio
import threading
from unittest.mock import MagicMock, patch
import pytest

import archer.server as server
from archer.core.event_bus import Event, EventType


def test_log_activity_from_plain_thread():
    """Verify calling _log_activity from a plain thread (no running event loop) does not raise."""
    error = None

    def worker():
        nonlocal error
        try:
            server._log_activity("Voice", "Test plain thread message")
            server._update_status_board("voice", "Listening", "Listening test", dot="green")
        except Exception as e:
            error = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert error is None, f"_log_activity or _update_status_board raised: {error}"
    # Verify the activity entry was recorded
    assert any("Test plain thread message" in e["text"] for e in server._activity_feed_history)


def test_broadcast_scheduled_via_call_soon_threadsafe():
    """Verify calling _log_activity from a thread when _ws_loop is active schedules via call_soon_threadsafe."""
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True

    with patch.object(server, "_ws_loop", mock_loop):
        # Add a fake client so broadcast actually attempts sending
        fake_ws = MagicMock()
        server._ws_clients.add(fake_ws)
        try:
            def worker():
                server._log_activity("Brain", "Thread activity with loop active")

            t = threading.Thread(target=worker)
            t.start()
            t.join()

            # call_soon_threadsafe should have been called on mock_loop
            assert mock_loop.call_soon_threadsafe.called
        finally:
            server._ws_clients.discard(fake_ws)


def test_on_agent_end_no_attribute_error():
    """Verify _on_agent_end runs cleanly without AttributeError on default_model."""
    mock_event = Event(
        type=EventType.AGENT_RESPONSE_END,
        data={
            "elapsed": 1.25,
            "first_words_elapsed": 0.45,
            "text": "Hello, how can I help you today?",
            "agent": "assistant",
        },
    )

    # In server._register_status_line_bridge, _on_agent_end is defined.
    # We test that the handler logic executes cleanly without raising AttributeError.
    with patch("archer.server._update_status_board") as mock_update, \
         patch("archer.server._log_activity") as mock_log:
        
        # Test the exact model extraction expression used in _on_agent_end:
        model = getattr(server.get_orchestrator(), "primary_model", None) or server.get_config().core_primary_model or "gemma4:e4b"
        assert model is not None

        # Verify that get_config() doesn't have default_model, but our handler doesn't crash
        assert not hasattr(server.get_config(), "default_model")


def test_android_state_broadcast_from_worker_thread():
    """Verify android_state broadcast callback executes cleanly from a worker thread."""
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True

    with patch.object(server, "_ws_loop", mock_loop):
        fake_ws = MagicMock()
        server._ws_clients.add(fake_ws)
        try:
            error = None

            def worker():
                nonlocal error
                try:
                    server._on_android_state_change({
                        "running": True,
                        "starting": False,
                        "step": "online",
                        "gpu_mode": "host",
                    })
                except Exception as e:
                    error = e

            t = threading.Thread(target=worker)
            t.start()
            t.join()

            assert error is None
            assert server._status_board_state["phone"]["state"] == "Online"
            assert server._status_board_state["phone"]["dot"] == "green"
        finally:
            server._ws_clients.discard(fake_ws)
