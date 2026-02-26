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

import sys
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

    The camera_source parameter accepts:
    - int: local device index (0 = default webcam, 1 = second camera, etc.)
    - str: RTSP/HTTP URL for network cameras (e.g. "rtsp://192.168.1.100:554/stream")
    """

    def __init__(
        self,
        camera_source: int | str = 0,
        capture_interval: float = 0.5,  # seconds between captures
        resolution: tuple[int, int] = (640, 480),
    ) -> None:
        self._camera_source = camera_source
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
        For local devices on Windows, tries DSHOW then MSMF backends, and
        verifies the camera can actually read a frame before starting.
        If the configured device fails, auto-scans devices 0-9 for a working one.
        """
        if self._running.is_set():
            logger.warning("WebcamCapture already running.")
            return True

        try:
            import cv2

            if isinstance(self._camera_source, int):
                # Local device: try configured device first, then scan
                self._cap = self._open_local_device(cv2, self._camera_source)

                if self._cap is None:
                    # Configured device failed — scan for any working camera
                    logger.info(
                        f"Configured device {self._camera_source} failed. "
                        "Scanning for working camera..."
                    )
                    for idx in range(10):
                        if idx == self._camera_source:
                            continue
                        self._cap = self._open_local_device(cv2, idx)
                        if self._cap is not None:
                            logger.info(f"Found working camera on device {idx}")
                            self._camera_source = idx
                            break
            else:
                # RTSP/HTTP URL — no backend selection needed
                self._cap = cv2.VideoCapture(self._camera_source)

            if self._cap is None or not self._cap.isOpened():
                source_desc = (
                    f"device {self._camera_source}"
                    if isinstance(self._camera_source, int)
                    else self._camera_source
                )
                logger.warning(
                    f"Could not open camera ({source_desc}). "
                    "Observer will run in no-camera mode."
                )
                if self._cap is not None:
                    self._cap.release()
                self._cap = None
                return False

            self._running.set()
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                name="WebcamCapture",
                daemon=True,
            )
            self._capture_thread.start()

            source_desc = (
                f"device {self._camera_source}"
                if isinstance(self._camera_source, int)
                else self._camera_source
            )
            backend = self._cap.getBackendName() if hasattr(self._cap, "getBackendName") else "unknown"
            logger.info(
                f"Camera capture started ({source_desc}, "
                f"backend={backend}, "
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

    def _open_local_device(self, cv2, device: int):
        """
        Try to open a local camera device and verify it can read a frame.

        Tries DSHOW first (Windows), then MSMF fallback.
        Returns the opened VideoCapture or None if all attempts fail.
        """
        backends = []
        if sys.platform == "win32":
            backends.append(("DSHOW", cv2.CAP_DSHOW))
            backends.append(("MSMF", cv2.CAP_MSMF))
        else:
            backends.append(("default", cv2.CAP_ANY))

        for backend_name, backend_id in backends:
            cap = None
            try:
                cap = cv2.VideoCapture(device, backend_id)
                if not cap.isOpened():
                    cap.release()
                    continue

                # Set MJPG codec on Windows for better compatibility
                if sys.platform == "win32":
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])

                # Warmup: let the camera stabilize before testing
                import time as _time
                _time.sleep(0.3)

                # Verify the camera can actually produce frames.
                # Read 3 test frames — some virtual devices (e.g. Remote
                # Desktop Camera Bus) pass a single read but fail on all
                # subsequent ones.
                ok_count = 0
                last_frame = None
                for _attempt in range(3):
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        ok_count += 1
                        last_frame = frame
                    _time.sleep(0.1)

                if ok_count < 2:
                    logger.debug(
                        f"Device {device} ({backend_name}): opened but only "
                        f"{ok_count}/3 test frames succeeded — skipping"
                    )
                    cap.release()
                    continue

                logger.debug(
                    f"Device {device} ({backend_name}): working — "
                    f"{last_frame.shape[1]}x{last_frame.shape[0]} "
                    f"({ok_count}/3 test frames OK)"
                )
                return cap

            except Exception as e:
                logger.debug(f"Device {device} ({backend_name}): error — {e}")
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        return None

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
