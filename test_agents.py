import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path("d:/ARCHER_9/src")))

from archer.agents.orchestrator import AgentOrchestrator
from archer.config import get_config

def test_agents():
    print("--- Test 1: Agent Architecture ---")
    
    # 1. Verify agents exist in orchestrator
    config = get_config()
    orch = AgentOrchestrator()
    
    expected_agents = ["assistant", "therapist", "trainer", "investment", "observer"]
    active_agents = orch._souls.keys()
    
    for agent in expected_agents:
        if agent in active_agents:
            print(f"[OK] Agent '{agent}' exists.")
        else:
            print(f"[FAIL] Agent '{agent}' MISSING.")

    # 2. Verify Finance is DELETED
    finance_path = Path("d:/ARCHER_9/src/archer/agents/finance")
    if not finance_path.exists():
        print("[OK] Finance agent directory DELETED.")
    else:
        print("[FAIL] Finance agent directory still exists.")
    
    if "finance" not in active_agents:
        print("[OK] Finance agent removed from Orchestrator.")
    else:
        print("[FAIL] Finance agent still in Orchestrator.")

if __name__ == "__main__":
    test_agents()
