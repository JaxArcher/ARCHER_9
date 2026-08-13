import time
import wave
import numpy as np
from archer.voice.audio import AudioManager

def record_debug():
    print("Initializing AudioManager...")
    audio = AudioManager()
    audio.start_capture()
    
    print("Recording 5 seconds of audio from the queue...")
    frames = []
    start_time = time.time()
    while time.time() - start_time < 5:
        chunk = audio.get_audio_chunk(timeout=0.1)
        if chunk:
            frames.append(chunk)
            
    audio.stop_capture()
    audio.shutdown()
    
    if not frames:
        print("Error: No audio frames captured!")
        return
        
    print(f"Captured {len(frames)} frames. Saving to debug_audio.wav...")
    with wave.open("debug_capture.wav", "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"".join(frames))
    print("Done. Download debug_capture.wav to listen.")

if __name__ == "__main__":
    record_debug()
