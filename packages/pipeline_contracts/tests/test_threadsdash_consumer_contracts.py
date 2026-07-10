from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pipeline_contracts.validator import SCHEMA_DIR

from pipeline_contracts import validate_contract


# Schemas ThreadsDashboard is required to mirror. If a schema is added to
# the canonical set that the dashboard must consume, add it here — the
# intersection-based comparison below intentionally no longer decides
# membership, so silent drops in the consumer fail loudly (audit B5).
# `assignment_eligibility.v1` is deliberately absent: it is internal to
# creator-os and has no ThreadsDashboard consumer.
REQUIRED_THREADSDASH_SCHEMAS = (
    "audio_catalog_export.v1.schema.json",
    "audio_intent.v1.schema.json",
    "campaign_draft_payload.v1.schema.json",
    "campaign_draft_payload.v2.schema.json",
    "caption_outcome_context.v1.schema.json",
    "creative_plan.v1.schema.json",
    "front_generation_plan.v1.schema.json",
    "generated_asset_lineage.v1.schema.json",
    "generated_asset_lineage.v2.schema.json",
    "higgsfield_soul_image_prompt.v1.schema.json",
    "kling_3_video_prompt.v1.schema.json",
    "motion_edit_render.v1.schema.json",
    "pattern_card.v1.schema.json",
    "performance_sync.v1.schema.json",
    "post_metric_history.read.v1.schema.json",
    "recommendation_accuracy_report.v1.schema.json",
    "recommendation_next_batch.v1.schema.json",
    "repurposing_plan.v1.schema.json",
    "variant_assignment.v1.schema.json",
    "video_analysis.v1.schema.json",
)


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

    missing = [
        filename
        for filename in REQUIRED_THREADSDASH_SCHEMAS
        if not (dashboard_schema_dir / filename).exists()
    ]
    assert not missing, (
        "ThreadsDashboard is missing required contract schemas: "
        f"{missing}"
    )

    unknown_required = [
        filename
        for filename in REQUIRED_THREADSDASH_SCHEMAS
        if not (SCHEMA_DIR / filename).exists()
    ]
    assert not unknown_required, (
        "REQUIRED_THREADSDASH_SCHEMAS lists schemas absent from the "
        f"canonical set: {unknown_required}"
    )

    for filename in REQUIRED_THREADSDASH_SCHEMAS:
        assert (dashboard_schema_dir / filename).read_text(encoding="utf-8") == (
            SCHEMA_DIR / filename
        ).read_text(encoding="utf-8"), f"schema drift: {filename}"

    # Any extra dashboard copy of a canonical schema must also match, even
    # if it is not (yet) in the required list.
    for path in sorted(dashboard_schema_dir.glob("*.schema.json")):
        if path.name in REQUIRED_THREADSDASH_SCHEMAS:
            continue
        canonical = SCHEMA_DIR / path.name
        if canonical.exists():
            assert path.read_text(encoding="utf-8") == canonical.read_text(
                encoding="utf-8"
            ), f"schema drift: {path.name}"


def test_threadsdashboard_example_payloads_validate_against_canonical(
    threadsdash_contracts_root: Path,
) -> None:
    dashboard_schema_dir = threadsdash_contracts_root / "schemas"

    missing_examples = [
        schema_name
        for schema_name in REQUIRED_THREADSDASH_SCHEMAS
        if not (
            dashboard_schema_dir
            / schema_name.replace(".schema.json", ".example.json")
        ).exists()
    ]
    assert not missing_examples, (
        "ThreadsDashboard is missing example payloads for required "
        f"schemas: {missing_examples}"
    )

    for schema_name in REQUIRED_THREADSDASH_SCHEMAS:
        example = dashboard_schema_dir / schema_name.replace(
            ".schema.json", ".example.json"
        )
        validate_contract(
            json.loads(example.read_text(encoding="utf-8")), schema_name
        )


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
