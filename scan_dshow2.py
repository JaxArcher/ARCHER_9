"""Try to capture from eMeet C960 using different methods."""
import cv2
import time

print(f"OpenCV build info (video I/O):")
info = cv2.getBuildInformation()
for line in info.split('\n'):
    if any(x in line.lower() for x in ['video', 'ffmpeg', 'dshow', 'msmf', 'gstreamer', 'media']):
        print(f"  {line.strip()}")

# Method 1: DSHOW with specific settings
print("\n=== Method 1: DSHOW idx 0 with explicit MJPG + 640x480 ===")
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
if cap.isOpened():
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    time.sleep(1)
    for i in range(5):
        ret, frame = cap.read()
        print(f"  Frame {i}: read={ret}")
    cap.release()
else:
    print("  Can't open")
    cap.release()

# Method 2: DSHOW with YUY2
print("\n=== Method 2: DSHOW idx 0 with YUY2 ===")
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
if cap.isOpened():
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUY2"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    time.sleep(1)
    for i in range(5):
        ret, frame = cap.read()
        print(f"  Frame {i}: read={ret}")
    cap.release()
else:
    print("  Can't open")
    cap.release()

# Method 3: Try MSMF with idx 0 and longer warmup
print("\n=== Method 3: MSMF idx 0 with 3s warmup ===")
cap = cv2.VideoCapture(0, cv2.CAP_MSMF)
if cap.isOpened():
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    time.sleep(3)
    for i in range(10):
        ret, frame = cap.read()
        print(f"  Frame {i}: read={ret}")
        time.sleep(0.2)
    cap.release()
else:
    print("  Can't open")
    cap.release()

# Method 4: Use CAP_DSHOW with explicit buffer size
print("\n=== Method 4: DSHOW idx 0 with buffersize=1 ===")
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
if cap.isOpened():
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    time.sleep(1)
    for i in range(5):
        ret, frame = cap.read()
        print(f"  Frame {i}: read={ret}")
    cap.release()
else:
    print("  Can't open")
    cap.release()

# Method 5: Use a VideoCapture with specific API + index combo
# On Windows, index = device_id + api_preference * 100
print("\n=== Method 5: Raw index encoding ===")
for api in [cv2.CAP_DSHOW, cv2.CAP_MSMF]:
    cap = cv2.VideoCapture(0 + api)
    if cap.isOpened():
        time.sleep(1)
        ret, frame = cap.read()
        print(f"  Index {0 + api} (api={api}): OPEN, read={ret}")
        cap.release()
    else:
        print(f"  Index {0 + api} (api={api}): FAILED")
        cap.release()

print("\nDone.")
