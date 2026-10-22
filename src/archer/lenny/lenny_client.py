"""
ARCHER LENNY Client (Phase 8, Spec Section 11).

Client for communicating with ARCHER Hands service running on LENNY:
- Pairing & authentication
- Status & physical user takeover detection
- Input forwarding (mouse, keyboard, text)
- UI Automation control queries & invocation
- Microsoft Office COM automation (Word, Excel, PowerPoint)
- Artifact download/sync to ARCHER's data/artifacts
- Remote Playwright browser process management
"""

from __future__ import annotations

import datetime
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store


class LennyClient:
    """Manages the network connection and execution bridge to LENNY."""

    _instance: Optional[LennyClient] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._cfg = get_config()
        self._store = get_sqlite_store()
        self._bus = get_event_bus()

        self._repo_root = Path(__file__).resolve().parents[3]
        self._artifacts_dir = self._repo_root / "data" / "artifacts"
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

        self._host: str = ""
        self._port: int = 8203
        self._token: str = ""
        self._browser_port: int = 9222
        self._status: str = "unpaired"
        self._current_task: str = ""
        self._takeover_active: bool = False
        self._last_status_check: float = 0.0

        self._load_config()

    def _load_config(self) -> None:
        """Load connection config from sqlite store, falling back to ArcherConfig."""
        try:
            db_cfg = self._store.get_lenny_config()
            self._host = db_cfg.get("host") or self._cfg.lenny_host
            self._port = db_cfg.get("port") or self._cfg.lenny_port or 8203
            self._token = db_cfg.get("token") or self._cfg.lenny_token
            self._browser_port = db_cfg.get("browser_port") or self._cfg.lenny_browser_port or 9222
            self._status = db_cfg.get("status", "unpaired")
        except Exception as e:
            logger.warning(f"[LennyClient] Failed loading config from store: {e}")
            self._host = self._cfg.lenny_host
            self._port = self._cfg.lenny_port or 8203
            self._token = self._cfg.lenny_token
            self._browser_port = self._cfg.lenny_browser_port or 9222

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str:
        return self._token

    @property
    def browser_port(self) -> int:
        return self._browser_port

    @property
    def status(self) -> str:
        return self._status

    @property
    def current_task(self) -> str:
        return self._current_task

    @property
    def takeover_active(self) -> bool:
        return self._takeover_active

    def is_configured(self) -> bool:
        """Return True if LENNY host and token are set."""
        return bool(self._host and self._token)

    def get_base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def get_stream_ws_url(self) -> str:
        """Return the direct WebSocket URL to LENNY's live screen stream."""
        return f"ws://{self._host}:{self._port}/ws/stream?token={self._token}"

    def get_headers(self) -> Dict[str, str]:
        headers = {}
        if self._token:
            headers["X-Lenny-Token"] = self._token
        return headers

    # -------------------------------------------------------------------------
    # Network Status & Pairing
    # -------------------------------------------------------------------------

    def is_online(self, timeout: float = 1.5) -> bool:
        """Check if LENNY is reachable over the local network."""
        if not self._host:
            return False
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(f"{self.get_base_url()}/api/status", headers=self.get_headers())
                return resp.status_code in (200, 401)
        except Exception:
            return False

    def get_status(self, timeout: float = 2.0) -> Dict[str, Any]:
        """Fetch status from LENNY and update local state and database."""
        if not self._host:
            return {
                "configured": False,
                "online": False,
                "status": "unconfigured",
                "current_task": "",
                "takeover_active": False,
            }

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(f"{self.get_base_url()}/api/status", headers=self.get_headers())
                if resp.status_code == 200:
                    data = resp.json()
                    new_status = data.get("status", "idle")
                    new_task = data.get("current_task", "")
                    new_takeover = bool(data.get("takeover_active", False))

                    prev_takeover = self._takeover_active
                    prev_status = self._status

                    self._status = new_status
                    self._current_task = new_task
                    self._takeover_active = new_takeover
                    self._last_status_check = time.time()

                    # Update DB heartbeat
                    try:
                        self._store.touch_lenny_heartbeat(status=new_status)
                    except Exception:
                        pass

                    # Fire takeover events if state changed
                    if new_takeover and not prev_takeover:
                        self._bus.publish(Event(
                            type=EventType.LENNY_TAKEOVER_START,
                            data={"task": new_task, "status": new_status, "host": self._host},
                        ))
                    elif not new_takeover and prev_takeover:
                        self._bus.publish(Event(
                            type=EventType.LENNY_TAKEOVER_END,
                            data={"task": new_task, "status": new_status, "host": self._host},
                        ))

                    if new_status != prev_status:
                        self._bus.publish(Event(
                            type=EventType.LENNY_STATUS_CHANGED,
                            data={"status": new_status, "task": new_task, "host": self._host},
                        ))

                    return {
                        "configured": self.is_configured(),
                        "online": True,
                        "status": new_status,
                        "current_task": new_task,
                        "takeover_active": new_takeover,
                        "idle_ms": data.get("idle_ms", 0),
                        "pairing_required": data.get("pairing_required", False),
                        "host": self._host,
                        "port": self._port,
                        "browser_port": self._browser_port,
                    }
                elif resp.status_code == 401:
                    return {
                        "configured": self.is_configured(),
                        "online": True,
                        "status": "unauthorized",
                        "pairing_required": True,
                        "host": self._host,
                    }
        except Exception as e:
            logger.debug(f"[LennyClient] Status check failed: {e}")

        return {
            "configured": self.is_configured(),
            "online": False,
            "status": "offline",
            "current_task": self._current_task,
            "takeover_active": False,
            "host": self._host,
        }

    def pair(self, pairing_code: str, host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
        """Pair with LENNY using the 6-digit code shown on LENNY's console."""
        target_host = host or self._host
        target_port = port or self._port or 8203

        if not target_host:
            raise ValueError("LENNY host IP must be specified for pairing")

        url = f"http://{target_host}:{target_port}/api/pair"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, json={"pairing_code": pairing_code.strip()})
                if resp.status_code == 200:
                    data = resp.json()
                    tok = data.get("token")
                    if not tok:
                        raise ValueError("Pairing succeeded but no token received")

                    self._host = target_host
                    self._port = target_port
                    self._token = tok
                    self._status = "paired"

                    # Save in database
                    self._store.update_lenny_config(
                        host=target_host,
                        port=target_port,
                        token=tok,
                        status="paired",
                    )

                    self._bus.publish(Event(
                        type=EventType.LENNY_STATUS_CHANGED,
                        data={"status": "paired", "host": target_host, "port": target_port},
                    ))
                    logger.info(f"[LennyClient] Successfully paired with LENNY at {target_host}:{target_port}")
                    return {"status": "paired", "host": target_host, "port": target_port}
                else:
                    raise ValueError(f"Pairing failed with status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[LennyClient] Pairing error: {e}")
            raise

    # -------------------------------------------------------------------------
    # Mouse & Keyboard Actions
    # -------------------------------------------------------------------------

    def send_mouse(self, event: str, norm_x: float, norm_y: float, button: str = "left") -> bool:
        """Send mouse event to LENNY via Hands service."""
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/mouse",
                    json={"event": event, "norm_x": norm_x, "norm_y": norm_y, "button": button},
                    headers=self.get_headers(),
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"[LennyClient] send_mouse failed: {e}")
            return False

    def send_keyboard(
        self,
        event: str = "press",
        key: str = "",
        char_code: Optional[int] = None,
        text: Optional[str] = None,
    ) -> bool:
        """Send keyboard or text string event to LENNY via Hands service."""
        payload: Dict[str, Any] = {"event": event}
        if text is not None:
            payload["text"] = text
        else:
            payload["key"] = key
            if char_code is not None:
                payload["char_code"] = char_code

        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/keyboard",
                    json=payload,
                    headers=self.get_headers(),
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"[LennyClient] send_keyboard failed: {e}")
            return False

    # -------------------------------------------------------------------------
    # UI Automation
    # -------------------------------------------------------------------------

    def get_uia_controls(self, window_title: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve UI Automation control tree from LENNY."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/uia/controls",
                    json={"window_title": window_title},
                    headers=self.get_headers(),
                )
                if resp.status_code == 200:
                    return resp.json().get("controls", [])
        except Exception as e:
            logger.error(f"[LennyClient] get_uia_controls failed: {e}")
        return []

    def invoke_uia_control(self, identifier: str, window_title: Optional[str] = None) -> bool:
        """Invoke or click a UI control identified by name or automation ID."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/uia/invoke",
                    json={"identifier": identifier, "window_title": window_title},
                    headers=self.get_headers(),
                )
                return resp.status_code == 200 and resp.json().get("status") == "invoked"
        except Exception as e:
            logger.error(f"[LennyClient] invoke_uia_control failed: {e}")
            return False

    # -------------------------------------------------------------------------
    # Microsoft Office COM Automation
    # -------------------------------------------------------------------------

    def create_word_document(
        self,
        title: str,
        paragraphs: Any,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Word document via Office COM on LENNY and pull to ARCHER artifacts."""
        if not filename or not filename.strip():
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"LennyWord_{ts}.docx"

        if isinstance(paragraphs, str):
            # Split lines or treat as single paragraph
            lines = [p.strip() for p in paragraphs.split("\n") if p.strip()]
            para_list = lines if lines else [paragraphs]
        elif isinstance(paragraphs, list):
            para_list = [str(p) for p in paragraphs]
        else:
            para_list = [str(paragraphs)]

        self.set_task(f"Creating Word document '{filename}'", status="working")

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/office/create_word",
                    json={"title": title, "paragraphs": para_list, "filename": filename},
                    headers=self.get_headers(),
                )
                if resp.status_code == 200:
                    # File created on LENNY; now download artifact to Main PC
                    local_path = self.download_artifact(filename)
                    self.set_task("", status="idle")
                    return {
                        "status": "created",
                        "filename": filename,
                        "path": str(local_path),
                        "created_on": "LENNY",
                    }
                else:
                    raise RuntimeError(f"Word creation failed on LENNY: {resp.text}")
        except Exception as e:
            self.set_task("", status="idle")
            logger.error(f"[LennyClient] create_word_document error: {e}")
            raise

    def create_excel_sheet(
        self,
        sheet_name: str,
        rows: Any,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Excel sheet via Office COM on LENNY and pull to ARCHER artifacts."""
        if not filename or not filename.strip():
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"LennySheet_{ts}.xlsx"

        import json
        if isinstance(rows, str):
            try:
                parsed_rows = json.loads(rows)
            except Exception:
                parsed_rows = [[cell.strip() for cell in line.split(",")] for line in rows.split("\n") if line.strip()]
        elif isinstance(rows, list):
            parsed_rows = rows
        else:
            parsed_rows = [[str(rows)]]

        self.set_task(f"Creating Excel sheet '{filename}'", status="working")

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/office/create_excel",
                    json={"sheet_name": sheet_name, "rows": parsed_rows, "filename": filename},
                    headers=self.get_headers(),
                )
                if resp.status_code == 200:
                    local_path = self.download_artifact(filename)
                    self.set_task("", status="idle")
                    return {
                        "status": "created",
                        "filename": filename,
                        "path": str(local_path),
                        "created_on": "LENNY",
                    }
                else:
                    raise RuntimeError(f"Excel creation failed on LENNY: {resp.text}")
        except Exception as e:
            self.set_task("", status="idle")
            logger.error(f"[LennyClient] create_excel_sheet error: {e}")
            raise

    def open_app(self, name: str) -> Dict[str, Any]:
        """Launch an application on LENNY."""
        self.set_task(f"Opening {name}", status="working")
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/app/open",
                    json={"name": name},
                    headers=self.get_headers(),
                )
                if resp.status_code == 200:
                    self.set_task("", status="idle")
                    return resp.json()
                raise RuntimeError(f"Open app failed on LENNY: {resp.text}")
        except Exception as e:
            self.set_task("", status="idle")
            logger.error(f"[LennyClient] open_app error: {e}")
            raise

    def describe_screen(self, focus_area: Optional[str] = None) -> str:
        """Capture screenshot from LENNY and describe it using local VLM on Main PC."""
        self.set_task("Inspecting LENNY screen", status="working")
        try:
            screenshot_bytes = self.get_screenshot()
            import base64
            b64_img = base64.b64encode(screenshot_bytes).decode("ascii")

            ollama_url = f"{self._cfg.ollama_base_url}/api/generate"
            prompt = (
                "You are an assistant viewing the desktop screen of LENNY, ARCHER's dedicated PC. "
                "Describe concisely in 2-3 plain sentences what is currently visible on the screen, "
                "including any open applications, windows, or documents."
            )
            if focus_area:
                prompt += f" Pay special attention to {focus_area}."

            payload = {
                "model": "qwen2.5vl:7b",
                "prompt": prompt,
                "images": [b64_img],
                "stream": False,
                "keep_alive": 0,
            }

            with httpx.Client(timeout=45.0) as client:
                resp = client.post(ollama_url, json=payload)
                if resp.status_code == 200:
                    res_text = resp.json().get("response", "").strip()
                    self.set_task("", status="idle")
                    return res_text
                else:
                    self.set_task("", status="idle")
                    return f"VLM returned status {resp.status_code}"
        except Exception as e:
            self.set_task("", status="idle")
            logger.warning(f"[LennyClient] describe_screen error: {e}")
            return f"Could not describe screen: {e}"

    # -------------------------------------------------------------------------
    # File Synchronization & Artifacts
    # -------------------------------------------------------------------------

    def download_artifact(self, filename: str, local_dest: Optional[Path] = None) -> Path:
        """Download generated file from LENNY artifacts to Main PC data/artifacts."""
        dest = local_dest or (self._artifacts_dir / filename)
        url = f"{self.get_base_url()}/api/files/download"
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(url, params={"filename": filename}, headers=self.get_headers())
                if resp.status_code == 200:
                    dest.write_bytes(resp.content)
                    logger.info(f"[LennyClient] Downloaded artifact {filename} -> {dest}")
                    return dest
                raise FileNotFoundError(f"Failed to download {filename} from LENNY: {resp.status_code}")
        except Exception as e:
            logger.error(f"[LennyClient] download_artifact error: {e}")
            raise

    def get_screenshot(self) -> bytes:
        """Fetch a single JPEG screenshot frame from LENNY."""
        url = f"{self.get_base_url()}/api/screenshot"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, headers=self.get_headers())
                if resp.status_code == 200:
                    return resp.content
                raise RuntimeError(f"Screenshot failed on LENNY with code {resp.status_code}")
        except Exception as e:
            logger.error(f"[LennyClient] get_screenshot error: {e}")
            raise

    # -------------------------------------------------------------------------
    # Task & Browser Management
    # -------------------------------------------------------------------------

    def set_task(self, task: str, status: str = "working") -> Dict[str, Any]:
        """Update active task and state on LENNY."""
        self._current_task = task
        self._status = status
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/task/set",
                    json={"task": task, "status": status},
                    headers=self.get_headers(),
                )
                if resp.status_code == 200:
                    res = resp.json()
                    self._bus.publish(Event(
                        type=EventType.LENNY_TASK_PROGRESS,
                        data={"task": task, "status": status, "host": self._host},
                    ))
                    return res
        except Exception as e:
            logger.debug(f"[LennyClient] set_task network warning: {e}")

        return {"task": task, "status": status}

    def start_browser(self, port: Optional[int] = None) -> bool:
        """Request Hands on LENNY to start Chromium with remote CDP debugging."""
        cdp_port = port or self._browser_port or 9222
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{self.get_base_url()}/api/browser/start",
                    json={"port": cdp_port},
                    headers=self.get_headers(),
                )
                return resp.status_code == 200 and resp.json().get("status") == "running"
        except Exception as e:
            logger.error(f"[LennyClient] start_browser failed: {e}")
            return False


def get_lenny_client() -> LennyClient:
    """Return singleton LennyClient instance."""
    if LennyClient._instance is None:
        with LennyClient._lock:
            if LennyClient._instance is None:
                LennyClient._instance = LennyClient()
    return LennyClient._instance
