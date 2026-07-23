"""Knowledge base API router — query documents, projects, search, and mindmap."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.knowledge import crud
from backend.knowledge.db import get_db
from backend.knowledge.models import Document, DocumentRelation, Project

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


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
