"""
ARCHER Observer Frame Analyzers.

Each analyzer receives a frame (numpy array in BGR format) and returns
structured detection results. The analyzers dispatch to containerized
services (MediaPipe, DeepFace) via HTTP to isolate dependency conflicts.

All analyzers are non-blocking and gracefully degrade if services
are unavailable.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from loguru import logger

from archer.config import get_config


@dataclass
class DetectionResult:
    """A single detection from a frame analyzer."""

    source: str          # 'webcam', 'mic', 'system'
    event_type: str      # e.g. 'emotion', 'posture', 'food', 'sedentary'
    confidence: float    # 0.0 - 1.0
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


def _frame_to_jpeg_b64(frame: np.ndarray, quality: int = 70) -> str:
    """Encode a BGR frame as base64 JPEG for HTTP dispatch."""
    try:
        import cv2
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer.tobytes()).decode('utf-8')
    except Exception as e:
        logger.error(f"Frame encoding failed: {e}")
        return ""


class SceneAnalyzer:
    """
    Semantic scene understanding via local Vision Language Model (Qwen2-VL).

    Sends JPEG frames to a local Ollama instance for identification of objects,
    scene description, and behavioral pattern detection. This is the Tier 1
    Observer layer, ensuring 100% local vision privacy as required by the spec.

    Runs on a configurable cooldown (default 30s) to manage VRAM/CPU load.
    """

    def __init__(self, cooldown_seconds: float = 30.0) -> None:
        self._config = get_config()
        self._cooldown = cooldown_seconds
        self._last_analysis: float = 0.0
        self._available = True
        self._last_check: float = 0.0
        self._check_interval = 60.0
        self._latest_description: str = ""
        self._model = self._config.observer_model
        self._ollama_url = f"{self._config.observer_ollama_url}/api/generate"

    def analyze(self, frame: np.ndarray, camera_source: str = "webcam", room: str = "main_office") -> list[DetectionResult]:
        """
        Analyze a frame using local Qwen2-VL on CPU Ollama.

        Returns a DetectionResult with scene description, room location, and structured objects.
        """
        now = time.monotonic()

        if now - self._last_analysis < self._cooldown:
            return []

        if not self._is_available() or not self._config.use_local_vision:
            return []

        try:
            import httpx
            import json

            b64_frame = _frame_to_jpeg_b64(frame, quality=60)
            if not b64_frame:
                return []

            prompt = (
                "Analyze this frame. Focus on person behavior and actions (e.g. sitting at desk, cooking, on phone, pacing, working) "
                "as well as notable objects. Respond with valid JSON strictly matching this structure:\n"
                "{\n"
                '  "description": "2-3 concise sentences of what the person is doing and the scene context",\n'
                '  "objects": [{"object_type": "item_name", "confidence": 0.9, "location": "desk"}]\n'
                "}"
            )

            # 60s, not 30s — a cold vision-model load (CUDA kernel
            # compilation on first inference after the model has been idle
            # past its keep_alive window) can take 20-30s on its own before
            # generation starts. See core_agent.py's identical fix for the
            # full story; this call hits the same Ollama instance and was
            # very likely the reason the GUI's Observer Feed panel has
            # been stuck on "Waiting for analysis..." — the very first
            # periodic analysis call after the model unloads would time
            # out here the same way.
            resp = httpx.post(
                self._ollama_url,
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "images": [b64_frame],
                    "stream": False,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()

            raw_resp = data.get("response", "").strip()
            self._last_analysis = now
            
            # Parse structured output or fallback to raw text
            description = raw_resp
            detected_objects = []
            try:
                # Find JSON block if enclosed in markdown
                if "```json" in raw_resp:
                    json_str = raw_resp.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_resp:
                    json_str = raw_resp.split("```")[1].split("```")[0].strip()
                else:
                    json_str = raw_resp
                parsed = json.loads(json_str)
                description = parsed.get("description", raw_resp)
                detected_objects = parsed.get("objects", [])
            except Exception:
                pass

            self._latest_description = description

            if description:
                return [DetectionResult(
                    source=camera_source,
                    event_type="scene",
                    confidence=0.85,
                    data={
                        "description": description,
                        "objects": detected_objects,
                        "room": room,
                        "model": self._model,
                        "local": True,
                    },
                )]
            return []

        except Exception as e:
            logger.debug(f"Local scene analysis (Ollama CPU) failed: {e}")
            self._available = False
            self._last_check = time.monotonic()
            self._last_analysis = now
            return []

    @property
    def latest_description(self) -> str:
        """Get the most recent scene description."""
        return self._latest_description

    def _is_available(self) -> bool:
        """Check if local Ollama service is responsive."""
        if self._available:
            return True
        if time.monotonic() - self._last_check > self._check_interval:
            self._available = True
            return True
        return False


