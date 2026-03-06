from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWidgets import QApplication
import os

# CRITICAL: Must set this BEFORE importing QWebEngineWidgets
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from PyQt6.QtWebEngineWidgets import QWebEngineView


class CanvasWidget(QWebEngineView):
    '''Canvas widget for displaying rich artifacts from agents.'''
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet('background: #1e1e1e;')
        self.setup_artifact_subscription()
    
    def setup_artifact_subscription(self):
        '''Subscribe to artifact display events.'''
        from archer.core.event_bus import EventType, get_event_bus
        bus = get_event_bus()
        bus.subscribe(EventType.ARTIFACT_DISPLAY, self._on_artifact_display)
    
    def _on_artifact_display(self, event):
        '''Handle artifact display event.'''
        html_path = event.data.get('html_path')
        if html_path and os.path.exists(html_path):
            url = QUrl.fromLocalFile(html_path)
            self.load(url)
