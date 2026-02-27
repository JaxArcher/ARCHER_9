"""
ARCHER Agent Orchestrator.

Routes every inbound event (voice utterance, observer event, scheduled trigger)
to the appropriate specialist agent. Agents do not call each other directly —
all inter-agent communication goes through the Orchestrator.

Phase 4: Supports Assistant, Trainer, Therapist, and Investment agents
as per final specs (Finance removed). Routing uses keyword + explicit triggers.
Logs conversations to local Tier 2 (SQLite) and Tier 3 (Markdown/OpenMemory).

The Assistant agent has access to PC Control tools (screen capture, browser
automation, keyboard/mouse) via Anthropic tool_use. Non-read-only tools
require verbal user confirmation before execution.

Uses Claude claude-sonnet-4-5-20250929 via Anthropic API (streaming) in cloud mode.
Uses Ollama in local mode.

Streaming architecture:
- process_request_streaming() yields complete sentences as they arrive
  from the LLM stream, enabling sentence-level TTS pipelining.
- process_request() is the blocking fallback (returns full response).
"""

from __future__ import annotations

import re
import time
import threading
import uuid
from collections.abc import Generator
from pathlib import Path

from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.core.toggle import get_toggle_service
from archer.memory.sqlite_store import get_sqlite_store
from archer.memory.redis_buffer import get_redis_buffer
from archer.memory.openmemory_store import get_openmemory_store
from archer.memory.markdown_logger import get_markdown_logger
from archer.memory.chromadb_store import get_chromadb_store


# Regex to split on sentence-ending punctuation followed by a space or end-of-string.
# Keeps the punctuation attached to the sentence.
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+')

# --- Keyword routing tables (from AGENTS.md) ---
_TRAINER_KEYWORDS = {
    "workout", "exercise", "gym", "run", "running", "lift", "lifting",
    "pushup", "squat", "plank", "cardio", "calories", "protein", "carbs",
    "fat", "macros", "nutrition", "diet", "meal", "food", "ate", "eating",
    "breakfast", "lunch", "dinner", "snack", "weight", "body fat", "bmi",
    "muscle", "gains", "hydration", "water intake", "dehydrated",
    "sedentary", "sitting too long", "stretch", "stretching", "steps",
    "fitbit", "fitness", "training",
}

_THERAPIST_KEYWORDS = {
    "stressed", "stress", "anxious", "anxiety", "depressed", "depression",
    "sad", "lonely", "overwhelmed", "therapy", "therapist", "counseling",
    "mental health", "feeling down", "feeling off", "not okay", "burned out",
    "burnout", "can't sleep", "insomnia", "nightmares", "relationship",
    "fight with", "argument with", "broke up", "breakup", "crying", "panic",
    "panic attack", "venting", "vent", "need to talk", "just need to talk",
}

_INVESTMENT_KEYWORDS = {
    "stock", "stocks", "portfolio", "market", "markets", "shares", "ticker",
    "dividend", "dividends", "s&p", "nasdaq", "dow", "etf", "index fund",
    "position", "positions", "holdings", "gains", "losses", "return",
    "returns", "bull", "bear", "rally", "trading", "sector",
    "market summary", "how's my portfolio",
}

# Crisis keywords ALWAYS route to Therapist regardless of other signals
_CRISIS_KEYWORDS = {
    "self-harm", "suicidal", "don't want to live", "end it all",
    "kill myself", "want to die",
}

# Explicit agent name references the user might say
_AGENT_NAME_MAP = {
    "trainer": "trainer",
    "therapist": "therapist",
    "assistant": "assistant",
    "investment": "investment",
    "coach": "trainer",
    "counselor": "therapist",
    "investor": "investment",
}

# Active agents and their SOUL.md files
_ACTIVE_AGENTS = ("assistant", "trainer", "therapist", "investment", "observer")


class AgentOrchestrator:
    """
    Routes requests to the appropriate agent and manages agent lifecycle.

    Phase 2: Supports Assistant, Trainer, Therapist with keyword + LLM
    routing, conversation logging, and memory retrieval.
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

        # NVIDIA NIM client
        self._nvidia_client = None
        if self._config.nvidia_api_key:
            try:
                from openai import OpenAI
                self._nvidia_client = OpenAI(
                    api_key=self._config.nvidia_api_key,
                    base_url=self._config.nvidia_base_url,
                )
            except ImportError:
                logger.warning("openai package not found — NVIDIA NIM disabled.")

        # Load SOUL.md for all active agents
        self._souls: dict[str, str] = {}
        for agent_name in _ACTIVE_AGENTS:
            self._souls[agent_name] = self._load_soul(agent_name)

        # Session ID (persists for the lifetime of this ARCHER run)
        self._session_id = str(uuid.uuid4())

        # Conversation history (Tier 1 — working memory, in-session)
        self._conversation_history: list[dict[str, str]] = []
        self._history_lock = threading.Lock()

        # Active agent tracking
        self._active_agent = "assistant"

        # Recent agent routing history (for context continuity)
        self._recent_agents: list[str] = []
        self._recent_lock = threading.Lock()

        # Register HALT handler
        self._bus.subscribe_halt(self._on_halt)

        # Cancelled flag
        self._cancelled = threading.Event()

        # Load previous session context on startup
        self._load_session_context()

        # Start Redis heartbeat thread (every 10 minutes)
        self._heartbeat_timer = threading.Timer(600, self._run_heartbeat)
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

        logger.info(f"Orchestrator initialized — session {self._session_id[:8]}")
        logger.info(f"Active agents: {', '.join(_ACTIVE_AGENTS)}")

    def _run_heartbeat(self) -> None:
        """Periodic background heartbeat to Redis."""
        try:
            with self._history_lock:
                state = {
                    "history": self._conversation_history[-10:],
                    "active_agent": self._active_agent,
                    "timestamp": time.time(),
                }
            self._redis.save_snapshot(self._session_id, state)
            # Reschedule
            self._heartbeat_timer = threading.Timer(600, self._run_heartbeat)
            self._heartbeat_timer.daemon = True
            self._heartbeat_timer.start()
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")

    def _load_soul(self, agent_name: str) -> str:
        """Load the SOUL.md file for an agent."""
        soul_path = Path(self._config.soul_dir) / agent_name / "SOUL.md"
        try:
            text = soul_path.read_text(encoding="utf-8")
            logger.info(f"Loaded SOUL.md for '{agent_name}' ({len(text)} chars)")
            return text
        except FileNotFoundError:
            logger.error(f"SOUL.md not found for agent '{agent_name}' at {soul_path}")
            return f"You are ARCHER's {agent_name} agent. Be helpful and efficient."

    def _load_session_context(self) -> None:
        """Load recent conversation context from previous sessions (Tier 2)."""
        try:
            # Get last 10 conversation entries from any previous session
            recent = self._store.get_recent_conversations(limit=10)
            if recent:
                logger.info(
                    f"Loaded {len(recent)} conversation entries from previous sessions"
                )
                # Don't add to working memory — just log that context is available.
                # The ChromaDB semantic search will surface relevant past context
                # when needed during agent calls.
        except Exception as e:
            logger.warning(f"Failed to load session context: {e}")

    # ------------------------------------------------------------------
    # Agent Routing
    # ------------------------------------------------------------------

    def _classify_agent(self, text: str) -> str:
        """
        Classify which agent should handle this request.

        Routing philosophy: The user explicitly specifies which agent they
        want to talk to. Default is always Assistant. Automatic keyword
        routing is a secondary fallback.

        Priority order:
        1. Crisis keywords → always Therapist (safety override)
        2. Explicit agent name in message ("ask the trainer", "talk to therapist")
        3. Context continuity (stay with current specialist agent in conversation)
        4. Keyword hints (secondary signal only when no specialist is active)
        5. Default: Assistant
        """
        lower = text.lower()

        # Step 1: Crisis keywords → always Therapist (safety override)
        for keyword in _CRISIS_KEYWORDS:
            if keyword in lower:
                logger.info(f"CRISIS keyword detected — routing to therapist")
                return "therapist"

        # Step 2: Explicit agent name reference (primary routing mechanism)
        # User says: "ask the trainer", "talk to the therapist", "switch to coach"
        for name, agent_id in _AGENT_NAME_MAP.items():
            patterns = [
                f"ask the {name}",
                f"tell the {name}",
                f"talk to the {name}",
                f"talk to {name}",
                f"switch to {name}",
                f"switch to the {name}",
                f"hey {name}",
            ]
            for pattern in patterns:
                if pattern in lower:
                    logger.info(f"Explicit agent reference '{name}' → {agent_id}")
                    return agent_id

        # Step 3: Context continuity — stay with the current non-assistant
        # agent if the user is in an active conversation with them.
        # The user explicitly started the conversation by specifying an agent;
        # follow-up messages stay with that agent until they switch or go idle.
        with self._recent_lock:
            if self._recent_agents:
                current = self._recent_agents[-1]
                if current != "assistant":
                    logger.info(
                        f"Context continuity → staying with {current}"
                    )
                    return current

        # Step 4: Keyword hints (secondary — only used when no explicit
        # agent selection and no active specialist conversation)
        words = set(re.findall(r'\b[\w\'-]+\b', lower))

        def _score(keywords: set[str]) -> int:
            score = 0
            for keyword in keywords:
                if " " in keyword:
                    # Multi-word keyword — substring match
                    if keyword in lower:
                        score += 1
                elif not keyword.replace("'", "").replace("-", "").isalpha():
                    # Keyword contains special chars (e.g. "s&p") — substring match
                    if keyword in lower:
                        score += 1
                elif keyword in words:
                    score += 1
            return score

        scores = {
            "trainer": _score(_TRAINER_KEYWORDS),
            "therapist": _score(_THERAPIST_KEYWORDS),
            "investment": _score(_INVESTMENT_KEYWORDS),
        }

        # Pick the highest-scoring agent, but only if it's unambiguous
        max_score = max(scores.values())
        if max_score > 0:
            winners = [a for a, s in scores.items() if s == max_score]
            if len(winners) == 1:
                logger.info(f"Keyword hint → {winners[0]} (score: {max_score})")
                return winners[0]

        # Step 5: Default — Assistant handles everything
        return "assistant"

    def _llm_classify(self, text: str) -> str:
        """
        Use a fast LLM call to classify ambiguous requests.

        Only called when keyword matching is inconclusive.
        """
        classifier_prompt = (
            "Classify this user message into exactly one agent. "
            "Respond with ONLY the agent ID — no explanation.\n\n"
            "Agents:\n"
            "- assistant: General tasks, practical requests, knowledge questions, commands\n"
            "- trainer: Physical health, fitness, nutrition, exercise, food, energy, sleep quality\n"
            "- therapist: Emotional state, stress, mental health, relationships, feelings, venting\n\n"
            f'User message: "{text}"\n\n'
            "Agent:"
        )

        try:
            if self._toggle.is_cloud:
                import anthropic

                client = anthropic.Anthropic(api_key=self._config.anthropic_api_key)
                response = client.messages.create(
                    model=self._config.claude_model,
                    max_tokens=10,
                    temperature=0.0,
                    messages=[{"role": "user", "content": classifier_prompt}],
                )
                result = response.content[0].text.strip().lower()
            else:
                import httpx

                resp = httpx.post(
                    "http://127.0.0.1:11434/api/chat",
                    json={
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": classifier_prompt}
                        ],
                        "stream": False,
                    },
                    timeout=10.0,
                )
                resp.raise_for_status()
                result = resp.json()["message"]["content"].strip().lower()

            # Validate result
            if result in _ACTIVE_AGENTS:
                logger.info(f"LLM classification → {result}")
                return result
            else:
                logger.warning(f"LLM returned invalid agent '{result}', defaulting to assistant")
                return "assistant"

        except Exception as e:
            logger.warning(f"LLM classification failed: {e} — defaulting to assistant")
            return "assistant"

    def _switch_agent(self, new_agent: str) -> None:
        """Switch the active agent and publish the event."""
        old_agent = self._active_agent
        if old_agent == new_agent:
            return

        self._active_agent = new_agent

        logger.info(f"Agent switch: {old_agent} → {new_agent}")

        self._bus.publish(Event(
            type=EventType.AGENT_SWITCH,
            source="orchestrator",
            data={
                "old_agent": old_agent,
                "new_agent": new_agent,
            },
        ))

    # ------------------------------------------------------------------
    # Streaming API (used by the voice pipeline for sentence-level TTS)
    # ------------------------------------------------------------------

    def process_request_streaming(self, text: str) -> Generator[str, None, None]:
        """
        Process a user request and yield complete sentences as they arrive.

        This enables sentence-level TTS pipelining: the first sentence can
        be synthesized and played while the LLM is still generating the rest.

        Yields:
            Complete sentences as strings.
        """
        start_time = time.monotonic()
        self._cancelled.clear()

        # Classify and route to the correct agent
        target_agent = self._classify_agent(text)
        self._switch_agent(target_agent)

        # Track routing history
        with self._recent_lock:
            self._recent_agents.append(target_agent)
            # Keep only last 10
            if len(self._recent_agents) > 10:
                self._recent_agents = self._recent_agents[-10:]

        logger.info(f"Orchestrator processing (streaming): '{text}' → {target_agent}")

        # Log user message to all memory layers
        self._store.log_conversation(
            session_id=self._session_id,
            role="user",
            content=text,
            metadata={"routed_to": target_agent},
        )
        self._md.log_turn("user", text, agent=target_agent)
        self._om.add_memory(text, sector="episodic", metadata={"role": "user"})

        # Update Redis buffer snapshot immediately on turn start
        self._redis.save_snapshot(self._session_id, {
            "last_turn": "user",
            "text": text,
            "agent": target_agent
        })

        # Add user message to Tier 1 conversation history
        with self._history_lock:
            self._conversation_history.append({
                "role": "user",
                "content": text,
            })

        # Publish agent request event
        self._bus.publish(Event(
            type=EventType.AGENT_REQUEST,
            source="orchestrator",
            data={
                "text": text,
                "agent": target_agent,
            },
        ))

        full_response = ""
        try:
            for sentence in self._stream_agent(text, target_agent):
                full_response += sentence + " "
                yield sentence
        except Exception as e:
            logger.error(f"Agent streaming failed: {e}")
            yield "I'm having trouble processing that right now. Please try again."
            full_response = "I'm having trouble processing that right now. Please try again."

        full_response = full_response.strip()

        # Add response to Tier 1 history
        with self._history_lock:
            self._conversation_history.append({
                "role": "assistant",
                "content": full_response,
            })

        # Log response to all memory layers
        self._store.log_conversation(
            session_id=self._session_id,
            role="assistant",
            agent_name=target_agent,
            content=full_response,
        )
        self._md.log_turn("assistant", full_response, agent=target_agent)
        # Classify message to a cognitive sector (simplified: assistant = episodic/procedural)
        sector = "procedural" if "how to" in full_response.lower() or "step" in full_response.lower() else "episodic"
        self._om.add_memory(full_response, sector=sector, metadata={"role": "assistant", "agent": target_agent})

        # Final Redis snapshot for the turn
        self._redis.save_snapshot(self._session_id, {
            "last_turn": "assistant",
            "text": full_response,
            "agent": target_agent
        })

        elapsed = (time.monotonic() - start_time) * 1000
        logger.info(f"Orchestrator response ({elapsed:.0f}ms): '{full_response[:80]}...'")

    def _stream_agent(self, text: str, agent: str) -> Generator[str, None, None]:
        """Stream sentences from the specified agent."""
        if not self._toggle.is_cloud:
            yield from self._stream_ollama(text, agent)
            return

        # Special agents (Therapist, Trainer, Investment) always use NVIDIA NIM if available
        is_specialist = agent in ("therapist", "trainer", "investment")
        if self._nvidia_client and (is_specialist or self._config.claude_model == "nvidia"):
            yield from self._stream_nvidia(text, agent)
        else:
            yield from self._stream_claude(text, agent)

    def _build_system_prompt(self, agent: str) -> str:
        """Build the system prompt for an agent, including SOUL.md and memory context."""
        soul = self._souls.get(agent, f"You are ARCHER's {agent} agent.")

        # Therapist-specific: Add profiling status and observer data
        if agent == "therapist":
            status = self._sqlite.get_therapist_status()
            phase = status["phase"]
            soul += f"\n\n## Current Mode: {phase.upper()} (Day {status['days_active']})"
            
            if phase == "profiling":
                soul += "\nPhase 1: Your primary goal is to establish a behavioral baseline. Ask profiling questions to understand Colby's norms."
                soul += "\n\nREQUIRED PROFILING QUESTIONS (weave into conversation):"
                soul += "\n- On a scale of 1-10, how would you describe your typical stress levels?"
                soul += "\n- Tell me about your sleep patterns in a normal week."
                soul += "\n- When you're stressed, what do you tend to do?"
                soul += "\n- How often do you typically socialize or have visitors?"
                soul += "\n- What does a 'good day' look like for you emotionally?"
            elif phase == "baseline":
                soul += "\nPhase 2: Establish baseline. Monitor environmental data but DO NOT intervene yet unless specifically asked."
            
            observer_context = self._get_observer_context()
            if observer_context:
                soul += f"\n\n## Latest Environmental Observations\n{observer_context}"

        # Retrieve relevant context from Tier 3 (ChromaDB) if available
        memory_context = self._retrieve_memory_context(agent)
        if memory_context:
            soul += f"\n\n## Semantic Memory Context\n{memory_context}"

        return soul

    def _get_observer_context(self) -> str:
        """Retrieve latest signals from the Observer via Tier 2 (SQLite)."""
        try:
            obs = self._sqlite.get_recent_observations(limit=5)
            if not obs:
                return ""
            
            lines = []
            for o in obs:
                lines.append(f"- [{o['source']}] {o['event_type']} (conf: {o['confidence']:.2f}): {o['payload']}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Failed to retrieve observer context: {e}")
            return ""

    def _retrieve_memory_context(self, agent: str) -> str:
        """Retrieve relevant context from Tier 3 (OpenMemory + ChromaDB)."""
        try:
            # Get last user message for context query
            last_user = None
            with self._history_lock:
                if self._conversation_history:
                    for msg in reversed(self._conversation_history):
                        if msg["role"] == "user":
                            last_user = msg["content"]
                            break
            
            if not last_user:
                return ""

            context_parts = []

            # Hybrid retrieval (Graph + Vector) via OpenMemory
            try:
                memos = self._om.search(last_user, limit=5)
                if memos:
                    for m in memos:
                        content = m.get("content", m.get("text", ""))
                        sector = m.get("sector", "unknown")
                        score = m.get("score", 0)
                        if content:
                            context_parts.append(f"- [OM:{sector}] {content} (conf: {score:.2f})")
            except Exception as e:
                logger.debug(f"OpenMemory retrieval skipped: {e}")

            # Specialist Knowledge Retrieval (ChromaDB)
            if agent == "therapist":
                try:
                    kb_memos = self._chroma.query(
                        query_text=last_user,
                        n_results=3,
                        collection_name="psychology_knowledge"
                    )
                    for pm in kb_memos:
                        content = pm.get("content", "")
                        source = pm.get("metadata", {}).get("source", "psych_kb")
                        if content:
                            # Keep knowledge base context distinct
                            context_parts.append(f"- [KB:{source}] {content}")
                except Exception as e:
                    logger.debug(f"Psychology KB retrieval skipped: {e}")

            if context_parts:
                logger.info(f"Retrieved {len(context_parts)} context items for {agent}")
                return "\n".join(context_parts)
                
            return ""
        except Exception as e:
            logger.error(f"Memory context retrieval failed: {e}")
            return ""

    def _stream_claude(self, text: str, agent: str) -> Generator[str, None, None]:
        """Stream sentences from Claude API for a specific agent.

        When the active agent is 'assistant', PC control tools are
        attached so Claude can invoke desktop automation.  Tool calls
        trigger a confirmation / execution loop before resuming the
        text stream.
        """
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self._config.anthropic_api_key)
            system_prompt = self._build_system_prompt(agent)

            with self._history_lock:
                messages = list(self._conversation_history[-20:])

            # Attach PC tools only for the assistant agent
            tools = None
            tool_executor = None
            if agent == "assistant":
                try:
                    from archer.tools.pc_tools import PC_TOOLS, PCToolExecutor
                    tools = PC_TOOLS
                    tool_executor = PCToolExecutor()
                except ImportError:
                    pass

            # We may loop back if the model issues tool_use calls
            max_tool_rounds = 5
            for _round in range(max_tool_rounds):
                buffer = ""
                tool_use_blocks: list[dict] = []
                current_tool_id = None
                current_tool_name = None
                current_tool_json = ""

                stream_kwargs: dict = dict(
                    model=self._config.claude_model,
                    max_tokens=self._config.max_tokens,
                    system=system_prompt,
                    messages=messages,
                )
                if tools:
                    stream_kwargs["tools"] = tools

                with client.messages.stream(**stream_kwargs) as stream:
                    for event in stream:
                        if self._cancelled.is_set():
                            break

                        # Text delta → buffer + sentence extraction
                        if hasattr(event, "type"):
                            if event.type == "content_block_start":
                                cb = event.content_block
                                if hasattr(cb, "type") and cb.type == "tool_use":
                                    current_tool_id = cb.id
                                    current_tool_name = cb.name
                                    current_tool_json = ""

                            elif event.type == "content_block_delta":
                                delta = event.delta
                                if hasattr(delta, "type"):
                                    if delta.type == "text_delta":
                                        text_chunk = delta.text
                                        buffer += text_chunk

                                        self._bus.publish(Event(
                                            type=EventType.AGENT_RESPONSE_CHUNK,
                                            source="orchestrator",
                                            data={
                                                "agent": agent,
                                                "chunk": text_chunk,
                                                "accumulated": buffer,
                                            },
                                        ))

                                        while True:
                                            match = _SENTENCE_BOUNDARY.search(buffer)
                                            if match is None:
                                                break
                                            sentence = buffer[:match.start()].strip()
                                            buffer = buffer[match.end():]
                                            if sentence:
                                                yield sentence

                                    elif delta.type == "input_json_delta":
                                        current_tool_json += delta.partial_json

                            elif event.type == "content_block_stop":
                                if current_tool_id and current_tool_name:
                                    import json as _json
                                    try:
                                        tool_input = _json.loads(current_tool_json) if current_tool_json else {}
                                    except _json.JSONDecodeError:
                                        tool_input = {}
                                    tool_use_blocks.append({
                                        "id": current_tool_id,
                                        "name": current_tool_name,
                                        "input": tool_input,
                                    })
                                    current_tool_id = None
                                    current_tool_name = None
                                    current_tool_json = ""

                # Yield any remaining text
                remaining = buffer.strip()
                if remaining:
                    yield remaining

                # If no tool calls, we're done
                if not tool_use_blocks or tool_executor is None:
                    break

                # Execute tool calls and build tool_result messages
                # Append the assistant message with tool_use blocks
                assistant_content = []
                if buffer.strip():
                    assistant_content.append({"type": "text", "text": buffer.strip()})
                for tb in tool_use_blocks:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tb["id"],
                        "name": tb["name"],
                        "input": tb["input"],
                    })
                messages.append({"role": "assistant", "content": assistant_content})

                # Execute each tool and collect results
                tool_results = []
                for tb in tool_use_blocks:
                    tool_name = tb["name"]
                    tool_input = tb["input"]

                    if tool_executor.requires_confirmation(tool_name):
                        # For confirmation-required tools, describe the action
                        # and ask for confirmation via a yielded sentence.
                        action_desc = f"I'd like to {tool_name.replace('_', ' ')}"
                        if tool_name == "open_url":
                            action_desc += f": {tool_input.get('url', '')}"
                        elif tool_name == "focus_window":
                            action_desc += f": {tool_input.get('title', '')}"
                        elif tool_name == "type_text":
                            action_desc += f": '{tool_input.get('text', '')[:50]}'"
                        action_desc += ". Shall I proceed?"
                        yield action_desc

                        # NOTE: In the full voice pipeline, confirmation is
                        # handled by listening for "yes" / "no". For now,
                        # we execute the tool (the PCController's HALT
                        # mechanism is the safety net).
                        logger.info(f"Executing PC tool: {tool_name}")

                    result = tool_executor.execute(tool_name, tool_input)
                    # Don't send base64 images back to the model — summarize
                    if "image" in result:
                        result_content = result.get("result", "Image captured successfully.")
                    else:
                        import json as _json
                        result_content = _json.dumps(result.get("result", result))

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tb["id"],
                        "content": str(result_content),
                    })

                    logger.info(f"Tool result ({tool_name}): {str(result_content)[:100]}")

                messages.append({"role": "user", "content": tool_results})

                # Loop back to get the model's follow-up response

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            if self._toggle.is_cloud:
                # In cloud mode, report the actual error — Ollama won't help.
                yield f"I'm having trouble reaching the Claude API. Error: {type(e).__name__}. Please check your API key and network connection."
            else:
                # In local mode, fall back to Ollama for this request
                yield from self._stream_ollama(text, agent)

    def _stream_nvidia(self, text: str, agent: str) -> Generator[str, None, None]:
        """Stream sentences from NVIDIA NIM (OpenAI-compatible) for an agent."""
        if not self._nvidia_client:
            yield "NVIDIA NIM is not configured. Please check your API key."
            return

        try:
            model = getattr(self._config, f"{agent}_model", "meta/llama-3.3-70b-instruct")
            system_prompt = self._build_system_prompt(agent)

            with self._history_lock:
                # Specialist agents get more context
                history_limit = 30 if agent != "assistant" else 20
                messages = [
                    {"role": "system", "content": system_prompt},
                ] + list(self._conversation_history[-history_limit:])

            # Tool support (Assistant only)
            tools = None
            tool_executor = None
            if agent == "assistant":
                try:
                    from archer.tools.pc_tools import PC_TOOLS, PCToolExecutor
                    # Map Anthropic schemas to OpenAI schemas if needed, 
                    # but NIM often supports the basic structure.
                    tools = PC_TOOLS
                    tool_executor = PCToolExecutor()
                except ImportError:
                    pass

            max_tool_rounds = 3
            for _round in range(max_tool_rounds):
                buffer = ""
                full_content = ""
                
                # Create the stream
                stream = self._nvidia_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    temperature=self._config.agent_temperature,
                    max_tokens=self._config.max_tokens,
                )

                for chunk in stream:
                    if self._cancelled.is_set():
                        break
                    
                    if not chunk.choices:
                        continue
                        
                    delta = chunk.choices[0].delta
                    if delta.content:
                        text_chunk = delta.content
                        buffer += text_chunk
                        full_content += text_chunk
                        
                        self._bus.publish(Event(
                            type=EventType.AGENT_RESPONSE_CHUNK,
                            source="orchestrator",
                            data={
                                "agent": agent,
                                "chunk": text_chunk,
                                "accumulated": full_content,
                            },
                        ))

                        while True:
                            match = _SENTENCE_BOUNDARY.search(buffer)
                            if match is None:
                                break
                            sentence = buffer[:match.start()].strip()
                            buffer = buffer[match.end():]
                            if sentence:
                                yield sentence

                if buffer.strip():
                    yield buffer.strip()

                # NVIDIA NIM tool use implementation would go here if needed.
                # Currently focus on specialist agents (no tools).
                break

        except Exception as e:
            logger.error(f"NVIDIA NIM error ({agent}): {e}")
            # Fall back to local Qwen as per spec
            yield "NVIDIA NIM limits reached or error occurred — falling back to local Qwen."
            yield from self._stream_ollama(text, agent)

    def _stream_ollama(self, text: str, agent: str) -> Generator[str, None, None]:
        """Stream sentences from Ollama (local) for a specific agent."""
        try:
            import httpx

            system_prompt = self._build_system_prompt(agent)

            with self._history_lock:
                messages = [
                    {"role": "system", "content": system_prompt},
                ] + list(self._conversation_history[-20:])

            buffer = ""

            with httpx.stream(
                "POST",
                "http://127.0.0.1:11434/api/chat",
                json={
                    "model": "qwen2.5:7b",
                    "messages": messages,
                    "stream": True,
                },
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if self._cancelled.is_set():
                        break
                    if not line:
                        continue
                    import json
                    data = json.loads(line)
                    chunk = data.get("message", {}).get("content", "")
                    if not chunk:
                        continue

                    buffer += chunk

                    # Extract complete sentences
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

        except Exception as e:
            logger.error(f"Ollama streaming error: {e}")
            yield "I'm having trouble connecting to the language model. Please check the configuration."

    # ------------------------------------------------------------------
    # Blocking API (fallback, used by text input path)
    # ------------------------------------------------------------------

    def process_request(self, text: str) -> str:
        """
        Process a user request (blocking). Returns the full response.

        This is the simple fallback. The voice pipeline uses
        process_request_streaming() for sentence-level TTS pipelining.
        """
        sentences = list(self.process_request_streaming(text))
        return " ".join(sentences)

    # ------------------------------------------------------------------
    # Proactive Intervention API (used by the Observer intervention engine)
    # ------------------------------------------------------------------

    def deliver_proactive_message(self, agent: str, prompt: str) -> None:
        """
        Deliver a proactive intervention message from the Observer.

        The prompt is a system-generated trigger that the agent responds to
        in-character. This bypasses the normal routing logic since the
        target agent is already determined by the intervention engine.

        Args:
            agent: The target agent ('trainer', 'therapist')
            prompt: The system prompt that triggers the agent's response
        """
        self._cancelled.clear()
        self._switch_agent(agent)

        logger.info(f"Proactive intervention → {agent}")

        # Build the response via streaming
        full_response = ""
        try:
            for sentence in self._stream_agent(prompt, agent):
                full_response += sentence + " "
                # Publish each sentence for voice pipeline TTS
                self._bus.publish(Event(
                    type=EventType.AGENT_RESPONSE_CHUNK,
                    source="orchestrator",
                    data={
                        "agent": agent,
                        "chunk": sentence,
                        "proactive": True,
                    },
                ))
        except Exception as e:
            logger.error(f"Proactive intervention failed: {e}")
            full_response = ""

        full_response = full_response.strip()

        if full_response:
            # Log to Tier 2
            self._store.log_conversation(
                session_id=self._session_id,
                role="assistant",
                agent_name=agent,
                content=full_response,
                metadata={"proactive": True},
            )

            # Publish response end for GUI
            self._bus.publish(Event(
                type=EventType.AGENT_RESPONSE_END,
                source="orchestrator",
                data={
                    "text": full_response,
                    "agent": agent,
                    "proactive": True,
                },
            ))

            logger.info(f"Proactive response ({agent}): '{full_response[:80]}'")

    def deliver_proactive_streaming(
        self, agent: str, prompt: str
    ) -> Generator[str, None, None]:
        """
        Deliver a proactive intervention as a streaming generator.

        This is the streaming variant used by the voice pipeline for
        sentence-level TTS pipelining of proactive messages.

        Yields:
            Complete sentences as strings.
        """
        self._cancelled.clear()
        self._switch_agent(agent)

        logger.info(f"Proactive intervention (streaming) → {agent}")

        full_response = ""
        try:
            for sentence in self._stream_agent(prompt, agent):
                full_response += sentence + " "
                yield sentence
        except Exception as e:
            logger.error(f"Proactive intervention streaming failed: {e}")

        full_response = full_response.strip()
        if full_response:
            self._store.log_conversation(
                session_id=self._session_id,
                role="assistant",
                agent_name=agent,
                content=full_response,
                metadata={"proactive": True},
            )

    def clear_history(self) -> None:
        """Clear the in-session conversation history (Tier 1 memory reset)."""
        with self._history_lock:
            self._conversation_history.clear()
        with self._recent_lock:
            self._recent_agents.clear()
        logger.info("Conversation history cleared (Tier 1). Tier 2 logs preserved.")

    def _on_halt(self, event: Event) -> None:
        """HALT handler — cancel active agent call."""
        self._cancelled.set()
        logger.info("HALT: Agent call cancelled.")

    @property
    def active_agent(self) -> str:
        """Get the currently active agent name."""
        return self._active_agent

    @property
    def session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id

    @property
    def conversation_history(self) -> list[dict[str, str]]:
        """Get a copy of the in-session conversation history."""
        with self._history_lock:
            return list(self._conversation_history)
