"""
Unit tests for AndroidEmulatorManager (Phase 7b).
"""
import pytest
import numpy as np
import cv2
from unittest.mock import MagicMock, patch
from archer.android_manager import (
    AndroidEmulatorManager,
    DEFAULT_GRPC_PORT,
    STREAM_WIDTH,
    STREAM_HEIGHT,
)
from archer.android_grpc import emulator_controller_pb2


@pytest.fixture
def manager():
    mgr = AndroidEmulatorManager()
    return mgr


def test_manager_initial_state(manager):
    assert manager.is_running is False
    assert manager.is_starting is False
    assert manager.grpc_port == DEFAULT_GRPC_PORT
    state = manager.get_state()
    assert state["running"] is False
    assert state["starting"] is False
    assert "Offline" in state["message"]


def test_is_installed(manager):
    # With data/android/sdk populated, emulator and adb exist
    assert manager.is_installed() is True


def test_hypervisor_check_cached(manager):
    val = manager.check_hypervisor()
    assert isinstance(val, bool)
    assert manager._hypervisor_ok is not None
    # Calling again should use cached value
    assert manager.check_hypervisor() == val


def test_frame_decoding_and_aspect_ratio(manager):
    received_frames = []
    manager.set_frame_bytes_callback(lambda bytes_data, w, h: received_frames.append((bytes_data, w, h)))

    # Create dummy 399x888 RGB888 image
    w, h = 399, 888
    dummy_pixels = np.zeros((h, w, 3), dtype=np.uint8)
    dummy_pixels[100:200, 50:150] = [255, 255, 255]

    mock_img = MagicMock()
    mock_img.image = dummy_pixels.tobytes()
    mock_img.format = MagicMock()
    mock_img.format.width = w
    mock_img.format.height = h
    mock_img.width = 0
    mock_img.height = 0

    success = manager._process_and_broadcast_frame(mock_img)
    assert success is True
    assert len(received_frames) == 1
    raw_bytes, fw, fh = received_frames[0]
    assert len(raw_bytes) > 0
    assert fw == w
    assert fh == h
    assert manager.last_frame_bytes == raw_bytes


def test_set_stream_resolution_and_visibility(manager):
    assert manager.streaming_active is False
    manager.set_streaming_active(True)
    assert manager.streaming_active is True

    # Test resolution clamping and aspect ratio calculations
    manager.set_stream_resolution(width=540, height=1200)
    assert manager.target_height == 1200
    assert manager.target_width == 540

    # Test bounds clamping
    manager.set_stream_resolution(width=5000, height=5000)
    assert manager.target_height == 2400
    assert manager.target_width == 1080


@pytest.mark.asyncio
async def test_input_handlers_when_stopped(manager):
    # Should safely return without error when no gRPC stub is active
    await manager.handle_touch("down", 0.5, 0.5)
    await manager.handle_touch("up", 0.5, 0.5)
    await manager.handle_button("home")
    await manager.handle_key("down", "a", "KeyA")

