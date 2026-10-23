# ARCHER: Antigravity's plan for the rest of the workspace project

Written by Claude on 2026-10-21. Col is near his weekly Claude limit, so
Antigravity works from this plan without Claude's reviews for a while. Claude
picks up again from the worklog when it's back.

**The spec decides what to build:** `ARCHER_Workspace_Redesign_Spec_06OCT2026.md`
(see the md5 in the latest reviews entry). This plan only says the order, how to work without Claude, and
which decisions are still Col's. If this plan and the spec disagree, the spec
wins, and you log a question.

---

## 1. How to work while Claude is away

- **Same procedure as spec 0b,** except for the working mode Col set on
  2026-10-21 (spec 0b, step 5):
  - Don't stop for sign-off. Put Col's test steps in a **"Ready for Col to
    test"** list at the end of the worklog, and keep going.
  - Stop only when something only Col can do blocks you, a decision is Col's
    and isn't in this plan, or a test Col ran fails.
  - Restart ARCHER yourself when you need to.
  - Push to GitHub after each phase (see Git below).
- **Questions go to Col directly.** Put them at the top of your message, one
  at a time, in plain language, with the options and the one you'd suggest.
  Col skims long text, so keep summaries short. Log the question and his
  answer in the worklog.
- **Decide technical details yourself** when the spec leaves them open and
  they're easy to change later. Log what you chose and why. Ask Col only about
  things that are his to decide: new dependencies, privacy, cost, anything
  hard to undo.
- **Check your own work before every stop.** These are the lessons from this
  week's reviews:
  1. **Run the real thing, not just unit tests.** Open ARCHER's page and use
     the feature the way Col will. The ANDROID tab passed its tests but
     couldn't start from the page, and the Logs tab threw on every event.
  2. **Read the console and `logs/` after a real run.** Look for tracebacks,
     "never awaited" warnings and repeated warnings. Fix them before
     stopping.
  3. **Thread safety:** anything that sends to the browser from a non-loop
     thread goes through `_ws_loop.call_soon_threadsafe`.
  4. **Never block the event loop** with subprocesses, sleeps or long waits.
  5. Child processes: logs go to a file; stops are graceful; they stop with
     ARCHER.
  6. **Don't overstate.** Say what's built, what's stubbed and what's
     untested. Copy text you quote; don't paraphrase it from memory.
  7. Give Col's acceptance-test steps in plain language, with the right
     address: `http://127.0.0.1:8200/app`.
- **Rules that don't change:**
  - Backups before edits, and keep each file's line endings (CRLF stays
    CRLF).
  - `web/CONTRACT.md` stays current.
  - No secrets in output; mask any `rtsp://` URL.
  - Room transcripts never go into logs or to any cloud service.
  - Tests never touch `data/archer.db`.
  - New dependencies need Col's OK and a Section 12 row.
  - No finance features. Never pyttsx3 or SAPI. No timelines in documents.
- **Don't touch Phase 2d** (`item_watcher.py`, `item_store.py`,
  `item_talk.py`, and the `ARCHER_ITEMS_WATCH` line in `.env`). It's paused.
- **Git (Col, 2026-10-21): push after each phase.** Before each push:
  - Check for secrets (passwords, keys, tokens). Never force-push.
  - Never push `.env`, `logs/`, `backups/`, `scratch/`, `data/`,
    `barehands/sample-notes/`, or the stray root copies (`*.ico`,
    `CONTRACT.md`, `index.html`, `*.js`, `ui.css`, `ui_control_SKILL.md`,
    `qc`).
  - Col is making the repo private.

## 2. The order of work

### First: one-time setup, so you don't need Col for restarts
- Write `scripts/setup_observer_restart_task.ps1`. It registers a Windows
  scheduled task, `ArcherObserverRestart`, that runs only
  `Restart-Service ArcherObserver` with highest privileges. Model it on the
  existing `ArcherLaunchOnVoice` setup script.
- Ask Col to run it once in an Administrator PowerShell. After that, restart
  the observer with `schtasks /run /tn ArcherObserverRestart`, and check the
  observer log to confirm it came back.

### Now: finish the queue in `ARCHER_Claude_Reviews.md`, entry "2026-10-21, 18:15"
Item 1 is done and checked (loopback runs on the LG soundbar). Then:
1. **Item 2:** fix broadcasts from outside the event loop (Logs tab, status
   board, AndroidManager) and the `default_model` error. Acceptance: the
   ANDROID tab reaches Online and shows the screen without a page reload,
   and the console has no "no running event loop" tracebacks.
2. **Item 3:** the slow first spoken reply. Measure first. Speed it up with
   a background warm-up of a few sentence lengths at startup.
3. **Item 4:** the cursor (review entry 17:55).
4. **Item 5:** panes Col can resize and move (spec 4c). Do the rule 11
   search, then get Col's OK on the library.
5. **Phase 7b sign-off:**
   - Col's acceptance test: start the virtual phone, sign into Google Play,
     install eero or Victure Home, and switch tabs and back.
   - The follow-up from review 15:15: pause frames on
     `document.visibilitychange`.
   - Make sure normal starts come from the Quick Boot snapshot (seconds),
     not a ~64 s cold boot.

### Then the phases, in this order
6. **Phase 3: approvals** (spec 6). Most later work depends on it.
6b. **Telegram line** (spec 10d). Col said yes. It's created from his
    existing account with @BotFather, so there's no second account or
    number.
7. **Phase 5: documents** (spec 8).
   - First Word, PowerPoint and PDF (pre-approved), and Excel (`openpyxl`,
     after Col's OK).
   - Then designed slides with the python-pptx fallback: layouts plus a
     vision check of rendered slides.
   - Presenton comes after Phase 4, through its review.
8. **Phase 6: terminal** (spec 9).
9. **Phase 4: tool pool** (spec 7). Then put Presenton through it (Col wants
   to try it).
10. **Phase 7: browser in the pane** (spec 10).
    - A persistent profile, so sign-ins survive restarts.
    - Google Messages for web stays pinned (spec 10b, "Texting").
11. **Phase 7c: the iPad Air page** (spec 10c). Home Wi-Fi only, Safari 12,
    pairing code.
12. **Phase 9: ARCHER works on itself** (spec 11b). The Antigravity CLI
    (`agy`, headless) does the coding with Col's own login and no
    pay-per-use APIs. One model writes, and a model from a different family
    checks.
13. **Phase 8, revised: ARCHER's own desk on LENNY** (spec 11, revised
    2026-10-22). **[COMPLETE]** LENNY is Col's spare Windows 11 Pro PC with Office. ARCHER
    gets its own mouse and keyboard there, so Col keeps his.
    - Wrote `scripts/lenny_setup.ps1` plus `docs/LENNY_Setup_Checklist.md` for Col.
    - Completed Rule 11 search (native SendInput/UIA/COM + low-latency WS stream).
    - Built Hands service (`scripts/lenny/hands.py`), the **LENNY tab** (`#tab-lenny`)
      with smooth ~30 FPS live video, latency counter, interactive takeover, and
      the three ways of operating apps (Office COM, UIA, local VLM look-and-click).
    - Relocated ARCHER's Playwright web browser to LENNY over CDP with automatic
      fallback to Main PC local browser if LENNY is offline.
    - Verified with 11/11 tests in `tests/test_phase8_lenny.py` and 71/71 passing
      regression tests.
    - Asks Col only for the steps on LENNY itself: running the script and the
      pairing code.
13a. **"I have questions" tab** (spec 5f, Col 2026-10-22). It replaces the
    photos-in-chat fix in reviews entry "2026-10-22, 16:30": nothing goes in
    the chat, and everything goes in the tab.
13b. **ARCHER's tool chest** (spec 11a, Col 2026-10-22). Build the
    registry, `tool_chest_find`, the code-level routing of clear requests
    (LENNY first), and the Tools-tab view. Then add the LENNY self-update
    channel (reviews entry "2026-10-22, 14:10").
14. **After LENNY: R&D scouting** (spec 11b, "R&D scouting"). Build ARCHER's
    weekly downtime routine, in which ARCHER's R&D agent researches and
    benchmarks newer brain and specialist models itself, and reports to Col.
    Build the routine only. Don't run the model comparison yourself (Col,
    2026-10-22: it's ARCHER's job, not Antigravity's).
    It runs in a boot-time background service, without the GUI (Col,
    2026-10-22), and stands down when ARCHER starts.

## 3. Col's decisions (all answered 2026-10-21, already in the spec)

| Topic | Col's answer |
|---|---|
| Layout library for resizable panes (4c) | Use a free library if it passes the rule 11 checks. Pick it yourself and log why. |
| Excel (`openpyxl`) | Yes. |
| Presenton for designed slides | Try it (after Phase 4's review), with templates as backup. |
| Who writes ARCHER's own code (11b) | Antigravity, via `agy` with his own login. No pay-per-use APIs. One writes, a different one checks. A local checker is optional later. |
| Telegram line (10d) | Yes. The bot is made from his existing account. |
| ARCHER texting by voice | On hold: "let's devise another texting plan later." Don't build it. |
| Victure app | Victure Home. |
| Antigravity's approval prompts | Turbo preset plus a Deny list (set by Col in Antigravity's settings; see the 2026-10-21 19:20 reviews entry). |
| Sign-off after each phase | No. Keep going and batch Col's tests. |
| Observer restarts | Through the `ArcherObserverRestart` task, after Col's one-time setup. |
| GitHub | Push after each phase, after a secrets check. Col makes the repo private. |
| Word / PowerPoint / PDF previews in ARCHER | Not needed: Open buttons only. Office is installed, so no LibreOffice. |
| Tesseract + Ghostscript for OCR | Yes. |
| Phase 8 | Rebuilt around LENNY as ARCHER's own desk (2026-10-22). The virtual display driver was rejected by the review. |

| Phase 4 security reviews | Through Antigravity (`agy`) on his plan as well, two different model families, no paid API keys (spec 7, step 4). |

## 4. Parked: don't start these unless Col asks

- **Phase 2d (items that get moved).** Resume in daylight:
  1. Col runs `scratch\reset_items_20oct.py`.
  2. Remove `ARCHER_ITEMS_WATCH=false` from `.env`.
  3. Restart the observer and ARCHER, then do the wallet test.
  See the reviews from 2026-10-20 21:20 and 21:25.
- Phase 2b's deferred checks; tracker phantoms and double boxes; the coats by
  the door.
- Steady noise (a fan near the camera drowns out speech).
- Taking the voice models offline for HuggingFace (voice auth, Kokoro and
  whisper check online at startup).
- The 21 older test failures, and `test_voice.py`'s stale import.
- The observer doesn't reconnect to Redis.
- Ollama listens on `0.0.0.0` (its app setting).
- For Col: change the camera password.
- Delete the database safety copies in `backups/2026-10-20_claude/` once Col
  says so.

## 5. When Claude comes back

Claude reads the worklog from the last "Claude review" entry onwards and
reviews whatever was built. Keep worklog entries complete enough for that:
files, backups, tests, real-run results and Col's answers.
