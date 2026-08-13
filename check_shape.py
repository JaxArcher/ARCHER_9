import sounddevice as sd
import numpy as np
from archer.config import get_config

c = get_config()
def callback(indata, outdata, frames, time, status):
    print(f"indata shape: {indata.shape}")
    raise sd.CallbackStop

with sd.Stream(device=(c.mic_device_index, c.speaker_device_index), 
               samplerate=16000, blocksize=480, channels=1, dtype='int16', 
               callback=callback):
    sd.sleep(100)
