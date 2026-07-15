from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .creative_modes import creative_workflow_mode
from .front_generation_stage import run_front_generation_stage
from .motion_edit_stage import run_motion_edit_stage
from .proactive_cycle_stage import run_proactive_cycle_stage
from .reference_video_remix_stage import (
    JsonCommandReferenceVideoRemixSeams,
    ReferenceVideoRemixSeams,
    plan_reference_video_remix_stage,
    run_reference_video_remix_stage,
)
from .static_mp4_stage import run_static_mp4_stage


def run_generation_workflow(
    factory: Any,
    *,
    mode: str,
    campaign_slug: str,
    dry_run: bool,
    apply: bool,
    reference_image_path: Path | None = None,
    accepted_still_path: Path | None = None,
    kling_selection_receipt_path: Path | None = None,
    reference_video_path: Path | None = None,
    creator: str | None = None,
    soul_id: str | None = None,
    workspace: Path | None = None,
    paid_confirmation: bool = False,
    max_credits: float | None = None,
    caption: str | None = None,
    duration_seconds: float | None = None,
    count: int = 3,
    account: str | None = None,
    library_folder: Path | None = None,
    model_slug: str | None = None,
    output_format: str = "auto",
    variant_count: int = 20,
    workers: int = 3,
    first_frame_approval_id: str | None = None,
    last_frame_approval_id: str | None = None,
    operator_selected: bool = False,
    rights_confirmed: bool = False,
    preferred_provider: str = "auto",
    available_providers: tuple[str, ...] | list[str] = ("seedance", "kling"),
    allow_upscale: bool = False,
    wait: bool = False,
    download: bool = False,
    structural_seams: ReferenceVideoRemixSeams | None = None,
) -> dict[str, Any]:
    """Route one explicitly selected mode through Campaign Factory."""
    selected = creative_workflow_mode(mode)
    mode_id = str(selected["id"])
    live = bool(apply and not dry_run)
    if apply == dry_run:
        raise ValueError("choose exactly one of dry_run or apply")

    if mode_id == "library_reuse":
        if library_folder is not None:
            folder = Path(library_folder).expanduser().resolve()
            if not folder.is_dir():
                raise FileNotFoundError(f"library folder not found: {folder}")
            _require(model_slug, "model_slug")
            if variant_count <= 0 or workers <= 0:
                raise ValueError("variant_count and workers must be positive")
            if output_format not in {"reel", "slideshow", "auto"}:
                raise ValueError("output_format must be reel, slideshow, or auto")
            if dry_run:
                result = {
                    "schema": "campaign_factory.library_reuse_preflight.v1",
                    "status": "planned",
                    "folder": str(folder),
                    "model": model_slug,
                    "format": output_format,
                    "variantCount": variant_count,
                    "workers": workers,
                    "providerCalls": 0,
                    "paidGenerationAllowed": False,
                    "autoApprovalAllowed": False,
                    "draftExportAllowed": False,
                }
            else:
                result = factory.make_batch(
                    folder=folder,
                    campaign_slug=campaign_slug,
                    model_slug=model_slug,
                    output_format=output_format,
                    variant_count=variant_count,
                    dry_run_export=True,
                    workers=workers,
                    auto_approve_warning_only=False,
                )
        else:
            result = run_proactive_cycle_stage(
                factory,
                campaign_slug=campaign_slug,
                count=count,
                account=account,
                generation_mode="existing_asset",
                enable_export=False,
                enable_schedule=False,
                dry_run=dry_run,
                apply=apply,
                enable_live=live,
                enable_paid_generation=False,
                budget_cap_usd=0,
            )
    elif mode_id == "soul_static":
        if accepted_still_path is not None:
            result = run_static_mp4_stage(
                factory,
                campaign_slug=campaign_slug,
                still_path=accepted_still_path,
                duration_seconds=duration_seconds,
                dry_run=dry_run,
                apply=apply,
                allow_upscale=allow_upscale,
            )
        else:
            _require(reference_image_path, "reference_image_path")
            _require(creator or soul_id, "creator or soul_id")
            if live:
                _require(creator, "target creator")
            _paid_inputs_if_live(
                live=live,
                paid_confirmation=paid_confirmation,
                workspace=workspace,
                max_credits=max_credits,
            )
            result = run_front_generation_stage(
                factory,
                campaign_slug=campaign_slug,
                reference_image_path=reference_image_path,
                creator=creator,
                soul_id=soul_id,
                animation_mode="static",
                dry_run=dry_run,
                apply=apply,
                enable_paid_generation=paid_confirmation,
                budget_cap_credits=max_credits,
                wait=wait,
                download=download,
            )
    elif mode_id == "motion_edit":
        _require(accepted_still_path, "accepted_still_path")
        caption = str(caption or "").strip()
        if not caption:
            raise ValueError("caption is required for local motion edit")
        static_fallback = run_static_mp4_stage(
            factory,
            campaign_slug=campaign_slug,
            still_path=accepted_still_path,
            duration_seconds=duration_seconds,
            dry_run=dry_run,
            apply=apply,
            allow_upscale=allow_upscale,
        )
        motion = run_motion_edit_stage(
            factory,
            campaign_slug=campaign_slug,
            still_path=accepted_still_path,
            caption=caption,
            duration_seconds=duration_seconds or 5.0,
            dry_run=dry_run,
            apply=apply,
            allow_upscale=allow_upscale,
        )
        result = {"staticFallback": static_fallback, "motionEdit": motion}
    elif mode_id == "best_only_kling":
        _require(reference_image_path, "reference_image_path")
        _require(accepted_still_path, "accepted_still_path")
        _require(kling_selection_receipt_path, "kling_selection_receipt_path")
        _require(creator or soul_id, "creator or soul_id")
        if live:
            _require(creator, "target creator")
        _paid_inputs_if_live(
            live=live,
            paid_confirmation=paid_confirmation,
            workspace=workspace,
            max_credits=max_credits,
        )
        result = run_front_generation_stage(
            factory,
            campaign_slug=campaign_slug,
            reference_image_path=reference_image_path,
            creator=creator,
            soul_id=soul_id,
            animation_mode="kling",
            accepted_still_path=accepted_still_path,
            kling_selection_receipt_path=kling_selection_receipt_path,
            budget_cap_credits=max_credits,
            enable_paid_generation=paid_confirmation,
            wait=wait,
            download=download,
            dry_run=dry_run,
            apply=apply,
        )
    else:
        _require(reference_video_path, "reference_video_path")
        _require(creator, "creator")
        _require(soul_id, "soul_id")
        _require(workspace, "workspace")
        if live:
            _paid_inputs_if_live(
                live=True,
                paid_confirmation=paid_confirmation,
                workspace=workspace,
                max_credits=max_credits,
            )
            _require(first_frame_approval_id, "first_frame_approval_id")
            _require(last_frame_approval_id, "last_frame_approval_id")
            result = run_reference_video_remix_stage(
                factory,
                campaign_slug=campaign_slug,
                reference_video_path=reference_video_path,
                creator=creator,
                soul_id=soul_id,
                workspace=workspace,
                operator_selected=operator_selected,
                rights_confirmed=rights_confirmed,
                first_frame_approval_id=first_frame_approval_id,
                last_frame_approval_id=last_frame_approval_id,
                paid_confirmation=True,
                max_credits=float(max_credits),
                preferred_provider=preferred_provider,
                available_providers=available_providers,
                seams=structural_seams or JsonCommandReferenceVideoRemixSeams(),
            )
        else:
            result = plan_reference_video_remix_stage(
                reference_video_path=reference_video_path,
                creator=creator,
                soul_id=soul_id,
                workspace=workspace,
                operator_selected=operator_selected,
                rights_confirmed=rights_confirmed,
                max_credits=max_credits,
            )
    return {
        "schema": "campaign_factory.generation_workflow_run.v1",
        "mode": mode_id,
        "modeDefinition": selected,
        "dryRun": dry_run,
        "apply": live,
        "result": result,
        "humanReviewRequired": True,
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }


def _paid_inputs_if_live(
    *,
    live: bool,
    paid_confirmation: bool,
    workspace: Path | None,
    max_credits: float | None,
) -> None:
    if not live:
        return
    if not paid_confirmation:
        raise PermissionError("paid generation requires explicit --confirm-paid")
    if workspace is None or not Path(workspace).expanduser().resolve().is_dir():
        raise ValueError("paid generation requires an existing --workspace")
    if (
        max_credits is None
        or isinstance(max_credits, bool)
        or not math.isfinite(float(max_credits))
        or float(max_credits) <= 0
    ):
        raise ValueError("paid generation requires a finite positive --max-credits")


def _require(value: Any, label: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{label} is required")
