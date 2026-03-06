"""
Intervention Engine for ARCHER Blindspot Agent.
Determines intervention urgency and selects the best strategy.
"""

from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from loguru import logger

class SeverityScorer:
    """Determines intervention urgency based on multiple factors."""
    
    SEVERITY_LEVELS = {
        1: 'observation',      # Just note it, no action
        2: 'gentle_mention',   # "I noticed..."
        3: 'suggestion',       # "Want to..."
        4: 'firm_reminder',    # "You need to..."
        5: 'urgent',           # "This is a problem"
        6: 'crisis'            # Route to Therapist immediately
    }
    
    def calculate_severity(self, issue: Dict[str, Any]) -> int:
        """
        Determine severity level for an issue.
        """
        deviation = issue.get('deviation_from_baseline', 0.0)
        impact = issue.get('health_impact', 'none')
        mental_health_indicator = issue.get('mental_health_indicator', False)
        
        severity = 1
        if mental_health_indicator:
            return 6  # Crisis - route to Therapist
        
        if deviation > 0.8:
            severity = 5
        elif deviation > 0.5:
            severity = 4
        elif deviation > 0.3:
            severity = 3
        elif deviation > 0.15:
            severity = 2
            
        return severity

class InterventionStrategy:
    """Strategy for delivering interventions."""
    
    def get_strategy(self, severity_level: int, state: str) -> Dict[str, Any]:
        """
        Return the best intervention strategy.
        """
        if severity_level >= 5:
            return {
                'type': 'firm_reminders',
                'delivery': 'interrupt',
                'tone': 'serious'
            }
        elif state == 'paralysis':
            return {
                'type': 'micro_scaffolding',
                'delivery': 'supportive',
                'tone': 'gentle'
            }
        elif state == 'hyperfocus':
            return {
                'type': 'gentle_interrupt',
                'delivery': 'gradual',
                'tone': 'caring'
            }
        return {
            'type': 'suggestion',
            'delivery': 'ambient',
            'tone': 'observant'
        }

class DecisionEngine:
    """Main decision engine for Blindspot interventions."""
    
    def __init__(self, db_store: Any):
        self.db = db_store
        self.scorer = SeverityScorer()
        self.strategy_selector = InterventionStrategy()
        
    def decide_intervention(self, issues: List[Dict[str, Any]], current_state: str) -> Optional[Dict[str, Any]]:
        """
        Decide whether to intervene and how.
        """
        if not issues:
            return None
            
        # Select most severe issue
        most_severe = max(issues, key=lambda x: self.scorer.calculate_severity(x))
        severity = self.scorer.calculate_severity(most_severe)
        
        if severity < 2:
            return None # Just record observation
            
        strategy = self.strategy_selector.get_strategy(severity, current_state)
        
        return {
            'issue': most_severe,
            'severity': severity,
            'strategy': strategy,
            'timestamp': datetime.now()
        }
