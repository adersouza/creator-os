from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pipeline_contracts import (
    AnalyzerRegistryV1,
    BenchmarkRecipeV1,
    ContentIntentV1,
    CreatorIdentityProfileV1,
)

from .creative_modes import creative_workflow_mode
from .evidence_foundation import (
    compile_thin_evidence_records,
    validate_library_reuse_evidence_binding,
)
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
    reference_video_path: Path | None = None,
    creator: str | None = None,
    soul_id: str | None = None,
    workspace: Path | None = None,
    paid_confirmation: bool = False,
    max_credits: float | None = None,
    max_usd: float | None = None,
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
    motion_model_id: str | None = None,
    local_evidence_bundle_path: Path | None = None,
    local_arena_summary_path: Path | None = None,
    router_override_operator: str | None = None,
    router_override_reason: str | None = None,
    motion_prompt: str | None = None,
    audio_path: Path | None = None,
    generate_audio: bool = False,
    last_image_path: Path | None = None,
    source_video_path: Path | None = None,
    retake_start_frame: int | None = None,
    retake_end_frame: int | None = None,
    extend_frames: int | None = None,
    extend_direction: str = "after",
    preserve_audio: bool = False,
    motion_reference_image_paths: tuple[Path, ...] | list[Path] = (),
    motion_reference_video_paths: tuple[Path, ...] | list[Path] = (),
    resolution: str | None = None,
    seed: int = 42,
    steps: int | None = None,
    enable_prompt_expansion: bool = False,
    shot_type: str = "single",
    local_model_dir: Path | None = None,
    motion_task: str = "image_to_video",
    motion_lora_path: Path | None = None,
    motion_lora_strength: float = 1.0,
    creator_identity_profile: CreatorIdentityProfileV1 | None = None,
    content_intent: ContentIntentV1 | None = None,
    benchmark_recipe: BenchmarkRecipeV1 | None = None,
    analyzer_registry: AnalyzerRegistryV1 | None = None,
) -> dict[str, Any]:
    """Route one explicitly selected mode through Campaign Factory."""
    execution_plan = build_generation_execution_plan(mode)
    mode_id = execution_plan.creative_mode
    selected = creative_workflow_mode(mode_id)
    if selected.get("operatorSelectable") is False:
        raise ValueError(f"retired creative workflow mode: {mode_id}")
    live = bool(apply and not dry_run)
    if apply == dry_run:
        raise ValueError("choose exactly one of dry_run or apply")
    evidence_inputs = (
        creator_identity_profile,
        content_intent,
        benchmark_recipe,
        analyzer_registry,
    )
    if any(record is not None for record in evidence_inputs) and not all(
        record is not None for record in evidence_inputs
    ):
        raise ValueError("thin_evidence_records_must_be_complete")
    evidence_records = None
    if all(record is not None for record in evidence_inputs):
        assert creator_identity_profile is not None
        assert content_intent is not None
        assert benchmark_recipe is not None
        assert analyzer_registry is not None
        evidence_records = compile_thin_evidence_records(
            creator_identity_profile=creator_identity_profile,
            content_intent=content_intent,
            execution_policy=execution_plan.to_contract(),
            benchmark_recipe=benchmark_recipe,
            analyzer_registry=analyzer_registry,
        )

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
            evidence_records=evidence_records,
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
    elif mode_id in {"local_wan", "best_motion"}:
        from .motion_generation_stage import run_motion_generation_stage

        video_edit = motion_task in {"video_retake", "video_extend"}
        if video_edit:
            _require(source_video_path, "source_video_path")
            if accepted_still_path is not None:
                raise ValueError(
                    f"{motion_task} uses source_video_path as its only primary input; "
                    "accepted_still_path is forbidden"
                )
        else:
            _require(accepted_still_path, "accepted_still_path")
        _require(motion_prompt, "motion_prompt")
        normalized_motion_prompt = " ".join(str(motion_prompt).split())
        selected_duration = None
        if duration_seconds is not None:
            if (
                not math.isfinite(float(duration_seconds))
                or not float(duration_seconds).is_integer()
            ):
                raise ValueError("motion duration must be a whole number of seconds")
            selected_duration = int(duration_seconds)
            if selected_duration <= 0:
                raise ValueError("motion duration must be positive")
        local_motion_admission = None
        if mode_id == "local_wan":
            from .local_motion_admission import build_local_motion_admission

            if local_arena_summary_path is None:
                raise ValueError("local_wan requires --local-arena-summary")
            campaign = factory.domains.campaign_by_slug(campaign_slug)
            campaign_creator = factory.domains.reel_execution.model_slug_for_campaign(
                campaign["id"]
            )
            local_motion_admission = build_local_motion_admission(
                evidence_bundle_path=local_evidence_bundle_path,
                evidence_bundle=evidence_records,
                arena_summary_path=local_arena_summary_path,
                accepted_still_path=accepted_still_path,
                audio_path=audio_path,
                last_image_path=last_image_path,
                source_video_path=source_video_path,
                prompt=normalized_motion_prompt,
                duration_seconds=selected_duration,
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
                campaign_creator=campaign_creator,
                task_kind=motion_task,
                override_model_id=motion_model_id,
                override_operator=router_override_operator,
                override_reason=router_override_reason,
                contentforge_root=factory.settings.contentforge_root,
            )
            selected_model = str(
                local_motion_admission["routerDecision"]["selectedModelId"]
            )
            admitted_records = local_motion_admission["evidenceRecords"]
            local_benchmark_recipe = admitted_records["benchmarkRecipe"]
            local_analyzer_registry = admitted_records["analyzerRegistry"]
        else:
            if any(
                value is not None
                for value in (
                    local_evidence_bundle_path,
                    local_arena_summary_path,
                    router_override_operator,
                    router_override_reason,
                )
            ):
                raise ValueError("local Router evidence applies only to local_wan")
            selected_model = motion_model_id or "wavespeed_wan27_i2v_pro"
            local_benchmark_recipe = None
            local_analyzer_registry = None
        result = run_motion_generation_stage(
            factory,
            execution_plan=execution_plan,
            campaign_slug=campaign_slug,
            still_path=accepted_still_path,
            prompt=normalized_motion_prompt,
            model_id=selected_model,
            duration_seconds=selected_duration,
            resolution=resolution,
            seed=seed,
            steps=steps,
            dry_run=dry_run,
            apply=apply,
            workspace=workspace,
            paid_confirmation=paid_confirmation,
            max_usd=max_usd,
            audio_path=audio_path,
            generate_audio=generate_audio,
            last_image_path=last_image_path,
            source_video_path=source_video_path,
            retake_start_frame=retake_start_frame,
            retake_end_frame=retake_end_frame,
            extend_frames=extend_frames,
            extend_direction=extend_direction,
            preserve_audio=preserve_audio,
            reference_image_paths=tuple(motion_reference_image_paths),
            reference_video_paths=tuple(motion_reference_video_paths),
            enable_prompt_expansion=enable_prompt_expansion,
            shot_type=shot_type,
            local_model_dir=local_model_dir,
            motion_task=motion_task,
            motion_lora_path=motion_lora_path,
            motion_lora_strength=motion_lora_strength,
            local_motion_admission=local_motion_admission,
            local_arena_summary_path=(
                local_arena_summary_path if mode_id == "local_wan" else None
            ),
            campaign_creator=(campaign_creator if mode_id == "local_wan" else None),
            benchmark_recipe=local_benchmark_recipe,
            analyzer_registry=local_analyzer_registry,
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
        **({"evidenceRecords": evidence_records} if evidence_records else {}),
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
    evidence_records: dict[str, Any] | None = None,
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
        if evidence_records is not None:
            evidence_records = validate_library_reuse_evidence_binding(
                evidence_records,
                model_slug=str(model_slug),
                selected_source_fingerprints=tuple(
                    item.source_sha256 for item in selections
                ),
                output_format=output_format,
                variant_count=variant_count,
                workers=workers,
            )
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
            **({"evidenceRecords": evidence_records} if evidence_records else {}),
        }
    return factory.domains.library_reuse.run(
        folder=folder,
        campaign_slug=campaign_slug,
        model_slug=model_slug,
        evidence_records=evidence_records,
        output_format=output_format,
        variant_count=variant_count,
        workers=workers,
    )


def _require(value: Any, label: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{label} is required")
