"""
Name a recurring unrecognized face so ARCHER recognizes it from now on.

    .venv\Scripts\python.exe scripts\name_person.py               (list who's waiting)
    .venv\Scripts\python.exe scripts\name_person.py Person_2 Col

Added 2026-10-06. The browser's "Unrecognized People" pane was removed on
2026-09-19, which left no way to name a face the observer keeps seeing but
can't match -- e.g. Col himself, who the observer has been logging as
"Person_2".

What it does: for each camera that has seen this face (the close-up webcam
and the across-the-room Reolink see the same face very differently), it
averages that face's most recent sightings into one reference and stores
it under the given name. If the name is already enrolled, these are ADDED
as extra references (known_person_references) -- the existing enrollment
is never overwritten, which is the mistake that broke Col's recognition
when Person_2 was first named on 2026-09-19. The observer re-reads known
faces on every sighting, so no restart is needed.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)  # ARCHER's paths (data/archer.db) are relative to the project root
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

import numpy as np  # noqa: E402

from archer.memory.sqlite_store import get_sqlite_store  # noqa: E402

PER_CAMERA = 30  # most recent sightings averaged into each camera's reference


def _templates_by_camera(store, person_id: str) -> dict:
    """{camera_source: (embedding_bytes, n_used)} from this face's latest
    unrecognized sightings, one averaged reference per camera."""
    groups: dict = {}
    for s in store.get_person_sightings(limit=5000):  # newest first
        if s.get("person_id") != person_id or s.get("is_known") or not s.get("embedding"):
            continue
        src = s.get("camera_source") or "unknown"
        bucket = groups.setdefault(src, [])
        if len(bucket) < PER_CAMERA:
            e = np.frombuffer(s["embedding"], dtype=np.float32)
            n = np.linalg.norm(e)
            if n > 0:
                bucket.append(e / n)
    out = {}
    for src, embs in groups.items():
        mean = np.mean(embs, axis=0)
        mean = mean / np.linalg.norm(mean)
        out[src] = (mean.astype(np.float32).tobytes(), len(embs))
    return out


def main() -> None:
    store = get_sqlite_store()

    if len(sys.argv) < 3:
        pending = store.get_pending_person_confirmations(status="pending", limit=50)
        if not pending:
            print("No unrecognized faces waiting on a name.")
            return
        print("Unrecognized faces waiting on a name (most recently seen first):")
        for row in pending:
            print(
                f"  {row['person_id']:<12} seen {row['sighting_count']}x, "
                f"last {row['last_seen_at']}   snapshot: {row.get('snapshot_path') or '-'}"
            )
        print("\nName one with:  .venv\\Scripts\\python.exe scripts\\name_person.py Person_N Name")
        return

    person_id, name = sys.argv[1], " ".join(sys.argv[2:]).strip()
    templates = _templates_by_camera(store, person_id)

    if not templates:
        rows = store.get_pending_person_confirmations(status="pending", limit=500)
        row = next((r for r in rows if r["person_id"] == person_id), None)
        if row is None or not row.get("embedding"):
            sys.exit(f"No stored face data for {person_id}. Run with no arguments to see who's waiting on a name.")
        templates = {"waiting-list entry": (row["embedding"], 1)}

    for src, (emb, used) in templates.items():
        how = store.add_person_face(name=name, embedding=emb, source=f"{person_id}/{src}")
        verb = "enrolled as" if how == "enrolled" else "added as an extra reference for"
        print(f"  {src}: average of {used} sighting(s) -- {verb} '{name}'")

    store.resolve_pending_person_confirmation_by_person_id(person_id, status="confirmed", confirmed_name=name)
    print(f"Done: ARCHER will recognize {person_id} as '{name}' from its next sighting -- no restart needed.")


if __name__ == "__main__":
    main()
