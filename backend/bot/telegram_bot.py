"""Telegram bot front-end for the Personal AI Assistant.

Uses python-telegram-bot with long polling (no webhook, no public IP needed).
Delegates all processing to the Orchestrator.

Runs on the *same* asyncio event loop as FastAPI (started/stopped from the
lifespan via ``await bot.start()`` / ``await bot.stop()``) rather than in its
own thread. The Orchestrator's DB session maker is bound to whichever event
loop first opens a connection; polling from a second thread-local loop caused
asyncpg futures to be awaited on the wrong loop ("Future ... attached to a
different loop").

Public interface expected by the rest of the system
---------------------------------------------------
- PersonalAssistantBot(token, orchestrator)
- await bot.start()
- await bot.stop()
- await bot.send_message(text, parse_mode)
- await bot.send_confirmation_request(doc_id, candidates, update)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend.config import settings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _uploads_dir() -> Path:
    """Return the uploads directory, creating it if necessary."""
    path: Path = settings.UPLOADS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

_AUDIO_MIME_SUFFIX: dict[str, str] = {
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/amr": ".amr",
}


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class PersonalAssistantBot:
    """Telegram Bot for the Personal AI Assistant.

    Attributes
    ----------
    token       : The bot token string.
    orchestrator: The Orchestrator instance used for routing and processing.
    app         : The underlying python-telegram-bot Application.
    """

    def __init__(self, token: str, orchestrator: Any) -> None:
        self.token: str = token
        self.orchestrator: Any = orchestrator
        self.app: Application = ApplicationBuilder().token(token).build()

        # Populated from the first inbound message; used by send_message().
        self._default_chat_id: int | None = None

        self._register_handlers()
        logger.info("PersonalAssistantBot initialised.")

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        add = self.app.add_handler

        # Commands
        add(CommandHandler("start", self.handle_start))
        add(CommandHandler("status", self.handle_status))

        # Specific media types — registered before the broad TEXT filter.
        add(MessageHandler(filters.PHOTO, self.handle_photo))
        add(MessageHandler(filters.Document.ALL, self.handle_document))
        add(MessageHandler(filters.AUDIO | filters.VOICE, self.handle_audio))
        add(MessageHandler(filters.VIDEO, self.handle_video))

        # Text (excludes commands so /start etc. are not double-handled).
        add(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        # Inline keyboard presses.
        add(CallbackQueryHandler(self.handle_callback))

        logger.debug("All handlers registered.")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        self._cache_chat_id(update)
        welcome = (
            "*Personal AI Assistant 已就緒！* 👋\n\n"
            "你可以傳給我：\n"
            "• 📝 文字 — 快速筆記或問題\n"
            "• 🔗 URL — 自動網頁剪輯\n"
            "• 📷 截圖 / 圖片 — 螢幕截圖分析\n"
            "• 📄 文件 (PDF, DOCX…) — 文件摘要\n"
            "• 🎤 語音 / 錄音 — 會議轉錄\n"
            "• 🎬 影片 — 語音轉錄摘要\n\n"
            "使用 /status 查看目前狀態。"
        )
        await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)

    async def handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        self._cache_chat_id(update)
        pending_count = len(getattr(self.orchestrator, "_pending", {}))
        text = (
            "*系統狀態*\n\n"
            f"⏳ 等待確認的任務：{pending_count}\n"
            "🤖 Bot 運作中 ✅"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    # ------------------------------------------------------------------
    # Media handlers
    # ------------------------------------------------------------------

    async def handle_photo(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Receive the highest-resolution photo and route to screenshot-agent."""
        self._cache_chat_id(update)
        await update.message.reply_text("📷 截圖已收到，正在分析...")

        try:
            # Telegram provides multiple sizes; the last element is the largest.
            photo = update.message.photo[-1]
            file_path = await self._download_file(
                context, photo.file_id, suffix=".jpg"
            )
            logger.info("Photo saved → {}", file_path)

            result = await self.orchestrator.process_input("image", str(file_path))
            await self._dispatch_result(update, result, prefix="📷 ")

        except Exception as exc:
            logger.exception("handle_photo error: {}", exc)
            await update.message.reply_text(f"❌ 處理圖片時發生錯誤：{exc}")

    async def handle_document(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Receive a document. Routes to document-agent, unless the file
        extension is a video container sent "as a file" — then meeting-agent
        transcribes it, same as a native video message."""
        self._cache_chat_id(update)
        tg_doc = update.message.document
        file_name: str = tg_doc.file_name or "document"
        suffix = Path(file_name).suffix or ".bin"
        is_video = suffix.lower() in _VIDEO_EXTENSIONS

        if is_video:
            await update.message.reply_text(f"🎬 影片《{file_name}》已收到，正在轉錄（可能需要幾分鐘）...")
        else:
            await update.message.reply_text(f"📄 文件《{file_name}》已收到，正在處理...")

        try:
            stem = Path(file_name).stem
            file_path = await self._download_file(
                context, tg_doc.file_id, suffix=suffix, stem=stem
            )
            logger.info("Document saved → {}", file_path)

            input_type = "video" if is_video else "file"
            result = await self.orchestrator.process_input(input_type, str(file_path))
            await self._dispatch_result(update, result, prefix="🎬 " if is_video else "📄 ")

        except Exception as exc:
            logger.exception("handle_document error: {}", exc)
            kind = "影片" if is_video else "文件"
            await update.message.reply_text(f"❌ 處理{kind}時發生錯誤：{exc}")

    async def handle_video(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Receive a native video message and route to meeting-agent for transcription."""
        self._cache_chat_id(update)
        tg_video = update.message.video
        file_name: str = tg_video.file_name or "video.mp4"
        await update.message.reply_text(f"🎬 影片《{file_name}》已收到，正在轉錄（可能需要幾分鐘）...")

        try:
            suffix = Path(file_name).suffix or ".mp4"
            file_path = await self._download_file(context, tg_video.file_id, suffix=suffix)
            logger.info("Video saved → {}", file_path)

            result = await self.orchestrator.process_input("video", str(file_path))
            await self._dispatch_result(update, result, prefix="🎬 ")

        except Exception as exc:
            logger.exception("handle_video error: {}", exc)
            await update.message.reply_text(f"❌ 處理影片時發生錯誤：{exc}")

    async def handle_audio(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Receive audio or voice message and route to meeting-agent."""
        self._cache_chat_id(update)
        await update.message.reply_text("🎤 音訊已收到，正在轉錄（可能需要幾分鐘）...")

        try:
            if update.message.voice:
                tg_file = update.message.voice
                suffix = ".ogg"
            else:
                tg_file = update.message.audio
                mime = getattr(tg_file, "mime_type", "") or ""
                suffix = _AUDIO_MIME_SUFFIX.get(mime.lower(), ".mp3")

            file_path = await self._download_file(
                context, tg_file.file_id, suffix=suffix
            )
            logger.info("Audio saved → {}", file_path)

            result = await self.orchestrator.process_input("audio", str(file_path))
            await self._dispatch_result(update, result, prefix="🎤 ")

        except Exception as exc:
            logger.exception("handle_audio error: {}", exc)
            await update.message.reply_text(f"❌ 處理音訊時發生錯誤：{exc}")

    # ------------------------------------------------------------------
    # Text handler
    # ------------------------------------------------------------------

    _TODO_INTENT_PATTERN = re.compile(r"代辦|待辦|todo|to-do|action[\s-]?items?", re.IGNORECASE)

    async def handle_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Route plain text to the appropriate input type.

        Decision logic
        --------------
        - Starts with http:// or https:// → webclip-agent via input_type="url"
        - Looks like a todo/action-item query (e.g. "今天有沒有代辦事項") → answered
          directly from the action-items aggregate, not saved as a note.
        - Everything else (short notes, questions, long text) → input_type="text"
          and let the orchestrator's LLM routing decide the agent.
        """
        self._cache_chat_id(update)
        text: str = update.message.text.strip()

        try:
            if text.startswith("http://") or text.startswith("https://"):
                await update.message.reply_text("🔗 連結已收到，正在處理...")
                logger.info("Text classified as URL: {:.80}", text)
                result = await self.orchestrator.process_input("url", text)
                prefix = "🔗 "
                await self._dispatch_result(update, result, prefix=prefix)
                return

            if self._TODO_INTENT_PATTERN.search(text):
                logger.info("Text classified as todo-intent query: {:.60}", text)
                items = await self.orchestrator.get_action_items()
                await update.message.reply_text(self._format_action_items(items))
                return

            await update.message.reply_text("📝 訊息已收到，正在處理...")
            logger.info(
                "Text classified as note/query (len={}): {:.60}", len(text), text
            )
            result = await self.orchestrator.process_input("text", text)
            await self._dispatch_result(update, result, prefix="✅ 收到！")

        except Exception as exc:
            logger.exception("handle_text error: {}", exc)
            await update.message.reply_text(f"❌ 處理文字時發生錯誤：{exc}")

    # ------------------------------------------------------------------
    # Inline keyboard callback
    # ------------------------------------------------------------------

    async def handle_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline button presses.

        Two independent callback_data formats share this handler:
          - ``confirm:{doc_id}:{agent_name}``   — agent-routing confirmation
          - ``project:{doc_id}:{project_name}`` — project-assignment confirmation
            (``project_name`` may be the sentinel ``__skip__`` for "不歸類")
        """
        query = update.callback_query
        await query.answer()

        data: str = query.data or ""
        parts = data.split(":", 2)

        if len(parts) != 3 or parts[0] not in ("confirm", "project"):
            logger.warning("Unrecognised callback_data: {!r}", data)
            await query.edit_message_text("❓ 無效的操作。")
            return

        kind, doc_id, payload = parts

        if kind == "confirm":
            logger.info("User confirmed routing: doc_id={} agent={}", doc_id, payload)
            try:
                result = await self.orchestrator.confirm_routing(doc_id, payload)
                if result.get("status") == "completed":
                    text = self._format_completed(result, prefix="✅ ")
                else:
                    text = f"❌ {result.get('message', '完成！')}"
                await query.edit_message_text(text)
            except Exception as exc:
                logger.exception("handle_callback (confirm) error: {}", exc)
                await query.edit_message_text(f"❌ 確認時發生錯誤：{exc}")
            return

        # kind == "project"
        project_name = None if payload == "__skip__" else payload
        logger.info("User responded to project confirmation: doc_id={} project={}", doc_id, project_name)
        try:
            result = await self.orchestrator.confirm_project(doc_id, project_name)
            icon = "✅" if result.get("status") == "completed" else "❌"
            await query.edit_message_text(f"{icon} {result.get('message', '完成！')}")
        except Exception as exc:
            logger.exception("handle_callback (project) error: {}", exc)
            await query.edit_message_text(f"❌ 確認時發生錯誤：{exc}")

    # ------------------------------------------------------------------
    # Outbound / proactive helpers
    # ------------------------------------------------------------------

    async def send_message(
        self,
        text: str,
        parse_mode: str = ParseMode.MARKDOWN,
    ) -> None:
        """Push a message to the default chat.

        Intended for use by the daily digest scheduler and other background tasks.
        Requires that at least one inbound message has been received first so that
        ``_default_chat_id`` is set, OR that ``settings.TELEGRAM_CHAT_ID`` is
        configured as a fallback.
        """
        chat_id = self._default_chat_id or getattr(settings, "TELEGRAM_CHAT_ID", None)
        if not chat_id:
            logger.warning(
                "send_message() called but no chat_id is known yet "
                "(set TELEGRAM_CHAT_ID in settings or send a /start message first)."
            )
            return
        await self.app.bot.send_message(
            chat_id=chat_id,
            text=text[:4096],
            parse_mode=parse_mode,
        )

    async def send_confirmation_request(
        self,
        doc_id: str,
        candidates: list[dict],
        update: Update,
    ) -> None:
        """Send an inline keyboard so the user can choose an agent.

        Parameters
        ----------
        doc_id     : Document ID produced by the orchestrator.
        candidates : List of dicts with keys ``name`` (str) and ``confidence``
                     (float 0–1).  At least one entry is expected.
        update     : The inbound Update to reply to.
        """
        buttons = [
            InlineKeyboardButton(
                text=(
                    f"{c['name']} ({c['confidence']:.0%})"
                    if c.get("confidence", 0) > 0
                    else c["name"]
                ),
                callback_data=f"confirm:{doc_id}:{c['name']}",
            )
            for c in candidates
        ]
        # One button per row keeps labels readable on mobile.
        keyboard = InlineKeyboardMarkup([[btn] for btn in buttons])
        await update.message.reply_text(
            "🤔 請選擇處理方式：",
            reply_markup=keyboard,
        )

    async def send_project_confirmation_request(
        self,
        doc_id: str,
        project_name: str,
        confidence: float,
        update: Update,
    ) -> None:
        """Ask the user to confirm a medium-confidence project assignment.

        Mirrors :meth:`send_confirmation_request` but for project linking
        instead of agent routing — SDD §7 requires this confirmation step
        when project-classification confidence isn't high enough to auto-link.
        """
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"✅ 加入「{project_name}」",
                callback_data=f"project:{doc_id}:{project_name}",
            )],
            [InlineKeyboardButton("❌ 不歸類", callback_data=f"project:{doc_id}:__skip__")],
        ])
        await update.message.reply_text(
            f"🗂️ 這份內容可能屬於專案「{project_name}」（信心度 {confidence:.0%}），要加入嗎？",
            reply_markup=keyboard,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start long polling on the caller's event loop (non-blocking)."""
        logger.info("Telegram bot starting long polling…")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        """Stop polling and release the underlying Application's resources."""
        logger.info("Telegram bot stopping…")
        if self.app.updater is not None and self.app.updater.running:
            await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    # ------------------------------------------------------------------
    # Private utilities
    # ------------------------------------------------------------------

    async def _download_file(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        file_id: str,
        suffix: str = ".bin",
        stem: str | None = None,
    ) -> Path:
        """Download a Telegram file to UPLOADS_DIR and return its Path.

        Uses the first 8 characters of the file_id as a uniqueness prefix so
        that multiple files with the same original name don't clobber each other.
        """
        uploads = _uploads_dir()
        tg_file = await context.bot.get_file(file_id)

        safe_prefix = file_id[:8]
        filename = f"{safe_prefix}_{stem}{suffix}" if stem else f"{safe_prefix}{suffix}"
        dest = uploads / filename

        await tg_file.download_to_drive(str(dest))
        return dest

    async def _dispatch_result(
        self,
        update: Update,
        result: dict,
        prefix: str = "✅ 收到！",
    ) -> None:
        """Translate an orchestrator result dict into one or more Telegram messages.

        Status mapping
        --------------
        completed            → simple confirmation reply.
        pending_confirmation → brief explanation + inline keyboard.
        failed               → error notice.
        """
        status = result.get("status", "unknown")
        message = result.get("message", "正在處理中...")

        if status == "completed":
            await update.message.reply_text(self._format_completed(result, prefix))
            pending_project = result.get("pending_project")
            if pending_project:
                await self.send_project_confirmation_request(
                    result.get("doc_id", ""),
                    pending_project["project_name"],
                    float(pending_project.get("confidence", 0.0)),
                    update,
                )

        elif status == "pending_confirmation":
            doc_id: str = result.get("doc_id", "")
            agent_name: str | None = result.get("agent_name")
            available: list[str] = result.get("available_agents", [])

            await update.message.reply_text(f"🤔 {message}")

            if doc_id:
                if agent_name:
                    confidence = float(result.get("confidence", 0.0))
                    candidates = [{"name": agent_name, "confidence": confidence}]
                else:
                    candidates = [{"name": n, "confidence": 0.0} for n in available]

                if candidates:
                    await self.send_confirmation_request(doc_id, candidates, update)

        elif status == "failed":
            await update.message.reply_text(f"❌ {message}")

        else:
            await update.message.reply_text(f"⚠️ {message or '發生未知錯誤，請稍後再試。'}")

    @staticmethod
    def _format_completed(result: dict, prefix: str) -> str:
        """Build a reply that shows the agent's actual title/summary/tags.

        Falls back to the generic ``message`` string if the orchestrator
        didn't return any structured fields (e.g. an older caller).
        """
        title = result.get("title")
        summary = result.get("summary")
        category = result.get("category")
        tags = result.get("tags") or []

        if not title and not summary:
            return f"{prefix}{result.get('message', '已儲存至知識庫')}"

        lines = ["✅ 已儲存至知識庫"]
        if title:
            lines.append(f"📌 {title}")
        if category:
            lines.append(f"🏷️ 分類：{category}")
        if summary:
            snippet = summary if len(summary) <= 300 else summary[:300] + "…"
            lines.append(f"📝 {snippet}")
        if tags:
            lines.append("🔖 " + "、".join(str(t) for t in tags))
        return "\n".join(lines)

    @staticmethod
    def _format_action_items(items: list[dict]) -> str:
        """Build a reply listing aggregated meeting action items.

        There is no "done" flag in the data model, so this always lists
        everything ever extracted — same caveat as the REST endpoint.
        """
        if not items:
            return "📋 目前沒有偵測到任何代辦事項（尚無會議紀錄含 action items）。"

        items = sorted(items, key=lambda i: i.get("due_date") or "9999-99-99")

        lines = [f"📋 代辦事項（共 {len(items)} 筆）："]
        for item in items[:20]:
            line = f"• {item['task']}"
            if item.get("due_date"):
                line += f"（📅 {item['due_date']}）"
            if item.get("owner"):
                line += f" @{item['owner']}"
            if item.get("source_title"):
                line += f"\n  來自：{item['source_title']}"
            lines.append(line)
        if len(items) > 20:
            lines.append(f"...還有 {len(items) - 20} 筆，未列出")
        return "\n".join(lines)

    def _cache_chat_id(self, update: Update) -> None:
        """Record the chat_id of the first inbound message as the default outbound target."""
        if self._default_chat_id is None and update.effective_chat:
            self._default_chat_id = update.effective_chat.id
            logger.debug("Default chat_id cached: {}", self._default_chat_id)
