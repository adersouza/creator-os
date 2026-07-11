from __future__ import annotations

import json
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
from .lineage_v2 import build_lineage_v2_core, finalize_lineage_v2
from .persistence import utc_now


def run_static_mp4_stage(
    factory: Any,
    *,
    campaign_slug: str,
    still_path: Path,
    duration_seconds: float = 5.0,
    dry_run: bool = True,
    apply: bool = False,
    allow_upscale: bool = False,
) -> dict[str, Any]:
    """Create the mandatory zero-cost static fallback for an accepted Soul still."""
    campaign = factory.campaign_by_slug(campaign_slug)
    source_asset = _source_asset_for_campaign(factory, campaign["id"])
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    still = Path(still_path).expanduser().resolve()
    if not still.exists() or not still.is_file():
        raise FileNotFoundError(f"accepted still not found: {still}")
    still_fingerprint = sha256_file(still)
    output_path = (
        dirs["rendered"] / f"{slugify(still.stem)}_{still_fingerprint[:12]}_static.mp4"
    )
    pipeline_job = factory.create_pipeline_job(
        "static_mp4",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "stillPath": str(still),
            "outputPath": str(output_path),
            "durationSeconds": duration_seconds,
            "dryRun": dry_run,
            "apply": apply,
            "paidGeneration": False,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        render = _invoke_reel_factory_static_mp4(
            factory,
            still_path=still,
            output_path=output_path,
            duration_seconds=duration_seconds,
            dry_run=dry_run or not apply,
            allow_upscale=allow_upscale,
        )
        _validate_render(render)
        registered_asset = None
        if apply and not dry_run:
            registered_asset = _register_rendered_asset(
                factory,
                campaign=campaign,
                source_asset=source_asset,
                render=render,
            )
        result = {
            "schema": "campaign_factory.static_mp4_stage_run.v1",
            "campaign": campaign_slug,
            "dryRun": dry_run or not apply,
            "apply": bool(apply and not dry_run),
            "paidGeneration": False,
            "render": render,
            "registeredAsset": registered_asset,
            "pipelineJobId": pipeline_job["id"],
        }
        factory.finish_pipeline_job(pipeline_job["id"], sanitize_for_storage(result))
        return result
    except Exception as exc:
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _invoke_reel_factory_static_mp4(
    factory: Any,
    *,
    still_path: Path,
    output_path: Path,
    duration_seconds: float,
    dry_run: bool,
    allow_upscale: bool,
) -> dict[str, Any]:
    command = [
        reel_factory_python(factory.settings.reel_factory_root),
        "static_mp4.py",
        "--still",
        str(still_path),
        "--out",
        str(output_path),
        "--duration",
        str(duration_seconds),
        "--audio-mode",
        "platform_auto_music",
    ]
    if allow_upscale:
        command.append("--allow-upscale")
    command.append("--dry-run" if dry_run else "--apply")
    proc = subprocess.run(
        command,
        cwd=factory.settings.reel_factory_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr[-2000:] or proc.stdout[-2000:] or "static_mp4 failed"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"static_mp4 returned invalid JSON: {proc.stdout[-500:]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("static_mp4 returned non-object JSON")
    return payload


def _validate_render(render: dict[str, Any]) -> None:
    if render.get("schema") != "reel_factory.static_mp4_render.v1":
        raise ValueError("static MP4 render has the wrong schema")
    if render.get("animationMode") != "static_image_mp4":
        raise ValueError("static MP4 render has the wrong animation mode")
    if render.get("paidGeneration") is not False:
        raise ValueError("static MP4 render must be zero-cost")
    if render.get("lockedStatic") is not True:
        raise ValueError("static MP4 render must remain locked")
    if render.get("audioBurned") is not False:
        raise ValueError("static MP4 render must not burn audio")


def _register_rendered_asset(
    factory: Any,
    *,
    campaign: dict[str, Any],
    source_asset: dict[str, Any],
    render: dict[str, Any],
) -> dict[str, Any]:
    output_path = Path(str(render.get("outputPath") or ""))
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise FileNotFoundError(f"static MP4 output missing: {output_path}")
    audio_intent_path = Path(str(render.get("audioIntentPath") or ""))
    if not audio_intent_path.is_file():
        raise FileNotFoundError(
            f"static MP4 audio-intent sidecar missing: {audio_intent_path}"
        )
    try:
        audio_intent = json.loads(audio_intent_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("static MP4 audio-intent sidecar is invalid") from exc
    if not isinstance(audio_intent, dict):
        raise ValueError("static MP4 audio-intent sidecar must be a JSON object")

    rendered_id = new_id("asset")
    content_fingerprint = sha256_file(output_path)
    existing = factory.conn.execute(
        """
        SELECT * FROM rendered_assets
        WHERE campaign_id = ? AND recipe = 'static_mp4' AND content_hash = ?
        ORDER BY created_at, id LIMIT 1
        """,
        (campaign["id"], content_fingerprint),
    ).fetchone()
    if existing:
        return dict(existing)
    caption_hash = factory._text_hash("")
    source_prompt = _source_prompt(source_asset)
    upstream_lineage = source_prompt.get("generatedAssetLineage")
    lineage = build_lineage_v2_core(
        upstream_lineage if isinstance(upstream_lineage, dict) else None,
        campaign_id=campaign["id"],
        recipe_id="static_mp4",
        caption_hash=caption_hash,
        rendered_asset_id=rendered_id,
        content_fingerprint=content_fingerprint,
        prompt_id=source_prompt.get("promptId"),
        reference_id=source_prompt.get("referenceId"),
    )
    source = lineage.setdefault("source", {})
    source.update(
        {
            "parentStillPath": render["stillPath"],
            "parentStillHash": sha256_file(Path(render["stillPath"])),
        }
    )
    lineage["generation"].update(
        {
            "tool": "reel_factory.static_mp4",
            "workflow": "accepted_soul_still_to_static_mp4",
            "animationMode": "static_image_mp4",
            "paidGeneration": False,
            "estimatedCostUsd": 0,
        }
    )
    lineage["render"] = {
        "outputPath": str(output_path),
        "durationSeconds": render["durationSeconds"],
        "lockedStatic": True,
        "audioBurned": False,
        "quality": render["quality"],
    }
    lineage["review"].update(
        {
            "parentStillAccepted": True,
            "humanReviewRequired": True,
            "status": "review_ready",
        }
    )
    lineage["asset_state"] = "approved_but_not_publishable"
    lineage["publishability_failure_reasons"] = ["native_audio_unresolved"]
    lineage = finalize_lineage_v2(
        lineage,
        audio_intent=audio_intent,
        variant_assignment=None,
        audio_id=None,
    )
    lineage_path = output_path.with_suffix(
        output_path.suffix + ".generated_asset_lineage.json"
    )
    atomic_write_text(
        lineage_path,
        json.dumps(lineage, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    caption_generation = {
        "schema": "campaign_factory.caption_generation.v1",
        "workflow": "accepted_soul_still_to_static_mp4",
        "animationMode": "static_image_mp4",
        "paidGeneration": False,
        "estimatedCostUsd": 0,
        "captionHash": caption_hash,
        "captionBurned": False,
        "staticMp4Render": render,
        "audioIntentPath": str(audio_intent_path),
        "generatedAssetLineagePath": str(lineage_path),
        "generatedAssetLineage": lineage,
        "humanReviewRequired": True,
    }
    metadata = {
        "staticMp4Render": render,
        "lockedStatic": True,
        "zeroCostFallback": True,
        "humanReviewRequired": True,
        "audioIntentPath": str(audio_intent_path),
        "generatedAssetLineagePath": str(lineage_path),
        "generatedAssetLineage": lineage,
    }
    now = utc_now()
    factory.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path,
         filename, media_type, content_surface, caption, caption_hash,
         caption_generation_json, recipe, target_ratio, metadata_json,
         audit_status, review_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', '', ?, ?, 'static_mp4',
                '9:16', ?, 'pending', 'review_ready', ?, ?)
        """,
        (
            rendered_id,
            campaign["id"],
            source_asset["id"],
            content_fingerprint,
            str(output_path),
            str(output_path),
            output_path.name,
            caption_hash,
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


def _source_prompt(source_asset: dict[str, Any]) -> dict[str, Any]:
    raw = source_asset.get("source_prompt")
    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("source asset prompt metadata is invalid") from exc
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("source asset prompt metadata must be a JSON object")
    if not str(payload.get("promptId") or "").strip():
        raise ValueError("static MP4 registration requires source promptId")
    if not str(payload.get("referenceId") or "").strip():
        raise ValueError("static MP4 registration requires source referenceId")
    return payload


def _source_asset_for_campaign(factory: Any, campaign_id: str) -> dict[str, Any]:
    row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? ORDER BY created_at, id LIMIT 1",
        (campaign_id,),
    ).fetchone()
    if not row:
        raise ValueError(
            "campaign must have at least one source asset before static MP4 registration"
        )
    return dict(row)
