"""
ARCHER 3D Orb Widget — PyVista Edition.

A 3D animated sphere rendered via PyVista/VTK embedded in PyQt6.
Replaces the Phase 1-3 QPainter 2D orb with a real 3D orb that
rotates, pulses, and shifts color based on agent / state / amplitude.

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

The orb uses a subdivided icosphere with Phong shading, ambient glow
ring, and subtle rotation. Audio amplitude drives the scale factor.

Falls back to the 2D OrbWidget if PyVista/VTK are unavailable.
"""

from __future__ import annotations

import math
import time
import traceback

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from loguru import logger


# Agent → RGB color mapping (0-1 floats for VTK)
_STATE_COLORS = {
    "idle": (0.80, 0.80, 0.80),
    "listening": (0.18, 0.43, 0.64),
    "processing": (0.78, 0.55, 0.00),
    "speaking": (0.10, 0.42, 0.24),
    "error": (0.61, 0.14, 0.21),
}

_AGENT_COLORS = {
    "assistant": (0.18, 0.43, 0.64),
    "trainer": (0.10, 0.42, 0.24),
    "therapist": (0.36, 0.16, 0.55),
    "finance": (0.55, 0.42, 0.00),
    "investment": (0.78, 0.36, 0.00),
    "observer": (0.53, 0.53, 0.53),
}


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation."""
    return a + (b - a) * t


def _lerp_color(
    c1: tuple[float, float, float],
    c2: tuple[float, float, float],
    t: float,
) -> tuple[float, float, float]:
    """Linearly interpolate two RGB tuples."""
    return (_lerp(c1[0], c2[0], t), _lerp(c1[1], c2[1], t), _lerp(c1[2], c2[2], t))


class Orb3DWidget(QWidget):
    """
    PyVista-based 3D animated orb embedded in a PyQt6 widget.

    Provides the same public API as OrbWidget (set_state, set_agent,
    set_mode, set_amplitude) so it's a drop-in replacement.
    """

    # Thread-safe signals (same API as OrbWidget)
    state_changed = pyqtSignal(str)
    agent_changed = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    amplitude_changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._state = "idle"
        self._agent = "assistant"
        self._mode = "cloud"
        self._amplitude = 0.0

        # Color transition
        self._current_color = _STATE_COLORS["idle"]
        self._target_color = _STATE_COLORS["idle"]
        self._transition_progress = 1.0
        self._transition_start_color = _STATE_COLORS["idle"]

        # Animation phase
        self._start_time = time.monotonic()

        # Build the PyVista plotter
        self._plotter = None
        self._sphere_actor = None
        self._glow_actor = None
        self._pyvista_ok = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            import pyvista as pv
            from pyvistaqt import QtInteractor

            # Create the embedded VTK widget
            self._plotter = QtInteractor(self, auto_update=False)
            self._plotter.set_background("#0d0d1a")
            self._plotter.hide_axes()

            # Remove interactor toolbar/menus
            self._plotter.disable_anti_aliasing()
            self._plotter.enable_anti_aliasing("ssaa")

            # Create the main sphere (icosphere-like, subdivided)
            sphere = pv.Sphere(
                radius=1.0,
                center=(0, 0, 0),
                theta_resolution=64,
                phi_resolution=64,
            )
            self._sphere_actor = self._plotter.add_mesh(
                sphere,
                color=self._current_color,
                smooth_shading=True,
                pbr=True,
                metallic=0.15,
                roughness=0.45,
                name="orb_main",
            )

            # Create an outer glow ring (larger, transparent sphere)
            glow = pv.Sphere(
                radius=1.35,
                center=(0, 0, 0),
                theta_resolution=32,
                phi_resolution=32,
            )
            self._glow_actor = self._plotter.add_mesh(
                glow,
                color=self._current_color,
                opacity=0.08,
                smooth_shading=True,
                name="orb_glow",
            )

            # Camera setup: looking at origin
            self._plotter.camera_position = [(0, 0, 4.0), (0, 0, 0), (0, 1, 0)]
            self._plotter.camera.zoom(1.0)

            # Add subtle light
            self._plotter.add_light(pv.Light(
                position=(2, 2, 3),
                focal_point=(0, 0, 0),
                intensity=0.8,
            ))
            self._plotter.add_light(pv.Light(
                position=(-2, -1, 2),
                focal_point=(0, 0, 0),
                intensity=0.3,
            ))

            layout.addWidget(self._plotter.interactor)
            self._pyvista_ok = True
            logger.info("PyVista 3D orb initialized successfully.")

        except Exception as e:
            logger.warning(f"PyVista 3D orb failed to initialize: {e}")
            logger.info("Falling back to 2D orb.")
            traceback.print_exc()
            # Fall back handled by caller checking is_3d

        # Connect signals
        self.state_changed.connect(self._set_state_internal)
        self.agent_changed.connect(self._set_agent_internal)
        self.mode_changed.connect(self._set_mode_internal)
        self.amplitude_changed.connect(self._set_amplitude_internal)

        # Animation timer (~30fps for 3D — less demanding than 60fps 2D)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        if self._pyvista_ok:
            self._timer.start(33)  # ~30fps

        self.setMinimumSize(200, 200)

    @property
    def is_3d(self) -> bool:
        """Return True if the 3D orb is active."""
        return self._pyvista_ok

    # --- Public API (same as OrbWidget) ---

    def set_state(self, state: str) -> None:
        """Set the orb state (thread-safe)."""
        self.state_changed.emit(state)

    def set_agent(self, agent: str) -> None:
        """Set the active agent (thread-safe)."""
        self.agent_changed.emit(agent)

    def set_mode(self, mode: str) -> None:
        """Set cloud/local mode (thread-safe)."""
        self.mode_changed.emit(mode)

    def set_amplitude(self, amplitude: float) -> None:
        """Set audio amplitude for speaking animation (thread-safe)."""
        self.amplitude_changed.emit(amplitude)

    # --- Internal handlers (GUI thread) ---

    def _set_state_internal(self, state: str) -> None:
        self._state = state
        target = self._resolve_color()
        self._start_color_transition(target)

    def _set_agent_internal(self, agent: str) -> None:
        self._agent = agent
        if self._state == "speaking":
            self._start_color_transition(self._resolve_color())

    def _set_mode_internal(self, mode: str) -> None:
        self._mode = mode
        self._start_color_transition(self._resolve_color())

    def _set_amplitude_internal(self, amplitude: float) -> None:
        self._amplitude = max(0.0, min(1.0, amplitude))

    def _resolve_color(self) -> tuple[float, float, float]:
        """Get the target color based on current state/agent/mode."""
        if self._state == "speaking":
            base = _AGENT_COLORS.get(self._agent, _AGENT_COLORS["assistant"])
        else:
            base = _STATE_COLORS.get(self._state, _STATE_COLORS["idle"])

        # Apply subtle warm/cool shift for cloud/local
        r, g, b = base
        if self._mode == "cloud":
            r = min(1.0, r + 0.03)
        else:
            b = min(1.0, b + 0.03)
        return (r, g, b)

    def _start_color_transition(self, target: tuple[float, float, float]) -> None:
        self._transition_start_color = self._current_color
        self._target_color = target
        self._transition_progress = 0.0

    def _animate(self) -> None:
        """Animation tick — ~30fps."""
        if not self._pyvista_ok or self._plotter is None:
            return

        elapsed = time.monotonic() - self._start_time

        # Color transition (300ms)
        if self._transition_progress < 1.0:
            self._transition_progress = min(1.0, self._transition_progress + 0.10)
            t = self._transition_progress * self._transition_progress * (3 - 2 * self._transition_progress)
            self._current_color = _lerp_color(self._transition_start_color, self._target_color, t)

        # Calculate pulse/scale
        pulse = self._get_pulse(elapsed)
        scale = 1.0 + pulse * 0.08

        # Apply rotation (slow ambient rotation)
        rotation_speed = {
            "idle": 0.3,
            "listening": 0.6,
            "processing": 1.2,
            "speaking": 0.8,
            "error": 3.0,
        }.get(self._state, 0.3)

        try:
            import pyvista as pv

            # Update main sphere
            sphere = pv.Sphere(
                radius=scale,
                center=(0, 0, 0),
                theta_resolution=64,
                phi_resolution=64,
                start_theta=elapsed * rotation_speed * 10 % 360,
            )
            self._plotter.update_coordinates(sphere.points, mesh="orb_main", render=False)

            # Update color via actor properties
            if self._sphere_actor is not None:
                prop = self._sphere_actor.GetProperty()
                prop.SetColor(*self._current_color)

            # Update glow
            glow_scale = scale * 1.35 + pulse * 0.05
            glow = pv.Sphere(
                radius=glow_scale,
                center=(0, 0, 0),
                theta_resolution=32,
                phi_resolution=32,
            )
            self._plotter.update_coordinates(glow.points, mesh="orb_glow", render=False)

            if self._glow_actor is not None:
                glow_prop = self._glow_actor.GetProperty()
                glow_prop.SetColor(*self._current_color)
                glow_opacity = 0.06 + abs(pulse) * 0.04
                glow_prop.SetOpacity(glow_opacity)

            # Render
            self._plotter.render()

        except Exception:
            pass  # Silently handle render errors during animation

    def _get_pulse(self, t: float) -> float:
        """Get pulse value based on state."""
        if self._state == "idle":
            return math.sin(t * 0.5) * 0.3
        elif self._state == "listening":
            return math.sin(t * 2.0) * 0.5 + self._amplitude * 0.3
        elif self._state == "processing":
            return math.sin(t * 3.0) * 0.4
        elif self._state == "speaking":
            return self._amplitude * 0.6 + math.sin(t * 1.5) * 0.2
        elif self._state == "error":
            return abs(math.sin(t * 8.0))
        return 0.0

    def closeEvent(self, event) -> None:
        """Clean up the PyVista plotter on close."""
        if self._timer.isActive():
            self._timer.stop()
        if self._plotter is not None:
            try:
                self._plotter.close()
            except Exception:
                pass
        super().closeEvent(event)
