"""Regression test for Tier-3 fix: the dashboard's "問答記錄" (ChatView) page
used to be a read-only archive of Telegram /ask history with no way to
start a new question from the dashboard itself. Added /api/chat/ask,
wrapping the same Orchestrator.ask_claude() call /ask uses.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.chat import AskRequest, ask


@pytest.mark.asyncio
async def test_ask_rejects_empty_question():
    orchestrator = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await ask(AskRequest(question="   "), orchestrator)
    assert exc_info.value.status_code == 422
    orchestrator.ask_claude.assert_not_called()


@pytest.mark.asyncio
async def test_ask_returns_completed_result():
    orchestrator = AsyncMock()
    orchestrator.ask_claude.return_value = {
        "status": "completed",
        "doc_id": "abc-123",
        "message": "已回答並存入知識庫",
        "title": "測試問題",
        "summary": "測試答案",
        "category": "chat",
        "tags": [],
    }

    result = await ask(AskRequest(question="測試問題"), orchestrator)

    orchestrator.ask_claude.assert_awaited_once_with("測試問題")
    assert result.status == "completed"
    assert result.doc_id == "abc-123"
    assert result.summary == "測試答案"


@pytest.mark.asyncio
async def test_ask_raises_502_on_failure():
    orchestrator = AsyncMock()
    orchestrator.ask_claude.return_value = {
        "status": "failed",
        "doc_id": "abc-123",
        "message": "claude -p timed out",
    }

    with pytest.raises(HTTPException) as exc_info:
        await ask(AskRequest(question="測試問題"), orchestrator)
    assert exc_info.value.status_code == 502
    assert "timed out" in exc_info.value.detail
