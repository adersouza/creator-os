from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from campaign_asset_test_support import (
    add_audit_report,
    add_variant_fixture,
    table_count,
)
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.adapters import (
    threadsdash_metrics_ingestion as threadsdash_metrics_adapter,
)
from campaign_factory.adapters.threadsdash_draft_payload import build_draft_payloads
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
from campaign_factory.contracts import (
    validate_performance_sync,
    validate_recommendation_accuracy_report,
    validate_recommendation_next_batch,
)
from campaign_learning_test_support import (
    _insert_creative_kb_snapshot,
    _manager_report_fixture,
    add_account_requirement_fixture,
    threadsdash_campaign_factory_metadata,
)
from campaign_test_support import add_rendered_asset, make_factory


def test_audio_catalog_import_and_recommendation_flow(tmp_path: Path):
    catalog_path = tmp_path / "audio_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        imported = cf.domains.audio_recommendations.import_audio_catalog(catalog_path)
        recs = cf.domains.audio_recommendations.recommend_audio(
            platform="instagram",
            content_tags=["fit_check", "glam"],
            account_tags=["ig_a"],
            limit=2,
        )

        assert imported["tracksImported"] == 2
        assert recs["recommendations"][0]["audioTitle"] == "Runway Pop"
        assert (
            recs["recommendations"][0]["platformUrl"] == "https://instagram.com/audio/1"
        )
        assert recs["recommendations"][0]["safeUsageNotes"] == "attach natively"
    finally:
        cf.close()


def test_audio_memory_import_selects_and_graphs_recommended_audio(tmp_path: Path):
    catalog_path = tmp_path / "audio_memory.json"
    catalog_path.write_text(
        json.dumps(
            {
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
                        "trendSnapshots": [
                            {
                                "observedAt": "2026-01-01T00:00:00+00:00",
                                "trendStatus": "rising",
                                "usageCount": 50000,
                                "velocityScore": 88,
                            }
                        ],
                        "exampleReels": ["https://instagram.com/reel/example"],
                        "performanceSummary": {"postCount": 3, "performanceLift": 12},
                        "fatigue": {"level": "low"},
                        "resolved": True,
                        "sourceConfidence": 0.9,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        first_import = cf.domains.audio_recommendations.import_audio_memory(
            catalog_path
        )
        second_import = cf.domains.audio_recommendations.import_audio_memory(
            catalog_path
        )
        assert first_import["tracksImported"] == 1
        assert second_import["trendSnapshotsImported"] == 1
        assert cf.conn.execute("SELECT COUNT(*) FROM audio_catalog").fetchone()[0] == 1
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM audio_trend_snapshots").fetchone()[0]
            == 1
        )

        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=True
        )
        item = rec["items"][0]
        assert (
            item["audioRecommendations"]["recommendations"][0]["audioTitle"]
            == "Mirror Trend"
        )
        assert item["audioDecision"]["primaryAudio"]["audioTitle"] == "Mirror Trend"
        assert item["audioDecision"]["decisionConfidence"] in {"usable", "strong"}
        assert item["audioRecommendations"]["recommendations"][0][
            "audioMemoryGraphId"
        ].startswith("cg_audio_memory_")
        assert (
            item["audioRecommendations"]["recommendations"][0]["scoreComponents"][
                "creatorFit"
            ]
            == 94
        )
        assert item["audioRecommendations"]["recommendations"][0][
            "recommendationConfidence"
        ] in {"usable", "strong"}
        memory = cf.domains.audio_recommendations.audio_memory(
            platform="instagram", account="ig_1", limit=5
        )
        assert memory["audioTrust"]["averageScore"] is not None
        assert memory["items"][0]["audioMemoryScore"] > 80

        selected = cf.domains.audio_operations.select_audio_for_recommendation(
            item["recommendationId"], "aud_mem", operator="tester"
        )
        assert selected["selection"]["status"] == "selected"
        updated = cf.domains.rendered_asset("asset_1")
        caption_generation = json.loads(updated["caption_generation_json"])
        assert caption_generation["audioIntent"]["status"] == "selected"
        assert (
            caption_generation["audioIntent"]["operator_selection"]["catalog_audio_id"]
            == "aud_mem"
        )
        edges = {
            row["relation_type"]
            for row in cf.conn.execute(
                "SELECT relation_type FROM content_graph_edges"
            ).fetchall()
        }
        assert "recommendation_item_to_audio_recommendation" in edges
        assert "audio_recommendation_to_audio_selection" in edges
        assert "audio_memory_to_audio_selection" in edges
        assert source["id"]
    finally:
        cf.close()


def test_audio_recommendations_include_contentforge_audio_fit_when_available(
    tmp_path: Path,
):
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
    catalog_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        cf.domains.audio_recommendations.import_audio_catalog(catalog_path)
        result = cf.domains.audio_recommendations.recommend_audio(
            platform="instagram",
            content_tags=["fit_check"],
            visual_signal={"energy": "high"},
            limit=2,
        )
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


def test_pipeline_audio_smoke_helpers_build_recommended_intent(tmp_path: Path):
    csv_path = write_smoke_audio_csv(tmp_path / "audio.csv")
    snapshot_path = write_smoke_audio_snapshot_csv(tmp_path / "audio_snapshot.csv")
    catalog_path = tmp_path / "audio_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        cf.domains.audio_recommendations.import_audio_catalog(catalog_path)
        create_smoke_campaign_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset(
            "asset_smoke", decision="approved"
        )
        add_smoke_audit_report(cf)
        payload = build_draft_payloads(
            cf, campaign_slug="audio_smoke", user_id="smoke_user"
        )
        intent = assert_smoke_draft_audio_intent(payload)
        performance = sync_smoke_performance(
            cf, draft_payload=payload, user_id="smoke_user"
        )
        contentforge = assert_contentforge_contract_response(
            CONTENTFORGE_SMOKE_RESPONSE
        )

        assert csv_path.read_text(encoding="utf-8") == SMOKE_CSV
        assert snapshot_path.read_text(encoding="utf-8") == SMOKE_SNAPSHOT_CSV
        assert intent["status"] == "needs_operator_selection"
        assert intent["recommendations"][0]["audio_title"] == "Runway Pop"
        assert contentforge["readinessSummary"]["uploadReady"] is True
        validate_performance_sync(performance)
        assert performance["inserted"] == 1
        assert (
            performance["summary"]["leaderboards"]["audioRecommendations"][0]["audio"][
                "audioTitle"
            ]
            == "Runway Pop"
        )
    finally:
        cf.close()


def test_recommend_next_batch_persists_idempotent_graph_backed_run(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
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
        caption_hash = threadsdash_client_adapter._text_hash("caption")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, raw_json, created_at,
             published_at, metrics_eligible, history_source, lineage_v2_valid)
            VALUES
            ('perf_good', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_1', 'instagram',
             'published', 'ig_1', ?, 12000, 900, 80, 100, 140, 10000, '{}', ?,
             '2026-01-02T00:00:00+00:00', 1, 'metric_history', 1)
            """,
            (
                campaign["id"],
                source["id"],
                source["content_hash"],
                caption_hash,
                now,
                now,
            ),
        )
        cf.conn.commit()

        first = cf.domains.recommendations.recommend_next_batch(
            "may", count=5, account="ig_1", persist=True
        )
        second = cf.domains.recommendations.recommend_next_batch(
            "may", count=5, account="ig_1", persist=True
        )

        validate_recommendation_next_batch(first)
        assert first["schema"] == "campaign_factory.recommendations.next_batch.v1"
        assert first["runId"] == second["runId"]
        assert first["items"][0]["status"] == "proposed"
        assert first["items"][0]["dataQuality"]["sampleSize"] > 0
        assert first["items"][0]["recommendationGraphId"].startswith(
            "cg_recommendation_item_"
        )
        assert first["items"][0]["campaignGraphId"].startswith("cg_campaign_")
        assert first["items"][0]["referencePatternGraphId"].startswith(
            "cg_reference_pattern_"
        )
        assert first["items"][0]["sourceAssetGraphId"].startswith("cg_source_asset_")
        assert first["items"][0]["renderedAssetGraphId"].startswith(
            "cg_rendered_asset_"
        )
        assert first["items"][0]["scoreBreakdown"]["performance"] > 50
        learning = first["items"][0]["decisionEvidence"]["learning"]
        assert (
            learning["performanceScore"]
            == first["items"][0]["scoreBreakdown"]["performance"]
        )
        assert learning["latestPerformanceSnapshotId"] == "perf_good"
        assert learning["dataQuality"]["sampleSize"] > 0
        assert learning["recommendationTrust"]["status"] == "unmeasured"
        assert first["items"][0]["confidence"] == "low"
        assert first["items"][0]["advisory"] is True
        assert "reference_pattern_evidence_advisory" in first["items"][0]["risks"]
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM recommendation_runs").fetchone()[0]
            == 1
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM recommendation_items").fetchone()[0]
            == 1
        )
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute(
                "SELECT relation_type FROM content_graph_edges"
            ).fetchall()
        }
        assert "performance_snapshot_to_recommendation_input" in edge_types
        assert "recommendation_input_to_recommendation_run" in edge_types
        assert "recommendation_run_to_recommendation_item" in edge_types
        assert "rendered_asset_to_recommendation_item" in edge_types
        stored = cf.domains.recommendations.recommendation_runs("may")
        assert (
            stored["runs"][0]["items"][0]["recommendationId"]
            == first["items"][0]["recommendationId"]
        )
    finally:
        cf.close()


def test_recommend_next_batch_explains_readiness_for_blocked_asset(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=False
        )

        validate_recommendation_next_batch(rec)
        item = rec["items"][0]
        readiness = item["readinessEvidence"]
        assert readiness["state"] == "blocked"
        assert readiness["reviewState"] == "draft"
        assert readiness["auditStatus"] == "pending"
        assert readiness["targetAccount"] == "ig_1"
        assert readiness["operatorScore"] < 50
        assert "missing_audit" in readiness["blockingReasons"]
        assert "review_state:draft" in readiness["blockingReasons"]
        assert "missing_audit" in item["risks"]
        assert item["evidence"]["readiness"] == readiness
        decision_readiness = item["decisionEvidence"]["readiness"]
        assert decision_readiness["verdict"] == "blocked"
        assert decision_readiness["nextAction"] == "resolve_readiness_blockers"
        assert decision_readiness["reviewState"] == "draft"
        assert decision_readiness["auditStatus"] == "pending"
        assert decision_readiness["contentSurface"] == "reel"
        assert decision_readiness["latestAuditVerdict"] is None
        assert item["decisionEvidence"]["whyNow"]["status"] == "blocked"
        assert (
            item["decisionEvidence"]["whyNow"]["nextAction"]
            == decision_readiness["nextAction"]
        )
        assert item["decisionEvidence"]["whyNow"]["reasons"] == item["reasons"]
        assert item["decisionEvidence"]["whyNow"]["risks"] == item["risks"]
        checklist = item["decisionEvidence"]["proofChecklist"]
        assert checklist["readiness"]["status"] == "blocked"
        assert checklist["readiness"]["nextAction"] == decision_readiness["nextAction"]
        assert checklist["readiness"]["blockingCount"] >= 1
        assert (
            checklist["quality"]["status"]
            == item["decisionEvidence"]["quality"]["status"]
        )
        assert (
            checklist["audio"]["status"] == item["decisionEvidence"]["audio"]["status"]
        )
    finally:
        cf.close()


def test_recommend_next_batch_surfaces_publishability_failures_as_risks(tmp_path: Path):
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
        cf.conn.commit()

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=False
        )
        validate_recommendation_next_batch(rec)
        item = rec["items"][0]

        assert (
            "missing_instagram_post_caption"
            in item["readinessEvidence"]["publishabilityFailureReasons"]
        )
        assert "publishability:missing_instagram_post_caption" in item["risks"]
        assert (
            "publishability:missing_instagram_post_caption"
            in item["decisionEvidence"]["readiness"]["blockingReasons"]
        )
        assert (
            "missing_instagram_post_caption"
            in item["decisionEvidence"]["readiness"]["publishabilityFailureReasons"]
        )
        caption = item["decisionEvidence"]["caption"]
        assert caption["status"] == "blocked"
        assert caption["blockingReasons"] == [
            "instagram_post_caption_quality_failed",
            "missing_instagram_post_caption",
        ]
        quality = item["decisionEvidence"]["quality"]
        assert quality["status"] == "blocked"
        assert quality["blockingCategories"] == ["caption"]
        assert "missing_instagram_post_caption" in quality["failureReasons"]
        variation_safety = item["decisionEvidence"]["variation"]["safety"]
        assert variation_safety["status"] == "clear"
        assert variation_safety["blockingReasons"] == []
        assert variation_safety["ssimRole"] == "diagnostic_only"
        assert item["score"] <= 45
    finally:
        cf.close()


def test_recommend_next_batch_surfaces_variation_safety_blockers(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET content_hash = '' WHERE id = 'asset_1'"
        )
        cf.conn.commit()

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=False
        )
        validate_recommendation_next_batch(rec)
        item = rec["items"][0]

        assert (
            "missing_content_fingerprint"
            in item["readinessEvidence"]["publishabilityFailureReasons"]
        )
        variation_safety = item["decisionEvidence"]["variation"]["safety"]
        assert variation_safety["status"] == "blocked"
        assert variation_safety["blockingReasons"] == ["missing_content_fingerprint"]
        assert variation_safety["authoritativeGate"] == "pdq_sscd_for_fanout"
        assert variation_safety["ssimRole"] == "diagnostic_only"
    finally:
        cf.close()


def test_recommend_next_batch_surfaces_attached_native_audio_selection(tmp_path: Path):
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
                        "instagram_post_caption": "new post",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": True,
                            "status": "attached",
                            "operator_selection": {
                                "audio_id": "ig_audio_123",
                                "audio_title": "Proof track",
                                "audio_artist": "DJ Proof",
                                "selection_source": "manual",
                                "selected_at": "2026-06-06T04:31:02+00:00",
                                "attached_at": "2026-06-06T04:31:02+00:00",
                            },
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=False
        )
        validate_recommendation_next_batch(rec)
        item = rec["items"][0]

        assert item["audioSelectionStatus"] == "attached"
        assert item["selectedAudio"]["audioId"] == "ig_audio_123"
        assert item["selectedAudio"]["audioTitle"] == "Proof track"
        assert item["selectedAudio"]["audioArtist"] == "DJ Proof"
        assert (
            item["decisionEvidence"]["audio"]["selectedAudio"] == item["selectedAudio"]
        )
        assert (
            item["decisionEvidence"]["audio"]["primaryAudio"] == item["selectedAudio"]
        )
        assert item["decisionEvidence"]["audio"]["status"] == "attached"
    finally:
        cf.close()


def test_reference_only_recommendation_explains_what_to_make_next(tmp_path: Path):
    bank_path = tmp_path / "reference_bank.json"
    bank_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.campaign_reference_bank.v1",
                "clusters": [
                    {
                        "clusterKey": "mirror_curiosity",
                        "label": "Mirror Curiosity",
                        "rank": 1,
                        "visualFormat": "mirror",
                        "hookType": "curiosity",
                        "captionArchetype": "short_direct",
                        "captionFormulas": [{"formula": "short direct caption"}],
                        "suggestedVariantRecipes": ["v01_original"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    audio_path = tmp_path / "audio_memory.json"
    audio_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.audio_catalog_export.v1",
                "items": [
                    {
                        "id": "aud_reference_only",
                        "title": "Reference Only Trend",
                        "artistName": "DJ Ref",
                        "platform": "instagram",
                        "nativeAudioId": "ig_ref",
                        "moodTags": ["mirror"],
                        "accountFit": ["ig_1"],
                        "trendStatus": "rising",
                        "trendScore": 88,
                        "velocityScore": 80,
                        "creatorFitScore": 90,
                        "usageCount": 9000,
                        "resolved": True,
                        "sourceConfidence": 0.9,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        cf.domains.reference.import_reference_bank(bank_path)
        cf.domains.audio_recommendations.import_audio_memory(audio_path)

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=False
        )
        validate_recommendation_next_batch(rec)
        item = rec["items"][0]

        assert item["renderedAssetId"] is None
        assert "no_rendered_assets_available" in rec["warnings"]
        assert (
            item["audioRecommendations"]["recommendations"][0]["audioTitle"]
            == "Reference Only Trend"
        )
        assert item["audioSelectionStatus"] == "recommended"
        assert item["decisionEvidence"]["targetAccount"] == "ig_1"
        assert (
            item["decisionEvidence"]["audio"]["primaryAudio"]["audioTitle"]
            == "Reference Only Trend"
        )
        assert (
            item["decisionEvidence"]["caption"]["guidance"] == item["captionGuidance"]
        )
        assert item["decisionEvidence"]["variation"]["preset"] == "ig_subtle"
        assert item["decisionEvidence"]["learning"]["dataQuality"]["sampleSize"] == 0
        assert (
            item["decisionEvidence"]["learning"]["latestPerformanceSnapshotId"] is None
        )
        assert item["decisionEvidence"]["readiness"]["blockingReasons"] == [
            "missing_rendered_assets"
        ]
        assert item["decisionEvidence"]["readiness"]["verdict"] == "blocked"
        assert (
            item["decisionEvidence"]["readiness"]["nextAction"]
            == "make_or_register_rendered_asset"
        )
        assert item["decisionEvidence"]["whyNow"] == {
            "status": "blocked",
            "nextAction": "make_or_register_rendered_asset",
            "reasons": [
                "active reference pattern is available for the next generation batch"
            ],
            "risks": item["risks"],
        }
        checklist = item["decisionEvidence"]["proofChecklist"]
        assert checklist["learning"]["status"] == "low"
        assert checklist["learning"]["sampleSize"] == 0
        assert checklist["readiness"]["status"] == "blocked"
        assert checklist["readiness"]["nextAction"] == "make_or_register_rendered_asset"
        assert checklist["audio"]["hasPrimaryAudio"] is True
        assert item["evidence"]["decision"] == item["decisionEvidence"]
    finally:
        cf.close()


def test_recommendation_accuracy_report_idempotent_and_segments(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        now = "2026-05-30T00:00:00+00:00"
        caption_hash = threadsdash_client_adapter._text_hash("caption")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, raw_json, created_at,
             published_at, metrics_eligible, history_source, lineage_v2_valid)
            VALUES
            ('perf_acc_rec', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_rec', 'instagram',
             'published', 'ig_1', ?, 12000, 900, 80, 100, 140, 10000, '{}', ?,
             '2026-05-30T00:00:00+00:00', 1, 'metric_history', 1),
            ('perf_acc_base_1', ?, 'manual_1', ?, 'hash_b1', ?, ?, 'v01_original', 'post_b1', 'instagram',
             'published', 'ig_1', ?, 100, 5, 0, 0, 0, 100, '{}', ?,
             '2026-05-30T00:00:00+00:00', 1, 'metric_history', 1),
            ('perf_acc_base_2', ?, 'manual_2', ?, 'hash_b2', ?, ?, 'v01_original', 'post_b2', 'instagram',
             'published', 'ig_1', ?, 120, 6, 0, 0, 0, 120, '{}', ?,
             '2026-05-30T00:00:00+00:00', 1, 'metric_history', 1),
            ('perf_acc_base_3', ?, 'manual_3', ?, 'hash_b3', ?, ?, 'v01_original', 'post_b3', 'instagram',
             'published', 'ig_1', ?, 90, 4, 0, 0, 0, 90, '{}', ?,
             '2026-05-30T00:00:00+00:00', 1, 'metric_history', 1)
            """,
            (
                campaign["id"],
                source["id"],
                source["content_hash"],
                caption_hash,
                now,
                now,
                campaign["id"],
                source["id"],
                source["content_hash"],
                caption_hash,
                now,
                now,
                campaign["id"],
                source["id"],
                source["content_hash"],
                caption_hash,
                now,
                now,
                campaign["id"],
                source["id"],
                source["content_hash"],
                caption_hash,
                now,
                now,
            ),
        )
        cf.conn.commit()
        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=True
        )
        item_id = rec["items"][0]["recommendationId"]
        cf.domains.recommendations.accept_recommendation_item(item_id)
        cf.domains.recommendations.link_recommendation_item(
            item_id, rendered_asset_id="asset_1", performance_snapshot_id="perf_acc_rec"
        )
        cf.domains.recommendations.measure_recommendation_item(item_id)
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
                cf.domains.graph.ensure_graph_node(
                    "recommendation_item",
                    local_table="recommendation_items",
                    local_id=measured_id,
                    payload=measured_payload,
                ),
                json.dumps({"level": "low"}),
                json.dumps(
                    {
                        "status": "measured",
                        "outcomeScore": 50,
                        "baselineScore": 50,
                        "measuredAt": now,
                    }
                ),
                json.dumps(measured_payload),
                now,
                now,
            ),
        )
        cf.conn.commit()

        first = cf.domains.recommendation_accuracy_repo.recommendation_accuracy(
            "may", account="ig_1", window_days=365
        )
        second = (
            cf.domains.recommendation_accuracy_repo.rebuild_recommendation_accuracy(
                "may", account="ig_1", window_days=365
            )
        )
        validate_recommendation_accuracy_report(first)
        assert second["schema"] == "campaign_factory.recommendation_accuracy_report.v1"
        assert first["overall"]["measuredCount"] == 2
        assert first["overall"]["provedCount"] == 1
        assert first["overall"]["inconclusiveCount"] == 1
        assert first["overall"]["accuracyDenominator"] == 1
        assert first["overall"]["accuracyRate"] == 1.0
        assert first["trustConfidence"] == "insufficient"
        assert first["calibration"][0]["key"] in {"strong", "weak"}
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM recommendation_accuracy_observations"
            ).fetchone()[0]
            == 2
        )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM recommendation_accuracy_reports"
            ).fetchone()[0]
            == 1
        )
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute(
                "SELECT relation_type FROM content_graph_edges"
            ).fetchall()
        }
        assert (
            "recommendation_item_to_recommendation_accuracy_observation" in edge_types
        )
        assert "recommendation_accuracy_observation_to_report" in edge_types
        summary = cf.domains.exceptions.trust_summary("may")
        assert summary["recommendations"]["proof"]["measuredCount"] == 2
    finally:
        cf.close()


def test_recommend_next_batch_downgrades_when_recommendation_trust_is_low(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.campaign_by_slug("may")
        seeded = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=True
        )
        now = "2026-05-31T00:00:00+00:00"
        rows = []
        for idx in range(3):
            item_id = f"recitem_disproved_{idx}"
            payload = {
                "recommendationId": item_id,
                "status": "disproved",
                "confidence": "high",
                "dataQuality": {"level": "high"},
                "outcome": {"outcomeScore": 30, "baselineScore": 75, "measuredAt": now},
            }
            rows.append(
                (
                    item_id,
                    seeded["runId"],
                    idx + 2,
                    source["id"],
                    cf.domains.graph.ensure_graph_node(
                        "recommendation_item",
                        local_table="recommendation_items",
                        local_id=item_id,
                        payload=payload,
                    ),
                    json.dumps({"level": "high"}),
                    json.dumps(payload["outcome"]),
                    json.dumps(payload),
                    now,
                    now,
                )
            )
        cf.conn.executemany(
            """
            INSERT INTO recommendation_items (
              id, run_id, rank, target_account, source_asset_id, rendered_asset_id,
              recommendation_graph_id, status, score, confidence, data_quality_json,
              outcome_json, baseline_json, measurement_version, output_json, measured_at,
              created_at
            )
            VALUES (?, ?, ?, 'ig_1', ?, 'asset_1', ?, 'disproved', 90, 'high', ?, ?,
              '{}', 'recommendation_measurement.v1', ?, ?, ?)
            """,
            rows,
        )
        cf.conn.commit()

        report = cf.domains.recommendation_accuracy_repo.recommendation_accuracy(
            "may", account="ig_1", window_days=365
        )
        assert report["recommendationTrustScore"] < 50

        next_batch = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=False
        )
        item = next_batch["items"][0]

        assert item["confidence"] == "low"
        assert "low_recommendation_trust" in item["risks"]
        assert (
            item["evidence"]["recommendationTrust"]["score"]
            == report["recommendationTrustScore"]
        )
        assert (
            item["scoreBreakdown"]["recommendationTrust"]
            == report["recommendationTrustScore"]
        )
        learning = item["decisionEvidence"]["learning"]
        assert learning["recommendationTrust"]["status"] == "low"
        assert (
            learning["recommendationTrust"]["score"]
            == report["recommendationTrustScore"]
        )
        assert learning["trustRisk"] == "low_recommendation_trust"
        assert learning["dataQuality"]["level"] in {"low", "medium", "high"}
    finally:
        cf.close()


def test_exception_queue_idempotent_resolve_snooze_reopen(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=True
        )
        item_id = rec["items"][0]["recommendationId"]
        graph_id = rec["items"][0]["recommendationGraphId"]

        first = cf.domains.exceptions.create_exception(
            reason_code="missing_account_assignment",
            severity="medium",
            campaign_id=campaign["id"],
            entity_graph_id=graph_id,
            recommendation_item_id=item_id,
            payload={"source": "test"},
        )
        second = cf.domains.exceptions.create_exception(
            reason_code="missing_account_assignment",
            severity="high",
            campaign_id=campaign["id"],
            entity_graph_id=graph_id,
            recommendation_item_id=item_id,
            payload={"source": "test_rerun"},
        )
        assert first["id"] == second["id"]
        open_rows = cf.domains.exceptions.exceptions("may", status="open")["exceptions"]
        assert len(open_rows) == 1
        assert open_rows[0]["severity"] == "high"

        snoozed = cf.domains.exceptions.snooze_exception(
            first["id"], until="2026-01-03T00:00:00+00:00", reason="wait", operator="op"
        )
        assert snoozed["status"] == "snoozed"
        reopened = cf.domains.exceptions.reopen_exception(
            first["id"], reason="ready", operator="op"
        )
        assert reopened["status"] == "open"
        resolved = cf.domains.exceptions.resolve_exception(
            first["id"], resolution="fixed", operator="op"
        )
        assert resolved["status"] == "resolved"

        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute(
                "SELECT relation_type FROM content_graph_edges"
            ).fetchall()
        }
        assert "entity_to_trust_exception" in edge_types
        assert "recommendation_item_to_trust_exception" in edge_types
    finally:
        cf.close()


def test_execute_accepted_recommendation_links_existing_asset_without_publishing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=True
        )
        item_id = rec["items"][0]["recommendationId"]
        cf.domains.recommendations.accept_recommendation_item(
            item_id, operator="operator_1"
        )

        executed = cf.domains.recommendations.execute_accepted_recommendation(
            item_id, run_audit=False
        )
        assert executed["schema"] == "campaign_factory.recommendation_execution.v1"
        assert executed["recommendation"]["status"] == "executed"
        assert executed["recommendation"]["executionStatus"] in {"completed", "blocked"}
        assert executed["recommendation"]["renderedAssetId"] == "asset_1"
        assert (
            cf.domains.events.pipeline_job(executed["pipelineJobId"])["status"]
            == "succeeded"
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM threadsdash_exports").fetchone()[0]
            == 0
        )
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute(
                "SELECT relation_type FROM content_graph_edges"
            ).fetchall()
        }
        assert "recommendation_item_to_rendered_asset" in edge_types
    finally:
        cf.close()


def test_autonomy_policy_blocks_level_one_execution(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=True
        )
        item_id = rec["items"][0]["recommendationId"]
        cf.domains.recommendations.accept_recommendation_item(item_id)

        policy = cf.domains.autonomy.set_autonomy_level("level_1")
        assert policy["level"] == "level_1"
        with pytest.raises(ValueError, match="auto execute blocked by autonomy level"):
            cf.domains.recommendations.execute_accepted_recommendation(item_id)
        exceptions = cf.domains.exceptions.exceptions("may", status="open")[
            "exceptions"
        ]
        assert any(
            item["reasonCode"] == "autonomy_level_blocks_execution"
            for item in exceptions
        )
        summary = cf.domains.exceptions.trust_summary("may")
        assert summary["schema"] == "campaign_factory.trust_summary.v1"
        assert summary["autonomyLevel"] == "level_1"
        assert summary["exceptions"]["openCount"] >= 1
        assert summary["recommendations"]["acceptedWaitingExecution"] == 1
        assert summary["recommendedAction"] in {
            "execute_accepted_recommendations",
            "review_high_severity_exceptions",
        }

        cf.domains.autonomy.set_autonomy_level("level_2")
        executed = cf.domains.recommendations.execute_accepted_recommendation(
            item_id, run_audit=False
        )
        assert executed["publishesAutomatically"] is False
        assert executed["recommendation"]["status"] == "executed"
    finally:
        cf.close()


def test_winner_registry_remembers_why_winners_won_without_writing(tmp_path: Path):
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
        cf.conn.execute(
            "UPDATE concepts SET creator = 'Stacey', metadata_json = ? WHERE id = ?",
            (json.dumps({"conceptName": "mirror selfie"}), parent["conceptId"]),
        )
        campaign_id = cf.domains.rendered_asset("asset_1")["campaign_id"]
        source_asset_id = cf.domains.rendered_asset("asset_1")["source_asset_id"]
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
             caption_angle, post_id, platform, status, instagram_account_id, published_at,
             snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible,
             concept_id, parent_reel_id, variant_family_id, variant_id, audio_id, creator_mix,
             created_at, raw_json, history_source, lineage_v2_valid)
            VALUES ('perf_memory_winner', ?, 'asset_1', ?, 'hash_1', 'caption_hash_1',
             'tease', 'post_memory_winner', 'instagram', 'published', 'ig_1',
             '2026-06-06T18:12:00+00:00', '2026-06-06T20:00:00+00:00',
             12000, 700, 40, 80, 100, 11000, 1, ?, ?, 'vfam_memory', 'variant_memory',
             'audio_12', 'Stacey', '2026-06-06T20:00:00+00:00',
             '{"followers": 12, "onlyfansRevenue": 999999}', 'metric_history', 1)
            """,
            (campaign_id, source_asset_id, parent["conceptId"], parent["parentReelId"]),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.domains.creative_knowledge.winner_registry(
            creator="Stacey", min_views=1000
        )

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


def test_winner_patterns_rolls_up_top_concepts_audio_captions_and_windows(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        campaign_id = cf.domains.rendered_asset("asset_1")["campaign_id"]
        source_asset_id = cf.domains.rendered_asset("asset_1")["source_asset_id"]
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
            (
                "perf_mirror_1",
                "post_mirror_1",
                "concept_mirror",
                "parent_mirror",
                "audio_12",
                "tease",
                "2026-06-06T18:05:00+00:00",
                14000,
                13000,
            ),
            (
                "perf_mirror_2",
                "post_mirror_2",
                "concept_mirror",
                "parent_mirror",
                "audio_12",
                "challenge",
                "2026-06-07T21:20:00+00:00",
                9000,
                8000,
            ),
            (
                "perf_gym_1",
                "post_gym_1",
                "concept_gym",
                "parent_gym",
                "audio_44",
                "challenge",
                "2026-06-08T18:40:00+00:00",
                7000,
                6500,
            ),
            (
                "perf_low",
                "post_low",
                "concept_gym",
                "parent_gym",
                "audio_44",
                "challenge",
                "2026-06-08T10:00:00+00:00",
                100,
                90,
            ),
        ]
        for (
            snapshot_id,
            post_id,
            concept_id,
            parent_reel_id,
            audio_id,
            caption_angle,
            published_at,
            views,
            reach,
        ) in snapshots:
            cf.conn.execute(
                """
                INSERT INTO performance_snapshots
                (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, caption_hash,
                 caption_angle, post_id, platform, status, instagram_account_id, published_at,
                 snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible,
                 concept_id, parent_reel_id, audio_id, creator_mix, created_at, raw_json, history_source, lineage_v2_valid)
                VALUES (?, ?, 'asset_1', ?, ?, ?, ?, ?, 'instagram', 'published', 'ig_1',
                 ?, '2026-06-09T00:00:00+00:00', ?, 100, 10, 20, 30, ?, 1,
                 ?, ?, ?, 'Stacey', '2026-06-09T00:00:00+00:00', '{}', 'metric_history', 1)
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

        report = cf.domains.creative_knowledge.winner_knowledge_base(
            creator="Stacey", min_views=1000
        )

        assert report["schema"] == "campaign_factory.winner_knowledge_base.v1"
        assert report["wouldWrite"] is False
        assert cf.conn.total_changes == before
        assert [
            item["conceptName"] for item in report["winnerPatterns"]["topConcepts"][:2]
        ] == ["mirror selfie", "gym mirror"]
        assert report["winnerPatterns"]["topAudioFamilies"][0]["audioId"] == "audio_12"
        assert (
            report["winnerPatterns"]["topCaptionAngles"][0]["captionAngle"]
            == "challenge"
        )
        assert (
            report["winnerPatterns"]["topPostingWindows"][0]["postingWindow"] == "6pm"
        )
        assert report["conceptRegistry"][0]["conceptName"] == "mirror selfie"
        assert report["winnerRegistry"]["summary"]["winnerCount"] == 3
    finally:
        cf.close()


def test_winner_expansion_plan_is_read_only_and_covers_named_operation_families(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        cf.domains.variant_lineage.register_parent_reel("asset_1", operator="tester")
        before = cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0]

        plan = cf.domains.winner_expansion.winner_expansion_plan(
            creator="Stacey",
            parent_asset_id="asset_1",
            target_variants=10,
            preset="caption_safe_v2",
        )

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
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0]
            == before
        )
    finally:
        cf.close()


def test_winner_expansion_plan_rejects_low_quality_and_duplicate_siblings(
    tmp_path: Path,
):
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
        add_variant_fixture(
            cf,
            tmp_path,
            variant_asset_id="asset_variant_low",
            variant_index=1,
            quality_score=89,
        )
        add_variant_fixture(
            cf,
            tmp_path,
            variant_asset_id="asset_variant_good",
            variant_index=2,
            content_hash="hash_unique_good",
        )
        add_variant_fixture(
            cf,
            tmp_path,
            variant_asset_id="asset_variant_duplicate_family",
            variant_index=3,
            content_hash="hash_unique_duplicate_family",
        )

        plan = cf.domains.winner_expansion.winner_expansion_plan(
            creator="Stacey",
            parent_asset_id="asset_1",
            target_variants=5,
            preset="caption_safe_v2",
        )

        assert plan["variantFamilyId"] == "vfam_winner"
        assert plan["parentReelId"] == parent["parentReelId"]
        assert plan["existingVariants"] == 1
        assert plan["recommendedNewVariants"] == 4
        assert "cover_frame" not in plan["operationFamilies"][:4]
        assert plan["rejectedExistingVariants"]["lowQuality"] == 1
        assert plan["rejectedExistingVariants"]["duplicateSiblings"] == 1
    finally:
        cf.close()


def test_learning_lineage_repairs_missing_reference_from_canonical_local_asset(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        meta = threadsdash_campaign_factory_metadata(source)
        del meta["generated_asset_lineage"]["source"]["referenceId"]
        row = {
            "id": "post_repair_1",
            "metadata": {"campaign_factory": meta},
        }

        repaired_row, repaired_meta, report = (
            threadsdash_metrics_adapter._repair_learning_lineage_from_local_asset(
                cf, row=row, meta=meta
            )
        )

        assert report == {
            "repairedFields": ["source.referenceId"],
            "blockingReasons": [],
        }
        assert (
            repaired_meta["generated_asset_lineage"]["source"]["referenceId"]
            == "reference_test_001"
        )
        assert (
            repaired_row["metadata"]["campaign_factory"]["generated_asset_lineage"][
                "source"
            ]["referenceId"]
            == "reference_test_001"
        )
    finally:
        cf.close()


def test_learning_lineage_repairs_missing_source_lineage_artifact_path(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        lineage_path = tmp_path / "source.direct_reference_lineage.json"
        lineage_path.write_text(
            json.dumps(
                {
                    "features": {
                        "creator": "stacey",
                        "scene": "bedroom",
                    }
                }
            ),
            encoding="utf-8",
        )
        caption_generation = json.loads(
            cf.conn.execute(
                "SELECT caption_generation_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        caption_generation["generatedAssetLineage"] = {
            "source": {"sourceLineagePath": str(lineage_path)}
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps(caption_generation, sort_keys=True),),
        )
        cf.conn.commit()
        meta = threadsdash_campaign_factory_metadata(source)
        meta["generated_asset_lineage"]["source"]["sourceLineagePath"] = None

        _, repaired_meta, report = (
            threadsdash_metrics_adapter._repair_learning_lineage_from_local_asset(
                cf,
                row={"id": "post_repair_lineage_path", "metadata": {}},
                meta=meta,
            )
        )

        assert report["blockingReasons"] == []
        assert report["repairedFields"] == [
            "features",
            "source.sourceLineagePath",
        ]
        assert repaired_meta["generated_asset_lineage"]["source"][
            "sourceLineagePath"
        ] == str(lineage_path)
        assert repaired_meta["generated_asset_lineage"]["features"] == {
            "creator": "stacey",
            "scene": "bedroom",
        }
    finally:
        cf.close()


def test_learning_lineage_does_not_read_untrusted_incoming_artifact_path(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        untrusted_path = tmp_path / "incoming.direct_reference_lineage.json"
        untrusted_path.write_text(
            json.dumps({"features": {"creator": "attacker", "scene": "spoofed"}}),
            encoding="utf-8",
        )
        meta = threadsdash_campaign_factory_metadata(source)
        meta["generated_asset_lineage"]["source"]["sourceLineagePath"] = str(
            untrusted_path
        )

        _, repaired_meta, report = (
            threadsdash_metrics_adapter._repair_learning_lineage_from_local_asset(
                cf,
                row={"id": "post_untrusted_lineage_path", "metadata": {}},
                meta=meta,
            )
        )

        assert "features" not in report["repairedFields"]
        assert "features" not in repaired_meta["generated_asset_lineage"]
    finally:
        cf.close()


def test_learning_lineage_refuses_conflicting_reference_identity(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        meta = threadsdash_campaign_factory_metadata(source)
        meta["generated_asset_lineage"]["source"]["referenceId"] = "wrong_reference"

        _, repaired_meta, report = (
            threadsdash_metrics_adapter._repair_learning_lineage_from_local_asset(
                cf, row={"id": "post_conflict", "metadata": {}}, meta=meta
            )
        )

        assert report["repairedFields"] == []
        assert report["blockingReasons"] == ["referenceId_conflict"]
        assert repaired_meta["learning_lineage_blocking_reasons"] == [
            "referenceId_conflict"
        ]
    finally:
        cf.close()


def test_recommended_inventory_request_plan_reports_no_recommendations(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        plan = (
            cf.domains.recommended_inventory_request.recommended_inventory_request_plan(
                creator="Stacey",
                target_count=5,
                daily_plan={
                    "schema": "creator_os.daily_plan.v1",
                    "creators": [{"creator": "Stacey", "recommendedInventory": []}],
                    "wouldWrite": False,
                },
            )
        )

        assert cf.conn.total_changes == before
        assert plan["requestBatches"] == []
        assert plan["blockingReason"] == "no_recommended_inventory_available"
        assert (
            plan["nextSafeAction"]
            == "wait_for_more_metrics_or_create_operator_selected_inventory"
        )
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_decision_ledger_preview_simulates_manager_decisions_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_story_need",
            platform="instagram",
            external_id="ig_story_need",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf,
            account_id=account["id"],
            surface="story",
            cadence="daily",
            max_per_day=1,
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        preview = cf.domains.decision_ledger.decision_ledger_preview(
            creator="Stacey",
            date="2026-06-06",
            threadsdash_report=_manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_story_need",
                        "username": "stacey_story_need",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": True,
                    }
                ]
            ),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 0,
                "items": [],
            },
            generated_at="2026-06-06T12:00:00+00:00",
        )

        assert cf.conn.total_changes == before
        assert preview["schema"] == "creator_os.decision_ledger_preview.v1"
        assert preview["wouldWrite"] is False
        by_type = {entry["decisionType"]: entry for entry in preview["decisions"]}
        assert (
            by_type["inventory_shortfall"]["reason"]
            == "insufficient_schedule_safe_drafts"
        )
        assert by_type["inventory_shortfall"]["inventoryShortfall"] == 1
        assert by_type["account_needs_story"]["accountId"] == account["id"]
        assert (
            by_type["account_needs_story"]["sourceSystem"]
            == "account_content_requirements"
        )
        assert by_type["story_intent_recommended"]["storyIntent"] in {
            "snapchat_promo",
            "lifestyle",
            "reel_teaser",
            "casual_selfie",
        }
        assert all(
            entry["timestamp"] == "2026-06-06T12:00:00+00:00"
            for entry in preview["decisions"]
        )
        assert all(entry["wouldWrite"] is False for entry in preview["decisions"])
        assert table_count(cf, "manager_decisions") == 0
    finally:
        cf.close()


def test_decision_ledger_preview_covers_winners_parent_selection_and_variant_rejections(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        preview = cf.domains.decision_ledger.decision_ledger_preview(
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
                "rejectedExistingVariants": {
                    "lowQuality": 1,
                    "duplicateSiblings": 2,
                    "notUploadReady": 1,
                },
                "wouldWrite": False,
            },
            generated_at="2026-06-06T12:00:00+00:00",
        )

        assert cf.conn.total_changes == before
        by_type = {entry["decisionType"]: entry for entry in preview["decisions"]}
        assert by_type["winner_selected"]["winnerReason"] == "high_views"
        assert by_type["parent_selected"]["parentAssetId"] == "asset_parent_1"
        rejection_reasons = {
            entry["reason"]
            for entry in preview["decisions"]
            if entry["decisionType"] == "variant_rejected"
        }
        assert {
            "low_quality",
            "duplicate_sibling",
            "not_upload_ready",
        } <= rejection_reasons
        assert preview["wouldWrite"] is False
    finally:
        cf.close()


def test_learning_engine_recommendations_include_explainability_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("stacey_learning_engine", "stacey")
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

        analysis = cf.domains.creative_knowledge.creative_performance_analysis(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        next_content = cf.domains.creative_knowledge.next_content_recommendations(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        daily = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"], threadsdash_report=_manager_report_fixture(accounts=[])
        )
        request = (
            cf.domains.recommended_inventory_request.recommended_inventory_request_plan(
                creator="Stacey", target_count=5, daily_plan=daily
            )
        )
        audit = cf.domains.creative_knowledge.recommendation_quality_audit(
            creator="Stacey", campaign_slug=campaign["slug"]
        )

        assert cf.conn.total_changes == before
        for item in (
            analysis["recommendedMoreOf"]
            + analysis["recommendedLessOf"]
            + next_content["recommendations"]
            + request["requestBatches"]
        ):
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


def test_learning_confidence_fatigue_and_surface_comparison_reports_are_read_only(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign(
            "stacey_learning_reports", "stacey"
        )
        for idx, (surface, views, reach) in enumerate(
            [
                ("reel", 1000, 900),
                ("story", 850, 760),
                ("feed_single", 500, 450),
                ("feed_carousel", 650, 580),
                ("reel", 600, 520),
                ("reel", 300, 260),
            ],
            start=1,
        ):
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

        confidence = cf.domains.creative_knowledge.creative_learning_confidence_model(
            creator="Stacey", campaign_slug=campaign["slug"]
        )
        fatigue = cf.domains.creative_knowledge.creative_fatigue_report(
            creator="Stacey", campaign_slug=campaign["slug"]
        )
        comparison = cf.domains.creative_knowledge.creative_surface_comparison_report(
            creator="Stacey", campaign_slug=campaign["slug"]
        )

        assert cf.conn.total_changes == before
        assert (
            confidence["schema"]
            == "campaign_factory.creative_learning_confidence_model.v1"
        )
        assert confidence["confidenceModel"]["highConfidenceSignals"]
        assert confidence["currentConfidence"]["classification"] in {
            "low_confidence",
            "medium_confidence",
            "high_confidence",
        }
        assert fatigue["schema"] == "campaign_factory.creative_fatigue_report.v1"
        assert any(
            item["fatigueType"] == "concept_fatigue"
            for item in fatigue["fatigueSignals"]
        )
        assert (
            comparison["schema"]
            == "campaign_factory.creative_surface_comparison_report.v1"
        )
        concept = comparison["concepts"][0]
        assert concept["conceptId"] == "mirror_selfie"
        assert {surface["surface"] for surface in concept["surfaces"]} >= {
            "reel",
            "story",
            "feed_single",
            "feed_carousel",
        }
        assert all(
            report["wouldWrite"] is False
            for report in [confidence, fatigue, comparison]
        )
    finally:
        cf.close()


def test_phase2_learning_reports_share_creative_knowledge_helper(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign(
            "stacey_creative_kb_20260606", "stacey"
        )
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
        original = cf.domains.creative_knowledge.build_creative_knowledge_base

        def tracking_helper(*args, **kwargs):
            calls.append(str(kwargs.get("creator") or ""))
            return original(*args, **kwargs)

        monkeypatch.setattr(
            cf.domains.creative_knowledge,
            "build_creative_knowledge_base",
            tracking_helper,
        )

        kb = cf.domains.creative_knowledge.creative_knowledge_base(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        caption = cf.domains.creative_knowledge.creative_caption_report(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        winners = cf.domains.creative_knowledge.winner_registry(
            creator="Stacey", campaign_slug=campaign["slug"], min_views=1000
        )

        assert kb["schema"] == "campaign_factory.creative_knowledge_base.v1"
        assert caption["schema"] == "campaign_factory.creative_caption_report.v1"
        assert winners["schema"] == "campaign_factory.winner_registry.v1"
        assert len(calls) >= 3
        assert kb["wouldWrite"] is False
        assert caption["wouldWrite"] is False
        assert winners["wouldWrite"] is False
    finally:
        cf.close()


def test_phase2_decision_ledger_wrappers_share_query_helper(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_story_need",
            platform="instagram",
            external_id="ig_story_need",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf,
            account_id=account["id"],
            surface="story",
            cadence="daily",
            max_per_day=1,
        )
        cf.conn.commit()
        calls: list[dict[str, Any]] = []
        original = cf.domains.decision_ledger.query_decision_ledger

        def tracking_query(*args, **kwargs):
            calls.append(dict(kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(
            cf.domains.decision_ledger, "query_decision_ledger", tracking_query
        )
        source = {
            "creator": "Stacey",
            "date": "2026-06-06",
            "threadsdash_report": _manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_story_need",
                        "username": "stacey_story_need",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": True,
                    }
                ]
            ),
            "schedule_plan": {
                "creator": "Stacey",
                "validatedDraftsAvailable": 0,
                "items": [],
            },
            "generated_at": "2026-06-06T12:00:00+00:00",
        }

        report = cf.domains.decision_ledger.decision_ledger_report(**source)
        by_account = cf.domains.decision_ledger.decision_ledger_by_account(
            account_id=account["id"], **source
        )
        by_surface = cf.domains.decision_ledger.decision_ledger_by_surface(
            surface="story", **source
        )

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


def test_exception_queue_report_unifies_blockers_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        daily_plan = {
            "schema": "creator_os.daily_plan.v1",
            "creators": [
                {
                    "creator": "Stacey",
                    "inventoryShortfall": 4,
                    "surfaceShortfalls": {"story": {"shortfall": 2}},
                }
            ],
            "accounts": [
                {
                    "accountId": "ig_blocked",
                    "username": "blocked",
                    "state": "blocked",
                    "blockedReason": "needs_reauth",
                }
            ],
        }
        readiness = {
            "schema": "creator_os.execution_readiness.v1",
            "blockers": ["missing_instagram_post_caption", "embedded_audio_invalid"],
        }

        report = cf.domains.exceptions.exception_queue_report(
            daily_plan=daily_plan, execution_readiness=readiness
        )
        summary = cf.domains.exceptions.exception_queue_summary(
            daily_plan=daily_plan, execution_readiness=readiness
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.exception_queue_report.v1"
        assert report["exceptionCount"] >= 4
        assert {item["reason"] for item in report["exceptions"]} >= {
            "needs_reauth",
            "inventory_shortfall",
            "missing_instagram_post_caption",
            "embedded_audio_invalid",
        }
        assert all(
            {
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
            }
            <= set(item)
            for item in report["exceptions"]
        )
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
            "accounts": [
                {
                    "accountId": "ig_blocked",
                    "state": "blocked",
                    "blockedReason": "restriction_event",
                }
            ],
        }
        before = cf.conn.total_changes

        priority = cf.domains.exceptions.exception_queue_priority_report(
            daily_plan=daily_plan
        )
        owner = cf.domains.exceptions.exception_queue_owner_report(
            daily_plan=daily_plan
        )

        assert cf.conn.total_changes == before
        assert priority["schema"] == "creator_os.exception_queue_priority_report.v1"
        assert priority["exceptions"]
        assert priority["exceptions"][0]["severity"] in {"critical", "high"}
        assert priority["wouldWrite"] is False
        assert owner["schema"] == "creator_os.exception_queue_owner_report.v1"
        assert owner["owners"]
        assert all(
            "owner" in row and "exceptionCount" in row for row in owner["owners"]
        )
        assert owner["wouldWrite"] is False
    finally:
        cf.close()
