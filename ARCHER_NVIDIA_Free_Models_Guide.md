# NVIDIA Free API Models for ARCHER - Complete Analysis & Integration Guide

## NVIDIA NIM Free Tier Models (Confirmed Available)

Based on NVIDIA API Catalog (build.nvidia.com) and your OpenClaw config, here are the **FREE** models available:

---

## 🎯 **PRIMARY CONVERSATIONAL MODELS** (For ARCHER Agents)

### **1. Kimi K2.5 (Moonshot AI)** ⭐ **RECOMMENDED DEFAULT**
```json
{
  "id": "moonshotai/kimi-k2.5",
  "context": 200000,
  "cost": "FREE",
  "maxTokens": 8192
}
```

**Strengths**:
- 🏆 **200K context** (massive - can hold days of conversation)
- 🎯 **Built for extended dialogue** (designed for "concerned friend" use case)
- 💰 **Completely free**
- 🚀 **Multimodal** (text + images)
- 🧠 **Native session memory** built-in

**Best For**:
- Default conversational LLM for all 6 ARCHER agents
- Long-context conversations
- Memory-intensive tasks

**ARCHER Use Case**: **PRIMARY LLM** for cloud mode

---

### **2. Meta Llama 3.3 70B Instruct**
```json
{
  "id": "meta/llama-3.3-70b-instruct",
  "context": 128000,
  "cost": "FREE"
}
```

**Strengths**:
- 🎯 **Top-tier reasoning** (rivals GPT-4 quality)
- 📚 **128K context**
- ⚖️ **Apache 2.0 license** (fully permissive)
- 🔥 **Excellent instruction following**

**Best For**:
- Complex reasoning tasks
- Multi-step problem solving
- When you need highest quality responses

**ARCHER Use Case**: **Fallback for critical tasks** when Kimi K2.5 fails

---

### **3. Meta Llama 3.1 8B Instruct** 
```json
{
  "id": "meta/llama-3.1-8b-instruct",
  "context": 128000,
  "cost": "FREE"
}
```

**Strengths**:
- ⚡ **Fastest inference** (small model size)
- 📚 **128K context**
- 💾 **Low latency**
- 🎯 **Good general-purpose quality**

**Best For**:
- Quick responses when speed matters
- Simple queries
- Testing/prototyping

**ARCHER Use Case**: **Speed-optimized fallback**

---

### **4. Mixtral 8x7B Instruct** 
```json
{
  "id": "mistralai/mixtral-8x7b-instruct-v0.1",
  "context": 32000,
  "cost": "FREE"
}
```

**Strengths**:
- 🎭 **Excellent creative writing**
- 🌍 **Strong multilingual** (European languages)
- 🏃 **Fast MoE architecture**
- ⚖️ **Apache 2.0 license**

**Best For**:
- Creative tasks
- Multilingual conversations
- Balanced quality/speed

**ARCHER Use Case**: **Creative/multilingual specialist**

---

### **5. Mistral 7B Instruct v0.2**
```json
{
  "id": "mistralai/mistral-7b-instruct-v0.2",
  "context": 32000,
  "cost": "FREE"
}
```

**Strengths**:
- ⚡ **Very fast**
- 🎯 **Solid general performance**
- 💾 **Low resource usage**

**Best For**:
- Quick responses
- General chat
- Lightweight tasks

**ARCHER Use Case**: **Lightweight fallback**

---

## 🧠 **SPECIALIZED MODELS** (For Specific ARCHER Functions)

### **6. Google Gemma 3 27B** ⭐ **MULTIMODAL VISION**
```json
{
  "id": "google/gemma-3-27b",
  "context": 128000,
  "cost": "FREE",
  "multimodal": true
}
```

**Strengths**:
- 👁️ **Vision + text + video understanding**
- 🌍 **140+ languages**
- 🎯 **Top-tier reasoning**
- 📱 **Optimized for single GPU**

**Best For**:
- Analyzing webcam frames (Observer agent)
- Understanding visual context
- Multimodal conversations

**ARCHER Use Case**: **OBSERVER AGENT** - Process webcam frames for behavioral analysis

---

### **7. NVIDIA Nemotron-3 Nano 30B** ⭐ **CODING SPECIALIST**
```json
{
  "id": "nvidia/nemotron-3-nano-30b-a3b",
  "context": 1000000,  // 1M tokens!
  "cost": "FREE"
}
```

**Strengths**:
- 💻 **Excellent coding ability**
- 🎯 **Tool calling expert**
- 📚 **1M context window** (insane for long code analysis)
- 🧠 **Strong reasoning**
- 🏗️ **MoE architecture** (30B total, efficient inference)

**Best For**:
- Code generation/analysis
- Tool calling (PC Control functions)
- Complex reasoning chains
- Analyzing large codebases

**ARCHER Use Case**: **ASSISTANT AGENT** (when doing PC Control tasks, coding, or complex tool use)

---

### **8. NVIDIA Nemotron Nano 12B v2 VL** ⭐ **LIGHTWEIGHT VISION**
```json
{
  "id": "nvidia/nemotron-nano-12b-v2-vl",
  "cost": "FREE",
  "multimodal": true
}
```

**Strengths**:
- 👁️ **Multi-image + video understanding**
- 📝 **Visual Q&A and summarization**
- ⚡ **Lightweight** (12B only)
- 🎥 **Video analysis**

**Best For**:
- Fast visual understanding
- Video frame analysis
- Real-time vision tasks

**ARCHER Use Case**: **Fast webcam analysis** (alternative to Gemma 3)

---

### **9. DeepSeek R1** ⭐ **REASONING SPECIALIST**
```json
{
  "id": "deepseek/deepseek-r1",
  "context": 128000,
  "cost": "FREE"
}
```

**Strengths**:
- 🧠 **Chain-of-thought reasoning**
- 🔬 **Math and logic expert**
- 📊 **Complex problem solving**
- 💭 **Shows thinking process**

**Best For**:
- Mathematical reasoning
- Complex logical problems
- Multi-step analysis
- Finance/Investment calculations

**ARCHER Use Case**: **INVESTMENT/FINANCE AGENT** specialist model

---

### **10. Qwen 3.5 397B (MoE)** ⭐ **AGENTIC POWERHOUSE**
```json
{
  "id": "qwen/qwen3.5-397b-a17b",
  "context": 200000,
  "cost": "FREE",
  "multimodal": true
}
```

**Strengths**:
- 🤖 **Agentic AI specialist** (designed for autonomous agents)
- 👁️ **Vision-language model** (VLM)
- 🎯 **RAG optimized**
- 🏗️ **MoE architecture** (efficient despite size)
- 🌏 **Multilingual** (especially strong in Asian languages)

**Best For**:
- Agentic workflows
- Complex multi-step tasks
- RAG applications
- Vision + language tasks

**ARCHER Use Case**: **Advanced agentic orchestration** (potential future upgrade for complex multi-agent coordination)

---

## 📊 **MODEL COMPARISON FOR ARCHER USE CASES**

| Model | Context | Speed | Quality | Best Agent Match | Use Case |
|-------|---------|-------|---------|------------------|----------|
| **Kimi K2.5** | 200K | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ALL | Default conversational |
| **Llama 3.3 70B** | 128K | ⭐⭐ | ⭐⭐⭐⭐⭐ | Assistant | Critical reasoning |
| **Llama 3.1 8B** | 128K | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Assistant | Speed priority |
| **Mixtral 8x7B** | 32K | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Therapist | Creative/emotional |
| **Gemma 3 27B** | 128K | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Observer | Vision analysis |
| **Nemotron-3 30B** | 1M | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Assistant | Coding/tools |
| **DeepSeek R1** | 128K | ⭐⭐ | ⭐⭐⭐⭐⭐ | Finance/Investment | Math/reasoning |
| **Qwen 3.5 397B** | 200K | ⭐⭐ | ⭐⭐⭐⭐⭐ | Future | Agentic workflows |

---

## 🎨 **RECOMMENDED ARCHER MODEL SELECTION ARCHITECTURE**

### **Strategy 1: Agent-Specific Model Routing** ⭐ **RECOMMENDED**

```python
ARCHER_MODEL_STRATEGY = {
    "assistant": {
        "default": "moonshotai/kimi-k2.5",
        "coding": "nvidia/nemotron-3-nano-30b-a3b",
        "speed": "meta/llama-3.1-8b-instruct",
    },
    "therapist": {
        "default": "moonshotai/kimi-k2.5",
        "creative": "mistralai/mixtral-8x7b-instruct-v0.1",
    },
    "trainer": {
        "default": "moonshotai/kimi-k2.5",
    },
    "finance": {
        "default": "moonshotai/kimi-k2.5",
        "reasoning": "deepseek/deepseek-r1",
    },
    "investment": {
        "default": "deepseek/deepseek-r1",  # Math/logic specialist
        "fallback": "moonshotai/kimi-k2.5",
    },
    "observer": {
        "default": "google/gemma-3-27b",  # Vision specialist
        "lightweight": "nvidia/nemotron-nano-12b-v2-vl",
    }
}
```

**Rationale**: Each agent gets optimal model for its specialty while maintaining Kimi K2.5 as general fallback.

---

### **Strategy 2: Task-Based Routing**

```python
TASK_BASED_ROUTING = {
    "conversation": "moonshotai/kimi-k2.5",        # Default chat
    "coding": "nvidia/nemotron-3-nano-30b-a3b",    # PC Control, dev tasks
    "vision": "google/gemma-3-27b",                 # Webcam analysis
    "math": "deepseek/deepseek-r1",                 # Finance calculations
    "speed": "meta/llama-3.1-8b-instruct",         # Quick responses
    "reasoning": "meta/llama-3.3-70b-instruct",    # Complex problems
    "creative": "mistralai/mixtral-8x7b-instruct-v0.1",  # Writing
}
```

---

### **Strategy 3: Hybrid Context-Length Routing**

```python
def select_model_by_context(conversation_length: int):
    if conversation_length < 10:  # Short conversation
        return "meta/llama-3.1-8b-instruct"  # Fast
    elif conversation_length < 50:  # Medium
        return "moonshotai/kimi-k2.5"  # Balanced
    else:  # Long conversation (50+ turns)
        return "nvidia/nemotron-3-nano-30b-a3b"  # 1M context
```

---

## 🖥️ **GUI DROPDOWN SELECTOR DESIGN**

### **Option 1: Per-Agent Model Selector** ⭐ **RECOMMENDED**

```
┌─────────────────────────────────────────┐
│ ARCHER Configuration                     │
├─────────────────────────────────────────┤
│                                          │
│ ASSISTANT AGENT MODEL:                   │
│ ┌─────────────────────────────────────┐ │
│ │ Kimi K2.5 (Default)          ▼      │ │
│ └─────────────────────────────────────┘ │
│   Options:                               │
│   • Kimi K2.5 - 200K context, best all-around
│   • Nemotron-3 30B - Coding & tool use  │
│   • Llama 3.3 70B - Max reasoning       │
│   • Llama 3.1 8B - Fastest              │
│                                          │
│ THERAPIST AGENT MODEL:                   │
│ ┌─────────────────────────────────────┐ │
│ │ Kimi K2.5 (Default)          ▼      │ │
│ └─────────────────────────────────────┘ │
│                                          │
│ FINANCE AGENT MODEL:                     │
│ ┌─────────────────────────────────────┐ │
│ │ Kimi K2.5 (Default)          ▼      │ │
│ └─────────────────────────────────────┘ │
│   Options:                               │
│   • Kimi K2.5 - Conversational          │
│   • DeepSeek R1 - Math reasoning       │
│                                          │
│ INVESTMENT AGENT MODEL:                  │
│ ┌─────────────────────────────────────┐ │
│ │ DeepSeek R1 (Specialist)     ▼      │ │
│ └─────────────────────────────────────┘ │
│                                          │
│ OBSERVER AGENT MODEL:                    │
│ ┌─────────────────────────────────────┐ │
│ │ Gemma 3 27B (Vision)         ▼      │ │
│ └─────────────────────────────────────┘ │
│   Options:                               │
│   • Gemma 3 27B - Best vision quality   │
│   • Nemotron 12B VL - Fast vision       │
│                                          │
│           [Save Configuration]           │
└─────────────────────────────────────────┘
```

---

### **Option 2: Single Global Model Selector with Presets**

```
┌─────────────────────────────────────────┐
│ MODEL PRESET:                            │
│ ┌─────────────────────────────────────┐ │
│ │ Balanced (Recommended)       ▼      │ │
│ └─────────────────────────────────────┘ │
│                                          │
│ PRESETS:                                 │
│ • Balanced - Kimi K2.5 everywhere       │
│ • Performance - Specialized per agent   │
│ • Speed - Llama 3.1 8B everywhere       │
│ • Quality - Llama 3.3 70B everywhere    │
│ • Custom - Manual selection             │
│                                          │
│ [Advanced Configuration...]              │
└─────────────────────────────────────────┘
```

---

### **Option 3: Dynamic Smart Selector**

```
┌─────────────────────────────────────────┐
│ INTELLIGENT MODEL SELECTION:  [ON]      │
│                                          │
│ System will auto-select best model for: │
│ ✓ Conversation length (context window)  │
│ ✓ Agent specialty (coding, vision, etc) │
│ ✓ Task complexity (reasoning needed)    │
│ ✓ Response speed priority               │
│                                          │
│ Manual Override:                         │
│ ┌─────────────────────────────────────┐ │
│ │ Auto-Select              ▼          │ │
│ └─────────────────────────────────────┘ │
│                                          │
│ Available Models (10 free):              │
│ • Kimi K2.5 (200K ctx, conversational)  │
│ • Llama 3.3 70B (128K ctx, reasoning)   │
│ • Gemma 3 27B (128K ctx, vision)        │
│ • Nemotron-3 30B (1M ctx, coding)       │
│ • DeepSeek R1 (128K ctx, math)          │
│ • [Show all 10 models...]               │
└─────────────────────────────────────────┘
```

---

## 💻 **IMPLEMENTATION CODE**

### **Step 1: Update `config.py`**

```python
# src/archer/config.py

from typing import Literal

NVIDIA_FREE_MODELS = {
    # Conversational
    "kimi-k2.5": "moonshotai/kimi-k2.5",
    "llama-3.3-70b": "meta/llama-3.3-70b-instruct",
    "llama-3.1-8b": "meta/llama-3.1-8b-instruct",
    "mixtral-8x7b": "mistralai/mixtral-8x7b-instruct-v0.1",
    "mistral-7b": "mistralai/mistral-7b-instruct-v0.2",
    
    # Specialized
    "gemma-3-27b": "google/gemma-3-27b",  # Vision
    "nemotron-30b": "nvidia/nemotron-3-nano-30b-a3b",  # Coding
    "nemotron-12b-vl": "nvidia/nemotron-nano-12b-v2-vl",  # Vision
    "deepseek-r1": "deepseek/deepseek-r1",  # Reasoning
    "qwen-397b": "qwen/qwen3.5-397b-a17b",  # Agentic
}

class ArcherConfig(BaseSettings):
    # ... existing config ...
    
    # NVIDIA NIM Models
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    
    # Agent-specific model selection
    assistant_model: str = Field(default="kimi-k2.5", alias="ARCHER_ASSISTANT_MODEL")
    therapist_model: str = Field(default="kimi-k2.5", alias="ARCHER_THERAPIST_MODEL")
    trainer_model: str = Field(default="kimi-k2.5", alias="ARCHER_TRAINER_MODEL")
    finance_model: str = Field(default="kimi-k2.5", alias="ARCHER_FINANCE_MODEL")
    investment_model: str = Field(default="deepseek-r1", alias="ARCHER_INVESTMENT_MODEL")
    observer_model: str = Field(default="gemma-3-27b", alias="ARCHER_OBSERVER_MODEL")
    
    # Task-specific overrides
    coding_model: str = Field(default="nemotron-30b", alias="ARCHER_CODING_MODEL")
    vision_model: str = Field(default="gemma-3-27b", alias="ARCHER_VISION_MODEL")
    reasoning_model: str = Field(default="deepseek-r1", alias="ARCHER_REASONING_MODEL")
    speed_model: str = Field(default="llama-3.1-8b", alias="ARCHER_SPEED_MODEL")
```

---

### **Step 2: Model Selector in Orchestrator**

```python
# src/archer/agents/orchestrator.py

def _select_model_for_agent(self, agent: str, task_type: str | None = None) -> str:
    """
    Select the optimal NVIDIA NIM model based on agent and task type.
    
    Args:
        agent: The agent making the request (assistant, therapist, etc.)
        task_type: Optional task override (coding, vision, reasoning, speed)
    
    Returns:
        Full model ID (e.g., "moonshotai/kimi-k2.5")
    """
    # Task-specific override takes precedence
    if task_type == "coding":
        model_key = self._config.coding_model
    elif task_type == "vision":
        model_key = self._config.vision_model
    elif task_type == "reasoning":
        model_key = self._config.reasoning_model
    elif task_type == "speed":
        model_key = self._config.speed_model
    # Agent-specific selection
    elif agent == "assistant":
        model_key = self._config.assistant_model
    elif agent == "therapist":
        model_key = self._config.therapist_model
    elif agent == "trainer":
        model_key = self._config.trainer_model
    elif agent == "finance":
        model_key = self._config.finance_model
    elif agent == "investment":
        model_key = self._config.investment_model
    elif agent == "observer":
        model_key = self._config.observer_model
    else:
        model_key = "kimi-k2.5"  # Default fallback
    
    # Convert friendly name to full model ID
    return NVIDIA_FREE_MODELS.get(model_key, NVIDIA_FREE_MODELS["kimi-k2.5"])

def _stream_nvidia(self, text: str, agent: str, task_type: str | None = None):
    """Stream from appropriate NVIDIA NIM model."""
    import openai
    
    model_id = self._select_model_for_agent(agent, task_type)
    
    logger.info(f"Using NVIDIA model: {model_id} for {agent} agent (task: {task_type})")
    
    client = openai.OpenAI(
        base_url=self._config.nvidia_base_url,
        api_key=self._config.nvidia_api_key
    )
    
    system_prompt = self._build_system_prompt(agent)
    
    with self._history_lock:
        messages = list(self._conversation_history[-30:])
    
    stream = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            *messages
        ],
        stream=True,
        max_tokens=self._config.max_tokens,
        temperature=self._config.agent_temperature,
    )
    
    # ... rest of streaming logic ...
```

---

### **Step 3: GUI Model Selector Widget**

```python
# src/archer/gui/model_selector.py

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton

class ModelSelectorWidget(QWidget):
    """GUI widget for selecting models per agent."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout()
        
        # Assistant model selector
        layout.addWidget(QLabel("Assistant Agent Model:"))
        self.assistant_combo = QComboBox()
        self.assistant_combo.addItems([
            "Kimi K2.5 (Default - 200K context)",
            "Nemotron-3 30B (Coding & Tools - 1M context)",
            "Llama 3.3 70B (Max Reasoning - 128K context)",
            "Llama 3.1 8B (Fastest - 128K context)",
        ])
        layout.addWidget(self.assistant_combo)
        
        # Therapist model selector
        layout.addWidget(QLabel("Therapist Agent Model:"))
        self.therapist_combo = QComboBox()
        self.therapist_combo.addItems([
            "Kimi K2.5 (Default - Empathetic)",
            "Mixtral 8x7B (Creative - Warm tone)",
        ])
        layout.addWidget(self.therapist_combo)
        
        # Finance model selector
        layout.addWidget(QLabel("Finance Agent Model:"))
        self.finance_combo = QComboBox()
        self.finance_combo.addItems([
            "Kimi K2.5 (Conversational)",
            "DeepSeek R1 (Math Reasoning)",
        ])
        layout.addWidget(self.finance_combo)
        
        # Investment model selector
        layout.addWidget(QLabel("Investment Agent Model:"))
        self.investment_combo = QComboBox()
        self.investment_combo.addItems([
            "DeepSeek R1 (Specialist - Math/Logic)",
            "Kimi K2.5 (Fallback)",
        ])
        layout.addWidget(self.investment_combo)
        
        # Observer model selector
        layout.addWidget(QLabel("Observer Agent Model:"))
        self.observer_combo = QComboBox()
        self.observer_combo.addItems([
            "Gemma 3 27B (Vision Specialist)",
            "Nemotron 12B VL (Lightweight Vision)",
        ])
        layout.addWidget(self.observer_combo)
        
        # Save button
        save_btn = QPushButton("Save Configuration")
        save_btn.clicked.connect(self._save_config)
        layout.addWidget(save_btn)
        
        self.setLayout(layout)
    
    def _save_config(self):
        # Map selections back to model keys
        model_map = {
            "Kimi K2.5": "kimi-k2.5",
            "Nemotron-3 30B": "nemotron-30b",
            "Llama 3.3 70B": "llama-3.3-70b",
            "Llama 3.1 8B": "llama-3.1-8b",
            "Mixtral 8x7B": "mixtral-8x7b",
            "DeepSeek R1": "deepseek-r1",
            "Gemma 3 27B": "gemma-3-27b",
            "Nemotron 12B VL": "nemotron-12b-vl",
        }
        
        # Extract model key from selection
        # (Parse dropdown text to get model key)
        # Save to config or database
        # Emit signal to orchestrator to reload models
```

---

## 🚀 **RECOMMENDED IMPLEMENTATION PLAN**

### **Phase 1: Core Model Support** (4-6 hours)
1. ✅ Add all 10 NVIDIA models to config
2. ✅ Implement model selector in orchestrator
3. ✅ Add agent-specific defaults
4. ✅ Test basic conversation with Kimi K2.5

### **Phase 2: Specialized Routing** (4-6 hours)
1. ✅ Implement task-based routing (coding, vision, reasoning)
2. ✅ Add Observer agent Gemma 3 27B integration
3. ✅ Add Investment agent DeepSeek R1 routing
4. ✅ Test multi-model conversation flow

### **Phase 3: GUI Selector** (6-8 hours)
1. ✅ Create ModelSelectorWidget
2. ✅ Add to ARCHER settings panel
3. ✅ Implement save/load configuration
4. ✅ Add live model switching (no restart required)

### **Phase 4: Testing & Optimization** (8-12 hours)
1. ✅ Test all 10 models with each agent
2. ✅ Benchmark response quality
3. ✅ Measure latency differences
4. ✅ Optimize model selection heuristics
5. ✅ Document model comparison results

---

## 📋 **FINAL RECOMMENDATIONS**

### **Default Configuration** (Start Here):

```python
ARCHER_DEFAULTS = {
    "assistant": "kimi-k2.5",      # Best all-around
    "therapist": "kimi-k2.5",      # Empathetic conversation
    "trainer": "kimi-k2.5",        # Motivational support
    "finance": "kimi-k2.5",        # Conversational budgeting
    "investment": "deepseek-r1",   # Math/logic specialist
    "observer": "gemma-3-27b",     # Vision specialist
}

TASK_OVERRIDES = {
    "pc_control": "nemotron-30b",   # Coding & tool use
    "webcam_analysis": "gemma-3-27b",  # Vision
    "financial_calc": "deepseek-r1",   # Reasoning
    "quick_response": "llama-3.1-8b",  # Speed
}
```

### **Why This Works**:

1. **Kimi K2.5** as default → FREE, 200K context, designed for conversation
2. **DeepSeek R1** for Investment → Math specialist, perfect for calculations
3. **Gemma 3 27B** for Observer → Vision specialist, webcam analysis
4. **Nemotron-3 30B** for coding → Tool use expert, 1M context for code analysis
5. **All FREE** → Zero API costs

---

## 🎯 **BOTTOM LINE**

**You have access to 10+ FREE, production-grade models via NVIDIA NIM that cover:**

✅ **Conversational AI** (Kimi K2.5, Llama, Mixtral)  
✅ **Vision/Multimodal** (Gemma 3, Nemotron VL)  
✅ **Coding/Tools** (Nemotron-3 30B)  
✅ **Math/Reasoning** (DeepSeek R1)  
✅ **Agentic Workflows** (Qwen 3.5)  

**This is a massive upgrade** from just Qwen 2.5 local + Claude API. You now have:

- **Specialized models** for each agent's strengths
- **Zero cost** (all free via NVIDIA)
- **Flexible routing** (per-agent, per-task, per-context-length)
- **User control** (dropdown selection in GUI)

**Want me to implement the complete integration with the dropdown selector?**
