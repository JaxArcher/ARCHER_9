"""
Unit tests for ARCHER Telegram Line (Phase 6b, Spec Section 10d).
"""

import pytest
from unittest.mock import MagicMock, patch

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.integrations.telegram_line import TelegramLineService, get_telegram_line


@pytest.fixture
def telegram_service():
    svc = get_telegram_line()
    yield svc
    svc.stop()


def test_telegram_authorization(telegram_service, monkeypatch):
    cfg = get_config()

    # Case 1: telegram_user_id configured
    monkeypatch.setattr(cfg, "telegram_user_id", 12345678)
    assert telegram_service._is_authorized(12345678, "colby") is True
    assert telegram_service._is_authorized(99999999, "intruder") is False

    # Case 2: telegram_user_id not configured (None)
    monkeypatch.setattr(cfg, "telegram_user_id", None)
    assert telegram_service._is_authorized(12345678, "colby") is False


def test_telegram_start_disabled_without_token(telegram_service, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "telegram_bot_token", "")

    # Calling start without a token returns False gracefully and stays stopped
    assert telegram_service.start() is False
    assert not telegram_service.is_running()


def test_text_splitter(telegram_service):
    short_text = "Hello world! This is a short response."
    chunks = telegram_service._split_text(short_text, max_len=100)
    assert len(chunks) == 1
    assert chunks[0] == short_text

    long_text = ("First paragraph.\n" * 50) + ("Second paragraph.\n" * 50)
    chunks = telegram_service._split_text(long_text, max_len=200)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 200


def test_telegram_approval_event_handling(telegram_service, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "telegram_user_id", 12345678)

    # Mock bot and loop
    mock_bot = MagicMock()
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    telegram_service._bot = mock_bot
    telegram_service._loop = mock_loop
    telegram_service._running = True

    with patch("asyncio.run_coroutine_threadsafe") as mock_run_coro:
        def _fake_run_coro(coro, loop):
            coro.close()
            return MagicMock()

        mock_run_coro.side_effect = _fake_run_coro

        # Trigger APPROVAL_REQUESTED event
        bus = get_event_bus()
        bus.publish(Event(
            type=EventType.APPROVAL_REQUESTED,
            source="test",
            data={
                "request_id": "appr_test_123",
                "tool_name": "click",
                "description": "Click mouse at (100, 200)",
                "details": "Button: left",
                "timeout_seconds": 30,
            }
        ))

        # Check that a coroutine was scheduled
        assert mock_run_coro.called
