"""
ARCHER Conversation Panel.

The top-left quadrant of the GUI. Shows:
- Top strip: wake word indicator, VAD level meter, live STT transcription
- Main area: scrollable full conversation history for the current session
- Bottom: text input field with send button and TTS mute toggle

Each conversation entry shows:
- User turn: timestamp, 'You:' label, transcribed text
- Agent turn: timestamp, agent name badge (colored), response text
- System events: gray labels for mode changes, HALT, session start/end
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QTextCursor
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QFrame,
    QScrollArea,
)

from archer.core.event_bus import Event, EventType, get_event_bus


# Agent badge colors
AGENT_COLORS = {
    "assistant": "#2E6DA4",
    "trainer": "#1A6B3C",
    "therapist": "#5B2A8C",
    "finance": "#8C6B00",
    "investment": "#C75B00",
    "observer": "#888888",
    "system": "#666666",
}


class ConversationPanel(QWidget):
    """
    Conversation panel with live transcription, history, and text input.

    All GUI updates happen on the main thread via Qt signals.
    Background threads communicate through the event bus → signal bridge.
    """

    # Signals for thread-safe GUI updates
    append_message_signal = pyqtSignal(str, str, str, str)  # role, agent, text, timestamp
    update_stt_signal = pyqtSignal(str)  # live STT text
    update_vad_signal = pyqtSignal(float)  # VAD level (0.0-1.0)
    update_wake_word_signal = pyqtSignal(bool)  # wake word detected
    text_submitted = pyqtSignal(str)  # text input submitted

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = get_event_bus()
        self._setup_ui()
        self._connect_signals()
        self._subscribe_events()

    def _setup_ui(self) -> None:
        """Build the conversation panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Top Strip: Status bar ---
        status_frame = QFrame()
        status_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border-bottom: 1px solid #333355;
                padding: 4px 8px;
            }
        """)
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(8, 4, 8, 4)

        # Wake word indicator dot
        self._wake_dot = QLabel("●")
        self._wake_dot.setStyleSheet("color: #444444; font-size: 12px;")
        self._wake_dot.setFixedWidth(20)
        status_layout.addWidget(self._wake_dot)

        # Wake word label
        wake_label = QLabel("WAKE")
        wake_label.setStyleSheet("color: #666666; font-size: 9px; font-weight: bold;")
        wake_label.setFixedWidth(35)
        status_layout.addWidget(wake_label)

        # VAD level meter
        self._vad_meter = QProgressBar()
        self._vad_meter.setRange(0, 100)
        self._vad_meter.setValue(0)
        self._vad_meter.setFixedHeight(8)
        self._vad_meter.setFixedWidth(80)
        self._vad_meter.setTextVisible(False)
        self._vad_meter.setStyleSheet("""
            QProgressBar {
                background-color: #0d0d1a;
                border: 1px solid #333355;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #2E6DA4;
                border-radius: 2px;
            }
        """)
        status_layout.addWidget(self._vad_meter)

        # VAD label
        vad_label = QLabel("VAD")
        vad_label.setStyleSheet("color: #666666; font-size: 9px; font-weight: bold;")
        vad_label.setFixedWidth(25)
        status_layout.addWidget(vad_label)

        # Live STT transcription
        self._stt_label = QLabel("")
        self._stt_label.setStyleSheet("""
            color: #88AACC;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
        """)
        self._stt_label.setWordWrap(True)
        status_layout.addWidget(self._stt_label, 1)

        layout.addWidget(status_frame)

        # --- Main Area: Conversation history ---
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d1a;
                color: #cccccc;
                border: none;
                padding: 12px;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 13px;
                line-height: 1.5;
                selection-background-color: #2E6DA4;
            }
            QScrollBar:vertical {
                background: #0d0d1a;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: #333355;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        layout.addWidget(self._history, 1)

        # --- Bottom: Text input ---
        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border-top: 1px solid #333355;
                padding: 4px;
            }
        """)
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(8, 6, 8, 6)

        # TTS mute toggle
        self._mute_btn = QPushButton("🔊")
        self._mute_btn.setFixedSize(32, 32)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #333355;
                border-radius: 4px;
                font-size: 16px;
                padding: 0;
            }
            QPushButton:checked {
                border-color: #9B2335;
                background: #1a0a0e;
            }
            QPushButton:hover {
                border-color: #555577;
            }
        """)
        self._mute_btn.clicked.connect(self._on_mute_toggle)
        input_layout.addWidget(self._mute_btn)

        # Text input field
        self._text_input = QLineEdit()
        self._text_input.setPlaceholderText("Type a message... (voice is primary)")
        self._text_input.setStyleSheet("""
            QLineEdit {
                background-color: #0d0d1a;
                color: #cccccc;
                border: 1px solid #333355;
                border-radius: 6px;
                padding: 6px 12px;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #2E6DA4;
            }
        """)
        self._text_input.returnPressed.connect(self._on_text_submit)
        input_layout.addWidget(self._text_input, 1)

        # Send button
        self._send_btn = QPushButton("Send")
        self._send_btn.setFixedSize(60, 32)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background-color: #2E6DA4;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #3A7DB4;
            }
            QPushButton:pressed {
                background-color: #1E5D94;
            }
        """)
        self._send_btn.clicked.connect(self._on_text_submit)
        input_layout.addWidget(self._send_btn)

        layout.addWidget(input_frame)

    def _connect_signals(self) -> None:
        """Connect signals for thread-safe GUI updates."""
        self.append_message_signal.connect(self._append_message_internal)
        self.update_stt_signal.connect(self._update_stt_internal)
        self.update_vad_signal.connect(self._update_vad_internal)
        self.update_wake_word_signal.connect(self._update_wake_word_internal)

    def _subscribe_events(self) -> None:
        """Subscribe to relevant event bus events."""
        self._bus.subscribe(EventType.STT_FINAL, self._on_stt_final)
        self._bus.subscribe(EventType.STT_PARTIAL, self._on_stt_partial)
        self._bus.subscribe(EventType.AGENT_RESPONSE_END, self._on_agent_response)
        self._bus.subscribe(EventType.AGENT_SWITCH, self._on_agent_switch)
        self._bus.subscribe(EventType.WAKE_WORD_DETECTED, self._on_wake_word)
        self._bus.subscribe(EventType.HALT, self._on_halt)
        self._bus.subscribe(EventType.MODE_CHANGED, self._on_mode_changed)
        self._bus.subscribe(EventType.SYSTEM_START, self._on_system_start)

        # Track current active agent for labeling responses
        self._current_agent = "assistant"

    # --- Thread-safe update methods ---

    def append_message(self, role: str, agent: str, text: str) -> None:
        """Append a message to the conversation (thread-safe)."""
        timestamp = datetime.now().strftime("%H:%M")
        self.append_message_signal.emit(role, agent, text, timestamp)

    def _append_message_internal(self, role: str, agent: str, text: str, timestamp: str) -> None:
        """Internal: append message on GUI thread."""
        logger.debug(f"GUI append: role={role}, text='{text[:60]}...' " if len(text) > 60 else f"GUI append: role={role}, text='{text}'")

        cursor = self._history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if role == "user":
            html = (
                f'<p style="margin: 6px 0;">'
                f'<span style="color: #666; font-size: 11px;">{timestamp}</span> '
                f'<span style="color: #AAAAAA; font-weight: bold;">You:</span> '
                f'<span style="color: #DDDDDD;">{text}</span>'
                f'</p>'
            )
        elif role == "assistant":
            color = AGENT_COLORS.get(agent, "#2E6DA4")
            badge = agent.capitalize()
            html = (
                f'<p style="margin: 6px 0;">'
                f'<span style="color: #666; font-size: 11px;">{timestamp}</span> '
                f'<span style="background: {color}22; color: {color}; '
                f'padding: 1px 6px; border-radius: 3px; font-weight: bold; '
                f'font-size: 11px;">{badge}</span> '
                f'<span style="color: #CCCCCC;">{text}</span>'
                f'</p>'
            )
        elif role == "system":
            html = (
                f'<p style="margin: 3px 0;">'
                f'<span style="color: #555; font-style: italic; font-size: 11px;">'
                f'{timestamp} — {text}</span>'
                f'</p>'
            )
        else:
            html = f'<p>{text}</p>'

        # insertBlock ensures each message starts on a new line.
        # Without this, consecutive insertHtml calls can merge content.
        if not self._history.toPlainText() == "":
            cursor.insertBlock()
        cursor.insertHtml(html)
        self._history.setTextCursor(cursor)
        self._history.ensureCursorVisible()

    def _update_stt_internal(self, text: str) -> None:
        """Update live STT display."""
        self._stt_label.setText(text)

    def _update_vad_internal(self, level: float) -> None:
        """Update VAD level meter."""
        self._vad_meter.setValue(int(level * 100))

    def _update_wake_word_internal(self, detected: bool) -> None:
        """Update wake word indicator."""
        if detected:
            self._wake_dot.setStyleSheet("color: #2E6DA4; font-size: 12px;")
            QTimer.singleShot(2000, lambda: self._wake_dot.setStyleSheet(
                "color: #444444; font-size: 12px;"
            ))

    # --- Event handlers ---

    def _on_stt_final(self, event: Event) -> None:
        text = event.data.get("text", "")
        self.append_message("user", "", text)
        self.update_stt_signal.emit("")

    def _on_stt_partial(self, event: Event) -> None:
        text = event.data.get("text", "")
        self.update_stt_signal.emit(text)

    def _on_agent_response(self, event: Event) -> None:
        text = event.data.get("text", "")
        # Use the tracked current agent — more reliable than event data
        # since AGENT_RESPONSE_END comes from the pipeline, not the orchestrator
        agent = event.data.get("agent", self._current_agent)
        self.append_message("assistant", agent, text)

    def _on_agent_switch(self, event: Event) -> None:
        new_agent = event.data.get("new_agent", "assistant")
        self._current_agent = new_agent

    def _on_wake_word(self, event: Event) -> None:
        self.update_wake_word_signal.emit(True)

    def _on_halt(self, event: Event) -> None:
        self.append_message("system", "", "⛔ HALT — All operations stopped.")

    def _on_mode_changed(self, event: Event) -> None:
        new_mode = event.data.get("new_mode", "unknown")
        self.append_message("system", "", f"Mode changed to {new_mode}")

    def _on_system_start(self, event: Event) -> None:
        self.append_message("system", "", "ARCHER session started")

    # --- User actions ---

    def _on_text_submit(self) -> None:
        """Handle text input submission."""
        text = self._text_input.text().strip()
        if text:
            self._text_input.clear()
            self.text_submitted.emit(text)

    def _on_mute_toggle(self) -> None:
        """Handle TTS mute toggle."""
        muted = self._mute_btn.isChecked()
        self._mute_btn.setText("🔇" if muted else "🔊")
        self._bus.publish(Event(
            type=EventType.GUI_MUTE_TTS,
            source="gui",
            data={"muted": muted},
        ))
