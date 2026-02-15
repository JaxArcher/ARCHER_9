"""
ARCHER Animated Orb Widget.

The orb is the visual heart of ARCHER. Its color and animation style
communicate the system state and active agent at a glance.

State Colors:
- Idle: Off-white (#CCCCCC) — slow ambient breathe
- Listening: Blue pulse (#2E6DA4)
- Thinking: Amber pulse (#C78C00)
- Speaking: Green (#1A6B3C)
- Error/HALT: Red strobe (#9B2335)

Agent Colors:
- Assistant: Calm blue (#2E6DA4)
- Trainer: Strong green (#1A6B3C)
- Therapist: Soft purple (#5B2A8C)
- Finance: Amber gold (#8C6B00)
- Investment: Deep orange (#C75B00)
- Observer: Neutral gray (#888888)

Mode Tint:
- Cloud: slightly warmer (shift hue toward warm)
- Local: slightly cooler (shift hue toward cool)

Color transitions are smooth cross-fades (300ms), not instant snaps.
Audio amplitude drives the orb size during speaking state.
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QRadialGradient,
    QPen,
    QBrush,
)
from PyQt6.QtWidgets import QWidget


class OrbColors:
    """Orb color constants."""
    IDLE = QColor(204, 204, 204)         # Off-white
    LISTENING = QColor(46, 109, 164)     # Calm blue
    THINKING = QColor(199, 140, 0)       # Amber
    SPEAKING = QColor(26, 107, 60)       # Green
    ERROR = QColor(155, 35, 53)          # Alert red
    HALT = QColor(155, 35, 53)           # Alert red

    # Agent-specific
    ASSISTANT = QColor(46, 109, 164)     # Calm blue
    TRAINER = QColor(26, 107, 60)        # Strong green
    THERAPIST = QColor(91, 42, 140)      # Soft purple
    FINANCE = QColor(140, 107, 0)        # Amber gold
    INVESTMENT = QColor(199, 91, 0)      # Deep orange
    OBSERVER = QColor(136, 136, 136)     # Neutral gray


class OrbWidget(QWidget):
    """
    Animated orb visualization widget.

    Uses QPainter for smooth 2D rendering with glow effects.
    PyVista 3D orb is planned for Phase 4 — this 2D version provides
    the correct visual language from Day 1.

    The orb animates based on:
    - Pipeline state (idle, listening, thinking, speaking)
    - Active agent (color coding)
    - Cloud/local mode (subtle color tint)
    - Audio amplitude (during speech — drives orb size)
    """

    # Signals for thread-safe state updates
    state_changed = pyqtSignal(str)
    agent_changed = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    amplitude_changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # State
        self._current_color = OrbColors.IDLE
        self._target_color = OrbColors.IDLE
        self._state = "idle"
        self._agent = "assistant"
        self._mode = "cloud"  # cloud/local — affects color tint
        self._animation_phase = 0.0
        self._amplitude = 0.0

        # Color transition
        self._transition_progress = 1.0
        self._transition_start_color = OrbColors.IDLE

        # Animation timer (60fps)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(16)  # ~60fps

        # Start time for smooth animations
        self._start_time = time.monotonic()

        # Connect signals for thread-safe updates
        self.state_changed.connect(self._set_state_internal)
        self.agent_changed.connect(self._set_agent_internal)
        self.mode_changed.connect(self._set_mode_internal)
        self.amplitude_changed.connect(self._set_amplitude_internal)

        # Widget settings
        self.setMinimumSize(200, 200)
        self.setStyleSheet("background: transparent;")

    def set_state(self, state: str) -> None:
        """Set the orb state (thread-safe)."""
        self.state_changed.emit(state)

    def set_agent(self, agent: str) -> None:
        """Set the active agent (thread-safe)."""
        self.agent_changed.emit(agent)

    def set_mode(self, mode: str) -> None:
        """Set the cloud/local mode (thread-safe)."""
        self.mode_changed.emit(mode)

    def set_amplitude(self, amplitude: float) -> None:
        """Set the audio amplitude for speech animation (thread-safe, 0.0-1.0)."""
        self.amplitude_changed.emit(amplitude)

    def _set_state_internal(self, state: str) -> None:
        """Internal state setter (runs on GUI thread)."""
        self._state = state
        self._start_color_transition(self._get_state_color(state))

    def _set_agent_internal(self, agent: str) -> None:
        """Internal agent setter (runs on GUI thread)."""
        self._agent = agent
        if self._state == "speaking":
            self._start_color_transition(self._get_agent_color(agent))

    def _set_mode_internal(self, mode: str) -> None:
        """Internal mode setter (runs on GUI thread)."""
        self._mode = mode
        # Re-apply current state color with new mode tint
        self._start_color_transition(self._get_state_color(self._state))

    def _set_amplitude_internal(self, amplitude: float) -> None:
        """Internal amplitude setter (runs on GUI thread)."""
        self._amplitude = max(0.0, min(1.0, amplitude))

    def _get_state_color(self, state: str) -> QColor:
        """Get the color for a pipeline state, with cloud/local mode tint."""
        colors = {
            "idle": OrbColors.IDLE,
            "listening": OrbColors.LISTENING,
            "processing": OrbColors.THINKING,
            "speaking": self._get_agent_color(self._agent),
            "error": OrbColors.ERROR,
        }
        base = colors.get(state, OrbColors.IDLE)
        return self._apply_mode_tint(base)

    def _get_agent_color(self, agent: str) -> QColor:
        """Get the color for an agent."""
        colors = {
            "assistant": OrbColors.ASSISTANT,
            "trainer": OrbColors.TRAINER,
            "therapist": OrbColors.THERAPIST,
            "finance": OrbColors.FINANCE,
            "investment": OrbColors.INVESTMENT,
            "observer": OrbColors.OBSERVER,
        }
        return colors.get(agent, OrbColors.ASSISTANT)

    def _apply_mode_tint(self, color: QColor) -> QColor:
        """Apply a subtle warm/cool tint based on cloud/local mode.

        Cloud mode: slightly warmer (shift hue toward orange, +5)
        Local mode: slightly cooler (shift hue toward blue, -5)
        """
        h, s, l, a = color.getHslF()
        if h < 0:
            # Achromatic (gray/white) — tint by adjusting saturation instead
            if self._mode == "cloud":
                # Add subtle warm saturation
                return QColor.fromHslF(0.08, 0.08, l, a)  # Warm off-white
            else:
                # Add subtle cool saturation
                return QColor.fromHslF(0.58, 0.08, l, a)  # Cool off-white
        else:
            shift = 0.015 if self._mode == "cloud" else -0.015
            h = (h + shift) % 1.0
            result = QColor()
            result.setHslF(h, s, l, a)
            return result

    def _start_color_transition(self, target: QColor) -> None:
        """Start a smooth 300ms color transition."""
        self._transition_start_color = QColor(self._current_color)
        self._target_color = target
        self._transition_progress = 0.0

    def _animate(self) -> None:
        """Animation tick — called at ~60fps."""
        elapsed = time.monotonic() - self._start_time
        self._animation_phase = elapsed

        # Color transition (300ms)
        if self._transition_progress < 1.0:
            self._transition_progress = min(1.0, self._transition_progress + 0.053)  # ~300ms
            t = self._ease_in_out(self._transition_progress)
            self._current_color = self._lerp_color(
                self._transition_start_color, self._target_color, t
            )

        self.update()

    def _ease_in_out(self, t: float) -> float:
        """Smooth ease-in-out curve."""
        return t * t * (3 - 2 * t)

    def _lerp_color(self, a: QColor, b: QColor, t: float) -> QColor:
        """Linear interpolation between two colors."""
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            int(a.alpha() + (b.alpha() - a.alpha()) * t),
        )

    def paintEvent(self, event) -> None:
        """Paint the orb with glow, pulse, and state-specific animations."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        center_x = w / 2
        center_y = h / 2
        base_radius = min(w, h) * 0.35

        # Calculate pulse based on state and audio amplitude
        pulse = self._get_pulse()
        radius = base_radius * (1.0 + pulse * 0.08)

        # --- Outer glow ---
        glow_color = QColor(self._current_color)
        glow_color.setAlpha(30)
        glow_gradient = QRadialGradient(center_x, center_y, radius * 1.8)
        glow_gradient.setColorAt(0.0, QColor(self._current_color.red(),
                                              self._current_color.green(),
                                              self._current_color.blue(), 40))
        glow_gradient.setColorAt(0.5, QColor(self._current_color.red(),
                                              self._current_color.green(),
                                              self._current_color.blue(), 15))
        glow_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setBrush(QBrush(glow_gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            QRectF(center_x - radius * 1.8, center_y - radius * 1.8,
                   radius * 3.6, radius * 3.6)
        )

        # --- Main orb body ---
        orb_gradient = QRadialGradient(
            center_x - radius * 0.3,
            center_y - radius * 0.3,
            radius * 1.2,
        )

        bright_color = QColor(self._current_color)
        bright_color = self._lighten(bright_color, 0.3)
        dark_color = QColor(self._current_color)
        dark_color = self._darken(dark_color, 0.3)

        orb_gradient.setColorAt(0.0, bright_color)
        orb_gradient.setColorAt(0.6, self._current_color)
        orb_gradient.setColorAt(1.0, dark_color)

        painter.setBrush(QBrush(orb_gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)
        )

        # --- Specular highlight ---
        highlight_gradient = QRadialGradient(
            center_x - radius * 0.2,
            center_y - radius * 0.35,
            radius * 0.5,
        )
        highlight_gradient.setColorAt(0.0, QColor(255, 255, 255, 100))
        highlight_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))

        painter.setBrush(QBrush(highlight_gradient))
        painter.drawEllipse(
            QRectF(center_x - radius * 0.6, center_y - radius * 0.7,
                   radius * 0.9, radius * 0.7)
        )

        # --- Outer ring (subtle) ---
        ring_color = QColor(self._current_color)
        ring_color.setAlpha(80)
        pen = QPen(ring_color, 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        ring_radius = radius * 1.15
        painter.drawEllipse(
            QRectF(center_x - ring_radius, center_y - ring_radius,
                   ring_radius * 2, ring_radius * 2)
        )

        painter.end()

    def _get_pulse(self) -> float:
        """Get the current pulse value based on state and audio amplitude."""
        t = self._animation_phase

        if self._state == "idle":
            # Very slow ambient breathe
            return math.sin(t * 0.5) * 0.3

        elif self._state == "listening":
            # Blue pulse — attentive, responds to mic amplitude
            return math.sin(t * 2.0) * 0.5 + self._amplitude * 0.3

        elif self._state == "processing":
            # Amber pulse — thinking
            return math.sin(t * 3.0) * 0.4

        elif self._state == "speaking":
            # Agent-colored — animates with TTS audio amplitude
            return self._amplitude * 0.6 + math.sin(t * 1.5) * 0.2

        elif self._state == "error":
            # Red strobe
            return abs(math.sin(t * 8.0))

        return 0.0

    def _lighten(self, color: QColor, amount: float) -> QColor:
        """Lighten a color by the given amount (0.0-1.0)."""
        h, s, l, a = color.getHslF()
        l = min(1.0, l + amount)
        c = QColor()
        c.setHslF(h, s, l, a)
        return c

    def _darken(self, color: QColor, amount: float) -> QColor:
        """Darken a color by the given amount (0.0-1.0)."""
        h, s, l, a = color.getHslF()
        l = max(0.0, l - amount)
        c = QColor()
        c.setHslF(h, s, l, a)
        return c
