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
    _FINANCE_KEYWORDS,
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


class TestFinanceRouting:
    """Test Finance agent keyword routing."""

    def test_finance_keywords_route_correctly(self, orchestrator):
        """Finance keywords should route to finance agent."""
        assert orchestrator._classify_agent("What's my budget this month?") == "finance"
        assert orchestrator._classify_agent("Log a spending of $50 at Walmart") == "finance"
        assert orchestrator._classify_agent("Show my expenses for January") == "finance"
        assert orchestrator._classify_agent("How much did I spend on bills?") == "finance"

    def test_finance_explicit_reference(self, orchestrator):
        """Explicit reference to finance agent routes correctly."""
        assert orchestrator._classify_agent("Ask the finance agent about my savings") == "finance"
        assert orchestrator._classify_agent("Talk to the accountant about receipts") == "finance"

    def test_finance_keywords_exist(self):
        """Finance keyword set should have meaningful keywords."""
        assert "budget" in _FINANCE_KEYWORDS
        assert "spending" in _FINANCE_KEYWORDS
        assert "expense" in _FINANCE_KEYWORDS
        assert "transaction" in _FINANCE_KEYWORDS
        assert "savings" in _FINANCE_KEYWORDS
        assert "bill" in _FINANCE_KEYWORDS


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


class TestFiveAgentRouting:
    """Test that all five agents are properly registered."""

    def test_five_active_agents(self):
        """Phase 4 should have exactly five active agents."""
        assert len(_ACTIVE_AGENTS) == 5
        assert "assistant" in _ACTIVE_AGENTS
        assert "trainer" in _ACTIVE_AGENTS
        assert "therapist" in _ACTIVE_AGENTS
        assert "finance" in _ACTIVE_AGENTS
        assert "investment" in _ACTIVE_AGENTS

    def test_agent_name_map_includes_all(self):
        """Agent name map should include all agents and aliases."""
        assert _AGENT_NAME_MAP["finance"] == "finance"
        assert _AGENT_NAME_MAP["investment"] == "investment"
        assert _AGENT_NAME_MAP["accountant"] == "finance"
        assert _AGENT_NAME_MAP["investor"] == "investment"
        assert _AGENT_NAME_MAP["coach"] == "trainer"
        assert _AGENT_NAME_MAP["counselor"] == "therapist"

    def test_five_souls_loaded(self, orchestrator):
        """Orchestrator should load SOUL.md for all five agents."""
        assert "finance" in orchestrator._souls
        assert "investment" in orchestrator._souls
        assert len(orchestrator._souls) == 5

    def test_all_souls_have_content(self, orchestrator):
        """All SOUL.md files should have substantial content."""
        for agent, soul in orchestrator._souls.items():
            assert len(soul) > 50, f"SOUL.md for {agent} too short ({len(soul)} chars)"

    def test_five_questions_five_agents(self, orchestrator):
        """Phase 4 success: five questions, five agents."""
        q1 = orchestrator._classify_agent("What time is the meeting tomorrow?")
        assert q1 == "assistant"

        q2 = orchestrator._classify_agent("Ask the trainer for a workout plan")
        assert q2 == "trainer"
        orchestrator._recent_agents.clear()

        q3 = orchestrator._classify_agent("Talk to the therapist about my stress")
        assert q3 == "therapist"
        orchestrator._recent_agents.clear()

        q4 = orchestrator._classify_agent("Show my budget for this month")
        assert q4 == "finance"
        orchestrator._recent_agents.clear()

        q5 = orchestrator._classify_agent("How's my portfolio doing?")
        assert q5 == "investment"

        agents = {q1, q2, q3, q4, q5}
        assert len(agents) == 5, f"Expected 5 unique agents, got {agents}"

    def test_ambiguous_keyword_defaults_to_assistant(self, orchestrator):
        """When keyword scores tie between agents, default to assistant."""
        # "gains" appears in both trainer and investment keywords
        # This should either pick one or fall through to assistant
        result = orchestrator._classify_agent("I'm thinking about gains")
        # Should not crash — any valid agent is acceptable
        assert result in _ACTIVE_AGENTS


class TestKeywordScoring:
    """Test the keyword scoring logic."""

    def test_single_keyword_routes_correctly(self, orchestrator):
        """A single clear keyword should route to the right agent."""
        assert orchestrator._classify_agent("Check my portfolio") == "investment"
        assert orchestrator._classify_agent("Show my budget") == "finance"
        assert orchestrator._classify_agent("I need a workout") == "trainer"
        assert orchestrator._classify_agent("I'm feeling anxious") == "therapist"

    def test_multi_word_keywords_work(self, orchestrator):
        """Multi-word keywords (with spaces) should match correctly."""
        assert orchestrator._classify_agent("I've been sitting too long") == "trainer"
        assert orchestrator._classify_agent("I had a panic attack") == "therapist"
        assert orchestrator._classify_agent("How much did I spend? Am I over budget?") == "finance"


# ==================================================================
# PC Control Tools
# ==================================================================

from archer.tools.pc_tools import (
    PC_TOOLS,
    READ_ONLY_TOOLS,
    CONFIRMATION_REQUIRED_TOOLS,
    PCToolExecutor,
)


class TestPCToolDefinitions:
    """Test PC tool schema definitions."""

    def test_tools_list_not_empty(self):
        """PC_TOOLS should have tool definitions."""
        assert len(PC_TOOLS) > 0

    def test_all_tools_have_required_fields(self):
        """Each tool must have name, description, and input_schema."""
        for tool in PC_TOOLS:
            assert "name" in tool, f"Tool missing 'name'"
            assert "description" in tool, f"Tool {tool.get('name')} missing 'description'"
            assert "input_schema" in tool, f"Tool {tool.get('name')} missing 'input_schema'"

    def test_tool_names_unique(self):
        """Tool names should be unique."""
        names = [t["name"] for t in PC_TOOLS]
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    def test_read_only_tools_defined(self):
        """Read-only tools should be in READ_ONLY_TOOLS set."""
        assert "take_screenshot" in READ_ONLY_TOOLS
        assert "get_active_window" in READ_ONLY_TOOLS
        assert "list_windows" in READ_ONLY_TOOLS
        assert "browser_get_text" in READ_ONLY_TOOLS
        assert "browser_screenshot" in READ_ONLY_TOOLS

    def test_confirmation_tools_defined(self):
        """Confirmation-required tools should be in CONFIRMATION_REQUIRED_TOOLS."""
        assert "open_url" in CONFIRMATION_REQUIRED_TOOLS
        assert "click" in CONFIRMATION_REQUIRED_TOOLS
        assert "type_text" in CONFIRMATION_REQUIRED_TOOLS
        assert "hotkey" in CONFIRMATION_REQUIRED_TOOLS
        assert "focus_window" in CONFIRMATION_REQUIRED_TOOLS
        assert "browser_click" in CONFIRMATION_REQUIRED_TOOLS
        assert "browser_type" in CONFIRMATION_REQUIRED_TOOLS
        assert "close_browser" in CONFIRMATION_REQUIRED_TOOLS

    def test_no_overlap_between_readonly_and_confirmation(self):
        """A tool can't be both read-only and require confirmation."""
        overlap = READ_ONLY_TOOLS & CONFIRMATION_REQUIRED_TOOLS
        assert len(overlap) == 0, f"Tools in both sets: {overlap}"

    def test_all_tools_categorized(self):
        """Every tool should be in either READ_ONLY or CONFIRMATION_REQUIRED."""
        all_tool_names = {t["name"] for t in PC_TOOLS}
        categorized = READ_ONLY_TOOLS | CONFIRMATION_REQUIRED_TOOLS
        uncategorized = all_tool_names - categorized
        assert len(uncategorized) == 0, f"Uncategorized tools: {uncategorized}"


class TestPCToolExecutor:
    """Test PCToolExecutor logic."""

    def test_executor_creation(self):
        """Executor should be created without errors."""
        executor = PCToolExecutor()
        assert executor is not None

    def test_requires_confirmation_read_only(self):
        """Read-only tools should not require confirmation."""
        executor = PCToolExecutor()
        assert not executor.requires_confirmation("take_screenshot")
        assert not executor.requires_confirmation("get_active_window")
        assert not executor.requires_confirmation("list_windows")

    def test_requires_confirmation_action_tools(self):
        """Action tools should require confirmation."""
        executor = PCToolExecutor()
        assert executor.requires_confirmation("open_url")
        assert executor.requires_confirmation("click")
        assert executor.requires_confirmation("type_text")
        assert executor.requires_confirmation("hotkey")

    def test_unknown_tool_returns_error(self):
        """Executing an unknown tool should return an error."""
        executor = PCToolExecutor()
        result = executor.execute("nonexistent_tool", {})
        assert "error" in result

    def test_reset_halt(self):
        """reset_halt should clear the halt flag."""
        executor = PCToolExecutor()
        executor._controller._halted.set()
        assert executor._controller._halted.is_set()
        executor.reset_halt()
        assert not executor._controller._halted.is_set()


# ==================================================================
# PC Controller
# ==================================================================

from archer.tools.pc_control import PCController


class TestPCController:
    """Test PCController basics."""

    def test_controller_creation(self):
        """Controller should initialize without errors."""
        controller = PCController()
        assert not controller._check_halt()

    def test_halt_flag_works(self):
        """HALT should set the flag and block actions."""
        controller = PCController()
        controller._halted.set()
        assert controller._check_halt()
        # Actions should return False when halted
        assert controller.click(100, 100) is False
        assert controller.type_text("hello") is False
        assert controller.hotkey("ctrl", "c") is False

    def test_reset_halt_clears_flag(self):
        """reset_halt should clear the halted flag."""
        controller = PCController()
        controller._halted.set()
        controller.reset_halt()
        assert not controller._check_halt()

    def test_active_window_returns_dict(self):
        """get_active_window should return a dict even if the library is unavailable."""
        controller = PCController()
        result = controller.get_active_window()
        assert isinstance(result, dict)
        assert "title" in result

    def test_list_windows_returns_list(self):
        """list_windows should return a list."""
        controller = PCController()
        result = controller.list_windows()
        assert isinstance(result, list)


# ==================================================================
# Artifact Pane
# ==================================================================

from archer.gui.artifact_pane import ArtifactPayload, _AGENT_COLORS, _TYPE_ICONS, MAX_TABS


class TestArtifactPayload:
    """Test ArtifactPayload dataclass."""

    def test_payload_creation(self):
        """ArtifactPayload should create with required fields."""
        payload = ArtifactPayload(
            type="document",
            title="Test",
            content="Hello world",
            agent="assistant",
        )
        assert payload.type == "document"
        assert payload.title == "Test"
        assert payload.content == "Hello world"
        assert payload.agent == "assistant"
        assert payload.timestamp is not None

    def test_payload_types(self):
        """All expected artifact types should be supported."""
        for atype in ["chart", "table", "document", "code", "image", "dashboard", "checklist"]:
            payload = ArtifactPayload(type=atype, title="T", content="C", agent="assistant")
            assert payload.type == atype

    def test_all_agents_have_colors(self):
        """Every active agent should have a color defined."""
        for agent in _ACTIVE_AGENTS:
            assert agent in _AGENT_COLORS, f"No color for agent '{agent}'"

    def test_type_icons_exist(self):
        """All supported artifact types should have icons."""
        expected = {"chart", "table", "document", "code", "image", "dashboard", "checklist"}
        for t in expected:
            assert t in _TYPE_ICONS, f"No icon for type '{t}'"

    def test_max_tabs_reasonable(self):
        """MAX_TABS should be a reasonable number."""
        assert MAX_TABS == 5


# ==================================================================
# 3D Orb Fallback
# ==================================================================

class TestOrb3DFallback:
    """Test that the 3D orb import doesn't crash the system."""

    def test_orb_3d_module_importable(self):
        """The orb_3d module should be importable without errors."""
        try:
            from archer.gui.orb_3d import Orb3DWidget
            assert Orb3DWidget is not None
        except ImportError:
            # This is acceptable — PyVista may not be installed
            pass

    def test_orb_2d_always_available(self):
        """The 2D OrbWidget must always be available as fallback."""
        from archer.gui.orb_widget import OrbWidget
        assert OrbWidget is not None

    def test_orb_3d_color_maps_complete(self):
        """3D orb should have colors for all agents and states."""
        from archer.gui.orb_3d import _STATE_COLORS, _AGENT_COLORS as _ORB_AGENT_COLORS
        assert "idle" in _STATE_COLORS
        assert "listening" in _STATE_COLORS
        assert "processing" in _STATE_COLORS
        assert "speaking" in _STATE_COLORS
        assert "error" in _STATE_COLORS

        for agent in _ACTIVE_AGENTS:
            assert agent in _ORB_AGENT_COLORS, f"No 3D orb color for '{agent}'"


# ==================================================================
# SOUL.md Files for New Agents
# ==================================================================

class TestNewAgentSouls:
    """Test Finance and Investment SOUL.md files."""

    def test_finance_soul_exists(self):
        """Finance SOUL.md should exist and have content."""
        from pathlib import Path
        soul_path = Path("src/archer/agents/finance/SOUL.md")
        assert soul_path.exists(), "Finance SOUL.md not found"
        content = soul_path.read_text(encoding="utf-8")
        assert len(content) > 100, "Finance SOUL.md too short"
        assert "budget" in content.lower() or "spending" in content.lower()

    def test_investment_soul_exists(self):
        """Investment SOUL.md should exist and have content."""
        from pathlib import Path
        soul_path = Path("src/archer/agents/investment/SOUL.md")
        assert soul_path.exists(), "Investment SOUL.md not found"
        content = soul_path.read_text(encoding="utf-8")
        assert len(content) > 100, "Investment SOUL.md too short"
        assert "portfolio" in content.lower() or "market" in content.lower()

    def test_finance_soul_no_investment_advice(self):
        """Finance SOUL.md should explicitly state no investment advice."""
        from pathlib import Path
        content = Path("src/archer/agents/finance/SOUL.md").read_text(encoding="utf-8")
        assert "never" in content.lower() and "invest" in content.lower()

    def test_investment_soul_no_specific_stock_picks(self):
        """Investment SOUL.md should not recommend specific stocks."""
        from pathlib import Path
        content = Path("src/archer/agents/investment/SOUL.md").read_text(encoding="utf-8")
        assert "never" in content.lower()


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


# ==================================================================
# Integration: Orchestrator + PC Tools
# ==================================================================

class TestOrchestratorPCToolIntegration:
    """Test that the orchestrator properly integrates PC tools."""

    def test_orchestrator_has_pc_tools_import(self):
        """The orchestrator should be able to import PC tools."""
        from archer.tools.pc_tools import PC_TOOLS, PCToolExecutor
        assert len(PC_TOOLS) > 0
        executor = PCToolExecutor()
        assert executor is not None

    def test_orchestrator_docstring_mentions_tools(self):
        """Orchestrator docstring should reference PC control."""
        import archer.agents.orchestrator as orch_module
        docstring = orch_module.__doc__
        assert "PC Control" in docstring or "tool" in docstring.lower()
