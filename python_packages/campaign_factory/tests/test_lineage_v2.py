from __future__ import annotations

from datetime import datetime

import pytest
from campaign_factory.learning_score import (
    learning_eligible,
    learning_ineligibility_reasons,
)
from campaign_factory.lineage_v2 import (
    audio_intent_fingerprint,
    build_lineage_v2_core,
    finalize_lineage_v2,
    lineage_v2_is_learning_traceable,
    lineage_v2_is_valid,
)

from pipeline_contracts import validate_generated_asset_lineage_v2


def core_lineage():
    return build_lineage_v2_core(
        {
            "schema": "reel_factory.generated_asset_lineage.v1",
            "pipelineTraceId": "trace_1",
            "source": {"promptId": "prompt_1", "referenceId": "reference_1"},
            "generation": {"tool": "higgsfield"},
            "review": {"status": "approved"},
        },
        campaign_id="may",
        recipe_id="recipe_1",
        caption_hash="caption_hash",
        rendered_asset_id="asset_1",
        content_fingerprint="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )


def audio_intent():
    return {
        "schema": "pipeline.audio_intent.v1",
        "mode": "native_platform_audio",
        "required": False,
        "status": "not_required",
        "platform": "instagram",
        "recommendations": [],
        "gates": {"allow_draft_export": True, "allow_publish": True},
    }


def test_audio_intent_fingerprint_is_canonical_and_deterministic():
    first = audio_intent()
    second = {
        "gates": {"allow_publish": True, "allow_draft_export": True},
        "recommendations": [],
        "platform": "instagram",
        "status": "not_required",
        "required": False,
        "mode": "native_platform_audio",
        "schema": "pipeline.audio_intent.v1",
    }

    assert audio_intent_fingerprint(first) == audio_intent_fingerprint(second)
    assert len(audio_intent_fingerprint(first)) == 64
    with_audit_metadata = {
        **first,
        "pipelineTraceId": "trace_ignored",
        "task": {
            "status": "open",
            "assignee": "ignored@example.com",
            "updated_at": "2026-07-09T12:00:00+00:00",
        },
    }
    without_audit_metadata = {**first, "task": {"status": "open"}}
    assert audio_intent_fingerprint(with_audit_metadata) == audio_intent_fingerprint(
        without_audit_metadata
    )
    assert audio_intent_fingerprint(first) != audio_intent_fingerprint(
        {**first, "status": "verified"}
    )


def test_base_and_varied_lineage_validate_with_null_late_bound_audio():
    base = finalize_lineage_v2(
        core_lineage(), audio_intent=audio_intent(), variant_assignment=None
    )
    varied = finalize_lineage_v2(
        core_lineage(),
        audio_intent=audio_intent(),
        variant_assignment={"variant_asset_id": "variant_assignment_1"},
    )

    validate_generated_asset_lineage_v2(base)
    validate_generated_asset_lineage_v2(varied)
    assert base["variantId"] is None
    assert base["audioId"] is None
    assert varied["variantId"] == "variant_assignment_1"
    assert lineage_v2_is_valid(varied, variant_id="variant_assignment_1")
    assert lineage_v2_is_learning_traceable(
        varied, rendered_asset_id="asset_1", variant_id="variant_assignment_1"
    )


def test_v2_contract_allows_null_reference_but_learning_traceability_does_not():
    lineage = finalize_lineage_v2(
        build_lineage_v2_core(
            {
                "source": {"promptId": "prompt_1"},
                "generation": {"tool": "higgsfield"},
                "review": {"status": "approved"},
            },
            campaign_id="may",
            recipe_id="recipe_1",
            caption_hash="caption_hash",
            rendered_asset_id="asset_1",
            content_fingerprint="a" * 64,
        ),
        audio_intent=audio_intent(),
        variant_assignment=None,
    )

    assert lineage_v2_is_valid(lineage)
    assert not lineage_v2_is_learning_traceable(lineage)


def test_learning_ineligibility_reports_forward_lineage_blocker_from_raw_row():
    reasons = learning_ineligibility_reasons(
        {
            "metrics_eligible": 1,
            "history_source": "metric_history",
            "published_at": "2026-06-02T00:00:00+00:00",
            "lineage_v2_valid": 0,
            "raw_json": '{"metadata":{"campaign_factory":{"learning_lineage_blocking_reasons":["missing_referenceId"]}}}',
        },
        cutover=datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
    )

    assert reasons == ["lineage_missing_referenceId"]


def test_varied_lineage_rejects_publishability_variant_instead_of_assignment():
    wrong = {**core_lineage(), "variantId": "base_publishability_variant"}

    with pytest.raises(ValueError, match="variantAssignment.variant_asset_id"):
        finalize_lineage_v2(
            wrong,
            audio_intent=audio_intent(),
            variant_assignment={"variant_asset_id": "assignment_variant"},
        )


def test_missing_prompt_hard_fails_and_v1_snapshot_is_fenced_from_learning():
    with pytest.raises(ValueError, match="missing promptId"):
        build_lineage_v2_core(
            {"source": {}, "generation": {}, "review": {}},
            campaign_id="may",
            recipe_id="recipe_1",
            caption_hash="caption_hash",
            rendered_asset_id="asset_1",
            content_fingerprint="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )

    assert not learning_eligible(
        {
            "metrics_eligible": 1,
            "history_source": "metric_history",
            "published_at": "2026-01-02T00:00:00+00:00",
            "lineage_v2_valid": 0,
        }
    )
