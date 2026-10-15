"""
ARCHER Body / Person Detector.

Uses the Col-approved YOLOX-Nano ONNX model via onnxruntime for fast, lightweight
body detection on 640x480 video frames (~17ms on CPU, Apache 2.0 license).
Provides automatic fallback to OpenCV HOG if the ONNX model is unavailable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional, Tuple
import cv2
import numpy as np
from loguru import logger

# Approved model specs (Spec Section 12, approved 2026-10-12)
# Source: https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx
# License: Apache 2.0
APPROVED_MODEL_PATH = "data/models/person_detector/yolox_nano.onnx"
APPROVED_MODEL_SHA256 = "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"


def _generate_yolox_grids_and_strides(
    input_size: tuple[int, int] = (416, 416),
    strides: tuple[int, ...] = (8, 16, 32),
) -> Tuple[np.ndarray, np.ndarray]:
    """Generate coordinate grid offsets and stride multipliers for YOLOX decoding."""
    grids = []
    expanded_strides = []
    for stride in strides:
        h, w = input_size[0] // stride, input_size[1] // stride
        xv, yv = np.meshgrid(np.arange(w), np.arange(h))
        grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
        grids.append(grid)
        shape = grid.shape[:2]
        expanded_strides.append(np.full((*shape, 1), stride))
    grids = np.concatenate(grids, 1)[0]
    expanded_strides = np.concatenate(expanded_strides, 1)[0]
    return grids, expanded_strides


class PersonDetector:
    """
    Lightweight person body detector.
    Detects full and partial human bodies (walking, seated, occluded) in video frames.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        input_size: tuple[int, int] = (416, 416),
        conf_thresh: float = 0.35,
        nms_thresh: float = 0.45,
    ) -> None:
        self._model_path = Path(model_path or APPROVED_MODEL_PATH)
        self._input_size = input_size
        self._conf_thresh = conf_thresh
        self._nms_thresh = nms_thresh
        self._session = None
        self._input_name = None
        self._hog = None
        self._grids, self._strides = _generate_yolox_grids_and_strides(input_size)

        self._init_detector()

    def _init_detector(self) -> None:
        """Initialize ONNX runtime session with CPU execution provider or fallback to HOG."""
        if self._model_path.exists():
            try:
                import onnxruntime as ort

                # Force single/few threads to keep background CPU footprint minimal (< 0.2% CPU at 2 FPS)
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.inter_op_num_threads = 1
                opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

                self._session = ort.InferenceSession(
                    str(self._model_path),
                    sess_options=opts,
                    providers=["CPUExecutionProvider"],
                )
                self._input_name = self._session.get_inputs()[0].name
                logger.info(f"PersonDetector: Loaded approved YOLOX-Nano ONNX model from {self._model_path}")
                return
            except Exception as e:
                logger.warning(f"PersonDetector: Failed loading ONNX model ({e}), falling back to HOG.")

        # Stand-in fallback: OpenCV HOG
        try:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self._hog = hog
            logger.info("PersonDetector: Initialized OpenCV HOG person detector fallback.")
        except Exception as e:
            logger.warning(f"PersonDetector: Failed initializing HOG fallback ({e}).")

    @property
    def is_available(self) -> bool:
        return (self._session is not None) or (self._hog is not None)

    @property
    def is_onnx_model(self) -> bool:
        return self._session is not None

    def detect(self, frame: np.ndarray) -> List[dict[str, Any]]:
        """
        Detect people in frame.
        
        Args:
            frame: BGR numpy image array (e.g. 640x480).
            
        Returns:
            List of detection dicts:
            [
                {
                    "box": [x, y, w, h],
                    "confidence": float,
                    "class": "person",
                }
            ]
        """
        if frame is None or not self.is_available:
            return []

        if self._session is not None:
            raw_dets = self._detect_onnx(frame)
        elif self._hog is not None:
            raw_dets = self._detect_hog(frame)
        else:
            raw_dets = []

        return self._merge_duplicate_person_boxes(raw_dets)

    def _merge_duplicate_person_boxes(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Merge overlapping boxes for the same person (Review 20:00 Item 4).
        Stops one person being seen as two due to torso/body sub-boxes or high IoU.
        """
        if len(detections) <= 1:
            return detections

        sorted_dets = sorted(detections, key=lambda d: float(d.get("confidence", 0.0)), reverse=True)
        merged_results: list[dict[str, Any]] = []

        for det in sorted_dets:
            bx, by, bw, bh = det["box"]
            box_area = bw * bh
            merged = False

            for existing in merged_results:
                ex, ey, ew, eh = existing["box"]
                ex_area = ew * eh

                ix1 = max(bx, ex)
                iy1 = max(by, ey)
                ix2 = min(bx + bw, ex + ew)
                iy2 = min(by + bh, ey + eh)
                iw = max(0, ix2 - ix1)
                ih = max(0, iy2 - iy1)
                inter_area = iw * ih

                if inter_area > 0:
                    union_area = box_area + ex_area - inter_area
                    iou = inter_area / union_area if union_area > 0 else 0.0
                    min_area = min(box_area, ex_area)
                    containment = inter_area / min_area if min_area > 0 else 0.0

                    if iou > 0.30 or containment > 0.60:
                        ux1 = min(bx, ex)
                        uy1 = min(by, ey)
                        ux2 = max(bx + bw, ex + ew)
                        uy2 = max(by + bh, ey + eh)
                        existing["box"] = [ux1, uy1, ux2 - ux1, uy2 - uy1]
                        existing["confidence"] = max(float(existing.get("confidence", 0.0)), float(det.get("confidence", 0.0)))
                        merged = True
                        break

            if not merged:
                merged_results.append(det)

        return merged_results

    def _detect_onnx(self, frame: np.ndarray) -> List[dict[str, Any]]:
        """Inference with YOLOX-Nano ONNX with grid-stride box decoding."""
        h, w = frame.shape[:2]
        net_h, net_w = self._input_size
        r = min(net_h / h, net_w / w)
        resized_w, resized_h = int(w * r), int(h * r)
        resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)

        # 114 padding per YOLOX specification
        padded = np.full((net_h, net_w, 3), 114, dtype=np.uint8)
        padded[:resized_h, :resized_w] = resized

        # BGR HWC -> CHW float32
        blob = padded.transpose((2, 0, 1))[None].astype(np.float32)

        outputs = self._session.run(None, {self._input_name: blob})[0]
        predictions = outputs[0]

        boxes = predictions[:, :4].copy()
        obj_confs = predictions[:, 4]
        cls_confs = predictions[:, 5:]

        # Class 0 = person
        person_scores = obj_confs * cls_confs[:, 0]
        mask = person_scores > self._conf_thresh
        if not np.any(mask):
            return []

        filtered_boxes = boxes[mask]
        filtered_scores = person_scores[mask]
        grids_masked = self._grids[mask]
        strides_masked = self._strides[mask]

        # Decode center (cx, cy) and scale (w, h)
        filtered_boxes[:, :2] = (filtered_boxes[:, :2] + grids_masked) * strides_masked
        filtered_boxes[:, 2:4] = np.exp(filtered_boxes[:, 2:4]) * strides_masked

        # Convert [center_x, center_y, box_w, box_h] back to original frame [x1, y1, w, h]
        x1 = np.maximum(0, (filtered_boxes[:, 0] - filtered_boxes[:, 2] / 2) / r)
        y1 = np.maximum(0, (filtered_boxes[:, 1] - filtered_boxes[:, 3] / 2) / r)
        box_w = np.minimum(w - x1, filtered_boxes[:, 2] / r)
        box_h = np.minimum(h - y1, filtered_boxes[:, 3] / r)

        boxes_xywh = np.stack([x1, y1, box_w, box_h], axis=1).tolist()
        indices = cv2.dnn.NMSBoxes(
            boxes_xywh,
            filtered_scores.tolist(),
            self._conf_thresh,
            self._nms_thresh,
        )

        results = []
        if len(indices) > 0:
            for idx in indices.flatten():
                bx, by, bw, bh = [int(v) for v in boxes_xywh[idx]]
                if bw > 15 and bh > 25:  # Filter noise artifacts
                    results.append({
                        "box": [bx, by, bw, bh],
                        "confidence": float(filtered_scores[idx]),
                        "class": "person",
                    })

        return results

    def _detect_hog(self, frame: np.ndarray) -> List[dict[str, Any]]:
        """Fallback inference with OpenCV HOG."""
        rects, weights = self._hog.detectMultiScale(
            frame,
            winStride=(8, 8),
            padding=(4, 4),
            scale=1.05,
        )
        results = []
        for (x, y, w, h), weight in zip(rects, weights):
            conf = float(weight[0]) if hasattr(weight, "__len__") else float(weight)
            if conf >= 0.1:
                results.append({
                    "box": [int(x), int(y), int(w), int(h)],
                    "confidence": min(1.0, conf),
                    "class": "person",
                })
        return results
