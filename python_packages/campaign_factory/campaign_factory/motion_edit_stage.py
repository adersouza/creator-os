from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .contracts import validate_generated_asset_lineage, validate_motion_edit_render
from .core import (
    new_id,
    reel_factory_python,
    sanitize_for_storage,
    sha256_file,
    slugify,
)
from .persistence import utc_now
from .variation_stage import run_variation_stage


def run_motion_edit_stage(
    factory: Any,
    *,
    campaign_slug: str,
    still_path: Path,
    caption: str,
    duration_seconds: float = 5.0,
    dry_run: bool = True,
    apply: bool = False,
    enable_variation: bool = False,
    variation_preset: str = "ig_subtle",
    allow_upscale: bool = False,
) -> dict[str, Any]:
    """Render or preview a zero-cost motion-edit reel for a campaign."""
    campaign = factory.campaign_by_slug(campaign_slug)
    source = _source_asset_for_campaign(factory, campaign["id"])
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    output_path = dirs["rendered"] / f"{slugify(Path(still_path).stem)}_motion_edit.mp4"
    pipeline_job = factory.create_pipeline_job(
        "motion_edit",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "stillPath": str(still_path),
            "outputPath": str(output_path),
            "durationSeconds": duration_seconds,
            "dryRun": dry_run,
            "apply": apply,
            "enableVariation": enable_variation,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        render = _invoke_reel_factory_motion_edit(
            factory,
            still_path=Path(still_path),
            output_path=output_path,
            caption=caption,
            duration_seconds=duration_seconds,
            dry_run=dry_run or not apply,
            allow_upscale=allow_upscale,
        )
        validate_motion_edit_render(render)
        registered_asset = None
        variation = None
        if apply and not dry_run:
            registered_asset = _register_rendered_asset(
                factory,
                campaign=campaign,
                source_asset=source,
                render=render,
                caption=caption,
                model_slug=model_slug,
            )
            if enable_variation:
                variation = run_variation_stage(
                    factory,
                    campaign_slug=campaign_slug,
                    preset_name=variation_preset,
                    rendered_asset_ids=[registered_asset["id"]],
                    dry_run=True,
                )
        result = {
            "schema": "campaign_factory.motion_edit_stage_run.v1",
            "campaign": campaign_slug,
            "dryRun": dry_run or not apply,
            "apply": bool(apply and not dry_run),
            "render": render,
            "registeredAsset": registered_asset,
            "variation": variation,
            "pipelineJobId": pipeline_job["id"],
        }
        factory.finish_pipeline_job(pipeline_job["id"], sanitize_for_storage(result))
        return result
    except Exception as exc:
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _invoke_reel_factory_motion_edit(
    factory: Any,
    *,
    still_path: Path,
    output_path: Path,
    caption: str,
    duration_seconds: float,
    dry_run: bool,
    allow_upscale: bool,
) -> dict[str, Any]:
    cmd = [
        reel_factory_python(factory.settings.reel_factory_root),
        "still_to_reel.py",
        "--still",
        str(still_path),
        "--out",
        str(output_path),
        "--caption",
        caption,
        "--duration",
        str(duration_seconds),
    ]
    if allow_upscale:
        cmd.append("--allow-upscale")
    cmd.append("--dry-run" if dry_run else "--apply")
    proc = subprocess.run(
        cmd,
        cwd=factory.settings.reel_factory_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr[-2000:] or proc.stdout[-2000:] or "still_to_reel failed"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"still_to_reel returned invalid JSON: {proc.stdout[-500:]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("still_to_reel returned non-object JSON")
    return payload


def _register_rendered_asset(
    factory: Any,
    *,
    campaign: dict[str, Any],
    source_asset: dict[str, Any],
    render: dict[str, Any],
    caption: str,
    model_slug: str,
) -> dict[str, Any]:
    output_path = Path(render["outputPath"])
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise FileNotFoundError(f"motion-edit output missing: {output_path}")
    rendered_id = new_id("asset")
    digest = sha256_file(output_path)
    now = utc_now()
    caption_hash = factory._text_hash(caption) if caption else None
    caption_context = _caption_context(
        render=render,
        caption=caption,
        caption_hash=caption_hash,
        rendered_asset_id=rendered_id,
        creator_model=model_slug,
    )
    generated_lineage = _load_motion_lineage(render=render, source_asset=source_asset)
    caption_generation = {
        "schema": "campaign_factory.caption_generation.v1",
        "workflow": "motion_edit_still_to_reel",
        "animationMode": "motion_edit",
        "paidGeneration": False,
        "estimatedCostUsd": 0,
        "captionHash": caption_hash,
        "captionOutcomeContext": caption_context,
        "motionEditRender": render,
        "audioIntentPath": render.get("audioIntentPath"),
        "generatedAssetLineagePath": render.get("lineagePath"),
        "generatedAssetLineage": generated_lineage,
    }
    metadata = {
        "motionEditRender": render,
        "humanReviewRequired": True,
        "audioIntentPath": render.get("audioIntentPath"),
        "generatedAssetLineagePath": render.get("lineagePath"),
        "generatedAssetLineage": generated_lineage,
    }
    factory.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         media_type, content_surface, caption, caption_hash, caption_bank, caption_banks_json,
         creator_mix, creator_model, frame_type, length_class, format_class, caption_fit_version,
         suitability_decision, suitability_reason, source_clip, caption_outcome_context_json,
         caption_generation_json, recipe, target_ratio, metadata_json, audit_status, review_state,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'motion_edit', '9:16', ?, 'pending', 'review_ready', ?, ?)
        """,
        (
            rendered_id,
            campaign["id"],
            source_asset["id"],
            digest,
            str(output_path),
            str(output_path),
            output_path.name,
            caption,
            caption_hash,
            caption_context["caption_bank"],
            json.dumps(
                caption_context["caption_banks"], ensure_ascii=False, sort_keys=True
            ),
            caption_context["creator_mix"],
            caption_context["creator_model"],
            caption_context["frame_type"],
            caption_context["length_class"],
            caption_context["format_class"],
            caption_context["caption_fit_version"],
            caption_context["suitability_decision"],
            caption_context["suitability_reason"],
            caption_context["source_clip"],
            json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
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


def _load_motion_lineage(
    *, render: dict[str, Any], source_asset: dict[str, Any]
) -> dict[str, Any]:
    lineage_path = Path(str(render.get("lineagePath") or ""))
    if not lineage_path.is_file():
        raise FileNotFoundError(f"motion-edit lineage sidecar missing: {lineage_path}")
    try:
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"motion-edit lineage sidecar is invalid: {lineage_path}"
        ) from exc
    if not isinstance(lineage, dict):
        raise ValueError("motion-edit lineage sidecar must contain a JSON object")
    raw_source_prompt = source_asset.get("source_prompt")
    try:
        source_prompt = (
            json.loads(raw_source_prompt)
            if isinstance(raw_source_prompt, str) and raw_source_prompt
            else raw_source_prompt or {}
        )
    except json.JSONDecodeError:
        source_prompt = {}
    if not isinstance(source_prompt, dict):
        source_prompt = {}
    source = lineage.setdefault("source", {})
    if isinstance(source, dict):
        prompt_id = source_prompt.get("promptId") or source_prompt.get("prompt_id")
        reference_id = source_prompt.get("referenceId") or source_prompt.get(
            "reference_id"
        )
        if prompt_id:
            source.setdefault("promptId", prompt_id)
        if reference_id:
            source.setdefault("referenceId", reference_id)
    validate_generated_asset_lineage(lineage)
    return lineage


def _caption_context(
    *,
    render: dict[str, Any],
    caption: str,
    caption_hash: str | None,
    rendered_asset_id: str,
    creator_model: str,
) -> dict[str, Any]:
    return {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": caption_hash,
        "caption_text": caption,
        "caption_bank": "motion_edit_direct",
        "caption_banks": ["motion_edit_direct"],
        "creator_mix": creator_model,
        "creator_model": creator_model,
        "render_recipe": "motion_edit",
        "source_clip": render["stillPath"],
        "rendered_output": render["outputPath"],
        "frame_type": "still_motion_edit",
        "length_class": "short",
        "format_class": "reel",
        "caption_fit_version": "motion_edit_v1",
        "suitability_decision": "review_required",
        "suitability_reason": "Motion-edit output requires normal operator review before export.",
        "captionPlacementPolicy": "focal_safe_v1",
        "captionPlacementDecision": {
            "status": "pending",
            "selectedLane": "center",
            "reason": "Motion-edit caption overlay requires normal review.",
        },
        "motionEditRender": render,
        "renderedAssetId": rendered_asset_id,
    }


def _source_asset_for_campaign(factory: Any, campaign_id: str) -> dict[str, Any]:
    row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? ORDER BY created_at, id LIMIT 1",
        (campaign_id,),
    ).fetchone()
    if not row:
        raise ValueError(
            "campaign must have at least one source asset before motion-edit registration"
        )
    return dict(row)
