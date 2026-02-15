"""
ARCHER System Tray.

ARCHER is always-on. Closing the main window minimizes to the system tray.
Uses QSystemTrayIcon (PyQt6 built-in, no third-party library needed).

Tray icon behavior:
- Left-click: restore the main window
- Right-click: context menu (Show Window, Mute Mic, Pause Observer,
  Cloud/Local Toggle, Quit ARCHER)
- Balloon notification for proactive messages while minimized

'Quit ARCHER' in the tray menu is the ONLY way to fully stop the process.
The window's X button always minimizes to tray, never quits.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QWidget

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus
from archer.core.toggle import get_toggle_service


class SystemTray(QSystemTrayIcon):
    """
    System tray icon with context menu and notifications.

    The tray icon color ring reflects the current orb state.
    """

    show_window = pyqtSignal()
    quit_requested = pyqtSignal()
    observer_paused = pyqtSignal(bool)  # True=paused, False=resumed

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._bus = get_event_bus()
        self._toggle = get_toggle_service()

        # Create tray icon
        self._create_icon()

        # Create context menu
        self._create_menu()

        # Connect signals
        self.activated.connect(self._on_activated)

        # Subscribe to events
        self._bus.subscribe(EventType.AGENT_RESPONSE_END, self._on_proactive_message)

    def _create_icon(self) -> None:
        """Create the tray icon with a colored ring."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer ring (state color)
        painter.setPen(QColor(204, 204, 204))
        painter.setBrush(QColor(30, 30, 50))
        painter.drawEllipse(2, 2, 28, 28)

        # Inner "A"
        painter.setPen(QColor(46, 109, 164))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(16)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), 0x0084, "A")  # AlignCenter

        painter.end()

        self.setIcon(QIcon(pixmap))
        self.setToolTip("ARCHER — AI Assistant")

    def _create_menu(self) -> None:
        """Create the right-click context menu."""
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #1a1a2e;
                color: #cccccc;
                border: 1px solid #333355;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #2E6DA4;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background: #333355;
                margin: 4px 8px;
            }
        """)

        # Show Window
        show_action = QAction("Show Window", menu)
        show_action.triggered.connect(self.show_window.emit)
        menu.addAction(show_action)

        menu.addSeparator()

        # Mute Microphone
        self._mute_mic_action = QAction("Mute Microphone", menu)
        self._mute_mic_action.setCheckable(True)
        self._mute_mic_action.triggered.connect(self._on_mute_mic)
        menu.addAction(self._mute_mic_action)

        # Pause Observer (Phase 3 — now enabled)
        self._pause_observer_action = QAction("Pause Observer", menu)
        self._pause_observer_action.setCheckable(True)
        self._pause_observer_action.triggered.connect(self._on_pause_observer)
        menu.addAction(self._pause_observer_action)

        # Cloud/Local Toggle
        mode = self._toggle.mode
        self._mode_action = QAction(
            f"Switch to {'Local' if mode == 'cloud' else 'Cloud'} Mode",
            menu,
        )
        self._mode_action.triggered.connect(self._on_toggle_mode)
        menu.addAction(self._mode_action)

        menu.addSeparator()

        # Quit ARCHER
        quit_action = QAction("Quit ARCHER", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window.emit()

    def _on_mute_mic(self) -> None:
        """Toggle microphone mute."""
        muted = self._mute_mic_action.isChecked()
        logger.info(f"Microphone {'muted' if muted else 'unmuted'} from tray")

    def _on_pause_observer(self) -> None:
        """Toggle observer pause state."""
        paused = self._pause_observer_action.isChecked()
        self.observer_paused.emit(paused)
        logger.info(f"Observer {'paused' if paused else 'resumed'} from tray")

    def _on_toggle_mode(self) -> None:
        """Toggle cloud/local mode."""
        new_mode = self._toggle.toggle()
        self._mode_action.setText(
            f"Switch to {'Local' if new_mode == 'cloud' else 'Cloud'} Mode"
        )

    def _on_proactive_message(self, event: Event) -> None:
        """Show balloon notification for proactive messages while minimized."""
        # Only show if the main window is not visible
        text = event.data.get("text", "")[:100]
        agent = event.data.get("agent", "ARCHER")
        if text:
            self.showMessage(
                f"ARCHER — {agent.capitalize()}",
                text,
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def update_state_color(self, color: QColor) -> None:
        """Update the tray icon ring color to reflect current state."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer ring with state color
        painter.setPen(color)
        painter.setBrush(QColor(30, 30, 50))
        painter.drawEllipse(2, 2, 28, 28)

        # Inner "A"
        painter.setPen(color)
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(16)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), 0x0084, "A")

        painter.end()

        self.setIcon(QIcon(pixmap))
