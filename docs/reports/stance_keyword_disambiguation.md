# ARCHER Technical Report: Disambiguating User Self-Expression vs. Quoting / Referencing

**Item Reference**: Live Testing Item 7  
**Target Module**: [`src/archer/agents/core_agent.py`](file:///d:/ARCHER_9/src/archer/agents/core_agent.py)  
**Status**: Disambiguation Architecture & Options Analysis  

---

## 1. Problem Statement

Keyword matching in `calculate_stance_tags()` is vulnerable to plain substring triggers. During live testing, when the user said *"sad or angry"* while quoting back an incorrect claim ARCHER had made about him (e.g. *"You said I was sad or angry earlier"*), the system triggered the full therapeutic register (`stance_prompt += "\n[Stance: Therapeutic & Reflective Register..."`).

### Root Cause:
The stance tag calculator evaluated keyword presence (e.g. `"sad"`, `"angry"`) without checking syntactic framing, quotation context, or whether the user was describing their *own current emotional state* versus discussing system behavior.

---

## 2. Technical Options Analysis

Below are 4 technical options for distinguishing user self-expression from quoting or referencing:

### Option A: Syntactic Dependency Parsing (spaCy / Local Rule Guard)
- **Method**: Use a lightweight NLP parser (`spaCy` `en_core_web_sm`) to analyze sentence structure.
- **Rule**: Require that emotional adjectives (`sad`, `angry`, `anxious`) be predicate adjectives linked to a first-person subject pronoun (`I`, `me`, `my`).
- **Example**:
  - `I am sad today` $\rightarrow$ `nsubj(sad) == "I"` $\rightarrow$ **TRIGGER THERAPEUTIC**
  - `You said I was sad` $\rightarrow$ `nsubj(said) == "You"`, `dobj(said) == "clause"` $\rightarrow$ **SUPPRESS THERAPEUTIC**
- **Pros**: Highly accurate syntactic ground truth.
- **Cons**: Adds a 5–10ms CPU dependency parsing overhead per turn.

---

### Option B: Regex Quote-Stripping & Meta-Question Filtering (Implemented Foundation)
- **Method**: Pre-process input text before scoring stance keywords:
  1. **Quote Stripping**: Strip content enclosed in quotation marks: `re.sub(r'["\'].*?["\']', '', text)`
  2. **Meta-Question Patterns**: Detect patterns where the user references past claims or system behavior:
     - `"you said"`, `"you claimed"`, `"you thought"`, `"you called"`, `"why did you say"`, `"your reading"`, `"incorrect"`, `"wrong"`
  3. **Negation Filtering**: Filter out negated keywords (`"not sad"`, `"not angry"`).
- **Pros**: Zero runtime overhead (<1ms), zero external dependencies, highly deterministic.
- **Cons**: Relies on maintaining pattern sets for meta-conversational phrasing.

---

### Option C: Micro-LLM / Zero-Shot Intent Classifier
- **Method**: Pass the turn through a micro-classifier prompt before stance scoring:
  - **Classes**: `[SELF_EMOTIONAL_EXPRESSION, QUOTING_OR_CORRECTING_SYSTEM, META_DISCUSSION, GENERAL_QUERY]`
- **Rule**: Only apply the therapeutic register if classified as `SELF_EMOTIONAL_EXPRESSION` with confidence $>0.80$.
- **Pros**: Solves complex nuances and implicit quoting.
- **Cons**: Adds 40–80ms latency to the turn context-assembly pipeline.

---

### Option D: Dialog-State Context Tracking (State Machine)
- **Method**: Track whether ARCHER emitted an ambient sensor alert or emotion confirmation question in the immediate prior turn ($T-1$).
- **Rule**: If turn $T-1$ was a system observation or confirmation question (e.g. *"Observer detected sustained distress"* or *"Did you feel sad?"*), any emotion keywords in turn $T$ are tagged as a **meta-response to system readings** rather than a new emotional disclosure.
- **Pros**: Completely eliminates false triggers caused by user feedback to ARCHER's proactive interventions.
- **Cons**: Requires active dialog-state tracking across turns.

---

## 3. Recommended Hybrid Implementation Strategy

Combine **Option B (Regex Quote-Stripping)** with **Option D (Dialog-State Tracking)**:

1. **Pre-Scoring Sanitization**: Strip quoted strings (`""`, `''`) and filter out meta-conversational phrases (`you said`, `why did you`, `your reading`).
2. **Dialog-State Awareness**: Check if the previous turn contained an ambient sensor flag or emotion confirmation question. If active, suppress automatic therapeutic stance escalation for that turn.
