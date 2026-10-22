"""
ARCHER Phase 8 Standalone Prototype Server.

Runs on http://127.0.0.1:8202 to demonstrate:
1. Live Windows desktop app streaming (PrintWindow PW_RENDERFULLCONTENT -> JPEG -> WebSocket).
2. Direct Win32 input forwarding from web canvas into the application window.
3. Live latency, FPS, and cursor behavior metrics.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger
import uvicorn

from archer.tools.desktop_streamer import DesktopAppStreamer, get_desktop_streamer

app = FastAPI(title="ARCHER Phase 8 Desktop Streamer Prototype")
streamer = get_desktop_streamer()
STATIC_DIR = Path(__file__).resolve().parent


@app.get("/", response_class=HTMLResponse)
async def serve_prototype_ui():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h3>index.html not found</h3>", status_code=404)


@app.get("/api/status")
async def get_status():
    return streamer.get_stats()


@app.post("/api/launch")
async def launch_app(payload: dict = None):
    exe = (payload or {}).get("executable", "notepad.exe")
    res = streamer.launch_app(executable=exe)
    return res


@app.post("/api/stop")
async def stop_app():
    streamer.stop_app()
    return {"status": "stopped"}


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket):
    await websocket.accept()
    logger.info("[PrototypeServer] WebSocket client connected for desktop stream")

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
                    streamer.inject_mouse(
                        event_type=msg.get("event", "click"),
                        norm_x=float(msg.get("norm_x", 0.0)),
                        norm_y=float(msg.get("norm_y", 0.0)),
                        button=msg.get("button", "left"),
                    )
                elif mtype == "key":
                    streamer.inject_key(
                        event_type=msg.get("event", "keydown"),
                        key=msg.get("key", ""),
                        char_code=msg.get("char_code"),
                    )
                elif mtype == "text":
                    streamer.inject_text(text=msg.get("text", ""))
        except (WebSocketDisconnect, asyncio.CancelledError):
            active = False
        except Exception as e:
            logger.debug(f"[PrototypeServer] Incoming reader error: {e}")
            active = False

    reader_task = asyncio.create_task(incoming_reader())

    try:
        while active:
            if streamer.target_hwnd:
                loop_start = time.perf_counter()
                jpeg_bytes, cap_ms, metrics = streamer.capture_frame(quality=75)

                if jpeg_bytes:
                    b64_frame = base64.b64encode(jpeg_bytes).decode("ascii")
                    payload = json.dumps({
                        "type": "frame",
                        "image": b64_frame,
                        "capture_ms": cap_ms,
                        "width": metrics.get("width"),
                        "height": metrics.get("height"),
                        "title": streamer.get_window_metrics().get("title", ""),
                        "hwnd": streamer.target_hwnd,
                        "timestamp": time.time(),
                    })
                    await websocket.send_text(payload)

                elapsed = time.perf_counter() - loop_start
                # Cap at ~25 FPS (40ms per frame)
                sleep_time = max(0.01, 0.04 - elapsed)
                await asyncio.sleep(sleep_time)
            else:
                await asyncio.sleep(0.2)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        active = False
        reader_task.cancel()
        logger.info("[PrototypeServer] WebSocket stream ended")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8202, log_level="info")
