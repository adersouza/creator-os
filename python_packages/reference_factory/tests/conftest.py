from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def allow_insecure_local_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
