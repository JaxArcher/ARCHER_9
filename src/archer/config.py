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
    # Personal single-user assistant: default to local models. Cloud is
    # available via the toggle whenever a cloud-delegation trigger fires
    # (see CoreAgent.evaluate_cloud_delegation) or the user flips it
    # explicitly -- it should never be the silent default.
    default_mode: Literal["cloud", "local"] = Field(
        default="local", alias="ARCHER_DEFAULT_MODE"
    )

    # TTS engine is its OWN toggle, independent of default_mode above
    # (2026-09-16, Col's call). default_mode governs conversation (LLM) +
    # STT only.
    #
    # Flipped to "local" 2026-09-16 (Col's call): originally defaulted to
    # "cloud" (ElevenLabs) on the assumption the monthly subscription
    # covered usage — turned out ElevenLabs bills per-credit on top of the
    # subscription and Col's .env key was actually a key ID, not a usable
    # secret (repeated 400 invalid_api_key on both TTS and STT). The
    # existing cloud-failure auto-fallback (ToggleService, see
    # trigger_cloud_fallback below) already caught this live and flipped
    # the persisted toggle_state row to local, but that's a reactive patch
    # per-install; this changes what a FRESH install (or a cleared
    # toggle_state table) starts with, so a broken/unset ElevenLabs key
    # doesn't cost a failed round-trip on every single turn before falling
    # back. Flip back to "cloud" here (or via the browser TTS toggle) once
    # the ElevenLabs key is fixed, if cloud voice is still wanted.
    default_tts_mode: Literal["cloud", "local"] = Field(
        default="local", alias="ARCHER_DEFAULT_TTS_MODE"
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
    wake_word: str = "hey_archer"  # Supported built-in fallback triggers: Alexa, Hey Jarvis, Hey Mycroft, Hey Rhasspy
    # 0.20 was far too permissive — real detections score 0.85-0.98, but
    # background noise / audio-stream glitches routinely score 0.2-0.3 on
    # one of the 4 simultaneously-running models, causing false wake-ups.
    # Raised to sit well above the noise floor and well below genuine hits.
    wake_word_threshold: float = 0.55
    vad_aggressiveness: int = 2  # webrtcvad: 0-3. Level 3 rejects speech on low-gain mics.
    stt_provider: str = Field(default="whisper", alias="ARCHER_STT_PROVIDER")  # whisper or parakeet
    stt_model: str = "base.en"  # Faster-Whisper model for local STT
    stt_model_large: str = "large-v3"  # For accuracy mode
    voice_auth_threshold: float = 0.85  # Cosine similarity for voice verification
    # Play a filler ("One moment...") only if the first sentence hasn't
    # arrived within this window. Raised from 600ms now that the pipeline
    # speed fixes (brevity limit, gated ambient context, no vision-loop
    # contention) got typical first-token latency well under a second —
    # 600ms was firing on nearly every request. Kept nonzero (rather than
    # disabled outright) as a safety net for genuinely slow calls (cloud
    # delegation, vision analysis) where silence would otherwise look like
    # ARCHER froze.
    filler_timeout_ms: int = 3000

    # --- Agent ---
    claude_model: str = "claude-sonnet-5"
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
    chatterbox_url: str = Field(default="http://127.0.0.1:8103", alias="CHATTERBOX_URL")
    indextts_url: str = Field(default="http://127.0.0.1:8103", alias="INDEXTTS_URL")  # Backward compatibility alias
    redis_url: str = "redis://127.0.0.1:6377/0"
    openmemory_db: str = "data/openmemory.db"
    memory_decay: bool = False
    observer_analysis_frequency: float = 30.0  # 30 seconds as per spec

    # NVIDIA NIM Models
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    # Agent-specific model selection
    assistant_model: str = Field(default="moonshotai/kimi-k2.5", alias="ARCHER_ASSISTANT_MODEL")
    therapist_model: str = Field(default="qwen/qwen3.5-397b-a17b", alias="ARCHER_THERAPIST_MODEL")
    trainer_model: str = Field(default="qwen/qwen3.6-35b-a3b", alias="ARCHER_TRAINER_MODEL")
    investment_model: str = Field(default="qwen/qwen3.5-397b-a17b", alias="ARCHER_INVESTMENT_MODEL")
    # qwen2.5vl:7b hits a known upstream Ollama/llama.cpp bug: it crashes
    # with HTTP 500 on specific real-world images (works fine on synthetic
    # warmup images) even on the latest Ollama release — see
    # https://github.com/ollama/ollama/issues/14170. moondream is smaller,
    # far more mature in Ollama's vision pipeline, and was the original
    # model used here before this was ever changed.
    observer_model: str = Field(default="moondream", alias="ARCHER_OBSERVER_MODEL")

    # Local Vision (Ollama)
    # NOTE: alias is intentionally NOT "OLLAMA_HOST" — that's Ollama's own
    # standard env var for telling `ollama serve` which address to bind to.
    # Reusing it here meant that setting OLLAMA_HOST to start a second
    # (port 11435) Ollama instance for the observer/vision pipeline
    # silently overrode THIS setting too if it ever leaked out of that one
    # shell into ARCHER's own environment (e.g. set persistently rather
    # than per-window) — breaking the main qwen3:8b chat calls with
    # "Request URL is missing an 'http://' or 'https://' protocol." since
    # the raw OLLAMA_HOST value (host:port, no scheme) got used directly.
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="ARCHER_OLLAMA_BASE_URL")
    # History: this second instance originally ran CPU-only
    # (CUDA_VISIBLE_DEVICES="") to fully isolate it from the main GPU
    # model. That was a bad trade at the time: CPU inference forced 20-60s
    # cold-start waits and, worse, pinned the CPU hard enough to starve
    # STT/audio scheduling during active conversation -- so on 2026-09-16
    # it moved to GPU instead (~1.2GB VRAM, confirmed via live Ollama
    # logs), trading VRAM for safety.
    #
    # Reverted back to CPU-only on 2026-09-19 (Col's call): GPU headroom
    # matters more now (every GB counts toward fitting a real vision
    # model), and the thing that made CPU risky -- the observer running
    # its analysis cycle WHILE ARCHER was actively being used -- is now
    # actually prevented: ObserverPipeline._analysis_loop checks a
    # Redis-backed cross-process flag (RedisBuffer.is_gui_active,
    # refreshed by server.py's heartbeat) and skips its own analysis
    # cycle entirely while any browser client is connected. See
    # integrations/ollama_bootstrap.py's force_cpu param, which is what
    # actually sets CUDA_VISIBLE_DEVICES="" for this instance now.
    observer_ollama_url: str = Field(default="http://127.0.0.1:11435", alias="OBSERVER_OLLAMA_HOST")
    use_local_vision: bool = True

    # --- Observer motion-gating (2026-09-16) ---
    # The standalone observer service (archer/observer_service.py) no
    # longer analyzes on a flat timer regardless of activity -- it stays
    # fully quiet until Reolink's own ONVIF person-detection signal opens
    # an active window (see observer/pipeline.py's notify_motion), then
    # analyzes at this tighter cadence for as long as signals keep
    # arriving, plus at least this many seconds after the last one
    # (Col's explicit ask). observer_analysis_frequency (above/below,
    # wherever it's defined) becomes the fallback flat-timer cadence used
    # only when no network_camera_url is configured at all -- some ambient
    # observation without a motion signal to gate on beats none.
    observer_motion_active_interval: float = Field(default=5.0, alias="ARCHER_OBSERVER_ACTIVE_INTERVAL")
    observer_motion_tail_seconds: float = Field(default=30.0, alias="ARCHER_OBSERVER_MOTION_TAIL")

    # --- Staleness / neglect reasoning (2026-09-16) ---
    # Deliberately NOT a hardcoded checklist (Col's explicit requirement)
    # -- observer/staleness_reasoner.py asks the local model to use its
    # own judgment over a window of recent scene descriptions, rather than
    # being told what to look for (dishes, laundry, etc). Runs on its own
    # cadence, independent of motion -- the whole point is noticing things
    # that stayed the same for too long, which by definition won't be
    # caught by a motion trigger.
    observer_staleness_interval_hours: float = Field(default=4.0, alias="ARCHER_OBSERVER_STALENESS_INTERVAL_HOURS")
    observer_staleness_lookback_hours: float = Field(default=48.0, alias="ARCHER_OBSERVER_STALENESS_LOOKBACK_HOURS")

    # Local Fallback
    local_fallback_model: str = Field(default="qwen3.5:4b", alias="ARCHER_LOCAL_MODEL")
    enable_auto_fallback: bool = Field(default=True, alias="ARCHER_ENABLE_FALLBACK")

    # ARCHER "reflective mode" profile learning (2026-09-17, see
    # /areas/reflective-mode.md). Gates CoreAgent._maybe_extract_profile_insight
    # -- the write path that distills a reflective conversation into a
    # standing profile_facts row. Defaults OFF: Col's explicit call was to
    # hold off on any of his real personal/biographical data entering
    # ARCHER's memory until the system is stable. The read side (the
    # standing profile block in build_context_system_prompt) works
    # regardless of this flag -- it just has nothing to read until either
    # this is turned on or a fact is inserted directly -- but the WRITE
    # path must stay behind this flag so a live conversation can't
    # silently start recording personal disclosures before Col says so.
    profile_learning_enabled: bool = Field(default=False, alias="ARCHER_PROFILE_LEARNING_ENABLED")

    # Local Primary Model (CoreAgent Single-Agent Architecture)
    # Switched from qwen3:8b (text-only) to gemma4:e4b (2026-09-16, Col's
    # call): natively multimodal at every size (no separate vision adapter),
    # ~86% tool-calling accuracy in third-party benchmarks — needed so the
    # LOCAL model can both call tools (screenshots, PC control, etc.) and
    # actually see the image a screenshot tool returns, not just be told
    # one was taken. ~9.6GB VRAM (e4b tag) on a 16GB card, leaving room for
    # moondream (still used separately for webcam vision — see
    # observer_model below and core_agent.py's _check_visual_query).
    #
    # Switched again 2026-09-19 (Col's find, confirmed against Ollama's own
    # library listing): the plain "gemma4:e4b" tag turned out to be
    # packaged TEXT-ONLY in Ollama despite Gemma 4's architecture having a
    # real vision+audio projector -- that's the actual root cause of the
    # whole "camera feed isn't being seen" investigation (empirically
    # confirmed: even a bare, ARCHER-free request to plain gemma4:e4b with
    # an image attached produced ungrounded hallucinations, never a real
    # description). "gemma4:e4b-it-qat" is a separate Ollama tag that DOES
    # bundle that projector -- Ollama's own listing states it supports
    # both text and image input -- while remaining the same underlying
    # instruction-tuned Gemma 4 model, just QAT-quantized (~6.1GB, smaller
    # than plain e4b's ~9.6GB too).
    # Requires `ollama pull gemma4:e4b-it-qat` on the machine running
    # Ollama — ARCHER does not and cannot pull models for you.
    core_primary_model: str = Field(
        default="gemma4:e4b-it-qat", alias="ARCHER_CORE_PRIMARY_MODEL"
    )

    # --- Nightly Maintenance (2026-09-16) ---
    # memory/maintenance.py's run_maintenance() (daily consolidation +
    # OpenMemory reflection) existed fully built but was never scheduled
    # anywhere -- start_maintenance_scheduler() fires it once per day at
    # this local hour (24h clock). 3am is a quiet-hours default; change if
    # ARCHER is regularly still in active use at that time.
    maintenance_hour: int = Field(default=3, alias="ARCHER_MAINTENANCE_HOUR")

    # --- HALT ---
    halt_phrase: str = "archer halt"
    halt_response_ms: int = 150  # Max time to respond to HALT

    # --- barehands (optional third-party gesture/face bridge) ---
    # Path to a locally-cloned https://github.com/jaredrhod/barehands checkout.
    # ARCHER never clones/installs this itself (untrusted-source download
    # policy) -- the user sets this up by hand, then points ARCHER at it.
    # Empty string (default) disables the bridge entirely, silently.
    barehands_dir: str = Field(default="", alias="ARCHER_BAREHANDS_DIR")

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
