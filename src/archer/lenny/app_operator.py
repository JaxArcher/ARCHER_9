"""
ARCHER App Operator for LENNY (Phase 8, Spec Section 11).

Implements the three ways of operating Windows applications on LENNY in order:
1. App Automation (Office COM for Word, Excel, PowerPoint; direct file operations)
2. UI Automation (inspect control tree by name, automation ID, role; invoke or click)
3. Look and Click (Local Vision Model on Main PC e.g. qwen2.5vl:7b with visual grounding,
   transiently loaded and immediately unloaded with keep_alive=0; zero cloud APIs)
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.lenny.lenny_client import LennyClient, get_lenny_client


class AppOperator:
    """Orchestrates application control on LENNY following the 3-tier hierarchy."""

    def __init__(self, client: Optional[LennyClient] = None) -> None:
        self.client = client or get_lenny_client()
        self.config = get_config()
        self.bus = get_event_bus()

    # =========================================================================
    # Tier 1: App Automation (Microsoft Office COM)
    # =========================================================================

    def create_word_document(
        self,
        title: str,
        paragraphs: List[str],
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Tier 1: Create a Word document using native Office COM on LENNY."""
        logger.info(f"[AppOperator] Tier 1: Creating Word document '{title}' on LENNY")
        return self.client.create_word_document(title=title, paragraphs=paragraphs, filename=filename)

    def create_excel_sheet(
        self,
        sheet_name: str,
        rows: List[List[Any]],
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Tier 1: Create an Excel spreadsheet using native Office COM on LENNY."""
        logger.info(f"[AppOperator] Tier 1: Creating Excel sheet '{sheet_name}' on LENNY")
        return self.client.create_excel_sheet(sheet_name=sheet_name, rows=rows, filename=filename)

    # =========================================================================
    # Tier 2: UI Automation (UIA)
    # =========================================================================

    def click_uia_control(self, identifier: str, window_title: Optional[str] = None) -> bool:
        """Tier 2: Find UI control by name or automation ID and click/invoke it."""
        logger.info(f"[AppOperator] Tier 2: Attempting UIA invoke for '{identifier}'")
        controls = self.client.get_uia_controls(window_title=window_title)
        if not controls:
            logger.warning("[AppOperator] Tier 2: No UIA controls returned")
            return False

        id_lower = identifier.lower().strip()
        matched: Optional[Dict[str, Any]] = None

        # Search for exact or substring match in name, automation_id, or class_name
        for ctrl in controls:
            c_name = str(ctrl.get("name", "")).lower()
            c_id = str(ctrl.get("automation_id", "")).lower()
            if id_lower == c_name or id_lower == c_id:
                matched = ctrl
                break
            if id_lower in c_name:
                matched = ctrl

        if matched:
            rect = matched.get("rect")
            if rect and len(rect) == 4:
                # Calculate center coordinates and click
                l, t, r, b = rect
                if r > l and b > t:
                    cx = (l + r) / 2.0
                    cy = (t + b) / 2.0
                    # Normalizing against typical 1920x1080 if absolute bounds are in pixels
                    # Note: Hands send_mouse takes normalized 0.0 - 1.0 coordinates
                    # If screen dimensions are available, normalize:
                    screen_w = 1920.0
                    screen_h = 1080.0
                    norm_x = min(1.0, max(0.0, cx / screen_w))
                    norm_y = min(1.0, max(0.0, cy / screen_h))
                    logger.info(f"[AppOperator] Tier 2: Clicking UIA control '{matched.get('name')}' at ({norm_x:.3f}, {norm_y:.3f})")
                    return self.client.send_mouse("click", norm_x, norm_y)

            # Fallback to direct invoke
            ctrl_id = matched.get("automation_id") or matched.get("name")
            return self.client.invoke_uia_control(ctrl_id, window_title=window_title)

        logger.debug(f"[AppOperator] Tier 2: Control '{identifier}' not found in UIA tree")
        return False

    def type_uia_control(self, identifier: str, text: str, window_title: Optional[str] = None) -> bool:
        """Tier 2: Click control to focus and type text."""
        if self.click_uia_control(identifier, window_title=window_title):
            time.sleep(0.1)
            return self.client.send_keyboard(text=text)
        return False

    # =========================================================================
    # Tier 3: Look and Click (Local Vision Model on Main PC)
    # =========================================================================

    def look_and_click(
        self,
        target_description: str,
        action: str = "click",
        window_title: Optional[str] = None,
        model_name: str = "qwen2.5vl:7b",
    ) -> bool:
        """
        Tier 3: Capture screenshot from LENNY, query local VLM on Main PC for click coordinates,
        send input to LENNY, and unload VLM immediately (keep_alive=0) to conserve VRAM.
        Zero pay-per-use APIs.
        """
        logger.info(f"[AppOperator] Tier 3: Look-and-click targeting '{target_description}' using local VLM ({model_name})")

        try:
            # 1. Fetch screenshot from LENNY
            screenshot_bytes = self.client.get_screenshot()
            b64_img = base64.b64encode(screenshot_bytes).decode("ascii")

            # 2. Query local Ollama instance on Main PC
            ollama_url = f"{self.config.ollama_base_url}/api/generate"
            prompt = (
                f"You are a computer vision assistant for a desktop interface. "
                f"Locate the element or button described as: '{target_description}'. "
                f"Return ONLY a JSON object with integer coordinates between 0 and 1000 representing "
                f"the center of the target as a fraction of 1000 of the total width and height. "
                f'Example: {{"x": 450, "y": 120}}\n'
                f"Do not include explanation or markdown code formatting, only valid JSON."
            )

            payload = {
                "model": model_name,
                "prompt": prompt,
                "images": [b64_img],
                "stream": False,
                # Spec: Load only when needed and unload after to preserve VRAM
                "keep_alive": 0,
            }

            coords: Optional[Tuple[float, float]] = None
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(ollama_url, json=payload)
                if resp.status_code == 200:
                    resp_data = resp.json()
                    response_text = resp_data.get("response", "").strip()
                    logger.debug(f"[AppOperator] VLM Grounding response: {response_text}")

                    # Extract coordinates from JSON
                    json_match = re.search(r"\{[^{}]*\}", response_text)
                    if json_match:
                        parsed = json.loads(json_match.group(0))
                        raw_x = float(parsed.get("x", 0))
                        raw_y = float(parsed.get("y", 0))

                        # Normalize to 0.0 .. 1.0
                        norm_x = min(1.0, max(0.0, raw_x / 1000.0 if raw_x > 1.0 else raw_x))
                        norm_y = min(1.0, max(0.0, raw_y / 1000.0 if raw_y > 1.0 else raw_y))
                        coords = (norm_x, norm_y)

            if coords is None:
                logger.warning(f"[AppOperator] Tier 3: Could not resolve coordinates for '{target_description}'")
                return False

            norm_x, norm_y = coords
            logger.info(f"[AppOperator] Tier 3: Resolved coordinates ({norm_x:.3f}, {norm_y:.3f}). Sending {action} to LENNY.")

            # 3. Send action to LENNY
            if action in ("click", "mousedown", "mouseup"):
                return self.client.send_mouse(action, norm_x, norm_y)
            elif action == "doubleclick":
                self.client.send_mouse("click", norm_x, norm_y)
                time.sleep(0.05)
                return self.client.send_mouse("click", norm_x, norm_y)

            return False

        except Exception as e:
            logger.error(f"[AppOperator] Tier 3 look_and_click error: {e}")
            return False

    # =========================================================================
    # Unified Execution Method
    # =========================================================================

    def operate(
        self,
        target: str,
        action: str = "click",
        value: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute an operation using the 3-tier hierarchy:
        1. Office COM / App Automation
        2. UI Automation
        3. Local Vision Look-and-Click
        """
        # Tier 1: Office COM check
        if "word" in target.lower() and action == "create":
            res = self.create_word_document(title=value or target, paragraphs=[], filename=f"{target}.docx")
            return {"tier": 1, "method": "Office COM Word", "result": res, "success": True}

        if ("excel" in target.lower() or "sheet" in target.lower()) and action == "create":
            res = self.create_excel_sheet(sheet_name="Data", rows=[], filename=f"{target}.xlsx")
            return {"tier": 1, "method": "Office COM Excel", "result": res, "success": True}

        # Tier 2: UI Automation
        uia_success = False
        if action == "click":
            uia_success = self.click_uia_control(target, window_title=window_title)
        elif action == "type" and value:
            uia_success = self.type_uia_control(target, value, window_title=window_title)

        if uia_success:
            return {"tier": 2, "method": "UI Automation", "success": True, "target": target}

        # Tier 3: Local Vision Look-and-Click
        logger.info(f"[AppOperator] Falling back to Tier 3 Look-and-Click for '{target}'")
        vlm_success = self.look_and_click(target, action=action, window_title=window_title)
        if vlm_success:
            if action == "type" and value:
                time.sleep(0.1)
                self.client.send_keyboard(text=value)
            return {"tier": 3, "method": "Look-and-Click (Local VLM)", "success": True, "target": target}

        return {"tier": 0, "method": "none", "success": False, "target": target, "error": "All 3 tiers failed"}
