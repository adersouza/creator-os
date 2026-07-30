from __future__ import annotations

import copy
import hashlib
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
from .derived_stills import derived_receipt_for_source
from .lineage_v2 import build_lineage_v2_core, finalize_lineage_v2
from .persistence import utc_now


def run_static_mp4_stage(
    factory: Any,
    *,
    campaign_slug: str,
    still_path: Path,
    content_intent: str | None = None,
    duration_seconds: float | None = None,
    dry_run: bool = True,
    apply: bool = False,
    allow_upscale: bool = False,
) -> dict[str, Any]:
    """Create the mandatory zero-cost static fallback for an accepted Soul still."""
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    dirs = factory.domains.campaign_dirs(model_slug, campaign["slug"])
    still = Path(still_path).expanduser().resolve()
    if not still.exists() or not still.is_file():
        raise FileNotFoundError(f"accepted still not found: {still}")
    still_fingerprint = sha256_file(still)
    source_asset = _source_asset_for_campaign(
        factory,
        campaign["id"],
        still_path=still,
        still_fingerprint=still_fingerprint,
    )
    selected_duration = (
        float(duration_seconds)
        if duration_seconds is not None
        else _duration_for_still(still_fingerprint)
    )
    output_path = (
        dirs["rendered"] / f"{slugify(still.stem)}_{still_fingerprint[:12]}_static.mp4"
    )
    pipeline_job = factory.domains.events.create_pipeline_job(
        "static_mp4",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "sourceAssetId": source_asset["id"],
            "stillPath": str(still),
            "outputPath": str(output_path),
            "durationSeconds": selected_duration,
            "dryRun": dry_run,
            "apply": apply,
            "paidGeneration": False,
        },
    )
    factory.domains.events.start_pipeline_job(pipeline_job["id"])
    try:
        registered_asset = (
            _existing_static_asset(
                factory,
                campaign_id=campaign["id"],
                parent_still_hash=still_fingerprint,
                content_intent=content_intent,
            )
            if apply and not dry_run
            else None
        )
        reused = registered_asset is not None
        if reused:
            metadata = _json_object(registered_asset.get("metadata_json"))
            render = metadata.get("staticMp4Render")
            if not isinstance(render, dict):
                raise ValueError("registered static MP4 is missing render metadata")
        else:
            render = _invoke_reel_factory_static_mp4(
                factory,
                still_path=still,
                output_path=output_path,
                duration_seconds=selected_duration,
                dry_run=dry_run or not apply,
                allow_upscale=allow_upscale,
            )
        _validate_render(render)
        if reused and registered_asset is not None:
            registered_asset = _repair_existing_static_lineage(
                factory,
                asset=registered_asset,
                source_asset=source_asset,
                still=still,
            )
        if apply and not dry_run and not reused:
            registered_asset = _register_rendered_asset(
                factory,
                campaign=campaign,
                source_asset=source_asset,
                render=render,
                content_intent=content_intent,
            )
        generation_attempt_id = (
            _ensure_static_generation_lineage(
                factory,
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                source_asset_id=source_asset["id"],
                source_sha256=still_fingerprint,
                registered_asset=registered_asset,
                render=render,
                reused=reused,
            )
            if registered_asset is not None
            else None
        )
        result = {
            "schema": "campaign_factory.static_mp4_stage_run.v1",
            "campaign": campaign_slug,
            "dryRun": dry_run or not apply,
            "apply": bool(apply and not dry_run),
            "paidGeneration": False,
            "sourceAssetId": source_asset["id"],
            "reused": reused,
            "render": render,
            "registeredAsset": registered_asset,
            "generationAttemptId": generation_attempt_id,
            "pipelineJobId": pipeline_job["id"],
        }
        factory.domains.events.finish_pipeline_job(
            pipeline_job["id"], sanitize_for_storage(result)
        )
        return result
    except Exception as exc:
        factory.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _ensure_static_generation_lineage(
    factory: Any,
    *,
    campaign_id: str,
    pipeline_job_id: str,
    source_asset_id: str,
    source_sha256: str,
    registered_asset: dict[str, Any],
    render: dict[str, Any],
    reused: bool,
) -> str:
    rendered_asset_id = str(registered_asset["id"])
    existing = factory.conn.execute(
        """
        SELECT id
        FROM generation_attempts
        WHERE rendered_asset_id = ?
        ORDER BY created_at, id
        LIMIT 1
        """,
        (rendered_asset_id,),
    ).fetchone()
    if existing is not None:
        return str(existing["id"])

    output_path = Path(str(registered_asset["output_path"])).expanduser().resolve()
    if not output_path.is_file() or output_path.is_symlink():
        raise FileNotFoundError(f"registered static MP4 is unsafe: {output_path}")
    output_sha256 = sha256_file(output_path)
    if output_sha256 != str(registered_asset["content_hash"]):
        raise RuntimeError("registered static MP4 content hash mismatch")
    now = utc_now()
    blob = factory.conn.execute(
        "SELECT id FROM generation_output_blobs WHERE content_sha256 = ?",
        (output_sha256,),
    ).fetchone()
    blob_id = str(blob["id"]) if blob is not None else f"blob_{output_sha256}"
    attempt_id = new_id("generation_attempt")
    request = {
        "sourceAssetId": source_asset_id,
        "sourceSha256": source_sha256,
        "outputSha256": output_sha256,
        "durationSeconds": render["durationSeconds"],
    }
    request_fingerprint = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    lineage = {
        "schema": "campaign_factory.generation_lineage_edge.v1",
        "modelId": "reel_factory.static_mp4",
        "motionTask": "static_image_mp4",
        "requestFingerprint": request_fingerprint,
        "source": {
            "assetId": source_asset_id,
            "sha256": source_sha256,
            "role": "generation_input",
        },
        "output": {"blobId": blob_id, "sha256": output_sha256},
    }
    with factory.conn:
        factory.conn.execute(
            """
            INSERT OR IGNORE INTO generation_output_blobs
            (id, content_sha256, byte_size, media_type, created_at)
            VALUES (?, ?, ?, 'video', ?)
            """,
            (blob_id, output_sha256, output_path.stat().st_size, now),
        )
        factory.conn.execute(
            """
            INSERT INTO generation_attempts
            (id, campaign_id, pipeline_job_id, source_asset_id, rendered_asset_id,
             output_blob_id, request_fingerprint, model_id, motion_task, prompt_sha256,
             source_sha256, admission_fingerprint, input_json, worker_result_json,
             attempted_output_path, duplicate_disposition, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'reel_factory.static_mp4',
                    'static_image_mp4', NULL, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                campaign_id,
                pipeline_job_id,
                source_asset_id,
                rendered_asset_id,
                blob_id,
                request_fingerprint,
                source_sha256,
                json.dumps(request, sort_keys=True),
                json.dumps(sanitize_for_storage(render), sort_keys=True),
                str(output_path),
                "reused_canonical_path" if reused else "canonical_output",
                now,
            ),
        )
        factory.conn.execute(
            """
            INSERT INTO generation_lineage_edges
            (id, generation_attempt_id, source_asset_id, rendered_asset_id,
             output_blob_id, relation, lineage_json, created_at)
            VALUES (?, ?, ?, ?, ?, 'generated_output', ?, ?)
            """,
            (
                new_id("generation_edge"),
                attempt_id,
                source_asset_id,
                rendered_asset_id,
                blob_id,
                json.dumps(sanitize_for_storage(lineage), sort_keys=True),
                now,
            ),
        )
    return attempt_id


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
        "-m",
        "reel_factory.static_mp4",
        "--still",
        str(still_path),
        "--out",
        str(output_path),
        "--duration",
        str(duration_seconds),
        "--audio-mode",
        "embedded_trending_audio",
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
    content_intent: str | None,
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
        metadata = _json_object(existing["metadata_json"])
        if content_intent is not None and metadata.get("contentIntent") != (
            content_intent
        ):
            raise ValueError("static MP4 existing content intent mismatch")
        return dict(existing)
    caption_hash = factory.domains.publishability.text_hash("")
    source_prompt = _source_prompt(source_asset)
    derived_still_source = derived_receipt_for_source(source_asset)
    upstream_lineage = _enriched_upstream_lineage(
        source_prompt, output_still=Path(render["stillPath"])
    )
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
    if derived_still_source is not None:
        lineage["derivedStillSource"] = derived_still_source
        lineage["captionPlacementConstraints"] = {
            "avoidGarmentRegion": True,
            "noSafeLanePolicy": "clean_reel",
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
    if content_intent is not None:
        metadata["contentIntent"] = content_intent
    if derived_still_source is not None:
        metadata["derivedStillSource"] = derived_still_source
        metadata["captionPlacementConstraints"] = {
            "avoidGarmentRegion": True,
            "noSafeLanePolicy": "clean_reel",
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


def _repair_existing_static_lineage(
    factory: Any,
    *,
    asset: dict[str, Any],
    source_asset: dict[str, Any],
    still: Path,
) -> dict[str, Any]:
    source_prompt = _source_prompt(source_asset)
    upstream = _enriched_upstream_lineage(source_prompt, output_still=still)
    upstream_features = (
        upstream.get("features") if isinstance(upstream.get("features"), dict) else {}
    )
    upstream_source = (
        upstream.get("source") if isinstance(upstream.get("source"), dict) else {}
    )
    lineage_path = str(upstream_source.get("sourceLineagePath") or "").strip()
    if not upstream_features and not lineage_path:
        return asset

    metadata = _json_object(asset.get("metadata_json"))
    caption_generation = _json_object(asset.get("caption_generation_json"))
    lineage = metadata.get("generatedAssetLineage")
    if not isinstance(lineage, dict):
        lineage = caption_generation.get("generatedAssetLineage")
    if not isinstance(lineage, dict):
        raise ValueError("registered static MP4 is missing generated lineage")
    updated_lineage = copy.deepcopy(lineage)
    if upstream_features:
        updated_lineage["features"] = copy.deepcopy(upstream_features)
    if lineage_path:
        updated_lineage.setdefault("source", {})["sourceLineagePath"] = lineage_path
    if updated_lineage == lineage:
        return asset

    sidecar_value = str(
        metadata.get("generatedAssetLineagePath")
        or caption_generation.get("generatedAssetLineagePath")
        or ""
    ).strip()
    sidecar = (
        Path(sidecar_value).expanduser().resolve()
        if sidecar_value
        else Path(asset["output_path"]).with_suffix(
            Path(asset["output_path"]).suffix + ".generated_asset_lineage.json"
        )
    )
    atomic_write_text(
        sidecar,
        json.dumps(updated_lineage, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    metadata["generatedAssetLineage"] = updated_lineage
    metadata["generatedAssetLineagePath"] = str(sidecar)
    caption_generation["generatedAssetLineage"] = updated_lineage
    caption_generation["generatedAssetLineagePath"] = str(sidecar)
    factory.conn.execute(
        """
        UPDATE rendered_assets
        SET metadata_json = ?, caption_generation_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(
                sanitize_for_storage(metadata), ensure_ascii=False, sort_keys=True
            ),
            json.dumps(
                sanitize_for_storage(caption_generation),
                ensure_ascii=False,
                sort_keys=True,
            ),
            utc_now(),
            asset["id"],
        ),
    )
    factory.conn.commit()
    return dict(
        factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset["id"],)
        ).fetchone()
    )


def _enriched_upstream_lineage(
    source_prompt: dict[str, Any], *, output_still: Path
) -> dict[str, Any]:
    raw = source_prompt.get("generatedAssetLineage")
    lineage = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    direct_path = _direct_reference_lineage_path(lineage, output_still)
    if direct_path is None:
        return lineage
    direct = _read_json_object(direct_path)
    _validate_direct_reference_lineage(
        direct,
        path=direct_path,
        output_still=output_still,
        expected_prompt_id=str(source_prompt.get("promptId") or ""),
    )
    features = direct.get("features")
    if isinstance(features, dict):
        existing = (
            lineage.get("features") if isinstance(lineage.get("features"), dict) else {}
        )
        merged = dict(features)
        merged.update(
            {
                key: value
                for key, value in existing.items()
                if value not in (None, "", "unknown")
            }
        )
        lineage["features"] = merged
    lineage.setdefault("source", {})["sourceLineagePath"] = str(direct_path)
    return lineage


def _direct_reference_lineage_path(
    lineage: dict[str, Any], output_still: Path
) -> Path | None:
    source = lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
    candidates: list[Path] = []
    explicit = str(source.get("sourceLineagePath") or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    stem = output_still.stem
    suffix = "_direct_reference_9x16"
    if stem.endswith(suffix):
        candidates.append(
            output_still.with_name(
                f"{stem.removesuffix(suffix)}.direct_reference_lineage.json"
            )
        )
    candidates.extend(
        [
            output_still.with_suffix(".direct_reference_lineage.json"),
            output_still.with_suffix(
                output_still.suffix + ".direct_reference_lineage.json"
            ),
        ]
    )
    for candidate in dict.fromkeys(path.resolve() for path in candidates):
        if candidate.is_file():
            return candidate
    return None


def _validate_direct_reference_lineage(
    lineage: dict[str, Any],
    *,
    path: Path,
    output_still: Path,
    expected_prompt_id: str,
) -> None:
    assets = lineage.get("assets") if isinstance(lineage.get("assets"), dict) else {}
    local_paths = (
        assets.get("localPaths") if isinstance(assets.get("localPaths"), dict) else {}
    )
    recorded = str(local_paths.get("image") or "").strip()
    if recorded:
        recorded_path = Path(recorded).expanduser().resolve()
        if recorded_path != output_still.resolve() and (
            not recorded_path.is_file()
            or sha256_file(recorded_path) != sha256_file(output_still)
        ):
            raise ValueError(
                f"direct-reference lineage does not match accepted still: {path}"
            )
    generation = (
        lineage.get("generation") if isinstance(lineage.get("generation"), dict) else {}
    )
    captured = str(generation.get("capturedHiggsfieldPrompt") or "").strip()
    if captured and expected_prompt_id.startswith("prompt_higgsfield_"):
        resolved = (
            "prompt_higgsfield_"
            + hashlib.sha256(captured.encode("utf-8")).hexdigest()[:16]
        )
        if resolved != expected_prompt_id:
            raise ValueError(
                "direct-reference lineage prompt does not match source prompt"
            )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"direct-reference lineage is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"direct-reference lineage must be an object: {path}")
    return value


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
    derived = derived_receipt_for_source(source_asset)
    if derived is not None:
        payload = {
            **payload,
            "promptId": payload.get("promptId")
            or f"prompt_derived_{str(source_asset['content_hash'])[:16]}",
            "referenceId": payload.get("referenceId")
            or f"source_{derived['rootSourceAssetId']}",
            "generatedAssetLineage": payload.get("generatedAssetLineage")
            or {
                "schema": "campaign_factory.generated_asset_lineage.v2",
                "source": {
                    "assetId": source_asset["id"],
                    "sha256": source_asset["content_hash"],
                    "derivedStillSource": derived,
                },
                "features": {
                    "sourceTier": derived["sourceTier"],
                    "operation": derived["operation"],
                    "provider": derived.get("provider"),
                    "model": derived.get("model"),
                    "batchingFormat": (derived.get("evidence") or {}).get(
                        "batchingFormat"
                    ),
                    "requestFingerprint": (derived.get("evidence") or {}).get(
                        "requestFingerprint"
                    ),
                },
            },
        }
    if not str(payload.get("promptId") or "").strip():
        raise ValueError("static MP4 registration requires source promptId")
    if not str(payload.get("referenceId") or "").strip():
        raise ValueError("static MP4 registration requires source referenceId")
    return payload


def _existing_static_asset(
    factory: Any,
    *,
    campaign_id: str,
    parent_still_hash: str,
    content_intent: str | None,
) -> dict[str, Any] | None:
    rows = factory.conn.execute(
        """
        SELECT * FROM rendered_assets
        WHERE campaign_id = ? AND recipe = 'static_mp4'
        ORDER BY created_at, id
        """,
        (campaign_id,),
    ).fetchall()
    for row in rows:
        asset = dict(row)
        metadata = _json_object(asset.get("metadata_json"))
        if content_intent is not None and metadata.get("contentIntent") != (
            content_intent
        ):
            continue
        lineage = metadata.get("generatedAssetLineage")
        source = lineage.get("source") if isinstance(lineage, dict) else None
        if not isinstance(source, dict) or source.get("parentStillHash") != (
            parent_still_hash
        ):
            continue
        output = Path(asset["output_path"])
        if output.is_file() and sha256_file(output) == asset["content_hash"]:
            return asset
    return None


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _duration_for_still(still_fingerprint: str) -> float:
    """Stable 5–7 second variation so retries never change the asset recipe."""
    milliseconds = int(still_fingerprint[:8], 16) % 2001
    return round(5.0 + milliseconds / 1000.0, 3)


def _source_asset_for_campaign(
    factory: Any,
    campaign_id: str,
    *,
    still_path: Path,
    still_fingerprint: str,
) -> dict[str, Any]:
    rows = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? ORDER BY created_at, id",
        (campaign_id,),
    ).fetchall()
    if not rows:
        raise ValueError(
            "campaign must have at least one source asset before static MP4 registration"
        )
    assets = [dict(row) for row in rows]
    matches = [
        asset
        for asset in assets
        if _source_records_accepted_still(
            asset,
            still_path=still_path,
            still_fingerprint=still_fingerprint,
        )
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            "accepted still lineage is ambiguous across multiple campaign source assets"
        )
    if len(assets) == 1:
        return assets[0]
    raise ValueError(
        "accepted still does not match generated-image QC lineage for any campaign source asset"
    )


def _source_records_accepted_still(
    source_asset: dict[str, Any],
    *,
    still_path: Path,
    still_fingerprint: str,
) -> bool:
    derived = derived_receipt_for_source(source_asset)
    if derived is not None:
        stored = Path(str(source_asset.get("stored_path") or "")).expanduser()
        return bool(
            source_asset.get("status") == "approved"
            and (derived.get("approval") or {}).get("decision") == "approved"
            and (derived.get("approval") or {}).get("exactOutputSha256")
            == still_fingerprint
            and stored.resolve() == still_path
            and source_asset.get("content_hash") == still_fingerprint
        )
    prompt = _json_object(source_asset.get("source_prompt"))
    lineage = prompt.get("generatedAssetLineage")
    review = lineage.get("review") if isinstance(lineage, dict) else None
    qc = review.get("generatedImageQc") if isinstance(review, dict) else None
    results = qc.get("results") if isinstance(qc, dict) else None
    if not isinstance(results, list):
        return False
    for result in results:
        if not isinstance(result, dict) or result.get("postable") is not True:
            continue
        raw_path = result.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        candidate = Path(raw_path).expanduser().resolve()
        if candidate == still_path:
            return True
        if candidate.is_file() and sha256_file(candidate) == still_fingerprint:
            return True
    return False
