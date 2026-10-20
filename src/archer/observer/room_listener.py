"""
ARCHER Phase 2c: room listening ("second brain").

Turns speech heard by the room camera's built-in mic into text, while someone
is in the room. Runs as threads inside the observer service.

Rules (spec 5c and its decisions block):
- Audio stays in memory only. No audio file is ever written.
- The words of a transcript never go into a log file.
- Listens only while someone is in the room: a person tracked by following
  people, or the camera's own person alert plus its tail; since 2026-10-20,
  until 2 hours after someone was last seen (the detector misses Col lying
  still on the couch).
- Uses its own audio-only connection to the camera's sub-stream; following
  people's video connection is untouched.
- Faster-Whisper base.en on the CPU, from ARCHER's own model folder.
- Whose speech is kept (Col, 2026-10-15): Col's voice always; another voice
  only while the camera sees someone besides Col. Otherwise it's taken to be
  a TV, a video or a speakerphone, and nothing is saved. Since 2026-10-20,
  another voice also needs the PC to be quiet: Col mutes the TV to talk with
  someone, and the people tracker's phantoms let TV speech in otherwise.
- TV check (Col, 2026-10-20): videos play from the PC, so a line that would
  be kept but repeats words the PC was playing at that moment is the TV and
  isn't saved, whoever's voice it sounds like (see pc_playback.py). While
  nothing is playing on the PC, a lower voice score counts as Col.
- ARCHER's own voice is marked, not dropped.
- Spoken commands ("all systems go", "ARCHER, stop listening",
  "ARCHER, forget that") count from speech that is kept, or from any voice
  when the PC wasn't playing those words (2026-10-20: short phrases score
  low on the voice check, so "all systems go" was being dropped).
- While paused, nothing is transcribed at all.

Built by Antigravity 2026-10-15; reworked by Claude 2026-10-15 after review;
TV check added by Claude 2026-10-20.
"""

from __future__ import annotations

import collections
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import webrtcvad
from loguru import logger

from archer.config import get_config
from archer.memory.sqlite_store import (
    SQLiteStore,
    format_room_transcript_timestamp,
    get_sqlite_store,
)
from archer.observer.pc_playback import PCPlayback, words_match

if TYPE_CHECKING:
    from archer.observer.person_tracker import PersonTracker
    from archer.observer.pipeline import ObserverPipeline

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
WHISPER_MODEL_DIR = _PROJECT_ROOT / "data" / "models" / "whisper" / "base.en"
VOICE_MODEL_DIR = _PROJECT_ROOT / "data" / "models" / "speechbrain"
FFMPEG_EXE = r"C:\Tools\ffmpeg\bin\ffmpeg.exe"

# Measured camera audio delay relative to real time (read-aloud test, 2026-10-15).
CAMERA_AUDIO_LAG_SECONDS = 1.18

# Cooldown between "all systems go" launches.
_LAUNCH_COOLDOWN_SECONDS = 30.0

# How often the listener re-reads the pause setting and room presence.
_PAUSE_CHECK_INTERVAL_S = 1.0
_PRESENCE_CHECK_INTERVAL_S = 0.5
# How often the listener reports its state to the database (heartbeat).
_STATE_HEARTBEAT_S = 10.0
# How often Col's room voice profile is re-read (picks up a new enrollment).
_PROFILE_RELOAD_S = 60.0

# An unidentified track counts as a person only if its box is at least this
# big (pixels on the 640x480 sub-stream). The coats on the hooks by the front
# door are detected as a ~50x90 "person" for hours at a time (2026-10-16/17
# logs); a person sitting or lying on the couch is 20,000+.
_MIN_PERSON_AREA = 8000
# ...and, to count as "someone besides Col", has been in view this long.
_MIN_OTHER_PERSON_SECONDS = 10.0
# A box that lies mostly (this share of it) inside another person's box is the
# same person seen twice: Col on the couch is often tracked as two overlapping
# boxes, which made TV speech count as "another voice" (2026-10-20 logs).
_SAME_PERSON_INSIDE_SHARE = 0.6


def _box_area(box) -> float:
    return float(box[2] * box[3]) if box and len(box) >= 4 else 0.0


def _share_inside(box, other) -> float:
    """How much of `box` lies inside `other` (0 to 1); boxes are [x, y, w, h]."""
    area = _box_area(box)
    if area <= 0 or _box_area(other) <= 0:
        return 0.0
    w = min(box[0] + box[2], other[0] + other[2]) - max(box[0], other[0])
    h = min(box[1] + box[3], other[1] + other[3]) - max(box[1], other[1])
    return max(0.0, w) * max(0.0, h) / area


def _drop_doubles(tracks: list) -> list:
    """Leave out a track whose box lies mostly inside another person's box (same person)."""
    def key(t):
        return (not getattr(t, "assigned_identity", None), -_box_area(getattr(t, "box", None)))

    kept: list = []
    for t in sorted(tracks, key=key):  # identified people first, then bigger boxes
        box = getattr(t, "box", None)
        if box and any(
            _share_inside(box, getattr(k, "box", None)) >= _SAME_PERSON_INSIDE_SHARE for k in kept
        ):
            continue
        kept.append(t)
    return kept

_ALL_SYSTEMS_GO_REGEX = re.compile(
    r"\b(?:all|whole)\s+systems?\s+(?:go|are\s+go|goal)\b", re.IGNORECASE
)
_NEAR_MISSES_REGEX = re.compile(
    r"\b(?:all\s+things\s+go|all\s+good\s+systems|systems\s+are\s+going|go\s+to\s+all\s+systems|is\s+the\s+system\s+go)\b",
    re.IGNORECASE,
)
_PAUSE_VOICE_REGEX = re.compile(r"\barcher\s+(?:stop|pause)\s+listening\b", re.IGNORECASE)
_FORGET_VOICE_REGEX = re.compile(r"\barcher\s+forget\s+that\b", re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def _has_command(text: str) -> bool:
    """True if the text holds one of the spoken commands."""
    clean = _clean(text)
    return bool(
        clean
        and (_PAUSE_VOICE_REGEX.search(clean) or _FORGET_VOICE_REGEX.search(clean) or is_all_systems_go(clean))
    )


def is_all_systems_go(text: str) -> bool:
    """True if the text contains "all systems go" or a close variant, but not a near-miss."""
    clean = _clean(text)
    if not clean or _NEAR_MISSES_REGEX.search(clean):
        return False
    return bool(_ALL_SYSTEMS_GO_REGEX.search(clean))


class RoomVoiceCheck:
    """
    Compares a stretch of room speech with Col's voice profile, using ARCHER's
    existing SpeechBrain ECAPA voice model (data/models/speechbrain), loaded
    from local files only. The profile is enrolled through the camera mic with
    scripts/room_voice.py and stored in the room_voice_profile table.
    """

    def __init__(self, store: SQLiteStore, model_dir: Path = VOICE_MODEL_DIR) -> None:
        self._store = store
        self._model_dir = Path(model_dir)
        self._model: Any = None
        self._model_failed = False
        self._lock = threading.Lock()
        self._profile: np.ndarray | None = None
        self._profile_loaded_at = 0.0

    def _ensure_model(self) -> Any:
        if self._model is not None or self._model_failed:
            return self._model
        with self._lock:
            if self._model is not None or self._model_failed:
                return self._model
            try:
                self._model = load_voice_model(self._model_dir)
                logger.info("Room voice check: voice model loaded (local files only).")
            except Exception as e:
                self._model_failed = True
                logger.error(f"Room voice check: voice model failed to load ({type(e).__name__}: {e}).")
            return self._model

    def profile(self) -> np.ndarray | None:
        now = time.time()
        if now - self._profile_loaded_at >= _PROFILE_RELOAD_S:
            self._profile_loaded_at = now
            emb = self._store.get_room_voice_profile("Col")
            self._profile = np.asarray(emb, dtype=np.float32) if emb else None
        return self._profile

    def score(self, audio: np.ndarray) -> float | None:
        """Cosine similarity with Col's profile, or None if there's no profile or model."""
        profile = self.profile()
        if profile is None:
            return None
        model = self._ensure_model()
        if model is None:
            return None
        emb = embed_voice(model, audio)
        denom = float(np.linalg.norm(emb) * np.linalg.norm(profile))
        return float(np.dot(emb, profile) / denom) if denom > 0 else 0.0


def load_voice_model(model_dir: Path = VOICE_MODEL_DIR) -> Any:
    """Load SpeechBrain's ECAPA voice model from the local folder, never the network."""
    import torch
    import torchaudio

    # torchaudio >= 2.10 removed list_audio_backends, which speechbrain 1.0.2 calls
    # on import (same patch as voice/auth.py).
    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]

    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    torch.set_num_threads(2)  # the observer's CPU budget
    d = str(Path(model_dir).resolve())
    # source == savedir with the files already there: speechbrain uses them
    # as they are (no copy, no link, no download).
    return EncoderClassifier.from_hparams(
        source=d,
        savedir=d,
        overrides={"pretrained_path": d},
        local_strategy=LocalStrategy.NO_LINK,
        run_opts={"device": "cpu"},
    )


def embed_voice(model: Any, audio: np.ndarray) -> np.ndarray:
    """192-number voice embedding for 16 kHz mono float audio."""
    import torch

    with torch.no_grad():
        tensor = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
        return model.encode_batch(tensor).squeeze().cpu().numpy().astype(np.float32)


def start_camera_audio(url: str, sample_rate: int = 16000) -> subprocess.Popen:
    """Audio-only ffmpeg connection to the camera stream: 16 kHz mono 16-bit PCM on stdout."""
    cmd = [
        FFMPEG_EXE,
        "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        "-f", "s16le",
        "pipe:1",
    ]
    # stderr is discarded on purpose: ffmpeg's error text can contain the URL.
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


class RoomListener:
    """Room listening: capture thread (audio, presence, speech detection) + transcription worker."""

    def __init__(
        self,
        pipeline: ObserverPipeline | None = None,
        tracker: PersonTracker | None = None,
        db_path: str | None = None,
        model_path: str | None = None,
        voice_check: RoomVoiceCheck | None = None,
        playback: PCPlayback | None = None,
    ) -> None:
        self._config = get_config()
        self._store = SQLiteStore(db_path) if db_path else get_sqlite_store()
        self._pipeline = pipeline
        self._tracker = tracker
        self._model_path = str(model_path or WHISPER_MODEL_DIR)
        self._model = None
        self._model_lock = threading.Lock()
        self._voice = voice_check if voice_check is not None else RoomVoiceCheck(self._store)
        if playback is None and getattr(self._config, "room_tv_check", True):
            playback = PCPlayback()
        self._playback = playback  # None: TV check switched off

        # Speech detection: webrtcvad on 30 ms frames at 16 kHz (960 bytes each).
        self._vad = webrtcvad.Vad(2)
        self._sample_rate = 16000
        self._frame_bytes = int(self._sample_rate * 0.03) * 2

        self._running = threading.Event()
        self._stream_proc: subprocess.Popen | None = None
        self._capture_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._audio_queue: collections.deque = collections.deque()
        self._queue_condition = threading.Condition()

        self._last_launch_time = 0.0
        self._state = ""
        self._state_written_at = 0.0
        self._paused_cache = (0.0, False)
        self._presence_cache = (0.0, False)
        self._last_seen = time.time()  # see is_room_active: occupied until shown otherwise
        self._dropped_count = 0
        self._tv_dropped_count = 0
        self._tv_error_logged = False
        self._saved_count = 0

    def set_pipeline_and_tracker(self, pipeline: ObserverPipeline, tracker: PersonTracker) -> None:
        self._pipeline = pipeline
        self._tracker = tracker

    # --- Presence, pause and state -----------------------------------------

    def _active_tracks(self) -> list:
        if self._tracker is None:
            return []
        try:
            return list(self._tracker.active_tracks)
        except Exception:
            return []

    def _people_tracks(self, min_seconds: float = 0.0) -> list:
        """
        Tracks that are really people: anyone identified (a face was seen), or an
        unidentified track big enough to be a person and in view at least
        `min_seconds`. Leaves out phantom detections such as the coats by the
        door, and a second box on the same person.
        """
        people = []
        for t in self._active_tracks():
            if getattr(t, "assigned_identity", None):
                people.append(t)
                continue
            box = getattr(t, "box", None) or []
            area = box[2] * box[3] if len(box) >= 4 else 0
            if area >= _MIN_PERSON_AREA and getattr(t, "duration", 0.0) >= min_seconds:
                people.append(t)
        return _drop_doubles(people)

    def someone_in_view(self) -> bool:
        """The camera sees someone now: a tracked person, or its person alert plus its tail."""
        if self._people_tracks():
            return True
        if self._pipeline is not None:
            try:
                if hasattr(self._pipeline, "_motion_active") and self._pipeline._motion_active():
                    return True
            except Exception:
                pass
        return False

    def is_room_active(self) -> bool:
        """
        Someone is (probably) in the room: seen now, or seen within the last
        `room_linger_minutes` (2 hours). The people detector often misses Col
        lying still on the couch (2026-10-20: nothing detected for 7+ minutes
        while he lay there, so "all systems go" went unheard). Listening to a
        room that has emptied costs little: the voice rule and the TV check
        drop TV speech. Right after the observer starts, nobody knows yet, so
        the room counts as occupied until the linger runs out.
        """
        now = time.time()
        if self.someone_in_view():
            self._last_seen = now
            return True
        linger = float(getattr(self._config, "room_linger_minutes", 120.0)) * 60.0
        return now - self._last_seen < linger

    def _room_active_cached(self, now: float) -> bool:
        at, value = self._presence_cache
        if now - at >= _PRESENCE_CHECK_INTERVAL_S:
            value = self.is_room_active()
            self._presence_cache = (now, value)
        return value

    def is_paused(self) -> bool:
        try:
            return self._store.is_listening_paused()
        except Exception:
            return False

    def _paused_cached(self, now: float) -> bool:
        at, value = self._paused_cache
        if now - at >= _PAUSE_CHECK_INTERVAL_S:
            value = self.is_paused()
            self._paused_cache = (now, value)
        return value

    def _report_state(self, state: str, now: float) -> None:
        """Write the listener's state for ARCHER's page: on every change, and as a heartbeat."""
        if state != self._state or now - self._state_written_at >= _STATE_HEARTBEAT_S:
            self._state = state
            self._state_written_at = now
            try:
                self._store.set_listener_state(state, now)
            except Exception:
                pass

    def _get_current_people_in_view(self) -> list[str]:
        """Names of the people in view now; unidentified people are listed as such. Empty if nobody."""
        people: list[str] = []
        for track in self._people_tracks():
            name = getattr(track, "assigned_identity", None) or "unidentified person"
            if name not in people:
                people.append(name)
        return people

    def _someone_besides_col_in_view(self) -> bool:
        """
        True when the camera sees someone other than Col: anyone identified as
        someone else, or real unidentified people beyond Col (one if Col is
        recognized, two if he isn't). A single unidentified person is most
        likely Col before his face is recognized, so it doesn't count.
        Phantom detections (see _people_tracks) never count.
        """
        tracks = self._people_tracks(min_seconds=_MIN_OTHER_PERSON_SECONDS)
        names = [getattr(t, "assigned_identity", None) for t in tracks]
        if any(n not in (None, "", "Col") for n in names):
            return True
        unidentified = sum(1 for n in names if not n)
        col_seen = any(n == "Col" for n in self._people_names())
        return unidentified >= (1 if col_seen else 2)

    def _people_names(self) -> list:
        return [getattr(t, "assigned_identity", None) for t in self._people_tracks()]

    def _get_current_stay_id(self) -> str | None:
        for track in self._people_tracks():
            if getattr(track, "stay_id", None):
                return track.stay_id
        return None

    # --- Start / stop ----------------------------------------------------

    def start(self) -> bool:
        if self._running.is_set():
            return True
        if not self._config.network_camera_url:
            logger.warning("RoomListener: no network camera configured; room listening is off.")
            return False
        self._running.set()
        self._worker_thread = threading.Thread(
            target=self._transcription_worker, name="RoomListener-Worker", daemon=True
        )
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="RoomListener-Capture", daemon=True
        )
        self._worker_thread.start()
        self._capture_thread.start()
        if self._playback is not None:
            self._playback.start()
        logger.info("RoomListener started (camera mic, audio-only connection).")
        return True

    def stop(self) -> None:
        self._running.clear()
        with self._queue_condition:
            self._queue_condition.notify_all()
        self._stop_stream()
        if self._playback is not None:
            self._playback.stop()
        for th in (self._capture_thread, self._worker_thread):
            if th and th.is_alive():
                th.join(timeout=3.0)
        try:
            self._store.set_listener_state("off")
        except Exception:
            pass
        logger.info("RoomListener stopped.")

    def _stop_stream(self) -> None:
        proc, self._stream_proc = self._stream_proc, None
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass

    # --- Capture ------------------------------------------------------------

    def _capture_loop(self) -> None:
        """Read camera audio, gate on presence and pause, cut speech into stretches. Memory only."""
        url = self._config.network_camera_url
        backoff = 0.0
        started_at = 0.0

        pre_roll: collections.deque = collections.deque(maxlen=16)  # ~0.5 s before speech starts
        speech: list[bytes] = []
        in_speech = False
        silence_frames = 0
        speech_start_ts = 0.0
        max_silence_frames = 36   # ~1.1 s of silence ends a stretch
        max_stretch_frames = 500  # ~15 s at most per stretch
        min_stretch_frames = 16   # ~0.5 s at least

        while self._running.is_set():
            if self._stream_proc is None or self._stream_proc.poll() is not None:
                if self._stream_proc is not None:
                    code = self._stream_proc.poll()
                    ran_for = time.time() - started_at
                    self._stream_proc = None
                    backoff = 3.0 if ran_for >= 60.0 else min(max(backoff * 2, 3.0), 60.0)
                    logger.warning(
                        f"RoomListener: camera audio stream ended (exit code {code}); "
                        f"reconnecting in {backoff:.0f} s."
                    )
                    self._report_state("off", time.time())
                    if self._sleep_while_running(backoff):
                        break
                try:
                    self._stream_proc = start_camera_audio(url, self._sample_rate)
                    started_at = time.time()
                except Exception as e:
                    backoff = min(max(backoff * 2, 3.0), 60.0)
                    logger.error(f"RoomListener: couldn't start ffmpeg ({type(e).__name__}); retrying in {backoff:.0f} s.")
                    if self._sleep_while_running(backoff):
                        break
                    continue

            try:
                frame = self._stream_proc.stdout.read(self._frame_bytes)
            except Exception:
                frame = b""
            if not frame or len(frame) < self._frame_bytes:
                continue  # the poll() above notices if ffmpeg ended

            now = time.time()
            if not self._room_active_cached(now) or self._paused_cached(now):
                state = "paused" if self._paused_cached(now) else "empty"
                self._report_state(state, now)
                pre_roll.clear()
                speech = []
                in_speech = False
                silence_frames = 0
                continue
            self._report_state("listening", now)

            try:
                is_speech = self._vad.is_speech(frame, self._sample_rate)
            except Exception:
                is_speech = False

            if is_speech:
                if not in_speech:
                    in_speech = True
                    speech_start_ts = now - len(pre_roll) * 0.03
                    speech = list(pre_roll)
                speech.append(frame)
                silence_frames = 0
            elif in_speech:
                speech.append(frame)
                silence_frames += 1
            else:
                pre_roll.append(frame)

            if in_speech and (silence_frames >= max_silence_frames or len(speech) >= max_stretch_frames):
                if len(speech) >= min_stretch_frames:
                    audio = np.frombuffer(b"".join(speech), dtype=np.int16).astype(np.float32) / 32768.0
                    self._enqueue(
                        audio,
                        speech_start_ts,
                        now,
                        self._get_current_people_in_view(),
                        self._get_current_stay_id(),
                        self._someone_besides_col_in_view(),
                    )
                speech = []
                in_speech = False
                silence_frames = 0

        self._stop_stream()

    def _sleep_while_running(self, seconds: float) -> bool:
        """Sleep up to `seconds`; True if the listener was stopped meanwhile."""
        end = time.time() + seconds
        while time.time() < end:
            if not self._running.is_set():
                return True
            time.sleep(0.2)
        return not self._running.is_set()

    def _enqueue(self, audio, start_ts, end_ts, people, stay_id, someone_else) -> None:
        with self._queue_condition:
            if len(self._audio_queue) >= 20:
                self._audio_queue.popleft()
                logger.warning("RoomListener: transcription fell behind; one stretch of speech was skipped.")
            self._audio_queue.append((audio, start_ts, end_ts, people, stay_id, someone_else))
            self._queue_condition.notify()

    # --- Transcription --------------------------------------------------------

    def _ensure_model_loaded(self) -> Any:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                logger.info("RoomListener: loading Faster-Whisper base.en on the CPU (local files only).")
                self._model = WhisperModel(
                    self._model_path,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=2,
                    local_files_only=True,
                )
            return self._model

    def _transcription_worker(self) -> None:
        while self._running.is_set():
            with self._queue_condition:
                while not self._audio_queue and self._running.is_set():
                    self._queue_condition.wait(timeout=1.0)
                if not self._running.is_set():
                    break
                item = self._audio_queue.popleft()
            try:
                self._process_speech_segment(*item)
            except Exception as e:
                logger.error(f"RoomListener: a stretch of speech couldn't be processed ({type(e).__name__}).")

    def _transcribe(self, audio: np.ndarray) -> str:
        model = self._ensure_model_loaded()
        segments, _info = model.transcribe(audio, beam_size=1, language="en", vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()

    def _process_speech_segment(
        self,
        audio: np.ndarray,
        start_ts: float,
        end_ts: float,
        people: list[str],
        stay_id: str | None,
        someone_besides_col: bool | None = None,
    ) -> int | None:
        """
        Transcribe one stretch, decide whether to keep it, save it, then act on
        any spoken command in it. Returns the saved row id, or None if nothing
        was saved.
        """
        if self.is_paused():
            return None  # paused after this stretch was captured: don't transcribe it

        text = self._transcribe(audio)
        if not text:
            return None

        if someone_besides_col is None:
            someone_besides_col = self._someone_besides_col_in_view()

        # 1. ARCHER's own voice: marked, kept, never a command.
        is_archer = self._store.check_if_archer_speech(
            start_time=start_ts, end_time=end_ts, text=text, lag_seconds=CAMERA_AUDIO_LAG_SECONDS
        )

        # 2. Whose voice: Col's is always kept; another voice only while the
        #    camera sees someone besides Col and the PC isn't playing.
        voice, score = "archer", None
        if not is_archer:
            score = self._voice_score(audio)
            playing = self._pc_playing(start_ts, end_ts)
            if score is None:
                voice = "unchecked"  # no profile enrolled yet (or the model failed)
            elif score >= self._voice_threshold(playing):
                voice = "col"
            elif someone_besides_col and playing is not True:
                voice = "other"
            else:
                self._dropped_count += 1
                why = "the PC was playing" if someone_besides_col else "nobody else in view"
                logger.debug(f"RoomListener: speech not saved (not Col's voice, {why}; score {score:.2f}).")
                if self._dropped_count % 25 == 1:
                    logger.info(
                        f"RoomListener: {self._dropped_count} stretches of speech not saved so far "
                        "(not Col's voice: TV, video or speakerphone)."
                    )
                self._commands_from_any_voice(text, start_ts, end_ts, playing)
                return None

        # 3. The TV: a line that would be kept but repeats words the PC was
        #    playing at that moment is the TV (videos play from the PC). Only
        #    checked for lines that would be kept, to save the CPU.
        tv_match = None
        if not is_archer:
            tv_match = self._tv_match(text, start_ts, end_ts)
            if tv_match is not None and tv_match >= self._config.room_tv_match_threshold:
                self._tv_dropped_count += 1
                logger.debug(f"RoomListener: speech not saved (the PC was playing the same words; {tv_match:.2f}).")
                if self._tv_dropped_count % 25 == 1:
                    logger.info(
                        f"RoomListener: {self._tv_dropped_count} lines not saved so far because the PC "
                        "was playing the same words (TV or video)."
                    )
                return None

        # 4. Not inside a "forget that" window (e.g. still queued when it was asked).
        if self._store.is_in_forgotten_window(start_ts, end_ts):
            return None

        row_id = self._store.insert_room_transcript(
            transcript=text,
            start_time=start_ts,
            end_time=end_ts,
            start_datetime=format_room_transcript_timestamp(start_ts),
            end_datetime=format_room_transcript_timestamp(end_ts),
            source="room_camera",
            people_in_view=people,
            stay_id=stay_id,
            is_archer=is_archer,
            voice=voice,
            voice_score=score,
        )
        self._saved_count += 1
        logger.info(
            f"RoomListener: line saved (#{row_id}, {len(text.split())} words, voice={voice}"
            + (f", score {score:.2f}" if score is not None else "")
            + (f", tv {tv_match:.2f}" if tv_match is not None else "")
            + ")."
        )

        # 5. Spoken commands, after the line is saved (so "forget that" removes itself too).
        if not is_archer:
            self._handle_voice_commands(text, start_ts, end_ts)
        return row_id

    def _pc_playing(self, start_ts: float, end_ts: float) -> bool | None:
        """Whether the PC was playing anything audible around this line; None if unknown."""
        if self._playback is None:
            return None
        try:
            return self._playback.playing_during(start_ts, end_ts, CAMERA_AUDIO_LAG_SECONDS)
        except Exception:
            return None

    def _voice_threshold(self, playing: bool | None) -> float:
        """
        The voice score that counts as Col: lower while nothing is playing on
        the PC, when there's no TV to mistake for him (Col's short remarks
        score lower than long ones). The usual one otherwise, or if unsure.
        """
        normal = self._config.room_voice_threshold
        if playing is False:
            return min(normal, getattr(self._config, "room_voice_threshold_quiet", normal))
        return normal

    def _commands_from_any_voice(self, text: str, start_ts: float, end_ts: float, playing: bool | None) -> None:
        """
        A spoken command in speech that isn't kept still counts, as long as the
        PC wasn't playing those words: short phrases like "all systems go"
        score low on the voice check. If it's unknown whether the PC was
        playing, it doesn't count (it might be the TV).
        """
        if not _has_command(text):
            return
        if playing is None:
            logger.info(
                "RoomListener: a spoken command was heard but not acted on: the voice didn't match Col's "
                "and it's unknown whether the PC was playing it."
            )
            return
        try:
            if playing:
                played = self._playback.played_audio_for(start_ts, end_ts, CAMERA_AUDIO_LAG_SECONDS)
                if played is not None and _has_command(self._transcribe(played)):
                    logger.info("RoomListener: a spoken command came from the PC (TV or video); ignored.")
                    return
        except Exception as e:
            logger.error(f"RoomListener: couldn't check a spoken command against the PC ({type(e).__name__}); ignored.")
            return
        logger.info("RoomListener: spoken command heard (voice not matched to Col; the PC didn't play it).")
        self._handle_voice_commands(text, start_ts, end_ts)

    def _tv_match(self, text: str, start_ts: float, end_ts: float) -> float | None:
        """
        Share of the line's words that the PC was also playing then
        (pc_playback.py); None if it can't be judged: too few words, the
        playback wasn't recorded, or nothing audible was playing.
        """
        if self._playback is None:
            return None
        try:
            if words_match(text, "") is None:
                return None  # too few words to judge; skip transcribing the PC
            played = self._playback.played_audio_for(start_ts, end_ts, CAMERA_AUDIO_LAG_SECONDS)
            if played is None:
                return None
            found = words_match(text, self._transcribe(played))
            return None if found is None else found[0]
        except Exception as e:
            if not self._tv_error_logged:
                self._tv_error_logged = True
                logger.error(f"RoomListener: TV check failed ({type(e).__name__}); skipping it.")
            return None

    def _voice_score(self, audio: np.ndarray) -> float | None:
        try:
            return self._voice.score(audio)
        except Exception as e:
            logger.error(f"RoomListener: voice check failed ({type(e).__name__}); keeping the line unchecked.")
            return None

    def _handle_voice_commands(self, text: str, start_ts: float, end_ts: float | None = None) -> None:
        clean = _clean(text)
        end_ts = end_ts if end_ts is not None else start_ts

        if _PAUSE_VOICE_REGEX.search(clean):
            logger.info("RoomListener: 'ARCHER, stop listening' heard; pausing for 1 hour.")
            self._store.set_listening_pause(duration_seconds=3600)
            self._paused_cache = (0.0, True)
            return

        if _FORGET_VOICE_REGEX.search(clean):
            # The 2 minutes before the request, plus the request itself.
            deleted = self._store.forget_recent_room_transcripts(
                seconds=120.0 + max(0.0, end_ts - start_ts), now=end_ts
            )
            logger.info(f"RoomListener: 'ARCHER, forget that' heard; {deleted} lines deleted.")
            return

        if is_all_systems_go(clean):
            now = time.time()
            if now - self._last_launch_time >= _LAUNCH_COOLDOWN_SECONDS:
                self._last_launch_time = now
                logger.info("RoomListener: 'all systems go' heard; asking the launch task to start ARCHER.")
                self._store.request_launch(now)
                self._trigger_all_systems_go()

    def _trigger_all_systems_go(self) -> None:
        """Run the scheduled task that starts ARCHER in Col's own session (see scripts/)."""
        try:
            proc = subprocess.run(
                ["schtasks.exe", "/run", "/tn", "ArcherLaunchOnVoice"],
                capture_output=True,
                timeout=10,
            )
            if proc.returncode != 0:
                logger.warning(
                    "RoomListener: the launch task didn't run (is ArcherLaunchOnVoice installed? "
                    "See scripts/setup_archer_launch_task.ps1)."
                )
        except Exception as e:
            logger.error(f"RoomListener: couldn't run the launch task ({type(e).__name__}).")
