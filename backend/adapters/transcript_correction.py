"""Optional LLM correction pass over a whisper transcript.

Experimental, opt-in-by-caller: whisper's ASR errors (homophone slips on rare
technical jargon especially) sometimes look fixable from context, but an LLM
"fixing" them can just as easily replace a genuinely-correct rare term with a
more common but wrong one — confidently, with no visible sign anything
changed. That's *worse* than the original garbled text for anything used as
a factual record (meeting decisions, action items), since a human skimming a
fluent paragraph has no cue to double-check it. So this never overwrites
original_content — callers store the result in a separate
corrected_content column and keep both.
"""
from __future__ import annotations

import re

from loguru import logger

from backend.model_router import AllProvidersFailedError

# Conservative chunk size — this is plain-text-in/plain-text-out (unlike the
# rest of the pipeline's summarization calls, which compress a large input
# into a small structured output), so the same input length costs much more
# context budget here. Chunked independently with no shared memory between
# chunks, so a term that's ambiguous near a chunk boundary won't get fixed
# consistently across the whole document — a known limitation of this
# approach, not something worth solving before the experiment says this is
# worth keeping at all.
_CHUNK_SIZE = 1500

_CORRECTION_PROMPT_TEMPLATE = (
    "以下是語音辨識（ASR）自動轉錄出來的逐字稿片段，可能包含同音字造成的錯誤"
    "（尤其是專有名詞、技術術語）。請只修正明顯是辨識錯誤的地方，"
    "不要改寫句子結構、不要精簡、不要摘要、不要新增或刪除內容、"
    "不要調整任何數字、日期、人名，除非該處明顯是同音字誤植。"
    "如果不確定某處是否有錯，保持原樣不要動。"
    "直接輸出修正後的逐字稿，不要加任何說明、不要用 markdown 標記。\n\n"
    "逐字稿片段：\n{chunk}"
)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _chunk(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


async def correct_transcript(model_router, text: str) -> str | None:
    """Run *text* through the complex_reasoning tier in chunks, correcting
    likely ASR errors. Returns None on total failure (caller just won't have
    a corrected_content value — never blocks the main pipeline)."""
    chunks = _chunk(text.strip(), _CHUNK_SIZE)
    corrected_chunks: list[str] = []

    for i, chunk in enumerate(chunks):
        prompt = _CORRECTION_PROMPT_TEMPLATE.format(chunk=chunk)
        try:
            raw = await model_router.chat(
                "complex_reasoning",
                [{"role": "user", "content": prompt}],
                temperature=0,
            )
        except AllProvidersFailedError as exc:
            logger.warning("Transcript correction failed on chunk {}/{}: {}", i + 1, len(chunks), exc)
            return None

        cleaned = _THINK_BLOCK.sub("", raw).strip()
        corrected_chunks.append(cleaned)

    return "".join(corrected_chunks)
