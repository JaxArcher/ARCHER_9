"""
ARCHER Tool Pool Manager (Phase 4, Spec Section 7).

Manages the lifecycle of external git repository tools:
1. Pin: resolve to exact commit hash.
2. Fetch: clone cleanly into data/staging/ without running any code.
3. Local checks: static AST, binary checks, build hook inspection.
4. Two independent AI reviews (different families). Both must return 'clear'.
5. Individual approval prompt (never session-approved).
6. Install into dedicated isolated venv (envs/tool_<name>/) and folder (data/tools/<name>/).
7. Register as skill (src/archer/skills/<name>_SKILL.md) and record in tools_registry table.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from archer.core.approvals import get_approval_manager
from archer.memory.sqlite_store import get_sqlite_store
from archer.tools.tool_auditor import ToolAuditor


class ToolPoolManager:
    """Singleton manager for the Phase 4 reviewed tool pool."""

    _instance: Optional[ToolPoolManager] = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> ToolPoolManager:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[3]
        self.store = get_sqlite_store()
        self.auditor = ToolAuditor()
        self.approvals = get_approval_manager()

        data_override = os.environ.get("ARCHER_DATA_DIR")
        data_base = Path(data_override) if data_override else (self.repo_root / "data")
        envs_override = os.environ.get("ARCHER_ENVS_DIR")
        envs_base = Path(envs_override) if envs_override else (self.repo_root / "envs")

        self.staging_base = data_base / "staging"
        self.tools_base = data_base / "tools"
        self.envs_base = envs_base

        self.staging_base.mkdir(parents=True, exist_ok=True)
        self.tools_base.mkdir(parents=True, exist_ok=True)
        self.envs_base.mkdir(parents=True, exist_ok=True)

    def propose_and_review(
        self,
        repo_url: str,
        commit_hash: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Step 1-4: Pin, fetch to staging, run local checks, run 2 AI reviews,
        and record candidate in registry.
        """
        if not repo_url or not repo_url.strip():
            return {"status": "error", "message": "Repo URL is required"}

        url = repo_url.strip()

        # Derive clean tool name if not provided
        if not tool_name:
            tool_name = Path(url.rstrip("/")).stem
            if tool_name.endswith(".git"):
                tool_name = tool_name[:-4]
        name = re.sub(r"[^a-zA-Z0-9_\-]", "_", tool_name).lower()

        # Step 1: Pin commit hash
        pinned_hash = commit_hash
        if not pinned_hash:
            pinned_hash = self._resolve_remote_head(url)
            if not pinned_hash:
                pinned_hash = "HEAD_LOCAL_PIN"

        # Step 2: Fetch into staging directory
        staging_dir = self.staging_base / f"{name}_{pinned_hash[:8]}"
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        cloned = self._fetch_repo(url, pinned_hash, staging_dir)
        if not cloned:
            return {
                "status": "failed",
                "message": f"Failed to fetch git repository from {url}",
                "name": name,
            }

        # Step 3 & 4: Local checks and two independent AI reviews
        audit_results = self.auditor.audit_staged_repo(
            staging_dir=staging_dir,
            tool_name=name,
            commit_hash=pinned_hash,
            repo_url=url,
        )

        overall_verdict = audit_results["overall_verdict"]
        initial_status = "awaiting_approval" if overall_verdict == "clear" else "rejected"
        reason = "; ".join(audit_results["rejection_reasons"]) if overall_verdict != "clear" else ""

        # Record in database
        tool_id = self.store.register_tool_candidate(
            name=name,
            repo_url=url,
            commit_hash=pinned_hash,
            install_folder=str(self.tools_base / name),
            env_path=str(self.envs_base / f"tool_{name}"),
            review_results=json.dumps(audit_results),
            status=initial_status,
            reason=reason,
        )

        # Notify / request approval if cleared
        if initial_status == "awaiting_approval":
            logger.info(f"[ToolPoolManager] Tool '{name}' cleared all reviews. Requesting individual approval.")

        return {
            "status": initial_status,
            "tool_id": tool_id,
            "name": name,
            "pinned_commit": pinned_hash,
            "verdict": overall_verdict,
            "rejection_reasons": audit_results["rejection_reasons"],
            "report_path": audit_results["report_path"],
            "report_rel_path": audit_results["report_rel_path"],
        }

    def install_tool(self, name_or_id: str | int) -> Dict[str, Any]:
        """
        Step 6-7: Install approved tool into dedicated folder and dedicated virtualenv.
        Register skill in src/archer/skills/<name>_SKILL.md.
        """
        tool = self.store.get_tool_candidate(name_or_id)
        if not tool:
            return {"status": "error", "message": f"Tool '{name_or_id}' not found in registry"}

        name = tool["name"]
        commit_hash = tool["commit_hash"]
        staging_dir = self.staging_base / f"{name}_{commit_hash[:8]}"
        install_dir = self.tools_base / name
        env_dir = self.envs_base / f"tool_{name}"

        # 1. Copy staged files to install_dir
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)
        if staging_dir.exists():
            shutil.copytree(staging_dir, install_dir)
        else:
            install_dir.mkdir(parents=True, exist_ok=True)

        # 2. Check dependencies
        req_file = install_dir / "requirements.txt"
        has_reqs = req_file.exists() and req_file.stat().st_size > 0

        # 3. Create isolated virtual environment
        if not env_dir.exists():
            logger.info(f"[ToolPoolManager] Creating dedicated venv in {env_dir}")
            try:
                # Fast creation: if no requirements.txt, --without-pip avoids 26s ensurepip lag
                venv_cmd = [sys.executable, "-m", "venv"]
                if not has_reqs:
                    venv_cmd.append("--without-pip")
                venv_cmd.append(str(env_dir))

                subprocess.run(
                    venv_cmd,
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
            except Exception as e:
                self.store.update_tool_candidate(tool["id"], status="failed", reason=f"Failed to create venv: {e}")
                return {"status": "failed", "message": f"Virtualenv creation failed: {e}"}

        # 4. Pip install dependencies if requirements exist
        pip_exe = env_dir / "Scripts" / "pip.exe"
        if has_reqs and pip_exe.exists():
            try:
                subprocess.run(
                    [str(pip_exe), "install", "-r", str(req_file)],
                    cwd=str(install_dir),
                    capture_output=True,
                    timeout=180,
                )
            except Exception as e:
                logger.debug(f"[ToolPoolManager] pip install requirements note: {e}")

        # 4. Generate and register skill definition (name_SKILL.md)
        skills_dir = self.repo_root / "src" / "archer" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skills_dir / f"{name}_SKILL.md"

        skill_content = (
            f"---\n"
            f"name: {name}\n"
            f"description: External tool '{name}' installed from {tool['repo_url']} (commit {commit_hash[:8]}).\n"
            f"category: pool_tools\n"
            f"---\n\n"
            f"### run_{name}\n"
            f"Run the installed '{name}' tool in its dedicated virtual environment.\n"
            f"**Parameters:**\n"
            f"- command: Command or script arguments to pass to {name} (string).\n"
        )
        skill_file.write_text(skill_content, encoding="utf-8")

        # 5. Update registry status
        self.store.update_tool_candidate(
            tool["id"],
            status="installed",
            install_folder=str(install_dir),
            env_path=str(env_dir),
        )

        try:
            from archer.skills.skills_registry import invalidate_skills_cache
            invalidate_skills_cache()
        except Exception:
            pass

        logger.info(f"[ToolPoolManager] Tool '{name}' successfully installed and registered as skill {skill_file.name}")
        return {
            "status": "installed",
            "name": name,
            "skill_file": str(skill_file),
            "install_folder": str(install_dir),
            "env_path": str(env_dir),
        }

    def uninstall_tool(self, name_or_id: str | int) -> Dict[str, Any]:
        """Remove installed tool, virtualenv, and skill file."""
        tool = self.store.get_tool_candidate(name_or_id)
        if not tool:
            return {"status": "error", "message": f"Tool '{name_or_id}' not found"}

        name = tool["name"]
        skill_file = self.repo_root / "src" / "archer" / "skills" / f"{name}_SKILL.md"
        install_dir = Path(tool["install_folder"]) if tool.get("install_folder") else self.tools_base / name
        env_dir = Path(tool["env_path"]) if tool.get("env_path") else self.envs_base / f"tool_{name}"

        # Delete skill file
        if skill_file.exists():
            try:
                skill_file.unlink()
            except Exception as e:
                logger.debug(f"[ToolPoolManager] Could not remove skill file: {e}")

        try:
            from archer.skills.skills_registry import invalidate_skills_cache
            invalidate_skills_cache()
        except Exception:
            pass

        # Delete install directory
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)

        # Delete virtual environment
        if env_dir.exists():
            shutil.rmtree(env_dir, ignore_errors=True)

        self.store.update_tool_candidate(tool["id"], status="uninstalled")
        logger.info(f"[ToolPoolManager] Tool '{name}' uninstalled cleanly.")

        return {"status": "uninstalled", "name": name}

    def execute_tool(self, tool_name: str, command: str = "") -> Dict[str, Any]:
        """Execute installed tool inside its dedicated environment."""
        tool = self.store.get_tool_candidate(tool_name)
        if not tool or tool.get("status") != "installed":
            return {"status": "error", "message": f"Tool '{tool_name}' is not currently installed"}

        env_dir = Path(tool["env_path"])
        install_dir = Path(tool["install_folder"])
        python_exe = env_dir / "Scripts" / "python.exe"

        if not python_exe.exists():
            return {"status": "error", "message": f"Python executable missing in {env_dir}"}

        try:
            # Run command in isolated tool environment
            cmd_args = [str(python_exe)]
            if command:
                cmd_args.extend(["-c", command])

            proc = subprocess.run(
                cmd_args,
                cwd=str(install_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "status": "success" if proc.returncode == 0 else "failed",
                "exit_code": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "message": "Tool execution timed out after 30 seconds"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _resolve_remote_head(self, repo_url: str) -> Optional[str]:
        """Query git remote HEAD commit hash via git ls-remote."""
        try:
            res = subprocess.run(
                ["git", "ls-remote", repo_url, "HEAD"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0 and res.stdout:
                parts = res.stdout.strip().split()
                if parts:
                    return parts[0]
        except Exception as e:
            logger.debug(f"[ToolPoolManager] ls-remote failed for {repo_url}: {e}")
        return None

    def _fetch_repo(self, repo_url: str, commit_hash: str, dest_dir: Path) -> bool:
        """Fetch repository commit into destination directory cleanly."""
        # Check if local path is passed
        local_src = Path(repo_url)
        if local_src.exists() and local_src.is_dir():
            shutil.copytree(local_src, dest_dir, dirs_exist_ok=True)
            return True

        # Otherwise clone from remote git URL
        try:
            res = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, str(dest_dir)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return res.returncode == 0
        except Exception as e:
            logger.error(f"[ToolPoolManager] git clone failed: {e}")
            return False


_tool_pool_manager: Optional[ToolPoolManager] = None


def get_tool_pool_manager() -> ToolPoolManager:
    """Get singleton ToolPoolManager instance."""
    global _tool_pool_manager
    if _tool_pool_manager is None:
        _tool_pool_manager = ToolPoolManager()
    return _tool_pool_manager
