"""
Tests for the ARCHER Configuration.
"""

import pytest

from archer.config import ArcherConfig, get_config


class TestConfig:
    """Tests for the configuration system."""

    def test_default_values(self):
        """Test that default config values are set correctly."""
        config = ArcherConfig()
        assert config.app_name == "ARCHER"
        assert config.sample_rate == 16000
        assert config.audio_channels == 1
        assert config.vad_aggressiveness == 2  # Level 3 rejects speech on low-gain mics
        assert config.voice_auth_threshold == 0.85
        assert config.filler_timeout_ms == 600
        assert config.halt_phrase == "archer halt"
        assert config.halt_response_ms == 150
        assert config.claude_model == "claude-sonnet-4-5-20250929"

    def test_singleton(self):
        """Test that get_config returns the same instance."""
        # Reset singleton
        if hasattr(get_config, "_instance"):
            delattr(get_config, "_instance")

        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_mode_values(self):
        """Test that mode can be cloud or local."""
        config = ArcherConfig(ARCHER_DEFAULT_MODE="local")
        assert config.default_mode == "local"

        config = ArcherConfig(ARCHER_DEFAULT_MODE="cloud")
        assert config.default_mode == "cloud"

    def test_docker_service_urls(self):
        """Test default Docker service URLs."""
        config = ArcherConfig()
        assert config.chromadb_url == "http://127.0.0.1:8100"
        assert config.mediapipe_url == "http://127.0.0.1:8101"
        assert config.deepface_url == "http://127.0.0.1:8102"
        assert config.indextts_url == "http://127.0.0.1:8103"
