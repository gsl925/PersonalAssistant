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

# A safety net against a genuinely stuck process (e.g. waiting on input
# despite stdin=DEVNULL, an infinite loop), not a normal ceiling — callers
# don't wait on this to decide "did the task finish," so it can afford to be
# generous. Real multi-step instructions (running several scripts in
# sequence, etc.) need real wall-clock room; a tight timeout here would kill
# legitimate work partway through for no benefit, since nobody's blocked on
# the result anyway (see project_sync.wake_now). Widened 300s -> 1800s ->
# 10800s (3h) as /wake instructions grew to include genuinely long-running
# work — there's no cost to a generous ceiling since it only ever fires on
# a real hang, never on legitimate completion.
_TIMEOUT_SECONDS = 10800.0

_WAKE_PROMPT = (
    "請檢查這個專案的 PROGRESS.md（如果有 SDD_PROGRESS_SYNC.md 就照它的規範），"
    "處理『📮 你的指示』區塊裡尚未勾選（- [ ]）的項目：自行判斷如何處理"
    "（回答問題、調整程式、或實際去做，可以讀寫檔案、執行指令），"
    "處理完後把對應項目改成 - [x]（不要刪除、不要改動文字，也不要動其他已經是 [x] 的舊項目）。"
    "如果這次工作階段有值得記錄的進度，也請更新『📋 進度回報』區塊的更新時間/今天完成/明天預計。"
)

# One-time onboarding turn for a brand-new tracked project — project_sync.
# add_project() already copied SDD_PROGRESS_SYNC.md into the repo before
# firing this, so the target session just needs to read it and act.
_BOOTSTRAP_PROMPT = (
    "這個專案剛被 Personal Assistant 加入追蹤，repo 根目錄已經有一份 SDD_PROGRESS_SYNC.md"
    "（跨專案進度同步協定規格）。請閱讀它，照規格在這個 repo 建立 PROGRESS.md（套用文件裡的模板）。"
    "同時把該協定對你的操作義務整理成一節加進這個專案的 CLAUDE.md"
    "（沒有就新建；已經有就新增一節，不要覆蓋既有內容）。"
    "完成後不用額外回報，下一次的 30 分鐘巡邏會自然讀到 PROGRESS.md。"
)


async def _run_claude(prompt: str, repo_path: str, timeout: float) -> dict:
    """Run one headless, fully-autonomous `claude -p` turn scoped to
    *repo_path*. Returns ``{"ok": True, "output": str}`` or
    ``{"ok": False, "error": str}``."""
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
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
        logger.error("claude -p timed out after {}s for {}", timeout, repo_path)
        return {"ok": False, "error": "逾時"}

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        logger.error("claude -p failed (exit {}) for {}: {}", proc.returncode, repo_path, err)
        return {"ok": False, "error": err or f"exit {proc.returncode}"}

    output = stdout.decode("utf-8", errors="replace").strip()
    return {"ok": True, "output": output}


async def wake_project(repo_path: str, timeout: float = _TIMEOUT_SECONDS) -> dict:
    """Ongoing "check your mailbox" turn — see module docstring."""
    result = await _run_claude(_WAKE_PROMPT, repo_path, timeout)
    if result["ok"]:
        logger.info("wake_project succeeded for {}: {:.200}", repo_path, result["output"])
    return result


async def bootstrap_project(repo_path: str, timeout: float = _TIMEOUT_SECONDS) -> dict:
    """One-time onboarding turn for a project project_sync.add_project()
    just started tracking — sets up PROGRESS.md/CLAUDE.md per
    SDD_PROGRESS_SYNC.md instead of processing an existing mailbox."""
    result = await _run_claude(_BOOTSTRAP_PROMPT, repo_path, timeout)
    if result["ok"]:
        logger.info("bootstrap_project succeeded for {}: {:.200}", repo_path, result["output"])
    return result
