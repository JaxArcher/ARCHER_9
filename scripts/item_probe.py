"""
ARCHER Phase 2d audit: what can the room camera make out, and which local
model can name the things people pick up and put down? (Claude, 2026-10-20)

Run by Col from D:\\ARCHER_9 in a normal PowerShell window:

    .venv\\Scripts\\python.exe scripts\\item_probe.py
    .venv\\Scripts\\python.exe scripts\\item_probe.py --hold "TV remote"

The first form looks at the room as it is. With --hold, sit where the camera
sees you, holding the item named, and the probe also asks what's in your hands.

For each check it prints what was found and how long it took:
  1. A full-resolution still from the room camera (the main stream), and its size.
  2. The observer's own detector (YOLOX-Nano, 80 everyday kinds of object
     such as phone, remote, cup, bottle, book, laptop) run over the still in
     tiles, on the CPU.
  3. ARCHER's own vision model (gemma4, on the GPU, already loaded) asked to
     list the small items it can see and where they are, and, with --hold,
     what the person is holding.
  4. The observer's scene model (moondream, on the CPU) asked the same.

Nothing is saved unless you add --save: the still stays in memory and the
answers appear only in this window. The camera address and password are never
printed. Uses the same model settings as ARCHER, so Ollama doesn't reload
anything.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

import cv2  # noqa: E402
import httpx  # noqa: E402
import numpy as np  # noqa: E402

from archer.config import get_config  # noqa: E402
from archer.integrations.ollama_settings import main_model_request  # noqa: E402
from archer.observer.person_detector import APPROVED_MODEL_PATH, _generate_yolox_grids_and_strides  # noqa: E402

# COCO's 80 classes, in YOLOX's order.
COCO = (
    "person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant stop_sign "
    "parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella handbag "
    "tie suitcase frisbee skis snowboard sports_ball kite baseball_bat baseball_glove skateboard surfboard "
    "tennis_racket bottle wine_glass cup fork knife spoon bowl banana apple sandwich orange broccoli carrot "
    "hot_dog pizza donut cake chair couch potted_plant bed dining_table toilet tv laptop mouse remote "
    "keyboard cell_phone microwave oven toaster sink refrigerator book clock vase scissors teddy_bear "
    "hair_drier toothbrush"
).split()
# Furniture and fixtures aren't "things that get moved".
NOT_ITEMS = {"person", "chair", "couch", "bed", "dining_table", "toilet", "tv", "sink", "refrigerator",
             "oven", "microwave", "potted_plant", "bench"}

ROOM_PROMPT = (
    "This is a still from a camera in a living room. List the small, movable everyday items you can "
    "actually see (for example a phone, TV remote, keys, wallet, glasses, mug, cup, bottle, book, "
    "headphones). One per line, as: item - where it is (the furniture or spot). Don't list furniture, "
    "and don't guess: if you can't tell what something is, say 'unclear object - where it is'."
)
HANDS_PROMPT = (
    "This is a close crop of a person from a room camera. What is the person holding in their hands, "
    "if anything? Answer with just the item's name, or 'nothing', or 'unclear' if you can't tell."
)


def camera_login():
    from urllib.parse import unquote, urlparse

    url = get_config().network_camera_url
    if not url:
        sys.exit("No room camera is set up (ARCHER_NETWORK_CAMERA_URL is empty).")
    parsed = urlparse(url)
    return parsed.hostname, unquote(parsed.username or ""), unquote(parsed.password or "")


async def _snapshot() -> bytes:
    from reolink_aio.api import Host

    host, user, password = camera_login()
    client = Host(host, username=user, password=password, use_https=None)
    try:
        await asyncio.wait_for(client.get_host_data(), timeout=30.0)
        data = await asyncio.wait_for(client.get_snapshot(0, stream="main"), timeout=15.0)
        if not data:
            raise RuntimeError("the camera returned no picture")
        return data
    finally:
        try:
            await client.logout()
        except Exception:
            pass


def snapshot() -> np.ndarray:
    data = asyncio.run(_snapshot())
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("the camera's picture couldn't be read")
    return image


class Detector:
    """YOLOX-Nano (the observer's model) for all 80 classes, run on tiles of a large still."""

    def __init__(self, size: int = 416, conf: float = 0.30):
        import onnxruntime as ort

        self.size = size
        self.conf = conf
        self.session = ort.InferenceSession(str(ROOT / APPROVED_MODEL_PATH), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.grids, self.strides = _generate_yolox_grids_and_strides((size, size))

    def _detect(self, tile: np.ndarray):
        h, w = tile.shape[:2]
        r = min(self.size / h, self.size / w)
        resized = cv2.resize(tile, (int(w * r), int(h * r)))
        padded = np.full((self.size, self.size, 3), 114, dtype=np.uint8)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        out = self.session.run(None, {self.input_name: padded.transpose(2, 0, 1)[None].astype(np.float32)})[0][0]
        scores = out[:, 4:5] * out[:, 5:]
        cls = scores.argmax(1)
        best = scores.max(1)
        keep = best > self.conf
        boxes = out[keep, :4].copy()
        boxes[:, :2] = (boxes[:, :2] + self.grids[keep]) * self.strides[keep]
        boxes[:, 2:4] = np.exp(boxes[:, 2:4]) * self.strides[keep]
        found = []
        for (cx, cy, bw, bh), c, s in zip(boxes, cls[keep], best[keep]):
            found.append((COCO[int(c)], float(s), ((cx - bw / 2) / r, (cy - bh / 2) / r, bw / r, bh / r)))
        return found

    def detect(self, image: np.ndarray, tile: int = 960, overlap: int = 160):
        h, w = image.shape[:2]
        step = tile - overlap
        found = []
        for y0 in range(0, max(h - overlap, 1), step):
            for x0 in range(0, max(w - overlap, 1), step):
                part = image[y0: y0 + tile, x0: x0 + tile]
                for name, score, (x, y, bw, bh) in self._detect(part):
                    found.append((name, score, [x + x0, y + y0, bw, bh]))
        boxes = [f[2] for f in found]
        keep = cv2.dnn.NMSBoxes(boxes, [f[1] for f in found], self.conf, 0.45) if found else []
        return [found[i] for i in np.array(keep).flatten()] if len(keep) else []


def ask(url: str, model: str, prompt: str, image: np.ndarray, main: bool) -> tuple[str, float]:
    ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    payload = {"model": model, "prompt": prompt, "images": [base64.b64encode(jpg.tobytes()).decode()],
               "stream": False}
    if main:
        payload["think"] = False
        main_model_request(payload, temperature=0.1)
    else:
        payload["options"] = {"num_gpu": 0, "num_predict": 200, "repeat_penalty": 1.15}
    start = time.monotonic()
    resp = httpx.post(f"{url}/api/generate", json=payload, timeout=180.0)
    resp.raise_for_status()
    return resp.json().get("response", "").strip(), time.monotonic() - start


def fit(image: np.ndarray, longest: int) -> np.ndarray:
    h, w = image.shape[:2]
    scale = longest / max(h, w)
    return cv2.resize(image, (int(w * scale), int(h * scale))) if scale < 1 else image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hold", metavar="ITEM", help="you're in view holding this item; also ask what's in your hands")
    parser.add_argument("--save", metavar="FOLDER", help="also save the still and crops there (off by default)")
    parser.add_argument("--no-moondream", action="store_true", help="skip the CPU scene model (it's slow)")
    args = parser.parse_args()
    config = get_config()

    print("1. Room camera still (main stream)")
    t = time.monotonic()
    try:
        image = snapshot()
    except Exception as e:
        print(f"   Couldn't get a still: {type(e).__name__}: {e}")
        return 1
    h, w = image.shape[:2]
    print(f"   {w}x{h} in {time.monotonic() - t:.1f} s (the observer's stream is 640x480).")
    if args.save:
        Path(args.save).mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(Path(args.save) / "room.jpg"), image)

    print("\n2. The observer's detector (YOLOX-Nano, 80 kinds of everyday object), CPU")
    t = time.monotonic()
    found = Detector().detect(image)
    took = time.monotonic() - t
    people = [f for f in found if f[0] == "person"]
    items = [f for f in found if f[0] not in NOT_ITEMS]
    print(f"   {took:.1f} s for the whole still in tiles. People: {len(people)}.")
    for name, score, (x, y, bw, bh) in sorted(items, key=lambda f: -f[1]):
        print(f"   {name:<12} {score:.2f}  at x={int(x)}, y={int(y)}, {int(bw)}x{int(bh)} px")
    if not items:
        print("   No movable items found.")

    print(f"\n3. ARCHER's vision model ({config.core_primary_model}), GPU")
    try:
        answer, took = ask(config.ollama_base_url, config.core_primary_model, ROOM_PROMPT, fit(image, 1600), True)
        print(f"   Whole room ({took:.1f} s):")
        for line in answer.splitlines():
            print(f"     {line}")
        for i, (_, _, (x, y, bw, bh)) in enumerate(people if args.hold else [], start=1):
            pad = 0.15
            x0, y0 = max(0, int(x - bw * pad)), max(0, int(y - bh * pad))
            x1, y1 = min(w, int(x + bw * (1 + pad))), min(h, int(y + bh * (1 + pad)))
            crop = image[y0:y1, x0:x1]
            if args.save:
                cv2.imwrite(str(Path(args.save) / f"person_{i}.jpg"), crop)
            answer, took = ask(config.ollama_base_url, config.core_primary_model, HANDS_PROMPT, crop, True)
            print(f"   Person {i}, {crop.shape[1]}x{crop.shape[0]} px crop ({took:.1f} s): {answer}"
                  f"   [you said: {args.hold}]")
        if args.hold and not people:
            print("   No one was detected, so the hands check was skipped.")
    except Exception as e:
        print(f"   Failed: {type(e).__name__}: {e}")

    if not args.no_moondream:
        print(f"\n4. The observer's scene model ({config.observer_model}), CPU")
        try:
            answer, took = ask(config.observer_ollama_url, config.observer_model, ROOM_PROMPT, fit(image, 1024), False)
            print(f"   Whole room ({took:.1f} s):")
            for line in answer.splitlines():
                print(f"     {line}")
        except Exception as e:
            print(f"   Failed: {type(e).__name__}: {e}")

    print("\nDone. Nothing was saved" + (f" except the stills in {args.save}." if args.save else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
