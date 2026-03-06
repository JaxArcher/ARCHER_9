"""
ADHD Engine for ARCHER Blindspot Agent.
Tracks ADHD states, patterns, and medication timing.
"""

from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from loguru import logger

class ADHDStateDetector:
    """Detects ADHD-specific states and patterns."""
    
    STATES = {
        'hyperfocus': 'Intense focus, time blindness, ignoring bodily needs',
        'paralysis': 'Cannot initiate task despite wanting to, executive dysfunction',
        'overstimulation': 'Too much sensory input, overwhelmed, scattered',
        'understimulation': 'Bored, seeking dopamine, prone to distraction',
        'dopamine_seeking': 'Actively pursuing quick rewards, avoiding difficult tasks',
        'emotional_dysregulation': 'Difficulty managing emotions, RSD triggered',
        'transition_difficulty': 'Stuck between activities, cannot switch gears'
    }
    
    def __init__(self):
        self.current_state: Optional[str] = None
        self.state_history: List[Dict[str, Any]] = []
        
    def detect_current_state(self, context: Dict[str, Any]) -> str:
        """
        Determine current ADHD state based on multiple signals.
        """
        # Hyperfocus detection: 2+ hours same activity, no breaks
        if (context.get('activity_duration_hours', 0) > 2 and 
            not context.get('break_taken_last_hour', False)):
            return 'hyperfocus'
            
        # Paralysis detection: many task switches, but no progress
        if (context.get('task_switches_last_hour', 0) > 10 and
            context.get('activity_duration_hours', 0) < 0.1):
            return 'paralysis'
            
        # Overstimulation: high noise or chaotic environment
        if context.get('environment_noise_level', 0) > 0.7:
            return 'overstimulation'
            
        # Understimulation / dopamine seeking: high screen time on low-value sites
        if (context.get('screen_time_minutes', 0) > 60 and
            any(site in context.get('activity_type', '') for site in ['reddit', 'twitter', 'youtube', 'tiktok', 'instagram'])):
            return 'dopamine_seeking'
            
        # Emotional dysregulation
        if any(e in ['anxious', 'frustrated', 'overwhelmed'] 
               for e in context.get('emotional_indicators', [])):
            return 'emotional_dysregulation'
            
        return 'baseline'

    def get_state_appropriate_intervention(self, state: str, task: str) -> Dict[str, Any]:
        """Return intervention strategy appropriate for current ADHD state."""
        if state == 'hyperfocus':
            return {
                'approach': 'gentle_interrupt',
                'message': f"I know you're in flow with {task}, but you've been at it for 2 hours. Time for a 5-minute break?",
                'mandatory': True,
                'action': 'force_break'
            }
        elif state == 'paralysis':
            return {
                'approach': 'micro_scaffolding',
                'message': f"I noticed you're stuck on {task}. Let's just do one tiny thing: reach for the first tool/open the file. No pressure to finish.",
                'action': 'segment_task'
            }
        elif state == 'overstimulation':
            return {
                'approach': 'reduce_stimuli',
                'message': "It sounds a bit chaotic in here. Should we switch to some white noise or focus music?",
                'action': 'suggest_environment_change'
            }
        elif state == 'dopamine_seeking':
            return {
                'approach': 'productive_dopamine',
                'message': "I see the scrolling loop. How about we get a quick win on a small task to get that dopamine instead?",
                'action': 'redirect_productive'
            }
        return {'approach': 'standard', 'message': f"Friendly reminder about {task}.", 'action': 'reminder'}

class ADHDPatternLibrary:
    """Library of common ADHD behavioral patterns."""
    
    PATTERNS = {
        'object_permanence_failure': {
            'description': 'Item put out of sight becomes forgotten',
            'detection': 'item_placement_hidden',
            'intervention': 'Suggest visible placement',
            'example': "You put those keys in a drawer. You're going to forget they exist in 10 minutes."
        },
        'time_blindness': {
            'description': 'No sense of time passing',
            'detection': 'estimate_reality_gap',
            'intervention': 'Departure countdowns',
            'example': "You said 5 minutes, but it's been 45. Real talk: you're going to be late."
        },
        'clutter_blindness': {
            'description': 'Clutter becomes invisible',
            'detection': 'clutter_accumulation',
            'intervention': 'Reality checks',
            'example': "You have 4 empty coffee mugs on your desk. I know you've stopped seeing them, but they're taking over."
        },
        'routine_collapse': {
            'description': 'One disruption destroys entire routine',
            'detection': 'consecutive_misses',
            'intervention': 'Soft reset',
            'example': "You missed the gym twice this week. Don't quit the whole routine - let's just do a 10-min stretch today."
        }
    }

class MedicationTracker:
    """Track ADHD medication timing."""
    
    def __init__(self, db_store: Any):
        self.db = db_store
        
    def log_medication(self, dose: str, on_time: bool):
        """Log medication intake."""
        # This would interface with the DB
        logger.info(f"Medication logged: {dose}, on_time={on_time}")
