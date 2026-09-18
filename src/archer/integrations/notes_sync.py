"""
Mirrors tasks/habits/learned-patterns out to plain markdown files inside
barehands' own "Notes" orb (barehands/sample-notes/ARCHER/*.md), so Col can
see them through the barehands Notes pane he already uses instead of a
dedicated dashboard input UI (2026-09-16, Col's call: "task and habit
tables and files i can modify should be in the files that i can access via
barehand pane... as well as the learning patterns").

This is a ONE-WAY mirror for v1: SQLite (sqlite_store.py) stays the real
source of truth, unchanged -- voice/text tool calls (tasks_SKILL.md) and
the dashboard's remaining read-only Tasks card both still go through it.
Editing these .md files directly in barehands does NOT write back to
SQLite yet; that would need a file-watcher and is a deliberate fast-follow,
not silently half-built here. Told to Col explicitly rather than assumed.

Called from server.py every time the underlying data actually changes --
piggy-backed onto _build_tasks_snapshot()/_build_memory_snapshot(), since
those already fire at every point (direct browser write, voice/text tool
call via the event bus, initial load) that matters. Best-effort throughout:
a write failure here should never take down the snapshot it's riding along
with.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from archer.config import get_config


def _notes_dir() -> Path | None:
    """barehands/sample-notes/ARCHER -- a subfolder of the SAME "Notes" orb
    barehands.json already points at (path: "sample-notes"), so no
    barehands.json/server.py change is needed for these to show up; a
    folder tree browser picks up new subfolders automatically."""
    raw = (get_config().barehands_dir or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser() / "sample-notes" / "ARCHER"


def _write(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception as e:
        logger.debug(f"notes_sync: could not write {path.name} (non-fatal): {e}")


def sync_tasks_and_habits(tasks: list[dict], habits: list[dict]) -> None:
    d = _notes_dir()
    if d is None:
        return

    open_tasks = [t for t in tasks if t.get("status") != "completed"]
    done_tasks = [t for t in tasks if t.get("status") == "completed"]
    lines = ["# Tasks", "", "_Mirrored from ARCHER's dashboard -- editing here doesn't sync back yet; add/complete by voice or the dashboard's Tasks card._", ""]
    lines.append("## Open")
    if open_tasks:
        for t in open_tasks:
            due = f" (due {t['due_date']})" if t.get("due_date") else ""
            lines.append(f"- [ ] {t.get('title', '')}{due}")
    else:
        lines.append("_Nothing open._")
    lines.append("")
    lines.append("## Completed")
    if done_tasks:
        for t in done_tasks[:30]:
            lines.append(f"- [x] {t.get('title', '')}")
    else:
        lines.append("_Nothing completed yet._")
    _write(d / "Tasks.md", "\n".join(lines) + "\n")

    hlines = ["# Habits", "", "_Mirrored from ARCHER's dashboard._", ""]
    if habits:
        for h in habits:
            last = f" -- last done {h['last_completed_at']}" if h.get("last_completed_at") else ""
            hlines.append(f"- **{h.get('name', '')}** ({h.get('frequency', '')}) -- streak {h.get('streak_count', 0)}{last}")
    else:
        hlines.append("_No habits tracked yet._")
    _write(d / "Habits.md", "\n".join(hlines) + "\n")


def sync_learned_patterns(entities: list[dict], patterns: list[dict]) -> None:
    d = _notes_dir()
    if d is None:
        return

    lines = ["# Learned Patterns", "", "_Mirrored from ARCHER's dashboard -- this fills in as you talk with ARCHER._", ""]
    lines.append("## Known Entities")
    if entities:
        for e in entities:
            resolves = f" -> {e['resolves_to']}" if e.get("resolves_to") else ""
            definition = f" -- {e['definition']}" if e.get("definition") else ""
            lines.append(f"- **{e.get('canonical_name', '')}** ({e.get('entity_type', '')}, {e.get('mention_count', 0)}x){resolves}{definition}")
    else:
        lines.append("_Nothing learned yet._")
    lines.append("")
    lines.append("## Recurring Themes")
    if patterns:
        for p in patterns:
            example = f' -- "{p["last_example"]}"' if p.get("last_example") else ""
            lines.append(f"- **{p.get('label', '')}** ({p.get('pattern_type', '')}, {p.get('occurrence_count', 0)}x){example}")
    else:
        lines.append("_No recurring themes noticed yet._")
    _write(d / "Learned_Patterns.md", "\n".join(lines) + "\n")
