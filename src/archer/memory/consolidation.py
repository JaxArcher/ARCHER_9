"""
ARCHER End-of-Day Memory Consolidation (Tier 2 Local Synthesis).

Runs nightly (or on-demand) to aggregate ambient visual scene observations
and person sightings from SQLite, enrich with conversation continuity,
synthesize daily behavioral patterns using the LOCAL model (core_primary_model
/ gemma4:e4b via Ollama), and record the summary into OpenMemoryStore
(episodic sector).

Was originally Claude-API synthesis (raw httpx.post straight to
api.anthropic.com) -- switched to local-only 2026-09-16 (Col's explicit
call) when this dormant pipeline was connected to a real nightly schedule
for the first time (see maintenance.py's start_maintenance_scheduler).
Matches the same reasoning already applied to memory/pattern_learner.py's
per-turn extraction: this is an autonomous background job, not a
user-facing conversation turn, so there's no need to spend cloud API
budget on it, and it keeps the feature working in local-only mode.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional
from loguru import logger

from archer.config import get_config
from archer.memory.sqlite_store import get_sqlite_store
from archer.memory.openmemory_store import get_openmemory_store
from archer.memory.markdown_logger import get_markdown_logger


def run_consolidation(target_date: str | None = None) -> bool:
    """
    Run end-of-day behavioral observation consolidation pass.

    Args:
        target_date: Date string in 'YYYY-MM-DD' format. Defaults to today's date.

    Returns:
        True if consolidation succeeded, False otherwise.
    """
    config = get_config()
    store = get_sqlite_store()
    om = get_openmemory_store()
    md = get_markdown_logger()

    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Starting ARCHER daily consolidation pass for {target_date}...")

    # 1. Pull observations, sightings, and ambient room transcripts from SQLite
    data = store.get_day_observations(target_date)
    observations = data.get("observations", [])
    sightings = data.get("sightings", [])

    # Phase 2c: Pull day's ambient room transcripts
    start_dt = datetime.strptime(target_date, "%Y-%m-%d")
    end_dt = start_dt.replace(hour=23, minute=59, second=59)
    day_transcripts = store.get_room_transcripts_range(
        start_time=start_dt.timestamp(),
        end_time=end_dt.timestamp(),
        include_archer=False,
    )

    if not observations and not sightings and not day_transcripts:
        logger.info(f"No scene observations, person sightings, or room transcripts recorded for {target_date}. Skipping consolidation.")
        md.log_audit(
            action="daily_consolidation",
            result="skipped",
            details=f"No observation data found for date {target_date}."
        )
        return True

    # Build observation text block
    obs_lines = []
    for obs in observations:
        ts = obs.get("timestamp", "")
        payload = obs.get("payload", "")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        desc = payload.get("description", "") if isinstance(payload, dict) else ""
        if desc:
            obs_lines.append(f"[{ts}] Scene: {desc}")

    sighting_lines = []
    for s in sightings:
        ts = s.get("timestamp", "")
        pid = s.get("person_id", "Unknown")
        known = "known" if s.get("is_known") else "unrecognized"
        sighting_lines.append(f"[{ts}] Sighting: {pid} ({known})")

    # Up to 60 lines, spread across the whole day (not just the first 60).
    # Whisper can't tell who spoke, so lines say whose voice it was (Col's or
    # another) and who was in view, not a speaker.
    if len(day_transcripts) > 60:
        step = len(day_transcripts) / 60.0
        day_transcripts_sample = [day_transcripts[int(i * step)] for i in range(60)]
    else:
        day_transcripts_sample = day_transcripts
    transcript_lines = []
    for t in day_transcripts_sample:
        voice = {"col": "Col's voice", "other": "another voice"}.get(t.get("voice") or "", "voice not checked")
        seen = ", ".join(t.get("people_in_view") or []) or "nobody identified"
        transcript_lines.append(f"[{t['start_datetime']}] ({voice}; in view: {seen}): \"{t['transcript']}\"")

    # 2. Retrieve recent session context & past memories for continuity
    recent_convs = store.get_recent_conversations(limit=10)
    conv_lines = [f"{c.get('role', '')}: {c.get('content', '')}" for c in recent_convs if c.get("content")]

    past_memos = om.search("daily habits routine patterns", limit=5)
    memo_lines = [m.get("content", "") for m in past_memos if m.get("content")]

    prompt = (
        f"You are ARCHER's end-of-day cognitive consolidation engine.\n"
        f"Synthesize the following ambient observation log, person sightings, and room conversations into a concise, insightful "
        f"daily behavioral summary for date {target_date}.\n\n"
        f"## Ambient Visual Observations ({len(observations)} events):\n"
        + ("\n".join(obs_lines[:50]) if obs_lines else "None recorded") + "\n\n"
        f"## Person Sightings ({len(sightings)} events):\n"
        + ("\n".join(sighting_lines[:50]) if sighting_lines else "None recorded") + "\n\n"
        f"## Ambient Room Transcripts ({len(day_transcripts)} utterances):\n"
        + ("\n".join(transcript_lines) if transcript_lines else "None recorded") + "\n\n"
        f"## Recent Conversational Context:\n"
        + ("\n".join(conv_lines[-10:]) if conv_lines else "None") + "\n\n"
        f"## Prior OpenMemory Context:\n"
        + ("\n".join(memo_lines[:3]) if memo_lines else "None") + "\n\n"
        f"Formulate a structured 1-2 paragraph synthesis summarizing:\n"
        f"1. Key behavioral patterns, activities, and daily workflow observed.\n"
        f"2. Notable presence of known persons (Col) or unrecognized visitors.\n"
        f"3. Notable ambient discussions, decisions, topics, or commitments heard in the room.\n"
        f"4. Any notable focus sessions, habits, or behavioral drift.\n"
        f"Do not include meta commentary or introductory chatter."
    )

    # 3. Send to the LOCAL model via Ollama (2026-09-16: was a direct Claude
    # API call -- see module docstring for why this is local-only now).
    summary_text = ""
    try:
        import httpx
        resp = httpx.post(
            f"{config.ollama_base_url}/api/generate",
            json={
                "model": config.core_primary_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.4},
            },
            # Generous timeout -- this runs on a nightly schedule, off any
            # user-facing critical path, so there's no reason to rush it.
            timeout=120.0,
        )
        resp.raise_for_status()
        summary_text = resp.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"Local model consolidation request failed: {e}")
        summary_text = (
            f"Daily Observation Summary for {target_date}: Recorded {len(observations)} scene events "
            f"and {len(sightings)} person sightings."
        )

    if not summary_text:
        summary_text = f"Daily observation summary recorded for {target_date}."

    # 4. Write summary into OpenMemoryStore
    try:
        om.add_memory(
            content=f"Daily Behavioral Observer Summary ({target_date}): {summary_text}",
            sector="episodic",
            metadata={
                "role": "observer",
                "type": "daily_consolidation",
                "date": target_date,
                "observation_count": len(observations),
                "sighting_count": len(sightings),
            },
        )
        logger.info(f"Consolidation summary saved to OpenMemoryStore for {target_date}.")
    except Exception as e:
        logger.error(f"Failed to save consolidation summary to OpenMemoryStore: {e}")

    # 5. Audit Log
    md.log_audit(
        action="daily_consolidation",
        result="success",
        details=f"Consolidated {len(observations)} observations and {len(sightings)} sightings for date {target_date}."
    )
    return True


if __name__ == "__main__":
    run_consolidation()
