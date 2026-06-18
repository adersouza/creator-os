from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .contracts import validate_front_generation_plan
from .core import reel_factory_python, sanitize_for_storage, slugify
from .cost_tracker import PROVIDER_PRICING


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
    estimated_image_cost_usd: float = DEFAULT_IMAGE_COST_USD,
    estimated_video_cost_usd: float = DEFAULT_KLING_COST_USD,
) -> dict[str, Any]:
    """Plan or submit the paid front-generation path behind fail-closed guards."""
    if animation_mode not in {"kling", "motion_edit"}:
        raise ValueError("animation_mode must be kling or motion_edit")
    if not creator and not soul_id and not soul_name:
        raise ValueError("creator, soul_id, or soul_name is required")
    campaign = factory.campaign_by_slug(campaign_slug)
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    reference_image = Path(reference_image_path).expanduser().resolve()
    if not reference_image.exists() or not reference_image.is_file():
        raise FileNotFoundError(f"reference image not found: {reference_image}")
    stem = slugify(reference_image.stem)
    prompt_path = _write_prompt_pack(
        dirs["reel_inputs"] / f"{stem}.front_generation_prompt.json",
        scene_type=scene_type,
    )
    projected_cost = _projected_cost(
        animation_mode=animation_mode,
        accepted_still_path=accepted_still_path,
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
            "acceptedStillPath": str(accepted_still_path) if accepted_still_path else None,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        if apply and not dry_run:
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
            dry_run=dry_run or not apply,
            budget_cap_usd=budget_cap_usd,
            estimated_image_cost_usd=estimated_image_cost_usd,
            estimated_video_cost_usd=estimated_video_cost_usd,
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
        result = {
            "schema": "campaign_factory.front_generation_stage_run.v1",
            "campaign": campaign_slug,
            "dryRun": dry_run or not apply,
            "apply": bool(apply and not dry_run),
            "plan": plan,
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
    estimated_image_cost_usd: float,
    estimated_video_cost_usd: float,
) -> float:
    total = 0.0 if accepted_still_path else estimated_image_cost_usd
    if animation_mode == "kling":
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
    dry_run: bool,
    budget_cap_usd: float | None,
    estimated_image_cost_usd: float,
    estimated_video_cost_usd: float,
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
            ],
            budget_cap_usd=budget_cap_usd,
        )
        stages.append({
            "name": "soul_reference_image",
            "status": "planned" if dry_run else "submitted",
            "paid": True,
            "estimatedCostUsd": estimated_image_cost_usd,
            "commands": image_result.get("commands") or [],
            "result": image_result,
        })
        stages.append({
            "name": "still_accept_gate",
            "status": "waiting_for_review",
            "paid": False,
            "estimatedCostUsd": 0,
            "commands": [],
            "reason": "Kling or motion-edit waits for an accepted still.",
        })
        if animation_mode == "motion_edit":
            stages.append({
                "name": "motion_edit",
                "status": "blocked",
                "paid": False,
                "estimatedCostUsd": 0,
                "commands": [],
                "reason": "Motion edit requires the accepted still path.",
            })
        else:
            video_result = _invoke_generate_assets(
                factory,
                [
                    "video-dry-run",
                    "--prompt-json",
                    str(prompt_path),
                    "--stem",
                    stem,
                    "--start-image",
                    ACCEPTED_STILL_PLACEHOLDER,
                    "--campaign",
                    campaign_slug,
                    "--estimated-cost-usd",
                    str(estimated_video_cost_usd),
                    *_soul_args(creator=creator, soul_id=soul_id, soul_name=soul_name),
                ],
                budget_cap_usd=budget_cap_usd,
            )
            stages.append({
                "name": "kling_video",
                "status": "planned",
                "paid": True,
                "estimatedCostUsd": estimated_video_cost_usd,
                "commands": video_result.get("commands") or [],
                "result": video_result,
            })
        return stages

    accepted_still = Path(accepted_still_path).expanduser().resolve()
    if not accepted_still.exists() or not accepted_still.is_file():
        raise FileNotFoundError(f"accepted still not found: {accepted_still}")
    stages.append({
        "name": "soul_reference_image",
        "status": "skipped",
        "paid": True,
        "estimatedCostUsd": 0,
        "commands": [],
        "reason": "Accepted still was supplied.",
    })
    stages.append({
        "name": "still_accept_gate",
        "status": "planned" if dry_run else "submitted",
        "paid": False,
        "estimatedCostUsd": 0,
        "commands": [],
    })
    if animation_mode == "motion_edit":
        stages.append({
            "name": "motion_edit",
            "status": "planned",
            "paid": False,
            "estimatedCostUsd": 0,
            "commands": [],
            "reason": "Run animation motion-edit separately after this paid still gate.",
        })
    else:
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
            ],
            budget_cap_usd=budget_cap_usd,
        )
        stages.append({
            "name": "kling_video",
            "status": "planned" if dry_run else "submitted",
            "paid": True,
            "estimatedCostUsd": estimated_video_cost_usd,
            "commands": video_result.get("commands") or [],
            "result": video_result,
        })
    return stages


def _invoke_generate_assets(factory: Any, args: list[str], *, budget_cap_usd: float | None) -> dict[str, Any]:
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
        raise RuntimeError(proc.stderr[-2000:] or proc.stdout[-2000:] or "generate_assets failed")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"generate_assets returned invalid JSON: {proc.stdout[-500:]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("generate_assets returned non-object JSON")
    return payload


def _soul_args(*, creator: str | None, soul_id: str | None, soul_name: str | None) -> list[str]:
    args: list[str] = []
    if creator:
        args += ["--creator", creator]
    if soul_id:
        args += ["--soul-id", soul_id]
    if soul_name:
        args += ["--soul-name", soul_name]
    return args


def _write_prompt_pack(path: Path, *, scene_type: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = scene_type.strip().replace("_", " ") or "room selfie"
    payload = {
        "higgsfieldGridPrompt": (
            "Create a realistic vertical social photo with natural lighting, "
            "stable styling, clear wardrobe detail, and coherent phone-camera framing."
        ),
        "klingMotionPrompt": (
            f"Use the supplied accepted 9:16 start image as the source frame for a short realistic {scene} phone video. "
            "Preserve the person, outfit, setting, pose family, camera angle, and lighting while adding subtle handheld motion, "
            "natural breathing, small posture movement, and restrained fabric motion."
        ),
        "notes": "Generated by Campaign Factory front-generation stage for accepted-still Kling planning.",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
