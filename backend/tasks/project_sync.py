"""Cross-project PROGRESS.md sync — see SDD_PROGRESS_SYNC.md.

Personal Assistant is a mailman here, not an executor: it only reads/writes
each tracked project's PROGRESS.md and relays to/from Telegram. It never
invokes the `claude` CLI or executes anything — actual judgment and
execution always happen inside that project's own Claude Code session,
per the SDD handed to each tracked project.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

from backend.config import TrackedProject, load_tracked_projects, settings
from backend.tasks.processing import _send_telegram

_TAIPEI = ZoneInfo("Asia/Taipei")

PROGRESS_FILENAME = "PROGRESS.md"
# Permanent, git-tracked record of resolved 💬/📮 exchanges — unlike
# PROGRESS.md (live, gitignored, constantly overwritten), this only ever
# grows, one entry per resolved decision, so the project keeps a durable
# log of what was discussed and decided even after PROGRESS.md moves on.
HISTORY_FILENAME = "PROGRESS_HISTORY.md"

_REPORT_HEADER = "## 📋 進度回報"
_DISCUSS_HEADER = "## 💬 待溝通 / 建議"
_INSTRUCT_HEADER = "## 📮 你的指示"
_SECTION_HEADERS = [_REPORT_HEADER, _DISCUSS_HEADER, _INSTRUCT_HEADER]

# How many sync cycles (see sync_all_projects) a "💬 待溝通/建議" item can
# sit relayed-but-undecided before it gets escalated into a Dashboard todo
# so it doesn't quietly get lost in Telegram scroll.
_ESCALATE_AFTER_CYCLES = 4  # ~2 hours at the 30-minute poll interval

_BULLET_PATTERN = re.compile(r"^- \[( |x)\] (.*)$")
_UPDATED_AT_PATTERN = re.compile(r"- 更新時間:[ \t]*(.*)")
# A reply that starts with a number targets that specific 💬 item (see the
# "#N 需要你決定" tag on each relayed message) — e.g. "1. 好，加進去" or "1 好".
_REPLY_NUMBER_PATTERN = re.compile(r"^\s*#?(\d+)[.:、\s]+(.*)$", re.DOTALL)


def _progress_path(project: TrackedProject) -> Path:
    return Path(project.repo_path) / PROGRESS_FILENAME


def _history_path(project: TrackedProject) -> Path:
    return Path(project.repo_path) / HISTORY_FILENAME


def _append_history(project: TrackedProject, discuss_content: str, decision_text: str) -> None:
    path = _history_path(project)
    today = datetime.now(_TAIPEI).date().isoformat()
    entry = f"## {today} — {project.label}\n- **待溝通**：{discuss_content}\n- **決策**：{decision_text}\n\n"
    if not path.exists():
        path.write_text(f"# {project.label} 進度同步歷史紀錄\n\n{entry}", encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)


async def _send_relay(text: str) -> None:
    """Send to the user's private/replyable chat with the bot (needed here
    since "💬 待溝通/建議" and "📋 進度回報" both expect a reply back), not the
    broadcast-only TELEGRAM_CHAT_ID digest channel that _send_telegram()
    defaults to. Falls back to that channel if the bot isn't up yet (e.g.
    this runs as a background task that can fire before the bot finishes
    starting) or TELEGRAM_BOT_TOKEN isn't configured at all."""
    try:
        from backend.main import get_telegram_bot

        await get_telegram_bot().send_message(text)
    except RuntimeError:
        await _send_telegram(text)


def _split_sections(text: str) -> dict[str, str]:
    """Split on the three fixed ## headers. Missing headers just yield an
    empty section rather than raising — a malformed file should degrade to
    "nothing to relay today", not crash the whole sync cycle."""
    sections: dict[str, str] = {h: "" for h in _SECTION_HEADERS}
    positions = [(h, text.find(h)) for h in _SECTION_HEADERS]
    found = sorted((pos, h) for h, pos in positions if pos != -1)
    for i, (pos, header) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(text)
        sections[header] = text[pos + len(header) : end].strip()
    return sections


def _extract_updated_at(report_section: str) -> str | None:
    match = _UPDATED_AT_PATTERN.search(report_section)
    value = match.group(1).strip() if match else ""
    return value or None


def _extract_bullets(section_text: str) -> list[dict]:
    bullets = []
    for line in section_text.splitlines():
        match = _BULLET_PATTERN.match(line.strip())
        if match:
            bullets.append({"checked": match.group(1) == "x", "raw_line": line, "content": match.group(2)})
    return bullets


# ---------------------------------------------------------------------------
# Per-project sync state (data/project_progress_state.json)
# ---------------------------------------------------------------------------


def _state_path() -> Path:
    return settings.BASE_DIR / "data" / "project_progress_state.json"


def _read_state() -> dict:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _project_state(state: dict, project_name: str) -> dict:
    pstate = state.setdefault(project_name, {})
    pstate.setdefault("cycle", 0)
    pstate.setdefault("last_report_time", None)
    pstate.setdefault("awaiting_decision", [])
    pstate.setdefault("next_item_number", 1)
    return pstate


async def _relay_discuss_items(project: TrackedProject, full_text: str, pstate: dict) -> None:
    """Send Telegram for any not-yet-relayed unchecked "💬" bullet, tagged
    with a stable #N so a later reply can target it precisely (see
    write_instruction) — without a number, one reply would ambiguously
    resolve every open item for the project at once. Does NOT check the box
    itself — the checkbox only flips once write_instruction actually
    resolves that specific item. Re-relay is prevented via
    pstate['awaiting_decision'] tracking, not via the file, so an
    already-relayed, still-unresolved item quietly stays `[ ]` without being
    re-sent to Telegram every cycle."""
    sections = _split_sections(full_text)
    already_tracked = {item["content"] for item in pstate["awaiting_decision"]}
    for bullet in _extract_bullets(sections[_DISCUSS_HEADER]):
        if bullet["checked"] or bullet["content"] in already_tracked:
            continue
        number = pstate["next_item_number"]
        pstate["next_item_number"] = number + 1
        await _send_relay(f"💬 [{project.label}] #{number} 需要你決定：{bullet['content']}\n\n#{project.name}")
        pstate["awaiting_decision"].append(
            {
                "number": number,
                "content": bullet["content"],
                "raw_line": bullet["raw_line"],
                "relayed_at_cycle": pstate["cycle"],
                "escalated": False,
            }
        )


async def _maybe_relay_report(project: TrackedProject, full_text: str, pstate: dict) -> None:
    sections = _split_sections(full_text)
    updated_at = _extract_updated_at(sections[_REPORT_HEADER])
    if not updated_at or updated_at == pstate.get("last_report_time"):
        return
    await _send_relay(
        f"📋 [{project.label}] 進度更新\n\n{sections[_REPORT_HEADER]}\n\n#{project.name}"
    )
    pstate["last_report_time"] = updated_at


async def _escalate_stale_discuss_items(project: TrackedProject, pstate: dict) -> None:
    """Once an item has sat unresolved for _ESCALATE_AFTER_CYCLES cycles,
    escalate it into a Dashboard todo *once* as a fallback reminder — but
    keep tracking it (don't touch the file), so a late reply via
    write_instruction still resolves and checks it off normally; escalation
    just means "also remind me on the Dashboard," not "give up on this."
    """
    to_escalate = [
        item
        for item in pstate["awaiting_decision"]
        if not item["escalated"] and pstate["cycle"] - item["relayed_at_cycle"] >= _ESCALATE_AFTER_CYCLES
    ]
    if not to_escalate:
        return
    for item in to_escalate:
        item["escalated"] = True

    try:
        from backend.main import get_orchestrator

        orchestrator = get_orchestrator()
        pending_items = [
            {"content": f"[{project.label}] {item['content']}", "due_date": None}
            for item in to_escalate
        ]
        created = await orchestrator.sync_project_todos(project.name, pending_items)
        if created:
            logger.info("Escalated {} unresolved item(s) from {} to a todo.", created, project.name)
    except Exception as exc:
        # Don't lose track of these — retry escalating them next cycle
        # instead of silently dropping them because e.g. the orchestrator
        # wasn't ready.
        logger.error("Failed to escalate stale item(s) for {}: {}", project.name, exc)
        for item in to_escalate:
            item["escalated"] = False


async def write_instruction(project_name: str, text: str) -> bool:
    """Called by telegram_bot.py when the user replies with a project's
    hashtag — appends *text* as a new unchecked line under "📮 你的指示".
    Returns False if the project is unknown or has no PROGRESS.md yet.

    "📮 你的指示" is always the LAST section in the fixed template (see
    SDD_PROGRESS_SYNC.md) and the project side is only supposed to check its
    boxes, never add prose after it — so appending to end-of-file is safe
    and avoids a fragile reconstruct-the-whole-file edit.

    If *text* starts with a number (e.g. "1. 好，加進去"), it's resolving that
    specific "#N" 💬 item relayed earlier — checks that item's box for real
    and archives the Q&A pair into PROGRESS_HISTORY.md. Without a number,
    it's only auto-resolved if there's exactly one open item (unambiguous);
    otherwise nothing gets checked off — better to leave it open than
    silently resolve the wrong one.
    """
    project = next((p for p in load_tracked_projects() if p.name == project_name), None)
    if project is None:
        return False
    path = _progress_path(project)
    if not path.exists():
        logger.warning("write_instruction: {} has no {} yet.", project_name, PROGRESS_FILENAME)
        return False

    full_text = path.read_text(encoding="utf-8")
    if _INSTRUCT_HEADER not in full_text:
        logger.warning("write_instruction: {} missing '{}' section.", project_name, _INSTRUCT_HEADER)
        return False

    state = _read_state()
    pstate = _project_state(state, project_name)

    number_match = _REPLY_NUMBER_PATTERN.match(text)
    target_item = None
    instruction_text = text
    if number_match:
        number = int(number_match.group(1))
        instruction_text = number_match.group(2).strip() or text
        target_item = next(
            (i for i in pstate["awaiting_decision"] if i["number"] == number), None
        )
    elif len(pstate["awaiting_decision"]) == 1:
        target_item = pstate["awaiting_decision"][0]

    today = datetime.now(_TAIPEI).date().isoformat()
    new_line = f"- [ ] {today} {instruction_text}"
    full_text = full_text.rstrip("\n") + "\n" + new_line + "\n"

    if target_item is not None:
        checked_line = target_item["raw_line"].replace("- [ ]", "- [x]", 1)
        full_text = full_text.replace(target_item["raw_line"], checked_line, 1)
        pstate["awaiting_decision"].remove(target_item)
        _append_history(project, target_item["content"], instruction_text)
        if target_item["escalated"]:
            try:
                from backend.main import get_orchestrator

                todo_content = f"[{project.label}] {target_item['content']}"
                await get_orchestrator().complete_project_todo(project_name, todo_content)
            except Exception as exc:
                logger.error("Failed to auto-complete escalated todo for {}: {}", project_name, exc)

    path.write_text(full_text, encoding="utf-8")
    _write_state(state)
    return True


async def sync_all_projects() -> None:
    """Main entry point — polled every 30 min by scheduler.py. One project's
    failure never stops the others."""
    state = _read_state()
    for project in load_tracked_projects():
        path = _progress_path(project)
        if not path.exists():
            logger.warning("{} has no {} yet; skipping.", project.name, PROGRESS_FILENAME)
            continue

        pstate = _project_state(state, project.name)

        try:
            full_text = path.read_text(encoding="utf-8")
            if not all(h in full_text for h in _SECTION_HEADERS):
                # Not a file managed by this protocol (e.g. a pre-existing,
                # differently-formatted PROGRESS.md some project already
                # had) — never touch it, just skip.
                logger.warning(
                    "{}'s {} doesn't match the expected section headers; skipping.",
                    project.name, PROGRESS_FILENAME,
                )
                continue

            pstate["cycle"] += 1
            await _relay_discuss_items(project, full_text, pstate)
            await _maybe_relay_report(project, full_text, pstate)
            await _escalate_stale_discuss_items(project, pstate)
        except Exception as exc:
            logger.error("Project sync failed for {}: {}", project.name, exc)

    _write_state(state)
