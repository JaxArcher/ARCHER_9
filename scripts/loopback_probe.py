"""
ARCHER: can this Windows account hear what the PC is playing? (Phase 2c)

Used to decide where the room listener's "is that the TV?" check can live
(Claude, 2026-10-20). Videos play from the PC with the TV as its screen, so
the PC's own playback is a reference for TV speech. This records 5 seconds
of playback (WASAPI loopback, through the `soundcard` package ARCHER
already uses) from each output device, and appends the loudness per second
to logs/loopback_probe.txt. The audio is held in memory only; nothing else
is written.

Run it while a video with talking plays on the TV:
  - as the observer service's account (SYSTEM), from a one-off task, and
  - from Col's own PowerShell:  .venv\\Scripts\\python.exe scripts\\loopback_probe.py
"""

from __future__ import annotations

import ctypes
import datetime
import getpass
import os
import sys
import threading
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs" / "loopback_probe.txt"
SECONDS = 5
RATE = 48000
HEARS_RMS = 0.003  # about -50 dBFS; speech in a video is far louder


def account_info() -> str:
    try:
        session = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
        session_id = str(session.value)
    except Exception:
        session_id = "?"
    return f"account {getpass.getuser()}, Windows session {session_id}"


def record_levels(sc, speaker) -> list[float]:
    """RMS per second of `speaker`'s playback; raises on failure."""
    try:
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # this thread joins COM's MTA
    except Exception:
        pass
    mic = sc.get_microphone(id=str(speaker.id), include_loopback=True)
    levels = []
    with mic.recorder(samplerate=RATE) as rec:
        for _ in range(SECONDS):
            data = np.asarray(rec.record(numframes=RATE), dtype=np.float64)
            levels.append(float(np.sqrt(np.mean(data ** 2))) if data.size else 0.0)
    return levels


def probe_speaker(sc, speaker) -> str:
    result: dict = {}

    def run():
        try:
            result["levels"] = record_levels(sc, speaker)
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(SECONDS + 10)
    if worker.is_alive():
        return f"  {speaker.name}: no sound data within {SECONDS + 10} s (recording blocked)"
    if "error" in result:
        return f"  {speaker.name}: couldn't record ({result['error']})"
    levels = result["levels"]
    shown = ", ".join("silent" if v < 1e-6 else f"{20 * np.log10(v):.0f}" for v in levels)
    verdict = "HEARS PLAYBACK" if max(levels) >= HEARS_RMS else "silent"
    return f"  {speaker.name}: {verdict}; level per second (dBFS): {shown}"


def main() -> int:
    lines = [f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}, {account_info()}, Python {sys.version.split()[0]}"]
    try:
        import soundcard as sc

        default = sc.default_speaker()
        speakers = sc.all_speakers()
        lines.append(f"Default output: {default.name if default else 'none'}")
        lines.append(f"Outputs found: {len(speakers)}")
        for speaker in speakers:
            lines.append(probe_speaker(sc, speaker))
    except Exception as e:
        lines.append(f"soundcard failed: {type(e).__name__}: {e}")
        lines.append(traceback.format_exc())

    text = "\n".join(lines) + "\n"
    print(text)
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
