"""
Pytest configuration and Windows DLL initialization.
Pre-loads torch and onnxruntime before PyQt6 test fixtures are imported.
Ensures strict test isolation so tests NEVER write to production databases.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch
import pytest

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# Point default database paths to an isolated temp directory during tests
_TEST_TEMP_DIR = tempfile.mkdtemp(prefix="archer_test_db_")
os.environ["OM_DB_URL"] = f"sqlite:///{os.path.join(_TEST_TEMP_DIR, 'test_openmemory.db')}"
os.environ["ARCHER_DB_PATH"] = os.path.join(_TEST_TEMP_DIR, "test_archer.db")
os.environ["ARCHER_SQLITE_DB"] = os.path.join(_TEST_TEMP_DIR, "test_archer.db")
os.environ["ARCHER_OPENMEMORY_DB"] = os.path.join(_TEST_TEMP_DIR, "test_openmemory.db")

try:
    import torch
    import onnxruntime
except ImportError:
    pass


OPENMEMORY_DB_FILES = [
    "openmemory.db",
    "data/openmemory.db",
]

ARCHER_REAL_DB = "data/archer.db"


def _file_hash(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _get_archer_db_state(path: str) -> dict | None:
    """Snapshot the record counts of all user/person/memory tables in real archer.db."""
    if not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(path, timeout=5.0)
        cur = con.cursor()
        tables = [
            "known_persons",
            "social_contacts",
            "social_interactions",
            "conversation_logs",
        ]
        counts = {}
        for t in tables:
            try:
                cur.execute(f"SELECT count(*) FROM {t}")
                counts[t] = cur.fetchone()[0]
            except sqlite3.OperationalError:
                pass
        # Check confirmed pending confirmations
        try:
            cur.execute("SELECT count(*) FROM pending_person_confirmations WHERE status != 'pending'")
            counts["confirmed_pending"] = cur.fetchone()[0]
        except sqlite3.OperationalError:
            pass
        con.close()
        return counts
    except Exception:
        return None


@pytest.fixture(autouse=True)
def guard_real_databases(tmp_path):
    """
    Autouse fixture that runs for EVERY test.
    Ensures strict isolation so tests are completely blocked from opening
    real databases or data folders (Review 2026-10-13 Item 13).
    """
    import builtins
    from archer.memory.sqlite_store import SQLiteStore
    from archer.observer.person_id import PersonIdentifier

    test_db_path = str(tmp_path / "conftest_isolated_archer.db")
    isolated_sqlite = SQLiteStore(db_path=test_db_path)
    
    mock_om = MagicMock()
    mock_om.add_memory.return_value = "mock-test-mem-id"
    mock_om.query_memories.return_value = []
    mock_om.get_recent_memories.return_value = []

    test_snapshots_dir = tmp_path / "test_snapshots"
    test_snapshots_dir.mkdir(parents=True, exist_ok=True)

    # 1. Intercept SQLiteStore.__init__ default
    orig_sqlite_init = SQLiteStore.__init__
    def safe_sqlite_init(self, db_path=None, *args, **kwargs):
        if db_path is None or db_path == "data/archer.db" or os.path.abspath(str(db_path)) == os.path.abspath("data/archer.db"):
            db_path = test_db_path
        orig_sqlite_init(self, db_path=db_path, *args, **kwargs)

    # 2. Block sqlite3.connect on production database files
    real_sqlite_connect = sqlite3.connect
    def blocked_sqlite_connect(database, *args, **kwargs):
        if isinstance(database, (str, bytes, os.PathLike)):
            p = os.path.abspath(os.fspath(database))
            real_data_dir = os.path.abspath("data")
            real_om = os.path.abspath("openmemory.db")
            if p == real_om or p.startswith(real_data_dir):
                raise PermissionError(
                    f"CRITICAL TEST ISOLATION FAILURE: Tests are strictly blocked from opening production database: {database}"
                )
        return real_sqlite_connect(database, *args, **kwargs)

    # 3. Block file writes into data/ or openmemory.db
    real_builtin_open = builtins.open
    def safe_builtin_open(file, mode="r", *args, **kwargs):
        if any(m in mode for m in ("w", "a", "x", "+")):
            if isinstance(file, (str, bytes, os.PathLike)):
                p = os.path.abspath(os.fspath(file))
                real_data_dir = os.path.abspath("data")
                real_om = os.path.abspath("openmemory.db")
                if p == real_om or p.startswith(real_data_dir):
                    raise PermissionError(
                        f"CRITICAL TEST ISOLATION FAILURE: Tests are strictly blocked from writing to production data folder: {file}"
                    )
        return real_builtin_open(file, mode, *args, **kwargs)

    # 4. Safe PersonIdentifier init with isolated snapshots dir
    orig_person_id_init = PersonIdentifier.__init__
    def safe_person_id_init(self, *args, **kwargs):
        if "snapshots_dir" not in kwargs or kwargs["snapshots_dir"] == "data/snapshots":
            kwargs["snapshots_dir"] = test_snapshots_dir
        orig_person_id_init(self, *args, **kwargs)

    with patch("archer.memory.sqlite_store.get_sqlite_store", return_value=isolated_sqlite), \
         patch("archer.agents.core_agent.get_sqlite_store", return_value=isolated_sqlite), \
         patch("archer.memory.openmemory_store.get_openmemory_store", return_value=mock_om), \
         patch("archer.agents.core_agent.get_openmemory_store", return_value=mock_om), \
         patch.object(SQLiteStore, "__init__", safe_sqlite_init), \
         patch.object(PersonIdentifier, "__init__", safe_person_id_init), \
         patch("sqlite3.connect", blocked_sqlite_connect), \
         patch("builtins.open", safe_builtin_open):
        yield


