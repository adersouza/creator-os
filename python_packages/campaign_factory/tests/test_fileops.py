from __future__ import annotations

import json
from pathlib import Path

import pytest
from campaign_factory.fileops import atomic_write_json, atomic_write_text, file_lock


def test_atomic_write_text_creates_parents_and_content(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "report.md"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_atomic_write_text_replaces_existing(tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "summary.json"
    atomic_write_json(target, {"b": 2, "a": 1})
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == []


def test_atomic_write_json_sorted_with_newline(tmp_path: Path) -> None:
    target = tmp_path / "summary.json"
    atomic_write_json(target, {"b": 2, "a": 1})
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert text.index('"a"') < text.index('"b"')
    assert json.loads(text) == {"a": 1, "b": 2}


def test_atomic_write_failure_preserves_original(tmp_path: Path) -> None:
    target = tmp_path / "summary.json"
    target.write_text("original", encoding="utf-8")

    class Boom:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": Boom()})
    assert target.read_text(encoding="utf-8") == "original"


def test_file_lock_yields_target_and_creates_lockfile(tmp_path: Path) -> None:
    target = tmp_path / "ledger.json"
    with file_lock(target) as locked:
        assert locked == target
    assert (tmp_path / "ledger.json.lock").exists()


def test_file_lock_nonblocking_raises_when_held(tmp_path: Path) -> None:
    target = tmp_path / "ledger.json"
    with file_lock(target):
        with pytest.raises(BlockingIOError):
            with file_lock(target, blocking=False):
                pass
    # released — can acquire again
    with file_lock(target, blocking=False):
        pass
