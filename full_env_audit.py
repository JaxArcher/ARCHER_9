import os
import sys

def audit():
    print("--- ARCHER ENVIRONMENT AUDIT (VENV) ---")
    
    # 1. Imports
    import_targets = ["torch", "PyQt6", "faster_whisper", "webrtcvad", "mediapipe", "cv2", "sounddevice", "mem0", "chromadb", "numpy"]
    for target in import_targets:
        try:
            mod = __import__(target)
            print(f"☑ {target}: PASS ({getattr(mod, '__version__', 'ok')})")
        except ImportError as e:
            print(f"☒ {target}: FAIL ({e})")
            
    # 2. CUDA
    try:
        import torch
        if torch.cuda.is_available():
            print(f"☑ H-01 (CUDA): PASS (Device: {torch.cuda.get_device_name(0)})")
        else:
            print("☒ H-01 (CUDA): FAIL (Not available to torch)")
    except Exception as e:
        print(f"☒ H-01 (CUDA): ERROR ({e})")
        
    # 3. Microphones
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        print(f"☑ H-04 (Audio Devices): {len(devices)} found")
    except Exception as e:
        print(f"☒ H-04 (Audio Devices): ERROR ({e})")

if __name__ == "__main__":
    audit()
