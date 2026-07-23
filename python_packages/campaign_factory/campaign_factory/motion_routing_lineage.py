"""Immutable local-model routing lineage projection for generated assets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def local_routing_lineage(
    admission: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if admission is None or admission.get("schema") != (
        "campaign_factory.local_motion_admission.v1"
    ):
        return None
    decision = admission.get("routerDecision")
    records = admission.get("evidenceRecords")
    summary = admission.get("arenaSummary")
    if not all(isinstance(value, Mapping) for value in (decision, records, summary)):
        raise RuntimeError("local_motion_asset_routing_evidence_missing")
    assert isinstance(decision, Mapping)
    assert isinstance(records, Mapping)
    assert isinstance(summary, Mapping)
    request = decision.get("request")
    winning = decision.get("winningEvidence")
    if not isinstance(request, Mapping) or not isinstance(winning, Mapping):
        raise RuntimeError("local_motion_asset_router_evidence_missing")
    cohort = winning.get("cohortKey")
    promotion = winning.get("promotionApproval")
    recipe = records.get("benchmarkRecipe")
    registry = records.get("analyzerRegistry")
    if not all(
        isinstance(value, Mapping) for value in (cohort, promotion, recipe, registry)
    ):
        raise RuntimeError("local_motion_asset_promotion_evidence_missing")
    assert isinstance(cohort, Mapping)
    assert isinstance(promotion, Mapping)
    assert isinstance(recipe, Mapping)
    assert isinstance(registry, Mapping)
    return {
        "schema": "campaign_factory.local_motion_routing_lineage.v1",
        "admissionFingerprint": admission.get("admissionFingerprint"),
        "routerDecisionId": decision.get("decisionId"),
        "routerDecisionFingerprint": decision.get("decisionFingerprint"),
        "selectedModelId": decision.get("selectedModelId"),
        "selectedModelFingerprint": decision.get("selectedModelFingerprint"),
        "capabilityCohort": request.get("capabilityCohort"),
        "cohortKey": dict(cohort),
        "cohortKeyFingerprint": _fingerprint(cohort),
        "runtimeBinding": winning.get("runtimeBinding"),
        "runtimeBindingFingerprint": winning.get("runtimeBindingFingerprint"),
        "licensePolicy": winning.get("licensePolicy"),
        "licensePolicyFingerprint": winning.get("licensePolicyFingerprint"),
        "arenaSummaryId": summary.get("summaryId"),
        "arenaSummaryFingerprint": summary.get("summaryFingerprint"),
        "benchmarkRecipeId": recipe.get("recipeId"),
        "benchmarkRecipeFingerprint": _fingerprint(recipe),
        "analyzerRegistryId": registry.get("registryId"),
        "analyzerRegistryFingerprint": _fingerprint(registry),
        "promotionApprovalEventId": promotion.get("approvalEventId"),
        "promotionApprovalEventHash": promotion.get("approvalEventHash"),
        "promotionHardwareFingerprint": promotion.get("hardwareFingerprint"),
        "promotionEvidenceFingerprint": promotion.get("evidenceFingerprint"),
        "promotionBenchmarkIdsFingerprint": _fingerprint(
            {"candidateBenchmarkIds": promotion.get("candidateBenchmarkIds")}
        ),
        "operatorOverride": decision.get("operatorOverride"),
    }
