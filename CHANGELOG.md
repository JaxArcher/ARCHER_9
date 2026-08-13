# ARCHER Changelog

---

## 2026-03-08

### Bugfix — Wrong date/time in LLM responses

**File changed:** `src/archer/agents/orchestrator.py` — `_build_system_prompt()`

**Problem:** The LLM returned dates from its training data (e.g. 2023) instead of the current date.

**Fix:** Current date and time are now prepended to every agent's system prompt at call time:
```
## Current Date & Time
Today is Sunday, March 08, 2026. The current time is 10:20 PM.
Always use this when asked about dates or times.
```
This applies to all agents (assistant, trainer, therapist, investment, etc.).

---

### Bugfix — Duplicate text input (investigation result)

**Files checked:** `src/archer/gui/conversation.py`, `src/archer/gui/main_window.py`, `src/archer/voice/pipeline.py`

**Finding:** Signal chain is single-path and correct — no duplicate connections found.
- `_on_text_submit` (conversation.py) emits `text_submitted` once after clearing the input field.
- `text_submitted` connects to `_on_text_submitted` (main_window.py) exactly once.
- `_on_text_submitted` publishes `GUI_TEXT_INPUT` once → pipeline processes it once.

**Status:** No code change required. If the duplicate response behavior recurs, the likely cause is the LLM responding as if the message was sent twice (content issue, not a signal issue).

---

### Bugfix — Ollama 404 / wrong local model name

**File changed:** `.env`

| Variable | Before | After |
|---|---|---|
| `ARCHER_LOCAL_MODEL` | `llama3:8b` | `qwen3.5:4b` |

**Problem:** `.env` specified `llama3:8b` but the installed Ollama model is `qwen3.5:4b`, causing 404s on every local fallback request.

**Fix:** Updated `ARCHER_LOCAL_MODEL` to match the installed model name. Note: `config.py` default was already `qwen3.5:4b` — the `.env` override was stale.

