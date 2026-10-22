"""
ARCHER Telegram Line (Phase 6b, Spec Section 10d).

Enables Col to talk to ARCHER from anywhere through Telegram on his phone:
- Long polling (no open ports or webhooks on the home network).
- Strict whitelist: only Col's Telegram user ID (ARCHER_TELEGRAM_USER_ID) is answered.
- Text chat routed to AgentOrchestrator.
- Voice notes transcribed with Whisper, and replied to with Kokoro voice notes.
- Phase 3 Approval prompts: sent with inline keyboard buttons (Approve, Deny, Session).
- HALT commands immediately interrupt execution.
- Forwarded files/photos saved to data/artifacts/telegram/.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from archer.config import get_config
from archer.core.approvals import get_approval_manager
from archer.core.event_bus import Event, EventType, get_event_bus


class TelegramLineService:
    """Manages the Telegram Bot integration using aiogram."""

    _instance: Optional[TelegramLineService] = None
    _lock = threading.Lock()

    def __new__(cls) -> TelegramLineService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._config = get_config()
        self._bus = get_event_bus()
        self._approval_mgr = get_approval_manager()

        self._bot = None
        self._dp = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._pending_msg_ids: Dict[str, int] = {}  # req_id -> message_id

        # Register event listeners
        self._bus.subscribe(EventType.APPROVAL_REQUESTED, self._on_approval_requested)
        self._bus.subscribe(EventType.APPROVAL_RESOLVED, self._on_approval_resolved)

        self._initialized = True

    def _is_authorized(self, user_id: int, username: str = "") -> bool:
        """Check if user matches Col's configured Telegram ID."""
        allowed_id = self._config.telegram_user_id
        if allowed_id is None:
            logger.warning(
                f"[Telegram] ARCHER_TELEGRAM_USER_ID not set in .env. "
                f"Ignoring message from user_id={user_id} (@{username}). "
                f"Set ARCHER_TELEGRAM_USER_ID={user_id} to authorize this user."
            )
            return False

        if user_id != allowed_id:
            logger.warning(
                f"[Telegram] Unauthorized message from user_id={user_id} (@{username}): ignored."
            )
            return False

        return True

    def is_running(self) -> bool:
        """Check if Telegram polling service is actively running."""
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start Telegram bot polling in a dedicated background thread."""
        token = (self._config.telegram_bot_token or "").strip()
        if not token:
            logger.info(
                "[Telegram] Bot token not configured in .env (ARCHER_TELEGRAM_BOT_TOKEN). "
                "Telegram line disabled."
            )
            return False

        if self.is_running():
            logger.debug("[Telegram] Service is already running.")
            return True

        self._running = True
        self._thread = threading.Thread(
            target=self._run_bot_loop,
            daemon=True,
            name="archer-telegram-line"
        )
        self._thread.start()
        logger.info("[Telegram] Telegram line service started (long-polling).")
        return True

    def stop(self) -> None:
        """Stop Telegram bot polling cleanly."""
        if not self._running:
            return

        self._running = False
        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception as e:
                logger.debug(f"[Telegram] Error stopping event loop: {e}")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("[Telegram] Telegram line service stopped.")

    def _run_bot_loop(self) -> None:
        """Thread worker creating its own asyncio loop for aiogram polling."""
        try:
            from aiogram import Bot, Dispatcher, F, types
            from aiogram.filters import Command
            from aiogram.types import (
                BufferedInputFile,
                CallbackQuery,
                InlineKeyboardButton,
                InlineKeyboardMarkup,
                Message,
            )
        except ImportError:
            logger.error("[Telegram] aiogram is not installed. Telegram line cannot start.")
            self._running = False
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        bot = Bot(token=self._config.telegram_bot_token)
        dp = Dispatcher()
        self._bot = bot
        self._dp = dp

        # --- Message Handlers ---

        @dp.message(Command("start", "help"))
        async def cmd_start(msg: Message) -> None:
            user = msg.from_user
            if not user or not self._is_authorized(user.id, user.username or ""):
                return

            await msg.answer(
                "👋 **ARCHER Telegram Line**\n\n"
                "Connected to your ARCHER assistant.\n"
                "- Send text to converse\n"
                "- Send voice notes (processed via Whisper, replied with Kokoro)\n"
                "- Approvals will appear here with buttons\n"
                "- Send `/halt` for emergency stop"
            )

        @dp.message(Command("halt"))
        async def cmd_halt(msg: Message) -> None:
            user = msg.from_user
            if not user or not self._is_authorized(user.id, user.username or ""):
                return

            self._bus.publish_halt("telegram")
            await msg.answer("🛑 **HALT triggered.** All active operations and speech stopped.")

        @dp.message(F.voice | F.audio)
        async def handle_voice(msg: Message) -> None:
            user = msg.from_user
            if not user or not self._is_authorized(user.id, user.username or ""):
                return

            voice = msg.voice or msg.audio
            if not voice:
                return

            status_msg = await msg.answer("🎧 _Listening to voice note..._")
            try:
                # 1. Download voice note bytes
                file_io = io.BytesIO()
                await bot.download(voice, destination=file_io)
                file_bytes = file_io.getvalue()

                # 2. Transcribe with Whisper
                transcribed_text = await self._transcribe_audio_bytes(file_bytes)
                if not transcribed_text:
                    await status_msg.edit_text("⚠️ Could not transcribe audio (no clear speech detected).")
                    return

                await status_msg.edit_text(f"🗣 _{transcribed_text}_")

                # 3. Process via Orchestrator
                reply_text = await self._process_orchestrator_request(transcribed_text)
                await msg.answer(reply_text)

                # 4. Synthesize voice note reply via Kokoro
                voice_reply_bytes = await self._synthesize_voice_reply(reply_text)
                if voice_reply_bytes:
                    voice_file = BufferedInputFile(voice_reply_bytes, filename="archer_reply.ogg")
                    await msg.answer_voice(voice_file)

            except Exception as e:
                logger.error(f"[Telegram] Failed handling voice note: {e}")
                await status_msg.edit_text(f"⚠️ Error processing voice note: {e}")

        @dp.message(F.photo | F.document)
        async def handle_attachment(msg: Message) -> None:
            user = msg.from_user
            if not user or not self._is_authorized(user.id, user.username or ""):
                return

            try:
                save_dir = Path("data/artifacts/telegram")
                save_dir.mkdir(parents=True, exist_ok=True)

                if msg.photo:
                    photo = msg.photo[-1]
                    file_path = save_dir / f"photo_{photo.file_id[:8]}.jpg"
                    await bot.download(photo, destination=file_path)
                    caption = msg.caption or "Received photo"
                    await msg.answer(f"📁 Photo saved to artifacts: `{file_path.name}`")
                elif msg.document:
                    doc = msg.document
                    file_path = save_dir / (doc.file_name or f"doc_{doc.file_id[:8]}")
                    await bot.download(doc, destination=file_path)
                    await msg.answer(f"📁 Document saved to artifacts: `{file_path.name}`")

            except Exception as e:
                logger.error(f"[Telegram] Failed saving attachment: {e}")
                await msg.answer(f"⚠️ Failed to save file: {e}")

        @dp.message(F.text)
        async def handle_text(msg: Message) -> None:
            user = msg.from_user
            if not user or not self._is_authorized(user.id, user.username or ""):
                return

            text = (msg.text or "").strip()
            if not text:
                return

            # Check HALT phrases
            if text.lower() in ("archer halt", "halt", "stop"):
                self._bus.publish_halt("telegram")
                await msg.answer("🛑 **HALT triggered.** All active operations and speech stopped.")
                return

            # Normal text turn
            try:
                reply_text = await self._process_orchestrator_request(text)
                # Split if reply is larger than Telegram's 4096 char limit
                for chunk in self._split_text(reply_text, 4000):
                    await msg.answer(chunk)
            except Exception as e:
                logger.error(f"[Telegram] Failed processing text turn: {e}")
                await msg.answer(f"⚠️ Error: {e}")

        # --- Callback Query Handler (Approvals) ---

        @dp.callback_query(F.data.startswith("appr:"))
        async def handle_approval_callback(cq: CallbackQuery) -> None:
            user = cq.from_user
            if not user or not self._is_authorized(user.id, user.username or ""):
                await cq.answer("Unauthorized", show_alert=True)
                return

            # Format: appr:<action>:<req_id>
            parts = (cq.data or "").split(":")
            if len(parts) != 3:
                await cq.answer("Invalid request data")
                return

            _, action, req_id = parts
            decision_map = {
                "approve": "approve",
                "deny": "deny",
                "session": "approve_session",
            }
            decision = decision_map.get(action, "deny")

            success = self._approval_mgr.handle_response(req_id, decision)
            label = {
                "approve": "✓ Approved",
                "deny": "✗ Denied",
                "session": "⚡ Approved for entire session",
            }.get(action, action)

            await cq.answer(f"Action: {label}")

            if cq.message and isinstance(cq.message, types.Message):
                current_text = cq.message.text or ""
                await cq.message.edit_text(
                    f"{current_text}\n\n**Decision:** {label}",
                    reply_markup=None
                )

        # Run polling
        try:
            self._loop.run_until_complete(dp.start_polling(bot))
        except Exception as e:
            if self._running:
                logger.error(f"[Telegram] Polling terminated unexpectedly: {e}")
        finally:
            self._running = False

    async def _process_orchestrator_request(self, text: str) -> str:
        """Route request through orchestrator in a thread pool."""
        from archer.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()

        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, orch.process_request, text)
        return reply or "*(No response generated)*"

    async def _transcribe_audio_bytes(self, audio_bytes: bytes) -> str:
        """Transcribe audio bytes using faster-whisper."""
        loop = asyncio.get_running_loop()

        def _do_transcribe():
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name
            try:
                from faster_whisper import WhisperModel
                cfg = self._config
                model = WhisperModel(cfg.stt_model, device="cuda", compute_type="float16")
                segments, _ = model.transcribe(temp_path, language="en", vad_filter=True)
                return " ".join(s.text.strip() for s in segments)
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

        return await loop.run_in_executor(None, _do_transcribe)

    async def _synthesize_voice_reply(self, text: str) -> Optional[bytes]:
        """Synthesize Kokoro speech audio bytes for a voice note reply."""
        loop = asyncio.get_running_loop()

        def _do_synth():
            try:
                import soundfile as sf
                from archer.voice.tts import get_tts_service
                tts = get_tts_service()
                audio_bytes, sr = tts.synthesize(text)
                if not audio_bytes:
                    return None

                # Convert raw PCM int16 to OGG/WAV for Telegram
                audio_arr = np.frombuffer(audio_bytes, dtype=np.int16)
                out_io = io.BytesIO()
                sf.write(out_io, audio_arr, sr, format="OGG", subtype="VORBIS")
                return out_io.getvalue()
            except Exception as e:
                logger.debug(f"[Telegram] Voice note synthesis omitted: {e}")
                return None

        import numpy as np
        return await loop.run_in_executor(None, _do_synth)

    def _split_text(self, text: str, max_len: int = 4000) -> list[str]:
        """Split text into chunks smaller than max_len."""
        chunks = []
        while len(text) > max_len:
            split_idx = text.rfind("\n", 0, max_len)
            if split_idx == -1:
                split_idx = max_len
            chunks.append(text[:split_idx])
            text = text[split_idx:].lstrip()
        if text:
            chunks.append(text)
        return chunks

    # --- Approval Event Handlers ---

    def _on_approval_requested(self, event: Event) -> None:
        """Send approval card to Col via Telegram with inline buttons."""
        if not self._running or not self._bot or not self._loop or not self._loop.is_running():
            return

        user_id = self._config.telegram_user_id
        if not user_id:
            return

        data = event.data
        req_id = data.get("request_id")
        desc = data.get("description", "Execute action")
        details = data.get("details", "")
        timeout = data.get("timeout_seconds", 30)

        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✓ Approve", callback_data=f"appr:approve:{req_id}"),
                InlineKeyboardButton(text="✗ Deny", callback_data=f"appr:deny:{req_id}"),
            ],
            [
                InlineKeyboardButton(text="⚡ Approve Session", callback_data=f"appr:session:{req_id}"),
            ]
        ])

        msg_text = (
            f"⚠️ **Approval Required**\n\n"
            f"**Action:** {desc}\n"
            f"**Details:** `{details}`\n"
            f"⏱ _Auto-denies in {int(timeout)}s if unanswered._"
        )

        async def _send():
            try:
                sent = await self._bot.send_message(chat_id=user_id, text=msg_text, reply_markup=kb)
                self._pending_msg_ids[req_id] = sent.message_id
            except Exception as e:
                logger.debug(f"[Telegram] Failed sending approval request: {e}")

        asyncio.run_coroutine_threadsafe(_send(), self._loop)

    def _on_approval_resolved(self, event: Event) -> None:
        """Update Telegram approval message when resolved from any surface."""
        if not self._running or not self._bot or not self._loop or not self._loop.is_running():
            return

        req_id = event.data.get("request_id")
        decision = event.data.get("decision", "resolved")
        user_id = self._config.telegram_user_id

        msg_id = self._pending_msg_ids.pop(req_id, None)
        if not msg_id or not user_id:
            return

        label = {
            "approve": "✓ Approved",
            "deny": "✗ Denied",
            "approve_session": "⚡ Approved for session",
            "halt": "🛑 Cancelled (HALT)",
            "timeout": "⏱ Denied (timed out)",
        }.get(decision, decision)

        async def _update():
            try:
                await self._bot.edit_message_reply_markup(
                    chat_id=user_id,
                    message_id=msg_id,
                    reply_markup=None
                )
            except Exception as e:
                logger.debug(f"[Telegram] Failed updating resolved approval message: {e}")

        asyncio.run_coroutine_threadsafe(_update(), self._loop)


_telegram_service: Optional[TelegramLineService] = None


def get_telegram_line() -> TelegramLineService:
    """Get the global TelegramLineService singleton."""
    global _telegram_service
    if _telegram_service is None:
        _telegram_service = TelegramLineService()
    return _telegram_service
