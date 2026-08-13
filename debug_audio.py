import sounddevice as sd
from archer.config import get_config

c = get_config()
m = sd.query_devices(c.mic_device_index)
s = sd.query_devices(c.speaker_device_index)

print(f"Mic ({c.mic_device_index}): {m['name']}")
print(f"  Max Input Channels: {m['max_input_channels']}")
print(f"  Default Sample Rate: {m['default_samplerate']}")

print(f"Speaker ({c.speaker_device_index}): {s['name']}")
print(f"  Max Output Channels: {s['max_output_channels']}")
print(f"  Default Sample Rate: {s['default_samplerate']}")
