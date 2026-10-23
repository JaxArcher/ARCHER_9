"""
ARCHER Phase 2d: talking about things that get moved (Claude, 2026-10-20).

What Col says to ARCHER about items, handled directly (no model guesswork):
- "Where's my wallet?", "Have you seen the remote?", "When did I last have my
  keys?": the last place and time, who put it there, and its last-seen photo
  shown in ARCHER's page. Never a made-up place.
- "This is my wallet" while holding it up to ARCHER's camera: ARCHER keeps a
  reference photo and a short description, so it knows which one is Col's.
- "Forget my wallet": the item, its moves and its photos are deleted.
- "Call that spot the couch arm": renames the spot ARCHER just mentioned.
- Answers to ARCHER's question about an item it couldn't name: "it's my
  sunglasses" names it; "no idea" / "ignore it" drops it and its photo.

And what ARCHER brings up itself (items_note, added to the system prompt):
moves by anyone but Col since it last spoke with him, and, now and then, one
item it couldn't name.

Used by CoreAgent. The observer service records the moves
(observer/item_watcher.py); both share archer.db (memory/item_store.py).
"""

from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger

from archer.memory.item_store import (
    COL,
    UNNAMED,
    ItemStore,
    _KIND_SYNONYMS,
    describe_move,
    describe_where,
    normalize_kind,
    when_text,
)

_LEAD = r"^(?:(?:hey\s+)?archer\s+)?(?:(?:can|could)\s+you\s+tell\s+me\s+|do\s+you\s+know\s+|so\s+|okay\s+|ok\s+)?"
_WHERE_RES = [
    re.compile(_LEAD + r"where(?:'s|\s+is|\s+are|'re|\s+did\s+i\s+(?:put|leave)|\s+have\s+i\s+(?:put|left)"
               r"|\s+did\s+(?:i|you)\s+(?:last\s+)?see)\s+(?P<q>(?:my|the|our)\s+.+?)"
               r"(?:\s+(?:at|go|went|now|again|right\s+now))?$"),
    re.compile(_LEAD + r"(?:have|did)\s+you\s+(?:seen|see)\s+(?P<q>(?:my|the|our)\s+.+?)"
               r"(?:\s+(?:anywhere|today|lately|recently))?$"),
    re.compile(_LEAD + r"when\s+did\s+i\s+last\s+(?:have|see|use|touch)\s+(?P<q>(?:my|the|our)\s+.+?)$"),
    re.compile(_LEAD + r"who\s+(?:moved|took|has|touched)\s+(?P<q>(?:my|the|our)\s+.+?)$"),
]
_TEACH_RES = [
    re.compile(_LEAD + r"(?:this\s+is|these\s+are|this\s+one\s+is|here'?s|here\s+is|here\s+are|meet)\s+"
               r"(?P<q>(?:my|our)\s+.+?)(?:\s+archer)?$"),
    re.compile(_LEAD + r"(?:remember|learn|note)\s+(?:that\s+)?(?:this\s+is|these\s+are)\s+(?P<q>(?:my|our)\s+.+?)$"),
]
_FORGET_RE = re.compile(_LEAD + r"(?:please\s+)?forget\s+(?:about\s+)?(?P<q>(?:my|the|our)\s+.+?)$")
_RENAME_RE = re.compile(
    _LEAD + r"(?:call\s+(?:that|the|this)\s+(?:spot|place)|(?:that|this)\s+(?:spot|place)\s+is(?:\s+called)?"
    r"|i\s+call\s+(?:that|it|that\s+spot)|call\s+it)\s+(?:the\s+)?(?P<name>.+)$"
)
_ANSWER_RE = re.compile(
    r"^(?:oh\s+|um\s+|uh\s+|yeah\s+|yes\s+)?(?:it'?s|that'?s|those\s+are|these\s+are|that\s+is|it\s+is|they'?re)\s+"
    r"(?:just\s+)?(?:my|a|an|the|some|our)?\s*(?P<name>.+)$"
)
_DISMISS_RE = re.compile(
    r"\b(?:no\s+idea|don'?t\s+know|not\s+sure|ignore\s+it|never\s*mind|nothing|forget\s+it|doesn'?t\s+matter)\b"
)
# "This is my brother" is a person (Phase 2b), not an item.
_PEOPLE_WORDS = {
    "friend", "brother", "sister", "mom", "mother", "dad", "father", "wife", "husband", "girlfriend",
    "boyfriend", "partner", "son", "daughter", "kid", "kids", "child", "baby", "neighbor", "neighbour",
    "coworker", "colleague", "boss", "roommate", "cousin", "uncle", "aunt", "grandma", "grandpa",
    "grandmother", "grandfather", "nephew", "niece", "buddy", "pal", "guest", "family", "fiance", "fiancee",
    "dog", "cat", "puppy", "kitten", "pet", "room", "house", "home", "place", "car", "truck", "favorite",
    "favourite", "point", "problem", "question", "idea", "plan", "day", "life", "turn", "job", "song",
}
_KNOWN_KINDS = set(_KIND_SYNONYMS)
# How often ARCHER may bring up an item it couldn't name, and how long an answer counts.
UNNAMED_ASK_EVERY = 30 * 60
ANSWER_WINDOW = 10 * 60


def _clean(text: str) -> str:
    clean = re.sub(r"[^\w\s']", " ", (text or "").lower().replace("’", "'"))
    return " ".join(clean.split())


def _item_phrase(q: str) -> Optional[str]:
    """'my black wallet' -> 'black wallet'; None if it's a person or too long to be an item."""
    words = q.split()
    if words and words[0] in ("my", "the", "our"):
        words = words[1:]
    if not words or len(words) > 4 or any(w in _PEOPLE_WORDS for w in words):
        return None
    return " ".join(words)


class ItemTalk:
    """See the module docstring."""

    def __init__(
        self,
        store: ItemStore | None = None,
        get_frame: Callable[[], tuple[Any, Any]] | None = None,
        describe: Callable[[str, Any], Optional[str]] | None = None,
        show_photo: Callable[[str, str], None] | None = None,
    ) -> None:
        self._store = store
        self._get_frame = get_frame
        self._describe = describe
        self._show_photo = show_photo
        self._last_place: Optional[tuple[int, str]] = None
        self._asked_unnamed: Optional[tuple[int, float]] = None
        self._last_unnamed_ask = 0.0

    @property
    def store(self) -> ItemStore:
        if self._store is None:
            self._store = ItemStore()
        return self._store

    # --- What Col says ---------------------------------------------------------------

    def handle(self, text: str) -> Optional[str]:
        """ARCHER's reply if `text` is about an item, else None."""
        clean = _clean(text)
        if not clean or len(clean.split()) > 16:
            return None
        try:
            return (
                self._answer_about_unnamed(clean)
                or self._teach(clean)
                or self._where(clean)
                or self._forget(clean)
                or self._rename_spot(clean)
            )
        except Exception as e:
            logger.warning(f"Item question failed: {type(e).__name__}: {e}")
            return None

    def _where(self, clean: str) -> Optional[str]:
        for pattern in _WHERE_RES:
            m = pattern.match(clean)
            if m:
                break
        else:
            return None
        phrase = _item_phrase(m.group("q"))
        if not phrase:
            return None
        kind = normalize_kind(phrase)
        found = self.store.find(phrase)
        if not found:
            if kind in _KNOWN_KINDS:
                noun = ("your " if m.group("q").startswith(("my", "our")) else "the ") + kind
                return f"I haven't seen {noun} yet."
            return None  # not an item ARCHER tracks; let the model answer
        item = found[0]
        answer = describe_where(item)
        if item.get("status") == "placed" and item.get("current_location_id") and item.get("place"):
            self._last_place = (item["current_location_id"], item["place"])
        self._show(item)
        return answer

    def _show(self, item: dict) -> None:
        """Show where the item was last seen. Nothing if ARCHER hasn't seen it yet (2026-10-20: the
        reference photo Col had just shown it came up titled "Last seen")."""
        if self._show_photo is None or not item.get("last_seen_ts"):
            return
        leaving = item.get("status") == "left" and item.get("image_path")
        path = item.get("image_path") if leaving else item.get("last_seen_image_path")
        if not path or not Path(path).exists():
            return
        try:
            data = base64.b64encode(Path(path).read_bytes()).decode()
            what = item.get("kind") or item.get("item_name")
            title = f"{'Leaving with' if leaving else 'Last seen'}: {what} ({when_text(item['last_seen_ts'])})"
            self._show_photo(data, title)
        except Exception as e:
            logger.debug(f"Couldn't show the item photo: {e}")

    def _teach(self, clean: str) -> Optional[str]:
        for pattern in _TEACH_RES:
            m = pattern.match(clean)
            if m:
                break
        else:
            return None
        phrase = _item_phrase(m.group("q"))
        kind = normalize_kind(phrase) if phrase else None
        if not kind or kind == UNNAMED:
            return None
        description = None
        reference = None
        frame = None
        if self._get_frame is not None:
            try:
                frame, _ts = self._get_frame()
            except Exception:
                frame = None
        if frame is not None and self._describe is not None:
            description = self._describe(kind, frame)
        item_id = self.store.teach(kind, COL, description or (phrase if phrase != kind else None))
        if frame is not None:
            try:
                import cv2

                path = self.store.photo_path(item_id, "reference")
                h, w = frame.shape[:2]
                scale = min(1.0, 960 / max(h, w))
                small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1 else frame
                cv2.imwrite(str(path), small)
                self.store.teach(kind, COL, None, reference_image_path=str(path))
                reference = path
            except Exception as e:
                logger.debug(f"Couldn't keep the reference photo: {e}")
        logger.info(f"Item taught: Col's {kind} (item {item_id}, description: {description!r}, photo: {bool(reference)}).")
        if description:
            return f"Got it: your {kind}, the {description}. I'll keep track of where it goes."
        if frame is None:
            return (f"Got it: your {kind}. I couldn't see it on the camera, so I'll learn what it looks like "
                    "when I spot it.")
        return f"Got it: your {kind}. I'll keep track of where it goes."

    def _forget(self, clean: str) -> Optional[str]:
        m = _FORGET_RE.match(clean)
        if not m:
            return None
        phrase = _item_phrase(m.group("q"))
        if not phrase:
            return None
        found = self.store.find(phrase)
        if not found:
            return None  # "forget the meeting" isn't about items
        item = found[0]
        self.store.forget(item["id"])
        noun = ("your " if item.get("owner") == COL or m.group("q").startswith("my") else "the ") + (item.get("kind") or phrase)
        logger.info(f"Item forgotten at Col's request: item {item['id']} ({item.get('kind')}).")
        return f"Done. I've forgotten {noun}, its photos and where it's been."

    def _rename_spot(self, clean: str) -> Optional[str]:
        m = _RENAME_RE.match(clean)
        if not m or self._last_place is None:
            return None
        name = " ".join(m.group("name").split()).strip(" .")
        if not name or len(name.split()) > 5:
            return None
        location_id, old = self._last_place
        self.store.rename_place(location_id, name)
        self._last_place = (location_id, name)
        return f"Got it. I'll call that spot the {name} from now on." if not name.startswith(("the ", "a ")) \
            else f"Got it. I'll call that spot {name} from now on."

    def _answer_about_unnamed(self, clean: str) -> Optional[str]:
        if self._asked_unnamed is None:
            return None
        item_id, asked_at = self._asked_unnamed
        if time.time() - asked_at > ANSWER_WINDOW:
            self._asked_unnamed = None
            return None
        if _DISMISS_RE.search(clean):
            self._asked_unnamed = None
            self.store.forget(item_id)
            return "No problem. I've dropped it and deleted its photo."
        m = _ANSWER_RE.match(clean)
        if not m:
            return None
        name = _item_phrase(m.group("name"))
        kind = normalize_kind(name) if name else None
        if not kind or kind == UNNAMED:
            return None
        owner = COL if re.search(r"\b(?:my|mine)\b", clean) else None
        self._asked_unnamed = None
        item = self.store.name_item(item_id, kind, owner=owner)
        where = f" It's {_place_text(item)}." if item and item.get("place") else ""
        return f"Thanks. I'll remember that's {'your' if owner else 'a'} {kind}.{where}"

    # --- What ARCHER brings up -----------------------------------------------------

    def items_note(self) -> str:
        """A block for the system prompt: moves to mention, and maybe one question. Empty if nothing."""
        parts = []
        try:
            moves = self.store.untold_moves(limit=6)
            if moves:
                lines = [describe_move(m) for m in moves]
                self.store.mark_told([m["id"] for m in moves])
                parts.append(
                    "[Items moved by someone other than Colby since you last spoke (from the room camera). "
                    "Tell him briefly, in your own words, at a natural point in this reply: "
                    + " ".join(lines) + "]"
                )
            # Spec 5f (Col 2026-10-22): No photos or questions in chat.
            # When ARCHER_ITEMS_WATCH is true, unnamed items become question cards in the 'I have questions' tab.
            # While ARCHER_ITEMS_WATCH=false (Phase 2d paused), item questions stay off completely.
            import os
            items_watch_on = (os.environ.get("ARCHER_ITEMS_WATCH", "false").lower() == "true")
            if items_watch_on:
                from archer.memory.sqlite_store import get_sqlite_store
                store = get_sqlite_store()
                if hasattr(store, "create_or_update_item_question"):
                    unnamed = self.store.unnamed_items()
                    if unnamed:
                        item = unnamed[0]
                        store.create_or_update_item_question(item["id"], item)
        except Exception as e:
            logger.debug(f"Item notes failed (non-fatal): {e}")
        return ("\n" + "\n".join(parts)) if parts else ""


def _place_text(item: dict) -> str:
    place = (item.get("place") or "a spot in the room").strip()
    if place.lower().startswith(("on ", "in ", "at ", "by ", "under ", "next to ", "near ")):
        return place
    if place.lower().startswith(("a ", "an ", "the ")):
        return f"on {place}"
    return f"on the {place}"


DESCRIBE_PROMPT = (
    "Colby is holding up or showing an item to the camera and says it's his {kind}. Describe that item in "
    "three to six words (colour, material, anything distinctive), for example 'black leather bifold wallet'. "
    "Reply with just the description. If you can't see a {kind}, reply with just: none"
)
