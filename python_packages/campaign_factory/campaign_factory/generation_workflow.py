from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .creative_modes import creative_workflow_mode
from .generation_execution_plan import (
    GenerationExecutionPlan,
    build_generation_execution_plan,
    require_generation_execution_mode,
)

if TYPE_CHECKING:
    from .reference_video_remix_stage import ReferenceVideoRemixSeams


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
    execution_plan = build_generation_execution_plan(mode)
    mode_id = execution_plan.creative_mode
    selected = creative_workflow_mode(mode_id)
    live = bool(apply and not dry_run)
    if apply == dry_run:
        raise ValueError("choose exactly one of dry_run or apply")

    if mode_id == "library_reuse":
        result = _run_library_reuse_mode(
            factory,
            execution_plan=execution_plan,
            campaign_slug=campaign_slug,
            library_folder=library_folder,
            model_slug=model_slug,
            output_format=output_format,
            variant_count=variant_count,
            workers=workers,
            dry_run=dry_run,
        )
    elif mode_id == "soul_static":
        require_generation_execution_mode(execution_plan, "soul_static")
        if accepted_still_path is not None:
            from .static_mp4_stage import run_static_mp4_stage

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
            from .front_generation_stage import run_front_generation_stage

            _require(reference_image_path, "reference_image_path")
            _require(creator or soul_id, "creator or soul_id")
            if live:
                _require(creator, "target creator")
                _require(soul_id, "Campaign-selected soul_id")
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
                execution_plan=execution_plan,
                dry_run=dry_run,
                apply=apply,
                enable_paid_generation=paid_confirmation,
                budget_cap_credits=max_credits,
                wait=wait,
                download=download,
            )
    elif mode_id == "motion_edit":
        result = _run_motion_edit_mode(
            factory,
            execution_plan=execution_plan,
            campaign_slug=campaign_slug,
            accepted_still_path=accepted_still_path,
            caption=caption,
            duration_seconds=duration_seconds,
            dry_run=dry_run,
            apply=apply,
            allow_upscale=allow_upscale,
        )
    elif mode_id == "best_only_kling":
        from .front_generation_stage import run_front_generation_stage

        require_generation_execution_mode(execution_plan, "best_only_kling")
        _require(reference_image_path, "reference_image_path")
        _require(accepted_still_path, "accepted_still_path")
        _require(kling_selection_receipt_path, "kling_selection_receipt_path")
        _require(creator or soul_id, "creator or soul_id")
        if live:
            _require(creator, "target creator")
            _require(soul_id, "Campaign-selected soul_id")
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
            execution_plan=execution_plan,
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
        # Reference-video remix carries optional OpenCV/PySceneDetect dependencies.
        # Import them only after the operator explicitly selects that paid mode so
        # the free Library Reuse path remains independently runnable.
        from .reference_video_remix_stage import (
            JsonCommandReferenceVideoRemixSeams,
            plan_reference_video_remix_stage,
            run_reference_video_remix_stage,
        )

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
                execution_plan=execution_plan,
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
                execution_plan=execution_plan,
            )
    return {
        "schema": "campaign_factory.generation_workflow_run.v1",
        "mode": mode_id,
        "modeDefinition": selected,
        "executionPlan": execution_plan.to_contract(),
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


def _run_library_reuse_mode(
    factory: Any,
    *,
    execution_plan: GenerationExecutionPlan,
    campaign_slug: str,
    library_folder: Path | None,
    model_slug: str | None,
    output_format: str,
    variant_count: int,
    workers: int,
    dry_run: bool,
) -> dict[str, Any]:
    require_generation_execution_mode(execution_plan, "library_reuse")
    _require(library_folder, "library_folder")
    folder = Path(library_folder).expanduser().resolve()
    _require(model_slug, "model_slug")
    if variant_count <= 0 or workers <= 0:
        raise ValueError("variant_count and workers must be positive")
    if output_format not in {"reel", "slideshow", "auto"}:
        raise ValueError("output_format must be reel, slideshow, or auto")
    if output_format == "slideshow":
        raise ValueError(
            "library_reuse_output_format_unsupported: Library Reuse preserves MP4s "
            "one-to-one and cannot render a slideshow"
        )
    if dry_run:
        selections = factory.domains.library_reuse.plan(folder)
        return {
            "schema": "campaign_factory.library_reuse_preflight.v1",
            "status": "planned",
            "folder": str(folder),
            "model": model_slug,
            "format": "reel",
            "selectedCount": len(selections),
            "selected": [
                {
                    "sourcePath": str(item.source_path),
                    "sourceSha256": item.source_sha256,
                    "mediaIdentity": item.media_identity,
                    "outputFilename": item.output_filename,
                }
                for item in selections
            ],
            "variantCountRequested": variant_count,
            "variantsCreated": 0,
            "workersRequested": workers,
            "renderingPerformed": False,
            "providerCalls": 0,
            "paidGenerationAllowed": False,
            "autoApprovalAllowed": False,
            "draftExportAllowed": False,
            "distributionDefaults": {
                "surface": "regular_reel",
                "instagramTrialReels": False,
                "shareToFeed": True,
                "collaborators": [],
            },
        }
    return factory.domains.library_reuse.run(
        folder=folder,
        campaign_slug=campaign_slug,
        model_slug=model_slug,
    )


def _run_motion_edit_mode(
    factory: Any,
    *,
    execution_plan: GenerationExecutionPlan,
    campaign_slug: str,
    accepted_still_path: Path | None,
    caption: str | None,
    duration_seconds: float | None,
    dry_run: bool,
    apply: bool,
    allow_upscale: bool,
) -> dict[str, Any]:
    from .motion_edit_stage import run_motion_edit_stage
    from .static_mp4_stage import run_static_mp4_stage

    require_generation_execution_mode(execution_plan, "motion_edit")
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
    return {"staticFallback": static_fallback, "motionEdit": motion}


def _require(value: Any, label: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{label} is required")
