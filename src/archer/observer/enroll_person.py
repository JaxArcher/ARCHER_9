"""
ARCHER Person Enrollment Script.

Captures face embeddings from a frame or image file and stores them into the
`known_persons` database table as a named profile (default: "Col").
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path
import cv2
import numpy as np
from loguru import logger

from archer.memory.sqlite_store import get_sqlite_store
from archer.observer.person_id import PersonIdentifier
from archer.observer.camera import WebcamCapture


def enroll_from_webcam(name: str = "Col", num_frames: int = 5) -> bool:
    """Capture frames from webcam and enroll average face embedding for named user."""
    logger.info(f"Starting face enrollment for '{name}' using webcam...")
    camera = WebcamCapture()
    if not camera.start():
        logger.error("Webcam unavailable for face enrollment.")
        return False

    identifier = PersonIdentifier()
    if not identifier.is_available:
        logger.error("InsightFace is unavailable. Check model installation.")
        camera.stop()
        return False

    embeddings = []
    captured = 0
    start_time = sys.maxsize

    try:
        logger.info("Look at the camera from slightly different angles...")
        for _ in range(50):
            frame, _ = camera.get_latest_frame()
            if frame is not None:
                emb = identifier.get_embedding(frame)
                if emb is not None:
                    embeddings.append(emb)
                    captured += 1
                    logger.info(f"Captured face frame {captured}/{num_frames}")
                    if captured >= num_frames:
                        break
            import time
            time.sleep(0.3)
    finally:
        camera.stop()

    if not embeddings:
        logger.error("No valid face embeddings detected during capture.")
        return False

    avg_embedding = np.mean(embeddings, axis=0, dtype=np.float32)
    norm = np.linalg.norm(avg_embedding)
    if norm > 0:
        avg_embedding = avg_embedding / norm

    store = get_sqlite_store()
    store.add_known_person(name=name, embedding=avg_embedding.tobytes())
    logger.info(f"Successfully enrolled '{name}' with {captured} face samples!")
    return True


def enroll_from_image(image_path: str, name: str = "Col") -> bool:
    """Enroll face embedding from an image file."""
    path = Path(image_path)
    if not path.exists():
        logger.error(f"Image path does not exist: {image_path}")
        return False

    frame = cv2.imread(str(path))
    if frame is None:
        logger.error(f"Failed to read image file: {image_path}")
        return False

    identifier = PersonIdentifier()
    if not identifier.is_available:
        logger.error("InsightFace is unavailable.")
        return False

    emb = identifier.get_embedding(frame)
    if emb is None:
        logger.error("No face detected in provided image.")
        return False

    store = get_sqlite_store()
    store.add_known_person(name=name, embedding=emb.tobytes())
    logger.info(f"Successfully enrolled '{name}' from image '{image_path}'!")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Enroll a person into ARCHER's face recognition database.")
    parser.add_argument("--name", type=str, default="Col", help="Person name to enroll (default: Col)")
    parser.add_argument("--image", type=str, default=None, help="Path to image file (if not using webcam)")
    args = parser.parse_args()

    if args.image:
        success = enroll_from_image(args.image, name=args.name)
    else:
        success = enroll_from_webcam(name=args.name)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
