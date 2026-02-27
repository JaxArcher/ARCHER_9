# ARCHER Psychology Knowledge Base - Setup Instructions

**Purpose**: Five comprehensive knowledge documents for ARCHER Therapist agent's RAG system.

**Created**: February 26, 2026  
**Total Size**: ~65KB (43,000+ words)  
**Format**: Markdown (easily convertible to any RAG format)

---

## WHAT'S INCLUDED

### **1. CBT_fundamentals.md** (15KB)
**Core CBT principles including**:
- Cognitive model and thought-feeling-behavior cycle
- 10 common cognitive distortions (all-or-nothing, catastrophizing, etc.)
- Thought record technique
- Behavioral activation for depression
- Exposure therapy for anxiety
- Problem-solving framework
- Core beliefs vs. automatic thoughts
- Socratic questioning techniques
- Relapse prevention
- SMART goal setting

**Use Cases**: Challenging negative thoughts, detecting cognitive distortions, guiding interventions

---

### **2. behavioral_psychology.md** (14KB)
**Behavioral observation and intervention including**:
- Operant conditioning (reinforcement/punishment)
- ABC model (Antecedent-Behavior-Consequence)
- Baseline establishment methodology
- Detecting behavioral deviations
- Depression/anxiety/stress behavioral markers
- Habit formation and change
- Behavioral activation protocols
- Observational learning
- Behavioral experiments

**Use Cases**: Pattern recognition, baseline profiling, intervention timing

---

### **3. emotional_intelligence.md** (14KB)
**EQ development framework including**:
- Five components (self-awareness, self-regulation, motivation, empathy, social skills)
- Emotion vocabulary expansion (50+ emotion words)
- Self-regulation techniques (pause, reappraisal, physical release)
- Intrinsic vs. extrinsic motivation
- Three types of empathy (cognitive, emotional, compassionate)
- Assertive communication formula
- Conflict resolution steps
- Boundary setting
- Emotional bids in relationships

**Use Cases**: Emotional intelligence training, communication skills, relationship support

---

### **4. therapeutic_techniques.md** (11KB)
**Practical intervention strategies including**:
- Intervention urgency framework (crisis, high, moderate, low)
- Confrontational vs. supportive tone balance
- Motivational interviewing (RULE, OARS techniques)
- Validation levels (Linehan's 6 levels)
- Grounding techniques (5-4-3-2-1, box breathing)
- Crisis de-escalation steps
- Relapse prevention planning
- Addressing specific issues (procrastination, withdrawal, sleep avoidance)
- Therapeutic boundaries (what NOT to do)
- Progress measurement

**Use Cases**: Real-time interventions, crisis response, tone calibration

---

### **5. mental_health_assessment.md** (11KB)
**Profiling and assessment protocols including**:
- Baseline profiling questionnaire (6 categories, 30+ questions)
- Daily behavioral observation metrics
- Depression warning signs (behavioral, cognitive, emotional, physical)
- Anxiety warning signs
- Stress/burnout indicators
- Intervention urgency levels with specific responses
- Weekly/monthly monitoring frameworks
- Special cases (neurodivergence, trauma)

**Use Cases**: Initial profiling, ongoing monitoring, intervention urgency determination

---

## HOW TO INTEGRATE WITH ARCHER

### **Option 1: ChromaDB (Current ARCHER Setup)**

```python
import chromadb
from chromadb.utils import embedding_functions

# Initialize ChromaDB client
client = chromadb.PersistentClient(path="data/psychology_knowledge")

# Create collection with embedding function
ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

collection = client.create_collection(
    name="therapist_knowledge",
    embedding_function=ef,
    metadata={"description": "Psychology knowledge base for Therapist agent"}
)

# Load documents
import os
knowledge_dir = "/path/to/psychology_knowledge/"
documents = []
metadatas = []
ids = []

for filename in os.listdir(knowledge_dir):
    if filename.endswith(".md") and filename != "README.md":
        filepath = os.path.join(knowledge_dir, filename)
        with open(filepath, 'r') as f:
            content = f.read()
            
        # Split into chunks (max 1000 chars per chunk)
        chunks = [content[i:i+1000] for i in range(0, len(content), 1000)]
        
        for idx, chunk in enumerate(chunks):
            documents.append(chunk)
            metadatas.append({
                "source": filename,
                "chunk": idx,
                "category": filename.replace(".md", "")
            })
            ids.append(f"{filename}_{idx}")

# Add to collection
collection.add(
    documents=documents,
    metadatas=metadatas,
    ids=ids
)

print(f"Loaded {len(documents)} chunks into ChromaDB")
```

---

### **Option 2: Query Example**

```python
# When Therapist needs to intervene
def query_psychology_knowledge(query_text, n_results=3):
    results = collection.query(
        query_texts=[query_text],
        n_results=n_results
    )
    
    context = "\n\n".join(results['documents'][0])
    return context

# Example usage
user_message = "I can't do anything right. I'm a complete failure."

# Query for relevant CBT techniques
context = query_psychology_knowledge(
    "cognitive distortions all-or-nothing thinking challenge negative thoughts",
    n_results=5
)

# Use context in Therapist agent prompt
therapist_prompt = f"""
You are ARCHER's Therapist agent. Use the following knowledge to inform your response:

CONTEXT:
{context}

USER MESSAGE:
{user_message}

Respond with confrontational + clinical tone. Challenge cognitive distortions directly.
"""
```

---

## CHUNK SIZE RECOMMENDATIONS

**For ChromaDB**:
- **Chunk size**: 500-1000 characters
- **Overlap**: 100 characters
- **Why**: Balance between context and retrieval precision

**For OpenMemory** (if migrating):
- **Node size**: Natural sections (use markdown headers)
- **Relationships**: Link related concepts (e.g., CBT distortion → intervention technique)

---

## TESTING THE KNOWLEDGE BASE

### **Test Queries**:

1. **"User expressing hopelessness"**
   - Should retrieve: Depression indicators, intervention urgency, crisis protocols

2. **"User avoiding tasks due to anxiety"**
   - Should retrieve: Exposure hierarchy, behavioral activation, cognitive distortions

3. **"How to challenge all-or-nothing thinking"**
   - Should retrieve: CBT fundamentals, thought record, Socratic questioning

4. **"User baseline profiling questions"**
   - Should retrieve: Mental health assessment questionnaire sections

5. **"When to be confrontational vs supportive"**
   - Should retrieve: Therapeutic techniques tone balance

---

## FILE SIZES

```
CBT_fundamentals.md:           15,361 bytes
behavioral_psychology.md:      14,273 bytes
emotional_intelligence.md:     13,897 bytes
therapeutic_techniques.md:     11,245 bytes
mental_health_assessment.md:   10,987 bytes
-------------------------------------------
TOTAL:                         65,763 bytes (~65KB)
```

---

## IMPORTANT NOTES

### **These are NOT**:
- ❌ Medical textbooks
- ❌ Diagnostic tools
- ❌ Replacement for professional therapy
- ❌ Clinical treatment protocols

### **These ARE**:
- ✅ Synthesized psychology frameworks
- ✅ Evidence-based techniques
- ✅ Supportive intervention strategies
- ✅ Guidance for non-clinical AI applications

### **Critical Disclaimers**:
- Every document includes disclaimer that ARCHER is NOT a therapist
- Crisis protocols emphasize professional resources (988, crisis text line)
- Boundaries clearly defined (no diagnosis, no prescribing, no trauma processing)

---

## UPDATES & MAINTENANCE

**Version**: 1.0 (Initial Release)  
**Last Updated**: February 26, 2026

**To Update**:
1. Edit markdown files directly
2. Re-chunk and re-embed into ChromaDB
3. Test retrieval with sample queries
4. Validate Therapist agent responses

---

## NEXT STEPS FOR ANTIGRAVITY

1. **Load into ChromaDB** (or OpenMemory if migrating)
2. **Test retrieval** with queries above
3. **Integrate with Therapist agent** prompt
4. **Validate responses** match expected tone (confrontational + clinical)
5. **Confirm pyttsx3 is documented as forbidden** ✅ (See therapeutic_techniques.md)

---

## QUESTIONS?

These documents are comprehensive but not exhaustive. If Therapist agent needs additional psychology knowledge:
- Add new sections to existing files
- Create new specialized files (e.g., "anxiety_techniques.md")
- Request additional content from Col

**Ready for immediate RAG integration!**
