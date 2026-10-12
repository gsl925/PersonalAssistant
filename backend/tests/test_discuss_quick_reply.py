"""Regression test for Tier-2 item: "💬" decision replies now offer inline
quick-reply buttons (好/不要/先緩著) instead of requiring the user to type a
numbered reply by hand.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.bot.telegram_bot import PersonalAssistantBot
from backend.tasks.project_sync import _discuss_item_keyboard, _DISCUSS_QUICK_REPLIES


def test_discuss_item_keyboard_shape():
    kb = _discuss_item_keyboard("genai-news", 7)
    buttons = [b for row in kb["inline_keyboard"] for b in row]
    assert len(buttons) == 3
    for b in buttons:
        assert b["callback_data"].startswith("discuss:genai-news#7:")
    choices = {b["callback_data"].rsplit(":", 1)[1] for b in buttons}
    assert choices == set(_DISCUSS_QUICK_REPLIES.keys())


@pytest.mark.asyncio
async def test_handle_callback_discuss_resolves_via_write_instruction():
    query = SimpleNamespace(
        data="discuss:genai-news#7:ok",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)

    with patch(
        "backend.tasks.project_sync.write_instruction", new=AsyncMock(return_value=True)
    ) as mock_write:
        await PersonalAssistantBot.handle_callback(SimpleNamespace(), update, context=None)

    mock_write.assert_awaited_once_with("genai-news", "7 好，照做")
    query.edit_message_text.assert_awaited_once()
    assert "好，照做" in query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_callback_discuss_reports_missing_progress_file():
    query = SimpleNamespace(
        data="discuss:genai-news#7:no",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)

    with patch(
        "backend.tasks.project_sync.write_instruction", new=AsyncMock(return_value=False)
    ):
        await PersonalAssistantBot.handle_callback(SimpleNamespace(), update, context=None)

    query.edit_message_text.assert_awaited_once()
    assert "❌" in query.edit_message_text.call_args[0][0]
