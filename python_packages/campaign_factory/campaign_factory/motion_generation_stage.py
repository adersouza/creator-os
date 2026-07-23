"""Campaign-owned orchestration for local MLX and WaveSpeed motion workers."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from creator_os_core.evidence_attestation import (
    load_evidence_secret,
    payload_fingerprint,
    sign_evidence_attestation,
)
from creator_os_core.fileops import atomic_write_text
from creator_os_core.provider_spend import verify_authorization_v2
from creator_os_core.task_inputs import canonical_task_input_bindings

from pipeline_contracts import (
    ContentIntentV1,
    CreatorIdentityProfileV1,
    IdentityReferenceV1,
    ProvenanceV1,
    SourceReferenceV1,
    validate_paid_motion_execution_receipt,
    validate_provider_spend_authorization_v2,
)

from .core import (
    new_id,
    sanitize_for_storage,
    sha256_file,
    slugify,
)
from .generation_execution_plan import (
    GenerationExecutionPlan,
    authorize_paid_generation,
    require_generation_execution_mode,
)
from .local_motion_admission import revalidate_local_motion_admission
from .motion_request_identity import (
    ensure_text_prompt_source_asset as _ensure_text_prompt_source_asset,
)
from .motion_request_identity import (
    motion_request_fingerprint as _motion_request_fingerprint,
)
from .motion_request_identity import required_path as _required_path
from .motion_request_identity import (
    resolve_task_media_path as _resolve_task_media_path,
)
from .motion_request_identity import (
    text_prompt_task_fingerprint as _text_prompt_task_fingerprint,
)
from .motion_routing_lineage import local_routing_lineage as _local_routing_lineage
from .motion_source_assets import (
    ensure_motion_edit_source_asset as _ensure_motion_edit_source_asset,
)
from .motion_worker_process import (
    MotionWorkerError,
)
from .motion_worker_process import (
    build_motion_worker_command as _worker_command,
)
from .motion_worker_process import (
    invoke_motion_worker as _invoke_worker,
)
from .persistence import utc_now
from .provider_spend import consume_provider_spend_authorization
from .provider_spend_v2 import (
    issue_wavespeed_spend_authorization,
    record_wavespeed_execution,
)
from .static_mp4_stage import run_static_mp4_stage


def run_motion_generation_stage(
    factory: Any,
    *,
    execution_plan: GenerationExecutionPlan,
    campaign_slug: str,
    still_path: Path | None,
    prompt: str,
    model_id: str,
    duration_seconds: int | None,
    resolution: str | None,
    seed: int,
    steps: int | None,
    dry_run: bool,
    apply: bool,
    workspace: Path | None = None,
    paid_confirmation: bool = False,
    max_usd: float | None = None,
    audio_path: Path | None = None,
    generate_audio: bool = False,
    last_image_path: Path | None = None,
    source_video_path: Path | None = None,
    retake_start_frame: int | None = None,
    retake_end_frame: int | None = None,
    extend_frames: int | None = None,
    extend_direction: str = "after",
    preserve_audio: bool = False,
    reference_image_paths: tuple[Path, ...] = (),
    reference_video_paths: tuple[Path, ...] = (),
    enable_prompt_expansion: bool = False,
    shot_type: str = "single",
    local_model_dir: Path | None = None,
    motion_task: str = "image_to_video",
    motion_lora_path: Path | None = None,
    motion_lora_strength: float = 1.0,
    benchmark_recipe: Mapping[str, Any] | None = None,
    analyzer_registry: Mapping[str, Any] | None = None,
    local_motion_admission: Mapping[str, Any] | None = None,
    local_arena_summary_path: Path | None = None,
    campaign_creator: str | None = None,
) -> dict[str, Any]:
    """Generate one review-only motion asset with a preserved static fallback."""
    expected_mode = execution_plan.creative_mode
    if expected_mode not in {"local_wan", "best_motion"}:
        raise PermissionError(f"{expected_mode} does not authorize motion generation")
    require_generation_execution_mode(execution_plan, expected_mode)
    if apply == dry_run:
        raise ValueError("choose exactly one of dry_run or apply")
    text_only = motion_task == "text_to_video"
    video_edit = motion_task in {"video_retake", "video_extend"}
    still: Path | None = None
    source_video: Path | None = None
    if text_only:
        supplied_media = [
            label
            for label, value in (
                ("still_path", still_path),
                ("audio_path", audio_path),
                ("last_image_path", last_image_path),
                ("source_video_path", source_video_path),
                ("reference_image_paths", reference_image_paths),
                ("reference_video_paths", reference_video_paths),
            )
            if value
        ]
        if supplied_media:
            raise ValueError(
                "text_to_video accepts no media inputs: " + ",".join(supplied_media)
            )
        primary_source = None
    elif video_edit:
        if still_path is not None:
            raise ValueError(
                f"{motion_task} uses source_video_path as its only primary input; "
                "still_path is forbidden"
            )
        if source_video_path is None:
            raise FileNotFoundError(f"{motion_task} source video is required")
        source_video = Path(source_video_path).expanduser().resolve()
        if source_video.is_symlink() or not source_video.is_file():
            raise FileNotFoundError(
                f"{motion_task} source video not found: {source_video}"
            )
        source_video_path = source_video
        primary_source = source_video
    else:
        if still_path is None:
            raise FileNotFoundError("accepted still is required")
        still = Path(still_path).expanduser().resolve()
        if still.is_symlink() or not still.is_file():
            raise FileNotFoundError(f"accepted still not found: {still}")
        source_video = _resolve_task_media_path(source_video_path, "source video")
        source_video_path = source_video
        primary_source = still
    audio_path = _resolve_task_media_path(audio_path, "source audio")
    last_image_path = _resolve_task_media_path(last_image_path, "last image")
    try:
        canonical_task_input_bindings(
            motion_task,
            image_sha256=sha256_file(still) if still is not None else None,
            audio_sha256=(sha256_file(audio_path) if audio_path is not None else None),
            last_image_sha256=(
                sha256_file(last_image_path) if last_image_path is not None else None
            ),
            source_video_sha256=(
                sha256_file(source_video) if source_video is not None else None
            ),
        )
    except ValueError as exc:
        raise ValueError(f"motion_{exc}") from exc
    prompt = " ".join(str(prompt or "").split())
    if len(prompt) < 20:
        raise ValueError("motion prompt must contain at least 20 characters")
    if model_id not in execution_plan.models:
        raise PermissionError(
            f"{execution_plan.creative_mode} does not authorize model {model_id}"
        )
    paid = model_id.startswith("wavespeed_")
    if paid:
        authorize_paid_generation(
            execution_plan,
            expected_mode="best_motion",
            media_kind="video",
            required_approvals=("human_still_approval", "paid_generation"),
            provider="wavespeed",
            model=model_id,
        )
    elif expected_mode != "local_wan":
        raise PermissionError("best_motion requires an explicit paid provider model")
    if (benchmark_recipe is None) != (analyzer_registry is None):
        raise ValueError("benchmark evidence records must be provided together")
    if paid and benchmark_recipe is not None:
        raise ValueError("benchmark evidence applies only to local models")
    if paid and local_motion_admission is not None:
        raise ValueError("local motion admission applies only to local models")
    if not paid:
        _validate_local_motion_admission(local_motion_admission, model_id=model_id)

    campaign = factory.domains.campaign_by_slug(campaign_slug)
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    if not paid:
        revalidate_admission = partial(
            revalidate_local_motion_admission,
            arena_summary_path=local_arena_summary_path,
            accepted_still_path=still,
            audio_path=audio_path,
            last_image_path=last_image_path,
            source_video_path=source_video_path,
            prompt=prompt,
            duration_seconds=duration_seconds,
            resolution=resolution,
            seed=seed,
            steps=steps,
            generate_audio=generate_audio,
            retake_start_frame=retake_start_frame,
            retake_end_frame=retake_end_frame,
            extend_frames=extend_frames,
            extend_direction=extend_direction,
            preserve_audio=preserve_audio,
            lora_path=motion_lora_path,
            lora_strength=motion_lora_strength,
            campaign_creator=campaign_creator or model_slug,
            task_kind=motion_task,
            model_id=model_id,
            benchmark_recipe=benchmark_recipe,
            analyzer_registry=analyzer_registry,
            contentforge_root=factory.settings.contentforge_root,
        )
        local_motion_admission = revalidate_admission(local_motion_admission)
    dirs = factory.domains.campaign_dirs(model_slug, campaign["slug"])
    source_hash = (
        _text_prompt_task_fingerprint(prompt)
        if text_only
        else sha256_file(_required_path(primary_source, "motion generation input"))
    )
    request_fingerprint = _motion_request_fingerprint(
        model_id=model_id,
        prompt=prompt,
        still=still,
        duration_seconds=duration_seconds,
        resolution=resolution,
        seed=seed,
        steps=steps,
        audio_path=audio_path,
        generate_audio=generate_audio,
        last_image_path=last_image_path,
        source_video_path=source_video_path,
        retake_start_frame=retake_start_frame,
        retake_end_frame=retake_end_frame,
        extend_frames=extend_frames,
        extend_direction=extend_direction,
        preserve_audio=preserve_audio,
        reference_image_paths=reference_image_paths,
        reference_video_paths=reference_video_paths,
        enable_prompt_expansion=enable_prompt_expansion,
        shot_type=shot_type,
        local_model_dir=local_model_dir,
        motion_task=motion_task,
        motion_lora_path=motion_lora_path,
        motion_lora_strength=motion_lora_strength,
        benchmark_recipe=benchmark_recipe,
        analyzer_registry=analyzer_registry,
        local_motion_admission=local_motion_admission,
    )
    output_source_stem = (
        "text_prompt"
        if text_only
        else slugify(_required_path(primary_source, "motion generation input").stem)
    )
    output_path = dirs["rendered"] / (
        f"{output_source_stem}_{source_hash[:12]}_{slugify(model_id)}_"
        f"{request_fingerprint[:16]}.mp4"
    )
    evidence_dir = dirs["audits"] / "motion_generation"
    worker_command = _worker_command(
        factory,
        model_id=model_id,
        prompt=prompt,
        still=still,
        output_path=output_path,
        campaign_slug=campaign_slug,
        duration_seconds=duration_seconds,
        resolution=resolution,
        seed=seed,
        steps=steps,
        audio_path=audio_path,
        generate_audio=generate_audio,
        last_image_path=last_image_path,
        source_video_path=source_video_path,
        retake_start_frame=retake_start_frame,
        retake_end_frame=retake_end_frame,
        extend_frames=extend_frames,
        extend_direction=extend_direction,
        preserve_audio=preserve_audio,
        reference_image_paths=reference_image_paths,
        reference_video_paths=reference_video_paths,
        enable_prompt_expansion=enable_prompt_expansion,
        shot_type=shot_type,
        local_model_dir=local_model_dir,
        motion_task=motion_task,
        motion_lora_path=motion_lora_path,
        motion_lora_strength=motion_lora_strength,
        benchmark_recipe=benchmark_recipe,
        analyzer_registry=analyzer_registry,
        local_motion_admission=local_motion_admission,
        evidence_transport_dir=evidence_dir / "worker_inputs",
        dry_run=True,
    )
    pipeline_job = factory.domains.events.create_pipeline_job(
        "motion_generation",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "modelId": model_id,
            "sourcePath": str(primary_source) if primary_source is not None else None,
            "sourceSha256": source_hash,
            "sourceRole": (
                "text_prompt"
                if text_only
                else ("source_video_edit" if video_edit else "accepted_still")
            ),
            "promptTaskFingerprint": source_hash if text_only else None,
            "requestFingerprint": request_fingerprint,
            "outputPath": str(output_path),
            "dryRun": dry_run,
            "apply": apply,
            "paidGeneration": paid,
            "benchmarkRecipeId": (
                benchmark_recipe.get("recipeId")
                if benchmark_recipe is not None
                else None
            ),
            "localMotionAdmissionFingerprint": (
                local_motion_admission.get("admissionFingerprint")
                if local_motion_admission is not None
                else None
            ),
        },
    )
    factory.domains.events.start_pipeline_job(pipeline_job["id"])
    preflight_log_evidence: dict[str, Any] | None = None
    apply_log_evidence: dict[str, Any] | None = None
    worker_phase = "preflight"
    try:
        worker_log_dir = evidence_dir / "worker_logs" / str(pipeline_job["id"])
        worker_plan = _invoke_worker(
            worker_command,
            factory=factory,
            log_dir=worker_log_dir,
            phase="preflight",
        )
        preflight_log_evidence = worker_plan.pop("_campaignExecutionLogEvidence", None)
        scope = worker_plan.get("spendScope")
        source_asset_id: str | None = None
        registration_source_path = primary_source
        registration_source_hash = source_hash
        if text_only:
            static_fallback = None
            if apply:
                prompt_source = _ensure_text_prompt_source_asset(
                    factory,
                    campaign=campaign,
                    model_slug=model_slug,
                    prompt=prompt,
                    prompt_task_fingerprint=source_hash,
                    evidence_dir=evidence_dir,
                )
                source_asset_id = str(prompt_source["id"])
                registration_source_path = (
                    Path(str(prompt_source["stored_path"])).expanduser().resolve()
                )
                registration_source_hash = str(prompt_source["content_hash"])
        elif video_edit:
            static_fallback = None
            if apply:
                source_asset = _ensure_motion_edit_source_asset(
                    factory,
                    campaign=campaign,
                    model_slug=model_slug,
                    source_video=_required_path(
                        primary_source, "motion edit source video"
                    ),
                    source_hash=source_hash,
                    motion_task=motion_task,
                )
                source_asset_id = str(source_asset["id"])
        else:
            assert still is not None
            static_fallback = run_static_mp4_stage(
                factory,
                campaign_slug=campaign_slug,
                still_path=still,
                duration_seconds=float(
                    6 if duration_seconds is None else duration_seconds
                ),
                dry_run=dry_run,
                apply=apply,
            )
            if apply:
                source_asset_id = _static_source_asset_id(static_fallback)
        authorization = None
        authorization_path: Path | None = None
        authorization_verified_at: str | None = None
        worker_result = worker_plan
        if apply:
            if not paid:
                local_motion_admission = revalidate_admission(local_motion_admission)
            apply_command = _worker_command(
                factory,
                model_id=model_id,
                prompt=prompt,
                still=still,
                output_path=output_path,
                campaign_slug=campaign_slug,
                duration_seconds=duration_seconds,
                resolution=resolution,
                seed=seed,
                steps=steps,
                audio_path=audio_path,
                generate_audio=generate_audio,
                last_image_path=last_image_path,
                source_video_path=source_video_path,
                retake_start_frame=retake_start_frame,
                retake_end_frame=retake_end_frame,
                extend_frames=extend_frames,
                extend_direction=extend_direction,
                preserve_audio=preserve_audio,
                reference_image_paths=reference_image_paths,
                reference_video_paths=reference_video_paths,
                enable_prompt_expansion=enable_prompt_expansion,
                shot_type=shot_type,
                local_model_dir=local_model_dir,
                motion_task=motion_task,
                motion_lora_path=motion_lora_path,
                motion_lora_strength=motion_lora_strength,
                benchmark_recipe=benchmark_recipe,
                analyzer_registry=analyzer_registry,
                local_motion_admission=local_motion_admission,
                evidence_transport_dir=evidence_dir / "worker_inputs",
                dry_run=False,
            )
            worker_phase = "apply"
            if paid:
                if not paid_confirmation:
                    raise PermissionError(
                        "paid motion generation requires --confirm-paid"
                    )
                if (
                    workspace is None
                    or not Path(workspace).expanduser().resolve().is_dir()
                ):
                    raise ValueError(
                        "paid motion generation requires an existing --workspace"
                    )
                if max_usd is None:
                    raise ValueError("paid motion generation requires --max-usd")
                if not isinstance(scope, dict):
                    raise RuntimeError("WaveSpeed worker preflight omitted spend scope")
                secret = os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", "")
                authorization = issue_wavespeed_spend_authorization(
                    factory.conn,
                    scope=scope,
                    campaign_id=campaign["id"],
                    max_usd=max_usd,
                    secret=secret,
                )
                evidence_dir.mkdir(parents=True, exist_ok=True)
                auth_path = evidence_dir / (
                    f"{scope['requestFingerprint']}.spend_authorization.json"
                )
                atomic_write_text(
                    auth_path,
                    json.dumps(authorization, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                authorization_path = auth_path
                authorization_verified_at = utc_now()
                _verify_paid_authorization_at_call(
                    authorization,
                    expected_scope=scope,
                    secret=secret,
                    now=datetime.fromisoformat(
                        authorization_verified_at.replace("Z", "+00:00")
                    ),
                )
                consume_provider_spend_authorization(
                    factory.conn, authorization["authorizationId"]
                )
                apply_command.extend(
                    [
                        "--authorization-json",
                        str(auth_path),
                        "--evidence-dir",
                        str(evidence_dir),
                    ]
                )
            worker_result = _invoke_worker(
                apply_command,
                factory=factory,
                log_dir=worker_log_dir,
                phase="apply",
            )
            apply_log_evidence = worker_result.pop(
                "_campaignExecutionLogEvidence", None
            )
            if preflight_log_evidence is not None or apply_log_evidence is not None:
                worker_result["campaignExecutionLogEvidence"] = {
                    "preflight": preflight_log_evidence,
                    "apply": apply_log_evidence,
                }
        elif preflight_log_evidence is not None:
            worker_result["campaignExecutionLogEvidence"] = {
                "preflight": preflight_log_evidence,
                "apply": None,
            }
            if paid and authorization is not None:
                execution = worker_result.get("result")
                prediction_id = (
                    str(execution.get("predictionId") or "")
                    if isinstance(execution, dict)
                    else ""
                )
                if not prediction_id:
                    raise RuntimeError("WaveSpeed worker omitted prediction id")
                assert isinstance(execution, dict)
                cost_event_id = record_wavespeed_execution(
                    factory.conn,
                    authorization=authorization,
                    prediction_id=prediction_id,
                    status=str(execution.get("status") or "completed"),
                    actual_usd=execution.get("providerCostUsd"),
                )
                worker_result["campaignCostEventId"] = cost_event_id
                worker_result["paidExecutionReceipt"] = (
                    _record_paid_motion_execution_receipt(
                        factory,
                        evidence_dir=evidence_dir,
                        authorization=authorization,
                        authorization_path=authorization_path,
                        authorization_verified_at=authorization_verified_at,
                        source_path=_required_path(
                            registration_source_path,
                            "motion generation provenance source",
                        ),
                        source_sha256=registration_source_hash,
                        output_path=output_path,
                        prediction_id=prediction_id,
                        provider_result=execution,
                        cost_event_id=cost_event_id,
                    )
                )
        registered_asset = None
        if apply:
            if source_asset_id is None:
                raise RuntimeError("motion generation source asset identity missing")
            registered_asset = _register_review_asset(
                factory,
                campaign=campaign,
                source_asset_id=source_asset_id,
                model_slug=model_slug,
                model_id=model_id,
                source_path=_required_path(
                    registration_source_path,
                    "motion generation provenance source",
                ),
                source_hash=registration_source_hash,
                output_path=output_path,
                worker_result=worker_result,
                paid=paid,
                motion_task=motion_task,
                request_fingerprint=request_fingerprint,
                local_motion_admission=local_motion_admission,
                prompt=prompt,
                pipeline_job_id=pipeline_job["id"],
                paid_authorization=authorization,
                paid_authorization_path=authorization_path,
            )
        result = {
            "schema": "campaign_factory.motion_generation_stage_run.v1",
            "campaign": campaign_slug,
            "modelId": model_id,
            "dryRun": dry_run,
            "apply": apply,
            "paidGeneration": paid,
            "providerCalls": worker_result.get("providerCalls", 0),
            "staticFallback": static_fallback,
            "worker": worker_result,
            "registeredAsset": registered_asset,
            "pipelineJobId": pipeline_job["id"],
            "localMotionAdmission": (
                dict(local_motion_admission)
                if local_motion_admission is not None
                else None
            ),
            "humanReviewRequired": True,
            "schedulingAllowed": False,
            "publishingAllowed": False,
        }
        factory.domains.events.finish_pipeline_job(
            pipeline_job["id"], sanitize_for_storage(result)
        )
        return result
    except Exception as exc:
        failure_evidence: dict[str, Any] = {
            "requestFingerprint": request_fingerprint,
            "workerPhase": worker_phase,
            "workerLogEvidence": {
                "preflight": preflight_log_evidence,
                "apply": apply_log_evidence,
            },
        }
        if isinstance(exc, MotionWorkerError):
            failure_evidence["workerLogEvidence"][worker_phase] = exc.log_evidence
        factory.domains.events.fail_pipeline_job(
            pipeline_job["id"],
            str(exc),
            sanitize_for_storage(failure_evidence),
        )
        raise


def _validate_local_motion_admission(
    admission: Mapping[str, Any] | None, *, model_id: str
) -> None:
    if admission is None:
        raise PermissionError("local_motion_router_admission_required")
    if admission.get("schema") != "campaign_factory.local_motion_admission.v1":
        raise PermissionError("local_motion_admission_schema_mismatch")
    core = dict(admission)
    claimed = str(core.pop("admissionFingerprint", ""))
    actual = hashlib.sha256(
        json.dumps(
            core, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    if claimed != actual:
        raise PermissionError("local_motion_admission_fingerprint_mismatch")
    decision = admission.get("routerDecision")
    summary = admission.get("arenaSummary")
    if not isinstance(decision, Mapping) or not isinstance(summary, Mapping):
        raise PermissionError("local_motion_admission_evidence_missing")
    if decision.get("schema") != "reel_factory.local_model_router_decision.v1":
        raise PermissionError("local_motion_router_decision_schema_mismatch")
    decision_core = dict(decision)
    decision_claimed = str(decision_core.pop("decisionFingerprint", ""))
    decision_actual = hashlib.sha256(
        json.dumps(
            decision_core,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if decision_claimed != decision_actual:
        raise PermissionError("local_motion_router_decision_fingerprint_mismatch")
    if decision.get("selectedModelId") != model_id:
        raise PermissionError("local_motion_router_selected_model_mismatch")
    if decision.get("paidProviderFallbackAllowed") is not False:
        raise PermissionError("local_motion_paid_provider_fallback_forbidden")
    if decision.get("legacyLocalMotionFallbackAllowed") is not False:
        raise PermissionError("local_motion_legacy_fallback_forbidden")
    winning = decision.get("winningEvidence")
    if not isinstance(winning, Mapping) or (
        winning.get("arenaSummaryFingerprint") != summary.get("summaryFingerprint")
    ):
        raise PermissionError("local_motion_arena_summary_binding_mismatch")
    if summary.get("purpose") != "promotion_eligible":
        raise PermissionError("local_motion_arena_not_promotion_eligible")


def _static_source_asset_id(static_fallback: dict[str, Any]) -> str:
    registered = static_fallback.get("registeredAsset")
    if not isinstance(registered, dict) or not registered.get("source_asset_id"):
        raise RuntimeError("static fallback omitted source asset identity")
    return str(registered["source_asset_id"])


def _canonical_fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def _verify_paid_authorization_at_call(
    authorization: Mapping[str, Any],
    *,
    expected_scope: Mapping[str, Any],
    secret: str,
    now: datetime,
) -> dict[str, Any]:
    """Validate the canonical contract and live HMAC immediately before provider I/O."""

    validate_provider_spend_authorization_v2(dict(authorization))
    return verify_authorization_v2(
        authorization,
        expected_scope=expected_scope,
        secret=secret,
        now=now,
    )


def _record_paid_motion_execution_receipt(
    factory: Any,
    *,
    evidence_dir: Path,
    authorization: Mapping[str, Any],
    authorization_path: Path | None,
    authorization_verified_at: str | None,
    source_path: Path,
    source_sha256: str,
    output_path: Path,
    prediction_id: str,
    provider_result: Mapping[str, Any],
    cost_event_id: str,
) -> dict[str, Any]:
    if authorization_path is None or authorization_verified_at is None:
        raise RuntimeError("paid_execution_authorization_verification_missing")
    auth_path = authorization_path.expanduser().resolve()
    resolved_source = source_path.expanduser().resolve()
    resolved_output = output_path.expanduser().resolve()
    provider_path = Path(str(provider_result.get("evidencePath") or "")).expanduser()
    if (
        auth_path.is_symlink()
        or resolved_source.is_symlink()
        or resolved_output.is_symlink()
        or provider_path.is_symlink()
    ):
        raise RuntimeError("paid_execution_provider_evidence_unsafe")
    provider_path = provider_path.resolve()
    if not all(
        path.is_file()
        for path in (auth_path, resolved_source, resolved_output, provider_path)
    ):
        raise RuntimeError("paid_execution_evidence_missing")
    try:
        stored_authorization = json.loads(auth_path.read_text(encoding="utf-8"))
        provider_evidence = json.loads(provider_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("paid_execution_evidence_invalid") from exc
    if stored_authorization != dict(authorization) or not isinstance(
        provider_evidence, dict
    ):
        raise RuntimeError("paid_execution_evidence_substituted")
    scope = authorization.get("scope")
    if not isinstance(scope, Mapping):
        raise RuntimeError("paid_execution_scope_missing")
    if sha256_file(resolved_source) != source_sha256:
        raise RuntimeError("paid_execution_input_substituted")
    output_sha256 = sha256_file(resolved_output)
    provider_model = str(scope.get("providerModel") or "")
    request_fingerprint = str(scope.get("requestFingerprint") or "")
    expected_provider_fields = {
        "schema": "reel_factory.wavespeed_submission.v1",
        "authorizationId": authorization.get("authorizationId"),
        "requestFingerprint": request_fingerprint,
        "providerModel": provider_model,
        "status": "completed",
        "predictionId": prediction_id,
        "outputSha256": output_sha256,
    }
    if any(
        provider_result.get(key) != value or provider_evidence.get(key) != value
        for key, value in expected_provider_fields.items()
    ):
        raise RuntimeError("paid_execution_provider_evidence_mismatch")
    cost_row = factory.conn.execute(
        "SELECT * FROM ai_cost_events WHERE id = ?", (cost_event_id,)
    ).fetchone()
    if cost_row is None:
        raise RuntimeError("paid_execution_cost_record_missing")
    cost_snapshot = dict(cost_row)
    try:
        cost_metadata = json.loads(cost_snapshot.get("metadata_json") or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("paid_execution_cost_record_invalid") from exc
    if (
        cost_snapshot.get("provider") != "wavespeed"
        or cost_metadata.get("authorizationId") != authorization.get("authorizationId")
        or cost_metadata.get("predictionId") != prediction_id
        or cost_metadata.get("requestFingerprint") != request_fingerprint
    ):
        raise RuntimeError("paid_execution_cost_record_mismatch")
    prediction_fingerprint = _canonical_fingerprint(
        {
            "provider": "wavespeed",
            "providerModel": provider_model,
            "predictionId": prediction_id,
            "requestFingerprint": request_fingerprint,
            "inputSha256": source_sha256,
            "outputSha256": output_sha256,
        }
    )
    recorded_at = utc_now()
    verified_at = datetime.fromisoformat(
        authorization_verified_at.replace("Z", "+00:00")
    )
    recorded_timestamp = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    if verified_at > recorded_timestamp:
        raise RuntimeError("paid_execution_authorization_verification_future")
    core = {
        "schema": "campaign_factory.paid_motion_execution_receipt.v1",
        "receiptId": "paid-motion-exec-"
        + _canonical_fingerprint(
            {
                "authorizationId": authorization.get("authorizationId"),
                "predictionId": prediction_id,
                "outputSha256": output_sha256,
            }
        )[:24],
        "issuer": "campaign_factory.motion_generation_stage",
        "recordedAt": recorded_at,
        "authorizationVerifiedAt": authorization_verified_at,
        "authorization": {
            "id": str(authorization.get("authorizationId") or ""),
            "fingerprint": payload_fingerprint(authorization),
        },
        "authorizationEvidence": {
            "path": str(auth_path),
            "sha256": sha256_file(auth_path),
        },
        "scope": dict(scope),
        "requestFingerprint": request_fingerprint,
        "providerModel": provider_model,
        "input": {"path": str(resolved_source), "sha256": source_sha256},
        "output": {"path": str(resolved_output), "sha256": output_sha256},
        "prediction": {"id": prediction_id, "fingerprint": prediction_fingerprint},
        "providerEvidence": {
            "path": str(provider_path),
            "sha256": sha256_file(provider_path),
        },
        "costRecord": {
            "id": cost_event_id,
            "fingerprint": payload_fingerprint(cost_snapshot),
            "snapshot": cost_snapshot,
        },
    }
    attested = {**core, "receiptFingerprint": payload_fingerprint(core)}
    receipt = {
        **attested,
        "attestation": sign_evidence_attestation(
            attested,
            issuer="campaign_factory.motion_generation_stage",
            issued_at=recorded_at,
            secret=load_evidence_secret(),
        ),
    }
    validate_paid_motion_execution_receipt(receipt)
    directory = evidence_dir.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    path = directory / f"{receipt['receiptId']}.json"
    if path.exists() or path.is_symlink():
        if not path.is_file() or path.is_symlink() or path.read_text() != encoded:
            raise RuntimeError("paid_execution_receipt_identity_collision")
    else:
        atomic_write_text(path, encoded, encoding="utf-8")
        path.chmod(0o444)
    return {
        "id": receipt["receiptId"],
        "fingerprint": receipt["receiptFingerprint"],
        "path": str(path),
        "sha256": sha256_file(path),
    }


def _paid_generation_evidence(
    factory: Any,
    *,
    campaign: Mapping[str, Any],
    model_slug: str,
    model_id: str,
    motion_task: str,
    source_asset_id: str,
    source_path: Path,
    source_hash: str,
    output_path: Path,
    output_hash: str,
    request_fingerprint: str | None,
    prompt: str | None,
    worker_result: Mapping[str, Any],
    authorization: Mapping[str, Any] | None,
    authorization_path: Path | None,
    produced_at: str,
) -> dict[str, Any]:
    """Snapshot exact paid execution lineage while the provider result is present."""

    if authorization is None or authorization_path is None:
        raise RuntimeError("paid_generation_authorization_evidence_missing")
    auth_path = Path(authorization_path).expanduser().resolve()
    if not auth_path.is_file() or auth_path.is_symlink():
        raise RuntimeError("paid_generation_authorization_evidence_unsafe")
    try:
        stored_authorization = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("paid_generation_authorization_evidence_invalid") from exc
    if stored_authorization != dict(authorization):
        raise RuntimeError("paid_generation_authorization_evidence_mismatch")
    scope = authorization.get("scope")
    generation = worker_result.get("result")
    if not isinstance(scope, Mapping) or not isinstance(generation, Mapping):
        raise RuntimeError("paid_generation_execution_evidence_missing")
    provider_request_fingerprint = str(scope.get("requestFingerprint") or "")
    provider_model = str(scope.get("providerModel") or "")
    prediction_id = str(generation.get("predictionId") or "")
    evidence_path = Path(str(generation.get("evidencePath") or "")).expanduser()
    if evidence_path.is_symlink():
        raise RuntimeError("paid_generation_provider_evidence_unsafe")
    evidence_path = evidence_path.resolve()
    if not evidence_path.is_file():
        raise RuntimeError("paid_generation_provider_evidence_missing")
    try:
        provider_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("paid_generation_provider_evidence_invalid") from exc
    if (
        not request_fingerprint
        or len(request_fingerprint) != 64
        or scope.get("provider") != "wavespeed"
        or not provider_model
        or not prediction_id
        or generation.get("status") != "completed"
        or generation.get("authorizationId") != authorization.get("authorizationId")
        or generation.get("requestFingerprint") != provider_request_fingerprint
        or generation.get("providerModel") != provider_model
        or generation.get("outputSha256") != output_hash
        or any(
            provider_evidence.get(key) != generation.get(key)
            for key in (
                "schema",
                "requestFingerprint",
                "authorizationId",
                "providerModel",
                "status",
                "predictionId",
                "outputSha256",
            )
        )
    ):
        raise RuntimeError("paid_generation_provider_evidence_mismatch")
    cost_event_id = str(worker_result.get("campaignCostEventId") or "")
    cost_row = factory.conn.execute(
        "SELECT * FROM ai_cost_events WHERE id = ?", (cost_event_id,)
    ).fetchone()
    if cost_row is None:
        raise RuntimeError("paid_generation_spend_record_missing")
    cost_record = dict(cost_row)
    metadata = json.loads(cost_record.get("metadata_json") or "{}")
    if (
        cost_record.get("provider") != "wavespeed"
        or metadata.get("authorizationId") != authorization.get("authorizationId")
        or metadata.get("predictionId") != prediction_id
        or metadata.get("requestFingerprint") != provider_request_fingerprint
    ):
        raise RuntimeError("paid_generation_spend_record_mismatch")
    execution_receipt = worker_result.get("paidExecutionReceipt")
    if not isinstance(execution_receipt, Mapping):
        raise RuntimeError("paid_generation_execution_receipt_missing")
    receipt_path = Path(str(execution_receipt.get("path") or "")).expanduser()
    if receipt_path.is_symlink():
        raise RuntimeError("paid_generation_execution_receipt_unsafe")
    receipt_path = receipt_path.resolve()
    if not receipt_path.is_file() or sha256_file(receipt_path) != execution_receipt.get(
        "sha256"
    ):
        raise RuntimeError("paid_generation_execution_receipt_mismatch")

    campaign_record = {
        "id": str(campaign.get("id") or ""),
        "slug": str(campaign.get("slug") or ""),
        "modelSlug": model_slug,
    }
    campaign_fingerprint = _canonical_fingerprint(campaign_record)
    identity = CreatorIdentityProfileV1(
        profile_id=f"campaign-creator-{model_slug}",
        creator_key=model_slug,
        display_name=model_slug,
        model_profile=model_slug,
        identity_references=(
            IdentityReferenceV1(
                namespace="campaign_source_still",
                external_id=source_asset_id,
                fingerprint=source_hash,
            ),
        ),
        provenance=ProvenanceV1(
            producer="campaign_factory.motion_generation_stage",
            produced_at=produced_at,
            source_references=(
                SourceReferenceV1(
                    record_id=str(campaign["id"]),
                    fingerprint=campaign_fingerprint,
                ),
                SourceReferenceV1(
                    record_id=source_asset_id,
                    fingerprint=source_hash,
                ),
            ),
        ),
    ).to_dict()
    intent = ContentIntentV1(
        intent_id=f"paid-motion-intent-{request_fingerprint[:24]}",
        creator_identity_profile_id=str(identity["profileId"]),
        goal="create one creator-conditioned motion asset for human review",
        content_surface="reel",
        media_kind="video",
        style_lanes=("creator_conditioned_motion",),
        concept_tags=tuple(sorted({motion_task, model_id})),
        source_asset_fingerprints=(source_hash,),
        provenance=ProvenanceV1(
            producer="campaign_factory.motion_generation_stage",
            produced_at=produced_at,
            source_references=(
                SourceReferenceV1(
                    record_id=source_asset_id,
                    fingerprint=source_hash,
                ),
                SourceReferenceV1(
                    record_id=f"provider-request-{provider_request_fingerprint[:24]}",
                    fingerprint=provider_request_fingerprint,
                ),
            ),
        ),
    ).to_dict()
    normalized_prompt = " ".join(str(prompt or "").split())
    recipe = {
        "schema": "campaign_factory.paid_motion_recipe.v1",
        "recipeId": f"paid-motion-recipe-{request_fingerprint[:24]}",
        "motionTask": motion_task,
        "creatorOsModelId": model_id,
        "providerModel": provider_model,
        "campaignRequestFingerprint": request_fingerprint,
        "providerRequestFingerprint": provider_request_fingerprint,
        "sourceSha256": source_hash,
        "promptSha256": hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest(),
    }
    prediction_fingerprint = _canonical_fingerprint(
        {
            "provider": "wavespeed",
            "providerModel": provider_model,
            "predictionId": prediction_id,
            "requestFingerprint": provider_request_fingerprint,
            "inputSha256": source_hash,
            "outputSha256": output_hash,
        }
    )
    execution_evidence = {
        "class": "paid_provider",
        "provider": "wavespeed",
        "providerModel": provider_model,
        "requestFingerprint": provider_request_fingerprint,
        "authorization": {
            "id": str(authorization["authorizationId"]),
            "fingerprint": payload_fingerprint(authorization),
        },
        "authorizationEvidence": {
            "path": str(auth_path),
            "sha256": sha256_file(auth_path),
        },
        "prediction": {
            "id": prediction_id,
            "fingerprint": prediction_fingerprint,
        },
        "providerEvidence": {
            "path": str(evidence_path),
            "sha256": sha256_file(evidence_path),
        },
        "spendRecord": {
            "id": cost_event_id,
            "fingerprint": payload_fingerprint(cost_record),
        },
        "executionReceipt": {
            "id": str(execution_receipt.get("id") or ""),
            "fingerprint": str(execution_receipt.get("fingerprint") or ""),
        },
        "executionReceiptEvidence": {
            "path": str(receipt_path),
            "sha256": str(execution_receipt.get("sha256") or ""),
        },
    }
    return {
        "creatorIdentityProfile": identity,
        "contentIntent": intent,
        "generationRecipe": recipe,
        "modelFingerprint": _canonical_fingerprint(
            {
                "provider": "wavespeed",
                "providerModel": provider_model,
                "creatorOsModelId": model_id,
            }
        ),
        "executionEvidence": execution_evidence,
        "spendRecord": cost_record,
        "campaignRequestFingerprint": request_fingerprint,
        "input": {"path": str(source_path), "sha256": source_hash},
        "output": {"path": str(output_path), "sha256": output_hash},
    }


def _register_review_asset(
    factory: Any,
    *,
    campaign: dict[str, Any],
    source_asset_id: str,
    model_slug: str,
    model_id: str,
    source_path: Path,
    source_hash: str,
    output_path: Path,
    worker_result: dict[str, Any],
    paid: bool,
    motion_task: str = "image_to_video",
    request_fingerprint: str | None = None,
    local_motion_admission: Mapping[str, Any] | None = None,
    prompt: str | None = None,
    pipeline_job_id: str | None = None,
    paid_authorization: Mapping[str, Any] | None = None,
    paid_authorization_path: Path | None = None,
) -> dict[str, Any]:
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise FileNotFoundError(f"motion output missing: {output_path}")
    digest = sha256_file(output_path)
    existing = factory.conn.execute(
        """SELECT * FROM rendered_assets
        WHERE campaign_id = ? AND content_hash = ? ORDER BY created_at, id LIMIT 1""",
        (campaign["id"], digest),
    ).fetchone()
    rendered_id = str(existing["id"]) if existing else new_id("asset")
    now = utc_now()
    caption_hash = factory.domains.publishability.text_hash("")
    generation = worker_result.get("result")
    generation = generation if isinstance(generation, dict) else {}
    audio = generation.get("audio")
    audio = audio if isinstance(audio, dict) else {"mode": "none"}
    audio_mode = str(audio.get("mode") or "none")
    embedded_audio = audio_mode in {"source", "generated"}
    blocking_issues = [
        "contentforge_audit_required",
        "motion_specific_qc_required",
        "human_final_review_required",
        "creative_approval_v2_required",
    ]
    if motion_task == "text_to_video":
        blocking_issues.append("text_to_video_identity_assignment_forbidden")
    if embedded_audio:
        blocking_issues.append("audio_video_alignment_qc_required")
    if model_id == "local_longcat_avatar15_q4_mlx":
        blocking_issues.append("lip_sync_qc_required")
    blocking_issues.append(
        "local_audio_policy_review_required"
        if embedded_audio
        else "native_audio_unresolved"
    )
    if generation.get("aiDisclosureRequired") is True:
        blocking_issues.append("ai_generated_media_disclosure_required")
    source_binding = {"path": str(source_path), "sha256": source_hash}
    video_edit = motion_task in {"video_retake", "video_extend"}
    prompt_only = motion_task == "text_to_video"
    static_fallback_source = None if video_edit or prompt_only else source_binding
    generation_source = None if motion_task == "text_to_video" else source_binding
    paid_generation_evidence = (
        _paid_generation_evidence(
            factory,
            campaign=campaign,
            model_slug=model_slug,
            model_id=model_id,
            motion_task=motion_task,
            source_asset_id=source_asset_id,
            source_path=source_path,
            source_hash=source_hash,
            output_path=output_path,
            output_hash=digest,
            request_fingerprint=request_fingerprint,
            prompt=prompt,
            worker_result=worker_result,
            authorization=paid_authorization,
            authorization_path=paid_authorization_path,
            produced_at=now,
        )
        if paid
        else None
    )
    local_routing_lineage = _local_routing_lineage(local_motion_admission)
    metadata = {
        "schema": "campaign_factory.motion_generation_asset.v1",
        "asset_state": "approved_but_not_publishable",
        "humanReviewRequired": True,
        "creativeApprovalRequired": True,
        "contentforgeAuditRequired": True,
        "captionBurned": False,
        "audioBurned": embedded_audio,
        "embeddedAudioMode": audio_mode,
        "embeddedAudio": audio,
        "nativeAudioResolved": False,
        "source": generation_source,
        "generationInput": generation_source,
        "staticFallbackSource": static_fallback_source,
        "promptSource": source_binding if prompt_only else None,
        "sourceAssetRole": (
            "prompt_provenance_only"
            if prompt_only
            else (
                "generation_input_only"
                if video_edit
                else "generation_input_and_static_fallback"
            )
        ),
        "identityRole": (
            "non_creator_broll"
            if motion_task == "text_to_video"
            else "creator_conditioned"
        ),
        "output": {"path": str(output_path), "sha256": digest},
        "modelId": model_id,
        "requestFingerprint": request_fingerprint,
        "localMotionAdmission": (
            dict(local_motion_admission) if local_motion_admission is not None else None
        ),
        "localMotionRoutingLineage": local_routing_lineage,
        "paidGeneration": paid,
        "paidGenerationEvidence": paid_generation_evidence,
        "worker": worker_result,
        "publishability": {
            "status": "blocked",
            "asset_state": "approved_but_not_publishable",
            "blockingIssues": blocking_issues,
        },
    }
    source_clip = "text_prompt_only" if prompt_only else source_path.name
    outcome_context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": caption_hash,
        "caption_bank": "none",
        "caption_banks": [],
        "creator_mix": model_slug,
        "creator_model": model_slug,
        "frame_type": "generated_motion",
        "length_class": "short",
        "format_class": "video",
        "caption_fit_version": "none",
        "suitability_decision": "review_required",
        "suitability_reason": "generated motion requires ContentForge and human review",
        "source_clip": source_clip,
    }
    blob_id = f"blob_{digest.lower()}"
    attempt_id = new_id("generation_attempt")
    lineage_edge_id = new_id("generation_edge")
    attempted_output_path = str(output_path)
    duplicate_disposition = "canonical_output"
    remove_duplicate = False
    if existing:
        canonical_path = Path(str(existing["output_path"])).expanduser().resolve()
        if not canonical_path.is_file():
            raise FileNotFoundError(
                f"canonical generation output missing for digest {digest}: "
                f"{canonical_path}"
            )
        if sha256_file(canonical_path) != digest:
            raise RuntimeError(
                f"canonical generation output hash mismatch for digest {digest}: "
                f"{canonical_path}"
            )
        if output_path.resolve() == canonical_path:
            duplicate_disposition = "reused_canonical_path"
        else:
            duplicate_disposition = "removed_unreferenced_duplicate"
            remove_duplicate = True
    normalized_prompt = " ".join(str(prompt or "").split())
    prompt_sha256 = (
        hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest()
        if normalized_prompt
        else None
    )
    admission_fingerprint = None
    if local_motion_admission is not None:
        admission_fingerprint = (
            str(local_motion_admission.get("admissionFingerprint") or "") or None
        )
    lineage = {
        "schema": "campaign_factory.generation_lineage_edge.v1",
        "modelId": model_id,
        "motionTask": motion_task,
        "requestFingerprint": request_fingerprint,
        "promptSha256": prompt_sha256,
        "source": {
            "assetId": source_asset_id,
            "sha256": source_hash,
            "role": ("prompt_provenance_only" if prompt_only else "generation_input"),
            "promptTaskFingerprint": (
                _text_prompt_task_fingerprint(normalized_prompt)
                if prompt_only
                else None
            ),
        },
        "output": {"blobId": blob_id, "sha256": digest},
        "admissionFingerprint": admission_fingerprint,
        "localMotionRouting": local_routing_lineage,
    }
    with factory.conn:
        factory.conn.execute(
            """
            INSERT OR IGNORE INTO generation_output_blobs
            (id, content_sha256, byte_size, media_type, created_at)
            VALUES (?, ?, ?, 'video', ?)
            """,
            (blob_id, digest.lower(), output_path.stat().st_size, now),
        )
        if not existing:
            factory.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path,
                 filename, media_type, content_surface, caption, caption_hash, caption_bank,
                 caption_banks_json, creator_mix, creator_model, frame_type, length_class,
                 format_class, caption_fit_version, suitability_decision, suitability_reason,
                 source_clip, caption_outcome_context_json, caption_generation_json, recipe,
                 target_ratio, metadata_json, audit_status, review_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', '', ?, 'none', '[]', ?, ?,
                        'generated_motion', 'short', 'video', 'none', 'review_required', ?, ?,
                        ?, ?, ?, '9:16', ?, 'pending', 'review_ready', ?, ?)
                """,
                (
                    rendered_id,
                    campaign["id"],
                    source_asset_id,
                    digest,
                    str(output_path),
                    str(output_path),
                    output_path.name,
                    caption_hash,
                    model_slug,
                    model_slug,
                    outcome_context["suitability_reason"],
                    source_clip,
                    json.dumps(outcome_context, sort_keys=True),
                    json.dumps(sanitize_for_storage(metadata), sort_keys=True),
                    model_id,
                    json.dumps(sanitize_for_storage(metadata), sort_keys=True),
                    now,
                    now,
                ),
            )
        factory.conn.execute(
            """
            INSERT INTO generation_attempts
            (id, campaign_id, pipeline_job_id, source_asset_id, rendered_asset_id,
             output_blob_id, request_fingerprint, model_id, motion_task, prompt_sha256,
             source_sha256, admission_fingerprint, input_json, worker_result_json,
             attempted_output_path, duplicate_disposition, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                campaign["id"],
                pipeline_job_id,
                source_asset_id,
                rendered_id,
                blob_id,
                request_fingerprint,
                model_id,
                motion_task,
                prompt_sha256,
                None if prompt_only else source_hash,
                admission_fingerprint,
                json.dumps(
                    sanitize_for_storage(
                        {
                            "sourcePath": (None if prompt_only else str(source_path)),
                            "sourceSha256": None if prompt_only else source_hash,
                            "promptSource": (
                                {
                                    "assetId": source_asset_id,
                                    "path": str(source_path),
                                    "sha256": source_hash,
                                    "promptTaskFingerprint": (
                                        _text_prompt_task_fingerprint(normalized_prompt)
                                    ),
                                }
                                if prompt_only
                                else None
                            ),
                            "motionTask": motion_task,
                        }
                    ),
                    sort_keys=True,
                ),
                json.dumps(sanitize_for_storage(worker_result), sort_keys=True),
                attempted_output_path,
                duplicate_disposition,
                now,
            ),
        )
        factory.conn.execute(
            """
            INSERT INTO generation_lineage_edges
            (id, generation_attempt_id, source_asset_id, rendered_asset_id,
             output_blob_id, relation, lineage_json, created_at)
            VALUES (?, ?, ?, ?, ?, 'generated_output', ?, ?)
            """,
            (
                lineage_edge_id,
                attempt_id,
                source_asset_id,
                rendered_id,
                blob_id,
                json.dumps(sanitize_for_storage(lineage), sort_keys=True),
                now,
            ),
        )
        if remove_duplicate:
            output_path.unlink()
    return dict(
        factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
        ).fetchone()
    )
