"""
Unit and integration tests for Phase 3 Approval System (Spec Section 6).
"""

import time
import pytest
import threading

from archer.core.approvals import (
    ApprovalManager,
    READ_ONLY_TOOLS,
    SELF_RECORD_TOOLS,
    ALWAYS_ASK_TOOLS,
    get_approval_manager,
)
from archer.core.event_bus import get_event_bus, Event, EventType
from archer.memory.sqlite_store import get_sqlite_store
from archer.skills.tool_executor import UniversalToolExecutor


@pytest.fixture(autouse=True)
def reset_approval_manager():
    """Reset approval manager session state before each test."""
    mgr = get_approval_manager()
    mgr.session_approval_active = False
    with mgr._pending_lock:
        mgr._pending.clear()
    mgr.set_broadcast_callback(None)
    yield
    mgr.session_approval_active = False
    with mgr._pending_lock:
        mgr._pending.clear()
    mgr.set_broadcast_callback(None)


def setup_auto_responder(mgr: ApprovalManager, decision: str, records: list | None = None):
    """Register broadcast callback that automatically resolves incoming approval requests."""
    def on_broadcast(msg):
        if records is not None:
            records.append(msg)
        if msg.get("type") == "approval_request":
            req_id = msg["request_id"]
            threading.Thread(target=lambda: mgr.handle_response(req_id, decision)).start()
    mgr.set_broadcast_callback(on_broadcast)


def test_should_gate_tool_categories():
    mgr = get_approval_manager()

    # Read-only tools
    for tool in ["open_url", "get_active_window", "take_screenshot", "search_inventory", "list_tasks"]:
        needs_approval, reason = mgr.should_gate(tool, {})
        assert not needs_approval, f"{tool} should not need approval"
        assert reason == "read_only"

    # Self-record tools
    for tool in ["add_task", "complete_task", "add_habit", "switch_tab"]:
        needs_approval, reason = mgr.should_gate(tool, {})
        assert not needs_approval, f"{tool} should not need approval"
        assert reason == "self_record"

    # Changing tools
    for tool in ["click", "type_text", "hotkey", "browser_click", "execute_command"]:
        needs_approval, reason = mgr.should_gate(tool, {})
        assert needs_approval, f"{tool} must require approval"
        assert reason == "changes_state"

    # Always-ask tools
    for tool in ["install_tool_git", "install_venv"]:
        needs_approval, reason = mgr.should_gate(tool, {})
        assert needs_approval, f"{tool} must require approval"
        assert reason == "always_ask"


def test_session_approval_mode():
    mgr = get_approval_manager()

    # Initially off
    assert not mgr.session_approval_active
    needs_appr, reason = mgr.should_gate("click", {})
    assert needs_appr
    assert reason == "changes_state"

    # Turn session approval ON
    mgr.set_session_approval(True)
    assert mgr.session_approval_active

    # Standard changing tools now bypass
    needs_appr, reason = mgr.should_gate("click", {})
    assert not needs_appr
    assert reason == "session_approved"

    needs_appr, reason = mgr.should_gate("execute_command", {})
    assert not needs_appr
    assert reason == "session_approved"

    # ALWAYS-ASK tools STILL require approval even during session approval
    needs_appr, reason = mgr.should_gate("install_tool_git", {})
    assert needs_appr
    assert reason == "always_ask"

    # Revoke session approval
    mgr.set_session_approval(False)
    assert not mgr.session_approval_active
    needs_appr, reason = mgr.should_gate("click", {})
    assert needs_appr
    assert reason == "changes_state"


def test_request_approval_flow_approved():
    mgr = get_approval_manager()
    broadcasts = []
    setup_auto_responder(mgr, "approve", broadcasts)

    approved = mgr.request_approval("click", {"x": 100, "y": 200}, timeout=2.0)

    assert approved is True
    assert len(broadcasts) >= 1
    req_msg = [b for b in broadcasts if b.get("type") == "approval_request"][0]
    assert req_msg["tool_name"] == "click"
    assert "Click mouse" in req_msg["description"]


def test_request_approval_flow_denied():
    mgr = get_approval_manager()
    setup_auto_responder(mgr, "deny")

    approved = mgr.request_approval("type_text", {"text": "hello"}, timeout=2.0)

    assert approved is False


def test_request_approval_approve_session():
    mgr = get_approval_manager()
    assert not mgr.session_approval_active
    setup_auto_responder(mgr, "approve_session")

    approved = mgr.request_approval("click", {"x": 50, "y": 50}, timeout=2.0)

    assert approved is True
    assert mgr.session_approval_active is True


def test_request_approval_timeout():
    mgr = get_approval_manager()
    broadcasts = []
    mgr.set_broadcast_callback(lambda msg: broadcasts.append(msg))

    # Fast timeout without answering
    start_t = time.time()
    approved = mgr.request_approval("click", {"x": 1, "y": 1}, timeout=0.2)
    elapsed = time.time() - start_t

    assert approved is False
    assert 0.15 <= elapsed <= 0.6
    timeout_msgs = [b for b in broadcasts if b.get("type") == "approval_timeout"]
    assert len(timeout_msgs) >= 1


def test_request_approval_halt_interruption():
    mgr = get_approval_manager()
    bus = get_event_bus()

    # When approval request is broadcast, trigger HALT immediately
    def on_broadcast(msg):
        if msg.get("type") == "approval_request":
            threading.Thread(target=lambda: bus.publish_halt("test")).start()
    mgr.set_broadcast_callback(on_broadcast)

    start_t = time.time()
    approved = mgr.request_approval("click", {"x": 10, "y": 10}, timeout=5.0)
    elapsed = time.time() - start_t

    assert approved is False
    # Should abort within ~0.3s rather than waiting full 5.0s
    assert elapsed < 1.0


def test_change_log_persistence_and_filtering():
    store = get_sqlite_store()

    # Insert test records
    id1 = store.add_change_log(
        what_changed="Added task 'Review spec'",
        prompted_by="User request",
        approval_status="no_approval_needed",
        tool_name="add_task",
        details="Title: Review spec",
    )
    assert id1 > 0

    id2 = store.add_change_log(
        what_changed="Click mouse at (100, 200)",
        prompted_by="User request",
        approval_status="individual",
        tool_name="click",
        details="Button: left",
    )
    assert id2 > id1

    # Fetch all
    entries = store.get_change_logs(limit=10)
    assert len(entries) >= 2
    row1 = [e for e in entries if e["id"] == id1][0]
    assert row1["what_changed"] == "Added task 'Review spec'"
    assert row1["approval_status"] == "no_approval_needed"

    row2 = [e for e in entries if e["id"] == id2][0]
    assert row2["what_changed"] == "Click mouse at (100, 200)"
    assert row2["approval_status"] == "individual"

    # Date filter with today
    import datetime
    today_str = datetime.date.today().isoformat()
    today_entries = store.get_change_logs(limit=10, date_filter=today_str)
    assert any(e["id"] == id1 for e in today_entries)

    # Date filter with past date
    past_entries = store.get_change_logs(limit=10, date_filter="2020-01-01")
    assert len(past_entries) == 0


def test_tool_executor_gating_integration():
    executor = UniversalToolExecutor()
    mgr = get_approval_manager()

    # 1. Denied tool execution returns error dictionary
    setup_auto_responder(mgr, "deny")
    res = executor.execute("click", {"x": 200, "y": 300})

    assert "error" in res
    assert res.get("denied") is True
