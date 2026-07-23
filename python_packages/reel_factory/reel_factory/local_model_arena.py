"""Reproducible local-model Arena built on the existing queue and benchmark store.

The Arena is a plan, an append-only outcome journal, and deterministic summary
logic.  It is deliberately not another scheduler: inference still runs through
``LocalGenerationQueue`` and measurements still live in
``LocalModelBenchmarkStore``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    load_evidence_secret,
    sign_evidence_attestation,
    verify_evidence_attestation,
)

from pipeline_contracts import (
    validate_local_model_arena_plan,
    validate_local_model_arena_review_packet,
    validate_local_model_arena_summary,
    validate_local_model_arena_unblinding_receipt,
)

from .fileops import atomic_write_text, file_lock
from .human_media_review import HumanMediaReviewStore, HumanReviewSamplingEvidence
from .human_media_review import load_review as load_human_review
from .identity_verification import identity_qc_receipt, verify_identity
from .local_generation_queue import (
    AppendOnlyJournal,
    LocalGenerationJob,
    LocalGenerationQueue,
    LocalQueueError,
    default_local_generation_queue,
    fingerprint,
    sha256_file,
)
from .local_model_benchmark import (
    LocalModelBenchmarkStore,
    default_local_model_benchmark_store,
)
from .local_model_manager import model_status
from .local_video import (
    LocalVideoRequest,
    plan_local_video_job,
    run_local_video,
)
from .video_provider_models import video_model

PLAN_SCHEMA: Final = "reel_factory.local_model_arena_plan.v1"
SUMMARY_SCHEMA: Final = "reel_factory.local_model_arena_summary.v1"
EVENT_SCHEMA: Final = "reel_factory.local_model_arena_event.v1"
REVIEW_PACKET_SCHEMA: Final = "reel_factory.local_model_arena_review_packet.v1"
UNBLINDING_RECEIPT_SCHEMA: Final = (
    "reel_factory.local_model_arena_unblinding_receipt.v1"
)
REVIEW_PACKET_ISSUER: Final = "reel_factory.local_model_arena.review_packet"
UNBLINDING_RECEIPT_ISSUER: Final = "reel_factory.local_model_arena.unblinding"
CREATORS: Final = frozenset({"stacey", "larissa", "lola"})
PURPOSES: Final = frozenset({"exploratory", "promotion_eligible"})
TERMINAL_STATUSES: Final = frozenset(
    {
        "succeeded",
        "failed",
        "interrupted",
        "resource_blocked",
        "unsupported",
        "cancelled",
        "missing",
    }
)
RECORDED_TERMINAL_STATUSES: Final = frozenset(
    {"succeeded", "failed", "unsupported", "cancelled"}
)
IDENTITY_ANALYZER: Final = ("reel_factory.identity_preservation", "2.0.0")
HUMAN_ANALYZER: Final = (
    "reel_factory.structured_human_media_review",
    "1.0.0",
)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"arena_{field}_missing")
    return normalized


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _valid_sha256(value: Any, field: str) -> str:
    normalized = _required_text(value, field)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"arena_{field}_invalid")
    return normalized


def _required_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"arena_{field}_must_be_integer")
    return value


def _implementation_registration(
    *,
    analyzer_id: str,
    analyzer_version: str,
    evidence_kinds: Sequence[str],
    implementation_ref: str,
    repository_root: Path,
) -> dict[str, Any]:
    relative = Path(implementation_ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("arena_analyzer_implementation_ref_invalid")
    implementation = (repository_root / relative).resolve()
    if (
        not implementation.is_relative_to(repository_root)
        or not implementation.is_file()
    ):
        raise LocalQueueError(f"arena_analyzer_implementation_missing:{analyzer_id}")
    return {
        "analyzerId": analyzer_id,
        "analyzerVersion": analyzer_version,
        "evidenceKinds": list(evidence_kinds),
        "implementationRef": relative.as_posix(),
        "implementationFingerprint": sha256_file(implementation),
    }


def arena_analyzer_registry(
    contentforge_registry: Mapping[str, Any],
    *,
    produced_at: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Add the two fixed Reel Factory evidence producers to ContentForge's snapshot."""

    if contentforge_registry.get("schema") != "creator_os.analyzer_registry.v1":
        raise ValueError("arena_contentforge_registry_schema_mismatch")
    base_id = _required_text(
        contentforge_registry.get("registryId"), "contentforge_registry_id"
    )
    raw_registrations = contentforge_registry.get("analyzers")
    if not isinstance(raw_registrations, list) or not raw_registrations:
        raise ValueError("arena_contentforge_registry_empty")
    registrations = [dict(registration) for registration in raw_registrations]
    registrations.extend(
        (
            _implementation_registration(
                analyzer_id=IDENTITY_ANALYZER[0],
                analyzer_version=IDENTITY_ANALYZER[1],
                evidence_kinds=(
                    "creator_identity_similarity",
                    "face_stability",
                    "identity_qc_receipt",
                ),
                implementation_ref=(
                    "python_packages/reel_factory/reel_factory/identity_verification.py"
                ),
                repository_root=repository_root,
            ),
            _implementation_registration(
                analyzer_id=HUMAN_ANALYZER[0],
                analyzer_version=HUMAN_ANALYZER[1],
                evidence_kinds=(
                    "realism_rating",
                    "attractiveness_rating",
                    "creator_resemblance_rating",
                    "motion_naturalness_rating",
                    "anatomy_rating",
                    "conversion_usefulness_rating",
                    "human_review_qc_receipt",
                ),
                implementation_ref=(
                    "python_packages/reel_factory/reel_factory/human_media_review.py"
                ),
                repository_root=repository_root,
            ),
        )
    )
    registrations.sort(
        key=lambda item: (str(item["analyzerId"]), str(item["analyzerVersion"]))
    )
    identities = [
        (str(item["analyzerId"]), str(item["analyzerVersion"]))
        for item in registrations
    ]
    if len(identities) != len(set(identities)):
        raise LocalQueueError("arena_analyzer_registry_duplicate_identity")
    registry_fp = fingerprint({"analyzers": registrations})
    payload = {
        "schema": "creator_os.analyzer_registry.v1",
        "registryId": f"reel_factory.local_arena.v1.{registry_fp[:16]}",
        "analyzers": registrations,
        "provenance": {
            "producer": "reel_factory.local_model_arena",
            "producedAt": produced_at,
            "sourceReferences": [
                {
                    "recordId": base_id,
                    "fingerprint": fingerprint(contentforge_registry),
                },
                *[
                    {
                        "recordId": (f"{item['analyzerId']}@{item['analyzerVersion']}"),
                        "fingerprint": item["implementationFingerprint"],
                    }
                    for item in registrations
                    if str(item["analyzerId"]).startswith("reel_factory.")
                ],
            ],
        },
    }
    return payload


@dataclass(frozen=True, slots=True)
class ArenaSampleSpec:
    creator_id: str
    identity_profile_id: str
    identity_profile_fingerprint: str
    content_intent_id: str
    content_intent_fingerprint: str
    source_path: Path
    model_id: str
    capability_cohort: str
    task_kind: str
    prompt: str
    seed: int
    duration_seconds: int
    resolution: str
    audio_mode: Literal["none", "source", "generated"] = "none"
    audio_path: Path | None = None
    overlays_exist: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArenaSampleSpec:
        audio_path = value.get("audioPath")
        return cls(
            creator_id=_required_text(value.get("creatorId"), "creator_id").lower(),
            identity_profile_id=_required_text(
                value.get("identityProfileId"), "identity_profile_id"
            ),
            identity_profile_fingerprint=_valid_sha256(
                value.get("identityProfileFingerprint"),
                "identity_profile_fingerprint",
            ),
            content_intent_id=_required_text(
                value.get("contentIntentId"), "content_intent_id"
            ),
            content_intent_fingerprint=_valid_sha256(
                value.get("contentIntentFingerprint"),
                "content_intent_fingerprint",
            ),
            source_path=Path(_required_text(value.get("sourcePath"), "source_path"))
            .expanduser()
            .resolve(),
            model_id=_required_text(value.get("modelId"), "model_id"),
            capability_cohort=_required_text(
                value.get("capabilityCohort"), "capability_cohort"
            ),
            task_kind=_required_text(value.get("taskKind"), "task_kind"),
            prompt=_required_text(value.get("prompt"), "prompt"),
            seed=_required_int(value.get("seed"), "seed"),
            duration_seconds=_required_int(
                value.get("durationSeconds"), "duration_seconds"
            ),
            resolution=_required_text(value.get("resolution"), "resolution"),
            audio_mode=str(value.get("audioMode") or "none"),  # type: ignore[arg-type]
            audio_path=(
                Path(str(audio_path)).expanduser().resolve()
                if audio_path is not None
                else None
            ),
            overlays_exist=value.get("overlaysExist") is True,
        )


def _required_analyzers(spec: ArenaSampleSpec) -> tuple[tuple[str, str], ...]:
    required = [
        ("contentforge.media_integrity", "1.0.0"),
        ("contentforge.temporal_motion", "1.0.0"),
        IDENTITY_ANALYZER,
        HUMAN_ANALYZER,
        ("contentforge.motion_specific_qc", "2.0.0"),
    ]
    if spec.audio_mode != "none":
        required.append(("contentforge.audio_integrity", "1.0.0"))
    if spec.overlays_exist:
        required.append(("contentforge.overlay_delivery", "1.0.0"))
    return tuple(required)


def _validate_spec(spec: ArenaSampleSpec) -> None:
    if spec.creator_id not in CREATORS:
        raise ValueError(f"arena_creator_unsupported:{spec.creator_id}")
    if not spec.source_path.is_file() or spec.source_path.is_symlink():
        raise LocalQueueError(f"arena_source_missing_or_unsafe:{spec.source_path}")
    model = video_model(spec.model_id)
    if model.backend != "local_mlx" or model.paid:
        raise LocalQueueError(f"arena_model_not_local_free:{spec.model_id}")
    if spec.task_kind not in (model.supported_tasks or (model.task,)):
        raise LocalQueueError(f"arena_model_capability_mismatch:{spec.model_id}")
    if spec.audio_mode == "none" and spec.audio_path is not None:
        raise ValueError("arena_audio_path_without_audio_mode")
    if spec.audio_mode == "source" and spec.audio_path is None:
        raise ValueError("arena_source_audio_missing")
    if spec.audio_path is not None and (
        not spec.audio_path.is_file() or spec.audio_path.is_symlink()
    ):
        raise LocalQueueError("arena_source_audio_missing_or_unsafe")
    if spec.duration_seconds <= 0:
        raise ValueError("arena_duration_must_be_positive")


def _promotion_design_check(specs: Sequence[ArenaSampleSpec]) -> None:
    if {spec.creator_id for spec in specs} != CREATORS:
        raise LocalQueueError("arena_promotion_requires_all_creators")
    source_sha_by_path = {
        spec.source_path: sha256_file(spec.source_path) for spec in specs
    }
    audio_sha_by_path = {
        spec.audio_path: sha256_file(spec.audio_path)
        for spec in specs
        if spec.audio_path is not None
    }
    grouped: dict[tuple[str, str, str, str], list[ArenaSampleSpec]] = defaultdict(list)
    for spec in specs:
        grouped[
            (
                spec.creator_id,
                spec.model_id,
                spec.capability_cohort,
                spec.content_intent_id,
            )
        ].append(spec)
    for key, rows in grouped.items():
        sources = {source_sha_by_path[row.source_path] for row in rows}
        if len(sources) < 2:
            raise LocalQueueError(
                "arena_promotion_requires_two_sources:" + ":".join(key)
            )
        for source_sha in sources:
            seeds = {
                row.seed
                for row in rows
                if source_sha_by_path[row.source_path] == source_sha
            }
            if len(seeds) < 2:
                raise LocalQueueError(
                    "arena_promotion_requires_two_seeds_per_source:" + ":".join(key)
                )

    # A promotion comparison is matched only when every competing model sees the
    # exact same non-model cells.  Comparing aggregate counts is insufficient:
    # a missing source, changed prompt, or different intent would otherwise make
    # model identity inseparable from the benchmark recipe.
    comparison_groups: dict[tuple[str, str], dict[str, set[tuple[Any, ...]]]] = (
        defaultdict(lambda: defaultdict(set))
    )
    for spec in specs:
        comparison_groups[(spec.creator_id, spec.capability_cohort)][spec.model_id].add(
            (
                spec.identity_profile_id,
                spec.identity_profile_fingerprint,
                spec.content_intent_id,
                spec.content_intent_fingerprint,
                source_sha_by_path[spec.source_path],
                (
                    audio_sha_by_path[spec.audio_path]
                    if spec.audio_path is not None
                    else None
                ),
                spec.task_kind,
                " ".join(spec.prompt.split()),
                spec.seed,
                spec.duration_seconds,
                spec.resolution,
                spec.audio_mode,
                spec.overlays_exist,
            )
        )
    for (creator_id, capability_cohort), grids in comparison_groups.items():
        if len(grids) < 2:
            continue
        reference_model, reference_grid = next(iter(grids.items()))
        for model_id, model_grid in grids.items():
            if model_grid != reference_grid:
                raise LocalQueueError(
                    "arena_promotion_unmatched_model_grid:"
                    f"{creator_id}:{capability_cohort}:"
                    f"{reference_model}:{model_id}"
                )


def build_arena_plan(
    *,
    sample_specs: Sequence[ArenaSampleSpec],
    purpose: str,
    produced_at: str,
    output_root: Path,
    execution_policy: Mapping[str, Any],
    analyzer_registry: Mapping[str, Any],
) -> dict[str, Any]:
    if purpose not in PURPOSES:
        raise ValueError("arena_purpose_invalid")
    if not sample_specs:
        raise ValueError("arena_samples_missing")
    if execution_policy.get("schema") != "creator_os.execution_policy.v1":
        raise ValueError("arena_execution_policy_schema_mismatch")
    if execution_policy.get("paidProvidersAllowed") is not False:
        raise LocalQueueError("arena_execution_policy_paid_provider_forbidden")
    if execution_policy.get("productionWritesAllowed") is not False:
        raise LocalQueueError("arena_execution_policy_production_write_forbidden")
    for spec in sample_specs:
        _validate_spec(spec)
    source_pairs = [
        (spec.creator_id, sha256_file(spec.source_path)) for spec in sample_specs
    ]
    if len(source_pairs) != len(set(source_pairs)) and len(
        {
            (spec.creator_id, spec.model_id, spec.seed, sha256_file(spec.source_path))
            for spec in sample_specs
        }
    ) != len(sample_specs):
        raise LocalQueueError("arena_duplicate_sample_identity")
    if purpose == "promotion_eligible":
        _promotion_design_check(sample_specs)

    output_directory = output_root.expanduser().resolve()
    if analyzer_registry.get("schema") != "creator_os.analyzer_registry.v1":
        raise ValueError("arena_analyzer_registry_schema_mismatch")
    registry_payload = dict(analyzer_registry)
    raw_registered = registry_payload.get("analyzers")
    if not isinstance(raw_registered, list) or not raw_registered:
        raise ValueError("arena_analyzer_registry_empty")
    registered = {
        (str(registration["analyzerId"]), str(registration["analyzerVersion"]))
        for registration in raw_registered
        if isinstance(registration, dict)
        and registration.get("analyzerId")
        and registration.get("analyzerVersion")
    }
    if len(registered) != len(raw_registered):
        raise LocalQueueError("arena_analyzer_registry_duplicate_or_invalid")
    policy_fingerprint = fingerprint(execution_policy)
    samples: list[dict[str, Any]] = []
    for spec in sample_specs:
        source_sha = sha256_file(spec.source_path)
        audio_sha = (
            sha256_file(spec.audio_path) if spec.audio_path is not None else None
        )
        required = _required_analyzers(spec)
        if not set(required).issubset(registered):
            missing = sorted(set(required).difference(registered))
            raise LocalQueueError(f"arena_required_analyzer_unregistered:{missing}")
        recipe_parameters = {
            "capabilityCohort": spec.capability_cohort,
            "taskKind": spec.task_kind,
            "prompt": " ".join(spec.prompt.split()),
            "seed": spec.seed,
            "durationSeconds": spec.duration_seconds,
            "resolution": spec.resolution,
            "audioMode": spec.audio_mode,
            "audioSha256": audio_sha,
            "overlaysExist": spec.overlays_exist,
        }
        recipe_identity = {
            "creatorId": spec.creator_id,
            "identityProfileFingerprint": spec.identity_profile_fingerprint,
            "contentIntentFingerprint": spec.content_intent_fingerprint,
            "sourceSha256": source_sha,
            **recipe_parameters,
        }
        recipe_identity_fingerprint = fingerprint(recipe_identity)
        sample_identity = {**recipe_identity, "modelId": spec.model_id}
        sample_id = f"arena_sample_{fingerprint(sample_identity)[:24]}"
        output_path = output_directory / "outputs" / f"{sample_id}.mp4"
        recipe = {
            "schema": "creator_os.benchmark_recipe.v1",
            "recipeId": f"arena_recipe_{recipe_identity_fingerprint[:24]}",
            "contentIntentId": spec.content_intent_id,
            "executionPolicySchema": str(execution_policy["schema"]),
            "executionPolicyFingerprint": policy_fingerprint,
            "taskKind": spec.task_kind,
            "inputFingerprints": [
                value for value in (source_sha, audio_sha) if value is not None
            ],
            "parameterFingerprint": fingerprint(recipe_parameters),
            "requiredAnalyzers": [
                {"analyzerId": item[0], "analyzerVersion": item[1]} for item in required
            ],
            "expectedProviderCalls": 0,
            "productionWritesAllowed": False,
            "provenance": {
                "producer": "reel_factory.local_model_arena",
                "producedAt": produced_at,
                "sourceReferences": [
                    {
                        "recordId": spec.identity_profile_id,
                        "fingerprint": spec.identity_profile_fingerprint,
                    },
                    {
                        "recordId": spec.content_intent_id,
                        "fingerprint": spec.content_intent_fingerprint,
                    },
                    {
                        "recordId": str(
                            execution_policy.get("policyId") or "execution-policy"
                        ),
                        "fingerprint": policy_fingerprint,
                    },
                ],
            },
        }
        status = model_status(spec.model_id, deep=True)
        deep_verification = status.get("deepVerificationReceipt")
        if (
            not status.get("ready")
            or status.get("deepVerified") is not True
            or not isinstance(deep_verification, dict)
        ):
            raise LocalQueueError(
                f"arena_model_not_ready:{spec.model_id}:"
                + ",".join(str(issue) for issue in status.get("issues", []))
            )
        deep_verification_fingerprint = _valid_sha256(
            deep_verification.get("verificationFingerprint"),
            "model_deep_verification_fingerprint",
        )
        deep_core = dict(deep_verification)
        deep_core.pop("verificationFingerprint", None)
        if fingerprint(deep_core) != deep_verification_fingerprint:
            raise LocalQueueError("arena_model_deep_verification_receipt_invalid")
        request = LocalVideoRequest(
            model_id=spec.model_id,
            image_path=spec.source_path,
            prompt=spec.prompt,
            output_path=output_path,
            duration_seconds=spec.duration_seconds,
            resolution=spec.resolution,
            seed=spec.seed,
            audio_mode=spec.audio_mode,
            audio_path=spec.audio_path,
            task=spec.task_kind,  # type: ignore[arg-type]
            benchmark_recipe=recipe,
            analyzer_registry=registry_payload,
            execution_context="arena_benchmark",
            arena_benchmark_binding=_arena_benchmark_binding(
                sample_id=sample_id,
                blinded_candidate_id=(
                    f"candidate_{fingerprint({'sample': sample_id})[:16]}"
                ),
                source_sha256=source_sha,
                identity_profile_id=spec.identity_profile_id,
                identity_profile_fingerprint=spec.identity_profile_fingerprint,
                content_intent_id=spec.content_intent_id,
                content_intent_fingerprint=spec.content_intent_fingerprint,
                benchmark_recipe_fingerprint=fingerprint(recipe),
                analyzer_registry_fingerprint=fingerprint(registry_payload),
                model_deep_verification_fingerprint=(deep_verification_fingerprint),
            ),
        )
        job = plan_local_video_job(request)
        manifest_sha = _valid_sha256(
            status.get("manifestSha256"), "model_manifest_sha256"
        )
        samples.append(
            {
                "sampleId": sample_id,
                "creatorId": spec.creator_id,
                "identityProfileId": spec.identity_profile_id,
                "identityProfileFingerprint": spec.identity_profile_fingerprint,
                "contentIntentId": spec.content_intent_id,
                "contentIntentFingerprint": spec.content_intent_fingerprint,
                "sourcePath": str(spec.source_path),
                "sourceSha256": source_sha,
                "audioPath": str(spec.audio_path) if spec.audio_path else None,
                "audioSha256": audio_sha,
                "modelId": spec.model_id,
                "modelRevision": str(status["manifest"]["revision"]),
                "modelManifestSha256": manifest_sha,
                "modelDeepVerificationFingerprint": (deep_verification_fingerprint),
                "modelFingerprint": job.model_fingerprint,
                "capabilityCohort": spec.capability_cohort,
                "taskKind": spec.task_kind,
                "prompt": " ".join(spec.prompt.split()),
                "seed": spec.seed,
                "durationSeconds": spec.duration_seconds,
                "resolution": spec.resolution,
                "audioMode": spec.audio_mode,
                "overlaysExist": spec.overlays_exist,
                "outputPath": str(output_path),
                "blindedCandidateId": f"candidate_{fingerprint({'sample': sample_id})[:16]}",
                "queueJob": job.as_dict(),
                "queueJobFingerprint": fingerprint(job.as_dict()),
                "benchmarkRecipe": recipe,
                "benchmarkRecipeFingerprint": fingerprint(recipe),
                "analyzerRegistry": registry_payload,
                "analyzerRegistryFingerprint": fingerprint(registry_payload),
                "promotionEligible": purpose == "promotion_eligible",
            }
        )
    samples.sort(key=lambda item: str(item["sampleId"]))
    core = {
        "schema": PLAN_SCHEMA,
        "planId": f"arena_plan_{fingerprint({'samples': samples, 'purpose': purpose})[:24]}",
        "purpose": purpose,
        "createdAt": produced_at,
        "creators": sorted({str(item["creatorId"]) for item in samples}),
        "expectedSampleCount": len(samples),
        "samples": samples,
        "providerCalls": 0,
        "productionWritesAllowed": False,
    }
    return {**core, "planFingerprint": fingerprint(core)}


def validate_arena_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    validate_local_model_arena_plan(dict(plan))
    payload = dict(plan)
    if payload.get("schema") != PLAN_SCHEMA:
        raise ValueError("arena_plan_schema_mismatch")
    claimed = _valid_sha256(payload.pop("planFingerprint", None), "plan_fingerprint")
    if fingerprint(payload) != claimed:
        raise LocalQueueError("arena_plan_fingerprint_mismatch")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("arena_plan_samples_missing")
    if payload.get("expectedSampleCount") != len(samples):
        raise LocalQueueError("arena_plan_sample_denominator_mismatch")
    expected_creators = sorted(
        {str(sample.get("creatorId")) for sample in samples if isinstance(sample, dict)}
    )
    if payload.get("creators") != expected_creators:
        raise LocalQueueError("arena_plan_creator_set_mismatch")
    identities: set[str] = set()
    blinded: set[str] = set()
    outputs: set[str] = set()
    jobs: set[str] = set()
    deep_models: dict[str, dict[str, Any]] = {}
    for raw in samples:
        if not isinstance(raw, dict):
            raise ValueError("arena_plan_sample_invalid")
        sample_id = _required_text(raw.get("sampleId"), "sample_id")
        if sample_id in identities:
            raise LocalQueueError("arena_duplicate_sample_identity")
        identities.add(sample_id)
        blind = _required_text(raw.get("blindedCandidateId"), "blinded_candidate_id")
        if blind in blinded:
            raise LocalQueueError("arena_duplicate_blinded_identity")
        blinded.add(blind)
        output = str(
            Path(_required_text(raw.get("outputPath"), "output_path")).resolve()
        )
        if output in outputs:
            raise LocalQueueError("arena_output_collision")
        outputs.add(output)
        queue_job = raw.get("queueJob")
        if not isinstance(queue_job, dict):
            raise ValueError("arena_queue_job_missing")
        if fingerprint(queue_job) != raw.get("queueJobFingerprint"):
            raise LocalQueueError("arena_queue_job_fingerprint_mismatch")
        job = LocalGenerationJob(
            job_id=str(queue_job["jobId"]),
            model_id=str(queue_job["modelId"]),
            model_fingerprint=str(queue_job["modelFingerprint"]),
            task_kind=str(queue_job["taskKind"]),
            task_fingerprint=str(queue_job["taskFingerprint"]),
            input_fingerprint=str(queue_job["inputFingerprint"]),
            requested_memory_bytes=int(queue_job["requestedMemoryBytes"]),
            params_fingerprint=str(queue_job["paramsFingerprint"]),
            owned_artifact_paths=tuple(
                str(item) for item in queue_job.get("ownedArtifactPaths", [])
            ),
            benchmark_recipe_id=(
                str(queue_job["benchmarkRecipeId"])
                if queue_job.get("benchmarkRecipeId") is not None
                else None
            ),
            benchmark_recipe_fingerprint=(
                str(queue_job["benchmarkRecipeFingerprint"])
                if queue_job.get("benchmarkRecipeFingerprint") is not None
                else None
            ),
            analyzer_registry_id=(
                str(queue_job["analyzerRegistryId"])
                if queue_job.get("analyzerRegistryId") is not None
                else None
            ),
            analyzer_registry_fingerprint=(
                str(queue_job["analyzerRegistryFingerprint"])
                if queue_job.get("analyzerRegistryFingerprint") is not None
                else None
            ),
        )
        if job.job_id in jobs:
            raise LocalQueueError("arena_duplicate_queue_job_identity")
        jobs.add(job.job_id)
        recipe = dict(raw["benchmarkRecipe"])
        registry = dict(raw["analyzerRegistry"])
        if recipe.get("schema") != "creator_os.benchmark_recipe.v1":
            raise ValueError("arena_benchmark_recipe_schema_mismatch")
        if registry.get("schema") != "creator_os.analyzer_registry.v1":
            raise ValueError("arena_analyzer_registry_schema_mismatch")
        if fingerprint(recipe) != raw.get("benchmarkRecipeFingerprint"):
            raise LocalQueueError("arena_benchmark_recipe_fingerprint_mismatch")
        if fingerprint(registry) != raw.get("analyzerRegistryFingerprint"):
            raise LocalQueueError("arena_analyzer_registry_fingerprint_mismatch")
        if (
            job.benchmark_recipe_id != recipe.get("recipeId")
            or job.benchmark_recipe_fingerprint != fingerprint(recipe)
            or job.analyzer_registry_id != registry.get("registryId")
            or job.analyzer_registry_fingerprint != fingerprint(registry)
        ):
            raise LocalQueueError("arena_queue_evidence_linkage_mismatch")
        expected_model_fingerprint = fingerprint(
            {
                "modelId": raw["modelId"],
                "modelRevision": raw["modelRevision"],
                "modelManifestSha256": raw["modelManifestSha256"],
            }
        )
        if (
            raw.get("modelFingerprint") != expected_model_fingerprint
            or job.model_id != raw.get("modelId")
            or job.model_fingerprint != expected_model_fingerprint
            or job.task_kind != raw.get("taskKind")
            or output not in job.owned_artifact_paths
        ):
            raise LocalQueueError("arena_queue_sample_binding_mismatch")
        model_id = str(raw["modelId"])
        if model_id not in deep_models:
            deep_models[model_id] = model_status(model_id, deep=True)
        current_model = deep_models[model_id]
        deep_receipt = current_model.get("deepVerificationReceipt")
        deep_claimed = (
            deep_receipt.get("verificationFingerprint")
            if isinstance(deep_receipt, dict)
            else None
        )
        deep_core = dict(deep_receipt) if isinstance(deep_receipt, dict) else {}
        deep_core.pop("verificationFingerprint", None)
        if (
            current_model.get("ready") is not True
            or current_model.get("deepVerified") is not True
            or not isinstance(deep_receipt, dict)
            or current_model.get("manifestSha256") != raw["modelManifestSha256"]
            or not isinstance(deep_claimed, str)
            or fingerprint(deep_core) != deep_claimed
            or deep_claimed != raw.get("modelDeepVerificationFingerprint")
        ):
            raise LocalQueueError("arena_model_deep_verification_missing_or_drifted")
        if raw.get("promotionEligible") is not (
            payload.get("purpose") == "promotion_eligible"
        ):
            raise LocalQueueError("arena_sample_promotion_eligibility_mismatch")
        source = Path(str(raw["sourcePath"])).resolve()
        if not source.is_file() or sha256_file(source) != raw.get("sourceSha256"):
            raise LocalQueueError("arena_source_missing_or_substituted")
        audio_path = raw.get("audioPath")
        audio_sha = raw.get("audioSha256")
        if audio_path is None:
            if audio_sha is not None or raw.get("audioMode") == "source":
                raise LocalQueueError("arena_audio_binding_incomplete")
        else:
            audio = Path(str(audio_path)).resolve()
            if (
                not audio.is_file()
                or audio_sha is None
                or sha256_file(audio) != audio_sha
            ):
                raise LocalQueueError("arena_audio_missing_or_substituted")
    return {**payload, "planFingerprint": claimed}


def _human_review_evidence(review: Any) -> tuple[list[str], float]:
    """Return fail-closed review blockers and one transparent quality mean."""

    decisions = review.decisions
    blockers: list[str] = []
    if not decisions.creator_identity_preserved:
        blockers.append("human_review_creator_identity_rejected")
    if not decisions.anatomy_acceptable:
        blockers.append("human_review_anatomy_rejected")
    if not decisions.operator_useful:
        blockers.append("human_review_operator_usefulness_rejected")
    if not decisions.approved_for_benchmark:
        blockers.append("human_review_benchmark_rejected")

    ratings = review.ratings
    components = [
        ratings.realism,
        ratings.attractiveness,
        ratings.creator_identity_similarity,
        ratings.face_stability,
        ratings.motion_naturalness,
        ratings.conversion_usefulness,
        ratings.intent_adherence,
        1.0 - ratings.face_artifact_score,
        1.0 - ratings.body_artifact_score,
    ]
    if ratings.hands_visible:
        if ratings.hand_artifact_score is None:
            raise LocalQueueError("arena_human_review_hand_evidence_missing")
        components.append(1.0 - ratings.hand_artifact_score)
    return blockers, sum(components) / len(components)


def _validate_human_review_binding(
    review: Any,
    *,
    plan: Mapping[str, Any],
    sample: Mapping[str, Any],
    analysis: Mapping[str, Any] | None = None,
    review_packet: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> None:
    reviewed_at = datetime.fromisoformat(review.reviewed_at.replace("Z", "+00:00"))
    plan_created_at = datetime.fromisoformat(
        str(plan["createdAt"]).replace("Z", "+00:00")
    )
    if reviewed_at.tzinfo is None or plan_created_at.tzinfo is None:
        raise LocalQueueError("arena_human_review_timestamp_timezone_missing")
    if reviewed_at > datetime.now(UTC):
        raise LocalQueueError("arena_human_review_from_future")
    if reviewed_at < plan_created_at:
        raise LocalQueueError("arena_human_review_predates_plan")
    if generated_at is not None:
        generated = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        if generated.tzinfo is None or reviewed_at < generated:
            raise LocalQueueError("arena_human_review_predates_generation")
    if (
        review.arena_plan_id != plan["planId"]
        or review.sample_id != sample["sampleId"]
        or review.blinded_candidate_id != sample["blindedCandidateId"]
        or review.source_sha256 != sample["sourceSha256"]
        or review.provenance.review_mode != "blinded"
        or review.provenance.unblinding_reason is not None
    ):
        raise LocalQueueError("arena_human_review_plan_binding_mismatch")
    required_references = {
        (str(plan["planId"]), str(plan["planFingerprint"])),
        (str(sample["sampleId"]), str(sample["queueJobFingerprint"])),
        (
            str(sample["identityProfileId"]),
            str(sample["identityProfileFingerprint"]),
        ),
        (
            str(sample["contentIntentId"]),
            str(sample["contentIntentFingerprint"]),
        ),
    }
    if analysis is not None:
        analysis_produced_at = datetime.fromisoformat(
            str(analysis["producedAt"]).replace("Z", "+00:00")
        )
        if analysis_produced_at.tzinfo is None or reviewed_at < analysis_produced_at:
            raise LocalQueueError("arena_human_review_predates_analysis")
        required_references.add(
            (str(analysis["analysisId"]), str(analysis["analysisFingerprint"]))
        )
        try:
            expected_sampling = HumanReviewSamplingEvidence.from_trusted_analysis(
                analysis
            )
        except ValueError as exc:
            raise LocalQueueError("arena_trusted_review_sampling_invalid") from exc
        if review.sampling_evidence != expected_sampling:
            raise LocalQueueError("arena_human_review_sampling_binding_mismatch")
    if review_packet is not None:
        candidate = [
            item
            for item in review_packet.get("candidates", [])
            if isinstance(item, dict)
            and item.get("blindedCandidateId") == sample["blindedCandidateId"]
        ]
        if (
            len(candidate) != 1
            or candidate[0].get("subjectSha256") != review.subject_sha256
        ):
            raise LocalQueueError("arena_human_review_packet_binding_mismatch")
        required_references.add(
            (
                str(review_packet["packetId"]),
                str(review_packet["packetFingerprint"]),
            )
        )
    if not required_references.issubset(set(review.provenance.source_references)):
        raise LocalQueueError("arena_human_review_provenance_incomplete")


def _arena_candidate_aggregates(
    sample_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    aggregate_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for result in sample_results:
        aggregate_groups[
            (str(result["modelId"]), str(result["capabilityCohort"]))
        ].append(result)
    aggregates: list[dict[str, Any]] = []
    for (model_id, capability), rows in sorted(aggregate_groups.items()):
        valid = [row for row in rows if row["promotionEvidenceValid"]]
        succeeded = [row for row in rows if row["status"] == "succeeded"]
        quality = [
            float(row["qualityScore"])
            for row in valid
            if row["qualityScore"] is not None
        ]
        latency = [
            float(row["wallTimeSeconds"])
            for row in valid
            if row["wallTimeSeconds"] is not None
        ]
        memory = [
            int(row["peakMemoryBytes"])
            for row in valid
            if row["peakMemoryBytes"] is not None
        ]
        aggregates.append(
            {
                "modelId": model_id,
                "capabilityCohort": capability,
                "plannedSamples": len(rows),
                "succeededSamples": len(succeeded),
                "failedSamples": len(rows) - len(succeeded),
                "failureRate": (len(rows) - len(succeeded)) / len(rows),
                "validSamples": len(valid),
                "promotionEligibleYield": len(valid) / len(rows),
                "meanHumanQualityScore": (
                    sum(quality) / len(quality)
                    if len(quality) == len(valid) and quality
                    else None
                ),
                "medianWallTimeSeconds": (
                    sorted(latency)[len(latency) // 2]
                    if len(latency) == len(valid) and latency
                    else None
                ),
                "medianPeakMemoryBytes": (
                    sorted(memory)[len(memory) // 2]
                    if len(memory) == len(valid) and memory
                    else None
                ),
                "benchmarkIds": sorted(
                    str(row["benchmarkId"])
                    for row in valid
                    if row["benchmarkId"] is not None
                ),
            }
        )
    return aggregates


def _attest_arena_evidence(
    core: Mapping[str, Any],
    *,
    fingerprint_field: str,
    issuer: str,
    issued_at: str,
    evidence_secret: str | None,
) -> dict[str, Any]:
    evidence_fingerprint = fingerprint(core)
    signed_payload = {**dict(core), fingerprint_field: evidence_fingerprint}
    attestation = sign_evidence_attestation(
        signed_payload,
        issuer=issuer,
        issued_at=issued_at,
        secret=evidence_secret or load_evidence_secret(),
    )
    return {
        **dict(core),
        "producerAttestation": attestation,
        fingerprint_field: evidence_fingerprint,
    }


def _verify_arena_evidence(
    payload: Mapping[str, Any],
    *,
    fingerprint_field: str,
    issuer: str,
    evidence_secret: str | None,
) -> tuple[dict[str, Any], str]:
    exact = dict(payload)
    claimed = _valid_sha256(exact.pop(fingerprint_field, None), fingerprint_field)
    attestation = exact.pop("producerAttestation", None)
    if fingerprint(exact) != claimed:
        raise LocalQueueError(f"arena_{fingerprint_field}_mismatch")
    if not isinstance(attestation, dict):
        raise LocalQueueError(f"arena_{fingerprint_field}_attestation_missing")
    signed_payload = {**exact, fingerprint_field: claimed}
    try:
        verify_evidence_attestation(
            attestation,
            signed_payload,
            secret=evidence_secret or load_evidence_secret(),
            expected_issuer=issuer,
        )
    except EvidenceAttestationError as exc:
        raise LocalQueueError(f"arena_{fingerprint_field}_attestation_invalid") from exc
    return exact, claimed


def validate_arena_review_packet(
    packet: Mapping[str, Any],
    *,
    arena_plan: Mapping[str, Any],
    evidence_secret: str | None = None,
) -> dict[str, Any]:
    validate_local_model_arena_review_packet(dict(packet))
    plan = validate_arena_plan(arena_plan)
    core, claimed = _verify_arena_evidence(
        packet,
        fingerprint_field="packetFingerprint",
        issuer=REVIEW_PACKET_ISSUER,
        evidence_secret=evidence_secret,
    )
    if (
        core.get("schema") != REVIEW_PACKET_SCHEMA
        or core.get("arenaPlanId") != plan["planId"]
        or core.get("arenaPlanFingerprint") != plan["planFingerprint"]
        or core.get("providerCalls") != 0
        or core.get("productionWrites") != 0
    ):
        raise LocalQueueError("arena_review_packet_plan_binding_mismatch")
    candidates = core.get("candidates")
    if not isinstance(candidates, list) or core.get("expectedCandidateCount") != len(
        candidates
    ):
        raise LocalQueueError("arena_review_packet_denominator_mismatch")
    if [candidate.get("reviewOrdinal") for candidate in candidates] != list(
        range(1, len(candidates) + 1)
    ):
        raise LocalQueueError("arena_review_packet_ordinal_mismatch")
    planned_by_blind = {
        str(sample["blindedCandidateId"]): sample for sample in plan["samples"]
    }
    observed_blind: set[str] = set()
    observed_paths: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise LocalQueueError("arena_review_packet_candidate_invalid")
        blind = str(candidate.get("blindedCandidateId") or "")
        planned = planned_by_blind.get(blind)
        subject = Path(str(candidate.get("subjectPath") or "")).resolve()
        planned_output = (
            Path(str(planned["outputPath"])).resolve() if planned is not None else None
        )
        if blind in observed_blind or str(subject) in observed_paths:
            raise LocalQueueError("arena_review_packet_duplicate_candidate")
        observed_blind.add(blind)
        observed_paths.add(str(subject))
        if (
            planned is None
            or candidate.get("creatorId") != planned["creatorId"]
            or candidate.get("contentIntentId") != planned["contentIntentId"]
            or planned_output is None
            or not planned_output.is_file()
            or planned_output.is_symlink()
            or not subject.is_file()
            or subject.is_symlink()
            or sha256_file(planned_output) != candidate.get("subjectSha256")
            or sha256_file(subject) != candidate.get("subjectSha256")
        ):
            raise LocalQueueError("arena_review_packet_candidate_binding_mismatch")
    if observed_blind != set(planned_by_blind):
        raise LocalQueueError("arena_review_packet_plan_sample_set_mismatch")
    return {
        **core,
        "producerAttestation": dict(packet["producerAttestation"]),
        "packetFingerprint": claimed,
    }


def build_arena_review_packet(
    *,
    arena_plan: Mapping[str, Any],
    queue: LocalGenerationQueue,
    created_at: str,
    evidence_secret: str | None = None,
) -> dict[str, Any]:
    plan = validate_arena_plan(arena_plan)
    states = queue.states()
    candidates: list[dict[str, Any]] = []
    packet_id = f"arena_review_packet_{plan['planFingerprint'][:24]}"
    first_output = Path(str(plan["samples"][0]["outputPath"])).resolve()
    blinded_root = first_output.parent.parent / "review_packets" / packet_id
    for sample in plan["samples"]:
        state = states.get(str(sample["queueJob"]["jobId"]))
        subject = Path(str(sample["outputPath"])).resolve()
        if (
            state is None
            or state.status != "succeeded"
            or fingerprint(state.job.as_dict()) != sample["queueJobFingerprint"]
            or not subject.is_file()
            or subject.is_symlink()
        ):
            raise LocalQueueError("arena_review_packet_requires_completed_grid")
        subject_sha = sha256_file(subject)
        if state.last_event.get("payload", {}).get("outputSha256") != subject_sha:
            raise LocalQueueError("arena_review_packet_output_substituted")
        blinded_subject = blinded_root / (
            f"{sample['blindedCandidateId']}{subject.suffix.lower()}"
        )
        blinded_subject.parent.mkdir(parents=True, exist_ok=True)
        if blinded_subject.exists():
            if (
                not blinded_subject.is_file()
                or blinded_subject.is_symlink()
                or sha256_file(blinded_subject) != subject_sha
            ):
                raise LocalQueueError("arena_review_packet_subject_collision")
        else:
            os.link(subject, blinded_subject)
        candidates.append(
            {
                "reviewOrdinal": 0,
                "blindedCandidateId": sample["blindedCandidateId"],
                "creatorId": sample["creatorId"],
                "contentIntentId": sample["contentIntentId"],
                "subjectPath": str(blinded_subject),
                "subjectSha256": subject_sha,
            }
        )
    secrets.SystemRandom().shuffle(candidates)
    for ordinal, candidate in enumerate(candidates, start=1):
        candidate["reviewOrdinal"] = ordinal
    core = {
        "schema": REVIEW_PACKET_SCHEMA,
        "packetId": packet_id,
        "arenaPlanId": plan["planId"],
        "arenaPlanFingerprint": plan["planFingerprint"],
        "createdAt": created_at,
        "expectedCandidateCount": len(candidates),
        "candidates": candidates,
        "providerCalls": 0,
        "productionWrites": 0,
    }
    packet = _attest_arena_evidence(
        core,
        fingerprint_field="packetFingerprint",
        issuer=REVIEW_PACKET_ISSUER,
        issued_at=created_at,
        evidence_secret=evidence_secret,
    )
    return validate_arena_review_packet(
        packet, arena_plan=plan, evidence_secret=evidence_secret
    )


def _locked_review_bindings(
    *,
    plan: Mapping[str, Any],
    packet: Mapping[str, Any],
    human_reviews: HumanMediaReviewStore,
) -> tuple[list[dict[str, Any]], str]:
    reviews = human_reviews.reviews()
    by_blind: dict[str, list[Any]] = defaultdict(list)
    for review in reviews.values():
        if review.arena_plan_id == plan["planId"]:
            by_blind[review.blinded_candidate_id].append(review)
    planned_by_blind = {
        str(sample["blindedCandidateId"]): sample for sample in plan["samples"]
    }
    bindings: list[dict[str, Any]] = []
    locked_reviews: list[dict[str, Any]] = []
    for candidate in packet["candidates"]:
        blind = str(candidate["blindedCandidateId"])
        matches = by_blind.get(blind, [])
        if len(matches) != 1:
            raise LocalQueueError("arena_unblinding_requires_exact_signed_review_set")
        review = matches[0]
        sample = planned_by_blind.get(blind)
        if (
            sample is None
            or review.operator_attestation is None
            or review.provenance.review_mode != "blinded"
            or review.provenance.unblinding_reason is not None
            or review.sample_id != sample["sampleId"]
            or review.subject_sha256 != candidate["subjectSha256"]
            or review.source_sha256 != sample["sourceSha256"]
            or (str(packet["packetId"]), str(packet["packetFingerprint"]))
            not in set(review.provenance.source_references)
        ):
            raise LocalQueueError("arena_unblinding_review_binding_mismatch")
        locked_reviews.append(
            {
                "blindedCandidateId": blind,
                "subjectSha256": review.subject_sha256,
                "humanReviewId": review.review_id,
                "humanReviewFingerprint": review.review_fingerprint,
            }
        )
        bindings.append(
            {
                **locked_reviews[-1],
                "sampleId": sample["sampleId"],
                "modelId": sample["modelId"],
                "modelRevision": sample["modelRevision"],
                "modelManifestSha256": sample["modelManifestSha256"],
                "modelDeepVerificationFingerprint": sample[
                    "modelDeepVerificationFingerprint"
                ],
                "modelFingerprint": sample["modelFingerprint"],
            }
        )
    bindings.sort(key=lambda item: str(item["blindedCandidateId"]))
    locked_reviews.sort(key=lambda item: str(item["blindedCandidateId"]))
    return bindings, fingerprint({"reviews": locked_reviews})


def build_arena_unblinding_receipt(
    *,
    arena_plan: Mapping[str, Any],
    review_packet: Mapping[str, Any],
    human_reviews: HumanMediaReviewStore,
    created_at: str,
    evidence_secret: str | None = None,
) -> dict[str, Any]:
    plan = validate_arena_plan(arena_plan)
    packet = validate_arena_review_packet(
        review_packet, arena_plan=plan, evidence_secret=evidence_secret
    )
    bindings, locked_fingerprint = _locked_review_bindings(
        plan=plan, packet=packet, human_reviews=human_reviews
    )
    core = {
        "schema": UNBLINDING_RECEIPT_SCHEMA,
        "receiptId": f"arena_unblinding_{packet['packetFingerprint'][:24]}",
        "arenaPlanId": plan["planId"],
        "arenaPlanFingerprint": plan["planFingerprint"],
        "reviewPacketId": packet["packetId"],
        "reviewPacketFingerprint": packet["packetFingerprint"],
        "createdAt": created_at,
        "expectedReviewCount": len(bindings),
        "lockedReviewSetFingerprint": locked_fingerprint,
        "bindings": bindings,
        "providerCalls": 0,
        "productionWrites": 0,
    }
    receipt = _attest_arena_evidence(
        core,
        fingerprint_field="receiptFingerprint",
        issuer=UNBLINDING_RECEIPT_ISSUER,
        issued_at=created_at,
        evidence_secret=evidence_secret,
    )
    return validate_arena_unblinding_receipt(
        receipt,
        arena_plan=plan,
        review_packet=packet,
        human_reviews=human_reviews,
        evidence_secret=evidence_secret,
    )


def validate_arena_unblinding_receipt(
    receipt: Mapping[str, Any],
    *,
    arena_plan: Mapping[str, Any],
    review_packet: Mapping[str, Any],
    human_reviews: HumanMediaReviewStore,
    evidence_secret: str | None = None,
) -> dict[str, Any]:
    validate_local_model_arena_unblinding_receipt(dict(receipt))
    plan = validate_arena_plan(arena_plan)
    packet = validate_arena_review_packet(
        review_packet, arena_plan=plan, evidence_secret=evidence_secret
    )
    core, claimed = _verify_arena_evidence(
        receipt,
        fingerprint_field="receiptFingerprint",
        issuer=UNBLINDING_RECEIPT_ISSUER,
        evidence_secret=evidence_secret,
    )
    if (
        core.get("schema") != UNBLINDING_RECEIPT_SCHEMA
        or core.get("arenaPlanId") != plan["planId"]
        or core.get("arenaPlanFingerprint") != plan["planFingerprint"]
        or core.get("reviewPacketId") != packet["packetId"]
        or core.get("reviewPacketFingerprint") != packet["packetFingerprint"]
        or core.get("providerCalls") != 0
        or core.get("productionWrites") != 0
    ):
        raise LocalQueueError("arena_unblinding_receipt_binding_mismatch")
    expected_bindings, locked_fingerprint = _locked_review_bindings(
        plan=plan, packet=packet, human_reviews=human_reviews
    )
    if (
        core.get("expectedReviewCount") != len(expected_bindings)
        or core.get("bindings") != expected_bindings
        or core.get("lockedReviewSetFingerprint") != locked_fingerprint
    ):
        raise LocalQueueError("arena_unblinding_locked_review_set_mismatch")
    return {
        **core,
        "producerAttestation": dict(receipt["producerAttestation"]),
        "receiptFingerprint": claimed,
    }


class LocalModelArenaStore:
    """Persist immutable Arena plans and outcomes beside benchmark evidence."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.plans = self.root / "arena_plans"
        self.review_packets = self.root / "arena_review_packets"
        self.unblinding_receipts = self.root / "arena_unblinding_receipts"
        self.events = AppendOnlyJournal(self.root / "arena_events.jsonl")
        self._mutation = self.root / "arena_mutation"

    def persist_plan(self, plan: Mapping[str, Any]) -> Path:
        payload = validate_arena_plan(plan)
        plan_id = str(payload["planId"])
        path = self.plans / f"{plan_id}.json"
        encoded = _canonical(payload)
        with file_lock(self._mutation):
            if path.exists():
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or path.read_text(encoding="utf-8") != encoded
                ):
                    raise LocalQueueError("arena_plan_identity_collision")
                return path
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, encoded)
            if (
                validate_arena_plan(json.loads(path.read_text(encoding="utf-8")))
                != payload
            ):
                raise LocalQueueError("arena_plan_persistence_failed")
        return path

    def load_plan(self, plan_id: str) -> dict[str, Any]:
        path = self.plans / f"{plan_id}.json"
        if not path.is_file() or path.is_symlink():
            raise LocalQueueError("arena_plan_not_found")
        return validate_arena_plan(json.loads(path.read_text(encoding="utf-8")))

    def persist_review_packet(
        self, packet: Mapping[str, Any], *, evidence_secret: str | None = None
    ) -> Path:
        plan = self.load_plan(str(packet.get("arenaPlanId") or ""))
        payload = validate_arena_review_packet(
            packet, arena_plan=plan, evidence_secret=evidence_secret
        )
        path = self.review_packets / f"{payload['packetId']}.json"
        with file_lock(self._mutation):
            _write_exact_json(path, payload)
        return path

    def load_review_packet(
        self, plan_id: str, *, evidence_secret: str | None = None
    ) -> dict[str, Any]:
        plan = self.load_plan(plan_id)
        packet_id = f"arena_review_packet_{plan['planFingerprint'][:24]}"
        path = self.review_packets / f"{packet_id}.json"
        if not path.is_file() or path.is_symlink():
            raise LocalQueueError("arena_review_packet_not_found")
        return validate_arena_review_packet(
            json.loads(path.read_text(encoding="utf-8")),
            arena_plan=plan,
            evidence_secret=evidence_secret,
        )

    def persist_unblinding_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        human_reviews: HumanMediaReviewStore,
        evidence_secret: str | None = None,
    ) -> Path:
        plan = self.load_plan(str(receipt.get("arenaPlanId") or ""))
        packet = self.load_review_packet(
            str(plan["planId"]), evidence_secret=evidence_secret
        )
        payload = validate_arena_unblinding_receipt(
            receipt,
            arena_plan=plan,
            review_packet=packet,
            human_reviews=human_reviews,
            evidence_secret=evidence_secret,
        )
        path = self.unblinding_receipts / f"{payload['receiptId']}.json"
        with file_lock(self._mutation):
            _write_exact_json(path, payload)
        return path

    def load_unblinding_receipt(
        self,
        plan_id: str,
        *,
        human_reviews: HumanMediaReviewStore,
        evidence_secret: str | None = None,
    ) -> dict[str, Any]:
        plan = self.load_plan(plan_id)
        packet = self.load_review_packet(plan_id, evidence_secret=evidence_secret)
        receipt_id = f"arena_unblinding_{packet['packetFingerprint'][:24]}"
        path = self.unblinding_receipts / f"{receipt_id}.json"
        if not path.is_file() or path.is_symlink():
            raise LocalQueueError("arena_unblinding_receipt_not_found")
        return validate_arena_unblinding_receipt(
            json.loads(path.read_text(encoding="utf-8")),
            arena_plan=plan,
            review_packet=packet,
            human_reviews=human_reviews,
            evidence_secret=evidence_secret,
        )

    def record_terminal(
        self,
        *,
        plan_id: str,
        sample_id: str,
        status: str,
        reason: str,
        output_sha256: str | None = None,
        benchmark_id: str | None = None,
        human_review_id: str | None = None,
        queue: LocalGenerationQueue | None = None,
        benchmarks: LocalModelBenchmarkStore | None = None,
        human_reviews: HumanMediaReviewStore | None = None,
    ) -> dict[str, Any]:
        if status not in RECORDED_TERMINAL_STATUSES:
            raise ValueError("arena_terminal_status_invalid")
        plan = self.load_plan(plan_id)
        samples = {str(item["sampleId"]): item for item in plan["samples"]}
        sample = samples.get(sample_id)
        if sample is None:
            raise LocalQueueError("arena_sample_not_in_plan")
        if status == "succeeded":
            if output_sha256 is None or benchmark_id is None or human_review_id is None:
                raise LocalQueueError("arena_success_evidence_incomplete")
            output = Path(str(sample["outputPath"])).resolve()
            if not output.is_file() or sha256_file(output) != output_sha256:
                raise LocalQueueError("arena_success_output_substituted")
            if queue is None or benchmarks is None or human_reviews is None:
                raise LocalQueueError("arena_success_verification_context_required")
            queue_state = queue.states().get(str(sample["queueJob"]["jobId"]))
            if (
                queue_state is None
                or queue_state.status != "succeeded"
                or fingerprint(queue_state.job.as_dict())
                != sample["queueJobFingerprint"]
                or queue_state.last_event.get("payload", {}).get("outputSha256")
                != output_sha256
            ):
                raise LocalQueueError("arena_success_queue_evidence_mismatch")
            receipt = benchmarks.all_receipts().get(benchmark_id)
            execution = queue.execution_evidence(queue_state.job.job_id)
            if (
                receipt is None
                or receipt.job_id != queue_state.job.job_id
                or receipt.output_sha256 != output_sha256
                or receipt.model_fingerprint != sample["modelFingerprint"]
                or receipt.task_fingerprint != sample["queueJob"]["taskFingerprint"]
                or receipt.benchmark_recipe_id != sample["benchmarkRecipe"]["recipeId"]
                or receipt.benchmark_recipe_fingerprint
                != sample["benchmarkRecipeFingerprint"]
                or receipt.analyzer_registry_id
                != sample["analyzerRegistry"]["registryId"]
                or receipt.analyzer_registry_fingerprint
                != sample["analyzerRegistryFingerprint"]
                or receipt.execution_attempt_count != execution.get("attemptCount")
                or receipt.execution_retry_count != execution.get("retryCount")
            ):
                raise LocalQueueError("arena_success_benchmark_evidence_mismatch")
            review = human_reviews.reviews().get(human_review_id)
            if review is None or review.subject_sha256 != output_sha256:
                raise LocalQueueError("arena_success_human_review_missing_or_mismatch")
            _validate_human_review_binding(
                review,
                plan=plan,
                sample=sample,
                review_packet=(
                    self.load_review_packet(plan_id)
                    if plan["purpose"] == "promotion_eligible"
                    else None
                ),
            )
        elif any(
            value is not None
            for value in (output_sha256, benchmark_id, human_review_id)
        ):
            raise LocalQueueError("arena_non_success_must_not_claim_success_evidence")
        terminal_payload = {
            "schema": EVENT_SCHEMA,
            "planId": plan_id,
            "planFingerprint": plan["planFingerprint"],
            "sampleId": sample_id,
            "queueJobFingerprint": sample["queueJobFingerprint"],
            "status": status,
            "reason": _required_text(reason, "terminal_reason"),
            "outputSha256": output_sha256,
            "benchmarkId": benchmark_id,
            "humanReviewId": human_review_id,
            "providerCalls": 0,
            "productionWrites": 0,
        }
        with file_lock(self._mutation):
            prior = [
                event
                for event in self.events.read().events
                if event.get("eventType") == "arena_sample_terminal"
                and event.get("payload", {}).get("planId") == plan_id
                and event.get("payload", {}).get("sampleId") == sample_id
            ]
            if prior:
                if len(prior) == 1 and prior[0].get("payload") == terminal_payload:
                    return prior[0]
                raise LocalQueueError("arena_terminal_sample_collision")
            return self.events.append(
                "arena_sample_terminal",
                terminal_payload,
            )

    def summarize(
        self,
        plan_id: str,
        *,
        queue: LocalGenerationQueue,
        benchmarks: LocalModelBenchmarkStore,
        human_reviews: HumanMediaReviewStore | None = None,
    ) -> dict[str, Any]:
        plan = self.load_plan(plan_id)
        packet: dict[str, Any] | None = None
        review_evidence = {
            "reviewPacketId": None,
            "reviewPacketFingerprint": None,
            "unblindingReceiptId": None,
            "unblindingReceiptFingerprint": None,
        }
        if plan["purpose"] == "promotion_eligible":
            if human_reviews is None:
                raise LocalQueueError("arena_promotion_review_store_missing")
            packet = self.load_review_packet(plan_id)
            unblinding = self.load_unblinding_receipt(
                plan_id, human_reviews=human_reviews
            )
            review_evidence = {
                "reviewPacketId": packet["packetId"],
                "reviewPacketFingerprint": packet["packetFingerprint"],
                "unblindingReceiptId": unblinding["receiptId"],
                "unblindingReceiptFingerprint": unblinding["receiptFingerprint"],
            }
        terminal_events = [
            dict(event["payload"])
            for event in self.events.read().events
            if event.get("eventType") == "arena_sample_terminal"
            and event.get("payload", {}).get("planId") == plan_id
        ]
        by_sample: dict[str, dict[str, Any]] = {}
        for event in terminal_events:
            sample_id = str(event["sampleId"])
            if sample_id in by_sample:
                raise LocalQueueError("arena_duplicate_terminal_sample")
            by_sample[sample_id] = event
        queue_states = queue.states()
        receipts = benchmarks.all_receipts()
        reviews = human_reviews.reviews() if human_reviews is not None else {}
        benchmark_ids: set[str] = set()
        sample_results: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        for sample in plan["samples"]:
            sample_id = str(sample["sampleId"])
            queue_job_id = str(sample["queueJob"]["jobId"])
            queue_state = queue_states.get(queue_job_id)
            terminal = by_sample.get(sample_id)
            if terminal is None:
                if queue_state is not None and queue_state.status in {
                    "failed",
                    "interrupted",
                    "cancelled",
                }:
                    status = queue_state.status
                    reason = str(
                        queue_state.last_event.get("payload", {}).get("reason")
                        or f"queue_job_{queue_state.status}_before_arena_finalize"
                    )
                elif (
                    queue_state is not None
                    and queue_state.status == "queued"
                    and queue_state.last_event.get("eventType")
                    == "job_admission_blocked"
                ):
                    status = "resource_blocked"
                    reason = str(
                        queue_state.last_event.get("payload", {}).get("reason")
                        or "queue_resource_admission_blocked"
                    )
                else:
                    status = "missing"
                    reason = "arena_terminal_event_missing"
                benchmark_id = None
                output_sha = None
                review_id = None
            else:
                status = str(terminal["status"])
                reason = str(terminal["reason"])
                benchmark_id = terminal.get("benchmarkId")
                output_sha = terminal.get("outputSha256")
                review_id = terminal.get("humanReviewId")
            counts[status] += 1
            blockers: list[str] = []
            execution_evidence: dict[str, Any] = {
                "status": "missing",
                "attemptCount": 0,
                "retryCount": 0,
                "admissionBlockCount": 0,
                "failureClass": "queue_job_missing",
                "executionMeasurement": {
                    "available": False,
                    "reason": "execution_measurement_unavailable",
                },
                "localCost": {
                    "available": False,
                    "currency": "USD",
                    "reason": "local_compute_cost_not_metered",
                    "value": None,
                },
            }
            if queue_state is None:
                blockers.append("queue_job_missing")
            else:
                execution_evidence = queue.execution_evidence(queue_job_id)
                if status == "succeeded" and queue_state.status != "succeeded":
                    blockers.append("queue_job_not_succeeded")
                if (
                    fingerprint(queue_state.job.as_dict())
                    != sample["queueJobFingerprint"]
                ):
                    blockers.append("queue_job_substituted")
            if status == "succeeded":
                if benchmark_id in benchmark_ids:
                    blockers.append("duplicate_benchmark_identity")
                if benchmark_id is not None:
                    benchmark_ids.add(str(benchmark_id))
                receipt = receipts.get(str(benchmark_id))
                if receipt is None:
                    blockers.append("benchmark_receipt_missing")
                else:
                    if receipt.job_id != queue_job_id:
                        blockers.append("benchmark_queue_job_mismatch")
                    if receipt.output_sha256 != output_sha:
                        blockers.append("benchmark_output_substituted")
                    if not receipt.all_qc_passed:
                        blockers.append("benchmark_qc_failed")
                    if (
                        receipt.benchmark_recipe_fingerprint
                        != sample["benchmarkRecipeFingerprint"]
                    ):
                        blockers.append("benchmark_recipe_mismatch")
                    if (
                        receipt.analyzer_registry_fingerprint
                        != sample["analyzerRegistryFingerprint"]
                    ):
                        blockers.append("benchmark_analyzer_registry_drift")
                    if (
                        receipt.model_deep_verification_fingerprint
                        != sample["modelDeepVerificationFingerprint"]
                    ):
                        blockers.append("benchmark_model_deep_verification_drift")
                review = reviews.get(str(review_id))
                if human_reviews is None:
                    blockers.append("human_review_store_missing")
                elif review is None:
                    blockers.append("human_review_missing")
                elif (
                    review.sample_id != sample_id
                    or review.subject_sha256 != output_sha
                    or review.source_sha256 != sample["sourceSha256"]
                    or review.blinded_candidate_id != sample["blindedCandidateId"]
                ):
                    blockers.append("human_review_mismatch")
                else:
                    try:
                        _validate_human_review_binding(
                            review,
                            plan=plan,
                            sample=sample,
                            review_packet=packet,
                            generated_at=(
                                str(queue_state.last_event.get("occurredAt") or "")
                                if queue_state is not None
                                else None
                            ),
                        )
                    except LocalQueueError as exc:
                        blockers.append(str(exc))
                    review_blockers, _ = _human_review_evidence(review)
                    blockers.extend(review_blockers)
            else:
                review = None
            quality_score = None
            wall_time_seconds = None
            peak_memory_bytes = None
            if status == "succeeded" and benchmark_id is not None:
                receipt = receipts.get(str(benchmark_id))
                if receipt is not None:
                    wall_time_seconds = receipt.wall_time_seconds
                    peak_memory_bytes = receipt.peak_memory_bytes
            if review is not None:
                _, quality_score = _human_review_evidence(review)
            sample_results.append(
                {
                    "sampleId": sample_id,
                    "creatorId": sample["creatorId"],
                    "identityProfileId": sample["identityProfileId"],
                    "identityProfileFingerprint": sample["identityProfileFingerprint"],
                    "contentIntentId": sample["contentIntentId"],
                    "contentIntentFingerprint": sample["contentIntentFingerprint"],
                    "modelId": sample["modelId"],
                    "capabilityCohort": sample["capabilityCohort"],
                    "taskKind": sample["taskKind"],
                    "status": status,
                    "reason": reason,
                    "outputSha256": output_sha,
                    "benchmarkId": benchmark_id,
                    "humanReviewId": review_id,
                    "qualityScore": quality_score,
                    "wallTimeSeconds": wall_time_seconds,
                    "peakMemoryBytes": peak_memory_bytes,
                    "executionEvidence": execution_evidence,
                    "blockingReasons": sorted(set(blockers)),
                    "promotionEvidenceValid": status == "succeeded" and not blockers,
                }
            )
        outputs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for result in sample_results:
            output_sha = result.get("outputSha256")
            if result.get("status") == "succeeded" and isinstance(output_sha, str):
                outputs[output_sha].append(result)
        for rows in outputs.values():
            if len(rows) <= 1:
                continue
            for row in rows:
                row["blockingReasons"] = sorted(
                    {*row["blockingReasons"], "duplicate_output_sha256"}
                )
                row["promotionEvidenceValid"] = False
        if sum(counts.values()) != int(plan["expectedSampleCount"]):
            raise LocalQueueError("arena_summary_denominator_mismatch")
        aggregates = _arena_candidate_aggregates(sample_results)
        core = {
            "schema": SUMMARY_SCHEMA,
            "summaryId": f"arena_summary_{plan_id}",
            "planId": plan_id,
            "planFingerprint": plan["planFingerprint"],
            "purpose": plan["purpose"],
            "expectedSampleCount": plan["expectedSampleCount"],
            "sampleCounts": {
                status: counts.get(status, 0) for status in sorted(TERMINAL_STATUSES)
            },
            "promotionEligibleYield": (
                sum(item["promotionEvidenceValid"] for item in sample_results)
                / int(plan["expectedSampleCount"])
            ),
            "samples": sample_results,
            "candidateAggregates": aggregates,
            "reviewEvidence": review_evidence,
            "providerCalls": 0,
            "productionWrites": 0,
        }
        return validate_arena_summary(
            {**core, "summaryFingerprint": fingerprint(core)}, arena_plan=plan
        )


def validate_arena_summary(
    summary: Mapping[str, Any], *, arena_plan: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    validate_local_model_arena_summary(dict(summary))
    payload = dict(summary)
    if payload.get("schema") != SUMMARY_SCHEMA:
        raise ValueError("arena_summary_schema_mismatch")
    claimed = _valid_sha256(
        payload.pop("summaryFingerprint", None), "summary_fingerprint"
    )
    if fingerprint(payload) != claimed:
        raise LocalQueueError("arena_summary_fingerprint_mismatch")
    samples = payload.get("samples")
    if not isinstance(samples, list) or len(samples) != payload.get(
        "expectedSampleCount"
    ):
        raise LocalQueueError("arena_summary_denominator_mismatch")
    counts = payload.get("sampleCounts")
    if not isinstance(counts, dict) or sum(
        int(counts.get(status, 0)) for status in TERMINAL_STATUSES
    ) != len(samples):
        raise LocalQueueError("arena_summary_terminal_counts_mismatch")
    if payload.get("providerCalls") != 0 or payload.get("productionWrites") != 0:
        raise LocalQueueError("arena_summary_external_activity_forbidden")
    review_evidence = payload.get("reviewEvidence")
    if not isinstance(review_evidence, dict):
        raise LocalQueueError("arena_summary_review_evidence_missing")
    review_values = tuple(
        review_evidence.get(field)
        for field in (
            "reviewPacketId",
            "reviewPacketFingerprint",
            "unblindingReceiptId",
            "unblindingReceiptFingerprint",
        )
    )
    if payload.get("purpose") == "promotion_eligible":
        if any(value is None for value in review_values):
            raise LocalQueueError("arena_summary_promotion_review_evidence_missing")
    elif any(value is not None for value in review_values):
        raise LocalQueueError("arena_summary_exploratory_review_evidence_forbidden")
    sample_ids = [str(sample["sampleId"]) for sample in samples]
    if len(sample_ids) != len(set(sample_ids)):
        raise LocalQueueError("arena_summary_duplicate_sample_identity")
    if not _finite_number(payload.get("promotionEligibleYield")):
        raise LocalQueueError("arena_summary_non_finite_number")
    for sample in samples:
        for field in ("qualityScore", "wallTimeSeconds", "peakMemoryBytes"):
            value = sample.get(field)
            if value is not None and not _finite_number(value):
                raise LocalQueueError("arena_summary_non_finite_number")
        execution = sample.get("executionEvidence")
        if not isinstance(execution, dict):
            raise LocalQueueError("arena_summary_execution_evidence_missing")
        measurement = execution.get("executionMeasurement")
        if sample.get("status") == "succeeded":
            if (
                execution.get("status") != "succeeded"
                or execution.get("failureClass") is not None
                or not isinstance(execution.get("attemptCount"), int)
                or execution["attemptCount"] < 1
                or execution.get("retryCount") != execution["attemptCount"] - 1
                or not isinstance(measurement, dict)
                or measurement.get("available") is not True
                or not _finite_number(measurement.get("wallTimeSeconds"))
                or not isinstance(measurement.get("peakMemoryBytes"), int)
                or measurement["peakMemoryBytes"] <= 0
            ):
                raise LocalQueueError("arena_summary_success_execution_mismatch")
        elif sample.get("promotionEvidenceValid") is True:
            raise LocalQueueError("arena_summary_non_success_claims_promotion")
    for aggregate in payload.get("candidateAggregates", []):
        if not isinstance(aggregate, dict):
            raise LocalQueueError("arena_summary_candidate_aggregate_invalid")
        for field in (
            "failureRate",
            "promotionEligibleYield",
            "meanHumanQualityScore",
            "medianWallTimeSeconds",
            "medianPeakMemoryBytes",
        ):
            value = aggregate.get(field)
            if value is not None and not _finite_number(value):
                raise LocalQueueError("arena_summary_non_finite_number")
    observed_counts = Counter(str(sample["status"]) for sample in samples)
    expected_counts = {
        status: observed_counts.get(status, 0) for status in sorted(TERMINAL_STATUSES)
    }
    if counts != expected_counts:
        raise LocalQueueError("arena_summary_status_counts_drift")
    valid_samples = [
        sample for sample in samples if sample["promotionEvidenceValid"] is True
    ]
    if any(
        sample["status"] != "succeeded"
        or sample["blockingReasons"]
        or any(
            sample[field] is None
            for field in (
                "qualityScore",
                "wallTimeSeconds",
                "peakMemoryBytes",
                "benchmarkId",
                "humanReviewId",
                "outputSha256",
            )
        )
        for sample in valid_samples
    ):
        raise LocalQueueError("arena_summary_invalid_promotion_evidence_claim")
    expected_yield = len(valid_samples) / len(samples)
    if payload.get("promotionEligibleYield") != expected_yield:
        raise LocalQueueError("arena_summary_yield_drift")
    benchmark_ids = [
        str(sample["benchmarkId"])
        for sample in samples
        if sample.get("benchmarkId") is not None
    ]
    if len(benchmark_ids) != len(set(benchmark_ids)):
        raise LocalQueueError("arena_summary_duplicate_benchmark_identity")
    duplicate_outputs = {
        output_sha
        for output_sha, count in Counter(
            str(sample["outputSha256"])
            for sample in samples
            if sample.get("status") == "succeeded"
            and sample.get("outputSha256") is not None
        ).items()
        if count > 1
    }
    if any(
        sample.get("outputSha256") in duplicate_outputs
        and (
            sample.get("promotionEvidenceValid") is True
            or "duplicate_output_sha256" not in sample.get("blockingReasons", [])
        )
        for sample in samples
    ):
        raise LocalQueueError("arena_summary_duplicate_output_claim")
    expected_aggregates = _arena_candidate_aggregates(samples)
    if payload.get("candidateAggregates") != expected_aggregates:
        raise LocalQueueError("arena_summary_candidate_aggregate_drift")
    if arena_plan is not None:
        plan = validate_arena_plan(arena_plan)
        if (
            payload.get("planId") != plan.get("planId")
            or payload.get("planFingerprint") != plan.get("planFingerprint")
            or payload.get("purpose") != plan.get("purpose")
        ):
            raise LocalQueueError("arena_summary_plan_binding_mismatch")
        planned = {str(item["sampleId"]): item for item in plan["samples"]}
        if set(sample_ids) != set(planned):
            raise LocalQueueError("arena_summary_plan_sample_set_mismatch")
        for sample in samples:
            frozen = planned[str(sample["sampleId"])]
            for field in (
                "creatorId",
                "identityProfileId",
                "identityProfileFingerprint",
                "contentIntentId",
                "contentIntentFingerprint",
                "modelId",
                "capabilityCohort",
                "taskKind",
            ):
                if sample.get(field) != frozen.get(field):
                    raise LocalQueueError("arena_summary_plan_sample_binding_mismatch")
    return {**payload, "summaryFingerprint": claimed}


def _sample(plan: Mapping[str, Any], sample_id: str) -> dict[str, Any]:
    matches = [
        dict(item)
        for item in plan.get("samples", [])
        if isinstance(item, dict) and item.get("sampleId") == sample_id
    ]
    if len(matches) != 1:
        raise LocalQueueError("arena_sample_not_found_exactly_once")
    return matches[0]


def _request_from_sample(sample: Mapping[str, Any]) -> LocalVideoRequest:
    return LocalVideoRequest(
        model_id=str(sample["modelId"]),
        image_path=Path(str(sample["sourcePath"])),
        prompt=str(sample["prompt"]),
        output_path=Path(str(sample["outputPath"])),
        duration_seconds=int(sample["durationSeconds"]),
        resolution=str(sample["resolution"]),
        seed=int(sample["seed"]),
        audio_mode=str(sample["audioMode"]),  # type: ignore[arg-type]
        audio_path=(
            Path(str(sample["audioPath"]))
            if sample.get("audioPath") is not None
            else None
        ),
        task=str(sample["taskKind"]),  # type: ignore[arg-type]
        benchmark_recipe=dict(sample["benchmarkRecipe"]),
        analyzer_registry=dict(sample["analyzerRegistry"]),
        execution_context="arena_benchmark",
        arena_benchmark_binding=_arena_benchmark_binding(
            sample_id=str(sample["sampleId"]),
            blinded_candidate_id=str(sample["blindedCandidateId"]),
            source_sha256=str(sample["sourceSha256"]),
            identity_profile_id=str(sample["identityProfileId"]),
            identity_profile_fingerprint=str(sample["identityProfileFingerprint"]),
            content_intent_id=str(sample["contentIntentId"]),
            content_intent_fingerprint=str(sample["contentIntentFingerprint"]),
            benchmark_recipe_fingerprint=str(sample["benchmarkRecipeFingerprint"]),
            analyzer_registry_fingerprint=str(sample["analyzerRegistryFingerprint"]),
            model_deep_verification_fingerprint=str(
                sample["modelDeepVerificationFingerprint"]
            ),
        ),
    )


def _arena_benchmark_binding(
    *,
    sample_id: str,
    blinded_candidate_id: str,
    source_sha256: str,
    identity_profile_id: str,
    identity_profile_fingerprint: str,
    content_intent_id: str,
    content_intent_fingerprint: str,
    benchmark_recipe_fingerprint: str,
    analyzer_registry_fingerprint: str,
    model_deep_verification_fingerprint: str,
) -> dict[str, Any]:
    core = {
        "schema": "reel_factory.arena_benchmark_execution.v1",
        "sampleId": sample_id,
        "blindedCandidateId": blinded_candidate_id,
        "sourceSha256": source_sha256,
        "identityProfileId": identity_profile_id,
        "identityProfileFingerprint": identity_profile_fingerprint,
        "contentIntentId": content_intent_id,
        "contentIntentFingerprint": content_intent_fingerprint,
        "benchmarkRecipeFingerprint": benchmark_recipe_fingerprint,
        "analyzerRegistryFingerprint": analyzer_registry_fingerprint,
        "modelDeepVerificationFingerprint": model_deep_verification_fingerprint,
        "providerCalls": 0,
        "productionWritesAllowed": False,
    }
    return {**core, "bindingFingerprint": fingerprint(core)}


def execute_arena_sample_generation(
    store: LocalModelArenaStore,
    *,
    plan_id: str,
    sample_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Run one exact planned sample through the normal local queue path."""

    plan = store.load_plan(plan_id)
    sample = _sample(plan, sample_id)
    request = _request_from_sample(sample)
    planned_job = plan_local_video_job(request)
    if (
        fingerprint(planned_job.as_dict()) != sample["queueJobFingerprint"]
        or planned_job.as_dict() != sample["queueJob"]
    ):
        raise LocalQueueError("arena_runtime_queue_job_drift")
    output = Path(str(sample["outputPath"])).resolve()
    if output.exists():
        raise LocalQueueError("arena_output_collision")
    if dry_run:
        return run_local_video(request, dry_run=True)
    return run_local_video(request, dry_run=False)


def _write_exact_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = _canonical(payload)
    if path.exists():
        if (
            not path.is_file()
            or path.is_symlink()
            or path.read_text(encoding="utf-8") != encoded
        ):
            raise LocalQueueError(f"arena_evidence_collision:{path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, encoded)


def _motion_qc_options(sample: Mapping[str, Any]) -> dict[str, bool]:
    task_kind = str(sample.get("taskKind") or "")
    expects_speech = task_kind == "audio_image_to_video"
    return {
        "expectsAudio": str(sample.get("audioMode") or "none") != "none"
        or expects_speech,
        "expectsSpeech": expects_speech,
    }


def _run_contentforge(
    command: str,
    request: Mapping[str, Any],
    *,
    evidence_root: Path,
    repository_root: Path,
    node_executable: str,
) -> dict[str, Any]:
    request_path = evidence_root / f"{command}.request.json"
    _write_exact_json(request_path, request)
    completed = subprocess.run(
        [
            node_executable,
            str(repository_root / "packages/contentforge/cli.mjs"),
            command,
            str(request_path),
        ],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
        timeout=1800,
    )
    if completed.returncode != 0:
        raise LocalQueueError(
            f"arena_contentforge_{command}_failed:"
            + (completed.stderr[-2000:] or completed.stdout[-2000:])
        )
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LocalQueueError(f"arena_contentforge_{command}_invalid_json") from exc
    if not isinstance(payload, dict):
        raise LocalQueueError(f"arena_contentforge_{command}_invalid_json")
    return payload


def finalize_arena_sample_evidence(
    store: LocalModelArenaStore,
    *,
    plan_id: str,
    sample_id: str,
    review_path: Path,
    queue: LocalGenerationQueue,
    benchmarks: LocalModelBenchmarkStore,
    human_reviews: HumanMediaReviewStore,
    repository_root: Path,
    identity_root: Path,
    produced_at: str,
    node_executable: str = "node",
) -> dict[str, Any]:
    """Produce exact media/QC evidence, then record one measured benchmark receipt."""

    plan = store.load_plan(plan_id)
    sample = _sample(plan, sample_id)
    review_packet = (
        store.load_review_packet(plan_id)
        if plan["purpose"] == "promotion_eligible"
        else None
    )
    output = Path(str(sample["outputPath"])).resolve()
    if not output.is_file() or output.is_symlink():
        raise LocalQueueError("arena_output_missing_or_unsafe")
    output_sha = sha256_file(output)
    queue_job_id = str(sample["queueJob"]["jobId"])
    state = queue.states().get(queue_job_id)
    if state is None or state.status != "succeeded":
        status = "missing" if state is None else state.status
        raise LocalQueueError(f"arena_queue_job_not_succeeded:{status}")
    if (
        fingerprint(state.job.as_dict()) != sample["queueJobFingerprint"]
        or state.last_event.get("payload", {}).get("outputSha256") != output_sha
    ):
        raise LocalQueueError("arena_queue_output_or_job_substituted")

    generated_at = str(state.last_event.get("occurredAt") or "")

    evidence_root = store.root / "arena_qc" / sample_id
    registry = dict(sample["analyzerRegistry"])
    if fingerprint(registry) != sample["analyzerRegistryFingerprint"]:
        raise LocalQueueError("arena_analyzer_registry_fingerprint_mismatch")
    analysis = _run_contentforge(
        "analyze-media",
        {
            "mediaPath": str(output),
            "mediaSha256": output_sha,
            "sourcePath": sample["sourcePath"],
            "sourceSha256": sample["sourceSha256"],
            "producedAt": produced_at,
            "overlaysExist": sample["overlaysExist"],
            "analyzerRegistry": registry,
        },
        evidence_root=evidence_root,
        repository_root=repository_root,
        node_executable=node_executable,
    )
    if (
        analysis.get("subject", {}).get("mediaSha256") != output_sha
        or analysis.get("analyzerRegistry", {}).get("registryFingerprint")
        != sample["analyzerRegistryFingerprint"]
    ):
        raise LocalQueueError("arena_trusted_analysis_linkage_mismatch")
    review = load_human_review(review_path)
    if review.operator_attestation is None:
        review = review.attest()
    if (
        review.arena_plan_id != plan_id
        or review.sample_id != sample_id
        or review.blinded_candidate_id != sample["blindedCandidateId"]
        or review.subject_sha256 != output_sha
        or review.source_sha256 != sample["sourceSha256"]
    ):
        raise LocalQueueError("arena_human_review_mismatch")
    _validate_human_review_binding(
        review,
        plan=plan,
        sample=sample,
        analysis=analysis,
        review_packet=review_packet,
        generated_at=generated_at,
    )
    analysis_path = evidence_root / "trusted-media-analysis.json"
    _write_exact_json(analysis_path, analysis)

    identity_result = verify_identity(
        output,
        creator=str(sample["creatorId"]),
        root=identity_root,
        identity_profile_id=str(sample["identityProfileId"]),
        identity_profile_fingerprint=str(sample["identityProfileFingerprint"]),
    )
    if identity_result.get("creatorIdentityProfile") != {
        "profileId": sample["identityProfileId"],
        "profileFingerprint": sample["identityProfileFingerprint"],
    }:
        raise LocalQueueError("arena_identity_profile_binding_mismatch")
    identity_receipt = identity_qc_receipt(identity_result)
    human_receipt = review.qc_receipt()
    motion_receipt = _run_contentforge(
        "motion-qc",
        {
            "mediaPath": str(output),
            "mediaSha256": output_sha,
            "analysis": analysis,
            "humanReview": review.as_dict(),
            "options": _motion_qc_options(sample),
        },
        evidence_root=evidence_root,
        repository_root=repository_root,
        node_executable=node_executable,
    )
    receipt_payloads = {
        str(item["policy"]["id"]): item
        for item in analysis.get("analyzerVerdicts", [])
        if isinstance(item, dict)
        and isinstance(item.get("policy"), dict)
        and item["policy"].get("id")
    }
    receipt_payloads[IDENTITY_ANALYZER[0]] = identity_receipt
    receipt_payloads[HUMAN_ANALYZER[0]] = human_receipt
    receipt_payloads["contentforge.motion_specific_qc"] = motion_receipt
    required_ids = {
        str(item["analyzerId"])
        for item in sample["benchmarkRecipe"]["requiredAnalyzers"]
    }
    if set(receipt_payloads).intersection(required_ids) != required_ids:
        raise LocalQueueError("arena_required_qc_receipt_missing")
    references = []
    for check_id in sorted(required_ids):
        receipt_path = evidence_root / f"{check_id}.json"
        _write_exact_json(receipt_path, receipt_payloads[check_id])
        references.append(
            benchmarks.ingest_qc_reference(
                check_id=check_id,
                receipt_path=receipt_path,
                expected_subject_sha256=output_sha,
            )
        )
    human_reviews.record(review, output_path=output)
    receipt = benchmarks.record_completed_job(
        queue,
        job_id=queue_job_id,
        qc_references=tuple(references),
        benchmark_recipe=dict(sample["benchmarkRecipe"]),
        analyzer_registry=registry,
    )
    store.record_terminal(
        plan_id=plan_id,
        sample_id=sample_id,
        status="succeeded",
        reason=(
            "generation_and_qc_completed"
            if receipt.all_qc_passed
            else "generation_completed_qc_blocked"
        ),
        output_sha256=output_sha,
        benchmark_id=receipt.benchmark_id,
        human_review_id=review.review_id,
        queue=queue,
        benchmarks=benchmarks,
        human_reviews=human_reviews,
    )
    return {
        "schema": "reel_factory.local_model_arena_finalize.v1",
        "planId": plan_id,
        "sampleId": sample_id,
        "outputSha256": output_sha,
        "benchmarkReceipt": receipt.as_dict(),
        "allQcPassed": receipt.all_qc_passed,
        "analysisPath": str(analysis_path),
        "humanReviewId": review.review_id,
        "providerCalls": 0,
        "productionWrites": 0,
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("arena_json_object_required")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(
            os.environ.get(
                "CREATOR_OS_LOCAL_MODEL_BENCHMARK_ROOT",
                Path.home() / ".creator-os/state/reel_factory/local_benchmarks",
            )
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    plan_command = sub.add_parser("plan")
    plan_command.add_argument("--request", type=Path, required=True)
    plan_command.add_argument("--contentforge-registry", type=Path, required=True)
    plan_command.add_argument("--repository-root", type=Path, required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--plan-id", required=True)
    generate.add_argument("--sample-id", required=True)
    generate.add_argument("--mode", choices=["local_wan"], required=True)
    execution = generate.add_mutually_exclusive_group(required=True)
    execution.add_argument("--dry-run", action="store_true")
    execution.add_argument("--apply", action="store_true")
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--plan-id", required=True)
    finalize.add_argument("--sample-id", required=True)
    finalize.add_argument("--review", type=Path, required=True)
    finalize.add_argument("--repository-root", type=Path, required=True)
    finalize.add_argument("--identity-root", type=Path, required=True)
    finalize.add_argument("--produced-at", required=True)
    finalize.add_argument("--node", default="node")
    packet_command = sub.add_parser("review-packet")
    packet_command.add_argument("--plan-id", required=True)
    packet_command.add_argument("--created-at", required=True)
    unblind_command = sub.add_parser("unblind")
    unblind_command.add_argument("--plan-id", required=True)
    unblind_command.add_argument("--created-at", required=True)
    summary = sub.add_parser("summary")
    summary.add_argument("--plan-id", required=True)
    args = parser.parse_args(argv)
    store = LocalModelArenaStore(args.root)
    try:
        if args.command == "plan":
            request = _read_json(args.request)
            registry = arena_analyzer_registry(
                _read_json(args.contentforge_registry),
                produced_at=str(request["producedAt"]),
                repository_root=args.repository_root.expanduser().resolve(),
            )
            plan = build_arena_plan(
                sample_specs=[
                    ArenaSampleSpec.from_dict(item) for item in request["samples"]
                ],
                purpose=str(request["purpose"]),
                produced_at=str(request["producedAt"]),
                output_root=Path(str(request["outputRoot"])),
                execution_policy=dict(request["executionPolicy"]),
                analyzer_registry=registry,
            )
            result: Any = {
                "plan": plan,
                "path": str(store.persist_plan(plan)),
            }
        elif args.command == "generate":
            result = execute_arena_sample_generation(
                store,
                plan_id=args.plan_id,
                sample_id=args.sample_id,
                dry_run=args.dry_run,
            )
        elif args.command == "finalize":
            benchmark_store = default_local_model_benchmark_store(args.root)
            result = finalize_arena_sample_evidence(
                store,
                plan_id=args.plan_id,
                sample_id=args.sample_id,
                review_path=args.review,
                queue=default_local_generation_queue(),
                benchmarks=benchmark_store,
                human_reviews=HumanMediaReviewStore(args.root),
                repository_root=args.repository_root.expanduser().resolve(),
                identity_root=args.identity_root.expanduser().resolve(),
                produced_at=args.produced_at,
                node_executable=args.node,
            )
        elif args.command == "review-packet":
            packet = build_arena_review_packet(
                arena_plan=store.load_plan(args.plan_id),
                queue=default_local_generation_queue(),
                created_at=args.created_at,
            )
            result = {
                "reviewPacket": packet,
                "path": str(store.persist_review_packet(packet)),
            }
        elif args.command == "unblind":
            human_reviews = HumanMediaReviewStore(args.root)
            receipt = build_arena_unblinding_receipt(
                arena_plan=store.load_plan(args.plan_id),
                review_packet=store.load_review_packet(args.plan_id),
                human_reviews=human_reviews,
                created_at=args.created_at,
            )
            result = {
                "unblindingReceipt": receipt,
                "path": str(
                    store.persist_unblinding_receipt(
                        receipt, human_reviews=human_reviews
                    )
                ),
            }
        else:
            result = store.summarize(
                args.plan_id,
                queue=default_local_generation_queue(),
                benchmarks=default_local_model_benchmark_store(args.root),
                human_reviews=HumanMediaReviewStore(args.root),
            )
    except (
        KeyError,
        LocalQueueError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
