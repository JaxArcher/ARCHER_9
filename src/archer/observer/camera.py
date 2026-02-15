"""
ARCHER Webcam Capture.

Dedicated capture thread that reads frames from the webcam at a
configurable interval and dispatches them for analysis.

Design rules:
- The capture thread is a daemon thread — it dies with the process.
- Frames are NOT queued — the latest frame is always available via
  get_latest_frame(). This avoids unbounded memory growth if analysis
  is slower than capture.
- The camera is released cleanly on stop() or process exit.
- If no camera is available, the module logs a warning and enters
  a no-op mode (the rest of the Observer pipeline degrades gracefully).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np
from loguru import logger


class WebcamCapture:
    """
    Webcam capture with a dedicated thread.

    Captures frames at ~2 FPS (every 500ms) to minimize CPU/GPU load
    while still detecting posture changes, emotions, and food in frame.
    Higher FPS is unnecessary for ambient observation.
    """

    def __init__(
        self,
        device_index: int = 0,
        capture_interval: float = 0.5,  # seconds between captures
        resolution: tuple[int, int] = (640, 480),
    ) -> None:
        self._device_index = device_index
        self._capture_interval = capture_interval
        self._resolution = resolution

        # Latest frame (thread-safe via lock)
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._frame_timestamp: float = 0.0

        # Control
        self._running = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._cap: Any = None  # cv2.VideoCapture — lazy import

        # Stats
        self._frames_captured = 0
        self._errors = 0

    def start(self) -> bool:
        """
        Start the webcam capture thread.

        Returns True if the camera was opened successfully, False otherwise.
        """
        if self._running.is_set():
            logger.warning("WebcamCapture already running.")
            return True

        try:
            import cv2
            self._cap = cv2.VideoCapture(self._device_index)

            if not self._cap.isOpened():
                logger.warning(
                    f"Could not open webcam (device {self._device_index}). "
                    "Observer will run in no-camera mode."
                )
                self._cap = None
                return False

            # Set resolution
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])

            self._running.set()
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                name="WebcamCapture",
                daemon=True,
            )
            self._capture_thread.start()

            logger.info(
                f"Webcam capture started (device {self._device_index}, "
                f"{self._resolution[0]}x{self._resolution[1]}, "
                f"{1/self._capture_interval:.1f} FPS)"
            )
            return True

        except ImportError:
            logger.warning(
                "opencv-python not installed. Observer webcam capture disabled. "
                "Install with: pip install opencv-python-headless"
            )
            return False
        except Exception as e:
            logger.warning(f"Webcam capture init failed: {e}")
            return False

    def stop(self) -> None:
        """Stop the webcam capture thread and release the camera."""
        self._running.clear()

        if self._capture_thread is not None:
            self._capture_thread.join(timeout=3.0)
            self._capture_thread = None

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        logger.info(
            f"Webcam capture stopped. "
            f"Frames captured: {self._frames_captured}, errors: {self._errors}"
        )

    def get_latest_frame(self) -> tuple[np.ndarray | None, float]:
        """
        Get the most recent captured frame.

        Returns:
            Tuple of (frame as numpy array or None, timestamp as float).
            The frame is in BGR format (OpenCV default).
        """
        with self._frame_lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy(), self._frame_timestamp
            return None, 0.0

    @property
    def is_running(self) -> bool:
        """Check if the capture thread is active."""
        return self._running.is_set()

    @property
    def frames_captured(self) -> int:
        """Total frames captured since start."""
        return self._frames_captured

    def _capture_loop(self) -> None:
        """Main capture loop — runs in dedicated thread."""
        while self._running.is_set():
            try:
                if self._cap is None or not self._cap.isOpened():
                    logger.warning("Camera disconnected. Stopping capture.")
                    self._running.clear()
                    break

                ret, frame = self._cap.read()
                if not ret or frame is None:
                    self._errors += 1
                    if self._errors > 50:
                        logger.error("Too many camera errors. Stopping capture.")
                        self._running.clear()
                        break
                    time.sleep(self._capture_interval)
                    continue

                with self._frame_lock:
                    self._latest_frame = frame
                    self._frame_timestamp = time.monotonic()
                    self._frames_captured += 1

            except Exception as e:
                logger.error(f"Webcam capture error: {e}")
                self._errors += 1

            # Sleep between captures — we don't need 30fps for ambient observation
            time.sleep(self._capture_interval)
