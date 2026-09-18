# ARCHER Technical Report: First-Run Voice Authentication Enrollment

**Item Reference**: Live Testing Item 5  
**Target Module**: [`src/archer/voice/auth.py`](file:///d:/ARCHER_9/src/archer/voice/auth.py)  
**Status**: Enrollment Workflow Specification  

---

## 1. Problem Statement & Incident Analysis

### Concrete Incident:
Following a false wake word trigger on TV audio, ARCHER accepted TV dialogue as valid user speech and held a full one-sided conversation for several minutes while unattended.

### Root Cause Analysis:
The speaker verification module (`VoiceAuthenticator` in `src/archer/voice/auth.py`) uses SpeechBrain's `ECAPA-TDNN` model to verify speaker identity. However:
1. No voice enrollment profile had been recorded (`self._enrolled_embedding` was `None`).
2. As a fallback mechanism, `VoiceAuthenticator.verify()` returned `True, 1.0` (granting full access) whenever `is_enrolled()` was `False`.
3. Consequently, TV dialogue and any background voices were treated as authenticated user speech, granting unrestricted access to memory, tools, and conversation history.

---

## 2. Enrollment Architecture & Workflow

To lock down system access and restrict unauthenticated speakers to Guest Mode, implement a first-run voice enrollment wizard.

### Step 1: Interactive Enrollment UX Flow
Create an interactive enrollment routine (`python -m archer enroll-voice` or a setup modal in the GUI):
1. **Instruction**: Prompt the user to sit at their standard working position with their target microphone.
2. **Recording Phrases**: Prompt the user to read 3 distinct calibration sentences:
   - Phrase 1: *"Hey ARCHER, this is Colby authenticating my voice profile."*
   - Phrase 2: *"System verification and executive assistant access granted."*
   - Phrase 3: *"Set up personal memory layers and voice authorization."*

### Step 2: Embedding Generation (SpeechBrain ECAPA-TDNN)
1. Capture ~3–5 seconds of 16 kHz mono PCM audio per phrase.
2. Pass each normalized audio tensor through `VoiceAuthenticator._model.encode_batch()`:
   ```python
   import torch
   import numpy as np

   embeddings = []
   for sample_bytes in audio_samples:
       audio_array = np.frombuffer(sample_bytes, dtype=np.int16).astype(np.float32) / 32768.0
       audio_tensor = torch.tensor(audio_array).unsqueeze(0)
       embedding = self._model.encode_batch(audio_tensor).squeeze().numpy()
       embeddings.append(embedding)

   # Compute centroid embedding vector (192 dimensions)
   enrolled_embedding = np.mean(embeddings, axis=0)
   ```

### Step 3: SQLite Database Persistence
Persist the enrolled 192-dimensional vector in the local SQLite database (`openmemory.db`):
```sql
CREATE TABLE IF NOT EXISTS voice_enrollment (
    user_id TEXT PRIMARY KEY,
    embedding TEXT NOT NULL,
    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO voice_enrollment (user_id, embedding)
VALUES ('primary', '<json_serialized_array>');
```

---

## 3. Strict Verification & Guest Mode Routing

Once enrollment is complete:

1. **Cosine Similarity Verification**:
   For every voice turn following a wake word activation:
   $$\text{similarity} = \frac{\mathbf{e}_{\text{sample}} \cdot \mathbf{e}_{\text{enrolled}}}{\|\mathbf{e}_{\text{sample}}\| \|\mathbf{e}_{\text{enrolled}}\|}$$
   
2. **Threshold Enforcement**:
   - Verification Threshold: **`0.85`** cosine similarity.
   
3. **Action on Verification Failure (TV / Guest Audio)**:
   - **Guest Mode Activation**:
     - Deny access to OpenMemory search, SQLite personal records, and OS action tools.
     - Respond in neutral tone with basic read-only info (e.g. time, weather, system status).
   - **Unattended TV Audio Mitigation**:
     - If the similarity score is $<0.70$ (indicating completely distinct speaker/TV dialogue), drop the turn silently without generating a response, terminating the pipeline immediately.
