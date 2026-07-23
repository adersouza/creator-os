from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from campaign_factory.local_motion_admission import (
    LocalMotionAdmissionError,
    build_local_motion_admission,
    revalidate_local_motion_admission,
    validate_canonical_analyzer_registry,
)


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    still = tmp_path / "accepted.png"
    still.write_bytes(b"accepted-still")
    still_sha = hashlib.sha256(still.read_bytes()).hexdigest()
    identity = {
        "profileId": "profile-1",
        "creatorKey": "stacey",
    }
    intent = {
        "intentId": "intent-1",
        "sourceAssetFingerprints": [still_sha],
    }
    records = {
        "creatorIdentityProfile": identity,
        "contentIntent": intent,
        "executionPolicy": {"schema": "campaign_factory.generation_execution_plan.v1"},
        "benchmarkRecipe": {
            "recipeId": "recipe-1",
            "inputFingerprints": [still_sha],
            "taskKind": "image_to_video",
        },
        "analyzerRegistry": {
            "schema": "creator_os.analyzer_registry.v1",
            "registryId": "fixture-registry",
            "analyzers": [],
            "provenance": {
                "producer": "fixture",
                "producedAt": "2026-07-22T20:00:00Z",
                "sourceReferences": [],
            },
        },
    }
    summary = {
        "summaryId": "summary-1",
        "summaryFingerprint": "a" * 64,
        "planId": "plan-1",
        "planFingerprint": "b" * 64,
        "purpose": "promotion_eligible",
        "samples": [
            {
                "creatorId": "stacey",
                "identityProfileId": identity["profileId"],
                "identityProfileFingerprint": _fingerprint(identity),
                "contentIntentId": intent["intentId"],
                "contentIntentFingerprint": _fingerprint(intent),
                "taskKind": "image_to_video",
                "capabilityCohort": "image_to_video",
            }
        ],
    }
    summary_path = tmp_path / "arena-summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return still, summary_path, records


def _patch_admission_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure: str | None = None,
) -> dict:
    captured: dict = {}

    def admit(**kwargs):
        captured.update(kwargs)
        if failure is not None:
            raise RuntimeError(failure)
        return {
            "schema": "campaign_factory.local_motion_admission.v1",
            "routerDecision": {"selectedModelId": "local_wan22_i2v_a14b_q4_mlx"},
            "arenaSummary": {"summaryId": kwargs["arena_summary"]["summaryId"]},
            "evidenceRecords": dict(kwargs["evidence_records"]),
            "inputFingerprints": list(kwargs["input_fingerprints"]),
            "resourceSnapshot": {
                "schema": "campaign_factory.local_motion_resource_snapshot.v1",
                "routerAvailableMemoryBytes": 24_000,
            },
            "admissionFingerprint": "f" * 64,
        }

    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.validate_compiled_thin_evidence_records",
        lambda value: value,
    )
    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.admit_local_motion", admit
    )
    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.validate_canonical_analyzer_registry",
        lambda value, **_kwargs: dict(value),
    )
    return captured


def test_admission_binds_exact_inputs_and_calls_only_public_worker_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still, summary_path, records = _fixture(tmp_path)
    captured = _patch_admission_dependencies(monkeypatch)

    result = build_local_motion_admission(
        evidence_bundle_path=None,
        evidence_bundle=records,
        arena_summary_path=summary_path,
        accepted_still_path=still,
        audio_path=None,
        campaign_creator="stacey",
        task_kind="image_to_video",
    )

    assert captured["creator_id"] == "stacey"
    assert captured["task_kind"] == "image_to_video"
    assert captured["arena_summary"]["planId"] == "plan-1"
    assert (
        captured["input_fingerprints"]
        == records["benchmarkRecipe"]["inputFingerprints"]
    )
    assert result["resourceSnapshot"]["routerAvailableMemoryBytes"] == 24_000


def test_admission_fails_closed_without_current_memory_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still, summary_path, records = _fixture(tmp_path)
    captured = _patch_admission_dependencies(
        monkeypatch, failure="available_memory_measurement_unavailable"
    )
    with pytest.raises(
        LocalMotionAdmissionError,
        match="router_admission_failed:available_memory_measurement_unavailable",
    ):
        build_local_motion_admission(
            evidence_bundle_path=None,
            evidence_bundle=records,
            arena_summary_path=summary_path,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
        )
    assert captured["creator_id"] == "stacey"


def test_admission_rejects_model_only_or_placeholder_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still, summary_path, records = _fixture(tmp_path)
    _patch_admission_dependencies(monkeypatch)
    with pytest.raises(LocalMotionAdmissionError, match="must_be_complete"):
        build_local_motion_admission(
            evidence_bundle_path=None,
            evidence_bundle=records,
            arena_summary_path=summary_path,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            override_model_id="local_ltx23_distilled_mlx",
        )
    with pytest.raises(LocalMotionAdmissionError, match="not_substantive"):
        build_local_motion_admission(
            evidence_bundle_path=None,
            evidence_bundle=records,
            arena_summary_path=summary_path,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            override_model_id="local_ltx23_distilled_mlx",
            override_operator="operator",
            override_reason="manual",
        )


def test_canonical_analyzer_registry_rejects_self_consistent_arbitrary_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supplied = {
        "schema": "creator_os.analyzer_registry.v1",
        "registryId": "attacker-controlled",
        "analyzers": [
            {
                "analyzerId": "contentforge.temporal_motion",
                "analyzerVersion": "1.0.0",
                "evidenceKinds": ["temporal_motion_observation"],
                "implementationRef": "attacker.js",
                "implementationFingerprint": "a" * 64,
            }
        ],
        "provenance": {
            "producer": "attacker",
            "producedAt": "2026-07-22T20:00:00Z",
            "sourceReferences": [],
        },
    }
    canonical = {
        **supplied,
        "registryId": "contentforge.trusted_media.v1.canonical",
        "provenance": {**supplied["provenance"], "producer": "contentforge"},
    }
    monkeypatch.setattr(
        "campaign_factory.canonical_analyzer_registry.run_contentforge",
        lambda *_args, **_kwargs: canonical,
    )
    with pytest.raises(
        LocalMotionAdmissionError, match="analyzer_registry_not_canonical"
    ):
        validate_canonical_analyzer_registry(
            supplied, contentforge_root=tmp_path / "contentforge"
        )


def _execution_admission_fixture(
    tmp_path: Path,
) -> tuple[dict, Path, Path, dict, dict]:
    still, summary_path, records = _fixture(tmp_path)
    identity = records["creatorIdentityProfile"]
    intent = records["contentIntent"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    winning = {
        "arenaSummaryFingerprint": summary["summaryFingerprint"],
        "benchmarkIds": ["benchmark-1"],
        "cohortKey": {"creatorId": "stacey", "taskKind": "image_to_video"},
        "matchedArenaSampleIds": ["sample-1"],
        "validArenaSampleIds": ["sample-1"],
        "promotionApproval": {"approvalEventId": "promotion-1"},
    }
    decision_core = {
        "schema": "reel_factory.local_model_router_decision.v1",
        "request": {
            "taskKind": "image_to_video",
            "identityProfileId": identity["profileId"],
            "identityProfileFingerprint": _fingerprint(identity),
            "contentIntentId": intent["intentId"],
            "contentIntentFingerprint": _fingerprint(intent),
        },
        "selectedModelId": "local_wan22_i2v_a14b_q4_mlx",
        "selectedModelFingerprint": "d" * 64,
        "winningEvidence": winning,
        "operatorOverride": None,
        "paidProviderFallbackAllowed": False,
        "legacyLocalMotionFallbackAllowed": False,
    }
    decision = {
        **decision_core,
        "decisionFingerprint": _fingerprint(decision_core),
    }
    admission_core = {
        "schema": "campaign_factory.local_motion_admission.v1",
        "routerDecision": decision,
        "arenaSummary": {
            field: summary[field]
            for field in (
                "summaryId",
                "summaryFingerprint",
                "planId",
                "planFingerprint",
                "purpose",
            )
        },
        "evidenceRecords": records,
        "inputFingerprints": [hashlib.sha256(still.read_bytes()).hexdigest()],
        "resourceSnapshot": {
            "schema": "campaign_factory.local_motion_resource_snapshot.v1"
        },
    }
    admission = {
        **admission_core,
        "admissionFingerprint": _fingerprint(admission_core),
    }
    return (
        admission,
        still,
        summary_path,
        records["benchmarkRecipe"],
        records["analyzerRegistry"],
    )


def _patch_execution_revalidation(
    monkeypatch: pytest.MonkeyPatch, admission: dict, *, failure: str | None = None
) -> None:
    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.validate_local_model_router_decision",
        lambda _value: None,
    )
    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.validate_compiled_thin_evidence_records",
        lambda value: dict(value),
    )
    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.validate_canonical_analyzer_registry",
        lambda value, **_kwargs: dict(value),
    )

    def readmit(**_kwargs):
        if failure is not None:
            raise RuntimeError(failure)
        return admission

    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.admit_local_motion", readmit
    )


def test_execution_revalidation_rehashes_current_input_and_rechecks_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    _patch_execution_revalidation(monkeypatch, admission)
    assert (
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
        == admission
    )


def test_execution_revalidation_rejects_still_substitution_before_readmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    called = False

    def unexpected_readmit(**_kwargs):
        nonlocal called
        called = True
        return admission

    _patch_execution_revalidation(monkeypatch, admission)
    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.admit_local_motion",
        unexpected_readmit,
    )
    still.write_bytes(b"substituted-after-admission")
    with pytest.raises(
        LocalMotionAdmissionError, match="execution_input_fingerprint_mismatch"
    ):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
    assert called is False


def test_execution_revalidation_rejects_audio_substitution_before_readmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"approved-audio")
    audio_sha = hashlib.sha256(audio.read_bytes()).hexdigest()
    records = admission["evidenceRecords"]
    intent = records["contentIntent"]
    recipe["inputFingerprints"].append(audio_sha)
    intent["sourceAssetFingerprints"].append(audio_sha)
    admission["inputFingerprints"].append(audio_sha)
    decision = admission["routerDecision"]
    decision["request"]["contentIntentFingerprint"] = _fingerprint(intent)
    decision_core = dict(decision)
    decision_core.pop("decisionFingerprint")
    decision["decisionFingerprint"] = _fingerprint(decision_core)
    admission_core = dict(admission)
    admission_core.pop("admissionFingerprint")
    admission["admissionFingerprint"] = _fingerprint(admission_core)
    called = False

    def unexpected_readmit(**_kwargs):
        nonlocal called
        called = True
        return admission

    _patch_execution_revalidation(monkeypatch, admission)
    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.admit_local_motion",
        unexpected_readmit,
    )
    audio.write_bytes(b"substituted-after-admission")
    with pytest.raises(
        LocalMotionAdmissionError, match="execution_input_fingerprint_mismatch"
    ):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=audio,
            campaign_creator="stacey",
            task_kind="image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
    assert called is False


def test_execution_revalidation_rejects_revoked_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    _patch_execution_revalidation(
        monkeypatch, admission, failure="active_promotion_not_found_exactly_once"
    )
    with pytest.raises(LocalMotionAdmissionError, match="execution_readmission_failed"):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_execution_revalidation_rejects_replaced_promotion_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    current = deepcopy(admission)
    current["routerDecision"]["winningEvidence"]["promotionApproval"] = {
        "approvalEventId": "replacement-promotion"
    }
    _patch_execution_revalidation(monkeypatch, current)
    with pytest.raises(
        LocalMotionAdmissionError,
        match="execution_winning_evidence_drift:promotionApproval",
    ):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def test_execution_revalidation_rejects_arena_summary_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    _patch_execution_revalidation(monkeypatch, admission)
    substituted = json.loads(summary.read_text(encoding="utf-8"))
    substituted["summaryFingerprint"] = "e" * 64
    summary.write_text(json.dumps(substituted), encoding="utf-8")
    with pytest.raises(LocalMotionAdmissionError, match="arena_summary_mismatch"):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


@pytest.mark.parametrize("field", ["benchmark", "registry"])
def test_execution_revalidation_rejects_recipe_or_registry_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    _patch_execution_revalidation(monkeypatch, admission)
    expected = "execution_benchmark" if field == "benchmark" else "execution_analyzer"
    with pytest.raises(LocalMotionAdmissionError, match=expected):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe={**recipe, "recipeId": "substituted"}
            if field == "benchmark"
            else recipe,
            analyzer_registry={**registry, "registryId": "substituted"}
            if field == "registry"
            else registry,
        )
