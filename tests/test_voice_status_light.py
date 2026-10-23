"""
Tests for ARCHER Voice Status Light (Claude Review 2026-10-22, 18:30).
Validates DOM placement at the top-left of the main page, visual CSS states
(red listening, yellow processing, blinking green speaking, dim/off idle,
slash when muted/paused), reduced-motion accessibility, screen reader support,
and event wiring with pipeline state events.
"""

import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SRC = ROOT / "src" / "archer"


def test_voice_status_light_dom_placement_and_accessibility():
    """Verify HTML structure of voice status light at top-left of main page."""
    html = (WEB / "index.html").read_text(encoding="utf-8")

    # In toolbar, right after archer-status dot
    toolbar_match = re.search(r'<div id="archer-toolbar">([\s\S]*?)<button id="archer-mode-btn"', html)
    assert toolbar_match, "archer-toolbar not found or does not contain archer-mode-btn"
    toolbar_content = toolbar_match.group(1)

    assert 'id="archer-status"' in toolbar_content, "Missing status-dot in toolbar"
    assert 'id="archer-voice-status"' in toolbar_content, "Missing archer-voice-status in toolbar"

    # Verify voice status light structure
    status_pos = toolbar_content.index('id="archer-status"')
    voice_pos = toolbar_content.index('id="archer-voice-status"')
    assert status_pos < voice_pos, "voice status light must be next to the existing status dot"

    voice_tag = re.search(r'<div id="archer-voice-status"([^>]*)>', toolbar_content)
    assert voice_tag, "Missing <div id=\"archer-voice-status\" ...>"
    attrs = voice_tag.group(1)

    assert "voice-status-light" in attrs, "Missing voice-status-light class"
    assert 'role="status"' in attrs, "Must have role='status' for accessibility"
    assert 'aria-live="polite"' in attrs, "Must have aria-live='polite' for accessibility"
    assert 'title=' in attrs, "Must have title tooltip"

    # Slash child element for muted/paused
    assert 'class="voice-status-slash"' in toolbar_content

    # Screen reader text label
    assert 'class="sr-only"' in toolbar_content
    assert 'id="archer-voice-status-sr"' in toolbar_content


def test_voice_status_light_css_styling_and_states():
    """Verify CSS dimensions (20-24px), colors for all states, blinking, and reduced-motion."""
    css = (WEB / "css" / "ui.css").read_text(encoding="utf-8")

    # Dimensions: roughly 20-24px round light
    dim_match = re.search(r"\.voice-status-light\s*\{([^}]*)\}", css)
    assert dim_match, "Missing .voice-status-light CSS block"
    dim_block = dim_match.group(1)

    w_match = re.search(r"width:\s*(\d+)px", dim_block)
    h_match = re.search(r"height:\s*(\d+)px", dim_block)
    assert w_match and h_match
    w = int(w_match.group(1))
    h = int(h_match.group(1))
    assert 20 <= w <= 24, f"Width {w}px not in 20-24px range"
    assert 20 <= h <= 24, f"Height {h}px not in 20-24px range"
    assert "border-radius: 50%" in dim_block or "border-radius:50%" in dim_block

    # State: listening (Red, steady)
    list_match = re.search(r"\.voice-status-light\.voice-state-listening\s*\{([^}]*)\}", css)
    assert list_match, "Missing .voice-state-listening CSS"
    list_block = list_match.group(1)
    assert "#ff" in list_block.lower() or "red" in list_block.lower(), "Listening state must be red"

    # State: processing (Yellow, steady)
    proc_match = re.search(r"\.voice-status-light\.voice-state-processing\s*\{([^}]*)\}", css)
    assert proc_match, "Missing .voice-state-processing CSS"
    proc_block = proc_match.group(1)
    assert ("#ff" in proc_block.lower() or "yellow" in proc_block.lower()), "Processing state must be yellow"

    # State: speaking (Green, blinking)
    spk_match = re.search(r"\.voice-status-light\.voice-state-speaking\s*\{([^}]*)\}", css)
    assert spk_match, "Missing .voice-state-speaking CSS"
    spk_block = spk_match.group(1)
    assert ("#30d158" in spk_block or "#34c759" in spk_block or "#4dffb8" in spk_block or "green" in spk_block), "Speaking state must be green"
    assert "animation:" in spk_block, "Speaking state must have blinking animation"

    # Reduced-motion support
    assert "@media (prefers-reduced-motion: reduce)" in css
    red_motion = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\}", css)
    assert red_motion, "Missing prefers-reduced-motion media query"
    assert "animation: none" in red_motion.group(1), "Reduced motion must turn off blinking animation"

    # State: idle (dim grey / off)
    idle_match = re.search(r"\.voice-status-light\.voice-state-idle\s*\{([^}]*)\}", css)
    assert idle_match, "Missing .voice-state-idle CSS"

    # Muted or paused slash
    assert ".voice-status-slash" in css
    assert ".voice-status-light.is-muted-or-paused" in css


def test_voice_status_light_ui_js_event_wiring():
    """Verify ui.js drives voice status light from pipeline state, mic mute, and listening pause."""
    ui_js = (WEB / "js" / "ui.js").read_text(encoding="utf-8")

    assert 'document.getElementById("archer-voice-status")' in ui_js
    assert 'document.getElementById("archer-voice-status-sr")' in ui_js

    # Listeners driving state
    assert 'ArcherClient.on("state"' in ui_js, "ui.js must subscribe to pipeline state events"
    assert 'ArcherClient.on("wakeWord"' in ui_js
    assert 'ArcherClient.on("halt"' in ui_js
    assert 'ArcherClient.on("micMute"' in ui_js

    # Function updating the light
    assert "updateVoiceStatusLight" in ui_js
    assert "voice-state-listening" in ui_js
    assert "voice-state-processing" in ui_js
    assert "voice-state-speaking" in ui_js
    assert "voice-state-idle" in ui_js
    assert "is-muted-or-paused" in ui_js

    # Tooltip and screen reader updates
    assert 'setAttribute("title"' in ui_js
    assert 'setAttribute("aria-label"' in ui_js


def test_server_tracks_and_broadcasts_voice_pipeline_state():
    """Verify server.py bridges PIPELINE_STATE_CHANGED and snapshots it for new connections."""
    server_py = (SRC / "server.py").read_text(encoding="utf-8")

    assert "_current_voice_state" in server_py
    assert "EventType.PIPELINE_STATE_CHANGED" in server_py
    assert '"voice_state": _current_voice_state' in server_py
    assert '"type": "state"' in server_py
    assert '"state": _current_voice_state' in server_py
