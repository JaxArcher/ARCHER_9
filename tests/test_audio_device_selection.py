"""
Unit tests for ARCHER audio device selection by name, loopback mapper fallback,
and Voice status card TV check notification (Review 2026-10-21 18:05/18:15 Item 1).
"""

from unittest.mock import MagicMock, patch
import pytest

from archer.voice.audio import find_audio_device, AudioManager
from archer.server import _status_board_state, _update_status_board


MOCK_DEVICES = [
    {
        "index": 0,
        "name": "Microsoft Sound Mapper - Input",
        "hostapi": 0,
        "max_input_channels": 2,
        "max_output_channels": 0,
        "default_samplerate": 44100,
    },
    {
        "index": 1,
        "name": "Microphone (2- JLab GO Talk)",
        "hostapi": 0,
        "max_input_channels": 2,
        "max_output_channels": 0,
        "default_samplerate": 48000,
    },
    {
        "index": 3,
        "name": "Microsoft Sound Mapper - Output",
        "hostapi": 0,
        "max_input_channels": 0,
        "max_output_channels": 2,
        "default_samplerate": 44100,
    },
    {
        "index": 4,
        "name": "LG-SOUND BAR (NVIDIA High Definition Audio)",
        "hostapi": 0,
        "max_input_channels": 0,
        "max_output_channels": 2,
        "default_samplerate": 48000,
    },
    {
        "index": 8,
        "name": "Primary Sound Capture Driver",
        "hostapi": 1,
        "max_input_channels": 2,
        "max_output_channels": 0,
        "default_samplerate": 44100,
    },
    {
        "index": 9,
        "name": "Microphone (2- JLab GO Talk)",
        "hostapi": 1,
        "max_input_channels": 2,
        "max_output_channels": 0,
        "default_samplerate": 48000,
    },
    {
        "index": 11,
        "name": "Primary Sound Driver",
        "hostapi": 1,
        "max_input_channels": 0,
        "max_output_channels": 2,
        "default_samplerate": 44100,
    },
    {
        "index": 12,
        "name": "LG-SOUND BAR (NVIDIA High Definition Audio)",
        "hostapi": 1,
        "max_input_channels": 0,
        "max_output_channels": 2,
        "default_samplerate": 48000,
    },
]


def test_find_audio_device_by_name_substring():
    """Verify audio device resolution matches by case-insensitive substring."""
    idx, name = find_audio_device(
        direction="output",
        name_pattern="lg-sound bar",
        devices=MOCK_DEVICES,
        preferred_hostapi=0,
    )
    assert idx == 4
    assert "LG-SOUND BAR" in name

    # Preferred hostapi 1 should select device index 12
    idx2, name2 = find_audio_device(
        direction="output",
        name_pattern="LG-SOUND BAR",
        devices=MOCK_DEVICES,
        preferred_hostapi=1,
    )
    assert idx2 == 12
    assert "LG-SOUND BAR" in name2


def test_find_audio_device_index_fallback():
    """When name pattern does not match, fall back to index_fallback."""
    idx, name = find_audio_device(
        direction="input",
        name_pattern="NonExistentMicrophone",
        index_fallback=1,
        devices=MOCK_DEVICES,
    )
    assert idx == 1
    assert "JLab GO Talk" in name


def test_find_audio_device_system_default_fallback():
    """When name and index are None, fall back to sounddevice default device."""
    with patch("sounddevice.default") as mock_default:
        mock_default.device = [1, 4]
        idx, name = find_audio_device(
            direction="input",
            name_pattern=None,
            index_fallback=None,
            devices=MOCK_DEVICES,
        )
        assert idx == 1
        assert "JLab GO Talk" in name


def test_loopback_mapper_fallback():
    """Verify _start_loopback falls back to physical default speaker when given a mapper."""
    mock_sc = MagicMock()
    mock_default_spk = MagicMock()
    mock_default_spk.name = "LG-SOUND BAR (NVIDIA High Definition Audio)"
    mock_default_spk.id = "{default-speaker-guid}"
    mock_sc.default_speaker.return_value = mock_default_spk

    mock_loopback_mic = MagicMock()
    mock_sc.get_microphone.return_value = mock_loopback_mic

    with patch.dict("sys.modules", {"soundcard": mock_sc}):
        with patch("archer.voice.audio.threading.Thread") as mock_thread:
            with patch("archer.voice.audio.get_config") as mock_cfg, patch("archer.voice.audio.get_event_bus"):
                mock_cfg.return_value = MagicMock(sample_rate=16000, audio_channels=1, audio_chunk_ms=30)
                am = AudioManager()
                am._playback_rate = 48000

                # 1. Given virtual mapper "Primary Sound Driver"
                am._start_loopback(speaker_index=11, speaker_name="Primary Sound Driver")
                mock_sc.default_speaker.assert_called()
                mock_sc.get_microphone.assert_called_with(id=str(mock_default_spk.id), include_loopback=True)
                mock_thread.assert_called_once()


def test_loopback_failed_open_fallback_to_default():
    """Verify if named speaker fails to open in soundcard, it tries default speaker before giving up."""
    mock_sc = MagicMock()
    mock_default_spk = MagicMock()
    mock_default_spk.name = "Real Physical Speaker"
    mock_default_spk.id = "{guid}"
    mock_sc.default_speaker.return_value = mock_default_spk

    def fake_get_mic(id, include_loopback=True):
        if id == "Broken Speaker":
            raise RuntimeError("no device with id Broken Speaker")
        return MagicMock()

    mock_sc.get_microphone.side_effect = fake_get_mic

    with patch.dict("sys.modules", {"soundcard": mock_sc}):
        with patch("archer.voice.audio.threading.Thread") as mock_thread:
            with patch("archer.voice.audio.get_config") as mock_cfg, patch("archer.voice.audio.get_event_bus"):
                mock_cfg.return_value = MagicMock(sample_rate=16000, audio_channels=1, audio_chunk_ms=30)
                am = AudioManager()
                am._playback_rate = 48000

                am._start_loopback(speaker_index=5, speaker_name="Broken Speaker")
                mock_sc.default_speaker.assert_called()
                mock_thread.assert_called_once()


def test_voice_card_red_when_loopback_fails():
    """Verify Logs tab Voice card turns red with warning when loopback cannot start."""
    with patch("archer.server._broadcast_ws"):
        # Reset card
        _update_status_board("voice", "Listening", "Listening | Mic: JLab | Speaker: LG", dot="green", is_error=False)
        assert _status_board_state["voice"]["dot"] == "green"
        assert not _status_board_state["voice"]["is_error"]

        # Call failure notification
        with patch("archer.voice.audio.get_config") as mock_cfg, patch("archer.voice.audio.get_event_bus"):
            mock_cfg.return_value = MagicMock(sample_rate=16000, audio_channels=1, audio_chunk_ms=30)
            am = AudioManager()
            am._notify_loopback_status(False)

            card = _status_board_state["voice"]
            assert card["dot"] == "red"
            assert card["is_error"] is True
            assert "TV check off: can't hear the PC's sound." in card["desc"]
