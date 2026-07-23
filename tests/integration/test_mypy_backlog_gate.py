from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_gate() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_mypy_backlog.py"
    spec = importlib.util.spec_from_file_location("check_mypy_backlog", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mypy_backlog_parser_reads_error_and_checked_file_counts():
    gate = _load_gate()

    assert gate.parse_summary(
        "Found 95 errors in 30 files (checked 79 source files)", 1
    ) == (95, 79)
    assert gate.parse_summary("Success: no issues found in 12 source files", 0) == (
        0,
        12,
    )


def test_mypy_backlog_parser_rejects_missing_terminal_evidence():
    gate = _load_gate()

    with pytest.raises(ValueError, match="recognized terminal summary"):
        gate.parse_summary("mypy crashed before checking source", 2)


def test_mypy_backlog_ceiling_allows_improvement_and_rejects_regression():
    gate = _load_gate()
    target = gate.BacklogTarget(
        path="example",
        maximum_errors=85,
        minimum_source_files=79,
    )

    assert gate.measurement_failures(
        "reel_factory",
        target,
        errors=83,
        checked=94,
    ) == []
    assert gate.measurement_failures(
        "reel_factory",
        target,
        errors=86,
        checked=94,
    ) == ["reel_factory: mypy backlog grew from 85 to 86"]
    assert gate.measurement_failures(
        "reel_factory",
        target,
        errors=85,
        checked=78,
    ) == ["reel_factory: checked only 78 source files; expected at least 79"]
