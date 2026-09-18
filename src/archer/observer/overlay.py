"""
ARCHER Frame Annotation Overlay.

Draws detection results (person bounding boxes and identity labels)
onto video frames for GUI display. Operates on BGR numpy arrays
using OpenCV drawing primitives.

Design rules:
- Pure function: frame in, annotated frame out.
- Never mutates the input frame (works on a copy).
- Gracefully handles missing or malformed data.
"""

from __future__ import annotations

import numpy as np


def draw_annotations(
    frame: np.ndarray,
    detections: list[dict],
) -> np.ndarray:
    """
    Draw detection annotations onto a frame.

    Args:
        frame: BGR numpy array (OpenCV format).
        detections: List of detection dicts, each with:
            - "type": "person"
            - "person_id": str ("Col" or "Person_N")
            - "is_known": bool
            - "box": [x, y, w, h]
            - "confidence": float

    Returns:
        Annotated frame (new array, input is not mutated).
    """
    if not detections:
        return frame

    import cv2  # noqa: lazy import to match project pattern

    annotated = frame.copy()

    for det in detections:
        det_type = det.get("type", "")
        if det_type == "person":
            _draw_person_box(annotated, det, cv2)

    return annotated


def _draw_person_box(frame: np.ndarray, det: dict, cv2) -> None:
    """Draw a person bounding box with identity label."""
    box = det.get("box", [])
    if len(box) < 4:
        return
    x, y, w, h = box[:4]
    if w <= 0 or h <= 0:
        return

    person_id = det.get("person_id", "Person")
    is_known = det.get("is_known", False)
    confidence = det.get("confidence", 0.0)

    # Green for known (Col), Orange for unrecognized visitors
    color = (0, 200, 0) if is_known else (0, 140, 255)

    # Draw rectangle
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

    # Draw label above the box
    label = f"{person_id} ({confidence:.0%})" if confidence > 0 else person_id
    _draw_label(frame, label, (x, y - 8), color, cv2)


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
