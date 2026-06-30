from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pipeline_contracts.validator import SCHEMA_DIR

from pipeline_contracts import validate_contract


def _threadsdash_root() -> Path:
    return Path(
        os.environ.get(
            "THREADSDASH_ROOT", "/Users/aderdesouza/Developer/ThreadsDashboard"
        )
    )


@pytest.fixture
def threadsdash_contracts_root() -> Path:
    root = _threadsdash_root() / "pipeline_contracts"
    if not root.exists():
        pytest.skip(f"ThreadsDashboard contracts not available: {root}")
    return root


def test_threadsdashboard_common_schemas_match_canonical(
    threadsdash_contracts_root: Path,
) -> None:
    dashboard_schema_dir = threadsdash_contracts_root / "schemas"
    common = sorted(
        path.name
        for path in dashboard_schema_dir.glob("*.schema.json")
        if (SCHEMA_DIR / path.name).exists()
    )

    assert common
    for filename in common:
        assert (dashboard_schema_dir / filename).read_text(encoding="utf-8") == (
            SCHEMA_DIR / filename
        ).read_text(encoding="utf-8")


def test_threadsdashboard_example_payloads_validate_against_canonical(
    threadsdash_contracts_root: Path,
) -> None:
    dashboard_schema_dir = threadsdash_contracts_root / "schemas"
    examples = sorted(
        path
        for path in dashboard_schema_dir.glob("*.example.json")
        if (SCHEMA_DIR / path.name.replace(".example.json", ".schema.json")).exists()
    )

    assert examples
    for path in examples:
        schema_name = path.name.replace(".example.json", ".schema.json")
        validate_contract(json.loads(path.read_text(encoding="utf-8")), schema_name)


def test_threadsdashboard_ingest_imports_pipeline_contracts(
    threadsdash_contracts_root: Path,
) -> None:
    ingest = (
        threadsdash_contracts_root.parent
        / "api"
        / "_lib"
        / "handlers"
        / "campaign-factory"
        / "draftIngest.ts"
    )

    assert 'from "../../../../pipeline_contracts/typescript.js"' in ingest.read_text(
        encoding="utf-8"
    )
