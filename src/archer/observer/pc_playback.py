"""
ARCHER Phase 2c: what the PC is playing, to recognise TV speech in the room.

Videos play from Col's PC with the TV as its screen (Col, 2026-10-20). When
a room line would be kept, the room listener also transcribes what the PC
played around that moment. If the line repeats those words, it's the TV (or
the far end of a call) and isn't saved, however much the voice sounds like
Col. The voice check alone couldn't tell one TV narrator from Col: 0.62,
against Col's 0.55 to 0.68 (TV test, 2026-10-20). This is the same idea as
ARCHER's own-voice check (SQLiteStore.check_if_archer_speech).

Matching loudness over time was tried first and failed live (2026-10-20,
11:05 test: TV stretches scored no higher than Col's). The two audio streams
can't be lined up to a fraction of a second, and words don't need that.

- Records the default output's playback (WASAPI loopback) through the
  `soundcard` package ARCHER's voice pipeline already uses. Works from the
  observer service's SYSTEM account (scripts/loopback_probe.py).
- Keeps the last 2 minutes of the PC's playback, 16 kHz mono, in memory only.
  Nothing is written anywhere.
- Best-effort: if it can't record, the voice rule decides alone.

Claude, 2026-10-20. Rule 11: no existing project does this locally.
"""

from __future__ import annotations

import collections
import threading
import time
import warnings

import numpy as np
from loguru import logger

_RATE = 48000
OUT_RATE = 16000
_BLOCK_FRAMES = 4800        # each read is 100 ms
_BUFFER_FRAMES = 24000      # Windows' recording buffer: 0.5 s, so a busy moment loses nothing
BLOCK_SECONDS = _BLOCK_FRAMES / _RATE
# Loudness at or above this counts as something audible playing: about
# -50 dBFS (speech in a video measured -45 to -34 in the probe).
AUDIBLE_RMS = 0.003
_DEVICE_CHECK_SECONDS = 30.0
# The PC's playback compared with a room line: from this long before the line
# started to this long after it ended, both after removing the camera's delay.
# Generous, because the two clocks only need to agree to within a second or so.
WINDOW_BEFORE = 2.0
WINDOW_AFTER = 1.5
# A line needs at least this many words, common words aside, to be judged.
MIN_WORDS = 3



def content_words(text: str) -> set[str]:
    """The line's words, common words aside: the same rule as ARCHER's own-voice check."""
    from archer.memory.sqlite_store import SQLiteStore

    return SQLiteStore._content_words(text)


def words_match(line_text: str, played_text: str) -> tuple[float, int] | None:
    """
    (share of the line's words that the PC also played, number of line words),
    or None if the line has too few words to judge. A word counts if it was
    played, or (5+ letters) shares its first 5 letters with one that was: the
    room transcript of a TV is rougher than the PC's own.
    """
    line = content_words(line_text)
    if len(line) < MIN_WORDS:
        return None
    played = content_words(played_text)
    prefixes = {w[:5] for w in played if len(w) >= 5}
    hits = sum(1 for w in line if w in played or (len(w) >= 5 and w[:5] in prefixes))
    return hits / len(line), len(line)


def _to_mono_16k(data) -> np.ndarray:
    block = np.asarray(data, dtype=np.float32)
    if block.ndim == 2:
        block = block.mean(axis=1)
    try:
        from scipy.signal import resample_poly

        return resample_poly(block, 1, 3).astype(np.float32)
    except Exception:
        n = len(block) // 3
        return block[: n * 3].reshape(n, 3).mean(axis=1)


class PCPlayback:
    """The PC's playback for the last couple of minutes, recorded on its own thread."""

    def __init__(self, keep_seconds: float = 120.0) -> None:
        # (end time, 16 kHz audio, loudness) per 100 ms block
        self._blocks: collections.deque[tuple[float, np.ndarray, float]] = collections.deque(
            maxlen=int(keep_seconds / BLOCK_SECONDS)
        )
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._recording = False
        self._device = ""

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def device(self) -> str:
        return self._device

    # --- Recording ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="RoomListener-PCPlayback", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def add_block(self, end_time: float, audio_16k: np.ndarray) -> None:
        """Store one block of 16 kHz playback ending at `end_time` (also used by tests)."""
        audio = np.asarray(audio_16k, dtype=np.float32)
        loudness = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if audio.size else 0.0
        with self._lock:
            self._blocks.append((end_time, audio, loudness))

    def _sleep_while_running(self, seconds: float) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if not self._running.is_set():
                return True
            time.sleep(0.2)
        return not self._running.is_set()

    def _loop(self) -> None:
        # soundcard sets up COM itself when first imported, and fails if this
        # thread already did (it treats "already set up" as an error), so it's
        # imported first. Joining COM afterwards covers a restart on a new
        # thread, when soundcard is already imported (2026-10-20 live test).
        try:
            import soundcard as sc
        except Exception as e:
            logger.warning(
                f"RoomListener: can't record what the PC is playing ({type(e).__name__}: {e}); "
                "the TV check is off."
            )
            return
        try:
            import ctypes

            ctypes.windll.ole32.CoInitializeEx(None, 0)  # join COM's multithreaded apartment
        except Exception:
            pass
        warnings.filterwarnings("once", message="data discontinuity in recording")

        backoff = 0.0
        while self._running.is_set():
            try:
                speaker = sc.default_speaker()
                loopback = sc.get_microphone(id=str(speaker.id), include_loopback=True)
                with loopback.recorder(samplerate=_RATE, blocksize=_BUFFER_FRAMES) as rec:
                    if speaker.name != self._device:
                        logger.info(f"RoomListener: TV check on; following the PC's playback on '{speaker.name}'.")
                    self._device = speaker.name
                    self._recording = True
                    backoff = 0.0
                    next_check = time.time() + _DEVICE_CHECK_SECONDS
                    while self._running.is_set():
                        data = rec.record(numframes=_BLOCK_FRAMES)
                        now = time.time()
                        self.add_block(now, _to_mono_16k(data))
                        if now >= next_check:
                            next_check = now + _DEVICE_CHECK_SECONDS
                            if str(sc.default_speaker().id) != str(speaker.id):
                                logger.info("RoomListener: the PC's sound output changed; following the new one.")
                                break
            except Exception as e:
                self._recording = False
                backoff = min(max(backoff * 2, 5.0), 60.0)
                logger.warning(
                    f"RoomListener: recording the PC's playback stopped ({type(e).__name__}); "
                    f"retrying in {backoff:.0f} s."
                )
                if self._sleep_while_running(backoff):
                    break
            finally:
                self._recording = False

    # --- Looking back --------------------------------------------------------

    def _blocks_between(self, t0: float, t1: float) -> list[tuple[float, np.ndarray, float]]:
        with self._lock:
            return [b for b in self._blocks if b[0] > t0 and b[0] - BLOCK_SECONDS < t1]

    def _window(self, start_ts: float, end_ts: float, lag: float) -> list | None:
        """The blocks around a room line (camera delay removed); None if mostly not recorded."""
        t0 = start_ts - lag - WINDOW_BEFORE
        t1 = end_ts - lag + WINDOW_AFTER
        blocks = self._blocks_between(t0, t1)
        if len(blocks) < 0.8 * (t1 - t0) / BLOCK_SECONDS:
            return None
        return blocks

    def playing_during(self, start_ts: float, end_ts: float, lag: float) -> bool | None:
        """
        Whether the PC was playing anything audible around a room line read
        from the camera between `start_ts` and `end_ts`; None if the playback
        wasn't recorded for most of that time.
        """
        blocks = self._window(start_ts, end_ts, lag)
        if blocks is None:
            return None
        return max(b[2] for b in blocks) >= AUDIBLE_RMS

    def played_audio_for(self, start_ts: float, end_ts: float, lag: float) -> np.ndarray | None:
        """
        The PC's playback (16 kHz) around a room line read from the camera
        between `start_ts` and `end_ts`, after removing the camera's delay
        `lag`. None if the playback wasn't recorded for most of that time, or
        nothing audible was playing.
        """
        blocks = self._window(start_ts, end_ts, lag)
        if blocks is None or max(b[2] for b in blocks) < AUDIBLE_RMS:
            return None
        return np.concatenate([b[1] for b in blocks])
