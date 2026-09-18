"""
ARCHER Proactive Intervention Engine.

Subscribes to OBSERVATION events from the Observer Pipeline and
triggers proactive agent responses when conditions are met.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from loguru import logger
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store


# Minimum confidence to trigger interventions
_MIN_CONFIDENCE = 0.5


class InterventionEngine:
    """
    Proactive intervention engine.

    Listens to OBSERVATION events and triggers proactive agent responses
    when conditions warrant intervention. Respects cooldowns and
    ignore-counts to avoid being annoying.
    """

    def __init__(
        self,
        speak_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        """
        Args:
            speak_callback: Function to deliver a proactive message.
                Signature: (agent_name: str, message_prompt: str) -> None
                The message_prompt is fed to the agent as a system trigger,
                and the agent responds in-character.
        """
        self._bus = get_event_bus()
        self._store = get_sqlite_store()
        self._speak_callback = speak_callback

        # Ignore tracking (in-memory — resets on restart)
        self._ignore_counts: dict[str, int] = {}  # "agent:topic" → count
        self._lock = threading.Lock()

        # Subscribe to observation events
        self._bus.subscribe(EventType.OBSERVATION_EVENT, self._on_observation)

        logger.info("Intervention engine initialized.")

    def set_speak_callback(self, callback: Callable[[str, str], None]) -> None:
        """Set the callback for delivering proactive messages."""
        self._speak_callback = callback

    def _on_observation(self, event: Event) -> None:
        """Handle an OBSERVATION event from the Observer Pipeline."""
        event_type = event.data.get("event_type", "")
        confidence = event.data.get("confidence", 0.0)

        if confidence < _MIN_CONFIDENCE:
            return

    def _deliver_intervention(
        self,
        agent: str,
        topic: str,
        prompt: str,
    ) -> None:
        """
        Deliver a proactive intervention.

        1. Set the cooldown
        2. Call the speak callback (which routes through the orchestrator)
        3. Log the intervention
        """
        # Set cooldown immediately (prevents double-firing)
        self._store.set_cooldown(agent, topic)

        logger.info(f"Proactive intervention: {agent}/{topic}")

        if self._speak_callback is not None:
            try:
                self._speak_callback(agent, prompt)
            except Exception as e:
                logger.error(f"Intervention delivery failed: {e}")
        else:
            logger.warning("No speak callback set — intervention not delivered.")

        # Log the intervention action
        try:
            self._store.log_action(
                agent_name=agent,
                action_type="proactive_intervention",
                description=f"Triggered {topic} intervention",
                metadata={"topic": topic, "prompt": prompt[:200]},
            )
        except Exception as e:
            logger.warning(f"Failed to log intervention action: {e}")

        # Publish intervention event for GUI
        self._bus.publish(Event(
            type=EventType.AGENT_REQUEST,
            source="intervention_engine",
            data={
                "agent": agent,
                "topic": topic,
                "proactive": True,
            },
        ))

    def mark_ignored(self, agent: str, topic: str) -> None:
        """
        Mark an intervention as ignored by the user.

        Called when a proactive message gets no response or is dismissed.
        After 2 ignores, triggers extended cooldown.
        """
        key = f"{agent}:{topic}"
        with self._lock:
            self._ignore_counts[key] = self._ignore_counts.get(key, 0) + 1
            count = self._ignore_counts[key]

        if count >= 2:
            self._store.set_cooldown(agent, topic)
            logger.info(
                f"Intervention {agent}/{topic} ignored {count}x — "
                f"entering cooldown"
            )

    def reset_ignores(self, agent: str, topic: str) -> None:
        """Reset ignore count (e.g., when user engages with the intervention)."""
        key = f"{agent}:{topic}"
        with self._lock:
            self._ignore_counts.pop(key, None)
