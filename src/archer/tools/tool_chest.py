"""
ARCHER Tool Chest Registry (Spec Section 11a, Col 2026-10-22).

Single registry of everything ARCHER can use to get work done.
Each entry specifies:
  - name
  - description (one plain line)
  - target bench ('LENNY', 'Beast', 'Antigravity', 'Telegram')
  - how_to_call
  - needs_approval
  - is_available
LENNY is the default bench for programs, Office, browsing, mouse and keyboard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from loguru import logger

from archer.config import get_config
from archer.memory.sqlite_store import get_sqlite_store
from archer.skills.skills_registry import get_all_tools, get_tool_category
from archer.core.approvals import READ_ONLY_TOOLS, SELF_RECORD_TOOLS


# Targets
BENCH_LENNY = "LENNY"
BENCH_BEAST = "Beast"
BENCH_ANTIGRAVITY = "Antigravity"
BENCH_TELEGRAM = "Telegram"


@dataclass
class ToolChestEntry:
    name: str
    description: str
    target: str
    category: str
    how_to_call: str
    needs_approval: bool
    is_available: bool


class ToolChest:
    """Registry and dispatcher for ARCHER's tool chest."""

    def __init__(self) -> None:
        self._config = get_config()
        self._store = get_sqlite_store()

    def get_lenny_availability(self) -> bool:
        """Check if LENNY is paired and reachable."""
        try:
            cfg = self._store.get_lenny_config()
            return bool(cfg.get("status") == "connected" and cfg.get("host"))
        except Exception:
            return bool(getattr(self._config, "lenny_enabled", True))

    def get_all_entries(self) -> List[ToolChestEntry]:
        """Collect all tools registered across skills, local engines, and LENNY."""
        entries: List[ToolChestEntry] = []
        lenny_ok = self.get_lenny_availability()

        # 1. Registered Skills from skills_registry
        try:
            skills_tools = get_all_tools()
        except Exception as e:
            logger.debug(f"Could not load skills tools: {e}")
            skills_tools = []

        for t in skills_tools:
            name = t.get("name", "")
            cat = get_tool_category(name)
            desc = t.get("description", "").strip().split("\n")[0]
            if not desc:
                desc = f"{name} tool in {cat} category"

            # Determine Target Bench
            if cat == "lenny" or name.startswith("lenny_"):
                target = BENCH_LENNY
                avail = lenny_ok
            elif cat in ("terminal", "system_status", "ui_control", "tasks", "profile"):
                target = BENCH_BEAST
                avail = True
            elif cat in ("documents", "office"):
                # Document compilation / conversion runs on Beast; live Office runs on LENNY
                target = BENCH_BEAST
                avail = True
            elif cat == "rnd":
                target = BENCH_ANTIGRAVITY
                avail = True
            elif cat == "telegram":
                target = BENCH_TELEGRAM
                avail = bool(getattr(self._config, "telegram_bot_token", ""))
            else:
                target = BENCH_BEAST
                avail = True

            # Approval status
            needs_appr = (name not in READ_ONLY_TOOLS and name not in SELF_RECORD_TOOLS)

            params = t.get("parameters", {})
            param_names = list(params.keys()) if isinstance(params, dict) else []
            call_sig = f"{name}({', '.join(param_names)})"

            entries.append(ToolChestEntry(
                name=name,
                description=desc,
                target=target,
                category=cat,
                how_to_call=call_sig,
                needs_approval=needs_appr,
                is_available=avail,
            ))

        # 2. Installed apps on LENNY (reported by Hands or standard workstation suite)
        lenny_apps = [
            ("winword", "Microsoft Word for drafting, editing, and formatting documents"),
            ("excel", "Microsoft Excel for spreadsheets, finances, and data analysis"),
            ("powerpnt", "Microsoft PowerPoint for presentations and slides"),
            ("chrome", "Google Chrome for web browsing, research, and web apps"),
            ("notepad", "Notepad for quick text notes and plain text files"),
            ("calc", "Windows Calculator for quick mathematical calculations"),
        ]
        for app_id, app_desc in lenny_apps:
            entries.append(ToolChestEntry(
                name=f"lenny_app_{app_id}",
                description=f"{app_desc} (on LENNY)",
                target=BENCH_LENNY,
                category="lenny_apps",
                how_to_call=f"lenny_open_app(name='{app_id}')",
                needs_approval=True,
                is_available=lenny_ok,
            ))

        # 3. Beast specialized capabilities
        beast_specialties = [
            ("terminal_powershell", "Full interactive PowerShell terminal for system scripts and diagnostics", BENCH_BEAST, "terminal", "run_terminal_command(command)", True, True),
            ("android_phone", "Virtual Android smartphone with camera, apps, and SMS simulation", BENCH_BEAST, "mobile", "android_emulator_action(action)", True, True),
            ("local_vision_vlm", "Qwen2.5-VL / Moondream local GPU vision grounding models on RTX 5080", BENCH_BEAST, "vision", "describe_screen()", False, True),
            ("local_whisper", "Local Whisper neural speech recognition", BENCH_BEAST, "voice", "transcribe(audio)", False, True),
        ]
        for name, desc, tgt, cat, sig, appr, av in beast_specialties:
            entries.append(ToolChestEntry(
                name=name,
                description=desc,
                target=tgt,
                category=cat,
                how_to_call=sig,
                needs_approval=appr,
                is_available=av,
            ))

        # 4. Antigravity Self-Dev & R&D
        entries.append(ToolChestEntry(
            name="antigravity_coding",
            description="Antigravity coding CLI (agy) running in sandbox worktree for self-development",
            target=BENCH_ANTIGRAVITY,
            category="rnd",
            how_to_call="rnd_propose(title, description)",
            needs_approval=True,
            is_available=True,
        ))

        # 5. Telegram Mobile Line (Spec 10d / 11a)
        entries.append(ToolChestEntry(
            name="telegram_messaging",
            description="Telegram bot mobile messaging line for direct mobile notifications and messages",
            target=BENCH_TELEGRAM,
            category="messaging",
            how_to_call="telegram_send_message(text)",
            needs_approval=True,
            is_available=True,
        ))

        return entries

    def tool_chest_find(self, task: str) -> List[Dict[str, Any]]:
        """
        Look in the tool chest for the best matching tools for a task.
        LENNY is the default bench for programs, Office, browsing, and desktop interaction.
        """
        task_clean = (task or "").lower().strip()
        if not task_clean:
            return []

        all_entries = self.get_all_entries()
        scored: List[tuple[int, ToolChestEntry]] = []

        # Keywords for intent scoring
        for e in all_entries:
            score = 0
            text_pool = f"{e.name} {e.description} {e.category}".lower()

            # Exact name or keyword match
            words = [w for w in re.split(r"\W+", task_clean) if len(w) > 2]
            for w in words:
                if w in text_pool:
                    score += 2

            # Domain bonuses (LENNY default bench gets strong preference for Office and interactive desktop tasks)
            if any(k in task_clean for k in ("spreadsheet", "excel", "sheet", "bills", "finances", "budget")):
                if "excel" in e.name or "sheet" in e.name:
                    score += 15
                    if e.target == BENCH_LENNY:
                        score += 10
            elif any(k in task_clean for k in ("word", "document", "letter", "essay", "report", "doc")):
                if "word" in e.name or "doc" in e.name:
                    score += 15
                    if e.target == BENCH_LENNY:
                        score += 10
            elif any(k in task_clean for k in ("notepad", "note", "scratchpad")):
                if "notepad" in e.name:
                    score += 15
                    if e.target == BENCH_LENNY:
                        score += 10
            elif any(k in task_clean for k in ("browse", "web", "website", "search online", "look up online")):
                if "chrome" in e.name or "browser" in e.name or "web" in e.name:
                    score += 12
                    if e.target == BENCH_LENNY:
                        score += 8
            elif any(k in task_clean for k in ("code", "fix bug", "r&d", "improve", "refactor")):
                if e.target == BENCH_ANTIGRAVITY:
                    score += 15
            elif any(k in task_clean for k in ("terminal", "command", "powershell", "script")):
                if "terminal" in e.name:
                    score += 10
            elif any(k in task_clean for k in ("telegram", "message", "text", "notify")):
                if e.target == BENCH_TELEGRAM:
                    score += 15
            elif any(k in task_clean for k in ("gpu", "vram", "vision", "model", "ollama", "5080")):
                if e.target == BENCH_BEAST and any(k in (e.name + " " + e.description).lower() for k in ("gpu", "vision", "vlm", "5080", "model")):
                    score += 15

            # LENNY default bench priority for interactive programs & desktop work
            if e.target == BENCH_LENNY:
                score += 3

            if score > 0:
                scored.append((score, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for e in scored[:8]:
            d = asdict(e[1])
            d["bench"] = d.get("target")
            results.append(d)
        return results

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Return all tools with both 'target' and 'bench' fields."""
        results = []
        for e in self.get_all_entries():
            d = asdict(e)
            d["bench"] = d.get("target")
            results.append(d)
        return results

    def get_tools_by_bench(self, bench: str) -> List[Dict[str, Any]]:
        """Filter tools by target bench."""
        return [
            t for t in self.get_all_tools()
            if t.get("target", "").lower() == bench.lower() or t.get("bench", "").lower() == bench.lower()
        ]

    def get_summary(self) -> Dict[str, Any]:
        """Summary metrics for the tool chest."""
        tools = self.get_all_tools()
        benches = [BENCH_LENNY, BENCH_BEAST, BENCH_ANTIGRAVITY, BENCH_TELEGRAM]
        bench_counts = {b: sum(1 for t in tools if t.get("bench") == b) for b in benches}
        return {
            "total_tools": len(tools),
            "benches": benches,
            "bench_counts": bench_counts,
            "default_bench": BENCH_LENNY,
            "lenny_online": self.get_lenny_availability(),
        }

    def route_clear_case(self, task: str) -> Optional[Dict[str, Any]]:
        """
        Deterministic code routing for unambiguous user task requests.
        Ensures clear requests go directly to the appropriate tool-chest entry (LENNY first)
        without relying on small model improvisation.
        """
        t = task.lower().strip()

        # Ignore reported speech (e.g. "Colby says write a word document")
        if re.search(r"\b(?:colby|user|someone|he|she)\s+(?:says|said|asks|asked)\b", t):
            return None

        # 1. Excel / Spreadsheets
        if re.search(r"\b(make|create|build|open|start|lay\s+down)\s+(?:an?|the)?\s*(?:excel\s+spreadsheet|excel\s+sheet|excel|spreadsheet|sheet)\b", t) or \
           re.search(r"\b(?:excel\s+spreadsheet|excel\s+sheet)\b", t) or \
           re.search(r"\bspreadsheet\s+of\b", t):
            return {
                "tool": "lenny_excel_sheet",
                "bench": BENCH_LENNY,
                "target": BENCH_LENNY,
                "action": "create_excel",
                "reason": "Routed to LENNY native Excel (default bench for Office tasks).",
            }

        # 2. Word / Documents
        if re.search(r"\b(make|create|write|draft|open)\s+.*?\b(?:in\s+word|in\s+microsoft\s+word|word\s+document|word\s+doc)\b", t) or \
           re.search(r"\b(?:word\s+document|word\s+doc)\b", t):
            return {
                "tool": "lenny_word_document",
                "bench": BENCH_LENNY,
                "target": BENCH_LENNY,
                "action": "create_word",
                "reason": "Routed to LENNY native Word (default bench for Office tasks).",
            }

        # 3. Direct write to Notepad
        if re.search(r"\b(?:write|type)\s+.*?\bin\s+notepad\b", t):
            return {
                "tool": "lenny_open_app",
                "bench": BENCH_LENNY,
                "target": BENCH_LENNY,
                "app": "notepad",
                "action": "open_app",
                "reason": "Routed to Notepad on LENNY to type note.",
            }

        # 4. Launch / Open specific applications
        m_open = re.search(r"\b(?:open|launch|start)\s+([a-z0-9_\-\.\s]+)\b", t)
        if m_open:
            app_raw = m_open.group(1).strip()
            # Stop at conjunctions like "and write"
            app_clean = re.split(r"\b(?:and|to|with|for)\b", app_raw)[0].strip()
            app_map = {
                "notepad": "notepad",
                "word": "winword",
                "excel": "excel",
                "powerpoint": "powerpnt",
                "chrome": "chrome",
                "browser": "chrome",
                "calculator": "calc",
            }
            if app_clean in app_map:
                app_id = app_map[app_clean]
                is_browse = (app_id == "chrome" or "browse" in t or "web" in t)
                action = "browse" if is_browse else "open_app"
                return {
                    "tool": "lenny_open_app",
                    "bench": BENCH_LENNY,
                    "target": BENCH_LENNY,
                    "app": app_id,
                    "action": action,
                    "reason": f"Routed to LENNY workstation to {'browse on Chrome' if action == 'browse' else 'launch ' + app_clean}.",
                }

        # 4. Web browsing / Look up online
        if re.search(r"\b(browse|look\s+up\s+on\s+the\s+web|search\s+online|browse\s+to|open\s+website|open\s+chrome)\b", t):
            return {
                "tool": "lenny_open_app",
                "bench": BENCH_LENNY,
                "target": BENCH_LENNY,
                "app": "chrome",
                "action": "browse",
                "reason": "Routed to Chrome on LENNY for live web research.",
            }

        return None

    def format_unsupported_tool_response(self, task: str) -> str:
        """Standard honest response when no tool exists in the tool chest for the task."""
        return (
            f"I don't have a tool for that yet. "
            f"Would you like me to research and propose a new tool for this in the R&D tab?"
        )

    def tool_chest_summary(self) -> str:
        """Produce a lean category summary of the tool chest for the brain's system prompt."""
        lenny_ok = "online" if self.get_lenny_availability() else "offline"
        return (
            f"ARCHER Tool Chest:\n"
            f"- LENNY ({lenny_ok}): Your dedicated Windows workstation for programs, Office (Word, Excel), browsing (Chrome), mouse and keyboard.\n"
            f"- Beast: Document building, terminal PowerShell, virtual Android phone, local GPU vision/whisper models.\n"
            f"- Antigravity: Coding, automated test runs, self-dev R&D worktrees.\n"
            f"- Telegram: Bot messaging.\n"
            f"Rule: Always use your tool chest for tasks; LENNY is your default bench."
        )


# Global singleton
_tool_chest: Optional[ToolChest] = None


def get_tool_chest() -> ToolChest:
    global _tool_chest
    if _tool_chest is None:
        _tool_chest = ToolChest()
    return _tool_chest


def format_unsupported_tool_response(task: str) -> str:
    """Standard honest response when no tool exists in the tool chest for the task."""
    return get_tool_chest().format_unsupported_tool_response(task)
