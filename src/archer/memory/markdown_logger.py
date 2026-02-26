"""
ARCHER Markdown Logger (Layer 2 Memory).

Purpose: Human-readable audit trail and manual editing capability.
Files: memory/YYYY-MM-DD.md, site_log.md, audit.md.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from archer.config import get_config


class MarkdownLogger:
    """
    Layer 2: Markdown-based persistent memory.
    Ensures a transparent, human-readable record of all ARCHER activity.
    """

    def __init__(self) -> None:
        self._config = get_config()
        # Ensure the memory directory exists
        self._base_dir = self._config.data_dir / "memory"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def log_turn(
        self,
        role: str,
        content: str,
        agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a conversation turn and update the site log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        day = datetime.now().strftime("%Y-%m-%d")
        daily_file = self._base_dir / f"{day}.md"

        # 1. Update Daily Log
        badge = f"[{agent.upper()}] " if agent else ""
        entry = f"### {timestamp} - {role.capitalize()}\n"
        if badge:
            entry += f"**Agent**: {badge}\n"
        entry += f"{content}\n\n"
        
        if metadata:
            entry += f"<details><summary>Metadata</summary>\n\n```json\n{metadata}\n```\n</details>\n\n"

        with daily_file.open("a", encoding="utf-8") as f:
            f.write(entry)

        # 2. Update Site Log (Summary of session)
        site_log = self._base_dir / "site_log.md"
        if not site_log.exists():
            site_log.write_text("# ARCHER Site Continuity Log\n\n", encoding="utf-8")
        
        # Only log user turns or major agent actions to site log to keep it "high level"
        if role == "user":
            with site_log.open("a", encoding="utf-8") as f:
                f.write(f"- {day} {timestamp}: Colby: {content[:100]}...\n")

    def log_audit(self, action: str, result: str, details: str | None = None) -> None:
        """Log a task validation or system event to audit.md."""
        timestamp = datetime.now().isoformat()
        audit_file = self._base_dir / "audit.md"
        
        if not audit_file.exists():
            audit_file.write_text("# ARCHER Task Validation Audit\n\n", encoding="utf-8")
            
        entry = f"| {timestamp} | {action} | {result} | {details or ''} |\n"
        
        # Add table header if new file or empty
        if audit_file.stat().st_size < 50:
             audit_file.write_text(
                 "# ARCHER Task Validation Audit\n\n| Timestamp | Action | Result | Details |\n|---|---|---|---|\n",
                 encoding="utf-8"
             )

        with audit_file.open("a", encoding="utf-8") as f:
            f.write(entry)


# Global singleton
_md_logger: MarkdownLogger | None = None


def get_markdown_logger() -> MarkdownLogger:
    """Get the global Markdown logger singleton."""
    global _md_logger
    if _md_logger is None:
        _md_logger = MarkdownLogger()
    return _md_logger
