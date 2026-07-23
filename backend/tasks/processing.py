"""Background processing tasks for the Personal AI Assistant.

Uses asyncio directly (no Celery/Redis required).
Called via FastAPI BackgroundTasks or APScheduler.
"""
from __future__ import annotations

import asyncio
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from loguru import logger

from backend.config import settings


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

async def send_daily_digest(orchestrator=None) -> None:
    """Generate and deliver the daily digest of today's processed documents.

    Scheduled by APScheduler at 08:00 Asia/Taipei every day.
    Can also be triggered manually via POST /api/settings/trigger-digest.
    """
    from backend.knowledge.crud import get_documents_created_today
    from backend.knowledge.db import async_session_maker
    from backend.model_router import ModelRouter, AllProvidersFailedError

    logger.info("Daily digest starting…")

    async with async_session_maker() as session:
        docs = await get_documents_created_today(session)

    if not docs:
        logger.info("Daily digest: no documents found for today, skipping.")
        return

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    doc_lines: list[str] = []
    for i, doc in enumerate(docs, start=1):
        title = doc.title or f"Document {i}"
        summary = doc.summary or "(no summary)"
        doc_lines.append(f"{i}. [{doc.source_type}] {title}\n   {summary}")

    prompt = (
        f"Today is {today_str}. Here are summaries of all content captured today:\n\n"
        + "\n\n".join(doc_lines)
        + "\n\nWrite a concise daily digest (3-5 paragraphs) highlighting key themes, "
          "action items, and grouping related content."
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
    logger.info("Daily digest sent ({} docs).", len(docs))


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

async def _send_telegram(text: str) -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured; skipping notification.")
        return
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text[:4096],
                "parse_mode": "Markdown",
            })
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Telegram send failed: {}", exc)


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
    try:
        with smtplib.SMTP(settings.EMAIL_SMTP_HOST, settings.EMAIL_SMTP_PORT) as s:
            s.ehlo()
            s.starttls()
            s.login(settings.EMAIL_USER, settings.EMAIL_PASSWORD)
            s.sendmail(settings.EMAIL_USER, settings.EMAIL_RECIPIENT, msg.as_string())
        logger.info("Email sent: {}", msg["Subject"])
    except smtplib.SMTPException as exc:
        logger.error("SMTP error: {}", exc)
