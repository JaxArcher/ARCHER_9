# Mental Health Assessment & Profiling for AI Applications

**Document Purpose**: Guide ARCHER in establishing baselines, detecting mental health indicators, and determining intervention urgency.

**Critical Disclaimer**: This is NOT for diagnosis. Only licensed professionals can diagnose mental health conditions.

---

## BASELINE PROFILING QUESTIONNAIRE

### **Phase 1: Initial Assessment** (Week 1-2)

**Emotional Baseline**:
```
1. On a scale of 1-10, how would you rate your typical stress level?
2. How would you describe your mood on an average day? (Happy, neutral, sad, anxious, etc.)
3. How often do you feel overwhelmed? (Daily, weekly, monthly, rarely)
4. What's your usual emotional range? (Stable vs. lots of ups and downs)
5. On a good day emotionally, what number would you rate yourself (1-10)?
```

**Sleep Patterns**:
```
1. What time do you typically go to bed on weeknights?
2. What time do you typically wake up?
3. How many hours of sleep do you usually get?
4. How would you rate your sleep quality? (1-10, where 10 is "wake up refreshed")
5. Do you have trouble falling asleep, staying asleep, or both?
```

**Social Interaction**:
```
1. How often do you interact with friends/family in person? (Daily, weekly, monthly)
2. How long do these interactions typically last?
3. Do you typically initiate social contact, or do others reach out first?
4. How comfortable are you with socializing? (1-10)
5. Do you feel lonely? (Never, sometimes, often, always)
```

**Activity & Energy**:
```
1. How many hours per day are you typically sedentary (sitting/lying)?
2. How often do you exercise? (Times per week, duration)
3. What's your typical energy level throughout the day? (1-10)
4. Do you have activities/hobbies you enjoy?
5. How motivated do you feel on a typical day? (1-10)
```

**Self-Care**:
```
1. How often do you shower/maintain hygiene?
2. How many meals do you typically eat per day?
3. Do you have regular meal times?
4. How often do you clean/organize your living space?
5. Do you feel you take care of yourself adequately?
```

**Stress & Coping**:
```
1. What are your biggest sources of stress currently?
2. When you're stressed, what do you typically do?
3. Do you have coping strategies that work well for you?
4. Do you avoid things when anxious/stressed?
5. How do you recover from bad days?
```

---

## BEHAVIORAL OBSERVATION METRICS

### **Data to Track Daily** (Automated via Observer):

**Sleep**:
- Bedtime
- Wake time
- Total sleep duration
- Sleep quality indicators (restlessness, awakenings)

**Activity**:
- Sedentary time (hours)
- Movement/exercise (type, duration)
- Posture (slouched vs. upright)

**Social**:
- Number of in-person interactions
- Duration of interactions
- Tone of interactions (positive, neutral, negative)

**Self-Care**:
- Hygiene routine completion
- Meal times and regularity
- Workspace organization state

**Emotional Signals** (from webcam/conversation):
- Facial expressions (flat, engaged, distressed)
- Tone of voice (flat, energetic, tense)
- Conversation patterns (withdrawn, engaged, scattered)

---

## MENTAL HEALTH INDICATORS (What to Watch For)

### **Depression Warning Signs**:

**Behavioral**:
- Withdrawal from activities (especially previously enjoyed)
- Social isolation (50%+ reduction from baseline)
- Psychomotor retardation (moving slowly, low energy)
- Sleep disruption (too much OR too little)
- Appetite changes (eating more or less than baseline)
- Neglecting self-care (skipping showers, hygiene)

**Cognitive**:
- Negative self-talk increasing
- Hopelessness expressed ("What's the point?")
- Difficulty concentrating (scattered conversation)
- Indecisiveness (paralyzed by simple choices)
- All-or-nothing thinking intensifying

**Emotional**:
- Flat affect (expressionless, monotone)
- Anhedonia (can't enjoy previously liked activities)
- Persistent sadness (2+ weeks)
- Irritability
- Crying spells

**Physical**:
- Fatigue (even after adequate sleep)
- Aches/pains without clear cause
- Psychomotor agitation (restlessness, pacing)

**Threshold for Concern**:
- 3+ symptoms persisting for 2+ weeks → Encourage professional evaluation

---

### **Anxiety Warning Signs**:

**Behavioral**:
- Avoidance increasing (canceling plans, procrastination)
- Safety behaviors (checking, reassurance-seeking)
- Restlessness, fidgeting
- Difficulty staying present in conversations

**Cognitive**:
- Catastrophizing ("What if..." spirals)
- Overestimating danger
- Underestimating ability to cope
- Rumination (repetitive worry thoughts)
- Mind racing, can't shut off thoughts

**Emotional**:
- Excessive worry (disproportionate to situation)
- Feeling on edge
- Irritability
- Dread or sense of impending doom
- Panic attacks

**Physical**:
- Muscle tension (jaw clenching, shoulder tension)
- Sleep onset insomnia (trouble falling asleep)
- Rapid heartbeat, shortness of breath
- Digestive issues (nausea, stomach pain)
- Trembling, shakiness

**Threshold for Concern**:
- Anxiety interfering with daily functioning (missing work, avoiding necessary tasks)
- Panic attacks occurring
- Physical symptoms persistent

---

### **Stress/Burnout Warning Signs**:

**Behavioral**:
- Working excessive hours but less productive
- Procrastination increasing
- Increased substance use (caffeine, alcohol)
- Skipping meals or eating irregularly

**Cognitive**:
- Cynicism, detachment
- Difficulty concentrating
- Memory problems
- Negativity bias (focusing on what's wrong)

**Emotional**:
- Irritability, short temper
- Emotional exhaustion
- Feeling overwhelmed constantly
- Loss of satisfaction in accomplishments

**Physical**:
- Tension headaches
- Muscle pain (especially neck/shoulders)
- Exhaustion that doesn't improve with rest
- Frequent illness (lowered immune function)

**Threshold for Concern**:
- Burnout symptoms persisting despite time off
- Physical health impacted
- Performance significantly declining

---

## INTERVENTION URGENCY LEVELS

### **CRISIS** (Immediate Action):

**Indicators**:
- Suicidal ideation ("I want to die", "Everyone would be better off without me")
- Self-harm mentioned or observed
- Psychotic symptoms (hallucinations, delusions, severely disorganized thinking)
- Severe dissociation (disconnected from reality)

**Response**:
```
IMMEDIATE:
1. "I'm concerned about your safety. I'm going to give you crisis resources."
2. Provide:
   - 988 Suicide & Crisis Lifeline
   - Crisis Text Line: Text HOME to 741741
   - Emergency services (911) if immediate danger
3. "Will you reach out to one of these right now? I can't provide the help you need in this moment."
4. If possible, notify emergency contact (if configured)
```

**DO NOT**:
- Try to talk them out of it alone
- Minimize ("It's not that bad")
- Leave them unsupported

---

### **HIGH URGENCY** (Within 24 Hours):

**Indicators**:
- Severe behavioral disruption (3+ days)
- Complete withdrawal (zero social contact, not leaving house)
- Expressed hopelessness without suicidal ideation
- Significant self-care neglect (not eating, not sleeping)

**Response**:
```
Proactive check-in:
"I've noticed [specific observations]. This is significantly different from your baseline. I'm concerned. What's going on?"

Then:
- Encourage professional support: "Have you considered talking to a therapist about this?"
- Provide resources for immediate support (crisis line, therapy options)
- Check-in again within 24 hours
```

---

### **MODERATE URGENCY** (1-3 Days):

**Indicators**:
- 50%+ deviation from baseline in key area
- Emerging negative patterns (2-3 days of disruption)
- User expressing struggle but still functioning

**Response**:
```
Gentle intervention:
"I've noticed [pattern]. This is outside your typical baseline. Let's talk about what's contributing to this."

Then:
- Offer coping strategies
- Behavioral activation suggestions
- Monitor closely
```

---

### **LOW URGENCY** (Monitor):

**Indicators**:
- 25-30% deviation from baseline
- Temporary disruption (1-2 days)
- User aware and addressing issue

**Response**:
```
Acknowledge + Offer support:
"Looks like you're having a rough patch. Need anything from me, or are you handling it?"

Then:
- Available if needed
- Continue monitoring
```

---

## ONGOING MONITORING

### **Weekly Check-Ins** (Automated):

**Track Trends**:
- Is mood improving, stable, or declining?
- Are negative patterns increasing or decreasing?
- Is user engaging more or less with activities?

**Questions to Ask**:
```
"How would you rate this week overall? (1-10)"
"What went well this week?"
"What was challenging?"
"Anything you want to work on next week?"
```

### **Monthly Assessments**:

**Compare to Baseline**:
- Sleep patterns vs. baseline
- Social interaction vs. baseline
- Activity level vs. baseline
- Mood stability vs. baseline

**Adjust Baseline If Needed**:
- If user has sustained improvement (4+ weeks), update baseline to reflect new normal
- If user has sustained decline, flag for professional support

---

## PROFILING SPECIAL CASES

### **Neurodivergence** (ADHD, Autism, etc.):

**Different Baselines**:
- Social interaction needs may be lower (not a problem)
- Sensory sensitivities affect environment preferences
- Executive function challenges (organization, time management)

**Avoid Pathologizing**:
- Different ≠ Disordered
- Focus on *functioning* not *conforming*

---

### **Trauma History**:

**Be Aware Of**:
- Hypervigilance (always on guard)
- Avoidance of triggers
- Emotional numbness
- Flashbacks/intrusive thoughts

**Do NOT**:
- Press for details about trauma
- Try to process trauma (requires professional)

**Do**:
- Provide grounding techniques if dysregulated
- Validate feelings
- Encourage trauma-informed therapy

---

## REFERENCES

- American Psychiatric Association. (2013). *Diagnostic and Statistical Manual of Mental Disorders* (5th ed.)
- National Institute of Mental Health. (2023). Mental Health Information
- Kroenke, K., et al. (2001). PHQ-9 (depression screening)
- Spitzer, R. L., et al. (2006). GAD-7 (anxiety screening)

**Document Status**: v1.0 - Ready for RAG
**Last Updated**: February 26, 2026
**Purpose**: ARCHER Mental Health Assessment Knowledge Base
