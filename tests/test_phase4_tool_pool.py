"""
Unit and integration tests for Phase 4 Tool Pool with Reviewed Installs (Spec Section 7).

Acceptance criteria from Spec Section 7:
- A deliberately harmless test repo goes through every step and installs, then appears in the Tools tab;
- A test repo with an obvious risky install hook or bundled binary is stopped at the local checks or reviews;
- No git-repo tool installs without Col's individual approval (never covered by session approval).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict
import pytest

from archer.core.approvals import get_approval_manager
from archer.memory.sqlite_store import get_sqlite_store
from archer.skills.tool_executor import UniversalToolExecutor
from archer.tools.tool_auditor import LocalSecurityScanner, ToolAuditor
from archer.tools.tool_pool_manager import ToolPoolManager, get_tool_pool_manager


@pytest.fixture(autouse=True)
def isolated_tool_pool_dirs(tmp_path: Path, monkeypatch):
    """Isolate tool pool staging, install, and venvs into tmp_path for test isolation."""
    test_data = tmp_path / "test_archer_data"
    test_envs = tmp_path / "test_archer_envs"
    test_data.mkdir(parents=True, exist_ok=True)
    test_envs.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("ARCHER_DATA_DIR", str(test_data))
    monkeypatch.setenv("ARCHER_ENVS_DIR", str(test_envs))

    # Re-init manager with test paths
    mgr = get_tool_pool_manager()
    mgr._init_manager()
    yield mgr


@pytest.fixture
def temp_clean_repo(tmp_path: Path) -> Path:
    """Create a harmless test repository with pure Python code."""
    repo_dir = tmp_path / "harmless_math_tool"
    repo_dir.mkdir(parents=True, exist_ok=True)

    pyproject = repo_dir / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "harmless_math_tool"\nversion = "0.1.0"\ndescription = "Harmless math helpers"\n',
        encoding="utf-8",
    )

    code_file = repo_dir / "main.py"
    code_file.write_text(
        "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    return repo_dir


@pytest.fixture
def temp_malicious_repo(tmp_path: Path) -> Path:
    """Create a test repository containing dangerous shellouts, eval, and bundled binaries."""
    repo_dir = tmp_path / "risky_exploit_tool"
    repo_dir.mkdir(parents=True, exist_ok=True)

    setup_file = repo_dir / "setup.py"
    setup_file.write_text(
        "from setuptools import setup\n"
        "# Custom hook\n"
        "class PostInstallCommand:\n"
        "    pass\n"
        "setup(name='risky_tool', version='0.1.0', cmdclass={'install': PostInstallCommand})\n",
        encoding="utf-8",
    )

    payload_file = repo_dir / "backdoor.py"
    payload_file.write_text(
        "import os\n"
        "def run_exploit(cmd):\n"
        "    os.system(cmd)\n"
        "    eval('__import__(\"os\").getcwd()')\n",
        encoding="utf-8",
    )

    fake_bin = repo_dir / "malicious_payload.exe"
    fake_bin.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00fake_binary_content")

    return repo_dir


def test_local_security_scanner_clean(temp_clean_repo: Path):
    """Test that harmless repo passes static checks with 0 critical findings."""
    scanner = LocalSecurityScanner()
    res = scanner.scan(temp_clean_repo)

    assert res["passed"] is True
    assert res["risk_level"] == "LOW"
    assert len(res["bundled_binaries"]) == 0
    assert len(res["dynamic_evals"]) == 0
    assert len(res["shell_calls"]) == 0


def test_local_security_scanner_detects_malicious_patterns(temp_malicious_repo: Path):
    """Test that risky repo is flagged for bundled binaries, install hooks, and eval."""
    scanner = LocalSecurityScanner()
    res = scanner.scan(temp_malicious_repo)

    assert res["passed"] is False
    assert res["risk_level"] == "CRITICAL"
    assert len(res["bundled_binaries"]) == 1
    assert "malicious_payload.exe" in res["bundled_binaries"][0]
    assert len(res["dynamic_evals"]) >= 1
    assert len(res["shell_calls"]) >= 1
    assert len(res["install_hooks"]) >= 1


def test_tool_auditor_generates_markdown_report(temp_clean_repo: Path):
    """Test full audit run generating markdown report in data/artifacts/reviews/."""
    auditor = ToolAuditor()
    report = auditor.audit_staged_repo(
        staging_dir=temp_clean_repo,
        tool_name="test_math",
        commit_hash="abc1234567890",
        repo_url="https://github.com/test/test_math.git",
    )

    assert report["overall_verdict"] == "clear"
    report_file = Path(report["report_path"])
    assert report_file.exists(), f"Report file not found: {report_file}"

    content = report_file.read_text(encoding="utf-8")
    assert "Security Review Report: test_math" in content
    assert "Local Security Scan" in content
    assert "Independent AI Review 1" in content
    assert "Independent AI Review 2" in content
    assert "**CLEARED**" in content


def test_tool_pool_propose_and_review_clean_repo(temp_clean_repo: Path):
    """Test proposing clean tool candidate results in awaiting_approval status in registry."""
    mgr = get_tool_pool_manager()
    res = mgr.propose_and_review(
        repo_url=str(temp_clean_repo),
        commit_hash="1122334455667788",
        tool_name="clean_test_calc",
    )

    assert res["status"] == "awaiting_approval"
    assert res["verdict"] == "clear"
    assert res["pinned_commit"] == "1122334455667788"

    # Verify candidate saved in database
    store = get_sqlite_store()
    tool_entry = store.get_tool_candidate("clean_test_calc")
    assert tool_entry is not None
    assert tool_entry["status"] == "awaiting_approval"
    assert tool_entry["commit_hash"] == "1122334455667788"


def test_tool_pool_propose_and_review_malicious_repo_rejected(temp_malicious_repo: Path):
    """Test proposing risky repo is rejected and reasons logged in registry."""
    mgr = get_tool_pool_manager()
    res = mgr.propose_and_review(
        repo_url=str(temp_malicious_repo),
        commit_hash="deadbeef12345678",
        tool_name="bad_exploit_tool",
    )

    assert res["status"] == "rejected"
    assert res["verdict"] == "rejected"
    assert len(res["rejection_reasons"]) > 0

    # Verify rejected candidate in database
    store = get_sqlite_store()
    tool_entry = store.get_tool_candidate("bad_exploit_tool")
    assert tool_entry is not None
    assert tool_entry["status"] == "rejected"
    assert len(tool_entry["reason"]) > 0


def test_tool_pool_approval_gate_never_bypassed_by_session_approval():
    """Verify install_tool_git ALWAYS requires approval even if session approval is True."""
    approvals = get_approval_manager()

    approvals.session_approval_active = True
    needs_appr, reason = approvals.should_gate("install_tool_git", {"repo_url": "https://github.com/test/tool"})
    assert needs_appr is True
    assert reason == "always_ask"

    action_type, desc, details = approvals.describe_action("install_tool_git", {"repo_url": "https://github.com/test/tool"})
    assert action_type == "tool_install"
    assert "https://github.com/test/tool" in desc


def test_tool_pool_install_registers_skill_and_executes(temp_clean_repo: Path):
    """Test full install lifecycle: venv creation, skill markdown registration, and tool routing."""
    mgr = get_tool_pool_manager()
    # 1. Propose
    prop_res = mgr.propose_and_review(
        repo_url=str(temp_clean_repo),
        commit_hash="9988776655443322",
        tool_name="sample_math_helper",
    )
    assert prop_res["status"] == "awaiting_approval"

    # 2. Install
    inst_res = mgr.install_tool("sample_math_helper")
    assert inst_res["status"] == "installed"

    # Verify skill file exists in src/archer/skills/
    skill_path = Path(inst_res["skill_file"])
    assert skill_path.exists()
    skill_text = skill_path.read_text(encoding="utf-8")
    assert "name: sample_math_helper" in skill_text
    assert "category: pool_tools" in skill_text

    # Verify registry updated
    store = get_sqlite_store()
    tool = store.get_tool_candidate("sample_math_helper")
    assert tool["status"] == "installed"

    # 3. Test execution through UniversalToolExecutor under session approval
    approvals = get_approval_manager()
    approvals.session_approval_active = True
    try:
        executor = UniversalToolExecutor()
        exec_res = executor.execute("run_sample_math_helper", {"command": "print(2 + 2)"})
        assert exec_res.get("status") == "success"
        assert exec_res.get("stdout") == "4"
    finally:
        approvals.session_approval_active = False

    # 4. Uninstall
    uninst_res = mgr.uninstall_tool("sample_math_helper")
    assert uninst_res["status"] == "uninstalled"
    assert not skill_path.exists()
    assert store.get_tool_candidate("sample_math_helper")["status"] == "uninstalled"
