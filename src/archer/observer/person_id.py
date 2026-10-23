"""
ARCHER Person Identification Module (InsightFace).

Detects faces in video frames, computes facial embeddings, and matches
them against enrolled known persons ("Col") or previously-seen unrecognized
visitors ("Person_N").
"""

from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.memory.sqlite_store import SQLiteStore, get_sqlite_store


# Detection size for sharp still crops (face plus its own size on each side); see
# PersonIdentifier._faces_in_still.
_STILL_DETECTION_SIZE = (192, 192)


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
        db_path: Optional[str | Path] = None,
    ) -> None:
        self._config = get_config()
        self._threshold = similarity_threshold
        self._snapshots_dir = Path(snapshots_dir)
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path) if db_path else "data/archer.db"

        self._static_face_history: List[Tuple[float, float, float]] = []  # (cx, cy, ts)
        self._app = None
        self._available = True
        self._init_insightface()

    def _init_insightface(self) -> None:
        """Initialize InsightFace FaceAnalysis engine."""
        try:
            import onnxruntime as ort
            from insightface.app import FaceAnalysis

            # Claude 2026-10-15: CPU cap that actually takes effect. onnxruntime
            # ignores thread counts given as CPU provider options; they must be
            # session settings (verified with onnxruntime 1.28.0 and this
            # InsightFace version: sess_options is passed through to every
            # model's session).
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = 2
            sess_options.inter_op_num_threads = 1
            # Detection + recognition + the 3D landmark model, which supplies
            # face.pose (the turned-away / looking-down check in is_clear_face).
            # Gender/age and 2D landmarks are not used and stay off.
            app = FaceAnalysis(
                name="buffalo_l",
                allowed_modules=["detection", "recognition", "landmark_3d_68"],
                providers=["CPUExecutionProvider"],
                sess_options=sess_options,
            )
            # Full detail: at 320 the room camera's ~50 px faces were missed in
            # about half of the saved room pictures (31 of 67 found vs 65 of 67).
            app.prepare(ctx_id=0, det_size=(640, 640))
            self._app = app
            logger.info("InsightFace PersonIdentifier initialized (detection, recognition, pose; 2 threads per model).")
        except Exception as e:
            logger.warning(f"InsightFace initialization fallback/failed: {e}")
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._app is not None

    def is_static_room_face(self, bbox: list[int] | tuple[int, ...]) -> bool:
        """
        Review 2026-10-13 Addendum Item 1:
        Remove the 'never moves' filter. Take out both the hard-coded shelf zone and
        the position history. ARCHER doesn't need its own way to spot decor; Col tells it instead.
        """
        return False

    def is_decor_face(self, emb: np.ndarray, store: Any = None) -> bool:
        """
        Check if a face embedding matches an entity marked as decor / not a person.
        Spec 5b & Review Addendum 13:05:
        ARCHER skips a decor face everywhere: when choosing a person's face, naming,
        re-checks and labels.
        """
        if emb is None:
            return False
        if store is None:
            store = get_sqlite_store()
        try:
            decor_embs = store.get_decor_embeddings()
            for d_bytes in decor_embs:
                d_emb = np.frombuffer(d_bytes, dtype=np.float32)
                sim = _cosine_similarity(emb, d_emb)
                if sim >= 0.50:
                    return True
        except Exception as e:
            logger.debug(f"Failed checking decor face: {e}")
        return False


    def is_clear_face(self, face: Any, frame_crop: Optional[np.ndarray] = None) -> Tuple[bool, str]:
        """
        Check whether a detected face meets the clarity criteria.
        Spec 5b & Review 23:55 Item 3:
        'A face that is turned away, looking down, blurry or too dark gives an unreliable match:
        Col's own head, turned away, has scored 0.07 against his references (Person_55),
        and looking down it scored 0.19 (Person_82). Such a face never names a stay,
        splits one, starts a waiting label or gets learned. Inside a stay, it belongs to the stay's person.'
        """
        # 1. Pose angles: pitch (looking down/up) and yaw (turned sideways) must be <= 30 deg.
        # Spec 5b (2026-10-14): the turn is measured, never assumed -- a face whose
        # turn can't be measured doesn't count as clear.
        pose = getattr(face, "pose", None)
        if pose is None or len(pose) < 2:
            return False, "turn not measured (no pose)"
        pitch = float(pose[0])
        yaw = float(pose[1])
        if abs(pitch) > 30.0:
            return False, f"pitch angle {pitch:.1f} > 30 deg (turned away / looking down)"
        if abs(yaw) > 30.0:
            return False, f"yaw angle {yaw:.1f} > 30 deg (turned away)"

        # 2. Detector confidence score
        det_score = float(getattr(face, "det_score", 1.0))
        if det_score < 0.55:
            return False, f"low detector confidence ({det_score:.2f} < 0.55)"

        # 3. Image clarity (blurriness and illumination)
        if frame_crop is not None and frame_crop.size > 0:
            import cv2
            gray = cv2.cvtColor(frame_crop, cv2.COLOR_BGR2GRAY) if len(frame_crop.shape) == 3 else frame_crop
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            if lap_var < 50.0:
                return False, f"blurry face (Laplacian var {lap_var:.1f} < 50.0)"
            brightness = float(gray.mean())
            if brightness < 35.0:
                return False, f"dark face (mean brightness {brightness:.1f} < 35.0)"

        return True, "clear"

    def get_similarity_to_col(self, emb: np.ndarray, store: Any = None) -> float:
        """Calculate maximum cosine similarity of an embedding against Col's enrolled references."""
        if emb is None:
            return 0.0
        if store is None:
            store = get_sqlite_store()

        best_sim = 0.0
        try:
            known_persons = store.get_known_persons()
            try:
                known_persons = known_persons + store.get_known_person_references()
            except Exception:
                pass
            for kp in known_persons:
                if kp.get("name") == "Col" and kp.get("embedding"):
                    k_emb = np.frombuffer(kp["embedding"], dtype=np.float32)
                    sim = _cosine_similarity(emb, k_emb)
                    if sim > best_sim:
                        best_sim = sim
        except Exception as e:
            logger.debug(f"Failed calculating similarity to Col: {e}")
        return best_sim

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

    def get_faces(self, frame: np.ndarray, camera_source: str = "network_cam") -> List[Any]:
        """
        Detect and return filtered faces in frame without full database matching.
        Returns face objects with bbox, det_score, and embedding.
        """
        if not self.is_available or frame is None:
            return []
        try:
            faces = self._app.get(frame)
            if not faces:
                return []
            frame_h = frame.shape[0]
            is_room_cam = ("network" in camera_source.lower() or "room" in camera_source.lower() or "rtsp" in camera_source.lower())
            MIN_FACE_HEIGHT_RATIO = 0.06 if is_room_cam else 0.12
            MIN_DET_SCORE = 0.55
            return [
                f for f in faces
                if (f.bbox[3] - f.bbox[1]) >= frame_h * MIN_FACE_HEIGHT_RATIO
                and float(getattr(f, "det_score", 1.0)) >= MIN_DET_SCORE
            ]
        except Exception as e:
            logger.debug(f"Face extraction failed: {e}")
            return []

    def identify_persons(
        self,
        frame: np.ndarray,
        camera_source: str = "webcam",
        store: Any = None,
        stay_id: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """
        Detect and identify all faces in frame.
        """
        if not self.is_available or frame is None:
            return []

        if store is None:
            store = get_sqlite_store()
        try:
            import cv2

            faces = self.get_faces(frame, camera_source=camera_source)
            if not faces:
                return []

            MAX_PLAUSIBLE_FACES = 3
            if len(faces) > MAX_PLAUSIBLE_FACES:
                logger.info(
                    f"Person ID: {len(faces)} faces detected in one frame -- "
                    "likely a screen or photo in the background rather than "
                    "real visitors. Skipping identification for this frame."
                )
                return []

            # Check if this stay is already recognized as Col's
            stay_is_col = False
            if stay_id:
                try:
                    stay_rec = store.get_stay(stay_id)
                    if stay_rec and stay_rec.get("person_id") == "Col" and stay_rec.get("is_known"):
                        stay_is_col = True
                except Exception:
                    pass

            results: List[dict[str, Any]] = []

            for face in faces:
                bbox = [int(v) for v in face.bbox]  # [x1, y1, x2, y2]
                x, y, w, h = bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]

                emb = np.array(face.embedding, dtype=np.float32)

                # Skip decor faces everywhere (Review 2026-10-13 Addendum Items 1 & 2)
                if self.is_decor_face(emb, store=store):
                    logger.debug(f"PersonID: Skipped decor face at {bbox}.")
                    continue

                det_conf = float(face.det_score) if hasattr(face, "det_score") else 0.90
                face_box_json = json.dumps([x, y, w, h])

                # Check clarity (Review 23:55 Item 3)
                is_clear, clarity_reason = self.is_clear_face(face)

                # Similarity against Col
                col_sim = self.get_similarity_to_col(emb, store=store)

                match_res = self.match_face_embedding(emb, store=store)
                is_known = match_res["is_known"]
                person_id = match_res["person_id"]
                best_sim = match_res.get("sim", 0.0)

                should_save = False
                should_create_pending_label = False
                effective_source = camera_source

                if stay_is_col:
                    # Inside a stay already known to be Col's (Review Items 1, 2, 3)
                    # A face that isn't clearly someone else is filed as Col, with no new label and no photo.
                    is_clear_stranger = (
                        is_clear and is_known and person_id != "Col" and best_sim >= self._threshold
                    )
                    if is_clear_stranger:
                        if not is_known:
                            should_save = True
                            should_create_pending_label = True
                    else:
                        person_id = "Col"
                        is_known = True
                        # Review Item 10: Save real similarity score (not forced to 0.50)
                        # and record that it was filed through stay association
                        best_sim = col_sim
                        effective_source = f"{camera_source}:stay_association"
                        should_save = False
                        should_create_pending_label = False
                else:
                    # Not inside a known Col stay
                    if not is_clear:
                        # An unclear face never names a stay, splits one, starts a waiting label, or gets learned.
                        logger.debug(f"PersonID: Face set aside as unclear ({clarity_reason}); no waiting label created.")
                        should_save = False
                        should_create_pending_label = False
                    else:
                        if not is_known:
                            should_save = True
                            should_create_pending_label = True

                # Save snapshot for unrecognized visitors (capped at max 3 photos per face)
                snapshot_path = None
                if should_save:
                    try:
                        if store.count_snapshots_for_person(person_id) >= 3:
                            should_save = False
                    except Exception:
                        pass

                    if should_save:
                        timestamp_str = int(time.time())
                        filename = f"{timestamp_str}_{person_id}.jpg"
                        filepath = self._snapshots_dir / filename
                        try:
                            cv2.imwrite(str(filepath), frame)
                            snapshot_path = str(filepath)
                        except Exception as e:
                            logger.warning(f"Failed to save snapshot for {person_id}: {e}")

                # Log sighting to SQLite with embedding BLOB and exact face_box
                emb_bytes = emb.tobytes()
                sighting_row_id = store.log_person_sighting(
                    person_id=person_id,
                    is_known=is_known,
                    confidence=best_sim if is_known else det_conf,
                    embedding=emb_bytes,
                    snapshot_path=snapshot_path,
                    camera_source=effective_source,
                    face_box=face_box_json,
                    faces_in_frame=len(faces),
                    stay_id=stay_id,
                )


                # Queue unrecognized faces for later naming (with stay_id linked)
                if should_create_pending_label and not is_known:
                    try:
                        store.upsert_pending_person_confirmation(
                            person_id=person_id,
                            embedding=emb_bytes,
                            snapshot_path=snapshot_path,
                            sighting_timestamp=time.time(),
                            face_box=face_box_json,
                            stay_id=stay_id,
                        )
                        if hasattr(store, "create_or_update_person_question"):
                            store.create_or_update_person_question(
                                person_id=person_id,
                                snapshot_path=snapshot_path,
                                timestamp=time.time(),
                            )
                    except Exception as e:
                        logger.debug(f"Pending person-confirmation upsert failed (non-fatal): {e}")

                results.append({
                    "person_id": person_id,
                    "is_known": is_known,
                    "confidence": best_sim if is_known else det_conf,
                    "box": [x, y, w, h],
                    "snapshot_path": snapshot_path,
                    "embedding": emb_bytes,
                    "stay_id": stay_id,
                    "sighting_id": sighting_row_id,
                })

            return results
        except Exception as e:
            logger.error(f"Person identification error: {e}")
            return []

    def match_face_embedding(self, emb: np.ndarray, store: Any = None) -> dict[str, Any]:
        """Match an embedding against known persons and unknown/pending/dismissed face clusters."""
        if store is None:
            store = SQLiteStore(self._db_path)

        known_persons = store.get_known_persons()
        try:
            known_persons = known_persons + store.get_known_person_references()
        except Exception:
            pass

        # Should-fix 9: A decor label must NEVER be a match result!
        decor_ids = set()
        try:
            decor_records = store.get_pending_person_confirmations(status="decor", limit=1000)
            decor_ids = {d["person_id"] for d in decor_records if d.get("person_id")}
        except Exception:
            pass

        best_sim = 0.0
        matched_name = None
        for kp in known_persons:
            name = kp.get("name")
            if name and name in decor_ids:
                continue
            if kp.get("embedding"):
                k_emb = np.frombuffer(kp["embedding"], dtype=np.float32)
                sim = _cosine_similarity(emb, k_emb)
                if sim > best_sim:
                    best_sim = sim
                    if sim >= self._threshold:
                        matched_name = name

        if matched_name and matched_name not in decor_ids:
            return {"person_id": matched_name, "is_known": True, "sim": best_sim}

        unknown_embeddings: List[Tuple[str, np.ndarray]] = []
        try:
            pending_confs = store.get_pending_person_confirmations(status=["pending", "dismissed"], limit=1000)
            for pc in pending_confs:
                pid = pc.get("person_id", "")
                if pid and pid not in decor_ids and pc.get("embedding"):
                    emb_p = np.frombuffer(pc["embedding"], dtype=np.float32)
                    unknown_embeddings.append((pid, emb_p))
        except Exception as e:
            logger.debug(f"Pending confirmations retrieval failed: {e}")

        past_sightings = store.get_person_sightings(limit=200)
        for ps in past_sightings:
            pid = ps.get("person_id", "")
            if pid and pid not in decor_ids and not ps.get("is_known") and ps.get("embedding"):
                emb_s = np.frombuffer(ps["embedding"], dtype=np.float32)
                unknown_embeddings.append((pid, emb_s))

        best_u_sim = 0.0
        matched_u_id = None
        for u_id, u_emb in unknown_embeddings:
            sim = _cosine_similarity(emb, u_emb)
            if sim > best_u_sim:
                best_u_sim = sim
                if sim >= self._threshold:
                    matched_u_id = u_id

        if matched_u_id and matched_u_id not in decor_ids:
            return {"person_id": matched_u_id, "is_known": False, "sim": best_u_sim}

        next_num = store.get_next_person_number()
        return {"person_id": f"Person_{next_num}", "is_known": False, "sim": 0.0}

    _match_face_embedding = match_face_embedding

    def analyze_face_crop(
        self,
        crop: np.ndarray,
        store: Any = None,
        stay_id: Optional[str] = None,
        camera_source: str = "network_cam",
    ) -> Optional[dict[str, Any]]:
        """
        Single-pass face analysis on a crop (Review 2026-10-13 Item 8).
        Runs FaceAnalysis once on the crop, evaluates clarity, filters decor faces,
        and computes similarity to Col and identity matching without redundant duplicate passes.
        """
        if not self.is_available or crop is None or crop.size == 0:
            return None
        if store is None:
            store = get_sqlite_store()

        try:
            faces = self._faces_in_still(crop)
            if not faces:
                return None

            # Filter out decor faces (Review Addendum 13:05)
            valid_faces = []
            for f in faces:
                emb = np.array(f.embedding, dtype=np.float32)
                if not self.is_decor_face(emb, store=store):
                    valid_faces.append(f)

            if not valid_faces:
                return None

            # Pick the face closest to the centre of the crop (Review 18:55 Should-fix 11)
            crop_h, crop_w = crop.shape[:2]
            crop_cx, crop_cy = crop_w / 2.0, crop_h / 2.0
            def _dist_to_center(f):
                fb = f.bbox
                fcx = (fb[0] + fb[2]) / 2.0
                fcy = (fb[1] + fb[3]) / 2.0
                return (fcx - crop_cx)**2 + (fcy - crop_cy)**2

            primary_face = min(valid_faces, key=_dist_to_center)
            primary_emb = np.array(primary_face.embedding, dtype=np.float32)

            # Blur/brightness are judged on the face itself (face plus 25%), not on the
            # whole still crop, which includes plenty of background.
            fx1, fy1, fx2, fy2 = [int(v) for v in primary_face.bbox]
            pw, ph = max(1, (fx2 - fx1) // 4), max(1, (fy2 - fy1) // 4)
            face_region = crop[max(0, fy1 - ph):min(crop_h, fy2 + ph), max(0, fx1 - pw):min(crop_w, fx2 + pw)]
            if face_region.size == 0:
                face_region = crop
            is_clear, clarity_reason = self.is_clear_face(primary_face, face_region)
            col_sim = self.get_similarity_to_col(primary_emb, store=store)
            match_res = self.match_face_embedding(primary_emb, store=store)

            return {
                "face": primary_face,
                "embedding": primary_emb,
                "is_clear": is_clear,
                "clarity_reason": clarity_reason,
                "col_sim": col_sim,
                "match_res": match_res,
                "bbox": [int(v) for v in primary_face.bbox],
                "det_score": float(getattr(primary_face, "det_score", 0.9)),
            }
        except Exception as e:
            logger.debug(f"analyze_face_crop failed: {e}")
            return None

    def _faces_in_still(self, img: np.ndarray) -> List[Any]:
        """
        Find and analyse the faces in a sharp still crop (Claude 2026-10-15).
        The still crop is the face plus its own size on each side, so the face is about a
        third of the crop. At the observer's normal 640 detection size such a face is blown
        up so far that the detector misses it (found in 2-11 of 34 saved crops of Col); at
        192 it's found in 32 of 34, with the same similarity scores. Recognition and the
        turn model still run on the crop's own full-resolution pixels.
        """
        from insightface.app.common import Face

        bboxes, kpss = self._app.det_model.detect(
            img, input_size=_STILL_DETECTION_SIZE, max_num=0, metric="default"
        )
        faces: List[Any] = []
        for i in range(bboxes.shape[0]):
            face = Face(
                bbox=bboxes[i, 0:4],
                kps=kpss[i] if kpss is not None else None,
                det_score=bboxes[i, 4],
            )
            for taskname, model in self._app.models.items():
                if taskname == "detection":
                    continue
                model.get(img, face)
            faces.append(face)
        return faces

    @staticmethod
    def is_facing_camera(face: Any, max_angle: float = 30.0) -> bool:
        """True when the face's measured turn (pitch and yaw) is within max_angle degrees."""
        pose = getattr(face, "pose", None)
        if pose is None or len(pose) < 2:
            return False
        return abs(float(pose[0])) <= max_angle and abs(float(pose[1])) <= max_angle

    def analyze_detected_face(
        self,
        face: Any,
        crop: Optional[np.ndarray] = None,
        store: Any = None,
    ) -> Optional[dict[str, Any]]:
        """
        Same result as analyze_face_crop, for a face already found and analysed in the
        whole small-stream frame (Claude 2026-10-15). Reuses that face's embedding and
        pose instead of running the face model a second time on the same pixels.
        `crop` is the small-stream crop around the face, used for the blur/brightness checks.
        """
        emb_raw = getattr(face, "embedding", None)
        if emb_raw is None:
            return None
        if store is None:
            store = get_sqlite_store()
        try:
            emb = np.array(emb_raw, dtype=np.float32)
            is_clear, clarity_reason = self.is_clear_face(face, crop)
            return {
                "face": face,
                "embedding": emb,
                "is_clear": is_clear,
                "clarity_reason": clarity_reason,
                "col_sim": self.get_similarity_to_col(emb, store=store),
                "match_res": self.match_face_embedding(emb, store=store),
                "bbox": [int(v) for v in face.bbox],
                "det_score": float(getattr(face, "det_score", 0.9)),
            }
        except Exception as e:
            logger.debug(f"analyze_detected_face failed: {e}")
            return None

    def save_snapshot(self, img: np.ndarray, filename: str) -> Optional[str]:
        """Save a face snapshot crop or frame to the configured snapshots directory."""
        if img is None or img.size == 0:
            return None
        try:
            import cv2
            filepath = self._snapshots_dir / filename
            cv2.imwrite(str(filepath), img)
            return str(filepath)
        except Exception as e:
            logger.warning(f"PersonIdentifier: Failed saving snapshot {filename}: {e}")
            return None


