from __future__ import annotations

import sys
from pathlib import Path

import pytest

MONOREPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_CONTRACTS = MONOREPO_ROOT / "packages" / "pipeline_contracts"

if PIPELINE_CONTRACTS.exists():
    sys.path.insert(0, str(PIPELINE_CONTRACTS))

# Make sibling test modules (e.g. test_core helpers) importable under
# --import-mode=importlib, where test files are NOT auto-added to sys.path.
# `from tests.test_core import ...` cannot work from the monorepo root: the
# repo-root `tests/` directory shadows the `tests` name, and this directory
# has no __init__.py. Bare `from test_core import ...` + this path entry does.
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)


@pytest.fixture(autouse=True)
def allow_insecure_local_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def isolate_runtime_state_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prevent tests using default Settings from creating operator state."""
    state = tmp_path / "creator-os-state"
    monkeypatch.setenv(
        "CAMPAIGN_FACTORY_DB", str(state / "campaign_factory/campaign_factory.sqlite")
    )
    monkeypatch.setenv(
        "REFERENCE_FACTORY_DB",
        str(state / "reference_factory/reference_factory.sqlite"),
    )
    monkeypatch.setenv(
        "REEL_FACTORY_MANIFEST_DB", str(state / "reel_factory/manifest.sqlite")
    )
    monkeypatch.setenv(
        "REEL_FACTORY_RENDER_QUEUE_DB",
        str(state / "reel_factory/render_queue.sqlite"),
    )


@pytest.fixture(autouse=True)
def learning_loop_cutover_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default cutover so learning readers stay exercised in tests.

    Individual tests override/delete LEARNING_LOOP_CUTOVER to exercise the
    fail-closed path explicitly.
    """
    monkeypatch.setenv("LEARNING_LOOP_CUTOVER", "2020-01-01T00:00:00+00:00")
