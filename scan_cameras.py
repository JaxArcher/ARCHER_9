"""Identify camera devices by reading frame characteristics."""
import cv2
import numpy as np

print(f"OpenCV: {cv2.__version__}\n")

for i in range(10):
    for backend_name, backend_id in [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF)]:
        cap = cv2.VideoCapture(i, backend_id)
        if not cap.isOpened():
            cap.release()
            continue

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        fourcc_str = "".join([chr((fourcc_int >> 8 * j) & 0xFF) for j in range(4)])

        # Read a few frames and check variance (OBS typically sends desktop content
        # with high variance; a real webcam in a room has different characteristics)
        frames_ok = 0
        for _ in range(3):
            ret, frame = cap.read()
            if ret and frame is not None:
                frames_ok += 1

        print(f"Device {i} ({backend_name}): {w}x{h}, fourcc={fourcc_str}, frames={frames_ok}/3")
        cap.release()

print("\nDone. Check which device shows your face vs OBS desktop.")
