---
name: ui_control
description: Controls for ARCHER's own browser/desktop interface (tabs, panels)
category: ui_control
---

# UI Control Tools

## Action Tools (No confirmation needed)

### switch_tab
Switch the active tab in the ARCHER browser client to the one named.

Use this when the user asks (by voice or text) to open, show, switch to,
or go to a specific tab in the ARCHER interface — for example "switch to
the gesture tab" or "open the dashboard". Currently available tab names:
`dashboard`, `gesture` (consolidated 2026-09-16 — the browser client used
to have five separate tabs: voice, logs, memory, tasks, system; they now
all live together as cards on one Dashboard tab, so any of those five
older names still works too and is treated as "dashboard"). If the user
asks for a tab that doesn't exist yet, tell them it isn't built yet
instead of calling this tool.

**Parameters:**
- tab_name: string - The tab to switch to (e.g. "dashboard", "gesture")
