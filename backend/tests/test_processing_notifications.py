"""Regression tests for Tier-1 bug #2: a failed Telegram send was silently
swallowed, but callers still recorded the notification as sent (todo
reminders marked `sent=True`, the daily digest marker written) — so a
transient Telegram/network failure meant that reminder or digest was lost
forever instead of being retried.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from backend.knowledge.db import async_session_maker
from backend.knowledge.models import Todo, TodoReminder
from backend.tasks import processing


def _mock_telegram_response(*, fails: bool):
    """Patch httpx.AsyncClient.post used inside _send_telegram."""
    mock_resp = Mock()
    if fails:
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=httpx.Request("POST", "https://example.invalid"), response=httpx.Response(400)
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(return_value=mock_resp),
    )


@pytest.mark.asyncio
async def test_send_telegram_returns_false_on_http_failure(monkeypatch):
    monkeypatch.setattr(processing.settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(processing.settings, "TELEGRAM_CHAT_ID", "123")

    with _mock_telegram_response(fails=True):
        ok = await processing._send_telegram("hello")
    assert ok is False


@pytest.mark.asyncio
async def test_send_telegram_returns_true_on_success(monkeypatch):
    monkeypatch.setattr(processing.settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(processing.settings, "TELEGRAM_CHAT_ID", "123")

    with _mock_telegram_response(fails=False):
        ok = await processing._send_telegram("hello")
    assert ok is True


@pytest.mark.asyncio
async def test_failed_reminder_send_is_not_marked_sent(monkeypatch):
    monkeypatch.setattr(processing.settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(processing.settings, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(processing.settings, "TELEGRAM_TODO_CHAT_ID", None)

    todo_id = uuid.uuid4()
    reminder_id = uuid.uuid4()

    # send_todo_reminder opens its own session internally, so the fixture
    # rows must actually be committed — otherwise that session can't see
    # them ("reminder not found") and the test would pass for the wrong
    # reason without ever exercising the failure path.
    async with async_session_maker() as session:
        session.add(
            Todo(id=todo_id, content="test todo", source="dashboard", status="pending")
        )
        session.add(
            TodoReminder(
                id=reminder_id,
                todo_id=todo_id,
                remind_at=datetime.now(timezone.utc),
                label="due",
                sent=False,
            )
        )
        await session.commit()

    try:
        with _mock_telegram_response(fails=True):
            await processing.send_todo_reminder(str(reminder_id))

        async with async_session_maker() as session:
            refreshed = await session.get(TodoReminder, reminder_id)
            assert refreshed is not None
            assert refreshed.sent is False, (
                "a reminder whose Telegram send failed must stay unsent so "
                "the restart catch-up (list_pending_todo_reminders) retries it"
            )
    finally:
        async with async_session_maker() as session:
            todo = await session.get(Todo, todo_id)
            if todo is not None:
                await session.delete(todo)
                await session.commit()


@pytest.mark.asyncio
async def test_failed_digest_send_does_not_write_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(processing.settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(processing.settings, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(processing.settings, "EMAIL_USER", "")
    monkeypatch.setattr(processing.settings, "BASE_DIR", tmp_path)

    with _mock_telegram_response(fails=True):
        result = await processing.send_daily_digest(force=True)

    assert result == 0  # no-docs path still reports 0, but...
    assert processing.get_last_digest_date() is None, (
        "digest marker must not be written when the Telegram send failed, "
        "otherwise it's silently never retried"
    )
