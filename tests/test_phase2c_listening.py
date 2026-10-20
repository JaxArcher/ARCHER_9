"""
Phase 2c: room listening (spec 5c and its decisions block).

Written by Antigravity 2026-10-15; rewritten by Claude 2026-10-15 after the
build review, so the tests go through the paths the live listener uses.

Tests run against temporary databases only; they never touch data/archer.db.
"""

from __future__ import annotations

import importlib.util
import io
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from archer.memory.sqlite_store import SQLiteStore, format_room_transcript_timestamp
from archer.observer import room_listener as rl
from archer.observer.room_listener import RoomListener, is_all_systems_go

REPO = Path(__file__).resolve().parents[1]


# --- helpers -----------------------------------------------------------------

class FakeVoice:
    """Stands in for RoomVoiceCheck: returns a fixed score (None = no profile)."""

    def __init__(self, score):
        self.value = score

    def score(self, audio):
        return self.value


def track(identity=None, stay="stay_1", box=(400, 300, 150, 170), duration=60.0):
    """A tracked person; the default box is someone sitting on the couch."""
    return SimpleNamespace(assigned_identity=identity, stay_id=stay, track_id=1, box=list(box), duration=duration)


def coats():
    """The phantom 'person' the detector sees in the coats by the front door (2026-10-16 logs)."""
    return track(None, stay="stay_coats", box=(0, 384, 53, 91), duration=25000.0)


def make_listener(db, score=0.9, tracks=None, motion=False):
    pipeline = MagicMock()
    pipeline._motion_active.return_value = motion
    tracker = SimpleNamespace(active_tracks=list(tracks or []))
    listener = RoomListener(pipeline=pipeline, tracker=tracker, db_path=db, voice_check=FakeVoice(score))
    return listener, tracker


def said(listener, text):
    """Make the fake Whisper model 'hear' `text`."""
    seg = SimpleNamespace(text=text)
    model = MagicMock()
    model.transcribe.return_value = ([seg], MagicMock())
    listener._model = model


def process(listener, text, start, end=None, people=("Col",), someone_else=None):
    said(listener, text)
    return listener._process_speech_segment(
        np.zeros(16000, dtype=np.float32), start, end if end is not None else start + 2.0,
        list(people), "stay_1", someone_else,
    )


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test_archer.db")
    SQLiteStore(path)  # creates the schema
    return path


# --- 1. Presence gating -----------------------------------------------------------

class FakeProc:
    """A fake ffmpeg that serves `n_frames` of audio; when they run out it stops the listener."""

    class _Out:
        def __init__(self, data, on_done):
            self._buf = io.BytesIO(data)
            self._on_done = on_done

        def read(self, n):
            chunk = self._buf.read(n)
            if not chunk:
                self._on_done()
            return chunk

    def __init__(self, n_frames, on_done):
        self.stdout = self._Out(b"\x01\x00" * 480 * n_frames, on_done)

    def poll(self):
        return None

    def kill(self):
        pass


def run_capture(listener, n_frames=200):
    """Run the real capture loop over fake audio where every frame counts as speech."""
    listener._config = SimpleNamespace(network_camera_url="rtsp://fake", room_voice_threshold=0.35)
    listener._vad = MagicMock()
    listener._vad.is_speech.return_value = True
    listener._running.set()
    with patch.object(rl, "start_camera_audio", lambda url, rate=16000: FakeProc(n_frames, listener._running.clear)):
        listener._capture_loop()


def test_nothing_is_queued_when_the_room_is_empty(db):
    listener, _ = make_listener(db, tracks=[])
    listener._last_seen = time.time() - 3 * 3600  # nobody seen for 3 hours
    run_capture(listener)
    assert len(listener._audio_queue) == 0
    assert SQLiteStore(db).get_listening_status()["state"] == "empty"


def test_speech_is_queued_when_someone_is_in_the_room(db):
    listener, _ = make_listener(db, tracks=[track("Col")])
    run_capture(listener, n_frames=600)
    assert len(listener._audio_queue) >= 1
    audio, start, end, people, stay, someone_else = listener._audio_queue[0]
    assert people == ["Col"] and stay == "stay_1" and someone_else is False
    assert SQLiteStore(db).get_listening_status()["state"] == "listening"


def test_nothing_is_queued_while_paused(db):
    SQLiteStore(db).set_listening_pause(duration_seconds=-1)
    listener, _ = make_listener(db, tracks=[track("Col")])
    run_capture(listener, n_frames=600)
    assert len(listener._audio_queue) == 0
    assert SQLiteStore(db).get_listening_status()["state"] == "paused"


# --- 2. No audio files, no transcript words in logs ----------------------------------

def test_listener_source_never_writes_audio():
    src = (REPO / "src" / "archer" / "observer" / "room_listener.py").read_text(encoding="utf-8")
    for forbidden in ("import soundfile", "sf.write", "import wave", "wave.open", ".wav", "np.save", "tofile("):
        assert forbidden not in src, forbidden


def test_no_files_written_while_processing(db, tmp_path, monkeypatch):
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    listener, _ = make_listener(db, tracks=[track("Col")])
    run_capture(listener, n_frames=600)
    while listener._audio_queue:
        item = listener._audio_queue.popleft()
        said(listener, "testing one two three")
        listener._process_speech_segment(*item)
    assert list(work.rglob("*")) == []


def test_transcript_words_never_go_into_the_log(db):
    from loguru import logger

    lines = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        listener, _ = make_listener(db, score=0.9)
        process(listener, "my secret zebra password phrase", time.time())
        listener._config = SimpleNamespace(room_voice_threshold=0.35)
        listener._voice = FakeVoice(0.1)
        process(listener, "television says a purple elephant line", time.time(), someone_else=False)
    finally:
        logger.remove(sink)
    log = "\n".join(lines)
    assert "line saved" in log
    for word in ("zebra", "password", "purple", "elephant"):
        assert word not in log


# --- 3. ARCHER's own voice ----------------------------------------------------------------

def test_archer_voice_needs_time_and_words(db):
    store = SQLiteStore(db)
    now = time.time()
    store.log_archer_speech(now - 10, now - 5, "Good afternoon Col, your dentist appointment is at three PM tomorrow.")
    heard = (now - 10 + 1.18, now - 5 + 1.18)
    assert store.check_if_archer_speech(*heard, "good afternoon col your dentist appointment is at three tomorrow")
    # Same time, different words: Col talking over ARCHER stays Col's.
    assert not store.check_if_archer_speech(*heard, "hang on I need to grab my keys first")
    # Same words much later: Col repeating ARCHER isn't ARCHER.
    assert not store.check_if_archer_speech(now + 120, now + 124, "your dentist appointment is at three tomorrow")
    # Only common words in common doesn't count.
    assert not store.check_if_archer_speech(*heard, "and you are the one that was there")


def test_archer_lines_are_kept_and_marked_and_never_commands(db):
    store = SQLiteStore(db)
    now = time.time()
    store.log_archer_speech(now - 6, now - 2, "All systems go is my favourite phrase, Col, and I will forget that later.")
    listener, _ = make_listener(db, score=0.1)
    with patch.object(listener, "_trigger_all_systems_go") as launch:
        row = process(listener, "all systems go is my favourite phrase col and i will forget that later",
                      now - 6 + 1.18, now - 2 + 1.18, someone_else=False)
    assert row and row > 0
    saved = store.get_recent_room_transcripts(limit=5)[0]
    assert saved["is_archer"] and saved["voice"] == "archer"
    launch.assert_not_called()


# --- 4. Pause ---------------------------------------------------------------------------

def test_pause_holds_through_restart(db):
    a = SQLiteStore(db)
    a.set_listening_pause(duration_seconds=900)
    assert SQLiteStore(db).is_listening_paused()
    a.set_listening_pause(duration_seconds=-1)
    assert SQLiteStore(db).get_listening_status() == {"state": "paused", "until": -1.0}
    SQLiteStore(db).set_listening_pause(duration_seconds=0)
    assert not SQLiteStore(db).is_listening_paused()


def test_paused_speech_is_not_transcribed(db):
    SQLiteStore(db).set_listening_pause(duration_seconds=-1)
    listener, _ = make_listener(db)
    said(listener, "anything")
    assert listener._process_speech_segment(np.zeros(16000, dtype=np.float32), time.time(), time.time() + 1, ["Col"], None) is None
    listener._model.transcribe.assert_not_called()


def test_stop_listening_by_voice_pauses_for_an_hour(db):
    listener, _ = make_listener(db)
    process(listener, "ARCHER, stop listening.", time.time())
    until = SQLiteStore(db).get_listening_pause()
    assert 3500 < until - time.time() <= 3600


def test_status_reports_off_when_the_observer_is_silent(db):
    store = SQLiteStore(db)
    assert store.get_listening_status()["state"] == "off"
    store.set_listener_state("empty")
    assert store.get_listening_status()["state"] == "empty"
    store.set_listener_state("listening", now=time.time() - 120)
    assert store.get_listening_status()["state"] == "off"


# --- 5. "Forget that" ---------------------------------------------------------------------

def test_forget_that_removes_the_last_two_minutes_and_itself(db):
    store = SQLiteStore(db)
    now = time.time()
    listener, _ = make_listener(db)
    process(listener, "old line from five minutes ago", now - 300)
    process(listener, "my account number is something private", now - 60)
    process(listener, "ARCHER, forget that.", now - 2, now)
    texts = [r["transcript"] for r in store.get_recent_room_transcripts(limit=10)]
    assert texts == ["old line from five minutes ago"]


def test_forgotten_window_blocks_lines_still_in_the_queue(db):
    store = SQLiteStore(db)
    now = time.time()
    store.forget_recent_room_transcripts(seconds=120, now=now)  # the page's button
    listener, _ = make_listener(db)
    assert process(listener, "this was said before the button press", now - 30) is None
    assert process(listener, "this comes after", now + 5) is not None


# --- 6. "All systems go" ----------------------------------------------------------------

def test_all_systems_go_variants():
    for p in ["all systems go", "All Systems Go!", "all system go", "All systems goal", "whole systems go",
              "ARCHER, all systems go please", "OK all systems go now"]:
        assert is_all_systems_go(p), p
    for p in ["all system", "systems go", "all things go", "is the system go", "the systems are going",
              "go to all systems", "all good systems", "ordinary conversation"]:
        assert not is_all_systems_go(p), p


def test_startup_announcement_never_says_the_phrase():
    src = (REPO / "src" / "archer" / "web_main.py").read_text(encoding="utf-8")
    line = src.split('STARTUP_ANNOUNCEMENT = "', 1)[1].split('"', 1)[0]
    assert line and not is_all_systems_go(line)


def test_launch_is_requested_with_cooldown(db):
    listener, _ = make_listener(db)
    with patch.object(rl.subprocess, "run") as run:
        run.return_value = SimpleNamespace(returncode=0)
        process(listener, "all systems go", time.time())
        process(listener, "all systems go", time.time())  # within the cooldown
    assert run.call_count == 1
    assert run.call_args[0][0] == ["schtasks.exe", "/run", "/tn", "ArcherLaunchOnVoice"]
    row = SQLiteStore(db)._listening_row()
    assert time.time() - row["launch_requested_at"] < 5


def test_tv_cannot_trigger_a_launch(db):
    listener, _ = make_listener(db, score=0.05)
    with patch.object(rl.subprocess, "run") as run:
        assert process(listener, "all systems go", time.time(), someone_else=False) is None
    run.assert_not_called()


def _load_launch_check():
    spec = importlib.util.spec_from_file_location("launch_check", REPO / "scripts" / "launch_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_launch_check_reads_the_real_table(db):
    lc = _load_launch_check()
    store = SQLiteStore(db)
    assert lc.consume_launch_request(Path(db)) == (False, 0.0)
    store.request_launch(time.time() - 30)
    ok, previous = lc.consume_launch_request(Path(db))
    assert ok and previous == 0.0
    assert lc.consume_launch_request(Path(db))[0] is False  # handled once only
    store.request_launch(time.time() - 700)  # older than 10 minutes
    assert lc.consume_launch_request(Path(db))[0] is False


def test_launch_check_never_starts_a_second_copy(db, tmp_path):
    lc = _load_launch_check()
    (tmp_path / "ARCHER-Web.bat").write_text("@echo off\n")
    lc.ARCHER_ROOT = tmp_path
    store = SQLiteStore(db)
    store.request_launch(time.time() - 60)
    with patch.object(lc, "is_archer_running", return_value=False), patch.object(lc.subprocess, "Popen") as popen:
        assert lc.main(["--db-path", db]) == 0
        assert popen.call_count == 1
        store.request_launch(time.time())  # said again while ARCHER is still starting
        assert lc.main(["--db-path", db]) == 0
        assert popen.call_count == 1
    with patch.object(lc, "is_archer_running", return_value=True), patch.object(lc.webbrowser, "open") as browse:
        store.request_launch(time.time() + 1)
        lc.main(["--db-path", db])
        browse.assert_called_once()


def test_launch_check_says_nothing():
    src = (REPO / "scripts" / "launch_check.py").read_text(encoding="utf-8")
    assert "SAPI" not in src and "pyttsx3" not in src and "Speak(" not in src


def test_launch_task_runs_with_normal_rights():
    src = (REPO / "scripts" / "setup_archer_launch_task.ps1").read_text(encoding="utf-8")
    assert "-RunLevel Limited" in src and "HIGHEST" not in src.upper()


# --- 7. Times -------------------------------------------------------------------------

def test_time_format():
    assert format_room_transcript_timestamp(datetime(2026, 10, 13, 15, 42).timestamp()) == "Tue Oct 13, 3:42 PM"
    assert format_room_transcript_timestamp(datetime(2026, 10, 5, 9, 5).timestamp()) == "Mon Oct 5, 9:05 AM"


def test_saved_lines_use_the_shared_format(db):
    listener, _ = make_listener(db)
    ts = datetime(2026, 10, 15, 15, 7).timestamp()
    process(listener, "a line", ts)
    assert SQLiteStore(db).get_recent_room_transcripts(1)[0]["start_datetime"] == "Thu Oct 15, 3:07 PM"


# --- 8. Asking ARCHER about the past --------------------------------------------------------

def _agent(store):
    from archer.agents.core_agent import CoreAgent

    agent = CoreAgent()
    agent._store = store
    return agent


def test_chat_finds_a_line_only_when_asked_about_past_speech(db):
    store = SQLiteStore(db)
    tuesday = datetime.now().replace(hour=15, minute=42, second=0, microsecond=0)
    while tuesday.weekday() != 1 or tuesday.date() >= datetime.now().date():
        tuesday -= timedelta(days=1)
    store.insert_room_transcript(
        text="I told the electrical contractor to replace the breaker panel on Friday",
        start_time=tuesday.timestamp(), end_time=tuesday.timestamp() + 5, voice="col",
        people_in_view=["Col"],
    )
    agent = _agent(store)
    with patch("archer.memory.sqlite_store.get_sqlite_store", return_value=store):
        prompt, trigger, _img, local_only = agent.build_context_system_prompt(
            "what did I tell the contractor on Tuesday?"
        )
        assert "breaker panel" in local_only and "Tue " in local_only
        assert "breaker panel" not in prompt  # never in the part that can go to a cloud model
        prompt2, _t, _i, local2 = agent.build_context_system_prompt("tell me about electrical panels")
        assert "breaker panel" not in prompt2 and "breaker panel" not in local2


def test_transcripts_keep_the_turn_local(db):
    store = SQLiteStore(db)
    store.insert_room_transcript(text="the contractor said the quote is four thousand", start_time=time.time() - 3600,
                                 end_time=time.time() - 3595, voice="col")
    agent = _agent(store)
    with patch.object(agent, "evaluate_cloud_delegation", return_value="explicit_request"):
        _p, trigger, _i, local_only = agent.build_context_system_prompt("what did the contractor say about the quote earlier?")
    assert trigger is None and "four thousand" in local_only


def test_start_listening_said_to_archer_resumes(db):
    store = SQLiteStore(db)
    store.set_listening_pause(duration_seconds=-1)
    agent = _agent(store)
    reply, trigger, _i, _l = agent.build_context_system_prompt("start listening")
    assert trigger == "direct_reply" and "back on" in reply
    assert not store.is_listening_paused()


# --- 9. Whose speech is kept (Col, 2026-10-15) -----------------------------------------------

def test_cols_voice_is_kept(db):
    listener, _ = make_listener(db, score=0.8)
    assert process(listener, "this is me talking", time.time(), someone_else=False)
    assert SQLiteStore(db).get_recent_room_transcripts(1)[0]["voice"] == "col"


def test_other_voice_alone_with_col_is_not_saved(db):
    listener, _ = make_listener(db, score=0.1)
    assert process(listener, "and now the weather for tonight", time.time(), someone_else=False) is None
    assert SQLiteStore(db).get_recent_room_transcripts(5) == []


def test_other_voice_kept_when_someone_else_is_seen(db):
    listener, _ = make_listener(db, score=0.1)
    assert process(listener, "nice to meet you", time.time(), people=("Col", "unidentified person"), someone_else=True)
    row = SQLiteStore(db).get_recent_room_transcripts(1)[0]
    assert row["voice"] == "other" and row["people_in_view"] == ["Col", "unidentified person"]


def test_without_a_profile_lines_are_kept_unchecked(db):
    listener, _ = make_listener(db, score=None)
    assert process(listener, "before enrollment", time.time(), someone_else=False)
    assert SQLiteStore(db).get_recent_room_transcripts(1)[0]["voice"] == "unchecked"


def test_who_is_in_view(db):
    listener, tracker = make_listener(db, tracks=[])
    assert listener._get_current_people_in_view() == []
    assert listener._someone_besides_col_in_view() is False
    tracker.active_tracks = [track(None)]
    assert listener._get_current_people_in_view() == ["unidentified person"]
    assert listener._someone_besides_col_in_view() is False  # most likely Col, not yet recognized
    tracker.active_tracks = [track("Col"), track(None, box=(150, 300, 150, 170))]  # beside Col
    assert listener._someone_besides_col_in_view() is True
    tracker.active_tracks = [track("Person_95")]
    assert listener._someone_besides_col_in_view() is True
    tracker.active_tracks = [track(None, duration=3.0), track("Col")]
    assert listener._someone_besides_col_in_view() is False  # only just appeared


def test_the_coats_by_the_door_are_not_a_person(db):
    listener, tracker = make_listener(db, tracks=[coats()])
    assert listener.someone_in_view() is False
    assert listener._get_current_people_in_view() == []
    tracker.active_tracks = [track("Col"), coats()]
    assert listener._someone_besides_col_in_view() is False
    assert listener._get_current_people_in_view() == ["Col"]
    # Col lying on the couch, face not visible: still a person.
    tracker.active_tracks = [track(None, box=(314, 392, 231, 87)), coats()]
    assert listener.someone_in_view() is True


# --- 10. Reconnecting to the camera -------------------------------------------------------

def test_ffmpeg_restarts_wait_longer_each_time(db):
    listener, _ = make_listener(db, tracks=[track("Col")])
    listener._config = SimpleNamespace(network_camera_url="rtsp://fake", room_voice_threshold=0.35)
    waits = []

    def fake_sleep(seconds):
        waits.append(seconds)
        if len(waits) >= 4:
            listener._running.clear()
        return not listener._running.is_set()

    dead = SimpleNamespace(stdout=io.BytesIO(b""), poll=lambda: 1, kill=lambda: None)
    listener._running.set()
    with patch.object(rl, "start_camera_audio", lambda url, rate=16000: dead), \
            patch.object(listener, "_sleep_while_running", fake_sleep):
        listener._capture_loop()
    assert waits[:4] == [3.0, 6.0, 12.0, 24.0]


# --- 11. ARCHER starts and the page loads ---------------------------------------------

def test_server_imports_and_reports_listening_status(db):
    import archer.server as server  # failed before the review fixes (EventType.CUSTOM)

    assert hasattr(server, "_listening_status_loop")


@pytest.mark.skipif(shutil.which("node") is None, reason="node isn't installed")
def test_page_script_loads_and_shows_each_state(tmp_path):
    harness = tmp_path / "harness.js"
    harness.write_text(
        """
const fs = require('fs'); const vm = require('vm');
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, textContent: '', style: {}, listeners: {},
    classList: { s: new Set(), add(c){this.s.add(c)}, remove(...c){c.forEach(x=>this.s.delete(x))},
                 toggle(c,on){on?this.s.add(c):this.s.delete(c)}, contains(c){return this.s.has(c)} },
    addEventListener(t,f){this.listeners[t]=f}, appendChild(){}, scrollTop:0, scrollHeight:0, value:'' };
  return els[id];
}
const handlers = {};
const ctx = { document: { getElementById: el, createElement: () => el('x' + Math.random()) },
  ArcherClient: new Proxy({}, { get: (t, k) => k === 'on' ? (n, f) => { handlers[n] = f } : () => {} }),
  setTimeout, console, Date };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const out = {};
for (const s of ['listening', 'paused', 'empty', 'off']) {
  handlers.listeningState({ state: s, until: s === 'paused' ? -1 : 0 });
  out[s] = [els['archer-listening-indicator'].textContent, els['archer-listen-resume'].style.display];
}
console.log(JSON.stringify(out));
""",
        encoding="utf-8",
    )
    res = subprocess.run(["node", str(harness), str(REPO / "web" / "js" / "ui.js")], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    out = __import__("json").loads(res.stdout.strip().splitlines()[-1])
    assert out["listening"][0] == "LISTENING" and out["paused"] == ["PAUSED", "inline-block"]
    assert out["empty"][0] == "EMPTY" and out["off"][0] == "OFF"


# --- 10. One person seen as two boxes (2026-10-20 logs) ---------------------------------

def test_col_tracked_twice_on_the_couch_is_one_person(db):
    # Logged at 11:19-11:22: a second, unidentified box inside Col's box.
    listener, _ = make_listener(db, tracks=[
        track("Col", box=(357, 350, 208, 129)),
        track(None, stay="stay_2", box=(379, 363, 83, 113)),
    ])
    assert not listener._someone_besides_col_in_view()
    assert listener._get_current_people_in_view() == ["Col"]


def test_a_mostly_overlapping_second_box_is_the_same_person(db):
    # Logged at 11:22: 67% of the unidentified box lies inside Col's.
    listener, _ = make_listener(db, tracks=[
        track("Col", box=(392, 362, 168, 115)),
        track(None, stay="stay_2", box=(351, 367, 124, 107)),
    ])
    assert not listener._someone_besides_col_in_view()


def test_two_unidentified_boxes_on_one_person_are_not_company(db):
    listener, _ = make_listener(db, tracks=[
        track(None, box=(357, 350, 208, 129)),
        track(None, stay="stay_2", box=(379, 363, 83, 113)),
    ])
    assert not listener._someone_besides_col_in_view()
    assert listener._get_current_people_in_view() == ["unidentified person"]


def test_a_guest_beside_col_still_counts(db):
    listener, _ = make_listener(db, tracks=[
        track("Col", box=(250, 300, 150, 170)),
        track(None, stay="stay_2", box=(420, 300, 150, 170)),
    ])
    assert listener._someone_besides_col_in_view()


def test_a_guest_partly_overlapping_col_still_counts(db):
    # Sitting close: 30% of the guest's box overlaps Col's.
    listener, _ = make_listener(db, tracks=[
        track("Col", box=(250, 300, 150, 170)),
        track(None, stay="stay_2", box=(355, 300, 150, 170)),
    ])
    assert listener._someone_besides_col_in_view()


# --- 11. The room stays occupied for a while after someone was seen (2026-10-20) ----------

def test_room_counts_as_occupied_right_after_the_observer_starts(db):
    listener, _ = make_listener(db, tracks=[])
    assert listener.someone_in_view() is False
    assert listener.is_room_active() is True


def test_col_lying_still_and_undetected_is_still_in_the_room(db):
    listener, tracker = make_listener(db, tracks=[track("Col")])
    assert listener.is_room_active() is True
    tracker.active_tracks = []                    # the detector loses him on the couch
    listener._last_seen = time.time() - 30 * 60   # half an hour ago
    assert listener.is_room_active() is True


def test_room_empties_two_hours_after_anyone_was_seen(db):
    listener, _ = make_listener(db, tracks=[])
    listener._last_seen = time.time() - 121 * 60
    assert listener.is_room_active() is False


def test_speech_is_queued_while_the_room_lingers(db):
    listener, _ = make_listener(db, tracks=[])
    listener._last_seen = time.time() - 10 * 60
    run_capture(listener, n_frames=600)
    assert len(listener._audio_queue) >= 1
    assert listener._audio_queue[0][3] == []  # nobody in view to list
