"""
Tests for ARCHER Voice Stack (STT, TTS, VAD, HALT, Wake Word).
"""

import pytest
from unittest.mock import MagicMock, patch
import numpy as np

from archer.config import ArcherConfig
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.core.toggle import ToggleService
from archer.voice.stt import STTService, CloudSTT, LocalSTT, ParakeetSTT
from archer.voice.tts import TTSService, CloudTTS, LocalTTS, FILLER_PHRASES
from archer.voice.vad import VoiceActivityDetector
from archer.voice.halt import HaltListener
from archer.voice.wake_word import WakeWordDetector


class TestSTTStack:
    """Tests for STT backends and service routing."""

    def test_parakeet_stt_transcribe_success(self):
        """ParakeetSTT should transcribe using NeMo model when available."""
        stt = ParakeetSTT()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ["Hello ARCHER"]
        stt._model = mock_model

        dummy_pcm = b"\x00\x00" * 1600
        result = stt.transcribe(dummy_pcm)
        assert result == "Hello ARCHER"

    def test_parakeet_stt_failure_raises(self):
        """ParakeetSTT should raise exception when model fails."""
        stt = ParakeetSTT()
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("GPU out of memory")
        stt._model = mock_model

        dummy_pcm = b"\x00\x00" * 1600
        with pytest.raises(RuntimeError):
            stt.transcribe(dummy_pcm)

    def test_local_stt_fallback_parakeet_to_whisper(self):
        """LocalSTT should fall back to Faster-Whisper if Parakeet fails."""
        local_stt = LocalSTT()
        local_stt._config.stt_provider = "parakeet"

        # Mock Parakeet failure
        mock_parakeet = MagicMock()
        mock_parakeet.is_available.return_value = True
        mock_parakeet.transcribe.side_effect = Exception("Parakeet failed")
        local_stt._parakeet = mock_parakeet

        # Mock Whisper success
        mock_whisper = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Whisper fallback transcript"
        mock_whisper.transcribe.return_value = ([mock_segment], None)
        local_stt._whisper = mock_whisper

        dummy_pcm = b"\x00\x00" * 1600
        text = local_stt.transcribe(dummy_pcm)
        assert text == "Whisper fallback transcript"
        mock_parakeet.transcribe.assert_called_once()

    def test_local_stt_uses_whisper_when_configured(self):
        """LocalSTT should use Whisper directly when stt_provider is whisper."""
        local_stt = LocalSTT()
        local_stt._config.stt_provider = "whisper"

        mock_whisper = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "Direct Whisper result"
        mock_whisper.transcribe.return_value = ([mock_segment], None)
        local_stt._whisper = mock_whisper

        dummy_pcm = b"\x00\x00" * 1600
        text = local_stt.transcribe(dummy_pcm)
        assert text == "Direct Whisper result"

    def test_stt_service_cloud_to_local_fallback(self):
        """STTService should fall back to local when cloud STT fails."""
        service = STTService()
        service._toggle.mode = "cloud"

        # Mock Cloud failure
        mock_cloud = MagicMock()
        mock_cloud.is_available.return_value = True
        mock_cloud.transcribe.side_effect = Exception("Cloud network error")
        service._cloud = mock_cloud

        # Mock Local success
        mock_local = MagicMock()
        mock_local.transcribe.return_value = "Local fallback result"
        service._local = mock_local

        dummy_pcm = b"\x00\x00" * 1600
        result = service.transcribe(dummy_pcm)
        assert result == "Local fallback result"
        assert not service._toggle.is_cloud  # Mode switched to local


class TestTTSStack:
    """Tests for TTS backends and service routing."""

    @patch("httpx.post")
    def test_local_tts_chatterbox_synthesis(self, mock_post):
        """LocalTTS should call Chatterbox container endpoint on HTTP fallback."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"RIFF....WAVEfmt "
        mock_resp.headers = {"X-Sample-Rate": "24000"}
        mock_post.return_value = mock_resp

        local_tts = LocalTTS()
        local_tts._kokoro_pipeline = None
        audio_bytes, sr = local_tts.synthesize("Hello Chatterbox")
        assert audio_bytes == b"RIFF....WAVEfmt "
        assert sr == 24000
        assert mock_post.called

    @patch("httpx.get")
    def test_local_tts_availability_check(self, mock_get):
        """LocalTTS is_available should check /health endpoint."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        local_tts = LocalTTS()
        assert local_tts.is_available()

    def test_tts_service_cloud_and_local_selection(self):
        """TTSService selects active backend and falls back if needed."""
        service = TTSService()
        service._toggle.mode = "local"

        mock_local = MagicMock()
        mock_local.synthesize.return_value = (b"AUDIO_DATA", 24000)
        service._local = mock_local

        res = service.synthesize("Test speech")
        assert res == (b"AUDIO_DATA", 24000)

    def test_tts_filler_phrases(self):
        """TTSService should return valid filler phrases."""
        service = TTSService()
        filler = service.get_filler_text()
        assert filler in FILLER_PHRASES


class TestHaltListener:
    """Tests for HALT command detection."""

    def test_text_halt_variants(self):
        """HaltListener should detect all phrase variants."""
        listener = HaltListener()
        bus = get_event_bus()

        halt_events = []
        def on_halt(event):
            halt_events.append(event)

        bus.subscribe_halt(on_halt)

        assert listener.check_text_for_halt("ARCHER HALT immediately")
        assert len(halt_events) == 1

        assert listener.check_text_for_halt("Please archer stop")
        assert len(halt_events) == 2

    def test_normal_text_does_not_trigger_halt(self):
        """Normal conversational text should not trigger HALT."""
        listener = HaltListener()
        assert not listener.check_text_for_halt("How is the weather today?")


class TestVoiceActivityDetector:
    """Tests for VAD speech onset and offset logic."""

    def test_vad_process_audio_chunk_size(self):
        """VAD should accept audio chunks and process without error."""
        vad = VoiceActivityDetector()
        # 30ms chunk at 16kHz int16 mono = 30 * 16 * 2 = 960 bytes
        chunk = b"\x00" * 960
        is_speaking = vad.process_audio(chunk)
        assert isinstance(is_speaking, bool)
