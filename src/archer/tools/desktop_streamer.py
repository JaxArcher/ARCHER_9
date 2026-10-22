"""
ARCHER Desktop App Streamer (Phase 8 Prototype, Spec Section 11).

Captures Windows desktop application windows (e.g. Notepad, Calculator) and
streams frames over WebSocket/HTTP while providing bi-directional mouse and
keyboard input forwarding into the application pane.

Key Capabilities:
1. Process & HWND Lifecycle: Launch target app, discover top-level and child HWNDs,
   track window bounds and visibility.
2. High-Performance Frame Capture: Uses Win32 PrintWindow with PW_RENDERFULLCONTENT (2)
   and DIB section extraction to grab window pixels without requiring the window to be
   physically in the foreground or occluded.
3. Bi-Directional Input Injection:
   - Direct Win32 Message Posting (WM_CHAR, WM_KEYDOWN, WM_KEYUP, WM_LBUTTONDOWN, WM_LBUTTONUP,
     WM_MOUSEMOVE) directly to the target HWND without moving the user's physical mouse cursor.
   - Optional Foreground SendInput mode to benchmark cursor disruption.
4. Latency & Resource Benchmarks: Tracks capture time, frame size, and memory usage.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import io
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from PIL import Image

# Win32 Constants
PW_RENDERFULLCONTENT = 2

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SETTEXT = 0x000C
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002

SW_RESTORE = 9
SW_SHOW = 5

# BITMAPINFOHEADER struct
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class DesktopAppStreamer:
    """
    Manages the lifecycle, capture, and input forwarding for a Windows desktop application.
    """

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32

        self.process: Optional[subprocess.Popen] = None
        self.target_hwnd: Optional[int] = None
        self.child_edit_hwnd: Optional[int] = None
        self.app_name: str = "notepad.exe"
        self.window_title: str = ""

        self._lock = threading.Lock()
        self._frames_captured: int = 0
        self._total_capture_time_ms: float = 0.0

    # -------------------------------------------------------------------------
    # Launch & Process Management
    # -------------------------------------------------------------------------

    def launch_app(
        self,
        executable: str = "notepad.exe",
        args: Optional[List[str]] = None,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Launch target Windows application and locate its main window HWND.
        """
        with self._lock:
            # Terminate any previously running app instance
            self._cleanup_process()

            self.app_name = executable
            cmd = [executable] + (args or [])

            try:
                self.process = subprocess.Popen(cmd)
            except Exception as e:
                logger.error(f"[DesktopStreamer] Failed to launch {executable}: {e}")
                return {"status": "error", "message": f"Failed to launch {executable}: {e}"}

            logger.info(f"[DesktopStreamer] Launched {executable} (PID={self.process.pid}). Waiting for HWND...")

        # Poll for HWND
        start_t = time.time()
        hwnd = None
        while time.time() - start_t < timeout:
            time.sleep(0.3)
            hwnd = self._find_window_by_pid_or_name(self.process.pid, executable)
            if hwnd:
                break

        if not hwnd:
            logger.warning(f"[DesktopStreamer] Could not find window for {executable} within {timeout}s")
            return {
                "status": "warning",
                "message": f"App launched (PID={self.process.pid}) but window not found yet",
                "pid": self.process.pid,
            }

        with self._lock:
            self.target_hwnd = hwnd
            self._discover_child_controls()
            metrics = self.get_window_metrics()

        logger.info(f"[DesktopStreamer] Bound HWND={hwnd} '{metrics.get('title')}' ({metrics.get('width')}x{metrics.get('height')})")
        return {
            "status": "running",
            "hwnd": hwnd,
            "pid": self.process.pid,
            "metrics": metrics,
        }

    def bind_existing_window(self, title_substring: str) -> Optional[int]:
        """Bind to an already running desktop application by title substring."""
        hwnd = self._find_window_by_title(title_substring)
        if hwnd:
            with self._lock:
                self.target_hwnd = hwnd
                self._discover_child_controls()
            logger.info(f"[DesktopStreamer] Bound existing window HWND={hwnd} for query '{title_substring}'")
            return hwnd
        return None

    def stop_app(self) -> None:
        """Terminate the launched application process and release HWND binding."""
        with self._lock:
            self._cleanup_process()

    def _cleanup_process(self) -> None:
        """Internal cleanup helper."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        self.target_hwnd = None
        self.child_edit_hwnd = None
        self.window_title = ""

    # -------------------------------------------------------------------------
    # Window Discovery Helpers
    # -------------------------------------------------------------------------

    def _find_window_by_pid_or_name(self, pid: int, exe_name: str) -> Optional[int]:
        """Enumerate top-level visible windows matching PID or executable name."""
        found_hwnds: List[int] = []
        clean_name = os.path.basename(exe_name).lower()
        if clean_name.endswith(".exe"):
            clean_name = clean_name[:-4]

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(hwnd, lparam):
            if self.user32.IsWindowVisible(hwnd):
                length = self.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    self.user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value

                    w_pid = wintypes.DWORD()
                    self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))

                    if w_pid.value == pid or clean_name in title.lower():
                        found_hwnds.append(hwnd)
            return True

        self.user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return found_hwnds[0] if found_hwnds else None

    def _find_window_by_title(self, title_substring: str) -> Optional[int]:
        """Find visible window matching title substring."""
        found: List[int] = []
        target = title_substring.lower()
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def enum_cb(hwnd, lparam):
            if self.user32.IsWindowVisible(hwnd):
                length = self.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    self.user32.GetWindowTextW(hwnd, buff, length + 1)
                    if target in buff.value.lower():
                        found.append(hwnd)
                        return False
            return True

        self.user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return found[0] if found else None

    def _discover_child_controls(self) -> None:
        """Find relevant inner edit controls (e.g. RichEditD2DPT or Edit)."""
        if not self.target_hwnd:
            return

        child_list: List[Tuple[int, str]] = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def child_cb(hwnd, lparam):
            cls_buff = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, cls_buff, 256)
            child_list.append((hwnd, cls_buff.value))
            return True

        self.user32.EnumChildWindows(self.target_hwnd, WNDENUMPROC(child_cb), 0)

        for ch_hwnd, cls_name in child_list:
            lower = cls_name.lower()
            if "richedit" in lower or lower == "edit":
                self.child_edit_hwnd = ch_hwnd
                break

    # -------------------------------------------------------------------------
    # Window Metrics
    # -------------------------------------------------------------------------

    def get_window_metrics(self, hwnd: Optional[int] = None) -> Dict[str, Any]:
        """Query window position, size, client rect, title, and minimized state."""
        h = hwnd or self.target_hwnd
        if not h or not self.user32.IsWindow(h):
            return {"valid": False, "hwnd": 0}

        rect = wintypes.RECT()
        self.user32.GetWindowRect(h, ctypes.byref(rect))
        client_rect = wintypes.RECT()
        self.user32.GetClientRect(h, ctypes.byref(client_rect))

        length = self.user32.GetWindowTextLengthW(h)
        title_buf = ctypes.create_unicode_buffer(length + 1) if length > 0 else ctypes.create_unicode_buffer(1)
        if length > 0:
            self.user32.GetWindowTextW(h, title_buf, length + 1)

        is_iconic = bool(self.user32.IsIconic(h))
        is_visible = bool(self.user32.IsWindowVisible(h))

        w = rect.right - rect.left
        height = rect.bottom - rect.top

        return {
            "valid": True,
            "hwnd": h,
            "title": title_buf.value,
            "width": max(1, w),
            "height": max(1, height),
            "client_width": max(1, client_rect.right - client_rect.left),
            "client_height": max(1, client_rect.bottom - client_rect.top),
            "x": rect.left,
            "y": rect.top,
            "is_minimized": is_iconic,
            "is_visible": is_visible,
        }

    # -------------------------------------------------------------------------
    # Frame Capture (Win32 PrintWindow with PW_RENDERFULLCONTENT)
    # -------------------------------------------------------------------------

    def capture_frame(
        self,
        hwnd: Optional[int] = None,
        quality: int = 75,
        max_width: int = 1280,
    ) -> Tuple[Optional[bytes], float, Dict[str, Any]]:
        """
        Capture the window contents into a compressed JPEG image buffer.
        Returns: (jpeg_bytes, capture_time_ms, metrics)
        """
        target = hwnd or self.target_hwnd
        if not target or not self.user32.IsWindow(target):
            return None, 0.0, {"valid": False}

        start_time = time.perf_counter()

        # If window is minimized, restore it
        if self.user32.IsIconic(target):
            self.user32.ShowWindow(target, SW_RESTORE)

        rect = wintypes.RECT()
        self.user32.GetWindowRect(target, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top

        if w <= 0 or h <= 0:
            return None, 0.0, {"valid": False}

        # Setup GDI device contexts
        hdc_screen = self.user32.GetDC(target)
        hdc_mem = self.gdi32.CreateCompatibleDC(hdc_screen)
        hbmp = self.gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        old_bmp = self.gdi32.SelectObject(hdc_mem, hbmp)

        # PW_RENDERFULLCONTENT (2) renders DirectComposition and complex controls
        res = self.user32.PrintWindow(target, hdc_mem, PW_RENDERFULLCONTENT)
        if not res:
            # Fallback to standard PrintWindow (0)
            self.user32.PrintWindow(target, hdc_mem, 0)

        # Extract DIB bits
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down bitmap
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf = ctypes.create_string_buffer(w * h * 4)
        self.gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)

        # Cleanup GDI handles
        self.gdi32.SelectObject(hdc_mem, old_bmp)
        self.gdi32.DeleteObject(hbmp)
        self.gdi32.DeleteDC(hdc_mem)
        self.user32.ReleaseDC(target, hdc_screen)

        # Create PIL Image
        try:
            img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
            img_rgb = img.convert("RGB")

            # Optional downscaling if window is very large
            if w > max_width:
                aspect = h / w
                new_w = max_width
                new_h = int(new_w * aspect)
                img_rgb = img_rgb.resize((new_w, new_h), Image.Resampling.BILINEAR)

            out_io = io.BytesIO()
            img_rgb.save(out_io, format="JPEG", quality=quality, optimize=True)
            jpeg_bytes = out_io.getvalue()
        except Exception as e:
            logger.error(f"[DesktopStreamer] Image processing error: {e}")
            return None, 0.0, {"valid": False, "error": str(e)}

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        with self._lock:
            self._frames_captured += 1
            self._total_capture_time_ms += elapsed_ms

        metrics = {
            "valid": True,
            "width": w,
            "height": h,
            "capture_ms": round(elapsed_ms, 2),
            "size_bytes": len(jpeg_bytes),
        }
        return jpeg_bytes, elapsed_ms, metrics

    # -------------------------------------------------------------------------
    # Bi-Directional Input Injection (Direct Win32 Messages)
    # -------------------------------------------------------------------------

    def inject_mouse(
        self,
        event_type: str,
        norm_x: float,
        norm_y: float,
        button: str = "left",
        hwnd: Optional[int] = None,
    ) -> bool:
        """
        Inject mouse click/move at normalized window coordinates (0.0 to 1.0).
        Uses Win32 PostMessage directly to target window, avoiding physical cursor disruption.
        """
        target = hwnd or self.target_hwnd
        if not target or not self.user32.IsWindow(target):
            return False

        rect = wintypes.RECT()
        self.user32.GetWindowRect(target, ctypes.byref(rect))
        w = max(1, rect.right - rect.left)
        h = max(1, rect.bottom - rect.top)

        pixel_x = int(norm_x * w)
        pixel_y = int(norm_y * h)
        lparam = (pixel_y << 16) | (pixel_x & 0xFFFF)

        ev = event_type.lower()
        if ev == "mousemove":
            self.user32.PostMessageW(target, WM_MOUSEMOVE, 0, lparam)
            return True
        elif ev in ("mousedown", "click"):
            msg_down = WM_LBUTTONDOWN if button == "left" else WM_RBUTTONDOWN
            msg_up = WM_LBUTTONUP if button == "left" else WM_RBUTTONUP
            flags = MK_LBUTTON if button == "left" else MK_RBUTTON

            self.user32.PostMessageW(target, WM_MOUSEMOVE, 0, lparam)
            self.user32.PostMessageW(target, msg_down, flags, lparam)
            if ev == "click":
                time.sleep(0.02)
                self.user32.PostMessageW(target, msg_up, 0, lparam)
            return True
        elif ev == "mouseup":
            msg_up = WM_LBUTTONUP if button == "left" else WM_RBUTTONUP
            self.user32.PostMessageW(target, msg_up, 0, lparam)
            return True
        elif ev == "wheel":
            # delta in wParam high word
            wparam = (120 << 16) if norm_y > 0 else ((-120 & 0xFFFF) << 16)
            self.user32.PostMessageW(target, WM_MOUSEWHEEL, wparam, lparam)
            return True

        return False

    def inject_key(
        self,
        event_type: str,
        key: str,
        char_code: Optional[int] = None,
        hwnd: Optional[int] = None,
    ) -> bool:
        """
        Inject keyboard event (keydown, keyup, char) directly into target window.
        """
        target = hwnd or self.child_edit_hwnd or self.target_hwnd
        if not target or not self.user32.IsWindow(target):
            return False

        ev = event_type.lower()

        # Handle direct text character
        if char_code and char_code >= 32:
            self.user32.SendMessageW(target, WM_CHAR, char_code, 0)
            return True

        # Handle special keys
        vkey_map = {
            "enter": 0x0D,
            "return": 0x0D,
            "backspace": 0x08,
            "tab": 0x09,
            "space": 0x20,
            "escape": 0x1B,
            "arrowleft": 0x25,
            "arrowup": 0x26,
            "arrowright": 0x27,
            "arrowdown": 0x28,
            "delete": 0x2E,
        }
        vk = vkey_map.get(key.lower())

        if vk:
            if ev in ("keydown", "press"):
                self.user32.SendMessageW(target, WM_KEYDOWN, vk, 0)
                if vk == 0x0D:
                    self.user32.SendMessageW(target, WM_CHAR, 0x0D, 0)
                elif vk == 0x08:
                    self.user32.SendMessageW(target, WM_CHAR, 0x08, 0)
            elif ev == "keyup":
                self.user32.SendMessageW(target, WM_KEYUP, vk, 0)
            return True

        # Single printable character fallback
        if len(key) == 1:
            code = ord(key)
            self.user32.SendMessageW(target, WM_CHAR, code, 0)
            return True

        return False

    def inject_text(self, text: str, hwnd: Optional[int] = None) -> bool:
        """
        Send a full text string directly to the target edit control via WM_SETTEXT
        or character sequence.
        """
        target = hwnd or self.child_edit_hwnd or self.target_hwnd
        if not target or not self.user32.IsWindow(target):
            return False

        # If child edit control exists, WM_SETTEXT is instant
        if self.child_edit_hwnd and target == self.child_edit_hwnd:
            self.user32.SendMessageW(target, WM_SETTEXT, 0, text)
            return True

        # Otherwise send sequence of WM_CHAR
        for ch in text:
            self.user32.SendMessageW(target, WM_CHAR, ord(ch), 0)
        return True

    # -------------------------------------------------------------------------
    # Performance & Diagnostics
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return diagnostic metrics on frame rate and capture latency."""
        with self._lock:
            count = self._frames_captured
            total_ms = self._total_capture_time_ms
            avg_ms = (total_ms / count) if count > 0 else 0.0

        metrics = self.get_window_metrics()
        return {
            "app_name": self.app_name,
            "target_hwnd": self.target_hwnd,
            "window_title": metrics.get("title", ""),
            "window_width": metrics.get("width", 0),
            "window_height": metrics.get("height", 0),
            "frames_captured": count,
            "avg_capture_ms": round(avg_ms, 2),
            "est_max_fps": round(1000.0 / avg_ms, 1) if avg_ms > 0 else 0.0,
        }


# Singleton accessor
_streamer_instance: Optional[DesktopAppStreamer] = None

def get_desktop_streamer() -> DesktopAppStreamer:
    global _streamer_instance
    if _streamer_instance is None:
        _streamer_instance = DesktopAppStreamer()
    return _streamer_instance
