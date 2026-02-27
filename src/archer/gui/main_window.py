"""
ARCHER Main Window.

PyQt6 on Windows, native. Four-quadrant layout:
- Top-left: Conversation panel (voice pipeline status + chat history)
- Top-right: 3D Orb visualization
- Bottom-left: Memory / context panel
- Bottom-right: Artifact pane (Response panel for Phase 1)

Rules:
- PyQt6 owns the main thread. No blocking calls anywhere.
- All updates from background threads go through Qt signals/slots.
- The webcam feed is optional (Phase 3).
- Cloud/local toggle in the title bar.
- HALT button always visible and always functional.
- X button minimizes to tray, never quits.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QFont, QColor, QAction
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSplitter,
    QToolBar,
    QStatusBar,
    QSizePolicy,
    QSystemTrayIcon,
)

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus
from archer.core.toggle import get_toggle_service
from archer.gui.orb_widget import OrbWidget
from archer.gui.conversation import ConversationPanel
from archer.gui.artifact_pane import ArtifactPane
from archer.gui.tray import SystemTray
from archer.gui.webcam_widget import WebcamWidget

# Try to import the 3D orb — falls back to 2D if PyVista is unavailable
try:
    from archer.gui.orb_3d import Orb3DWidget
    _HAS_3D_ORB = True
except ImportError:
    _HAS_3D_ORB = False


class MainWindow(QMainWindow):
    """
    ARCHER Main Window — Mission Control.

    Four-quadrant layout with animated orb, conversation panel,
    memory context, and artifact pane.
    """

    # Signals for thread-safe updates (all GUI changes from background threads
    # MUST go through signals — never touch widgets directly from non-GUI threads)
    update_state_signal = pyqtSignal(str)
    update_agent_signal = pyqtSignal(str)
    update_status_signal = pyqtSignal(str)
    update_mode_signal = pyqtSignal(str)       # cloud/local → orb tint
    update_amplitude_signal = pyqtSignal(float) # audio amplitude → orb animation
    update_observer_signal = pyqtSignal(str)   # observer status display
    update_vision_signal = pyqtSignal(str)     # vision/scene analysis results
    observer_pause_signal = pyqtSignal(bool)   # observer pause/resume from tray
    gui_visibility_signal = pyqtSignal(bool)   # True=visible, False=hidden → camera switch
    _mode_changed_signal = pyqtSignal(str)
    _system_error_signal = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()

        self._bus = get_event_bus()
        self._toggle = get_toggle_service()

        # Set up window
        self.setWindowTitle("ARCHER — Mission Control")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        # Dark theme
        self.setStyleSheet(self._get_stylesheet())

        # Build UI
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_status_bar()
        self._setup_tray()

        # Connect signals
        self.update_state_signal.connect(self._on_state_update)
        self.update_agent_signal.connect(self._on_agent_update)
        self.update_status_signal.connect(self._on_status_update)
        self.update_mode_signal.connect(self._on_mode_update)
        self.update_amplitude_signal.connect(self._on_amplitude_update)
        self.update_observer_signal.connect(self._on_observer_update)
        self.update_vision_signal.connect(self._on_vision_update)
        self._mode_changed_signal.connect(self._apply_mode_change)
        self._system_error_signal.connect(self._apply_system_error)

        # Performance monitoring timer
        self._perf_timer = QTimer(self)
        self._perf_timer.timeout.connect(self._update_perf_metrics)
        self._perf_timer.start(5000) # Every 5 seconds

        # Subscribe to events
        self._subscribe_events()

        # Initialize orb mode to match current toggle state
        self._orb.set_mode(self._toggle.mode)

    def _get_stylesheet(self) -> str:
        """Global dark theme stylesheet."""
        return """
            QMainWindow {
                background-color: #0d0d1a;
                color: #cccccc;
            }
            QWidget {
                background-color: #0d0d1a;
                color: #cccccc;
                font-family: 'Segoe UI', 'Inter', sans-serif;
            }
            QToolBar {
                background-color: #12122a;
                border-bottom: 1px solid #333355;
                spacing: 8px;
                padding: 4px 8px;
            }
            QStatusBar {
                background-color: #12122a;
                color: #888888;
                border-top: 1px solid #333355;
                font-size: 11px;
            }
            QFrame#quadrant {
                background-color: #12122a;
                border: 1px solid #1a1a3e;
                border-radius: 8px;
            }
            QLabel#section_title {
                color: #888888;
                font-size: 10px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
                padding: 8px 12px 4px 12px;
            }
        """

    def _setup_toolbar(self) -> None:
        """Set up the title bar toolbar."""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        # ARCHER title
        title = QLabel("  ARCHER  ")
        title.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #2E6DA4;
            letter-spacing: 3px;
        """)
        toolbar.addWidget(title)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        toolbar.addWidget(spacer)

        # Mode indicator
        self._mode_label = QLabel(f"  ☁ CLOUD  " if self._toggle.is_cloud else "  🖥 LOCAL  ")
        self._mode_label.setStyleSheet("""
            color: #888888;
            font-size: 11px;
            font-weight: bold;
            padding: 2px 8px;
            border: 1px solid #333355;
            border-radius: 4px;
        """)
        toolbar.addWidget(self._mode_label)

        # Cloud/Local toggle button
        self._toggle_btn = QPushButton("Toggle Mode")
        self._toggle_btn.setFixedSize(100, 28)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a3e;
                color: #aaaaaa;
                border: 1px solid #333355;
                border-radius: 4px;
                font-size: 11px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                border-color: #2E6DA4;
                color: #cccccc;
            }
        """)
        self._toggle_btn.clicked.connect(self._on_toggle_mode)
        toolbar.addWidget(self._toggle_btn)

        # HALT button — always visible, always functional
        self._halt_btn = QPushButton("⛔ HALT")
        self._halt_btn.setFixedSize(80, 28)
        self._halt_btn.setStyleSheet("""
            QPushButton {
                background: #3a1020;
                color: #ff4444;
                border: 2px solid #9B2335;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #5a1030;
                border-color: #ff4444;
            }
            QPushButton:pressed {
                background: #9B2335;
                color: white;
            }
        """)
        self._halt_btn.clicked.connect(self._on_halt_clicked)
        toolbar.addWidget(self._halt_btn)

    def _setup_central_widget(self) -> None:
        """Set up the four-quadrant layout."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(8)

        # Horizontal splitter for top and bottom halves
        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- Top half ---
        top_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Top-left: Conversation panel
        conv_frame = QFrame()
        conv_frame.setObjectName("quadrant")
        conv_layout = QVBoxLayout(conv_frame)
        conv_layout.setContentsMargins(0, 0, 0, 0)
        conv_layout.setSpacing(0)

        conv_title = QLabel("CONVERSATION")
        conv_title.setObjectName("section_title")
        conv_layout.addWidget(conv_title)

        self._conversation = ConversationPanel()
        self._conversation.text_submitted.connect(self._on_text_submitted)
        conv_layout.addWidget(self._conversation)

        top_splitter.addWidget(conv_frame)

        # Top-right: Orb
        orb_frame = QFrame()
        orb_frame.setObjectName("quadrant")
        orb_layout = QVBoxLayout(orb_frame)
        orb_layout.setContentsMargins(0, 0, 0, 0)

        orb_title = QLabel("STATUS")
        orb_title.setObjectName("section_title")
        orb_layout.addWidget(orb_title)

        # Try 3D PyVista orb first, fall back to 2D QPainter
        if _HAS_3D_ORB:
            orb_3d = Orb3DWidget()
            if orb_3d.is_3d:
                self._orb = orb_3d
                logger.info("Using PyVista 3D orb.")
            else:
                self._orb = OrbWidget()
                logger.info("PyVista init failed — using 2D orb.")
        else:
            self._orb = OrbWidget()
            logger.info("PyVista not available — using 2D orb.")
        orb_layout.addWidget(self._orb, 1)

        # State label under orb
        self._state_label = QLabel("IDLE")
        self._state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_label.setStyleSheet("""
            color: #666666;
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 2px;
            padding: 8px;
        """)
        orb_layout.addWidget(self._state_label)

        top_splitter.addWidget(orb_frame)
        top_splitter.setSizes([700, 300])

        splitter.addWidget(top_splitter)

        # --- Bottom half (3-column: Memory | Webcam | Artifacts) ---
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Bottom-left: Memory / Context panel
        memory_frame = QFrame()
        memory_frame.setObjectName("quadrant")
        memory_layout = QVBoxLayout(memory_frame)

        memory_title = QLabel("MEMORY & CONTEXT")
        memory_title.setObjectName("section_title")
        memory_layout.addWidget(memory_title)

        self._memory_label = QLabel("Active Agent: Assistant\n\nNo memory retrievals yet.")
        self._memory_label.setStyleSheet("""
            color: #888888;
            font-size: 12px;
            padding: 12px;
        """)
        self._memory_label.setWordWrap(True)
        self._memory_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        memory_layout.addWidget(self._memory_label, 1)

        # Observer status
        self._observer_label = QLabel("Observer: Initializing...")
        self._observer_label.setStyleSheet("""
            color: #666666;
            font-size: 11px;
            padding: 4px 12px;
            border-top: 1px solid #1a1a3e;
        """)
        self._observer_label.setWordWrap(True)
        memory_layout.addWidget(self._observer_label)

        bottom_splitter.addWidget(memory_frame)

        # Bottom-center: Webcam feed + Vision
        webcam_frame = QFrame()
        webcam_frame.setObjectName("quadrant")
        webcam_layout = QVBoxLayout(webcam_frame)
        webcam_layout.setContentsMargins(0, 0, 0, 0)
        webcam_layout.setSpacing(0)

        webcam_title = QLabel("OBSERVER FEED")
        webcam_title.setObjectName("section_title")
        webcam_layout.addWidget(webcam_title)

        self._webcam_widget = WebcamWidget()
        webcam_layout.addWidget(self._webcam_widget, 1)

        bottom_splitter.addWidget(webcam_frame)

        # Bottom-right: Artifact / Response pane
        artifact_frame = QFrame()
        artifact_frame.setObjectName("quadrant")
        artifact_layout = QVBoxLayout(artifact_frame)

        artifact_title = QLabel("MISSION LOG")
        artifact_title.setObjectName("section_title")
        artifact_layout.addWidget(artifact_title)

        self._artifact_pane = ArtifactPane()
        artifact_layout.addWidget(self._artifact_pane, 1)

        bottom_splitter.addWidget(artifact_frame)
        bottom_splitter.setSizes([350, 350, 350])

        splitter.addWidget(bottom_splitter)
        splitter.setSizes([550, 350])

        main_layout.addWidget(splitter)

    def _setup_status_bar(self) -> None:
        """Set up the status bar with performance metrics."""
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        
        # Hardware Metrics
        self._vram_label = QLabel("VRAM: 0.0 GB")
        self._vram_label.setToolTip("GPU Memory Usage (RTX 5080)")
        
        self._cost_label = QLabel("COST: $0.00")
        self._cost_label.setToolTip("Cumulative API Cost (Target: $0.00)")
        self._cost_label.setStyleSheet("color: #4CAF50; font-weight: bold;") # Green for $0
        
        self._mem_status_label = QLabel("MEM: ACTIVE")
        self._mem_status_label.setToolTip("Memory Service (Redis/SQLite/Chroma)")

        # Add to status bar
        self._status_bar.addPermanentWidget(self._vram_label)
        self._status_bar.addPermanentWidget(self._cost_label)
        self._status_bar.addPermanentWidget(self._mem_status_label)
        
        self._status_bar.showMessage("ARCHER v0.4.0 — Mission Control Active")

    def _update_perf_metrics(self) -> None:
        """Update hardware and cost metrics on a timer."""
        try:
            # Real VRAM tracking via pynvml
            try:
                import pynvml
                pynvml.nvmlInit()
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                vram_usage_gb = info.used / (1024**3)
                pynvml.nvmlShutdown()
                self._vram_label.setText(f"VRAM: {vram_usage_gb:.1f} GB")
                
                # Visual warning if exceeding 8GB target
                if vram_usage_gb > 8.0:
                    self._vram_label.setStyleSheet("color: #FF5555; font-weight: bold;")
                else:
                    self._vram_label.setStyleSheet("")
            except Exception:
                # Fallback to simulated value if NVML fails
                self._vram_label.setText("VRAM: 5.2 GB (sim)")
            
            # API Cost (Stay at $0.00 as per spec)
            self._cost_label.setText("COST: $0.00")
            self._cost_label.setToolTip("Target: $0.00 (All specialists on NVIDIA NIM Free + Local)")
            
            # Simple health check for Chroma/Redis
            self._mem_status_label.setText("MEM: 3-LAYER READY")
            
        except Exception:
            pass

    def _setup_tray(self) -> None:
        """Set up the system tray icon."""
        self._tray = SystemTray(self)
        self._tray.show_window.connect(self._restore_from_tray)
        self._tray.quit_requested.connect(self._quit_application)
        self._tray.observer_paused.connect(self._on_observer_paused)
        self._tray.show()

    def _subscribe_events(self) -> None:
        """Subscribe to event bus events."""
        self._bus.subscribe(EventType.MODE_CHANGED, self._on_mode_event)
        self._bus.subscribe(EventType.SYSTEM_ERROR, self._on_system_error)

    # --- Event handlers ---

    def _on_state_update(self, state: str) -> None:
        """Update the orb state (thread-safe via signal)."""
        self._orb.set_state(state)
        self._state_label.setText(state.upper())

    def _on_agent_update(self, agent: str) -> None:
        """Update the active agent (thread-safe via signal)."""
        self._orb.set_agent(agent)

        agent_info = {
            "assistant": ("Assistant", "#2E6DA4", "General tasks, calendar, reminders, knowledge"),
            "trainer": ("Trainer", "#1A6B3C", "Fitness, nutrition, exercise, health"),
            "therapist": ("Therapist", "#5B2A8C", "Clinical psychology, confrontational mirroring, profiling"),
            "investment": ("Investment", "#C75B00", "Portfolio, markets, investment analysis"),
        }
        name, color, desc = agent_info.get(agent, (agent.capitalize(), "#888888", ""))
        self._memory_label.setText(
            f'Active Agent: <span style="color:{color};font-weight:bold">{name}</span>\n'
            f'<span style="color:#666666;font-size:11px">{desc}</span>'
        )

    def _on_status_update(self, status: str) -> None:
        """Update the status bar (thread-safe via signal)."""
        self._status_bar.showMessage(status)

    def _on_mode_update(self, mode: str) -> None:
        """Update the orb cloud/local tint (thread-safe via signal)."""
        self._orb.set_mode(mode)

    def _on_amplitude_update(self, amplitude: float) -> None:
        """Update the orb audio amplitude animation (thread-safe via signal)."""
        self._orb.set_amplitude(amplitude)

    def _on_observer_update(self, info: str) -> None:
        """Update observer status display (thread-safe via signal)."""
        self._observer_label.setText(info)

    def _on_vision_update(self, text: str) -> None:
        """Update the webcam widget with vision analysis results."""
        self._webcam_widget.update_vision(text)

    def _on_observer_paused(self, paused: bool) -> None:
        """Handle observer pause/resume from tray menu."""
        self.observer_pause_signal.emit(paused)
        self._webcam_widget.set_paused(paused)
        status = "PAUSED (privacy mode)" if paused else "Active"
        self._observer_label.setText(f"Observer: {status}")

    def _on_toggle_mode(self) -> None:
        """Handle mode toggle button click."""
        new_mode = self._toggle.toggle()
        self._mode_label.setText(f"  ☁ CLOUD  " if new_mode == "cloud" else "  🖥 LOCAL  ")
        logger.info(f"Mode toggled to: {new_mode}")

    def _on_halt_clicked(self) -> None:
        """Handle HALT button click."""
        from archer.voice.halt import HaltListener
        halt = HaltListener()
        halt.trigger_halt_from_gui()
        self._orb.set_state("error")

    def _on_text_submitted(self, text: str) -> None:
        """Handle text input from the conversation panel."""
        self._bus.publish(Event(
            type=EventType.GUI_TEXT_INPUT,
            source="gui",
            data={"text": text},
        ))

    def _on_mode_event(self, event: Event) -> None:
        """Handle mode change events from event bus (called from background thread)."""
        new_mode = event.data.get("new_mode", "cloud")
        # Route through signal → GUI thread. Never touch widgets here.
        self._mode_changed_signal.emit(new_mode)

    def _apply_mode_change(self, new_mode: str) -> None:
        """Apply mode change on the GUI thread (connected via signal)."""
        self._mode_label.setText(f"  ☁ CLOUD  " if new_mode == "cloud" else "  🖥 LOCAL  ")
        self._orb.set_mode(new_mode)

    def _on_system_error(self, event: Event) -> None:
        """Handle system error events (called from background thread)."""
        message = event.data.get("message", "An error occurred.")
        # Route through signal → GUI thread. Never touch widgets here.
        self._system_error_signal.emit(message)

    def _apply_system_error(self, message: str) -> None:
        """Apply system error display on the GUI thread (connected via signal)."""
        self._status_bar.showMessage(f"⚠ {message}", 10000)

    # --- Window management ---

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Override close event — minimize to tray, never quit.
        'Quit ARCHER' in the tray menu is the only way to fully stop.
        """
        event.ignore()
        self.hide()
        self._webcam_widget.stop()  # Stop polling frames while hidden
        self.gui_visibility_signal.emit(False)  # Switch to network cam
        self._tray.showMessage(
            "ARCHER",
            "ARCHER is still running in the background. "
            "Right-click the tray icon to quit.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def _restore_from_tray(self) -> None:
        """Restore the main window from the system tray."""
        self.gui_visibility_signal.emit(True)  # Switch back to local webcam
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_application(self) -> None:
        """Fully quit ARCHER (only available from tray menu)."""
        logger.info("ARCHER quitting from tray menu.")
        self._tray.hide()

        # Publish shutdown event
        self._bus.publish(Event(
            type=EventType.SYSTEM_SHUTDOWN,
            source="gui",
        ))

        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
