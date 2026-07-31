"""Headless "wake up and process your mailbox" calls — triggered by
project_sync.py when a "📮 你的指示" item sits unprocessed too long.

Unlike claude_chat.py (pure Q&A, zero tools), this gives full autonomous
file-edit + Bash access scoped to the target project's own repo via
`--add-dir` + `cwd` — deliberately no confirmation gate
(`--permission-mode acceptEdits`), empirically verified to run Edit/Write/
Bash without hanging in headless mode. This is a meaningfully bigger trust
boundary than claude_chat.py, so project_sync.py only calls this for
projects with `auto_wake: true` in projects.yaml (opt-in per project).
"""
from __future__ import annotations

import asyncio

from loguru import logger

_TIMEOUT_SECONDS = 300.0

_WAKE_PROMPT = (
    "請檢查這個專案的 PROGRESS.md（如果有 SDD_PROGRESS_SYNC.md 就照它的規範），"
    "處理『📮 你的指示』區塊裡尚未勾選（- [ ]）的項目：自行判斷如何處理"
    "（回答問題、調整程式、或實際去做，可以讀寫檔案、執行指令），"
    "處理完後把對應項目改成 - [x]（不要刪除、不要改動文字，也不要動其他已經是 [x] 的舊項目）。"
    "如果這次工作階段有值得記錄的進度，也請更新『📋 進度回報』區塊的更新時間/今天完成/明天預計。"
)


async def wake_project(repo_path: str, timeout: float = _TIMEOUT_SECONDS) -> dict:
    """Run one headless, fully-autonomous `claude -p` turn scoped to
    *repo_path*. Returns ``{"ok": True, "output": str}`` or
    ``{"ok": False, "error": str}``."""
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", _WAKE_PROMPT,
        "--add-dir", repo_path,
        "--permission-mode", "acceptEdits",
        "--output-format", "text",
        "--no-session-persistence",
        cwd=repo_path,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.error("wake_project timed out after {}s for {}", timeout, repo_path)
        return {"ok": False, "error": "喚醒逾時"}

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        logger.error("wake_project failed (exit {}) for {}: {}", proc.returncode, repo_path, err)
        return {"ok": False, "error": err or f"exit {proc.returncode}"}

    output = stdout.decode("utf-8", errors="replace").strip()
    logger.info("wake_project succeeded for {}: {:.200}", repo_path, output)
    return {"ok": True, "output": output}
