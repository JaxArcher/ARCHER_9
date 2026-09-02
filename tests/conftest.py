"""
Pytest configuration and Windows DLL initialization.
Pre-loads torch and onnxruntime before PyQt6 test fixtures are imported.
"""

from __future__ import annotations

import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

try:
    import torch
    import onnxruntime
except ImportError:
    pass
