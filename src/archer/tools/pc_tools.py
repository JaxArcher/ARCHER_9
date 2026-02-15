"""
ARCHER PC Control Tool Definitions.

Exposes the PCController methods as structured tool definitions that the
LLM can invoke via Anthropic's tool_use API. Each tool has a name,
description, and input_schema that Claude uses to decide when and how to
call it.

Safety:
- Read-only tools (screenshot, list_windows, get_active_window) execute
  immediately without confirmation.
- Action tools (open_url, click, type_text, hotkey, focus_window,
  browser_click, browser_type, close_browser) set `requires_confirmation=True`
  in their schema. The Orchestrator must present the action to the user
  and obtain verbal "yes" before executing.
- HALT cancels all pending and active PC control operations.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from archer.tools.pc_control import PCController


# --------------------------------------------------------------------------
# Tool schema definitions (Anthropic tool_use format)
# --------------------------------------------------------------------------

PC_TOOLS: list[dict[str, Any]] = [
    {
        "name": "take_screenshot",
        "description": (
            "Capture a screenshot of the primary monitor and return it as "
            "a base64-encoded PNG. Read-only — no confirmation needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region to capture: {left, top, width, height}",
                    "properties": {
                        "left": {"type": "integer"},
                        "top": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_active_window",
        "description": (
            "Get the title and geometry of the currently active window. "
            "Read-only — no confirmation needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_windows",
        "description": (
            "List all visible windows with titles and positions. "
            "Read-only — no confirmation needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "open_url",
        "description": (
            "Open a URL in the Playwright-managed Chromium browser. "
            "REQUIRES user confirmation before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": (
            "Click at screen coordinates (x, y). "
            "REQUIRES user confirmation before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "Mouse button (default: left)",
                },
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": (
            "Type text using keyboard simulation. "
            "REQUIRES user confirmation before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "hotkey",
        "description": (
            "Press a keyboard shortcut (e.g., ['ctrl', 'c']). "
            "REQUIRES user confirmation before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of keys to press simultaneously",
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "focus_window",
        "description": (
            "Focus a window by partial title match. "
            "REQUIRES user confirmation before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Partial window title to match",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "browser_click",
        "description": (
            "Click an element in the Playwright browser by CSS selector. "
            "REQUIRES user confirmation before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector for the element to click",
                },
            },
            "required": ["selector"],
        },
    },
    {
        "name": "browser_type",
        "description": (
            "Type text into a browser element by CSS selector. "
            "REQUIRES user confirmation before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector for the input element",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type into the element",
                },
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "browser_get_text",
        "description": (
            "Get text content from a browser element. "
            "Read-only — no confirmation needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector (default: body)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "browser_screenshot",
        "description": (
            "Take a screenshot of the active browser page. "
            "Read-only — no confirmation needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "close_browser",
        "description": (
            "Close the Playwright browser. "
            "REQUIRES user confirmation before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

# Tools that are read-only (no confirmation needed)
READ_ONLY_TOOLS = {
    "take_screenshot",
    "get_active_window",
    "list_windows",
    "browser_get_text",
    "browser_screenshot",
}

# Tools that require user confirmation before execution
CONFIRMATION_REQUIRED_TOOLS = {
    "open_url",
    "click",
    "type_text",
    "hotkey",
    "focus_window",
    "browser_click",
    "browser_type",
    "close_browser",
}


class PCToolExecutor:
    """
    Executes PC control tool calls from the LLM.

    Maps tool names to PCController methods and handles the
    confirmation flow for non-read-only tools.
    """

    def __init__(self) -> None:
        self._controller = PCController()

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a PC tool call.

        Returns a dict with 'result' key on success, 'error' on failure.
        For confirmation-required tools, the caller must have already
        obtained user confirmation before calling this method.
        """
        try:
            handler = getattr(self, f"_exec_{tool_name}", None)
            if handler is None:
                return {"error": f"Unknown tool: {tool_name}"}
            return handler(tool_input)
        except Exception as e:
            logger.error(f"PC tool execution failed ({tool_name}): {e}")
            return {"error": str(e)}

    def requires_confirmation(self, tool_name: str) -> bool:
        """Check if a tool requires user confirmation."""
        return tool_name in CONFIRMATION_REQUIRED_TOOLS

    def reset_halt(self) -> None:
        """Clear the HALT flag for new operations."""
        self._controller.reset_halt()

    # --- Tool handlers ---

    def _exec_take_screenshot(self, inp: dict) -> dict:
        region = inp.get("region")
        result = self._controller.take_screenshot(region)
        if result:
            return {"result": f"Screenshot captured ({len(result)} bytes base64)", "image": result}
        return {"error": "Screenshot capture failed"}

    def _exec_get_active_window(self, inp: dict) -> dict:
        return {"result": self._controller.get_active_window()}

    def _exec_list_windows(self, inp: dict) -> dict:
        windows = self._controller.list_windows()
        return {"result": windows}

    def _exec_open_url(self, inp: dict) -> dict:
        url = inp["url"]
        result = self._controller.open_url(url)
        return {"result": result}

    def _exec_click(self, inp: dict) -> dict:
        x, y = inp["x"], inp["y"]
        button = inp.get("button", "left")
        success = self._controller.click(x, y, button)
        return {"result": {"success": success}}

    def _exec_type_text(self, inp: dict) -> dict:
        text = inp["text"]
        success = self._controller.type_text(text)
        return {"result": {"success": success}}

    def _exec_hotkey(self, inp: dict) -> dict:
        keys = inp["keys"]
        success = self._controller.hotkey(*keys)
        return {"result": {"success": success}}

    def _exec_focus_window(self, inp: dict) -> dict:
        title = inp["title"]
        success = self._controller.focus_window(title)
        return {"result": {"success": success}}

    def _exec_browser_click(self, inp: dict) -> dict:
        selector = inp["selector"]
        success = self._controller.browser_click(selector)
        return {"result": {"success": success}}

    def _exec_browser_type(self, inp: dict) -> dict:
        selector = inp["selector"]
        text = inp["text"]
        success = self._controller.browser_type(selector, text)
        return {"result": {"success": success}}

    def _exec_browser_get_text(self, inp: dict) -> dict:
        selector = inp.get("selector", "body")
        text = self._controller.browser_get_text(selector)
        return {"result": text}

    def _exec_browser_screenshot(self, inp: dict) -> dict:
        result = self._controller.browser_screenshot()
        if result:
            return {"result": f"Browser screenshot captured", "image": result}
        return {"error": "No active browser page"}

    def _exec_close_browser(self, inp: dict) -> dict:
        self._controller.close_browser()
        return {"result": {"success": True}}
