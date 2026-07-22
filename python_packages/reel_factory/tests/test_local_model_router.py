from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from reel_factory.local_generation_queue import LocalQueueError, fingerprint
from reel_factory.local_model_router import RouterRequest, route_local_model

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


@dataclass
class FakeReceipt:
    benchmark_id: str = "benchmark-1"
    model_fingerprint: str = MODEL_FINGERPRINT
    task_kind: str = "image_to_video"
    all_qc_passed: bool = True
    benchmark_recipe_fingerprint: str | None = "a" * 64
    analyzer_registry_fingerprint: str | None = "b" * 64


class FakeStore:
    def __init__(
        self,
        *,
        recorded_at: str = "2026-07-22T11:00:00Z",
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
        self.approval_error = approval_error

    def all_receipts(self):
        return {self.receipt.benchmark_id: self.receipt}

    def active_promotion(self, **kwargs):
        if self.approval_error is not None:
            raise LocalQueueError(self.approval_error)
        if not self.approved:
            raise LocalQueueError("not approved")
        return {
            "evaluationId": "evaluation-1",
            "approvalEventHash": "d" * 64,
            "candidateModelFingerprint": kwargs["candidate_model_fingerprint"],
            "taskKind": kwargs["task_kind"],
        }


def _summary(
    *,
    quality=0.85,
    yield_rate=0.75,
    task="image_to_video",
    creator="stacey",
    identity_profile_id="identity-stacey",
    identity_profile_fingerprint="1" * 64,
    content_intent_id="intent-motion",
    content_intent_fingerprint="2" * 64,
    promotion_evidence_valid=True,
) -> dict:
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
                "validSamples": 1,
                "promotionEligibleYield": yield_rate,
                "meanHumanQualityScore": quality,
                "medianWallTimeSeconds": 100.0,
                "medianPeakMemoryBytes": 20 * 1024**3,
                "benchmarkIds": ["benchmark-1"],
            }
        ],
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


@pytest.fixture(autouse=True)
def _ready_model(monkeypatch):
    monkeypatch.setattr(
        "reel_factory.local_model_router.model_status",
        lambda *_args, **_kwargs: {
            "ready": True,
            "manifestSha256": MANIFEST_SHA,
            "manifest": {"revision": MODEL_REVISION},
        },
    )


def test_router_selects_only_approved_measured_local_model() -> None:
    decision = route_local_model(
        _request(), arena_summary=_summary(), benchmark_store=FakeStore()
    )
    assert decision["selectedModelId"] == MODEL_ID
    assert decision["paidProviderFallbackAllowed"] is False
    assert decision["legacyLocalMotionFallbackAllowed"] is False
    assert decision["operatorOverride"] is None


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


def test_router_rejects_creator_intent_without_valid_sample() -> None:
    with pytest.raises(LocalQueueError, match="creator_intent_evidence_ineligible"):
        route_local_model(
            _request(),
            arena_summary=_summary(promotion_evidence_valid=False),
            benchmark_store=FakeStore(),
        )


def test_router_rejects_unavailable_human_quality() -> None:
    with pytest.raises(LocalQueueError, match="human_quality_evidence_unavailable"):
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
