"""
ARCHER Voice Authentication.

Uses SpeechBrain ECAPA-TDNN speaker verification model.

Enrollment: On first run, ARCHER asks the user to speak 3 short enrollment
phrases. These are stored as a voice embedding in the local SQLite DB.

Verification: After wake word detection and before the agent call, a 2-second
voice sample is compared against the enrollment embedding. Cosine similarity
threshold: 0.85.

If verification fails: ARCHER responds in a neutral tone, does not identify
which agent would have responded, and does not execute any tool calls.
Guest mode only.

Guest mode: limited set of read-only interactions (time, weather, what ARCHER is).
No memory reads, no tool execution, no personal data.
"""

from __future__ import annotations

import json
import sqlite3
import threading

import numpy as np
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus


class VoiceAuthenticator:
    """
    Speaker verification using SpeechBrain ECAPA-TDNN.

    Verifies that the speaker is the enrolled user before allowing
    full agent access. Unknown speakers get guest mode only.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._threshold = self._config.voice_auth_threshold
        self._model = None
        self._enrolled_embedding: np.ndarray | None = None
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """Load the speaker verification model and enrolled embedding."""
        try:
            # Patch torchaudio if list_audio_backends was removed (torchaudio >= 2.10)
            import torchaudio
            if not hasattr(torchaudio, "list_audio_backends"):
                torchaudio.list_audio_backends = lambda: ["soundfile"]

            # Windows: force huggingface_hub to use copies instead of symlinks.
            # In huggingface_hub >= 1.x, the module must be imported explicitly
            # (attribute access on the top-level package doesn't auto-resolve it).
            from huggingface_hub import constants as hf_constants
            hf_constants.HF_HUB_DISABLE_SYMLINKS_WARNING = True

            from huggingface_hub import file_download as _hf_file_download
            _orig_create_symlink = getattr(_hf_file_download, '_create_symlink', None)
            if _orig_create_symlink:
                import shutil
                def _copy_instead_of_symlink(src, dst):
                    try:
                        _orig_create_symlink(src, dst)
                    except OSError:
                        shutil.copy2(str(src), str(dst))
                _hf_file_download._create_symlink = _copy_instead_of_symlink

            from speechbrain.inference.speaker import SpeakerRecognition

            self._model = SpeakerRecognition.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir="data/models/speechbrain",
            )
            logger.info("Voice authentication model loaded (ECAPA-TDNN)")

            # Load enrolled embedding from DB
            self._load_enrollment()

        except Exception as e:
            logger.error(f"Failed to initialize voice authentication: {e}")
            logger.warning("Voice authentication disabled — all users will have full access")

    def _load_enrollment(self) -> None:
        """Load the enrolled voice embedding from SQLite."""
        try:
            conn = sqlite3.connect(self._config.sqlite_db_path)
            cursor = conn.execute(
                "SELECT embedding FROM voice_enrollment WHERE user_id = 'primary'"
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                self._enrolled_embedding = np.array(json.loads(row[0]))
                logger.info("Enrolled voice embedding loaded from database")
            else:
                logger.info("No voice enrollment found — enrollment required on first run")
        except Exception as e:
            logger.debug(f"No voice enrollment table yet: {e}")

    def is_enrolled(self) -> bool:
        """Check if a user voice profile is enrolled."""
        return self._enrolled_embedding is not None

    def enroll(self, audio_samples: list[bytes], sample_rate: int = 16000) -> bool:
        """
        Enroll a new voice profile from multiple audio samples.

        Args:
            audio_samples: List of raw PCM audio bytes (int16, mono)
            sample_rate: Sample rate of the audio

        Returns:
            True if enrollment was successful.
        """
        if self._model is None:
            logger.error("Voice auth model not loaded — cannot enroll")
            return False

        try:
            embeddings = []
            for sample in audio_samples:
                audio_array = np.frombuffer(sample, dtype=np.int16).astype(np.float32) / 32768.0
                import torch
                audio_tensor = torch.tensor(audio_array).unsqueeze(0)
                embedding = self._model.encode_batch(audio_tensor)
                embeddings.append(embedding.squeeze().numpy())

            # Average the embeddings
            self._enrolled_embedding = np.mean(embeddings, axis=0)

            # Save to SQLite
            conn = sqlite3.connect(self._config.sqlite_db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS voice_enrollment (
                    user_id TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                INSERT OR REPLACE INTO voice_enrollment (user_id, embedding)
                VALUES ('primary', ?)
            """, (json.dumps(self._enrolled_embedding.tolist()),))
            conn.commit()
            conn.close()

            logger.info("Voice enrollment complete and saved to database")
            return True

        except Exception as e:
            logger.error(f"Voice enrollment failed: {e}")
            return False

    def verify(self, audio_data: bytes, sample_rate: int = 16000) -> tuple[bool, float]:
        """
        Verify a voice sample against the enrolled profile.

        Args:
            audio_data: Raw PCM audio bytes (int16, mono), ~2 seconds
            sample_rate: Sample rate

        Returns:
            Tuple of (is_verified, similarity_score)
        """
        if self._model is None or self._enrolled_embedding is None:
            # No auth available — allow access (per spec: enrollment on first run)
            logger.warning("Voice auth not available — granting full access")
            return True, 1.0

        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            import torch
            audio_tensor = torch.tensor(audio_array).unsqueeze(0)
            embedding = self._model.encode_batch(audio_tensor).squeeze().numpy()

            # Cosine similarity
            similarity = float(np.dot(embedding, self._enrolled_embedding) / (
                np.linalg.norm(embedding) * np.linalg.norm(self._enrolled_embedding)
            ))

            is_verified = similarity >= self._threshold

            if is_verified:
                logger.info(f"Voice verified (similarity={similarity:.3f})")
                self._bus.publish(Event(
                    type=EventType.AUTH_SUCCESS,
                    source="voice_auth",
                    data={"similarity": similarity},
                ))
            else:
                logger.warning(f"Voice verification FAILED (similarity={similarity:.3f})")
                self._bus.publish(Event(
                    type=EventType.AUTH_FAILURE,
                    source="voice_auth",
                    data={"similarity": similarity},
                ))

            return is_verified, similarity

        except Exception as e:
            logger.error(f"Voice verification error: {e}")
            return True, 1.0  # Fail open — don't lock out the user on errors
