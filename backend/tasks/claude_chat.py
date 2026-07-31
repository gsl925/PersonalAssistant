"""One-off headless Claude Code chat calls — see the `/ask` Telegram command
in telegram_bot.py.

Not a coding agent: `--tools` restricts availability to WebSearch/WebFetch
only — no repo/file reads, no bash, no edits — and `--allowedTools`
pre-approves exactly those two so headless mode (no TTY to prompt) doesn't
auto-deny them. `--no-session-persistence` keeps each call stateless so it
never grows or leaks context across questions. Deliberately omits `--bare`
— that mode requires a separate ANTHROPIC_API_KEY, which isn't configured
here; without it, the CLI reuses whatever `claude login` already
authenticated on this machine (subscription/OAuth), same as the interactive
session.
"""
from __future__ import annotations

import asyncio

from loguru import logger

_TIMEOUT_SECONDS = 120.0
_ALLOWED_TOOLS = "WebSearch,WebFetch"


async def ask_claude(question: str, timeout: float = _TIMEOUT_SECONDS) -> dict:
    """Run `claude -p` headless for a single stateless Q&A turn.

    Returns ``{"ok": True, "answer": str}`` on success, or
    ``{"ok": False, "error": str}`` on failure/timeout — the caller decides
    how to surface that (Telegram reply, failed Document row, etc.).
    """
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", question,
        "--tools", _ALLOWED_TOOLS,
        "--allowedTools", _ALLOWED_TOOLS,
        "--output-format", "text",
        "--no-session-persistence",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.error("claude -p timed out after {}s for question: {:.60}", timeout, question)
        return {"ok": False, "error": "回答逾時，請稍後再試。"}

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        logger.error("claude -p failed (exit {}): {}", proc.returncode, err)
        if "not logged in" in err.lower():
            message = "這台機器上的 Claude Code 還沒登入，請先執行 `claude login`。"
        else:
            message = err or f"claude -p 失敗（exit {proc.returncode}）"
        return {"ok": False, "error": message}

    answer = stdout.decode("utf-8", errors="replace").strip()
    if not answer:
        return {"ok": False, "error": "沒有收到回覆內容。"}
    return {"ok": True, "answer": answer}
