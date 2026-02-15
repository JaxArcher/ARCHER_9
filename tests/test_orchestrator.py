"""
Tests for ARCHER Agent Orchestrator.

Phase 2 success criterion: Three different questions routed to three
different agents with distinct response styles.

Routing philosophy: User explicitly specifies agent. Default is Assistant.
Keyword routing is a secondary fallback when no specialist is active.
"""

import os
import sys
import threading
import pytest

# Ensure working directory is project root for SOUL.md loading
os.chdir(os.path.join(os.path.dirname(__file__), ".."))


from archer.agents.orchestrator import (
    AgentOrchestrator,
    _TRAINER_KEYWORDS,
    _THERAPIST_KEYWORDS,
    _CRISIS_KEYWORDS,
)


@pytest.fixture
def orchestrator():
    """Create a fresh orchestrator for each test."""
    return AgentOrchestrator()


class TestAgentClassification:
    """Test the routing logic."""

    def test_assistant_default(self, orchestrator):
        """General questions should route to assistant by default."""
        assert orchestrator._classify_agent("What time is it?") == "assistant"
        assert orchestrator._classify_agent("What's the weather?") == "assistant"
        assert orchestrator._classify_agent("Remind me to call mom") == "assistant"
        assert orchestrator._classify_agent("Open my calendar") == "assistant"
        assert orchestrator._classify_agent("What is the capital of France?") == "assistant"

    def test_explicit_agent_reference(self, orchestrator):
        """User can explicitly name an agent to route to."""
        assert orchestrator._classify_agent("Ask the trainer about my diet") == "trainer"
        assert orchestrator._classify_agent("Tell the therapist I need help") == "therapist"
        assert orchestrator._classify_agent("Ask the coach about sets") == "trainer"
        assert orchestrator._classify_agent("Talk to the trainer") == "trainer"
        assert orchestrator._classify_agent("Switch to therapist") == "therapist"
        assert orchestrator._classify_agent("Hey trainer") == "trainer"

    def test_crisis_keywords_always_therapist(self, orchestrator):
        """Crisis keywords MUST always route to therapist."""
        for keyword in _CRISIS_KEYWORDS:
            text = f"I {keyword}"
            result = orchestrator._classify_agent(text)
            assert result == "therapist", (
                f"Crisis keyword '{keyword}' routed to {result} instead of therapist"
            )

    def test_crisis_overrides_active_specialist(self, orchestrator):
        """Crisis keywords override even an active trainer conversation."""
        orchestrator._recent_agents.append("trainer")
        result = orchestrator._classify_agent("I want to die")
        assert result == "therapist"

    def test_keyword_hints_when_no_specialist_active(self, orchestrator):
        """Keywords route to specialist only when no specialist is active."""
        # No recent agents → keywords work as hints
        assert orchestrator._classify_agent("I need a good workout routine") == "trainer"
        assert orchestrator._classify_agent("I am feeling really stressed") == "therapist"
        assert orchestrator._classify_agent("How many calories in a banana?") == "trainer"
        assert orchestrator._classify_agent("I feel so lonely") == "therapist"

    def test_context_continuity_stays_with_specialist(self, orchestrator):
        """Once in a specialist conversation, follow-ups stay there."""
        # User explicitly started with trainer
        orchestrator._recent_agents.append("trainer")

        # Follow-up that doesn't mention any agent should stay with trainer
        result = orchestrator._classify_agent("What about tomorrow?")
        assert result == "trainer"

        # Even a therapist-keyword message stays with trainer (context wins)
        result = orchestrator._classify_agent("I feel stressed about it")
        assert result == "trainer"

    def test_context_continuity_not_for_assistant(self, orchestrator):
        """Context continuity doesn't lock onto assistant (it's the default)."""
        orchestrator._recent_agents.append("assistant")

        # Keywords should still work when assistant was last
        assert orchestrator._classify_agent("I need a workout") == "trainer"
        assert orchestrator._classify_agent("I am really stressed") == "therapist"

    def test_explicit_switch_overrides_context(self, orchestrator):
        """Explicit agent reference overrides context continuity."""
        orchestrator._recent_agents.append("trainer")

        # Explicit switch to therapist overrides active trainer conversation
        result = orchestrator._classify_agent("Talk to the therapist")
        assert result == "therapist"

    def test_no_false_positives_from_substrings(self, orchestrator):
        """Ensure keyword matching uses word boundaries."""
        # "lately" contains "ate" but should NOT trigger trainer
        assert orchestrator._classify_agent("I've been tired lately") == "assistant"
        # "platform" contains "fat" — should not trigger trainer
        assert orchestrator._classify_agent("What platform should I use?") == "assistant"

    def test_three_agents_three_questions(self, orchestrator):
        """Phase 2 success criterion: three questions, three different agents."""
        # Q1: General question → Assistant
        q1_agent = orchestrator._classify_agent("What's the weather today?")
        assert q1_agent == "assistant"

        # Q2: Explicit trainer request
        q2_agent = orchestrator._classify_agent("Ask the trainer for a workout plan")
        assert q2_agent == "trainer"

        # Reset context so we don't get stuck with trainer
        orchestrator._recent_agents.clear()

        # Q3: Explicit therapist request
        q3_agent = orchestrator._classify_agent("Talk to the therapist, I need to vent")
        assert q3_agent == "therapist"

        # All three are different agents
        agents = {q1_agent, q2_agent, q3_agent}
        assert len(agents) == 3


class TestOrchestratorInit:
    """Test orchestrator initialization."""

    def test_loads_all_souls(self, orchestrator):
        """All three agent SOUL.md files should be loaded."""
        assert "assistant" in orchestrator._souls
        assert "trainer" in orchestrator._souls
        assert "therapist" in orchestrator._souls

    def test_souls_not_empty(self, orchestrator):
        """SOUL.md files should have content."""
        for agent, soul in orchestrator._souls.items():
            assert len(soul) > 100, f"SOUL.md for {agent} seems too short"

    def test_session_id_generated(self, orchestrator):
        """Each orchestrator instance gets a unique session ID."""
        orch2 = AgentOrchestrator()
        assert orchestrator.session_id != orch2.session_id

    def test_default_agent_is_assistant(self, orchestrator):
        """The default active agent should be assistant."""
        assert orchestrator.active_agent == "assistant"


class TestAgentSwitch:
    """Test agent switching and event publishing."""

    def test_switch_publishes_event(self, orchestrator):
        """Switching agents should publish an AGENT_SWITCH event."""
        from archer.core.event_bus import EventType, get_event_bus

        bus = get_event_bus()
        events_received = []

        def handler(event):
            events_received.append(event)

        bus.subscribe(EventType.AGENT_SWITCH, handler)

        orchestrator._switch_agent("trainer")

        assert len(events_received) == 1
        assert events_received[0].data["old_agent"] == "assistant"
        assert events_received[0].data["new_agent"] == "trainer"
        assert orchestrator.active_agent == "trainer"

        # Clean up
        bus.unsubscribe(EventType.AGENT_SWITCH, handler)

    def test_no_event_on_same_agent(self, orchestrator):
        """No event should be published if the agent doesn't change."""
        from archer.core.event_bus import EventType, get_event_bus

        bus = get_event_bus()
        events_received = []

        def handler(event):
            events_received.append(event)

        bus.subscribe(EventType.AGENT_SWITCH, handler)

        orchestrator._switch_agent("assistant")  # Already the active agent

        assert len(events_received) == 0

        bus.unsubscribe(EventType.AGENT_SWITCH, handler)


class TestConversationHistory:
    """Test conversation memory management."""

    def test_clear_history(self, orchestrator):
        """Clearing history should empty Tier 1 but preserve Tier 2."""
        orchestrator._conversation_history.append(
            {"role": "user", "content": "test"}
        )
        orchestrator._recent_agents.append("trainer")

        orchestrator.clear_history()

        assert len(orchestrator.conversation_history) == 0
        assert len(orchestrator._recent_agents) == 0

    def test_halt_cancels_processing(self, orchestrator):
        """HALT should set the cancelled flag."""
        from archer.core.event_bus import Event, EventType

        assert not orchestrator._cancelled.is_set()

        orchestrator._on_halt(Event(type=EventType.HALT, source="test"))

        assert orchestrator._cancelled.is_set()
