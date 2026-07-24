"""Fail-closed Arena/Router admission for ordinary local motion generation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from creator_os_core.evidence_attestation import payload_fingerprint
from creator_os_core.task_inputs import canonical_task_input_bindings
from reel_factory.worker_api import (
    admit_local_motion,
    validate_local_wan_i2v_prompt_expansion,
)

from pipeline_contracts import validate_local_model_router_decision

from .canonical_analyzer_registry import (
    CanonicalAnalyzerRegistryError,
)
from .canonical_analyzer_registry import (
    validate_canonical_analyzer_registry as _validate_canonical_analyzer_registry,
)
from .core import sha256_file
from .evidence_foundation import validate_compiled_thin_evidence_records


class LocalMotionAdmissionError(RuntimeError):
    """The requested local generation is not backed by valid promotion evidence."""


_PLACEHOLDER_REASONS = {"test", "manual", "because", "override", "n/a", "na"}


def _fingerprint(value: Mapping[str, Any]) -> str:
    return payload_fingerprint(value)


def validate_canonical_analyzer_registry(
    registry: Mapping[str, Any],
    *,
    contentforge_root: Path | None = None,
) -> dict[str, Any]:
    """Require the exact registry emitted by ContentForge's canonical adapter."""

    try:
        return _validate_canonical_analyzer_registry(
            registry, contentforge_root=contentforge_root
        )
    except CanonicalAnalyzerRegistryError as exc:
        raise LocalMotionAdmissionError(f"local_motion_{exc}") from exc


def _load_json_object(path: Path, *, field: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise LocalMotionAdmissionError(f"local_motion_{field}_missing_or_unsafe")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalMotionAdmissionError(f"local_motion_{field}_invalid_json") from exc
    if not isinstance(value, dict):
        raise LocalMotionAdmissionError(f"local_motion_{field}_must_be_object")
    return value


def _normalized_override(
    *,
    model_id: str | None,
    operator: str | None,
    reason: str | None,
) -> tuple[str | None, str | None, str | None]:
    supplied = (model_id, operator, reason)
    if any(value is not None for value in supplied) and not all(
        value is not None and str(value).strip() for value in supplied
    ):
        raise LocalMotionAdmissionError(
            "local_motion_router_override_evidence_must_be_complete"
        )
    if model_id is None:
        return None, None, None
    normalized_reason = " ".join(str(reason).split())
    words = [
        word for word in normalized_reason.split(" ") if any(c.isalnum() for c in word)
    ]
    if (
        len(normalized_reason) < 20
        or len(words) < 3
        or normalized_reason.lower().strip(" .!?") in _PLACEHOLDER_REASONS
    ):
        raise LocalMotionAdmissionError(
            "local_motion_router_override_reason_not_substantive"
        )
    return str(model_id).strip(), str(operator).strip(), normalized_reason


def _execution_input_bindings(
    *,
    accepted_still_path: Path | None,
    audio_path: Path | None,
    last_image_path: Path | None,
    source_video_path: Path | None,
    task_kind: str,
    error_prefix: str,
) -> list[dict[str, str]]:
    """Hash every consumed file and return its canonical typed role binding."""

    accepted_input = (
        None
        if task_kind in {"text_to_video", "video_retake", "video_extend"}
        else accepted_still_path
    )
    role_fingerprints: dict[str, str | None] = {
        "image": None,
        "audio": None,
        "last_image": None,
        "source_video": None,
    }
    for field, raw_path in (
        ("image", accepted_input),
        ("audio", audio_path),
        ("last_image", last_image_path),
        ("source_video", source_video_path),
    ):
        if raw_path is None:
            continue
        path = raw_path.expanduser().resolve()
        if not path.is_file() or path.is_symlink():
            raise LocalMotionAdmissionError(
                f"local_motion_{error_prefix}{field}_missing_or_unsafe"
            )
        role_fingerprints[field] = sha256_file(path)
    try:
        return list(
            canonical_task_input_bindings(
                task_kind,
                image_sha256=role_fingerprints["image"],
                audio_sha256=role_fingerprints["audio"],
                last_image_sha256=role_fingerprints["last_image"],
                source_video_sha256=role_fingerprints["source_video"],
            )
        )
    except ValueError as exc:
        raise LocalMotionAdmissionError(f"local_motion_{error_prefix}{exc}") from exc


def _requested_audio_mode(
    *,
    audio_path: Path | None,
    generate_audio: bool,
    preserve_audio: bool,
    error_prefix: str,
) -> str:
    selected = sum(
        (
            audio_path is not None,
            generate_audio is True,
            preserve_audio is True,
        )
    )
    if selected > 1:
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}audio_mode_conflict"
        )
    if audio_path is not None:
        return "source"
    if generate_audio:
        return "generated"
    if preserve_audio:
        return "preserved"
    return "none"


def _motion_edit_binding(
    *,
    task_kind: str,
    source_video_path: Path | None,
    retake_start_frame: int | None,
    retake_end_frame: int | None,
    extend_frames: int | None,
    extend_direction: str,
    preserve_audio: bool,
    error_prefix: str,
) -> dict[str, Any]:
    """Bind every LTX edit control and the current source-video bytes."""

    source_video = None
    if source_video_path is not None:
        path = source_video_path.expanduser().resolve()
        if not path.is_file() or path.is_symlink():
            raise LocalMotionAdmissionError(
                f"local_motion_{error_prefix}source_video_missing_or_unsafe"
            )
        source_video = {"path": str(path), "sha256": sha256_file(path)}
    edit_task = task_kind in {"video_retake", "video_extend"}
    if edit_task != (source_video is not None):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}source_video_task_binding_invalid"
        )
    if not isinstance(preserve_audio, bool):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}preserve_audio_invalid"
        )
    if task_kind == "video_retake":
        if (
            not isinstance(retake_start_frame, int)
            or isinstance(retake_start_frame, bool)
            or not isinstance(retake_end_frame, int)
            or isinstance(retake_end_frame, bool)
            or not 0 <= retake_start_frame < retake_end_frame
            or extend_frames is not None
        ):
            raise LocalMotionAdmissionError(
                f"local_motion_{error_prefix}retake_binding_invalid"
            )
    elif task_kind == "video_extend":
        if (
            retake_start_frame is not None
            or retake_end_frame is not None
            or not isinstance(extend_frames, int)
            or isinstance(extend_frames, bool)
            or not 1 <= extend_frames <= 24
            or preserve_audio
        ):
            raise LocalMotionAdmissionError(
                f"local_motion_{error_prefix}extend_binding_invalid"
            )
    elif (
        any(
            value is not None
            for value in (retake_start_frame, retake_end_frame, extend_frames)
        )
        or preserve_audio
    ):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}edit_controls_without_edit_task"
        )
    if extend_direction not in {"before", "after"}:
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}extend_direction_invalid"
        )
    return {
        "taskKind": task_kind,
        "sourceVideo": source_video,
        "retakeStartFrame": retake_start_frame,
        "retakeEndFrame": retake_end_frame,
        "extendFrames": extend_frames,
        "extendDirection": extend_direction,
        "preserveAudio": preserve_audio,
    }


def _validated_router_execution_policy(
    decision: Mapping[str, Any], *, model_id: str, error_prefix: str
) -> dict[str, Any]:
    """Validate exact runtime and commercial-license evidence for one winner."""

    candidates = decision.get("consideredCandidates")
    selected = [
        item
        for item in candidates or []
        if isinstance(item, Mapping) and item.get("modelId") == model_id
    ]
    if len(selected) != 1:
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}selected_candidate_not_exactly_once"
        )
    candidate = selected[0]
    winning = decision.get("winningEvidence")
    if not isinstance(winning, Mapping):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}winning_evidence_missing"
        )

    runtime = winning.get("runtimeBinding")
    runtime_fingerprint = winning.get("runtimeBindingFingerprint")
    runtime_text_keys = {
        "runtimeId",
        "repository",
        "revision",
        "platform",
        "platformRelease",
        "osBuild",
        "machine",
        "python",
        "pythonExecutable",
        "pythonExecutableResolved",
        "mlxVersion",
        "runtimeReceiptFingerprint",
        "resolvedEnvironmentFingerprint",
        "ffmpegExecutable",
        "ffmpegSha256",
        "ffmpegVersion",
        "ffprobeExecutable",
        "ffprobeSha256",
        "ffprobeVersion",
    }
    runtime_size_keys = {"ffmpegSize", "ffprobeSize"}
    runtime_keys = runtime_text_keys | runtime_size_keys
    if (
        not isinstance(runtime, Mapping)
        or set(runtime) != runtime_keys
        or any(
            not isinstance(runtime.get(key), str) or not runtime.get(key)
            for key in runtime_text_keys
        )
        or any(
            not isinstance(runtime.get(key), int)
            or isinstance(runtime.get(key), bool)
            or int(runtime[key]) <= 0
            for key in runtime_size_keys
        )
        or any(
            not isinstance(runtime.get(key), str)
            or len(str(runtime[key])) != 64
            or any(char not in "0123456789abcdef" for char in str(runtime[key]))
            for key in {
                "runtimeReceiptFingerprint",
                "resolvedEnvironmentFingerprint",
                "ffmpegSha256",
                "ffprobeSha256",
            }
        )
        or any(
            not Path(str(runtime.get(key) or "")).is_absolute()
            for key in {
                "pythonExecutable",
                "pythonExecutableResolved",
                "ffmpegExecutable",
                "ffprobeExecutable",
            }
        )
        or not isinstance(runtime_fingerprint, str)
        or _fingerprint(runtime) != runtime_fingerprint
        or candidate.get("runtimeBinding") != runtime
        or candidate.get("runtimeBindingFingerprint") != runtime_fingerprint
    ):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}runtime_binding_invalid"
        )

    license_policy = winning.get("licensePolicy")
    license_fingerprint = winning.get("licensePolicyFingerprint")
    license_keys = {
        "licenseId",
        "commercialUse",
        "declaredAnnualRevenueUsd",
        "commercialRevenueLimitUsd",
        "commercialUseAllowed",
        "aiDisclosureRequired",
    }
    if (
        not isinstance(license_policy, Mapping)
        or set(license_policy) != license_keys
        or not isinstance(license_policy.get("licenseId"), str)
        or not str(license_policy.get("licenseId") or "").strip()
        or not isinstance(license_policy.get("aiDisclosureRequired"), bool)
        or not isinstance(license_fingerprint, str)
        or _fingerprint(license_policy) != license_fingerprint
        or candidate.get("licensePolicy") != license_policy
        or candidate.get("licensePolicyFingerprint") != license_fingerprint
    ):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}license_policy_invalid"
        )
    if (
        license_policy.get("commercialUse") is not True
        or license_policy.get("commercialUseAllowed") is not True
    ):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}commercial_use_attestation_required"
        )
    declared_revenue = license_policy.get("declaredAnnualRevenueUsd")
    revenue_limit = license_policy.get("commercialRevenueLimitUsd")
    if declared_revenue is not None and (
        not isinstance(declared_revenue, int)
        or isinstance(declared_revenue, bool)
        or declared_revenue < 0
    ):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}commercial_revenue_attestation_invalid"
        )
    if revenue_limit is not None and (
        not isinstance(revenue_limit, int)
        or isinstance(revenue_limit, bool)
        or revenue_limit <= 0
    ):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}commercial_revenue_limit_invalid"
        )
    if revenue_limit is not None and (
        declared_revenue is None or declared_revenue >= revenue_limit
    ):
        raise LocalMotionAdmissionError(
            f"local_motion_{error_prefix}commercial_revenue_not_licensed"
        )
    return {
        "runtimeBinding": dict(runtime),
        "runtimeBindingFingerprint": runtime_fingerprint,
        "licensePolicy": dict(license_policy),
        "licensePolicyFingerprint": license_fingerprint,
    }


def build_local_motion_admission(
    *,
    evidence_bundle_path: Path | None,
    evidence_bundle: Mapping[str, Any] | None = None,
    arena_summary_path: Path,
    accepted_still_path: Path | None,
    audio_path: Path | None,
    last_image_path: Path | None = None,
    source_video_path: Path | None = None,
    prompt: str = "A person moves naturally within the original composition",
    duration_seconds: int | None = None,
    resolution: str | None = None,
    seed: int = 42,
    steps: int | None = None,
    generate_audio: bool = False,
    retake_start_frame: int | None = None,
    retake_end_frame: int | None = None,
    extend_frames: int | None = None,
    extend_direction: str = "after",
    preserve_audio: bool = False,
    lora_path: Path | None = None,
    lora_strength: float = 1.0,
    campaign_creator: str,
    task_kind: str,
    override_model_id: str | None = None,
    override_operator: str | None = None,
    override_reason: str | None = None,
    contentforge_root: Path | None = None,
    prompt_expansion: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one exact Router decision bound to this Campaign request."""

    if (evidence_bundle_path is None) == (evidence_bundle is None):
        raise LocalMotionAdmissionError(
            "local_motion_evidence_bundle_requires_one_transport"
        )
    raw_records = (
        _load_json_object(evidence_bundle_path, field="evidence_bundle")
        if evidence_bundle_path is not None
        else dict(evidence_bundle or {})
    )
    records = validate_compiled_thin_evidence_records(raw_records)
    validate_canonical_analyzer_registry(
        records["analyzerRegistry"], contentforge_root=contentforge_root
    )
    summary = _load_json_object(arena_summary_path, field="arena_summary")
    identity = records["creatorIdentityProfile"]
    intent = records["contentIntent"]
    recipe = records["benchmarkRecipe"]
    normalized_creator = str(campaign_creator or "").strip().lower()
    evidence_creator = str(identity.get("creatorKey") or "").strip().lower()
    if not normalized_creator or evidence_creator != normalized_creator:
        raise LocalMotionAdmissionError("local_motion_campaign_creator_mismatch")

    audio_mode = _requested_audio_mode(
        audio_path=audio_path,
        generate_audio=generate_audio,
        preserve_audio=preserve_audio,
        error_prefix="",
    )
    input_bindings = _execution_input_bindings(
        accepted_still_path=accepted_still_path,
        audio_path=audio_path,
        last_image_path=last_image_path,
        source_video_path=source_video_path,
        task_kind=task_kind,
        error_prefix="",
    )
    input_fingerprints = [binding["sha256"] for binding in input_bindings]
    edit_binding = _motion_edit_binding(
        task_kind=task_kind,
        source_video_path=source_video_path,
        retake_start_frame=retake_start_frame,
        retake_end_frame=retake_end_frame,
        extend_frames=extend_frames,
        extend_direction=extend_direction,
        preserve_audio=preserve_audio,
        error_prefix="",
    )
    if not set(input_fingerprints).issubset(
        set(intent.get("sourceAssetFingerprints") or [])
    ):
        raise LocalMotionAdmissionError("local_motion_content_intent_input_mismatch")
    if list(recipe.get("inputFingerprints") or []) != input_fingerprints:
        raise LocalMotionAdmissionError("local_motion_benchmark_input_mismatch")
    if recipe.get("taskKind") != task_kind:
        raise LocalMotionAdmissionError("local_motion_benchmark_task_mismatch")
    validated_prompt_expansion = None
    if prompt_expansion is not None:
        if task_kind != "image_to_video" or accepted_still_path is None:
            raise LocalMotionAdmissionError(
                "local_motion_prompt_expansion_task_invalid"
            )
        try:
            validated_prompt_expansion = validate_local_wan_i2v_prompt_expansion(
                prompt_expansion,
                image_path=accepted_still_path,
                expanded_prompt=prompt,
            )
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            raise LocalMotionAdmissionError(
                f"local_motion_prompt_expansion_invalid:{exc}"
            ) from exc

    profile_id = str(identity.get("profileId") or "")
    profile_fingerprint = _fingerprint(identity)
    intent_id = str(intent.get("intentId") or "")
    intent_fingerprint = _fingerprint(intent)
    selected_model, operator, reason = _normalized_override(
        model_id=override_model_id,
        operator=override_operator,
        reason=override_reason,
    )
    try:
        admission = admit_local_motion(
            arena_summary=summary,
            evidence_records=records,
            input_fingerprints=input_fingerprints,
            input_bindings=input_bindings,
            creator_id=normalized_creator,
            identity_profile_id=profile_id,
            identity_profile_fingerprint=profile_fingerprint,
            content_intent_id=intent_id,
            content_intent_fingerprint=intent_fingerprint,
            task_kind=task_kind,
            prompt=prompt,
            duration_seconds=duration_seconds,
            resolution=resolution,
            seed=seed,
            steps=steps,
            audio_mode=audio_mode,
            lora_path=lora_path,
            lora_strength=lora_strength,
            source_video_path=source_video_path,
            retake_start_frame=retake_start_frame,
            retake_end_frame=retake_end_frame,
            extend_frames=extend_frames,
            extend_direction=extend_direction,
            override_model_id=selected_model,
            override_operator=operator,
            override_reason=reason,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise LocalMotionAdmissionError(
            f"local_motion_router_admission_failed:{exc}"
        ) from exc
    if not isinstance(admission, dict):
        raise LocalMotionAdmissionError("local_motion_router_admission_invalid")
    decision = admission.get("routerDecision")
    if not isinstance(decision, Mapping):
        raise LocalMotionAdmissionError("local_motion_router_decision_missing")
    _validated_router_execution_policy(
        decision,
        model_id=str(decision.get("selectedModelId") or ""),
        error_prefix="",
    )
    if validated_prompt_expansion is not None and not str(
        decision.get("selectedModelId") or ""
    ).startswith("local_wan22_"):
        raise LocalMotionAdmissionError(
            "local_motion_prompt_expansion_selected_model_invalid"
        )
    resource = admission.get("resourceSnapshot")
    if not isinstance(resource, dict):
        raise LocalMotionAdmissionError("local_motion_resource_snapshot_missing")
    resource["motionEditBinding"] = edit_binding
    if validated_prompt_expansion is not None:
        admission["promptExpansion"] = validated_prompt_expansion
    admission_core = dict(admission)
    admission_core.pop("admissionFingerprint", None)
    admission["admissionFingerprint"] = _fingerprint(admission_core)
    return admission


def revalidate_local_motion_admission(
    admission: Mapping[str, Any] | None,
    *,
    arena_summary_path: Path | None,
    accepted_still_path: Path | None,
    audio_path: Path | None,
    last_image_path: Path | None = None,
    source_video_path: Path | None = None,
    prompt: str = "A person moves naturally within the original composition",
    duration_seconds: int | None = None,
    resolution: str | None = None,
    seed: int = 42,
    steps: int | None = None,
    generate_audio: bool = False,
    retake_start_frame: int | None = None,
    retake_end_frame: int | None = None,
    extend_frames: int | None = None,
    extend_direction: str = "after",
    preserve_audio: bool = False,
    lora_path: Path | None = None,
    lora_strength: float = 1.0,
    campaign_creator: str,
    task_kind: str,
    model_id: str,
    benchmark_recipe: Mapping[str, Any] | None,
    analyzer_registry: Mapping[str, Any] | None,
    contentforge_root: Path | None = None,
) -> dict[str, Any]:
    """Re-admit immediately before execution and reject stale/replayed evidence."""

    if not isinstance(admission, Mapping):
        raise LocalMotionAdmissionError("local_motion_execution_admission_missing")
    original = dict(admission)
    expected_keys = {
        "schema",
        "routerDecision",
        "arenaSummary",
        "evidenceRecords",
        "inputFingerprints",
        "inputBindings",
        "promotionInputCohort",
        "taskParameterMaterial",
        "taskParameterFingerprint",
        "resourceSnapshot",
        "admissionFingerprint",
    }
    if (
        set(original) not in (expected_keys, expected_keys | {"promptExpansion"})
        or original.get("schema") != "campaign_factory.local_motion_admission.v1"
    ):
        raise LocalMotionAdmissionError("local_motion_execution_admission_invalid")
    original_core = dict(original)
    claimed_admission = str(original_core.pop("admissionFingerprint") or "")
    if _fingerprint(original_core) != claimed_admission:
        raise LocalMotionAdmissionError(
            "local_motion_execution_admission_fingerprint_mismatch"
        )
    audio_mode = _requested_audio_mode(
        audio_path=audio_path,
        generate_audio=generate_audio,
        preserve_audio=preserve_audio,
        error_prefix="execution_",
    )
    raw_decision = original.get("routerDecision")
    if not isinstance(raw_decision, Mapping):
        raise LocalMotionAdmissionError(
            "local_motion_execution_router_decision_missing"
        )
    decision = dict(raw_decision)
    try:
        validate_local_model_router_decision(decision)
    except ValueError as exc:
        raise LocalMotionAdmissionError(
            "local_motion_execution_router_decision_invalid"
        ) from exc
    decision_core = dict(decision)
    claimed_decision = str(decision_core.pop("decisionFingerprint") or "")
    if _fingerprint(decision_core) != claimed_decision:
        raise LocalMotionAdmissionError(
            "local_motion_execution_router_decision_fingerprint_mismatch"
        )
    if decision.get("selectedModelId") != model_id:
        raise LocalMotionAdmissionError(
            "local_motion_execution_selected_model_mismatch"
        )
    if (
        decision.get("paidProviderFallbackAllowed") is not False
        or decision.get("legacyLocalMotionFallbackAllowed") is not False
    ):
        raise LocalMotionAdmissionError(
            "local_motion_execution_router_fallback_not_closed"
        )
    original_execution_policy = _validated_router_execution_policy(
        decision, model_id=model_id, error_prefix="execution_"
    )
    resource = original.get("resourceSnapshot")
    if not isinstance(resource, Mapping):
        raise LocalMotionAdmissionError(
            "local_motion_execution_resource_snapshot_missing"
        )
    current_edit_binding = _motion_edit_binding(
        task_kind=task_kind,
        source_video_path=source_video_path,
        retake_start_frame=retake_start_frame,
        retake_end_frame=retake_end_frame,
        extend_frames=extend_frames,
        extend_direction=extend_direction,
        preserve_audio=preserve_audio,
        error_prefix="execution_",
    )
    if resource.get("motionEditBinding") != current_edit_binding:
        raise LocalMotionAdmissionError(
            "local_motion_execution_motion_edit_binding_mismatch"
        )
    prompt_expansion = original.get("promptExpansion")
    if prompt_expansion is not None:
        if (
            not model_id.startswith("local_wan22_")
            or task_kind != "image_to_video"
            or accepted_still_path is None
        ):
            raise LocalMotionAdmissionError(
                "local_motion_execution_prompt_expansion_task_invalid"
            )
        try:
            validate_local_wan_i2v_prompt_expansion(
                prompt_expansion,
                image_path=accepted_still_path,
                expanded_prompt=prompt,
            )
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            raise LocalMotionAdmissionError(
                f"local_motion_execution_prompt_expansion_invalid:{exc}"
            ) from exc

    records_raw = original.get("evidenceRecords")
    if not isinstance(records_raw, Mapping):
        raise LocalMotionAdmissionError("local_motion_execution_evidence_missing")
    records = validate_compiled_thin_evidence_records(records_raw)
    recipe = records["benchmarkRecipe"]
    registry = records["analyzerRegistry"]
    if benchmark_recipe is None or dict(benchmark_recipe) != recipe:
        raise LocalMotionAdmissionError(
            "local_motion_execution_benchmark_recipe_mismatch"
        )
    if analyzer_registry is None or dict(analyzer_registry) != registry:
        raise LocalMotionAdmissionError(
            "local_motion_execution_analyzer_registry_mismatch"
        )
    validate_canonical_analyzer_registry(registry, contentforge_root=contentforge_root)

    identity = records["creatorIdentityProfile"]
    intent = records["contentIntent"]
    normalized_creator = str(campaign_creator or "").strip().lower()
    if str(identity.get("creatorKey") or "").strip().lower() != normalized_creator:
        raise LocalMotionAdmissionError(
            "local_motion_execution_campaign_creator_mismatch"
        )
    input_bindings = _execution_input_bindings(
        accepted_still_path=accepted_still_path,
        audio_path=audio_path,
        last_image_path=last_image_path,
        source_video_path=source_video_path,
        task_kind=task_kind,
        error_prefix="execution_",
    )
    input_fingerprints = [binding["sha256"] for binding in input_bindings]
    if (
        original.get("inputFingerprints") != input_fingerprints
        or original.get("inputBindings") != input_bindings
        or not set(input_fingerprints).issubset(
            set(intent.get("sourceAssetFingerprints") or [])
        )
        or list(recipe.get("inputFingerprints") or []) != input_fingerprints
    ):
        raise LocalMotionAdmissionError(
            "local_motion_execution_input_fingerprint_mismatch"
        )
    if (
        recipe.get("taskKind") != task_kind
        or decision.get("request", {}).get("taskKind") != task_kind
    ):
        raise LocalMotionAdmissionError("local_motion_execution_task_mismatch")

    if arena_summary_path is None:
        raise LocalMotionAdmissionError(
            "local_motion_execution_arena_summary_path_missing"
        )
    summary = _load_json_object(arena_summary_path, field="arena_summary")
    summary_binding = {
        "summaryId": summary.get("summaryId"),
        "summaryFingerprint": summary.get("summaryFingerprint"),
        "planId": summary.get("planId"),
        "planFingerprint": summary.get("planFingerprint"),
        "purpose": summary.get("purpose"),
    }
    if original.get("arenaSummary") != summary_binding:
        raise LocalMotionAdmissionError("local_motion_execution_arena_summary_mismatch")

    override = decision.get("operatorOverride")
    override = override if isinstance(override, Mapping) else {}
    try:
        current = admit_local_motion(
            arena_summary=summary,
            evidence_records=records,
            input_fingerprints=input_fingerprints,
            input_bindings=input_bindings,
            creator_id=normalized_creator,
            identity_profile_id=str(identity.get("profileId") or ""),
            identity_profile_fingerprint=_fingerprint(identity),
            content_intent_id=str(intent.get("intentId") or ""),
            content_intent_fingerprint=_fingerprint(intent),
            task_kind=task_kind,
            prompt=prompt,
            duration_seconds=duration_seconds,
            resolution=resolution,
            seed=seed,
            steps=steps,
            audio_mode=audio_mode,
            lora_path=lora_path,
            lora_strength=lora_strength,
            source_video_path=source_video_path,
            retake_start_frame=retake_start_frame,
            retake_end_frame=retake_end_frame,
            extend_frames=extend_frames,
            extend_direction=extend_direction,
            override_model_id=(str(override.get("modelId")) if override else None),
            override_operator=(str(override.get("operator")) if override else None),
            override_reason=(str(override.get("reason")) if override else None),
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise LocalMotionAdmissionError(
            f"local_motion_execution_readmission_failed:{exc}"
        ) from exc
    if not isinstance(current, dict):
        raise LocalMotionAdmissionError("local_motion_execution_readmission_invalid")
    for field in (
        "inputBindings",
        "promotionInputCohort",
        "taskParameterMaterial",
        "taskParameterFingerprint",
    ):
        if current.get(field) != original.get(field):
            raise LocalMotionAdmissionError(
                f"local_motion_execution_promoted_input_drift:{field}"
            )
    current_decision = current.get("routerDecision")
    if not isinstance(current_decision, Mapping):
        raise LocalMotionAdmissionError(
            "local_motion_execution_readmission_decision_missing"
        )
    current_execution_policy = _validated_router_execution_policy(
        current_decision, model_id=model_id, error_prefix="execution_current_"
    )
    if current_execution_policy != original_execution_policy:
        raise LocalMotionAdmissionError(
            "local_motion_execution_runtime_or_license_policy_drift"
        )
    for field in (
        "selectedModelId",
        "selectedModelFingerprint",
        "operatorOverride",
        "paidProviderFallbackAllowed",
        "legacyLocalMotionFallbackAllowed",
    ):
        if current_decision.get(field) != decision.get(field):
            raise LocalMotionAdmissionError(
                f"local_motion_execution_router_drift:{field}"
            )
    original_winning = decision.get("winningEvidence")
    current_winning = current_decision.get("winningEvidence")
    if not isinstance(original_winning, Mapping) or not isinstance(
        current_winning, Mapping
    ):
        raise LocalMotionAdmissionError(
            "local_motion_execution_winning_evidence_missing"
        )
    for field in (
        "arenaSummaryFingerprint",
        "benchmarkIds",
        "cohortKey",
        "matchedArenaSampleIds",
        "validArenaSampleIds",
        "promotionApproval",
        "runtimeBinding",
        "runtimeBindingFingerprint",
        "licensePolicy",
        "licensePolicyFingerprint",
    ):
        if current_winning.get(field) != original_winning.get(field):
            raise LocalMotionAdmissionError(
                f"local_motion_execution_winning_evidence_drift:{field}"
            )
    return original
