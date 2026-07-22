"""Reproducible local-model Arena built on the existing queue and benchmark store.

The Arena is a plan, an append-only outcome journal, and deterministic summary
logic.  It is deliberately not another scheduler: inference still runs through
``LocalGenerationQueue`` and measurements still live in
``LocalModelBenchmarkStore``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from .fileops import atomic_write_text, file_lock
from .human_media_review import HumanMediaReviewStore
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
CREATORS: Final = frozenset({"stacey", "larissa", "lola"})
PURPOSES: Final = frozenset({"exploratory", "promotion_eligible"})
TERMINAL_STATUSES: Final = frozenset(
    {
        "succeeded",
        "failed",
        "interrupted",
        "resource_blocked",
        "unsupported",
        "missing",
    }
)
IDENTITY_ANALYZER: Final = ("reel_factory.identity_preservation", "2.0.0")
HUMAN_ANALYZER: Final = (
    "reel_factory.structured_human_media_review",
    "1.0.0",
)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"arena_{field}_missing")
    return normalized


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
        ("contentforge.motion_specific_qc", "1.0.0"),
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
        sources = {sha256_file(row.source_path) for row in rows}
        if len(sources) < 2:
            raise LocalQueueError(
                "arena_promotion_requires_two_sources:" + ":".join(key)
            )
        for source_sha in sources:
            seeds = {
                row.seed for row in rows if sha256_file(row.source_path) == source_sha
            }
            if len(seeds) < 2:
                raise LocalQueueError(
                    "arena_promotion_requires_two_seeds_per_source:" + ":".join(key)
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
        )
        status = model_status(spec.model_id, deep=False)
        if not status.get("ready"):
            raise LocalQueueError(
                f"arena_model_not_ready:{spec.model_id}:"
                + ",".join(str(issue) for issue in status.get("issues", []))
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
    identities: set[str] = set()
    blinded: set[str] = set()
    outputs: set[str] = set()
    jobs: set[str] = set()
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
        source = Path(str(raw["sourcePath"])).resolve()
        if not source.is_file() or sha256_file(source) != raw.get("sourceSha256"):
            raise LocalQueueError("arena_source_missing_or_substituted")
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


class LocalModelArenaStore:
    """Persist immutable Arena plans and outcomes beside benchmark evidence."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.plans = self.root / "arena_plans"
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
    ) -> dict[str, Any]:
        if status not in TERMINAL_STATUSES:
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
        elif any(
            value is not None
            for value in (output_sha256, benchmark_id, human_review_id)
        ):
            raise LocalQueueError("arena_non_success_must_not_claim_success_evidence")
        with file_lock(self._mutation):
            prior = [
                event
                for event in self.events.read().events
                if event.get("eventType") == "arena_sample_terminal"
                and event.get("payload", {}).get("planId") == plan_id
                and event.get("payload", {}).get("sampleId") == sample_id
            ]
            if prior:
                raise LocalQueueError("arena_duplicate_terminal_sample")
            return self.events.append(
                "arena_sample_terminal",
                {
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
                },
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
            terminal = by_sample.get(sample_id)
            if terminal is None:
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
            queue_job_id = str(sample["queueJob"]["jobId"])
            queue_state = queue_states.get(queue_job_id)
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
                review = reviews.get(str(review_id))
                if human_reviews is not None:
                    if review is None:
                        blockers.append("human_review_missing")
                    elif (
                        review.sample_id != sample_id
                        or review.subject_sha256 != output_sha
                        or review.source_sha256 != sample["sourceSha256"]
                        or review.blinded_candidate_id != sample["blindedCandidateId"]
                    ):
                        blockers.append("human_review_mismatch")
                    else:
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
        if sum(counts.values()) != int(plan["expectedSampleCount"]):
            raise LocalQueueError("arena_summary_denominator_mismatch")
        aggregates: list[dict[str, Any]] = []
        aggregate_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(
            list
        )
        for result in sample_results:
            aggregate_groups[
                (str(result["modelId"]), str(result["capabilityCohort"]))
            ].append(result)
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
            "providerCalls": 0,
            "productionWrites": 0,
        }
        return {**core, "summaryFingerprint": fingerprint(core)}


def validate_arena_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
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
    )


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
    return run_local_video(request, dry_run=dry_run)


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

    review = load_human_review(review_path)
    if (
        review.arena_plan_id != plan_id
        or review.sample_id != sample_id
        or review.blinded_candidate_id != sample["blindedCandidateId"]
        or review.subject_sha256 != output_sha
        or review.source_sha256 != sample["sourceSha256"]
    ):
        raise LocalQueueError("arena_human_review_mismatch")
    human_reviews.record(review, output_path=output)

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
    analysis_path = evidence_root / "trusted-media-analysis.json"
    _write_exact_json(analysis_path, analysis)

    identity_result = verify_identity(
        output,
        creator=str(sample["creatorId"]),
        root=identity_root,
    )
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
