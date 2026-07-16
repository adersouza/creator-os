from __future__ import annotations

import json
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path

from campaign_factory.core import CampaignFactory


def add_audit_report(
    cf: CampaignFactory,
    *,
    rendered_asset_id: str = "asset_1",
    audit_id: str = "audit_1",
    status: str = "approved_candidate",
    overall_verdict: str = "pass",
    failed: list[str] | None = None,
    warnings: list[str] | None = None,
    warning_codes: list[str] | None = None,
    upload_ready: bool = True,
) -> dict:
    asset = cf.conn.execute(
        "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
    ).fetchone()
    assert asset is not None
    failed = failed or []
    warnings = warnings or []
    warning_codes = warning_codes or []
    report_path = Path(asset["campaign_path"]).with_suffix(f".{audit_id}.json")
    report_payload = {
        "readinessSummary": {
            "uploadReady": upload_ready,
            "blockingReasons": failed,
            "warnings": warnings,
            "blockingCodes": [],
            "warningCodes": warning_codes,
            "visualQcStatus": "passed",
            "identityVerificationStatus": "passed",
        },
        "visualQcStatus": "passed",
        "identityVerificationStatus": "passed",
        "visualQc": {"status": "passed"},
        "identityVerification": {"status": "passed"},
        "overallVerdict": overall_verdict,
        "warnings": warnings,
        "failedChecks": failed,
        "error": None,
    }
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")
    cf.conn.execute(
        """
        INSERT INTO audit_reports
        (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score, status,
         layers_json, verdicts_json, overall_verdict, files_analyzed, failed_checks_json, warnings_json, created_at)
        VALUES (?, ?, ?, 'run_1', ?, ?, ?, '{}', '{}', ?, 1, ?, ?, ?)
        """,
        (
            audit_id,
            asset["campaign_id"],
            rendered_asset_id,
            str(report_path),
            100 if status == "approved_candidate" else 0,
            status,
            overall_verdict,
            json.dumps(failed),
            json.dumps(warnings),
            "2026-01-01T00:00:00+00:00",
        ),
    )
    cf.conn.commit()
    return {"id": audit_id, "path": str(report_path)}


def ensure_exportable_distribution_plan(
    cf: CampaignFactory,
    rendered_asset_id: str = "asset_1",
    *,
    instagram_account_id: str = "ig_1",
    planned_window_start: str = "2026-01-02T10:00:00+00:00",
    planned_window_end: str = "2026-01-02T10:30:00+00:00",
) -> dict:
    existing = cf.conn.execute(
        "SELECT * FROM distribution_plans WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
        (rendered_asset_id,),
    ).fetchone()
    if existing:
        return cf.domains.distribution.distribution_plan_payload(dict(existing))
    return cf.domains.distribution.create_distribution_plan(
        rendered_asset_id,
        instagram_account_id=instagram_account_id,
        planned_window_start=planned_window_start,
        planned_window_end=planned_window_end,
    )


def add_schedule_safe_production_asset(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    asset_id: str,
    source: dict,
    parent_asset_id: str | None = None,
    caption_generation: dict | None = None,
    caption_context: dict | None = None,
    filename: str | None = None,
    review_state: str = "approved",
    created_at: str | None = None,
) -> dict:
    campaign = cf.domains.campaign_by_slug("may")
    rendered_path = tmp_path / (filename or f"{asset_id}.mp4")
    rendered_path.write_bytes(f"rendered-{asset_id}".encode())
    now = created_at or datetime.now(UTC).isoformat()
    context = caption_context or {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": f"caption_hash_{asset_id}",
        "caption_text": "caption",
        "caption_bank": "test_bank",
        "caption_banks": ["test_bank"],
        "creator_mix": "Test",
        "render_recipe": "v01_original",
        "rendered_output": str(rendered_path),
        "captionPlacementPolicy": "focal_safe_v1",
        "captionPlacementDecision": {
            "status": "passed",
            "selectedLane": "top",
            "reason": "test fixture placement passed",
        },
    }
    generation = caption_generation or {
        "instagram_post_caption": "new fit today",
        "audioIntent": {
            "schema": "pipeline.audio_intent.v1",
            "mode": "native_platform_audio",
            "required": False,
            "status": "not_required",
        },
    }
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, parent_asset_id, content_hash, output_path, campaign_path, filename,
         caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
         caption_generation_json, creator_mix, creator_model, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'caption', ?, ?, 'v01_original', 'passed', ?,
                ?, 'Test', 'Test', ?, ?)
        """,
        (
            asset_id,
            campaign["id"],
            source["id"],
            parent_asset_id,
            f"hash_{asset_id}",
            str(rendered_path),
            str(rendered_path),
            rendered_path.name,
            f"caption_hash_{asset_id}",
            json.dumps(context, ensure_ascii=False, sort_keys=True),
            review_state,
            json.dumps(generation, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    cf.conn.commit()
    add_audit_report(cf, rendered_asset_id=asset_id, audit_id=f"audit_{asset_id}")
    return dict(
        cf.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    )


def add_variant_fixture(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    variant_asset_id: str,
    variant_family_id: str = "vfam_winner",
    variant_index: int = 1,
    family_name: str = "cover_frame",
    quality_score: int = 95,
    content_hash: str | None = None,
) -> dict:
    parent = cf.domains.rendered_asset("asset_1")
    rendered_path = tmp_path / f"{variant_asset_id}.mp4"
    rendered_path.write_bytes(f"rendered-{variant_asset_id}".encode())
    now = "2026-01-02T00:00:00+00:00"
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
         caption_generation_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'contentforge_variant_pack', 'passed', 'approved', '{}', ?, ?)
        """,
        (
            variant_asset_id,
            parent["campaign_id"],
            parent["source_asset_id"],
            content_hash or f"hash_{variant_asset_id}",
            str(rendered_path),
            str(rendered_path),
            rendered_path.name,
            parent.get("caption"),
            parent.get("caption_hash"),
            parent.get("caption_outcome_context_json") or "{}",
            now,
            now,
        ),
    )
    variant = cf.domains.variant_lineage.register_variant_asset(
        parent_asset_id="asset_1",
        variant_asset_id=variant_asset_id,
        variant_family_id=variant_family_id,
        variant_index=variant_index,
        operations=[
            {
                "type": "contentforge_result",
                "result": {
                    "familyName": family_name,
                    "uploadReady": True,
                    "qualityScore": quality_score,
                    "differenceScore": 35,
                    "operationDiversityScore": 35,
                    "captionReadabilityScore": 96,
                    "focalSafetyScore": 96,
                },
            }
        ],
        contentforge_preset="caption_safe_v2",
    )
    audit_path = rendered_path.with_suffix(".audit.json")
    audit_path.write_text(
        json.dumps(
            {
                "readinessSummary": {
                    "uploadReady": True,
                    "visualQcStatus": "passed",
                    "identityVerificationStatus": "passed",
                },
                "visualQcStatus": "passed",
                "identityVerificationStatus": "passed",
                "variant": {
                    "familyName": family_name,
                    "uploadReady": True,
                    "qualityScore": quality_score,
                    "differenceScore": 35,
                    "operationDiversityScore": 35,
                    "captionReadabilityScore": 96,
                    "focalSafetyScore": 96,
                },
            }
        ),
        encoding="utf-8",
    )
    cf.conn.execute(
        """
        INSERT INTO audit_reports
        (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score, status,
         layers_json, verdicts_json, overall_verdict, files_analyzed, failed_checks_json, warnings_json, created_at)
        VALUES (?, ?, ?, 'run_variant', ?, ?, 'pass', '{}', '{}', 'pass', 1, '[]', '[]', ?)
        """,
        (
            f"audit_{variant_asset_id}",
            parent["campaign_id"],
            variant_asset_id,
            str(audit_path),
            quality_score,
            now,
        ),
    )
    cf.conn.commit()
    return variant


def add_inventory_parent_fixture(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    asset_id: str,
    campaign_slug: str = "stacey_archive_marketing_20260606",
    creator: str = "Stacey",
    instagram_post_caption: str | None = "new post is up",
    audio_required: bool = False,
    caption_placement_qc: bool = True,
) -> dict:
    try:
        campaign = cf.domains.campaign_by_slug(campaign_slug)
    except ValueError:
        folder = tmp_path / f"inputs_{campaign_slug}"
        folder.mkdir()
        (folder / f"{campaign_slug}.mp4").write_bytes(b"source")
        cf.domains.asset_import.import_folder(
            folder, campaign_slug=campaign_slug, model_slug="stacey"
        )
        campaign = cf.domains.campaign_by_slug(campaign_slug)
    source = cf.domains.asset_import.assets_for_campaign(campaign["id"])[0]
    rendered_path = tmp_path / f"{asset_id}.mp4"
    rendered_path.write_bytes(f"rendered-{asset_id}".encode())
    now = "2026-01-01T00:00:00+00:00"
    caption_context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": f"caption_hash_{asset_id}",
        "caption_text": "caption",
        "caption_bank": "test_bank",
        "caption_banks": ["test_bank"],
        "creator_mix": creator,
        "render_recipe": "v01_original",
        "rendered_output": str(rendered_path),
        "visualQcStatus": "passed",
        "identityVerificationStatus": "passed",
        "visualQc": {"status": "passed"},
        "identityVerification": {"status": "passed"},
    }
    if caption_placement_qc:
        caption_context["captionPlacementPolicy"] = "focal_safe_v1"
        caption_context["captionPlacementDecision"] = {
            "status": "passed",
            "selectedLane": "top",
            "reason": "test fixture placement passed",
        }
    audio_intent = {
        "schema": "pipeline.audio_intent.v1",
        "mode": "native_platform_audio",
        "required": audio_required,
        "status": "not_required",
    }
    if audio_required:
        audio_intent = {
            "schema": "pipeline.audio_intent.v1",
            "mode": "native_platform_audio",
            "required": True,
            "status": "attached",
            "operator_selection": {
                "audio_id": f"audio_{asset_id}",
                "track_id": f"audio_{asset_id}",
                "track_name": "Inventory Test Audio",
                "selected_at": now,
                "attached_at": now,
                "notes": "Audio is embedded in the registered MP4.",
            },
        }
    caption_generation = {"audioIntent": audio_intent}
    if instagram_post_caption is not None:
        caption_generation["instagram_post_caption"] = instagram_post_caption
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
         caption_generation_json, creator_mix, creator_model, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'caption', ?, ?, 'v01_original', 'passed', 'approved',
                ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            campaign["id"],
            source["id"],
            f"hash_{asset_id}",
            str(rendered_path),
            str(rendered_path),
            rendered_path.name,
            f"caption_hash_{asset_id}",
            json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
            json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
            creator,
            creator,
            now,
            now,
        ),
    )
    cf.conn.commit()
    add_audit_report(cf, rendered_asset_id=asset_id, audit_id=f"audit_{asset_id}")
    return cf.domains.variant_lineage.register_parent_reel(asset_id, operator="tester")


def table_count(cf: CampaignFactory, table: str) -> int:
    exists = cf.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if not exists:
        return 0
    return int(cf.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


def write_surface_image(path: Path) -> Path:
    return write_rgb_png(path, 1080, 1920)


def write_rgb_png(
    path: Path,
    width: int,
    height: int,
    *,
    color: tuple[int, int, int] = (200, 80, 120),
    bars: set[str] | None = None,
) -> Path:
    bars = bars or set()
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            is_bar = (
                ("top" in bars and y < max(1, height // 12))
                or ("bottom" in bars and y >= height - max(1, height // 12))
                or ("left" in bars and x < max(1, width // 12))
                or ("right" in bars and x >= width - max(1, width // 12))
            )
            row.extend((0, 0, 0) if is_bar else color)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


def add_story_quality_asset(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    asset_id: str,
    width: int = 1080,
    height: int = 1920,
    bars: set[str] | None = None,
    quality_metadata: dict | None = None,
) -> dict:
    asset = add_surface_asset_fixture(
        cf,
        tmp_path,
        asset_id=asset_id,
        content_surface="story",
        media_type="image",
        instagram_post_caption="",
        target_ratio="9:16",
    )
    image_path = write_rgb_png(tmp_path / f"{asset_id}.png", width, height, bars=bars)
    generation = json.loads(asset["caption_generation_json"] or "{}")
    if quality_metadata:
        generation["storyQuality"] = quality_metadata
    story_asset_class = generation.get("story_asset_class") or "story_selfie"
    story_intent = generation.get("story_intent") or "casual_selfie"
    story_style = generation.get("story_style") or "selfie"
    cf.conn.execute(
        """
        UPDATE rendered_assets
        SET output_path = ?, campaign_path = ?, filename = ?, content_hash = ?,
            caption_generation_json = ?, target_ratio = ?,
            story_asset_class = ?, story_intent = ?, story_style = ?
        WHERE id = ?
        """,
        (
            str(image_path),
            str(image_path),
            image_path.name,
            f"hash_{asset_id}_{width}_{height}_{'_'.join(sorted(bars or []))}",
            json.dumps(generation, ensure_ascii=False, sort_keys=True),
            "9:16" if width * 16 == height * 9 else f"{width}:{height}",
            story_asset_class,
            story_intent,
            story_style,
            asset_id,
        ),
    )
    cf.conn.commit()
    return dict(
        cf.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    )


def add_surface_asset_fixture(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    asset_id: str,
    creator: str = "Stacey",
    content_surface: str = "feed_single",
    media_type: str = "image",
    instagram_post_caption: str | None = "new post",
    target_ratio: str = "1:1",
    review_state: str = "approved",
) -> dict:
    campaign_slug = "stacey_surface_inventory_20260606"
    try:
        campaign = cf.domains.campaign_by_slug(campaign_slug)
    except ValueError:
        folder = tmp_path / "surface_inputs"
        folder.mkdir()
        (folder / "surface-source.jpg").write_bytes(b"source-image")
        cf.domains.asset_import.import_folder(
            folder, campaign_slug=campaign_slug, model_slug="stacey"
        )
        campaign = cf.domains.campaign_by_slug(campaign_slug)
    source = cf.domains.asset_import.assets_for_campaign(campaign["id"])[0]
    suffix = ".mp4" if media_type == "video" else ".png"
    media_path = tmp_path / f"{asset_id}{suffix}"
    if media_type == "image" and content_surface == "story":
        write_rgb_png(media_path, 1080, 1920)
        target_ratio = "9:16"
    else:
        media_path.write_bytes(f"surface-{asset_id}".encode())
    caption_context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": f"caption_hash_{asset_id}",
        "caption_text": "burned caption",
        "creator_mix": creator,
        "render_recipe": "surface_fixture",
        "visualQcStatus": "passed",
        "identityVerificationStatus": "passed",
        "visualQc": {"status": "passed"},
        "identityVerification": {"status": "passed"},
    }
    caption_generation = {}
    if instagram_post_caption is not None:
        caption_generation["instagram_post_caption"] = instagram_post_caption
    if content_surface == "story":
        caption_generation.update(
            {
                "story_asset_class": "story_selfie",
                "story_intent": "casual_selfie",
                "story_style": "selfie",
            }
        )
    now = "2026-06-06T00:00:00+00:00"
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         caption, caption_hash, caption_outcome_context_json, caption_generation_json,
         recipe, target_ratio, audit_status, review_state, creator_mix, creator_model,
         content_surface, media_type, story_asset_class, story_intent, story_style, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'burned caption', ?, ?, ?, 'surface_fixture', ?,
                'passed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            campaign["id"],
            source["id"],
            f"hash_{asset_id}",
            str(media_path),
            str(media_path),
            media_path.name,
            f"caption_hash_{asset_id}",
            json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
            json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
            target_ratio,
            review_state,
            creator,
            creator,
            content_surface,
            media_type,
            "story_selfie" if content_surface == "story" else None,
            "casual_selfie" if content_surface == "story" else None,
            "selfie" if content_surface == "story" else None,
            now,
            now,
        ),
    )
    cf.conn.commit()
    return dict(
        cf.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    )
