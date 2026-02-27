import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path("d:/ARCHER_9/src")))

from archer.memory.chromadb_store import get_chromadb_store
from loguru import logger

def load_trainer_knowledge():
    store = get_chromadb_store()
    if not store.is_available:
        logger.error("ChromaDB not available.")
        return

    knowledge_files = [
        "exercise_physiology.md",
        "nutrition_science.md",
        "habit_formation.md"
    ]
    
    base_path = Path("d:/ARCHER_9")
    collection_name = "trainer_knowledge"
    
    total_chunks = 0
    for filename in knowledge_files:
        filepath = base_path / filename
        if not filepath.exists():
            logger.warning(f"File not found: {filepath}")
            continue
            
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Split into chunks
        chunks = []
        paragraphs = content.split("\n\n")
        current_chunk = ""
        
        for p in paragraphs:
            if len(current_chunk) + len(p) < 1000:
                current_chunk += p + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p + "\n\n"
        if current_chunk:
            chunks.append(current_chunk.strip())

        logger.info(f"Loading {filename} ({len(chunks)} chunks)...")
        
        for idx, chunk in enumerate(chunks):
            success = store.store(
                content=chunk,
                agent="system",
                collection_name=collection_name,
                metadata={
                    "source": filename,
                    "chunk": idx,
                    "category": filename.replace(".md", "")
                }
            )
            if success:
                total_chunks += 1
            else:
                logger.error(f"Failed to store chunk {idx} of {filename}")

    logger.info(f"Successfully loaded {total_chunks} chunks into {collection_name}")

if __name__ == "__main__":
    load_trainer_knowledge()
