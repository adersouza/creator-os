"""Thin immutable records shared by Creator OS components.

These value objects contain no routing, provider, persistence, or workflow
logic. Their JSON schemas remain the source of validation truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from .validator import (
    validate_analyzer_registry,
    validate_benchmark_recipe,
    validate_content_intent,
    validate_creator_identity_profile,
)


@dataclass(frozen=True, slots=True)
class SourceReferenceV1:
    record_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("evidence_provenance_source_record_missing")
        if len(self.fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.fingerprint
        ):
            raise ValueError("evidence_provenance_source_fingerprint_invalid")

    def to_dict(self) -> dict[str, str]:
        return {"recordId": self.record_id, "fingerprint": self.fingerprint}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SourceReferenceV1:
        return cls(
            record_id=str(payload["recordId"]),
            fingerprint=str(payload["fingerprint"]),
        )


@dataclass(frozen=True, slots=True)
class ProvenanceV1:
    producer: str
    produced_at: str
    source_references: tuple[SourceReferenceV1, ...]

    def __post_init__(self) -> None:
        if not self.producer.strip():
            raise ValueError("evidence_provenance_producer_missing")
        try:
            produced_at = datetime.fromisoformat(
                self.produced_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("evidence_provenance_timestamp_invalid") from exc
        if produced_at.tzinfo is None:
            raise ValueError("evidence_provenance_timestamp_timezone_missing")
        if not self.source_references:
            raise ValueError("evidence_provenance_source_record_missing")
        identities = [reference.record_id for reference in self.source_references]
        if len(identities) != len(set(identities)):
            raise ValueError("evidence_provenance_source_record_duplicate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer": self.producer,
            "producedAt": self.produced_at,
            "sourceReferences": [
                reference.to_dict() for reference in self.source_references
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProvenanceV1:
        return cls(
            producer=str(payload["producer"]),
            produced_at=str(payload["producedAt"]),
            source_references=tuple(
                SourceReferenceV1.from_dict(value)
                for value in payload["sourceReferences"]
            ),
        )


@dataclass(frozen=True, slots=True)
class IdentityReferenceV1:
    namespace: str
    external_id: str
    fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "externalId": self.external_id,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> IdentityReferenceV1:
        fingerprint = payload.get("fingerprint")
        return cls(
            namespace=str(payload["namespace"]),
            external_id=str(payload["externalId"]),
            fingerprint=str(fingerprint) if fingerprint is not None else None,
        )


@dataclass(frozen=True, slots=True)
class CreatorIdentityProfileV1:
    profile_id: str
    creator_key: str
    display_name: str
    model_profile: str
    identity_references: tuple[IdentityReferenceV1, ...]
    provenance: ProvenanceV1

    def __post_init__(self) -> None:
        validate_creator_identity_profile(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "creator_os.creator_identity_profile.v1",
            "profileId": self.profile_id,
            "creatorKey": self.creator_key,
            "displayName": self.display_name,
            "modelProfile": self.model_profile,
            "identityReferences": [
                reference.to_dict() for reference in self.identity_references
            ],
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CreatorIdentityProfileV1:
        validate_creator_identity_profile(payload)
        return cls(
            profile_id=str(payload["profileId"]),
            creator_key=str(payload["creatorKey"]),
            display_name=str(payload["displayName"]),
            model_profile=str(payload["modelProfile"]),
            identity_references=tuple(
                IdentityReferenceV1.from_dict(item)
                for item in payload["identityReferences"]
            ),
            provenance=ProvenanceV1.from_dict(payload["provenance"]),
        )


@dataclass(frozen=True, slots=True)
class ContentIntentV1:
    intent_id: str
    creator_identity_profile_id: str
    goal: str
    content_surface: Literal["reel", "story", "feed_post", "thread"]
    media_kind: Literal["image", "video", "carousel"]
    style_lanes: tuple[str, ...]
    concept_tags: tuple[str, ...]
    source_asset_fingerprints: tuple[str, ...]
    provenance: ProvenanceV1

    def __post_init__(self) -> None:
        validate_content_intent(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "creator_os.content_intent.v1",
            "intentId": self.intent_id,
            "creatorIdentityProfileId": self.creator_identity_profile_id,
            "goal": self.goal,
            "contentSurface": self.content_surface,
            "mediaKind": self.media_kind,
            "styleLanes": list(self.style_lanes),
            "conceptTags": list(self.concept_tags),
            "sourceAssetFingerprints": list(self.source_asset_fingerprints),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ContentIntentV1:
        validate_content_intent(payload)
        return cls(
            intent_id=str(payload["intentId"]),
            creator_identity_profile_id=str(payload["creatorIdentityProfileId"]),
            goal=str(payload["goal"]),
            content_surface=payload["contentSurface"],
            media_kind=payload["mediaKind"],
            style_lanes=tuple(str(value) for value in payload["styleLanes"]),
            concept_tags=tuple(str(value) for value in payload["conceptTags"]),
            source_asset_fingerprints=tuple(
                str(value) for value in payload["sourceAssetFingerprints"]
            ),
            provenance=ProvenanceV1.from_dict(payload["provenance"]),
        )


@dataclass(frozen=True, slots=True)
class AnalyzerRequirementV1:
    analyzer_id: str
    analyzer_version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "analyzerId": self.analyzer_id,
            "analyzerVersion": self.analyzer_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AnalyzerRequirementV1:
        return cls(
            analyzer_id=str(payload["analyzerId"]),
            analyzer_version=str(payload["analyzerVersion"]),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkRecipeV1:
    recipe_id: str
    content_intent_id: str
    execution_policy_schema: str
    execution_policy_fingerprint: str
    task_kind: str
    input_fingerprints: tuple[str, ...]
    parameter_fingerprint: str
    required_analyzers: tuple[AnalyzerRequirementV1, ...]
    expected_provider_calls: int
    production_writes_allowed: Literal[False]
    provenance: ProvenanceV1

    def __post_init__(self) -> None:
        validate_benchmark_recipe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "creator_os.benchmark_recipe.v1",
            "recipeId": self.recipe_id,
            "contentIntentId": self.content_intent_id,
            "executionPolicySchema": self.execution_policy_schema,
            "executionPolicyFingerprint": self.execution_policy_fingerprint,
            "taskKind": self.task_kind,
            "inputFingerprints": list(self.input_fingerprints),
            "parameterFingerprint": self.parameter_fingerprint,
            "requiredAnalyzers": [
                requirement.to_dict() for requirement in self.required_analyzers
            ],
            "expectedProviderCalls": self.expected_provider_calls,
            "productionWritesAllowed": self.production_writes_allowed,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BenchmarkRecipeV1:
        validate_benchmark_recipe(payload)
        return cls(
            recipe_id=str(payload["recipeId"]),
            content_intent_id=str(payload["contentIntentId"]),
            execution_policy_schema=str(payload["executionPolicySchema"]),
            execution_policy_fingerprint=str(payload["executionPolicyFingerprint"]),
            task_kind=str(payload["taskKind"]),
            input_fingerprints=tuple(
                str(value) for value in payload["inputFingerprints"]
            ),
            parameter_fingerprint=str(payload["parameterFingerprint"]),
            required_analyzers=tuple(
                AnalyzerRequirementV1.from_dict(item)
                for item in payload["requiredAnalyzers"]
            ),
            expected_provider_calls=int(payload["expectedProviderCalls"]),
            production_writes_allowed=payload["productionWritesAllowed"],
            provenance=ProvenanceV1.from_dict(payload["provenance"]),
        )


@dataclass(frozen=True, slots=True)
class AnalyzerRegistrationV1:
    analyzer_id: str
    analyzer_version: str
    evidence_kinds: tuple[str, ...]
    implementation_ref: str
    implementation_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzerId": self.analyzer_id,
            "analyzerVersion": self.analyzer_version,
            "evidenceKinds": list(self.evidence_kinds),
            "implementationRef": self.implementation_ref,
            "implementationFingerprint": self.implementation_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AnalyzerRegistrationV1:
        return cls(
            analyzer_id=str(payload["analyzerId"]),
            analyzer_version=str(payload["analyzerVersion"]),
            evidence_kinds=tuple(str(value) for value in payload["evidenceKinds"]),
            implementation_ref=str(payload["implementationRef"]),
            implementation_fingerprint=str(payload["implementationFingerprint"]),
        )


@dataclass(frozen=True, slots=True)
class AnalyzerRegistryV1:
    registry_id: str
    analyzers: tuple[AnalyzerRegistrationV1, ...]
    provenance: ProvenanceV1

    def __post_init__(self) -> None:
        validate_analyzer_registry(self.to_dict())
        identities = [
            (registration.analyzer_id, registration.analyzer_version)
            for registration in self.analyzers
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("analyzer_registry_duplicate_registration")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "creator_os.analyzer_registry.v1",
            "registryId": self.registry_id,
            "analyzers": [registration.to_dict() for registration in self.analyzers],
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AnalyzerRegistryV1:
        validate_analyzer_registry(payload)
        return cls(
            registry_id=str(payload["registryId"]),
            analyzers=tuple(
                AnalyzerRegistrationV1.from_dict(item) for item in payload["analyzers"]
            ),
            provenance=ProvenanceV1.from_dict(payload["provenance"]),
        )
