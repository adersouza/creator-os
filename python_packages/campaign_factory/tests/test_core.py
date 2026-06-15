from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import struct
import shutil
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import campaign_factory.app as app_module
import campaign_factory.core as core_module
from campaign_factory.audio_smoke import (
    CONTENTFORGE_SMOKE_RESPONSE,
    SMOKE_CSV,
    SMOKE_SNAPSHOT_CSV,
    add_smoke_audit_report,
    assert_contentforge_contract_response,
    assert_smoke_draft_audio_intent,
    create_smoke_campaign_asset,
    sync_smoke_performance,
    write_smoke_audio_csv,
    write_smoke_audio_snapshot_csv,
)
from campaign_factory.adapters.contentforge import audit_campaign
from campaign_factory.adapters import contentforge as contentforge_adapter
from campaign_factory.adapters import threadsdash as threadsdash_adapter
from campaign_factory.adapters.threadsdash import (
    build_draft_payloads,
    clear_preview_schedule,
    evaluate_export_readiness,
    export_threadsdash,
    preflight_supabase,
    safe_live_smoke_export,
    summarize_threadsdash_usage,
    sync_threadsdash_account_assignments,
    sync_performance_snapshots,
    verify_threadsdash_export,
)
from campaign_factory.config import Settings
from campaign_factory.contracts import (
    validate_audio_catalog_export,
    validate_audio_intent,
    validate_performance_sync,
    validate_recommendation_accuracy_report,
    validate_recommendation_next_batch,
    validate_schema_examples,
    validate_threadsdash_draft_payload,
)
from campaign_factory.control import operator_control_check
from campaign_factory.core import CampaignFactory
from campaign_factory.db import _repair_source_asset_fk_references
from campaign_factory.pipeline_smoke import _run_mocked_generation_intake_smoke
from campaign_factory.readiness_report import build_mass_production_readiness_report
from campaign_factory.reel_ledger_promotion import promote_reel_ledger
from campaign_factory.caption_outcome import build_caption_outcome_context, column_values


def make_factory(tmp_path: Path) -> CampaignFactory:
    reel_root = tmp_path / "reel_factory"
    (reel_root / "00_source_videos").mkdir(parents=True)
    (reel_root / "01_captions").mkdir(parents=True)
    return CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=reel_root,
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))


def test_caption_outcome_context_preserves_additive_scene_fields():
    existing = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": "caption_hash",
        "caption_text": "caption",
        "caption_bank": "shared_girl_next_door",
        "caption_banks": ["shared_girl_next_door"],
        "captionSceneTags": ["pool"],
        "reelSceneTags": ["indoor_selfie"],
        "sceneCompatibilityDecision": "blocked",
        "sceneCompatibilityReason": "pool caption blocked for indoor_selfie reel",
        "captionSceneFitVersion": "v1",
    }

    rebuilt = build_caption_outcome_context(lineage=existing)
    columns = column_values(rebuilt)
    stored = json.loads(columns["caption_outcome_context_json"])

    assert rebuilt["captionSceneTags"] == ["pool"]
    assert rebuilt["reelSceneTags"] == ["indoor_selfie"]
    assert rebuilt["sceneCompatibilityDecision"] == "blocked"
    assert stored["captionSceneFitVersion"] == "v1"


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
            (source_id, campaign_id, f"source-{campaign_id}", str(tmp_path / "source.mp4"), str(tmp_path / "source.mp4"), now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, created_at, updated_at)
            VALUES (?, ?, ?, 'same-render-hash', ?, ?, ?, ?, ?)
            """,
            (asset_id, campaign_id, source_id, str(tmp_path / f"{slug}.mp4"), str(tmp_path / f"{slug}.mp4"), f"{slug}.mp4", now, now),
        )
    rows = cf.conn.execute(
        "SELECT id FROM rendered_assets WHERE content_hash = 'same-render-hash' ORDER BY id"
    ).fetchall()
    assert [row["id"] for row in rows] == ["asset_a", "asset_b"]


def test_operator_control_check_reports_required_entrypoints(tmp_path: Path):
    root = tmp_path / "campaign_factory"
    reel_root = tmp_path / "reel_factory"
    contentforge_root = tmp_path / "contentforge"
    reference_root = tmp_path / "reference_factory"
    threadsdash_root = tmp_path / "ThreadsDashboard"
    for path in [
        root / "campaign_factory",
        reel_root,
        contentforge_root / "app" / "api" / "variant-pack",
        contentforge_root / "app" / "api" / "similarity",
        reference_root / "reference_factory",
        threadsdash_root,
    ]:
        path.mkdir(parents=True, exist_ok=True)
    (root / "campaign_factory" / "cli.py").write_text("", encoding="utf-8")
    (reel_root / "reel_pipeline.py").write_text("", encoding="utf-8")
    (reel_root / "slideshow_factory.py").write_text("", encoding="utf-8")
    (contentforge_root / "package.json").write_text("{}", encoding="utf-8")
    (contentforge_root / "app" / "api" / "variant-pack" / "route.js").write_text("", encoding="utf-8")
    (contentforge_root / "app" / "api" / "similarity" / "route.js").write_text("", encoding="utf-8")
    (reference_root / "reference_factory" / "cli.py").write_text("", encoding="utf-8")
    (root / "schemas").mkdir(parents=True)
    for name in [
        "audio_intent.v1.schema.json",
        "campaign_draft_payload.v1.schema.json",
        "audio_catalog_export.v1.schema.json",
        "performance_sync.v1.schema.json",
    ]:
        (root / "schemas" / name).write_text("{}", encoding="utf-8")
    settings = Settings(
        root=root,
        db_path=root / "campaign_factory.sqlite",
        reel_factory_root=reel_root,
        contentforge_root=contentforge_root,
        reference_factory_root=reference_root,
        threadsdash_root=threadsdash_root,
        campaigns_dir=root / "campaigns",
    )

    result = operator_control_check(settings)

    assert result["ok"] is True
    assert result["blockingCount"] == 0
    assert any(check["name"] == "reference_bank" for check in result["checks"])
    assert any(check["name"] == "schema.audio_intent" for check in result["checks"])
    assert any(check["name"] == "ffmpeg" for check in result["checks"])
    assert "make-batch" in result["commands"]["makeBatch"]


def test_contract_schema_examples_validate():
    checks = validate_schema_examples()
    assert {check["name"] for check in checks} == {
        "audio_intent.v1.example.json",
        "audio_catalog_export.v1.example.json",
        "campaign_draft_payload.v1.example.json",
        "caption_outcome_context.v1.example.json",
        "creative_plan.v1.example.json",
        "generated_asset_lineage.v1.example.json",
        "higgsfield_soul_image_prompt.v1.example.json",
        "kling_3_video_prompt.v1.example.json",
        "performance_sync.v1.example.json",
        "pattern_card.v1.example.json",
        "recommendation_accuracy_report.v1.example.json",
        "recommendation_next_batch.v1.example.json",
        "repurposing_plan.v1.example.json",
        "video_analysis.v1.example.json",
    }


def test_import_folder_dedupes_by_hash_and_ignores_unsupported(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"same")
    (folder / "b.mov").write_bytes(b"same")
    (folder / "ignore.txt").write_text("no")
    cf = make_factory(tmp_path)
    try:
        result = cf.import_folder(folder, campaign_slug="May Launch", model_slug="Model A", account_handles=["ig_a"])
        assert len(result["imported"]) == 1
        assert len(result["duplicates"]) == 1
        assert len(result["ignored"]) == 1
        stored = Path(result["imported"][0]["stored_path"])
        assert stored.exists()
        assert "00_sources" in str(stored)
    finally:
        cf.close()


def test_import_folder_allows_same_source_in_different_campaigns(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"same")
    cf = make_factory(tmp_path)
    try:
        first = cf.import_folder(folder, campaign_slug="first", model_slug="model")
        second = cf.import_folder(folder, campaign_slug="second", model_slug="model")

        assert len(first["imported"]) == 1
        assert len(second["imported"]) == 1
        assert first["imported"][0]["content_hash"] == second["imported"][0]["content_hash"]
        assert first["imported"][0]["campaign_id"] != second["imported"][0]["campaign_id"]
    finally:
        cf.close()


def test_db_repair_restores_source_asset_foreign_key_table_names():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        CREATE TABLE source_assets (id TEXT PRIMARY KEY);
        CREATE TABLE source_assets_old_global_hash (id TEXT PRIMARY KEY);
        CREATE TABLE render_jobs (
          id TEXT PRIMARY KEY,
          source_asset_id TEXT NOT NULL,
          FOREIGN KEY(source_asset_id) REFERENCES "source_assets_old_global_hash"(id)
        );
        INSERT INTO render_jobs (id, source_asset_id) VALUES ('job_1', 'src_1');
        """
    )

    _repair_source_asset_fk_references(conn)

    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'render_jobs'").fetchone()["sql"]
    assert "source_assets_old_global_hash" not in sql
    assert "source_assets" in sql
    assert conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"] == 1


def test_import_folder_accepts_images_as_slideshow_sources(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"image")
    cf = make_factory(tmp_path)
    try:
        result = cf.import_folder(folder, campaign_slug="May Slides", model_slug="Model A")

        assert len(result["imported"]) == 1
        assert result["imported"][0]["media_type"] == "image"
        assert cf.assets_for_campaign(result["campaign"]["id"])[0]["media_type"] == "image"
    finally:
        cf.close()


def test_prepare_reel_writes_video_and_caption_sidecar(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        result = cf.prepare_reel_inputs(campaign_slug="may", hooks=["hook one"], recipes=["v01_original"], caption_color="auto")
        job = result["prepared"][0]
        video = cf.settings.reel_factory_root / "00_source_videos" / f"{job['reel_clip_stem']}.mp4"
        sidecar = cf.settings.reel_factory_root / "01_captions" / f"{job['reel_clip_stem']}.json"
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
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        result = cf.prepare_reel_inputs(
            campaign_slug="may",
            hooks=["hook one", "hook two", "hook three"],
            recipes=["v01_original", "v05_hflip"],
            caption_color="auto",
        )
        stems = [job["reel_clip_stem"] for job in result["prepared"]]
        first = json.loads((cf.settings.reel_factory_root / "01_captions" / f"{stems[0]}.json").read_text())
        second = json.loads((cf.settings.reel_factory_root / "01_captions" / f"{stems[1]}.json").read_text())
        assert first["hooks"] == ["hook one", "hook two", "hook three"]
        assert second["hooks"] == ["hook two", "hook three", "hook one"]
    finally:
        cf.close()


def test_reference_bank_import_select_and_prepare(tmp_path: Path):
    bank_path = tmp_path / "campaign_reference_bank.json"
    prompt_pack_path = tmp_path / "higgsfield_prompt_pack_top300.json"
    bank_path.write_text(json.dumps({
        "schema": "reference_factory.campaign_reference_bank.v1",
        "clusters": [
            {
                "clusterRank": 1,
                "clusterKey": "caption_led_visual::direct_response::question_hook",
                "label": "caption led visual / direct response / question hook",
                "visualFormat": "caption_led_visual",
                "hookType": "direct_response",
                "captionArchetype": "question_hook",
                "referenceIds": ["ref_1"],
                "localPaths": [str(tmp_path / "ref.mp4")],
                "promptTemplate": {"captionBrief": "short direct question"},
                "audioRecommendations": {
                    "schema": "reference_factory.audio_recommendations.v1",
                    "primaryStrategy": "light_trending_response_sound",
                    "nativeAudioPreferred": True,
                    "recommendations": [
                        {
                            "platform": "instagram",
                            "audioId": "ig_audio_1",
                            "audioVibe": "caption_friendly",
                            "instruction": "Use a low-volume native trending sound.",
                        }
                    ],
                },
            }
        ],
    }))
    prompt_pack_path.write_text(json.dumps({
        "schema": "reference_factory.higgsfield_prompt_pack.v1",
        "prompts": [
            {
                "clusterKey": "caption_led_visual::direct_response::question_hook",
                "referenceIds": ["ref_1"],
                "publicUrls": ["https://instagram.com/p/example/"],
                "higgsfieldJson": {"scene": "caption-led vertical reel"},
                "captionFormulas": [{"formula": "{direct question}?", "exampleCaptions": ["red or pink ?"]}],
                "audioRecommendations": {
                    "primaryStrategy": "current_native_trending_sound",
                    "nativeAudioPreferred": True,
                },
            }
        ],
    }))
    (tmp_path / "ref.mp4").write_bytes(b"reference")
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        imported = cf.import_reference_bank(bank_path, prompt_pack_path)
        assert imported["patternsImported"] == 1
        patterns = cf.reference_patterns()
        assert patterns["patterns"][0]["captionFormulas"][0]["formula"] == "{direct question}?"
        assert patterns["patterns"][0]["audioRecommendations"]["primaryStrategy"] == "light_trending_response_sound"
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        prepared = cf.prepare_reel_from_reference(
            campaign_slug="may",
            cluster_key="caption_led_visual::direct_response::question_hook",
            variant_count=2,
            recipes=["v01_original"],
        )
        assert prepared["selection"]["pattern"]["label"].startswith("caption led visual")
        sidecar = cf.settings.reel_factory_root / "01_captions" / f"{prepared['prepare']['prepared'][0]['reel_clip_stem']}.json"
        sidecar_data = json.loads(sidecar.read_text())
        assert sidecar_data["hooks"][0] == "red or pink ?"
        assert sidecar_data["hook_metadata"][0]["referenceClusterKey"] == "caption_led_visual::direct_response::question_hook"
        assert sidecar_data["hook_metadata"][0]["text"] == "red or pink ?"
        assert sidecar_data["hook_metadata"][0]["candidateKind"] == "example_caption"
        assert sidecar_data["hook_metadata"][0]["audioRecommendations"]["primaryStrategy"] == "light_trending_response_sound"
        generation_payload = cf._caption_generation_for_clip(prepared["prepare"]["prepared"][0]["reel_clip_stem"])
        assert generation_payload["audioRecommendations"]["primaryStrategy"] == "light_trending_response_sound"
        second = cf.prepare_reel_from_reference(
            campaign_slug="may",
            cluster_key="caption_led_visual::direct_response::question_hook",
            variant_count=1,
            recipes=["v01_original"],
        )
        assert second["prepare"]["prepared"][0]["reel_clip_stem"] != prepared["prepare"]["prepared"][0]["reel_clip_stem"]
        assert second["prepare"]["reusedExisting"] == []
    finally:
        cf.close()


def test_reference_hooks_filter_unsafe_placeholder_and_long_hooks(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        pattern = {
            "clusterKey": "caption_led_visual::curiosity_gap::short_meme_caption",
            "label": "caption led visual / curiosity gap / short meme caption",
            "hookType": "curiosity_gap",
            "captionArchetype": "short_meme_caption",
            "captionFormulas": [
                {
                    "formula": "{short claim} + one emoji",
                    "exampleCaptions": [
                        "DM me",
                        "this caption is intentionally way too long for schedule safe burned reel placement",
                        "GOING LIVE TONIGHT!!!",
                        "he can’t resist me 😈",
                        "Who’s my good boy then",
                        "Du entscheidest🇦🇹🇩🇪",
                        "mirror check",
                    ],
                }
            ],
            "audioRecommendations": {},
        }

        hooks = cf.reference_hooks(pattern, count=3)

        assert [hook["text"] for hook in hooks] == ["mirror check", "mirror check", "mirror check"]
        assert all(hook["candidateKind"] == "example_caption" for hook in hooks)
    finally:
        cf.close()


def test_audio_catalog_import_and_recommendation_flow(tmp_path: Path):
    catalog_path = tmp_path / "audio_catalog.json"
    catalog_path.write_text(json.dumps({
        "schema": "reference_factory.audio_catalog_export.v1",
        "items": [
            {
                "id": "aud_1",
                "title": "Runway Pop",
                "artistName": "DJ A",
                "platform": "instagram",
                "nativeAudioId": "ig_1",
                "nativeAudioUrl": "https://instagram.com/audio/1",
                "moodTags": ["glam", "confident"],
                "bestContentTypes": ["fit_check", "mirror_selfie"],
                "accountFit": ["ig_a"],
                "trendStatus": "rising",
                "usageCount": 120000,
                "bpm": 124,
                "energy": 8,
                "safeUsageNotes": "attach natively",
            },
            {
                "id": "aud_2",
                "title": "Sleepy Song",
                "artistName": "DJ B",
                "platform": "instagram",
                "nativeAudioId": "ig_2",
                "moodTags": ["chill"],
                "bestContentTypes": ["tutorial"],
                "trendStatus": "stale",
                "usageCount": 500,
            },
        ],
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        imported = cf.import_audio_catalog(catalog_path)
        recs = cf.recommend_audio(platform="instagram", content_tags=["fit_check", "glam"], account_tags=["ig_a"], limit=2)

        assert imported["tracksImported"] == 2
        assert recs["recommendations"][0]["audioTitle"] == "Runway Pop"
        assert recs["recommendations"][0]["platformUrl"] == "https://instagram.com/audio/1"
        assert recs["recommendations"][0]["safeUsageNotes"] == "attach natively"
    finally:
        cf.close()


def test_audio_memory_import_selects_and_graphs_recommended_audio(tmp_path: Path):
    catalog_path = tmp_path / "audio_memory.json"
    catalog_path.write_text(json.dumps({
        "schema": "reference_factory.audio_catalog_export.v1",
        "items": [
            {
                "id": "aud_mem",
                "title": "Mirror Trend",
                "artistName": "DJ M",
                "platform": "instagram",
                "nativeAudioId": "ig_mem",
                "nativeAudioUrl": "https://instagram.com/audio/mem",
                "moodTags": ["mirror"],
                "bestContentTypes": ["v01_original"],
                "accountFit": ["ig_1"],
                "trendStatus": "rising",
                "trendScore": 91,
                "velocityScore": 88,
                "creatorFitScore": 94,
                "usageCount": 50000,
                "trendSources": ["reference_factory", "tiktok_creative_center"],
                "trendSnapshots": [{"observedAt": "2026-01-01T00:00:00+00:00", "trendStatus": "rising", "usageCount": 50000, "velocityScore": 88}],
                "exampleReels": ["https://instagram.com/reel/example"],
                "performanceSummary": {"postCount": 3, "performanceLift": 12},
                "fatigue": {"level": "low"},
                "resolved": True,
                "sourceConfidence": 0.9,
            }
        ],
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        first_import = cf.import_audio_memory(catalog_path)
        second_import = cf.import_audio_memory(catalog_path)
        assert first_import["tracksImported"] == 1
        assert second_import["trendSnapshotsImported"] == 1
        assert cf.conn.execute("SELECT COUNT(*) FROM audio_catalog").fetchone()[0] == 1
        assert cf.conn.execute("SELECT COUNT(*) FROM audio_trend_snapshots").fetchone()[0] == 1

        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        rec = cf.recommend_next_batch("may", count=1, account="ig_1", persist=True)
        item = rec["items"][0]
        assert item["audioRecommendations"]["recommendations"][0]["audioTitle"] == "Mirror Trend"
        assert item["audioDecision"]["primaryAudio"]["audioTitle"] == "Mirror Trend"
        assert item["audioDecision"]["decisionConfidence"] in {"usable", "strong"}
        assert item["audioRecommendations"]["recommendations"][0]["audioMemoryGraphId"].startswith("cg_audio_memory_")
        assert item["audioRecommendations"]["recommendations"][0]["scoreComponents"]["creatorFit"] == 94
        assert item["audioRecommendations"]["recommendations"][0]["recommendationConfidence"] in {"usable", "strong"}
        memory = cf.audio_memory(platform="instagram", account="ig_1", limit=5)
        assert memory["audioTrust"]["averageScore"] is not None
        assert memory["items"][0]["audioMemoryScore"] > 80

        selected = cf.select_audio_for_recommendation(item["recommendationId"], "aud_mem", operator="tester")
        assert selected["selection"]["status"] == "selected"
        updated = cf.rendered_asset("asset_1")
        caption_generation = json.loads(updated["caption_generation_json"])
        assert caption_generation["audioIntent"]["status"] == "selected"
        assert caption_generation["audioIntent"]["operator_selection"]["catalog_audio_id"] == "aud_mem"
        edges = {
            row["relation_type"]
            for row in cf.conn.execute("SELECT relation_type FROM content_graph_edges").fetchall()
        }
        assert "recommendation_item_to_audio_recommendation" in edges
        assert "audio_recommendation_to_audio_selection" in edges
        assert "audio_memory_to_audio_selection" in edges
        assert source["id"]
    finally:
        cf.close()


def test_audio_recommendations_include_contentforge_audio_fit_when_available(tmp_path: Path):
    contentforge_lib = tmp_path / "contentforge" / "lib"
    contentforge_lib.mkdir(parents=True)
    (contentforge_lib / "audio-fit.js").write_text(
        """
export function scoreAudioFit(input) {
  const energyFit = input.visual?.energy === "high" && input.audio.bpm >= 120 ? 99 : null;
  return {
    available: true,
    advisoryOnly: true,
    publishAuthority: false,
    audioFitScore: input.audio.tags.includes("fit_check") ? (energyFit ? 92 : 88) : 31,
    reasons: [{ code: "tag_match", label: "Tag match", impact: 18, detail: "fit_check" }],
    warnings: input.audio.tags.includes("stale") ? [{ code: "audio_fit_stale_trend", label: "Stale", message: "stale" }] : [],
    components: { tagAffinity: 90, toneFit: 80, energyFit, trendFit: null },
    signals: { visualPacing: input.visual || {} }
  };
}
""",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "audio_catalog.json"
    catalog_path.write_text(json.dumps({
        "schema": "reference_factory.audio_catalog_export.v1",
        "items": [
            {
                "id": "aud_fit",
                "title": "Good Fit",
                "artistName": "DJ A",
                "platform": "instagram",
                "nativeAudioId": "ig_fit",
                "moodTags": ["fit_check"],
                "bestContentTypes": ["mirror_selfie"],
                "trendStatus": "rising",
                "bpm": 128,
            },
            {
                "id": "aud_bad",
                "title": "Bad Fit",
                "artistName": "DJ B",
                "platform": "instagram",
                "nativeAudioId": "ig_bad",
                "moodTags": ["stale"],
                "bestContentTypes": ["tutorial"],
                "trendStatus": "rising",
            },
        ],
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        cf.import_audio_catalog(catalog_path)
        result = cf.recommend_audio(platform="instagram", content_tags=["fit_check"], visual_signal={"energy": "high"}, limit=2)
        recs = result["recommendations"]

        assert result["visualSignal"] == {"energy": "high"}
        assert result["decision"]["primaryAudio"]["audioTitle"] == "Good Fit"
        assert result["decision"]["backupAudios"][0]["audioTitle"] == "Bad Fit"
        assert recs[0]["audioTitle"] == "Good Fit"
        assert recs[0]["audioFitScore"] == 92
        assert recs[0]["audioFitReasons"][0]["code"] == "tag_match"
        assert recs[0]["audioFitComponents"]["energyFit"] == 99
        assert "audio_fit:92" in recs[0]["rationale"]
        assert recs[1]["audioFitScore"] == 31
        assert recs[1]["audioFitWarnings"][0]["code"] == "audio_fit_stale_trend"
    finally:
        cf.close()


def test_audio_decision_prefers_resolved_instagram_over_unresolved_and_tiktok(tmp_path: Path):
    catalog_path = tmp_path / "audio_decision.json"
    catalog_path.write_text(json.dumps({
        "schema": "reference_factory.audio_catalog_export.v1",
        "items": [
            {
                "id": "ig_resolved",
                "title": "Resolved IG Winner",
                "artistName": "DJ A",
                "platform": "instagram",
                "nativeAudioId": "ig_resolved",
                "nativeAudioUrl": "https://instagram.com/reels/audio/ig_resolved",
                "moodTags": ["mirror", "glam"],
                "bestContentTypes": ["ofm_reels"],
                "trendStatus": "rising",
                "creatorFitScore": 86,
                "accountFitScore": 88,
                "fatigue": {"level": "low"},
            },
            {
                "id": "ig_unresolved",
                "title": "Instagram audio example_deadbeef",
                "platform": "instagram",
                "nativeAudioId": "example_deadbeef",
                "nativeAudioUrl": "https://instagram.com/p/example",
                "moodTags": ["mirror", "glam"],
                "bestContentTypes": ["ofm_reels"],
                "trendStatus": "rising",
                "creatorFitScore": 90,
            },
            {
                "id": "tt_signal",
                "title": "TikTok audio 12345",
                "platform": "tiktok",
                "nativeAudioId": "12345",
                "nativeAudioUrl": "https://www.tiktok.com/@creator/video/1",
                "moodTags": ["mirror", "glam"],
                "bestContentTypes": ["ofm_reels"],
                "trendStatus": "rising",
                "creatorFitScore": 92,
            },
        ],
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        cf.import_audio_memory(catalog_path)
        result = cf.recommend_audio(platform="instagram", content_tags=["mirror", "glam"], limit=3)
        decision = result["decision"]

        assert decision["primaryAudio"]["catalogAudioId"] == "ig_resolved"
        assert "resolved_instagram_native_audio" in decision["decisionReasons"]
        by_id = {item["catalogAudioId"]: item for item in result["recommendations"]}
        assert "unresolved_or_generic_title" in by_id["ig_unresolved"]["riskFlags"]
        assert "needs_ig_lookup" in by_id["tt_signal"]["riskFlags"]
    finally:
        cf.close()


def test_audio_decision_moves_high_fatigue_or_stale_audio_to_do_not_use(tmp_path: Path):
    catalog_path = tmp_path / "audio_decision_risks.json"
    catalog_path.write_text(json.dumps({
        "schema": "reference_factory.audio_catalog_export.v1",
        "items": [
            {
                "id": "safe",
                "title": "Safe Audio",
                "platform": "instagram",
                "nativeAudioId": "ig_safe",
                "nativeAudioUrl": "https://instagram.com/reels/audio/ig_safe",
                "moodTags": ["glam"],
                "bestContentTypes": ["ofm_reels"],
                "trendStatus": "current",
                "fatigue": {"level": "low"},
            },
            {
                "id": "tired",
                "title": "Tired Audio",
                "platform": "instagram",
                "nativeAudioId": "ig_tired",
                "nativeAudioUrl": "https://instagram.com/reels/audio/ig_tired",
                "moodTags": ["glam"],
                "bestContentTypes": ["ofm_reels"],
                "trendStatus": "stale",
                "fatigue": {"level": "high"},
            },
        ],
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        cf.import_audio_memory(catalog_path)
        result = cf.recommend_audio(platform="instagram", content_tags=["glam"], limit=2)
        decision = result["decision"]

        assert decision["primaryAudio"]["catalogAudioId"] == "safe"
        assert decision["doNotUseAudios"][0]["catalogAudioId"] == "tired"
        assert "stale_trend" in decision["doNotUseAudios"][0]["riskFlags"]
    finally:
        cf.close()


def test_audio_memory_v2_balanced_scoring_prefers_ofm_velocity_and_low_fatigue(tmp_path: Path):
    catalog_path = tmp_path / "audio_v2.json"
    catalog_path.write_text(json.dumps({
        "schema": "reference_factory.audio_catalog_export.v1",
        "items": [
            {
                "id": "ofm_fast",
                "title": "OFM Fast Riser",
                "platform": "tiktok",
                "nativeAudioId": "tt_fast",
                "nativeAudioUrl": "https://www.tiktok.com/music/fast",
                "moodTags": ["ofm_reels", "glam", "mirror"],
                "bestContentTypes": ["ig_reels", "fit_check"],
                "accountFit": ["onlyfans_ig_reels", "ig_1"],
                "trendStatus": "rising",
                "trendScore": 86,
                "velocityScore": 96,
                "creatorFitScore": 92,
                "accountFitScore": 88,
                "sourceConfidence": 0.9,
                "fatigue": {"level": "low", "fatigueScore": 10},
                "performanceSummary": {"postCount": 2, "performanceLift": 8},
                "trendSources": ["tiktok_creative_center", "reference_factory"],
                "resolved": True,
            },
            {
                "id": "generic_big",
                "title": "Generic Viral",
                "platform": "tiktok",
                "nativeAudioId": "tt_big",
                "moodTags": ["tutorial"],
                "bestContentTypes": ["explainer"],
                "trendStatus": "trending",
                "trendScore": 95,
                "velocityScore": 30,
                "usageCount": 9000000,
                "fatigue": {"level": "high", "fatigueScore": 90},
                "sourceConfidence": 0.8,
                "resolved": True,
            },
        ],
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        cf.import_audio_memory(catalog_path)
        result = cf.recommend_audio(platform="instagram", content_tags=["mirror", "fit_check"], account="ig_1", limit=2)
        first = result["recommendations"][0]
        assert first["catalogAudioId"] == "ofm_fast"
        assert first["platform"] == "tiktok"
        assert "matching native Instagram audio" in first["instruction"]
        assert first["scoreComponents"]["velocity"] == 96
        assert first["scoreComponents"]["creatorFit"] == 92
        assert first["scoreComponents"]["fatigueSafety"] == 90
        assert first["recommendationConfidence"] == "usable"
        assert "creator_fit" in first["rationale"]
    finally:
        cf.close()


def test_audio_catalog_recommendations_feed_threadsdash_audio_intent(tmp_path: Path):
    catalog_path = tmp_path / "audio_catalog.json"
    catalog_path.write_text(json.dumps({
        "schema": "reference_factory.audio_catalog_export.v1",
        "items": [
            {
                "id": "aud_1",
                "title": "Runway Pop",
                "artistName": "DJ A",
                "platform": "instagram",
                "nativeAudioId": "ig_1",
                "nativeAudioUrl": "https://instagram.com/audio/1",
                "moodTags": ["fit_check"],
                "bestContentTypes": ["v01_original"],
                "trendStatus": "rising",
                "safeUsageNotes": "native only",
            }
        ],
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        cf.import_audio_catalog(catalog_path)
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({}),),
        )
        cf.conn.commit()
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        intent = payload["drafts"][0]["metadata"]["campaign_factory"]["audio_intent"]

        assert intent["status"] == "recommended"
        assert intent["decision"]["primaryAudio"]["audio_title"] == "Runway Pop"
        assert intent["decision"]["decisionConfidence"] in {"usable", "strong"}
        assert intent["recommendations"][0]["audio_title"] == "Runway Pop"
        assert intent["recommendations"][0]["platform_audio_id"] == "ig_1"
        assert intent["recommendations"][0]["platform_url"] == "https://instagram.com/audio/1"
        assert intent["recommendations"][0]["freshness"] == "rising"
        assert source["id"]
    finally:
        cf.close()


def test_pipeline_audio_smoke_helpers_build_recommended_intent(tmp_path: Path):
    csv_path = write_smoke_audio_csv(tmp_path / "audio.csv")
    snapshot_path = write_smoke_audio_snapshot_csv(tmp_path / "audio_snapshot.csv")
    catalog_path = tmp_path / "audio_catalog.json"
    catalog_path.write_text(json.dumps({
        "schema": "reference_factory.audio_catalog_export.v1",
        "items": [
            {
                "id": "aud_smoke",
                "title": "Runway Pop",
                "artistName": "DJ A",
                "platform": "instagram",
                "nativeAudioId": "ig_runway_pop",
                "nativeAudioUrl": "https://instagram.com/audio/runway_pop",
                "moodTags": ["glam", "fit_check"],
                "bestContentTypes": ["regular_reel", "v01_original"],
                "accountFit": ["smoke_account"],
                "trendStatus": "rising",
                "usageCount": 120000,
                "safeUsageNotes": "Attach natively only",
            }
        ],
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        cf.import_audio_catalog(catalog_path)
        create_smoke_campaign_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_smoke", decision="approved")
        add_smoke_audit_report(cf)
        payload = build_draft_payloads(cf, campaign_slug="audio_smoke", user_id="smoke_user")
        intent = assert_smoke_draft_audio_intent(payload)
        performance = sync_smoke_performance(cf, draft_payload=payload, user_id="smoke_user")
        contentforge = assert_contentforge_contract_response(CONTENTFORGE_SMOKE_RESPONSE)

        assert csv_path.read_text(encoding="utf-8") == SMOKE_CSV
        assert snapshot_path.read_text(encoding="utf-8") == SMOKE_SNAPSHOT_CSV
        assert intent["status"] == "recommended"
        assert intent["recommendations"][0]["audio_title"] == "Runway Pop"
        assert contentforge["readinessSummary"]["uploadReady"] is True
        validate_performance_sync(performance)
        assert performance["inserted"] == 1
        assert performance["summary"]["leaderboards"]["audioRecommendations"][0]["audio"]["audioTitle"] == "Runway Pop"
    finally:
        cf.close()


def test_pipeline_full_smoke_mocked_generation_intake_preserves_lineage(tmp_path: Path):
    projects_root = tmp_path / "Projects"
    for repo in ["reel_factory", "contentforge", "reference_factory", "ThreadsDashboard"]:
        (projects_root / repo).mkdir(parents=True)

    result = _run_mocked_generation_intake_smoke(projects_root=projects_root, workspace=tmp_path / "workspace")

    assert result["ok"] is True
    checks = result["checks"]
    assert checks["lineagePreserved"] is True
    assert checks["promptScorePreserved"] is True
    assert checks["fallbackPreserved"] is True
    assert checks["variationGridPreserved"] is True
    assert result["finishedVideoIntake"]["draftFirst"] is True


def test_contentforge_smoke_contract_rejects_malformed_response():
    bad = dict(CONTENTFORGE_SMOKE_RESPONSE)
    bad["overallVerdict"] = "maybe"

    try:
        assert_contentforge_contract_response(bad)
    except AssertionError as exc:
        assert "unexpected ContentForge verdict" in str(exc)
    else:
        raise AssertionError("malformed ContentForge response passed smoke validation")


def test_make_batch_returns_compact_operator_summary(tmp_path: Path, monkeypatch):
    bank_path = tmp_path / "campaign_reference_bank.json"
    bank_path.write_text(json.dumps({
        "schema": "reference_factory.campaign_reference_bank.v1",
        "clusters": [
            {
                "clusterRank": 1,
                "clusterKey": "caption_led_visual::direct_response::question_hook",
                "label": "caption led visual / direct response / question hook",
                "visualFormat": "caption_led_visual",
                "hookType": "direct_response",
                "captionArchetype": "question_hook",
                "captionFormulas": [{"formula": "{direct question}?", "exampleCaptions": ["red or pink ?"]}],
                "suggestedVariantRecipes": ["v01_original", "v05_hflip"],
            }
        ],
    }))
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.import_reference_bank(bank_path)
        run_kwargs = {}

        def fake_run_reel(**kwargs):
            run_kwargs.update(kwargs)
            return {
                "returncode": 0,
                "runs": [{"renderJobId": "job_1"}],
                "elapsed_seconds": 1.23,
            }

        monkeypatch.setattr(cf, "run_reel_factory", fake_run_reel)
        monkeypatch.setattr(cf, "sync_reel_outputs", lambda **kwargs: {
            "synced": [{"id": "asset_1"}],
        })
        monkeypatch.setattr(contentforge_adapter, "audit_campaign", lambda *args, **kwargs: {
            "reports": [{"overallVerdict": "warn", "warnings": ["review"], "failedChecks": []}],
        })

        result = cf.make_batch(
            folder=folder,
            campaign_slug="batch",
            model_slug="model",
            variant_count=1,
            user_id=None,
            recipes=None,
        )
        assert result["import"]["importedCount"] == 1
        assert result["referenceSelection"]["clusterKey"] == "caption_led_visual::direct_response::question_hook"
        assert result["referenceSelection"]["recipes"] == ["v01_original", "v05_hflip"]
        assert result["prepare"]["preparedCount"] == 1
        assert result["run"]["runCount"] == 1
        assert result["sync"]["syncedCount"] == 1
        assert result["audit"]["reportCount"] == 1
        assert "reports" not in result["audit"]
        assert "runs" not in result["run"]
        assert run_kwargs["max_outputs_per_clip"] == 1
    finally:
        cf.close()


def test_finished_video_intake_uses_reference_pipeline_metadata(tmp_path: Path, monkeypatch):
    source = tmp_path / "mirror_selfie_finished.mp4"
    source.write_bytes(b"finished video")
    cf = make_factory(tmp_path)
    try:
        captured: dict[str, object] = {}
        monkeypatch.setattr(core_module, "probe_video_shape", lambda path: {"effectiveAspectRatio": 1080 / 1920})

        def fake_make_batch(**kwargs):
            captured.update(kwargs)
            return {
                "schema": "campaign_factory.make_batch.v1",
                "campaign": kwargs["campaign_slug"],
                "referenceSelection": {"clusterKey": kwargs["reference_pattern"]},
                "dryRunExport": {"dryRun": True},
            }

        monkeypatch.setattr(cf, "make_batch", fake_make_batch)

        result = cf.intake_finished_video(
            input_path=source,
            model_slug="model_a",
            platform="instagram",
            goal="reach",
            reference_pattern="auto",
            campaign_slug="daily_video",
            variant_count=3,
            recipes=["v01_original"],
        )

        staged_folder = Path(result["finishedVideoIntake"]["stagedFolder"])
        source_prompt = json.loads(str(captured["source_prompt"]))
        assert result["finishedVideoIntake"]["formatType"] == "mirror_selfie"
        assert captured["folder"] == staged_folder
        assert captured["output_format"] == "reel"
        assert captured["dry_run_export"] is True
        assert captured["variant_count"] == 3
        assert captured["recipes"] == ["v01_original"]
        assert source_prompt["strategy"]["distributionPriority"] == "instagram_reels_first"
        assert source_prompt["strategy"]["primaryMetric"] == "views_reach"
        assert source_prompt["strategy"]["humanReviewRequired"] is True
        assert source_prompt["strategy"]["nativeAudioRequired"] is True
        assert source_prompt["sourcePreflight"]["warnings"] == []
        assert source_prompt["generatedAssetLineage"]["schema"] == "campaign_factory.generated_asset_lineage.v1"
        assert source_prompt["generatedAssetLineage"]["source"]["formatType"] == "mirror_selfie"
    finally:
        cf.close()


def test_finished_video_intake_accepts_higgsfield_source_lineage(tmp_path: Path, monkeypatch):
    source = tmp_path / "generated_finished.mp4"
    source.write_bytes(b"finished video")
    lineage_path = tmp_path / "lineage.json"
    lineage_path.write_text(json.dumps({
        "schema": "campaign_factory.generated_asset_lineage.v1",
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
    }), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        captured: dict[str, object] = {}
        monkeypatch.setattr(core_module, "probe_video_shape", lambda path: {"effectiveAspectRatio": 1080 / 1920})

        def fake_make_batch(**kwargs):
            captured.update(kwargs)
            return {"schema": "campaign_factory.make_batch.v1", "campaign": kwargs["campaign_slug"]}

        monkeypatch.setattr(cf, "make_batch", fake_make_batch)

        result = cf.intake_finished_video(
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
        warnings = cf._finished_video_preflight({"effectiveAspectRatio": 828 / 1108})
        assert warnings[0]["code"] == "finished_video_not_reels_canvas"

        clean = cf._finished_video_preflight({"effectiveAspectRatio": 1080 / 1920})
        assert clean == []
    finally:
        cf.close()


def test_archive_inventory_report_requires_enough_clean_stacey_candidates(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        for index in range(3):
            (archive / f"stacey_{index}.mp4").write_bytes(f"video-{index}".encode("utf-8"))

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

        result = cf.archive_inventory_report(
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


def test_archive_inventory_report_blocks_when_inventory_is_short(tmp_path: Path, monkeypatch):
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

        result = cf.archive_inventory_report(
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


def test_archive_inventory_report_blocks_duplicates_and_corrupt_files(tmp_path: Path, monkeypatch):
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

        result = cf.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=2,
        )

        assert result["archiveVideosFound"] == 4
        assert result["duplicateSourceFingerprint"] == 1
        assert result["corruptedOrInvalid"] == 1
        assert result["cleanStaceyCandidates"] == 2
        blocked = {item["filename"]: item for item in result["items"] if item["status"] == "blocked"}
        assert blocked["stacey_dup_b.mp4"]["blockingReasons"] == ["duplicate_source_fingerprint"]
        assert "probe_failed" in blocked["stacey_corrupt.mp4"]["blockingReasons"]
        clean_items = [item for item in result["items"] if item["status"] == "clean_source_candidate"]
        assert all(item["audioStatus"] == "missing_needs_campaign_audio" for item in clean_items)
    finally:
        cf.close()


def test_archive_inventory_report_blocks_existing_campaign_duplicates(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        existing = archive / "stacey_existing.mp4"
        existing.write_bytes(b"existing")
        digest = core_module.sha256_file(existing)
        model = cf.upsert_model("stacey", "Stacey")
        campaign = cf.upsert_campaign("other_campaign", "stacey", platform="instagram")
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

        result = cf.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=1,
        )

        assert result["status"] == "blocked"
        assert result["duplicateContentHash"] == 1
        assert result["items"][0]["blockingReasons"] == ["duplicate_existing_campaign_asset"]
    finally:
        cf.close()


def test_archive_candidate_quality_report_ranks_clean_candidates_and_excludes_worst_crop(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        for name in ["good_vertical.mp4", "square_crop.mp4", "low_res.mp4"]:
            (archive / name).write_bytes(name.encode("utf-8"))

        def fake_probe(path: Path) -> dict[str, object]:
            if path.name == "square_crop.mp4":
                return {
                    "ok": True,
                    "width": 960,
                    "height": 960,
                    "effectiveWidth": 960,
                    "effectiveHeight": 960,
                    "effectiveAspectRatio": 1.0,
                    "durationSeconds": 5.0,
                    "bitrate": 5_000_000,
                    "videoCodec": "h264",
                    "audioPresent": False,
                }
            if path.name == "low_res.mp4":
                return {
                    "ok": True,
                    "width": 540,
                    "height": 960,
                    "effectiveWidth": 540,
                    "effectiveHeight": 960,
                    "effectiveAspectRatio": 540 / 960,
                    "durationSeconds": 5.0,
                    "bitrate": 2_000_000,
                    "videoCodec": "h264",
                    "audioPresent": False,
                }
            return {
                "ok": True,
                "width": 720,
                "height": 1280,
                "effectiveWidth": 720,
                "effectiveHeight": 1280,
                "effectiveAspectRatio": 720 / 1280,
                "durationSeconds": 5.0,
                "bitrate": 5_000_000,
                "videoCodec": "h264",
                "audioPresent": False,
            }

        monkeypatch.setattr(core_module, "probe_video_metadata", fake_probe)
        inventory = cf.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=2,
        )

        quality = cf.archive_candidate_quality_report(
            inventory_report_path=Path(inventory["reportPath"]),
            requested_count=2,
        )

        assert quality["schema"] == "campaign_factory.archive_candidate_quality_report.v1"
        assert quality["status"] == "ready_for_source_approval"
        selected_names = {
            item["filename"]
            for item in quality["items"]
            if item["recommendation"] == "selected_for_source_approval"
        }
        assert selected_names == {"good_vertical.mp4", "low_res.mp4"}
        square = next(item for item in quality["items"] if item["filename"] == "square_crop.mp4")
        assert square["estimatedCropSeverity"] == "severe"
        assert square["recommendation"] == "alternate"
        assert Path(quality["reportPath"]).exists()
    finally:
        cf.close()


def test_archive_candidate_quality_report_blocks_when_ranked_inventory_is_short(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "only.mp4").write_bytes(b"only")
        monkeypatch.setattr(
            core_module,
            "probe_video_metadata",
            lambda path: {
                "ok": True,
                "width": 720,
                "height": 1280,
                "effectiveWidth": 720,
                "effectiveHeight": 1280,
                "effectiveAspectRatio": 720 / 1280,
                "durationSeconds": 5.0,
                "bitrate": 5_000_000,
                "videoCodec": "h264",
                "audioPresent": False,
            },
        )
        inventory = cf.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=1,
        )

        quality = cf.archive_candidate_quality_report(
            inventory_report_path=Path(inventory["reportPath"]),
            requested_count=2,
        )

        assert quality["status"] == "blocked"
        assert quality["blockingReason"] == "insufficient_ranked_archive_inventory"
        assert quality["wouldProceedToRendering"] is False
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
        mirror = cf.finished_video_hooks("mirror_selfie", pattern, count=3)
        pov = cf.finished_video_hooks("pov", pattern, count=2)

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
        monkeypatch.setattr(core_module, "probe_video_shape", lambda path: {"effectiveAspectRatio": 1080 / 1920})

        def fake_make_batch(**kwargs):
            captured.update(kwargs)
            return {"schema": "campaign_factory.make_batch.v1", "campaign": kwargs["campaign_slug"]}

        monkeypatch.setattr(cf, "make_batch", fake_make_batch)
        result = cf.intake_finished_video(
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
        assert cf._finished_video_caption_band("mirror_selfie") == "auto"
        assert cf._finished_video_caption_band("pov") == "auto"
        assert cf._finished_video_caption_band("slideshow") == "center"
    finally:
        cf.close()


def test_finished_video_caption_font_prefers_instagram_condensed_for_reels(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        assert cf._finished_video_caption_font("mirror_selfie") == "Instagram Sans Condensed"
        assert cf._finished_video_caption_font("pov") == "Instagram Sans Condensed"
        assert cf._finished_video_caption_font("slideshow") == "Instagram Sans Condensed"
    finally:
        cf.close()


def test_creative_plan_create_status_and_finished_video_linkage(tmp_path: Path, monkeypatch):
    source = tmp_path / "selfie_finished.mp4"
    source.write_bytes(b"finished video")
    cf = make_factory(tmp_path)
    try:
        plan = cf.create_creative_plan(
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

        updated = cf.update_creative_plan_status(name="stacey_daily_001", status="prompts_ready")
        assert updated["status"] == "prompts_ready"

        captured: dict[str, object] = {}

        def fake_make_batch(**kwargs):
            captured.update(kwargs)
            return {"schema": "campaign_factory.make_batch.v1", "campaign": kwargs["campaign_slug"]}

        monkeypatch.setattr(cf, "make_batch", fake_make_batch)
        result = cf.intake_finished_video(
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
        assert cf.creative_plan_for_campaign("daily_video")["id"] == plan["id"]
    finally:
        cf.close()


def test_batch_summary_includes_daily_finished_video_counters(tmp_path: Path):
    folder = tmp_path / "finished"
    folder.mkdir()
    (folder / "selfie.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.import_folder(
            folder,
            campaign_slug="daily",
            model_slug="model_a",
            source_prompt=json.dumps({
                "schema": "campaign_factory.finished_video_intake.v1",
                "strategy": {"primaryMetric": "views_reach"},
            }),
        )
        summary = cf.batch_summary("daily")

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
        plan = cf.create_creative_plan(name="daily_plan", target_account="staceybennetx", linked_campaign="daily")
        cf.import_folder(
            folder,
            campaign_slug="daily",
            model_slug="model_a",
            source_prompt=json.dumps({
                "schema": "campaign_factory.finished_video_intake.v1",
                "creativePlanId": plan["id"],
                "creativePlanName": plan["name"],
                "generatedAssetLineage": {
                    "schema": "campaign_factory.generated_asset_lineage.v1",
                    "source": {"referenceId": "ref_1", "patternCardId": "pattern_1", "promptId": "prompt_1"},
                    "generation": {"tool": "manual_finished_video", "modelProfile": "model_a"},
                    "review": {"humanReviewRequired": True, "status": "draft"},
                },
            }),
        )
        summary = cf.batch_summary("daily")

        assert summary["creativePlan"]["id"] == plan["id"]
        assert summary["creativePlan"]["counts"]["generated_videos"] == 1
        assert summary["creativePlan"]["counts"]["references"] == 1
    finally:
        cf.close()


def test_sync_creative_plan_progress_counts_reference_prompt_exports(tmp_path: Path):
    prompt_export = tmp_path / "generated_video_prompts.json"
    cf = make_factory(tmp_path)
    try:
        plan = cf.create_creative_plan(name="daily_plan", target_account="staceybennetx", daily_base_video_target=4)
        prompt_export.write_text(json.dumps({
            "schema": "reference_factory.generated_video_prompts.v1",
            "creativePlanId": plan["id"],
            "items": [
                {
                    "imagePrompt": {
                        "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
                        "id": "image_prompt_1",
                        "creativePlanId": plan["id"],
                        "referenceId": "ref_1",
                        "sourcePatternId": "pattern_1",
                        "targetTool": "higgsfield_soul",
                    },
                    "klingPrompt": {
                        "schema": "reference_factory.kling_3_video_prompt.v1",
                        "id": "kling_prompt_1",
                        "creativePlanId": plan["id"],
                        "referenceId": "ref_1",
                        "sourcePatternId": "pattern_1",
                        "targetTool": "kling_3",
                    },
                },
                {
                    "imagePrompt": {
                        "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
                        "id": "image_prompt_2",
                        "creativePlanId": plan["id"],
                        "referenceId": "ref_2",
                        "sourcePatternId": "pattern_2",
                        "targetTool": "higgsfield_soul",
                    }
                },
            ],
        }), encoding="utf-8")

        result = cf.sync_creative_plan_progress(name="daily_plan", prompt_export_path=prompt_export)

        assert result["counts"] == {
            "references": 2,
            "analyses": 2,
            "image_prompts": 2,
            "video_prompts": 1,
        }
        assert result["plan"]["status"] == "prompts_ready"
        assert result["plan"]["counts"]["references"] == 2
        assert result["plan"]["counts"]["image_prompts"] == 2
        assert "Select 2 more references" in result["plan"]["next_actions"]
    finally:
        cf.close()


def test_make_batch_slideshow_format_registers_slideshow_asset(tmp_path: Path, monkeypatch):
    bank_path = tmp_path / "campaign_reference_bank.json"
    bank_path.write_text(json.dumps({
        "schema": "reference_factory.campaign_reference_bank.v1",
        "clusters": [
            {
                "clusterRank": 1,
                "clusterKey": "caption_led_visual::direct_response::question_hook",
                "label": "caption led visual / direct response / question hook",
                "visualFormat": "caption_led_visual",
                "hookType": "direct_response",
                "captionArchetype": "question_hook",
                "captionFormulas": [{"formula": "{direct question}?", "exampleCaptions": ["red or pink ?"]}],
                "suggestedVariantRecipes": ["v01_original", "v05_hflip"],
                "suggestedFormats": ["reel", "slideshow"],
            }
        ],
    }))
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.import_reference_bank(bank_path)

        def fake_run(cmd, cwd=None, text=None, capture_output=None, check=None):
            assert "--reference-pattern-id" in cmd
            assert cmd[cmd.index("--reference-pattern-id") + 1].startswith("refpat_")
            assert "--generation-id" in cmd
            assert cmd[cmd.index("--generation-id") + 1].startswith("slidegen_")
            out_dir = Path(cmd[cmd.index("--out-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            reel = out_dir / "slideshow_reel.mp4"
            reel.write_bytes(b"fake slideshow reel")
            (out_dir / "slideshow_manifest.json").write_text(json.dumps({
                "schema": "reel_factory.slideshow.v1",
                "reel_path": str(reel),
                "items": [{"source_hash": "src", "hook": "red or pink ?"}],
            }), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
        monkeypatch.setattr(contentforge_adapter, "audit_campaign", lambda *args, **kwargs: {"reports": []})

        result = cf.make_batch(
            folder=folder,
            campaign_slug="slides",
            model_slug="model",
            output_format="slideshow",
            variant_count=3,
            user_id=None,
        )

        rendered = cf.dashboard("slides")["rendered"]
        assert result["format"] == "slideshow"
        assert result["prepare"]["preparedCount"] == 1
        assert result["sync"]["syncedCount"] == 1
        assert rendered[0]["recipe"] == "slideshow_pack"
        assert rendered[0]["captionGeneration"]["format"] == "slideshow_pack"
        assert rendered[0]["captionGeneration"]["generationId"].startswith("slidegen_")
        assert rendered[0]["captionGeneration"]["referencePattern"]["id"].startswith("refpat_")
    finally:
        cf.close()


def test_make_batch_auto_mixed_folder_runs_reel_and_slideshow_groups(tmp_path: Path, monkeypatch):
    bank_path = tmp_path / "campaign_reference_bank.json"
    bank_path.write_text(json.dumps({
        "schema": "reference_factory.campaign_reference_bank.v1",
        "clusters": [
            {
                "clusterRank": 1,
                "clusterKey": "mixed_pattern",
                "label": "mixed pattern",
                "visualFormat": "mirror_grid",
                "hookType": "question",
                "captionArchetype": "question_hook",
                "captionFormulas": [{"formula": "{question}?", "exampleCaptions": ["which one wins ?"]}],
                "suggestedVariantRecipes": ["v01_original"],
                "suggestedFormats": ["reel", "slideshow"],
            }
        ],
    }))
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    (folder / "b.jpg").write_bytes(b"image")
    cf = make_factory(tmp_path)
    try:
        cf.import_reference_bank(bank_path)

        monkeypatch.setattr(cf, "run_reel_factory", lambda **kwargs: {
            "returncode": 0,
            "runs": [{"renderJobId": "job_1"}],
            "elapsed_seconds": 1.23,
        })
        monkeypatch.setattr(cf, "sync_reel_outputs", lambda **kwargs: {
            "synced": [{"id": "asset_1"}],
        })

        def fake_run(cmd, cwd=None, text=None, capture_output=None, check=None):
            assert "--reference-pattern-id" in cmd
            assert "--generation-id" in cmd
            media_dir = Path(cmd[cmd.index("--media-dir") + 1])
            assert all(path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic"} for path in media_dir.iterdir())
            out_dir = Path(cmd[cmd.index("--out-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            reel = out_dir / "slideshow_reel.mp4"
            reel.write_bytes(b"fake slideshow reel")
            (out_dir / "slideshow_manifest.json").write_text(json.dumps({
                "schema": "reel_factory.slideshow.v1",
                "reel_path": str(reel),
                "items": [{"source_hash": "src", "hook": "which one wins ?"}],
            }), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
        monkeypatch.setattr(contentforge_adapter, "audit_campaign", lambda *args, **kwargs: {"reports": []})

        result = cf.make_batch(
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


def test_run_reel_factory_targets_only_campaign_clips(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    (folder / "b.mp4").write_bytes(b"video b")
    cf = make_factory(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        cf.prepare_reel_inputs(campaign_slug="may", hooks=["hook"], recipes=["v01_original"], caption_color="auto")
        result = cf.run_reel_factory(campaign_slug="may", workers=2)
        assert result["returncode"] == 0
        assert len(calls) == 2
        assert all("--only-clip" in call for call in calls)
        assert all("v01_original" in call for call in calls)
        assert all(call[call.index("--band") + 1] == "auto" for call in calls)
        assert all(call[call.index("--color") + 1] == "light" for call in calls)
        assert all(call[call.index("--style") + 1] == "ig" for call in calls)
        assert all(call[call.index("--font") + 1] == "Instagram Sans Condensed" for call in calls)
        assert all("--phone-finalize" in call for call in calls)
        assert calls[0][calls[0].index("--only-clip") + 1] == "clip_001"
        assert calls[1][calls[1].index("--only-clip") + 1] == "clip_002"
    finally:
        cf.close()


def test_run_reel_factory_can_cap_outputs_per_clip(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    cf = make_factory(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        cf.prepare_reel_inputs(campaign_slug="may", hooks=["h1", "h2"], recipes=None, caption_color="auto")
        result = cf.run_reel_factory(campaign_slug="may", workers=1, max_outputs_per_clip=4)
        assert result["returncode"] == 0
        assert "--per-clip" in calls[0]
        assert calls[0][calls[0].index("--per-clip") + 1] == "4"
    finally:
        cf.close()


def test_run_reel_factory_skips_rendered_jobs_by_default(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    (folder / "b.mp4").write_bytes(b"video b")
    cf = make_factory(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        cf.prepare_reel_inputs(campaign_slug="may", hooks=["hook"], recipes=["v01_original"], caption_color="auto")
        first = cf.conn.execute("SELECT id FROM render_jobs ORDER BY reel_clip_stem LIMIT 1").fetchone()["id"]
        cf.conn.execute("UPDATE render_jobs SET status = 'rendered' WHERE id = ?", (first,))
        cf.conn.commit()
        result = cf.run_reel_factory(campaign_slug="may", workers=2)
        assert result["returncode"] == 0
        assert len(calls) == 1
        assert calls[0][calls[0].index("--only-clip") + 1] == "clip_002"
    finally:
        cf.close()


def test_run_reel_factory_dry_run_keeps_prepared_status(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    cf = make_factory(tmp_path)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        job = cf.prepare_reel_inputs(campaign_slug="may", hooks=["hook"])["prepared"][0]
        result = cf.run_reel_factory(campaign_slug="may", dry_run=True)
        assert result["returncode"] == 0
        status = cf.conn.execute("SELECT status FROM render_jobs WHERE id = ?", (job["id"],)).fetchone()["status"]
        assert status == "prepared"
    finally:
        cf.close()


def test_sync_reel_outputs_reads_manifest_and_copies_rendered_asset(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        job = cf.prepare_reel_inputs(campaign_slug="may", hooks=["caption"], recipes=["v01_original"])["prepared"][0]
        sidecar = cf.settings.reel_factory_root / "01_captions" / f"{job['reel_clip_stem']}.json"
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        data["generation"] = {
            "generation_id": "capgen_test",
            "model": "fake",
            "backend": "ollama",
            "prompt_hash": "prompt_hash",
            "caption_hashes": ["caption_hash_1"],
            "quality": [{"captionHash": "caption_hash_1", "qualityScore": 95, "warnings": []}],
        }
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        out_dir = cf.settings.reel_factory_root / "02_processed" / job["reel_clip_stem"]
        out_dir.mkdir(parents=True)
        out = out_dir / f"{job['reel_clip_stem']}_h00_v01_original_9x16_light_deadbeef.mp4"
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
            ("job", job["reel_clip_stem"], "v01_original", json.dumps({"_target_ratio": "9:16"}), "caption", str(out), "draft", "ok", 1),
        )
        conn.commit()
        conn.close()
        result = cf.sync_reel_outputs(campaign_slug="may")
        assert len(result["synced"]) == 1
        copied = Path(result["synced"][0]["campaign_path"])
        assert copied.exists()
        assert "02_rendered" in str(copied)
        assert result["synced"][0]["caption_generation_json"]
        dashboard_asset = cf.dashboard("may")["rendered"][0]
        assert dashboard_asset["captionGeneration"]["generationId"] == "capgen_test"
        assert dashboard_asset["captionHash"]
        assert dashboard_asset["captionOutcomeContext"]["caption_hash"] == dashboard_asset["captionHash"]
        assert dashboard_asset["captionOutcomeContext"]["captionPlacementPolicy"] == "focal_safe_v1"
        assert dashboard_asset["captionOutcomeContext"]["captionPlacementDecision"]["status"] == "pending"
        assert dashboard_asset["captionGeneration"]["instagramPostCaption"]["instagram_post_caption"]
        assert dashboard_asset["captionGeneration"]["audioIntent"]["status"] in {"attached", "missing"}
    finally:
        cf.close()


def add_rendered_asset(cf: CampaignFactory, tmp_path: Path, *, campaign_slug: str = "may", filename: str = "ok.mp4") -> tuple[dict, Path]:
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf.import_folder(folder, campaign_slug=campaign_slug, model_slug="model")
    source = cf.assets_for_campaign(cf.campaign_by_slug(campaign_slug)["id"])[0]
    rendered_path = tmp_path / filename
    rendered_path.write_bytes(b"rendered")
    now = "2026-01-01T00:00:00+00:00"
    caption_context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": "caption_hash_1",
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
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
         caption_generation_json, created_at, updated_at)
        VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, ?, 'caption', 'caption_hash_1', ?, 'v01_original', 'pending', 'draft', ?, ?, ?)
        """,
        (
            source["campaign_id"],
            source["id"],
            str(rendered_path),
            str(rendered_path),
            filename,
            json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
            json.dumps({
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                }
            }),
            now,
            now,
        ),
    )
    cf.conn.commit()
    return source, rendered_path


def threadsdash_campaign_factory_metadata(
    source: dict,
    *,
    rendered_asset_id: str = "asset_1",
    content_hash: str = "hash_1",
    caption_hash: str = "caption_hash_1",
    recipe: str = "v01_original",
    context: dict | None = None,
) -> dict:
    context = context or {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": caption_hash,
        "caption_text": "caption",
        "caption_bank": "test_bank",
        "caption_banks": ["test_bank"],
        "creator_mix": "Test",
        "render_recipe": recipe,
    }
    return {
        "campaign_id": "may",
        "source_asset_id": source["id"],
        "rendered_asset_id": rendered_asset_id,
        "asset_id": rendered_asset_id,
        "asset_state": "exportable",
        "platform_state": "platform_draft_validated",
        "content_hash": content_hash,
        "content_fingerprint": content_hash,
        "source_content_hash": source["content_hash"],
        "caption_hash": caption_hash,
        "recipe": recipe,
        "captionOutcomeContext": context,
        "caption_outcome_context": context,
        "publishability_failure_reasons": [],
        "quarantined": False,
        "handoff_manifest": {
            "manifest_version": 1,
            "asset_id": rendered_asset_id,
            "render_file_id": "render_file_test",
            "content_fingerprint": content_hash,
            "caption_hash": caption_hash,
            "captionOutcomeContext": context,
            "visual_verification_id": "visual_verification_test",
            "caption_verification_id": "caption_verification_test",
            "audio_id": "audio_test",
            "distribution_plan_id": "dist_test",
            "exported_by_system": "campaign_factory",
            "exported_at": "2026-01-02T00:00:00+00:00",
        },
    }


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
        return cf._distribution_plan_payload(dict(existing))
    return cf.create_distribution_plan(
        rendered_asset_id,
        instagram_account_id=instagram_account_id,
        planned_window_start=planned_window_start,
        planned_window_end=planned_window_end,
    )


def test_mass_production_readiness_report_flags_blockers(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()

        report = build_mass_production_readiness_report(cf, campaign_id="may", days=7)

        assert report["schema"] == "campaign_factory.mass_production_readiness_report.v1"
        assert report["counts"]["approvedAssets"] == 1
        assert report["counts"]["missingCanonicalIds"] == 1
        assert report["counts"]["missingLineage"] == 1
        assert report["counts"]["missingAccountAssignment"] == 1
        assert report["schedule"]["scheduleGaps"]["pilot"]["gap"] == 105
        assert report["readinessScore"] == "NOT_READY"
        assert any(item["code"] == "missing_account_assignment" for item in report["blockerRanking"]["preventsProduction"])
        assert any(item["code"] == "missing_canonical_ids" for item in report["blockerRanking"]["risksLosingTracking"])
        assert "# Mass Production Readiness: may" in report["markdownSummary"]
    finally:
        cf.close()


def test_mass_production_readiness_report_can_mark_pilot_ready(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, rendered_path = add_rendered_asset(cf, tmp_path)
        cf.ensure_graph_node(
            "rendered_asset",
            local_table="rendered_assets",
            local_id="asset_1",
            payload={"filename": rendered_path.name},
            commit=True,
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved', audit_status = 'approved_candidate' WHERE id = 'asset_1'"
        )
        cf.conn.execute(
            "UPDATE source_assets SET source_prompt = ? WHERE id = ?",
            (
                json.dumps({
                    "generatedAssetLineage": {
                        "schema": "pipeline.generated_asset_lineage.v1",
                        "source": {"referenceId": "ref_couch"},
                        "generation": {"system": "reel_factory"},
                        "quality": {"contentFingerprint": "fingerprint_couch"},
                    }
                }),
                source["id"],
            ),
        )
        start = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(second=0, microsecond=0)
        for day in range(7):
            for account_idx in range(5):
                account = f"stacey_{account_idx + 1}"
                base = start + timedelta(days=day)
                for slot_idx, surface in enumerate(("regular_reel", "trial_reel", "trial_reel")):
                    slot = base + timedelta(hours=slot_idx * 3)
                    cf.create_distribution_plan(
                        "asset_1",
                        surface=surface,
                        instagram_account_id=account,
                        planned_window_start=slot.isoformat(),
                        planned_window_end=(slot + timedelta(minutes=30)).isoformat(),
                    )

        report = build_mass_production_readiness_report(
            cf,
            campaign_id="may",
            days=7,
            threadsdash_readiness={
                "checked": True,
                "liveExportAllowed": True,
                "blockingReasons": [],
                "warnings": [],
            },
        )

        assert report["counts"]["approvedAssets"] == 1
        assert report["counts"]["missingCanonicalIds"] == 0
        assert report["counts"]["missingLineage"] == 0
        assert report["counts"]["missingAccountAssignment"] == 0
        assert report["schedule"]["scheduledMainTrialSlots"] == 105
        assert report["schedule"]["scheduleGaps"]["pilot"]["gap"] == 0
        assert report["readinessScore"] == "PILOT_READY"
    finally:
        cf.close()


def test_mass_production_readiness_report_detects_duplicate_content_risk(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, rendered_path = add_rendered_asset(cf, tmp_path)
        second_path = tmp_path / "second.mp4"
        second_path.write_bytes(b"rendered-2")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, caption_generation_json, created_at, updated_at)
            VALUES ('asset_2', ?, ?, 'hash_2', ?, ?, 'second.mp4', 'caption 2', 'v02', 'pending', 'approved', ?, ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                str(second_path),
                str(second_path),
                json.dumps({
                    "audioIntent": {"status": "not_required"},
                    "generatedAssetLineage": {
                        "source": {"referenceId": "same_ref"},
                        "quality": {"contentFingerprint": "same_fp"},
                    },
                }),
                now,
                now,
            ),
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved', caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps({
                    "audioIntent": {"status": "not_required"},
                    "generatedAssetLineage": {
                        "source": {"referenceId": "same_ref"},
                        "quality": {"contentFingerprint": "same_fp"},
                    },
                }),
            ),
        )
        cf.conn.commit()

        report = build_mass_production_readiness_report(cf, campaign_id="may", days=7)

        assert report["duplicateRisk"]["byContentFingerprint"] == [
            {"key": "same_fp", "count": 2, "renderedAssetIds": ["asset_1", "asset_2"]}
        ]
        assert report["duplicateRisk"]["bySourceReferenceOrFamily"] == [
            {"key": "same_ref", "count": 2, "renderedAssetIds": ["asset_1", "asset_2"]}
        ]
        assert any(item["code"] == "content_fingerprint_reuse" for item in report["blockerRanking"]["risksDuplicatePosting"])
    finally:
        cf.close()


def test_mass_production_readiness_report_blocks_external_posting_ledger_state(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        ledger = cf.settings.reel_factory_root / "manifest.sqlite"
        conn = sqlite3.connect(ledger)
        conn.execute(
            """
            CREATE TABLE posting_slots (
                posting_slot_id TEXT PRIMARY KEY,
                account_id TEXT,
                account_handle TEXT,
                campaign_id TEXT,
                date TEXT,
                slot_type TEXT,
                post_status TEXT,
                content_fingerprint TEXT,
                rendered_output_path TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO posting_slots
            (posting_slot_id, account_id, account_handle, campaign_id, date, slot_type, post_status, content_fingerprint, rendered_output_path)
            VALUES ('slot_1', 'stacey_1', 'stacey_1', 'may', '2026-06-03', 'main', 'approved', 'fp_1', '/tmp/out.mp4')
            """
        )
        conn.commit()
        conn.close()

        report = build_mass_production_readiness_report(cf, campaign_id="may", days=7)

        assert report["externalPostingLedgerAudit"]["matchingSlotCount"] == 1
        assert report["externalPostingLedgerAudit"]["requiresMigrationToCampaignFactory"] is True
        assert report["readinessScore"] == "NOT_READY"
        assert any(
            item["code"] == "external_schedule_state_not_canonical"
            for item in report["blockerRanking"]["preventsProduction"]
        )
        assert any(
            "posting_ledger" in reason
            for reason in report["scaleReadiness"]["pilot5Accounts"]["blockingReasons"]
        )
    finally:
        cf.close()


def test_reel_ledger_promotion_dry_run_writes_nothing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        rendered_path = tmp_path / "ready.mp4"
        rendered_path.write_bytes(b"ready rendered bytes")
        campaign = cf.upsert_campaign("may", "model")
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_ready",
            campaign_id=campaign["slug"],
            rendered_output_path=rendered_path,
            content_fingerprint="fp_ready",
            lineage={"schema": "campaign_factory.generated_asset_lineage.v1", "source": {"referenceId": "ref_ready"}},
            audio_track_id="audio_1",
            post_status="approved",
        )

        preview = promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
        )

        assert preview["apply"] is False
        assert preview["summary"]["rowsToCreate"] == 1
        assert preview["summary"]["rowsToUpdate"] == 0
        assert preview["blocked"] == []
        assert preview["conflicts"] == []
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"] == 0
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM distribution_plans").fetchone()["c"] == 0
    finally:
        cf.close()


def test_reel_ledger_promotion_apply_is_idempotent_and_readiness_sees_distribution(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        rendered_path = tmp_path / "ready.mp4"
        rendered_path.write_bytes(b"ready rendered bytes")
        campaign = cf.upsert_campaign("may", "model")
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_ready",
            campaign_id=campaign["slug"],
            account_id="stacey_1",
            account_handle="stacey_1",
            rendered_output_path=rendered_path,
            content_fingerprint="fp_ready",
            lineage={"schema": "campaign_factory.generated_asset_lineage.v1", "source": {"referenceId": "ref_ready"}},
            audio_track_id="audio_1",
            post_status="approved",
            date=(datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat(),
        )

        applied = promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
            apply=True,
        )
        second = promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
            apply=True,
        )
        report = build_mass_production_readiness_report(cf, campaign_id="may", days=7)

        assert applied["applied"] is True
        assert second["summary"]["rowsToCreate"] == 0
        assert second["summary"]["rowsToUpdate"] == 1
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"] == 1
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM asset_account_assignments").fetchone()["c"] == 1
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM distribution_plans").fetchone()["c"] == 1
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM content_graph_nodes WHERE external_system = 'reel_factory.posting_ledger'").fetchone()["c"] == 1
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM activity_events WHERE event_type = 'reel_ledger_promoted'").fetchone()["c"] >= 1
        assert report["schedule"]["scheduledMainTrialSlots"] == 1
        assert report["externalPostingLedgerAudit"]["matchingSlotCount"] == 0
        assert report["externalPostingLedgerAudit"]["promotedSlotCount"] == 1
        assert report["externalPostingLedgerAudit"]["requiresMigrationToCampaignFactory"] is False
    finally:
        cf.close()


def test_reel_ledger_promotion_copies_caption_outcome_context_to_render_plan_and_export(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        rendered_path = tmp_path / "caption_outcome.mp4"
        rendered_path.write_bytes(b"caption outcome bytes")
        campaign = cf.upsert_campaign("may", "lola")
        caption_lineage = {
            "schema": "reel_factory.caption_lineage.v1",
            "captionHash": "caption_hash_rendered",
            "rawCaptionText": "caption",
            "sourceBanks": ["question_bank"],
            "selectedBanks": ["question_bank"],
            "selectedMix": "Lola",
            "sourceClip": "clip_010",
            "lengthClass": "very_short",
            "formatClass": "single_line",
            "frameType": "mirror_fullbody",
            "captionFitVersion": "v1",
            "suitabilityDecision": "allowed",
            "suitabilityReason": "very_short static caption allowed for mirror_fullbody",
        }
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_caption_outcome",
            campaign_id=campaign["slug"],
            account_id="lola_1",
            account_handle="lola_1",
            rendered_output_path=rendered_path,
            content_fingerprint="fp_caption_outcome",
            lineage={
                "schema": "reel_factory.render_lineage.v1",
                "sourceClip": "clip_010",
                "captionHash": "caption_hash_rendered",
                "captionBank": caption_lineage,
                "recipe": "v09_caption_bg",
            },
            audio_track_id="audio_1",
            post_status="approved",
            date="2026-06-05",
        )

        promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
            apply=True,
        )

        asset = cf.conn.execute("SELECT * FROM rendered_assets WHERE content_hash = 'fp_caption_outcome'").fetchone()
        plan = cf.conn.execute("SELECT * FROM distribution_plans WHERE rendered_asset_id = ?", (asset["id"],)).fetchone()
        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1", schedule_mode="preview")
        draft = payload["drafts"][0]
        metadata = draft["metadata"]["campaign_factory"]

        assert asset["caption_hash"] == "caption_hash_rendered"
        assert asset["caption_bank"] == "question_bank"
        assert asset["creator_mix"] == "Lola"
        assert asset["creator_model"] == "lola"
        assert asset["frame_type"] == "mirror_fullbody"
        assert asset["length_class"] == "very_short"
        assert asset["format_class"] == "single_line"
        assert asset["caption_fit_version"] == "v1"
        assert asset["source_clip"] == "clip_010"
        assert json.loads(asset["caption_outcome_context_json"])["suitability_decision"] == "allowed"
        assert plan["caption_hash"] == "caption_hash_rendered"
        assert plan["caption_bank"] == "question_bank"
        assert json.loads(plan["caption_outcome_context_json"])["rendered_output"] == str(rendered_path.resolve())
        assert draft["captionHash"] == "caption_hash_rendered"
        assert draft["captionOutcomeContext"]["creator_mix"] == "Lola"
        assert metadata["captionOutcomeContext"]["caption_fit_version"] == "v1"
        assert metadata["caption_outcome_context"]["caption_fit_version"] == "v1"
    finally:
        cf.close()


def test_reel_ledger_promotion_loads_caption_context_from_render_sidecar(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        rendered_path = tmp_path / "sidecar_caption_outcome.mp4"
        rendered_path.write_bytes(b"caption outcome sidecar bytes")
        caption_sidecar = {
            "schema": "reel_factory.caption_lineage.v1",
            "captionHash": "caption_hash_sidecar",
            "rawCaptionText": "caption from sidecar",
            "selectedBanks": ["girl_next_door"],
            "selectedMix": "Stacey",
            "sourceClip": "clip_011",
            "lengthClass": "short",
            "formatClass": "single_line",
            "frameType": "closeup",
            "captionFitVersion": "v1",
            "captionOutcomeContext": {
                "schema": "campaign_factory.caption_outcome_context.v1",
                "caption_hash": "caption_hash_sidecar",
                "caption_text": "caption from sidecar",
                "caption_bank": "girl_next_door",
                "caption_banks": ["girl_next_door"],
                "creator_mix": "Stacey",
                "creator_model": None,
                "frame_type": "closeup",
                "length_class": "short",
                "format_class": "single_line",
                "caption_fit_version": "v1",
                "render_recipe": "v00_passthrough",
                "source_clip": "clip_011",
                "rendered_output": str(rendered_path.resolve()),
            },
        }
        rendered_path.with_suffix(rendered_path.suffix + ".caption_lineage.json").write_text(
            json.dumps(caption_sidecar),
            encoding="utf-8",
        )
        campaign = cf.upsert_campaign("may", "stacey")
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_caption_sidecar",
            campaign_id=campaign["slug"],
            rendered_output_path=rendered_path,
            content_fingerprint="fp_caption_sidecar",
            lineage={"schema": "campaign_factory.generated_asset_lineage.v1", "render": {"renderJobKey": "job_1"}},
            audio_track_id=None,
            post_status="ready_for_review",
            date="2026-06-05",
        )

        preview = promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
        )

        assert preview["blocked"] == []
        assert preview["summary"]["rowsToCreate"] == 1
        context = preview["creates"][0]["captionOutcomeContext"]
        assert context["caption_hash"] == "caption_hash_sidecar"
        assert context["caption_bank"] == "girl_next_door"
        assert context["creator_mix"] == "Stacey"
    finally:
        cf.close()


def test_reel_ledger_promotion_blocks_duplicate_missing_lineage_and_audio(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("may", "model")
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        third = tmp_path / "third.mp4"
        for path in (first, second, third):
            path.write_bytes(path.name.encode("utf-8"))
        lineage = {"schema": "campaign_factory.generated_asset_lineage.v1", "source": {"referenceId": "ref"}}
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_dup_1",
            campaign_id=campaign["slug"],
            rendered_output_path=first,
            content_fingerprint="same_fp",
            lineage=lineage,
            audio_track_id="audio_1",
            post_status="approved",
        )
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_dup_2",
            campaign_id=campaign["slug"],
            rendered_output_path=second,
            content_fingerprint="same_fp",
            lineage=lineage,
            audio_track_id="audio_2",
            post_status="approved",
            slot_type="trial_1",
        )
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_no_lineage",
            campaign_id=campaign["slug"],
            rendered_output_path=third,
            content_fingerprint="third_fp",
            lineage={},
            audio_track_id="audio_3",
            post_status="approved",
            slot_type="trial_2",
        )
        missing_audio = tmp_path / "missing_audio.mp4"
        missing_audio.write_bytes(b"missing audio")
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_no_audio",
            campaign_id=campaign["slug"],
            rendered_output_path=missing_audio,
            content_fingerprint="audio_fp",
            lineage=lineage,
            audio_track_id=None,
            manual_audio_needed=True,
            post_status="approved",
            account_id="stacey_2",
            account_handle="stacey_2",
        )

        preview = promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
        )
        applied = promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
            apply=True,
        )

        assert preview["summary"]["duplicateFingerprintRiskCount"] == 2
        assert preview["summary"]["missingLineageCount"] == 1
        assert preview["summary"]["missingAudioCount"] == 1
        assert {item["reason"] for item in preview["conflicts"]} == {"duplicate_content_fingerprint"}
        assert {"missing_lineage", "missing_audio"} <= {item["reason"] for item in preview["blocked"]}
        assert applied["applyBlocked"] is True
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"] == 0
    finally:
        cf.close()


def test_reel_ledger_promotion_marks_posted_without_proof_unverified(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        rendered_path = tmp_path / "posted.mp4"
        rendered_path.write_bytes(b"posted rendered bytes")
        campaign = cf.upsert_campaign("may", "model")
        _write_reel_posting_slot(
            cf,
            posting_slot_id="slot_posted",
            campaign_id=campaign["slug"],
            rendered_output_path=rendered_path,
            content_fingerprint="fp_posted",
            lineage={"schema": "campaign_factory.generated_asset_lineage.v1", "source": {"referenceId": "ref_posted"}},
            audio_track_id="audio_1",
            post_status="posted",
        )

        promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
            apply=True,
        )
        asset = cf.conn.execute("SELECT * FROM rendered_assets").fetchone()
        caption_generation = json.loads(asset["caption_generation_json"])

        assert caption_generation["reelLedger"]["status"]["promotedPostState"] == "unverified_platform_post"
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM performance_snapshots").fetchone()["c"] == 0
    finally:
        cf.close()


def test_reel_ledger_promotion_reports_account_day_quota_issue(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("may", "model")
        lineage = {"schema": "campaign_factory.generated_asset_lineage.v1", "source": {"referenceId": "ref"}}
        for idx in range(4):
            rendered_path = tmp_path / f"quota_{idx}.mp4"
            rendered_path.write_bytes(f"quota {idx}".encode("utf-8"))
            _write_reel_posting_slot(
                cf,
                posting_slot_id=f"slot_quota_{idx}",
                campaign_id=campaign["slug"],
                rendered_output_path=rendered_path,
                content_fingerprint=f"fp_quota_{idx}",
                lineage=lineage,
                audio_track_id=f"audio_{idx}",
                post_status="approved",
                account_id="stacey_1",
                account_handle="stacey_1",
                slot_type=("main" if idx == 0 else f"trial_{idx}"),
                date="2026-06-05",
            )

        preview = promote_reel_ledger(
            cf,
            campaign_id="may",
            reel_factory_root=cf.settings.reel_factory_root,
        )

        assert preview["summary"]["accountDayQuotaIssueCount"] == 4
        assert {item["reason"] for item in preview["conflicts"]} == {"account_day_quota_exceeded"}
    finally:
        cf.close()


def _write_reel_posting_slot(
    cf: CampaignFactory,
    *,
    posting_slot_id: str,
    campaign_id: str,
    rendered_output_path: Path,
    content_fingerprint: str,
    lineage: dict,
    audio_track_id: str | None,
    post_status: str,
    account_id: str = "stacey_1",
    account_handle: str = "stacey_1",
    slot_type: str = "main",
    date: str = "2026-06-05",
    manual_audio_needed: bool = False,
) -> None:
    db_path = cf.settings.reel_factory_root / "manifest.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posting_slots (
            posting_slot_id TEXT PRIMARY KEY,
            account_id TEXT,
            account_handle TEXT,
            platform TEXT,
            campaign_id TEXT,
            date TEXT,
            slot_type TEXT,
            planned_slot_time TEXT,
            rendered_output_path TEXT,
            content_fingerprint TEXT,
            caption TEXT,
            audio_track_id TEXT,
            audio_source TEXT,
            audio_selected_reason TEXT,
            manual_audio_needed INTEGER DEFAULT 0,
            lineage_path TEXT,
            lineage_json TEXT,
            post_status TEXT,
            review_status TEXT,
            post_url TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO posting_slots
        (posting_slot_id, account_id, account_handle, platform, campaign_id, date, slot_type,
         planned_slot_time, rendered_output_path, content_fingerprint, caption, audio_track_id,
         audio_source, audio_selected_reason, manual_audio_needed, lineage_json, post_status, review_status)
        VALUES (?, ?, ?, 'ig', ?, ?, ?, '10:00', ?, ?, 'caption', ?, 'native_platform_audio',
                'test selection', ?, ?, ?, 'approved')
        """,
        (
            posting_slot_id,
            account_id,
            account_handle,
            campaign_id,
            date,
            slot_type,
            str(rendered_output_path),
            content_fingerprint,
            audio_track_id,
            1 if manual_audio_needed else 0,
            json.dumps(lineage),
            post_status,
        ),
    )
    conn.commit()
    conn.close()


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
    asset = cf.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)).fetchone()
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
        },
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


def test_publishability_blocks_shouty_live_burned_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": "bad_caption_hash",
            "caption_text": "GOING LIVE TONIGHT!!!",
            "caption_bank": "test_bank",
            "caption_banks": ["test_bank"],
            "creator_mix": "Test",
            "render_recipe": "v01_original",
            "captionPlacementPolicy": "focal_safe_v1",
            "captionPlacementDecision": {
                "status": "passed",
                "selectedLane": "center",
                "reason": "test fixture placement passed",
            },
            "instagram_post_caption": "simple today",
            "instagram_post_caption_hash": "post_hash",
            "burned_caption_text": "GOING LIVE TONIGHT!!!",
            "burned_caption_hash": "bad_caption_hash",
        }
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption = ?,
                caption_hash = ?,
                caption_outcome_context_json = ?,
                review_state = 'approved',
                audit_status = 'approved_candidate'
            WHERE id = 'asset_1'
            """,
            ("GOING LIVE TONIGHT!!!", "bad_caption_hash", json.dumps(context, ensure_ascii=False, sort_keys=True)),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id="asset_1")

        publishability = cf.explain_publishability("asset_1")

        assert publishability["burnedCaptionQualityPassed"] is False
        assert "burned_caption_quality_failed" in publishability["publishability_failure_reasons"]
        assert "caption_placement_qc_failed" not in publishability["publishability_failure_reasons"]
    finally:
        cf.close()


def test_contentforge_http_audit_records_pass_result(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    def fake_similarity(base_url, *, source, target_file=None, audit_profile=None, layers):
        assert base_url == "http://contentforge.test"
        assert source.startswith("campaign_factory_source_")
        assert target_file.startswith("campaign_factory_variant_")
        assert audit_profile == "campaign_factory_v1"
        assert "pdq" in layers
        return {
            "auditProfile": audit_profile,
            "targetFile": target_file,
            "layers": {"pdq": {"stats": {"avgDistance": 90}}},
            "verdicts": {"pdq": "pass"},
            "verdictCodes": {"pdq": "pdq_pass"},
            "overallVerdict": "pass",
            "readinessSummary": {
                "summaryText": "Upload-ready candidate with no blocking audit issues.",
                "uploadReady": True,
                "blockingReasons": [],
                "warnings": [],
                "blockingCodes": [],
                "warningCodes": [],
                "topWarnings": [],
                "recommendedAction": "approve_candidate",
            },
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may", contentforge_base_url="http://contentforge.test")
        report = result["reports"][0]
        assert report["status"] == "approved_candidate"
        assert report["overallVerdict"] == "pass"
        assert report["auditProfile"] == "campaign_factory_v1"
        assert report["targetFile"].startswith("campaign_factory_variant_")
        assert report["verdictCodes"] == {"pdq": "pdq_pass"}
        assert report["readinessSummary"]["uploadReady"] is True
        assert report["filesAnalyzed"] == 1
        row = cf.conn.execute("SELECT * FROM audit_reports WHERE rendered_asset_id = 'asset_1'").fetchone()
        assert row["overall_verdict"] == "pass"
        assert json.loads(row["verdicts_json"]) == {"pdq": "pass"}
    finally:
        cf.close()


def test_contentforge_audit_uses_selected_reference_pattern(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"reference")
    seen = {}

    def fake_similarity(base_url, *, source, target_file=None, audit_profile=None, layers, originality_reference_files=None):
        seen["layers"] = layers
        seen["references"] = originality_reference_files
        return {
            "auditProfile": audit_profile,
            "targetFile": target_file,
            "layers": {},
            "verdicts": {"originality": "pass"},
            "verdictCodes": {"originality": "originality_pass"},
            "overallVerdict": "pass",
            "referenceMatch": {"mode": "reference_match_meter", "referenceMatchLevel": "high"},
            "readinessSummary": {"uploadReady": True, "blockingCodes": [], "warningCodes": []},
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        cf.conn.execute(
            """
            INSERT INTO reference_patterns
            (id, cluster_key, rank, label, visual_format, hook_type, caption_archetype,
             reference_ids_json, local_paths_json, public_urls_json, prompt_template_json,
             higgsfield_json, caption_formulas_json, raw_json, imported_at, updated_at)
            VALUES ('refpat_1', 'cluster', 1, 'cluster label', 'caption_led_visual', 'direct_response',
             'question_hook', '[]', ?, '[]', '{}', '{}', '[]', '{}', 'now', 'now')
            """,
            (json.dumps([str(reference)]),),
        )
        add_rendered_asset(cf, tmp_path)
        campaign = cf.campaign_by_slug("may")
        cf.conn.execute(
            """
            INSERT INTO campaign_reference_plans
            (id, campaign_id, reference_pattern_id, variant_count, created_at, updated_at)
            VALUES ('plan_1', ?, 'refpat_1', 3, 'now', 'now')
            """,
            (campaign["id"],),
        )
        cf.conn.commit()
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert "originality" in seen["layers"]
        assert "reference" not in seen["layers"]
        assert seen["references"] and seen["references"][0].startswith("campaign_factory_reference_")
        assert report["referencePattern"]["clusterKey"] == "cluster"
        assert report["referenceMatch"]["referenceMatchLevel"] == "high"
    finally:
        cf.close()


def test_contentforge_http_audit_records_warn_and_fail_results(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    def fake_similarity(base_url, *, source, target_file=None, audit_profile=None, layers):
        return {
            "layers": {"pdq": {}, "sscd": {}},
            "verdicts": {"pdq": "warn", "sscd": "fail"},
            "overallVerdict": "fail",
            "readinessSummary": {
                "blockingCodes": ["sscd_failed"],
                "warningCodes": ["pdq_review"],
                "blockingReasons": ["sscd: layer failed"],
                "warnings": ["pdq: layer warning"],
                "uploadReady": False,
                "recommendedAction": "reject",
            },
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert report["status"] == "needs_review"
        assert report["score"] == 0
        assert report["failedChecks"] == ["sscd", "sscd_failed"]
        assert report["warnings"] == ["pdq", "pdq_review"]
    finally:
        cf.close()


def test_contentforge_http_audit_keeps_review_only_layer_failures_nonblocking(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    def fake_similarity(base_url, *, source, target_file=None, audit_profile=None, layers):
        return {
            "layers": {"sscd": {}},
            "verdicts": {"sscd": "fail"},
            "overallVerdict": "warn",
            "readinessSummary": {
                "blockingCodes": [],
                "warningCodes": ["sscd_review"],
                "blockingReasons": [],
                "warnings": ["sscd: layer needs review"],
                "uploadReady": True,
                "recommendedAction": "review",
            },
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert report["score"] == 84
        assert report["failedChecks"] == []
        assert report["warnings"] == ["sscd_review"]
        readiness = cf.dashboard("may")["rendered"][0]["export_readiness"]
        assert not any(reason.startswith("audit_failed:sscd") for reason in readiness["blockingReasons"])
    finally:
        cf.close()


def test_contentforge_http_audit_handles_server_unavailable(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    def fake_similarity(base_url, *, source, target_file=None, audit_profile=None, layers):
        raise RuntimeError("ContentForge is unavailable")

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert report["status"] == "needs_review"
        assert "contentforge_http" in report["failedChecks"]
        assert report["error"] == "ContentForge is unavailable"
        assert "contentforge_http: ContentForge is unavailable" in report["warnings"]
        assert report["overallVerdict"] == "fail"
    finally:
        cf.close()


def test_contentforge_http_audit_handles_malformed_response(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    def fake_similarity(base_url, *, source, target_file=None, audit_profile=None, layers):
        return {"layers": {}, "verdicts": {}, "filesAnalyzed": 1}

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert report["status"] == "needs_review"
        assert "contentforge_malformed_response" in report["failedChecks"]
        assert report["overallVerdict"] == "fail"
    finally:
        cf.close()


def test_threadsdash_export_dry_run_creates_draft_payload_only(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model", account_handles=["ig_a"])
        source = cf.assets_for_campaign(cf.campaign_by_slug("may")["id"])[0]
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, caption_generation_json, created_at, updated_at)
            VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, 'ok.mp4', 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps({
                    "audioRecommendations": {
                        "primaryStrategy": "current_native_trending_sound",
                        "nativeAudioPreferred": True,
                        "recommendations": [{"audioVibe": "clean_fitcheck"}],
                    }
                }),
                now,
                now,
            ),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id="asset_1")
        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        assert payload["drafts"][0]["status"] == "draft"
        assert payload["drafts"][0]["platform"] == "instagram"
        assert payload["drafts"][0]["instagramAccountId"] is None
        assert payload["drafts"][0]["contentHash"] == "hash_1"
        assert payload["drafts"][0]["sourceContentHash"] == source["content_hash"]
        assert payload["drafts"][0]["captionHash"]
        assert payload["drafts"][0]["recipe"] == "v01_original"
        assert payload["drafts"][0]["audioRecommendations"]["primaryStrategy"] == "current_native_trending_sound"
        metadata = payload["drafts"][0]["metadata"]["campaign_factory"]
        assert metadata["campaign_id"] == "may"
        assert metadata["graph_id"].startswith("cg_rendered_asset_")
        assert metadata["campaign_graph_id"].startswith("cg_campaign_")
        assert metadata["source_asset_graph_id"].startswith("cg_source_asset_")
        assert metadata["rendered_asset_graph_id"] == metadata["graph_id"]
        assert metadata["source_asset_id"] == source["id"]
        assert metadata["rendered_asset_id"] == "asset_1"
        assert metadata["content_hash"] == "hash_1"
        assert metadata["source_content_hash"] == source["content_hash"]
        assert metadata["caption_hash"] == payload["drafts"][0]["captionHash"]
        assert metadata["recipe"] == "v01_original"
        assert metadata["audio_recommendations"]["primaryStrategy"] == "current_native_trending_sound"
        assert metadata["audio_intent"]["schema"] == "pipeline.audio_intent.v1"
        assert metadata["audio_intent"]["required"] is True
        assert metadata["audio_intent"]["status"] == "recommended"
        assert metadata["audio_intent"]["task"]["schema"] == "pipeline.audio_task.v1"
        assert metadata["audio_intent"]["task"]["status"] == "open"
        assert metadata["audio_intent"]["task"]["proof_required"] is False
        assert metadata["audio_intent"]["gates"]["allow_draft_export"] is True
        assert metadata["audio_intent"]["gates"]["allow_publish"] is False
        assert metadata["audio_strategy"] == "current_native_trending_sound"
        assert metadata["native_audio_preferred"] is True
        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=True,
            content_pillar="fit_check",
            cta_type="profile_visit",
            language="en",
        )
        assert Path(result["path"]).exists()
        assert result["dryRun"] is True
        assert result["payload"]["drafts"][0]["contentPillar"] == "fit_check"
        assert result["payload"]["drafts"][0]["ctaType"] == "profile_visit"
        assert result["payload"]["drafts"][0]["language"] == "en"
        written = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert written["path"] == result["path"]
        assert written["pipelineJobId"] == result["pipelineJobId"]
        written_meta = written["payload"]["drafts"][0]["metadata"]["campaign_factory"]
        assert written_meta["graph_id"] == metadata["graph_id"]
        assert written_meta["content_pillar"] == "fit_check"
        assert written_meta["cta_type"] == "profile_visit"
        assert written_meta["language"] == "en"
    finally:
        cf.close()


def test_content_graph_tracks_import_render_audit_approval_and_export(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    inserted: list[tuple[str, dict]] = []
    upserted: list[tuple[str, dict, str]] = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

        def upload_storage_object(self, bucket, storage_path, file_path, content_type):
            pass

        def insert_with_fallback(self, table, row, fallback_remove):
            inserted.append((table, dict(row)))
            return {"id": f"{table}_{len([item for item in inserted if item[0] == table])}", **row}

        def upsert(self, table, row, *, on_conflict):
            upserted.append((table, dict(row), on_conflict))
            return [{**row}]

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        ensure_exportable_distribution_plan(cf)
        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=False,
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            allow_warnings=True,
        )

        assert result["supabase"]["attempted"] is True
        node_types = {
            row["entity_type"]
            for row in cf.conn.execute("SELECT entity_type FROM content_graph_nodes").fetchall()
        }
        assert {"campaign", "source_asset", "rendered_asset", "audit_report", "approval_decision", "threadsdash_post"} <= node_types
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute("SELECT relation_type FROM content_graph_edges").fetchall()
        }
        assert "campaign_contains_source_asset" in edge_types
        assert "rendered_asset_to_audit_report" in edge_types
        assert "rendered_asset_to_approval_decision" in edge_types
        assert "rendered_asset_to_threadsdash_post" in edge_types
        mirror_tables = {table for table, _row, _conflict in upserted}
        assert {"campaign_factory_entities", "campaign_factory_edges", "campaign_factory_post_links"} <= mirror_tables
    finally:
        cf.close()


def test_recommend_next_batch_persists_idempotent_graph_backed_run(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.campaign_by_slug("may")
        now = "2026-01-02T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO reference_patterns (
              id, cluster_key, rank, label, visual_format, hook_type, caption_archetype,
              reference_ids_json, local_paths_json, public_urls_json, prompt_template_json,
              higgsfield_json, caption_formulas_json, audio_recommendations_json, raw_json,
              imported_at, updated_at
            )
            VALUES (
              'refpat_1', 'bathroom_mirror_curiosity', 1, 'Bathroom Mirror Curiosity',
              'mirror', 'curiosity', 'short_direct', '[]', '[]', '[]',
              '{"captionBrief":"short direct caption"}', '{}',
              '[{"formula":"short direct caption"}]',
              '{"recommendations":[{"audioTitle":"Runway Pop"}]}',
              '{"bank":{"suggestedVariantRecipes":["v01_original"]}}',
              ?, ?
            )
            """,
            (now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO campaign_reference_plans
            (id, campaign_id, reference_pattern_id, variant_count, created_at, updated_at)
            VALUES ('crp_1', ?, 'refpat_1', 5, ?, ?)
            """,
            (campaign["id"], now, now),
        )
        caption_hash = threadsdash_adapter._text_hash("caption")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, raw_json, created_at)
            VALUES
            ('perf_good', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_1', 'instagram',
             'published', 'ig_1', ?, 12000, 900, 80, 100, 140, 10000, '{}', ?)
            """,
            (campaign["id"], source["id"], source["content_hash"], caption_hash, now, now),
        )
        cf.conn.commit()

        first = cf.recommend_next_batch("may", count=5, account="ig_1", persist=True)
        second = cf.recommend_next_batch("may", count=5, account="ig_1", persist=True)

        validate_recommendation_next_batch(first)
        assert first["schema"] == "campaign_factory.recommendations.next_batch.v1"
        assert first["runId"] == second["runId"]
        assert first["items"][0]["status"] == "proposed"
        assert first["items"][0]["dataQuality"]["sampleSize"] > 0
        assert first["items"][0]["recommendationGraphId"].startswith("cg_recommendation_item_")
        assert first["items"][0]["campaignGraphId"].startswith("cg_campaign_")
        assert first["items"][0]["referencePatternGraphId"].startswith("cg_reference_pattern_")
        assert first["items"][0]["sourceAssetGraphId"].startswith("cg_source_asset_")
        assert first["items"][0]["renderedAssetGraphId"].startswith("cg_rendered_asset_")
        assert first["items"][0]["scoreBreakdown"]["performance"] > 50
        assert first["items"][0]["confidence"] in {"medium", "high"}
        assert cf.conn.execute("SELECT COUNT(*) FROM recommendation_runs").fetchone()[0] == 1
        assert cf.conn.execute("SELECT COUNT(*) FROM recommendation_items").fetchone()[0] == 1
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute("SELECT relation_type FROM content_graph_edges").fetchall()
        }
        assert "performance_snapshot_to_recommendation_input" in edge_types
        assert "recommendation_input_to_recommendation_run" in edge_types
        assert "recommendation_run_to_recommendation_item" in edge_types
        assert "rendered_asset_to_recommendation_item" in edge_types
        stored = cf.recommendation_runs("may")
        assert stored["runs"][0]["items"][0]["recommendationId"] == first["items"][0]["recommendationId"]
    finally:
        cf.close()


def test_recommendation_lifecycle_accept_link_and_measure(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.campaign_by_slug("may")
        now = "2026-01-02T00:00:00+00:00"
        caption_hash = threadsdash_adapter._text_hash("caption")
        cf.conn.execute(
            """
            INSERT INTO render_jobs
            (id, campaign_id, source_asset_id, reel_clip_stem, hooks_json, recipes_json, status, created_at, updated_at)
            VALUES ('rjob_1', ?, ?, 'clip_1', '[]', '[]', 'completed', ?, ?)
            """,
            (campaign["id"], source["id"], now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, raw_json, created_at)
            VALUES
            ('perf_rec', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_rec', 'instagram',
             'published', 'ig_1', ?, 12000, 900, 80, 100, 140, 10000, '{}', ?),
            ('perf_base_1', ?, 'manual_1', ?, 'hash_b1', ?, ?, 'v01_original', 'post_b1', 'instagram',
             'published', 'ig_1', ?, 100, 5, 0, 0, 0, 100, '{}', ?),
            ('perf_base_2', ?, 'manual_2', ?, 'hash_b2', ?, ?, 'v01_original', 'post_b2', 'instagram',
             'published', 'ig_1', ?, 120, 6, 0, 0, 0, 120, '{}', ?),
            ('perf_base_3', ?, 'manual_3', ?, 'hash_b3', ?, ?, 'v01_original', 'post_b3', 'instagram',
             'published', 'ig_1', ?, 90, 4, 0, 0, 0, 90, '{}', ?)
            """,
            (
                campaign["id"], source["id"], source["content_hash"], caption_hash, now, now,
                campaign["id"], source["id"], source["content_hash"], caption_hash, now, now,
                campaign["id"], source["id"], source["content_hash"], caption_hash, now, now,
                campaign["id"], source["id"], source["content_hash"], caption_hash, now, now,
            ),
        )
        cf.conn.commit()
        rec = cf.recommend_next_batch("may", count=1, account="ig_1", persist=True)
        item_id = rec["items"][0]["recommendationId"]

        accepted = cf.accept_recommendation_item(item_id, operator="operator_1", notes="use this")
        assert accepted["status"] == "accepted"
        assert accepted["decision"]["action"] == "accepted"
        assert accepted["acceptedAt"]

        linked = cf.link_recommendation_item(
            item_id,
            source_asset_id=source["id"],
            render_job_id="rjob_1",
            rendered_asset_id="asset_1",
            post_id="post_rec",
            performance_snapshot_id="perf_rec",
            evidence={"operator": "operator_1"},
        )
        assert linked["status"] == "posted"
        assert linked["evidence"]["links"]["postId"] == "post_rec"

        measured = cf.measure_recommendation_item(item_id)
        measured_again = cf.measure_recommendation_item(item_id)
        assert measured["status"] == "proved"
        assert measured_again["status"] == "proved"
        assert measured["outcome"]["baselineSnapshotCount"] == 3
        assert measured["baseline"]["baselineType"] == "campaign_account_history"
        assert measured["baseline"]["sampleSize"] == 3
        assert measured["baseline"]["threshold"] == 5
        assert measured["baseline"]["confidence"] == "usable"
        assert measured["measurementVersion"] == "recommendation_measurement.v1"
        with pytest.raises(ValueError, match="invalid recommendation status transition"):
            cf.accept_recommendation_item(item_id)
        overridden = cf.accept_recommendation_item(
            item_id,
            admin_override=True,
            override_reason="manual lifecycle correction",
        )
        assert overridden["status"] == "accepted"
        assert overridden["decision"]["adminOverrides"][0]["reason"] == "manual lifecycle correction"
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute("SELECT relation_type FROM content_graph_edges").fetchall()
        }
        assert "recommendation_item_to_source_asset" in edge_types
        assert "recommendation_item_to_render_job" in edge_types
        assert "recommendation_item_to_rendered_asset" in edge_types
        assert "recommendation_item_to_threadsdash_post" in edge_types
        assert "recommendation_item_to_performance_snapshot" in edge_types
    finally:
        cf.close()


def test_recommendation_accuracy_report_idempotent_and_segments(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.campaign_by_slug("may")
        now = "2026-05-30T00:00:00+00:00"
        caption_hash = threadsdash_adapter._text_hash("caption")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, raw_json, created_at)
            VALUES
            ('perf_acc_rec', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_rec', 'instagram',
             'published', 'ig_1', ?, 12000, 900, 80, 100, 140, 10000, '{}', ?),
            ('perf_acc_base_1', ?, 'manual_1', ?, 'hash_b1', ?, ?, 'v01_original', 'post_b1', 'instagram',
             'published', 'ig_1', ?, 100, 5, 0, 0, 0, 100, '{}', ?),
            ('perf_acc_base_2', ?, 'manual_2', ?, 'hash_b2', ?, ?, 'v01_original', 'post_b2', 'instagram',
             'published', 'ig_1', ?, 120, 6, 0, 0, 0, 120, '{}', ?),
            ('perf_acc_base_3', ?, 'manual_3', ?, 'hash_b3', ?, ?, 'v01_original', 'post_b3', 'instagram',
             'published', 'ig_1', ?, 90, 4, 0, 0, 0, 90, '{}', ?)
            """,
            (
                campaign["id"], source["id"], source["content_hash"], caption_hash, now, now,
                campaign["id"], source["id"], source["content_hash"], caption_hash, now, now,
                campaign["id"], source["id"], source["content_hash"], caption_hash, now, now,
                campaign["id"], source["id"], source["content_hash"], caption_hash, now, now,
            ),
        )
        cf.conn.commit()
        rec = cf.recommend_next_batch("may", count=1, account="ig_1", persist=True)
        item_id = rec["items"][0]["recommendationId"]
        cf.accept_recommendation_item(item_id)
        cf.link_recommendation_item(item_id, rendered_asset_id="asset_1", performance_snapshot_id="perf_acc_rec")
        cf.measure_recommendation_item(item_id)
        measured_id = "recitem_measured"
        measured_payload = {
            "recommendationId": measured_id,
            "status": "measured",
            "confidence": "low",
            "dataQuality": {"level": "low"},
            "outcome": {"outcomeScore": 50, "baselineScore": 50, "measuredAt": now},
        }
        cf.conn.execute(
            """
            INSERT INTO recommendation_items (
              id, run_id, rank, target_account, recommendation_graph_id, status,
              score, confidence, data_quality_json, outcome_json, baseline_json,
              measurement_version, output_json, measured_at, created_at
            )
            VALUES (?, ?, 2, 'ig_1', ?, 'measured', 50, 'low', ?, ?, '{}',
              'recommendation_measurement.v1', ?, ?, ?)
            """,
            (
                measured_id,
                rec["runId"],
                cf.ensure_graph_node("recommendation_item", local_table="recommendation_items", local_id=measured_id, payload=measured_payload),
                json.dumps({"level": "low"}),
                json.dumps({"status": "measured", "outcomeScore": 50, "baselineScore": 50, "measuredAt": now}),
                json.dumps(measured_payload),
                now,
                now,
            ),
        )
        cf.conn.commit()

        first = cf.recommendation_accuracy("may", account="ig_1", window_days=365)
        second = cf.rebuild_recommendation_accuracy("may", account="ig_1", window_days=365)
        validate_recommendation_accuracy_report(first)
        assert second["schema"] == "campaign_factory.recommendation_accuracy_report.v1"
        assert first["overall"]["measuredCount"] == 2
        assert first["overall"]["provedCount"] == 1
        assert first["overall"]["inconclusiveCount"] == 1
        assert first["overall"]["accuracyDenominator"] == 1
        assert first["overall"]["accuracyRate"] == 1.0
        assert first["trustConfidence"] == "insufficient"
        assert first["calibration"][0]["key"] in {"strong", "weak"}
        assert cf.conn.execute("SELECT COUNT(*) FROM recommendation_accuracy_observations").fetchone()[0] == 2
        assert cf.conn.execute("SELECT COUNT(*) FROM recommendation_accuracy_reports").fetchone()[0] == 1
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute("SELECT relation_type FROM content_graph_edges").fetchall()
        }
        assert "recommendation_item_to_recommendation_accuracy_observation" in edge_types
        assert "recommendation_accuracy_observation_to_report" in edge_types
        summary = cf.trust_summary("may")
        assert summary["recommendations"]["proof"]["measuredCount"] == 2
    finally:
        cf.close()


def test_account_memory_rebuild_and_account_fit_recommendations(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.campaign_by_slug("may")
        now = "2026-01-02T12:00:00+00:00"
        caption_hash = threadsdash_adapter._text_hash("caption")
        raw = {
            "metadata": {
                "campaign_factory": {
                    "hook_key": "curiosity_open_loop",
                    "recipe": "v01_original",
                    "audio_intent": {"recommendations": [{"audioTitle": "Runway Pop"}]},
                    "reference_pattern": {"label": "Mirror Curiosity", "visualFormat": "mirror", "hookType": "curiosity"},
                    "caption_generation": {"captionFormula": "short direct caption"},
                }
            }
        }
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible, raw_json, created_at)
            VALUES
            ('perf_account_1', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_1', 'instagram',
             'published', 'ig_memory', ?, 5000, 400, 20, 30, 50, 4500, 1, ?, ?)
            """,
            (campaign["id"], source["id"], source["content_hash"], caption_hash, now, json.dumps(raw), now),
        )
        cf.conn.commit()

        rebuilt = cf.rebuild_account_memory("may")
        assert rebuilt["accountCount"] == 1
        memory = cf.account_memory("may", account="ig_memory")
        account = memory["accounts"][0]
        assert account["accountId"] == "ig_memory"
        assert account["sampleSize"] == 1
        assert account["confidence"] == "low"
        assert account["patternStats"]

        rec = cf.recommend_next_batch("may", count=1, account="ig_memory", persist=True)
        item = rec["items"][0]
        assert item["accountMemory"]["accountId"] == "ig_memory"
        assert item["accountFitEvidence"]["score"] is not None
        assert item["autonomyLevel"] == "level_2"
    finally:
        cf.close()


def test_exception_queue_idempotent_resolve_snooze_reopen(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.campaign_by_slug("may")
        rec = cf.recommend_next_batch("may", count=1, account="ig_1", persist=True)
        item_id = rec["items"][0]["recommendationId"]
        graph_id = rec["items"][0]["recommendationGraphId"]

        first = cf.create_exception(
            reason_code="missing_account_assignment",
            severity="medium",
            campaign_id=campaign["id"],
            entity_graph_id=graph_id,
            recommendation_item_id=item_id,
            payload={"source": "test"},
        )
        second = cf.create_exception(
            reason_code="missing_account_assignment",
            severity="high",
            campaign_id=campaign["id"],
            entity_graph_id=graph_id,
            recommendation_item_id=item_id,
            payload={"source": "test_rerun"},
        )
        assert first["id"] == second["id"]
        open_rows = cf.exceptions("may", status="open")["exceptions"]
        assert len(open_rows) == 1
        assert open_rows[0]["severity"] == "high"

        snoozed = cf.snooze_exception(first["id"], until="2026-01-03T00:00:00+00:00", reason="wait", operator="op")
        assert snoozed["status"] == "snoozed"
        reopened = cf.reopen_exception(first["id"], reason="ready", operator="op")
        assert reopened["status"] == "open"
        resolved = cf.resolve_exception(first["id"], resolution="fixed", operator="op")
        assert resolved["status"] == "resolved"

        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute("SELECT relation_type FROM content_graph_edges").fetchall()
        }
        assert "entity_to_trust_exception" in edge_types
        assert "recommendation_item_to_trust_exception" in edge_types
    finally:
        cf.close()


def test_execute_accepted_recommendation_links_existing_asset_without_publishing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        rec = cf.recommend_next_batch("may", count=1, account="ig_1", persist=True)
        item_id = rec["items"][0]["recommendationId"]
        cf.accept_recommendation_item(item_id, operator="operator_1")

        executed = cf.execute_accepted_recommendation(item_id, run_audit=False)
        assert executed["schema"] == "campaign_factory.recommendation_execution.v1"
        assert executed["recommendation"]["status"] == "executed"
        assert executed["recommendation"]["executionStatus"] in {"completed", "blocked"}
        assert executed["recommendation"]["renderedAssetId"] == "asset_1"
        assert cf.pipeline_job(executed["pipelineJobId"])["status"] == "succeeded"
        assert cf.conn.execute("SELECT COUNT(*) FROM threadsdash_exports").fetchone()[0] == 0
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute("SELECT relation_type FROM content_graph_edges").fetchall()
        }
        assert "recommendation_item_to_rendered_asset" in edge_types
    finally:
        cf.close()


def test_autonomy_policy_blocks_level_one_execution(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        rec = cf.recommend_next_batch("may", count=1, account="ig_1", persist=True)
        item_id = rec["items"][0]["recommendationId"]
        cf.accept_recommendation_item(item_id)

        policy = cf.set_autonomy_level("level_1")
        assert policy["level"] == "level_1"
        with pytest.raises(ValueError, match="auto execute blocked by autonomy level"):
            cf.execute_accepted_recommendation(item_id)
        exceptions = cf.exceptions("may", status="open")["exceptions"]
        assert any(item["reasonCode"] == "autonomy_level_blocks_execution" for item in exceptions)
        summary = cf.trust_summary("may")
        assert summary["schema"] == "campaign_factory.trust_summary.v1"
        assert summary["autonomyLevel"] == "level_1"
        assert summary["exceptions"]["openCount"] >= 1
        assert summary["recommendations"]["acceptedWaitingExecution"] == 1
        assert summary["recommendedAction"] in {"execute_accepted_recommendations", "review_high_severity_exceptions"}

        cf.set_autonomy_level("level_2")
        executed = cf.execute_accepted_recommendation(item_id, run_audit=False)
        assert executed["publishesAutomatically"] is False
        assert executed["recommendation"]["status"] == "executed"
    finally:
        cf.close()


def test_threadsdash_audio_intent_defaults_to_needs_operator_selection_without_recommendations(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        folder = tmp_path / "inputs"
        folder.mkdir()
        (folder / "a.mp4").write_bytes(b"source")
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        source = cf.assets_for_campaign(cf.campaign_by_slug("may")["id"])[0]
        rendered_path = tmp_path / "needs_audio.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_audio', ?, ?, 'hash_audio', ?, ?, 'needs_audio.mp4', 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?)
            """,
            (source["campaign_id"], source["id"], str(rendered_path), str(rendered_path), now, now),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id="asset_audio")

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        intent = payload["drafts"][0]["metadata"]["campaign_factory"]["audio_intent"]
        readiness = evaluate_export_readiness(cf, campaign_slug="may", user_id="user_1")

        assert intent["required"] is True
        assert intent["status"] == "needs_operator_selection"
        assert intent["task"]["status"] == "open"
        assert "campaign_audio_unresolved: select audio before ThreadsDashboard export" in readiness["assets"][0]["blockingReasons"]
        assert any(
            reason.endswith("campaign_audio_unresolved: select audio before ThreadsDashboard export")
            for reason in readiness["blockingReasons"]
        )
        assert not any("native_audio_unresolved" in reason for reason in readiness["blockingReasons"])
    finally:
        cf.close()


def test_dashboard_audio_workflow_summary_counts_audio_tasks(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        rendered = [cf._dashboard_rendered_asset(asset) for asset in cf.rendered_for_campaign(cf.campaign_by_slug("may")["id"])]
        summary = cf.audio_workflow_summary(rendered)

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
        summary = cf.audio_workflow_summary(rendered)

        assert summary["taskCounts"]["completed"] == 1
        assert summary["counts"]["ready"] == 1
    finally:
        cf.close()


def test_threadsdash_audio_intent_safe_statuses_pass_live_gate(tmp_path: Path, monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    for status in ("attached", "verified", "skipped", "not_required"):
        cf = make_factory(tmp_path / status)
        try:
            source, _ = add_rendered_asset(cf, tmp_path / status)
            cf.review_rendered_asset("asset_1", decision="approved")
            add_audit_report(cf)
            required = status != "not_required"
            cf.conn.execute(
                "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
                (json.dumps({
                    "audioIntent": {
                        "schema": "pipeline.audio_intent.v1",
                        "mode": "native_platform_audio",
                        "required": required,
                        "status": status,
                        **({
                            "operator_selection": {
                                "platform_audio_id": "ig_audio_1",
                                "selected_at": "2026-05-22T12:00:00+00:00",
                                **({"attached_at": "2026-05-22T12:05:00+00:00"} if status == "attached" else {"verified_at": "2026-05-22T12:10:00+00:00"}),
                            }
                        } if status in {"attached", "verified"} else {}),
                    }
                }),),
            )
            cf.conn.commit()

            readiness = evaluate_export_readiness(
                cf,
                campaign_slug="may",
                user_id="user_1",
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
            )

            assert readiness["liveExportAllowed"] is True
            assert not any("campaign_audio_unresolved" in reason for reason in readiness["blockingReasons"])
            assert source["id"]
        finally:
            cf.close()


def test_threadsdash_audio_intent_attached_requires_native_proof(tmp_path: Path, monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": True,
                    "status": "attached",
                }
            }),),
        )
        cf.conn.commit()

        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assert readiness["liveExportAllowed"] is False
        assert any(
            "campaign_audio_unresolved: select audio before ThreadsDashboard export" in reason
            for reason in readiness["blockingReasons"]
        )
    finally:
        cf.close()


def test_attach_audio_to_distribution_plan_marks_campaign_audio_attached_and_exports_metadata(tmp_path: Path, monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": True,
                    "status": "needs_operator_selection",
                }
            }),),
        )
        cf.conn.commit()
        plan = cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_stacey_1",
            planned_window_start="2026-06-05T15:00:00+00:00",
            planned_window_end="2026-06-05T15:15:00+00:00",
        )

        result = cf.attach_audio_to_distribution_plan(
            plan["id"],
            track_id="ig_audio_123",
            track_name="Proof track",
            source="manual",
            selected_reason="operator_selected_for_proof",
            operator="tester",
        )
        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1", schedule_mode="live")
        draft_intent = payload["drafts"][0]["metadata"]["campaign_factory"]["audio_intent"]
        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            schedule_mode="live",
        )

        assert result["audioIntent"]["status"] == "attached"
        assert result["audioIntent"]["operator_selection"]["audio_id"] == "ig_audio_123"
        assert result["audioIntent"]["operator_selection"]["audio_title"] == "Proof track"
        assert result["audioIntent"]["operator_selection"]["selection_source"] == "manual"
        assert result["audioIntent"]["operator_selection"]["selected_reason"] == "operator_selected_for_proof"
        campaign_meta = payload["drafts"][0]["metadata"]["campaign_factory"]
        assert campaign_meta["asset_state"] == "exportable"
        assert campaign_meta["audio_id"] == "ig_audio_123"
        assert campaign_meta["handoff_manifest"]["asset_id"] == "asset_1"
        assert campaign_meta["handoff_manifest"]["content_fingerprint"] == "hash_1"
        assert campaign_meta["handoff_manifest"]["caption_hash"] == "caption_hash_1"
        assert campaign_meta["handoff_manifest"]["audio_id"] == "ig_audio_123"
        assert campaign_meta["publishability_failure_reasons"] == []
        assert draft_intent["status"] == "attached"
        assert draft_intent["operator_selection"]["audio_id"] == "ig_audio_123"
        assert draft_intent["operator_selection"]["selected_reason"] == "operator_selected_for_proof"
        assert readiness["liveExportAllowed"] is True
        assert not any("campaign_audio_unresolved" in reason for reason in readiness["blockingReasons"])
    finally:
        cf.close()


def test_audio_segment_and_cover_frame_export_as_campaign_owned_instructions(tmp_path: Path, monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": True,
                    "status": "needs_operator_selection",
                },
            }),),
        )
        cf.conn.commit()
        cf.attach_cover_frame_to_rendered_asset(
            "asset_1",
            seconds=1.4,
            cover_image_path="/tmp/stacey-cover.jpg",
            cover_image_url="https://cdn.example.com/stacey-cover.jpg",
            cover_image_hash="cover_hash_1",
            reason="best face and outfit framing",
        )
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_stacey_1")

        cf.attach_audio_to_distribution_plan(
            plan["id"],
            track_id="ig_audio_123",
            track_name="Proof track",
            source="manual",
            selected_reason="operator selected different song section",
            segment_start_seconds=18.5,
            segment_duration_seconds=6.0,
            segment_label="hook section",
            segment_reason="use a different part of the same song",
            operator="tester",
        )

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1", schedule_mode="live")
        campaign_meta = payload["drafts"][0]["metadata"]["campaign_factory"]
        manifest = campaign_meta["handoff_manifest"]

        assert campaign_meta["audio_segment"] == {
            "start_seconds": 18.5,
            "duration_seconds": 6.0,
            "label": "hook section",
            "reason": "use a different part of the same song",
        }
        assert manifest["audio_segment"] == campaign_meta["audio_segment"]
        assert campaign_meta["cover_frame"] == {
            "seconds": 1.4,
            "image_path": "/tmp/stacey-cover.jpg",
            "image_url": "https://cdn.example.com/stacey-cover.jpg",
            "image_hash": "cover_hash_1",
            "reason": "best face and outfit framing",
        }
        assert manifest["cover_frame"] == campaign_meta["cover_frame"]
        assert payload["drafts"][0]["media"][0]["thumbnailUrl"] == "https://cdn.example.com/stacey-cover.jpg"
        assert payload["drafts"][0]["metadata"]["coverUrl"] == "https://cdn.example.com/stacey-cover.jpg"
        assert payload["drafts"][0]["metadata"]["thumbOffset"] == 1.4
    finally:
        cf.close()


def test_distribution_plan_exports_trial_and_story_surfaces(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.upsert_model_account_profile(
            "model",
            allowed_instagram_account_ids=["ig_good"],
            default_smart_link="https://example.com/stacey",
            story_cta_text="new post is up",
        )
        trial = cf.create_distribution_plan(
            "asset_1",
            surface="trial_reel",
            instagram_account_id="ig_good",
            planned_window_start="2026-01-02T10:00:00+00:00",
            reason_code="test_uncertain_winner",
        )
        story = cf.create_distribution_plan(
            "asset_1",
            surface="story_cta",
            instagram_account_id="ig_good",
            paired_rendered_asset_id="asset_1",
            reason_code="cta_followup",
            smart_link="https://example.com/stacey",
            cta_text="new post is up",
        )

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1", schedule_mode="preview")
        by_surface = {draft["distributionSurface"]: draft for draft in payload["drafts"]}
        assert set(by_surface) == {"trial_reel", "story_cta"}
        assert by_surface["trial_reel"]["status"] == "draft"
        assert by_surface["trial_reel"]["scheduledFor"] == "2026-01-02T10:00:00+00:00"
        assert by_surface["trial_reel"]["metadata"]["campaign_factory"]["preview_schedule_only"] is True
        assert "trialReels" not in by_surface["trial_reel"]["metadata"]
        assert by_surface["trial_reel"]["metadata"]["campaign_factory"]["instagram_trial_reels"] is False
        assert by_surface["trial_reel"]["metadata"]["campaign_factory"]["trial_reel"] is True
        assert by_surface["trial_reel"]["metadata"]["campaign_factory"]["distribution_plan_id"] == trial["id"]
        assert by_surface["story_cta"]["content"] == "new post is up"
        assert by_surface["story_cta"]["metadata"]["campaign_factory"]["distribution_plan_id"] == story["id"]
        assert by_surface["story_cta"]["metadata"]["campaign_factory"]["smart_link"] == "https://example.com/stacey"
        assert by_surface["story_cta"]["metadata"]["campaign_factory"]["paired_rendered_asset_id"] == "asset_1"
        assert by_surface["trial_reel"]["metadata"]["campaign_factory"]["account_profile"]["modelSlug"] == "model"
        assert by_surface["trial_reel"]["campaignId"] == "may"
    finally:
        cf.close()


def test_regular_reel_manifest_defaults_instagram_trial_reels_false(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")

        plan = cf.create_distribution_plan("asset_1", surface="regular_reel", instagram_account_id="ig_good")
        explanation = cf.explain_publishability("asset_1", distribution_plan_id=plan["id"])

        manifest = explanation["handoff_manifest"]
        assert plan["instagramTrialReels"] is False
        assert plan["trialGraduationStrategy"] is None
        assert manifest["instagram_trial_reels"] is False
        assert manifest["trial_graduation_strategy"] is None
    finally:
        cf.close()


def test_internal_trial_or_proof_campaign_does_not_set_instagram_trial_reels(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path, campaign_slug="stacey_variant_fanout_proof_trial_20260606")
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")

        plan = cf.create_distribution_plan("asset_1", surface="trial_reel", instagram_account_id="ig_good")
        explanation = cf.explain_publishability("asset_1", distribution_plan_id=plan["id"])

        manifest = explanation["handoff_manifest"]
        assert plan["surface"] == "trial_reel"
        assert plan["instagramTrialReels"] is False
        assert manifest["instagram_trial_reels"] is False
        assert manifest["trial_graduation_strategy"] is None
    finally:
        cf.close()


def test_explicit_instagram_trial_reel_manifest_includes_trial_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")

        plan = cf.create_distribution_plan(
            "asset_1",
            surface="trial_reel",
            instagram_account_id="ig_good",
            instagram_trial_reels=True,
            trial_graduation_strategy="MANUAL",
        )
        explanation = cf.explain_publishability("asset_1", distribution_plan_id=plan["id"])

        manifest = explanation["handoff_manifest"]
        assert plan["contentSurface"] == "reel"
        assert plan["instagramTrialReels"] is True
        assert plan["trialGraduationStrategy"] == "MANUAL"
        assert manifest["content_surface"] == "reel"
        assert manifest["distribution_surface"] == "trial_reel"
        assert manifest["ig_media_type"] == "REELS"
        assert manifest["instagram_trial_reels"] is True
        assert manifest["trial_graduation_strategy"] == "MANUAL"
    finally:
        cf.close()


def test_non_reel_instagram_trial_intent_is_blocked(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_feed_trial_blocked",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="new post",
        )

        with pytest.raises(ValueError, match="Instagram Trial Reels require reel content"):
            cf.create_distribution_plan(
                "asset_feed_trial_blocked",
                surface="feed_single",
                instagram_account_id="ig_good",
                instagram_trial_reels=True,
                trial_graduation_strategy="MANUAL",
            )
    finally:
        cf.close()


def test_invalid_trial_graduation_strategy_is_blocked(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")

        with pytest.raises(ValueError, match="trial_graduation_strategy must be one of"):
            cf.create_distribution_plan(
                "asset_1",
                surface="trial_reel",
                instagram_account_id="ig_good",
                instagram_trial_reels=True,
                trial_graduation_strategy="AUTO",
            )
    finally:
        cf.close()


def test_plan_distribution_creates_trial_heavy_preview_plans(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        now = "2026-01-01T00:00:00+00:00"
        for i in range(2, 6):
            rendered_path = tmp_path / f"ok_{i}.mp4"
            rendered_path.write_bytes(b"rendered")
            cf.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
                 caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
                 caption_generation_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'v01_original', 'approved_candidate', 'approved', ?, ?, ?)
                """,
                (
                    f"asset_{i}",
                    source["campaign_id"],
                    source["id"],
                    f"hash_{i}",
                    str(rendered_path),
                    str(rendered_path),
                    f"ok_{i}.mp4",
                    f"caption {i}",
                    f"caption_hash_{i}",
                    json.dumps({
                        "schema": "campaign_factory.caption_outcome_context.v1",
                        "caption_hash": f"caption_hash_{i}",
                        "caption_text": f"caption {i}",
                        "caption_bank": "test_bank",
                        "caption_banks": ["test_bank"],
                        "creator_mix": "Test",
                        "render_recipe": "v01_original",
                        "captionPlacementPolicy": "focal_safe_v1",
                        "captionPlacementDecision": {"status": "passed", "selectedLane": "top"},
                    }),
                    json.dumps({
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        }
                    }),
                    now,
                    now,
                ),
            )
            add_audit_report(cf, rendered_asset_id=f"asset_{i}", audit_id=f"audit_{i}")
        cf.conn.commit()
        cf.upsert_model_account_profile(
            "model",
            allowed_instagram_account_ids=["ig_1", "ig_2", "ig_3", "ig_4", "ig_5"],
            story_cta_text="new post is up",
        )

        result = cf.plan_distribution("may", user_id="user_1")
        plans = cf.distribution_plans_for_campaign("may")
        primary = [plan for plan in plans if plan["surface"] != "story_cta"]
        stories = [plan for plan in plans if plan["surface"] == "story_cta"]

        assert result["surfaceCounts"]["regular_reel"] == 1
        assert result["surfaceCounts"]["trial_reel"] == 3
        assert result["unplannedCount"] == 1
        assert len(primary) == 4
        assert len(stories) == 4
        assert all(plan["plannedWindowStart"] for plan in primary)
        assert all(plan["instagramAccountId"] in {"ig_1", "ig_2", "ig_3", "ig_4", "ig_5"} for plan in primary)

        unplanned_id = result["unplanned"][0]["renderedAssetId"]
        cf.assign_asset_account(unplanned_id, instagram_account_id="ig_5")
        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1", schedule_mode="preview")
        assert len(payload["drafts"]) == len(plans)
        assert unplanned_id not in {draft["renderedAssetId"] for draft in payload["drafts"]}
    finally:
        cf.close()


def test_clear_preview_schedule_only_unschedules_campaign_factory_rows(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = [
        {
            "id": "post_cf",
            "user_id": "user_1",
            "status": "scheduled",
            "scheduled_for": "2026-05-20T14:00:00+00:00",
            "media_urls": ["https://example.com/reel.mp4"],
            "metadata": {
                "previewScheduleOnly": True,
                "campaign_factory": {
                    "campaign_id": "may",
                    "rendered_asset_id": "asset_1",
                    "preview_schedule_only": True,
                },
            },
        },
        {
            "id": "post_other_campaign",
            "user_id": "user_1",
            "status": "scheduled",
            "scheduled_for": "2026-05-20T15:00:00+00:00",
            "media_urls": ["https://example.com/other.mp4"],
            "metadata": {"campaign_factory": {"campaign_id": "other"}},
        },
        {
            "id": "post_manual",
            "user_id": "user_1",
            "status": "scheduled",
            "scheduled_for": "2026-05-20T16:00:00+00:00",
            "media_urls": ["https://example.com/manual.mp4"],
            "metadata": {"source": "manual"},
        },
        {
            "id": "post_published",
            "user_id": "user_1",
            "status": "published",
            "scheduled_for": "2026-05-20T17:00:00+00:00",
            "media_urls": ["https://example.com/published.mp4"],
            "metadata": {"campaign_factory": {"campaign_id": "may"}},
        },
    ]

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            user_filter = params.get("user_id")
            if user_filter == "eq.user_1":
                return [dict(row) for row in rows]
            return []

        def update(self, table, values, filters):
            assert table == "posts"
            assert filters["user_id"] == "eq.user_1"
            assert filters["status"] == "eq.scheduled"
            post_id = filters["id"].removeprefix("eq.")
            updated = []
            for row in rows:
                if row["id"] == post_id and row["user_id"] == "user_1" and row["status"] == "scheduled":
                    row.update(values)
                    updated.append(dict(row))
            return updated

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        folder = tmp_path / "inputs"
        folder.mkdir()
        (folder / "a.mp4").write_bytes(b"source")
        cf.import_folder(folder, campaign_slug="may", model_slug="model")

        result = clear_preview_schedule(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        cleared = rows[0]
        other_campaign = rows[1]
        manual = rows[2]
        published = rows[3]
        cleared_meta = cleared["metadata"]["campaign_factory"]

        assert result["clearedCount"] == 1
        assert result["remainingScheduledCount"] == 0
        assert cleared["status"] == "draft"
        assert cleared["scheduled_for"] is None
        assert cleared["media_urls"] == ["https://example.com/reel.mp4"]
        assert cleared_meta["previous_scheduled_for"] == "2026-05-20T14:00:00+00:00"
        assert cleared_meta["unscheduled_reason"] == "audio_workflow_not_ready"
        assert cleared_meta["preview_schedule_only"] is True
        assert other_campaign["status"] == "scheduled"
        assert manual["status"] == "scheduled"
        assert published["status"] == "published"
    finally:
        cf.close()


def test_model_account_profile_blocks_wrong_model_account(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.upsert_model_account_profile("model", allowed_instagram_account_ids=["ig_good"])
        cf.assign_asset_account("asset_1", instagram_account_id="ig_wrong")

        readiness = evaluate_export_readiness(cf, campaign_slug="may", user_id="user_1")
        row = readiness["assets"][0]
        plan = cf.account_plan("may", user_id="user_1")

        assert "model_account_mismatch" in row["blockingReasons"]
        assert "asset_1:model_account_mismatch" in readiness["blockingReasons"]
        assert "model_account_mismatch" in plan["rows"][0]["warnings"]
    finally:
        cf.close()


def test_end_to_end_smoke_import_audit_approve_export(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        imported = cf.import_folder(folder, campaign_slug="launch", model_slug="model", account_handles=["ig_a"])
        source = imported["imported"][0]
        rendered_path = tmp_path / "rendered.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_smoke', ?, ?, 'hash_smoke', ?, ?, 'rendered.mp4', 'caption', 'v01_original', 'pending', 'draft', ?, ?)
            """,
            (source["campaign_id"], source["id"], str(rendered_path), str(rendered_path), now, now),
        )
        cf.conn.commit()
        audit = audit_campaign(cf, campaign_slug="launch")
        assert audit["reports"][0]["status"] == "needs_review"
        cf.approve_rendered_asset("asset_smoke")
        exported = export_threadsdash(cf, campaign_slug="launch", user_id="user_1", dry_run=True)
        data = json.loads(Path(exported["path"]).read_text())
        assert data["draftCount"] == 1
        draft = data["payload"]["drafts"][0]
        assert draft["status"] == "draft"
        assert "scheduledFor" not in draft
    finally:
        cf.close()


def test_dashboard_returns_latest_audit_and_readiness(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        audit = add_audit_report(cf, warnings=["compression"], overall_verdict="warn")
        report_path = Path(audit["path"])
        report_payload = json.loads(report_path.read_text())
        report_payload["creativeQuality"] = {
            "semanticEngine": "heuristic_v1",
            "modelBacked": False,
            "score": 72,
            "hookClarity": {"score": 80, "level": "strong", "text": "just cracked you in my head"},
            "visualClarity": {"score": 68, "level": "medium"},
            "openingStrength": {"score": 70, "level": "medium"},
            "subjectVisibility": {"score": 64, "level": "medium"},
            "warnings": [{"code": "creative_hook_generic", "label": "Generic hook"}],
        }
        report_path.write_text(json.dumps(report_payload), encoding="utf-8")
        dashboard = cf.dashboard("may")
        asset = dashboard["rendered"][0]
        assert asset["latest_audit"]["id"] == "audit_1"
        assert asset["latest_audit"]["overallVerdict"] == "warn"
        assert asset["latest_audit"]["readinessSummary"]["uploadReady"] is True
        assert asset["latest_audit"]["creativeQuality"]["semanticEngine"] == "heuristic_v1"
        assert asset["latest_audit"]["creativeQuality"]["score"] == 72
        assert asset["latest_audit"]["creativeQuality"]["hookClarity"]["score"] == 80
        assert asset["export_readiness"]["state"] == "blocked"
        assert "review_state:draft" in asset["export_readiness"]["blockingReasons"]
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
                "recommendations": [{
                    "audioTitle": "Runway Pop",
                    "artistName": "DJ A",
                    "audioId": "ig_1",
                    "freshness": "rising",
                    "confidence": 0.91,
                }],
            },
        },
        {
            "id": "asset_selected",
            "captionGeneration": {
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "required": True,
                    "status": "selected",
                    "recommendations": [{"audioTitle": "Runway Pop", "artistName": "DJ A", "audioId": "ig_1"}],
                }
            },
            "referencePattern": {},
            "audioRecommendations": {"recommendations": []},
        },
        {
            "id": "asset_blocked",
            "captionGeneration": {"audioIntent": {"required": True, "status": "blocked"}},
            "referencePattern": {},
            "audioRecommendations": {},
        },
        {
            "id": "asset_ready",
            "captionGeneration": {"audioIntent": {"required": True, "status": "attached"}},
            "referencePattern": {},
            "audioRecommendations": {},
        },
    ]
    try:
        summary = cf.audio_workflow_summary(rendered)

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


def test_dashboard_defaults_to_campaign_with_rendered_assets(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        empty_folder = tmp_path / "empty_inputs"
        empty_folder.mkdir()
        (empty_folder / "empty.mp4").write_bytes(b"empty")
        cf.import_folder(empty_folder, campaign_slug="new_empty", model_slug="model")
        add_rendered_asset(cf, tmp_path, campaign_slug="with_assets")
        dashboard = cf.dashboard()
        assert dashboard["campaign"]["slug"] == "with_assets"
        assert len(dashboard["rendered"]) == 1
    finally:
        cf.close()


def test_review_decision_supports_reject_and_approve(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        rejected = cf.review_rendered_asset("asset_1", decision="rejected", notes="no")
        assert rejected["review_state"] == "rejected"
        approved = cf.review_rendered_asset("asset_1", decision="approved", notes="ok")
        assert approved["review_state"] == "approved"
        decisions = cf.conn.execute("SELECT decision FROM approval_decisions ORDER BY created_at").fetchall()
        assert [row["decision"] for row in decisions] == ["rejected", "approved"]
    finally:
        cf.close()


def test_operator_approval_requires_safe_audit_when_guard_enabled(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        with pytest.raises(ValueError, match="audit_status:pending"):
            cf.review_rendered_asset("asset_1", decision="approved", require_safe_audit=True)

        cf.conn.execute("UPDATE rendered_assets SET audit_status = 'approved_candidate' WHERE id = 'asset_1'")
        cf.conn.commit()
        approved = cf.review_rendered_asset("asset_1", decision="approved", require_safe_audit=True)

        assert approved["review_state"] == "approved"

        cf.conn.execute("UPDATE rendered_assets SET audit_status = 'needs_review', review_state = 'review_ready' WHERE id = 'asset_1'")
        cf.conn.commit()
        warning_only = cf.review_rendered_asset("asset_1", decision="approved", require_safe_audit=True)

        assert warning_only["review_state"] == "approved"
    finally:
        cf.close()


def test_media_route_refuses_unknown_asset(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    cf.close()
    monkeypatch.setattr(app_module, "settings", cf.settings)
    client = TestClient(app_module.app)
    response = client.get("/api/rendered/missing/media")
    assert response.status_code == 404


def test_export_readiness_blocks_missing_audit_rejected_failed_and_published(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        rows.append({
            "id": "post_1",
            "status": "published",
            "platform": "instagram",
            "media_type": "reel",
            "ig_media_type": "REELS",
            "content_surface": "reel",
            "account_id": None,
            "instagram_account_id": None,
            "created_at": "2026-01-03T00:00:00+00:00",
            "metadata": {
                "campaign_factory": {
                    "campaign_id": "may",
                    "source_asset_id": source["id"],
                        "rendered_asset_id": "asset_1",
                        "content_hash": "hash_1",
                        "source_content_hash": source["content_hash"],
                        "caption_hash": "caption_hash_1",
                    }
                },
            })
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        add_audit_report(cf, failed=["forensics"], overall_verdict="fail", upload_ready=False)
        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert readiness["liveExportAllowed"] is False
        row = readiness["assets"][0]
        assert "upload_readiness:forensics" in row["blockingReasons"]
        assert "contentforge_verdict:fail" in row["blockingReasons"]
        assert "exact_render_published" in row["blockingReasons"]
        assert any(reason.endswith("exact_render_published") for reason in readiness["blockingReasons"])

        cf.review_rendered_asset("asset_1", decision="rejected")
        rejected = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert rejected["expectedDraftCount"] == 0
        assert "no_approved_assets" in rejected["blockingReasons"]
    finally:
        cf.close()


def test_export_readiness_warns_on_already_drafted_render(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        rows.append({
            "id": "post_1",
                    "status": "draft",
                    "platform": "instagram",
                    "account_id": None,
                    "instagram_account_id": None,
                    "created_at": "2026-01-03T00:00:00+00:00",
                    "content": "caption",
                    "metadata": {
                        "campaign_factory": {
                    "campaign_id": "may",
                    "source_asset_id": source["id"],
                    "rendered_asset_id": "asset_1",
                    "content_hash": "hash_1",
                    "source_content_hash": source["content_hash"],
                    "caption_hash": "caption_hash_1",
                }
            },
        })
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        add_audit_report(cf, overall_verdict="warn", warnings=["compression"])
        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert readiness["liveExportAllowed"] is True
        row = readiness["assets"][0]
        assert row["state"] == "warning"
        assert "exact_render_already_queued" in row["warnings"]
        assert "contentforge_verdict:warn" in row["warnings"]
        assert "caption_reuse" in row["warnings"]
    finally:
        cf.close()


def test_export_readiness_warns_on_batch_calendar_guardrails(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, first_path = add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        for idx in (2, 3):
            rendered_path = tmp_path / f"ok_{idx}.mp4"
            rendered_path.write_bytes(f"rendered {idx}".encode())
            now = "2026-01-01T00:00:00+00:00"
            cf.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?)
                """,
                (
                    f"asset_{idx}",
                    source["campaign_id"],
                    source["id"],
                    f"hash_{idx}",
                    str(rendered_path),
                    str(rendered_path),
                    rendered_path.name,
                    now,
                    now,
                ),
            )
            cf.conn.commit()
            add_audit_report(cf, rendered_asset_id=f"asset_{idx}", audit_id=f"audit_{idx}")
        readiness = evaluate_export_readiness(cf, campaign_slug="may", user_id="user_1")
        warnings = {warning for row in readiness["assets"] for warning in row["warnings"]}
        assert "account_batch_volume_review" in warnings
        assert "same_caption_in_batch" in warnings
        assert "source_family_batch_volume_review" in warnings
        assert all(isinstance(row["operatorScore"], int) for row in readiness["assets"])
    finally:
        cf.close()


def test_live_export_blocks_same_rendered_asset_to_same_account_batch(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_lola_1",
            planned_window_start="2026-06-05T10:00:00+00:00",
            reason_code="proof_slot_1",
        )
        cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_lola_1",
            planned_window_start="2026-06-06T10:00:00+00:00",
            reason_code="proof_slot_2",
        )

        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            schedule_mode="live",
        )

        assert readiness["liveExportAllowed"] is False
        assert readiness["expectedDraftCount"] == 2
        assert "asset_1:same_rendered_asset_in_account_batch" in readiness["blockingReasons"]
    finally:
        cf.close()


def test_threadsdash_export_preserves_existing_caption_outcome_context_nulls(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="stacey", account_handles=["ig_a"])
        source = cf.assets_for_campaign(cf.campaign_by_slug("may")["id"])[0]
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": "caption_hash_1",
            "caption_text": "caption",
            "caption_bank": "shared_girl_next_door",
            "caption_banks": ["shared_girl_next_door"],
            "creator_mix": "Stacey",
            "creator_model": None,
            "frame_type": "closeup",
            "length_class": "short",
            "format_class": "singleline",
            "caption_fit_version": "v1",
            "suitability_decision": "allowed",
            "suitability_reason": "test",
            "render_recipe": "v01_original",
            "source_clip": "clip_001",
            "rendered_output": str(rendered_path),
        }
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
             caption, recipe, audit_status, review_state, caption_generation_json,
             caption_hash, caption_outcome_context_json, created_at, updated_at)
            VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, 'ok.mp4',
             'caption', 'v01_original', 'approved_candidate', 'approved', '{}',
             'caption_hash_1', ?, ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps(context, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        cf.conn.commit()

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1", rendered_asset_ids=["asset_1"])
        exported_context = payload["drafts"][0]["captionOutcomeContext"]
        metadata_context = payload["drafts"][0]["metadata"]["campaign_factory"]["captionOutcomeContext"]
        assert exported_context == context
        assert metadata_context == context
        assert exported_context["creator_model"] is None
    finally:
        cf.close()


def test_publishability_blocks_passthrough_captioned_media_before_export(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path, filename="proof_v00_passthrough.mp4")
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assert readiness["liveExportAllowed"] is False
        assert readiness["assets"][0]["publishability"]["publishableCandidate"] is False
        assert readiness["assets"][0]["publishability"]["publishability_failure_reasons"] == readiness["assets"][0]["publishability"]["failureReasons"]
        assert "missing_burned_captions" in readiness["assets"][0]["publishability"]["publishability_failure_reasons"]

        with pytest.raises(ValueError, match="export blocked by (publishability|handoff manifest)"):
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=False,
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
            )
    finally:
        cf.close()


def test_publishability_blocks_missing_caption_placement_qc(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        context = json.loads(cf.conn.execute(
            "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
        ).fetchone()[0])
        context.pop("captionPlacementPolicy", None)
        context.pop("captionPlacementDecision", None)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ? WHERE id = 'asset_1'",
            (json.dumps(context, sort_keys=True),),
        )
        cf.conn.commit()

        explanation = cf.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert "caption_placement_qc_failed" in explanation["publishability_failure_reasons"]
        assert explanation["checks"]["caption_placement_qc_passed"] is False
    finally:
        cf.close()


def test_publishability_blocks_failed_caption_placement_qc(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        context = json.loads(cf.conn.execute(
            "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
        ).fetchone()[0])
        context["captionPlacementDecision"] = {
            "status": "failed",
            "selectedLane": "center",
            "reason": "center overlaps face",
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ? WHERE id = 'asset_1'",
            (json.dumps(context, sort_keys=True),),
        )
        cf.conn.commit()

        explanation = cf.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert explanation["captionPlacementPolicy"] == "focal_safe_v1"
        assert explanation["captionPlacementDecision"]["status"] == "failed"
        assert "caption_placement_qc_failed" in explanation["publishability_failure_reasons"]
    finally:
        cf.close()


def test_publishability_blocks_caption_safe_zone_audit_warning(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(
            cf,
            warnings=["Caption-like text may overlap bottom or right-side Reels UI controls"],
            warning_codes=["caption_overlaps_ui_safe_zone"],
        )

        explanation = cf.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert explanation["checks"]["caption_placement_qc_passed"] is False
        assert "caption_placement_qc_failed" in explanation["publishability_failure_reasons"]
    finally:
        cf.close()


def test_publishability_blocks_blank_instagram_post_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": "",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()

        explanation = cf.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert "missing_instagram_post_caption" in explanation["publishability_failure_reasons"]
    finally:
        cf.close()


def test_publishability_blocks_reel_captions_with_dm_or_link_references(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": "DM me for the link",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()

        explanation = cf.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert "unsafe_reel_caption_link_or_dm_reference" in explanation["publishability_failure_reasons"]
        assert explanation["checks"]["reel_caption_account_safety_passed"] is False
        assert {item["reason"] for item in explanation["reelCaptionAccountSafetyViolations"]} == {
            "dm_reference",
            "link_reference",
        }
    finally:
        cf.close()


def test_publishability_blocks_reel_captions_with_text_me_language(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": "too scared to text me",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()

        explanation = cf.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert "unsafe_reel_caption_link_or_dm_reference" in explanation["publishability_failure_reasons"]
        assert explanation["checks"]["reel_caption_account_safety_passed"] is False
        assert {item["reason"] for item in explanation["reelCaptionAccountSafetyViolations"]} == {"dm_reference"}
    finally:
        cf.close()


def test_publishability_blocks_low_quality_instagram_post_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": (
                    "this is a very long caption that should not be used under a Reel because it reads like generated copy "
                    "instead of a simple Instagram caption and it keeps rambling way past the limit"
                ),
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()

        explanation = cf.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert "instagram_post_caption_quality_failed" in explanation["publishability_failure_reasons"]
        assert explanation["checks"]["instagram_post_caption_quality_passed"] is False
        assert explanation["instagramPostCaptionQuality"]["reasons"] == ["instagram_post_caption_too_long"]
    finally:
        cf.close()


def test_caption_quality_repair_plan_is_read_only_and_recovers_long_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        context = json.loads(cf.conn.execute(
            "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
        ).fetchone()[0])
        burned_before = context["caption_text"]
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": (
                    "this caption is too long and keeps going because it is not the simple native style we want "
                    "under Instagram posts when the asset should be safe for scheduling"
                ),
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()
        before = {
            "rendered_assets": table_count(cf, "rendered_assets"),
            "caption_versions": table_count(cf, "caption_versions"),
            "distribution_plans": table_count(cf, "distribution_plans"),
            "total_changes": cf.conn.total_changes,
        }

        plan = cf.caption_quality_repair_plan(creator="Test")

        after_context = json.loads(cf.conn.execute(
            "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
        ).fetchone()[0])
        assert plan["schema"] == "campaign_factory.caption_quality_repair_plan.v1"
        assert plan["wouldWrite"] is False
        assert plan["blockedByCaptionQuality"] == 1
        assert plan["recoverableByCaptionRewrite"] == 1
        assert plan["recoverableByHashtagTrim"] == 0
        assert plan["recoverableByCTARemoval"] == 0
        assert plan["unrecoverable"] == 0
        candidate = plan["replacementCandidates"][0]
        assert candidate["assetId"] == "asset_1"
        assert candidate["recoveryClass"] == "recoverableByCaptionRewrite"
        assert candidate["suggestedInstagramPostCaption"] in core_module.SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL
        assert candidate["wouldPassQualityGate"] is True
        assert candidate["burnedCaptionText"] == burned_before
        assert after_context["caption_text"] == burned_before
        assert {
            "rendered_assets": table_count(cf, "rendered_assets"),
            "caption_versions": table_count(cf, "caption_versions"),
            "distribution_plans": table_count(cf, "distribution_plans"),
            "total_changes": cf.conn.total_changes,
        } == before
    finally:
        cf.close()


def test_caption_quality_repair_plan_classifies_hashtag_and_cta_repairs(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        rendered_path = tmp_path / "asset_2.mp4"
        rendered_path.write_bytes(b"rendered-2")
        context = json.loads(cf.conn.execute(
            "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
        ).fetchone()[0])
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
             caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
             caption_generation_json, created_at, updated_at)
            VALUES ('asset_2', ?, ?, 'hash_2', ?, ?, 'asset_2.mp4', 'caption', 'caption_hash_2',
                    ?, 'v01_original', 'passed', 'approved', '{}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps({**context, "caption_hash": "caption_hash_2"}, sort_keys=True),
            ),
        )
        add_audit_report(cf, rendered_asset_id="asset_2", audit_id="audit_asset_2")
        cf.review_rendered_asset("asset_2", decision="approved")
        common_audio = {
            "schema": "pipeline.audio_intent.v1",
            "mode": "native_platform_audio",
            "required": False,
            "status": "not_required",
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": "pick one\n#one #two #three #four #five #six",
                "hashtags": ["#one", "#two", "#three", "#four", "#five", "#six"],
                "audioIntent": common_audio,
            }),),
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_2'",
            (json.dumps({
                "instagram_post_caption": "DM me for the link",
                "audioIntent": common_audio,
            }),),
        )
        cf.conn.commit()

        plan = cf.caption_quality_repair_plan(creator="Test")
        by_asset = {item["assetId"]: item for item in plan["replacementCandidates"]}

        assert plan["blockedByCaptionQuality"] == 2
        assert plan["recoverableByHashtagTrim"] == 1
        assert plan["recoverableByCTARemoval"] == 1
        assert by_asset["asset_1"]["recoveryClass"] == "recoverableByHashtagTrim"
        assert by_asset["asset_2"]["recoveryClass"] == "recoverableByCTARemoval"
        assert by_asset["asset_1"]["wouldPassQualityGate"] is True
        assert by_asset["asset_2"]["wouldPassQualityGate"] is True
    finally:
        cf.close()


def test_caption_quality_repair_plan_marks_non_caption_blockers_unrecoverable(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        context = json.loads(cf.conn.execute(
            "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
        ).fetchone()[0])
        context.pop("captionPlacementPolicy", None)
        context.pop("captionPlacementDecision", None)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ?, caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(context, sort_keys=True),
                json.dumps({
                    "instagram_post_caption": "DM me for the link",
                    "audioIntent": {
                        "schema": "pipeline.audio_intent.v1",
                        "mode": "native_platform_audio",
                        "required": False,
                        "status": "not_required",
                    },
                }),
            ),
        )
        cf.conn.commit()

        plan = cf.caption_quality_repair_plan(creator="Test")
        candidate = plan["replacementCandidates"][0]

        assert plan["blockedByCaptionQuality"] == 1
        assert plan["unrecoverable"] == 1
        assert candidate["recoveryClass"] == "unrecoverable"
        assert "caption_placement_qc_failed" in candidate["nonCaptionBlockers"]
        assert candidate["wouldPassQualityGate"] is False
    finally:
        cf.close()


def test_caption_quality_repair_plan_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": "DM me for the link",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "caption-quality-repair-plan",
            "--creator",
            "Test",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.caption_quality_repair_plan.v1"
    assert payload["blockedByCaptionQuality"] == 1
    assert payload["replacementCandidates"][0]["wouldWrite"] is False
    assert payload["wouldWrite"] is False


def test_inventory_recovery_report_ranks_repair_classes_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": (
                    "this caption is too long and keeps going because it is not the simple native style we want "
                    "under Instagram posts when the asset should be safe for scheduling"
                ),
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        rendered_path = tmp_path / "asset_operator_audio_preview_test.mp4"
        rendered_path.write_bytes(b"operator-review")
        context = json.loads(cf.conn.execute(
            "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
        ).fetchone()[0])
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
             caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
             caption_generation_json, created_at, updated_at)
            VALUES ('asset_operator', ?, ?, 'hash_operator', ?, ?, 'asset_operator_audio_preview_test.mp4',
                    'caption', 'caption_hash_operator', ?, 'v01_original', 'passed', 'approved',
                    ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps({**context, "caption_hash": "caption_hash_operator"}, sort_keys=True),
                json.dumps({
                    "instagram_post_caption": "new fit today",
                    "audioIntent": {
                        "schema": "pipeline.audio_intent.v1",
                        "mode": "native_platform_audio",
                        "required": False,
                        "status": "not_required",
                    },
                }),
            ),
        )
        add_audit_report(cf, rendered_asset_id="asset_operator", audit_id="audit_operator")
        cf.conn.commit()
        before_changes = cf.conn.total_changes

        report = cf.inventory_recovery_report(creator="Test", content_surface="reel", required_inventory=3)
        by_class = {row["repairClass"]: row for row in report["repairClasses"]}

        assert report["schema"] == "creator_os.inventory_recovery_report.v1"
        assert report["wouldWrite"] is False
        assert report["currentScheduleSafeAssets"] == 0
        assert report["requiredInventory"] == 3
        assert report["shortfall"] == 3
        assert by_class["caption_only"]["blockedAssets"] == 1
        assert by_class["caption_only"]["scheduleSafeAssetsRecoverable"] == 1
        assert by_class["operator_visual_review_required"]["blockedAssets"] == 1
        assert by_class["operator_visual_review_required"]["scheduleSafeAssetsRecoverable"] == 1
        assert report["highestROIRepairClass"] == "caption_only"
        assert report["inventoryGateImpact"]["inventoryAfterTop3Repairs"] == 2
        assert report["inventoryGateImpact"]["wouldPass25AccountGate"] is False
        assert cf.conn.total_changes == before_changes
    finally:
        cf.close()


def test_inventory_recovery_report_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": "DM me for the link",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "inventory-recovery-report",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "3",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.inventory_recovery_report.v1"
    assert payload["successCriteria"]["whyAssetsAreBlocked"] is True
    assert payload["repairClasses"]
    assert payload["wouldWrite"] is False


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
    campaign = cf.campaign_by_slug("may")
    rendered_path = tmp_path / (filename or f"{asset_id}.mp4")
    rendered_path.write_bytes(f"rendered-{asset_id}".encode("utf-8"))
    now = created_at or datetime.now(timezone.utc).isoformat()
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
    return dict(cf.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)).fetchone())


def test_schedule_safe_production_report_measures_fresh_waterfall_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        parent = add_schedule_safe_production_asset(cf, tmp_path, asset_id="parent_fresh", source=source)
        now = datetime.now(timezone.utc).isoformat()
        cf.conn.execute(
            """
            INSERT INTO concepts
            (id, campaign_id, creator, parent_reel_id, parent_asset_id, source_asset_id,
             source_fingerprint, content_fingerprint, caption_hash, audio_id, status, metadata_json, created_at, updated_at)
            VALUES ('concept_prod', ?, 'Test', 'parent_reel_prod', 'parent_fresh', ?,
                    'source_hash_prod', 'hash_parent_fresh', 'caption_hash_parent_fresh', 'audio_prod', 'active', '{}', ?, ?)
            """,
            (parent["campaign_id"], source["id"], now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO caption_families
            (id, campaign_id, concept_id, parent_reel_id, parent_asset_id, creator, requested_count, style, status, metadata_json, created_at, updated_at)
            VALUES ('cfam_prod', ?, ?, ?, 'parent_fresh', 'Test', 3, 'ig_short', 'active', '{}', ?, ?)
            """,
            (parent["campaign_id"], "concept_prod", "parent_reel_prod", now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO caption_versions
            (id, caption_family_id, campaign_id, concept_id, parent_reel_id, parent_asset_id,
             caption_family_index, burned_caption_text, burned_caption_hash, instagram_post_caption,
             instagram_post_caption_hash, caption_angle, status, created_at, updated_at)
            VALUES
            ('cver_prod_1', 'cfam_prod', ?, ?, ?, 'parent_fresh', 0, 'caption', 'caption_hash_prod_1', 'new fit today', 'post_hash_1', 'soft_cta', 'active', ?, ?),
            ('cver_prod_2', 'cfam_prod', ?, ?, ?, 'parent_fresh', 1, 'caption', 'caption_hash_prod_2', 'mirror check', 'post_hash_2', 'soft_cta', 'active', ?, ?)
            """,
            (
                parent["campaign_id"], "concept_prod", "parent_reel_prod", now, now,
                parent["campaign_id"], "concept_prod", "parent_reel_prod", now, now,
            ),
        )
        add_schedule_safe_production_asset(cf, tmp_path, asset_id="variant_pass", source=source, parent_asset_id="parent_fresh")
        ensure_exportable_distribution_plan(cf, "variant_pass")
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="variant_visual_fail",
            source=source,
            parent_asset_id="parent_fresh",
            filename="variant_audio_preview_fail.mp4",
        )
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="variant_caption_quality_fail",
            source=source,
            parent_asset_id="parent_fresh",
            caption_generation={
                "instagram_post_caption": "this caption is too long and keeps going because it is not the simple native style we want under Instagram posts when the asset should be safe for scheduling and it keeps adding more unnecessary words",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            },
        )
        old_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="variant_old_outside_window",
            source=source,
            parent_asset_id="parent_fresh",
            created_at=old_time,
        )
        ensure_exportable_distribution_plan(cf, "variant_old_outside_window")
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.schedule_safe_production_report(
            creator="Test",
            content_surface="reel",
            lookback_days=1,
            required_inventory=225,
            current_inventory=11,
        )
        summary = report["waterfallSummary"]

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.schedule_safe_production_report.v1"
        assert summary["rawParents"] == 1
        assert summary["acceptedParents"] == 1
        assert summary["captionFamilies"] == 1
        assert summary["captionFamiliesAccepted"] == 1
        assert summary["variantsCreated"] == 3
        assert summary["visualQcPassed"] == 2
        assert summary["captionQualityPassed"] == 1
        assert summary["scheduleSafeAssets"] == 1
        assert report["scheduleSafeAssetsProducedPerDay"] == 1.0
        assert report["currentInventory"] == 11
        assert report["daysToReach25AccountBuffer"] == 214
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_schedule_safe_production_report_uses_variant_parent_cohort_for_old_parent_lineage(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        old_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        parent = add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="parent_old",
            source=source,
            created_at=old_time,
        )
        now = datetime.now(timezone.utc).isoformat()
        cf.conn.execute(
            """
            INSERT INTO concepts
            (id, campaign_id, creator, parent_reel_id, parent_asset_id, source_asset_id,
             source_fingerprint, content_fingerprint, caption_hash, audio_id, status, metadata_json, created_at, updated_at)
            VALUES ('concept_old_lineage', ?, 'Test', 'parent_reel_old', 'parent_old', ?,
                    'source_hash_old', 'hash_parent_old', 'caption_hash_parent_old', 'audio_old', 'active', '{}', ?, ?)
            """,
            (parent["campaign_id"], source["id"], old_time, old_time),
        )
        cf.conn.execute(
            """
            INSERT INTO caption_families
            (id, campaign_id, concept_id, parent_reel_id, parent_asset_id, creator, requested_count, style, status, metadata_json, created_at, updated_at)
            VALUES ('cfam_old_lineage', ?, 'concept_old_lineage', 'parent_reel_old', 'parent_old', 'Test', 3, 'ig_short', 'active', '{}', ?, ?)
            """,
            (parent["campaign_id"], old_time, old_time),
        )
        cf.conn.execute(
            """
            INSERT INTO caption_versions
            (id, caption_family_id, campaign_id, concept_id, parent_reel_id, parent_asset_id,
             caption_family_index, burned_caption_text, burned_caption_hash, instagram_post_caption,
             instagram_post_caption_hash, caption_angle, status, created_at, updated_at)
            VALUES ('cver_old_lineage', 'cfam_old_lineage', ?, 'concept_old_lineage', 'parent_reel_old',
                    'parent_old', 0, 'caption', 'caption_hash_old', 'new fit today', 'post_hash_old',
                    'soft_cta', 'active', ?, ?)
            """,
            (parent["campaign_id"], old_time, old_time),
        )
        add_schedule_safe_production_asset(cf, tmp_path, asset_id="variant_fresh_from_old_parent", source=source, parent_asset_id="parent_old", created_at=now)
        ensure_exportable_distribution_plan(cf, "variant_fresh_from_old_parent")
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.schedule_safe_production_report(
            creator="Test",
            content_surface="reel",
            lookback_days=1,
            required_inventory=225,
            current_inventory=11,
        )

        assert cf.conn.total_changes == before
        assert report["waterfallSummary"]["rawParents"] == 1
        assert report["waterfallSummary"]["captionFamilies"] == 1
        assert report["metadataGapCounts"]["parentsMissingCaptionFamily"] == 0
        assert report["measurementWarnings"] == []
        assert report["largestProductionLoss"]["largestLossGate"] != "caption_families_created"
        assert "productionLossesOnly" in report
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_schedule_safe_production_report_classifies_missing_caption_family_as_lineage_gap(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        old_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="parent_without_family",
            source=source,
            created_at=old_time,
        )
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="variant_fresh_without_family",
            source=source,
            parent_asset_id="parent_without_family",
        )
        ensure_exportable_distribution_plan(cf, "variant_fresh_without_family")
        cf.conn.commit()

        report = cf.schedule_safe_production_report(
            creator="Test",
            content_surface="reel",
            lookback_days=1,
            required_inventory=225,
            current_inventory=11,
        )

        assert report["metadataGapCounts"]["parentsMissingCaptionFamily"] == 1
        assert "lineage_metadata_gap:caption_families_missing_for_variant_parent_cohort" in report["measurementWarnings"]
        assert report["largestProductionLoss"]["largestLossGate"] != "caption_families_created"
        assert all(row["stage"] != "caption_families_created" for row in report["productionLossesOnly"])
        assert report["lineageCompletenessPct"] < 100
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_schedule_safe_production_capacity_zero_production_is_blocked(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        report = cf.schedule_safe_production_capacity_model(
            creator="Test",
            content_surface="reel",
            lookback_days=1,
            required_inventory=225,
            current_inventory=11,
        )

        assert report["schema"] == "creator_os.schedule_safe_production_capacity_model.v1"
        assert report["scheduleSafeAssetsProducedPerDay"] == 0
        assert report["daysToReach25AccountBuffer"] is None
        assert report["capacityProjections"]["25Accounts"]["blockedReason"] == "no_schedule_safe_production_observed"
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_schedule_safe_production_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "schedule-safe-production-report",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "225",
            "--current-inventory",
            "11",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.schedule_safe_production_report.v1"
    assert payload["requiredFor25Accounts"] == 225
    assert payload["currentInventory"] == 11
    assert payload["wouldWrite"] is False


def test_contentforge_visual_qc_failure_report_classifies_operator_review_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        add_schedule_safe_production_asset(cf, tmp_path, asset_id="parent_fresh", source=source)
        add_schedule_safe_production_asset(cf, tmp_path, asset_id="variant_pass", source=source, parent_asset_id="parent_fresh")
        ensure_exportable_distribution_plan(cf, "variant_pass")
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="variant_operator_review",
            source=source,
            parent_asset_id="parent_fresh",
            filename="variant_audio_preview_review.mp4",
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.contentforge_visual_qc_failure_report(
            creator="Test",
            content_surface="reel",
            lookback_days=1,
            current_inventory=11,
            required_inventory=225,
        )
        by_category = {row["failureCategory"]: row for row in report["failureCategories"]}

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.contentforge_visual_qc_failure_report.v1"
        assert report["variantsAnalyzed"] == 2
        assert report["visualQcFailed"] == 1
        assert by_category["operator_visual_review_required"]["count"] == 1
        assert by_category["operator_visual_review_required"]["repairable"] is True
        assert report["largestVisualQCLoss"]["largestFailureCategory"] == "operator_visual_review_required"
        assert report["recoveryProjection"]["inventoryRecoveredIfTopVisualIssueFixed"] == 1
        assert report["recoveryProjection"]["remainingGap"] == 213
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_contentforge_visual_qc_reports_zero_failure_window(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        report = cf.contentforge_visual_qc_waterfall(
            creator="Test",
            content_surface="reel",
            lookback_days=1,
            current_inventory=11,
            required_inventory=225,
        )

        assert report["schema"] == "creator_os.contentforge_visual_qc_waterfall.v1"
        assert report["waterfall"]["variantsCreated"] == 0
        assert report["waterfall"]["visualQcFailed"] == 0
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_contentforge_visual_qc_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "contentforge-visual-qc-master-report",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--current-inventory",
            "11",
            "--required-inventory",
            "225",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.contentforge_visual_qc_master_report.v1"
    assert payload["recoveryProjection"]["currentScheduleSafeAssets"] == 11
    assert payload["recoveryProjection"]["requiredFor25Accounts"] == 225
    assert payload["wouldWrite"] is False


def test_multi_blocker_inventory_unlock_report_finds_combined_repairs_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        add_schedule_safe_production_asset(cf, tmp_path, asset_id="asset_single_caption", source=source)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_single_caption'",
            (json.dumps({
                "instagram_post_caption": "this caption is too long and keeps going because it is not the simple native style we want under Instagram posts when the asset should be safe for scheduling and it keeps adding more unnecessary words",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="asset_combo",
            source=source,
            filename="asset_combo_audio_preview_test.mp4",
            caption_generation={
                "instagram_post_caption": "this caption is too long and keeps going because it is not the simple native style we want under Instagram posts when the asset should be safe for scheduling and it keeps adding more unnecessary words",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            },
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.multi_blocker_inventory_unlock_report(
            creator="Test",
            content_surface="reel",
            required_inventory=3,
            current_inventory=0,
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.multi_blocker_inventory_unlock_report.v1"
        assert report["currentScheduleSafeAssets"] == 0
        assert report["shortfall"] == 3
        assert report["bestSingleRepair"]["repairClass"] == "instagram_post_caption_quality_failed"
        assert report["bestSingleRepair"]["assetsUnlocked"] == 1
        assert set(report["bestTwoRepairCombo"]["repairClasses"]) == {
            "operator_visual_review_required",
            "instagram_post_caption_quality_failed",
        }
        assert report["bestTwoRepairCombo"]["assetsUnlocked"] == 2
        assert report["minimalFixSetFor25Accounts"]["assetsUnlocked"] == 2
        assert report["minimalFixSetFor25Accounts"]["wouldPass25Gate"] is False
        assert report["stillNeedsNewProduction"] is True
        assert report["newProductionAssetsRequired"] == 1
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_multi_blocker_inventory_unlock_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "inventory-unlock-master-report",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "225",
            "--current-inventory",
            "11",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.inventory_unlock_master_report.v1"
    assert payload["currentScheduleSafeAssets"] == 11
    assert payload["requiredFor25Accounts"] == 225
    assert payload["wouldWrite"] is False


def test_operator_inventory_review_batch_plan_prioritizes_safe_repairs_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="asset_safe_combo",
            source=source,
            filename="asset_safe_combo_audio_preview_test.mp4",
            caption_generation={
                "instagram_post_caption": "this caption is too long and keeps going because it is not the simple native style we want under Instagram posts when the asset should be safe for scheduling and it keeps adding more unnecessary words",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            },
        )
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="asset_wrong_visual",
            source=source,
            filename="asset_wrong_visual_passthrough.mp4",
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        plan = cf.operator_inventory_review_batch_plan(
            creator="Test",
            content_surface="reel",
            required_inventory=2,
            current_inventory=0,
            target_unlock=1,
        )

        assert cf.conn.total_changes == before
        assert plan["schema"] == "creator_os.operator_inventory_review_batch_plan.v1"
        assert plan["reviewCandidates"] == 1
        assert plan["recommendedReviewBatchSize"] == 1
        assert plan["reviewBatch"][0]["assetId"] == "asset_safe_combo"
        assert "asset_wrong_visual" not in {row["assetId"] for row in plan["reviewBatch"]}
        assert plan["estimatedInventoryGain"] == 1
        assert plan["safeRepairsOnly"] is True
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_operator_inventory_review_batch_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "operator-inventory-review-batch-summary",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "225",
            "--current-inventory",
            "11",
            "--target-unlock",
            "10",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.operator_inventory_review_batch_summary.v1"
    assert payload["targetUnlock"] == 10
    assert payload["safeRepairsOnly"] is True
    assert payload["wouldWrite"] is False


def test_operator_review_simulator_models_approval_rates_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        for index in range(4):
            add_schedule_safe_production_asset(
                cf,
                tmp_path,
                asset_id=f"asset_caption_{index}",
                source=source,
                caption_generation={
                    "instagram_post_caption": "this caption is too long and keeps going because it is not the simple native style we want under Instagram posts when the asset should be safe for scheduling and it keeps adding more unnecessary words",
                    "audioIntent": {
                        "schema": "pipeline.audio_intent.v1",
                        "mode": "native_platform_audio",
                        "required": False,
                        "status": "not_required",
                    },
                },
            )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.operator_review_simulator(
            creator="Test",
            content_surface="reel",
            required_inventory=4,
            current_inventory=0,
        )
        scenarios = {row["approvalRate"]: row for row in report["scenarios"]}

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.operator_review_simulator.v1"
        assert scenarios[50]["assetsReviewed"] == 4
        assert scenarios[50]["assetsRecovered"] == 2
        assert scenarios[50]["passes25AccountGate"] is False
        assert scenarios[100]["assetsRecovered"] == 4
        assert scenarios[100]["passes25AccountGate"] is True
        assert report["minimumAssetsReviewedToPass25Gate"] == 4
        assert report["minimumOperatorMinutesToPass25Gate"] == 8
        assert report["highestROIBatchType"] == "caption_only"
        assert report["lowestRiskBatchType"] == "caption_only"
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_operator_review_simulator_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "operator-review-minimum-certification-path",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "225",
            "--current-inventory",
            "11",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.operator_review_minimum_certification_path.v1"
    assert "minimumOperatorMinutesToPass25Gate" in payload
    assert payload["wouldWrite"] is False


def test_fresh_schedule_safe_production_plan_calculates_reel_only_buffer_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        report = cf.fresh_schedule_safe_production_plan(
            creator="Stacey",
            target_schedule_safe_inventory=270,
            current_inventory=11,
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.fresh_schedule_safe_production_plan.v1"
        assert report["contentSurface"] == "reel"
        assert report["reelsOnly"] is True
        assert report["targetScheduleSafeInventory"] == 270
        assert report["currentScheduleSafeInventory"] == 11
        assert report["freshScheduleSafeAssetsNeeded"] == 259
        assert report["expectedYield"] == 68.1
        assert report["parentsNeeded"] == 26
        assert report["captionFamiliesNeeded"] == 26
        assert report["captionVersionsNeeded"] == 130
        assert report["variantsNeeded"] == 381
        assert report["rawParentCandidatesNeeded"] == 32
        assert report["batchesRequired"] == 3
        assert report["executionBatches"][0]["gatesToVerify"] == [
            "discoverability_generation_gate",
            "visual_qc",
            "caption_placement_qc",
            "instagram_post_caption_quality",
            "publishability",
            "handoff_manifest",
        ]
        assert report["largestProductionRisk"] == "variant_to_schedule_safe_yield_not_yet_proven"
        assert report["downstreamYieldEvidenceStatus"] == "insufficient_schedule_safe_variant_production_evidence"
        assert report["yieldSource"] == "conservative_default"
        assert report["sampleSize"] == 0
        assert report["confidence"] == "low"
        assert report["recommendedBatchCount"] == report["batchesRequired"]
        assert report["stopAfterEachBatchForGateCheck"] is True
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_fresh_schedule_safe_production_plan_uses_measured_recent_yield_when_sample_is_adequate(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        parent = add_schedule_safe_production_asset(cf, tmp_path, asset_id="parent_measured_recent", source=source)
        now = datetime.now(timezone.utc).isoformat()
        cf.conn.execute(
            """
            INSERT INTO concepts
            (id, campaign_id, creator, parent_reel_id, parent_asset_id, source_asset_id,
             source_fingerprint, content_fingerprint, caption_hash, audio_id, status, metadata_json, created_at, updated_at)
            VALUES ('concept_measured_recent', ?, 'Stacey', 'parent_reel_measured_recent',
                    'parent_measured_recent', ?, 'source_hash_measured_recent',
                    'hash_parent_measured_recent', 'caption_hash_parent_measured_recent',
                    'audio_measured_recent', 'active', '{}', ?, ?)
            """,
            (parent["campaign_id"], source["id"], now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO caption_families
            (id, campaign_id, concept_id, parent_reel_id, parent_asset_id, creator, requested_count, style, status, metadata_json, created_at, updated_at)
            VALUES ('cfam_measured_recent', ?, 'concept_measured_recent',
                    'parent_reel_measured_recent', 'parent_measured_recent',
                    'Stacey', 3, 'ig_short', 'active', '{}', ?, ?)
            """,
            (parent["campaign_id"], now, now),
        )
        cf.conn.execute(
            """
            INSERT INTO caption_versions
            (id, caption_family_id, campaign_id, concept_id, parent_reel_id, parent_asset_id,
             caption_family_index, burned_caption_text, burned_caption_hash, instagram_post_caption,
             instagram_post_caption_hash, caption_angle, status, created_at, updated_at)
            VALUES ('cver_measured_recent', 'cfam_measured_recent', ?,
                    'concept_measured_recent', 'parent_reel_measured_recent',
                    'parent_measured_recent', 0, 'caption', 'caption_hash_measured_recent',
                    'new fit today', 'post_hash_measured_recent', 'soft_cta',
                    'active', ?, ?)
            """,
            (parent["campaign_id"], now, now),
        )
        for index in range(30):
            asset_id = f"variant_measured_recent_{index}"
            add_schedule_safe_production_asset(
                cf,
                tmp_path,
                asset_id=asset_id,
                source=source,
                parent_asset_id="parent_measured_recent",
            )
            if index < 15:
                ensure_exportable_distribution_plan(cf, asset_id)
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.fresh_schedule_safe_production_plan(
            creator="Test",
            target_schedule_safe_inventory=111,
            current_inventory=11,
        )

        assert cf.conn.total_changes == before
        assert report["yieldSource"] == "measured_recent"
        assert report["sampleSize"] == 30
        assert report["confidence"] == "medium"
        assert report["expectedYield"] == 50.0
        assert report["freshScheduleSafeAssetsNeeded"] == 100
        assert report["variantsNeeded"] == 200
        assert report["parentsNeeded"] == 14
        assert report["recommendedBatchCount"] == report["batchesRequired"]
        assert report["stopAfterEachBatchForGateCheck"] is True
        assert report["measuredRecentYield"]["variantsCreated"] == 30
        assert report["measuredRecentYield"]["scheduleSafeAssets"] == 15
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_fresh_reel_production_capacity_plan_exposes_conservative_scenario(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        report = cf.fresh_reel_production_capacity_plan(
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


def test_fresh_schedule_safe_production_plan_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "fresh-schedule-safe-production-plan",
            "--creator",
            "Stacey",
            "--current-inventory",
            "11",
            "--target-schedule-safe-inventory",
            "270",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.fresh_schedule_safe_production_plan.v1"
    assert payload["freshScheduleSafeAssetsNeeded"] == 259
    assert payload["parentsNeeded"] == 26
    assert payload["wouldWrite"] is False


def test_creator_os_50_account_readiness_alias_is_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        report = cf.creator_os_50_account_readiness(content_surface="reel")

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.50_account_readiness.v1"
        assert report["targetStage"] == 50
        assert report["contentSurface"] == "reel"
        assert report["requiredInventory"] == 450
        assert report["shortfall"] == max(0, report["requiredInventory"] - report["availableInventory"])
        assert "inventory_buffer_not_maintained" in report["blockingReasons"]
        assert report["recommendedNextAction"] == "produce_fresh_schedule_safe_reels"
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_50_account_readiness_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "50-account-readiness",
            "--content-surface",
            "reel",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.50_account_readiness.v1"
    assert payload["targetStage"] == 50
    assert payload["contentSurface"] == "reel"
    assert payload["wouldWrite"] is False


def test_handoff_manifest_preserves_distinct_instagram_post_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "instagram_post_caption": "new post is up",
                "caption_cta": "go watch",
                "hashtags": ["#stacey", "mirror fit", "#reels"],
                "post_caption_style": "short_natural",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")

        explanation = cf.explain_publishability("asset_1", distribution_plan_id=plan["id"])
        manifest = explanation["handoff_manifest"]

        assert explanation["publishableCandidate"] is True
        assert manifest["burned_caption_text"] == "caption"
        assert manifest["instagram_post_caption"] == "new post is up\ngo watch\n#stacey #mirrorfit #reels"
        assert manifest["instagram_post_caption_hash"] == threadsdash_adapter._text_hash(manifest["instagram_post_caption"])
        assert manifest["post_caption_style"] == "short_natural"
    finally:
        cf.close()


def test_publishability_blocks_embedded_audio_claim_when_mp4_has_no_audio(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": True,
                    "status": "attached",
                    "operator_selection": {
                        "audio_id": "cml_insomniac_ella_boh",
                        "track_id": "cml_insomniac_ella_boh",
                        "track_name": "iNSOMNiAC",
                        "selected_at": "2026-06-06T04:31:02+00:00",
                        "attached_at": "2026-06-06T04:31:02+00:00",
                        "source": "tiktok_cml",
                        "notes": "Audio is embedded in the registered MP4.",
                    },
                }
            }),),
        )
        cf.conn.commit()
        monkeypatch.setattr(core_module, "probe_video_metadata", lambda path: {"ok": True, "audioPresent": False})

        explanation = cf.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert explanation["checks"]["embedded_audio_verified"] is False
        assert "embedded_audio_missing" in explanation["publishability_failure_reasons"]
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

        result = cf.register_finished_video(
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


def test_register_finished_video_can_keep_post_caption_separate_from_burned_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        video = tmp_path / "finished_captioned.mp4"
        video.write_bytes(b"fake mp4 bytes")

        result = cf.register_finished_video(
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


def test_register_finished_video_blocks_unsafe_caption_before_registration(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        video = tmp_path / "finished_unsafe_caption.mp4"
        video.write_bytes(b"fake mp4 bytes")
        before_rendered = cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"]
        before_sources = cf.conn.execute("SELECT COUNT(*) AS c FROM source_assets").fetchone()["c"]
        before_jobs = cf.conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"]

        result = cf.register_finished_video(
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
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"] == before_rendered
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM source_assets").fetchone()["c"] == before_sources
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"] == before_jobs
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
        cf.import_folder(
            source_dir,
            campaign_slug="stacey_archive_marketing_20260606",
            model_slug="stacey",
            platform="instagram",
        )
        before_jobs = cf.conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"]

        result = cf.prepare_reel_inputs(
            campaign_slug="stacey_archive_marketing_20260606",
            hooks=["DM me for more"],
            force_new=True,
        )

        assert result["canProceed"] is False
        assert result["blockedAt"] == "discoverability_generation_gate"
        assert result["prepared"] == []
        assert result["rejectionEvidenceCapture"]["capturedCount"] >= 1
        assert cf.conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"] == before_jobs
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
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()

        parent = cf.register_parent_reel("asset_1", operator="tester")

        assert parent["schema"] == "campaign_factory.parent_reel.v1"
        assert parent["parentReelId"].startswith("parent_")
        assert parent["conceptId"].startswith("concept_")
        assert parent["parentAssetId"] == "asset_1"
        row = cf.conn.execute("SELECT * FROM concepts WHERE id = ?", (parent["conceptId"],)).fetchone()
        assert row["parent_asset_id"] == "asset_1"
        assert row["content_fingerprint"] == "hash_1"
    finally:
        cf.close()


def test_register_parent_reel_captures_rejection_evidence_before_blocking(tmp_path: Path):
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
                json.dumps({
                    "caption_text": "link in bio",
                    "burned_caption_text": "link in bio",
                    "instagram_post_caption": "link in bio",
                    "caption_hash": "caption_hash_1",
                    "captionPlacementDecision": {"status": "passed"},
                }),
            ),
        )
        cf.conn.commit()

        with pytest.raises(ValueError, match="publishable_candidate"):
            cf.register_parent_reel("asset_1", operator="tester")

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
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        cf.register_parent_reel("asset_1", operator="tester")

        result = cf.variant_plan(parent_asset_id="asset_1", count=3, contentforge_preset="caption_safe")

        assert result["schema"] == "campaign_factory.variant_plan.v1"
        assert result["parentAssetId"] == "asset_1"
        assert result["requestedVariants"] == 3
        assert result["canGenerate"] is True
        assert result["wouldWrite"] is False
        assert result["variantFamilyId"].startswith("vfam_")
        assert [item["variantIndex"] for item in result["plannedOperations"]] == [1, 2, 3]
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0] == 0
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_variant_plan_accepts_caption_safe_v2(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        cf.register_parent_reel("asset_1", operator="tester")

        result = cf.variant_plan(parent_asset_id="asset_1", count=12, contentforge_preset="caption_safe_v2")

        assert result["contentforgePreset"] == "caption_safe_v2"
        assert result["canGenerate"] is True
        assert result["plannedOperations"][0]["operationSet"] == "caption_safe_v2"
    finally:
        cf.close()


def test_generate_variants_accepts_contentforge_v2_pack(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        cf.register_parent_reel("asset_1", operator="tester")
        output_dir = tmp_path / "contentforge_out"
        output_dir.mkdir()
        (output_dir / "variant_001.mp4").write_bytes(b"variant-one")
        (output_dir / "variant_002.mp4").write_bytes(b"variant-two")
        report = {
            "schema": "contentforge.variant_pack.v2",
            "runId": "cf_run_v2",
            "manifestPath": str(output_dir / "variant_pack.json"),
            "outputDir": str(output_dir),
            "results": [
                {
                    "file": "variant_001.mp4",
                    "uploadReady": True,
                    "recommended": True,
                    "familyName": "cover_frame",
                    "variantFamilyRecipe": {"familyName": "cover_frame", "profile": "early_hook"},
                    "operationSet": "caption_safe_v2",
                    "operationSignals": {"coverFrameDifferent": True},
                    "qualityScore": 95,
                    "operationDiversityScore": 33,
                },
                {
                    "file": "variant_002.mp4",
                    "uploadReady": True,
                    "recommended": False,
                    "familyName": "generic_variant",
                },
            ],
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(report).encode("utf-8")

        monkeypatch.setattr(core_module, "urlopen", lambda *_args, **_kwargs: FakeResponse())

        result = cf.generate_variants(
            parent_asset_id="asset_1",
            count=2,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
        )

        assert result["status"] == "completed"
        assert result["contentforgeReport"]["schema"] == "contentforge.variant_pack.v2"
        assert result["contentforgeReport"]["recommendedCount"] == 1
        assert len(result["registeredVariants"]) == 1
        operations = result["registeredVariants"][0]["variantOperations"]
        assert operations[0]["preset"] == "caption_safe_v2"
        assert operations[1]["result"]["familyName"] == "cover_frame"
        publishability = cf.explain_publishability(result["registeredVariants"][0]["variantAssetId"])
        assert publishability["publishableCandidate"] is True
        assert publishability["checks"]["readiness_checks_pass"] is True
    finally:
        cf.close()


def test_variant_lineage_is_added_to_publishability_and_handoff_manifest(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        parent = cf.register_parent_reel("asset_1", operator="tester")
        variant = cf.register_variant_asset(
            parent_asset_id="asset_1",
            variant_asset_id="asset_1",
            variant_family_id="vfam_test",
            variant_index=1,
            operations=[{"type": "caption_safe", "preset": "caption_safe"}],
            contentforge_run_id="cf_run_1",
        )
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")

        publishability = cf.explain_publishability("asset_1", distribution_plan_id=plan["id"])

        assert variant["variantId"].startswith("var_")
        assert publishability["conceptId"] == parent["conceptId"]
        assert publishability["variantFamilyId"] == "vfam_test"
        assert publishability["variantId"] == variant["variantId"]
        manifest = publishability["handoff_manifest"]
        assert manifest["concept_id"] == parent["conceptId"]
        assert manifest["variant_family_id"] == "vfam_test"
        assert manifest["variant_id"] == variant["variantId"]
        context = publishability["captionOutcomeContext"]
        assert context["concept_id"] == parent["conceptId"]
        assert context["variant_family_id"] == "vfam_test"
    finally:
        cf.close()


def test_threadsdash_insert_preserves_variant_first_class_columns():
    inserted: list[tuple[str, dict]] = []

    class FakeClient:
        def insert_with_fallback(self, table, row, fallback_remove):
            inserted.append((table, dict(row)))
            return {"id": "post_1", **row}

    draft = {
        "userId": "user_1",
        "instagramAccountId": "ig_1",
        "content": "caption",
        "topics": [],
        "status": "draft",
        "renderedAssetId": "asset_variant_1",
        "distributionPlanId": "dist_1",
        "campaignFactoryPostKey": "post_key_1",
        "captionHash": "caption_hash_1",
        "media": [{"type": "video"}],
        "metadata": {
            "campaign_factory": {
                "content_fingerprint": "content_hash_1",
                "concept_id": "concept_1",
                "parent_asset_id": "asset_parent_1",
                "variant_family_id": "vfam_1",
                "variant_id": "var_1",
            }
        },
    }

    threadsdash_adapter._insert_draft_post(FakeClient(), draft=draft, media_ref={"publicUrl": "https://cdn.example/video.mp4"})

    post_row = inserted[0][1]
    assert post_row["campaign_factory_content_fingerprint"] == "content_hash_1"
    assert post_row["campaign_factory_concept_id"] == "concept_1"
    assert post_row["campaign_factory_parent_asset_id"] == "asset_parent_1"
    assert post_row["campaign_factory_variant_family_id"] == "vfam_1"
    assert post_row["campaign_factory_variant_id"] == "var_1"


def test_threadsdash_insert_preserves_feed_single_surface():
    inserted: list[tuple[str, dict]] = []

    class FakeClient:
        def insert_with_fallback(self, table, row, fallback_remove):
            inserted.append((table, dict(row)))
            return {"id": "post_feed_1", **row}

    draft = {
        "userId": "user_1",
        "instagramAccountId": "ig_1",
        "content": "feed caption",
        "topics": [],
        "status": "draft",
        "contentSurface": "feed_single",
        "renderedAssetId": "asset_feed_1",
        "distributionPlanId": "dist_feed_1",
        "campaignFactoryPostKey": "post_key_feed_1",
        "captionHash": "caption_hash_feed_1",
        "media": [{"type": "image"}],
        "metadata": {
            "campaign_factory": {
                "content_surface": "feed_single",
                "ig_media_type": "IMAGE",
                "content_fingerprint": "content_hash_feed_1",
            }
        },
    }

    threadsdash_adapter._insert_draft_post(FakeClient(), draft=draft, media_ref={"publicUrl": "https://cdn.example/feed.jpg"})

    post_row = inserted[0][1]
    assert post_row["media_type"] == "image"
    assert post_row["ig_media_type"] == "IMAGE"
    assert post_row["content_surface"] == "feed_single"


def test_variant_metrics_rollup_groups_by_parent_family_and_variant(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        parent = cf.register_parent_reel("asset_1", operator="tester")
        variant = cf.register_variant_asset(
            parent_asset_id="asset_1",
            variant_asset_id="asset_1",
            variant_family_id="vfam_test",
            variant_index=1,
            operations=[{"type": "caption_safe"}],
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
             post_id, platform, status, instagram_account_id, snapshot_at, views, likes,
             comments, shares, saves, reach, metrics_eligible, concept_id, parent_reel_id,
             variant_family_id, variant_id, audio_id, created_at)
            VALUES ('perf_variant_1', ?, 'asset_1', ?, 'hash_1', 'caption_hash_1',
             'post_variant_1', 'instagram', 'published', 'ig_1', '2026-01-02T00:00:00+00:00',
             100, 10, 2, 3, 4, 90, 1, ?, ?, 'vfam_test', ?, 'audio_1', '2026-01-02T00:00:00+00:00')
            """,
            (
                cf.rendered_asset("asset_1")["campaign_id"],
                cf.rendered_asset("asset_1")["source_asset_id"],
                parent["conceptId"],
                parent["parentReelId"],
                variant["variantId"],
            ),
        )
        cf.conn.commit()

        report = cf.variant_metrics_rollup("may")

        assert report["summary"]["variantsPosted"] == 1
        assert report["summary"]["accountsReached"] == 1
        assert report["summary"]["totalViews"] == 100
        assert report["parents"][0]["parentReelId"] == parent["parentReelId"]
        assert report["families"][0]["variantFamilyId"] == "vfam_test"
        assert report["variants"][0]["variantId"] == variant["variantId"]
    finally:
        cf.close()


def test_winner_registry_remembers_why_winners_won_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        parent = cf.register_parent_reel("asset_1", operator="tester")
        cf.conn.execute(
            "UPDATE concepts SET creator = 'Stacey', metadata_json = ? WHERE id = ?",
            (json.dumps({"conceptName": "mirror selfie"}), parent["conceptId"]),
        )
        campaign_id = cf.rendered_asset("asset_1")["campaign_id"]
        source_asset_id = cf.rendered_asset("asset_1")["source_asset_id"]
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
             caption_angle, post_id, platform, status, instagram_account_id, published_at,
             snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible,
             concept_id, parent_reel_id, variant_family_id, variant_id, audio_id, creator_mix,
             created_at, raw_json)
            VALUES ('perf_memory_winner', ?, 'asset_1', ?, 'hash_1', 'caption_hash_1',
             'tease', 'post_memory_winner', 'instagram', 'published', 'ig_1',
             '2026-06-06T18:12:00+00:00', '2026-06-06T20:00:00+00:00',
             12000, 700, 40, 80, 100, 11000, 1, ?, ?, 'vfam_memory', 'variant_memory',
             'audio_12', 'Stacey', '2026-06-06T20:00:00+00:00',
             '{"followers": 12, "onlyfansRevenue": 999999}')
            """,
            (campaign_id, source_asset_id, parent["conceptId"], parent["parentReelId"]),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.winner_registry(creator="Stacey", min_views=1000)

        assert report["schema"] == "campaign_factory.winner_registry.v1"
        assert report["creator"] == "Stacey"
        assert report["wouldWrite"] is False
        assert cf.conn.total_changes == before
        assert report["summary"]["winnerCount"] == 1
        winner = report["winners"][0]
        assert winner["postId"] == "post_memory_winner"
        assert winner["reason"] == "high_views"
        assert winner["why"]["primaryMetric"] == "views"
        assert winner["conceptName"] == "mirror selfie"
        assert winner["audioId"] == "audio_12"
        assert winner["captionAngle"] == "tease"
        assert winner["postingWindow"] == "6pm"
        assert "onlyfans" not in json.dumps(report).lower()
    finally:
        cf.close()


def test_winner_patterns_rolls_up_top_concepts_audio_captions_and_windows(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        campaign_id = cf.rendered_asset("asset_1")["campaign_id"]
        source_asset_id = cf.rendered_asset("asset_1")["source_asset_id"]
        asset_2_path = tmp_path / "asset_2.mp4"
        asset_2_path.write_bytes(b"rendered-2")
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
             caption, caption_hash, created_at, updated_at)
            VALUES ('asset_2', ?, ?, 'hash_2', ?, ?, 'asset_2.mp4',
                    'caption 2', 'caption_hash_2',
                    '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
            """,
            (campaign_id, source_asset_id, str(asset_2_path), str(asset_2_path)),
        )
        concept_rows = [
            ("concept_mirror", "parent_mirror", "asset_1", "mirror selfie"),
            ("concept_gym", "parent_gym", "asset_2", "gym mirror"),
        ]
        for concept_id, parent_reel_id, parent_asset_id, name in concept_rows:
            cf.conn.execute(
                """
                INSERT OR REPLACE INTO concepts
                (id, campaign_id, creator, parent_reel_id, parent_asset_id, source_asset_id,
                 source_fingerprint, content_fingerprint, caption_hash, audio_id, status,
                 metadata_json, created_at, updated_at)
                VALUES (?, ?, 'Stacey', ?, ?, ?, ?, ?, ?, ?, 'active', ?,
                        '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
                """,
                (
                    concept_id,
                    campaign_id,
                    parent_reel_id,
                    parent_asset_id,
                    source_asset_id,
                    f"src_{concept_id}",
                    f"content_{concept_id}",
                    f"caption_{concept_id}",
                    f"audio_{concept_id}",
                    json.dumps({"conceptName": name}),
                ),
            )
        snapshots = [
            ("perf_mirror_1", "post_mirror_1", "concept_mirror", "parent_mirror", "audio_12", "tease", "2026-06-06T18:05:00+00:00", 14000, 13000),
            ("perf_mirror_2", "post_mirror_2", "concept_mirror", "parent_mirror", "audio_12", "challenge", "2026-06-07T21:20:00+00:00", 9000, 8000),
            ("perf_gym_1", "post_gym_1", "concept_gym", "parent_gym", "audio_44", "challenge", "2026-06-08T18:40:00+00:00", 7000, 6500),
            ("perf_low", "post_low", "concept_gym", "parent_gym", "audio_44", "challenge", "2026-06-08T10:00:00+00:00", 100, 90),
        ]
        for snapshot_id, post_id, concept_id, parent_reel_id, audio_id, caption_angle, published_at, views, reach in snapshots:
            cf.conn.execute(
                """
                INSERT INTO performance_snapshots
                (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
                 caption_angle, post_id, platform, status, instagram_account_id, published_at,
                 snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible,
                 concept_id, parent_reel_id, audio_id, creator_mix, created_at, raw_json)
                VALUES (?, ?, 'asset_1', ?, ?, ?, ?, ?, 'instagram', 'published', 'ig_1',
                 ?, '2026-06-09T00:00:00+00:00', ?, 100, 10, 20, 30, ?, 1,
                 ?, ?, ?, 'Stacey', '2026-06-09T00:00:00+00:00', '{}')
                """,
                (
                    snapshot_id,
                    campaign_id,
                    source_asset_id,
                    f"hash_{snapshot_id}",
                    f"caption_{snapshot_id}",
                    caption_angle,
                    post_id,
                    published_at,
                    views,
                    reach,
                    concept_id,
                    parent_reel_id,
                    audio_id,
                ),
            )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.winner_knowledge_base(creator="Stacey", min_views=1000)

        assert report["schema"] == "campaign_factory.winner_knowledge_base.v1"
        assert report["wouldWrite"] is False
        assert cf.conn.total_changes == before
        assert [item["conceptName"] for item in report["winnerPatterns"]["topConcepts"][:2]] == ["mirror selfie", "gym mirror"]
        assert report["winnerPatterns"]["topAudioFamilies"][0]["audioId"] == "audio_12"
        assert report["winnerPatterns"]["topCaptionAngles"][0]["captionAngle"] == "challenge"
        assert report["winnerPatterns"]["topPostingWindows"][0]["postingWindow"] == "6pm"
        assert report["conceptRegistry"][0]["conceptName"] == "mirror selfie"
        assert report["winnerRegistry"]["summary"]["winnerCount"] == 3
    finally:
        cf.close()


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
    parent = cf.rendered_asset("asset_1")
    rendered_path = tmp_path / f"{variant_asset_id}.mp4"
    rendered_path.write_bytes(f"rendered-{variant_asset_id}".encode("utf-8"))
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
    variant = cf.register_variant_asset(
        parent_asset_id="asset_1",
        variant_asset_id=variant_asset_id,
        variant_family_id=variant_family_id,
        variant_index=variant_index,
        operations=[{"type": "contentforge_result", "result": {
            "familyName": family_name,
            "uploadReady": True,
            "qualityScore": quality_score,
            "differenceScore": 35,
            "operationDiversityScore": 35,
            "captionReadabilityScore": 96,
            "focalSafetyScore": 96,
        }}],
        contentforge_preset="caption_safe_v2",
    )
    audit_path = rendered_path.with_suffix(".audit.json")
    audit_path.write_text(json.dumps({"readinessSummary": {"uploadReady": True}, "variant": {
        "familyName": family_name,
        "uploadReady": True,
        "qualityScore": quality_score,
        "differenceScore": 35,
        "operationDiversityScore": 35,
        "captionReadabilityScore": 96,
        "focalSafetyScore": 96,
    }}), encoding="utf-8")
    cf.conn.execute(
        """
        INSERT INTO audit_reports
        (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score, status,
         layers_json, verdicts_json, overall_verdict, files_analyzed, failed_checks_json, warnings_json, created_at)
        VALUES (?, ?, ?, 'run_variant', ?, ?, 'pass', '{}', '{}', 'pass', 1, '[]', '[]', ?)
        """,
        (f"audit_{variant_asset_id}", parent["campaign_id"], variant_asset_id, str(audit_path), quality_score, now),
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
        campaign = cf.campaign_by_slug(campaign_slug)
    except ValueError:
        folder = tmp_path / f"inputs_{campaign_slug}"
        folder.mkdir()
        (folder / f"{campaign_slug}.mp4").write_bytes(b"source")
        cf.import_folder(folder, campaign_slug=campaign_slug, model_slug="stacey")
        campaign = cf.campaign_by_slug(campaign_slug)
    source = cf.assets_for_campaign(campaign["id"])[0]
    rendered_path = tmp_path / f"{asset_id}.mp4"
    rendered_path.write_bytes(f"rendered-{asset_id}".encode("utf-8"))
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
    return cf.register_parent_reel(asset_id, operator="tester")


def table_count(cf: CampaignFactory, table: str) -> int:
    exists = cf.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if not exists:
        return 0
    return int(cf.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


def test_caption_family_plan_is_read_only_and_produces_requested_versions(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        parent = add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")
        before = {
            "caption_families": table_count(cf, "caption_families"),
            "caption_versions": table_count(cf, "caption_versions"),
            "rendered_assets": table_count(cf, "rendered_assets"),
            "distribution_plans": table_count(cf, "distribution_plans"),
            "variant_assets": table_count(cf, "variant_assets"),
        }

        plan = cf.caption_family_plan(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=5,
            style="ig_short",
            dry_run=True,
        )

        assert plan["schema"] == "campaign_factory.caption_family_plan.v1"
        assert plan["parentAssetId"] == "asset_caption_parent"
        assert plan["parentReelId"] == parent["parentReelId"]
        assert plan["captionFamilyId"].startswith("cfam_")
        assert plan["requestedCaptionVersions"] == 5
        assert len(plan["plannedVersions"]) == 5
        assert plan["canProceed"] is True
        assert plan["blockingReason"] == ""
        assert plan["wouldWrite"] is False
        assert {version["captionFamilyIndex"] for version in plan["plannedVersions"]} == {1, 2, 3, 4, 5}
        assert {version["captionAngle"] for version in plan["plannedVersions"]} == {
            "question_bait",
            "flirty_tease",
            "pov",
            "outfit_vote",
            "validation_hook",
        }
        assert table_count(cf, "caption_families") == before["caption_families"]
        assert table_count(cf, "caption_versions") == before["caption_versions"]
        assert table_count(cf, "rendered_assets") == before["rendered_assets"]
        assert table_count(cf, "distribution_plans") == before["distribution_plans"]
        assert table_count(cf, "variant_assets") == before["variant_assets"]
    finally:
        cf.close()


def test_caption_family_plan_keeps_burned_and_instagram_captions_separate_and_caps_hashtags(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_caption_parent'",
            (json.dumps({
                "instagram_post_caption": "new post is up",
                "caption_cta": "tell me if this works",
                "hashtags": ["#stacey", "mirror fit", "#reels", "outfit", "vote", "extra_tag"],
                "post_caption_style": "short_natural",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        cf.conn.commit()

        plan = cf.caption_family_plan(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=2,
            style="ig_short",
            dry_run=True,
        )

        first = plan["plannedVersions"][0]
        assert first["burnedCaptionText"]
        assert first["instagramPostCaption"]
        assert first["burnedCaptionText"] != first["instagramPostCaption"]
        assert first["burnedCaptionHash"] == cf._text_hash(first["burnedCaptionText"])
        assert first["instagramPostCaptionHash"] == cf._text_hash(first["instagramPostCaption"])
        assert len(first["hashtags"]) <= 5
        assert first["captionCta"]
        assert first["postCaptionStyle"] == "ig_short"
    finally:
        cf.close()


def test_caption_family_plan_blocks_blank_instagram_post_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")

        plan = cf.caption_family_plan(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=1,
            style="blank_instagram_post_caption",
            dry_run=True,
        )

        assert plan["canProceed"] is False
        assert plan["blockingReason"] == "blank_instagram_post_caption"
        assert plan["plannedVersions"][0]["instagramPostCaption"] == ""
        assert plan["plannedVersions"][0]["wouldWrite"] is False
    finally:
        cf.close()


def test_caption_family_hashes_are_stable_and_create_only_caption_records(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        parent = add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")
        first = cf.caption_family_plan(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=3,
            style="ig_short",
            dry_run=True,
        )
        second = cf.caption_family_plan(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=3,
            style="ig_short",
            dry_run=True,
        )
        before_assets = table_count(cf, "rendered_assets")
        before_plans = table_count(cf, "distribution_plans")

        created = cf.caption_family_create(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=3,
            style="ig_short",
            dry_run=False,
        )

        assert [v["captionVersionId"] for v in first["plannedVersions"]] == [v["captionVersionId"] for v in second["plannedVersions"]]
        assert [v["burnedCaptionHash"] for v in first["plannedVersions"]] == [v["burnedCaptionHash"] for v in second["plannedVersions"]]
        assert created["wouldWrite"] is True
        assert created["createdCaptionVersions"] == 3
        assert table_count(cf, "caption_families") == 1
        assert table_count(cf, "caption_versions") == 3
        assert table_count(cf, "rendered_assets") == before_assets
        assert table_count(cf, "distribution_plans") == before_plans
        row = cf.conn.execute("SELECT * FROM caption_versions WHERE caption_family_index = 1").fetchone()
        assert row["parent_reel_id"] == parent["parentReelId"]
        assert row["burned_caption_hash"] == first["plannedVersions"][0]["burnedCaptionHash"]
        assert row["instagram_post_caption_hash"] == first["plannedVersions"][0]["instagramPostCaptionHash"]
    finally:
        cf.close()


def test_caption_version_lineage_is_preserved_into_variant_plan(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")
        created = cf.caption_family_create(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=1,
            style="ig_short",
            dry_run=False,
        )
        caption_version_id = created["plannedVersions"][0]["captionVersionId"]

        plan = cf.variant_plan(
            parent_asset_id="asset_caption_parent",
            caption_version_id=caption_version_id,
            count=3,
            contentforge_preset="caption_safe_v2",
        )

        assert plan["captionFamilyId"] == created["captionFamilyId"]
        assert plan["captionVersionId"] == caption_version_id
        assert plan["variantFamilyId"].startswith("vfam_")
        assert all(
            {"captionFamilyId": created["captionFamilyId"], "captionVersionId": caption_version_id}.items()
            <= item["operations"][1].items()
            for item in plan["plannedOperations"]
        )
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_generate_variants_timeout_is_retry_safe_and_commits_no_variants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        cf.register_parent_reel("asset_1", operator="tester")

        def fake_urlopen(*_args, **_kwargs):
            raise TimeoutError("variant pack timed out")

        monkeypatch.setattr(core_module, "urlopen", fake_urlopen)

        result = cf.generate_variants(
            parent_asset_id="asset_1",
            count=2,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
            contentforge_timeout_seconds=1,
        )

        assert result["status"] == "blocked"
        assert result["blockingReason"] == "contentforge_variant_pack_start_timeout"
        assert result["retryOrResumeSafe"] is True
        assert result["partialCommitPrevented"] is True
        assert result["registeredVariants"] == []
        assert result["contentforgeDiagnostics"]["timeoutSeconds"] == 1
        assert cf.conn.execute("SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'contentforge_variant_pack'").fetchone()[0] == 0
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_generate_variants_polls_job_and_registers_terminal_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        cf.register_parent_reel("asset_1", operator="tester")
        output_dir = tmp_path / "contentforge_job_out"
        output_dir.mkdir()
        (output_dir / "variant_001.mp4").write_bytes(b"variant-one")
        report = {
            "schema": "contentforge.variant_pack.v2",
            "runId": "cf_job_inner_run",
            "manifestPath": str(output_dir / "variant_pack.json"),
            "outputDir": str(output_dir),
            "results": [
                {
                    "file": "variant_001.mp4",
                    "uploadReady": True,
                    "recommended": True,
                    "familyName": "cover_frame",
                    "operationSet": "caption_safe_v2",
                    "qualityScore": 95,
                    "operationDiversityScore": 33,
                }
            ],
        }
        responses = [
            {
                "schema": "contentforge.variant_pack_job.v1",
                "runId": "job_12345678",
                "status": "running",
                "pollUrl": "/api/variant-pack/jobs/job_12345678",
                "startedAt": "2026-06-09T00:00:00Z",
            },
            {
                "schema": "contentforge.variant_pack_job.v1",
                "runId": "job_12345678",
                "status": "succeeded",
                "pollUrl": "/api/variant-pack/jobs/job_12345678",
                "startedAt": "2026-06-09T00:00:00Z",
                "report": report,
                "artifacts": [{"filename": "variant_001.mp4"}],
            },
        ]
        seen_urls = []

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, **_kwargs):
            seen_urls.append(request.full_url)
            return FakeResponse(responses.pop(0))

        monkeypatch.setattr(core_module, "urlopen", fake_urlopen)
        monkeypatch.setattr(core_module.time, "sleep", lambda *_args: None)

        result = cf.generate_variants(
            parent_asset_id="asset_1",
            count=1,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
            contentforge_timeout_seconds=5,
        )

        assert result["status"] == "completed"
        assert seen_urls == [
            "http://contentforge.local/api/variant-pack/jobs",
            "http://contentforge.local/api/variant-pack/jobs/job_12345678",
        ]
        assert result["contentforgeReport"]["runId"] == "cf_job_inner_run"
        assert len(result["registeredVariants"]) == 1
        assert cf.conn.execute("SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'contentforge_variant_pack'").fetchone()[0] == 1
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 1
    finally:
        cf.close()


def test_generate_variants_running_job_is_resumable_and_commits_no_variants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        cf.register_parent_reel("asset_1", operator="tester")
        running = {
            "schema": "contentforge.variant_pack_job.v1",
            "runId": "job_running",
            "status": "running",
            "pollUrl": "/api/variant-pack/jobs/job_running",
            "startedAt": "2026-06-09T00:00:00Z",
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(running).encode("utf-8")

        monkeypatch.setattr(core_module, "urlopen", lambda *_args, **_kwargs: FakeResponse())
        monkeypatch.setattr(core_module.time, "sleep", lambda *_args: None)

        result = cf.generate_variants(
            parent_asset_id="asset_1",
            count=1,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
            contentforge_timeout_seconds=1,
        )

        assert result["status"] == "blocked"
        assert result["blockingReason"] == "contentforge_variant_pack_job_running"
        assert result["retryOrResumeSafe"] is True
        assert result["partialCommitPrevented"] is True
        assert result["contentforgeJob"]["runId"] == "job_running"
        assert cf.conn.execute("SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'contentforge_variant_pack'").fetchone()[0] == 0
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_generate_variants_rolls_back_partial_registration_on_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        cf.register_parent_reel("asset_1", operator="tester")
        output_dir = tmp_path / "contentforge_out"
        output_dir.mkdir()
        (output_dir / "variant_001.mp4").write_bytes(b"variant-one")
        report = {
            "schema": "contentforge.variant_pack.v2",
            "runId": "cf_run_v2_rollback",
            "manifestPath": str(output_dir / "variant_pack.json"),
            "outputDir": str(output_dir),
            "results": [
                {
                    "file": "variant_001.mp4",
                    "uploadReady": True,
                    "recommended": True,
                    "familyName": "cover_frame",
                    "operationSet": "caption_safe_v2",
                    "qualityScore": 95,
                    "operationDiversityScore": 33,
                }
            ],
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(report).encode("utf-8")

        monkeypatch.setattr(core_module, "urlopen", lambda *_args, **_kwargs: FakeResponse())

        def fail_register_variant_asset(**_kwargs):
            raise RuntimeError("simulated registration failure")

        monkeypatch.setattr(cf, "register_variant_asset", fail_register_variant_asset)

        with pytest.raises(RuntimeError, match="simulated registration failure"):
            cf.generate_variants(
                parent_asset_id="asset_1",
                count=1,
                contentforge_preset="caption_safe_v2",
                contentforge_base_url="http://contentforge.local",
            )

        assert cf.conn.execute("SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'contentforge_variant_pack'").fetchone()[0] == 0
        assert cf.conn.execute("SELECT COUNT(*) FROM audit_reports WHERE id LIKE 'audit_variant_%'").fetchone()[0] == 0
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_generate_variants_registers_caption_version_lineage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")
        created = cf.caption_family_create(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=1,
            style="ig_short",
            dry_run=False,
        )
        caption_version = created["plannedVersions"][0]
        output_dir = tmp_path / "contentforge_out"
        output_dir.mkdir()
        (output_dir / "variant_caption_001.mp4").write_bytes(b"variant-caption-version")
        source_override = tmp_path / "caption_version_parent.mp4"
        source_override.write_bytes(b"caption-version-rendered-parent")
        report = {
            "schema": "contentforge.variant_pack.v2",
            "runId": "cf_caption_version_run",
            "manifestPath": str(output_dir / "variant_pack.json"),
            "outputDir": str(output_dir),
            "results": [
                {
                    "file": "variant_caption_001.mp4",
                    "uploadReady": True,
                    "recommended": True,
                    "familyName": "cover_frame",
                    "operationSet": "caption_safe_v2",
                    "qualityScore": 96,
                    "differenceScore": 32,
                    "operationDiversityScore": 34,
                    "captionReadabilityScore": 98,
                    "focalSafetyScore": 98,
                }
            ],
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(report).encode("utf-8")

        monkeypatch.setattr(core_module, "urlopen", lambda *_args, **_kwargs: FakeResponse())

        result = cf.generate_variants(
            parent_asset_id="asset_caption_parent",
            caption_version_id=caption_version["captionVersionId"],
            count=1,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
            source_media_path=str(source_override),
        )

        assert result["status"] == "completed"
        assert len(result["registeredVariants"]) == 1
        variant = result["registeredVariants"][0]
        assert variant["parentAssetId"] == "asset_caption_parent"
        assert variant["captionFamilyId"] == created["captionFamilyId"]
        assert variant["captionVersionId"] == caption_version["captionVersionId"]
        assert variant["captionHash"] == caption_version["burnedCaptionHash"]
        rendered = cf.rendered_asset(variant["variantAssetId"])
        assert rendered["caption"] == caption_version["burnedCaptionText"]
        assert rendered["caption_hash"] == caption_version["burnedCaptionHash"]
        publishability = cf.explain_publishability(variant["variantAssetId"])
        assert publishability["captionFamilyId"] == created["captionFamilyId"]
        assert publishability["captionVersionId"] == caption_version["captionVersionId"]
        assert publishability["instagram_post_caption"] == caption_version["instagramPostCaption"]
    finally:
        cf.close()


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
        campaign = cf.campaign_by_slug(campaign_slug)
    except ValueError:
        folder = tmp_path / "surface_inputs"
        folder.mkdir()
        (folder / "surface-source.jpg").write_bytes(b"source-image")
        cf.import_folder(folder, campaign_slug=campaign_slug, model_slug="stacey")
        campaign = cf.campaign_by_slug(campaign_slug)
    source = cf.assets_for_campaign(campaign["id"])[0]
    suffix = ".mp4" if media_type == "video" else ".png"
    media_path = tmp_path / f"{asset_id}{suffix}"
    if media_type == "image" and content_surface == "story":
        write_rgb_png(media_path, 1080, 1920)
        target_ratio = "9:16"
    else:
        media_path.write_bytes(f"surface-{asset_id}".encode("utf-8"))
    caption_context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": f"caption_hash_{asset_id}",
        "caption_text": "burned caption",
        "creator_mix": creator,
        "render_recipe": "surface_fixture",
    }
    caption_generation = {}
    if instagram_post_caption is not None:
        caption_generation["instagram_post_caption"] = instagram_post_caption
    if content_surface == "story":
        caption_generation.update({
            "story_asset_class": "story_selfie",
            "story_intent": "casual_selfie",
            "story_style": "selfie",
        })
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
    return dict(cf.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)).fetchone())


def test_content_surface_normalization_keeps_feed_and_story_distinct():
    assert core_module.normalize_content_surface("regular_reel") == "reel"
    assert core_module.normalize_content_surface("feed-single") == "feed_single"
    assert core_module.normalize_content_surface("feed_carousel") == "feed_carousel"
    assert core_module.normalize_content_surface("story") == "story"
    assert core_module.normalize_content_surface("story_cta") == "story_cta"
    assert core_module.normalize_content_surface("image") == "feed_single"


def test_discoverability_safe_contract_blocks_dm_link_and_off_platform_language(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        result = cf.discoverability_safe_content_contract(
            "DM me",
            "link in bio",
            "Snap me",
            "subscribe here",
            "normal caption of the day",
        )

        assert result["discoverabilitySafe"] is False
        assert result["blockedReason"] == "discoverability_risk_link_dm_or_off_platform_reference"
        assert {item["reason"] for item in result["blockedTerms"]} == {
            "dm_reference",
            "link_reference",
            "off_platform_reference",
            "subscription_cta",
        }
        assert result["wouldWrite"] is False
    finally:
        cf.close()


def test_discoverability_safe_contract_does_not_block_common_word_of(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        result = cf.discoverability_safe_content_contract("photo of the day")

        assert result["discoverabilitySafe"] is True
        assert result["blockedTerms"] == []
    finally:
        cf.close()


def test_multi_surface_inventory_audit_counts_schedule_safe_by_surface(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_reel_safe", campaign_slug="stacey_surface_inventory_20260606")
        cf.conn.execute("UPDATE rendered_assets SET content_surface = 'reel', media_type = 'video' WHERE id = 'asset_reel_safe'")
        cf.create_distribution_plan("asset_reel_safe", surface="reel", instagram_account_id="ig_stacey_1")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_feed_safe", content_surface="feed_single", media_type="image")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_feed_blocked", content_surface="feed_single", media_type="image", instagram_post_caption="")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_safe", content_surface="story", media_type="image", instagram_post_caption="")

        report = cf.multi_surface_inventory_audit(creator="Stacey")

        assert report["inventoryBySurface"]["reel"] == {"total": 1, "scheduleSafe": 1}
        assert report["inventoryBySurface"]["story"] == {"total": 1, "scheduleSafe": 1}
        assert report["inventoryBySurface"]["feed_single"] == {"total": 2, "scheduleSafe": 1}
        assert report["inventoryBySurface"]["feed_carousel"] == {"total": 0, "scheduleSafe": 0}
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_handoff_readiness_blocks_discoverability_unsafe_feed_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_feed_unsafe_caption",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="link in bio",
        )

        report = cf.surface_handoff_readiness_report(
            creator="Stacey",
            rendered_asset_id="asset_feed_unsafe_caption",
        )

        assert report["assets"][0]["canHandoff"] is False
        assert report["assets"][0]["discoverabilitySafe"] is False
        assert "discoverability_safety_failed" in report["assets"][0]["blockingReasons"]
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_multi_surface_inventory_audit_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_feed_cli", content_surface="feed_single", media_type="image")
    finally:
        cf.close()

    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        "REEL_FACTORY_ROOT": str(tmp_path / "reel_factory"),
        "CONTENTFORGE_ROOT": str(tmp_path / "contentforge"),
        "THREADSDASH_ROOT": str(tmp_path / "ThreadsDashboard"),
        "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "multi-surface-inventory-audit",
            "--creator",
            "Stacey",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.multi_surface_inventory_audit.v1"
    assert payload["inventoryBySurface"]["feed_single"]["total"] == 1
    assert payload["wouldWrite"] is False


def test_account_surface_obligations_plan_is_read_only_and_surface_specific(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        campaign = cf.upsert_campaign("stacey_surface_inventory_20260606", "stacey")
        account = cf.upsert_account("stacey_main", platform="instagram", external_id="ig_stacey_1", model_id=model["id"])
        before = table_count(cf, "account_content_requirements")
        cf.conn.execute(
            """
            INSERT INTO account_content_requirements
            (id, account_id, creator, content_surface, cadence, max_per_day, min_gap_hours, allowed_days, active, created_at, updated_at)
            VALUES
            ('req_story', ?, 'Stacey', 'story', 'daily', 1, 20, '[]', 1, '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00'),
            ('req_reel', ?, 'Stacey', 'reel', 'daily', 1, 20, '[]', 1, '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00'),
            ('req_carousel', ?, 'Stacey', 'feed_carousel', 'weekly', 1, 96, '[6]', 1, '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
            """,
            (account["id"], account["id"], account["id"]),
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, post_id, platform, status, instagram_account_id, content_surface,
             published_at, snapshot_at, metrics_eligible, raw_json, created_at)
            VALUES ('snap_story_done', ?, 'post_story_done', 'instagram', 'published',
                    'ig_stacey_1', 'story', '2026-06-06T10:00:00+00:00',
                    '2026-06-06T11:00:00+00:00', 1, '{}', '2026-06-06T11:00:00+00:00')
            """,
            (campaign["id"],),
        )
        cf.conn.commit()

        plan = cf.account_surface_obligations_plan(creator="Stacey", date="2026-06-06")

        row = plan["accounts"][0]
        assert row["surfaceStatus"]["story"]["completed"] is True
        assert row["surfaceStatus"]["story"]["needed"] is False
        assert row["surfaceStatus"]["reel"]["needed"] is True
        assert row["surfaceStatus"]["feed_carousel"]["needed"] is True
        assert row["surfaceStatus"]["feed_single"]["needed"] is False
        assert table_count(cf, "account_content_requirements") == before + 3
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def add_account_requirement_fixture(
    cf: CampaignFactory,
    *,
    account_id: str,
    creator: str = "Stacey",
    surface: str,
    cadence: str = "daily",
    max_per_day: int = 1,
    allowed_days: list[int] | None = None,
):
    cf.conn.execute(
        """
        INSERT INTO account_content_requirements
        (id, account_id, creator, content_surface, cadence, max_per_day, min_gap_hours,
         allowed_days, active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, 1,
                '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
        """,
        (
            f"req_{account_id}_{surface}",
            account_id,
            creator,
            surface,
            cadence,
            max_per_day,
            json.dumps(allowed_days or []),
        ),
    )


def test_account_content_needs_counts_required_completed_scheduled_remaining(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_account_12", platform="instagram", external_id="ig_stacey_12", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="reel", max_per_day=1)
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", max_per_day=3)
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_scheduled", content_surface="story", media_type="image", instagram_post_caption="")
        campaign = cf.campaign_by_slug("stacey_surface_inventory_20260606")
        cf.conn.execute(
            """
            INSERT INTO distribution_plans
            (id, campaign_id, rendered_asset_id, account_id, instagram_account_id, surface, content_surface,
             created_at, updated_at, planned_window_start)
            VALUES ('dist_story_1', ?, 'asset_story_scheduled', ?, 'ig_stacey_12', 'story', 'story',
                    '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00',
                    '2026-06-06T12:00:00+00:00')
            """,
            (campaign["id"], account["id"]),
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, post_id, platform, status, account_id, instagram_account_id,
             content_surface, published_at, snapshot_at, raw_json, created_at)
            VALUES ('perf_story_1', ?, 'post_story_1', 'instagram', 'published', ?, 'ig_stacey_12',
                    'story', '2026-06-06T09:00:00+00:00', '2026-06-06T10:00:00+00:00',
                    '{}', '2026-06-06T10:00:00+00:00')
            """,
            (campaign["id"], account["id"]),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.account_content_needs(
            account_id=account["id"],
            creator="Stacey",
            date="2026-06-06",
        )

        obligations = {item["surface"]: item for item in report["obligations"]}
        assert obligations["story"]["required"] == 3
        assert obligations["story"]["completed"] == 1
        assert obligations["story"]["scheduled"] == 1
        assert obligations["story"]["remaining"] == 1
        assert obligations["story"]["needed"] is True
        assert obligations["reel"]["required"] == 1
        assert obligations["reel"]["remaining"] == 1
        assert report["wouldWrite"] is False
        assert cf.conn.total_changes == before
    finally:
        cf.close()


def test_account_content_needs_parses_per_day_cadence_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_story_account", platform="instagram", external_id="ig_story", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", cadence="3_per_day")
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.account_content_needs(
            account_id=account["id"],
            creator="Stacey",
            date="2026-06-06",
        )

        obligations = {item["surface"]: item for item in report["obligations"]}
        assert obligations["story"]["cadence"] == "3_per_day"
        assert obligations["story"]["required"] == 3
        assert obligations["story"]["remaining"] == 3
        assert report["wouldWrite"] is False
        assert cf.conn.total_changes == before
    finally:
        cf.close()


def test_account_surface_status_reports_needed_scheduled_completed_blocked_overdue(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_status_account", platform="instagram", external_id="ig_status", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="feed_carousel", cadence="weekly", max_per_day=1, allowed_days=[5])
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.account_surface_status(
            account_id=account["id"],
            creator="Stacey",
            date="2026-06-06",
        )

        status = report["surfaceStatus"]["feed_carousel"]
        assert status["needed"] is True
        assert status["scheduled"] == 0
        assert status["completed"] == 0
        assert status["blocked"] is False
        assert status["overdue"] is False
        assert "feed_carousel" in report["trackedStates"]
        assert report["wouldWrite"] is False
        assert cf.conn.total_changes == before
    finally:
        cf.close()


def test_creator_content_needs_rolls_up_accounts_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account_a = cf.upsert_account("stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"])
        account_b = cf.upsert_account("stacey_b", platform="instagram", external_id="ig_b", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account_a["id"], surface="story", max_per_day=3)
        add_account_requirement_fixture(cf, account_id=account_a["id"], surface="reel", max_per_day=1)
        add_account_requirement_fixture(cf, account_id=account_b["id"], surface="feed_carousel", cadence="weekly", max_per_day=1, allowed_days=[5])
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.creator_content_needs(creator="Stacey", date="2026-06-06")

        assert report["accountsAnalyzed"] == 2
        assert report["surfaceRequirementsTracked"] == ["reel", "story", "feed_single", "feed_carousel"]
        assert report["totalsBySurface"]["story"]["required"] == 3
        assert report["totalsBySurface"]["reel"]["required"] == 1
        assert report["totalsBySurface"]["feed_carousel"]["required"] == 1
        assert report["wouldWrite"] is False
        assert cf.conn.total_changes == before
    finally:
        cf.close()


def test_surface_gap_report_compares_remaining_needs_to_inventory(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account_a = cf.upsert_account("stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"])
        account_b = cf.upsert_account("stacey_b", platform="instagram", external_id="ig_b", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account_a["id"], surface="story", max_per_day=2)
        add_account_requirement_fixture(cf, account_id=account_b["id"], surface="story", max_per_day=1)
        add_account_requirement_fixture(cf, account_id=account_b["id"], surface="feed_carousel", cadence="weekly", max_per_day=1, allowed_days=[5])
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_gap", content_surface="story", media_type="image", instagram_post_caption="")
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.surface_gap_report(creator="Stacey", date="2026-06-06")

        assert report["surfaceGaps"]["story"]["needed"] == 3
        assert report["surfaceGaps"]["story"]["available"] == 1
        assert report["surfaceGaps"]["story"]["shortfall"] == 2
        assert report["surfaceGaps"]["feed_carousel"]["needed"] == 1
        assert report["surfaceGaps"]["feed_carousel"]["available"] == 0
        assert report["surfaceGaps"]["feed_carousel"]["blocked"] is True
        assert report["wouldWrite"] is False
        assert cf.conn.total_changes == before
    finally:
        cf.close()


def test_surface_handoff_readiness_validates_surfaces_differently(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_reel_ready", campaign_slug="stacey_surface_inventory_20260606")
        cf.conn.execute("UPDATE rendered_assets SET content_surface = 'reel', media_type = 'video' WHERE id = 'asset_reel_ready'")
        cf.create_distribution_plan("asset_reel_ready", surface="reel", instagram_account_id="ig_stacey_1")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_ready", content_surface="story", media_type="image", instagram_post_caption="")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_single_ready", content_surface="feed_single", media_type="image", instagram_post_caption="tap for more")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_single_blocked", content_surface="feed_single", media_type="image", instagram_post_caption="")
        carousel = add_surface_asset_fixture(cf, tmp_path, asset_id="asset_carousel_ready", content_surface="feed_carousel", media_type="image", instagram_post_caption="pick one")
        for index in range(2):
            component_path = tmp_path / f"carousel_{index}.jpg"
            component_path.write_bytes(f"carousel-{index}".encode("utf-8"))
            cf.conn.execute(
                """
                INSERT INTO asset_components
                (id, asset_id, component_index, media_path, media_hash, media_type, aspect_ratio,
                 alt_text, publishability_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'image', '1:1', ?, 'passed', '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
                """,
                (f"comp_{index}", carousel["id"], index, str(component_path), f"hash_comp_{index}", f"slide {index}"),
            )
        cf.conn.commit()

        report = cf.surface_handoff_readiness_report(creator="Stacey")
        by_asset = {item["assetId"]: item for item in report["assets"]}

        assert by_asset["asset_reel_ready"]["canHandoff"] is True
        assert by_asset["asset_story_ready"]["canHandoff"] is True
        assert by_asset["asset_story_ready"]["igMediaType"] == "STORIES"
        assert by_asset["asset_single_ready"]["canHandoff"] is True
        assert by_asset["asset_single_blocked"]["canHandoff"] is False
        assert "instagram_post_caption_missing" in by_asset["asset_single_blocked"]["blockingReasons"]
        assert by_asset["asset_carousel_ready"]["canHandoff"] is True
        assert by_asset["asset_carousel_ready"]["igMediaType"] == "CAROUSEL"
        assert len(by_asset["asset_carousel_ready"]["handoffManifestV2"]["mediaItems"]) == 2
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_handoff_readiness_blocks_carousel_without_ordered_components(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_carousel_gap", content_surface="feed_carousel", media_type="image", instagram_post_caption="pick one")
        component_path = tmp_path / "carousel_gap_1.jpg"
        component_path.write_bytes(b"carousel-gap")
        cf.conn.execute(
            """
            INSERT INTO asset_components
            (id, asset_id, component_index, media_path, media_hash, media_type, aspect_ratio,
             alt_text, publishability_state, created_at, updated_at)
            VALUES ('comp_gap_1', 'asset_carousel_gap', 1, ?, 'hash_gap_1', 'image', '1:1',
                    'slide 1', 'passed', '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
            """,
            (str(component_path),),
        )
        cf.conn.commit()

        report = cf.surface_handoff_readiness_report(creator="Stacey")
        item = next(asset for asset in report["assets"] if asset["assetId"] == "asset_carousel_gap")

        assert item["canHandoff"] is False
        assert "carousel_requires_2_to_10_components" in item["blockingReasons"]
        assert "carousel_components_not_ordered" in item["blockingReasons"]
        assert item["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_draft_proof_feed_single_image_does_not_collapse_to_reel(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_feed_single_proof",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="new fit today",
        )

        proof = cf.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_surface_inventory_20260606",
            rendered_asset_id="asset_feed_single_proof",
        )

        draft = proof["drafts"][0]
        manifest = draft["handoffManifestV2"]
        assert proof["canProduceDraftPayload"] is True
        assert draft["contentSurface"] == "feed_single"
        assert draft["igMediaType"] == "IMAGE"
        assert draft["mediaType"] == "image"
        assert draft["contentSurface"] != "reel"
        assert manifest["contentSurface"] == "feed_single"
        assert manifest["igMediaType"] == "IMAGE"
        assert manifest["mediaItems"][0]["mediaType"] == "image"
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_draft_proof_story_does_not_require_post_caption_by_default(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_proof",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
            target_ratio="9:16",
        )
        quality = cf.story_quality_gate_v1("asset_story_proof")

        proof = cf.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_surface_inventory_20260606",
            rendered_asset_id="asset_story_proof",
        )

        draft = proof["drafts"][0]
        assert quality["story_quality_gate_passed"] is True
        assert quality["geometry"]["width"] == 1080
        assert quality["geometry"]["height"] == 1920
        assert quality["storyBlackBarCheck"]["blackBarsDetected"] is False
        assert quality["story_safe_zone_score"] >= 95
        assert quality["story_focal_safety_score"] >= 95
        assert quality["story_text_readability_score"] >= 95
        assert proof["canProduceDraftPayload"] is True
        assert draft["contentSurface"] == "story"
        assert draft["igMediaType"] == "STORIES"
        assert draft["instagramPostCaption"] == ""
        assert draft["handoffManifestV2"]["instagramPostCaption"] == ""
        assert draft["handoffManifestV2"]["surfaceReadiness"]["canHandoff"] is True
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_draft_proof_carousel_manifest_has_ordered_media_items(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        carousel = add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_carousel_proof",
            content_surface="feed_carousel",
            media_type="image",
            instagram_post_caption="which one wins?",
        )
        for index in range(3):
            component_path = tmp_path / f"proof_carousel_{index}.jpg"
            component_path.write_bytes(f"carousel-{index}".encode("utf-8"))
            cf.conn.execute(
                """
                INSERT INTO asset_components
                (id, asset_id, component_index, media_path, media_hash, media_type, aspect_ratio,
                 alt_text, publishability_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'image', '1:1', ?, 'passed',
                        '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
                """,
                (f"proof_comp_{index}", carousel["id"], index, str(component_path), f"hash_proof_{index}", f"slide {index}"),
            )
        cf.conn.commit()

        proof = cf.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_surface_inventory_20260606",
            rendered_asset_id="asset_carousel_proof",
        )

        draft = proof["drafts"][0]
        media_items = draft["handoffManifestV2"]["mediaItems"]
        assert proof["canProduceDraftPayload"] is True
        assert draft["contentSurface"] == "feed_carousel"
        assert draft["igMediaType"] == "CAROUSEL"
        assert [item["componentIndex"] for item in media_items] == [0, 1, 2]
        assert all(item["mediaHash"] for item in media_items)
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def write_surface_image(path: Path) -> Path:
    return write_rgb_png(path, 1080, 1920)


def write_rgb_png(path: Path, width: int, height: int, *, color: tuple[int, int, int] = (200, 80, 120), bars: set[str] | None = None) -> Path:
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
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

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
    return dict(cf.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)).fetchone())


def test_story_quality_gate_1080x1920_passes(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_1080")

        result = cf.story_quality_gate_v1("asset_story_1080")

        assert result["story_quality_gate_passed"] is True
        assert result["geometry"]["passed"] is True
        assert result["storyBlackBarCheck"]["blackBarsDetected"] is False
        assert result["wouldWrite"] is False
    finally:
        cf.close()


@pytest.mark.parametrize("asset_id,width,height,reason", [
    ("asset_story_square", 1080, 1080, "invalid_story_aspect_ratio"),
    ("asset_story_landscape", 1920, 1080, "invalid_story_aspect_ratio"),
])
def test_story_quality_gate_blocks_non_story_geometry(tmp_path: Path, asset_id: str, width: int, height: int, reason: str):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id=asset_id, width=width, height=height)

        result = cf.story_quality_gate_v1(asset_id)

        assert result["story_quality_gate_passed"] is False
        assert reason in result["failureReasons"]
    finally:
        cf.close()


def test_story_quality_gate_blocks_black_bars(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_bars", bars={"top", "bottom"})

        result = cf.story_quality_gate_v1("asset_story_bars")

        assert result["storyBlackBarCheck"]["blackBarsDetected"] is True
        assert "black_bars" in result["failureReasons"]
    finally:
        cf.close()


@pytest.mark.parametrize("asset_id,quality_metadata,reason", [
    ("asset_story_safe_zone", {"story_safe_zone_score": 70}, "safe_zone_violation"),
    ("asset_story_head_cutoff", {"story_focal_safety_score": 65, "focalFailureReason": "head_cutoff"}, "head_cutoff"),
    ("asset_story_text_hidden", {"containsRenderedText": True, "story_text_readability_score": 60}, "text_hidden"),
])
def test_story_quality_gate_blocks_safe_zone_focal_and_text_failures(tmp_path: Path, asset_id: str, quality_metadata: dict, reason: str):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id=asset_id, quality_metadata=quality_metadata)

        result = cf.story_quality_gate_v1(asset_id)

        assert result["story_quality_gate_passed"] is False
        assert reason in result["failureReasons"]
    finally:
        cf.close()


def test_story_quality_report_and_readiness_use_quality_gate(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_quality_pass")
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_quality_fail", bars={"left"})

        report = cf.story_quality_report(creator="Stacey")
        readiness = cf.surface_handoff_readiness_report(creator="Stacey", rendered_asset_id="asset_story_quality_fail")
        inventory = cf.story_inventory_report(creator="Stacey")

        assert report["storyAssetsAnalyzed"] == 2
        assert report["passed"] == 1
        assert report["failed"] == 1
        assert "black_bars" in report["failureReasons"]
        assert readiness["assets"][0]["canHandoff"] is False
        assert "story_quality_gate_failed" in readiness["assets"][0]["blockingReasons"]
        assert inventory["storyAssetsQualityPassed"] == 1
        assert inventory["storyAssetsScheduleSafe"] == 1
        assert inventory["wouldWrite"] is False
    finally:
        cf.close()


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

        report = cf.story_intent_report(creator="Stacey")

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

        mix = cf.story_mix_plan(creator="Stacey")
        calendar = cf.story_calendar_plan(creator="Stacey")

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
        cf.conn.execute("UPDATE rendered_assets SET story_intent = 'snapchat_promo', story_style = 'casual' WHERE id = 'asset_story_snap'")
        cf.conn.execute("UPDATE rendered_assets SET story_intent = 'reel_teaser', story_style = 'raw_phone' WHERE id = 'asset_story_reel'")
        cf.conn.execute("UPDATE rendered_assets SET story_intent = 'casual_selfie', story_style = 'selfie' WHERE id = 'asset_story_casual'")
        cf.conn.commit()

        inventory = cf.story_inventory_report(creator="Stacey")
        summary = cf.story_intent_summary(creator="Stacey")

        assert inventory["snapchatPromoStories"] == 1
        assert inventory["reelTeaserStories"] == 1
        assert inventory["casualStories"] == 1
        assert inventory["storyIntentCoverage"] is True
        assert summary["storyIntentPerformance"] == {}
        assert summary["storyStylePerformance"] == {}
        assert summary["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_recommends_story_intent_and_style(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_story", platform="instagram", external_id="ig_story", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", cadence="daily", max_per_day=1)
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_snap")
        cf.conn.execute("UPDATE rendered_assets SET story_intent = 'snapchat_promo', story_style = 'casual' WHERE id = 'asset_story_snap'")
        cf.conn.commit()

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            date="2026-06-06",
            threadsdash_report=_manager_report_fixture(accounts=[
                {"accountId": "ig_story", "username": "stacey_story", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": False}
            ]),
            schedule_plan={"creator": "Stacey", "items": []},
        )

        stacey = plan["creators"][0]
        assert stacey["accountsNeedingStories"] == 1
        assert stacey["recommendedStoryIntent"] == "snapchat_promo"
        assert stacey["recommendedStoryStyle"] == "casual_selfie"
        assert stacey["wouldWrite"] is False
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

        result = cf.register_surface_asset(
            input_path=image,
            surface="feed_single",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            instagram_post_caption="new fit today",
        )

        asset = cf.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (result["renderedAssetId"],)).fetchone()
        proof = cf.surface_draft_proof(
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
        assert draft["handoffManifestV2"]["mediaItems"][0]["mediaHash"] == result["contentHash"]
        assert table_count(cf, "distribution_plans") == before["distribution_plans"]
        assert table_count(cf, "threadsdash_exports") == before["threadsdash_exports"]
        assert table_count(cf, "performance_snapshots") == before["performance_snapshots"]
    finally:
        cf.close()


def test_register_surface_asset_story_image_and_video_keep_story_mapping(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "story.png")
        video = tmp_path / "story.mp4"
        video.write_bytes(b"story-video-placeholder")

        image_result = cf.register_surface_asset(
            input_path=image,
            surface="story",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            story_asset_class="story_selfie",
            story_intent="casual_selfie",
            story_style="selfie",
        )
        video_result = cf.register_surface_asset(
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
        proof = cf.surface_draft_proof(creator="Stacey", campaign="stacey_surface_nonreel_20260606")
        drafts_by_asset = {draft["assetId"]: draft for draft in proof["drafts"]}
        blocked_by_asset = {item["assetId"]: item for item in proof["blockedAssets"]}
        assert drafts_by_asset[image_result["renderedAssetId"]]["instagramPostCaption"] == ""
        assert "story_quality_gate_failed" in blocked_by_asset[video_result["renderedAssetId"]]["blockingReasons"]
    finally:
        cf.close()


def test_register_surface_asset_story_rejects_rendered_reel_sources(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        rendered_dir = tmp_path / "campaign_factory" / "campaigns" / "stacey" / "old_reel_campaign" / "02_rendered"
        rendered_dir.mkdir(parents=True)
        reel_like = write_surface_image(rendered_dir / "parent_repair_captioned_reel.jpg")

        with pytest.raises(ValueError, match="story source is not story-native"):
            cf.register_surface_asset(
                input_path=reel_like,
                surface="story",
                creator="Stacey",
                campaign_slug="stacey_story_source_guard_20260609",
            )
    finally:
        cf.close()


def test_story_quality_gate_blocks_existing_story_with_reel_render_lineage(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        asset = add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_bad_lineage",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
            target_ratio="9:16",
        )
        reel_rendered = tmp_path / "campaign_factory" / "campaigns" / "stacey" / "variant_fanout" / "02_rendered" / "parent_repair_captioned.mp4"
        reel_rendered.parent.mkdir(parents=True)
        reel_rendered.write_bytes(b"not-used")
        cf.conn.execute(
            "UPDATE rendered_assets SET source_clip = ? WHERE id = ?",
            (str(reel_rendered), asset["id"]),
        )
        cf.conn.commit()

        quality = cf.story_quality_gate_v1(asset["id"])

        assert quality["story_quality_gate_passed"] is False
        assert "story_source_must_be_raw_not_rendered_reel_asset" in quality["failureReasons"]
        assert "story_source_appears_to_have_burned_caption_or_reel_lineage" in quality["failureReasons"]
        readiness = cf.surface_handoff_readiness_report(creator="Stacey", rendered_asset_id=asset["id"])
        assert "story_quality_gate_failed" in readiness["assets"][0]["blockingReasons"]
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

        quality = cf.story_quality_gate_v1("asset_story_text_visible")

        assert quality["storyNoTextRequired"] is True
        assert quality["storyNoTextPassed"] is False
        assert "story_no_text_violation" in quality["failureReasons"]
    finally:
        cf.close()


def test_story_readiness_blocks_missing_story_style_metadata(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_missing_style")
        cf.conn.execute(
            "UPDATE rendered_assets SET story_asset_class = NULL, story_intent = NULL, story_style = NULL WHERE id = ?",
            ("asset_story_missing_style",),
        )
        cf.conn.commit()

        readiness = cf.surface_handoff_readiness_report(creator="Stacey", rendered_asset_id="asset_story_missing_style")

        assert readiness["assets"][0]["canHandoff"] is False
        assert "story_style_not_approved" in readiness["assets"][0]["blockingReasons"]
    finally:
        cf.close()


def test_story_handoff_manifest_v2_includes_story_quality_proof_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(
            cf,
            tmp_path,
            asset_id="asset_story_manifest_quality",
            quality_metadata={"storyNoTextRequired": True, "storyNoTextPassed": True},
        )

        readiness = cf.surface_handoff_readiness_report(creator="Stacey", rendered_asset_id="asset_story_manifest_quality")
        manifest = readiness["assets"][0]["handoffManifestV2"]

        assert readiness["assets"][0]["canHandoff"] is True
        assert manifest["storyQualityGatePassed"] is True
        assert manifest["storySourceNative"] is True
        assert manifest["storyNoTextRequired"] is True
        assert manifest["storyNoTextPassed"] is True
        assert manifest["storyStyleApproved"] is True
        assert manifest["sourceLineageBlockers"] == []
        assert manifest["visualQualityStatus"] == "passed"
    finally:
        cf.close()


def test_register_surface_asset_carousel_creates_ordered_components(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        components = [write_surface_image(tmp_path / f"carousel_{index}.png") for index in range(3)]

        result = cf.register_surface_asset(
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
        proof = cf.surface_draft_proof(
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


def test_carousel_integrity_report_preserves_order_hashes_surface_and_caption_lineage(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        inputs = [
            write_rgb_png(tmp_path / f"integrity_carousel_{index}.png", 1080, 1080, color=(120 + index, 90, 180))
            for index in range(3)
        ]
        registered = cf.register_surface_asset(
            input_path=inputs,
            surface="feed_carousel",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            instagram_post_caption="which slide wins?",
            target_ratio="1:1",
            alt_text=["first", "second", "third"],
        )
        before = cf.conn.total_changes

        report = cf.carousel_integrity_report(
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
        assert item["assetComponents"]["componentHashes"] == item["handoffManifestV2"]["componentHashes"]
        assert item["handoffManifestV2"]["componentHashes"] == item["surfaceDraftProof"]["componentHashes"]
        assert item["surfaceDraftProof"]["componentHashes"] == item["threadDashPayload"]["componentHashes"]
        assert item["threadDashPayload"]["componentHashes"] == item["metaChildPayloadPreview"]["componentHashes"]
        assert item["threadDashPayload"]["contentSurface"] == "feed_carousel"
        assert item["metaChildPayloadPreview"]["parentPayload"]["media_type"] == "CAROUSEL"
    finally:
        cf.close()


def test_carousel_child_metrics_plan_is_read_only_and_child_addressable(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        inputs = [
            write_rgb_png(tmp_path / f"metrics_carousel_{index}.png", 1080, 1080, color=(90, 110 + index, 160))
            for index in range(2)
        ]
        registered = cf.register_surface_asset(
            input_path=inputs,
            surface="feed_carousel",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            instagram_post_caption="pick one",
            target_ratio="1:1",
        )
        before = cf.conn.total_changes

        plan = cf.carousel_child_metrics_plan(
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            rendered_asset_id=registered["renderedAssetId"],
        )

        assert cf.conn.total_changes == before
        assert plan["schema"] == "campaign_factory.carousel_child_metrics_plan.v1"
        assert plan["wouldWrite"] is False
        assert plan["carouselAssetsAnalyzed"] == 1
        item = plan["assets"][0]
        assert item["contentSurface"] == "feed_carousel"
        assert item["igMediaType"] == "CAROUSEL"
        assert item["childCount"] == 2
        assert item["parentMetricsCanonical"] is True
        assert item["childMetricsSupplemental"] is True
        assert item["parentMetricKeys"] == [
            "post_id",
            "rendered_asset_id",
            "content_surface",
            "views",
            "reach",
            "likes",
            "comments",
            "shares",
            "saves",
        ]
        assert [child["componentIndex"] for child in item["childMetricsPlan"]] == [0, 1]
        assert all(child["componentHash"] for child in item["childMetricsPlan"])
        assert item["metricsRollupKeys"] == [
            "rendered_asset_id",
            "carousel_child_index",
            "carousel_child_hash",
            "content_surface",
        ]
    finally:
        cf.close()


@pytest.mark.parametrize("component_count", [1, 11])
def test_register_surface_asset_carousel_rejects_invalid_component_count(tmp_path: Path, component_count: int):
    cf = make_factory(tmp_path)
    try:
        components = [write_surface_image(tmp_path / f"bad_carousel_{index}.png") for index in range(component_count)]

        with pytest.raises(ValueError, match="carousel requires 2 to 10 components"):
            cf.register_surface_asset(
                input_path=components,
                surface="feed_carousel",
                creator="Stacey",
                campaign_slug="stacey_surface_nonreel_20260606",
                instagram_post_caption="pick one",
            )
    finally:
        cf.close()


def test_register_surface_asset_feed_single_requires_caption_and_never_collapses_to_reel(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "feed_no_caption.png")

        with pytest.raises(ValueError, match="instagram_post_caption is required"):
            cf.register_surface_asset(
                input_path=image,
                surface="feed_single",
                creator="Stacey",
                campaign_slug="stacey_surface_nonreel_20260606",
                instagram_post_caption="",
            )

        assert cf.conn.execute("SELECT COUNT(*) AS c FROM rendered_assets").fetchone()["c"] == 0
    finally:
        cf.close()


def test_feed_single_caption_family_uses_surface_handoff_readiness(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "feed_caption_family.png")
        registered = cf.register_surface_asset(
            input_path=image,
            surface="feed_single",
            creator="Stacey",
            campaign_slug="stacey_feed_single_proof",
            instagram_post_caption="soft launch today",
        )

        parent = cf.register_parent_reel(registered["renderedAssetId"], operator="tester")
        created = cf.caption_family_create(
            creator="Stacey",
            parent_asset_id=registered["renderedAssetId"],
            requested_caption_versions=3,
            style="ig_short",
        )

        assert parent["parentAssetId"] == registered["renderedAssetId"]
        assert created["createdCaptionVersions"] == 3
        assert created["canProceed"] is True
        assert all(version["instagramPostCaption"] for version in created["plannedVersions"])
        assert cf.conn.execute("SELECT COUNT(*) FROM caption_versions WHERE caption_family_id = ?", (created["captionFamilyId"],)).fetchone()[0] == 3
    finally:
        cf.close()


def test_feed_single_manifest_v2_is_metrics_eligible_after_publish(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "feed_metrics_v2.png")
        registered = cf.register_surface_asset(
            input_path=image,
            surface="feed_single",
            creator="Stacey",
            campaign_slug="stacey_feed_single_proof",
            instagram_post_caption="soft launch today",
        )
        asset = cf.rendered_asset(registered["renderedAssetId"])
        readiness = cf.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_feed_single_proof",
            rendered_asset_id=registered["renderedAssetId"],
        )["drafts"][0]
        manifest = readiness["handoffManifestV2"]
        row = {
            "id": "post_feed_single_v2",
            "status": "published",
            "platform": "instagram",
            "content_surface": "feed_single",
            "ig_media_type": "IMAGE",
            "content": readiness["instagramPostCaption"],
        }
        meta = {
            "rendered_asset_id": asset["id"],
            "source_asset_id": asset["source_asset_id"],
            "content_hash": asset["content_hash"],
            "caption_hash": asset["caption_hash"],
            "asset_state": "exportable",
            "handoff_manifest": manifest,
            "publishability_failure_reasons": [],
        }

        eligibility = threadsdash_adapter._metrics_eligibility_for_threadsdash_row(cf, row=row, meta=meta)

        assert eligibility["eligible"] is True
        assert "handoff_manifest_version_invalid" not in eligibility["blockingReasons"]
    finally:
        cf.close()


def test_story_metrics_eligibility_allows_blank_story_caption_hash(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "story_metrics.png")
        registered = cf.register_surface_asset(
            input_path=image,
            surface="story",
            creator="Stacey",
            campaign_slug="stacey_story_metrics_proof",
            story_asset_class="story_selfie",
            story_intent="casual_selfie",
            story_style="selfie",
        )
        asset = cf.rendered_asset(registered["renderedAssetId"])
        draft = cf.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_story_metrics_proof",
            rendered_asset_id=registered["renderedAssetId"],
        )["drafts"][0]
        manifest = draft["handoffManifestV2"]
        assert manifest["contentSurface"] == "story"
        assert manifest["caption_hash"] is None

        row = {
            "id": "post_story_metrics",
            "status": "published",
            "platform": "instagram",
            "content_surface": "story",
            "ig_media_type": "STORIES",
            "content": "",
        }
        meta = {
            "rendered_asset_id": asset["id"],
            "source_asset_id": asset["source_asset_id"],
            "content_hash": asset["content_hash"],
            "caption_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "asset_state": "exportable",
            "handoff_manifest": manifest,
            "publishability_failure_reasons": [],
        }

        eligibility = threadsdash_adapter._metrics_eligibility_for_threadsdash_row(cf, row=row, meta=meta)

        assert eligibility["eligible"] is True
        assert "handoff_manifest_caption_hash_mismatch" not in eligibility["blockingReasons"]
    finally:
        cf.close()


def test_variant_inventory_plan_can_fill_shortfall_from_eligible_parents(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        for asset_id in ("asset_parent_1", "asset_parent_2", "asset_parent_3"):
            add_inventory_parent_fixture(cf, tmp_path, asset_id=asset_id)

        plan = cf.variant_inventory_plan(
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
        assert [batch["requestedVariants"] for batch in plan["executionBatches"]] == [10, 10, 5]
        assert all(batch["minimumRecommended"] == 3 for batch in plan["executionBatches"])
        assert plan["executionBatches"][0]["operationFamilies"][:6] == [
            "cover_frame",
            "timing_trim",
            "caption_lane_timing",
            "crop_zoom_family",
            "color_profile",
            "audio_offset",
        ]
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0] == 0
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_variant_inventory_plan_blocks_when_parent_inventory_insufficient(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_parent_1")

        plan = cf.variant_inventory_plan(
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
        assert plan["blockingReason"] == "insufficient_eligible_parent_inventory_missing_15_variants"
        assert plan["nextSafeAction"] == "create_or_import_more_parent_reels"
    finally:
        cf.close()


def test_variant_inventory_plan_excludes_blocked_parent_reasons(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_quarantined")
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_missing_caption")
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_missing_audio", audio_required=True)
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_missing_placement")
        cf.quarantine_asset("asset_quarantined", reason="operator_quarantine", root_cause="qc_failure")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_missing_caption'",
            (json.dumps({
                "instagram_post_caption": "",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            }),),
        )
        context = json.loads(cf.conn.execute(
            "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_missing_placement'"
        ).fetchone()[0])
        context.pop("captionPlacementPolicy", None)
        context.pop("captionPlacementDecision", None)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ? WHERE id = 'asset_missing_placement'",
            (json.dumps(context, sort_keys=True),),
        )
        cf.conn.commit()
        monkeypatch.setattr(core_module, "probe_video_metadata", lambda path: {"ok": True, "audioPresent": False})

        plan = cf.variant_inventory_plan(
            creator="Stacey",
            campaign="stacey_archive_marketing_20260606",
            target_draft_shortfall=3,
            dry_run=True,
        )

        reasons = {row["parentAssetId"]: row["blockingReason"] for row in plan["blockedParents"]}
        assert plan["eligibleParents"] == []
        assert reasons["asset_quarantined"] == "quarantined_asset"
        assert reasons["asset_missing_caption"] == "missing_instagram_post_caption"
        assert reasons["asset_missing_audio"] == "embedded_audio_missing"
        assert reasons["asset_missing_placement"] == "caption_placement_qc_failed"
        assert all(row["wouldWrite"] is False for row in plan["blockedParents"])
    finally:
        cf.close()


def test_variant_inventory_plan_existing_siblings_reduce_estimated_capacity(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_1")
        for index, family_name in enumerate(["cover_frame", "timing_trim", "caption_lane_timing", "crop_zoom_family"], start=1):
            add_variant_fixture(
                cf,
                tmp_path,
                variant_asset_id=f"asset_variant_{index}",
                variant_family_id="vfam_inventory",
                variant_index=index,
                family_name=family_name,
                content_hash=f"variant_hash_{index}",
            )

        plan = cf.variant_inventory_plan(
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
        assert plan["executionBatches"][0]["operationFamilies"][:2] == ["color_profile", "audio_offset"]
    finally:
        cf.close()


def test_ad_hoc_inventory_fill_variant_requires_operator_visual_review(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_1")
        add_variant_fixture(
            cf,
            tmp_path,
            variant_asset_id="asset_ad_hoc_inventory_variant",
            variant_family_id="vfam_ad_hoc",
            variant_index=1,
        )
        operations = [
            {"type": "inventory_fill_ffmpeg_variant", "operationFamily": "color_profile", "operation": "color_profile_warm_safe"},
            {"type": "preserve_parent_lineage", "parentAssetId": "asset_1"},
        ]
        cf.conn.execute(
            "UPDATE rendered_assets SET variant_operations_json = ? WHERE id = ?",
            (json.dumps(operations, ensure_ascii=False, sort_keys=True), "asset_ad_hoc_inventory_variant"),
        )
        cf.conn.execute(
            "UPDATE variant_assets SET operations_json = ? WHERE variant_asset_id = ?",
            (json.dumps(operations, ensure_ascii=False, sort_keys=True), "asset_ad_hoc_inventory_variant"),
        )
        cf.conn.commit()

        plan = cf.create_distribution_plan("asset_ad_hoc_inventory_variant", surface="regular_reel")
        publishability = cf.explain_publishability("asset_ad_hoc_inventory_variant", distribution_plan_id=plan["id"])
        readiness = cf._surface_handoff_readiness_for_asset(cf.rendered_asset("asset_ad_hoc_inventory_variant"))

        assert "operator_visual_review_required" in publishability["publishability_failure_reasons"]
        assert "operator_visual_review_required" in readiness["blockingReasons"]
        assert readiness["canHandoff"] is False
    finally:
        cf.close()


def test_audio_preview_reel_requires_operator_visual_review(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_audio_preview")
        preview_path = tmp_path / "stacey_archive_01_src19_caption_bg_light_audio_preview_asset_audio_preview.mp4"
        preview_path.write_bytes(b"preview-render")
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET filename = ?, output_path = ?, campaign_path = ?
            WHERE id = 'asset_audio_preview'
            """,
            (preview_path.name, str(preview_path), str(preview_path)),
        )
        cf.conn.commit()

        plan = cf.create_distribution_plan("asset_audio_preview", surface="regular_reel")
        publishability = cf.explain_publishability("asset_audio_preview", distribution_plan_id=plan["id"])
        readiness = cf._surface_handoff_readiness_for_asset(cf.rendered_asset("asset_audio_preview"))

        assert "operator_visual_review_required" in publishability["publishability_failure_reasons"]
        assert "operator_visual_review_required" in readiness["blockingReasons"]
        assert readiness["canHandoff"] is False
    finally:
        cf.close()


def test_variant_inventory_plan_prefers_winner_parent_over_non_winner(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        winner = add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_winner")
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_archive")
        campaign = cf.campaign_by_slug("stacey_archive_marketing_20260606")
        asset = cf.rendered_asset("asset_winner")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
             post_id, platform, status, instagram_account_id, snapshot_at, views, likes,
             comments, shares, saves, reach, metrics_eligible, concept_id, parent_reel_id,
             audio_id, created_at)
            VALUES ('perf_inventory_winner', ?, 'asset_winner', ?, 'hash_asset_winner', 'caption_hash_asset_winner',
             'post_winner', 'instagram', 'published', 'ig_1', '2026-01-02T00:00:00+00:00',
             12000, 700, 40, 80, 100, 11000, 1, ?, ?, 'audio_1',
             '2026-01-02T00:00:00+00:00')
            """,
            (campaign["id"], asset["source_asset_id"], winner["conceptId"], winner["parentReelId"]),
        )
        cf.conn.commit()

        plan = cf.variant_inventory_plan(
            creator="Stacey",
            campaign="stacey_archive_marketing_20260606",
            target_draft_shortfall=12,
            max_variants_per_parent=10,
            dry_run=True,
        )

        assert [row["parentAssetId"] for row in plan["eligibleParents"][:2]] == ["asset_winner", "asset_archive"]
        assert plan["eligibleParents"][0]["reasonEligible"] == "winner_metrics"
        assert plan["executionBatches"][0]["parentAssetId"] == "asset_winner"
    finally:
        cf.close()


def test_winner_expansion_plan_is_read_only_and_covers_named_operation_families(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        cf.register_parent_reel("asset_1", operator="tester")
        before = cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0]

        plan = cf.winner_expansion_plan(creator="Stacey", parent_asset_id="asset_1", target_variants=10, preset="caption_safe_v2")

        assert plan["parentAssetId"] == "asset_1"
        assert plan["existingVariants"] == 0
        assert plan["recommendedNewVariants"] == 10
        assert plan["canProceed"] is True
        assert plan["wouldWrite"] is False
        assert plan["blockingReason"] == ""
        assert plan["operationFamilies"][:6] == [
            "cover_frame",
            "timing_trim",
            "caption_lane_timing",
            "crop_zoom_family",
            "color_profile",
            "audio_offset",
        ]
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0] == before
    finally:
        cf.close()


def test_winner_expansion_plan_rejects_low_quality_and_duplicate_siblings(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        parent = cf.register_parent_reel("asset_1", operator="tester")
        add_variant_fixture(cf, tmp_path, variant_asset_id="asset_variant_low", variant_index=1, quality_score=89)
        add_variant_fixture(cf, tmp_path, variant_asset_id="asset_variant_good", variant_index=2, content_hash="hash_unique_good")
        add_variant_fixture(cf, tmp_path, variant_asset_id="asset_variant_duplicate_family", variant_index=3, content_hash="hash_unique_duplicate_family")

        plan = cf.winner_expansion_plan(creator="Stacey", parent_asset_id="asset_1", target_variants=5, preset="caption_safe_v2")

        assert plan["variantFamilyId"] == "vfam_winner"
        assert plan["parentReelId"] == parent["parentReelId"]
        assert plan["existingVariants"] == 1
        assert plan["recommendedNewVariants"] == 4
        assert "cover_frame" not in plan["operationFamilies"][:4]
        assert plan["rejectedExistingVariants"]["lowQuality"] == 1
        assert plan["rejectedExistingVariants"]["duplicateSiblings"] == 1
    finally:
        cf.close()


def test_winner_expansion_report_is_read_only_and_uses_instagram_visible_metrics(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute("UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'")
        cf.conn.commit()
        parent = cf.register_parent_reel("asset_1", operator="tester")
        variant = cf.register_variant_asset(
            parent_asset_id="asset_1",
            variant_asset_id="asset_1",
            variant_family_id="vfam_report",
            variant_index=1,
            operations=[{"type": "contentforge_result", "result": {"familyName": "cover_frame"}}],
        )
        before = (
            cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0],
            cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0],
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
             post_id, platform, status, instagram_account_id, snapshot_at, views, likes,
             comments, shares, saves, reach, metrics_eligible, concept_id, parent_reel_id,
             variant_family_id, variant_id, audio_id, created_at, raw_json)
            VALUES ('perf_winner', ?, 'asset_1', ?, 'hash_1', 'caption_hash_1',
             'post_winner', 'instagram', 'published', 'ig_1', '2026-01-02T00:00:00+00:00',
             12000, 700, 40, 80, 100, 11000, 1, ?, ?, 'vfam_report', ?, 'audio_1',
             '2026-01-02T00:00:00+00:00', '{"onlyfansRevenue":999999}')
            """,
            (
                cf.rendered_asset("asset_1")["campaign_id"],
                cf.rendered_asset("asset_1")["source_asset_id"],
                parent["conceptId"],
                parent["parentReelId"],
                variant["variantId"],
            ),
        )
        cf.conn.commit()

        report = cf.winner_expansion_report("may", min_views=1000)

        assert report["wouldWrite"] is False
        assert report["summary"]["winnerCount"] == 1
        assert report["winners"][0]["postId"] == "post_winner"
        assert report["winners"][0]["assetId"] == "asset_1"
        assert report["winners"][0]["parentReelId"] == parent["parentReelId"]
        assert report["winners"][0]["variantFamilyId"] == "vfam_report"
        assert report["winners"][0]["reason"] == "high_views"
        assert report["winners"][0]["recommendedAction"] == "create_more_variants"
        assert report["winners"][0]["wouldWrite"] is False
        assert "onlyfansRevenue" not in json.dumps(report).lower()
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0] == before[0]
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == before[1]
    finally:
        cf.close()


def test_explain_publishability_and_quarantine_bad_asset(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path, filename="proof_v00_passthrough.mp4")
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)

        explanation = cf.explain_publishability("asset_1")
        assert explanation["asset_state"] == "approved_but_not_publishable"
        assert explanation["approved"] is True
        assert "missing_burned_captions" in explanation["publishability_failure_reasons"]
        assert explanation["rootCause"] == "wrong_approved_asset"

        quarantine = cf.quarantine_asset(
            "asset_1",
            reason="threadsdash_draft_media_invalid_missing_burned_captions",
            root_cause="wrong_approved_asset",
            threadsdash_post_id="8ee460e1-4f4e-4298-9597-462223b3f5cb",
            created_by="test",
        )
        assert quarantine["excluded_from_metrics"] == 1

        after = cf.explain_publishability("asset_1")
        assert "quarantined_asset" in after["publishability_failure_reasons"]
        assert after["blockingReason"] in {"missing_burned_captions", "quarantined_asset"}
    finally:
        cf.close()


def test_live_export_requires_explicit_confirmation_for_warnings(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []
    inserted: list[tuple[str, dict]] = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

        def upload_storage_object(self, bucket, storage_path, file_path, content_type):
            pass

        def insert_with_fallback(self, table, row, fallback_remove):
            inserted.append((table, dict(row)))
            return {"id": f"{table}_1", **row}

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf, overall_verdict="warn", warnings=["compression"])
        cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_1",
            planned_window_start="2026-06-05T15:00:00+00:00",
            planned_window_end="2026-06-05T15:15:00+00:00",
        )
        try:
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=False,
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
                schedule_mode="live",
            )
        except ValueError as exc:
            assert "warnings" in str(exc)
        else:
            raise AssertionError("live export should require explicit warning confirmation")

        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=False,
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            allow_warnings=True,
            content_pillar="lifestyle",
            cta_type="none",
            language="en",
            schedule_mode="live",
        )
        assert result["supabase"]["attempted"] is True
        assert any(table == "posts" for table, _ in inserted)
        post_row = next(row for table, row in inserted if table == "posts")
        meta = post_row["metadata"]["campaign_factory"]
        assert meta["caption_hash"]
        assert meta["content_pillar"] == "lifestyle"
        assert meta["cta_type"] == "none"
        assert meta["language"] == "en"
    finally:
        cf.close()


def test_threadsdash_live_export_builds_exact_supabase_rows(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    inserted: list[tuple[str, dict]] = []
    uploads: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def upload_storage_object(self, bucket, storage_path, file_path, content_type):
            uploads.append((bucket, storage_path))

        def insert_with_fallback(self, table, row, fallback_remove):
            inserted.append((table, dict(row)))
            return {"id": f"{table}_1", **row}

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        source = cf.assets_for_campaign(cf.campaign_by_slug("may")["id"])[0]
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
             caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
             caption_generation_json, created_at, updated_at)
            VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, 'ok.mp4', 'caption', 'caption_hash_1', ?,
                    'v01_original', 'approved_candidate', 'approved', ?, ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps({
                    "schema": "campaign_factory.caption_outcome_context.v1",
                    "caption_hash": "caption_hash_1",
                    "caption_text": "caption",
                    "caption_bank": "test_bank",
                    "caption_banks": ["test_bank"],
                    "creator_mix": "Test",
                    "render_recipe": "v01_original",
                    "captionPlacementPolicy": "focal_safe_v1",
                    "captionPlacementDecision": {"status": "passed", "selectedLane": "top"},
                }),
                json.dumps({
                    "audioIntent": {
                        "schema": "pipeline.audio_intent.v1",
                        "mode": "native_platform_audio",
                        "required": False,
                        "status": "not_required",
                    }
                }),
                now,
                now,
            ),
        )
        cf.conn.commit()
        add_audit_report(cf)
        ensure_exportable_distribution_plan(cf)
        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=False,
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert result["dryRun"] is False
        assert uploads[0][0] == "media"
        media_row = next(row for table, row in inserted if table == "media")
        post_row = next(row for table, row in inserted if table == "posts")
        assert set(media_row) >= {"user_id", "file_name", "file_url", "file_type", "file_size", "mime_type", "storage_url", "storage_path", "tags"}
        assert "workspace_id" not in media_row
        assert post_row["platform"] == "instagram"
        assert post_row["status"] == "draft"
        assert post_row["media_type"] == "reel"
        assert post_row["ig_media_type"] == "REELS"
        assert post_row["scheduled_for"] is None
        assert post_row["campaign_factory_asset_id"] == "asset_1"
        assert post_row["campaign_factory_distribution_plan_id"]
        assert post_row["campaign_factory_post_key"]
        assert post_row["campaign_factory_content_fingerprint"] == "hash_1"
        assert post_row["campaign_factory_caption_hash"]
        assert post_row["platform_draft_validated"] is True
        assert "published_at" not in post_row
        assert "ig_container_id" not in post_row
        assert post_row["metadata"]["campaign_factory"]["rendered_asset_id"] == "asset_1"
        assert post_row["metadata"]["campaign_factory"]["content_hash"] == "hash_1"
        assert post_row["metadata"]["campaign_factory"]["source_content_hash"] == source["content_hash"]
        assert post_row["metadata"]["campaign_factory"]["caption_hash"]
        assert post_row["metadata"]["campaign_factory"]["recipe"] == "v01_original"
        assert post_row["metadata"]["campaign_factory"]["export_id"].startswith("tdexp_")
    finally:
        cf.close()


def test_live_export_blocks_without_passing_readiness(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        try:
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=False,
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
                schedule_mode="live",
            )
        except ValueError as exc:
            assert "missing_audit" in str(exc)
        else:
            raise AssertionError("live export should block without an audit")
    finally:
        cf.close()


def test_threadsdash_usage_summarizes_existing_campaign_posts(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            assert params["user_id"] == "eq.user_1"
            return [
                {
                    "id": "post_1",
                    "status": "published",
                    "platform": "instagram",
                    "media_type": "reel",
                    "ig_media_type": "REELS",
                    "account_id": None,
                    "instagram_account_id": "ig_1",
                    "created_at": "2026-01-02T00:00:00+00:00",
                    "metadata": {
                        "campaign_factory": {
                            "campaign_id": "may",
                            "source_asset_id": "src_1",
                            "rendered_asset_id": "asset_1",
                            "content_hash": "hash_1",
                            "source_content_hash": "source_hash_1",
                        }
                    },
                },
                {
                    "id": "post_2",
                    "status": "draft",
                    "platform": "instagram",
                    "media_type": "story",
                    "ig_media_type": "STORIES",
                    "account_id": None,
                    "instagram_account_id": "ig_2",
                    "created_at": "2026-01-03T00:00:00+00:00",
                    "metadata": {
                        "campaign_factory": {
                            "campaign_id": "may",
                            "source_asset_id": "src_1",
                            "rendered_asset_id": "other_asset",
                            "content_hash": "other_hash",
                            "source_content_hash": "source_hash_1",
                        }
                    },
                },
            ]

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        imported = cf.import_folder(folder, campaign_slug="may", model_slug="model")
        source = imported["imported"][0]
        cf.conn.execute("UPDATE source_assets SET id = 'src_1', content_hash = 'source_hash_1' WHERE id = ?", (source["id"],))
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_1', ?, 'src_1', 'hash_1', ?, ?, 'ok.mp4', 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?)
            """,
            (source["campaign_id"], str(rendered_path), str(rendered_path), now, now),
        )
        cf.conn.commit()

        usage = summarize_threadsdash_usage(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        asset = usage["assets"][0]
        assert asset["usage"]["published"] == 1
        assert usage["sourceUsage"]["src_1"]["total"] == 2
        assert usage["contentHashUsage"]["hash_1"]["published"] == 1
        assert usage["accountUsage"]["ig_1"]["published"] == 1
        assert usage["surfaceUsage"]["reel"]["published"] == 1
        assert usage["surfaceUsage"]["story"]["draft"] == 1
        assert asset["usage"]["posts"][0]["surface"] == "reel"
        assert any(w["type"] == "exact_render_published" for w in usage["warnings"])
        assert any(w["type"] == "source_family_reuse" for w in usage["warnings"])
    finally:
        cf.close()


def test_sync_threadsdash_account_assignments_imports_calendar_accounts(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            return [
                {
                    "id": "post_1",
                    "status": "scheduled",
                    "platform": "instagram",
                    "media_type": "reel",
                    "ig_media_type": "REELS",
                    "account_id": "remote_account_1",
                    "instagram_account_id": "ig_1",
                    "scheduled_for": "2026-05-20T14:00:00+00:00",
                    "metadata": {
                        "campaign_factory": {
                            "campaign_id": "may",
                            "source_asset_id": "src_1",
                            "rendered_asset_id": "asset_1",
                        }
                    },
                }
            ]

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        imported = cf.import_folder(folder, campaign_slug="may", model_slug="model")
        source = imported["imported"][0]
        cf.conn.execute("UPDATE source_assets SET id = 'src_1' WHERE id = ?", (source["id"],))
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_1', ?, 'src_1', 'hash_1', ?, ?, 'ok.mp4', 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?)
            """,
            (source["campaign_id"], str(rendered_path), str(rendered_path), now, now),
        )
        cf.conn.commit()

        first = sync_threadsdash_account_assignments(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        second = sync_threadsdash_account_assignments(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assignments = cf.assignments_for_campaign("may")
        assert first["inserted"] == 1
        assert second["inserted"] == 0
        assert assignments[0]["rendered_asset_id"] == "asset_1"
        assert assignments[0]["account_id"] is None
        assert assignments[0]["instagram_account_id"] == "ig_1"
        assert assignments[0]["planned_window_start"] == "2026-05-20T14:00:00+00:00"
    finally:
        cf.close()


def test_sync_threadsdash_instagram_accounts_imports_real_stacey_roster_idempotently(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "instagram_accounts"
            return [
                {
                    "id": "ig_stacey_1",
                    "username": "stacey_ben.x",
                    "display_name": "Stacey",
                    "is_active": True,
                    "status": "active",
                    "needs_reauth": False,
                    "sync_cohort": "hot",
                },
                {
                    "id": "ig_stacey_2",
                    "username": "bennett.lovee",
                    "display_name": "Stacey",
                    "is_active": True,
                    "status": "active",
                    "needs_reauth": False,
                    "sync_cohort": "warm",
                },
                {
                    "id": "ig_stacey_blocked",
                    "username": "stacey_blocked",
                    "display_name": "Stacey",
                    "is_active": False,
                    "status": "needs_reauth",
                    "needs_reauth": True,
                    "sync_cohort": "warm",
                },
                {
                    "id": "ig_lola_1",
                    "username": "lola_main",
                    "display_name": "Lola",
                    "is_active": True,
                    "status": "active",
                    "needs_reauth": False,
                    "sync_cohort": "hot",
                },
            ]

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        first = threadsdash_adapter.sync_threadsdash_instagram_accounts(
            cf,
            creator="Stacey",
            match="stacey",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        second = threadsdash_adapter.sync_threadsdash_instagram_accounts(
            cf,
            creator="Stacey",
            match="stacey",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        rows = [dict(row) for row in cf.conn.execute("SELECT handle, external_id FROM accounts ORDER BY handle").fetchall()]
        assert first["imported"] == 2
        assert first["created"] == 2
        assert first["skipReasons"]["not_eligible"] == 1
        assert first["skipReasons"]["creator_match_failed"] == 1
        assert second["imported"] == 2
        assert second["created"] == 0
        assert rows == [
            {"handle": "bennett.lovee", "external_id": "ig_stacey_2"},
            {"handle": "stacey_ben.x", "external_id": "ig_stacey_1"},
        ]
    finally:
        cf.close()


def test_sync_performance_snapshots_imports_metrics_once(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            assert params["user_id"] == "eq.user_1"
            return rows

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        rows.append({
            "id": "post_1",
            "status": "published",
            "platform": "instagram",
            "account_id": None,
            "instagram_account_id": "ig_1",
            "created_at": "2026-01-02T00:00:00+00:00",
            "updated_at": "2026-01-03T00:00:00+00:00",
            "published_at": "2026-01-02T01:00:00+00:00",
            "permalink": "https://instagram.test/p/1",
            "views": 1200,
            "ig_impressions": 1800,
            "likes_count": 80,
            "ig_comment_count": 9,
            "ig_shares": 14,
            "metadata": {
                "campaign_factory": threadsdash_campaign_factory_metadata(source),
                "metrics": {
                    "saves": 22,
                    "reach": 1100,
                    "watch_time_seconds": 321.5,
                    "metricContractVersion": "instagram_metrics_contract_v1",
                    "metricSurface": "reel",
                    "metricFallbackUsed": False,
                    "metricNames": ["views", "reach", "likes", "comments"],
                },
                "insights": {"likes": 81},
            },
        })
        first = sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        second = sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert first["inserted"] == 1
        assert second["inserted"] == 0
        assert second["updated"] == 1
        graph_counts = {
            row["entity_type"]: row["n"]
            for row in cf.conn.execute("SELECT entity_type, COUNT(*) AS n FROM content_graph_nodes GROUP BY entity_type")
        }
        assert graph_counts["threadsdash_post"] == 1
        assert graph_counts["performance_snapshot"] == 1
        assert graph_counts["recommendation_input"] == 1
        sync_state = cf.conn.execute("SELECT * FROM content_graph_sync_state WHERE system = 'threadsdash.performance'").fetchone()
        assert sync_state is not None
        summary = cf.performance_summary("may")
        asset = summary["renderedAssets"]["asset_1"]
        assert asset["count"] == 1
        assert asset["totals"]["views"] == 1200
        assert asset["totals"]["likes"] == 80
        assert asset["totals"]["saves"] == 22
        assert asset["totals"]["impressions"] == 1800
        assert asset["rates"]["engagementRate"] == pytest.approx((80 + 9 + 14 + 22) / 1800)
        assert asset["latest"]["permalink"] == "https://instagram.test/p/1"
        assert asset["latest"]["contentSurface"] == "reel"
        assert asset["latest"]["metricContract"] == {
            "version": "instagram_metrics_contract_v1",
            "surface": "reel",
            "fallbackUsed": False,
            "metricNames": ["views", "reach", "likes", "comments"],
        }
        assert summary["surfaces"]["reel"]["count"] == 1
    finally:
        cf.close()


def test_sync_performance_snapshots_imports_caption_outcome_context_columns(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            assert params["user_id"] == "eq.user_1"
            return rows

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": "caption_hash_rendered",
            "caption_text": "caption",
            "caption_bank": "question_bank",
            "caption_banks": ["question_bank"],
            "creator_mix": "Lola",
            "creator_model": "lola",
            "frame_type": "mirror_fullbody",
            "length_class": "very_short",
            "format_class": "single_line",
            "caption_fit_version": "v1",
            "suitability_decision": "allowed",
            "suitability_reason": "very_short static caption allowed for mirror_fullbody",
            "render_recipe": "v09_caption_bg",
            "source_clip": "clip_010",
            "rendered_output": "/tmp/caption_outcome.mp4",
            "caption_family_id": "cfam_test",
            "caption_version_id": "cver_test",
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_hash = ?, caption_outcome_context_json = ?, recipe = ? WHERE id = 'asset_1'",
            ("caption_hash_rendered", json.dumps(context, ensure_ascii=False, sort_keys=True), "v09_caption_bg"),
        )
        cf.conn.commit()
        rows.append({
            "id": "post_caption_outcome",
            "status": "published",
            "platform": "instagram",
            "account_id": None,
            "instagram_account_id": "ig_lola_1",
            "created_at": "2026-01-02T00:00:00+00:00",
            "updated_at": "2026-01-03T00:00:00+00:00",
            "published_at": "2026-01-02T01:00:00+00:00",
            "permalink": "https://instagram.test/p/caption-outcome",
            "views": 1400,
            "likes_count": 90,
            "ig_comment_count": 10,
            "ig_shares": 15,
            "metadata": {
                "campaign_factory": threadsdash_campaign_factory_metadata(
                    source,
                    caption_hash="caption_hash_rendered",
                    recipe="v09_caption_bg",
                    context=context,
                ),
                "metrics": {"saves": 24, "reach": 1200, "watch_time_seconds": 330.0},
            },
        })

        result = sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        snapshot = cf.conn.execute("SELECT * FROM performance_snapshots WHERE post_id = 'post_caption_outcome'").fetchone()
        assert result["inserted"] == 1
        assert snapshot["caption_hash"] == "caption_hash_rendered"
        assert snapshot["caption_text"] == "caption"
        assert snapshot["caption_bank"] == "question_bank"
        assert snapshot["creator_mix"] == "Lola"
        assert snapshot["creator_model"] == "lola"
        assert snapshot["frame_type"] == "mirror_fullbody"
        assert snapshot["length_class"] == "very_short"
        assert snapshot["format_class"] == "single_line"
        assert snapshot["caption_fit_version"] == "v1"
        assert snapshot["source_clip"] == "clip_010"
        assert snapshot["caption_family_id"] == "cfam_test"
        assert snapshot["caption_version_id"] == "cver_test"
        assert json.loads(snapshot["caption_outcome_context_json"])["suitability_decision"] == "allowed"
    finally:
        cf.close()


def test_sync_performance_preserves_null_transport_fields_in_caption_context(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            return rows

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": "caption_hash_rendered",
            "caption_text": "caption",
            "caption_bank": "question_bank",
            "caption_banks": ["question_bank"],
            "creator_mix": "Stacey",
            "creator_model": None,
            "frame_type": "closeup",
            "length_class": "long",
            "format_class": "multiline",
            "caption_fit_version": "v1",
            "suitability_decision": "allowed",
            "suitability_reason": "long static caption allowed for closeup",
            "render_recipe": None,
            "source_clip": "clip_009",
            "rendered_output": "/tmp/caption_outcome.mp4",
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_hash = ?, caption_outcome_context_json = ? WHERE id = 'asset_1'",
            ("caption_hash_rendered", json.dumps(context, ensure_ascii=False, sort_keys=True)),
        )
        cf.conn.commit()
        remote_context = dict(context)
        remote_context["render_recipe"] = "reel_ledger_promotion"
        remote_context["creator_model"] = "stacey"
        metadata = threadsdash_campaign_factory_metadata(
            source,
            caption_hash="caption_hash_rendered",
            recipe="reel_ledger_promotion",
            context=remote_context,
        )
        metadata["model_slug"] = "stacey"
        rows.append({
            "id": "post_transport_recipe",
            "status": "published",
            "platform": "instagram",
            "instagram_account_id": "ig_stacey_1",
            "created_at": "2026-01-02T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:00+00:00",
            "published_at": "2026-01-02T01:00:00+00:00",
            "metadata": {"campaign_factory": metadata},
        })

        sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        snapshot = cf.conn.execute("SELECT * FROM performance_snapshots WHERE post_id = 'post_transport_recipe'").fetchone()
        stored_context = json.loads(snapshot["caption_outcome_context_json"])
        assert snapshot["recipe"] == "reel_ledger_promotion"
        assert stored_context["render_recipe"] is None
        assert snapshot["creator_model"] is None
        assert stored_context["creator_model"] is None
    finally:
        cf.close()


def test_performance_summary_includes_read_only_caption_outcome_review(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        campaign_id = cf.campaign_by_slug("may")["id"]
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": "caption_hash_1",
            "caption_text": "caption",
            "caption_bank": "question_bank",
            "caption_banks": ["question_bank"],
            "creator_mix": "Lola",
            "creator_model": "lola",
            "frame_type": "mirror_fullbody",
            "length_class": "very_short",
            "format_class": "single_line",
            "caption_fit_version": "v1",
            "captionPlacementPolicy": "focal_safe_v1",
            "captionPlacementDecision": {"status": "passed", "selectedLane": "bottom"},
            "render_recipe": "v09_caption_bg",
            "source_clip": "clip_010",
            "rendered_output": "/tmp/out.mp4",
        }
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, caption_text, caption_bank, caption_banks_json, creator_mix, creator_model,
             frame_type, length_class, format_class, caption_fit_version, source_clip,
             caption_outcome_context_json, recipe, post_id, platform, status, account_id,
             instagram_account_id, snapshot_at, views, likes, comments, shares, saves, reach,
             watch_time_seconds, metrics_eligible, raw_json, created_at)
            VALUES
            ('perf_caption_review_1', ?, 'asset_1', ?, 'hash_1', ?, 'caption_hash_1',
             'caption', 'question_bank', ?, 'Lola', 'lola', 'mirror_fullbody',
             'very_short', 'single_line', 'v1', 'clip_010', ?, 'v09_caption_bg',
             'post_caption_review_1', 'instagram', 'published', NULL, 'ig_1',
             '2026-01-03T00:00:00+00:00', 1000, 80, 9, 12, 18, 900, 240.0, 1, '{}',
             '2026-01-03T00:00:00+00:00')
            """,
            (
                campaign_id,
                source["id"],
                source["content_hash"],
                json.dumps(["question_bank"]),
                json.dumps(context),
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, caption_text, caption_bank, caption_banks_json, creator_mix, creator_model,
             frame_type, length_class, format_class, caption_fit_version, source_clip,
             caption_outcome_context_json, recipe, post_id, platform, status, account_id,
             instagram_account_id, snapshot_at, views, likes, comments, shares, saves, reach,
             watch_time_seconds, metrics_eligible, raw_json, created_at)
            VALUES
            ('perf_caption_review_ineligible', ?, 'asset_bad', ?, 'hash_bad', ?, 'caption_hash_bad',
             'bad caption', 'bad_bank', ?, 'Lola', 'lola', 'mirror_fullbody',
             'very_short', 'single_line', 'v1', 'clip_bad', ?, 'v00_passthrough',
             'post_bad', 'instagram', 'published', NULL, 'ig_1',
             '2026-01-03T00:00:00+00:00', 9999, 999, 99, 99, 99, 9999, 999.0, 0, '{}',
             '2026-01-03T00:00:00+00:00')
            """,
            (
                campaign_id,
                source["id"],
                source["content_hash"],
                json.dumps(["bad_bank"]),
                json.dumps({**context, "caption_hash": "caption_hash_bad", "caption_bank": "bad_bank"}),
            ),
        )
        cf.conn.commit()

        review = cf.performance_summary("may")["captionOutcomeReview"]
        direct = cf.caption_outcome_report("may")

        assert review["manualReviewOnly"] is True
        assert cf.performance_summary("may")["snapshotCount"] == 1
        assert direct["manualReviewOnly"] is True
        assert direct["campaign"] == "may"
        assert review["coverage"]["snapshotsWithCaptionOutcomeContext"] == 1
        assert review["coverage"]["snapshotsMissingCaptionOutcomeContext"] == 0
        assert review["byCaptionBank"][0]["captionBank"] == "question_bank"
        assert "bad_bank" not in json.dumps(review)
        assert review["byCreatorMix"][0]["creatorMix"] == "Lola"
        assert review["byFrameType"][0]["frameType"] == "mirror_fullbody"
        assert review["byLengthClass"][0]["lengthClass"] == "very_short"
        assert review["byFormatClass"][0]["formatClass"] == "single_line"
        assert review["byCaptionFitVersion"][0]["captionFitVersion"] == "v1"
        assert review["byCaptionPlacementLane"][0]["captionPlacementLane"] == "bottom"
        assert review["byCaptionPlacementStatus"][0]["captionPlacementStatus"] == "passed"
        assert "promote" not in json.dumps(review).lower()
        assert "winner" not in json.dumps(review).lower()
    finally:
        cf.close()


def _approve_asset_for_lifecycle(cf: CampaignFactory, tmp_path: Path):
    source, _ = add_rendered_asset(cf, tmp_path)
    add_audit_report(cf)
    cf.review_rendered_asset("asset_1", decision="approved")
    return source


def _threadsdash_lifecycle_post(
    *,
    post_id: str = "post_1",
    status: str = "draft",
    scheduled_for: str | None = None,
    published_at: str | None = None,
    plan_id: str | None = None,
    rendered_asset_id: str = "asset_1",
    metadata_extra: dict | None = None,
) -> dict:
    campaign_factory = {
        "campaign_id": "may",
        "rendered_asset_id": rendered_asset_id,
        "asset_id": rendered_asset_id,
        "asset_state": "exportable",
        "platform_state": "platform_draft_validated",
        "content_hash": "hash_1",
        "content_fingerprint": "hash_1",
        "caption_hash": "caption_hash_1",
        "publishability_failure_reasons": [],
        "quarantined": False,
    }
    if plan_id:
        campaign_factory["distribution_plan_id"] = plan_id
        campaign_factory["handoff_manifest"] = {
            "manifest_version": 1,
            "asset_id": rendered_asset_id,
            "render_file_id": "render_file_lifecycle",
            "content_fingerprint": "hash_1",
            "caption_hash": "caption_hash_1",
            "captionOutcomeContext": {
                "schema": "campaign_factory.caption_outcome_context.v1",
                "caption_hash": "caption_hash_1",
                "caption_text": "caption",
            },
            "visual_verification_id": "visual_verification_lifecycle",
            "caption_verification_id": "caption_verification_lifecycle",
            "audio_id": "audio_lifecycle",
            "distribution_plan_id": plan_id,
            "exported_by_system": "campaign_factory",
            "exported_at": "2026-01-01T00:00:00+00:00",
        }
    if metadata_extra:
        campaign_factory.update(metadata_extra)
    return {
        "id": post_id,
        "status": status,
        "scheduled_for": scheduled_for,
        "published_at": published_at,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "platform": "instagram",
        "instagram_account_id": "ig_1",
        "metadata": {"campaign_factory": campaign_factory},
    }


def _lifecycle_state(report: dict) -> str:
    assert len(report["rows"]) == 1
    return report["rows"][0]["currentState"]


def test_lifecycle_report_derives_approved_assigned_planned_and_ready_states(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)

        approved = cf.lifecycle_report("may", include_threadsdash="off")
        assert _lifecycle_state(approved) == "creative_approved"
        assert approved["rows"][0]["blockingReason"] == "missing_distribution_plan"

        cf.assign_asset_account("asset_1", instagram_account_id="ig_1")
        assigned = cf.lifecycle_report("may", include_threadsdash="off")
        assert _lifecycle_state(assigned) == "assigned"

        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")
        ready = cf.lifecycle_report("may", include_threadsdash="off")
        assert _lifecycle_state(ready) == "exportable"
        assert ready["rows"][0]["distributionPlanId"] == plan["id"]

        cf.conn.execute("DELETE FROM audit_reports")
        cf.conn.commit()
        blocked = cf.lifecycle_report("may", include_threadsdash="off")
        assert _lifecycle_state(blocked) == "distribution_planned"
        assert blocked["rows"][0]["blockingReason"] == "missing_audit"
    finally:
        cf.close()


def test_lifecycle_report_derives_threadsdash_schedule_states(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")

        draft = cf.lifecycle_report("may", threadsdash_posts=[_threadsdash_lifecycle_post(plan_id=plan["id"])])
        assert _lifecycle_state(draft) == "platform_draft_validated"

        future = cf.lifecycle_report(
            "may",
            threadsdash_posts=[_threadsdash_lifecycle_post(status="scheduled", scheduled_for="2099-01-01T00:00:00+00:00", plan_id=plan["id"])],
        )
        assert _lifecycle_state(future) == "scheduled"
        assert future["rows"][0]["blockingReason"] == "awaiting_publish"

        past_due = cf.lifecycle_report(
            "may",
            threadsdash_posts=[_threadsdash_lifecycle_post(status="scheduled", scheduled_for="2026-01-01T00:00:00+00:00", plan_id=plan["id"])],
        )
        assert _lifecycle_state(past_due) == "past_due_schedule"
        assert past_due["rows"][0]["nextOperatorAction"] == "reschedule_or_manual_publish"
    finally:
        cf.close()


def test_lifecycle_report_derives_published_and_metrics_imported_states(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")
        published = cf.lifecycle_report(
            "may",
            threadsdash_posts=[_threadsdash_lifecycle_post(status="published", published_at="2026-01-02T00:00:00+00:00", plan_id=plan["id"])],
        )
        assert _lifecycle_state(published) == "published"
        assert published["rows"][0]["blockingReason"] == "awaiting_metrics"

        campaign = cf.campaign_by_slug("may")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id, snapshot_at, views, raw_json, created_at)
            VALUES ('perf_1', ?, 'asset_1', ?, 'hash_1', ?, 'caption_hash_1', 'v01_original',
                    'post_1', 'instagram', 'published', 'ig_1', '2026-01-02T01:00:00+00:00', 123, '{}', '2026-01-02T01:00:00+00:00')
            """,
            (campaign["id"], cf.assets_for_campaign(campaign["id"])[0]["id"], cf.assets_for_campaign(campaign["id"])[0]["content_hash"]),
        )
        cf.conn.commit()

        measured = cf.lifecycle_report("may", threadsdash_posts=[_threadsdash_lifecycle_post(status="published", plan_id=plan["id"])])
        assert _lifecycle_state(measured) == "metrics_imported"
        assert measured["summary"]["stateCounts"]["metrics_imported"] == 1
    finally:
        cf.close()


def test_lifecycle_report_ignores_null_report_context_fields_after_metrics_import(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source = _approve_asset_for_lifecycle(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (json.dumps({
                "schema": "campaign_factory.caption_outcome_context.v1",
                "caption_hash": "caption_hash_1",
                "caption_text": "caption",
                "render_recipe": None,
            }),),
        )
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")
        campaign = cf.campaign_by_slug("may")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, caption_outcome_context_json, recipe, post_id, platform, status,
             instagram_account_id, snapshot_at, views, raw_json, created_at)
            VALUES ('perf_1', ?, 'asset_1', ?, 'hash_1', ?, 'caption_hash_1', ?,
                    'v01_original', 'post_1', 'instagram', 'published', 'ig_1',
                    '2026-01-02T01:00:00+00:00', 123, '{}', '2026-01-02T01:00:00+00:00')
            """,
            (
                campaign["id"],
                source["id"],
                source["content_hash"],
                json.dumps({
                    "schema": "campaign_factory.caption_outcome_context.v1",
                    "caption_hash": "caption_hash_1",
                    "caption_text": "caption",
                    "render_recipe": None,
                    "frame_type": None,
                    "length_class": None,
                    "format_class": None,
                    "caption_fit_version": None,
                    "suitability_decision": None,
                    "suitability_reason": None,
                }),
            ),
        )
        cf.conn.commit()

        measured = cf.lifecycle_report("may", threadsdash_posts=[_threadsdash_lifecycle_post(
            status="published",
            plan_id=plan["id"],
            metadata_extra={
                "caption_hash": "caption_hash_1",
                "captionOutcomeContext": {
                    "schema": "campaign_factory.caption_outcome_context.v1",
                    "caption_hash": "caption_hash_1",
                    "caption_text": "caption",
                    "render_recipe": None,
                    "frame_type": None,
                },
            },
        )])

        assert _lifecycle_state(measured) == "metrics_imported"
        assert measured["summary"]["stateCounts"]["metrics_imported"] == 1
        assert measured["summary"]["stuckCounts"] == {}
        assert measured["rows"][0]["evidence"]["lineageMismatch"] == {}
    finally:
        cf.close()


def test_lifecycle_report_marks_resolved_past_due_draft_without_rescheduling(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")
        report = cf.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    post_id="8ee460e1-4f4e-4298-9597-462223b3f5cb",
                    status="draft",
                    scheduled_for=None,
                    plan_id=plan["id"],
                    metadata_extra={
                        "past_due_schedule": True,
                        "previous_scheduled_for": "2026-06-04T14:00:00+00:00",
                    },
                )
            ],
        )
        assert _lifecycle_state(report) == "platform_draft_validated"
        assert report["rows"][0]["evidence"]["pastDueScheduleResolved"] is True
        assert report["rows"][0]["threadsDashboardPostId"] == "8ee460e1-4f4e-4298-9597-462223b3f5cb"
    finally:
        cf.close()


def test_lifecycle_report_marks_invalid_export_payload_as_failed(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")
        report = cf.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    post_id="8ee460e1-4f4e-4298-9597-462223b3f5cb",
                    status="draft",
                    plan_id=plan["id"],
                    metadata_extra={
                        "invalid_export_payload": True,
                        "invalid_reason": "threadsdash_draft_media_invalid_missing_burned_captions",
                        "invalidated_at": "2026-06-05T00:00:00Z",
                    },
                )
            ],
        )
        assert _lifecycle_state(report) == "failed"
        assert report["rows"][0]["blockingReason"] == "threadsdash_draft_media_invalid_missing_burned_captions"
        assert report["rows"][0]["nextOperatorAction"] == "replace_draft_with_verified_captioned_asset"
        assert report["rows"][0]["evidence"]["mediaValidation"]["source"] == "threadsdash_metadata"
    finally:
        cf.close()


def test_creator_os_lifecycle_dashboard_summarizes_lifecycle_states_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")
        before = cf.conn.total_changes

        dashboard = cf.creator_os_lifecycle_dashboard(
            campaign="may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    status="scheduled",
                    scheduled_for="2099-01-01T00:00:00+00:00",
                    plan_id=plan["id"],
                )
            ],
        )

        assert cf.conn.total_changes == before
        assert dashboard["schema"] == "creator_os.lifecycle_dashboard.v1"
        assert dashboard["campaign"] == "may"
        assert dashboard["counts"]["approved"] == 0
        assert dashboard["counts"]["publishable"] == 0
        assert dashboard["counts"]["exported"] == 0
        assert dashboard["counts"]["scheduled"] == 1
        assert dashboard["counts"]["published"] == 0
        assert dashboard["counts"]["metricsImported"] == 0
        assert dashboard["counts"]["quarantined"] == 0
        assert dashboard["counts"]["failed"] == 0
        assert dashboard["commandCenter"]["scheduled"] == 1
        assert dashboard["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_lifecycle_dashboard_counts_quarantined_separately(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        cf.quarantine_asset("asset_1", reason="operator_quarantine", root_cause="qc_failure")
        before = cf.conn.total_changes

        dashboard = cf.creator_os_lifecycle_dashboard(campaign="may", include_threadsdash="off")

        assert cf.conn.total_changes == before
        assert dashboard["counts"]["quarantined"] == 1
        assert dashboard["counts"]["failed"] == 0
        assert dashboard["rows"][0]["bucket"] == "quarantined"
        assert dashboard["rows"][0]["currentState"] == "failed"
        assert dashboard["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_lifecycle_dashboard_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "lifecycle-dashboard",
            "--campaign",
            "may",
            "--include-threadsdash",
            "off",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.lifecycle_dashboard.v1"
    assert payload["counts"]["approved"] == 1
    assert payload["wouldWrite"] is False


def test_lifecycle_report_cli_outputs_json_and_filters_state(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
    finally:
        cf.close()

    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        "REEL_FACTORY_ROOT": str(tmp_path / "reel_factory"),
        "CONTENTFORGE_ROOT": str(tmp_path / "contentforge"),
        "THREADSDASH_ROOT": str(tmp_path / "ThreadsDashboard"),
        "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "lifecycle-report",
            "--campaign",
            "may",
            "--include-threadsdash",
            "off",
            "--state",
            "creative_approved",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.lifecycle_report.v1"
    assert payload["summary"]["stateCounts"] == {"creative_approved": 1}
    assert payload["rows"][0]["currentState"] == "creative_approved"


def test_performance_summary_builds_hook_recipe_audio_leaderboards(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        campaign_id = cf.campaign_by_slug("may")["id"]
        meta = {
            "campaign_factory": {
                "campaign_id": "may",
                "source_asset_id": source["id"],
                "rendered_asset_id": "asset_1",
                "content_hash": "hash_1",
                "source_content_hash": source["content_hash"],
                "caption_hash": "caption_hash_1",
                "recipe": "v01_original",
                "caption_generation": {
                    "referencePattern": {
                        "clusterKey": "caption_led_visual::direct_response::question_hook",
                        "label": "Question hook",
                        "hookType": "question_hook",
                        "visualFormat": "mirror_selfie",
                    }
                },
                "source_prompt": {
                    "schema": "campaign_factory.finished_video_intake.v1",
                    "formatType": "mirror_selfie",
                    "promptId": "prompt_1",
                    "modelProfile": "soul_main",
                    "referencePattern": "caption_led_visual::direct_response::question_hook",
                    "strategy": {"primaryMetric": "views_reach"},
                    "generatedAssetLineage": {
                        "schema": "campaign_factory.generated_asset_lineage.v1",
                        "source": {
                            "referenceId": "ref_1",
                            "patternCardId": "pattern_1",
                            "promptId": "prompt_1",
                            "formatType": "mirror_selfie",
                        },
                        "generation": {"tool": "higgsfield_kling_manual", "modelProfile": "soul_main"},
                        "review": {"humanReviewRequired": True, "status": "draft"},
                    },
                },
                "audio_intent": {
                    "schema": "pipeline.audio_intent.v1",
                    "status": "recommended",
                    "recommendations": [{
                        "audio_title": "Runway Pop",
                        "artist_name": "DJ A",
                        "platform_audio_id": "ig_audio_1",
                        "platform_url": "https://instagram.com/audio/1",
                    }],
                },
            }
        }
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, account_id, instagram_account_id,
             permalink, published_at, snapshot_at, views, likes, comments, shares, saves, reach,
             watch_time_seconds, metrics_eligible, raw_json, created_at)
            VALUES
            ('perf_lb_1', ?, 'asset_1', ?, 'hash_1', ?, 'caption_hash_1',
             'v01_original', 'post_lb_1', 'instagram', 'published', NULL, 'ig_1',
             'https://instagram.test/p/lb1', '2026-01-02T00:00:00+00:00',
             '2026-01-03T00:00:00+00:00', 1000, 80, 9, 12, 18, 900, 240.0, 1, ?, '2026-01-03T00:00:00+00:00')
            """,
            (
                campaign_id,
                source["id"],
                source["content_hash"],
                json.dumps({"metadata": meta}),
            ),
        )
        cf.conn.commit()

        summary = cf.performance_summary("may")
        leaderboards = summary["leaderboards"]

        assert leaderboards["hooks"][0]["hook"]["key"] == "caption_led_visual::direct_response::question_hook"
        assert leaderboards["hooks"][0]["performance"]["totals"]["saves"] == 18
        assert leaderboards["recipes"][0]["recipe"] == "v01_original"
        assert leaderboards["audioRecommendations"][0]["audio"]["platformAudioId"] == "ig_audio_1"
        assert leaderboards["referenceFormats"][0]["referenceFormat"]["key"] == "mirror_selfie"
        assert leaderboards["promptPatterns"][0]["promptPattern"]["key"] == "caption_led_visual::direct_response::question_hook"
        assert leaderboards["promptPatterns"][0]["promptPattern"]["primaryMetric"] == "views_reach"
        assert leaderboards["patternCards"][0]["patternCard"]["key"] == "pattern_1"
        assert leaderboards["modelAccounts"][0]["modelAccount"]["modelProfile"] == "soul_main"
        assert leaderboards["captionFormulas"][0]["captionFormula"]["label"] == "question_hook"
        assert leaderboards["hookRecipeCombos"][0]["recipe"] == "v01_original"
        assert leaderboards["formatRecipeCombos"][0]["recipe"] == "v01_original"
        assert leaderboards["formatAudioCombos"][0]["audio"]["audioTitle"] == "Runway Pop"
        assert leaderboards["hookAudioCombos"][0]["audio"]["audioTitle"] == "Runway Pop"
        assert leaderboards["hookRecipeAudioCombos"][0]["renderedAssetIds"] == ["asset_1"]
        assert summary["snapshots"][0]["dimensions"]["audio"]["platformUrl"] == "https://instagram.com/audio/1"
        assert summary["snapshots"][0]["dimensions"]["referenceFormat"]["label"] == "mirror_selfie"
        assert summary["snapshots"][0]["dimensions"]["patternCard"]["key"] == "pattern_1"
    finally:
        cf.close()


def test_dashboard_returns_performance_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        campaign_id = cf.campaign_by_slug("may")["id"]
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, account_id, instagram_account_id,
             published_at, snapshot_at, views, likes, comments, shares, saves, reach,
             watch_time_seconds, raw_json, created_at)
            VALUES
            ('perf_1', ?, 'asset_1', ?, 'hash_1', 'source_hash_1',
             ?, 'v01_original', 'post_1', 'instagram', 'published', NULL, 'ig_1',
             '2026-01-02T00:00:00+00:00', '2026-01-03T00:00:00+00:00', 500, 40, 3, 7, 9, 450,
             100.0, '{}', '2026-01-03T00:00:00+00:00')
            """,
            (
                campaign_id,
                cf.rendered_asset("asset_1")["source_asset_id"],
                threadsdash_adapter._text_hash("caption"),
            ),
        )
        cf.conn.commit()
        asset = cf.dashboard("may")["rendered"][0]
        assert asset["latestPerformance"]["metrics"]["views"] == 500
        assert asset["sourcePerformance"]["count"] == 1
        assert asset["captionPerformance"]["count"] == 1
        assert asset["recipePerformance"]["count"] == 1
        assert asset["performanceScore"] is not None
    finally:
        cf.close()


def test_performance_api_endpoints_sync_and_summarize(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    settings = cf.settings
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            return rows

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        rows.append({
            "id": "post_api_1",
            "status": "published",
            "platform": "instagram",
            "instagram_account_id": "ig_1",
            "created_at": "2026-01-02T00:00:00+00:00",
            "views_count": 333,
            "ig_impressions": 444,
            "ig_reach": 400,
                "metadata": {
                    "campaign_factory": threadsdash_campaign_factory_metadata(source),
                    "insights": {"likes": 21, "shares": 4, "saves": 6},
                },
            })
    finally:
        cf.close()

    client = TestClient(app_module.app)
    sync = client.post("/api/sync-performance", json={
        "campaign": "may",
        "userId": "user_1",
        "supabaseUrl": "https://example.supabase.co",
        "supabaseServiceRoleKey": "service-role",
    })
    assert sync.status_code == 200
    assert sync.json()["inserted"] == 1
    summary = client.get("/api/performance-summary", params={"campaign": "may"})
    assert summary.status_code == 200
    data = summary.json()
    assert data["renderedAssets"]["asset_1"]["totals"]["views"] == 333
    assert data["renderedAssets"]["asset_1"]["totals"]["impressions"] == 444
    assert data["renderedAssets"]["asset_1"]["totals"]["reach"] == 400
    assert data["captionHashes"]["caption_hash_1"]["totals"]["likes"] == 21


def test_supabase_preflight_checks_bucket_and_required_schema(monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def get_storage_bucket(self, bucket):
            assert bucket == "media"
            return {"id": "media", "name": "media", "public": True}

        def select(self, table, params):
            assert table in {"posts", "media"}
            assert "select" in params
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    result = preflight_supabase(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
        supabase_storage_bucket="media",
    )
    assert result["ok"] is True
    assert {check["name"] for check in result["checks"]} == {
        "auth_posts_read",
        "media_bucket_exists",
        "media_schema",
        "posts_schema",
    }


def test_verify_threadsdash_export_blocks_non_draft_posts(monkeypatch):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "media":
                return [{
                    "id": "media_1",
                    "file_type": "video",
                    "file_url": "https://example/media.mp4",
                    "storage_url": "https://example/media.mp4",
                    "storage_path": "user/media.mp4",
                }]
            if table == "posts":
                return [{
                    "id": "post_1",
                    "platform": "instagram",
                    "status": "scheduled",
                    "scheduled_for": "2026-01-02T00:00:00+00:00",
                    "media_type": "reel",
                    "ig_media_type": "REELS",
                    "metadata": {"campaign_factory": {"rendered_asset_id": "asset_1"}},
                }]
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    result = verify_threadsdash_export(
        export_result_or_path={
            "campaign": "may",
            "supabase": {
                "media": [{"id": "media_1"}],
                "posts": [{"id": "post_1"}],
            },
        },
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
    )
    assert result["ok"] is False
    assert any("post_status:scheduled" in reason for reason in result["blockingReasons"])
    assert any("scheduled_for_not_null" in reason for reason in result["blockingReasons"])


def test_safe_live_smoke_exports_one_draft_and_verifies(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    media_rows = {}
    post_rows = {}

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def get_storage_bucket(self, bucket):
            return {"id": bucket, "name": bucket}

        def upload_storage_object(self, bucket, storage_path, file_path, content_type):
            assert bucket == "media"
            assert file_path.exists()

        def insert_with_fallback(self, table, row, fallback_remove):
            if table == "media":
                media_id = f"media_{len(media_rows) + 1}"
                stored = {"id": media_id, **row}
                media_rows[media_id] = stored
                return stored
            if table == "posts":
                post_id = f"post_{len(post_rows) + 1}"
                stored = {"id": post_id, **row}
                post_rows[post_id] = stored
                return stored
            raise AssertionError(table)

        def select(self, table, params):
            if table == "media":
                media_id = (params.get("id") or "").removeprefix("eq.")
                return [media_rows[media_id]] if media_id in media_rows else []
            if table == "posts":
                post_id = (params.get("id") or "").removeprefix("eq.")
                if post_id:
                    return [post_rows[post_id]] if post_id in post_rows else []
                return []
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        ensure_exportable_distribution_plan(cf)
        result = safe_live_smoke_export(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            supabase_storage_bucket="media",
        )
        assert result["ok"] is True
        assert result["export"]["draftCount"] == 1
        assert len(post_rows) == 1
        post = next(iter(post_rows.values()))
        assert post["status"] == "draft"
        assert post["platform"] == "instagram"
        assert post["scheduled_for"] is None
        assert post["metadata"]["campaign_factory"]["rendered_asset_id"] == "asset_1"
    finally:
        cf.close()


def test_export_can_target_one_rendered_asset(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        second_path = tmp_path / "second.mp4"
        second_path.write_bytes(b"rendered 2")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_2', ?, ?, 'hash_2', ?, ?, 'second.mp4', 'caption two', 'v01_original', 'approved_candidate', 'approved', ?, ?)
            """,
            (source["campaign_id"], source["id"], str(second_path), str(second_path), now, now),
        )
        cf.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf, rendered_asset_id="asset_2", audit_id="audit_2")
        cf.conn.commit()
        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=True,
            rendered_asset_ids=["asset_2"],
        )
        assert result["draftCount"] == 1
        assert result["payload"]["drafts"][0]["renderedAssetId"] == "asset_2"
    finally:
        cf.close()


def test_activity_and_pipeline_job_tables_initialize_and_helpers_work(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        tables = {
            row["name"]
            for row in cf.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert "activity_events" in tables
        assert "pipeline_jobs" in tables

        campaign = cf.upsert_campaign("may", "model")
        job = cf.create_pipeline_job("import_folder", campaign["id"], {"supabaseServiceRoleKey": "secret"})
        assert job["status"] == "queued"
        assert job["input"]["supabaseServiceRoleKey"] == "<redacted>"
        cf.start_pipeline_job(job["id"])
        cf.record_event(
            "source_imported",
            campaign_id=campaign["id"],
            pipeline_job_id=job["id"],
            status="success",
            message="test event",
            metadata={"service_role_key": "secret", "count": 1},
        )
        finished = cf.finish_pipeline_job(job["id"], {"ok": True})
        assert finished["status"] == "succeeded"
        events = cf.events_for_campaign("may")
        assert events[0]["message"] == "test event"
        assert events[0]["metadata"]["service_role_key"] == "<redacted>"
        assert cf.jobs_for_campaign("may")[0]["id"] == job["id"]
    finally:
        cf.close()


def test_import_prepare_and_review_emit_activity_and_jobs(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    (folder / "ignore.txt").write_text("ignore")
    cf = make_factory(tmp_path)
    try:
        first = cf.import_folder(folder, campaign_slug="may", model_slug="model")
        second = cf.import_folder(folder, campaign_slug="may", model_slug="model")
        assert first["pipelineJobId"]
        assert second["pipelineJobId"]
        assert len(second["duplicates"]) == 1

        prepared = cf.prepare_reel_inputs(campaign_slug="may", hooks=["hook"], recipes=["v01_original"])
        assert prepared["pipelineJobId"]

        source = cf.assets_for_campaign(cf.campaign_by_slug("may")["id"])[0]
        rendered_path = tmp_path / "review.mp4"
        rendered_path.write_bytes(b"rendered")
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, 'review.mp4', 'caption', 'v01_original', 'pending', 'draft', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (source["campaign_id"], source["id"], str(rendered_path), str(rendered_path)),
        )
        cf.conn.commit()
        cf.review_rendered_asset("asset_1", decision="rejected", notes="bad")

        event_types = [event["eventType"] for event in cf.events_for_campaign("may", limit=50)]
        assert "source_imported" in event_types
        assert "source_duplicate_ignored" in event_types
        assert "reel_inputs_prepared" in event_types
        assert "asset_rejected" in event_types
        job_types = [job["jobType"] for job in cf.jobs_for_campaign("may")]
        assert "import_folder" in job_types
        assert "prepare_reel" in job_types
    finally:
        cf.close()


def test_run_reel_failure_records_failed_job_and_event(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 7, stdout="", stderr="render failed")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.import_folder(folder, campaign_slug="may", model_slug="model")
        cf.prepare_reel_inputs(campaign_slug="may", hooks=["hook"])
        result = cf.run_reel_factory(campaign_slug="may")
        assert result["returncode"] == 7
        job = cf.pipeline_job(result["pipelineJobId"])
        assert job["status"] == "failed"
        events = cf.events_for_campaign("may")
        assert any(event["eventType"] == "reel_render_failed" for event in events)
    finally:
        cf.close()


def test_export_live_job_redacts_secrets_and_records_ids(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    media_rows = {}
    post_rows = {}

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url
            self.service_role_key = service_role_key

        def upload_storage_object(self, bucket, storage_path, file_path, content_type):
            assert file_path.exists()

        def insert_with_fallback(self, table, row, fallback_remove):
            if table == "media":
                media_id = f"media_{len(media_rows) + 1}"
                media_rows[media_id] = {"id": media_id, **row}
                return media_rows[media_id]
            if table == "posts":
                post_id = f"post_{len(post_rows) + 1}"
                post_rows[post_id] = {"id": post_id, **row}
                return post_rows[post_id]
            raise AssertionError(table)

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        ensure_exportable_distribution_plan(cf)
        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=False,
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        job = cf.pipeline_job(result["pipelineJobId"])
        serialized = json.dumps(job, sort_keys=True)
        assert "service-role" not in serialized
        assert job["status"] == "succeeded"
        assert job["result"]["postIds"] == ["post_1"]
        assert job["result"]["mediaIds"] == ["media_1"]
        events = cf.events_for_campaign("may")
        assert any(event["eventType"] == "threadsdash_export_created" for event in events)
    finally:
        cf.close()


def test_activity_and_jobs_api_return_newest_first(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    settings = cf.settings
    try:
        campaign = cf.upsert_campaign("may", "model")
        older = cf.create_pipeline_job("import_folder", campaign["id"], {})
        newer = cf.create_pipeline_job("prepare_reel", campaign["id"], {})
        cf.record_event("source_imported", campaign_id=campaign["id"], pipeline_job_id=older["id"], message="older")
        cf.record_event("reel_inputs_prepared", campaign_id=campaign["id"], pipeline_job_id=newer["id"], message="newer")
    finally:
        cf.close()

    monkeypatch.setattr(app_module, "settings", settings)
    client = TestClient(app_module.app)
    activity = client.get("/api/activity-log", params={"campaign": "may", "limit": 10})
    assert activity.status_code == 200
    assert activity.json()["events"][0]["message"] == "newer"
    jobs = client.get("/api/jobs", params={"campaign": "may", "limit": 10})
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["id"] == newer["id"]
    job = client.get(f"/api/jobs/{newer['id']}")
    assert job.status_code == 200
    assert job.json()["jobType"] == "prepare_reel"


def test_campaign_health_asset_detail_ranking_and_api(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    settings = cf.settings
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.campaign_by_slug("may")
        failed = cf.create_pipeline_job("run_reel", campaign["id"], {})
        cf.start_pipeline_job(failed["id"])
        cf.fail_pipeline_job(failed["id"], "old failure")
        succeeded = cf.create_pipeline_job("run_reel", campaign["id"], {})
        cf.start_pipeline_job(succeeded["id"])
        cf.finish_pipeline_job(succeeded["id"], {"ok": True})
        health = cf.campaign_health("may")
        assert health["counts"]["sourcesImported"] == 1
        assert health["counts"]["renderedAssets"] == 1
        assert health["counts"]["auditedAssets"] == 1
        assert health["counts"]["approvedAssets"] == 1
        assert health["counts"]["exportReadyAssets"] == 1
        assert health["counts"]["failedJobs"] == 0

        detail = cf.asset_detail("asset_1")
        assert detail["asset"]["id"] == "asset_1"
        assert detail["source"]["id"] == detail["asset"]["source_asset_id"]
        assert detail["audits"][0]["id"] == "audit_1"
        assert detail["ranking"]["score"] > 0

        readiness = cf.campaign_readiness("may", user_id="user_1")
        assert readiness["ready"] is True
        assert readiness["health"]["counts"]["approvedAssets"] == 1
        ranking = cf.ranking("may")
        assert ranking["assets"][0]["renderedAssetId"] == "asset_1"
        assert ranking["assets"][0]["breakdown"]["sourceHistory"] == 50
    finally:
        cf.close()

    monkeypatch.setattr(app_module, "settings", settings)
    client = TestClient(app_module.app)
    assert client.get("/api/campaign-health", params={"campaign": "may"}).status_code == 200
    assert client.get("/api/asset-detail/asset_1").status_code == 200
    assert client.get("/api/ranking", params={"campaign": "may"}).status_code == 200
    assert client.get("/api/autonomy-policy").json()["level"] == "level_2"
    set_policy_response = client.post("/api/autonomy-policy", json={"level": "level_2"})
    assert set_policy_response.status_code == 200
    trust_response = client.get("/api/trust-summary", params={"campaign": "may"})
    assert trust_response.status_code == 200
    assert trust_response.json()["schema"] == "campaign_factory.trust_summary.v1"
    recommend_response = client.post("/api/recommendations/run", json={"campaign": "may", "count": 3, "persist": True})
    assert recommend_response.status_code == 200
    assert recommend_response.json()["schema"] == "campaign_factory.recommendations.next_batch.v1"
    assert recommend_response.json()["items"][0]["renderedAssetId"] == "asset_1"
    recommendation_item_id = recommend_response.json()["items"][0]["recommendationId"]
    accept_response = client.post(f"/api/recommendations/{recommendation_item_id}/accept", json={"operator": "api_user"})
    assert accept_response.status_code == 200
    assert accept_response.json()["status"] == "accepted"
    link_response = client.post(f"/api/recommendations/{recommendation_item_id}/link", json={"renderedAssetId": "asset_1"})
    assert link_response.status_code == 200
    assert link_response.json()["status"] == "executed"
    execute_response = client.post(f"/api/recommendations/{recommendation_item_id}/execute", json={"runAudit": False})
    assert execute_response.status_code == 200
    assert execute_response.json()["recommendation"]["status"] == "executed"
    memory_rebuild_response = client.post("/api/account-memory/rebuild", json={"campaign": "may"})
    assert memory_rebuild_response.status_code == 200
    memory_response = client.get("/api/account-memory", params={"campaign": "may"})
    assert memory_response.status_code == 200
    exceptions_response = client.get("/api/exceptions", params={"campaign": "may", "status": "open"})
    assert exceptions_response.status_code == 200
    stored_recommendations = client.get("/api/recommendations", params={"campaign": "may"})
    assert stored_recommendations.status_code == 200
    assert stored_recommendations.json()["runs"][0]["items"][0]["renderedAssetId"] == "asset_1"
    accuracy_response = client.get("/api/recommendations/accuracy", params={"campaign": "may", "windowDays": 365})
    assert accuracy_response.status_code == 200
    assert accuracy_response.json()["schema"] == "campaign_factory.recommendation_accuracy_report.v1"
    ready_response = client.post("/api/campaign-readiness", json={"campaign": "may", "userId": "user_1"})
    assert ready_response.status_code == 200
    assert ready_response.json()["ready"] is True


def test_account_assignment_drives_draft_destinations_and_metadata(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    inserted: list[tuple[str, dict]] = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def upload_storage_object(self, bucket, storage_path, file_path, content_type):
            pass

        def insert_with_fallback(self, table, row, fallback_remove):
            inserted.append((table, dict(row)))
            return {"id": f"{table}_1", **row}

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        assignment = cf.assign_asset_account(
            "asset_1",
            instagram_account_id="ig_acc_1",
            planned_window_start="2026-05-15T10:00:00-04:00",
            planned_window_end="2026-05-15T12:00:00-04:00",
            notes="morning test",
        )
        assert assignment["instagram_account_id"] == "ig_acc_1"

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        draft = payload["drafts"][0]
        assert draft["accountId"] is None
        assert draft["instagramAccountId"] == "ig_acc_1"
        assert draft["plannedWindowStart"] == "2026-05-15T10:00:00-04:00"
        assert draft["plannedWindowEnd"] == "2026-05-15T12:00:00-04:00"
        draft_metadata = draft["metadata"]["campaign_factory"]
        assert draft_metadata["planned_window_start"] == "2026-05-15T10:00:00-04:00"
        assert draft_metadata["planned_window_end"] == "2026-05-15T12:00:00-04:00"
        assert draft_metadata["assignment_notes"] == "morning test"
        cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_acc_1",
            planned_window_start="2026-05-15T10:00:00-04:00",
            planned_window_end="2026-05-15T12:00:00-04:00",
            reason_code="morning test",
        )

        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=False,
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        assert result["supabase"]["attempted"] is True
        post_row = next(row for table, row in inserted if table == "posts")
        assert post_row["instagram_account_id"] == "ig_acc_1"
        metadata = post_row["metadata"]["campaign_factory"]
        assert metadata["planned_window_start"] == "2026-05-15T10:00:00-04:00"
        assert metadata["planned_window_end"] == "2026-05-15T12:00:00-04:00"
        assert metadata["distribution_reason_code"] == "morning test"
    finally:
        cf.close()


def test_account_plan_warns_on_batch_volume_and_api_assigns(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    settings = cf.settings
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        for idx in (2, 3):
            rendered_path = tmp_path / f"asset_{idx}.mp4"
            rendered_path.write_bytes(f"rendered {idx}".encode())
            cf.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'caption', 'v01_original', 'approved_candidate', 'approved', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """,
                (f"asset_{idx}", source["campaign_id"], source["id"], f"hash_{idx}", str(rendered_path), str(rendered_path), rendered_path.name),
            )
            cf.conn.commit()
            add_audit_report(cf, rendered_asset_id=f"asset_{idx}", audit_id=f"audit_{idx}")
            cf.assign_asset_account(f"asset_{idx}", instagram_account_id="ig_shared")
        cf.assign_asset_account("asset_1", instagram_account_id="ig_shared")
        plan = cf.account_plan("may", user_id="user_1")
        assert len(plan["rows"]) == 3
        assert "account_batch_volume_review" in plan["warnings"]
    finally:
        cf.close()

    monkeypatch.setattr(app_module, "settings", settings)
    client = TestClient(app_module.app)
    response = client.post("/api/asset-account-assignment", json={
        "renderedAssetId": "asset_1",
        "instagramAccountId": "ig_extra",
    })
    assert response.status_code == 200
    account_plan = client.get("/api/account-plan", params={"campaign": "may", "userId": "user_1"})
    assert account_plan.status_code == 200
    assert any(row["instagramAccountId"] == "ig_extra" for row in account_plan.json()["rows"])


def test_ranking_uses_performance_but_keeps_blocked_assets_low(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.review_rendered_asset("asset_1", decision="approved")
        blocked_path = tmp_path / "blocked.mp4"
        blocked_path.write_bytes(b"blocked")
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_blocked', ?, ?, 'hash_blocked', ?, ?, 'blocked.mp4', 'caption', 'v01_original', 'pending', 'draft', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (source["campaign_id"], source["id"], str(blocked_path), str(blocked_path)),
        )
        campaign_id = cf.campaign_by_slug("may")["id"]
        caption_hash = threadsdash_adapter._text_hash("caption")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, account_id, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, watch_time_seconds, raw_json, created_at)
            VALUES
            ('perf_good', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_1', 'instagram', 'published',
             NULL, 'ig_1', '2026-01-03T00:00:00+00:00', 10000, 800, 80, 100, 120, 9000, 500.0, '{}', '2026-01-03T00:00:00+00:00')
            """,
            (campaign_id, source["id"], source["content_hash"], caption_hash),
        )
        cf.conn.commit()

        ranking = cf.ranking("may")
        by_asset = ranking["byAsset"]
        assert by_asset["asset_1"]["breakdown"]["sourceHistory"] > 50
        assert by_asset["asset_1"]["score"] > by_asset["asset_blocked"]["score"]
        assert by_asset["asset_blocked"]["score"] <= 35
        assert "blocked assets stay low regardless of performance" in by_asset["asset_blocked"]["reasons"]
    finally:
        cf.close()


def _manager_report_fixture(*, accounts: list[dict], missed: list[dict] | None = None) -> dict:
    buckets = {
        "safe_to_schedule_today": [a for a in accounts if a.get("bucket") == "safe_to_schedule_today"],
        "already_scheduled_today": [a for a in accounts if a.get("bucket") == "already_scheduled_today"],
        "blocked_reauth": [a for a in accounts if a.get("bucket") == "blocked_reauth"],
        "blocked_token_expired": [a for a in accounts if a.get("bucket") == "blocked_token_expired"],
        "blocked_disabled": [a for a in accounts if a.get("bucket") == "blocked_disabled"],
        "blocked_recent_failure": [a for a in accounts if a.get("bucket") == "blocked_recent_failure"],
        "blocked_unknown": [a for a in accounts if a.get("bucket") == "blocked_unknown"],
    }
    return {
        "schema": "threadsdashboard.campaign_schedule_manager_report.v1",
        "accounts": accounts,
        "accountBuckets": buckets,
        "missedDispatches": missed or [],
        "summary": {
            "safeToScheduleCount": len(buckets["safe_to_schedule_today"]),
            "needsPostTodayCount": sum(1 for a in accounts if a.get("needsPostToday")),
            "blockedCount": sum(len(buckets[key]) for key in buckets if key.startswith("blocked_")),
            "missedDispatchCount": len(missed or []),
        },
    }


def _draft_item(
    post_id: str,
    account_id: str,
    *,
    variant_family_id: str | None = None,
    variant_id: str | None = None,
    cooldown: str = "clear",
    instagram_post_caption: str | None = "new post is up",
    handoff_manifest_ok: bool | None = True,
    platform_draft_validated: bool | None = True,
    publishability_state: str | None = "exportable",
    quarantined: bool = False,
    scheduled_for: str = "2026-06-06T16:00:00+00:00",
    content_surface: str = "reel",
) -> dict:
    return {
        "postId": post_id,
        "accountId": account_id,
        "username": f"user_{account_id}",
        "creator": "Stacey",
        "renderedAssetId": f"asset_{post_id}",
        "distributionPlanId": f"dist_{post_id}",
        "variantFamilyId": variant_family_id,
        "variantId": variant_id,
        "platformDraftValidated": platform_draft_validated,
        "handoffManifestOk": handoff_manifest_ok,
        "publishabilityState": publishability_state,
        "quarantined": quarantined,
        "duplicateCheck": "clear",
        "variantCooldownCheck": cooldown,
        "qstashEligible": cooldown == "clear",
        "instagramPostCaption": instagram_post_caption,
        "scheduledFor": scheduled_for,
        "contentSurface": content_surface,
        "wouldWrite": False,
    }


def test_creator_os_daily_plan_is_read_only_and_detects_inventory_shortfall(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        before = cf.conn.total_changes
        accounts = [
            {"accountId": "ig_1", "username": "stacey_one", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_2", "username": "stacey_two", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "validatedDraftsAvailable": 1, "items": [_draft_item("post_1", "ig_1")]},
        )

        assert plan["schema"] == "creator_os.daily_plan.v1"
        assert plan["wouldWrite"] is False
        assert cf.conn.total_changes == before
        stacey = plan["creators"][0]
        assert stacey["creator"] == "Stacey"
        assert stacey["safeAccounts"] == 2
        assert stacey["accountsNeedingPostsToday"] == 2
        assert stacey["validatedDraftsAvailable"] == 1
        assert stacey["inventoryShortfall"] == 1
        assert stacey["managerDecision"] == "needs_reel_factory_inventory"
        assert "create_reel_factory_or_source_inventory" in stacey["recommendedActions"]
    finally:
        cf.close()


def test_creator_os_daily_plan_excludes_blocked_and_already_scheduled_accounts(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_safe", "username": "safe", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_scheduled", "username": "scheduled", "creator": "Stacey", "bucket": "already_scheduled_today", "safeToSchedule": False, "needsPostToday": False, "nextScheduledPost": {"id": "post_s"}},
            {"accountId": "ig_blocked", "username": "blocked", "creator": "Stacey", "bucket": "blocked_reauth", "safeToSchedule": False, "needsPostToday": False, "blockingReason": "needs_reauth"},
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "validatedDraftsAvailable": 1, "items": [_draft_item("post_1", "ig_safe")]},
        )

        by_id = {row["accountId"]: row for row in plan["accounts"]}
        assert by_id["ig_safe"]["needsPostToday"] is True
        assert by_id["ig_safe"]["eligibleDrafts"][0]["draftPostId"] == "post_1"
        assert by_id["ig_scheduled"]["needsPostToday"] is False
        assert by_id["ig_scheduled"]["state"] == "safe"
        assert by_id["ig_blocked"]["state"] == "blocked"
        assert by_id["ig_blocked"]["blockedReason"] == "needs_reauth"
        assert plan["creators"][0]["blockedAccounts"] == 1
        assert plan["creators"][0]["accountsNeedingPostsToday"] == 1
    finally:
        cf.close()


def test_creator_os_daily_plan_respects_variant_cooldowns_and_missed_dispatches(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_cool", "username": "cool", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_missed", "username": "missed", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
        ]
        missed = [{"postId": "post_missed", "accountId": "ig_missed", "blockingReason": "overdue_dispatch_no_publish_attempt"}]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts, missed=missed),
            time_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 2,
                "items": [
                    _draft_item("post_cool", "ig_cool", variant_family_id="vfam_1", variant_id="var_1", cooldown="same_variant_family_within_14_days"),
                    _draft_item("post_missed", "ig_missed"),
                ],
            },
        )

        by_id = {row["accountId"]: row for row in plan["accounts"]}
        assert by_id["ig_cool"]["eligibleDrafts"] == []
        assert by_id["ig_cool"]["variantCooldowns"][0]["variantFamilyId"] == "vfam_1"
        assert by_id["ig_cool"]["variantCooldowns"][0]["reason"] == "same_variant_family_within_14_days"
        assert by_id["ig_missed"]["state"] == "blocked"
        assert by_id["ig_missed"]["blockedReason"] == "overdue_dispatch_no_publish_attempt"
        assert by_id["ig_missed"]["needsPostToday"] is False
        assert "resolve_missed_dispatches_before_scheduling" in plan["creators"][0]["recommendedActions"]
    finally:
        cf.close()


def test_creator_os_daily_plan_cli_outputs_json(tmp_path: Path):
    report_path = tmp_path / "threadsdash_report.json"
    schedule_path = tmp_path / "schedule_plan.json"
    report_path.write_text(json.dumps(_manager_report_fixture(accounts=[
        {"accountId": "ig_cli", "username": "cli", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
    ])), encoding="utf-8")
    schedule_path.write_text(json.dumps({
        "creator": "Stacey",
        "validatedDraftsAvailable": 1,
        "items": [_draft_item("post_cli", "ig_cli")],
    }), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "daily-plan",
            "--creator",
            "Stacey",
            "--threadsdash-report-json",
            str(report_path),
            "--schedule-plan-json",
            str(schedule_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.daily_plan.v1"
    assert payload["wouldWrite"] is False
    assert payload["creators"][0]["accountsNeedingPostsToday"] == 1
    assert payload["accounts"][0]["eligibleDrafts"][0]["draftPostId"] == "post_cli"


def test_creator_os_daily_plan_consumes_winner_expansion_report(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        accounts = [
            {"accountId": f"ig_{idx}", "username": f"stacey_{idx}", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True}
            for idx in range(1, 4)
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "validatedDraftsAvailable": 1, "items": [_draft_item("post_1", "ig_1")]},
            winner_expansion_report={
                "schema": "campaign_factory.winner_expansion_report.v1",
                "recommendations": [{
                    "creator": "Stacey",
                    "assetId": "asset_parent",
                    "variantFamilyId": "vfam_hot",
                    "reason": "high_views",
                    "recommendedAction": "create_more_variants",
                    "wouldWrite": False,
                }],
            },
        )

        stacey = plan["creators"][0]
        assert cf.conn.total_changes == before
        assert stacey["managerDecision"] == "needs_variants"
        assert stacey["inventoryShortfall"] == 2
        assert stacey["winnerExpansionRecommendations"] == [{
            "parentAssetId": "asset_parent",
            "variantFamilyId": "vfam_hot",
            "reason": "high_views",
            "recommendedAction": "generate_more_variants",
            "recommendedVariantCount": 2,
            "wouldWrite": False,
        }]
        assert "run_contentforge_variant_plan" in stacey["nextSafeActions"]
        assert "run_campaign_schedule_time_plan_then_campaign_schedule" not in stacey["nextSafeActions"]
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_includes_creative_recommended_inventory(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_daily_learning", "stacey")
        for idx, views in enumerate([1000, 1100, 1200], start=1):
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"daily_learning_good_{idx}",
                campaign_id=campaign["id"],
                post_id=f"daily_learning_post_good_{idx}",
                concept_id="mirror_selfie",
                campaign_asset_id="asset_daily_learning_parent",
                parent_reel_id="parent_daily_learning",
                caption_angle="tease",
                audio_id="audio_12",
                content_surface="reel",
                published_at=f"2026-06-06T18:0{idx}:00+00:00",
                views=views,
                reach=views - 100,
                saves=15,
                shares=8,
                followers=2,
            )
        for idx, views in enumerate([100, 110, 120], start=1):
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"daily_learning_weak_{idx}",
                campaign_id=campaign["id"],
                post_id=f"daily_learning_post_weak_{idx}",
                concept_id="generic_feed",
                caption_angle="hard_cta",
                audio_id="audio_44",
                content_surface="feed_single",
                published_at=f"2026-06-06T09:0{idx}:00+00:00",
                views=views,
                reach=views - 20,
                saves=1,
                shares=0,
            )
        cf.conn.commit()
        before = cf.conn.total_changes

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=[
                {"accountId": "ig_daily_learning", "username": "stacey", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            ]),
            schedule_plan={"creator": "Stacey", "validatedDraftsAvailable": 0, "items": []},
            generated_at="2026-06-08T12:00:00+00:00",
        )

        assert cf.conn.total_changes == before
        stacey = plan["creators"][0]
        assert stacey["recommendedInventory"]
        first = stacey["recommendedInventory"][0]
        assert first["sourceSystem"] == "campaign_factory.creative_performance_analysis"
        assert first["reason"]
        assert first["confidence"] == "low"
        assert first["conceptId"] == "mirror_selfie"
        assert first["captionAngle"] == "tease"
        assert first["audioId"] == "audio_12"
        assert first["postingWindow"] == "6pm"
        assert first["wouldWrite"] is False
        assert stacey["creativeLearningReadiness"] == "ready"
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_recommended_inventory_request_plan_translates_daily_plan_into_read_only_batches(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        daily_plan = {
            "schema": "creator_os.daily_plan.v1",
            "creators": [
                {
                    "creator": "Stacey",
                    "inventoryShortfall": 10,
                    "recommendedInventory": [
                        {
                            "sourceSystem": "campaign_factory.creative_performance_analysis",
                            "surface": "reel",
                            "reason": "mirror_selfie is 42.0% above creator baseline using Instagram-visible metrics.",
                            "confidence": "medium",
                            "conceptId": "mirror_selfie",
                            "captionAngle": "tease",
                            "postingWindow": "6pm",
                            "audioId": "audio_12",
                            "storyIntent": "",
                            "parentAssetId": "asset_parent_hot",
                            "scoreLiftPct": 42.0,
                            "wouldWrite": False,
                        },
                        {
                            "sourceSystem": "campaign_factory.creative_performance_analysis",
                            "surface": "story",
                            "reason": "snapchat_promo is 28.0% above creator baseline using Instagram-visible metrics.",
                            "confidence": "medium",
                            "conceptId": "story_concept",
                            "captionAngle": "",
                            "postingWindow": "9pm",
                            "audioId": "",
                            "storyIntent": "snapchat_promo",
                            "parentAssetId": "",
                            "scoreLiftPct": 28.0,
                            "wouldWrite": False,
                        },
                    ],
                }
            ],
            "wouldWrite": False,
        }
        inventory_plan = {
            "schema": "campaign_factory.variant_inventory_plan.v1",
            "executionBatches": [
                {
                    "parentAssetId": "asset_parent_hot",
                    "preset": "caption_safe_v2",
                    "requestedVariants": 6,
                    "minimumRecommended": 3,
                    "operationFamilies": ["cover_frame", "timing_trim", "crop_zoom_family"],
                }
            ],
            "estimatedRecommendedVariants": 6,
            "wouldWrite": False,
        }

        plan = cf.recommended_inventory_request_plan(
            creator="Stacey",
            target_count=10,
            daily_plan=daily_plan,
            variant_inventory_plan=inventory_plan,
        )

        assert cf.conn.total_changes == before
        assert plan["schema"] == "creator_os.recommended_inventory_request_plan.v1"
        assert plan["creator"] == "Stacey"
        assert plan["targetCount"] == 10
        assert plan["existingInventoryCanSatisfy"] == 6
        assert plan["remainingRequestCount"] == 4
        assert plan["wouldWrite"] is False
        first = plan["requestBatches"][0]
        assert first["recommendedAction"] == "create_more_reels"
        assert first["parentAssetId"] == "asset_parent_hot"
        assert first["captionAngle"] == "tease"
        assert first["audioId"] == "audio_12"
        assert first["postingWindow"] == "6pm"
        assert first["targetCount"] == 6
        assert first["existingInventoryAvailable"] == 6
        assert first["reason"] == "mirror_selfie is 42.0% above creator baseline using Instagram-visible metrics."
        assert first["sourceSystem"] == "campaign_factory.creative_performance_analysis"
        assert first["wouldWrite"] is False
        story = [item for item in plan["requestBatches"] if item["surface"] == "story"][0]
        assert story["recommendedAction"] == "create_more_snapchat_promo_stories"
        assert story["storyIntent"] == "snapchat_promo"
        assert story["targetCount"] == 4
        assert plan["canSatisfyFromExistingInventory"] is False
        assert plan["nextSafeAction"] == "review_and_approve_inventory_requests"
    finally:
        cf.close()


def test_recommended_inventory_request_plan_reports_no_recommendations(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        plan = cf.recommended_inventory_request_plan(
            creator="Stacey",
            target_count=5,
            daily_plan={"schema": "creator_os.daily_plan.v1", "creators": [{"creator": "Stacey", "recommendedInventory": []}], "wouldWrite": False},
        )

        assert cf.conn.total_changes == before
        assert plan["requestBatches"] == []
        assert plan["blockingReason"] == "no_recommended_inventory_available"
        assert plan["nextSafeAction"] == "wait_for_more_metrics_or_create_operator_selected_inventory"
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_recommended_inventory_request_plan_cli_outputs_json(tmp_path: Path):
    daily_path = tmp_path / "daily_plan.json"
    inventory_path = tmp_path / "variant_inventory_plan.json"
    daily_path.write_text(json.dumps({
        "schema": "creator_os.daily_plan.v1",
        "creators": [
            {
                "creator": "Stacey",
                "inventoryShortfall": 3,
                "recommendedInventory": [
                    {
                        "sourceSystem": "campaign_factory.creative_performance_analysis",
                        "surface": "reel",
                        "reason": "mirror_selfie is above creator baseline.",
                        "confidence": "low",
                        "conceptId": "mirror_selfie",
                        "captionAngle": "tease",
                        "postingWindow": "6pm",
                        "audioId": "audio_12",
                        "storyIntent": "",
                        "parentAssetId": "asset_parent_cli",
                        "scoreLiftPct": 20,
                        "wouldWrite": False,
                    }
                ],
            }
        ],
        "wouldWrite": False,
    }), encoding="utf-8")
    inventory_path.write_text(json.dumps({
        "schema": "campaign_factory.variant_inventory_plan.v1",
        "executionBatches": [
            {"parentAssetId": "asset_parent_cli", "requestedVariants": 3, "preset": "caption_safe_v2", "operationFamilies": ["cover_frame"]}
        ],
        "wouldWrite": False,
    }), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "recommended-inventory-request-plan",
            "--creator",
            "Stacey",
            "--target-count",
            "3",
            "--daily-plan-json",
            str(daily_path),
            "--variant-inventory-plan-json",
            str(inventory_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.recommended_inventory_request_plan.v1"
    assert payload["requestBatches"][0]["recommendedAction"] == "create_more_reels"
    assert payload["requestBatches"][0]["parentAssetId"] == "asset_parent_cli"
    assert payload["canSatisfyFromExistingInventory"] is True
    assert payload["wouldWrite"] is False


def test_creator_os_daily_plan_prefers_existing_unused_variants_before_generation(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": f"ig_{idx}", "username": f"stacey_{idx}", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True}
            for idx in range(1, 5)
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 2,
                "items": [
                    _draft_item("post_var_1", "ig_1", variant_family_id="vfam_existing", variant_id="var_existing_1"),
                    _draft_item("post_var_2", "ig_2", variant_family_id="vfam_existing", variant_id="var_existing_2"),
                ],
            },
            winner_expansion_report={
                "schema": "campaign_factory.winner_expansion_report.v1",
                "recommendations": [{
                    "creator": "Stacey",
                    "assetId": "asset_winner",
                    "variantFamilyId": "vfam_winner",
                    "reason": "high_reach",
                    "recommendedAction": "create_more_variants",
                }],
            },
        )

        recs = plan["creators"][0]["winnerExpansionRecommendations"]
        assert recs[0]["recommendedAction"] == "fanout_existing_variants"
        assert recs[0]["recommendedVariantCount"] == 2
        assert len(recs) == 1
        assert plan["creators"][0]["managerDecision"] == "needs_variants"
    finally:
        cf.close()


def test_creator_os_daily_plan_without_winners_falls_back_to_reel_factory_inventory(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_1", "username": "stacey_one", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_2", "username": "stacey_two", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "validatedDraftsAvailable": 0, "items": []},
        )

        stacey = plan["creators"][0]
        assert stacey["managerDecision"] == "needs_reel_factory_inventory"
        assert stacey["winnerExpansionRecommendations"] == []
        assert "create_reel_factory_or_source_inventory" in stacey["nextSafeActions"]
        assert "run_campaign_schedule_time_plan_then_campaign_schedule" not in stacey["nextSafeActions"]
    finally:
        cf.close()


def test_creator_os_daily_plan_blocks_draft_missing_instagram_post_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_1", "username": "stacey_one", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 1,
                "items": [_draft_item("post_no_caption", "ig_1", instagram_post_caption="")],
            },
        )

        account = plan["accounts"][0]
        assert account["eligibleDrafts"] == []
        assert account["variantCooldowns"][0]["reason"] == "missing_instagram_post_caption"
        assert account["needsPostToday"] is True
        assert plan["creators"][0]["managerDecision"] == "needs_reel_factory_inventory"
    finally:
        cf.close()


def test_creator_os_daily_plan_reports_draft_exclusion_breakdown(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": f"ig_{idx}", "username": f"stacey_{idx}", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True}
            for idx in range(1, 7)
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 99,
                "items": [
                    _draft_item("post_no_caption", "ig_1", instagram_post_caption=""),
                    _draft_item("post_no_manifest", "ig_2", handoff_manifest_ok=False),
                    _draft_item("post_not_validated", "ig_3", platform_draft_validated=False),
                    _draft_item("post_quarantined", "ig_4", quarantined=True),
                    _draft_item("post_failed", "ig_5", publishability_state="blocked"),
                    _draft_item("post_cooldown", "ig_6", variant_family_id="vfam_1", variant_id="var_1", cooldown="same_variant_family_within_14_days"),
                ],
            },
        )

        stacey = plan["creators"][0]
        assert stacey["validatedDraftsAvailable"] == 0
        assert stacey["scheduleSafeDraftsAvailable"] == 0
        assert stacey["inventoryShortfall"] == 6
        assert stacey["draftsExcluded"] == {
            "missingInstagramPostCaption": 1,
            "missingHandoffManifest": 1,
            "notPlatformDraftValidated": 1,
            "quarantined": 1,
            "publishabilityFailed": 1,
            "variantCooldownBlocked": 1,
        }
        assert stacey["managerDecision"] == "needs_reel_factory_inventory"
        assert all(not row["eligibleDrafts"] for row in plan["accounts"])
    finally:
        cf.close()


def test_creator_os_daily_plan_includes_account_tiers(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_warming", "username": "warming", "creator": "Stacey", "accountState": "warming", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_normal", "username": "normal", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_growth", "username": "growth", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True, "performance": {"views7d": 900, "posts7d": 5}},
            {"accountId": "ig_winner", "username": "winner", "creator": "Stacey", "accountState": "high-performing", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_resting", "username": "resting", "creator": "Stacey", "accountState": "resting", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": False},
            {"accountId": "ig_blocked", "username": "blocked", "creator": "Stacey", "bucket": "blocked_reauth", "safeToSchedule": False, "needsPostToday": False, "blockingReason": "needs_reauth"},
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "items": []},
        )

        by_id = {row["accountId"]: row for row in plan["accounts"]}
        assert by_id["ig_warming"]["accountTier"] == "warming"
        assert by_id["ig_normal"]["accountTier"] == "normal"
        assert by_id["ig_growth"]["accountTier"] == "growth"
        assert by_id["ig_winner"]["accountTier"] == "winner"
        assert by_id["ig_resting"]["accountTier"] == "resting"
        assert by_id["ig_blocked"]["accountTier"] == "blocked"
        assert by_id["ig_winner"]["tierPostingGuidance"]["priority"] == "prioritize_winning_concepts"
        assert by_id["ig_resting"]["tierPostingGuidance"]["recommendedPostCount"] == 0
        assert plan["creators"][0]["accountTierSummary"] == {
            "warming": 1,
            "normal": 1,
            "growth": 1,
            "winner": 1,
            "resting": 1,
            "blocked": 1,
        }
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_account_tiers_report_is_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_winner", "username": "winner", "creator": "Stacey", "safeToSchedule": True, "accountTier": "winner"},
            {"accountId": "ig_blocked", "username": "blocked", "creator": "Stacey", "safeToSchedule": False, "blockingReason": "token_expired"},
        ]
        before = cf.conn.total_changes

        report = cf.creator_os_account_tiers(
            creator="Stacey",
            threadsdash_report=_manager_report_fixture(accounts=accounts),
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.account_tiers.v1"
        assert report["tierSummary"]["winner"] == 1
        assert report["tierSummary"]["blocked"] == 1
        assert report["accounts"][0]["tier"] == "winner"
        assert report["accounts"][0]["postingGuidance"]["priority"] == "prioritize_winning_concepts"
        assert report["accounts"][1]["tier"] == "blocked"
        assert report["accounts"][1]["postingGuidance"]["recommendedPostCount"] == 0
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_account_tiers_cli_outputs_json(tmp_path: Path):
    report_path = tmp_path / "threadsdash_report.json"
    report_path.write_text(json.dumps(_manager_report_fixture(accounts=[
        {"accountId": "ig_cli", "username": "cli", "creator": "Stacey", "safeToSchedule": True, "accountTier": "growth"},
    ])), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "account-tiers",
            "--creator",
            "Stacey",
            "--threadsdash-report-json",
            str(report_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.account_tiers.v1"
    assert payload["tierSummary"]["growth"] == 1
    assert payload["wouldWrite"] is False


def test_creator_os_account_health_report_cli_outputs_json(tmp_path: Path):
    report_path = tmp_path / "threadsdash_report.json"
    report_path.write_text(json.dumps(_manager_report_fixture(accounts=[
        {"accountId": "ig_cli", "username": "cli", "creator": "Stacey", "linkSharingRestricted": True},
    ])), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "account-health-report",
            "--creator",
            "Stacey",
            "--threadsdash-report-json",
            str(report_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.account_health_report.v1"
    assert payload["accounts"][0]["safeToSchedule"] is False
    assert payload["wouldWrite"] is False


def test_creator_os_account_health_report_blocks_restricted_and_not_recommended_accounts(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_link",
                "username": "link_restricted",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "linkSharingRestricted": True,
                "restrictionEndsAt": "2026-07-07T00:00:00+00:00",
            },
            {
                "accountId": "ig_rec",
                "username": "not_recommended",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "recommendationEligibilityState": "not_recommended",
            },
            {
                "accountId": "ig_ok",
                "username": "ok",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "recommendationEligibilityState": "eligible",
                "accountMaturityScore": 75,
            },
        ]

        report = cf.creator_os_account_health_report(
            creator="Stacey",
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            generated_at="2026-06-08T16:00:00+00:00",
        )

        by_id = {row["accountId"]: row for row in report["accounts"]}
        assert by_id["ig_link"]["safeToSchedule"] is False
        assert "account_link_sharing_restricted" in by_id["ig_link"]["blockers"]
        assert by_id["ig_rec"]["safeToSchedule"] is False
        assert "recommendation_not_eligible" in by_id["ig_rec"]["blockers"]
        assert by_id["ig_ok"]["safeToSchedule"] is True
        assert report["summary"]["safeToSchedule"] == 1
        assert report["summary"]["restrictedAccounts"] == 1
        assert report["summary"]["recommendationEligibilitySummary"]["not_recommended"] == 1
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_account_health_report_uses_conservative_unknown_recommendation_defaults(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [{
            "accountId": "ig_unknown",
            "username": "unknown",
            "creator": "Stacey",
            "bucket": "safe_to_schedule_today",
            "safeToSchedule": True,
            "needsPostToday": True,
            "accountAgeDays": 1,
        }]

        report = cf.creator_os_account_health_report(
            creator="Stacey",
            threadsdash_report=_manager_report_fixture(accounts=accounts),
        )

        account = report["accounts"][0]
        assert account["recommendationEligibilityState"] == "unknown"
        assert "recommendation_eligibility_unknown_conservative_cadence" in account["warnings"]
        assert account["accountTier"] == "warming"
        assert account["postingGuidance"]["maxPostsPerDay"] == 1
        assert account["postingGuidance"]["minimumGapHours"] == 24
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_account_health_failures(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_restricted",
                "username": "restricted",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "linkSharingRestricted": True,
            },
        ]
        draft = _draft_item("post_1", "ig_restricted")
        schedule_plan = {"schema": "threadsdashboard.campaign_schedule_plan.v1", "status": "ready", "items": [draft]}
        time_plan = {"schema": "threadsdashboard.campaign_schedule_time_plan.v1", "status": "ready", "items": [draft]}

        readiness = cf.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan=schedule_plan,
            time_plan=time_plan,
        )

        assert readiness["executionReady"] is False
        assert readiness["managerDecision"] == "blocked"
        assert "account_link_sharing_restricted" in readiness["blockers"]
        assert readiness["preCommitChecklist"]["accountHealthReadiness"] == "fail"
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_warming_over_cadence(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_warm",
                "username": "warm",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "accountAgeDays": 2,
                "postsToday": 1,
            },
        ]
        draft = _draft_item("post_1", "ig_warm")
        schedule_plan = {"schema": "threadsdashboard.campaign_schedule_plan.v1", "status": "ready", "items": [draft]}
        time_plan = {"schema": "threadsdashboard.campaign_schedule_time_plan.v1", "status": "ready", "items": [draft]}

        readiness = cf.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan=schedule_plan,
            time_plan=time_plan,
        )

        assert readiness["executionReady"] is False
        assert "account_warming_cadence_exceeded" in readiness["blockers"]
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_creative_risk_and_similarity_budget(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_safe",
                "username": "safe",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "recommendationEligibilityState": "eligible",
                "accountMaturityScore": 70,
            },
        ]
        risky = _draft_item("post_risky", "ig_safe")
        risky["creativeRiskScore"] = 80
        risky["similarityBudget"] = {"blocked": True, "reason": "visual_similarity_cluster_budget_exceeded"}
        schedule_plan = {"schema": "threadsdashboard.campaign_schedule_plan.v1", "status": "ready", "items": [risky]}
        time_plan = {"schema": "threadsdashboard.campaign_schedule_time_plan.v1", "status": "ready", "items": [risky]}

        readiness = cf.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan=schedule_plan,
            time_plan=time_plan,
        )

        assert readiness["executionReady"] is False
        assert "creative_risk_score_exceeded" in readiness["blockers"]
        assert "similarity_budget_exceeded" in readiness["blockers"]
    finally:
        cf.close()


def test_creator_os_account_health_filtered_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_link", "username": "link", "creator": "Stacey", "linkSharingRestricted": True},
            {"accountId": "ig_manual", "username": "manual", "creator": "Stacey", "accountTrustState": "manual_review_required"},
            {"accountId": "ig_warm", "username": "warm", "creator": "Stacey", "accountAgeDays": 2},
        ]
        threadsdash_report = _manager_report_fixture(accounts=accounts)
        before = cf.conn.total_changes

        restricted = cf.creator_os_restricted_account_report(creator="Stacey", threadsdash_report=threadsdash_report)
        manual = cf.creator_os_manual_review_queue(creator="Stacey", threadsdash_report=threadsdash_report)
        warmup = cf.creator_os_account_warmup_report(creator="Stacey", threadsdash_report=threadsdash_report)

        assert cf.conn.total_changes == before
        assert restricted["restrictedAccounts"] == 1
        assert manual["manualReviewAccounts"] == 2
        assert warmup["warmingAccounts"] >= 1
        assert restricted["wouldWrite"] is False
        assert manual["wouldWrite"] is False
        assert warmup["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_is_surface_aware_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account_a = cf.upsert_account("stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"])
        account_b = cf.upsert_account("stacey_b", platform="instagram", external_id="ig_b", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account_a["id"], surface="reel", max_per_day=1)
        add_account_requirement_fixture(cf, account_id=account_a["id"], surface="story", max_per_day=2)
        add_account_requirement_fixture(cf, account_id=account_b["id"], surface="feed_single", max_per_day=1)
        add_account_requirement_fixture(cf, account_id=account_b["id"], surface="feed_carousel", cadence="weekly", max_per_day=1, allowed_days=[5])
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_safe", content_surface="story", media_type="image", instagram_post_caption="")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_single_safe", content_surface="feed_single", media_type="image")
        cf.conn.commit()
        before = cf.conn.total_changes

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            date="2026-06-06",
            threadsdash_report=_manager_report_fixture(accounts=[
                {"accountId": "ig_a", "username": "stacey_a", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
                {"accountId": "ig_b", "username": "stacey_b", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            ]),
            schedule_plan={
                "creator": "Stacey",
                "status": "ready",
                "items": [
                    _draft_item("post_story", "ig_a", content_surface="story"),
                    _draft_item("post_feed", "ig_b", content_surface="feed_single"),
                ],
            },
        )

        stacey = plan["creators"][0]
        assert cf.conn.total_changes == before
        assert plan["surfaceAwareDailyPlan"] is True
        assert stacey["accountsNeedingReels"] == 1
        assert stacey["accountsNeedingStories"] == 2
        assert stacey["accountsNeedingFeedSingles"] == 1
        assert stacey["accountsNeedingCarousels"] == 1
        assert stacey["surfaceInventory"]["story"]["localScheduleSafe"] == 1
        assert stacey["surfaceInventory"]["story"]["threadDashScheduleSafeDrafts"] == 1
        assert stacey["surfaceShortfalls"]["story"]["shortfall"] == 1
        assert stacey["surfaceScheduleReadiness"]["story"]["ready"] is False
        assert stacey["surfaceScheduleReadiness"]["feed_single"]["ready"] is True
        assert stacey["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_uses_threadsdash_surface_needs_when_no_requirements(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=[
                {
                    "accountId": "ig_surface",
                    "username": "stacey_surface",
                    "creator": "Stacey",
                    "bucket": "safe_to_schedule_today",
                    "safeToSchedule": True,
                    "needsPostToday": False,
                    "surfaceNeeds": {"story": 1, "feed_single": {"remaining": 1}},
                }
            ]),
            schedule_plan={"creator": "Stacey", "items": []},
        )

        stacey = plan["creators"][0]
        assert stacey["accountsNeedingReels"] == 0
        assert stacey["accountsNeedingStories"] == 1
        assert stacey["accountsNeedingFeedSingles"] == 1
        assert plan["accounts"][0]["surfaceNeeds"]["story"]["needed"] is True
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_surface_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", max_per_day=2)
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_safe", content_surface="story", media_type="image", instagram_post_caption="")
        cf.conn.commit()
        before = cf.conn.total_changes

        creator_summary = cf.creator_surface_summary(creator="Stacey", date="2026-06-06")
        account_summary = cf.account_surface_summary(creator="Stacey", date="2026-06-06")
        gap = cf.creator_surface_gap_report(creator="Stacey", date="2026-06-06")

        assert cf.conn.total_changes == before
        assert creator_summary["schema"] == "creator_os.creator_surface_summary.v1"
        assert creator_summary["surfaceInventory"]["story"]["scheduleSafe"] == 1
        assert account_summary["schema"] == "creator_os.account_surface_summary.v1"
        assert account_summary["accounts"][0]["surfaceStatus"]["story"]["needed"] is True
        assert gap["schema"] == "creator_os.creator_surface_gap_report.v1"
        assert gap["surfaceGaps"]["story"]["needed"] == 2
        assert gap["surfaceGaps"]["story"]["available"] == 1
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_story_reports_handle_daily_and_multi_story_cadence(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account_a = cf.upsert_account("stacey_daily", platform="instagram", external_id="ig_daily", model_id=model["id"])
        account_b = cf.upsert_account("stacey_multi", platform="instagram", external_id="ig_multi", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account_a["id"], surface="story", cadence="daily", max_per_day=1)
        add_account_requirement_fixture(cf, account_id=account_b["id"], surface="story", cadence="2_per_day", max_per_day=1)
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_safe_1", content_surface="story", media_type="image", instagram_post_caption="")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_safe_2", content_surface="story", media_type="image", instagram_post_caption="")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, post_id, platform, status, account_id, instagram_account_id,
             content_surface, published_at, snapshot_at, raw_json, created_at)
            VALUES ('perf_story_daily', ?, 'post_story_daily', 'instagram', 'published', ?, 'ig_daily',
                    'story', '2026-06-06T09:00:00+00:00', '2026-06-06T10:00:00+00:00',
                    '{}', '2026-06-06T10:00:00+00:00')
            """,
            (cf.campaign_by_slug("stacey_surface_inventory_20260606")["id"], account_a["id"]),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        status = cf.account_story_status(account_id=account_b["id"], creator="Stacey", date="2026-06-06")
        gap = cf.story_gap_report(creator="Stacey", date="2026-06-06")
        summary = cf.creator_story_summary(creator="Stacey", date="2026-06-06")

        assert cf.conn.total_changes == before
        assert status["storyNeededToday"] is True
        assert status["storyCadence"] == "2_per_day"
        assert status["status"] == "needs_story"
        assert gap["accountsAnalyzed"] == 2
        assert gap["needsStoryToday"] == 1
        assert gap["alreadySatisfied"] == 1
        assert gap["blocked"] == 0
        assert summary["storyInventoryAvailable"] == 2
        assert summary["storyInventoryShortfall"] == 0
        assert summary["storyReadiness"] == "ready"
        assert summary["wouldWrite"] is False
    finally:
        cf.close()


def test_story_reports_handle_every_other_day_cadence(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_eod", platform="instagram", external_id="ig_eod", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", cadence="every_other_day", max_per_day=1)
        cf.conn.commit()

        first = cf.account_story_status(account_id=account["id"], creator="Stacey", date="2026-06-06")
        second = cf.account_story_status(account_id=account["id"], creator="Stacey", date="2026-06-07")

        assert {first["storyNeededToday"], second["storyNeededToday"]} == {True, False}
        assert first["wouldWrite"] is False
        assert second["wouldWrite"] is False
    finally:
        cf.close()


def test_story_inventory_report_counts_schedule_safe_and_blocked_assets(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_safe", content_surface="story", media_type="image", instagram_post_caption="")
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_blocked", content_surface="story", media_type="other", instagram_post_caption="")
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

        report = cf.story_inventory_report(creator="Stacey")

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


def test_creator_os_daily_plan_includes_story_inventory_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_story", platform="instagram", external_id="ig_story", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", cadence="daily", max_per_day=1)
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_story_safe", content_surface="story", media_type="image", instagram_post_caption="")
        cf.conn.commit()
        before = cf.conn.total_changes

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            date="2026-06-06",
            threadsdash_report=_manager_report_fixture(accounts=[
                {"accountId": "ig_story", "username": "stacey_story", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": False}
            ]),
            schedule_plan={"creator": "Stacey", "items": []},
        )

        stacey = plan["creators"][0]
        assert cf.conn.total_changes == before
        assert stacey["accountsNeedingStories"] == 1
        assert stacey["storyInventoryAvailable"] == 1
        assert stacey["storyInventoryShortfall"] == 0
        assert stacey["storyScheduleReadiness"] == "ready"
        assert stacey["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_surface_report_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_cli", platform="instagram", external_id="ig_cli", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="feed_single", max_per_day=1)
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "creator-surface-summary",
            "--creator",
            "Stacey",
            "--date",
            "2026-06-06",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.creator_surface_summary.v1"
    assert payload["totalsBySurface"]["feed_single"]["remaining"] == 1
    assert payload["wouldWrite"] is False


def test_creator_os_draft_inventory_gap_reports_local_assets_not_exported(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_local_safe")
        cf.create_distribution_plan("asset_local_safe", instagram_account_id="ig_1")
        before = cf.conn.total_changes

        gap = cf.creator_os_draft_inventory_gap(
            creator="Stacey",
            schedule_plan={"schema": "threadsdashboard.campaign_schedule_plan.v1", "items": []},
        )

        assert cf.conn.total_changes == before
        assert gap["schema"] == "creator_os.draft_inventory_gap.v1"
        assert gap["localScheduleSafeAssets"] == 1
        assert gap["threadDashValidatedDrafts"] == 0
        assert gap["notExportedYet"][0]["renderedAssetId"] == "asset_local_safe"
        assert gap["blockedReasons"] == {"not_exported_to_threadsdash": 1}
        assert gap["nextSafeAction"] == "export_validated_drafts"
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_draft_inventory_gap_reports_exported_but_not_validated(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        gap = cf.creator_os_draft_inventory_gap(
            creator="Stacey",
            schedule_plan={
                "schema": "threadsdashboard.campaign_schedule_plan.v1",
                "items": [
                    _draft_item("post_unvalidated", "ig_1", platform_draft_validated=False),
                ],
            },
        )

        assert cf.conn.total_changes == before
        assert gap["localScheduleSafeAssets"] == 0
        assert gap["threadDashValidatedDrafts"] == 0
        assert gap["exportedButNotValidated"] == [{
            "draftPostId": "post_unvalidated",
            "renderedAssetId": "asset_post_unvalidated",
            "distributionPlanId": "dist_post_unvalidated",
            "reason": "notPlatformDraftValidated",
            "wouldWrite": False,
        }]
        assert gap["blockedReasons"] == {"platform_draft_not_validated": 1}
        assert gap["nextSafeAction"] == "fix_validation"
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_draft_inventory_gap_reports_validated_but_not_schedule_safe(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        gap = cf.creator_os_draft_inventory_gap(
            creator="Stacey",
            schedule_plan={
                "schema": "threadsdashboard.campaign_schedule_plan.v1",
                "items": [
                    _draft_item("post_no_caption", "ig_1", instagram_post_caption=""),
                    _draft_item("post_cooldown", "ig_2", variant_family_id="vfam_1", variant_id="var_1", cooldown="same_variant_family_within_14_days"),
                ],
            },
        )

        assert cf.conn.total_changes == before
        assert gap["localScheduleSafeAssets"] == 0
        assert gap["threadDashValidatedDrafts"] == 0
        reasons = {row["draftPostId"]: row["reason"] for row in gap["validatedButNotScheduleSafe"]}
        assert reasons == {
            "post_no_caption": "missing_instagram_post_caption",
            "post_cooldown": "same_variant_family_within_14_days",
        }
        assert gap["blockedReasons"] == {
            "missing_instagram_post_caption": 1,
            "same_variant_family_within_14_days": 1,
        }
        assert gap["nextSafeAction"] == "fix_validation"
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_includes_draft_inventory_gap(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_local_safe")
        cf.create_distribution_plan("asset_local_safe", instagram_account_id="ig_1")

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=[
                {"accountId": "ig_1", "username": "safe", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            ]),
            schedule_plan={"schema": "threadsdashboard.campaign_schedule_plan.v1", "items": []},
        )

        gap = plan["creators"][0]["draftInventoryGap"]
        assert gap["localScheduleSafeAssets"] == 1
        assert gap["threadDashValidatedDrafts"] == 0
        assert gap["nextSafeAction"] == "export_validated_drafts"
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_draft_inventory_gap_cli_outputs_json(tmp_path: Path):
    schedule_path = tmp_path / "schedule_plan.json"
    schedule_path.write_text(json.dumps({
        "schema": "threadsdashboard.campaign_schedule_plan.v1",
        "items": [_draft_item("post_cli", "ig_cli", instagram_post_caption="")],
    }), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "draft-inventory-gap",
            "--creator",
            "Stacey",
            "--schedule-plan-json",
            str(schedule_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.draft_inventory_gap.v1"
    assert payload["validatedButNotScheduleSafe"][0]["reason"] == "missing_instagram_post_caption"
    assert payload["wouldWrite"] is False


def test_creator_os_daily_plan_counts_blocked_account_breakdown(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_safe", "username": "safe", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_recent", "username": "recent", "creator": "Stacey", "bucket": "blocked_recent_failure", "safeToSchedule": False, "needsPostToday": False},
            {"accountId": "ig_reauth", "username": "reauth", "creator": "Stacey", "bucket": "blocked_reauth", "safeToSchedule": False, "needsPostToday": False, "blockingReason": "needs_reauth"},
        ]

        plan = cf.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "validatedDraftsAvailable": 1, "items": [_draft_item("post_1", "ig_safe")]},
        )

        stacey = plan["creators"][0]
        assert stacey["blockedAccounts"] == 2
        assert stacey["blockedAccountBreakdown"] == {
            "blocked_recent_failure": 1,
            "needs_reauth": 1,
        }
        by_id = {row["accountId"]: row for row in plan["accounts"]}
        assert by_id["ig_recent"]["state"] == "blocked"
        assert by_id["ig_recent"]["blockedReason"] == "blocked_recent_failure"
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_when_inventory_is_zero(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_1", "username": "stacey_one", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_2", "username": "stacey_two", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
        ]
        before = cf.conn.total_changes

        result = cf.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=2,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "requestedCount": 2, "status": "blocked", "blockingReason": "insufficient_validated_drafts", "validatedDraftsAvailable": 0, "items": []},
            time_plan={"creator": "Stacey", "requestedCount": 2, "status": "blocked", "blockingReason": "insufficient_validated_drafts", "items": []},
        )

        assert cf.conn.total_changes == before
        assert result["schema"] == "creator_os.execution_readiness.v1"
        assert result["managerDecision"] == "needs_inventory"
        assert result["executionReady"] is False
        assert result["scheduleSafeDraftsAvailable"] == 0
        assert "insufficient_schedule_safe_drafts" in result["blockers"]
        assert result["preCommitChecklist"]["draftReadiness"] == "fail"
        assert result["wouldWrite"] is False
    finally:
        cf.close()


def test_decision_ledger_preview_simulates_manager_decisions_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_story_need", platform="instagram", external_id="ig_story_need", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", cadence="daily", max_per_day=1)
        cf.conn.commit()
        before = cf.conn.total_changes

        preview = cf.decision_ledger_preview(
            creator="Stacey",
            date="2026-06-06",
            threadsdash_report=_manager_report_fixture(accounts=[
                {"accountId": "ig_story_need", "username": "stacey_story_need", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True}
            ]),
            schedule_plan={"creator": "Stacey", "validatedDraftsAvailable": 0, "items": []},
            generated_at="2026-06-06T12:00:00+00:00",
        )

        assert cf.conn.total_changes == before
        assert preview["schema"] == "creator_os.decision_ledger_preview.v1"
        assert preview["wouldWrite"] is False
        by_type = {entry["decisionType"]: entry for entry in preview["decisions"]}
        assert by_type["inventory_shortfall"]["reason"] == "insufficient_schedule_safe_drafts"
        assert by_type["inventory_shortfall"]["inventoryShortfall"] == 1
        assert by_type["account_needs_story"]["accountId"] == account["id"]
        assert by_type["account_needs_story"]["sourceSystem"] == "account_content_requirements"
        assert by_type["story_intent_recommended"]["storyIntent"] in {"snapchat_promo", "lifestyle", "reel_teaser", "casual_selfie"}
        assert all(entry["timestamp"] == "2026-06-06T12:00:00+00:00" for entry in preview["decisions"])
        assert all(entry["wouldWrite"] is False for entry in preview["decisions"])
        assert table_count(cf, "manager_decisions") == 0
    finally:
        cf.close()


def test_decision_ledger_report_filters_by_creator_account_surface_and_type(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_story_need", platform="instagram", external_id="ig_story_need", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", cadence="daily", max_per_day=1)
        cf.conn.commit()
        source = {
            "creator": "Stacey",
            "date": "2026-06-06",
            "threadsdash_report": _manager_report_fixture(accounts=[
                {"accountId": "ig_story_need", "username": "stacey_story_need", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True}
            ]),
            "schedule_plan": {"creator": "Stacey", "validatedDraftsAvailable": 0, "items": []},
            "generated_at": "2026-06-06T12:00:00+00:00",
        }

        by_creator = cf.decision_ledger_by_creator(**source)
        by_account = cf.decision_ledger_by_account(account_id=account["id"], **source)
        by_surface = cf.decision_ledger_by_surface(surface="story", **source)
        by_type = cf.decision_ledger_by_decision_type(decision_type="account_needs_story", **source)
        summary = cf.decision_ledger_summary(**source)

        assert by_creator["creator"] == "Stacey"
        assert by_creator["decisionCount"] >= 3
        assert {entry["accountId"] for entry in by_account["decisions"]} == {account["id"]}
        assert {entry["surface"] for entry in by_surface["decisions"] if entry.get("surface")} == {"story"}
        assert {entry["decisionType"] for entry in by_type["decisions"]} == {"account_needs_story"}
        assert summary["decisionCountsByType"]["account_needs_story"] == 1
        assert summary["decisionCountsBySurface"]["story"] >= 1
        assert summary["wouldWrite"] is False
        assert table_count(cf, "manager_decisions") == 0
    finally:
        cf.close()


def test_decision_ledger_preview_covers_winners_parent_selection_and_variant_rejections(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        preview = cf.decision_ledger_preview(
            creator="Stacey",
            date="2026-06-06",
            winner_expansion_report={
                "schema": "campaign_factory.winner_expansion_report.v1",
                "winners": [
                    {
                        "postId": "post_1",
                        "assetId": "asset_parent_1",
                        "parentReelId": "parent_1",
                        "variantFamilyId": "vfam_1",
                        "reason": "high_views",
                        "recommendedAction": "create_more_variants",
                        "wouldWrite": False,
                    }
                ],
            },
            variant_inventory_plan={
                "schema": "campaign_factory.variant_inventory_plan.v1",
                "executionBatches": [
                    {
                        "parentAssetId": "asset_parent_1",
                        "preset": "caption_safe_v2",
                        "requestedVariants": 5,
                        "minimumRecommended": 3,
                        "operationFamilies": ["cover_frame", "timing_trim"],
                    }
                ],
                "wouldWrite": False,
            },
            winner_expansion_plan={
                "schema": "campaign_factory.winner_expansion_plan.v1",
                "parentAssetId": "asset_parent_1",
                "rejectedExistingVariants": {"lowQuality": 1, "duplicateSiblings": 2, "notUploadReady": 1},
                "wouldWrite": False,
            },
            generated_at="2026-06-06T12:00:00+00:00",
        )

        assert cf.conn.total_changes == before
        by_type = {entry["decisionType"]: entry for entry in preview["decisions"]}
        assert by_type["winner_selected"]["winnerReason"] == "high_views"
        assert by_type["parent_selected"]["parentAssetId"] == "asset_parent_1"
        rejection_reasons = {entry["reason"] for entry in preview["decisions"] if entry["decisionType"] == "variant_rejected"}
        assert {"low_quality", "duplicate_sibling", "not_upload_ready"} <= rejection_reasons
        assert preview["wouldWrite"] is False
    finally:
        cf.close()


def _insert_creative_kb_snapshot(
    cf: CampaignFactory,
    *,
    snapshot_id: str,
    campaign_id: str,
    post_id: str,
    creator: str = "Stacey",
    campaign_asset_id: str = "",
    source_asset_id: str = "",
    concept_id: str = "",
    parent_reel_id: str = "",
    variant_family_id: str = "",
    variant_id: str = "",
    caption_angle: str = "",
    caption_hash: str = "",
    caption_family_id: str = "",
    caption_version_id: str = "",
    instagram_post_caption_hash: str = "",
    audio_id: str = "",
    content_surface: str = "reel",
    ig_media_type: str = "REELS",
    account_id: str = "",
    instagram_account_id: str = "",
    account_username: str = "",
    account_tier: str = "",
    story_intent: str = "",
    story_style: str = "",
    story_goal: str = "",
    published_at: str = "2026-06-06T18:00:00+00:00",
    views: int = 0,
    reach: int = 0,
    saves: int = 0,
    shares: int = 0,
    followers: int = 0,
    profile_visits: int = 0,
) -> None:
    raw = {
        "followers": followers,
        "profile_visits": profile_visits,
        "instagram_post_caption_hash": instagram_post_caption_hash,
        "ig_media_type": ig_media_type,
        "account_username": account_username,
        "account_tier": account_tier,
        "story_intent": story_intent,
        "story_style": story_style,
        "story_goal": story_goal,
        "metric_contract": {
            "version": "instagram_metrics_contract_v1",
            "surface": content_surface,
            "metricNames": ["views", "reach", "likes", "comments", "shares", "saves", "followers", "profile_visits"],
        },
    }
    context = {
        "caption_angle": caption_angle,
        "caption_family_id": caption_family_id,
        "caption_version_id": caption_version_id,
        "instagram_post_caption_hash": instagram_post_caption_hash,
        "storyIntent": story_intent,
        "storyStyle": story_style,
        "storyGoal": story_goal,
    }
    cf.conn.execute(
        """
        INSERT INTO performance_snapshots
        (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
         caption_hash, caption_text, creator_mix, caption_outcome_context_json, concept_id,
         parent_reel_id, variant_family_id, variant_id, audio_id, recipe, post_id, platform,
         content_surface, status, account_id, instagram_account_id, published_at, snapshot_at,
         views, likes, comments, shares, saves, impressions, reach, watch_time_seconds,
         metrics_eligible, raw_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'recipe_1', ?, 'instagram',
         ?, 'published', ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, 0, 1, ?, ?)
        """,
        (
            snapshot_id,
            campaign_id,
            campaign_asset_id or f"asset_{snapshot_id}",
            source_asset_id or f"source_{snapshot_id}",
            f"hash_{snapshot_id}",
            f"source_hash_{snapshot_id}",
            caption_hash,
            "caption text",
            creator,
            json.dumps(context),
            concept_id,
            parent_reel_id,
            variant_family_id,
            variant_id,
            audio_id,
            post_id,
            content_surface,
            account_id,
            instagram_account_id,
            published_at,
            published_at,
            views,
            shares,
            saves,
            reach,
            reach,
            json.dumps(raw),
            published_at,
        ),
    )


def test_creative_knowledge_base_reports_insufficient_data_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_creative_kb", "stacey")
        before = cf.conn.total_changes

        report = cf.creative_knowledge_base(creator="Stacey", campaign_slug=campaign["slug"])

        assert cf.conn.total_changes == before
        assert report["schema"] == "campaign_factory.creative_knowledge_base.v1"
        assert report["creator"] == "Stacey"
        assert report["insufficientData"] is True
        assert report["reason"] == "not_enough_published_metrics"
        assert report["topCaptionAngles"] == []
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creative_knowledge_base_aggregates_dimensions_and_weighted_scores(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_creative_kb", "stacey")
        _insert_creative_kb_snapshot(
            cf,
            snapshot_id="perf_kb_1",
            campaign_id=campaign["id"],
            post_id="post_1",
            concept_id="mirror_selfie",
            parent_reel_id="parent_1",
            variant_family_id="vfam_1",
            variant_id="var_1",
            caption_angle="tease",
            caption_hash="burn_hash_1",
            caption_family_id="cfam_1",
            caption_version_id="cver_1",
            instagram_post_caption_hash="ig_hash_1",
            audio_id="audio_12",
            content_surface="reel",
            ig_media_type="REELS",
            account_id="acct_1",
            instagram_account_id="ig_1",
            account_username="stacey_one",
            account_tier="growth",
            published_at="2026-06-06T18:00:00+00:00",
            views=1000,
            reach=800,
            saves=20,
            shares=10,
            followers=5,
        )
        _insert_creative_kb_snapshot(
            cf,
            snapshot_id="perf_kb_2",
            campaign_id=campaign["id"],
            post_id="post_2",
            concept_id="mirror_selfie",
            parent_reel_id="parent_1",
            variant_family_id="vfam_1",
            variant_id="var_2",
            caption_angle="tease",
            caption_hash="burn_hash_1",
            caption_family_id="cfam_1",
            caption_version_id="cver_1",
            instagram_post_caption_hash="ig_hash_1",
            audio_id="audio_12",
            content_surface="story",
            ig_media_type="STORIES",
            account_id="acct_2",
            instagram_account_id="ig_2",
            account_username="stacey_two",
            account_tier="warmup",
            story_intent="snapchat_promo",
            story_style="casual_selfie",
            story_goal="traffic",
            published_at="2026-06-06T21:00:00+00:00",
            views=500,
            reach=400,
            saves=4,
            shares=8,
            followers=2,
        )
        _insert_creative_kb_snapshot(
            cf,
            snapshot_id="perf_kb_3",
            campaign_id=campaign["id"],
            post_id="post_3",
            concept_id="gym_mirror",
            caption_angle="question_bait",
            caption_hash="burn_hash_2",
            caption_family_id="cfam_2",
            caption_version_id="cver_2",
            instagram_post_caption_hash="ig_hash_2",
            audio_id="audio_44",
            content_surface="feed_single",
            ig_media_type="IMAGE",
            account_id="acct_3",
            instagram_account_id="ig_3",
            account_username="stacey_three",
            account_tier="established",
            published_at="2026-06-07T18:00:00+00:00",
            views=100,
            reach=90,
            saves=1,
            shares=1,
            followers=0,
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.creative_knowledge_base(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)

        assert cf.conn.total_changes == before
        assert report["insufficientData"] is False
        assert report["wouldWrite"] is False
        assert report["metricsContract"]["visibleMetricFields"] == ["views", "reach", "likes", "comments", "shares", "saves", "followers", "profile_visits"]
        assert report["topCaptionAngles"][0]["key"] == "tease"
        assert report["topCaptionAngles"][0]["sampleSize"] == 2
        assert report["topCaptionAngles"][0]["avgViews"] == 750
        assert report["topCaptionAngles"][0]["score"] == 540.5
        assert report["topAudioIds"][0]["key"] == "audio_12"
        assert report["topSurfaces"][0]["key"] == "reel"
        assert {item["key"] for item in report["topSurfaces"]} == {"reel", "story", "feed_single"}
        assert report["topStoryIntents"][0]["key"] == "snapchat_promo"
        assert report["topAccountTiers"][0]["key"] == "growth"
        assert report["topPostingWindows"][0]["key"] in {"6pm", "9pm"}
        assert report["topCaptionVersions"][0]["key"] == "cver_1"

        caption_report = cf.creative_caption_report(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        audio_report = cf.creative_audio_report(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        surface_report = cf.creative_surface_report(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        tier_report = cf.creative_account_tier_report(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        window_report = cf.creative_window_report(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)

        assert caption_report["captionAngles"][0]["key"] == "tease"
        assert audio_report["audioIds"][0]["key"] == "audio_12"
        assert surface_report["surfaces"]
        assert tier_report["accountTiers"]
        assert window_report["postingWindows"]
        assert all(item["wouldWrite"] is False for item in [caption_report, audio_report, surface_report, tier_report, window_report])
    finally:
        cf.close()


def test_creative_knowledge_base_cli_outputs_read_only_report(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_creative_cli", "stacey")
        _insert_creative_kb_snapshot(
            cf,
            snapshot_id="perf_kb_cli",
            campaign_id=campaign["id"],
            post_id="post_cli",
            caption_angle="tease",
            audio_id="audio_12",
            views=500,
            reach=400,
            saves=10,
            shares=5,
            followers=1,
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "creative-knowledge-base",
            "--creator",
            "Stacey",
            "--campaign",
            campaign["slug"],
            "--minimum-sample-size",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
            "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
        },
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.creative_knowledge_base.v1"
    assert payload["topAudioIds"][0]["key"] == "audio_12"
    assert payload["wouldWrite"] is False


def test_creative_performance_analysis_reports_insufficient_data_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_creative_perf", "stacey")
        _insert_creative_kb_snapshot(
            cf,
            snapshot_id="perf_analysis_low_1",
            campaign_id=campaign["id"],
            post_id="post_analysis_low_1",
            content_surface="reel",
            caption_angle="tease",
            views=100,
            reach=80,
            saves=1,
            shares=1,
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.creative_performance_analysis(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)

        assert cf.conn.total_changes == before
        assert report["schema"] == "campaign_factory.creative_performance_analysis.v1"
        assert report["insufficientData"] is True
        assert report["reason"] == "not_enough_published_metrics"
        assert report["bestPerformingPatterns"] == []
        assert report["underperformingPatterns"] == []
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creative_performance_analysis_baseline_and_recommendations_are_explainable(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_creative_perf", "stacey")
        for idx, views in enumerate([1000, 1100, 1200, 1300, 1400], start=1):
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"perf_analysis_good_{idx}",
                campaign_id=campaign["id"],
                post_id=f"post_analysis_good_{idx}",
                concept_id="mirror_selfie",
                parent_reel_id="parent_good",
                campaign_asset_id="asset_good_parent",
                caption_angle="tease",
                audio_id="audio_12",
                content_surface="reel",
                account_tier="growth",
                published_at=f"2026-06-06T18:0{idx}:00+00:00",
                views=views,
                reach=views - 100,
                saves=20,
                shares=12,
                followers=3,
            )
        for idx, views in enumerate([100, 120, 140, 160, 180], start=1):
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"perf_analysis_weak_{idx}",
                campaign_id=campaign["id"],
                post_id=f"post_analysis_weak_{idx}",
                concept_id="generic_feed",
                caption_angle="hard_cta",
                audio_id="audio_44",
                content_surface="feed_single",
                account_tier="warmup",
                published_at=f"2026-06-06T09:0{idx}:00+00:00",
                views=views,
                reach=views - 20,
                saves=1,
                shares=0,
            )
        cf.conn.commit()

        report = cf.creative_performance_analysis(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        summary = cf.creator_learning_summary(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        recommendations = cf.next_content_recommendations(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)

        assert report["insufficientData"] is False
        assert report["confidence"] == "medium"
        assert report["creatorBaseline"]["postCount"] == 10
        assert report["creatorBaseline"]["avgViews"] == 670
        assert report["bestPerformingPatterns"][0]["key"] == "mirror_selfie"
        assert report["bestPerformingPatterns"][0]["comparison"] == "above_creator_baseline"
        assert "above creator baseline" in report["bestPerformingPatterns"][0]["reason"]
        assert any(item["key"] == "generic_feed" for item in report["underperformingPatterns"])
        assert any(item["recommendation"] == "make_more_variants" for item in report["recommendedMoreOf"])
        assert any(item["recommendation"] == "avoid_or_rework_pattern" for item in report["recommendedLessOf"])
        assert all(item["reason"] for item in report["recommendedMoreOf"] + report["recommendedLessOf"])
        assert summary["confidence"] == "medium"
        assert summary["summary"]
        assert any("mirror_selfie" in line for line in summary["summary"])
        assert recommendations["recommendations"][0]["surface"] == "reel"
        assert recommendations["recommendations"][0]["parentAssetId"] == "asset_good_parent"
        assert recommendations["recommendations"][0]["captionAngle"] == "tease"
        assert recommendations["recommendations"][0]["audioId"] == "audio_12"
        assert recommendations["recommendations"][0]["confidence"] == "medium"
        assert report["wouldWrite"] is False
        assert summary["wouldWrite"] is False
        assert recommendations["wouldWrite"] is False
    finally:
        cf.close()


def test_creative_performance_analysis_confidence_thresholds_and_story_recommendation(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_creative_perf_confidence", "stacey")
        for idx in range(51):
            if idx < 26:
                surface = "story"
                story_intent = "snapchat_promo"
                story_style = "casual_selfie"
                story_goal = "traffic"
                views = 700 + idx
                reach = 600 + idx
                saves = 3
                shares = 2
            else:
                surface = "reel"
                story_intent = ""
                story_style = ""
                story_goal = ""
                views = 100
                reach = 90
                saves = 1
                shares = 0
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"perf_analysis_conf_{idx}",
                campaign_id=campaign["id"],
                post_id=f"post_analysis_conf_{idx}",
                concept_id="story_concept" if surface == "story" else "weak_reel",
                content_surface=surface,
                story_intent=story_intent,
                story_style=story_style,
                story_goal=story_goal,
                account_tier="growth",
                published_at="2026-06-06T21:00:00+00:00",
                views=views,
                reach=reach,
                saves=saves,
                shares=shares,
            )
        cf.conn.commit()

        report = cf.creative_performance_analysis(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        recommendations = cf.next_content_recommendations(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)

        assert report["confidence"] == "high"
        assert any(item["dimension"] == "storyIntent" and item["key"] == "snapchat_promo" for item in report["bestPerformingPatterns"])
        story_recs = [item for item in recommendations["recommendations"] if item["surface"] == "story"]
        assert story_recs
        assert story_recs[0]["recommendation"] == "make_more_snapchat_promo_stories"
        assert "above creator baseline" in story_recs[0]["reason"]
        assert story_recs[0]["confidence"] == "high"
        assert recommendations["wouldWrite"] is False
    finally:
        cf.close()


def test_learning_engine_recommendations_include_explainability_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_learning_engine", "stacey")
        for idx, views in enumerate([1000, 1100, 1200, 1300], start=1):
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"learning_engine_good_{idx}",
                campaign_id=campaign["id"],
                post_id=f"learning_engine_good_post_{idx}",
                concept_id="mirror_selfie",
                campaign_asset_id="asset_learning_parent",
                caption_angle="tease",
                audio_id="audio_12",
                content_surface="reel",
                views=views,
                reach=views - 100,
                saves=15,
                shares=8,
                followers=2,
            )
        for idx, views in enumerate([100, 120, 140, 160], start=1):
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"learning_engine_weak_{idx}",
                campaign_id=campaign["id"],
                post_id=f"learning_engine_weak_post_{idx}",
                concept_id="generic_feed",
                caption_angle="hard_cta",
                audio_id="audio_44",
                content_surface="feed_single",
                views=views,
                reach=views - 20,
                saves=1,
                shares=0,
            )
        cf.conn.commit()
        before = cf.conn.total_changes

        analysis = cf.creative_performance_analysis(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        next_content = cf.next_content_recommendations(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        daily = cf.creator_os_daily_plan(creators=["Stacey"], threadsdash_report=_manager_report_fixture(accounts=[]))
        request = cf.recommended_inventory_request_plan(creator="Stacey", target_count=5, daily_plan=daily)
        audit = cf.recommendation_quality_audit(creator="Stacey", campaign_slug=campaign["slug"])

        assert cf.conn.total_changes == before
        for item in analysis["recommendedMoreOf"] + analysis["recommendedLessOf"] + next_content["recommendations"] + request["requestBatches"]:
            explainability = item["explainability"]
            assert explainability["reason"]
            assert isinstance(explainability["confidence"], int)
            assert explainability["sampleSize"] >= 0
            assert explainability["baselineMetric"] == "score"
            assert explainability["observedMetric"] == "score"
            assert "scoreLiftPct" in explainability
        assert audit["schema"] == "campaign_factory.recommendation_quality_audit.v1"
        assert audit["recommendationsAudited"] >= 1
        assert audit["qualityBuckets"]["low_confidence"] >= 1
        assert audit["wouldWrite"] is False
    finally:
        cf.close()


def test_learning_confidence_fatigue_and_surface_comparison_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_learning_reports", "stacey")
        for idx, (surface, views, reach) in enumerate([
            ("reel", 1000, 900),
            ("story", 850, 760),
            ("feed_single", 500, 450),
            ("feed_carousel", 650, 580),
            ("reel", 600, 520),
            ("reel", 300, 260),
        ], start=1):
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"learning_reports_{idx}",
                campaign_id=campaign["id"],
                post_id=f"learning_reports_post_{idx}",
                concept_id="mirror_selfie",
                caption_angle="tease",
                audio_id="audio_12",
                content_surface=surface,
                account_id=f"acct_{idx % 3}",
                published_at=f"2026-06-0{idx}T18:00:00+00:00",
                views=views,
                reach=reach,
                saves=max(1, idx),
                shares=max(0, idx - 1),
            )
        cf.conn.commit()
        before = cf.conn.total_changes

        confidence = cf.creative_learning_confidence_model(creator="Stacey", campaign_slug=campaign["slug"])
        fatigue = cf.creative_fatigue_report(creator="Stacey", campaign_slug=campaign["slug"])
        comparison = cf.creative_surface_comparison_report(creator="Stacey", campaign_slug=campaign["slug"])

        assert cf.conn.total_changes == before
        assert confidence["schema"] == "campaign_factory.creative_learning_confidence_model.v1"
        assert confidence["confidenceModel"]["highConfidenceSignals"]
        assert confidence["currentConfidence"]["classification"] in {"low_confidence", "medium_confidence", "high_confidence"}
        assert fatigue["schema"] == "campaign_factory.creative_fatigue_report.v1"
        assert any(item["fatigueType"] == "concept_fatigue" for item in fatigue["fatigueSignals"])
        assert comparison["schema"] == "campaign_factory.creative_surface_comparison_report.v1"
        concept = comparison["concepts"][0]
        assert concept["conceptId"] == "mirror_selfie"
        assert {surface["surface"] for surface in concept["surfaces"]} >= {"reel", "story", "feed_single", "feed_carousel"}
        assert all(report["wouldWrite"] is False for report in [confidence, fatigue, comparison])
    finally:
        cf.close()


def test_phase2_learning_reports_share_creative_knowledge_helper(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("stacey_creative_kb_20260606", "stacey")
        for idx in range(3):
            _insert_creative_kb_snapshot(
                cf,
                snapshot_id=f"perf_phase2_{idx}",
                campaign_id=campaign["id"],
                post_id=f"post_phase2_{idx}",
                caption_angle="question_bait",
                audio_id="audio_12",
                views=1200 + idx,
                reach=900 + idx,
                saves=10,
                shares=4,
                followers=1,
                published_at=f"2026-06-06T1{idx}:00:00+00:00",
            )
        cf.conn.commit()
        calls: list[str] = []
        original = cf._build_creative_knowledge_base

        def tracking_helper(*args, **kwargs):
            calls.append(str(kwargs.get("creator") or ""))
            return original(*args, **kwargs)

        monkeypatch.setattr(cf, "_build_creative_knowledge_base", tracking_helper)

        kb = cf.creative_knowledge_base(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        caption = cf.creative_caption_report(creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3)
        winners = cf.winner_registry(creator="Stacey", campaign_slug=campaign["slug"], min_views=1000)

        assert kb["schema"] == "campaign_factory.creative_knowledge_base.v1"
        assert caption["schema"] == "campaign_factory.creative_caption_report.v1"
        assert winners["schema"] == "campaign_factory.winner_registry.v1"
        assert len(calls) >= 3
        assert kb["wouldWrite"] is False
        assert caption["wouldWrite"] is False
        assert winners["wouldWrite"] is False
    finally:
        cf.close()


def test_phase2_surface_and_readiness_reports_share_helpers(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(cf, tmp_path, asset_id="asset_phase2_story", content_surface="story", media_type="image", instagram_post_caption="")
        cf.conn.commit()
        inventory_calls = 0
        readiness_calls = 0
        original_inventory = cf._build_surface_inventory
        original_readiness = cf._build_surface_readiness

        def tracking_inventory(*args, **kwargs):
            nonlocal inventory_calls
            inventory_calls += 1
            return original_inventory(*args, **kwargs)

        def tracking_readiness(*args, **kwargs):
            nonlocal readiness_calls
            readiness_calls += 1
            return original_readiness(*args, **kwargs)

        monkeypatch.setattr(cf, "_build_surface_inventory", tracking_inventory)
        monkeypatch.setattr(cf, "_build_surface_readiness", tracking_readiness)

        inventory = cf.story_inventory_report(creator="Stacey")
        audit = cf.multi_surface_inventory_audit(creator="Stacey")
        readiness = cf.surface_handoff_readiness_report(creator="Stacey")
        proof = cf.surface_draft_proof(creator="Stacey")

        assert inventory["schema"] == "campaign_factory.story_inventory_report.v1"
        assert audit["schema"] == "campaign_factory.multi_surface_inventory_audit.v1"
        assert readiness["schema"] == "campaign_factory.surface_handoff_readiness_report.v1"
        assert proof["schema"] == "campaign_factory.surface_draft_proof.v1"
        assert inventory_calls >= 2
        assert readiness_calls >= 2
        assert inventory["wouldWrite"] is False
        assert audit["wouldWrite"] is False
        assert readiness["wouldWrite"] is False
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_phase2_decision_ledger_wrappers_share_query_helper(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        account = cf.upsert_account("stacey_story_need", platform="instagram", external_id="ig_story_need", model_id=model["id"])
        add_account_requirement_fixture(cf, account_id=account["id"], surface="story", cadence="daily", max_per_day=1)
        cf.conn.commit()
        calls: list[dict[str, Any]] = []
        original = cf._query_decision_ledger

        def tracking_query(*args, **kwargs):
            calls.append(dict(kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(cf, "_query_decision_ledger", tracking_query)
        source = {
            "creator": "Stacey",
            "date": "2026-06-06",
            "threadsdash_report": _manager_report_fixture(accounts=[
                {"accountId": "ig_story_need", "username": "stacey_story_need", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True}
            ]),
            "schedule_plan": {"creator": "Stacey", "validatedDraftsAvailable": 0, "items": []},
            "generated_at": "2026-06-06T12:00:00+00:00",
        }

        report = cf.decision_ledger_report(**source)
        by_account = cf.decision_ledger_by_account(account_id=account["id"], **source)
        by_surface = cf.decision_ledger_by_surface(surface="story", **source)

        assert report["schema"] == "creator_os.decision_ledger_report.v1"
        assert by_account["schema"] == "creator_os.decision_ledger_by_account.v1"
        assert by_surface["schema"] == "creator_os.decision_ledger_by_surface.v1"
        assert any(call.get("account_id") == account["id"] for call in calls)
        assert any(call.get("surface") == "story" for call in calls)
        assert report["wouldWrite"] is False
        assert by_account["wouldWrite"] is False
        assert by_surface["wouldWrite"] is False
        assert table_count(cf, "manager_decisions") == 0
    finally:
        cf.close()


def test_creator_os_execution_readiness_passes_with_safe_accounts_and_drafts(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_1", "username": "stacey_one", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
            {"accountId": "ig_2", "username": "stacey_two", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
        ]
        items = [
            _draft_item("post_1", "ig_1", scheduled_for="2026-06-06T16:00:00+00:00"),
            _draft_item("post_2", "ig_2", scheduled_for="2026-06-06T16:15:00+00:00"),
        ]

        result = cf.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=2,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "requestedCount": 2, "status": "ready", "validatedDraftsAvailable": 2, "items": items},
            time_plan={"creator": "Stacey", "requestedCount": 2, "status": "ready", "items": items},
        )

        assert result["managerDecision"] == "ready_to_schedule"
        assert result["executionReady"] is True
        assert result["safeAccountsAvailable"] == 2
        assert result["scheduleSafeDraftsAvailable"] == 2
        assert result["blockers"] == []
        assert result["preCommitChecklist"] == {
            "accountReadiness": "pass",
            "accountHealthReadiness": "pass",
            "draftReadiness": "pass",
            "schedulePlanReadiness": "pass",
            "timePlanReadiness": "pass",
            "publishRuntimeReadiness": "pass",
            "captionContractReadiness": "pass",
        }
        assert result["nextSafeActions"] == ["commit_campaign_schedule_batch"]
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_unsafe_draft_contracts(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": f"ig_{idx}", "username": f"stacey_{idx}", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True}
            for idx in range(1, 6)
        ]
        items = [
            _draft_item("post_no_caption", "ig_1", instagram_post_caption=""),
            _draft_item("post_no_manifest", "ig_2", handoff_manifest_ok=False),
            _draft_item("post_not_validated", "ig_3", platform_draft_validated=False),
            _draft_item("post_quarantined", "ig_4", quarantined=True),
            _draft_item("post_failed", "ig_5", publishability_state="blocked"),
        ]

        result = cf.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=5,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={"creator": "Stacey", "requestedCount": 5, "status": "ready", "validatedDraftsAvailable": 5, "items": items},
            time_plan={"creator": "Stacey", "requestedCount": 5, "status": "ready", "items": items},
        )

        assert result["managerDecision"] == "needs_inventory"
        assert result["scheduleSafeDraftsAvailable"] == 0
        assert result["preCommitChecklist"]["draftReadiness"] == "fail"
        assert result["preCommitChecklist"]["captionContractReadiness"] == "fail"
        assert "missing_instagram_post_caption" in result["blockers"]
        assert "missing_handoff_manifest" in result["blockers"]
        assert "platform_draft_not_validated" in result["blockers"]
        assert "quarantined_draft_present" in result["blockers"]
        assert "publishability_failed_draft_present" in result["blockers"]
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_variant_cooldown_missed_dispatch_and_time_slots(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {"accountId": "ig_1", "username": "stacey_one", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
        ]
        missed = [{"postId": "post_missed", "accountId": "ig_1", "blockingReason": "overdue_dispatch_no_publish_attempt"}]

        result = cf.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(accounts=accounts, missed=missed),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "validatedDraftsAvailable": 1,
                "items": [_draft_item("post_1", "ig_1", variant_family_id="vfam_1", variant_id="var_1", cooldown="same_variant_family_within_14_days")],
            },
            time_plan={"creator": "Stacey", "requestedCount": 1, "status": "ready", "items": []},
        )

        assert result["managerDecision"] == "blocked"
        assert result["preCommitChecklist"]["publishRuntimeReadiness"] == "fail"
        assert result["preCommitChecklist"]["timePlanReadiness"] == "fail"
        assert "missed_dispatches_unresolved" in result["blockers"]
        assert "variant_cooldown_violation" in result["blockers"]
        assert "insufficient_time_plan_items" in result["blockers"]
        assert "resolve_missed_dispatches_before_scheduling" in result["nextSafeActions"]
    finally:
        cf.close()


def test_creator_os_execution_readiness_cli_outputs_json(tmp_path: Path):
    report_path = tmp_path / "threadsdash_report.json"
    schedule_path = tmp_path / "schedule_plan.json"
    time_path = tmp_path / "time_plan.json"
    report_path.write_text(json.dumps(_manager_report_fixture(accounts=[
        {"accountId": "ig_cli", "username": "cli", "creator": "Stacey", "bucket": "safe_to_schedule_today", "safeToSchedule": True, "needsPostToday": True},
    ])), encoding="utf-8")
    item = _draft_item("post_cli", "ig_cli", scheduled_for="2026-06-06T16:00:00+00:00")
    schedule_path.write_text(json.dumps({"creator": "Stacey", "requestedCount": 1, "status": "ready", "validatedDraftsAvailable": 1, "items": [item]}), encoding="utf-8")
    time_path.write_text(json.dumps({"creator": "Stacey", "requestedCount": 1, "status": "ready", "items": [item]}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "execution-readiness",
            "--creator",
            "Stacey",
            "--requested-count",
            "1",
            "--threadsdash-report-json",
            str(report_path),
            "--schedule-plan-json",
            str(schedule_path),
            "--time-plan-json",
            str(time_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.execution_readiness.v1"
    assert payload["managerDecision"] == "ready_to_schedule"
    assert payload["wouldWrite"] is False


def test_creator_os_200_account_acceptance_suite_is_read_only_and_exercises_core_paths(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        result = cf.creator_os_200_account_acceptance_suite(
            accounts=200,
            creators=3,
            daily_obligations=600,
            draft_inventory=1800,
            warming_accounts=30,
            restricted_accounts=15,
            manual_review_accounts=10,
            mixed_surfaces=True,
        )

        assert cf.conn.total_changes == before
        assert result["schema"] == "creator_os.200_account_acceptance_suite.v1"
        assert result["acceptancePassed"] is True
        assert result["postsPerDay"] == 600
        assert result["draftsPerDay"] == 1800
        assert result["metricsSnapshotsPerDay"] == 1800
        assert result["scheduleDecisionsPerDay"] >= 600
        assert result["accountHealthEvaluationsPerDay"] == 200
        assert result["blockedAccounts"] == 25
        assert result["unexpectedBlockedAccounts"] == 0
        assert result["inventoryShortfall"] == 0
        assert result["dailyPlanRuntimeMs"] >= 0
        assert result["executionReadinessRuntimeMs"] >= 0
        assert result["validatedPaths"] == [
            "daily-plan",
            "execution-readiness",
            "account-health",
            "surface-inventory",
            "decision-ledger",
            "lifecycle",
            "publishability",
            "recommendation-generation",
            "inventory-planning",
        ]
        assert result["unexpectedFailures"] == []
        assert result["wouldWrite"] is False
    finally:
        cf.close()


def test_inventory_slo_and_buffer_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        slo = cf.inventory_slo_report(accounts=200, posts_per_account_per_day=3, creators=3, minimum_inventory_days=3)
        buffer_report = cf.inventory_buffer_report(
            accounts=200,
            posts_per_account_per_day=3,
            creators=3,
            current_validated_drafts=1800,
            current_drafts_by_surface={"reel": 900, "story": 600, "feed_single": 300, "feed_carousel": 0},
        )

        assert cf.conn.total_changes == before
        assert slo["minimumInventoryDays"] == 3
        assert slo["minimumValidatedDraftBuffer"] == 1800
        assert slo["minimumDraftsPerCreator"] == {"Creator 1": 600, "Creator 2": 600, "Creator 3": 600}
        assert slo["minimumDraftsPerSurface"]["reel"] > 0
        assert slo["inventoryHealth"] == "critical"
        assert slo["wouldWrite"] is False
        assert buffer_report["inventoryHealth"] == "healthy"
        assert buffer_report["currentValidatedDrafts"] == 1800
        assert buffer_report["draftSurplus"] == 0
        assert buffer_report["wouldWrite"] is False
    finally:
        cf.close()


def test_exception_queue_report_unifies_blockers_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        daily_plan = {
            "schema": "creator_os.daily_plan.v1",
            "creators": [{"creator": "Stacey", "inventoryShortfall": 4, "surfaceShortfalls": {"story": {"shortfall": 2}}}],
            "accounts": [{"accountId": "ig_blocked", "username": "blocked", "state": "blocked", "blockedReason": "needs_reauth"}],
        }
        readiness = {
            "schema": "creator_os.execution_readiness.v1",
            "blockers": ["missing_instagram_post_caption", "embedded_audio_invalid"],
        }

        report = cf.exception_queue_report(daily_plan=daily_plan, execution_readiness=readiness)
        summary = cf.exception_queue_summary(daily_plan=daily_plan, execution_readiness=readiness)

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.exception_queue_report.v1"
        assert report["exceptionCount"] >= 4
        assert {item["reason"] for item in report["exceptions"]} >= {
            "needs_reauth",
            "inventory_shortfall",
            "missing_instagram_post_caption",
            "embedded_audio_invalid",
        }
        assert all({
            "exceptionId",
            "severity",
            "owner",
            "system",
            "category",
            "nextAction",
            "repairable",
            "estimatedResolutionMinutes",
            "blockingAccounts",
            "blockingInventory",
        } <= set(item) for item in report["exceptions"])
        assert report["wouldWrite"] is False
        assert summary["schema"] == "creator_os.exception_queue_summary.v1"
        assert summary["exceptionCount"] == report["exceptionCount"]
        assert summary["wouldWrite"] is False
    finally:
        cf.close()


def test_exception_queue_priority_and_owner_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        daily_plan = {
            "schema": "creator_os.daily_plan.v1",
            "creators": [{"creator": "Stacey", "inventoryShortfall": 8}],
            "accounts": [{"accountId": "ig_blocked", "state": "blocked", "blockedReason": "restriction_event"}],
        }
        before = cf.conn.total_changes

        priority = cf.exception_queue_priority_report(daily_plan=daily_plan)
        owner = cf.exception_queue_owner_report(daily_plan=daily_plan)

        assert cf.conn.total_changes == before
        assert priority["schema"] == "creator_os.exception_queue_priority_report.v1"
        assert priority["exceptions"]
        assert priority["exceptions"][0]["severity"] in {"critical", "high"}
        assert priority["wouldWrite"] is False
        assert owner["schema"] == "creator_os.exception_queue_owner_report.v1"
        assert owner["owners"]
        assert all("owner" in row and "exceptionCount" in row for row in owner["owners"])
        assert owner["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_and_inventory_autopilot_plans_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        parent = cf.parent_factory_autopilot_plan(accounts=200, posts_per_account_per_day=3)
        shortfall = cf.parent_factory_shortfall_report(accounts=200, posts_per_account_per_day=3)
        targets = cf.parent_factory_production_targets(accounts=200, posts_per_account_per_day=3)
        inventory = cf.inventory_autopilot_plan(accounts=100, posts_per_account_per_day=3, available_inventory=0)
        repair = cf.inventory_shortage_repair_plan(accounts=100, posts_per_account_per_day=3, available_inventory=0)
        buffer = cf.inventory_buffer_protection_report(accounts=100, posts_per_account_per_day=3, available_inventory=0)

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
        assert all(item["wouldWrite"] is False for item in [parent, shortfall, targets, inventory, repair, buffer])
    finally:
        cf.close()


def test_creator_os_100_volume_surface_and_10_readiness_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        proof = cf.creator_os_100_account_proof()
        volume = cf.creator_os_volume_acceptance_suite()
        scorecard = cf.surface_readiness_scorecard()
        readiness = cf.creator_os_10_0_readiness_report()

        assert cf.conn.total_changes == before
        assert proof["schema"] == "creator_os.100_account_proof.v1"
        assert proof["accounts"] == 100
        assert proof["postsPerDay"] == 300
        assert proof["inventoryBuffer"] == 900
        assert proof["wouldWrite"] is False
        assert volume["schema"] == "creator_os.volume_acceptance_suite.v1"
        assert volume["tiers"]["100"]["accounts"] == 100
        assert volume["tiers"]["200"]["accounts"] == 200
        assert volume["wouldWrite"] is False
        assert scorecard["schema"] == "creator_os.surface_readiness_scorecard.v1"
        assert set(scorecard["surfaces"]) >= {"reel", "story", "feed_single", "feed_carousel"}
        assert all("rating" in row for row in scorecard["surfaces"].values())
        assert readiness["schema"] == "creator_os.10_0_readiness_report.v1"
        assert readiness["scores"]["overall"] >= 9.0
        assert readiness["successCriteria"]["exceptionQueueReady"] is True
        assert readiness["successCriteria"]["inventoryAutopilotReady"] is True
        assert readiness["successCriteria"]["requiredParentsPerDayKnown"] is True
        assert readiness["finalOutput"]["projectedRatingAfterSprint"] >= readiness["finalOutput"]["currentRating"]
        assert readiness["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_final_certification_proofs_are_read_only_and_evidence_based(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        live = cf.creator_os_live_100_account_readiness()
        runbook = cf.creator_os_live_scale_runbook()
        live_scorecard = cf.creator_os_live_scale_scorecard()
        production_trial = cf.parent_factory_production_trial()
        production_scorecard = cf.parent_factory_production_scorecard()
        real_yield = cf.parent_factory_real_yield_report()
        prevention = cf.discoverability_prevention_audit()
        prevention_scorecard = cf.discoverability_prevention_scorecard()
        story = cf.story_production_readiness()
        story_gap = cf.story_proof_gap_analysis()
        story_certification = cf.story_certification_proof()
        carousel = cf.carousel_production_readiness()
        carousel_gap = cf.carousel_proof_gap_analysis()
        carousel_certification = cf.carousel_certification_proof()
        certification = cf.creator_os_certification_report()

        assert cf.conn.total_changes == before
        assert live["schema"] == "creator_os.live_100_account_readiness.v1"
        assert {"canRun100AccountsToday", "blockingReason", "requiredInventory", "requiredParentsPerDay", "expectedOperatorLoad", "expectedExceptionRate"} <= set(live)
        assert {"eligibleAccounts", "restrictedAccounts", "warmingAccounts", "validatedDraftBuffer", "safeToRun100Accounts"} <= set(live)
        assert live["dataSource"] == "actual_current_state"
        assert runbook["schema"] == "creator_os.live_scale_runbook.v1"
        assert runbook["steps"]
        assert live_scorecard["schema"] == "creator_os.live_scale_scorecard.v1"
        assert production_trial["schema"] == "creator_os.parent_factory_production_trial.v1"
        assert {"rawCandidates", "qualityPassed", "discoverabilityPassed", "publishabilityPassed", "acceptedParents", "yieldPct", "operatorMinutes"} <= set(production_trial)
        assert production_scorecard["schema"] == "creator_os.parent_factory_production_scorecard.v1"
        assert real_yield["schema"] == "creator_os.parent_factory_real_yield_report.v1"
        assert prevention["schema"] == "creator_os.discoverability_prevention_audit.v1"
        assert {"violationsCaughtBeforeRender", "violationsCaughtAfterRender", "violationsCaughtAtPublishability"} <= set(prevention)
        assert prevention_scorecard["schema"] == "creator_os.discoverability_prevention_scorecard.v1"
        assert story["schema"] == "creator_os.story_production_readiness.v1"
        assert story["publishProofMissing"] is True
        assert story_gap["schema"] == "creator_os.story_proof_gap_analysis.v1"
        assert story_certification["schema"] == "creator_os.story_certification_proof.v1"
        assert story_certification["storyCreated"] is False
        assert story_certification["storyPublished"] is False
        assert story_certification["status"] == "blocked"
        assert "story_asset_missing" in story_certification["blockers"]
        assert carousel["schema"] == "creator_os.carousel_production_readiness.v1"
        assert carousel["publishProofMissing"] is True
        assert carousel_gap["schema"] == "creator_os.carousel_proof_gap_analysis.v1"
        assert carousel_certification["schema"] == "creator_os.carousel_certification_proof.v1"
        assert carousel_certification["carouselCreated"] is False
        assert carousel_certification["carouselPublished"] is False
        assert carousel_certification["status"] == "blocked"
        assert "carousel_asset_missing" in carousel_certification["blockers"]
        assert certification["schema"] == "creator_os.certification_report.v1"
        assert certification["storyCertified"] is False
        assert certification["carouselCertified"] is False
        assert certification["100AccountCertified"] is False
        assert 0 <= certification["finalRating"] <= 10
        assert "maximumAchievableRating" not in certification
        assert "singleHighestROITask" not in certification
        assert "projectedRating" not in certification
        assert all(item["wouldWrite"] is False for item in [
            live, runbook, live_scorecard, production_trial, production_scorecard, real_yield,
            prevention, prevention_scorecard, story, story_gap, story_certification,
            carousel, carousel_gap, carousel_certification, certification,
        ])
    finally:
        cf.close()


def test_creator_os_staged_operational_acceptance_uses_actual_evidence_and_is_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        stage_10 = cf.creator_os_live_account_acceptance(account_target=10)
        staged = cf.creator_os_staged_live_acceptance()

        assert cf.conn.total_changes == before
        assert stage_10["schema"] == "creator_os.live_account_acceptance.v1"
        assert stage_10["accountTarget"] == 10
        assert stage_10["passCriteria"] == {
            "missedDispatches": 0,
            "duplicatePublishes": 0,
            "restrictedAccountsScheduled": 0,
            "surfaceContractViolations": 0,
            "inventoryBufferMaintained": True,
            "metricsImported": True,
            "exceptionQueueWithinThreshold": True,
        }
        assert {"missedDispatches", "duplicatePublishes", "restrictedAccountsScheduled", "surfaceContractViolations", "inventoryBufferMaintained", "metricsImported", "exceptionQueueWithinThreshold"} <= set(stage_10["actuals"])
        assert stage_10["dataSource"] == "actual_current_state"
        assert stage_10["wouldWrite"] is False
        assert staged["schema"] == "creator_os.staged_live_acceptance.v1"
        assert [row["accountTarget"] for row in staged["stages"]] == [10, 25, 50, 100]
        assert staged["currentCertifiedStage"] in [0, 10, 25, 50, 100]
        assert staged["nextStageTarget"] in [10, 25, 50, 100, None]
        assert staged["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_staged_operational_acceptance_can_pass_with_clean_actual_state(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("stacey", name="Stacey")
        for index in range(10):
            cf.upsert_account(f"stacey_{index}", platform="instagram", external_id=f"ig_{index}", model_id=model["id"])
        for index in range(90):
            add_surface_asset_fixture(
                cf,
                tmp_path,
                asset_id=f"asset_scale_inventory_{index}",
                content_surface="feed_single",
                media_type="image",
                instagram_post_caption="schedule safe",
            )
        campaign_id = cf.campaign_by_slug("stacey_surface_inventory_20260606")["id"]
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, post_id, account_id, instagram_account_id, platform,
             content_surface, metrics_eligible, snapshot_at, created_at, raw_json)
            VALUES ('snap_scale_1', ?, 'asset_scale_inventory_0', 'post_scale_1', 'ig_0', 'ig_0',
                    'instagram', 'reel', 1,
                    '2026-06-09T00:00:00+00:00', '2026-06-09T00:00:00+00:00', '{}')
            """,
            (campaign_id,),
        )
        cf.conn.commit()

        result = cf.creator_os_live_account_acceptance(account_target=10)
        reel_result = cf.creator_os_live_account_acceptance(account_target=10, content_surface="reel")

        assert result["actuals"]["missedDispatches"] == 0
        assert result["actuals"]["duplicatePublishes"] == 0
        assert result["actuals"]["restrictedAccountsScheduled"] == 0
        assert result["actuals"]["surfaceContractViolations"] == 0
        assert result["actuals"]["inventoryBufferMaintained"] is True
        assert result["actuals"]["metricsImported"] is True
        assert result["actuals"]["exceptionQueueWithinThreshold"] is True
        assert result["acceptancePassed"] is True
        assert result["blockingReasons"] == []
        assert result["contentSurface"] == "all"
        assert reel_result["contentSurface"] == "reel"
        assert reel_result["availableInventory"] == 0
        assert reel_result["acceptancePassed"] is False
        assert "inventory_buffer_not_maintained" in reel_result["blockingReasons"]
    finally:
        cf.close()


def test_story_certification_requires_actual_publish_and_metrics_evidence(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        asset = add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_cert",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
            target_ratio="9:16",
        )
        before = cf.conn.total_changes

        blocked = cf.story_certification_proof(rendered_asset_id=asset["id"])

        assert cf.conn.total_changes == before
        assert blocked["storyCreated"] is True
        assert blocked["storyValidated"] is True
        assert blocked["storyScheduled"] is False
        assert blocked["storyPublished"] is False
        assert blocked["storyMetricsImported"] is False
        assert blocked["lifecycleReconciled"] is False
        assert blocked["status"] == "blocked"
        assert "story_publish_evidence_missing" in blocked["blockers"]
        assert "story_metrics_evidence_missing" in blocked["blockers"]
        assert blocked["audit"]["manifestV2"]["contentSurface"] == "story"
        assert blocked["audit"]["publishPayload"]["igMediaType"] == "STORIES"
        assert blocked["wouldWrite"] is False
    finally:
        cf.close()


def test_carousel_certification_passes_with_ordering_publish_and_metrics_evidence(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        result = cf.register_surface_asset(
            input_path=[write_surface_image(tmp_path / f"cert_carousel_{index}.png") for index in range(3)],
            surface="feed_carousel",
            creator="Stacey",
            campaign_slug="stacey_carousel_cert_20260609",
            instagram_post_caption="which one wins?",
        )
        asset_id = result["renderedAssetId"]
        asset = cf.rendered_asset(asset_id)
        cf.record_proof_run(
            campaign_id=asset["campaign_id"],
            rendered_asset_id=asset_id,
            threadsdash_draft_id="draft_carousel_cert",
            threadsdash_post_id="post_carousel_cert",
            status="passed",
            current_state="published",
            metrics_eligible=True,
            metadata={"contentSurface": "feed_carousel", "igMediaType": "CAROUSEL"},
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
             post_id, platform, status, account_id, instagram_account_id, published_at,
             snapshot_at, views, likes, comments, shares, saves, reach, raw_json,
             created_at, metrics_eligible, content_surface)
            VALUES ('perf_carousel_cert', ?, ?, ?, ?, ?, 'post_carousel_cert', 'instagram',
                    'published', 'acct_carousel', 'ig_carousel', '2026-06-09T12:00:00+00:00',
                    '2026-06-09T13:00:00+00:00', 100, 10, 1, 2, 3, 90, '{}',
                    '2026-06-09T13:00:00+00:00', 1, 'feed_carousel')
            """,
            (asset["campaign_id"], asset_id, asset["source_asset_id"], asset["content_hash"], asset["caption_hash"]),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        proof = cf.carousel_certification_proof(rendered_asset_id=asset_id)

        assert cf.conn.total_changes == before
        assert proof["carouselCreated"] is True
        assert proof["carouselValidated"] is True
        assert proof["carouselPublished"] is True
        assert proof["slideOrderPreserved"] is True
        assert proof["slideHashesPreserved"] is True
        assert proof["parentMetricsImported"] is True
        assert proof["lifecycleReconciled"] is True
        assert proof["status"] == "passed"
        assert proof["blockers"] == []
        assert proof["audit"]["publishPayload"]["igMediaType"] == "CAROUSEL"
        assert proof["audit"]["metricsPayload"]["contentSurface"] == "feed_carousel"
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_failure_injection_and_idempotency_proofs_are_simulation_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        failures = cf.failure_injection_suite()
        idempotency = cf.idempotency_proof()

        assert cf.conn.total_changes == before
        assert failures["schema"] == "creator_os.failure_injection_suite.v1"
        assert failures["failureInjectionPassed"] is True
        assert {item["scenario"] for item in failures["scenarios"]} == {
            "duplicate_publish_callback",
            "double_qstash_dispatch",
            "late_dispatch",
            "missed_dispatch",
            "expired_publish_token",
            "partial_metrics_sync",
            "missing_performance_snapshot",
            "duplicate_performance_snapshot",
            "invalid_handoff_manifest",
            "stale_account_restriction",
        }
        assert all(item["detected"] and item["contained"] and item["recovered"] for item in failures["scenarios"])
        assert failures["wouldWrite"] is False
        assert idempotency["schema"] == "creator_os.idempotency_proof.v1"
        assert idempotency["idempotent"] is True
        assert idempotency["unsafePaths"] == []
        assert all(item["sameRequestOnce"] == item["sameRequestTwice"] == item["sameRequestTenTimes"] for item in idempotency["paths"])
        assert idempotency["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_maturity_operator_ownership_complexity_and_final_readiness_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        surface = cf.surface_maturity_audit()
        operator = cf.operator_load_audit()
        ownership = cf.single_source_of_truth_audit()
        complexity = cf.core_complexity_reduction_plan()
        final = cf.creator_os_9_5_readiness_report()

        assert cf.conn.total_changes == before
        assert surface["schema"] == "creator_os.surface_maturity_audit.v1"
        assert set(surface["surfaces"]) == {"reel", "story", "feed_single", "feed_carousel", "trial_reel"}
        assert surface["surfaces"]["reel"]["publishProof"] is True
        assert surface["surfaces"]["story"]["publishProof"] is False
        assert surface["surfaces"]["feed_carousel"]["metricsProof"] is False
        assert surface["wouldWrite"] is False
        assert operator["schema"] == "creator_os.operator_load_audit.v1"
        assert operator["firstBreakingPoint"] in {"100_accounts", "200_accounts"}
        assert operator["scaleTiers"]["200"]["largestBottleneck"]
        assert operator["wouldWrite"] is False
        assert ownership["schema"] == "creator_os.single_source_of_truth_audit.v1"
        assert ownership["recommendedOwners"]["performance metrics"] == "performance_snapshots"
        assert ownership["wouldWrite"] is False
        assert complexity["schema"] == "creator_os.core_complexity_reduction_plan.v1"
        assert any(row["file"].endswith("campaign_factory/core.py") for row in complexity["largestFiles"])
        assert complexity["expectedComplexityReductionPct"] >= 20
        assert complexity["wouldWrite"] is False
        assert final["schema"] == "creator_os.9_5_readiness_report.v1"
        assert final["currentScore"] >= 8.5
        assert final["scores"]["200Accounts"] < final["currentScore"]
        assert final["scores"]["1000Accounts"] < final["scores"]["500Accounts"]
        assert len(final["top10RemainingRisks"]) == 10
        assert final["exactPathTo9_5"]
        assert final["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_9_5_readiness_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "creator-os-9.5-readiness-report",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.9_5_readiness_report.v1"
    assert payload["wouldWrite"] is False
    assert len(payload["top10RemainingRisks"]) == 10


def test_inventory_factory_audit_and_yield_analysis_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        audit = cf.inventory_factory_audit(accounts=200, posts_per_account_per_day=3)
        yield_report = cf.inventory_yield_analysis()

        assert cf.conn.total_changes == before
        assert audit["schema"] == "creator_os.inventory_factory_audit.v1"
        assert audit["inventoryPipelineMapped"] is True
        assert audit["dailyCapacityEstimate"] == 0
        assert audit["validatedInventoryCapacity"] == 0
        assert audit["scheduleSafeInventoryCapacity"] == 0
        assert audit["limitingStage"] == "validated_inventory"
        assert audit["wouldWrite"] is False
        assert yield_report["schema"] == "creator_os.inventory_yield_analysis.v1"
        assert yield_report["stageCounts"]["parentAssets"] == 0
        assert yield_report["parentToVariantYield"] == 0
        assert yield_report["variantToValidatedYield"] == 0
        assert yield_report["validatedToScheduleSafeYield"] == 0
        assert yield_report["largestDropoff"]
        assert yield_report["wouldWrite"] is False
    finally:
        cf.close()


def test_inventory_buffer_policy_and_slo_enforcement_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        buffer_plan = cf.inventory_buffer_policy_plan(
            creator="Stacey",
            surface="reel",
            daily_demand=600,
            buffer_target_days=3,
            available_inventory=900,
        )
        slo = cf.inventory_slo_enforcement_audit(
            creators=["Stacey", "Lola"],
            accounts=200,
            posts_per_account_per_day=3,
            minimum_inventory_days=3,
            available_by_creator_surface={
                "Stacey": {"reel": 900, "story": 500, "feed_single": 100, "feed_carousel": 0},
                "Lola": {"reel": 100, "story": 0, "feed_single": 0, "feed_carousel": 0},
            },
        )

        assert cf.conn.total_changes == before
        assert buffer_plan == {
            "schema": "creator_os.inventory_buffer_policy_plan.v1",
            "creator": "Stacey",
            "surface": "reel",
            "dailyDemand": 600,
            "bufferTargetDays": 3,
            "requiredInventory": 1800,
            "availableInventory": 900,
            "shortfall": 900,
            "health": "critical",
            "wouldWrite": False,
        }
        assert slo["schema"] == "creator_os.inventory_slo_enforcement_audit.v1"
        assert slo["slosDefined"] is True
        assert slo["violations"]
        assert slo["highestRiskCreator"] == "Lola"
        assert slo["highestRiskSurface"] in {"story", "feed_single", "feed_carousel"}
        assert slo["wouldWrite"] is False
    finally:
        cf.close()


def test_inventory_consumption_and_production_requirements_use_real_calculations(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        simulation = cf.inventory_consumption_simulation(available_inventory=1800)
        production = cf.inventory_production_requirements(accounts=200, posts_per_account_per_day=3)
        road = cf.road_to_200_accounts()

        assert cf.conn.total_changes == before
        assert simulation["schema"] == "creator_os.inventory_consumption_simulation.v1"
        row_200 = next(row for row in simulation["simulations"] if row["accounts"] == 200)
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


def test_inventory_exception_and_readiness_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        readiness = {
            "schema": "creator_os.execution_readiness.v1",
            "blockers": [
                "missing_instagram_post_caption",
                "embedded_audio_invalid",
                "publishability_failed_draft_present",
                "missing_instagram_post_caption",
            ],
        }

        exceptions = cf.inventory_exception_audit(execution_readiness=readiness)
        readiness_report = cf.inventory_factory_readiness_report(
            accounts=200,
            posts_per_account_per_day=3,
            available_inventory=1800,
            execution_readiness=readiness,
        )
        master = cf.inventory_factory_master_report(
            accounts=200,
            posts_per_account_per_day=3,
            available_inventory=1800,
            execution_readiness=readiness,
        )

        assert cf.conn.total_changes == before
        assert exceptions["schema"] == "creator_os.inventory_exception_audit.v1"
        assert exceptions["topLossReason"] == "missing_instagram_post_caption"
        assert exceptions["avoidableLossPct"] > 0
        assert exceptions["wouldWrite"] is False
        assert readiness_report["schema"] == "creator_os.inventory_factory_readiness_report.v1"
        assert 0 <= readiness_report["overallInventoryReadiness"] <= 10
        assert readiness_report["inventoryBufferScore"] == 10
        assert readiness_report["wouldWrite"] is False
        assert master["schema"] == "creator_os.inventory_factory_master_report.v1"
        assert master["currentInventoryReadiness"]["overallInventoryReadiness"] == readiness_report["overallInventoryReadiness"]
        assert master["requirementsFor200Accounts"]["requiredInventoryBuffer"] == "1800 schedule-safe drafts"
        assert master["requirementsFor500Accounts"]["requiredInventoryBuffer"] == "4500 schedule-safe drafts"
        assert master["wouldWrite"] is False
    finally:
        cf.close()


def test_inventory_factory_master_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "inventory-factory-master-report",
            "--available-inventory",
            "1800",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.inventory_factory_master_report.v1"
    assert payload["wouldWrite"] is False
    assert payload["requirementsFor200Accounts"]["requiredInventoryBuffer"] == "1800 schedule-safe drafts"


def test_reel_factory_parent_throughput_proof_is_read_only_and_pessimistic(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        proof = cf.reel_factory_parent_throughput_proof(required_parents_per_day=53)

        assert cf.conn.total_changes == before
        assert proof["schema"] == "creator_os.reel_factory_parent_throughput_proof.v1"
        assert proof["canProduce53QualityParentsPerDay"] is False
        assert proof["confidence"] in {"low", "medium", "high"}
        assert proof["limitingStep"]
        assert proof["requiredRawCandidatesPerDay"] >= 53
        assert 0 <= proof["qualityParentPassRate"] <= 1
        assert 0 <= proof["publishabilityPassRate"] <= 1
        assert 0 <= proof["captionFamilyEligibleRate"] <= 1
        assert 0 <= proof["audioValidRate"] <= 1
        assert 0 <= proof["handoffReadyRate"] <= 1
        assert proof["operatorReviewMinutesPerParent"] >= 0
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_reel_factory_yield_failure_and_capacity_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        yield_report = cf.reel_factory_yield_analysis()
        failure = cf.reel_factory_failure_analysis()
        capacity = cf.reel_factory_capacity_model(required_parents_per_day=53)

        assert cf.conn.total_changes == before
        assert yield_report["schema"] == "creator_os.reel_factory_yield_analysis.v1"
        assert yield_report["funnel"][0]["stage"] == "raw_candidates"
        assert yield_report["funnel"][-1]["stage"] == "schedule_safe"
        assert yield_report["overallYieldPct"] >= 0
        assert yield_report["largestDropoff"]
        assert yield_report["wouldWrite"] is False
        assert failure["schema"] == "creator_os.reel_factory_failure_analysis.v1"
        assert failure["failures"]
        assert failure["whatBreaksFirst"]
        assert all("repairCostMinutes" in item for item in failure["failures"])
        assert failure["wouldWrite"] is False
        assert capacity["schema"] == "creator_os.reel_factory_capacity_model.v1"
        assert capacity["requiredParentsPerDay"] == 53
        assert capacity["passRateScenarios"]["95%"] == 56
        assert capacity["passRateScenarios"]["90%"] == 59
        assert capacity["passRateScenarios"]["80%"] == 67
        assert capacity["passRateScenarios"]["70%"] == 76
        assert capacity["passRateScenarios"]["60%"] == 89
        assert capacity["wouldWrite"] is False
    finally:
        cf.close()


def test_reel_factory_200_account_readiness_and_master_report_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        readiness = cf.reel_factory_200_account_readiness()
        master = cf.reel_factory_master_report()

        assert cf.conn.total_changes == before
        assert readiness["schema"] == "creator_os.reel_factory_200_account_readiness.v1"
        assert readiness["requiredParentsPerDay"] == 53
        assert readiness["scalingAnalysis"]["200Accounts"]["requiredParentsPerDay"] == 53
        assert readiness["scalingAnalysis"]["200Accounts"]["requiredValidatedDraftsPerDay"] == 600
        assert readiness["scalingAnalysis"]["500Accounts"]["requiredInventoryBuffer"] == 4500
        assert readiness["wouldWrite"] is False
        assert master["schema"] == "creator_os.reel_factory_master_report.v1"
        verdict = master["finalVerdict"]
        assert verdict["currentParentFactoryRating"] <= 10
        assert verdict["canSupport200Accounts"] is False
        assert verdict["requiredParentsPerDay"] == 53
        assert verdict["requiredRawCandidatesPerDay"] >= 53
        assert verdict["largestBottleneck"]
        assert verdict["largestHumanBottleneck"]
        assert verdict["largestTechnicalBottleneck"]
        assert verdict["recommendedNextSprint"]
        assert master["wouldWrite"] is False
    finally:
        cf.close()


def test_reel_factory_master_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "reel-factory-master-report",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.reel_factory_master_report.v1"
    assert payload["finalVerdict"]["requiredParentsPerDay"] == 53
    assert payload["wouldWrite"] is False


def test_parent_factory_yield_waterfall_and_loss_analysis_explain_current_yield(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        waterfall = cf.parent_factory_yield_waterfall(required_parents_per_day=53)
        loss = cf.parent_factory_loss_analysis(required_parents_per_day=53)

        assert cf.conn.total_changes == before
        assert waterfall["schema"] == "creator_os.parent_factory_yield_waterfall.v1"
        assert waterfall["overallYieldPct"] >= 0
        assert waterfall["requiredRawCandidatesPerDay"] >= 53
        assert [row["stage"] for row in waterfall["stages"]] == [
            "raw_candidate",
            "render_success",
            "visual_qc_pass",
            "caption_burn_pass",
            "audio_validation_pass",
            "discoverability_safety_pass",
            "publishability_pass",
            "handoff_ready",
            "schedule_safe",
            "parent_accepted",
        ]
        assert all({"stage", "inputCount", "outputCount", "yieldPct", "lossCount"} <= set(row) for row in waterfall["stages"])
        assert waterfall["wouldWrite"] is False
        assert loss["schema"] == "creator_os.parent_factory_loss_analysis.v1"
        assert loss["largestLossStage"]
        assert loss["largestRepairableLossStage"]
        assert loss["highestROIImprovement"]
        assert loss["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_rejection_quality_and_optimization_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        rejections = cf.parent_factory_rejection_report()
        quality = cf.parent_factory_quality_gate_analysis()
        optimization = cf.parent_factory_optimization_plan(required_parents_per_day=53)

        assert cf.conn.total_changes == before
        assert rejections["schema"] == "creator_os.parent_factory_rejection_report.v1"
        assert rejections["rejectionReasons"]
        assert all({"reason", "frequency", "percentOfFailures", "repairable", "estimatedFixDifficulty"} <= set(row) for row in rejections["rejectionReasons"])
        assert rejections["wouldWrite"] is False
        assert quality["schema"] == "creator_os.parent_factory_quality_gate_analysis.v1"
        assert quality["qualityGates"]
        assert "publishability_pass" in {row["gate"] for row in quality["qualityGates"]}
        assert quality["wouldWrite"] is False
        assert optimization["schema"] == "creator_os.parent_factory_optimization_plan.v1"
        assert optimization["currentYieldPct"] >= 0
        assert optimization["yieldScenarios"]["20%"]["rawCandidatesNeededFor53Parents"] == 265
        assert optimization["yieldScenarios"]["40%"]["rawCandidatesNeededFor53Parents"] == 133
        assert optimization["yieldScenarios"]["50%"]["rawCandidatesNeededFor53Parents"] == 106
        assert optimization["humanBottleneckAnalysis"]["accountsSupportedPerOperator"] >= 0
        assert optimization["whatThreeFixesIncreaseYieldFastest"]
        assert optimization["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_discoverability_loss_analysis_categorizes_preventable_rejections(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption = ?,
                caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                "DM me, link in bio, add me on Snapchat, OnlyFans",
                json.dumps({
                    "caption_text": "DM me, link in bio, add me on Snapchat, OnlyFans",
                    "instagram_post_caption": "DM me, link in bio",
                }),
            ),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        analysis = cf.parent_factory_discoverability_loss_analysis()

        assert cf.conn.total_changes == before
        assert analysis["schema"] == "creator_os.parent_factory_discoverability_loss_analysis.v1"
        categories = {row["category"]: row["frequency"] for row in analysis["discoverabilityRejectionCategories"]}
        assert categories["dm_language"] >= 1
        assert categories["bio_reference"] >= 1
        assert categories["snapchat_reference"] >= 1
        assert categories["onlyfans_reference"] >= 1
        assert analysis["percentPreventableAtCaptionCreation"] > 0
        assert analysis["percentPreventableAtGeneration"] >= 0
        assert analysis["percentPreventableAtRegistration"] >= 0
        assert analysis["wouldWrite"] is False
    finally:
        cf.close()


def test_capture_publishability_rejection_evidence_stores_exact_discoverability_terms(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET review_state = 'approved',
                caption = ?,
                caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                "DM me",
                json.dumps({
                    "caption_text": "DM me",
                    "burned_caption_text": "DM me",
                    "instagram_post_caption": "link in bio",
                    "captionPlacementDecision": {"status": "passed"},
                }),
            ),
        )
        cf.conn.commit()

        result = cf.capture_publishability_rejection_evidence("asset_1")
        second = cf.capture_publishability_rejection_evidence("asset_1")
        rows = [
            dict(row)
            for row in cf.conn.execute(
                "SELECT * FROM asset_rejection_evidence WHERE rendered_asset_id = ? ORDER BY failure_category, source_field",
                ("asset_1",),
            ).fetchall()
        ]

        assert result["schema"] == "campaign_factory.rejection_evidence_capture.v1"
        assert result["capturedCount"] >= 2
        assert second["capturedCount"] == result["capturedCount"]
        assert {row["failed_stage"] for row in rows} == {"discoverability_safety_pass"}
        assert {"dm_language", "bio_reference"} <= {row["failure_category"] for row in rows}
        assert "burned_caption_text" in {row["source_field"] for row in rows}
        assert "instagram_post_caption" in {row["source_field"] for row in rows}
        assert all(row["policy_version"] == "discoverability_safe_v1" for row in rows)
        assert all(row["repairable"] == 1 for row in rows)
    finally:
        cf.close()


def test_parent_factory_discoverability_loss_analysis_prefers_captured_evidence(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET review_state = 'approved',
                caption = ?,
                caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                "DM me on Telegram",
                json.dumps({
                    "caption_text": "DM me on Telegram",
                    "burned_caption_text": "DM me on Telegram",
                    "instagram_post_caption": "DM me on Telegram",
                    "captionPlacementDecision": {"status": "passed"},
                }),
            ),
        )
        cf.conn.commit()
        cf.capture_publishability_rejection_evidence("asset_1")
        before = cf.conn.total_changes

        analysis = cf.parent_factory_discoverability_loss_analysis()

        assert cf.conn.total_changes == before
        categories = {row["category"]: row["frequency"] for row in analysis["discoverabilityRejectionCategories"]}
        assert categories["dm_language"] >= 1
        assert categories["telegram_reference"] >= 1
        assert analysis["capturedEvidenceCount"] >= 2
        assert analysis["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_master_optimization_report_exposes_discoverability_breakdown(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        report = cf.parent_factory_master_optimization_report(required_parents_per_day=53)

        assert cf.conn.total_changes == before
        breakdown = report["discoverabilityLossAnalysis"]
        assert breakdown["schema"] == "creator_os.parent_factory_discoverability_loss_analysis.v1"
        assert {row["category"] for row in breakdown["discoverabilityRejectionCategories"]} >= {
            "dm_language",
            "link_language",
            "off_platform_reference",
            "onlyfans_reference",
            "telegram_reference",
            "snapchat_reference",
            "whatsapp_reference",
            "bio_reference",
            "cta_language",
            "other",
        }
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_master_optimization_report_answers_acceptance_questions(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        report = cf.parent_factory_master_optimization_report(required_parents_per_day=53)

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.parent_factory_master_optimization_report.v1"
        acceptance = report["acceptanceCriteria"]
        assert acceptance["whyYieldIs8_2Pct"]
        assert acceptance["whatSingleFixImprovesYieldMost"]
        assert len(acceptance["whatThreeFixesIncreaseYieldFastest"]) == 3
        assert acceptance["expectedYieldAfterFixes"] >= report["optimizationPlan"]["currentYieldPct"]
        assert acceptance["newRawCandidatesNeededFor53Parents"] <= report["optimizationPlan"]["currentRawCandidatesNeededFor53Parents"]
        assert isinstance(acceptance["canSupport200AccountsAfterFixes"], bool)
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_discoverability_upstream_gates_block_unsafe_text_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        payload = {
            "source_caption": "normal mirror caption",
            "generated_caption": "DM me",
            "burned_caption_text": "link in bio",
            "instagram_post_caption": "casual post caption",
        }

        intake = cf.discoverability_intake_gate(payload)
        generation = cf.discoverability_generation_gate(payload)
        pre_render = cf.discoverability_pre_render_gate(payload)

        assert cf.conn.total_changes == before
        assert intake["schema"] == "campaign_factory.discoverability_intake_gate.v1"
        assert generation["schema"] == "campaign_factory.discoverability_generation_gate.v1"
        assert pre_render["schema"] == "campaign_factory.discoverability_pre_render_gate.v1"
        assert intake["canProceed"] is True
        assert generation["canProceed"] is False
        assert pre_render["canProceed"] is False
        assert {item["sourceField"] for item in pre_render["violations"]} >= {"generated_caption", "burned_caption_text"}
        assert {item["failureCategory"] for item in pre_render["violations"]} >= {"dm_language", "bio_reference"}
        assert all(item["wouldWrite"] is False for item in [intake, generation, pre_render])
    finally:
        cf.close()


def test_parent_factory_yield_recovery_math_uses_measured_waterfall(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        origin = cf.discoverability_violation_origin_map()
        recovery = cf.parent_factory_recoverable_yield()
        throughput = cf.parent_factory_throughput_recovery_plan()
        feasibility = cf.parent_factory_53_parent_feasibility()

        assert cf.conn.total_changes == before
        assert origin["schema"] == "creator_os.discoverability_violation_origin_map.v1"
        assert origin["whereViolationsFirstAppear"]
        assert origin["earliestPreventableStage"] in {"source_content_perception", "prompt_generation", "caption_generation", "burned_caption_generation", "caption_family_generation", "parent_registration", "publishability_validation"}
        assert 0 <= origin["percentPreventableBeforeRender"] <= 100
        assert 0 <= origin["percentPreventableBeforeRegistration"] <= 100
        assert recovery["schema"] == "creator_os.parent_factory_recoverable_yield.v1"
        assert recovery["currentYieldPct"] == 8.2
        assert recovery["yieldIfDiscoverabilityFixed"] > recovery["currentYieldPct"]
        assert recovery["yieldIfBothFixed"] >= recovery["yieldIfDiscoverabilityFixed"]
        assert recovery["requiredRawCandidatesFor53Parents"] <= 647
        assert throughput["schema"] == "creator_os.parent_factory_throughput_recovery_plan.v1"
        assert throughput["requiredParentsPerDay"] == 53
        assert throughput["currentParentsPerDay"] == 20
        assert throughput["gap"] == 33
        assert throughput["largestLossStage"] == "discoverability_safety_pass"
        assert throughput["expectedGainFromRepair"] > 0
        assert feasibility["schema"] == "creator_os.parent_factory_53_parent_feasibility.v1"
        assert feasibility["minimumYieldRequired"] == 21.6
        assert feasibility["minimumCandidatesRequired"] == 245
        assert feasibility["highestROIChange"]
        assert feasibility["recommendedNextImplementation"]
        assert all(item["wouldWrite"] is False for item in [origin, recovery, throughput, feasibility])
    finally:
        cf.close()


def test_parent_factory_secondary_loss_model_does_not_assume_perfect_recovery(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        secondary = cf.parent_factory_secondary_loss_analysis()
        repaired_waterfall = cf.parent_factory_waterfall_after_discoverability()
        true_yield = cf.parent_factory_true_yield_model()
        realistic = cf.parent_factory_realistic_53_parent_plan()

        assert cf.conn.total_changes == before
        assert secondary["schema"] == "creator_os.parent_factory_secondary_loss_analysis.v1"
        assert secondary["discoverabilityRemoved"] is True
        assert secondary["newLargestLossStage"] == "none_measured_after_discoverability"
        assert secondary["rankedLossStages"]
        assert secondary["nextBottleneck"] == "downstream_sample_size_uncertainty"
        assert repaired_waterfall["schema"] == "creator_os.parent_factory_waterfall_after_discoverability.v1"
        assert repaired_waterfall["discoverabilityRemoved"] is True
        assert repaired_waterfall["stages"][0]["stage"] == "raw_candidate"
        assert all(row["stage"] != "discoverability_safety_pass" for row in repaired_waterfall["stages"])
        assert true_yield["schema"] == "creator_os.parent_factory_true_yield_model.v1"
        assert true_yield["currentYieldPct"] == 8.2
        assert true_yield["theoreticalUpperBoundYieldPct"] == 100.0
        assert true_yield["realisticYieldAfterDiscoverabilityRepair"] < true_yield["theoreticalUpperBoundYieldPct"]
        assert true_yield["acceptedParentsPer245Candidates"] < 245
        assert realistic["schema"] == "creator_os.parent_factory_realistic_53_parent_plan.v1"
        assert realistic["discoverabilityRemoved"] is True
        assert realistic["expectedRealYieldPct"] == true_yield["realisticYieldAfterDiscoverabilityRepair"]
        assert realistic["requiredCandidatesFor53Parents"] >= 53
        assert realistic["highestROIAfterDiscoverability"]
        assert all(item["wouldWrite"] is False for item in [secondary, repaired_waterfall, true_yield, realistic])
    finally:
        cf.close()


def test_parent_factory_53_parent_trial_reports_measured_throughput_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        trial = cf.parent_factory_53_parent_trial()
        results = cf.parent_factory_trial_results()
        analysis = cf.parent_factory_trial_analysis()

        assert cf.conn.total_changes == before
        assert trial["schema"] == "creator_os.parent_factory_53_parent_trial.v1"
        assert trial["targetParents"] == 53
        assert trial["actualCandidates"] == 245
        assert trial["acceptedParents"] == 20
        assert trial["yieldPct"] == 8.2
        assert trial["discoverabilityFailures"] == 225
        assert trial["publishabilityFailures"] == 0
        assert trial["qualityFailures"] == 0
        assert trial["duplicateFailures"] == 0
        assert trial["otherFailures"] == 0
        assert trial["trialPassed"] is False
        assert trial["limitingStep"] == "discoverability_safety_pass"
        assert trial["wouldWrite"] is False
        assert results["schema"] == "creator_os.parent_factory_trial_results.v1"
        assert results["trialPassed"] is False
        assert results["largestLossStage"] == "discoverability_safety_pass"
        assert results["repairable"] is True
        assert results["estimatedRecoveredParents"] == 225
        assert results["rankedLosses"][0] == {"stage": "discoverability_safety_pass", "count": 225}
        assert analysis["schema"] == "creator_os.parent_factory_trial_analysis.v1"
        assert analysis["statement"] == (
            "The factory produced 20 accepted parents from 245 candidates. "
            "The limiting factor was discoverability_safety_pass."
        )
        assert analysis["measuredOnly"] is True
        assert all(item["wouldWrite"] is False for item in [trial, results, analysis])
    finally:
        cf.close()


def test_parent_factory_53_parent_trial_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "parent-factory-53-parent-trial",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["schema"] == "creator_os.parent_factory_53_parent_trial.v1"
    assert payload["targetParents"] == 53
    assert payload["trialPassed"] is False
    assert payload["limitingStep"] == "discoverability_safety_pass"
    assert payload["wouldWrite"] is False


def test_parent_factory_post_gate_fresh_batch_proof_uses_sandbox_and_real_gates(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        proof = cf.parent_factory_post_gate_fresh_batch_proof()

        assert cf.conn.total_changes == before
        assert proof["schema"] == "creator_os.parent_factory_post_gate_fresh_batch_proof.v1"
        assert proof["freshBatch"] is True
        assert proof["fixtureBatch"] is True
        assert proof["targetAcceptedParents"] == 53
        assert proof["rawCandidates"] >= 64
        assert proof["blockedBeforeRender"] > 0
        assert proof["blockedBeforeRender"] + proof["registeredParents"] == proof["rawCandidates"]
        assert proof["renderJobsAvoided"] == proof["blockedBeforeRender"]
        assert proof["renderJobsCreated"] == proof["registeredParents"]
        assert proof["registeredParents"] == proof["acceptedParents"]
        assert proof["acceptedParents"] == 53
        assert proof["yieldPct"] >= 50
        assert proof["lateDiscoverabilityFailures"] == 0
        assert proof["publishabilityFailures"] == 0
        assert proof["qualityFailures"] == 0
        assert proof["duplicateFailures"] == 0
        assert proof["otherFailures"] == 0
        assert proof["targetParentsReached"] is True
        assert proof["successCriteria"]["passed"] is True
        assert proof["successCriteria"]["strongPass"] is True
        assert proof["comparison"]["baseline"]["acceptedParents"] == 20
        assert proof["comparison"]["baseline"]["lateDiscoverabilityFailures"] == 225
        assert proof["comparison"]["improvement"]["lateDiscoverabilityFailuresReduced"] is True
        assert proof["comparison"]["improvement"]["yieldImproved"] is True
        assert proof["comparison"]["improvement"]["acceptedParentLift"] >= 33
        assert proof["blockedCandidates"]
        assert all(item["renderJobCreated"] is False for item in proof["blockedCandidates"])
        assert all(item["sourceAssetCreated"] is False for item in proof["blockedCandidates"])
        assert all(item["renderedAssetCreated"] is False for item in proof["blockedCandidates"])
        assert {item["blockedAt"] for item in proof["blockedCandidates"]} == {"discoverability_pre_render_gate"}
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_post_gate_fresh_batch_proof_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "parent-factory-post-gate-fresh-batch-proof",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["schema"] == "creator_os.parent_factory_post_gate_fresh_batch_proof.v1"
    assert payload["freshBatch"] is True
    assert payload["lateDiscoverabilityFailures"] == 0
    assert payload["blockedBeforeRender"] > 0
    assert payload["renderJobsAvoided"] > 0
    assert payload["targetParentsReached"] is True
    assert payload["wouldWrite"] is False


def test_parent_factory_master_optimization_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "parent-factory-master-optimization-report",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.parent_factory_master_optimization_report.v1"
    assert payload["acceptanceCriteria"]["whatSingleFixImprovesYieldMost"]
    assert payload["wouldWrite"] is False


def test_parent_factory_discoverability_loss_analysis_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "parent-factory-discoverability-loss-analysis",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.parent_factory_discoverability_loss_analysis.v1"
    assert payload["discoverabilityRejectionCategories"]
    assert payload["wouldWrite"] is False


def test_capture_publishability_rejection_evidence_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption = ?,
                caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                "DM me",
                json.dumps({
                    "caption_text": "DM me",
                    "burned_caption_text": "DM me",
                    "instagram_post_caption": "DM me",
                    "captionPlacementDecision": {"status": "passed"},
                }),
            ),
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.creator_os_cli",
            "capture-publishability-rejection-evidence",
            "--asset-id",
            "asset_1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite")},
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.rejection_evidence_capture.v1"
    assert payload["capturedCount"] >= 1
    assert payload["wouldWrite"] is True
