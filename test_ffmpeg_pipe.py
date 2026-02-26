"""Test capturing from eMeet C960 via ffmpeg subprocess pipe."""
import subprocess
import numpy as np
import time

WIDTH = 640
HEIGHT = 480

# Try ffmpeg with different pixel formats and options
configs = [
    # Try with explicit pixel format
    {
        "name": "rawvideo bgr24",
        "cmd": [
            "ffmpeg", "-f", "dshow",
            "-video_size", f"{WIDTH}x{HEIGHT}",
            "-i", "video=HD Webcam eMeet C960",
            "-pix_fmt", "bgr24",
            "-f", "rawvideo",
            "-"
        ]
    },
    # Try with rtbufsize to avoid buffer issues
    {
        "name": "rawvideo bgr24 + rtbufsize",
        "cmd": [
            "ffmpeg", "-f", "dshow",
            "-rtbufsize", "100M",
            "-video_size", f"{WIDTH}x{HEIGHT}",
            "-i", "video=HD Webcam eMeet C960",
            "-pix_fmt", "bgr24",
            "-f", "rawvideo",
            "-"
        ]
    },
    # Try without specifying video_size (let camera choose default)
    {
        "name": "rawvideo bgr24 default size",
        "cmd": [
            "ffmpeg", "-f", "dshow",
            "-i", "video=HD Webcam eMeet C960",
            "-pix_fmt", "bgr24",
            "-s", f"{WIDTH}x{HEIGHT}",
            "-f", "rawvideo",
            "-"
        ]
    },
    # Try with pixel_format set for input
    {
        "name": "input pixel_format mjpeg",
        "cmd": [
            "ffmpeg", "-f", "dshow",
            "-pixel_format", "mjpeg",
            "-video_size", f"{WIDTH}x{HEIGHT}",
            "-i", "video=HD Webcam eMeet C960",
            "-pix_fmt", "bgr24",
            "-f", "rawvideo",
            "-"
        ]
    },
    # Try with pixel_format yuyv422
    {
        "name": "input pixel_format yuyv422",
        "cmd": [
            "ffmpeg", "-f", "dshow",
            "-pixel_format", "yuyv422",
            "-video_size", f"{WIDTH}x{HEIGHT}",
            "-i", "video=HD Webcam eMeet C960",
            "-pix_fmt", "bgr24",
            "-f", "rawvideo",
            "-"
        ]
    },
]

for config in configs:
    print(f"\n=== {config['name']} ===")
    print(f"  cmd: {' '.join(config['cmd'])}")
    try:
        proc = subprocess.Popen(
            config["cmd"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**8
        )

        frame_size = WIDTH * HEIGHT * 3  # bgr24

        # Try to read 3 frames with timeout
        for i in range(3):
            raw = proc.stdout.read(frame_size)
            if len(raw) == frame_size:
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
                print(f"  Frame {i}: OK, shape={frame.shape}, mean={frame.mean():.1f}")
            else:
                print(f"  Frame {i}: FAILED, got {len(raw)} bytes (expected {frame_size})")
                # Read stderr for error details
                proc.terminate()
                err = proc.stderr.read().decode('utf-8', errors='replace')
                for line in err.split('\n'):
                    if 'error' in line.lower() or 'could not' in line.lower() or 'warning' in line.lower():
                        print(f"  stderr: {line.strip()}")
                break
        else:
            print(f"  SUCCESS: Read 3 frames!")

        proc.terminate()
        proc.wait(timeout=3)

    except Exception as e:
        print(f"  ERROR: {e}")

print("\nDone.")
