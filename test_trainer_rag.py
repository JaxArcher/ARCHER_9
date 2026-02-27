import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path("d:/ARCHER_9/src")))

from archer.agents.orchestrator import AgentOrchestrator
from archer.config import get_config

def test_trainer_rag():
    print("--- Test 2: Trainer RAG Retrieval ---")
    
    config = get_config()
    orch = AgentOrchestrator()
    
    # Query related to nutrition/exercise
    query = "How much protein do I need and what are some good exercises for hypertrophy?"
    
    # Inject fake history for Orchestrator to pull from
    orch._conversation_history.append({"role": "user", "content": query})
    
    # We bypass the full process_request to just check memory retrieval
    context = orch._retrieve_memory_context("trainer")
    
    print(f"Query: {query}")
    print("Context retrieved:")
    if context:
        print(context)
        if "[KB:nutrition_science.md]" in context:
            print("[OK] Nutrition knowledge retrieved.")
        if "[KB:exercise_physiology.md]" in context:
            print("[OK] Exercise knowledge retrieved.")
    else:
        print("[FAIL] No context retrieved.")

if __name__ == "__main__":
    test_trainer_rag()
