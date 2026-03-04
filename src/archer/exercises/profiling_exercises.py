"""
ARCHER Profiling Exercises System

Implements cognitive assessment exercises broken into 10-minute segments
that users can complete at their convenience.

User Requirements:
- 4-week baseline profiling period
- Questions broken into 10-minute segments
- User answers at will (no forced timing)
- Exercises help calibrate emotion detection and behavioral understanding
"""

from __future__ import annotations

import time
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

from loguru import logger


class ExerciseType(Enum):
    """Types of profiling exercises."""
    EMOTIONAL_CALIBRATION = "emotional_calibration"
    STRESS_RESPONSE = "stress_response"
    ATTENTION_ASSESSMENT = "attention_assessment"
    DECISION_MAKING = "decision_making"
    BASELINE_OBSERVATION = "baseline_observation"
    BASELINE_QUESTIONS = "baseline_questions"


class ExerciseStatus(Enum):
    """Exercise completion status."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclass
class ExerciseSegment:
    """
    A 10-minute segment of an exercise.
    
    Segments can be completed independently, allowing user
    to pause and resume at will.
    """
    segment_id: str
    exercise_type: ExerciseType
    title: str
    description: str
    questions: List[Dict[str, Any]]
    estimated_minutes: int = 10
    status: ExerciseStatus = ExerciseStatus.NOT_STARTED
    responses: List[Dict[str, Any]] = None
    completed_at: Optional[float] = None
    
    def __post_init__(self):
        if self.responses is None:
            self.responses = []


@dataclass
class ProfilingProgress:
    """Tracks overall profiling progress."""
    start_date: float
    current_week: int
    phase: str  # "profiling", "baseline", "active"
    exercises_completed: int
    exercises_total: int
    questions_answered: int
    baseline_established: bool = False


class ProfilingExerciseManager:
    """
    Manages profiling exercises and baseline establishment.
    
    Implements 4-week profiling period:
    - Week 1-2: Active profiling with questions
    - Week 3-4: Passive baseline observation
    - Week 5+: Active monitoring
    """
    
    def __init__(self, store) -> None:
        """
        Args:
            store: SQLiteStore instance
        """
        self._store = store
        self._segments: Dict[str, ExerciseSegment] = {}
        self._initialize_exercises()
        logger.info("Profiling exercise manager initialized")
    
    def _initialize_exercises(self) -> None:
        """Create all exercise segments."""
        
        # Week 1: Baseline Questions (broken into 10-min segments)
        self._create_baseline_question_segments()
        
        # Week 1: Emotional Calibration
        self._create_emotional_calibration_segments()
        
        # Week 2: Stress Response Profiling
        self._create_stress_profiling_segments()
        
        # Week 2: Attention Assessment
        self._create_attention_segments()
        
        # Week 3: Decision Making Profiling
        self._create_decision_segments()
        
        # Week 4: Baseline Day Observation (passive, no segments)
        self._create_baseline_observation()
    
    def _create_baseline_question_segments(self) -> None:
        """Create baseline profiling question segments."""
        
        # Segment 1: Emotional Baseline (10 min)
        self._segments["baseline_emotional"] = ExerciseSegment(
            segment_id="baseline_emotional",
            exercise_type=ExerciseType.BASELINE_QUESTIONS,
            title="Emotional Baseline",
            description="Help me understand your typical emotional patterns",
            questions=[
                {
                    "id": "stress_scale",
                    "question": "On a scale of 1-10, how would you describe your typical stress levels on a normal day?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                },
                {
                    "id": "stress_triggers",
                    "question": "What situations or events typically make you feel stressed?",
                    "type": "open_text",
                },
                {
                    "id": "stress_coping",
                    "question": "When you're stressed, what do you tend to do? (e.g., take a walk, call a friend, work harder)",
                    "type": "open_text",
                },
                {
                    "id": "happiness_baseline",
                    "question": "On a scale of 1-10, what's your typical happiness level on an average day?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                },
                {
                    "id": "good_day",
                    "question": "What does a 'good day' look like for you emotionally?",
                    "type": "open_text",
                },
            ],
            estimated_minutes=10,
        )
        
        # Segment 2: Sleep & Energy Baseline (10 min)
        self._segments["baseline_sleep"] = ExerciseSegment(
            segment_id="baseline_sleep",
            exercise_type=ExerciseType.BASELINE_QUESTIONS,
            title="Sleep & Energy Patterns",
            description="Understanding your sleep and energy rhythms",
            questions=[
                {
                    "id": "sleep_hours",
                    "question": "How many hours of sleep do you typically get on a weeknight?",
                    "type": "number",
                },
                {
                    "id": "bedtime",
                    "question": "What time do you usually go to bed on weeknights?",
                    "type": "time",
                },
                {
                    "id": "wake_time",
                    "question": "What time do you typically wake up?",
                    "type": "time",
                },
                {
                    "id": "sleep_quality",
                    "question": "On a scale of 1-10, how would you rate your typical sleep quality?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                },
                {
                    "id": "energy_peak",
                    "question": "What time of day do you have the most energy?",
                    "type": "multiple_choice",
                    "options": ["Morning (6am-10am)", "Midday (10am-2pm)", "Afternoon (2pm-6pm)", "Evening (6pm-10pm)", "Night (10pm+)"],
                },
                {
                    "id": "energy_low",
                    "question": "When do you typically feel most tired or low energy?",
                    "type": "multiple_choice",
                    "options": ["Morning", "After lunch", "Mid-afternoon", "Evening", "Varies"],
                },
            ],
            estimated_minutes=10,
        )
        
        # Segment 3: Social & Work Baseline (10 min)
        self._segments["baseline_social"] = ExerciseSegment(
            segment_id="baseline_social",
            exercise_type=ExerciseType.BASELINE_QUESTIONS,
            title="Social & Work Patterns",
            description="Your typical social and work rhythms",
            questions=[
                {
                    "id": "social_frequency",
                    "question": "How often do you typically socialize or have visitors in a normal week?",
                    "type": "multiple_choice",
                    "options": ["Daily", "3-5 times/week", "1-2 times/week", "Rarely", "Never"],
                },
                {
                    "id": "alone_comfort",
                    "question": "How comfortable are you being alone for extended periods?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                    "labels": {"1": "Very uncomfortable", "10": "Very comfortable"},
                },
                {
                    "id": "work_hours",
                    "question": "How many hours do you typically work per day?",
                    "type": "number",
                },
                {
                    "id": "break_frequency",
                    "question": "How often do you take breaks during work?",
                    "type": "multiple_choice",
                    "options": ["Every hour", "Every 2-3 hours", "Only lunch", "Rarely", "Never"],
                },
                {
                    "id": "focus_duration",
                    "question": "How long can you maintain deep focus on a task before needing a break?",
                    "type": "multiple_choice",
                    "options": ["15-30 min", "30-60 min", "1-2 hours", "2-4 hours", "4+ hours"],
                },
            ],
            estimated_minutes=10,
        )
        
        # Segment 4: Physical Baseline (10 min)
        self._segments["baseline_physical"] = ExerciseSegment(
            segment_id="baseline_physical",
            exercise_type=ExerciseType.BASELINE_QUESTIONS,
            title="Physical Activity & Health",
            description="Your typical physical activity patterns",
            questions=[
                {
                    "id": "sitting_hours",
                    "question": "How many hours per day do you typically spend sitting?",
                    "type": "number",
                },
                {
                    "id": "exercise_frequency",
                    "question": "How many days per week do you exercise or do physical activity?",
                    "type": "number",
                    "min": 0,
                    "max": 7,
                },
                {
                    "id": "exercise_type",
                    "question": "What type of exercise do you typically do?",
                    "type": "multiple_choice",
                    "multiple": True,
                    "options": ["Cardio/running", "Weight training", "Sports", "Yoga/stretching", "Walking", "None"],
                },
                {
                    "id": "water_intake",
                    "question": "How many glasses of water do you drink per day?",
                    "type": "number",
                },
                {
                    "id": "meal_regularity",
                    "question": "How regular are your meal times?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                    "labels": {"1": "Very irregular", "10": "Very consistent"},
                },
            ],
            estimated_minutes=10,
        )
    
    def _create_emotional_calibration_segments(self) -> None:
        """Create emotional calibration exercise segments."""
        
        self._segments["emotional_cal"] = ExerciseSegment(
            segment_id="emotional_cal",
            exercise_type=ExerciseType.EMOTIONAL_CALIBRATION,
            title="Emotional Calibration Exercise",
            description="I'll describe scenarios and you tell me how you'd feel. This helps me understand your emotional responses.",
            questions=[
                {
                    "id": "scenario_deadline",
                    "scenario": "You have a major deadline tomorrow and you're only 50% done with the work.",
                    "question": "How would you feel in this situation?",
                    "type": "emotion_rating",
                    "emotions": ["calm", "stressed", "anxious", "motivated", "overwhelmed"],
                },
                {
                    "id": "scenario_success",
                    "scenario": "You just completed a project that went really well and received praise from your boss.",
                    "question": "How would you feel?",
                    "type": "emotion_rating",
                    "emotions": ["happy", "proud", "relieved", "accomplished", "neutral"],
                },
                {
                    "id": "scenario_conflict",
                    "scenario": "A friend cancels plans with you last minute for the third time.",
                    "question": "How would you feel?",
                    "type": "emotion_rating",
                    "emotions": ["angry", "disappointed", "hurt", "understanding", "indifferent"],
                },
                {
                    "id": "scenario_unexpected",
                    "scenario": "You receive an unexpected bill for $500.",
                    "question": "How would you feel?",
                    "type": "emotion_rating",
                    "emotions": ["stressed", "worried", "angry", "calm", "panicked"],
                },
                {
                    "id": "scenario_alone",
                    "scenario": "You've been working alone at home for 3 days straight with no social interaction.",
                    "question": "How would you feel?",
                    "type": "emotion_rating",
                    "emotions": ["lonely", "content", "focused", "restless", "energized"],
                },
            ],
            estimated_minutes=10,
        )
    
    def _create_stress_profiling_segments(self) -> None:
        """Create stress response profiling segments."""
        
        self._segments["stress_profile"] = ExerciseSegment(
            segment_id="stress_profile",
            exercise_type=ExerciseType.STRESS_RESPONSE,
            title="Stress Response Profile",
            description="Understanding how you respond to pressure and stress",
            questions=[
                {
                    "id": "pressure_response",
                    "question": "When facing a tight deadline, do you typically work faster, slower, or at the same pace?",
                    "type": "multiple_choice",
                    "options": ["Much faster", "Slightly faster", "Same pace", "Slower", "Freeze up"],
                },
                {
                    "id": "stress_physical",
                    "question": "How does stress typically manifest physically for you?",
                    "type": "multiple_choice",
                    "multiple": True,
                    "options": ["Tension in shoulders/neck", "Headaches", "Stomach issues", "Rapid heartbeat", "No physical symptoms"],
                },
                {
                    "id": "help_seeking",
                    "question": "When overwhelmed, do you typically ask for help or try to handle it alone?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                    "labels": {"1": "Always handle alone", "10": "Always seek help"},
                },
                {
                    "id": "stress_duration",
                    "question": "After a stressful event, how long does it typically take you to feel calm again?",
                    "type": "multiple_choice",
                    "options": ["Minutes", "Hours", "Days", "Weeks", "Varies greatly"],
                },
                {
                    "id": "frustration_response",
                    "question": "When something frustrates you, what's your typical first response?",
                    "type": "multiple_choice",
                    "options": ["Take a break", "Push harder", "Ask for help", "Get irritated", "Give up"],
                },
            ],
            estimated_minutes=10,
        )
    
    def _create_attention_segments(self) -> None:
        """Create attention assessment segments."""
        
        self._segments["attention_profile"] = ExerciseSegment(
            segment_id="attention_profile",
            exercise_type=ExerciseType.ATTENTION_ASSESSMENT,
            title="Focus & Attention Patterns",
            description="Understanding your concentration and distraction patterns",
            questions=[
                {
                    "id": "distraction_triggers",
                    "question": "What types of things typically break your focus?",
                    "type": "multiple_choice",
                    "multiple": True,
                    "options": ["Notifications", "People talking", "Email", "Random thoughts", "Physical discomfort", "Hunger/thirst"],
                },
                {
                    "id": "focus_time_preference",
                    "question": "What time of day are you most able to focus deeply?",
                    "type": "multiple_choice",
                    "options": ["Early morning", "Late morning", "Afternoon", "Evening", "Night", "Varies"],
                },
                {
                    "id": "task_switching",
                    "question": "How well do you handle switching between multiple tasks?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                    "labels": {"1": "Very difficult", "10": "Very easy"},
                },
                {
                    "id": "concentration_recovery",
                    "question": "After an interruption, how long does it take you to regain deep focus?",
                    "type": "multiple_choice",
                    "options": ["Immediately", "1-5 minutes", "5-15 minutes", "15-30 minutes", "Hard to regain focus"],
                },
            ],
            estimated_minutes=10,
        )
    
    def _create_decision_segments(self) -> None:
        """Create decision-making profiling segments."""
        
        self._segments["decision_profile"] = ExerciseSegment(
            segment_id="decision_profile",
            exercise_type=ExerciseType.DECISION_MAKING,
            title="Decision-Making Style",
            description="Understanding how you make decisions under uncertainty",
            questions=[
                {
                    "id": "decision_speed",
                    "question": "When faced with a decision, do you decide quickly or take time to consider?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                    "labels": {"1": "Very quick", "10": "Very deliberate"},
                },
                {
                    "id": "decision_confidence",
                    "question": "After making a decision, how confident are you that it was right?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                    "labels": {"1": "Often second-guess", "10": "Very confident"},
                },
                {
                    "id": "risk_tolerance",
                    "question": "How comfortable are you taking risks when outcomes are uncertain?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                    "labels": {"1": "Very risk-averse", "10": "Very risk-tolerant"},
                },
                {
                    "id": "information_seeking",
                    "question": "Before deciding, do you prefer to have all possible information or decide with what you have?",
                    "type": "scale",
                    "min": 1,
                    "max": 10,
                    "labels": {"1": "Need all info", "10": "Decide quickly"},
                },
            ],
            estimated_minutes=10,
        )
    
    def _create_baseline_observation(self) -> None:
        """Create baseline observation (passive, no questions)."""
        
        self._segments["baseline_observation"] = ExerciseSegment(
            segment_id="baseline_observation",
            exercise_type=ExerciseType.BASELINE_OBSERVATION,
            title="Baseline Day Observation",
            description="I'll observe your normal patterns for a full day without intervention.",
            questions=[],  # No questions, just passive observation
            estimated_minutes=0,  # Runs automatically
        )
    
    def get_available_segments(self, week: int) -> List[ExerciseSegment]:
        """
        Get exercise segments available for current week.
        
        Week 1-2: Baseline questions + calibration exercises
        Week 3-4: Decision/attention exercises + passive observation
        
        Args:
            week: Current week number (1-4)
            
        Returns:
            List of available ExerciseSegments
        """
        available = []
        
        if week == 1:
            # Week 1: Baseline questions + emotional calibration
            available = [
                self._segments["baseline_emotional"],
                self._segments["baseline_sleep"],
                self._segments["baseline_social"],
                self._segments["baseline_physical"],
                self._segments["emotional_cal"],
            ]
        elif week == 2:
            # Week 2: Stress + attention profiling
            available = [
                self._segments["stress_profile"],
                self._segments["attention_profile"],
            ]
        elif week == 3:
            # Week 3: Decision profiling + start baseline observation
            available = [
                self._segments["decision_profile"],
                self._segments["baseline_observation"],
            ]
        elif week >= 4:
            # Week 4: Final baseline observation, all questions completed
            available = [
                self._segments["baseline_observation"],
            ]
        
        # Filter to only not-completed segments
        return [s for s in available if s.status != ExerciseStatus.COMPLETED]
    
    def present_next_segment(self, week: int) -> Optional[ExerciseSegment]:
        """
        Get the next available segment user can complete.
        
        Args:
            week: Current profiling week
            
        Returns:
            Next ExerciseSegment or None if all complete
        """
        available = self.get_available_segments(week)
        
        if not available:
            return None
        
        # Return first not-started segment, or first in-progress
        for segment in available:
            if segment.status == ExerciseStatus.NOT_STARTED:
                return segment
        
        for segment in available:
            if segment.status == ExerciseStatus.IN_PROGRESS:
                return segment
        
        return None
    
    def record_segment_response(
        self,
        segment_id: str,
        question_id: str,
        response: Any,
    ) -> None:
        """
        Record user's response to a question in a segment.
        
        Args:
            segment_id: ID of the exercise segment
            question_id: ID of specific question
            response: User's response (type varies by question)
        """
        if segment_id not in self._segments:
            logger.warning(f"Unknown segment ID: {segment_id}")
            return
        
        segment = self._segments[segment_id]
        
        # Update segment status
        if segment.status == ExerciseStatus.NOT_STARTED:
            segment.status = ExerciseStatus.IN_PROGRESS
        
        # Store response
        segment.responses.append({
            "question_id": question_id,
            "response": response,
            "timestamp": time.time(),
        })
        
        # Persist to database
        self._store.save_exercise_response(
            segment_id=segment_id,
            question_id=question_id,
            response=json.dumps(response),
        )
        
        # Check if segment is complete
        if len(segment.responses) >= len(segment.questions):
            segment.status = ExerciseStatus.COMPLETED
            segment.completed_at = time.time()
            logger.info(f"Exercise segment '{segment.title}' completed")
    
    def get_profiling_progress(self) -> ProfilingProgress:
        """
        Get current profiling progress.
        
        Returns:
            ProfilingProgress object with completion stats
        """
        # Calculate weeks since start
        start_date = self._store.get_profiling_start_date()
        if not start_date:
            # Not started yet
            return ProfilingProgress(
                start_date=time.time(),
                current_week=0,
                phase="not_started",
                exercises_completed=0,
                exercises_total=len(self._segments),
                questions_answered=0,
            )
        
        weeks_elapsed = int((time.time() - start_date) / (7 * 24 * 3600))
        current_week = min(weeks_elapsed + 1, 4)
        
        # Determine phase
        if current_week <= 2:
            phase = "profiling"
        elif current_week <= 4:
            phase = "baseline"
        else:
            phase = "active"
        
        # Count completions
        completed = sum(1 for s in self._segments.values() if s.status == ExerciseStatus.COMPLETED)
        total = len(self._segments)
        
        # Count total questions answered
        questions_answered = sum(len(s.responses) for s in self._segments.values())
        
        # Check if baseline established
        baseline_established = (
            current_week >= 4 and
            completed >= total * 0.8  # 80% of exercises complete
        )
        
        return ProfilingProgress(
            start_date=start_date,
            current_week=current_week,
            phase=phase,
            exercises_completed=completed,
            exercises_total=total,
            questions_answered=questions_answered,
            baseline_established=baseline_established,
        )
    
    def should_ask_question(self) -> bool:
        """
        Determine if it's appropriate to ask a profiling question now.
        
        User requirement: Questions at user's convenience
        System should offer questions but not force them.
        
        Returns:
            True if questions are available and timing is appropriate
        """
        progress = self.get_profiling_progress()
        
        # Don't ask if profiling period is over
        if progress.current_week > 4:
            return False
        
        # Don't ask if all exercises complete
        if progress.exercises_completed >= progress.exercises_total:
            return False
        
        # Check cooldown - don't ask more than once per hour
        last_question_time = self._store.get_last_profiling_question_time()
        if last_question_time and (time.time() - last_question_time) < 3600:
            return False
        
        return True
    
    def generate_question_offer(self) -> Optional[str]:
        """
        Generate a natural offer to complete a profiling segment.
        
        Returns:
            Offer text, or None if no questions available
        """
        progress = self.get_profiling_progress()
        next_segment = self.present_next_segment(progress.current_week)
        
        if not next_segment:
            return None
        
        # Generate natural offer based on segment type
        offers = {
            ExerciseType.BASELINE_QUESTIONS: [
                f"I have some baseline questions about {next_segment.title.lower()} when you have 10 minutes. Want to answer them now or later?",
                f"Quick 10-minute exercise: {next_segment.description}. Good time, or should I ask later?",
            ],
            ExerciseType.EMOTIONAL_CALIBRATION: [
                "I'd like to run a quick emotional calibration exercise - helps me understand you better. Takes about 10 minutes. Interested?",
                "Want to help me learn your emotional patterns? Short 10-minute exercise. Now or later?",
            ],
            ExerciseType.STRESS_RESPONSE: [
                "I have some questions about how you handle stress. 10 minutes when you're free. Now work?",
            ],
            ExerciseType.ATTENTION_ASSESSMENT: [
                "Quick focus assessment - helps me learn when you concentrate best. 10 minutes. Want to try it?",
            ],
            ExerciseType.DECISION_MAKING: [
                "I'm curious how you make decisions. Short 10-minute questionnaire. Interested?",
            ],
        }
        
        import random
        return random.choice(offers.get(next_segment.exercise_type, [
            f"{next_segment.title} - 10 minutes when you're free. Now or later?"
        ]))
