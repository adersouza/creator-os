from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from reel_factory.local_generation_queue import LocalQueueError, fingerprint
from reel_factory.local_model_arena import _arena_candidate_aggregates
from reel_factory.local_model_router import RouterRequest, _arithmetic_mean
from reel_factory.local_model_router import route_local_model as _route_local_model

OBSERVED_AT = "2026-07-22T12:00:00Z"
MODEL_ID = "local_wan22_ti2v_5b_mlx"
MANIFEST_SHA = "c" * 64
MODEL_REVISION = "model-revision"
MODEL_FINGERPRINT = fingerprint(
    {
        "modelId": MODEL_ID,
        "modelRevision": MODEL_REVISION,
        "modelManifestSha256": MANIFEST_SHA,
    }
)
DEEP_VERIFICATION_FINGERPRINT = "9" * 64
RUNTIME_BINDING = {
    "runtimeId": "mlx_video",
    "repository": "fixture/runtime",
    "revision": "runtime-revision",
    "platform": "Darwin",
    "platformRelease": "25.0",
    "osBuild": "Darwin Kernel Version fixture",
    "machine": "arm64",
    "python": "3.12.0",
    "pythonExecutable": "/fixture/runtime/python",
    "pythonExecutableResolved": "/fixture/runtime/python3.12",
    "mlxVersion": "0.32.0",
    "runtimeReceiptFingerprint": "1" * 64,
    "resolvedEnvironmentFingerprint": "2" * 64,
    "ffmpegExecutable": "/fixture/bin/ffmpeg",
    "ffmpegSha256": "3" * 64,
    "ffmpegSize": 1024,
    "ffmpegVersion": "ffmpeg version fixture",
    "ffprobeExecutable": "/fixture/bin/ffprobe",
    "ffprobeSha256": "4" * 64,
    "ffprobeSize": 1024,
    "ffprobeVersion": "ffprobe version fixture",
}
RUNTIME_FINGERPRINT = fingerprint(RUNTIME_BINDING)
LICENSE_POLICY = {
    "licenseId": "apache-2.0",
    "commercialUse": True,
    "declaredAnnualRevenueUsd": None,
    "commercialRevenueLimitUsd": None,
    "commercialUseAllowed": True,
    "aiDisclosureRequired": False,
}
LICENSE_FINGERPRINT = fingerprint(LICENSE_POLICY)
REVIEW_PACKET = {
    "packetId": "packet-1",
    "packetFingerprint": "8" * 64,
}
UNBLINDING_RECEIPT = {
    "receiptId": "unblinding-1",
    "receiptFingerprint": "7" * 64,
}


@dataclass
class FakeReceipt:
    benchmark_id: str = "benchmark-1"
    job_id: str = "job-1"
    model_id: str = MODEL_ID
    model_fingerprint: str = MODEL_FINGERPRINT
    model_deep_verification_fingerprint: str = DEEP_VERIFICATION_FINGERPRINT
    task_fingerprint: str = "3" * 64
    task_kind: str = "image_to_video"
    hardware_fingerprint: str = "f" * 64
    output_sha256: str = "e" * 64
    benchmark_recipe_id: str = "recipe-1"
    all_qc_passed: bool = True
    benchmark_recipe_fingerprint: str | None = "a" * 64
    analyzer_registry_id: str = "registry-1"
    analyzer_registry_fingerprint: str | None = "b" * 64
    creator_identity_profile_id: str | None = "identity-stacey"
    creator_identity_profile_fingerprint: str | None = "1" * 64
    content_intent_id: str | None = "intent-motion"
    content_intent_fingerprint: str | None = "2" * 64
    wall_time_seconds: float = 100.0
    peak_memory_bytes: int = 20 * 1024**3
    memory_measurement_method: str = "test"
    execution_attempt_count: int = 1
    execution_retry_count: int = 0
    runtime_binding: dict | None = None
    runtime_binding_fingerprint: str | None = RUNTIME_FINGERPRINT
    license_policy: dict | None = None
    license_policy_fingerprint: str | None = LICENSE_FINGERPRINT

    def __post_init__(self) -> None:
        self.runtime_binding = dict(RUNTIME_BINDING)
        self.license_policy = dict(LICENSE_POLICY)


class FakeStore:
    def __init__(
        self,
        *,
        recorded_at: str = "2026-07-22T11:00:00Z",
        approved_at: str = "2026-07-22T10:00:00Z",
        approved: bool = True,
        approval_error: str | None = None,
    ):
        self.receipt = FakeReceipt()
        self.benchmarks = SimpleNamespace(
            read=lambda: SimpleNamespace(
                events=(
                    {
                        "eventType": "benchmark_recorded",
                        "occurredAt": recorded_at,
                        "payload": {"benchmarkId": self.receipt.benchmark_id},
                    },
                )
            )
        )
        self.approved = approved
        self.approved_at = approved_at
        self.approval_error = approval_error
        self.active_promotion_requests: list[dict] = []

    def all_receipts(self):
        return {self.receipt.benchmark_id: self.receipt}

    def active_promotion(self, **kwargs):
        self.active_promotion_requests.append(dict(kwargs))
        if self.approval_error is not None:
            raise LocalQueueError(self.approval_error)
        if not self.approved:
            raise LocalQueueError("not approved")
        return {
            "evaluationId": "evaluation-1",
            "approvalEventId": "approval-event-1",
            "approvalEventHash": "d" * 64,
            "approvedAt": self.approved_at,
            "approvedBy": "reviewer",
            "scope": [kwargs["task_kind"]],
            "expiresAt": None,
            "candidateModelFingerprint": kwargs["candidate_model_fingerprint"],
            "taskKind": kwargs["task_kind"],
            "candidateBenchmarkIds": list(kwargs["candidate_benchmark_ids"]),
            "hardwareFingerprint": kwargs["hardware_fingerprint"],
            "evidenceFingerprint": "e" * 64,
        }


def _summary(
    *,
    quality=0.85,
    task="image_to_video",
    creator="stacey",
    identity_profile_id="identity-stacey",
    identity_profile_fingerprint="1" * 64,
    content_intent_id="intent-motion",
    content_intent_fingerprint="2" * 64,
    promotion_evidence_valid=True,
) -> dict:
    yield_rate = 1.0 if promotion_evidence_valid else 0.0
    sample = {
        "sampleId": "sample-1",
        "creatorId": creator,
        "identityProfileId": identity_profile_id,
        "identityProfileFingerprint": identity_profile_fingerprint,
        "contentIntentId": content_intent_id,
        "contentIntentFingerprint": content_intent_fingerprint,
        "modelId": MODEL_ID,
        "capabilityCohort": "silent_i2v",
        "status": "succeeded",
        "reason": "completed",
        "outputSha256": "e" * 64,
        "benchmarkId": "benchmark-1",
        "humanReviewId": "review-1",
        "qualityScore": quality,
        "wallTimeSeconds": 100.0,
        "peakMemoryBytes": 20 * 1024**3,
        "executionEvidence": {
            "status": "succeeded",
            "attemptCount": 1,
            "retryCount": 0,
            "admissionBlockCount": 0,
            "failureClass": None,
            "executionMeasurement": {
                "available": True,
                "wallTimeSeconds": 100.0,
                "peakMemoryBytes": 20 * 1024**3,
                "memoryMeasurementMethod": "test",
            },
            "localCost": {
                "available": False,
                "currency": "USD",
                "reason": "local_compute_cost_not_metered",
                "value": None,
            },
        },
        "blockingReasons": [],
        "promotionEvidenceValid": promotion_evidence_valid,
        "taskKind": task,
    }
    core = {
        "schema": "reel_factory.local_model_arena_summary.v1",
        "summaryId": "summary-1",
        "planId": "plan-1",
        "planFingerprint": "f" * 64,
        "purpose": "promotion_eligible",
        "expectedSampleCount": 1,
        "sampleCounts": {
            "cancelled": 0,
            "failed": 0,
            "interrupted": 0,
            "missing": 0,
            "resource_blocked": 0,
            "succeeded": 1,
            "unsupported": 0,
        },
        "promotionEligibleYield": yield_rate,
        "samples": [sample],
        "candidateAggregates": [
            {
                "modelId": MODEL_ID,
                "capabilityCohort": "silent_i2v",
                "plannedSamples": 1,
                "succeededSamples": 1,
                "failedSamples": 0,
                "failureRate": 0.0,
                "validSamples": 1 if promotion_evidence_valid else 0,
                "promotionEligibleYield": yield_rate,
                "meanHumanQualityScore": (
                    quality if promotion_evidence_valid else None
                ),
                "medianWallTimeSeconds": 100.0 if promotion_evidence_valid else None,
                "medianPeakMemoryBytes": (
                    20 * 1024**3 if promotion_evidence_valid else None
                ),
                "benchmarkIds": ["benchmark-1"] if promotion_evidence_valid else [],
            }
        ],
        "reviewEvidence": {
            "reviewPacketId": REVIEW_PACKET["packetId"],
            "reviewPacketFingerprint": REVIEW_PACKET["packetFingerprint"],
            "unblindingReceiptId": UNBLINDING_RECEIPT["receiptId"],
            "unblindingReceiptFingerprint": UNBLINDING_RECEIPT["receiptFingerprint"],
        },
        "providerCalls": 0,
        "productionWrites": 0,
    }
    return {**core, "summaryFingerprint": fingerprint(core)}


def _request(**overrides) -> RouterRequest:
    values = {
        "creator_id": "stacey",
        "identity_profile_id": "identity-stacey",
        "identity_profile_fingerprint": "1" * 64,
        "content_intent_id": "intent-motion",
        "content_intent_fingerprint": "2" * 64,
        "task_kind": "image_to_video",
        "capability_cohort": "silent_i2v",
        "available_memory_bytes": 64 * 1024**3,
        "observed_at": OBSERVED_AT,
    }
    values.update(overrides)
    return RouterRequest(**values)


def _plan(summary: dict) -> dict:
    samples = []
    for item in summary["samples"]:
        sample_id = str(item["sampleId"])
        samples.append(
            {
                **{
                    field: item[field]
                    for field in (
                        "sampleId",
                        "creatorId",
                        "identityProfileId",
                        "identityProfileFingerprint",
                        "contentIntentId",
                        "contentIntentFingerprint",
                        "modelId",
                        "capabilityCohort",
                        "taskKind",
                    )
                },
                "sourceSha256": "4" * 64,
                "blindedCandidateId": f"candidate-{sample_id}",
                "modelFingerprint": MODEL_FINGERPRINT,
                "queueJob": {
                    "jobId": "job-1" if sample_id == "sample-1" else f"job-{sample_id}",
                    "modelId": item["modelId"],
                    "modelFingerprint": MODEL_FINGERPRINT,
                    "taskKind": item["taskKind"],
                    "taskFingerprint": "3" * 64,
                    "benchmarkRecipeId": "recipe-1",
                    "benchmarkRecipeFingerprint": "a" * 64,
                    "analyzerRegistryId": "registry-1",
                    "analyzerRegistryFingerprint": "b" * 64,
                },
                "benchmarkRecipe": {"recipeId": "recipe-1"},
                "benchmarkRecipeFingerprint": "a" * 64,
                "analyzerRegistry": {"registryId": "registry-1"},
                "analyzerRegistryFingerprint": "b" * 64,
                "runtimeBinding": RUNTIME_BINDING,
                "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
                "licensePolicy": LICENSE_POLICY,
                "licensePolicyFingerprint": LICENSE_FINGERPRINT,
            }
        )
    return {
        "planId": summary["planId"],
        "planFingerprint": summary["planFingerprint"],
        "purpose": summary["purpose"],
        "samples": samples,
    }


class FakeHumanReviewStore:
    def __init__(self, summary: dict):
        sample = summary["samples"][0]
        quality = float(sample.get("qualityScore") or 0.0)
        self._reviews = {
            "review-1": SimpleNamespace(
                arena_plan_id=summary["planId"],
                sample_id=sample["sampleId"],
                blinded_candidate_id=f"candidate-{sample['sampleId']}",
                subject_sha256=sample["outputSha256"],
                source_sha256="4" * 64,
                provenance=SimpleNamespace(review_mode="blinded"),
                decisions=SimpleNamespace(
                    creator_identity_preserved=True,
                    anatomy_acceptable=True,
                    operator_useful=True,
                    approved_for_benchmark=True,
                ),
                ratings=SimpleNamespace(
                    realism=quality,
                    attractiveness=quality,
                    creator_identity_similarity=quality,
                    face_stability=quality,
                    motion_naturalness=quality,
                    face_artifact_score=1.0 - quality,
                    hands_visible=False,
                    hand_artifact_score=None,
                    body_artifact_score=1.0 - quality,
                    conversion_usefulness=quality,
                    intent_adherence=quality,
                ),
            )
        }

    def reviews(self):
        return self._reviews


def route_local_model(
    request: RouterRequest, *, arena_summary: dict, benchmark_store: FakeStore
) -> dict:
    return _route_local_model(
        request,
        arena_plan=_plan(arena_summary),
        arena_summary=arena_summary,
        benchmark_store=benchmark_store,  # type: ignore[arg-type]
        human_review_store=FakeHumanReviewStore(arena_summary),  # type: ignore[arg-type]
        review_packet=REVIEW_PACKET,
        unblinding_receipt=UNBLINDING_RECEIPT,
    )


@pytest.fixture(autouse=True)
def _ready_model(monkeypatch):
    monkeypatch.setattr(
        "reel_factory.local_model_arena.validate_arena_plan", lambda plan: dict(plan)
    )
    monkeypatch.setattr(
        "reel_factory.local_model_router.validate_arena_plan", lambda plan: dict(plan)
    )
    monkeypatch.setattr(
        "reel_factory.local_model_router.validate_arena_review_packet",
        lambda packet, **_kwargs: dict(packet),
    )
    monkeypatch.setattr(
        "reel_factory.local_model_router.validate_arena_unblinding_receipt",
        lambda receipt, **_kwargs: dict(receipt),
    )
    monkeypatch.setattr(
        "reel_factory.local_model_router.model_status",
        lambda *_args, **_kwargs: {
            "ready": True,
            "deepVerified": True,
            "manifestSha256": MANIFEST_SHA,
            "manifest": {"revision": MODEL_REVISION},
            "deepVerificationReceipt": {
                "verificationFingerprint": DEEP_VERIFICATION_FINGERPRINT,
                "runtimeBinding": RUNTIME_BINDING,
                "runtimeBindingFingerprint": RUNTIME_FINGERPRINT,
            },
        },
    )


def test_router_selects_only_approved_measured_local_model() -> None:
    store = FakeStore()
    decision = route_local_model(
        _request(), arena_summary=_summary(), benchmark_store=store
    )
    assert decision["selectedModelId"] == MODEL_ID
    assert decision["paidProviderFallbackAllowed"] is False
    assert decision["legacyLocalMotionFallbackAllowed"] is False
    assert decision["operatorOverride"] is None
    assert decision["winningEvidence"]["benchmarkIds"] == ["benchmark-1"]
    assert decision["winningEvidence"]["matchedArenaSampleIds"] == ["sample-1"]
    assert store.active_promotion_requests == [
        {
            "candidate_model_fingerprint": MODEL_FINGERPRINT,
            "task_kind": "image_to_video",
            "candidate_benchmark_ids": ("benchmark-1",),
            "hardware_fingerprint": "f" * 64,
            "observed_at": OBSERVED_AT,
        }
    ]


def test_router_rejects_review_packet_or_unblinding_substitution() -> None:
    summary = _summary()
    summary["reviewEvidence"]["reviewPacketFingerprint"] = "6" * 64
    summary["summaryFingerprint"] = fingerprint(
        {key: value for key, value in summary.items() if key != "summaryFingerprint"}
    )
    with pytest.raises(LocalQueueError, match="review_evidence_chain_mismatch"):
        route_local_model(
            _request(), arena_summary=summary, benchmark_store=FakeStore()
        )


def test_router_mean_human_quality_is_arithmetic_not_median() -> None:
    assert _arithmetic_mean([0.6, 0.6, 1.0]) == pytest.approx(0.7333333333333334)


def test_router_rejects_capability_mismatch() -> None:
    with pytest.raises(LocalQueueError, match="router_no_valid_model"):
        route_local_model(
            _request(task_kind="audio_image_to_video"),
            arena_summary=_summary(),
            benchmark_store=FakeStore(),
        )


def test_router_rejects_stale_evidence() -> None:
    with pytest.raises(LocalQueueError, match="benchmark_evidence_stale"):
        route_local_model(
            _request(maximum_evidence_age_days=2),
            arena_summary=_summary(),
            benchmark_store=FakeStore(recorded_at="2026-06-01T12:00:00Z"),
        )


def test_router_rejects_benchmark_evidence_from_future() -> None:
    with pytest.raises(LocalQueueError, match="benchmark_evidence_from_future"):
        route_local_model(
            _request(),
            arena_summary=_summary(),
            benchmark_store=FakeStore(recorded_at="2026-07-22T12:00:01Z"),
        )


def test_router_rejects_promotion_approval_from_future() -> None:
    with pytest.raises(LocalQueueError, match="promotion_approval_from_future"):
        route_local_model(
            _request(),
            arena_summary=_summary(),
            benchmark_store=FakeStore(approved_at="2026-07-22T12:00:01Z"),
        )


def test_router_rejects_resource_shortage() -> None:
    with pytest.raises(LocalQueueError, match="resource_shortage"):
        route_local_model(
            _request(available_memory_bytes=8 * 1024**3),
            arena_summary=_summary(),
            benchmark_store=FakeStore(),
        )


def test_router_rejects_unapproved_model() -> None:
    with pytest.raises(LocalQueueError, match="active_promotion_missing_or_invalid"):
        route_local_model(
            _request(),
            arena_summary=_summary(),
            benchmark_store=FakeStore(approved=False),
        )


def test_router_rejects_analyzer_drift_from_active_promotion() -> None:
    with pytest.raises(LocalQueueError, match="active_promotion_missing_or_invalid"):
        route_local_model(
            _request(),
            arena_summary=_summary(),
            benchmark_store=FakeStore(
                approval_error="benchmark_analyzer_implementation_drift"
            ),
        )


def test_router_rejects_known_creator_without_matched_evidence() -> None:
    with pytest.raises(LocalQueueError, match="creator_evidence_unsupported"):
        route_local_model(
            _request(),
            arena_summary=_summary(creator="larissa"),
            benchmark_store=FakeStore(),
        )


def test_router_rejects_identity_profile_mismatch() -> None:
    with pytest.raises(LocalQueueError, match="identity_profile_evidence_mismatch"):
        route_local_model(
            _request(),
            arena_summary=_summary(identity_profile_fingerprint="9" * 64),
            benchmark_store=FakeStore(),
        )


def test_router_rejects_content_intent_mismatch() -> None:
    with pytest.raises(LocalQueueError, match="content_intent_evidence_mismatch"):
        route_local_model(
            _request(),
            arena_summary=_summary(content_intent_id="intent-other"),
            benchmark_store=FakeStore(),
        )


def test_router_scores_only_exact_creator_identity_intent_task_cohort() -> None:
    summary = _summary(quality=0.5)
    lola_sample = {
        **summary["samples"][0],
        "sampleId": "sample-lola",
        "creatorId": "lola",
        "identityProfileId": "identity-lola",
        "identityProfileFingerprint": "7" * 64,
        "contentIntentId": "intent-other",
        "contentIntentFingerprint": "8" * 64,
        "benchmarkId": "benchmark-lola",
        "outputSha256": "6" * 64,
        "qualityScore": 1.0,
        "wallTimeSeconds": 1.0,
        "peakMemoryBytes": 1,
    }
    summary["samples"].append(lola_sample)
    summary["expectedSampleCount"] = 2
    summary["sampleCounts"]["succeeded"] = 2
    summary["candidateAggregates"] = _arena_candidate_aggregates(summary["samples"])
    summary["summaryFingerprint"] = fingerprint(
        {key: value for key, value in summary.items() if key != "summaryFingerprint"}
    )

    with pytest.raises(LocalQueueError, match="human_quality_below_policy"):
        route_local_model(
            _request(), arena_summary=summary, benchmark_store=FakeStore()
        )


def test_router_rejects_substituted_global_aggregate_benchmark_ids() -> None:
    summary = _summary()
    summary["candidateAggregates"][0]["benchmarkIds"] = ["other-creator-benchmark"]
    summary["summaryFingerprint"] = fingerprint(
        {key: value for key, value in summary.items() if key != "summaryFingerprint"}
    )

    with pytest.raises(
        LocalQueueError, match="arena_summary_candidate_aggregate_drift"
    ):
        route_local_model(
            _request(), arena_summary=summary, benchmark_store=FakeStore()
        )


def test_router_rejects_duplicate_candidate_aggregate_key() -> None:
    summary = _summary()
    summary["candidateAggregates"].append(dict(summary["candidateAggregates"][0]))
    summary["summaryFingerprint"] = fingerprint(
        {key: value for key, value in summary.items() if key != "summaryFingerprint"}
    )

    with pytest.raises(
        LocalQueueError, match="arena_summary_candidate_aggregate_drift"
    ):
        route_local_model(
            _request(), arena_summary=summary, benchmark_store=FakeStore()
        )


def test_router_rejects_creator_intent_without_valid_sample() -> None:
    with pytest.raises(LocalQueueError, match="creator_intent_evidence_ineligible"):
        route_local_model(
            _request(),
            arena_summary=_summary(promotion_evidence_valid=False),
            benchmark_store=FakeStore(),
        )


def test_router_rejects_valid_claim_with_unavailable_human_quality() -> None:
    with pytest.raises(
        LocalQueueError, match="arena_summary_invalid_promotion_evidence_claim"
    ):
        route_local_model(
            _request(),
            arena_summary=_summary(quality=None),
            benchmark_store=FakeStore(),
        )


def test_router_override_is_explicit_and_excluded_from_learning() -> None:
    decision = route_local_model(
        _request(
            override_model_id=MODEL_ID,
            override_operator="operator",
            override_reason="controlled comparison",
        ),
        arena_summary=_summary(),
        benchmark_store=FakeStore(),
    )
    assert decision["operatorOverride"] == {
        "modelId": MODEL_ID,
        "operator": "operator",
        "reason": "controlled comparison",
        "excludedFromBenchmarkLearning": True,
    }


def test_router_rejects_unsupported_creator() -> None:
    with pytest.raises(ValueError, match="router_creator_unsupported"):
        _request(creator_id="unknown")


@pytest.mark.parametrize(
    "overrides",
    (
        {"minimum_yield": 0.49},
        {"minimum_quality_score": 0.59},
        {"maximum_evidence_age_days": 31},
    ),
)
def test_router_policy_cannot_be_weakened(overrides) -> None:
    with pytest.raises(ValueError, match="router_"):
        _request(**overrides)
