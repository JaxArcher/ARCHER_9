"""
Tests for Phase 7c: ARCHER on Col's iPad Air (Spec Section 10c).

Verifies:
1. Safari 12 / iOS 12 compatibility (Zero optional chaining, zero nullish coalescing, zero BigInt).
2. Pairing flow, cryptographic token generation, and authorization gating.
3. Unpaired device isolation (401 Unauthorized).
4. PC System Tab pairing management (get pairing, generate fresh code, revoke pairing).
5. Chat sending, history, and EventBus integration.
6. Approval prompts display and touch response resolution.
7. Away & Tasks checklist and toggle.
8. Items search and photo endpoint.
9. WebSocket connection authentication, init state, and real-time event streaming.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from archer.config import get_config
from archer.core.approvals import get_approval_manager
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.ipad_server import ipad_app, _record_chat
from archer.memory.sqlite_store import get_sqlite_store
from archer.server import app as main_pc_app


@pytest.fixture(autouse=True)
def clean_ipad_state():
    """Ensure clean test database state before and after each test."""
    store = get_sqlite_store()
    store.revoke_device_pairing(device_type="ipad")
    yield
    store.revoke_device_pairing(device_type="ipad")


def test_safari12_compatibility():
    """Guarantee strict compatibility with Apple Safari 12 and iOS 12."""
    js_path = Path("web/ipad/app.js")
    assert js_path.exists(), "web/ipad/app.js must exist"
    raw_content = js_path.read_text(encoding="utf-8")

    # Strip comments to inspect executable code
    clean_code = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*", "", raw_content), flags=re.DOTALL)

    # 1. No optional chaining (?.)
    assert "?." not in clean_code, "Found forbidden optional chaining (?.) in web/ipad/app.js"

    # 2. No nullish coalescing (??)
    assert "??" not in clean_code, "Found forbidden nullish coalescing (??) in web/ipad/app.js"

    # 3. No BigInt
    assert "BigInt" not in clean_code, "Found forbidden BigInt in web/ipad/app.js"

    # 4. No replaceAll
    assert "replaceAll" not in clean_code, "Found forbidden replaceAll in web/ipad/app.js"

    # 5. Check index.html for iOS Web Clip meta tags
    html_path = Path("web/ipad/index.html")
    assert html_path.exists()
    html_content = html_path.read_text(encoding="utf-8")
    assert "apple-mobile-web-app-capable" in html_content
    assert "apple-touch-icon" in html_content


def test_ipad_pairing_flow_and_token_gating():
    """Verify 6-digit pairing code generation, validation, and token authentication."""
    client = TestClient(ipad_app)
    store = get_sqlite_store()

    # 1. Unpaired device status
    res = client.get("/api/ipad/status")
    assert res.status_code == 200
    data = res.json()
    assert data["paired"] is False

    # 2. Protected endpoints reject unpaired requests with 401
    assert client.get("/api/ipad/chat/history").status_code == 401
    assert client.get("/api/ipad/tasks").status_code == 401
    assert client.get("/api/ipad/away").status_code == 401
    assert client.get("/api/ipad/items").status_code == 401
    assert client.get("/api/ipad/approvals").status_code == 401

    # 3. Get active pending code from store
    pairing_info = store.get_or_create_pairing_code(device_type="ipad")
    code = pairing_info["pairing_code"]
    assert len(code) == 6
    assert code.isdigit()

    # 4. Bad code fails with 400
    bad_res = client.post("/api/ipad/pair", json={"code": "000000"})
    assert bad_res.status_code == 400

    # 5. Good code pairs successfully and returns bearer token
    good_res = client.post("/api/ipad/pair", json={"code": code, "device_name": "Col's iPad Air"})
    assert good_res.status_code == 200
    pair_data = good_res.json()
    assert pair_data["status"] == "paired"
    token = pair_data["token"]
    assert token and len(token) > 20

    # 6. Status now reports paired
    status_res = client.get("/api/ipad/status")
    assert status_res.status_code == 200
    assert status_res.json()["paired"] is True
    assert status_res.json()["device_name"] == "Col's iPad Air"

    # 7. Authenticated request with Bearer header succeeds
    headers = {"Authorization": f"Bearer {token}"}
    tasks_res = client.get("/api/ipad/tasks", headers=headers)
    assert tasks_res.status_code == 200
    assert "tasks" in tasks_res.json()

    # 8. Authenticated request with query parameter succeeds
    away_res = client.get(f"/api/ipad/away?token={token}")
    assert away_res.status_code == 200
    assert "interventions" in away_res.json()

    # 9. Revoke token
    assert store.revoke_device_pairing(device_type="ipad") is True
    assert client.get("/api/ipad/tasks", headers=headers).status_code == 401
    assert client.get("/api/ipad/status").json()["paired"] is False


def test_pc_system_tab_pairing_controls():
    """Verify PC server endpoints for managing iPad pairing from the System tab."""
    pc_client = TestClient(main_pc_app)

    # 1. GET /api/system/ipad_pairing returns active code and URL
    res = pc_client.get("/api/system/ipad_pairing")
    assert res.status_code == 200
    data = res.json()
    assert "pending_code" in data or data.get("paired") is True
    assert "lan_ip" in data
    assert "port" in data
    assert "url" in data

    # 2. POST /api/system/ipad_generate_code generates fresh code
    gen_res = pc_client.post("/api/system/ipad_generate_code")
    assert gen_res.status_code == 200
    new_code = gen_res.json()["pending_code"]
    assert len(new_code) == 6

    # 3. Pair using the new code on the iPad gateway
    ipad_client = TestClient(ipad_app)
    pair_res = ipad_client.post("/api/ipad/pair", json={"code": new_code})
    assert pair_res.status_code == 200
    token = pair_res.json()["token"]

    # 4. System tab now shows paired
    st_res = pc_client.get("/api/system/ipad_pairing")
    assert st_res.json()["paired"] is True

    # 5. Revoke from PC System tab
    rev_res = pc_client.post("/api/system/ipad_revoke")
    assert rev_res.status_code == 200
    assert rev_res.json()["paired"] is False

    # 6. iPad token is now invalid
    assert ipad_client.get("/api/ipad/tasks", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_ipad_chat_send_and_history():
    """Verify sending chat messages from iPad dispatches GUI_TEXT_INPUT and updates history."""
    client = TestClient(ipad_app)
    store = get_sqlite_store()

    # Pair device
    info = store.get_or_create_pairing_code()
    token = store.verify_and_pair_device(info["pairing_code"])
    headers = {"Authorization": f"Bearer {token}"}

    received_events = []
    bus = get_event_bus()

    def _on_input(e: Event):
        received_events.append(e.data)

    bus.subscribe(EventType.GUI_TEXT_INPUT, _on_input)

    # Send message from iPad
    msg_text = "Hey ARCHER, where are my keys?"
    send_res = client.post("/api/ipad/chat/send", json={"text": msg_text}, headers=headers)
    assert send_res.status_code == 200
    assert send_res.json()["status"] == "sent"

    # Verify event published on internal bus
    assert len(received_events) >= 1
    assert any(ev.get("text") == msg_text for ev in received_events)

    # Verify message in history
    hist_res = client.get("/api/ipad/chat/history", headers=headers)
    assert hist_res.status_code == 200
    history = hist_res.json()["messages"]
    assert any(m.get("text") == msg_text and m.get("role") == "user" for m in history)


def test_ipad_approvals_integration():
    """Verify approval prompt display and resolution from the iPad Air interface."""
    client = TestClient(ipad_app)
    store = get_sqlite_store()
    mgr = get_approval_manager()

    # Pair device
    info = store.get_or_create_pairing_code()
    token = store.verify_and_pair_device(info["pairing_code"])
    headers = {"Authorization": f"Bearer {token}"}

    # Simulate an active approval request in a background thread
    req_id = "test_req_ipad_123"
    event = asyncio.Event()

    with mgr._pending_lock:
        mgr._pending[req_id] = {
            "event": threading.Event(),
            "decision": None,
            "tool_name": "delete_file",
            "action_type": "file_operation",
            "description": "Delete temporary log file",
            "details": "Path: data/artifacts/temp.log",
            "prompted_by": "User request",
            "start_time": 0.0,
            "timeout": 30.0,
        }

    try:
        # Check that iPad can see pending approvals
        appr_res = client.get("/api/ipad/approvals", headers=headers)
        assert appr_res.status_code == 200
        reqs = appr_res.json()["requests"]
        assert any(r["request_id"] == req_id for r in reqs)

        # Approve the request from iPad
        resp_res = client.post(
            "/api/ipad/approvals/respond",
            json={"request_id": req_id, "decision": "approve"},
            headers=headers,
        )
        assert resp_res.status_code == 200
        assert resp_res.json()["status"] == "resolved"
        assert resp_res.json()["decision"] == "approve"

        # Verify decision set on ApprovalManager
        assert mgr._pending[req_id]["decision"] == "approve"
        assert mgr._pending[req_id]["event"].is_set()
    finally:
        with mgr._pending_lock:
            mgr._pending.pop(req_id, None)


def test_ipad_tasks_and_away_endpoints():
    """Verify task checklist, completion toggle, and While You Were Away queries."""
    client = TestClient(ipad_app)
    store = get_sqlite_store()

    # Pair device
    info = store.get_or_create_pairing_code()
    token = store.verify_and_pair_device(info["pairing_code"])
    headers = {"Authorization": f"Bearer {token}"}

    # Add a test task in the database
    conn = store._get_connection()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO tasks (title, due_date, source) VALUES ('Test iPad task', 'Tomorrow', 'ipad_test')"
            )
            task_id = cur.lastrowid
    finally:
        conn.close()

    # 1. Fetch tasks
    tasks_res = client.get("/api/ipad/tasks", headers=headers)
    assert tasks_res.status_code == 200
    tasks = tasks_res.json()["tasks"]
    test_task = next((t for t in tasks if t["id"] == task_id), None)
    assert test_task is not None
    assert test_task["status"] == "pending"

    # 2. Toggle task to completed
    toggle_res = client.post(
        "/api/ipad/tasks/toggle",
        json={"task_id": task_id, "completed": True},
        headers=headers,
    )
    assert toggle_res.status_code == 200

    # 3. Verify task is completed
    updated_tasks = client.get("/api/ipad/tasks", headers=headers).json()["tasks"]
    up_task = next(t for t in updated_tasks if t["id"] == task_id)
    assert up_task["status"] == "completed"

    # 4. Fetch Away interventions
    away_res = client.get("/api/ipad/away", headers=headers)
    assert away_res.status_code == 200
    assert "interventions" in away_res.json()


def test_ipad_items_query():
    """Verify item location query and photo availability check."""
    client = TestClient(ipad_app)
    store = get_sqlite_store()

    # Pair device
    info = store.get_or_create_pairing_code()
    token = store.verify_and_pair_device(info["pairing_code"])
    headers = {"Authorization": f"Bearer {token}"}

    # Query items list
    items_res = client.get("/api/ipad/items", headers=headers)
    assert items_res.status_code == 200
    assert "items" in items_res.json()

    # Query with filter
    search_res = client.get("/api/ipad/items?query=keys", headers=headers)
    assert search_res.status_code == 200
    assert isinstance(search_res.json()["items"], list)

    # Missing photo returns 404
    photo_res = client.get("/api/ipad/items/photo/99999", headers=headers)
    assert photo_res.status_code == 404


def test_ipad_websocket_auth_and_messaging():
    """Verify WebSocket connection authentication, init snapshot, and ping/pong."""
    client = TestClient(ipad_app)
    store = get_sqlite_store()

    # 1. Connecting without token or with bad token is rejected
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/ipad"):
            pass

    with pytest.raises(Exception):
        with client.websocket_connect("/ws/ipad?token=bad_token_123"):
            pass

    # 2. Connect with valid token
    info = store.get_or_create_pairing_code()
    token = store.verify_and_pair_device(info["pairing_code"])

    with client.websocket_connect(f"/ws/ipad?token={token}") as ws:
        # Receives init packet
        init_raw = ws.receive_text()
        init_msg = json.loads(init_raw)
        assert init_msg["type"] == "init"
        assert "tasks" in init_msg
        assert "habits" in init_msg
        assert "interventions" in init_msg

        # Test ping / pong
        ws.send_text(json.dumps({"type": "ping"}))
        pong_raw = ws.receive_text()
        pong_msg = json.loads(pong_raw)
        assert pong_msg["type"] == "pong"
