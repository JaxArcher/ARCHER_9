"""
Behavioral Detector for ARCHER Blindspot Agent.
Tracks task completion, time blindness, and routine adherence.
"""

from __future__ import annotations
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from loguru import logger

class TaskCompletionTracker:
    """Tracks task starts, interruptions, and completions."""
    
    def __init__(self, db_store: Any):
        self.db = db_store
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        
    def start_task(self, activity: str) -> str:
        """Record when user starts a task."""
        task_id = str(uuid.uuid4())[:8]
        now = datetime.now()
        self.active_tasks[task_id] = {
            'activity': activity,
            'started_at': now,
            'last_activity_at': now,
            'interruptions': 0,
            'status': 'active'
        }
        # In actual implementation, this points to SQLite task_tracking table
        logger.debug(f"Task started: {activity} [{task_id}]")
        return task_id
        
    def log_interruption(self, task_id: str):
        """Record an interruption to an active task."""
        if task_id in self.active_tasks:
            self.active_tasks[task_id]['interruptions'] += 1
            self.active_tasks[task_id]['last_activity_at'] = datetime.now()
            
    def complete_task(self, task_id: str):
        """Record when user completes a task."""
        if task_id in self.active_tasks:
            task = self.active_tasks.pop(task_id)
            task['status'] = 'completed'
            task['completed_at'] = datetime.now()
            logger.info(f"Task completed: {task['activity']}")
            # Update DB here
            
    def find_abandoned_tasks(self, threshold_hours: int = 12) -> List[Dict[str, Any]]:
        """Identify tasks started but not completed within threshold."""
        now = datetime.now()
        abandoned = []
        for task_id, task in list(self.active_tasks.items()):
            hours_since_activity = (now - task['last_activity_at']).total_seconds() / 3600
            if hours_since_activity > threshold_hours:
                task['status'] = 'abandoned'
                abandoned.append(task)
                del self.active_tasks[task_id]
        return abandoned

class TimeBlindnessDetector:
    """Detects ADHD time blindness patterns."""
    
    def __init__(self):
        self.history: List[Dict[str, Any]] = []
        
    def track_estimate_vs_reality(self, task: str, estimated_mins: int, actual_mins: int):
        """
        Record user's estimate vs real time spent.
        """
        self.history.append({
            'task': task,
            'estimated': estimated_mins,
            'actual': actual_mins,
            'error_ratio': actual_mins / max(estimated_mins, 1)
        })
        
    def get_lateness_risk(self, event_time: datetime, prep_mins: int) -> float:
        """
        Predict likelihood user will be late.
        """
        now = datetime.now()
        time_until = (event_time - now).total_seconds() / 60
        if prep_mins > time_until:
            return 1.0  # Already late
        # Add historical error factor
        avg_ratio = 1.0
        if self.history:
            avg_ratio = sum(h['error_ratio'] for h in self.history) / len(self.history)
        
        predicted_prep = prep_mins * avg_ratio
        if predicted_prep > time_until:
            return 0.8  # High risk
        return 0.2

class RoutineAdherenceMonitor:
    """Monitors daily routines and detects collapse."""
    
    def __init__(self, db_store: Any):
        self.db = db_store
        
    def check_routine_collapse(self, routine_name: str, misses: int) -> Optional[str]:
        """Detect when a routine is falling apart."""
        if misses >= 3:
            return f"The {routine_name} routine has collapsed. Let's do a soft reset tomorrow - just the first step."
        return None
