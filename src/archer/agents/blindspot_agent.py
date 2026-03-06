"""
ARCHER Blindspot Agent implementation.
Focuses on behavioral patterns, ADHD specialization, and direct feedback.
"""

from __future__ import annotations
import json
import enum
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store


# Import core blindspot components
from archer.blindspot.adhd_engine import ADHDStateDetector, ADHDPatternLibrary, MedicationTracker
from archer.blindspot.behavioral_detector import TaskCompletionTracker, TimeBlindnessDetector, RoutineAdherenceMonitor
from archer.blindspot.normative_comparator import NormativeStandardsDB, UserBaselineSystem, DeviationAnalyzer
from archer.blindspot.visual_detector import AppearanceAnalyzer, ClutterDetector, AestheticEvaluator, PlantMonitor
from archer.blindspot.relationship_tracker import RelationshipTracker
from archer.blindspot.intervention_engine import DecisionEngine

class BlindspotAgent:
    """
    The Blindspot Agent identifies what the user overlooks and provides accountability.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._store = get_sqlite_store()
        
        # Initialize engines
        self.adhd_detector = ADHDStateDetector()
        self.adhd_patterns = ADHDPatternLibrary()
        self.med_tracker = MedicationTracker(self._store)
        
        self.task_tracker = TaskCompletionTracker(self._store)
        self.time_blindness = TimeBlindnessDetector()
        self.routine_monitor = RoutineAdherenceMonitor(self._store)
        
        self.normative_db = NormativeStandardsDB()
        self.baseline_system = UserBaselineSystem(self._store)
        self.deviation_analyzer = DeviationAnalyzer(self.normative_db, self.baseline_system)
        
        self.appearance_analyzer = AppearanceAnalyzer(self._store)
        self.clutter_detector = ClutterDetector(self._store)
        self.aesthetic_evaluator = AestheticEvaluator()
        self.plant_monitor = PlantMonitor(self._store)
        
        self.rel_tracker = RelationshipTracker(self._store)
        self.decision_engine = DecisionEngine(self._store)
        
        self._subscribe_events()
        logger.info("Blindspot Agent initialized.")

    def _subscribe_events(self) -> None:
        """Subscribe to relevant event bus channels."""
        self._bus.subscribe(EventType.OBSERVATION_EVENT, self._on_observation)
        self._bus.subscribe(EventType.STT_FINAL, self._on_utterance)
        self._bus.subscribe(EventType.ACTION_COMPLETED, self._on_action)

    def _on_observation(self, event: Event) -> None:
        """Handle vision/system observations."""
        payload = event.data.get("payload", {})
        source = event.data.get("source", "unknown")
        
        if source == "webcam":
            # 1. Update ADHD state
            current_state = self.adhd_detector.detect_current_state(payload)
            
            # 2. Extract specific issues
            issues = []
            
            # Appearance
            grooming = self.appearance_analyzer.analyze_grooming(payload)
            if grooming.get('needs_shave'):
                issues.append({'category': 'hygiene', 'metric': 'shave_needs', 'deviation_from_baseline': 0.4})
            
            # Clutter
            clutter = self.clutter_detector.measure_clutter("desk", payload)
            if clutter.get('clutter_score', 0.0) > 0.4:
                issues.append({'category': 'household', 'metric': 'clutter', 'deviation_from_baseline': clutter['clutter_score']})
            
            # Plants
            plants = self.plant_monitor.assess_plants(payload)
            for p in plants:
                if p.get('needs_water'):
                    issues.append({'category': 'household', 'metric': 'plant_watering', 'deviation_from_baseline': 0.6})
            
            # 3. Decision Engine
            intervention = self.decision_engine.decide_intervention(issues, current_state)
            if intervention:
                self._dispatch_intervention(intervention)

    def _on_utterance(self, event: Event) -> None:
        """Handle user speech for relational/task tracking."""
        text = event.data.get("text", "").lower()
        
        # Track commitments (heuristic-based)
        if "tell" in text and ("i'll" in text or "i will" in text):
            # Extract name and promise
            # Example: "Tell Mike I'll call him later"
            self.rel_tracker.track_commitment("unknown", text)
            
        # Track time estimates
        if "5 minutes" in text or "minutes" in text:
            # self.time_blindness.track_estimate(...)
            pass

    def _on_action(self, event: Event) -> None:
        """Handle agent actions (audit)."""
        pass

    def _dispatch_intervention(self, intervention: Dict[str, Any]) -> None:
        """Send intervention event for the orchestrator to handle."""
        # This would publish an AGENT_INTERVENTION event
        # Logic to skip if on cooldown
        logger.info(f"Dispatching Blindspot intervention: {intervention['issue']}")
        self._bus.publish(Event(
            type=EventType.MODE_CHANGED, # Placeholder for now or new event type
            data={
                "agent": "blindspot",
                "content": intervention['issue'],
                "strategy": intervention['strategy']
            }
        ))
