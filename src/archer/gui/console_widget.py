"""
ARCHER Console/Log Tab.

Not a literal embedded terminal (PyQt has no cross-platform way to embed
the actual OS console window ARCHER was launched from) — instead this
tails the same rotating log file `__main__.py` already writes via loguru
(`config.log_dir / archer_YYYY-MM-DD.log`) and streams new lines into a
read-only monospace text view. Functionally the same information the
terminal shows, live, without needing to alt-tab to check it.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel

from loguru import logger

from archer.config import get_config

# Cap how much text we keep in the widget so a long-running session doesn't
# grow the document forever.
_MAX_BLOCKS = 4000
# How much of the existing file to show when we first attach (tail -n style),
# rather than dumping the entire (possibly multi-MB) log from the start.
_INITIAL_TAIL_BYTES = 12_000


class ConsoleWidget(QWidget):
    """Live-tailing view of ARCHER's current log file."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = get_config()
        self._current_path: Path | None = None
        self._offset = 0
        self._paused = False
        self._setup_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(750)
        # Do an initial poll immediately so the tab isn't empty on first view.
        self._poll()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Small toolbar: which file we're tailing + pause/clear controls.
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)

        self._file_label = QLabel("")
        self._file_label.setStyleSheet("color: #666666; font-size: 10px;")
        bar.addWidget(self._file_label, 1)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setFixedSize(60, 22)
        self._pause_btn.setStyleSheet(
            "QPushButton { background: #1a1a3e; color: #aaa; border: 1px solid #333355; "
            "border-radius: 3px; font-size: 10px; } "
            "QPushButton:hover { border-color: #2E6DA4; }"
        )
        self._pause_btn.clicked.connect(self._toggle_pause)
        bar.addWidget(self._pause_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(60, 22)
        clear_btn.setStyleSheet(
            "QPushButton { background: #1a1a3e; color: #aaa; border: 1px solid #333355; "
            "border-radius: 3px; font-size: 10px; } "
            "QPushButton:hover { border-color: #2E6DA4; }"
        )
        clear_btn.clicked.connect(self._clear)
        bar.addWidget(clear_btn)

        bar_frame = QWidget()
        bar_frame.setLayout(bar)
        bar_frame.setStyleSheet("background-color: #12122a; border-bottom: 1px solid #1a1a3e;")
        layout.addWidget(bar_frame)

        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setStyleSheet(
            "QTextEdit { background-color: #05050a; color: #8fdb8f; border: none; "
            "padding: 8px; font-family: 'Consolas', 'Courier New', monospace; font-size: 11px; }"
        )
        layout.addWidget(self._view, 1)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._pause_btn.setText("Resume" if self._paused else "Pause")

    def _clear(self) -> None:
        self._view.clear()

    def _latest_log_file(self) -> Path | None:
        """Find the most recently modified archer_*.log* file."""
        try:
            log_dir = Path(self._config.log_dir)
            candidates = list(log_dir.glob("archer_*.log*"))
            if not candidates:
                return None
            return max(candidates, key=lambda p: p.stat().st_mtime)
        except Exception:
            return None

    def _poll(self) -> None:
        if self._paused:
            return

        latest = self._latest_log_file()
        if latest is None:
            self._file_label.setText("No log file found yet.")
            return

        try:
            if latest != self._current_path:
                # New file (first attach, or rotation happened) — seed with
                # a tail of recent content rather than the whole file.
                self._current_path = latest
                size = latest.stat().st_size
                self._offset = max(0, size - _INITIAL_TAIL_BYTES)
                self._file_label.setText(f"Tailing: {latest.name}")

            with open(self._current_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                new_text = f.read()
                self._offset = f.tell()

            if new_text:
                self._append(new_text)

        except Exception as e:
            logger.debug(f"Console tail read failed (non-critical): {e}")

    def _append(self, text: str) -> None:
        cursor = self._view.textCursor()
        from PyQt6.QtGui import QTextCursor
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._view.setTextCursor(cursor)
        self._view.ensureCursorVisible()

        # Trim from the top if the document has grown too large.
        doc = self._view.document()
        if doc.blockCount() > _MAX_BLOCKS:
            trim_cursor = QTextCursor(doc)
            trim_cursor.movePosition(QTextCursor.MoveOperation.Start)
            trim_cursor.movePosition(
                QTextCursor.MoveOperation.Down,
                QTextCursor.MoveMode.KeepAnchor,
                doc.blockCount() - _MAX_BLOCKS,
            )
            trim_cursor.removeSelectedText()
