---
name: pc_control
description: Desktop automation and browser control tools
category: automation
---

# PC Control Tools

## Read-Only Tools (No confirmation needed)

### take_screenshot
Capture the user's actual desktop/monitor and return as base64 PNG. Use this for
any request about "my screen", "my computer screen", "what's on my monitor",
etc. -- i.e. anything NOT specifically about a page ARCHER itself opened in
its own automated browser.

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
Take a screenshot of the page currently open in ARCHER's OWN automated
Playwright browser (the one open_url opens) -- NOT the user's desktop, and
NOT any browser window the user opened themselves. Only useful right after
open_url in the same conversation. Errors if no such page exists yet.

---

## Action Tools (Require confirmation)

### open_url
Open URL in Playwright-managed Chromium browser. Resolve the url yourself
from what the user named (e.g. "YouTube" -> "https://youtube.com") -- never
reuse a placeholder/example URL (like example.com) that appeared earlier in
the conversation just because it's the only concrete URL around. If the
user's request doesn't clearly name a site, ask which site instead of
guessing.

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
