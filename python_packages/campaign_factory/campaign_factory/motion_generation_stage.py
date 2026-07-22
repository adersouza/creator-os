"""Campaign-owned orchestration for local MLX and WaveSpeed motion workers."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
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
    steps: int | None,
    dry_run: bool,
    apply: bool,
    workspace: Path | None = None,
    paid_confirmation: bool = False,
    max_usd: float | None = None,
    audio_path: Path | None = None,
    generate_audio: bool = False,
    last_image_path: Path | None = None,
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
    if (benchmark_recipe is None) != (analyzer_registry is None):
        raise ValueError("benchmark evidence records must be provided together")
    if paid and benchmark_recipe is not None:
        raise ValueError("benchmark evidence applies only to local models")

    campaign = factory.domains.campaign_by_slug(campaign_slug)
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    dirs = factory.domains.campaign_dirs(model_slug, campaign["slug"])
    source_hash = sha256_file(still)
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
    )
    output_path = dirs["rendered"] / (
        f"{slugify(still.stem)}_{source_hash[:12]}_{slugify(model_id)}_"
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
                generate_audio=generate_audio,
                last_image_path=last_image_path,
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
                motion_task=motion_task,
                request_fingerprint=request_fingerprint,
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
    steps: int | None,
    audio_path: Path | None,
    generate_audio: bool,
    last_image_path: Path | None,
    reference_image_paths: tuple[Path, ...],
    reference_video_paths: tuple[Path, ...],
    enable_prompt_expansion: bool,
    shot_type: str,
    local_model_dir: Path | None,
    motion_task: str,
    motion_lora_path: Path | None,
    motion_lora_strength: float,
    benchmark_recipe: Mapping[str, Any] | None = None,
    analyzer_registry: Mapping[str, Any] | None = None,
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
        "--shot-type",
        shot_type,
        "--dry-run" if dry_run else "--apply",
    ]
    if model_id.startswith("local_"):
        command.extend(["--task", motion_task])
    if model_id == "wavespeed_wan27_reference":
        command.extend(["--reference-image", str(still)])
    elif motion_task != "text_to_video":
        command.extend(["--image", str(still)])
    for flag, value in (
        ("--steps", steps),
        ("--duration", duration_seconds),
        ("--resolution", resolution),
        ("--audio", audio_path),
        ("--last-image", last_image_path),
        ("--model-dir", local_model_dir),
        ("--lora", motion_lora_path),
    ):
        if value is not None:
            command.extend([flag, str(value)])
    if motion_lora_strength != 1.0:
        command.extend(["--lora-strength", str(motion_lora_strength)])
    for path in reference_image_paths:
        command.extend(["--reference-image", str(path)])
    for path in reference_video_paths:
        command.extend(["--reference-video", str(path)])
    if enable_prompt_expansion:
        command.append("--enable-prompt-expansion")
    if generate_audio:
        command.append("--generate-audio")
    if benchmark_recipe is not None and analyzer_registry is not None:
        command.extend(
            [
                "--benchmark-recipe-json",
                json.dumps(
                    dict(benchmark_recipe),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "--analyzer-registry-json",
                json.dumps(
                    dict(analyzer_registry),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ]
        )
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


def _motion_request_fingerprint(
    *,
    model_id: str,
    prompt: str,
    still: Path,
    duration_seconds: int | None,
    resolution: str | None,
    seed: int,
    steps: int | None,
    audio_path: Path | None,
    generate_audio: bool,
    last_image_path: Path | None,
    reference_image_paths: tuple[Path, ...],
    reference_video_paths: tuple[Path, ...],
    enable_prompt_expansion: bool,
    shot_type: str,
    local_model_dir: Path | None,
    motion_task: str,
    motion_lora_path: Path | None,
    motion_lora_strength: float,
    benchmark_recipe: Mapping[str, Any] | None = None,
    analyzer_registry: Mapping[str, Any] | None = None,
) -> str:
    def media(path: Path | None) -> dict[str, str] | None:
        if path is None:
            return None
        resolved = Path(path).expanduser().resolve()
        return {"path": str(resolved), "sha256": sha256_file(resolved)}

    payload = {
        "modelId": model_id,
        "prompt": prompt,
        "still": media(still),
        "durationSeconds": duration_seconds,
        "resolution": resolution,
        "seed": seed,
        "steps": steps,
        "audio": media(audio_path),
        "generateAudio": generate_audio,
        "lastImage": media(last_image_path),
        "referenceImages": [media(path) for path in reference_image_paths],
        "referenceVideos": [media(path) for path in reference_video_paths],
        "enablePromptExpansion": enable_prompt_expansion,
        "shotType": shot_type,
        "localModelDir": (
            str(Path(local_model_dir).expanduser().resolve())
            if local_model_dir is not None
            else None
        ),
        "motionTask": motion_task,
        "lora": media(motion_lora_path),
        "loraStrength": motion_lora_strength,
        "benchmarkRecipeFingerprint": (
            hashlib.sha256(
                json.dumps(
                    dict(benchmark_recipe),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            if benchmark_recipe is not None
            else None
        ),
        "analyzerRegistryFingerprint": (
            hashlib.sha256(
                json.dumps(
                    dict(analyzer_registry),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            if analyzer_registry is not None
            else None
        ),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    motion_task: str = "image_to_video",
    request_fingerprint: str | None = None,
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
    fallback_source = {"path": str(source_path), "sha256": source_hash}
    generation_source = None if motion_task == "text_to_video" else fallback_source
    metadata = {
        "schema": "campaign_factory.motion_generation_asset.v1",
        "asset_state": "approved_but_not_publishable",
        "humanReviewRequired": True,
        "contentforgeAuditRequired": True,
        "captionBurned": False,
        "audioBurned": embedded_audio,
        "embeddedAudioMode": audio_mode,
        "embeddedAudio": audio,
        "nativeAudioResolved": False,
        "source": generation_source,
        "generationInput": generation_source,
        "staticFallbackSource": fallback_source,
        "sourceAssetRole": (
            "static_fallback_only"
            if motion_task == "text_to_video"
            else "generation_input_and_static_fallback"
        ),
        "identityRole": (
            "non_creator_broll"
            if motion_task == "text_to_video"
            else "creator_conditioned"
        ),
        "output": {"path": str(output_path), "sha256": digest},
        "modelId": model_id,
        "requestFingerprint": request_fingerprint,
        "paidGeneration": paid,
        "worker": worker_result,
        "publishability": {
            "status": "blocked",
            "asset_state": "approved_but_not_publishable",
            "blockingIssues": blocking_issues,
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
        "source_clip": (
            "text_prompt_only" if motion_task == "text_to_video" else source_path.name
        ),
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
