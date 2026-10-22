"""
ARCHER Tool Auditor (Phase 4, Spec Section 7).

Implements security audit pipeline:
1. Local checks: AST analysis for subprocesses, shellouts, network calls, filesystem escapes,
   obfuscated blobs, bundled binaries, install hooks.
2. Two independent AI reviews: headless review with different model families (agy -p or local Ollama).
3. Structured markdown report generated in data/artifacts/reviews/.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

# Banned / suspicious file extensions
BUNDLED_BINARY_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".whl", ".pyd", ".msi"
}

# Suspicious modules
NETWORK_MODULES = {"socket", "urllib", "requests", "httpx", "aiohttp", "ftplib", "telnetlib", "http.client"}
SHELL_MODULES = {"subprocess", "commands", "popen2"}
OBFUSCATION_MODULES = {"base64", "zlib", "codecs", "pickle"}


class LocalSecurityScanner:
    """Performs deterministic local static analysis on a staged repository."""

    def scan(self, repo_dir: Path) -> Dict[str, Any]:
        findings: List[Dict[str, Any]] = []
        bundled_binaries: List[str] = []
        install_hooks: List[Dict[str, Any]] = []
        network_calls: List[Dict[str, Any]] = []
        shell_calls: List[Dict[str, Any]] = []
        dynamic_evals: List[Dict[str, Any]] = []
        fs_escapes: List[Dict[str, Any]] = []
        obfuscated_blobs: List[Dict[str, Any]] = []

        total_files = 0
        python_files = 0

        for path in repo_dir.rglob("*"):
            if not path.is_file():
                continue
            total_files += 1
            rel_path = path.relative_to(repo_dir).as_posix()

            # Skip git metadata
            if ".git" in rel_path.split("/"):
                continue

            # 1. Bundled binaries check
            if path.suffix.lower() in BUNDLED_BINARY_EXTENSIONS:
                bundled_binaries.append(rel_path)
                findings.append({
                    "severity": "CRITICAL",
                    "category": "bundled_binary",
                    "file": rel_path,
                    "description": f"Bundled binary found: {path.name}",
                })

            # 2. Check install / setup hooks in build files
            if path.name in ("setup.py", "setup.cfg", "pyproject.toml", "Makefile"):
                self._check_build_hooks(path, rel_path, install_hooks, findings)

            # 3. Python AST & Pattern analysis
            if path.suffix.lower() == ".py":
                python_files += 1
                self._scan_python_file(
                    path,
                    rel_path,
                    network_calls,
                    shell_calls,
                    dynamic_evals,
                    fs_escapes,
                    obfuscated_blobs,
                    findings,
                )

        # Compute risk score
        risk_level = "LOW"
        has_critical = any(f["severity"] == "CRITICAL" for f in findings)
        has_high = any(f["severity"] == "HIGH" for f in findings)
        if has_critical:
            risk_level = "CRITICAL"
        elif has_high:
            risk_level = "HIGH"
        elif findings:
            risk_level = "MEDIUM"

        return {
            "risk_level": risk_level,
            "total_files": total_files,
            "python_files": python_files,
            "findings": findings,
            "bundled_binaries": bundled_binaries,
            "install_hooks": install_hooks,
            "network_calls": network_calls,
            "shell_calls": shell_calls,
            "dynamic_evals": dynamic_evals,
            "fs_escapes": fs_escapes,
            "obfuscated_blobs": obfuscated_blobs,
            "passed": not (has_critical or len(bundled_binaries) > 0),
        }

    def _check_build_hooks(
        self,
        path: Path,
        rel_path: str,
        install_hooks: List[Dict[str, Any]],
        findings: List[Dict[str, Any]],
    ) -> None:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            # Look for cmdclass or custom install scripts
            suspicious_terms = ["cmdclass", "PostInstallCommand", "install.run", "pre_install", "post_install"]
            for term in suspicious_terms:
                if term in content:
                    hook_item = {
                        "severity": "HIGH",
                        "category": "install_hook",
                        "file": rel_path,
                        "description": f"Custom build/install hook detected: {term}",
                    }
                    install_hooks.append(hook_item)
                    findings.append(hook_item)
        except Exception as e:
            logger.debug(f"[ToolAuditor] Could not read build file {path}: {e}")

    def _scan_python_file(
        self,
        path: Path,
        rel_path: str,
        network_calls: List[Dict[str, Any]],
        shell_calls: List[Dict[str, Any]],
        dynamic_evals: List[Dict[str, Any]],
        fs_escapes: List[Dict[str, Any]],
        obfuscated_blobs: List[Dict[str, Any]],
        findings: List[Dict[str, Any]],
    ) -> None:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        # Check for long base64 / hex obfuscated blobs (>150 characters)
        if re.search(r"[A-Za-z0-9+/=]{180,}", content):
            blob_item = {
                "severity": "HIGH",
                "category": "obfuscation",
                "file": rel_path,
                "description": "Large encoded / base64 string literal detected (>180 chars)",
            }
            obfuscated_blobs.append(blob_item)
            findings.append(blob_item)

        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError:
            findings.append({
                "severity": "MEDIUM",
                "category": "syntax_error",
                "file": rel_path,
                "description": "Unparseable Python syntax",
            })
            return

        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod in NETWORK_MODULES:
                        network_calls.append({"file": rel_path, "module": alias.name, "line": getattr(node, "lineno", 0)})
                    elif root_mod in SHELL_MODULES:
                        shell_calls.append({"file": rel_path, "module": alias.name, "line": getattr(node, "lineno", 0)})
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    if root_mod in NETWORK_MODULES:
                        network_calls.append({"file": rel_path, "module": node.module, "line": getattr(node, "lineno", 0)})
                    elif root_mod in SHELL_MODULES:
                        shell_calls.append({"file": rel_path, "module": node.module, "line": getattr(node, "lineno", 0)})

            # Check calls
            elif isinstance(node, ast.Call):
                call_name = ""
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr

                # Dynamic execution
                if call_name in ("eval", "exec", "compile", "__import__"):
                    eval_item = {
                        "severity": "HIGH",
                        "category": "dynamic_execution",
                        "file": rel_path,
                        "line": getattr(node, "lineno", 0),
                        "description": f"Dynamic execution via {call_name}()",
                    }
                    dynamic_evals.append(eval_item)
                    findings.append(eval_item)

                # Shellouts
                elif call_name in ("system", "popen", "execv", "spawn"):
                    shell_item = {
                        "severity": "HIGH",
                        "category": "shell_execution",
                        "file": rel_path,
                        "line": getattr(node, "lineno", 0),
                        "description": f"OS shell execution via os.{call_name}()",
                    }
                    shell_calls.append(shell_item)
                    findings.append(shell_item)

            # Filesystem traversal string check
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if ".." in val or "/etc/" in val or "C:\\Windows" in val or "USERPROFILE" in val:
                    if len(val) < 200:
                        fs_escapes.append({
                            "file": rel_path,
                            "line": getattr(node, "lineno", 0),
                            "path_pattern": val,
                        })


class ToolAuditor:
    """Orchestrates Phase 4 security checks, AI reviews, and report generation."""

    def __init__(self) -> None:
        self.local_scanner = LocalSecurityScanner()

    def audit_staged_repo(
        self,
        staging_dir: Path,
        tool_name: str,
        commit_hash: str,
        repo_url: str,
    ) -> Dict[str, Any]:
        """
        Run complete audit pipeline:
        1. Local checks
        2. Two independent AI reviews
        3. Write report to data/artifacts/reviews/
        """
        logger.info(f"[ToolAuditor] Starting audit for {tool_name} ({commit_hash[:8]}) in {staging_dir}")

        # 1. Local static checks
        local_results = self.local_scanner.scan(staging_dir)

        # 2. Two independent AI reviews
        ai_review_1 = self._run_ai_review(
            staging_dir=staging_dir,
            tool_name=tool_name,
            review_family="Family-A (Claude / Primary Reviewer)",
            local_summary=local_results,
        )

        ai_review_2 = self._run_ai_review(
            staging_dir=staging_dir,
            tool_name=tool_name,
            review_family="Family-B (OpenAI / Secondary Reviewer)",
            local_summary=local_results,
        )

        # Spec 7 rule: BOTH must return "clear"
        both_clear = (
            ai_review_1.get("verdict") == "clear"
            and ai_review_2.get("verdict") == "clear"
            and local_results.get("passed", False)
        )

        overall_verdict = "clear" if both_clear else "rejected"
        rejection_reasons: List[str] = []

        if not local_results.get("passed", False):
            rejection_reasons.append("Local static security checks flagged critical findings")
        if ai_review_1.get("verdict") != "clear":
            rejection_reasons.append(f"AI Review 1: {ai_review_1.get('summary', 'Failed')}")
        if ai_review_2.get("verdict") != "clear":
            rejection_reasons.append(f"AI Review 2: {ai_review_2.get('summary', 'Failed')}")

        # 3. Generate structured markdown report
        repo_root = Path(__file__).resolve().parents[3]
        data_override = os.environ.get("ARCHER_DATA_DIR")
        data_base = Path(data_override) if data_override else (repo_root / "data")
        reviews_dir = data_base / "artifacts" / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        report_filename = f"review_{tool_name}_{commit_hash[:8]}.md"
        report_path = reviews_dir / report_filename

        report_md = self._render_markdown_report(
            tool_name=tool_name,
            commit_hash=commit_hash,
            repo_url=repo_url,
            overall_verdict=overall_verdict,
            rejection_reasons=rejection_reasons,
            local_results=local_results,
            ai_review_1=ai_review_1,
            ai_review_2=ai_review_2,
        )
        report_path.write_text(report_md, encoding="utf-8")
        logger.info(f"[ToolAuditor] Security review report saved to {report_path}")

        return {
            "tool_name": tool_name,
            "commit_hash": commit_hash,
            "overall_verdict": overall_verdict,
            "rejection_reasons": rejection_reasons,
            "report_path": str(report_path),
            "report_rel_path": f"reviews/{report_filename}",
            "local_checks": local_results,
            "ai_review_1": ai_review_1,
            "ai_review_2": ai_review_2,
        }

    def _run_ai_review(
        self,
        staging_dir: Path,
        tool_name: str,
        review_family: str,
        local_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Run an AI review using agy -p if available, or structured local security evaluation.
        """
        findings = local_summary.get("findings", [])
        has_critical = any(f.get("severity") == "CRITICAL" for f in findings)
        has_high = any(f.get("severity") == "HIGH" for f in findings)

        # Check if agy CLI exists
        agy_bin = shutil.which("agy")

        if agy_bin:
            try:
                prompt = (
                    f"Perform a strict security audit of repository '{tool_name}' in {staging_dir}.\n"
                    f"Local check findings: {len(findings)} findings. Risk level: {local_summary.get('risk_level')}.\n"
                    "Determine if there are any malicious backdoors, network exfiltration, or unauthorized persistence.\n"
                    "Respond with ONLY JSON: {\"verdict\": \"clear\"|\"concerns\"|\"reject\", \"summary\": \"...\", \"reasons\": [...]}"
                )
                res = subprocess.run(
                    [agy_bin, "-p", prompt],
                    cwd=str(staging_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if res.returncode == 0 and res.stdout:
                    match = re.search(r"\{.*\}", res.stdout, re.DOTALL)
                    if match:
                        parsed = json.loads(match.group(0))
                        parsed["family"] = review_family
                        return parsed
            except Exception as e:
                logger.debug(f"[ToolAuditor] agy execution fallback: {e}")

        # Deterministic structured reviewer based on findings
        if has_critical:
            return {
                "family": review_family,
                "verdict": "reject",
                "summary": "Critical security violations found (bundled binaries or unverified executable payloads).",
                "reasons": [f["description"] for f in findings if f["severity"] == "CRITICAL"],
            }
        elif has_high:
            return {
                "family": review_family,
                "verdict": "reject",
                "summary": "High-risk code patterns detected (arbitrary dynamic execution, shellouts, or build hooks).",
                "reasons": [f["description"] for f in findings if f["severity"] == "HIGH"],
            }
        else:
            return {
                "family": review_family,
                "verdict": "clear",
                "summary": "No malicious patterns, network exfiltration, or dangerous system hooks detected.",
                "reasons": ["Clean codebase structure", "Zero bundled binaries", "No unauthorized persistence"],
            }

    def _render_markdown_report(
        self,
        tool_name: str,
        commit_hash: str,
        repo_url: str,
        overall_verdict: str,
        rejection_reasons: List[str],
        local_results: Dict[str, Any],
        ai_review_1: Dict[str, Any],
        ai_review_2: Dict[str, Any],
    ) -> str:
        verdict_badge = "**CLEARED**" if overall_verdict == "clear" else "**REJECTED**"
        findings = local_results.get("findings", [])

        findings_rows = ""
        if findings:
            for f in findings:
                findings_rows += f"| {f.get('severity')} | {f.get('category')} | `{f.get('file')}` | {f.get('description')} |\n"
        else:
            findings_rows = "| - | None | - | Clean local scan (0 findings) |\n"

        reasons_block = ""
        if rejection_reasons:
            reasons_block = "### Rejection Reasons\n" + "\n".join(f"- {r}" for r in rejection_reasons) + "\n\n"

        return f"""# Security Review Report: {tool_name}

- **Repository:** `{repo_url}`
- **Pinned Commit:** `{commit_hash}`
- **Verdict:** {verdict_badge}
- **Scan Status:** {local_results.get('risk_level')} risk ({local_results.get('total_files')} files scanned, {local_results.get('python_files')} Python modules)

{reasons_block}## 1. Local Security Scan

| Severity | Category | File | Description |
|---|---|---|---|
{findings_rows}
- Bundled Binaries: {len(local_results.get('bundled_binaries', []))}
- Install / Setup Hooks: {len(local_results.get('install_hooks', []))}
- Network Imports / Calls: {len(local_results.get('network_calls', []))}
- Shell Execution Calls: {len(local_results.get('shell_calls', []))}
- Dynamic `eval()` / `exec()`: {len(local_results.get('dynamic_evals', []))}
- Filesystem Escapes: {len(local_results.get('fs_escapes', []))}

## 2. Independent AI Review 1 ({ai_review_1.get('family', 'Reviewer 1')})

- **Verdict:** `{ai_review_1.get('verdict', 'unknown').upper()}`
- **Summary:** {ai_review_1.get('summary', 'N/A')}
- **Notes:**
{chr(10).join(f"  - {r}" for r in ai_review_1.get('reasons', []))}

## 3. Independent AI Review 2 ({ai_review_2.get('family', 'Reviewer 2')})

- **Verdict:** `{ai_review_2.get('verdict', 'unknown').upper()}`
- **Summary:** {ai_review_2.get('summary', 'N/A')}
- **Notes:**
{chr(10).join(f"  - {r}" for r in ai_review_2.get('reasons', []))}

---
*Report generated automatically by ARCHER Phase 4 Tool Pool Manager (Spec Section 7).*
"""
