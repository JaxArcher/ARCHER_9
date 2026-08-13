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
        "mental health", "burnout", "insomnia", "grief", "venting"
    },
    "financial": {
        "stock", "stocks", "portfolio", "market", "shares", "dividend", "s&p",
        "holdings", "investing", "trading", "returns"
    },
    "accountability": {
        "procrastination", "adhd", "focus", "distraction", "routine", "clutter",
        "habit", "time blindness", "tasks"
    }
}


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
        
        self._history_lock = threading.Lock()
        self._conversation_history: List[Dict[str, str]] = []
        
        # Subscribe to observer events for activity buffer
        self._bus.subscribe(EventType.OBSERVATION_EVENT, self._on_observation)
        logger.info("CoreAgent (Single-Agent Architecture) initialized.")

    def _on_observation(self, event: Event) -> None:
        """Update rolling activity status buffer on significant events."""
        event_type = event.data.get("event_type", "observation")
        if event_type == "sedentary":
            mins = event.data.get("duration_minutes", 120)
            self.activity_buffer.update_status(f"Observer flagged sedentary behavior ({mins:.0f} min).")
        elif event_type == "sustained_emotion":
            emo = event.data.get("dominant_emotion", "distress")
            self.activity_buffer.update_status(f"Observer detected sustained {emo} emotional state.")
        elif event_type == "posture":
            self.activity_buffer.update_status("Observer flagged slouching posture.")

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
        """Score situational stance tags from input text."""
        words = set(re.findall(r'\b[\w\'-]+\b', text.lower()))
        scores: Dict[str, float] = {}
        for stance, kws in _STANCE_KEYWORDS.items():
            count = sum(1 for kw in kws if kw in words)
            if count > 0:
                scores[stance] = float(count)
        return scores

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

    def build_context_system_prompt(self, text: str) -> tuple[str, Optional[str]]:
        """
        Construct 7-step context assembly pipeline:
        1. Safety pre-check
        2. Core identity block
        3. Stance tag scoring
        4. Domain knowledge retrieval
        5. Personal memory retrieval (OpenMemory)
        6. Rolling activity status buffer
        7. System prompt string + cloud trigger flag
        """
        safety_response = self.check_safety_override(text)
        if safety_response:
            return safety_response, "safety_override"

        # 2. Core Identity Block
        identity_block = (
            "You are ARCHER — Advanced Responsive Computing Helper & Executive Resource.\n"
            "You are Colby's primary personal companion and assistant. You speak with directness, "
            "warm empathy, and intelligent clarity. Maintain a single unified identity at all times."
        )

        # 3. Stance Tag Scoring
        stance_tags = self.calculate_stance_tags(text)
        stance_prompt = ""
        if "therapeutic" in stance_tags:
            stance_prompt += "\n[Stance: Therapeutic & Reflective Register - Listen attentively and validate feelings.]"
        if "coaching" in stance_tags:
            stance_prompt += "\n[Stance: Direct Fitness Register - Be action-oriented and encouraging.]"
        if "financial" in stance_tags:
            stance_prompt += "\n[Stance: Analytical Financial Register - Focus on precision and data.]"

        # 4. Domain Knowledge Retrieval
        domain_kb = self.retrieve_domain_knowledge(stance_tags, text)
        kb_block = f"\n\n## Domain Knowledge Context\n{domain_kb}" if domain_kb else ""

        # 5. Personal Memory Retrieval
        om_context = ""
        try:
            memos = self._om.search(text, limit=3)
            if memos:
                items = [f"- {m.get('content', '')}" for m in memos if m.get('content')]
                if items:
                    om_context = "\n\n## Personal Memory Context\n" + "\n".join(items)
        except Exception:
            pass

        # 6. Activity Status Buffer
        activity_block = f"\n\n## ARCHER Activity Status\n{self.activity_buffer.get_summary()}"

        full_system_prompt = f"{identity_block}{stance_prompt}{kb_block}{om_context}{activity_block}"
        
        # Estimate tokens (~4 chars per token)
        token_est = len(full_system_prompt) // 4
        cloud_trigger = self.evaluate_cloud_delegation(text, token_est)

        return full_system_prompt, cloud_trigger
