"""
Phase 2d: things that get moved (Claude, 2026-10-20).

The item records (memory/item_store.py): items, named spots, moves, who moved
them, and ARCHER's answers. Uses a temporary database and photo folder, never
the real ones.
"""

import time
from datetime import datetime

import pytest

from archer.memory.item_store import (
    COL,
    UNNAMED,
    ItemStore,
    describe_move,
    describe_where,
    normalize_kind,
    when_text,
)

COUCH_ARM = [100.0, 380.0, 40.0, 16.0]  # a phone-sized patch, 640x480 coordinates
COUNTER = [520.0, 250.0, 30.0, 14.0]


@pytest.fixture
def store(tmp_path):
    return ItemStore(db_path=str(tmp_path / "archer.db"), photos_dir=tmp_path / "items")


def test_kinds():
    assert normalize_kind("TV remote") == "remote"
    assert normalize_kind("Black leather wallet") == "wallet"
    assert normalize_kind("my smartphone") == "phone"
    assert normalize_kind("a set of keys") == "keys"
    assert normalize_kind("red lighter") == "lighter"
    for nothing in ("nothing", "None", "unclear", "", None):
        assert normalize_kind(nothing) is None
    assert normalize_kind(UNNAMED) == UNNAMED


def test_put_down_then_where(store):
    now = time.time()
    item = store.record_put_down("Wallet", COUCH_ARM, "arm of the couch", COL, "stay_a", now)
    assert item["new"] and item["moved"] and item["place"] == "arm of the couch"
    found = store.find("my wallet")
    assert [f["id"] for f in found] == [item["id"]]
    answer = describe_where(found[0], now=now)
    assert answer.startswith("The wallet is on the arm of the couch. You put it there at ")


def test_same_spot_is_not_a_new_move(store):
    first = store.record_put_down("phone", COUCH_ARM, "arm of the couch", COL, "stay_a", 1000.0)
    again = store.record_put_down("smartphone", [102.0, 381.0, 38.0, 15.0], "couch arm", COL, "stay_a", 1100.0)
    assert again["id"] == first["id"] and not again["moved"]
    assert len(store.history(first["id"])) == 1


def test_pick_up_and_put_down_elsewhere_by_someone_else(store):
    store.teach("wallet", COL, "black leather wallet")
    item = store.record_put_down("wallet", COUCH_ARM, "arm of the couch", COL, "stay_col", 1000.0)
    taken = store.record_picked_up(COUCH_ARM, "Sarah", "stay_sarah", 2000.0)
    assert [t["id"] for t in taken] == [item["id"]]
    assert store.get(item["id"])["status"] == "carried"
    moved = store.record_put_down("wallet", COUNTER, "kitchen counter", "Sarah", "stay_sarah", 2100.0)
    assert moved["id"] == item["id"] and moved["place"] == "kitchen counter"
    assert moved["owner"] == COL  # still Col's wallet

    # Col's own put-down needs no telling; Sarah's pick-up and move do.
    untold = store.untold_moves()
    assert [m["event"] for m in untold] == ["picked_up", "put_down"]
    told = describe_move(untold[1], now=2200.0)
    assert told.startswith("Sarah moved your wallet from the arm of the couch to the kitchen counter at ")
    store.mark_told([m["id"] for m in untold])
    assert store.untold_moves() == []


def test_leaving_with_an_item(store, tmp_path):
    item = store.record_put_down("remote", COUCH_ARM, "arm of the couch", COL, "stay_col", 1000.0)
    store.record_picked_up(COUCH_ARM, "Person_4", "stay_p4", 2000.0)
    assert [c["id"] for c in store.carried_by_stay("stay_p4")] == [item["id"]]
    photo = str(tmp_path / "items" / f"item_{item['id']}_leaving.jpg")
    left = store.record_left_with("stay_p4", "Person_4", 2050.0, photo)
    assert [r["id"] for r in left] == [item["id"]]
    found = store.get(item["id"])
    assert found["status"] == "left" and found["image_path"] == photo
    assert "someone I don't know yet left the room with the remote" in describe_where(found, now=2100.0)


def test_unnamed_items_are_kept_apart_and_named_later(store, tmp_path):
    a = store.record_unnamed(COUCH_ARM, "arm of the couch", COL, "s", 1000.0)
    b = store.record_unnamed(COUNTER, "kitchen counter", COL, "s", 1001.0)
    assert a["id"] != b["id"]
    assert [u["id"] for u in store.unnamed_items()] == [a["id"], b["id"]]
    photo = store.photo_path(a["id"], "unnamed")
    photo.write_bytes(b"jpg")
    named = store.name_item(a["id"], "sunglasses", owner=COL)
    assert named["kind"] == "sunglasses" and not photo.exists()
    assert [u["id"] for u in store.unnamed_items()] == [b["id"]]


def test_teaching_adopts_an_item_seen_before(store):
    seen = store.record_put_down("phone", COUCH_ARM, "arm of the couch", COL, "s", 1000.0)
    taught = store.teach("my phone", COL, "black phone in a blue case", "data/items/ref.jpg")
    assert taught == seen["id"]
    item = store.get(taught)
    assert item["owner"] == COL and item["description"] == "black phone in a blue case"
    assert store.teach("phone", COL, None) == taught  # teaching again updates it


def test_forget_removes_item_history_and_photos(store):
    item = store.record_put_down("mug", COUCH_ARM, "arm of the couch", COL, "s", 1000.0)
    photo = store.photo_path(item["id"], "last_seen")
    photo.write_bytes(b"jpg")
    assert store.forget(item["id"])
    assert store.get(item["id"]) is None and store.history(item["id"]) == [] and not photo.exists()


def test_places_are_reused_and_can_be_renamed(store):
    first = store.record_put_down("phone", COUCH_ARM, "arm of the couch", COL, "s", 1000.0)
    beside = store.record_put_down("wallet", [130.0, 382.0, 30.0, 14.0], "couch", COL, "s", 1001.0)
    assert beside["current_location_id"] == first["current_location_id"]  # next to it: same spot
    store.rename_place(first["current_location_id"], "couch arm")
    assert store.get(first["id"])["place"] == "couch arm"


def test_answers_never_invent_a_place(store):
    assert describe_where({"kind": "keys", "owner": COL}) == "I haven't seen your keys yet."
    assert store.find("wallet") == []


def test_when_text():
    now = datetime(2026, 10, 20, 18, 0).timestamp()
    assert when_text(datetime(2026, 10, 20, 15, 12).timestamp(), now) == "at 3:12 PM"
    assert when_text(datetime(2026, 10, 19, 9, 5).timestamp(), now) == "yesterday at 9:05 AM"
    assert when_text(datetime(2026, 10, 14, 15, 42).timestamp(), now) == "on Wed Oct 14 at 3:42 PM"


# --- The room watcher (observer/item_watcher.py) ------------------------------------------

from types import SimpleNamespace  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from archer.observer.item_watcher import ItemEvent, ItemWatcher  # noqa: E402


def room():
    """A 640x480 'living room': a gradient with a couch and a table, so blurring keeps detail."""
    img = np.zeros((480, 640, 3), np.uint8)
    img[:] = np.linspace(60, 140, 640, dtype=np.uint8)[None, :, None]
    cv2.rectangle(img, (40, 360), (600, 470), (70, 60, 50), -1)    # couch
    cv2.rectangle(img, (420, 230), (600, 300), (110, 120, 130), -1)  # counter
    return img


def person(img, box):
    x, y, w, h = box
    cv2.rectangle(img, (x, y), (x + w, y + h), (30, 30, 30), -1)
    return img


def track(box, identity="Col", stay="stay_1"):
    return SimpleNamespace(box=list(box), state="active", assigned_identity=identity, stay_id=stay, is_reflection=False)


def run(watcher, frames, start=1000.0):
    """frames: list of (image, tracks); 2 frames a second. Returns all events."""
    events = []
    for i, (img, tracks) in enumerate(frames):
        events += watcher.observe(img, start + i * 0.5, tracks)
    return events


PERSON = (150, 200, 100, 250)          # standing beside the couch arm
WALLET = (100, 380, 40, 16)            # 640x480 box of the item put down


def with_wallet(img):
    x, y, w, h = WALLET
    cv2.rectangle(img, (x, y), (x + w, y + h), (200, 200, 210), -1)
    return img


def test_something_put_down_after_someone_was_there(store):
    watcher = ItemWatcher(store=store)
    frames = [(room(), [])] * 4
    frames += [(person(room(), PERSON), [track(PERSON)])] * 6                    # Col walks up
    frames += [(with_wallet(person(room(), PERSON)), [track(PERSON)])] * 4      # puts it down
    frames += [(with_wallet(room()), [])] * 14                                  # walks away
    events = run(watcher, frames)
    assert len(events) == 1
    event = events[0]
    assert event.kind == "look" and event.mover == "Col" and event.stay_id == "stay_1"
    x, y, w, h = event.box
    assert abs(x - 100) <= 4 and abs(y - 380) <= 4 and 34 <= w <= 46 and 10 <= h <= 22
    # Once handled, the spot is part of the background: no second event.
    assert run(watcher, [(with_wallet(room()), [])] * 20, start=2000.0) == []


def test_nothing_happens_without_someone_nearby(store):
    watcher = ItemWatcher(store=store)
    frames = [(room(), [])] * 4 + [(with_wallet(room()), [])] * 20
    assert run(watcher, frames) == []


def test_lights_coming_on_are_not_an_item(store):
    watcher = ItemWatcher(store=store)
    brighter = cv2.add(room(), np.full((480, 640, 3), 60, np.uint8))
    frames = [(room(), [])] * 4 + [(person(room(), PERSON), [track(PERSON)])] * 4
    frames += [(brighter, [])] * 20
    assert run(watcher, frames) == []


def test_taking_a_known_item_is_checked(store):
    item = store.record_put_down("wallet", list(map(float, WALLET)), "arm of the couch", COL, "stay_0", 500.0)
    watcher = ItemWatcher(store=store)
    frames = [(with_wallet(room()), [])] * 4
    frames += [(person(with_wallet(room()), PERSON), [track(PERSON, "Sarah", "stay_9")])] * 6
    frames += [(person(room(), PERSON), [track(PERSON, "Sarah", "stay_9")])] * 4
    frames += [(room(), [])] * 14
    events = run(watcher, frames)
    assert [(e.kind, e.item_id, e.mover) for e in events] == [("check", item["id"], "Sarah")]


def still_2560():
    return cv2.imencode(".jpg", cv2.resize(with_wallet(room()), (2560, 1920)))[1].tobytes()


def event(kind="look", **kw):
    return ItemEvent(kind, [100.0, 380.0, 40.0, 16.0], 1500.0, kw.pop("mover", COL), kw.pop("stay", "stay_1"),
                     frame=with_wallet(room()), **kw)


def test_a_named_item_is_recorded_with_its_photo(store):
    asked = []

    def ask(prompt, images):
        asked.append((prompt, [i.shape for i in images]))
        return {"what": "black leather wallet", "kind": "item", "on": "arm of the couch"}

    watcher = ItemWatcher(store=store, snapshot=still_2560, ask=ask)
    item = watcher.handle(event())
    assert item["kind"] == "wallet" and item["place"] == "arm of the couch" and item["description"] == "black leather wallet"
    assert "red box" in asked[0][0]
    close, context = asked[0][1]
    assert max(close[:2]) >= 256          # the spot alone, enlarged
    assert context[0] >= 400              # the spot and its surroundings, from the sharp still
    photo = store.get(item["id"])["last_seen_image_path"]
    assert photo and cv2.imread(photo) is not None


def test_nothing_there_is_ignored(store):
    for answer in ({"what": None, "kind": "nothing"}, {"what": "cushion", "kind": "item", "on": "couch"},
                   {"what": "feet", "kind": "person", "on": "pillow"}, {"what": "glasses", "kind": "person"},
                   {"what": "pillow", "kind": "furniture"}, {}):
        watcher = ItemWatcher(store=store, snapshot=still_2560, ask=lambda p, i, a=answer: a)
        assert watcher.handle(event()) is None, answer
    assert store.find("wallet") == [] and store.find("glasses") == [] and store.unnamed_items() == []


def test_an_unclear_item_is_kept_to_ask_about(store):
    watcher = ItemWatcher(store=store, snapshot=still_2560, ask=lambda p, i: {"what": None, "kind": "item", "on": "couch"})
    item = watcher.handle(event())
    assert item["kind"] == UNNAMED and store.unnamed_items()[0]["id"] == item["id"]
    assert store.photo_path(item["id"], "unnamed").exists()


@pytest.fixture(autouse=True)
def _no_recheck_wait(monkeypatch):
    import archer.observer.item_watcher as iw

    monkeypatch.setattr(iw, "RECHECK_SECONDS", 0.0)


def test_picked_up_then_carried_out_the_door(store):
    item = store.record_put_down("remote", [100.0, 380.0, 40.0, 16.0], "arm of the couch", COL, "stay_0", 500.0)
    notes = []
    watcher = ItemWatcher(store=store, snapshot=still_2560, ask=lambda p, i: {"present": False, "what": None},
                          notify=notes.append)
    watcher.handle(event("check", mover="Person_4", stay="stay_p4", item_id=item["id"], item_kind="remote"))
    assert store.get(item["id"])["status"] == "carried"
    assert notes and notes[0].startswith("Person_4 picked up the remote")
    door = [10.0, 250.0, 60.0, 170.0]
    watcher.handle(ItemEvent("leaving", door, 1600.0, "Person_4", "stay_p4"))
    left = watcher.handle(ItemEvent("left", door, 1601.0, "Person_4", "stay_p4"))
    assert [r["id"] for r in left] == [item["id"]]
    found = store.get(item["id"])
    assert found["status"] == "left" and found["image_path"] and cv2.imread(found["image_path"]) is not None


def test_a_check_that_finds_the_item_still_there_changes_nothing(store):
    item = store.record_put_down("phone", [100.0, 380.0, 40.0, 16.0], "arm of the couch", COL, "stay_0", 500.0)
    watcher = ItemWatcher(store=store, snapshot=still_2560, ask=lambda p, i: {"present": True})
    result = watcher.handle(event("check", item_id=item["id"], item_kind="phone"))
    assert result["moved"] is False and len(store.history(item["id"])) == 1


def test_leaving_events_come_from_the_tracker_at_a_door(store):
    store.record_put_down("remote", [100.0, 380.0, 40.0, 16.0], "arm of the couch", COL, "stay_0", 500.0)
    store.record_picked_up([100.0, 380.0, 40.0, 16.0], "Person_4", "stay_p4", 600.0)
    at_door = lambda box, centroid, shape: box[0] <= 65  # noqa: E731
    watcher = ItemWatcher(store=store, is_at_exit=at_door)
    door = (10, 250, 60, 170)
    events = run(watcher, [(room(), [])] + [(room(), [track(door, "Person_4", "stay_p4")])] * 3 + [(room(), [])])
    kinds = [e.kind for e in events]
    events = []
    while not watcher._events.empty():
        events.append(watcher._events.get_nowait())
    assert [e.kind for e in events] == ["leaving", "left"]
    assert kinds == []  # observe() returns only spots to look at


def test_the_observer_runs_the_watcher_beside_the_tracker():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "src" / "archer" / "observer" / "pipeline.py").read_text(encoding="utf-8")
    loop = text[text.index("def _tracker_loop"):text.index("def _item_snapshot")]
    assert loop.index("self._person_tracker.update(") < loop.index("self._item_watcher.observe(")
    assert "self._item_watcher.start()" in text and "self._item_watcher.stop()" in text
    assert 'category="items"' in text and "mark_interventions_delivered([row_id])" in text


def test_the_observer_pipeline_builds_a_watcher(tmp_path, monkeypatch):
    from archer.config import ArcherConfig

    assert ArcherConfig.model_fields["items_watch"].default is True


# --- What Col says about items (agents/item_talk.py) ------------------------------------------

from archer.agents.item_talk import ItemTalk  # noqa: E402


def talk(store, frame=None, description=None):
    shown = []
    t = ItemTalk(
        store=store,
        get_frame=lambda: (frame, 1.0),
        describe=lambda kind, f: description,
        show_photo=lambda b64, title: shown.append(title),
    )
    return t, shown


def test_where_is_my_wallet(store):
    item = store.record_put_down("wallet", COUCH_ARM, "arm of the couch", COL, "s", time.time() - 60)
    store.photo_path(item["id"], "last_seen").write_bytes(cv2.imencode(".jpg", room())[1].tobytes())
    store.set_last_seen_photo(item["id"], str(store.photo_path(item["id"], "last_seen")))
    t, shown = talk(store)
    for question in ("Where's my wallet?", "Hey ARCHER, where did I put my wallet?", "Have you seen my wallet?",
                     "When did I last have my wallet?", "where is the wallet"):
        answer = t.handle(question)
        assert answer and answer.startswith("The wallet is on the arm of the couch. You put it there at"), question
    assert shown and shown[0].startswith("Last seen: wallet")


def test_where_never_invents(store):
    t, _ = talk(store)
    assert t.handle("Where are my keys?") == "I haven't seen your keys yet."
    assert t.handle("Where is the capital of France?") is None  # not an item: the model answers
    assert t.handle("Where's my brother?") is None


def test_teaching_an_item(store):
    frame = room()
    t, _ = talk(store, frame=frame, description="black leather bifold wallet")
    reply = t.handle("ARCHER, this is my wallet.")
    assert reply == "Got it: your wallet, the black leather bifold wallet. I'll keep track of where it goes."
    item = store.find("wallet")[0]
    assert item["owner"] == COL and item["description"] == "black leather bifold wallet"
    assert item["reference_image_path"] and cv2.imread(item["reference_image_path"]) is not None


def test_teaching_without_a_camera(store):
    t, _ = talk(store, frame=None)
    assert "couldn't see it on the camera" in t.handle("These are my keys")
    assert store.find("keys")[0]["owner"] == COL


def test_people_are_not_items(store):
    t, _ = talk(store, frame=room(), description="x")
    for text in ("This is my brother Mike", "This is my friend", "this is my favorite song"):
        assert t.handle(text) is None, text
    assert store.find("mike") == []


def test_forget_an_item(store):
    store.record_put_down("remote", COUCH_ARM, "arm of the couch", COL, "s", 1000.0)
    t, _ = talk(store)
    assert t.handle("Forget my remote") == "Done. I've forgotten your remote, its photos and where it's been."
    assert store.find("remote") == []
    assert t.handle("Forget the meeting") is None


def test_renaming_the_spot_just_mentioned(store):
    item = store.record_put_down("phone", COUCH_ARM, "arm of the couch", COL, "s", time.time())
    t, _ = talk(store)
    assert t.handle("Call that spot the couch arm") is None  # nothing mentioned yet
    t.handle("Where's my phone?")
    assert t.handle("Call that spot the couch arm") == "Got it. I'll call that spot the couch arm from now on."
    assert store.get(item["id"])["place"] == "couch arm"


def test_moves_by_others_are_mentioned_once(store):
    store.record_put_down("wallet", COUCH_ARM, "arm of the couch", COL, "s", 1000.0)
    store.record_picked_up(COUCH_ARM, "Sarah", "s2", 2000.0)
    store.record_put_down("wallet", COUNTER, "kitchen counter", "Sarah", "s2", 2100.0)
    t, _ = talk(store)
    note = t.items_note()
    assert "Sarah picked up the wallet" in note and "Sarah moved the wallet from the arm of the couch to the kitchen counter" in note
    assert t.items_note() == ""  # told once


def test_asking_about_an_unnamed_item_and_the_answer(store):
    item = store.record_unnamed(COUCH_ARM, "arm of the couch", COL, "s", time.time() - 120)
    store.photo_path(item["id"], "unnamed").write_bytes(b"jpg")
    t, shown = talk(store)
    note = t.items_note()
    assert "couldn't identify, on the arm of the couch" in note and "Don't guess" in note
    assert t.items_note() == ""  # one question at a time
    assert t.handle("It's my sunglasses") == "Thanks. I'll remember that's your sunglasses. It's on the arm of the couch."
    named = store.get(item["id"])
    assert named["kind"] == "sunglasses" and named["owner"] == COL
    assert not store.photo_path(item["id"], "unnamed").exists()


def test_an_unnamed_item_can_be_dropped(store):
    item = store.record_unnamed(COUCH_ARM, "arm of the couch", COL, "s", time.time())
    t, _ = talk(store)
    t.items_note()
    assert t.handle("No idea, ignore it") == "No problem. I've dropped it and deleted its photo."
    assert store.get(item["id"]) is None


def test_core_agent_routes_item_talk_and_the_model_has_a_tool():
    from pathlib import Path

    from archer.skills.skills_registry import get_all_tools_ollama_format, get_tool_category

    text = (Path(__file__).resolve().parents[1] / "src" / "archer" / "agents" / "core_agent.py").read_text(encoding="utf-8")
    assert "item_reply = self._item_talk.handle(text)" in text and "self._item_talk.items_note()" in text
    names = [t["function"]["name"] for t in get_all_tools_ollama_format()]
    assert "find_item" in names and get_tool_category("find_item") == "inventory"


def test_find_item_tool(store, monkeypatch):
    import archer.memory.item_store as item_store
    from archer.skills.tool_executor import UniversalToolExecutor

    store.record_put_down("remote", COUCH_ARM, "arm of the couch", COL, "s", time.time())
    monkeypatch.setattr(item_store, "ItemStore", lambda: store)
    executor = UniversalToolExecutor.__new__(UniversalToolExecutor)
    out = executor._exec_inventory_tool("find_item", {"name": "TV remote"})
    assert out["result"].startswith("The remote is on the arm of the couch.")


def test_photos_live_beside_the_database(tmp_path):
    s = ItemStore(db_path=str(tmp_path / "db" / "archer.db") if (tmp_path / "db").mkdir() is None else None)
    assert s.photos_dir == tmp_path / "db" / "items"
    ItemStore(db_path=str(tmp_path / "db" / "archer.db"))  # set up twice: no duplicate-column error


def test_a_room_first_seen_with_someone_in_it(store):
    """The background's first frame had Col in front of a table; the table isn't a change once he moves."""
    watcher = ItemWatcher(store=store)
    hidden = (90, 360, 80, 60)                                                  # Col covers this patch at first
    first = person(with_wallet(room()), hidden)
    frames = [(first, [track(hidden)])] * 4 + [(with_wallet(room()), [])] * 16
    assert run(watcher, frames) == []


def test_people_are_blurred_in_item_photos():
    from archer.observer.item_watcher import _blur_people

    img = np.zeros((480, 640, 3), np.uint8)
    img[::2, ::2] = 255  # sharp checkerboard everywhere
    out = _blur_people(img, [[300, 100, 100, 200]], [100, 380, 40, 16])
    assert out[200, 350].std() < img[190:210, 340:360].std()      # inside the person: blurred
    assert np.array_equal(out[380:396, 100:140], img[380:396, 100:140])  # the item spot: untouched
    assert np.array_equal(_blur_people(img, [[90, 360, 80, 60]], [100, 380, 40, 16]), img)  # covers the spot: left alone


def test_a_pick_up_is_confirmed_by_a_second_look(store):
    item = store.record_put_down("bottle", [100.0, 380.0, 40.0, 16.0], "side table", COL, "stay_0", 500.0)
    answers = iter([{"present": False}, {"present": True}])
    watcher = ItemWatcher(store=store, snapshot=still_2560, ask=lambda p, i: next(answers))
    assert watcher.handle(event("check", mover="Person_3", item_id=item["id"], item_kind="bottle")) == {"still_there": item["id"]}
    assert store.get(item["id"])["status"] == "placed"


def test_taught_items_are_named_by_their_description(store):
    store.teach("wallet", COL, "blue patterned fabric wallet")
    prompts = []
    watcher = ItemWatcher(store=store, snapshot=still_2560,
                          ask=lambda p, i: prompts.append(p) or {"what": "wallet", "kind": "item", "on": "table"})
    item = watcher.handle(event())
    assert "blue patterned fabric wallet (his wallet)" in prompts[0]
    assert item["owner"] == COL and item["kind"] == "wallet"


def test_no_photo_when_the_item_has_not_been_seen(store, tmp_path):
    item_id = store.teach("wallet", COL, "blue patterned fabric wallet")
    ref = store.photo_path(item_id, "reference")
    ref.write_bytes(cv2.imencode(".jpg", room())[1].tobytes())
    store.teach("wallet", COL, None, reference_image_path=str(ref))
    t, shown = talk(store)
    assert t.handle("Where did I put my wallet?") == "I haven't seen your wallet yet."
    assert shown == []
