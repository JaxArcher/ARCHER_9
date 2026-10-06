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
        # Failure visibility (2026-10-06) -- see analyze()'s except block.
        self._failing = False
        self._first_success_logged = False

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

            # Plain-language prompt (2026-10-06). The previous prompt asked
            # moondream -- a 1.4B captioning model -- for strict JSON with an
            # open-ended "objects" list. It almost never stopped (see the
            # num_predict note below), and the few answers that did finish
            # echoed the template back ("confidence 0.9, location desk") or
            # invented people's names. Nothing downstream reads "objects" --
            # Blindspot and the staleness reasoner work from the description
            # text -- so ask for exactly that. The JSON-parsing fallback below
            # still copes if the model volunteers JSON anyway.
            prompt = (
                "Describe this scene in two or three short sentences: what the "
                "person is doing, if anyone is present, and the notable objects "
                "around them. Refer to people only as 'a person'."
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
                    # num_gpu: 0 (2026-09-24 finding) -- CUDA_VISIBLE_DEVICES=-1
                    # on the spawned observer ollama process (see
                    # ollama_bootstrap.py's _spawn_ollama_serve) was not
                    # reliably keeping moondream off the GPU; Col observed it
                    # resident in VRAM live. This per-request override pins
                    # it to CPU directly through Ollama's own API instead of
                    # depending on the env var alone.
                    "options": {
                        "num_gpu": 0,
                        # Hard cap on answer length (2026-10-06). 2-3
                        # sentences is roughly 60-80 tokens; at ~16 tok/s on
                        # CPU plus ~6s to encode the frame, 120 tokens lands
                        # well inside the 60s timeout even if the model
                        # rambles. Without a cap, 98 of 104 requests on
                        # 2026-10-03 were still generating (640-956 tokens)
                        # when the timeout killed them.
                        "num_predict": 120,
                        # Light penalty against the repetition loops that
                        # caused the runaway answers above.
                        "repeat_penalty": 1.15,
                    },
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()

            raw_resp = data.get("response", "").strip()
            self._last_analysis = now
            if self._failing:
                logger.info("Scene analysis recovered -- moondream is answering again.")
                self._failing = False
            
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
            if description and not self._first_success_logged:
                logger.info(f"First scene description this run: {description[:200]}")
                self._first_success_logged = True

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
            # WARNING once per outage, DEBUG for repeats (2026-10-06): at
            # DEBUG only, a full day of failed analyses never showed in the
            # console or the service's stderr log.
            if not self._failing:
                logger.warning(
                    f"Scene analysis failed ({type(e).__name__}: {e}) -- moondream at "
                    f"{self._ollama_url}. Will keep retrying; repeats are logged at DEBUG."
                )
                self._failing = True
            else:
                logger.debug(f"Local scene analysis (Ollama CPU) failed: {type(e).__name__}: {e}")
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


