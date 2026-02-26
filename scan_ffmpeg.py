"""Try to capture from eMeet C960 using OpenCV's FFMPEG backend with dshow device name."""
import cv2
import time
import subprocess

# First check if ffmpeg can see the device
print("=== ffmpeg device list ===")
try:
    result = subprocess.run(
        ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True, text=True, timeout=10
    )
    # ffmpeg prints device list to stderr
    for line in result.stderr.split('\n'):
        if 'dshow' in line.lower() or 'device' in line.lower() or '"' in line:
            print(f"  {line.strip()}")
except FileNotFoundError:
    print("  ffmpeg not in PATH, trying OpenCV's bundled ffmpeg...")
except Exception as e:
    print(f"  ffmpeg error: {e}")

# Try OpenCV FFMPEG backend with dshow device name
print("\n=== OpenCV FFMPEG + dshow device name ===")
names_to_try = [
    'video=HD Webcam eMeet C960',
    'video=HD Webcam eMeet C960:audio=Microphone (HD Webcam eMeet C960)',
]
for name in names_to_try:
    cap = cv2.VideoCapture(name, cv2.CAP_FFMPEG)
    if cap.isOpened():
        time.sleep(1)
        ret, frame = cap.read()
        print(f"  '{name}': OPEN, read={ret}, shape={frame.shape if ret and frame is not None else None}")
        cap.release()
    else:
        print(f"  '{name}': FAILED")
        cap.release()

# Try with the env var for FFMPEG
print("\n=== OpenCV FFMPEG with explicit options ===")
import os
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'video_size;640x480'
cap = cv2.VideoCapture('video=HD Webcam eMeet C960', cv2.CAP_FFMPEG)
if cap.isOpened():
    time.sleep(1)
    ret, frame = cap.read()
    print(f"  OPEN, read={ret}")
    cap.release()
else:
    print("  FAILED")
    cap.release()

print("\nDone.")
