"""Regression test for Tier-2 item: pending todos with no due_date, or
overdue, never surfaced anywhere except a direct /todo list query — folded
into the daily digest now via _build_todo_reminder_section so they don't
silently age out of sight.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from backend.knowledge.db import async_session_maker
from backend.knowledge.models import Todo
from backend.tasks import processing

_TODAY = date(2026, 10, 2)


async def _make_todo(content: str, due_date: date | None, status: str = "pending") -> uuid.UUID:
    todo_id = uuid.uuid4()
    async with async_session_maker() as session:
        session.add(
            Todo(id=todo_id, content=content, source="dashboard", status=status, due_date=due_date)
        )
        await session.commit()
    return todo_id


async def _cleanup(todo_ids: list[uuid.UUID]) -> None:
    async with async_session_maker() as session:
        for todo_id in todo_ids:
            todo = await session.get(Todo, todo_id)
            if todo is not None:
                await session.delete(todo)
        await session.commit()


@pytest.mark.asyncio
async def test_todo_section_includes_overdue_and_no_due_date_excludes_others():
    ids = []
    try:
        ids.append(await _make_todo("overdue task", due_date=_TODAY - timedelta(days=3)))
        ids.append(await _make_todo("no due date task", due_date=None))
        ids.append(await _make_todo("future task", due_date=_TODAY + timedelta(days=3)))
        ids.append(await _make_todo("done overdue task", due_date=_TODAY - timedelta(days=1), status="done"))

        async with async_session_maker() as session:
            section = await processing._build_todo_reminder_section(session, _TODAY)

        assert section is not None
        assert "overdue task" in section
        assert "no due date task" in section
        assert "future task" not in section
        assert "done overdue task" not in section
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
async def test_todo_section_excludes_a_future_dated_task():
    # This runs against the real dev DB, which may already have other
    # pending no-due-date/overdue todos — so don't assert the section is
    # None overall, just that this specific future-dated task never shows.
    ids = []
    try:
        ids.append(await _make_todo("a distinctly-named future-only task xyz123", due_date=_TODAY + timedelta(days=1)))

        async with async_session_maker() as session:
            section = await processing._build_todo_reminder_section(session, _TODAY)

        assert section is None or "a distinctly-named future-only task xyz123" not in section
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
async def test_no_docs_digest_still_reports_overdue_todos(monkeypatch, tmp_path):
    monkeypatch.setattr(processing.settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(processing.settings, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(processing.settings, "EMAIL_USER", "")
    monkeypatch.setattr(processing.settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(processing, "_today_taipei", lambda: _TODAY)

    sent_texts = []

    async def _fake_post(self, url, json):
        sent_texts.append(json["text"])
        resp = Mock()
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    # In case the dev DB's documents table happens to have real docs for
    # today (live app data), avoid an actual LLM call for the digest-text
    # generation path.
    from backend.model_router import ModelRouter

    monkeypatch.setattr(ModelRouter, "chat", AsyncMock(return_value="(test digest text)"))

    ids = [await _make_todo("overdue task", due_date=_TODAY - timedelta(days=5))]
    try:
        # Don't assume result == 0 — this hits the real dev DB's documents
        # table, which could legitimately have today's docs from the live
        # app. Either branch (no-docs or with-docs) must still carry the
        # overdue todo.
        await processing.send_daily_digest(force=True)
        assert any("overdue task" in t for t in sent_texts), (
            "an overdue todo must appear in the digest even on a no-new-docs day"
        )
    finally:
        await _cleanup(ids)
