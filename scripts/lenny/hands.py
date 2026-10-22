"""
ARCHER Hands Service (Runs on LENNY, Spec Section 11).

Provides remote execution, live video streaming, and automation on LENNY:
1. Live Screen Streaming (~30 FPS, low latency, text sharpness).
2. Mouse & Keyboard control via Win32 SendInput (on LENNY's desktop).
3. UI Automation (inspect control tree, invoke controls).
4. Office COM Automation (Word, Excel, PowerPoint).
5. Physical User Activity Detection (GetLastInputInfo) -> automatic pause & notification.
6. File transfer to/from ARCHER main PC artifacts.
7. Playwright Chromium manager with remote debugging (port 9222).
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
from ctypes import wintypes
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from PIL import Image
import uvicorn

# Constants & Paths
LENNY_DIR = Path("C:/archer_lenny")
ARTIFACTS_DIR = LENNY_DIR / "artifacts"
PROFILE_DIR = LENNY_DIR / "browser_profile"
TOKEN_FILE = LENNY_DIR / "lenny_token.json"

ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Win32 Constants & Structs
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


app = FastAPI(title="ARCHER Hands Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HandsState:
    """Manages Hands service state, security, capture, and automation."""

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

        self.token: str = self._load_or_create_token()
        self.pairing_code: str = self._load_or_create_pairing_code()
        self.status: str = "idle"  # idle, working, paused
        self.current_task: str = ""
        self.takeover_active: bool = False
        self.last_autonomous_action_time: float = 0.0

        self.browser_process: Optional[subprocess.Popen] = None
        self._subscriber_websockets: set[WebSocket] = set()
        self._lock = threading.Lock()

        # Start background safety watchdog for physical user activity
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="HandsWatchdog")
        self._watchdog_thread.start()

    def _load_or_create_token(self) -> str:
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
                return data.get("token", "")
            except Exception:
                pass
        import secrets
        tok = secrets.token_urlsafe(32)
        TOKEN_FILE.write_text(json.dumps({"token": tok, "created_at": time.time()}), encoding="utf-8")
        return tok

    def _load_or_create_pairing_code(self) -> str:
        # 6-digit numeric pairing code
        import secrets
        code = f"{secrets.randbelow(900000) + 100000}"
        return code

    def verify_auth(self, req_token: Optional[str]) -> bool:
        if not self.token:
            return True
        return req_token == self.token

    # -------------------------------------------------------------------------
    # Physical User Takeover Detection (GetLastInputInfo)
    # -------------------------------------------------------------------------

    def _get_idle_ms(self) -> int:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if self.user32.GetLastInputInfo(ctypes.byref(lii)):
            curr_ticks = self.kernel32.GetTickCount()
            return max(0, curr_ticks - lii.dwTime)
        return 999999

    def _watchdog_loop(self) -> None:
        """Monitors physical keyboard & mouse activity on LENNY's console."""
        while True:
            time.sleep(0.3)
            idle_ms = self._get_idle_ms()
            now = time.time()

            # If input happened in last 1.2s and it wasn't triggered by Hands autonomous execution
            if idle_ms < 1200 and (now - self.last_autonomous_action_time > 1.5):
                if not self.takeover_active:
                    with self._lock:
                        self.takeover_active = True
                        if self.status == "working":
                            self.status = "paused"
                    logger.info("[HandsWatchdog] User touched physical controls on LENNY. Takeover active.")
                    self._broadcast_event({
                        "type": "takeover",
                        "active": True,
                        "status": self.status,
                        "task": self.current_task,
                    })
            elif idle_ms > 5000 and self.takeover_active:
                # 5s quiet period -> clear physical takeover flag
                with self._lock:
                    self.takeover_active = False
                logger.info("[HandsWatchdog] Physical controls quiet. User takeover ended.")
                self._broadcast_event({
                    "type": "takeover",
                    "active": False,
                    "status": self.status,
                    "task": self.current_task,
                })

    def _broadcast_event(self, data: dict) -> None:
        payload = json.dumps(data)
        to_remove = set()
        for ws in list(self._subscriber_websockets):
            try:
                asyncio.run_coroutine_threadsafe(ws.send_text(payload), asyncio.get_event_loop())
            except Exception:
                to_remove.add(ws)
        self._subscriber_websockets.difference_update(to_remove)

    # -------------------------------------------------------------------------
    # Desktop Screen Capture
    # -------------------------------------------------------------------------

    def capture_screen_jpeg(self, quality: int = 75, max_width: int = 1280) -> Tuple[bytes, float, int, int]:
        """Capture LENNY desktop and return (jpeg_bytes, capture_ms, width, height)."""
        start_t = time.perf_counter()

        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary display
            sct_img = sct.grab(monitor)
            w, h = sct_img.size
            img = Image.frombytes("RGB", (w, h), sct_img.bgra, "raw", "BGRX")

            if w > max_width:
                aspect = h / w
                new_w = max_width
                new_h = int(new_w * aspect)
                img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
                w, h = new_w, new_h

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            jpeg_bytes = buf.getvalue()

        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        return jpeg_bytes, elapsed_ms, w, h

    # -------------------------------------------------------------------------
    # Win32 SendInput (Mouse & Keyboard on LENNY)
    # -------------------------------------------------------------------------

    def send_mouse_input(self, event_type: str, norm_x: float, norm_y: float, button: str = "left") -> bool:
        """Inject physical mouse input on LENNY using normalized coordinates (0.0 to 1.0)."""
        self.last_autonomous_action_time = time.time()
        screen_w = self.user32.GetSystemMetrics(0)
        screen_h = self.user32.GetSystemMetrics(1)

        # Convert to absolute normalized 0..65535 coordinates for SendInput
        abs_x = int(norm_x * 65535)
        abs_y = int(norm_y * 65535)

        ev = event_type.lower()
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi.dx = abs_x
        inp.u.mi.dy = abs_y
        inp.u.mi.mouseData = 0
        inp.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE

        if ev == "mousemove":
            self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            return True
        elif ev in ("mousedown", "click"):
            flag_down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
            flag_up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP

            inp.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | flag_down
            self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            if ev == "click":
                time.sleep(0.03)
                inp.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | flag_up
                self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            return True
        elif ev == "mouseup":
            flag_up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
            inp.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | flag_up
            self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            return True
        elif ev == "wheel":
            inp.u.mi.dwFlags = MOUSEEVENTF_WHEEL
            inp.u.mi.mouseData = int(norm_y)  # wheel delta
            self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            return True

        return False

    def send_keyboard_input(self, event_type: str, key: str, char_code: Optional[int] = None) -> bool:
        """Inject physical keyboard input on LENNY."""
        self.last_autonomous_action_time = time.time()
        ev = event_type.lower()

        # Direct Unicode character injection
        if char_code and char_code >= 32:
            inp_down = INPUT()
            inp_down.type = INPUT_KEYBOARD
            inp_down.u.ki.wScan = char_code
            inp_down.u.ki.dwFlags = KEYEVENTF_UNICODE
            self.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))

            inp_up = INPUT()
            inp_up.type = INPUT_KEYBOARD
            inp_up.u.ki.wScan = char_code
            inp_up.u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            self.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
            return True

        # Special key mappings
        vk_map = {
            "enter": 0x0D, "return": 0x0D, "backspace": 0x08, "tab": 0x09,
            "space": 0x20, "escape": 0x1B, "arrowleft": 0x25, "arrowup": 0x26,
            "arrowright": 0x27, "arrowdown": 0x28, "delete": 0x2E,
        }
        vk = vk_map.get(key.lower())
        if vk:
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.u.ki.wVk = vk
            inp.u.ki.dwFlags = 0 if ev in ("keydown", "press") else KEYEVENTF_KEYUP
            self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            if ev == "press":
                time.sleep(0.02)
                inp.u.ki.dwFlags = KEYEVENTF_KEYUP
                self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            return True

        if len(key) == 1:
            code = ord(key)
            inp_down = INPUT()
            inp_down.type = INPUT_KEYBOARD
            inp_down.u.ki.wScan = code
            inp_down.u.ki.dwFlags = KEYEVENTF_UNICODE
            self.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))

            inp_up = INPUT()
            inp_up.type = INPUT_KEYBOARD
            inp_up.u.ki.wScan = code
            inp_up.u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            self.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
            return True

        return False

    def send_text_string(self, text: str) -> bool:
        """Inject a sequence of text characters on LENNY."""
        self.last_autonomous_action_time = time.time()
        for ch in text:
            self.send_keyboard_input("press", key=ch, char_code=ord(ch))
        return True

    # -------------------------------------------------------------------------
    # UI Automation (Control Tree Inspection & Invocation)
    # -------------------------------------------------------------------------

    def get_uia_controls(self, window_title: Optional[str] = None, max_depth: int = 4) -> List[Dict[str, Any]]:
        """Inspect and return UI Automation control tree."""
        try:
            import pywinauto
            from pywinauto import Desktop

            d = Desktop(backend="uia")
            if window_title:
                win = d.window(title_re=f".*{window_title}.*")
            else:
                win = d.active()

            controls: List[Dict[str, Any]] = []

            def _traverse(elem, depth):
                if depth > max_depth or len(controls) > 150:
                    return
                try:
                    rect = elem.rectangle()
                    name = elem.element_info.name
                    ctrl_type = elem.element_info.control_type
                    auto_id = elem.element_info.automation_id
                    enabled = elem.is_enabled()

                    if name or auto_id:
                        controls.append({
                            "name": name,
                            "type": ctrl_type,
                            "automation_id": auto_id,
                            "enabled": enabled,
                            "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
                        })
                    for child in elem.children():
                        _traverse(child, depth + 1)
                except Exception:
                    pass

            _traverse(win, 0)
            return controls
        except Exception as e:
            logger.warning(f"[Hands] UIA traversal failed: {e}")
            return []

    def invoke_uia_control(self, name_or_id: str, window_title: Optional[str] = None) -> bool:
        """Locate and invoke a control by name or automation ID."""
        self.last_autonomous_action_time = time.time()
        try:
            import pywinauto
            from pywinauto import Desktop

            d = Desktop(backend="uia")
            win = d.window(title_re=f".*{window_title}.*") if window_title else d.active()

            for elem in win.descendants():
                if elem.element_info.name == name_or_id or elem.element_info.automation_id == name_or_id:
                    try:
                        elem.invoke()
                        return True
                    except Exception:
                        elem.click_input()
                        return True
            return False
        except Exception as e:
            logger.warning(f"[Hands] UIA invoke failed for '{name_or_id}': {e}")
            return False

    # -------------------------------------------------------------------------
    # Office COM Automation (Word, Excel, PowerPoint)
    # -------------------------------------------------------------------------

    def create_word_doc(self, title: str, paragraphs: List[str], filename: str = "document.docx") -> str:
        """Create Word document via native Microsoft Office COM."""
        self.last_autonomous_action_time = time.time()
        out_path = ARTIFACTS_DIR / filename
        try:
            import win32com.client
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = True  # Visible on LENNY's screen so Col/ARCHER sees it
            doc = word.Documents.Add()

            # Add title
            p_title = doc.Paragraphs.Add()
            p_title.Range.Text = title
            p_title.Range.InsertParagraphAfter()

            # Add body paragraphs
            for p_text in paragraphs:
                p = doc.Paragraphs.Add()
                p.Range.Text = p_text
                p.Range.InsertParagraphAfter()

            doc.SaveAs2(str(out_path))
            logger.info(f"[Hands] Word document saved via COM: {out_path}")
            return str(out_path)
        except Exception as e:
            logger.error(f"[Hands] Office Word COM error: {e}")
            raise RuntimeError(f"Word automation error: {e}")

    def create_excel_sheet(self, sheet_name: str, rows: List[List[Any]], filename: str = "sheet.xlsx") -> str:
        """Create Excel spreadsheet with headers, rows, and SUM formula via native COM."""
        self.last_autonomous_action_time = time.time()
        out_path = ARTIFACTS_DIR / filename
        try:
            import win32com.client
            excel = win32com.client.Dispatch("Excel.Application")
            excel.Visible = True
            wb = excel.Workbooks.Add()
            ws = wb.ActiveSheet
            ws.Name = sheet_name[:31]

            for r_idx, row in enumerate(rows, start=1):
                for c_idx, val in enumerate(row, start=1):
                    ws.Cells(r_idx, c_idx).Value = val

            wb.SaveAs(str(out_path))
            logger.info(f"[Hands] Excel spreadsheet saved via COM: {out_path}")
            return str(out_path)
        except Exception as e:
            logger.error(f"[Hands] Office Excel COM error: {e}")
            raise RuntimeError(f"Excel automation error: {e}")

    # -------------------------------------------------------------------------
    # Chromium Browser Management (Port 9222 CDP)
    # -------------------------------------------------------------------------

    def start_browser(self, cdp_port: int = 9222) -> bool:
        """Launch Playwright Chromium on LENNY with remote debugging and clean profile."""
        if self.browser_process and self.browser_process.poll() is None:
            return True

        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        # Check playwright installed browsers
        pw_browser_path = None
        pw_root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        if pw_root.exists():
            for p in pw_root.glob("chromium-*/chrome-win/chrome.exe"):
                if p.exists():
                    pw_browser_path = str(p)
                    break

        exe = pw_browser_path or next((c for c in chrome_candidates if os.path.exists(c)), "chrome.exe")

        cmd = [
            exe,
            f"--remote-debugging-port={cdp_port}",
            "--remote-debugging-address=0.0.0.0",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://messages.google.com/web",  # Pinned Google Messages on Tab 0
        ]
        try:
            self.browser_process = subprocess.Popen(cmd)
            logger.info(f"[Hands] Chromium started on LENNY (PID={self.browser_process.pid}, CDP port={cdp_port})")
            return True
        except Exception as e:
            logger.error(f"[Hands] Failed to launch Chromium: {e}")
            return False

    def stop_browser(self) -> None:
        if self.browser_process:
            try:
                self.browser_process.terminate()
                self.browser_process.wait(timeout=2.0)
            except Exception:
                self.browser_process.kill()
            self.browser_process = None


hands_state = HandsState()


# =============================================================================
# REST Endpoints
# =============================================================================

@app.get("/api/status")
async def get_status(token: Optional[str] = Query(None), x_lenny_token: Optional[str] = Header(None)):
    req_token = token or x_lenny_token
    is_authed = hands_state.verify_auth(req_token)
    return {
        "status": hands_state.status,
        "current_task": hands_state.current_task,
        "takeover_active": hands_state.takeover_active,
        "pairing_required": not is_authed,
        "idle_ms": hands_state._get_idle_ms(),
        "timestamp": time.time(),
    }


@app.post("/api/pair")
async def pair_device(payload: dict):
    code = payload.get("pairing_code", "").strip()
    if code == hands_state.pairing_code:
        return {"status": "paired", "token": hands_state.token}
    raise HTTPException(status_code=401, detail="Invalid pairing code")


@app.post("/api/mouse")
async def inject_mouse(payload: dict, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    ok = hands_state.send_mouse_input(
        event_type=payload.get("event", "click"),
        norm_x=float(payload.get("norm_x", 0.0)),
        norm_y=float(payload.get("norm_y", 0.0)),
        button=payload.get("button", "left"),
    )
    return {"status": "ok" if ok else "failed"}


@app.post("/api/keyboard")
async def inject_keyboard(payload: dict, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if "text" in payload:
        ok = hands_state.send_text_string(payload["text"])
    else:
        ok = hands_state.send_keyboard_input(
            event_type=payload.get("event", "press"),
            key=payload.get("key", ""),
            char_code=payload.get("char_code"),
        )
    return {"status": "ok" if ok else "failed"}


@app.post("/api/uia/controls")
async def get_controls(payload: dict = None, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    title = (payload or {}).get("window_title")
    controls = hands_state.get_uia_controls(window_title=title)
    return {"controls": controls}


@app.post("/api/uia/invoke")
async def invoke_control(payload: dict, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    ok = hands_state.invoke_uia_control(
        name_or_id=payload.get("identifier", ""),
        window_title=payload.get("window_title"),
    )
    return {"status": "invoked" if ok else "failed"}


@app.post("/api/office/create_word")
async def create_word_doc(payload: dict, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    title = payload.get("title", "Untitled Document")
    paragraphs = payload.get("paragraphs", [])
    fname = payload.get("filename", "document.docx")
    out_path = hands_state.create_word_doc(title, paragraphs, fname)
    return {"status": "created", "path": out_path, "filename": fname}


@app.post("/api/office/create_excel")
async def create_excel_sheet(payload: dict, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    sname = payload.get("sheet_name", "Sheet1")
    rows = payload.get("rows", [])
    fname = payload.get("filename", "sheet.xlsx")
    out_path = hands_state.create_excel_sheet(sname, rows, fname)
    return {"status": "created", "path": out_path, "filename": fname}


@app.post("/api/browser/start")
async def start_browser(payload: dict = None, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    port = (payload or {}).get("port", 9222)
    ok = hands_state.start_browser(cdp_port=port)
    return {"status": "running" if ok else "failed", "port": port}


@app.get("/api/screenshot")
async def get_screenshot(x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    from fastapi.responses import Response
    jpeg_bytes, _, _, _ = hands_state.capture_screen_jpeg(quality=80, max_width=1920)
    return Response(content=jpeg_bytes, media_type="image/jpeg")


@app.get("/api/files/download")
async def download_file(filename: str, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    path = ARTIFACTS_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(str(path), filename=filename)
    raise HTTPException(status_code=404, detail=f"File {filename} not found on LENNY")


@app.post("/api/task/set")
async def set_task(payload: dict, x_lenny_token: Optional[str] = Header(None)):
    if not hands_state.verify_auth(x_lenny_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    with hands_state._lock:
        hands_state.current_task = payload.get("task", "")
        hands_state.status = payload.get("status", "working")
    hands_state._broadcast_event({
        "type": "status_changed",
        "status": hands_state.status,
        "task": hands_state.current_task,
    })
    return {"status": hands_state.status, "task": hands_state.current_task}


# =============================================================================
# WebSocket Live Stream & Input Channel (~30 FPS)
# =============================================================================

@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket, token: Optional[str] = Query(None)):
    await websocket.accept()
    if not hands_state.verify_auth(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    logger.info("[Hands] Client connected for live desktop stream")
    active = True

    async def incoming_reader():
        nonlocal active
        try:
            while active:
                data_text = await websocket.receive_text()
                msg = json.loads(data_text)
                mtype = msg.get("type")

                if mtype == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "client_time": msg.get("time"),
                        "server_time": time.time(),
                    }))
                elif mtype == "mouse":
                    hands_state.send_mouse_input(
                        event_type=msg.get("event", "click"),
                        norm_x=float(msg.get("norm_x", 0.0)),
                        norm_y=float(msg.get("norm_y", 0.0)),
                        button=msg.get("button", "left"),
                    )
                elif mtype == "key":
                    hands_state.send_keyboard_input(
                        event_type=msg.get("event", "keydown"),
                        key=msg.get("key", ""),
                        char_code=msg.get("char_code"),
                    )
                elif mtype == "text":
                    hands_state.send_text_string(text=msg.get("text", ""))
        except (WebSocketDisconnect, asyncio.CancelledError):
            active = False
        except Exception as e:
            logger.debug(f"[Hands] Incoming reader error: {e}")
            active = False

    reader_task = asyncio.create_task(incoming_reader())

    try:
        while active:
            loop_start = time.perf_counter()
            jpeg_bytes, cap_ms, w, h = hands_state.capture_screen_jpeg(quality=70, max_width=1280)

            if jpeg_bytes:
                b64_frame = base64.b64encode(jpeg_bytes).decode("ascii")
                payload = json.dumps({
                    "type": "frame",
                    "image": b64_frame,
                    "capture_ms": round(cap_ms, 2),
                    "width": w,
                    "height": h,
                    "status": hands_state.status,
                    "task": hands_state.current_task,
                    "takeover": hands_state.takeover_active,
                    "timestamp": time.time(),
                })
                await websocket.send_text(payload)

            elapsed = time.perf_counter() - loop_start
            # Target ~25-30 FPS (33ms per frame)
            sleep_time = max(0.01, 0.033 - elapsed)
            await asyncio.sleep(sleep_time)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        active = False
        reader_task.cancel()
        logger.info("[Hands] Live stream ended")


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket, token: Optional[str] = Query(None)):
    await websocket.accept()
    if not hands_state.verify_auth(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    hands_state._subscriber_websockets.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        hands_state._subscriber_websockets.discard(websocket)


if __name__ == "__main__":
    port = int(os.environ.get("ARCHER_HANDS_PORT", 8203))
    logger.info(f"[Hands] Starting ARCHER Hands Service on 0.0.0.0:{port}")
    print(f"=====================================================")
    print(f" ARCHER Hands Service Ready on LENNY")
    print(f" Pairing Code: {hands_state.pairing_code}")
    print(f" Token: {hands_state.token[:8]}...")
    print(f" Port: {port}")
    print(f"=====================================================")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
