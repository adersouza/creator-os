from __future__ import annotations

import json
from pathlib import Path

import pytest
from campaign_asset_test_support import (
    add_audit_report,
    add_inventory_parent_fixture,
    add_surface_asset_fixture,
    write_rgb_png,
    write_surface_image,
)
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.adapters import (
    threadsdash_metrics_ingestion as threadsdash_metrics_adapter,
)
from campaign_factory.adapters.threadsdash_metrics_ingestion import (
    sync_performance_snapshots,
)
from campaign_factory.contracts import validate_recommendation_next_batch
from campaign_learning_test_support import (
    _approve_asset_for_lifecycle,
    _insert_creative_kb_snapshot,
    _lifecycle_state,
    _slice_rows,
    _threadsdash_lifecycle_post,
    threadsdash_campaign_factory_metadata,
)
from campaign_test_support import add_rendered_asset, make_factory


def test_record_audio_performance_snapshot_writes_rollup_and_graph(tmp_path: Path):
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
        result = cf.domains.audio_operations.record_audio_performance_snapshot(
            {
                "id": "snap_audio_1",
                "campaign_id": campaign["id"],
                "rendered_asset_id": "asset_1",
                "source_asset_id": None,
                "content_hash": "hash_1",
                "source_content_hash": None,
                "concept_id": None,
                "parent_reel_id": None,
                "variant_family_id": None,
                "variant_id": None,
                "variant_index": None,
                "variant_operations_json": "[]",
                "audio_id": "aud_mem",
                "caption_hash": None,
                "caption_text": None,
                "caption_bank": None,
                "caption_banks_json": "[]",
                "creator_mix": None,
                "creator_model": None,
                "frame_type": None,
                "length_class": None,
                "format_class": None,
                "caption_fit_version": None,
                "caption_outcome_context_json": "{}",
                "recipe": "v01_original",
                "account_id": "acct_1",
                "instagram_account_id": "ig_1",
                "post_id": "post_audio_1",
                "platform": "instagram",
                "content_surface": "reel",
                "snapshot_at": "2026-06-06T10:00:00+00:00",
                "views": 1000,
                "likes": 50,
                "comments": 5,
                "shares": 4,
                "saves": 3,
                "impressions": 1000,
                "reach": 900,
                "watch_time_seconds": None,
                "status": "published",
                "permalink": None,
                "published_at": None,
                "raw_json": json.dumps(
                    {
                        "metadata": {
                            "campaign_factory": {
                                "audio_intent": {
                                    "operator_selection": {
                                        "catalog_audio_id": "aud_mem",
                                        "platform_audio_id": "ig_mem",
                                        "audio_title": "Mirror Trend",
                                    }
                                }
                            }
                        }
                    }
                ),
            }
        )
        rollup = cf.conn.execute(
            "SELECT * FROM audio_performance_rollups WHERE audio_catalog_id = 'aud_mem'"
        ).fetchone()
        edges = {
            row["relation_type"]
            for row in cf.conn.execute(
                "SELECT relation_type FROM content_graph_edges"
            ).fetchall()
        }

        assert result == {
            "audioKey": "instagram:aud_mem",
            "audioCatalogId": "aud_mem",
            "score": 100.0,
        }
        assert rollup["post_count"] == 1
        assert rollup["view_count"] == 1000
        assert json.loads(rollup["stats_json"])["lastPostId"] == "post_audio_1"
        assert "audio_memory_to_performance_snapshot" in edges
    finally:
        cf.close()


def test_recommend_next_batch_prefers_performance_ranked_reference_pattern(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        now = "2026-01-02T00:00:00+00:00"
        for pattern_id, cluster_key, rank, label in [
            ("refpat_static", "static_active", 1, "Static Active"),
            ("refpat_winner", "winner_signal", 20, "Winner Signal"),
        ]:
            cf.conn.execute(
                """
                INSERT INTO reference_patterns (
                  id, cluster_key, rank, label, visual_format, hook_type, caption_archetype,
                  reference_ids_json, local_paths_json, public_urls_json, prompt_template_json,
                  higgsfield_json, caption_formulas_json, audio_recommendations_json, raw_json,
                  imported_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'mirror', 'curiosity', 'short_direct', '[]', '[]', '[]',
                  '{"captionBrief":"short direct caption"}', '{}', '[{"formula":"short direct caption"}]',
                  '{}', '{}', ?, ?)
                """,
                (pattern_id, cluster_key, rank, label, now, now),
            )
        cf.conn.execute(
            """
            INSERT INTO campaign_reference_plans
            (id, campaign_id, reference_pattern_id, variant_count, created_at, updated_at)
            VALUES ('crp_static', ?, 'refpat_static', 5, ?, ?)
            """,
            (campaign["id"], now, now),
        )
        caption_hash = threadsdash_client_adapter._text_hash("caption")
        snapshots = [
            ("perf_static", "post_static", "static_active", 200, 5, 0, 0, 0, 180),
            (
                "perf_winner_1",
                "post_winner_1",
                "winner_signal",
                15000,
                1200,
                90,
                130,
                180,
                13000,
            ),
            (
                "perf_winner_2",
                "post_winner_2",
                "winner_signal",
                14500,
                1100,
                80,
                120,
                170,
                12500,
            ),
            (
                "perf_winner_3",
                "post_winner_3",
                "winner_signal",
                15500,
                1250,
                95,
                140,
                190,
                13500,
            ),
        ]
        for (
            snapshot_id,
            post_id,
            cluster_key,
            views,
            likes,
            comments,
            shares,
            saves,
            reach,
        ) in snapshots:
            raw = {
                "metadata": {
                    "campaign_factory": {
                        "reference_pattern": {
                            "clusterKey": cluster_key,
                            "label": cluster_key.replace("_", " ").title(),
                        }
                    }
                }
            }
            cf.conn.execute(
                """
                INSERT INTO performance_snapshots
                (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
                 caption_hash, recipe, post_id, platform, status, instagram_account_id,
                 snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible, raw_json, created_at, published_at, history_source, lineage_v2_valid)
                VALUES (?, ?, 'asset_1', ?, ?, ?, ?, 'v01_original', ?, 'instagram',
                 'published', 'ig_1', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, '2026-01-02T00:00:00+00:00', 'metric_history', 1)
                """,
                (
                    snapshot_id,
                    campaign["id"],
                    source["id"],
                    source["content_hash"],
                    source["content_hash"],
                    caption_hash,
                    post_id,
                    now,
                    views,
                    likes,
                    comments,
                    shares,
                    saves,
                    reach,
                    json.dumps(raw),
                    now,
                ),
            )
        cf.conn.commit()

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=True
        )

        validate_recommendation_next_batch(rec)
        item = rec["items"][0]
        assert item["referencePatternId"] == "refpat_winner"
        assert item["referencePatternEvidence"]["recommendationStatus"] == "eligible"
        assert item["referencePatternEvidence"]["measuredExampleCount"] == 3
        assert item["advisory"] is False
        assert (
            item["referencePatternEvidence"]["selectionSource"]
            == "performance_snapshots"
        )
        rankings = item["referencePatternEvidence"]["rankings"]
        assert [ranking["patternId"] for ranking in rankings[:2]] == [
            "refpat_winner",
            "refpat_static",
        ]
        assert rankings[0]["performanceScore"] > rankings[1]["performanceScore"]
        assert rankings[0]["planningScore"] > rankings[1]["planningScore"]
        assert rankings[0]["bandit"]["algorithm"] == "beta_bernoulli_decayed_v1"
        assert rankings[0]["learning"]["status"] == "measured"
        assert (
            rankings[0]["learning"]["scoringVersion"]
            == "account_normalized_decay_shrinkage.v1"
        )
        assert (
            rankings[0]["learning"]["weightedRelativeReward"]
            > rankings[1]["learning"]["weightedRelativeReward"]
        )
        assert rankings[0]["learning"]["baselineSourceCounts"]["account_median"] >= 1
    finally:
        cf.close()


def test_recommend_next_batch_recommends_account_performance_ranked_variation_preset(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        now = "2026-01-02T12:00:00+00:00"
        caption_hash = threadsdash_client_adapter._text_hash("caption")
        snapshots = [
            ("perf_preset_subtle", "post_subtle", "ig_subtle", 250, 8, 0, 0, 1, 220),
            (
                "perf_preset_bold",
                "post_bold",
                "ig_bold",
                18000,
                1500,
                120,
                150,
                210,
                16000,
            ),
        ]
        for (
            snapshot_id,
            post_id,
            preset,
            views,
            likes,
            comments,
            shares,
            saves,
            reach,
        ) in snapshots:
            raw = {"metadata": {"campaign_factory": {"variationPreset": preset}}}
            cf.conn.execute(
                """
                INSERT INTO performance_snapshots
                (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
                 caption_hash, recipe, post_id, platform, status, instagram_account_id,
                 snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible,
                 variant_operations_json, raw_json, created_at, published_at, history_source, lineage_v2_valid)
                VALUES (?, ?, 'asset_1', ?, ?, ?, ?, 'v01_original', ?, 'instagram',
                 'published', 'ig_memory', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, '2026-01-02T00:00:00+00:00', 'metric_history', 1)
                """,
                (
                    snapshot_id,
                    campaign["id"],
                    source["id"],
                    source["content_hash"],
                    source["content_hash"],
                    caption_hash,
                    post_id,
                    now,
                    views,
                    likes,
                    comments,
                    shares,
                    saves,
                    reach,
                    json.dumps(
                        [{"type": "account_bound_variant", "preset_name": preset}]
                    ),
                    json.dumps(raw),
                    now,
                ),
            )
        cf.conn.commit()

        rebuilt = cf.domains.account_memory.rebuild_account_memory("may")
        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_memory", persist=True
        )

        assert rebuilt["accountCount"] == 1
        memory = cf.domains.account_memory.account_memory("may", account="ig_memory")[
            "accounts"
        ][0]
        variation_stats = [
            item
            for item in memory["patternStats"]
            if item["patternType"] == "variationPreset"
        ]
        assert len(variation_stats) == 2
        assert [item["label"] for item in variation_stats[:2]] == [
            "ig_bold",
            "ig_subtle",
        ]
        validate_recommendation_next_batch(rec)
        item = rec["items"][0]
        assert item["recommendedVariationPreset"] == "ig_bold"
        assert (
            item["variationPresetEvidence"]["selectionSource"]
            == "performance_snapshots"
        )
        rankings = item["variationPresetEvidence"]["rankings"]
        assert [ranking["presetName"] for ranking in rankings[:2]] == [
            "ig_bold",
            "ig_subtle",
        ]
        assert rankings[0]["performanceScore"] > rankings[1]["performanceScore"]
        assert rankings[0]["planningScore"] > rankings[1]["planningScore"]
        assert (
            rankings[0]["bandit"]["rewardEvent"]
            == "relative_reward_beats_account_baseline"
        )
    finally:
        cf.close()


def test_recommendation_lifecycle_accept_link_and_measure(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        now = "2026-01-02T00:00:00+00:00"
        caption_hash = threadsdash_client_adapter._text_hash("caption")
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
             snapshot_at, views, likes, comments, shares, saves, reach, raw_json, created_at,
             published_at, metrics_eligible, history_source, lineage_v2_valid)
            VALUES
            ('perf_rec', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_rec', 'instagram',
             'published', 'ig_1', ?, 12000, 900, 80, 100, 140, 10000, '{}', ?,
             '2026-01-02T00:00:00+00:00', 1, 'metric_history', 1),
            ('perf_base_1', ?, 'manual_1', ?, 'hash_b1', ?, ?, 'v01_original', 'post_b1', 'instagram',
             'published', 'ig_1', ?, 100, 5, 0, 0, 0, 100, '{}', ?,
             '2026-01-02T00:00:00+00:00', 1, 'metric_history', 1),
            ('perf_base_2', ?, 'manual_2', ?, 'hash_b2', ?, ?, 'v01_original', 'post_b2', 'instagram',
             'published', 'ig_1', ?, 120, 6, 0, 0, 0, 120, '{}', ?,
             '2026-01-02T00:00:00+00:00', 1, 'metric_history', 1),
            ('perf_base_3', ?, 'manual_3', ?, 'hash_b3', ?, ?, 'v01_original', 'post_b3', 'instagram',
             'published', 'ig_1', ?, 90, 4, 0, 0, 0, 90, '{}', ?,
             '2026-01-02T00:00:00+00:00', 1, 'metric_history', 1)
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

        accepted = cf.domains.recommendations.accept_recommendation_item(
            item_id, operator="operator_1", notes="use this"
        )
        assert accepted["status"] == "accepted"
        assert accepted["decision"]["action"] == "accepted"
        assert accepted["acceptedAt"]

        linked = cf.domains.recommendations.link_recommendation_item(
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

        measured = cf.domains.recommendations.measure_recommendation_item(item_id)
        measured_again = cf.domains.recommendations.measure_recommendation_item(item_id)
        assert measured["status"] == "proved"
        assert measured_again["status"] == "proved"
        assert measured["outcome"]["baselineSnapshotCount"] == 3
        assert measured["baseline"]["baselineType"] == "campaign_account_history"
        assert measured["baseline"]["sampleSize"] == 3
        assert measured["baseline"]["threshold"] == 5
        assert measured["baseline"]["confidence"] == "usable"
        assert measured["measurementVersion"] == "recommendation_measurement.v1"
        with pytest.raises(
            ValueError, match="invalid recommendation status transition"
        ):
            cf.domains.recommendations.accept_recommendation_item(item_id)
        overridden = cf.domains.recommendations.accept_recommendation_item(
            item_id,
            admin_override=True,
            override_reason="manual lifecycle correction",
        )
        assert overridden["status"] == "accepted"
        assert (
            overridden["decision"]["adminOverrides"][0]["reason"]
            == "manual lifecycle correction"
        )
        edge_types = {
            row["relation_type"]
            for row in cf.conn.execute(
                "SELECT relation_type FROM content_graph_edges"
            ).fetchall()
        }
        assert "recommendation_item_to_source_asset" in edge_types
        assert "recommendation_item_to_render_job" in edge_types
        assert "recommendation_item_to_rendered_asset" in edge_types
        assert "recommendation_item_to_threadsdash_post" in edge_types
        assert "recommendation_item_to_performance_snapshot" in edge_types
    finally:
        cf.close()


def test_variant_metrics_rollup_groups_by_parent_family_and_variant(tmp_path: Path):
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
        variant = cf.domains.variant_lineage.register_variant_asset(
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
             variant_family_id, variant_id, audio_id, created_at, published_at, history_source, lineage_v2_valid)
            VALUES ('perf_variant_1', ?, 'asset_1', ?, 'hash_1', 'caption_hash_1',
             'post_variant_1', 'instagram', 'published', 'ig_1', '2026-01-02T00:00:00+00:00',
             100, 10, 2, 3, 4, 90, 1, ?, ?, 'vfam_test', ?, 'audio_1', '2026-01-02T00:00:00+00:00', '2026-01-02T00:00:00+00:00', 'metric_history', 1)
            """,
            (
                cf.domains.rendered_asset("asset_1")["campaign_id"],
                cf.domains.rendered_asset("asset_1")["source_asset_id"],
                parent["conceptId"],
                parent["parentReelId"],
                variant["variantId"],
            ),
        )
        cf.conn.commit()

        report = cf.domains.variant_lineage.variant_metrics_rollup("may")

        assert report["summary"]["variantsPosted"] == 1
        assert report["summary"]["accountsReached"] == 1
        assert report["summary"]["totalViews"] == 100
        assert report["parents"][0]["parentReelId"] == parent["parentReelId"]
        assert report["families"][0]["variantFamilyId"] == "vfam_test"
        assert report["variants"][0]["variantId"] == variant["variantId"]
    finally:
        cf.close()


def test_carousel_child_metrics_plan_is_read_only_and_child_addressable(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        inputs = [
            write_rgb_png(
                tmp_path / f"metrics_carousel_{index}.png",
                1080,
                1080,
                color=(90, 110 + index, 160),
            )
            for index in range(2)
        ]
        registered = cf.domains.surface_registration.register_surface_asset(
            input_path=inputs,
            surface="feed_carousel",
            creator="Stacey",
            campaign_slug="stacey_surface_nonreel_20260606",
            instagram_post_caption="pick one",
            target_ratio="1:1",
        )
        before = cf.conn.total_changes

        plan = cf.domains.carousel_integrity.carousel_child_metrics_plan(
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


def test_feed_single_manifest_v2_is_metrics_eligible_after_publish(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "feed_metrics_v2.png")
        registered = cf.domains.surface_registration.register_surface_asset(
            input_path=image,
            surface="feed_single",
            creator="Stacey",
            campaign_slug="stacey_feed_single_proof",
            instagram_post_caption="soft launch today",
        )
        asset = cf.domains.rendered_asset(registered["renderedAssetId"])
        readiness = cf.domains.surface_handoff.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_feed_single_proof",
            rendered_asset_id=registered["renderedAssetId"],
        )["drafts"][0]
        manifest = readiness["handoffManifestV2"]
        row = {
            "id": "post_feed_single_v2",
            "status": "published",
            "platform": "instagram",
            "instagram_post_id": "ig_feed_single_v2",
            "permalink": "https://instagram.test/p/feed-single-v2",
            "published_at": "2026-01-02T01:00:00+00:00",
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

        eligibility = (
            threadsdash_metrics_adapter._metrics_eligibility_for_threadsdash_row(
                cf, row=row, meta=meta
            )
        )

        assert eligibility["eligible"] is True
        assert "handoff_manifest_version_invalid" not in eligibility["blockingReasons"]

        missing_identity = dict(row)
        missing_identity.pop("instagram_post_id")
        missing_identity.pop("permalink")
        missing_identity.pop("published_at")
        blocked = threadsdash_metrics_adapter._metrics_eligibility_for_threadsdash_row(
            cf, row=missing_identity, meta=meta
        )
        assert blocked["eligible"] is False
        assert set(blocked["blockingReasons"]) >= {
            "missing_instagram_post_id",
            "missing_instagram_permalink",
            "missing_instagram_published_at",
        }
    finally:
        cf.close()


def test_story_metrics_eligibility_allows_blank_story_caption_hash(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        image = write_surface_image(tmp_path / "story_metrics.png")
        registered = cf.domains.surface_registration.register_surface_asset(
            input_path=image,
            surface="story",
            creator="Stacey",
            campaign_slug="stacey_story_metrics_proof",
            story_asset_class="story_selfie",
            story_intent="casual_selfie",
            story_style="selfie",
        )
        asset = cf.domains.rendered_asset(registered["renderedAssetId"])
        draft = cf.domains.surface_handoff.surface_draft_proof(
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
            "instagram_post_id": "ig_story_metrics",
            "permalink": "https://instagram.test/s/story-metrics",
            "published_at": "2026-01-02T01:00:00+00:00",
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

        eligibility = (
            threadsdash_metrics_adapter._metrics_eligibility_for_threadsdash_row(
                cf, row=row, meta=meta
            )
        )

        assert eligibility["eligible"] is True
        assert (
            "handoff_manifest_caption_hash_mismatch"
            not in eligibility["blockingReasons"]
        )
    finally:
        cf.close()


def test_winner_expansion_report_is_read_only_and_uses_instagram_visible_metrics(
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
        variant = cf.domains.variant_lineage.register_variant_asset(
            parent_asset_id="asset_1",
            variant_asset_id="asset_1",
            variant_family_id="vfam_report",
            variant_index=1,
            operations=[
                {"type": "contentforge_result", "result": {"familyName": "cover_frame"}}
            ],
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
             variant_family_id, variant_id, audio_id, created_at, raw_json, published_at, history_source, lineage_v2_valid)
            VALUES ('perf_winner', ?, 'asset_1', ?, 'hash_1', 'caption_hash_1',
             'post_winner', 'instagram', 'published', 'ig_1', '2026-01-02T00:00:00+00:00',
             12000, 700, 40, 80, 100, 11000, 1, ?, ?, 'vfam_report', ?, 'audio_1',
             '2026-01-02T00:00:00+00:00', '{"onlyfansRevenue":999999}', '2026-01-02T00:00:00+00:00', 'metric_history', 1)
            """,
            (
                cf.domains.rendered_asset("asset_1")["campaign_id"],
                cf.domains.rendered_asset("asset_1")["source_asset_id"],
                parent["conceptId"],
                parent["parentReelId"],
                variant["variantId"],
            ),
        )
        cf.conn.commit()

        report = cf.domains.winner_expansion.winner_expansion_report(
            "may", min_views=1000
        )

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
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM variant_families").fetchone()[0]
            == before[0]
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0]
            == before[1]
        )
    finally:
        cf.close()


def test_sync_performance_snapshots_imports_metrics_once(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "post_metric_history":
                return _slice_rows(
                    [
                        {
                            "id": "hist_post_1_24h",
                            "post_id": "post_1",
                            "account_id": "acct_1",
                            "platform": "instagram",
                            "snapshot_at": "2026-01-03T01:00:00+00:00",
                            "hours_since_publish": 24,
                            "views_count": 1200,
                            "likes_count": 80,
                            "replies_count": 9,
                            "reposts_count": 0,
                            "quotes_count": 0,
                            "shares_count": 14,
                            "saves_count": 22,
                            "reach": 1100,
                            "engagement_rate": 0.113,
                            "created_at": "2026-01-03T01:00:00+00:00",
                        }
                    ],
                    params,
                )
            assert table == "posts"
            assert params["user_id"] == "eq.user_1"
            return _slice_rows(rows, params)

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        rows.append(
            {
                "id": "post_1",
                "status": "published",
                "platform": "instagram",
                "account_id": None,
                "instagram_account_id": "ig_1",
                "created_at": "2026-01-02T00:00:00+00:00",
                "updated_at": "2026-01-03T00:00:00+00:00",
                "published_at": "2026-01-02T01:00:00+00:00",
                "permalink": "https://instagram.test/p/1",
                "instagram_post_id": "ig_post_1",
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
            }
        )
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
            for row in cf.conn.execute(
                "SELECT entity_type, COUNT(*) AS n FROM content_graph_nodes GROUP BY entity_type"
            )
        }
        assert graph_counts["threadsdash_post"] == 1
        assert graph_counts["performance_snapshot"] == 1
        assert graph_counts["recommendation_input"] == 1
        sync_state = cf.conn.execute(
            "SELECT * FROM content_graph_sync_state WHERE system = 'threadsdash.performance'"
        ).fetchone()
        assert sync_state is not None
        summary = cf.domains.performance_summary_repo.performance_summary("may")
        asset = summary["renderedAssets"]["asset_1"]
        assert asset["count"] == 1
        assert asset["totals"]["views"] == 1200
        assert asset["totals"]["likes"] == 80
        assert asset["totals"]["saves"] == 22
        assert asset["totals"]["impressions"] == 1800
        assert asset["rates"]["engagementRate"] == pytest.approx(
            (80 + 9 + 14 + 22) / 1800
        )
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


def test_metric_history_read_omits_nonexistent_created_at_column():
    captured: dict[str, str] = {}

    class CapturedFailingRequestClient:
        def select(self, table, params):
            assert table == "post_metric_history"
            captured.update(params)
            if "created_at" in params["select"].split(","):
                raise RuntimeError(
                    "HTTP 400: column post_metric_history.created_at does not exist"
                )
            return _slice_rows(
                [
                    {
                        "id": "hist_no_created_at",
                        "post_id": "post_1",
                        "account_id": "acct_1",
                        "platform": "instagram",
                        "snapshot_at": "2026-01-03T01:00:00+00:00",
                        "hours_since_publish": 24,
                        "views_count": 1200,
                        "likes_count": 80,
                        "replies_count": 9,
                        "reposts_count": 0,
                        "quotes_count": 0,
                        "shares_count": 14,
                        "saves_count": 22,
                        "reach": 1100,
                        "engagement_rate": 0.113,
                    }
                ],
                params,
            )

    rows, truncated = (
        threadsdash_client_adapter._select_threadsdash_post_metric_history(
            CapturedFailingRequestClient(), post_ids=["post_1"], limit=1000
        )
    )
    assert truncated is False
    threadsdash_client_adapter._validate_threadsdash_post_metric_history_read(rows)

    assert len(rows) == 1
    assert "created_at" not in captured["select"].split(",")
    assert captured["post_id"] == "in.(post_1)"


@pytest.mark.parametrize("snapshot_at", [None, "not-a-date"])
def test_metric_history_read_rejects_invalid_snapshot_at_without_created_at_fallback(
    snapshot_at,
):
    row = {
        "id": "hist_invalid_snapshot_at",
        "post_id": "post_1",
        "account_id": "acct_1",
        "platform": "instagram",
        "snapshot_at": snapshot_at,
        "hours_since_publish": 24,
        "views_count": 1200,
        "likes_count": 80,
        "replies_count": 9,
        "reposts_count": 0,
        "quotes_count": 0,
        "shares_count": 14,
        "saves_count": 22,
        "reach": 1100,
        "engagement_rate": 0.113,
        # This used to be a tempting fallback. Metric-history rows must reject
        # invalid snapshot_at instead of silently relabeling created_at.
        "created_at": "2026-01-03T01:00:00+00:00",
    }

    with pytest.raises(
        RuntimeError,
        match="post_metric_history.read.v1 validation failed.*snapshot_at",
    ):
        threadsdash_client_adapter._validate_threadsdash_post_metric_history_read([row])


def test_metric_history_read_batches_the_captured_1000_post_request_shape():
    captured_filters: list[str] = []

    class UrlLengthGuardClient:
        def select(self, table, params):
            assert table == "post_metric_history"
            post_filter = params["post_id"]
            captured_filters.append(post_filter)
            if len(post_filter) >= 20_000:
                raise RuntimeError("Supabase request failed 400: Bad Request")
            return []

    post_ids = [f"00000000-0000-4000-8000-{index:012d}" for index in range(1000)]
    rows, truncated = (
        threadsdash_client_adapter._select_threadsdash_post_metric_history(
            UrlLengthGuardClient(), post_ids=post_ids, limit=1000
        )
    )
    assert truncated is False

    assert rows == []
    assert len(captured_filters) == 200
    assert all(len(post_filter) < 250 for post_filter in captured_filters)
    assert sum(post_filter.count(",") + 1 for post_filter in captured_filters) == 1000


def test_metric_history_read_detects_truncation():
    class TruncatedHistoryClient:
        def select(self, table, params):
            assert table == "post_metric_history"
            offset = int(params.get("offset", "0"))
            limit = int(params["limit"])
            return [
                {"id": f"hist_{offset + index}", "post_id": "post_1"}
                for index in range(limit)
            ]

    rows, truncated = (
        threadsdash_client_adapter._select_threadsdash_post_metric_history(
            TruncatedHistoryClient(), post_ids=["post_1"], limit=48
        )
    )

    assert truncated is True
    assert len(rows) == 48


def test_metric_history_failure_fails_open_but_fallback_is_learning_ineligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    error = "HTTP 503: post_metric_history temporarily unavailable"

    class FailingHistoryClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "post_metric_history":
                raise RuntimeError(error)
            assert table == "posts"
            return _slice_rows(
                [
                    {
                        "id": "post_fallback_1",
                        "status": "published",
                        "platform": "instagram",
                        "instagram_account_id": "ig_1",
                        "created_at": "2026-01-02T00:00:00+00:00",
                        "updated_at": "2026-01-03T01:00:00+00:00",
                        "published_at": "2026-01-02T01:00:00+00:00",
                        "permalink": "https://instagram.test/p/fallback-1",
                        "instagram_post_id": "ig_post_fallback_1",
                        "views": 1200,
                        "likes_count": 80,
                        "metadata": {
                            "campaign_factory": threadsdash_campaign_factory_metadata(
                                source
                            )
                        },
                    },
                    {
                        "id": "post_manual_1",
                        "status": "published",
                        "platform": "instagram",
                        "published_at": "2026-01-02T01:00:00+00:00",
                        "updated_at": "2026-01-03T01:00:00+00:00",
                        "metadata": {},
                    },
                ],
                params,
            )

    monkeypatch.setattr(
        threadsdash_client_adapter, "SupabaseRestClient", FailingHistoryClient
    )
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        result = sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        stored = cf.conn.execute(
            "SELECT metrics_eligible, history_source, lineage_v2_valid FROM performance_snapshots WHERE post_id = ?",
            ("post_fallback_1",),
        ).fetchone()
        assert result["inserted"] == 0
        assert result["postsScanned"] == 2
        assert result["postsImported"] == 0
        assert result["metricHistoryError"] == error
        assert result["historySources"] == {}
        assert result["fallbackRows"] == 0
        assert result["learningIneligiblePosts"] == 2
        assert result["learningIneligibleSnapshots"] == 0
        assert result["learningIneligibleReasons"] == {
            "metrics_not_observed": 1,
            "manual_no_lineage": 1,
        }
        assert result["learningReadiness"]["counts"]["eligiblePosts"] == 0
        assert stored is None
    finally:
        cf.close()


def test_sync_performance_snapshots_fails_loudly_on_metric_history_column_drift(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    post_rows = []
    history_rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "posts":
                offset = int(params.get("offset", 0))
                limit = int(params.get("limit", len(post_rows)))
                return post_rows[offset : offset + limit]
            if table == "post_metric_history":
                offset = int(params.get("offset", 0))
                limit = int(params.get("limit", len(history_rows)))
                return history_rows[offset : offset + limit]
            raise AssertionError(table)

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        post_rows.append(
            {
                "id": "post_history_drift",
                "status": "published",
                "platform": "instagram",
                "account_id": None,
                "instagram_account_id": "ig_1",
                "created_at": "2026-01-02T00:00:00+00:00",
                "updated_at": "2026-01-03T00:00:00+00:00",
                "published_at": "2026-01-02T01:00:00+00:00",
                "metadata": {
                    "campaign_factory": threadsdash_campaign_factory_metadata(source),
                },
            }
        )
        history_rows.append(
            {
                "id": "hist_drift",
                "post_id": "post_history_drift",
                "account_id": "acct_1",
                "platform": "instagram",
                "snapshot_at": "2026-01-03T01:00:00+00:00",
                "hours_since_publish": 24,
                "likes_count": 80,
                "replies_count": 9,
                "reposts_count": 0,
                "quotes_count": 0,
                "shares_count": 14,
                "saves_count": 22,
                "reach": 1100,
                "engagement_rate": 0.113,
                "created_at": "2026-01-03T01:00:00+00:00",
            }
        )

        with pytest.raises(
            RuntimeError,
            match="post_metric_history.read.v1 validation failed.*views_count",
        ):
            sync_performance_snapshots(
                cf,
                campaign_slug="may",
                user_id="user_1",
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
            )
    finally:
        cf.close()


def test_sync_performance_snapshots_dead_letters_missing_campaign_metadata(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    add_rendered_asset(cf, tmp_path)
    rows = [
        {
            "id": "post_missing_campaign_meta",
            "status": "published",
            "platform": "instagram",
            "account_id": None,
            "instagram_account_id": "ig_1",
            "created_at": "2026-01-02T00:00:00+00:00",
            "updated_at": "2026-01-03T00:00:00+00:00",
            "published_at": "2026-01-02T01:00:00+00:00",
            "permalink": "https://instagram.test/p/missing-meta",
            "views": 1200,
            "likes_count": 80,
            "metadata": {"source": "threadsdash"},
        }
    ]

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "post_metric_history":
                return []
            assert table == "posts"
            return _slice_rows(rows, params)

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        result = sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assert result["inserted"] == 0
        assert result["skipped"] == 1
        assert result["skipReasons"] == {"missing_campaign_factory_metadata": 1}
        assert result["warnings"][0]["reason"] == "missing_campaign_factory_metadata"
        assert result["warnings"][0]["postId"] == "post_missing_campaign_meta"
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM performance_snapshots").fetchone()[0]
            == 0
        )
        exception = cf.conn.execute(
            "SELECT reason_code, severity, payload_json FROM trust_exceptions"
        ).fetchone()
        assert (
            exception["reason_code"]
            == "threadsdash_performance_missing_campaign_metadata"
        )
        assert exception["severity"] == "medium"
        payload = json.loads(exception["payload_json"])
        assert payload["postId"] == "post_missing_campaign_meta"
        assert payload["reason"] == "missing_campaign_factory_metadata"
    finally:
        cf.close()


def test_sync_performance_snapshots_imports_caption_outcome_context_columns(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "post_metric_history":
                return []
            assert table == "posts"
            assert params["user_id"] == "eq.user_1"
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", len(rows)))
            return rows[offset : offset + limit]

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
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
            (
                "caption_hash_rendered",
                json.dumps(context, ensure_ascii=False, sort_keys=True),
                "v09_caption_bg",
            ),
        )
        cf.conn.commit()
        rows.append(
            {
                "id": "post_caption_outcome",
                "status": "published",
                "platform": "instagram",
                "account_id": None,
                "instagram_account_id": "ig_lola_1",
                "created_at": "2026-01-02T00:00:00+00:00",
                "updated_at": "2026-01-03T00:00:00+00:00",
                "published_at": "2026-01-02T01:00:00+00:00",
                "permalink": "https://instagram.test/p/caption-outcome",
                "instagram_post_id": "ig_post_caption_outcome",
                "metrics_observed_at": "2026-01-03T00:00:00+00:00",
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
                    "metrics": {
                        "saves": 24,
                        "reach": 1200,
                        "watch_time_seconds": 330.0,
                    },
                },
            }
        )

        result = sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        snapshot = cf.conn.execute(
            "SELECT * FROM performance_snapshots WHERE post_id = 'post_caption_outcome'"
        ).fetchone()
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
        assert (
            json.loads(snapshot["caption_outcome_context_json"])["suitability_decision"]
            == "allowed"
        )
    finally:
        cf.close()


def test_sync_performance_preserves_null_transport_fields_in_caption_context(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "post_metric_history":
                return []
            assert table == "posts"
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", len(rows)))
            return rows[offset : offset + limit]

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
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
            (
                "caption_hash_rendered",
                json.dumps(context, ensure_ascii=False, sort_keys=True),
            ),
        )
        cf.conn.commit()
        remote_context = dict(context)
        remote_context["render_recipe"] = "caption_outcome_fixture"
        remote_context["creator_model"] = "stacey"
        metadata = threadsdash_campaign_factory_metadata(
            source,
            caption_hash="caption_hash_rendered",
            recipe="caption_outcome_fixture",
            context=remote_context,
        )
        metadata["model_slug"] = "stacey"
        rows.append(
            {
                "id": "post_transport_recipe",
                "status": "published",
                "platform": "instagram",
                "instagram_account_id": "ig_stacey_1",
                "created_at": "2026-01-02T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "published_at": "2026-01-02T01:00:00+00:00",
                "permalink": "https://instagram.test/p/transport-recipe",
                "instagram_post_id": "ig_post_transport_recipe",
                "metrics_observed_at": "2026-01-03T00:00:00+00:00",
                "metadata": {"campaign_factory": metadata},
            }
        )

        sync_performance_snapshots(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        snapshot = cf.conn.execute(
            "SELECT * FROM performance_snapshots WHERE post_id = 'post_transport_recipe'"
        ).fetchone()
        stored_context = json.loads(snapshot["caption_outcome_context_json"])
        assert snapshot["recipe"] == "caption_outcome_fixture"
        assert stored_context["render_recipe"] is None
        assert snapshot["creator_model"] is None
        assert stored_context["creator_model"] is None
    finally:
        cf.close()


def test_performance_summary_includes_read_only_caption_outcome_review(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        campaign_id = cf.domains.campaign_by_slug("may")["id"]
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
             watch_time_seconds, metrics_eligible, raw_json, created_at, published_at, history_source, lineage_v2_valid)
            VALUES
            ('perf_caption_review_1', ?, 'asset_1', ?, 'hash_1', ?, 'caption_hash_1',
             'caption', 'question_bank', ?, 'Lola', 'lola', 'mirror_fullbody',
             'very_short', 'single_line', 'v1', 'clip_010', ?, 'v09_caption_bg',
             'post_caption_review_1', 'instagram', 'published', NULL, 'ig_1',
             '2026-01-03T00:00:00+00:00', 1000, 80, 9, 12, 18, 900, 240.0, 1, '{}',
             '2026-01-03T00:00:00+00:00', '2026-01-02T00:00:00+00:00', 'metric_history', 1)
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
             watch_time_seconds, metrics_eligible, raw_json, created_at, published_at, history_source, lineage_v2_valid)
            VALUES
            ('perf_caption_review_ineligible', ?, 'asset_bad', ?, 'hash_bad', ?, 'caption_hash_bad',
             'bad caption', 'bad_bank', ?, 'Lola', 'lola', 'mirror_fullbody',
             'very_short', 'single_line', 'v1', 'clip_bad', ?, 'v00_passthrough',
             'post_bad', 'instagram', 'published', NULL, 'ig_1',
             '2026-01-03T00:00:00+00:00', 9999, 999, 99, 99, 99, 9999, 999.0, 0, '{}',
             '2026-01-03T00:00:00+00:00', '2026-01-02T00:00:00+00:00', 'metric_history', 1)
            """,
            (
                campaign_id,
                source["id"],
                source["content_hash"],
                json.dumps(["bad_bank"]),
                json.dumps(
                    {
                        **context,
                        "caption_hash": "caption_hash_bad",
                        "caption_bank": "bad_bank",
                    }
                ),
            ),
        )
        cf.conn.commit()

        review = cf.domains.performance_summary_repo.performance_summary("may")[
            "captionOutcomeReview"
        ]
        direct = cf.domains.performance_summary_repo.caption_outcome_report("may")

        assert review["manualReviewOnly"] is True
        assert (
            cf.domains.performance_summary_repo.performance_summary("may")[
                "snapshotCount"
            ]
            == 1
        )
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
        assert (
            review["byCaptionPlacementStatus"][0]["captionPlacementStatus"] == "passed"
        )
        assert "promote" not in json.dumps(review).lower()
        assert "winner" not in json.dumps(review).lower()
    finally:
        cf.close()


def test_lifecycle_report_derives_approved_assigned_planned_and_ready_states(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)

        approved = cf.domains.lifecycle_reporting.lifecycle_report(
            "may", include_threadsdash="off"
        )
        assert _lifecycle_state(approved) == "creative_approved"
        assert approved["rows"][0]["blockingReason"] == "missing_distribution_plan"

        cf.domains.campaign_overview.assign_asset_account(
            "asset_1", instagram_account_id="ig_1"
        )
        assigned = cf.domains.lifecycle_reporting.lifecycle_report(
            "may", include_threadsdash="off"
        )
        assert _lifecycle_state(assigned) == "assigned"

        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        ready = cf.domains.lifecycle_reporting.lifecycle_report(
            "may", include_threadsdash="off"
        )
        assert _lifecycle_state(ready) == "exportable"
        assert ready["rows"][0]["distributionPlanId"] == plan["id"]

        cf.conn.execute("DELETE FROM audit_reports")
        cf.conn.commit()
        blocked = cf.domains.lifecycle_reporting.lifecycle_report(
            "may", include_threadsdash="off"
        )
        assert _lifecycle_state(blocked) == "distribution_planned"
        assert blocked["rows"][0]["blockingReason"] == "missing_audit"
    finally:
        cf.close()


def test_lifecycle_report_derives_published_and_metrics_imported_states(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        published = cf.domains.lifecycle_reporting.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    status="published",
                    published_at="2026-01-02T00:00:00+00:00",
                    plan_id=plan["id"],
                )
            ],
        )
        assert _lifecycle_state(published) == "published"
        assert published["rows"][0]["blockingReason"] == "awaiting_metrics"

        campaign = cf.domains.campaign_by_slug("may")
        rendered_hash = cf.domains.rendered_asset("asset_1")["content_hash"]
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id, snapshot_at, views, raw_json, created_at)
            VALUES ('perf_1', ?, 'asset_1', ?, ?, ?, 'caption_hash_1', 'v01_original',
                    'post_1', 'instagram', 'published', 'ig_1', '2026-01-02T01:00:00+00:00', 123, '{}', '2026-01-02T01:00:00+00:00')
            """,
            (
                campaign["id"],
                cf.domains.asset_import.assets_for_campaign(campaign["id"])[0]["id"],
                rendered_hash,
                cf.domains.asset_import.assets_for_campaign(campaign["id"])[0][
                    "content_hash"
                ],
            ),
        )
        cf.conn.commit()

        measured = cf.domains.lifecycle_reporting.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(status="published", plan_id=plan["id"])
            ],
        )
        assert _lifecycle_state(measured) == "metrics_imported"
        assert measured["summary"]["stateCounts"]["metrics_imported"] == 1
    finally:
        cf.close()


def test_lifecycle_report_ignores_null_report_context_fields_after_metrics_import(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source = _approve_asset_for_lifecycle(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                json.dumps(
                    {
                        "schema": "campaign_factory.caption_outcome_context.v1",
                        "caption_hash": "caption_hash_1",
                        "caption_text": "caption",
                        "render_recipe": None,
                    }
                ),
            ),
        )
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        campaign = cf.domains.campaign_by_slug("may")
        rendered_hash = cf.domains.rendered_asset("asset_1")["content_hash"]
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, caption_outcome_context_json, recipe, post_id, platform, status,
             instagram_account_id, snapshot_at, views, raw_json, created_at)
            VALUES ('perf_1', ?, 'asset_1', ?, ?, ?, 'caption_hash_1', ?,
                    'v01_original', 'post_1', 'instagram', 'published', 'ig_1',
                    '2026-01-02T01:00:00+00:00', 123, '{}', '2026-01-02T01:00:00+00:00')
            """,
            (
                campaign["id"],
                source["id"],
                rendered_hash,
                source["content_hash"],
                json.dumps(
                    {
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
                    }
                ),
            ),
        )
        cf.conn.commit()

        measured = cf.domains.lifecycle_reporting.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
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
                )
            ],
        )

        assert _lifecycle_state(measured) == "metrics_imported"
        assert measured["summary"]["stateCounts"]["metrics_imported"] == 1
        assert measured["summary"]["stuckCounts"] == {}
        assert measured["rows"][0]["evidence"]["lineageMismatch"] == {}
    finally:
        cf.close()


def test_creator_os_lifecycle_dashboard_summarizes_lifecycle_states_read_only(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        before = cf.conn.total_changes

        dashboard = cf.domains.lifecycle_reporting.creator_os_lifecycle_dashboard(
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
        cf.domains.publishability.quarantine_asset(
            "asset_1", reason="operator_quarantine", root_cause="qc_failure"
        )
        before = cf.conn.total_changes

        dashboard = cf.domains.lifecycle_reporting.creator_os_lifecycle_dashboard(
            campaign="may", include_threadsdash="off"
        )

        assert cf.conn.total_changes == before
        assert dashboard["counts"]["quarantined"] == 1
        assert dashboard["counts"]["failed"] == 0
        assert dashboard["rows"][0]["bucket"] == "quarantined"
        assert dashboard["rows"][0]["currentState"] == "failed"
        assert dashboard["wouldWrite"] is False
    finally:
        cf.close()


def test_performance_summary_builds_hook_recipe_audio_leaderboards(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        campaign_id = cf.domains.campaign_by_slug("may")["id"]
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
                        "schema": "reel_factory.generated_asset_lineage.v1",
                        "source": {
                            "referenceId": "ref_1",
                            "patternCardId": "pattern_1",
                            "promptId": "prompt_1",
                            "formatType": "mirror_selfie",
                        },
                        "generation": {
                            "tool": "higgsfield_kling_manual",
                            "modelProfile": "soul_main",
                        },
                        "review": {"humanReviewRequired": True, "status": "draft"},
                    },
                },
                "audio_intent": {
                    "schema": "pipeline.audio_intent.v1",
                    "status": "recommended",
                    "recommendations": [
                        {
                            "audio_title": "Runway Pop",
                            "artist_name": "DJ A",
                            "platform_audio_id": "ig_audio_1",
                            "platform_url": "https://instagram.com/audio/1",
                        }
                    ],
                },
            }
        }
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, account_id, instagram_account_id,
             permalink, published_at, snapshot_at, views, likes, comments, shares, saves, reach,
             watch_time_seconds, metrics_eligible, raw_json, created_at, history_source, lineage_v2_valid)
            VALUES
            ('perf_lb_1', ?, 'asset_1', ?, 'hash_1', ?, 'caption_hash_1',
             'v01_original', 'post_lb_1', 'instagram', 'published', NULL, 'ig_1',
             'https://instagram.test/p/lb1', '2026-01-02T00:00:00+00:00',
             '2026-01-03T00:00:00+00:00', 1000, 80, 9, 12, 18, 900, 240.0, 1, ?, '2026-01-03T00:00:00+00:00', 'metric_history', 1)
            """,
            (
                campaign_id,
                source["id"],
                source["content_hash"],
                json.dumps({"metadata": meta}),
            ),
        )
        cf.conn.commit()

        summary = cf.domains.performance_summary_repo.performance_summary("may")
        leaderboards = summary["leaderboards"]

        assert (
            leaderboards["hooks"][0]["hook"]["key"]
            == "caption_led_visual::direct_response::question_hook"
        )
        assert leaderboards["hooks"][0]["performance"]["totals"]["saves"] == 18
        assert leaderboards["recipes"][0]["recipe"] == "v01_original"
        assert (
            leaderboards["audioRecommendations"][0]["audio"]["platformAudioId"]
            == "ig_audio_1"
        )
        assert (
            leaderboards["referenceFormats"][0]["referenceFormat"]["key"]
            == "mirror_selfie"
        )
        assert (
            leaderboards["promptPatterns"][0]["promptPattern"]["key"]
            == "caption_led_visual::direct_response::question_hook"
        )
        assert (
            leaderboards["promptPatterns"][0]["promptPattern"]["primaryMetric"]
            == "views_reach"
        )
        assert leaderboards["patternCards"][0]["patternCard"]["key"] == "pattern_1"
        assert (
            leaderboards["modelAccounts"][0]["modelAccount"]["modelProfile"]
            == "soul_main"
        )
        assert (
            leaderboards["captionFormulas"][0]["captionFormula"]["label"]
            == "question_hook"
        )
        assert leaderboards["hookRecipeCombos"][0]["recipe"] == "v01_original"
        assert leaderboards["formatRecipeCombos"][0]["recipe"] == "v01_original"
        assert (
            leaderboards["formatAudioCombos"][0]["audio"]["audioTitle"] == "Runway Pop"
        )
        assert leaderboards["hookAudioCombos"][0]["audio"]["audioTitle"] == "Runway Pop"
        assert leaderboards["hookRecipeAudioCombos"][0]["renderedAssetIds"] == [
            "asset_1"
        ]
        assert (
            summary["snapshots"][0]["dimensions"]["audio"]["platformUrl"]
            == "https://instagram.com/audio/1"
        )
        assert (
            summary["snapshots"][0]["dimensions"]["referenceFormat"]["label"]
            == "mirror_selfie"
        )
        assert (
            summary["snapshots"][0]["dimensions"]["patternCard"]["key"] == "pattern_1"
        )
    finally:
        cf.close()


def test_ranking_uses_performance_but_keeps_blocked_assets_low(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
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
        campaign_id = cf.domains.campaign_by_slug("may")["id"]
        caption_hash = threadsdash_client_adapter._text_hash("caption")
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, account_id, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, watch_time_seconds,
             raw_json, created_at, published_at, metrics_eligible, history_source, lineage_v2_valid)
            VALUES
            ('perf_good', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_1', 'instagram', 'published',
             NULL, 'ig_1', '2026-01-03T00:00:00+00:00', 10000, 800, 80, 100, 120, 9000, 500.0, '{}',
             '2026-01-03T00:00:00+00:00', '2026-01-02T00:00:00+00:00', 1, 'metric_history', 1)
            """,
            (campaign_id, source["id"], source["content_hash"], caption_hash),
        )
        cf.conn.commit()

        ranking = cf.domains.account_planning.ranking("may")
        by_asset = ranking["byAsset"]
        assert by_asset["asset_1"]["breakdown"]["sourceHistory"] > 50
        assert by_asset["asset_1"]["score"] > by_asset["asset_blocked"]["score"]
        assert by_asset["asset_blocked"]["score"] <= 35
        assert (
            "blocked assets stay low regardless of performance"
            in by_asset["asset_blocked"]["reasons"]
        )
    finally:
        cf.close()


def test_creative_performance_analysis_reports_insufficient_data_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("stacey_creative_perf", "stacey")
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

        report = cf.domains.creative_knowledge.creative_performance_analysis(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "campaign_factory.creative_performance_analysis.v1"
        assert report["insufficientData"] is True
        assert report["reason"] == "not_enough_published_metrics"
        assert report["bestPerformingPatterns"] == []
        assert report["underperformingPatterns"] == []
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creative_performance_analysis_baseline_and_recommendations_are_explainable(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("stacey_creative_perf", "stacey")
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

        report = cf.domains.creative_knowledge.creative_performance_analysis(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        summary = cf.domains.creative_knowledge.creator_learning_summary(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        recommendations = cf.domains.creative_knowledge.next_content_recommendations(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )

        assert report["insufficientData"] is False
        assert report["confidence"] == "medium"
        assert report["creatorBaseline"]["postCount"] == 10
        assert report["creatorBaseline"]["avgViews"] == 670
        assert report["bestPerformingPatterns"][0]["key"] == "mirror_selfie"
        assert (
            report["bestPerformingPatterns"][0]["comparison"]
            == "above_creator_baseline"
        )
        assert "above creator baseline" in report["bestPerformingPatterns"][0]["reason"]
        assert any(
            item["key"] == "generic_feed" for item in report["underperformingPatterns"]
        )
        assert any(
            item["recommendation"] == "make_more_variants"
            for item in report["recommendedMoreOf"]
        )
        assert any(
            item["recommendation"] == "avoid_or_rework_pattern"
            for item in report["recommendedLessOf"]
        )
        assert all(
            item["reason"]
            for item in report["recommendedMoreOf"] + report["recommendedLessOf"]
        )
        assert summary["confidence"] == "medium"
        assert summary["summary"]
        assert any("mirror_selfie" in line for line in summary["summary"])
        assert recommendations["recommendations"][0]["surface"] == "reel"
        assert (
            recommendations["recommendations"][0]["parentAssetId"]
            == "asset_good_parent"
        )
        assert recommendations["recommendations"][0]["captionAngle"] == "tease"
        assert recommendations["recommendations"][0]["audioId"] == "audio_12"
        assert recommendations["recommendations"][0]["confidence"] == "medium"
        assert report["wouldWrite"] is False
        assert summary["wouldWrite"] is False
        assert recommendations["wouldWrite"] is False
    finally:
        cf.close()


def test_creative_performance_analysis_confidence_thresholds_and_story_recommendation(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign(
            "stacey_creative_perf_confidence", "stacey"
        )
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

        report = cf.domains.creative_knowledge.creative_performance_analysis(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )
        recommendations = cf.domains.creative_knowledge.next_content_recommendations(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=3
        )

        assert report["confidence"] == "high"
        assert any(
            item["dimension"] == "storyIntent" and item["key"] == "snapchat_promo"
            for item in report["bestPerformingPatterns"]
        )
        story_recs = [
            item
            for item in recommendations["recommendations"]
            if item["surface"] == "story"
        ]
        assert story_recs
        assert story_recs[0]["recommendation"] == "make_more_snapchat_promo_stories"
        assert "above creator baseline" in story_recs[0]["reason"]
        assert story_recs[0]["confidence"] == "high"
        assert recommendations["wouldWrite"] is False
    finally:
        cf.close()


def test_track_q_calibration_status_counts_owner_reviewed_reels_and_low_score_samples(
    tmp_path: Path,
):
    from campaign_factory.quality_calibration import track_q_calibration_status

    cf = make_factory(tmp_path)
    try:
        base = track_q_calibration_status(
            cf.conn, campaign_slug="stacey_archive_marketing_20260606"
        )
        assert base["schema"] == "campaign_factory.track_q_calibration_status.v1"
        assert base["targets"] == {
            "reviewedReels": 30,
            "lowScoreOrRejectedSamples": 10,
            "lowScoreThreshold": 70,
        }
        assert base["calibrationReady"] is False
        assert base["remaining"]["reviewedReels"] == 30
        assert base["remaining"]["lowScoreOrRejectedSamples"] == 10

        for idx, (decision, score) in enumerate(
            [("approved", 92), ("rejected", 88), ("approved", 61)], start=1
        ):
            asset_id = f"asset_calibration_{idx}"
            add_inventory_parent_fixture(cf, tmp_path, asset_id=asset_id)
            cf.domains.finished_video.review_rendered_asset(
                asset_id, decision=decision, notes=f"owner {decision}"
            )
            cf.conn.execute(
                "UPDATE audit_reports SET score = ?, created_at = ? WHERE rendered_asset_id = ?",
                (score, f"2026-01-0{idx}T00:00:00+00:00", asset_id),
            )
        cf.conn.commit()

        ready = track_q_calibration_status(
            cf.conn,
            campaign_slug="stacey_archive_marketing_20260606",
            min_reviewed_reels=3,
            min_low_score_or_rejected_samples=2,
            low_score_threshold=70,
        )

        assert ready["calibrationReady"] is True
        assert ready["status"] == "ready_for_calibration"
        assert ready["counts"]["reviewedReels"] == 3
        assert ready["counts"]["rejectedReels"] == 1
        assert ready["counts"]["lowScoreReviewedReels"] == 1
        assert ready["counts"]["lowScoreOrRejectedSamples"] == 2
        assert ready["remaining"] == {
            "reviewedReels": 0,
            "lowScoreOrRejectedSamples": 0,
        }
        assert ready["wouldWrite"] is False
    finally:
        cf.close()


def test_closed_loop_learning_status_counts_posts_with_1h_and_24h_history(
    tmp_path: Path,
):
    from campaign_factory.learning_readiness import closed_loop_learning_status

    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign(
            "stacey_learning_volume_20260606", "stacey"
        )
        now = "2026-01-05T00:00:00+00:00"
        rows = [
            ("snap_post_1_1h", "post_1", "2026-01-01T01:00:00+00:00", 1, 100),
            ("snap_post_1_24h", "post_1", "2026-01-02T00:00:00+00:00", 24, 1200),
            ("snap_post_2_1h", "post_2", "2026-01-03T01:00:00+00:00", 1, 80),
        ]
        for snapshot_id, post_id, snapshot_at, hours_since_publish, views in rows:
            cf.conn.execute(
                """
                INSERT INTO performance_snapshots
                (id, campaign_id, post_id, content_surface, snapshot_at, published_at, views,
                 metrics_eligible, raw_json, created_at, history_source, lineage_v2_valid)
                VALUES (?, ?, ?, 'reel', ?, '2026-01-01T00:00:00+00:00', ?, 1, ?, ?, 'metric_history', 1)
                """,
                (
                    snapshot_id,
                    campaign["id"],
                    post_id,
                    snapshot_at,
                    views,
                    json.dumps(
                        {
                            "metadata": {
                                "threadsdash_metric_history": {
                                    "hoursSincePublish": hours_since_publish
                                }
                            }
                        }
                    ),
                    now,
                ),
            )
        cf.conn.commit()

        base = closed_loop_learning_status(cf.conn, campaign_slug=campaign["slug"])
        assert base["schema"] == "campaign_factory.closed_loop_learning_status.v1"
        assert base["targets"] == {"postsWith1hAnd24hHistory": 50}
        assert base["learningAuditReady"] is False
        assert base["counts"]["eligiblePosts"] == 2
        assert base["counts"]["postsWith1hHistory"] == 2
        assert base["counts"]["postsWith24hHistory"] == 1
        assert base["counts"]["postsWith1hAnd24hHistory"] == 1
        assert base["remaining"]["postsWith1hAnd24hHistory"] == 49

        ready = closed_loop_learning_status(
            cf.conn, campaign_slug=campaign["slug"], min_posts_with_1h_and_24h=1
        )
        assert ready["learningAuditReady"] is True
        assert ready["status"] == "ready_for_learning_audit"
        assert ready["remaining"] == {"postsWith1hAnd24hHistory": 0}
        assert ready["wouldWrite"] is False
    finally:
        cf.close()


def test_story_certification_requires_actual_publish_and_metrics_evidence(
    tmp_path: Path,
):
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

        blocked = cf.domains.story_management.story_certification_proof(
            rendered_asset_id=asset["id"]
        )

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


def test_carousel_certification_passes_with_ordering_publish_and_metrics_evidence(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        result = cf.domains.surface_registration.register_surface_asset(
            input_path=[
                write_surface_image(tmp_path / f"cert_carousel_{index}.png")
                for index in range(3)
            ],
            surface="feed_carousel",
            creator="Stacey",
            campaign_slug="stacey_carousel_cert_20260609",
            instagram_post_caption="which one wins?",
        )
        asset_id = result["renderedAssetId"]
        asset = cf.domains.rendered_asset(asset_id)
        cf.domains.publishability.record_proof_run(
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
            (
                asset["campaign_id"],
                asset_id,
                asset["source_asset_id"],
                asset["content_hash"],
                asset["caption_hash"],
            ),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        proof = cf.domains.carousel_integrity.carousel_certification_proof(
            rendered_asset_id=asset_id
        )

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
