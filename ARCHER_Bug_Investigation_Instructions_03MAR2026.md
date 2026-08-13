# ARCHER Bug Investigation & Fixes

**Date:** March 8, 2026  
**For:** Antigravity Development Team  
**Priority:** Medium - System functional but has bugs

---

## Issue 1: Duplicate Text Input Detection

### Problem
```
User types: "hello"
ARCHER responds: "It looks like you're saying hello twice!"
```

System is detecting/processing single input twice.

### Investigation Steps

#### Step 1: Check GUI Text Input Handler

**File:** `src/archer/gui/console_widget.py` or `src/archer/gui/main_window.py`

**Look for text input submission code:**
```python
# Search for methods handling Enter key or Send button
# Common patterns to look for:
def _on_send_clicked(self):
def _on_return_pressed(self):
def keyPressEvent(self, event):
```

**Check for:**
1. Is the event handler called twice?
2. Is there both a button click AND Enter key handler triggering?
3. Is the signal connected multiple times?

**Add debug logging:**
```python
def _on_send_clicked(self):
    logger.info(f"DEBUGGING: _on_send_clicked called with text: {self.input_box.text()}")
    # ... existing code
```

#### Step 2: Check Voice Pipeline Text Handler

**File:** `src/archer/voice/pipeline.py`

**Find the `_on_text_input` method (line ~656):**
```python
def _on_text_input(self, text: str):
    logger.info(f"📝 Text input: '{text}'")
    # ... rest of method
```

**Add debug logging BEFORE this line:**
```python
def _on_text_input(self, text: str):
    import traceback
    logger.info(f"DEBUGGING: _on_text_input called, stack trace:")
    logger.info("".join(traceback.format_stack()))
    logger.info(f"📝 Text input: '{text}'")
    # ... rest of method
```

**Run ARCHER and type "hello"** - check logs for how many times it's called and from where.

#### Step 3: Check for Signal/Event Double-Connection

**Search for signal connections:**
```powershell
cd D:\ARCHER_9\src
grep -r "connect.*_on_text_input" .
grep -r "connect.*send_clicked" .
```

**Look for duplicate connections like:**
```python
# BAD - connecting twice:
self.send_button.clicked.connect(self._on_send_clicked)
self.send_button.clicked.connect(self._on_send_clicked)  # Duplicate!

# GOOD - only once:
self.send_button.clicked.connect(self._on_send_clicked)
```

### Expected Fix

Once you identify the source, it's likely one of:

**A) Duplicate signal connection:**
```python
# Remove duplicate connection
self.input_box.returnPressed.connect(self._on_send_clicked)
# self.input_box.returnPressed.connect(self._on_send_clicked)  # DELETE THIS
```

**B) Both Enter key AND button triggering:**
```python
def _on_send_clicked(self):
    text = self.input_box.text().strip()
    if not text:
        return
    
    # Clear input FIRST to prevent double-send
    self.input_box.clear()
    
    # Then send
    self._send_to_voice_pipeline(text)
```

**C) Event propagating twice:**
```python
def keyPressEvent(self, event):
    if event.key() == Qt.Key_Return:
        self._on_send_clicked()
        event.accept()  # Stop event propagation
        return
    super().keyPressEvent(event)
```

---

## Issue 2: Ollama 404 Investigation

### Problem
```
INFO:httpx:HTTP Request: POST http://localhost:11434/api/generate "HTTP/1.1 404 Not Found"
```

But responses ARE coming from Ollama (8+ second response times indicate local LLM).

### Investigation Steps

#### Step 1: Verify Ollama is Running

```powershell
# Check if Ollama process is running
Get-Process ollama

# Check if Ollama is responding
curl http://localhost:11434/api/tags

# Check Ollama version
ollama --version
```

**Expected:** JSON response from `/api/tags` showing available models.

#### Step 2: Search for 404 Request Source

**Search for code making the failing request:**
```powershell
cd D:\ARCHER_9\src
grep -r "11434/api/generate" .
grep -r "ollama.*generate" .
```

**Look for TWO different request patterns:**
```python
# Correct Ollama API endpoint:
response = requests.post("http://localhost:11434/api/generate", ...)

# Incorrect endpoint that might 404:
response = requests.post("http://localhost:11434/api/chat", ...)  # Wrong
```

#### Step 3: Add Request Logging

**File:** `src/archer/agents/orchestrator.py`

**Find the `_stream_local` method:**
```python
def _stream_local(self, prompt: str, ...):
    full_response = ""
    
    # ADD THIS DEBUG LOGGING:
    logger.info(f"DEBUGGING: About to call Ollama at {ollama_url}")
    logger.info(f"DEBUGGING: Endpoint: {endpoint}")
    logger.info(f"DEBUGGING: Payload: {payload}")
    
    # ... existing request code
```

**Run ARCHER, type a message, check logs for:**
- What URL is being called
- What endpoint path is used
- Whether multiple requests are made

#### Step 4: Check Ollama Model Availability

```powershell
ollama list
```

**Expected output:**
```
NAME            ID              SIZE
llama3:8b       abc123...       4.7 GB
```

**If model not found:**
```powershell
ollama pull llama3:8b
```

### Expected Fix

Likely one of:

**A) Wrong endpoint:**
```python
# WRONG:
url = "http://localhost:11434/api/chat"

# CORRECT:
url = "http://localhost:11434/api/generate"
```

**B) Model name mismatch:**
```python
# Config says:
model = "llama3:8b"

# But Ollama has:
# llama3.1:8b (different version)

# Fix in .env or config:
OLLAMA_MODEL=llama3.1:8b
```

**C) Secondary request failing:**
```python
# Main request works
response1 = ollama.generate(...)  # ✓ Works

# Some other code tries again with wrong endpoint
response2 = ollama.chat(...)  # ✗ 404
```

---

## Issue 3: Incorrect Date in Responses

### Problem
```
User: "what is todays date?"
Assistant: "Today's date is March 12, 2023"
Actual date: March 8, 2026
```

LLM doesn't know current date - needs injection in system prompt.

### Fix Steps

#### Step 1: Find System Prompt Injection Point

**File:** `src/archer/agents/orchestrator.py`

**Search for where prompts are built:**
```python
# Look for system message construction:
def _build_prompt(self, ...):
    system_message = "You are ARCHER..."
```

OR

```python
# Look for SOUL.md loading:
def _load_soul(self, agent_name: str):
    soul_content = read_file(f"souls/{agent_name}/SOUL.md")
```

#### Step 2: Add Current Date to System Prompt

**Option A: Modify prompt builder:**
```python
from datetime import datetime

def _build_prompt(self, user_message: str, agent: str) -> str:
    # Get current date
    current_date = datetime.now().strftime("%A, %B %d, %Y")
    current_time = datetime.now().strftime("%I:%M %p")
    
    # Load SOUL.md
    soul = self._load_soul(agent)
    
    # Build system message with date injection
    system_message = f"""
{soul}

CURRENT DATE AND TIME:
Today is {current_date}
Current time is {current_time}

Always use this information when asked about dates or times.
"""
    
    return system_message
```

**Option B: Inject in each SOUL.md file:**

**Files:** `src/archer/souls/*/SOUL.md`

**Add to each SOUL.md:**
```markdown
# SOUL.md for Assistant

[existing personality content...]

## Current Context
{{CURRENT_DATE}} - This will be replaced at runtime
{{CURRENT_TIME}} - This will be replaced at runtime
```

**Then in orchestrator:**
```python
def _load_soul(self, agent_name: str) -> str:
    from datetime import datetime
    
    soul_content = read_soul_file(agent_name)
    
    # Replace placeholders
    current_date = datetime.now().strftime("%A, %B %d, %Y")
    current_time = datetime.now().strftime("%I:%M %p")
    
    soul_content = soul_content.replace("{{CURRENT_DATE}}", current_date)
    soul_content = soul_content.replace("{{CURRENT_TIME}}", current_time)
    
    return soul_content
```

#### Step 3: Verify Fix

**After implementing, test:**
```
User: "What is today's date?"
Expected: "Today is Saturday, March 8, 2026"

User: "What time is it?"
Expected: "It's currently 10:00 PM" (or actual time)
```

### Recommended Approach

**Use Option A (modify prompt builder)** - cleaner and doesn't require editing all SOUL.md files.

**Implementation location:**
```python
# File: src/archer/agents/orchestrator.py
# Method: _stream_local() or _stream_claude()
# Add date/time to system message before sending to LLM
```

---

## Verification Checklist

After fixes:

### Duplicate Input
- [ ] Type "hello" in GUI
- [ ] ARCHER should NOT say "you're saying hello twice"
- [ ] Only one log entry for `_on_text_input` per message
- [ ] Stack trace shows single call path

### Ollama 404
- [ ] `ollama list` shows llama3:8b
- [ ] `curl http://localhost:11434/api/tags` returns JSON
- [ ] No 404 errors in ARCHER logs during conversation
- [ ] Response times still 5-10 seconds (indicates local model)

### Correct Date
- [ ] Ask "what is today's date?"
- [ ] ARCHER responds with "March 8, 2026" or "Saturday, March 8, 2026"
- [ ] Ask "what time is it?"
- [ ] ARCHER responds with current time (not from 2023)
- [ ] Date updates automatically on next day

---

## Debug Logging Template

**Add these to help investigation:**

```python
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# In text input handler:
logger.info(f"[{datetime.now()}] TEXT_INPUT called with: '{text}'")

# In Ollama request:
logger.info(f"[{datetime.now()}] OLLAMA_REQUEST to {url} with model {model}")

# In prompt builder:
logger.info(f"[{datetime.now()}] PROMPT_BUILT with date: {current_date}")
```

**Run ARCHER with debug logging:**
```powershell
python -m archer 2>&1 | Tee-Object -FilePath debug.log
```

**Send debug.log file** showing:
1. User typing "hello" (shows duplicate input issue)
2. User asking date (shows wrong date issue)
3. Ollama request/response cycle (shows 404 issue)

---

## Questions for Clarification

**Before starting, please confirm:**

1. **Ollama running?** Run `ollama list` and share output
2. **Which file handles GUI text input?** Likely `console_widget.py` or `main_window.py`
3. **Where are SOUL.md files located?** Need path to inject date
4. **Can you add debug logging?** Or should we add it together?

---

**Document Status:** Ready for investigation  
**Estimated Time:** 2-3 hours total for all three issues  
**Priority Order:** Date fix (easiest) → Duplicate input → Ollama 404 (lowest priority if responses work)
