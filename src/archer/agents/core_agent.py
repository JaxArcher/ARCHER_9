"""
ARCHER Single-Agent Core Engine (CoreAgent).

Build-alongside implementation of the single local-primary conversational agent
as specified in ARCHER Update Instructions v2 (Section 6).

Reuses existing memory layers (SQLite, ChromaDB, OpenMemory, Redis) and EventBus,
owning its own context-assembly pipeline and deterministic cloud-delegation triggers.
"""

from __future__ import annotations

import re
import time
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.core.toggle import get_toggle_service
from archer.memory.sqlite_store import get_sqlite_store
from archer.memory.redis_buffer import get_redis_buffer
from archer.memory.openmemory_store import get_openmemory_store
from archer.memory.markdown_logger import get_markdown_logger
from archer.memory.chromadb_store import get_chromadb_store


# Safety crisis keywords for mandatory hard code-level override
_SAFETY_CRISIS_KEYWORDS = {
    "suicide", "kill myself", "end my life", "want to die", "harm myself", "self harm",
    "emergency", "911", "overdose"
}

# Domain stance keywords for tag scoring
_STANCE_KEYWORDS = {
    "coaching": {
        "workout", "exercise", "gym", "run", "lift", "pushup", "squat", "cardio",
        "calories", "protein", "nutrition", "diet", "macros", "posture", "sedentary"
    },
    "therapeutic": {
        "stressed", "anxious", "depressed", "sad", "lonely", "overwhelmed",
        "mental health", "burnout", "insomnia", "grief", "venting",
        # Broadened 2026-09-17 (ARCHER "reflective mode" spec) -- the
        # original list only caught explicit mood words, which misses most
        # genuine personal/reflective disclosure. Real example that missed
        # every original keyword: "I just came to the realization that I
        # have RSD... People used to say I was just sensitive... growing up
        # in poverty with older brothers..." -- a long first-person
        # narrative about childhood/family/self-realization with zero
        # mood-word hits. See _is_reflective_narrative for the
        # length/structure heuristic that catches cases like that one too.
        "childhood", "growing up", "my father", "my mother", "my parents",
        "trauma", "realization", "realized", "diagnosed", "diagnosis",
        "rejection", "rejected", "abandoned", "betrayed", "i feel like",
        "i've been feeling", "reflecting on", "reflect on", "looking back",
        "growing up poor", "used to cry", "when i was younger"
    },
    "financial": {
        "stock", "stocks", "portfolio", "market", "shares", "dividend", "s&p",
        "holdings", "investing", "trading", "returns"
    },
    "accountability": {
        "procrastination", "adhd", "focus", "distraction", "routine", "clutter",
        "habit", "time blindness", "tasks"
    },
    "research_rd": {
        "python", "code", "architecture", "script", "algorithm", "debug", "refactor", "api",
        "benchmark", "framework", "system design", "database", "engineering", "hardware", "ai model"
    }
}


import json
import httpx
from collections.abc import Generator

# Regex to split on sentence-ending punctuation followed by a space or end-of-string.
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+')


class ActivityStatusBuffer:
    """Rolling plain-language activity status buffer for ARCHER-wide awareness."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status_lines: List[str] = [
            "System online and monitoring ambient environment.",
            "No active alerts."
        ]

    def update_status(self, line: str) -> None:
        with self._lock:
            self._status_lines.append(line)
            if len(self._status_lines) > 5:
                self._status_lines = self._status_lines[-5:]

    def get_summary(self) -> str:
        with self._lock:
            return "\n".join(f"- {line}" for line in self._status_lines)


class CoreAgent:
    """
    Unified Single-Agent Core for ARCHER.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._toggle = get_toggle_service()
        self._store = get_sqlite_store()
        self._redis = get_redis_buffer()
        self._om = get_openmemory_store()
        self._md = get_markdown_logger()
        self._chroma = get_chromadb_store()
        self.activity_buffer = ActivityStatusBuffer()
        
        # Section 6.5 originally benchmark-selected qwen3:8b (136+ tok/s,
        # ~7.3GB VRAM headroom, Unsloth LoRA viability on 16GB GPU) — since
        # switched to gemma4:e4b (2026-09-16, Col's call) so this model can
        # both call tools and see images (screenshots) directly; see
        # config.py's core_primary_model for the full rationale.
        self.primary_model: str = self._config.core_primary_model
        
        # NVIDIA NIM client setup for cloud delegation (e.g. Kimi model)
        self._nvidia_client = None
        if self._config.nvidia_api_key:
            try:
                from openai import OpenAI
                self._nvidia_client = OpenAI(
                    api_key=self._config.nvidia_api_key,
                    base_url=self._config.nvidia_base_url,
                )
            except ImportError:
                logger.warning("openai package not found — CoreAgent NVIDIA NIM disabled.")

        self._history_lock = threading.Lock()
        self._turn_lock = threading.Lock()
        self._blindspot_lock = threading.Lock()
        self._pending_blindspot_flags: List[str] = []
        self._blindspot_state: Dict[str, Any] = {}
        self._conversation_history: List[Dict[str, str]] = []

        # Tool-calling (screenshots, PC/browser control, UI control like
        # switch_tab, inventory, ...) — same UniversalToolExecutor used
        # everywhere else in ARCHER, wired here for both cloud (_stream_cloud's
        # Claude branch) and local (_stream_local, Ollama) turns. This is
        # CoreAgent, not agents/orchestrator.py's AgentOrchestrator class —
        # AgentOrchestrator is never actually instantiated anywhere in the
        # running app (confirmed 2026-09-16), so tool support has to live
        # here to do anything at all.
        from archer.skills.tool_executor import UniversalToolExecutor
        self._tool_executor = UniversalToolExecutor()

        # Most recent local-model generation speed, in tokens/sec --
        # populated from Ollama's own eval_count/eval_duration on each
        # streaming turn's final chunk (see _stream_local). Surfaced on
        # the SYSTEM dashboard card (2026-09-16, Col's ask for a tokens
        # chart) -- None until the first local turn completes. Cloud
        # turns (Claude/NVIDIA) don't update this; it's specifically
        # about local-model throughput, which is what the earlier
        # ~100s-delay investigation cared about.
        self._last_tokens_per_sec: Optional[float] = None

        # Blindspot: reconnected 2026-09-16 (it lived only inside the dead
        # AgentOrchestrator before this). Passive by design (Col's call):
        # flagged observations become available in context the NEXT time a
        # conversation turn happens, not an unprompted interruption.
        #
        # Reconciled again 2026-09-16 (same day, later): decision-making
        # moved into archer/observer_service.py so it runs independent of
        # whether this process is even open (see blindspot_agent.py's
        # handle_observations/handle_utterances split). This instance now
        # ONLY handles utterance-based relationship/commitment tracking
        # (real STT needs a live voice pipeline, which only exists here) --
        # handle_observations=False means it never independently decides on
        # raw scene/staleness/person_sighting events itself anymore, so
        # there's no risk of double-deciding the same event the
        # observer_service.py instance already decided on.
        from archer.agents.blindspot_agent import BlindspotAgent, INTERVENTION_REDIS_CHANNEL
        self._blindspot = BlindspotAgent(handle_observations=False)
        self._bus.subscribe(EventType.AGENT_INTERVENTION, self._on_blindspot_intervention)

        # Live delivery of interventions DECIDED elsewhere (observer_service.py's
        # BlindspotAgent instance), pushed here the moment they're decided,
        # regardless of which process made the decision.
        self._redis.subscribe(INTERVENTION_REDIS_CHANNEL, self._on_redis_intervention)

        # Startup catch-up (2026-09-16): anything decided while THIS process
        # wasn't running (GUI/browser closed, or simply not started yet)
        # still needs to reach the user eventually. observer_service.py's
        # BlindspotAgent persists every decision durably regardless of
        # whether anyone's listening live -- pull everything undelivered
        # now, queue it the same as a live one, and mark it delivered so
        # this doesn't repeat on the next restart. Col's call (2026-09-16):
        # surface everything, no cap/expiry on how much may have piled up.
        try:
            undelivered = self._store.get_undelivered_interventions()
            if undelivered:
                with self._blindspot_lock:
                    self._pending_blindspot_flags.extend(row["content"] for row in undelivered)
                self._store.mark_interventions_delivered([row["id"] for row in undelivered])
                logger.info(
                    f"Caught up on {len(undelivered)} Blindspot intervention(s) "
                    f"decided while this process wasn't running."
                )
        except Exception as e:
            logger.warning(f"Blindspot intervention catch-up failed (non-fatal): {e}")

        # Pattern recognition / recursive learning (2026-09-16): real-time,
        # per-turn entity + recurring-theme extraction (Col's call). Fired
        # in the background after each turn's response is already complete
        # -- see memory/pattern_learner.py's module docstring for the full
        # rationale. get_context_glossary() below feeds learned entities
        # back into every future system prompt.
        from archer.memory.pattern_learner import get_pattern_learner
        self._pattern_learner = get_pattern_learner()

        # Subscribe to observer events for activity buffer
        self._bus.subscribe(EventType.OBSERVATION_EVENT, self._on_observation)

        # Bridge the standalone observer service's Redis-published events
        # onto this process's own local event bus (2026-09-16). The
        # observer now runs as its own OS process (archer/observer_service.py),
        # decoupled from whichever process CoreAgent lives in (desktop GUI
        # or browser server) -- Redis pub/sub is the cross-process link.
        # Relaying onto the local bus here means _on_observation above and
        # BlindspotAgent's own OBSERVATION_EVENT subscription need zero
        # changes to consume it.
        from archer.observer.pipeline import OBSERVER_REDIS_CHANNEL
        self._redis.subscribe(OBSERVER_REDIS_CHANNEL, self._on_redis_observer_event)
        logger.info(f"CoreAgent (Single-Agent Architecture) initialized with primary model: {self.primary_model}")

    @property
    def active_agent(self) -> str:
        """Compatibility property for server/GUI components."""
        return "core_agent"

    @property
    def session_id(self) -> str:
        """Compatibility property for server/GUI components."""
        return "core_agent"

    def process_request(self, user_input: str) -> str:
        """Synchronous full-turn string generation (compatibility method)."""
        return " ".join(list(self.process_turn_streaming(user_input)))

    def _on_observation(self, event: Event) -> None:
        """Update rolling activity status buffer and pending Blindspot flag on significant events."""
        event_type = event.data.get("event_type", "observation")
        if event_type == "scene":
            desc = event.data.get("description", "")
            if desc:
                self.activity_buffer.update_status(f"Observer visual scene: {desc}")
        elif event_type == "person_sighting":
            person = event.data.get("person_id", "unrecognized person")
            self.activity_buffer.update_status(f"Observer person sighting: {person}")

    def _on_redis_observer_event(self, data: Dict[str, Any]) -> None:
        """Callback for the Redis subscription set up in __init__ --
        `data` is the same flat dict archer/observer_service.py's
        ObserverPipeline._publish_observation (or staleness_reasoner.py)
        published. Republish it as a normal local Event so every existing
        OBSERVATION_EVENT subscriber (this class's own _on_observation,
        BlindspotAgent's) just works, unmodified."""
        self._bus.publish(Event(
            type=EventType.OBSERVATION_EVENT,
            source="observer_service",
            data=data,
        ))

    def _on_blindspot_intervention(self, event: Event) -> None:
        """Same-process AGENT_INTERVENTION publish (see blindspot_agent.py's
        _dispatch_intervention) -- kept for any future same-process
        subscriber, though with handle_observations=False this instance's
        own BlindspotAgent never actually fires one anymore. Queued (not
        overwritten) since 2026-09-16 -- multiple can now be pending at
        once, all surfaced next turn, none silently dropped."""
        content = event.data.get("content", "")
        if not content:
            return
        with self._blindspot_lock:
            self._pending_blindspot_flags.append(content)

    def _on_redis_intervention(self, data: Dict[str, Any]) -> None:
        """Live cross-process delivery: observer_service.py's BlindspotAgent
        instance decided this is worth mentioning, right now, regardless of
        which process made that decision. Same queue as the startup
        catch-up and the same-process path above -- build_context_system_
        prompt doesn't need to know or care which of the three got a given
        entry in there."""
        content = data.get("content")
        if not content:
            return
        with self._blindspot_lock:
            self._pending_blindspot_flags.append(content)


    def check_safety_override(self, text: str) -> Optional[str]:
        """Safety pre-check (code-level crisis override)."""
        lower = text.lower()
        for kw in _SAFETY_CRISIS_KEYWORDS:
            if kw in lower:
                logger.warning(f"CoreAgent Safety Triggered by keyword: {kw}")
                return (
                    "I hear that you are going through a critical moment right now. "
                    "Please know you are not alone. If you are in crisis or feeling unsafe, "
                    "please reach out directly to 988 (Suicide & Crisis Lifeline) or call 911 immediately."
                )
        return None

    def calculate_stance_tags(self, text: str) -> Dict[str, float]:
        """
        Score situational stance tags from input text.
        Applies context awareness to avoid triggering on quotes, system feedback, or negations.
        """
        lower = text.lower()

        # Check if user is quoting back, referencing past system claims, or providing system correction
        quote_correction_patterns = [
            "you said", "you claimed", "you thought", "you called", "you told",
            "you wrote", "you mentioned", "your reading", "your claim", "your assumption",
            "incorrect", "inaccurate", "wrong", "mistake", "didn't say", "did not say",
            "why did you say", "i'm not", "i am not", "not sad", "not angry", "not anxious",
            "not depressed", "not stressed"
        ]
        is_quote_or_correction = any(pattern in lower for pattern in quote_correction_patterns)

        words = set(re.findall(r'\b[\w\'-]+\b', lower))
        scores: Dict[str, float] = {}
        for stance, kws in _STANCE_KEYWORDS.items():
            # If the user is quoting past claims or correcting system readings, suppress therapeutic stance
            if stance == "therapeutic" and is_quote_or_correction:
                continue

            matching_kws = [kw for kw in kws if kw in words or (len(kw.split()) > 1 and kw in lower)]
            if is_quote_or_correction and stance in ("coaching", "accountability"):
                matching_kws = [
                    kw for kw in matching_kws
                    if not (f"not {kw}" in lower or f"no {kw}" in lower or f"never {kw}" in lower)
                ]

            count = len(matching_kws)
            if count > 0:
                scores[stance] = float(count)

        # Structural fallback for "therapeutic" (2026-09-17, ARCHER
        # reflective-mode spec): a long, first-person, narrative turn with
        # no question and no task-shaped imperative reads as personal
        # disclosure even when it happens to avoid every keyword above --
        # the real example that motivated this was a multi-sentence
        # childhood/family story with zero keyword hits. Kept as a small
        # flat score bump (not scaled to length) since this only needs to
        # flip the tag ON for downstream `if "therapeutic" in stance_tags`
        # checks, not compete quantitatively with real keyword matches.
        if not is_quote_or_correction and "therapeutic" not in scores:
            if self._is_reflective_narrative(text, words):
                scores["therapeutic"] = 0.5

        return scores

    @staticmethod
    def _is_reflective_narrative(text: str, words: set) -> bool:
        """
        Heuristic-only, no extra model/network call (this runs inline in
        build_context_system_prompt's hot path on every turn, so it has to
        stay cheap) -- see calculate_stance_tags. Flags a turn as
        reflective/personal narrative rather than a task request when it's
        long, mostly first-person, and doesn't read as a question or a
        command.
        """
        if "?" not in text and len(words) >= 25:
            first_person = {"i", "i'm", "i've", "i'd", "i'll", "my", "me", "myself"}
            first_person_hits = sum(1 for w in words if w in first_person)
            if first_person_hits >= 3:
                # Command/task-shaped turns are usually short imperatives
                # even when long-winded about context first -- a leading
                # imperative verb strongly suggests "do this" rather than
                # "here's what's on my mind".
                imperative_starts = (
                    "remind", "schedule", "set", "add", "create", "open",
                    "turn", "play", "send", "call", "text", "check",
                    "search", "find", "look up", "what is", "what's",
                    "how do", "how much", "how many", "can you", "could you",
                )
                lowered = text.strip().lower()
                if not lowered.startswith(imperative_starts):
                    return True
        return False

    def retrieve_domain_knowledge(self, stance_tags: Dict[str, float], text: str) -> str:
        """Retrieve relevant ChromaDB knowledge base items unconditionally based on stance tags."""
        retrieved: List[str] = []
        if "therapeutic" in stance_tags or "accountability" in stance_tags:
            try:
                memos = self._chroma.query(query_text=text, n_results=2, collection_name="psychology_knowledge")
                for m in memos:
                    if m.get("content"):
                        retrieved.append(f"[Psychology KB] {m['content']}")
            except Exception:
                pass

        if "coaching" in stance_tags:
            try:
                memos = self._chroma.query(query_text=text, n_results=2, collection_name="trainer_knowledge")
                for m in memos:
                    if m.get("content"):
                        retrieved.append(f"[Fitness KB] {m['content']}")
            except Exception:
                pass

        if "financial" in stance_tags:
            try:
                memos = self._chroma.query(query_text=text, n_results=2, collection_name="investment_knowledge")
                for m in memos:
                    if m.get("content"):
                        retrieved.append(f"[Financial KB] {m['content']}")
            except Exception:
                pass

        if "research_rd" in stance_tags:
            try:
                memos = self._chroma.query(query_text=text, n_results=2, collection_name="research_knowledge")
                for m in memos:
                    if m.get("content"):
                        retrieved.append(f"[R&D KB] {m['content']}")
            except Exception:
                pass

        return "\n".join(retrieved)

    def evaluate_cloud_delegation(self, text: str, total_tokens_est: int) -> Optional[str]:
        """
        Evaluate deterministic cloud delegation triggers:
        1. Explicit user request ("ask claude", "use cloud")
        2. Complex task category heuristics (heavy code, multi-page doc analysis)
        3. Context budget overflow (>2000 tokens)
        """
        lower = text.lower()
        if "ask claude" in lower or "use cloud" in lower or "cloud mode" in lower:
            return "explicit_request"
        
        code_heuristics = ["write a script", "build a class", "refactor", "complex code", "architecture spec"]
        if any(h in lower for h in code_heuristics):
            return "complex_task"
            
        if total_tokens_est > 2000:
            return "context_overflow"
            
        return None

    # Sentinel distinguishing "this wasn't a visual question" (returns None,
    # caller adds nothing to context) from "this WAS a visual question but
    # the vision model couldn't be reached" (caller must tell the LLM the
    # camera is unavailable, rather than silently saying nothing — which is
    # what let the LLM confidently invent a whole fabricated scene when the
    # observer_ollama_url instance turned out not to be running at all).
    VISION_UNAVAILABLE = "__VISION_UNAVAILABLE__"

    def _publish_visual_status(self, note: str) -> None:
        """Best-effort push of a human-readable "what the camera check just
        did" line to the browser's LOGS pane (2026-09-18, Col's request --
        see server.py's status-line bridge for where this actually gets
        rendered). Separate from the logger.info/.warning calls right next
        to each call site: those go to the DEBUG-level file log Col rarely
        looks at live; this is specifically for the curated, in-the-moment
        feed. Never let a broadcast failure break the actual visual query."""
        try:
            self._bus.publish(Event(
                type=EventType.VISUAL_QUERY,
                source="core_agent",
                data={"note": note},
            ))
        except Exception:
            pass

    def _check_visual_query(self, text: str) -> Optional[Dict[str, Any]]:
        """
        If text asks a visual question ("what do you see", "look at this", "how many fingers am I holding up"),
        capture a frame from the camera pipeline for the model to see DIRECTLY.

        Rewritten 2026-09-16 (Col's call): previously ran the frame through
        moondream (a tiny 1.42B captioning model) to get a text description,
        then handed THAT text to gemma4:e4b -- a lossy detour now that
        gemma4:e4b is natively multimodal and can just look at the picture
        itself. Moondream stays doing its OTHER job (observer/analyzers.py's
        SceneAnalyzer, feeding BlindspotAgent/staleness_reasoner's ambient
        passes) -- this change only touches the GUI's on-demand "look at
        this" path.

        WHO is in frame is deliberately NOT asked of any vision-language
        model, moondream or gemma4:e4b -- general VLMs aren't fine-tuned on
        Col's face and will happily hallucinate a confident-sounding wrong
        name from pixels alone, which is worse than admitting uncertainty.
        Identity comes from InsightFace face-embedding matching instead
        (ObserverPipeline.person_identifier, the same engine
        observer_service.py's analysis loop uses), run on this exact frame
        so it can't go stale relative to what the model is actually shown.

        Returns:
            None -- not a visual question.
            self.VISION_UNAVAILABLE -- visual question, but no camera frame
                reachable.
            {"image_b64": ..., "identity_note": ...} -- success. image_b64
                is attached directly to the model's message (see
                _stream_local/_stream_cloud); identity_note is folded into
                the text system prompt by build_context_system_prompt.
        """
        lower = text.lower()
        visual_phrases = [
            "what do you see", "look at", "in front of the camera", "describe what you see",
            "what am i holding", "what is in front of me", "what's on my desk", "what's in the camera",
            "can you see me", "can you see this", "how many fingers", "what am i wearing",
            "what color is", "what is this", "in my hand", "am i holding", "am i wearing",
            "what's in my hand", "how many", "what does this look like", "on camera", "in the feed",
            "how many fingers am i holding up", "finger count", "count my fingers", "can you see",
            "do you see", "what color", "what is on", "read this", "what does it say"
        ]

        visual_keywords = {
            "see", "look", "holding", "wearing", "camera", "feed", "view", "picture",
            "image", "frame", "showing", "pointing", "watching", "finger", "fingers", "hand", "hands",
            "shirt", "glasses", "desk", "object", "item", "color", "sign", "text", "card", "read",
            "count", "spot", "viewing"
        }
        question_words = {
            "what", "how", "who", "where", "which", "can", "could", "do", "does", "is", "are", "am",
            "tell", "count", "describe", "identify", "check", "?"
        }

        words = set(re.findall(r'\b[\w\'-]+\b', lower))
        has_phrase_match = any(p in lower for p in visual_phrases)
        has_keyword_combo = bool(words & visual_keywords) and (bool(words & question_words) or "?" in lower)

        if not (has_phrase_match or has_keyword_combo):
            return None

        try:
            from archer.observer.pipeline import ObserverPipeline
            pipeline = ObserverPipeline.get_instance()
            # Explicit released-camera check (2026-09-18): the browser's
            # "Camera" button frees the physical device so barehands'
            # gesture control can grab exclusive access (Windows only
            # allows one owner). Before this, get_latest_frame() would
            # still happily hand back whatever frame was captured right
            # before release -- camera.py's stop() now clears it, but
            # checking is_camera_released here too gives an honest,
            # specific reason instead of a generic "no frame" one.
            if pipeline and pipeline.is_camera_released:
                logger.warning(
                    "Visual Q&A: camera is currently released (freed for another "
                    "app, e.g. barehands gesture control) -- no live frame available."
                )
                self._publish_visual_status(
                    "Camera is released (freed for another app) -- can't look right now."
                )
                return self.VISION_UNAVAILABLE
            if pipeline and pipeline.camera:
                frame, timestamp = pipeline.camera.get_latest_frame()
                # Staleness check: get_latest_frame() previously only ever
                # checked "is it None", never how OLD it is. A frame more
                # than a few capture-intervals old (this camera runs at
                # ~2 FPS / 0.5s intervals) means something's wrong with
                # the capture loop even though the object itself looks
                # fine -- treat it the same as no frame rather than let
                # the model confidently describe a stale scene.
                frame_age = (time.monotonic() - timestamp) if frame is not None else None
                if frame is not None and frame_age is not None and frame_age > 3.0:
                    logger.warning(
                        f"Visual Q&A: latest frame is {frame_age:.1f}s old (stale) -- "
                        "treating as unavailable rather than attaching it."
                    )
                    self._publish_visual_status(
                        f"Latest camera frame is {frame_age:.1f}s old (stale) -- skipping it."
                    )
                    frame = None
                if frame is not None:
                    import cv2
                    import base64
                    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    img_bytes = buffer.tobytes()
                    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

                    # Debug dump (2026-09-18, Col's request): the audio
                    # pipeline has saved every played clip to scratch/ for
                    # a while now specifically so a "did it actually hear
                    # right" question can be answered by listening to the
                    # file instead of guessing from logs alone. Nothing
                    # equivalent existed for vision, so a "did it actually
                    # SEE right" question -- like this one -- had no way to
                    # be settled except debating the model's own words.
                    # Mirrors that same pattern for the exact JPEG bytes
                    # actually sent to gemma4:e4b.
                    debug_frame_path = None
                    try:
                        import os
                        os.makedirs("scratch", exist_ok=True)
                        ts = int(time.time() * 1000)
                        debug_frame_path = f"scratch/visual_qna_frame_{ts}.jpg"
                        with open(debug_frame_path, "wb") as f:
                            f.write(img_bytes)
                    except Exception as e:
                        logger.debug(f"Visual Q&A frame debug dump failed (non-fatal): {e}")

                    # Identity, from InsightFace face-embedding matching on
                    # THIS exact frame -- not from moondream or gemma4:e4b
                    # guessing (see method docstring for why). Best-effort:
                    # a face-recognition hiccup shouldn't block the visual
                    # answer itself, just mean identity is reported as
                    # unavailable this once.
                    identity_note = "Face recognition unavailable for this frame."
                    try:
                        identified = pipeline.person_identifier.identify_persons(
                            frame, camera_source="webcam"
                        )
                        if identified:
                            parts = []
                            for p in identified:
                                if p.get("is_known"):
                                    parts.append(
                                        f"{p['person_id']} (recognized, "
                                        f"{p.get('confidence', 0.0) * 100:.0f}% confidence)"
                                    )
                                else:
                                    parts.append(f"an unrecognized person ({p['person_id']})")
                            identity_note = (
                                "Face recognition identified: " + "; ".join(parts) + "."
                            )
                        else:
                            identity_note = (
                                "Face recognition found no face in this frame (the person may "
                                "not be facing the camera, or may be out of frame)."
                            )
                    except Exception as e:
                        logger.debug(f"Visual Q&A: face identification failed (non-fatal): {e}")

                    logger.info(
                        f"Visual Q&A: attaching frame directly to {self.primary_model} "
                        f"(age={frame_age:.2f}s, saved to {debug_frame_path or 'N/A'}) "
                        f"({identity_note})"
                    )
                    self._publish_visual_status(f"Looking at the camera -- {identity_note}")
                    return {"image_b64": img_b64, "identity_note": identity_note}
                else:
                    logger.warning("Visual Q&A: no camera frame available yet (frame is None).")
                    self._publish_visual_status("No camera frame available yet.")
                    return self.VISION_UNAVAILABLE
            else:
                logger.warning("Visual Q&A: ObserverPipeline or camera not available.")
                self._publish_visual_status("Camera isn't available right now.")
                return self.VISION_UNAVAILABLE
        except Exception as e:
            logger.warning(f"Visual Q&A query failed: {e}")
            self._publish_visual_status(f"Camera check failed: {e}")
            return self.VISION_UNAVAILABLE

    # Introduction phrasing that plausibly names a person who's currently
    # in frame. Deliberately narrow (a handful of clear patterns) rather
    # than anything that merely mentions a capitalized word -- a false
    # positive here silently mis-names someone's face.
    _INTRODUCTION_PATTERNS = [
        re.compile(r"\bthis is\s+([A-Za-z][\w'-]*)", re.IGNORECASE),
        re.compile(r"\bmeet\s+([A-Za-z][\w'-]*)", re.IGNORECASE),
        re.compile(r"\bthat'?s\s+([A-Za-z][\w'-]*)", re.IGNORECASE),
        re.compile(r"\b(?:her|his) name(?:'s| is)\s+([A-Za-z][\w'-]*)", re.IGNORECASE),
        re.compile(r"\bsay hi to\s+([A-Za-z][\w'-]*)", re.IGNORECASE),
    ]
    # Words that legitimately follow "this is"/"that's" without naming a
    # person ("this is great", "that's fine") -- checked case-insensitively
    # against whatever the pattern captured so those don't get treated as
    # a name.
    _INTRODUCTION_STOPWORDS = {
        "is", "the", "a", "an", "not", "just", "actually", "really", "so", "what",
        "how", "great", "good", "bad", "fine", "important", "cool", "it", "my",
        "your", "for", "about", "why", "all", "going", "here", "there", "me",
        "you", "us", "them", "gonna", "correct", "right", "true", "false",
        "done", "over", "on", "off", "nice", "awesome", "crazy", "weird",
        "funny", "annoying", "ridiculous", "amazing", "perfect", "wrong",
    }

    def _check_person_introduction(self, text: str) -> Optional[str]:
        """
        Col's explicit ask (2026-09-16): no manual enrollment step for
        anyone but himself -- ARCHER should either pick up a person's
        identity from context, or ask Col later. This is the "pick up from
        context" half. (The "ask later" half is pending_person_confirmations
        / person_id.py's upsert on every unknown sighting, surfaced in the
        browser MEMORY tab's "Unrecognized People" pane.)

        When Col introduces someone by name ("this is Sarah", "meet Dave")
        while exactly one unrecognized face is in the current webcam frame,
        silently bind that name to that face's InsightFace embedding via
        add_known_person() -- no separate enrollment flow, no confirmation
        round-trip. Deliberately conservative: zero or multiple unrecognized
        faces in frame means do nothing rather than guess which one is
        "Sarah".

        Returns a short note for the system prompt on a successful bind
        (so the model doesn't need to guess whether it worked), else None.
        """
        name: Optional[str] = None
        for pattern in self._INTRODUCTION_PATTERNS:
            m = pattern.search(text)
            if m:
                candidate = m.group(1).strip("'\"., ")
                if candidate.lower() not in self._INTRODUCTION_STOPWORDS and len(candidate) > 1:
                    name = candidate[:1].upper() + candidate[1:]
                    break

        if not name:
            return None

        try:
            from archer.observer.pipeline import ObserverPipeline
            pipeline = ObserverPipeline.get_instance()
            if not (pipeline and pipeline.camera):
                return None
            frame, _ts = pipeline.camera.get_latest_frame()
            if frame is None:
                return None

            identified = pipeline.person_identifier.identify_persons(frame, camera_source="webcam")
            unknown = [p for p in identified if not p.get("is_known")]
            if len(unknown) != 1:
                # Nobody unrecognized in frame, or more than one -- too
                # ambiguous to guess which face "Sarah" refers to.
                return None

            target = unknown[0]
            emb_bytes = target.get("embedding")
            if not emb_bytes:
                return None

            self._store.add_known_person(name=name, embedding=emb_bytes)
            try:
                self._store.resolve_pending_person_confirmation_by_person_id(
                    target["person_id"], status="confirmed", confirmed_name=name
                )
            except Exception:
                pass
            logger.info(
                f"Person Recognition: learned to recognize '{name}' from a live "
                f"introduction (was tracked as {target['person_id']})."
            )
            return f"Learned to recognize {name} from the camera just now -- will recognize them going forward."
        except Exception as e:
            logger.debug(f"Person introduction binding failed (non-fatal): {e}")
            return None

    @property
    def pc_controller(self):
        """The live PCController (Playwright browser, screenshots, click/
        type automation) that backs every PC-control/browser-control tool
        call this turn. Exposed publicly so server.py can mirror the same
        Playwright browser's screen into the browser dashboard pane
        (2026-09-16, Col's ask) without needing a second browser instance
        or reaching into a private attribute."""
        return self._tool_executor._pc_controller

    def _maybe_extract_profile_insight(self, user_input: str, full_response: str) -> None:
        """
        Distill a reflective-mode turn into a durable profile_facts row, in
        the background, so it never adds latency to the response itself
        (fire-and-forget thread, same pattern as voice/pipeline.py's
        _generate_contextual_filler).

        Gated behind config.profile_learning_enabled (default False) --
        a complete no-op until Col explicitly turns this on. See
        /areas/reflective-mode.md and profile_facts' schema comment in
        sqlite_store.py for the full design context: this is the write
        side of "reflective mode", separate from (and independent of) the
        stance-prompt behavior rules already wired into
        build_context_system_prompt.

        Re-checks calculate_stance_tags itself (cheap, no network call)
        rather than threading stance_tags through _stream_local/
        _stream_cloud's signatures, to keep this self-contained and easy
        to remove/disable in one place.
        """
        if not self._config.profile_learning_enabled:
            return
        try:
            stance_tags = self.calculate_stance_tags(user_input)
        except Exception:
            return
        if "therapeutic" not in stance_tags:
            return

        def _extract():
            try:
                resp = httpx.post(
                    f"{self._config.ollama_base_url}/api/chat",
                    json={
                        "model": self.primary_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You extract a durable personal-profile insight from one "
                                    "conversational exchange. Reply with ONLY a JSON object: "
                                    '{"domain": "<a one or two word category, e.g. motivation, '
                                    'executive_function, criticism_response, social_validation>", '
                                    '"insight": "<one or two plain sentences distilling the pattern, '
                                    'written about the user in third person, no therapy jargon>"}. '
                                    "If nothing durable or profile-worthy is actually present in this "
                                    'specific exchange, reply with {"domain": null, "insight": null}. '
                                    "Do not include anything else in your reply."
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"User said: {user_input}\n\nAssistant responded: {full_response}",
                            },
                        ],
                        "stream": False,
                        "options": {"num_predict": 120},
                    },
                    timeout=30.0,
                )
                if resp.status_code != 200:
                    return
                content = resp.json().get("message", {}).get("content", "").strip()
                data = json.loads(content)
                domain = data.get("domain")
                insight = data.get("insight")
                if domain and insight:
                    self._store.add_profile_fact(domain=str(domain), content=str(insight))
                    logger.info(f"Profile insight recorded ({domain}): {str(insight)[:100]}")
            except Exception as e:
                logger.debug(f"Profile insight extraction failed (non-fatal): {e}")

        threading.Thread(target=_extract, daemon=True, name="ProfileInsightExtractor").start()

    def build_context_system_prompt(self, text: str) -> tuple[str, Optional[str], Optional[str], str]:
        """
        Construct 7-step context assembly pipeline:
        1. Safety pre-check
        2. Core identity block
        3. Stance tag scoring
        4. Domain knowledge retrieval (including visual Q&A)
        5. Personal memory retrieval (OpenMemory)
        6. Rolling activity status buffer
        7. System prompt string + cloud trigger flag + visual image (if any)

        Third return value (2026-09-16): base64 JPEG of the current webcam
        frame when this turn asked a visual question, else None. Threaded
        through process_request_streaming to whichever of _stream_local /
        _stream_cloud handles the turn, so the actual model sees the
        picture directly (see _check_visual_query's docstring) instead of
        getting a pre-written text description baked into this string.

        Fourth return value, profile_block (2026-09-17, ARCHER "reflective
        mode" -- see /areas/reflective-mode.md): the standing "## User
        Profile" block built from profile_facts. Returned SEPARATELY from
        full_system_prompt rather than folded into it -- this is the one
        piece of context that must NEVER reach a cloud call. It is
        deliberately excluded from full_system_prompt's token_est below
        (so its size can't itself push a turn into context_overflow cloud
        delegation) and process_request_streaming appends it to the prompt
        ONLY on the _stream_local path. _stream_cloud never sees it, on
        ANY trigger reason (explicit request, complex_task, or
        context_overflow) -- this is a blanket exclusion, not a
        conditional one, because the whole point is that this content
        never leaves the machine, full stop.
        """
        safety_response = self.check_safety_override(text)
        if safety_response:
            return safety_response, "safety_override", None, ""

        # 1. System Environment (Deterministic System Fact: Current Local Date & Time)
        now_dt = datetime.now()
        date_str = now_dt.strftime("%A, %B %d, %Y")
        time_str = now_dt.strftime("%I:%M %p").lstrip("0")
        env_block = f"CURRENT SYSTEM ENVIRONMENT:\n- Current Local Date & Time: {date_str} at {time_str}\n\n"

        # 2. Core Identity Block & Operational Guidelines
        identity_block = (
            "You are ARCHER — Advanced Responsive Computing Helper & Executive Resource.\n"
            "You are Colby's primary personal companion and assistant. You speak with directness, "
            "warm empathy, and intelligent clarity. Maintain a single unified identity at all times.\n\n"
            f"{env_block}"
            "CRITICAL ATTRIBUTION & OPERATIONAL GUIDELINES:\n"
            "1. OBSERVER / SENSOR DATA: Ambient observations (e.g. visual scene descriptions, person sightings, behavioral patterns) "
            "are tentative sensor readings, NOT established facts or diagnoses. ALWAYS frame sensor findings as tentative, "
            "named observations or open questions (e.g. 'I noticed you seem busy at your desk — how are things going?'). "
            "NEVER assert sensor readings as definitive psychological truth or absolute fact.\n"
            "2. RETRIEVED KNOWLEDGE & PAST MEMORIES: Context provided under '## Reference Domain Knowledge' or "
            "'## Past Session Context' consists of external reference material or prior context from past interactions. "
            "NEVER claim, quote, or paraphrase retrieved reference material or past memory entries as if the user said them in the "
            "current turn. Only reference past context explicitly as prior context.\n"
            "3. INTEGRATED VOICE & VISION SYSTEM AND OS ACTION TOOLS: You ARE fully integrated into ARCHER's desktop environment "
            "with real, working voice input (Faster-Whisper STT), natural voice output, and a real-time camera/observer "
            "pipeline that feeds visual scene descriptions and person sightings into your context. NEVER claim you lack voice or camera "
            "capabilities. You ALSO have real tool-calling available this turn — screenshots, browser control, PC control, and "
            "switching tabs in ARCHER's own interface — when the conversation calls for one, actually call the tool rather than "
            "describing what you would do or claiming you can't.\n"
            "4. HARD ANTI-FABRICATION RULE FOR DATA & FIGURES: Current system date and time are provided in the system environment above and can be stated directly. However, NEVER state, invent, or estimate specific stock prices, financial figures, percentage moves, or unverified real-time external market data unless explicitly provided in context. If asked for current stock prices or live market data when no live data is in context, state plainly that you do not have live market data access.\n"
            "5. SPOKEN RESPONSE FORMAT: You are a voice-first assistant. Always respond in plain, natural spoken prose. NEVER use markdown "
            "formatting (no asterisks, headers, bold, bullet points) or emojis, as these are read literally by the text-to-speech engine.\n"
            "6. DIRECT OPERATIONAL FEEDBACK & CORRECTIONS: When given direct user feedback, corrections, or operational critiques "
            "(e.g. reporting inaccurate scene descriptions or flawed assumptions), acknowledge the feedback directly, "
            "concisely, and plainly without defensiveness or meta-commentary. State plainly what action or note you are taking in response.\n"
            "7. VISUAL QUESTIONS & CAMERA FEED: When visual feedback/description is provided from the camera feed, answer the user's "
            "visual question directly based on that visual data. If the visual data or camera frame is ambiguous, low resolution, or cannot "
            "conclusively answer a precise question (e.g. exact finger count, fine text, far objects), state honestly and plainly that the "
            "camera view is unclear or imprecise, rather than giving vague hedges, guessing, or pretending to confirm without being sure.\n"
            "8. GLOBAL NO ROLE-FILLER RULE: Across ALL responses in all contexts, NEVER include generic role declarations, self-justifying "
            "meta-commentary, or boundary reassurances (do NOT say 'I'm here to help', 'I'm here to help clarify', 'As an AI', 'My role is to', "
            "'I don't want to overstep', or 'I'm here to listen'). Cut all zero-information role filler. State answers, facts, actions, or open "
            "questions directly.\n"
            "9. FRAGMENTARY & AMBIGUOUS INPUTS: When the user's input is a short fragment or ambiguous phrase (e.g. 'of this.', 'and the.') "
            "and no specific domain knowledge or past memory in context resolves what they are referring to, NEVER guess, invent a hypothetical "
            "scenario, or fabricate prior conversation context. Ask the user directly and concisely to repeat or clarify what they meant — "
            "in ONE short sentence, not a list of guesses.\n"
            "10. VOICE BREVITY — HARD LIMIT: Every response is spoken aloud through TTS, and the user is waiting in real time. Default to "
            "1-2 short sentences. NEVER enumerate multiple options, interpretations, or examples as a list — no bullet points, no dashes, "
            "no 'first... second...', no 'for example: - X - Y - Z'. If you are unsure what the user meant, ask ONE brief clarifying "
            "question and stop there; do not also guess several possibilities in the same breath. Say less.\n"
            "11. LIVE CAMERA FEED IS AUTHORITATIVE FOR VISUAL QUESTIONS: If an image is attached to this message, it is the current "
            "webcam frame — answer the user's visual question directly from what you actually see in it, in as much detail as you can. "
            "Do NOT substitute, blend in, or fall back on unrelated ambient notes from '## ARCHER Observer & Sensor Activity' (a separate "
            "background summary) when answering a direct visual question — they are not the same data and mixing them produces wrong "
            "answers (e.g. describing a book from an old ambient scan instead of directly answering a question about clothing).\n"
            "12. NEVER GUESS WHO IS IN THE CAMERA IMAGE: You cannot reliably recognize specific people from pixels alone, and a "
            "confident wrong name is worse than no name. If a '[Live Camera Feed]' entry under Reference Domain Knowledge includes a "
            "face-recognition identity note, use that note — and only that note — for who's present. If it says no one was recognized "
            "or recognition was unavailable, say so plainly rather than guessing a name from appearance.\n"
            "13. USER PROFILE INFORMS HOW, NOT JUST WHAT: If a '## User Profile' section appears below, it holds durable patterns about "
            "how this specific user operates — motivation, executive function, how they respond to criticism, etc. Use it to shape HOW "
            "you phrase things across every kind of turn, not only reflective ones: how you word a task reminder or nudge, how you frame "
            "a Blindspot observation, how you motivate follow-through. Never quote it verbatim or announce that you're using it — let it "
            "change your phrasing silently, the way a person who actually knows someone adjusts their delivery without narrating why."
        )

        # 3. Stance Tag Scoring & Register Assembly
        blindspot_prompt = ""
        with self._blindspot_lock:
            if self._pending_blindspot_flags:
                # Multiple can be queued now -- live ones from this session,
                # plus a startup catch-up batch from downtime (Col's call,
                # 2026-09-16: surface everything, no cap). Joined into one
                # register rather than one prompt block per item so the
                # model weaves them into a natural sentence or two instead
                # of reciting a list.
                joined = "; ".join(self._pending_blindspot_flags)
                blindspot_prompt = (
                    f"\n[Stance: Proactive Blindspot Register - The user's ambient sensors detected potential physical/environmental pattern(s), possibly from while you weren't in conversation: {joined}.\n"
                    f"CRITICAL PARAPHRASE INSTRUCTION: You MUST naturally weave a gentle, warm, conversational mention of this into the opening of your response in your own words (e.g. 'I noticed your posture looks a bit slouched', 'You look like you've been sitting for a while', etc.). If more than one thing is listed, mention them naturally together, not as a recited list.\n"
                    f"DO NOT ever quote or echo system flag text, metadata phrases, or words like 'Observer flagged' verbatim. Paraphrase naturally as a caring companion.]"
                )
                self._pending_blindspot_flags = []  # Consume the whole queue so it surfaces only once

        stance_tags = self.calculate_stance_tags(text)
        stance_prompt = blindspot_prompt
        if "therapeutic" in stance_tags:
            # Rewritten 2026-09-17 per the ARCHER "reflective mode" behavior
            # spec (handoff doc, separate Claude project): four specific
            # traits, not a generic "be supportive" instruction. The
            # source example that motivated this got real synthesis
            # (naming a pattern across the user's father, school, and work
            # behavior) because it had the user's actual history to draw
            # on -- see the "## Past Session Context" / domain-knowledge
            # blocks already assembled elsewhere in this same prompt (steps
            # 4-5 above). This stance block only supplies the SHAPE of the
            # response; the substance still depends on what's actually in
            # those blocks for this user, which is currently thin until the
            # personal-data backfill (deliberately deferred, see
            # /areas/reflective-mode.md) actually happens.
            stance_prompt += (
                "\n[Stance: Reflective Register - This is personal/reflective disclosure, not a task request. "
                "Respond with these four traits, in this order: "
                "(1) Draw on whatever relevant context about the user already appears elsewhere in this prompt "
                "(Past Session Context, domain knowledge, entity glossary) automatically -- do not ask the user "
                "to re-explain their own history if it's already available to you. "
                "(2) Synthesize what they said into a real pattern or throughline, adding genuine interpretation -- "
                "do not just mirror their words back or offer a generic validating statement. "
                "(3) Keep a level, direct, respectful tone throughout -- treat the user as capable of hearing "
                "analysis, not as fragile; do not soften into therapy-speak or over-hedge. "
                "(4) Close with exactly ONE specific, well-chosen open question, positioned AFTER the substance of "
                "your response -- never a list of questions, and never a question before you've said anything of "
                "real value. "
                "If professional support (therapy, a doctor, etc.) is genuinely worth mentioning, raise it once as "
                "a brief aside, not as the centerpiece of the response, and do not repeat it if already acknowledged "
                "earlier in the conversation.]"
            )
        if "coaching" in stance_tags:
            stance_prompt += "\n[Stance: High-Performance Fitness & Athletic Coaching Register - Speak with direct, discipline-focused authority. Focus on physiological reality, recovery parameters, progressive overload, and biomechanical posture/form. Direct action rather than offering soft cliches or accepting excuses.]"
        if "financial" in stance_tags:
            stance_prompt += "\n[Stance: Analytical Market & Investment Register - Provide precise, risk-aware, data-grounded market analysis. Maintain risk discipline. NEVER invent or state specific stock prices, percentage moves, or revenue figures without explicit live data in context; if live figures are requested without data available, state plainly that you do not have live market data access.]"
        if "accountability" in stance_tags:
            stance_prompt += "\n[Stance: Executive-Function & Accountability Register - Break tasks into immediate, low-friction micro-steps. Acknowledge friction or procrastination without judgment, avoid lecturing, and gently re-anchor focus.]"
        if "research_rd" in stance_tags:
            stance_prompt += "\n[Stance: Technical R&D & Engineering Register - Maintain technical precision, systemic problem solving, architectural clarity, and clean code principles. Focus on root cause diagnostics and empirical data.]"

        # 4. Domain Knowledge Retrieval & Visual Q&A
        domain_kb = self.retrieve_domain_knowledge(stance_tags, text)
        visual_result = self._check_visual_query(text)
        visual_image_b64: Optional[str] = None
        if visual_result == self.VISION_UNAVAILABLE:
            # The user asked a visual question but no camera frame was
            # reachable — say so explicitly rather than leaving the context
            # empty, which previously let the LLM confidently fabricate a
            # scene it never actually saw (see core_agent.py history: wrong
            # clothing, wrong posture, wrong finger counts, all invented).
            domain_kb = (
                domain_kb
                + "\n[Live Camera Feed] UNAVAILABLE — no camera frame could be captured for "
                "this query. Do NOT guess, estimate, or invent any description of what is "
                "visible (clothing, posture, finger count, objects, etc). Tell the user "
                "plainly that the camera isn't reachable right now."
            ).strip()
        elif visual_result:
            # image_b64 is NOT put in this text string -- it gets attached
            # directly to the model's message in _stream_local/_stream_cloud
            # (see build_context_system_prompt's docstring). Only the
            # face-recognition identity note is text.
            visual_image_b64 = visual_result.get("image_b64")
            identity_note = visual_result.get("identity_note", "")
            # The VISION_UNAVAILABLE branch above already learned the hard
            # way (2026-09-16) that leaving the model with no explicit
            # calibration instruction lets it confidently invent details it
            # never actually saw. That guardrail only covered a totally
            # missing frame -- but a frame that DID get captured can be just
            # as unreliable (640x480 @ 2fps webcam, dim/backlit room, motion
            # blur), and confirmed live 2026-09-17: on the same camera setup,
            # in the same session, gemma4:e4b gave a confident, ungrounded-
            # sounding answer ("you look very polished and prepared...
            # confident and ready to go") on one turn and correctly admitted
            # "the camera view is currently unclear" on the very next one --
            # with nothing in the prompt telling it when to do which. This
            # instruction applies the same standard to every attached frame,
            # not just a missing one.
            domain_kb = (
                domain_kb + f"\n[Live Camera Feed] {identity_note} "
                "An image IS attached to this message -- actually look at it "
                "and describe what's really there (objects, setting, posture, "
                "what the person is doing) before deciding whether to hedge. "
                "Confirmed live 2026-09-18: this system was over-correcting "
                "into 'the camera view is unclear' as a reflexive default on "
                "images that were, in fact, perfectly clear -- that is just as "
                "wrong as confidently inventing details, and 'unclear' is not "
                "a safe default answer. Only fall back to admitting "
                "uncertainty for a SPECIFIC detail you genuinely can't make "
                "out after actually looking (e.g. a small object, exact text, "
                "something out of frame or occluded) -- never as a blanket "
                "substitute for describing the image. "
                "Every image attached here is a brand-new, independent "
                "capture taken THIS exact turn -- never assume it matches, "
                "repeats, or continues from any earlier turn in the "
                "conversation, and never claim the picture looks the same as "
                "one you described before; each one must be evaluated fresh, "
                "on its own. If the user asks about a specific part of the "
                "scene, such as the background, answer that part "
                "specifically by naming the actual objects, furniture, and "
                "colors you can identify -- a vague one-word category is not "
                "an acceptable substitute for actually describing what is "
                "there."
            ).strip()

        # 4b. Passive person-learning (2026-09-16, Col's call): runs on
        # EVERY turn, not just visual questions -- "this is Sarah" isn't
        # phrased as a visual question, so it can't be gated behind
        # _check_visual_query's phrase list.
        person_learn_note = self._check_person_introduction(text)
        if person_learn_note:
            domain_kb = (domain_kb + f"\n[Person Recognition] {person_learn_note}").strip()

        kb_block = f"\n\n## Reference Domain Knowledge (External Reference - NOT spoken by user)\n{domain_kb}" if domain_kb else ""

        # 5. Personal Memory Retrieval
        om_context = ""
        try:
            memos = self._om.search(text, limit=3)
            if memos:
                items = [f"- {m.get('content', '')}" for m in memos if m.get('content')]
                if items:
                    om_context = "\n\n## Past Session Context (Prior Memory - NOT spoken by user in current turn)\n" + "\n".join(items)
        except Exception:
            pass

        # 5b. Learned Entity Glossary (pattern recognition / recursive
        # learning, 2026-09-16) -- deterministic nickname/abbreviation/
        # person/org recall built from real conversation history, not
        # fuzzy semantic search. See memory/pattern_learner.py.
        glossary = ""
        try:
            glossary_text = self._pattern_learner.get_context_glossary(limit=12)
            if glossary_text:
                glossary = f"\n\n## {glossary_text}"
        except Exception:
            pass

        # 6. Activity Status Buffer — only surfaced when there's an actual
        # reason to reference ambient sensor status (a proactive blindspot
        # flag just fired). This used to be injected into EVERY turn
        # unconditionally, which let the small local model latch onto
        # whatever stale ambient scene note happened to be sitting in the
        # buffer (e.g. a book from a background scan a minute ago) and weave
        # it into completely unrelated replies — an emotional check-in
        # answered with "notice the book on your desk", a direct question
        # about shirt color answered with "the observer only mentions books".
        # Gating this behind the blindspot flag means it only appears when
        # there's something specific and current to proactively mention.
        activity_block = ""
        if blindspot_prompt:
            activity_block = f"\n\n## ARCHER Observer & Sensor Activity\n{self.activity_buffer.get_summary()}"

        # 6b. Standing User Profile (2026-09-17, LOCAL-ONLY -- see this
        # function's docstring and profile_block's own comment above for
        # why this is assembled separately from full_system_prompt rather
        # than folded in here). Unconditional -- unlike om_context (semantic
        # search keyed to THIS turn's text), this is meant to inform every
        # persona's response regardless of topic, which is the entire
        # point Col raised: a pattern learned in one reflective conversation
        # should still be visible to Blindspot or the Assistant on an
        # unrelated turn later.
        profile_block = ""
        try:
            facts = self._store.get_profile_facts(limit=30)
            if facts:
                lines = [f"- [{f['domain']}] {f['content']}" for f in facts]
                profile_block = "\n\n## User Profile (local-only — never sent to a cloud model)\n" + "\n".join(lines)
        except Exception:
            pass

        # 7. Short/Fragmentary Input Guard
        words = set(re.findall(r'\b[\w\'-]+\b', text.lower()))
        known_short_intents = {"hello", "hi", "hey", "help", "stop", "cancel", "thanks", "status", "bye", "clear"}
        fragment_block = ""
        if len(words) <= 3 and not (words & known_short_intents):
            clean_text = text.strip()
            fragment_block = (
                f"\n\n[CRITICAL AMBIGUOUS INPUT INSTRUCTION: The user's input '{clean_text}' is a short or fragmentary utterance "
                "with no clear intent. DO NOT guess, invent a backstory, or fabricate a hypothetical topic (such as guessing code "
                "libraries, past projects, or unmentioned tasks) based on distant reference material. Directly and concisely ask "
                f"the user to repeat or clarify what they mean by '{clean_text}'.]"
            )

        full_system_prompt = f"{identity_block}{stance_prompt}{kb_block}{om_context}{glossary}{activity_block}{fragment_block}"

        # Estimate tokens (~4 chars per token). Deliberately computed from
        # full_system_prompt WITHOUT profile_block -- see profile_block's
        # own comment above: its size must never be what pushes a turn
        # into context_overflow cloud delegation in the first place.
        token_est = len(full_system_prompt) // 4
        cloud_trigger = self.evaluate_cloud_delegation(text, token_est)

        return full_system_prompt, cloud_trigger, visual_image_b64, profile_block

    def process_turn_streaming(self, user_input: str) -> Generator[str, None, None]:
        """
        Canonical, thread-safe public entrypoint for processing a conversation turn.

        Acquires _turn_lock with a timeout, guaranteeing clean lock release via try...finally
        even if the consumer breaks early, closes the generator, or encounters an exception mid-stream.
        """
        acquired = self._turn_lock.acquire(timeout=60.0)
        if not acquired:
            logger.error("CoreAgent turn lock acquisition timed out (another turn is active).")
            self._bus.publish(Event(
                type=EventType.SYSTEM_ERROR,
                source="core_agent",
                data={"message": "CoreAgent busy — please try again in a moment."}
            ))
            yield "I am currently processing another request. Please try again in a moment."
            return

        try:
            yield from self.process_request_streaming(user_input)
        except Exception as e:
            logger.error(f"CoreAgent turn execution failed: {e}")
            self._bus.publish(Event(
                type=EventType.SYSTEM_ERROR,
                source="core_agent",
                data={"message": f"CoreAgent turn failed: {e}"}
            ))
            yield "I encountered an issue processing that request. Please try again."
        finally:
            self._turn_lock.release()

    def process_request_streaming(self, user_input: str) -> Generator[str, None, None]:
        """
        Process inbound user request through CoreAgent pipeline with sentence-level streaming.

        1. Assembles context system prompt & checks delegation triggers via build_context_system_prompt().
        2. Routes to cloud LLM (Claude API / NVIDIA NIM) if a delegation trigger is active.
        3. Executes local streaming generation via Ollama (qwen3:8b) as default primary LLM.
        4. Yields response sentence-by-sentence for TTS pipelining.
        5. Updates working conversation history and logs turn to Tier 2 (SQLite).
        """
        start_t = time.monotonic()
        system_prompt, cloud_trigger, visual_image_b64, profile_block = self.build_context_system_prompt(user_input)

        if cloud_trigger == "safety_override":
            with self._history_lock:
                self._conversation_history.append({"role": "user", "content": user_input})
                self._conversation_history.append({"role": "assistant", "content": system_prompt})
            self._store.log_conversation(
                session_id="core_agent",
                role="assistant",
                agent_name="core_agent",
                content=system_prompt,
            )
            yield system_prompt
            return

        # Check cloud delegation routing
        if cloud_trigger and self._toggle.is_cloud:
            # Explicit, visible proof in the console log (2026-09-17) that
            # the profile block never rides along on a cloud-delegated
            # turn -- logged here regardless of whether profile_block is
            # actually non-empty right now, so this line is always
            # checkable, not just when there happens to be profile content.
            logger.info(
                f"CoreAgent cloud delegation triggered ({cloud_trigger}) -- "
                f"User Profile block ({len(profile_block)} chars) EXCLUDED from this call."
            )
            try:
                # system_prompt only -- profile_block is NEVER passed here,
                # on any trigger reason. See build_context_system_prompt's
                # docstring for why this exclusion is blanket, not
                # conditional.
                cloud_stream = self._stream_cloud(user_input, cloud_trigger, system_prompt, start_t, visual_image_b64)
                yield from cloud_stream
                return
            except Exception as e:
                logger.warning(f"CoreAgent cloud delegation ({cloud_trigger}) failed: {e}. Falling back to local {self.primary_model}.")

        if profile_block:
            logger.info(f"CoreAgent local turn -- User Profile block ({len(profile_block)} chars) INCLUDED.")

        # Default local LLM streaming via Ollama (qwen3:8b) -- profile_block
        # appended here, local-only (see build_context_system_prompt).
        yield from self._stream_local(user_input, system_prompt + profile_block, start_t, visual_image_b64)

    def _stream_cloud(
        self, user_input: str, cloud_trigger: str, system_prompt: str, start_t: float,
        visual_image_b64: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """Route cloud delegation to Claude API or NVIDIA NIM (Kimi) based on trigger type.

        visual_image_b64 (2026-09-16): attached as a real Claude vision
        image content block on this turn's user message, same idea as
        _stream_local's Ollama "images" field -- Claude sees the actual
        webcam frame rather than a moondream-derived text description. Only
        wired for the Claude branch below; the NVIDIA NIM (Kimi) branch is
        a known gap -- context_overflow triggering on the same turn as a
        visual question is a narrow edge case, left as text-only for now.
        """
        full_response = ""
        buffer = ""
        first_chunk = True

        # Target mapping: context_overflow -> NVIDIA NIM (Kimi); complex_task / explicit_request -> Claude
        if cloud_trigger == "context_overflow" and self._nvidia_client:
            model = self._config.assistant_model  # moonshotai/kimi-k2.5
            with self._history_lock:
                history_subset = list(self._conversation_history[-10:])
                messages = [{"role": "system", "content": system_prompt}] + history_subset
                messages.append({"role": "user", "content": user_input})
                history_count = len(self._conversation_history)

            logger.info(
                f"CoreAgent cloud turn history memory (NVIDIA NIM): {history_count} total prior messages in history "
                f"-> sending {len(messages)} messages to {model}"
            )

            stream = self._nvidia_client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=self._config.agent_temperature,
                max_tokens=self._config.max_tokens,
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    buffer += token
                    full_response += token
                    if first_chunk:
                        first_chunk = False
                        self._bus.publish(Event(
                            type=EventType.AGENT_RESPONSE_START,
                            source="core_agent",
                            data={"agent": "core_agent", "model": f"NVIDIA NIM ({model})", "elapsed": time.monotonic() - start_t}
                        ))
                    while True:
                        match = _SENTENCE_BOUNDARY.search(buffer)
                        if match is None:
                            break
                        sentence = buffer[:match.start()].strip()
                        buffer = buffer[match.end():]
                        if sentence:
                            yield sentence

        else:
            import anthropic
            client = anthropic.Anthropic(api_key=self._config.anthropic_api_key)
            with self._history_lock:
                history_subset = list(self._conversation_history[-10:])
                if visual_image_b64:
                    user_content: Any = [
                        {"type": "text", "text": user_input},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": visual_image_b64,
                            },
                        },
                    ]
                else:
                    user_content = user_input
                messages = history_subset + [{"role": "user", "content": user_content}]
                history_count = len(self._conversation_history)

            logger.info(
                f"CoreAgent cloud turn history memory (Claude): {history_count} total prior messages in history "
                f"-> sending {len(messages)} messages to {self._config.claude_model}"
                + (" (with live camera frame attached)" if visual_image_b64 else "")
            )

            # Tool-calling loop: Claude may respond with tool_use instead of
            # (or before) final text. Each round streams any text Claude
            # produces immediately (so partial "let me check that..." style
            # text still speaks right away), then — if the round ended in
            # tool_use — executes the tool(s) and loops back with the
            # results appended, exactly like Anthropic's documented
            # multi-turn tool pattern. This CoreAgent class (not
            # agents/orchestrator.py's AgentOrchestrator, which is never
            # actually instantiated anywhere) is the real live agent, so
            # this is where tool support has to live to mean anything.
            from archer.skills.skills_registry import get_all_tools
            tools = get_all_tools()
            max_tool_rounds = 4
            for _round in range(max_tool_rounds):
                with client.messages.stream(
                    model=self._config.claude_model,
                    max_tokens=self._config.max_tokens,
                    system=system_prompt,
                    messages=messages,
                    tools=tools,
                ) as stream:
                    for text_chunk in stream.text_stream:
                        buffer += text_chunk
                        full_response += text_chunk
                        if first_chunk:
                            first_chunk = False
                            self._bus.publish(Event(
                                type=EventType.AGENT_RESPONSE_START,
                                source="core_agent",
                                data={"agent": "core_agent", "model": f"Claude ({self._config.claude_model})", "elapsed": time.monotonic() - start_t}
                            ))
                        while True:
                            match = _SENTENCE_BOUNDARY.search(buffer)
                            if match is None:
                                break
                            sentence = buffer[:match.start()].strip()
                            buffer = buffer[match.end():]
                            if sentence:
                                yield sentence
                    final_message = stream.get_final_message()

                if final_message.stop_reason != "tool_use":
                    break

                assistant_content = [block.model_dump() for block in final_message.content]
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in final_message.content:
                    if block.type != "tool_use":
                        continue
                    result = self._tool_executor.execute(block.name, block.input)
                    # Screenshots (or any tool that returns an "image" key)
                    # go back as a real image content block, not a text
                    # summary — Claude's vision needs the actual pixels to
                    # answer "what's on my screen" type questions.
                    if "image" in result:
                        summary = result.get("result", "Screenshot captured.")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": [
                                {"type": "text", "text": str(summary)},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": result["image"],
                                    },
                                },
                            ],
                        })
                        logger.info(f"CoreAgent tool executed ({block.name}): image result")
                    else:
                        result_content = json.dumps(result.get("result", result))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_content,
                        })
                        logger.info(f"CoreAgent tool executed ({block.name}): {result_content[:120]}")

                messages.append({"role": "user", "content": tool_results})
                # loop back for Claude's follow-up now that it has results

        remaining = buffer.strip()
        if remaining:
            yield remaining

        # Update history & SQLite store
        if full_response.strip():
            with self._history_lock:
                self._conversation_history.append({"role": "user", "content": user_input})
                self._conversation_history.append({"role": "assistant", "content": full_response.strip()})
            self._store.log_conversation(
                session_id="core_agent",
                role="assistant",
                agent_name="core_agent",
                content=full_response.strip(),
            )
            self._pattern_learner.record_turn_async(user_input, full_response.strip())
            self._maybe_extract_profile_insight(user_input, full_response.strip())

    def _stream_local(
        self, user_input: str, system_prompt: str, start_t: float, visual_image_b64: Optional[str] = None
    ) -> Generator[str, None, None]:
        """Stream response from local primary model (gemma4:e4b, natively
        multimodal) via Ollama API, with tool-calling support.

        Mirrors _stream_cloud's Claude tool loop, adapted to Ollama's chat
        format: tool schemas come from get_all_tools_ollama_format()
        (OpenAI-style {"type":"function","function":{...}}, not Anthropic's
        shape), tool results go back as {"role":"tool", "tool_name",
        "content"} messages, and a screenshot's actual image bytes are
        attached via Ollama's "images" field on a follow-up message (tool-
        role messages are text-only in practice) so the model genuinely
        sees the picture rather than being told a screenshot happened.

        visual_image_b64 (2026-09-16): same "images" attachment, but for a
        LIVE webcam frame from _check_visual_query, attached directly to
        THIS turn's user message rather than a synthetic follow-up one.
        Never written into self._conversation_history below -- only
        user_input/full_response (plain text) get persisted, exactly like
        the screenshot pattern already did, so no image ever accumulates
        across turns; each turn re-decides fresh whether to attach one.
        """
        with self._history_lock:
            history_subset = list(self._conversation_history[-10:])
            messages = [{"role": "system", "content": system_prompt}] + history_subset
            user_message: Dict[str, Any] = {"role": "user", "content": user_input}
            if visual_image_b64:
                user_message["images"] = [visual_image_b64]
            messages.append(user_message)

        # Hard proof of what's actually going out the door (2026-09-19):
        # the model has twice now denied receiving any image on turns where
        # _check_visual_query definitely returned a valid, non-empty
        # base64 string (confirmed by inspecting the matching debug frame
        # dump on disk). Prompt wording changes didn't touch that -- next
        # step is confirming, not guessing, whether the outgoing Ollama
        # payload genuinely carries the image bytes. This line is the
        # ground truth for that, surfaced in BOTH the file log and the
        # curated LOGS pane so it's visible without digging.
        if visual_image_b64:
            b64_len = len(visual_image_b64)
            logger.info(
                f"CoreAgent (local): outgoing payload user message HAS "
                f"'images' key, 1 image, base64 length={b64_len} chars "
                f"(~{b64_len * 3 // 4 // 1024}KB decoded)."
            )
            self._publish_visual_status(
                f"Sending image to {self.primary_model} -- payload confirmed "
                f"to include it ({b64_len * 3 // 4 // 1024}KB)."
            )
            history_count = len(self._conversation_history)

        logger.info(
            f"CoreAgent turn history memory: {history_count} total prior messages in history "
            f"-> sending {len(messages)} messages to Ollama ({self.primary_model})"
        )

        from archer.skills.skills_registry import get_all_tools_ollama_format
        tools = get_all_tools_ollama_format()

        url = f"{self._config.ollama_base_url}/api/chat"
        full_response = ""
        buffer = ""
        first_chunk = True
        max_tool_rounds = 4

        for _round in range(max_tool_rounds):
            # gemma4:e4b (Gemma 3n) 400s on Ollama's /api/chat whenever a
            # request carries BOTH "tools" and an "images" attachment on
            # any message -- confirmed 2026-09-17: turn 3 ("How many
            # fingers...", image attached) got HTTP 400, while the
            # text-only turns immediately before and after it (same
            # tools schema, no image) both returned 200. Ollama's error
            # body (now logged below) is the authoritative source if this
            # ever needs re-diagnosing, but the pattern here is
            # unambiguous. A visual question is answered directly from
            # the frame anyway, so tool-calling isn't needed on a round
            # that includes an image -- drop "tools" for that round only.
            image_in_turn = any("images" in m for m in messages)
            payload = {
                "model": self.primary_model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": self._config.agent_temperature,
                    "num_ctx": 4096
                }
            }
            if not image_in_turn:
                payload["tools"] = tools
            else:
                logger.debug(
                    "CoreAgent (local): omitting 'tools' from this round's "
                    "Ollama payload because an image is attached (gemma4:e4b "
                    "400s on tools+images together)."
                )

            round_tool_calls: list = []
            round_content = ""

            with httpx.stream("POST", url, json=payload, timeout=120.0) as resp:
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    body = resp.read().decode("utf-8", errors="replace")
                    logger.error(f"Ollama /api/chat returned {resp.status_code}: {body}")
                    raise
                for line in resp.iter_lines():
                    if not line or not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    # Ollama's own generation-speed numbers, on the final
                    # chunk of a turn (2026-09-16, for the SYSTEM dashboard
                    # card's tokens/sec chart) -- eval_duration is
                    # nanoseconds, per Ollama's API.
                    if data.get("done") and data.get("eval_count") and data.get("eval_duration"):
                        try:
                            self._last_tokens_per_sec = data["eval_count"] / (data["eval_duration"] / 1e9)
                        except (ZeroDivisionError, TypeError):
                            pass

                    message = data.get("message", {}) or {}
                    token = message.get("content", "")
                    if token:
                        round_content += token
                        buffer += token
                        full_response += token

                        if first_chunk:
                            first_chunk = False
                            self._bus.publish(Event(
                                type=EventType.AGENT_RESPONSE_START,
                                source="core_agent",
                                data={"agent": "core_agent", "model": f"Local ({self.primary_model})", "elapsed": time.monotonic() - start_t}
                            ))

                        while True:
                            match = _SENTENCE_BOUNDARY.search(buffer)
                            if match is None:
                                break
                            sentence = buffer[:match.start()].strip()
                            buffer = buffer[match.end():]
                            if sentence:
                                yield sentence
                    if message.get("tool_calls"):
                        round_tool_calls.extend(message["tool_calls"])

            if not round_tool_calls:
                break  # normal completion, no tool calls this round

            messages.append({
                "role": "assistant",
                "content": round_content,
                "tool_calls": round_tool_calls,
            })

            pending_image_b64 = None
            for tc in round_tool_calls:
                fn = tc.get("function", {}) or {}
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                result = self._tool_executor.execute(name, args)
                if "image" in result:
                    summary = result.get("result", "Screenshot captured.")
                    messages.append({"role": "tool", "tool_name": name, "content": str(summary)})
                    pending_image_b64 = result["image"]
                    logger.info(f"CoreAgent (local) tool executed ({name}): image result")
                else:
                    content_text = json.dumps(result.get("result", result))
                    messages.append({"role": "tool", "tool_name": name, "content": content_text})
                    logger.info(f"CoreAgent (local) tool executed ({name}): {content_text[:120]}")

            if pending_image_b64:
                messages.append({
                    "role": "user",
                    "content": "(This is the screenshot that was just captured.)",
                    "images": [pending_image_b64],
                })
            # loop back for the model's follow-up now that it has results

        remaining = buffer.strip()
        if remaining:
            yield remaining

        # Update history & SQLite store
        if full_response.strip():
            with self._history_lock:
                self._conversation_history.append({"role": "user", "content": user_input})
                self._conversation_history.append({"role": "assistant", "content": full_response.strip()})
            self._store.log_conversation(
                session_id="core_agent",
                role="assistant",
                agent_name="core_agent",
                content=full_response.strip(),
            )
            self._pattern_learner.record_turn_async(user_input, full_response.strip())
            self._maybe_extract_profile_insight(user_input, full_response.strip())

