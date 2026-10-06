# ARCHER Workspace Redesign — Specification & Antigravity Instructions (06OCT2026)

Owner: Col. Architecture and review: Claude. Implementation: Antigravity.

This package redesigns ARCHER's browser client into a fixed control column plus a
tabbed workspace, makes hand gestures work everywhere, and gives ARCHER real
hands: an approval system, a reviewed tool pool, documents, a terminal, an
embedded browser, and (last) any desktop app inside the page.

Read this whole document before starting. Build strictly phase by phase. Every
phase must leave ARCHER runnable. Do not start a phase until the previous one
passes its acceptance checks and Col has signed it off.

---

## 0. Rules for this build (non-negotiable)

1. **Phase 0 audit first.** Prior ARCHER builds failed because work was based on
   wrong assumptions about the code. Verify every "Current state" fact below
   against the actual files before changing anything. If a fact is wrong, stop
   and report it rather than building on it.
2. **Hard exclusions.** No Finance agent or finance features of any kind. Never
   use or mention `pyttsx3`. No timelines in documentation.
3. **Local-first.** No user data leaves the PC. The only new cloud traffic in
   this package is the tool security review (Phase 4), which sends a candidate
   repo's *code* — never Col's files, conversations, camera frames or any other
   personal data. Third-party front-end libraries are stored locally under
   `web/vendor/`, not loaded from CDNs.
4. **Ask before changing anything** (see Phase 3). Until Phase 3 exists, do not
   add any new capability that changes files, runs commands, installs software
   or sends anything.
5. **Flat, uniquely named files.** Prefer flat folders with descriptive unique
   filenames over nested folders of same-named files. New agent skills follow
   `name_SKILL.md` in `src/archer/skills/` and are discovered by
   `skills_registry.py`.
6. **Isolation.** Dependency conflicts have broken ARCHER before. Anything in
   the tool pool (Phase 4) installs into its own environment, never into
   ARCHER's `.venv`. Only the pre-approved list in Section 12 may be added to
   ARCHER's own `.venv`.
7. **Keep `web/CONTRACT.md` current.** Every new WebSocket message, endpoint or
   tab gets documented there in the same change.
8. **Back up before editing.** Copy each file you change into
   `backups/<date>_<phase>/` first. (The repo's git history is not a reliable
   rollback point — the working tree has many uncommitted changes.)
9. **No prescriptive code in this document is intentional.** It names
   libraries, APIs and behaviors; how to write them is yours.
10. **Never assume. Ask.** If anything in this document is ambiguous, conflicts
    with what you find in the code, or leaves a choice open, do not pick an
    answer yourself. Write it up as a question in the worklog (Section 0b) and
    wait for the answer. This applies to small things too (a label, a file
    location, a default value).

---

## 0b. How Antigravity works through this package (step by step)

**The worklog file.** Create and maintain `D:\ARCHER_9\ARCHER_Antigravity_Worklog.md`.
Claude reads this file directly to review your work and answer questions, and
Col reads it too. It has exactly two sections:

1. **Open Questions** — one entry per question, numbered `Q-01`, `Q-02`, …:
   - Phase and item it belongs to
   - The question, stated so it can be answered in a sentence or a choice
   - What you found that raised it (file and line, if relevant)
   - The options you see, with no recommendation required
   - What is blocked until it's answered
   - **Status:** OPEN / ANSWERED, and the answer once given (answers are written
     into this file by Col or Claude)
2. **Action Log** — append one entry for every action as you take it, not in a
   batch at the end:
   - Date and time
   - Phase and item
   - What you did (read, changed, created, deleted, installed, ran, tested)
   - Files touched (full paths) and the backup location for changed files
   - Why
   - Result, including any error text and how you verified it

**Procedure.**
1. At the start of every work session, re-read this spec section for the
   current phase and the whole worklog, including answers to earlier questions.
2. Work on one phase only. Do not start the next phase until Col has signed off
   the current one in the worklog.
3. Before changing a file: back it up (Rule 8) and log it.
4. When you hit an ambiguity: log a question, mark the affected item BLOCKED,
   and continue only with items that don't depend on the answer. If nothing
   independent is left, stop and say so.
5. When a phase's acceptance checks pass: write a short **Phase N summary** in
   the Action Log (what changed, what was tested and how, anything left open)
   and stop for sign-off.
6. If something breaks ARCHER, restore from the backup, log what happened, and
   ask before trying a different approach.

---

## 1. Decisions already made (do not re-open)

| Topic | Decision |
|---|---|
| Layout | A fixed left column — chat box, orb, webcam feed, stacked top to bottom in that order — that never scrolls. A tabbed workspace on the right. |
| Tabs | **Files** (gesture file access — the barehands board), **Artifacts**, **Tools**, **System**. |
| Gestures | Hand gestures work in every tab, not only on the barehands board. |
| Camera | While ARCHER's page is open, the browser owns the webcam. The fixed webcam pane, the global hand tracker and the barehands board all share that one feed. |
| Approvals | ARCHER asks before making changes. Col can approve everything for the current session instead of answering each prompt — this covers commands and the Python library installs ARCHER needs while working on code. Col does not want to approve every command or library install once session approval is on. Only tool installs from git repos still ask every time. |
| Tools tab | Only a list of the tools and skills added for ARCHER to use. Clicking one opens that program's code in the Artifacts pane, where Col and ARCHER can review and edit it. Nothing else goes in this tab. |
| Browser | Chromium (Playwright), embedded and interactive in the Artifacts tab. Not Opera. |
| Artifacts tab | Objects ARCHER creates, plus: command line, Word, PowerPoint, PDF, the embedded browser, and (last) any desktop app. |
| PDF ability | Create, manipulate and format PDFs — using established open-source libraries. |
| Tool pool | ARCHER can add tools from git repos, only with Col's approval, and only after each repo is cleared by two independent cloud AI reviews: Claude (Anthropic) and OpenAI. |
| Voice | Local only — Kokoro TTS, Faster-Whisper STT. ElevenLabs was removed 2026-10-06. |

Open decision (do not place these until answered — log as a question if you
reach it first): where "While You Were Away" and Tasks go. They are **not** in
the Tools tab.

Defaults chosen by Claude that Col may change (flag if you think one is wrong):
- Logs and all GPU/CPU/model/mic/speaker monitoring move to the **System** tab;
  the always-visible controls bar (model / mic / speaker dropdowns) stays at the
  top of the page.
- New files ARCHER creates inside its own artifacts folder do **not** need
  approval (creating a requested document is the task itself). Anything that
  touches Col's existing files, runs a command, controls an app, submits
  something in the browser, or installs anything does.
- Python libraries installed under session approval go into the environment of
  the code being worked on, never into ARCHER's own `.venv` (that still asks
  individually, to protect ARCHER from dependency conflicts).
- Tool installs from git repos are **never** covered by "approve all for this
  session" — each one is approved individually, after its reviews.

---

## 2. Current state (verified 2026-10-06 — re-verify in Phase 0)

**Browser client**
- Served by `src/archer/server.py` at `/app`; static files under `/static/`
  from `web/`. WebSocket at `/ws/voice`. MJPEG webcam stream at `/camera_stream`.
- `web/index.html` — toolbar, a `#archer-tabs` bar (DASHBOARD, GESTURE), an
  always-visible `#archer-controls-bar`, and `#archer-tab-content`.
- The Dashboard tab holds: orb + chat + a `#tab-system` sidebar (live camera,
  GPU/VRAM, performance charts) in a top row, then Logs / Memory / Tasks /
  Browser-mirror cards. The whole tab scrolls; the system sidebar also scrolls
  internally (max-height 340px), which is why the webcam scrolls out of view.
- JS: `app.js` (WS bridge, exposes `window.ArcherClient`), `ui.js` (toolbar),
  `tabs.js` (tab switching + legacy-name aliases), `system.js`, `logs.js`,
  `memory.js`, `tasks.js`, `browser.js` (screenshot mirror of ARCHER's
  Playwright browser, polled every 2s), `barehands.js`, `cursor.js`, `orb.js`.
  CSS: `web/css/ui.css`, `orb.css`, `cursor.css`.
- `ui_control_SKILL.md` advertises `switch_tab` destinations (currently
  "dashboard" / "gesture").

**Camera**
- `src/archer/web_main.py` creates an analysis-free `ObserverPipeline`
  (`run_analysis=False`) that holds the local webcam open via OpenCV for the
  camera pane, ENROLL FACE, visual questions and "this is X" introductions.
- Windows lets one process hold a webcam at a time. Today's workaround: the
  Gesture tab releases ARCHER's camera on entry and takes it back on exit
  (`camera_release` / `camera_reacquire` WS messages, added 2026-10-06).
  **Phase 2 replaces this.**
- The always-on observer service (`src/archer/observer_service.py`, Windows
  service `ArcherObserver`) uses the Reolink network camera, but at startup it
  first scans the local webcam before switching to the network camera — it
  briefly grabs the webcam each time it starts.

**barehands (gesture file access)**
- Separate app at `D:\ARCHER_9\barehands`, its own server on port 8794,
  embedded in ARCHER's Gesture tab as a cross-origin iframe
  (`stage.html?camhide=1&bg=...`).
- Its page does its own hand tracking with Google MediaPipe `tasks-vision`
  0.10.14 (loaded from the jsDelivr CDN) via its own `getUserMedia` call.
- Its orbs open configured folders (`barehands.json`) as glass cards.

**Agent tools**
- Every agent tool call goes through `UniversalToolExecutor`
  (`src/archer/skills/tool_executor.py`). This is the single choke point for
  the approval gate (Phase 3).
- Existing skills: `canvas_SKILL.md`, `inventory_SKILL.md`,
  `pc_control_SKILL.md`, `tasks_SKILL.md`, `ui_control_SKILL.md`.
- `src/archer/tools/pc_control.py` drives a visible (non-headless) Playwright
  Chromium window (`_ensure_browser`, `open_url`, `browser_click`,
  `browser_type`, `browser_screenshot`), exposed to the server as
  `CoreAgent.pc_controller`.
- `src/archer/canvas/renderer.py` already writes HTML charts/tables to
  `data/artifacts/`.
- An `action_audit` table already exists in `data/archer.db`
  (agent_name, action_type, description, success, error, metadata JSON,
  timestamp), written by `sqlite_store.py`. Reuse it for the approval log if it
  fits.

**Keys available in `.env`:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
(also `MISTRAL_API_KEY`). No NVIDIA key is set.

**Changes made by Claude on 2026-10-06 (already in the files):**
- Observer service: runs from the project root (shares `data/archer.db` with
  ARCHER), depends on a new boot-time CPU-only Ollama service
  (`ArcherObserverOllama`, port 11435); moondream prompt/length cap fixed.
- Face recognition: new `known_person_references` table and
  `add_person_face()` — naming a face for an existing name adds a reference
  instead of overwriting; `scripts/name_person.py`.
- Gesture tab camera handoff (superseded by Phase 2).
- ElevenLabs removed (TTS and STT, the VOICE toolbar button, config, the
  `tts_mode` toggle and its WS messages).
- Backups of all of these are under `D:\ARCHER_9\backups\2026-10-06_*`.

---

## 3. Phase 0 — Audit (no code changes)

Produce a short written report (`ARCHER_Workspace_Phase0_Audit_<date>.md`)
covering:

1. Each fact in Section 2 confirmed or corrected, with file and line.
2. Every place that reads a webcam frame server-side (search for
   `get_latest_frame`, `camera`, `enroll_current_person`,
   `_check_visual_query`, `_check_person_introduction`, `/camera_stream`).
3. Every tool the agent can currently call, and which of them change state
   (write/delete/move files, run processes, click/type, send, install).
4. Whether Microsoft Word and PowerPoint are installed (COM automation
   available) and whether LibreOffice is installed.
5. Whether `git` is on PATH, and its version.
6. ARCHER launches cleanly in browser mode (`ARCHER-Web.bat`) before any
   change — note any existing errors so they aren't blamed on this work.

**Acceptance:** Col and Claude review the report before Phase 1 starts.

---

## 4. Phase 1 — New layout

**Goal:** fixed left column + four tabs. No behavior changes beyond moving
things.

Requirements:
- **Left column, fixed, never scrolls:** chat box (transcript + text input) on
  top, the orb below it, the live webcam feed at the bottom. The chat
  transcript scrolls inside its own box; the column itself does not move.
  Sized so all three are visible at once on Col's desktop monitor.
- **Right side:** tab bar with **Files**, **Artifacts**, **Tools**, **System**.
  Only the active tab's content scrolls.
- **Toolbar and controls bar** stay at the top, unchanged in behavior.
- **Files tab:** the barehands board (what the Gesture tab shows today).
- **Artifacts tab:** placeholder until Phase 5, except the existing browser
  mirror card moves here for now.
- **Tools tab:** a list of ARCHER's current skills (every `*_SKILL.md` found by
  `skills_registry.py`), showing name and one-line description. Nothing else
  goes in this tab. (Clicking an entry to open its code arrives in Phase 5;
  installed pool tools join the list in Phase 4.)
- **"While You Were Away" and Tasks:** OPEN decision (Section 1). They are not
  in the Tools tab. Log a question and leave them unplaced until answered.
- **System tab:** GPU/VRAM, performance charts, loaded Ollama models, and the
  logs tail.
- **Voice/text tab switching:** update `tabs.js` aliases and
  `ui_control_SKILL.md` so `switch_tab` accepts files / artifacts / tools /
  system, and every old name still resolves (gesture → files; dashboard,
  voice → artifacts; logs, system → system; memory, tasks → tools).
- Polling (GPU stats, browser mirror) runs only while its tab is visible, as
  today.
- Visual style unchanged (cyan-on-navy HUD). The orb art (`web/assets`,
  `orb.css`, `orb.js`) is not modified — Col's design agent owns it.

**Acceptance:** all four tabs reachable by click and by voice; the left column
never moves while any tab scrolls; every existing card still works.

---

## 5. Phase 2 — Browser owns the camera; gestures in every tab

**Goal:** one webcam feed shared inside Chrome; a hand-tracking cursor that
works across ARCHER's whole page.

**Camera ownership**
- The main page opens the webcam itself (`getUserMedia`) when it loads. The
  fixed webcam pane shows that stream directly.
- ARCHER's server stops opening the local webcam in browser mode
  (`web_main.py`'s webcam `ObserverPipeline` goes away or never opens the
  device). The desktop app (`__main__.py`) is out of scope and keeps its
  current behavior.
- **Server frame requests:** when the server needs a webcam frame (ENROLL FACE,
  visual questions, "this is X" introductions), it asks the connected page over
  the WebSocket and the page replies with a JPEG of the current frame. Define
  the request/response messages (with a request id and timeout) in
  `CONTRACT.md`. If no page is connected, those features reply that no camera
  is available instead of hanging.
- Remove the `camera_release` / `camera_reacquire` / toggle path and the
  CAMERA toolbar button once nothing needs them.
- **Observer service:** when a network camera is configured, it must not open
  or scan the local webcam at all.
- `/camera_stream` can be removed if nothing else uses it.

**Global hand tracker**
- Use the same library barehands uses — Google MediaPipe `tasks-vision`
  HandLandmarker — stored locally under `web/vendor/` (JS bundle, WASM files and
  the model file), not loaded from a CDN.
- Runs on the page's shared camera stream; draws a hand cursor over the whole
  page (reuse/extend `cursor.js` styling).
- Gestures: hover moves the cursor; quick pinch = click; pinch-and-drag =
  scroll a scrollable area or drag a draggable element. Use barehands'
  shape-ratio gesture thresholds as the reference — they were tuned on a real
  hand and hold at any camera distance.
- Dispatches real pointer/click/wheel events to the element under the cursor so
  every tab, button and pane works without per-pane code.
- **Files tab exception:** the barehands board is a cross-origin iframe, so
  ARCHER's page can't send events into it. While the Files tab is active,
  ARCHER's global tracker pauses and barehands' own tracker drives the board.
  barehands opens its own `getUserMedia` on the same device — Chrome shares the
  camera between them, so no release/handoff is needed. Verify this sharing
  works on Col's machine in this phase.
- A visible toggle to turn gestures off (e.g. when typing), remembered per
  browser.

**Acceptance:** webcam pane always live; ENROLL FACE and "what do you see?"
still work via frame requests; pinch-click works on buttons in all four tabs;
the Files tab board works with no "camera in use" error; restarting the
observer service never touches the webcam.

---

## 6. Phase 3 — Approval system

**Goal:** ARCHER asks before any change, with a per-session "approve all".

- **Gate location:** `UniversalToolExecutor`. Every tool declares whether it
  is read-only or changes state. Changing tools must pass the gate before they
  run. Tools that haven't declared default to "changes state".
- **Changes state (needs approval):** modifying, moving or deleting existing
  files; any terminal command ARCHER runs; clicks/typing in desktop apps;
  browser actions that submit, post, purchase or send; sending messages or
  email; installing anything.
- **Does not need approval:** reading, searching, screenshots, navigating to a
  page, and creating new files inside ARCHER's own artifacts folder (default
  from Section 1).
- **Approval prompt:** appears in the chat box (left column) and is spoken
  briefly. Shows exactly what will happen (the command, the file path, the
  app and action, the page and button). Buttons: **Approve**, **Deny**,
  **Approve all for this session**. Voice "approve" / "deny" also work.
  Gesture-clickable.
- **Session approval:** lasts until ARCHER restarts or Col clicks **End session
  approval** (always visible while active, e.g. a toolbar indicator). While
  it's on, ARCHER does not stop to ask about commands, file changes, app
  actions, or Python library installs it needs while working on code — Col
  explicitly does not want to approve each one. Every action is still logged
  and shown in the chat box as it happens.
- **Still asks every time, even under session approval:**
  - installing a tool from a git repo (Phase 4);
  - installing into ARCHER's own `.venv` (library installs for code ARCHER is
    working on go into that code's environment instead).
- **Timeout:** an unanswered prompt is treated as denied after a reasonable
  wait; ARCHER says so.
- **Log:** every gated action, the decision and the outcome go into
  `action_audit` (or a new table if it doesn't fit), visible in the System tab.
- HALT cancels a pending approval and any running action.

**Acceptance:** each changing tool asks first; Deny prevents it; "approve all"
skips prompts (including commands and library installs for code being worked
on) until ended; git-repo tool installs and `.venv` installs still ask;
everything is logged.

---

## 7. Phase 4 — Tool pool with reviewed installs (Tools tab)

**Goal:** ARCHER can propose and add tools from git repos, safely.

**Registry**
- A table of tools: name, repo URL, pinned commit hash, install folder,
  environment path, review results (local scan + each AI review), status
  (proposed / under review / cleared / rejected / awaiting approval /
  installed / failed), timestamps.
- Installed tools appear in the Tools tab list alongside ARCHER's skills.
  Nothing else does: install progress and the approval request appear in the
  chat box (Phase 3 prompt), and the full review report opens in the
  Artifacts pane from a link in that prompt. Rejected candidates are recorded
  in the registry with their reasons, not shown in the Tools tab.

**Install pipeline (in this order; any failure stops it)**
1. **Pin:** resolve the repo to one exact commit. Only that commit is reviewed
   and installed. Updates create a new review.
2. **Fetch:** clone into a staging folder — nothing runs at this step, no
   install scripts, no package installs.
3. **Local checks:** flag install/setup hooks, post-install scripts, code that
   makes network calls, shells out, or touches files outside its own folder,
   obfuscated or encoded blobs, bundled binaries, and dependencies with known
   vulnerabilities (OSV database / `pip-audit`, plus `bandit` or `semgrep` for
   Python). Results go into the report.
4. **Two independent AI reviews:** send the repo's code (and the local-check
   report) to Claude via `ANTHROPIC_API_KEY` and to OpenAI via
   `OPENAI_API_KEY`, with the same review instructions: identify malicious or
   risky behavior and return a structured verdict (clear / concerns / reject)
   with reasons. **Both must return "clear."** Very large repos: review all
   code that runs, and say in the report what was skipped and why. Only repo
   code is sent — never Col's data.
5. **Col approves** from the chat-box prompt after reading the report
   (individual approval only — never covered by session approval).
6. **Install** into its own folder and its own environment (a separate venv
   per Python tool), never ARCHER's `.venv`.
7. **Register** as a skill (`name_SKILL.md`) so the agent can call it. The tool
   runs as a separate process from its own environment; every call goes
   through the Phase 3 gate according to what it does.

Uninstall removes the folder, environment and skill, and records it.

**Acceptance:** a deliberately harmless test repo goes through every step and
installs, then appears in the Tools tab; a test repo with an obvious risky
install hook is stopped at the local checks or reviews; no git-repo tool
installs without Col's individual approval.

---

## 8. Phase 5 — Artifacts: things ARCHER makes + documents

**Goal:** the Artifacts tab shows what ARCHER creates, and ARCHER can create and
edit Word, PowerPoint and PDF files.

**Viewer**
- A file list of ARCHER's artifacts folder (`data/artifacts/`), newest first,
  with type, size and time; click (or pinch) to open in the viewer area.
- PDFs render in the pane.
- Word and PowerPoint files show a preview made by converting to PDF in the
  background — with Office itself via COM automation if installed (Phase 0
  finding), otherwise LibreOffice headless. Plus **Open in Word / Open in
  PowerPoint** buttons.
- Images, HTML (sandboxed), text and markdown display directly.

**Code view/edit (from the Tools tab)**
- Clicking a skill or tool in the Tools tab opens its program in the Artifacts
  pane: a file tree of that tool's folder (for a skill: its `*_SKILL.md` and the
  code that implements it) and a code editor (Monaco, the editor VS Code uses,
  stored locally in `web/vendor/`).
- Col and ARCHER can both read and edit. Saving goes through the Phase 3 gate
  (covered by session approval). Each save keeps the previous version in a
  backup so an edit can be undone.
- ARCHER can propose an edit as a visible diff in the editor before it's saved.

**Document tools (agent skills)**
- Word: create and edit `.docx` (`python-docx`).
- PowerPoint: create and edit `.pptx` (`python-pptx`).
- PDF: the starter set below. These are established packages from the Python
  package index, pre-approved (Section 12) and installed into their own
  document-tools environment, not ARCHER's `.venv`; each becomes a skill that
  appears in the Tools tab:
  - `pypdf` — merge, split, rotate, encrypt, fill forms
  - `PyMuPDF` — edit text and images, annotate, redact, render pages
    (AGPL license — fine for Col's personal use)
  - `pdfplumber` — extract text and tables
  - `ReportLab` — build PDFs from scratch
  - `OCRmyPDF` — make scanned PDFs searchable (needs Tesseract and Ghostscript
    installed on Windows — confirm with Col before installing those)
- Editing Col's existing files goes through Phase 3 approval; ARCHER saves an
  edited copy into the artifacts folder unless Col approves overwriting the
  original.

**Acceptance:** "make me a one-page PDF summary of X", "turn this into a
5-slide deck", "merge these two PDFs" each produce a file that appears in the
list and previews correctly.

---

## 9. Phase 6 — Terminal

**Goal:** a real command line in the Artifacts tab, shared by Col and ARCHER.

- Front end: `xterm.js` (stored in `web/vendor/`). Back end: a PowerShell
  session in a Windows pseudo-terminal (`pywinpty`), streamed over the
  WebSocket.
- Col can type into it directly at any time.
- ARCHER's commands go through the Phase 3 gate, then are typed into the
  **same** visible session (clearly marked as ARCHER's), and ARCHER reads the
  output back.
- One terminal for v1. Closing/reopening the tab doesn't kill the session.

**Acceptance:** Col runs a command by keyboard; ARCHER asks, then runs one
visibly and summarizes its output; HALT stops a running command.

---

## 10. Phase 7 — Chromium inside the pane

**Goal:** ARCHER's browser lives inside the Artifacts tab and both Col and
ARCHER can drive it.

- Reuse the existing Playwright Chromium from `pc_control.py` (one browser
  instance, not a second one). No separate visible window.
- Stream the page into the pane with the Chrome DevTools Protocol screencast
  (`Page.startScreencast`), and forward Col's mouse, wheel and keyboard input
  back (`Input.dispatchMouseEvent` / `dispatchKeyEvent` / `insertText`).
  Gesture clicks arrive as normal clicks.
- Address bar, back, forward, reload, and simple tabs.
- ARCHER's existing browser tools keep working against the same page;
  navigation is free, but submit/post/purchase/send actions go through Phase 3.
- Replaces the 2-second screenshot mirror (`browser.js` / `browser_get_screenshot`).

**Acceptance:** Col browses normally in the pane; ARCHER opens and navigates a
page Col can watch and take over; the old mirror is gone.

---

## 11. Phase 8 — Any desktop app inside the pane (prototype first)

**Goal:** see and use any Windows app from the Artifacts tab.

This is the riskiest phase. Do a standalone prototype and report back before
integrating.

- Windows only sends keyboard input to the window in front, so apps can't
  simply be "embedded". Proposed approach to prototype: a **virtual second
  monitor** (an open-source virtual display driver) that isn't physically
  shown. Apps ARCHER or Col open "in ARCHER" go to that display; the pane
  streams it (DXGI desktop duplication or Windows Graphics Capture) and sends
  input to it.
- Known catch to evaluate: Windows has one mouse cursor, so while the pane is
  being used the real cursor moves onto the virtual display. Report how
  disruptive this is in practice.
- The virtual display driver is a third-party install: it goes through the
  Phase 4 review and Col's approval like any tool.
- ARCHER's clicks/typing in apps go through the Phase 3 gate.

**Acceptance (prototype):** open Notepad on the virtual display, see it live in
a test page, type into it from the page; written findings on cursor behavior,
latency and reliability. Integration only after Col reviews.

---

## 12. Pre-approved dependencies

May be added to ARCHER's own `.venv` / `web/vendor/` without asking again:

| Package | Phase | Purpose |
|---|---|---|
| MediaPipe `tasks-vision` (JS + WASM + hand model, local copy) | 2 | Global hand tracker |
| `xterm.js` (+ fit addon) | 6 | Terminal front end |
| `pywinpty` | 6 | Windows pseudo-terminal |
| `python-docx`, `python-pptx` | 5 | Word / PowerPoint |
| `pywin32` | 5 | Office COM preview (if Office installed) |
| `pip-audit`, `bandit` (and/or `semgrep`) | 4 | Local security checks |
| `anthropic`, `openai` SDKs (if not already present) | 4 | The two AI reviews |
| Monaco Editor (local copy) | 5 | Code view/edit in the Artifacts pane |
| `pypdf`, `PyMuPDF`, `pdfplumber`, `ReportLab`, `OCRmyPDF` | 5 | PDF starter set — into a separate document-tools environment, not `.venv` |

Everything else — including LibreOffice, Tesseract, Ghostscript and the
virtual display driver — needs Col's explicit approval (git-repo tools go
through the Phase 4 pipeline).

---

## 13. Out of scope for this package

- The PyQt6 desktop app (left as is).
- Mobile app, remote access (LiveKit/Tailscale).
- Redis reconnect for the observer service (deferred by Col).
- Observer change detection / "no change" heartbeat.
- The other open bugs list (desktop startup freeze 2026-10-03, ~100s first
  reply, older March audit items) — tracked separately.

---

## 14. Pending manual steps for Col (from 2026-10-06 session)

1. ~~`nssm restart ArcherObserver`~~ — done by Col 2026-10-06.
2. Close and relaunch ARCHER (`ARCHER-Web.bat`) — loads the Gesture handoff,
   face fixes and ElevenLabs removal.
3. `.venv\Scripts\python.exe scripts\name_person.py Person_2 Col` from
   `D:\ARCHER_9` — gives ARCHER webcam and Reolink references for Col.
4. Optional: delete the `ELEVENLABS_` lines from `.env`.
