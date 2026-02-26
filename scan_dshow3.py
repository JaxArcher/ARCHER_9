"""Test capturing from eMeet C960 via pygrabber (DirectShow COM)."""
import time
import numpy as np
from pygrabber.dshow_graph import FilterGraph

print("Setting up DirectShow capture for 'HD Webcam eMeet C960'...")

graph = FilterGraph()
devices = graph.get_input_devices()
print(f"Available devices: {devices}")

# Find eMeet device index
emeet_idx = None
for i, name in enumerate(devices):
    if "emeet" in name.lower() or "c960" in name.lower():
        emeet_idx = i
        break

if emeet_idx is None:
    print("eMeet C960 not found!")
    exit(1)

print(f"Found eMeet C960 at DirectShow index {emeet_idx}")

# Try capturing a single frame
captured_frame = [None]

def frame_callback(image):
    """Called when a frame is captured."""
    captured_frame[0] = np.array(image)
    print(f"  Got frame! Shape: {captured_frame[0].shape}")

graph.add_video_input_device(emeet_idx)
graph.add_sample_grabber(frame_callback)
graph.add_null_render()
graph.prepare_preview_graph()
graph.run()

print("Waiting for frames...")
time.sleep(3)

graph.stop()
graph.grab_frame()
time.sleep(1)

if captured_frame[0] is not None:
    print(f"\nSUCCESS: Captured frame with shape {captured_frame[0].shape}")
else:
    print("\nFAILED: No frames captured")

print("Done.")
