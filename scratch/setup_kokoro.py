"""
Download and test Kokoro ONNX model and voices.
"""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from huggingface_hub import hf_hub_download
from kokoro_onnx import Kokoro


def setup_and_test_kokoro():
    print("=" * 72)
    print("  KOKORO-82M ONNX SYNTHESIS TEST")
    print("=" * 72)

    model_dir = Path("data/models/kokoro")
    model_dir.mkdir(parents=True, exist_ok=True)

    onnx_path = model_dir / "kokoro-v1.0.onnx"
    voices_path = model_dir / "voices-v1.0.bin"

    if not onnx_path.exists():
        print("Downloading kokoro-v1.0.onnx from HuggingFace (hexgrad/Kokoro-82M)...")
        path = hf_hub_download(
            repo_id="hexgrad/Kokoro-82M",
            filename="onnx/model.onnx",
            local_dir=str(model_dir),
        )
        os.rename(path, onnx_path)
        print(f"  ✓ Saved {onnx_path}")

    if not voices_path.exists():
        print("Downloading voices-v1.0.bin from HuggingFace (hexgrad/Kokoro-82M)...")
        path = hf_hub_download(
            repo_id="hexgrad/Kokoro-82M",
            filename="onnx/voices.bin",
            local_dir=str(model_dir),
        )
        os.rename(path, voices_path)
        print(f"  ✓ Saved {voices_path}")

    print("\nInitializing Kokoro ONNX engine...")
    kokoro = Kokoro(str(onnx_path), str(voices_path))

    test1 = "Hello"
    test2 = "The quick brown fox jumps over the lazy dog near the river bank."

    print(f"\nSynthesizing test 1: {test1!r}...")
    samples1, sr1 = kokoro.create(test1, voice="af_sarah", speed=1.0, lang="en-us")
    print(f"  ✓ Test 1: shape={samples1.shape}, sr={sr1}, duration={len(samples1)/sr1:.3f}s")
    print(f"  - First 10 samples: {samples1[:10].tolist()}")

    print(f"\nSynthesizing test 2: {test2!r}...")
    samples2, sr2 = kokoro.create(test2, voice="af_sarah", speed=1.0, lang="en-us")
    print(f"  ✓ Test 2: shape={samples2.shape}, sr={sr2}, duration={len(samples2)/sr2:.3f}s")
    print(f"  - First 10 samples: {samples2[:10].tolist()}")

    print("\n" + "=" * 72)
    print("  DIFF VERIFICATION:")
    print(f"  - Test 1 first 10: {samples1[:10].tolist()}")
    print(f"  - Test 2 first 10: {samples2[:10].tolist()}")
    print(f"  - Are first 10 identical? {np.array_equal(samples1[:10], samples2[:10])}")
    print("=" * 72)


if __name__ == "__main__":
    setup_and_test_kokoro()
