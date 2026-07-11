from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .contracts import validate_front_generation_plan
from .core import (
    new_id,
    reel_factory_python,
    sanitize_for_storage,
    sha256_file,
    slugify,
)
from .cost_tracker import PROVIDER_PRICING
from .kling_selection_stage import validate_kling_selection_receipt
from .persistence import utc_now
from .static_mp4_stage import run_static_mp4_stage
from .variation_stage import run_variation_stage

SCHEMA = "campaign_factory.front_generation_plan.v1"
DEFAULT_IMAGE_COST_USD = PROVIDER_PRICING["higgsfield"]["per_generation"]
DEFAULT_KLING_COST_USD = PROVIDER_PRICING["kling"]["per_generation"]
ACCEPTED_STILL_PLACEHOLDER = "<accepted_still_path_after_review>"


def run_front_generation_stage(
    factory: Any,
    *,
    campaign_slug: str,
    reference_image_path: Path,
    creator: str | None = None,
    soul_id: str | None = None,
    soul_name: str | None = None,
    scene_type: str = "room_selfie",
    animation_mode: str = "kling",
    dry_run: bool = True,
    apply: bool = False,
    enable_paid_generation: bool = False,
    budget_cap_usd: float | None = None,
    accepted_still_path: Path | None = None,
    kling_selection_receipt_path: Path | None = None,
    estimated_image_cost_usd: float = DEFAULT_IMAGE_COST_USD,
    estimated_video_cost_usd: float = DEFAULT_KLING_COST_USD,
    wait: bool = False,
    download: bool = False,
    enable_variation: bool = False,
    variation_preset: str = "ig_subtle",
) -> dict[str, Any]:
    """Plan or submit the paid front-generation path behind fail-closed guards."""
    if animation_mode not in {"kling", "motion_edit"}:
        raise ValueError("animation_mode must be kling or motion_edit")
    if not creator and not soul_id and not soul_name:
        raise ValueError("creator, soul_id, or soul_name is required")
    if kling_selection_receipt_path is not None and accepted_still_path is None:
        raise ValueError("Kling selection receipt requires an accepted still")
    campaign = factory.campaign_by_slug(campaign_slug)
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    reference_image = Path(reference_image_path).expanduser().resolve()
    if not reference_image.exists() or not reference_image.is_file():
        raise FileNotFoundError(f"reference image not found: {reference_image}")
    stem = slugify(reference_image.stem)
    reference_pattern = factory.active_reference_pattern_for_campaign(campaign["id"])
    prompt_path = _write_prompt_pack(
        dirs["reel_inputs"] / f"{stem}.front_generation_prompt.json",
        scene_type=scene_type,
        reference_pattern=reference_pattern,
    )
    projected_cost = _projected_cost(
        animation_mode=animation_mode,
        accepted_still_path=accepted_still_path,
        kling_selection_receipt_path=kling_selection_receipt_path,
        estimated_image_cost_usd=estimated_image_cost_usd,
        estimated_video_cost_usd=estimated_video_cost_usd,
    )
    budget_status = _budget_status(
        projected_cost_usd=projected_cost,
        budget_cap_usd=budget_cap_usd,
    )
    pipeline_job = factory.create_pipeline_job(
        "front_generation",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "referenceImagePath": str(reference_image),
            "animationMode": animation_mode,
            "dryRun": dry_run,
            "apply": apply,
            "enablePaidGeneration": enable_paid_generation,
            "budgetCapUsd": budget_cap_usd,
            "acceptedStillPath": str(accepted_still_path)
            if accepted_still_path
            else None,
            "klingSelectionReceiptPath": str(kling_selection_receipt_path)
            if kling_selection_receipt_path
            else None,
            "wait": wait,
            "download": download,
            "enableVariation": enable_variation,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        if apply and not dry_run and projected_cost > 0:
            _enforce_paid_generation_guard(
                enable_paid_generation=enable_paid_generation,
                budget_cap_usd=budget_cap_usd,
                projected_cost_usd=projected_cost,
            )
        stages = _build_stages(
            factory,
            campaign_slug=campaign_slug,
            reference_image=reference_image,
            stem=stem,
            creator=creator,
            soul_id=soul_id,
            soul_name=soul_name,
            animation_mode=animation_mode,
            prompt_path=prompt_path,
            accepted_still_path=accepted_still_path,
            kling_selection_receipt_path=kling_selection_receipt_path,
            dry_run=dry_run or not apply,
            budget_cap_usd=budget_cap_usd,
            estimated_image_cost_usd=estimated_image_cost_usd,
            estimated_video_cost_usd=estimated_video_cost_usd,
            wait=wait,
            download=download,
        )
        plan = {
            "schema": SCHEMA,
            "campaign": campaign_slug,
            "referenceImagePath": str(reference_image),
            "soul": {
                "creator": creator,
                "soulId": soul_id,
                "soulName": soul_name,
            },
            "animationMode": animation_mode,
            "dryRun": dry_run or not apply,
            "paidGenerationEnabled": bool(enable_paid_generation),
            "projectedCostUsd": round(projected_cost, 4),
            "budgetCapUsd": budget_cap_usd,
            "budgetStatus": budget_status,
            "humanReviewRequired": True,
            "publishingAllowed": False,
            "stages": stages,
        }
        validate_front_generation_plan(plan)
        static_result = _stage_result(stages, "static_mp4")
        registered_static_asset = static_result.get("registeredAsset")
        registered_asset = None
        variation = None
        if apply and not dry_run and accepted_still_path and animation_mode == "kling":
            video_result = _stage_result(stages, "kling_video")
            video_path = _local_video_path(video_result)
            if video_path is not None:
                registered_asset = _register_kling_rendered_asset(
                    factory,
                    campaign=campaign,
                    source_asset=_source_asset_for_campaign(factory, campaign["id"]),
                    video_path=video_path,
                    video_result=video_result,
                    plan=plan,
                    accepted_still_path=Path(accepted_still_path)
                    .expanduser()
                    .resolve(),
                    estimated_video_cost_usd=estimated_video_cost_usd,
                    kling_selection_receipt=video_result.get("klingSelectionReceipt"),
                )
                if enable_variation:
                    variation = run_variation_stage(
                        factory,
                        campaign_slug=campaign_slug,
                        preset_name=variation_preset,
                        rendered_asset_ids=[registered_asset["id"]],
                        dry_run=True,
                    )
            elif enable_variation:
                raise ValueError(
                    "front generation variation requires a downloaded local Kling video; pass --wait --download"
                )
        result = {
            "schema": "campaign_factory.front_generation_stage_run.v1",
            "campaign": campaign_slug,
            "dryRun": dry_run or not apply,
            "apply": bool(apply and not dry_run),
            "plan": plan,
            "registeredStaticAsset": registered_static_asset,
            "registeredAsset": registered_asset,
            "variation": variation,
            "promptPath": str(prompt_path),
            "pipelineJobId": pipeline_job["id"],
        }
        factory.finish_pipeline_job(pipeline_job["id"], sanitize_for_storage(result))
        return result
    except Exception as exc:
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _projected_cost(
    *,
    animation_mode: str,
    accepted_still_path: Path | None,
    kling_selection_receipt_path: Path | None,
    estimated_image_cost_usd: float,
    estimated_video_cost_usd: float,
) -> float:
    total = 0.0 if accepted_still_path else estimated_image_cost_usd
    if animation_mode == "kling" and kling_selection_receipt_path is not None:
        total += estimated_video_cost_usd
    return total


def _budget_status(
    *,
    projected_cost_usd: float,
    budget_cap_usd: float | None,
) -> str:
    if projected_cost_usd <= 0:
        return "not_required"
    if budget_cap_usd is None:
        return "missing_cap"
    if projected_cost_usd > budget_cap_usd:
        return "exceeds_cap"
    return "within_cap"


def _enforce_paid_generation_guard(
    *,
    enable_paid_generation: bool,
    budget_cap_usd: float | None,
    projected_cost_usd: float,
) -> None:
    if not enable_paid_generation:
        raise PermissionError("paid generation requires --enable-paid-generation")
    if budget_cap_usd is None:
        raise ValueError("paid generation requires --budget-cap-usd")
    if projected_cost_usd > budget_cap_usd:
        raise ValueError("projected generation cost exceeds --budget-cap-usd")


def _build_stages(
    factory: Any,
    *,
    campaign_slug: str,
    reference_image: Path,
    stem: str,
    creator: str | None,
    soul_id: str | None,
    soul_name: str | None,
    animation_mode: str,
    prompt_path: Path,
    accepted_still_path: Path | None,
    kling_selection_receipt_path: Path | None,
    dry_run: bool,
    budget_cap_usd: float | None,
    estimated_image_cost_usd: float,
    estimated_video_cost_usd: float,
    wait: bool,
    download: bool,
) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    if accepted_still_path is None:
        image_result = _invoke_generate_assets(
            factory,
            [
                "reference-image-dry-run" if dry_run else "reference-image",
                "--reference",
                str(reference_image),
                "--stem",
                stem,
                "--estimated-cost-usd",
                str(estimated_image_cost_usd),
                *_soul_args(creator=creator, soul_id=soul_id, soul_name=soul_name),
                *_runtime_generation_args(
                    wait=wait, download=download, dry_run=dry_run
                ),
            ],
            budget_cap_usd=budget_cap_usd,
        )
        stages.append(
            {
                "name": "soul_reference_image",
                "status": "planned" if dry_run else "submitted",
                "paid": True,
                "estimatedCostUsd": estimated_image_cost_usd,
                "commands": image_result.get("commands") or [],
                "result": image_result,
            }
        )
        stages.append(
            {
                "name": "still_accept_gate",
                "status": "waiting_for_review",
                "paid": False,
                "estimatedCostUsd": 0,
                "commands": [],
                "reason": "Kling or motion-edit waits for an accepted still.",
            }
        )
        stages.append(
            {
                "name": "static_mp4",
                "status": "blocked",
                "paid": False,
                "estimatedCostUsd": 0,
                "commands": [],
                "reason": "Static MP4 requires the accepted still path.",
            }
        )
        if animation_mode == "motion_edit":
            stages.append(
                {
                    "name": "motion_edit",
                    "status": "blocked",
                    "paid": False,
                    "estimatedCostUsd": 0,
                    "commands": [],
                    "reason": "Motion edit requires the accepted still path.",
                }
            )
        else:
            stages.append(
                {
                    "name": "kling_video",
                    "status": "blocked",
                    "paid": True,
                    "estimatedCostUsd": estimated_video_cost_usd,
                    "commands": [],
                    "reason": (
                        "Kling requires an accepted static fallback, safe audit, "
                        "human approval, and best-only selection receipt."
                    ),
                }
            )
        return stages

    accepted_still = Path(accepted_still_path).expanduser().resolve()
    if not accepted_still.exists() or not accepted_still.is_file():
        raise FileNotFoundError(f"accepted still not found: {accepted_still}")
    stages.append(
        {
            "name": "soul_reference_image",
            "status": "skipped",
            "paid": True,
            "estimatedCostUsd": 0,
            "commands": [],
            "reason": "Accepted still was supplied.",
        }
    )
    stages.append(
        {
            "name": "still_accept_gate",
            "status": "planned" if dry_run else "submitted",
            "paid": False,
            "estimatedCostUsd": 0,
            "commands": [],
        }
    )
    static_result = run_static_mp4_stage(
        factory,
        campaign_slug=campaign_slug,
        still_path=accepted_still,
        dry_run=dry_run,
        apply=not dry_run,
    )
    stages.append(
        {
            "name": "static_mp4",
            "status": "planned" if dry_run else "submitted",
            "paid": False,
            "estimatedCostUsd": 0,
            "commands": [static_result["render"].get("ffmpegCommand") or []],
            "result": static_result,
        }
    )
    if animation_mode == "motion_edit":
        stages.append(
            {
                "name": "motion_edit",
                "status": "planned",
                "paid": False,
                "estimatedCostUsd": 0,
                "commands": [],
                "reason": "Run animation motion-edit separately after this paid still gate.",
            }
        )
    else:
        if kling_selection_receipt_path is None:
            stages.append(
                {
                    "name": "kling_video",
                    "status": "blocked",
                    "paid": True,
                    "estimatedCostUsd": estimated_video_cost_usd,
                    "commands": [],
                    "reason": (
                        "Kling is blocked until this static candidate wins an "
                        "approved multi-candidate ranking batch."
                    ),
                }
            )
            return stages
        selection = validate_kling_selection_receipt(
            factory,
            receipt_path=kling_selection_receipt_path,
            accepted_still_path=accepted_still,
            selected_static_asset=static_result.get("registeredAsset"),
        )
        video_result = _invoke_generate_assets(
            factory,
            [
                "video-dry-run" if dry_run else "video",
                "--prompt-json",
                str(prompt_path),
                "--stem",
                stem,
                "--start-image",
                str(accepted_still),
                "--campaign",
                campaign_slug,
                "--estimated-cost-usd",
                str(estimated_video_cost_usd),
                *_soul_args(creator=creator, soul_id=soul_id, soul_name=soul_name),
                *_runtime_generation_args(
                    wait=wait, download=download, dry_run=dry_run
                ),
            ],
            budget_cap_usd=budget_cap_usd,
        )
        video_result["klingSelectionReceipt"] = selection
        stages.append(
            {
                "name": "kling_video",
                "status": "planned" if dry_run else "submitted",
                "paid": True,
                "estimatedCostUsd": estimated_video_cost_usd,
                "commands": video_result.get("commands") or [],
                "result": video_result,
            }
        )
    return stages


def _invoke_generate_assets(
    factory: Any, args: list[str], *, budget_cap_usd: float | None
) -> dict[str, Any]:
    cmd = [
        reel_factory_python(factory.settings.reel_factory_root),
        "generate_assets.py",
        *args,
        "--root",
        str(factory.settings.reel_factory_root),
    ]
    env = os.environ.copy()
    if budget_cap_usd is not None:
        env.setdefault("HIGGSFIELD_DAILY_BUDGET_USD", str(budget_cap_usd))
        env.setdefault("HIGGSFIELD_RUN_MAX_ASSETS", "2")
        env.setdefault("HIGGSFIELD_MIN_BALANCE_USD", "0")
    proc = subprocess.run(
        cmd,
        cwd=factory.settings.reel_factory_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr[-2000:] or proc.stdout[-2000:] or "generate_assets failed"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"generate_assets returned invalid JSON: {proc.stdout[-500:]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("generate_assets returned non-object JSON")
    return payload


def _soul_args(
    *, creator: str | None, soul_id: str | None, soul_name: str | None
) -> list[str]:
    args: list[str] = []
    if creator:
        args += ["--creator", creator]
    if soul_id:
        args += ["--soul-id", soul_id]
    if soul_name:
        args += ["--soul-name", soul_name]
    return args


def _runtime_generation_args(*, wait: bool, download: bool, dry_run: bool) -> list[str]:
    args: list[str] = []
    if wait:
        args.append("--wait")
    if download and not dry_run:
        args.append("--download")
    return args


def _stage_result(stages: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for stage in stages:
        if stage.get("name") == name and isinstance(stage.get("result"), dict):
            return stage["result"]
    return {}


def _local_video_path(video_result: dict[str, Any]) -> Path | None:
    if not video_result.get("ok", False):
        return None
    lineage = video_result.get("lineage")
    if not isinstance(lineage, dict):
        return None
    assets = lineage.get("assets")
    if not isinstance(assets, dict):
        return None
    local_paths = assets.get("localPaths")
    if not isinstance(local_paths, dict):
        return None
    for key in ("video", "output", "mp4"):
        value = local_paths.get(key)
        if not value:
            continue
        path = Path(str(value)).expanduser().resolve()
        if path.exists() and path.is_file():
            return path
    return None


def _register_kling_rendered_asset(
    factory: Any,
    *,
    campaign: dict[str, Any],
    source_asset: dict[str, Any],
    video_path: Path,
    video_result: dict[str, Any],
    plan: dict[str, Any],
    accepted_still_path: Path,
    estimated_video_cost_usd: float,
    kling_selection_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    if video_path.stat().st_size <= 0:
        raise FileNotFoundError(f"Kling video output is empty: {video_path}")
    rendered_id = new_id("asset")
    digest = sha256_file(video_path)
    now = utc_now()
    lineage_path = video_result.get("path") or video_result.get("lineage_path")
    caption_generation = {
        "schema": "campaign_factory.caption_generation.v1",
        "workflow": "front_generation_soul_to_kling",
        "animationMode": "kling",
        "paidGeneration": True,
        "estimatedCostUsd": estimated_video_cost_usd,
        "frontGenerationPlan": plan,
        "generatedAssetLineagePath": lineage_path,
        "acceptedStillPath": str(accepted_still_path),
        "klingSelectionReceipt": kling_selection_receipt,
        "humanReviewRequired": True,
    }
    metadata = {
        "frontGeneration": {
            "animationMode": "kling",
            "paidGeneration": True,
            "estimatedCostUsd": estimated_video_cost_usd,
            "acceptedStillPath": str(accepted_still_path),
            "generatedAssetLineagePath": lineage_path,
            "klingSelectionReceipt": kling_selection_receipt,
        },
        "humanReviewRequired": True,
    }
    factory.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         media_type, content_surface, caption_generation_json, recipe, target_ratio, metadata_json,
         audit_status, review_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', ?, 'kling_front_generation', '9:16', ?, 'pending', 'review_ready', ?, ?)
        """,
        (
            rendered_id,
            campaign["id"],
            source_asset["id"],
            digest,
            str(video_path),
            str(video_path),
            video_path.name,
            json.dumps(
                sanitize_for_storage(caption_generation),
                ensure_ascii=False,
                sort_keys=True,
            ),
            json.dumps(
                sanitize_for_storage(metadata), ensure_ascii=False, sort_keys=True
            ),
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


def _source_asset_for_campaign(factory: Any, campaign_id: str) -> dict[str, Any]:
    row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? ORDER BY created_at, id LIMIT 1",
        (campaign_id,),
    ).fetchone()
    if not row:
        raise ValueError(
            "campaign must have at least one source asset before front-generation registration"
        )
    return dict(row)


def _write_prompt_pack(
    path: Path, *, scene_type: str, reference_pattern: dict[str, Any] | None = None
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = scene_type.strip().replace("_", " ") or "room selfie"
    guidance = _learned_prompt_guidance(reference_pattern)
    guidance_text = _learned_prompt_guidance_text(guidance)
    payload = {
        "higgsfieldGridPrompt": (
            "Create a realistic vertical social photo with natural lighting, "
            "stable styling, clear wardrobe detail, and coherent phone-camera framing."
            f"{guidance_text}"
        ),
        "klingMotionPrompt": (
            f"Use the supplied accepted 9:16 start image as the source frame for a short realistic {scene} phone video. "
            "Preserve the person, outfit, setting, pose family, camera angle, and lighting while adding subtle handheld motion, "
            "natural breathing, small posture movement, and restrained fabric motion."
            f"{guidance_text}"
        ),
        "notes": "Generated by Campaign Factory front-generation stage for accepted-still Kling planning.",
    }
    if guidance:
        payload["learnedPromptGuidance"] = guidance
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def _learned_prompt_guidance(
    reference_pattern: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(reference_pattern, dict) or not reference_pattern:
        return None
    prompt_template = reference_pattern.get("promptTemplate")
    if not isinstance(prompt_template, dict):
        prompt_template = {}
    guidance = {
        "source": "campaign_factory.reference_pattern",
        "referencePatternId": reference_pattern.get("id"),
        "clusterKey": reference_pattern.get("clusterKey"),
        "label": reference_pattern.get("label"),
        "visualFormat": reference_pattern.get("visualFormat"),
        "hookType": reference_pattern.get("hookType"),
        "captionArchetype": reference_pattern.get("captionArchetype"),
        "promptPattern": {
            key: prompt_template.get(key)
            for key in ("visual", "captionOverlay", "motion", "captionBrief")
            if prompt_template.get(key)
        },
        "instruction": "Use as structural guidance only; create original media and do not copy a prior post.",
    }
    return {
        key: value for key, value in guidance.items() if value not in (None, {}, [])
    }


def _learned_prompt_guidance_text(guidance: dict[str, Any] | None) -> str:
    if not guidance:
        return ""
    parts = [
        guidance.get("visualFormat"),
        guidance.get("hookType"),
        guidance.get("captionArchetype"),
    ]
    prompt_pattern = (
        guidance.get("promptPattern")
        if isinstance(guidance.get("promptPattern"), dict)
        else {}
    )
    parts.extend(str(value) for value in prompt_pattern.values() if value)
    compact = "; ".join(str(part).strip() for part in parts if str(part or "").strip())
    if not compact:
        return " Use learned reference-pattern structure as structural guidance only; create original media."
    return f" Learned reference-pattern structure ({compact}) is structural guidance only; create original media."
