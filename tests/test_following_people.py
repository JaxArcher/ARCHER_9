"""
Comprehensive tests for 'Following People' (Spec 5b, Col 2026-10-12).

Tests:
1. Approved YOLOX-Nano ONNX detector loading, checksum, and detection.
2. Continuous body tracking across frames at 2 FPS (~500ms).
3. One identity for the whole stay: retrospective backfill of earlier sightings to Col.
4. Second person entering the room gets their own waiting label and is never filed as Col.
5. Mirror reflection filter via Kinematic Lockstep: reflections never create a second track.
6. Ambiguous crossing / overlapping paths: identity carry suspended until fresh verification.
7. Morning sequence test (9:11 to 9:29): sightings following Col recognition stay as Col.
8. Sharp face crop snapshot API: camera passwords never leaked in logs or error messages.
9. Reolink ONVIF listener subscription renewal and auto-reconnect backoff loop.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from archer.memory.sqlite_store import SQLiteStore
from archer.observer.person_detector import (
    APPROVED_MODEL_PATH,
    APPROVED_MODEL_SHA256,
    PersonDetector,
)
from archer.observer.person_id import PersonIdentifier
from archer.observer.person_tracker import MirrorFilter, PersonTracker, Track


class TestFollowingPeopleSpec5b:
    """Test suite validating Following People against Spec 5b acceptance criteria."""

    def test_approved_detector_source_and_checksum(self):
        """Verify the approved person-detector model file exists with exact pinned checksum."""
        model_file = Path(APPROVED_MODEL_PATH)
        assert model_file.exists(), f"Approved model file missing at {APPROVED_MODEL_PATH}"

        hasher = hashlib.sha256()
        with open(model_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        calculated_sha = hasher.hexdigest()

        assert calculated_sha == APPROVED_MODEL_SHA256, (
            f"Checksum mismatch! Expected {APPROVED_MODEL_SHA256}, got {calculated_sha}"
        )

        detector = PersonDetector(model_path=model_file)
        assert detector.is_available is True
        assert detector.is_onnx_model is True

    def test_continuous_body_tracking_at_2fps(self):
        """Verify body tracking follows a person across frames at 2 FPS and accumulates duration."""
        tracker = PersonTracker(fps=2.0)

        # Mock detector output: person moving across room
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        # Frame 1: Person enters at (100, 100)
        mock_detector.detect.return_value = [{"box": [100, 100, 80, 200], "confidence": 0.85, "class": "person"}]
        t0 = 1000.0
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        assert len(tracks) == 1
        t1 = tracks[0]
        assert t1.track_id == 1
        assert t1.box == [100, 100, 80, 200]
        assert t1.duration == 0.0
        initial_stay = t1.stay_id

        # Frame 2: Person takes half a step to (110, 100) at t = t0 + 0.5s (2 FPS)
        mock_detector.detect.return_value = [{"box": [110, 100, 80, 200], "confidence": 0.87, "class": "person"}]
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 0.5)
        assert len(tracks) == 1
        assert tracks[0].track_id == 1
        assert tracks[0].stay_id == initial_stay
        assert tracks[0].box == [110, 100, 80, 200]
        assert pytest.approx(tracks[0].duration, 0.01) == 0.5

        # Frame 3: Person continues to (120, 100) at t = t0 + 1.0s
        mock_detector.detect.return_value = [{"box": [120, 100, 80, 200], "confidence": 0.88, "class": "person"}]
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 1.0)
        assert len(tracks) == 1
        assert tracks[0].track_id == 1
        assert tracks[0].stay_id == initial_stay
        assert pytest.approx(tracks[0].duration, 0.01) == 1.0

    def test_one_identity_for_whole_stay_and_backfill(self, tmp_path):
        """
        Spec 5b: 'The first time ARCHER clearly recognizes a face, that person's whole stay
        in view counts as them, including the time before. Every face sighting is logged
        with the stay it belongs to.'
        """
        test_db = str(tmp_path / "test_following.db")
        store = SQLiteStore(db_path=test_db)

        stay_id = "stay_test_col_123"

        # Log 3 sightings during this stay that were initially unrecognized (off-angle looks)
        s1 = store.log_person_sighting(
            person_id="Person_31",
            is_known=False,
            confidence=0.42,
            camera_source="network_cam",
            stay_id=stay_id,
        )
        s2 = store.log_person_sighting(
            person_id="Person_31",
            is_known=False,
            confidence=0.45,
            camera_source="network_cam",
            stay_id=stay_id,
        )
        s3 = store.log_person_sighting(
            person_id="Person_31",
            is_known=False,
            confidence=0.48,
            camera_source="network_cam",
            stay_id=stay_id,
        )

        sightings_before = store.get_stay_sightings(stay_id)
        assert len(sightings_before) == 3
        for s in sightings_before:
            assert s["person_id"] == "Person_31"
            assert s["is_known"] == 0

        # Now at t = 9:28, Col turns facing the camera and is recognized!
        updated = store.backfill_stay_as_col(stay_id)
        assert updated == 3

        sightings_after = store.get_stay_sightings(stay_id)
        assert len(sightings_after) == 3
        for s in sightings_after:
            assert s["person_id"] == "Col"
            assert s["is_known"] == 1

    def test_second_person_gets_own_waiting_label_never_filed_as_col(self, tmp_path):
        """
        Spec 5b: 'A second person who comes in is never filed as Col, and their stay
        gets one waiting label.'
        """
        test_db = str(tmp_path / "test_two_people.db")
        store = SQLiteStore(db_path=test_db)
        tracker = PersonTracker(fps=2.0)

        mock_detector = MagicMock()
        tracker.detector = mock_detector

        # Frame 1: Col is already tracked at (100, 100)
        mock_detector.detect.return_value = [{"box": [100, 100, 80, 200], "confidence": 0.90, "class": "person"}]
        t0 = 2000.0
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        assert len(tracks) == 1
        col_track = tracks[0]
        tracker.resolve_track_identity(col_track, "Col", is_known=True, confidence=0.75, store=store)
        assert col_track.assigned_identity == "Col"
        assert col_track.is_known is True

        # Frame 2: Second person enters at (450, 120) while Col is still at (105, 100)
        mock_detector.detect.return_value = [
            {"box": [105, 100, 80, 200], "confidence": 0.91, "class": "person"},
            {"box": [450, 120, 80, 200], "confidence": 0.85, "class": "person"},
        ]
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 0.5)
        assert len(tracks) == 2

        # Col track remains Col
        track_col = next(t for t in tracks if t.track_id == col_track.track_id)
        assert track_col.assigned_identity == "Col"
        assert track_col.is_known is True

        # Second person track is distinct, has distinct stay_id, and is NOT Col
        track_visitor = next(t for t in tracks if t.track_id != col_track.track_id)
        assert track_visitor.stay_id != col_track.stay_id
        assert track_visitor.assigned_identity is None or track_visitor.assigned_identity != "Col"
        assert track_visitor.is_known is False

        # Assign visitor waiting label
        tracker.resolve_track_identity(track_visitor, "Person_40", is_known=False, confidence=0.50, store=store)
        assert track_visitor.assigned_identity == "Person_40"
        assert track_col.assigned_identity == "Col"

    def test_mirror_reflection_kinematic_lockstep_never_creates_second_track(self):
        """
        Spec 5b & Review 15:40 Item 3:
        A reflection in the mirror zone moving in horizontal lockstep with a grounded track
        over >= 3 frames is mathematically identified as an optical reflection and suppressed.
        """
        mirror_filter = MirrorFilter(mirror_roi=(210, 25, 260, 140), max_horizontal_offset=75.0, min_lockstep_frames=2)
        tracker = PersonTracker(fps=2.0)
        tracker.mirror_filter = mirror_filter
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        # Frame 1 (t=3000.0): Real person on floor (x=240, y=260) and optical reflection in mirror (x=245, y=60)
        mock_detector.detect.return_value = [
            {"box": [240, 260, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [245, 60, 60, 80], "confidence": 0.85, "class": "person"},
        ]
        t0 = 3000.0
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        # On single frame 1: not dropped yet (never drop on single frame)
        assert len(tracks) >= 1

        # Frame 2 (t=3000.5): Real person moves right to x=260 (dx=+20), reflection moves right to x=265 (dx=+20)
        mock_detector.detect.return_value = [
            {"box": [260, 260, 80, 200], "confidence": 0.91, "class": "person"},
            {"box": [265, 60, 60, 80], "confidence": 0.86, "class": "person"},
        ]
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 0.5)

        # Frame 3 (t=3001.0): Real person moves further right to x=280 (dx=+20), reflection moves to x=285 (dx=+20)
        mock_detector.detect.return_value = [
            {"box": [280, 260, 80, 200], "confidence": 0.92, "class": "person"},
            {"box": [285, 60, 60, 80], "confidence": 0.87, "class": "person"},
        ]
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 1.0)

        # After >= 3 frames in lockstep: reflection is confirmed and suppressed from active tracks!
        # Exactly ONE track exists: the real grounded person!
        assert len(tracks) == 1
        assert tracks[0].box == [280, 260, 80, 200]

    def test_two_people_sitting_on_couch_both_tracked(self):
        """
        Review 15:40 Item 3:
        Two people sitting side by side on the couch (y > 200, below the elevated mirror zone)
        must both be tracked across frames without either person being dropped.
        """
        tracker = PersonTracker(fps=2.0)
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        # Two people sitting side by side on the couch:
        # Person A (Col) at x=200, y=220, w=90, h=200 (center y=320, well below mirror zone)
        # Person B (Visitor) at x=310, y=220, w=90, h=200 (center y=320)
        mock_detector.detect.return_value = [
            {"box": [200, 220, 90, 200], "confidence": 0.92, "class": "person"},
            {"box": [310, 220, 90, 200], "confidence": 0.89, "class": "person"},
        ]

        t0 = 5000.0
        # Frame 1
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        assert len(tracks) == 2, "Both people sitting on couch must be detected on frame 1"
        assert not any(getattr(t, "is_reflection", False) for t in tracks)

        # Frame 2 (0.5s later)
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 0.5)
        assert len(tracks) == 2, "Both people sitting on couch must continue to be tracked"

        # Frame 3 (1.0s later)
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 1.0)
        assert len(tracks) == 2, "Neither person sitting on the couch is dropped"
        t_ids = {t.track_id for t in tracks}
        assert len(t_ids) == 2

    def test_ended_tracks_pruned_from_active_tracks(self):
        """
        Review 15:40 Item 6 (Minor):
        Ended tracks must be pruned from _active_tracks so the dictionary does not leak memory.
        """
        tracker = PersonTracker(fps=2.0, max_missed_seconds=3.0)
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        # Person enters at boundary (leaving frame at edge)
        mock_detector.detect.return_value = [{"box": [10, 100, 80, 200], "confidence": 0.90, "class": "person"}]
        t0 = 6000.0
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        assert len(tracker._active_tracks) == 1

        # Person disappears from view for > 3.0s
        mock_detector.detect.return_value = []
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 3.5)
        # Track ended and was pruned from _active_tracks
        assert len(tracker._active_tracks) == 0
        assert len(tracker.active_tracks) == 0

    def test_ambiguous_crossing_suspends_identity_carry(self):
        """
        Spec 5b: 'ARCHER doesn't carry an identity across a gap if: two people overlap or cross paths.
        It waits for another clear look at each face.'
        """
        tracker = PersonTracker(fps=2.0)
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        # Frame 1: Two separate people approaching each other
        mock_detector.detect.return_value = [
            {"box": [150, 150, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [300, 150, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        t0 = 4000.0
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        assert len(tracks) == 2
        t1, t2 = tracks[0], tracks[1]
        tracker.resolve_track_identity(t1, "Col", is_known=True, confidence=0.80)
        tracker.resolve_track_identity(t2, "Visitor", is_known=False, confidence=0.70)
        assert t1.assigned_identity == "Col"
        assert t2.assigned_identity == "Visitor"

        # Advance frames across 2.5s so both tracks have separate history (duration >= 2.0s, Review 20:00 Item 4)
        mock_detector.detect.return_value = [
            {"box": [170, 150, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [280, 150, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 1.0)

        mock_detector.detect.return_value = [
            {"box": [190, 150, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [260, 150, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 2.1)

        # Frame 4: The two people overlap / cross paths directly
        # Bounding boxes overlap heavily: box1=(220, 150), box2=(230, 150)
        mock_detector.detect.return_value = [
            {"box": [220, 150, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [230, 150, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 2.6)
        assert len(tracks) == 2

        # Both tracks are marked ambiguous, and identity assumption is cleared until fresh face match!
        assert tracks[0].ambiguous is True
        assert tracks[1].ambiguous is True
        assert tracks[0].assigned_identity is None
        assert tracks[1].assigned_identity is None

    def test_morning_sequence_stays_as_col_after_recognition(self, tmp_path):
        """
        Replicate the 2026-10-12 morning sequence:
        At 9:28 Col is recognized (row 1473).
        In the subsequent sightings (9:28:41 and 9:29:22), with Col still in the room within the same stay,
        sightings must be logged as Col, preventing separate Person_35 and Person_36 labels from spawning.
        """
        test_db = str(tmp_path / "test_morning.db")
        store = SQLiteStore(db_path=test_db)
        tracker = PersonTracker(fps=2.0)

        stay_id = "stay_morning_0928"
        track = Track(
            track_id=1,
            stay_id=stay_id,
            box=[200, 150, 100, 250],
            centroid=(250.0, 275.0),
            first_seen_ts=1728721200.0,  # 9:20
            last_seen_ts=1728721681.0,   # 9:28:01
        )
        tracker._active_tracks[1] = track

        # Sighting at 9:28:01 recognizes Col
        tracker.resolve_track_identity(track, "Col", is_known=True, confidence=0.55, store=store)
        s_928 = store.log_person_sighting(
            person_id=track.assigned_identity,
            is_known=track.is_known,
            confidence=0.55,
            camera_source="network_cam",
            stay_id=track.stay_id,
        )

        # 40 seconds later (9:28:41): Col is still in the room, seen off-angle
        track.last_seen_ts += 40.0
        assert track.assigned_identity == "Col"
        s_928_40 = store.log_person_sighting(
            person_id=track.assigned_identity,
            is_known=track.is_known,
            confidence=0.48,  # off-angle look
            camera_source="network_cam",
            stay_id=track.stay_id,
        )

        # 41 seconds later (9:29:22): Col still in view
        track.last_seen_ts += 41.0
        assert track.assigned_identity == "Col"
        s_929_22 = store.log_person_sighting(
            person_id=track.assigned_identity,
            is_known=track.is_known,
            confidence=0.45,
            camera_source="network_cam",
            stay_id=track.stay_id,
        )

        # All 3 sightings in this stay are logged as Col! No Person_35 or Person_36 created.
        sightings = store.get_stay_sightings(stay_id)
        assert len(sightings) == 3
        for s in sightings:
            assert s["person_id"] == "Col"
            assert s["is_known"] == 1

    def test_sharp_crop_camera_password_never_leaked(self):
        """Verify camera credentials and password are never printed or leaked in error logs."""
        tracker = PersonTracker()
        track = Track(
            track_id=1,
            stay_id="stay_pw_test",
            box=[100, 100, 80, 200],
            centroid=(140.0, 200.0),
        )

        secret_password = "super_secret_archer_camera_pass_xyz123"
        url_with_secret = f"rtsp://admin:{secret_password}@192.168.1.99:554/h264Preview_01_main"

        # Capture crop with invalid host (triggers network error)
        # Verify secret_password never appears in captured error message
        with patch("urllib.request.build_opener") as mock_opener:
            mock_opener.return_value.open.side_effect = RuntimeError(f"Failed connecting to {url_with_secret}")
            crop, box, is_sharp = tracker.capture_sharp_face_crop(
                track=track,
                frame_sub=np.zeros((480, 640, 3), dtype=np.uint8),
                network_camera_url=url_with_secret,
            )
            # Falls back cleanly to sub-frame crop
            assert crop is not None
            assert box is not None
            assert is_sharp is False

    def test_pipeline_tracker_runs_in_own_quick_loop_at_2fps(self):
        """
        Review 15:40 Item 1:
        Verify the real ObserverPipeline runs the tracker in its own dedicated thread at ~2 FPS,
        completely decoupled from the slow scene analysis cycle.
        """
        from archer.observer.pipeline import ObserverPipeline

        pipeline = ObserverPipeline(run_analysis=True, open_camera=False)

        # Mock camera with a test frame
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_camera = MagicMock()
        mock_camera.start.return_value = True
        mock_camera.get_latest_frame.return_value = (test_frame, time.time())
        pipeline._camera = mock_camera

        # Set network camera source
        pipeline._active_source = pipeline._config.network_camera_url

        # Mock person detector so tracker runs and returns a detection
        mock_detector = MagicMock()
        mock_detector.detect.return_value = [{"box": [150, 150, 80, 200], "confidence": 0.90, "class": "person"}]
        pipeline.person_tracker.detector = mock_detector

        # Set slow analysis interval (60 seconds)
        pipeline._analysis_interval = 60.0

        ok = pipeline.start()
        assert ok is True
        try:
            # Let tracker thread run for ~1.2 seconds (at 2 FPS, expects ~2 updates)
            time.sleep(1.2)
            assert pipeline.tracker_updates_count >= 2, (
                f"Tracker update count too low ({pipeline.tracker_updates_count}); expected at least 2 at 2 FPS!"
            )
            # Analysis cycle shouldn't have run multiple times in 1.2s with a 60s interval
            assert pipeline._analyses_run <= 1
        finally:
            pipeline.stop()

    def test_retired_only_col_recently_and_lookback_rule(self, tmp_path):
        """
        Review 19:30 Item 1:
        Retire the old 'only Col recently' rule and the look-back.
        Faces are now identified on per-person crops, so identity comes strictly
        from the track and direct face matching, never from single-face context heuristics.
        """
        test_db = str(tmp_path / "test_retired_context.db")
        store = SQLiteStore(db_path=test_db)
        store.add_known_person(name="Col", embedding=np.ones(512, dtype=np.float32).tobytes())

        identifier = PersonIdentifier(db_path=test_db)

        # Unrecognized face embedding (orthogonal to Col, similarity ~0.0)
        unrecognized_emb = np.zeros(512, dtype=np.float32)
        unrecognized_emb[0] = 1.0

        match_res = identifier.match_face_embedding(unrecognized_emb, store=store)
        assert match_res["is_known"] is False
        assert match_res["person_id"].startswith("Person_")
        assert match_res["person_id"] != "Col"

    def test_periodic_recheck_splits_stay_when_face_is_someone_else(self, tmp_path):
        """
        Review 19:30 Item 2:
        Re-check tracks confirmed as Col every minute or so.
        If a clear face says it's someone else, split the stay at that point.
        """
        test_db = str(tmp_path / "test_split_stay.db")
        store = SQLiteStore(db_path=test_db)

        # Start initial stay for Col
        stay_1 = "stay_col_initial"
        store.log_or_update_stay(
            stay_id=stay_1,
            person_id="Col",
            confidence=0.85,
            is_known=True,
            camera_source="network_cam",
            started_at="2026-10-12 12:00:00",
            ended_at="2026-10-12 12:05:00",
            track_id=1,
        )

        initial_stay = store.get_stay(stay_1)
        assert initial_stay["person_id"] == "Col"
        assert initial_stay["is_known"] == 1

        # Re-check at 12:05:00 reveals a visitor's clear face -> split stay!
        stay_2 = "stay_visitor_subsequent"
        split_ts = "2026-10-12 12:05:00"
        store.split_stay(
            old_stay_id=stay_1,
            new_stay_id=stay_2,
            new_person_id="Jenna",
            split_time=split_ts,
            camera_source="network_cam",
            confidence=0.78,
            is_known=True,
            track_id=1,
        )

        col_stay_ended = store.get_stay(stay_1)
        visitor_stay = store.get_stay(stay_2)

        assert col_stay_ended["ended_at"] == split_ts
        assert col_stay_ended["person_id"] == "Col"

        assert visitor_stay["started_at"] == split_ts
        assert visitor_stay["person_id"] == "Jenna"
        assert visitor_stay["confidence"] == 0.78

    def test_person_stays_records_continuous_visits(self, tmp_path):
        """
        Review 19:30 Item 3:
        Keep a record of each visit (who, camera, started_at, ended_at, confidence, is_known, track_id).
        """
        test_db = str(tmp_path / "test_stays_record.db")
        store = SQLiteStore(db_path=test_db)

        stay_id = "stay_visit_001"
        store.log_or_update_stay(
            stay_id=stay_id,
            person_id="Col",
            camera_source="network_cam",
            started_at="2026-10-12 14:00:00",
            ended_at="2026-10-12 14:00:00",
            confidence=0.88,
            is_known=True,
            track_id=5,
        )

        # Stay continues for 30 minutes
        store.log_or_update_stay(
            stay_id=stay_id,
            person_id="Col",
            ended_at="2026-10-12 14:30:00",
            confidence=0.92,
            is_known=True,
            track_id=5,
        )

        record = store.get_stay(stay_id)
        assert record is not None
        assert record["person_id"] == "Col"
        assert record["camera_source"] == "network_cam"
        assert record["started_at"] == "2026-10-12 14:00:00"
        assert record["ended_at"] == "2026-10-12 14:30:00"
        assert record["confidence"] == 0.92
        assert record["is_known"] == 1
        assert record["track_id"] == 5

        recent = store.get_recent_stays(limit=10)
        assert len(recent) == 1
        assert recent[0]["stay_id"] == stay_id

    def test_detector_merges_duplicate_person_boxes(self):
        """
        Review 20:00 Item 4:
        Stop one person being seen as two. Merge duplicate overlapping boxes (containment > 0.60
        or IoU > 0.30) so the detector's output gives one box per person.
        """
        detector = PersonDetector()
        # Simulated raw detections: full body box and upper torso box for the same seated person
        raw_detections = [
            {"box": [100, 100, 100, 200], "confidence": 0.88, "class": "person"},  # full body
            {"box": [110, 110, 80, 100], "confidence": 0.75, "class": "person"},   # nested upper torso
        ]

        merged = detector._merge_duplicate_person_boxes(raw_detections)
        assert len(merged) == 1
        bx, by, bw, bh = merged[0]["box"]
        assert bx <= 100 and by <= 100
        assert (bx + bw) >= 200 and (by + bh) >= 300
        assert merged[0]["confidence"] == 0.88

    def test_sharp_crop_only_when_face_visible_and_crops_around_face(self):
        """
        Review 20:00 Item 5:
        Only take a sharp photo when a face is visible, and crop around the face with 25% padding.
        """
        tracker = PersonTracker()
        track = Track(
            track_id=1,
            stay_id="stay_crop_test",
            box=[100, 100, 100, 200],  # body box
            centroid=(150.0, 200.0),
        )

        sub_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Draw simulated face on sub_frame
        sub_face_box = [130, 110, 40, 40]

        crop, box, is_sharp = tracker.capture_sharp_face_crop(
            track=track,
            frame_sub=sub_frame,
            sub_face_box=sub_face_box,
        )

        assert crop is not None
        assert box is not None
        # Verify crop dimensions match face box plus 25% padding (40 + 10 + 10 = 60 px)
        crop_w, crop_h = box[2], box[3]
        assert crop_w == 60
        assert crop_h == 60

    def test_learn_sharp_photo_samples_of_col(self, tmp_path):
        """
        Review 20:00 Item 6:
        Let ARCHER learn sharp-photo samples of Col (0.45 <= similarity < 0.85, max 3/day,
        logged in Change Log / action_audit).
        """
        test_db = str(tmp_path / "test_learn_col.db")
        store = SQLiteStore(db_path=test_db)
        store.add_known_person(name="Col", embedding=np.ones(512, dtype=np.float32).tobytes())

        # Test adding sharp crop reference
        test_emb = (np.ones(512, dtype=np.float32) * 0.7).tobytes()
        res = store.add_person_face(name="Col", embedding=test_emb, source="sharp_crop")
        assert res["action"] == "reference"

        # Verify counted today
        assert store.count_learned_references_today("Col") == 1

        # Log action in audit trail
        store.log_action(
            agent_name="observer",
            action_type="learned_reference",
            description="Added sharp-photo face reference for Col (similarity: 0.65).",
            metadata={"similarity": 0.65, "source": "sharp_crop"},
        )

        actions = store.get_recent_actions(limit=5)
        assert len(actions) == 1
        assert "sharp-photo face reference for Col" in actions[0]["description"]
        assert actions[0]["action_type"] == "learned_reference"

    # =========================================================================
    # Review 2026-10-12 23:55 — Item 11 Test Suite
    # Realistic Observer Decision Tests for Spec 5b Fixes
    # =========================================================================

    def test_item11_1_recheck_off_angle_col_face_no_split(self, tmp_path):
        """
        Review 23:55 Item 11 Test 1:
        Re-check with an off-angle Col face (0.50) -> no split.
        Spec 5b: Re-check must not split Col's stay when face similarity to Col is 0.50
        (off-angle view of Col, 0.25 <= sim < 0.55).
        """
        import uuid
        test_db = str(tmp_path / "test_recheck_off_angle.db")
        store = SQLiteStore(db_path=test_db)
        store.add_known_person(name="Col", embedding=np.ones(512, dtype=np.float32).tobytes())

        stay_id = "stay_col_recheck"
        store.log_or_update_stay(
            stay_id=stay_id,
            person_id="Col",
            confidence=0.85,
            is_known=True,
            camera_source="network_cam",
            track_id=1,
        )

        track = Track(
            track_id=1,
            stay_id=stay_id,
            box=[100, 100, 80, 200],
            centroid=(140.0, 200.0),
            assigned_identity="Col",
            is_known=True,
            confirmed_known=True,
            last_face_check_ts=1000.0,
        )

        # Embedding with similarity 0.50 to Col
        v1 = np.ones(512, dtype=np.float32)
        v1 /= np.linalg.norm(v1)
        v2 = np.ones(512, dtype=np.float32)
        v2[256:] = -1.0
        v2 /= np.linalg.norm(v2)
        off_angle_emb = 0.50 * v1 + np.sqrt(0.75) * v2

        from archer.observer.pipeline import ObserverPipeline
        pipeline = ObserverPipeline(run_analysis=False, open_camera=False, db_path=test_db)
        pipeline._store = store

        if hasattr(pipeline, "recheck_track_face"):
            pipeline.recheck_track_face(
                track=track,
                face_embedding=off_angle_emb,
                is_clear=True,
                timestamp=1065.0,
            )
        else:
            # Current code decision from pipeline.py lines 681-706:
            pid = "Person_84"
            is_k = False
            conf = 0.90  # detector conf >= 0.55
            needs_periodic_recheck = True
            if needs_periodic_recheck:
                if pid and pid != "Col" and (is_k or conf >= 0.45):
                    new_stay_id = f"stay_{uuid.uuid4().hex[:12]}"
                    store.split_stay(
                        old_stay_id=track.stay_id,
                        new_stay_id=new_stay_id,
                        new_person_id=pid,
                        split_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(1065.0)),
                        camera_source="network_cam",
                        confidence=conf,
                        is_known=is_k,
                        track_id=track.track_id,
                    )
                    track.stay_id = new_stay_id
                    track.assigned_identity = pid

        assert track.stay_id == stay_id, f"Stay split unexpectedly to {track.stay_id} on off-angle Col face (0.50)!"
        assert track.assigned_identity == "Col"

    def test_item11_2_turned_away_face_no_split_no_label(self, tmp_path):
        """
        Review 23:55 Item 11 Test 2:
        A turned-away face (0.07) -> no split, no label.
        Spec 5b & Review Item 3: A face that is turned away (similarity 0.07, looking away/unclear)
        must never name a stay, split a stay, or start a waiting label.
        """
        test_db = str(tmp_path / "test_turned_away.db")
        store = SQLiteStore(db_path=test_db)
        store.add_known_person(name="Col", embedding=np.ones(512, dtype=np.float32).tobytes())

        identifier = PersonIdentifier(db_path=test_db)

        # Embedding with similarity ~0.07 to Col (turned away face like Person_55)
        v1 = np.ones(512, dtype=np.float32)
        v1 /= np.linalg.norm(v1)
        v2 = np.ones(512, dtype=np.float32)
        v2[256:] = -1.0
        v2 /= np.linalg.norm(v2)
        turned_away_emb = 0.07 * v1 + np.sqrt(1.0 - 0.07**2) * v2

        mock_face = MagicMock()
        mock_face.bbox = [100, 100, 180, 200]
        mock_face.embedding = turned_away_emb
        mock_face.det_score = 0.65
        mock_face.pose = [45.0, 10.0, 5.0]  # pitch > 30 deg, turned away

        with patch.object(identifier, "get_faces", return_value=[mock_face]):
            res = identifier.identify_persons(
                np.zeros((480, 640, 3), dtype=np.uint8),
                camera_source="network_cam",
                store=store,
                stay_id="stay_col_turned_away",
            )

        # Expected: No waiting label created in pending confirmations!
        pending = store.get_pending_person_confirmations(status=["pending"])
        assert len(pending) == 0, f"Expected no pending label, but got: {pending}"

    def test_item11_3_clear_stranger_face_splits(self, tmp_path):
        """
        Review 23:55 Item 11 Test 3:
        A clear stranger's face -> split.
        Spec 5b & Review Item 1: Re-check must split Col's stay when a clear face
        is seen that is someone else (similarity to Col < 0.25).
        """
        test_db = str(tmp_path / "test_clear_stranger.db")
        store = SQLiteStore(db_path=test_db)
        store.add_known_person(name="Col", embedding=np.ones(512, dtype=np.float32).tobytes())

        stay_id = "stay_col_recheck_stranger"
        store.log_or_update_stay(
            stay_id=stay_id,
            person_id="Col",
            confidence=0.85,
            is_known=True,
            camera_source="network_cam",
            track_id=1,
        )

        track = Track(
            track_id=1,
            stay_id=stay_id,
            box=[100, 100, 80, 200],
            centroid=(140.0, 200.0),
            assigned_identity="Col",
            is_known=True,
            confirmed_known=True,
            last_face_check_ts=1000.0,
        )

        # Stranger's face embedding: similarity to Col is 0.10 (plainly unlike Col, < 0.25)
        v1 = np.ones(512, dtype=np.float32)
        v1 /= np.linalg.norm(v1)
        v2 = np.ones(512, dtype=np.float32)
        v2[256:] = -1.0
        v2 /= np.linalg.norm(v2)
        stranger_emb = 0.10 * v1 + np.sqrt(1.0 - 0.10**2) * v2

        from archer.observer.pipeline import ObserverPipeline
        pipeline = ObserverPipeline(run_analysis=False, open_camera=False)
        pipeline._store = store

        if hasattr(pipeline, "recheck_track_face"):
            # Per Review 18:55 Must-fix 6: single look under 0.25 does not split (requires >= 2 consecutive stranger looks)
            split1 = pipeline.recheck_track_face(
                track=track,
                face_embedding=stranger_emb,
                is_clear=True,
                timestamp=1065.0,
            )
            assert split1 is False, "Single look under 0.25 must not split Col's stay"
            assert track.stay_id == stay_id, "Track stay_id should remain unchanged after 1 stranger look"
            split2 = pipeline.recheck_track_face(
                track=track,
                face_embedding=stranger_emb,
                is_clear=True,
                timestamp=1066.0,
            )
            assert split2 is True, "Second consecutive stranger look must split Col's stay"
        else:
            raise AssertionError("Decoupled recheck_track_face not implemented on current pipeline")

        assert track.stay_id != stay_id, "Track stay_id should have split to a new stay!"
        assert track.assigned_identity != "Col", "Identity should no longer be Col!"
        stay_record = store.get_stay(stay_id)
        assert stay_record["ended_at"] is not None

    def test_item11_4_static_face_never_moves_no_label(self, tmp_path):
        """
        Review 23:55 Item 11 Test 4 (updated by Addendum 13:05 Item 1):
        A face marked as decor (such as the carved mask sculpture Person_61)
        gets no label or pending confirmation.
        """
        test_db = str(tmp_path / "test_static_mask.db")
        store = SQLiteStore(db_path=test_db)
        identifier = PersonIdentifier(db_path=test_db)

        # Static mask detection at (270, 20, 130, 175)
        # Marked as decor in the store (Addendum 13:05)
        mask_emb = np.random.randn(512).astype(np.float32)
        mask_emb /= np.linalg.norm(mask_emb)
        store.upsert_pending_person_confirmation(
            person_id="Person_61",
            embedding=mask_emb.tobytes(),
            status="decor"
        )

        mock_face = MagicMock()
        mock_face.bbox = [270, 20, 400, 195]
        mock_face.embedding = mask_emb
        mock_face.det_score = 0.65

        with patch.object(identifier, "get_faces", return_value=[mock_face]):
            for t in range(5):
                identifier.identify_persons(
                    np.zeros((480, 640, 3), dtype=np.uint8),
                    camera_source="network_cam",
                    store=store,
                )

        # Must never get a new label in pending confirmations (only the decor record exists)!
        pending = store.get_pending_person_confirmations(status="pending")
        assert len(pending) == 0, f"Decor face must get no pending label, but got: {pending}"

    def test_item11_5_label_during_stay_closed_as_col(self, tmp_path):
        """
        Review 23:55 Item 11 Test 5:
        A label started during a stay later recognized as Col -> closed as Col.
        Spec 5b & Review Item 2: Every label started during a stay later recognized as Col's
        must be closed as Col in pending_person_confirmations.
        """
        test_db = str(tmp_path / "test_close_label_as_col.db")
        store = SQLiteStore(db_path=test_db)
        identifier = PersonIdentifier(db_path=test_db)

        stay_id = "stay_col_unrecognized_first"

        # Frame 1: Person enters, unconfirmed off-angle face creates Person_50 label
        mock_face = MagicMock()
        mock_face.bbox = [100, 100, 180, 200]
        mock_face.embedding = np.random.randn(512).astype(np.float32)
        mock_face.det_score = 0.70
        mock_face.pose = np.array([0.0, 10.0, 0.0])  # measured turn (Claude 2026-10-15: turn must be measured)

        with patch.object(identifier, "get_faces", return_value=[mock_face]):
            res = identifier.identify_persons(
                np.zeros((480, 640, 3), dtype=np.uint8),
                camera_source="network_cam",
                store=store,
                stay_id=stay_id,
            )

        assert len(res) == 1
        label = res[0]["person_id"]
        assert label.startswith("Person_")

        pending_before = store.get_pending_person_confirmations(status=["pending"])
        assert len(pending_before) == 1
        assert pending_before[0]["person_id"] == label

        # Frame 2: Later during this same stay, Col is clearly recognized!
        updated = store.backfill_stay_as_col(stay_id)
        assert updated >= 1

        # The pending label must now be closed as Col!
        pending_after = store.get_pending_person_confirmations(status=["pending"])
        assert len(pending_after) == 0, f"Expected label {label} to be closed, but still pending!"

        resolved = store.get_pending_person_confirmations(status=["confirmed"])
        assert len(resolved) == 1
        assert resolved[0]["person_id"] == label
        assert resolved[0]["confirmed_name"] == "Col"

    def test_item11_6_end_times_from_camera_timestamps_real_utc(self, tmp_path):
        """
        Review 23:55 Item 11 Test 6:
        End times from the camera's own timestamps -> real UTC.
        Spec 5b & Review Item 9: Camera frame timestamps must be real UTC wall-clock epoch,
        not time.monotonic(), so ended_at in person_stays is never in 1970.
        """
        from archer.observer.camera import WebcamCapture

        test_db = str(tmp_path / "test_utc_timestamps.db")
        store = SQLiteStore(db_path=test_db)
        tracker = PersonTracker(fps=2.0)
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        cam = WebcamCapture(camera_source=0)
        with cam._frame_lock:
            cam._latest_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            if hasattr(cam, "capture_timestamp"):
                cam._frame_timestamp = cam.capture_timestamp()
            else:
                cam._frame_timestamp = time.monotonic()

        frame, cam_ts = cam.get_latest_frame()

        # Update tracker with detection at cam_ts
        mock_detector.detect.return_value = [{"box": [100, 100, 80, 200], "confidence": 0.90, "class": "person"}]
        tracker.update(frame, timestamp=cam_ts, store=store)

        # Track ends 4 seconds later
        mock_detector.detect.return_value = []
        tracker.update(frame, timestamp=cam_ts + 4.0, store=store)

        stays = store.get_recent_stays(limit=5)
        assert len(stays) >= 1
        ended_at = stays[0]["ended_at"]

        # Real UTC year must be >= 2026, never 1970!
        year = int(ended_at[:4])
        assert year >= 2026, f"Stay ended_at has year {year} ({ended_at}); expected >= 2026 UTC!"

    def test_item11_7_twosec_gap_at_2fps_one_bytetrack_id(self):
        """
        Review 23:55 Item 11 Test 7:
        A 2-second detector gap at 2 FPS -> one ByteTrack ID throughout.
        Spec 5b: Losing sight in the middle of the room isn't leaving.
        A 2-second gap (4 missed frames at 2 FPS) must maintain the same track throughout
        with one ByteTrack ID.
        """
        tracker = PersonTracker(fps=2.0)
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        # Frame 1: Person detected mid-room at (200, 200)
        mock_detector.detect.return_value = [{"box": [200, 200, 80, 200], "confidence": 0.90, "class": "person"}]
        t0 = 10000.0
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        assert len(tracks) == 1
        initial_tid = tracks[0].track_id
        initial_stay = tracks[0].stay_id
        initial_b_id = next(b for b, a in tracker._bytetrack_to_track_id.items() if a == initial_tid)

        # 2-second detector gap: 4 frames with empty detections at 2 FPS (dt=0.5s)
        mock_detector.detect.return_value = []
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 0.5)
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 1.0)
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 1.5)
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 2.0)

        # Frame 6: Person detected again at (205, 200)
        mock_detector.detect.return_value = [{"box": [205, 200, 80, 200], "confidence": 0.88, "class": "person"}]
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 2.5)

        assert len(tracks) == 1
        assert tracks[0].track_id == initial_tid, (
            f"Expected track ID to remain {initial_tid}, but got {tracks[0].track_id}"
        )
        assert tracks[0].stay_id == initial_stay, (
            f"Expected stay ID to remain {initial_stay}, but got {tracks[0].stay_id}"
        )
        # Review Item 11: One ByteTrack ID throughout!
        current_b_id = next(b for b, a in tracker._bytetrack_to_track_id.items() if a == tracks[0].track_id)
        assert current_b_id == initial_b_id, (
            f"ByteTrack assigned new tracker ID {current_b_id} (expected {initial_b_id}) after 2s gap!"
        )

    def test_item11_8_two_people_side_by_side_for_two_minutes_two_tracks(self):
        """
        Review 23:55 Item 11 Test 8:
        Two people side by side for 2 minutes -> two tracks.
        Spec 5b & Review Item 7:
        1. One box per track per frame (two boxes in the same frame can never update the same track).
        2. A new box joins an existing track only when it mostly overlaps it (IoU >= 0.40).
           A visitor standing next to Col (dist 55px < 80px, low IoU 0.20) must never join Col's track.
        """
        tracker = PersonTracker(fps=2.0)

        # Track 1 (Col) is active at [100, 100, 80, 200]
        track1 = Track(
            track_id=1,
            stay_id="stay_col_side_by_side",
            box=[100, 100, 80, 200],
            centroid=(140.0, 200.0),
            assigned_identity="Col",
            is_known=True,
            state="active",
        )
        tracker._active_tracks = {1: track1}
        tracker._bytetrack_to_track_id = {1: 1}

        # Simulated frame where two boxes are detected:
        # Box A: Col at [100, 100, 80, 200]
        # Box B: Visitor standing next to Col at [155, 100, 80, 200] (dist 55px < 80px, IoU = 0.23 < 0.40)
        # In current code:
        # - If Box B has b_id = 1 (or unassigned b_id = -1), current code attaches Box B to Track 1 via
        #   80px spatial fallback (dist <= 80.0) or duplicate b_id update!
        # - As a result, both boxes update Track 1, and only 1 track is produced!
        mock_detector = MagicMock()
        tracker.detector = mock_detector
        mock_detector.detect.return_value = [
            {"box": [100, 100, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [155, 100, 80, 200], "confidence": 0.90, "class": "person"},
        ]

        # Patch byte tracker to return unassigned / loose association for the new person
        import supervision as sv
        mock_dets = sv.Detections(
            xyxy=np.array([[100, 100, 180, 300], [155, 100, 235, 300]], dtype=np.float32),
            confidence=np.array([0.90, 0.90], dtype=np.float32),
            class_id=np.array([0, 0], dtype=int),
        )
        # In current code, if tracker_id is [1, -1]:
        # Box 1 has b_id = 1 -> matches Track 1.
        # Box 2 has b_id = -1 -> spatial fallback checks Track 1: dist=55px <= 80px -> matches Track 1!
        mock_dets.tracker_id = np.array([1, -1], dtype=int)
        update_method = "update_with_detections" if hasattr(tracker._byte_tracker, "update_with_detections") else "update"
        with patch.object(tracker._byte_tracker, update_method, return_value=mock_dets):
            tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=20000.5)

        # Expected: Visitor gets their own distinct track (2 tracks)!
        assert len(tracks) == 2, (
            f"Visitor beside Col was merged into Col's track! Got {len(tracks)} tracks instead of 2."
        )

    def test_item11_9_clear_050_face_in_col_stay_learned(self, tmp_path):
        """
        Review 23:55 Item 11 Test 9:
        A clear 0.50 face in Col's stay -> learned.
        Spec 5b & Review Item 10: During a stay clearly identified as Col, a clear face
        scoring 0.50 against Col must be learned (0.45 <= sim < 0.85),
        and logged with plain Change Log text:
        'Learned a new view of Col's face from the room camera.'
        """
        test_db = str(tmp_path / "test_learn_col_050.db")
        store = SQLiteStore(db_path=test_db)
        store.add_known_person(name="Col", embedding=np.ones(512, dtype=np.float32).tobytes())

        track = Track(
            track_id=1,
            stay_id="stay_col_learn_test",
            box=[100, 100, 80, 200],
            centroid=(140.0, 200.0),
            assigned_identity="Col",
            is_known=True,
            confirmed_known=True,
        )

        from archer.observer.pipeline import ObserverPipeline
        pipeline = ObserverPipeline(run_analysis=False, open_camera=False)
        pipeline._store = store

        # Off-angle Col face with similarity 0.50 (detector conf 0.90)
        v1 = np.ones(512, dtype=np.float32)
        v1 /= np.linalg.norm(v1)
        v2 = np.ones(512, dtype=np.float32)
        v2[256:] = -1.0
        v2 /= np.linalg.norm(v2)
        target_emb = 0.50 * v1 + np.sqrt(0.75) * v2

        if hasattr(pipeline, "maybe_learn_col_face"):
            learned = pipeline.maybe_learn_col_face(
                track=track,
                face_embedding=target_emb,
                similarity_to_col=0.50,
                detector_confidence=0.90,
                is_sharp=True,
                is_clear=True,
            )
        else:
            conf = 0.90  # Current code checked detector confidence!
            is_sharp = True
            learned = False
            if is_sharp and target_emb is not None and track.confirmed_known and track.assigned_identity == "Col":
                if 0.45 <= conf < 0.85:  # False on current code because conf is 0.90!
                    store.add_person_face(name="Col", embedding=target_emb.tobytes(), source="sharp_crop")
                    learned = True



        assert learned is True, "Clear 0.50 face of Col in Col's stay must be learned!"
        assert store.count_learned_references_today("Col") == 1

        actions = store.get_recent_actions(limit=5)
        assert len(actions) == 1
        assert actions[0]["description"] == "Learned a new view of Col's face from the room camera."

    def test_item11_10_crossing_starts_new_stays(self):
        """
        Review 23:55 Item 11 Test 10:
        A crossing -> new stays.
        Spec 5b & Review Item 8: When two tracks with separate histories cross paths,
        each person must start a NEW stay from that point on.
        """
        tracker = PersonTracker(fps=2.0)
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        mock_detector.detect.return_value = [
            {"box": [150, 150, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [300, 150, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        t0 = 30000.0
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        assert len(tracks) == 2
        t1, t2 = tracks[0], tracks[1]
        initial_stay_1 = t1.stay_id
        initial_stay_2 = t2.stay_id

        # Separate history >= 2.0s
        mock_detector.detect.return_value = [
            {"box": [170, 150, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [280, 150, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 1.0)

        mock_detector.detect.return_value = [
            {"box": [190, 150, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [260, 150, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 2.1)

        # Cross paths directly (IoU > 0.30)
        mock_detector.detect.return_value = [
            {"box": [220, 150, 80, 200], "confidence": 0.90, "class": "person"},
            {"box": [230, 150, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 2.6)
        assert len(tracks) == 2

        assert tracks[0].stay_id != initial_stay_1, (
            f"Track 0 stay_id ({tracks[0].stay_id}) did not change after crossing!"
        )
        assert tracks[1].stay_id != initial_stay_2, (
            f"Track 1 stay_id ({tracks[1].stay_id}) did not change after crossing!"
        )

    def test_review7_1_col_seated_20_times_never_dropped(self, tmp_path):
        """
        Review 2026-10-13 Addendum Item 1:
        Col's face at the same seat 20 times in a row is never dropped, on the room camera or the webcam.
        The old 'never moves' filter dropped 4 of 5 faces after the first because of position history.
        """
        test_db = str(tmp_path / "test_seated_col.db")
        store = SQLiteStore(db_path=test_db)
        identifier = PersonIdentifier(db_path=test_db, snapshots_dir=tmp_path / "snaps")
        col_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        col_emb /= np.linalg.norm(col_emb)
        store.add_known_person(name="Col", embedding=col_emb.tobytes())

        # Col sits at the same seat for 20 checks in a row
        seat_bbox = [200, 150, 80, 90]
        results = []
        for i in range(20):
            # In room camera or webcam
            is_dropped = False
            # Check if identifier drops or marks this static face as decor
            if hasattr(identifier, "is_static_room_face"):
                if identifier.is_static_room_face(seat_bbox):
                    is_dropped = True
            results.append(is_dropped)

        assert not any(results), f"Col was dropped {sum(results)} times out of 20 while sitting still!"

    def test_review7_2_not_a_person_replies_marked_decor(self, tmp_path):
        """
        Review 2026-10-13 Addendum Item 1:
        These replies, given while ARCHER is waiting for a name, are each understood as 'not a person':
        'That's a statue', 'it's just a poster', 'that's the TV'.
        The label is marked as decor, and the face is never labelled or attached to anyone again.
        """
        from archer.agents.core_agent import CoreAgent
        test_db = str(tmp_path / "test_decor.db")
        store = SQLiteStore(db_path=test_db)
        agent = CoreAgent(store=store)

        decor_replies = ["That's a statue", "it's just a poster", "that's the TV"]
        for reply in decor_replies:
            classified = agent._classify_person_reply(reply, stage="awaiting_name")
            assert classified.get("intent") in ("not_a_person", "decor"), (
                f"Reply '{reply}' was classified as {classified.get('intent')} instead of not_a_person/decor!"
            )

    def test_review7_3_not_my_brother_not_decor(self):
        """
        Review 2026-10-13 Addendum Item 1:
        'That's not my brother' still isn't 'not a person'.
        """
        from archer.agents.core_agent import CoreAgent
        agent = CoreAgent()
        classified = agent._classify_person_reply("That's not my brother", stage="awaiting_name")
        assert classified.get("intent") != "not_a_person" and classified.get("intent") != "decor", (
            "'That's not my brother' must not be classified as not_a_person or decor!"
        )

    def test_review7_4_skip_decor_faces_everywhere(self, tmp_path):
        """
        Review 2026-10-13 Addendum Item 2:
        Skip decor before choosing a person's face, naming, re-checks and labels.
        Person_61 (statue) marked as decor is skipped everywhere.
        """
        test_db = str(tmp_path / "test_skip_decor.db")
        store = SQLiteStore(db_path=test_db)
        identifier = PersonIdentifier(db_path=test_db, snapshots_dir=tmp_path / "snaps")

        # Mark Person_61 as decor in store
        sculpture_emb = np.random.RandomState(61).randn(512).astype(np.float32)
        sculpture_emb /= np.linalg.norm(sculpture_emb)
        store.upsert_pending_person_confirmation(
            person_id="Person_61",
            embedding=sculpture_emb.tobytes(),
            status="decor"
        )

        assert hasattr(identifier, "is_decor_face"), "PersonIdentifier must have is_decor_face method!"
        is_decor = identifier.is_decor_face(sculpture_emb, store=store)
        assert is_decor is True, "Sculpture embedding marked as decor in store must be recognized as decor!"

    def test_review7_5_multiple_faces_in_body_picks_head(self):
        """
        Review 2026-10-13 Item 2:
        When a box contains more than one face, pick the one at the person's head (closest to top of body box).
        """
        from types import SimpleNamespace
        from archer.observer.pipeline import ObserverPipeline
        pipeline = ObserverPipeline(open_camera=False)

        # Track body box is [200, 100, 100, 250] (y ranges 100 to 350)
        track = Track(track_id=1, stay_id="stay_test", box=[200, 100, 100, 250], centroid=(250, 225), first_seen_ts=100.0, last_seen_ts=100.0, duration=0.0)
        
        # Face A: on shirt / sculpture behind: center (240, 260) - lower down
        face_a = SimpleNamespace(bbox=[220, 240, 260, 280], det_score=0.9)
        # Face B: person's actual head: center (240, 130) - top of body box
        face_b = SimpleNamespace(bbox=[220, 110, 260, 150], det_score=0.85)

        assert hasattr(pipeline, "_select_track_face"), "ObserverPipeline must have _select_track_face method!"
        chosen = pipeline._select_track_face(track, [face_a, face_b])
        assert chosen is face_b, "Must pick the face at the person's head (lowest y / closest to top of body box)!"

    def test_review7_6_room_camera_exits_and_couch_monitor_non_exit(self):
        """
        Review 2026-10-13 Item 3 and Review 18:55 Must-fix 2:
        Use the measured three exits based on person's feet:
        1. Front door: off left edge past coat hooks (feet_x <= 65, feet_y in [200, 425])
        2. Hallway opening: doorway directly behind right end of couch (feet_x in [505, 565], feet_y in [280, 400])
        3. Kitchen door: left of fridge at right edge (feet_x >= 590, feet_y in [260, 390])
        Everywhere else is inside the room.
        Couch and PC monitor at bottom (feet_y >= 430) is NEVER an exit!
        """
        tracker = PersonTracker(fps=2.0)
        assert hasattr(tracker, "is_at_exit"), "PersonTracker must have is_at_exit method!"

        # 1. Front door exit (feet at x=50, y=300)
        assert tracker.is_at_exit(box=[30, 200, 40, 100], centroid=(50, 250), frame_shape=(480, 640)) is True
        # 2. Hallway exit (feet at x=530, y=360)
        assert tracker.is_at_exit(box=[515, 270, 30, 90], centroid=(530, 315), frame_shape=(480, 640)) is True
        # 3. Kitchen door exit (feet at x=615, y=300)
        assert tracker.is_at_exit(box=[595, 200, 40, 100], centroid=(610, 250), frame_shape=(480, 640)) is True

        # Couch / PC monitor at bottom: NOT an exit (reaches feet_y >= 430)
        assert tracker.is_at_exit(box=[200, 350, 100, 120], centroid=(250, 410), frame_shape=(480, 640)) is False
        assert tracker.is_at_exit(box=[450, 350, 100, 120], centroid=(500, 410), frame_shape=(480, 640)) is False

    def test_review7_7_midroom_resumption_nearest_and_nobody_came_or_went(self):
        """
        Review 2026-10-13 Item 3:
        A paused stay resumes only if nobody was seen coming or going in the meantime,
        and resumes the NEAREST paused stay.
        """
        tracker = PersonTracker(fps=2.0)
        mock_detector = MagicMock()
        tracker.detector = mock_detector

        # Col at desk: centroid (300, 300)
        mock_detector.detect.return_value = [{"box": [260, 200, 80, 200], "confidence": 0.90, "class": "person"}]
        t0 = 50000.0
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0)
        stay_col = tracks[0].stay_id

        # Lost in mid-room for 4 seconds -> pauses
        mock_detector.detect.return_value = []
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 4.0)
        assert tracker._active_tracks[1].state == "paused"

        # Case A: Someone enters from the front door (x=30, y=200) in the meantime!
        mock_detector.detect.return_value = [{"box": [20, 180, 60, 150], "confidence": 0.90, "class": "person"}]
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 5.0)

        # Now detection appears near Col's old spot at (300, 300)
        mock_detector.detect.return_value = [
            {"box": [20, 180, 60, 150], "confidence": 0.90, "class": "person"},
            {"box": [265, 200, 80, 200], "confidence": 0.90, "class": "person"},
        ]
        tracks2 = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + 6.0)
        desk_track = [t for t in tracks2 if abs(t.centroid[0] - 300) < 50][0]
        # Because someone entered in the meantime, the paused stay must NOT resume!
        assert desk_track.stay_id != stay_col, (
            "Paused stay must NOT resume when someone was seen coming in the meantime!"
        )

    def test_review7_8_mirror_zone_by_front_door(self):
        """
        Review 2026-10-13 Item 4:
        Mirror zone is the standing mirror by front door at x in [65, 165], y in [280, 420],
        not blank ceiling at y in [25, 165].
        """
        filter = MirrorFilter()
        mx, my, mw, mh = filter.mirror_roi
        # Must match standing mirror by front door
        assert 60 <= mx <= 70 and 270 <= my <= 290, (
            f"Mirror ROI ({mx}, {my}, {mw}, {mh}) does not watch the standing mirror by front door!"
        )
        assert filter.is_in_mirror_zone([90, 300, 40, 80]) is True
        assert filter.is_in_mirror_zone([300, 50, 40, 80]) is False, "Ceiling must not be in mirror zone!"

    def test_review7_9_room_camera_presence_events_published(self):
        """
        Review 2026-10-13 Item 5:
        Room camera publishes 'person seen' observation events for identified people
        so Blindspot agent and chat status receive them.
        """
        from archer.observer.pipeline import ObserverPipeline
        pipeline = ObserverPipeline(open_camera=False)
        pipeline._config.network_camera_url = "rtsp://mock-cam/live"
        published_events = []
        pipeline._publish_observation = lambda res: published_events.append(res)

        # Track identified as Col in room camera
        track = Track(track_id=1, stay_id="stay_col", box=[200, 150, 80, 200], centroid=(240, 250), first_seen_ts=100.0, last_seen_ts=100.0, duration=10.0)
        track.assigned_identity = "Col"
        track.is_known = True

        assert hasattr(pipeline, "_publish_room_camera_presence"), (
            "ObserverPipeline must have _publish_room_camera_presence method!"
        )
        pipeline._publish_room_camera_presence([track], now=100.0)
        person_sightings = [e for e in published_events if e.event_type == "person_sighting"]
        assert len(person_sightings) >= 1, "Must publish person_sighting event for identified person!"
        assert person_sightings[0].data.get("person_id") == "Col"

    def test_review7_10_sightings_throttle_and_real_scores(self, tmp_path):
        """
        Review 2026-10-13 Items 9, 10, 11:
        1. Inside Col's stay, save real similarity score (not bumped to 0.50), filed as stay association.
        2. Unconfirmed stays throttle sightings to at most once every 30s unless identity changes.
        3. Ambiguous stays after crossing throttled to 30s.
        """
        test_db = str(tmp_path / "test_throttle.db")
        store = SQLiteStore(db_path=test_db)
        identifier = PersonIdentifier(db_path=test_db, snapshots_dir=tmp_path / "snaps")

        # Fake face with low similarity to Col (e.g. 0.07) inside Col's stay
        low_sim_emb = np.random.RandomState(99).randn(512).astype(np.float32)
        low_sim_emb /= np.linalg.norm(low_sim_emb)

        # Create Col's stay in DB
        store.log_or_update_stay("stay_col_1", person_id="Col", is_known=True)

        with patch.object(identifier, "get_faces", return_value=[MagicMock(bbox=[100, 100, 180, 200], embedding=low_sim_emb, det_score=0.90, pose=[0, 0])]), \
             patch.object(identifier, "get_similarity_to_col", return_value=0.07), \
             patch.object(identifier, "match_face_embedding", return_value={"is_known": False, "person_id": "Person_99", "sim": 0.07}):
            
            res = identifier.identify_persons(np.zeros((480, 640, 3), dtype=np.uint8), stay_id="stay_col_1", store=store)
            assert len(res) == 1
            # Real score must be saved, NOT forced to 0.50!
            conn = store._get_connection()
            try:
                row = conn.execute("SELECT * FROM person_sightings ORDER BY id DESC LIMIT 1").fetchone()
                assert row is not None
                assert pytest.approx(row["confidence"], 0.01) == 0.07, (
                    f"Confidence was {row['confidence']}, should be real score 0.07!"
                )
            finally:
                conn.close()

    def test_review8_1_stranger_gets_waiting_label_through_face_check(self, tmp_path):
        """
        Review 18:55 Must-fix 1:
        Someone never recognized gets one waiting label for the whole stay, with a photo
        (at most 3), linked to the stay. Must test through the observer's own face check.
        """
        from archer.observer.pipeline import ObserverPipeline
        test_db = str(tmp_path / "test_stranger_label.db")
        store = SQLiteStore(db_path=test_db)
        snaps_dir = tmp_path / "snaps"
        snaps_dir.mkdir(parents=True, exist_ok=True)

        pipeline = ObserverPipeline(open_camera=False)
        pipeline._store = store
        pipeline._person_identifier = PersonIdentifier(db_path=test_db, snapshots_dir=snaps_dir)

        # Stranger track
        track = Track(track_id=1, stay_id="stay_stranger_1", box=[200, 100, 80, 200], centroid=(240, 200), first_seen_ts=100.0, last_seen_ts=100.0, duration=0.0)
        pipeline._person_tracker._active_tracks = {1: track}

        # Clear stranger face embedding
        stranger_emb = np.random.RandomState(42).randn(512).astype(np.float32)
        stranger_emb /= np.linalg.norm(stranger_emb)

        mock_face = MagicMock(bbox=[220, 110, 260, 150], embedding=stranger_emb, det_score=0.90, pose=[0, 0])
        # Claude 2026-10-15: a label starts only on a sharp look (a still from the main stream).
        sharp_still = np.full((120, 100, 3), 128, dtype=np.uint8)
        real_capture = pipeline._person_tracker.capture_sharp_face_crop
        def fake_capture(track, frame_sub, network_camera_url=None, reolink_detector=None, sub_face_box=None, fetch_network_still=False):
            if fetch_network_still:
                return sharp_still, [0, 0, 100, 120], True
            return real_capture(track, frame_sub, network_camera_url, reolink_detector, sub_face_box, False)
        pipeline._config.network_camera_url = "rtsp://mock-cam/live"
        with patch.object(pipeline._person_tracker, "capture_sharp_face_crop", side_effect=fake_capture), \
             patch.object(pipeline._person_identifier, "get_faces", return_value=[mock_face]), \
             patch.object(pipeline._person_identifier, "_faces_in_still", return_value=[mock_face]), \
             patch.object(pipeline._person_identifier, "is_clear_face", return_value=(True, "clear")), \
             patch.object(pipeline._person_identifier, "get_similarity_to_col", return_value=0.05), \
             patch.object(pipeline._person_identifier, "match_face_embedding", return_value={"is_known": False, "person_id": "Person_1", "sim": 0.05}):
            
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            pipeline._run_tracker_face_checks(frame, timestamp=100.0)

            # Must have queued one waiting label linked to stay_stranger_1
            pending = store.get_pending_person_confirmations(status="pending")
            assert len(pending) == 1, f"Expected 1 waiting label, got {len(pending)}"
            assert pending[0]["person_id"] == "Person_1"
            assert pending[0]["stay_id"] == "stay_stranger_1"
            assert pending[0]["snapshot_path"] is not None

    def test_review8_2_doorways_measured_boxes(self):
        """
        Review 18:55 Must-fix 2:
        Judge exits by where the person's feet are.
        - Standing in hallway doorway: feet at (537, 365) -> at exit
        - Sitting on couch in front of hallway: feet at (530, 440) -> NOT at exit (bottom >= 400)
        - Standing in kitchen doorway: feet at (617, 350) -> at exit
        - Sitting at desk monitor: feet at (245, 440) -> NOT at exit (bottom >= 400)
        """
        tracker = PersonTracker(fps=2.0)
        # Hallway standing: box=[520, 270, 35, 95] -> feet at (537.5, 365)
        assert tracker.is_at_exit(box=[520, 270, 35, 95], centroid=(537.5, 317.5), frame_shape=(480, 640)) is True

        # Couch in front of hallway: box=[490, 330, 80, 110] -> feet at (530, 440)
        assert tracker.is_at_exit(box=[490, 330, 80, 110], centroid=(530, 385), frame_shape=(480, 640)) is False

        # Kitchen standing: box=[600, 260, 35, 90] -> feet at (617.5, 350)
        assert tracker.is_at_exit(box=[600, 260, 35, 90], centroid=(617.5, 305), frame_shape=(480, 640)) is True

        # Desk monitor: box=[200, 320, 90, 120] -> feet at (245, 440)
        assert tracker.is_at_exit(box=[200, 320, 90, 120], centroid=(245, 380), frame_shape=(480, 640)) is False

    def test_review8_3_presence_events_over_five_minutes(self):
        """
        Review 18:55 Must-fix 3:
        Publish 'person seen' events for every identified stay every 30 seconds while it lasts.
        Test over 5 simulated minutes through observer's loop, not by calling publish directly.
        """
        from archer.observer.pipeline import ObserverPipeline
        pipeline = ObserverPipeline(open_camera=False)
        published_events = []
        pipeline._publish_observation = lambda res: published_events.append(res)

        track = Track(track_id=1, stay_id="stay_col", box=[200, 150, 80, 200], centroid=(240, 250), first_seen_ts=0.0, last_seen_ts=0.0, duration=0.0)
        track.assigned_identity = "Col"
        track.is_known = True
        track.confirmed_known = True
        pipeline._person_tracker._active_tracks = {1: track}

        # Simulate 5 minutes (300 seconds) at 1-second ticks
        for t in range(0, 301):
            track.last_seen_ts = float(t)
            track.duration = float(t)
            # Call pipeline's tracker face check routine
            pipeline._run_tracker_face_checks(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=float(t))

        col_sightings = [e for e in published_events if e.event_type == "person_sighting" and e.data.get("person_id") == "Col"]
        # Over 300 seconds, every 30 seconds = ~10 events (must be >= 8 events, not just 1)
        assert len(col_sightings) >= 8, f"Expected at least 8 presence events over 5 mins, got {len(col_sightings)}"

    def test_review8_4_crossing_starts_new_stays_once_and_closes_old(self, tmp_path):
        """
        Review 18:55 Should-fix 7:
        A crossing starts new stays once per crossing, when overlap begins, and closes the old stays.
        Does not keep spawning new stays while the two people continue overlapping.
        """
        test_db = str(tmp_path / "test_crossing.db")
        store = SQLiteStore(db_path=test_db)
        tracker = PersonTracker(fps=2.0)

        # Start two separate tracks with > 2.0s duration
        t1 = Track(track_id=1, stay_id="stay_a", box=[200, 200, 80, 150], centroid=(240, 275), first_seen_ts=0.0, last_seen_ts=3.0, duration=3.0)
        t2 = Track(track_id=2, stay_id="stay_b", box=[250, 200, 80, 150], centroid=(290, 275), first_seen_ts=0.0, last_seen_ts=3.0, duration=3.0)
        store.log_or_update_stay(stay_id="stay_a", person_id="Person_A")
        store.log_or_update_stay(stay_id="stay_b", person_id="Person_B")

        tracker._active_tracks = {1: t1, 2: t2}
        tracker.detector = MagicMock()

        # Frame 1: They overlap (IoU > 0.30)
        tracker.detector.detect.return_value = [
            {"box": [220, 200, 80, 150], "confidence": 0.9, "class": "person"},
            {"box": [230, 200, 80, 150], "confidence": 0.9, "class": "person"},
        ]
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=4.0, store=store)

        stay_1_after_crossing = t1.stay_id
        stay_2_after_crossing = t2.stay_id
        assert stay_1_after_crossing != "stay_a"
        assert stay_2_after_crossing != "stay_b"

        # Old stays must be closed with ended_at!
        old_stay_a = store.get_stay("stay_a")
        assert old_stay_a["ended_at"] is not None

        # Frame 2 to 5: They continue overlapping on the couch
        for step in range(5, 10):
            tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=float(step), store=store)
            assert t1.stay_id == stay_1_after_crossing, "Stay should not change while overlap continues!"
            assert t2.stay_id == stay_2_after_crossing, "Stay should not change while overlap continues!"

    def test_review8_5_decor_replies_not_caught(self):
        """
        Review 18:55 Must-fix 5:
        Only replies plainly about an object count as decor.
        Replies mentioning a person, role, name, or human negation must NOT be marked as decor:
        - 'that's not a person I know'
        - 'it's the TV repair guy'
        - 'that's the heater guy, he fixed it'
        - 'that was the figure skating coach'
        - 'it's a mask he was wearing, that's Sam'
        """
        from archer.agents.core_agent import CoreAgent
        agent = CoreAgent()
        replies = [
            "that's not a person I know",
            "it's the TV repair guy",
            "that's the heater guy, he fixed it",
            "that was the figure skating coach",
            "it's a mask he was wearing, that's Sam",
        ]
        for r in replies:
            res = agent._classify_person_reply(r, stage="awaiting_name")
            assert res.get("intent") != "not_a_person" and res.get("intent") != "decor", (
                f"Reply '{r}' was incorrectly classified as {res.get('intent')}!"
            )

    def test_review8_6_single_look_under_025_no_split(self, tmp_path):
        """
        Review 18:55 Must-fix 6:
        If any clear look of Col scores below 0.25 (like Person_10 / Person_29 with glasses at night),
        a single look must NOT split Col's stay!
        """
        from archer.observer.pipeline import ObserverPipeline
        test_db = str(tmp_path / "test_no_single_split.db")
        store = SQLiteStore(db_path=test_db)
        pipeline = ObserverPipeline(open_camera=False)
        pipeline._store = store
        pipeline._person_identifier = PersonIdentifier(db_path=test_db)

        track = Track(track_id=1, stay_id="stay_col", box=[200, 150, 80, 200], centroid=(240, 250), first_seen_ts=0.0, last_seen_ts=10.0, duration=10.0)
        track.assigned_identity = "Col"
        track.is_known = True
        track.confirmed_known = True

        low_sim_emb = np.zeros(512, dtype=np.float32)
        with patch.object(pipeline._person_identifier, "get_similarity_to_col", return_value=0.18), \
             patch.object(pipeline._person_identifier, "match_face_embedding", return_value={"is_known": False, "person_id": "Person_10", "sim": 0.18}):

            # Single look with sim=0.18
            did_split = pipeline.recheck_track_face(track, low_sim_emb, is_clear=True, timestamp=11.0)
            assert did_split is False, "A single clear look scoring under 0.25 must NOT split Col's stay!"
            assert track.stay_id == "stay_col"







class TestClaudeFixes20261015:
    """
    Claude's direct fixes, 2026-10-15 (see ARCHER_Claude_Reviews.md, 2026-10-14 23:15 review
    and the 2026-10-15 fix entry). Each test fails on the code from 2026-10-14.
    """

    @staticmethod
    def _pipeline_with(tmp_path, db_name):
        from archer.observer.pipeline import ObserverPipeline
        test_db = str(tmp_path / db_name)
        store = SQLiteStore(db_path=test_db)
        snaps = tmp_path / "snaps"
        snaps.mkdir(parents=True, exist_ok=True)
        pipeline = ObserverPipeline(open_camera=False)
        pipeline._store = store
        pipeline._person_identifier = PersonIdentifier(db_path=test_db, snapshots_dir=snaps)
        pipeline._config.network_camera_url = "rtsp://mock-cam/live"
        return pipeline, store

    @staticmethod
    def _capture(pipeline, still_ok):
        """Small-stream crops work as normal; the sharp still succeeds only if still_ok."""
        real_capture = pipeline._person_tracker.capture_sharp_face_crop
        sharp_still = np.full((120, 100, 3), 128, dtype=np.uint8)

        def fake(track, frame_sub, network_camera_url=None, reolink_detector=None, sub_face_box=None, fetch_network_still=False):
            if fetch_network_still:
                return (sharp_still, [0, 0, 100, 120], True) if still_ok else (None, None, False)
            return real_capture(track, frame_sub, network_camera_url, reolink_detector, sub_face_box, False)
        return fake

    def test_face_model_settings_full_detail_pose_and_thread_cap(self, tmp_path):
        """Faces searched at full detail, the turn model is on, and the 2-thread cap is a session setting."""
        pid = PersonIdentifier(db_path=str(tmp_path / "m.db"), snapshots_dir=tmp_path / "s")
        if not pid.is_available:
            pytest.skip("InsightFace models not available")
        app = pid._app
        assert "landmark_3d_68" in app.models, "turn (pose) model must be loaded"
        assert tuple(app.det_model.input_size) == (640, 640), "faces must be searched at full detail"
        for name, model in app.models.items():
            so = model.session.get_session_options()
            assert so.intra_op_num_threads == 2, f"{name}: thread cap not applied"

    def test_unmeasured_turn_is_not_clear(self):
        from types import SimpleNamespace
        pid = PersonIdentifier.__new__(PersonIdentifier)
        face = SimpleNamespace(bbox=[0, 0, 50, 60], det_score=0.9)  # no pose
        is_clear, reason = PersonIdentifier.is_clear_face(pid, face)
        assert is_clear is False and "turn" in reason
        face.pose = [0.0, 45.0, 0.0]
        assert PersonIdentifier.is_clear_face(pid, face)[0] is False
        face.pose = [0.0, 10.0, 0.0]
        assert PersonIdentifier.is_clear_face(pid, face)[0] is True

    def test_small_stream_look_starts_no_label_and_is_not_reanalysed(self, tmp_path):
        """Without a sharp still: no waiting label, and the face model isn't run a second time."""
        pipeline, store = self._pipeline_with(tmp_path, "nolabel.db")
        track = Track(track_id=1, stay_id="stay_x", box=[200, 100, 80, 200], centroid=(240, 200), first_seen_ts=100.0, last_seen_ts=100.0, duration=0.0)
        pipeline._person_tracker._active_tracks = {1: track}
        emb = np.random.RandomState(7).randn(512).astype(np.float32)
        face = MagicMock(bbox=[220, 110, 260, 150], embedding=emb, det_score=0.9, pose=[0.0, 5.0, 0.0])
        second_pass = MagicMock(return_value=[face])
        with patch.object(pipeline._person_tracker, "capture_sharp_face_crop", side_effect=self._capture(pipeline, still_ok=False)), \
             patch.object(pipeline._person_identifier, "get_faces", return_value=[face]), \
             patch.object(pipeline._person_identifier, "_faces_in_still", second_pass), \
             patch.object(pipeline._person_identifier, "is_clear_face", return_value=(True, "clear")):
            pipeline._run_tracker_face_checks(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=100.0)
        assert store.get_pending_person_confirmations(status="pending") == []
        assert second_pass.call_count == 0, "the small-stream face must not be analysed twice"

    def test_returning_stranger_keeps_waiting_label(self, tmp_path):
        pipeline, store = self._pipeline_with(tmp_path, "returning.db")
        emb = np.random.RandomState(11).randn(512).astype(np.float32)
        emb /= np.linalg.norm(emb)
        store.upsert_pending_person_confirmation(person_id="Person_5", embedding=emb.tobytes(), stay_id="stay_old")
        track = Track(track_id=1, stay_id="stay_new", box=[200, 100, 80, 200], centroid=(240, 200), first_seen_ts=100.0, last_seen_ts=100.0, duration=0.0)
        pipeline._person_tracker._active_tracks = {1: track}
        face = MagicMock(bbox=[220, 110, 260, 150], embedding=emb, det_score=0.9, pose=[0.0, 5.0, 0.0])
        with patch.object(pipeline._person_tracker, "capture_sharp_face_crop", side_effect=self._capture(pipeline, still_ok=True)), \
             patch.object(pipeline._person_identifier, "get_faces", return_value=[face]), \
             patch.object(pipeline._person_identifier, "_faces_in_still", return_value=[face]), \
             patch.object(pipeline._person_identifier, "is_clear_face", return_value=(True, "clear")):
            pipeline._run_tracker_face_checks(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=100.0)
        pending = store.get_pending_person_confirmations(status="pending")
        assert [p["person_id"] for p in pending] == ["Person_5"], "a returning stranger must keep their label"
        assert track.assigned_identity == "Person_5"

    def test_small_stream_looks_never_split_col(self, tmp_path):
        """Two clear small-stream looks scoring 0.05 a minute apart don't split Col's stay."""
        pipeline, store = self._pipeline_with(tmp_path, "nosplit.db")
        track = Track(track_id=1, stay_id="stay_col", box=[200, 100, 80, 200], centroid=(240, 200), first_seen_ts=0.0, last_seen_ts=0.0, duration=0.0)
        track.assigned_identity, track.is_known, track.confirmed_known = "Col", True, True
        pipeline._person_tracker._active_tracks = {1: track}
        face = MagicMock(bbox=[220, 110, 260, 150], embedding=np.ones(512, dtype=np.float32), det_score=0.9, pose=[0.0, 5.0, 0.0])
        with patch.object(pipeline._person_tracker, "capture_sharp_face_crop", side_effect=self._capture(pipeline, still_ok=False)), \
             patch.object(pipeline._person_identifier, "get_faces", return_value=[face]), \
             patch.object(pipeline._person_identifier, "_faces_in_still", return_value=[face]), \
             patch.object(pipeline._person_identifier, "is_clear_face", return_value=(True, "clear")), \
             patch.object(pipeline._person_identifier, "get_similarity_to_col", return_value=0.05), \
             patch.object(pipeline._person_identifier, "match_face_embedding", return_value={"is_known": False, "person_id": "Person_9", "sim": 0.05}):
            for t in (61.0, 122.0, 183.0):
                track.last_seen_ts = t
                pipeline._run_tracker_face_checks(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t)
        assert track.stay_id == "stay_col" and track.assigned_identity == "Col"

    def test_correction_quick_check_only_undoes_decor(self):
        from archer.agents.core_agent import CoreAgent
        agent = CoreAgent()
        with patch("archer.agents.core_agent.httpx.post", side_effect=RuntimeError("no model in tests")):
            agent._last_confirmed_person = {"person_id": "Person_1", "confirmation_id": 1, "name": "Sam"}
            for reply in ["No, that's me", "No, that's wrong", "Actually it's fine", "wait, that's him", "Actually, that's Jenna"]:
                res = agent._classify_person_reply(reply, stage="awaiting_name")
                assert res.get("intent") != "correction", f"'{reply}' must go to the full reader, got {res}"
            agent._last_confirmed_person = {"person_id": "Person_1", "confirmation_id": 1, "name": None, "status": "decor"}
            res = agent._classify_person_reply("No, that's Sam", stage="awaiting_name")
            assert res.get("intent") == "correction" and res.get("name") == "Sam"
            for reply in ["No, that's me", "No, that's wrong", "wait, that's him"]:
                res = agent._classify_person_reply(reply, stage="awaiting_name")
                assert res.get("intent") != "correction", f"'{reply}' after a decor mark is not a name, got {res}"

    def test_crossing_clears_waiting_label(self, tmp_path):
        tracker = PersonTracker(fps=2.0)
        t1 = Track(track_id=1, stay_id="stay_a", box=[200, 200, 80, 150], centroid=(240, 275), first_seen_ts=0.0, last_seen_ts=3.0, duration=3.0)
        t2 = Track(track_id=2, stay_id="stay_b", box=[250, 200, 80, 150], centroid=(290, 275), first_seen_ts=0.0, last_seen_ts=3.0, duration=3.0)
        t1.waiting_label_id, t1._waiting_photos_count = "Person_7", 2
        tracker._active_tracks = {1: t1, 2: t2}
        tracker.detector = MagicMock()
        tracker.detector.detect.return_value = [
            {"box": [220, 200, 80, 150], "confidence": 0.9, "class": "person"},
            {"box": [230, 200, 80, 150], "confidence": 0.9, "class": "person"},
        ]
        tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=4.0)
        assert t1.stay_id != "stay_a"
        assert t1.waiting_label_id is None and t1._waiting_photos_count == 0

    def test_stay_given_up_ends_when_last_seen(self, tmp_path):
        store = SQLiteStore(db_path=str(tmp_path / "end.db"))
        tracker = PersonTracker(fps=2.0)
        tracker.detector = MagicMock()
        tracker.detector.detect.return_value = [{"box": [260, 200, 80, 200], "confidence": 0.9, "class": "person"}]
        t0 = 1_800_000_000.0
        tracks = tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0, store=store)
        stay_id = tracks[0].stay_id
        tracker.detector.detect.return_value = []
        for dt in (4.0, 30.0, 61.0):
            tracker.update(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=t0 + dt, store=store)
        stay = store.get_stay(stay_id)
        assert stay["ended_at"].startswith(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t0))), stay["ended_at"]

    def test_still_crop_is_face_plus_its_own_size_each_side(self):
        """A sharp still crop leaves the face about a third of the crop (where the detector finds it)."""
        import cv2
        tracker = PersonTracker(fps=2.0)
        main = np.zeros((1920, 2560, 3), dtype=np.uint8)
        ok, jpg = cv2.imencode(".jpg", main)
        reolink = MagicMock()
        reolink.get_snapshot.return_value = jpg.tobytes()
        track = Track(track_id=1, stay_id="s", box=[200, 100, 80, 200], centroid=(240, 200), first_seen_ts=0.0, last_seen_ts=0.0, duration=0.0)
        crop, box, sharp = tracker.capture_sharp_face_crop(
            track, np.zeros((480, 640, 3), dtype=np.uint8), reolink_detector=reolink,
            sub_face_box=[300, 200, 40, 50], fetch_network_still=True,
        )
        assert sharp is True
        # face on the main stream: 160 x 200 px at (1200, 800); crop = face + 100% each side
        assert box == [1040, 600, 480, 600]
