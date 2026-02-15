"""
ARCHER Proactive Intervention Engine.

Subscribes to OBSERVATION events from the Observer Pipeline and
triggers proactive agent responses when conditions are met.

Intervention rules (from SOUL.md files):

Trainer:
- Sedentary 2+ hours → one-sentence directive
- If ignored twice → 4-hour cooldown on that topic

Therapist:
- Sustained stress/frustration/sadness for 20+ minutes → warm check-in
- Never more than once per 2 hours on the same emotional topic
- Crisis protocol → always fires, no cooldown

Each intervention goes through the Orchestrator's streaming pipeline
just like a user request, but the "user message" is a system-generated
observation prompt that the agent responds to in-character.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store


# --- Intervention definitions ---

# Emotions that trigger Therapist intervention
_DISTRESS_EMOTIONS = {"sad", "angry", "fear", "disgust"}

# Trainer sedentary cooldown (minutes)
_TRAINER_SEDENTARY_COOLDOWN = 240.0  # 4 hours after 2 ignores

# Therapist emotion cooldown (minutes)
_THERAPIST_EMOTION_COOLDOWN = 120.0  # 2 hours

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
        self._bus.subscribe(EventType.OBSERVATION, self._on_observation)

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

        try:
            if event_type == "sedentary":
                self._handle_sedentary(event.data)
            elif event_type == "sustained_emotion":
                self._handle_sustained_emotion(event.data)
            elif event_type == "posture" and event.data.get("is_hunched"):
                self._handle_hunched_posture(event.data)
        except Exception as e:
            logger.error(f"Intervention handler error: {e}")

    def _handle_sedentary(self, data: dict[str, Any]) -> None:
        """
        Handle sedentary alert — routes to Trainer.

        Rules:
        - Fire after 2+ hours of sitting
        - If ignored twice, enter 4-hour cooldown
        """
        agent = "trainer"
        topic = "sedentary"
        key = f"{agent}:{topic}"

        # Check ignore count
        with self._lock:
            ignores = self._ignore_counts.get(key, 0)
            if ignores >= 2:
                # Check if cooldown has expired
                if self._store.check_cooldown(agent, topic, _TRAINER_SEDENTARY_COOLDOWN):
                    logger.debug(f"Trainer sedentary intervention in cooldown (ignored {ignores}x)")
                    return
                else:
                    # Cooldown expired — reset ignore count
                    self._ignore_counts[key] = 0
                    ignores = 0

        # Check normal cooldown (don't fire more than once per session without reset)
        if self._store.check_cooldown(agent, topic, 120.0):  # 2-hour minimum gap
            return

        duration_minutes = data.get("duration_minutes", 120)
        hours = duration_minutes / 60.0

        prompt = (
            f"[SYSTEM: Observer detected that the user has been sitting for "
            f"{hours:.1f} hours without standing. Generate a brief, one-sentence "
            f"sedentary alert in your Trainer voice. Keep it to ONE sentence. "
            f"Be direct and action-oriented.]"
        )

        self._deliver_intervention(agent, topic, prompt)

    def _handle_sustained_emotion(self, data: dict[str, Any]) -> None:
        """
        Handle sustained emotional distress — routes to Therapist.

        Rules:
        - Fire after 20+ minutes of sustained negative emotion
        - Never more than once per 2 hours on the same emotional topic
        """
        dominant = data.get("dominant_emotion", "neutral")

        if dominant not in _DISTRESS_EMOTIONS:
            return

        agent = "therapist"
        topic = f"emotion_{dominant}"

        # Therapist cooldown: 2 hours per emotional topic
        if self._store.check_cooldown(agent, topic, _THERAPIST_EMOTION_COOLDOWN):
            logger.debug(f"Therapist emotion intervention in cooldown for {topic}")
            return

        sustained_seconds = data.get("sustained_seconds", 0)
        sustained_minutes = sustained_seconds / 60.0

        prompt = (
            f"[SYSTEM: Observer detected that the user has appeared "
            f"{dominant} for about {sustained_minutes:.0f} minutes. "
            f"Generate a brief, warm check-in in your Therapist voice. "
            f"Start with an observation, not a question. Keep it to one "
            f"or two sentences. Leave space for the user to engage or not.]"
        )

        self._deliver_intervention(agent, topic, prompt)

    def _handle_hunched_posture(self, data: dict[str, Any]) -> None:
        """
        Handle hunched posture detection — routes to Trainer.

        Gentler than sedentary — just a posture reminder.
        """
        agent = "trainer"
        topic = "posture"

        # 30-minute cooldown for posture reminders
        if self._store.check_cooldown(agent, topic, 30.0):
            return

        prompt = (
            "[SYSTEM: Observer detected that the user is hunching. "
            "Generate a brief posture reminder in your Trainer voice. "
            "ONE sentence maximum. Be direct but not aggressive.]"
        )

        self._deliver_intervention(agent, topic, prompt)

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
            # Enter extended cooldown
            if agent == "trainer":
                cooldown = _TRAINER_SEDENTARY_COOLDOWN
            else:
                cooldown = _THERAPIST_EMOTION_COOLDOWN

            self._store.set_cooldown(agent, topic)
            logger.info(
                f"Intervention {agent}/{topic} ignored {count}x — "
                f"entering {cooldown}min cooldown"
            )

    def reset_ignores(self, agent: str, topic: str) -> None:
        """Reset ignore count (e.g., when user engages with the intervention)."""
        key = f"{agent}:{topic}"
        with self._lock:
            self._ignore_counts.pop(key, None)
