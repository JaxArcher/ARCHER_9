"""
Inspection / wipe script for OpenMemory.
Run from the ARCHER_9 root with the venv active, and with ARCHER closed
so nothing else is holding the DB file open:
    .\.venv\Scripts\python.exe scripts\dump_openmemory.py
    .\.venv\Scripts\python.exe scripts\dump_openmemory.py "search query here"
    .\.venv\Scripts\python.exe scripts\dump_openmemory.py --wipe

With no argument, dumps everything stored (Memory.history()).
With a query argument, runs a semantic search for that query instead.
With --wipe, deletes ALL memories for archer_user after a y/n confirmation.
"""
import os
import sys
import asyncio

os.environ["OM_DB_URL"] = "sqlite:///data/openmemory.db"

from openmemory import Memory  # noqa: E402

mem = Memory(user="archer_user")

if len(sys.argv) > 1 and sys.argv[1] == "--wipe":
    rows = mem.history(user_id="archer_user", limit=1000, offset=0)
    print(f"About to permanently delete {len(rows)} memories for archer_user.")
    confirm = input("Type 'yes' to proceed: ").strip().lower()
    if confirm == "yes":
        asyncio.run(mem.delete_all(user_id="archer_user"))
        print("OpenMemory wiped.")
    else:
        print("Aborted — nothing deleted.")
elif len(sys.argv) > 1:
    query = " ".join(sys.argv[1:])
    print(f"Searching OpenMemory for: {query!r}\n")
    results = asyncio.run(mem.search(query=query, limit=10))
    if not results:
        print("No matches.")
    for r in results:
        print(f"[score={r.get('score')}] {r.get('content')}")
        print(f"  meta: {r.get('meta')}")
        print()
else:
    print("Dumping all stored memories (Memory.history())\n")
    rows = mem.history(user_id="archer_user", limit=200, offset=0)
    if not rows:
        print("Nothing stored — OpenMemory is empty.")
    for row in rows:
        print(f"id={row.get('id')} | {row.get('content')}")
        print(f"  meta: {row.get('meta')}")
        print()
    print(f"\nTotal: {len(rows)} memories shown (limit=200)")
