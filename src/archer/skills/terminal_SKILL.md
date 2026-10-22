---
name: Terminal
description: Run commands in ARCHER's visible PowerShell terminal in the Artifacts tab.
category: terminal
---

### run_terminal_command
Run a command in ARCHER's visible terminal session. Col can see the command running live in the Artifacts pane with a cyan [ARCHER] tag. Use this for running shell commands, builds, git queries, running scripts, or checking filesystem/system status.
**Parameters:**
- command: The PowerShell command string to execute (string).
- timeout: (optional) Timeout in seconds before auto-cancelling with Ctrl+C (default 30).
