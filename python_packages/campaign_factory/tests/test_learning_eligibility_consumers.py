from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.learning_readiness import closed_loop_learning_status

CUTOVER = "2026-06-01T00:00:00+00:00"
ELIGIBLE_PUBLISHED_AT = "2026-06-02T00:00:00+00:00"


@pytest.fixture(autouse=True)
def learning_loop_cutover_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEARNING_LOOP_CUTOVER", CUTOVER)


def make_factory(tmp_path: Path) -> CampaignFactory:
    reel_root = tmp_path / "reel_factory"
    reel_root.mkdir()
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=reel_root,
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def caption_hash(text: str = "learning caption") -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


def insert_snapshot(
    cf: CampaignFactory,
    *,
    campaign_id: str,
    snapshot_id: str,
    post_id: str,
    rendered_asset_id: str = "asset_learning",
    source_asset_id: str = "source_learning",
    caption: str = "learning caption",
    recipe: str = "v01_original",
    account: str = "ig_eligible",
    published_at: str | None = ELIGIBLE_PUBLISHED_AT,
    snapshot_at: str = "2026-06-03T00:00:00+00:00",
    metrics_eligible: int = 1,
    history_source: str = "metric_history",
    lineage_v2_valid: int = 1,
    views: int = 100,
    likes: int = 10,
    comments: int = 1,
    shares: int = 2,
    saves: int = 3,
    reach: int = 90,
    raw: dict[str, Any] | None = None,
    variant_id: str | None = None,
    variant_family_id: str | None = None,
    parent_reel_id: str | None = None,
    creator_mix: str | None = None,
) -> None:
    cf.conn.execute(
        """
        INSERT INTO performance_snapshots (
          id, campaign_id, rendered_asset_id, source_asset_id, caption_hash, recipe,
          post_id, platform, status, instagram_account_id, published_at, snapshot_at,
          views, likes, comments, shares, saves, reach, metrics_eligible, history_source,
          lineage_v2_valid, raw_json, created_at, variant_id, variant_family_id,
          parent_reel_id, creator_mix
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'instagram', 'published', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            campaign_id,
            rendered_asset_id,
            source_asset_id,
            caption_hash(caption),
            recipe,
            post_id,
            account,
            published_at,
            snapshot_at,
            views,
            likes,
            comments,
            shares,
            saves,
            reach,
            metrics_eligible,
            history_source,
            lineage_v2_valid,
            json.dumps(raw or {}, sort_keys=True),
            snapshot_at,
            variant_id,
            variant_family_id,
            parent_reel_id,
            creator_mix,
        ),
    )


def insert_reference_pattern(
    cf: CampaignFactory, *, pattern_id: str, cluster_key: str, rank: int
) -> None:
    cf.conn.execute(
        """
        INSERT INTO reference_patterns (
          id, cluster_key, rank, label, visual_format, hook_type, caption_archetype,
          reference_ids_json, local_paths_json, public_urls_json, prompt_template_json,
          higgsfield_json, caption_formulas_json, audio_recommendations_json, raw_json,
          imported_at, updated_at
        ) VALUES (?, ?, ?, ?, 'mirror', 'curiosity', 'short_direct', '[]', '[]', '[]',
          '{}', '{}', '[]', '{}', '{}', ?, ?)
        """,
        (
            pattern_id,
            cluster_key,
            rank,
            cluster_key.replace("_", " ").title(),
            ELIGIBLE_PUBLISHED_AT,
            ELIGIBLE_PUBLISHED_AT,
        ),
    )


def test_readiness_counts_only_forward_metric_history_with_v2_lineage(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("learning_eligibility", "instagram")
        cases = [
            ("eligible", ELIGIBLE_PUBLISHED_AT, "metric_history", 1, 1),
            ("pre_cutover", "2026-05-31T00:00:00+00:00", "metric_history", 1, 1),
            ("fallback", ELIGIBLE_PUBLISHED_AT, "post_row_fallback", 1, 1),
            ("no_lineage", ELIGIBLE_PUBLISHED_AT, "metric_history", 0, 1),
            ("raw_only", ELIGIBLE_PUBLISHED_AT, "metric_history", 1, 0),
            ("null_published", None, "metric_history", 1, 1),
        ]
        for (
            name,
            published_at,
            history_source,
            lineage_valid,
            metrics_eligible,
        ) in cases:
            for hour, snapshot_at in (
                (1, "2026-06-02T01:00:00+00:00"),
                (24, "2026-06-03T00:00:00+00:00"),
            ):
                insert_snapshot(
                    cf,
                    campaign_id=campaign["id"],
                    snapshot_id=f"snap_{name}_{hour}",
                    post_id=f"post_{name}",
                    published_at=published_at,
                    snapshot_at=snapshot_at,
                    metrics_eligible=metrics_eligible,
                    history_source=history_source,
                    lineage_v2_valid=lineage_valid,
                    raw={
                        "metadata": {
                            "threadsdash_metric_history": {"hoursSincePublish": hour}
                        }
                    },
                )
        cf.conn.commit()

        status = closed_loop_learning_status(
            cf.conn,
            campaign_slug=campaign["slug"],
            min_posts_with_1h_and_24h=1,
        )

        assert status["learningAuditReady"] is True
        assert status["counts"] == {
            "eligiblePosts": 1,
            "postsWith1hHistory": 1,
            "postsWith24hHistory": 1,
            "postsWith1hAnd24hHistory": 1,
        }
    finally:
        cf.close()


def test_readiness_reaches_the_50_post_dual_window_gate(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("learning_fifty", "instagram")
        for post_index in range(50):
            for hour, snapshot_at in (
                (1, f"2026-06-02T01:{post_index:02d}:00+00:00"),
                (24, f"2026-06-03T00:{post_index:02d}:00+00:00"),
            ):
                insert_snapshot(
                    cf,
                    campaign_id=campaign["id"],
                    snapshot_id=f"snap_{post_index}_{hour}",
                    post_id=f"post_{post_index}",
                    snapshot_at=snapshot_at,
                    raw={
                        "metadata": {
                            "threadsdash_metric_history": {"hoursSincePublish": hour}
                        }
                    },
                )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_partial_1",
            post_id="post_partial",
            snapshot_at="2026-06-02T01:59:00+00:00",
            raw={"metadata": {"threadsdash_metric_history": {"hoursSincePublish": 1}}},
        )
        cf.conn.commit()

        status = closed_loop_learning_status(cf.conn, campaign_slug=campaign["slug"])

        assert status["learningAuditReady"] is True
        assert status["counts"] == {
            "eligiblePosts": 51,
            "postsWith1hHistory": 51,
            "postsWith24hHistory": 50,
            "postsWith1hAnd24hHistory": 50,
        }
        assert status["remaining"] == {"postsWith1hAnd24hHistory": 0}
    finally:
        cf.close()


def test_performance_summary_asset_planning_and_baselines_exclude_poison_rows(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("learning_performance", "instagram")
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_eligible",
            post_id="post_eligible",
            views=100,
            account="ig_eligible",
        )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_fallback_poison",
            post_id="post_fallback_poison",
            snapshot_at="2026-06-04T00:00:00+00:00",
            views=999_999,
            account="ig_poison",
            history_source="post_row_fallback",
        )
        cf.conn.commit()

        summary = cf.performance_summary(campaign["slug"])
        asset_performance = cf._performance_for_asset(
            {
                "id": "asset_learning",
                "source_asset_id": "source_learning",
                "caption": "learning caption",
                "recipe": "v01_original",
            }
        )

        assert summary["snapshotCount"] == 1
        assert summary["accounts"].keys() == {"ig_eligible"}
        assert summary["renderedAssets"]["asset_learning"]["totals"]["views"] == 100
        assert asset_performance["latestPerformance"]["id"] == "snap_eligible"
        assert asset_performance["sourcePerformance"]["count"] == 1
        assert asset_performance["sourcePerformance"]["totals"]["views"] == 100
    finally:
        cf.close()


def test_recommendation_rankings_and_measurement_exclude_ineligible_rows(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("learning_recommendations", "instagram")
        insert_reference_pattern(
            cf, pattern_id="refpat_eligible", cluster_key="eligible_pattern", rank=20
        )
        insert_reference_pattern(
            cf, pattern_id="refpat_poison", cluster_key="poison_pattern", rank=1
        )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_rec_eligible",
            post_id="post_rec_eligible",
            rendered_asset_id="asset_measurement",
            views=100,
            raw={
                "metadata": {
                    "campaign_factory": {
                        "reference_pattern": {"clusterKey": "eligible_pattern"},
                        "variationPreset": "ig_subtle",
                    }
                }
            },
        )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_rec_poison",
            post_id="post_rec_poison",
            rendered_asset_id="asset_measurement",
            views=999_999,
            history_source="post_row_fallback",
            raw={
                "metadata": {
                    "campaign_factory": {
                        "reference_pattern": {"clusterKey": "poison_pattern"},
                        "variationPreset": "ig_bold",
                    }
                }
            },
        )
        cf.conn.commit()

        reference_rankings = cf._ranked_reference_patterns_for_campaign(campaign["id"])
        preset_rankings = cf._ranked_variation_presets_for_campaign(campaign["id"])
        measurement_rows = cf.domains.recommendations.recommendation_performance_rows(
            {"rendered_asset_id": "asset_measurement", "evidence_json": "{}"}
        )
        explicitly_linked_poison = (
            cf.domains.recommendations.recommendation_performance_rows(
                {
                    "rendered_asset_id": None,
                    "evidence_json": json.dumps(
                        {"links": {"performanceSnapshotId": "snap_rec_poison"}}
                    ),
                }
            )
        )

        assert [row["patternId"] for row in reference_rankings] == ["refpat_eligible"]
        assert [row["presetName"] for row in preset_rankings] == ["ig_subtle"]
        assert [row["id"] for row in measurement_rows] == ["snap_rec_eligible"]
        assert explicitly_linked_poison == []
    finally:
        cf.close()


def test_account_memory_excludes_ineligible_accounts(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("learning_memory", "instagram")
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_memory_eligible",
            post_id="post_memory_eligible",
            account="ig_eligible",
        )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_memory_poison",
            post_id="post_memory_poison",
            account="ig_poison",
            lineage_v2_valid=0,
        )
        cf.conn.execute(
            """
            INSERT INTO account_memory (
              id, campaign_id, account_id, platform, sample_size, confidence,
              pattern_stats_json, posting_windows_json, fatigue_json,
              audience_notes_json, recommendation_outcomes_json, updated_at
            ) VALUES (
              'acctmem_stale', ?, 'ig_poison', 'instagram', 99, 'high',
              '[]', '[]', '{}', '{}', '{}', ?
            )
            """,
            (campaign["id"], ELIGIBLE_PUBLISHED_AT),
        )
        cf.conn.commit()

        report = cf.rebuild_account_memory(campaign["slug"])

        assert report["accountCount"] == 1
        assert report["snapshotCount"] == 1
        assert [row["accountId"] for row in report["accounts"]] == ["ig_eligible"]
        assert (
            cf.account_memory(campaign["slug"], account="ig_poison")["accounts"] == []
        )
    finally:
        cf.close()


def test_creative_knowledge_excludes_pre_cutover_rows(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("learning_creative", "instagram")
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_creative_eligible",
            post_id="post_creative_eligible",
            creator_mix="Stacey",
            views=100,
        )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_creative_poison",
            post_id="post_creative_poison",
            creator_mix="Stacey",
            published_at="2026-05-31T00:00:00+00:00",
            views=999_999,
        )
        cf.conn.commit()

        report = cf.creative_knowledge_base(
            creator="Stacey", campaign_slug=campaign["slug"], minimum_sample_size=1
        )

        assert report["insufficientData"] is False
        assert report["sampleSize"] == 1
    finally:
        cf.close()


def test_winner_expansion_excludes_fallback_winners(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("learning_winners", "instagram")
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_winner_eligible",
            post_id="post_winner_eligible",
            views=1_500,
            reach=1_400,
        )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_winner_poison",
            post_id="post_winner_poison",
            views=999_999,
            reach=999_999,
            history_source="post_row_fallback",
        )
        cf.conn.commit()

        report = cf.winner_expansion_report(campaign["slug"], min_views=1_000)

        assert [row["postId"] for row in report["winners"]] == ["post_winner_eligible"]
    finally:
        cf.close()


def test_variant_rollup_excludes_null_published_and_invalid_lineage_rows(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("learning_variants", "instagram")
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_variant_eligible",
            post_id="post_variant_eligible",
            variant_id="variant_eligible",
            variant_family_id="family_eligible",
            parent_reel_id="parent_eligible",
            views=100,
        )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_variant_no_publish",
            post_id="post_variant_no_publish",
            published_at=None,
            variant_id="variant_poison_1",
            views=999_999,
        )
        insert_snapshot(
            cf,
            campaign_id=campaign["id"],
            snapshot_id="snap_variant_bad_lineage",
            post_id="post_variant_bad_lineage",
            lineage_v2_valid=0,
            variant_id="variant_poison_2",
            views=999_999,
        )
        cf.conn.commit()

        report = cf.variant_metrics_rollup(campaign["slug"])

        assert report["summary"]["variantsPosted"] == 1
        assert report["summary"]["totalViews"] == 100
        assert [row["variantId"] for row in report["variants"]] == ["variant_eligible"]
    finally:
        cf.close()
