"""
Emotion Confirmation System for ARCHER Observer

Adds confirmation step before emotional interventions to prevent
false positives and improve user trust.

User Requirements:
- Always ask for confirmation before emotional interventions
- Learn from user corrections to improve model accuracy
- Track confirmation history to build confidence over time
"""

from __future__ import annotations

import time
import random
from typing import Optional
from dataclasses import dataclass

from loguru import logger


@dataclass
class PendingConfirmation:
    """Represents an emotion awaiting user confirmation."""
    emotion: str
    confidence: float
    timestamp: float
    observation_id: int
    confirmed: Optional[bool] = None
    actual_emotion: Optional[str] = None


class EmotionConfirmationManager:
    """
    Manages emotion confirmation workflow.
    
    Flow:
    1. Observer detects emotion
    2. System asks for confirmation
    3. User responds (yes/no/actually X)
    4. System learns from correction
    5. Updates confidence thresholds
    """
    
    def __init__(self, store) -> None:
        """
        Args:
            store: SQLiteStore instance for persistence
        """
        self._store = store
        self._pending_confirmations: dict[str, PendingConfirmation] = {}
        
        # Confirmation templates by emotion
        self._templates = {
            "fear": [
                "I'm noticing what might be tension or worry in your expression. Are you feeling anxious right now?",
                "You seem a bit on edge. Everything okay?",
                "I'm picking up some stress signals. Am I reading that right?",
                "You look tense. Feeling stressed about something?",
            ],
            "sad": [
                "You seem a bit down. Am I reading that correctly?",
                "I'm noticing you might be feeling low. Is that accurate?",
                "Everything alright? You seem quieter than usual.",
                "You look a little sad. Is something bothering you?",
            ],
            "angry": [
                "You seem frustrated. Is something bothering you?",
                "I'm sensing some tension. Want to talk about it?",
                "You seem irritated. Am I off base?",
                "Looking a bit frustrated there. Everything okay?",
            ],
            "disgust": [
                "You look uncomfortable with something. Am I reading that right?",
                "Something bothering you?",
                "You seem put off by something. What's up?",
            ],
            "surprise": [
                "You look surprised. Did something unexpected just happen?",
                "That's an interesting reaction. What just happened?",
            ],
            "neutral": [
                "How are you feeling right now?",
                "Everything going okay?",
            ],
        }
        
        logger.info("Emotion confirmation manager initialized")
    
    def should_confirm(self, emotion: str, confidence: float, user_context: dict) -> bool:
        """
        Determine if detected emotion needs confirmation.
        
        Per user requirements: ALWAYS confirm emotional interventions.
        
        Args:
            emotion: Detected emotion label
            confidence: Model confidence (0.0-1.0)
            user_context: Additional context about detection
            
        Returns:
            True (always, per user requirements)
        """
        # User specified: Always ask for confirmation
        return True
    
    def generate_confirmation_question(self, emotion: str, confidence: float) -> str:
        """
        Generate natural confirmation question for detected emotion.
        
        Uses randomized templates to avoid sounding robotic.
        Lower confidence → softer, more tentative language.
        
        Args:
            emotion: Detected emotion label
            confidence: Model confidence (0.0-1.0)
            
        Returns:
            Confirmation question string
        """
        templates = self._templates.get(emotion, self._templates["neutral"])
        
        # For low confidence, add softening language
        question = random.choice(templates)
        
        if confidence < 0.7:
            softeners = [
                "I might be wrong, but ",
                "Just checking - ",
                "Forgive me if I'm misreading, but ",
            ]
            question = random.choice(softeners) + question.lower()
        
        return question
    
    def create_pending_confirmation(
        self, 
        emotion: str, 
        confidence: float,
        observation_id: int
    ) -> str:
        """
        Create a pending confirmation entry.
        
        Args:
            emotion: Detected emotion
            confidence: Detection confidence
            observation_id: ID of observation event in database
            
        Returns:
            Confirmation ID for tracking
        """
        confirmation_id = f"{emotion}_{int(time.time())}"
        
        pending = PendingConfirmation(
            emotion=emotion,
            confidence=confidence,
            timestamp=time.time(),
            observation_id=observation_id,
        )
        
        self._pending_confirmations[confirmation_id] = pending
        
        # Also persist to database
        self._store.log_pending_confirmation(
            emotion=emotion,
            confidence=confidence,
            observation_id=observation_id,
        )
        
        logger.info(f"Created pending confirmation for {emotion} (conf: {confidence:.2f})")
        return confirmation_id
    
    def process_confirmation_response(
        self,
        confirmation_id: str,
        user_confirmed: bool,
        actual_emotion: Optional[str] = None,
    ) -> dict:
        """
        Process user's confirmation response.
        
        Args:
            confirmation_id: ID of pending confirmation
            user_confirmed: True if user confirmed, False if denied
            actual_emotion: If denied, what emotion user actually felt
            
        Returns:
            dict with correction info for model training
        """
        if confirmation_id not in self._pending_confirmations:
            logger.warning(f"Unknown confirmation ID: {confirmation_id}")
            return {}
        
        pending = self._pending_confirmations[confirmation_id]
        pending.confirmed = user_confirmed
        pending.actual_emotion = actual_emotion
        
        # Store result
        self._store.update_emotion_confirmation(
            emotion=pending.emotion,
            confidence=pending.confidence,
            user_confirmed=user_confirmed,
            actual_emotion=actual_emotion,
        )
        
        # Calculate accuracy delta for model tuning
        correction_needed = not user_confirmed
        
        result = {
            "detected_emotion": pending.emotion,
            "confidence": pending.confidence,
            "was_correct": user_confirmed,
            "actual_emotion": actual_emotion,
            "correction_needed": correction_needed,
        }
        
        if correction_needed:
            logger.info(
                f"Emotion correction: detected {pending.emotion} "
                f"(conf: {pending.confidence:.2f}), actually {actual_emotion}"
            )
        else:
            logger.info(
                f"Emotion confirmed: {pending.emotion} "
                f"(conf: {pending.confidence:.2f})"
            )
        
        # Clean up
        del self._pending_confirmations[confirmation_id]
        
        return result
    
    def get_confidence_adjustment(self, emotion: str) -> float:
        """
        Get recommended confidence threshold adjustment for an emotion.
        
        Based on historical confirmation accuracy, suggests whether
        to raise or lower confidence threshold for this emotion.
        
        Args:
            emotion: Emotion label
            
        Returns:
            Adjustment factor (-0.2 to +0.2)
            Negative = lower threshold (model is too cautious)
            Positive = raise threshold (model has false positives)
        """
        stats = self._store.get_emotion_confirmation_stats(emotion)
        
        if not stats or stats["total_detections"] < 10:
            # Not enough data yet
            return 0.0
        
        accuracy = stats["confirmed"] / stats["total_detections"]
        
        # If accuracy > 90%, we can lower threshold (model is reliable)
        # If accuracy < 70%, raise threshold (too many false positives)
        
        if accuracy > 0.9:
            return -0.1  # Lower threshold, model is accurate
        elif accuracy < 0.7:
            return 0.15  # Raise threshold, too many false positives
        
        return 0.0  # Accuracy is acceptable, no adjustment
    
    def get_learning_summary(self) -> dict:
        """
        Get summary of what the system has learned from confirmations.
        
        Returns:
            dict with per-emotion accuracy stats and adjustments
        """
        emotions = ["fear", "sad", "angry", "disgust", "surprise", "happy", "neutral"]
        
        summary = {}
        for emotion in emotions:
            stats = self._store.get_emotion_confirmation_stats(emotion)
            adjustment = self.get_confidence_adjustment(emotion)
            
            summary[emotion] = {
                "total_detections": stats.get("total_detections", 0),
                "confirmed": stats.get("confirmed", 0),
                "accuracy": stats.get("accuracy", 0.0),
                "recommended_threshold_adjustment": adjustment,
            }
        
        return summary
