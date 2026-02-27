import sys
from pathlib import Path
import time

# Add src to path
sys.path.append(str(Path("d:/ARCHER_9/src")))

from archer.config import get_config
from archer.observer.pipeline import ObserverPipeline

def test_observer():
    print("--- Test 4: Observer Pipeline ---")
    config = get_config()
    
    # 1. Verify Frequency
    print(f"Target Analysis Frequency: {config.observer_analysis_frequency}s")
    
    # 2. Verify Pipeline initialization
    try:
        pipeline = ObserverPipeline()
        print(f"[OK] Pipeline initialized with interval: {pipeline._analysis_interval}s")
        
        if pipeline._analysis_interval == config.observer_analysis_frequency:
             print("[OK] Pipeline frequency matches configuration.")
        else:
             print(f"[FAIL] Pipeline frequency ({pipeline._analysis_interval}) mismatch.")
             
    except Exception as e:
        print(f"[FAIL] Pipeline initialization failed: {e}")

    # 3. Verify Vision Model (Local Vision)
    print(f"Vision Model: {config.observer_model}")
    if "7b" in config.observer_model.lower():
         print("[OK] High-performance local vision model selected.")
    else:
         print(f"[WARNING] Model {config.observer_model} may be suboptimal.")

if __name__ == "__main__":
    test_observer()
