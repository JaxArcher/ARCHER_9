"""
Tests for ARCHER Spec 11a: Tool Chest & Default Bench Routing.
Validates single unified tool registry across benches (LENNY, Beast, Antigravity, Telegram),
default bench priority for LENNY, deterministic code-level routing, honest fallback for unsupported tasks,
and API endpoints.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from archer.tools.tool_chest import ToolChest, get_tool_chest, format_unsupported_tool_response
from archer.agents.core_agent import CoreAgent
import archer.server as server_module


class TestToolChestRegistry:
    """Test tool discovery, categorization, and bench assignment."""

    def test_all_benches_represented(self):
        chest = ToolChest()
        tools = chest.get_all_tools()
        benches = {t["bench"] for t in tools}

        assert "LENNY" in benches, "LENNY bench must be represented"
        assert "Beast" in benches, "Beast bench must be represented"
        assert "Antigravity" in benches, "Antigravity bench must be represented"
        assert "Telegram" in benches, "Telegram bench must be represented"

    def test_lenny_bench_tools_include_office_apps_and_peripherals(self):
        chest = ToolChest()
        lenny_tools = chest.get_tools_by_bench("LENNY")
        tool_names = {t["name"] for t in lenny_tools}

        assert "lenny_excel_sheet" in tool_names
        assert "lenny_word_document" in tool_names
        assert "lenny_open_app" in tool_names
        assert "lenny_type_text" in tool_names
        assert "lenny_press_keys" in tool_names
        assert "lenny_look_and_click" in tool_names

    def test_summary_counts(self):
        chest = ToolChest()
        summary = chest.get_summary()
        assert summary["total_tools"] > 15
        assert summary["bench_counts"]["LENNY"] >= 8
        assert summary["default_bench"] == "LENNY"


class TestToolChestFindAndDefaultBench:
    """Test tool matching and default bench routing logic."""

    def test_tool_chest_find_matches(self):
        chest = ToolChest()

        # Excel
        res_excel = chest.tool_chest_find("create a spreadsheet with monthly expenses")
        assert len(res_excel) > 0
        assert res_excel[0]["name"] == "lenny_excel_sheet"
        assert res_excel[0]["bench"] == "LENNY"

        # Word
        res_word = chest.tool_chest_find("write a word document about architecture")
        assert len(res_word) > 0
        assert res_word[0]["name"] == "lenny_word_document"
        assert res_word[0]["bench"] == "LENNY"

        # GPU / Ollama -> Beast
        res_gpu = chest.tool_chest_find("gpu query status")
        assert any(t["bench"] == "Beast" for t in res_gpu)

    def test_route_clear_cases_deterministic(self):
        chest = ToolChest()

        # Clear case: Spreadsheet
        route_excel = chest.route_clear_case("make a spreadsheet of my three biggest monthly bills")
        assert route_excel is not None
        assert route_excel["tool"] == "lenny_excel_sheet"
        assert route_excel["action"] == "create_excel"
        assert route_excel["bench"] == "LENNY"

        # Clear case: Word document
        route_word = chest.route_clear_case("make a Word document about the project roadmap")
        assert route_word is not None
        assert route_word["tool"] == "lenny_word_document"
        assert route_word["action"] == "create_word"
        assert route_word["bench"] == "LENNY"

        # Clear case: Open notepad
        route_notepad = chest.route_clear_case("open notepad and write note")
        assert route_notepad is not None
        assert route_notepad["tool"] == "lenny_open_app"
        assert route_notepad["action"] == "open_app"
        assert route_notepad["app"] == "notepad"

        # Clear case: Browse web
        route_browse = chest.route_clear_case("open chrome to browse websites")
        assert route_browse is not None
        assert route_browse["tool"] == "lenny_open_app"
        assert route_browse["action"] == "browse"

    def test_unsupported_task_honesty(self):
        """Honest 'I don't have a tool for that yet' message for unsupported requests."""
        chest = ToolChest()
        route = chest.route_clear_case("cook a pizza in the oven")
        assert route is None

        resp = format_unsupported_tool_response("cook a pizza in the oven")
        assert resp.startswith("I don't have a tool for that yet")


class TestCoreAgentToolChestIntegration:
    """Test CoreAgent handles tool chest requests and guidelines."""

    def test_core_agent_routes_spreadsheet_command(self):
        agent = CoreAgent()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {"result": {"success": True}}
        agent._tool_executor = mock_executor

        reply = agent._handle_tool_chest_command("make a spreadsheet of my three biggest monthly bills")
        assert reply is not None
        assert "spreadsheet on LENNY" in reply
        mock_executor.execute.assert_called_once()
        call_args = mock_executor.execute.call_args[0]
        assert call_args[0] == "lenny_excel_sheet"

    def test_core_agent_routes_notepad_command(self):
        agent = CoreAgent()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {"result": {"success": True}}
        agent._tool_executor = mock_executor

        reply = agent._handle_tool_chest_command("open notepad and write a quick note")
        assert reply is not None
        assert "notepad on LENNY" in reply.lower() or "Opened notepad" in reply
        assert mock_executor.execute.call_count >= 1

    def test_guidelines_16_and_17_present(self):
        agent = CoreAgent()
        prompt, _, _, _ = agent.build_context_system_prompt("hello")
        assert "16. TOOL CHEST & DEFAULT BENCH:" in prompt
        assert "LENNY is your default bench" in prompt
        assert "I don't have a tool for that yet" in prompt
        assert "17. I HAVE QUESTIONS TAB" in prompt


class TestToolChestAPI:
    """Test FastAPI endpoints for Tool Chest."""

    def test_tool_chest_endpoints(self):
        client = TestClient(server_module.app)

        # 1. GET /api/tool_chest
        res = client.get("/api/tool_chest")
        assert res.status_code == 200
        data = res.json()
        assert "tools" in data
        assert "benches" in data
        assert "LENNY" in data["benches"]
        assert data["default_bench"] == "LENNY"

        # 2. POST /api/tool_chest/find
        find_res = client.post("/api/tool_chest/find", json={"task": "create spreadsheet"})
        assert find_res.status_code == 200
        find_data = find_res.json()
        assert len(find_data["matches"]) > 0
        assert find_data["clear_case"] is not None
        assert find_data["clear_case"]["bench"] == "LENNY"
