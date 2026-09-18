# ARCHER Technical Report: Custom Wake Word Model Fine-Tuning & Training

**Item Reference**: Live Testing Item 4  
**Target Module**: [`src/archer/voice/wake_word.py`](file:///d:/ARCHER_9/src/archer/voice/wake_word.py)  
**Status**: Architecture & Training Specification  

---

## 1. Problem Statement & Root Cause

During live testing, the generic openWakeWord pretrained models (`alexa`, `hey_jarvis`, `hey_mycroft`, `hey_rhasspy`) false-triggered on TV audio three times in a single session at low confidence scores (0.20 – 0.31). Concurrently, actual user speech occasionally required multiple repetitions to trigger detection.

### Root Cause Analysis:
1. **Generic Acoustic Calibration**: The pretrained models were trained on synthetic or generalized datasets that lack acoustic calibration for:
   - The user's specific vocal timbre, pitch, and accent.
   - The user's specific microphone hardware (frequency response, noise floor).
   - The specific room acoustic profile (reverberation time, distance to microphone, background fan/HVAC noise).
2. **Multi-Model Noise Susceptibility**: Running 4 separate wake word models concurrently in `WakeWordDetector` increases the statistical probability of false positives on rich audio sources like television dialogue or podcasts.

---

## 2. Dataset Collection Specification

To train a dedicated `hey_archer.onnx` model optimized for this setup, collect two datasets:

### A. Positive Samples (Target Voice)
- **Sample Count**: 30–50 distinct recordings of the phrase *"Hey ARCHER"*.
- **Acoustic Diversity**:
  - Distance: Near-field (0.5m), mid-field (1.5m), far-field (3m).
  - Energy & Tone: Normal speaking level, quiet/whispered tone, authoritative/projected tone.
  - Speech Rate: Normal cadence, fast cadence, slightly drawn-out cadence.
- **Format**: 16 kHz, 16-bit PCM, Mono `.wav` files.

### B. Negative Samples (Environment & Background Audio)
- **Room Background Noise**: 10 minutes of ambient room audio recorded with the target microphone (silence, keyboard typing, chair movement, HVAC noise).
- **TV & Speech Noise**: 15–30 minutes of continuous TV dialogue, podcasts, and video audio recorded from the room speakers.

### C. Synthetic Data Augmentation
Using `openwakeword.data` utilities and local TTS engines (Kokoro / Piper):
- Generate 1,000+ synthetic clips of *"Hey ARCHER"* using diverse TTS voice embeddings.
- Apply Room Impulse Response (RIR) convolution filters to simulate room reverberation.
- Add pitch shifting (±5%) and speed perturbations (0.9x to 1.1x).

---

## 3. Feature Extraction & Model Training Pipeline

1. **Audio Preprocessing**:
   - Sample Rate: 16,000 Hz.
   - Spectrogram: 80-channel log-mel filterbanks.
   - Frame Length: 80 ms window, 10 ms hop size.

2. **Model Architecture**:
   - Lightweight 2-layer Fully Connected Neural Network or Depthwise Separable CNN.
   - Target Size: <500 KB ONNX binary to guarantee <5 ms CPU inference latency per audio frame.

3. **Loss Function & Hard Negative Mining**:
   - Binary Cross-Entropy with Focal Loss ($\gamma = 2.0$) to heavily penalize false positives on TV speech samples.
   - High ratio of negative background samples to positive samples (10:1 ratio during training).

---

## 4. Model Export & System Integration

1. **Export Trained Model**:
   - Save the trained PyTorch checkpoint and convert to ONNX format: `data/models/openwakeword/hey_archer.onnx`.

2. **Update `WakeWordDetector`**:
   In `src/archer/voice/wake_word.py`:
   ```python
   # Load dedicated custom hey_archer model
   self._model = Model(
       wakeword_models=["data/models/openwakeword/hey_archer.onnx"],
       inference_framework="onnx",
   )
   ```

3. **Threshold Adjustment**:
   - Elevate the confidence threshold in `config.py` (`wake_word_threshold`) from the current generic `0.20` up to **`0.65 – 0.75`**.
   - A single, highly calibrated `hey_archer` model operating at 0.70 confidence threshold will eliminate low-confidence TV false triggers (which scored 0.20–0.31) while maintaining >95% recall for true user utterances.
