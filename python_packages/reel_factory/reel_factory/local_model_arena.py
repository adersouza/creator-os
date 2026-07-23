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
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    load_evidence_secret,
    sign_evidence_attestation,
    verify_evidence_attestation,
)
from creator_os_core.task_inputs import canonical_task_input_bindings
from creator_os_core.task_parameters import (
    benchmark_task_parameter_fingerprint,
    task_parameter_fingerprint,
)

from pipeline_contracts import (
    ContentIntentV1,
    CreatorIdentityProfileV1,
    IdentityReferenceV1,
    ProvenanceV1,
    SourceReferenceV1,
    validate_local_model_arena_plan,
    validate_local_model_arena_review_packet,
    validate_local_model_arena_summary,
    validate_local_model_arena_unblinding_receipt,
    validate_local_model_rollout_gate_receipt,
)

from .fileops import atomic_write_text, file_lock
from .human_media_review import HumanMediaReviewStore, HumanReviewSamplingEvidence
from .human_media_review import load_review as load_human_review
from .identity_verification import (
    _load_reference_embeddings,
    get_identity_provider,
    identity_health,
    identity_qc_receipt,
    verify_identity,
)
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
    DEFAULT_NEGATIVE_PROMPT,
    LocalVideoRequest,
    local_video_task_parameter_material,
    plan_local_video_job,
    run_local_video,
)
from .local_video_models import local_video_model_spec
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
ROLLOUT_GATE_SCHEMA: Final = "reel_factory.local_model_rollout_gate_receipt.v1"
ROLLOUT_GATE_ISSUER: Final = "reel_factory.local_model_arena.rollout_gate"
ROLLOUT_GATE_SIZES: Final = (10, 25, 50, 100)
ROLLOUT_MODE_CONFIRMATION: Final = "Mode 3 — Local Wan / LTX motion — free."
CREATORS: Final = frozenset({"stacey", "larissa", "lola"})
PURPOSES: Final = frozenset({"exploratory", "promotion_eligible", "supervised_rollout"})
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
RECORDED_TERMINAL_STATUSES: Final = TERMINAL_STATUSES
NON_ROLLOUT_RECORDED_TERMINAL_STATUSES: Final = frozenset(
    {"succeeded", "failed", "unsupported", "cancelled"}
)
IDENTITY_ANALYZER: Final = ("reel_factory.identity_preservation", "2.0.0")
HUMAN_ANALYZER: Final = (
    "reel_factory.structured_human_media_review",
    "1.0.0",
)


def _require_promotion_identity_ready(
    *,
    purpose: str,
    bindings: Sequence[tuple[str, str, str, Mapping[str, Any]]],
    identity_root: Path | None,
) -> None:
    """Fail before Arena work when exact promotion identity evidence is unusable.

    The identity analyzer remains optional for general Reel Factory rendering,
    but it is mandatory for a promotion-eligible Arena.  The operator launcher
    selects the locked ``reel-factory[identity]`` extra; this boundary also
    verifies the current provider, ArcFace weights, v4 reference set, analyzer
    implementation, and exact CreatorIdentityProfile binding before a plan,
    generation, or finalization can proceed.
    """

    if purpose != "promotion_eligible":
        return
    if identity_root is None:
        raise LocalQueueError("arena_promotion_identity_root_required")
    root = identity_root.expanduser().resolve()
    provider = get_identity_provider()
    seen: set[tuple[str, str, str]] = set()
    for creator, profile_id, profile_fingerprint, raw_profile in sorted(
        bindings, key=lambda item: (item[0], item[1], item[2])
    ):
        identity = (creator, profile_id, profile_fingerprint)
        if identity in seen:
            continue
        seen.add(identity)
        health = identity_health(creator=creator, root=root, provider=provider)
        blocking = [
            str(reason)
            for reason in health.get("blockingReasons", [])
            if str(reason).strip()
        ]
        if (
            health.get("status") != "ready"
            or health.get("promotionEligible") is not True
        ):
            reasons = ",".join(sorted(set(blocking))) or "identity_unavailable"
            raise LocalQueueError(
                f"arena_promotion_identity_preflight_failed:{creator}:{reasons}"
            )
        reference_path = Path(str(health["referenceSetPath"])).expanduser().resolve()
        loaded = _load_reference_embeddings(reference_path, creator=creator)
        expected_profile = dict(raw_profile)
        if (
            loaded.error is not None
            or loaded.promotion_eligible is not True
            or loaded.creator_identity_profile != expected_profile
            or expected_profile.get("profileId") != profile_id
            or fingerprint(expected_profile) != profile_fingerprint
        ):
            reason = loaded.error or "identity_profile_binding_mismatch"
            raise LocalQueueError(
                f"arena_promotion_identity_preflight_failed:{creator}:{reason}"
            )


def _spec_identity_bindings(
    sample_specs: Sequence[ArenaSampleSpec],
) -> tuple[tuple[str, str, str, Mapping[str, Any]], ...]:
    return tuple(
        (
            spec.creator_id,
            spec.identity_profile_id,
            spec.identity_profile_fingerprint,
            spec.creator_identity_profile,
        )
        for spec in sample_specs
    )


def _plan_identity_bindings(
    plan: Mapping[str, Any],
) -> tuple[tuple[str, str, str, Mapping[str, Any]], ...]:
    return tuple(
        (
            str(sample["creatorId"]),
            str(sample["identityProfileId"]),
            str(sample["identityProfileFingerprint"]),
            dict(sample["creatorIdentityProfile"]),
        )
        for sample in plan["samples"]
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
    _required_text(contentforge_registry.get("registryId"), "contentforge_registry_id")
    raw_registrations = contentforge_registry.get("analyzers")
    if not isinstance(raw_registrations, list) or not raw_registrations:
        raise ValueError("arena_contentforge_registry_empty")
    registrations = [dict(registration) for registration in raw_registrations]
    fixed_registrations = (
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
            evidence_kinds=("human_media_review",),
            implementation_ref=(
                "python_packages/reel_factory/reel_factory/human_media_review.py"
            ),
            repository_root=repository_root,
        ),
    )
    by_identity = {
        (str(item.get("analyzerId")), str(item.get("analyzerVersion"))): item
        for item in registrations
    }
    if len(by_identity) != len(registrations):
        raise LocalQueueError("arena_analyzer_registry_duplicate_identity")
    for fixed in fixed_registrations:
        identity = (
            str(fixed["analyzerId"]),
            str(fixed["analyzerVersion"]),
        )
        existing = by_identity.get(identity)
        if existing is not None:
            if existing != fixed:
                raise LocalQueueError(
                    "arena_analyzer_registration_drift:"
                    + f"{identity[0]}@{identity[1]}"
                )
            continue
        registrations.append(fixed)
        by_identity[identity] = fixed
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
                    "recordId": f"{item['analyzerId']}@{item['analyzerVersion']}",
                    "fingerprint": item["implementationFingerprint"],
                }
                for item in registrations
            ],
        },
    }
    return payload


@dataclass(frozen=True, slots=True)
class ArenaSampleSpec:
    creator_id: str
    identity_profile_id: str
    identity_profile_fingerprint: str
    creator_identity_profile: dict[str, Any]
    content_intent_id: str
    content_intent_fingerprint: str
    content_intent: dict[str, Any]
    source_path: Path | None
    model_id: str
    capability_cohort: str
    task_kind: str
    prompt: str
    seed: int
    duration_seconds: int
    resolution: str
    steps: int | None = None
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    audio_mode: Literal["none", "source", "generated", "preserved"] = "none"
    audio_path: Path | None = None
    last_image_path: Path | None = None
    source_video_path: Path | None = None
    retake_start_frame: int | None = None
    retake_end_frame: int | None = None
    extend_frames: int | None = None
    extend_direction: Literal["before", "after"] = "after"
    preserve_audio: bool = False
    lora_path: Path | None = None
    lora_strength: float = 1.0
    low_ram: bool = True
    tile_frames: int = 1
    tile_spatial: int = 2
    commercial_use: bool = True
    commercial_annual_revenue_usd: int | None = None
    overlays_exist: bool = False
    prompt_source_path: Path | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArenaSampleSpec:
        audio_path = value.get("audioPath")
        last_image_path = value.get("lastImagePath")
        source_video_path = value.get("sourceVideoPath")
        prompt_source = value.get("promptSource")
        if prompt_source is not None and not isinstance(prompt_source, dict):
            raise ValueError("arena_prompt_source_invalid")
        raw_profile = value.get("creatorIdentityProfile")
        raw_intent = value.get("contentIntent")
        if not isinstance(raw_profile, dict):
            raise ValueError("arena_creator_identity_profile_missing")
        if not isinstance(raw_intent, dict):
            raise ValueError("arena_content_intent_record_missing")
        profile = CreatorIdentityProfileV1.from_dict(dict(raw_profile)).to_dict()
        intent = ContentIntentV1.from_dict(dict(raw_intent)).to_dict()
        return cls(
            creator_id=_required_text(value.get("creatorId"), "creator_id").lower(),
            identity_profile_id=_required_text(
                value.get("identityProfileId"), "identity_profile_id"
            ),
            identity_profile_fingerprint=_valid_sha256(
                value.get("identityProfileFingerprint"),
                "identity_profile_fingerprint",
            ),
            creator_identity_profile=profile,
            content_intent_id=_required_text(
                value.get("contentIntentId"), "content_intent_id"
            ),
            content_intent_fingerprint=_valid_sha256(
                value.get("contentIntentFingerprint"),
                "content_intent_fingerprint",
            ),
            content_intent=intent,
            source_path=(
                Path(str(value["sourcePath"])).expanduser().resolve()
                if value.get("sourcePath") is not None
                else None
            ),
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
            steps=(
                _required_int(value.get("steps"), "steps")
                if value.get("steps") is not None
                else None
            ),
            negative_prompt=str(value.get("negativePrompt") or DEFAULT_NEGATIVE_PROMPT),
            audio_mode=str(value.get("audioMode") or "none"),  # type: ignore[arg-type]
            audio_path=(
                Path(str(audio_path)).expanduser().resolve()
                if audio_path is not None
                else None
            ),
            last_image_path=(
                Path(str(last_image_path)).expanduser().resolve()
                if last_image_path is not None
                else None
            ),
            source_video_path=(
                Path(str(source_video_path)).expanduser().resolve()
                if source_video_path is not None
                else None
            ),
            retake_start_frame=(
                _required_int(value.get("retakeStartFrame"), "retake_start_frame")
                if value.get("retakeStartFrame") is not None
                else None
            ),
            retake_end_frame=(
                _required_int(value.get("retakeEndFrame"), "retake_end_frame")
                if value.get("retakeEndFrame") is not None
                else None
            ),
            extend_frames=(
                _required_int(value.get("extendFrames"), "extend_frames")
                if value.get("extendFrames") is not None
                else None
            ),
            extend_direction=str(value.get("extendDirection") or "after"),  # type: ignore[arg-type]
            preserve_audio=value.get("preserveAudio") is True,
            lora_path=(
                Path(str(value["loraPath"])).expanduser().resolve()
                if value.get("loraPath") is not None
                else None
            ),
            lora_strength=float(value.get("loraStrength", 1.0)),
            low_ram=value.get("lowRam") is not False,
            tile_frames=int(value.get("tileFrames", 1)),
            tile_spatial=int(value.get("tileSpatial", 2)),
            commercial_use=value.get("commercialUse") is not False,
            commercial_annual_revenue_usd=(
                _required_int(
                    value.get("commercialAnnualRevenueUsd"),
                    "commercial_annual_revenue_usd",
                )
                if value.get("commercialAnnualRevenueUsd") is not None
                else None
            ),
            overlays_exist=value.get("overlaysExist") is True,
            prompt_source_path=(
                Path(str(prompt_source["path"])).expanduser().resolve()
                if isinstance(prompt_source, dict) and prompt_source.get("path")
                else None
            ),
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
    # Pixel-integrity/overlay analysis is mandatory even when the operator
    # declares no semantic overlay. That is how undeclared UI, watermarks, and
    # accidental burned text are detected rather than trusted as absent.
    required.append(("contentforge.overlay_delivery", "1.0.0"))
    return tuple(required)


def _spec_input_bindings(spec: ArenaSampleSpec) -> tuple[dict[str, str], ...]:
    return canonical_task_input_bindings(
        spec.task_kind,
        image_sha256=(
            sha256_file(spec.source_path) if spec.source_path is not None else None
        ),
        audio_sha256=(
            sha256_file(spec.audio_path) if spec.audio_path is not None else None
        ),
        last_image_sha256=(
            sha256_file(spec.last_image_path)
            if spec.last_image_path is not None
            else None
        ),
        source_video_sha256=(
            sha256_file(spec.source_video_path)
            if spec.source_video_path is not None
            else None
        ),
    )


def _spec_input_binding_fingerprint(spec: ArenaSampleSpec) -> str:
    return fingerprint({"inputBindings": list(_spec_input_bindings(spec))})


def _spec_local_video_request(
    spec: ArenaSampleSpec, *, output_path: Path
) -> LocalVideoRequest:
    return LocalVideoRequest(
        model_id=spec.model_id,
        image_path=spec.source_path,
        prompt=spec.prompt,
        output_path=output_path,
        duration_seconds=spec.duration_seconds,
        resolution=spec.resolution,
        seed=spec.seed,
        steps=spec.steps,
        negative_prompt=spec.negative_prompt,
        audio_mode=spec.audio_mode,
        audio_path=spec.audio_path,
        last_image_path=spec.last_image_path,
        task=spec.task_kind,  # type: ignore[arg-type]
        lora_path=spec.lora_path,
        lora_strength=spec.lora_strength,
        source_video_path=spec.source_video_path,
        retake_start_frame=spec.retake_start_frame,
        retake_end_frame=spec.retake_end_frame,
        extend_frames=spec.extend_frames,
        extend_direction=spec.extend_direction,
        low_ram=spec.low_ram,
        tile_frames=spec.tile_frames,
        tile_spatial=spec.tile_spatial,
        commercial_use=spec.commercial_use,
        commercial_annual_revenue_usd=spec.commercial_annual_revenue_usd,
        overlays_exist=spec.overlays_exist,
    )


def _spec_parameter_material(
    spec: ArenaSampleSpec,
    *,
    runtime_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected_runtime = runtime_binding
    if selected_runtime is None and spec.task_kind in {"video_retake", "video_extend"}:
        status = model_status(spec.model_id, deep=True)
        receipt = status.get("deepVerificationReceipt")
        selected_runtime = (
            receipt.get("runtimeBinding") if isinstance(receipt, Mapping) else None
        )
        if not isinstance(selected_runtime, Mapping):
            raise LocalQueueError("arena_runtime_binding_missing_for_edit_geometry")
    return local_video_task_parameter_material(
        _spec_local_video_request(
            spec, output_path=Path("/creator-os/arena/parameter-material-only.mp4")
        ),
        spec=local_video_model_spec(spec.model_id),
        runtime_binding=selected_runtime,
    )


def _primary_source_path(spec: ArenaSampleSpec) -> Path:
    if spec.task_kind in {"video_retake", "video_extend"}:
        if spec.source_video_path is None:
            raise ValueError("arena_video_task_source_video_missing")
        return spec.source_video_path
    if spec.task_kind == "text_to_video":
        raise ValueError("arena_text_task_has_no_media_source")
    if spec.source_path is None:
        raise ValueError("arena_image_task_source_missing")
    return spec.source_path


def _primary_source_sha(spec: ArenaSampleSpec) -> str:
    if spec.task_kind == "text_to_video":
        return fingerprint(
            {
                "taskKind": spec.task_kind,
                "prompt": " ".join(spec.prompt.split()),
            }
        )
    return sha256_file(_primary_source_path(spec))


def _prompt_source_binding(spec: ArenaSampleSpec) -> dict[str, str] | None:
    if spec.task_kind != "text_to_video":
        if spec.prompt_source_path is not None:
            raise LocalQueueError("arena_prompt_source_forbidden_for_media_task")
        return None
    if spec.prompt_source_path is None:
        raise LocalQueueError("arena_text_task_prompt_source_missing")
    prompt_path = spec.prompt_source_path.expanduser().resolve()
    expected_material = {
        "prompt": " ".join(spec.prompt.split()),
        "taskKind": "text_to_video",
    }
    expected_sha = fingerprint(expected_material)
    if (
        not prompt_path.is_file()
        or prompt_path.is_symlink()
        or sha256_file(prompt_path) != expected_sha
    ):
        raise LocalQueueError("arena_text_task_prompt_source_missing_or_substituted")
    try:
        decoded = json.loads(prompt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalQueueError("arena_text_task_prompt_source_invalid") from exc
    if decoded != expected_material or prompt_path.read_text(encoding="utf-8") != (
        _canonical(expected_material)
    ):
        raise LocalQueueError("arena_text_task_prompt_source_invalid")
    return {"path": str(prompt_path), "sha256": expected_sha}


def _validate_spec(spec: ArenaSampleSpec) -> None:
    if spec.creator_id not in CREATORS:
        raise ValueError(f"arena_creator_unsupported:{spec.creator_id}")
    model = video_model(spec.model_id)
    if model.backend != "local_mlx" or model.paid:
        raise LocalQueueError(f"arena_model_not_local_free:{spec.model_id}")
    if spec.task_kind not in (model.supported_tasks or (model.task,)):
        raise LocalQueueError(f"arena_model_capability_mismatch:{spec.model_id}")
    _spec_input_bindings(spec)
    prompt_source = _prompt_source_binding(spec)
    if spec.task_kind != "text_to_video":
        primary_source = _primary_source_path(spec)
        if not primary_source.is_file() or primary_source.is_symlink():
            raise LocalQueueError(f"arena_source_missing_or_unsafe:{primary_source}")
    if spec.audio_mode == "none" and spec.audio_path is not None:
        raise ValueError("arena_audio_path_without_audio_mode")
    if spec.audio_mode == "source" and spec.audio_path is None:
        raise ValueError("arena_source_audio_missing")
    if spec.preserve_audio is not (spec.audio_mode == "preserved"):
        raise ValueError("arena_preserve_audio_mode_mismatch")
    if spec.audio_mode == "preserved" and spec.source_video_path is None:
        raise ValueError("arena_preserve_audio_source_video_missing")
    if spec.audio_path is not None and (
        not spec.audio_path.is_file() or spec.audio_path.is_symlink()
    ):
        raise LocalQueueError("arena_source_audio_missing_or_unsafe")
    for label, path in (
        ("last_image", spec.last_image_path),
        ("source_video", spec.source_video_path),
    ):
        if path is not None and (not path.is_file() or path.is_symlink()):
            raise LocalQueueError(f"arena_{label}_missing_or_unsafe")
    retake = (spec.retake_start_frame, spec.retake_end_frame)
    if any(value is not None for value in retake) and not all(
        value is not None for value in retake
    ):
        raise ValueError("arena_retake_range_must_be_complete")
    if (
        spec.retake_start_frame is not None
        and spec.retake_end_frame is not None
        and (
            spec.retake_start_frame < 0
            or spec.retake_end_frame <= spec.retake_start_frame
            or spec.source_video_path is None
        )
    ):
        raise ValueError("arena_retake_range_invalid")
    if spec.extend_frames is not None and (
        spec.extend_frames <= 0 or spec.source_video_path is None
    ):
        raise ValueError("arena_extend_request_invalid")
    if spec.extend_direction not in {"before", "after"}:
        raise ValueError("arena_extend_direction_invalid")
    if spec.commercial_annual_revenue_usd is not None and (
        spec.commercial_annual_revenue_usd < 0
    ):
        raise ValueError("arena_commercial_revenue_invalid")
    revenue_limit = local_video_model_spec(spec.model_id).commercial_revenue_limit_usd
    if spec.commercial_use and revenue_limit is not None:
        if spec.commercial_annual_revenue_usd is None:
            raise LocalQueueError("arena_commercial_revenue_attestation_required")
        if spec.commercial_annual_revenue_usd >= revenue_limit:
            raise LocalQueueError("arena_model_license_commercial_use_forbidden")
    if spec.duration_seconds <= 0:
        raise ValueError("arena_duration_must_be_positive")
    profile = CreatorIdentityProfileV1.from_dict(
        dict(spec.creator_identity_profile)
    ).to_dict()
    intent = ContentIntentV1.from_dict(dict(spec.content_intent)).to_dict()
    if (
        profile["profileId"] != spec.identity_profile_id
        or fingerprint(profile) != spec.identity_profile_fingerprint
    ):
        raise LocalQueueError("arena_creator_identity_profile_binding_mismatch")
    if str(profile["creatorKey"]).lower() != spec.creator_id:
        raise LocalQueueError("arena_creator_identity_profile_creator_mismatch")
    if (
        intent["intentId"] != spec.content_intent_id
        or fingerprint(intent) != spec.content_intent_fingerprint
    ):
        raise LocalQueueError("arena_content_intent_binding_mismatch")
    if intent["creatorIdentityProfileId"] != spec.identity_profile_id:
        raise LocalQueueError("arena_content_intent_profile_mismatch")
    exact_input_fingerprints = [
        binding["sha256"] for binding in _spec_input_bindings(spec)
    ]
    if prompt_source is not None:
        exact_input_fingerprints.append(prompt_source["sha256"])
    authorized_input_fingerprints = set(intent["sourceAssetFingerprints"])
    if not set(exact_input_fingerprints).issubset(authorized_input_fingerprints):
        raise LocalQueueError("arena_content_intent_source_mismatch")


def _promotion_design_check(specs: Sequence[ArenaSampleSpec]) -> None:
    if {spec.creator_id for spec in specs} != CREATORS:
        raise LocalQueueError("arena_promotion_requires_all_creators")
    source_sha_by_spec = {
        id(spec): _spec_input_binding_fingerprint(spec) for spec in specs
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
        sources = {source_sha_by_spec[id(row)] for row in rows}
        if len(sources) < 2:
            raise LocalQueueError(
                "arena_promotion_requires_two_sources:" + ":".join(key)
            )
        for source_sha in sources:
            seeds = {
                row.seed for row in rows if source_sha_by_spec[id(row)] == source_sha
            }
            if len(seeds) < 4:
                raise LocalQueueError(
                    "arena_promotion_requires_four_seeds_per_source:" + ":".join(key)
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
                source_sha_by_spec[id(spec)],
                benchmark_task_parameter_fingerprint(_spec_parameter_material(spec)),
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
    identity_root: Path | None = None,
) -> dict[str, Any]:
    if purpose not in PURPOSES:
        raise ValueError("arena_purpose_invalid")
    if not sample_specs:
        raise ValueError("arena_samples_missing")
    if purpose == "supervised_rollout" and len(sample_specs) not in ROLLOUT_GATE_SIZES:
        raise LocalQueueError("arena_rollout_gate_size_invalid")
    if execution_policy.get("schema") != "creator_os.execution_policy.v1":
        raise ValueError("arena_execution_policy_schema_mismatch")
    if execution_policy.get("paidProvidersAllowed") is not False:
        raise LocalQueueError("arena_execution_policy_paid_provider_forbidden")
    if execution_policy.get("productionWritesAllowed") is not False:
        raise LocalQueueError("arena_execution_policy_production_write_forbidden")
    intent_identities: dict[tuple[str, str], str] = {}
    for spec in sample_specs:
        _validate_spec(spec)
        existing_intent_fingerprint = intent_identities.setdefault(
            (spec.creator_id, spec.content_intent_id),
            spec.content_intent_fingerprint,
        )
        if existing_intent_fingerprint != spec.content_intent_fingerprint:
            raise LocalQueueError("arena_content_intent_identity_collision")
    source_pairs = [
        (spec.creator_id, _spec_input_binding_fingerprint(spec))
        for spec in sample_specs
    ]
    if len(source_pairs) != len(set(source_pairs)) and len(
        {
            (
                spec.creator_id,
                spec.model_id,
                spec.seed,
                _spec_input_binding_fingerprint(spec),
            )
            for spec in sample_specs
        }
    ) != len(sample_specs):
        raise LocalQueueError("arena_duplicate_sample_identity")
    if purpose == "promotion_eligible":
        _promotion_design_check(sample_specs)
        _require_promotion_identity_ready(
            purpose=purpose,
            bindings=_spec_identity_bindings(sample_specs),
            identity_root=identity_root,
        )

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
        source_sha = _primary_source_sha(spec)
        prompt_source = _prompt_source_binding(spec)
        audio_sha = (
            sha256_file(spec.audio_path) if spec.audio_path is not None else None
        )
        last_image_sha = (
            sha256_file(spec.last_image_path)
            if spec.last_image_path is not None
            else None
        )
        source_video_sha = (
            sha256_file(spec.source_video_path)
            if spec.source_video_path is not None
            else None
        )
        required = _required_analyzers(spec)
        if not set(required).issubset(registered):
            missing = sorted(set(required).difference(registered))
            raise LocalQueueError(f"arena_required_analyzer_unregistered:{missing}")
        model_spec = local_video_model_spec(spec.model_id)
        parameter_request = _spec_local_video_request(
            spec, output_path=output_directory / "parameters" / "not-executed.mp4"
        )
        parameter_material = _spec_parameter_material(spec)
        parameter_fp = task_parameter_fingerprint(parameter_material)
        benchmark_parameter_fp = benchmark_task_parameter_fingerprint(
            parameter_material
        )
        exact_input_bindings = list(_spec_input_bindings(spec))
        recipe_identity = {
            "creatorId": spec.creator_id,
            "identityProfileFingerprint": spec.identity_profile_fingerprint,
            "contentIntentFingerprint": spec.content_intent_fingerprint,
            "inputBindings": exact_input_bindings,
            "inputBindingsFingerprint": fingerprint(
                {"inputBindings": exact_input_bindings}
            ),
            "capabilityCohort": spec.capability_cohort,
            "taskParameterFingerprint": benchmark_parameter_fp,
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
                binding["sha256"] for binding in exact_input_bindings
            ],
            "parameterFingerprint": benchmark_parameter_fp,
            "promotionEvidenceAllowed": purpose == "promotion_eligible",
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
        runtime_binding = deep_verification.get("runtimeBinding")
        runtime_binding_fingerprint = _valid_sha256(
            deep_verification.get("runtimeBindingFingerprint"),
            "runtime_binding_fingerprint",
        )
        if (
            not isinstance(runtime_binding, dict)
            or fingerprint(runtime_binding) != runtime_binding_fingerprint
        ):
            raise LocalQueueError("arena_runtime_binding_invalid")
        manifest = status.get("manifest")
        if (
            not isinstance(manifest, dict)
            or manifest.get("licenseId") != model_spec.license_id
            or manifest.get("commercialRevenueLimitUsd")
            != model_spec.commercial_revenue_limit_usd
        ):
            raise LocalQueueError("arena_model_license_manifest_drift")
        license_policy = {
            "licenseId": model_spec.license_id,
            "commercialUse": spec.commercial_use,
            "declaredAnnualRevenueUsd": spec.commercial_annual_revenue_usd,
            "commercialRevenueLimitUsd": model_spec.commercial_revenue_limit_usd,
            "commercialUseAllowed": True,
            "aiDisclosureRequired": model_spec.ai_disclosure_required,
        }
        license_policy_fingerprint = fingerprint(license_policy)
        request = replace(
            parameter_request,
            output_path=output_path,
            benchmark_recipe=recipe,
            analyzer_registry=registry_payload,
            creator_identity_profile=spec.creator_identity_profile,
            content_intent=spec.content_intent,
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
                runtime_binding=runtime_binding,
                runtime_binding_fingerprint=runtime_binding_fingerprint,
                license_policy=license_policy,
                license_policy_fingerprint=license_policy_fingerprint,
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
                "creatorIdentityProfile": spec.creator_identity_profile,
                "contentIntentId": spec.content_intent_id,
                "contentIntentFingerprint": spec.content_intent_fingerprint,
                "contentIntent": spec.content_intent,
                "sourcePath": str(spec.source_path) if spec.source_path else None,
                "sourceSha256": source_sha,
                "promptSource": prompt_source,
                "audioPath": str(spec.audio_path) if spec.audio_path else None,
                "audioSha256": audio_sha,
                "lastImagePath": (
                    str(spec.last_image_path) if spec.last_image_path else None
                ),
                "lastImageSha256": last_image_sha,
                "sourceVideoPath": (
                    str(spec.source_video_path) if spec.source_video_path else None
                ),
                "sourceVideoSha256": source_video_sha,
                "retakeStartFrame": spec.retake_start_frame,
                "retakeEndFrame": spec.retake_end_frame,
                "extendFrames": spec.extend_frames,
                "extendDirection": spec.extend_direction,
                "preserveAudio": spec.preserve_audio,
                "modelId": spec.model_id,
                "modelRevision": str(status["manifest"]["revision"]),
                "modelManifestSha256": manifest_sha,
                "modelDeepVerificationFingerprint": (deep_verification_fingerprint),
                "runtimeBinding": runtime_binding,
                "runtimeBindingFingerprint": runtime_binding_fingerprint,
                "licensePolicy": license_policy,
                "licensePolicyFingerprint": license_policy_fingerprint,
                "modelFingerprint": job.model_fingerprint,
                "capabilityCohort": spec.capability_cohort,
                "taskKind": spec.task_kind,
                "prompt": " ".join(spec.prompt.split()),
                "seed": spec.seed,
                "durationSeconds": spec.duration_seconds,
                "resolution": spec.resolution,
                "audioMode": spec.audio_mode,
                "steps": spec.steps,
                "negativePrompt": spec.negative_prompt,
                "loraPath": str(spec.lora_path) if spec.lora_path else None,
                "loraSha256": (sha256_file(spec.lora_path) if spec.lora_path else None),
                "loraStrength": spec.lora_strength,
                "lowRam": spec.low_ram,
                "tileFrames": spec.tile_frames,
                "tileSpatial": spec.tile_spatial,
                "commercialUse": spec.commercial_use,
                "commercialAnnualRevenueUsd": spec.commercial_annual_revenue_usd,
                "overlaysExist": spec.overlays_exist,
                "taskParameterMaterial": parameter_material,
                "taskParameterFingerprint": parameter_fp,
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
    if payload.get("purpose") == "supervised_rollout" and len(samples) not in (
        ROLLOUT_GATE_SIZES
    ):
        raise LocalQueueError("arena_rollout_gate_size_invalid")
    expected_creators = sorted(
        {str(sample.get("creatorId")) for sample in samples if isinstance(sample, dict)}
    )
    if payload.get("creators") != expected_creators:
        raise LocalQueueError("arena_plan_creator_set_mismatch")
    identities: set[str] = set()
    blinded: set[str] = set()
    outputs: set[str] = set()
    jobs: set[str] = set()
    content_intent_identities: dict[tuple[str, str], str] = {}
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
            creator_identity_profile_id=(
                str(queue_job["creatorIdentityProfileId"])
                if queue_job.get("creatorIdentityProfileId") is not None
                else None
            ),
            creator_identity_profile_fingerprint=(
                str(queue_job["creatorIdentityProfileFingerprint"])
                if queue_job.get("creatorIdentityProfileFingerprint") is not None
                else None
            ),
            content_intent_id=(
                str(queue_job["contentIntentId"])
                if queue_job.get("contentIntentId") is not None
                else None
            ),
            content_intent_fingerprint=(
                str(queue_job["contentIntentFingerprint"])
                if queue_job.get("contentIntentFingerprint") is not None
                else None
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
            runtime_binding=(
                dict(queue_job["runtimeBinding"])
                if isinstance(queue_job.get("runtimeBinding"), dict)
                else None
            ),
            runtime_binding_fingerprint=(
                str(queue_job["runtimeBindingFingerprint"])
                if queue_job.get("runtimeBindingFingerprint") is not None
                else None
            ),
            license_policy=(
                dict(queue_job["licensePolicy"])
                if isinstance(queue_job.get("licensePolicy"), dict)
                else None
            ),
            license_policy_fingerprint=(
                str(queue_job["licensePolicyFingerprint"])
                if queue_job.get("licensePolicyFingerprint") is not None
                else None
            ),
        )
        if job.job_id in jobs:
            raise LocalQueueError("arena_duplicate_queue_job_identity")
        jobs.add(job.job_id)
        recipe = dict(raw["benchmarkRecipe"])
        registry = dict(raw["analyzerRegistry"])
        profile = CreatorIdentityProfileV1.from_dict(
            dict(raw["creatorIdentityProfile"])
        ).to_dict()
        intent = ContentIntentV1.from_dict(dict(raw["contentIntent"])).to_dict()
        if recipe.get("schema") != "creator_os.benchmark_recipe.v1":
            raise ValueError("arena_benchmark_recipe_schema_mismatch")
        promotion_evidence_allowed = recipe.get("promotionEvidenceAllowed")
        purpose = payload.get("purpose")
        if (
            (
                purpose == "supervised_rollout"
                and promotion_evidence_allowed is not False
            )
            or (purpose == "promotion_eligible" and promotion_evidence_allowed is False)
            or (purpose == "exploratory" and promotion_evidence_allowed is True)
        ):
            raise LocalQueueError("arena_benchmark_recipe_evidence_use_mismatch")
        if registry.get("schema") != "creator_os.analyzer_registry.v1":
            raise ValueError("arena_analyzer_registry_schema_mismatch")
        if fingerprint(recipe) != raw.get("benchmarkRecipeFingerprint"):
            raise LocalQueueError("arena_benchmark_recipe_fingerprint_mismatch")
        if fingerprint(registry) != raw.get("analyzerRegistryFingerprint"):
            raise LocalQueueError("arena_analyzer_registry_fingerprint_mismatch")
        stored_parameter_material = raw.get("taskParameterMaterial")
        stored_parameter_fingerprint = raw.get("taskParameterFingerprint")
        if stored_parameter_material is None and stored_parameter_fingerprint is None:
            # Historical v1 plans remain readable but cannot be executed or
            # admitted because the execution boundaries require this evidence.
            pass
        elif not isinstance(stored_parameter_material, dict):
            raise LocalQueueError("arena_task_parameter_material_invalid")
        else:
            current_parameter_material = local_video_task_parameter_material(
                _request_from_sample(raw),
                runtime_binding=raw.get("runtimeBinding"),
            )
            current_parameter_fingerprint = task_parameter_fingerprint(
                current_parameter_material
            )
            current_benchmark_parameter_fingerprint = (
                benchmark_task_parameter_fingerprint(current_parameter_material)
            )
            if (
                stored_parameter_material != current_parameter_material
                or stored_parameter_fingerprint != current_parameter_fingerprint
                or recipe.get("parameterFingerprint")
                != current_benchmark_parameter_fingerprint
            ):
                raise LocalQueueError("arena_task_parameter_material_mismatch")
        if (
            raw.get("identityProfileId") != profile.get("profileId")
            or raw.get("identityProfileFingerprint") != fingerprint(profile)
            or str(profile.get("creatorKey") or "").lower()
            != str(raw.get("creatorId") or "").lower()
        ):
            raise LocalQueueError("arena_creator_identity_profile_binding_mismatch")
        if (
            raw.get("contentIntentId") != intent.get("intentId")
            or raw.get("contentIntentFingerprint") != fingerprint(intent)
            or intent.get("creatorIdentityProfileId") != profile.get("profileId")
        ):
            raise LocalQueueError("arena_content_intent_binding_mismatch")
        intent_id = str(intent["intentId"])
        intent_fingerprint = fingerprint(intent)
        existing_intent_fingerprint = content_intent_identities.setdefault(
            (str(raw["creatorId"]), intent_id), intent_fingerprint
        )
        if existing_intent_fingerprint != intent_fingerprint:
            raise LocalQueueError("arena_content_intent_identity_collision")
        if (
            job.benchmark_recipe_id != recipe.get("recipeId")
            or job.benchmark_recipe_fingerprint != fingerprint(recipe)
            or job.analyzer_registry_id != registry.get("registryId")
            or job.analyzer_registry_fingerprint != fingerprint(registry)
            or job.creator_identity_profile_id != profile.get("profileId")
            or job.creator_identity_profile_fingerprint != fingerprint(profile)
            or job.content_intent_id != intent.get("intentId")
            or job.content_intent_fingerprint != fingerprint(intent)
            or job.runtime_binding != raw.get("runtimeBinding")
            or job.runtime_binding_fingerprint != raw.get("runtimeBindingFingerprint")
            or job.license_policy != raw.get("licensePolicy")
            or job.license_policy_fingerprint != raw.get("licensePolicyFingerprint")
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
        runtime_binding = deep_receipt.get("runtimeBinding")
        runtime_binding_fingerprint = deep_receipt.get("runtimeBindingFingerprint")
        if (
            not isinstance(runtime_binding, dict)
            or fingerprint(runtime_binding) != runtime_binding_fingerprint
            or raw.get("runtimeBinding") != runtime_binding
            or raw.get("runtimeBindingFingerprint") != runtime_binding_fingerprint
        ):
            raise LocalQueueError("arena_runtime_binding_missing_or_drifted")
        model_spec = local_video_model_spec(model_id)
        manifest = current_model.get("manifest")
        expected_license_policy = {
            "licenseId": model_spec.license_id,
            "commercialUse": raw.get("commercialUse"),
            "declaredAnnualRevenueUsd": raw.get("commercialAnnualRevenueUsd"),
            "commercialRevenueLimitUsd": model_spec.commercial_revenue_limit_usd,
            "commercialUseAllowed": True,
            "aiDisclosureRequired": model_spec.ai_disclosure_required,
        }
        if (
            not isinstance(manifest, dict)
            or manifest.get("licenseId") != model_spec.license_id
            or manifest.get("commercialRevenueLimitUsd")
            != model_spec.commercial_revenue_limit_usd
            or raw.get("licensePolicy") != expected_license_policy
            or raw.get("licensePolicyFingerprint")
            != fingerprint(expected_license_policy)
        ):
            raise LocalQueueError("arena_model_license_evidence_drift")
        if raw.get("promotionEligible") is not (
            payload.get("purpose") == "promotion_eligible"
        ):
            raise LocalQueueError("arena_sample_promotion_eligibility_mismatch")
        source_path = raw.get("sourcePath")
        source_video_path = raw.get("sourceVideoPath")
        if raw.get("taskKind") == "text_to_video":
            if source_path is not None or source_video_path is not None:
                raise LocalQueueError("arena_text_task_media_source_forbidden")
            if raw.get("sourceSha256") != fingerprint(
                {
                    "taskKind": "text_to_video",
                    "prompt": " ".join(str(raw.get("prompt") or "").split()),
                }
            ):
                raise LocalQueueError("arena_text_task_source_identity_mismatch")
            prompt_source = raw.get("promptSource")
            if not isinstance(prompt_source, dict):
                raise LocalQueueError("arena_text_task_prompt_source_missing")
            prompt_path = Path(str(prompt_source.get("path") or "")).resolve()
            if (
                set(prompt_source) != {"path", "sha256"}
                or prompt_source.get("sha256") != raw.get("sourceSha256")
                or not prompt_path.is_file()
                or prompt_path.is_symlink()
                or sha256_file(prompt_path) != raw.get("sourceSha256")
            ):
                raise LocalQueueError(
                    "arena_text_task_prompt_source_missing_or_substituted"
                )
            primary_source = None
        elif raw.get("taskKind") in {"video_retake", "video_extend"}:
            if source_path is not None or source_video_path is None:
                raise LocalQueueError("arena_video_task_primary_source_invalid")
            primary_source = Path(str(source_video_path)).resolve()
        else:
            if raw.get("promptSource") is not None:
                raise LocalQueueError("arena_media_task_prompt_source_forbidden")
            if source_path is None:
                raise LocalQueueError("arena_image_task_primary_source_missing")
            primary_source = Path(str(source_path)).resolve()
        if primary_source is not None and (
            not primary_source.is_file()
            or sha256_file(primary_source) != raw.get("sourceSha256")
        ):
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
        for prefix in ("lastImage", "sourceVideo"):
            raw_path = raw.get(f"{prefix}Path")
            raw_sha = raw.get(f"{prefix}Sha256")
            if raw_path is None:
                if raw_sha is not None:
                    raise LocalQueueError(f"arena_{prefix.lower()}_binding_incomplete")
                continue
            path = Path(str(raw_path)).resolve()
            if not path.is_file() or raw_sha is None or sha256_file(path) != raw_sha:
                raise LocalQueueError(f"arena_{prefix.lower()}_missing_or_substituted")
        exact_bindings = canonical_task_input_bindings(
            str(raw["taskKind"]),
            image_sha256=(
                str(raw["sourceSha256"]) if raw.get("sourcePath") is not None else None
            ),
            audio_sha256=(
                str(raw["audioSha256"]) if raw.get("audioSha256") is not None else None
            ),
            last_image_sha256=(
                str(raw["lastImageSha256"])
                if raw.get("lastImageSha256") is not None
                else None
            ),
            source_video_sha256=(
                str(raw["sourceVideoSha256"])
                if raw.get("sourceVideoSha256") is not None
                else None
            ),
        )
        exact_inputs = [binding["sha256"] for binding in exact_bindings]
        if recipe.get("inputFingerprints") != exact_inputs or not set(
            exact_inputs
        ).issubset(set(intent.get("sourceAssetFingerprints") or [])):
            raise LocalQueueError("arena_extended_input_fingerprint_mismatch")
        if raw.get("preserveAudio") is not (raw.get("audioMode") == "preserved"):
            raise LocalQueueError("arena_preserve_audio_binding_mismatch")
        if raw.get("audioMode") == "preserved" and raw.get("sourceVideoPath") is None:
            raise LocalQueueError("arena_preserve_audio_source_video_missing")
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
                    statistics.median(latency)
                    if len(latency) == len(valid) and latency
                    else None
                ),
                "medianPeakMemoryBytes": (
                    statistics.median(memory)
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


def _rollout_count_map(
    samples: Sequence[Mapping[str, Any]], field: str
) -> dict[str, int]:
    return dict(sorted(Counter(str(sample[field]) for sample in samples).items()))


def _rollout_plan_counts(plan: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    samples = tuple(dict(sample) for sample in plan["samples"])
    return {
        "creatorCounts": _rollout_count_map(samples, "creatorId"),
        "modelCounts": _rollout_count_map(samples, "modelId"),
        "capabilityCounts": _rollout_count_map(samples, "capabilityCohort"),
    }


def validate_rollout_gate_receipt(
    receipt: Mapping[str, Any],
    *,
    arena_plan: Mapping[str, Any],
    evidence_secret: str | None = None,
) -> dict[str, Any]:
    validate_local_model_rollout_gate_receipt(dict(receipt))
    plan = validate_arena_plan(arena_plan)
    if plan.get("purpose") != "supervised_rollout":
        raise LocalQueueError("arena_rollout_requires_non_promotion_plan")
    payload = dict(receipt)
    attestation = payload.pop("operatorAttestation", None)
    claimed = _valid_sha256(
        payload.pop("receiptFingerprint", None), "rollout_receipt_fingerprint"
    )
    if fingerprint(payload) != claimed:
        raise LocalQueueError("arena_rollout_receipt_fingerprint_mismatch")
    signed_payload = {**payload, "receiptFingerprint": claimed}
    if not isinstance(attestation, dict):
        raise LocalQueueError("arena_rollout_receipt_attestation_missing")
    try:
        verify_evidence_attestation(
            attestation,
            signed_payload,
            secret=evidence_secret or load_evidence_secret(),
            expected_issuer=ROLLOUT_GATE_ISSUER,
        )
    except EvidenceAttestationError as exc:
        raise LocalQueueError("arena_rollout_receipt_attestation_invalid") from exc
    expected_counts = _rollout_plan_counts(plan)
    if (
        payload.get("arenaPlanId") != plan["planId"]
        or payload.get("arenaPlanFingerprint") != plan["planFingerprint"]
        or payload.get("gateSize") != plan["expectedSampleCount"]
        or any(payload.get(field) != value for field, value in expected_counts.items())
    ):
        raise LocalQueueError("arena_rollout_receipt_plan_binding_mismatch")
    gate_size = int(payload["gateSize"])
    predecessor = payload.get("predecessorReceiptFingerprint")
    if (gate_size == ROLLOUT_GATE_SIZES[0]) is not (predecessor is None):
        raise LocalQueueError("arena_rollout_predecessor_nullability_invalid")
    if payload.get("decision") != payload.get("transition"):
        raise LocalQueueError("arena_rollout_transition_decision_mismatch")
    planned = {str(sample["sampleId"]): sample for sample in plan["samples"]}
    referenced_sample_ids = [
        str(sample_id)
        for reference in payload["routerEvidence"]
        for sample_id in reference["sampleIds"]
    ]
    if len(referenced_sample_ids) != len(set(referenced_sample_ids)) or set(
        referenced_sample_ids
    ) != set(planned):
        raise LocalQueueError("arena_rollout_router_sample_partition_invalid")
    for reference in payload["routerEvidence"]:
        for sample_id in reference["sampleIds"]:
            sample = planned[str(sample_id)]
            if (
                reference["selectedModelId"] != sample["modelId"]
                or reference["selectedModelFingerprint"] != sample["modelFingerprint"]
                or reference["taskKind"] != sample["taskKind"]
                or reference["capabilityCohort"] != sample["capabilityCohort"]
            ):
                raise LocalQueueError("arena_rollout_router_reference_plan_mismatch")
    summary_evidence = payload.get("summaryEvidence")
    if isinstance(summary_evidence, dict):
        if (
            sum(int(value) for value in summary_evidence["terminalCounts"].values())
            != gate_size
        ):
            raise LocalQueueError("arena_rollout_terminal_counts_mismatch")
        failed_sample_ids = [
            str(sample["sampleId"])
            for sample in summary_evidence["failedOrHeldSamples"]
        ]
        if len(failed_sample_ids) != len(set(failed_sample_ids)) or not set(
            failed_sample_ids
        ).issubset(planned):
            raise LocalQueueError("arena_rollout_failed_sample_set_invalid")
        criteria = dict(summary_evidence["gateCriteria"])
        criteria_fingerprint = criteria.pop("criteriaFingerprint")
        if (
            criteria.get("gateSize") != gate_size
            or fingerprint(criteria) != criteria_fingerprint
            or criteria.get("passed") is not (not criteria.get("blockingReasons"))
        ):
            raise LocalQueueError("arena_rollout_gate_criteria_invalid")
    return {
        **payload,
        "receiptFingerprint": claimed,
        "operatorAttestation": attestation,
    }


def _validate_rollout_router_bundle(
    bundle: Mapping[str, Any],
    *,
    benchmark_store: LocalModelBenchmarkStore,
    human_reviews: HumanMediaReviewStore,
    observed_at: str,
    evidence_secret: str | None,
    require_active_promotion: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from .local_model_router import validate_router_decision

    exact = dict(bundle)
    if set(exact) != {
        "arenaPlan",
        "arenaSummary",
        "reviewPacket",
        "unblindingReceipt",
        "routerDecision",
        "rolloutSampleIds",
    } or not all(
        isinstance(exact[field], dict)
        for field in (
            "arenaPlan",
            "arenaSummary",
            "reviewPacket",
            "unblindingReceipt",
            "routerDecision",
        )
    ):
        raise LocalQueueError("arena_rollout_router_evidence_bundle_invalid")
    rollout_sample_ids = exact["rolloutSampleIds"]
    if (
        not isinstance(rollout_sample_ids, list)
        or not rollout_sample_ids
        or any(
            not isinstance(sample_id, str) or not sample_id.strip()
            for sample_id in rollout_sample_ids
        )
        or len(rollout_sample_ids) != len(set(rollout_sample_ids))
    ):
        raise LocalQueueError("arena_rollout_router_sample_ids_invalid")
    promotion_plan = validate_arena_plan(dict(exact["arenaPlan"]))
    if promotion_plan.get("purpose") != "promotion_eligible":
        raise LocalQueueError("arena_rollout_router_evidence_not_promotion_plan")
    promotion_summary = validate_arena_summary(
        dict(exact["arenaSummary"]), arena_plan=promotion_plan
    )
    packet = validate_arena_review_packet(
        dict(exact["reviewPacket"]),
        arena_plan=promotion_plan,
        evidence_secret=evidence_secret,
    )
    unblinding = validate_arena_unblinding_receipt(
        dict(exact["unblindingReceipt"]),
        arena_plan=promotion_plan,
        review_packet=packet,
        human_reviews=human_reviews,
        evidence_secret=evidence_secret,
    )
    expected_review_evidence = {
        "reviewPacketId": packet["packetId"],
        "reviewPacketFingerprint": packet["packetFingerprint"],
        "unblindingReceiptId": unblinding["receiptId"],
        "unblindingReceiptFingerprint": unblinding["receiptFingerprint"],
    }
    if promotion_summary.get("reviewEvidence") != expected_review_evidence:
        raise LocalQueueError("arena_rollout_router_review_evidence_mismatch")
    decision = validate_router_decision(
        dict(exact["routerDecision"]),
        arena_plan=promotion_plan,
        arena_summary=promotion_summary,
    )
    if (
        decision.get("paidProviderFallbackAllowed") is not False
        or decision.get("legacyLocalMotionFallbackAllowed") is not False
    ):
        raise LocalQueueError("arena_rollout_router_fallback_forbidden")
    if decision.get("operatorOverride") is not None:
        raise LocalQueueError("arena_rollout_router_override_forbidden")
    winning = dict(decision["winningEvidence"])
    approval = winning.get("promotionApproval")
    if not isinstance(approval, dict):
        raise LocalQueueError("arena_rollout_router_promotion_missing")
    if require_active_promotion:
        active = benchmark_store.active_promotion(
            candidate_model_fingerprint=str(decision["selectedModelFingerprint"]),
            task_kind=str(decision["request"]["taskKind"]),
            candidate_benchmark_ids=tuple(
                str(value) for value in winning["benchmarkIds"]
            ),
            hardware_fingerprint=str(approval["hardwareFingerprint"]),
            observed_at=observed_at,
        )
        if active != approval:
            raise LocalQueueError("arena_rollout_router_promotion_not_active")
    snapshot_fingerprint = fingerprint(exact)
    reference = {
        "snapshotFingerprint": snapshot_fingerprint,
        "sampleIds": sorted(rollout_sample_ids),
        "routerDecisionId": decision["decisionId"],
        "routerDecisionFingerprint": decision["decisionFingerprint"],
        "selectedModelId": decision["selectedModelId"],
        "selectedModelFingerprint": decision["selectedModelFingerprint"],
        "taskKind": decision["request"]["taskKind"],
        "capabilityCohort": decision["request"]["capabilityCohort"],
        "promotionArenaPlanFingerprint": promotion_plan["planFingerprint"],
        "promotionArenaSummaryFingerprint": promotion_summary["summaryFingerprint"],
        "promotionReviewPacketFingerprint": packet["packetFingerprint"],
        "promotionUnblindingReceiptFingerprint": unblinding["receiptFingerprint"],
        "promotionApprovalEventId": approval["approvalEventId"],
        "promotionApprovalEventHash": approval["approvalEventHash"],
        "promotionEvidenceFingerprint": approval["evidenceFingerprint"],
    }
    return exact, reference


def _rollout_router_bundle_matches_sample(
    bundle: Mapping[str, Any], sample: Mapping[str, Any]
) -> bool:
    decision = dict(bundle["routerDecision"])
    request = dict(decision["request"])
    return (
        decision["selectedModelId"] == sample["modelId"]
        and decision["selectedModelFingerprint"] == sample["modelFingerprint"]
        and request["creatorId"] == sample["creatorId"]
        and request["identityProfileId"] == sample["identityProfileId"]
        and request["identityProfileFingerprint"]
        == sample["identityProfileFingerprint"]
        and request["contentIntentId"] == sample["contentIntentId"]
        and request["contentIntentFingerprint"] == sample["contentIntentFingerprint"]
        and request["taskKind"] == sample["taskKind"]
        and request["capabilityCohort"] == sample["capabilityCohort"]
    )


class LocalModelArenaStore:
    """Persist immutable Arena plans and outcomes beside benchmark evidence."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.plans = self.root / "arena_plans"
        self.identity_profiles = self.root / "creator_identity_profiles"
        self.content_intents = self.root / "content_intents"
        self.review_packets = self.root / "arena_review_packets"
        self.unblinding_receipts = self.root / "arena_unblinding_receipts"
        self.rollout_router_evidence = self.root / "arena_rollout_router_evidence"
        self.rollout_summaries = self.root / "arena_rollout_summaries"
        self.events = AppendOnlyJournal(self.root / "arena_events.jsonl")
        self._mutation = self.root / "arena_mutation"

    def persist_plan(self, plan: Mapping[str, Any]) -> Path:
        payload = validate_arena_plan(plan)
        plan_id = str(payload["planId"])
        path = self.plans / f"{plan_id}.json"
        encoded = _canonical(payload)
        with file_lock(self._mutation):
            for sample in payload["samples"]:
                self._persist_record_snapshot(
                    self.identity_profiles,
                    dict(sample["creatorIdentityProfile"]),
                    str(sample["identityProfileFingerprint"]),
                )
                self._persist_record_snapshot(
                    self.content_intents,
                    dict(sample["contentIntent"]),
                    str(sample["contentIntentFingerprint"]),
                )
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

    @staticmethod
    def _persist_record_snapshot(
        directory: Path, payload: Mapping[str, Any], expected_fingerprint: str
    ) -> Path:
        if fingerprint(payload) != expected_fingerprint:
            raise LocalQueueError("arena_record_snapshot_fingerprint_mismatch")
        path = directory / f"{expected_fingerprint}.json"
        _write_exact_json(path, payload)
        if sha256_file(path) != expected_fingerprint:
            raise LocalQueueError("arena_record_snapshot_persistence_failed")
        return path

    def _verify_record_snapshots(self, plan: Mapping[str, Any]) -> None:
        for sample in plan["samples"]:
            for directory, field, fingerprint_field in (
                (
                    self.identity_profiles,
                    "creatorIdentityProfile",
                    "identityProfileFingerprint",
                ),
                (self.content_intents, "contentIntent", "contentIntentFingerprint"),
            ):
                expected = str(sample[fingerprint_field])
                path = directory / f"{expected}.json"
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or sha256_file(path) != expected
                    or json.loads(path.read_text(encoding="utf-8")) != sample[field]
                ):
                    raise LocalQueueError("arena_record_snapshot_missing_or_drifted")

    def load_plan(self, plan_id: str) -> dict[str, Any]:
        path = self.plans / f"{plan_id}.json"
        if not path.is_file() or path.is_symlink():
            raise LocalQueueError("arena_plan_not_found")
        plan = validate_arena_plan(json.loads(path.read_text(encoding="utf-8")))
        self._verify_record_snapshots(plan)
        return plan

    def _rollout_transition_events(self) -> list[dict[str, Any]]:
        return [
            dict(event)
            for event in self.events.read().events
            if event.get("eventType") == "arena_rollout_gate_transition"
        ]

    def _validated_rollout_event(
        self,
        event: Mapping[str, Any],
        *,
        evidence_secret: str | None = None,
    ) -> dict[str, Any]:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise LocalQueueError("arena_rollout_event_payload_invalid")
        plan = self.load_plan(str(payload.get("arenaPlanId") or ""))
        return validate_rollout_gate_receipt(
            payload, arena_plan=plan, evidence_secret=evidence_secret
        )

    def _rollout_receipt_by_fingerprint(
        self,
        receipt_fingerprint: str,
        *,
        evidence_secret: str | None = None,
    ) -> dict[str, Any]:
        matches = [
            self._validated_rollout_event(event, evidence_secret=evidence_secret)
            for event in self._rollout_transition_events()
            if event.get("payload", {}).get("receiptFingerprint") == receipt_fingerprint
        ]
        if len(matches) != 1:
            raise LocalQueueError(
                "arena_rollout_receipt_not_found_exactly_once:" + receipt_fingerprint
            )
        return matches[0]

    def _rollout_gate_receipts(
        self,
        plan_id: str,
        *,
        evidence_secret: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            self._validated_rollout_event(event, evidence_secret=evidence_secret)
            for event in self._rollout_transition_events()
            if event.get("payload", {}).get("arenaPlanId") == plan_id
        ]

    def _persist_rollout_snapshot(
        self, directory: Path, payload: Mapping[str, Any]
    ) -> str:
        expected = fingerprint(payload)
        path = directory / f"{expected}.json"
        _write_exact_json(path, payload)
        if sha256_file(path) != expected:
            raise LocalQueueError("arena_rollout_snapshot_persistence_failed")
        return expected

    def _load_rollout_snapshot(
        self, directory: Path, expected_fingerprint: str
    ) -> dict[str, Any]:
        path = directory / f"{expected_fingerprint}.json"
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != expected_fingerprint
        ):
            raise LocalQueueError("arena_rollout_snapshot_missing_or_substituted")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalQueueError("arena_rollout_snapshot_invalid") from exc
        if (
            not isinstance(payload, dict)
            or fingerprint(payload) != expected_fingerprint
        ):
            raise LocalQueueError("arena_rollout_snapshot_fingerprint_mismatch")
        return payload

    def _rollout_external_activity(
        self,
        plan: Mapping[str, Any],
        *,
        summary: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        terminal_events = [
            event
            for event in self.events.read().events
            if event.get("eventType") == "arena_sample_terminal"
            and event.get("payload", {}).get("planId") == plan["planId"]
        ]
        terminal_provider_calls = sum(
            int(event.get("payload", {}).get("providerCalls", -1))
            for event in terminal_events
        )
        terminal_production_writes = sum(
            int(event.get("payload", {}).get("productionWrites", -1))
            for event in terminal_events
        )
        activity = {
            "planProviderCalls": plan["providerCalls"],
            "planProductionWritesAllowed": plan["productionWritesAllowed"],
            "summaryProviderCalls": (
                summary.get("providerCalls") if summary is not None else None
            ),
            "summaryProductionWrites": (
                summary.get("productionWrites") if summary is not None else None
            ),
            "terminalEventCount": len(terminal_events),
            "terminalEventProviderCalls": terminal_provider_calls,
            "terminalEventProductionWrites": terminal_production_writes,
            "observedProviderCalls": (
                int(plan["providerCalls"])
                + terminal_provider_calls
                + int(summary.get("providerCalls", 0) if summary is not None else 0)
            ),
            "observedProductionWrites": (
                terminal_production_writes
                + int(summary.get("productionWrites", 0) if summary is not None else 0)
            ),
        }
        if (
            activity["planProviderCalls"] != 0
            or activity["planProductionWritesAllowed"] is not False
            or activity["terminalEventProviderCalls"] != 0
            or activity["terminalEventProductionWrites"] != 0
            or activity["observedProviderCalls"] != 0
            or activity["observedProductionWrites"] != 0
            or (
                summary is not None
                and (
                    activity["summaryProviderCalls"] != 0
                    or activity["summaryProductionWrites"] != 0
                )
            )
        ):
            raise LocalQueueError("arena_rollout_external_activity_detected")
        return activity

    def _append_rollout_receipt(
        self,
        core: Mapping[str, Any],
        *,
        evidence_secret: str | None,
    ) -> dict[str, Any]:
        exact_core = dict(core)
        receipt_fingerprint = fingerprint(exact_core)
        signed_payload = {
            **exact_core,
            "receiptFingerprint": receipt_fingerprint,
        }
        secret = evidence_secret or load_evidence_secret()
        receipt = {
            **signed_payload,
            "operatorAttestation": sign_evidence_attestation(
                signed_payload,
                issuer=ROLLOUT_GATE_ISSUER,
                issued_at=str(exact_core["decidedAt"]),
                secret=secret,
            ),
        }
        plan = self.load_plan(str(exact_core["arenaPlanId"]))
        validated = validate_rollout_gate_receipt(
            receipt, arena_plan=plan, evidence_secret=secret
        )
        event = self.events.append("arena_rollout_gate_transition", validated)
        return {"event": event, "receipt": validated}

    def _verify_rollout_predecessor(
        self,
        *,
        rollout_id: str,
        gate_size: int,
        predecessor_receipt_fingerprint: str | None,
        evidence_secret: str | None,
    ) -> None:
        gate_index = ROLLOUT_GATE_SIZES.index(gate_size)
        rollout_receipts = [
            self._validated_rollout_event(event, evidence_secret=evidence_secret)
            for event in self._rollout_transition_events()
            if event.get("payload", {}).get("rolloutId") == rollout_id
        ]
        if gate_index == 0:
            if predecessor_receipt_fingerprint is not None:
                raise LocalQueueError("arena_rollout_gate_10_predecessor_forbidden")
            if rollout_receipts:
                raise LocalQueueError("arena_rollout_gate_order_invalid")
            return
        if predecessor_receipt_fingerprint is None:
            raise LocalQueueError("arena_rollout_predecessor_required")
        predecessor = self._rollout_receipt_by_fingerprint(
            predecessor_receipt_fingerprint,
            evidence_secret=evidence_secret,
        )
        expected_gate_size = ROLLOUT_GATE_SIZES[gate_index - 1]
        if (
            predecessor["rolloutId"] != rollout_id
            or predecessor["gateSize"] != expected_gate_size
            or predecessor["transition"] != "approved_to_escalate"
        ):
            raise LocalQueueError("arena_rollout_predecessor_invalid")
        if (
            not rollout_receipts
            or rollout_receipts[-1]["receiptFingerprint"]
            != predecessor_receipt_fingerprint
            or any(receipt["gateSize"] == gate_size for receipt in rollout_receipts)
        ):
            raise LocalQueueError("arena_rollout_gate_order_invalid")

    def approve_rollout_gate(
        self,
        *,
        plan_id: str,
        rollout_id: str,
        operator_identity: str,
        decided_at: str,
        reason: str,
        mode_confirmation: str,
        router_evidence_bundles: Sequence[Mapping[str, Any]],
        benchmark_store: LocalModelBenchmarkStore,
        human_reviews: HumanMediaReviewStore,
        predecessor_receipt_fingerprint: str | None = None,
        evidence_secret: str | None = None,
    ) -> dict[str, Any]:
        plan = self.load_plan(plan_id)
        if plan.get("purpose") != "supervised_rollout":
            raise LocalQueueError("arena_rollout_requires_non_promotion_plan")
        gate_size = int(plan["expectedSampleCount"])
        if gate_size not in ROLLOUT_GATE_SIZES:
            raise LocalQueueError("arena_rollout_gate_size_invalid")
        if mode_confirmation != ROLLOUT_MODE_CONFIRMATION:
            raise LocalQueueError("arena_rollout_mode_confirmation_invalid")
        if (
            not rollout_id.strip()
            or not operator_identity.strip()
            or not reason.strip()
        ):
            raise ValueError("arena_rollout_operator_fields_missing")
        if self._rollout_gate_receipts(plan_id, evidence_secret=evidence_secret):
            raise LocalQueueError("arena_rollout_gate_already_transitioned")
        self._verify_rollout_predecessor(
            rollout_id=rollout_id,
            gate_size=gate_size,
            predecessor_receipt_fingerprint=predecessor_receipt_fingerprint,
            evidence_secret=evidence_secret,
        )
        if not router_evidence_bundles:
            raise LocalQueueError("arena_rollout_router_evidence_required")
        snapshots: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        for raw_bundle in router_evidence_bundles:
            snapshot, reference = _validate_rollout_router_bundle(
                raw_bundle,
                benchmark_store=benchmark_store,
                human_reviews=human_reviews,
                observed_at=decided_at,
                evidence_secret=evidence_secret,
            )
            snapshots.append(snapshot)
            references.append(reference)
        reference_fingerprints = [
            str(reference["snapshotFingerprint"]) for reference in references
        ]
        if len(reference_fingerprints) != len(set(reference_fingerprints)):
            raise LocalQueueError("arena_rollout_router_evidence_duplicate")
        planned_samples = {
            str(sample["sampleId"]): sample for sample in plan["samples"]
        }
        for sample_id, sample in planned_samples.items():
            matches = [
                snapshot
                for snapshot, reference in zip(snapshots, references, strict=True)
                if sample_id in reference["sampleIds"]
                and _rollout_router_bundle_matches_sample(snapshot, sample)
            ]
            if len(matches) != 1:
                raise LocalQueueError(
                    "arena_rollout_sample_router_evidence_not_exactly_once:" + sample_id
                )
        referenced_sample_ids = [
            str(sample_id)
            for reference in references
            for sample_id in reference["sampleIds"]
        ]
        if len(referenced_sample_ids) != len(set(referenced_sample_ids)) or set(
            referenced_sample_ids
        ) != set(planned_samples):
            raise LocalQueueError("arena_rollout_router_sample_partition_invalid")
        activity = self._rollout_external_activity(plan, summary=None)
        if activity["terminalEventCount"] != 0:
            raise LocalQueueError("arena_rollout_activity_precedes_approval")
        with file_lock(self._mutation):
            if self._rollout_gate_receipts(plan_id, evidence_secret=evidence_secret):
                raise LocalQueueError("arena_rollout_gate_already_transitioned")
            self._verify_rollout_predecessor(
                rollout_id=rollout_id,
                gate_size=gate_size,
                predecessor_receipt_fingerprint=predecessor_receipt_fingerprint,
                evidence_secret=evidence_secret,
            )
            for snapshot, reference in zip(snapshots, references, strict=True):
                persisted = self._persist_rollout_snapshot(
                    self.rollout_router_evidence, snapshot
                )
                if persisted != reference["snapshotFingerprint"]:
                    raise LocalQueueError(
                        "arena_rollout_router_snapshot_fingerprint_mismatch"
                    )
            gate_id = f"rollout_gate_{gate_size}_{plan['planFingerprint'][:24]}"
            core = {
                "schema": ROLLOUT_GATE_SCHEMA,
                "receiptId": f"{gate_id}_approved_to_run",
                "rolloutId": rollout_id,
                "gateId": gate_id,
                "gateSize": gate_size,
                "transition": "approved_to_run",
                "arenaPlanId": plan["planId"],
                "arenaPlanFingerprint": plan["planFingerprint"],
                "predecessorReceiptFingerprint": predecessor_receipt_fingerprint,
                "previousReceiptFingerprint": None,
                **_rollout_plan_counts(plan),
                "routerEvidence": sorted(
                    references,
                    key=lambda item: (
                        item["routerDecisionFingerprint"],
                        item["snapshotFingerprint"],
                    ),
                ),
                "modeConfirmation": mode_confirmation,
                "operatorIdentity": operator_identity,
                "decidedAt": decided_at,
                "decision": "approved_to_run",
                "reason": reason,
                "summaryEvidence": None,
                "externalActivity": activity,
            }
            return self._append_rollout_receipt(core, evidence_secret=evidence_secret)

    def _verify_rollout_router_snapshots(
        self,
        *,
        plan: Mapping[str, Any],
        receipt: Mapping[str, Any],
        benchmark_store: LocalModelBenchmarkStore,
        human_reviews: HumanMediaReviewStore,
        observed_at: str,
        evidence_secret: str | None,
        require_active_promotion: bool,
    ) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for reference in receipt["routerEvidence"]:
            snapshot = self._load_rollout_snapshot(
                self.rollout_router_evidence,
                str(reference["snapshotFingerprint"]),
            )
            validated_snapshot, exact_reference = _validate_rollout_router_bundle(
                snapshot,
                benchmark_store=benchmark_store,
                human_reviews=human_reviews,
                observed_at=observed_at,
                evidence_secret=evidence_secret,
                require_active_promotion=require_active_promotion,
            )
            if exact_reference != reference:
                raise LocalQueueError("arena_rollout_router_reference_drift")
            snapshots.append(validated_snapshot)
        planned_samples = {
            str(sample["sampleId"]): sample for sample in plan["samples"]
        }
        references = list(receipt["routerEvidence"])
        for sample_id, sample in planned_samples.items():
            matches = [
                snapshot
                for snapshot, reference in zip(snapshots, references, strict=True)
                if sample_id in reference["sampleIds"]
                and _rollout_router_bundle_matches_sample(snapshot, sample)
            ]
            if len(matches) != 1:
                raise LocalQueueError(
                    "arena_rollout_sample_router_evidence_not_exactly_once:" + sample_id
                )
        referenced_sample_ids = [
            str(sample_id)
            for reference in references
            for sample_id in reference["sampleIds"]
        ]
        if len(referenced_sample_ids) != len(set(referenced_sample_ids)) or set(
            referenced_sample_ids
        ) != set(planned_samples):
            raise LocalQueueError("arena_rollout_router_sample_partition_invalid")
        return snapshots

    def require_rollout_approved_to_run(
        self,
        plan_id: str,
        *,
        benchmark_store: LocalModelBenchmarkStore,
        human_reviews: HumanMediaReviewStore,
        sample_id: str | None = None,
        observed_at: str | None = None,
        evidence_secret: str | None = None,
    ) -> dict[str, Any]:
        plan = self.load_plan(plan_id)
        if plan.get("purpose") != "supervised_rollout":
            raise LocalQueueError("arena_rollout_requires_non_promotion_plan")
        receipts = self._rollout_gate_receipts(plan_id, evidence_secret=evidence_secret)
        if len(receipts) != 1 or receipts[0].get("transition") != "approved_to_run":
            raise LocalQueueError("arena_rollout_gate_not_executable")
        approval = receipts[0]
        self._verify_rollout_router_snapshots(
            plan=plan,
            receipt=approval,
            benchmark_store=benchmark_store,
            human_reviews=human_reviews,
            observed_at=observed_at or datetime.now(UTC).isoformat(),
            evidence_secret=evidence_secret,
            require_active_promotion=True,
        )
        activity = self._rollout_external_activity(plan, summary=None)
        if activity["terminalEventCount"] >= int(plan["expectedSampleCount"]):
            raise LocalQueueError("arena_rollout_gate_not_executable")
        if sample_id is not None and any(
            event.get("eventType") == "arena_sample_terminal"
            and event.get("payload", {}).get("planId") == plan_id
            and event.get("payload", {}).get("sampleId") == sample_id
            for event in self.events.read().events
        ):
            raise LocalQueueError("arena_rollout_sample_already_terminal")
        return approval

    @staticmethod
    def _rollout_summary_evidence(
        summary: Mapping[str, Any],
        *,
        gate_size: int,
        promotion_active: bool,
    ) -> dict[str, Any]:
        failed_or_held: list[dict[str, Any]] = []
        for sample in summary["samples"]:
            blockers = sorted(str(value) for value in sample["blockingReasons"])
            if sample["status"] == "succeeded" and not blockers:
                continue
            failed_or_held.append(
                {
                    "sampleId": sample["sampleId"],
                    "status": sample["status"],
                    "classification": (
                        "qc_blocked"
                        if sample["status"] == "succeeded"
                        else sample["status"]
                    ),
                    "reason": sample["reason"],
                    "blockingReasons": blockers,
                }
            )
        review_evidence = dict(summary["reviewEvidence"])
        return {
            "summaryId": summary["summaryId"],
            "summaryFingerprint": summary["summaryFingerprint"],
            "reviewPacketFingerprint": review_evidence["reviewPacketFingerprint"],
            "unblindingReceiptFingerprint": review_evidence[
                "unblindingReceiptFingerprint"
            ],
            "terminalCounts": dict(summary["sampleCounts"]),
            "validReviewedYield": summary["promotionEligibleYield"],
            "failedOrHeldSamples": failed_or_held,
            "gateCriteria": LocalModelArenaStore._rollout_gate_criteria(
                summary,
                gate_size=gate_size,
                promotion_active=promotion_active,
            ),
        }

    def _persist_rollout_summary(
        self, summary: Mapping[str, Any], *, plan: Mapping[str, Any]
    ) -> None:
        payload = validate_arena_summary(summary, arena_plan=plan)
        expected = str(payload["summaryFingerprint"])
        path = self.rollout_summaries / f"{expected}.json"
        _write_exact_json(path, payload)
        persisted = validate_arena_summary(
            json.loads(path.read_text(encoding="utf-8")), arena_plan=plan
        )
        if persisted != payload:
            raise LocalQueueError("arena_rollout_summary_persistence_failed")

    def _load_rollout_summary(
        self,
        summary_fingerprint: str,
        *,
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        path = self.rollout_summaries / f"{summary_fingerprint}.json"
        if not path.is_file() or path.is_symlink():
            raise LocalQueueError("arena_rollout_summary_missing_or_substituted")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalQueueError("arena_rollout_summary_invalid") from exc
        payload = validate_arena_summary(raw, arena_plan=plan)
        if payload["summaryFingerprint"] != summary_fingerprint:
            raise LocalQueueError("arena_rollout_summary_fingerprint_mismatch")
        return payload

    def _require_explicit_rollout_terminal_events(
        self, plan: Mapping[str, Any]
    ) -> None:
        planned = [str(sample["sampleId"]) for sample in plan["samples"]]
        observed = [
            str(event.get("payload", {}).get("sampleId"))
            for event in self.events.read().events
            if event.get("eventType") == "arena_sample_terminal"
            and event.get("payload", {}).get("planId") == plan["planId"]
        ]
        if len(observed) != int(plan["expectedSampleCount"]) or Counter(
            observed
        ) != Counter(planned):
            raise LocalQueueError("arena_rollout_terminal_evidence_incomplete")

    @staticmethod
    def _rollout_gate_criteria(
        summary: Mapping[str, Any],
        *,
        gate_size: int,
        promotion_active: bool,
    ) -> dict[str, Any]:
        samples = [dict(sample) for sample in summary["samples"]]
        counts = dict(summary["sampleCounts"])
        no_missing = int(counts.get("missing", 0)) == 0
        integrity_markers = (
            "duplicate",
            "substitut",
            "mismatch",
            "drift",
            "forg",
        )
        no_integrity_blockers = not any(
            any(marker in str(reason) for marker in integrity_markers)
            for sample in samples
            for reason in sample["blockingReasons"]
        )
        valid_yield = float(summary["promotionEligibleYield"])
        minimum_yield = {10: 0.80, 25: 0.75, 50: 1.0, 100: 1.0}[gate_size]
        yield_threshold_met = valid_yield >= minimum_yield
        queue_stability: bool | None = None
        active_distribution: bool | None = None
        failure_recovery: bool | None = None
        sustained_throughput: bool | None = None
        resource_latency_complete: bool | None = None
        if gate_size >= 25:
            queue_stability = (
                int(counts.get("interrupted", 0)) == 0
                and int(counts.get("resource_blocked", 0)) == 0
                and all(
                    isinstance(sample["executionEvidence"].get("attemptCount"), int)
                    and sample["executionEvidence"]["attemptCount"] >= 0
                    and sample["executionEvidence"].get("retryCount")
                    == max(0, sample["executionEvidence"]["attemptCount"] - 1)
                    for sample in samples
                )
            )
        if gate_size >= 50:
            active_distribution = promotion_active
            failure_recovery = all(
                sample["status"] == "succeeded"
                and sample["promotionEvidenceValid"] is True
                for sample in samples
            )
        if gate_size == 100:
            sustained_throughput = (
                int(counts.get("succeeded", 0)) == gate_size
                and failure_recovery is True
            )
            resource_latency_complete = all(
                sample.get("wallTimeSeconds") is not None
                and sample.get("peakMemoryBytes") is not None
                and sample["executionEvidence"]
                .get("executionMeasurement", {})
                .get("available")
                is True
                for sample in samples
            )
        checks = {
            "allSamplesExplicitlyTerminal": True,
            "noMissingEvidence": no_missing,
            "noIntegrityBlockers": no_integrity_blockers,
            "validReviewedYieldThresholdMet": yield_threshold_met,
            "queueStabilityProven": queue_stability,
            "activePromotedRouterDistributionProven": active_distribution,
            "failureRecoveryComplete": failure_recovery,
            "sustainedThroughputProven": sustained_throughput,
            "resourceLatencyEvidenceComplete": resource_latency_complete,
        }
        blocking_reasons: list[str] = []
        for field, reason in (
            ("noMissingEvidence", "rollout_missing_evidence"),
            ("noIntegrityBlockers", "rollout_integrity_blocker"),
            (
                "validReviewedYieldThresholdMet",
                f"rollout_valid_yield_below_{minimum_yield:.2f}",
            ),
        ):
            if checks[field] is not True:
                blocking_reasons.append(reason)
        for field, reason in (
            ("queueStabilityProven", "rollout_queue_stability_not_proven"),
            (
                "activePromotedRouterDistributionProven",
                "rollout_active_router_distribution_not_proven",
            ),
            ("failureRecoveryComplete", "rollout_failure_recovery_incomplete"),
            ("sustainedThroughputProven", "rollout_sustained_throughput_not_proven"),
            (
                "resourceLatencyEvidenceComplete",
                "rollout_resource_latency_evidence_incomplete",
            ),
        ):
            if checks[field] is False:
                blocking_reasons.append(reason)
        core = {
            "schema": "reel_factory.local_model_rollout_gate_criteria.v1",
            "gateSize": gate_size,
            **checks,
            "blockingReasons": sorted(blocking_reasons),
            "passed": not blocking_reasons,
        }
        return {**core, "criteriaFingerprint": fingerprint(core)}

    @staticmethod
    def _rollout_gate_passes(
        summary: Mapping[str, Any],
        *,
        gate_size: int,
        promotion_active: bool = True,
    ) -> bool:
        return bool(
            LocalModelArenaStore._rollout_gate_criteria(
                summary,
                gate_size=gate_size,
                promotion_active=promotion_active,
            )["passed"]
        )

    def record_rollout_reconciliation(
        self,
        *,
        plan_id: str,
        decision: Literal["terminal", "held"],
        operator_identity: str,
        decided_at: str,
        reason: str,
        queue: LocalGenerationQueue,
        benchmark_store: LocalModelBenchmarkStore,
        human_reviews: HumanMediaReviewStore,
        evidence_secret: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"terminal", "held"}:
            raise ValueError("arena_rollout_reconciliation_decision_invalid")
        plan = self.load_plan(plan_id)
        if plan.get("purpose") != "supervised_rollout":
            raise LocalQueueError("arena_rollout_requires_non_promotion_plan")
        receipts = self._rollout_gate_receipts(plan_id, evidence_secret=evidence_secret)
        if len(receipts) != 1 or receipts[0].get("transition") != "approved_to_run":
            raise LocalQueueError("arena_rollout_reconciliation_predecessor_invalid")
        approval = receipts[0]
        self._require_explicit_rollout_terminal_events(plan)
        promotion_active = True
        try:
            self._verify_rollout_router_snapshots(
                plan=plan,
                receipt=approval,
                benchmark_store=benchmark_store,
                human_reviews=human_reviews,
                observed_at=decided_at,
                evidence_secret=evidence_secret,
                require_active_promotion=True,
            )
        except LocalQueueError as exc:
            if (
                decision != "held"
                or str(exc) != "arena_rollout_router_promotion_not_active"
            ):
                raise
            promotion_active = False
            self._verify_rollout_router_snapshots(
                plan=plan,
                receipt=approval,
                benchmark_store=benchmark_store,
                human_reviews=human_reviews,
                observed_at=decided_at,
                evidence_secret=evidence_secret,
                require_active_promotion=False,
            )
        summary = self.summarize(
            plan_id,
            queue=queue,
            benchmarks=benchmark_store,
            human_reviews=human_reviews,
        )
        gate_size = int(plan["expectedSampleCount"])
        gate_passes = self._rollout_gate_passes(
            summary,
            gate_size=gate_size,
            promotion_active=promotion_active,
        )
        if decision == "terminal" and not gate_passes:
            raise LocalQueueError("arena_rollout_gate_pass_criteria_not_met")
        activity = self._rollout_external_activity(plan, summary=summary)
        summary_evidence = self._rollout_summary_evidence(
            summary,
            gate_size=gate_size,
            promotion_active=promotion_active,
        )
        with file_lock(self._mutation):
            current_receipts = self._rollout_gate_receipts(
                plan_id, evidence_secret=evidence_secret
            )
            if (
                len(current_receipts) != 1
                or current_receipts[0]["receiptFingerprint"]
                != approval["receiptFingerprint"]
            ):
                raise LocalQueueError(
                    "arena_rollout_reconciliation_predecessor_invalid"
                )
            self._persist_rollout_summary(summary, plan=plan)
            core = {
                "schema": ROLLOUT_GATE_SCHEMA,
                "receiptId": f"{approval['gateId']}_{decision}",
                "rolloutId": approval["rolloutId"],
                "gateId": approval["gateId"],
                "gateSize": approval["gateSize"],
                "transition": decision,
                "arenaPlanId": approval["arenaPlanId"],
                "arenaPlanFingerprint": approval["arenaPlanFingerprint"],
                "predecessorReceiptFingerprint": approval[
                    "predecessorReceiptFingerprint"
                ],
                "previousReceiptFingerprint": approval["receiptFingerprint"],
                "creatorCounts": approval["creatorCounts"],
                "modelCounts": approval["modelCounts"],
                "capabilityCounts": approval["capabilityCounts"],
                "routerEvidence": approval["routerEvidence"],
                "modeConfirmation": approval["modeConfirmation"],
                "operatorIdentity": _required_text(
                    operator_identity, "operator_identity"
                ),
                "decidedAt": decided_at,
                "decision": decision,
                "reason": _required_text(reason, "rollout_reason"),
                "summaryEvidence": summary_evidence,
                "externalActivity": activity,
            }
            transition = self._append_rollout_receipt(
                core, evidence_secret=evidence_secret
            )
        return {**transition, "summary": summary}

    def approve_rollout_escalation(
        self,
        *,
        plan_id: str,
        operator_identity: str,
        decided_at: str,
        reason: str,
        benchmark_store: LocalModelBenchmarkStore,
        human_reviews: HumanMediaReviewStore,
        evidence_secret: str | None = None,
    ) -> dict[str, Any]:
        plan = self.load_plan(plan_id)
        receipts = self._rollout_gate_receipts(plan_id, evidence_secret=evidence_secret)
        if (
            len(receipts) != 2
            or receipts[0].get("transition") != "approved_to_run"
            or receipts[1].get("transition") != "terminal"
            or receipts[1].get("previousReceiptFingerprint")
            != receipts[0].get("receiptFingerprint")
        ):
            raise LocalQueueError("arena_rollout_escalation_predecessor_invalid")
        approval, terminal = receipts
        summary_evidence = terminal.get("summaryEvidence")
        if not isinstance(summary_evidence, dict):
            raise LocalQueueError("arena_rollout_escalation_summary_missing")
        summary = self._load_rollout_summary(
            str(summary_evidence["summaryFingerprint"]), plan=plan
        )
        gate_size = int(plan["expectedSampleCount"])
        if (
            self._rollout_summary_evidence(
                summary,
                gate_size=gate_size,
                promotion_active=True,
            )
            != summary_evidence
        ):
            raise LocalQueueError("arena_rollout_escalation_summary_drift")
        if not self._rollout_gate_passes(
            summary,
            gate_size=gate_size,
            promotion_active=True,
        ):
            raise LocalQueueError("arena_rollout_gate_pass_criteria_not_met")
        self._verify_rollout_router_snapshots(
            plan=plan,
            receipt=approval,
            benchmark_store=benchmark_store,
            human_reviews=human_reviews,
            observed_at=decided_at,
            evidence_secret=evidence_secret,
            require_active_promotion=True,
        )
        activity = self._rollout_external_activity(plan, summary=summary)
        core = {
            "schema": ROLLOUT_GATE_SCHEMA,
            "receiptId": f"{approval['gateId']}_approved_to_escalate",
            "rolloutId": approval["rolloutId"],
            "gateId": approval["gateId"],
            "gateSize": approval["gateSize"],
            "transition": "approved_to_escalate",
            "arenaPlanId": approval["arenaPlanId"],
            "arenaPlanFingerprint": approval["arenaPlanFingerprint"],
            "predecessorReceiptFingerprint": approval["predecessorReceiptFingerprint"],
            "previousReceiptFingerprint": terminal["receiptFingerprint"],
            "creatorCounts": approval["creatorCounts"],
            "modelCounts": approval["modelCounts"],
            "capabilityCounts": approval["capabilityCounts"],
            "routerEvidence": approval["routerEvidence"],
            "modeConfirmation": approval["modeConfirmation"],
            "operatorIdentity": _required_text(operator_identity, "operator_identity"),
            "decidedAt": decided_at,
            "decision": "approved_to_escalate",
            "reason": _required_text(reason, "rollout_reason"),
            "summaryEvidence": summary_evidence,
            "externalActivity": activity,
        }
        with file_lock(self._mutation):
            current_receipts = self._rollout_gate_receipts(
                plan_id, evidence_secret=evidence_secret
            )
            if (
                len(current_receipts) != 2
                or current_receipts[0]["receiptFingerprint"]
                != approval["receiptFingerprint"]
                or current_receipts[1]["receiptFingerprint"]
                != terminal["receiptFingerprint"]
            ):
                raise LocalQueueError("arena_rollout_escalation_predecessor_invalid")
            return self._append_rollout_receipt(core, evidence_secret=evidence_secret)

    def rollout_status(
        self, plan_id: str, *, evidence_secret: str | None = None
    ) -> dict[str, Any]:
        plan = self.load_plan(plan_id)
        receipts = self._rollout_gate_receipts(plan_id, evidence_secret=evidence_secret)
        return {
            "planId": plan_id,
            "planFingerprint": plan["planFingerprint"],
            "gateSize": plan["expectedSampleCount"],
            "state": receipts[-1]["transition"] if receipts else "proposed",
            "receipts": receipts,
        }

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
        if (
            plan.get("purpose") != "supervised_rollout"
            and status not in NON_ROLLOUT_RECORDED_TERMINAL_STATUSES
        ):
            raise ValueError("arena_terminal_status_invalid")
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
                        receipt.creator_identity_profile_id
                        != sample["identityProfileId"]
                        or receipt.creator_identity_profile_fingerprint
                        != sample["identityProfileFingerprint"]
                        or receipt.content_intent_id != sample["contentIntentId"]
                        or receipt.content_intent_fingerprint
                        != sample["contentIntentFingerprint"]
                    ):
                        blockers.append("benchmark_identity_intent_mismatch")
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
    source_path = sample.get("sourcePath")
    return LocalVideoRequest(
        model_id=str(sample["modelId"]),
        image_path=(Path(str(source_path)) if source_path is not None else None),
        prompt=str(sample["prompt"]),
        output_path=Path(str(sample["outputPath"])),
        duration_seconds=int(sample["durationSeconds"]),
        resolution=str(sample["resolution"]),
        seed=int(sample["seed"]),
        steps=(int(sample["steps"]) if sample.get("steps") is not None else None),
        negative_prompt=str(sample.get("negativePrompt") or DEFAULT_NEGATIVE_PROMPT),
        audio_mode=str(sample["audioMode"]),  # type: ignore[arg-type]
        audio_path=(
            Path(str(sample["audioPath"]))
            if sample.get("audioPath") is not None
            else None
        ),
        last_image_path=(
            Path(str(sample["lastImagePath"]))
            if sample.get("lastImagePath") is not None
            else None
        ),
        task=str(sample["taskKind"]),  # type: ignore[arg-type]
        lora_path=(
            Path(str(sample["loraPath"]))
            if sample.get("loraPath") is not None
            else None
        ),
        lora_strength=float(sample.get("loraStrength", 1.0)),
        source_video_path=(
            Path(str(sample["sourceVideoPath"]))
            if sample.get("sourceVideoPath") is not None
            else None
        ),
        retake_start_frame=(
            int(sample["retakeStartFrame"])
            if sample.get("retakeStartFrame") is not None
            else None
        ),
        retake_end_frame=(
            int(sample["retakeEndFrame"])
            if sample.get("retakeEndFrame") is not None
            else None
        ),
        extend_frames=(
            int(sample["extendFrames"])
            if sample.get("extendFrames") is not None
            else None
        ),
        extend_direction=str(sample.get("extendDirection") or "after"),  # type: ignore[arg-type]
        low_ram=sample.get("lowRam") is not False,
        tile_frames=int(sample.get("tileFrames", 1)),
        tile_spatial=int(sample.get("tileSpatial", 2)),
        commercial_use=sample.get("commercialUse") is not False,
        commercial_annual_revenue_usd=(
            int(sample["commercialAnnualRevenueUsd"])
            if sample.get("commercialAnnualRevenueUsd") is not None
            else None
        ),
        overlays_exist=sample.get("overlaysExist") is True,
        benchmark_recipe=dict(sample["benchmarkRecipe"]),
        analyzer_registry=dict(sample["analyzerRegistry"]),
        creator_identity_profile=dict(sample["creatorIdentityProfile"]),
        content_intent=dict(sample["contentIntent"]),
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
            runtime_binding=dict(sample["runtimeBinding"]),
            runtime_binding_fingerprint=str(sample["runtimeBindingFingerprint"]),
            license_policy=dict(sample["licensePolicy"]),
            license_policy_fingerprint=str(sample["licensePolicyFingerprint"]),
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
    runtime_binding: Mapping[str, Any],
    runtime_binding_fingerprint: str,
    license_policy: Mapping[str, Any],
    license_policy_fingerprint: str,
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
        "runtimeBinding": dict(runtime_binding),
        "runtimeBindingFingerprint": runtime_binding_fingerprint,
        "licensePolicy": dict(license_policy),
        "licensePolicyFingerprint": license_policy_fingerprint,
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
    identity_root: Path | None = None,
    benchmarks: LocalModelBenchmarkStore | None = None,
    human_reviews: HumanMediaReviewStore | None = None,
    evidence_secret: str | None = None,
) -> dict[str, Any]:
    """Run one exact planned sample through the normal local queue path."""

    plan = store.load_plan(plan_id)
    if plan["purpose"] == "supervised_rollout":
        if benchmarks is None or human_reviews is None:
            raise LocalQueueError("arena_rollout_execution_context_required")
        store.require_rollout_approved_to_run(
            plan_id,
            benchmark_store=benchmarks,
            human_reviews=human_reviews,
            sample_id=sample_id,
            evidence_secret=evidence_secret,
        )
    sample = _sample(plan, sample_id)
    _require_promotion_identity_ready(
        purpose=str(plan["purpose"]),
        bindings=_plan_identity_bindings(plan),
        identity_root=identity_root,
    )
    if not isinstance(sample.get("taskParameterMaterial"), dict) or not isinstance(
        sample.get("taskParameterFingerprint"), str
    ):
        raise LocalQueueError("arena_task_parameter_evidence_required_for_execution")
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


def _trusted_motion_qc_request(
    sample: Mapping[str, Any],
    *,
    output: Path,
    output_sha256: str,
    produced_at: str,
    analyzer_registry: Mapping[str, Any],
    human_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the only production-trusted ContentForge motion-QC request.

    ContentForge intentionally reruns its canonical analysis from immutable
    media/source inputs. Passing the earlier diagnostic analysis back across
    this boundary would be caller-supplied evidence and must remain impossible.
    """

    source = _qc_source_binding(sample)
    return {
        "mediaPath": str(output),
        "mediaSha256": output_sha256,
        "sourcePath": source["path"],
        "sourceSha256": source["sha256"],
        "producedAt": produced_at,
        "overlaysExist": sample["overlaysExist"],
        "analyzerRegistry": dict(analyzer_registry),
        "humanReview": dict(human_review),
        "options": _motion_qc_options(sample),
    }


def _qc_source_binding(sample: Mapping[str, Any]) -> dict[str, str]:
    """Resolve immutable source provenance without adding an execution input."""

    if sample.get("taskKind") == "text_to_video":
        prompt_source = sample.get("promptSource")
        if not isinstance(prompt_source, dict):
            raise LocalQueueError("arena_text_task_prompt_source_missing")
        path = Path(str(prompt_source.get("path") or "")).expanduser().resolve()
        expected = str(sample.get("sourceSha256") or "")
        if (
            set(prompt_source) != {"path", "sha256"}
            or prompt_source.get("sha256") != expected
            or not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != expected
        ):
            raise LocalQueueError(
                "arena_text_task_prompt_source_missing_or_substituted"
            )
        return {"path": str(path), "sha256": expected}
    path = Path(str(sample.get("sourcePath") or "")).expanduser().resolve()
    expected = str(sample.get("sourceSha256") or "")
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
        raise LocalQueueError("arena_source_missing_or_substituted")
    return {"path": str(path), "sha256": expected}


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
    _require_promotion_identity_ready(
        purpose=str(plan["purpose"]),
        bindings=_plan_identity_bindings(plan),
        identity_root=identity_root,
    )
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
    source = _qc_source_binding(sample)
    analysis = _run_contentforge(
        "analyze-media",
        {
            "mediaPath": str(output),
            "mediaSha256": output_sha,
            "sourcePath": source["path"],
            "sourceSha256": source["sha256"],
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
        creator_identity_profile=dict(sample["creatorIdentityProfile"]),
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
        _trusted_motion_qc_request(
            sample,
            output=output,
            output_sha256=output_sha,
            produced_at=produced_at,
            analyzer_registry=registry,
            human_review=review.as_dict(),
        ),
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


def build_arena_record_bundle(
    *,
    reviewed_identity_facts_path: Path,
    source_path: Path | None,
    typed_inputs: Sequence[tuple[str, Path]] = (),
    reviewed_source_paths: Sequence[Path] = (),
    task_kind: str = "image_to_video",
    prompt: str | None = None,
    goal: str,
    content_surface: str,
    media_kind: str,
    style_lanes: Sequence[str],
    concept_tags: Sequence[str],
    produced_at: str,
    output_root: Path,
) -> dict[str, Any]:
    """Build exact Arena records from reviewed facts and authorized source media.

    ``source_path`` and ``typed_inputs`` describe one exact execution cell.
    ``reviewed_source_paths`` expands only the immutable ContentIntent
    authorization set so matched Arena cells may share one intent. Each
    BenchmarkRecipe remains bound to the exact inputs consumed by its cell.
    Text-to-video has no typed media inputs; its immutable source descriptor is
    the canonical ``taskKind`` + normalized ``prompt`` JSON whose file digest is
    the same prompt-task fingerprint used by Arena plans.
    """

    facts_path = reviewed_identity_facts_path.expanduser().resolve()
    source = source_path.expanduser().resolve() if source_path is not None else None
    if not facts_path.is_file() or facts_path.is_symlink():
        raise LocalQueueError("arena_reviewed_identity_facts_missing_or_unsafe")
    destination = output_root.expanduser().resolve()
    reviewed_sources = [path.expanduser().resolve() for path in reviewed_source_paths]
    for reviewed_source in reviewed_sources:
        if not reviewed_source.is_file() or reviewed_source.is_symlink():
            raise LocalQueueError("arena_record_reviewed_source_missing_or_unsafe")

    role_aliases = {
        "image": "image",
        "audio": "audio",
        "last-image": "last_image",
        "last_image": "last_image",
        "source-video": "source_video",
        "source_video": "source_video",
    }
    role_paths: dict[str, Path] = {}
    if source is not None:
        role_paths["image"] = source
    for input_kind, input_path in typed_inputs:
        role = role_aliases.get(input_kind)
        if role is None:
            raise ValueError(f"arena_record_input_kind_invalid:{input_kind}")
        resolved_input = input_path.expanduser().resolve()
        existing_role_path = role_paths.get(role)
        if existing_role_path is not None and existing_role_path != resolved_input:
            raise LocalQueueError(f"arena_record_input_role_duplicate:{role}")
        role_paths[role] = resolved_input
    for input_path in role_paths.values():
        if not input_path.is_file() or input_path.is_symlink():
            raise LocalQueueError("arena_record_source_missing_or_unsafe")

    normalized_prompt: str | None = None
    prompt_source_material: dict[str, str] | None = None
    prompt_source_path: Path | None = None
    prompt_task_fingerprint: str | None = None
    authorized_source_fingerprints: tuple[str, ...]
    if task_kind == "text_to_video":
        if role_paths or reviewed_sources:
            raise LocalQueueError("arena_record_text_task_media_forbidden")
        normalized_prompt = " ".join(_required_text(prompt, "prompt").split())
        prompt_source_material = {
            "taskKind": "text_to_video",
            "prompt": normalized_prompt,
        }
        prompt_task_fingerprint = fingerprint(prompt_source_material)
        prompt_source_path = (
            destination / "prompt_sources" / f"{prompt_task_fingerprint}.json"
        )
        canonical_bindings: tuple[dict[str, str], ...] = ()
        input_assets: list[dict[str, str]] = []
        source_sha: str | None = prompt_task_fingerprint
        authorized_source_fingerprints = (prompt_task_fingerprint,)
    else:
        role_hashes = {role: sha256_file(path) for role, path in role_paths.items()}
        try:
            canonical_bindings = canonical_task_input_bindings(
                task_kind,
                image_sha256=role_hashes.get("image"),
                audio_sha256=role_hashes.get("audio"),
                last_image_sha256=role_hashes.get("last_image"),
                source_video_sha256=role_hashes.get("source_video"),
            )
        except ValueError as exc:
            raise LocalQueueError(f"arena_record_{exc}") from exc
        input_assets = [
            {
                "kind": binding["role"].replace("_", "-"),
                "path": str(role_paths[binding["role"]]),
                "sha256": binding["sha256"],
            }
            for binding in canonical_bindings
        ]
        source_sha = (
            str(canonical_bindings[0]["sha256"]) if canonical_bindings else None
        )
        authorized_source_fingerprints = tuple(
            sorted(
                {
                    *(binding["sha256"] for binding in canonical_bindings),
                    *(sha256_file(path) for path in reviewed_sources),
                }
            )
        )
    facts = _read_json(facts_path)
    expected_fact_keys = {
        "schema",
        "creatorKey",
        "displayName",
        "modelProfile",
        "identityReferences",
        "reviewedBy",
        "reviewedAt",
    }
    if set(facts) != expected_fact_keys or facts.get("schema") != (
        "reel_factory.reviewed_creator_identity_facts.v1"
    ):
        raise ValueError("arena_reviewed_identity_facts_schema_invalid")
    creator_key = _required_text(facts.get("creatorKey"), "creator_key").lower()
    if creator_key not in CREATORS:
        raise ValueError(f"arena_creator_unsupported:{creator_key}")
    reviewed_by = _required_text(facts.get("reviewedBy"), "reviewed_by")
    reviewed_at = _required_text(facts.get("reviewedAt"), "reviewed_at")
    reviewed_timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    produced_timestamp = datetime.fromisoformat(produced_at.replace("Z", "+00:00"))
    if reviewed_timestamp.tzinfo is None or produced_timestamp.tzinfo is None:
        raise ValueError("arena_record_timestamp_timezone_required")
    if reviewed_timestamp > produced_timestamp or produced_timestamp > datetime.now(
        UTC
    ):
        raise ValueError("arena_record_timestamp_order_invalid")
    raw_references = facts.get("identityReferences")
    if not isinstance(raw_references, list) or not raw_references:
        raise ValueError("arena_reviewed_identity_references_missing")
    references = tuple(
        IdentityReferenceV1.from_dict(dict(item))
        for item in raw_references
        if isinstance(item, dict)
    )
    if len(references) != len(raw_references):
        raise ValueError("arena_reviewed_identity_reference_invalid")
    facts_sha = sha256_file(facts_path)
    profile_material = {
        "factsSha256": facts_sha,
        "creatorKey": creator_key,
        "reviewedBy": reviewed_by,
        "reviewedAt": reviewed_at,
    }
    profile = CreatorIdentityProfileV1(
        profile_id=f"creator_profile_{creator_key}_{fingerprint(profile_material)[:24]}",
        creator_key=creator_key,
        display_name=_required_text(facts.get("displayName"), "display_name"),
        model_profile=_required_text(facts.get("modelProfile"), "model_profile"),
        identity_references=references,
        provenance=ProvenanceV1(
            producer="reel_factory.local_model_arena.record_builder",
            produced_at=produced_at,
            source_references=(
                SourceReferenceV1(
                    record_id=f"reviewed_identity_facts:{facts_sha[:24]}",
                    fingerprint=facts_sha,
                ),
            ),
        ),
    ).to_dict()
    profile_fingerprint = fingerprint(profile)
    normalized_lanes = tuple(
        dict.fromkeys(_required_text(value, "style_lane") for value in style_lanes)
    )
    normalized_tags = tuple(
        dict.fromkeys(_required_text(value, "concept_tag") for value in concept_tags)
    )
    intent_material = {
        "creatorIdentityProfileFingerprint": profile_fingerprint,
        "authorizedSourceFingerprints": authorized_source_fingerprints,
        "goal": _required_text(goal, "goal"),
        "contentSurface": content_surface,
        "mediaKind": media_kind,
        "styleLanes": normalized_lanes,
        "conceptTags": normalized_tags,
    }
    intent = ContentIntentV1(
        intent_id=f"content_intent_{fingerprint(intent_material)[:24]}",
        creator_identity_profile_id=str(profile["profileId"]),
        goal=str(intent_material["goal"]),
        content_surface=content_surface,  # type: ignore[arg-type]
        media_kind=media_kind,  # type: ignore[arg-type]
        style_lanes=normalized_lanes,
        concept_tags=normalized_tags,
        source_asset_fingerprints=authorized_source_fingerprints,
        provenance=ProvenanceV1(
            producer="reel_factory.local_model_arena.record_builder",
            produced_at=produced_at,
            source_references=(
                SourceReferenceV1(
                    record_id=str(profile["profileId"]),
                    fingerprint=profile_fingerprint,
                ),
                *(
                    SourceReferenceV1(
                        record_id=f"source_asset:{value[:24]}",
                        fingerprint=value,
                    )
                    for value in authorized_source_fingerprints
                ),
            ),
        ),
    ).to_dict()
    intent_fingerprint = fingerprint(intent)
    profile_path = (
        destination / "creator_identity_profiles" / (f"{profile_fingerprint}.json")
    )
    intent_path = destination / "content_intents" / f"{intent_fingerprint}.json"
    if (
        prompt_source_path is not None
        and prompt_source_material is not None
        and prompt_task_fingerprint is not None
    ):
        _write_exact_json(prompt_source_path, prompt_source_material)
        if sha256_file(prompt_source_path) != prompt_task_fingerprint:
            raise LocalQueueError("arena_record_prompt_source_hash_mismatch")
        prompt_source_path.chmod(0o444)
    _write_exact_json(profile_path, profile)
    _write_exact_json(intent_path, intent)
    return {
        "creatorIdentityProfile": profile,
        "identityProfileId": profile["profileId"],
        "identityProfileFingerprint": profile_fingerprint,
        "contentIntent": intent,
        "contentIntentId": intent["intentId"],
        "contentIntentFingerprint": intent_fingerprint,
        "taskKind": task_kind,
        "sourcePath": str(source) if source is not None else None,
        "sourceSha256": source_sha,
        "promptTaskFingerprint": prompt_task_fingerprint,
        "promptSource": (
            {
                "path": str(prompt_source_path),
                "sha256": prompt_task_fingerprint,
            }
            if prompt_source_path is not None and prompt_task_fingerprint is not None
            else None
        ),
        "inputAssets": input_assets,
        "recordPaths": {
            "creatorIdentityProfile": str(profile_path),
            "contentIntent": str(intent_path),
            **(
                {"promptSource": str(prompt_source_path)}
                if prompt_source_path is not None
                else {}
            ),
        },
        "providerCalls": 0,
        "productionWrites": 0,
    }


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
    plan_command.add_argument(
        "--identity-root",
        type=Path,
        help="required for promotion-eligible plans; contains signed v4 reference sets",
    )
    records_command = sub.add_parser("build-records")
    records_command.add_argument("--reviewed-identity-facts", type=Path, required=True)
    records_command.add_argument("--source", type=Path)
    records_command.add_argument(
        "--reviewed-source",
        action="append",
        type=Path,
        default=[],
        help=(
            "Repeatable reviewed source authorized by the shared ContentIntent; "
            "does not add an input to the exact BenchmarkRecipe"
        ),
    )
    records_command.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="KIND=PATH",
        help="Repeatable typed input: image, audio, last-image, or source-video",
    )
    records_command.add_argument(
        "--task-kind",
        choices=[
            "text_to_video",
            "image_to_video",
            "audio_image_to_video",
            "keyframe_interpolation",
            "video_retake",
            "video_extend",
        ],
        default="image_to_video",
    )
    records_command.add_argument(
        "--prompt",
        help=(
            "Exact prompt required for text_to_video; its canonical task/prompt "
            "descriptor is the zero-media source identity"
        ),
    )
    records_command.add_argument("--goal", required=True)
    records_command.add_argument(
        "--content-surface",
        choices=["reel", "story", "feed_post", "thread"],
        required=True,
    )
    records_command.add_argument(
        "--media-kind", choices=["image", "video", "carousel"], required=True
    )
    records_command.add_argument("--style-lane", action="append", required=True)
    records_command.add_argument("--concept-tag", action="append", default=[])
    records_command.add_argument("--produced-at", required=True)
    records_command.add_argument("--output-root", type=Path, required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--plan-id", required=True)
    generate.add_argument("--sample-id", required=True)
    generate.add_argument("--mode", choices=["local_wan"], required=True)
    generate.add_argument(
        "--identity-root",
        type=Path,
        help="required when generating a promotion-eligible Arena plan",
    )
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
    rollout_approve = sub.add_parser("rollout-approve")
    rollout_approve.add_argument("--plan-id", required=True)
    rollout_approve.add_argument("--rollout-id", required=True)
    rollout_approve.add_argument("--operator-identity", required=True)
    rollout_approve.add_argument("--decided-at", required=True)
    rollout_approve.add_argument("--reason", required=True)
    rollout_approve.add_argument("--mode-confirmation", required=True)
    rollout_approve.add_argument(
        "--router-evidence",
        type=Path,
        action="append",
        required=True,
        help="Repeat once per immutable Router evidence bundle JSON.",
    )
    rollout_approve.add_argument("--predecessor-receipt-fingerprint")
    rollout_sample_terminal = sub.add_parser("rollout-sample-terminal")
    rollout_sample_terminal.add_argument("--plan-id", required=True)
    rollout_sample_terminal.add_argument("--sample-id", required=True)
    rollout_sample_terminal.add_argument(
        "--status",
        choices=sorted(TERMINAL_STATUSES - {"succeeded"}),
        required=True,
    )
    rollout_sample_terminal.add_argument("--reason", required=True)
    rollout_reconcile = sub.add_parser("rollout-reconcile")
    rollout_reconcile.add_argument("--plan-id", required=True)
    rollout_reconcile.add_argument(
        "--decision", choices=["terminal", "held"], required=True
    )
    rollout_reconcile.add_argument("--operator-identity", required=True)
    rollout_reconcile.add_argument("--decided-at", required=True)
    rollout_reconcile.add_argument("--reason", required=True)
    rollout_escalate = sub.add_parser("rollout-escalate")
    rollout_escalate.add_argument("--plan-id", required=True)
    rollout_escalate.add_argument("--operator-identity", required=True)
    rollout_escalate.add_argument("--decided-at", required=True)
    rollout_escalate.add_argument("--reason", required=True)
    rollout_status = sub.add_parser("rollout-status")
    rollout_status.add_argument("--plan-id", required=True)
    args = parser.parse_args(argv)
    store = LocalModelArenaStore(args.root)
    try:
        if args.command == "build-records":
            typed_inputs: list[tuple[str, Path]] = []
            for raw_input in args.input:
                input_kind, separator, raw_path = str(raw_input).partition("=")
                if not separator or not raw_path.strip():
                    raise ValueError("arena_record_input_must_be_kind_equals_path")
                typed_inputs.append((input_kind.strip(), Path(raw_path.strip())))
            result = build_arena_record_bundle(
                reviewed_identity_facts_path=args.reviewed_identity_facts,
                source_path=args.source,
                typed_inputs=typed_inputs,
                reviewed_source_paths=args.reviewed_source,
                task_kind=args.task_kind,
                prompt=args.prompt,
                goal=args.goal,
                content_surface=args.content_surface,
                media_kind=args.media_kind,
                style_lanes=args.style_lane,
                concept_tags=args.concept_tag,
                produced_at=args.produced_at,
                output_root=args.output_root,
            )
        elif args.command == "plan":
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
                identity_root=args.identity_root,
            )
            result = {
                "plan": plan,
                "path": str(store.persist_plan(plan)),
            }
        elif args.command == "generate":
            benchmark_store = default_local_model_benchmark_store(args.root)
            result = execute_arena_sample_generation(
                store,
                plan_id=args.plan_id,
                sample_id=args.sample_id,
                dry_run=args.dry_run,
                identity_root=args.identity_root,
                benchmarks=benchmark_store,
                human_reviews=HumanMediaReviewStore(args.root),
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
        elif args.command == "rollout-approve":
            result = store.approve_rollout_gate(
                plan_id=args.plan_id,
                rollout_id=args.rollout_id,
                operator_identity=args.operator_identity,
                decided_at=args.decided_at,
                reason=args.reason,
                mode_confirmation=args.mode_confirmation,
                router_evidence_bundles=[
                    _read_json(path) for path in args.router_evidence
                ],
                benchmark_store=default_local_model_benchmark_store(args.root),
                human_reviews=HumanMediaReviewStore(args.root),
                predecessor_receipt_fingerprint=(args.predecessor_receipt_fingerprint),
            )
        elif args.command == "rollout-sample-terminal":
            result = store.record_terminal(
                plan_id=args.plan_id,
                sample_id=args.sample_id,
                status=args.status,
                reason=args.reason,
            )
        elif args.command == "rollout-reconcile":
            result = store.record_rollout_reconciliation(
                plan_id=args.plan_id,
                decision=args.decision,
                operator_identity=args.operator_identity,
                decided_at=args.decided_at,
                reason=args.reason,
                queue=default_local_generation_queue(),
                benchmark_store=default_local_model_benchmark_store(args.root),
                human_reviews=HumanMediaReviewStore(args.root),
            )
        elif args.command == "rollout-escalate":
            result = store.approve_rollout_escalation(
                plan_id=args.plan_id,
                operator_identity=args.operator_identity,
                decided_at=args.decided_at,
                reason=args.reason,
                benchmark_store=default_local_model_benchmark_store(args.root),
                human_reviews=HumanMediaReviewStore(args.root),
            )
        elif args.command == "rollout-status":
            result = store.rollout_status(args.plan_id)
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
