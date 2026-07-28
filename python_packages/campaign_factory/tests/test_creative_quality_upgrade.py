from __future__ import annotations

import hashlib
import sqlite3

import pytest
from campaign_factory.creative_quality_benchmark import SCHEMA as BENCHMARK_SCHEMA
from campaign_factory.creative_quality_benchmark import validate_benchmark_manifest
from campaign_factory.production_compatibility import assess_source_compatibility
from campaign_factory.production_prompts import (
    build_creative_direction_prompt_card,
    compile_passive_prompt_card,
    validate_prompt_card,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source() -> dict[str, object]:
    return {
        "id": "source-1",
        "content_hash": _sha("source"),
        "sourceResolution": {"width": 1080, "height": 1920, "aspectRatio": 0.5625},
        "metadata": {
            "approvedReferencePatternId": "pattern-1",
            "visualAnalysis": {"faceVisibility": True, "sceneType": "room_selfie"},
        },
    }


def test_prompt_card_is_deterministic_fingerprint_valid_and_retains_provenance() -> (
    None
):
    source = _source()
    compatibility = assess_source_compatibility(source)
    first = build_creative_direction_prompt_card(
        creator="stacey",
        intent="passive_selfie",
        source=source,
        observed_facts=compatibility["observedFacts"],
    )
    second = build_creative_direction_prompt_card(
        creator="stacey",
        intent="passive_selfie",
        source=source,
        observed_facts=compatibility["observedFacts"],
    )
    assert first == second
    assert validate_prompt_card(first) == first
    assert first["source"]["sha256"] == source["content_hash"]
    assert first["approvedReferencePatternId"] == "pattern-1"
    assert first["blocking"]["gazeDirection"] == "unknown"


def test_compiled_prompt_preserves_identity_and_safety_constraints() -> None:
    source = _source()
    compatibility = assess_source_compatibility(source)
    card = build_creative_direction_prompt_card(
        creator="stacey",
        intent="passive_selfie",
        source=source,
        observed_facts=compatibility["observedFacts"],
    )
    compiled = compile_passive_prompt_card(card, base_prompt="Subtle gaze movement.")
    assert "Preserve the same person, outfit, setting, pose family" in compiled["text"]
    assert "Keep the full head and face visible" in compiled["text"]
    assert "generated music and ambient audio must remain disabled" in compiled["text"]


def test_compatibility_is_advisory_without_model_switch_or_provider_calls() -> None:
    result = assess_source_compatibility(_source())
    assert result["status"] == "advisory"
    assert result["providerCalls"] == 0
    assert result["modelSwitchAuthorized"] is False
    assert result["benchmarkSupportedModelEvidence"] == []


def test_technical_incompatibility_blocks() -> None:
    source = _source()
    source["sourceResolution"] = {
        "width": 1920,
        "height": 1080,
        "aspectRatio": 1.777778,
    }
    result = assess_source_compatibility(source)
    assert result["status"] == "blocked"
    assert "portrait_aspect_ratio_incompatible" in result["hardBlockers"]


def _benchmark_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE source_assets (id TEXT PRIMARY KEY, content_hash TEXT, status TEXT)"
    )
    for index in range(10):
        conn.execute(
            "INSERT INTO source_assets VALUES (?, ?, 'approved')",
            (f"source-{index}", _sha(f"source-{index}")),
        )
    return conn


def _benchmark_manifest() -> dict[str, object]:
    return {
        "schema": BENCHMARK_SCHEMA,
        "cases": [
            {
                "benchmarkCaseId": f"case-{index}",
                "creator": "stacey",
                "sourceAssetId": f"source-{index}",
                "sourceSha256": _sha(f"source-{index}"),
                "intent": "passive_selfie",
                "sceneClass": "unknown",
                "expectedDurationSeconds": 5,
                "promptCardFingerprint": _sha(f"card-{index}"),
                "incumbentRecipe": "higgsfield_kling3_i2v",
                "challengerRecipe": "higgsfield_seedance2_i2v",
                "comparableInputRequirements": ["same exact source", "same card"],
                "outputs": [],
            }
            for index in range(10)
        ],
    }


def test_benchmark_dry_run_is_read_only_and_cannot_activate_defaults() -> None:
    conn = _benchmark_conn()
    before = conn.total_changes
    result = validate_benchmark_manifest(
        conn, _benchmark_manifest(), future_max_credits=100
    )
    assert result["projectedPaidJobs"] == 20
    assert result["providerCalls"] == 0
    assert result["databaseWrites"] == 0
    assert conn.total_changes == before
    assert result["productionDefaultsChanged"] is False


def test_benchmark_requires_exact_source_and_output_hashes() -> None:
    conn = _benchmark_conn()
    manifest = _benchmark_manifest()
    manifest["cases"][0]["sourceSha256"] = "0" * 64
    manifest["cases"][1]["outputs"] = [{"identity": "PASS", "finalSha256": None}]
    result = validate_benchmark_manifest(conn, manifest, future_max_credits=None)
    reasons = {
        reason for blocker in result["blockers"] for reason in blocker["reasons"]
    }
    assert "source_sha_mismatch" in reasons
    assert "human_scores_require_exact_output_sha" in reasons
    assert result["futureSpendAuthorization"]["present"] is False


def test_prompt_card_rejects_non_passive_compilation() -> None:
    source = _source()
    card = build_creative_direction_prompt_card(
        creator="stacey",
        intent="motion_copy",
        source=source,
        observed_facts={},
    )
    with pytest.raises(ValueError, match="passive intents"):
        compile_passive_prompt_card(card, base_prompt="copy motion")
