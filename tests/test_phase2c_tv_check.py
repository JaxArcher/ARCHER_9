"""
Phase 2c TV check (Col, 2026-10-20): videos play from the PC, so a room line
that would be kept but repeats words the PC was playing at that moment is the
TV and isn't saved, whoever's voice it sounds like. See
src/archer/observer/pc_playback.py.

Claude, 2026-10-20. Uses fake audio, a fake Whisper and a fake soundcard;
the real devices and databases are never touched.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from archer.memory.sqlite_store import SQLiteStore
from archer.observer.pc_playback import (
    AUDIBLE_RMS,
    BLOCK_SECONDS,
    OUT_RATE,
    WINDOW_AFTER,
    WINDOW_BEFORE,
    PCPlayback,
    words_match,
)
from archer.observer.room_listener import CAMERA_AUDIO_LAG_SECONDS, RoomListener

REPO = Path(__file__).resolve().parents[1]
LAG = CAMERA_AUDIO_LAG_SECONDS
BLOCK = int(OUT_RATE * BLOCK_SECONDS)

# From the 2026-10-20 TV test: the room's rough transcript of a game video,
# and what the PC itself was saying.
ROOM_TV = "19 points of bludgeoning damage. Thank you for the same topic. Yeah. Plus, five"
PC_TV = "That's 19 points of bludgeoning damage. Thank you for the save, Tom. Yeah, plus five more fire damage."
COL = "Hold on, I need to call the contractor about the breaker panel tomorrow."


# --- helpers -------------------------------------------------------------------

def filled(start: float, seconds: float, level: float = 0.1) -> PCPlayback:
    """A PCPlayback holding `seconds` of playback at `level`, from `start`."""
    pb = PCPlayback()
    n = int(round(seconds / BLOCK_SECONDS))
    for i in range(n):
        pb.add_block(start + (i + 1) * BLOCK_SECONDS, np.full(BLOCK, level, dtype=np.float32))
    return pb


class FakeVoice:
    def __init__(self, score):
        self.value = score

    def score(self, audio):
        return self.value


PLAYBACK_MARK = 0.123  # fake playback audio is filled with this, so the fake Whisper can tell


class FakePlayback:
    """Stands in for PCPlayback: playing `played` (text), or nothing (None)."""

    def __init__(self, played, playing="auto"):
        self.played = played
        self.playing = (played is not None) if playing == "auto" else playing  # True / False / None
        self.asked = 0
        self.started = self.stopped = False

    def playing_during(self, start_ts, end_ts, lag):
        return self.playing

    def played_audio_for(self, start_ts, end_ts, lag):
        self.asked += 1
        return None if self.played is None else np.full(OUT_RATE, PLAYBACK_MARK, dtype=np.float32)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def fake_whisper(room_text, played_text):
    def transcribe(audio, **kwargs):
        text = played_text if len(audio) and audio[0] == np.float32(PLAYBACK_MARK) else room_text
        return [SimpleNamespace(text=text)], MagicMock()

    model = MagicMock()
    model.transcribe.side_effect = transcribe
    return model


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test_archer.db")
    SQLiteStore(path)
    return path


def make_listener(db, score, played, playing="auto"):
    pipeline = MagicMock()
    pipeline._motion_active.return_value = False
    return RoomListener(pipeline=pipeline, tracker=SimpleNamespace(active_tracks=[]), db_path=db,
                        voice_check=FakeVoice(score), playback=FakePlayback(played, playing))


def process(listener, text, start, end=None, someone_else=False):
    listener._model = fake_whisper(text, getattr(listener._playback, "played", None))
    return listener._process_speech_segment(
        np.zeros(OUT_RATE * 3, dtype=np.float32), start, end if end is not None else start + 3.0,
        ["Col"], "stay_1", someone_else,
    )


# --- 1. Word matching -------------------------------------------------------------

def test_tv_line_repeats_the_pcs_words():
    share, n = words_match(ROOM_TV, PC_TV)
    assert n >= 3 and share >= 0.6


def test_cols_words_while_a_video_plays_dont_match():
    share, _ = words_match(COL, PC_TV)
    assert share < 0.2


def test_rough_transcripts_still_match_by_word_start():
    share, _ = words_match("the dragon slithered across bludgeons everyone", "the dragon slithers across, bludgeoning everyone")
    assert share == 1.0


def test_lines_with_too_few_words_are_not_judged():
    assert words_match("Okay. So. Okay. So.", PC_TV) is None
    assert words_match("Hold on", "hold on") is None


def test_common_words_dont_count():
    assert words_match("and then you were there with them", "and then you were there with them") is None


# --- 2. The PC's playback, looking back --------------------------------------------

def test_playback_for_a_line_covers_its_time_minus_the_camera_delay():
    now = 1_800_000_000.0
    pb = filled(now - 60, 60)
    start, end = now - 20, now - 10
    played = pb.played_audio_for(start, end, LAG)
    expected = (end - LAG + WINDOW_AFTER) - (start - LAG - WINDOW_BEFORE)
    assert played is not None
    assert abs(len(played) / OUT_RATE - expected) <= 2 * BLOCK_SECONDS


def test_nothing_audible_playing_is_not_judged():
    now = 1_800_000_000.0
    pb = filled(now - 60, 60, level=AUDIBLE_RMS / 10)
    assert pb.played_audio_for(now - 20, now - 10, LAG) is None


def test_not_judged_when_the_playback_was_not_recorded():
    now = 1_800_000_000.0
    assert PCPlayback().played_audio_for(now - 20, now - 10, LAG) is None
    pb = filled(now - 60, 30)  # recording stopped 30 s ago
    assert pb.played_audio_for(now - 20, now - 10, LAG) is None


def test_only_the_last_two_minutes_are_kept():
    pb = filled(1000.0, 300)
    assert len(pb._blocks) == int(120 / BLOCK_SECONDS)


# --- 3. The room listener ----------------------------------------------------------------

def test_tv_line_in_a_voice_like_cols_is_not_saved(db):
    listener = make_listener(db, score=0.62, played=PC_TV)
    assert process(listener, ROOM_TV, time.time()) is None
    assert SQLiteStore(db).get_recent_room_transcripts(5) == []
    assert listener._tv_dropped_count == 1


def test_col_talking_while_a_video_plays_is_kept(db):
    listener = make_listener(db, score=0.6, played=PC_TV)
    assert process(listener, COL, time.time())
    assert SQLiteStore(db).get_recent_room_transcripts(1)[0]["voice"] == "col"


def test_with_nothing_playing_the_voice_rule_decides(db):
    listener = make_listener(db, score=0.6, played=None)
    assert process(listener, COL, time.time())
    listener = make_listener(db, score=0.2, played=None)
    assert process(listener, "a voice that is not cols at all", time.time()) is None


def test_lines_the_voice_rule_drops_never_transcribe_the_pc(db):
    listener = make_listener(db, score=0.1, played=PC_TV)
    assert process(listener, ROOM_TV, time.time()) is None
    assert listener._playback.asked == 0


def test_short_lines_never_transcribe_the_pc(db):
    listener = make_listener(db, score=0.9, played=PC_TV)
    assert process(listener, "Hold on.", time.time())
    assert listener._playback.asked == 0


def test_tv_line_seen_with_a_guest_is_still_the_tv(db):
    listener = make_listener(db, score=0.1, played=PC_TV)
    assert process(listener, ROOM_TV, time.time(), someone_else=True) is None


def test_archer_is_still_marked_when_it_plays_through_the_pc(db):
    store = SQLiteStore(db)
    now = time.time()
    said = "Your dentist appointment is at three tomorrow afternoon, Col."
    store.log_archer_speech(now - 6, now - 2, said)
    listener = make_listener(db, score=0.1, played=said)
    assert process(listener, said, now - 6 + 1.18, now - 2 + 1.18)
    assert store.get_recent_room_transcripts(1)[0]["voice"] == "archer"


def test_the_tv_cannot_give_commands(db):
    said = "Archer stop listening, said the villain to the computer on the bridge."
    listener = make_listener(db, score=0.9, played=said)
    process(listener, said, time.time())
    assert not SQLiteStore(db).is_listening_paused()


def test_tv_check_errors_never_lose_cols_speech(db):
    listener = make_listener(db, score=0.9, played=PC_TV)
    listener._playback.played_audio_for = MagicMock(side_effect=RuntimeError("device gone"))
    assert process(listener, COL, time.time())


def test_tv_check_follows_the_listener(db, monkeypatch):
    listener = make_listener(db, score=0.9, played=None)
    monkeypatch.setattr(listener, "_capture_loop", lambda: None)
    monkeypatch.setattr(listener, "_transcription_worker", lambda: None)
    listener._config = SimpleNamespace(network_camera_url="rtsp://fake")
    assert listener.start()
    listener.stop()
    assert listener._playback.started and listener._playback.stopped


def test_tv_check_can_be_switched_off(db, monkeypatch):
    from archer import config as cfg

    monkeypatch.setattr(cfg.get_config(), "room_tv_check", False)
    listener = RoomListener(pipeline=MagicMock(), tracker=SimpleNamespace(active_tracks=[]),
                            db_path=db, voice_check=FakeVoice(0.9))
    assert listener._playback is None
    assert process(listener, ROOM_TV, time.time())


# --- 4. Recording the PC's playback --------------------------------------------

class FakeRecorder:
    def __init__(self, level):
        self.level = level

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def record(self, numframes):
        time.sleep(0.01)
        return np.full((numframes, 2), self.level, dtype=np.float32)


def fake_soundcard(level=0.1, fail=False, seen=None):
    speaker = SimpleNamespace(id="{lg}", name="LG-SOUND BAR (NVIDIA High Definition Audio)")

    def recorder(samplerate, blocksize=None):
        if seen is not None:
            seen.update(samplerate=samplerate, blocksize=blocksize)
        return FakeRecorder(level)

    def get_microphone(id, include_loopback=False):
        assert include_loopback and id == "{lg}"
        if fail:
            raise RuntimeError("no such device")
        return SimpleNamespace(recorder=recorder)

    return SimpleNamespace(default_speaker=lambda: speaker, get_microphone=get_microphone)


def wait_for(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_records_the_default_output_at_16khz_with_a_roomy_buffer(monkeypatch):
    seen: dict = {}
    monkeypatch.setitem(sys.modules, "soundcard", fake_soundcard(level=0.1, seen=seen))
    pb = PCPlayback()
    pb.start()
    try:
        assert wait_for(lambda: len(pb._blocks) >= 10)
        assert pb.recording and pb.device.startswith("LG-SOUND BAR")
        _, audio, loudness = pb._blocks[-1]
        assert len(audio) == BLOCK and loudness == pytest.approx(0.1, abs=0.01)
        assert seen["samplerate"] == 48000 and seen["blocksize"] >= 48000 * 0.25
    finally:
        pb.stop()
    assert not pb.recording


def test_recording_failures_retry_and_stop_cleanly(monkeypatch):
    monkeypatch.setitem(sys.modules, "soundcard", fake_soundcard(fail=True))
    pb = PCPlayback()
    pb.start()
    time.sleep(0.3)
    assert not pb.recording
    started = time.time()
    pb.stop()
    assert time.time() - started < 1.5  # the retry wait doesn't hold up stopping


def test_no_soundcard_means_no_tv_check(monkeypatch):
    monkeypatch.setitem(sys.modules, "soundcard", None)  # import fails
    pb = PCPlayback()
    pb.start()
    pb.stop()
    assert not pb.recording and len(pb._blocks) == 0


def test_soundcard_is_imported_before_the_thread_joins_com():
    # soundcard's import sets up COM itself and raises if the thread already
    # did ("already set up" isn't handled), which switched the TV check off
    # in the 2026-10-20 live test.
    src = (REPO / "src" / "archer" / "observer" / "pc_playback.py").read_text(encoding="utf-8")
    loop = src[src.index("def _loop"):]
    assert loop.index("import soundcard as sc") < loop.index("CoInitializeEx(")


def test_playback_source_never_writes_audio():
    src = (REPO / "src" / "archer" / "observer" / "pc_playback.py").read_text(encoding="utf-8")
    for forbidden in ("import soundfile", "sf.write", "import wave", "wave.open", ".wav", "np.save", "tofile(", "open("):
        assert forbidden not in src, forbidden


# --- 5. A lower voice bar while the PC is quiet (muted-TV test, 2026-10-20) ----------

def test_short_remark_kept_while_the_pc_is_quiet(db):
    listener = make_listener(db, score=0.4, played=None, playing=False)
    assert process(listener, "let's just button that", time.time())
    assert SQLiteStore(db).get_recent_room_transcripts(1)[0]["voice"] == "col"


def test_same_score_dropped_while_the_pc_plays(db):
    listener = make_listener(db, score=0.4, played="something else entirely on the video", playing=True)
    assert process(listener, "let's just button that", time.time()) is None


def test_usual_bar_when_unsure_whether_the_pc_played(db):
    listener = make_listener(db, score=0.4, played=None, playing=None)
    assert process(listener, "let's just button that", time.time()) is None


def test_quiet_bar_never_goes_below_a_very_different_voice(db):
    listener = make_listener(db, score=0.2, played=None, playing=False)
    assert process(listener, "a stranger on a speakerphone", time.time()) is None


def test_playing_during_reports_quiet_playing_and_unknown():
    now = 1_800_000_000.0
    assert filled(now - 60, 60).playing_during(now - 20, now - 10, LAG) is True
    assert filled(now - 60, 60, level=0.0).playing_during(now - 20, now - 10, LAG) is False
    assert PCPlayback().playing_during(now - 20, now - 10, LAG) is None


# --- 6. Commands from any voice the PC didn't play; other voices only while it's quiet ----

def run_command(db, said, played, playing):
    from unittest.mock import patch

    listener = make_listener(db, score=0.1, played=played, playing=playing)
    with patch.object(listener, "_trigger_all_systems_go") as launch:
        row = process(listener, said, time.time())
    return row, launch


def test_all_systems_go_counts_from_a_low_scoring_voice_when_the_pc_is_quiet(db):
    # 2026-10-20 13:25: Col's "all systems go" scored 0.16 on voice and was dropped.
    row, launch = run_command(db, "All systems go.", played=None, playing=False)
    assert row is None  # the line itself still isn't saved
    launch.assert_called_once()


def test_command_the_pc_played_is_ignored(db):
    _, launch = run_command(db, "All systems go.", played="Captain, all systems go for launch.", playing=True)
    launch.assert_not_called()


def test_command_counts_while_the_pc_plays_something_else(db):
    _, launch = run_command(db, "All systems go.", played=PC_TV, playing=True)
    launch.assert_called_once()


def test_command_ignored_when_unsure_whether_the_pc_played_it(db):
    _, launch = run_command(db, "All systems go.", played=None, playing=None)
    launch.assert_not_called()


def test_stop_listening_from_any_voice_when_the_pc_is_quiet(db):
    run_command(db, "Archer, stop listening.", played=None, playing=False)
    assert SQLiteStore(db).is_listening_paused()


def test_other_voice_not_kept_while_the_pc_plays(db):
    # The people tracker's phantoms made TV speech count as "another voice".
    listener = make_listener(db, score=0.1, played=PC_TV, playing=True)
    assert process(listener, "nice to meet you all finally", time.time(), someone_else=True) is None


def test_other_voice_kept_while_the_pc_is_quiet(db):
    listener = make_listener(db, score=0.1, played=None, playing=False)
    assert process(listener, "nice to meet you all finally", time.time(), someone_else=True)
    assert SQLiteStore(db).get_recent_room_transcripts(1)[0]["voice"] == "other"
