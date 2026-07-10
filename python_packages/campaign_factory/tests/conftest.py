from __future__ import annotations

import sys
from pathlib import Path

import pytest

MONOREPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_CONTRACTS = MONOREPO_ROOT / "packages" / "pipeline_contracts"

if PIPELINE_CONTRACTS.exists():
    sys.path.insert(0, str(PIPELINE_CONTRACTS))


@pytest.fixture(autouse=True)
def allow_insecure_local_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def learning_loop_cutover_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default cutover so learning readers stay exercised in tests.

    Individual tests override/delete LEARNING_LOOP_CUTOVER to exercise the
    fail-closed path explicitly.
    """
    monkeypatch.setenv("LEARNING_LOOP_CUTOVER", "2020-01-01T00:00:00+00:00")
