"""Retrieval step shared by both backends of /api/chat/ask_kb.

Embedding and vector search were already wired up for document-to-document
relation finding (see Orchestrator._post_process) — this module reuses the
same ModelRouter/Qdrant plumbing to retrieve for a *question* instead of a
newly-saved document, then builds an LLM-ready context block. Generation
(local vs cloud) stays out of here — the caller decides who answers.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.knowledge import crud
from backend.model_router import ModelRouter

# Below this Qdrant cosine-similarity score, a hit is treated as unrelated
# noise rather than a real match — keeps an off-topic question from forcing
# the LLM to awkwardly reason about irrelevant notes.
_SCORE_THRESHOLD = 0.3

# How many of the top retrieval hits get their full original_content pulled
# in (vs. just title/summary) — see the 2026-10-05 discussion in PROGRESS.md:
# full text only for the most relevant few keeps prompts short while still
# surfacing the detail a summary alone would have dropped.
_DETAIL_COUNT = 3

# Full-text excerpt length per detailed source, in characters.
_EXCERPT_CHARS = 3000


@dataclass
class RagSource:
    doc_id: str
    title: str | None
    score: float
    created_at: str | None


async def build_context(
    db: AsyncSession,
    model_router: ModelRouter,
    qdrant_client: Any,
    question: str,
    top_k: int = 5,
) -> tuple[str | None, list[RagSource]]:
    """Return (context_text, sources). context_text is None when nothing in
    the knowledge base clears the similarity threshold — caller should tell
    the user there's nothing relevant rather than asking an LLM to guess."""
    vector = await model_router.get_embedding(question)
    hits = await qdrant_client.search_similar(vector, limit=top_k)
    hits = [h for h in hits if h["score"] >= _SCORE_THRESHOLD]
    if not hits:
        return None, []

    doc_ids = [uuid.UUID(h["id"]) for h in hits]
    docs_by_id = await crud.get_documents_by_ids(db, doc_ids)

    blocks: list[str] = []
    sources: list[RagSource] = []
    for rank, hit in enumerate(hits):
        doc_id = uuid.UUID(hit["id"])
        doc = docs_by_id.get(doc_id)
        if doc is None:
            continue  # Qdrant point outlived its Postgres row (deleted doc)

        title = doc.title or "(未命名)"
        created = doc.created_at.date().isoformat() if doc.created_at else None
        header = f"[{rank + 1}] {title}" + (f"（{created}）" if created else "")

        if rank < _DETAIL_COUNT and doc.original_content:
            body = doc.original_content[:_EXCERPT_CHARS]
        else:
            body = doc.summary or ""

        blocks.append(f"{header}\n{body}")
        sources.append(
            RagSource(doc_id=str(doc_id), title=doc.title, score=hit["score"], created_at=created)
        )

    if not blocks:
        return None, []

    context_text = "\n\n---\n\n".join(blocks)
    return context_text, sources


def build_prompt(question: str, context_text: str) -> str:
    return (
        "你是使用者個人知識庫的問答助理。只能根據下面提供的資料回答問題；"
        "資料裡找不到答案時，直接說知識庫裡沒有相關資訊，不要編造。"
        "回答時可以用 [1][2] 這種編號引用對應的資料來源。"
        "回答請全部使用繁體中文撰寫，不要使用簡體中文或英文。"
        "專有名詞、產品名稱/型號、技術術語等翻譯會失真的內容，直接保留原文即可，"
        "但敘述本身必須是中文，不能整句都是英文或簡體字。\n\n"
        f"=== 知識庫資料 ===\n{context_text}\n\n"
        f"=== 問題 ===\n{question}"
    )
