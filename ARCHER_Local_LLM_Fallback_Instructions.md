# ARCHER Local LLM Fallback Implementation

## Objective
Add automatic fallback to local Qwen 3.5:4b model when Claude API fails, and make it the primary local model.

## Task 1: Update Configuration

**File:** `src/archer/config.py`

Add these fields to the `ArcherConfig` class:

```python
# Local fallback model
local_fallback_model: str = Field(default="qwen3.5:4b", alias="ARCHER_LOCAL_MODEL")
enable_auto_fallback: bool = Field(default=True, alias="ARCHER_ENABLE_FALLBACK")
```

## Task 2: Implement Automatic Fallback in Orchestrator

**File:** `src/archer/agents/orchestrator.py`

In the `_stream_claude()` method, wrap the Claude API call with fallback logic:

```python
def _stream_claude(self, agent: str, text: str) -> Generator[str, None, None]:
    """Stream response from Claude with automatic local fallback."""
    
    # Try Claude API first
    try:
        # Existing Claude streaming code here
        ...
        
    except anthropic.APIError as e:
        # Log the API failure
        logger.warning(f"Claude API failed: {e}. Falling back to local model.")
        
        # Fall back to local Ollama model
        if self._config.enable_auto_fallback:
            yield from self._stream_local(agent, text)
        else:
            raise
```

Add new method `_stream_local()`:

```python
def _stream_local(self, agent: str, text: str) -> Generator[str, None, None]:
    """Stream response from local Ollama model."""
    import requests
    
    system_prompt = self._build_system_prompt(agent)
    
    # Get conversation history
    with self._history_lock:
        messages = list(self._conversation_history[-10:])
    
    # Format for Ollama
    prompt = f"{system_prompt}\n\n"
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prompt += f"{role.upper()}: {content}\n"
    prompt += f"USER: {text}\nASSISTANT:"
    
    # Call Ollama API
    url = f"{self._config.ollama_base_url}/api/generate"
    payload = {
        "model": self._config.local_fallback_model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": self._config.agent_temperature,
            "num_ctx": 4096
        }
    }
    
    try:
        response = requests.post(url, json=payload, stream=True, timeout=60)
        response.raise_for_status()
        
        buffer = ""
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                token = data.get("response", "")
                buffer += token
                
                # Yield complete sentences
                sentences = self._split_sentences(buffer)
                for sentence in sentences[:-1]:
                    yield sentence.strip()
                buffer = sentences[-1]
        
        # Yield remaining text
        if buffer.strip():
            yield buffer.strip()
            
    except Exception as e:
        logger.error(f"Local model fallback failed: {e}")
        yield "I'm experiencing technical difficulties. Please try again."
```

