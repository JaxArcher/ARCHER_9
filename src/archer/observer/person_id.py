"""
ARCHER Person Identification Module (InsightFace).

Detects faces in video frames, computes facial embeddings, and matches
them against enrolled known persons ("Col") or previously-seen unrecognized
visitors ("Person_N").
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.memory.sqlite_store import get_sqlite_store


def _cosine_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Compute cosine similarity between two 1D embedding vectors."""
    norm1 = np.linalg.norm(emb1)
    norm2 = np.linalg.norm(emb2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(emb1, emb2) / (norm1 * norm2))


class PersonIdentifier:
    """
    Person Identification engine using InsightFace.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.55,
        snapshots_dir: str | Path = "data/snapshots",
    ) -> None:
        self._config = get_config()
        self._threshold = similarity_threshold
        self._snapshots_dir = Path(snapshots_dir)
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

        self._app = None
        self._available = True
        self._init_insightface()

    def _init_insightface(self) -> None:
        """Initialize InsightFace FaceAnalysis engine."""
        try:
            from insightface.app import FaceAnalysis

            # Use buffalo_l or default lightweight model, CPU execution mode
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=0, det_size=(640, 640))
            self._app = app
            logger.info("InsightFace PersonIdentifier initialized successfully.")
        except Exception as e:
            logger.warning(f"InsightFace initialization fallback/failed: {e}")
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._app is not None

    def get_embedding(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Extract primary face embedding vector from a frame."""
        if not self.is_available or frame is None:
            return None

        try:
            faces = self._app.get(frame)
            if not faces:
                return None
            # Return embedding of largest face
            largest_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            return np.array(largest_face.embedding, dtype=np.float32)
        except Exception as e:
            logger.debug(f"Face embedding extraction failed: {e}")
            return None

    def identify_persons(
        self,
        frame: np.ndarray,
        camera_source: str = "webcam",
    ) -> List[dict[str, Any]]:
        """
        Detect and identify all faces in frame.

        Returns list of detection dicts:
        [
            {
                "person_id": "Col" or "Person_2",
                "is_known": True/False,
                "confidence": 0.92,
                "box": [x, y, w, h],
                "snapshot_path": "data/snapshots/..."
            }
        ]
        """
        if not self.is_available or frame is None:
            return []

        store = get_sqlite_store()
        try:
            import cv2

            faces = self._app.get(frame)
            if not faces:
                return []

            known_persons = store.get_known_persons()
            known_embeddings: List[Tuple[str, np.ndarray]] = []
            for kp in known_persons:
                if kp.get("embedding"):
                    emb = np.frombuffer(kp["embedding"], dtype=np.float32)
                    known_embeddings.append((kp["name"], emb))

            # Retrieve past unknown sightings with stored embeddings
            past_sightings = store.get_person_sightings(limit=200)
            unknown_embeddings: List[Tuple[str, np.ndarray]] = []
            seen_unknown_ids = set()
            for ps in past_sightings:
                pid = ps.get("person_id", "")
                if not ps.get("is_known") and ps.get("embedding"):
                    emb = np.frombuffer(ps["embedding"], dtype=np.float32)
                    unknown_embeddings.append((pid, emb))
                if pid:
                    seen_unknown_ids.add(pid)

            results: List[dict[str, Any]] = []

            for face in faces:
                bbox = [int(v) for v in face.bbox]  # [x1, y1, x2, y2]
                x, y, w, h = bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]
                emb = np.array(face.embedding, dtype=np.float32)
                det_conf = float(face.det_score) if hasattr(face, "det_score") else 0.90

                matched_name: Optional[str] = None
                best_sim = 0.0

                # 1. Match against known persons (e.g. Col)
                for name, k_emb in known_embeddings:
                    sim = _cosine_similarity(emb, k_emb)
                    if sim > best_sim:
                        best_sim = sim
                        if sim >= self._threshold:
                            matched_name = name

                is_known = False
                person_id = ""

                if matched_name:
                    is_known = True
                    person_id = matched_name
                else:
                    # 2. Match against previously seen unknown visitors
                    best_u_sim = 0.0
                    matched_u_id: Optional[str] = None
                    for u_id, u_emb in unknown_embeddings:
                        sim = _cosine_similarity(emb, u_emb)
                        if sim > best_u_sim:
                            best_u_sim = sim
                            if sim >= self._threshold:
                                matched_u_id = u_id

                    if matched_u_id:
                        person_id = matched_u_id
                    else:
                        # 3. New unrecognized visitor -> Person_N
                        next_num = len([p for p in seen_unknown_ids if p.startswith("Person_")]) + 2
                        person_id = f"Person_{next_num}"
                        seen_unknown_ids.add(person_id)

                # Save snapshot for unrecognized visitors or first sightings
                snapshot_path = None
                if not is_known:
                    timestamp_str = int(time.time())
                    filename = f"{timestamp_str}_{person_id}.jpg"
                    filepath = self._snapshots_dir / filename
                    try:
                        cv2.imwrite(str(filepath), frame)
                        snapshot_path = str(filepath)
                    except Exception as e:
                        logger.warning(f"Failed to save snapshot for {person_id}: {e}")

                # Log sighting to SQLite with embedding BLOB
                emb_bytes = emb.tobytes()
                store.log_person_sighting(
                    person_id=person_id,
                    is_known=is_known,
                    confidence=best_sim if is_known else det_conf,
                    embedding=emb_bytes,
                    snapshot_path=snapshot_path,
                    camera_source=camera_source,
                )

                # Queue unrecognized faces for later naming (2026-09-16,
                # Col's call: no manual enrollment step for anyone but
                # himself). Upserts by person_id so a recurring stranger
                # bumps one row's sighting_count instead of piling up
                # duplicates -- see the pending_person_confirmations schema
                # comment in sqlite_store.py. Best-effort: a hiccup here
                # shouldn't break identification itself.
                if not is_known:
                    try:
                        store.upsert_pending_person_confirmation(
                            person_id=person_id,
                            embedding=emb_bytes,
                            snapshot_path=snapshot_path,
                        )
                    except Exception as e:
                        logger.debug(f"Pending person-confirmation upsert failed (non-fatal): {e}")

                results.append({
                    "person_id": person_id,
                    "is_known": is_known,
                    "confidence": best_sim if is_known else det_conf,
                    "box": [x, y, w, h],
                    "snapshot_path": snapshot_path,
                    # Raw embedding BLOB -- not persisted anywhere new by
                    # this addition (it's already stored via
                    # log_person_sighting above), just also handed back to
                    # the caller so CoreAgent._check_person_introduction can
                    # bind a live "this is Sarah" to THIS exact face without
                    # a second InsightFace pass or a re-query.
                    "embedding": emb_bytes,
                })

            return results
        except Exception as e:
            logger.error(f"Person identification error: {e}")
            return []
