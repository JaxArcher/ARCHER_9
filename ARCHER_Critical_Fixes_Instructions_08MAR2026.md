# ARCHER Critical Fixes - Priority Task List

**Date:** March 8, 2026  
**For:** Antigravity Development Team  
**Status:** Three critical blockers preventing ARCHER from functioning

---

## Overview

ARCHER core systems are functional but three issues prevent proper operation:
1. CUDA not detected (GPU idle, everything on CPU)
2. Code bug in orchestrator.py
3. Ollama service not running

**Fix these in order, then add FastAPI wrapper for mobile app.**

---

## Fix 1: CUDA Detection (PRIORITY 1)

### Problem
```
FutureWarning: NVIDIA GeForce RTX 5080 with CUDA capability sm_120 is not compatible with the current PyTorch installation.
```

PyTorch not detecting RTX 5080 GPU. System running on CPU with poor performance.

### Prerequisites

#### Check NVIDIA Driver
```powershell
nvidia-smi
```

**Required:** CUDA version 12.8 or higher shown in top-right corner

**If lower than 12.8:**
1. Go to https://www.nvidia.com/drivers
2. Select: GeForce RTX 50 Series → RTX 5080 → Windows
3. Download and install latest driver
4. Restart computer

#### Install Visual C++ Redistributable
**Required to prevent DLL errors**

1. Download: https://aka.ms/vs/17/release/vc_redist.x64.exe
2. Run installer
3. Restart computer

### Solution Steps

#### Step 1: Clean Uninstall Old PyTorch
```powershell
cd D:\ARCHER_9
.venv\Scripts\activate
pip uninstall torch torchvision torchaudio -y
pip cache purge
```

#### Step 2: Install PyTorch 2.7.0 with CUDA 12.8
```powershell
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

**Note:** 
- `cu128` = CUDA 12.8
- Compatible with CUDA 12.9+ drivers (forward compatible)
- **Do NOT use nightly builds** - they caused dependency conflicts previously

#### Step 3: Verify Installation
```powershell
python -c "import torch; print('CUDA Available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

**Expected Output:**
```
CUDA Available: True
GPU: NVIDIA GeForce RTX 5080
```

**If you see warnings about sm_120:** PyTorch is still detecting GPU correctly, warnings are non-fatal.

### Troubleshooting

#### Issue: "DLL load failed" error
**Solution:** Install Visual C++ Redistributable (see Prerequisites)

#### Issue: CUDA Available returns False
**Solutions:**
1. Check NVIDIA driver supports CUDA 12.8+ (run `nvidia-smi`)
2. Restart terminal/computer
3. Verify PyTorch installed from cu128 index (not CPU version)

#### Issue: "Could not find torchaudio"
**Solution:** Install without torchaudio:
```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```
ARCHER doesn't require torchaudio.

### Verification Tests

**Test 1: Basic CUDA**
```powershell
python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"
```

**Test 2: GPU Memory**
```powershell
python -c "import torch; print('GPU Memory:', torch.cuda.get_device_properties(0).total_memory / 1024**3, 'GB')"
```

**Expected:** ~16 GB for RTX 5080

**Test 3: ARCHER Startup**
```powershell
python -m archer
```

Look for faster initialization times and no CUDA warnings.

---

## Fix 2: Orchestrator Code Bug (PRIORITY 2)

### Problem
```
ERROR: Local model fallback failed: name 'full_response' is not defined
```

Variable `full_response` used before initialization in `_stream_local()` method.

### Solution

**File:** `D:\ARCHER_9\src\archer\agents\orchestrator.py`

**Find the `_stream_local()` method** (around line 1000-1100)

**Add this line at the very start of the method:**

```python
def _stream_local(self, prompt: str, agent: str, session_id: str) -> dict:
    """Stream response from local Ollama model."""
    full_response = ""  # ← ADD THIS LINE FIRST
    
    # ... rest of existing code ...
```

**Why this fixes it:**
The variable `full_response` is referenced later in the method but never initialized if certain code paths execute. Adding initialization at the start prevents `NameError`.

### Verification

After fix, test:
```powershell
python -m archer
```

Try voice command. Should not see "name 'full_response' is not defined" error.

---

## Fix 3: Start Ollama Service (PRIORITY 3)

### Problem
```
ERROR: 404 Client Error: Not Found for url: http://localhost:11434/api/generate
```

Ollama service not running on localhost:11434.

### Check if Ollama is Installed

```powershell
ollama --version
```

**If command not found:** Ollama not installed, proceed to Installation section below.

**If version shows:** Ollama installed, proceed to Start Service section.

### Installation (If Needed)

#### Download Ollama
1. Go to https://ollama.com/download/windows
2. Download OllamaSetup.exe
3. Run installer
4. Restart terminal after installation

#### Pull Required Model
```powershell
ollama pull llama3:8b
```

Wait for download to complete (~4.7 GB).

### Start Ollama Service

#### Option A: Start as Background Service (Recommended)
```powershell
# Ollama should auto-start on Windows after installation
# If not running, launch Ollama app from Start Menu
```

#### Option B: Start Manually in Terminal
```powershell
ollama serve
```

**Keep this terminal window open** - Ollama runs in foreground.

### Verify Ollama is Running

```powershell
curl http://localhost:11434/api/tags
```

**Expected:** JSON response listing available models including `llama3:8b`

**If connection refused:** Ollama not running, restart it.

### Test with ARCHER

```powershell
# In separate terminal:
cd D:\ARCHER_9
.venv\Scripts\activate
python -m archer
```

Try voice command. Should see:
```
INFO: Orchestrator processing (streaming): 'your message' → assistant
```

And receive actual response instead of "technical difficulties".

---

## Fix 4: Add FastAPI Wrapper (AFTER FIXES 1-3)

### Overview

Create REST API endpoints for mobile app to connect to ARCHER backend.

### Implementation

**Create new file:** `D:\ARCHER_9\src\archer\server.py`

```python
"""
ARCHER Mobile API Server
FastAPI wrapper around existing agent orchestrator for mobile app access.
"""

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os

from archer.agents.orchestrator import AgentOrchestrator
from archer.memory.sqlite_store import SQLiteStore
from archer.memory.chromadb_store import ChromaDBStore

app = FastAPI(title="ARCHER Mobile API", version="1.0.0")

# CORS - only allow Tailscale network
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production to Tailscale IPs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authentication
MOBILE_TOKEN = os.getenv("ARCHER_MOBILE_TOKEN", "CHANGE_IN_PRODUCTION")

def verify_token(authorization: str = Header(...)):
    """Verify bearer token from mobile app."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = authorization.replace("Bearer ", "")
    if token != MOBILE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return token


# Request/Response Models
class ChatRequest(BaseModel):
    message: str
    user_id: str = "col"
    response_format: str = "text"  # "text" or "audio"


class ChatResponse(BaseModel):
    agent: str
    response: str
    timestamp: str
    conversation_id: str


# Initialize services
orchestrator = None
memory_store = None

@app.on_event("startup")
async def startup():
    """Initialize ARCHER services on startup."""
    global orchestrator, memory_store
    
    # Initialize orchestrator (reuse existing instance if possible)
    # TODO: Import and initialize your existing orchestrator
    # orchestrator = AgentOrchestrator()
    
    # Initialize memory stores
    # TODO: Import existing memory stores
    # memory_store = SQLiteStore()
    
    print("ARCHER Mobile API server started")


# Endpoints
@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "ARCHER Mobile API"}


@app.post("/mobile/chat")
async def mobile_chat(
    request: ChatRequest,
    token: str = Depends(verify_token)
):
    """
    Process text message from mobile app and return agent response.
    
    TODO: Integration needed:
    1. Route to existing AgentOrchestrator.process_request_streaming()
    2. Extract agent name and response text
    3. Store in memory
    4. Return formatted response
    """
    
    # PLACEHOLDER - Replace with actual orchestrator call
    # response = await orchestrator.process_request_streaming(request.message)
    
    return ChatResponse(
        agent="Assistant",
        response="Mobile API placeholder - integrate with orchestrator",
        timestamp="2026-03-08T18:00:00Z",
        conversation_id="placeholder-id"
    )


@app.get("/mobile/memory/recent")
async def get_recent_memory(
    limit: int = 20,
    token: str = Depends(verify_token)
):
    """
    Get recent conversations from memory.
    
    TODO: Integration needed:
    1. Query SQLite conversation_logs table
    2. Return last N conversations
    """
    
    return {
        "conversations": [],
        "total": 0,
        "message": "Memory integration needed"
    }


@app.get("/mobile/memory/search")
async def search_memory(
    q: str,
    limit: int = 10,
    token: str = Depends(verify_token)
):
    """
    Semantic search across conversation memory.
    
    TODO: Integration needed:
    1. Use ChromaDB.query() for semantic search
    2. Return ranked results
    """
    
    return {
        "results": [],
        "query": q,
        "total_results": 0,
        "message": "Search integration needed"
    }


@app.get("/mobile/health")
async def health_check():
    """Health check - no authentication required."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "agents_available": [
            "assistant",
            "trainer", 
            "therapist",
            "investment",
            "blindspot",
            "inventory",
            "observer"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Configuration

**Add to `.env` file:**
```
ARCHER_MOBILE_TOKEN=generate-secure-random-token-here
```

Generate token:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Running the Server

**Option A: Standalone (for testing)**
```powershell
cd D:\ARCHER_9
.venv\Scripts\activate
python src/archer/server.py
```

**Option B: With Uvicorn**
```powershell
uvicorn src.archer.server:app --host 0.0.0.0 --port 8000 --reload
```

### Testing Endpoints

**Test health check:**
```powershell
curl http://localhost:8000/mobile/health
```

**Test authenticated endpoint:**
```powershell
curl -X POST http://localhost:8000/mobile/chat \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello ARCHER", "user_id": "col"}'
```

### Integration Tasks

The server.py file above has TODO comments for integration points:

1. **Import existing orchestrator** - Connect to running ARCHER instance
2. **Route chat requests** - Call `orchestrator.process_request_streaming()`
3. **Memory queries** - Connect to SQLiteStore and ChromaDBStore
4. **Response formatting** - Extract agent name, text, timestamp

These integrations should reuse existing ARCHER code, not reimplement logic.

---

## Verification Checklist

After completing all fixes:

- [ ] `torch.cuda.is_available()` returns True
- [ ] No "sm_120 not compatible" warnings (or only non-fatal warnings)
- [ ] `python -m archer` starts without CUDA errors
- [ ] Ollama responds on `http://localhost:11434/api/tags`
- [ ] Voice commands get actual responses (not "technical difficulties")
- [ ] No "name 'full_response' is not defined" errors
- [ ] FastAPI server starts: `python src/archer/server.py`
- [ ] Health check works: `curl http://localhost:8000/mobile/health`

---

## Expected Performance After Fixes

### With RTX 5080 GPU Working:
- **Faster-Whisper (STT):** ~200-500ms (vs 3-5s on CPU)
- **Vision Models:** ~100-200ms per frame (vs 1-2s on CPU)
- **LLM Inference (Ollama):** ~50-100 tokens/sec (vs 5-10 on CPU)

### With Ollama Working:
- Actual agent responses instead of error messages
- Local model fallback functional when cloud APIs unavailable

### With FastAPI Working:
- Mobile app can connect to ARCHER backend
- RESTful API for agent interactions
- Foundation for mobile development

---

## Support & Questions

**If you encounter issues:**

1. **CUDA problems:** Verify driver version with `nvidia-smi`, ensure Visual C++ installed
2. **Ollama problems:** Check service running with `curl http://localhost:11434/api/tags`
3. **Code bugs:** Search codebase for similar patterns, check variable initialization
4. **API integration:** Review existing orchestrator code for correct method signatures

**Priority order matters:** Fix CUDA first (affects everything), then code bugs, then services, then new features.

---

**Document Status:** Ready for implementation  
**Last Updated:** March 8, 2026  
**Prepared For:** Antigravity Development Team
