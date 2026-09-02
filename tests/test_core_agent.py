"""
Tests for ARCHER CoreAgent (Single-Agent Core).
"""

import pytest
from archer.agents.core_agent import CoreAgent


class TestCoreAgent:
    """Tests for CoreAgent pipeline and delegation logic."""

    @pytest.fixture
    def core_agent(self):
        return CoreAgent()

    def test_safety_override_triggered(self, core_agent):
        """Safety override should detect crisis phrases."""
        resp = core_agent.check_safety_override("I am feeling overwhelmed and want to end my life")
        assert resp is not None
        assert "988" in resp

    def test_safety_override_normal(self, core_agent):
        """Normal messages should pass safety override."""
        resp = core_agent.check_safety_override("How is the weather today?")
        assert resp is None

    def test_calculate_stance_tags(self, core_agent):
        """Stance tags should score based on stance keywords."""
        tags = core_agent.calculate_stance_tags("I need a intense workout and gym routine")
        assert "coaching" in tags
        assert tags["coaching"] >= 2.0

    def test_cloud_delegation_explicit(self, core_agent):
        """Explicit request triggers cloud delegation."""
        trigger = core_agent.evaluate_cloud_delegation("Ask Claude to analyze this", 100)
        assert trigger == "explicit_request"

    def test_cloud_delegation_complex_task(self, core_agent):
        """Complex code task triggers cloud delegation."""
        trigger = core_agent.evaluate_cloud_delegation("Write a script to parse logs", 100)
        assert trigger == "complex_task"

    def test_cloud_delegation_context_overflow(self, core_agent):
        """Context overflow triggers cloud delegation."""
        trigger = core_agent.evaluate_cloud_delegation("Normal query", 2500)
        assert trigger == "context_overflow"

    def test_build_context_system_prompt(self, core_agent):
        """System prompt should include identity, stance, and activity status."""
        prompt, trigger = core_agent.build_context_system_prompt("Let's plan my workout")
        assert "ARCHER" in prompt
        assert "High-Performance Fitness" in prompt

    def test_blindspot_path1_piggyback(self, core_agent):
        """Blindspot flag should piggyback on next turn once and clear after use."""
        from archer.event_bus import Event, EventType
        # Stage observer event
        core_agent._on_observation(Event(type=EventType.OBSERVATION_EVENT, source="test", data={"event_type": "sedentary", "duration_minutes": 90}))
        
        # Turn 1: user asks workout question while sedentary flag is pending
        prompt_turn1, _ = core_agent.build_context_system_prompt("What workout should I do today?")
        assert "Proactive Blindspot Register" in prompt_turn1
        assert "Observer flagged sedentary behavior (90 min)" in prompt_turn1
        assert "High-Performance Fitness" in prompt_turn1  # Coexists with domain stance!

        # Turn 2: next turn should NOT have Blindspot flag (cleared after single use)
        prompt_turn2, _ = core_agent.build_context_system_prompt("What workout should I do today?")
        assert "Proactive Blindspot Register" not in prompt_turn2
        assert "High-Performance Fitness" in prompt_turn2
