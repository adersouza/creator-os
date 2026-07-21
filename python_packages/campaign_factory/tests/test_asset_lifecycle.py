from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import campaign_factory.app as app_module
import campaign_factory.core as core_module
import pytest
from campaign_asset_test_support import (
    add_audit_report,
    add_inventory_parent_fixture,
    add_story_quality_asset,
    add_surface_asset_fixture,
    add_variant_fixture,
    table_count,
    write_rgb_png,
    write_surface_image,
)
from campaign_factory.adapters import contentforge as contentforge_adapter
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.creative_modes import (
    creative_workflow_menu,
    creative_workflow_modes,
)
from campaign_test_support import add_rendered_asset, make_factory
from fastapi.testclient import TestClient


def _paged_posts_client(total_rows: int):
    class PagedPostsClient:
        def __init__(self):
            self.calls: list[dict] = []

        def select(self, table, params):
            assert table == "posts"
            self.calls.append(dict(params))
            offset = int(params.get("offset", "0"))
            limit = int(params["limit"])
            remaining = max(total_rows - offset, 0)
            count = min(limit, remaining)
            return [
                {"id": f"post_{offset + index}", "metadata": {}}
                for index in range(count)
            ]

    return PagedPostsClient()


def test_rendered_asset_content_hash_is_scoped_to_campaign(tmp_path: Path):
    cf = make_factory(tmp_path)
    now = "2026-05-24T00:00:00+00:00"
    for campaign_id, slug, source_id, asset_id in [
        ("camp_a", "campaign-a", "src_a", "asset_a"),
        ("camp_b", "campaign-b", "src_b", "asset_b"),
    ]:
        cf.conn.execute(
            """
            INSERT INTO campaigns (id, slug, name, platform, root_path, created_at, updated_at)
            VALUES (?, ?, ?, 'instagram', ?, ?, ?)
            """,
            (campaign_id, slug, slug, str(tmp_path / slug), now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO models (id, slug, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            ("model_1", "model", "Model", now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path, filename, created_at, updated_at)
            VALUES (?, ?, 'model_1', ?, ?, ?, 'source.mp4', ?, ?)
            """,
            (
                source_id,
                campaign_id,
                f"source-{campaign_id}",
                str(tmp_path / "source.mp4"),
                str(tmp_path / "source.mp4"),
                now,
                now,
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, created_at, updated_at)
            VALUES (?, ?, ?, 'same-render-hash', ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                campaign_id,
                source_id,
                str(tmp_path / f"{slug}.mp4"),
                str(tmp_path / f"{slug}.mp4"),
                f"{slug}.mp4",
                now,
                now,
            ),
        )
    rows = cf.conn.execute(
        "SELECT id FROM rendered_assets WHERE content_hash = 'same-render-hash' ORDER BY id"
    ).fetchall()
    assert [row["id"] for row in rows] == ["asset_a", "asset_b"]


def test_import_folder_dedupes_by_hash_and_ignores_unsupported(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"same")
    (folder / "b.mov").write_bytes(b"same")
    (folder / "ignore.txt").write_text("no")
    cf = make_factory(tmp_path)
    try:
        result = cf.domains.asset_import.import_folder(
            folder,
            campaign_slug="May Launch",
            model_slug="Model A",
            account_handles=["ig_a"],
        )
        assert len(result["imported"]) == 1
        assert len(result["duplicates"]) == 1
        assert len(result["ignored"]) == 1
        stored = Path(result["imported"][0]["stored_path"])
        assert stored.exists()
        assert "00_sources" in str(stored)
    finally:
        cf.close()


def test_import_folder_rejects_unknown_storage_mode_before_mutation(tmp_path: Path):
    folder = tmp_path / "external_library"
    folder.mkdir()
    (folder / "stacey.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="storage_mode must be copy or reference"):
            cf.domains.asset_import.import_folder(
                folder,
                campaign_slug="stacey_library",
                model_slug="stacey",
                storage_mode="symlink",
            )
        assert cf.conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 0
        assert cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0] == 0
    finally:
        cf.close()


def test_import_folder_allows_same_source_in_different_campaigns(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"same")
    cf = make_factory(tmp_path)
    try:
        first = cf.domains.asset_import.import_folder(
            folder, campaign_slug="first", model_slug="model"
        )
        second = cf.domains.asset_import.import_folder(
            folder, campaign_slug="second", model_slug="model"
        )

        assert len(first["imported"]) == 1
        assert len(second["imported"]) == 1
        assert (
            first["imported"][0]["content_hash"]
            == second["imported"][0]["content_hash"]
        )
        assert (
            first["imported"][0]["campaign_id"] != second["imported"][0]["campaign_id"]
        )
    finally:
        cf.close()


def test_import_folder_accepts_images_as_slideshow_sources(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"image")
    cf = make_factory(tmp_path)
    try:
        result = cf.domains.asset_import.import_folder(
            folder, campaign_slug="May Slides", model_slug="Model A"
        )

        assert len(result["imported"]) == 1
        assert result["imported"][0]["media_type"] == "image"
        assert (
            cf.domains.asset_import.assets_for_campaign(result["campaign"]["id"])[0][
                "media_type"
            ]
            == "image"
        )
    finally:
        cf.close()


def test_prepare_reel_writes_video_and_caption_sidecar(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        result = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may",
            hooks=["hook one"],
            recipes=["v01_original"],
            caption_color="auto",
        )
        job = result["prepared"][0]
        video = (
            cf.settings.reel_factory_root
            / "00_source_videos"
            / f"{job['reel_clip_stem']}.mp4"
        )
        sidecar = (
            cf.settings.reel_factory_root
            / "01_captions"
            / f"{job['reel_clip_stem']}.json"
        )
        assert video.exists()
        assert sidecar.exists()
        data = json.loads(sidecar.read_text())
        assert data["hooks"] == ["hook one"]
        assert data["recipes"] == ["v01_original"]
    finally:
        cf.close()


def test_prepare_reel_rotates_hook_order_across_sources(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    (folder / "b.mp4").write_bytes(b"video b")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        result = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may",
            hooks=["hook one", "hook two", "hook three"],
            recipes=["v01_original", "v05_hflip"],
            caption_color="auto",
        )
        stems = [job["reel_clip_stem"] for job in result["prepared"]]
        first = json.loads(
            (
                cf.settings.reel_factory_root / "01_captions" / f"{stems[0]}.json"
            ).read_text()
        )
        second = json.loads(
            (
                cf.settings.reel_factory_root / "01_captions" / f"{stems[1]}.json"
            ).read_text()
        )
        assert first["hooks"] == ["hook one", "hook two", "hook three"]
        assert second["hooks"] == ["hook two", "hook three", "hook one"]
    finally:
        cf.close()


def test_prepare_reel_can_target_explicit_source_assets(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    (folder / "b.mp4").write_bytes(b"video b")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        sources = cf.domains.asset_import.assets_for_campaign(
            cf.domains.campaign_by_slug("may")["id"]
        )
        selected = sources[1]
        result = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may",
            hooks=["hook"],
            source_asset_ids=[selected["id"]],
        )
        assert [job["source_asset_id"] for job in result["prepared"]] == [
            selected["id"]
        ]
        with pytest.raises(ValueError, match="video source assets not found"):
            cf.domains.reel_execution.prepare_reel_inputs(
                campaign_slug="may",
                hooks=["hook"],
                source_asset_ids=["missing_source"],
            )
    finally:
        cf.close()


def test_verify_audio_for_post_creates_verified_selection_and_rollup(tmp_path: Path):
    catalog_path = tmp_path / "audio_memory.json"
    catalog_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "aud_mem",
                        "title": "Mirror Trend",
                        "artistName": "DJ M",
                        "platform": "instagram",
                        "nativeAudioId": "ig_mem",
                        "moodTags": ["mirror"],
                        "bestContentTypes": ["v01_original"],
                        "resolved": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        cf.domains.audio_recommendations.import_audio_memory(catalog_path)
        add_rendered_asset(cf, tmp_path)
        campaign = cf.domains.campaign_by_slug("may")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots (
              id, campaign_id, rendered_asset_id, post_id, platform, status,
              account_id, instagram_account_id, snapshot_at, views, likes,
              comments, shares, saves, raw_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap_audio_verify",
                campaign["id"],
                "asset_1",
                "post_audio_verify",
                "instagram",
                "published",
                "acct_1",
                "ig_1",
                "2026-06-06T10:00:00+00:00",
                500,
                20,
                2,
                1,
                4,
                json.dumps(
                    {
                        "metadata": {
                            "campaign_factory": {
                                "audio_intent": {
                                    "operator_selection": {
                                        "catalog_audio_id": "aud_mem",
                                        "platform_audio_id": "ig_mem",
                                        "audio_title": "Mirror Trend",
                                        "selected_at": "2026-06-06T09:00:00+00:00",
                                    }
                                }
                            }
                        }
                    }
                ),
                "2026-06-06T10:00:00+00:00",
            ),
        )
        cf.conn.commit()

        result = cf.domains.audio_operations.verify_audio_for_post(
            "post_audio_verify",
            proof_url="https://proof.example/audio",
            proof_note="operator confirmed native audio",
            operator="tester",
        )
        selection = result["selection"]
        rollup = cf.conn.execute(
            "SELECT * FROM audio_performance_rollups WHERE audio_catalog_id = 'aud_mem'"
        ).fetchone()
        edges = {
            row["relation_type"]
            for row in cf.conn.execute(
                "SELECT relation_type FROM content_graph_edges"
            ).fetchall()
        }

        assert selection["status"] == "verified"
        assert selection["proof_url"] == "https://proof.example/audio"
        assert selection["post_id"] == "post_audio_verify"
        assert selection["audio_catalog_id"] == "aud_mem"
        assert rollup["post_count"] == 1
        assert "audio_selection_to_threadsdash_post" in edges
        assert "audio_selection_to_performance_snapshot" in edges
    finally:
        cf.close()


def test_finished_video_intake_accepts_higgsfield_source_lineage(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "generated_finished.mp4"
    source.write_bytes(b"finished video")
    lineage_path = tmp_path / "lineage.json"
    lineage_path.write_text(
        json.dumps(
            {
                "schema": "reel_factory.generated_asset_lineage.v1",
                "source": {
                    "referenceId": "ref_001",
                    "patternCardId": "pattern_001",
                    "promptId": "prompt_001",
                    "formatType": "mirror_selfie",
                },
                "generation": {
                    "tool": "higgsfield_kling_cli",
                    "modelProfile": "Stacey",
                    "soulId": "5828d958-91dd-4d6d-8909-934503f47644",
                    "imageJobId": "img_job",
                    "videoJobId": "vid_job",
                    "imagePath": str(tmp_path / "image.png"),
                    "assetPath": str(source),
                    "status": "generated",
                },
                "review": {"humanReviewRequired": True, "status": "draft"},
                "quality": {"copyRisk": "medium"},
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            core_module,
            "probe_video_shape",
            lambda path: {"effectiveAspectRatio": 1080 / 1920},
        )

        def fake_make_batch(**kwargs):
            captured.update(kwargs)
            return {
                "schema": "campaign_factory.make_batch.v1",
                "campaign": kwargs["campaign_slug"],
            }

        monkeypatch.setattr(cf.domains.make_batch_repo, "make_batch", fake_make_batch)

        result = cf.domains.finished_video.intake_finished_video(
            input_path=source,
            model_slug="stacey",
            campaign_slug="generated_daily",
            source_lineage_path=lineage_path,
        )

        source_prompt = json.loads(str(captured["source_prompt"]))
        lineage = source_prompt["generatedAssetLineage"]
        assert result["finishedVideoIntake"]["sourceLineagePath"] == str(lineage_path)
        assert lineage["generation"]["tool"] == "higgsfield_kling_cli"
        assert lineage["generation"]["imageJobId"] == "img_job"
        assert lineage["generation"]["videoJobId"] == "vid_job"
        assert lineage["source"]["referenceId"] == "ref_001"
        assert source_prompt["generationTool"] == "higgsfield_kling_cli"
        assert source_prompt["promptId"] == "prompt_001"
    finally:
        cf.close()


def test_finished_video_preflight_flags_non_reels_canvas(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        warnings = cf.domains.finished_video.finished_video_preflight(
            {"effectiveAspectRatio": 828 / 1108}
        )
        assert warnings[0]["code"] == "finished_video_not_reels_canvas"

        clean = cf.domains.finished_video.finished_video_preflight(
            {"effectiveAspectRatio": 1080 / 1920}
        )
        assert clean == []
    finally:
        cf.close()


def test_archive_inventory_report_requires_enough_clean_stacey_candidates(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        for index in range(3):
            (archive / f"stacey_{index}.mp4").write_bytes(f"video-{index}".encode())

        monkeypatch.setattr(
            core_module,
            "probe_video_metadata",
            lambda path: {
                "ok": True,
                "width": 1080,
                "height": 1920,
                "effectiveAspectRatio": 1080 / 1920,
                "durationSeconds": 5.0,
                "videoCodec": "h264",
                "audioPresent": True,
                "audioCodec": "aac",
            },
        )

        result = cf.domains.archive_quality.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=2,
        )

        assert result["schema"] == "campaign_factory.archive_inventory_report.v1"
        assert result["archiveVideosFound"] == 3
        assert result["cleanStaceyCandidates"] == 3
        assert result["status"] == "ready_for_source_approval"
        assert result["creatorMatchRequired"] is True
        assert Path(result["reportPath"]).exists()
    finally:
        cf.close()


def test_archive_inventory_report_blocks_when_inventory_is_short(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "stacey_one.mp4").write_bytes(b"one")

        monkeypatch.setattr(
            core_module,
            "probe_video_metadata",
            lambda path: {
                "ok": True,
                "width": 1080,
                "height": 1920,
                "effectiveAspectRatio": 1080 / 1920,
                "durationSeconds": 5.0,
                "videoCodec": "h264",
                "audioPresent": True,
            },
        )

        result = cf.domains.archive_quality.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=2,
        )

        assert result["status"] == "blocked"
        assert result["blockingReason"] == "insufficient_clean_archive_inventory"
        assert result["wouldProceedToRendering"] is False
    finally:
        cf.close()


def test_archive_inventory_report_blocks_duplicates_and_corrupt_files(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        duplicate_a = archive / "stacey_dup_a.mp4"
        duplicate_b = archive / "stacey_dup_b.mp4"
        corrupt = archive / "stacey_corrupt.mp4"
        clean = archive / "stacey_clean.mp4"
        duplicate_a.write_bytes(b"same")
        duplicate_b.write_bytes(b"same")
        corrupt.write_bytes(b"bad")
        clean.write_bytes(b"clean")

        def fake_probe(path: Path) -> dict[str, object]:
            if path.name == "stacey_corrupt.mp4":
                return {"ok": False, "error": "probe_failed"}
            return {
                "ok": True,
                "width": 1080,
                "height": 1920,
                "effectiveAspectRatio": 1080 / 1920,
                "durationSeconds": 5.0,
                "videoCodec": "h264",
                "audioPresent": False,
            }

        monkeypatch.setattr(core_module, "probe_video_metadata", fake_probe)

        result = cf.domains.archive_quality.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=2,
        )

        assert result["archiveVideosFound"] == 4
        assert result["duplicateSourceFingerprint"] == 1
        assert result["corruptedOrInvalid"] == 1
        assert result["cleanStaceyCandidates"] == 2
        blocked = {
            item["filename"]: item
            for item in result["items"]
            if item["status"] == "blocked"
        }
        assert blocked["stacey_dup_b.mp4"]["blockingReasons"] == [
            "duplicate_source_fingerprint"
        ]
        assert "probe_failed" in blocked["stacey_corrupt.mp4"]["blockingReasons"]
        clean_items = [
            item
            for item in result["items"]
            if item["status"] == "clean_source_candidate"
        ]
        assert all(
            item["audioStatus"] == "missing_needs_campaign_audio"
            for item in clean_items
        )
    finally:
        cf.close()


def test_archive_inventory_report_blocks_existing_campaign_duplicates(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        existing = archive / "stacey_existing.mp4"
        existing.write_bytes(b"existing")
        digest = core_module.sha256_file(existing)
        model = cf.domains.models.upsert_model("stacey", "Stacey")
        campaign = cf.domains.models.upsert_campaign(
            "other_campaign", "stacey", platform="instagram"
        )
        cf.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path, filename,
             media_type, platform, source_prompt, notes, account_ids_json, status, created_at, updated_at)
            VALUES ('src_existing', ?, ?, ?, ?, ?, 'existing.mp4', 'video', 'instagram',
                    '{}', 'existing asset', '[]', 'imported', ?, ?)
            """,
            (
                campaign["id"],
                model["id"],
                digest,
                str(existing),
                str(existing),
                "2026-06-05T00:00:00+00:00",
                "2026-06-05T00:00:00+00:00",
            ),
        )
        cf.conn.commit()

        monkeypatch.setattr(
            core_module,
            "probe_video_metadata",
            lambda path: {
                "ok": True,
                "width": 1080,
                "height": 1920,
                "effectiveAspectRatio": 1080 / 1920,
                "durationSeconds": 5.0,
                "videoCodec": "h264",
                "audioPresent": True,
            },
        )

        result = cf.domains.archive_quality.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=1,
        )

        assert result["status"] == "blocked"
        assert result["duplicateContentHash"] == 1
        assert result["items"][0]["blockingReasons"] == [
            "duplicate_existing_campaign_asset"
        ]
    finally:
        cf.close()


def test_finished_video_hooks_are_format_native(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        pattern = {
            "clusterKey": "cluster",
            "label": "Pattern",
            "audioRecommendations": {"recommendations": []},
        }
        mirror = cf.domains.finished_video.finished_video_hooks(
            "mirror_selfie", pattern, count=3
        )
        pov = cf.domains.finished_video.finished_video_hooks("pov", pattern, count=2)

        assert mirror[0]["text"] == "he thinks this was for him"
        assert mirror[0]["candidateKind"] == "finished_video_caption"
        assert mirror[0]["captionArchetype"] == "mirror_selfie_native"
        assert pov[0]["text"].startswith("pov:")
        assert pov[0]["source"] == "campaign_factory_finished_video"
    finally:
        cf.close()


def test_finished_video_style_lane_can_override_format(tmp_path: Path, monkeypatch):
    source = tmp_path / "IMG_5556.mp4"
    source.write_bytes(b"finished video")
    cf = make_factory(tmp_path)
    try:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            core_module,
            "probe_video_shape",
            lambda path: {"effectiveAspectRatio": 1080 / 1920},
        )

        def fake_make_batch(**kwargs):
            captured.update(kwargs)
            return {
                "schema": "campaign_factory.make_batch.v1",
                "campaign": kwargs["campaign_slug"],
            }

        monkeypatch.setattr(cf.domains.make_batch_repo, "make_batch", fake_make_batch)
        result = cf.domains.finished_video.intake_finished_video(
            input_path=source,
            model_slug="model_a",
            campaign_slug="daily_video",
            style_lane="mirror_selfie",
            variant_count=1,
        )

        assert result["finishedVideoIntake"]["formatType"] == "mirror_selfie"
        source_prompt = json.loads(str(captured["source_prompt"]))
        assert source_prompt["formatType"] == "mirror_selfie"
        assert source_prompt["styleLane"] == "mirror_selfie"
    finally:
        cf.close()


def test_finished_video_caption_band_prefers_auto_for_people_formats(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        assert (
            cf.domains.finished_video.finished_video_caption_band("mirror_selfie")
            == "auto"
        )
        assert cf.domains.finished_video.finished_video_caption_band("pov") == "auto"
        assert (
            cf.domains.finished_video.finished_video_caption_band("slideshow")
            == "center"
        )
    finally:
        cf.close()


def test_finished_video_caption_font_prefers_instagram_condensed_for_reels(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        assert (
            cf.domains.finished_video.finished_video_caption_font("mirror_selfie")
            == "Instagram Sans Condensed"
        )
        assert (
            cf.domains.finished_video.finished_video_caption_font("pov")
            == "Instagram Sans Condensed"
        )
        assert (
            cf.domains.finished_video.finished_video_caption_font("slideshow")
            == "Instagram Sans Condensed"
        )
    finally:
        cf.close()


def test_creative_plan_create_status_and_finished_video_linkage(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "selfie_finished.mp4"
    source.write_bytes(b"finished video")
    cf = make_factory(tmp_path)
    try:
        plan = cf.domains.creative_planning.create_creative_plan(
            name="stacey_daily_001",
            target_account="staceybennetx",
            daily_base_video_target=10,
            style_lanes=["amateur_native", "polished_glam"],
            model_profile="stacey",
            source_accounts=["staceybennetx", "competitor_refs"],
            linked_campaign="daily_video",
        )
        assert plan["schema"] == "campaign_factory.creative_plan.v1"
        assert plan["status"] == "planned"
        assert plan["counts"]["generated_videos"] == 0
        assert "Analyze 10 more references" in plan["next_actions"]

        updated = cf.domains.creative_planning.update_creative_plan_status(
            name="stacey_daily_001", status="prompts_ready"
        )
        assert updated["status"] == "prompts_ready"

        captured: dict[str, object] = {}

        def fake_make_batch(**kwargs):
            captured.update(kwargs)
            return {
                "schema": "campaign_factory.make_batch.v1",
                "campaign": kwargs["campaign_slug"],
            }

        monkeypatch.setattr(cf.domains.make_batch_repo, "make_batch", fake_make_batch)
        result = cf.domains.finished_video.intake_finished_video(
            input_path=source,
            model_slug="model_a",
            campaign_slug="daily_video",
            creative_plan="stacey_daily_001",
            style_lane="amateur_native",
        )

        source_prompt = json.loads(str(captured["source_prompt"]))
        assert source_prompt["creativePlanId"] == plan["id"]
        assert source_prompt["creativePlanName"] == "stacey_daily_001"
        assert source_prompt["styleLane"] == "amateur_native"
        assert result["finishedVideoIntake"]["creativePlan"]["id"] == plan["id"]
        assert (
            cf.domains.creative_planning.creative_plan_for_campaign("daily_video")["id"]
            == plan["id"]
        )
    finally:
        cf.close()


def test_batch_summary_includes_daily_finished_video_counters(tmp_path: Path):
    folder = tmp_path / "finished"
    folder.mkdir()
    (folder / "selfie.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            folder,
            campaign_slug="daily",
            model_slug="model_a",
            source_prompt=json.dumps(
                {
                    "schema": "campaign_factory.finished_video_intake.v1",
                    "strategy": {"primaryMetric": "views_reach"},
                }
            ),
        )
        summary = cf.domains.export_summary.batch_summary("daily")

        assert summary["dailyProduction"]["targetBaseVideos"] == 10
        assert summary["dailyProduction"]["promptReady"] == 1
        assert summary["dailyProduction"]["generated"] == 1
        assert summary["dailyProduction"]["remainingBaseVideos"] == 9
        assert summary["dailyProduction"]["primaryMetric"] == "views_reach"
    finally:
        cf.close()


def test_batch_summary_includes_linked_creative_plan(tmp_path: Path):
    folder = tmp_path / "finished"
    folder.mkdir()
    (folder / "selfie.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        plan = cf.domains.creative_planning.create_creative_plan(
            name="daily_plan", target_account="staceybennetx", linked_campaign="daily"
        )
        cf.domains.asset_import.import_folder(
            folder,
            campaign_slug="daily",
            model_slug="model_a",
            source_prompt=json.dumps(
                {
                    "schema": "campaign_factory.finished_video_intake.v1",
                    "creativePlanId": plan["id"],
                    "creativePlanName": plan["name"],
                    "generatedAssetLineage": {
                        "schema": "reel_factory.generated_asset_lineage.v1",
                        "source": {
                            "referenceId": "ref_1",
                            "patternCardId": "pattern_1",
                            "promptId": "prompt_1",
                        },
                        "generation": {
                            "tool": "manual_finished_video",
                            "modelProfile": "model_a",
                        },
                        "review": {"humanReviewRequired": True, "status": "draft"},
                    },
                }
            ),
        )
        summary = cf.domains.export_summary.batch_summary("daily")

        assert summary["creativePlan"]["id"] == plan["id"]
        assert summary["creativePlan"]["counts"]["generated_videos"] == 1
        assert summary["creativePlan"]["counts"]["references"] == 1
    finally:
        cf.close()


def test_make_batch_slideshow_format_registers_slideshow_asset(
    tmp_path: Path, monkeypatch
):
    bank_path = tmp_path / "campaign_reference_bank.json"
    bank_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.campaign_reference_bank.v1",
                "clusters": [
                    {
                        "clusterRank": 1,
                        "clusterKey": "caption_led_visual::direct_response::question_hook",
                        "label": "caption led visual / direct response / question hook",
                        "visualFormat": "caption_led_visual",
                        "hookType": "direct_response",
                        "captionArchetype": "question_hook",
                        "captionFormulas": [
                            {
                                "formula": "{direct question}?",
                                "exampleCaptions": ["red or pink ?"],
                            }
                        ],
                        "suggestedVariantRecipes": ["v01_original", "v05_hflip"],
                        "suggestedFormats": ["reel", "slideshow"],
                    }
                ],
            }
        )
    )
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.domains.reference.import_reference_bank(bank_path)

        def fake_run(cmd, cwd=None, text=None, capture_output=None, check=None):
            assert "--reference-pattern-id" in cmd
            assert cmd[cmd.index("--reference-pattern-id") + 1].startswith("refpat_")
            assert "--generation-id" in cmd
            assert cmd[cmd.index("--generation-id") + 1].startswith("slidegen_")
            out_dir = Path(cmd[cmd.index("--out-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            reel = out_dir / "slideshow_reel.mp4"
            reel.write_bytes(b"fake slideshow reel")
            (out_dir / "slideshow_manifest.json").write_text(
                json.dumps(
                    {
                        "schema": "reel_factory.slideshow.v1",
                        "reel_path": str(reel),
                        "items": [{"source_hash": "src", "hook": "red or pink ?"}],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
        monkeypatch.setattr(
            contentforge_adapter,
            "audit_campaign",
            lambda *args, **kwargs: {"reports": []},
        )

        result = cf.domains.make_batch_repo.make_batch(
            folder=folder,
            campaign_slug="slides",
            model_slug="model",
            output_format="slideshow",
            variant_count=3,
            user_id=None,
        )

        rendered = cf.domains.campaign_overview.dashboard("slides")["rendered"]
        assert result["format"] == "slideshow"
        assert result["prepare"]["preparedCount"] == 1
        assert result["sync"]["syncedCount"] == 1
        assert rendered[0]["recipe"] == "slideshow_pack"
        assert rendered[0]["captionGeneration"]["format"] == "slideshow_pack"
        assert rendered[0]["captionGeneration"]["generationId"].startswith("slidegen_")
        assert rendered[0]["captionGeneration"]["referencePattern"]["id"].startswith(
            "refpat_"
        )
    finally:
        cf.close()


def test_make_batch_auto_mixed_folder_runs_reel_and_slideshow_groups(
    tmp_path: Path, monkeypatch
):
    bank_path = tmp_path / "campaign_reference_bank.json"
    bank_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.campaign_reference_bank.v1",
                "clusters": [
                    {
                        "clusterRank": 1,
                        "clusterKey": "mixed_pattern",
                        "label": "mixed pattern",
                        "visualFormat": "mirror_grid",
                        "hookType": "question",
                        "captionArchetype": "question_hook",
                        "captionFormulas": [
                            {
                                "formula": "{question}?",
                                "exampleCaptions": ["which one wins ?"],
                            }
                        ],
                        "suggestedVariantRecipes": ["v01_original"],
                        "suggestedFormats": ["reel", "slideshow"],
                    }
                ],
            }
        )
    )
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    (folder / "b.jpg").write_bytes(b"image")
    cf = make_factory(tmp_path)
    try:
        cf.domains.reference.import_reference_bank(bank_path)

        monkeypatch.setattr(
            cf.domains.reel_execution,
            "run_reel_factory",
            lambda **kwargs: {
                "returncode": 0,
                "runs": [{"renderJobId": "job_1"}],
                "elapsed_seconds": 1.23,
            },
        )
        monkeypatch.setattr(
            cf.domains.reel_execution,
            "sync_reel_outputs",
            lambda **kwargs: {
                "synced": [{"id": "asset_1"}],
            },
        )

        def fake_run(cmd, cwd=None, text=None, capture_output=None, check=None):
            assert "--reference-pattern-id" in cmd
            assert "--generation-id" in cmd
            media_dir = Path(cmd[cmd.index("--media-dir") + 1])
            assert all(
                path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic"}
                for path in media_dir.iterdir()
            )
            out_dir = Path(cmd[cmd.index("--out-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            reel = out_dir / "slideshow_reel.mp4"
            reel.write_bytes(b"fake slideshow reel")
            (out_dir / "slideshow_manifest.json").write_text(
                json.dumps(
                    {
                        "schema": "reel_factory.slideshow.v1",
                        "reel_path": str(reel),
                        "items": [{"source_hash": "src", "hook": "which one wins ?"}],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
        monkeypatch.setattr(
            contentforge_adapter,
            "audit_campaign",
            lambda *args, **kwargs: {"reports": []},
        )

        result = cf.domains.make_batch_repo.make_batch(
            folder=folder,
            campaign_slug="mixed",
            model_slug="model",
            output_format="auto",
            variant_count=2,
            user_id=None,
        )

        assert result["sourceMix"] == {"video": 1, "image": 1}
        assert result["formatsRun"] == ["reel", "slideshow"]
        assert result["prepare"]["byFormat"]["reel"]["preparedCount"] == 1
        assert result["prepare"]["byFormat"]["slideshow"]["preparedCount"] == 1
        assert result["run"]["byFormat"]["slideshow"]["returncode"] == 0
    finally:
        cf.close()


def test_sync_reel_outputs_reads_manifest_and_copies_rendered_asset(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        job = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may", hooks=["caption"], recipes=["v01_original"]
        )["prepared"][0]
        sidecar = (
            cf.settings.reel_factory_root
            / "01_captions"
            / f"{job['reel_clip_stem']}.json"
        )
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        data["generation"] = {
            "generation_id": "capgen_test",
            "model": "fake",
            "backend": "ollama",
            "prompt_hash": "prompt_hash",
            "caption_hashes": ["caption_hash_1"],
            "quality": [
                {"captionHash": "caption_hash_1", "qualityScore": 95, "warnings": []}
            ],
        }
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        out_dir = cf.settings.reel_factory_root / "02_processed" / job["reel_clip_stem"]
        out_dir.mkdir(parents=True)
        out = (
            out_dir
            / f"{job['reel_clip_stem']}_h00_v01_original_9x16_light_deadbeef.mp4"
        )
        out.write_bytes(b"rendered")
        conn = sqlite3.connect(cf.settings.reel_factory_root / "manifest.sqlite")
        conn.execute("""
            CREATE TABLE variations (
              job_key TEXT, clip TEXT, recipe TEXT, recipe_params_json TEXT, caption_text TEXT,
              output_path TEXT, review_state TEXT, status TEXT, encoded_at INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO variations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "job",
                job["reel_clip_stem"],
                "v01_original",
                json.dumps({"_target_ratio": "9:16"}),
                "caption",
                str(out),
                "draft",
                "ok",
                1,
            ),
        )
        conn.commit()
        conn.close()
        result = cf.domains.reel_execution.sync_reel_outputs(campaign_slug="may")
        assert len(result["synced"]) == 1
        copied = Path(result["synced"][0]["campaign_path"])
        assert copied.exists()
        assert "02_rendered" in str(copied)
        assert result["synced"][0]["caption_generation_json"]
        dashboard_asset = cf.domains.campaign_overview.dashboard("may")["rendered"][0]
        assert dashboard_asset["captionGeneration"]["generationId"] == "capgen_test"
        assert dashboard_asset["captionHash"]
        assert (
            dashboard_asset["captionOutcomeContext"]["caption_hash"]
            == dashboard_asset["captionHash"]
        )
        assert (
            dashboard_asset["captionOutcomeContext"]["captionPlacementPolicy"]
            == "focal_safe_v1"
        )
        assert (
            dashboard_asset["captionOutcomeContext"]["captionPlacementDecision"][
                "status"
            ]
            == "pending"
        )
        assert dashboard_asset["captionGeneration"]["instagramPostCaption"][
            "instagram_post_caption"
        ]
        assert dashboard_asset["captionGeneration"]["audioIntent"]["status"] in {
            "attached",
            "missing",
        }
    finally:
        cf.close()


def test_creative_workflow_mode_catalog_is_additive_and_fail_closed():
    catalog = creative_workflow_modes()

    assert catalog["schema"] == "campaign_factory.creative_workflow_modes.v1"
    assert "defaultMode" not in catalog
    assert catalog["selectionRequired"] is True
    assert catalog["modePrompt"] == "Which Creator OS mode do you want for this run?"
    modes = {mode["id"]: mode for mode in catalog["modes"]}
    assert set(modes) == {
        "library_reuse",
        "soul_static",
        "motion_edit",
        "best_only_kling",
        "reference_video_remix",
    }
    assert modes["soul_static"]["paidVideoGeneration"] is False
    assert modes["best_only_kling"]["staticFallbackRequired"] is True
    assert modes["reference_video_remix"]["entrypoint"] == (
        "generation run --mode reference_video_remix"
    )
    assert all(mode["costLabel"] for mode in modes.values())
    assert all(mode["requiredApprovals"] for mode in modes.values())
    assert all(mode["humanReviewRequired"] is True for mode in modes.values())
    assert all(mode["schedulingAllowed"] is False for mode in modes.values())
    assert all(mode["publishingAllowed"] is False for mode in modes.values())
    assert creative_workflow_menu().splitlines() == [
        "Which Creator OS mode do you want for this run?",
        "1. Library reuse — free",
        "2. Soul still + static MP4 — paid still generation, free MP4",
        "3. Local motion edit — free",
        "4. Best-only Kling — paid video",
        "5. Reference-video remix — paid endpoint stills and paid Seedance/Kling video",
    ]


def test_graph_id_for_and_ensure_graph_edge_direct(tmp_path: Path):
    # Direct coverage for the graph_id_for/ensure_graph_edge facade methods,
    # previously exercised only by the deleted test_core_characterization.py
    # golden-master snapshots (F7). Other content-graph tests here assert the
    # graph via table SQL and graph_id fields but never call these two methods
    # directly.
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("Model A", name="Model A", notes="first")
        campaign = cf.domains.models.upsert_campaign(
            "Launch Campaign", model["slug"], platform="threads"
        )
        account = cf.domains.models.upsert_account(
            "@creator_a", platform="instagram", external_id="ig_1", model_id=model["id"]
        )

        campaign_graph = cf.domains.graph.graph_id_for(
            "campaigns",
            campaign["id"],
            entity_type="campaign",
            payload={"slug": campaign["slug"]},
        )
        account_graph = cf.domains.graph.graph_id_for(
            "accounts",
            account["id"],
            entity_type="account",
            payload={"handle": account["handle"]},
        )
        assert campaign_graph and campaign_graph.startswith("cg_")
        assert account_graph and account_graph.startswith("cg_")

        edge_id = cf.domains.graph.ensure_graph_edge(
            campaign_graph,
            account_graph,
            "assigned_account",
            evidence={"source": "test"},
            commit=True,
        )
        assert edge_id
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM content_graph_edges "
                "WHERE relation_type = 'assigned_account'"
            ).fetchone()[0]
            == 1
        )
    finally:
        cf.close()


def test_dashboard_audio_workflow_summary_counts_audio_tasks(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        rendered = [
            cf.domains.account_planning.dashboard_rendered_asset(asset)
            for asset in cf.domains.rendered_for_campaign(
                cf.domains.campaign_by_slug("may")["id"]
            )
        ]
        summary = cf.domains.audio_operations.audio_workflow_summary(rendered)

        assert summary["taskCounts"]["not_required"] == 1
        assert summary["taskCounts"]["completed"] == 0

        rendered[0]["captionGeneration"] = {
            "audio_intent": {
                "schema": "pipeline.audio_intent.v1",
                "required": True,
                "status": "verified",
                "operator_selection": {
                    "platform_audio_id": "ig_audio_1",
                    "selected_at": "2026-05-22T12:00:00.000Z",
                    "verified_at": "2026-05-22T12:05:00.000Z",
                },
            },
        }
        summary = cf.domains.audio_operations.audio_workflow_summary(rendered)

        assert summary["taskCounts"]["completed"] == 1
        assert summary["counts"]["ready"] == 1
    finally:
        cf.close()


def test_dashboard_audio_workflow_summary_counts_and_top_audio(tmp_path: Path):
    cf = make_factory(tmp_path)
    rendered = [
        {
            "id": "asset_recommended",
            "captionGeneration": {},
            "referencePattern": {},
            "audioRecommendations": {
                "recommendations": [
                    {
                        "audioTitle": "Runway Pop",
                        "artistName": "DJ A",
                        "audioId": "ig_1",
                        "freshness": "rising",
                        "confidence": 0.91,
                    }
                ],
            },
        },
        {
            "id": "asset_selected",
            "captionGeneration": {
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "required": True,
                    "status": "selected",
                    "recommendations": [
                        {
                            "audioTitle": "Runway Pop",
                            "artistName": "DJ A",
                            "audioId": "ig_1",
                        }
                    ],
                }
            },
            "referencePattern": {},
            "audioRecommendations": {"recommendations": []},
        },
        {
            "id": "asset_blocked",
            "captionGeneration": {
                "audioIntent": {"required": True, "status": "blocked"}
            },
            "referencePattern": {},
            "audioRecommendations": {},
        },
        {
            "id": "asset_ready",
            "captionGeneration": {
                "audioIntent": {"required": True, "status": "attached"}
            },
            "referencePattern": {},
            "audioRecommendations": {},
        },
    ]
    try:
        summary = cf.domains.audio_operations.audio_workflow_summary(rendered)

        assert summary["counts"] == {
            "needs_audio": 1,
            "selected_not_attached": 1,
            "blocked": 1,
            "ready": 1,
        }
        assert summary["topRecommendedAudio"][0]["audio_title"] == "Runway Pop"
        assert summary["topRecommendedAudio"][0]["count"] == 2
    finally:
        cf.close()


def test_fresh_reel_production_capacity_plan_exposes_conservative_scenario(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        report = cf.domains.fresh_reel_production.fresh_reel_production_capacity_plan(
            creator="Stacey",
            target_schedule_safe_inventory=270,
            current_inventory=11,
        )

        assert report["schema"] == "creator_os.fresh_reel_production_capacity_plan.v1"
        assert report["freshScheduleSafeAssetsNeeded"] == 259
        assert report["estimatedDaysToBuffer"] == 3
        assert report["dailyScheduleSafeTarget"] == 90
        assert report["conservativeScenario"]["conservativeYieldPct"] == 50.0
        assert report["conservativeScenario"]["variantsNeededConservative"] == 518
        assert report["conservativeScenario"]["parentsNeededConservative"] == 35
        assert report["conservativeScenario"]["estimatedDaysConservative"] == 4
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_register_finished_video_preserves_caption_placement_qc(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        video = tmp_path / "finished_captioned.mp4"
        video.write_bytes(b"fake mp4 bytes")
        decision = {
            "status": "passed",
            "selectedLane": "bottom",
            "reason": "bottom selected; top overlaps face",
        }

        result = cf.domains.finished_video.register_finished_video(
            input_path=video,
            campaign_slug="stacey_archive_marketing_20260606",
            model_slug="stacey",
            caption="caption text",
            caption_hash="caption_hash_1",
            caption_bank="stacey_bank",
            creator_mix="Stacey",
            creator_model="Stacey",
            track_id="audio_1",
            track_name="Audio One",
            audio_source="local_review_preview",
            selected_reason="operator selected",
            operator="codex",
            approval_reason="test approval",
            review_batch="render_trials_v6_focal_safe_placement",
            caption_placement_policy="focal_safe_v1",
            caption_placement_decision=decision,
        )

        explanation = result["publishability"]
        assert explanation["publishableCandidate"] is True
        assert explanation["checks"]["caption_placement_qc_passed"] is True
        assert explanation["captionPlacementPolicy"] == "focal_safe_v1"
        assert explanation["captionPlacementDecision"] == decision
    finally:
        cf.close()


def test_register_finished_video_can_keep_post_caption_separate_from_burned_caption(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        video = tmp_path / "finished_captioned.mp4"
        video.write_bytes(b"fake mp4 bytes")

        result = cf.domains.finished_video.register_finished_video(
            input_path=video,
            campaign_slug="stacey_archive_marketing_20260606",
            model_slug="stacey",
            caption="Save this so you don't forget it",
            instagram_post_caption="mirror check",
            caption_hash="caption_hash_1",
            caption_bank="stacey_bank",
            creator_mix="Stacey",
            creator_model="Stacey",
            track_id="audio_1",
            track_name="Audio One",
            audio_source="local_review_preview",
            selected_reason="operator selected",
            operator="codex",
            approval_reason="test approval",
            review_batch="render_trials_v6_focal_safe_placement",
            caption_placement_policy="focal_safe_v1",
            caption_placement_decision={"status": "passed"},
        )

        explanation = result["publishability"]
        assert explanation["publishableCandidate"] is True
        assert explanation["burned_caption_text"] == "Save this so you don't forget it"
        assert explanation["instagram_post_caption"] == "mirror check"
        assert explanation["instagramPostCaptionQuality"]["passed"] is True
    finally:
        cf.close()


def test_register_finished_video_blocks_unsafe_caption_before_registration(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        video = tmp_path / "finished_unsafe_caption.mp4"
        video.write_bytes(b"fake mp4 bytes")
        before_rendered = cf.conn.execute(
            "SELECT COUNT(*) AS c FROM rendered_assets"
        ).fetchone()["c"]
        before_sources = cf.conn.execute(
            "SELECT COUNT(*) AS c FROM source_assets"
        ).fetchone()["c"]
        before_jobs = cf.conn.execute(
            "SELECT COUNT(*) AS c FROM render_jobs"
        ).fetchone()["c"]

        result = cf.domains.finished_video.register_finished_video(
            input_path=video,
            campaign_slug="stacey_archive_marketing_20260606",
            model_slug="stacey",
            caption="DM me",
            caption_hash="caption_hash_dm",
            caption_bank="stacey_bank",
            creator_mix="Stacey",
            creator_model="Stacey",
            track_id="audio_1",
            track_name="Audio One",
            audio_source="local_review_preview",
            selected_reason="operator selected",
            operator="codex",
            approval_reason="test approval",
            review_batch="render_trials_v6_focal_safe_placement",
            caption_placement_policy="focal_safe_v1",
            caption_placement_decision={"status": "passed"},
        )

        assert result["canProceed"] is False
        assert result["blockedAt"] == "discoverability_pre_render_gate"
        assert result["renderedAssetId"] == ""
        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"]
            == before_rendered
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM source_assets").fetchone()["c"]
            == before_sources
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"]
            == before_jobs
        )
        rows = [
            dict(row)
            for row in cf.conn.execute(
                "SELECT * FROM asset_rejection_evidence WHERE failed_stage = ?",
                ("discoverability_pre_render_gate",),
            ).fetchall()
        ]
        assert rows
        assert {row["failure_category"] for row in rows} == {"dm_language"}
        assert "caption_text" in {row["source_field"] for row in rows}
        assert all(row["matched_text"].lower() == "dm" for row in rows)
        assert result["rejectionEvidenceCapture"]["capturedCount"] == len(rows)
    finally:
        cf.close()


def test_prepare_reel_inputs_blocks_unsafe_hooks_before_render_jobs(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        (source_dir / "clip.mp4").write_bytes(b"fake mp4 bytes")
        cf.domains.asset_import.import_folder(
            source_dir,
            campaign_slug="stacey_archive_marketing_20260606",
            model_slug="stacey",
            platform="instagram",
        )
        before_jobs = cf.conn.execute(
            "SELECT COUNT(*) AS c FROM render_jobs"
        ).fetchone()["c"]

        result = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="stacey_archive_marketing_20260606",
            hooks=["DM me for more"],
            force_new=True,
        )

        assert result["canProceed"] is False
        assert result["blockedAt"] == "discoverability_generation_gate"
        assert result["prepared"] == []
        assert result["rejectionEvidenceCapture"]["capturedCount"] >= 1
        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"]
            == before_jobs
        )
        evidence = [
            dict(row)
            for row in cf.conn.execute(
                "SELECT * FROM asset_rejection_evidence WHERE failed_stage = ?",
                ("discoverability_generation_gate",),
            ).fetchall()
        ]
        assert evidence
        assert {row["failure_category"] for row in evidence} == {"dm_language"}
        assert "hook" in {row["source_field"] for row in evidence}
    finally:
        cf.close()


def test_register_parent_reel_creates_concept_registry_row(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()

        parent = cf.domains.variant_lineage.register_parent_reel(
            "asset_1", operator="tester"
        )

        assert parent["schema"] == "campaign_factory.parent_reel.v1"
        assert parent["parentReelId"].startswith("parent_")
        assert parent["conceptId"].startswith("concept_")
        assert parent["parentAssetId"] == "asset_1"
        row = cf.conn.execute(
            "SELECT * FROM concepts WHERE id = ?", (parent["conceptId"],)
        ).fetchone()
        assert row["parent_asset_id"] == "asset_1"
        assert (
            row["content_fingerprint"]
            == cf.domains.rendered_asset("asset_1")["content_hash"]
        )
    finally:
        cf.close()


def test_register_parent_reel_captures_rejection_evidence_before_blocking(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET review_state = 'approved',
                caption = ?,
                caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                "link in bio",
                json.dumps(
                    {
                        "caption_text": "link in bio",
                        "burned_caption_text": "link in bio",
                        "instagram_post_caption": "link in bio",
                        "caption_hash": "caption_hash_1",
                        "captionPlacementDecision": {"status": "passed"},
                    }
                ),
            ),
        )
        cf.conn.commit()

        with pytest.raises(ValueError, match="publishable_candidate"):
            cf.domains.variant_lineage.register_parent_reel(
                "asset_1", operator="tester"
            )

        rows = [
            dict(row)
            for row in cf.conn.execute(
                "SELECT * FROM asset_rejection_evidence WHERE rendered_asset_id = ?",
                ("asset_1",),
            ).fetchall()
        ]
        assert rows
        assert {row["failed_stage"] for row in rows} == {"discoverability_safety_pass"}
        assert "bio_reference" in {row["failure_category"] for row in rows}
        assert "burned_caption_text" in {row["source_field"] for row in rows}
        assert all(row["repairable"] == 1 for row in rows)
    finally:
        cf.close()


def test_variant_plan_is_read_only_and_creates_stable_family_id(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        cf.domains.variant_lineage.register_parent_reel("asset_1", operator="tester")

        result = cf.domains.variant_lineage.variant_plan(
            parent_asset_id="asset_1", count=3, contentforge_preset="caption_safe"
        )

        assert result["schema"] == "campaign_factory.variant_plan.v1"
        assert result["parentAssetId"] == "asset_1"
        assert result["requestedVariants"] == 3
        assert result["canGenerate"] is True
        assert result["wouldWrite"] is False
        assert result["variantFamilyId"].startswith("vfam_")
        assert [item["variantIndex"] for item in result["plannedOperations"]] == [
            1,
            2,
            3,
        ]
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0] == 0
        )
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_variant_plan_accepts_caption_safe_v2(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        cf.domains.variant_lineage.register_parent_reel("asset_1", operator="tester")

        result = cf.domains.variant_lineage.variant_plan(
            parent_asset_id="asset_1", count=12, contentforge_preset="caption_safe_v2"
        )

        assert result["contentforgePreset"] == "caption_safe_v2"
        assert result["canGenerate"] is True
        assert result["plannedOperations"][0]["operationSet"] == "caption_safe_v2"
    finally:
        cf.close()


def test_caption_version_lineage_is_preserved_into_variant_plan(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")
        created = cf.domains.caption_family.caption_family_create(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=1,
            style="ig_short",
            dry_run=False,
        )
        caption_version_id = created["plannedVersions"][0]["captionVersionId"]

        plan = cf.domains.variant_lineage.variant_plan(
            parent_asset_id="asset_caption_parent",
            caption_version_id=caption_version_id,
            count=3,
            contentforge_preset="caption_safe_v2",
        )

        assert plan["captionFamilyId"] == created["captionFamilyId"]
        assert plan["captionVersionId"] == caption_version_id
        assert plan["variantFamilyId"].startswith("vfam_")
        assert all(
            {
                "captionFamilyId": created["captionFamilyId"],
                "captionVersionId": caption_version_id,
            }.items()
            <= item["operations"][1].items()
            for item in plan["plannedOperations"]
        )
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_content_surface_normalization_keeps_feed_and_story_distinct():
    assert core_module.normalize_content_surface("regular_reel") == "reel"
    assert core_module.normalize_content_surface("feed-single") == "feed_single"
    assert core_module.normalize_content_surface("feed_carousel") == "feed_carousel"
    assert core_module.normalize_content_surface("story") == "story"
    assert core_module.normalize_content_surface("story_cta") == "story_cta"
    assert core_module.normalize_content_surface("image") == "feed_single"


def test_story_intent_report_classifies_story_assets(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_snap")
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET story_intent = 'snapchat_promo',
                story_goal = 'traffic',
                story_style = 'casual_selfie',
                snapchat_display_name = 'Stacey',
                snapchat_username = 'staceyxx',
                snapchat_cta_text = 'add me'
            WHERE id = 'asset_story_snap'
            """
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.domains.story_management.story_intent_report(creator="Stacey")

        assert cf.conn.total_changes == before
        assert report["storyAssetsAnalyzed"] == 1
        assert report["intentCounts"] == {"snapchat_promo": 1}
        assert report["goalCounts"] == {"traffic": 1}
        assert report["styleCounts"] == {"casual_selfie": 1}
        assert report["snapchatPromoStories"] == 1
        assert report["snapchatPromo"][0]["snapchatUsername"] == "staceyxx"
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_story_mix_and_calendar_plans_are_balanced_and_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        mix = cf.domains.story_management.story_mix_plan(creator="Stacey")
        calendar = cf.domains.story_management.story_calendar_plan(creator="Stacey")

        assert cf.conn.total_changes == before
        assert mix["storyMix"] == {
            "casual_selfie": 30,
            "reel_teaser": 25,
            "snapchat_promo": 25,
            "lifestyle": 10,
            "engagement": 10,
        }
        assert mix["storyMix"]["snapchat_promo"] < 50
        assert calendar["calendar"]["Monday"] == "reel_teaser"
        assert calendar["calendar"]["Tuesday"] == "snapchat_promo"
        assert calendar["calendar"]["Sunday"] == "casual_selfie"
        assert mix["wouldWrite"] is False
        assert calendar["wouldWrite"] is False
    finally:
        cf.close()


def test_story_inventory_rolls_up_story_intents(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_snap")
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_reel")
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_casual")
        cf.conn.execute(
            "UPDATE rendered_assets SET story_intent = 'snapchat_promo', story_style = 'casual' WHERE id = 'asset_story_snap'"
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET story_intent = 'reel_teaser', story_style = 'raw_phone' WHERE id = 'asset_story_reel'"
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET story_intent = 'casual_selfie', story_style = 'selfie' WHERE id = 'asset_story_casual'"
        )
        cf.conn.commit()

        inventory = cf.domains.story_management.story_inventory_report(creator="Stacey")
        summary = cf.domains.story_management.story_intent_summary(creator="Stacey")

        assert inventory["snapchatPromoStories"] == 1
        assert inventory["reelTeaserStories"] == 1
        assert inventory["casualStories"] == 1
        assert inventory["storyIntentCoverage"] is True
        assert summary["storyIntentPerformance"] == {}
        assert summary["storyStylePerformance"] == {}
        assert summary["wouldWrite"] is False
    finally:
        cf.close()


def test_register_surface_asset_feed_single_image_is_schedule_safe(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "feed_single.png")
        before = {
            "distribution_plans": table_count(cf, "distribution_plans"),
            "threadsdash_exports": table_count(cf, "threadsdash_exports"),
            "performance_snapshots": table_count(cf, "performance_snapshots"),
        }

        result = cf.domains.surface_registration.register_surface_asset(
            input_path=image,
            surface="feed_single",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            instagram_post_caption="new fit today",
        )

        asset = cf.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (result["renderedAssetId"],)
        ).fetchone()
        proof = cf.domains.surface_handoff.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_surface_nonreel_20260606",
            rendered_asset_id=result["renderedAssetId"],
        )
        draft = proof["drafts"][0]
        assert asset["content_surface"] == "feed_single"
        assert asset["media_type"] == "image"
        assert result["igMediaType"] == "IMAGE"
        assert result["publishability"] == "passed"
        assert proof["canProduceDraftPayload"] is True
        assert draft["contentSurface"] == "feed_single"
        assert draft["igMediaType"] == "IMAGE"
        assert (
            draft["handoffManifestV2"]["mediaItems"][0]["mediaHash"]
            == result["contentHash"]
        )
        assert table_count(cf, "distribution_plans") == before["distribution_plans"]
        assert table_count(cf, "threadsdash_exports") == before["threadsdash_exports"]
        assert (
            table_count(cf, "performance_snapshots") == before["performance_snapshots"]
        )
    finally:
        cf.close()


def test_register_surface_asset_story_image_and_video_keep_story_mapping(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "story.png")
        video = tmp_path / "story.mp4"
        video.write_bytes(b"story-video-placeholder")

        image_result = cf.domains.surface_registration.register_surface_asset(
            input_path=image,
            surface="story",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            story_asset_class="story_selfie",
            story_intent="casual_selfie",
            story_style="selfie",
        )
        video_result = cf.domains.surface_registration.register_surface_asset(
            input_path=video,
            surface="story",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            target_ratio="9:16",
            story_asset_class="story_selfie",
            story_intent="casual_selfie",
            story_style="selfie",
        )

        assert image_result["contentSurface"] == "story"
        assert image_result["igMediaType"] == "STORIES"
        assert image_result["publishability"] == "passed"
        assert video_result["contentSurface"] == "story"
        assert video_result["mediaType"] == "video"
        assert video_result["igMediaType"] == "STORIES"
        assert video_result["publishability"] == "blocked"
        proof = cf.domains.surface_handoff.surface_draft_proof(
            creator="Stacey", campaign="stacey_surface_nonreel_20260606"
        )
        drafts_by_asset = {draft["assetId"]: draft for draft in proof["drafts"]}
        blocked_by_asset = {item["assetId"]: item for item in proof["blockedAssets"]}
        assert (
            drafts_by_asset[image_result["renderedAssetId"]]["instagramPostCaption"]
            == ""
        )
        assert (
            "story_quality_gate_failed"
            in blocked_by_asset[video_result["renderedAssetId"]]["blockingReasons"]
        )
    finally:
        cf.close()


def test_register_surface_asset_story_rejects_rendered_reel_sources(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        rendered_dir = (
            tmp_path
            / "campaign_factory"
            / "campaigns"
            / "stacey"
            / "old_reel_campaign"
            / "02_rendered"
        )
        rendered_dir.mkdir(parents=True)
        reel_like = write_surface_image(
            rendered_dir / "parent_repair_captioned_reel.jpg"
        )

        with pytest.raises(ValueError, match="story source is not story-native"):
            cf.domains.surface_registration.register_surface_asset(
                input_path=reel_like,
                surface="story",
                creator="Stacey",
                campaign_slug="stacey_story_source_guard_20260609",
            )
    finally:
        cf.close()


def test_story_no_words_gate_blocks_rendered_text_in_image(tmp_path: Path):
    if not shutil.which("tesseract"):
        pytest.skip("tesseract is required for no-words Story OCR gate")
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    cf = make_factory(tmp_path)
    try:
        asset = add_story_quality_asset(
            cf,
            tmp_path,
            asset_id="asset_story_text_visible",
            quality_metadata={"storyNoTextRequired": True},
        )
        image_path = Path(asset["campaign_path"])
        image = Image.new("RGB", (1080, 1920), "white")
        draw = ImageDraw.Draw(image)
        draw.text((180, 850), "VISIBLE STORY TEXT", fill="black")
        image.save(image_path)

        quality = cf.domains.story_management.story_quality_gate_v1(
            "asset_story_text_visible"
        )

        assert quality["storyNoTextRequired"] is True
        assert quality["storyNoTextPassed"] is False
        assert "story_no_text_violation" in quality["failureReasons"]
    finally:
        cf.close()


def test_register_surface_asset_carousel_creates_ordered_components(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        components = [
            write_surface_image(tmp_path / f"carousel_{index}.png")
            for index in range(3)
        ]

        result = cf.domains.surface_registration.register_surface_asset(
            input_path=components,
            surface="feed_carousel",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            instagram_post_caption="which one wins?",
        )

        rows = cf.conn.execute(
            "SELECT * FROM asset_components WHERE asset_id = ? ORDER BY component_index",
            (result["renderedAssetId"],),
        ).fetchall()
        proof = cf.domains.surface_handoff.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_surface_nonreel_20260606",
            rendered_asset_id=result["renderedAssetId"],
        )
        media_items = proof["drafts"][0]["handoffManifestV2"]["mediaItems"]
        assert result["contentSurface"] == "feed_carousel"
        assert result["igMediaType"] == "CAROUSEL"
        assert result["publishability"] == "passed"
        assert [row["component_index"] for row in rows] == [0, 1, 2]
        assert all(row["media_hash"] for row in rows)
        assert [item["componentIndex"] for item in media_items] == [0, 1, 2]
        assert all(item["mediaHash"] for item in media_items)
    finally:
        cf.close()


def test_carousel_integrity_report_preserves_order_hashes_surface_and_caption_lineage(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        inputs = [
            write_rgb_png(
                tmp_path / f"integrity_carousel_{index}.png",
                1080,
                1080,
                color=(120 + index, 90, 180),
            )
            for index in range(3)
        ]
        registered = cf.domains.surface_registration.register_surface_asset(
            input_path=inputs,
            surface="feed_carousel",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            instagram_post_caption="which slide wins?",
            target_ratio="1:1",
            alt_text=["first", "second", "third"],
        )
        before = cf.conn.total_changes

        report = cf.domains.carousel_integrity.carousel_integrity_report(
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            rendered_asset_id=registered["renderedAssetId"],
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "campaign_factory.carousel_integrity_report.v1"
        assert report["wouldWrite"] is False
        assert report["carouselAssetsAnalyzed"] == 1
        item = report["assets"][0]
        assert item["contentSurfacePreserved"] is True
        assert item["captionLineagePreserved"] is True
        assert item["overallIntegrityPassed"] is True
        for boundary in item["boundaries"]:
            assert boundary["slideCountPreserved"] is True
            assert boundary["slideOrderPreserved"] is True
            assert boundary["componentHashesMatch"] is True
        assert (
            item["assetComponents"]["componentHashes"]
            == item["handoffManifestV2"]["componentHashes"]
        )
        assert (
            item["handoffManifestV2"]["componentHashes"]
            == item["surfaceDraftProof"]["componentHashes"]
        )
        assert (
            item["surfaceDraftProof"]["componentHashes"]
            == item["threadDashPayload"]["componentHashes"]
        )
        assert (
            item["threadDashPayload"]["componentHashes"]
            == item["metaChildPayloadPreview"]["componentHashes"]
        )
        assert item["threadDashPayload"]["contentSurface"] == "feed_carousel"
        assert (
            item["metaChildPayloadPreview"]["parentPayload"]["media_type"] == "CAROUSEL"
        )
    finally:
        cf.close()


@pytest.mark.parametrize("component_count", [1, 11])
def test_register_surface_asset_carousel_rejects_invalid_component_count(
    tmp_path: Path, component_count: int
):
    cf = make_factory(tmp_path)
    try:
        components = [
            write_surface_image(tmp_path / f"bad_carousel_{index}.png")
            for index in range(component_count)
        ]

        with pytest.raises(ValueError, match="carousel requires 2 to 10 components"):
            cf.domains.surface_registration.register_surface_asset(
                input_path=components,
                surface="feed_carousel",
                creator="Stacey",
                campaign_slug="stacey_surface_nonreel_20260606",
                instagram_post_caption="pick one",
            )
    finally:
        cf.close()


def test_register_surface_asset_feed_single_requires_caption_and_never_collapses_to_reel(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "feed_no_caption.png")

        with pytest.raises(ValueError, match="instagram_post_caption is required"):
            cf.domains.surface_registration.register_surface_asset(
                input_path=image,
                surface="feed_single",
                creator="Stacey",
                campaign_slug="stacey_surface_nonreel_20260606",
                instagram_post_caption="",
            )

        assert (
            cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"]
            == 0
        )
    finally:
        cf.close()


def test_variant_inventory_plan_can_fill_shortfall_from_eligible_parents(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        for asset_id in ("asset_parent_1", "asset_parent_2", "asset_parent_3"):
            add_inventory_parent_fixture(cf, tmp_path, asset_id=asset_id)

        plan = cf.domains.winner_expansion.variant_inventory_plan(
            creator="Stacey",
            campaign="stacey_archive_marketing_20260606",
            target_draft_shortfall=25,
            preset="caption_safe_v2",
            max_variants_per_parent=10,
            minimum_recommended_per_parent=3,
            dry_run=True,
        )

        assert plan["schema"] == "campaign_factory.variant_inventory_plan.v1"
        assert plan["creator"] == "Stacey"
        assert plan["targetDraftShortfall"] == 25
        assert plan["estimatedRecommendedVariants"] == 25
        assert plan["canFillShortfall"] is True
        assert plan["blockingReason"] == ""
        assert plan["nextSafeAction"] == "execute_contentforge_variant_batches"
        assert plan["wouldWrite"] is False
        assert [batch["requestedVariants"] for batch in plan["executionBatches"]] == [
            10,
            10,
            5,
        ]
        assert all(
            batch["minimumRecommended"] == 3 for batch in plan["executionBatches"]
        )
        assert plan["executionBatches"][0]["operationFamilies"][:6] == [
            "cover_frame",
            "timing_trim",
            "caption_lane_timing",
            "crop_zoom_family",
            "color_profile",
            "audio_offset",
        ]
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0] == 0
        )
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_variant_inventory_plan_blocks_when_parent_inventory_insufficient(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_parent_1")

        plan = cf.domains.winner_expansion.variant_inventory_plan(
            creator="Stacey",
            campaign="stacey_archive_marketing_20260606",
            target_draft_shortfall=25,
            max_variants_per_parent=10,
            minimum_recommended_per_parent=3,
            dry_run=True,
        )

        assert plan["canFillShortfall"] is False
        assert plan["estimatedRecommendedVariants"] == 10
        assert plan["missingRecommendedVariants"] == 15
        assert (
            plan["blockingReason"]
            == "insufficient_eligible_parent_inventory_missing_15_variants"
        )
        assert plan["nextSafeAction"] == "create_or_import_more_parent_reels"
    finally:
        cf.close()


def test_variant_inventory_plan_excludes_blocked_parent_reasons(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_quarantined")
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_missing_caption")
        add_inventory_parent_fixture(
            cf, tmp_path, asset_id="asset_missing_audio", audio_required=True
        )
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_missing_placement")
        cf.domains.publishability.quarantine_asset(
            "asset_quarantined", reason="operator_quarantine", root_cause="qc_failure"
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_missing_caption'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        },
                    }
                ),
            ),
        )
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_missing_placement'"
            ).fetchone()[0]
        )
        context.pop("captionPlacementPolicy", None)
        context.pop("captionPlacementDecision", None)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ? WHERE id = 'asset_missing_placement'",
            (json.dumps(context, sort_keys=True),),
        )
        cf.conn.commit()
        monkeypatch.setattr(
            core_module,
            "probe_video_metadata",
            lambda path: {"ok": True, "audioPresent": False},
        )

        plan = cf.domains.winner_expansion.variant_inventory_plan(
            creator="Stacey",
            campaign="stacey_archive_marketing_20260606",
            target_draft_shortfall=3,
            dry_run=True,
        )

        reasons = {
            row["parentAssetId"]: row["blockingReason"]
            for row in plan["blockedParents"]
        }
        assert plan["eligibleParents"] == []
        assert reasons["asset_quarantined"] == "quarantined_asset"
        assert reasons["asset_missing_caption"] == "missing_instagram_post_caption"
        assert reasons["asset_missing_audio"] == "embedded_audio_missing"
        assert reasons["asset_missing_placement"] == "caption_placement_qc_failed"
        assert all(row["wouldWrite"] is False for row in plan["blockedParents"])
    finally:
        cf.close()


def test_variant_inventory_plan_existing_siblings_reduce_estimated_capacity(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_1")
        for index, family_name in enumerate(
            ["cover_frame", "timing_trim", "caption_lane_timing", "crop_zoom_family"],
            start=1,
        ):
            add_variant_fixture(
                cf,
                tmp_path,
                variant_asset_id=f"asset_variant_{index}",
                variant_family_id="vfam_inventory",
                variant_index=index,
                family_name=family_name,
                content_hash=f"variant_hash_{index}",
            )

        plan = cf.domains.winner_expansion.variant_inventory_plan(
            creator="Stacey",
            campaign="stacey_archive_marketing_20260606",
            target_draft_shortfall=10,
            max_variants_per_parent=10,
            minimum_recommended_per_parent=3,
            dry_run=True,
        )

        parent = plan["eligibleParents"][0]
        assert parent["existingVariantCount"] == 4
        assert parent["existingRecommendedVariantCount"] == 4
        assert parent["estimatedNewRecommendedVariants"] == 6
        assert plan["executionBatches"][0]["requestedVariants"] == 6
        assert plan["executionBatches"][0]["operationFamilies"][:2] == [
            "color_profile",
            "audio_offset",
        ]
    finally:
        cf.close()


def test_variant_inventory_plan_prefers_winner_parent_over_non_winner(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        winner = add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_winner")
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_archive")
        campaign = cf.domains.campaign_by_slug("stacey_archive_marketing_20260606")
        asset = cf.domains.rendered_asset("asset_winner")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
             post_id, platform, status, instagram_account_id, snapshot_at, views, likes,
             comments, shares, saves, reach, metrics_eligible, concept_id, parent_reel_id,
             audio_id, created_at, published_at, history_source, lineage_v2_valid)
            VALUES ('perf_inventory_winner', ?, 'asset_winner', ?, 'hash_asset_winner', 'caption_hash_asset_winner',
             'post_winner', 'instagram', 'published', 'ig_1', '2026-01-02T00:00:00+00:00',
             12000, 700, 40, 80, 100, 11000, 1, ?, ?, 'audio_1',
             '2026-01-02T00:00:00+00:00', '2026-01-02T00:00:00+00:00', 'metric_history', 1)
            """,
            (
                campaign["id"],
                asset["source_asset_id"],
                winner["conceptId"],
                winner["parentReelId"],
            ),
        )
        cf.conn.commit()

        plan = cf.domains.winner_expansion.variant_inventory_plan(
            creator="Stacey",
            campaign="stacey_archive_marketing_20260606",
            target_draft_shortfall=12,
            max_variants_per_parent=10,
            dry_run=True,
        )

        assert [row["parentAssetId"] for row in plan["eligibleParents"][:2]] == [
            "asset_winner",
            "asset_archive",
        ]
        assert plan["eligibleParents"][0]["reasonEligible"] == "winner_metrics"
        assert plan["executionBatches"][0]["parentAssetId"] == "asset_winner"
    finally:
        cf.close()


def test_posts_read_paginates_beyond_page_size():
    client = _paged_posts_client(total_rows=750)
    rows, truncated = threadsdash_client_adapter._select_threadsdash_posts_paged(
        client, user_id="user_1", limit=1000, page_size=500
    )

    assert len(rows) == 750
    assert truncated is False
    assert len({row["id"] for row in rows}) == 750
    offsets = [int(call.get("offset", "0")) for call in client.calls]
    # A short-but-non-empty page is not treated as end-of-data (PostgREST
    # `max-rows` can silently clamp pages below the requested limit), so the
    # reader pages from the real offset until it sees an empty page. The final
    # call at offset 750 returns [] and terminates the loop without a probe.
    assert offsets == [0, 500, 750]


def test_posts_read_detects_truncation_at_limit():
    client = _paged_posts_client(total_rows=1200)
    rows, truncated = threadsdash_client_adapter._select_threadsdash_posts_paged(
        client, user_id="user_1", limit=1000, page_size=500
    )

    assert len(rows) == 1000
    assert truncated is True
    # final call is the 1-row truncation probe
    assert client.calls[-1]["limit"] == "1"
    assert client.calls[-1]["offset"] == "1000"


def test_posts_compatibility_reader_fails_closed_on_truncation():
    client = _paged_posts_client(total_rows=1001)

    with pytest.raises(RuntimeError, match="threadsdash_posts_truncated"):
        threadsdash_client_adapter._select_threadsdash_posts(
            client, user_id="user_1", limit=1000
        )


def test_campaign_filtered_posts_read_accepts_internal_id_and_slug():
    client = _paged_posts_client(total_rows=0)

    rows, truncated = threadsdash_client_adapter._select_threadsdash_posts_paged(
        client,
        user_id="user_1",
        campaign_ids=["campaign_internal", "stacey_learning_cohort_v1"],
        limit=1000,
        page_size=500,
    )

    assert rows == []
    assert truncated is False
    assert client.calls[0]["metadata->campaign_factory->>campaign_id"] == (
        'in.("campaign_internal","stacey_learning_cohort_v1")'
    )


def test_campaign_health_asset_detail_ranking_and_api(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    settings = cf.settings
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        failed = cf.domains.events.create_pipeline_job("run_reel", campaign["id"], {})
        cf.domains.events.start_pipeline_job(failed["id"])
        cf.domains.events.fail_pipeline_job(failed["id"], "old failure")
        succeeded = cf.domains.events.create_pipeline_job(
            "run_reel", campaign["id"], {}
        )
        cf.domains.events.start_pipeline_job(succeeded["id"])
        cf.domains.events.finish_pipeline_job(succeeded["id"], {"ok": True})
        health = cf.domains.campaign_overview.campaign_health("may")
        assert health["counts"]["sourcesImported"] == 1
        assert health["counts"]["renderedAssets"] == 1
        assert health["counts"]["auditedAssets"] == 1
        assert health["counts"]["approvedAssets"] == 1
        assert health["counts"]["exportReadyAssets"] == 1
        assert health["counts"]["failedJobs"] == 0

        detail = cf.domains.campaign_overview.asset_detail("asset_1")
        assert detail["asset"]["id"] == "asset_1"
        assert detail["source"]["id"] == detail["asset"]["source_asset_id"]
        assert detail["audits"][0]["id"] == "audit_1"
        assert detail["ranking"]["score"] > 0

        readiness = cf.domains.lifecycle_reporting.campaign_readiness(
            "may", user_id="user_1"
        )
        assert readiness["ready"] is True
        assert readiness["health"]["counts"]["approvedAssets"] == 1
        ranking = cf.domains.account_planning.ranking("may")
        assert ranking["assets"][0]["renderedAssetId"] == "asset_1"
        assert ranking["assets"][0]["breakdown"]["sourceHistory"] == 50
    finally:
        cf.close()

    monkeypatch.setattr(app_module, "settings", settings)
    client = TestClient(app_module.app)
    assert (
        client.get("/api/campaign-health", params={"campaign": "may"}).status_code
        == 200
    )
    assert client.get("/api/asset-detail/asset_1").status_code == 200
    assert client.get("/api/ranking", params={"campaign": "may"}).status_code == 200
    assert client.get("/api/autonomy-policy").json()["level"] == "level_2"
    set_policy_response = client.post("/api/autonomy-policy", json={"level": "level_2"})
    assert set_policy_response.status_code == 200
    trust_response = client.get("/api/trust-summary", params={"campaign": "may"})
    assert trust_response.status_code == 200
    assert trust_response.json()["schema"] == "campaign_factory.trust_summary.v1"
    recommend_response = client.post(
        "/api/recommendations/run",
        json={"campaign": "may", "count": 3, "persist": True},
    )
    assert recommend_response.status_code == 200
    assert (
        recommend_response.json()["schema"]
        == "campaign_factory.recommendations.next_batch.v1"
    )
    assert recommend_response.json()["items"][0]["renderedAssetId"] == "asset_1"
    recommendation_item_id = recommend_response.json()["items"][0]["recommendationId"]
    accept_response = client.post(
        f"/api/recommendations/{recommendation_item_id}/accept",
        json={"operator": "api_user"},
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["status"] == "accepted"
    link_response = client.post(
        f"/api/recommendations/{recommendation_item_id}/link",
        json={"renderedAssetId": "asset_1"},
    )
    assert link_response.status_code == 200
    assert link_response.json()["status"] == "executed"
    execute_response = client.post(
        f"/api/recommendations/{recommendation_item_id}/execute",
        json={"runAudit": False},
    )
    assert execute_response.status_code == 200
    assert execute_response.json()["recommendation"]["status"] == "executed"
    memory_rebuild_response = client.post(
        "/api/account-memory/rebuild", json={"campaign": "may"}
    )
    assert memory_rebuild_response.status_code == 200
    memory_response = client.get("/api/account-memory", params={"campaign": "may"})
    assert memory_response.status_code == 200
    exceptions_response = client.get(
        "/api/exceptions", params={"campaign": "may", "status": "open"}
    )
    assert exceptions_response.status_code == 200
    stored_recommendations = client.get(
        "/api/recommendations", params={"campaign": "may"}
    )
    assert stored_recommendations.status_code == 200
    assert (
        stored_recommendations.json()["runs"][0]["items"][0]["renderedAssetId"]
        == "asset_1"
    )
    accuracy_response = client.get(
        "/api/recommendations/accuracy", params={"campaign": "may", "windowDays": 365}
    )
    assert accuracy_response.status_code == 200
    assert (
        accuracy_response.json()["schema"]
        == "campaign_factory.recommendation_accuracy_report.v1"
    )
    ready_response = client.post(
        "/api/campaign-readiness", json={"campaign": "may", "userId": "user_1"}
    )
    assert ready_response.status_code == 200
    assert ready_response.json()["ready"] is True


def test_story_inventory_report_counts_schedule_safe_and_blocked_assets(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_safe",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_blocked",
            content_surface="story",
            media_type="other",
            instagram_post_caption="",
        )
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET story_asset_class = 'story_mirror',
                story_cta_type = 'bio_link',
                story_cta_text = 'more of me',
                story_cta_target_url = 'https://example.com/stacey'
            WHERE id = 'asset_story_safe'
            """
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET story_asset_class = NULL, caption_generation_json = '{}' WHERE id = 'asset_story_blocked'"
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.domains.story_management.story_inventory_report(creator="Stacey")

        assert cf.conn.total_changes == before
        assert report["storyAssetsAvailable"] == 2
        assert report["storyAssetsPublishable"] == 2
        assert report["storyAssetsScheduleSafe"] == 1
        assert report["storyAssetsBlocked"] == 1
        assert report["storyClassifications"] == {"story_mirror": 1}
        assert report["storyCtaTypes"] == {"bio_link": 1}
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_and_inventory_autopilot_plans_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        parent = cf.domains.parent_factory_planning.parent_factory_autopilot_plan(
            accounts=200, posts_per_account_per_day=3
        )
        shortfall = cf.domains.parent_factory_planning.parent_factory_shortfall_report(
            accounts=200, posts_per_account_per_day=3
        )
        targets = cf.domains.parent_factory_planning.parent_factory_production_targets(
            accounts=200, posts_per_account_per_day=3
        )
        inventory = cf.domains.inventory_planning.inventory_autopilot_plan(
            accounts=100, posts_per_account_per_day=3, available_inventory=0
        )
        repair = cf.domains.inventory_planning.inventory_shortage_repair_plan(
            accounts=100, posts_per_account_per_day=3, available_inventory=0
        )
        buffer = cf.domains.inventory_planning.inventory_buffer_protection_report(
            accounts=100, posts_per_account_per_day=3, available_inventory=0
        )

        assert cf.conn.total_changes == before
        assert parent["schema"] == "creator_os.parent_factory_autopilot_plan.v1"
        assert parent["requiredParentsToday"] == 53
        assert parent["shortfall"] >= 0
        assert parent["requiredRawCandidates"] >= parent["requiredParentsToday"]
        assert parent["requiredCaptionFamilies"] == parent["requiredParentsToday"]
        assert parent["requiredVariants"] >= 600
        assert shortfall["schema"] == "creator_os.parent_factory_shortfall_report.v1"
        assert targets["schema"] == "creator_os.parent_factory_production_targets.v1"
        assert inventory["schema"] == "creator_os.inventory_autopilot_plan.v1"
        assert inventory["repairActions"]
        assert repair["schema"] == "creator_os.inventory_shortage_repair_plan.v1"
        assert repair["repairActions"] == inventory["repairActions"]
        assert buffer["schema"] == "creator_os.inventory_buffer_protection_report.v1"
        assert buffer["health"] == "critical"
        assert all(
            item["wouldWrite"] is False
            for item in [parent, shortfall, targets, inventory, repair, buffer]
        )
    finally:
        cf.close()


def test_inventory_reservation_blocks_computed_pdq_cluster_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account_a = cf.domains.models.upsert_account(
            "stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"]
        )
        account_b = cf.domains.models.upsert_account(
            "stacey_b", platform="instagram", external_id="ig_b", model_id=model["id"]
        )
        for index in range(2):
            add_surface_asset_fixture(
                cf,
                tmp_path,
                asset_id=f"asset_pdq_cluster_{index}",
                content_surface="reel",
                media_type="video",
                instagram_post_caption="lmk",
            )

        def fake_pdq(path: Path, **_: Any) -> dict[str, Any]:
            name = Path(path).name
            fingerprint = (
                ("0" * 64) if "asset_pdq_cluster_0" in name else ("0" * 63 + "1")
            )
            return {
                "status": "available",
                "algorithm": "pdq_v1",
                "fingerprint": fingerprint,
                "quality": 100,
                "source": "first_frame",
            }

        monkeypatch.setattr(core_module, "compute_pdq_fingerprint", fake_pdq)

        first = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset_pdq_cluster_0",
            account_id=account_a["id"],
            surface="reel",
            reserved_by="test",
        )

        with pytest.raises(
            ValueError, match="cross-account source/perceptual reuse cooldown conflict"
        ):
            cf.domains.inventory_reservations.reserve_inventory_asset(
                "asset_pdq_cluster_1",
                account_id=account_b["id"],
                surface="reel",
                reserved_by="test",
            )

        second = cf.domains.rendered_asset("asset_pdq_cluster_1")
        second_metadata = json.loads(second["metadata_json"])
        assert first["perceptual_cluster_id"].startswith("pdq:")
        assert second_metadata["perceptualFingerprint"] == "0" * 63 + "1"
        assert second_metadata["perceptualClusterId"] == first["perceptual_cluster_id"]
    finally:
        cf.close()


def test_inventory_reservation_expired_ttl_is_released_from_net_inventory(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        for index in range(10):
            cf.domains.models.upsert_account(
                f"stacey_{index}",
                platform="instagram",
                external_id=f"ig_{index}",
                model_id=model["id"],
            )
        for index in range(90):
            add_surface_asset_fixture(
                cf,
                tmp_path,
                asset_id=f"asset_ttl_inventory_{index}",
                content_surface="feed_single",
                media_type="image",
                instagram_post_caption="schedule safe",
            )
        expired = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset_ttl_inventory_0",
            surface="feed_single",
            reserved_by="test",
            expires_at="2026-01-01T00:00:00+00:00",
        )

        result = cf.domains.live_acceptance.creator_os_live_account_acceptance(
            account_target=10, content_surface="feed_single"
        )
        row = cf.conn.execute(
            "SELECT status FROM asset_inventory_reservations WHERE id = ?",
            (expired["id"],),
        ).fetchone()

        assert row["status"] == "expired"
        assert result["reservedInventory"] == 0
        assert result["netInventory"] == 90
    finally:
        cf.close()


def test_inventory_reservation_concurrent_claim_cannot_double_claim(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_concurrent_claim",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="schedule safe",
        )
    finally:
        cf.close()

    barrier = threading.Barrier(2)

    def claim(label: str) -> tuple[str, str]:
        worker = make_factory(tmp_path)
        try:
            barrier.wait(timeout=5)
            reservation = worker.domains.inventory_reservations.reserve_inventory_asset(
                "asset_concurrent_claim",
                surface="feed_single",
                reserved_by=label,
            )
            return ("reserved", reservation["asset_id"])
        except ValueError as exc:
            return ("blocked", str(exc))
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result()
            for future in [
                executor.submit(claim, "first"),
                executor.submit(claim, "second"),
            ]
        ]

    first = make_factory(tmp_path)
    try:
        assert [status for status, _ in outcomes].count("reserved") == 1
        assert [status for status, _ in outcomes].count("blocked") == 1
        assert (
            first.conn.execute(
                "SELECT COUNT(*) AS c FROM asset_inventory_reservations WHERE asset_id = ? AND status IN ('pending', 'committed')",
                ("asset_concurrent_claim",),
            ).fetchone()["c"]
            == 1
        )
    finally:
        first.close()


def test_inventory_consumption_and_production_requirements_use_real_calculations(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        simulation = cf.domains.inventory_planning.inventory_consumption_simulation(
            available_inventory=1800
        )
        production = cf.domains.inventory_planning.inventory_production_requirements(
            accounts=200, posts_per_account_per_day=3
        )
        road = cf.domains.inventory_planning.road_to_200_accounts()

        assert cf.conn.total_changes == before
        assert simulation["schema"] == "creator_os.inventory_consumption_simulation.v1"
        row_200 = next(
            row for row in simulation["simulations"] if row["accounts"] == 200
        )
        assert row_200["dailyDemand"] == 600
        assert row_200["inventoryConsumed"] == 600
        assert row_200["daysUntilEmpty"] == 3
        assert row_200["requiredProductionRate"] == 600
        assert simulation["wouldWrite"] is False
        assert production["schema"] == "creator_os.inventory_production_requirements.v1"
        assert production["accounts"] == 200
        assert production["postsPerDay"] == 600
        assert production["requiredValidatedDraftsPerDay"] == 600
        assert production["requiredVariantsPerDay"] >= 600
        assert production["requiredParentsPerDay"] > 0
        assert production["wouldWrite"] is False
        assert road["schema"] == "creator_os.road_to_200_accounts.v1"
        assert road["requiredInventoryBuffer"] == "1800 schedule-safe drafts"
        assert road["requiredDailyProduction"] == "600 schedule-safe drafts/day"
        assert road["requiredExceptionRate"] == "<=2.0% inventory-blocking exceptions"
        assert road["wouldWrite"] is False
    finally:
        cf.close()
