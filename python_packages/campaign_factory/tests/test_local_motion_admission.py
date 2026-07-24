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


def _runtime_and_license_policy() -> tuple[dict, dict, str, str]:
    runtime = {
        "runtimeId": "mlx_video",
        "repository": "https://example.invalid/mlx-video.git",
        "revision": "runtime-revision-1",
        "platform": "Darwin",
        "platformRelease": "25.0.0",
        "osBuild": "25A123",
        "machine": "arm64",
        "python": "3.12.10",
        "pythonExecutable": "/opt/creator-os/bin/python",
        "pythonExecutableResolved": "/opt/creator-os/bin/python3.12",
        "mlxVersion": "0.29.3",
        "runtimeReceiptFingerprint": "1" * 64,
        "resolvedEnvironmentFingerprint": "2" * 64,
        "ffmpegExecutable": "/opt/homebrew/bin/ffmpeg",
        "ffmpegSha256": "3" * 64,
        "ffmpegSize": 1_024,
        "ffmpegVersion": "ffmpeg version 8.0",
        "ffprobeExecutable": "/opt/homebrew/bin/ffprobe",
        "ffprobeSha256": "4" * 64,
        "ffprobeSize": 512,
        "ffprobeVersion": "ffprobe version 8.0",
    }
    license_policy = {
        "licenseId": "ltx-2-community-license-agreement",
        "commercialUse": True,
        "declaredAnnualRevenueUsd": 500_000,
        "commercialRevenueLimitUsd": 10_000_000,
        "commercialUseAllowed": True,
        "aiDisclosureRequired": True,
    }
    return (
        runtime,
        license_policy,
        _fingerprint(runtime),
        _fingerprint(license_policy),
    )


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
    admission_mutator=None,
    selected_model_id: str = "local_wan22_i2v_a14b_q4_mlx",
) -> dict:
    captured: dict = {}

    def admit(**kwargs):
        captured.update(kwargs)
        if failure is not None:
            raise RuntimeError(failure)
        runtime, license_policy, runtime_fingerprint, license_fingerprint = (
            _runtime_and_license_policy()
        )
        decision = {
            "selectedModelId": selected_model_id,
            "consideredCandidates": [
                {
                    "modelId": selected_model_id,
                    "runtimeBinding": runtime,
                    "runtimeBindingFingerprint": runtime_fingerprint,
                    "licensePolicy": license_policy,
                    "licensePolicyFingerprint": license_fingerprint,
                }
            ],
            "winningEvidence": {
                "runtimeBinding": runtime,
                "runtimeBindingFingerprint": runtime_fingerprint,
                "licensePolicy": license_policy,
                "licensePolicyFingerprint": license_fingerprint,
            },
        }
        result = {
            "schema": "campaign_factory.local_motion_admission.v1",
            "routerDecision": decision,
            "arenaSummary": {"summaryId": kwargs["arena_summary"]["summaryId"]},
            "evidenceRecords": dict(kwargs["evidence_records"]),
            "inputFingerprints": list(kwargs["input_fingerprints"]),
            "inputBindings": [dict(item) for item in kwargs["input_bindings"]],
            "promotionInputCohort": [[dict(item) for item in kwargs["input_bindings"]]],
            "taskParameterMaterial": {"schema": "fixture.parameters.v1"},
            "taskParameterFingerprint": "9" * 64,
            "resourceSnapshot": {
                "schema": "campaign_factory.local_motion_resource_snapshot.v1",
                "routerAvailableMemoryBytes": 24_000,
            },
            "admissionFingerprint": "f" * 64,
        }
        if admission_mutator is not None:
            admission_mutator(result)
        return result

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


def test_wan_prompt_expansion_rejects_non_wan_router_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still, summary_path, records = _fixture(tmp_path)
    _patch_admission_dependencies(
        monkeypatch,
        selected_model_id="local_ltx23_i2v_2b_q4_mlx",
    )
    receipt = {"expandedPrompt": "expanded"}
    monkeypatch.setattr(
        "campaign_factory.local_motion_admission.validate_local_wan_i2v_prompt_expansion",
        lambda *_args, **_kwargs: receipt,
    )

    with pytest.raises(
        LocalMotionAdmissionError,
        match="prompt_expansion_selected_model_invalid",
    ):
        build_local_motion_admission(
            evidence_bundle_path=None,
            evidence_bundle=records,
            arena_summary_path=summary_path,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
            prompt="expanded",
            prompt_expansion=receipt,
        )


def test_admission_allows_exact_recipe_input_from_shared_intent_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still, summary_path, records = _fixture(tmp_path)
    other_reviewed_source = "f" * 64
    records["contentIntent"]["sourceAssetFingerprints"].append(other_reviewed_source)
    captured = _patch_admission_dependencies(monkeypatch)

    build_local_motion_admission(
        evidence_bundle_path=None,
        evidence_bundle=records,
        arena_summary_path=summary_path,
        accepted_still_path=still,
        audio_path=None,
        campaign_creator="stacey",
        task_kind="image_to_video",
    )

    assert (
        captured["input_fingerprints"]
        == records["benchmarkRecipe"]["inputFingerprints"]
    )
    assert other_reviewed_source not in captured["input_fingerprints"]


def test_admission_binds_first_and_last_frame_fingerprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still, summary_path, records = _fixture(tmp_path)
    last_image = tmp_path / "last-frame.png"
    last_image.write_bytes(b"approved-last-frame")
    last_sha = hashlib.sha256(last_image.read_bytes()).hexdigest()
    records["contentIntent"]["sourceAssetFingerprints"].append(last_sha)
    records["benchmarkRecipe"]["inputFingerprints"].append(last_sha)
    records["benchmarkRecipe"]["taskKind"] = "keyframe_interpolation"
    captured = _patch_admission_dependencies(monkeypatch)

    build_local_motion_admission(
        evidence_bundle_path=None,
        evidence_bundle=records,
        arena_summary_path=summary_path,
        accepted_still_path=still,
        audio_path=None,
        last_image_path=last_image,
        campaign_creator="stacey",
        task_kind="keyframe_interpolation",
    )

    assert captured["input_fingerprints"] == [
        hashlib.sha256(still.read_bytes()).hexdigest(),
        last_sha,
    ]


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


def test_build_admission_rejects_conflicting_audio_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still, summary_path, records = _fixture(tmp_path)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"source audio")
    _patch_admission_dependencies(monkeypatch)

    with pytest.raises(LocalMotionAdmissionError, match="audio_mode_conflict"):
        build_local_motion_admission(
            evidence_bundle_path=None,
            evidence_bundle=records,
            arena_summary_path=summary_path,
            accepted_still_path=still,
            audio_path=audio,
            generate_audio=True,
            campaign_creator="stacey",
            task_kind="audio_image_to_video",
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("commercialUse", False, "commercial_use_attestation_required"),
        ("declaredAnnualRevenueUsd", None, "commercial_revenue_not_licensed"),
        (
            "declaredAnnualRevenueUsd",
            10_000_000,
            "commercial_revenue_not_licensed",
        ),
        ("aiDisclosureRequired", "yes", "license_policy_invalid"),
    ],
)
def test_admission_rejects_invalid_commercial_revenue_or_disclosure_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    error: str,
) -> None:
    still, summary_path, records = _fixture(tmp_path)

    def mutate(admission: dict) -> None:
        decision = admission["routerDecision"]
        policy = {**decision["winningEvidence"]["licensePolicy"], field: value}
        policy_fingerprint = _fingerprint(policy)
        decision["winningEvidence"]["licensePolicy"] = policy
        decision["winningEvidence"]["licensePolicyFingerprint"] = policy_fingerprint
        decision["consideredCandidates"][0]["licensePolicy"] = policy
        decision["consideredCandidates"][0]["licensePolicyFingerprint"] = (
            policy_fingerprint
        )

    _patch_admission_dependencies(monkeypatch, admission_mutator=mutate)
    with pytest.raises(LocalMotionAdmissionError, match=error):
        build_local_motion_admission(
            evidence_bundle_path=None,
            evidence_bundle=records,
            arena_summary_path=summary_path,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
        )


@pytest.mark.parametrize("failure", ["missing", "mixed"])
def test_admission_rejects_missing_or_mixed_runtime_toolchain_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    still, summary_path, records = _fixture(tmp_path)

    def mutate(admission: dict) -> None:
        decision = admission["routerDecision"]
        if failure == "missing":
            decision["winningEvidence"]["runtimeBinding"] = None
        else:
            replacement = {
                **decision["winningEvidence"]["runtimeBinding"],
                "python": "3.13.0",
            }
            decision["winningEvidence"]["runtimeBinding"] = replacement
            decision["winningEvidence"]["runtimeBindingFingerprint"] = _fingerprint(
                replacement
            )

    _patch_admission_dependencies(monkeypatch, admission_mutator=mutate)
    with pytest.raises(LocalMotionAdmissionError, match="runtime_binding_invalid"):
        build_local_motion_admission(
            evidence_bundle_path=None,
            evidence_bundle=records,
            arena_summary_path=summary_path,
            accepted_still_path=still,
            audio_path=None,
            campaign_creator="stacey",
            task_kind="image_to_video",
        )


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
    runtime, license_policy, runtime_fingerprint, license_fingerprint = (
        _runtime_and_license_policy()
    )
    winning.update(
        {
            "runtimeBinding": runtime,
            "runtimeBindingFingerprint": runtime_fingerprint,
            "licensePolicy": license_policy,
            "licensePolicyFingerprint": license_fingerprint,
        }
    )
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
        "consideredCandidates": [
            {
                "modelId": "local_wan22_i2v_a14b_q4_mlx",
                "runtimeBinding": runtime,
                "runtimeBindingFingerprint": runtime_fingerprint,
                "licensePolicy": license_policy,
                "licensePolicyFingerprint": license_fingerprint,
            }
        ],
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
        "inputBindings": [
            {
                "role": "image",
                "sha256": hashlib.sha256(still.read_bytes()).hexdigest(),
            }
        ],
        "promotionInputCohort": [
            [
                {
                    "role": "image",
                    "sha256": hashlib.sha256(still.read_bytes()).hexdigest(),
                }
            ]
        ],
        "taskParameterMaterial": {"schema": "fixture.parameters.v1"},
        "taskParameterFingerprint": "9" * 64,
        "resourceSnapshot": {
            "schema": "campaign_factory.local_motion_resource_snapshot.v1",
            "motionEditBinding": {
                "taskKind": "image_to_video",
                "sourceVideo": None,
                "retakeStartFrame": None,
                "retakeEndFrame": None,
                "extendFrames": None,
                "extendDirection": "after",
                "preserveAudio": False,
            },
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


def test_execution_revalidation_rejects_conflicting_audio_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"source audio")
    _patch_execution_revalidation(monkeypatch, admission)

    with pytest.raises(
        LocalMotionAdmissionError, match="execution_audio_mode_conflict"
    ):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=audio,
            generate_audio=True,
            campaign_creator="stacey",
            task_kind="audio_image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


def _retake_execution_fixture(
    tmp_path: Path,
) -> tuple[dict, Path, Path, Path, dict, dict]:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"approved-source-video")
    source_sha = hashlib.sha256(source_video.read_bytes()).hexdigest()
    records = admission["evidenceRecords"]
    records["contentIntent"]["sourceAssetFingerprints"] = [source_sha]
    records["benchmarkRecipe"]["inputFingerprints"] = [source_sha]
    records["benchmarkRecipe"]["taskKind"] = "video_retake"
    admission["inputFingerprints"] = [source_sha]
    admission["inputBindings"] = [{"role": "source_video", "sha256": source_sha}]
    admission["promotionInputCohort"] = [admission["inputBindings"]]
    decision = admission["routerDecision"]
    decision["request"]["taskKind"] = "video_retake"
    decision["winningEvidence"]["cohortKey"]["taskKind"] = "video_retake"
    decision_core = dict(decision)
    decision_core.pop("decisionFingerprint")
    decision["decisionFingerprint"] = _fingerprint(decision_core)
    admission["resourceSnapshot"]["motionEditBinding"] = {
        "taskKind": "video_retake",
        "sourceVideo": {"path": str(source_video), "sha256": source_sha},
        "retakeStartFrame": 2,
        "retakeEndFrame": 8,
        "extendFrames": None,
        "extendDirection": "after",
        "preserveAudio": True,
    }
    admission_core = dict(admission)
    admission_core.pop("admissionFingerprint")
    admission["admissionFingerprint"] = _fingerprint(admission_core)
    return admission, still, source_video, summary, recipe, registry


def test_retake_revalidation_binds_source_range_and_preserved_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, source, summary, recipe, registry = _retake_execution_fixture(
        tmp_path
    )
    _patch_execution_revalidation(monkeypatch, admission)
    assert (
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            source_video_path=source,
            retake_start_frame=2,
            retake_end_frame=8,
            preserve_audio=True,
            campaign_creator="stacey",
            task_kind="video_retake",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
        == admission
    )


@pytest.mark.parametrize(
    "substitution",
    ["source", "range", "preserve_audio"],
)
def test_retake_revalidation_rejects_execution_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    substitution: str,
) -> None:
    admission, still, source, summary, recipe, registry = _retake_execution_fixture(
        tmp_path
    )
    _patch_execution_revalidation(monkeypatch, admission)
    if substitution == "source":
        source.write_bytes(b"substituted-source-video")
    with pytest.raises(
        LocalMotionAdmissionError,
        match="execution_motion_edit_binding_mismatch",
    ):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            source_video_path=source,
            retake_start_frame=3 if substitution == "range" else 2,
            retake_end_frame=8,
            preserve_audio=substitution != "preserve_audio",
            campaign_creator="stacey",
            task_kind="video_retake",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )


@pytest.mark.parametrize(
    ("frames", "direction"),
    [(0, "after"), (25, "after"), (8, "sideways")],
)
def test_extend_admission_rejects_invalid_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frames: int,
    direction: str,
) -> None:
    still, summary_path, records = _fixture(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    records["contentIntent"]["sourceAssetFingerprints"] = [source_sha]
    records["benchmarkRecipe"]["inputFingerprints"] = [source_sha]
    records["benchmarkRecipe"]["taskKind"] = "video_extend"
    _patch_admission_dependencies(monkeypatch)
    with pytest.raises(
        LocalMotionAdmissionError,
        match="extend_binding_invalid|extend_direction_invalid",
    ):
        build_local_motion_admission(
            evidence_bundle_path=None,
            evidence_bundle=records,
            arena_summary_path=summary_path,
            accepted_still_path=still,
            audio_path=None,
            source_video_path=source,
            extend_frames=frames,
            extend_direction=direction,
            campaign_creator="stacey",
            task_kind="video_extend",
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
    recipe["taskKind"] = "audio_image_to_video"
    intent["sourceAssetFingerprints"].append(audio_sha)
    admission["inputFingerprints"].append(audio_sha)
    audio_binding = {"role": "audio", "sha256": audio_sha}
    admission["inputBindings"].append(audio_binding)
    admission["promotionInputCohort"] = [[*admission["inputBindings"]]]
    admission["resourceSnapshot"]["motionEditBinding"]["taskKind"] = (
        "audio_image_to_video"
    )
    decision = admission["routerDecision"]
    decision["request"]["taskKind"] = "audio_image_to_video"
    decision["winningEvidence"]["cohortKey"]["taskKind"] = "audio_image_to_video"
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
            task_kind="audio_image_to_video",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
    assert called is False


def test_execution_revalidation_rejects_last_frame_substitution_before_readmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    last_image = tmp_path / "last-frame.png"
    last_image.write_bytes(b"approved-last-frame")
    last_sha = hashlib.sha256(last_image.read_bytes()).hexdigest()
    records = admission["evidenceRecords"]
    intent = records["contentIntent"]
    recipe["inputFingerprints"].append(last_sha)
    recipe["taskKind"] = "keyframe_interpolation"
    intent["sourceAssetFingerprints"].append(last_sha)
    admission["inputFingerprints"].append(last_sha)
    last_binding = {"role": "last_image", "sha256": last_sha}
    admission["inputBindings"].append(last_binding)
    admission["promotionInputCohort"] = [[*admission["inputBindings"]]]
    admission["resourceSnapshot"]["motionEditBinding"]["taskKind"] = (
        "keyframe_interpolation"
    )
    decision = admission["routerDecision"]
    decision["request"]["taskKind"] = "keyframe_interpolation"
    decision["winningEvidence"]["cohortKey"]["taskKind"] = "keyframe_interpolation"
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
    last_image.write_bytes(b"substituted-after-admission")
    with pytest.raises(
        LocalMotionAdmissionError, match="execution_input_fingerprint_mismatch"
    ):
        revalidate_local_motion_admission(
            admission,
            arena_summary_path=summary,
            accepted_still_path=still,
            audio_path=None,
            last_image_path=last_image,
            campaign_creator="stacey",
            task_kind="keyframe_interpolation",
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


@pytest.mark.parametrize(
    "failure",
    [
        "router_no_valid_model:model_unavailable_or_drifted",
        "router_no_valid_model:model_license_cohort_noncompliant",
    ],
)
def test_execution_revalidation_rejects_revoked_deep_verification_or_license(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    _patch_execution_revalidation(
        monkeypatch,
        admission,
        failure=failure,
    )
    with pytest.raises(
        LocalMotionAdmissionError,
        match="model_unavailable_or_drifted|model_license_cohort_noncompliant",
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


@pytest.mark.parametrize("binding", ["runtime", "license", "disclosure"])
def test_execution_revalidation_rejects_runtime_or_license_policy_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding: str,
) -> None:
    admission, still, summary, recipe, registry = _execution_admission_fixture(tmp_path)
    current = deepcopy(admission)
    decision = current["routerDecision"]
    winning = decision["winningEvidence"]
    candidate = decision["consideredCandidates"][0]
    if binding == "runtime":
        replacement = {**winning["runtimeBinding"], "revision": "runtime-revision-2"}
        fingerprint = _fingerprint(replacement)
        winning["runtimeBinding"] = replacement
        winning["runtimeBindingFingerprint"] = fingerprint
        candidate["runtimeBinding"] = replacement
        candidate["runtimeBindingFingerprint"] = fingerprint
    else:
        replacement = {
            **winning["licensePolicy"],
            (
                "aiDisclosureRequired"
                if binding == "disclosure"
                else "declaredAnnualRevenueUsd"
            ): False if binding == "disclosure" else 750_000,
        }
        fingerprint = _fingerprint(replacement)
        winning["licensePolicy"] = replacement
        winning["licensePolicyFingerprint"] = fingerprint
        candidate["licensePolicy"] = replacement
        candidate["licensePolicyFingerprint"] = fingerprint
    decision_core = dict(decision)
    decision_core.pop("decisionFingerprint")
    decision["decisionFingerprint"] = _fingerprint(decision_core)
    admission_core = dict(current)
    admission_core.pop("admissionFingerprint")
    current["admissionFingerprint"] = _fingerprint(admission_core)
    _patch_execution_revalidation(monkeypatch, current)

    with pytest.raises(
        LocalMotionAdmissionError, match="runtime_or_license_policy_drift"
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
