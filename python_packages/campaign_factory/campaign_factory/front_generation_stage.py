from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text
from creator_os_core.runtime_guards import require_global_write_allowed

from .contracts import validate_front_generation_plan
from .core import (
    new_id,
    reel_factory_python,
    sanitize_for_storage,
    sha256_file,
    slugify,
)
from .kling_selection_stage import validate_kling_selection_receipt
from .persistence import utc_now
from .static_mp4_stage import run_static_mp4_stage
from .variation_stage import run_variation_stage

SCHEMA = "campaign_factory.front_generation_plan.v1"
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
    budget_cap_credits: float | None = None,
    accepted_still_path: Path | None = None,
    kling_selection_receipt_path: Path | None = None,
    wait: bool = False,
    download: bool = False,
    enable_variation: bool = False,
    variation_preset: str = "ig_subtle",
) -> dict[str, Any]:
    """Plan or submit the paid front-generation path behind fail-closed guards."""
    if animation_mode not in {"static", "kling", "motion_edit"}:
        raise ValueError("animation_mode must be static, kling, or motion_edit")
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
    paid_generation_required = _paid_generation_required(
        animation_mode=animation_mode,
        accepted_still_path=accepted_still_path,
        kling_selection_receipt_path=kling_selection_receipt_path,
    )
    if apply and not dry_run and paid_generation_required:
        require_global_write_allowed("paid front generation")
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
            "budgetCapCredits": budget_cap_credits,
            "budgetCapScope": "per_provider_call",
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
        if apply and not dry_run and paid_generation_required:
            _enforce_paid_generation_guard(
                enable_paid_generation=enable_paid_generation,
                budget_cap_credits=budget_cap_credits,
            )
            if not wait or not download:
                raise ValueError(
                    "live paid generation requires --wait --download so prompt, QC, and local assets are verified"
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
            budget_cap_credits=budget_cap_credits,
            wait=wait,
            download=download,
        )
        projected_credits = _active_stage_credit_total(stages)
        budget_status = _budget_status(
            paid_generation_required=paid_generation_required,
            budget_cap_credits=budget_cap_credits,
            projected_credits=projected_credits,
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
            "projectedCostCredits": projected_credits,
            "budgetCapCredits": budget_cap_credits,
            "budgetCapScope": "per_provider_call",
            "budgetStatus": budget_status,
            "humanReviewRequired": True,
            "publishingAllowed": False,
            "stages": stages,
        }
        validate_front_generation_plan(plan)
        static_result = _stage_result(stages, "static_mp4")
        registered_static_assets = static_result.get("registeredAssets")
        if not isinstance(registered_static_assets, list):
            registered_static_asset = static_result.get("registeredAsset")
            registered_static_assets = (
                [registered_static_asset]
                if isinstance(registered_static_asset, dict)
                else []
            )
        registered_static_asset = (
            registered_static_assets[0] if registered_static_assets else None
        )
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
                    estimated_video_cost_credits=_provider_quote_amount(video_result),
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
            "registeredStaticAssets": registered_static_assets,
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


def _paid_generation_required(
    *,
    animation_mode: str,
    accepted_still_path: Path | None,
    kling_selection_receipt_path: Path | None,
) -> bool:
    return accepted_still_path is None or (
        animation_mode == "kling" and kling_selection_receipt_path is not None
    )


def _budget_status(
    *,
    paid_generation_required: bool,
    budget_cap_credits: float | None,
    projected_credits: float | None = None,
) -> str:
    if not paid_generation_required:
        return "not_required"
    if budget_cap_credits is None:
        return "missing_cap"
    if projected_credits is not None:
        return "within_cap"
    return "quote_pending"


def _active_stage_credit_total(stages: list[dict[str, Any]]) -> float | None:
    active_paid = [
        stage
        for stage in stages
        if stage.get("paid") is True and stage.get("status") in {"planned", "submitted"}
    ]
    if not active_paid:
        return 0.0
    amounts = [stage.get("estimatedCostCredits") for stage in active_paid]
    if any(not isinstance(amount, (int, float)) for amount in amounts):
        return None
    return round(sum(float(amount) for amount in amounts), 4)


def _enforce_paid_generation_guard(
    *,
    enable_paid_generation: bool,
    budget_cap_credits: float | None,
) -> None:
    if not enable_paid_generation:
        raise PermissionError("paid generation requires --enable-paid-generation")
    if budget_cap_credits is None or budget_cap_credits <= 0:
        raise ValueError("paid generation requires --budget-cap-credits")


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
    budget_cap_credits: float | None,
    wait: bool,
    download: bool,
) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    if accepted_still_path is None:
        static_batches: list[dict[str, Any]] = []
        image_result = _invoke_generate_assets(
            factory,
            [
                "reference-image-dry-run" if dry_run else "reference-image",
                "--reference",
                str(reference_image),
                "--stem",
                stem,
                *_credit_args(campaign_slug, budget_cap_credits),
                *_soul_args(creator=creator, soul_id=soul_id, soul_name=soul_name),
                *_runtime_generation_args(
                    wait=wait, download=download, dry_run=dry_run
                ),
            ],
        )
        if not dry_run:
            _require_generation_ok(image_result, "Soul reference image")
            static_batches.append(
                _materialize_generated_static_candidates(
                    factory,
                    campaign_slug=campaign_slug,
                    reference_image=reference_image,
                    generated_candidates=(("original", image_result),),
                )
            )
        stages.append(
            {
                "name": "soul_reference_image",
                "status": "planned" if dry_run else "submitted",
                "paid": True,
                "estimatedCostCredits": _provider_quote_amount(image_result),
                "commands": image_result.get("commands") or [],
                "result": image_result,
            }
        )
        sexy_result: dict[str, Any] | None = None
        if dry_run:
            stages.append(
                {
                    "name": "soul_sexy_image",
                    "status": "blocked",
                    "paid": True,
                    "estimatedCostCredits": None,
                    "commands": [],
                    "reason": (
                        "The text-only sexy variant requires the captured prompt "
                        "from the completed reference-conditioned original."
                    ),
                }
            )
        else:
            variant_spec = _invoke_generate_variant_spec(factory, image_result)
            sexy_prompt_path = _write_sexy_prompt_pack(
                prompt_path.with_name(f"{stem}.sexy_variant_prompt.json"),
                variant_spec=variant_spec,
                base_prompt_path=prompt_path,
            )
            sexy = variant_spec["sexy"]
            sexy_result = _invoke_generate_assets(
                factory,
                [
                    "image",
                    "--prompt-json",
                    str(sexy_prompt_path),
                    "--stem",
                    f"{stem}_sexy",
                    "--image-aspect-ratio",
                    str(sexy["aspect_ratio"]),
                    *_credit_args(campaign_slug, budget_cap_credits),
                    *_soul_args(
                        creator=creator,
                        soul_id=str(variant_spec["soul_id"]),
                        soul_name=None,
                    ),
                    *_runtime_generation_args(
                        wait=wait, download=download, dry_run=False
                    ),
                ],
            )
            _require_generation_ok(sexy_result, "text-only Soul sexy variant")
            static_batches.append(
                _materialize_generated_static_candidates(
                    factory,
                    campaign_slug=campaign_slug,
                    reference_image=reference_image,
                    generated_candidates=(("sexy", sexy_result),),
                )
            )
            stages.append(
                {
                    "name": "soul_sexy_image",
                    "status": "submitted",
                    "paid": True,
                    "estimatedCostCredits": _provider_quote_amount(sexy_result),
                    "commands": sexy_result.get("commands") or [],
                    "result": sexy_result,
                    "variantSpec": variant_spec,
                }
            )
        if dry_run:
            stages.append(
                {
                    "name": "still_accept_gate",
                    "status": "waiting_for_review",
                    "paid": False,
                    "estimatedCostCredits": 0,
                    "commands": [],
                    "reason": (
                        "A live QC-passing original and sexy still will each receive "
                        "a static MP4 before human review."
                    ),
                }
            )
            stages.append(
                {
                    "name": "static_mp4",
                    "status": "blocked",
                    "paid": False,
                    "estimatedCostCredits": 0,
                    "commands": [],
                    "reason": "Static MP4 requires downloaded QC-passing stills.",
                }
            )
        else:
            if sexy_result is None:
                raise RuntimeError("text-only Soul sexy variant result is missing")
            static_batch = _combine_generated_static_candidate_batches(static_batches)
            stages.append(
                {
                    "name": "still_accept_gate",
                    "status": "waiting_for_review",
                    "paid": False,
                    "estimatedCostCredits": 0,
                    "commands": [],
                    "reason": (
                        "QC-passing stills already have zero-cost static fallbacks; "
                        "human review now selects handoff and optional Kling candidates."
                    ),
                }
            )
            stages.append(
                {
                    "name": "static_mp4",
                    "status": "submitted",
                    "paid": False,
                    "estimatedCostCredits": 0,
                    "commands": [
                        candidate["staticMp4"]["render"].get("ffmpegCommand") or []
                        for candidate in static_batch["candidates"]
                    ],
                    "result": static_batch,
                }
            )
        if animation_mode == "static":
            pass
        elif animation_mode == "motion_edit":
            stages.append(
                {
                    "name": "motion_edit",
                    "status": "blocked",
                    "paid": False,
                    "estimatedCostCredits": 0,
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
                    "estimatedCostCredits": None,
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
            "estimatedCostCredits": 0,
            "commands": [],
            "reason": "Accepted still was supplied.",
        }
    )
    stages.append(
        {
            "name": "still_accept_gate",
            "status": "planned" if dry_run else "submitted",
            "paid": False,
            "estimatedCostCredits": 0,
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
            "estimatedCostCredits": 0,
            "commands": [static_result["render"].get("ffmpegCommand") or []],
            "result": static_result,
        }
    )
    if animation_mode == "static":
        return stages
    if animation_mode == "motion_edit":
        stages.append(
            {
                "name": "motion_edit",
                "status": "planned",
                "paid": False,
                "estimatedCostCredits": 0,
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
                    "estimatedCostCredits": None,
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
                *_credit_args(campaign_slug, budget_cap_credits),
                *_soul_args(creator=creator, soul_id=soul_id, soul_name=soul_name),
                *_runtime_generation_args(
                    wait=wait, download=download, dry_run=dry_run
                ),
            ],
        )
        if not dry_run:
            _require_generation_ok(video_result, "Kling video")
        video_result["klingSelectionReceipt"] = selection
        stages.append(
            {
                "name": "kling_video",
                "status": "planned" if dry_run else "submitted",
                "paid": True,
                "estimatedCostCredits": _provider_quote_amount(video_result),
                "commands": video_result.get("commands") or [],
                "result": video_result,
            }
        )
    return stages


def _combine_generated_static_candidate_batches(
    batches: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = [
        candidate
        for batch in batches
        for candidate in batch.get("candidates", [])
        if isinstance(candidate, dict)
    ]
    registered_assets = [
        asset
        for batch in batches
        for asset in batch.get("registeredAssets", [])
        if isinstance(asset, dict)
    ]
    if not candidates or len(candidates) != len(registered_assets):
        raise RuntimeError("generated static candidate batches are incomplete")
    return {
        "schema": "campaign_factory.generated_static_candidate_batch.v1",
        "paidGeneration": False,
        "candidateCount": len(candidates),
        "candidates": candidates,
        "registeredAssets": registered_assets,
    }


def _materialize_generated_static_candidates(
    factory: Any,
    *,
    campaign_slug: str,
    reference_image: Path,
    generated_candidates: tuple[tuple[str, dict[str, Any]], ...],
) -> dict[str, Any]:
    """Persist every QC-passing generated still and render its free fallback."""
    campaign = factory.campaign_by_slug(campaign_slug)
    candidates: list[dict[str, Any]] = []
    registered_assets: list[dict[str, Any]] = []
    for variant, generation_result in generated_candidates:
        stills = _qc_passing_stills(generation_result, variant=variant)
        for still in stills:
            source_asset = _ensure_generated_still_source_asset(
                factory,
                campaign=campaign,
                reference_image=reference_image,
                still=still,
                generation_result=generation_result,
                variant=variant,
            )
            canonical_still = Path(source_asset["stored_path"]).expanduser().resolve()
            if not canonical_still.is_file():
                raise FileNotFoundError(
                    f"registered {variant} Soul still is missing: {canonical_still}"
                )
            static_result = run_static_mp4_stage(
                factory,
                campaign_slug=campaign_slug,
                still_path=canonical_still,
                dry_run=False,
                apply=True,
            )
            registered = static_result.get("registeredAsset")
            if not isinstance(registered, dict):
                raise RuntimeError(f"{variant} static MP4 was not registered")
            registered_assets.append(registered)
            candidates.append(
                {
                    "variant": variant,
                    "stillPath": str(canonical_still),
                    "sourceAssetId": source_asset["id"],
                    "renderedAssetId": registered["id"],
                    "staticMp4": static_result,
                }
            )
    if not candidates:
        raise RuntimeError(
            "no QC-passing generated stills were available for static MP4"
        )
    return {
        "schema": "campaign_factory.generated_static_candidate_batch.v1",
        "paidGeneration": False,
        "candidateCount": len(candidates),
        "candidates": candidates,
        "registeredAssets": registered_assets,
    }


def _qc_passing_stills(result: dict[str, Any], *, variant: str) -> list[Path]:
    lineage = result.get("lineage")
    review = lineage.get("review") if isinstance(lineage, dict) else None
    qc = review.get("generatedImageQc") if isinstance(review, dict) else None
    if not isinstance(qc, dict) or qc.get("status") != "passed":
        raise RuntimeError(f"{variant} still lacks passing generated-image QC")
    rows = qc.get("results")
    if not isinstance(rows, list):
        raise RuntimeError(f"{variant} still QC has no result rows")
    paths: list[Path] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("postable") is not True:
            continue
        value = row.get("path")
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{variant} QC-passing still not found: {path}")
        if path not in paths:
            paths.append(path)
    if not paths:
        raise RuntimeError(f"{variant} still QC has no postable local output")
    return paths


def _ensure_generated_still_source_asset(
    factory: Any,
    *,
    campaign: dict[str, Any],
    reference_image: Path,
    still: Path,
    generation_result: dict[str, Any],
    variant: str,
) -> dict[str, Any]:
    lineage = generation_result.get("lineage")
    if not isinstance(lineage, dict):
        raise ValueError(f"{variant} generated still is missing lineage")
    lineage = copy.deepcopy(lineage)
    source = lineage.setdefault("source", {})
    lineage_path = str(generation_result.get("path") or "").strip()
    if lineage_path:
        source["sourceLineagePath"] = str(Path(lineage_path).expanduser().resolve())
    review = lineage.setdefault("review", {})
    review["qcAcceptanceStatus"] = "accepted"
    review.setdefault("humanReviewStatus", "pending")

    digest = sha256_file(still)
    existing = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
        (campaign["id"], digest),
    ).fetchone()
    model_row = factory.conn.execute(
        "SELECT model_id FROM source_assets WHERE campaign_id = ? "
        "ORDER BY created_at, id LIMIT 1",
        (campaign["id"],),
    ).fetchone()
    if not model_row:
        raise ValueError(
            "front generation requires an existing campaign source to resolve its model"
        )

    prompt_text = _generated_prompt_text(lineage)
    prompt_id = (
        "prompt_higgsfield_"
        + hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
    )
    reference_id = str(source.get("referenceId") or "").strip() or (
        "reference_file_" + sha256_file(reference_image)[:16]
    )
    source_prompt = {
        "schema": "campaign_factory.generated_soul_still_source.v1",
        "variant": variant,
        "promptId": prompt_id,
        "referenceId": reference_id,
        "referenceImagePath": str(reference_image),
        "generatedAssetLineage": lineage,
    }
    stored_source_prompt = json.dumps(
        sanitize_for_storage(source_prompt), ensure_ascii=False, sort_keys=True
    )

    if existing:
        row = dict(existing)
        current: dict[str, Any] = {}
        raw_current = row.get("source_prompt")
        if isinstance(raw_current, str) and raw_current.strip():
            try:
                parsed = json.loads(raw_current)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                current = parsed
        if current.get("schema") != source_prompt["schema"]:
            if current:
                source_prompt["previousSourcePrompt"] = current
            stored_source_prompt = json.dumps(
                sanitize_for_storage(source_prompt),
                ensure_ascii=False,
                sort_keys=True,
            )
            factory.conn.execute(
                "UPDATE source_assets SET source_prompt = ?, status = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    stored_source_prompt,
                    "generated_qc_passed",
                    utc_now(),
                    row["id"],
                ),
            )
            factory.conn.commit()
            row = dict(
                factory.conn.execute(
                    "SELECT * FROM source_assets WHERE id = ?", (row["id"],)
                ).fetchone()
            )
        return row

    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    stored = dirs["sources"] / (
        f"{slugify(still.stem)}_{digest[:10]}{still.suffix.lower()}"
    )
    if still != stored.resolve():
        stored.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(still, stored)
    else:
        stored = still
    now = utc_now()
    source_id = new_id("src")
    factory.conn.execute(
        """
        INSERT INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path,
         filename, media_type, content_surface, platform, source_prompt, notes,
         account_ids_json, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'image', 'reel', 'instagram', ?, ?, '[]',
                'generated_qc_passed', ?, ?)
        """,
        (
            source_id,
            campaign["id"],
            model_row["model_id"],
            digest,
            str(still),
            str(stored),
            stored.name,
            stored_source_prompt,
            f"QC-passing {variant} Soul still from front generation.",
            now,
            now,
        ),
    )
    factory.conn.commit()
    factory.record_event(
        "source_imported",
        campaign_id=campaign["id"],
        source_asset_id=source_id,
        status="success",
        message=f"Registered QC-passing {variant} Soul still",
        metadata={
            "variant": variant,
            "originalPath": str(still),
            "storedPath": str(stored),
            "contentHash": digest,
            "sourceGenerationPaid": True,
            "staticFallbackPaidGeneration": False,
        },
    )
    return dict(
        factory.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?", (source_id,)
        ).fetchone()
    )


def _generated_prompt_text(lineage: dict[str, Any]) -> str:
    generation = lineage.get("generation")
    if not isinstance(generation, dict):
        raise ValueError("generated still lineage is missing generation metadata")
    captured = str(generation.get("capturedHiggsfieldPrompt") or "").strip()
    if captured:
        return captured
    prompts = generation.get("prompts")
    if isinstance(prompts, dict):
        prompt = str(prompts.get("higgsfieldGridPrompt") or "").strip()
        if prompt:
            return prompt
    raise ValueError("generated still lineage is missing its provider prompt")


def _invoke_generate_assets(factory: Any, args: list[str]) -> dict[str, Any]:
    cmd = [
        reel_factory_python(factory.settings.reel_factory_root),
        "generate_assets.py",
        *args,
        "--root",
        str(factory.settings.reel_factory_root),
    ]
    env = os.environ.copy()
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


def _credit_args(campaign_slug: str, budget_cap_credits: float | None) -> list[str]:
    args = ["--cohort-id", campaign_slug]
    if budget_cap_credits is not None:
        args += ["--max-credits", str(budget_cap_credits)]
    return args


def _provider_quote_amount(result: dict[str, Any]) -> float | None:
    lineage = result.get("lineage")
    generation = lineage.get("generation") if isinstance(lineage, dict) else None
    preflight = (
        generation.get("costPreflight") if isinstance(generation, dict) else None
    )
    quote = preflight.get("providerQuote") if isinstance(preflight, dict) else None
    amount = quote.get("amount") if isinstance(quote, dict) else None
    return (
        float(amount)
        if isinstance(amount, (int, float)) and not isinstance(amount, bool)
        else None
    )


def _invoke_generate_variant_spec(
    factory: Any, original_result: dict[str, Any]
) -> dict[str, Any]:
    lineage = original_result.get("lineage")
    if not isinstance(lineage, dict):
        raise ValueError("completed Soul original is missing lineage")
    generation = lineage.get("generation")
    source = lineage.get("source")
    if not isinstance(generation, dict) or not isinstance(source, dict):
        raise ValueError("completed Soul original lineage is incomplete")
    captured_prompt = str(generation.get("capturedHiggsfieldPrompt") or "").strip()
    resolved_soul_id = str(source.get("soulId") or "").strip()
    if not captured_prompt:
        raise ValueError("Higgsfield did not return the captured original prompt")
    if not resolved_soul_id:
        raise ValueError("completed Soul original is missing its Soul ID")
    command = [
        reel_factory_python(factory.settings.reel_factory_root),
        "generate_variants.py",
        "--captured-prompt",
        captured_prompt,
        "--soul-id",
        resolved_soul_id,
    ]
    image_job_id = str(generation.get("imageJobId") or "").strip()
    if image_job_id:
        command += ["--reference-media-id", image_job_id]
    proc = subprocess.run(
        command,
        cwd=factory.settings.reel_factory_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr[-2000:] or proc.stdout[-2000:] or "variant spec failed"
        )
    try:
        spec = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("variant spec returned invalid JSON") from exc
    _validate_variant_spec(spec, expected_soul_id=resolved_soul_id)
    return spec


def _validate_variant_spec(spec: Any, *, expected_soul_id: str) -> None:
    if not isinstance(spec, dict) or spec.get("soul_id") != expected_soul_id:
        raise ValueError("variant spec Soul ID does not match the original")
    original = spec.get("original")
    sexy = spec.get("sexy")
    if (
        not isinstance(original, dict)
        or original.get("generation_required") is not False
        or not isinstance(sexy, dict)
        or sexy.get("generation_required") is not True
        or sexy.get("text_only") is not True
        or sexy.get("reference_media_id") is not None
        or spec.get("provider_generation_count") != 1
    ):
        raise ValueError("variant spec violates the original-plus-text-only policy")
    prompt = str(sexy.get("prompt") or "")
    if not prompt.strip():
        raise ValueError("text-only sexy variant prompt is empty")
    words = set(re.findall(r"[a-z]+", prompt.lower()))
    forbidden = {
        "adult",
        "adults",
        "woman",
        "women",
        "girl",
        "girls",
        "teen",
        "teens",
        "young",
    }
    if words & forbidden:
        raise ValueError(
            "text-only sexy variant prompt contains forbidden identity wording"
        )


def _write_sexy_prompt_pack(
    path: Path, *, variant_spec: dict[str, Any], base_prompt_path: Path
) -> Path:
    base = json.loads(base_prompt_path.read_text(encoding="utf-8"))
    sexy = variant_spec["sexy"]
    payload = {
        "higgsfieldGridPrompt": sexy["prompt"],
        "klingMotionPrompt": str(base.get("klingMotionPrompt") or ""),
        "notes": (
            "Text-only Soul variant derived from the captured Higgsfield prompt; "
            "the reference image is intentionally not attached."
        ),
    }
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _require_generation_ok(result: dict[str, Any], label: str) -> None:
    if result.get("ok") is True:
        return
    error = result.get("error")
    if isinstance(error, dict):
        reason = error.get("reason") or error.get("message")
    else:
        reason = error
    lineage = result.get("lineage")
    generation = lineage.get("generation") if isinstance(lineage, dict) else None
    failure = generation.get("failure") if isinstance(generation, dict) else None
    if not reason and isinstance(failure, dict):
        reason = failure.get("reason") or failure.get("message")
    raise RuntimeError(f"{label} generation blocked or failed: {reason or 'unknown'}")


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
    estimated_video_cost_credits: float | None,
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
        "estimatedCostCredits": estimated_video_cost_credits,
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
            "estimatedCostCredits": estimated_video_cost_credits,
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
