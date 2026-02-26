"""
ARCHER Webcam Feed Widget.

Displays live webcam frames and vision analysis results in the GUI.
Polls the shared WebcamCapture instance for frames and converts
them to Qt-displayable images.

Threading model:
- The WebcamCapture thread handles all camera I/O.
- This widget just reads the latest frame via a QTimer on the GUI thread.
- No blocking calls, no threading here.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QScrollArea,
    QSizePolicy,
)

import numpy as np
from loguru import logger


class WebcamWidget(QFrame):
    """
    Live webcam feed with vision analysis results.

    Top section: video feed (QLabel with QPixmap)
    Bottom section: scrolling text with latest vision/scene analysis

    The widget does NOT own a camera — it reads from a shared
    WebcamCapture instance passed at construction time.
    """

    vision_updated = pyqtSignal(str)  # Emitted when vision text changes

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("quadrant")

        self._camera = None  # Set via set_camera()
        self._paused = False
        self._get_detections: Callable[[], list[dict]] | None = None

        self._setup_ui()

        # Frame polling timer — ~10 FPS for smooth display
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frame)
        self._timer.setInterval(100)  # 100ms = 10 FPS

    def _setup_ui(self) -> None:
        """Build the layout: video feed on top, vision text on bottom."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Video feed ---
        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_label.setMinimumSize(320, 240)
        self._video_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._video_label.setStyleSheet("""
            background-color: #0a0a18;
            border-bottom: 1px solid #1a1a3e;
        """)
        self._show_placeholder("No Camera")
        layout.addWidget(self._video_label, 3)

        # --- Vision results ---
        self._vision_label = QLabel("Vision: Waiting for analysis...")
        self._vision_label.setWordWrap(True)
        self._vision_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self._vision_label.setStyleSheet("""
            color: #aaaacc;
            font-size: 11px;
            padding: 8px 10px;
            background-color: #0d0d1a;
            line-height: 1.4;
        """)
        self._vision_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        self._vision_label.setMaximumHeight(100)

        vision_scroll = QScrollArea()
        vision_scroll.setWidget(self._vision_label)
        vision_scroll.setWidgetResizable(True)
        vision_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #0d0d1a;
            }
            QScrollBar:vertical {
                width: 6px;
                background: #0d0d1a;
            }
            QScrollBar::handle:vertical {
                background: #333355;
                border-radius: 3px;
            }
        """)
        vision_scroll.setMaximumHeight(100)
        layout.addWidget(vision_scroll, 1)

    def set_camera(self, camera) -> None:
        """
        Attach a WebcamCapture instance and start polling.

        Args:
            camera: A WebcamCapture instance (from observer pipeline).
        """
        self._camera = camera
        if camera is not None:
            self._timer.start()
            logger.info("Webcam widget attached to camera feed.")
        else:
            self._timer.stop()
            self._show_placeholder("No Camera")

    def set_detections_source(self, getter: Callable[[], list[dict]]) -> None:
        """Set the function to call for getting overlay detections."""
        self._get_detections = getter

    def set_paused(self, paused: bool) -> None:
        """Show/hide the feed based on observer pause state."""
        self._paused = paused
        if paused:
            self._show_placeholder("OBSERVER PAUSED\n\nPrivacy mode active")
        elif self._camera is not None:
            # Timer will resume showing frames naturally
            pass
        else:
            self._show_placeholder("No Camera")

    def update_vision(self, text: str) -> None:
        """Update the vision analysis text (thread-safe — call via signal)."""
        if text:
            self._vision_label.setText(f"🔍 {text}")
            self.vision_updated.emit(text)

    def _update_frame(self) -> None:
        """Poll the latest frame and display it (with detection overlays)."""
        if self._paused or self._camera is None:
            return

        frame, timestamp = self._camera.get_latest_frame()
        if frame is None:
            return

        # Apply detection overlays if available
        if self._get_detections is not None:
            try:
                detections = self._get_detections()
                if detections:
                    from archer.observer.overlay import draw_annotations
                    frame = draw_annotations(frame, detections)
            except Exception:
                pass  # Show raw frame on overlay failure

        self._display_frame(frame)

    def _display_frame(self, frame: np.ndarray) -> None:
        """Convert a BGR numpy array to QPixmap and display it."""
        try:
            # OpenCV BGR → Qt RGB
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            qimg = QImage(
                rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888
            )

            # Scale to fit label while maintaining aspect ratio
            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(
                self._video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._video_label.setPixmap(scaled)

        except Exception as e:
            logger.debug(f"Frame display error: {e}")

    def _show_placeholder(self, text: str) -> None:
        """Show a text placeholder instead of video."""
        self._video_label.clear()
        self._video_label.setText(text)
        self._video_label.setStyleSheet("""
            background-color: #0a0a18;
            color: #444466;
            font-size: 14px;
            font-weight: bold;
            letter-spacing: 2px;
            border-bottom: 1px solid #1a1a3e;
        """)

    def stop(self) -> None:
        """Stop the frame polling timer."""
        self._timer.stop()
