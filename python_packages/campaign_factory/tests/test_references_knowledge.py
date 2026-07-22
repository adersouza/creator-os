from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import campaign_factory.core as core_module
import campaign_factory.daily_library_production as daily_library_module
import pytest
from campaign_asset_test_support import (
    add_audit_report,
    add_inventory_parent_fixture,
    table_count,
)
from campaign_factory.adapters import contentforge as contentforge_adapter
from campaign_factory.adapters.contentforge import audit_campaign
from campaign_factory.caption_outcome import (
    build_caption_outcome_context,
    column_values,
)
from campaign_factory.contracts import validate_front_generation_plan
from campaign_factory.front_generation_stage import run_front_generation_stage
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.static_mp4_stage import run_static_mp4_stage
from campaign_generation_test_support import (
    fake_front_generation_result,
    fake_static_mp4_render,
    write_fake_static_mp4_outputs,
)
from campaign_learning_test_support import _insert_creative_kb_snapshot
from campaign_test_support import (
    add_rendered_asset,
    add_source_asset,
    make_factory,
    set_test_source_prompt,
)


def test_daily_library_identity_cache_tracks_reference_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    reference_set = (
        cf.settings.reel_factory_root / "identity_references" / "stacey.json"
    )
    reference_set.parent.mkdir(parents=True)
    reference_set.write_text('{"referenceSetId":"one"}', encoding="utf-8")
    source = {
        "id": "src_1",
        "content_hash": "abc123",
        "stored_path": str(tmp_path / "clip.mp4"),
    }
    calls = 0

    def passed(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                {
                    "schema": "reel_factory.identity_verification.v1",
                    "status": "passed",
                    "score": 0.9,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(daily_library_module.subprocess, "run", passed)
    try:
        daily_library_module._verify_library_identity(cf, source)
        daily_library_module._verify_library_identity(cf, source)
        reference_set.write_text('{"referenceSetId":"two"}', encoding="utf-8")
        daily_library_module._verify_library_identity(cf, source)
        assert calls == 2
    finally:
        cf.close()


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


def test_import_folder_reference_mode_catalogs_without_copying(tmp_path: Path):
    folder = tmp_path / "external_library"
    folder.mkdir()
    source = folder / "stacey.mp4"
    source.write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        result = cf.domains.asset_import.import_folder(
            folder,
            campaign_slug="stacey_library",
            model_slug="stacey",
            storage_mode="reference",
        )

        assert result["storageMode"] == "reference"
        assert len(result["imported"]) == 1
        imported = result["imported"][0]
        assert imported["original_path"] == str(source.resolve())
        assert imported["stored_path"] == str(source.resolve())
        campaign_sources = (
            tmp_path / "campaigns" / "stacey" / "stacey_library" / "00_sources"
        )
        assert list(campaign_sources.iterdir()) == []
        job = cf.conn.execute(
            "SELECT input_json FROM pipeline_jobs WHERE job_type = 'import_folder'"
        ).fetchone()
        assert json.loads(job["input_json"])["storageMode"] == "reference"
    finally:
        cf.close()


def test_reference_bank_import_select_and_prepare(tmp_path: Path):
    bank_path = tmp_path / "campaign_reference_bank.json"
    prompt_pack_path = tmp_path / "higgsfield_prompt_pack_top300.json"
    bank_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.campaign_reference_bank.v1",
                "clusters": [
                    {
                        "clusterRank": 1,
                        "clusterKey": "caption_led_visual::direct_response::question_hook",
                        "embeddingClusterId": "emb_test_cluster",
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
            }
        )
    )
    prompt_pack_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.higgsfield_prompt_pack.v1",
                "prompts": [
                    {
                        "clusterKey": "caption_led_visual::direct_response::question_hook",
                        "referenceIds": ["ref_1"],
                        "publicUrls": ["https://instagram.com/p/example/"],
                        "higgsfieldJson": {"scene": "caption-led vertical reel"},
                        "captionFormulas": [
                            {
                                "formula": "{direct question}?",
                                "exampleCaptions": ["red or pink ?"],
                            }
                        ],
                        "audioRecommendations": {
                            "primaryStrategy": "current_native_trending_sound",
                            "nativeAudioPreferred": True,
                        },
                    }
                ],
            }
        )
    )
    (tmp_path / "ref.mp4").write_bytes(b"reference")
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        preview = cf.domains.reference.import_reference_bank(
            bank_path,
            prompt_pack_path,
            dry_run=True,
            require_local_paths=True,
        )
        assert preview["dryRun"] is True
        assert preview["patternsCreated"] == 1
        assert cf.domains.reference.reference_patterns()["patterns"] == []
        imported = cf.domains.reference.import_reference_bank(
            bank_path, prompt_pack_path
        )
        assert imported["patternsImported"] == 1
        assert imported["patternsCreated"] == 1
        repeated = cf.domains.reference.import_reference_bank(
            bank_path, prompt_pack_path
        )
        assert repeated["patternsImported"] == 0
        assert repeated["patternsUnchanged"] == 1
        patterns = cf.domains.reference.reference_patterns()
        assert (
            patterns["patterns"][0]["raw"]["bank"]["embeddingClusterId"]
            == "emb_test_cluster"
        )
        assert (
            patterns["patterns"][0]["captionFormulas"][0]["formula"]
            == "{direct question}?"
        )
        assert (
            patterns["patterns"][0]["audioRecommendations"]["primaryStrategy"]
            == "light_trending_response_sound"
        )
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        linked = cf.domains.reference.import_reference_bank(
            bank_path,
            prompt_pack_path,
            campaign_slug="may",
        )
        assert linked["campaignLinksCreated"] == 1
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM campaign_reference_plans").fetchone()[
                0
            ]
            == 1
        )
        prepared = cf.domains.reference.prepare_reel_from_reference(
            campaign_slug="may",
            cluster_key="caption_led_visual::direct_response::question_hook",
            variant_count=2,
            recipes=["v01_original"],
        )
        assert prepared["selection"]["pattern"]["label"].startswith(
            "caption led visual"
        )
        sidecar = (
            cf.settings.reel_factory_root
            / "01_captions"
            / f"{prepared['prepare']['prepared'][0]['reel_clip_stem']}.json"
        )
        sidecar_data = json.loads(sidecar.read_text())
        assert sidecar_data["hooks"][0] == "red or pink ?"
        assert (
            sidecar_data["hook_metadata"][0]["referenceClusterKey"]
            == "caption_led_visual::direct_response::question_hook"
        )
        assert sidecar_data["hook_metadata"][0]["text"] == "red or pink ?"
        assert sidecar_data["hook_metadata"][0]["candidateKind"] == "example_caption"
        assert (
            sidecar_data["hook_metadata"][0]["audioRecommendations"]["primaryStrategy"]
            == "light_trending_response_sound"
        )
        generation_payload = cf.domains.reel_execution.caption_generation_for_clip(
            prepared["prepare"]["prepared"][0]["reel_clip_stem"]
        )
        assert (
            generation_payload["audioRecommendations"]["primaryStrategy"]
            == "light_trending_response_sound"
        )
        second = cf.domains.reference.prepare_reel_from_reference(
            campaign_slug="may",
            cluster_key="caption_led_visual::direct_response::question_hook",
            variant_count=1,
            recipes=["v01_original"],
        )
        assert (
            second["prepare"]["prepared"][0]["reel_clip_stem"]
            != prepared["prepare"]["prepared"][0]["reel_clip_stem"]
        )
        assert second["prepare"]["reusedExisting"] == []
    finally:
        cf.close()


def test_reference_bank_import_expands_portable_local_paths(
    tmp_path: Path, monkeypatch
):
    reference_root = tmp_path / "reference_reels"
    reference_root.mkdir()
    reference_file = reference_root / "portable.mp4"
    reference_file.write_bytes(b"reference")
    monkeypatch.setenv("REFERENCE_REELS_ROOT", str(reference_root))
    bank_path = tmp_path / "portable-bank.json"
    bank_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.campaign_reference_bank.v1",
                "clusters": [
                    {
                        "clusterKey": "portable_cluster",
                        "label": "Portable cluster",
                        "localPaths": ["${REFERENCE_REELS_ROOT}/portable.mp4"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        result = cf.domains.reference.import_reference_bank(
            bank_path, require_local_paths=True
        )
        assert result["missingLocalPaths"] == []
        pattern = cf.domains.reference.reference_patterns()["patterns"][0]
        assert pattern["localPaths"] == [str(reference_file)]
    finally:
        cf.close()


def test_reference_bank_import_can_replace_campaign_links(tmp_path: Path):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(
        json.dumps(
            {"clusters": [{"clusterKey": "old", "label": "Old", "localPaths": []}]}
        ),
        encoding="utf-8",
    )
    second_path.write_text(
        json.dumps(
            {"clusters": [{"clusterKey": "new", "label": "New", "localPaths": []}]}
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source"
    source.mkdir()
    (source / "video.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            source, campaign_slug="may", model_slug="model"
        )
        cf.domains.reference.import_reference_bank(first_path, campaign_slug="may")
        preview = cf.domains.reference.import_reference_bank(
            second_path,
            campaign_slug="may",
            dry_run=True,
            replace_campaign_links=True,
        )
        assert preview["campaignLinksCreated"] == 1
        assert preview["campaignLinksRemoved"] == 1
        applied = cf.domains.reference.import_reference_bank(
            second_path, campaign_slug="may", replace_campaign_links=True
        )
        assert applied["campaignLinksRemoved"] == 1
        linked_pattern = cf.conn.execute(
            """SELECT rp.cluster_key FROM campaign_reference_plans crp
            JOIN reference_patterns rp ON rp.id = crp.reference_pattern_id"""
        ).fetchone()["cluster_key"]
        assert linked_pattern == "new"
    finally:
        cf.close()


def test_reference_hooks_filter_only_objective_safety_failures(tmp_path: Path):
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
                        "men, stop doing this:",
                        "this caption is intentionally way too long for schedule safe burned reel placement",
                        "GOING LIVE TONIGHT!!!",
                        "he can’t resist me 😈",
                        "Who’s my good boy then",
                        "Du entscheidest🇦🇹🇩🇪",
                        "this could be us but you're too scared to text me",
                        "link in bio",
                        "mirror check",
                    ],
                }
            ],
            "audioRecommendations": {},
        }

        hooks = cf.domains.reference.reference_hooks(pattern, count=7)

        assert [hook["text"] for hook in hooks] == [
            "this caption is intentionally way too long for schedule safe burned reel placement",
            "GOING LIVE TONIGHT!!!",
            "he can’t resist me 😈",
            "Who’s my good boy then",
            "Du entscheidest🇦🇹🇩🇪",
            "this could be us but you're too scared to text me",
            "mirror check",
        ]
        assert all(hook["candidateKind"] == "example_caption" for hook in hooks)
    finally:
        cf.close()


def test_reference_hooks_use_safe_fallbacks_when_every_candidate_is_blocked(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        pattern = {
            "clusterKey": "caption_led_visual::hard_blocked",
            "label": "hard blocked",
            "hookType": "curiosity_gap",
            "captionArchetype": "short_meme_caption",
            "captionFormulas": [
                {
                    "formula": "{unresolved hook}",
                    "exampleCaptions": [
                        "DM me",
                        "link in bio",
                        "subscribe",
                        "onlyfans",
                    ],
                }
            ],
            "audioRecommendations": {},
        }

        hooks = cf.domains.reference.reference_hooks(pattern, count=3)

        assert [hook["text"] for hook in hooks] == [
            "new fit today",
            "which one wins?",
            "felt cute",
        ]
        assert all(hook["candidateKind"] == "simple_native_fallback" for hook in hooks)
    finally:
        cf.close()


def test_audio_decision_prefers_resolved_instagram_over_unresolved_and_tiktok(
    tmp_path: Path,
):
    catalog_path = tmp_path / "audio_decision.json"
    catalog_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        cf.domains.audio_recommendations.import_audio_memory(catalog_path)
        result = cf.domains.audio_recommendations.recommend_audio(
            platform="instagram", content_tags=["mirror", "glam"], limit=3
        )
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
    catalog_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        cf.domains.audio_recommendations.import_audio_memory(catalog_path)
        result = cf.domains.audio_recommendations.recommend_audio(
            platform="instagram", content_tags=["glam"], limit=2
        )
        decision = result["decision"]

        assert decision["primaryAudio"]["catalogAudioId"] == "safe"
        assert decision["doNotUseAudios"][0]["catalogAudioId"] == "tired"
        assert "stale_trend" in decision["doNotUseAudios"][0]["riskFlags"]
    finally:
        cf.close()


def test_audio_memory_v2_balanced_scoring_prefers_ofm_velocity_and_low_fatigue(
    tmp_path: Path,
):
    catalog_path = tmp_path / "audio_v2.json"
    catalog_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        cf.domains.audio_recommendations.import_audio_memory(catalog_path)
        result = cf.domains.audio_recommendations.recommend_audio(
            platform="instagram",
            content_tags=["mirror", "fit_check"],
            account="ig_1",
            limit=2,
        )
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


def test_finished_video_intake_uses_reference_pipeline_metadata(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "mirror_selfie_finished.mp4"
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
                "referenceSelection": {"clusterKey": kwargs["reference_pattern"]},
                "dryRunExport": {"dryRun": True},
            }

        monkeypatch.setattr(cf.domains.make_batch_repo, "make_batch", fake_make_batch)

        result = cf.domains.finished_video.intake_finished_video(
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
        assert (
            source_prompt["strategy"]["distributionPriority"] == "instagram_reels_first"
        )
        assert source_prompt["strategy"]["primaryMetric"] == "views_reach"
        assert source_prompt["strategy"]["humanReviewRequired"] is True
        assert source_prompt["strategy"]["nativeAudioRequired"] is True
        assert source_prompt["sourcePreflight"]["warnings"] == []
        assert (
            source_prompt["generatedAssetLineage"]["schema"]
            == "reel_factory.generated_asset_lineage.v1"
        )
        assert (
            source_prompt["generatedAssetLineage"]["source"]["formatType"]
            == "mirror_selfie"
        )
    finally:
        cf.close()


def test_sync_creative_plan_progress_counts_reference_prompt_exports(tmp_path: Path):
    prompt_export = tmp_path / "generated_video_prompts.json"
    cf = make_factory(tmp_path)
    try:
        plan = cf.domains.creative_planning.create_creative_plan(
            name="daily_plan", target_account="staceybennetx", daily_base_video_target=4
        )
        prompt_export.write_text(
            json.dumps(
                {
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
                }
            ),
            encoding="utf-8",
        )

        result = cf.domains.creative_planning.sync_creative_plan_progress(
            name="daily_plan", prompt_export_path=prompt_export
        )

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


def test_front_generation_prompt_pack_uses_selected_reference_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")
        campaign = cf.domains.campaign_by_slug("may")
        cf.conn.execute(
            """
            INSERT INTO reference_patterns (
              id, cluster_key, rank, label, visual_format, hook_type, caption_archetype,
              reference_ids_json, local_paths_json, public_urls_json, prompt_template_json,
              higgsfield_json, caption_formulas_json, raw_json, imported_at, updated_at
            ) VALUES (
              'refpat_prompt', 'mirror_curiosity', 1, 'Mirror curiosity winner',
              'mirror_selfie', 'curiosity_gap', 'question_hook',
              '[]', '[]', '[]', ?, '{}', '[]', '{}', 'now', 'now'
            )
            """,
            (
                json.dumps(
                    {
                        "visual": "mirror selfie with phone-camera framing",
                        "captionOverlay": "short question hook",
                    }
                ),
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO campaign_reference_plans
            (id, campaign_id, reference_pattern_id, variant_count, created_at, updated_at)
            VALUES ('plan_prompt', ?, 'refpat_prompt', 3, 'now', 'now')
            """,
            (campaign["id"],),
        )
        cf.conn.commit()

        monkeypatch.setattr(
            "campaign_factory.front_generation_stage._invoke_generate_assets",
            lambda _factory, args: fake_front_generation_result(args),
        )

        result = run_front_generation_stage(
            cf,
            campaign_slug="may",
            reference_image_path=reference,
            creator="Stacey",
            execution_plan=build_generation_execution_plan("soul_static"),
            dry_run=True,
        )

        validate_front_generation_plan(result["plan"])
        prompt_pack = json.loads(Path(result["promptPath"]).read_text(encoding="utf-8"))
        joined = json.dumps(prompt_pack, ensure_ascii=False).lower()
        assert (
            prompt_pack["learnedPromptGuidance"]["source"]
            == "campaign_factory.reference_pattern"
        )
        assert (
            prompt_pack["learnedPromptGuidance"]["referencePatternId"]
            == "refpat_prompt"
        )
        assert "mirror_selfie" in joined
        assert "curiosity_gap" in joined
        assert "question_hook" in joined
        assert "structural guidance only" in joined
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM rendered_assets").fetchone()[0] == 0
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM threadsdash_exports").fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_reused_static_mp4_repairs_direct_reference_features_without_rerender(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        captured_prompt = "A bedroom mirror selfie with slow natural movement."
        prompt_id = (
            "prompt_higgsfield_"
            + hashlib.sha256(captured_prompt.encode("utf-8")).hexdigest()[:16]
        )
        set_test_source_prompt(
            cf,
            source["id"],
            prompt_id=prompt_id,
            reference_id="identity_set:file_1",
        )
        still = tmp_path / "lca_test_direct_reference_9x16.png"
        still.write_bytes(b"accepted-static-still")
        invoke_count = 0

        def fake_invoke(_factory, **kwargs):
            nonlocal invoke_count
            invoke_count += 1
            write_fake_static_mp4_outputs(kwargs["output_path"])
            return fake_static_mp4_render(
                kwargs["still_path"], kwargs["output_path"], dry_run=False
            )

        monkeypatch.setattr(
            "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
            fake_invoke,
        )
        first = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=still,
            dry_run=False,
            apply=True,
        )
        lineage_path = tmp_path / "lca_test.direct_reference_lineage.json"
        lineage_path.write_text(
            json.dumps(
                {
                    "features": {
                        "scene": "bedroom",
                        "camera": "mirror_selfie",
                        "creator": "stacey",
                        "motion": "slow_pan",
                    },
                    "generation": {"capturedHiggsfieldPrompt": captured_prompt},
                    "assets": {"localPaths": {"image": str(still)}},
                }
            ),
            encoding="utf-8",
        )

        second = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=still,
            dry_run=False,
            apply=True,
        )

        assert first["registeredAsset"]["id"] == second["registeredAsset"]["id"]
        assert second["reused"] is True
        assert invoke_count == 1
        metadata = json.loads(second["registeredAsset"]["metadata_json"])
        lineage = metadata["generatedAssetLineage"]
        assert lineage["features"] == {
            "camera": "mirror_selfie",
            "creator": "stacey",
            "motion": "slow_pan",
            "scene": "bedroom",
        }
        assert lineage["source"]["sourceLineagePath"] == str(lineage_path)
        assert (
            json.loads(
                Path(metadata["generatedAssetLineagePath"]).read_text(encoding="utf-8")
            )
            == lineage
        )
    finally:
        cf.close()


def test_contentforge_audit_uses_selected_reference_pattern(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"reference")
    seen = {}

    def fake_similarity(
        base_url,
        *,
        source,
        target_file=None,
        audit_profile=None,
        layers,
        originality_reference_files=None,
        run_id=None,
    ):
        seen["layers"] = layers
        seen["references"] = originality_reference_files
        return {
            "auditProfile": audit_profile,
            "targetFile": target_file,
            "layers": {},
            "verdicts": {"originality": "pass"},
            "verdictCodes": {"originality": "originality_pass"},
            "overallVerdict": "pass",
            "referenceMatch": {
                "mode": "reference_match_meter",
                "referenceMatchLevel": "high",
            },
            "readinessSummary": {
                "uploadReady": True,
                "blockingCodes": [],
                "warningCodes": [],
            },
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
        campaign = cf.domains.campaign_by_slug("may")
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
        assert seen["references"] and seen["references"][0].startswith(
            "campaign_factory_reference_"
        )
        assert report["referencePattern"]["clusterKey"] == "cluster"
        assert report["referenceMatch"]["referenceMatchLevel"] == "high"
    finally:
        cf.close()


def test_publishability_blocks_reel_captions_with_dm_or_link_references(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "DM me for the link",
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
        cf.conn.commit()

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert (
            "unsafe_reel_caption_link_or_dm_reference"
            in explanation["publishability_failure_reasons"]
        )
        assert explanation["checks"]["reel_caption_account_safety_passed"] is False
        assert {
            item["reason"] for item in explanation["reelCaptionAccountSafetyViolations"]
        } == {
            "dm_reference",
            "link_reference",
        }
    finally:
        cf.close()


def test_caption_family_plan_is_read_only_and_produces_requested_versions(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        parent = add_inventory_parent_fixture(
            cf, tmp_path, asset_id="asset_caption_parent"
        )
        before = {
            "caption_families": table_count(cf, "caption_families"),
            "caption_versions": table_count(cf, "caption_versions"),
            "rendered_assets": table_count(cf, "rendered_assets"),
            "distribution_plans": table_count(cf, "distribution_plans"),
            "variant_assets": table_count(cf, "variant_assets"),
        }

        plan = cf.domains.caption_family.caption_family_plan(
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
        assert {
            version["captionFamilyIndex"] for version in plan["plannedVersions"]
        } == {1, 2, 3, 4, 5}
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


def test_caption_family_plan_keeps_burned_and_instagram_captions_separate_and_caps_hashtags(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_caption_parent'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post is up",
                        "caption_cta": "tell me if this works",
                        "hashtags": [
                            "#stacey",
                            "mirror fit",
                            "#reels",
                            "outfit",
                            "vote",
                            "extra_tag",
                        ],
                        "post_caption_style": "short_natural",
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
        cf.conn.commit()

        plan = cf.domains.caption_family.caption_family_plan(
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
        assert first["burnedCaptionHash"] == cf.domains.publishability.text_hash(
            first["burnedCaptionText"]
        )
        assert first["instagramPostCaptionHash"] == cf.domains.publishability.text_hash(
            first["instagramPostCaption"]
        )
        assert len(first["hashtags"]) <= 5
        assert first["captionCta"]
        assert first["postCaptionStyle"] == "ig_short"
    finally:
        cf.close()


def test_caption_family_plan_blocks_blank_instagram_post_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")

        plan = cf.domains.caption_family.caption_family_plan(
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


def test_caption_family_hashes_are_stable_and_create_only_caption_records(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        parent = add_inventory_parent_fixture(
            cf, tmp_path, asset_id="asset_caption_parent"
        )
        first = cf.domains.caption_family.caption_family_plan(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=3,
            style="ig_short",
            dry_run=True,
        )
        second = cf.domains.caption_family.caption_family_plan(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=3,
            style="ig_short",
            dry_run=True,
        )
        before_assets = table_count(cf, "rendered_assets")
        before_plans = table_count(cf, "distribution_plans")

        created = cf.domains.caption_family.caption_family_create(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=3,
            style="ig_short",
            dry_run=False,
        )

        assert [v["captionVersionId"] for v in first["plannedVersions"]] == [
            v["captionVersionId"] for v in second["plannedVersions"]
        ]
        assert [v["burnedCaptionHash"] for v in first["plannedVersions"]] == [
            v["burnedCaptionHash"] for v in second["plannedVersions"]
        ]
        assert created["wouldWrite"] is True
        assert created["createdCaptionVersions"] == 3
        assert table_count(cf, "caption_families") == 1
        assert table_count(cf, "caption_versions") == 3
        assert table_count(cf, "rendered_assets") == before_assets
        assert table_count(cf, "distribution_plans") == before_plans
        row = cf.conn.execute(
            "SELECT * FROM caption_versions WHERE caption_family_index = 1"
        ).fetchone()
        assert row["parent_reel_id"] == parent["parentReelId"]
        assert (
            row["burned_caption_hash"]
            == first["plannedVersions"][0]["burnedCaptionHash"]
        )
        assert (
            row["instagram_post_caption_hash"]
            == first["plannedVersions"][0]["instagramPostCaptionHash"]
        )
    finally:
        cf.close()


def test_reference_outcome_report_ranks_approved_measured_references(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("may", "stacey")
        now = datetime.now(UTC).isoformat()
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, caption_hash, recipe,
             post_id, platform, status, account_id, instagram_account_id, published_at,
             snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible,
             raw_json, created_at, history_source, lineage_v2_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'instagram', 'published', ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 1, ?, ?, 'metric_history', 1)
            """,
            (
                "perf_approved",
                campaign["id"],
                "asset_1",
                "source_1",
                "caption_1",
                "motion_edit",
                "post_1",
                "acct_1",
                "ig_1",
                "2026-06-21T12:00:00+00:00",
                "2026-06-22T12:00:00+00:00",
                240,
                json.dumps(
                    {
                        "metadata": {
                            "campaign_factory": {
                                "source_asset_id": "source_1",
                                "rendered_asset_id": "asset_1",
                                "caption_hash": "caption_1",
                                "generated_asset_lineage": {
                                    "source": {"referenceId": "ref_1"}
                                },
                                "operator_review": {
                                    "decision": "approved",
                                    "notes": "hook works",
                                },
                            }
                        }
                    }
                ),
                now,
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, caption_hash, recipe,
             post_id, platform, status, account_id, instagram_account_id, published_at,
             snapshot_at, views, metrics_eligible, raw_json, created_at, history_source, lineage_v2_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'instagram', 'published', ?, ?, ?, ?, ?, 1, ?, ?, 'metric_history', 1)
            """,
            (
                "perf_unmeasured",
                campaign["id"],
                "asset_2",
                "source_2",
                "caption_2",
                "motion_edit",
                "post_2",
                "acct_1",
                "ig_1",
                "2026-06-22T12:00:00+00:00",
                "2026-06-22T13:00:00+00:00",
                20,
                json.dumps(
                    {
                        "metadata": {
                            "campaign_factory": {
                                "source_asset_id": "source_2",
                                "rendered_asset_id": "asset_2",
                                "caption_hash": "caption_2",
                                "generated_asset_lineage": {
                                    "source": {"referenceId": "ref_2"}
                                },
                            }
                        }
                    }
                ),
                now,
            ),
        )
        cf.conn.commit()

        report = cf.domains.performance_summary_repo.reference_outcome_report("may")

        assert report["schema"] == "campaign_factory.reference_outcome_report.v1"
        assert report["rows"][0] == {
            "referenceId": "ref_1",
            "sourceAssetId": "source_1",
            "captionHash": "caption_1",
            "accountId": "acct_1",
            "reelsPosted": 1,
            "approvedCount": 1,
            "avgViews24h": 240,
            "measurementState": "measured",
            "operatorNotes": ["hook works"],
        }
        assert report["rows"][1]["referenceId"] == "ref_2"
        assert report["rows"][1]["measurementState"] == "unmeasured"
    finally:
        cf.close()


def test_creative_knowledge_base_reports_insufficient_data_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("stacey_creative_kb", "stacey")
        before = cf.conn.total_changes

        report = cf.domains.creative_knowledge.creative_knowledge_base(
            creator="Stacey", campaign_slug=campaign["slug"]
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "campaign_factory.creative_knowledge_base.v1"
        assert report["creator"] == "Stacey"
        assert report["insufficientData"] is True
        assert report["reason"] == "not_enough_published_metrics"
        assert report["topCaptionAngles"] == []
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creative_knowledge_base_aggregates_dimensions_and_weighted_scores(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("stacey_creative_kb", "stacey")
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

        report = cf.domains.creative_knowledge.creative_knowledge_base(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )

        assert cf.conn.total_changes == before
        assert report["insufficientData"] is False
        assert report["wouldWrite"] is False
        assert report["metricsContract"]["visibleMetricFields"] == [
            "views",
            "reach",
            "likes",
            "comments",
            "shares",
            "saves",
            "followers",
            "profile_visits",
        ]
        assert report["topCaptionAngles"][0]["key"] == "tease"
        assert report["topCaptionAngles"][0]["sampleSize"] == 2
        assert report["topCaptionAngles"][0]["avgViews"] == 750
        assert report["topCaptionAngles"][0]["score"] == 540.5
        assert report["topAudioIds"][0]["key"] == "audio_12"
        assert report["topSurfaces"][0]["key"] == "reel"
        assert {item["key"] for item in report["topSurfaces"]} == {
            "reel",
            "story",
            "feed_single",
        }
        assert report["topStoryIntents"][0]["key"] == "snapchat_promo"
        assert report["topAccountTiers"][0]["key"] == "growth"
        assert report["topPostingWindows"][0]["key"] in {"6pm", "9pm"}
        assert report["topCaptionVersions"][0]["key"] == "cver_1"

        caption_report = cf.domains.creative_knowledge.creative_caption_report(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        audio_report = cf.domains.creative_knowledge.creative_audio_report(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        surface_report = cf.domains.creative_knowledge.creative_surface_report(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        tier_report = cf.domains.creative_knowledge.creative_account_tier_report(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        window_report = cf.domains.creative_knowledge.creative_window_report(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )

        assert caption_report["captionAngles"][0]["key"] == "tease"
        assert audio_report["audioIds"][0]["key"] == "audio_12"
        assert surface_report["surfaces"]
        assert tier_report["accountTiers"]
        assert window_report["postingWindows"]
        assert all(
            item["wouldWrite"] is False
            for item in [
                caption_report,
                audio_report,
                surface_report,
                tier_report,
                window_report,
            ]
        )
    finally:
        cf.close()
