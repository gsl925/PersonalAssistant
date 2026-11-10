"""Regression test for Tier-1 bug #3: when every provider failed (or the
LLM's response wasn't parseable JSON), the orchestrator used to swallow the
failure into a generic placeholder result and save the document as
'completed' — permanently hiding the failure, since retry_document() only
accepts documents already in 'failed' status.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from backend.adapters.base import ProcessedContent
from backend.knowledge import crud
from backend.knowledge.db import async_session_maker
from backend.model_router import AllProvidersFailedError
from backend.orchestrator import Orchestrator
from backend.skills_loader import SkillDefinition

_FAKE_SKILL = SkillDefinition(
    name="webclip-agent",
    description="test",
    model="complex_reasoning",
    tools=[],
    enabled=True,
    output_schema="webclip",
    version="1",
    system_prompt="You are a test agent.",
    skill_dir=None,
)


def _make_orchestrator(chat_side_effect) -> Orchestrator:
    fake_router = Mock()
    fake_router.chat = AsyncMock(side_effect=chat_side_effect)

    fake_skills_loader = Mock()
    fake_skills_loader.get_skill = Mock(return_value=_FAKE_SKILL)
    fake_skills_loader.get_enabled_skills = Mock(return_value=[_FAKE_SKILL])

    return Orchestrator(
        model_router=fake_router,
        skills_loader=fake_skills_loader,
        qdrant_client=None,
        session_maker=async_session_maker,
    )


async def _make_doc_and_processed() -> tuple[uuid.UUID, ProcessedContent]:
    async with async_session_maker() as session:
        doc = await crud.create_document(session, source_type="webclip", processing_status="pending")
        await session.commit()
        doc_id = doc.id
    processed = ProcessedContent(
        source_type="webclip",
        original_content="some article content",
        title="Test Article",
        source_url="https://example.com/article",
    )
    return doc_id, processed


async def _cleanup_doc(doc_id: uuid.UUID) -> None:
    async with async_session_maker() as session:
        doc = await crud.get_document(session, doc_id)
        if doc is not None:
            await session.delete(doc)
            await session.commit()


@pytest.mark.asyncio
async def test_llm_exhausted_retries_marks_document_failed_not_completed(monkeypatch):
    from backend import orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "_RETRY_DELAY", 0.01)  # don't slow the test down

    orch = _make_orchestrator(chat_side_effect=AllProvidersFailedError("all providers down"))
    doc_id, processed = await _make_doc_and_processed()

    try:
        result = await orch._route_and_finalize(doc_id, "url", processed)

        assert result["status"] == "failed"

        async with async_session_maker() as session:
            doc = await crud.get_document(session, doc_id)
            assert doc.processing_status == "failed", (
                "an LLM failure must leave the document in 'failed' status, "
                "not 'completed' with a placeholder summary/category"
            )
            assert doc.category != "General"

        # retry_document()'s guard (processing_status == 'failed') must now
        # accept this document — this was unreachable before the fix.
        retry_result = await orch.retry_document(str(doc_id))
        assert retry_result.get("message") != "Document is not in 'failed' state (current: completed)"
    finally:
        await _cleanup_doc(doc_id)


@pytest.mark.asyncio
async def test_invalid_json_response_marks_document_failed_not_completed(monkeypatch):
    from backend import orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "_RETRY_DELAY", 0.01)

    orch = _make_orchestrator(chat_side_effect=lambda *a, **k: "not even close to json")
    doc_id, processed = await _make_doc_and_processed()

    try:
        result = await orch._route_and_finalize(doc_id, "url", processed)

        assert result["status"] == "failed"

        async with async_session_maker() as session:
            doc = await crud.get_document(session, doc_id)
            assert doc.processing_status == "failed"
            assert doc.category != "General"
    finally:
        await _cleanup_doc(doc_id)
