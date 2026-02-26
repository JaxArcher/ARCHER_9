"""Test capturing from eMeet C960 using alternative methods."""
import subprocess
import time
import os
import sys

# Method 1: Try ffmpeg with mediafoundation input instead of dshow
print("=== Method 1: ffmpeg mediafoundation ===")
configs = [
    ["ffmpeg", "-f", "mfvideo", "-i", "video=HD Webcam eMeet C960", "-frames:v", "1", "-y", "D:\\ARCHER_9\\test_mf.jpg"],
    ["ffmpeg", "-f", "vfwcap", "-i", "0", "-frames:v", "1", "-y", "D:\\ARCHER_9\\test_vfw.jpg"],
]
for cmd in configs:
    print(f"  Trying: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and os.path.exists(cmd[-1]):
            size = os.path.getsize(cmd[-1])
            print(f"  SUCCESS! File size: {size} bytes")
        else:
            # Extract key error lines
            for line in result.stderr.split('\n'):
                if any(x in line.lower() for x in ['error', 'could not', 'no such', 'unknown']):
                    print(f"  {line.strip()}")
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT")
    except Exception as e:
        print(f"  ERROR: {e}")

# Method 2: Check supported ffmpeg input formats
print("\n=== Available ffmpeg input formats ===")
try:
    result = subprocess.run(["ffmpeg", "-devices"], capture_output=True, text=True, timeout=5)
    for line in result.stderr.split('\n'):
        if any(x in line.lower() for x in ['dshow', 'mf', 'gdi', 'video', 'vfw', 'media']):
            print(f"  {line.strip()}")
except Exception as e:
    print(f"  ERROR: {e}")

# Method 3: List dshow device capabilities
print("\n=== eMeet C960 dshow capabilities ===")
try:
    result = subprocess.run(
        ["ffmpeg", "-f", "dshow", "-list_options", "true", "-i", "video=HD Webcam eMeet C960"],
        capture_output=True, text=True, timeout=10
    )
    for line in result.stderr.split('\n'):
        if 'pixel' in line.lower() or 'min' in line.lower() or 'max' in line.lower() or 'fps' in line.lower() or 'video' in line.lower():
            print(f"  {line.strip()}")
except Exception as e:
    print(f"  ERROR: {e}")

# Method 4: Check if camera app can see it
print("\n=== Opening Windows Camera app to test ===")
print("  If the Windows Camera app shows video, the camera hardware is fine")
print("  and the issue is specific to DirectShow/OpenCV integration.")

print("\nDone.")
