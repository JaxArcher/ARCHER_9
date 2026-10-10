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
the files tab" or "open tools". Currently available tab names:
`files`, `artifacts`, `tools`, `away_tasks` (or "away & tasks"), `system`, `logs`.
Legacy tab names are automatically aliased (`gesture` -> `files`, `dashboard` / `voice` -> `artifacts`,
`memory` / `tasks` -> `away_tasks`). If the user asks for a tab that doesn't exist, tell them it isn't built yet
instead of calling this tool.

**Parameters:**
- tab_name: string - The tab to switch to (e.g. "files", "artifacts", "tools", "away_tasks", "system", "logs")

