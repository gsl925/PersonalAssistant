from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.knowledge.models import (
    Document,
    DocumentProject,
    DocumentRelation,
    DocumentTag,
    Project,
    Todo,
    TodoReminder,
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


async def get_meeting_documents_with_action_items(db: AsyncSession) -> Sequence[Document]:
    """Completed meeting documents that have any per-skill output stored —
    callers flatten ``type_specific_data["action_items"]`` themselves since
    only the meeting-agent schema defines that field."""
    result = await db.execute(
        select(Document)
        .where(Document.source_type == "meeting")
        .where(Document.processing_status == "completed")
        .where(Document.type_specific_data.isnot(None))
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


async def list_action_items(
    db: AsyncSession, due_before: date | None = None
) -> list[dict[str, Any]]:
    """Aggregate ``action_items`` across all completed meeting documents.

    Only meeting-agent's output schema defines ``action_items`` — there is no
    "done" flag anywhere in the data model, so this always reflects everything
    ever extracted, not just outstanding ones. Shared by the REST endpoint and
    the Telegram bot's todo-intent shortcut so both stay in sync.
    """
    docs = await get_meeting_documents_with_action_items(db)

    items: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.type_specific_data or {}
        meeting_date = data.get("meeting_date")
        for raw in data.get("action_items") or []:
            if not isinstance(raw, dict) or not raw.get("task"):
                continue
            due_date_str = raw.get("due_date")
            if due_before is not None and due_date_str:
                try:
                    if date.fromisoformat(due_date_str[:10]) > due_before:
                        continue
                except ValueError:
                    pass
            items.append(
                {
                    "task": raw["task"],
                    "owner": raw.get("owner"),
                    "due_date": due_date_str,
                    "source_doc_id": doc.id,
                    "source_title": doc.title,
                    "meeting_date": meeting_date,
                    "created_at": doc.created_at,
                }
            )
    return items


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


async def get_documents_sharing_tags(
    db: AsyncSession,
    doc_id: uuid.UUID,
    keywords: list[str],
    limit: int = 10,
) -> Sequence[tuple[uuid.UUID, int]]:
    """Return ``(other_doc_id, shared_tag_count)`` for documents that share at
    least one of *keywords* with *doc_id*, ordered by most shared first."""
    if not keywords:
        return []
    normalized = [kw.lower().strip() for kw in keywords if kw.strip()]
    if not normalized:
        return []

    result = await db.execute(
        select(DocumentTag.doc_id, func.count(DocumentTag.keyword).label("shared_count"))
        .where(DocumentTag.keyword.in_(normalized))
        .where(DocumentTag.doc_id != doc_id)
        .group_by(DocumentTag.doc_id)
        .order_by(func.count(DocumentTag.keyword).desc())
        .limit(limit)
    )
    return [(row.doc_id, row.shared_count) for row in result]


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


# ---------------------------------------------------------------------------
# Todos (quick-capture)
# ---------------------------------------------------------------------------


async def create_todo(
    db: AsyncSession,
    *,
    content: str,
    source: str,
    raw_input: str | None = None,
    source_url: str | None = None,
    start_date: date | None = None,
    due_date: date | None = None,
) -> Todo:
    todo = Todo(
        id=uuid.uuid4(),
        content=content,
        source=source,
        raw_input=raw_input,
        source_url=source_url,
        start_date=start_date,
        due_date=due_date,
    )
    db.add(todo)
    await db.flush()
    return todo


async def create_todo_reminders(
    db: AsyncSession, todo_id: uuid.UUID, reminders: list[tuple[str, datetime]]
) -> list[TodoReminder]:
    """reminders is a list of (label, remind_at) pairs, e.g. [("start", ...), ("due", ...)]."""
    rows = [
        TodoReminder(id=uuid.uuid4(), todo_id=todo_id, label=label, remind_at=remind_at)
        for label, remind_at in reminders
    ]
    if rows:
        db.add_all(rows)
        await db.flush()
    return rows


async def get_todo(db: AsyncSession, todo_id: uuid.UUID) -> Todo | None:
    return await db.get(Todo, todo_id)


async def list_todos(
    db: AsyncSession,
    status: str | None = None,
    due_before: date | None = None,
) -> Sequence[Todo]:
    q = select(Todo).options(selectinload(Todo.reminders))
    filters = []
    if status:
        filters.append(Todo.status == status)
    if due_before is not None:
        filters.append(Todo.due_date.isnot(None))
        filters.append(Todo.due_date <= due_before)
    if filters:
        q = q.where(and_(*filters))
    q = q.order_by(Todo.due_date.asc().nulls_last(), Todo.created_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


async def update_todo_status(
    db: AsyncSession, todo_id: uuid.UUID, status: str
) -> Todo | None:
    todo = await db.get(Todo, todo_id)
    if todo is None:
        return None
    todo.status = status
    todo.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return todo


async def list_pending_todo_reminders(db: AsyncSession) -> Sequence[TodoReminder]:
    """Unsent reminders belonging to still-pending todos — used to re-register
    APScheduler jobs on startup, since the in-memory job store loses
    everything on restart."""
    result = await db.execute(
        select(TodoReminder)
        .join(Todo, Todo.id == TodoReminder.todo_id)
        .where(TodoReminder.sent.is_(False))
        .where(Todo.status == "pending")
    )
    return result.scalars().all()


async def get_todo_reminder(db: AsyncSession, reminder_id: uuid.UUID) -> TodoReminder | None:
    return await db.get(TodoReminder, reminder_id)


async def mark_todo_reminder_sent(db: AsyncSession, reminder_id: uuid.UUID) -> None:
    reminder = await db.get(TodoReminder, reminder_id)
    if reminder is not None:
        reminder.sent = True
        await db.flush()


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
