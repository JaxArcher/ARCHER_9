---
name: pc_control
description: Desktop automation and browser control tools
category: automation
---

# PC Control Tools

## Read-Only Tools (No confirmation needed)

### take_screenshot
Capture the screen and return as base64 PNG.

**Parameters:**
- region: (optional) {left, top, width, height} for specific area

### get_active_window
Get title and geometry of currently active window.

### list_windows  
List all visible windows with titles and positions.

### browser_get_text
Get text content from browser element by CSS selector.

**Parameters:**
- selector: CSS selector (default: body)

### browser_screenshot
Take screenshot of active browser page.

---

## Action Tools (Require confirmation)

### open_url
Open URL in Playwright-managed Chromium browser.

**Parameters:**
- url: string - URL to open

### click
Click at screen coordinates.

**Parameters:**
- x: integer - X coordinate
- y: integer - Y coordinate  
- button: 'left' | 'right' | 'middle' (default: left)

### type_text
Type text at current cursor position.

**Parameters:**
- text: string - Text to type

### hotkey
Press keyboard shortcut.

**Parameters:**
- keys: array of strings - Keys to press together (e.g. ['ctrl', 'c'])

### focus_window
Bring window to focus by partial title match.

**Parameters:**
- title: string - Partial window title

### browser_click
Click element in browser by CSS selector.

**Parameters:**
- selector: string - CSS selector

### browser_type
Type text into browser element.

**Parameters:**
- selector: string - CSS selector for input element
- text: string - Text to type

### close_browser
Close the Playwright browser instance.
