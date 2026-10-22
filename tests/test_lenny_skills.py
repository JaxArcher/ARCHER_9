"""
Tests for ARCHER LENNY skills, routing, gating, and system prompt awareness (Spec Section 11).
"""

from unittest.mock import MagicMock, patch
import pytest

from archer.skills.skills_registry import get_all_tools, get_tool_category
from archer.core.approvals import get_approval_manager, READ_ONLY_TOOLS, SELF_RECORD_TOOLS
from archer.skills.tool_executor import UniversalToolExecutor


def test_lenny_skills_registered():
    """All 10 LENNY tools are discovered and categorized under 'lenny'."""
    expected_tools = [
        "lenny_status",
        "lenny_open_app",
        "lenny_word_document",
        "lenny_excel_sheet",
        "lenny_list_controls",
        "lenny_invoke_control",
        "lenny_type_text",
        "lenny_press_keys",
        "lenny_look_and_click",
        "lenny_describe_screen",
    ]
    all_tools = {t["name"]: t for t in get_all_tools(refresh=True)}
    for tool_name in expected_tools:
        assert tool_name in all_tools, f"Tool '{tool_name}' missing from skills registry"
        assert get_tool_category(tool_name) == "lenny", f"Tool '{tool_name}' category is not 'lenny'"


def test_lenny_approvals_gating():
    """Read-only and self-record LENNY tools do not require user prompt; interactive action tools do."""
    mgr = get_approval_manager()

    # Read-only
    assert "lenny_status" in READ_ONLY_TOOLS
    assert "lenny_list_controls" in READ_ONLY_TOOLS
    assert "lenny_describe_screen" in READ_ONLY_TOOLS
    assert mgr.should_gate("lenny_status", {}) == (False, "read_only")
    assert mgr.should_gate("lenny_list_controls", {}) == (False, "read_only")
    assert mgr.should_gate("lenny_describe_screen", {}) == (False, "read_only")

    # Self-record (Office document creation in artifacts)
    assert "lenny_word_document" in SELF_RECORD_TOOLS
    assert "lenny_excel_sheet" in SELF_RECORD_TOOLS
    assert mgr.should_gate("lenny_word_document", {"title": "Doc", "content": "Text"}) == (False, "self_record")
    assert mgr.should_gate("lenny_excel_sheet", {"sheet_name": "S1", "rows": []}) == (False, "self_record")

    # Action tools require Phase 3 gate
    assert mgr.should_gate("lenny_open_app", {"name": "notepad"})[0] is True
    assert mgr.should_gate("lenny_invoke_control", {"identifier": "btn"})[0] is True
    assert mgr.should_gate("lenny_type_text", {"text": "hello"})[0] is True
    assert mgr.should_gate("lenny_press_keys", {"keys": "enter"})[0] is True
    assert mgr.should_gate("lenny_look_and_click", {"description": "Save"})[0] is True


def test_tool_executor_routes_lenny_tools():
    """UniversalToolExecutor executes lenny tools via _exec_lenny_tool."""
    executor = UniversalToolExecutor()

    with patch("archer.lenny.lenny_client.get_lenny_client") as mock_get_client, \
         patch("archer.lenny.app_operator.AppOperator") as mock_app_op:

        mock_client = MagicMock()
        mock_client.get_status.return_value = {"status": "connected", "online": True}
        mock_client.open_app.return_value = {"status": "launched", "name": "notepad"}
        mock_get_client.return_value = mock_client

        mock_op = MagicMock()
        mock_op.create_word_document.return_value = {"status": "created", "filename": "test.docx"}
        mock_app_op.return_value = mock_op

        # 1. lenny_status
        res_status = executor.execute("lenny_status", {})
        assert res_status.get("status") == "connected"
        assert mock_client.get_status.called

        # 2. lenny_open_app (bypass gating for unit test via session approval or direct _exec)
        res_open = executor._exec_lenny_tool("lenny_open_app", {"name": "notepad"})
        assert res_open.get("status") == "launched"
        mock_client.open_app.assert_called_with("notepad")

        # 3. lenny_word_document
        res_word = executor.execute("lenny_word_document", {"title": "Items", "content": "1. Apples"})
        assert res_word.get("status") == "created"
        assert mock_op.create_word_document.called


def test_core_agent_system_prompt_guideline_15():
    """CoreAgent system prompt includes Guideline 15 awareness of LENNY workstation."""
    with patch("archer.agents.core_agent.get_sqlite_store"), \
         patch("archer.agents.core_agent.get_openmemory_store"), \
         patch("archer.agents.core_agent.get_chromadb_store"), \
         patch("archer.agents.core_agent.get_redis_buffer"):
        from archer.agents.core_agent import CoreAgent
        agent = CoreAgent()
        prompt, _, _, _ = agent.build_context_system_prompt("Colby says write a word document on LENNY")

        assert "15. DEDICATED DESK PC (LENNY):" in prompt
        assert "LENNY" in prompt
        assert "Office" in prompt
        assert "Beast" in prompt
