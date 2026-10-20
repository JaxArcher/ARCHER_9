"""
Browser tools (Claude, 2026-10-20):
- open_url allows 90 s for the browser's first start (it took ~50 s live,
  the 30 s limit reported a failure, and the model then answered about
  something else);
- open_url_in_my_browser opens Col's own browser, only for http(s) pages,
  when he asks for a separate window.
"""

from unittest.mock import MagicMock, patch

import pytest

from archer.tools.pc_control import PCController


@pytest.fixture
def pc():
    p = PCController.__new__(PCController)
    p._browser = None
    p._check_halt = lambda: False
    return p


def test_first_browser_start_gets_90_seconds(pc):
    pc._run_on_pw_thread = MagicMock(return_value={"success": True})
    pc.open_url("https://youtube.com")
    assert pc._run_on_pw_thread.call_args.kwargs["timeout"] == 90.0
    pc._browser = object()
    pc.open_url("https://youtube.com")
    assert pc._run_on_pw_thread.call_args.kwargs["timeout"] == 30.0


@pytest.mark.parametrize("given, opened", [
    ("https://www.youtube.com", "https://www.youtube.com"),
    ("http://example.org/page", "http://example.org/page"),
    ("youtube.com", "https://youtube.com"),
])
def test_opens_web_pages_in_cols_browser(pc, given, opened):
    with patch("webbrowser.open", return_value=True) as wb:
        result = pc.open_url_in_my_browser(given)
    wb.assert_called_once_with(opened, new=2)
    assert result["success"] and result["url"] == opened


@pytest.mark.parametrize("given", ["file:///C:/Windows/win.ini", "javascript:alert(1)", "ftp://x.org"])
def test_never_opens_anything_but_web_pages(pc, given):
    with patch("webbrowser.open") as wb:
        result = pc.open_url_in_my_browser(given)
    wb.assert_not_called()
    assert not result["success"]


def test_the_model_is_offered_both_tools():
    from archer.skills import skills_registry as reg

    reg._SKILLS_CACHE = None
    tools = {t["name"]: t for t in reg.get_all_tools()}
    assert "separate window" in tools["open_url_in_my_browser"]["description"]
    assert "default" in tools["open_url"]["description"]
    assert tools["open_url_in_my_browser"]["input_schema"]["required"] == ["url"]


def test_executor_routes_the_new_tool():
    from archer.skills.tool_executor import UniversalToolExecutor

    ex = UniversalToolExecutor.__new__(UniversalToolExecutor)
    ex._pc_controller = MagicMock()
    ex._pc_controller.open_url_in_my_browser.return_value = {"success": True}
    out = ex._exec_pc_tool("open_url_in_my_browser", {"url": "https://youtube.com"})
    ex._pc_controller.open_url_in_my_browser.assert_called_once_with("https://youtube.com")
    assert out == {"result": {"success": True}}


def _launch_args(monkeypatch, on_screen):
    import sys
    import types
    from types import SimpleNamespace

    launched = {}

    class FakeChromium:
        def launch(self, headless, args):
            launched.update(headless=headless, args=args)
            return SimpleNamespace(new_context=lambda viewport: object())

    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: SimpleNamespace(start=lambda: SimpleNamespace(chromium=FakeChromium()))
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    monkeypatch.setattr("archer.config.get_config", lambda: SimpleNamespace(browser_on_screen=on_screen))
    p = PCController.__new__(PCController)
    p._browser = None
    assert p._ensure_browser()
    return launched


def test_browser_window_opens_off_screen_by_default(monkeypatch):
    """Col, 2026-10-20: pages show inside ARCHER's page, not in a desktop window."""
    from archer.config import ArcherConfig

    assert ArcherConfig.model_fields["browser_on_screen"].default is False
    launched = _launch_args(monkeypatch, on_screen=False)
    assert launched["headless"] is False  # a real window: fewer blocks, and sound plays
    assert "--window-position=12000,12000" in launched["args"]
    assert "--start-maximized" not in launched["args"]
    assert _launch_args(monkeypatch, on_screen=True)["args"] == ["--start-maximized"]


def test_off_screen_window_keeps_drawing(monkeypatch):
    args = _launch_args(monkeypatch, on_screen=False)["args"]
    assert "--disable-features=CalculateNativeWinOcclusion" in args


def test_window_comes_on_screen_when_its_picture_stops(monkeypatch):
    """2026-10-20, 16:18: off-screen, every in-page screenshot timed out."""
    from types import SimpleNamespace

    sent = []
    shots = {"fail": True}

    class Page:
        def screenshot(self, timeout):
            if shots["fail"]:
                raise TimeoutError("Page.screenshot: Timeout 8000ms exceeded.")
            return b"png"

    cdp = SimpleNamespace(send=lambda method, params=None: sent.append((method, params)) or {"windowId": 7})
    p = PCController.__new__(PCController)
    p._browser_context = SimpleNamespace(pages=[Page()], new_cdp_session=lambda page: cdp)
    p._browser_off_screen = True
    p._screenshot_failures = 0
    assert p._browser_screenshot_impl() is None
    assert sent == []  # one failure can be a busy page
    assert p._browser_screenshot_impl() is None
    assert sent[-1][0] == "Browser.setWindowBounds"
    assert sent[-1][1]["windowId"] == 7 and sent[-1][1]["bounds"]["left"] == 40
    assert p._browser_off_screen is False
    shots["fail"] = False
    assert p._browser_screenshot_impl()  # the picture comes back
    assert p._screenshot_failures == 0


# --- Play something on YouTube (Claude, 2026-10-20, 16:45) -----------------------

def test_play_youtube_is_offered_and_routed():
    from archer.skills.skills_registry import get_all_tools_ollama_format, get_tool_category
    from archer.skills.tool_executor import UniversalToolExecutor

    tools = {t["function"]["name"]: t for t in get_all_tools_ollama_format()}
    assert tools["play_youtube"]["function"]["parameters"]["required"] == ["query"]
    assert get_tool_category("play_youtube") == "automation"
    executor = UniversalToolExecutor.__new__(UniversalToolExecutor)
    executor._pc_controller = MagicMock()
    executor._pc_controller.play_youtube.return_value = {"success": True, "playing": "X"}
    assert executor.execute("play_youtube", {"query": "black parade"}) == {"result": {"success": True, "playing": "X"}}
    executor._pc_controller.play_youtube.assert_called_once_with("black parade")


def test_play_youtube_needs_something_to_search(pc):
    pc._run_on_pw_thread = MagicMock()
    assert pc.play_youtube("   ")["success"] is False
    pc._run_on_pw_thread.assert_not_called()


def test_play_youtube_in_a_real_browser_with_fake_youtube_pages():
    """Ads and Shorts are skipped; a renamed results page falls back to any video link."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    results = (
        '<ytd-ad-slot-renderer><a href="https://ads.example/x">Ad</a></ytd-ad-slot-renderer>'
        '<ytd-reel-shelf-renderer><a href="/shorts/abc">Short</a></ytd-reel-shelf-renderer>'
        '<ytd-video-renderer><a id="video-title" title="Black Parade" href="/watch?v=first">Black Parade</a>'
        '</ytd-video-renderer>'
    )
    renamed = '<new-renderer><a href="/watch?v=fallback">Fallback video</a></new-renderer>'
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip(f"no browser here: {e}")
    try:
        for page_html, expected in ((results, "watch?v=first"), (renamed, "watch?v=fallback")):
            context = browser.new_context()
            def serve(route, html=page_html):
                route.fulfill(status=200, content_type="text/html",
                              body=html if "/results" in route.request.url else "<title>video</title>")

            context.route("https://www.youtube.com/**", lambda route: serve(route))
            p = PCController.__new__(PCController)
            p._browser, p._browser_context = browser, context
            p._ensure_browser = lambda: True
            out = p._play_youtube_impl("black parade")
            assert out["success"] and out["url"].endswith(expected), out
            context.close()
    finally:
        browser.close()
        pw.stop()
