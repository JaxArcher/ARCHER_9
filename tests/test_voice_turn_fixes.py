"""
Col's 15:47-15:52 session (Claude, 2026-10-20):
- Three of four answers were shown but not spoken: the mic audio queued while
  the filler played was checked for barge-in once the answer started, and the
  filler (model-made, so not in the fixed list) was taken as Col talking.
- "Open YouTube" was heard as "pen YouTube" / "up in YouTube": the first
  syllable came before the VAD decided it was speech.
- "Open YouTube" got "I will open YouTube for you now." with no tool call.
"""

import collections
import queue
import time
from pathlib import Path
from types import SimpleNamespace

from archer.agents.core_agent import _ACTION_PROMISE_RE, CoreAgent
from archer.voice.audio import AudioManager
from archer.voice.pipeline import _OWN_LINE_SECONDS, VoicePipeline

SRC = Path(__file__).resolve().parents[1] / "src" / "archer"


# --- ARCHER's own fillers heard back ------------------------------------------

def pipeline_with_lines(*lines, age=1.0):
    now = time.monotonic()
    return SimpleNamespace(
        _current_speaking_text="It is Tuesday, October 20, 2026, at 3:48 PM.",
        _last_spoken_text="",
        _recent_own_lines=collections.deque([(now - age, line) for line in lines], maxlen=6),
    )


def test_garbled_echo_of_a_contextual_filler_is_ignored():
    state = pipeline_with_lines("Checking the current time for you now.")
    assert VoicePipeline._is_self_echo(state, "taking the current time through now.")


def test_exact_and_partial_filler_echoes_are_ignored():
    state = pipeline_with_lines("Analyzing the visual input now.", "Searching YouTube now.")
    assert VoicePipeline._is_self_echo(state, "analyzing the visual input now.")
    assert VoicePipeline._is_self_echo(state, "YouTube now.")


def test_filler_echo_check_also_applies_while_listening():
    state = pipeline_with_lines("Checking the current time for you now.")
    assert VoicePipeline._is_self_echo(state, "checking the current time now", include_recent_response=False)


def test_old_fillers_no_longer_count():
    state = pipeline_with_lines("Searching YouTube now.", age=_OWN_LINE_SECONDS + 5)
    assert not VoicePipeline._is_self_echo(state, "YouTube now.")


def test_col_interrupting_is_still_heard():
    state = pipeline_with_lines("Checking the current time for you now.")
    for heard in ("Stop.", "Hold on.", "Wait, no, open YouTube instead."):
        assert not VoicePipeline._is_self_echo(state, heard), heard


def test_fillers_and_announcements_are_remembered():
    state = SimpleNamespace(_recent_own_lines=collections.deque(maxlen=6))
    VoicePipeline._remember_own_line(state, "Searching YouTube now.")
    VoicePipeline._remember_own_line(state, "")
    assert [line for _, line in state._recent_own_lines] == ["Searching YouTube now."]
    text = (SRC / "voice" / "pipeline.py").read_text(encoding="utf-8")
    assert text.count("self._remember_own_line(") == 3  # both filler paths and announce()


def test_queued_mic_audio_is_dropped_before_the_answer_is_spoken():
    manager = AudioManager.__new__(AudioManager)
    manager._audio_queue = queue.Queue(maxsize=100)
    for _ in range(7):
        manager._audio_queue.put_nowait(b"x")
    assert manager.drain_input() == 7
    assert manager.drain_input() == 0
    text = (SRC / "voice" / "pipeline.py").read_text(encoding="utf-8")
    start = text.index('drain = getattr(self._audio, "drain_input", None)')
    assert start < text.index('name="SpeakResponse"', start)


def test_listening_keeps_a_pre_roll():
    text = (SRC / "voice" / "pipeline.py").read_text(encoding="utf-8")
    assert "collections.deque(maxlen=15)" in text
    assert "self._speech_buffer.extend(self._listen_preroll)" in text
    assert "self._listen_preroll.clear()  # never ARCHER's own audio" in text


# --- "Open YouTube" done directly ----------------------------------------------

class FakeExecutor:
    def __init__(self, result):
        self.calls = []
        self.result = result

    def execute(self, tool, args):
        self.calls.append((tool, args))
        return self.result


def agent(result):
    a = CoreAgent.__new__(CoreAgent)
    a._tool_executor = FakeExecutor(result)
    return a


def test_open_youtube_opens_it_in_archers_browser():
    a = agent({"result": {"success": True, "title": "YouTube"}})
    assert a._handle_open_site_command("Open YouTube.") == "YouTube is open."
    assert a._tool_executor.calls == [("open_url", {"url": "https://www.youtube.com"})]


def test_separate_window_uses_cols_browser():
    a = agent({"result": {"success": True}})
    assert a._handle_open_site_command("Open Google in a separate window.") == "Google is open in your browser."
    assert a._tool_executor.calls[0][0] == "open_url_in_my_browser"


def test_a_failure_is_reported():
    a = agent({"result": {"success": False, "reason": "Browser not available"}})
    assert a._handle_open_site_command("Pull up Netflix") == "I couldn't open Netflix: Browser not available."


def test_anything_more_goes_to_the_model():
    a = agent({"result": {"success": True}})
    for text in ("Open YouTube and play some music.", "open notepad", "Open my calendar",
                 "What is YouTube?", "pen YouTube."):
        assert a._handle_open_site_command(text) is None, text
    assert a._tool_executor.calls == []


def test_web_addresses():
    a = CoreAgent.__new__(CoreAgent)
    assert a._open_site_target("go to youtube dot com")[0] == "https://youtube.com"
    assert a._open_site_target("Open www.bbc.co.uk/news")[0] == "https://www.bbc.co.uk/news"


# --- A promise without a tool call ----------------------------------------------

def test_promises_are_recognised():
    for reply in ("I will open YouTube for you now.", "Opening YouTube now.", "Okay, adding it.",
                  "Let me pull up YouTube.", "I'm going to open that."):
        assert _ACTION_PROMISE_RE.search(reply), reply


def test_ordinary_replies_are_not_promises():
    for reply in ("Let me know if you need anything else.", "I'm going to need more details.",
                  "It is Tuesday, October 20, 2026, at 3:48 PM.", "Would you like me to open it?",
                  "I'm completely sure.", "I'll take a look."):
        assert not _ACTION_PROMISE_RE.search(reply), reply


class FakeStream:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


def _chunk(content="", tool_calls=None, done=False):
    import json

    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return json.dumps({"message": message, "done": done})


def run_turn(monkeypatch, rounds, tool_result=None):
    """Run _stream_local against scripted model rounds; returns (spoken sentences, payloads, executor)."""
    import archer.agents.core_agent as core

    payloads = []
    scripted = list(rounds)

    def fake_stream(method, url, json, timeout):
        payloads.append(json)
        return FakeStream(scripted.pop(0))

    monkeypatch.setattr(core.httpx, "stream", fake_stream)
    a = core.CoreAgent.__new__(core.CoreAgent)
    a._config = SimpleNamespace(
        ollama_base_url="http://x", ollama_num_ctx=32768, ollama_keep_alive="60m",
        agent_temperature=0.5, core_think=False,
    )
    a.primary_model = "gemma"
    a._history_lock = __import__("threading").Lock()
    a._conversation_history = []
    a._bus = SimpleNamespace(publish=lambda event: None)
    a._tool_executor = FakeExecutor(tool_result or {"result": {"success": True}})
    a._store = SimpleNamespace(log_conversation=lambda **kw: None)
    a._pattern_learner = SimpleNamespace(record_turn_async=lambda *args: None)
    a._maybe_extract_profile_insight = lambda *args: None
    a._publish_tool_screenshot = lambda *args: None
    spoken = list(a._stream_local("Open YouTube.", "system prompt", time.monotonic(), None))
    return spoken, payloads, a._tool_executor


def test_a_promise_without_a_tool_gets_one_more_try(monkeypatch):
    call = [{"function": {"name": "open_url", "arguments": {"url": "https://www.youtube.com"}}}]
    spoken, payloads, executor = run_turn(monkeypatch, [
        [_chunk("I will open YouTube for you now."), _chunk(done=True)],
        [_chunk("Calling it."), _chunk(tool_calls=call), _chunk(done=True)],
        [_chunk("YouTube is open."), _chunk(done=True)],
    ])
    assert executor.calls == [("open_url", {"url": "https://www.youtube.com"})]
    assert spoken == ["I will open YouTube for you now.", "YouTube is open."]  # the quiet round isn't spoken
    # (the payloads share one message list, so look through all of it)
    assert any("didn't call a tool" in str(m.get("content")) for m in payloads[1]["messages"])


def test_still_no_tool_says_so(monkeypatch):
    spoken, payloads, executor = run_turn(monkeypatch, [
        [_chunk("I will set a reminder for you."), _chunk(done=True)],
        [_chunk("NONE"), _chunk(done=True)],
    ])
    assert executor.calls == []
    assert spoken == ["I will set a reminder for you.", "Sorry, I can't actually do that one myself yet."]
    assert len(payloads) == 2


def test_an_ordinary_reply_is_not_asked_again(monkeypatch):
    spoken, payloads, executor = run_turn(monkeypatch, [
        [_chunk("It is 3:48 PM."), _chunk(done=True)],
    ])
    assert spoken == ["It is 3:48 PM."]
    assert len(payloads) == 1


def test_archer_keeps_its_own_cuda_cache():
    text = (SRC / "web_main.py").read_text(encoding="utf-8")
    cache = text.index('os.environ.setdefault("CUDA_CACHE_PATH"')
    assert cache < text.index("from archer.")  # before anything can start CUDA
    assert 'os.environ.setdefault("CUDA_CACHE_MAXSIZE", str(4 * 1024 ** 3))' in text


# --- The listening loop itself (Claude, 2026-10-20, 16:30) -----------------------
# The pre-roll change first moved the end-of-speech check under the wrong
# branch, so every request waited for the 30 s cap ("Max utterance duration
# reached" on every turn of Col's 16:15 session). This drives the real loop.

def drive_listening(vad_results):
    import threading

    from archer.voice.pipeline import VoicePipelineState

    chunks = [bytes([i % 256]) * 960 for i in range(len(vad_results))]
    feed = iter(zip(chunks, vad_results))
    p = VoicePipeline.__new__(VoicePipeline)
    p._running = threading.Event()
    p._running.set()
    p._halted = threading.Event()
    p._wake_ack_playing = threading.Event()
    p._state = VoicePipelineState.LISTENING
    p._heard_speech = False
    p._silence_frames = 0
    p._listen_start = time.monotonic()
    p._speech_buffer = []
    p._listen_preroll = collections.deque(maxlen=15)
    p._pre_buffer = collections.deque(maxlen=33)
    p._NO_SPEECH_TIMEOUT_SECONDS = 60
    current = {}

    def next_chunk(timeout=0.1):
        try:
            chunk, speech = next(feed)
        except StopIteration:
            p._running.clear()
            return None
        current["speech"] = speech
        return chunk

    p._audio = SimpleNamespace(get_audio_chunk=next_chunk, is_playing=False)
    p._halt = SimpleNamespace(process_audio=lambda chunk: None)
    p._wake_word = SimpleNamespace(process_audio=lambda chunk: False, reset=lambda: None)
    p._vad = SimpleNamespace(process_audio=lambda chunk: current["speech"], reset=lambda: None)
    p._bus = SimpleNamespace(publish=lambda event: None)
    p._set_state = lambda state: setattr(p, "_state", state)
    handled = []

    def process():
        handled.append(list(p._speech_buffer))
        p._speech_buffer.clear()
        p._state = VoicePipelineState.PROCESSING

    p._process_utterance = process
    p._pipeline_loop()
    return handled, chunks


def test_speech_ends_after_a_second_of_silence():
    vad = [False] * 20 + [True] * 10 + [False] * 40
    handled, chunks = drive_listening(vad)
    assert len(handled) == 1  # ended by the silence, not the 30 s cap
    audio = handled[0]
    assert audio[:15] == chunks[5:20]  # the 15 chunks heard just before speech
    assert audio[15:25] == chunks[20:30]  # the speech itself
    assert len(audio) == 15 + 10 + 33  # then the silence up to the end


def test_no_speech_means_no_request():
    handled, _ = drive_listening([False] * 60)
    assert handled == []


def test_play_on_youtube_is_done_directly():
    a = agent({"result": {"success": True, "playing": "Beyonce - BLACK PARADE"}})
    assert a._handle_youtube_play_command("Play Beyonce Black Parade on YouTube.") == "Playing Beyonce - BLACK PARADE."
    assert a._tool_executor.calls == [("play_youtube", {"query": "beyonce black parade"})]
    for text in ("play the news", "Play YouTube", "Open YouTube.",
                 "In the YouTube window that you open, could you search for Beyonce Black Parade "
                 "and play the first video that appears?"):
        assert a._handle_youtube_play_command(text) is None, text
    failing = agent({"result": {"success": False, "reason": "no videos found in YouTube's results"}})
    assert failing._handle_youtube_play_command("put on lo-fi music on youtube") == (
        "I couldn't play that on YouTube: no videos found in YouTube's results.")


# --- TV speech and a later wake word (Claude, 2026-10-20, 20:30) -------------------------------
# During the follow-up window the TV said "You can't control my life ..." and
# Col then said "Hey ARCHER"; ARCHER answered the TV.

import numpy as np  # noqa: E402

from archer.voice.pipeline import _after_wake_word  # noqa: E402


def test_wake_word_after_other_speech():
    tv = "You can't control my life. All that people's choice is the pattern. It's way more controlled than I do. Hey Archer!"
    assert _after_wake_word(tv) == ("", True)
    assert _after_wake_word("blah blah. Archer, open YouTube.") == ("open YouTube.", True)
    assert _after_wake_word("Hey Archer, what time is it?") == ("what time is it?", False)
    assert _after_wake_word("What time is it, Archer?") == ("What time is it", False)
    assert _after_wake_word("Hey Archer.") == ("", True)
    assert _after_wake_word("What time is it?") == ("What time is it?", False)


class _FakeAudio:
    def __init__(self, played):
        self.played = played

    def get_loopback_audio(self, start, end):
        return self.played


class _FakeSTT:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def transcribe(self, pcm, publish_event=True):
        self.calls += 1
        return self.text


def tv_check(heard, played_text, loud=True):
    p = VoicePipeline.__new__(VoicePipeline)
    p._audio = _FakeAudio(np.full(16000 * 3, 0.05 if loud else 0.0, np.float32))
    p._stt = _FakeSTT(played_text)
    return VoicePipeline._pc_played_it(p, heard, 100.0, 103.0), p._stt.calls


def test_speech_the_pc_was_playing_is_ignored():
    heard = "You can't control my life. All that people's choice is the pattern."
    assert tv_check(heard, "you can't control my life all of the people's choices are the pattern") == (True, 1)


def test_col_talking_over_the_tv_is_kept():
    assert tv_check("What time is it on the clock today?", "and the weather tomorrow brings heavy rain")[0] is False


def test_a_quiet_pc_is_not_transcribed():
    assert tv_check("You can't control my life at all, honestly.", "x", loud=False) == (False, 0)


def test_short_lines_are_not_judged():
    assert tv_check("Stop.", "stop the car")[0] is False


def test_the_pc_playback_is_kept_in_memory():
    import collections as c

    m = AudioManager.__new__(AudioManager)
    m._loopback_available = True
    m._loopback_lock = __import__("threading").Lock()
    m._loopback_bin_seconds = 0.02
    m._playback_rate = 16000
    m._loopback_audio = c.deque([(10.0 + i * 0.02, np.full(320, i, np.float32)) for i in range(100)], maxlen=1500)
    audio = m.get_loopback_audio(10.5, 11.0)
    assert len(audio) == 27 * 320 and audio[0] == 25  # 10.50 to 11.02 s
    m._loopback_available = False
    assert m.get_loopback_audio(10.5, 11.0) is None


def test_the_worker_uses_both_checks():
    text = (SRC / "voice" / "pipeline.py").read_text(encoding="utf-8")
    assert "_after_wake_word(text)" in text and "self._pc_played_it(text" in text
    assert text.count("self._listen_after_wake()") == 2
