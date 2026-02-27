import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path("d:/ARCHER_9/src")))

from archer.memory.chromadb_store import get_chromadb_store

def check_counts():
    store = get_chromadb_store()
    collections = ["archer_memory", "psychology_knowledge", "trainer_knowledge"]
    
    for c in collections:
        count = store.count(c)
        print(f"Collection '{c}': {count} documents")
        
    # Try a raw query
    if store.is_available:
        print("\nTesting raw query on 'trainer_knowledge'...")
        results = store.query("protein hypertrophy", collection_name="trainer_knowledge")
        print(f"Results found: {len(results)}")
        for r in results:
            print(f"- [{r['metadata'].get('source')}] {r['content'][:100]}...")

if __name__ == "__main__":
    check_counts()
