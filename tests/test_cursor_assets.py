"""
Unit tests for cursor HUD effects, mouse priority, and asset consistency
(Review 2026-10-21 17:55 / 18:15 Item 4).
"""

from pathlib import Path
import pytest


def test_cursor_js_contains_mouse_priority_and_fallbacks():
    """Verify web/js/cursor.js has mouse-priority and hand takeover logic."""
    cursor_js_path = Path("web/js/cursor.js")
    assert cursor_js_path.exists(), "web/js/cursor.js must exist"
    content = cursor_js_path.read_text(encoding="utf-8")

    # Mouse priority: ring follows mouse, mouse wins
    assert "pointermove" in content
    assert "lastMouseTime" in content
    assert "MOUSE_OVERRIDE_TIMEOUT_MS" in content
    assert "handTrackingActive" in content

    # Cursor stability: never disappears
    assert "hideCursor" in content
    assert "showCursor" in content
    assert "document.elementFromPoint" in content
    assert "archer-cursor-active" in content
    assert "ac-visible" in content
    assert "trails" in content

    # Native input preservation
    assert "input" in content
    assert "textarea" in content
    assert "select" in content
    assert "iframe" in content


def test_cursor_css_rules():
    """Verify web/css/cursor.css defines ring, trails, and preserves native cursor on inputs."""
    cursor_css_path = Path("web/css/cursor.css")
    assert cursor_css_path.exists(), "web/css/cursor.css must exist"
    css = cursor_css_path.read_text(encoding="utf-8")

    assert "#archer-cursor" in css
    assert ".archer-cursor-trail" in css
    assert "pointer-events: none" in css
    assert "html.archer-cursor-active" in css

    # Native cursor restoration rules
    assert "html.archer-cursor-active input" in css
    assert "html.archer-cursor-active textarea" in css
    assert "html.archer-cursor-active iframe" in css


def test_barehands_css_in_sync():
    """Verify barehands/assets/cursor.css is identical to web/css/cursor.css per contract."""
    web_css = Path("web/css/cursor.css").read_text(encoding="utf-8")
    barehands_css = Path("barehands/assets/cursor.css").read_text(encoding="utf-8")
    assert web_css == barehands_css, "barehands/assets/cursor.css must match web/css/cursor.css"


def test_web_index_html_loads_cursor_module():
    """Verify web/index.html includes cursor.js script."""
    index_html = Path("web/index.html").read_text(encoding="utf-8")
    assert "/static/js/cursor.js" in index_html
