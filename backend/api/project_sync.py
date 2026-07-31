"""Cross-project PROGRESS.md sync API — Dashboard front-end for the same
mailman flow project_sync.py/telegram_bot.py already drive from Telegram.
No Orchestrator dependency here (unlike todos.py) — project_sync.py's
functions are self-contained file/state operations, not part of the
Orchestrator's domain, so routing through it would just be a pointless
extra layer.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/api/project-sync", tags=["project-sync"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PendingItemOut(BaseModel):
    number: int
    content: str


class TrackedProjectOut(BaseModel):
    name: str
    label: str
    pending_items: list[PendingItemOut]


class TrackedProjectListResponse(BaseModel):
    items: list[TrackedProjectOut]


class SendInstructionRequest(BaseModel):
    project_name: str
    text: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/projects", response_model=TrackedProjectListResponse)
async def list_tracked_projects() -> TrackedProjectListResponse:
    from backend.tasks.project_sync import get_projects_overview

    return TrackedProjectListResponse(
        items=[TrackedProjectOut(**p) for p in get_projects_overview()]
    )


@router.post("/instruction", response_model=dict)
async def send_instruction(body: SendInstructionRequest) -> dict:
    from backend.tasks.project_sync import write_instruction

    ok = await write_instruction(body.project_name, body.text)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or PROGRESS.md missing.",
        )
    return {"ok": True}


@router.delete("/projects/{name}", response_model=dict)
async def delete_tracked_project(name: str) -> dict:
    from backend.tasks.project_sync import remove_project

    ok = remove_project(name)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return {"ok": True}
