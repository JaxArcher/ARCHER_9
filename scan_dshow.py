"""Enumerate DirectShow video input devices using pygrabber."""
from pygrabber.dshow_graph import FilterGraph

graph = FilterGraph()
devices = graph.get_input_devices()

print("DirectShow video input devices:")
for i, name in enumerate(devices):
    print(f"  Index {i}: {name}")

print(f"\nTotal: {len(devices)} devices")
print("\nThis is the REAL device ordering OpenCV DSHOW uses.")
