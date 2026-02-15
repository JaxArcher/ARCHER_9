"""
ARCHER Thread-Safe Event Bus.

All inter-component communication goes through this event bus.
Components NEVER share objects directly — they publish and subscribe to events.

This is inspired by OpenClaw's Gateway WebSocket event bus, ported to Python
using thread-safe queues and callbacks.
"""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class EventType(str, Enum):
    """All event types in the ARCHER system."""

    # Voice pipeline events
    WAKE_WORD_DETECTED = "voice.wake_word_detected"
    VAD_SPEECH_START = "voice.vad_speech_start"
    VAD_SPEECH_END = "voice.vad_speech_end"
    STT_PARTIAL = "voice.stt_partial"
    STT_FINAL = "voice.stt_final"
    TTS_START = "voice.tts_start"
    TTS_CHUNK = "voice.tts_chunk"
    TTS_END = "voice.tts_end"
    BARGE_IN = "voice.barge_in"
    FILLER_PLAY = "voice.filler_play"

    # HALT
    HALT = "system.halt"

    # Agent events
    AGENT_REQUEST = "agent.request"
    AGENT_RESPONSE_START = "agent.response_start"
    AGENT_RESPONSE_CHUNK = "agent.response_chunk"
    AGENT_RESPONSE_END = "agent.response_end"
    AGENT_SWITCH = "agent.switch"

    # Toggle events
    MODE_CHANGED = "system.mode_changed"

    # Auth events
    AUTH_SUCCESS = "auth.success"
    AUTH_FAILURE = "auth.failure"
    AUTH_GUEST = "auth.guest_mode"

    # GUI events
    GUI_TEXT_INPUT = "gui.text_input"
    GUI_TOGGLE_MODE = "gui.toggle_mode"
    GUI_HALT_BUTTON = "gui.halt_button"
    GUI_MUTE_TTS = "gui.mute_tts"

    # Observer events (Phase 3, but schema is defined now)
    OBSERVATION = "observer.observation"

    # Memory events
    MEMORY_STORE = "memory.store"
    MEMORY_RETRIEVE = "memory.retrieve"

    # Artifact events
    ARTIFACT_PUSH = "artifact.push"

    # Pipeline events
    PIPELINE_STATE_CHANGED = "pipeline.state_changed"
    AUDIO_AMPLITUDE = "audio.amplitude"

    # System events
    SYSTEM_START = "system.start"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"


@dataclass
class Event:
    """An event in the ARCHER event bus."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# Type alias for event handlers
EventHandler = Callable[[Event], None]


class EventBus:
    """
    Thread-safe event bus for inter-component communication.

    All components publish events through this bus. Subscribers receive events
    on their own threads via callbacks. This enforces the threading constraint:
    components never share objects directly.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._lock = threading.Lock()
        self._halt_handlers: list[EventHandler] = []

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to an event type. Handler is called when the event fires."""
        with self._lock:
            self._subscribers[event_type].append(handler)

    def subscribe_halt(self, handler: EventHandler) -> None:
        """
        Subscribe to HALT events with highest priority.
        HALT handlers are called before any other subscribers and are
        guaranteed to execute within the HALT response window.
        """
        with self._lock:
            self._halt_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a handler from an event type."""
        with self._lock:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)

    def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers.

        HALT events are processed with highest priority — HALT handlers
        are called first, then regular subscribers.
        """
        with self._lock:
            handlers = list(self._subscribers.get(event.type, []))
            halt_handlers = list(self._halt_handlers) if event.type == EventType.HALT else []

        # HALT handlers first (highest priority)
        for handler in halt_handlers:
            try:
                handler(event)
            except Exception as e:
                # HALT handlers must not fail — log and continue
                import traceback
                traceback.print_exc()

        # Regular handlers
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                import traceback
                traceback.print_exc()

    def publish_halt(self, source: str = "system") -> None:
        """Convenience method to publish a HALT event immediately."""
        self.publish(Event(
            type=EventType.HALT,
            source=source,
            data={"reason": "halt_command"},
        ))

    def clear(self) -> None:
        """Remove all subscribers. Used during shutdown."""
        with self._lock:
            self._subscribers.clear()
            self._halt_handlers.clear()


# Global singleton event bus
_event_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get the global event bus singleton."""
    global _event_bus
    if _event_bus is None:
        with _bus_lock:
            if _event_bus is None:
                _event_bus = EventBus()
    return _event_bus
