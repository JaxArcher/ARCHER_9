import torch
import cv2
import sounddevice as sd
import numpy as np
import os
import sys
from pathlib import Path

def audit_phase_0():
    print("--- ARCHER QA AUDIT: PHASE 0 (ENVIRONMENT) ---")
    
    # 1. CUDA/GPU
    cuda_avail = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_avail else "NONE"
    print(f"H-01 (CUDA Visible): {'☑ PASS' if cuda_avail else '☒ FAIL'}")
    print(f"H-02 (GPU Name): {gpu_name}")
    
    # 2. Camera
    cap = cv2.VideoCapture(0)
    opened = cap.isOpened()
    print(f"H-03 (Webcam Opens): {'☑ PASS' if opened else '☒ FAIL'}")
    cap.release()
    
    # 3. Audio
    try:
        sd.check_input_settings()
        print("H-04 (Mic Present): ☑ PASS")
    except Exception as e:
        print(f"H-04 (Mic Present): ☒ FAIL ({e})")
        
    # 4. Python packages
    packages = [
        ("PyQt6", "PyQt6"),
        ("faster-whisper", "faster_whisper"),
        ("webrtcvad", "webrtcvad"),
        ("mediapipe", "mediapipe"),
        ("numpy", "numpy")
    ]
    for pkg, imp in packages:
        try:
            mod = __import__(imp)
            v = getattr(mod, "__version__", "ok")
            print(f"P-XX ({pkg}): ☑ PASS ({v})")
        except ImportError:
            print(f"P-XX ({pkg}): ☒ FAIL")

if __name__ == "__main__":
    audit_phase_0()
