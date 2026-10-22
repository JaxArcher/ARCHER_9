"""
ARCHER PC Control Module.

Provides desktop automation tools for the Assistant agent:
- Mouse and keyboard control via pyautogui
- Window management via pygetwindow
- Screen capture via mss
- Browser automation via Playwright Chromium in the workspace pane (Phase 7, Spec Section 10)

CRITICAL SAFETY RULES:
1. All non-read-only actions require user confirmation before execution.
2. HALT immediately cancels all queued actions and active automation.
3. Screen capture (read-only) does NOT require confirmation.
4. Navigation is free; submit/post/purchase/send actions go through Phase 3 approval gate.
"""

from __future__ import annotations

import base64
import concurrent.futures
import io
import os
import queue
import time
import threading
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus

_PC_CONTROLLER_INSTANCE: PCController | None = None


def get_pc_controller() -> PCController:
    """Get the singleton PCController instance."""
    global _PC_CONTROLLER_INSTANCE
    if _PC_CONTROLLER_INSTANCE is None:
        _PC_CONTROLLER_INSTANCE = PCController()
    return _PC_CONTROLLER_INSTANCE


class PCController:
    """
    Desktop and Browser automation controller.

    Reuses a single persistent Playwright Chromium instance inside the ARCHER pane
    with CDP screencast streaming, bidirectional mouse/keyboard forwarding, tab
    management, and pinned Google Messages for web.
    """

    def __new__(cls, *args, **kwargs):
        global _PC_CONTROLLER_INSTANCE
        if _PC_CONTROLLER_INSTANCE is None:
            _PC_CONTROLLER_INSTANCE = super().__new__(cls)
        return _PC_CONTROLLER_INSTANCE

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._bus = get_event_bus()
        self._halted = threading.Event()
        self._bus.subscribe_halt(self._on_halt)

        # Playwright persistent browser instance state
        self._playwright = None
        self._browser = None
        self._browser_context = None
        self._active_page = None
        self._active_page_idx = 0
        self._cdp_session = None

        # Screencasting & interaction state
        self._screencast_active = False
        self._screencast_visible = False
        self._screencast_callbacks: list[Callable[[str, dict, int], None]] = []

        # Dedicated Playwright worker thread & command queue
        self._pw_queue = queue.Queue()
        self._pw_thread_stop = threading.Event()
        self._pw_thread = threading.Thread(
            target=self._pw_worker_loop,
            daemon=True,
            name="archer-playwright-worker",
        )
        self._pw_thread.start()

    def _on_halt(self, event: Event) -> None:
        """HALT handler — cancel active automation."""
        self._halted.set()
        logger.warning("PC Control: HALT — automation stopped.")

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
        """Get information about the currently active window."""
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
        """List all visible windows."""
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
        """Click at desktop screen coordinates."""
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
        """Type text using keyboard simulation."""
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
        """Press a keyboard shortcut (e.g. hotkey('ctrl', 'c'))."""
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
        """Focus a desktop window by title."""
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
    # Playwright Thread Worker Loop & Helpers
    # ------------------------------------------------------------------

    def _run_on_pw_thread(self, fn, *args, timeout: float = 30.0, **kwargs):
        """Submit fn to the dedicated Playwright thread and block for result."""
        if self._pw_thread_stop.is_set():
            return None
        future = concurrent.futures.Future()
        self._pw_queue.put((fn, args, kwargs, future))
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.error(f"Playwright call '{fn.__name__}' timed out after {timeout}s.")
            return None
        except Exception as e:
            logger.error(f"Playwright execution error for '{fn.__name__}': {e}")
            return None

    def _pw_worker_loop(self) -> None:
        """Worker loop running on the dedicated Playwright thread."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                self._playwright = p
                while not self._pw_thread_stop.is_set():
                    # If screencasting is actively visible, pump event loop frequently (~25 FPS)
                    timeout = 0.035 if (self._screencast_active and self._screencast_visible) else 0.2
                    try:
                        item = self._pw_queue.get(timeout=timeout)
                        fn, args, kwargs, future = item
                        try:
                            res = fn(*args, **kwargs)
                            future.set_result(res)
                        except Exception as exc:
                            future.set_exception(exc)
                    except queue.Empty:
                        if self._screencast_active and self._screencast_visible and self._active_page:
                            try:
                                self._active_page.wait_for_timeout(35)
                            except Exception:
                                pass
                self._close_browser_impl()
        except Exception as e:
            logger.error(f"Playwright worker loop exited: {e}")

    # ------------------------------------------------------------------
    # Browser Automation & Screencast Streaming (Phase 7, Spec Section 10)
    # ------------------------------------------------------------------

    def _ensure_browser_impl(self) -> bool:
        """Ensure Playwright persistent browser context is launched."""
        if self._browser_context is not None:
            return True
        if self._playwright is None:
            return False

        try:
            from archer.config import get_config
            cfg = get_config()

            profile_dir = Path(os.environ.get("ARCHER_BROWSER_PROFILE_DIR", str(cfg.data_dir / "browser_profile"))).resolve()
            profile_dir.mkdir(parents=True, exist_ok=True)

            self._browser_off_screen = not getattr(cfg, "browser_on_screen", False)
            if not self._browser_off_screen:
                args = ["--start-maximized"]
            else:
                args = [
                    "--window-position=12000,12000",
                    "--window-size=1280,800",
                    "--disable-features=CalculateNativeWinOcclusion",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                ]

            self._browser_context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                args=args,
                viewport={"width": 1280, "height": 800},
            )
            self._browser = getattr(self._browser_context, "browser", self._browser_context)

            pages = self._browser_context.pages
            if not pages:
                page = self._browser_context.new_page()
            else:
                page = pages[0]
            self._active_page_idx = 0
            self._active_page = page

            # Pinned Google Messages: navigate if currently blank
            if page.url in ("", "about:blank"):
                try:
                    page.goto("https://messages.google.com/web", timeout=12000, wait_until="domcontentloaded")
                except Exception as e:
                    logger.debug(f"Initial navigation to Messages: {e}")

            self._attach_cdp_impl(page)
            logger.info(f"Playwright persistent browser launched (profile: {profile_dir}).")
            return True
        except Exception as e:
            logger.error(f"Browser launch failed: {e}")
            return False

    def _attach_cdp_impl(self, page) -> None:
        """Attach CDP session to the active page for screencast and input."""
        if self._cdp_session:
            try:
                self._cdp_session.send("Page.stopScreencast")
                self._cdp_session.detach()
            except Exception:
                pass
            self._cdp_session = None

        self._active_page = page
        try:
            self._cdp_session = self._browser_context.new_cdp_session(page)

            def _on_screencast_frame(params):
                sid = params.get("sessionId")
                data_b64 = params.get("data")
                metadata = params.get("metadata", {})
                try:
                    if self._cdp_session:
                        self._cdp_session.send("Page.screencastFrameAck", {"sessionId": sid})
                except Exception:
                    pass
                for cb in list(self._screencast_callbacks):
                    try:
                        cb(data_b64, metadata, sid)
                    except Exception as err:
                        logger.debug(f"Screencast callback error: {err}")

            self._cdp_session.on("Page.screencastFrame", _on_screencast_frame)
            if self._screencast_active:
                self._cdp_session.send("Page.startScreencast", {
                    "format": "jpeg",
                    "quality": 70,
                    "maxWidth": 1280,
                    "maxHeight": 800,
                    "everyNthFrame": 1,
                })
        except Exception as e:
            logger.error(f"CDP attach failed: {e}")

    def _close_browser_impl(self) -> None:
        """Close browser context and cleanup CDP."""
        if self._cdp_session:
            try:
                self._cdp_session.send("Page.stopScreencast")
                self._cdp_session.detach()
            except Exception:
                pass
            self._cdp_session = None
        if self._browser_context:
            try:
                self._browser_context.close()
            except Exception:
                pass
            self._browser_context = None
        self._browser = None
        self._active_page = None

    # ------------------------------------------------------------------
    # Public Browser Controls & CDP Screencast API
    # ------------------------------------------------------------------

    def ensure_browser(self) -> bool:
        """Ensure browser is open and running."""
        return bool(self._run_on_pw_thread(self._ensure_browser_impl))

    def start_screencast(self) -> bool:
        """Start screencast streaming on the active page."""
        def _start():
            if not self._ensure_browser_impl():
                return False
            self._screencast_active = True
            self._screencast_visible = True
            if self._cdp_session:
                try:
                    self._cdp_session.send("Page.startScreencast", {
                        "format": "jpeg",
                        "quality": 70,
                        "maxWidth": 1280,
                        "maxHeight": 800,
                        "everyNthFrame": 1,
                    })
                except Exception as e:
                    logger.debug(f"Start screencast CDP error: {e}")
            return True
        return bool(self._run_on_pw_thread(_start))

    def stop_screencast(self) -> bool:
        """Stop screencast streaming."""
        def _stop():
            self._screencast_active = False
            if self._cdp_session:
                try:
                    self._cdp_session.send("Page.stopScreencast")
                except Exception:
                    pass
            return True
        return bool(self._run_on_pw_thread(_stop))

    def set_screencast_visible(self, visible: bool) -> None:
        """Pause or resume screencast frame pumping based on tab visibility."""
        def _set():
            self._screencast_visible = visible
            if visible and not self._screencast_active:
                self._start_screencast_impl()
            return True
        self._run_on_pw_thread(_set)

    def _start_screencast_impl(self):
        self._screencast_active = True
        self._screencast_visible = True
        if self._cdp_session:
            try:
                self._cdp_session.send("Page.startScreencast", {
                    "format": "jpeg",
                    "quality": 70,
                    "maxWidth": 1280,
                    "maxHeight": 800,
                    "everyNthFrame": 1,
                })
            except Exception:
                pass

    def register_screencast_callback(self, cb: Callable[[str, dict, int], None]) -> None:
        """Register callback for screencast frame events."""
        if cb not in self._screencast_callbacks:
            self._screencast_callbacks.append(cb)

    def unregister_screencast_callback(self, cb: Callable[[str, dict, int], None]) -> None:
        """Unregister screencast callback."""
        if cb in self._screencast_callbacks:
            self._screencast_callbacks.remove(cb)

    # ------------------------------------------------------------------
    # Input Forwarding (Mouse, Wheel, Keyboard, Text)
    # ------------------------------------------------------------------

    def dispatch_mouse_event(
        self,
        event_type: str,
        x: int,
        y: int,
        button: str = "left",
        click_count: int = 1,
        delta_x: float = 0.0,
        delta_y: float = 0.0,
    ) -> bool:
        """Dispatch mouse or wheel event via CDP."""
        def _impl():
            if not self._cdp_session:
                return False
            try:
                params: dict[str, Any] = {
                    "type": event_type,
                    "x": int(x),
                    "y": int(y),
                }
                if event_type in ("mousePressed", "mouseReleased"):
                    params["button"] = button
                    params["clickCount"] = click_count
                elif event_type == "mouseMoved":
                    if button and button != "none":
                        params["button"] = button
                elif event_type == "wheel":
                    params["deltaX"] = float(delta_x)
                    params["deltaY"] = float(delta_y)

                self._cdp_session.send("Input.dispatchMouseEvent", params)
                return True
            except Exception as e:
                logger.debug(f"CDP mouse dispatch error: {e}")
                return False
        return bool(self._run_on_pw_thread(_impl, timeout=5.0))

    def dispatch_key_event(
        self,
        event_type: str,
        key: str = "",
        code: str = "",
        text: str = "",
        windows_virtual_key_code: int = 0,
    ) -> bool:
        """Dispatch keyboard key event via CDP."""
        def _impl():
            if not self._cdp_session:
                return False
            try:
                params: dict[str, Any] = {"type": event_type}
                if key:
                    params["key"] = key
                if code:
                    params["code"] = code
                if text:
                    params["text"] = text
                if windows_virtual_key_code:
                    params["windowsVirtualKeyCode"] = int(windows_virtual_key_code)

                self._cdp_session.send("Input.dispatchKeyEvent", params)
                return True
            except Exception as e:
                logger.debug(f"CDP key dispatch error: {e}")
                return False
        return bool(self._run_on_pw_thread(_impl, timeout=5.0))

    def insert_text(self, text: str) -> bool:
        """Insert text string directly into active element via CDP."""
        def _impl():
            if not self._cdp_session:
                return False
            try:
                self._cdp_session.send("Input.insertText", {"text": text})
                return True
            except Exception as e:
                logger.debug(f"CDP insertText error: {e}")
                return False
        return bool(self._run_on_pw_thread(_impl, timeout=5.0))

    # ------------------------------------------------------------------
    # Tab Management & Chrome Navigation
    # ------------------------------------------------------------------

    def _get_tabs_impl(self) -> list[dict[str, Any]]:
        if not self._browser_context:
            return []
        tabs = []
        for i, page in enumerate(self._browser_context.pages):
            try:
                title = page.title() or "New Tab"
                url = page.url or "about:blank"
            except Exception:
                title, url = "Tab", ""
            is_pinned = (i == 0 and "messages.google.com" in url)
            tabs.append({
                "index": i,
                "title": title,
                "url": url,
                "active": (i == self._active_page_idx),
                "pinned": is_pinned,
            })
        return tabs

    def get_browser_tabs(self) -> list[dict[str, Any]]:
        """Return list of open tabs with title, url, active, and pinned flags."""
        res = self._run_on_pw_thread(self._get_tabs_impl, timeout=5.0)
        return res if res is not None else []


    def browser_new_tab(self, url: str = "about:blank") -> dict[str, Any]:
        """Open a new tab in the persistent browser context."""
        def _impl():
            if not self._ensure_browser_impl():
                return {"success": False, "reason": "Browser unavailable"}
            page = self._browser_context.new_page()
            if url and url != "about:blank":
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    logger.debug(f"Tab navigation: {e}")
            self._active_page_idx = len(self._browser_context.pages) - 1
            self._attach_cdp_impl(page)
            return {
                "success": True,
                "index": self._active_page_idx,
                "title": page.title(),
                "url": page.url,
            }
        res = self._run_on_pw_thread(_impl, timeout=20.0)
        return res if res is not None else {"success": False}

    def browser_switch_tab(self, index: int) -> dict[str, Any]:
        """Switch active tab by index."""
        def _impl():
            if not self._browser_context:
                return {"success": False, "reason": "No browser"}
            pages = self._browser_context.pages
            if 0 <= index < len(pages):
                self._active_page_idx = index
                page = pages[index]
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                self._attach_cdp_impl(page)
                return {
                    "success": True,
                    "index": index,
                    "title": page.title(),
                    "url": page.url,
                }
            return {"success": False, "reason": "Index out of range"}
        res = self._run_on_pw_thread(_impl, timeout=5.0)
        return res if res is not None else {"success": False}

    def browser_close_tab(self, index: int) -> dict[str, Any]:
        """Close tab by index."""
        def _impl():
            if not self._browser_context:
                return {"success": False, "reason": "No browser"}
            pages = self._browser_context.pages
            if 0 <= index < len(pages):
                if len(pages) == 1:
                    return {"success": False, "reason": "Cannot close last tab"}
                target_page = pages[index]
                try:
                    target_page.close()
                except Exception as e:
                    logger.debug(f"Close page error: {e}")
                pages = self._browser_context.pages
                new_idx = min(self._active_page_idx, len(pages) - 1)
                self._active_page_idx = new_idx
                self._attach_cdp_impl(pages[new_idx])
                return {"success": True, "index": new_idx}
            return {"success": False, "reason": "Index out of range"}
        res = self._run_on_pw_thread(_impl, timeout=5.0)
        return res if res is not None else {"success": False}

    def browser_navigate(self, url: str) -> dict[str, Any]:
        """Navigate active tab to a URL."""
        def _impl():
            if not self._ensure_browser_impl():
                return {"success": False, "reason": "Browser unavailable"}
            target = (url or "").strip()
            if not target.lower().startswith(("http://", "https://", "data:", "about:")):
                target = "https://" + target
            try:
                self._active_page.goto(target, wait_until="domcontentloaded", timeout=15000)
                return {
                    "success": True,
                    "title": self._active_page.title(),
                    "url": self._active_page.url,
                }
            except Exception as e:
                return {"success": False, "reason": str(e)}
        res = self._run_on_pw_thread(_impl, timeout=20.0)
        return res if res is not None else {"success": False}

    def browser_back(self) -> dict[str, Any]:
        """Navigate back in history."""
        def _impl():
            if not self._active_page:
                return {"success": False, "reason": "No active page"}
            try:
                self._active_page.go_back(timeout=10000)
                return {"success": True, "title": self._active_page.title(), "url": self._active_page.url}
            except Exception as e:
                return {"success": False, "reason": str(e)}
        res = self._run_on_pw_thread(_impl, timeout=10.0)
        return res if res is not None else {"success": False}

    def browser_forward(self) -> dict[str, Any]:
        """Navigate forward in history."""
        def _impl():
            if not self._active_page:
                return {"success": False, "reason": "No active page"}
            try:
                self._active_page.go_forward(timeout=10000)
                return {"success": True, "title": self._active_page.title(), "url": self._active_page.url}
            except Exception as e:
                return {"success": False, "reason": str(e)}
        res = self._run_on_pw_thread(_impl, timeout=10.0)
        return res if res is not None else {"success": False}

    def browser_reload(self) -> dict[str, Any]:
        """Reload active page."""
        def _impl():
            if not self._active_page:
                return {"success": False, "reason": "No active page"}
            try:
                self._active_page.reload(timeout=10000)
                return {"success": True, "title": self._active_page.title(), "url": self._active_page.url}
            except Exception as e:
                return {"success": False, "reason": str(e)}
        res = self._run_on_pw_thread(_impl, timeout=10.0)
        return res if res is not None else {"success": False}

    def restart_browser(self) -> bool:
        """Restart Playwright persistent context and re-attach CDP."""
        def _restart():
            self._close_browser_impl()
            ok = self._ensure_browser_impl()
            if ok and self._screencast_active:
                self._start_screencast_impl()
            return ok
        return bool(self._run_on_pw_thread(_restart, timeout=30.0))

    def get_browser_status(self) -> dict[str, Any]:
        """Return whether ARCHER's browser is open, tabs, and current title."""
        res = self._run_on_pw_thread(self._get_browser_status_impl, timeout=5.0)
        return res if res is not None else {"open": False, "title": "Closed", "tabs": [], "url": ""}

    def _get_browser_status_impl(self) -> dict[str, Any]:
        if self._browser_context is None or self._active_page is None:
            return {"open": False, "title": "Closed", "tabs": [], "url": ""}
        try:
            tabs = self._get_tabs_impl()
            title = self._active_page.title() if self._active_page else ""
            url = self._active_page.url if self._active_page else ""
            return {
                "open": True,
                "title": title or url or "Open",
                "url": url,
                "tabs": tabs,
                "canGoBack": True,
                "canGoForward": True,
            }
        except Exception as e:
            logger.debug(f"Error in _get_browser_status_impl: {e}")
            return {"open": True, "title": "Open", "tabs": [], "url": ""}

    # ------------------------------------------------------------------
    # Agent Tools Compatibility (UniversalToolExecutor)
    # ------------------------------------------------------------------

    def open_url(self, url: str) -> dict[str, Any]:
        """
        Open a URL in ARCHER's browser pane.
        Free navigation under Phase 3.
        """
        if self._check_halt():
            return {"success": False, "reason": "HALT"}
        timeout = 30.0 if self._browser_context is not None else 90.0
        result = self._run_on_pw_thread(self._open_url_impl, url, timeout=timeout)
        if result and result.get("success"):
            self._bus.publish(Event(
                type=EventType.BROWSER_ACTION,
                source="pc_control",
                data={"action": "open_url", "title": result.get("title", ""), "url": url},
            ))
        return result if result is not None else {"success": False, "reason": "Playwright call failed/timed out"}

    def _open_url_impl(self, url: str) -> dict[str, Any]:
        if not self._ensure_browser_impl():
            return {"success": False, "reason": "Browser not available"}
        try:
            target = (url or "").strip()
            if not target.lower().startswith(("http://", "https://", "data:", "about:")):
                target = "https://" + target
            self._active_page.goto(target, wait_until="domcontentloaded", timeout=15000)
            result = {
                "success": True,
                "title": self._active_page.title(),
                "url": self._active_page.url,
            }
            logger.info(f"Opened URL: {target} — Title: '{result['title']}'")
            return result
        except Exception as e:
            logger.error(f"Browser navigation failed: {e}")
            return {"success": False, "reason": str(e)}

    def open_url_in_my_browser(self, url: str) -> dict[str, Any]:
        """
        Open a URL in Col's own default browser outside ARCHER.
        """
        if self._check_halt():
            return {"success": False, "reason": "HALT"}
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            if "://" in url or url.lower().startswith(("file:", "javascript:")):
                return {"success": False, "reason": "Only web (http/https) addresses can be opened."}
            url = "https://" + url
        try:
            import webbrowser
            opened = webbrowser.open(url, new=2)
        except Exception as e:
            logger.error(f"Opening in Col's browser failed: {e}")
            return {"success": False, "reason": str(e)}
        logger.info(f"Opened in Col's own browser: {url}")
        return {"success": bool(opened), "url": url, "where": "Col's own browser (ARCHER can't see or control it)"}

    # The first real video in YouTube's results
    _YOUTUBE_FIRST_VIDEO = ("ytd-video-renderer a#video-title", "a[href^='/watch?v=']")

    def play_youtube(self, query: str) -> dict[str, Any]:
        """Search YouTube for query in ARCHER's browser and play the first video."""
        if self._check_halt():
            return {"success": False, "reason": "HALT"}
        query = " ".join((query or "").split())
        if not query:
            return {"success": False, "reason": "Nothing to search for"}
        timeout = 45.0 if self._browser_context is not None else 105.0
        result = self._run_on_pw_thread(self._play_youtube_impl, query, timeout=timeout)
        if result and result.get("success"):
            self._bus.publish(Event(
                type=EventType.BROWSER_ACTION,
                source="pc_control",
                data={"action": "play_youtube", "title": result.get("playing", ""), "url": result.get("url", "")},
            ))
        return result if result is not None else {"success": False, "reason": "Playwright call failed/timed out"}

    def _play_youtube_impl(self, query: str) -> dict[str, Any]:
        from urllib.parse import quote_plus

        if not self._ensure_browser_impl():
            return {"success": False, "reason": "Browser not available"}
        try:
            page = self._active_page
            page.goto(
                f"https://www.youtube.com/results?search_query={quote_plus(query)}",
                wait_until="domcontentloaded", timeout=20000,
            )
            first = None
            for selector, wait_ms in zip(self._YOUTUBE_FIRST_VIDEO, (12000, 5000)):
                candidate = page.locator(selector).first
                try:
                    candidate.wait_for(state="visible", timeout=wait_ms)
                    first = candidate
                    break
                except Exception:
                    continue
            if first is None:
                return {"success": False, "reason": "no videos found in YouTube's results"}
            title = (first.get_attribute("title") or first.inner_text() or "").strip()
            first.click()
            page.wait_for_url("**/watch**", timeout=15000)
            logger.info(f"Playing on YouTube: '{title}' ({page.url})")
            return {"success": True, "playing": title, "url": page.url}
        except Exception as e:
            logger.error(f"YouTube search/play failed: {e}")
            return {"success": False, "reason": str(e).splitlines()[0]}

    def browser_screenshot(self) -> str | None:
        """Take a screenshot of the active browser page. Read-only."""
        return self._run_on_pw_thread(self._browser_screenshot_impl)

    def _browser_screenshot_impl(self) -> str | None:
        if not self._active_page:
            return None
        try:
            screenshot_bytes = self._active_page.screenshot(timeout=8000)
            return base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"Browser screenshot failed: {e}")
            return None

    def browser_click(self, selector: str) -> bool:
        """Click an element in the browser by CSS selector. Requires confirmation."""
        if self._check_halt():
            return False
        return bool(self._run_on_pw_thread(self._browser_click_impl, selector))

    def _browser_click_impl(self, selector: str) -> bool:
        if not self._active_page:
            return False
        try:
            self._active_page.click(selector, timeout=5000)
            logger.info(f"Browser click: '{selector}'")
            return True
        except Exception as e:
            logger.error(f"Browser click failed: {e}")
            return False

    def browser_type(self, selector: str, text: str) -> bool:
        """Type text into a browser element. Requires confirmation."""
        if self._check_halt():
            return False
        return bool(self._run_on_pw_thread(self._browser_type_impl, selector, text))

    def _browser_type_impl(self, selector: str, text: str) -> bool:
        if not self._active_page:
            return False
        try:
            self._active_page.fill(selector, text, timeout=5000)
            logger.info(f"Browser type into '{selector}': '{text[:50]}'")
            return True
        except Exception as e:
            logger.error(f"Browser type failed: {e}")
            return False

    def browser_get_text(self, selector: str = "body") -> str:
        """Get text content from a browser element. Read-only."""
        result = self._run_on_pw_thread(self._browser_get_text_impl, selector)
        return result if result is not None else ""

    def _browser_get_text_impl(self, selector: str = "body") -> str:
        if not self._active_page:
            return ""
        try:
            return self._active_page.inner_text(selector, timeout=5000)
        except Exception as e:
            logger.error(f"Browser get text failed: {e}")
            return ""

    def close_browser(self) -> None:
        """Close the browser context. Requires confirmation."""
        if self._check_halt():
            return
        self._run_on_pw_thread(self._close_browser_impl)
        self._bus.publish(Event(
            type=EventType.BROWSER_ACTION,
            source="pc_control",
            data={"action": "close", "title": "Closed"},
        ))
        logger.info("Browser closed by user request.")
