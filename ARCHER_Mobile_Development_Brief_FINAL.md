# ARCHER Mobile App - Development Brief for Antigravity

**Date:** March 6, 2026  
**Client:** Col  
**Project:** ARCHER Android Mobile App  
**Timeline:** Complete before Col returns from travel (target: 2-3 weeks)

---

## Executive Summary

Build a native Android app that allows Col to interact with ARCHER's AI agent system while traveling. The app is a thin client connecting to ARCHER backend (running on Col's home PC with RTX 5080) via Tailscale VPN.

**Key Design Decision:** Use Android's native voice input for STT + on-device TTS for responses. This eliminates microphone permissions, works offline, and provides better UX than custom voice pipeline.

---

## Project Context

### What is ARCHER?
ARCHER (Advanced Responsive Computing Helper & Executive Resource) is Col's personal AI assistant system featuring:
- 7 specialized AI agents (Assistant, Therapist, Trainer, Investment, Blindspot, Inventory, Observer)
- Multi-tier memory system (SQLite, ChromaDB, Mem0)
- Voice interaction with wake word detection
- Behavioral monitoring via webcam/microphone
- PC control and automation capabilities

### Current State
- ✅ Desktop GUI fully functional (PyQt6 on Windows)
- ✅ Voice pipeline working (wake word, STT, TTS, agent routing)
- ✅ 7 agents operational with distinct personalities
- ✅ Observer containers running (MediaPipe, DeepFace)
- ✅ Tailscale configured (IP: 100.96.72.71)
- ✅ RDP remote access working

### Mobile App Purpose
Col needs lightweight access to ARCHER while traveling:
- Quick text interactions with agents
- Voice input/output for hands-free use
- Access to conversation memory
- Works anywhere via Tailscale VPN

---

## Technical Architecture

### Network Transport
```
Phone (Android)
    ↓
Tailscale VPN (encrypted tunnel)
    ↓
Col's Home Network (100.96.72.71:8000)
    ↓
ARCHER Backend (FastAPI)
    ↓
Agent Orchestrator → 7 Agents
    ↓
Memory Systems (SQLite, ChromaDB, Mem0)
```

**Security:** 
- All traffic over Tailscale (zero-trust VPN)
- No public internet exposure
- Bearer token authentication
- 100% private - no data leaves Col's network

---

## Mobile App Specification

### Platform
- **Target:** Android only
- **Minimum:** Android 10 (API 29)
- **Target SDK:** Android 14 (API 34)
- **Distribution:** APK (direct install / sideload)

### Tech Stack Options

**Option A: React Native (Recommended for Speed)**
- Framework: Expo / React Native CLI
- Language: TypeScript
- Timeline: ~2 weeks for full app
- Pros: Faster development, can add iOS later
- Cons: Slightly larger APK size

**Option B: Native Kotlin**
- Framework: Jetpack Compose
- Language: Kotlin
- Pros: Better performance, smaller APK
- Cons: Takes longer to build

**Our Recommendation:** React Native for initial build, can port to Kotlin later if needed.

---

## Core Features

### Phase 1: Text Chat (MVP)

**User Flow:**
1. User opens app
2. Types message to ARCHER
3. Agent processes and responds
4. Conversation stored locally

**UI Components:**
- Chat interface (messages scrollable list)
- Text input field
- Send button
- Agent indicator (shows which agent is responding)
- Connection status indicator (Tailscale connected/disconnected)

**Technical Implementation:**
```typescript
// API call to ARCHER
const response = await fetch('http://100.96.72.71:8000/mobile/chat', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer YOUR_TOKEN',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    message: userInput,
    user_id: 'col',
    response_format: 'text'
  })
});

const data = await response.json();
// { agent: "Assistant", response: "...", timestamp: "...", conversation_id: "..." }
```

**Local Storage:**
- SQLite database for conversation history
- Store: message text, agent name, timestamp, conversation_id
- Persist across app restarts

**Deliverable:** Working text chat app, messages persist, connects via Tailscale

---

### Phase 2: Voice Features

**Voice Input Strategy: Use Android Native Dictation**

Instead of recording audio and uploading to server, use Android's built-in voice input:

```kotlin
// Trigger Android voice input
val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
    putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak to ARCHER")
}
startActivityForResult(intent, VOICE_INPUT_REQUEST)

// Receive transcribed text
override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
    if (requestCode == VOICE_INPUT_REQUEST && resultCode == RESULT_OK) {
        val results = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
        val text = results?.get(0) ?: ""
        // Send text to ARCHER (same as typed message)
        sendMessageToArcher(text)
    }
}
```

**Why This Approach:**
- ✅ Zero microphone permissions needed
- ✅ Better STT quality (Google's voice recognition)
- ✅ Familiar UX (users know how this works)
- ✅ Works offline (after initial setup)
- ✅ No audio upload bandwidth

**Voice Output Strategy: Three Tiers**

**Tier 1: Android System TTS (Use for MVP)**
```kotlin
val tts = TextToSpeech(context) { status ->
    if (status == TextToSpeech.SUCCESS) {
        tts.speak(archerResponse, TextToSpeech.QUEUE_FLUSH, null, null)
    }
}
```
- Built into Android (zero setup)
- Works offline
- Good quality
- **START HERE**

**Tier 2: Piper TTS (Add for Production Quality)**
```kotlin
// Add Piper ONNX model (~25MB) to assets/
val piper = PiperTTS(context)
piper.loadModel("en_US-amy-medium.onnx")
piper.synthesize(archerResponse) { audioData ->
    mediaPlayer.play(audioData)
}
```
- Download model: https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US
- Recommended: `en_US-amy-medium.onnx` (~25MB)
- Excellent quality
- Works offline
- **ADD THIS IN PHASE 2 IF TIME PERMITS**

**Tier 3: Server TTS (Optional - Skip for Now)**
- Request audio from ARCHER backend
- Only needed if Col wants exact voice match with desktop
- Requires active Tailscale connection
- **SKIP UNLESS SPECIFICALLY REQUESTED**

**UI Components:**
- Microphone button (triggers Android voice input)
- "Voice Mode" toggle (enable/disable TTS responses)
- Audio playback indicator
- TTS settings (speed, voice selection)

**Deliverable:** Voice input working, TTS responses playing

---

### Phase 3: Memory & Advanced Features

**Recent Conversations:**
```typescript
const history = await fetch('http://100.96.72.71:8000/mobile/memory/recent?limit=20', {
  headers: { 'Authorization': 'Bearer TOKEN' }
});
// Returns last 20 conversations with summaries
```

**Semantic Search:**
```typescript
const results = await fetch('http://100.96.72.71:8000/mobile/memory/search?q=fitness', {
  headers: { 'Authorization': 'Bearer TOKEN' }
});
// Returns relevant conversations matching query
```

**UI Components:**
- Search bar
- Conversation history list
- Conversation detail view
- Filter by agent / date

**Deliverable:** Memory search working, can browse history

---

## Backend Requirements (For ARCHER Team)

Col's ARCHER backend needs these new endpoints added. **Question for Col: Who will implement these - Antigravity or Col's team?**

### Endpoint 1: Text Chat

```python
# File: ARCHER_backend/mobile_api.py (new file)

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
import os

app = FastAPI()

# Authentication
MOBILE_TOKEN = os.getenv("ARCHER_MOBILE_TOKEN", "CHANGE_IN_PRODUCTION")

def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")
    token = authorization.replace("Bearer ", "")
    if token != MOBILE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token

# Models
class ChatRequest(BaseModel):
    message: str
    user_id: str = "col"
    response_format: str = "text"  # "text" or "audio" (for optional server TTS)

class ChatResponse(BaseModel):
    agent: str
    response: str
    timestamp: str
    conversation_id: str

# Endpoints
@app.post("/mobile/chat")
async def mobile_chat(
    request: ChatRequest,
    token: str = Depends(verify_token)
):
    """
    Process text message and return agent response
    
    Integration needed:
    1. Route to existing agent orchestrator
    2. Get agent response
    3. Store in memory system
    4. Return formatted response
    """
    # TODO: Replace with actual ARCHER agent routing
    # response = await archer_orchestrator.process(request.message)
    
    return ChatResponse(
        agent="Assistant",  # Replace with actual agent name
        response="This is a placeholder response",  # Replace with actual agent response
        timestamp="2026-03-06T14:30:00Z",
        conversation_id="uuid-here"
    )

@app.get("/mobile/memory/recent")
async def get_recent_memory(
    limit: int = 20,
    token: str = Depends(verify_token)
):
    """
    Get recent conversations
    
    Integration needed:
    1. Query SQLite/ChromaDB for recent conversations
    2. Return formatted list
    """
    # TODO: Query actual memory system
    return {
        "conversations": [
            {
                "id": "uuid-1",
                "timestamp": "2026-03-05T18:00:00Z",
                "agent": "Assistant",
                "summary": "Discussed project deadlines",
                "user_message": "When is the report due?",
                "agent_response": "March 15th"
            }
        ],
        "total": 1
    }

@app.get("/mobile/memory/search")
async def search_memory(
    q: str,
    limit: int = 10,
    token: str = Depends(verify_token)
):
    """
    Semantic search across memory
    
    Integration needed:
    1. Use ChromaDB vector search
    2. Return ranked results
    """
    # TODO: Implement actual semantic search
    return {
        "results": [],
        "query": q,
        "total_results": 0
    }

@app.get("/mobile/health")
async def health_check():
    """Health check (no auth required)"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "agents_available": ["Assistant", "Therapist", "Trainer", "Investment", "Blindspot", "Inventory", "Observer"]
    }
```

**Environment Variables to Add:**
```bash
# In ARCHER .env file
ARCHER_MOBILE_TOKEN=generate-random-secure-token-here
ARCHER_MOBILE_ENABLED=true
```

**Integration Points:**
- Hook `/mobile/chat` to existing agent orchestrator
- Hook `/mobile/memory/*` to existing memory system (ChromaDB, SQLite)
- No new infrastructure needed - just API endpoints

---

## UI/UX Design

### Theme
**Dark Mode (Match ARCHER Desktop)**
- Background: `#1a1a1a`
- Text: `#ffffff`
- User messages: `#2563eb` (blue)
- Agent messages: `#374151` (gray)
- Error: `#ef4444` (red)
- Success: `#10b981` (green)

### Typography
- Font: System default (Roboto on Android)
- Message text: 16sp
- Agent names: 14sp bold
- Timestamps: 12sp light

### Chat Interface Layout

```
┌─────────────────────────────┐
│  ARCHER                  ⚙️  │  ← Header with settings
├─────────────────────────────┤
│                             │
│  ┌─────────────────────┐   │
│  │ What should I       │   │  ← User message (blue)
│  │ focus on today?     │   │
│  └─────────────────────┘   │
│  13:45                      │
│                             │
│   ┌────────────────────┐   │
│   │ Based on your      │   │  ← Agent response (gray)
│   │ schedule...        │   │
│   │                    │   │
│   └────────────────────┘   │
│   Assistant · 13:45        │  ← Agent indicator
│                             │
│  [Scrollable messages]      │
│                             │
├─────────────────────────────┤
│  🎤  Type message...   ➤    │  ← Input bar
└─────────────────────────────┘
   ↑    ↑               ↑
   Mic  Text input     Send
```

### Agent Indicators
Show which agent responded with color-coded badges:
- **Assistant:** Blue circle
- **Therapist:** Purple circle
- **Trainer:** Orange circle
- **Investment:** Gold circle
- **Blindspot:** Red circle
- **Inventory:** Green circle
- **Observer:** Gray circle

---

## Security & Privacy

### Network Security
- **Tailscale VPN required:** App only works when connected to Col's tailnet
- **No public exposure:** Backend never exposed to internet
- **Bearer token auth:** Simple token validation on top of Tailscale

### Data Storage
- **Local only:** All conversation history stored on device (SQLite)
- **No cloud sync:** No data sent to third parties
- **Encrypted at rest:** Use Android's built-in encryption

### Permissions
- **INTERNET:** Required for Tailscale/API calls
- **No microphone permission:** Using system voice input instead
- **No camera permission:** Not needed for mobile app
- **No location permission:** Optional, only if user wants location context

---

## Development Timeline

### Week 1: MVP - Text Chat
**Days 1-2:** Project setup
- Create React Native project
- Set up Tailscale SDK integration
- Configure build system

**Days 3-4:** Core chat functionality
- Implement chat UI
- Connect to `/mobile/chat` endpoint
- Add local SQLite storage
- Handle authentication

**Day 5:** Testing & polish
- Test on Android device
- Fix bugs
- Add connection error handling

**Deliverable:** APK file with working text chat

---

### Week 2: Voice Features
**Days 1-2:** Voice input
- Integrate Android Speech Recognition API
- Add microphone button to UI
- Test dictation flow

**Days 3-4:** Voice output
- Implement System TTS (Tier 1)
- Add playback controls
- Test audio focus handling
- Optional: Add Piper TTS (Tier 2) if time permits

**Day 5:** Testing & polish
- Test voice flow end-to-end
- Handle edge cases (phone calls, notifications)
- Audio quality testing

**Deliverable:** APK with full voice support

---

### Week 3: Memory & Polish
**Days 1-2:** Memory features
- Implement conversation history view
- Add search functionality
- Connect to `/mobile/memory/*` endpoints

**Days 3-4:** Advanced features
- Agent selection
- Settings screen
- TTS mode selector (System/Piper/Cloud)

**Day 5:** Final testing & delivery
- End-to-end testing
- Performance optimization
- Build final release APK

**Deliverable:** Production-ready APK

---

## Testing Checklist

### Functional Tests
- [ ] App connects to ARCHER over Tailscale
- [ ] Token authentication works
- [ ] Can send text messages
- [ ] Receives agent responses
- [ ] Messages persist after app restart
- [ ] Offline mode queues messages
- [ ] Android voice input works
- [ ] TTS playback works
- [ ] Audio focus handled correctly
- [ ] Memory search returns results
- [ ] Conversation history displays correctly
- [ ] Settings persist

### Device Tests
- [ ] Works on Android 10
- [ ] Works on Android 14
- [ ] Works on phone (6" screen)
- [ ] Works on tablet (10" screen)
- [ ] Handles phone rotation
- [ ] Survives low memory conditions
- [ ] Battery usage acceptable

### Network Tests
- [ ] Works over WiFi
- [ ] Works over cellular data
- [ ] Handles network disconnection gracefully
- [ ] Reconnects automatically when network returns
- [ ] Shows clear error when Tailscale not connected

---

## Questions to Resolve Before Starting

**For Col:**

1. **Who implements the backend endpoints?**
   - Option A: Antigravity implements them
   - Option B: Col's team implements, Antigravity just builds mobile app
   - **Please clarify assignment**

2. **React Native or Kotlin?**
   - React Native: Faster (2 weeks), can add iOS later
   - Kotlin: More polished (3 weeks), Android-only
   - **Your preference?**

3. **Voice features in MVP or Phase 2?**
   - With voice from start: 2 weeks
   - Text-only MVP, add voice later: 1 week + 3-5 days
   - **Your preference?**

4. **App distribution method?**
   - Direct APK file (sideload to phone)
   - Google Play internal testing
   - **Your preference?**

5. **Local/Cloud mode toggle?**
   - ARCHER logs show cloud APIs (ElevenLabs, Claude)
   - Should mobile app have mode selector?
   - Or just use whatever ARCHER PC is set to?
   - **Please clarify expected behavior**

---

## Deliverables

### Phase 1 Deliverable (Week 1)
- **File:** `ARCHER-Mobile-v1.0.apk`
- **Features:** Text chat, message persistence, Tailscale connectivity
- **Size:** ~15-25MB

### Phase 2 Deliverable (Week 2)
- **File:** `ARCHER-Mobile-v2.0.apk`
- **Features:** Everything from v1.0 + voice input/output
- **Size:** ~20-30MB (with System TTS) or ~50-75MB (with Piper)

### Phase 3 Deliverable (Week 3)
- **File:** `ARCHER-Mobile-v3.0-RELEASE.apk`
- **Features:** Everything from v2.0 + memory search, settings, polish
- **Size:** ~25-35MB (System TTS) or ~55-85MB (Piper)

### Documentation
- Installation instructions (how to sideload APK)
- User guide (how to use the app)
- Troubleshooting guide (common issues)

---

## Success Criteria

**The app is successful if:**

✅ Col can send text messages to ARCHER from phone  
✅ Col can use voice dictation to interact with ARCHER  
✅ ARCHER's voice responses play on phone  
✅ Conversation history persists and is searchable  
✅ Works reliably over Tailscale from anywhere  
✅ Response time <3 seconds for text chat  
✅ No data leaves Col's private network  
✅ App works offline (after initial Tailscale connection)  

---

## Support & Contact

**Project Owner:** Col  
**Development Team:** Antigravity  
**ARCHER Backend:** FastAPI running on Col's PC (100.96.72.71:8000)  
**Communication Channel:** [Specify: Email, Slack, etc.]

---

## Appendix A: API Reference

### Authentication
All endpoints require Bearer token:
```
Authorization: Bearer <ARCHER_MOBILE_TOKEN>
```

### Base URL
```
http://100.96.72.71:8000
```
(Only accessible via Tailscale VPN)

### Endpoints

**POST /mobile/chat**
- Purpose: Send message to ARCHER, get response
- Body: `{ message: string, user_id: string, response_format: "text" }`
- Response: `{ agent: string, response: string, timestamp: string, conversation_id: string }`

**GET /mobile/memory/recent?limit=20**
- Purpose: Get recent conversations
- Response: `{ conversations: [...], total: number }`

**GET /mobile/memory/search?q=query&limit=10**
- Purpose: Search conversation history
- Response: `{ results: [...], query: string, total_results: number }`

**GET /mobile/health**
- Purpose: Health check (no auth)
- Response: `{ status: "healthy", version: string, agents_available: [...] }`

---

## Appendix B: Piper TTS Integration

### Model Download
```bash
# Recommended voice model
curl -L -o app/src/main/assets/en_US-amy-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx

# Model size: ~25MB
```

### Gradle Dependencies (Kotlin)
```gradle
dependencies {
    implementation 'ai.onnxruntime:onnxruntime-android:1.15.0'
}
```

### React Native Integration
```bash
npm install react-native-onnxruntime
# Bundle model in assets/
```

### Usage Example
```kotlin
val piper = PiperTTS(context)
piper.loadModel("en_US-amy-medium.onnx")
piper.synthesize("Hello from ARCHER") { audioData ->
    val player = MediaPlayer()
    player.setDataSource(audioData)
    player.prepare()
    player.start()
}
```

---

**Document Version:** 1.0  
**Last Updated:** March 6, 2026  
**Status:** Ready for development

---

**READY TO START? Please answer the 5 questions in "Questions to Resolve Before Starting" section and we can begin immediately.**
