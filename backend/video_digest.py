"""Long-form, sectioned video digest with timestamp citations and a
self-assessed confidence score — additive to webclip-agent's own short
summary/key_points, not a replacement for them (Telegram notifications and
RAG indexing still read the webclip-agent output; this feeds a separate
Dashboard-only block, see Orchestrator._execute_and_save).

Mirrors backend/tasks/dev_agent.py's draft→review split, applied to content
instead of code: a local model and a cloud model each draft independently
(so one can't silently fall back to the other and defeat the comparison —
see the video_digest_local/video_digest_cloud tiers in backend/config.py),
then headless Claude Code (`claude -p`, via claude_wake.py's _run_claude)
judges the two drafts against the source transcript and produces the final
sectioned digest plus a 0-100 confidence score. Degrades gracefully at every
step (see generate_video_digest's docstring) — a failure here must never
fail the document's own save.
"""
from __future__ import annotations

import asyncio
import json
import re

from loguru import logger

from backend.model_router import AllProvidersFailedError

# Generous relative to webclip-agent's/insight.py's 4000-char truncation —
# this task's whole point is a long-form breakdown, not a quick blurb, so it
# needs the (near-)full transcript. Still bounded against a pathological
# multi-hour transcript blowing out context/latency.
_MAX_TRANSCRIPT_CHARS = 14000

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

_DIGEST_SCHEMA_HINT = (
    '{"sections": [{"heading": "<依內容動態歸類的章節標題，繁體中文>", '
    '"points": [{"text": "<重點內容，繁體中文，專有名詞/型號可保留原文>", '
    '"timestamp": "<逐字稿裡實際出現過的 MM:SS，找不到就填 null>"}]}], '
    '"conclusion": "<總結/定位評價，2-4 句話，繁體中文>", '
    '"self_confidence": <0 到 100 的整數，你對這份摘要內容正確性的自評信心>}'
)

_DRAFT_PROMPT_TEMPLATE = (
    "以下是一部影片的逐字稿，每行開頭是 [MM:SS] 格式的真實時間戳記。"
    "請把內容整理成分章節的重點報告：章節標題依內容本身動態歸類"
    "（例如規格、效能測試、使用體驗、結論等，不要套用固定分類），"
    "每個重點盡量附上它在逐字稿裡最接近的時間戳記——"
    "時間戳記必須是逐字稿裡真實出現過的 [MM:SS]，絕對不可以自己編造或推算。"
    "最後给一個總結/定位評價，並對整份摘要的內容正確性自評一個 0-100 的信心分數"
    "（根據逐字稿內容是否清楚、完整、有沒有模糊不確定之處來判斷，不是隨便給高分）。"
    "{title_line}"
    "逐字稿：\n{transcript}\n\n"
    "請只回覆純 JSON（不要加 markdown 標記、不要有其他文字），格式為：\n"
    # Braces doubled: this template goes through str.format() below, and the
    # JSON example's literal { } would otherwise be read as format fields.
    f"{_DIGEST_SCHEMA_HINT.replace('{', '{{').replace('}', '}}')}\n"
    "所有文字欄位（heading/text/conclusion）必須是繁體中文，不要使用簡體中文或英文"
    "（專有名詞、產品型號、技術術語可保留原文）。"
)

_JUDGE_PROMPT_TEMPLATE = (
    "你是內容查核編輯。以下是一部影片的逐字稿，以及兩個不同模型各自獨立產出的重點整理草稿"
    "（草稿 A 來自本地模型，草稿 B 來自雲端模型）。"
    "請對照逐字稿，比較兩份草稿的正確性與完整度，挑選較好的內容、或合併兩者的優點，"
    "產出一份最終版重點整理。特別注意：每個重點附帶的時間戳記 [MM:SS] 必須對照逐字稿核實"
    "是真的在那個時間點附近提到的，不可以沿用草稿裡錯誤或編造的時間戳記。"
    "最後對這份最終版的內容正確性給一個 0-100 的信心分數，以及一句話的評語"
    "（例如為什麼信心高/低、主要參考了哪份草稿）。\n\n"
    "逐字稿：\n{transcript}\n\n"
    "草稿 A（本地模型）：\n{draft_local}\n\n"
    "草稿 B（雲端模型）：\n{draft_cloud}\n\n"
    "請只回覆純 JSON（不要加 markdown 標記、不要有其他文字），格式為：\n"
    '{{"sections": [{{"heading": "...", "points": [{{"text": "...", "timestamp": "MM:SS 或 null"}}]}}], '
    '"conclusion": "...", "confidence_score": <0-100整數>, "review_note": "<一句話評語，繁體中文>"}}\n'
    "所有文字欄位必須是繁體中文（專有名詞可保留原文）。"
)


def _parse_json(raw: str) -> dict | None:
    cleaned = _THINK_BLOCK.sub("", raw).strip()
    match = _JSON_BLOCK.search(cleaned)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed.get("sections"), list) else None


def _clamp_confidence(value: object) -> int | None:
    try:
        return max(0, min(100, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def _draft(model_router, tier: str, transcript: str, title: str | None) -> dict | None:
    title_line = f"標題：{title}\n" if title else ""
    prompt = _DRAFT_PROMPT_TEMPLATE.format(
        title_line=title_line, transcript=transcript[:_MAX_TRANSCRIPT_CHARS]
    )
    try:
        # response_format makes llama.cpp (and Ollama's /v1) constrain decoding to
        # valid JSON; without it deepseek-r1:14b broke the JSON or drifted into
        # Simplified Chinese on ~2 of 7 real transcripts.
        raw = await model_router.chat(
            tier,
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except AllProvidersFailedError as exc:
        logger.warning("video_digest draft failed for tier '{}': {}", tier, exc)
        return None

    parsed = _parse_json(raw)
    if parsed is None:
        logger.warning("video_digest draft for tier '{}' returned unparseable output", tier)
        return None
    return parsed


async def _judge(
    transcript: str, draft_local: dict, draft_cloud: dict, repo_path: str
) -> dict | None:
    from backend.tasks.claude_wake import _run_claude

    prompt = _JUDGE_PROMPT_TEMPLATE.format(
        transcript=transcript[:_MAX_TRANSCRIPT_CHARS],
        draft_local=json.dumps(draft_local, ensure_ascii=False),
        draft_cloud=json.dumps(draft_cloud, ensure_ascii=False),
    )
    result = await _run_claude(prompt, repo_path, timeout=600.0)
    if not result.get("ok"):
        logger.warning("video_digest Claude judge call failed: {}", result.get("error"))
        return None

    judged = _parse_json(result["output"])
    if judged is None:
        logger.warning("video_digest Claude judge returned unparseable output")
        return None

    confidence = _clamp_confidence(judged.get("confidence_score"))
    if confidence is None:
        return None
    judged["confidence_score"] = confidence
    judged["review_source"] = "claude-judge"
    return judged


async def generate_video_digest(
    model_router, transcript: str, title: str | None, repo_path: str
) -> dict:
    """Returns a dict always containing ``status`` plus (on anything but a
    full failure) ``sections``/``conclusion``/``confidence_score``/
    ``review_source``. Never raises — every failure mode degrades to the
    next-best thing rather than blocking the caller's document save:

    - both drafts succeed, Claude judge succeeds → judge's merged result
      (``status: "judged"``)
    - both drafts succeed, Claude judge fails/unavailable → whichever draft
      self-reported higher confidence (``status: "fallback"``)
    - only one draft succeeds → that draft as-is (``status: "single-draft"``)
    - both drafts fail → empty result (``status: "failed"``)
    """
    if not transcript or not transcript.strip():
        return {"status": "failed", "sections": [], "conclusion": None, "confidence_score": None}

    draft_local, draft_cloud = await asyncio.gather(
        _draft(model_router, "video_digest_local", transcript, title),
        _draft(model_router, "video_digest_cloud", transcript, title),
    )

    if draft_local is None and draft_cloud is None:
        return {"status": "failed", "sections": [], "conclusion": None, "confidence_score": None}

    if draft_local is None or draft_cloud is None:
        only = draft_local if draft_local is not None else draft_cloud
        source = "cloud-only" if draft_local is None else "local-only"
        return {
            "status": "single-draft",
            "sections": only.get("sections", []),
            "conclusion": only.get("conclusion"),
            "confidence_score": _clamp_confidence(only.get("self_confidence")),
            "review_source": source,
        }

    judged = await _judge(transcript, draft_local, draft_cloud, repo_path)
    if judged is not None:
        return {
            "status": "judged",
            "sections": judged.get("sections", []),
            "conclusion": judged.get("conclusion"),
            "confidence_score": judged.get("confidence_score"),
            "review_source": "claude-judge",
            "review_note": judged.get("review_note"),
        }

    local_conf = _clamp_confidence(draft_local.get("self_confidence")) or 0
    cloud_conf = _clamp_confidence(draft_cloud.get("self_confidence")) or 0
    winner, source = (
        (draft_local, "local-fallback")
        if local_conf >= cloud_conf
        else (draft_cloud, "cloud-fallback")
    )
    return {
        "status": "fallback",
        "sections": winner.get("sections", []),
        "conclusion": winner.get("conclusion"),
        "confidence_score": _clamp_confidence(winner.get("self_confidence")),
        "review_source": source,
    }
