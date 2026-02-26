"""
ARCHER Frame Annotation Overlay.

Draws detection results (face bounding boxes, pose landmarks, labels)
onto video frames for GUI display. Operates on BGR numpy arrays
using OpenCV drawing primitives.

Design rules:
- Pure function: frame in, annotated frame out.
- Never mutates the input frame (works on a copy).
- Gracefully handles missing or malformed data.
"""

from __future__ import annotations

import numpy as np


# Emotion → BGR color mapping
_EMOTION_COLORS: dict[str, tuple[int, int, int]] = {
    "happy": (0, 200, 0),       # green
    "neutral": (200, 150, 50),   # blue-ish
    "sad": (0, 0, 200),          # red
    "angry": (0, 0, 220),        # red
    "fear": (0, 140, 255),       # orange
    "surprise": (0, 220, 220),   # yellow
    "disgust": (50, 0, 180),     # dark red
}

# Skeleton connections: pairs of landmark indices to draw lines between.
# MediaPipe key landmarks: 11,12 (shoulders), 23,24 (hips), 25,26 (knees), 27,28 (ankles)
_SKELETON_CONNECTIONS: list[tuple[int, int]] = [
    (11, 12),  # shoulder to shoulder
    (11, 23),  # left shoulder to left hip
    (12, 24),  # right shoulder to right hip
    (23, 24),  # hip to hip
    (23, 25),  # left hip to left knee
    (24, 26),  # right hip to right knee
    (25, 27),  # left knee to left ankle
    (26, 28),  # right knee to right ankle
]


def draw_annotations(
    frame: np.ndarray,
    detections: list[dict],
) -> np.ndarray:
    """
    Draw detection annotations onto a frame.

    Args:
        frame: BGR numpy array (OpenCV format).
        detections: List of detection dicts, each with:
            - "type": "face" | "pose"
            - For "face": "face_region" dict, "dominant_emotion" str, "confidence" float
            - For "pose": "landmarks" list, "posture" str, "is_hunched" bool

    Returns:
        Annotated frame (new array, input is not mutated).
    """
    if not detections:
        return frame

    import cv2  # noqa: lazy import to match project pattern

    annotated = frame.copy()

    for det in detections:
        det_type = det.get("type", "")
        if det_type == "face":
            _draw_face_box(annotated, det, cv2)
        elif det_type == "pose":
            _draw_pose_landmarks(annotated, det, cv2)

    return annotated


def _draw_face_box(frame: np.ndarray, det: dict, cv2) -> None:
    """Draw a face bounding box with emotion label."""
    region = det.get("face_region", {})
    x = region.get("x", 0)
    y = region.get("y", 0)
    w = region.get("w", 0)
    h = region.get("h", 0)
    if w <= 0 or h <= 0:
        return

    emotion = det.get("dominant_emotion", "neutral")
    confidence = det.get("confidence", 0.0)
    color = _EMOTION_COLORS.get(emotion, (200, 150, 50))

    # Draw rectangle
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

    # Draw label above the box
    label = f"{emotion} {confidence:.0%}"
    _draw_label(frame, label, (x, y - 8), color, cv2)


def _draw_pose_landmarks(frame: np.ndarray, det: dict, cv2) -> None:
    """Draw pose landmark circles and skeleton lines."""
    landmarks = det.get("landmarks", [])
    if not landmarks:
        return

    h, w = frame.shape[:2]
    is_hunched = det.get("is_hunched", False)
    color = (0, 0, 220) if is_hunched else (0, 180, 0)  # red if hunched, green otherwise

    # Build index→pixel lookup
    lm_map: dict[int, tuple[int, int]] = {}
    for lm in landmarks:
        idx = lm.get("index", -1)
        vis = lm.get("visibility", 0.0)
        if idx < 0 or vis < 0.3:
            continue
        px = int(lm["x"] * w)
        py = int(lm["y"] * h)
        lm_map[idx] = (px, py)
        # Draw landmark circle
        cv2.circle(frame, (px, py), 5, color, -1)

    # Draw skeleton connections
    for idx_a, idx_b in _SKELETON_CONNECTIONS:
        if idx_a in lm_map and idx_b in lm_map:
            cv2.line(frame, lm_map[idx_a], lm_map[idx_b], color, 2)

    # Draw posture label near top-center of body
    posture = det.get("posture", "")
    if posture and 11 in lm_map:
        label = f"{'HUNCHED ' if is_hunched else ''}{posture}"
        _draw_label(frame, label, (lm_map[11][0], lm_map[11][1] - 15), color, cv2)


def _draw_label(
    frame: np.ndarray,
    text: str,
    pos: tuple[int, int],
    color: tuple[int, int, int],
    cv2,
) -> None:
    """Draw a text label with a dark background rectangle for readability."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.5
    thickness = 1

    (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
    x, y = pos
    # Clamp y so the label doesn't go above the frame
    y = max(th + 4, y)

    # Background rectangle
    cv2.rectangle(
        frame,
        (x, y - th - 4),
        (x + tw + 4, y + 2),
        (0, 0, 0),
        -1,
    )
    # Text
    cv2.putText(frame, text, (x + 2, y - 2), font, scale, color, thickness, cv2.LINE_AA)
