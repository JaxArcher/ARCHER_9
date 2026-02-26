"""Quick utility to list all available camera indices on this system."""
import cv2

def list_cameras(max_index=10):
    print("Scanning for available cameras...\n")
    found = []
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)  # CAP_DSHOW is best on Windows
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            backend = cap.getBackendName()
            print(f"  [Index {idx}]  {w}x{h} @ {fps:.1f} FPS  (backend: {backend})")
            found.append(idx)
            cap.release()
        else:
            cap.release()

    if not found:
        print("  No cameras found.")
    else:
        print(f"\nTotal cameras found: {len(found)}")
        print(f"Available indices: {found}")

if __name__ == "__main__":
    list_cameras()
