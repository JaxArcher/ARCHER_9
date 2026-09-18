"""
ARCHER Blindspot Agent implementation.
Focuses on behavioral patterns, ADHD specialization, and direct feedback.
"""

from __future__ import annotations
import json
import enum
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store
from archer.memory.redis_buffer import get_redis_buffer

# Cross-process live push for decided interventions (2026-09-16). Separate
# from observer/pipeline.py's OBSERVER_REDIS_CHANNEL, which carries RAW
# observations (scene/staleness_finding/person_sighting) -- this one
# carries already-DECIDED interventions, so a subscriber never has to
# re-run DecisionEngine itself. See core_agent.py's subscription.
INTERVENTION_REDIS_CHANNEL = "archer:blindspot:interventions"


# Import core blindspot components
from archer.blindspot.adhd_engine import ADHDStateDetector, ADHDPatternLibrary, MedicationTracker
from archer.blindspot.behavioral_detector import TaskCompletionTracker, TimeBlindnessDetector, RoutineAdherenceMonitor
from archer.blindspot.normative_comparator import NormativeStandardsDB, UserBaselineSystem, DeviationAnalyzer
from archer.blindspot.visual_detector import AppearanceAnalyzer, ClutterDetector, AestheticEvaluator, PlantMonitor
from archer.blindspot.relationship_tracker import RelationshipTracker
from archer.blindspot.intervention_engine import DecisionEngine


# Real (not mocked) signal for the visual side of Blindspot, since
# AppearanceAnalyzer/ClutterDetector/PlantMonitor all turned out to be
# stubs expecting pre-computed structured fields (has_facial_hair,
# object_count, a pre-built plants list, ...) that nothing in ARCHER
# actually produces (confirmed 2026-09-16). What genuinely exists is
# SceneAnalyzer's free-text scene description (observer/analyzers.py,
# moondream via Ollama) and InsightFace's person-sighting timestamps.
# This keyword scan over that real text, plus a real continuous-presence
# duration tracker, replace the mocked inputs -- the DecisionEngine /
# SeverityScorer / ADHDPatternLibrary machinery downstream is untouched
# and genuinely was already implemented.
_CLUTTER_KEYWORDS = (
    "clutter", "cluttered", "messy", "mess ", "disorganized", "piled up",
    "overflowing", "dishes", "trash", "scattered",
)
_GROOMING_KEYWORDS = (
    "unshaven", "disheveled", "unkempt", "hasn't shaved", "messy hair",
    "uncombed",
)
_POSTURE_KEYWORDS = ("slouch", "slumped", "hunched")

# How long the same person must be continuously in frame, with no gap
# longer than _PRESENCE_GAP_RESET_S, before it counts as one unbroken
# session for hyperfocus detection -- matches ADHDStateDetector's own
# built-in "2 hours, no break" threshold.
_PRESENCE_GAP_RESET_S = 15 * 60  # a 15+ minute gap = they left and came back
_INTERVENTION_COOLDOWN_S = 30 * 60  # don't re-flag the same issue for 30 min


class BlindspotAgent:
    """
    The Blindspot Agent identifies what the user overlooks and provides accountability.
    """

    def __init__(self, handle_observations: bool = True, handle_utterances: bool = True) -> None:
        """
        handle_observations / handle_utterances (2026-09-16): BlindspotAgent
        now runs in TWO different processes, each only needing half its
        job. archer/observer_service.py has no voice pipeline (no STT ever
        fires there) but is where scene/staleness/person_sighting events
        actually originate, so it wants handle_utterances=False and
        handle_observations=True (the default) -- deciding on observations
        independent of whether the GUI/browser is even open, which is the
        whole point of this split. CoreAgent's own instance (core_agent.py)
        is the opposite: it still needs _on_utterance for commitment/
        relationship tracking from real speech, but must NOT also decide on
        raw observations itself anymore -- that would double-decide (and
        double cooldown-track, from a separate in-memory state) the exact
        same event the observer_service.py instance already decided on.
        """
        self._config = get_config()
        self._bus = get_event_bus()
        self._store = get_sqlite_store()
        self._redis = get_redis_buffer()
        self._handle_observations = handle_observations
        self._handle_utterances = handle_utterances

        # Initialize engines
        self.adhd_detector = ADHDStateDetector()
        self.adhd_patterns = ADHDPatternLibrary()
        self.med_tracker = MedicationTracker(self._store)

        self.task_tracker = TaskCompletionTracker(self._store)
        self.time_blindness = TimeBlindnessDetector()
        self.routine_monitor = RoutineAdherenceMonitor(self._store)

        self.normative_db = NormativeStandardsDB()
        self.baseline_system = UserBaselineSystem(self._store)
        self.deviation_analyzer = DeviationAnalyzer(self.normative_db, self.baseline_system)

        self.appearance_analyzer = AppearanceAnalyzer(self._store)
        self.clutter_detector = ClutterDetector(self._store)
        self.aesthetic_evaluator = AestheticEvaluator()
        self.plant_monitor = PlantMonitor(self._store)

        self.rel_tracker = RelationshipTracker(self._store)
        self.decision_engine = DecisionEngine(self._store)

        # Real-data tracking state for the heuristics above (in-memory,
        # resets on restart -- fine for "have I already flagged this
        # recently" style bookkeeping, not meant to be durable history).
        self._presence: Dict[str, Dict[str, float]] = {}  # person_id -> {first_seen, last_seen}
        self._last_dispatch: Dict[str, float] = {}  # "category.metric" -> last dispatch monotonic time

        self._subscribe_events()
        logger.info("Blindspot Agent initialized.")

    def _subscribe_events(self) -> None:
        """Subscribe to relevant event bus channels -- gated by which half
        of the job this instance is responsible for (see __init__)."""
        if self._handle_observations:
            self._bus.subscribe(EventType.OBSERVATION_EVENT, self._on_observation)
        if self._handle_utterances:
            self._bus.subscribe(EventType.STT_FINAL, self._on_utterance)
            self._bus.subscribe(EventType.ACTION_COMPLETED, self._on_action)

    def _on_observation(self, event: Event) -> None:
        """Handle vision/system observations.

        Was gated on source == "webcam" -- silently never fired for a
        Reolink network camera, which the Observer pipeline labels
        "network_cam" (see observer/pipeline.py's cam_source_str). Any
        camera source is handled the same way now.
        """
        event_type = event.data.get("event_type", "")

        if event_type == "scene":
            description = (event.data.get("description") or "").strip()
            if not description:
                return
            issues = self._extract_visual_issues(description)
            current_state = "baseline"
            intervention = self.decision_engine.decide_intervention(issues, current_state)
            if intervention:
                self._dispatch_intervention(intervention)

        elif event_type == "staleness_finding":
            # From observer/staleness_reasoner.py -- a periodic, motion-
            # independent pass that asks the local model to use its own
            # judgment about what's been left unchanged/neglected for an
            # unusual stretch (Col's explicit ask, 2026-09-16: no
            # hardcoded checklist, unlike the keyword scan in
            # _extract_visual_issues above, which exists only because the
            # real visual analyzers turned out to be mocked -- this is a
            # genuinely different, judgment-based signal). Fed through the
            # same real DecisionEngine severity scoring as everything else.
            description = (event.data.get("description") or "").strip()
            if not description:
                return
            issues = [{
                "category": "household",
                "metric": "neglected_item",
                "deviation_from_baseline": 0.5,
                "description": description,
            }]
            intervention = self.decision_engine.decide_intervention(issues, "baseline")
            if intervention:
                self._dispatch_intervention(intervention)

        elif event_type == "person_sighting":
            person_id = event.data.get("person_id", "")
            if not person_id or person_id.lower().startswith("person_"):
                # Unidentified/generic person labels aren't a stable key to
                # track a continuous session against -- only track known,
                # named people (post-enrollment).
                return
            hours = self._update_presence(person_id)
            if hours <= 0:
                return
            current_state = self.adhd_detector.detect_current_state({
                "activity_duration_hours": hours,
                # No real break-detection signal exists yet -- a gap of
                # _PRESENCE_GAP_RESET_S resets the session tracker entirely
                # rather than registering as a "break taken", so this is
                # always False for now. Known simplification, not a bug.
                "break_taken_last_hour": False,
            })
            if current_state != "baseline":
                task = "whatever you're working on"
                suggestion = self.adhd_detector.get_state_appropriate_intervention(current_state, task)
                self._dispatch_intervention({
                    "issue": {"category": "adhd_state", "metric": current_state, "deviation_from_baseline": 0.5},
                    "severity": 4 if suggestion.get("mandatory") else 3,
                    "strategy": suggestion,
                    "timestamp": datetime.now(),
                })

    def _extract_visual_issues(self, description: str) -> List[Dict[str, Any]]:
        """Keyword scan over a REAL scene description (from moondream via
        SceneAnalyzer) -- a coarse substitute for the grooming/clutter
        computer vision that was never actually built (see module comment
        above). Deviation scores are rough fixed magnitudes, not derived
        from any real baseline -- there isn't one to derive from yet."""
        lower = description.lower()
        issues: List[Dict[str, Any]] = []
        if any(kw in lower for kw in _CLUTTER_KEYWORDS):
            issues.append({"category": "household", "metric": "clutter", "deviation_from_baseline": 0.4, "description": description})
        if any(kw in lower for kw in _GROOMING_KEYWORDS):
            issues.append({"category": "hygiene", "metric": "grooming", "deviation_from_baseline": 0.4, "description": description})
        if any(kw in lower for kw in _POSTURE_KEYWORDS):
            issues.append({"category": "posture", "metric": "slouching", "deviation_from_baseline": 0.3, "description": description})
        return issues

    def _update_presence(self, person_id: str) -> float:
        """Track continuous in-frame presence for one person_id from real
        person_sighting events. Returns hours of the CURRENT unbroken
        session (0 if a session isn't underway yet)."""
        now = time.monotonic()
        session = self._presence.get(person_id)
        if session is None or (now - session["last_seen"]) > _PRESENCE_GAP_RESET_S:
            # First sighting, or the gap since the last one was long enough
            # to count as "they left and came back" -- start a new session.
            self._presence[person_id] = {"first_seen": now, "last_seen": now}
            return 0.0
        session["last_seen"] = now
        return (now - session["first_seen"]) / 3600.0

    def _on_utterance(self, event: Event) -> None:
        """Handle user speech for relational/task tracking."""
        raw_text = event.data.get("text", "") or ""
        text = raw_text.lower()

        # Track commitments (heuristic-based). Previously hardcoded the
        # contact name to the literal string "unknown" no matter what was
        # said -- every commitment landed on the same fake contact. Now
        # pulls the name out of the "tell <name> ..." pattern itself (still
        # a regex heuristic, not real NER -- good enough to stop discarding
        # the one piece of information the sentence actually gives us).
        if "tell" in text and ("i'll" in text or "i will" in text):
            person = self._extract_commitment_target(raw_text) or "unknown"
            self.rel_tracker.track_commitment(person, raw_text.strip())

        # Track time estimates
        if "5 minutes" in text or "minutes" in text:
            # self.time_blindness.track_estimate(...)
            pass

    @staticmethod
    def _extract_commitment_target(raw_text: str) -> Optional[str]:
        """Pull the name out of "tell <name> (that) I'll/I will ..." --
        e.g. "Tell Mike I'll call him later" -> "Mike". Deliberately
        conservative: only matches 1-2 word names, returns None (caller
        falls back to "unknown") rather than guessing on anything odder."""
        import re
        match = re.search(
            r"\btell\s+([A-Za-z][A-Za-z']*(?:\s+[A-Za-z][A-Za-z']*)?)\s+(?:that\s+)?i(?:'ll|\s+will)\b",
            raw_text,
            re.IGNORECASE,
        )
        if not match:
            return None
        name = match.group(1).strip()
        # Reject obvious non-names that "tell ... i'll" can still match,
        # e.g. "tell them I'll be late".
        if name.lower() in ("them", "her", "him", "everyone", "people", "the team"):
            return None
        return " ".join(w.capitalize() for w in name.split())

    def _on_action(self, event: Event) -> None:
        """Handle agent actions (audit)."""
        pass

    def _dispatch_intervention(self, intervention: Dict[str, Any]) -> None:
        """Decided intervention -> durable SQLite row + live push, both ends
        (2026-09-16).

        Previously this only ever published a local AGENT_INTERVENTION
        event, consumed by a SINGLE in-memory string on whichever CoreAgent
        happened to be subscribed at that exact moment -- lost on restart,
        overwritten by the next one, and never even fired at all while
        BlindspotAgent only lived inside CoreAgent's process (no GUI/
        browser open = no BlindspotAgent = nothing decided, ever, even
        though the observer was still detecting things and logging raw
        data). Now: every decided intervention is written to
        pending_interventions first (durable, survives any process being
        down for any length of time), then pushed on
        INTERVENTION_REDIS_CHANNEL for whichever CoreAgent process is alive
        right now to pick up live, and CoreAgent also does a startup sweep
        of undelivered rows to catch up on anything it missed. The local
        AGENT_INTERVENTION publish stays too, for a same-process subscriber
        (harmless no-op when nothing's listening, e.g. this instance
        running inside observer_service.py where nothing subscribes to it).

        Cooldown: the same category+metric won't re-fire for
        _INTERVENTION_COOLDOWN_S, so a clutter flag doesn't repeat every
        30 seconds for half an hour once it's been raised once. This is
        per-instance, in-memory state -- correct now that only ONE
        BlindspotAgent instance (observer_service.py's) ever decides on
        observations, so there's no second instance with its own cooldown
        clock to double-fire against.
        """
        issue = intervention["issue"]
        cooldown_key = f"{issue.get('category', '?')}.{issue.get('metric', '?')}"
        now = time.monotonic()
        if now - self._last_dispatch.get(cooldown_key, 0.0) < _INTERVENTION_COOLDOWN_S:
            return
        self._last_dispatch[cooldown_key] = now

        strategy = intervention.get("strategy") or {}
        # Prefer an actual drafted line (ADHDStateDetector's
        # get_state_appropriate_intervention includes one); otherwise a
        # real observed description (staleness findings, and the keyword-
        # matched visual issues both carry one) beats the generic
        # templated sentence -- CoreAgent gets the actual specific thing
        # that was noticed, not just a category label. Either way,
        # CoreAgent's own prompt explicitly tells the model to paraphrase
        # this in its own words rather than read it verbatim.
        content = (
            strategy.get("message")
            or issue.get("description")
            or (
                f"Recent observations suggest a {issue.get('category', 'general')} "
                f"concern ({issue.get('metric', 'unspecified')})."
            )
        )
        category = issue.get("category", "general")
        metric = issue.get("metric", "unspecified")
        severity = intervention.get("severity")

        logger.info(f"Dispatching Blindspot intervention: {cooldown_key} -> {content}")

        try:
            self._store.add_pending_intervention(
                category=category, metric=metric, content=content, severity=severity,
            )
        except Exception as e:
            logger.warning(f"Failed to persist intervention (will still push live): {e}")

        payload = {"content": content, "category": category, "metric": metric, "severity": severity}
        try:
            self._redis.publish(INTERVENTION_REDIS_CHANNEL, payload)
        except Exception as e:
            logger.debug(f"Redis intervention push failed (non-fatal): {e}")

        self._bus.publish(Event(
            type=EventType.AGENT_INTERVENTION,
            source="blindspot_agent",
            data={
                "agent": "blindspot",
                "content": content,
                "severity": severity,
                "strategy": strategy,
            },
        ))
