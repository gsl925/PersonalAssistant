"""Insight extraction — "what is the author actually arguing," not a summary.

Deliberately separate from webclip-agent's SKILL.md-driven prompt: that one
is restatement-oriented (summary/key_points/category, meant to feed search
and browsing). This one asks specifically for the author's core
argument/thesis/stance, and is used by the insight-preview flow (see
Orchestrator.preview_insight) which runs BEFORE any decision to save — it
intentionally does not go through the skill/agent pipeline or
normalize_agent_output, since there's no output_schema/agent_name concept
here, just a single ad hoc structured call (same idiom as
Orchestrator.extract_todo_fields/classify_todo_intent).
"""
from __future__ import annotations

import json
import re

from loguru import logger

from backend.model_router import AllProvidersFailedError

# Matches webclip-agent's own truncation convention (orchestrator.py) — keeps
# latency/context cost comparable rather than letting this one call balloon
# on long transcripts.
_MAX_CONTENT_CHARS = 4000

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

_INSIGHT_PROMPT_TEMPLATE = (
    "以下是一篇文章或影片逐字稿。請找出作者真正想傳達的核心觀點、立場，或想讓讀者/"
    "觀眾思考的問題——不是要你重述內容或列重點，是要指出「作者到底在主張什麼」。"
    "如果內容本身沒有明顯的觀點或論點（純資訊性、教學步驟等），就直接說明這點，"
    "不要硬generate一個不存在的論點。"
    "只根據內容裡實際出現的資訊做判斷與推論，不要提及、舉例或發明內容中沒有明確出現的"
    "具體技術細節、數字或項目——寧可講得保守籠統，也不要講出聽起來專業但無法從原文核實的細節。\n\n"
    "{title_line}"
    "內容：\n{content}\n\n"
    "請回覆純 JSON（不要加 markdown 標記）：\n"
    '{{"insight": "<核心觀點，2-4 句話，繁體中文>"}}\n'
    "insight 請使用繁體中文撰寫，不要使用簡體中文或英文（專有名詞可保留原文）。"
)


async def extract_insight(model_router, content: str, title: str | None = None) -> dict:
    """Returns ``{"insight": str}``. Never raises — on failure, returns a
    fallback message so callers (preview_insight) can still show *something*
    rather than erroring out the whole preview over a single LLM hiccup."""
    title_line = f"標題：{title}\n" if title else ""
    prompt = _INSIGHT_PROMPT_TEMPLATE.format(
        title_line=title_line, content=content[:_MAX_CONTENT_CHARS]
    )
    try:
        raw = await model_router.chat(
            "insight_extraction", [{"role": "user", "content": prompt}], temperature=0.2,
        )
        cleaned = _THINK_BLOCK.sub("", raw).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            data = json.loads(match.group())
            insight = str(data.get("insight") or "").strip()
            if insight:
                return {"insight": insight}
    except (AllProvidersFailedError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Insight extraction failed: {}", exc)
    return {"insight": "（無法產生洞察，請稍後再試或直接查看原文）"}
