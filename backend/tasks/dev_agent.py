"""Local dev-agent execution loop for factory-tools.

Unlike claude_wake.py (Claude Code, cloud) or claude_chat.py, this drafts and
writes the actual code change using a LOCAL Ollama model — deliberately no
cloud call for this stage, since factory source code/business data (SNs, CPU
model codes, folder structures, ...) shouldn't leave the machine just to
draft a script. Claude Code only enters afterward, as a review-only gate
(_run_review) that DOES have an approved cloud-fallback exception for its
own quota exhaustion — that exception is scoped to reviewing a diff, not to
drafting one.

Full autonomy, same trust boundary as claude_wake.py: the loop reads/writes
files and runs shell commands inside factory-tools with no confirmation gate.

Model is per-task (see run_dev_agent_task's local_model param), defaulting
to _DEFAULT_OLLAMA_MODEL, so the user can A/B different local models for
performance. Key implementation fact that still applies to any model chosen
(verified live for qwen3-coder:30b before writing this): tool calls only
come back as a structured `tool_calls` field via Ollama's NATIVE `/api/chat`
endpoint — the OpenAI-compatible `/v1/chat/completions` endpoint (what
ModelRouter uses) dumped a malformed pseudo-XML tag into `content` instead
for that model. This module talks to `/api/chat` directly rather than going
through ModelRouter — but a different model swapped in here isn't guaranteed
to support native tool-calling equally well; that's part of what the A/B is for.

Whether a multi-turn tool loop reliably terminates on this Ollama version is
NOT proven yet (one quick follow-up-turn test hung) — every per-call and
per-task limit below exists because of that, not just as generic caution.
"""
from __future__ import annotations

import asyncio
import difflib
import re
import subprocess
import uuid
from pathlib import Path

import httpx
from loguru import logger

from backend.config import settings
from backend.knowledge import crud
from backend.knowledge.db import async_session_maker

_DEFAULT_OLLAMA_MODEL = "qwen3-coder:30b"
_MAX_STEPS = 30
# Generous on purpose: a cold model swap on this machine (evicting whatever
# else is currently loaded, e.g. qwen2.5-coder:32b, then loading
# qwen3-coder:30b from disk) can itself take longer than a normal inference
# call — hit in practice on the first real smoke test (2026-09-08, timed out
# at 180s while something else was actively using Ollama). A generous ceiling
# costs nothing since it only ever matters when something's actually slow/
# stuck, same reasoning claude_wake.py's own timeout comment uses.
_PER_CALL_TIMEOUT = 300.0
_MAX_TASK_SECONDS = 1800.0  # 30 min — start conservative, this path is unproven
_RUN_COMMAND_TIMEOUT = 60.0
_CONFIDENCE_THRESHOLD = 0.6
# Low temperature on purpose — drafting/self-testing code is a task where we
# want deterministic, repeatable behavior, not creative variety.
_DRAFT_TEMPERATURE = 0.2
# How many times the loop will refuse the model's "I'm done" and force it to
# re-check against example_output before giving up and returning anyway —
# caps the cost of an example_output the model structurally can't satisfy
# (e.g. it's wrong, or the fuzzy check itself is too strict for this case).
_MAX_VERIFY_RETRIES = 2
# Fraction of example_output's distinctive tokens that must show up somewhere
# in the accumulated self-test log for a "done" claim to be trusted. Fuzzy on
# purpose — exact string equality would fail on harmless formatting/precision
# differences and just burn retries on a false negative.
_VERIFY_MATCH_THRESHOLD = 0.6

_SYSTEM_PROMPT = """你是在工廠做測試軟體開發的工程師（factory-tools 專案）。工廠 PASS/FAIL 判斷通常是「先執行程式/測試 → 產出真實 log → 解析那份 log 判斷結果」，不是憑空手動輸入數字。

規則：
1. 有參考資料路徑時，先用工具實際探索多個真實範例（不要只看第一個），把能從真實資料驗證的都驗證完，不要用 placeholder 硬猜格式。
2. 主動提出替代方案（例如「寫容錯程式碼」vs.「要求上游先整理資料」這類權衡），不要只執行第一個想到的做法。
3. 寫完之後，用 run_command 實際執行/測試你寫的東西，不要跳過自測就宣告完成。
4. 如果任務context裡有給「範例輸入/範例輸出」，那就是正確性的 ground truth：自測時務必實際跑一次範例輸入，確認產出跟範例輸出一致，不一致就還沒做完，不能宣告完成。
5. 完成後用一段純文字總結做了什麼（不要再呼叫任何工具）——這個總結後面會被另一個模型審查，所以要包含：改了哪些檔案、為什麼、自測結果是什麼（如果有範例輸入/輸出，要寫明自測是否對上）。
6. 如果需求裡有東西你判斷不出來、也沒辦法從資料裡驗證，就在最後的文字總結裡明確寫出「需要人類決定：...」，不要瞎猜硬做。
7. 所有檔案路徑都相對於 factory-tools repo 根目錄；要讀參考資料時，路徑前面加 "ref:"（例如 "ref:some/sub/dir"）。
8. 如果這次異動有實際寫入/修改 tools/ 底下的程式檔案，順手在同一個工具資料夾下建立或更新一份 SPEC.md（例如 tools/hello_check/SPEC.md）——用精簡的文字濃縮這個工具的用途、輸入、輸出、呼叫方式，讓不熟這個系統的人也能快速看懂，不需要另外寫 PRD/SDD 那種正式文件。
"""

_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List entries directly inside a directory (non-recursive). Prefix path with 'ref:' to look under the reference data root instead of the repo root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "Recursively search for files matching a glob pattern (e.g. '**/CinebenchResults.csv'). Prefix pattern with 'ref:' to search under the reference data root instead of the repo root.",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file's contents. Prefix path with 'ref:' to read from the reference data root instead of the repo root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write (create or overwrite) a text file inside the factory-tools repo. Path is always relative to the repo root — cannot write to the reference data root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command with cwd = the factory-tools repo root, to test what you just wrote. Use this before declaring the task done. This runs as a real shell with no path translation: the 'ref:' prefix does NOT work here — use the actual real absolute reference-data path given to you in the task context instead.",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        },
    },
]


class _ToolError(Exception):
    """A tool call failed in a way that should be reported back to the model
    as a tool result, not crash the whole loop."""


class _Sandbox:
    """Resolves and executes tool calls scoped to repo_path (read+write) and
    reference_path (read-only, addressed via a 'ref:' path prefix)."""

    def __init__(self, repo_path: Path, reference_path: Path | None):
        self.repo_path = repo_path
        self.reference_path = reference_path
        self.self_test_log: list[str] = []

    def _resolve(self, path_str: str, for_write: bool) -> Path:
        if path_str.startswith("ref:"):
            if for_write:
                raise _ToolError("The reference data root is read-only.")
            if self.reference_path is None:
                raise _ToolError("No reference data root was provided for this task.")
            root = self.reference_path
            rel = path_str[len("ref:"):].lstrip("/\\")
        else:
            root = self.repo_path
            rel = path_str.lstrip("/\\")

        resolved = (root / rel).resolve() if rel else root.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            raise _ToolError(f"Path '{path_str}' escapes the allowed root.") from None
        return resolved

    def list_dir(self, path: str) -> str:
        target = self._resolve(path, for_write=False)
        if not target.exists():
            return f"ERROR: '{path}' does not exist."
        if not target.is_dir():
            return f"ERROR: '{path}' is not a directory."
        entries = sorted(target.iterdir(), key=lambda p: p.name)
        lines = [f"{'[dir] ' if e.is_dir() else '[file]'} {e.name}" for e in entries]
        return "\n".join(lines) if lines else "(empty directory)"

    def glob_files(self, pattern: str) -> str:
        if pattern.startswith("ref:"):
            root = self.reference_path
            rel_pattern = pattern[len("ref:"):]
            if root is None:
                return "ERROR: No reference data root was provided for this task."
        else:
            root = self.repo_path
            rel_pattern = pattern

        # The model sometimes repeats the root's own absolute path after the
        # 'ref:'/root prefix (e.g. 'ref:C:\...\root\**\file.csv' where the
        # root itself is 'C:\...\root') instead of a pattern relative to it.
        # Strip that duplication rather than passing an absolute pattern
        # straight to Path.glob(), which raises NotImplementedError on
        # Python 3.13+ instead of just treating it as absolute.
        rel_pattern = rel_pattern.lstrip("/\\")
        root_str = str(root.resolve())
        normalized = rel_pattern.replace("/", "\\")
        if normalized.lower().startswith(root_str.lower()):
            rel_pattern = normalized[len(root_str):].lstrip("/\\")

        try:
            matches = list(root.glob(rel_pattern))[:200]
        except NotImplementedError:
            return (
                f"ERROR: '{pattern}' is not a valid relative pattern under the root. "
                "Don't repeat the root's own absolute path after the prefix — write the "
                "pattern relative to the root itself (e.g. 'ref:**/CinebenchResults.csv')."
            )
        if not matches:
            return "(no matches)"
        prefix = "ref:" if pattern.startswith("ref:") else ""
        return "\n".join(f"{prefix}{m.relative_to(root)}" for m in matches)

    def read_file(self, path: str) -> str:
        target = self._resolve(path, for_write=False)
        if not target.exists() or not target.is_file():
            return f"ERROR: '{path}' is not an existing file."
        try:
            return target.read_text(encoding="utf-8", errors="replace")[:20000]
        except Exception as exc:
            return f"ERROR reading '{path}': {exc}"

    def write_file(self, path: str, content: str) -> str:
        target = self._resolve(path, for_write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"OK: wrote {len(content)} chars to {path}"

    def run_command(self, cmd: str) -> str:
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=_RUN_COMMAND_TIMEOUT,
            )
            result = (
                f"exit_code={proc.returncode}\n"
                f"stdout:\n{(proc.stdout or '')[:4000]}\n"
                f"stderr:\n{(proc.stderr or '')[:4000]}"
            )
        except subprocess.TimeoutExpired:
            result = f"ERROR: command timed out after {_RUN_COMMAND_TIMEOUT}s"
        self.self_test_log.append(f"$ {cmd}\n{result}")
        return result

    def dispatch(self, name: str, args: dict) -> str:
        try:
            if name == "list_dir":
                return self.list_dir(args.get("path", ""))
            if name == "glob_files":
                return self.glob_files(args.get("pattern", ""))
            if name == "read_file":
                return self.read_file(args.get("path", ""))
            if name == "write_file":
                return self.write_file(args.get("path", ""), args.get("content", ""))
            if name == "run_command":
                return self.run_command(args.get("cmd", ""))
            return f"ERROR: unknown tool '{name}'"
        except _ToolError as exc:
            return f"ERROR: {exc}"
        except Exception as exc:
            logger.exception("Tool '{}' raised unexpectedly", name)
            return f"ERROR: {exc}"


async def _call_ollama_chat(messages: list[dict], model_name: str) -> dict:
    url = settings.OLLAMA_LOCAL_BASE_URL.rstrip("/") + "/api/chat"
    payload = {
        "model": model_name,
        "messages": messages,
        "tools": _TOOLS_SCHEMA,
        "stream": False,
        "options": {"temperature": _DRAFT_TEMPERATURE},
    }
    async with httpx.AsyncClient(timeout=_PER_CALL_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()


def _snapshot_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    snapshot: dict[str, str] = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root))
            try:
                snapshot[rel] = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                snapshot[rel] = "<binary or unreadable>"
    return snapshot


def _diff_snapshots(before: dict[str, str], after: dict[str, str]) -> tuple[str, set[str]]:
    """Returns (unified diff text, set of top-level folder names touched)."""
    changed_parts: list[str] = []
    touched_top: set[str] = set()
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key, ""), after.get(key, "")
        if a == b:
            continue
        touched_top.add(key.split("/")[0].split("\\")[0])
        diff = difflib.unified_diff(
            b.splitlines(keepends=True), a.splitlines(keepends=True),
            fromfile=f"a/{key}", tofile=f"b/{key}",
        )
        changed_parts.append("".join(diff))
    text = "\n".join(changed_parts) if changed_parts else "(no file changes detected)"
    return text, touched_top


def _self_test_matches_example(example_output: str, self_test_log: list[str]) -> bool:
    """Fuzzy, best-effort check that the model's own self-test run actually
    produced something resembling example_output — used to stop the loop
    from ending on the model's bare say-so (see rule 4 in _SYSTEM_PROMPT,
    which asks for this but has nothing checking it actually happened)."""
    tokens = list(dict.fromkeys(re.findall(r"[A-Za-z0-9_.\-]{3,}", example_output)))
    if not tokens:
        return True
    combined = "\n".join(self_test_log)
    found = sum(1 for t in tokens if t in combined)
    return (found / len(tokens)) >= _VERIFY_MATCH_THRESHOLD


def _fmt_checklist(label: str, items: list[str], detail: str | None = None) -> str | None:
    if not items:
        return None
    line = f"{label}：{'、'.join(items)}"
    if detail:
        line += f"（{detail}）"
    return line


async def _run_agent_loop(
    task_description: str,
    repo_path: Path,
    reference_path: Path | None,
    attachment_path: str | None,
    tools_context: str,
    model_name: str,
    task_type: str | None = None,
    example_input: str | None = None,
    example_output: str | None = None,
    input_source: list[str] | None = None,
    file_filter: list[str] | None = None,
    filter_detail: str | None = None,
    folder_depth: str | None = None,
    extraction_method: list[str] | None = None,
    calc_method: list[str] | None = None,
    exception_handling: list[str] | None = None,
    comparison_scope: list[str] | None = None,
    output_format: list[str] | None = None,
    completion_report: list[str] | None = None,
    result_format: str | None = None,
    keep_full_log: bool = True,
    additional_notes: str | None = None,
) -> tuple[str, _Sandbox]:
    """Runs the tool-calling loop until the model finishes or a hard limit
    is hit. Returns (final_summary_text, sandbox) — raises on abort."""
    sandbox = _Sandbox(repo_path, reference_path)

    user_parts = [f"任務需求：{task_description}"]
    if task_type:
        user_parts.append(f"任務類型：{task_type}")
    if reference_path is not None:
        user_parts.append(
            f"參考資料根目錄：{reference_path}\n"
            "－ list_dir / glob_files / read_file 這三個工具：用 'ref:' 前綴存取，後面接的路徑/pattern"
            "是相對於這個根目錄，不要再重複整個根目錄路徑（例如 'ref:**/CinebenchResults.csv' 是對的，"
            "'ref:" + str(reference_path) + "\\**\\CinebenchResults.csv' 是錯的，會失敗）。\n"
            "－ run_command 這個工具：是真的 shell，完全不認得 'ref:' 前綴，要用上面這個真實絕對路徑本身。"
        )
    if attachment_path:
        user_parts.append(f"使用者上傳的附件（repo 內相對路徑）：{attachment_path}")

    if example_input and example_output:
        user_parts.append(
            "範例輸入 → 範例輸出（這是正確性的 ground truth，自測時務必實際跑一次確認對上）：\n"
            f"範例輸入：\n{example_input}\n"
            f"範例輸出：\n{example_output}"
        )

    checklist_lines = [
        _fmt_checklist("INPUT-來源型態", input_source or []),
        _fmt_checklist("INPUT-檔案篩選", file_filter or [], filter_detail),
        f"INPUT-資料夾層級：{folder_depth}" if folder_depth else None,
        _fmt_checklist("邏輯-抓取方式", extraction_method or []),
        _fmt_checklist("邏輯-判斷計算", calc_method or []),
        _fmt_checklist("邏輯-例外處理", exception_handling or []),
        _fmt_checklist("邏輯-比較範圍", comparison_scope or []),
        _fmt_checklist("OUTPUT-交付格式", output_format or []),
        _fmt_checklist("OUTPUT-完成回報", completion_report or [], result_format),
        f"OUTPUT-除錯log：{'保留完整執行過程 log' if keep_full_log else '只在出錯時保留 log'}",
    ]
    checklist_lines = [line for line in checklist_lines if line]
    if checklist_lines:
        user_parts.append("使用者勾選的規格（沒列出的項目代表不需要）：\n" + "\n".join(checklist_lines))

    if additional_notes:
        user_parts.append(f"補充說明：{additional_notes}")

    user_parts.append(tools_context)

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    deadline = asyncio.get_event_loop().time() + _MAX_TASK_SECONDS
    verify_retries_used = 0
    for step in range(_MAX_STEPS):
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"Exceeded {_MAX_TASK_SECONDS}s wall-clock budget after {step} step(s).")

        try:
            data = await _call_ollama_chat(messages, model_name)
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            raise TimeoutError(f"Ollama call failed/timed out at step {step}: {exc}") from exc

        message = data.get("message", {})
        tool_calls = message.get("tool_calls") or []
        messages.append(message)

        if not tool_calls:
            content = message.get("content", "").strip()
            if (
                example_output
                and verify_retries_used < _MAX_VERIFY_RETRIES
                and step < _MAX_STEPS - 1
                and not _self_test_matches_example(example_output, sandbox.self_test_log)
            ):
                verify_retries_used += 1
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "自動比對發現你的自測結果跟範例輸出對不太起來——"
                            "請重新檢查邏輯，並用 run_command 再實際跑一次範例輸入，"
                            "確認輸出真的符合範例輸出後才能結束（不要只是重複宣告已經測過）。"
                        ),
                    }
                )
                continue
            return content, sandbox

        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                import json
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            logger.info("dev_agent tool call: {}({})", name, args)
            result = sandbox.dispatch(name, args)
            messages.append({"role": "tool", "content": result})

    raise TimeoutError(f"Exceeded {_MAX_STEPS} tool-call steps without finishing.")


async def run_dev_agent_task(
    *,
    project_name: str,
    task_description: str,
    repo_path: str,
    target_tool_name: str | None = None,
    new_tool_name: str | None = None,
    reference_path: str | None = None,
    attachment_path: str | None = None,
    task_type: str | None = None,
    example_input: str | None = None,
    example_output: str | None = None,
    input_source: list[str] | None = None,
    file_filter: list[str] | None = None,
    filter_detail: str | None = None,
    folder_depth: str | None = None,
    extraction_method: list[str] | None = None,
    calc_method: list[str] | None = None,
    exception_handling: list[str] | None = None,
    comparison_scope: list[str] | None = None,
    output_format: list[str] | None = None,
    completion_report: list[str] | None = None,
    result_format: str | None = None,
    keep_full_log: bool = True,
    additional_notes: str | None = None,
    local_model: str | None = None,
    notify: str = "default",
) -> dict:
    """Entry point — fire-and-forget background task, called right after a
    dev-task form submission. Drafts+writes+self-tests via the local model,
    then hands off to Claude Code (_run_review) for the confidence gate."""
    from backend.tasks.project_sync import write_instruction

    model_name = local_model or _DEFAULT_OLLAMA_MODEL
    drafted_by = f"{model_name}-local"

    repo = Path(repo_path)
    ref = Path(reference_path) if reference_path else None
    tools_root = repo / "tools"

    async with async_session_maker() as db:
        existing_tools = await crud.list_tools(db)
    tools_context_lines = [f"- {t.name}（{t.repo_relative_path}）：{t.description or ''}" for t in existing_tools]
    if target_tool_name:
        tools_context = f"使用者已指定目標工具：{target_tool_name}（在 tools/{target_tool_name}/ 下修改）。"
    elif new_tool_name:
        tools_context = f"使用者要求建立新工具，建議資料夾：tools/{new_tool_name}/。"
    else:
        tools_context = (
            "使用者沒有指定目標工具。現有工具列表：\n" + ("\n".join(tools_context_lines) or "（目前沒有任何工具）")
            + "\n請自行判斷這是修改既有工具還是要新建一個（新建的話，在 tools/ 下取一個合理的資料夾名稱）。"
        )

    before_snapshot = _snapshot_tree(tools_root)

    try:
        summary, sandbox = await _run_agent_loop(
            task_description, repo, ref, attachment_path, tools_context,
            model_name,
            task_type=task_type,
            example_input=example_input, example_output=example_output,
            input_source=input_source, file_filter=file_filter, filter_detail=filter_detail,
            folder_depth=folder_depth,
            extraction_method=extraction_method, calc_method=calc_method,
            exception_handling=exception_handling, comparison_scope=comparison_scope,
            output_format=output_format, completion_report=completion_report,
            result_format=result_format, keep_full_log=keep_full_log,
            additional_notes=additional_notes,
        )
    except Exception as exc:
        logger.error("dev_agent task aborted for '{}': {}", project_name, exc)
        await write_instruction(
            project_name,
            f"dev-agent（{model_name}）自動執行失敗（{exc}）——原始需求：{task_description}",
        )
        return {"status": "aborted", "error": str(exc)}

    after_snapshot = _snapshot_tree(tools_root)
    diff_text, touched_top = _diff_snapshots(before_snapshot, after_snapshot)

    tool_slug = target_tool_name or new_tool_name or (sorted(touched_top)[0] if touched_top else None)
    if tool_slug is None:
        logger.warning(
            "dev_agent task for '{}' produced no file changes. Model summary: {}",
            project_name, summary,
        )
        summary_text = (summary or "（local model 沒有留下文字總結）")[:1500]
        await write_instruction(
            project_name,
            f"dev-agent（{model_name}）執行完成但沒有偵測到任何檔案變更，需要人工檢查——原始需求：{task_description}"
            f"｜模型結束前的總結：{summary_text}",
        )
        return {"status": "no_changes", "summary": summary}

    async with async_session_maker() as db:
        tool = await crud.get_tool_by_name(db, tool_slug)
        if tool is None:
            tool = await crud.create_tool(
                db,
                name=tool_slug,
                display_name=tool_slug,
                repo_relative_path=f"tools/{tool_slug}",
                reference_path=reference_path,
            )
        self_test_result = "\n\n".join(sandbox.self_test_log) or "(local model 沒有呼叫 run_command 自測)"
        change_log = await crud.create_tool_change_log(
            db,
            tool_id=tool.id,
            change_summary=summary or "(local model 沒有留下文字總結)",
            change_reason=task_description,
            diff_text=diff_text,
            drafted_by=drafted_by,
            self_test_result=self_test_result,
            reference_path=reference_path,
        )
        await db.commit()
        change_log_id = change_log.id

    review = await _run_review(
        change_log_id=change_log_id,
        repo_path=repo,
        change_summary=summary,
        diff_text=diff_text,
        self_test_result=self_test_result,
    )

    if notify == "default":
        await _notify_result(tool_slug, review, model_name)

    return {"status": "completed", "tool": tool_slug, "review": review}


_CONFIDENCE_RE = re.compile(r"CONFIDENCE:\s*([0-9.]+)", re.IGNORECASE)
_VERDICT_RE = re.compile(r"VERDICT:\s*(landed|blocked)", re.IGNORECASE)

_REVIEW_PROMPT_TEMPLATE = """你是資深工程師，正在審查一個工廠測試工具的變更，這個變更由一個 local 模型自動草擬完成，你的工作是把關。

變更摘要：
{change_summary}

Diff：
{diff_text}

自測結果：
{self_test_result}

請檢查這個 diff 是否合理、有沒有明顯錯誤或遺漏，必要時可以自己在這個 repo 底下讀檔案/執行指令驗證。最後，在回覆的最後兩行，精確用這個格式輸出（不要有其他文字混在這兩行）：
CONFIDENCE: <0.0 到 1.0 之間的數字>
VERDICT: <landed 或 blocked>
"""


async def _run_review(
    change_log_id: uuid.UUID,
    repo_path: Path,
    change_summary: str,
    diff_text: str,
    self_test_result: str,
) -> dict:
    from backend.tasks.claude_wake import _run_claude

    prompt = _REVIEW_PROMPT_TEMPLATE.format(
        change_summary=change_summary[:4000],
        diff_text=diff_text[:8000],
        self_test_result=self_test_result[:4000],
    )

    review_source = "claude-code"
    result = await _run_claude(prompt, str(repo_path), timeout=600.0)
    output = result.get("output", "") if result.get("ok") else ""

    if not result.get("ok"):
        logger.warning("Claude Code review failed ({}), falling back to cloud tier.", result.get("error"))
        try:
            from backend.main import get_model_router

            router = get_model_router()
            output = await router.chat("complex_reasoning", [{"role": "user", "content": prompt}])
            review_source = "cloud-fallback:complex_reasoning"
        except Exception as exc:
            logger.error("Review cloud fallback also failed: {}", exc)
            output = ""

    confidence_match = _CONFIDENCE_RE.search(output)
    verdict_match = _VERDICT_RE.search(output)
    if confidence_match and verdict_match:
        confidence = max(0.0, min(1.0, float(confidence_match.group(1))))
        verdict = verdict_match.group(1).lower()
    else:
        confidence = 0.0
        verdict = "blocked"
        output = (output or "") + "\n\n(審查回覆無法解析出 CONFIDENCE/VERDICT，預設視為 blocked。)"

    status = "landed" if (verdict == "landed" and confidence >= _CONFIDENCE_THRESHOLD) else "blocked"
    blocked_reason = None if status == "landed" else output[-1000:]

    async with async_session_maker() as db:
        await crud.update_tool_change_log_review(
            db,
            change_log_id=change_log_id,
            review_source=review_source,
            confidence_score=confidence,
            status=status,
            blocked_reason=blocked_reason,
        )
        await db.commit()

    return {
        "status": status,
        "confidence": confidence,
        "review_source": review_source,
        "reason": blocked_reason,
    }


async def _notify_result(tool_slug: str, review: dict, model_name: str) -> None:
    from backend.tasks.project_sync import _send_relay

    icon = "✅" if review["status"] == "landed" else "⚠️"
    text = (
        f"{icon} dev-agent（{model_name}）完成「{tool_slug}」\n"
        f"狀態：{review['status']}（信心分數 {review['confidence']:.2f}，審查來源 {review['review_source']}）"
    )
    if review.get("reason"):
        text += f"\n{review['reason'][:500]}"
    try:
        await _send_relay(text)
    except Exception as exc:
        logger.error("Failed to send dev-agent result notification: {}", exc)
