from dotenv import load_dotenv
load_dotenv('.env', override=True)
import sounddevice as sd
import numpy as np

print('=== All audio output devices ===')
devices = sd.query_devices()
for i, d in enumerate(devices):
    if d['max_output_channels'] > 0:
        print(f"  [{i}] {d['name']}  (rate={int(d['default_samplerate'])})")

print()
from archer.config import get_config
config = get_config()
print(f'Configured speaker index: {config.speaker_device_index}')

t = np.linspace(0, 0.4, int(24000 * 0.4), dtype=np.float32)
tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

try:
    print(f'Playing tone on device {config.speaker_device_index} ...')
    sd.play(tone, samplerate=24000, device=config.speaker_device_index)
    sd.wait()
    print('OK - did you hear a tone?')
except Exception as e:
    print(f'PLAYBACK ERROR on device {config.speaker_device_index}: {type(e).__name__}: {e}')
    print('Trying default device ...')
    try:
        sd.play(tone, samplerate=24000)
        sd.wait()
        print('Default device OK - did you hear a tone?')
    except Exception as e2:
        print(f'DEFAULT DEVICE ERROR: {e2}')
