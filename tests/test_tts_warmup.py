"""
Unit tests for TTS background warm-up (Review 2026-10-21 18:15 Item 3).
"""

from unittest.mock import MagicMock, patch
import pytest

from archer.voice.tts import LocalTTS, TTSService


def test_local_tts_warm_up_calls_synthesize():
    """Verify LocalTTS.warm_up synthesizes phrases and catches any non-fatal errors."""
    with patch.object(LocalTTS, "_init_kokoro"):
        tts = LocalTTS()
        with patch.object(tts, "synthesize", return_value=(b"fake_wav", 24000)) as mock_synth:
            tts.warm_up()
            assert mock_synth.call_count >= 2
            # Check that it called synthesize with string phrases
            for call in mock_synth.call_args_list:
                assert isinstance(call[0][0], str)
                assert len(call[0][0]) > 0


def test_local_tts_warm_up_resilient_to_errors():
    """Verify LocalTTS.warm_up does not raise if synthesize fails."""
    with patch.object(LocalTTS, "_init_kokoro"):
        tts = LocalTTS()
        with patch.object(tts, "synthesize", side_effect=RuntimeError("Synthesis failed")):
            # Should not raise
            tts.warm_up()


def test_tts_service_warm_up_delegates():
    """Verify TTSService.warm_up delegates to LocalTTS."""
    with patch.object(LocalTTS, "_init_kokoro"):
        service = TTSService()
        with patch.object(service._local, "warm_up") as mock_warm_up:
            service.warm_up()
            assert mock_warm_up.called


def test_voice_pipeline_spawns_tts_warmup_thread():
    """Verify VoicePipeline.initialize spawns a TTSWarmUp thread."""
    with patch("archer.voice.pipeline.get_audio_manager"), \
         patch("archer.voice.pipeline.WakeWordDetector"), \
         patch("archer.voice.pipeline.VoiceActivityDetector"), \
         patch("archer.voice.pipeline.STTService"), \
         patch("archer.voice.pipeline.TTSService") as mock_tts_cls, \
         patch("archer.voice.pipeline.HaltListener"), \
         patch("archer.voice.pipeline.VoiceAuthenticator"), \
         patch("archer.voice.pipeline.threading.Thread") as mock_thread:

        mock_tts_instance = MagicMock()
        mock_tts_cls.return_value = mock_tts_instance

        from archer.voice.pipeline import VoicePipeline
        pipeline = VoicePipeline()
        pipeline.initialize()

        # Check that threading.Thread was called with name="TTSWarmUp"
        thread_names = [call.kwargs.get("name") for call in mock_thread.call_args_list]
        assert "TTSWarmUp" in thread_names
