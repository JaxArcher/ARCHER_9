import shutil
import torchaudio
import huggingface_hub
import huggingface_hub.errors

# Patch torchaudio
if not hasattr(torchaudio, "list_audio_backends"):
    torchaudio.list_audio_backends = lambda: ["soundfile"]

# Patch huggingface_hub for use_auth_token parameter mapping and 404 ValueError translation
_orig_hf_download = huggingface_hub.hf_hub_download

def _patched_hf_hub_download(*args, **kwargs):
    filename = kwargs.get("filename", "")
    if "use_auth_token" in kwargs:
        token_val = kwargs.pop("use_auth_token")
        if "token" not in kwargs and token_val is not None:
            kwargs["token"] = token_val
    try:
        return _orig_hf_download(*args, **kwargs)
    except Exception as e:
        if filename == "custom.py" or "NotFoundError" in type(e).__name__:
            raise ValueError(f"File not found on HuggingFace Hub: {filename}") from e
        raise

huggingface_hub.hf_hub_download = _patched_hf_hub_download

# Patch Windows symlink strategy for SpeechBrain fetching
import speechbrain.utils.fetching as sb_fetch
_orig_link = sb_fetch.link_with_strategy

def _patched_link(src, dst, strategy):
    try:
        return _orig_link(src, dst, strategy)
    except OSError:
        shutil.copy2(src, dst)
        return dst

sb_fetch.link_with_strategy = _patched_link

from speechbrain.inference.speaker import SpeakerRecognition

print("Loading SpeechBrain ECAPA-TDNN model...")
model = SpeakerRecognition.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb",
    savedir="data/models/speechbrain"
)
print("SpeechBrain ECAPA-TDNN model loaded 100% SUCCESSFULLY!")
