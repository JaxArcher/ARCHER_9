import sqlite3
import os

db_path = 'data/archer.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print("\n".join(tables))
    conn.close()
else:
    print(f"File {db_path} not found")
