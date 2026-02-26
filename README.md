# ARCHER — Advanced Responsive Computing Helper & Executive Resource

## Phase 4: PC Control + Finance + Full GUI

A personal AI assistant with always-on voice interaction, five-agent orchestration,
ambient observation, proactive interventions, desktop automation, and financial
tracking — running on local hardware with cloud fallback.

---

## Prerequisites

- **Python 3.11** (exactly — do not use 3.12+)
- **CUDA 12.4** drivers installed
- **Windows 11**
- **Docker Desktop** with NVIDIA Container Toolkit (for containerized services)
- **Playwright** browsers: `playwright install chromium` (for PC Control)

## Quick Start (Windows)

### 1. Create Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```powershell
pip install -e ".[dev]"
playwright install chromium
```

### 3. Configure Environment

Copy the example environment file and fill in your API keys:

```powershell
copy .env.example .env
```

Edit `.env` with your keys:
- `ANTHROPIC_API_KEY` — Claude API key
- `ELEVENLABS_API_KEY` — ElevenLabs API key

### 4. Start Containerized Services

```powershell
docker compose up -d chromadb
# For Observer features (webcam + emotion/posture detection):
docker compose --profile observer up -d
```

### 5. Run ARCHER

```powershell
python -m archer
```

Or use the entry point:

```powershell
archer
```

---

## Project Structure

```
ARCHER_9/
├── pyproject.toml          # Locked dependencies
├── docker-compose.yml      # Containerized services
├── .env.example            # Environment template
├── src/
│   └── archer/
│       ├── __init__.py
│       ├── __main__.py     # Entry point
│       ├── config.py       # Central configuration
│       ├── core/
│       │   ├── event_bus.py    # Thread-safe event system
│       │   └── toggle.py      # Cloud/local toggle service
│       ├── voice/
│       │   ├── wake_word.py    # openWakeWord detection
│       │   ├── vad.py          # Voice activity detection
│       │   ├── stt.py          # Speech-to-text (cloud + local)
│       │   ├── tts.py          # Text-to-speech (cloud + local)
│       │   ├── audio.py        # Audio I/O management
│       │   ├── pipeline.py     # Voice pipeline orchestrator
│       │   ├── halt.py         # HALT command listener
│       │   └── auth.py         # Voice authentication
│       ├── agents/
│       │   ├── AGENTS.md       # Routing manifest
│       │   ├── orchestrator.py # Multi-agent routing + tool calling
│       │   ├── assistant/
│       │   │   └── SOUL.md     # Assistant personality
│       │   ├── trainer/
│       │   │   └── SOUL.md     # Trainer personality
│       │   ├── therapist/
│       │   │   └── SOUL.md     # Therapist personality
│       │   ├── finance/
│       │   │   └── SOUL.md     # Finance personality
│       │   └── investment/
│       │       └── SOUL.md     # Investment personality
│       ├── observer/
│       │   ├── __init__.py
│       │   ├── camera.py        # Webcam capture thread
│       │   ├── analyzers.py     # Frame analyzers (emotion, pose, sedentary)
│       │   ├── pipeline.py      # Observer pipeline orchestrator
│       │   ├── interventions.py # Proactive intervention engine
│       │   └── overlay.py       # Visual detection overlay
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── pc_control.py    # Desktop automation (pyautogui, Playwright)
│       │   └── pc_tools.py      # Tool definitions for Claude tool_use
│       ├── memory/
│       │   ├── sqlite_store.py  # Tier 1+2 memory + observation logs
│       │   └── chromadb_store.py # Tier 3 semantic memory
│       └── gui/
│           ├── main_window.py  # PyQt6 four-quadrant main window
│           ├── orb_widget.py   # 2D animated orb (fallback)
│           ├── orb_3d.py       # PyVista 3D animated orb
│           ├── webcam_widget.py # Live webcam feed widget
│           ├── artifact_pane.py # Tabbed artifact rendering surface
│           ├── conversation.py # Conversation panel
│           └── tray.py         # System tray
├── tests/
└── docker/
    ├── mediapipe/              # MediaPipe pose service container
    └── deepface/               # DeepFace emotion service container
```

---

## Architecture Notes

### Five-Agent System (Phase 4)
- **Assistant**: General tasks, calendar, reminders, inventory, PC control
- **Trainer**: Fitness, nutrition, exercise (proactive: sedentary/posture)
- **Therapist**: Emotional support, mental health (proactive: sustained distress)
- **Finance**: Budget tracking, spending analysis, financial planning
- **Investment**: Portfolio monitoring, market summaries, investment analysis

### Routing Priority
1. Crisis keywords → always Therapist (safety override)
2. Explicit agent name ("ask the trainer", "talk to therapist")
3. Context continuity (stay with active specialist)
4. Keyword hints (secondary, unambiguous matches only)
5. Default: Assistant

### PC Control (Phase 4)
The Assistant agent can execute desktop automation via Claude tool_use:
- Screen capture (mss) — read-only, no confirmation
- Window management (pygetwindow) — read-only
- Mouse/keyboard (pyautogui) — requires verbal confirmation
- Browser automation (Playwright) — requires verbal confirmation
- HALT cancels all active automation immediately

### Artifact Pane (Phase 4)
The bottom-right GUI quadrant is a tabbed rendering surface where agents
push rich visual content: charts, tables, code blocks, dashboards,
checklists, and images. Up to 5 tabs, auto-switches to newest unless
user manually selected a different tab.

### Threading Model (Critical)
- **Main thread**: PyQt6 event loop
- **FastAPI thread**: Dedicated asyncio loop for API
- **GPU worker pool**: STT, TTS, LLM inference behind a queue
- **Webcam thread**: Dedicated capture loop (~2 FPS ambient observation)
- **Observer analysis thread**: Frame analysis dispatch (every 5s)

These components **NEVER** share objects directly. All inter-thread
communication goes through thread-safe queues, the event bus, and Qt signals/slots.

### Observer Pipeline (Phase 3)
The Observer runs ambient observation through a webcam feed:
- Facial emotion detection via DeepFace (containerized)
- Body posture analysis via MediaPipe (containerized)
- Sedentary behavior tracking (local, 2-hour threshold)
- Proactive interventions: Trainer (sedentary/posture), Therapist (sustained distress)
- Privacy mode: "Pause Observer" in system tray stops all analysis
- Cooldown system prevents intervention fatigue (2h Therapist, 4h after 2 ignores)

### Cloud/Local Toggle
Switchable mid-session without restart. Stored in SQLite. Each service
reads the active mode before every request.

---

## Build Phases

| Phase | Focus | Status |
|-------|-------|--------|
| Phase 1 | Core Voice Loop | ✅ Complete |
| Phase 2 | Agent Orchestration + Memory | ✅ Complete |
| Phase 3 | Observer + Proactive | ✅ Complete |
| **Phase 4** | PC Control + Finance + Full GUI | 🔨 In Progress |
