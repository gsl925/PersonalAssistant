"""Dashboard chat API — lets the "問答記錄" (ChatView) page start a new
question itself instead of being a read-only archive of Telegram /ask
history. Same underlying Orchestrator.ask_claude() call as /ask, saved the
same way (source_type="chat"), so it shows up in the same list either way.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.orchestrator import Orchestrator

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _get_orchestrator() -> Orchestrator:
    """FastAPI dependency — returns the app-level Orchestrator singleton."""
    from backend.main import get_orchestrator  # imported lazily to avoid circular imports
    return get_orchestrator()


OrchestratorDep = Annotated[Orchestrator, Depends(_get_orchestrator)]


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    status: str
    doc_id: str | None = None
    message: str | None = None
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    tags: list[str] | None = None


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, orchestrator: OrchestratorDep) -> AskResponse:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="question must not be empty")
    result = await orchestrator.ask_claude(question)
    if result.get("status") == "failed":
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result.get("message", "發生錯誤"))
    return AskResponse(**result)


class KBSource(BaseModel):
    doc_id: str
    title: str | None
    score: float
    created_at: str | None


class KBAnswer(BaseModel):
    answer: str | None
    model: str | None
    latency_ms: int | None
    error: str | None = None


class AskKnowledgeBaseRequest(BaseModel):
    question: str
    include_cloud: bool = False


class AskKnowledgeBaseResponse(BaseModel):
    sources: list[KBSource]
    local: KBAnswer
    cloud: KBAnswer | None = None


@router.post("/ask_kb", response_model=AskKnowledgeBaseResponse)
async def ask_knowledge_base(
    body: AskKnowledgeBaseRequest, orchestrator: OrchestratorDep
) -> AskKnowledgeBaseResponse:
    """RAG Q&A over the saved knowledge base — local (Ollama) only by
    default; pass include_cloud=true to also run cloud (Claude) side by
    side, e.g. for the dashboard's comparison mode. Doesn't persist
    anything; see Orchestrator.ask_knowledge_base()."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="question must not be empty")
    result = await orchestrator.ask_knowledge_base(question, include_cloud=body.include_cloud)
    return AskKnowledgeBaseResponse(**result)
