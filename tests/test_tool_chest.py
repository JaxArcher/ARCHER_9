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

        # Clear case: Spreadsheet (non-finance: chores)
        route_excel = chest.route_clear_case("make a spreadsheet of this week's chores: dishes Monday, laundry Wednesday, vacuum Saturday")
        assert route_excel is not None
        assert route_excel["tool"] == "lenny_excel_sheet"
        assert route_excel["action"] == "create_excel"
        assert route_excel["bench"] == "LENNY"

        # Clear case: Word document (story)
        route_word = chest.route_clear_case("write a 10-sentence story in Word")
        assert route_word is not None
        assert route_word["tool"] == "lenny_word_document"
        assert route_word["action"] == "create_word"
        assert route_word["bench"] == "LENNY"

        # Clear case: Open notepad with specific text
        route_notepad = chest.route_clear_case("open Notepad and write 'call the vet'")
        assert route_notepad is not None
        assert route_notepad["tool"] == "lenny_open_app"
        assert route_notepad["action"] == "open_app"
        assert route_notepad["app"] == "notepad"

        # Clear case: Browse web
        route_browse = chest.route_clear_case("open chrome to browse websites")
        assert route_browse is not None
        assert route_browse["tool"] == "lenny_open_app"
        assert route_browse["action"] == "browse"

    def test_excel_voice_phrasings_route_deterministic(self):
        """Test Colby's exact Excel phrasings route directly to lenny_excel_sheet."""
        chest = ToolChest()
        s1 = "Open an Excel spreadsheet and lay down a one-week workout routine for me day by day"
        r1 = chest.route_clear_case(s1)
        assert r1 is not None
        assert r1["tool"] == "lenny_excel_sheet"
        assert r1["bench"] == "LENNY"

        s2 = "Create an Excel spreadsheet with the days of the week, eight rows for each hour, where I should have breakfast, lunch and dinner"
        r2 = chest.route_clear_case(s2)
        assert r2 is not None
        assert r2["tool"] == "lenny_excel_sheet"
        assert r2["bench"] == "LENNY"

    def test_unsupported_task_honesty(self):
        """Honest 'I don't have a tool for that yet' message for unsupported requests."""
        chest = ToolChest()
        route = chest.route_clear_case("cook a pizza in the oven")
        assert route is None

        resp = format_unsupported_tool_response("cook a pizza in the oven")
        assert resp.startswith("I don't have a tool for that yet")


class TestCoreAgentToolChestIntegration:
    """Test CoreAgent handles tool chest requests with brain-driven content and no hardcoded rows."""

    def test_core_agent_routes_spreadsheet_chores_matching_content(self):
        agent = CoreAgent()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {"result": {"success": True}}
        agent._tool_executor = mock_executor

        reply = agent._handle_tool_chest_command(
            "make a spreadsheet of this week's chores: dishes Monday, laundry Wednesday, vacuum Saturday"
        )
        assert reply is not None
        assert "spreadsheet on LENNY" in reply

        # Verify lenny_excel_sheet was called with exactly the chores from the prompt
        mock_executor.execute.assert_called_once()
        call_args = mock_executor.execute.call_args[0]
        assert call_args[0] == "lenny_excel_sheet"
        payload = call_args[1]
        rows = payload.get("rows", [])

        # Flatten rows text for matching
        flat_rows_text = " ".join(" ".join(str(c) for c in r) for r in rows).lower()
        assert "dishes" in flat_rows_text and "monday" in flat_rows_text
        assert "laundry" in flat_rows_text and "wednesday" in flat_rows_text
        assert "vacuum" in flat_rows_text and "saturday" in flat_rows_text

        # Verify NO canned finance figures
        assert "1500.00" not in flat_rows_text
        assert "rent" not in flat_rows_text
        assert "utilities" not in flat_rows_text

    def test_core_agent_routes_word_story_matching_content(self):
        agent = CoreAgent()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {"result": {"success": True}}
        agent._tool_executor = mock_executor

        reply = agent._handle_tool_chest_command("write a 10-sentence story in Word")
        assert reply is not None
        assert "Word on LENNY" in reply

        # Verify lenny_word_document was called with actual story content (not boilerplate)
        mock_executor.execute.assert_called_once()
        call_args = mock_executor.execute.call_args[0]
        assert call_args[0] == "lenny_word_document"
        payload = call_args[1]
        content = payload.get("content", [])

        full_content_text = " ".join(content)
        # Content must be a real story with multiple sentences
        assert len(full_content_text.split(".")) >= 8
        # Must NOT contain old placeholder strings
        assert "Document created by ARCHER for Colby on" not in full_content_text
        assert "Tasks and details recorded as requested" not in full_content_text

    def test_core_agent_routes_notepad_exact_text(self):
        agent = CoreAgent()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {"result": {"success": True}}
        agent._tool_executor = mock_executor

        reply = agent._handle_tool_chest_command("open Notepad and write 'call the vet'")
        assert reply is not None
        assert "notepad" in reply.lower()

        # Verify lenny_open_app was called for notepad
        mock_executor.execute.assert_any_call("lenny_open_app", {"name": "notepad"})

        # Verify lenny_type_text was called with exactly "call the vet"
        mock_executor.execute.assert_any_call("lenny_type_text", {"text": "call the vet"})

    def test_core_agent_missing_facts_creates_question_card_and_does_not_fabricate(self):
        """When user asks for facts ARCHER lacks (e.g. bills), ARCHER must ask Colby and NOT fabricate rows."""
        agent = CoreAgent()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {"result": {"success": True}}
        agent._tool_executor = mock_executor

        reply = agent._handle_tool_chest_command("make a spreadsheet of my three biggest monthly bills")
        assert reply is not None

        # Must NOT have executed excel creation with fake numbers
        mock_executor.execute.assert_not_called()

        # Must mention Questions tab or ask for details
        assert "Questions tab" in reply or "details" in reply or "bills" in reply

        # Question card was recorded in store
        questions = agent._store.get_questions()
        assert any(q.get("source") == "tool_chest" or "bills" in q.get("text", "").lower() for q in questions)

    def test_colby_excel_voice_requests_with_sensible_first_version(self):
        """
        Claude 2026-10-22 18:10 review:
        Test both of Col's exact sentences from entry 18:10:
        1. "Open an Excel spreadsheet and lay down a one-week workout routine for me day by day"
        2. "Create an Excel spreadsheet with the days of the week, eight rows for each hour, where I should have breakfast, lunch and dinner"
        The brain writes a sensible first version instead of asking or refusing.
        """
        agent = CoreAgent()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {"result": {"success": True}}
        agent._tool_executor = mock_executor

        # Sentence 1: Workout routine
        s1 = "Open an Excel spreadsheet and lay down a one-week workout routine for me day by day"
        reply1 = agent._handle_tool_chest_command(s1)
        assert reply1 is not None
        assert "sensible first version" in reply1
        assert "tell me what to change" in reply1.lower()

        mock_executor.execute.assert_called()
        call_args1 = mock_executor.execute.call_args[0]
        assert call_args1[0] == "lenny_excel_sheet"
        payload1 = call_args1[1]
        rows1 = payload1.get("rows", [])
        assert len(rows1) >= 7, "Workout routine must have at least 7 days/rows"
        flat_workout = " ".join(" ".join(str(c) for c in r) for r in rows1).lower()
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            assert day in flat_workout

        mock_executor.reset_mock()

        # Sentence 2: Daily meal & hour schedule
        s2 = "Create an Excel spreadsheet with the days of the week, eight rows for each hour, where I should have breakfast, lunch and dinner"
        reply2 = agent._handle_tool_chest_command(s2)
        assert reply2 is not None
        assert "sensible first version" in reply2
        assert "tell me what to change" in reply2.lower()

        mock_executor.execute.assert_called()
        call_args2 = mock_executor.execute.call_args[0]
        assert call_args2[0] == "lenny_excel_sheet"
        payload2 = call_args2[1]
        rows2 = payload2.get("rows", [])
        assert len(rows2) >= 8, "Must have at least 8 hourly rows"
        flat_meal = " ".join(" ".join(str(c) for c in r) for r in rows2).lower()
        assert "breakfast" in flat_meal
        assert "lunch" in flat_meal
        assert "dinner" in flat_meal
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            assert day in flat_meal

    def test_no_hardcoded_content_strings_in_routing_path(self):
        """Assert that no canned rows or placeholder strings remain in core_agent.py."""
        from pathlib import Path
        core_agent_path = Path(__file__).parent.parent / "src" / "archer" / "agents" / "core_agent.py"
        content = core_agent_path.read_text(encoding="utf-8")

        canned_strings = [
            "1500.00",
            "Rent / Housing",
            "220.00",
            "Utilities / Internet",
            "380.00",
            "Car / Insurance",
            "Document created by ARCHER for Colby on",
            "Tasks and details recorded as requested.",
            "Note recorded by ARCHER:\n",
        ]
        for s in canned_strings:
            assert s not in content, f"Found banned canned string '{s}' in core_agent.py!"

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
