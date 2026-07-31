"""Knowledge base API router — query documents, projects, search, and mindmap."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.knowledge import crud
from backend.knowledge.db import get_db
from backend.knowledge.models import Document, DocumentRelation, Project
from backend.orchestrator import Orchestrator

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _get_orchestrator() -> Orchestrator:
    """FastAPI dependency — returns the app-level Orchestrator singleton."""
    from backend.main import get_orchestrator  # imported lazily to avoid circular imports
    return get_orchestrator()


OrchestratorDep = Annotated[Orchestrator, Depends(_get_orchestrator)]


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------


class TagOut(BaseModel):
    keyword: str

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: uuid.UUID
    source_type: str
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    file_path: str | None = None
    source_url: str | None = None
    agent_used: str | None = None
    processing_status: str
    created_at: datetime
    updated_at: datetime | None = None
    tags: list[TagOut] = []
    projects: list[ProjectOut] = []

    model_config = {"from_attributes": True}


class DocumentContentOut(BaseModel):
    id: uuid.UUID
    title: str | None = None
    original_content: str | None = None
    type_specific_data: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class RetryResponse(BaseModel):
    status: str
    doc_id: str
    message: str
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    tags: list[str] | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentOut]
    skip: int
    limit: int
    count: int


class SearchResult(BaseModel):
    id: str
    score: float
    payload: dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class MindmapNode(BaseModel):
    id: str
    title: str | None = None
    source_type: str
    category: str | None = None
    tags: list[str] = []


class MindmapEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    score: float


class MindmapResponse(BaseModel):
    center_id: str
    nodes: list[MindmapNode]
    edges: list[MindmapEdge]


class ActionItemOut(BaseModel):
    task: str
    owner: str | None = None
    due_date: str | None = None
    source_doc_id: uuid.UUID
    source_title: str | None = None
    meeting_date: str | None = None
    created_at: datetime


class ActionItemListResponse(BaseModel):
    items: list[ActionItemOut]
    count: int


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _doc_to_out(doc: Document) -> DocumentOut:
    projects = [
        ProjectOut(
            id=link.project.id,
            name=link.project.name,
            description=link.project.description,
            status=link.project.status,
            created_at=link.project.created_at,
        )
        for link in (doc.project_links or [])
        if link.project is not None
    ]
    return DocumentOut(
        id=doc.id,
        source_type=doc.source_type,
        title=doc.title,
        summary=doc.summary,
        category=doc.category,
        file_path=doc.file_path,
        source_url=doc.source_url,
        agent_used=doc.agent_used,
        processing_status=doc.processing_status,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        tags=[TagOut(keyword=t.keyword) for t in (doc.tags or [])],
        projects=projects,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    db: DbDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    source_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
) -> DocumentListResponse:
    """List documents with optional filters and pagination."""
    docs = await crud.get_documents(
        db,
        skip=skip,
        limit=limit,
        source_type=source_type,
        category=category,
        project_id=project_id,
        start_date=start_date,
        end_date=end_date,
    )
    return DocumentListResponse(
        items=[_doc_to_out(d) for d in docs],
        skip=skip,
        limit=limit,
        count=len(docs),
    )


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID,
    db: DbDep,
) -> DocumentOut:
    """Retrieve a single document including its tags and project links."""
    doc = await crud.get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return _doc_to_out(doc)


@router.delete("/documents/{doc_id}", response_model=dict)
async def delete_document(doc_id: uuid.UUID, db: DbDep) -> dict:
    """Delete a note/document — the DB row (cascades to its tags/project
    links), its Qdrant vector, and its uploaded file (if any). Used to clean
    up experimental/test captures from the Dashboard."""
    from backend.main import get_qdrant_client

    ok, file_path = await crud.delete_document(db, doc_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        await get_qdrant_client().delete_document(str(doc_id))
    except Exception as exc:
        logger.warning("Failed to delete Qdrant vector for {}: {}", doc_id, exc)

    if file_path:
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to delete file {} for document {}: {}", file_path, doc_id, exc)

    return {"ok": True}


@router.post("/documents/{doc_id}/retry", response_model=RetryResponse)
async def retry_document(
    doc_id: uuid.UUID,
    orchestrator: OrchestratorDep,
) -> RetryResponse:
    """Manually re-run processing for a document currently in ``"failed"`` status.

    Reuses whatever was persisted (file_path / source_url / original_content)
    instead of requiring the caller to re-upload anything.
    """
    result = await orchestrator.retry_document(str(doc_id))
    if result.get("status") == "failed" and "not found" in result.get("message", "").lower():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["message"])
    return RetryResponse(**result)


@router.get("/documents/{doc_id}/content", response_model=DocumentContentOut)
async def get_document_content(
    doc_id: uuid.UUID,
    db: DbDep,
) -> DocumentContentOut:
    """Retrieve the full original content (transcript/extracted text) for a
    document, plus its raw per-skill output — the fields ``DocumentOut``
    deliberately omits to keep list/detail responses lean."""
    doc = await crud.get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentContentOut(
        id=doc.id,
        title=doc.title,
        original_content=doc.original_content,
        type_specific_data=doc.type_specific_data,
    )


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(db: DbDep) -> list[ProjectOut]:
    """List all active projects."""
    projects = await crud.get_projects(db)
    return [
        ProjectOut(
            id=p.id,
            name=p.name,
            description=p.description,
            status=p.status,
            created_at=p.created_at,
        )
        for p in projects
    ]


@router.delete("/projects/{project_id}", response_model=dict)
async def delete_project(project_id: uuid.UUID, db: DbDep) -> dict:
    """Delete a project tag — documents keep existing, they just lose the
    project link. Used to clean up experimental/test project tags."""
    ok = await crud.delete_project(db, project_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return {"ok": True}


@router.get("/projects/{project_id}/documents", response_model=DocumentListResponse)
async def list_project_documents(
    project_id: uuid.UUID,
    db: DbDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> DocumentListResponse:
    """List documents belonging to a specific project."""
    docs = await crud.get_project_documents(db, project_id, skip=skip, limit=limit)
    return DocumentListResponse(
        items=[_doc_to_out(d) for d in docs],
        skip=skip,
        limit=limit,
        count=len(docs),
    )


@router.get("/search", response_model=SearchResponse)
async def semantic_search(
    q: str = Query(min_length=1, description="Search query text"),
    limit: int = Query(default=10, ge=1, le=50),
) -> SearchResponse:
    """Embed the query with the model router and search Qdrant for similar documents."""
    from backend.main import get_model_router, get_qdrant_client

    model_router = get_model_router()
    qdrant = get_qdrant_client()

    logger.info("GET /api/knowledge/search — q={!r}, limit={}", q, limit)

    try:
        vector = await model_router.get_embedding(q)
        hits = await qdrant.search_similar(vector, limit=limit)
    except Exception as exc:
        logger.exception("Semantic search failed: {}", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Search unavailable: {exc}",
        ) from exc

    return SearchResponse(
        query=q,
        results=[
            SearchResult(id=h["id"], score=h["score"], payload=h["payload"])
            for h in hits
        ],
    )


@router.get("/timeline", response_model=DocumentListResponse)
async def get_timeline(
    db: DbDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    source_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
) -> DocumentListResponse:
    """Documents sorted by creation date descending, with the same filter options as /documents."""
    # crud.get_documents already sorts by created_at DESC — timeline is the same query.
    docs = await crud.get_documents(
        db,
        skip=skip,
        limit=limit,
        source_type=source_type,
        category=category,
        project_id=project_id,
        start_date=start_date,
        end_date=end_date,
    )
    return DocumentListResponse(
        items=[_doc_to_out(d) for d in docs],
        skip=skip,
        limit=limit,
        count=len(docs),
    )


@router.get("/action-items", response_model=ActionItemListResponse)
async def list_action_items(
    db: DbDep,
    due_before: date | None = Query(
        default=None,
        description="Only include items whose due_date is on or before this date. Items with no due_date are always included.",
    ),
) -> ActionItemListResponse:
    """Aggregate ``action_items`` across all completed meeting documents.

    Only meeting-agent's output schema defines ``action_items`` — there is no
    "done" flag anywhere in the data model, so this always reflects everything
    ever extracted, not just outstanding ones.
    """
    raw_items = await crud.list_action_items(db, due_before=due_before)
    items = [ActionItemOut(**raw) for raw in raw_items]
    return ActionItemListResponse(items=items, count=len(items))


@router.get("/mindmap/{doc_id}", response_model=MindmapResponse)
async def get_mindmap(
    doc_id: uuid.UUID,
    db: DbDep,
) -> MindmapResponse:
    """Return the center document and all related nodes/edges up to 2 hops away (BFS)."""
    # Verify center document exists first.
    center = await crud.get_document(db, doc_id)
    if center is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    nodes_orm, edges_orm = await crud.get_mindmap_data(db, doc_id, max_hops=2)

    nodes = [
        MindmapNode(
            id=str(n.id),
            title=n.title,
            source_type=n.source_type,
            category=n.category,
            tags=[t.keyword for t in (n.tags or [])],
        )
        for n in nodes_orm
    ]

    # Deduplicate edges (BFS can surface the same relation via both hops).
    seen: set[tuple[str, str, str]] = set()
    edges: list[MindmapEdge] = []
    for e in edges_orm:
        key = (str(e.doc_id_a), str(e.doc_id_b), e.relation_type)
        if key not in seen:
            seen.add(key)
            edges.append(
                MindmapEdge(
                    source=str(e.doc_id_a),
                    target=str(e.doc_id_b),
                    relation_type=e.relation_type,
                    score=e.score,
                )
            )

    return MindmapResponse(center_id=str(doc_id), nodes=nodes, edges=edges)
