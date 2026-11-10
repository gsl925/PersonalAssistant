"""Regression test for Tier-2 item: projects.yaml used to round-trip through
PyYAML's safe_load/safe_dump, which has no comment support — every
add_tracked_project()/remove_tracked_project() call silently wiped out any
hand-written "# ..." comments elsewhere in the file. Switched to ruamel.yaml
(round-trip mode), which preserves them.
"""
from __future__ import annotations

from pathlib import Path

import backend.config as cfgmod

_SAMPLE = """projects:
- name: genai-news
  label: GenAI News
  repo_path: D:/x/genai
  enabled: true
  auto_wake: false  # verified working 2026-07-30, do not change without checking with user
- name: aegis-trader
  label: AegisTrader
  repo_path: D:/x/aegis-trader
  enabled: true
"""


def _write_sample(tmp_path: Path) -> Path:
    path = tmp_path / "projects.yaml"
    path.write_text(_SAMPLE, encoding="utf-8")
    return path


def test_add_tracked_project_preserves_existing_comment(tmp_path, monkeypatch):
    path = _write_sample(tmp_path)
    monkeypatch.setattr(cfgmod.settings, "PROJECTS_YAML_PATH", path)

    ok = cfgmod.add_tracked_project("new-proj", "New Project", "D:/x/new-proj")
    assert ok is True

    text = path.read_text(encoding="utf-8")
    assert "# verified working 2026-07-30" in text
    assert "new-proj" in text


def test_remove_tracked_project_preserves_existing_comment(tmp_path, monkeypatch):
    path = _write_sample(tmp_path)
    monkeypatch.setattr(cfgmod.settings, "PROJECTS_YAML_PATH", path)

    ok = cfgmod.remove_tracked_project("aegis-trader")
    assert ok is True

    text = path.read_text(encoding="utf-8")
    assert "# verified working 2026-07-30" in text
    assert "aegis-trader" not in text
    assert "genai-news" in text


def test_load_tracked_projects_still_works_after_round_trip(tmp_path, monkeypatch):
    path = _write_sample(tmp_path)
    monkeypatch.setattr(cfgmod.settings, "PROJECTS_YAML_PATH", path)

    cfgmod.add_tracked_project("new-proj", "New Project", "D:/x/new-proj")
    projects = cfgmod.load_tracked_projects()

    names = {p.name for p in projects}
    assert names == {"genai-news", "aegis-trader", "new-proj"}
    genai = next(p for p in projects if p.name == "genai-news")
    assert genai.auto_wake is False
