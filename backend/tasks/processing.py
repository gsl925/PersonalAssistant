"""Background processing tasks for the Personal AI Assistant.

Uses asyncio directly (no Celery/Redis required).
Called via FastAPI BackgroundTasks or APScheduler.
"""
from __future__ import annotations

import asyncio
import json
import smtplib
import uuid
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from backend.config import settings

_TAIPEI = ZoneInfo("Asia/Taipei")


def _today_taipei() -> date:
    return datetime.now(_TAIPEI).date()


def _last_digest_marker_path() -> Path:
    return settings.BASE_DIR / "data" / "last_digest_date.txt"


def get_last_digest_date() -> date | None:
    """Date the digest last actually ran (sent or a no-docs no-op), or None
    if it has never run. Persisted to a plain file — this only needs to
    survive process restarts, not warrant a DB table."""
    path = _last_digest_marker_path()
    if not path.exists():
        return None
    try:
        return date.fromisoformat(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _write_last_digest_date(d: date) -> None:
    path = _last_digest_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(d.isoformat(), encoding="utf-8")


def get_digest_status() -> dict:
    """Surface digest catch-up state for the dashboard Settings page."""
    today = _today_taipei()
    last_sent = get_last_digest_date()
    return {
        "last_sent_date": last_sent.isoformat() if last_sent else None,
        "today": today.isoformat(),
        "sent_today": last_sent == today,
    }


# ---------------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------------

async def process_content_async(
    doc_id: str,
    source_type: str,
    input_data: dict,
    orchestrator=None,
) -> None:
    """Full async processing pipeline for a single document.

    Called by FastAPI BackgroundTasks after the HTTP response is sent.
    *orchestrator* is the app-level singleton passed from main.py.
    """
    from backend.knowledge.crud import update_document_status
    from backend.knowledge.db import async_session_maker

    doc_uuid = uuid.UUID(doc_id)

    try:
        if orchestrator is None:
            from backend.main import get_orchestrator
            orchestrator = get_orchestrator()

        # The orchestrator already saved the stub; just re-run through agent pipeline
        # by calling _execute_and_save directly if we have processed content.
        # For background re-processing, mark as processing first.
        async with async_session_maker() as session:
            await update_document_status(session, doc_uuid, "processing")
            await session.commit()

        logger.info("Background processing started for doc={}", doc_id)

    except Exception as exc:
        logger.exception("Background processing failed for doc={}: {}", doc_id, exc)
        try:
            async with async_session_maker() as session:
                await update_document_status(session, doc_uuid, "failed")
                await session.commit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------

async def send_daily_digest(orchestrator=None, *, force: bool = False) -> int | None:
    """Generate and deliver the daily digest of today's processed documents.

    Scheduled by APScheduler at 08:00 Asia/Taipei every day, AND run once on
    every app startup (see scheduler.py::start_scheduler) — the pure-cron
    trigger only fires if the process happens to be alive at that exact
    moment, which doesn't suit a machine that isn't always on at 8am. The
    per-day marker guard below (skipped when *force* is set) is what makes
    calling this from both places safe — whichever fires first for a given
    day wins, the other becomes a no-op instead of a duplicate send.
    Also triggerable manually via POST /api/settings/trigger-digest, which
    passes force=True so a manual click always actually runs.

    Returns the number of documents included, or None if skipped because
    today's digest was already sent (only possible when force=False).
    """
    from backend.knowledge.crud import get_documents_created_today
    from backend.knowledge.db import async_session_maker
    from backend.model_router import ModelRouter, AllProvidersFailedError

    today = _today_taipei()
    if not force and get_last_digest_date() == today:
        logger.info("Daily digest already handled today ({}); skipping.", today)
        return None

    logger.info("Daily digest starting…")

    async with async_session_maker() as session:
        docs = await get_documents_created_today(session)

    if not docs:
        logger.info("Daily digest: no documents found for today.")
        # Still send a short heads-up (Telegram only, no email) — silence is
        # indistinguishable from "the system is broken" otherwise.
        await _send_telegram(f"*Daily Digest — {today.isoformat()}*\n\n今天沒有新內容。")
        _write_last_digest_date(today)
        return 0

    today_str = today.isoformat()
    doc_lines: list[str] = []
    for i, doc in enumerate(docs, start=1):
        title = doc.title or f"Document {i}"
        summary = doc.summary or "(no summary)"
        doc_lines.append(f"{i}. [{doc.source_type}] {title}\n   {summary}")

    prompt = (
        f"Today is {today_str}. Here are summaries of all content captured today:\n\n"
        + "\n\n".join(doc_lines)
        + "\n\nWrite a concise daily digest (3-5 paragraphs) highlighting key themes, "
          "action items, and grouping related content. "
          "請全部使用繁體中文撰寫，不要使用簡體中文或英文。"
    )

    model_router = ModelRouter()
    try:
        digest_text = await model_router.chat(
            "complex_reasoning",
            [{"role": "user", "content": prompt}],
        )
    except AllProvidersFailedError as exc:
        logger.error("Daily digest LLM failed: {}", exc)
        digest_text = f"[Daily digest generation failed: {exc}]\n\n" + "\n".join(doc_lines)

    await _send_telegram(f"*Daily Digest — {today_str}*\n\n{digest_text}")
    await _send_email(
        subject=f"Personal AI Assistant — Daily Digest {today_str}",
        body=digest_text,
    )
    _write_last_digest_date(today)
    logger.info("Daily digest sent ({} docs).", len(docs))
    return len(docs)


# ---------------------------------------------------------------------------
# Todo reminders
# ---------------------------------------------------------------------------

_TODO_REMINDER_LABELS = {
    "start": "🔔 開始提醒",
    "midpoint": "📍 期間提醒",
    "due": "⏰ 截止前提醒",
}


async def send_todo_reminder(reminder_id: str) -> None:
    """Push a single TodoReminder (start/midpoint/due). Scheduled one-off by
    APScheduler (see backend/tasks/scheduler.py::schedule_todo_reminder) —
    a todo with multiple reminders gets one job per reminder, not per todo."""
    from backend.knowledge import crud
    from backend.knowledge.db import async_session_maker

    reminder_uuid = uuid.UUID(reminder_id)
    async with async_session_maker() as db:
        reminder = await crud.get_todo_reminder(db, reminder_uuid)
        if reminder is None:
            logger.warning("send_todo_reminder: reminder {} not found.", reminder_id)
            return

        todo = await crud.get_todo(db, reminder.todo_id)
        if todo is None or todo.status != "pending":
            status = todo.status if todo else "missing"
            logger.info("send_todo_reminder: todo for {} is '{}', skipping.", reminder_id, status)
            return

        label = _TODO_REMINDER_LABELS.get(reminder.label, "⏰ 提醒")
        due_suffix = f"（截止 {todo.due_date.isoformat()}）" if todo.due_date else ""
        url_suffix = f"\n{todo.source_url}" if todo.source_url else ""
        todo_chat_id = settings.TELEGRAM_TODO_CHAT_ID or settings.TELEGRAM_CHAT_ID
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ 完成", "callback_data": f"remind:{reminder_id}:done"},
                {"text": "😴 明天再提醒", "callback_data": f"remind:{reminder_id}:snooze"},
            ]]
        }
        await _send_telegram(
            f"{label}：{todo.content}{due_suffix}{url_suffix}",
            chat_id=todo_chat_id,
            reply_markup=keyboard,
        )

        await crud.mark_todo_reminder_sent(db, reminder_uuid)
        await db.commit()
    logger.info("Todo reminder sent for {} (label={}).", reminder_id, reminder.label)


_RECURRENCE_FREQUENCY_LABELS = {"daily": "每天", "weekly": "每週", "monthly": "每月"}


async def send_recurring_todo_reminder(todo_id: str) -> None:
    """Fires every time a recurring todo's CronTrigger goes off (see
    backend/tasks/scheduler.py::schedule_recurring_todo). Unlike
    send_todo_reminder, there's no TodoReminder row per fire — this is an
    infinitely-repeating job keyed by the todo itself, so there's nothing to
    mark "sent". Guard only checks "cancelled", not "done" — completing a
    recurring todo does not stop future reminders, by design.
    """
    from backend.knowledge import crud
    from backend.knowledge.db import async_session_maker

    todo_uuid = uuid.UUID(todo_id)
    async with async_session_maker() as db:
        todo = await crud.get_todo(db, todo_uuid)
        if todo is None or todo.status == "cancelled":
            status = todo.status if todo else "missing"
            logger.info("send_recurring_todo_reminder: todo {} is '{}', skipping.", todo_id, status)
            return

        label = _RECURRENCE_FREQUENCY_LABELS.get(todo.recurrence_frequency, "🔁")
        todo_chat_id = settings.TELEGRAM_TODO_CHAT_ID or settings.TELEGRAM_CHAT_ID
        keyboard = {
            "inline_keyboard": [[
                {"text": "🚫 停止提醒", "callback_data": f"remind:{todo_id}:stop_recurring"},
            ]]
        }
        await _send_telegram(
            f"🔁 週期提醒（{label}）：{todo.content}",
            chat_id=todo_chat_id,
            reply_markup=keyboard,
        )
    logger.info("Recurring todo reminder sent for {}.", todo_id)


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

async def _send_telegram(
    text: str,
    chat_id: str | None = None,
    reply_markup: dict | None = None,
    parse_mode: str | None = "Markdown",
) -> None:
    """Push *text* to *chat_id*, defaulting to TELEGRAM_CHAT_ID (the daily
    digest's destination) when not given explicitly.

    *reply_markup* (e.g. an inline keyboard) works the same in channels as
    in regular chats — any viewer can tap it, no special permission needed;
    Telegram routes the resulting callback_query to this same bot regardless
    of which code path sent the original message (raw httpx here, not the
    python-telegram-bot Application), so handle_callback() still sees it.

    *parse_mode* defaults to Markdown for callers with controlled, hand-
    written text (e.g. the daily digest). Pass ``None`` when *text* embeds
    arbitrary/untrusted content (e.g. another project's raw PROGRESS.md
    text) — unbalanced `_`/`*`/backticks in that content would otherwise
    make Telegram reject the whole message as an entity-parse error.
    """
    target = chat_id or settings.TELEGRAM_CHAT_ID
    if not settings.TELEGRAM_BOT_TOKEN or not target:
        logger.warning("Telegram not configured; skipping notification.")
        return
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target,
        "text": text[:4096],
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Telegram send failed: {} | text preview: {!r}", exc, text[:200])


async def _send_email(subject: str, body: str) -> None:
    if not settings.EMAIL_USER or not settings.EMAIL_RECIPIENT:
        logger.warning("Email not configured; skipping.")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_USER
    msg["To"] = settings.EMAIL_RECIPIENT
    msg.attach(MIMEText(body, "plain", "utf-8"))

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _smtp_send, msg)


def _smtp_send(msg: MIMEMultipart) -> None:
    # Without an explicit timeout, a blocked/filtered outbound port (common on
    # corporate networks) hangs this call — and its OS-level thread — forever,
    # since a cancelled asyncio.wait_for() around run_in_executor() does not
    # actually interrupt the underlying blocking socket call.
    try:
        with smtplib.SMTP(settings.EMAIL_SMTP_HOST, settings.EMAIL_SMTP_PORT, timeout=20) as s:
            s.ehlo()
            s.starttls()
            s.login(settings.EMAIL_USER, settings.EMAIL_PASSWORD)
            s.sendmail(settings.EMAIL_USER, settings.EMAIL_RECIPIENT, msg.as_string())
        logger.info("Email sent: {}", msg["Subject"])
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("SMTP error: {}", exc)
