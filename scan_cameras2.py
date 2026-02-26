"""Scan cameras using DirectShow device name enumeration via ffmpeg/pygrabber."""
import cv2
import sys

# Method 1: Try opening by device path (WMF style)
print("=== Method 1: Try device path for eMeet C960 ===")
# Some OpenCV builds support opening by device path on Windows
vid_path = r"USB\VID_328F&PID_2013&MI_00\6&39FBEEC7&1&0000"
for path in [
    vid_path,
    f"@device:pnp:\\\\?\\usb#vid_328f&pid_2013&mi_00#6&39fbeec7&1&0000",
    f"video=HD Webcam eMeet C960",
]:
    cap = cv2.VideoCapture(path, cv2.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        print(f"  '{path}': OPEN, read={ret}")
        cap.release()
    else:
        print(f"  '{path}': FAILED")
        cap.release()

# Method 2: Try higher indices up to 20
print("\n=== Method 2: Extended index scan 0-19 (DSHOW) ===")
for i in range(20):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        import time
        time.sleep(0.3)
        ret, frame = cap.read()
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        fourcc_str = "".join([chr((fourcc_int >> 8 * j) & 0xFF) for j in range(4)])
        print(f"  Device {i}: OPEN ({w}x{h}, fourcc={fourcc_str}), read={ret}")
        cap.release()
    else:
        cap.release()

# Method 3: Try CAP_ANY with extended range
print("\n=== Method 3: Extended index scan 0-19 (CAP_ANY) ===")
for i in range(20):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        import time
        time.sleep(0.3)
        ret, frame = cap.read()
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        backend = cap.getBackendName()
        print(f"  Device {i}: OPEN ({w}x{h}, backend={backend}), read={ret}")
        cap.release()
    else:
        cap.release()

print("\nDone.")
