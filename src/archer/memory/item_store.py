"""
ARCHER Phase 2d: things that get moved (Claude, 2026-10-20).

Where each item was last seen, who moved it, and the history of its moves.
Shared through archer.db by the observer service, which records moves, and
ARCHER, which answers "where's my wallet?" and learns the items Col shows it.

Uses the inventory tables that already exist (inventory_items,
storage_locations, item_location_history), adding the columns this needs.
item_location_history is the change log the spec asks for: one row per move.

Places are spots in the room camera's picture (640x480 coordinates). Until Col
names a spot, it carries the vision model's own description of it ("arm of
the couch").
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Kinds of item, as ARCHER says them. A name containing one of these phrases
# is that kind ("black leather wallet" -> wallet). Checked longest first.
_KIND_SYNONYMS = {
    "phone": ("cell phone", "cellphone", "mobile phone", "smartphone", "smart phone", "iphone", "android phone", "phone"),
    "remote": ("tv remote", "remote control", "television remote", "remote"),
    "wallet": ("wallet", "billfold"),
    "keys": ("set of keys", "car keys", "house keys", "keychain", "key ring", "keys", "key"),
    "glasses": ("eyeglasses", "reading glasses", "glasses", "spectacles"),
    "sunglasses": ("sunglasses",),
    "mug": ("coffee mug", "mug"),
    "cup": ("cup",),
    "bottle": ("water bottle", "bottle"),
    "headphones": ("headphones", "headset", "earbuds", "airpods"),
    "watch": ("wristwatch", "watch"),
    "book": ("book", "notebook"),
    "laptop": ("laptop",),
    "tablet": ("tablet", "ipad"),
    "controller": ("game controller", "controller", "gamepad"),
    "charger": ("charger", "charging cable"),
    "bag": ("backpack", "handbag", "purse", "bag"),
}
_SYNONYM_PAIRS = sorted(
    ((phrase, kind) for kind, phrases in _KIND_SYNONYMS.items() for phrase in phrases),
    key=lambda pair: -len(pair[0]),
)
_FILLER_WORDS = {"a", "an", "the", "my", "your", "his", "her", "their", "some", "small", "little", "of"}

ITEM_PHOTOS_DIR = Path("data") / "items"
COL = "Col"
# The kind of an item ARCHER couldn't name yet (asked about later).
UNNAMED = "unnamed item"


def normalize_kind(name: str | None) -> str | None:
    """The kind of item a name describes ("TV remote" -> "remote"), or None for no item."""
    if (name or "").strip().lower() == UNNAMED:
        return UNNAMED
    clean = re.sub(r"[^a-z0-9+' ]", " ", (name or "").lower())
    clean = " ".join(w for w in clean.split() if w not in _FILLER_WORDS)
    if not clean or clean in {"none", "null", "nothing", "no item", "unclear", "unknown"}:
        return None
    padded = f" {clean} "
    for phrase, kind in _SYNONYM_PAIRS:
        if f" {phrase} " in padded:
            return kind
    return clean.split()[-1]  # the head noun: "red lighter" -> "lighter"


def _box_overlap(a: list[float], b: list[float]) -> float:
    """Share of the smaller box covered by the other ([x, y, w, h])."""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    smaller = max(1e-6, min(a[2] * a[3], b[2] * b[3]))
    return (iw * ih) / smaller


def _center_inside(a: list[float], b: list[float], margin: float = 0.0) -> bool:
    cx, cy = a[0] + a[2] / 2, a[1] + a[3] / 2
    return (b[0] - margin) <= cx <= (b[0] + b[2] + margin) and (b[1] - margin) <= cy <= (b[1] + b[3] + margin)


def when_text(ts: float, now: float | None = None) -> str:
    """'at 5:57 PM', 'yesterday at 5:57 PM', or 'on Tue Oct 14 at 3:42 PM'."""
    moment = datetime.fromtimestamp(ts)
    today = datetime.fromtimestamp(now if now is not None else time.time()).date()
    clock = moment.strftime("%I:%M %p").lstrip("0")
    days = (today - moment.date()).days
    if days == 0:
        return f"at {clock}"
    if days == 1:
        return f"yesterday at {clock}"
    return f"on {moment.strftime('%a %b')} {moment.day} at {clock}"


class ItemStore:
    """Items, places and moves in archer.db (see the module docstring)."""

    _COLUMNS = (
        ("inventory_items", "kind", "TEXT"),
        ("inventory_items", "owner", "TEXT"),
        ("inventory_items", "description", "TEXT"),
        ("inventory_items", "reference_image_path", "TEXT"),
        ("inventory_items", "last_seen_image_path", "TEXT"),
        ("inventory_items", "last_seen_box", "TEXT"),
        ("inventory_items", "last_seen_ts", "REAL"),
        ("inventory_items", "status", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("inventory_items", "carried_by", "TEXT"),
        ("inventory_items", "carried_stay_id", "TEXT"),
        ("inventory_items", "last_moved_by", "TEXT"),
        ("inventory_items", "taught_at", "REAL"),
        ("storage_locations", "named_by", "TEXT"),
        ("storage_locations", "camera", "TEXT"),
        ("item_location_history", "event", "TEXT"),
        ("item_location_history", "moved_by", "TEXT"),
        ("item_location_history", "stay_id", "TEXT"),
        ("item_location_history", "ts", "REAL"),
        ("item_location_history", "image_path", "TEXT"),
        ("item_location_history", "from_location_id", "INTEGER"),
        ("item_location_history", "told_col", "REAL"),
    )

    def __init__(self, db_path: str | None = None, photos_dir: Path | str | None = None) -> None:
        if db_path is None:
            from archer.config import get_config

            db_path = get_config().sqlite_db_path
        self._db_path = str(db_path)
        # Beside the database (data/items for data/archer.db), so tests' temporary
        # databases never put photos in the real folder.
        self.photos_dir = Path(photos_dir) if photos_dir is not None else Path(self._db_path).parent / ITEM_PHOTOS_DIR.name
        self._lock = threading.Lock()
        self._init()

    # --- Set-up ----------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                # The tables normally exist already (SQLiteStore creates them);
                # created here too so this works on its own (tests, a fresh PC).
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS storage_locations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        location_name TEXT NOT NULL,
                        room TEXT,
                        furniture_type TEXT,
                        level INTEGER,
                        is_visible BOOLEAN DEFAULT 1,
                        parent_location_id INTEGER,
                        coordinates TEXT,
                        FOREIGN KEY (parent_location_id) REFERENCES storage_locations(id)
                    );
                    CREATE TABLE IF NOT EXISTS inventory_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_name TEXT NOT NULL,
                        category TEXT,
                        brand TEXT,
                        model TEXT,
                        serial_number TEXT,
                        barcode TEXT,
                        estimated_value REAL,
                        is_consumable BOOLEAN DEFAULT 0,
                        persistent_object_id TEXT UNIQUE,
                        notes TEXT,
                        current_location_id INTEGER,
                        last_seen_at TIMESTAMP,
                        image_path TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (current_location_id) REFERENCES storage_locations(id)
                    );
                    CREATE TABLE IF NOT EXISTS item_location_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_id INTEGER NOT NULL,
                        location_id INTEGER NOT NULL,
                        confidence REAL,
                        still_there BOOLEAN DEFAULT 1,
                        placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        removed_at TIMESTAMP,
                        FOREIGN KEY (item_id) REFERENCES inventory_items(id),
                        FOREIGN KEY (location_id) REFERENCES storage_locations(id)
                    );
                """)
                for table, column, decl in self._COLUMNS:
                    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                    if column not in existing:
                        try:
                            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                        except sqlite3.OperationalError as e:
                            # The observer service and ARCHER both set this up; the
                            # other one may have just added it.
                            if "duplicate column" not in str(e).lower():
                                raise
                conn.commit()
            finally:
                conn.close()

    # --- Places -------------------------------------------------------------------

    def place_for(self, conn: sqlite3.Connection, box: list[float], spot: str | None) -> tuple[int, str]:
        """The named spot this box is in, creating one if needed: (location id, name)."""
        best = None
        for row in conn.execute("SELECT id, location_name, coordinates FROM storage_locations WHERE camera = 'room'"):
            try:
                place_box = json.loads(row["coordinates"] or "null")
            except ValueError:
                place_box = None
            if not place_box:
                continue
            score = _box_overlap(box, place_box)
            if score >= 0.3 or _center_inside(box, place_box):
                if best is None or score > best[0]:
                    best = (score, row["id"], row["location_name"])
        if best is not None:
            return best[1], best[2]
        name = " ".join((spot or "").split()).strip(" .") or "a spot in the room"
        # A new spot is a little bigger than the item, so the next thing put
        # down beside it lands in the same place.
        pad_w, pad_h = max(24.0, box[2]), max(24.0, box[3])
        place_box = [max(0.0, box[0] - pad_w), max(0.0, box[1] - pad_h), box[2] + 2 * pad_w, box[3] + 2 * pad_h]
        cur = conn.execute(
            "INSERT INTO storage_locations (location_name, room, coordinates, named_by, camera) "
            "VALUES (?, 'living room', ?, 'archer', 'room')",
            (name, json.dumps([round(v, 1) for v in place_box])),
        )
        return cur.lastrowid, name

    # --- Items ----------------------------------------------------------------------

    def teach(self, kind: str, owner: str | None, description: str | None,
              reference_image_path: str | None = None, name: str | None = None) -> int:
        """Col showed ARCHER an item ("this is my wallet"): add it, or update the one he already has."""
        kind = normalize_kind(kind) or kind
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT id FROM inventory_items WHERE kind = ? AND owner IS ? ORDER BY taught_at IS NULL, id LIMIT 1",
                    (kind, owner),
                ).fetchone()
                if row is None and owner is not None:
                    # An item of this kind seen before anyone said whose it was.
                    row = conn.execute(
                        "SELECT id FROM inventory_items WHERE kind = ? AND owner IS NULL ORDER BY last_seen_ts DESC LIMIT 1",
                        (kind,),
                    ).fetchone()
                display = name or kind
                if row is None:
                    cur = conn.execute(
                        "INSERT INTO inventory_items (item_name, category, kind, owner, description, "
                        "reference_image_path, taught_at, status) VALUES (?, 'tracked', ?, ?, ?, ?, ?, 'unknown')",
                        (display, kind, owner, description, reference_image_path, time.time()),
                    )
                    item_id = cur.lastrowid
                else:
                    item_id = row["id"]
                    conn.execute(
                        "UPDATE inventory_items SET item_name = ?, owner = ?, description = COALESCE(?, description), "
                        "reference_image_path = COALESCE(?, reference_image_path), taught_at = ? WHERE id = ?",
                        (display, owner, description, reference_image_path, time.time(), item_id),
                    )
                conn.commit()
                return item_id
            finally:
                conn.close()

    def _item_dict(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["place"] = None
        if item.get("current_location_id"):
            place = conn.execute(
                "SELECT location_name FROM storage_locations WHERE id = ?", (item["current_location_id"],)
            ).fetchone()
            item["place"] = place["location_name"] if place else None
        return item

    def find(self, query: str) -> list[dict[str, Any]]:
        """Items matching what Col asked about ("my wallet", "the remote"), most recently seen first."""
        kind = normalize_kind(query)
        if not kind:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM inventory_items WHERE kind = ? OR lower(item_name) = ? "
                "ORDER BY (owner = 'Col') DESC, last_seen_ts IS NULL, last_seen_ts DESC",
                (kind, kind),
            ).fetchall()
            return [self._item_dict(conn, r) for r in rows]
        finally:
            conn.close()

    def get(self, item_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
            return self._item_dict(conn, row) if row else None
        finally:
            conn.close()

    def history(self, item_id: int, limit: int = 10) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT h.*, l.location_name FROM item_location_history h "
                "LEFT JOIN storage_locations l ON l.id = h.location_id "
                "WHERE h.item_id = ? ORDER BY h.ts DESC, h.id DESC LIMIT ?",
                (item_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _match_put_down(self, conn: sqlite3.Connection, kind: str, box: list[float], stay_id: str | None):
        """Which known item this is, if any (see record_put_down)."""
        if stay_id:
            row = conn.execute(
                "SELECT * FROM inventory_items WHERE kind = ? AND status = 'carried' AND carried_stay_id = ? "
                "ORDER BY last_seen_ts DESC LIMIT 1", (kind, stay_id),
            ).fetchone()
            if row:
                return row
        same_kind = conn.execute(
            "SELECT * FROM inventory_items WHERE kind = ? ORDER BY last_seen_ts DESC", (kind,)
        ).fetchall()
        for row in same_kind:  # re-seen where it already was
            try:
                seen = json.loads(row["last_seen_box"] or "null")
            except ValueError:
                seen = None
            if row["status"] == "placed" and seen and (_box_overlap(box, seen) >= 0.3 or _center_inside(box, seen, 8)):
                return row
        if kind == UNNAMED:
            return None  # two things ARCHER couldn't name aren't the same thing
        owned = [r for r in same_kind if r["owner"] == COL]
        if len(owned) == 1:
            return owned[0]
        if len(same_kind) == 1:
            return same_kind[0]
        return None

    def record_put_down(self, kind: str, box: list[float], spot: str | None, moved_by: str | None,
                        stay_id: str | None, ts: float, description: str | None = None) -> dict[str, Any]:
        """
        Something of this kind was put down at `box` (640x480 room-camera
        coordinates). Matched to a known item: one the same person was
        carrying, one already seen right there, Col's only item of that kind,
        or the only item of that kind. Otherwise it's a new item.
        Returns the item, with "place" and "new".
        """
        kind = normalize_kind(kind) or kind
        with self._lock:
            conn = self._connect()
            try:
                row = self._match_put_down(conn, kind, box, stay_id)
                location_id, place = self.place_for(conn, box, spot)
                box_json = json.dumps([round(v, 1) for v in box])
                is_new = row is None
                if is_new:
                    cur = conn.execute(
                        "INSERT INTO inventory_items (item_name, category, kind, description, status, "
                        "current_location_id, last_seen_box, last_seen_ts, last_seen_at, last_moved_by) "
                        "VALUES (?, 'tracked', ?, ?, 'placed', ?, ?, ?, ?, ?)",
                        (kind, kind, description, location_id, box_json, ts,
                         datetime.fromtimestamp(ts).isoformat(), moved_by),
                    )
                    item_id = cur.lastrowid
                else:
                    item_id = row["id"]
                    same_spot = row["status"] == "placed" and row["current_location_id"] == location_id
                    conn.execute(
                        "UPDATE inventory_items SET status = 'placed', current_location_id = ?, last_seen_box = ?, "
                        "last_seen_ts = ?, last_seen_at = ?, carried_by = NULL, carried_stay_id = NULL, "
                        "last_moved_by = CASE WHEN ? THEN last_moved_by ELSE ? END, "
                        "description = COALESCE(description, ?) WHERE id = ?",
                        (location_id, box_json, ts, datetime.fromtimestamp(ts).isoformat(),
                         1 if same_spot else 0, moved_by, description, item_id),
                    )
                    if same_spot:
                        conn.commit()
                        item = self._item_dict(conn, conn.execute(
                            "SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone())
                        item["new"] = False
                        item["moved"] = False
                        return item
                conn.execute(
                    "UPDATE item_location_history SET still_there = 0, removed_at = ? WHERE item_id = ? AND still_there = 1",
                    (datetime.fromtimestamp(ts).isoformat(), item_id),
                )
                came_from = None if is_new else row["current_location_id"]
                conn.execute(
                    "INSERT INTO item_location_history (item_id, location_id, still_there, placed_at, event, moved_by, "
                    "stay_id, ts, from_location_id, told_col) VALUES (?, ?, 1, ?, 'put_down', ?, ?, ?, ?, ?)",
                    (item_id, location_id, datetime.fromtimestamp(ts).isoformat(), moved_by, stay_id, ts,
                     came_from, ts if moved_by == COL else None),
                )
                conn.commit()
                item = self._item_dict(conn, conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone())
                item["new"] = is_new
                item["moved"] = True
                return item
            finally:
                conn.close()

    def record_picked_up(self, box: list[float], moved_by: str | None, stay_id: str | None,
                         ts: float) -> list[dict[str, Any]]:
        """Something was taken from `box`: the items last seen there are now with that person."""
        with self._lock:
            conn = self._connect()
            try:
                taken = []
                for row in conn.execute("SELECT * FROM inventory_items WHERE status = 'placed'").fetchall():
                    try:
                        seen = json.loads(row["last_seen_box"] or "null")
                    except ValueError:
                        continue
                    if seen and (_box_overlap(box, seen) >= 0.3 or _center_inside(seen, box, 8)):
                        taken.append(row)
                for row in taken:
                    conn.execute(
                        "UPDATE inventory_items SET status = 'carried', carried_by = ?, carried_stay_id = ?, "
                        "last_seen_ts = ?, last_moved_by = ? WHERE id = ?",
                        (moved_by, stay_id, ts, moved_by, row["id"]),
                    )
                    conn.execute(
                        "UPDATE item_location_history SET still_there = 0, removed_at = ? WHERE item_id = ? AND still_there = 1",
                        (datetime.fromtimestamp(ts).isoformat(), row["id"]),
                    )
                    conn.execute(
                        "INSERT INTO item_location_history (item_id, location_id, still_there, placed_at, event, "
                        "moved_by, stay_id, ts, told_col) VALUES (?, ?, 0, ?, 'picked_up', ?, ?, ?, ?)",
                        (row["id"], row["current_location_id"], datetime.fromtimestamp(ts).isoformat(),
                         moved_by, stay_id, ts, ts if moved_by == COL else None),
                    )
                conn.commit()
                return [self._item_dict(conn, conn.execute("SELECT * FROM inventory_items WHERE id = ?", (r["id"],)).fetchone())
                        for r in taken]
            finally:
                conn.close()

    def taught_items(self) -> list[dict[str, Any]]:
        """Items Col showed ARCHER, with their descriptions."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, kind, description FROM inventory_items WHERE taught_at IS NOT NULL ORDER BY taught_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def placed_items(self) -> list[dict[str, Any]]:
        """Items last seen put down somewhere, with where (for the room watcher)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, kind, last_seen_box FROM inventory_items WHERE status = 'placed' AND last_seen_box IS NOT NULL"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def carrying_stays(self) -> list[str]:
        """Stays (people in the room) last seen picking something up."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT carried_stay_id FROM inventory_items WHERE status = 'carried' AND carried_stay_id IS NOT NULL"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def carried_by_stay(self, stay_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM inventory_items WHERE status = 'carried' AND carried_stay_id = ?", (stay_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def record_left_with(self, stay_id: str, moved_by: str | None, ts: float,
                         image_path: str | None) -> list[dict[str, Any]]:
        """The person carrying these items left the room: keep the photo of them leaving."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM inventory_items WHERE status = 'carried' AND carried_stay_id = ?", (stay_id,)
                ).fetchall()
                for row in rows:
                    conn.execute(
                        "UPDATE inventory_items SET status = 'left', last_seen_ts = ?, image_path = ? WHERE id = ?",
                        (ts, image_path, row["id"]),
                    )
                    conn.execute(
                        "INSERT INTO item_location_history (item_id, location_id, still_there, placed_at, event, "
                        "moved_by, stay_id, ts, image_path, told_col) VALUES (?, ?, 0, ?, 'left_with', ?, ?, ?, ?, ?)",
                        (row["id"], row["current_location_id"], datetime.fromtimestamp(ts).isoformat(),
                         moved_by, stay_id, ts, image_path, ts if moved_by == COL else None),
                    )
                conn.commit()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # --- Telling Col, naming, forgetting --------------------------------------------

    def untold_moves(self, limit: int = 20) -> list[dict[str, Any]]:
        """Moves by anyone but Col that ARCHER hasn't mentioned yet, oldest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT h.*, i.kind, i.item_name, i.owner, l.location_name AS place, f.location_name AS from_place "
                "FROM item_location_history h JOIN inventory_items i ON i.id = h.item_id "
                "LEFT JOIN storage_locations l ON l.id = h.location_id "
                "LEFT JOIN storage_locations f ON f.id = h.from_location_id "
                "WHERE h.told_col IS NULL AND h.event IS NOT NULL ORDER BY h.ts LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_told(self, history_ids: list[int]) -> None:
        if not history_ids:
            return
        with self._lock:
            conn = self._connect()
            try:
                marks = ",".join("?" * len(history_ids))
                conn.execute(f"UPDATE item_location_history SET told_col = ? WHERE id IN ({marks})",
                             [time.time(), *history_ids])
                conn.commit()
            finally:
                conn.close()

    def record_unnamed(self, box: list[float], spot: str | None, moved_by: str | None, stay_id: str | None,
                       ts: float, description: str | None = None) -> dict[str, Any]:
        """Something ARCHER couldn't name was put down: kept as an unnamed item to ask Col about."""
        item = self.record_put_down(UNNAMED, box, spot, moved_by, stay_id, ts, description=description)
        return item

    def unnamed_items(self) -> list[dict[str, Any]]:
        """Items waiting for Col to say what they are, oldest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM inventory_items WHERE kind = ? ORDER BY last_seen_ts", (UNNAMED,)
            ).fetchall()
            return [self._item_dict(conn, r) for r in rows]
        finally:
            conn.close()

    def name_item(self, item_id: int, name: str, owner: str | None = None) -> dict[str, Any] | None:
        """Col said what an item is. Its 'unnamed' photo is no longer needed (spec 5d, privacy)."""
        kind = normalize_kind(name) or name
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE inventory_items SET kind = ?, item_name = ?, owner = COALESCE(?, owner) WHERE id = ?",
                    (kind, kind, owner, item_id),
                )
                conn.commit()
            finally:
                conn.close()
        self._delete_photo(item_id, "unnamed")
        return self.get(item_id)

    def rename_place(self, location_id: int, name: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("UPDATE storage_locations SET location_name = ?, named_by = 'Col' WHERE id = ?",
                             (" ".join(name.split()), location_id))
                conn.commit()
            finally:
                conn.close()

    def forget(self, item_id: int) -> bool:
        """Remove an item, its moves and its photos (Col can delete any of them, spec 5d)."""
        with self._lock:
            conn = self._connect()
            try:
                photos = [r["image_path"] for r in conn.execute(
                    "SELECT image_path FROM item_location_history WHERE item_id = ? AND image_path IS NOT NULL",
                    (item_id,))]
                conn.execute("DELETE FROM item_location_history WHERE item_id = ?", (item_id,))
                gone = conn.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,)).rowcount
                conn.commit()
            finally:
                conn.close()
        for what in ("last_seen", "reference", "leaving", "unnamed"):
            self._delete_photo(item_id, what)
        for path in photos:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        return bool(gone)

    def _delete_photo(self, item_id: int, what: str) -> None:
        try:
            (self.photos_dir / f"item_{item_id}_{what}.jpg").unlink(missing_ok=True)
        except OSError:
            pass

    def set_last_seen_photo(self, item_id: int, path: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("UPDATE inventory_items SET last_seen_image_path = ? WHERE id = ?", (path, item_id))
                conn.commit()
            finally:
                conn.close()

    def photo_path(self, item_id: int, what: str) -> Path:
        """Where an item's photo goes: what is 'last_seen', 'reference' or 'leaving'. Replaced each time."""
        self.photos_dir.mkdir(parents=True, exist_ok=True)
        return self.photos_dir / f"item_{item_id}_{what}.jpg"


def mover_text(moved_by: str | None) -> str:
    """'You', 'Sarah', or 'someone I don't know yet'."""
    if not moved_by or moved_by.startswith("Person_"):
        return "someone I don't know yet"
    return "you" if moved_by == COL else moved_by


def _on_place(place: str) -> str:
    """'on the arm of the couch', 'at a spot by the door'."""
    place = place.strip()
    if place.lower().startswith(("on ", "in ", "at ", "by ", "under ", "next to ", "beside ", "near ")):
        return place
    if place.lower().startswith(("a ", "an ", "the ")):
        return f"on {place}"
    return f"on the {place}"


def describe_where(item: dict[str, Any], now: float | None = None) -> str:
    """ARCHER's answer to "where's my X?" for one item. Never makes up a place."""
    kind = item.get("kind") or item.get("item_name") or "that"
    noun = ("your " if item.get("owner") == COL else "the ") + kind
    status = item.get("status")
    ts = item.get("last_seen_ts")
    who = mover_text(item.get("last_moved_by"))
    if not ts:
        return f"I haven't seen {noun} yet."
    when = when_text(ts, now)
    if status == "placed" and item.get("place"):
        if who == "someone I don't know yet" and not item.get("last_moved_by"):
            return f"{noun[0].upper() + noun[1:]} is {_on_place(item['place'])}. I saw it there {when}."
        subject = "You" if who == "you" else who[0].upper() + who[1:]
        return f"{noun[0].upper() + noun[1:]} is {_on_place(item['place'])}. {subject} put it there {when}."
    if status == "carried":
        return f"The last I saw, {who} picked up {noun} {when}. I didn't see where it went after that."
    if status == "left":
        return f"The last I saw, {who} left the room with {noun} {when}."
    return f"I haven't seen where {noun} is."


def describe_move(move: dict[str, Any], now: float | None = None) -> str:
    """One move by someone else, for telling Col: 'Sarah moved your keys from the hanger to the counter at 3:12 PM.'"""
    who = mover_text(move.get("moved_by"))
    who = who[0].upper() + who[1:]
    kind = move.get("kind") or move.get("item_name") or "something"
    noun = ("your " if move.get("owner") == COL else "the ") + kind
    when = when_text(move.get("ts") or time.time(), now)
    event = move.get("event")
    if event == "put_down":
        if move.get("from_place"):
            return f"{who} moved {noun} from {_bare(move['from_place'])} to {_bare(move.get('place') or 'another spot')} {when}."
        return f"{who} put {noun} {_on_place(move.get('place') or 'a spot in the room')} {when}."
    if event == "picked_up":
        where = f" from {_bare(move['place'])}" if move.get("place") else ""
        return f"{who} picked up {noun}{where} {when}."
    if event == "left_with":
        return f"{who} left the room with {noun} {when}."
    return f"{who} moved {noun} {when}."


def _bare(place: str) -> str:
    """'the arm of the couch' for 'arm of the couch'."""
    place = place.strip()
    return place if place.lower().startswith(("a ", "an ", "the ")) else f"the {place}"
