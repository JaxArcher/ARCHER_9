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
11. **Look for an existing project first (Col, 2026-10-15).** Before building
    any component, search for an existing open-source project or library that
    already does it (GitHub and the package indexes). The audit lists what was
    found: what it does, licence, upkeep, Windows support, and whether it fits
    ARCHER's rules (local only, no new cloud traffic). Prefer adopting a good
    fit over writing new code. Adopting one is still a new dependency, so it
    needs Col's approval and a Section 12 entry.

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

**The worklog is append-only.** Add new entries at the end. Never edit, reorder or
remove an existing entry — yours, Col's or Claude's. To correct an earlier entry,
add a new one that says what was wrong. Re-read the file right before every write,
so you never save over a newer version.

**Claude's reviews** are in `D:\ARCHER_9\ARCHER_Claude_Reviews.md` (added
2026-10-08). Claude writes that file; Antigravity only reads it.

**Procedure.**
1. At the start of every work session, re-read this spec section for the
   current phase, the whole worklog (including answers to earlier questions),
   and `ARCHER_Claude_Reviews.md`. Do every open item in Claude's latest review
   before continuing with new work.
2. Work on one phase only. Do not start the next phase until Col has signed off
   the current one in the worklog.
3. Before changing a file: back it up (Rule 8) and log it.
4. When you hit an ambiguity: log a question, mark the affected item BLOCKED,
   and continue only with items that don't depend on the answer. If nothing
   independent is left, stop and say so.
5. When a phase's acceptance checks pass: write a short **Phase N summary** in
   the Action Log (what changed, what was tested and how, anything left open).
   **Working mode from 2026-10-21 (Col):**
   - Don't stop for sign-off. Add Col's acceptance-test steps to a
     **"Ready for Col to test"** list at the end of the worklog, in plain
     language, and go straight on to the next phase.
   - Stop only when something only Col can do blocks you (a sign-in, a
     physical step, an administrator step that isn't set up), when a decision
     is Col's and isn't already in `ARCHER_Antigravity_Plan.md`, or when a
     test Col ran fails.
   - Restart ARCHER yourself whenever testing needs it. Restart the observer
     with `schtasks /run /tn ArcherObserverRestart`, after Col's one-time
     setup.
   - **GitHub (Col, 2026-10-21): push after each phase.** Before each push,
     check for passwords, keys and tokens. Never push `.env`, `logs/`,
     `backups/`, `scratch/`, `data/`, `barehands/sample-notes/` or the stray
     root copies. Never force-push. Col is making the repo private.
6. If something breaks ARCHER, restore from the backup, log what happened, and
   ask before trying a different approach.

---

## 1. Decisions already made (do not re-open)

| Topic | Decision |
|---|---|
| Layout | A fixed left column — chat box, orb, webcam feed, stacked top to bottom in that order — that never scrolls. A tabbed workspace on the right. **Updated by Col 2026-10-21:** this is the starting layout; Col can resize and rearrange every pane (section 4c). |
| Tabs | **Files** (gesture file access — the barehands board), **Artifacts**, **Tools**, **Away & Tasks** ("While You Were Away" plus Tasks, together in one tab), **System** (performance monitoring), **Logs**. Decided by Col 2026-10-06 (Q-01). |
| Gestures | Hand gestures work in every tab, not only on the barehands board. |
| Camera | While ARCHER's page is open, the browser owns the webcam. The fixed webcam pane, the global hand tracker and the barehands board all share that one feed. |
| Approvals | ARCHER asks before making changes. Col can approve everything for the current session instead of answering each prompt — this covers commands and the Python library installs ARCHER needs while working on code. Col does not want to approve every command or library install once session approval is on. Only tool installs from git repos still ask every time. |
| ARCHER's own records | ARCHER's changes to its own records (tasks, habits, inventory, purchase/loan logs) do **not** need approval. Every such change is recorded in the **Change Log** — a table Col can open and review in the Logs tab, one row per change with a clear one- or two-sentence plain-language summary (not technical detail). Decided by Col 2026-10-06 (Q-02). |
| Tools tab | Only a list of the tools and skills added for ARCHER to use. Clicking one opens that program's code in the Artifacts pane, where Col and ARCHER can review and edit it. Nothing else goes in this tab. |
| Browser | Chromium (Playwright), embedded and interactive in the Artifacts tab. Not Opera. |
| Artifacts tab | Objects ARCHER creates, plus: command line, Word, PowerPoint, PDF, the embedded browser, and (last) any desktop app. |
| PDF ability | Create, manipulate and format PDFs — using established open-source libraries. |
| Tool pool | ARCHER can add tools from git repos, only with Col's approval, and only after each repo is cleared by two independent cloud AI reviews: Claude (Anthropic) and OpenAI. |
| Voice | Local only — Kokoro TTS, Faster-Whisper STT. ElevenLabs was removed 2026-10-06. |
| People and faces | **No manual face enrollment — for anyone, Col included.** No button, form, script or command for enrolling faces. ARCHER picks up who people are from context — mainly names that come up naturally while that person is in view; a direct introduction ("this is Sam") also works, though Col rarely does that — keeps a snapshot of every new face, and later asks Col about them in conversation: first whether now is a good time, then one person at a time with the snapshot — who it is and anything worth remembering. Decided by Col 2026-09-16, restated 2026-10-09. See Phase 2b. |
| Listening (second brain) | Whenever someone is in the room — Col included — ARCHER **transcribes** what it hears into text (updated 2026-10-13: presence comes from following people as well as the Reolink's person alerts). **No audio is saved.** Hearing Col's calls and everything he says is the point: ARCHER is his second brain. Col was told that California's consent rules may cover transcribing other people's conversations, and decided to go ahead (2026-10-10). See Phase 2c. |

Defaults chosen by Claude that Col may change (flag if you think one is wrong):
- GPU/CPU/VRAM/performance monitoring goes in the **System** tab; the
  always-visible controls bar (model / mic / speaker dropdowns) stays at the
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
  instead of overwriting; `scripts/name_person.py` (to be removed — no manual
  enrollment, Col 2026-10-09).
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
- **Right side:** tab bar with, in this order: **FILES**, **ARTIFACTS**,
  **TOOLS**, **AWAY & TASKS**, **SYSTEM**, **LOGS** (labels exactly as written).
  Only the active tab's content scrolls.
- **Toolbar and controls bar** stay at the top, unchanged in behavior.
- **Files tab:** the barehands board (what the Gesture tab shows today).
- **Artifacts tab:** placeholder until Phase 5, except the existing browser
  mirror card moves here for now.
- **Tools tab:** a list of ARCHER's current skills (every `*_SKILL.md` found by
  `skills_registry.py`), showing name and one-line description. Nothing else
  goes in this tab. (Clicking an entry to open its code arrives in Phase 5;
  installed pool tools join the list in Phase 4.)
- **Away & Tasks tab:** the existing "While You Were Away" list and the
  existing Tasks view, together in this one tab (Q-01, answered).
- **System tab:** GPU/VRAM, performance charts, loaded Ollama models.
- **Logs tab:** the existing raw application log tail for now. The Change Log
  table is added here in Phase 3.
- **Voice/text tab switching:** update `tabs.js` aliases and
  `ui_control_SKILL.md` so `switch_tab` accepts files / artifacts / tools /
  away_tasks / system / logs, and every old name still resolves
  (gesture → files; dashboard, voice → artifacts; memory, tasks, away →
  away_tasks; logs → logs; system → system).
- Polling (GPU stats, browser mirror) runs only while its tab is visible, as
  today.
- Visual style unchanged (cyan-on-navy HUD). The orb art (`web/assets`,
  `orb.css`, `orb.js`) is not modified — Col's design agent owns it.

**Acceptance:** all six tabs reachable by click and by voice; the left column
never moves while any tab scrolls; every existing card still works.

---

## 4c. Panes Col can resize and move (Col, 2026-10-21)

**Goal:** Col: "can we make the panes in ARCHER reshapeable and rearrangeable
by me? The panes for the chat box and webcam feed are too small. It would be
nice if I could resize those and move them as I'd like. I understand making
one pane larger may shrink the size of another pane, including the tabs
panes, and that's fine."

**Order:** after the fixes in the 18:05 and 17:55 reviews, before Phase 3.

**Behaviour**
- **Panes:** the chat box, the orb, the webcam feed, the tab workspace, and
  the controls bar if it fits the library.
- **Resizing:** Col drags the borders between panes to resize them. The
  neighbouring panes shrink or grow, and every pane has a sensible minimum
  size.
- **Moving:** Col drags a pane by its title bar to another side or position
  (left, right, top, bottom of any pane). The starting layout is today's.
- **The layout is remembered** in this browser (local storage) and comes back
  after a reload or restart. A **Reset layout** button returns to the default.
- **Must keep working while panes move or resize:**
  - The webcam `<video>` keeps playing. It's the one camera stream, shared by
    the hand tracker and the barehands board, so moving it must not restart
    the camera.
  - The barehands iframe (FILES) and any other iframe must not reload: moving
    an iframe element in the page normally reloads it.
  - The ANDROID stream resizes with its pane (the tab's resize message).
  - The hand cursor and pinch-click work on the new layout.
  - Tab switching by voice still works.
- Gestures for resizing and moving are optional in v1. Mouse is enough.

**Rule 11 first.** Look for an existing open-source layout library before
writing one. Claude's leads, to check:
- **dockview** (docking layout with drag-and-drop, split views, tab groups and
  save/restore; works without React; the `dockview` package, not the internal
  `dockview-core`).
- **GoldenLayout 2**.
- **Gridstack.js** (grid of resizable, draggable widgets).
Report the licence, upkeep, plain-JavaScript support, and how each handles
iframes and `<video>` when a pane moves. **Col, 2026-10-21: use a free library
if it passes these checks.** Antigravity picks one, logs why, stores it locally in
`web/vendor/` (Rule 3) and adds a Section 12 row. It doesn't need to ask again
unless none of them passes.

**Acceptance:**
- Col makes the chat box and webcam bigger, moves the webcam to a different
  spot, and reloads the page: the layout is still there.
- The camera and the FILES board keep working throughout.
- Reset layout brings back the default.

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
- **Server frame requests:** when the server needs a webcam frame (visual
  questions, "this is X" introductions), it asks the connected page over
  the WebSocket and the page replies with a JPEG of the current frame. Define
  the request/response messages (with a request id and timeout) in
  `CONTRACT.md`. If no page is connected, those features reply that no camera
  is available instead of hanging.
- **Remove manual face enrollment** (Col, 2026-10-09 — section 1): the ENROLL
  FACE button and everything behind it — the `enroll_face` message, its server
  handler, the observer pipeline's enroll methods, `observer/enroll_person.py`
  and `scripts/name_person.py`. Keep `add_person_face`; Phase 2b uses it.
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
- **Gestures must work in every tab** (Col's requirement): FILES, ARTIFACTS,
  TOOLS, AWAY & TASKS, SYSTEM, LOGS — and inside the Artifacts panes added in
  later phases (code editor, terminal, embedded browser, app view), where
  gesture clicks, scrolls and drags must arrive exactly like mouse input. Each
  of those later phases must re-test this.
- Gestures point, click, scroll and drag; they do not type. Text entry stays
  keyboard or voice.
- **Files tab exception:** the barehands board is a cross-origin iframe, so
  ARCHER's page can't send events into it. While the Files tab is active,
  ARCHER's global tracker pauses and barehands' own tracker drives the board.
  barehands opens its own `getUserMedia` on the same device — Chrome shares the
  camera between them, so no release/handoff is needed. Verify this sharing
  works on Col's machine in this phase.
- A visible toggle to turn gestures off (e.g. when typing), remembered per
  browser.

**Acceptance:** webcam pane always live; "what do you see?" and "this is X"
introductions work via frame requests; no ENROLL FACE button or enrollment code
remains; pinch-click and pinch-scroll work in every tab;
the Files tab board works with no "camera in use" error; restarting the
observer service never touches the webcam.

---

## 5b. Phase 2b — People: learn faces from context, ask Col later

**Goal:** ARCHER learns who people are without any manual enrollment, the way
Col described it (2026-09-16, restated 2026-10-09). It identifies people from
context, keeps a picture of every new face, and asks Col about them later, in
conversation.

**Start after Phase 2 is signed off.** First do a short audit (no code changes)
of what already exists, and log it in the worklog:
- `observer/person_id.py` gives unrecognized faces a `Person_N` label, saves a
  snapshot and logs each sighting.
- The `pending_person_confirmations` table holds one row per unrecognized face,
  with a sighting count.
- `CoreAgent._check_person_introduction` names a face when Col says "this is X"
  while exactly one unrecognized face is in view.
- `known_person_references` / `add_person_face` add a new face for a known name
  alongside the old ones, never overwriting.
- The "Unrecognized People" pane was removed on 2026-09-19 at Col's request.
  The follow-up happens in conversation, not in a form.

**New faces**
- Every new face from either camera (the webcam, through frame requests, and the
  Reolink camera, through the observer service) gets a snapshot and a waiting
  entry. Most of this exists; confirm both cameras feed it.
- Fix the two labelling problems found 2026-10-08 (project doc
  `claude/ARCHER_Ideas_Backlog.md`, item 1):
  - Unknown faces are compared only with the last 200 sightings, so the same
    person can collect several labels.
  - A new label can reuse a number already given to someone else.

  One person should keep one label until they're named.

**Learning from context (Col, 2026-10-09)**
- ARCHER picks up names from context. Mostly that means a name coming up
  naturally while the person is in view: Col greeting someone by name, or
  someone saying their own name. Col rarely introduces anyone to the PC
  directly, but when he does ("this is…", "meet…"), it still counts.
- Only name a face when the link is clear: exactly one unrecognized face in
  view, and the name said while it's there. When unsure, don't guess; save the
  question for the conversational follow-up.
- Naming adds the face as an extra reference, never replacing an existing one.
- **Names from conversation.** Col decided on 2026-10-10 that ARCHER
  transcribes the room whenever the Reolink detects a person (Phase 2c). Build
  Phase 2b first, using what ARCHER already hears: wake-word conversations and
  the follow-up questions. Once Phase 2c exists, picking up names from those
  transcripts joins this, under the same "only when the link is clear" rule.
  For example, "Hi, I'm Sam" or Col greeting Sam while one unrecognized face is
  in view counts. A name that is merely mentioned ("I talked to Sam yesterday")
  never does.
- **Col's own face (Col, 2026-10-10).** Every unrecognized face so far has been
  Col, seen from angles and distances where the room camera doesn't recognize
  him. ARCHER learns this from context instead of asking Col about himself:
  - An unrecognized face counts as Col when the link is clear: exactly one
    person is in view, and Col was recognized in the same scene in the observer
    cycle just before or after, or by the other camera at the same moment.
  - That sighting is logged as Col. The face is added as a new reference for Col
    only when it also looks enough like his saved face. Otherwise it isn't kept
    as a reference, so ARCHER's picture of Col doesn't drift towards blurry or
    partial faces.
  - When the link isn't clear, nothing changes: the face waits for the
    conversational follow-up.
  - Every face added to Col this way appears in the Change Log.
  - **One-off clean-up:** every face waiting on 2026-10-10 is Col. The ones that
    look enough like his saved face are added to his references. The rest are
    too unclear to be useful, or aren't real faces, so they're marked "don't
    know" and ARCHER stops asking about them. Back up `data/archer.db` first.
  - **Replaced on 2026-10-12** by "Following people" below, which takes over
    the ongoing rule. The one-off clean-up is done.

**Asking Col later, in conversation**
- When Col next talks to ARCHER and people are waiting, ARCHER asks whether now
  is a good time to go over people it has seen. It doesn't interrupt something
  Col is in the middle of.
- **If yes:** one person at a time. ARCHER shows the snapshot in the chat (or the
  Artifacts pane), says when and where that person was seen, asks who it is, then
  asks a few short questions worth remembering (how Col knows them, anything to
  note).
- **If not:** ARCHER asks again later, without nagging.
- Col can answer in any of these ways:
  - **A name:** the face is recognized from then on.
  - **"That's me":** the face is added to Col's own references.
  - **"Don't know" / "a stranger":** ARCHER stops asking about that face.
  - **"Forget them":** ARCHER deletes that face's snapshots and records.
- What Col says about a person is saved to ARCHER's memory of that person and
  appears in the Change Log, because it's one of ARCHER's own records
  (section 1).
- Snapshots and faces never leave the machine.

**Following people (Col, 2026-10-12)**

Col's point: once ARCHER has seen him come into the room, the person in the
frame is still him as long as he hasn't left and nobody new has come in. Today
ARCHER judges each snapshot on its own, so every off-angle look at him is a
fresh guess.

- **Follow people; don't re-guess.** On the room camera, ARCHER follows each
  person from the moment they appear until they leave the frame. It looks at the
  room a couple of times a second, in its own quick loop, separate from the slow
  scene descriptions. It sees whole people (bodies), not just faces, so it can
  tell "Col turned around" from "Col left and someone else came in".
- **No video is kept.** Frames are looked at and dropped. Only what ARCHER
  concludes is saved: who, when, and where in the room, as today.
- **One identity for the whole stay.** The first time ARCHER clearly recognizes
  a face, that person's whole stay in view counts as them, including the time
  before. Every face sighting is logged with the stay it belongs to.
- **When to stop assuming.** ARCHER doesn't carry an identity across a gap if:
  - the person leaves the frame, at an edge or through a doorway in view; or
  - two people overlap or cross paths. From that point, each of them starts a
    new stay.

  It waits for another clear look at each face.
- **Losing sight isn't leaving (Col, 2026-10-12).** The detector often loses a
  person in the middle of the room: sitting still, back turned, behind
  furniture. If they show up again near where they were lost, and nobody was
  seen coming in or going out in the meantime, it's the same stay. There is a
  time limit, set from real data on Col's PC. *(Replaces "loses track of them
  for more than a few seconds", which split one visit into many.)*
- **Exits on the room camera (Col, 2026-10-13).** People come and go in three
  places:
  - the front door, off the left edge of the picture past the coat hooks;
  - the hallway to the bathroom and bedroom: the doorway just right of where the
    carved statue stood (the wall heater is there now), right of centre and
    directly behind the right end of the couch;
  - the kitchen door to the left of the fridge, at the right edge.

  Everywhere else is inside the room. The bottom of the picture, where the couch
  and the PC monitor are, is not an exit. A person is at an exit when their feet
  are in one of these doorways. Someone sitting on the couch in front of the
  hallway is inside the room. *(Clarified 2026-10-13: the hallway is not in the
  middle of the picture.)*
- **Only clear faces count.** A face that is turned away, looking down, blurry
  or too dark gives an unreliable match: Col's own head, turned away, has scored
  0.07 against his references. Such a face never names a stay, splits one,
  starts a waiting label or gets learned. Inside a stay, it belongs to the
  stay's person. How far a face is turned is measured, never assumed: a face
  whose turn can't be measured doesn't count as clear.
- **Faces that aren't people (Col, 2026-10-13).** The carved mask statue was
  detected as a face, so Col moved it out of the camera's view. ARCHER doesn't
  need its own way of spotting decor. Instead, when ARCHER asks about a face and
  Col says it isn't a person (a statue, a poster, a picture on the TV), ARCHER
  ignores that face from then on: it gets no label, is never attached to a
  person, and never splits a stay. The statue had two faces, Person_61 and
  Person_84; both are treated this way. Only a reply that is plainly about an
  object counts: one that also mentions a person, a name or a role ("it's the TV
  repair guy") does not. If Col corrects it straight away ("no, that's Sam"),
  the mark is undone.
- **Face checks run on their own schedule.** Checking the faces of the people
  being followed doesn't wait for the slow scene descriptions, the motion alert,
  or ARCHER being closed.
- **Sharp looks (2026-10-14).** The room camera's small stream is for finding
  people and their faces, at its full detail. Who a face belongs to is judged
  from a sharp still from the camera's full-resolution stream, taken when the
  face is turned toward the camera, at a limited rate per stay. On the small
  stream alone, several clear faces of Col scored below 0.25 against him; on
  sharp stills, none did. Only sharp, clear looks are learned.
- **CPU budget (Claude's default, 2026-10-13; Col can change it).** While
  following one person, the observer averages at most one CPU core (about 5% of
  the PC) and never uses more than two, and the tracker keeps its couple of
  frames a second.
- **Someone it never recognizes** gets one waiting label for the whole stay, not
  one label per sighting. The 2-minute rule counts the length of the stay. If
  their face matches a label that is already waiting, that label is used: the
  same person keeps one label across visits until they're named.
- **Learning Col's face.** During a stay that is clearly Col, a clear face that
  doesn't reach the recognition bar can be added to his references. The existing
  limits apply: a match score against Col of 0.45 to 0.85, at most 3 a day, each
  one in the Change Log.
- **The mirror.** The room camera can see a mirror: the standing mirror by the
  front door, on the left side of the picture. A reflection must never count as
  a second person.
- **The camera's own person alerts.** The Reolink can report people itself, but
  ARCHER's listener for those alerts keeps failing ("not yet subscribed"). Fix
  it and use it as a cross-check. Phase 2c's "transcribe while someone is
  there" depends on it too.
- **The desk webcam** is only looked at while ARCHER is open, through frame
  requests, so it doesn't need to follow people.
- **This replaces** the ongoing part of "Col's own face" above.

**Audit first** (logged in the worklog, no code changes):
- Which person detector and tracker can run on the CPU at a couple of frames a
  second alongside the rest of the observer. Measure the CPU use on Col's PC.
- Whether faces at room distance on the 640x480 stream are good enough, or
  whether short, sharp crops from the camera's full-resolution stream are
  needed.
- How the mirror shows up.

**Minimum time before asking (Col confirmed 2026-10-09):** ARCHER only asks
about faces seen for 2 minutes or more in total, so one-off passers-by and
delivery drivers don't come up. This matches Col's mobile-observer plan ("face
storage after 2+ minutes of interaction").

**Acceptance:**
- No button, form, script or command for enrolling faces exists anywhere.
- An unrecognized face seen by either camera gets a snapshot and a waiting entry,
  and keeps the same label on later sightings.
- In the next conversation, ARCHER asks whether now is a good time. Answering
  with a name makes that face recognized from then on (it shows in the sightings
  log under that name).
- "That's me", "don't know" and "forget them" each work as described.
- **Following people:**
  - With Col alone moving around the room for 10 minutes, every face sighting in
    a stay where he was recognized at least once is logged as Col, and no new
    labels appear.
  - A second person who comes in is never filed as Col, and their stay gets one
    waiting label. Test this live when someone is available; until then, with
    automated tests.
  - The mirror never creates a second person.
  - The observer's CPU use, before and after, is in the worklog.
- Tested with Col's real cameras (a manual checklist), plus automated checks that
  can fail when the feature is broken.

---

## 5c. Phase 2c — Listening: transcribe the room (second brain)

**Goal:** ARCHER is Col's second brain. Whenever someone is in the room — Col
included — ARCHER turns what it hears into text: Col's
phone calls, conversations with visitors, things he says to himself. **It saves
the text, never the audio.** Later, Col can ask ARCHER about what was said ("what
did I tell the contractor on Tuesday?"), and Phase 2b can pick up names from it.
Decided by Col, 2026-10-10.

**Start after Phase 2b is signed off.** Begin with a short audit (no code
changes), logged in the worklog:
- **Which microphone.** The Reolink RLC-520A has a built-in mic, and its
  stream may carry audio. Col's desk mic (JLab GO Talk) is used by ARCHER's
  voice pipeline. Find out which of these the observer service can actually use
  while running as a Windows service before login. Test both for how clearly
  each picks up normal speech across the room. Log the comparison and ask Col
  if both work.
- **Where it runs.** Transcription belongs with the always-on observer service,
  so it works whether or not ARCHER's window is open, the same as the camera.
  The observer runs on the CPU by design, to keep the graphics card free for
  ARCHER's brain. Measure CPU load while transcribing, and log it.
- **What already exists.** Faster-Whisper (local speech-to-text), voice activity
  detection, the Reolink person-detection listener and its 30-second tail.

**Behaviour**
- **When:** whenever someone is in the room. That means while ARCHER is following
  anyone on the room camera (an open stay, Phase 2b), plus the Reolink's own
  person alert and its 30-second tail. Not otherwise. *(Updated 2026-10-13: the
  camera's alerts stop once someone sits still, which would cut off a long phone
  call on the couch.)*
- **What:** only stretches that contain speech (voice activity detection), turned
  into text. Audio is held in memory only as long as it takes to
  transcribe, then discarded. Never write it to disk (the voice pipeline's
  `scratch/*.wav` debug dumps must not happen here).
- **ARCHER's own voice:** mark or drop lines that are ARCHER speaking, so ARCHER's
  replies don't show up as things Col said.
- **Date and time on everything (Col, 2026-10-10):** every transcript line
  carries the full date and time it was spoken, in Col's local time. When ARCHER
  shows or quotes a transcript, it shows the date and time too
  (e.g. "Tue Oct 14, 3:42 PM").
- **Storage:** transcripts go to ARCHER's own local database with their date,
  time and source, linked to what the observer saw at that moment (who was in view, if
  known). They are kept, because this is Col's memory; nothing expires
  automatically.
- **Memory:** transcripts become searchable for ARCHER, so Col can ask about past
  conversations. The nightly maintenance pass can also fold them into its daily
  summary.
- **Names (Phase 2b):** follow the "only when the link is clear" rule in
  Phase 2b.

**Local only, no exceptions.** Speech-to-text runs entirely on Col's machine. The
model must load from the local cache with no network calls. Today faster-whisper
(and Kokoro and the voice-auth model) check Hugging Face for model details when
they load; that must not happen for this, and ideally nowhere in ARCHER.

**Defaults chosen by Claude — Col may change them:**
- A **visible "Listening" indicator** in the left column while transcription is
  active.
- A way to **pause listening**: say "ARCHER, stop listening" or use a button,
  until Col resumes it or for a set time.
- **"Forget that"**: Col can ask ARCHER to delete the transcript of a recent
  stretch.

**Acceptance:**
- With a person in view, ARCHER transcribes speech in the room; with no one in
  view, it doesn't.
- Every transcript line has its date and time, and ARCHER shows them when it
  quotes one.
- No audio files are written anywhere, and nothing is sent off the machine.
- Col can ask ARCHER about something he said on a call earlier, and it answers
  from the transcript.
- The indicator, pause and "forget that" all work.
- ARCHER's responsiveness isn't noticeably affected (CPU measured and logged).
- Tested with Col's real room and voice (manual checklist), plus automated
  checks that can fail when the feature is broken.

**Launch phrase: "All systems go" (Col, 2026-10-13)**

Once the observer can hear the room, Col can start ARCHER by voice.
- **The phrase.** When Col says "all systems go" in the room, ARCHER starts the
  web GUI: the same start-up as `ARCHER-Web.bat` (Docker, Ollama and the other
  services, then the page at `http://127.0.0.1:8200/app` in the browser).
- **Already open.** If ARCHER is already running, it brings its page to the
  front, or reopens the page if it was closed. It never starts a second copy.
- **Locked PC.** If the PC is locked or at the login screen, ARCHER opens the GUI
  as soon as Col logs in.
- **Confirmation.** When ARCHER is up, it says so in one short spoken line
  (Claude's default; Col can change the wording or turn it off).
- **Whose voice.** Any voice saying the phrase counts, because opening ARCHER
  is harmless (Claude's default; Col can restrict it to his own voice).
- **What it listens for.** The phrase uses the same listening as transcription,
  so it works whenever someone is in the room. Nothing extra is recorded or kept
  for it.
- **What to find out in the audit.** The observer runs as a Windows service, and
  services can't open windows on Col's desktop. Find out what in Col's own
  login session should start ARCHER and open the page when the observer hears
  the phrase. Log the options, and ask before adding anything that starts at
  login.

**Acceptance (launch phrase):**
- ARCHER closed: Col says "all systems go" from the couch, and the GUI opens.
- ARCHER already open: saying it again brings the page forward without
  starting a second copy.
- Saying it while the PC is locked opens the GUI right after Col logs in.
- Ordinary conversation that doesn't contain the phrase never starts ARCHER
  (checked over a day of real room audio).

**Decisions after the audit (Col and Claude, 2026-10-15)**
- **Microphone (Col):** the room camera's built-in mic. Listening uses its own
  audio-only connection to the camera's sub-stream; the video connection that
  following people uses is left exactly as it is. The desk mic isn't used for
  this.
- **Speech-to-text:** Faster-Whisper `base.en` on the CPU, loaded from a copy
  kept in ARCHER's own model folder (copied from the files already on the PC,
  no download), with Hugging Face's offline mode on for the observer. It must
  work under the service's own account, not only Col's. If a short read-aloud
  test shows too many wrong words, a larger model is Col's decision (it's a
  download).
- **CPU (Claude's default; Col can change it):** while transcribing, listening
  adds at most 2 cores, and that cap must hold when measured. Over a long call
  it averages about 1 core. The graphics card is never used. Following people
  keeps its own budget.
- **ARCHER's own voice:** ARCHER records when it spoke and what it said. Lines
  that overlap that speech in time (allowing for the camera's audio delay)
  and repeat its words, ignoring common words, are marked as ARCHER's, never
  dropped. A line that only overlaps in time is kept as Col's, so his words
  spoken over ARCHER stay searchable. This, pause and "forget
  that" all go through the database the observer and ARCHER already share.
  No new link between the two processes, and nothing that needs Redis or
  ARCHER's window to be open.
- **Launch confirmation (Col, 2026-10-15):** the launcher itself says
  nothing. When ARCHER starts, ARCHER announces itself in its own voice with
  one short line that never contains the launch phrase; the line is logged as
  ARCHER's speech like everything else it says.
- **Pause and "forget that":** by button, or by saying "ARCHER, stop
  listening" or "ARCHER, forget that" in the room. Pausing lasts 15 minutes,
  1 hour, or until resumed; it holds even when ARCHER is closed or the
  observer restarts. While paused, the room mic transcribes nothing, so it
  can't hear a request to resume. Listening resumes from the button, when the
  pause runs out, or when Col says "start listening" to ARCHER directly (in
  chat, or through ARCHER's own voice input) (Claude, 2026-10-15 review).
  "Forget that" deletes the last 2 minutes of transcript (Claude's default),
  including the request itself. Transcript words never go into log files.
- **Asking about the past, privacy:** ARCHER searches the transcripts only
  when Col asks about something said or heard earlier, and never brings them
  up otherwise.
- **Who was there:** Whisper can't tell who spoke, so each line stores who was
  in view (from following people) and the stay it belongs to, not a "speaker".
- **Asking about the past:** ARCHER's chat can search the transcripts to
  answer questions like "what did I tell the contractor on Tuesday?". Search
  is by words; meaning-based search waits until word search falls short.
- **"All systems go" detection:** the observer looks for the phrase (and close
  variants) in the transcript lines, with a short cooldown. No separate wake
  word model.
- **Launching (Col approved a scheduled task):** a scheduled task that runs as
  Col in his own session. The service triggers it when it hears the phrase.
  - If Col is logged in, even with the PC locked, the task runs at once and the
    page is waiting when he unlocks.
  - At login, it starts ARCHER only if the phrase was heard in the last 10
    minutes.
  - The service itself never starts ARCHER.
  - Setup is one command Col runs once as Administrator, with a matching
    uninstall.
- **Whose speech is kept (Col, 2026-10-15): Col's voice always; other voices
  only while the camera sees someone besides Col.**
  - Each transcribed stretch is checked against Col's voice with ARCHER's
    existing voice ID (SpeechBrain ECAPA, already installed), using a voice
    profile enrolled through the camera mic: about a minute of Col reading
    from the couch.
  - Another voice is kept, with who was in view, only while the camera sees
    another person. Otherwise it's taken to be a TV, a video or a
    speakerphone, and nothing is saved. On a phone call, Col's side is kept.
  - Spoken commands ("all systems go", stop listening, forget that) count only
    from speech that is kept, so a TV can't trigger them.
    - **Changed 2026-10-20 (live test):** short phrases score low on the voice
      check, so Col's "all systems go" was dropped. A command now also counts
      from any voice, as long as the PC wasn't playing those words. If it's
      unknown whether the PC was playing, the old rule holds.
  - **Another voice only while the PC is quiet (2026-10-20).** Col mutes the TV
    to talk with someone. The people tracker's phantoms (Col tracked twice,
    boxes that aren't people) had let TV speech in as "another voice".
  - **A lower voice bar while the PC is quiet (2026-10-20):** 0.35 instead of
    0.50, so Col's short remarks are kept (muted-TV test: 0.37 to 0.42).
  - **The room counts as occupied for 2 hours after anyone was last seen
    (2026-10-20),** and right after the observer starts. The people detector
    missed Col lying still on the couch, so "all systems go" went unheard.
    Setting: `ARCHER_ROOM_LINGER_MINUTES` (120).
  - Test it before relying on it: Col's own lines kept, TV and video speech
    dropped, with the TV on.
  - If the voice check can't tell Col from the TV reliably at that distance,
    the fallback is: keep every line, mark lines that aren't Col's voice, and
    ARCHER ignores those lines when answering. Col is asked first.
- **TV speech (Col, 2026-10-20): matched against what the PC is playing.**
  - The TV test showed the voice check alone can't do it: one TV narrator
    who sounds like Col scored 0.62, and Col's own lines 0.55 to 0.68.
  - Videos play from the PC with the TV as its screen. So the observer
    records the PC's own playback (Windows loopback, through the `soundcard`
    package ARCHER's voice pipeline already uses, so it's not a new
    dependency).
  - When a line would be kept, the observer also transcribes what the PC
    played around that moment. If the line repeats those words (half or more
    of its words, common words aside), it's the TV and isn't saved, whoever's
    voice it sounds like. This is the same idea as ARCHER's own-voice check.
    ARCHER's own lines are still marked and kept, because that check comes
    first.
  - Matching loudness over time was tried first and failed live: the two
    audio streams can't be lined up closely enough.
  - The last 2 minutes of the PC's playback are held in memory only. No
    audio is stored.
  - Works from the observer service's SYSTEM account (probe, 2026-10-20). If
    the playback can't be recorded, the voice rule above decides alone.
  - Settings: `ARCHER_ROOM_TV_MATCH` (share of words, set from the TV test)
    and `ARCHER_ROOM_TV_CHECK` (on or off).
  - Rule 11: no existing project does this locally (the one found relies on
    an online speech service), so this reuses ARCHER's own approach.
  - Not covered: video from a source other than the PC, such as an app on
    the TV itself.

---

## 5d. Phase 2d — Things that get moved

**Goal:** ARCHER keeps track of the things that get moved around, by Col or by
anyone else, so it can answer "where's my wallet?" with "On the dining table.
You put it there at 2:15 PM."
This is the real-time location tracking from the Inventory Manager plan
(January 2026). It builds on "Following people" in Phase 2b. Decided by Col,
2026-10-12.

**Start after Phase 2c is signed off.** Col decided on 2026-10-12 that this
comes after the room transcription.

**Audit first** (logged in the worklog, no code changes):
- **What the room camera can make out.** On the 640x480 stream a face is about
  46 pixels tall, so keys or a wallet in a hand are only a few pixels. Check
  whether short, sharp crops around people's hands, taken from the camera's
  full-resolution stream, are enough to identify everyday items.
- **Which local model can name a held item reliably.** Candidates are the
  observer's scene describer, ARCHER's own vision model and a dedicated object
  detector. Measure the CPU and GPU cost too: Col games on this PC.
- **What already exists:** the inventory table and `inventory_SKILL.md`.

**Audit results (Claude, 2026-10-20; `scripts/item_probe.py` on Col's camera):**
- **Built by Claude** (Col, 2026-10-20).
- **The camera:** a still from the main stream is 2560x1920. A phone on the
  couch arm was about 160x65 pixels in it, and the remote in Col's hand about
  65x150, so a still has enough detail. Taking one took about 9 s with a fresh
  login each time; the observer keeps a connection open, which is faster.
- **Naming items:** ARCHER's own vision model (gemma4, on the GPU, already
  loaded) named the remote in a crop of Col correctly in about 1 s. Asked
  about the whole room at once, it found the phone but missed the wallet. So
  it is asked about one spot at a time.
- **The observer's detector** (YOLOX-Nano) found the phone in the still in
  under a second on the CPU, but it can't name wallets or keys and called the
  remote a phone. It isn't used to name things.
- **The observer's scene model** (moondream) returned nonsense both times. It
  isn't used.
- **Existing code:** the database has tables for items, places and moves
  (`inventory_items`, `storage_locations`, `item_location_history`), but the
  code meant to fill them returns placeholder values. Phase 2d uses the tables
  and writes the code.
- **Existing projects (rule 11):** nothing open-source remembers where things
  in a home were put down. Hand-and-object research detectors (Hands23,
  100DOH) are large GPU models built for Linux. Open-vocabulary detectors
  would be new dependencies, and ARCHER's own model already does the naming.

**How it works (Claude's design, 2026-10-20):**
- **Key moments.** The observer keeps a picture of the room without people in
  it, from the 640x480 stream it already reads. When a small patch of the room
  changes right after someone was there, and stays changed once they've moved
  away, something was put down or picked up there. The change has to be small
  and steady, so lighting and cushions shifting don't count.
- **A closer look.** Only then does ARCHER take a sharp still from the main
  stream and ask its vision model about that one spot: what the item is, and
  what it's sitting on. If nothing is there, the change is ignored.
- **Who.** The person who was at that spot just before: Col, a person ARCHER
  knows by name, or a waiting label such as Person_N.
- **Picked up.** When the change is where a known item was last seen and the
  item is gone, the person who was there has it. If that person then leaves
  through a door, ARCHER keeps a sharp photo of them leaving, linked to the
  item.

**Behaviour**
- **Anyone, not just Col (Col, 2026-10-12).** ARCHER watches everyone it is
  following, not only Col. It records who moved the item: Col, a person it
  knows by name, or a waiting label such as Person_N, along with that label's
  photo.
- **Only at key moments.** While following people, ARCHER notices when someone
  picks something up, puts something down or carries something away. Only at
  those moments does it take a closer look at their hands.
- **What it records:** the item, who moved it, where it was put down, and the
  date and time ("Tue Oct 14, 3:42 PM", as in Phase 2c).
- **Telling Col.** ARCHER mentions moves made by anyone other than Col, both in
  While You Were Away and the next time Col talks to it. For example: "Sarah
  moved your keys from the hanger to the counter at 3:12 PM." Col's own moves
  are recorded but not announced, and he can always ask. (This is Claude's
  default; Col can change it.)
- **A photo of where it was last seen.** For each item, ARCHER keeps a still
  photo of the item where it was last seen, with enough of the surroundings to
  recognize the spot. Each new move replaces it.
- **Leaving with an item.** If someone leaves the frame carrying an item,
  ARCHER keeps a sharp still photo of that person as they leave, linked to the
  item: "last seen leaving with your keys, Tue Oct 14, 3:42 PM". If ARCHER
  doesn't recognize the person, the photo also goes into the face follow-up
  (spec 5b).
- **Named places.** Places are named spots in the room, such as "dining table"
  or "couch". The first time ARCHER needs a name for a spot, it asks Col.
- **Where it goes.** Moves go into the existing inventory records, with a Change
  Log entry for each one.
- **Answers.** "Where's my X?" gives the last place and time, and "When did I
  last have X?" works too. When ARCHER isn't sure what an item was, it says so.
  It never makes up a location.
- **Unknown items.** When ARCHER can't name an item, it keeps a cropped photo of
  it and asks Col about it later in conversation, the same way it does with
  faces: one at a time, when it's a good time.
- **Teaching ARCHER an item (Col, 2026-10-20).** Col holds an item up to
  ARCHER's camera and says what it is ("ARCHER, this is my wallet"). ARCHER
  keeps a reference photo and a short description ("black leather wallet"),
  so it knows which wallet is Col's and can tell it from others. Pointing at an
  item in the room is a later addition.
- **Privacy.** No video is kept. The only stills kept are:
  - each item's last-seen photo
  - the photo of someone leaving with an item
  - photos of items ARCHER couldn't name
  - the reference photo of an item Col taught ARCHER

  All of them stay on the PC and are listed with their item, and Col can delete
  any of them. Photos of unnamed items are deleted once Col names or dismisses
  the item.

**Acceptance:**
- Col picks up an everyday item (for example a phone, mug or remote) and puts it
  somewhere else in the room. Asked "where's my X?", ARCHER gives the right
  place and time, and shows the last-seen photo.
- When someone other than Col moves an item, ARCHER records who did it and
  mentions it to Col. Until there's a visitor to test with, check this with
  automated tests.
- Carrying an item out of the frame produces a photo of the person leaving,
  linked to the item.
- An item ARCHER can't identify leads to a question later, never a guess.
- Tested with Col's real camera (a manual checklist), plus automated checks that
  can fail when the feature is broken.

---

## 5e. Logs tab: everything ARCHER is doing, and what state it's in (Col, 2026-10-21)

**Goal:** Col opens the Logs tab and sees what every part of ARCHER is doing
right now and what just happened. Col: "I'd like to have a log of all
activities occurring within the log tab. So I can look at it and see what
process is happening, what state it's in."

**Order:** right after the Phase 7b fixes, before Phase 3.

**What's there now:** `logs.js` shows a curated feed (`log_line`, from
`_register_status_line_bridge` in `server.py`) built from a few event-bus
events: voice state, transcripts, replies, camera checks. Most of ARCHER
never shows up in it.

**1. Status board (top of the tab).** One row per part of ARCHER, each with
its current state and how long it's been in it. States update live, and a part
that has stopped or failed turns red with the reason:
- **Voice:** listening, hearing you, thinking, speaking, paused, or muted.
  Show the microphone and speaker in use.
- **Brain:** idle or answering, with the model and the last reply's timing
  (first words, total time).
- **Startup:** each step while ARCHER is starting, with its time: the voice
  model loading, Kokoro, whisper warm-up, the models warming up, the camera.
  This shows where the ~90 s start goes.
- **Observer service:** running or stopped, room listening on, paused or
  off, people in view (as a count, not names), and the item watcher on or
  off.
- **Virtual phone:** stopped, or the start-up step (launching, Android
  booting, connecting the screen), or online, or the error.
- **ARCHER's browser:** closed, or open with the page title.
- **Tools:** the tool running now, if any, and the last one with its result.
- **Background jobs:** nightly maintenance (next run), Ollama (the models
  loaded, GPU or CPU), Redis and ChromaDB (connected or not).

**2. Activity feed (below).** One plain-English line per event from every part,
newest at the bottom, keeping today's existing Pause / Clear and the
"Working for" timer:
- Voice turns and model rounds, with timing.
- Every tool call: started, finished or failed, with a one-line result.
- Browser actions.
- Virtual phone start, stop and errors.
- Observer events, which reach ARCHER through the existing Redis bridge:
  - Someone came into view or left (by name, if recognised).
  - The room listener kept or dropped a segment. Show a count only, never the
    words.
  - Item moves (while Phase 2d is on).
- Wake words, approvals (once Phase 3 exists), startup steps, and every
  warning and error.
- Each warning or error line has a "Details" toggle that shows the raw log
  line. Errors are highlighted.

**3. Controls.**
- Filter by part (Voice, Brain, Tools, Observer, Phone, Browser, System) and
  by "errors only".
- Search box.
- **Technical log** toggle: a live tail of ARCHER's own log file at INFO and
  above (no DEBUG noise, no `GET /api/ps` polling lines), for when something
  is broken.

**Rules**
- The feed and the board are shown only in this tab. They're kept in memory:
  the last 1,000 lines, sent again when the page reconnects, so a reload
  doesn't lose them. Nothing new is stored on disk beyond ARCHER's existing
  log files.
- **Privacy:** room transcripts, and the words of anything heard in the
  room, never appear (spec 5c). Col's own requests to ARCHER and ARCHER's
  replies may appear, as they do in the chat box.
- Cheap to run: events are pushed when they happen; nothing polls just to
  fill the board.
- Update `web/CONTRACT.md` for every new message.

**Acceptance:**
- With the Logs tab open, Col restarts ARCHER and sees each startup step with
  its time.
- He asks a question and watches voice → brain → reply, with timings.
- He starts the virtual phone and watches its steps.
- He stops the observer service and its row turns red within a few seconds.
- Room speech shows only as counts.

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
  page, creating new files inside ARCHER's own artifacts folder (default from
  Section 1), and ARCHER's changes to its own records — tasks, habits,
  inventory, purchase and loan logs (Col, Q-02).
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
  `action_audit` (or a new table if it doesn't fit).
- **Change Log (Logs tab):** a table Col can open and review, listing every
  change ARCHER makes — its own record updates (which don't ask) and every
  approved action. Columns: date/time; what changed, in one or two clear,
  plain-language sentences (no technical detail — e.g. "Added a task to call
  the bank tomorrow." / "Created a 3-page PDF summary of the meeting notes in
  Artifacts."); what prompted it (your request, a Blindspot observation, etc.);
  and whether it was approved individually, under session approval, or needed
  no approval. Newest first, filterable by date. The summaries are written when
  the change happens, not generated later.
- HALT cancels a pending approval and any running action.

**Acceptance:** each changing tool asks first; Deny prevents it; "approve all"
skips prompts (including commands and library installs for code being worked
on) until ended; git-repo tool installs and `.venv` installs still ask;
ARCHER's own record updates never ask; every change appears in the Change Log
with a readable one- or two-sentence summary.

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
4. **Two independent AI reviews (Col, 2026-10-21: through Antigravity on his
   plan, no pay-per-use API keys):** run two headless Antigravity CLI reviews
   (`agy -p`, read-only permissions, inside the staging folder), each with a
   model from a different family. Use a Claude model and an OpenAI-family
   model if the CLI offers them, otherwise the two most different families it
   offers, and log which. Send the repo's code and the local-check report,
   with the same review instructions: identify malicious or
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
- **No previews inside ARCHER for Word, PowerPoint or PDF (Col, 2026-10-21):**
  "I don't need previews or screenshots inside of ARCHER's tabs. I can see the
  programs myself." Each file gets **Open** (in Word, PowerPoint or the PDF
  reader) and **Show in folder** buttons. Microsoft Office is installed. No
  LibreOffice.
- ARCHER may still render slides to images for its own design check (the
  vision check in "Designed slides"), using PowerPoint through COM
  (`pywin32`). That's for ARCHER's own use and isn't shown in the tab.
- Images, text and markdown display directly.

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
  - `OCRmyPDF` — make scanned PDFs searchable. Needs Tesseract and Ghostscript
    installed on Windows: **approved by Col 2026-10-21** (Section 12).
- Excel (Col, 2026-10-20): create and edit `.xlsx` with formulas, formatting
  and charts, using `openpyxl` (MIT licence). **Approved by Col 2026-10-21**
  (Section 12).
- Editing Col's existing files goes through Phase 3 approval; ARCHER saves an
  edited copy into the artifacts folder unless Col approves overwriting the
  original.

**Designed slides (Col, 2026-10-20).** ARCHER designs decks, not just fills
bullet points into a blank template.
- Candidate: **Presenton** (Apache 2.0), an open-source deck generator that works
  with local Ollama models. It exports editable PowerPoint and PDF, can build
  templates from Col's own PowerPoint files, and has an API ARCHER can call.
  - It runs in its own Docker container (Docker already runs ChromaDB and
    Redis) and uses ARCHER's main Ollama model, so it needs no extra VRAM.
  - Nothing may leave the PC: its community gallery is switched off
    (`PRESENTON_COMMUNITY_ENABLED=false`) and no stock-photo or image-service
    keys are set.
  - It goes through the Phase 4 review and Col's approval like any repo tool.
  - **Col, 2026-10-21: try Presenton**, with the templates as backup.
- Fallback, if it fails the review or the decks aren't good enough: ARCHER's
  own layouts in `python-pptx`. That means a small set of designed layouts
  (title, section, two columns, image with text, chart, quote) and one theme.
  ARCHER then checks its work: it renders each slide to an image and looks at
  it with its vision model to catch text overflow and overlaps.
- Either way the deck opens in the Artifacts pane, and Col can edit it.

**Acceptance:** "make me a one-page PDF summary of X", "turn this into a
5-slide deck", "merge these two PDFs" and "make a spreadsheet of X with totals"
each produce a file that appears in the list, and opens correctly in its own
program. A designed
deck has one consistent theme, varied layouts and no text running off a slide.

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
- Keeps its sign-ins between restarts: a persistent profile in
  `data/browser_profile/`, never pushed. Today `pc_control.py` starts a fresh
  profile on every launch. Needed for Google Messages for web, which stays
  pinned (Phase 7b texting, Col 2026-10-20).

**Acceptance:** Col browses normally in the pane; ARCHER opens and navigates a
page Col can watch and take over; the old mirror is gone.

---

## 10b. Phase 7b — Android apps tab (Col, 2026-10-13)

**Goal:** Col runs apps from his Android phone inside an ARCHER tab, on the PC.

**Order:** Claude's default is right after Phase 2d. It doesn't depend on the
approval system, because in this phase only Col uses the apps.

**Audit first** (logged in the worklog, no installs):
- **Emulator.** Which Android emulator can run Col's apps on his PC and show its
  screen inside a browser tab, with his mouse, keyboard and gesture clicks going
  back to it. Prefer free, open, maintained options: the official Android
  Emulator with a Google Play system image, plus a way to stream it into the page
  (the emulator's own streaming, or scrcpy). Avoid closed, ad-supported
  emulators. Windows Subsystem for Android has been discontinued; don't use it.
- **Graphics card.** The graphics card is already tight for ARCHER's brain, so
  measure the emulator's VRAM and CPU use. Prefer a setup that leaves the card
  free.
- **Col's apps.** The ones he uses most (Col, 2026-10-13): **Messages**,
  **Victure** (his cameras) and **eero** (his Wi-Fi). Check each one in the
  emulator; some apps refuse to run on anything but a real phone. Report which
  work.
  - Messages is a special case: the emulator has no SIM or phone number, so it
    can't send or receive Col's texts itself. Check whether Messages' own web
    pairing with his phone, shown in this tab or in the browser of Phase 7,
    serves him better.
- **Dependencies.** List every install needed (emulator, system image,
  streaming component), with licences, for Col's approval. None is pre-approved.

**Behaviour**
- **The tab.** A new **ANDROID** tab, placed after ARTIFACTS. Voice and text tab
  switching accept "android", "phone" and "apps" (Claude's default label; Col may
  rename it).
- **Use.** The phone screen fills the tab, and Col uses it with mouse, keyboard
  and gestures. Apps are installed from Google Play inside the emulator, signed
  into Col's Google account, like setting up a new phone.
- **Starting and stopping.** The emulator starts the first time Col opens the
  tab and keeps running while ARCHER is open. Col can stop it from the tab. It
  stops when ARCHER closes.
- **Privacy.** The apps go online the way they do on Col's phone. ARCHER itself
  sends nothing, and nothing from the emulator goes into ARCHER's memory unless
  Col asks.
- **ARCHER using the apps** (tapping, typing, reading the screen) is a later
  step, through the Phase 3 approval gate like the browser in Phase 7.

**Acceptance:** Col opens the tab, signs into Google Play, installs one of his
apps, and uses it in the tab with mouse, keyboard and gestures. Switching away
and back keeps the app where he left it. The CPU and VRAM cost is measured and
logged, and ARCHER's replies don't slow down noticeably while the emulator runs.

**Audit results (first pass, Claude, 2026-10-20; details in the reviews log)**
- **Col's choice (2026-10-20): Google's official Android Emulator.** Mirroring
  his real phone with scrcpy was offered and not chosen.
- **Hypervisor.** WSL2 is installed, so Windows' own hypervisor is running. The
  emulator uses Windows Hypervisor Platform (a Windows feature, needs a
  reboot). The older AEHD driver needs Hyper-V off and is retired on
  31 Dec 2026.
- **Installs for approval** (all free, under Google's Android SDK License, not
  open-source):
  - SDK command-line tools, the emulator and platform-tools (adb).
  - One Google Play x86_64 system image. Apps built only for phone chips run
    through Google's ARM translation on these images; some may fail.
- **Into the tab.** The emulator's WebRTC kit runs only in Linux containers.
  On Windows the stream comes from the emulator's gRPC interface (screen
  frames plus touch and key input) or from scrcpy (Apache 2.0) connected to the
  emulator. The tab decodes video with WebCodecs. Claude decides which after
  measuring both.
- **Graphics.** Measure `-gpu host` (uses the card) against `-gpu software`
  (uses the CPU) with ARCHER running (`scratch/android_probe_20oct.ps1` takes
  the starting numbers).
- **Apps.** Apps can refuse emulators through Google's Play Integrity check
  (usual for banking and health apps). Only a live test settles eero and
  Victure. eero has no web dashboard for home users; its app is reported to run
  fully on Windows. The Victure app is **Victure Home** (Col, 2026-10-21).

**Build decisions for Antigravity (Claude, 2026-10-20; Col approved the
installs at 22:26)**
- **Who turns on the Windows feature.** Col switches on Windows Hypervisor
  Platform himself ("Turn Windows features on or off"), then restarts the PC.
  Antigravity doesn't change Windows features or system-wide settings.
- **Where it's installed.** Everything goes under `D:\ARCHER_9\data\android\`:
  the SDK in `sdk\` and the virtual phone in `avd\`. `ANDROID_SDK_ROOT` /
  `ANDROID_HOME` and `ANDROID_AVD_HOME` are set only for the processes ARCHER
  starts, not in the user's or the system's environment. Accept the licences
  with `sdkmanager --licenses`, after Col has seen them: show them in the
  worklog first.
- **System image.** The newest stable (not preview) `google_apis_playstore`
  x86_64 image that `sdkmanager --list` offers. Log the exact package name.
- **Virtual phone.** A current Pixel phone profile, 4 GB RAM, with Quick Boot
  snapshots on, so the phone comes back as Col left it.
- **The emulator mustn't grab ARCHER's devices.**
  - Cameras off (`-camera-back none -camera-front none`): the browser owns
    the webcam.
  - Audio off (`-no-audio`), so it can't take the JLab microphone.
  - Sound for apps is a later step if Col asks.
- **Window and stream.**
  - The emulator runs without its own window (`-no-window`).
  - Its gRPC interface listens on `127.0.0.1` only (`-grpc <port>`), with
    token authentication (`-grpc-use-token`).
  - ARCHER's server reads frames with `streamScreenshot`, sized to the tab
    and sent to the tab as JPEG frames over WebSocket. Mouse, touch, wheel and
    keys go back through the emulator's input calls, following the
    `emulator_controller.proto` that ships with the installed emulator.
  - `grpcio` and `protobuf` are already in `.venv`. Generate the Python stubs
    once, in a throwaway environment, and commit the generated files; don't
    add `grpcio-tools` to `.venv`.
  - If lag or CPU use is poor, log the numbers and ask before switching to
    scrcpy, which isn't approved yet.
- **Tab toolbar.** Back, Home, Recent apps, rotate, and Stop phone. Text typed
  on the PC keyboard goes into the focused field.
- **Graphics.** Try `-gpu host` first. Log VRAM, CPU and ARCHER's reply speed
  with the phone running, then the same with `-gpu software`, and use the one
  that leaves ARCHER's replies as fast as before. If neither does, ask.
- **Leave alone:** Phase 2d files (paused) and the `ARCHER_ITEMS_WATCH` line in
  `.env`.

**Texting (Col, 2026-10-20: "If it can't text, then I guess we need to make a
tab in ARCHER for the messenger window? Or what about using Whatsapp?")**
- **Texts: Google Messages for web.** messages.google.com/web pairs with Col's
  phone through his Google account and covers his normal texts and RCS chats.
  - It's a pinned page in ARCHER's own browser (Phase 7), so it needs no
    separate app or tab. The phone has to be online.
  - That browser must keep its sign-ins between restarts. Today
    `pc_control.py` starts a fresh profile each time; Phase 7 switches to a
    persistent profile in `data/browser_profile/`, never pushed.
- **WhatsApp (optional, Col's call).** It only reaches people who use WhatsApp,
  so it doesn't replace texting. It can run in the emulator as a linked device
  of Col's phone (WhatsApp allows up to five), or as WhatsApp Web in the browser.
- **ARCHER texting by voice: on hold.** Col, 2026-10-21: "let's devise
  another texting plan later." Don't build anything for it. The notes below
  are kept only for that later discussion. Earlier candidate: **SMS Gateway
  for Android** (Apache 2.0), an app on Col's phone used in its local mode.
  - It sends SMS and MMS through an API on the home network and reports
    incoming texts to ARCHER. No account and no cloud.
  - Limits: it can't send RCS, and installing it on the phone needs Col's
    approval.
  - Other options found: KDE Connect (GPL; its Windows app has an SMS window).
    Avoid the AGPL Google Messages bridges.

---

## 10c. Phase 7c — ARCHER on Col's iPad Air (Col, 2026-10-20)

**Goal:** Col uses ARCHER from his iPad Air (1st generation). iOS 12 is the
last version that iPad can run.

**Order:** after Phase 3, because the iPad is meant for approving prompts from
the couch.

**Findings (Claude, 2026-10-20)**
- **Home Wi-Fi only.** Tailscale needs iOS 15 or later, so this iPad can only
  reach ARCHER at home. Access from outside the home stays out of scope.
- **What it is.** A web page that ARCHER serves on the home network. Col saves
  it to the iPad's Home Screen ("Add to Home Screen"), so it opens like an app.
  This is the same kind of HTML app Col already uses on this iPad.
- **Code limits.** It's written for Safari 12: plain HTML, CSS and JavaScript
  with no build step. No newer JavaScript syntax (`?.` and `??` arrived in
  Safari 13.1), no MediaPipe gestures and no WebCodecs. Test it on the iPad
  itself.
- **Microphone.** Home-screen apps on iOS 12 can't use the microphone; Apple
  fixed that in iOS 13.4. In Safari itself the microphone works only over
  HTTPS. So v1 is text and touch, and ARCHER's spoken replies can play on the
  iPad. Talking to ARCHER through the iPad is a later step: it needs a local
  HTTPS certificate installed on the iPad.

**Behaviour**
- **The page:**
  - Chat with ARCHER. It's the same conversation as on the PC, and replies
    come as text, optionally spoken on the iPad.
  - Away & Tasks.
  - "Where's my …" answers with the item photos.
  - Approval prompts (Approve / Deny).
- **Access.** Today ARCHER listens only on the PC itself (`127.0.0.1:8200`).
  The iPad page gets its own port on the home network with a one-time pairing:
  - ARCHER shows a 6-digit code on the PC screen.
  - Col types it on the iPad, and the iPad keeps a long-lived token.
  - Col can revoke the token from the System tab.
  - Everything else stays on `127.0.0.1`. In v1 the iPad gets no camera view,
    logs, transcripts or file access.

**Acceptance:**
- Col adds the page to the iPad's Home Screen and pairs once.
- He can chat with ARCHER, see his tasks and While You Were Away, and approve
  a prompt.
- Any unpaired device on the network gets nothing.

---

## 10d. Telegram line to ARCHER (Col, 2026-10-21)

**Goal:** Col talks to ARCHER from anywhere through Telegram on his phone.

**Order:** after Phase 3 (approvals are one of its main uses).

**Setup**
- Col already has a Telegram account. The bot is created from that account
  with Telegram's @BotFather, so there's no second account or phone number.
- Its token goes into `.env` as `ARCHER_TELEGRAM_BOT_TOKEN`, and is never
  logged.
- Library: **aiogram** (MIT), approved by Col 2026-10-21 (Section 12).
- Long polling, so no ports are opened on the home network.

**What it does**
- Text chat with ARCHER, the same conversation as at home.
- Voice notes are transcribed on the PC with whisper. Replies can come back as
  voice notes in ARCHER's Kokoro voice.
- Approval prompts (Phase 3) as Approve / Deny buttons.
- Reminders, tasks coming due, and While You Were Away items.
- Forwarded links, photos and documents are filed into memory, tasks or
  Artifacts.
- Files ARCHER made are sent to Col (up to 50 MB).

**Privacy**
- Bot chats aren't end-to-end encrypted: Telegram's servers can read them.
- Only Col's Telegram user ID is answered. Anyone else is ignored and logged.
- Room transcripts, camera images and memory summaries are never sent unless
  Col asks for that specific thing in the chat.

**Acceptance:**
- From his phone, away from Wi-Fi, Col asks ARCHER something and gets an
  answer.
- He sends a voice note and gets a reply.
- He approves a prompt.
- A message from another account gets no answer.

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
- The virtual display driver (open source) is **approved by Col 2026-10-21,
  provided it passes the Phase 4 review**. It's a third-party install: it goes through the
  Phase 4 review and Col's approval like any tool.
- ARCHER's clicks/typing in apps go through the Phase 3 gate.

**Acceptance (prototype):** open Notepad on the virtual display, see it live in
a test page, type into it from the page; written findings on cursor behavior,
latency and reliability. Integration only after Col reviews.

---

## 11b. Phase 9 — ARCHER works on itself (R&D) (Col, 2026-10-20)

**Goal:** ARCHER researches, writes and tests improvements to its own code, and
builds new tools and skills for itself. Col: "we need ARCHER to be able to do
it's own R&D development, improving and working on itself."

**Order:** after Phases 3 (approval gate), 5 (code view and diffs) and 6
(terminal). Outside repos still come in only through Phase 4.

**Who writes the code (Col, 2026-10-21): Antigravity, with no pay-per-use
APIs.** Col: one AI writes and a different one checks. "If it has to pay per
use, then we need to rethink this … archer should simply use antigravity for
coding."
- ARCHER hands each coding job to the **Antigravity CLI** (`agy`) in headless
  mode, e.g. `agy -p "<task>" --output-format json`. It uses Col's existing
  Antigravity login (his cached credentials), not an API key.
- **Writer and checker:** the writer runs with one model, and the checker is a
  second `agy` run with a model from a *different* family. It reviews the
  diff and the test results and returns clear / concerns / reject, with
  reasons. Use whichever models the installed CLI offers (`--model`); log
  which. A change goes ahead only on "clear".
- **Permissions:** never `--dangerously-skip-permissions`. Pre-approve only
  what the job needs (`permissions.allow` in its settings: git, the test
  runner, file edits inside the worktree), and keep the agent inside the
  worktree (`--sandbox` if the CLI supports it on Windows).
- **Installing the CLI** is approved by Col's answer, but check first:
  - its install method, licence and Windows support
  - how its quota ("AI credits") works on Col's plan
  Log all of it, and add a Section 12 row.
- A local model as a third checker is optional later. Today's local models
  that are good enough at code need more VRAM than is left beside ARCHER's
  brain.
- ARCHER's own model (gemma4 e4b) keeps the conversation: it turns Col's
  request into the task, and reports the result.

**What may leave the PC**
- Only ARCHER's source code, which is already public on GitHub, and the task
  description.
- Never `data/`, `logs/`, `backups/`, `scratch/`, `.env`, the databases,
  transcripts or photos.
- How that's enforced: the work happens in a separate copy of the repo (a git
  worktree with tracked files only), and the coding agent can only read and
  write inside that copy.

**Flow**
1. An idea comes from Col ("ARCHER, make the timer skill…"), from ARCHER
   noticing a tool failing, or from its own research. It's written as a short
   plain-language proposal in an R&D list in the Away & Tasks tab.
2. ARCHER works in its own copy on a branch. It writes the change and its
   tests, and runs the test suite.
3. The result opens in the Artifacts pane: a diff, a plain-language summary
   and the test results.
4. Applying it to the live ARCHER goes through the Phase 3 gate (session
   approval covers it). The changed files are backed up first, the change
   takes effect at the next restart, and it's recorded in the Change Log.
   "ARCHER, undo the last update" restores the backup.

**Never without Col's individual approval:** changes to the approval gate,
the security and privacy rules, `.env`, or ARCHER's own permissions. ARCHER
never pushes to GitHub; Col pushes.

**Quota:** no pay-per-use spending. Coding uses Col's Antigravity plan. If the
quota runs out, ARCHER stops, says so, and waits. It doesn't fall back to a
paid API.

**Acceptance:**
- Col asks for a small improvement by voice, and ARCHER produces a tested diff
  in the Artifacts pane.
- Col applies it, and it works after a restart. "Undo" restores the old version.
- The request log shows nothing but tracked code was sent.
- The checker's verdict is in the record.

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
| One person-detector model file, permissively licensed (e.g. SSD-MobileNet via OpenCV, or YOLOX-Nano via onnxruntime; not Ultralytics/AGPL). Pinned source and checksum, recorded in the worklog. Approved by Col 2026-10-12. | 2b | Following people on the room camera |
| Roboflow `trackers` (ByteTrack; Apache 2.0) and its `supervision` dependency, pinned version. Replaces the hand-written track matching. Approved by Col 2026-10-12. | 2b | Following people on the room camera |
| `sherpa-onnx` 1.13.8 (+ `sherpa-onnx-core`; Apache 2.0) and its GigaSpeech keyword-spotting model (`sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01`, int8 files, Apache 2.0) in `data/models/kws`. Approved by Col 2026-10-20. | Next stage | "Hey ARCHER" / "ARCHER" wake words |
| Tesseract OCR and Ghostscript (Windows installers, pinned versions and checksums), for `OCRmyPDF`. Approved by Col 2026-10-21. | 5 | Searchable scanned PDFs |
| One open-source virtual display driver, if it passes the Phase 4 review. Approved by Col 2026-10-21. | 8 | Desktop apps in the pane |
| `openpyxl` (MIT), into the document-tools environment. Approved by Col 2026-10-21. | 5 | Excel files |
| `aiogram` (MIT), pinned version. Approved by Col 2026-10-21. | 10d | Telegram line |
| `gridstack` 14.0.0 (MIT), stored in `web/vendor/gridstack/`. Selected per Rule 11 check (preserves persistent DOM elements so `<video>` stream and `<iframe>`s never reload on move/resize). Approved by Col 2026-10-21. | 4c | Resizable panes |
| Antigravity CLI (`agy`), using Col's own Antigravity login, no API keys. Approved in principle by Col 2026-10-21; check the install, licence and quota first. | 9 | ARCHER works on itself |
| Google's Android SDK command-line tools, Android Emulator, platform-tools (adb) and one Google Play x86_64 system image (Android SDK License; free, not open source), installed in `data/android/` (gitignored), not in `.venv`. Approved by Col 2026-10-20 ("proceed with building"). | 7b | Android tab |
| Eclipse Temurin JRE 17 (GPLv2+CE, portable zip for Windows x64, pinned SHA-256: `bc21a93923103cdaac93ee337b0ae4365e739fde36df823dd456bc67c8a9d352`), extracted into `data/android/jdk/`, not in `.venv` or system PATH. Approved by Col 2026-10-21. | 7b | Android tab (sdkmanager / avdmanager) |

Everything else — including LibreOffice, Tesseract, Ghostscript and the
virtual display driver — needs Col's explicit approval (git-repo tools go
through the Phase 4 pipeline).

---

## 13. Out of scope for this package

- The PyQt6 desktop app (left as is).
- Mobile app, and access from outside the home (LiveKit/Tailscale). The iPad
  on home Wi-Fi is in scope (Phase 7c, Col 2026-10-20).
- Redis reconnect for the observer service (deferred by Col).
- Observer change detection / "no change" heartbeat.
- The other open bugs list (desktop startup freeze 2026-10-03, ~100s first
  reply, older March audit items) — tracked separately.

---

## 14. Pending manual steps for Col (from 2026-10-06 session)

1. ~~`nssm restart ArcherObserver`~~ — done by Col 2026-10-06.
2. Close and relaunch ARCHER (`ARCHER-Web.bat`) — loads the Gesture handoff,
   face fixes and ElevenLabs removal.
3. ~~`scripts\name_person.py Person_2 Col`~~ — no longer needed: no manual
   enrollment (Col, 2026-10-09). ARCHER will ask Col about unrecognized faces in
   conversation (Phase 2b), and "that's me" covers Col's own face.
4. Optional: delete the `ELEVENLABS_` lines from `.env`.
