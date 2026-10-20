"""
ARCHER: "all systems go" launch check (Phase 2c).

Run by the ArcherLaunchOnVoice scheduled task, in Col's own Windows session:
- on demand, when the observer service hears "all systems go" in the room
  (it records the request in the database, then runs the task), and
- at Col's logon.

Either way it does the same thing:
1. If there's no launch request from the last 10 minutes that hasn't been
   handled yet, it exits and does nothing.
2. It marks the request handled, so it never starts ARCHER twice for one
   request.
3. If ARCHER is already running, it opens ARCHER's page in the browser.
   Otherwise it starts ARCHER the usual way (ARCHER-Web.bat, which opens the
   page itself once the server answers).

It says nothing: ARCHER announces itself in its own voice when it starts
(Col, 2026-10-15). Reads and writes only the listening_control row of
data/archer.db.

Usage (normally only from the task):
    .venv\\Scripts\\python.exe scripts\\launch_check.py [--force]
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ARCHER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ARCHER_ROOT / "data" / "archer.db"
HEALTH_URL = "http://127.0.0.1:8200/mobile/health"
APP_URL = "http://127.0.0.1:8200/app"
MAX_REQUEST_AGE_S = 600.0
STARTUP_GRACE_S = 180.0


def consume_launch_request(
    db_path: Path, max_age_seconds: float = MAX_REQUEST_AGE_S, now: float | None = None
) -> tuple[bool, float]:
    """
    (True, previous_handled_at) if a launch was requested within
    `max_age_seconds` and not handled yet, marking it handled in the same
    transaction; otherwise (False, 0.0).
    """
    if not db_path.exists():
        return False, 0.0
    now = time.time() if now is None else now
    try:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        try:
            with conn:
                row = conn.execute(
                    "SELECT launch_requested_at, launch_handled_at FROM listening_control WHERE id = 1"
                ).fetchone()
                if not row:
                    return False, 0.0
                requested, handled = float(row[0] or 0.0), float(row[1] or 0.0)
                if requested <= 0.0 or requested <= handled or now - requested > max_age_seconds:
                    return False, 0.0
                conn.execute(
                    "UPDATE listening_control SET launch_handled_at = ? WHERE id = 1", (now,)
                )
                return True, handled
        finally:
            conn.close()
    except Exception as e:
        print(f"[launch_check] Couldn't read the launch request: {e}", file=sys.stderr)
        return False, 0.0


def is_archer_running() -> bool:
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "ARCHER-VoiceLaunch/1.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ARCHER 'all systems go' launch check")
    parser.add_argument("--onlogon", action="store_true", help="Run by the logon trigger (same behaviour).")
    parser.add_argument("--force", action="store_true", help="Launch even without a recent request (manual test).")
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    args = parser.parse_args(argv)

    previous = 0.0
    if not args.force:
        requested, previous = consume_launch_request(Path(args.db_path))
        if not requested:
            print("[launch_check] No new 'all systems go' in the last 10 minutes. Nothing to do.")
            return 0

    if is_archer_running():
        print("[launch_check] ARCHER is already running; opening its page.")
        webbrowser.open(APP_URL)
        return 0

    # A launch from a few minutes ago may still be starting up (Docker, Ollama
    # and the models take a while): never start a second copy.
    if previous and time.time() - previous < STARTUP_GRACE_S:
        print("[launch_check] ARCHER is still starting from the last request. Nothing to do.")
        return 0

    launcher = ARCHER_ROOT / "ARCHER-Web.bat"
    if not launcher.exists():
        print(f"[launch_check] {launcher} not found.", file=sys.stderr)
        return 1
    print("[launch_check] Starting ARCHER (ARCHER-Web.bat)...")
    subprocess.Popen(
        ["cmd.exe", "/c", str(launcher)],
        cwd=str(ARCHER_ROOT),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
