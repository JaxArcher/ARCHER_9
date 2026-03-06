"""
Normative Comparator for ARCHER Blindspot Agent.
Compares user behavior to typical norms and personal baselines.
"""

from __future__ import annotations
import numpy as np
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from loguru import logger

class NormativeStandardsDB:
    """Database of 'normal' behavior standards."""
    
    STANDARDS = {
        'hygiene': {
            'shower_frequency_per_week': 7,
            'shave_frequency_per_week': 3,
            'teeth_brushing_frequency_per_day': 2
        },
        'household': {
            'trash_removal_frequency_per_week': 2,
            'dish_washing_delay_max_hours': 24,
            'bed_making_frequency_per_week': 7,
            'clutter_free_surface_percentage': 70
        },
        'nutrition': {
            'meals_per_day': 3,
            'water_intake_liters_per_day': 2.5
        },
        'social': {
            'close_contact_frequency_per_week': 2,
            'family_contact_frequency_per_week': 1,
            'response_time_important_messages_hours': 24
        }
    }
    
    def get_standard(self, category: str, metric: str) -> Optional[float]:
        """Get a specific normative standard."""
        return self.STANDARDS.get(category, {}).get(metric)
        
    def get_adhd_adjusted_standard(self, category: str, metric: str) -> Optional[float]:
        """Adjusted for ADHD reality (0.75x typically)."""
        std = self.get_standard(category, metric)
        if std:
            # For 7/week, ADHD-adjusted is ~5/week
            return std * 0.75
        return None

class UserBaselineSystem:
    """Learns and tracks user's personal baseline behaviors."""
    
    def __init__(self, db_store: Any):
        self.db = db_store
        self.baselines: Dict[str, Dict[str, Any]] = {}

    def record_observation(self, category: str, metric: str, value: float):
        """Record an observation during calibration."""
        # Interface with behavior_observations table
        logger.debug(f"Observation recorded: {category}.{metric} = {value}")
        
    def get_user_baseline(self, category: str, metric: str) -> Optional[float]:
        """Get user's personal baseline for a metric."""
        # Use median of observations if calibrating, else use calculated_value
        return 1.0 # Mocked for now

class DeviationAnalyzer:
    """Compares current behavior to baselines."""
    
    def __init__(self, normative_db: NormativeStandardsDB, user_baseline: UserBaselineSystem):
        self.normative_db = normative_db
        self.user_baseline = user_baseline
        
    def analyze_deviation(self, category: str, metric: str, current_value: float) -> Dict[str, Any]:
        """
        Compare current value to user baseline and normative standards.
        """
        user_base = self.user_baseline.get_user_baseline(category, metric)
        norm = self.normative_db.get_standard(category, metric)
        adhd_norm = self.normative_db.get_adhd_adjusted_standard(category, metric)
        
        result = {
            'user_baseline': user_base,
            'normative_standard': norm,
            'adhd_adjusted_standard': adhd_norm,
            'current_value': current_value
        }
        
        # Calculate deviation from user baseline
        if user_base:
            deviation_from_user = ((current_value - user_base) / user_base) * 100
        else:
            deviation_from_user = 0
            
        result['deviation_from_user'] = deviation_from_user
        
        # Determine severity
        if abs(deviation_from_user) < 20:
            result['severity'] = 'normal'
        elif abs(deviation_from_user) < 40:
            result['severity'] = 'mild'
        elif abs(deviation_from_user) < 60:
            result['severity'] = 'moderate'
        else:
            result['severity'] = 'severe'
            
        result['trigger_intervention'] = result['severity'] in ['moderate', 'severe']
        return result
