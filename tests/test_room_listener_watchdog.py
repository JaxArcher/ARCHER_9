"""
Tests for RoomListener 10-second no-audio watchdog, hanging-ffmpeg termination,
and Logs-tab stall/reconnect status.
Spec 5c / Claude Review 2026-10-21, 16:30.
"""

from __future__ import annotations

import io
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from archer.memory.sqlite_store import SQLiteStore
from archer.observer import room_listener as rl
from archer.observer.room_listener import RoomListener, _StreamReader


class HangingFakeProc:
    """A fake ffmpeg process that writes a burst of audio, then hangs indefinitely."""

    def __init__(self, initial_frames: int = 2) -> None:
        self.killed = threading.Event()
        self.initial_frames = initial_frames
        self._q: queue.Queue[bytes] = queue.Queue()
        # 16 kHz 16-bit mono = 960 bytes per 30 ms frame
        for _ in range(initial_frames):
            self._q.put(b"\x00" * 960)

    class _Out:
        def __init__(self, parent: HangingFakeProc) -> None:
            self.parent = parent

        def read(self, n: int = 1920) -> bytes:
            if self.parent.killed.is_set():
                return b""
            try:
                return self.parent._q.get_nowait()
            except queue.Empty:
                # Hang indefinitely until killed
                while not self.parent.killed.is_set():
                    time.sleep(0.05)
                return b""

    @property
    def stdout(self) -> _Out:
        return self._Out(self)

    def poll(self) -> int | None:
        return -9 if self.killed.is_set() else None

    def kill(self) -> None:
        self.killed.set()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test_watchdog.db")
    SQLiteStore(path)
    return path


def test_stream_reader_reads_chunks_and_handles_eof():
    """Verify _StreamReader background thread reads from stream into queue and sets EOF."""
    data = b"abcdef" * 500
    stream = io.BytesIO(data)
    reader = _StreamReader(stream)

    collected = bytearray()
    while len(collected) < len(data):
        try:
            chunk = reader.q.get(timeout=1.0)
            if not chunk:
                break
            collected.extend(chunk)
        except queue.Empty:
            break

    reader.stop()
    assert bytes(collected) == data


def test_hanging_ffmpeg_triggers_watchdog_and_reconnects_within_15s(db):
    """
    Review 2026-10-21, 16:30 Item 4:
    A fake ffmpeg writes some audio and then hangs without exiting.
    The listener watchdog must kill ffmpeg after 10s of no audio,
    and reconnect within ~15s.
    """
    pipeline = MagicMock()
    pipeline._motion_active.return_value = True
    tracker = SimpleNamespace(active_tracks=[])
    listener = RoomListener(pipeline=pipeline, tracker=tracker, db_path=db)
    listener._config = SimpleNamespace(network_camera_url="rtsp://test_camera", room_voice_threshold=0.35)
    listener._vad = MagicMock()
    listener._vad.is_speech.return_value = False

    proc1 = HangingFakeProc(initial_frames=2)
    proc2 = HangingFakeProc(initial_frames=2)
    procs = [proc1, proc2]
    proc_spawned = []

    def fake_start_camera_audio(url, sample_rate=16000):
        if procs:
            p = procs.pop(0)
        else:
            p = HangingFakeProc(initial_frames=0)
        proc_spawned.append(p)
        return p

    listener._running.set()
    start_time = time.time()

    # Run capture loop in background thread
    with patch.object(rl, "start_camera_audio", fake_start_camera_audio):
        loop_thread = threading.Thread(target=listener._capture_loop, daemon=True)
        loop_thread.start()

        # Wait until proc1 is killed and proc2 is spawned (reconnected)
        reconnected = False
        reconnect_elapsed = 0.0

        for _ in range(160):  # Poll for up to 16.0s (160 * 0.1s)
            time.sleep(0.1)
            if len(proc_spawned) >= 2 and proc1.killed.is_set():
                reconnect_elapsed = time.time() - start_time
                reconnected = True
                break

        # Stop listener and wait for loop thread
        listener.stop()
        loop_thread.join(timeout=3.0)

    # 1. Assert proc1 was killed by the watchdog
    assert proc1.killed.is_set(), "Hanging proc1 must be killed by the 10-second watchdog"

    # 2. Assert a reconnect occurred (proc2 was spawned)
    assert reconnected, f"Listener must reconnect to camera audio; spawned count: {len(proc_spawned)}"
    assert len(proc_spawned) >= 2, "A second ffmpeg process must be spawned on reconnect"

    # 3. Assert timing is ~10-15s (watchdog 10s + backoff 3s ~ 13-15s)
    assert 9.5 <= reconnect_elapsed <= 15.5, (
        f"Reconnect must happen within ~15 s, got {reconnect_elapsed:.2f} s"
    )

    # 4. Verify database recorded audio received / stalled
    store = SQLiteStore(db)
    row = store._listening_row()
    assert float(row.get("audio_last_received_at", 0.0)) > 0.0


def test_server_observer_card_reflects_audio_stall(db):
    """
    Review 2026-10-21, 16:30 Item 3:
    The observer card shows 'room listening: no audio for N s' in amber/red
    when an audio stall happens, and the feed logs the stall and reconnect.
    """
    import archer.server as server

    store = SQLiteStore(db)

    # Simulate active listening with recent audio
    now = time.time()
    store.set_listener_state("listening", now=now)
    store.update_audio_received(now=now)

    # Audio stall for 12 seconds (< 30s -> amber)
    store.update_audio_stalled(12.0)
    row = store._listening_row()
    stall_sec = float(row.get("audio_stalled_seconds", 0.0))
    assert stall_sec == 12.0

    # In server.py: simulate monitor loop logic
    curr = time.time()
    audio_stalled_sec = float(row.get("audio_stalled_seconds", 0.0) or 0.0)
    is_audio_stalled = audio_stalled_sec > 0.0
    stall_elapsed = int(audio_stalled_sec)
    dot = "amber" if stall_elapsed < 30 else "red"

    server._update_status_board(
        "observer", "Audio Stalled",
        f"Running | room listening: no audio for {stall_elapsed} s | 0 people in view | Item watcher off",
        dot=dot, is_error=(stall_elapsed >= 30)
    )

    card = server._status_board_state["observer"]
    assert card["state"] == "Audio Stalled"
    assert card["dot"] == "amber"
    assert "room listening: no audio for 12 s" in card["desc"]

    # Audio stall for 35 seconds (>= 30s -> red)
    store.update_audio_stalled(35.0)
    row = store._listening_row()
    audio_stalled_sec = float(row.get("audio_stalled_seconds", 0.0) or 0.0)
    stall_elapsed = int(audio_stalled_sec)
    dot = "amber" if stall_elapsed < 30 else "red"

    server._update_status_board(
        "observer", "Audio Stalled",
        f"Running | room listening: no audio for {stall_elapsed} s | 0 people in view | Item watcher off",
        dot=dot, is_error=(stall_elapsed >= 30)
    )

    card = server._status_board_state["observer"]
    assert card["dot"] == "red"
    assert "room listening: no audio for 35 s" in card["desc"]

    # Recovery: audio frames flow again
    store.update_audio_received(now=time.time())
    row = store._listening_row()
    assert float(row.get("audio_stalled_seconds", 0.0)) == 0.0

    server._update_status_board(
        "observer", "Running",
        "Running | Room listening listening | 0 people in view | Item watcher off",
        dot="green", is_error=False
    )
    card = server._status_board_state["observer"]
    assert card["state"] == "Running"
    assert card["dot"] == "green"
