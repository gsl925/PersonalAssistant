"""Regression test for Tier-2 item: a weekly consolidated reminder of every
still-open "💬" item across all tracked projects, since an individually
relayed item otherwise has no further visibility until it's escalated.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.config import TrackedProject
from backend.tasks import project_sync


def test_item_age_days_parses_leading_date():
    age = project_sync._item_age_days("2026-08-20 查到兩個問題...")
    assert age is not None
    assert age >= 0


def test_item_age_days_none_without_leading_date():
    assert project_sync._item_age_days("沒有日期的描述") is None


@pytest.mark.asyncio
async def test_roundup_includes_all_open_items_grouped_by_project(monkeypatch):
    project_a = TrackedProject(name="proj-a", label="Project A", repo_path="/tmp/a")
    project_b = TrackedProject(name="proj-b", label="Project B", repo_path="/tmp/b")
    monkeypatch.setattr(project_sync, "load_tracked_projects", lambda: [project_a, project_b])
    monkeypatch.setattr(
        project_sync,
        "_read_state",
        lambda: {
            "proj-a": {
                "awaiting_decision": [
                    {"number": 1, "content": "2026-08-01 決定A"},
                    {"number": 2, "content": "2026-09-01 決定B"},
                ]
            },
            "proj-b": {"awaiting_decision": []},
        },
    )
    sent = AsyncMock()
    monkeypatch.setattr(project_sync, "_send_relay", sent)

    await project_sync.send_weekly_discuss_roundup()

    sent.assert_awaited_once()
    text = sent.call_args[0][0]
    assert "Project A" in text
    assert "決定A" in text
    assert "決定B" in text
    assert "Project B" not in text  # nothing open there, so it's skipped


@pytest.mark.asyncio
async def test_roundup_says_nothing_open_when_all_projects_empty(monkeypatch):
    project_a = TrackedProject(name="proj-a", label="Project A", repo_path="/tmp/a")
    monkeypatch.setattr(project_sync, "load_tracked_projects", lambda: [project_a])
    monkeypatch.setattr(project_sync, "_read_state", lambda: {"proj-a": {"awaiting_decision": []}})
    sent = AsyncMock()
    monkeypatch.setattr(project_sync, "_send_relay", sent)

    await project_sync.send_weekly_discuss_roundup()

    sent.assert_awaited_once()
    assert "沒有待決事項" in sent.call_args[0][0]
