# ARCHER Technical Reports Index

This directory contains technical reports and architectural specifications resulting from live testing and system optimization.

---

## Reports Index

1. [**Custom Wake Word Model Fine-Tuning & Training**](file:///d:/ARCHER_9/docs/reports/wake_word_training.md)
   - *Item 4*: Technical report detailing dataset collection (user voice, room acoustics, TV noise), openWakeWord ONNX feature extraction pipeline, synthetic RIR augmentation, and threshold tuning (0.65–0.75) to eliminate TV false positives.

2. [**First-Run Voice Authentication Enrollment**](file:///d:/ARCHER_9/docs/reports/voice_auth_enrollment.md)
   - *Item 5*: Technical report documenting the 3-phrase first-run enrollment wizard, SpeechBrain ECAPA-TDNN embedding generation, SQLite persistence, and strict 0.85 cosine similarity verification to restrict unauthenticated TV dialogue to Guest Mode or silent drop.

3. [**Disambiguating User Self-Expression vs. Quoting / Referencing**](file:///d:/ARCHER_9/docs/reports/stance_keyword_disambiguation.md)
   - *Item 7*: Technical report evaluating 4 options (spaCy dependency parsing, quote-stripping regex heuristics, zero-shot intent classification, and dialog-state tracking) to prevent false stance escalation when users quote or reference emotion keywords.
