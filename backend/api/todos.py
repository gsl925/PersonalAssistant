"""Todo API router — quick-capture todos, separate from meeting action_items."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.knowledge.db import get_db
from backend.orchestrator import Orchestrator

router = APIRouter(prefix="/api/todos", tags=["todos"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _get_orchestrator() -> Orchestrator:
    """FastAPI dependency — returns the app-level Orchestrator singleton."""
    from backend.main import get_orchestrator  # imported lazily to avoid circular imports
    return get_orchestrator()


OrchestratorDep = Annotated[Orchestrator, Depends(_get_orchestrator)]


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateTodoRequest(BaseModel):
    text: str
    source: str = "dashboard"


class ReminderOut(BaseModel):
    label: str
    remind_at: str


class TodoOut(BaseModel):
    id: str
    content: str
    status: str
    start_date: str | None = None
    due_date: str | None = None
    source: str
    source_url: str | None = None
    created_at: datetime
    reminders: list[ReminderOut] | None = None


class TodoListResponse(BaseModel):
    items: list[TodoOut]
    count: int


class UpdateTodoStatusRequest(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=TodoOut)
async def create_todo(
    body: CreateTodoRequest,
    orchestrator: OrchestratorDep,
) -> TodoOut:
    """Explicit-intent todo creation (desktop widget / dashboard quick-add).

    Skips the ambient is-this-a-todo classification the Telegram bot uses —
    the caller already knows this is a todo, so this goes straight to date
    extraction.
    """
    result = await orchestrator.create_todo_from_text(body.text, source=body.source)
    return TodoOut(**result)


@router.get("", response_model=TodoListResponse)
async def list_todos(
    orchestrator: OrchestratorDep,
    status_: str | None = Query(default="pending", alias="status"),
    due_before: date | None = Query(default=None),
) -> TodoListResponse:
    items_raw = await orchestrator.get_todos(
        status=status_, due_before=due_before.isoformat() if due_before else None
    )
    items = [TodoOut(**item) for item in items_raw]
    return TodoListResponse(items=items, count=len(items))


@router.patch("/{todo_id}", response_model=dict)
async def update_todo_status(
    todo_id: uuid.UUID,
    body: UpdateTodoStatusRequest,
    orchestrator: OrchestratorDep,
) -> dict:
    result = await orchestrator.update_todo_status(str(todo_id), body.status)
    if result.get("status") == "failed":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["message"])
    return result


@router.post("/{todo_id}/snooze", response_model=dict)
async def snooze_todo(
    todo_id: uuid.UUID,
    orchestrator: OrchestratorDep,
) -> dict:
    """Add one more reminder a day from now — same action as the "😴 明天再
    提醒" button on a fired Telegram reminder, exposed here for dashboard
    parity."""
    result = await orchestrator.snooze_todo(str(todo_id))
    if result.get("status") == "failed":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["message"])
    return result
