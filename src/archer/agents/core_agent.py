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
        
        # Section 6.5 Benchmark Selected Primary Model: qwen3:8b
        # Reason: Chosen for 136+ tok/s speed, ~7.3GB VRAM headroom, and Unsloth LoRA viability on 16GB GPU.
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
        self._conversation_history: List[Dict[str, str]] = []
        
        # Subscribe to observer events for activity buffer
        self._bus.subscribe(EventType.OBSERVATION_EVENT, self._on_observation)
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

        # 2. Core Identity Block & Strict Attribution Rules
        identity_block = (
            "You are ARCHER — Advanced Responsive Computing Helper & Executive Resource.\n"
            "You are Colby's primary personal companion and assistant. You speak with directness, "
            "warm empathy, and intelligent clarity. Maintain a single unified identity at all times.\n\n"
            "CRITICAL ATTRIBUTION & OBSERVATION GUIDELINES:\n"
            "1. OBSERVER / SENSOR DATA: Ambient observations (e.g. posture alerts, emotional detection, sedentary tracking) "
            "are tentative sensor readings, NOT established facts or diagnoses. ALWAYS frame sensor findings as tentative, "
            "named observations or open questions (e.g. 'I noticed you seem a bit tense or slouched — how are you feeling?' "
            "or 'My sensors flagged a bit of stress, is that accurate?'). NEVER assert sensor readings as definitive psychological "
            "truth or absolute fact. Allow the user to confirm or reject them naturally.\n"
            "2. RETRIEVED KNOWLEDGE & PAST MEMORIES: Context provided under '## Reference Domain Knowledge' or "
            "'## Past Session Context' consists of external reference material or prior context from past interactions. "
            "NEVER claim, quote, or paraphrase retrieved reference material or past memory entries as if the user said them in the "
            "current turn. Only reference past context explicitly as prior context (e.g., 'In a past session, we discussed...' "
            "or 'Based on reference materials...'). The current user prompt is the ONLY source for what the user is saying right now.\n"
            "3. ACTIVE CAPABILITIES & CONVERSATIONAL BOUNDARIES: You are currently operating in a pure voice/text "
            "conversational mode. You do NOT have active local tool-execution capabilities (such as browser automation, "
            "taking screenshots, mouse/keyboard control, or file modifications) enabled in this turn. Describe yourself strictly "
            "as a conversational assistant, sounding board, and knowledge advisor. NEVER claim, fabricate, or pretend to perform "
            "system actions, Playwright browser control, window focus, or local file edits."
        )

        # 3. Stance Tag Scoring & Register Assembly
        stance_tags = self.calculate_stance_tags(text)
        stance_prompt = ""
        if "therapeutic" in stance_tags:
            stance_prompt += "\n[Stance: Therapeutic & Reflective Register - Listen attentively, validate feelings, and explore emotional dynamics without judgment.]"
        if "coaching" in stance_tags:
            stance_prompt += "\n[Stance: High-Performance Fitness & Athletic Coaching Register - Speak with direct, discipline-focused authority. Focus on physiological reality, recovery parameters, progressive overload, and biomechanical posture/form. Direct action rather than offering soft cliches or accepting excuses.]"
        if "financial" in stance_tags:
            stance_prompt += "\n[Stance: Analytical Market & Investment Register - Provide precise, risk-aware, data-grounded market analysis. Express figures in percentages and dollar amounts together, maintain risk discipline, and present options calmly without asserting certainty or making trade execution promises.]"
        if "accountability" in stance_tags:
            stance_prompt += "\n[Stance: Executive-Function & Accountability Register - Break tasks into immediate, low-friction micro-steps. Acknowledge friction or procrastination without judgment, avoid lecturing, and gently re-anchor focus.]"
        if "research_rd" in stance_tags:
            stance_prompt += "\n[Stance: Technical R&D & Engineering Register - Maintain technical precision, systemic problem solving, architectural clarity, and clean code principles. Focus on root cause diagnostics and empirical data.]"

        # 4. Domain Knowledge Retrieval
        domain_kb = self.retrieve_domain_knowledge(stance_tags, text)
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

        # 6. Activity Status Buffer
        activity_block = f"\n\n## ARCHER Observer & Sensor Activity\n{self.activity_buffer.get_summary()}"

        full_system_prompt = f"{identity_block}{stance_prompt}{kb_block}{om_context}{activity_block}"
        
        # Estimate tokens (~4 chars per token)
        token_est = len(full_system_prompt) // 4
        cloud_trigger = self.evaluate_cloud_delegation(text, token_est)

        return full_system_prompt, cloud_trigger

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
        system_prompt, cloud_trigger = self.build_context_system_prompt(user_input)

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
            try:
                cloud_stream = self._stream_cloud(user_input, cloud_trigger, system_prompt, start_t)
                yield from cloud_stream
                return
            except Exception as e:
                logger.warning(f"CoreAgent cloud delegation ({cloud_trigger}) failed: {e}. Falling back to local {self.primary_model}.")

        # Default local LLM streaming via Ollama (qwen3:8b)
        yield from self._stream_local(user_input, system_prompt, start_t)

    def _stream_cloud(
        self, user_input: str, cloud_trigger: str, system_prompt: str, start_t: float
    ) -> Generator[str, None, None]:
        """Route cloud delegation to Claude API or NVIDIA NIM (Kimi) based on trigger type."""
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
                messages = history_subset + [{"role": "user", "content": user_input}]
                history_count = len(self._conversation_history)

            logger.info(
                f"CoreAgent cloud turn history memory (Claude): {history_count} total prior messages in history "
                f"-> sending {len(messages)} messages to {self._config.claude_model}"
            )

            with client.messages.stream(
                model=self._config.claude_model,
                max_tokens=self._config.max_tokens,
                system=system_prompt,
                messages=messages,
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

    def _stream_local(self, user_input: str, system_prompt: str, start_t: float) -> Generator[str, None, None]:
        """Stream response from local primary model (qwen3:8b) via Ollama API."""
        with self._history_lock:
            history_subset = list(self._conversation_history[-10:])
            messages = [{"role": "system", "content": system_prompt}] + history_subset
            messages.append({"role": "user", "content": user_input})
            history_count = len(self._conversation_history)

        logger.info(
            f"CoreAgent turn history memory: {history_count} total prior messages in history "
            f"-> sending {len(messages)} messages to Ollama ({self.primary_model})"
        )

        url = f"{self._config.ollama_base_url}/api/chat"
        payload = {
            "model": self.primary_model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self._config.agent_temperature,
                "num_ctx": 4096
            }
        }

        full_response = ""
        buffer = ""
        first_chunk = True

        with httpx.stream("POST", url, json=payload, timeout=120.0) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if not token:
                        continue
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
                except Exception:
                    continue

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

