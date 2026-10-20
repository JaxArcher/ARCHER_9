"""
ARCHER hearing its own voice while it speaks (self-echo), 2026-10-20 live
session: two partial, slightly garbled echoes were taken as Col barging in,
so ARCHER cut itself off, and once answered its own words. Claude, 2026-10-20.

_is_self_echo is called on a stand-in object with only the two attributes it
reads, so no audio devices are opened.
"""

from types import SimpleNamespace

from archer.voice.pipeline import VoicePipeline, _mostly_in_order


def speaking(current="", last=""):
    return SimpleNamespace(_current_speaking_text=current, _last_spoken_text=last)


def is_echo(state, heard, recent=True):
    return VoicePipeline._is_self_echo(state, heard, include_recent_response=recent)


SOFA = "Yes, I can see you sitting on the brown sofa in the living room. You are wearing a dark tank top."
CALENDAR = ("I don't have direct access to your personal calendar, so I might not have been able to ask "
            "you a question about it unless you provided me with specific information.")


def test_partial_garbled_echo_of_the_current_sentence():
    # Logged at 14:25:50: "Barge-in confirmed (not self-echo)".
    assert is_echo(speaking(current=SOFA), "I can see you sitting on the ground so")


def test_long_partial_echo_of_the_current_answer():
    # Logged at 14:31:03.
    heard = ("have direct access to your personal calendar. So I might not have been able to ask you "
             "a question about it unless you provide it.")
    assert is_echo(speaking(current=CALENDAR), heard)


def test_short_interruptions_are_still_col():
    for heard in ("Stop.", "Hold on.", "Wait, no.", "ARCHER, stop."):
        assert not is_echo(speaking(current=SOFA), heard), heard


def test_a_real_reply_sharing_a_few_words_is_still_col():
    assert not is_echo(speaking(current=SOFA), "No, I'm on the couch by the window, not the sofa")


def test_the_listening_path_never_compares_with_archers_answer():
    # A genuine reply that repeats ARCHER's question must not be dropped.
    assert not is_echo(speaking(last="Did you mean the meeting on Thursday at three?"),
                       "Yes, the meeting on Thursday at three", recent=False)


def test_mostly_in_order_needs_four_words_in_order():
    assert _mostly_in_order("a b c d".split(), "x a b c d y".split())
    assert not _mostly_in_order("a b c".split(), "a b c".split())          # too short
    assert not _mostly_in_order("d c b a e f".split(), "a b c d".split())  # wrong order
