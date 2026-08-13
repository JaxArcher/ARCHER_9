# ARCHER CUDA Fix - RTX 5080 Support

**Issue:** PyTorch not detecting RTX 5080 GPU (sm_120 architecture)  
**Status:** Solved - working solution documented below

---

## Prerequisites

### 1. Verify NVIDIA Driver Version
```powershell
nvidia-smi
```

**Required:** CUDA version 12.8 or higher shown in top-right corner

**If lower than 12.8:**
1. Go to https://www.nvidia.com/drivers
2. Select: GeForce RTX 50 Series → RTX 5080 → Windows
3. Download and install latest driver
4. Restart computer

### 2. Install Visual C++ Redistributable
**Required to prevent DLL errors**

1. Download: https://aka.ms/vs/17/release/vc_redist.x64.exe
2. Run installer
3. Restart computer

---

## Solution: Install PyTorch with CUDA 12.8 Support

### Step 1: Clean Uninstall Old PyTorch
```powershell
pip uninstall torch torchvision torchaudio -y
pip cache purge
```

### Step 2: Install PyTorch 2.7.0 with CUDA 12.8
```powershell
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

**Note:** cu128 = CUDA 12.8. This is compatible with CUDA 12.9+ drivers (forward compatible).

### Step 3: Verify Installation
```powershell
python -c "import torch; print('CUDA Available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

**Expected Output:**
```
CUDA Available: True
GPU: NVIDIA GeForce RTX 5080
```

---

## Troubleshooting

### Issue: "DLL load failed" error
**Solution:** Install Visual C++ Redistributable (see Prerequisites)

### Issue: CUDA Available returns False
**Solutions:**
1. Check NVIDIA driver supports CUDA 12.8+ (run `nvidia-smi`)
2. Restart terminal/computer
3. Verify PyTorch installed from cu128 index (not CPU version)

### Issue: "Could not find torchaudio"
**Solution:** Install without torchaudio (ARCHER doesn't need it):
```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

### Issue: Still shows sm_120 incompatibility warning
**Solution:** Try PyTorch nightly build:
```powershell
pip uninstall torch torchvision torchaudio -y
pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu124
```

---

## Verification Tests

### Test 1: CUDA Detection
```powershell
python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"
```

### Test 2: GPU Memory
```powershell
python -c "import torch; print('GPU Memory:', torch.cuda.get_device_properties(0).total_memory / 1024**3, 'GB')"
```

**Expected:** ~16 GB for RTX 5080

### Test 3: Simple Tensor Operation
```python
import torch
x = torch.randn(1000, 1000).cuda()
y = x @ x
print("GPU computation successful!")
```

---

## Expected Performance After Fix

With RTX 5080 GPU working:
- **Faster-Whisper (STT):** ~300-500ms (vs 3-5s on CPU)
- **Vision Models:** ~100-200ms per frame (vs 1-2s on CPU)  
- **LLM Inference:** ~50-100 tokens/sec (vs 5-10 on CPU)

---

## Status Checklist

- [x] NVIDIA driver updated to CUDA 12.8+ support
- [x] Visual C++ Redistributable installed
- [x] Old PyTorch uninstalled
- [x] PyTorch 2.10.0+cu128 installed
- [x] `torch.cuda.is_available()` returns True
- [x] GPU shows as "NVIDIA GeForce RTX 5080"
- [x] No sm_120 compatibility warnings

---

**Last Updated:** Based on successful fixes from October 2024 - December 2025 conversations  
**Tested On:** Windows 11, RTX 5080, Python 3.11
