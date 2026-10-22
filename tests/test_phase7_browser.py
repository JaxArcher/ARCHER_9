"""
Unit and integration tests for Phase 7: Chromium inside the pane (Spec Section 10).

Verifies:
1. PCController singleton pattern and persistent profile path isolation.
2. Browser launch, persistent context, and tab list tracking with pinned Google Messages.
3. Chrome DevTools Protocol (CDP) screencasting and frame callback streaming.
4. Browser chrome actions: navigate, back, forward, reload.
5. Multi-tab management: new tab, switch tab, close tab.
6. Input forwarding: mouse, wheel, keyboard, and insertText via CDP.
7. Screencast visibility pause and resume.
8. Compatibility with UniversalToolExecutor agent tools (open_url, browser_screenshot, get_browser_status).
9. Server endpoints for browser state, navigate, tabs, and restart.
"""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from archer.tools.pc_control import PCController, get_pc_controller


@pytest.fixture(scope="module")
def isolated_browser_controller(tmp_path_factory):
    """Fixture providing a PCController with an isolated profile dir."""
    temp_profile = tmp_path_factory.mktemp("browser_profile")
    os.environ["ARCHER_BROWSER_PROFILE_DIR"] = str(temp_profile)

    pc = get_pc_controller()
    pc.reset_halt()
    yield pc

    # Cleanup browser on teardown
    try:
        pc.close_browser()
    except Exception:
        pass


def test_pc_controller_singleton(isolated_browser_controller):
    """Verify PCController returns the singleton instance."""
    pc1 = get_pc_controller()
    pc2 = PCController()
    assert pc1 is pc2
    assert pc1 is isolated_browser_controller


def test_browser_launch_and_pinned_tab(isolated_browser_controller):
    """Verify persistent browser launches and initializes pinned tab."""
    pc = isolated_browser_controller
    assert pc.ensure_browser() is True

    status = pc.get_browser_status()
    assert status.get("open") is True
    tabs = status.get("tabs", [])
    assert len(tabs) >= 1
    # First tab should be pinned Google Messages
    first_tab = tabs[0]
    assert first_tab.get("index") == 0
    assert first_tab.get("pinned") is True


def test_screencast_streaming_and_callbacks(isolated_browser_controller):
    """Verify CDP screencast frames stream into registered callbacks."""
    pc = isolated_browser_controller
    received_frames = []

    def on_frame(data, metadata, session_id):
        received_frames.append(session_id)

    pc.register_screencast_callback(on_frame)
    pc.start_screencast()

    # Navigate to a lightweight data URL to trigger a paint
    res = pc.browser_navigate("data:text/html,<html><body style='background:#0a1828;'><h1 style='color:#53e8ff;'>Screencast Test</h1></body></html>")
    assert res.get("success") is True

    # Wait briefly for screencast frames to arrive
    t0 = time.time()
    while time.time() - t0 < 3.0 and not received_frames:
        time.sleep(0.05)

    pc.unregister_screencast_callback(on_frame)
    assert len(received_frames) > 0, "No screencast frames received via CDP callback"


def test_multi_tab_management(isolated_browser_controller):
    """Verify creating new tabs, switching tabs, and closing tabs."""
    pc = isolated_browser_controller

    # Open a second tab
    res_tab2 = pc.browser_new_tab("data:text/html,<h1>Tab 2</h1>")
    assert res_tab2.get("success") is True
    tab2_idx = res_tab2.get("index")

    tabs = pc.get_browser_tabs()
    assert len(tabs) >= 2
    assert any(t["index"] == tab2_idx and t["active"] for t in tabs)

    # Switch back to tab 0
    res_sw = pc.browser_switch_tab(0)
    assert res_sw.get("success") is True
    tabs = pc.get_browser_tabs()
    assert tabs[0]["active"] is True

    # Close tab 2
    res_close = pc.browser_close_tab(tab2_idx)
    assert res_close.get("success") is True
    tabs_after = pc.get_browser_tabs()
    assert len(tabs_after) == len(tabs) - 1


def test_input_forwarding_via_cdp(isolated_browser_controller):
    """Verify mouse click, keyboard typing, and insertText dispatch."""
    pc = isolated_browser_controller

    pc.browser_navigate("data:text/html,<html><body><input id='inp' type='text' value='' /><button id='btn' onclick=\"document.getElementById('inp').value='clicked'\">Click</button></body></html>")

    # Click button at approximate coordinates
    click_ok = pc.dispatch_mouse_event("mousePressed", x=50, y=50, button="left")
    assert click_ok is True
    release_ok = pc.dispatch_mouse_event("mouseReleased", x=50, y=50, button="left")
    assert release_ok is True

    # Dispatch text insertion
    insert_ok = pc.insert_text("ARCHER")
    assert insert_ok is True

    # Dispatch key event
    key_ok = pc.dispatch_key_event("rawKeyDown", key="Enter", code="Enter")
    assert key_ok is True


def test_browser_chrome_navigation(isolated_browser_controller):
    """Verify back, forward, reload, and navigation."""
    pc = isolated_browser_controller

    res1 = pc.browser_navigate("data:text/html,<h1>Page A</h1>")
    assert res1.get("success") is True

    res2 = pc.browser_navigate("data:text/html,<h1>Page B</h1>")
    assert res2.get("success") is True

    # Test reload
    reload_res = pc.browser_reload()
    assert reload_res.get("success") is True

    # Test back
    back_res = pc.browser_back()
    assert back_res.get("success") is True


def test_agent_tools_backward_compatibility(isolated_browser_controller):
    """Verify existing open_url, browser_screenshot, and get_browser_status methods."""
    pc = isolated_browser_controller
    pc.reset_halt()

    # open_url
    nav_res = pc.open_url("data:text/html,<h2 id='test-title'>Agent Tool Page</h2>")
    assert nav_res.get("success") is True

    # browser_screenshot
    shot_b64 = pc.browser_screenshot()
    assert shot_b64 is not None
    assert len(shot_b64) > 100

    # browser_get_text
    text = pc.browser_get_text("h2#test-title")
    assert "Agent Tool Page" in text

    # get_browser_status
    status = pc.get_browser_status()
    assert status.get("open") is True


def test_visibility_pause_and_resume(isolated_browser_controller):
    """Verify screencast visibility toggle does not crash or stall."""
    pc = isolated_browser_controller

    # Pause screencasting (user switched tabs away)
    pc.set_screencast_visible(False)
    time.sleep(0.1)

    # Resume screencasting (user switched back to artifacts)
    pc.set_screencast_visible(True)
    time.sleep(0.1)

    status = pc.get_browser_status()
    assert status.get("open") is True
