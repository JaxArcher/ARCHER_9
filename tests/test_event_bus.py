"""
Tests for the ARCHER Event Bus.
"""

import threading
import time

import pytest

from archer.core.event_bus import Event, EventBus, EventType


class TestEventBus:
    """Tests for the thread-safe event bus."""

    def test_subscribe_and_publish(self):
        """Test basic subscribe and publish."""
        bus = EventBus()
        received = []

        def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.WAKE_WORD_DETECTED, handler)
        bus.publish(Event(type=EventType.WAKE_WORD_DETECTED, data={"test": True}))

        assert len(received) == 1
        assert received[0].data["test"] is True

    def test_multiple_subscribers(self):
        """Test multiple handlers for the same event type."""
        bus = EventBus()
        received_a = []
        received_b = []

        bus.subscribe(EventType.STT_FINAL, lambda e: received_a.append(e))
        bus.subscribe(EventType.STT_FINAL, lambda e: received_b.append(e))
        bus.publish(Event(type=EventType.STT_FINAL, data={"text": "hello"}))

        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_halt_priority(self):
        """Test that HALT handlers run before regular subscribers."""
        bus = EventBus()
        order = []

        bus.subscribe(EventType.HALT, lambda e: order.append("regular"))
        bus.subscribe_halt(lambda e: order.append("halt_priority"))

        bus.publish_halt()

        assert order[0] == "halt_priority"
        assert order[1] == "regular"

    def test_unsubscribe(self):
        """Test removing a handler."""
        bus = EventBus()
        received = []

        def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.STT_FINAL, handler)
        bus.publish(Event(type=EventType.STT_FINAL))
        assert len(received) == 1

        bus.unsubscribe(EventType.STT_FINAL, handler)
        bus.publish(Event(type=EventType.STT_FINAL))
        assert len(received) == 1  # Should not have increased

    def test_thread_safety(self):
        """Test concurrent publish/subscribe from multiple threads."""
        bus = EventBus()
        received = []
        lock = threading.Lock()

        def handler(event: Event):
            with lock:
                received.append(event)

        bus.subscribe(EventType.STT_FINAL, handler)

        threads = []
        for i in range(10):
            t = threading.Thread(
                target=bus.publish,
                args=(Event(type=EventType.STT_FINAL, data={"i": i}),),
            )
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == 10

    def test_handler_exception_does_not_break_others(self):
        """Test that a failing handler doesn't prevent other handlers from running."""
        bus = EventBus()
        received = []

        def bad_handler(event: Event):
            raise ValueError("test error")

        def good_handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.STT_FINAL, bad_handler)
        bus.subscribe(EventType.STT_FINAL, good_handler)
        bus.publish(Event(type=EventType.STT_FINAL))

        assert len(received) == 1

    def test_clear(self):
        """Test clearing all subscribers."""
        bus = EventBus()
        received = []

        bus.subscribe(EventType.STT_FINAL, lambda e: received.append(e))
        bus.subscribe_halt(lambda e: received.append(e))
        bus.clear()

        bus.publish(Event(type=EventType.STT_FINAL))
        bus.publish_halt()

        assert len(received) == 0

    def test_event_has_unique_id(self):
        """Test that each event gets a unique ID."""
        e1 = Event(type=EventType.STT_FINAL)
        e2 = Event(type=EventType.STT_FINAL)
        assert e1.event_id != e2.event_id

    def test_event_has_timestamp(self):
        """Test that events have timestamps."""
        e = Event(type=EventType.STT_FINAL)
        assert e.timestamp is not None
