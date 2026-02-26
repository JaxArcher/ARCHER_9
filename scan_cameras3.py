"""Try opening eMeet C960 by name using ffmpeg backend."""
import cv2

# OpenCV CAP_FFMPEG can use DirectShow device names via ffmpeg's dshow input
# Format: video=DeviceName
print("=== Trying ffmpeg dshow device name ===")
for name in [
    "video=HD Webcam eMeet C960",
    "video=eMeet C960",
]:
    cap = cv2.VideoCapture(name, cv2.CAP_FFMPEG)
    if cap.isOpened():
        import time
        time.sleep(0.5)
        ret, frame = cap.read()
        print(f"  '{name}': OPEN, read={ret}, shape={frame.shape if ret else None}")
        cap.release()
    else:
        print(f"  '{name}': FAILED")
        cap.release()

# Also try with the API preference for MSMF using a device name
print("\n=== Trying MSMF by device name ===")
for name in [
    "HD Webcam eMeet C960",
]:
    cap = cv2.VideoCapture(name, cv2.CAP_MSMF)
    if cap.isOpened():
        import time
        time.sleep(0.5)
        ret, frame = cap.read()
        print(f"  '{name}': OPEN, read={ret}")
        cap.release()
    else:
        print(f"  '{name}': FAILED")
        cap.release()

# Try opening device 0 with DSHOW but after a longer delay
print("\n=== Trying device 0 DSHOW with long warmup ===")
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
print(f"  Opened: {cap.isOpened()}")
if cap.isOpened():
    import time
    time.sleep(2)
    for i in range(5):
        ret, frame = cap.read()
        print(f"  Frame {i}: read={ret}")
        time.sleep(0.5)
    cap.release()
else:
    cap.release()

# Check if uninstalling OBS virtual camera helps
# First, let's see if the NV12 device at index 1 is the only available
# by checking its device name (if possible via backend-specific APIs)
print("\n=== Checking if pygrabber can enumerate devices ===")
try:
    from pygrabber.dshow_graph import FilterGraph
    graph = FilterGraph()
    devices = graph.get_input_devices()
    for i, name in enumerate(devices):
        print(f"  DirectShow device {i}: {name}")
except ImportError:
    print("  pygrabber not installed - trying alternative enumeration")
    # Try using Windows WMI
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-CimInstance Win32_PnPEntity | Where-Object { $_.Caption -like '*camera*' -or $_.Caption -like '*webcam*' -or $_.Caption -like '*video*' } | Select-Object Caption, DeviceID | Format-List"],
            capture_output=True, text=True, timeout=10
        )
        print(result.stdout[:2000] if result.stdout else "  No output")
    except Exception as e:
        print(f"  WMI failed: {e}")

print("\nDone.")
