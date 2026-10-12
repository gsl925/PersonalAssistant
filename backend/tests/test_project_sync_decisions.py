"""Regression tests for Tier-1 bug #4 (project-sync side): ghost items in
`awaiting_decision` that never got reconciled against the actual file, and
write_instruction() silently archiving a decision as "resolved" when its
raw_line no longer matched the file (so the checkbox was never actually
flipped).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.config import TrackedProject
from backend.tasks import project_sync

_PROGRESS_TEMPLATE = """# Test Project 進度同步文件

## 📋 進度回報
- 更新時間: 2026-10-01
- 今天完成:
- 明天預計:

## 💬 待溝通 / 建議
{discuss}

## 📮 你的指示
"""


def _project(tmp_path) -> TrackedProject:
    return TrackedProject(name="testproj", label="Test Project", repo_path=str(tmp_path))


def _write_progress(tmp_path, discuss_body: str) -> None:
    (tmp_path / "PROGRESS.md").write_text(
        _PROGRESS_TEMPLATE.format(discuss=discuss_body), encoding="utf-8"
    )


@pytest.fixture(autouse=True)
def _no_real_telegram(monkeypatch):
    monkeypatch.setattr(project_sync, "_send_telegram", AsyncMock(return_value=True))


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    # _state_path() is settings.BASE_DIR / "data" / ... — point it at a
    # scratch dir so this test never touches the real project's state file.
    monkeypatch.setattr(project_sync.settings, "BASE_DIR", tmp_path / "_pa_base")


@pytest.mark.asyncio
async def test_ghost_awaiting_decision_item_is_dropped_once_bullet_is_gone(tmp_path):
    project = _project(tmp_path)
    _write_progress(tmp_path, "- [ ] 要不要升級資料庫？")

    state = {}
    pstate = project_sync._project_state(state, project.name)
    full_text = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
    await project_sync._relay_discuss_items(project, full_text, pstate)
    assert len(pstate["awaiting_decision"]) == 1

    # The bullet disappears from the file (edited/removed directly) without
    # ever going through write_instruction.
    _write_progress(tmp_path, "")
    full_text = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
    await project_sync._relay_discuss_items(project, full_text, pstate)

    assert pstate["awaiting_decision"] == [], (
        "a bullet removed from the file must be dropped from "
        "awaiting_decision instead of lingering as a ghost item forever"
    )


@pytest.mark.asyncio
async def test_write_instruction_does_not_falsely_archive_when_raw_line_changed(
    tmp_path, monkeypatch
):
    project = _project(tmp_path)
    monkeypatch.setattr(project_sync, "load_tracked_projects", lambda: [project])

    _write_progress(tmp_path, "- [ ] 要不要升級資料庫？")
    state = {}
    pstate = project_sync._project_state(state, project.name)
    full_text = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
    await project_sync._relay_discuss_items(project, full_text, pstate)
    assert len(pstate["awaiting_decision"]) == 1
    project_sync._write_state(state)

    # The bullet's exact text changes in the file (e.g. the project edited
    # its own wording) before the user's reply is processed — raw_line
    # captured at relay time no longer appears verbatim (the new wording
    # isn't even a substring of the old one, so a naive .replace() can't
    # accidentally still match).
    _write_progress(tmp_path, "- [ ] 資料庫升級方案重新確認中")

    ok = await project_sync.write_instruction(project.name, "好，升級")
    assert ok is True

    final_text = (tmp_path / "PROGRESS.md").read_text(encoding="utf-8")
    assert "- [x]" not in final_text, (
        "nothing should be checked off when the tracked raw_line no longer "
        "matches the file — the old .replace() no-op'd silently and the "
        "item was archived as resolved anyway"
    )

    new_state = project_sync._read_state()
    new_pstate = new_state[project.name]
    assert len(new_pstate["awaiting_decision"]) == 1, (
        "the item must stay tracked as unresolved, not be silently "
        "removed/archived when the checkbox was never actually flipped"
    )

    history_path = tmp_path / "PROGRESS_HISTORY.md"
    assert not history_path.exists(), (
        "nothing should be archived into PROGRESS_HISTORY.md for a "
        "decision that was never actually resolved in the file"
    )
