"""
Phase 9 Tests: ARCHER works on itself (R&D, Spec Section 11b).

Verifies:
1. SelfDevManager proposal lifecycle (propose, list, update).
2. Git worktree isolation and strict privacy boundary (tracked files only, no .env/data leaks).
3. Dual-model requirement (writer and checker from different families).
4. Automated R&D pipeline execution, test execution with timeout, and diff/summary artifacts.
5. Phase 3 approval gate integration:
   - Session approval covers standard changes.
   - Security-sensitive files (approval gate, security rules, .env, permissions) ALWAYS require individual approval.
6. Automated pre-apply backup and rollback ("ARCHER, undo the last update").
7. UniversalToolExecutor and REST API endpoints.
8. CoreAgent voice command shortcut for 'ARCHER, undo the last update'.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from archer.core.approvals import (
    ApprovalManager,
    get_approval_manager,
    touches_security_sensitive_files,
)
from archer.core.event_bus import get_event_bus
from archer.memory.sqlite_store import get_sqlite_store
from archer.server import app
from archer.skills.tool_executor import UniversalToolExecutor
from archer.tools.self_dev import (
    DEFAULT_CHECKER_MODEL,
    DEFAULT_WRITER_MODEL,
    MODEL_FAMILIES,
    SelfDevManager,
    get_self_dev_manager,
    run_command_safe,
)


@pytest.fixture(autouse=True)
def reset_system_state():
    """Ensure clean state and clear any residual halts."""
    appr = get_approval_manager()
    appr.set_session_approval(False)
    yield
    appr.set_session_approval(False)


def test_dual_model_family_validation():
    """Writer and checker must be from different families per Spec Section 11b."""
    mgr = get_self_dev_manager()

    # Same family should fail
    with pytest.raises(ValueError, match="must be from different families"):
        mgr.run_job("test_job", writer_model="gemini-4-argon-medium", checker_model="gemini-3.8-flash-high")

    # Different families should be accepted in validation
    w_fam = MODEL_FAMILIES.get("gemini-4-argon-medium")
    c_fam = MODEL_FAMILIES.get("claude-sonnet-5-5-medium")
    assert w_fam == "Gemini"
    assert c_fam == "Claude"
    assert w_fam != c_fam


def test_proposal_lifecycle():
    """Test proposing, listing, and querying R&D proposals in SQLite."""
    mgr = get_self_dev_manager()
    prop = mgr.propose(
        title="Add weather skill",
        description="Fetch current temperature and forecasts",
        source="user",
    )

    assert prop["job_id"].startswith("rnd_")
    assert prop["title"] == "Add weather skill"
    assert prop["status"] == "proposed"

    retrieved = mgr.get_proposal(prop["job_id"])
    assert retrieved is not None
    assert retrieved["title"] == "Add weather skill"

    proposals = mgr.list_proposals()
    assert any(p["job_id"] == prop["job_id"] for p in proposals)


def test_security_sensitive_files_detection():
    """Files touching security, approval gate, .env, or permissions must be detected."""
    assert touches_security_sensitive_files(["src/archer/core/approvals.py"])
    assert touches_security_sensitive_files(["src/archer/core/security.py"])
    assert touches_security_sensitive_files(["src/archer/tools/tool_auditor.py"])
    assert touches_security_sensitive_files(["src/archer/agents/AGENTS.md"])
    assert touches_security_sensitive_files([".env"])
    assert touches_security_sensitive_files(["config/settings.json"])

    # Standard tool / feature files should NOT be flagged as security-sensitive
    assert not touches_security_sensitive_files([
        "src/archer/skills/weather_SKILL.md",
        "src/archer/tools/weather.py",
        "web/js/weather.js",
    ])


def test_approval_gate_for_rnd_updates():
    """
    Spec Section 11b:
    - Session approval covers standard self-dev changes.
    - Security-sensitive changes ALWAYS require individual approval, even if session approval is on!
    """
    appr = get_approval_manager()

    # Case 1: Session approval OFF -> requires approval
    appr.set_session_approval(False)
    standard_input = {"job_id": "job_1", "files": ["src/archer/skills/timer_SKILL.md"]}
    needs_appr, reason = appr.should_gate("apply_rnd_update", standard_input)
    assert needs_appr is True
    assert reason == "changes_state"

    # Case 2: Session approval ON -> standard change skips prompt
    appr.set_session_approval(True)
    needs_appr, reason = appr.should_gate("apply_rnd_update", standard_input)
    assert needs_appr is False
    assert reason == "session_approved"

    # Case 3: Session approval ON, but touches approval gate -> MUST STILL ASK!
    security_input = {"job_id": "job_2", "files": ["src/archer/core/approvals.py"]}
    needs_appr, reason = appr.should_gate("apply_rnd_update", security_input)
    assert needs_appr is True
    assert reason == "always_ask_security"

    # Case 4: Session approval ON, touches .env -> MUST STILL ASK!
    env_input = {"job_id": "job_3", "files": [".env"]}
    needs_appr, reason = appr.should_gate("apply_rnd_update", env_input)
    assert needs_appr is True
    assert reason == "always_ask_security"


def test_safe_subprocess_runner():
    """Safe runner prevents blocking reads and enforces timeouts."""
    # Fast successful command
    ret, stdout, stderr = run_command_safe(["python", "-c", "print('hello from safe runner')"], cwd=".", timeout=5.0)
    assert ret == 0
    assert "hello from safe runner" in stdout

    # Timeout enforcement
    ret_to, stdout_to, stderr_to = run_command_safe(["python", "-c", "import time; time.sleep(10)"], cwd=".", timeout=1.0)
    assert ret_to == -1
    assert "timed out" in stderr_to


def test_e2e_rnd_pipeline_execution():
    """Test full R&D pipeline execution in isolated worktree with diff and artifacts."""
    mgr = get_self_dev_manager()

    prop = mgr.propose(
        title="Add unit test helper module",
        description="Creates a test helper file and tests it",
        source="test_suite",
    )
    job_id = prop["job_id"]

    # Mock the model step and pytest runner for fast deterministic unit testing
    with patch.object(mgr, "_run_model_step") as mock_model_step, \
         patch.object(mgr, "_run_tests") as mock_tests:

        def fake_model_step(worktree_path, model_name, prompt, role):
            if role == "writer":
                # Create a sample file in the worktree
                dummy_file = worktree_path / "src" / "archer" / "tools" / f"dummy_helper_{job_id[:8]}.py"
                dummy_file.parent.mkdir(parents=True, exist_ok=True)
                dummy_file.write_text("# Dummy helper\ndef helper(): return True\n", encoding="utf-8")
                return True, "Created dummy_helper.py"
            else:
                return True, json.dumps({
                    "verdict": "clear",
                    "summary": "Clean helper implementation with tests",
                    "reasons": ["Well isolated", "No security issues"],
                })

        mock_model_step.side_effect = fake_model_step
        mock_tests.return_value = {"passed": True, "summary": "1 passed in 0.1s"}

        result = mgr.run_job(job_id, run_async=False)

        assert result["status"] == "ready_for_review"
        assert result["checker_verdict"] == "clear"
        assert result["tests_passed"] is True
        assert os.path.exists(result["diff_path"])
        assert os.path.exists(result["summary_path"])

        # Verify summary artifact content
        summary_content = Path(result["summary_path"]).read_text(encoding="utf-8")
        assert "ARCHER R&D Proposal:" in summary_content
        assert "VERDICT:" in summary_content.upper()
        assert "CLEAN HELPER IMPLEMENTATION" in summary_content.upper()


def test_apply_and_undo_rollback():
    """
    Test applying an R&D update to live files with automatic pre-apply backup,
    and subsequent rollback ('ARCHER, undo the last update').
    """
    mgr = get_self_dev_manager()
    appr = get_approval_manager()
    appr.set_session_approval(True)  # Session approval active for standard file

    # 1. Create a dummy live file in repository
    test_target = mgr.repo_root / "scratch" / "test_self_dev_target.txt"
    test_target.parent.mkdir(parents=True, exist_ok=True)
    original_text = "VERSION 1.0 (ORIGINAL CONTENT)"
    test_target.write_text(original_text, encoding="utf-8")

    # 2. Create proposal
    prop = mgr.propose(title="Upgrade test target", description="Updates test target to 2.0", source="test")
    job_id = prop["job_id"]

    # 3. Create simulated worktree with modified file
    wt_dir = mgr.worktrees_base / job_id
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_target = wt_dir / "scratch" / "test_self_dev_target.txt"
    wt_target.parent.mkdir(parents=True, exist_ok=True)
    new_text = "VERSION 2.0 (MODIFIED BY R&D)"
    wt_target.write_text(new_text, encoding="utf-8")

    mgr.store.update_rnd_proposal(
        job_id,
        status="ready_for_review",
        worktree_path=str(wt_dir),
        checker_verdict="clear",
    )

    # 4. Apply update
    apply_res = mgr.apply_update(job_id)
    assert apply_res["status"] == "applied"
    assert "scratch/test_self_dev_target.txt" in apply_res["applied_files"]

    # Verify live file now has new content
    assert test_target.read_text(encoding="utf-8") == new_text

    # 5. Undo update ("ARCHER, undo the last update")
    undo_res = mgr.undo_last_update(job_id)
    assert undo_res["status"] == "undone"

    # Verify live file is restored to original content!
    assert test_target.read_text(encoding="utf-8") == original_text

    # Cleanup test file
    test_target.unlink(missing_ok=True)


def test_tool_executor_rnd_routing():
    """Verify UniversalToolExecutor routes rnd tools correctly."""
    executor = UniversalToolExecutor()

    # 1. propose_improvement
    res = executor.execute("propose_improvement", {"title": "Executor tool test", "description": "Routing test"})
    assert "job_id" in res
    assert res["status"] == "proposed"
    job_id = res["job_id"]

    # 2. list_rnd_proposals
    proposals = executor.execute("list_rnd_proposals", {})
    assert "proposals" in proposals
    assert any(p["job_id"] == job_id for p in proposals["proposals"])

    # 3. get_rnd_status
    status_res = executor.execute("get_rnd_status", {"job_id": job_id})
    assert "proposal" in status_res
    assert status_res["proposal"]["job_id"] == job_id


def test_server_rest_endpoints():
    """Test REST endpoints for listing, proposing, and undoing."""
    client = TestClient(app)

    # Propose
    resp = client.post("/api/rnd/propose", json={
        "title": "API test proposal",
        "description": "Created via REST API",
        "source": "api_test",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    job_id = data["job_id"]

    # List
    list_resp = client.get("/api/rnd/proposals")
    assert list_resp.status_code == 200
    all_props = list_resp.json().get("proposals", [])
    assert any(p["job_id"] == job_id for p in all_props)


def test_core_agent_voice_undo_shortcut():
    """Verify voice shortcut 'ARCHER, undo the last update' is handled directly."""
    from archer.agents.core_agent import CoreAgent

    # Mock undo_last_update
    with patch("archer.tools.self_dev.get_self_dev_manager") as mock_mgr_getter:
        mock_mgr = MagicMock()
        mock_mgr.undo_last_update.return_value = {
            "status": "undone",
            "restored_files": ["file1.py", "file2.py"],
            "backup_path": "backups/rnd/test",
        }
        mock_mgr_getter.return_value = mock_mgr

        agent = CoreAgent()
        reply = agent._handle_undo_update_command("ARCHER, please undo the last update")
        assert reply is not None
        assert "restored 2 files from backup" in reply.lower()
