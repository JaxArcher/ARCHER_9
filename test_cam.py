"""Quick webcam diagnostic script."""
import cv2
import time

print(f"OpenCV: {cv2.__version__}")

# Check installed package
try:
    import importlib.metadata
    for d in importlib.metadata.distributions():
        name = d.metadata.get("Name", "")
        if name and "opencv" in name.lower():
            print(f"Package: {name}=={d.version}")
except Exception:
    pass

# Available backends
for name in ["CAP_MSMF", "CAP_DSHOW", "CAP_VFW", "CAP_ANY"]:
    val = getattr(cv2, name, None)
    if val is not None:
        print(f"  Backend {name} = {val}")

# Try DSHOW
print("\n--- DSHOW ---")
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
print(f"Opened: {cap.isOpened()}")
if cap.isOpened():
    print(f"Backend: {cap.getBackendName()}")
    time.sleep(1)
    ret, frame = cap.read()
    print(f"Read: {ret}, shape={frame.shape if ret else None}")
cap.release()

# Try MSMF with YUY2 format forced
print("\n--- MSMF + YUY2 ---")
cap = cv2.VideoCapture(0, cv2.CAP_MSMF)
print(f"Opened: {cap.isOpened()}")
if cap.isOpened():
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("Y", "U", "Y", "2"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    time.sleep(2)
    ret, frame = cap.read()
    print(f"Read: {ret}, shape={frame.shape if ret else None}")
cap.release()

# Try default with convert=False (raw mode)
print("\n--- Default + convert=False ---")
cap = cv2.VideoCapture(0)
print(f"Opened: {cap.isOpened()}")
if cap.isOpened():
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    time.sleep(1)
    ret, frame = cap.read()
    print(f"Read: {ret}, shape={frame.shape if ret else None}")
cap.release()

# Try different device indices
print("\n--- Device scan ---")
for idx in range(5):
    cap = cv2.VideoCapture(idx)
    if cap.isOpened():
        ret, frame = cap.read()
        print(f"Device {idx}: opened=True, read={ret}, shape={frame.shape if ret else None}")
    else:
        print(f"Device {idx}: opened=False")
    cap.release()

print("\nDone.")
