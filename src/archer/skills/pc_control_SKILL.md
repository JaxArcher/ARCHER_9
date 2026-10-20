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
Open URL in ARCHER's own browser (Playwright-managed Chromium, mirrored in
ARCHER's page). This is the default for opening any site. Resolve the url yourself
from what the user named (e.g. "YouTube" -> "https://youtube.com") -- never
reuse a placeholder/example URL (like example.com) that appeared earlier in
the conversation just because it's the only concrete URL around. If the
user's request doesn't clearly name a site, ask which site instead of
guessing.

**Parameters:**
- url: string - URL to open

### play_youtube
Search YouTube for a song, video or topic and play the first video, in
ARCHER's own browser (shown in ARCHER's page). Use this for any request to
play, find or put on something on YouTube, including "search YouTube for X"
and "play X". Don't use open_url plus clicks for that.

**Parameters:**
- query: string - What to search for, e.g. "Beyonce Black Parade"

### open_url_in_my_browser
Open URL in Col's own web browser (his usual browser, with his sign-ins) as a
separate window. Use this ONLY when Col asks for a separate window, a new
window, or his own/normal browser; otherwise use open_url. ARCHER cannot see
or control that window afterwards (browser_screenshot and browser_click don't
work on it), so tell Col it's open and leave it to him.

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
