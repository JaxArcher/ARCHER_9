"""
ARCHER: Col's voice through the room camera's mic (Phase 2c).

Two jobs, run by Col from D:\\ARCHER_9 in a normal PowerShell window:

  .venv\\Scripts\\python.exe scripts\\room_voice.py enroll
      Learns Col's voice through the camera mic. Sit on the couch, alone,
      with the TV and videos off, and read the sentences shown, at a normal
      volume (about a minute). Saves a voice profile (192 numbers, no audio)
      in data/archer.db; the observer picks it up within a minute.

  .venv\\Scripts\\python.exe scripts\\room_voice.py test [--minutes 5]
      Checks the voice rule and the TV check. With the profile saved, play a
      video from the PC on the TV and talk now and then. Each stretch of
      speech is printed with its voice score, the share of its words the PC
      was also playing ("tv", with how many words were compared), and what
      the observer would do with it. Nothing is saved: the words appear only
      in this window.

Audio is held in memory only; nothing is written to disk except the voice
profile. Uses the same camera audio connection, speech detection and voice
model as the observer's room listener.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

import numpy as np  # noqa: E402
import webrtcvad  # noqa: E402

from archer.config import get_config  # noqa: E402
from archer.memory.sqlite_store import get_sqlite_store  # noqa: E402
from archer.observer.pc_playback import PCPlayback, words_match  # noqa: E402
from archer.observer.room_listener import (  # noqa: E402
    CAMERA_AUDIO_LAG_SECONDS,
    _has_command,
    embed_voice,
    load_voice_model,
    start_camera_audio,
)

SENTENCES = [
    "Hey ARCHER, this is Col, and this is how my voice sounds from the couch.",
    "I'm reading a few ordinary sentences so you can learn what I sound like.",
    "Tomorrow I need to call the contractor about the breaker panel.",
    "Remind me to pick up groceries on the way home on Thursday.",
    "The meeting moved to three forty-five, so I have a little extra time.",
    "I think the new layout looks good, but the left column feels crowded.",
    "Let's order dinner in tonight and watch something after.",
    "That's enough for now. Thanks for listening.",
]

RATE = 16000
FRAME_BYTES = int(RATE * 0.03) * 2  # 30 ms


def speech_stretches(proc, seconds: float, on_stretch=None, min_s: float = 1.5, max_s: float = 10.0):
    """Read `seconds` of camera audio; yield stretches of speech (float32 arrays), memory only."""
    vad = webrtcvad.Vad(2)
    end = time.time() + seconds
    buf: list[bytes] = []
    silence = 0
    stretches = []
    while time.time() < end:
        frame = proc.stdout.read(FRAME_BYTES)
        if not frame or len(frame) < FRAME_BYTES:
            if proc.poll() is not None:
                raise RuntimeError("The camera audio connection ended.")
            continue
        speech = vad.is_speech(frame, RATE)
        if speech:
            buf.append(frame)
            silence = 0
        elif buf:
            buf.append(frame)
            silence += 1
        if buf and (silence >= 27 or len(buf) * 0.03 >= max_s):
            if len(buf) * 0.03 >= min_s:
                audio = np.frombuffer(b"".join(buf), dtype=np.int16).astype(np.float32) / 32768.0
                stretches.append(audio)
                if on_stretch:
                    on_stretch(audio)
            buf, silence = [], 0
    return stretches


def cosine(a, b) -> float:
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / d) if d else 0.0


def enroll(model, url: str, delay: float) -> int:
    print("\nSit on the couch, alone, with the TV and videos off.")
    print("Read these sentences at a normal volume, with a short pause after each")
    print("(from this screen or your phone), or just talk naturally for a minute:\n")
    for s in SENTENCES:
        print(f"  - {s}")
    print(f"\nListening starts in {delay:.0f} seconds and lasts 75 seconds.")
    time.sleep(max(0.0, delay))
    proc = start_camera_audio(url, RATE)
    try:
        print("\nListening now (75 seconds)...", flush=True)
        stretches = speech_stretches(proc, 75.0)
    finally:
        proc.kill()

    if len(stretches) < 4:
        print(f"\nOnly {len(stretches)} stretches of speech were heard; at least 4 are needed. "
              "Check the TV is off and try again, a little louder.")
        return 1

    embs = [embed_voice(model, a) for a in stretches]
    profile = np.mean(embs, axis=0)
    # How well each stretch matches a profile built from the others.
    loo = []
    for i, e in enumerate(embs):
        others = np.mean([x for j, x in enumerate(embs) if j != i], axis=0)
        loo.append(cosine(e, others))
    loo = sorted(loo)
    get_sqlite_store().save_room_voice_profile(profile.tolist(), samples=len(embs))
    print(f"\nSaved Col's room voice profile from {len(embs)} stretches of speech.")
    print(f"Self-match scores: lowest {loo[0]:.2f}, median {loo[len(loo) // 2]:.2f}, highest {loo[-1]:.2f}.")
    print(f"Current threshold: {get_config().room_voice_threshold:.2f} "
          "(ARCHER_ROOM_VOICE_THRESHOLD in .env).")
    print("Next: run the test with the TV on:  .venv\\Scripts\\python.exe scripts\\room_voice.py test")
    return 0


def test(model, url: str, minutes: float) -> int:
    emb = get_sqlite_store().get_room_voice_profile("Col")
    if not emb:
        print("No room voice profile yet. Run:  .venv\\Scripts\\python.exe scripts\\room_voice.py enroll")
        return 1
    profile = np.asarray(emb, dtype=np.float32)
    config = get_config()
    threshold = config.room_voice_threshold
    quiet_threshold = min(threshold, config.room_voice_threshold_quiet)
    tv_threshold = config.room_tv_match_threshold

    from faster_whisper import WhisperModel
    from archer.observer.room_listener import WHISPER_MODEL_DIR

    whisper = WhisperModel(str(WHISPER_MODEL_DIR), device="cpu", compute_type="int8",
                           cpu_threads=2, local_files_only=True)
    playback = PCPlayback()
    playback.start()
    time.sleep(2.0)
    where = playback.device or "nothing (the TV check can't run)"
    print(f"\nListening for {minutes:g} minutes. Play a video from the PC on the TV, and talk now and then.")
    print(f"Following the PC's playback on: {where}")
    print(f"Voice threshold {threshold:.2f} while the PC plays, {quiet_threshold:.2f} while it's quiet "
          f"(at or above counts as Col); TV threshold {tv_threshold:.2f} (that share of a line's words "
          "also playing on the PC means the TV). Nothing is saved.\n")
    print("level  score   tv (words)  length  would-be  cmd   words")

    # Like the observer, the camera is read on one thread and each stretch is
    # judged on another, so the timing of what's read stays real.
    stretches: queue.Queue = queue.Queue()
    results = []

    def judge() -> None:
        while True:
            item = stretches.get()
            if item is None:
                return
            audio, end_time = item
            start_time = end_time - len(audio) / RATE
            score = cosine(embed_voice(model, audio), profile)
            segs, _ = whisper.transcribe(audio, beam_size=1, language="en", vad_filter=True)
            words = " ".join(s.text.strip() for s in segs).strip()
            rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
            level = f"{20 * np.log10(rms):4.0f}dB" if rms > 1e-6 else "silent"
            if not words:
                print(f"{level}  {score:5.2f}  {'':10s}  {len(audio) / RATE:5.1f} s  (sound, but no speech found in it)", flush=True)
                continue
            # The TV check, shown for every line here (the observer only runs
            # it on lines it would otherwise keep).
            found = None
            playing = playback.playing_during(start_time, end_time, CAMERA_AUDIO_LAG_SECONDS)
            bar = quiet_threshold if playing is False else threshold
            if words_match(words, "") is not None:
                played = playback.played_audio_for(start_time, end_time, CAMERA_AUDIO_LAG_SECONDS)
                if played is not None:
                    psegs, _ = whisper.transcribe(played, beam_size=1, language="en", vad_filter=True)
                    found = words_match(words, " ".join(s.text.strip() for s in psegs))
            if found is not None and found[0] >= tv_threshold and score >= bar:
                verdict = "TV"
            elif score >= bar:
                verdict = "COL"
            elif found is not None and found[0] >= tv_threshold:
                verdict = "drop/TV"
            else:
                verdict = "drop"
            results.append(verdict)
            tv_text = "  -       " if found is None else f"{found[0]:4.2f} ({found[1]:2d}) "
            cmd = "YES" if _has_command(words) else "-"
            print(f"{level}  {score:5.2f}  {tv_text}  {len(audio) / RATE:5.1f} s  {verdict:8s}  {cmd:4s}  {words[:80]}", flush=True)

    worker = threading.Thread(target=judge, daemon=True)
    worker.start()
    proc = start_camera_audio(url, RATE)
    try:
        speech_stretches(proc, minutes * 60.0, on_stretch=lambda audio: stretches.put((audio, time.time())))
    finally:
        proc.kill()
        stretches.put(None)
        worker.join()
        playback.stop()
    counts = ", ".join(f"{results.count(v)} {v}" for v in ("COL", "TV", "drop", "drop/TV"))
    print(f"\nDone: {len(results)} stretches ({counts}). Copy the lines above to Claude, marking which were you.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Col's voice through the room camera's mic")
    parser.add_argument("job", choices=["enroll", "test"])
    parser.add_argument("--minutes", type=float, default=5.0, help="test: how long to listen")
    parser.add_argument("--delay", type=float, default=20.0, help="enroll: seconds before listening starts")
    args = parser.parse_args()

    url = get_config().network_camera_url
    if not url:
        print("No network camera is configured (ARCHER_NETWORK_CAMERA_URL).")
        return 1
    print("Loading the voice model...")
    model = load_voice_model()
    return enroll(model, url, args.delay) if args.job == "enroll" else test(model, url, args.minutes)


if __name__ == "__main__":
    sys.exit(main())
