"""
Bridge to jaredrhod/barehands (https://github.com/jaredrhod/barehands) —
a separately-installed, separately-run webcam hand-gesture UI ("the board")
with a JARVIS-style state ring ("the face").

barehands is its OWN standalone app: its own stdlib Python server, its own
port (8794 by default), its own browser page (stage.html). ARCHER does not
embed it and does not clone/install/run it — per policy, code isn't pulled
from an untrusted source and executed automatically. The user clones and
runs barehands themselves (see README instructions at the repo above), then
points ARCHER at the checkout via ARCHER_BAREHANDS_DIR in .env. If that
variable is unset, everything in this module is a silent no-op.

barehands documents exactly two "dead-simple protocols" for wiring in a
brain (README, "Wire in your AI"):

  1. THE FACE — the ring reads three tiny files in `state/`:
       - `state`: one word, idle | listening | thinking | speaking
       - `wave.json`: {"samples": [0..1 x64], "ts": <unix time>} — the
         speech waveform, read only while speaking
     This module owns both. It subscribes to ARCHER's event bus
     (PIPELINE_STATE_CHANGED for the word, AUDIO_AMPLITUDE for the wave —
     the exact same amplitude stream the browser orb animates from, see
     server.py's "amplitude" WS message) so the ring becomes a second
     physical-desk face for ARCHER, pulsing with real speech, alongside
     the desktop orb and the browser client. `mood.json` is left alone —
     there's no ARCHER concept (green/amber/red) it obviously maps to yet.

  2. THE BOARD — `bin/board.sh '{"a":"add_card",...}'` posts cards (notes,
     images, 3D props) onto the board, and `bin/board-state.sh` reads what's
     currently on it. This is deliberately NOT auto-wired here: what should
     get posted, and how often, is a product decision (spoken responses?
     only long ones? only on request?) rather than a mechanical 1:1 mapping
     like the state file. `post_card()` below exposes the primitive so a
     specific behavior can be wired up once that's decided, without needing
     to touch this bridge module again.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus

# VoicePipelineState string -> barehands' own state vocabulary
# (idle / listening / thinking / speaking, per its README). ARCHER's
# "processing" maps to barehands' "thinking"; ARCHER's "error" has no
# barehands equivalent documented, so it falls back to "idle" rather than
# writing something the ring doesn't understand.
_STATE_MAP = {
    "idle": "idle",
    "listening": "listening",
    "processing": "thinking",
    "speaking": "speaking",
    "error": "idle",
}

_lock = threading.Lock()
_state_file: Path | None = None
_wave_file: Path | None = None
_board_script: Path | None = None
_wave_samples: "deque[float]" = deque(maxlen=64)


def _resolve_dir() -> Path | None:
    from archer.config import get_config

    raw = (get_config().barehands_dir or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_dir():
        logger.warning(
            f"ARCHER_BAREHANDS_DIR is set to '{raw}' but that directory "
            "doesn't exist — barehands bridge disabled."
        )
        return None
    return path


def _on_pipeline_state_changed(event: Event) -> None:
    if _state_file is None:
        return
    raw_state = event.data.get("state", "idle")
    mapped = _STATE_MAP.get(raw_state, "idle")
    try:
        with _lock:
            # Atomic-ish write: barehands polls this file, so avoid it ever
            # observing a half-written value.
            tmp = _state_file.with_suffix(".tmp")
            tmp.write_text(mapped, encoding="utf-8")
            tmp.replace(_state_file)
    except OSError as e:
        logger.debug(f"barehands state-file write failed (non-fatal): {e}")


def _on_audio_amplitude(event: Event) -> None:
    if _wave_file is None:
        return
    value = event.data.get("amplitude", 0.0)
    try:
        value = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return
    try:
        with _lock:
            _wave_samples.append(value)
            payload = json.dumps({"samples": list(_wave_samples), "ts": time.time()})
            tmp = _wave_file.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(_wave_file)
    except OSError as e:
        logger.debug(f"barehands wave-file write failed (non-fatal): {e}")


def start_barehands_bridge() -> bool:
    """
    Wire ARCHER's pipeline state to a locally-running barehands checkout's
    face ring, if ARCHER_BAREHANDS_DIR is configured and looks valid.
    Safe to call unconditionally at startup — no-ops cleanly otherwise.
    Returns True if the bridge is active.
    """
    global _state_file, _wave_file, _board_script

    root = _resolve_dir()
    if root is None:
        return False

    state_dir = root / "state"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"Could not create barehands state/ dir: {e} — bridge disabled.")
        return False

    _state_file = state_dir / "state"
    _wave_file = state_dir / "wave.json"
    board_sh = root / "bin" / "board.sh"
    _board_script = board_sh if board_sh.exists() else None

    bus = get_event_bus()
    bus.subscribe(EventType.PIPELINE_STATE_CHANGED, _on_pipeline_state_changed)
    bus.subscribe(EventType.AUDIO_AMPLITUDE, _on_audio_amplitude)
    # Seed an initial value so the ring doesn't sit on whatever was left
    # over from a previous run before the first real state change fires.
    try:
        _state_file.write_text("idle", encoding="utf-8")
    except OSError:
        pass

    logger.info(f"barehands bridge active — mirroring pipeline state to {_state_file}")
    return True


def post_card(title: str, body: str = "", kind: str = "notes") -> bool:
    """
    Post a card onto the barehands board via bin/board.sh. Not called
    automatically anywhere yet (see module docstring) — available for
    whichever specific behavior gets wired up next (e.g. surfacing
    ARCHER's spoken responses as cards on request).

    NOTE: board.sh is a POSIX shell script; on Windows this needs bash on
    PATH (Git Bash/WSL) to actually run — untested, since this isn't wired
    up to anything yet. Revisit when a real caller shows up.
    """
    if _board_script is None:
        logger.debug("barehands board.sh not available — post_card() is a no-op.")
        return False
    payload = {"a": "add_card", "title": title, "body": body, "kind": kind}
    try:
        subprocess.run(
            [str(_board_script), json.dumps(payload)],
            cwd=str(_board_script.parent.parent),
            capture_output=True,
            timeout=5,
            check=False,
        )
        return True
    except OSError as e:
        logger.debug(f"barehands post_card failed (non-fatal): {e}")
        return False
