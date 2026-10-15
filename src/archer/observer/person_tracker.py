"""
ARCHER Multi-Person Tracker & Following System (Spec 5b, Col 2026-10-12).

Follows people on the room camera continuously across their stay in view at ~2 FPS (~500ms),
maintaining consistent identity across body turns and off-angle postures.

Key Architecture:
- Body Tracking: Runs approved YOLOX-Nano ONNX detector on 640x480 sub-stream.
- One Identity Per Stay: The first time ARCHER clearly recognizes a face, that person's
  whole stay in view counts as them, backfilling earlier sightings in that stay.
- Mirror Disambiguation: Kinematic Lockstep primary defense (reflections moving in
  horizontal synchrony with a floor-contact track never spawn a new track).
- Disambiguation on Crossings: When two people overlap or cross paths, identity assumption
  is suspended until another clear face match.
- High-Resolution Face Verification: Captures on-demand snapshots from camera snapshot API
  in memory only when a tracked person faces the camera. Camera credentials are never logged.
- Memory & Privacy: Frames are processed in memory and dropped immediately. Zero video saved.
"""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from loguru import logger

from archer.config import get_config
from archer.observer.person_detector import PersonDetector


def _compute_iou(boxA: list[int] | tuple[int, ...], boxB: list[int] | tuple[int, ...]) -> float:
    """Compute Intersection over Union between two [x, y, w, h] boxes."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

    interW = max(0, xB - xA)
    interH = max(0, yB - yA)
    interArea = interW * interH

    boxAArea = max(1, boxA[2] * boxA[3])
    boxBArea = max(1, boxB[2] * boxB[3])

    return float(interArea / (boxAArea + boxBArea - interArea))


@dataclass
class Track:
    """An active visual body track representing a person's stay in the room."""

    track_id: int
    stay_id: str
    box: list[int]  # [x, y, w, h]
    centroid: tuple[float, float]
    velocity: tuple[float, float] = (0.0, 0.0)  # (dx, dy) pixels per second
    first_seen_ts: float = field(default_factory=time.time)
    last_seen_ts: float = field(default_factory=time.time)
    duration: float = 0.0  # continuous seconds in view
    missed_frames: int = 0
    assigned_identity: Optional[str] = None  # e.g. "Col" or "Person_N"
    is_known: bool = False
    confidence: float = 0.0
    confirmed_known: bool = False
    ambiguous: bool = False  # True during crossing paths / overlap
    sightings_in_stay: list[int] = field(default_factory=list)
    unrecognized_snapshots_count: int = 0
    last_face_check_ts: float = 0.0
    last_stay_write_ts: float = 0.0
    state: str = "active"  # "active" | "paused" | "ended"
    is_reflection: bool = False
    reflection_lockstep_count: int = 0


class MirrorFilter:
    """
    Filters out optical reflections from the wall-mounted mirror above the couch.
    Primary Defense: Multi-Frame Kinematic Lockstep.

    A reflection candidate in the elevated mirror region that tracks horizontally with a
    real floor-grounded body track over >= 3 frames is mathematically identified
    as an optical reflection.

    Crucial Rule (Review 15:40 Item 3):
    A candidate reflection is NEVER dropped on a single frame. It must exhibit
    multi-frame horizontal lockstep motion (dx_candidate * dx_ground > 0) with a
    grounded person track over at least 3 frames before suppression.
    People sitting on the couch (y > 200, outside the mirror zone) are never dropped.
    """

    def __init__(
        self,
        mirror_roi: tuple[int, int, int, int] = (65, 280, 100, 140),  # Standing mirror by front door (Spec 5b & Review 2026-10-13 Item 4): [x, y, w, h] on 640x480
        max_horizontal_offset: float = 75.0,
        min_lockstep_frames: int = 2,  # 2 consecutive lockstep transitions across 3 frames
    ) -> None:
        self.mirror_roi = mirror_roi
        self.max_horizontal_offset = max_horizontal_offset
        self.min_lockstep_frames = min_lockstep_frames

    def is_in_mirror_zone(self, box: list[int] | tuple[int, ...]) -> bool:
        """Check if detection box is elevated inside the mirror region above the couch."""
        bx, by, bw, bh = box
        mx, my, mw, mh = self.mirror_roi
        center_x = bx + bw / 2.0
        center_y = by + bh / 2.0
        return (mx <= center_x <= mx + mw) and (my <= center_y <= my + mh)

    def check_lockstep_and_filter(
        self,
        tracks: list[Track],
    ) -> None:
        """
        Evaluate active tracks across multiple frames. If a track in the mirror zone
        exhibits correlated horizontal motion in lockstep with a real person in the room over >= 3 frames,
        mark is_reflection = True.
        """
        candidates = [t for t in tracks if t.state == "active" and self.is_in_mirror_zone(t.box)]
        grounded = [
            t for t in tracks
            if t.state == "active" and not self.is_in_mirror_zone(t.box)
        ]


        for cand in candidates:
            cand_cx = cand.centroid[0]
            for ground in grounded:
                # Check horizontal alignment within max_horizontal_offset
                if abs(cand_cx - ground.centroid[0]) <= self.max_horizontal_offset:
                    cand_vx = cand.velocity[0]
                    ground_vx = ground.velocity[0]
                    # Review 23:55 Item 13: Correlated horizontal motion (speed >= 5.0 px/s, above jitter)
                    if (cand_vx * ground_vx > 0) and (abs(ground_vx) >= 5.0 or abs(cand_vx) >= 5.0):
                        cand.reflection_lockstep_count += 1
                    else:
                        # Reset count when motion disagrees or is within jitter
                        cand.reflection_lockstep_count = 0

                    if cand.reflection_lockstep_count >= self.min_lockstep_frames:
                        cand.is_reflection = True
                        logger.info(
                            f"MirrorFilter: Track {cand.track_id} confirmed as optical reflection "
                            f"(lockstep {cand.reflection_lockstep_count} frames with grounded track {ground.track_id})."
                        )
                        break

    def is_reflection_candidate(
        self,
        det_box: list[int],
        active_tracks: list[Track],
        other_detections: list[dict] | None = None,
    ) -> bool:
        """
        Check if a detection matches an already-confirmed reflection track.
        Never drops unconfirmed detections on a single frame.
        """
        if not self.is_in_mirror_zone(det_box):
            return False

        det_cx = det_box[0] + det_box[2] / 2.0
        det_cy = det_box[1] + det_box[3] / 2.0
        for track in active_tracks:
            if getattr(track, "is_reflection", False):
                dist = np.hypot(det_cx - track.centroid[0], det_cy - track.centroid[1])
                if dist < 60.0:
                    return True
        return False

    def is_reflection_of_active_track(
        self,
        det_box: list[int],
        active_tracks: list[Track],
    ) -> bool:
        """Alias for is_reflection_candidate."""
        return self.is_reflection_candidate(det_box, active_tracks)


class PersonTracker:
    """
    Multi-person body tracker across video frames.
    Follows people at ~2 FPS in its own dedicated loop, maintaining consistent stay identities.
    Thread-safe for concurrent tracker and analysis pipeline access.
    """

    def __init__(
        self,
        detector: Optional[PersonDetector] = None,
        max_missed_seconds: float = 3.0,
        iou_threshold: float = 0.20,
        max_centroid_dist: float = 80.0,
        fps: float = 2.0,
    ) -> None:
        self.detector = detector or PersonDetector()
        self.max_missed_seconds = max_missed_seconds
        self.iou_threshold = iou_threshold
        self.max_centroid_dist = max_centroid_dist
        self.fps = fps
        self.mirror_filter = MirrorFilter()

        self._active_tracks: Dict[int, Track] = {}
        self._bytetrack_to_track_id: Dict[int, int] = {}
        self._next_track_id: int = 1
        self._last_update_ts: float = 0.0
        self._last_processed_frame_ts: float = 0.0
        self._active_crossings: set[tuple[int, int]] = set()
        self._recent_exit_events: List[Tuple[str, float, int]] = []  # ('entry' | 'exit', timestamp, track_id)
        self._lock = threading.RLock()
        self._init_bytetrack()

    def _init_bytetrack(self) -> None:
        """Initialize approved trackers.ByteTrackTracker (Apache 2.0) (Review 2026-10-13 Item 6 & 8)."""
        # Buffer: 60 frames = 2.0 seconds at 30 fps
        lost_buffer = 60
        try:
            import trackers
            from trackers.core.bytetrack.tracklet import ByteTrackTracklet

            class _ArcherByteTracker(trackers.ByteTrackTracker):
                def _spawn_new_tracks(self, detection_boxes, confidences, unmatched_high_local, high_indices, out_det_indices, out_tracker_ids):
                    for det_local_idx in unmatched_high_local:
                        global_idx = int(high_indices[det_local_idx])
                        if float(confidences[global_idx]) >= self.track_activation_threshold:
                            t = ByteTrackTracklet(initial_bbox=detection_boxes[global_idx], state_estimator_class=self.state_estimator_class)
                            t.tracker_id = self._allocate_tracker_id()
                            self.tracks.append(t)
                            out_det_indices.append(global_idx)
                            out_tracker_ids.append(t.tracker_id)
                        else:
                            out_det_indices.append(global_idx)
                            out_tracker_ids.append(-1)

            self._byte_tracker = _ArcherByteTracker(
                lost_track_buffer=lost_buffer,
                frame_rate=30,
                track_activation_threshold=0.35,
                minimum_consecutive_frames=1,
                minimum_iou_threshold=0.10,
            )
            logger.info(f"PersonTracker: Initialized trackers.ByteTrackTracker (lost_track_buffer={lost_buffer}, frame_rate=30).")
        except Exception as e:
            logger.warning(f"PersonTracker: Failed to initialize trackers.ByteTrackTracker: {e}")
            self._byte_tracker = None

    def is_at_exit(
        self,
        box: list[int] | tuple[int, ...],
        centroid: tuple[float, float],
        frame_shape: tuple[int, int] = (480, 640),
    ) -> bool:
        """
        Check if person's feet are at one of the spec's three room camera exits (Must-fix 2):
        1. Front door: off left edge past coat hooks (feet_x <= 65, feet_y in [200, 425])
        2. Hallway opening: behind right end of couch (feet_x in [505, 565], feet_y in [280, 400])
        3. Kitchen door: left of fridge at right edge (feet_x >= 590, feet_y in [260, 390])
        Everywhere else is inside the room.
        Couch and PC monitor (feet_y >= 400, reaching bottom of picture) are NEVER exits!
        """
        frame_h, frame_w = frame_shape[:2]
        scale_x = frame_w / 640.0
        scale_y = frame_h / 480.0

        bx, by, bw, bh = box[:4]

        # Normalized coordinates on standard 640x480 grid
        norm_bx = bx / scale_x
        norm_by = by / scale_y
        norm_bw = bw / scale_x
        norm_bh = bh / scale_y

        feet_x = norm_bx + norm_bw / 2.0
        feet_y = norm_by + norm_bh

        # Couch and PC monitor reach the bottom of the picture (feet_y >= 430), which is NEVER an exit
        if feet_y >= 430.0:
            return False

        # 1. Front door: off left edge past coat hooks (x <= 65)
        is_front_door = (feet_x <= 65.0) and (200.0 <= feet_y <= 425.0)

        # 2. Hallway opening: doorway directly behind right end of couch (floor line y in [280, 400])
        # Note: Someone sitting on the couch reaches feet_y >= 430, while standing in hallway doorway is <= 400.
        is_hallway = (505.0 <= feet_x <= 565.0) and (280.0 <= feet_y <= 400.0)

        # 3. Kitchen door: left of fridge at right edge (x >= 590, floor line y in [260, 390])
        is_kitchen_door = (feet_x >= 590.0) and (260.0 <= feet_y <= 390.0)

        return is_front_door or is_hallway or is_kitchen_door



    @property
    def active_tracks(self) -> List[Track]:
        with self._lock:
            return [
                t for t in self._active_tracks.values()
                if t.state in ("active", "paused") and not getattr(t, "is_reflection", False)
            ]

    def update(
        self,
        frame: np.ndarray,
        timestamp: Optional[float] = None,
        store: Any = None,
    ) -> List[Track]:
        """
        Process a new frame (~2 FPS), detect people, filter reflections,
        and update multi-person tracks using Roboflow ByteTrack.
        """
        with self._lock:
            now = timestamp if timestamp is not None else time.time()
            if timestamp is not None and timestamp <= self._last_processed_frame_ts:
                return self.active_tracks
            self._last_processed_frame_ts = now
            dt = (now - self._last_update_ts) if self._last_update_ts > 0 else (1.0 / self.fps)
            dt = max(0.05, min(2.0, dt))
            self._last_update_ts = now

            # 1. Run Person Detector (duplicate boxes merged)
            raw_detections = self.detector.detect(frame)

            # 2. Filter out already-confirmed mirror reflections
            valid_detections: List[dict] = []
            for det in raw_detections:
                box = det["box"]
                if self.mirror_filter.is_reflection_candidate(box, list(self._active_tracks.values()), raw_detections):
                    logger.debug(f"PersonTracker: Dropped confirmed mirror reflection at {box}.")
                    continue
                valid_detections.append(det)

            # 3. Feed to Roboflow ByteTrack
            import supervision as sv
            if valid_detections:
                xyxy_boxes = []
                confs = []
                for det in valid_detections:
                    bx, by, bw, bh = det["box"]
                    xyxy_boxes.append([bx, by, bx + bw, by + bh])
                    confs.append(float(det.get("confidence", 0.9)))
                sv_dets = sv.Detections(
                    xyxy=np.array(xyxy_boxes, dtype=np.float32),
                    confidence=np.array(confs, dtype=np.float32),
                    class_id=np.zeros(len(valid_detections), dtype=int),
                )
            else:
                sv_dets = sv.Detections.empty()

            if self._byte_tracker is not None:
                try:
                    tracked_res = self._byte_tracker.update(sv_dets, timestamp=now)
                except Exception as e:
                    logger.debug(f"ByteTrack update fallback: {e}")
                    tracked_res = sv_dets
                    tracked_res.tracker_id = np.array([-1] * len(sv_dets), dtype=int)
            else:
                tracked_res = sv_dets
                tracked_res.tracker_id = np.array([-1] * len(sv_dets), dtype=int)

            matched_track_ids = set()
            matched_valid_indices = set()


            # Process tracked detections from ByteTrack
            if len(tracked_res) > 0 and tracked_res.tracker_id is not None:
                for i in range(len(tracked_res)):
                    b_id = int(tracked_res.tracker_id[i])
                    x1, y1, x2, y2 = tracked_res.xyxy[i]
                    det_box = [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]
                    det_center = (float(x1 + (x2 - x1) / 2.0), float(y1 + (y2 - y1) / 2.0))
                    det_conf = float(tracked_res.confidence[i]) if tracked_res.confidence is not None else 0.9

                    for vi, vdet in enumerate(valid_detections):
                        if vi not in matched_valid_indices and _compute_iou(vdet["box"], det_box) >= 0.50:
                            matched_valid_indices.add(vi)
                            break

                    track: Optional[Track] = None
                    if b_id >= 0 and b_id in self._bytetrack_to_track_id:
                        arch_id = self._bytetrack_to_track_id[b_id]
                        if arch_id in self._active_tracks and arch_id not in matched_track_ids:
                            cand = self._active_tracks[arch_id]
                            if cand.state == "active":
                                track = cand
                            elif cand.state == "paused":
                                came_or_went = any(
                                    ts >= cand.last_seen_ts for ev_type, ts, tid in self._recent_exit_events
                                )
                                if not came_or_went:
                                    track = cand

                    # If not mapped by ByteTrack ID, check spatial association with existing active tracks
                    # Review 23:55 Item 7: A new box joins an existing track only when it mostly overlaps it (IoU >= 0.40)
                    if track is None:
                        best_iou = 0.0
                        best_existing = None
                        for cand_track in self._active_tracks.values():
                            if cand_track.track_id in matched_track_ids:
                                continue
                            if cand_track.state == "active":
                                pass
                            elif cand_track.state == "paused":
                                came_or_went = any(
                                    ts >= cand_track.last_seen_ts for ev_type, ts, tid in self._recent_exit_events
                                )
                                if came_or_went:
                                    continue
                            else:
                                continue

                            iou = _compute_iou(cand_track.box, det_box)
                            if iou >= 0.40 and iou > best_iou:
                                best_iou = iou
                                best_existing = cand_track

                        if best_existing is not None:
                            track = best_existing
                            if b_id >= 0:
                                self._bytetrack_to_track_id[b_id] = track.track_id

                    # Mid-room retention: "Losing sight isn't leaving" (Spec 5b & Review 2026-10-13 Item 3)
                    # A paused stay resumes if:
                    # 1. candidate detection within 100px
                    # 2. within 60s
                    # 3. nobody was seen coming or going in the meantime
                    # Resumes the NEAREST paused stay
                    if track is None:
                        paused_candidates = []
                        for cand_track in self._active_tracks.values():
                            if cand_track.state == "paused" and cand_track.track_id not in matched_track_ids:
                                if (now - cand_track.last_seen_ts) <= 60.0:
                                    came_or_went = any(
                                        ts >= cand_track.last_seen_ts for ev_type, ts, tid in self._recent_exit_events
                                    )
                                    if not came_or_went:
                                        dist = np.hypot(cand_track.centroid[0] - det_center[0], cand_track.centroid[1] - det_center[1])
                                        if dist < 100.0:
                                            paused_candidates.append((cand_track, dist))

                        if paused_candidates:
                            paused_candidates.sort(key=lambda x: x[1])
                            nearest_track, _ = paused_candidates[0]
                            track = nearest_track
                            if b_id >= 0:
                                self._bytetrack_to_track_id[b_id] = track.track_id
                            logger.info(
                                f"PersonTracker: Resumed track {track.track_id} (stay: {track.stay_id}) "
                                f"after mid-room detector gap ({now - track.last_seen_ts:.1f}s)."
                            )

                    # If still not matched, spawn a genuinely new person track
                    if track is None:
                        new_track_id = max(self._next_track_id, max(self._active_tracks.keys(), default=0) + 1)
                        self._next_track_id = new_track_id + 1
                        stay_id = f"stay_{uuid.uuid4().hex[:12]}"
                        at_exit = self.is_at_exit(det_box, det_center, frame.shape[:2])
                        if at_exit:
                            self._recent_exit_events.append(("entry", now, new_track_id))
                        track = Track(
                            track_id=new_track_id,
                            stay_id=stay_id,
                            box=det_box,
                            centroid=det_center,
                            first_seen_ts=now,
                            last_seen_ts=now,
                            duration=0.0,
                            confidence=det_conf,
                            state="active",
                        )
                        self._active_tracks[new_track_id] = track
                        if b_id >= 0:
                            self._bytetrack_to_track_id[b_id] = new_track_id
                        logger.info(
                            f"PersonTracker: New person entered frame -> Track {new_track_id} (stay: {stay_id}) "
                            f"at box={det_box}, centroid={det_center}, at_exit={at_exit}."
                        )

                    # Update track state
                    track.state = "active"
                    old_center = track.centroid
                    vx = (det_center[0] - old_center[0]) / dt
                    vy = (det_center[1] - old_center[1]) / dt
                    track.velocity = (0.7 * track.velocity[0] + 0.3 * vx, 0.7 * track.velocity[1] + 0.3 * vy)
                    track.box = det_box
                    track.centroid = det_center
                    track.last_seen_ts = now
                    track.duration = now - track.first_seen_ts
                    track.missed_frames = 0
                    track.confidence = max(track.confidence, det_conf)
                    matched_track_ids.add(track.track_id)

            # Process any valid detections that ByteTrack did not return (e.g. unactivated on first frame)
            for vi, vdet in enumerate(valid_detections):
                if vi in matched_valid_indices:
                    continue
                det_box = vdet["box"]
                bx, by, bw, bh = det_box
                det_center = (float(bx + bw / 2.0), float(by + bh / 2.0))
                det_conf = float(vdet.get("confidence", 0.9))

                track: Optional[Track] = None
                best_iou = 0.0
                best_existing = None
                for cand_track in self._active_tracks.values():
                    if cand_track.track_id in matched_track_ids:
                        continue
                    if cand_track.state == "active":
                        pass
                    elif cand_track.state == "paused":
                        came_or_went = any(
                            ts >= cand_track.last_seen_ts for ev_type, ts, tid in self._recent_exit_events
                        )
                        if came_or_went:
                            continue
                    else:
                        continue
                    iou = _compute_iou(cand_track.box, det_box)
                    if iou >= 0.40 and iou > best_iou:
                        best_iou = iou
                        best_existing = cand_track

                if best_existing is not None:
                    track = best_existing

                if track is None:
                    paused_candidates = []
                    for cand_track in self._active_tracks.values():
                        if cand_track.state == "paused" and cand_track.track_id not in matched_track_ids:
                            if (now - cand_track.last_seen_ts) <= 60.0:
                                came_or_went = any(
                                    ts >= cand_track.last_seen_ts for ev_type, ts, tid in self._recent_exit_events
                                )
                                if not came_or_went:
                                    dist = np.hypot(cand_track.centroid[0] - det_center[0], cand_track.centroid[1] - det_center[1])
                                    if dist < 100.0:
                                        paused_candidates.append((cand_track, dist))

                    if paused_candidates:
                        paused_candidates.sort(key=lambda x: x[1])
                        nearest_track, _ = paused_candidates[0]
                        track = nearest_track

                if track is None:
                    new_track_id = max(self._next_track_id, max(self._active_tracks.keys(), default=0) + 1)
                    self._next_track_id = new_track_id + 1
                    stay_id = f"stay_{uuid.uuid4().hex[:12]}"
                    at_exit = self.is_at_exit(det_box, det_center, frame.shape[:2])
                    if at_exit:
                        self._recent_exit_events.append(("entry", now, new_track_id))
                    track = Track(
                        track_id=new_track_id,
                        stay_id=stay_id,
                        box=det_box,
                        centroid=det_center,
                        first_seen_ts=now,
                        last_seen_ts=now,
                        duration=0.0,
                        confidence=det_conf,
                        state="active",
                    )
                    self._active_tracks[new_track_id] = track
                    logger.info(
                        f"PersonTracker: New person entered frame (untracked detection) -> Track {new_track_id} (stay: {stay_id}) "
                        f"at box={det_box}, centroid={det_center}, at_exit={at_exit}."
                    )

                track.state = "active"
                old_center = track.centroid
                vx = (det_center[0] - old_center[0]) / dt
                vy = (det_center[1] - old_center[1]) / dt
                track.velocity = (0.7 * track.velocity[0] + 0.3 * vx, 0.7 * track.velocity[1] + 0.3 * vy)
                track.box = det_box
                track.centroid = det_center
                track.last_seen_ts = now
                track.duration = now - track.first_seen_ts
                track.missed_frames = 0
                track.confidence = max(track.confidence, det_conf)
                matched_track_ids.add(track.track_id)
                matched_valid_indices.add(vi)

            # 4. Handle Unmatched Tracks (Missed Frames & Mid-Room Gaps)
            ended_track_ids = []
            for track in list(self._active_tracks.values()):
                if track.state in ("active", "paused") and track.track_id not in matched_track_ids:
                    track.missed_frames += 1
                    missed_seconds = now - track.last_seen_ts

                    frame_h, frame_w = frame.shape[:2]
                    at_exit = self.is_at_exit(track.box, track.centroid, (frame_h, frame_w))

                    should_end = False
                    if at_exit:
                        if missed_seconds >= self.max_missed_seconds:
                            should_end = True
                    else:
                        # Mid-room: losing sight isn't leaving (timeout 60s)
                        if missed_seconds >= 60.0:
                            should_end = True
                        elif missed_seconds >= self.max_missed_seconds:
                            track.state = "paused"

                    if should_end:
                        track.state = "ended"
                        ended_track_ids.append(track.track_id)
                        if at_exit:
                            self._recent_exit_events.append(("exit", now, track.track_id))
                        # A stay ends when the person was last seen, not when it's given up
                        # (Claude 2026-10-15). track.duration already runs to last_seen_ts.
                        logger.info(
                            f"PersonTracker: Track {track.track_id} (identity: {track.assigned_identity}, stay: {track.stay_id}) "
                            f"ended after {track.duration:.1f}s stay at box={track.box}, centroid={track.centroid}, at_exit={at_exit}."
                        )
                        if store is not None:
                            try:
                                # Review 23:55 Item 9: UTC timestamp for ended_at
                                utc_ended = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(track.last_seen_ts))
                                store.log_or_update_stay(
                                    stay_id=track.stay_id,
                                    person_id=track.assigned_identity or "Person",
                                    ended_at=utc_ended,
                                    track_id=track.track_id,
                                )
                            except Exception:
                                pass

            # Prune ended tracks
            for etid in ended_track_ids:
                self._active_tracks.pop(etid, None)
                self._bytetrack_to_track_id = {k: v for k, v in self._bytetrack_to_track_id.items() if v != etid}

            # Prune old exit events (> 120s)
            self._recent_exit_events = [(ev, ts, tid) for ev, ts, tid in self._recent_exit_events if (now - ts) <= 120.0]

            # 5. Check for Overlapping Paths / Ambiguous Crossings (Should-fix 7)
            # A 'crossing' happens when two tracks with their own separate histories converge.
            # Start new stays once per crossing, close old stays with ended_at, and maintain while overlapping.
            current_active = [t for t in self._active_tracks.values() if t.state == "active" and not getattr(t, "is_reflection", False)]
            detected_crossings = set()
            for i in range(len(current_active)):
                for j in range(i + 1, len(current_active)):
                    t1 = current_active[i]
                    t2 = current_active[j]
                    pair = (min(t1.track_id, t2.track_id), max(t1.track_id, t2.track_id))
                    if t1.duration >= 2.0 and t2.duration >= 2.0 and _compute_iou(t1.box, t2.box) > 0.30:
                        detected_crossings.add(pair)
                        if pair not in self._active_crossings:
                            self._active_crossings.add(pair)
                            old_s1, old_s2 = t1.stay_id, t2.stay_id
                            utc_ended = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))
                            if store is not None:
                                try:
                                    store.log_or_update_stay(
                                        stay_id=old_s1,
                                        person_id=t1.assigned_identity or "Person",
                                        ended_at=utc_ended,
                                        track_id=t1.track_id,
                                    )
                                    store.log_or_update_stay(
                                        stay_id=old_s2,
                                        person_id=t2.assigned_identity or "Person",
                                        ended_at=utc_ended,
                                        track_id=t2.track_id,
                                    )
                                except Exception as e:
                                    logger.debug(f"Failed closing stays on crossing: {e}")
                            t1.stay_id = f"stay_{uuid.uuid4().hex[:12]}"
                            t2.stay_id = f"stay_{uuid.uuid4().hex[:12]}"
                            t1.ambiguous = True
                            t2.ambiguous = True
                            t1.assigned_identity = None
                            t2.assigned_identity = None
                            t1.confirmed_known = False
                            t2.confirmed_known = False
                            # After a crossing either track may be following the other person:
                            # drop per-person face state so faces aren't added to the wrong label.
                            for _t in (t1, t2):
                                _t.is_known = False
                                _t.waiting_label_id = None
                                _t._waiting_photos_count = 0
                                _t._last_waiting_photo_ts = None
                                _t._last_saved_snapshot_path = None
                                _t._consecutive_stranger_looks = 0
                            logger.info(
                                f"PersonTracker: Tracks {t1.track_id} and {t2.track_id} crossed paths (IoU > 0.30). "
                                f"Closed stays {old_s1}, {old_s2} and started new stays: {t1.stay_id}, {t2.stay_id}."
                            )

            for pair in list(self._active_crossings):
                if pair not in detected_crossings:
                    self._active_crossings.discard(pair)


            # 6. Multi-frame Kinematic Lockstep Mirror Evaluation
            self.mirror_filter.check_lockstep_and_filter(list(self._active_tracks.values()))

            # 7. Update Stays Record in store (Spec 5b, Review 19:30 Item 3 & Review 23:55 Item 12, Review 2026-10-13 Item 11: Throttled)
            if store is not None:
                for track in current_active:
                    should_write = (
                        track.last_stay_write_ts == 0.0
                        or (now - track.last_stay_write_ts >= 30.0)
                    )
                    if should_write:
                        try:
                            store.log_or_update_stay(
                                stay_id=track.stay_id,
                                person_id=track.assigned_identity or "Person",
                                confidence=track.confidence,
                                is_known=track.is_known,
                                track_id=track.track_id,
                            )
                            track.last_stay_write_ts = now
                        except Exception as e:
                            logger.debug(f"Failed updating stay in store: {e}")


            return [
                t for t in self._active_tracks.values()
                if t.state == "active" and not getattr(t, "is_reflection", False)
            ]

    def resolve_track_identity(
        self,
        track: Track,
        identity: str,
        is_known: bool,
        confidence: float,
        store: Any = None,
    ) -> None:
        """
        Bind or update identity for a track's whole stay.
        Spec 5b: 'The first time ARCHER clearly recognizes a face, that person's whole stay
        in view counts as them, including the time before. Every face sighting is logged
        with the stay it belongs to.'
        """
        with self._lock:
            track.assigned_identity = identity
            track.is_known = is_known
            track.confidence = confidence
            track.ambiguous = False
            track.last_face_check_ts = time.time()
            track.last_stay_write_ts = time.time()

            if store is not None:
                try:
                    store.log_or_update_stay(
                        stay_id=track.stay_id,
                        person_id=identity,
                        confidence=confidence,
                        is_known=is_known,
                        track_id=track.track_id,
                    )
                except Exception as e:
                    logger.debug(f"Failed logging resolved stay identity: {e}")

            if is_known and identity == "Col":
                track.confirmed_known = True
                if store is not None:
                    try:
                        backfilled = store.backfill_stay_as_col(track.stay_id)
                        if backfilled > 0:
                            logger.info(
                                f"PersonTracker: Backfilled {backfilled} earlier sightings in stay {track.stay_id} to Col."
                            )
                    except Exception as e:
                        logger.debug(f"Failed backfilling stay {track.stay_id} to Col: {e}")

    def capture_sharp_face_crop(
        self,
        track: Track,
        frame_sub: np.ndarray,
        network_camera_url: Optional[str] = None,
        reolink_detector: Any = None,
        sub_face_box: Optional[list[int]] = None,
        fetch_network_still: bool = False,
    ) -> Tuple[Optional[np.ndarray], Optional[list[int]], bool]:
        """
        Extract face crop in memory.
        If fetch_network_still is True and camera snapshot API is available, grabs a 2560x1920 snapshot
        and crops around the detected face box with 25% padding margin.
        Routine face checks set fetch_network_still=False to crop directly from frame_sub in memory
        to save CPU and network bandwidth (Must-fix 4).
        Returns: (crop, box, is_sharp) where is_sharp is True if obtained from high-res snapshot.
        Credentials are never printed to logs or error messages.
        """
        frame_h, frame_w = frame_sub.shape[:2]
        if sub_face_box is not None:
            fx, fy, fw, fh = sub_face_box
        else:
            bx, by, bw, bh = track.box
            fx, fy, fw, fh = bx, by, bw, int(bh * 0.45)

        img_main = None

        if fetch_network_still:
            # 1. Try ReolinkSmartDetector's authenticated snapshot session
            if reolink_detector is not None:
                try:
                    if hasattr(reolink_detector, "get_snapshot"):
                        img_bytes = reolink_detector.get_snapshot()
                        if img_bytes:
                            nparr = np.frombuffer(img_bytes, np.uint8)
                            img_main = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                except Exception as e:
                    logger.debug(f"ReolinkSmartDetector snapshot retrieval fallback: {e}")

            # 2. Try direct HTTP snapshot API if detector wasn't available
            if img_main is None and network_camera_url and "rtsp://" in network_camera_url:
                pwd = ""
                try:
                    parsed = urllib.parse.urlparse(network_camera_url)
                    host = parsed.hostname or "127.0.0.1"
                    user = urllib.parse.unquote(parsed.username or "")
                    pwd = urllib.parse.unquote(parsed.password or "")

                    snap_url = f"http://{host}/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=wuu9570"
                    passman = urllib.request.HTTPPasswordMgrWithDefaultRealm()
                    passman.add_password(None, snap_url, user, pwd)
                    authhandler = urllib.request.HTTPDigestAuthHandler(passman)
                    opener = urllib.request.build_opener(authhandler)

                    req = urllib.request.Request(snap_url)
                    with opener.open(req, timeout=2.0) as resp:
                        img_bytes = resp.read()

                    if img_bytes:
                        nparr = np.frombuffer(img_bytes, np.uint8)
                        img_main = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                except Exception as e:
                    err_msg = str(e)
                    if pwd and pwd in err_msg:
                        err_msg = err_msg.replace(pwd, "***")
                    logger.debug(f"Camera HTTP snapshot capture fallback: {err_msg}")


        # If high-resolution snapshot succeeded:
        if img_main is not None:
            main_h, main_w = img_main.shape[:2]
            scale_x = main_w / float(frame_w)
            scale_y = main_h / float(frame_h)

            face_box_x = int(fx * scale_x)
            face_box_y = int(fy * scale_y)
            face_box_w = int(fw * scale_x)
            face_box_h = int(fh * scale_y)

            # Still crop: the face plus its own size on each side (Claude 2026-10-15). This
            # leaves room for the person moving between the small-stream frame and the still,
            # and keeps the face about a third of the crop, where the detector finds it.
            pad_x = int(face_box_w * 1.0)
            pad_y = int(face_box_h * 1.0)
            crop_x1 = max(0, face_box_x - pad_x)
            crop_y1 = max(0, face_box_y - pad_y)
            crop_x2 = min(main_w, face_box_x + face_box_w + pad_x)
            crop_y2 = min(main_h, face_box_y + face_box_h + pad_y)

            crop = img_main[crop_y1:crop_y2, crop_x1:crop_x2]
            if crop.size > 0:
                return crop, [crop_x1, crop_y1, crop_x2 - crop_x1, crop_y2 - crop_y1], True

        # Fallback: crop face box from sub-stream frame in memory
        pad_x = int(fw * 0.25)
        pad_y = int(fh * 0.25)
        crop_y1 = max(0, fy - pad_y)
        crop_y2 = min(frame_h, fy + fh + pad_y)
        crop_x1 = max(0, fx - pad_x)
        crop_x2 = min(frame_w, fx + fw + pad_x)
        crop = frame_sub[crop_y1:crop_y2, crop_x1:crop_x2]
        return ((crop, [crop_x1, crop_y1, crop_x2 - crop_x1, crop_y2 - crop_y1], False)
                if crop.size > 0 else (None, None, False))

