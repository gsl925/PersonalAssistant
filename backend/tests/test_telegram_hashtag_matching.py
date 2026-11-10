"""Regression test for part of Tier-1 bug #4: a reply containing more than
one "#token" (e.g. "#23 好 #genai-news" — a decision-item number plus the
project tag copied from the relayed message) used to misroute entirely,
because the old code took the *first* "#..." match regardless of whether it
was an actual tracked project.
"""
from __future__ import annotations

from backend.bot.telegram_bot import _find_project_hashtag
from backend.config import TrackedProject

_PROJECTS = [
    TrackedProject(name="genai-news", label="GenAI News", repo_path="/tmp/genai-news"),
    TrackedProject(name="aegis-trader", label="Aegis Trader", repo_path="/tmp/aegis-trader"),
]


def test_picks_the_hashtag_that_is_an_actual_tracked_project():
    match, project = _find_project_hashtag("#23 好 #genai-news", _PROJECTS)
    assert project is not None
    assert project.name == "genai-news"
    assert match.group(1) == "genai-news"


def test_single_valid_hashtag_still_matches():
    match, project = _find_project_hashtag("#aegis-trader 先擱置", _PROJECTS)
    assert project is not None
    assert project.name == "aegis-trader"


def test_no_tracked_project_hashtag_returns_none():
    match, project = _find_project_hashtag("#99 好，就這樣", _PROJECTS)
    assert match is None
    assert project is None


def test_case_insensitive_match():
    match, project = _find_project_hashtag("#GenAI-News 好", _PROJECTS)
    assert project is not None
    assert project.name == "genai-news"
