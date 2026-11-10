"""The digest prompt templates go through str.format(); literal JSON braces in
them once raised KeyError: '"sections"' on every video, so keep them formattable."""
from __future__ import annotations

import asyncio

from backend import video_digest


def test_draft_prompt_formats_and_keeps_json_example():
    prompt = video_digest._DRAFT_PROMPT_TEMPLATE.format(title_line="標題：測試\n", transcript="[00:01] 你好")
    assert '{"sections"' in prompt
    assert "[00:01] 你好" in prompt


def test_judge_prompt_formats_and_keeps_json_example():
    prompt = video_digest._JUDGE_PROMPT_TEMPLATE.format(
        transcript="[00:01] 你好", draft_local="{}", draft_cloud="{}"
    )
    assert '{"sections"' in prompt
    assert "review_note" in prompt


def test_draft_parses_model_json():
    class FakeRouter:
        async def chat(self, tier, messages, **kwargs):
            assert '{"sections"' in messages[0]["content"]
            assert kwargs["response_format"] == {"type": "json_object"}
            return '```json\n{"sections": [{"heading": "h", "points": []}], "conclusion": "c"}\n```'

    result = asyncio.run(video_digest._draft(FakeRouter(), "fast_text", "[00:01] 你好", "t"))
    assert result is not None and result["sections"][0]["heading"] == "h"
