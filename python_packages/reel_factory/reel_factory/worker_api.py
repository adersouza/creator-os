"""Stable in-process APIs exposed to the Campaign Factory control plane."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.task_inputs import (
    canonical_task_input_bindings,
    validate_task_input_binding_records,
)
from creator_os_core.task_parameters import (
    DEFAULT_LOCAL_VIDEO_NEGATIVE_PROMPT,
    benchmark_task_parameter_fingerprint,
    task_parameter_fingerprint,
)

from .audio_intent import read_audio_intent
from .caption_bank import CaptionBankStore, load_or_build_caption_bank_store
from .human_media_review import HumanMediaReviewStore
from .local_generation_queue import (
    _macos_available_memory_bytes,
    default_local_generation_queue,
    fingerprint,
    hardware_identity,
)
from .local_model_arena import LocalModelArenaStore
from .local_model_benchmark import default_local_model_benchmark_store
from .local_model_router import RouterRequest, route_local_model
from .local_video import LocalVideoRequest, local_video_task_parameter_material
from .local_wan_prompt_expansion import (
    expand_wan_i2v_prompt,
    validate_wan_prompt_expansion,
)
from .reference_video_remix import (
    build_reference_video_remix_plan,
    gemini_motion_analysis_instruction,
)
from .video_provider_models import video_model


def expand_local_wan_i2v_prompt(
    *, image_path: Path, original_prompt: str
) -> dict[str, Any]:
    """Return one exact provider-free Qwen-VL expansion receipt."""

    return expand_wan_i2v_prompt(
        image_path=image_path,
        original_prompt=original_prompt,
    )


def validate_local_wan_i2v_prompt_expansion(
    receipt: Mapping[str, Any],
    *,
    image_path: Path,
    expanded_prompt: str,
) -> dict[str, Any]:
    """Revalidate the exact expansion capability and source binding."""

    return validate_wan_prompt_expansion(
        receipt,
        image_path=image_path,
        expanded_prompt=expanded_prompt,
    )


def admit_local_motion(
    *,
    arena_summary: Mapping[str, Any],
    evidence_records: Mapping[str, Any],
    input_fingerprints: Sequence[str],
    input_bindings: Sequence[Mapping[str, object]],
    creator_id: str,
    identity_profile_id: str,
    identity_profile_fingerprint: str,
    content_intent_id: str,
    content_intent_fingerprint: str,
    task_kind: str,
    prompt: str = "A person moves naturally within the original composition",
    duration_seconds: int | None = None,
    resolution: str | None = None,
    seed: int = 42,
    steps: int | None = None,
    audio_mode: str = "none",
    negative_prompt: str = DEFAULT_LOCAL_VIDEO_NEGATIVE_PROMPT,
    lora_path: Path | None = None,
    lora_strength: float = 1.0,
    source_video_path: Path | None = None,
    retake_start_frame: int | None = None,
    retake_end_frame: int | None = None,
    extend_frames: int | None = None,
    extend_direction: str = "after",
    low_ram: bool = True,
    tile_frames: int = 1,
    tile_spatial: int = 2,
    override_model_id: str | None = None,
    override_operator: str | None = None,
    override_reason: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Return the sole canonical admission for ordinary local motion.

    Campaign Factory owns campaign/input compatibility and passes its compiled
    evidence records here. Reel Factory owns machine resource admission and all
    queue, Arena, benchmark, human-review, model, and Router internals.
    """

    summary = dict(arena_summary)
    records = dict(evidence_records)
    inputs = [str(value) for value in input_fingerprints]
    if set(records) != {
        "creatorIdentityProfile",
        "contentIntent",
        "executionPolicy",
        "benchmarkRecipe",
        "analyzerRegistry",
    }:
        raise ValueError("local_motion_evidence_record_set_invalid")
    if any(not _is_sha256(value) for value in inputs):
        raise ValueError("local_motion_input_fingerprints_invalid")
    canonical_inputs = validate_task_input_binding_records(task_kind, input_bindings)
    if [binding["sha256"] for binding in canonical_inputs] != inputs:
        raise ValueError("local_motion_input_binding_fingerprint_mismatch")
    identity = records.get("creatorIdentityProfile")
    intent = records.get("contentIntent")
    recipe = records.get("benchmarkRecipe")
    registry = records.get("analyzerRegistry")
    if not isinstance(identity, Mapping):
        raise ValueError("local_motion_evidence_record_invalid")
    if not isinstance(intent, Mapping):
        raise ValueError("local_motion_evidence_record_invalid")
    if not isinstance(recipe, Mapping):
        raise ValueError("local_motion_evidence_record_invalid")
    if not isinstance(registry, Mapping):
        raise ValueError("local_motion_evidence_record_invalid")
    normalized_creator = str(creator_id or "").strip().lower()
    if normalized_creator not in {"stacey", "larissa", "lola"}:
        raise ValueError("local_motion_creator_unsupported")
    if (
        str(identity.get("creatorKey") or "").strip().lower() != normalized_creator
        or identity.get("profileId") != identity_profile_id
        or fingerprint(identity) != identity_profile_fingerprint
        or intent.get("intentId") != content_intent_id
        or fingerprint(intent) != content_intent_fingerprint
        or not set(inputs).issubset(set(intent.get("sourceAssetFingerprints") or []))
        or list(recipe.get("inputFingerprints") or []) != inputs
        or recipe.get("taskKind") != task_kind
    ):
        raise ValueError("local_motion_compiled_evidence_binding_mismatch")

    override_selected_model, operator, reason = _validated_override(
        model_id=override_model_id,
        operator=override_operator,
        reason=override_reason,
    )
    timestamp = observed_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("local_motion_observed_at_timezone_required")

    queue = default_local_generation_queue()
    current_available_memory = _macos_available_memory_bytes()
    if current_available_memory is None:
        raise RuntimeError("local_motion_available_memory_measurement_unavailable")
    usable_memory = max(0, current_available_memory - queue.memory_reserve_bytes)
    routed_available_memory = min(queue.resource_limit_bytes, usable_memory)
    if routed_available_memory <= 0:
        raise RuntimeError("local_motion_usable_memory_unavailable")
    resource_snapshot = {
        "schema": "campaign_factory.local_motion_resource_snapshot.v1",
        "observedAt": timestamp,
        "measurement": "reel_factory.local_generation_queue.vm_stat.v1",
        "currentAvailableMemoryBytes": current_available_memory,
        "memoryReserveBytes": queue.memory_reserve_bytes,
        "usableMemoryBytes": usable_memory,
        "configuredResourceLimitBytes": queue.resource_limit_bytes,
        "routerAvailableMemoryBytes": routed_available_memory,
    }

    benchmark_store = default_local_model_benchmark_store()
    arena_store = LocalModelArenaStore(benchmark_store.root)
    plan_id = str(summary.get("planId") or "")
    if not plan_id:
        raise ValueError("local_motion_arena_plan_id_missing")
    human_reviews = HumanMediaReviewStore(benchmark_store.root)
    arena_plan = arena_store.load_plan(plan_id)
    review_packet = arena_store.load_review_packet(plan_id)
    decision = route_local_model(
        RouterRequest(
            creator_id=normalized_creator,
            identity_profile_id=identity_profile_id,
            identity_profile_fingerprint=identity_profile_fingerprint,
            content_intent_id=content_intent_id,
            content_intent_fingerprint=content_intent_fingerprint,
            task_kind=task_kind,
            capability_cohort=_exact_capability_cohort(
                summary=summary,
                creator_id=normalized_creator,
                identity_profile_id=identity_profile_id,
                identity_profile_fingerprint=identity_profile_fingerprint,
                content_intent_id=content_intent_id,
                content_intent_fingerprint=content_intent_fingerprint,
                task_kind=task_kind,
            ),
            available_memory_bytes=routed_available_memory,
            observed_at=timestamp,
            override_model_id=override_selected_model,
            override_operator=operator,
            override_reason=reason,
        ),
        arena_plan=arena_plan,
        arena_summary=summary,
        benchmark_store=benchmark_store,
        human_review_store=human_reviews,
        review_packet=review_packet,
        unblinding_receipt=arena_store.load_unblinding_receipt(
            plan_id, human_reviews=human_reviews
        ),
    )
    winning = decision.get("winningEvidence")
    approval = (
        winning.get("promotionApproval") if isinstance(winning, Mapping) else None
    )
    current_hardware = hardware_identity()
    if not isinstance(approval, Mapping) or approval.get(
        "hardwareFingerprint"
    ) != current_hardware.get("fingerprint"):
        raise ValueError("local_motion_promotion_hardware_mismatch")
    promoted_samples = _promoted_samples(
        arena_plan=arena_plan,
        router_decision=decision,
        task_kind=task_kind,
    )
    promotion_input_cohort = _promotion_input_cohort(promoted_samples)
    current_input_bindings = list(canonical_inputs)
    if current_input_bindings not in promotion_input_cohort:
        raise ValueError("local_motion_input_not_in_promoted_cohort")
    selected_model_id = str(decision.get("selectedModelId") or "")
    selected_model_spec = video_model(selected_model_id)
    matched_parameter_materials: dict[str, dict[str, Any]] = {}
    for sample in promoted_samples:
        sample_bindings = _sample_input_bindings(sample)
        if sample_bindings != current_input_bindings:
            continue
        stored_material = sample.get("taskParameterMaterial")
        stored_fingerprint = sample.get("taskParameterFingerprint")
        if not isinstance(stored_material, dict) or not isinstance(
            stored_fingerprint, str
        ):
            raise ValueError("local_motion_promoted_parameter_evidence_missing")
        policy = stored_material.get("policyContext")
        if not isinstance(policy, Mapping):
            raise ValueError("local_motion_promoted_parameter_evidence_invalid")
        current_request = LocalVideoRequest(
            model_id=selected_model_id,
            image_path=None,
            prompt=prompt,
            output_path=Path("/creator-os/admission/not-executed.mp4"),
            duration_seconds=(
                selected_model_spec.default_duration
                if duration_seconds is None
                else duration_seconds
            ),
            resolution=(
                selected_model_spec.default_resolution
                if resolution is None
                else resolution
            ),
            seed=seed,
            steps=steps,
            negative_prompt=negative_prompt,
            audio_mode=audio_mode,  # type: ignore[arg-type]
            task=task_kind,  # type: ignore[arg-type]
            lora_path=lora_path,
            lora_strength=lora_strength,
            source_video_path=source_video_path,
            retake_start_frame=retake_start_frame,
            retake_end_frame=retake_end_frame,
            extend_frames=extend_frames,
            extend_direction=extend_direction,  # type: ignore[arg-type]
            low_ram=low_ram,
            tile_frames=tile_frames,
            tile_spatial=tile_spatial,
            commercial_use=policy.get("commercialUse") is not False,
            commercial_annual_revenue_usd=(
                int(policy["commercialAnnualRevenueUsd"])
                if policy.get("commercialAnnualRevenueUsd") is not None
                else None
            ),
            overlays_exist=policy.get("overlaysExist") is True,
        )
        current_material = local_video_task_parameter_material(
            current_request,
            runtime_binding=(
                winning.get("runtimeBinding") if isinstance(winning, Mapping) else None
            ),
        )
        current_fingerprint = task_parameter_fingerprint(current_material)
        if (
            current_material == stored_material
            and current_fingerprint == stored_fingerprint
        ):
            matched_parameter_materials[current_fingerprint] = current_material
    if len(matched_parameter_materials) != 1:
        raise ValueError("local_motion_task_parameter_mismatch")
    parameter_fingerprint, parameter_material = next(
        iter(matched_parameter_materials.items())
    )
    if recipe.get("parameterFingerprint") != benchmark_task_parameter_fingerprint(
        parameter_material
    ):
        raise ValueError("local_motion_benchmark_parameter_mismatch")
    resource_snapshot["hardware"] = current_hardware
    summary_binding = {
        "summaryId": summary.get("summaryId"),
        "summaryFingerprint": summary.get("summaryFingerprint"),
        "planId": summary.get("planId"),
        "planFingerprint": summary.get("planFingerprint"),
        "purpose": summary.get("purpose"),
    }
    core = {
        "schema": "campaign_factory.local_motion_admission.v1",
        "routerDecision": decision,
        "arenaSummary": summary_binding,
        "evidenceRecords": records,
        "inputFingerprints": inputs,
        "inputBindings": current_input_bindings,
        "promotionInputCohort": promotion_input_cohort,
        "taskParameterMaterial": parameter_material,
        "taskParameterFingerprint": parameter_fingerprint,
        "resourceSnapshot": resource_snapshot,
    }
    return {**core, "admissionFingerprint": fingerprint(core)}


def _promoted_samples(
    *,
    arena_plan: Mapping[str, Any],
    router_decision: Mapping[str, Any],
    task_kind: str,
) -> list[Mapping[str, Any]]:
    winning = router_decision.get("winningEvidence")
    if not isinstance(winning, Mapping):
        raise ValueError("local_motion_winning_evidence_missing")
    valid_ids = winning.get("validArenaSampleIds")
    selected_model_id = str(router_decision.get("selectedModelId") or "")
    if (
        not isinstance(valid_ids, list)
        or not valid_ids
        or any(not str(value or "").strip() for value in valid_ids)
        or len(valid_ids) != len(set(str(value) for value in valid_ids))
        or not selected_model_id
    ):
        raise ValueError("local_motion_promoted_sample_identity_invalid")
    samples = {
        str(sample.get("sampleId") or ""): sample
        for sample in arena_plan.get("samples", [])
        if isinstance(sample, Mapping)
    }
    promoted: list[Mapping[str, Any]] = []
    for sample_id in valid_ids:
        sample = samples.get(str(sample_id))
        if (
            sample is None
            or sample.get("modelId") != selected_model_id
            or sample.get("taskKind") != task_kind
        ):
            raise ValueError("local_motion_promoted_sample_binding_invalid")
        _sample_input_bindings(sample)
        promoted.append(sample)
    return promoted


def _sample_input_bindings(sample: Mapping[str, Any]) -> list[dict[str, str]]:
    return list(
        canonical_task_input_bindings(
            str(sample.get("taskKind") or ""),
            image_sha256=(
                str(sample["sourceSha256"])
                if sample.get("sourcePath") is not None
                else None
            ),
            audio_sha256=(
                str(sample["audioSha256"])
                if sample.get("audioSha256") is not None
                else None
            ),
            last_image_sha256=(
                str(sample["lastImageSha256"])
                if sample.get("lastImageSha256") is not None
                else None
            ),
            source_video_sha256=(
                str(sample["sourceVideoSha256"])
                if sample.get("sourceVideoSha256") is not None
                else None
            ),
        )
    )


def _promotion_input_cohort(
    promoted_samples: Sequence[Mapping[str, Any]],
) -> list[list[dict[str, str]]]:
    cohorts: dict[str, list[dict[str, str]]] = {}
    for sample in promoted_samples:
        bindings = _sample_input_bindings(sample)
        cohorts[fingerprint({"inputs": bindings})] = bindings
    if not cohorts:
        raise ValueError("local_motion_promoted_input_cohort_missing")
    return [cohorts[key] for key in sorted(cohorts)]


def _exact_capability_cohort(
    *,
    summary: Mapping[str, Any],
    creator_id: str,
    identity_profile_id: str,
    identity_profile_fingerprint: str,
    content_intent_id: str,
    content_intent_fingerprint: str,
    task_kind: str,
) -> str:
    cohorts = {
        str(sample.get("capabilityCohort") or "").strip()
        for sample in summary.get("samples", [])
        if isinstance(sample, Mapping)
        and str(sample.get("creatorId") or "").lower() == creator_id
        and sample.get("identityProfileId") == identity_profile_id
        and sample.get("identityProfileFingerprint") == identity_profile_fingerprint
        and sample.get("contentIntentId") == content_intent_id
        and sample.get("contentIntentFingerprint") == content_intent_fingerprint
        and sample.get("taskKind") == task_kind
        and str(sample.get("capabilityCohort") or "").strip()
    }
    if len(cohorts) != 1:
        raise ValueError("local_motion_arena_capability_cohort_not_exactly_one")
    return next(iter(cohorts))


def _validated_override(
    *, model_id: str | None, operator: str | None, reason: str | None
) -> tuple[str | None, str | None, str | None]:
    values = (model_id, operator, reason)
    if any(value is not None for value in values) and not all(
        value is not None and str(value).strip() for value in values
    ):
        raise ValueError("local_motion_router_override_evidence_must_be_complete")
    if model_id is None:
        return None, None, None
    normalized_reason = " ".join(str(reason).split())
    words = [
        word
        for word in normalized_reason.split(" ")
        if any(char.isalnum() for char in word)
    ]
    if len(normalized_reason) < 20 or len(words) < 3:
        raise ValueError("local_motion_router_override_reason_not_substantive")
    return str(model_id).strip(), str(operator).strip(), normalized_reason


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "CaptionBankStore",
    "admit_local_motion",
    "build_reference_video_remix_plan",
    "gemini_motion_analysis_instruction",
    "load_or_build_caption_bank_store",
    "read_audio_intent",
]
