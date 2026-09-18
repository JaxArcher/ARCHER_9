# ARCHER browser client — interface contract

This does not require reading any Python in this repo, though it links to
the server-side pieces that matter.

## What this is (and isn't)

This is the browser client — a visual window onto the ARCHER assistant
that's already running in this same process (`archer.web_main`), sharing
the exact same CoreAgent, voice pipeline, camera, and memory as the
desktop app would. It is NOT a remote-access client; the browser tab must
be on the same machine ARCHER is running on (LiveKit + Tailscale remote
access is a later, separate phase). This client:

1. **Displays** live state pushed over a WebSocket (what ARCHER is doing,
   what was said, an amplitude value for animating the orb, GPU/CPU/model
   info, logs, memory, tasks).
2. **Streams** the live webcam feed (MJPEG) and, when active, a mirror of
   ARCHER's own Playwright-driven browser.
3. **Sends** typed text, device/model switches, and task/memory actions
   back over the same socket.

Desktop-vs-browser: as of 2026-09-16 this browser client is where active
development happens (Col's call) — barehands gesture control only exists
here, it's the foundation for a planned mobile app, and every feature
built since then (camera stream, GPU/model/audio controls, logs, memory,
tasks, browser mirror) is browser-only. The desktop PyQt6 app still runs
but isn't being actively extended.

## Running it

The FastAPI server that runs inside `archer.web_main` (or the desktop
app's `__main__.py`) serves this client at:

- `http://127.0.0.1:8200/app` → `web/index.html`
- static assets under `http://127.0.0.1:8200/static/...` → anything in `web/`
- `http://127.0.0.1:8200/camera_stream` → live MJPEG webcam feed
- WebSocket: `ws://127.0.0.1:8200/ws/voice`

`Launch-ARCHER.ps1 -WebOnly` (or `ARCHER-Web.bat`) starts everything —
Docker/Redis/ChromaDB, Ollama, LM Studio, barehands (`barehands/run.bat`,
port 8794), then ARCHER itself — and auto-opens this page in your default
browser once the server actually answers.

Editing files under `web/` and refreshing the browser is the whole dev
loop — no build step, no bundler, no external JS dependencies (the old
Chart.js CDN script was removed 2026-09-16 in favor of inline SVG gauges,
specifically so a blocked/slow CDN can't silently break the dashboard
again).

## Layout

```
+---------------------------------------------------------------+
| toolbar: status dot, MODE, MIC, SPEAKER, VOICE, CAMERA,        |
|          ENROLL FACE, HALT                                     |
+---------------------------------------------------------------+
| tabs: DASHBOARD | GESTURE                                      |
+---------------------------------------------------------------+
| controls bar: Brain Model / Microphone / Speaker dropdowns     |  <- always visible,
+---------------------------------------------------------------+     not part of the
| DASHBOARD (scrollable)                                         |     scrolling area
|  primary row: [orb] [chat/transcript] [System sidebar: camera, |
|                GPU/VRAM, performance gauges, ollama-loaded]    |
|  secondary grid: Logs | Memory | Tasks | Browser (mirror)      |
+---------------------------------------------------------------+
```

Toolbar buttons all carry `title` tooltips explaining what they do
(mode = local vs cloud brain, mic/speaker mute, voice engine, camera
release, face enrollment, emergency halt).

### Dashboard consolidation history (2026-09-16)

This started as five separate tabs (Voice, Logs, Memory, Tasks, System).
Col's call was to fold everything except Gesture (barehands is a
self-contained, full-bleed pane that shouldn't share screen space with
anything else) into one Dashboard. Two follow-up passes reshaped it
further based on his feedback:

- **First pass**: camera feed fixed (was broken because `web_main.py` had
  `observer = None`), layout redesigned (orb/chat side by side instead of
  stacked), fonts bumped, the Memory tab's relationship-input UI removed
  entirely (Col: manage that via files in barehands' Notes pane instead),
  a read-only browser mirror pane added, GPU/CPU/temp/token charts added.
- **Second pass**: found that `app.js` declared `const ArcherClient` but
  never assigned it to `window.ArcherClient` — every other file only acts
  through `if (window.ArcherClient)` guards, so that was silently false
  everywhere, which is why dropdowns/charts/GPU info and Logs/Memory/Tasks
  never showed real data. Fixed with one line. Also: model/mic/speaker
  dropdowns moved out of the scrollable System card into the always-visible
  controls bar; Chart.js sparklines replaced with dependency-free SVG ring
  gauges; Tasks card cut down to a read-only "what's open" list (no
  add-task form, no Habits section); Memory card's "Learned Patterns"
  section removed. Tasks, Habits, and Learned Patterns are now mirrored
  as markdown files into barehands' Notes pane instead (see "Notes sync"
  below) — **one-way** for now, SQLite stays the source of truth, editing
  those files doesn't write back yet. Browser mirror card now physically
  moves into the primary row and grows large when a real Playwright
  session is active, and moves back when it ends.

Mechanically, each card still builds into its own original container id
(`#tab-logs`/`#tab-memory`/`#tab-tasks`/`#tab-system`/`#tab-browser`) via
its own JS file (`logs.js`/`memory.js`/`tasks.js`/`system.js`/
`browser.js`) — only where those containers sit in the DOM, and when each
file loads its data (`ArcherClient.on("connected", ...)` rather than "my
tab was clicked", since Dashboard is the default view now), changed.

## Notes sync (barehands integration, 2026-09-16)

`src/archer/integrations/notes_sync.py` mirrors tasks, habits, and
learned patterns out to plain markdown files inside barehands' existing
"Notes" orb: `barehands/sample-notes/ARCHER/{Tasks,Habits,Learned_Patterns}.md`.
Called from `server.py`'s `_build_tasks_snapshot()` /
`_build_memory_snapshot()` every time the underlying SQLite data changes,
from any surface (voice, text, or this browser client). SQLite stays the
real source of truth — this is a one-way mirror so Col can browse/read
this data through barehands instead of a dedicated dashboard input UI;
editing the .md files there doesn't sync back to SQLite (yet — a file
watcher for two-way sync is a possible fast-follow, not built).

`Launch-ARCHER.ps1` also auto-starts barehands itself (`barehands/run.bat`
on port 8794) as part of the normal launch sequence, so the GESTURE tab
doesn't require starting it by hand in a separate window.

## WebSocket messages (server → browser)

| `type`               | Fields                          | Meaning                                                                 |
|-----------------------|----------------------------------|--------------------------------------------------------------------------|
| `state`               | `state`                         | Pipeline state: `idle` \| `listening` \| `processing` \| `speaking` \| `error` \| `halted` |
| `amplitude`           | `value` (0.0–1.0)                | Live TTS output amplitude, drives orb pulse while `state === "speaking"` |
| `stt_partial`         | `text`                          | Live (in-progress) transcription while listening                        |
| `stt_final`           | `text`                          | Finalized user utterance                                                 |
| `agent_response_start`| `elapsed` (seconds)              | Agent call is taking a while (still thinking)                            |
| `agent_response`      | `text`, `agent`                 | Final assistant response text and which agent answered                   |
| `agent_switch`        | `agent`                         | Active agent personality changed                                         |
| `assistant_line`      | `text`                          | A short spoken aside — wake-word ack or filler                          |
| `wake_word`            | —                                | Wake word just fired                                                     |
| `mode`                | `mode`                          | Cloud/local brain mode toggled: `"cloud"` \| `"local"`                  |
| `halt`                | —                                | HALT triggered                                                           |
| `mic_mute`            | `muted`                         | Mic mute state changed                                                   |
| `tts_mute`            | `muted`                         | TTS output mute state changed                                            |
| `tts_mode`            | `mode`                          | Voice engine: `"cloud"` (ElevenLabs) \| `"local"` (Kokoro)               |
| `observer_camera`     | `released`                      | Webcam released/reacquired (e.g. for another app to use it)              |
| `enroll_progress`     | `name`                          | Face enrollment in progress                                              |
| `enroll_result`       | `success`, `name`, `error`      | Face enrollment finished                                                 |
| `switch_tab`          | `tab`                           | Switch the active tab (`"dashboard"` or `"gesture"`) — fired by the `switch_tab` agent tool |
| `log_line`            | `text`                          | One line of the application log, pushed unconditionally                  |
| `memory_snapshot`     | `contacts`, `commitments`, `entities`, `patterns`, `interventions`, `pending_people` | Bulk memory payload (Memory card now only renders `interventions`/`pending_people`; the rest still ship for the notes_sync mirror and any future consumer) |
| `tasks_snapshot`      | `tasks`, `habits`               | Bulk tasks/habits payload                                                |
| `system_snapshot`     | `gpu`, `cpu`, `tokens_per_sec`, `ollama_loaded`, `available_models`, `current_model`, `mic_devices`, `speaker_devices`, `current_mic_index`, `current_speaker_index` | GPU/VRAM/temp, CPU%, tokens/sec, ollama-ps-equivalent, and device lists for the controls bar + System card |
| `browser_screenshot`  | `image_b64`, `active`           | Mirror of ARCHER's own Playwright browser, when a session is open        |
| `hello`               | `mode`, `tts_mode`, `mic_muted`, `tts_muted`, `camera_released`, `camera_available` | Sent on connect — initial toolbar state                    |
| `system_start`        | —                                | Session (re)started                                                      |

## Messages (browser → server)

```json
{"type": "text_input", "text": "what's on my calendar today"}
{"type": "halt"}
{"type": "mode_toggle"}
{"type": "mic_mute_toggle"}
{"type": "tts_mute_toggle"}
{"type": "tts_mode_toggle"}
{"type": "camera_release_toggle"}
{"type": "enroll_face", "name": "Col"}
{"type": "memory_get_all"}
{"type": "memory_confirm_person", "id": 1, "name": "Sarah"}
{"type": "memory_dismiss_person", "id": 1}
{"type": "tasks_get_all"}
{"type": "tasks_add", "title": "...", "due_date": null}
{"type": "tasks_complete", "task_id": 1}
{"type": "tasks_delete", "task_id": 1}
{"type": "habits_add", "name": "...", "frequency": "daily"}
{"type": "habits_complete", "name": "..."}
{"type": "habits_delete", "name": "..."}
{"type": "system_get_all"}
{"type": "system_switch_mic", "device_index": 21}
{"type": "system_switch_speaker", "device_index": 16}
{"type": "system_switch_model", "model": "gemma4:e4b"}
{"type": "browser_get_screenshot"}
```

`text_input` bypasses voice entirely and goes straight to the active
agent. `halt` stops TTS, cancels in-flight actions, and the pipeline
returns to `idle`. `system_switch_mic`/`system_switch_speaker` hot-swap
the live audio device with no restart (see `voice/audio.py`'s
`switch_input_device`/`switch_output_device`) and persist the choice to
`.env`; both raise/log a warning if audio capture isn't currently running
(e.g. both mic and speaker failed to open at startup) rather than
switching a device that doesn't exist yet.

## The orb

`web/js/orb.js` (`ArcherApertureOrb`) is a real canvas-based renderer, not
a placeholder — Col supplied the actual art (`web/assets/approved.png`,
synced into `barehands/assets/approved.png` too so barehands' own ring
matches). It warps/rotates that art per-frame via `requestAnimationFrame`,
with distinct idle/listening/processing/speaking motion driven by
`state`/`amplitude` events from `app.js`. It respects
`prefers-reduced-motion` (stops animating if that's on) — worth checking
if the orb ever looks frozen and nothing else explains it.

## Files

```
web/
  index.html        entry point — loads ui.css, orb.css, app.js, orb.js, ui.js, tabs.js, logs.js, memory.js, tasks.js, system.js, browser.js, barehands.js
  CONTRACT.md        this file
  assets/
    approved.png     the orb artwork
  css/
    ui.css           page chrome: toolbar, tabs, controls bar, dashboard grid/cards, gauges, transcript, text input
    orb.css          the orb's own sizing/aspect-ratio styling
  js/
    app.js           WebSocket client + reconnect + dispatch (exposes window.ArcherClient — every other file depends on this being set)
    orb.js           the animated HUD orb (ArcherApertureOrb)
    ui.js            toolbar (mode/mic/speaker/camera/enroll/halt) + transcript + text input
    tabs.js           top-level tab switching (Dashboard/Gesture, plus legacy tab-name aliases)
    logs.js           builds the Dashboard's Logs card — scrolling tail view + Pause/Clear
    memory.js         builds the Dashboard's Memory card — "While You Were Away" + "Unrecognized People"
    tasks.js          builds the Dashboard's Tasks card — read-only open-tasks list
    system.js         builds the always-visible controls bar (model/mic/speaker) + the System card (camera, GPU/VRAM, performance gauges, ollama-loaded)
    browser.js        builds the Browser (mirror) card, including its primary-row reflow when active
    barehands.js      mounts barehands into the Gesture tab, if reachable
```
