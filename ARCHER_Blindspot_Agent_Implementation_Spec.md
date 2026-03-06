# ARCHER Blindspot Agent - Complete Implementation Specification

**Target**: Antigravity Development Team  
**Date**: March 5, 2026  
**Priority**: High - Core differentiation feature  
**Complexity**: Advanced (requires computer vision, behavioral analysis, ADHD specialization)

---

## 📋 TABLE OF CONTENTS

1. [Executive Summary](#executive-summary)
2. [Agent Overview](#agent-overview)
3. [Architecture](#architecture)
4. [Detection Systems](#detection-systems)
5. [ADHD Specialization](#adhd-specialization)
6. [Intervention Strategies](#intervention-strategies)
7. [Database Schema](#database-schema)
8. [Implementation Phases](#implementation-phases)
9. [Privacy & Ethics](#privacy--ethics)
10. [Testing Criteria](#testing-criteria)

---

## EXECUTIVE SUMMARY

The Blindspot Agent is ARCHER's most advanced behavioral monitoring system. It identifies what the user consistently overlooks or cannot process due to ADHD executive dysfunction, then intervenes proactively with compassionate accountability.

**Core Principle**: For ADHD users, blindspots aren't just "things you don't notice" - they're things your brain **cannot track, process, or execute**. ARCHER becomes the external executive function system.

**Key Differentiators**:
- Brutally honest but caring (like a best friend who tells hard truths)
- ADHD-specialized (understands executive dysfunction, time blindness, etc.)
- Visually observant (uses computer vision for environmental assessment)
- Normative comparison (compares user behavior to typical patterns)
- Actionable interventions (not just alerts, but step-by-step help)

---

## AGENT OVERVIEW

### Agent Profile

**Name**: Blindspot Agent  
**Internal ID**: `blindspot`  
**Personality**: Observant, opinionated, caring but direct, design-savvy, socially aware  
**Tone**: Best friend who tells you hard truths
- "Dude, you need to shower"
- "Real talk: your place looks rough"  
- "I'm saying this because I care: take care of yourself"

**Model**: `qwen/qwen3.5-397b-a17b` (NVIDIA NIM)  
**Fallback**: `qwen3.5:9b` (local)

### Core Responsibilities

1. **Personal Appearance Monitoring**: Grooming, hygiene, clothing condition
2. **Environmental Assessment**: Clutter, cleanliness, organization, aesthetics
3. **Behavioral Pattern Analysis**: Comparing user behavior to normative standards
4. **ADHD-Specific Support**: Executive function assistance, time blindness compensation
5. **Social Relationship Tracking**: Follow-ups, commitments, relationship maintenance
6. **Proactive Intervention**: Not just observation - active guidance and scaffolding

### Integration Points

- **Routes TO**: Therapist (mental health patterns), Assistant (organizing help), Trainer (hygiene habits)
- **Uses**: Observer vision data, memory systems, user profile, web knowledge
- **Outputs**: Interventions (alerts/suggestions), memory updates, agent routing

---

## ARCHITECTURE

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                     BLINDSPOT AGENT ARCHITECTURE                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Observer   │  │    Memory    │  │  Calendar/   │          │
│  │   Vision     │  │   Systems    │  │  Contacts    │          │
│  │              │  │              │  │              │          │
│  │ • Webcam     │  │ • SQLite     │  │ • Events     │          │
│  │ • MediaPipe  │  │ • ChromaDB   │  │ • People     │          │
│  │ • DeepFace   │  │ • Redis      │  │ • Tasks      │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                  │                  │
│         └─────────────────┴──────────────────┘                  │
│                           │                                     │
└───────────────────────────┼─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   DETECTION ENGINES                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────┐             │
│  │    VISUAL DETECTION ENGINE                     │             │
│  ├────────────────────────────────────────────────┤             │
│  │ • Personal Appearance Analyzer                 │             │
│  │ • Environmental Clutter Detector               │             │
│  │ • Furniture & Aesthetic Evaluator              │             │
│  │ • Object State Analyzer (clean/dirty/worn)     │             │
│  │ • Plant Health Monitor                         │             │
│  └────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌────────────────────────────────────────────────┐             │
│  │    BEHAVIORAL PATTERN ENGINE                   │             │
│  ├────────────────────────────────────────────────┤             │
│  │ • Task Completion Tracker                      │             │
│  │ • Routine Adherence Monitor                    │             │
│  │ • Time Blindness Detector                      │             │
│  │ • Hyperfocus/Procrastination Analyzer          │             │
│  │ • Emotional State Correlator                   │             │
│  └────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌────────────────────────────────────────────────┐             │
│  │    NORMATIVE COMPARISON ENGINE                 │             │
│  ├────────────────────────────────────────────────┤             │
│  │ • User Baseline vs. Current State              │             │
│  │ • User Standards vs. General Norms             │             │
│  │ • ADHD-Specific Pattern Recognition            │             │
│  │ • Deviation Severity Scoring                   │             │
│  └────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌────────────────────────────────────────────────┐             │
│  │    SOCIAL & RELATIONAL ENGINE                  │             │
│  ├────────────────────────────────────────────────┤             │
│  │ • Contact Interaction Tracker                  │             │
│  │ • Promise/Commitment Monitor                   │             │
│  │ • Relationship Health Analyzer                 │             │
│  │ • Meeting Follow-up Detector                   │             │
│  └────────────────────────────────────────────────┘             │
│                                                                  │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ADHD SPECIALIZATION LAYER                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────┐             │
│  │    ADHD State Detection                        │             │
│  ├────────────────────────────────────────────────┤             │
│  │ • Hyperfocus (good - protect, enforce breaks)  │             │
│  │ • Paralysis (stuck - needs scaffolding)        │             │
│  │ • Overstimulation (environment too chaotic)    │             │
│  │ • Understimulation (bored - seeking dopamine)  │             │
│  │ • Medication State (timing/adherence)          │             │
│  │ • Executive Dysfunction Level                  │             │
│  └────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌────────────────────────────────────────────────┐             │
│  │    ADHD Pattern Library                        │             │
│  ├────────────────────────────────────────────────┤             │
│  │ • Object permanence issues                     │             │
│  │ • Time blindness patterns                      │             │
│  │ • Task switching/completion failures           │             │
│  │ • Dopamine-seeking behaviors                   │             │
│  │ • Emotional dysregulation triggers             │             │
│  │ • Environmental sensitivity thresholds         │             │
│  │ • Transition difficulty indicators             │             │
│  │ • Impulse control patterns                     │             │
│  │ • Routine collapse signatures                  │             │
│  └────────────────────────────────────────────────┘             │
│                                                                  │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   INTERVENTION ENGINE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────┐             │
│  │    Severity Scoring                            │             │
│  ├────────────────────────────────────────────────┤             │
│  │ • Level 1: Observation (just note it)          │             │
│  │ • Level 2: Gentle Mention ("I noticed...")     │             │
│  │ • Level 3: Suggestion ("Want to...")           │             │
│  │ • Level 4: Firm Reminder ("You need to...")    │             │
│  │ • Level 5: Urgent ("This is a problem")        │             │
│  │ • Level 6: Crisis (route to Therapist)         │             │
│  └────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌────────────────────────────────────────────────┐             │
│  │    Intervention Strategies                     │             │
│  ├────────────────────────────────────────────────┤             │
│  │ • Simple Alert ("Trash needs to go out")       │             │
│  │ • Step-by-Step Guidance (executive function)   │             │
│  │ • Body Doubling (virtual presence)             │             │
│  │ • Reward System (dopamine reinforcement)       │             │
│  │ • Agent Routing (Therapist/Assistant/Trainer)  │             │
│  │ • Context-Aware Timing (when to intervene)     │             │
│  └────────────────────────────────────────────────┘             │
│                                                                  │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        OUTPUT LAYER                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  • Voice/GUI Alerts                                              │
│  • Memory Updates (patterns stored)                              │
│  • Agent Routing (to Therapist/Assistant/Trainer)               │
│  • User Profile Updates (learn preferences)                      │
│  • Dashboard Metrics (blindspot analytics)                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## DETECTION SYSTEMS

### 1. Visual Detection Engine

**File**: `src/archer/blindspot/visual_detector.py`

#### 1.1 Personal Appearance Analyzer

**Purpose**: Detect grooming, hygiene, and clothing condition issues

**Computer Vision Models**:
- **Facial hair detection**: Use MediaPipe face mesh + custom stubble classifier
- **Clothing analysis**: Detect wrinkles, stains, wear using texture analysis
- **Hygiene indicators**: Greasy hair, unkempt appearance (visual cues)

**Implementation**:

```python
class PersonalAppearanceAnalyzer:
    """Analyzes user's physical appearance for grooming/hygiene issues."""
    
    def __init__(self):
        self.face_detector = MediaPipeFaceDetector()
        self.clothing_analyzer = ClothingConditionAnalyzer()
        self.baseline_appearance = None  # Learned "well-groomed" state
        
    def analyze_facial_hair(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Detect facial hair length and grooming state.
        
        Returns:
            {
                'has_facial_hair': bool,
                'stubble_length_mm': float,
                'needs_shave': bool,
                'last_shave_estimated_days': int
            }
        """
        # Use face mesh to detect texture/shadow patterns indicating stubble
        # Compare to user's baseline (clean-shaven vs bearded)
        
    def analyze_clothing_condition(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Detect wrinkles, stains, wear in visible clothing.
        
        Returns:
            {
                'wrinkle_severity': float,  # 0-1 scale
                'visible_stains': List[BoundingBox],
                'wear_indicators': List[str],  # ['fraying', 'pilling', etc.]
                'needs_change': bool
            }
        """
        # Use texture analysis for wrinkles
        # Color anomaly detection for stains
        # Edge detection for wear/fraying
        
    def detect_same_outfit(self, current_frame: np.ndarray, days: int = 3) -> bool:
        """
        Check if user is wearing the same outfit as previous days.
        
        Args:
            current_frame: Current video frame
            days: How many days back to compare
            
        Returns:
            True if same outfit detected across multiple days
        """
        # Extract clothing color palette and patterns
        # Compare to historical frames
        # Account for similar but different items
        
    def estimate_shower_recency(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Estimate time since last shower using visual cues.
        
        Visual indicators:
        - Hair appearance (greasy vs clean)
        - Skin condition
        - General grooming state
        
        Returns:
            {
                'estimated_hours_since_shower': int,
                'confidence': float,
                'visual_cues': List[str]
            }
        """
        # This is probabilistic - combine with behavioral data
        # (e.g., saw user enter/exit bathroom with towel)
```

#### 1.2 Environmental Clutter Detector

**Purpose**: Measure clutter levels and compare to clean baseline

**Implementation**:

```python
class EnvironmentalClutterDetector:
    """Detects clutter and environmental disorder."""
    
    def __init__(self):
        self.object_detector = YOLOv8()  # Or similar
        self.room_baselines = {}  # Clean state for each room
        
    def establish_clean_baseline(self, room_name: str, frames: List[np.ndarray]):
        """
        Learn what 'clean' looks like for this room.
        
        User must explicitly mark a time when room is clean.
        This becomes the comparison baseline.
        """
        # Extract object count, placement, surface coverage
        # Store as baseline for this room
        
    def measure_clutter_level(self, room_name: str, frame: np.ndarray) -> Dict[str, Any]:
        """
        Compare current state to clean baseline.
        
        Returns:
            {
                'clutter_score': float,  # 0-1 (0=baseline clean, 1=very messy)
                'object_count_delta': int,  # Extra objects vs baseline
                'surface_coverage_pct': float,  # % of surfaces covered
                'notable_items': List[str],  # ['dishes on counter', 'clothes on floor']
                'severity': str  # 'clean', 'mild', 'moderate', 'severe'
            }
        """
        baseline = self.room_baselines.get(room_name)
        if not baseline:
            return {'error': 'No baseline established for this room'}
            
        current_objects = self.object_detector.detect(frame)
        
        # Compare object counts
        # Measure surface coverage (tables, counters, floors)
        # Identify out-of-place items
        # Calculate deviation from baseline
        
    def detect_specific_issues(self, room_name: str, frame: np.ndarray) -> List[str]:
        """
        Identify specific cleanliness issues.
        
        Returns list of issues like:
        - "Dishes piled in sink"
        - "Trash can overflowing"
        - "Clothes on floor"
        - "Food wrappers on desk"
        - "Unmade bed"
        """
        issues = []
        
        # Dish detection
        if self._detect_dishes_in_sink(frame):
            issues.append("Dishes piled in sink")
            
        # Trash can analysis
        trash_fullness = self._measure_trash_can_fill(frame)
        if trash_fullness > 0.8:
            issues.append("Trash can overflowing")
            
        # Floor clutter
        if self._detect_floor_items(frame):
            issues.append("Items on floor")
            
        return issues
        
    def _detect_trash_can_fill(self, frame: np.ndarray) -> float:
        """
        Measure how full trash can is (0-1 scale).
        
        Uses:
        - Object detection to find trash can
        - Bounding box height analysis
        - Visual overflow detection
        """
        # Detect trash can
        # Measure fill level based on visible contents
        # Return percentage (0 = empty, 1 = overflowing)
```

#### 1.3 Furniture & Aesthetic Evaluator

**Purpose**: Assess room layout, furniture condition, design quality

**Implementation**:

```python
class FurnitureAestheticEvaluator:
    """Evaluates furniture placement, condition, and aesthetic quality."""
    
    def __init__(self):
        self.design_principles = self._load_design_knowledge()
        self.room_layouts = {}
        
    def _load_design_knowledge(self) -> Dict[str, Any]:
        """
        Load interior design principles from web/LLM knowledge.
        
        Principles include:
        - Furniture placement (traffic flow, focal points)
        - Color theory (complementary, analogous)
        - Lighting (natural light maximization)
        - Space utilization (proportion, balance)
        - Ergonomics (comfortable arrangements)
        """
        # This could be a JSON file scraped from design websites
        # Or embedded in LLM knowledge
        # Key rules like "don't block windows", "create conversation areas"
        
    def analyze_furniture_placement(self, room_name: str, frame: np.ndarray) -> Dict[str, Any]:
        """
        Evaluate furniture arrangement against design principles.
        
        Returns:
            {
                'issues': List[str],  # ['blocks window', 'poor traffic flow']
                'suggestions': List[str],  # ['Move couch 2ft left', 'Rotate chair']
                'score': float,  # 0-1 design quality score
                'improvements': List[Dict]  # Specific actionable changes
            }
        """
        # Detect furniture positions
        # Check against principles (e.g., blocking windows, cramped pathways)
        # Generate improvement suggestions
        
    def assess_furniture_condition(self, item_type: str, frame: np.ndarray) -> Dict[str, Any]:
        """
        Evaluate physical condition of furniture.
        
        Detects:
        - Wear and tear (fraying, stains, damage)
        - Age indicators
        - Quality level
        
        Returns:
            {
                'condition': str,  # 'new', 'good', 'worn', 'poor', 'replace'
                'issues': List[str],  # ['visible stains', 'cushion sagging']
                'estimated_replacement_cost': int,
                'suggestions': List[str]  # ['clean', 'reupholster', 'replace']
            }
        """
        # Analyze texture for wear
        # Color analysis for stains/fading
        # Shape analysis for sagging/deformation
        
    def evaluate_color_scheme(self, room_name: str, frame: np.ndarray) -> Dict[str, Any]:
        """
        Assess room color palette against color theory.
        
        Returns:
            {
                'primary_colors': List[RGB],
                'harmony_score': float,  # How well colors work together
                'issues': List[str],  # ['clashing colors', 'too chaotic']
                'suggestions': List[str]  # ['Add neutral tones', 'Reduce red']
            }
        """
        # Extract dominant colors
        # Apply color theory rules
        # Check for clashes or monotony
        
    def suggest_improvements(self, room_name: str, frame: np.ndarray) -> List[Dict]:
        """
        Generate specific, actionable improvement suggestions.
        
        Returns list of improvements like:
        {
            'action': 'Move bookshelf',
            'reason': 'Currently blocks natural light from window',
            'new_position': 'Against north wall',
            'difficulty': 'medium',
            'estimated_time': '15 minutes',
            'impact': 'high'  # How much it improves the space
        }
        """
        # Combine all analyses
        # Prioritize by impact and difficulty
        # Provide step-by-step instructions
```

#### 1.4 Plant Health Monitor

**Purpose**: Detect dying/wilting plants and alert for watering

**Implementation**:

```python
class PlantHealthMonitor:
    """Monitors plant health and watering needs."""
    
    def __init__(self):
        self.plant_registry = {}  # Track known plants
        
    def detect_plants(self, frame: np.ndarray) -> List[Dict]:
        """
        Identify plants in the frame and track them over time.
        
        Returns list of detected plants with IDs for tracking.
        """
        # Use object detection to find plants
        # Assign persistent IDs
        # Track location and species (if identifiable)
        
    def assess_plant_health(self, plant_id: str, frame: np.ndarray) -> Dict[str, Any]:
        """
        Evaluate plant health based on visual cues.
        
        Indicators:
        - Leaf color (green = healthy, yellow/brown = unhealthy)
        - Leaf droop (wilting)
        - Soil moisture (visual darkness/wetness)
        - Leaf count changes (dropping leaves)
        
        Returns:
            {
                'health_score': float,  # 0-1 (0=dying, 1=thriving)
                'needs_water': bool,
                'days_since_watered': int,  # Estimated
                'issues': List[str],  # ['wilting', 'yellowing leaves']
                'urgency': str  # 'fine', 'water_soon', 'water_now', 'dying'
            }
        """
        # Color analysis (HSV space for leaf health)
        # Shape analysis (drooping detection)
        # Soil appearance (dry vs moist)
        # Compare to historical baseline
        
    def track_watering_schedule(self, plant_id: str):
        """
        Track when plants were last watered.
        
        Detection methods:
        - See user watering plant (action recognition)
        - Soil darkness changes (visual indicator)
        - User verbal confirmation ("I just watered the plants")
        """
        # Update last_watered timestamp
        # Estimate next watering need based on plant type
```

---

### 2. Behavioral Pattern Engine

**File**: `src/archer/blindspot/behavioral_detector.py`

#### 2.1 Task Completion Tracker

**Purpose**: Detect started-but-unfinished tasks (ADHD pattern)

**Implementation**:

```python
class TaskCompletionTracker:
    """Tracks task starts, interruptions, and completions."""
    
    def __init__(self):
        self.active_tasks = {}  # Tasks currently in progress
        self.completed_tasks = []
        self.abandoned_tasks = []
        
    def detect_task_start(self, activity: str, timestamp: datetime):
        """
        Identify when user starts a new task.
        
        Detection methods:
        - Vision: See user begin activity (folding laundry, cooking, etc.)
        - Audio: User says "I'm going to [task]"
        - Context: New window/app opened for specific task
        """
        task_id = self._generate_task_id()
        self.active_tasks[task_id] = {
            'activity': activity,
            'started': timestamp,
            'last_activity': timestamp,
            'interruptions': 0,
            'status': 'active'
        }
        
    def detect_task_interruption(self, task_id: str, timestamp: datetime):
        """
        Detect when user gets distracted from active task.
        
        Indicators:
        - User walks away from task area
        - Starts different activity
        - Phone/computer usage unrelated to task
        """
        if task_id in self.active_tasks:
            self.active_tasks[task_id]['interruptions'] += 1
            self.active_tasks[task_id]['last_activity'] = timestamp
            
    def detect_task_completion(self, task_id: str, timestamp: datetime):
        """
        Identify completed tasks.
        
        Detection:
        - Vision confirms task finished (laundry folded and put away)
        - User verbal confirmation
        - Expected end state achieved
        """
        if task_id in self.active_tasks:
            task = self.active_tasks.pop(task_id)
            task['completed'] = timestamp
            task['duration'] = (timestamp - task['started']).total_seconds()
            self.completed_tasks.append(task)
            
    def identify_abandoned_tasks(self, threshold_hours: int = 24) -> List[Dict]:
        """
        Find tasks started but not completed within threshold.
        
        ADHD pattern: Start many things, finish few
        
        Returns list of abandoned tasks for intervention.
        """
        now = datetime.now()
        abandoned = []
        
        for task_id, task in list(self.active_tasks.items()):
            hours_since_activity = (now - task['last_activity']).total_seconds() / 3600
            
            if hours_since_activity > threshold_hours:
                task['status'] = 'abandoned'
                abandoned.append(task)
                self.abandoned_tasks.append(task)
                del self.active_tasks[task_id]
                
        return abandoned
        
    def calculate_completion_rate(self, days: int = 7) -> float:
        """
        Calculate % of started tasks that get completed.
        
        Low completion rate = ADHD pattern
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_completed = [t for t in self.completed_tasks if t['completed'] > cutoff]
        recent_abandoned = [t for t in self.abandoned_tasks if t['started'] > cutoff]
        
        total = len(recent_completed) + len(recent_abandoned)
        if total == 0:
            return 1.0
            
        return len(recent_completed) / total
```

#### 2.2 Time Blindness Detector

**Purpose**: Detect when user loses track of time (ADHD core symptom)

**Implementation**:

```python
class TimeBlindnessDetector:
    """Detects ADHD time blindness patterns."""
    
    def __init__(self):
        self.time_estimates = {}  # User's time estimates vs reality
        self.hyperfocus_sessions = []
        
    def track_time_estimate(self, task: str, estimated_minutes: int, actual_minutes: int):
        """
        Compare user's time estimates to reality.
        
        ADHD pattern: Consistently underestimate or overestimate time
        """
        if task not in self.time_estimates:
            self.time_estimates[task] = []
            
        self.time_estimates[task].append({
            'estimated': estimated_minutes,
            'actual': actual_minutes,
            'error_ratio': actual_minutes / max(estimated_minutes, 1)
        })
        
    def detect_hyperfocus(self, activity: str, duration_hours: float) -> bool:
        """
        Identify hyperfocus sessions.
        
        Indicators:
        - Extended uninterrupted focus (3+ hours)
        - No breaks, no eating/drinking
        - User unaware of time passing
        
        Returns True if hyperfocus detected
        """
        if duration_hours >= 3.0:
            self.hyperfocus_sessions.append({
                'activity': activity,
                'duration_hours': duration_hours,
                'timestamp': datetime.now()
            })
            return True
        return False
        
    def calculate_late_probability(self, event_time: datetime, prep_needed_minutes: int) -> float:
        """
        Predict likelihood user will be late.
        
        Factors:
        - Current time vs event time
        - Preparation time needed
        - User's historical lateness pattern
        - Current activity (hyperfocused = high risk)
        """
        now = datetime.now()
        time_until_event = (event_time - now).total_seconds() / 60  # minutes
        
        # If prep time exceeds available time, guaranteed late
        if prep_needed_minutes > time_until_event:
            return 1.0
            
        # Factor in historical lateness
        # Factor in current state (hyperfocused?)
        # Return probability 0-1
        
    def alert_time_passage(self, activity: str, threshold_minutes: int = 30):
        """
        Alert when user has been doing something longer than they realize.
        
        Example: "You said '5 minutes' - it's been 45 minutes"
        """
        # Track when user says time estimate
        # Monitor actual time
        # Alert when reality exceeds estimate significantly
```

#### 2.3 Routine Adherence Monitor

**Purpose**: Track whether user follows established routines

**Implementation**:

```python
class RoutineAdherenceMonitor:
    """Monitors routine execution and detects collapse."""
    
    def __init__(self):
        self.routines = {}  # User's established routines
        self.adherence_history = []
        
    def define_routine(self, name: str, steps: List[str], schedule: str):
        """
        User establishes a routine.
        
        Example:
        name = "morning_routine"
        steps = ["shower", "breakfast", "meds", "exercise"]
        schedule = "daily, 6:00 AM - 9:00 AM"
        """
        self.routines[name] = {
            'steps': steps,
            'schedule': schedule,
            'expected_duration_minutes': len(steps) * 15,  # Estimate
            'consecutive_completions': 0,
            'consecutive_misses': 0
        }
        
    def track_routine_execution(self, routine_name: str, completed_steps: List[str], timestamp: datetime):
        """
        Record which steps of routine were completed.
        """
        routine = self.routines.get(routine_name)
        if not routine:
            return
            
        completion_rate = len(completed_steps) / len(routine['steps'])
        
        self.adherence_history.append({
            'routine': routine_name,
            'timestamp': timestamp,
            'completion_rate': completion_rate,
            'completed_steps': completed_steps,
            'missed_steps': [s for s in routine['steps'] if s not in completed_steps]
        })
        
        # Update streak tracking
        if completion_rate >= 0.8:  # 80% = success
            routine['consecutive_completions'] += 1
            routine['consecutive_misses'] = 0
        else:
            routine['consecutive_misses'] += 1
            routine['consecutive_completions'] = 0
            
    def detect_routine_collapse(self, routine_name: str) -> Dict[str, Any]:
        """
        Identify when a routine has fallen apart.
        
        ADHD pattern: One disruption breaks entire routine
        
        Returns:
            {
                'collapsed': bool,
                'consecutive_misses': int,
                'trigger_event': str,  # What disrupted it
                'days_since_last_success': int,
                'recovery_suggestion': str
            }
        """
        routine = self.routines.get(routine_name)
        if not routine:
            return {'collapsed': False}
            
        # If missed 3+ days in a row, routine collapsed
        if routine['consecutive_misses'] >= 3:
            return {
                'collapsed': True,
                'consecutive_misses': routine['consecutive_misses'],
                'recovery_suggestion': 'Soft reset tomorrow - just do one step to rebuild habit'
            }
            
        return {'collapsed': False}
```

---

### 3. Normative Comparison Engine

**File**: `src/archer/blindspot/normative_comparator.py`

**Purpose**: Compare user behavior to typical/expected standards

#### 3.1 Normative Standards Database

**Implementation**:

```python
class NormativeStandardsDB:
    """Database of 'normal' behavior standards for comparison."""
    
    def __init__(self):
        self.standards = self._load_standards()
        
    def _load_standards(self) -> Dict[str, Any]:
        """
        Load normative behavior standards.
        
        Sources:
        - Medical/health guidelines (CDC, WHO)
        - Interior design principles
        - Social norms research
        - ADHD-specific accommodations
        
        Structure:
        {
            'hygiene': {
                'shower_frequency_per_week': 7,
                'shave_frequency_per_week': 3,  # If not bearded
                'clothes_change_frequency_per_day': 1,
                'teeth_brushing_frequency_per_day': 2
            },
            'household': {
                'trash_removal_frequency_per_week': 2,
                'dish_washing_delay_max_hours': 24,
                'bed_making_frequency_per_week': 7,
                'sheet_change_frequency_per_weeks': 1,
                'deep_clean_frequency_per_month': 1
            },
            'nutrition': {
                'meals_per_day': 3,
                'water_intake_liters_per_day': 2.5,
                'fruit_servings_per_day': 2,
                'vegetable_servings_per_day': 3
            },
            'social': {
                'close_contact_frequency_per_week': 2,
                'family_contact_frequency_per_week': 1,
                'response_time_important_messages_hours': 24
            },
            'interior_design': {
                'furniture_blocks_windows': False,
                'clear_pathways_minimum_width_feet': 3,
                'clutter_free_surface_percentage': 70
            }
        }
        """
        # This could be loaded from JSON file or embedded
        # Should be research-backed where possible
        
    def get_standard(self, category: str, metric: str) -> Any:
        """Get a specific normative standard."""
        return self.standards.get(category, {}).get(metric)
        
    def get_adhd_adjusted_standard(self, category: str, metric: str) -> Any:
        """
        Get standard adjusted for ADHD reality.
        
        Example:
        - Normal: Shower daily
        - ADHD-adjusted: Shower every 2 days (executive function tax)
        
        This prevents unrealistic expectations while still maintaining health.
        """
        standard = self.get_standard(category, metric)
        
        # Apply ADHD adjustment factor (typically 0.7-0.8x for frequency tasks)
        if 'frequency' in metric:
            return standard * 0.75  # 25% reduction for ADHD accommodation
            
        return standard
```

#### 3.2 User Baseline System

**Implementation**:

```python
class UserBaselineSystem:
    """Learn and track user's personal baseline behaviors."""
    
    def __init__(self):
        self.baselines = {}
        self.calibration_period_days = 14  # Learn for 2 weeks
        
    def enter_calibration_mode(self, user_id: str):
        """
        Start learning user's baseline.
        
        During calibration:
        - Observe but don't judge
        - Record all behaviors
        - Identify user's "normal"
        - Don't compare to general norms yet
        """
        self.baselines[user_id] = {
            'calibration_start': datetime.now(),
            'observations': [],
            'state': 'calibrating'
        }
        
    def record_observation(self, user_id: str, category: str, metric: str, value: Any):
        """
        Record a behavior observation during calibration.
        
        Example:
        - category='hygiene', metric='shower_frequency', value=0.5 (per day)
        - category='household', metric='trash_removal_frequency', value=0.125 (per day = 1x/week)
        """
        if user_id not in self.baselines:
            return
            
        self.baselines[user_id]['observations'].append({
            'category': category,
            'metric': metric,
            'value': value,
            'timestamp': datetime.now()
        })
        
    def finalize_baseline(self, user_id: str):
        """
        After calibration period, calculate user's baseline norms.
        
        This becomes the "USER normal" that we compare to, not general population.
        """
        baseline = self.baselines.get(user_id)
        if not baseline or baseline['state'] != 'calibrating':
            return
            
        # Group observations by category/metric
        # Calculate averages/medians
        # Store as user's personal baseline
        
        baseline['state'] = 'active'
        baseline['calculated_norms'] = self._calculate_norms(baseline['observations'])
        
    def _calculate_norms(self, observations: List[Dict]) -> Dict[str, Any]:
        """Calculate typical values from observations."""
        norms = {}
        
        # Group by category and metric
        grouped = {}
        for obs in observations:
            key = f"{obs['category']}.{obs['metric']}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(obs['value'])
            
        # Calculate median for each
        for key, values in grouped.items():
            norms[key] = np.median(values)
            
        return norms
        
    def get_user_baseline(self, user_id: str, category: str, metric: str) -> Any:
        """Get user's personal baseline for a metric."""
        baseline = self.baselines.get(user_id)
        if not baseline or baseline['state'] != 'active':
            return None
            
        key = f"{category}.{metric}"
        return baseline.get('calculated_norms', {}).get(key)
```

#### 3.3 Deviation Analyzer

**Implementation**:

```python
class DeviationAnalyzer:
    """Compares current behavior to baselines and detects deviations."""
    
    def __init__(self, normative_db: NormativeStandardsDB, user_baseline: UserBaselineSystem):
        self.normative_db = normative_db
        self.user_baseline = user_baseline
        
    def analyze_deviation(self, user_id: str, category: str, metric: str, current_value: Any) -> Dict[str, Any]:
        """
        Compare current value to user baseline and normative standards.
        
        Returns:
            {
                'user_baseline': float,
                'normative_standard': float,
                'adhd_adjusted_standard': float,
                'current_value': float,
                'deviation_from_user': float,  # Percentage
                'deviation_from_norm': float,  # Percentage
                'severity': str,  # 'normal', 'mild', 'moderate', 'severe'
                'trigger_intervention': bool
            }
        """
        user_base = self.user_baseline.get_user_baseline(user_id, category, metric)
        norm = self.normative_db.get_standard(category, metric)
        adhd_norm = self.normative_db.get_adhd_adjusted_standard(category, metric)
        
        result = {
            'user_baseline': user_base,
            'normative_standard': norm,
            'adhd_adjusted_standard': adhd_norm,
            'current_value': current_value
        }
        
        # Calculate deviations
        if user_base:
            result['deviation_from_user'] = ((current_value - user_base) / user_base) * 100
        else:
            result['deviation_from_user'] = 0
            
        if adhd_norm:
            result['deviation_from_norm'] = ((current_value - adhd_norm) / adhd_norm) * 100
        else:
            result['deviation_from_norm'] = 0
            
        # Determine severity
        # Priority: Compare to user baseline first, then ADHD norms, then general norms
        if abs(result['deviation_from_user']) < 20:
            result['severity'] = 'normal'  # Within 20% of user's normal
        elif abs(result['deviation_from_user']) < 40:
            result['severity'] = 'mild'
        elif abs(result['deviation_from_user']) < 60:
            result['severity'] = 'moderate'
        else:
            result['severity'] = 'severe'
            
        # Trigger intervention if moderate or severe
        result['trigger_intervention'] = result['severity'] in ['moderate', 'severe']
        
        return result
```

---

### 4. Social & Relational Engine

**File**: `src/archer/blindspot/relationship_tracker.py`

**Purpose**: Track social interactions, commitments, and relationship health

**Implementation**:

```python
class RelationshipTracker:
    """Tracks social relationships and interaction patterns."""
    
    def __init__(self):
        self.contacts = {}  # Person profiles
        self.interactions = []  # Interaction history
        self.commitments = []  # Promises made
        
    def add_contact(self, name: str, relationship: str, metadata: Dict = None):
        """
        Register a contact in the system.
        
        Args:
            name: Person's name
            relationship: 'family', 'friend', 'colleague', etc.
            metadata: Optional info (birthday, preferences, etc.)
        """
        self.contacts[name] = {
            'relationship': relationship,
            'added': datetime.now(),
            'metadata': metadata or {},
            'interaction_frequency': None,  # Will be learned
            'last_interaction': None,
            'typical_interval_days': None
        }
        
    def log_interaction(self, person: str, interaction_type: str, notes: str = None):
        """
        Record an interaction with a person.
        
        Args:
            person: Person's name
            interaction_type: 'call', 'text', 'in-person', 'email', etc.
            notes: Optional notes about interaction
        """
        interaction = {
            'person': person,
            'type': interaction_type,
            'timestamp': datetime.now(),
            'notes': notes
        }
        
        self.interactions.append(interaction)
        
        # Update contact's last interaction
        if person in self.contacts:
            self.contacts[person]['last_interaction'] = datetime.now()
            self._update_typical_interval(person)
            
    def _update_typical_interval(self, person: str):
        """
        Calculate typical time between interactions with this person.
        """
        person_interactions = [i for i in self.interactions if i['person'] == person]
        
        if len(person_interactions) < 2:
            return
            
        # Calculate intervals between interactions
        intervals = []
        for i in range(1, len(person_interactions)):
            delta = (person_interactions[i]['timestamp'] - 
                    person_interactions[i-1]['timestamp']).days
            intervals.append(delta)
            
        # Store median interval as "typical"
        self.contacts[person]['typical_interval_days'] = np.median(intervals)
        
    def detect_neglected_relationships(self, threshold_multiplier: float = 1.5) -> List[Dict]:
        """
        Find relationships that haven't been maintained.
        
        Args:
            threshold_multiplier: Alert if interval exceeds typical by this factor
            
        Returns list of neglected contacts with details.
        """
        neglected = []
        now = datetime.now()
        
        for name, contact in self.contacts.items():
            if not contact['last_interaction'] or not contact['typical_interval_days']:
                continue
                
            days_since = (now - contact['last_interaction']).days
            typical_days = contact['typical_interval_days']
            
            if days_since > (typical_days * threshold_multiplier):
                neglected.append({
                    'person': name,
                    'relationship': contact['relationship'],
                    'days_since_contact': days_since,
                    'typical_interval': typical_days,
                    'severity': 'mild' if days_since < typical_days * 2 else 'moderate'
                })
                
        return neglected
        
    def track_commitment(self, person: str, promise: str, due_date: datetime = None):
        """
        Record a commitment made to someone.
        
        Example: "Told Mike I'd send that document by Friday"
        """
        self.commitments.append({
            'person': person,
            'promise': promise,
            'made_on': datetime.now(),
            'due_date': due_date,
            'fulfilled': False,
            'status': 'pending'
        })
        
    def detect_unfulfilled_commitments(self, days_overdue_threshold: int = 3) -> List[Dict]:
        """
        Find promises that haven't been kept.
        
        ADHD pattern: Forgetting commitments made in conversation
        """
        overdue = []
        now = datetime.now()
        
        for commitment in self.commitments:
            if commitment['fulfilled']:
                continue
                
            if commitment['due_date']:
                days_overdue = (now - commitment['due_date']).days
                if days_overdue > 0:
                    overdue.append({
                        **commitment,
                        'days_overdue': days_overdue
                    })
            else:
                # No due date, but check if it's been too long
                days_since = (now - commitment['made_on']).days
                if days_since > days_overdue_threshold:
                    overdue.append({
                        **commitment,
                        'days_pending': days_since
                    })
                    
        return overdue
        
    def analyze_relationship_health(self, person: str) -> Dict[str, Any]:
        """
        Overall relationship health assessment.
        
        Factors:
        - Interaction frequency vs typical
        - Unfulfilled commitments
        - Reciprocity (do they initiate too?)
        - Recent interaction sentiment
        
        Returns:
            {
                'health_score': float,  # 0-1
                'status': str,  # 'strong', 'stable', 'at_risk', 'neglected'
                'issues': List[str],
                'suggestions': List[str]
            }
        """
        # Calculate based on multiple factors
        # Return actionable recommendations
```

---

## ADHD SPECIALIZATION

**File**: `src/archer/blindspot/adhd_engine.py`

### ADHD State Detection

**Purpose**: Identify current ADHD state to tailor interventions

**Implementation**:

```python
class ADHDStateDetector:
    """Detects ADHD-specific states and patterns."""
    
    # State definitions
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
        self.current_state = None
        self.state_history = []
        self.medication_schedule = None
        
    def detect_current_state(self, context: Dict[str, Any]) -> str:
        """
        Determine current ADHD state based on multiple signals.
        
        Args:
            context: {
                'activity_duration_hours': float,
                'activity_type': str,
                'break_taken_last_hour': bool,
                'environment_noise_level': float,
                'screen_time_minutes': int,
                'task_switches_last_hour': int,
                'emotional_indicators': List[str],
                'medication_timing': Dict
            }
            
        Returns state key from STATES
        """
        # Hyperfocus detection
        if (context.get('activity_duration_hours', 0) > 2 and 
            not context.get('break_taken_last_hour', False)):
            return 'hyperfocus'
            
        # Paralysis detection
        if (context.get('task_switches_last_hour', 0) > 10 and
            context.get('activity_duration_hours', 0) < 0.1):
            return 'paralysis'
            
        # Overstimulation
        if context.get('environment_noise_level', 0) > 0.7:
            return 'overstimulation'
            
        # Understimulation / dopamine seeking
        if (context.get('screen_time_minutes', 0) > 60 and
            'social_media' in context.get('activity_type', '')):
            return 'dopamine_seeking'
            
        # Emotional dysregulation
        if any(e in ['anxious', 'frustrated', 'overwhelmed'] 
               for e in context.get('emotional_indicators', [])):
            return 'emotional_dysregulation'
            
        return 'baseline'  # No specific state detected
        
    def get_state_appropriate_intervention(self, state: str, task: str) -> Dict[str, Any]:
        """
        Return intervention strategy appropriate for current ADHD state.
        
        Different states need different approaches.
        """
        if state == 'hyperfocus':
            return {
                'approach': 'gentle_interrupt',
                'message': "I know you're in flow, but you need a break",
                'mandatory': True,  # Override resistance
                'action': 'force_5min_break'
            }
            
        elif state == 'paralysis':
            return {
                'approach': 'micro_scaffolding',
                'message': "Let's just do the tiniest first step - no commitment to finish",
                'action': 'break_into_microsteps',
                'body_doubling': True
            }
            
        elif state == 'overstimulation':
            return {
                'approach': 'reduce_stimuli',
                'message': "Your environment is overwhelming. Want me to help calm things down?",
                'actions': ['suggest_quiet_space', 'offer_white_noise', 'reduce_visual_clutter']
            }
            
        elif state == 'understimulation':
            return {
                'approach': 'gamify_redirect',
                'message': "I see you're bored. Let's make the task more interesting",
                'action': 'add_challenge_or_reward'
            }
            
        elif state == 'dopamine_seeking':
            return {
                'approach': 'productive_dopamine',
                'message': "You're chasing dopamine. Here's a more productive way to get it",
                'action': 'suggest_engaging_productive_task'
            }
            
        else:
            return {
                'approach': 'standard',
                'message': task,
                'action': 'normal_reminder'
            }
```

### ADHD Pattern Library

**Implementation**:

```python
class ADHDPatternLibrary:
    """Library of common ADHD behavioral patterns."""
    
    PATTERNS = {
        'object_permanence_failure': {
            'description': 'Item put out of sight becomes forgotten',
            'detection': 'User places important item in drawer/cabinet',
            'intervention': 'Suggest visible placement or immediate reminder',
            'example': "Keys in drawer = you'll forget they exist"
        },
        
        'time_blindness': {
            'description': 'No sense of time passing, consistently late',
            'detection': 'User says "5 minutes" but 45 minutes pass',
            'intervention': 'Real-time time alerts, departure countdowns',
            'example': "Meeting in 10 min but you need 20 to get ready"
        },
        
        'task_initiation_paralysis': {
            'description': 'Cannot start task despite wanting to',
            'detection': 'User avoids task for days, visible procrastination',
            'intervention': 'Micro-step scaffolding, body doubling',
            'example': "You know you need to do this but can't make yourself start"
        },
        
        'hyperfocus_tunnel_vision': {
            'description': 'Intense focus, ignores bodily needs',
            'detection': '3+ hours without break, food, water, bathroom',
            'intervention': 'Forced breaks, health reminders',
            'example': "You've been coding 6 hours straight with no food"
        },
        
        'dopamine_chasing': {
            'description': 'Seeking quick rewards, avoiding boring tasks',
            'detection': 'Excessive phone use, impulsive purchases, task avoidance',
            'intervention': 'Redirect to productive dopamine sources',
            'example': "Opened Reddit 15 times instead of doing laundry"
        },
        
        'emotional_dysregulation': {
            'description': 'Intense emotions, difficulty regulating',
            'detection': 'Overwrote message 8 times, pacing, visible anxiety',
            'intervention': 'Route to Therapist, grounding techniques',
            'example': "You've rewritten that text 8 times - you're overthinking"
        },
        
        'rejection_sensitivity': {
            'description': 'Perceiving rejection where none intended (RSD)',
            'detection': 'Mood shift after neutral message, overanalyzing tone',
            'intervention': 'Reality check, reassurance, Therapist routing',
            'example': "That email was neutral but you're reading it as critical"
        },
        
        'routine_collapse': {
            'description': 'One disruption destroys entire routine',
            'detection': 'Missed one gym day, now it's been a week',
            'intervention': 'Soft reset, don't require perfection',
            'example': "Missing one doesn't mean quit - let's just do today"
        },
        
        'clutter_blindness': {
            'description': 'Visual clutter becomes invisible over time',
            'detection': 'Clutter accumulates without user noticing',
            'intervention': 'Periodic "do you see this?" reality checks',
            'example': "You have 4 coffee mugs on your desk - do you even see them?"
        },
        
        'impulse_control_failure': {
            'description': 'Act/speak before thinking through consequences',
            'detection': 'About to send angry email, impulse purchase',
            'intervention': 'Delay mechanism, cooling-off period',
            'example': "Save that email draft - review in 1 hour before sending"
        },
        
        'working_memory_overload': {
            'description': 'Forget what you were doing mid-task',
            'detection': 'Task switching without completing, losing track',
            'intervention': 'External task tracking, what were you doing reminders',
            'example': "You went to the kitchen for water, now you're reorganizing the pantry"
        },
        
        'decision_fatigue': {
            'description': 'Overwhelmed by too many options',
            'detection': 'Staring at options for 20+ minutes, paralyzed',
            'intervention': 'Reduce options to 2-3, decide for user if needed',
            'example': "You've looked at 50 options - here are the top 3"
        }
    }
    
    def identify_pattern(self, behavior: Dict[str, Any]) -> List[str]:
        """
        Match observed behavior to known ADHD patterns.
        
        Returns list of matching pattern names.
        """
        matches = []
        
        # Pattern matching logic
        # Compare behavior to pattern signatures
        # Return all matches
        
        return matches
        
    def get_pattern_intervention(self, pattern_name: str) -> Dict[str, Any]:
        """Get recommended intervention for a specific pattern."""
        pattern = self.PATTERNS.get(pattern_name)
        if not pattern:
            return {}
            
        return {
            'intervention_type': pattern['intervention'],
            'example_message': pattern['example']
        }
```

### Medication Tracking Integration

**Implementation**:

```python
class MedicationTracker:
    """Track ADHD medication timing and correlate with performance."""
    
    def __init__(self):
        self.medication_schedule = []
        self.performance_log = []
        
    def log_medication(self, timestamp: datetime, dose: str, taken_on_time: bool):
        """
        Record when medication was taken.
        """
        self.medication_schedule.append({
            'timestamp': timestamp,
            'dose': dose,
            'on_time': taken_on_time,
            'minutes_late': self._calculate_lateness(timestamp) if not taken_on_time else 0
        })
        
    def correlate_with_performance(self, date: datetime.date) -> Dict[str, Any]:
        """
        Analyze how medication timing affected day's performance.
        
        Returns:
            {
                'med_taken_on_time': bool,
                'minutes_late': int,
                'productivity_score': float,
                'mood_score': float,
                'focus_score': float,
                'correlation': str  # 'strong', 'moderate', 'weak'
            }
        """
        # Find medication timing for this date
        # Get performance metrics for same date
        # Calculate correlation
        # Example: "Took meds 2 hours late, afternoon productivity tanked"
        
    def predict_medication_needed(self, upcoming_tasks: List[str]) -> Dict[str, Any]:
        """
        Predict if user will need medication for upcoming tasks.
        
        Considers:
        - Task difficulty
        - Time of day
        - Historical performance with/without meds
        
        Returns reminder if meds needed.
        """
        # Analyze task difficulty
        # Check typical medication timing
        # Return recommendation
```

---

## INTERVENTION ENGINE

**File**: `src/archer/blindspot/intervention_engine.py`

### Severity Scoring System

**Implementation**:

```python
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
        
        Args:
            issue: {
                'category': str,  # 'hygiene', 'household', 'social', etc.
                'metric': str,
                'deviation_from_baseline': float,  # Percentage
                'duration_days': int,  # How long it's been an issue
                'health_impact': str,  # 'none', 'low', 'medium', 'high'
                'social_impact': str,  # 'none', 'low', 'medium', 'high'
                'mental_health_indicator': bool  # Could signal depression
            }
            
        Returns severity level (1-6)
        """
        score = 1  # Start at observation level
        
        # Factor 1: Deviation magnitude
        deviation = abs(issue.get('deviation_from_baseline', 0))
        if deviation > 80:
            score += 2
        elif deviation > 50:
            score += 1
            
        # Factor 2: Duration
        days = issue.get('duration_days', 0)
        if days > 7:
            score += 2
        elif days > 3:
            score += 1
            
        # Factor 3: Health impact
        health_impact = issue.get('health_impact', 'none')
        if health_impact == 'high':
            score += 2
        elif health_impact == 'medium':
            score += 1
            
        # Factor 4: Mental health indicator
        if issue.get('mental_health_indicator', False):
            score = max(score, 5)  # At least urgent, maybe crisis
            
        # Cap at 6
        return min(score, 6)
        
    def should_escalate_to_therapist(self, issues: List[Dict]) -> bool:
        """
        Determine if pattern suggests mental health crisis.
        
        Indicators:
        - Multiple hygiene issues
        - Social withdrawal
        - Routine collapse
        - Emotional dysregulation
        - Sustained low functioning
        
        This could be depression, not just ADHD struggles.
        """
        # Look for depression indicators
        hygiene_issues = sum(1 for i in issues if i['category'] == 'hygiene')
        social_issues = sum(1 for i in issues if i['category'] == 'social')
        duration_days = max((i.get('duration_days', 0) for i in issues), default=0)
        
        # Multiple severe issues over extended period = potential depression
        if hygiene_issues >= 2 and social_issues >= 1 and duration_days > 7:
            return True
            
        return False
```

### Intervention Strategy Generator

**Implementation**:

```python
class InterventionStrategy:
    """Generates context-appropriate interventions."""
    
    def __init__(self, adhd_state_detector: ADHDStateDetector, severity_scorer: SeverityScorer):
        self.adhd_detector = adhd_state_detector
        self.severity_scorer = severity_scorer
        
    def generate_intervention(self, issue: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create intervention appropriate for issue, severity, and ADHD state.
        
        Args:
            issue: The detected problem
            context: Current user state, environment, time, etc.
            
        Returns:
            {
                'message': str,  # What to say to user
                'tone': str,  # 'gentle', 'firm', 'urgent', 'caring'
                'action': str,  # 'alert', 'scaffolding', 'body_doubling', 'route_agent'
                'timing': str,  # 'immediate', 'wait_for_good_moment', 'daily_summary'
                'route_to_agent': str,  # Which agent to involve (if any)
                'expected_response': str  # What we hope user does
            }
        """
        severity = self.severity_scorer.calculate_severity(issue)
        adhd_state = self.adhd_detector.detect_current_state(context)
        
        # Generate intervention based on severity and ADHD state
        intervention = {}
        
        if severity == 1:  # Observation
            intervention = {
                'message': None,  # Don't say anything yet
                'action': 'log_only',
                'timing': 'none'
            }
            
        elif severity == 2:  # Gentle mention
            intervention = {
                'message': self._gentle_mention(issue),
                'tone': 'observational',
                'action': 'alert',
                'timing': 'wait_for_good_moment'
            }
            
        elif severity == 3:  # Suggestion
            intervention = {
                'message': self._suggest_action(issue),
                'tone': 'helpful',
                'action': 'offer_assistance',
                'timing': 'immediate'
            }
            
        elif severity == 4:  # Firm reminder
            intervention = {
                'message': self._firm_reminder(issue),
                'tone': 'direct',
                'action': 'push_for_action',
                'timing': 'immediate'
            }
            
        elif severity == 5:  # Urgent
            intervention = {
                'message': self._urgent_alert(issue),
                'tone': 'concerned',
                'action': 'require_acknowledgment',
                'timing': 'immediate'
            }
            
        elif severity == 6:  # Crisis
            intervention = {
                'message': "I'm concerned about some patterns I'm seeing. Can we talk?",
                'tone': 'caring',
                'action': 'route_to_therapist',
                'route_to_agent': 'therapist',
                'timing': 'immediate'
            }
            
        # Adjust for ADHD state
        intervention = self._adjust_for_adhd_state(intervention, adhd_state, issue)
        
        return intervention
        
    def _adjust_for_adhd_state(self, intervention: Dict, adhd_state: str, issue: Dict) -> Dict:
        """
        Modify intervention approach based on current ADHD state.
        
        Different states need different approaches.
        """
        if adhd_state == 'hyperfocus':
            # Don't interrupt hyperfocus unless urgent
            if intervention['timing'] != 'immediate' or intervention.get('severity', 0) < 4:
                intervention['timing'] = 'wait_for_break'
                
        elif adhd_state == 'paralysis':
            # Provide scaffolding, not just reminders
            intervention['action'] = 'step_by_step_guidance'
            intervention['body_doubling'] = True
            intervention['message'] = self._create_scaffolding(issue)
            
        elif adhd_state == 'overstimulation':
            # Reduce additional stimuli
            intervention['tone'] = 'calm'
            intervention['message'] = self._simplify_message(intervention['message'])
            
        elif adhd_state == 'dopamine_seeking':
            # Add reward/gamification
            intervention['reward'] = self._suggest_reward(issue)
            
        return intervention
        
    def _gentle_mention(self, issue: Dict) -> str:
        """Create gentle observational message."""
        category = issue['category']
        metric = issue['metric']
        
        if category == 'hygiene' and 'shower' in metric:
            return "I noticed it's been a couple days since you showered"
        elif category == 'household' and 'trash' in metric:
            return "Noticed the trash is getting full"
        elif category == 'social' and 'contact' in metric:
            person = issue.get('person', 'them')
            return f"It's been a while since you talked to {person}"
            
        return f"I noticed {metric} is different from usual"
        
    def _suggest_action(self, issue: Dict) -> str:
        """Create helpful suggestion."""
        category = issue['category']
        metric = issue['metric']
        
        if category == 'hygiene' and 'shower' in metric:
            return "Want to hop in the shower? I'll queue up your playlist"
        elif category == 'household' and 'trash' in metric:
            return "Want to take out the trash? I'll remind you to bring the bins in later"
        elif category == 'social' and 'contact' in metric:
            person = issue.get('person', 'them')
            return f"Want to send {person} a quick message?"
            
        return f"Want some help with {metric}?"
        
    def _firm_reminder(self, issue: Dict) -> str:
        """Create direct reminder."""
        category = issue['category']
        metric = issue['metric']
        
        if category == 'hygiene' and 'shower' in metric:
            return "Dude, you need to shower"
        elif category == 'household' and 'trash' in metric:
            return "Trash needs to go out - it's been a week"
        elif category == 'social' and 'contact' in metric:
            person = issue.get('person', 'them')
            return f"You promised {person} you'd follow up - time to do it"
            
        return f"{metric} needs attention"
        
    def _urgent_alert(self, issue: Dict) -> str:
        """Create urgent message."""
        category = issue['category']
        
        if category == 'hygiene':
            return "Real talk: you need to take care of yourself. This is becoming a problem."
        elif category == 'household':
            return "Your space is getting unhealthy. We need to address this."
        elif category == 'social':
            return "You're withdrawing from people. That's not like you. What's going on?"
            
        return "This needs immediate attention"
        
    def _create_scaffolding(self, issue: Dict) -> str:
        """
        Create step-by-step guidance for executive dysfunction.
        
        Break task into tiniest possible steps.
        """
        category = issue['category']
        metric = issue['metric']
        
        if category == 'hygiene' and 'shower' in metric:
            return """I see you're stuck. Let's break this down:
Step 1: Just stand up (that's all - don't think about the rest)
...then we'll do step 2"""
            
        elif category == 'household' and 'dishes' in metric:
            return """Let's make this tiny:
Step 1: Put one dish in the dishwasher (literally just one)
Then we'll see how you feel"""
            
        return "Let's break this into the smallest possible first step"
        
    def _suggest_reward(self, issue: Dict) -> str:
        """Add dopamine reward for task completion."""
        return "After you do this, you can [preferred reward activity] guilt-free"
```

### Body Doubling System

**Purpose**: Virtual presence to help ADHD users start/complete tasks

**Implementation**:

```python
class BodyDoublingSystem:
    """Provides virtual body doubling for ADHD task support."""
    
    def __init__(self):
        self.active_sessions = {}
        
    def start_body_doubling(self, user_id: str, task: str, estimated_minutes: int):
        """
        Begin body doubling session.
        
        ARCHER stays "present" while user works on task.
        Provides periodic check-ins and encouragement.
        """
        session_id = self._generate_session_id()
        
        self.active_sessions[session_id] = {
            'user_id': user_id,
            'task': task,
            'started': datetime.now(),
            'estimated_minutes': estimated_minutes,
            'check_ins': [],
            'status': 'active'
        }
        
        # Start monitoring
        self._schedule_check_ins(session_id)
        
        return {
            'session_id': session_id,
            'message': f"I'm here with you. Let's do this. Starting {task}..."
        }
        
    def check_in(self, session_id: str):
        """
        Periodic check-in during body doubling.
        
        Provides encouragement and tracks progress.
        """
        session = self.active_sessions.get(session_id)
        if not session:
            return
            
        elapsed = (datetime.now() - session['started']).total_seconds() / 60  # minutes
        
        messages = [
            f"Still here with you. {int(elapsed)} minutes in - you're doing great",
            "I see you working. Keep going.",
            f"Halfway through the estimated time. You've got this.",
            "Almost there. Finish strong."
        ]
        
        # Pick appropriate message based on progress
        progress = elapsed / session['estimated_minutes']
        
        if progress < 0.25:
            msg = messages[0]
        elif progress < 0.5:
            msg = messages[1]
        elif progress < 0.75:
            msg = messages[2]
        else:
            msg = messages[3]
            
        session['check_ins'].append({
            'timestamp': datetime.now(),
            'message': msg,
            'progress': progress
        })
        
        return msg
        
    def complete_session(self, session_id: str, task_completed: bool):
        """
        End body doubling session.
        
        Celebrate completion or acknowledge attempt.
        """
        session = self.active_sessions.get(session_id)
        if not session:
            return
            
        session['status'] = 'completed' if task_completed else 'attempted'
        session['ended'] = datetime.now()
        duration = (session['ended'] - session['started']).total_seconds() / 60
        
        if task_completed:
            return {
                'message': f"You did it! {duration:.0f} minutes. That's a win. Celebrate that.",
                'reward': True
            }
        else:
            return {
                'message': f"You tried for {duration:.0f} minutes. That counts. Don't beat yourself up.",
                'reward': False
            }
```

---

## DATABASE SCHEMA

### SQLite Tables

**File**: `src/archer/blindspot/schema.sql`

```sql
-- Blindspot Observations
CREATE TABLE IF NOT EXISTS blindspot_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,  -- 'hygiene', 'household', 'social', 'behavioral'
    metric TEXT NOT NULL,
    observed_value REAL,
    baseline_value REAL,
    normative_value REAL,
    deviation_percentage REAL,
    severity INTEGER,  -- 1-6
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE INDEX idx_observations_user_category ON blindspot_observations(user_id, category);
CREATE INDEX idx_observations_timestamp ON blindspot_observations(timestamp);

-- Interventions
CREATE TABLE IF NOT EXISTS blindspot_interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER,
    user_id TEXT NOT NULL,
    severity INTEGER,
    message TEXT NOT NULL,
    tone TEXT,  -- 'gentle', 'firm', 'urgent', 'caring'
    action TEXT,  -- 'alert', 'scaffolding', 'body_doubling', 'route_agent'
    delivered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    user_acknowledged BOOLEAN DEFAULT FALSE,
    user_action_taken BOOLEAN DEFAULT FALSE,
    routed_to_agent TEXT,
    FOREIGN KEY (observation_id) REFERENCES blindspot_observations(id)
);

CREATE INDEX idx_interventions_user ON blindspot_interventions(user_id);
CREATE INDEX idx_interventions_delivered ON blindspot_interventions(delivered_at);

-- User Baselines
CREATE TABLE IF NOT EXISTS user_baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    metric TEXT NOT NULL,
    baseline_value REAL NOT NULL,
    calibration_start DATE,
    calibration_end DATE,
    observation_count INTEGER,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, category, metric)
);

-- ADHD States
CREATE TABLE IF NOT EXISTS adhd_state_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    state TEXT NOT NULL,  -- 'hyperfocus', 'paralysis', 'overstimulation', etc.
    confidence REAL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME,
    duration_minutes INTEGER,
    context TEXT  -- JSON with environmental factors
);

CREATE INDEX idx_adhd_states_user ON adhd_state_log(user_id);
CREATE INDEX idx_adhd_states_timestamp ON adhd_state_log(started_at);

-- Task Tracking
CREATE TABLE IF NOT EXISTS task_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    task_description TEXT NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_activity DATETIME,
    completed_at DATETIME,
    abandoned_at DATETIME,
    interruption_count INTEGER DEFAULT 0,
    status TEXT,  -- 'active', 'completed', 'abandoned'
    duration_minutes INTEGER
);

CREATE INDEX idx_tasks_user_status ON task_tracking(user_id, status);

-- Medication Log
CREATE TABLE IF NOT EXISTS medication_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    medication_name TEXT,
    scheduled_time TIME,
    actual_time DATETIME,
    taken_on_time BOOLEAN,
    minutes_late INTEGER,
    dose TEXT,
    date DATE DEFAULT CURRENT_DATE
);

CREATE INDEX idx_medication_user_date ON medication_log(user_id, date);

-- Relationship Tracking
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    person_name TEXT NOT NULL,
    relationship_type TEXT,  -- 'family', 'friend', 'colleague'
    typical_interval_days INTEGER,
    last_interaction DATETIME,
    interaction_count INTEGER DEFAULT 0,
    metadata TEXT,  -- JSON with birthday, preferences, etc.
    UNIQUE(user_id, person_name)
);

CREATE TABLE IF NOT EXISTS relationship_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relationship_id INTEGER NOT NULL,
    interaction_type TEXT,  -- 'call', 'text', 'in-person', 'email'
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY (relationship_id) REFERENCES relationships(id)
);

CREATE INDEX idx_interactions_relationship ON relationship_interactions(relationship_id);

CREATE TABLE IF NOT EXISTS commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relationship_id INTEGER,
    user_id TEXT NOT NULL,
    promise TEXT NOT NULL,
    made_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    due_date DATETIME,
    fulfilled BOOLEAN DEFAULT FALSE,
    fulfilled_at DATETIME,
    status TEXT DEFAULT 'pending',
    FOREIGN KEY (relationship_id) REFERENCES relationships(id)
);

CREATE INDEX idx_commitments_user_status ON commitments(user_id, status);

-- Environmental Baselines
CREATE TABLE IF NOT EXISTS environment_baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    room_name TEXT NOT NULL,
    state TEXT NOT NULL,  -- 'clean', 'current'
    object_count INTEGER,
    clutter_score REAL,
    captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    image_hash TEXT,  -- For comparison
    UNIQUE(user_id, room_name, state)
);

-- Body Doubling Sessions
CREATE TABLE IF NOT EXISTS body_doubling_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    task_description TEXT NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    estimated_minutes INTEGER,
    actual_minutes INTEGER,
    completed BOOLEAN DEFAULT FALSE,
    check_in_count INTEGER DEFAULT 0,
    ended_at DATETIME
);

CREATE INDEX idx_body_doubling_user ON body_doubling_sessions(user_id);
```

---

## IMPLEMENTATION PHASES

### Phase 1: Foundation (Week 1-2)
**Goal**: Basic detection and intervention infrastructure

**Tasks**:
1. Database schema setup
2. Visual detection engine skeleton
   - Personal appearance analyzer (basic)
   - Environmental clutter detector (basic)
3. Normative standards database (initial data)
4. User baseline calibration system
5. Basic intervention generator
6. Integration with Observer pipeline

**Deliverables**:
- SQLite tables created
- Basic visual analysis working
- Can detect at least 3 types of issues (shower, trash, clutter)
- Interventions appear in conversation panel

**Success Criteria**:
- Detects when user hasn't showered in 3+ days
- Detects trash can overflow
- Generates gentle intervention message
- Logs to database

---

### Phase 2: ADHD Specialization (Week 3-4)
**Goal**: ADHD-specific pattern detection and state-aware interventions

**Tasks**:
1. ADHD state detector
2. ADHD pattern library implementation
3. Task completion tracker
4. Time blindness detector
5. Medication tracking integration
6. State-appropriate intervention strategies

**Deliverables**:
- ADHD state detection working
- Can identify hyperfocus, paralysis, dopamine-seeking
- Interventions adapt to ADHD state
- Medication timing tracked and correlated

**Success Criteria**:
- Detects hyperfocus and forces break
- Recognizes task paralysis and provides scaffolding
- Medication timing correlated with productivity
- Different intervention styles for different states

---

### Phase 3: Social & Relational (Week 5)
**Goal**: Relationship tracking and commitment monitoring

**Tasks**:
1. Relationship tracker implementation
2. Contact interaction logging
3. Commitment tracking system
4. Neglected relationship detection
5. Integration with calendar/contacts

**Deliverables**:
- Can track interactions with people
- Detects when user hasn't contacted someone in too long
- Tracks unfulfilled commitments
- Suggests social maintenance actions

**Success Criteria**:
- "Haven't talked to Mom in 2 weeks - you usually call weekly"
- "You told Mike you'd send that document 10 days ago"
- Relationship health scores calculated

---

### Phase 4: Advanced Visual Analysis (Week 6-7)
**Goal**: Sophisticated computer vision for environment and aesthetics

**Tasks**:
1. Furniture condition assessment
2. Aesthetic evaluation (color theory, design principles)
3. Plant health monitoring
4. Detailed clutter analysis
5. Improvement suggestion generator

**Deliverables**:
- Can assess furniture condition (worn, stained, etc.)
- Evaluates room aesthetics and suggests improvements
- Monitors plant health and watering needs
- Provides actionable design suggestions

**Success Criteria**:
- "Your couch is looking worn - here are replacement options"
- "Move bookshelf to north wall - it's blocking light"
- "Plants need water - they're wilting"

---

### Phase 5: Body Doubling & Advanced Support (Week 8)
**Goal**: Active task support and executive function scaffolding

**Tasks**:
1. Body doubling system
2. Step-by-step task scaffolding
3. Reward system integration
4. Progress tracking and celebration
5. Routine collapse recovery

**Deliverables**:
- Virtual body doubling sessions
- Breaks tasks into micro-steps
- Celebrates wins, encourages attempts
- Helps rebuild collapsed routines

**Success Criteria**:
- User successfully completes task with body doubling
- Task broken into tiny steps when paralyzed
- Routine soft-reset after disruption
- Completion celebrated with dopamine reward

---

### Phase 6: Integration & Polish (Week 9-10)
**Goal**: Smooth integration with other agents and UI polish

**Tasks**:
1. Therapist routing for mental health patterns
2. Assistant routing for organizing help
3. Trainer routing for hygiene habits
4. Dashboard for blindspot analytics
5. User preference controls (what to monitor, tone settings)
6. Privacy controls (opt in/out by category)

**Deliverables**:
- Seamless agent handoffs
- Analytics dashboard showing patterns
- User can configure monitoring preferences
- Privacy controls implemented

**Success Criteria**:
- Depression pattern routes to Therapist
- Organizing help routes to Assistant
- Dashboard shows blindspot trends
- User can disable specific monitoring categories

---

## PRIVACY & ETHICS

### Privacy Protections

**Critical Requirements**:

1. **Explicit Consent System**
   - User must explicitly enable Blindspot Agent
   - Category-by-category opt-in (hygiene, household, social, etc.)
   - Can disable at any time
   - Clear explanation of what's monitored

2. **Local Processing Only**
   - All computer vision processed locally
   - No images/videos sent to cloud
   - Analysis results stored locally (SQLite)
   - Camera access controlled by user

3. **Data Retention Controls**
   - User can set retention periods
   - Can delete all blindspot data
   - Can export data for review
   - Automatic cleanup of old observations

4. **Transparency**
   - User can see all observations logged
   - Can see what triggered each intervention
   - Can review baseline values
   - Can understand how patterns were detected

### Ethical Guidelines

**Tone & Approach**:
- Never shame or judge
- Assume good intent, recognize executive dysfunction
- Distinguish between "won't" and "can't"
- Provide help, not criticism
- Celebrate progress, not just completion

**Mental Health Awareness**:
- Recognize depression vs ADHD patterns
- Route to Therapist when appropriate
- Never diagnose, only observe and support
- Respect when user says "not now"

**Autonomy Respect**:
- User can decline interventions
- User defines their own standards
- ARCHER suggests, doesn't demand
- User can override any observation

**Cultural Sensitivity**:
- Standards vary across cultures
- User can set their own norms
- Don't assume Western standards are universal
- Learn from user's preferences

---

## TESTING CRITERIA

### Phase 1 Tests

**Visual Detection**:
- [ ] Detects facial hair at 3+ days growth
- [ ] Identifies wrinkled clothing (>30% wrinkle coverage)
- [ ] Measures trash can fill level (80%+ = full)
- [ ] Counts days since last shower (visual indicators)
- [ ] Detects clutter deviation from clean baseline (>50%)

**Baseline System**:
- [ ] Establishes user baseline from 14 days observation
- [ ] Stores baselines per category/metric
- [ ] Compares current to baseline accurately
- [ ] Calculates deviation percentages

**Intervention Generation**:
- [ ] Generates appropriate message for severity 2 (gentle)
- [ ] Generates appropriate message for severity 4 (firm)
- [ ] Chooses correct timing (immediate vs wait)
- [ ] Logs intervention to database

### Phase 2 Tests

**ADHD State Detection**:
- [ ] Detects hyperfocus (3+ hours no break)
- [ ] Detects paralysis (10+ task switches, <10min on each)
- [ ] Detects dopamine-seeking (excessive phone use)
- [ ] Detects overstimulation (high noise/visual chaos)

**Pattern Matching**:
- [ ] Identifies object permanence issue (item in drawer)
- [ ] Identifies time blindness (estimated 5min, actual 45min)
- [ ] Identifies routine collapse (3+ consecutive misses)
- [ ] Identifies impulse control failure (about to send angry message)

**State-Aware Interventions**:
- [ ] Provides scaffolding during paralysis
- [ ] Forces break during hyperfocus
- [ ] Reduces stimuli during overstimulation
- [ ] Redirects dopamine-seeking productively

### Phase 3 Tests

**Relationship Tracking**:
- [ ] Logs interactions with people
- [ ] Calculates typical interval between contacts
- [ ] Detects neglected relationships (1.5x typical interval)
- [ ] Tracks unfulfilled commitments

**Social Interventions**:
- [ ] Suggests contact when interval exceeded
- [ ] Reminds of unfulfilled promises
- [ ] Provides relationship health scores

### Phase 4 Tests

**Advanced Visual**:
- [ ] Assesses furniture condition (worn vs good)
- [ ] Evaluates color scheme harmony
- [ ] Detects furniture blocking windows
- [ ] Monitors plant health (wilting detection)
- [ ] Suggests specific room improvements

### Phase 5 Tests

**Body Doubling**:
- [ ] Starts session with task description
- [ ] Provides periodic check-ins (every 10-15 min)
- [ ] Tracks progress toward estimated time
- [ ] Celebrates completion
- [ ] Acknowledges attempt even if incomplete

**Task Scaffolding**:
- [ ] Breaks task into micro-steps
- [ ] Presents one step at a time
- [ ] Doesn't overwhelm with full task
- [ ] Provides next step after completion

### Phase 6 Tests

**Agent Routing**:
- [ ] Routes depression pattern to Therapist
- [ ] Routes organizing request to Assistant
- [ ] Routes hygiene habit to Trainer
- [ ] Provides context to receiving agent

**Privacy Controls**:
- [ ] User can disable hygiene monitoring
- [ ] User can disable household monitoring
- [ ] User can delete all blindspot data
- [ ] User can export observations

---

## INTEGRATION CHECKLIST

### Observer Pipeline Integration
- [ ] Blindspot receives frames from Observer webcam
- [ ] Blindspot uses MediaPipe pose data
- [ ] Blindspot uses DeepFace emotion data
- [ ] Blindspot analysis runs every 30 seconds (configurable)

### Memory System Integration
- [ ] Observations stored in SQLite
- [ ] Patterns indexed in ChromaDB for retrieval
- [ ] User baseline stored persistently
- [ ] Historical data available for trend analysis

### Agent Communication
- [ ] Can route to Therapist with context
- [ ] Can route to Assistant with context
- [ ] Can route to Trainer with context
- [ ] Receiving agent has full context of why routed

### GUI Integration
- [ ] Interventions appear in conversation panel
- [ ] Blindspot agent has unique color
- [ ] Dashboard shows blindspot metrics
- [ ] User can access blindspot settings

### Event Bus Integration
- [ ] Publishes BLINDSPOT_OBSERVATION events
- [ ] Publishes BLINDSPOT_INTERVENTION events
- [ ] Subscribes to USER_ACTIVITY events
- [ ] Subscribes to AGENT_RESPONSE events

---

## NOTES FOR ANTIGRAVITY

**Key Implementation Priorities**:

1. **Start with simplest detections**: Shower tracking, trash overflow, clutter
2. **Get baseline system working early**: Everything depends on knowing "normal"
3. **ADHD state detection is critical**: Interventions must adapt to state
4. **Privacy is non-negotiable**: Local processing, explicit consent, user control
5. **Tone matters enormously**: Caring but direct, never shaming

**Common Pitfalls to Avoid**:

- Don't make ARCHER judgy or parent-like (kills trust immediately)
- Don't intervene during hyperfocus unless urgent (user will resent it)
- Don't compare to neurotypical standards without ADHD adjustment
- Don't assume correlation = causation (test your pattern matching)
- Don't overwhelm user with too many interventions at once

**Success Indicators**:

- User actually acts on interventions (not just dismisses)
- User feels supported, not surveilled
- User willingly enables more monitoring categories
- User completion rates improve
- User reports feeling "seen" and understood

**This is the most complex agent in ARCHER. Take time to get it right.**

---

**END OF SPECIFICATION**

Total estimated implementation time: 10 weeks
Complexity: High
Value: Transformative - this is what makes ARCHER truly personal
