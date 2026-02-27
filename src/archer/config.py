"""
ARCHER Central Configuration.

All configuration is managed through environment variables and a SQLite-backed
runtime config store. The ToggleService reads from this store to determine
cloud/local mode for each service.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class ArcherConfig(BaseSettings):
    """Central configuration for ARCHER. Reads from .env file and environment variables."""

    # --- Identity ---
    app_name: str = "ARCHER"
    version: str = "0.4.0"

    # --- API Keys ---
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(
        default="21m00Tcm4TlvDq8ikWAM", alias="ELEVENLABS_VOICE_ID"
    )

    # --- Mode ---
    default_mode: Literal["cloud", "local"] = Field(
        default="cloud", alias="ARCHER_DEFAULT_MODE"
    )

    # --- Audio ---
    mic_device_index: int | None = Field(default=None, alias="ARCHER_MIC_DEVICE_INDEX")
    speaker_device_index: int | None = Field(
        default=None, alias="ARCHER_SPEAKER_DEVICE_INDEX"
    )
    sample_rate: int = 16000
    audio_channels: int = 1

    @field_validator("mic_device_index", "speaker_device_index", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: Any) -> int | None:
        """Treat empty strings from .env as None (triggers interactive selection)."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v
    audio_chunk_ms: int = 30  # 30ms chunks for VAD

    # --- Camera (Observer) ---
    # Local webcam (used when GUI is active)
    webcam_device: int = Field(default=0, alias="ARCHER_WEBCAM_DEVICE")
    # Network camera RTSP URL (used when GUI is minimized / headless)
    network_camera_url: str = Field(default="", alias="ARCHER_NETWORK_CAMERA_URL")

    @field_validator("webcam_device", mode="before")
    @classmethod
    def _parse_webcam_device(cls, v: Any) -> int:
        """Parse webcam device index from env."""
        if isinstance(v, str):
            stripped = v.strip()
            return int(stripped) if stripped else 0
        return v

    # --- Voice Pipeline ---
    wake_word: str = "hey_archer"
    wake_word_threshold: float = 0.3
    vad_aggressiveness: int = 2  # webrtcvad: 0-3. Level 3 rejects speech on low-gain mics.
    stt_model: str = "base.en"  # Faster-Whisper model for local STT
    stt_model_large: str = "large-v3"  # For accuracy mode
    voice_auth_threshold: float = 0.85  # Cosine similarity for voice verification
    filler_timeout_ms: int = 600  # Play filler if no response in 600ms

    # --- Agent ---
    claude_model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096
    agent_temperature: float = 0.7

    # --- Memory ---
    sqlite_db_path: str = Field(default="data/archer.db", alias="ARCHER_DB_PATH")

    # --- Paths ---
    data_dir: Path = Field(default=Path("data"), alias="ARCHER_DATA_DIR")
    log_dir: Path = Field(default=Path("logs"), alias="ARCHER_LOG_DIR")
    soul_dir: Path = Field(default=Path("src/archer/agents"))

    # --- Server ---
    api_host: str = "127.0.0.1"
    api_port: int = 8200

    # --- Docker Services ---
    chromadb_url: str = "http://127.0.0.1:8100"
    mediapipe_url: str = "http://127.0.0.1:8101"
    deepface_url: str = "http://127.0.0.1:8102"
    indextts_url: str = "http://127.0.0.1:8103"
    redis_url: str = "redis://127.0.0.1:6377/0"
    openmemory_db: str = "data/openmemory.db"
    memory_decay: bool = False

    # NVIDIA NIM Models
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    # Agent-specific model selection
    assistant_model: str = Field(default="moonshotai/kimi-k2.5", alias="ARCHER_ASSISTANT_MODEL")
    therapist_model: str = Field(default="qwen/qwen3.5-397b-a17b", alias="ARCHER_THERAPIST_MODEL")
    trainer_model: str = Field(default="meta/llama-3.3-70b-instruct", alias="ARCHER_TRAINER_MODEL")
    investment_model: str = Field(default="qwen/qwen3.5-397b-a17b", alias="ARCHER_INVESTMENT_MODEL")
    observer_model: str = Field(default="qwen2.5vl:7b", alias="ARCHER_OBSERVER_MODEL")

    # Local Vision (Ollama)
    ollama_base_url: str = "http://localhost:11434"
    use_local_vision: bool = True

    # --- HALT ---
    halt_phrase: str = "archer halt"
    halt_response_ms: int = 150  # Max time to respond to HALT

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


def _list_audio_devices() -> list[dict]:
    """List all available audio devices via sounddevice."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        result = []
        for i, dev in enumerate(devices):
            result.append({
                "index": i,
                "name": dev["name"],
                "max_input": dev["max_input_channels"],
                "max_output": dev["max_output_channels"],
                "default_sr": dev["default_samplerate"],
            })
        return result
    except Exception:
        return []


def _pick_device(direction: str, devices: list[dict]) -> int:
    """
    Show available devices and let the user pick one interactively.

    Args:
        direction: 'input' or 'output'
        devices: list of device dicts from _list_audio_devices
    """
    key = "max_input" if direction == "input" else "max_output"
    label = "MICROPHONE" if direction == "input" else "SPEAKER"
    candidates = [d for d in devices if d[key] > 0]

    if not candidates:
        print(f"\n⚠  No {direction} audio devices found!")
        print("   ARCHER will run in text-only mode.")
        return -1

    print(f"\n🎤 Select your {label}:")
    print(f"   {'Index':<7} {'Channels':<10} {'Sample Rate':<13} Name")
    print(f"   {'─'*7} {'─'*10} {'─'*13} {'─'*30}")
    for d in candidates:
        ch = d[key]
        sr = int(d["default_sr"])
        print(f"   {d['index']:<7} {ch:<10} {sr:<13} {d['name']}")

    while True:
        try:
            choice = input(f"\n   Enter {direction} device index: ").strip()
            idx = int(choice)
            if any(d["index"] == idx for d in candidates):
                selected = next(d for d in candidates if d["index"] == idx)
                print(f"   ✓ Selected: {selected['name']}")
                return idx
            else:
                print(f"   ✗ Invalid index. Choose from: {[d['index'] for d in candidates]}")
        except (ValueError, EOFError):
            print(f"   ✗ Please enter a valid integer.")


def _save_device_to_env(key: str, value: int) -> None:
    """Write a device index back to .env so the user doesn't have to pick again."""
    env_path = Path(".env")
    if not env_path.exists():
        return

    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_audio_devices(config: ArcherConfig) -> None:
    """
    If mic or speaker device indices are not set, detect devices
    and prompt the user to select interactively.
    """
    if config.mic_device_index is not None and config.speaker_device_index is not None:
        return  # Both already set

    devices = _list_audio_devices()
    if not devices:
        print("\n⚠  Could not query audio devices. Continuing with defaults.")
        return

    if config.mic_device_index is None:
        idx = _pick_device("input", devices)
        if idx >= 0:
            config.mic_device_index = idx
            _save_device_to_env("ARCHER_MIC_DEVICE_INDEX", idx)

    if config.speaker_device_index is None:
        idx = _pick_device("output", devices)
        if idx >= 0:
            config.speaker_device_index = idx
            _save_device_to_env("ARCHER_SPEAKER_DEVICE_INDEX", idx)

    print()  # Blank line after device selection


def get_config() -> ArcherConfig:
    """Get the global ARCHER configuration. Cached singleton."""
    if not hasattr(get_config, "_instance"):
        get_config._instance = ArcherConfig()

        # Ensure directories exist
        get_config._instance.data_dir.mkdir(parents=True, exist_ok=True)
        get_config._instance.log_dir.mkdir(parents=True, exist_ok=True)

        # Resolve audio devices interactively if not set
        _resolve_audio_devices(get_config._instance)

    return get_config._instance
