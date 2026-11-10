"""Regression test for Tier-1 bug #5: dev-agent's reference_path pre-flight
check (and the sandbox it feeds) only accepted a directory — pointing it at
a single reference file (e.g. one log file, not a folder of them) was
rejected even though that's a legitimate case.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.dev_tasks import _validate_reference_path
from backend.tasks.dev_agent import _normalize_reference_path


def test_validate_reference_path_accepts_a_single_file(tmp_path):
    log_file = tmp_path / "run.log"
    log_file.write_text("some log content", encoding="utf-8")

    _validate_reference_path(str(log_file))  # must not raise


def test_validate_reference_path_still_rejects_missing_path(tmp_path):
    missing = tmp_path / "does-not-exist.log"
    with pytest.raises(HTTPException) as exc_info:
        _validate_reference_path(str(missing))
    assert exc_info.value.status_code == 422


def test_validate_reference_path_still_rejects_empty_directory(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(HTTPException) as exc_info:
        _validate_reference_path(str(empty_dir))
    assert exc_info.value.status_code == 422


def test_validate_reference_path_still_accepts_a_populated_directory(tmp_path):
    (tmp_path / "a.csv").write_text("x", encoding="utf-8")
    _validate_reference_path(str(tmp_path))  # must not raise


def test_normalize_reference_path_uses_parent_dir_for_a_file(tmp_path):
    log_file = tmp_path / "run.log"
    log_file.write_text("some log content", encoding="utf-8")

    root, hint = _normalize_reference_path(log_file)

    assert root == tmp_path
    assert hint == "run.log"


def test_normalize_reference_path_passes_through_a_directory_unchanged(tmp_path):
    root, hint = _normalize_reference_path(tmp_path)
    assert root == tmp_path
    assert hint is None


def test_normalize_reference_path_passes_through_none():
    root, hint = _normalize_reference_path(None)
    assert root is None
    assert hint is None
