"""
ARCHER Artifact Pane.

The bottom-right quadrant of the GUI — a dynamic, context-aware
rendering surface where agents push rich visual content alongside
the conversation. Supports charts, tables, documents, code, images,
web previews, dashboards, and checklists.

Driven by ArtifactPayload objects emitted by agents. Each artifact
gets a tab in the pane's tab bar. Up to 5 recent artifacts are shown
as tabs; older ones are accessible via the history button.

Agent color coding carries through to tab labels and content headers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QPixmap
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTabBar,
    QTextEdit,
    QPushButton,
    QFrame,
    QScrollArea,
    QStackedWidget,
    QSizePolicy,
)

from loguru import logger

from archer.core.event_bus import Event, EventType, get_event_bus


# Agent color map (matches conversation.py and orb_widget.py)
_AGENT_COLORS = {
    "assistant": "#2E6DA4",
    "trainer": "#1A6B3C",
    "therapist": "#5B2A8C",
    "finance": "#8C6B00",
    "investment": "#C75B00",
    "observer": "#888888",
    "system": "#666666",
}

# Type icons for tab labels
_TYPE_ICONS = {
    "chart": "\U0001F4CA",      # 📊
    "table": "\U0001F4CB",      # 📋
    "document": "\U0001F4C4",   # 📄
    "code": "\U0001F4BB",       # 💻
    "image": "\U0001F5BC",      # 🖼
    "web": "\U0001F310",        # 🌐
    "dashboard": "\U0001F4F1",  # 📱
    "checklist": "\u2611",      # ☑
}

MAX_TABS = 5


@dataclass
class ArtifactPayload:
    """A rich artifact pushed by an agent to the Artifact Pane."""

    type: str          # chart, table, document, code, image, web, dashboard, checklist
    title: str         # Short label (e.g., "Portfolio", "Budget")
    content: Any       # Type-specific content
    agent: str         # Agent that created this artifact
    timestamp: datetime = field(default_factory=datetime.now)


class ArtifactPane(QWidget):
    """
    Tabbed artifact rendering pane.

    Agents push ArtifactPayload objects via the event bus. Each artifact
    becomes a tab in the pane. The pane auto-switches to the newest
    artifact unless the user has manually selected a previous tab.
    """

    # Signal for thread-safe artifact delivery
    artifact_received_signal = pyqtSignal(object)  # ArtifactPayload

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = get_event_bus()
        self._artifacts: list[ArtifactPayload] = []
        self._user_selected_tab = False  # True if user manually clicked a tab
        self._setup_ui()
        self._connect_events()

    def _setup_ui(self) -> None:
        """Build the artifact pane UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._tabs.setMovable(False)
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #0d0d1a;
            }
            QTabBar::tab {
                background: #12122a;
                color: #888888;
                border: 1px solid #1a1a3e;
                border-bottom: none;
                padding: 4px 12px;
                margin-right: 2px;
                font-size: 11px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #0d0d1a;
                color: #cccccc;
                border-bottom: none;
            }
            QTabBar::tab:hover {
                color: #aaaaaa;
            }
        """)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Add idle state tab
        self._add_idle_tab()

        layout.addWidget(self._tabs)

    def _connect_events(self) -> None:
        """Connect event bus and signals."""
        self.artifact_received_signal.connect(self._handle_artifact)
        self._bus.subscribe(EventType.ARTIFACT_PUSH, self._on_artifact_event)

    def _on_artifact_event(self, event: Event) -> None:
        """Handle artifact push from event bus (background thread)."""
        try:
            payload = ArtifactPayload(
                type=event.data.get("type", "document"),
                title=event.data.get("title", "Artifact"),
                content=event.data.get("content", ""),
                agent=event.data.get("agent", "assistant"),
            )
            self.artifact_received_signal.emit(payload)
        except Exception as e:
            logger.error(f"Artifact event handling failed: {e}")

    def _on_tab_changed(self, index: int) -> None:
        """User manually selected a tab."""
        self._user_selected_tab = True

    def push_artifact(self, payload: ArtifactPayload) -> None:
        """Push an artifact to the pane (thread-safe)."""
        self.artifact_received_signal.emit(payload)

    def _handle_artifact(self, payload: ArtifactPayload) -> None:
        """Add a new artifact tab (GUI thread)."""
        self._artifacts.append(payload)

        # Remove idle tab if it's the only tab
        if self._tabs.count() == 1 and self._tabs.tabText(0) == "ARCHER":
            self._tabs.removeTab(0)

        # Create the content widget based on type
        content_widget = self._create_content_widget(payload)

        # Build tab label with icon and agent color
        icon = _TYPE_ICONS.get(payload.type, "\U0001F4C4")
        label = f"{icon} {payload.title}"

        # Add tab
        index = self._tabs.addTab(content_widget, label)

        # Color the tab text to match the agent
        color = QColor(_AGENT_COLORS.get(payload.agent, "#888888"))
        self._tabs.tabBar().setTabTextColor(index, color)

        # Remove excess tabs (keep MAX_TABS)
        while self._tabs.count() > MAX_TABS:
            self._tabs.removeTab(0)
            if self._artifacts and len(self._artifacts) > MAX_TABS:
                self._artifacts.pop(0)

        # Auto-switch to new tab unless user manually selected another
        if not self._user_selected_tab:
            self._tabs.setCurrentIndex(self._tabs.count() - 1)
        self._user_selected_tab = False  # Reset for next auto-switch

        logger.info(f"Artifact pushed: {payload.type} — '{payload.title}' from {payload.agent}")

    def _create_content_widget(self, payload: ArtifactPayload) -> QWidget:
        """Create the appropriate widget for the artifact type."""
        if payload.type == "chart":
            return self._create_chart_widget(payload)
        elif payload.type == "table":
            return self._create_table_widget(payload)
        elif payload.type == "code":
            return self._create_code_widget(payload)
        elif payload.type == "checklist":
            return self._create_checklist_widget(payload)
        elif payload.type == "image":
            return self._create_image_widget(payload)
        elif payload.type == "dashboard":
            return self._create_dashboard_widget(payload)
        else:
            return self._create_document_widget(payload)

    def _create_document_widget(self, payload: ArtifactPayload) -> QWidget:
        """Create a scrollable text document widget."""
        widget = QTextEdit()
        widget.setReadOnly(True)
        widget.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d1a;
                color: #cccccc;
                border: none;
                padding: 16px;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 13px;
            }
        """)

        color = _AGENT_COLORS.get(payload.agent, "#888888")
        header = (
            f'<div style="margin-bottom: 12px;">'
            f'<span style="color:{color}; font-weight:bold; font-size:15px;">'
            f'{payload.title}</span>'
            f'<span style="color:#666; font-size:11px; margin-left:12px;">'
            f'{payload.agent.capitalize()} — {payload.timestamp.strftime("%H:%M")}</span>'
            f'</div><hr style="border-color:#1a1a3e;"/>'
        )

        content = str(payload.content) if payload.content else ""
        widget.setHtml(header + f'<div style="margin-top:12px;">{content}</div>')
        return widget

    def _create_code_widget(self, payload: ArtifactPayload) -> QWidget:
        """Create a syntax-highlighted code block with copy button."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header with copy button
        header_layout = QHBoxLayout()
        color = _AGENT_COLORS.get(payload.agent, "#888888")
        title = QLabel(f'<span style="color:{color}; font-weight:bold;">{payload.title}</span>')
        header_layout.addWidget(title)
        header_layout.addStretch()

        copy_btn = QPushButton("Copy")
        copy_btn.setFixedSize(60, 24)
        copy_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a3e;
                color: #aaa;
                border: 1px solid #333355;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover { border-color: #2E6DA4; }
        """)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(str(payload.content)))
        header_layout.addWidget(copy_btn)
        layout.addLayout(header_layout)

        # Code block
        code_edit = QTextEdit()
        code_edit.setReadOnly(True)
        code_edit.setPlainText(str(payload.content))
        code_edit.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a15;
                color: #88CC88;
                border: 1px solid #1a1a3e;
                border-radius: 4px;
                padding: 12px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(code_edit)

        container.setStyleSheet("background-color: #0d0d1a;")
        return container

    def _create_table_widget(self, payload: ArtifactPayload) -> QWidget:
        """Create an HTML table rendering."""
        widget = QTextEdit()
        widget.setReadOnly(True)
        widget.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d1a;
                color: #cccccc;
                border: none;
                padding: 12px;
                font-size: 13px;
            }
        """)

        color = _AGENT_COLORS.get(payload.agent, "#888888")
        content = payload.content

        # If content is a list of dicts, render as HTML table
        if isinstance(content, list) and content and isinstance(content[0], dict):
            headers = list(content[0].keys())
            table_html = f'<table style="width:100%; border-collapse:collapse;">'
            table_html += '<tr>'
            for h in headers:
                table_html += (
                    f'<th style="padding:6px 12px; text-align:left; '
                    f'border-bottom:2px solid {color}; color:{color}; '
                    f'font-size:11px; text-transform:uppercase;">{h}</th>'
                )
            table_html += '</tr>'
            for row in content:
                table_html += '<tr>'
                for h in headers:
                    val = row.get(h, "")
                    table_html += (
                        f'<td style="padding:6px 12px; border-bottom:1px solid #1a1a3e;">'
                        f'{val}</td>'
                    )
                table_html += '</tr>'
            table_html += '</table>'
        else:
            table_html = str(content)

        header = (
            f'<div style="margin-bottom:8px;">'
            f'<span style="color:{color}; font-weight:bold;">{payload.title}</span></div>'
        )
        widget.setHtml(header + table_html)
        return widget

    def _create_chart_widget(self, payload: ArtifactPayload) -> QWidget:
        """
        Create a chart widget.

        Content can be:
        - A base64 PNG string (pre-rendered matplotlib chart)
        - A dict with chart data (rendered via matplotlib if available)
        """
        widget = QLabel()
        widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        widget.setStyleSheet("background-color: #0d0d1a; padding: 12px;")

        content = payload.content

        if isinstance(content, str) and len(content) > 100:
            # Assume base64 PNG
            try:
                import base64
                pixmap = QPixmap()
                pixmap.loadFromData(base64.b64decode(content))
                widget.setPixmap(pixmap.scaled(
                    800, 500,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            except Exception as e:
                widget.setText(f"Chart rendering failed: {e}")
        else:
            color = _AGENT_COLORS.get(payload.agent, "#888888")
            widget.setText(
                f'<div style="color:{color}; font-size:14px;">'
                f'<b>{payload.title}</b><br/><br/>'
                f'{str(content)}</div>'
            )
        return widget

    def _create_image_widget(self, payload: ArtifactPayload) -> QWidget:
        """Create an image display widget."""
        widget = QLabel()
        widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        widget.setStyleSheet("background-color: #0d0d1a; padding: 12px;")

        try:
            import base64
            pixmap = QPixmap()
            if isinstance(payload.content, str):
                pixmap.loadFromData(base64.b64decode(payload.content))
            widget.setPixmap(pixmap.scaled(
                800, 600,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        except Exception:
            widget.setText("Image could not be displayed.")
        return widget

    def _create_dashboard_widget(self, payload: ArtifactPayload) -> QWidget:
        """Create a metrics dashboard widget."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        container.setStyleSheet("background-color: #0d0d1a;")

        color = _AGENT_COLORS.get(payload.agent, "#888888")
        title = QLabel(
            f'<span style="color:{color}; font-weight:bold; font-size:15px;">'
            f'{payload.title}</span>'
        )
        layout.addWidget(title)

        content = payload.content
        if isinstance(content, dict):
            for key, value in content.items():
                metric = QLabel(
                    f'<div style="margin:8px 0;">'
                    f'<span style="color:#666; font-size:11px; text-transform:uppercase;">'
                    f'{key}</span><br/>'
                    f'<span style="color:#cccccc; font-size:20px; font-weight:bold;">'
                    f'{value}</span></div>'
                )
                layout.addWidget(metric)
        else:
            fallback = QLabel(str(content))
            fallback.setStyleSheet("color: #cccccc;")
            layout.addWidget(fallback)

        layout.addStretch()
        return container

    def _create_checklist_widget(self, payload: ArtifactPayload) -> QWidget:
        """Create an interactive checklist widget."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        container.setStyleSheet("background-color: #0d0d1a;")

        color = _AGENT_COLORS.get(payload.agent, "#888888")
        title = QLabel(
            f'<span style="color:{color}; font-weight:bold; font-size:15px;">'
            f'{payload.title}</span>'
        )
        layout.addWidget(title)

        content = payload.content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text", str(item))
                    checked = item.get("checked", False)
                else:
                    text = str(item)
                    checked = False

                from PyQt6.QtWidgets import QCheckBox
                cb = QCheckBox(text)
                cb.setChecked(checked)
                cb.setStyleSheet("""
                    QCheckBox {
                        color: #cccccc;
                        font-size: 13px;
                        padding: 4px;
                    }
                    QCheckBox::indicator {
                        width: 16px;
                        height: 16px;
                    }
                """)
                layout.addWidget(cb)
        else:
            fallback = QLabel(str(content))
            fallback.setStyleSheet("color: #cccccc;")
            layout.addWidget(fallback)

        layout.addStretch()
        return container

    def _add_idle_tab(self) -> None:
        """Add the idle/default state tab."""
        idle = QLabel(
            '<div style="text-align:center; padding:40px;">'
            '<div style="color:#2E6DA4; font-size:28px; font-weight:bold; '
            'letter-spacing:3px; margin-bottom:16px;">ARCHER</div>'
            '<div style="color:#555; font-size:13px;">'
            'Advanced Responsive Computing<br/>'
            'Helper & Executive Resource</div>'
            '<div style="color:#333; font-size:12px; margin-top:24px;">'
            'Artifacts from agents will appear here.</div>'
            '</div>'
        )
        idle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idle.setStyleSheet("background-color: #0d0d1a;")
        self._tabs.addTab(idle, "ARCHER")

    def _copy_to_clipboard(self, text: str) -> None:
        """Copy text to the system clipboard."""
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
                logger.info("Copied to clipboard.")
        except Exception as e:
            logger.warning(f"Clipboard copy failed: {e}")
