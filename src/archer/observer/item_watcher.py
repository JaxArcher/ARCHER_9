"""
ARCHER Phase 2d: noticing things that get moved (Claude, 2026-10-20).

Runs in the observer service, beside the people tracker, on the room camera's
640x480 stream (2 frames a second).

- **A picture of the room without people.** Updated slowly everywhere no one
  is standing, so lighting drifts in, and the spot under a person keeps how
  it looked before they got there.
- **Key moments.** A small patch that differs from that picture, near where
  someone just was, and stays that way for a few seconds once they've moved
  away: something was put down or picked up there. Changes nobody was near,
  and big changes (lights, the camera switching to night mode), don't count.
- **A closer look.** Only then is a sharp still taken from the camera's main
  stream (2560x1920). ARCHER's vision model is shown the spot with a red box
  around it and asked what's there and what it's sitting on.
- **Picked up / carried out.** A change where a known item was last seen is
  checked for that item. If it's gone, the person who was there has it, and
  if they then leave through a door, a still of them leaving is kept.

Frames stay in memory. The only stills kept are those spec 5d lists (an
item's last-seen photo, someone leaving with an item, an item ARCHER couldn't
name), in data/items/. Model calls happen on a worker thread, never in the
tracker's loop. Audit and design: spec 5d.
"""

from __future__ import annotations

import collections
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import cv2
import numpy as np
from loguru import logger

from archer.memory.item_store import COL, ItemStore, normalize_kind

FRAME_W, FRAME_H = 640, 480

# Background picture: how fast it follows the room where no one is (per
# frame, at 2 frames a second: about 15 s to settle).
BG_RATE = 0.03
# A pixel differs when the blurred grey level is this far from the background.
DIFF_LEVEL = 28
# A patch is item-sized: a phone on the couch arm was about 40x16 here.
MIN_AREA = 60
MAX_AREA = 5000
MAX_SIDE = 140
MIN_FILL = 0.2
# More changed patches than this in one frame is noise, not an item.
MAX_PATCHES = 40
# More than this share of the picture changed: lights or night mode; start over.
GLOBAL_CHANGE = 0.20
# Around each person's box, the area they can reach. Generous: the detector's
# box often misses feet, a hand or a head on a pillow (2026-10-20 live run:
# "the feet on the pillow", "the glasses on the pillow").
REACH_PX = 40
REACH_SHARE = 0.20
# Someone must have been at the spot within this long...
PERSON_WINDOW = 90.0
# ...and away from it for this long, with the change steady for this long.
CLEAR_SECONDS = 4.0
STEADY_SECONDS = 3.0
STEADY_FRAMES = 5
# A spot just looked at isn't looked at again for this long.
HANDLED_COOLDOWN = 20.0
NOTHING_COOLDOWN = 600.0
# Model calls: at most one this often; at most this many waiting.
MIN_ASK_INTERVAL = 2.0
QUEUE_SIZE = 8
# Someone carrying an item, at a door: a still of them at most this often.
LEAVING_STILL_INTERVAL = 4.0
LEAVING_PHOTO_MAX_AGE = 30.0
# A picked-up item is looked at again this long later before it counts (a
# person passing in front of it isn't a pick-up).
RECHECK_SECONDS = 4.0
# Kinds that aren't "things that get moved".
NOT_ITEMS = {"cushion", "pillow", "blanket", "throw", "shadow", "light", "reflection", "couch", "sofa",
             "chair", "table", "floor", "carpet", "rug", "wall", "curtain", "tv", "television", "screen",
             "person", "hand", "hands", "arm", "leg", "foot", "feet", "face", "head", "hair", "body",
             "finger", "knee", "shoulder", "shirt", "clothing", "cat", "dog"}

# The model gets two pictures: a close-up of just the spot, and the spot with
# its surroundings (red box). A first version showed only the surroundings and
# the model named whatever stood out nearby: a remote on the "pillow" eight
# times in a minute while Col sat on the couch (2026-10-20 live run).
LOOK_PROMPT = (
    "Image 1 is a close-up of one spot in a living room, from a ceiling camera. Image 2 shows the "
    "same spot inside the red box, with its surroundings. What is the main thing in image 1? Reply "
    "with JSON only: "
    '{{"what": "<a short name, or null>", "kind": "<item, person, furniture or nothing>", '
    '"on": "<what it is sitting on, from image 2, e.g. \'arm of the couch\', \'coffee table\'>"}}. '
    "kind is: item = a small movable object someone could pick up and carry (phone, wallet, keys, "
    "remote, mug, bottle, book...); person = any part of a person or what they are wearing (face, "
    "hand, foot, hair, glasses being worn, clothes); furniture = cushions, pillows, blankets, the "
    "couch, a table, the floor; nothing = a shadow, light or reflection, or nothing you can see. "
    'If it is an item but you cannot tell what, use "what": null with kind item.{owned}'
)
CHECK_PROMPT = (
    "Image 1 is a close-up of one spot in a living room, from a ceiling camera. Image 2 shows the "
    "same spot inside the red box, with its surroundings. Is there a {kind} in image 1? Reply with "
    "JSON only: "
    '{{"present": <true or false>, "what": "<the small movable item there instead, or null>", '
    '"on": "<what the spot is, from image 2>"}}.{owned}'
)


def _overlap(a, b) -> bool:
    return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])


def _iou(a, b) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _reach(box) -> list[float]:
    """A person's box grown by how far they can reach."""
    x, y, w, h = [float(v) for v in box[:4]]
    pad = REACH_PX + REACH_SHARE * max(w, h)
    x0, y0 = max(0.0, x - pad), max(0.0, y - pad)
    return [x0, y0, min(FRAME_W, x + w + pad) - x0, min(FRAME_H, y + h + pad) - y0]


@dataclass
class _Patch:
    box: list[float]
    first_ts: float
    last_ts: float
    frames: int = 1


@dataclass
class _Person:
    ts: float
    reach: list[float]
    identity: Optional[str]
    stay_id: Optional[str]


@dataclass
class ItemEvent:
    """A spot to look at: kind 'look' (what's here?) or 'check' (is item_id still here?)."""
    kind: str
    box: list[float]
    ts: float
    mover: Optional[str]
    stay_id: Optional[str]
    frame: Optional[np.ndarray] = None
    item_id: Optional[int] = None
    item_kind: Optional[str] = None
    extra: dict = field(default_factory=dict)


class ItemWatcher:
    """See the module docstring. observe() is called by the observer's tracker loop."""

    def __init__(
        self,
        store: ItemStore | None = None,
        snapshot: Callable[[], Optional[bytes]] | None = None,
        ask: Callable[[str, np.ndarray], Optional[dict]] | None = None,
        is_at_exit: Callable[[list, tuple, tuple], bool] | None = None,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self._store = store
        self._snapshot = snapshot
        self._ask = ask or ask_vision_model
        self._is_at_exit = is_at_exit
        self._notify = notify
        self._bg: Optional[np.ndarray] = None
        self._bg_known: Optional[np.ndarray] = None
        self._last_gray: Optional[np.ndarray] = None
        self._people_boxes: list[list[float]] = []
        self._patches: list[_Patch] = []
        self._people: collections.deque[_Person] = collections.deque()
        self._cooldowns: list[tuple[float, list[float]]] = []  # (until, box)
        self._known: list[tuple[int, str, list[float]]] = []
        self._known_ts = 0.0
        self._carrying: set[str] = set()
        self._stays_seen: dict[str, tuple[float, list, Optional[str]]] = {}
        self._leaving: dict[str, tuple[float, bytes]] = {}
        self._leaving_asked: dict[str, float] = {}
        self._events: queue.Queue[ItemEvent] = queue.Queue(maxsize=QUEUE_SIZE)
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # --- Start / stop -------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self._store is None:
            self._store = ItemStore()
        self._running.set()
        self._thread = threading.Thread(target=self._worker, name="ItemWatcher", daemon=True)
        self._thread.start()
        logger.info("ItemWatcher: watching the room for things that get moved (spec 5d).")

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    # --- Each frame (fast; the tracker loop's thread) -------------------------------

    def observe(self, frame: np.ndarray, ts: float, tracks: list) -> list[ItemEvent]:
        """Look at one 640x480 frame with the current people tracks. Returns any new events."""
        if frame is None:
            return []
        if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)

        people_now = []
        for t in tracks or []:
            if getattr(t, "is_reflection", False):
                continue
            box = list(getattr(t, "box", None) or [])
            if len(box) < 4:
                continue
            reach = _reach(box)
            people_now.append(reach)
            if getattr(t, "state", "active") == "active":
                self._people.append(_Person(ts, reach, getattr(t, "assigned_identity", None),
                                            getattr(t, "stay_id", None)))
        while self._people and ts - self._people[0].ts > PERSON_WINDOW:
            self._people.popleft()
        self._cooldowns = [(until, box) for until, box in self._cooldowns if until > ts]

        people_mask = np.zeros((FRAME_H, FRAME_W), np.uint8)
        for x, y, w, h in people_now:
            people_mask[int(y):int(y + h), int(x):int(x + w)] = 1

        self._last_gray = gray
        self._people_boxes = [list(map(float, getattr(t, "box", [])[:4])) for t in tracks or []
                              if len(getattr(t, "box", None) or []) >= 4 and not getattr(t, "is_reflection", False)]
        free = people_mask == 0
        if self._bg is None:
            # Where someone is standing, the room isn't known yet (2026-10-20:
            # the background was first taken with Col in front of the side
            # table, and the table "changed" once he moved).
            self._bg = gray.copy()
            self._bg_known = free.copy()
            return []
        unseen = free & ~self._bg_known
        if unseen.any():
            self._bg[unseen] = gray[unseen]
            self._bg_known |= unseen
        self._known_items(ts)  # refreshed every 10 s: known items, and who is carrying one

        diff = cv2.absdiff(gray, self._bg)
        changed = (diff > DIFF_LEVEL).astype(np.uint8)
        changed[~(free & self._bg_known)] = 0
        if changed.sum() > GLOBAL_CHANGE * max(1, int(free.sum())):
            logger.debug("ItemWatcher: most of the room changed (lights?); starting a fresh background.")
            self._bg[free] = gray[free]
            self._patches = []
            return []

        # Follow the room slowly where no one is.
        self._bg[free] += BG_RATE * (gray[free] - self._bg[free])

        events = self._track_patches(changed, ts, people_now, frame)
        self._watch_leaving(ts, tracks or [])
        return events

    def _track_patches(self, changed: np.ndarray, ts: float, people_now: list, frame: np.ndarray) -> list[ItemEvent]:
        changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        changed = cv2.morphologyEx(changed, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        count, _labels, stats, _ = cv2.connectedComponentsWithStats(changed, connectivity=8)
        boxes = []
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if MIN_AREA <= area <= MAX_AREA and w <= MAX_SIDE and h <= MAX_SIDE and area >= MIN_FILL * w * h:
                boxes.append([float(x), float(y), float(w), float(h)])
        if len(boxes) > MAX_PATCHES:
            return []

        kept: list[_Patch] = []
        for box in boxes:
            match = next((p for p in self._patches if _iou(p.box, box) > 0.3), None)
            if match is not None:
                match.box, match.last_ts, match.frames = box, ts, match.frames + 1
                kept.append(match)
            else:
                kept.append(_Patch(box, ts, ts))
        self._patches = kept

        events = []
        for patch in list(self._patches):
            if ts - patch.first_ts < STEADY_SECONDS or patch.frames < STEADY_FRAMES:
                continue
            if any(_overlap(patch.box, reach) for reach in people_now):
                continue
            if any(_overlap(patch.box, box) for _, box in self._cooldowns):
                continue
            visitor = self._last_visitor(patch.box)
            if visitor is None or ts - visitor.ts < CLEAR_SECONDS:
                continue
            event = self._event_for(patch, visitor, frame)
            self._absorb(patch.box, HANDLED_COOLDOWN, ts)
            self._patches.remove(patch)
            try:
                self._events.put_nowait(event)
                events.append(event)
            except queue.Full:
                logger.debug("ItemWatcher: too many spots waiting; skipped one.")
        return events

    def _last_visitor(self, box) -> Optional[_Person]:
        for person in reversed(self._people):
            if _overlap(box, person.reach):
                return person
        return None

    def _event_for(self, patch: _Patch, visitor: _Person, frame: np.ndarray) -> ItemEvent:
        known = self._known_items(patch.last_ts)
        people = {"people": [list(b) for b in self._people_boxes]}
        for item_id, kind, seen in known:
            if _iou(patch.box, seen) > 0.2 or _overlap(_center_box(seen), patch.box):
                return ItemEvent("check", patch.box, patch.last_ts, visitor.identity, visitor.stay_id,
                                 frame.copy(), item_id=item_id, item_kind=kind, extra=people)
        return ItemEvent("look", patch.box, patch.last_ts, visitor.identity, visitor.stay_id, frame.copy(),
                         extra=people)

    def _absorb(self, box, cooldown: float, ts: float) -> None:
        """Take a spot's current look into the background and leave it alone for a while."""
        x, y, w, h = [int(v) for v in box]
        pad = 6
        y0, y1, x0, x1 = max(0, y - pad), min(FRAME_H, y + h + pad), max(0, x - pad), min(FRAME_W, x + w + pad)
        if self._bg is not None and self._last_gray is not None:
            self._bg[y0:y1, x0:x1] = self._last_gray[y0:y1, x0:x1]
        self._cooldowns.append((ts + cooldown, [float(x0), float(y0), float(x1 - x0), float(y1 - y0)]))

    def _known_items(self, ts: float) -> list[tuple[int, str, list[float]]]:
        """Items last seen put down somewhere (cached for 10 s)."""
        if self._store is not None and ts - self._known_ts > 10.0:
            self._known_ts = ts
            try:
                known = []
                for item in self._store.placed_items():
                    box = json.loads(item.get("last_seen_box") or "null")
                    if box:
                        known.append((item["id"], item.get("kind") or "item", box))
                self._known = known
                self._carrying = set(self._store.carrying_stays())
            except Exception as e:
                logger.debug(f"ItemWatcher: couldn't read the item list: {e}")
        return self._known

    # --- Leaving with an item -----------------------------------------------------

    def _watch_leaving(self, ts: float, tracks: list) -> None:
        current = {}
        for t in tracks:
            stay = getattr(t, "stay_id", None)
            if stay:
                current[stay] = t
                self._stays_seen[stay] = (ts, list(t.box), getattr(t, "assigned_identity", None))
        if not self._carrying:
            self._stays_seen = {k: v for k, v in self._stays_seen.items() if k in current}
            return
        for stay, t in current.items():
            if stay not in self._carrying or not self._at_exit(t.box):
                continue
            if ts - self._leaving_asked.get(stay, 0.0) >= LEAVING_STILL_INTERVAL:
                self._leaving_asked[stay] = ts
                try:
                    self._events.put_nowait(ItemEvent("leaving", list(t.box), ts,
                                                      getattr(t, "assigned_identity", None), stay))
                except queue.Full:
                    pass
        for stay in [s for s in self._stays_seen if s not in current]:
            seen_ts, box, identity = self._stays_seen.pop(stay)
            if stay in self._carrying and self._at_exit(box):
                try:
                    self._events.put_nowait(ItemEvent("left", box, seen_ts, identity, stay))
                except queue.Full:
                    pass

    def _at_exit(self, box) -> bool:
        if self._is_at_exit is None:
            return False
        x, y, w, h = box[:4]
        try:
            return bool(self._is_at_exit(box, (x + w / 2, y + h / 2), (FRAME_H, FRAME_W)))
        except Exception:
            return False

    # --- The closer look (worker thread) ----------------------------------------

    def _worker(self) -> None:
        last_ask = 0.0
        while self._running.is_set():
            try:
                event = self._events.get(timeout=0.5)
            except queue.Empty:
                continue
            wait = MIN_ASK_INTERVAL - (time.monotonic() - last_ask)
            if wait > 0:
                time.sleep(wait)
            try:
                self.handle(event)
            except Exception as e:
                logger.warning(f"ItemWatcher: looking at a spot failed: {type(e).__name__}: {e}")
            last_ask = time.monotonic()

    def _still(self, event: ItemEvent) -> np.ndarray | None:
        """A sharp still from the main stream, or the event's own frame if there's none."""
        if self._snapshot is not None:
            try:
                data = self._snapshot()
                if data:
                    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    if image is not None:
                        return image
            except Exception as e:
                logger.debug(f"ItemWatcher: no still from the camera ({e}); using the stream frame.")
        return event.frame

    def handle(self, event: ItemEvent) -> Optional[dict]:
        """Look at one spot and record what happened. Returns the store's result (for tests and logs)."""
        if event.kind == "left":
            return self._handle_left(event)
        still = self._still(event)
        if still is None:
            return None
        if event.kind == "leaving":
            crop = _crop(still, event.box, scale_pad=0.15, min_side=0)
            ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if ok and event.stay_id:
                self._leaving[event.stay_id] = (event.ts, jpg.tobytes())
            return None

        # People in the picture are blurred: an item's photo is of the item
        # and its spot, not of whoever is nearby (spec 5d privacy).
        still = _blur_people(still, event.extra.get("people") or [], event.box)
        answer, plain = self._look(still, event)
        on = _text(answer.get("on"))
        name = _text(answer.get("what"))
        kind = normalize_kind(name)
        not_an_item = str(answer.get("kind") or "item").lower() in ("person", "furniture", "nothing")
        if kind in NOT_ITEMS or not_an_item:
            kind = None

        if event.kind == "check":
            if answer.get("present") is True:
                result = self._store.record_put_down(event.item_kind or "item", event.box, on, None,
                                                     event.stay_id, event.ts)
                if result.get("moved") is False:
                    return result
            else:
                # Looked at again a few seconds later: someone passing in front
                # of it isn't a pick-up.
                time.sleep(RECHECK_SECONDS)
                again = self._still(event)
                if again is not None:
                    second, _ = self._look(_blur_people(again, event.extra.get("people") or [], event.box), event)
                    if second.get("present") is True:
                        logger.debug(f"ItemWatcher: the {event.item_kind} is still there after all.")
                        return {"still_there": event.item_id}
                taken = self._store.record_picked_up(event.box, event.mover, event.stay_id, event.ts)
                self._carrying.add(event.stay_id or "")
                for item in taken:
                    logger.info(f"ItemWatcher: {event.mover or 'someone'} picked up the {item.get('kind')} "
                                f"(item {item['id']}).")
                    self._tell_if_not_col(item, event, "picked up")
                if not kind:
                    self._known_ts = 0.0
                    return {"picked_up": [t["id"] for t in taken]}

        if not kind and (not_an_item or name or answer.get("kind") is None):
            # Nothing there: a shadow, a cushion, the light. Leave the spot alone for a while.
            self._cooldowns.append((event.ts + NOTHING_COOLDOWN, event.box))
            logger.debug(f"ItemWatcher: nothing at {event.box} ({name or 'no item'}).")
            return None

        if kind:
            item = self._store.record_put_down(kind, event.box, on, event.mover, event.stay_id, event.ts,
                                               description=name)
            photo = self._store.photo_path(item["id"], "last_seen")
        else:
            item = self._store.record_unnamed(event.box, on, event.mover, event.stay_id, event.ts)
            photo = self._store.photo_path(item["id"], "unnamed")
        cv2.imwrite(str(photo), plain)
        self._store.set_last_seen_photo(item["id"], str(photo))
        self._known_ts = 0.0
        logger.info(
            f"ItemWatcher: {event.mover or 'someone'} put down {('the ' + kind) if kind else 'something unclear'} "
            f"on {item.get('place')} (item {item['id']}{', new' if item.get('new') else ''})."
        )
        if item.get("moved"):
            self._tell_if_not_col(item, event, "moved")
        return item

    def _look(self, still: np.ndarray, event: ItemEvent) -> tuple[dict, np.ndarray]:
        """Ask the vision model about the spot: (its answer, the photo to keep of the spot)."""
        marked, plain = _marked_crop(still, event.box)
        close = _close_up(still, event.box)
        owned = self._owned_note()
        if event.kind == "check":
            prompt = CHECK_PROMPT.format(kind=event.item_kind or "item", owned=owned)
        else:
            prompt = LOOK_PROMPT.format(owned=owned)
        return (self._ask(prompt, [close, marked]) or {}), plain

    def _owned_note(self) -> str:
        """The items Col taught ARCHER, so the model uses their names ("his wallet")."""
        try:
            taught = self._store.taught_items() if self._store is not None else []
        except Exception:
            taught = []
        described = [f"{t['description']} (his {t['kind']})" for t in taught if t.get("description")]
        if not described:
            return ""
        return (" Colby's own items look like this: " + "; ".join(described[:8])
                + ". If the item is one of these, use that name.")

    def _handle_left(self, event: ItemEvent) -> Optional[list]:
        photo_path = None
        saved = self._leaving.pop(event.stay_id or "", None)
        carried = self._store.carried_by_stay(event.stay_id or "")
        if not carried:
            return None
        if saved and event.ts - saved[0] <= LEAVING_PHOTO_MAX_AGE:
            path = self._store.photo_path(carried[0]["id"], "leaving")
            path.write_bytes(saved[1])
            photo_path = str(path)
        left = self._store.record_left_with(event.stay_id, event.mover, event.ts, photo_path)
        self._carrying.discard(event.stay_id or "")
        for item in left:
            logger.info(f"ItemWatcher: {event.mover or 'someone'} left the room with the {item.get('kind')} "
                        f"(item {item['id']}, photo {'kept' if photo_path else 'none'}).")
        return left

    def _tell_if_not_col(self, item: dict, event: ItemEvent, what: str) -> None:
        """Moves by anyone but Col go into While You Were Away (ARCHER also mentions them in conversation)."""
        if event.mover == COL or self._notify is None:
            return
        try:
            self._notify(f"{event.mover or 'Someone'} {what} the {item.get('kind') or 'item'}"
                         f"{' (' + item['place'] + ')' if item.get('place') else ''}.")
        except Exception:
            pass


def _blur_people(image: np.ndarray, people: list, spot) -> np.ndarray:
    """A copy of `image` with each person's box (640x480 coordinates) blurred, unless it covers the spot."""
    if not people:
        return image
    out = image.copy()
    h, w = out.shape[:2]
    sx, sy = w / FRAME_W, h / FRAME_H
    for box in people:
        x, y, bw, bh = box[:4]
        pad_w, pad_h = 0.15 * bw, 0.15 * bh
        grown = [x - pad_w, y - pad_h, bw + 2 * pad_w, bh + 2 * pad_h]
        if _overlap(grown, spot):
            continue
        x0, y0 = int(max(0, grown[0] * sx)), int(max(0, grown[1] * sy))
        x1, y1 = int(min(w, (grown[0] + grown[2]) * sx)), int(min(h, (grown[1] + grown[3]) * sy))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        region = out[y0:y1, x0:x1]
        k = max(15, (min(x1 - x0, y1 - y0) // 4) | 1)
        out[y0:y1, x0:x1] = cv2.GaussianBlur(region, (k, k), 0)
    return out


def _center_box(box) -> list[float]:
    x, y, w, h = box
    return [x + w / 2 - 1, y + h / 2 - 1, 2.0, 2.0]


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip(" .")
    return text if text and text.lower() not in {"null", "none", "n/a", "unknown"} else None


def _crop(image: np.ndarray, box, scale_pad: float = 1.5, min_side: int = 360) -> np.ndarray:
    """A crop around a 640x480 box, from an image of any size."""
    h, w = image.shape[:2]
    sx, sy = w / FRAME_W, h / FRAME_H
    x, y, bw, bh = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
    cx, cy = x + bw / 2, y + bh / 2
    half_w = max(bw * (1 + 2 * scale_pad), min_side) / 2
    half_h = max(bh * (1 + 2 * scale_pad), min_side) / 2
    x0, x1 = int(max(0, cx - half_w)), int(min(w, cx + half_w))
    y0, y1 = int(max(0, cy - half_h)), int(min(h, cy + half_h))
    return image[y0:y1, x0:x1].copy()


def _close_up(image: np.ndarray, box) -> np.ndarray:
    """Just the spot (40% margin), enlarged to at least 256 pixels on its long side."""
    h, w = image.shape[:2]
    sx, sy = w / FRAME_W, h / FRAME_H
    x, y, bw, bh = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
    pad_w, pad_h = max(0.4 * bw, 4 * sx), max(0.4 * bh, 4 * sy)
    x0, y0 = int(max(0, x - pad_w)), int(max(0, y - pad_h))
    x1, y1 = int(min(w, x + bw + pad_w)), int(min(h, y + bh + pad_h))
    crop = image[y0:y1, x0:x1]
    long_side = max(crop.shape[:2]) if crop.size else 0
    if 0 < long_side < 256:
        scale = 256 / long_side
        crop = cv2.resize(crop, (int(crop.shape[1] * scale), int(crop.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
    return crop


def _marked_crop(image: np.ndarray, box) -> tuple[np.ndarray, np.ndarray]:
    """(crop with a red box around the spot, the same crop without it)."""
    h, w = image.shape[:2]
    sx, sy = w / FRAME_W, h / FRAME_H
    x, y, bw, bh = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
    # Four times the spot, and at least a 100-pixel square of the 640x480
    # picture (400 pixels of the 2560x1920 still), for what it's sitting on.
    half = max(4.0 * max(box[2], box[3]), 100.0) * sx / 2
    cx, cy = x + bw / 2, y + bh / 2
    x0, x1 = int(max(0, cx - half)), int(min(w, cx + half))
    y0, y1 = int(max(0, cy - half)), int(min(h, cy + half))
    plain = image[y0:y1, x0:x1].copy()
    marked = plain.copy()
    pad = max(4, int(4 * sx))
    thickness = max(2, int(2 * sx))
    cv2.rectangle(marked, (int(x - x0) - pad, int(y - y0) - pad), (int(x - x0 + bw) + pad, int(y - y0 + bh) + pad),
                  (0, 0, 255), thickness)
    return marked, plain


def ask_vision_model(prompt: str, images: list[np.ndarray]) -> Optional[dict]:
    """Ask ARCHER's own vision model about some pictures; its JSON answer, or None."""
    import base64

    import httpx

    from archer.config import get_config
    from archer.integrations.ollama_settings import main_model_request

    config = get_config()
    encoded = []
    for image in images if isinstance(images, (list, tuple)) else [images]:
        ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return None
        encoded.append(base64.b64encode(jpg.tobytes()).decode())
    payload = {
        "model": config.core_primary_model,
        "think": bool(getattr(config, "core_think", False)),
        "prompt": prompt,
        "images": encoded,
        "format": "json",
        "stream": False,
    }
    main_model_request(payload, config, temperature=0.0, num_predict=120)
    try:
        resp = httpx.post(f"{config.ollama_base_url}/api/generate", json=payload, timeout=60.0)
        resp.raise_for_status()
        return json.loads(resp.json().get("response") or "{}")
    except Exception as e:
        logger.debug(f"ItemWatcher: the vision model didn't answer ({type(e).__name__}: {e}).")
        return None
