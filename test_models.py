import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(str(Path("d:/ARCHER_9/src")))

from archer.config import get_config
from archer.agents.orchestrator import AgentOrchestrator

def test_models():
    print("--- Test 2: Model Routing & NVIDIA NIM ---")
    config = get_config()
    
    # 1. Verify Config
    print(f"Assistant Model: {config.assistant_model}")
    print(f"Therapist Model: {config.therapist_model}")
    print(f"Trainer Model: {config.trainer_model}")
    print(f"Investment Model: {config.investment_model}")
    print(f"Observer Model: {config.observer_model}")
    
    if "nvidia" in config.nvidia_base_url.lower():
        print("[OK] NVIDIA NIM Base URL configured.")
    else:
        print("[FAIL] NVIDIA NIM Base URL incorrect.")
        
    if config.nvidia_api_key:
        print("[OK] NVIDIA API Key present.")
    else:
        print("[WARNING] NVIDIA API Key missing. Specialists will fail.")

    # 2. Verify Local Vision config
    if config.use_local_vision:
        print("[OK] Observer configured for LOCAL vision (Privacy compliant).")
    else:
        print("[FAIL] Observer NOT configured for local vision.")

    # 3. Test Orchestrator Routing
    orch = AgentOrchestrator()
    
    test_cases = [
        ("How's the S&P 500 doing today?", "investment"),
        ("I'm feeling really stressed about work.", "therapist"),
        ("What's a good workout for my back?", "trainer"),
        ("Set a timer for 10 minutes.", "assistant"),
    ]
    
    for text, expected in test_cases:
        actual = orch._classify_agent(text)
        if actual == expected:
            print(f"[OK] Routing: '{text[:20]}...' -> {actual}")
        else:
            print(f"[FAIL] Routing: '{text[:20]}...' -> {actual} (Expected: {expected})")

if __name__ == "__main__":
    test_models()
