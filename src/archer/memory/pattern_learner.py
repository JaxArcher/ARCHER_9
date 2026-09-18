"""
ARCHER Pattern Recognition / Recursive Learning (2026-09-16).

Implements the feature Col described from the reference video almost
verbatim: "The system actively learns from transcriptions of your
conversations. It identifies recurring themes, such as verbal fillers, or
triggers for frustration when the AI lacks context. [...] maintains a count
of what it has learned, including specific entities like people,
organizations, nicknames, and abbreviations. It uses this structured data
to self-correct and improve its contextual understanding over time."

Design notes (why it looks the way it does):

- Runs in real time, every conversation turn (Col's explicit choice over a
  cheaper nightly-batch alternative) -- but AFTER the turn's response has
  already been fully generated and handed to the user, in a background
  thread. This keeps it "real time" (each turn's data is used immediately,
  not deferred to a nightly job) without adding latency to the spoken
  response, and without competing with the live conversation model for
  GPU/VRAM mid-turn.

- Always uses the LOCAL model (core_primary_model / gemma4:e4b via Ollama),
  never Claude, regardless of which model handled the conversation itself.
  This is a per-turn background job -- routing it through the cloud API on
  every single turn would multiply API cost for no real quality need here
  (entity/pattern extraction is a much easier task than the conversation
  itself), and it keeps this feature working even in local-only mode.

- Storage is a real SQLite table (learned_entities / conversation_patterns
  in sqlite_store.py), not just a vector-search memory, precisely because
  "self-correct and improve contextual understanding" implies deterministic
  recall (resolve "Mo" -> "Maurice" reliably) rather than fuzzy semantic
  search. get_context_glossary() below is what makes that recall actually
  reach the LLM: it's injected as a compact block into
  CoreAgent.build_context_system_prompt(), the same way domain_kb/om_context
  already are.

- Recurring-pattern findings (verbal fillers, frustration-from-missing-
  context) are stored for the Memory tab to display, but are NOT injected
  into the live system prompt -- CoreAgent's own history already documents
  why low-value ambient notes stuffed into every turn cause the small local
  model to latch onto irrelevant context (see the activity_block comment in
  build_context_system_prompt). A running "you tend to say 'like' a lot"
  note has no business showing up in an unrelated answer.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Optional

import httpx
from loguru import logger

from archer.config import get_config
from archer.memory.sqlite_store import get_sqlite_store, SQLiteStore


_VALID_ENTITY_TYPES = {"person", "organization", "nickname", "abbreviation"}
_VALID_PATTERN_TYPES = {"verbal_filler", "frustration_trigger", "other"}

# Turns too short/trivial to bother extracting from -- pure acks, filler
# replies, etc. Saves a model call on every "okay" / "thanks" / "stop".
_SKIP_USER_TEXTS = {
    "yes", "no", "okay", "ok", "thanks", "thank you", "stop", "cancel",
    "hi", "hello", "hey", "bye", "goodbye", "sure", "yep", "nope",
}

_EXTRACTION_PROMPT = """You are a silent background analysis pass over one turn of a spoken conversation. You do NOT respond to the user -- you only extract structured data about it.

Return ONLY valid JSON (no markdown fences, no commentary) matching exactly this shape:
{{
  "entities": [
    {{"name": "canonical name", "type": "person|organization|nickname|abbreviation", "resolves_to": "canonical name this nickname/abbreviation refers to, or null", "definition": "one short clause on who/what this is, or null"}}
  ],
  "patterns": [
    {{"type": "verbal_filler|frustration_trigger|other", "label": "short reusable label, e.g. \\"says \\'like\\' often\\" or \\"frustrated when ARCHER lacks context\\"", "example": "the specific phrase/moment from this turn"}}
  ]
}}

Rules:
- Only extract entities/patterns actually present in THIS turn. If none, return empty lists.
- "entities": named people, organizations, nicknames, or abbreviations mentioned BY THE USER. Do not invent ones that aren't there. A first name alone is still a "person".
- "patterns": only flag a verbal_filler if it's a distinctive repeated speech tic in the user's own words (not every "um"). Only flag frustration_trigger when the user's tone or words show frustration, especially frustration caused by ARCHER lacking context or misunderstanding.
- Keep "label" generic/reusable (so repeats of the same pattern match the same label across turns), and "example" specific to this turn.

Conversation turn:
User: {user_text}
Assistant: {assistant_text}

JSON:"""


class PatternLearner:
    """Real-time per-turn entity/pattern extraction (see module docstring)."""

    def __init__(self, store: Optional[SQLiteStore] = None) -> None:
        self._config = get_config()
        self._store = store or get_sqlite_store()
        self._model = self._config.core_primary_model
        self._url = f"{self._config.ollama_base_url}/api/generate"

    def record_turn_async(self, user_text: str, assistant_text: str) -> None:
        """Fire-and-forget: schedule extraction for one completed turn on a
        background thread. Never raises, never blocks the caller."""
        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()
        if not user_text:
            return
        if user_text.lower().strip(".! ") in _SKIP_USER_TEXTS and len(user_text) < 20:
            return
        thread = threading.Thread(
            target=self._extract_and_store,
            args=(user_text, assistant_text),
            daemon=True,
            name="pattern-learner-extract",
        )
        thread.start()

    def _extract_and_store(self, user_text: str, assistant_text: str) -> None:
        try:
            result = self._run_extraction(user_text, assistant_text)
        except Exception as e:
            logger.debug(f"PatternLearner extraction failed (non-fatal): {e}")
            return

        for entity in result.get("entities", []):
            try:
                name = (entity.get("name") or "").strip()
                etype = (entity.get("type") or "").strip().lower()
                if not name or etype not in _VALID_ENTITY_TYPES:
                    continue
                self._store.upsert_learned_entity(
                    canonical_name=name,
                    entity_type=etype,
                    resolves_to=(entity.get("resolves_to") or None),
                    definition=(entity.get("definition") or None),
                )
            except Exception as e:
                logger.debug(f"PatternLearner: failed to store entity {entity!r}: {e}")

        for pattern in result.get("patterns", []):
            try:
                ptype = (pattern.get("type") or "").strip().lower()
                label = (pattern.get("label") or "").strip()
                if not label or ptype not in _VALID_PATTERN_TYPES:
                    continue
                self._store.upsert_conversation_pattern(
                    pattern_type=ptype,
                    label=label,
                    example=(pattern.get("example") or None),
                )
            except Exception as e:
                logger.debug(f"PatternLearner: failed to store pattern {pattern!r}: {e}")

    def _run_extraction(self, user_text: str, assistant_text: str) -> dict[str, Any]:
        prompt = _EXTRACTION_PROMPT.format(
            user_text=user_text[:2000],
            assistant_text=assistant_text[:1000],
        )
        resp = httpx.post(
            self._url,
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            # Generous but bounded -- this runs after the user already has
            # their response, so it's not user-facing latency, just VRAM/
            # queue time behind it if the same Ollama instance is briefly
            # loaded for something else.
            timeout=45.0,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Best-effort JSON parse, tolerant of markdown fences and stray
        prose around the object (small local models don't always follow
        'JSON only' perfectly) -- same tolerant-parsing shape used by
        observer/analyzers.py's SceneAnalyzer for the same reason."""
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
        # Last resort: grab the outermost {...} block.
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return {"entities": [], "patterns": []}

    def get_context_glossary(self, limit: int = 12) -> str:
        """Compact 'known entities' block for system-prompt injection --
        deterministic nickname/abbreviation resolution, not fuzzy search.
        Returns "" when nothing has been learned yet."""
        try:
            entities = self._store.get_learned_entities(limit=limit)
        except Exception as e:
            logger.debug(f"PatternLearner: glossary fetch failed: {e}")
            return ""
        if not entities:
            return ""
        lines = []
        for e in entities:
            piece = f"- {e['canonical_name']} ({e['entity_type']}"
            if e.get("resolves_to"):
                piece += f" -> {e['resolves_to']}"
            piece += f", mentioned {e['mention_count']}x)"
            if e.get("definition"):
                piece += f": {e['definition']}"
            lines.append(piece)
        return "Known entities learned from conversation:\n" + "\n".join(lines)


_learner: PatternLearner | None = None


def get_pattern_learner() -> PatternLearner:
    global _learner
    if _learner is None:
        _learner = PatternLearner()
    return _learner
