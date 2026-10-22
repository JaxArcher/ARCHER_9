"""
Unit and integration tests for Phase 6 Terminal (Spec Section 9).

Tests:
- PowerShell PTY start, process liveness, and singleton semantics.
- Non-blocking reader thread and broadcast streaming.
- ARCHER command execution with [ARCHER] prefix and clean output retrieval.
- Error handling on failed commands.
- HALT interruption (Ctrl+C).
- Window resizing and history ring-buffer retrieval.
- Approval gating and UniversalToolExecutor routing.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List
import pytest

from archer.core.approvals import get_approval_manager
from archer.core.event_bus import get_event_bus
from archer.skills.tool_executor import UniversalToolExecutor
from archer.tools.terminal_manager import TerminalManager, get_terminal_manager


@pytest.fixture(scope="module")
def term_manager():
    mgr = get_terminal_manager()
    yield mgr
    mgr.stop()


def test_terminal_manager_singleton(term_manager: TerminalManager):
    """Test that TerminalManager follows singleton pattern."""
    mgr2 = get_terminal_manager()
    assert term_manager is mgr2


def test_terminal_manager_start_and_liveness(term_manager: TerminalManager):
    """Test starting the PowerShell PTY session and checking liveness."""
    started = term_manager.start(cols=80, rows=24)
    assert started is True
    assert term_manager.is_alive() is True


def test_terminal_manager_write_and_stream(term_manager: TerminalManager):
    """Test direct keyboard input and broadcast callback streaming."""
    received_chunks: List[str] = []

    def on_broadcast(chunk: str):
        received_chunks.append(chunk)

    term_manager.set_broadcast_callback(on_broadcast)
    term_manager.write("Write-Output 'KEYBOARD_STREAM_TEST'\r\n")

    # Wait up to 3 seconds for chunks without blocking
    start_t = time.time()
    while time.time() - start_t < 3.0:
        if any("KEYBOARD_STREAM_TEST" in c for c in received_chunks):
            break
        time.sleep(0.1)

    combined = "".join(received_chunks)
    assert "KEYBOARD_STREAM_TEST" in combined
    term_manager.set_broadcast_callback(None)


def test_terminal_execute_archer_command_success(term_manager: TerminalManager):
    """Test executing an ARCHER command visibly with clean output capture."""
    res = term_manager.execute_archer_command("Write-Output 'ARCHER_CMD_SUCCESS_TOKEN'", timeout=10.0)

    assert res.get("status") == "success"
    assert res.get("success") is True
    assert "ARCHER_CMD_SUCCESS_TOKEN" in res.get("output", "")
    # Ensure raw prompt/end markers are stripped from summary
    assert "__ARCHER_END__" not in res.get("output", "")


def test_terminal_execute_archer_command_failure(term_manager: TerminalManager):
    """Test executing a failing PowerShell command and catching error status."""
    res = term_manager.execute_archer_command(
        "Get-Item 'C:\\archer_nonexistent_test_path_12345'",
        timeout=10.0,
    )
    # The command should complete but report failed status
    assert res.get("status") == "failed" or res.get("success") is False


def test_terminal_halt_interruption(term_manager: TerminalManager):
    """Test that HALT cancels in-flight command execution immediately via Ctrl+C."""
    result_holder: Dict[str, Any] = {}

    def run_long_cmd():
        res = term_manager.execute_archer_command("Start-Sleep -Seconds 15", timeout=12.0)
        result_holder.update(res)

    t = threading.Thread(target=run_long_cmd)
    t.start()

    # Wait briefly for command to begin execution
    time.sleep(0.4)

    # Trigger HALT
    term_manager.on_halt()
    t.join(timeout=4.0)

    assert not t.is_alive(), "Command thread hung after HALT"
    assert result_holder.get("status") in ("halted", "timeout", "failed")


def test_terminal_resize_and_history(term_manager: TerminalManager):
    """Test resizing dimensions and fetching terminal ring-buffer history."""
    term_manager.resize(cols=120, rows=40)
    history = term_manager.get_history()

    assert isinstance(history, str)
    assert len(history) > 0
    assert "ARCHER_CMD_SUCCESS_TOKEN" in history or "KEYBOARD_STREAM_TEST" in history


def test_terminal_approval_gating():
    """Test that run_terminal_command requires approval in Phase 3 gate."""
    approvals = get_approval_manager()

    # When session approval is False, terminal commands must require approval
    approvals.session_approval_active = False
    needs_approval, reason = approvals.should_gate("run_terminal_command", {"command": "dir"})
    assert needs_approval is True
    assert reason == "changes_state"

    # Action description
    action_type, desc, details = approvals.describe_action("run_terminal_command", {"command": "dir"})
    assert action_type == "terminal_command"
    assert "dir" in desc


def test_terminal_universal_tool_executor_routing(term_manager: TerminalManager):
    """Test executing run_terminal_command via UniversalToolExecutor under session approval."""
    executor = UniversalToolExecutor()
    approvals = get_approval_manager()

    approvals.session_approval_active = True
    try:
        res = executor.execute("run_terminal_command", {"command": "Write-Output 'TOOL_ROUTER_PHASE6'"})
        assert res.get("status") == "success"
        assert "TOOL_ROUTER_PHASE6" in res.get("output", "")
    finally:
        approvals.session_approval_active = False
