from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.knowledge.models import (
    Document,
    DocumentProject,
    DocumentRelation,
    DocumentTag,
    Project,
)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def create_document(
    db: AsyncSession,
    source_type: str,
    title: str | None = None,
    summary: str | None = None,
    category: str | None = None,
    original_content: str | None = None,
    file_path: str | None = None,
    source_url: str | None = None,
    agent_used: str | None = None,
    processing_status: str = "pending",
) -> Document:
    doc = Document(
        id=uuid.uuid4(),
        source_type=source_type,
        title=title,
        summary=summary,
        category=category,
        original_content=original_content,
        file_path=file_path,
        source_url=source_url,
        agent_used=agent_used,
        processing_status=processing_status,
    )
    db.add(doc)
    await db.flush()
    return doc


async def get_document(db: AsyncSession, doc_id: uuid.UUID) -> Document | None:
    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.tags),
            selectinload(Document.project_links).selectinload(DocumentProject.project),
        )
        .where(Document.id == doc_id)
    )
    return result.scalar_one_or_none()


async def update_document_status(
    db: AsyncSession,
    doc_id: uuid.UUID,
    status: str,
    **kwargs,
) -> Document | None:
    doc = await db.get(Document, doc_id)
    if doc is None:
        return None
    doc.processing_status = status
    for key, value in kwargs.items():
        if hasattr(doc, key):
            setattr(doc, key, value)
    doc.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return doc


async def get_documents(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    source_type: str | None = None,
    category: str | None = None,
    project_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> Sequence[Document]:
    q = select(Document).options(
        selectinload(Document.tags),
        selectinload(Document.project_links).selectinload(DocumentProject.project),
    )

    filters = []
    if source_type:
        filters.append(Document.source_type == source_type)
    if category:
        filters.append(Document.category == category)
    if start_date:
        filters.append(Document.created_at >= start_date)
    if end_date:
        filters.append(Document.created_at <= end_date)
    if project_id:
        q = q.join(DocumentProject, DocumentProject.doc_id == Document.id).where(
            DocumentProject.project_id == project_id
        )
    if filters:
        q = q.where(and_(*filters))

    q = q.order_by(Document.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


async def get_documents_created_today(db: AsyncSession) -> Sequence[Document]:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.tags))
        .where(Document.created_at >= today_start)
        .where(Document.processing_status == "completed")
        .order_by(Document.created_at.asc())
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


async def add_tags(db: AsyncSession, doc_id: uuid.UUID, keywords: list[str]) -> None:
    existing_result = await db.execute(
        select(DocumentTag.keyword).where(DocumentTag.doc_id == doc_id)
    )
    existing = set(existing_result.scalars().all())
    new_tags = [
        DocumentTag(doc_id=doc_id, keyword=kw.lower().strip())
        for kw in keywords
        if kw.lower().strip() not in existing and kw.strip()
    ]
    if new_tags:
        db.add_all(new_tags)
        await db.flush()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


async def get_or_create_project(
    db: AsyncSession,
    name: str,
    description: str | None = None,
) -> Project:
    result = await db.execute(select(Project).where(Project.name == name))
    project = result.scalar_one_or_none()
    if project is None:
        project = Project(id=uuid.uuid4(), name=name, description=description)
        db.add(project)
        await db.flush()
    return project


async def get_projects(db: AsyncSession) -> Sequence[Project]:
    result = await db.execute(
        select(Project).where(Project.status == "active").order_by(Project.name)
    )
    return result.scalars().all()


async def get_project_documents(
    db: AsyncSession,
    project_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[Document]:
    result = await db.execute(
        select(Document)
        .join(DocumentProject, DocumentProject.doc_id == Document.id)
        .where(DocumentProject.project_id == project_id)
        .options(selectinload(Document.tags))
        .order_by(Document.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Document ↔ Project links
# ---------------------------------------------------------------------------


async def link_document_project(
    db: AsyncSession,
    doc_id: uuid.UUID,
    project_id: uuid.UUID,
    confidence: float | None = None,
) -> None:
    existing = await db.get(DocumentProject, (doc_id, project_id))
    if existing is None:
        link = DocumentProject(doc_id=doc_id, project_id=project_id, confidence=confidence)
        db.add(link)
        await db.flush()


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


async def add_relation(
    db: AsyncSession,
    doc_id_a: uuid.UUID,
    doc_id_b: uuid.UUID,
    relation_type: str,
    score: float,
) -> None:
    # Avoid duplicates by checking both orderings
    existing = await db.execute(
        select(DocumentRelation).where(
            or_(
                and_(
                    DocumentRelation.doc_id_a == doc_id_a,
                    DocumentRelation.doc_id_b == doc_id_b,
                    DocumentRelation.relation_type == relation_type,
                ),
                and_(
                    DocumentRelation.doc_id_a == doc_id_b,
                    DocumentRelation.doc_id_b == doc_id_a,
                    DocumentRelation.relation_type == relation_type,
                ),
            )
        )
    )
    if existing.scalar_one_or_none() is None:
        rel = DocumentRelation(
            doc_id_a=doc_id_a,
            doc_id_b=doc_id_b,
            relation_type=relation_type,
            score=score,
        )
        db.add(rel)
        await db.flush()


async def get_related_documents(
    db: AsyncSession,
    doc_id: uuid.UUID,
    limit: int = 10,
) -> Sequence[Document]:
    """Return documents related to *doc_id* via document_relations (both sides)."""
    related_ids_result = await db.execute(
        select(
            DocumentRelation.doc_id_b.label("related_id")
        ).where(DocumentRelation.doc_id_a == doc_id)
        .union(
            select(DocumentRelation.doc_id_a.label("related_id")).where(
                DocumentRelation.doc_id_b == doc_id
            )
        )
        .limit(limit)
    )
    related_ids = [row.related_id for row in related_ids_result]
    if not related_ids:
        return []

    result = await db.execute(
        select(Document)
        .options(selectinload(Document.tags))
        .where(Document.id.in_(related_ids))
    )
    return result.scalars().all()


async def get_mindmap_data(
    db: AsyncSession,
    doc_id: uuid.UUID,
    max_hops: int = 2,
) -> tuple[list[Document], list[DocumentRelation]]:
    """BFS over document_relations up to *max_hops* away from *doc_id*.

    Returns (nodes, edges) where nodes includes the center document.
    """
    visited: set[uuid.UUID] = {doc_id}
    frontier: set[uuid.UUID] = {doc_id}
    all_edges: list[DocumentRelation] = []

    for _ in range(max_hops):
        if not frontier:
            break
        edges_result = await db.execute(
            select(DocumentRelation).where(
                or_(
                    DocumentRelation.doc_id_a.in_(frontier),
                    DocumentRelation.doc_id_b.in_(frontier),
                )
            )
        )
        edges = edges_result.scalars().all()
        new_frontier: set[uuid.UUID] = set()
        for edge in edges:
            all_edges.append(edge)
            for neighbor in (edge.doc_id_a, edge.doc_id_b):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_frontier.add(neighbor)
        frontier = new_frontier

    docs_result = await db.execute(
        select(Document)
        .options(selectinload(Document.tags))
        .where(Document.id.in_(visited))
    )
    nodes = docs_result.scalars().all()
    return nodes, all_edges
