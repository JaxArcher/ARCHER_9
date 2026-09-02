"""
ARCHER Hardware Device Diagnostic Tool.

Lists all available audio input (microphone) devices, audio output (speaker) devices,
and video capture (webcam) devices connected to your system.
"""

import sys
from pathlib import Path

# Ensure UTF-8 stdout encoding for Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.append(str(Path(__file__).parent.parent / "src"))

def list_hardware_devices():
    print("=" * 72)
    print("  ARCHER HARDWARE DEVICE DIAGNOSTIC")
    print("=" * 72)

    # 1. Audio Devices (Microphones & Speakers)
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default_mic = sd.default.device[0]
        default_speaker = sd.default.device[1]

        print("\n🎤 AVAILABLE MICROPHONES (Audio Inputs):")
        print("-" * 72)
        mic_found = False
        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                mic_found = True
                is_default = " [DEFAULT SYSTEM MIC]" if idx == default_mic else ""
                print(f"  Index [{idx:2d}] : {dev['name']}{is_default}")

        if not mic_found:
            print("  ⚠️ No microphone devices detected.")

        print("\n🔊 AVAILABLE SPEAKERS (Audio Outputs):")
        print("-" * 72)
        speaker_found = False
        for idx, dev in enumerate(devices):
            if dev["max_output_channels"] > 0:
                speaker_found = True
                is_default = " [DEFAULT SYSTEM SPEAKER]" if idx == default_speaker else ""
                print(f"  Index [{idx:2d}] : {dev['name']}{is_default}")

        if not speaker_found:
            print("  ⚠️ No speaker devices detected.")

    except Exception as e:
        print(f"\n⚠️ Could not query audio devices: {e}")

    # 2. Camera Devices (Webcams)
    print("\n📷 AVAILABLE WEBCAMS (Video Inputs):")
    print("-" * 72)
    try:
        import cv2
        webcams_found = []
        for idx in range(6):
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    webcams_found.append(idx)
                    print(f"  Device Index [{idx}] : Camera detected & capturing OK")
                else:
                    print(f"  Device Index [{idx}] : Camera detected (busy or warming up)")
                cap.release()

        if not webcams_found:
            print("  ⚠️ No working webcams detected on indices 0-5.")

    except Exception as e:
        print(f"⚠️ Could not probe webcam devices: {e}")

    print("\n" + "=" * 72)
    print("  HOW TO CONFIGURE ARCHER TO USE A SPECIFIC MIC / CAMERA:")
    print("=" * 72)
    print("  Edit your `.env` file (or set environment variables):")
    print("    ARCHER_MIC_DEVICE_INDEX=<index_number>")
    print("    ARCHER_WEBCAM_DEVICE=<device_number>")
    print("    ARCHER_SPEAKER_DEVICE_INDEX=<index_number>")
    print("=" * 72 + "\n")

if __name__ == "__main__":
    list_hardware_devices()
