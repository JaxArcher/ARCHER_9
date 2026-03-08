import os
import sys
from pathlib import Path

def check_package(package_name, import_name=None):
    if import_name is None:
        import_name = package_name
    try:
        mod = __import__(import_name)
        version = getattr(mod, '__version__', 'unknown')
        print(f"☑ {package_name} ({version}): ok")
        return True
    except ImportError as e:
        print(f"☒ {package_name}: FAIL ({e})")
        return False

def check_torch():
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        print(f"{'☑' if cuda_ok else '☒'} torch.cuda.is_available(): {cuda_ok}")
        return cuda_ok
    except ImportError:
        print("☒ torch: FAIL (not installed)")
        return False

def check_camera():
    import cv2
    cap = cv2.VideoCapture(0)
    opened = cap.isOpened()
    print(f"{'☑' if opened else '☒'} Camera 0 opens: {opened}")
    cap.release()
    return opened

def check_audio():
    import sounddevice as sd
    try:
        sd.check_input_settings()
        print("☑ sounddevice input settings: ok")
        return True
    except Exception as e:
        print(f"☒ sounddevice input settings: FAIL ({e})")
        return False

def main():
    print("--- Phase 0: Environment & Prerequisites ---")
    packages = [
        ("PyQt6", "PyQt6"),
        ("faster-whisper", "faster_whisper"),
        ("webrtcvad", "webrtcvad"),
        ("mediapipe", "mediapipe"),
        ("opencv-python", "cv2"),
        ("sounddevice", "sounddevice"),
        ("mem0", "mem0"),
        ("chromadb", "chromadb"),
        ("numpy", "numpy"),
    ]
    
    all_ok = True
    for pkg, imp in packages:
        if not check_package(pkg, imp):
            all_ok = False
            
    if not check_torch():
        all_ok = False
        
    # Camera check can be slow or fail in CI/headless, but let's try
    try:
        if not check_camera():
            all_ok = False
    except Exception as e:
        print(f"☒ check_camera: FAIL ({e})")
        all_ok = False
        
    if not check_audio():
        all_ok = False
        
    print(f"\nPhase 0 status: {'PASS' if all_ok else 'FAILING'}")

if __name__ == "__main__":
    main()
