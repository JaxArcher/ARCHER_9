"""
ARCHER Mobile API Server
FastAPI wrapper around existing agent orchestrator for mobile app access.
"""

import asyncio
import os
import json
import logging
import datetime
import threading
import time as _time
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator

from fastapi import FastAPI, HTTPException, Header, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import httpx

from archer.agents.orchestrator import AgentOrchestrator
from archer.config import get_config
from archer.core.event_bus import get_event_bus, Event, EventType
from archer.core.toggle import get_toggle_service
from archer.memory.sqlite_store import get_sqlite_store

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("archer-server")

app = FastAPI(title="ARCHER Mobile API", version="1.0.0")

# CORS - only allow Tailscale network (open by default, restrict via config if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production to Tailscale IPs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Local browser client (see web/ and web/CONTRACT.md) ---
# Serves the browser UI and mounts its static assets. The client is a
# second, symmetric VIEW onto the same live pipeline the PyQt6 GUI
# watches (see the WebSocket bridge below) -- it doesn't carry audio.
# Voice capture stays on this machine's own mic via the existing
# AudioManager for the local case; only the later remote/LiveKit phase
# needs audio to cross the network, since a remote device has its own mic.
import mimetypes
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/wasm", ".wasm")

class _NoCacheStaticFiles(StaticFiles):
    """Plain StaticFiles lets browsers cache JS/CSS aggressively with no
    freshness check at all, since script/link tags reference plain,
    unversioned URLs (/static/js/memory.js, etc.) with no cache-busting
    query string or hash. That bit Col directly (2026-09-19): a real,
    verified-correct fix to memory.js kept showing the OLD removed
    "Unrecognized People" pane, because the browser never even asked the
    server if the file had changed. Forcing Cache-Control: no-cache (not
    no-store) doesn't disable caching -- it makes the browser always
    revalidate via a conditional GET (If-Modified-Since/ETag, which
    Starlette already sends), so an unchanged file is still served from
    cache on a 304 and nothing gets slower, but a changed file is always
    picked up on the next normal reload instead of requiring a hard
    refresh."""

    def file_response(self, path, *args, **kwargs):
        response = super().file_response(path, *args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        p_str = str(path).lower()
        if p_str.endswith(".mjs") or p_str.endswith(".js"):
            response.headers["Content-Type"] = "application/javascript"
        elif p_str.endswith(".wasm"):
            response.headers["Content-Type"] = "application/wasm"
        return response


_WEB_DIR = Path(__file__).resolve().parents[2] / "web"
if _WEB_DIR.exists():
    app.mount("/static", _NoCacheStaticFiles(directory=str(_WEB_DIR)), name="static")

    @app.get("/app")
    async def serve_web_client():
        """Serves the local browser client's entry point."""
        return FileResponse(str(_WEB_DIR / "index.html"))
else:
    logger.warning(f"web/ directory not found at {_WEB_DIR} — browser client route ('/app') disabled.")

# Authentication
# In production, this should be a strong random token stored in .env
MOBILE_TOKEN = os.getenv("ARCHER_MOBILE_TOKEN", "CHANGE_IN_PRODUCTION")

def verify_token(authorization: str = Header(...)):
    """Verify bearer token from mobile app."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = authorization.replace("Bearer ", "")
    if token != MOBILE_TOKEN:
        logger.warning(f"Invalid token attempt: {token[:4]}...")
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return token


# Request/Response Models
class ChatRequest(BaseModel):
    message: str
    user_id: str = "col"
    response_format: str = "text"  # "text" or "audio"


class ChatResponse(BaseModel):
    agent: str
    response: str
    timestamp: str
    conversation_id: str


# Global orchestrator / agent instance (singleton)
_orchestrator = None

def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from archer.agents.core_agent import CoreAgent
        _orchestrator = CoreAgent()
    return _orchestrator

def set_orchestrator(orch: Any):
    """Inject a pre-initialized agent or orchestrator instance."""
    global _orchestrator
    _orchestrator = orch


# Global observer pipeline instance (optional — None if observer deps
# unavailable / disabled). Lets the WS bridge below release/reacquire the
# camera on request (see ObserverPipeline.release_camera, added for the
# barehands device-contention issue: only one process can hold a webcam
# at a time on Windows).
_observer = None

def set_observer(observer: Any):
    """Inject the running ObserverPipeline instance, if any."""
    global _observer
    _observer = observer



_pending_frame_futures: dict[str, asyncio.Future[str]] = {}


async def _request_browser_camera_frame(ws: WebSocket, timeout: float = 5.0):
    """Request a camera frame (base64 JPEG) from the connected browser client."""
    logger.debug("[ServerWS] Top of _request_browser_camera_frame")
    import base64
    import uuid
    import cv2
    import numpy as np

    req_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _pending_frame_futures[req_id] = fut
    try:
        logger.debug(f"[ServerWS] Sending camera_frame_request req_id={req_id}")
        await _ws_send_safe(ws, json.dumps({"type": "camera_frame_request", "request_id": req_id}))
        b64_data = await asyncio.wait_for(fut, timeout=timeout)
        if not b64_data:
            return None
        img_bytes = base64.b64decode(b64_data)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.warning(f"Browser camera frame request failed or timed out: {e}")
        return None
    finally:
        _pending_frame_futures.pop(req_id, None)


async def _handle_browser_screenshot(websocket: WebSocket) -> None:
    agent = get_orchestrator()
    image_b64 = None
    try:
        pc = agent.pc_controller
        if pc is not None:
            image_b64 = await asyncio.to_thread(pc.browser_screenshot)
    except Exception as e:
        logger.debug(f"Browser screenshot unavailable: {e}")
    await _ws_send_safe(websocket, json.dumps({
        "type": "browser_screenshot",
        "image_b64": image_b64,
        "active": image_b64 is not None,
    }))


# Endpoints
@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "ARCHER Mobile API"}


@app.get("/api/skills")
async def get_skills_list():
    """Return all skills discovered by skills_registry.py for the TOOLS tab."""
    from archer.skills.skills_registry import parse_skill_file
    skills_dir = Path(__file__).parent / "skills"
    skill_files = list(skills_dir.glob("*_SKILL.md"))
    result = []
    for sf in sorted(skill_files):
        try:
            data = parse_skill_file(sf)
            result.append({
                "file_name": sf.name,
                "name": data.get("name", sf.name),
                "category": data.get("category", "general"),
                "description": data.get("description", ""),
                "tool_count": len(data.get("tools", [])),
            })
        except Exception as e:
            logger.warning(f"Could not parse skill file {sf}: {e}")
    return {"skills": result}


@app.get("/mobile/health")
async def health_check():
    """Detailed health check - no authentication required."""
    orch = get_orchestrator()
    return {
        "status": "healthy",
        "version": "1.0.0",
        "active_agent": orch.active_agent,
        "session_id": orch.session_id,
        "agents_available": [
            "assistant", "trainer", "therapist", "investment",
            "blindspot", "inventory", "observer"
        ]
    }


@app.post("/mobile/chat", response_model=ChatResponse)
async def mobile_chat(
    request: ChatRequest,
    token: str = Depends(verify_token)
):
    """
    Process text message from mobile app and return agent response.
    Blocks until full response is generated (for simple mobile clients).
    """
    orch = get_orchestrator()
    
    try:
        # Orchestrator handles memory storage internally
        response_text = orch.process_request(request.message)
        
        return ChatResponse(
            agent=orch.active_agent.capitalize(),
            response=response_text,
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
            conversation_id=orch.session_id
        )
    except Exception as e:
        logger.error(f"Mobile chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mobile/stream")
async def mobile_stream(
    request: ChatRequest,
    token: str = Depends(verify_token)
):
    """
    Sentence-level streaming for lower latency in mobile UI.
    Returns NDJSON stream.
    """
    orch = get_orchestrator()
    
    def generate() -> Generator[str, None, None]:
        try:
            for sentence in orch.process_request_streaming(request.message):
                yield json.dumps({
                    "sentence": sentence,
                    "agent": orch.active_agent,
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
                }) + "\n"
        except Exception as e:
            logger.error(f"Mobile streaming error: {e}")
            yield json.dumps({"error": str(e)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/mobile/memory/recent")
async def get_recent_memory(
    limit: int = 20,
    token: str = Depends(verify_token)
):
    """
    Get recent conversations from memory.
    """
    orch = get_orchestrator()
    try:
        # Access the underlying history from orchestrator
        with orch._history_lock:
            history = list(orch._conversation_history[-limit:])
        
        return {
            "conversations": history,
            "total": len(history),
            "session_id": orch.session_id
        }
    except Exception as e:
        logger.error(f"Memory access error: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve memory.")


@app.get("/mobile/memory/search")
async def search_memory(
    q: str,
    limit: int = 10,
    token: str = Depends(verify_token)
):
    """
    Semantic search across conversation memory.
    """
    orch = get_orchestrator()
    try:
        # We need to access the ChromaDB store. 
        # In a real implementation, we'd query the store directly.
        # For now, we search within the loaded context if possible, 
        # but full semantic search requires reaching into the memory agent.
        
        results = orch._retrieve_memory_context(q, limit=limit)
        
        return {
            "results": results,
            "query": q,
            "total_results": len(results)
        }
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail="Search failed.")


# --- Browser client event bridge ---
# Forwards the internal event bus (archer.core.event_bus — the same one
# the PyQt6 ConversationPanel subscribes to, see gui/conversation.py) to
# every connected browser client over WebSocket. Message schema is
# documented in web/CONTRACT.md — that file is the interface contract for
# building/restyling the browser UI without touching this Python.
#
# The event bus calls subscriber callbacks SYNCHRONOUSLY on whatever
# thread published the event (the voice pipeline runs on its own thread,
# not the asyncio loop) — so callbacks can't just `await ws.send_text()`
# directly. Instead they hand the message to the asyncio loop thread-
# safely via call_soon_threadsafe, and a loop-side function does the
# actual broadcast.
_ws_clients: set[WebSocket] = set()
_ws_loop: asyncio.AbstractEventLoop | None = None


async def _ws_send_safe(ws: WebSocket, text: str) -> None:
    try:
        await ws.send_text(text)
    except Exception as e:
        logger.warning(f"[ServerWS] _ws_send_safe failed: {e}")
        _ws_clients.discard(ws)


def _broadcast_ws(msg: dict) -> None:
    """Runs ON the asyncio loop thread — scheduled via call_soon_threadsafe."""
    if not _ws_clients:
        return
    text = json.dumps(msg, default=str)
    for ws in list(_ws_clients):
        asyncio.create_task(_ws_send_safe(ws, text))


def _on_bus_event(msg_type: str, **data) -> None:
    """Build a browser-facing message and hand it to the asyncio loop thread-safely."""
    if _ws_loop is None:
        return  # no browser client has connected yet
    msg = {"type": msg_type, **data}
    try:
        _ws_loop.call_soon_threadsafe(_broadcast_ws, msg)
    except RuntimeError:
        pass  # loop already closed/shutting down


def _register_event_bridge() -> None:
    """Subscribe to the internal event bus once, at import time."""
    bus = get_event_bus()
    bus.subscribe(EventType.PIPELINE_STATE_CHANGED, lambda e: _on_bus_event(
        "state", state=e.data.get("state", "idle")))
    bus.subscribe(EventType.STT_PARTIAL, lambda e: _on_bus_event(
        "stt_partial", text=e.data.get("text", "")))
    bus.subscribe(EventType.STT_FINAL, lambda e: _on_bus_event(
        "stt_final", text=e.data.get("text", "")))
    bus.subscribe(EventType.AGENT_RESPONSE_START, lambda e: _on_bus_event(
        "agent_response_start", elapsed=e.data.get("elapsed", 0.0)))
    bus.subscribe(EventType.AGENT_RESPONSE_END, lambda e: _on_bus_event(
        "agent_response", text=e.data.get("text", ""), agent=e.data.get("agent", "assistant")))
    bus.subscribe(EventType.AGENT_SWITCH, lambda e: _on_bus_event(
        "agent_switch", agent=e.data.get("new_agent", "assistant")))
    bus.subscribe(EventType.WAKE_WORD_DETECTED, lambda e: _on_bus_event("wake_word"))
    bus.subscribe(EventType.WAKE_ACK_PLAY, lambda e: _on_bus_event(
        "assistant_line", text=e.data.get("text", "")))
    bus.subscribe(EventType.FILLER_PLAY, lambda e: _on_bus_event(
        "assistant_line", text=e.data.get("text", "")))
    bus.subscribe(EventType.AUDIO_AMPLITUDE, lambda e: _on_bus_event(
        "amplitude", value=e.data.get("amplitude", 0.0)))
    bus.subscribe(EventType.MODE_CHANGED, lambda e: _on_bus_event(
        "mode", mode=e.data.get("new_mode", "unknown")))
    bus.subscribe(EventType.SYSTEM_START, lambda e: _on_bus_event("system_start"))
    bus.subscribe(EventType.UI_SWITCH_TAB, lambda e: _on_bus_event(
        "switch_tab", tab=e.data.get("tab", "")))
    bus.subscribe(EventType.TASKS_CHANGED, lambda e: _broadcast_tasks_snapshot())
    bus.subscribe(EventType.ARTIFACT_PUSH, lambda e: _on_bus_event(
        "artifact_push", image_b64=e.data.get("image_b64", ""),
        kind=e.data.get("kind", ""), title=e.data.get("title", "")))
    bus.subscribe_halt(lambda e: _on_bus_event("halt"))


_register_event_bridge()


# --- LOGS tab: curated "what ARCHER is doing right now" feed ---
# Replaced 2026-09-18 (Col's request) -- this used to tail ARCHER's own
# raw DEBUG-level rotating log file (archer_YYYY-MM-DD.log) straight into
# the browser, mirroring gui/console_widget.py's desktop Console tab. In
# practice that was mostly httpx polling noise ("GET /api/ps 200 OK"
# every second, from every SYSTEM-tab metrics poll) with the actually
# useful lines buried in it -- Col's own words: "whatever is showing
# there currently is never anything useful." This subscribes to the SAME
# event-bus events server.py already bridges to the browser for other
# purposes (state changes, transcripts, responses, camera checks) and
# turns each into one plain-English line on the same log_line channel
# the LOGS pane already renders -- no frontend change needed, just a
# different (better) source for the text.
from collections import deque as _deque
_status_line_history: _deque = _deque(maxlen=50)


def _status_line(text: str) -> None:
    line = f"{_time.strftime('%H:%M:%S')} | {text}\n"
    _status_line_history.append(line)
    _on_bus_event("log_line", text=line)


def _register_status_line_bridge() -> None:
    bus = get_event_bus()

    _STATE_LINES = {
        "listening": "🎤 Listening...",
        "processing": "🤔 Thinking -- request sent to the model...",
        "speaking": "🔊 Speaking the response...",
        "idle": "💤 Idle -- waiting for the wake word.",
    }

    def _on_state(e: Event) -> None:
        line = _STATE_LINES.get(e.data.get("state", ""))
        if line:
            _status_line(line)

    bus.subscribe(EventType.PIPELINE_STATE_CHANGED, _on_state)
    bus.subscribe(EventType.WAKE_WORD_DETECTED, lambda e: _status_line("🎤 Wake word detected."))
    bus.subscribe(EventType.STT_FINAL, lambda e: _status_line(
        f"📝 Heard: \"{e.data.get('text', '')}\""))
    bus.subscribe(EventType.VISUAL_QUERY, lambda e: _status_line(
        f"👁️ {e.data.get('note', '')}"))
    bus.subscribe(EventType.FILLER_PLAY, lambda e: _status_line(
        f"💬 Still thinking -- playing filler: \"{e.data.get('text', '')}\""))
    bus.subscribe(EventType.AGENT_RESPONSE_START, lambda e: _status_line(
        f"✍️ First words arriving ({e.data.get('elapsed', 0.0):.1f}s after the request)."))
    bus.subscribe(EventType.AGENT_RESPONSE_END, lambda e: _status_line(
        f"✅ Response ready: \"{e.data.get('text', '')[:150]}\""))
    bus.subscribe(EventType.SYSTEM_ERROR, lambda e: _status_line(
        f"⚠️ Error: {e.data.get('message', '')}"))
    bus.subscribe(EventType.MODE_CHANGED, lambda e: _status_line(
        f"🔀 Switched to {e.data.get('new_mode', 'unknown')} mode."))
    bus.subscribe_halt(lambda e: _status_line("🛑 HALT -- stopped."))


_register_status_line_bridge()


# --- Cross-process "GUI is active" heartbeat (2026-09-19) ---
# Moondream moved back to CPU-only (Col's call -- GPU headroom matters
# more than the earlier contention risk, now that this flag lets the
# standalone observer service actually pause itself). Refreshes a short-
# TTL Redis key for as long as at least one browser client is connected,
# so ObserverPipeline._analysis_loop (running in a completely different
# OS process) knows to skip its CPU-heavy moondream analysis cycles while
# ARCHER is actually in use, and resume automatically once nobody's
# connected. TTL-based, not a start/stop message, on purpose: if this
# process is killed rather than shut down cleanly, the flag just expires
# on its own a few seconds later instead of leaving the observer paused
# forever. See RedisBuffer.mark_gui_active's docstring for the full
# reasoning.
def _gui_active_heartbeat_loop() -> None:
    from archer.memory.redis_buffer import get_redis_buffer
    redis_buffer = get_redis_buffer()
    while True:
        if _ws_clients:
            redis_buffer.mark_gui_active()
        _time.sleep(3.0)


threading.Thread(target=_gui_active_heartbeat_loop, daemon=True, name="archer-gui-active-heartbeat").start()


@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket):
    """
    Browser client connection — see web/CONTRACT.md for the full message
    schema. Pushes live pipeline state/transcript/agent-response events;
    accepts inbound: typed text (bridged to GUI_TEXT_INPUT, the exact path
    the desktop text box already uses), a halt command, and mode/mute
    toggles (mirroring the desktop GUI's own toolbar buttons exactly). No
    audio flows over this socket — see the comment above _ws_clients for why.
    """
    global _ws_loop
    await websocket.accept()
    _ws_loop = asyncio.get_running_loop()
    _ws_clients.add(websocket)
    logger.info(f"Browser client connected ({len(_ws_clients)} total)")

    # Snapshot current mode/mute state for this one new client -- the
    # broadcast events below only fire on the next *change*, so without
    # this a freshly-opened tab would show stale defaults until something
    # happens to toggle them.
    try:
        from archer.voice import get_audio_manager
        am = get_audio_manager()
        await _ws_send_safe(websocket, json.dumps({
            "type": "hello",
            "mode": get_toggle_service().mode,
            "mic_muted": am.is_mic_muted(),
            "tts_muted": am.is_tts_muted,
            "camera_released": bool(_observer and _observer.is_camera_released),
            "camera_available": _observer is not None,
        }))
    except Exception as e:
        logger.debug(f"Could not send initial state snapshot to browser client: {e}")

    # Seed the LOGS tab with recent curated status history -- events only
    # broadcast going forward, so without this a freshly opened tab would
    # sit empty until the next thing actually happens.
    try:
        if _status_line_history:
            await _ws_send_safe(websocket, json.dumps({
                "type": "log_line", "text": "".join(_status_line_history)
            }))
    except Exception as e:
        logger.debug(f"Could not send initial status history to browser client: {e}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            bus = get_event_bus()
            msg_type = msg.get("type")
            logger.debug(f"[ServerWS] Received WS message: type='{msg_type}'")
            if msg_type == "text_input":
                text = (msg.get("text") or "").strip()
                if text:
                    bus.publish(Event(
                        type=EventType.GUI_TEXT_INPUT,
                        source="web_client",
                        data={"text": text},
                    ))
            elif msg_type == "halt":
                bus.publish_halt(source="web_client")
            elif msg_type == "mode_toggle":
                # ToggleService.mode setter publishes EventType.MODE_CHANGED
                # itself, which the bridge above already broadcasts to every
                # connected client (including this one) as {"type": "mode"}.
                new_mode = get_toggle_service().toggle()
                logger.info(f"Mode toggled to {new_mode} (via web client)")
            elif msg_type == "mic_mute_toggle":
                from archer.voice import get_audio_manager
                am = get_audio_manager()
                new_val = not am.is_mic_muted()
                am.set_mic_muted(new_val)
                _broadcast_ws({"type": "mic_mute", "muted": new_val})
            elif msg_type == "tts_mute_toggle":
                from archer.voice import get_audio_manager
                am = get_audio_manager()
                new_val = not am.is_tts_muted
                am.set_tts_muted(new_val)
                _broadcast_ws({"type": "tts_mute", "muted": new_val})
            elif msg_type == "camera_frame_response":
                req_id = msg.get("request_id")
                image_b64 = msg.get("image_b64")
                if req_id and req_id in _pending_frame_futures:
                    fut = _pending_frame_futures.get(req_id)
                    if fut and not fut.done():
                        fut.set_result(image_b64)
            elif msg_type == "request_camera_frame":
                asyncio.create_task(_request_browser_camera_frame(websocket, timeout=5.0))
            elif msg_type == "memory_get_all":
                # MEMORY tab initial load / manual refresh -- one bulk
                # payload rather than four round trips (2026-09-16).
                await _ws_send_safe(websocket, json.dumps(_build_memory_snapshot()))
            elif msg_type == "memory_add_contact":
                store = get_sqlite_store()
                name = (msg.get("name") or "").strip()
                if name:
                    store.upsert_contact(
                        name=name,
                        relationship=(msg.get("relationship") or None),
                        typical_interval_days=msg.get("typical_interval_days"),
                    )
                    _broadcast_ws(_build_memory_snapshot())
            elif msg_type == "memory_log_interaction":
                store = get_sqlite_store()
                contact_name = (msg.get("contact_name") or "").strip()
                if contact_name:
                    store.log_interaction(
                        contact_name=contact_name,
                        interaction_type=(msg.get("interaction_type") or "in-person"),
                        notes=(msg.get("notes") or None),
                        sentiment_score=msg.get("sentiment_score"),
                    )
                    _broadcast_ws(_build_memory_snapshot())
            elif msg_type == "memory_add_commitment":
                store = get_sqlite_store()
                contact_name = (msg.get("contact_name") or "").strip()
                promise = (msg.get("promise") or "").strip()
                if contact_name and promise:
                    store.track_commitment(
                        contact_name=contact_name,
                        promise=promise,
                        due_date=(msg.get("due_date") or None),
                    )
                    _broadcast_ws(_build_memory_snapshot())
            elif msg_type == "memory_resolve_commitment":
                store = get_sqlite_store()
                commitment_id = msg.get("commitment_id")
                if commitment_id is not None:
                    store.resolve_commitment(
                        int(commitment_id), fulfilled=bool(msg.get("fulfilled", True))
                    )
                    _broadcast_ws(_build_memory_snapshot())
            elif msg_type == "memory_confirm_person":
                # Col names a recurring stranger from the "Unrecognized
                # People" pane -- pull the embedding InsightFace already
                # captured for this face-cluster off the resolved row and
                # enroll it as a known person, same store call the live
                # "this is Sarah" path uses (CoreAgent._check_person_
                # introduction). No re-capture, no second InsightFace pass.
                store = get_sqlite_store()
                confirmation_id = msg.get("id")
                name = (msg.get("name") or "").strip()
                if confirmation_id is not None and name:
                    row = store.resolve_pending_person_confirmation(
                        int(confirmation_id), status="confirmed", confirmed_name=name
                    )
                    if row and row.get("embedding"):
                        # add_person_face (2026-10-06): adds a reference if the
                        # name is already enrolled instead of overwriting it.
                        how = store.add_person_face(name=name, embedding=row["embedding"], source="confirmation")
                        logger.info(f"Named '{name}' from browser confirmation ({how}).")
                    _broadcast_ws(_build_memory_snapshot())
            elif msg_type == "memory_dismiss_person":
                # A one-off stranger (delivery driver, etc.) Col doesn't
                # want to name -- clears it from the pane without enrolling
                # anyone. upsert_pending_person_confirmation() won't
                # resurrect a dismissed row for this same face.
                store = get_sqlite_store()
                confirmation_id = msg.get("id")
                if confirmation_id is not None:
                    store.resolve_pending_person_confirmation(int(confirmation_id), status="dismissed")
                    _broadcast_ws(_build_memory_snapshot())
            elif msg_type == "tasks_get_all":
                await _ws_send_safe(websocket, json.dumps(_build_tasks_snapshot()))
            elif msg_type == "tasks_add":
                title = (msg.get("title") or "").strip()
                if title:
                    get_sqlite_store().add_task(
                        title=title,
                        due_date=(msg.get("due_date") or None),
                        source="user",
                    )
                    _broadcast_ws(_build_tasks_snapshot())
            elif msg_type == "tasks_complete":
                task_id = msg.get("task_id")
                if task_id is not None:
                    get_sqlite_store().complete_task(int(task_id))
                    _broadcast_ws(_build_tasks_snapshot())
            elif msg_type == "tasks_delete":
                task_id = msg.get("task_id")
                if task_id is not None:
                    get_sqlite_store().delete_task(int(task_id))
                    _broadcast_ws(_build_tasks_snapshot())
            elif msg_type == "habits_add":
                name = (msg.get("name") or "").strip()
                if name:
                    get_sqlite_store().add_habit(name=name, frequency=(msg.get("frequency") or "daily"))
                    _broadcast_ws(_build_tasks_snapshot())
            elif msg_type == "habits_complete":
                name = (msg.get("name") or "").strip()
                if name:
                    get_sqlite_store().complete_habit(name)
                    _broadcast_ws(_build_tasks_snapshot())
            elif msg_type == "habits_delete":
                name = (msg.get("name") or "").strip()
                if name:
                    get_sqlite_store().delete_habit(name)
                    _broadcast_ws(_build_tasks_snapshot())
            elif msg_type == "system_get_all":
                # SYSTEM tab initial load / manual refresh -- devices,
                # local models, and GPU/ollama metrics in one payload,
                # same "one bulk round trip" pattern as memory_get_all /
                # tasks_get_all (2026-09-16).
                await _ws_send_safe(websocket, json.dumps(await _build_system_snapshot()))
            elif msg_type == "system_switch_mic":
                device_index = msg.get("device_index")
                if device_index is not None:
                    from archer.voice import get_audio_manager
                    try:
                        get_audio_manager().switch_input_device(int(device_index))
                    except Exception as e:
                        logger.warning(f"Mic switch failed: {e}")
                    _broadcast_ws(await _build_system_snapshot())
            elif msg_type == "system_switch_speaker":
                device_index = msg.get("device_index")
                if device_index is not None:
                    from archer.voice import get_audio_manager
                    try:
                        get_audio_manager().switch_output_device(int(device_index))
                    except Exception as e:
                        logger.warning(f"Speaker switch failed: {e}")
                    _broadcast_ws(await _build_system_snapshot())
            elif msg_type == "system_switch_model":
                model = (msg.get("model") or "").strip()
                if model:
                    agent = get_orchestrator()
                    agent.primary_model = model
                    logger.info(f"Local 'brain' model switched to '{model}' from browser SYSTEM tab.")
                    _broadcast_ws(await _build_system_snapshot())
            elif msg_type == "browser_get_screenshot":
                # Mirrors the SAME Playwright browser ARCHER's own
                # browser-control tools already drive (tools/pc_control.py)
                # into a dashboard pane (2026-09-16, Col's ask) -- read-only
                # for now, no click/type forwarding yet. Screenshot capture
                # is a blocking Playwright call, so it runs off the event
                # loop (same reasoning as enroll_face below).
                agent = get_orchestrator()
                image_b64 = None
                try:
                    pc = agent.pc_controller
                    if pc is not None:
                        image_b64 = await asyncio.to_thread(pc.browser_screenshot)
                except Exception as e:
                    logger.debug(f"Browser screenshot unavailable: {e}")
                await _ws_send_safe(websocket, json.dumps({
                    "type": "browser_screenshot",
                    "image_b64": image_b64,
                    "active": image_b64 is not None,
                }))
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)
        logger.info(f"Browser client disconnected ({len(_ws_clients)} total)")

        # Reset the "brain" model back to the configured default once
        # nobody's left to be driving a manually-picked one (2026-09-19,
        # Col's call): the SYSTEM tab dropdown lets you try any locally
        # pulled model (e.g. llama3.2-vision) for a session, but that's a
        # deliberate one-off choice, not something that should silently
        # keep running as the primary model -- including handling tool
        # calls -- after you've closed the tab and forgotten about it.
        # Only resets if it actually drifted from the default, so this is
        # a no-op on every ordinary disconnect where nobody touched the
        # dropdown.
        if not _ws_clients:
            try:
                config = get_config()
                agent = get_orchestrator()
                if getattr(agent, "primary_model", None) != config.core_primary_model:
                    logger.info(
                        f"Last browser client disconnected -- resetting 'brain' model "
                        f"from '{agent.primary_model}' back to default '{config.core_primary_model}'."
                    )
                    agent.primary_model = config.core_primary_model
            except Exception as e:
                logger.debug(f"Brain-model reset on disconnect failed (non-fatal): {e}")


def _person_snapshot_data_uri(snapshot_path: Optional[str]) -> Optional[str]:
    """Read a face snapshot JPEG off disk and inline it as a data: URI for
    the browser -- these files live under data/snapshots/ (see
    person_id.py) and were never served over HTTP before, so the simplest
    fix is embedding the bytes directly in the WS payload rather than
    adding a new static route. Best-effort: a missing/unreadable file just
    means no thumbnail, not a broken pane."""
    if not snapshot_path:
        return None
    try:
        raw = Path(snapshot_path).read_bytes()
        import base64
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    except Exception as e:
        logger.debug(f"Could not read person snapshot '{snapshot_path}': {e}")
        return None


def _build_memory_snapshot() -> dict:
    """One bulk payload for the browser Memory tab -- relationships/social
    components (contacts, interactions, commitments) plus the pattern-
    recognition/recursive-learning output (learned entities, recurring
    conversation patterns). See sqlite_store.py's 2026-09-16 additions and
    memory/pattern_learner.py."""
    store = get_sqlite_store()
    pending_people = store.get_pending_person_confirmations(status="pending", limit=5)
    for p in pending_people:
        p["snapshot_data_uri"] = _person_snapshot_data_uri(p.get("snapshot_path"))
        p.pop("embedding", None)  # raw BLOB -- not JSON-serializable, not needed by the browser
    entities = store.get_learned_entities(limit=100)
    patterns = store.get_conversation_patterns(limit=50)
    try:
        from archer.integrations.notes_sync import sync_learned_patterns
        sync_learned_patterns(entities, patterns)
    except Exception as e:
        logger.debug(f"notes_sync (learned patterns) failed (non-fatal): {e}")
    return {
        "type": "memory_snapshot",
        "contacts": store.get_contacts(),
        "commitments": store.get_commitments(),
        "entities": entities,
        "patterns": patterns,
        # "While you were away" (2026-09-16): every Blindspot intervention
        # ever decided, most recent first, regardless of whether it's been
        # folded into a CoreAgent conversation yet -- see blindspot_agent.py
        # and core_agent.py's startup catch-up. Independent of that
        # delivery mechanism; this is purely for visibility in the browser.
        "interventions": store.get_recent_interventions(limit=20),
        # "Unrecognized People" (2026-09-16): recurring faces InsightFace
        # can't match to known_persons, waiting on a name. The OTHER half
        # of no-manual-enrollment (see CoreAgent._check_person_introduction
        # for the live "this is Sarah" half) -- this is what happens when
        # nobody ever says who a recurring visitor is out loud. Confirming
        # or dismissing one is a round trip through memory_confirm_person /
        # memory_dismiss_person below.
        "pending_people": pending_people,
    }


def _build_tasks_snapshot() -> dict:
    """One bulk payload for the browser TASKS card -- tasks and habits, both
    in v1 together per Col's call. See sqlite_store.py's 2026-09-16
    additions and skills/tasks_SKILL.md (available to every agent persona,
    not just the core Assistant). Also mirrors both out to barehands' Notes
    pane (see notes_sync.py) every time this is built -- i.e. every time
    the underlying data actually changed, from any surface."""
    store = get_sqlite_store()
    tasks = store.get_tasks()
    habits = store.get_habits()
    try:
        from archer.integrations.notes_sync import sync_tasks_and_habits
        sync_tasks_and_habits(tasks, habits)
    except Exception as e:
        logger.debug(f"notes_sync (tasks/habits) failed (non-fatal): {e}")
    return {
        "type": "tasks_snapshot",
        "tasks": tasks,
        "habits": habits,
    }


def _broadcast_tasks_snapshot() -> None:
    """Push a fresh tasks_snapshot to every connected client -- used both
    after a direct browser-tab write (see the WS handlers below) and when
    EventType.TASKS_CHANGED fires from a voice/text tool call
    (tasks_SKILL.md via UniversalToolExecutor), so the tab stays live no
    matter which surface made the change. Mirrors _on_bus_event's
    thread-safe hand-off, just without wrapping a "type" key that
    _build_tasks_snapshot() already provides."""
    if _ws_loop is None:
        return
    try:
        _ws_loop.call_soon_threadsafe(_broadcast_ws, _build_tasks_snapshot())
    except RuntimeError:
        pass


async def _ollama_tags(base_url: str) -> list[dict]:
    """Every model pulled and available to this Ollama instance (GET
    /api/tags -- what `ollama list` shows), not just what's currently
    loaded into memory. Best-effort: an unreachable instance just means an
    empty list for it, not a broken SYSTEM tab."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            return resp.json().get("models", [])
    except Exception as e:
        logger.debug(f"Could not reach Ollama /api/tags at {base_url}: {e}")
        return []


async def _ollama_ps(base_url: str) -> list[dict]:
    """Models currently loaded into memory on this Ollama instance, with
    size_vram vs size telling GPU vs CPU residency -- the browser
    equivalent of running `ollama ps` yourself (2026-09-16, Col's ask
    after the ~100s-to-first-token delay investigation). Best-effort, same
    reasoning as _ollama_tags."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/api/ps")
            resp.raise_for_status()
            return resp.json().get("models", [])
    except Exception as e:
        logger.debug(f"Could not reach Ollama /api/ps at {base_url}: {e}")
        return []


def _gpu_metrics() -> dict | None:
    """Total/used/free VRAM on the GPU via pynvml (already an installed
    dependency -- see torch.cuda's own pynvml import at boot). Returns
    None if pynvml or the driver isn't reachable rather than raising, so a
    headless/CPU-only box just shows no GPU card instead of an error."""
    try:
        import pynvml
        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="ignore")
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            try:
                temp_c = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                temp_c = None
            return {
                "name": name,
                "total_mb": round(mem.total / (1024 * 1024)),
                "used_mb": round(mem.used / (1024 * 1024)),
                "free_mb": round(mem.free / (1024 * 1024)),
                "gpu_util_pct": util.gpu,
                "temp_c": temp_c,
            }
        finally:
            pynvml.nvmlShutdown()
    except Exception as e:
        logger.debug(f"GPU metrics unavailable: {e}")
        return None


def _cpu_metrics() -> dict | None:
    """CPU utilization via psutil (2026-09-16, Col's ask for a CPU chart
    alongside GPU/VRAM/temp/tokens). cpu_percent(interval=None) is
    non-blocking and measures since the LAST call -- the module-level
    priming call right after import means the very first real snapshot
    is already meaningful instead of psutil's usual first-call 0.0."""
    try:
        import psutil
        return {"cpu_util_pct": psutil.cpu_percent(interval=None)}
    except Exception as e:
        logger.debug(f"CPU metrics unavailable: {e}")
        return None


try:
    import psutil as _psutil_prime
    _psutil_prime.cpu_percent(interval=None)  # prime the internal baseline
except Exception:
    pass


async def _build_system_snapshot() -> dict:
    """One bulk payload for the browser SYSTEM tab (2026-09-16, Col's ask
    after diagnosing a ~100s local-model delay by hand with `ollama ps` /
    `nvidia-smi`): GPU/VRAM headroom, which models are actually loaded on
    GPU vs CPU per Ollama instance, every locally-pulled model (for the
    'brain' dropdown), and audio I/O devices (for the mic/speaker
    dropdowns) -- so this diagnostic work is a glance at a tab from now on
    instead of a terminal round-trip."""
    config = get_config()
    from archer.config import _list_audio_devices

    main_tags, observer_tags, main_ps, observer_ps = await asyncio.gather(
        _ollama_tags(config.ollama_base_url),
        _ollama_tags(config.observer_ollama_url),
        _ollama_ps(config.ollama_base_url),
        _ollama_ps(config.observer_ollama_url),
    )
    # Dedupe by name -- the "brain" dropdown offers every model pulled on
    # either instance, since either Ollama server can technically serve
    # gemma4:e4b if asked.
    seen = {}
    for m in main_tags + observer_tags:
        seen[m.get("name") or m.get("model")] = m
    available_models = sorted(seen.keys())
    agent = get_orchestrator()
    devices = _list_audio_devices()

    current_model = getattr(agent, "primary_model", None) or config.core_primary_model
    if current_model and current_model not in available_models:
        available_models.append(current_model)
    available_models = sorted(list(set(available_models)))

    mic_devices = [d for d in devices if d.get("max_input", 0) > 0]
    speaker_devices = [d for d in devices if d.get("max_output", 0) > 0]

    return {
        "type": "system_snapshot",
        "gpu": _gpu_metrics(),
        "cpu": _cpu_metrics(),
        "tokens_per_sec": getattr(agent, "_last_tokens_per_sec", None),
        "ollama_loaded": [
            {**m, "instance": "main (11434)"} for m in main_ps
        ] + [
            {**m, "instance": "observer (11435)"} for m in observer_ps
        ],
        "available_models": available_models,
        "current_model": current_model,
        "mic_devices": mic_devices,
        "speaker_devices": speaker_devices,
        "current_mic_index": config.mic_device_index,
        "current_speaker_index": config.speaker_device_index,
    }


def start_server(host: str = None, port: int = None):
    config = get_config()
    host = host or config.api_host
    port = port or config.api_port
    logger.info(f"Starting ARCHER Mobile API on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
