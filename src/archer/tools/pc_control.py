"""
ARCHER PC Control Module.

Provides desktop automation tools for the Assistant agent:
- Mouse and keyboard control via pyautogui
- Window management via pygetwindow
- Screen capture via mss
- Browser automation via Playwright

CRITICAL SAFETY RULES:
1. All non-read-only actions require user confirmation before execution.
2. HALT immediately cancels all queued actions and active automation.
3. Screen capture (read-only) does NOT require confirmation.
4. The Agent describes the intended action and waits for verbal "yes" before executing.
"""

from __future__ import annotations

import base64
import concurrent.futures
import io
import time
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus


class PCController:
    """
    Desktop automation controller.

    All methods check the halted flag before executing — if HALT
    is triggered mid-action, execution stops immediately.
    """

    def __init__(self) -> None:
        self._bus = get_event_bus()
        self._halted = threading.Event()
        self._bus.subscribe_halt(self._on_halt)

        # Playwright browser instance (lazy init)
        self._browser = None
        self._playwright = None
        self._browser_context = None

        # Playwright's sync API pins every browser/context/page object to
        # the exact OS thread (specifically the greenlet) that created it --
        # calling into it from any other thread raises "Cannot switch to a
        # different thread" (or, once that original thread has been
        # recycled/destroyed, "...which happens to have exited"). Found
        # 2026-09-19: _ensure_browser() used to run on whatever thread
        # happened to call open_url() first (a per-turn CoreAgent thread),
        # while browser_screenshot() was called both from that same kind of
        # per-turn thread AND from server.py's periodic GUI browser-mirror
        # poll (`asyncio.to_thread`, which pulls from Python's shared,
        # multi-threaded default pool) -- neither of those is guaranteed to
        # land on the thread that created the browser, so screenshots failed
        # essentially every time except by chance. Fix: every Playwright
        # call, including the lazy browser launch itself, now runs on this
        # one dedicated single-worker thread, so they're always on the same
        # thread/greenlet regardless of which caller's thread invoked them.
        self._pw_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="archer-playwright"
        )

    def _on_halt(self, event: Event) -> None:
        """HALT handler — stop all active automation."""
        self._halted.set()
        # Fire-and-forget onto the Playwright thread (see _pw_executor's
        # docstring) rather than calling _close_browser() directly here --
        # halt can be triggered from any thread, and close() needs the same
        # thread-affinity as every other Playwright call.
        try:
            self._pw_executor.submit(self._close_browser)
        except RuntimeError:
            pass  # executor already shut down
        logger.warning("PC Control: HALT — all automation stopped.")

    def _check_halt(self) -> bool:
        """Check if HALT was triggered. Returns True if halted."""
        return self._halted.is_set()

    def reset_halt(self) -> None:
        """Clear the halt flag for new operations."""
        self._halted.clear()

    # ------------------------------------------------------------------
    # Screen Capture (read-only — no confirmation needed)
    # ------------------------------------------------------------------

    def take_screenshot(self, region: dict | None = None) -> str | None:
        """
        Capture the screen and return as base64-encoded PNG.

        Args:
            region: Optional dict with keys 'left', 'top', 'width', 'height'
                   for capturing a specific region. None = full screen.

        Returns:
            Base64-encoded PNG string, or None on failure.
        """
        try:
            import mss

            with mss.mss() as sct:
                if region:
                    monitor = {
                        "left": region.get("left", 0),
                        "top": region.get("top", 0),
                        "width": region.get("width", 1920),
                        "height": region.get("height", 1080),
                    }
                else:
                    monitor = sct.monitors[1]  # Primary monitor

                screenshot = sct.grab(monitor)

                # Convert to PNG bytes
                from PIL import Image
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

                logger.info(f"Screenshot captured ({screenshot.size[0]}x{screenshot.size[1]})")
                return b64

        except ImportError as e:
            logger.warning(f"Screenshot dependencies not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None

    def get_active_window(self) -> dict[str, Any]:
        """
        Get information about the currently active window.

        Returns dict with 'title', 'left', 'top', 'width', 'height'.
        Read-only — no confirmation needed.
        """
        try:
            import pygetwindow as gw
            win = gw.getActiveWindow()
            if win:
                return {
                    "title": win.title,
                    "left": win.left,
                    "top": win.top,
                    "width": win.width,
                    "height": win.height,
                }
            return {"title": "Unknown", "left": 0, "top": 0, "width": 0, "height": 0}
        except Exception as e:
            logger.warning(f"Could not get active window: {e}")
            return {"title": "Unknown"}

    def list_windows(self) -> list[dict[str, Any]]:
        """
        List all visible windows.

        Read-only — no confirmation needed.
        """
        try:
            import pygetwindow as gw
            windows = gw.getAllWindows()
            return [
                {
                    "title": w.title,
                    "left": w.left,
                    "top": w.top,
                    "width": w.width,
                    "height": w.height,
                    "visible": w.visible,
                }
                for w in windows
                if w.title and w.visible
            ]
        except Exception as e:
            logger.warning(f"Could not list windows: {e}")
            return []

    # ------------------------------------------------------------------
    # Mouse & Keyboard (requires confirmation)
    # ------------------------------------------------------------------

    def click(self, x: int, y: int, button: str = "left") -> bool:
        """
        Click at screen coordinates.

        REQUIRES user confirmation before calling.
        """
        if self._check_halt():
            return False

        try:
            import pyautogui
            pyautogui.click(x, y, button=button)
            logger.info(f"Clicked ({button}) at ({x}, {y})")
            return True
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return False

    def type_text(self, text: str, interval: float = 0.02) -> bool:
        """
        Type text using keyboard simulation.

        REQUIRES user confirmation before calling.
        """
        if self._check_halt():
            return False

        try:
            import pyautogui
            pyautogui.typewrite(text, interval=interval)
            logger.info(f"Typed: '{text[:50]}{'...' if len(text) > 50 else ''}'")
            return True
        except Exception as e:
            logger.error(f"Type failed: {e}")
            return False

    def hotkey(self, *keys: str) -> bool:
        """
        Press a keyboard shortcut (e.g., hotkey('ctrl', 'c')).

        REQUIRES user confirmation before calling.
        """
        if self._check_halt():
            return False

        try:
            import pyautogui
            pyautogui.hotkey(*keys)
            logger.info(f"Hotkey: {'+'.join(keys)}")
            return True
        except Exception as e:
            logger.error(f"Hotkey failed: {e}")
            return False

    def focus_window(self, title: str) -> bool:
        """
        Focus a window by title (partial match).

        REQUIRES user confirmation before calling.
        """
        if self._check_halt():
            return False

        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].activate()
                time.sleep(0.3)
                logger.info(f"Focused window: '{windows[0].title}'")
                return True
            logger.warning(f"No window found matching '{title}'")
            return False
        except Exception as e:
            logger.error(f"Focus window failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Browser Automation (requires confirmation)
    # ------------------------------------------------------------------

    def _ensure_browser(self) -> bool:
        """Ensure a Playwright browser instance is running."""
        if self._browser is not None:
            return True

        try:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=False,
                args=["--start-maximized"],
            )
            self._browser_context = self._browser.new_context(
                viewport=None,  # Use full window size
            )
            logger.info("Playwright browser launched.")
            return True

        except ImportError:
            logger.warning(
                "Playwright not installed. Install with: pip install playwright && playwright install chromium"
            )
            return False
        except Exception as e:
            logger.error(f"Browser launch failed: {e}")
            return False

    def _close_browser(self) -> None:
        """Close the Playwright browser."""
        try:
            if self._browser_context:
                self._browser_context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        finally:
            self._browser = None
            self._browser_context = None
            self._playwright = None

    def _run_on_pw_thread(self, fn, *args, timeout: float = 30.0, **kwargs):
        """Submit fn to the dedicated Playwright thread and block for the
        result (see _pw_executor's docstring in __init__ for why this
        exists). fn is expected to already catch its own exceptions and
        return a safe fallback value -- this only guards against the
        submission itself failing or genuinely hanging."""
        try:
            future = self._pw_executor.submit(fn, *args, **kwargs)
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.error(f"Playwright call '{fn.__name__}' timed out after {timeout}s.")
            return None
        except RuntimeError as e:
            logger.error(f"Playwright thread unavailable for '{fn.__name__}': {e}")
            return None

    def open_url(self, url: str) -> dict[str, Any]:
        """
        Open a URL in the browser.

        REQUIRES user confirmation before calling.

        Returns dict with 'success', 'title', 'url'.
        """
        if self._check_halt():
            return {"success": False, "reason": "HALT"}
        result = self._run_on_pw_thread(self._open_url_impl, url)
        return result if result is not None else {"success": False, "reason": "Playwright call failed/timed out"}

    def _open_url_impl(self, url: str) -> dict[str, Any]:
        if not self._ensure_browser():
            return {"success": False, "reason": "Browser not available"}

        try:
            page = self._browser_context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)

            result = {
                "success": True,
                "title": page.title(),
                "url": page.url,
            }
            logger.info(f"Opened URL: {url} — Title: '{result['title']}'")
            return result

        except Exception as e:
            logger.error(f"Browser navigation failed: {e}")
            return {"success": False, "reason": str(e)}

    def browser_screenshot(self) -> str | None:
        """
        Take a screenshot of the active browser page.

        Read-only — no confirmation needed.
        """
        return self._run_on_pw_thread(self._browser_screenshot_impl)

    def _browser_screenshot_impl(self) -> str | None:
        if not self._browser_context:
            return None

        try:
            pages = self._browser_context.pages
            if not pages:
                return None

            page = pages[-1]  # Most recent page
            # Explicit shorter timeout (2026-09-19 finding): Playwright's
            # screenshot default timeout is 30s, and a live/animated page
            # (autoplaying YouTube, in particular) can genuinely stall on
            # "waiting for fonts to load" for the full 30s before failing --
            # that's 30s of dead air in the middle of a conversation turn.
            # Fail fast instead; the caller already handles a None result.
            screenshot_bytes = page.screenshot(timeout=8000)
            return base64.b64encode(screenshot_bytes).decode("utf-8")

        except Exception as e:
            logger.error(f"Browser screenshot failed: {e}")
            return None

    def browser_click(self, selector: str) -> bool:
        """
        Click an element in the browser by CSS selector.

        REQUIRES user confirmation before calling.
        """
        if self._check_halt():
            return False
        return bool(self._run_on_pw_thread(self._browser_click_impl, selector))

    def _browser_click_impl(self, selector: str) -> bool:
        if not self._browser_context:
            return False

        try:
            pages = self._browser_context.pages
            if not pages:
                return False

            page = pages[-1]
            page.click(selector, timeout=5000)
            logger.info(f"Browser click: '{selector}'")
            return True

        except Exception as e:
            logger.error(f"Browser click failed: {e}")
            return False

    def browser_type(self, selector: str, text: str) -> bool:
        """
        Type text into a browser element.

        REQUIRES user confirmation before calling.
        """
        if self._check_halt():
            return False
        return bool(self._run_on_pw_thread(self._browser_type_impl, selector, text))

    def _browser_type_impl(self, selector: str, text: str) -> bool:
        if not self._browser_context:
            return False

        try:
            pages = self._browser_context.pages
            if not pages:
                return False

            page = pages[-1]
            page.fill(selector, text, timeout=5000)
            logger.info(f"Browser type into '{selector}': '{text[:50]}'")
            return True

        except Exception as e:
            logger.error(f"Browser type failed: {e}")
            return False

    def browser_get_text(self, selector: str = "body") -> str:
        """
        Get text content from a browser element.

        Read-only — no confirmation needed.
        """
        result = self._run_on_pw_thread(self._browser_get_text_impl, selector)
        return result if result is not None else ""

    def _browser_get_text_impl(self, selector: str = "body") -> str:
        if not self._browser_context:
            return ""

        try:
            pages = self._browser_context.pages
            if not pages:
                return ""

            page = pages[-1]
            return page.inner_text(selector, timeout=5000)

        except Exception as e:
            logger.error(f"Browser get text failed: {e}")
            return ""

    def close_browser(self) -> None:
        """Close the browser. REQUIRES user confirmation."""
        if self._check_halt():
            return
        self._run_on_pw_thread(self._close_browser)
        logger.info("Browser closed by user request.")
