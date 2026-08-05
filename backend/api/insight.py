"""Insight-preview API router — preview an author's core argument for a URL
without saving it, then optionally save. Separate from the ingest/knowledge
routers since this is a distinct two-step concept (preview, then a separate
save decision), not a one-shot ingest."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.knowledge.db import get_db
from backend.orchestrator import Orchestrator

router = APIRouter(prefix="/api/insight", tags=["insight"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _get_orchestrator() -> Orchestrator:
    """FastAPI dependency — returns the app-level Orchestrator singleton."""
    from backend.main import get_orchestrator  # imported lazily to avoid circular imports
    return get_orchestrator()


OrchestratorDep = Annotated[Orchestrator, Depends(_get_orchestrator)]


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PreviewInsightRequest(BaseModel):
    url: str


class PreviewInsightResponse(BaseModel):
    status: str
    preview_id: str | None = None
    title: str | None = None
    insight: str | None = None
    source_url: str | None = None
    is_video: bool | None = None
    message: str | None = None


class SaveInsightResponse(BaseModel):
    status: str
    doc_id: str | None = None
    message: str | None = None
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    ai_insight: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/preview", response_model=PreviewInsightResponse)
async def preview_insight(
    body: PreviewInsightRequest,
    orchestrator: OrchestratorDep,
) -> PreviewInsightResponse:
    result = await orchestrator.preview_insight(body.url)
    if result.get("status") == "failed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"])
    return PreviewInsightResponse(**result)


@router.post("/{preview_id}/save", response_model=SaveInsightResponse)
async def save_insight(
    preview_id: str,
    orchestrator: OrchestratorDep,
) -> SaveInsightResponse:
    result = await orchestrator.save_insight_preview(preview_id)
    if result.get("status") == "failed":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["message"])
    return SaveInsightResponse(**result)
