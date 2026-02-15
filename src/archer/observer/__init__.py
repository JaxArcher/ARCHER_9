"""
ARCHER Observer Module (Phase 3).

Ambient observation subsystem that monitors the user's environment
through a webcam feed and publishes OBSERVATION events when significant
state changes are detected (posture, emotion, food, sedentary alerts).

Threading model:
- Webcam capture runs in a dedicated daemon thread.
- Frame analysis is dispatched to containerized services (MediaPipe,
  DeepFace) via HTTP to avoid dependency conflicts.
- All results are published through the event bus — the Observer never
  touches GUI widgets or agent code directly.
"""
