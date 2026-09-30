"""Dashboard "開發任務" API for factory-tools dev-agent requests.

Submitting writes a formatted "📮 你的指示" line into factory-tools'
PROGRESS.md via the existing project_sync mailman flow (audit trail, same as
before) AND fires the local dev-agent loop (backend/tasks/dev_agent.py) as a
background task — submit = auto-execute, confirmed with the user 2026-09-08.
Complex/ambiguous follow-ups still go through the existing 💬/📮 mechanism or
a human opening an interactive session; this endpoint doesn't add a chat UI.
"""
from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import load_tracked_projects
from backend.knowledge import crud
from backend.knowledge.db import get_db

router = APIRouter(prefix="/api/dev-tasks", tags=["dev-tasks"])

_TARGET_PROJECT = "factory-tools"

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _factory_tools_repo_path() -> Path:
    project = next((p for p in load_tracked_projects() if p.name == _TARGET_PROJECT), None)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{_TARGET_PROJECT}' 尚未加入追蹤專案清單。",
        )
    return Path(project.repo_path)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ToolOut(BaseModel):
    name: str
    display_name: str
    description: str | None


class ToolListResponse(BaseModel):
    items: list[ToolOut]


class AttachmentUploadResponse(BaseModel):
    relative_path: str


class DevTaskSubmitRequest(BaseModel):
    description: str
    reference_path: str | None = None
    attachment_path: str | None = None
    target_tool: str | None = None
    new_tool_name: str | None = None
    notify: str = "default"  # "default" | "none"

    # Placeholder-hint only — does not gate which fields below are shown.
    task_type: str | None = None

    # A concrete input->output example is the ground truth for extraction/
    # aggregation logic that's hard to put into words; also becomes the
    # self-test oracle for the drafting model when given.
    example_input: str | None = None
    example_output: str | None = None

    # INPUT / 邏輯 / OUTPUT checklists — unchecked means "not needed", not
    # "unknown". Always shown in full regardless of task_type (per user
    # decision 2026-09-10: hiding groups by type isn't worth the complexity).
    input_source: list[str] = []
    file_filter: list[str] = []
    filter_detail: str | None = None
    folder_depth: str | None = None

    extraction_method: list[str] = []
    calc_method: list[str] = []
    exception_handling: list[str] = []
    comparison_scope: list[str] = []

    output_format: list[str] = []
    completion_report: list[str] = []
    result_format: str | None = None
    keep_full_log: bool = True  # opt-out, not opt-in — user wants failures pasteable by default

    additional_notes: str | None = None  # escape valve for anything no checkbox covers

    local_model: str | None = None  # which Ollama model drafts this task; None = dev_agent's default


class DevTaskSubmitResponse(BaseModel):
    ok: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/tools", response_model=ToolListResponse)
async def list_tools(db: DbDep) -> ToolListResponse:
    tools = await crud.list_tools(db)
    return ToolListResponse(
        items=[ToolOut(name=t.name, display_name=t.display_name, description=t.description) for t in tools]
    )


@router.post("/attachment", response_model=AttachmentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_attachment(file: UploadFile) -> AttachmentUploadResponse:
    inbox_dir = _factory_tools_repo_path() / "_inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "attachment").suffix or ""
    dest_filename = f"{uuid.uuid4().hex}{suffix}"
    dest_path = inbox_dir / dest_filename

    try:
        with dest_path.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
    except Exception as exc:
        logger.exception("Failed to save dev-task attachment '{}': {}", file.filename, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {exc}",
        ) from exc
    finally:
        await file.close()

    logger.info("POST /api/dev-tasks/attachment — saved '{}' -> {}", file.filename, dest_path)
    return AttachmentUploadResponse(relative_path=f"_inbox/{dest_filename}")


def _fmt_list(items: list[str]) -> str:
    return "、".join(items) if items else "無"


@router.post("/submit", response_model=DevTaskSubmitResponse)
async def submit_dev_task(body: DevTaskSubmitRequest, db: DbDep) -> DevTaskSubmitResponse:
    from backend.tasks.project_sync import write_instruction

    description = " ".join(body.description.strip().splitlines())
    if not description:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="description must not be empty",
        )

    # Pre-flight fail-fast: catch structurally-detectable problems before
    # writing anything or spending a single model token. The Cinebench
    # incident (2026-09-09) burned a full 30-step/30-min run to discover the
    # reference folder had been moved — that's a plain existence check, not
    # something the model needed to figure out.
    reference_path = body.reference_path.strip() if body.reference_path else None
    if reference_path:
        ref = Path(reference_path)
        if not ref.exists() or not ref.is_dir():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"參考路徑不存在或不是資料夾：{reference_path}",
            )
        if not any(p.is_file() for p in ref.rglob("*")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"參考路徑底下沒有任何檔案：{reference_path}",
            )

    if body.target_tool:
        existing_tools = await crud.list_tools(db)
        if not any(t.name == body.target_tool for t in existing_tools):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"目標工具不存在：{body.target_tool}",
            )
        target_line = body.target_tool
    elif body.new_tool_name and body.new_tool_name.strip():
        target_line = f"新工具：{body.new_tool_name.strip()}"
    else:
        target_line = "未指定，請自行判斷分類"

    notify_line = "不需要通知" if body.notify == "none" else "預設（Telegram）"
    example_input = body.example_input.strip() if body.example_input else None
    example_output = body.example_output.strip() if body.example_output else None
    filter_detail = body.filter_detail.strip() if body.filter_detail else None
    additional_notes = body.additional_notes.strip() if body.additional_notes else None

    # write_instruction appends this as a single "- [ ] ..." bullet line per
    # SDD_PROGRESS_SYNC.md's one-line-per-item contract — join with "｜"
    # instead of newlines so the result stays one physical line.
    parts = [
        "【開發任務】",
        f"需求描述：{description}",
        f"任務類型：{body.task_type or '未指定'}",
        f"參考路徑：{reference_path or '無'}",
        f"附件：{body.attachment_path or '無'}",
        f"目標工具：{target_line}",
        f"範例輸入：{example_input or '無'}",
        f"範例輸出：{example_output or '無'}",
        f"INPUT-來源型態：{_fmt_list(body.input_source)}",
        f"INPUT-檔案篩選：{_fmt_list(body.file_filter)}" + (f"（{filter_detail}）" if filter_detail else ""),
        f"INPUT-資料夾層級：{body.folder_depth or '未指定'}",
        f"邏輯-抓取方式：{_fmt_list(body.extraction_method)}",
        f"邏輯-判斷計算：{_fmt_list(body.calc_method)}",
        f"邏輯-例外處理：{_fmt_list(body.exception_handling)}",
        f"邏輯-比較範圍：{_fmt_list(body.comparison_scope)}",
        f"OUTPUT-交付格式：{_fmt_list(body.output_format)}",
        f"OUTPUT-完成回報：{_fmt_list(body.completion_report)}"
        + (f"（格式：{body.result_format}）" if body.result_format else ""),
        f"OUTPUT-除錯log：{'保留完整' if body.keep_full_log else '只在出錯時保留'}",
        f"補充說明：{additional_notes or '無'}",
        f"使用 local 模型：{body.local_model or '預設'}",
        f"結果通知：{notify_line}",
    ]
    instruction_text = "｜".join(parts)

    ok = await write_instruction(_TARGET_PROJECT, instruction_text)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{_TARGET_PROJECT}' not found or PROGRESS.md missing.",
        )

    from backend.tasks.dev_agent import run_dev_agent_task

    asyncio.create_task(
        run_dev_agent_task(
            project_name=_TARGET_PROJECT,
            task_description=description,
            repo_path=str(_factory_tools_repo_path()),
            target_tool_name=body.target_tool or None,
            new_tool_name=body.new_tool_name.strip() if body.new_tool_name else None,
            reference_path=reference_path,
            attachment_path=body.attachment_path or None,
            task_type=body.task_type or None,
            example_input=example_input,
            example_output=example_output,
            input_source=body.input_source,
            file_filter=body.file_filter,
            filter_detail=filter_detail,
            folder_depth=body.folder_depth or None,
            extraction_method=body.extraction_method,
            calc_method=body.calc_method,
            exception_handling=body.exception_handling,
            comparison_scope=body.comparison_scope,
            output_format=body.output_format,
            completion_report=body.completion_report,
            result_format=body.result_format or None,
            keep_full_log=body.keep_full_log,
            additional_notes=additional_notes,
            local_model=body.local_model or None,
            notify=body.notify,
        )
    )
    return DevTaskSubmitResponse(ok=True)
