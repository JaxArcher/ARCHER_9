"""
ARCHER Approval System (Phase 3).

Spec Section 6:
- Gate location: UniversalToolExecutor.
- Every tool declares whether it is read-only or changes state.
- Changing tools must pass the gate before they run.
- Changes state (needs approval): modifying/moving/deleting files, terminal commands,
  desktop clicks/typing, browser actions that submit/post/send, installs.
- Does not need approval: reading, searching, screenshots, navigating to a page,
  creating new files in artifacts folder, and ARCHER's changes to its own records
  (tasks, habits, inventory, purchase/loan logs).
- Approval prompt: appears in chat box and spoken briefly. Shows command/file/action.
  Buttons: Approve, Deny, Approve all for this session.
- Session approval: lasts until restart or Col clicks "End session approval".
  While on, skips prompts for commands, file changes, app actions, library installs.
  Still asks every time for git-repo tool installs and ARCHER's own .venv installs.
- Timeout: unanswered prompt treated as denied after timeout (default 30s).
- Log: every gated action, decision, and outcome recorded to action_audit and change_log.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional, Tuple

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store


# Tools that only inspect state or read data (no state mutation)
READ_ONLY_TOOLS = {
    "get_active_window",
    "list_windows",
    "open_url",
    "open_url_in_my_browser",
    "play_youtube",
    "browser_get_text",
    "browser_screenshot",
    "take_screenshot",
    "find_item",
    "search_inventory",
    "get_low_supplies",
    "list_tasks",
    "list_habits",
    "get_tasks",
    "get_habits",
    "open_document",
    "show_in_folder",
    "list_artifacts",
    "list_rnd_proposals",
    "get_rnd_status",
}

# ARCHER's internal record mutations and new artifact creations (Spec Section 6)
SELF_RECORD_TOOLS = {
    "add_task",
    "complete_task",
    "delete_task",
    "add_habit",
    "complete_habit",
    "delete_habit",
    "add_inventory_item",
    "log_purchase",
    "track_loan",
    "switch_tab",
    "create_word_document",
    "create_presentation",
    "create_spreadsheet",
    "create_pdf",
    "merge_pdfs",
    "propose_improvement",
    "undo_last_update",
}

# Tools that ALWAYS require explicit approval even when session approval is active
ALWAYS_ASK_TOOLS = {
    "install_tool_git",
    "install_venv",
    "install_package_venv",
    "apply_rnd_update_security",
}

# Security and permission sensitive files that ALWAYS require individual approval (Spec Section 11b)
SECURITY_SENSITIVE_FILES = [
    "src/archer/core/approvals.py",       # The approval gate
    "src/archer/core/security.py",        # Security rules
    "src/archer/tools/tool_auditor.py",   # Tool auditor & security checks
    "src/archer/agents/AGENTS.md",        # Agent behavioral boundaries & permissions
    ".env",                               # Environment secrets & tokens
    "settings.json",                      # Permissions configuration
]


def touches_security_sensitive_files(file_list: List[str]) -> bool:
    """Check if any file in file_list touches security rules, approval gate, .env, or permissions."""
    for f in file_list:
        f_norm = str(f).replace("\\", "/").lower()
        for sensitive in SECURITY_SENSITIVE_FILES:
            if sensitive.lower() in f_norm or f_norm.endswith(".env"):
                return True
    return False


class ApprovalManager:
    """Singleton manager for tool approval requests, session approval, and auditing."""

    _instance: Optional[ApprovalManager] = None
    _lock = threading.Lock()

    def __new__(cls) -> ApprovalManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self) -> None:
        self.session_approval_active: bool = False
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self._bus = get_event_bus()
        self._store = get_sqlite_store()
        self._broadcast_func: Optional[Callable[[Dict[str, Any]], None]] = None

        # Register HALT listener to abort pending approvals
        self._bus.subscribe_halt(self._on_halt)

    def set_broadcast_callback(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        """Register the WebSocket broadcast callback from server.py."""
        self._broadcast_func = cb

    def _broadcast(self, msg: Dict[str, Any]) -> None:
        """Broadcast a message thread-safely."""
        if self._broadcast_func:
            try:
                self._broadcast_func(msg)
            except Exception as e:
                logger.debug(f"[ApprovalManager] Broadcast failed: {e}")

    def should_gate(self, tool_name: str, tool_input: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Check if a tool execution requires user approval.
        Returns: (needs_approval: bool, reason: str)
        """
        if tool_name in READ_ONLY_TOOLS:
            return False, "read_only"

        if tool_name in SELF_RECORD_TOOLS:
            return False, "self_record"

        if tool_name in ALWAYS_ASK_TOOLS:
            return True, "always_ask"

        if tool_name == "apply_rnd_update":
            # Spec Section 11b: Changes to approval gate, security rules, .env, or permissions ALWAYS require individual approval
            if tool_input.get("touches_security") or touches_security_sensitive_files(tool_input.get("files", [])):
                return True, "always_ask_security"
            if self.session_approval_active:
                return False, "session_approved"
            return True, "changes_state"

        if self.session_approval_active:
            return False, "session_approved"

        # Default: all changing tools require approval
        return True, "changes_state"

    def describe_action(self, tool_name: str, tool_input: Dict[str, Any]) -> Tuple[str, str, str]:
        """
        Produce a categorized (action_type, description, details) triple for an action.
        """
        if tool_name == "click":
            x, y = tool_input.get("x"), tool_input.get("y")
            btn = tool_input.get("button", "left")
            return "desktop_action", f"Click mouse at ({x}, {y})", f"Button: {btn}"

        if tool_name == "type_text":
            text = tool_input.get("text", "")
            return "desktop_action", f"Type text into active window", f"Text: {text}"

        if tool_name == "hotkey":
            keys = "+".join(tool_input.get("keys", []))
            return "desktop_action", f"Press keyboard shortcut: {keys}", f"Keys: {keys}"

        if tool_name == "focus_window":
            title = tool_input.get("title", "")
            return "desktop_action", f"Switch focus to window '{title}'", f"Title: {title}"

        if tool_name == "browser_click":
            sel = tool_input.get("selector", "")
            return "browser_action", f"Click browser element '{sel}'", f"Selector: {sel}"

        if tool_name == "browser_type":
            sel = tool_input.get("selector", "")
            text = tool_input.get("text", "")
            return "browser_action", f"Type into browser element '{sel}'", f"Text: {text}"

        if tool_name == "close_browser":
            return "browser_action", "Close active browser window", ""

        if tool_name in ("execute_command", "run_terminal", "run_terminal_command"):
            cmd = tool_input.get("command", "")
            return "terminal_command", f"Run terminal command: {cmd}", f"Command: {cmd}"

        if tool_name in ALWAYS_ASK_TOOLS:
            repo = tool_input.get("repo") or tool_input.get("repo_url") or tool_input.get("name") or tool_input.get("package") or ""
            return "tool_install", f"Install tool or library: {repo}", f"Target: {repo}"

        # Self-record summaries
        if tool_name == "add_task":
            title = tool_input.get("title", "")
            return "self_record", f"Add task '{title}'", f"Title: {title}"

        if tool_name == "complete_task":
            tid = tool_input.get("task_id", "")
            return "self_record", f"Complete task #{tid}", f"Task ID: {tid}"

        if tool_name == "delete_task":
            tid = tool_input.get("task_id", "")
            return "self_record", f"Delete task #{tid}", f"Task ID: {tid}"

        if tool_name == "add_habit":
            name = tool_input.get("name", "")
            return "self_record", f"Add habit '{name}'", f"Name: {name}"

        if tool_name == "switch_tab":
            tab = tool_input.get("tab_name", "")
            return "self_record", f"Switch to '{tab}' tab", f"Tab: {tab}"

        if tool_name == "apply_rnd_update":
            title = tool_input.get("title", "")
            job_id = tool_input.get("job_id", "")
            files = tool_input.get("files", [])
            sec_warn = " [SECURITY: Individual approval required]" if tool_input.get("touches_security") or touches_security_sensitive_files(files) else ""
            return "self_dev_apply", f"Apply R&D update: {title}{sec_warn}", f"Job: {job_id}, Files: {len(files)}"

        if tool_name == "undo_last_update":
            return "self_dev_undo", "Undo last R&D update", "Restores repository from pre-apply backup"

        return "changes_state", f"Execute action '{tool_name}'", str(tool_input)

    def request_approval(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        timeout: float = 30.0,
        prompted_by: str = "User request"
    ) -> bool:
        """
        Request user approval for a tool execution. Blocks up to `timeout` seconds.
        Returns True if approved, False if denied, timed out, or cancelled.
        """
        req_id = f"appr_{uuid.uuid4().hex[:8]}"
        action_type, description, details = self.describe_action(tool_name, tool_input)

        event = threading.Event()
        with self._pending_lock:
            self._pending[req_id] = {
                "event": event,
                "decision": None,
                "tool_name": tool_name,
                "action_type": action_type,
                "description": description,
                "details": details,
                "prompted_by": prompted_by,
                "start_time": time.time(),
                "timeout": timeout,
            }

        logger.info(f"[ApprovalManager] Approval requested [{req_id}]: {description}")

        # Publish to event bus and WebSocket
        self._bus.publish(Event(
            type=EventType.APPROVAL_REQUESTED,
            source="approval_manager",
            data={
                "request_id": req_id,
                "tool_name": tool_name,
                "action_type": action_type,
                "description": description,
                "details": details,
                "timeout_seconds": timeout,
            }
        ))

        self._broadcast({
            "type": "approval_request",
            "request_id": req_id,
            "tool_name": tool_name,
            "action_type": action_type,
            "description": description,
            "details": details,
            "timeout_seconds": timeout,
        })

        # Wait for decision or timeout
        signaled = event.wait(timeout=timeout)

        with self._pending_lock:
            req_info = self._pending.pop(req_id, None)

        if not signaled or not req_info or req_info.get("decision") is None:
            # Timed out
            logger.warning(f"[ApprovalManager] Approval timed out [{req_id}] for {tool_name}. Denying.")
            self._record_decision(tool_name, description, details, prompted_by, "denied_timeout", False)
            self._broadcast({
                "type": "approval_timeout",
                "request_id": req_id,
                "description": description,
            })
            return False

        decision = req_info["decision"]

        if decision == "approve":
            logger.info(f"[ApprovalManager] Approval granted [{req_id}] for {tool_name}.")
            self._record_decision(tool_name, description, details, prompted_by, "individual", True)
            return True

        if decision == "approve_session":
            logger.info(f"[ApprovalManager] Session approval granted via [{req_id}].")
            self.session_approval_active = True
            self._broadcast({
                "type": "session_approval_state",
                "active": True,
            })
            self._record_decision(tool_name, description, details, prompted_by, "session", True)
            return True

        logger.info(f"[ApprovalManager] Approval denied [{req_id}] for {tool_name} (decision={decision}).")
        self._record_decision(tool_name, description, details, prompted_by, "denied", False)
        return False

    def handle_response(self, request_id: str, decision: str) -> bool:
        """
        Handle user response from UI or voice ('approve', 'deny', 'approve_session').
        """
        with self._pending_lock:
            req_info = self._pending.get(request_id)
            if not req_info:
                return False
            req_info["decision"] = decision
            req_info["event"].set()

        self._bus.publish(Event(
            type=EventType.APPROVAL_RESOLVED,
            source="approval_manager",
            data={"request_id": request_id, "decision": decision}
        ))
        return True

    def set_session_approval(self, active: bool) -> None:
        """Set or revoke session approval."""
        self.session_approval_active = active
        logger.info(f"[ApprovalManager] Session approval set to: {active}")
        self._broadcast({
            "type": "session_approval_state",
            "active": active,
        })

    def get_pending_requests(self) -> list[Dict[str, Any]]:
        """Return list of all currently active pending approval requests."""
        with self._pending_lock:
            now = time.time()
            res = []
            for req_id, info in self._pending.items():
                elapsed = now - info.get("start_time", now)
                timeout = info.get("timeout", 30.0)
                res.append({
                    "request_id": req_id,
                    "tool_name": info.get("tool_name"),
                    "action_type": info.get("action_type"),
                    "description": info.get("description"),
                    "details": info.get("details"),
                    "remaining_seconds": max(0, int(timeout - elapsed)),
                    "timeout_seconds": timeout,
                })
            return res

    def record_change(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        approval_status: str,
        prompted_by: str = "User request",
        success: bool = True
    ) -> None:
        """Record an executed change to change_log and action_audit."""
        _, desc, details = self.describe_action(tool_name, tool_input)
        self._record_decision(tool_name, desc, details, prompted_by, approval_status, success)

    def _record_decision(
        self,
        tool_name: str,
        description: str,
        details: str,
        prompted_by: str,
        approval_status: str,
        success: bool
    ) -> None:
        """Write change log and action audit records."""
        try:
            self._store.add_change_log(
                what_changed=description,
                prompted_by=prompted_by,
                approval_status=approval_status,
                tool_name=tool_name,
                details=details,
            )
            self._store.log_action(
                agent_name="tool_executor",
                action_type=tool_name,
                description=description,
                success=success,
                error=None if success else f"Status: {approval_status}",
                metadata={"approval_status": approval_status, "details": details},
            )
        except Exception as e:
            logger.debug(f"[ApprovalManager] Failed recording audit/changelog: {e}")

    def _on_halt(self, event: Event) -> None:
        """Emergency HALT listener: cancels any pending approval requests immediately."""
        with self._pending_lock:
            for req_id, req_info in list(self._pending.items()):
                req_info["decision"] = "halt"
                req_info["event"].set()
        logger.info("[ApprovalManager] HALT: Cancelled all pending approval requests.")


_manager: Optional[ApprovalManager] = None


def get_approval_manager() -> ApprovalManager:
    """Get the global ApprovalManager instance."""
    global _manager
    if _manager is None:
        _manager = ApprovalManager()
    return _manager
