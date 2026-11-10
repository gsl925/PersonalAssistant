"""Regression test for the Tier-3 "Project 分類" fix: _classify_project()
used to return the agent's own suggested_project/project_confidence
directly whenever the `projects` table was empty, skipping the LLM
classifier call entirely. Since no agent's SKILL.md output_schema ever
populates those fields, that fallback was always (None, 0.0) — a permanent
deadlock that kept the projects table empty forever, no matter how many
documents came in. The LLM call must now run even with zero existing
projects, so it can bootstrap the first one.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.adapters.base import ProcessedContent
from backend.knowledge.db import async_session_maker
from backend.model_router import AllProvidersFailedError
from backend.orchestrator import Orchestrator


def _make_orchestrator(chat_return_value=None, chat_side_effect=None) -> Orchestrator:
    fake_router = Mock()
    fake_router.chat = AsyncMock(return_value=chat_return_value, side_effect=chat_side_effect)
    return Orchestrator(
        model_router=fake_router,
        skills_loader=Mock(),
        qdrant_client=None,
        session_maker=async_session_maker,
    )


@pytest.mark.asyncio
async def test_classify_project_calls_llm_even_with_zero_existing_projects():
    orch = _make_orchestrator(
        chat_return_value='{"project_name": "GenAI News", "confidence": 0.85}'
    )
    processed = ProcessedContent(source_type="webclip", original_content="an article about GenAI")
    agent_result = {"summary": "an article about GenAI", "suggested_project": None, "project_confidence": 0.0}

    async with async_session_maker() as db:
        name, confidence = await orch._classify_project(db, agent_result, processed)

    orch.model_router.chat.assert_awaited_once()
    assert name == "GenAI News"
    assert confidence == 0.85


@pytest.mark.asyncio
async def test_classify_project_falls_back_to_agent_suggestion_on_llm_failure():
    orch = _make_orchestrator(chat_side_effect=AllProvidersFailedError("down"))
    processed = ProcessedContent(source_type="webclip", original_content="an article")
    agent_result = {"summary": "an article", "suggested_project": None, "project_confidence": 0.0}

    async with async_session_maker() as db:
        name, confidence = await orch._classify_project(db, agent_result, processed)

    assert name is None
    assert confidence == 0.0


@pytest.mark.asyncio
async def test_classify_project_returns_none_when_llm_says_no_match():
    orch = _make_orchestrator(chat_return_value='{"project_name": null, "confidence": 0.0}')
    processed = ProcessedContent(source_type="webclip", original_content="random one-off news")
    agent_result = {"summary": "random one-off news", "suggested_project": None, "project_confidence": 0.0}

    async with async_session_maker() as db:
        name, confidence = await orch._classify_project(db, agent_result, processed)

    orch.model_router.chat.assert_awaited_once()
    assert name is None
