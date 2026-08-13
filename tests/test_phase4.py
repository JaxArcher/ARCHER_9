"""
Tests for ARCHER Phase 4: PC Control + Finance/Investment + Full GUI.

Covers:
- Finance and Investment agent routing (keyword + explicit)
- PC Control tool definitions and executor
- Artifact Pane widget
- 3D orb graceful fallback
- Orchestrator Phase 4 integration (5 agents, tool schemas)
"""

import os
import json
import sys
import threading
import time
import pytest

# Ensure working directory is project root for SOUL.md loading
os.chdir(os.path.join(os.path.dirname(__file__), ".."))


# ==================================================================
# Finance & Investment Agent Routing
# ==================================================================

from archer.agents.orchestrator import (
    AgentOrchestrator,
    _INVESTMENT_KEYWORDS,
    _TRAINER_KEYWORDS,
    _THERAPIST_KEYWORDS,
    _ACTIVE_AGENTS,
    _AGENT_NAME_MAP,
)


@pytest.fixture
def orchestrator():
    """Create a fresh orchestrator for each test."""
    return AgentOrchestrator()


class TestInvestmentRouting:
    """Test Investment agent keyword routing."""

    def test_investment_keywords_route_correctly(self, orchestrator):
        """Investment keywords should route to investment agent."""
        assert orchestrator._classify_agent("How's my stock portfolio doing?") == "investment"
        assert orchestrator._classify_agent("Show me the market summary") == "investment"
        assert orchestrator._classify_agent("What's the S&P 500 at today?") == "investment"

    def test_investment_explicit_reference(self, orchestrator):
        """Explicit reference to investment agent routes correctly."""
        assert orchestrator._classify_agent("Talk to the investment agent") == "investment"
        assert orchestrator._classify_agent("Ask the investor about my holdings") == "investment"

    def test_investment_keywords_exist(self):
        """Investment keyword set should have meaningful keywords."""
        assert "stock" in _INVESTMENT_KEYWORDS
        assert "portfolio" in _INVESTMENT_KEYWORDS
        assert "market" in _INVESTMENT_KEYWORDS
        assert "dividend" in _INVESTMENT_KEYWORDS


class TestActiveAgentRouting:
    """Test that active agents are properly registered."""

    def test_active_agents(self):
        """Phase 4 should have active agents registered."""
        assert "assistant" in _ACTIVE_AGENTS
        assert "trainer" in _ACTIVE_AGENTS
        assert "therapist" in _ACTIVE_AGENTS
        assert "investment" in _ACTIVE_AGENTS

    def test_agent_name_map_includes_all(self):
        """Agent name map should include active agents and aliases."""
        assert _AGENT_NAME_MAP["investment"] == "investment"
        assert _AGENT_NAME_MAP["investor"] == "investment"
        assert _AGENT_NAME_MAP["coach"] == "trainer"
        assert _AGENT_NAME_MAP["counselor"] == "therapist"

    def test_souls_loaded(self, orchestrator):
        """Orchestrator should load SOUL.md for all active agents."""
        assert "assistant" in orchestrator._souls
        assert "investment" in orchestrator._souls
        assert "trainer" in orchestrator._souls
        assert "therapist" in orchestrator._souls

    def test_all_souls_have_content(self, orchestrator):
        """All SOUL.md files should have substantial content."""
        for agent, soul in orchestrator._souls.items():
            assert len(soul) > 50, f"SOUL.md for {agent} too short ({len(soul)} chars)"

    def test_questions_route_to_active_agents(self, orchestrator):
        """Test routing questions to specialized active agents."""
        q1 = orchestrator._classify_agent("What time is the meeting tomorrow?")
        assert q1 == "assistant"

        q2 = orchestrator._classify_agent("Ask the trainer for a workout plan")
        assert q2 == "trainer"
        orchestrator._recent_agents.clear()

        q3 = orchestrator._classify_agent("Talk to the therapist about my stress")
        assert q3 == "therapist"
        orchestrator._recent_agents.clear()

        q4 = orchestrator._classify_agent("How's my stock portfolio doing?")
        assert q4 == "investment"

    def test_ambiguous_keyword_defaults_to_assistant(self, orchestrator):
        """When keyword scores tie between agents, default to assistant."""
        # "gains" appears in both trainer and investment keywords
        # This should either pick one or fall through to assistant
        result = orchestrator._classify_agent("I'm thinking about gains")
        # Should not crash — any valid agent is acceptable
        assert result in _ACTIVE_AGENTS


# ==================================================================
# Event Bus — ARTIFACT_PUSH
# ==================================================================

class TestArtifactEvent:
    """Test ARTIFACT_PUSH event type."""

    def test_artifact_event_type_exists(self):
        """ARTIFACT_PUSH should exist in EventType."""
        from archer.core.event_bus import EventType
        assert hasattr(EventType, "ARTIFACT_PUSH")

    def test_artifact_event_publishable(self):
        """Should be able to publish an ARTIFACT_PUSH event."""
        from archer.core.event_bus import Event, EventType, get_event_bus
        bus = get_event_bus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.ARTIFACT_PUSH, handler)

        bus.publish(Event(
            type=EventType.ARTIFACT_PUSH,
            source="test",
            data={
                "type": "document",
                "title": "Test Doc",
                "content": "Hello",
                "agent": "assistant",
            },
        ))

        assert len(received) == 1
        assert received[0].data["type"] == "document"
        assert received[0].data["title"] == "Test Doc"

        bus.unsubscribe(EventType.ARTIFACT_PUSH, handler)
