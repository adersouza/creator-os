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
