"""Campaign-owned orchestration for local Wan and WaveSpeed motion workers."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .core import (
    new_id,
    reel_factory_python,
    sanitize_for_storage,
    sha256_file,
    slugify,
)
from .generation_execution_plan import (
    GenerationExecutionPlan,
    authorize_paid_generation,
    require_generation_execution_mode,
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
    still_path: Path,
    prompt: str,
    model_id: str,
    duration_seconds: int | None,
    resolution: str | None,
    seed: int,
    steps: int,
    dry_run: bool,
    apply: bool,
    workspace: Path | None = None,
    paid_confirmation: bool = False,
    max_usd: float | None = None,
    audio_path: Path | None = None,
    last_image_path: Path | None = None,
    reference_image_paths: tuple[Path, ...] = (),
    reference_video_paths: tuple[Path, ...] = (),
    enable_prompt_expansion: bool = False,
    shot_type: str = "single",
    local_wan_model_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate one review-only motion asset with a preserved static fallback."""
    expected_mode = execution_plan.creative_mode
    if expected_mode not in {"local_wan", "best_motion"}:
        raise PermissionError(f"{expected_mode} does not authorize motion generation")
    require_generation_execution_mode(execution_plan, expected_mode)
    if apply == dry_run:
        raise ValueError("choose exactly one of dry_run or apply")
    still = Path(still_path).expanduser().resolve()
    if not still.is_file():
        raise FileNotFoundError(f"accepted still not found: {still}")
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

    campaign = factory.domains.campaign_by_slug(campaign_slug)
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    dirs = factory.domains.campaign_dirs(model_slug, campaign["slug"])
    source_hash = sha256_file(still)
    output_path = dirs["rendered"] / (
        f"{slugify(still.stem)}_{source_hash[:12]}_{slugify(model_id)}_{seed}.mp4"
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
        last_image_path=last_image_path,
        reference_image_paths=reference_image_paths,
        reference_video_paths=reference_video_paths,
        enable_prompt_expansion=enable_prompt_expansion,
        shot_type=shot_type,
        local_wan_model_dir=local_wan_model_dir,
        dry_run=True,
    )
    pipeline_job = factory.domains.events.create_pipeline_job(
        "motion_generation",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "modelId": model_id,
            "sourcePath": str(still),
            "sourceSha256": source_hash,
            "outputPath": str(output_path),
            "dryRun": dry_run,
            "apply": apply,
            "paidGeneration": paid,
        },
    )
    factory.domains.events.start_pipeline_job(pipeline_job["id"])
    try:
        worker_plan = _invoke_worker(worker_command, factory=factory)
        scope = worker_plan.get("spendScope")
        static_fallback = run_static_mp4_stage(
            factory,
            campaign_slug=campaign_slug,
            still_path=still,
            duration_seconds=float(duration_seconds or 6),
            dry_run=dry_run,
            apply=apply,
        )
        authorization = None
        worker_result = worker_plan
        if apply:
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
                last_image_path=last_image_path,
                reference_image_paths=reference_image_paths,
                reference_video_paths=reference_video_paths,
                enable_prompt_expansion=enable_prompt_expansion,
                shot_type=shot_type,
                local_wan_model_dir=local_wan_model_dir,
                dry_run=False,
            )
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
            worker_result = _invoke_worker(apply_command, factory=factory)
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
        registered_asset = None
        if apply:
            source_asset_id = _static_source_asset_id(static_fallback)
            registered_asset = _register_review_asset(
                factory,
                campaign=campaign,
                source_asset_id=source_asset_id,
                model_slug=model_slug,
                model_id=model_id,
                source_path=still,
                source_hash=source_hash,
                output_path=output_path,
                worker_result=worker_result,
                paid=paid,
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
            "humanReviewRequired": True,
            "schedulingAllowed": False,
            "publishingAllowed": False,
        }
        factory.domains.events.finish_pipeline_job(
            pipeline_job["id"], sanitize_for_storage(result)
        )
        return result
    except Exception as exc:
        factory.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _worker_command(
    factory: Any,
    *,
    model_id: str,
    prompt: str,
    still: Path,
    output_path: Path,
    campaign_slug: str,
    duration_seconds: int | None,
    resolution: str | None,
    seed: int,
    steps: int,
    audio_path: Path | None,
    last_image_path: Path | None,
    reference_image_paths: tuple[Path, ...],
    reference_video_paths: tuple[Path, ...],
    enable_prompt_expansion: bool,
    shot_type: str,
    local_wan_model_dir: Path | None,
    dry_run: bool,
) -> list[str]:
    command = [
        reel_factory_python(factory.settings.reel_factory_root),
        "-m",
        "reel_factory.motion_generate",
        "--model",
        model_id,
        "--prompt",
        prompt,
        "--out",
        str(output_path),
        "--campaign",
        campaign_slug,
        "--cohort-id",
        "creator_os_motion",
        "--seed",
        str(seed),
        "--steps",
        str(steps),
        "--shot-type",
        shot_type,
        "--dry-run" if dry_run else "--apply",
    ]
    if model_id == "wavespeed_wan27_reference":
        command.extend(["--reference-image", str(still)])
    else:
        command.extend(["--image", str(still)])
    for flag, value in (
        ("--duration", duration_seconds),
        ("--resolution", resolution),
        ("--audio", audio_path),
        ("--last-image", last_image_path),
        ("--model-dir", local_wan_model_dir),
    ):
        if value is not None:
            command.extend([flag, str(value)])
    for path in reference_image_paths:
        command.extend(["--reference-image", str(path)])
    for path in reference_video_paths:
        command.extend(["--reference-video", str(path)])
    if enable_prompt_expansion:
        command.append("--enable-prompt-expansion")
    return command


def _invoke_worker(command: list[str], *, factory: Any) -> dict[str, Any]:
    proc = subprocess.run(
        command,
        cwd=factory.settings.reel_factory_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=60 * 60 * 6,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr[-3000:] or proc.stdout[-3000:] or "motion worker failed"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("motion worker returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema") != (
        "reel_factory.motion_generation_result.v1"
    ):
        raise RuntimeError("motion worker returned the wrong schema")
    return payload


def _static_source_asset_id(static_fallback: dict[str, Any]) -> str:
    registered = static_fallback.get("registeredAsset")
    if not isinstance(registered, dict) or not registered.get("source_asset_id"):
        raise RuntimeError("static fallback omitted source asset identity")
    return str(registered["source_asset_id"])


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
) -> dict[str, Any]:
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise FileNotFoundError(f"motion output missing: {output_path}")
    digest = sha256_file(output_path)
    existing = factory.conn.execute(
        """SELECT * FROM rendered_assets
        WHERE campaign_id = ? AND content_hash = ? ORDER BY created_at, id LIMIT 1""",
        (campaign["id"], digest),
    ).fetchone()
    if existing:
        return dict(existing)
    rendered_id = new_id("asset")
    now = utc_now()
    caption_hash = factory.domains.publishability.text_hash("")
    metadata = {
        "schema": "campaign_factory.motion_generation_asset.v1",
        "asset_state": "approved_but_not_publishable",
        "humanReviewRequired": True,
        "contentforgeAuditRequired": True,
        "captionBurned": False,
        "audioBurned": False,
        "nativeAudioResolved": False,
        "source": {"path": str(source_path), "sha256": source_hash},
        "output": {"path": str(output_path), "sha256": digest},
        "modelId": model_id,
        "paidGeneration": paid,
        "worker": worker_result,
        "publishability": {
            "status": "blocked",
            "asset_state": "approved_but_not_publishable",
            "blockingIssues": [
                "contentforge_audit_required",
                "human_final_review_required",
                "native_audio_unresolved",
            ],
        },
    }
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
        "source_clip": source_path.name,
    }
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
            source_path.name,
            json.dumps(outcome_context, sort_keys=True),
            json.dumps(sanitize_for_storage(metadata), sort_keys=True),
            model_id,
            json.dumps(sanitize_for_storage(metadata), sort_keys=True),
            now,
            now,
        ),
    )
    factory.conn.commit()
    return dict(
        factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
        ).fetchone()
    )
