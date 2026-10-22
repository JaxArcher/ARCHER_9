"""
ARCHER iPad Air Gateway Server (Phase 7c / Spec Section 10c).

Runs on a dedicated port on the home network (default: 0.0.0.0:8201).
Strict Security & Capability Isolation:
- Only serves the Safari 12 compatible iPad Air web application.
- Enforces one-time 6-digit numeric pairing code and persistent cryptographic token.
- Allowed surfaces: Chat with ARCHER, Spoken audio replies (Kokoro TTS),
  Away & Tasks ("While You Were Away" + tasks checklist),
  "Where's my..." item locations and photos, and Touch-friendly Approval Prompts (Approve/Deny).
- Strictly BLOCKED and never exposed to the iPad network:
  Camera streams, raw logs, transcripts, file browser, terminal, browser screencast,
  or system configuration.
- Any unpaired request receives 401 Unauthorized.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Query, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from archer.config import get_config
from archer.core.approvals import get_approval_manager
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store

logger = logging.getLogger("archer-ipad-server")

ipad_app = FastAPI(title="ARCHER iPad Air Gateway", version="1.0.0")

ipad_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_IPAD_DIR = Path(__file__).resolve().parents[2] / "web" / "ipad"
_ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "data" / "artifacts"
_ITEMS_DIR = Path(__file__).resolve().parents[2] / "data" / "items"

# WebSocket clients connected to iPad gateway
_ipad_ws_clients: Set[WebSocket] = set()
_ipad_ws_clients_lock = threading.Lock()
_ipad_loop: Optional[asyncio.AbstractEventLoop] = None

# In-memory recent chat history buffer for newly pairing / reconnecting iPad clients
_ipad_chat_history: List[Dict[str, Any]] = []
_ipad_chat_lock = threading.Lock()
MAX_CHAT_HISTORY = 100


def get_local_lan_ip() -> str:
    """Find the host's primary IPv4 address on the local home network."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _record_chat(role: str, text: str, agent: str = "assistant") -> None:
    """Record a chat message into the shared recent buffer."""
    with _ipad_chat_lock:
        _ipad_chat_history.append({
            "id": f"msg_{int(time.time()*1000)}_{len(_ipad_chat_history)}",
            "role": role,
            "text": text,
            "agent": agent,
            "timestamp": time.time(),
        })
        if len(_ipad_chat_history) > MAX_CHAT_HISTORY:
            _ipad_chat_history.pop(0)


async def _ws_send_safe(ws: WebSocket, text: str) -> None:
    """Send text frame over WebSocket safely."""
    try:
        await ws.send_text(text)
    except Exception as e:
        logger.debug(f"[iPadWS] send_text failed: {e}")


def _broadcast_ipad_ws(msg: Dict[str, Any]) -> None:
    """Broadcast JSON message to all connected iPad WebSockets."""
    raw = json.dumps(msg)
    with _ipad_ws_clients_lock:
        clients = list(_ipad_ws_clients)
    for ws in clients:
        if _ipad_loop and _ipad_loop.is_running():
            asyncio.run_coroutine_threadsafe(_ws_send_safe(ws, raw), _ipad_loop)


def disconnect_all_ipad_clients() -> None:
    """Disconnect all active iPad clients (e.g. upon token revocation)."""
    with _ipad_ws_clients_lock:
        clients = list(_ipad_ws_clients)
    for ws in clients:
        if _ipad_loop and _ipad_loop.is_running():
            asyncio.run_coroutine_threadsafe(ws.close(code=4401, reason="Pairing revoked"), _ipad_loop)


# --- Event Bus Bridge for iPad Gateway ---
_bridge_registered = False

def _register_ipad_event_bridge() -> None:
    """Subscribe to EventBus to forward relevant real-time events to the iPad."""
    global _bridge_registered
    if _bridge_registered:
        return
    _bridge_registered = True
    bus = get_event_bus()

    # Chat / Speech responses
    def _on_stt_final(e: Event):
        text = e.data.get("text", "").strip()
        if text:
            _record_chat("user", text)
            _broadcast_ipad_ws({"type": "chat_message", "role": "user", "text": text})

    def _on_agent_response(e: Event):
        text = e.data.get("text", "").strip()
        agent = e.data.get("agent", "assistant")
        if text:
            _record_chat("assistant", text, agent=agent)
            _broadcast_ipad_ws({"type": "chat_message", "role": "assistant", "text": text, "agent": agent})

    # Approval events
    def _on_approval_requested(e: Event):
        data = e.data
        _broadcast_ipad_ws({
            "type": "approval_request",
            "request_id": data.get("request_id"),
            "tool_name": data.get("tool_name"),
            "action_type": data.get("action_type"),
            "description": data.get("description"),
            "details": data.get("details"),
            "timeout_seconds": data.get("timeout_seconds", 30),
        })

    def _on_approval_resolved(e: Event):
        data = e.data
        _broadcast_ipad_ws({
            "type": "approval_resolved",
            "request_id": data.get("request_id"),
            "decision": data.get("decision"),
        })

    # Tasks / Habits changed
    def _on_tasks_changed(e: Event):
        store = get_sqlite_store()
        _broadcast_ipad_ws({
            "type": "tasks_updated",
            "tasks": store.get_tasks(),
            "habits": store.get_habits(),
        })

    bus.subscribe(EventType.STT_FINAL, _on_stt_final)
    bus.subscribe(EventType.AGENT_RESPONSE_END, _on_agent_response)
    bus.subscribe(EventType.APPROVAL_REQUESTED, _on_approval_requested)
    bus.subscribe(EventType.APPROVAL_RESOLVED, _on_approval_resolved)
    bus.subscribe(EventType.TASKS_CHANGED, _on_tasks_changed)


_register_ipad_event_bridge()


# --- Authentication Dependency ---

def get_auth_token(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> str:
    """Extract and validate bearer token for iPad API endpoints."""
    tok = None
    if authorization and authorization.lower().startswith("bearer "):
        tok = authorization[7:].strip()
    elif token:
        tok = token.strip()

    if not tok or not get_sqlite_store().validate_device_token(tok, device_type="ipad"):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: iPad is not paired or pairing has been revoked by PC.",
        )
    return tok


# --- Static Asset Endpoints ---

@ipad_app.get("/")
@ipad_app.get("/ipad")
async def serve_ipad_page():
    """Serve the Safari 12 compatible iPad Air HTML page."""
    index_file = _IPAD_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="iPad index.html not found")
    return FileResponse(str(index_file), media_type="text/html")


@ipad_app.get("/ipad/style.css")
async def serve_ipad_css():
    """Serve the iPad stylesheet."""
    css_file = _IPAD_DIR / "style.css"
    if not css_file.exists():
        raise HTTPException(status_code=404, detail="style.css not found")
    return FileResponse(str(css_file), media_type="text/css")


@ipad_app.get("/ipad/app.js")
async def serve_ipad_js():
    """Serve the Safari 12 compatible JavaScript application."""
    js_file = _IPAD_DIR / "app.js"
    if not js_file.exists():
        raise HTTPException(status_code=404, detail="app.js not found")
    return FileResponse(str(js_file), media_type="application/javascript")


@ipad_app.get("/ipad/icon.png")
@ipad_app.get("/apple-touch-icon.png")
async def serve_ipad_icon():
    """Serve the Apple touch icon for Add to Home Screen."""
    icon_file = _IPAD_DIR / "icon.png"
    if not icon_file.exists():
        raise HTTPException(status_code=404, detail="icon.png not found")
    return FileResponse(str(icon_file), media_type="image/png")


# --- Pairing & Status Endpoints ---

class PairRequest(BaseModel):
    code: str
    device_name: Optional[str] = "Col's iPad Air"


@ipad_app.post("/api/ipad/pair")
async def api_pair_ipad(payload: PairRequest):
    """
    Validate 6-digit numeric pairing code entered on iPad.
    If valid, returns long-lived cryptographic bearer token.
    """
    code = (payload.code or "").strip()
    device_name = (payload.device_name or "Col's iPad Air").strip()
    store = get_sqlite_store()
    token = store.verify_and_pair_device(code, device_type="ipad", device_name=device_name)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired pairing code.")
    logger.info(f"[iPadGateway] Device paired successfully: {device_name}")
    return {"status": "paired", "token": token, "device_name": device_name}


@ipad_app.get("/api/ipad/status")
async def api_ipad_status():
    """Public pairing status check (whether any iPad is currently paired)."""
    status = get_sqlite_store().get_paired_device_status(device_type="ipad")
    return {
        "paired": status.get("paired", False),
        "device_name": status.get("device_name"),
        "paired_at": status.get("paired_at"),
        "last_seen_at": status.get("last_seen_at"),
    }


# --- Authenticated Application Endpoints ---

class ChatSendRequest(BaseModel):
    text: str


@ipad_app.get("/api/ipad/chat/history")
async def api_get_chat_history(token: str = Depends(get_auth_token)):
    """Return recent conversation messages for display on iPad."""
    with _ipad_chat_lock:
        return {"messages": list(_ipad_chat_history)}


@ipad_app.post("/api/ipad/chat/send")
async def api_send_chat(payload: ChatSendRequest, token: str = Depends(get_auth_token)):
    """Send text message from iPad to ARCHER CoreAgent."""
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text message")
    _record_chat("user", text)
    _broadcast_ipad_ws({"type": "chat_message", "role": "user", "text": text})

    bus = get_event_bus()
    bus.publish(Event(
        type=EventType.GUI_TEXT_INPUT,
        source="ipad_client",
        data={"text": text},
    ))
    return {"status": "sent", "text": text}


@ipad_app.get("/api/ipad/tasks")
async def api_get_tasks(token: str = Depends(get_auth_token)):
    """Return tasks and habits checklist for iPad Away & Tasks view."""
    store = get_sqlite_store()
    return {
        "tasks": store.get_tasks(),
        "habits": store.get_habits(),
    }


class TaskToggleRequest(BaseModel):
    task_id: int
    completed: bool


@ipad_app.post("/api/ipad/tasks/toggle")
async def api_toggle_task(payload: TaskToggleRequest, token: str = Depends(get_auth_token)):
    """Toggle a task completion state from iPad."""
    store = get_sqlite_store()
    if payload.completed:
        store.complete_task(payload.task_id)
    else:
        # Re-open task
        conn = store._get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE tasks SET status = 'pending', completed_at = NULL WHERE id = ?",
                    (payload.task_id,),
                )
        finally:
            conn.close()

    get_event_bus().publish(Event(type=EventType.TASKS_CHANGED, source="ipad_client"))
    return {"status": "updated", "tasks": store.get_tasks()}


@ipad_app.get("/api/ipad/away")
async def api_get_away(token: str = Depends(get_auth_token)):
    """Return 'While You Were Away' interventions for iPad."""
    store = get_sqlite_store()
    return {
        "interventions": store.get_recent_interventions(limit=20),
    }


@ipad_app.get("/api/ipad/items")
async def api_get_items(query: Optional[str] = None, token: str = Depends(get_auth_token)):
    """
    Return tracked item locations and photo availability ('Where's my ...').
    """
    store = get_sqlite_store()
    conn = store._get_connection()
    try:
        sql = """
            SELECT i.id, i.item_name, i.category, i.last_seen_at, i.image_path,
                   l.location_name, l.room, l.furniture_type
            FROM inventory_items i
            LEFT JOIN storage_locations l ON i.current_location_id = l.id
        """
        params = []
        if query and query.strip():
            q = f"%{query.strip()}%"
            sql += " WHERE i.item_name LIKE ? OR l.location_name LIKE ? OR l.room LIKE ?"
            params.extend([q, q, q])
        sql += " ORDER BY i.last_seen_at DESC LIMIT 50"

        rows = conn.execute(sql, tuple(params)).fetchall()
        items = []
        for r in rows:
            img_path = r[4]
            has_photo = bool(img_path and Path(img_path).exists())
            items.append({
                "id": r[0],
                "item_name": r[1],
                "category": r[2],
                "last_seen_at": r[3],
                "location_name": r[5] or "Unknown",
                "room": r[6] or "Unknown",
                "furniture_type": r[7] or "",
                "has_photo": has_photo,
            })
        return {"items": items}
    finally:
        conn.close()


@ipad_app.get("/api/ipad/items/photo/{item_id}")
async def api_get_item_photo(item_id: int, token: str = Depends(get_auth_token)):
    """Serve photo of tracked item to iPad."""
    store = get_sqlite_store()
    conn = store._get_connection()
    try:
        row = conn.execute(
            "SELECT image_path FROM inventory_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="Item photo not found")
        path = Path(row[0])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Photo file not found on disk")
        return FileResponse(str(path))
    finally:
        conn.close()


@ipad_app.get("/api/ipad/approvals")
async def api_get_approvals(token: str = Depends(get_auth_token)):
    """Return all active pending approval requests for iPad."""
    mgr = get_approval_manager()
    return {"requests": mgr.get_pending_requests()}


class ApprovalRespondRequest(BaseModel):
    request_id: str
    decision: str  # 'approve', 'deny', 'approve_session'


@ipad_app.post("/api/ipad/approvals/respond")
async def api_respond_approval(payload: ApprovalRespondRequest, token: str = Depends(get_auth_token)):
    """Approve or deny pending tool execution from iPad."""
    decision = payload.decision.lower().strip()
    if decision not in ("approve", "deny", "approve_session"):
        raise HTTPException(status_code=400, detail="Invalid decision value")
    mgr = get_approval_manager()
    success = mgr.handle_response(payload.request_id, decision)
    if not success:
        raise HTTPException(status_code=404, detail="Approval request not found or already resolved")
    return {"status": "resolved", "request_id": payload.request_id, "decision": decision}


@ipad_app.get("/api/ipad/tts")
async def api_get_tts(text: str = Query(...), token: str = Depends(get_auth_token)):
    """
    Synthesize speech audio for spoken replies on the iPad.
    Returns standard audio/wav stream compatible with iOS 12 Safari HTML5 Audio.
    """
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Empty text for synthesis")
    try:
        from archer.voice.tts import LocalTTS
        tts = LocalTTS()
        audio_bytes, sr = tts.synthesize(clean_text)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS synthesis produced empty audio")
        return StreamingResponse(io.BytesIO(audio_bytes), media_type="audio/wav")
    except Exception as e:
        logger.warning(f"[iPadTTS] Synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis error: {e}")


# --- WebSocket Bridge for Real-time iPad Updates ---

@ipad_app.websocket("/ws/ipad")
async def ws_ipad(websocket: WebSocket, token: Optional[str] = Query(None)):
    """
    Real-time bidirectional WebSocket for the iPad Air client.
    Streams live chat, approval prompts, and task updates.
    """
    global _ipad_loop
    # Authenticate token before accepting
    if not token or not get_sqlite_store().validate_device_token(token, device_type="ipad"):
        await websocket.close(code=4401, reason="Unauthorized: iPad not paired or token revoked")
        return

    await websocket.accept()
    _ipad_loop = asyncio.get_running_loop()
    with _ipad_ws_clients_lock:
        _ipad_ws_clients.add(websocket)
    logger.info(f"[iPadWS] iPad connected ({len(_ipad_ws_clients)} active iPad clients)")

    # Send initial state packet
    try:
        store = get_sqlite_store()
        mgr = get_approval_manager()
        with _ipad_chat_lock:
            chat_snap = list(_ipad_chat_history)
        await _ws_send_safe(websocket, json.dumps({
            "type": "init",
            "chat_history": chat_snap,
            "tasks": store.get_tasks(),
            "habits": store.get_habits(),
            "interventions": store.get_recent_interventions(limit=20),
            "pending_approvals": mgr.get_pending_requests(),
        }))
    except Exception as e:
        logger.debug(f"[iPadWS] Failed to send init snapshot: {e}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            if msg_type == "chat_input":
                text = (msg.get("text") or "").strip()
                if text:
                    _record_chat("user", text)
                    _broadcast_ipad_ws({"type": "chat_message", "role": "user", "text": text})
                    get_event_bus().publish(Event(
                        type=EventType.GUI_TEXT_INPUT,
                        source="ipad_client",
                        data={"text": text},
                    ))
            elif msg_type == "approval_response":
                req_id = msg.get("request_id")
                decision = msg.get("decision", "deny")
                if req_id:
                    get_approval_manager().handle_response(req_id, decision)
            elif msg_type == "task_toggle":
                task_id = msg.get("task_id")
                completed = msg.get("completed", False)
                if task_id:
                    store = get_sqlite_store()
                    if completed:
                        store.complete_task(task_id)
                    else:
                        conn = store._get_connection()
                        try:
                            with conn:
                                conn.execute("UPDATE tasks SET status = 'pending', completed_at = NULL WHERE id = ?", (task_id,))
                        finally:
                            conn.close()
                    get_event_bus().publish(Event(type=EventType.TASKS_CHANGED, source="ipad_client"))
            elif msg_type == "ping":
                await _ws_send_safe(websocket, json.dumps({"type": "pong"}))
    except (WebSocketDisconnect, ConnectionResetError):
        pass
    finally:
        with _ipad_ws_clients_lock:
            _ipad_ws_clients.discard(websocket)
        logger.info(f"[iPadWS] iPad disconnected ({len(_ipad_ws_clients)} remaining)")


# --- Server Lifecycle Runner ---

_server_instance: Optional[uvicorn.Server] = None
_server_thread: Optional[threading.Thread] = None


def start_ipad_server(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Start the iPad gateway server on a background daemon thread."""
    global _server_instance, _server_thread
    if _server_thread and _server_thread.is_alive():
        logger.info("[iPadGateway] Server is already running.")
        return

    config = get_config()
    server_host = host or config.ipad_host
    server_port = port or config.ipad_port

    uvi_config = uvicorn.Config(
        app=ipad_app,
        host=server_host,
        port=server_port,
        log_level="warning",
        access_log=False,
    )
    _server_instance = uvicorn.Server(uvi_config)

    def _run():
        lan_ip = get_local_lan_ip()
        logger.info(f"[iPadGateway] Starting iPad server on http://{server_host}:{server_port} (LAN: http://{lan_ip}:{server_port})")
        _server_instance.run()

    _server_thread = threading.Thread(target=_run, daemon=True, name="archer-ipad-server")
    _server_thread.start()


def stop_ipad_server() -> None:
    """Stop the iPad gateway server."""
    global _server_instance, _server_thread
    if _server_instance:
        _server_instance.should_exit = True
    disconnect_all_ipad_clients()
    _server_thread = None
    logger.info("[iPadGateway] Server stopped.")
