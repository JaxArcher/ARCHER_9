# ARCHER dashboard roadmap — MEMORY / LOGS / TASKS tabs

Spec for the next three tabs on the browser client's tab bar (Voice and
Gesture already exist — see `web/CONTRACT.md`). Written before any of
this gets built, per how we've been working: diagnose/scope first,
build second. Each section below says what already exists in the code,
what's genuinely new, a proposed first version, and the open questions
that are actually yours to decide before I start.

Recommended build order: **LOGS → MEMORY → TASKS**, smallest/most-already-built
first. Each is independent — nothing here blocks anything else.

---

## LOGS tab

**Status: built (2026-09-16).** See `web/CONTRACT.md`'s LOGS tab section
for how it actually landed — matches the proposed v1 below almost
exactly (background tailer thread in `server.py`, `log_line` WS
messages, Pause/Clear browser tab).

**What exists already:** the desktop app already does exactly this —
`gui/console_widget.py` polls ARCHER's own log file
(`config.log_dir / archer_YYYY-MM-DD.log`) on a timer, seeking from the
last read offset, and streams new lines into a scrolling view, with
pause/clear controls. This is a solved problem on the desktop side;
the browser tab is a port, not new design.

**What's new:** a way to get those lines to the browser. The desktop
widget reads the file directly because it's in-process; the browser
needs the file tailed server-side and pushed over the existing
WebSocket bridge (`server.py` already has the broadcast mechanism from
the state/mode/mic messages — this reuses it, doesn't add a new one).

**Proposed v1:**
- A small background thread in `server.py` (or `web_main.py`), same
  tail-by-offset pattern as `console_widget.py`, broadcasting each new
  line as `{"type": "log_line", "text": "..."}`.
- Browser tab: a scrolling read-only panel, newest at the bottom,
  auto-scroll unless the user has scrolled up (matches normal log-viewer
  behavior). Pause/Clear buttons, mirroring the desktop widget.
- No filtering/search in v1 — just the raw tail, like the desktop has.

**Open questions:** none that block starting — this one's ready to build
as described unless you want search/filtering from day one.

---

## MEMORY tab

**What exists already**, and it's more than the video implies is
possible from scratch: `known_persons` (names + face embeddings),
`person_sightings` (who was seen when, known or not), conversation
history in SQLite/Redis, and semantic search over ChromaDB — there's
even a working search endpoint already, `server.py`'s
`/mobile/memory/search`, that calls into the orchestrator's memory
retrieval. None of this has a browser UI yet; the data is real, the
window into it isn't.

**What's new:** the video's graph — literal floating bubbles/clusters by
category (person, project, tool, pattern) with counts like "76 people,
640 patterns" — does not exist here in any form, and "patterns" (learned
quirks like "uses verbal fillers," "gets frustrated when context is
missing") isn't a thing ARCHER extracts or stores at all today. That's
not a UI gap, it's a missing analysis pipeline — something would need
to periodically read conversation transcripts and infer + store these,
which is a real design question (how often, what counts as a pattern,
where it's reviewed) before it's a build question.

**Proposed v1 (data-first, not graph-first):** rather than starting with
the hardest part (a literal particle/node graph — cool, but purely
cosmetic on top of data we don't have flowing yet), start with something
plain and correct:
- A list of known people (name, when last seen, sighting count).
- A searchable conversation history (reuses the existing search
  endpoint — type a query, see relevant past exchanges).
- A recent-activity feed (last N observations/conversations).

The graph visualization is a good phase 2, once there's real data worth
looking at — and like the orb, that's a visual-design-heavy piece
worth hydrating with your design agent rather than something I mock up
blind.

**Decided (2026-09-16):**
1. Yes to the "patterns" feature — Col wants patterns tracked "for
   relevant matters" (i.e. scoped to things that actually matter, not
   every stray observation). Still needs its own scoping pass before
   build — how often transcripts get analyzed, what counts as a
   "relevant" pattern worth surfacing vs. noise, where it's reviewed,
   and how (if at all) it overlaps with the Blindspot agent's existing
   ADHD-focused pattern detection — but the feature itself is a go, not
   an open question anymore.
2. Plain list/search for MEMORY v1, confirmed — graph is a labeled
   "coming later," not a blocker.
3. Relationship/social tracking must be wired into the tab too, not left
   disconnected — Col's call: "relationship tracking and task etc is
   irrelevant if it isn't connected to memory."
4. Pattern extraction runs in real time, every conversation turn (Col's
   choice over a cheaper nightly-batch alternative).

**Status: built (2026-09-16).** See `web/CONTRACT.md`'s "MEMORY tab:
relationships + pattern recognition" section for the full design. What
shipped: a relationships/social-components pane (contacts, interactions,
commitments — real SQLite persistence via new accessor methods, the
tables themselves predate this session but had zero code behind them
until now) that you can add to directly from the tab, and a pattern-
recognition/recursive-learning pipeline (`memory/pattern_learner.py`)
that extracts named entities (people/orgs/nicknames/abbreviations, with
running mention counts and nickname resolution) and recurring themes
(verbal fillers, frustration-from-missing-context) from every
conversation turn in the background, storing them in two new tables
(`learned_entities`, `conversation_patterns`). The entity glossary feeds
back into every future system prompt for deterministic recall; recurring
patterns surface in the tab but aren't injected into live prompts (same
reasoning as the activity-buffer gating elsewhere in CoreAgent — avoids
the small local model latching onto irrelevant ambient notes).

Not yet built: the known-people-list / searchable-conversation-history /
recent-activity-feed basics originally proposed above for MEMORY v1 —
these are still open, and a natural next increment on top of what's here
now.

**Also done (2026-09-16, follow-up):** the dormant `memory/consolidation.py`
/ `memory/maintenance.py` nightly pipeline is now actually scheduled
(`start_maintenance_scheduler()`, fires once/day at `config.maintenance_hour`,
default 3am) and, per Col's call, synthesizes using the LOCAL model
(gemma4:e4b via Ollama) instead of Claude — no cloud API involvement in
this background job at all now. See `web/CONTRACT.md`'s "Nightly
maintenance" section.

---

## TASKS tab (the video's "Battle Station")

**What exists already:** almost nothing usable. There's a
`scheduled_tasks` table that's defined but never referenced anywhere,
and a `task_tracking` table that's used internally only by the
Blindspot agent for its own ADHD-focused pattern detection — neither
is a real to-do system, and neither is exposed to any agent tool or UI.
This is the most honestly "from scratch" of the three tabs.

**Proposed v1:**
- New tables designed for this specifically (not reusing the two above,
  which have incompatible purposes): `tasks` (title, due date, status,
  created/completed timestamps, source) and, if you want habits too,
  `habits` (name, frequency, streak).
- A basic CRUD tool set exposed to CoreAgent (`add_task`, `list_tasks`,
  `complete_task`) — the same pattern already used for PC control tools
  — so you can manage tasks by voice ("remind me to call the bank
  tomorrow") not just by clicking in the tab.
- Browser tab: a list with add/complete/delete, and quick-due-date
  buttons (today/tomorrow/3 days), mirroring the video's UI without
  copying its exact wording.

**Explicitly NOT in v1** (the video bundles these in, but they depend on
things ARCHER doesn't have yet): "people I need to reply to" reminders
(needs real email/SMS integration first — still a gap per the earlier
review), and AI-proposed project/report suggestions (needs a defined
trigger and review flow, not just a data model).

**Decided (2026-09-16):**
1. Habits (daily streaks) ARE in v1, alongside tasks — build both
   tables/tools together rather than tasks-first.
2. Task/habit tools are available to *every* agent persona (Assistant,
   Therapist, Trainer, etc.), not just the core Assistant.

**Status: built (2026-09-16).** See `web/CONTRACT.md`'s "TASKS tab" section
for the full design. Shipped as proposed above: new `tasks`/`habits`
SQLite tables (not the pre-existing `scheduled_tasks`/`task_tracking`,
which are unused/internal-only respectively), a real CRUD tool set
(`tasks_SKILL.md`: add/list/complete/delete for tasks, add/list/complete/
delete for habits with streak tracking) exposed through the same
`UniversalToolExecutor` path every other tool uses — which means every
agent persona already has these tools by construction, since tool
availability was never scoped per-persona to begin with. Browser tab has
add/complete/delete for tasks (with today/tomorrow/3-day quick-due-date
buttons) and add/complete/remove for habits, live-synced whether the
change came from the tab or from a voice/text command.

All three planned dashboard tabs (LOGS, MEMORY, TASKS) are now built.

---

## Sequencing

If it were up to build-effort alone: LOGS is nearly free (porting
existing logic), MEMORY's list/search version reuses real infrastructure
and is moderate effort, TASKS is the only genuinely new subsystem
end-to-end (schema + tools + UI). None of the three block each other, so
they can happen in any order — LOGS → MEMORY → TASKS is just cheapest
first.
