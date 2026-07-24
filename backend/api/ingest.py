"""Ingest API router — receives new content and hands it to the orchestrator."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.factory import AdapterFactory
from backend.config import settings
from backend.knowledge.db import get_db
from backend.orchestrator import Orchestrator

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TextIngestRequest(BaseModel):
    text: str


class UrlIngestRequest(BaseModel):
    url: str


class IngestResponse(BaseModel):
    status: str
    doc_id: str | None = None
    message: str
    agent_name: str | None = None
    confidence: float | None = None
    available_agents: list[str] | None = None


# ---------------------------------------------------------------------------
# Dependency: orchestrator
# ---------------------------------------------------------------------------


def _get_orchestrator() -> Orchestrator:
    """FastAPI dependency — returns the app-level Orchestrator singleton."""
    from backend.main import get_orchestrator  # imported lazily to avoid circular imports
    return get_orchestrator()


OrchestratorDep = Annotated[Orchestrator, Depends(_get_orchestrator)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/text", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_text(
    body: TextIngestRequest,
    orchestrator: OrchestratorDep,
) -> IngestResponse:
    """Accept raw text and route it through the orchestrator."""
    if not body.text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="text must not be empty",
        )
    logger.info("POST /api/ingest/text — {} chars", len(body.text))
    result = await orchestrator.process_input("text", body.text)
    return IngestResponse(**result)


@router.post("/file", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_file(
    file: UploadFile,
    orchestrator: OrchestratorDep,
    input_type: Annotated[str | None, Form()] = None,
) -> IngestResponse:
    """Accept an uploaded file, persist it to the uploads directory, then process it.

    `input_type` is an optional override for callers that know better than
    extension-sniffing which adapter should handle the file — e.g. the
    desktop widget uploading a hotkey screenshot as a `.png`, which would
    otherwise be auto-detected as a generic "file" and misrouted into
    DocumentAdapter (PDF/DOCX only).
    """
    if input_type is not None and input_type.lower() not in AdapterFactory.registered_types():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown input_type={input_type!r}. Known: {AdapterFactory.supported_aliases()}",
        )

    uploads_dir: Path = settings.UPLOADS_DIR
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Build a collision-free filename while preserving the original extension.
    suffix = Path(file.filename or "upload").suffix or ""
    dest_filename = f"{uuid.uuid4().hex}{suffix}"
    dest_path = uploads_dir / dest_filename

    try:
        with dest_path.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
    except Exception as exc:
        logger.exception("Failed to save upload '{}': {}", file.filename, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {exc}",
        ) from exc
    finally:
        await file.close()

    logger.info("POST /api/ingest/file — saved '{}' → {}", file.filename, dest_path)
    resolved_type = input_type.lower() if input_type else (
        "video" if suffix.lower() in _VIDEO_EXTENSIONS else "file"
    )
    result = await orchestrator.process_input(
        resolved_type, str(dest_path), user_context={"original_filename": file.filename}
    )
    return IngestResponse(**result)


@router.post("/url", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_url(
    body: UrlIngestRequest,
    orchestrator: OrchestratorDep,
) -> IngestResponse:
    """Accept a URL and pass it to the webclip adapter via the orchestrator."""
    url = body.url.strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="url must not be empty",
        )
    logger.info("POST /api/ingest/url — {}", url)
    result = await orchestrator.process_input("url", url)
    return IngestResponse(**result)
