"""
ARCHER Staleness / Neglect Reasoner (2026-09-16).

Answers a specific request from Col: the observer should be able to
notice things that HAVEN'T changed for an unusually long stretch (a dish
left on the table, laundry piling up) -- not just things that moved.
Motion-gated analysis (observer/pipeline.py) fundamentally can't catch
this by definition: it only wakes up when something moves.

Explicitly NOT a hardcoded checklist. Col's own words: "I want it to be
able to intuitively know these things and not require me to provide a
list... this is only if the program can intuitively determine these
things, not given a prescriptive list." So this doesn't check for
"dishes" or "laundry" as keywords (the earlier keyword-scan heuristic in
blindspot_agent.py's _extract_visual_issues is exactly the kind of
prescriptive approach Col is contrasting this with) -- it hands the
local model a chronological window of real scene descriptions and asks
it to use its own judgment about what looks neglected, the same way a
person glancing at a timelapse would.

Runs on its own cadence (observer_staleness_interval_hours, default
every 4h), independent of motion entirely -- called from
archer/observer_service.py at startup. Findings are published exactly
like any other observation (SQLite + Redis, event_type
"staleness_finding") so they flow through the same pipe as scene/
person_sighting events; see agents/blindspot_agent.py's handling of this
event_type, which feeds them through the same real DecisionEngine/
SeverityScorer severity-scoring and cooldown logic every other
intervention already goes through -- no separate ad-hoc mechanism.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import httpx
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store
from archer.memory.redis_buffer import get_redis_buffer

_PROMPT = """You are reviewing a chronological log of ambient scene descriptions from a camera watching someone's living/working space over roughly the last {hours:.0f} hours. Each line is one observation at a point in time.

Your job: using your own judgment -- not a fixed checklist -- identify anything in the space that appears to have been left unchanged, unaddressed, or accumulating for an unusually long stretch of this window. The kind of thing a person would probably want pointed out if they hadn't noticed it themselves: an item sitting somewhere it shouldn't for days, something piling up, a task-in-progress that seems abandoned. Those are illustrative examples only, not an exhaustive list -- use your own read of what's actually described below.

Only flag things you can actually infer from the descriptions themselves -- don't guess at anything not evidenced in them, and don't force a finding if nothing genuinely stands out. Most passes over a normal window should probably find nothing.

Return ONLY valid JSON (no markdown fences, no commentary), matching exactly this shape:
{{
  "findings": [
    {{"description": "plain-language description of what's been neglected/unchanged and roughly how long, based on the timestamps", "duration_estimate": "your best estimate, e.g. 'about a day', 'several days'"}}
  ]
}}
If nothing stands out, return {{"findings": []}}.

Observations (oldest first):
{observations}

JSON:"""


def _parse_json(raw: str) -> dict[str, Any]:
    """Same tolerant-parsing shape used elsewhere for small local model
    output (observer/analyzers.py, memory/pattern_learner.py) -- strips
    markdown fences, falls back to grabbing the outermost {...} block."""
    candidate = raw
    if "```json" in candidate:
        candidate = candidate.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in candidate:
        candidate = candidate.split("```", 1)[1].split("```", 1)[0]
    candidate = candidate.strip()
    try:
        return json.loads(candidate)
    except Exception:
        pass
    match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return {"findings": []}


def _run_pass() -> None:
    config = get_config()
    store = get_sqlite_store()
    lookback_hours = config.observer_staleness_lookback_hours

    observations = store.get_observations_since("scene", lookback_hours, limit=500)
    if not observations:
        logger.debug("Staleness pass: no scene observations in the lookback window yet.")
        return

    lines = []
    for obs in observations:
        payload = obs.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        desc = (payload or {}).get("description", "") if isinstance(payload, dict) else ""
        if desc:
            lines.append(f"[{obs.get('timestamp', '?')}] {desc}")

    if len(lines) < 3:
        # Not enough real history yet to say anything meaningful about
        # what has or hasn't changed -- avoid the model inventing a
        # pattern out of one or two data points.
        logger.debug("Staleness pass: too few observations yet to reason about.")
        return

    prompt = _PROMPT.format(hours=lookback_hours, observations="\n".join(lines))

    try:
        resp = httpx.post(
            f"{config.ollama_base_url}/api/generate",
            json={
                "model": config.core_primary_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            # This can be a genuinely long prompt (hours of observations) --
            # generous timeout, off any user-facing critical path anyway.
            timeout=120.0,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
    except Exception as e:
        logger.debug(f"Staleness reasoning request failed (non-fatal): {e}")
        return

    result = _parse_json(raw)
    findings = result.get("findings", []) if isinstance(result, dict) else []
    if not findings:
        logger.debug("Staleness pass: nothing flagged this cycle.")
        return

    redis = get_redis_buffer()
    # Import here (not at module load) to avoid a circular import --
    # pipeline.py doesn't import this module, but keeping the channel
    # constant defined in one place (pipeline.py) rather than duplicating it.
    from archer.observer.pipeline import OBSERVER_REDIS_CHANNEL

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        description = (finding.get("description") or "").strip()
        if not description:
            continue
        payload = {
            "event_type": "staleness_finding",
            "source": "staleness_reasoner",
            "confidence": 0.6,
            "description": description,
            "duration_estimate": finding.get("duration_estimate"),
        }
        try:
            store.log_observation(
                source="staleness_reasoner",
                event_type="staleness_finding",
                confidence=0.6,
                payload=payload,
            )
        except Exception as e:
            logger.warning(f"Failed to log staleness finding: {e}")
        redis.publish(OBSERVER_REDIS_CHANNEL, payload)
        # Also publish locally (2026-09-16) -- BlindspotAgent now runs
        # inside THIS process (archer/observer_service.py) too, subscribed
        # to the local event bus same as it always was for scene/
        # person_sighting events. Without this, a same-process
        # BlindspotAgent would only ever see staleness findings via a
        # Redis round-trip back to itself, which works but is an odd
        # detour when the direct local bus is right there -- this matches
        # observer/pipeline.py's own "local bus + Redis, always both"
        # pattern in _publish_observation.
        get_event_bus().publish(Event(
            type=EventType.OBSERVATION_EVENT,
            source="staleness_reasoner",
            data=payload,
        ))
        logger.info(f"Staleness finding: {description}")


def _loop() -> None:
    config = get_config()
    interval_s = max(config.observer_staleness_interval_hours, 0.25) * 3600.0
    # Let real observations accumulate before the very first pass rather
    # than reasoning over a near-empty log the moment the service starts.
    time.sleep(min(600.0, interval_s))
    while True:
        try:
            _run_pass()
        except Exception as e:
            logger.error(f"Staleness reasoning loop iteration failed (non-fatal): {e}")
        time.sleep(interval_s)


def start_staleness_reasoner() -> None:
    """Call once from the observer service. Background daemon thread,
    runs forever on its own cadence."""
    threading.Thread(target=_loop, daemon=True, name="archer-staleness-reasoner").start()
    logger.info(
        f"Staleness/neglect reasoner started "
        f"(every {get_config().observer_staleness_interval_hours}h, "
        f"{get_config().observer_staleness_lookback_hours}h lookback)."
    )
