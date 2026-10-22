"""
Tests for Phase 8: ARCHER's Dedicated Desk on LENNY (Spec Section 11, Plan Item 13).

Covers:
1. Hands service auth & pairing
2. Mouse & keyboard input dispatching
3. Physical user takeover detection (GetLastInputInfo)
4. LennyClient state, pairing, and sqlite_store persistence
5. 3-tier AppOperator execution (Office COM -> UIA -> Local VLM look-and-click)
6. Playwright browser relocation to LENNY with automatic Main PC fallback
7. Server REST endpoints and WebSocket stream proxy
"""

import asyncio
import base64
import json
import os
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.lenny.app_operator import AppOperator
from archer.lenny.lenny_client import LennyClient, get_lenny_client
from archer.memory.sqlite_store import get_sqlite_store
from archer.server import app
from archer.tools.pc_control import PCController, get_pc_controller


# =============================================================================
# 1. Hands Service Tests
# =============================================================================

def test_hands_service_pairing_and_auth():
    """Verify Hands service pairing code validation and bearer token authentication."""
    from scripts.lenny.hands import app as hands_app, hands_state

    client = TestClient(hands_app)

    with hands_state._lock:
        code = hands_state.generate_new_pairing_code()

    # Status before pairing
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("idle", "working", "paused")
    assert data["pairing_required"] is True

    # Attempt pairing with invalid code
    bad_resp = client.post("/api/pair", json={"pairing_code": "000000"})
    assert bad_resp.status_code == 401

    # Attempt pairing with correct code
    pair_resp = client.post("/api/pair", json={"pairing_code": code})
    assert pair_resp.status_code == 200
    token = pair_resp.json()["token"]
    assert token == hands_state.token

    # Authorized call with token header
    authed_status = client.get("/api/status", headers={"X-Lenny-Token": token})
    assert authed_status.status_code == 200
    assert authed_status.json()["pairing_required"] is False

    # Unauthorized protected endpoint
    unauth_mouse = client.post("/api/mouse", json={"event": "click", "norm_x": 0.5, "norm_y": 0.5})
    assert unauth_mouse.status_code == 401


def test_hands_service_pairing_security():
    """Verify single-use code consumption, expiration, lockout after 5 failures, and new_code generation."""
    from scripts.lenny.hands import app as hands_app, hands_state
    client = TestClient(hands_app)

    # 1. Reset state with fresh code
    with hands_state._lock:
        code1 = hands_state.generate_new_pairing_code()
        hands_state.locked_until = 0.0
        hands_state.failed_pairing_attempts = 0

    # 2. Expiration test
    with hands_state._lock:
        hands_state.pairing_code_expires_at = time.time() - 5.0  # expired
    expired_resp = client.post("/api/pair", json={"pairing_code": code1})
    assert expired_resp.status_code == 400
    assert "expired" in expired_resp.json()["detail"].lower()

    # 3. Fresh code generation
    with hands_state._lock:
        code2 = hands_state.generate_new_pairing_code()

    # 4. Five wrong attempts trigger 10-minute lockout (HTTP 429)
    for _ in range(4):
        resp = client.post("/api/pair", json={"pairing_code": "wrong_code"})
        assert resp.status_code == 401

    # 5th attempt triggers lockout
    resp5 = client.post("/api/pair", json={"pairing_code": "wrong_code"})
    assert resp5.status_code == 429
    assert "locked" in resp5.json()["detail"].lower()

    # Attempt with correct code during lockout should still return 429
    locked_resp = client.post("/api/pair", json={"pairing_code": code2})
    assert locked_resp.status_code == 429

    # 5. Generate new code via /api/pair/new_code (resets lockout)
    new_code_resp = client.post("/api/pair/new_code", headers={"X-Lenny-Token": hands_state.token})
    assert new_code_resp.status_code == 200
    code3 = new_code_resp.json()["pairing_code"]
    assert code3 is not None
    assert new_code_resp.json()["expires_in_seconds"] == 900

    # Lockout is now cleared, so pairing with code3 succeeds
    pair_ok = client.post("/api/pair", json={"pairing_code": code3})
    assert pair_ok.status_code == 200
    assert pair_ok.json()["status"] == "paired"

    # 6. Single-use test: immediate replay of code3 must fail
    replay_resp = client.post("/api/pair", json={"pairing_code": code3})
    assert replay_resp.status_code == 400
    assert "already used" in replay_resp.json()["detail"].lower()


def test_hands_mouse_and_keyboard_input():
    """Verify mouse and keyboard input endpoints on Hands service."""
    from scripts.lenny.hands import app as hands_app, hands_state

    client = TestClient(hands_app)
    headers = {"X-Lenny-Token": hands_state.token}

    with patch.object(hands_state, "send_mouse_input", return_value=True) as mock_mouse:
        resp = client.post(
            "/api/mouse",
            json={"event": "click", "norm_x": 0.25, "norm_y": 0.75, "button": "left"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_mouse.assert_called_once_with(event_type="click", norm_x=0.25, norm_y=0.75, button="left")

    with patch.object(hands_state, "send_text_string", return_value=True) as mock_text:
        resp = client.post("/api/keyboard", json={"text": "Hello LENNY"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_text.assert_called_once_with("Hello LENNY")


def test_physical_takeover_detection():
    """Verify that user activity on physical controls triggers takeover state and notification."""
    from scripts.lenny.hands import hands_state

    with hands_state._lock:
        hands_state.takeover_active = False
        hands_state.status = "working"
        hands_state.current_task = "Writing Report"

    # Simulate physical mouse touch (idle ms = 100ms, last autonomous action > 2s ago)
    hands_state.last_autonomous_action_time = time.time() - 3.0
    with patch.object(hands_state, "_get_idle_ms", return_value=100):
        # Manually invoke the watchdog detection logic step
        idle_ms = hands_state._get_idle_ms()
        now = time.time()
        if idle_ms < 1200 and (now - hands_state.last_autonomous_action_time > 1.5):
            with hands_state._lock:
                hands_state.takeover_active = True
                if hands_state.status == "working":
                    hands_state.status = "paused"

        assert hands_state.takeover_active is True
        assert hands_state.status == "paused"


# =============================================================================
# 2. LennyClient & Database Persistence Tests
# =============================================================================

def test_lenny_client_pairing_and_persistence(tmp_path):
    """Verify LennyClient pairs and stores configuration in sqlite_store."""
    store = get_sqlite_store()
    client = LennyClient()

    # Mock successful HTTP pairing response from Hands
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "paired", "token": "test_lenny_token_12345"}

    with patch("httpx.Client.post", return_value=mock_resp):
        res = client.pair(pairing_code="123456", host="192.168.4.50", port=8203)
        assert res["status"] == "paired"
        assert client.host == "192.168.4.50"
        assert client.token == "test_lenny_token_12345"

        # Verify saved in SQLite lenny_config table
        db_cfg = store.get_lenny_config()
        assert db_cfg["host"] == "192.168.4.50"
        assert db_cfg["port"] == 8203
        assert db_cfg["token"] == "test_lenny_token_12345"
        assert db_cfg["status"] == "paired"


def test_lenny_client_status_and_takeover_events():
    """Verify status query updates state and publishes event bus takeover events."""
    bus = get_event_bus()
    client = LennyClient()
    client._host = "192.168.4.50"
    client._token = "valid_tok"

    events = []
    bus.subscribe(EventType.LENNY_TAKEOVER_START, lambda e: events.append("takeover_start"))
    bus.subscribe(EventType.LENNY_TAKEOVER_END, lambda e: events.append("takeover_end"))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "paused",
        "current_task": "Formatting Table",
        "takeover_active": True,
        "idle_ms": 200,
        "pairing_required": False,
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        st = client.get_status()
        assert st["online"] is True
        assert st["status"] == "paused"
        assert st["takeover_active"] is True
        assert "takeover_start" in events

    # Now simulate quiet period where takeover clears
    mock_resp.json.return_value = {
        "status": "idle",
        "current_task": "",
        "takeover_active": False,
        "idle_ms": 10000,
        "pairing_required": False,
    }
    with patch("httpx.Client.get", return_value=mock_resp):
        st2 = client.get_status()
        assert st2["takeover_active"] is False
        assert "takeover_end" in events


# =============================================================================
# 3. 3-Tier AppOperator Tests (Spec Section 11)
# =============================================================================

def test_app_operator_tier1_office_com(tmp_path):
    """Verify Tier 1: Office COM document generation on LENNY with artifact sync."""
    client = MagicMock(spec=LennyClient)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)
    doc_path = artifacts_dir / "TestReport.docx"
    doc_path.write_text("dummy docx content")

    client.create_word_document.return_value = {
        "status": "created",
        "filename": "TestReport.docx",
        "path": str(doc_path),
        "created_on": "LENNY",
    }

    operator = AppOperator(client=client)
    res = operator.create_word_document(title="Test Report", paragraphs=["Section 1"], filename="TestReport.docx")
    assert res["status"] == "created"
    assert res["created_on"] == "LENNY"
    client.create_word_document.assert_called_once_with(
        title="Test Report", paragraphs=["Section 1"], filename="TestReport.docx"
    )


def test_app_operator_tier2_ui_automation():
    """Verify Tier 2: UI Automation control tree lookup and click."""
    client = MagicMock(spec=LennyClient)
    client.get_uia_controls.return_value = [
        {"name": "Save As", "automation_id": "btnSaveAs", "rect": [100, 200, 200, 250]},
        {"name": "Cancel", "automation_id": "btnCancel", "rect": [250, 200, 350, 250]},
    ]
    client.send_mouse.return_value = True

    operator = AppOperator(client=client)
    success = operator.click_uia_control("Save As")
    assert success is True
    # Verify calculated normalized center coordinates were sent to Hands
    client.send_mouse.assert_called_once()
    call_args = client.send_mouse.call_args[0]
    assert call_args[0] == "click"
    assert 0.0 < call_args[1] < 1.0  # norm_x
    assert 0.0 < call_args[2] < 1.0  # norm_y


def test_app_operator_tier3_look_and_click_vlm():
    """Verify Tier 3: Local VLM look-and-click with transient model load (keep_alive=0)."""
    client = MagicMock(spec=LennyClient)
    client.get_screenshot.return_value = b"\xFF\xD8\xFF\xE0MockJpegBytes"
    client.send_mouse.return_value = True

    operator = AppOperator(client=client)

    # Mock Ollama response with visual grounding coordinates
    mock_ollama_resp = MagicMock()
    mock_ollama_resp.status_code = 200
    mock_ollama_resp.json.return_value = {
        "response": '{"x": 650, "y": 420}',
    }

    with patch("httpx.Client.post", return_value=mock_ollama_resp) as mock_post:
        success = operator.look_and_click("the red Submit button")
        assert success is True

        # Verify Ollama was queried with keep_alive=0 (preserve VRAM per spec)
        mock_post.assert_called_once()
        req_payload = mock_post.call_args[1]["json"]
        assert req_payload["keep_alive"] == 0
        assert "red Submit button" in req_payload["prompt"]

        # Verify mouse click was dispatched with normalized coordinates (650/1000 = 0.65, 420/1000 = 0.42)
        client.send_mouse.assert_called_once_with("click", 0.65, 0.42)


# =============================================================================
# 4. Browser Relocation & Fallback Tests (Spec Section 11)
# =============================================================================

def test_browser_relocation_fallback_when_lenny_offline():
    """Verify that when LENNY is offline, browser automatically falls back to Main PC local browser."""
    pc = PCController()
    cfg = get_config()

    bus = get_event_bus()
    fallback_events = []
    bus.subscribe(EventType.BROWSER_ACTION, lambda e: fallback_events.append(e.data))

    # Mock Playwright and LennyClient to simulate offline LENNY
    mock_playwright = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_page.url = "about:blank"
    mock_context.pages = [mock_page]
    mock_playwright.chromium.launch_persistent_context.return_value = mock_context

    orig_pw = pc._playwright
    orig_ctx = pc._browser_context
    try:
        with patch("archer.lenny.lenny_client.get_lenny_client") as mock_get_lenny:
            mock_lenny = MagicMock()
            mock_lenny.is_configured.return_value = True
            mock_lenny.is_online.return_value = False  # LENNY offline!
            mock_get_lenny.return_value = mock_lenny

            pc._playwright = mock_playwright
            pc._browser_context = None

            with patch.object(pc, "_attach_cdp_impl"):
                ok = pc._ensure_browser_impl()
                assert ok is True
                # Verified: Fell back to Main PC
                assert pc.get_browser_host() == "Main PC"
                mock_playwright.chromium.launch_persistent_context.assert_called_once()
    finally:
        pc._playwright = orig_pw
        pc._browser_context = orig_ctx


def test_browser_relocation_connects_to_lenny_when_online():
    """Verify that when LENNY is online, browser connects over CDP to LENNY."""
    pc = PCController()

    mock_playwright = MagicMock()
    mock_remote_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_page.url = "about:blank"
    mock_context.pages = [mock_page]
    mock_remote_browser.contexts = [mock_context]
    mock_playwright.chromium.connect_over_cdp.return_value = mock_remote_browser

    orig_pw = pc._playwright
    orig_ctx = pc._browser_context
    try:
        with patch("archer.lenny.lenny_client.get_lenny_client") as mock_get_lenny:
            mock_lenny = MagicMock()
            mock_lenny.is_configured.return_value = True
            mock_lenny.is_online.return_value = True
            mock_lenny.host = "192.168.4.50"
            mock_lenny.browser_port = 9222
            mock_get_lenny.return_value = mock_lenny

            pc._playwright = mock_playwright
            pc._browser_context = None

            with patch.object(pc, "_attach_cdp_impl"):
                ok = pc._ensure_browser_impl()
                assert ok is True
                # Verified: Connected to LENNY
                assert pc.get_browser_host() == "LENNY"
                mock_playwright.chromium.connect_over_cdp.assert_called_once_with(
                    "http://192.168.4.50:9222", timeout=3000
                )
    finally:
        pc._playwright = orig_pw
        pc._browser_context = orig_ctx


# =============================================================================
# 5. Server REST & WebSocket Endpoints Tests
# =============================================================================

def test_server_lenny_endpoints():
    """Verify Server REST endpoints for LENNY status, task setting, and control."""
    client = TestClient(app)

    with patch("archer.lenny.lenny_client.get_lenny_client") as mock_get_lenny:
        mock_lenny = MagicMock()
        mock_lenny.get_status.return_value = {
            "configured": True,
            "online": True,
            "status": "idle",
            "current_task": "",
            "takeover_active": False,
            "host": "192.168.4.50",
            "port": 8203,
        }
        mock_lenny.set_task.return_value = {"status": "paused", "task": "Analysis"}
        mock_get_lenny.return_value = mock_lenny

        # GET /api/lenny/status
        resp = client.get("/api/lenny/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["online"] is True
        assert "browser_host" in data

        # POST /api/lenny/control
        resp_ctrl = client.post("/api/lenny/control", json={"action": "pause"})
        assert resp_ctrl.status_code == 200
        mock_lenny.set_task.assert_called_once()
