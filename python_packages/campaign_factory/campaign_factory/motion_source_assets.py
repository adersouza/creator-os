"""Exact local source-video registration for Retake and Extend tasks."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .core import new_id, sha256_file, slugify
from .persistence import utc_now


def ensure_motion_edit_source_asset(
    factory: Any,
    *,
    campaign: Mapping[str, Any],
    model_slug: str,
    source_video: Path,
    source_hash: str,
    motion_task: str,
) -> dict[str, Any]:
    """Register the exact source video without inventing a still fallback."""

    existing = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
        (campaign["id"], source_hash),
    ).fetchone()
    if existing is not None:
        row = dict(existing)
        stored = Path(str(row.get("stored_path") or "")).expanduser()
        if (
            row.get("media_type") != "video"
            or stored.is_symlink()
            or not stored.is_file()
            or sha256_file(stored.resolve()) != source_hash
        ):
            raise RuntimeError("motion_edit_existing_source_asset_mismatch")
        return row

    model = factory.conn.execute(
        "SELECT id FROM models WHERE slug = ?", (model_slug,)
    ).fetchone()
    if model is None:
        raise RuntimeError(f"motion_edit_campaign_model_missing:{model_slug}")
    dirs = factory.domains.campaign_dirs(model_slug, str(campaign["slug"]))
    suffix = source_video.suffix.lower() or ".mp4"
    stored = dirs["sources"] / (
        f"{slugify(source_video.stem)}_{source_hash[:12]}{suffix}"
    )
    stored.parent.mkdir(parents=True, exist_ok=True)
    if stored.exists() or stored.is_symlink():
        if (
            stored.is_symlink()
            or not stored.is_file()
            or sha256_file(stored) != source_hash
        ):
            raise FileExistsError(f"motion_edit_source_output_collision:{stored}")
    elif source_video.resolve() != stored.resolve():
        partial = stored.with_name(f".{stored.name}.{source_hash[:12]}.partial")
        if partial.exists() or partial.is_symlink():
            raise FileExistsError(f"motion_edit_source_partial_collision:{partial}")
        shutil.copy2(source_video, partial)
        if partial.is_symlink() or sha256_file(partial) != source_hash:
            raise RuntimeError("motion_edit_source_copy_hash_mismatch")
        os.replace(partial, stored)
    else:
        stored = source_video

    source_id = new_id("src")
    now = utc_now()
    source_prompt = {
        "schema": "campaign_factory.motion_edit_source.v1",
        "motionTask": motion_task,
        "sourceVideo": {"path": str(source_video), "sha256": source_hash},
        "staticFallbackCreated": False,
    }
    with factory.conn:
        factory.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, content_surface, platform, source_prompt, notes,
             account_ids_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', 'instagram', ?, ?, '[]',
                    'imported', ?, ?)
            """,
            (
                source_id,
                campaign["id"],
                model["id"],
                source_hash,
                str(source_video),
                str(stored),
                stored.name,
                json.dumps(source_prompt, ensure_ascii=False, sort_keys=True),
                "Exact source video for local motion retake/extend.",
                now,
                now,
            ),
        )
    row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError("motion_edit_source_asset_registration_missing")
    return dict(row)
