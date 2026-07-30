"""Compatibility checks for thin evidence records carried by Campaign runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pipeline_contracts import (
    AnalyzerRegistryV2,
    BenchmarkRecipeV1,
    ContentIntentV1,
    CreatorIdentityProfileV1,
    IdentityReferenceV1,
    ProvenanceV1,
    validate_generation_execution_plan,
)


class ThinEvidenceCompatibilityError(ValueError):
    """Stable fail-closed error for records that cannot describe one run."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    """Fingerprint one serializable record without adding record behavior."""

    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def snapshot_creator_identity_profile(
    model_account_profile: Mapping[str, Any],
    *,
    identity_references: tuple[IdentityReferenceV1, ...],
    provenance: ProvenanceV1,
) -> CreatorIdentityProfileV1:
    """Snapshot identity facts from Campaign's existing account-profile owner."""

    return CreatorIdentityProfileV1(
        profile_id=str(model_account_profile.get("id") or ""),
        creator_key=str(model_account_profile.get("modelSlug") or ""),
        display_name=str(model_account_profile.get("label") or ""),
        model_profile=str(model_account_profile.get("modelSlug") or ""),
        identity_references=identity_references,
        provenance=provenance,
    )


def snapshot_content_intent(
    creative_plan: Mapping[str, Any],
    *,
    intent_id: str,
    creator_identity_profile_id: str,
    content_surface: str,
    media_kind: str,
    concept_tags: tuple[str, ...],
    source_asset_fingerprints: tuple[str, ...],
    provenance: ProvenanceV1,
) -> ContentIntentV1:
    """Snapshot only intent fields from the mutable Creative Plan record."""

    style_lanes = creative_plan.get("style_lanes") or creative_plan.get("styleLanes")
    return ContentIntentV1(
        intent_id=intent_id,
        creator_identity_profile_id=creator_identity_profile_id,
        goal=str(creative_plan.get("goal") or ""),
        content_surface=content_surface,  # type: ignore[arg-type]
        media_kind=media_kind,  # type: ignore[arg-type]
        style_lanes=tuple(str(value) for value in (style_lanes or [])),
        concept_tags=concept_tags,
        source_asset_fingerprints=source_asset_fingerprints,
        provenance=provenance,
    )


def compile_thin_evidence_records(
    *,
    creator_identity_profile: CreatorIdentityProfileV1,
    content_intent: ContentIntentV1,
    execution_policy: Mapping[str, Any],
    benchmark_recipe: BenchmarkRecipeV1,
    analyzer_registry: AnalyzerRegistryV2,
) -> dict[str, Any]:
    """Validate independent records and return their canonical JSON forms.

    This function only checks cross-record references. It does not route work,
    select providers, run analyzers, persist state, or authorize publication.
    """

    if not isinstance(analyzer_registry, AnalyzerRegistryV2):
        raise ThinEvidenceCompatibilityError(
            "thin_evidence_analyzer_production_authority_v2_required"
        )

    policy = dict(execution_policy)
    validate_generation_execution_plan(policy)

    if (
        content_intent.creator_identity_profile_id
        != creator_identity_profile.profile_id
    ):
        raise ThinEvidenceCompatibilityError(
            "thin_evidence_creator_identity_profile_mismatch"
        )
    if benchmark_recipe.content_intent_id != content_intent.intent_id:
        raise ThinEvidenceCompatibilityError("thin_evidence_content_intent_mismatch")
    if benchmark_recipe.execution_policy_schema != policy.get("schema"):
        raise ThinEvidenceCompatibilityError(
            "thin_evidence_execution_policy_version_mismatch"
        )
    if benchmark_recipe.execution_policy_fingerprint != canonical_json_sha256(policy):
        raise ThinEvidenceCompatibilityError(
            "thin_evidence_execution_policy_fingerprint_mismatch"
        )
    if not set(benchmark_recipe.input_fingerprints).issubset(
        set(content_intent.source_asset_fingerprints)
    ):
        raise ThinEvidenceCompatibilityError("thin_evidence_benchmark_input_mismatch")

    registered = {
        (registration.analyzer_id, registration.analyzer_version)
        for registration in analyzer_registry.analyzers
    }
    missing = [
        (requirement.analyzer_id, requirement.analyzer_version)
        for requirement in benchmark_recipe.required_analyzers
        if (requirement.analyzer_id, requirement.analyzer_version) not in registered
    ]
    if missing:
        raise ThinEvidenceCompatibilityError(
            "thin_evidence_required_analyzer_unregistered"
        )

    return {
        "creatorIdentityProfile": creator_identity_profile.to_dict(),
        "contentIntent": content_intent.to_dict(),
        "executionPolicy": policy,
        "benchmarkRecipe": benchmark_recipe.to_dict(),
        "analyzerRegistry": analyzer_registry.to_dict(),
    }


def validate_compiled_thin_evidence_records(
    evidence_records: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-validate a transported bundle before a run may persist it."""

    expected_keys = {
        "creatorIdentityProfile",
        "contentIntent",
        "executionPolicy",
        "benchmarkRecipe",
        "analyzerRegistry",
    }
    if set(evidence_records) != expected_keys:
        raise ThinEvidenceCompatibilityError("thin_evidence_record_set_invalid")
    try:
        identity = CreatorIdentityProfileV1.from_dict(
            dict(evidence_records["creatorIdentityProfile"])
        )
        intent = ContentIntentV1.from_dict(dict(evidence_records["contentIntent"]))
        recipe = BenchmarkRecipeV1.from_dict(dict(evidence_records["benchmarkRecipe"]))
        registry_payload = dict(evidence_records["analyzerRegistry"])
        if registry_payload.get("schema") != "creator_os.analyzer_registry.v2":
            raise ThinEvidenceCompatibilityError(
                "thin_evidence_analyzer_production_authority_v2_required"
            )
        registry = AnalyzerRegistryV2.from_dict(registry_payload)
        policy = dict(evidence_records["executionPolicy"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ThinEvidenceCompatibilityError(
            "thin_evidence_record_payload_invalid"
        ) from exc
    return compile_thin_evidence_records(
        creator_identity_profile=identity,
        content_intent=intent,
        execution_policy=policy,
        benchmark_recipe=recipe,
        analyzer_registry=registry,
    )
