# ARCHER System Update - FINAL SPECIFICATION
**Date**: February 26, 2026  
**For**: Antigravity Development Team  
**Status**: Ready for Implementation

---

## 🚨 CRITICAL DECISION: MentalQLM Status

**BLOCKER DISCOVERED**: MentalQLM GitHub repo contains TRAINING CODE ONLY - no pre-trained weights available.

**Col's Status**:
- ✅ Python 3.10+ installed
- ✅ PyTorch installed
- ❓ Transformers library unknown (needs: `pip install transformers`)
- ❌ NO mental health datasets
- ❌ NO pre-trained MentalQLM model available

**DECISION**: Use **Qwen 3.5 397B (NVIDIA NIM) + Psychology RAG** instead

**Rationale**:
- MentalQLM requires training from scratch (20-40 GPU hours)
- No datasets available
- Qwen 3.5 397B is FREE, available immediately
- Can load psychology knowledge into RAG for clinical expertise
- Meets Col's requirement: "Profile me first, establish baseline"

---

## FINAL AGENT ARCHITECTURE

### **5 Agents (Finance DELETED Permanently)**

| Agent | Purpose | Initiation | Model | Privacy |
|-------|---------|------------|-------|---------|
| **Assistant** | General tasks | 50/50 | Kimi K2.5 (NVIDIA) | Cloud OK |
| **Therapist** | Psychology, emotional intelligence | Agent | Qwen 3.5 397B + Psych RAG | Cloud OK |
| **Trainer** | Health/wellness expert | Agent | Llama 3.3 70B + Health RAG | Cloud OK |
| **Investment** | Markets ONLY (NO budgeting) | Agent | Qwen 3.5 397B | Cloud OK |
| **Observer** | Pattern detection, clutter, inventory | Agent | **Qwen2-VL-7B LOCAL** | **100% Local** |

---

## AGENT SPECIFICATIONS

### **1. THERAPIST - Profiling & Intervention**

**Personality**: "Both confrontational AND clinical" (Col's answer)

**Examples**:
```
Confrontational: "You said you'd sleep early. It's 12:30 and you're on YouTube. What's actually going on?"

Clinical: "I've observed sleep avoidance patterns for 4 consecutive nights. This may indicate stress coping mechanisms."

Combined: "Fourth night staying up late when you said you wouldn't. This pattern often indicates anxiety avoidance. What are you avoiding thinking about?"
```

**Profiling Requirement** (Col: "Profile me first, establish baseline"):

**Phase 1 - Initial Profiling (Week 1-2)**:
```python
PROFILING_QUESTIONS = [
    "Before I can help, I need to understand your baseline. On a scale of 1-10, how would you describe your typical stress levels?",
    "Tell me about your sleep patterns in a normal week.",
    "When you're stressed, what do you tend to do?",
    "How often do you typically socialize or have visitors?",
    "What does a 'good day' look like for you emotionally?"
]
```

**Phase 2 - Baseline Observation (Week 3-4)**:
- Therapist monitors Observer data but does NOT intervene yet
- Collects behavioral baseline metrics
- Establishes Col's personal norms (not generic health standards)

**Phase 3 - Active Intervention (Week 5+)**:
- Intervenes when deviations from Col's baseline detected
- "Always intervene" when concerning patterns appear (Col's answer)
- No cooldown restrictions initially (TBD later)

**Observer Integration**:
- Observer pushes updates to database
- Therapist polls for new data (Observer doesn't trigger Therapist directly)
- Therapist analyzes updates as they occur

**Model Configuration**:
```python
THERAPIST_CONFIG = {
    "model": "nvidia/qwen/qwen3.5-397b-a17b",
    "cost": "FREE",
    "knowledge_base": [
        "CBT_therapy_guide.pdf",
        "behavioral_psychology.pdf",
        "emotional_intelligence_framework.pdf"
    ],
    "intervention_trigger": "always_on_concerning_patterns",
    "tone": "confrontational_and_clinical_blend"
}
```

---

### **2. TRAINER - Motivationally Stern Expert**

**Personality**: "Motivationally stern" (Col's answer)

**Intervention Philosophy**: "It should base interventions on what is healthy. It's supposed to be the expert." (Col's answer)

**Key**: NO fixed thresholds (like ">2hr sedentary"). Trainer uses health science expertise to determine appropriate intervention.

**Examples**:
```
Motivational: "Four days of consistency—that's real discipline. Keep this momentum."

Stern: "You skipped three workouts this week. Your baseline is 5/week. What's the excuse?"

Motivationally Stern: "I get it—life gets in the way. But you committed to this for a reason. Three days off track means you hit it twice as hard tomorrow. No excuses, just action."
```

**Model Configuration**:
```python
TRAINER_CONFIG = {
    "model": "nvidia/meta/llama-3.3-70b-instruct",
    "knowledge_base": [
        "exercise_physiology.pdf",
        "nutrition_science.pdf",
        "habit_formation_research.pdf"
    ],
    "intervention_philosophy": "expert_determines_thresholds",
    "tone": "motivationally_stern"
}
```

---

### **3. INVESTMENT - Markets Only, Recommendations**

**Scope**: "Markets ONLY" (Col: "No budgeting")

**NO budgeting features**:
- ❌ Bank APIs
- ❌ Receipt scanning
- ❌ Spending tracking
- ❌ Budget alerts
- ❌ Expense categorization

**Capabilities**:
- ✅ Market analysis
- ✅ Portfolio recommendations
- ✅ Volatility alerts
- ✅ News impact analysis
- ✅ Risk assessment

**Intervention Trigger**: "Market volatility affecting portfolio" (Col's answer)

**Trade Execution**: "Recommendations only" (Col's answer)

**Model Configuration**:
```python
INVESTMENT_CONFIG = {
    "model": "nvidia/qwen/qwen3.5-397b-a17b",
    "scope": "market_analysis_ONLY",
    "no_budgeting": True,
    "no_bank_integration": True,
    "recommendations_only": True,
    "intervention_trigger": "market_volatility_affecting_portfolio"
}
```

---

### **4. OBSERVER - 100% Local Vision**

**Privacy**: "Vision should be local" (Col's answer)

**Model**: Qwen2-VL-7B (local via Ollama)
- VRAM: 4-5GB
- 100% local (no cloud API calls)
- Webcam analysis every 30 seconds

**Therapist Integration**:
- Observer pushes behavioral data to local database
- Therapist monitors database for updates (Observer doesn't trigger Therapist)
- "The observer shouldn't trigger the therapist, the therapist should monitor for any updates and analyze as updates occur." (Col's answer)

**Model Configuration**:
```python
OBSERVER_CONFIG = {
    "vision_model": "qwen2-vl-7b",
    "deployment": "ollama_local",
    "vram": "4-5GB",
    "privacy": "100%_local_no_cloud",
    "analysis_frequency": "every_30_seconds",
    "database": "local_sqlite",
    "therapist_integration": {
        "mode": "push_to_database",
        "therapist_polls": True,
        "observer_triggers": False
    }
}
```

---

## PRIVACY & DATA HANDLING

**Critical Requirements** (Col's answers):

1. **"There shouldn't be any cloud logging in general"**
   - All conversation logs: LOCAL ONLY
   - All memory databases: LOCAL ONLY
   - No cloud backups

2. **"Vision should be local"**
   - Observer MUST use local vision model
   - NO cloud vision APIs

3. **Memory Decay**: "No decay if avoidable"
   - Disable temporal decay in OpenMemory
   - Permanent retention

**Configuration**:
```python
PRIVACY_CONFIG = {
    "cloud_logging": False,
    "cloud_backups": False,
    "redis": "localhost:6379",
    "openmemory": "data/openmemory.db (local)",
    "markdown_logs": "data/memory/*.md (local)",
    "observer_vision": "100%_local",
    "memory_decay": False,
    "retention": "permanent"
}
```

---

## TTS - CRITICAL PRIORITY

**Status**: "Immediate" (Col's answer)

**CRITICAL**: "Pyttsx3 is NEVER an option and should be firmly documented as such." (Col's answer)

**VRAM Budget**: 8GB reserved (no more)

**Evaluation Status**: "Evaluating" (Col's answer)

**Antigravity Task**:
1. Research local TTS options (KittenTTS, Coqui, F5-TTS, etc.)
2. Test VRAM requirements (MUST be ≤8GB)
3. Test voice quality
4. Test latency (<500ms first-word)
5. Provide recommendation report

**Deliverable**: Report ranking 3 TTS options by quality/VRAM/latency

---

## NVIDIA NIM SETUP INSTRUCTIONS

**For Col - Verification Process**:

### **Step 1: Check NVIDIA Account**
```bash
# Go to: https://build.nvidia.com
# Click "Sign In" (top right)
# If you don't remember password, click "Forgot Password"
```

### **Step 2: Get API Key**
```bash
# Once logged in:
1. Go to https://build.nvidia.com/models
2. Click any model (e.g., "Kimi K2.5")
3. Click "Get API Key" button
4. Click "Generate Key"
5. Copy the key (starts with "nvapi-")
```

### **Step 3: Check Usage Limits**
```bash
# In your account dashboard:
1. Look for "Usage" or "Quotas" section
2. Note daily/monthly request limits
3. Document what you find
```

### **Step 4: Add to ARCHER**
```bash
# Edit .env file in ARCHER directory:
NVIDIA_API_KEY=nvapi-YOUR_KEY_HERE
```

**Fallback Plan**: If limits exceeded → "Qwen" (Col's answer)

---

## VRAM ALLOCATION

**Hardware**: RTX 5080 16GB (single GPU)

**Can offload to RAM**: Yes (256GB available)

**Budget**:
```
Total: 16GB

Allocations:
- Observer (Qwen2-VL-7B local): 4-5GB
- Future TTS: 8GB reserved
- Buffer: 3-4GB

Cloud models (NVIDIA NIM): 0GB (API-based)
Local Qwen fallback: 5-6GB (only when NVIDIA unavailable)
```

**Confirmed** (Col: "Yes to all 3 questions"):
- Single GPU for now
- Can revisit budget if hit 8GB before TTS
- OK to offload to system RAM if needed

---

## IMPLEMENTATION PHASES

### **Phase 1: Finance Agent Deletion** ⚡ IMMEDIATE

**Time**: 2-3 hours

**Tasks**:
1. Delete `/src/archer/agents/finance/` directory
2. Remove `_FINANCE_KEYWORDS` from orchestrator
3. Update agent list to 5 (remove Finance)
4. Update Investment SOUL.md (markets only, no budgeting)
5. Remove all Finance references from docs

**QA Gate**:
- [ ] Zero Finance references in codebase
- [ ] Investment scope = markets only
- [ ] 5 agents confirmed (not 6)

---

### **Phase 2: Observer Local Vision** ⚡ HIGH PRIORITY

**Time**: 4-6 hours

**Tasks**:
1. Install Qwen2-VL-7B via Ollama
2. Configure local webcam analysis
3. Set up local database for behavioral signals
4. Implement Observer → Database push
5. Verify 100% local (NO cloud calls)

**QA Gate**:
- [ ] Qwen2-VL runs locally
- [ ] VRAM usage 4-5GB
- [ ] Webcam analysis functional
- [ ] NO cloud API calls (verify with network monitor)
- [ ] Data stored locally only

---

### **Phase 3: Therapist with Profiling** ⚡ HIGH PRIORITY

**Time**: 6-8 hours

**Tasks**:
1. Implement Qwen 3.5 397B via NVIDIA NIM
2. Load psychology knowledge into RAG
3. Create profiling questionnaire system
4. Build baseline establishment logic
5. Implement confrontational+clinical response blending
6. Set up database polling (not Observer-triggered)

**QA Gate**:
- [ ] Profiling questions engage appropriately
- [ ] Baseline metrics stored locally
- [ ] Response tone = confrontational + clinical
- [ ] Therapist polls database (not triggered by Observer)
- [ ] "Always intervene" logic works

---

### **Phase 4: NVIDIA NIM Integration** ⚡ MEDIUM PRIORITY

**Time**: 4-6 hours

**Tasks**:
1. Configure NVIDIA API key
2. Add all NVIDIA NIM models to config
3. Implement intelligent routing
4. Test fallback to local Qwen
5. Verify $0 cost (within free tier)

**QA Gate**:
- [ ] All NVIDIA models accessible
- [ ] Routing works correctly
- [ ] Fallback to Qwen functional
- [ ] Free tier limits documented
- [ ] Cost = $0

---

### **Phase 5: TTS Research** ⚡ IMMEDIATE

**Time**: 4-6 hours

**Antigravity Deliverable**:

Report with 3 TTS options:
1. Option name
2. VRAM requirements
3. Voice quality (1-10)
4. Latency measurements
5. Pros/cons
6. Recommendation

**CRITICAL**: Document that pyttsx3 is NEVER acceptable

---

### **Phase 6: Integration Testing** ⚡ FINAL

**Time**: 8-12 hours

**Tasks**:
1. Test all 5 agents independently
2. Test Observer → Therapist pipeline
3. Test proactive interventions
4. Verify memory system works
5. Monitor VRAM usage
6. Validate voice pipeline unchanged
7. Confirm $0 API costs
8. End-to-end testing

**Test Scenarios**: Antigravity creates (Col: "You decide")

**Memory Graph Test**: Synthetic data OK (Col: "test synthetic test data should be fine, right?")

**QA Gate**:
- [ ] All agents respond appropriately
- [ ] Therapist profiling works
- [ ] Observer local vision works
- [ ] Investment provides market recommendations
- [ ] Trainer motivationally stern
- [ ] Total VRAM ≤8GB (excluding TTS)
- [ ] Voice pipeline functional
- [ ] NO API charges
- [ ] Memory persists correctly
- [ ] NO cloud logging

---

## ROLLBACK PROCEDURE

**Tolerance**: "OK to have ARCHER offline for a few hours during updates" (Col's answer)

**Fallback**: "NOT acceptable to fall back to Claude for Therapist" (Col's answer)

**Procedure**:
```bash
# If critical failure:
1. Stop all services
2. Git checkout previous commit
3. Restore database backups
4. Restart ARCHER
5. Document failure
```

---

## CRITICAL SUCCESS CRITERIA

### **Must-Have**:
1. ✅ Finance agent deleted (zero traces)
2. ✅ Therapist profiles before interventions
3. ✅ Observer 100% local (privacy)
4. ✅ Investment = markets only (NO budgeting)
5. ✅ VRAM ≤8GB (reserve for TTS)
6. ✅ $0 API costs
7. ✅ Voice pipeline unchanged
8. ✅ NO cloud logging
9. ✅ pyttsx3 NEVER used (documented)
10. ✅ TTS research completed

---

## FINAL CONFIGURATION SUMMARY

```python
ARCHER_FINAL_CONFIG = {
    "agents": {
        "assistant": "nvidia/moonshotai/kimi-k2.5",
        "therapist": "nvidia/qwen/qwen3.5-397b-a17b + psych_RAG",
        "trainer": "nvidia/meta/llama-3.3-70b-instruct + health_RAG",
        "investment": "nvidia/qwen/qwen3.5-397b-a17b",
        "observer": "qwen2-vl-7b (LOCAL)"
    },
    
    "privacy": {
        "cloud_logging": False,
        "cloud_backups": False,
        "observer_vision": "100%_local",
        "memory_decay": False
    },
    
    "vram_budget": {
        "observer": "4-5GB",
        "tts_reserved": "8GB",
        "buffer": "3-4GB",
        "total": "16GB"
    },
    
    "cost": "$0/month (NVIDIA NIM free tier)",
    
    "tts": {
        "current": "NONE",
        "forbidden": "pyttsx3",
        "status": "research_in_progress",
        "priority": "immediate"
    }
}
```

---

## ANTIGRAVITY CHECKLIST

**Before Starting**:
- [ ] Understand all 5 agent responsibilities
- [ ] Confirm Finance deletion is permanent
- [ ] Understand Therapist profiling requirement
- [ ] Know Observer MUST be local
- [ ] Understand Investment ≠ budgeting
- [ ] Read this entire spec

**During Implementation**:
- [ ] Follow QA gates strictly
- [ ] Test Observer privacy (network monitor)
- [ ] Monitor VRAM continuously
- [ ] Document deviations

**At Completion**:
- [ ] Validation report
- [ ] VRAM usage documentation
- [ ] $0 API cost confirmation
- [ ] TTS research report
- [ ] Known issues list

---

**Timeline**: "This is being built by AI, so timeline should not be addressed nor a consideration" (Col's answer)

**Quality**: Over speed. Pass ALL QA gates.

**Ready to begin Phase 1.**
