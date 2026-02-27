import sys
from pathlib import Path
import time

# Add src to path
sys.path.append(str(Path("d:/ARCHER_9/src")))

from archer.memory.redis_buffer import get_redis_buffer
from archer.memory.markdown_logger import get_markdown_logger
from archer.memory.openmemory_store import get_openmemory_store
from archer.config import get_config

def test_memory():
    print("--- Test 3: 3-Layer Memory System ---")
    
    # 1. Redis (Layer 1)
    redis_buf = get_redis_buffer()
    if redis_buf._client is not None:
        print("[OK] Layer 1: Redis Buffer available.")
        test_data = {"status": "testing"}
        redis_buf.save_snapshot("test_session", test_data)
        val = redis_buf.load_snapshot("test_session")
        if val and val.get("status") == "testing":
            print("[OK] Redis read/write functional.")
        else:
            print("[FAIL] Redis data integrity issue.")
    else:
        print("[WARNING] Layer 1: Redis NOT available (Check Docker).")

    # 2. Markdown (Layer 2)
    md = get_markdown_logger()
    md.log_turn("user", "Hello Layer 2", agent="assistant")
    # File should be in data/memory/YYYY-MM-DD.md
    log_file = Path("data/memory") / f"{time.strftime('%Y-%m-%d')}.md"
    if log_file.exists():
        print(f"[OK] Layer 2: Markdown logging functional ({log_file}).")
    else:
        print(f"[FAIL] Markdown log file not found at {log_file}.")

    # 3. OpenMemory (Layer 3)
    om = get_openmemory_store()
    try:
        om.add_memory("The password to the secret base is 'Archer123'", sector="semantic")
        print("[OK] Layer 3: OpenMemory write functional.")
        
        # Retrieval test
        memos = om.search("secret base password")
        if memos:
            print(f"[OK] OpenMemory retrieval functional: {memos[0].get('content')}")
        else:
            print("[FAIL] OpenMemory retrieval returned no results.")
    except Exception as e:
        print(f"[FAIL] OpenMemory operation failed: {e}")

if __name__ == "__main__":
    test_memory()
