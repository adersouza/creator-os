from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import campaign_factory.core as core_module
import pytest
from campaign_asset_test_support import (
    add_audit_report,
    add_story_quality_asset,
    add_surface_asset_fixture,
    table_count,
)
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.adapters.threadsdash_draft_payload import build_draft_payloads
from campaign_factory.adapters.threadsdash_draft_readiness import (
    evaluate_export_readiness,
)
from campaign_factory.contracts import validate_recommendation_next_batch
from campaign_factory.core import CampaignFactory
from campaign_learning_test_support import (
    _draft_item,
    _insert_creative_kb_snapshot,
    _manager_report_fixture,
    add_account_requirement_fixture,
)
from campaign_test_support import add_rendered_asset, make_factory


def project_trial_account(
    factory: CampaignFactory,
    external_id: str,
    capability: str,
    *,
    scopes: list[str] | None = None,
    checked_at: str | None = "2026-07-15T04:30:00+00:00",
    reason: str | None = None,
) -> dict[str, Any]:
    if scopes is None:
        scopes = ["instagram_content_publish"]
    account = factory.domains.models.upsert_account(
        f"fixture_{external_id}",
        external_id=external_id,
    )
    observed_at = datetime.now(UTC).isoformat()
    return factory.domains.models.project_instagram_trial_capability(
        account["id"],
        capability=capability,
        oauth_granted_scopes=scopes,
        oauth_scopes_verified_at=(
            "2026-07-15T04:00:00+00:00" if scopes is not None else None
        ),
        checked_at=checked_at,
        reason=reason,
        projection_observed_at=observed_at,
    )


def test_recommend_next_batch_explains_account_audio_caption_decision(tmp_path: Path):
    catalog_path = tmp_path / "audio_memory.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.audio_catalog_export.v1",
                "items": [
                    {
                        "id": "aud_decision",
                        "title": "Mirror Decision Trend",
                        "artistName": "DJ Decision",
                        "platform": "instagram",
                        "nativeAudioId": "ig_decision",
                        "moodTags": ["mirror"],
                        "bestContentTypes": ["v01_original"],
                        "accountFit": ["ig_1"],
                        "trendStatus": "rising",
                        "trendScore": 90,
                        "velocityScore": 80,
                        "creatorFitScore": 91,
                        "usageCount": 10000,
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
        cf.domains.audio_recommendations.import_audio_memory(catalog_path)
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.campaign_overview.assign_asset_account(
            "asset_1", instagram_account_id="ig_1"
        )

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_1", persist=False
        )
        validate_recommendation_next_batch(rec)
        item = rec["items"][0]

        decision = item["decisionEvidence"]
        assert decision["targetAccount"] == "ig_1"
        assert (
            decision["account"]["score"] == item["scoreBreakdown"]["accountFitFatigue"]
        )
        assert decision["account"]["reasons"]
        assert decision["audio"]["status"] == "recommended"
        assert (
            decision["audio"]["primaryAudio"]["audioTitle"] == "Mirror Decision Trend"
        )
        assert decision["audio"]["recommendationCount"] == 1
        assert decision["caption"]["guidance"] == item["captionGuidance"]
        assert (
            decision["caption"]["captionHash"]
            == item["readinessEvidence"]["captionHash"]
        )
        assert decision["caption"]["status"] == "ready"
        assert decision["caption"]["blockingReasons"] == []
        assert decision["readiness"]["verdict"] == "ready"
        assert decision["readiness"]["nextAction"] == "ready_for_operator_export_review"
        assert decision["readiness"]["reviewState"] == "approved"
        assert (
            decision["readiness"]["auditStatus"]
            == item["readinessEvidence"]["auditStatus"]
        )
        assert decision["readiness"]["latestAuditVerdict"] == "pass"
        assert decision["whyNow"]["status"] == "ready"
        assert decision["whyNow"]["nextAction"] == decision["readiness"]["nextAction"]
        assert decision["whyNow"]["reasons"] == item["reasons"]
        assert decision["whyNow"]["risks"] == item["risks"]
        checklist = decision["proofChecklist"]
        assert checklist["accountFit"]["score"] == decision["account"]["score"]
        assert (
            checklist["learning"]["sampleSize"]
            == decision["learning"]["dataQuality"]["sampleSize"]
        )
        assert checklist["audio"]["hasPrimaryAudio"] is True
        assert checklist["caption"]["status"] == "ready"
        assert checklist["quality"]["status"] == "passed"
        assert checklist["variationSafety"]["status"] == "clear"
        assert checklist["readiness"]["status"] == "ready"
        assert item["evidence"]["decision"] == decision
    finally:
        cf.close()


def test_account_memory_rebuild_and_account_fit_recommendations(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        now = "2026-01-02T12:00:00+00:00"
        caption_hash = threadsdash_client_adapter._text_hash("caption")
        raw = {
            "metadata": {
                "campaign_factory": {
                    "hook_key": "curiosity_open_loop",
                    "recipe": "v01_original",
                    "audio_intent": {"recommendations": [{"audioTitle": "Runway Pop"}]},
                    "reference_pattern": {
                        "label": "Mirror Curiosity",
                        "visualFormat": "mirror",
                        "hookType": "curiosity",
                    },
                    "caption_generation": {"captionFormula": "short direct caption"},
                }
            }
        }
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, instagram_account_id,
             snapshot_at, views, likes, comments, shares, saves, reach, metrics_eligible, raw_json, created_at, published_at, history_source, lineage_v2_valid)
            VALUES
            ('perf_account_1', ?, 'asset_1', ?, 'hash_1', ?, ?, 'v01_original', 'post_1', 'instagram',
             'published', 'ig_memory', ?, 5000, 400, 20, 30, 50, 4500, 1, ?, ?, '2026-01-02T00:00:00+00:00', 'metric_history', 1)
            """,
            (
                campaign["id"],
                source["id"],
                source["content_hash"],
                caption_hash,
                now,
                json.dumps(raw),
                now,
            ),
        )
        cf.conn.commit()

        rebuilt = cf.domains.account_memory.rebuild_account_memory("may")
        assert rebuilt["accountCount"] == 1
        memory = cf.domains.account_memory.account_memory("may", account="ig_memory")
        account = memory["accounts"][0]
        assert account["accountId"] == "ig_memory"
        assert account["sampleSize"] == 1
        assert account["confidence"] == "low"
        assert account["patternStats"]

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_memory", persist=True
        )
        item = rec["items"][0]
        assert item["accountMemory"]["accountId"] == "ig_memory"
        assert item["accountFitEvidence"]["score"] is not None
        assert item["autonomyLevel"] == "level_2"
    finally:
        cf.close()


def test_recommend_next_batch_uses_requested_account_fit_before_slicing_candidates(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        rendered_path = tmp_path / "asset_2.mp4"
        rendered_path.write_bytes(b"rendered-2")
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
             caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
             caption_generation_json, metadata_json, created_at, updated_at)
            VALUES ('asset_2', ?, ?, 'hash_2', ?, ?, 'asset_2.mp4', 'caption', 'caption_hash_2',
                    ?, 'v01_original', 'passed', 'approved', ?, '{}',
                    '2025-12-31T00:00:00+00:00', '2025-12-31T00:00:00+00:00')
            """,
            (
                campaign["id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps(
                    {**context, "caption_hash": "caption_hash_2"}, sort_keys=True
                ),
                json.dumps(
                    {
                        "instagram_post_caption": "new post",
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
        add_audit_report(cf, rendered_asset_id="asset_2", audit_id="audit_asset_2")
        cf.domains.campaign_overview.assign_asset_account(
            "asset_1", instagram_account_id="ig_other"
        )
        cf.domains.campaign_overview.assign_asset_account(
            "asset_2", instagram_account_id="ig_target"
        )

        rec = cf.domains.recommendations.recommend_next_batch(
            "may", count=1, account="ig_target", persist=False
        )
        item = rec["items"][0]

        assert item["renderedAssetId"] == "asset_2"
        assert item["targetAccount"] == "ig_target"
        assert item["accountFitEvidence"]["account"] == "ig_target"
        assert item["scoreBreakdown"]["accountFitFatigue"] > 50
    finally:
        cf.close()


def test_attach_audio_to_distribution_plan_marks_campaign_audio_attached_and_exports_metadata(
    tmp_path: Path, monkeypatch
):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
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
                            "status": "needs_operator_selection",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_stacey_1",
            planned_window_start="2026-06-05T15:00:00+00:00",
            planned_window_end="2026-06-05T15:15:00+00:00",
        )

        result = cf.domains.audio_operations.attach_audio_to_distribution_plan(
            plan["id"],
            track_id="ig_audio_123",
            track_name="Proof track",
            source="manual",
            selected_reason="operator_selected_for_proof",
            operator="tester",
        )
        payload = build_draft_payloads(
            cf, campaign_slug="may", user_id="user_1", schedule_mode="live"
        )
        draft_intent = payload["drafts"][0]["metadata"]["campaign_factory"][
            "audio_intent"
        ]
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
        assert (
            result["audioIntent"]["operator_selection"]["audio_title"] == "Proof track"
        )
        assert (
            result["audioIntent"]["operator_selection"]["selection_source"] == "manual"
        )
        assert (
            result["audioIntent"]["operator_selection"]["selected_reason"]
            == "operator_selected_for_proof"
        )
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
        assert (
            draft_intent["operator_selection"]["selected_reason"]
            == "operator_selected_for_proof"
        )
        assert readiness["liveExportAllowed"] is True
        assert not any(
            "campaign_audio_unresolved" in reason
            for reason in readiness["blockingReasons"]
        )
    finally:
        cf.close()


def test_regular_reel_manifest_defaults_instagram_trial_reels_false(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", surface="regular_reel", instagram_account_id="ig_good"
        )
        explanation = cf.domains.publishability.explain_publishability(
            "asset_1", distribution_plan_id=plan["id"]
        )

        manifest = explanation["handoff_manifest"]
        assert plan["instagramTrialReels"] is False
        assert plan["trialGraduationStrategy"] is None
        assert manifest["instagram_trial_reels"] is False
        assert manifest["trial_graduation_strategy"] is None
    finally:
        cf.close()


def test_trial_surface_requires_explicit_instagram_trial_reel_intent(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(
            cf, tmp_path, campaign_slug="stacey_variant_fanout_proof_trial_20260606"
        )
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        with pytest.raises(
            ValueError,
            match="trial_reel surface requires instagram_trial_reels=true",
        ):
            cf.domains.distribution.create_distribution_plan(
                "asset_1", surface="trial_reel", instagram_account_id="ig_good"
            )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM distribution_plans").fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_instagram_trial_reel_intent_requires_trial_surface(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        with pytest.raises(
            ValueError,
            match="instagram_trial_reels=true requires trial_reel surface",
        ):
            cf.domains.distribution.create_distribution_plan(
                "asset_1",
                surface="regular_reel",
                instagram_account_id="ig_good",
                instagram_trial_reels=True,
                trial_graduation_strategy="MANUAL",
            )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM distribution_plans").fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_explicit_instagram_trial_reel_manifest_includes_trial_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        project_trial_account(
            cf,
            "ig_good",
            "eligible",
            scopes=["instagram_basic", "instagram_content_publish"],
            reason="meta_trial_reel_publish_succeeded",
        )

        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1",
            surface="trial_reel",
            instagram_account_id="ig_good",
            instagram_trial_reels=True,
            trial_graduation_strategy="MANUAL",
            trial_group_id="trial_group_test",
        )
        explanation = cf.domains.publishability.explain_publishability(
            "asset_1", distribution_plan_id=plan["id"]
        )

        manifest = explanation["handoff_manifest"]
        assert plan["contentSurface"] == "reel"
        assert plan["instagramTrialReels"] is True
        assert plan["trialGraduationStrategy"] == "MANUAL"
        assert plan["trialCapability"] == {
            "status": "eligible",
            "checkedAt": "2026-07-15T04:30:00+00:00",
            "reason": "meta_trial_reel_publish_succeeded",
            "authorization": None,
        }
        assert manifest["content_surface"] == "reel"
        assert manifest["distribution_surface"] == "trial_reel"
        assert manifest["ig_media_type"] == "REELS"
        assert manifest["instagram_trial_reels"] is True
        assert manifest["trial_graduation_strategy"] == "MANUAL"
        draft = build_draft_payloads(
            cf,
            campaign_slug="may",
            user_id="user_1",
            surface="trial_reel",
        )["drafts"][0]
        assert draft["instagramTrialReels"] is True
        assert draft["shareToFeed"] is False
        assert draft["metadata"]["shareToFeed"] is False
        assert draft["metadata"]["trialGroupId"] == "trial_group_test"
        assert draft["metadata"]["campaign_factory"]["share_to_feed"] is False
    finally:
        cf.close()


def test_regular_reel_export_isolated_from_ineligible_trial_destination(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.distribution.create_distribution_plan(
            "asset_1",
            surface="regular_reel",
            instagram_account_id="ig_regular",
        )
        project_trial_account(
            cf,
            "ig_trial",
            "unknown",
            scopes=[],
            checked_at=None,
        )
        campaign = cf.domains.campaign_by_slug("may")
        cf.conn.execute(
            """
            INSERT INTO distribution_plans
            (id, campaign_id, rendered_asset_id, instagram_account_id,
             surface, content_surface, instagram_trial_reels,
             trial_graduation_strategy, created_at, updated_at)
            VALUES ('dist_trial_stale', ?, 'asset_1', 'ig_trial',
                    'trial_reel', 'reel', 1, 'MANUAL', ?, ?)
            """,
            (campaign["id"], "2026-07-15T04:30:00+00:00", "2026-07-15T04:30:00+00:00"),
        )
        cf.conn.commit()

        regular = build_draft_payloads(
            cf,
            campaign_slug="may",
            user_id="user_1",
            surface="regular_reel",
        )
        assert len(regular["drafts"]) == 1
        assert regular["drafts"][0]["distributionSurface"] == "regular_reel"
        assert regular["drafts"][0]["instagramTrialReels"] is False

        with pytest.raises(ValueError, match="trial_publish_scope_missing"):
            build_draft_payloads(
                cf,
                campaign_slug="may",
                user_id="user_1",
                surface="trial_reel",
            )
    finally:
        cf.close()


def test_unknown_trial_capability_requires_operator_canary(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        project_trial_account(cf, "ig_unknown", "unknown", checked_at=None)

        with pytest.raises(
            ValueError,
            match="trial_capability_unknown_requires_operator_canary",
        ):
            cf.domains.distribution.create_distribution_plan(
                "asset_1",
                surface="trial_reel",
                instagram_account_id="ig_unknown",
                instagram_trial_reels=True,
                trial_graduation_strategy="MANUAL",
            )

        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1",
            surface="trial_reel",
            instagram_account_id="ig_unknown",
            instagram_trial_reels=True,
            trial_graduation_strategy="MANUAL",
            trial_capability_authorization="operator_canary",
        )

        assert plan["trialCapability"] == {
            "status": "unknown",
            "checkedAt": None,
            "reason": None,
            "authorization": "operator_canary",
        }
    finally:
        cf.close()


def test_denied_trial_capability_blocks_operator_canary(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        project_trial_account(
            cf,
            "ig_denied",
            "denied",
            reason="meta_permission_or_eligibility_denied:code_10:subcode_none",
        )

        with pytest.raises(ValueError, match="trial_capability_denied"):
            cf.domains.distribution.create_distribution_plan(
                "asset_1",
                surface="trial_reel",
                instagram_account_id="ig_denied",
                instagram_trial_reels=True,
                trial_graduation_strategy="MANUAL",
                trial_capability_authorization="operator_canary",
            )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM distribution_plans").fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_known_missing_trial_publish_scope_blocks_operator_canary(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        project_trial_account(
            cf,
            "ig_missing_scope",
            "unknown",
            scopes=["instagram_basic"],
            checked_at=None,
        )

        with pytest.raises(ValueError, match="trial_publish_scope_missing"):
            cf.domains.distribution.create_distribution_plan(
                "asset_1",
                surface="trial_reel",
                instagram_account_id="ig_missing_scope",
                instagram_trial_reels=True,
                trial_graduation_strategy="MANUAL",
                trial_capability_authorization="operator_canary",
            )
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

        with pytest.raises(
            ValueError, match="Instagram Trial Reels require reel content"
        ):
            cf.domains.distribution.create_distribution_plan(
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
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        with pytest.raises(
            ValueError, match="trial_graduation_strategy must be one of"
        ):
            cf.domains.distribution.create_distribution_plan(
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
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
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
                    json.dumps(
                        {
                            "schema": "campaign_factory.caption_outcome_context.v1",
                            "caption_hash": f"caption_hash_{i}",
                            "caption_text": f"caption {i}",
                            "instagram_post_caption": f"new post {i}",
                            "instagram_post_caption_hash": threadsdash_client_adapter._text_hash(
                                f"new post {i}"
                            ),
                            "caption_bank": "test_bank",
                            "caption_banks": ["test_bank"],
                            "creator_mix": "Test",
                            "render_recipe": "v01_original",
                            "captionPlacementPolicy": "focal_safe_v1",
                            "captionPlacementDecision": {
                                "status": "passed",
                                "selectedLane": "top",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "instagram_post_caption": f"new post {i}",
                            "audioIntent": {
                                "schema": "pipeline.audio_intent.v1",
                                "mode": "native_platform_audio",
                                "required": False,
                                "status": "not_required",
                            },
                        }
                    ),
                    now,
                    now,
                ),
            )
            add_audit_report(cf, rendered_asset_id=f"asset_{i}", audit_id=f"audit_{i}")
        cf.conn.commit()
        cf.domains.models.upsert_model_account_profile(
            "model",
            allowed_instagram_account_ids=["ig_1", "ig_2", "ig_3", "ig_4", "ig_5"],
            story_cta_text="new post is up",
        )
        project_trial_account(cf, "ig_1", "eligible")
        project_trial_account(cf, "ig_2", "denied", reason="Meta code 10")
        project_trial_account(cf, "ig_3", "unknown", checked_at=None)
        project_trial_account(cf, "ig_4", "eligible")
        project_trial_account(cf, "ig_5", "eligible")

        result = cf.domains.distribution.plan_distribution("may", user_id="user_1")
        plans = cf.domains.distribution.distribution_plans_for_campaign("may")
        primary = [plan for plan in plans if plan["surface"] != "story_cta"]
        stories = [plan for plan in plans if plan["surface"] == "story_cta"]

        assert result["surfaceCounts"]["regular_reel"] == 1
        assert result["surfaceCounts"]["trial_reel"] == 3
        assert result["unplannedCount"] == 1
        assert len(primary) == 4
        assert len(stories) == 4
        assert all(plan["plannedWindowStart"] for plan in primary)
        assert all(
            plan["instagramAccountId"] in {"ig_1", "ig_2", "ig_3", "ig_4", "ig_5"}
            for plan in primary
        )
        assert {
            plan["instagramAccountId"]
            for plan in primary
            if plan["surface"] == "trial_reel"
        }.isdisjoint({"ig_2", "ig_3"})

        unplanned_id = result["unplanned"][0]["renderedAssetId"]
        cf.domains.campaign_overview.assign_asset_account(
            unplanned_id, instagram_account_id="ig_5"
        )
        payload = build_draft_payloads(
            cf, campaign_slug="may", user_id="user_1", schedule_mode="preview"
        )
        assert len(payload["drafts"]) == len(plans)
        assert unplanned_id not in {
            draft["renderedAssetId"] for draft in payload["drafts"]
        }
    finally:
        cf.close()


def test_plan_distribution_empty_history_uses_first_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.models.upsert_model_account_profile(
            "model", allowed_instagram_account_ids=["ig_1"]
        )
        first_slot = datetime(2026, 1, 2, 10, tzinfo=UTC)
        monkeypatch.setattr(
            cf.domains.distribution,
            "distribution_slots",
            lambda _hours, _count: [
                first_slot,
                first_slot + timedelta(hours=4),
            ],
        )

        result = cf.domains.distribution.plan_distribution(
            "may", user_id="user_1", replace=False
        )

        assert result["planned"][0]["plannedWindowStart"] == first_slot.isoformat()
    finally:
        cf.close()


def test_plan_distribution_hydrates_account_day_counts_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.models.upsert_model_account_profile(
            "model", allowed_instagram_account_ids=["ig_1"]
        )
        day_one = datetime(2026, 1, 2, 10, tzinfo=UTC)
        monkeypatch.setattr(
            cf.domains.distribution,
            "distribution_slots",
            lambda _hours, _count: [
                day_one,
                day_one + timedelta(hours=4),
                day_one + timedelta(days=1),
            ],
        )

        first = cf.domains.distribution.plan_distribution(
            "may", user_id="user_1", replace=False
        )
        second = cf.domains.distribution.plan_distribution(
            "may", user_id="user_1", replace=False
        )

        assert first["planned"][0]["plannedWindowStart"] == day_one.isoformat()
        assert (
            second["planned"][0]["plannedWindowStart"]
            == (day_one + timedelta(days=1)).isoformat()
        )
    finally:
        cf.close()


def test_plan_distribution_hydrates_min_gap_from_existing_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.models.upsert_model_account_profile(
            "model", allowed_instagram_account_ids=["ig_1"]
        )
        existing = datetime(2026, 1, 1, 23, tzinfo=UTC)
        too_close = existing + timedelta(hours=3)
        valid = existing + timedelta(hours=5)
        cf.domains.distribution.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_1",
            planned_window_start=existing.isoformat(),
        )
        monkeypatch.setattr(
            cf.domains.distribution,
            "distribution_slots",
            lambda _hours, _count: [too_close, valid],
        )

        result = cf.domains.distribution.plan_distribution(
            "may", user_id="user_1", replace=False
        )

        assert result["planned"][0]["plannedWindowStart"] == valid.isoformat()
    finally:
        cf.close()


def test_plan_distribution_hydrates_window_from_max_min_gap_hours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        model = cf.domains.models.upsert_model("model", name="Model")
        account = cf.domains.models.upsert_account(
            "ig_1",
            platform="instagram",
            external_id="ig_1",
            model_id=model["id"],
        )
        cf.domains.models.upsert_model_account_profile(
            "model", allowed_instagram_account_ids=["ig_1"]
        )
        cf.conn.execute(
            """
            INSERT INTO account_content_requirements
            (id, account_id, creator, content_surface, cadence, max_per_day,
             min_gap_hours, allowed_days, active, created_at, updated_at)
            VALUES ('req_ig_1_gap_6', ?, 'Model', 'reel', 'daily', 3, 6,
                    '[]', 1, '2026-01-01T00:00:00+00:00',
                    '2026-01-01T00:00:00+00:00')
            """,
            (account["id"],),
        )
        existing = datetime(2026, 1, 1, 23, tzinfo=UTC)
        too_close = existing + timedelta(hours=5)
        valid = existing + timedelta(hours=7)
        cf.domains.distribution.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_1",
            planned_window_start=existing.isoformat(),
        )
        monkeypatch.setattr(
            cf.domains.distribution,
            "distribution_slots",
            lambda _hours, _count: [too_close, valid],
        )

        result = cf.domains.distribution.plan_distribution(
            "may", user_id="user_1", replace=False
        )

        assert result["planned"][0]["plannedWindowStart"] == valid.isoformat()
    finally:
        cf.close()


def test_next_distribution_slot_uses_account_requirement_cap_and_gap(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_main",
            platform="instagram",
            external_id="ig_1",
            model_id=model["id"],
        )
        cf.conn.execute(
            """
            INSERT INTO account_content_requirements
            (id, account_id, creator, content_surface, cadence, max_per_day,
             min_gap_hours, allowed_days, active, created_at, updated_at)
            VALUES ('req_stacey_reel', ?, 'Stacey', 'reel', 'daily', 2, 2,
                    '[]', 1, '2026-01-01T00:00:00+00:00',
                    '2026-01-01T00:00:00+00:00')
            """,
            (account["id"],),
        )
        slots = [
            datetime(2026, 1, 2, 10, tzinfo=UTC),
            datetime(2026, 1, 2, 11, tzinfo=UTC),
            datetime(2026, 1, 2, 12, tzinfo=UTC),
        ]
        day_counts: dict[tuple[str, str], int] = {}
        slot_times: dict[str, list[datetime]] = {}
        caption_counts: dict[tuple[str, str], int] = {}
        source_counts: dict[tuple[str, str], int] = {}
        warnings: list[dict[str, Any]] = []

        first, index = cf.domains.distribution.next_valid_distribution_slot(
            slots,
            0,
            "ig_1",
            {"id": "asset_1", "caption_hash": "caption_1", "source_asset_id": "src_1"},
            day_counts,
            slot_times,
            caption_counts,
            source_counts,
            warnings,
        )
        second, _ = cf.domains.distribution.next_valid_distribution_slot(
            slots,
            index,
            "ig_1",
            {"id": "asset_2", "caption_hash": "caption_2", "source_asset_id": "src_2"},
            day_counts,
            slot_times,
            caption_counts,
            source_counts,
            warnings,
        )

        assert first == slots[0]
        assert second == slots[2]
    finally:
        cf.close()


def test_model_account_profile_blocks_wrong_model_account(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.models.upsert_model_account_profile(
            "model", allowed_instagram_account_ids=["ig_good"]
        )
        cf.domains.campaign_overview.assign_asset_account(
            "asset_1", instagram_account_id="ig_wrong"
        )

        readiness = evaluate_export_readiness(cf, campaign_slug="may", user_id="user_1")
        row = readiness["assets"][0]
        plan = cf.domains.account_planning.account_plan("may", user_id="user_1")

        assert "model_account_mismatch" in row["blockingReasons"]
        assert "asset_1:model_account_mismatch" in readiness["blockingReasons"]
        assert "model_account_mismatch" in plan["rows"][0]["warnings"]
    finally:
        cf.close()


def test_account_surface_obligations_plan_is_read_only_and_surface_specific(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        campaign = cf.domains.models.upsert_campaign(
            "stacey_surface_inventory_20260606", "stacey"
        )
        account = cf.domains.models.upsert_account(
            "stacey_main",
            platform="instagram",
            external_id="ig_stacey_1",
            model_id=model["id"],
        )
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

        plan = cf.domains.surface_requirements.account_surface_obligations_plan(
            creator="Stacey", date="2026-06-06"
        )

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


def test_account_content_needs_counts_required_completed_scheduled_remaining(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_account_12",
            platform="instagram",
            external_id="ig_stacey_12",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf, account_id=account["id"], surface="reel", max_per_day=1
        )
        add_account_requirement_fixture(
            cf, account_id=account["id"], surface="story", max_per_day=3
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_scheduled",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        campaign = cf.domains.campaign_by_slug("stacey_surface_inventory_20260606")
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

        report = cf.domains.surface_requirements.account_content_needs(
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
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_story_account",
            platform="instagram",
            external_id="ig_story",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf, account_id=account["id"], surface="story", cadence="3_per_day"
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.domains.surface_requirements.account_content_needs(
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


def test_account_surface_status_reports_needed_scheduled_completed_blocked_overdue(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_status_account",
            platform="instagram",
            external_id="ig_status",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf,
            account_id=account["id"],
            surface="feed_carousel",
            cadence="weekly",
            max_per_day=1,
            allowed_days=[5],
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.domains.surface_requirements.account_surface_status(
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
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account_a = cf.domains.models.upsert_account(
            "stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"]
        )
        account_b = cf.domains.models.upsert_account(
            "stacey_b", platform="instagram", external_id="ig_b", model_id=model["id"]
        )
        add_account_requirement_fixture(
            cf, account_id=account_a["id"], surface="story", max_per_day=3
        )
        add_account_requirement_fixture(
            cf, account_id=account_a["id"], surface="reel", max_per_day=1
        )
        add_account_requirement_fixture(
            cf,
            account_id=account_b["id"],
            surface="feed_carousel",
            cadence="weekly",
            max_per_day=1,
            allowed_days=[5],
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.domains.surface_requirements.creator_content_needs(
            creator="Stacey", date="2026-06-06"
        )

        assert report["accountsAnalyzed"] == 2
        assert report["surfaceRequirementsTracked"] == [
            "reel",
            "story",
            "feed_single",
            "feed_carousel",
        ]
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
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account_a = cf.domains.models.upsert_account(
            "stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"]
        )
        account_b = cf.domains.models.upsert_account(
            "stacey_b", platform="instagram", external_id="ig_b", model_id=model["id"]
        )
        add_account_requirement_fixture(
            cf, account_id=account_a["id"], surface="story", max_per_day=2
        )
        add_account_requirement_fixture(
            cf, account_id=account_b["id"], surface="story", max_per_day=1
        )
        add_account_requirement_fixture(
            cf,
            account_id=account_b["id"],
            surface="feed_carousel",
            cadence="weekly",
            max_per_day=1,
            allowed_days=[5],
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_gap",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.domains.surface_requirements.surface_gap_report(
            creator="Stacey", date="2026-06-06"
        )

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


def test_creator_os_daily_plan_recommends_story_intent_and_style(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_story",
            platform="instagram",
            external_id="ig_story",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf,
            account_id=account["id"],
            surface="story",
            cadence="daily",
            max_per_day=1,
        )
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_snap")
        cf.conn.execute(
            "UPDATE rendered_assets SET story_intent = 'snapchat_promo', story_style = 'casual' WHERE id = 'asset_story_snap'"
        )
        cf.conn.commit()

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            date="2026-06-06",
            threadsdash_report=_manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_story",
                        "username": "stacey_story",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": False,
                    }
                ]
            ),
            schedule_plan={"creator": "Stacey", "items": []},
        )

        stacey = plan["creators"][0]
        assert stacey["accountsNeedingStories"] == 1
        assert stacey["recommendedStoryIntent"] == "snapchat_promo"
        assert stacey["recommendedStoryStyle"] == "casual_selfie"
        assert stacey["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_is_read_only_and_detects_inventory_shortfall(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        before = cf.conn.total_changes
        accounts = [
            {
                "accountId": "ig_1",
                "username": "stacey_one",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
            {
                "accountId": "ig_2",
                "username": "stacey_two",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 1,
                "items": [_draft_item("post_1", "ig_1")],
            },
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


def test_creator_os_daily_plan_excludes_blocked_and_already_scheduled_accounts(
    tmp_path: Path,
):
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
            },
            {
                "accountId": "ig_scheduled",
                "username": "scheduled",
                "creator": "Stacey",
                "bucket": "already_scheduled_today",
                "safeToSchedule": False,
                "needsPostToday": False,
                "nextScheduledPost": {"id": "post_s"},
            },
            {
                "accountId": "ig_blocked",
                "username": "blocked",
                "creator": "Stacey",
                "bucket": "blocked_reauth",
                "safeToSchedule": False,
                "needsPostToday": False,
                "blockingReason": "needs_reauth",
            },
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 1,
                "items": [_draft_item("post_1", "ig_safe")],
            },
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


def test_creator_os_daily_plan_respects_variant_cooldowns_and_missed_dispatches(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_cool",
                "username": "cool",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
            {
                "accountId": "ig_missed",
                "username": "missed",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
        ]
        missed = [
            {
                "postId": "post_missed",
                "accountId": "ig_missed",
                "blockingReason": "overdue_dispatch_no_publish_attempt",
            }
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(
                accounts=accounts, missed=missed
            ),
            time_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 2,
                "items": [
                    _draft_item(
                        "post_cool",
                        "ig_cool",
                        variant_family_id="vfam_1",
                        variant_id="var_1",
                        cooldown="same_variant_family_within_14_days",
                    ),
                    _draft_item("post_missed", "ig_missed"),
                ],
            },
        )

        by_id = {row["accountId"]: row for row in plan["accounts"]}
        assert by_id["ig_cool"]["eligibleDrafts"] == []
        assert by_id["ig_cool"]["variantCooldowns"][0]["variantFamilyId"] == "vfam_1"
        assert (
            by_id["ig_cool"]["variantCooldowns"][0]["reason"]
            == "same_variant_family_within_14_days"
        )
        assert by_id["ig_missed"]["state"] == "blocked"
        assert (
            by_id["ig_missed"]["blockedReason"] == "overdue_dispatch_no_publish_attempt"
        )
        assert by_id["ig_missed"]["needsPostToday"] is False
        assert (
            "resolve_missed_dispatches_before_scheduling"
            in plan["creators"][0]["recommendedActions"]
        )
    finally:
        cf.close()


def test_creator_os_daily_plan_consumes_winner_expansion_report(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        accounts = [
            {
                "accountId": f"ig_{idx}",
                "username": f"stacey_{idx}",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            }
            for idx in range(1, 4)
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 1,
                "items": [_draft_item("post_1", "ig_1")],
            },
            winner_expansion_report={
                "schema": "campaign_factory.winner_expansion_report.v1",
                "recommendations": [
                    {
                        "creator": "Stacey",
                        "assetId": "asset_parent",
                        "variantFamilyId": "vfam_hot",
                        "reason": "high_views",
                        "recommendedAction": "create_more_variants",
                        "wouldWrite": False,
                    }
                ],
            },
        )

        stacey = plan["creators"][0]
        assert cf.conn.total_changes == before
        assert stacey["managerDecision"] == "needs_variants"
        assert stacey["inventoryShortfall"] == 2
        assert stacey["winnerExpansionRecommendations"] == [
            {
                "parentAssetId": "asset_parent",
                "variantFamilyId": "vfam_hot",
                "reason": "high_views",
                "recommendedAction": "generate_more_variants",
                "recommendedVariantCount": 2,
                "wouldWrite": False,
            }
        ]
        assert "run_contentforge_variant_plan" in stacey["nextSafeActions"]
        assert (
            "run_campaign_schedule_time_plan_then_campaign_schedule"
            not in stacey["nextSafeActions"]
        )
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_includes_creative_recommended_inventory(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("stacey_daily_learning", "stacey")
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

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_daily_learning",
                        "username": "stacey",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": True,
                    },
                ]
            ),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 0,
                "items": [],
            },
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


def test_recommended_inventory_request_plan_translates_daily_plan_into_read_only_batches(
    tmp_path: Path,
):
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
                    "operationFamilies": [
                        "cover_frame",
                        "timing_trim",
                        "crop_zoom_family",
                    ],
                }
            ],
            "estimatedRecommendedVariants": 6,
            "wouldWrite": False,
        }

        plan = (
            cf.domains.recommended_inventory_request.recommended_inventory_request_plan(
                creator="Stacey",
                target_count=10,
                daily_plan=daily_plan,
                variant_inventory_plan=inventory_plan,
            )
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
        assert (
            first["reason"]
            == "mirror_selfie is 42.0% above creator baseline using Instagram-visible metrics."
        )
        assert first["sourceSystem"] == "campaign_factory.creative_performance_analysis"
        assert first["wouldWrite"] is False
        story = [item for item in plan["requestBatches"] if item["surface"] == "story"][
            0
        ]
        assert story["recommendedAction"] == "create_more_snapchat_promo_stories"
        assert story["storyIntent"] == "snapchat_promo"
        assert story["targetCount"] == 4
        assert plan["canSatisfyFromExistingInventory"] is False
        assert plan["nextSafeAction"] == "review_and_approve_inventory_requests"
    finally:
        cf.close()


def test_creator_os_daily_plan_prefers_existing_unused_variants_before_generation(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": f"ig_{idx}",
                "username": f"stacey_{idx}",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            }
            for idx in range(1, 5)
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 2,
                "items": [
                    _draft_item(
                        "post_var_1",
                        "ig_1",
                        variant_family_id="vfam_existing",
                        variant_id="var_existing_1",
                    ),
                    _draft_item(
                        "post_var_2",
                        "ig_2",
                        variant_family_id="vfam_existing",
                        variant_id="var_existing_2",
                    ),
                ],
            },
            winner_expansion_report={
                "schema": "campaign_factory.winner_expansion_report.v1",
                "recommendations": [
                    {
                        "creator": "Stacey",
                        "assetId": "asset_winner",
                        "variantFamilyId": "vfam_winner",
                        "reason": "high_reach",
                        "recommendedAction": "create_more_variants",
                    }
                ],
            },
        )

        recs = plan["creators"][0]["winnerExpansionRecommendations"]
        assert recs[0]["recommendedAction"] == "fanout_existing_variants"
        assert recs[0]["recommendedVariantCount"] == 2
        assert len(recs) == 1
        assert plan["creators"][0]["managerDecision"] == "needs_variants"
    finally:
        cf.close()


def test_creator_os_daily_plan_without_winners_falls_back_to_reel_factory_inventory(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_1",
                "username": "stacey_one",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
            {
                "accountId": "ig_2",
                "username": "stacey_two",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 0,
                "items": [],
            },
        )

        stacey = plan["creators"][0]
        assert stacey["managerDecision"] == "needs_reel_factory_inventory"
        assert stacey["winnerExpansionRecommendations"] == []
        assert "create_reel_factory_or_source_inventory" in stacey["nextSafeActions"]
        assert (
            "run_campaign_schedule_time_plan_then_campaign_schedule"
            not in stacey["nextSafeActions"]
        )
    finally:
        cf.close()


def test_creator_os_daily_plan_includes_account_tiers(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_warming",
                "username": "warming",
                "creator": "Stacey",
                "accountState": "warming",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
            {
                "accountId": "ig_normal",
                "username": "normal",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
            {
                "accountId": "ig_growth",
                "username": "growth",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "performance": {"views7d": 900, "posts7d": 5},
            },
            {
                "accountId": "ig_winner",
                "username": "winner",
                "creator": "Stacey",
                "accountState": "high-performing",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
            {
                "accountId": "ig_resting",
                "username": "resting",
                "creator": "Stacey",
                "accountState": "resting",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": False,
            },
            {
                "accountId": "ig_blocked",
                "username": "blocked",
                "creator": "Stacey",
                "bucket": "blocked_reauth",
                "safeToSchedule": False,
                "needsPostToday": False,
                "blockingReason": "needs_reauth",
            },
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
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
        assert (
            by_id["ig_winner"]["tierPostingGuidance"]["priority"]
            == "prioritize_winning_concepts"
        )
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
            {
                "accountId": "ig_winner",
                "username": "winner",
                "creator": "Stacey",
                "safeToSchedule": True,
                "accountTier": "winner",
            },
            {
                "accountId": "ig_blocked",
                "username": "blocked",
                "creator": "Stacey",
                "safeToSchedule": False,
                "blockingReason": "token_expired",
            },
        ]
        before = cf.conn.total_changes

        report = cf.domains.account_health.creator_os_account_tiers(
            creator="Stacey",
            threadsdash_report=_manager_report_fixture(accounts=accounts),
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.account_tiers.v1"
        assert report["tierSummary"]["winner"] == 1
        assert report["tierSummary"]["blocked"] == 1
        assert report["accounts"][0]["tier"] == "winner"
        assert (
            report["accounts"][0]["postingGuidance"]["priority"]
            == "prioritize_winning_concepts"
        )
        assert report["accounts"][1]["tier"] == "blocked"
        assert report["accounts"][1]["postingGuidance"]["recommendedPostCount"] == 0
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_account_health_report_blocks_restricted_and_not_recommended_accounts(
    tmp_path: Path,
):
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

        report = cf.domains.account_health.creator_os_account_health_report(
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
        assert (
            report["summary"]["recommendationEligibilitySummary"]["not_recommended"]
            == 1
        )
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_account_health_report_uses_conservative_unknown_recommendation_defaults(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_unknown",
                "username": "unknown",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "accountAgeDays": 1,
            }
        ]

        report = cf.domains.account_health.creator_os_account_health_report(
            creator="Stacey",
            threadsdash_report=_manager_report_fixture(accounts=accounts),
        )

        account = report["accounts"][0]
        assert account["recommendationEligibilityState"] == "unknown"
        assert (
            "recommendation_eligibility_unknown_conservative_cadence"
            in account["warnings"]
        )
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
        schedule_plan = {
            "schema": "threadsdashboard.campaign_schedule_plan.v1",
            "status": "ready",
            "items": [draft],
        }
        time_plan = {
            "schema": "threadsdashboard.campaign_schedule_time_plan.v1",
            "status": "ready",
            "items": [draft],
        }

        readiness = cf.domains.execution_readiness.creator_os_execution_readiness(
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
        schedule_plan = {
            "schema": "threadsdashboard.campaign_schedule_plan.v1",
            "status": "ready",
            "items": [draft],
        }
        time_plan = {
            "schema": "threadsdashboard.campaign_schedule_time_plan.v1",
            "status": "ready",
            "items": [draft],
        }

        readiness = cf.domains.execution_readiness.creator_os_execution_readiness(
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


def test_creator_os_account_health_filtered_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_link",
                "username": "link",
                "creator": "Stacey",
                "linkSharingRestricted": True,
            },
            {
                "accountId": "ig_manual",
                "username": "manual",
                "creator": "Stacey",
                "accountTrustState": "manual_review_required",
            },
            {
                "accountId": "ig_warm",
                "username": "warm",
                "creator": "Stacey",
                "accountAgeDays": 2,
            },
        ]
        threadsdash_report = _manager_report_fixture(accounts=accounts)
        before = cf.conn.total_changes

        restricted = cf.domains.account_health.creator_os_restricted_account_report(
            creator="Stacey", threadsdash_report=threadsdash_report
        )
        manual = cf.domains.account_health.creator_os_manual_review_queue(
            creator="Stacey", threadsdash_report=threadsdash_report
        )
        warmup = cf.domains.account_health.creator_os_account_warmup_report(
            creator="Stacey", threadsdash_report=threadsdash_report
        )

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
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account_a = cf.domains.models.upsert_account(
            "stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"]
        )
        account_b = cf.domains.models.upsert_account(
            "stacey_b", platform="instagram", external_id="ig_b", model_id=model["id"]
        )
        add_account_requirement_fixture(
            cf, account_id=account_a["id"], surface="reel", max_per_day=1
        )
        add_account_requirement_fixture(
            cf, account_id=account_a["id"], surface="story", max_per_day=2
        )
        add_account_requirement_fixture(
            cf, account_id=account_b["id"], surface="feed_single", max_per_day=1
        )
        add_account_requirement_fixture(
            cf,
            account_id=account_b["id"],
            surface="feed_carousel",
            cadence="weekly",
            max_per_day=1,
            allowed_days=[5],
        )
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
            asset_id="asset_single_safe",
            content_surface="feed_single",
            media_type="image",
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            date="2026-06-06",
            threadsdash_report=_manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_a",
                        "username": "stacey_a",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": True,
                    },
                    {
                        "accountId": "ig_b",
                        "username": "stacey_b",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": True,
                    },
                ]
            ),
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


def test_creator_os_surface_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"]
        )
        add_account_requirement_fixture(
            cf, account_id=account["id"], surface="story", max_per_day=2
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_safe",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        creator_summary = cf.domains.surface_summary.creator_surface_summary(
            creator="Stacey", date="2026-06-06"
        )
        account_summary = cf.domains.surface_summary.account_surface_summary(
            creator="Stacey", date="2026-06-06"
        )
        gap = cf.domains.surface_summary.creator_surface_gap_report(
            creator="Stacey", date="2026-06-06"
        )

        assert cf.conn.total_changes == before
        assert creator_summary["schema"] == "creator_os.creator_surface_summary.v1"
        assert creator_summary["surfaceInventory"]["story"]["scheduleSafe"] == 1
        assert account_summary["schema"] == "creator_os.account_surface_summary.v1"
        assert (
            account_summary["accounts"][0]["surfaceStatus"]["story"]["needed"] is True
        )
        assert gap["schema"] == "creator_os.creator_surface_gap_report.v1"
        assert gap["surfaceGaps"]["story"]["needed"] == 2
        assert gap["surfaceGaps"]["story"]["available"] == 1
        assert gap["wouldWrite"] is False
    finally:
        cf.close()


def test_story_reports_handle_daily_and_multi_story_cadence(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account_a = cf.domains.models.upsert_account(
            "stacey_daily",
            platform="instagram",
            external_id="ig_daily",
            model_id=model["id"],
        )
        account_b = cf.domains.models.upsert_account(
            "stacey_multi",
            platform="instagram",
            external_id="ig_multi",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf,
            account_id=account_a["id"],
            surface="story",
            cadence="daily",
            max_per_day=1,
        )
        add_account_requirement_fixture(
            cf,
            account_id=account_b["id"],
            surface="story",
            cadence="2_per_day",
            max_per_day=1,
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_safe_1",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_safe_2",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, post_id, platform, status, account_id, instagram_account_id,
             content_surface, published_at, snapshot_at, raw_json, created_at)
            VALUES ('perf_story_daily', ?, 'post_story_daily', 'instagram', 'published', ?, 'ig_daily',
                    'story', '2026-06-06T09:00:00+00:00', '2026-06-06T10:00:00+00:00',
                    '{}', '2026-06-06T10:00:00+00:00')
            """,
            (
                cf.domains.campaign_by_slug("stacey_surface_inventory_20260606")["id"],
                account_a["id"],
            ),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        status = cf.domains.story_management.account_story_status(
            account_id=account_b["id"], creator="Stacey", date="2026-06-06"
        )
        gap = cf.domains.story_management.story_gap_report(
            creator="Stacey", date="2026-06-06"
        )
        summary = cf.domains.story_management.creator_story_summary(
            creator="Stacey", date="2026-06-06"
        )

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
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_eod",
            platform="instagram",
            external_id="ig_eod",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf,
            account_id=account["id"],
            surface="story",
            cadence="every_other_day",
            max_per_day=1,
        )
        cf.conn.commit()

        first = cf.domains.story_management.account_story_status(
            account_id=account["id"], creator="Stacey", date="2026-06-06"
        )
        second = cf.domains.story_management.account_story_status(
            account_id=account["id"], creator="Stacey", date="2026-06-07"
        )

        assert {first["storyNeededToday"], second["storyNeededToday"]} == {True, False}
        assert first["wouldWrite"] is False
        assert second["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_daily_plan_includes_story_inventory_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_story",
            platform="instagram",
            external_id="ig_story",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf,
            account_id=account["id"],
            surface="story",
            cadence="daily",
            max_per_day=1,
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_safe",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            date="2026-06-06",
            threadsdash_report=_manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_story",
                        "username": "stacey_story",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": False,
                    }
                ]
            ),
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


def test_creator_os_daily_plan_counts_blocked_account_breakdown(tmp_path: Path):
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
            },
            {
                "accountId": "ig_recent",
                "username": "recent",
                "creator": "Stacey",
                "bucket": "blocked_recent_failure",
                "safeToSchedule": False,
                "needsPostToday": False,
            },
            {
                "accountId": "ig_reauth",
                "username": "reauth",
                "creator": "Stacey",
                "bucket": "blocked_reauth",
                "safeToSchedule": False,
                "needsPostToday": False,
                "blockingReason": "needs_reauth",
            },
        ]

        plan = cf.domains.daily_plan.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "validatedDraftsAvailable": 1,
                "items": [_draft_item("post_1", "ig_safe")],
            },
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


def test_decision_ledger_report_filters_by_creator_account_surface_and_type(
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

        by_creator = cf.domains.decision_ledger.decision_ledger_by_creator(**source)
        by_account = cf.domains.decision_ledger.decision_ledger_by_account(
            account_id=account["id"], **source
        )
        by_surface = cf.domains.decision_ledger.decision_ledger_by_surface(
            surface="story", **source
        )
        by_type = cf.domains.decision_ledger.decision_ledger_by_decision_type(
            decision_type="account_needs_story", **source
        )
        summary = cf.domains.decision_ledger.decision_ledger_summary(**source)

        assert by_creator["creator"] == "Stacey"
        assert by_creator["decisionCount"] >= 3
        assert {entry["accountId"] for entry in by_account["decisions"]} == {
            account["id"]
        }
        assert {
            entry["surface"]
            for entry in by_surface["decisions"]
            if entry.get("surface")
        } == {"story"}
        assert {entry["decisionType"] for entry in by_type["decisions"]} == {
            "account_needs_story"
        }
        assert summary["decisionCountsByType"]["account_needs_story"] == 1
        assert summary["decisionCountsBySurface"]["story"] >= 1
        assert summary["wouldWrite"] is False
        assert table_count(cf, "manager_decisions") == 0
    finally:
        cf.close()


def test_creator_os_execution_readiness_passes_with_safe_accounts_and_drafts(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_1",
                "username": "stacey_one",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
            {
                "accountId": "ig_2",
                "username": "stacey_two",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
        ]
        items = [
            _draft_item("post_1", "ig_1", scheduled_for="2026-06-06T16:00:00+00:00"),
            _draft_item("post_2", "ig_2", scheduled_for="2026-06-06T16:15:00+00:00"),
        ]

        result = cf.domains.execution_readiness.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=2,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 2,
                "status": "ready",
                "validatedDraftsAvailable": 2,
                "items": items,
            },
            time_plan={
                "creator": "Stacey",
                "requestedCount": 2,
                "status": "ready",
                "items": items,
            },
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
            "qualityReadiness": "pass",
            "audioReadiness": "pass",
            "captionContractReadiness": "pass",
        }
        assert result["nextSafeActions"] == ["commit_campaign_schedule_batch"]
    finally:
        cf.close()


def test_creator_os_200_account_acceptance_suite_is_read_only_and_exercises_core_paths(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        result = cf.domains.acceptance_suite.creator_os_200_account_acceptance_suite(
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


def test_creator_os_100_volume_surface_and_10_readiness_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        proof = cf.domains.readiness_report.creator_os_100_account_proof()
        volume = cf.domains.readiness_report.creator_os_volume_acceptance_suite()
        scorecard = cf.domains.readiness_report.surface_readiness_scorecard()
        readiness = cf.domains.readiness_report.creator_os_10_0_readiness_report()

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
        assert set(scorecard["surfaces"]) >= {
            "reel",
            "story",
            "feed_single",
            "feed_carousel",
        }
        assert all("rating" in row for row in scorecard["surfaces"].values())
        assert readiness["schema"] == "creator_os.10_0_readiness_report.v1"
        assert readiness["scores"]["overall"] >= 9.0
        assert readiness["successCriteria"]["exceptionQueueReady"] is True
        assert readiness["successCriteria"]["inventoryAutopilotReady"] is True
        assert readiness["successCriteria"]["requiredParentsPerDayKnown"] is True
        assert (
            readiness["finalOutput"]["projectedRatingAfterSprint"]
            >= readiness["finalOutput"]["currentRating"]
        )
        assert readiness["wouldWrite"] is False
    finally:
        cf.close()


def test_live_account_acceptance_counts_net_inventory_after_reservations_and_assignments(
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
                asset_id=f"asset_net_inventory_{index}",
                content_surface="feed_single",
                media_type="image",
                instagram_post_caption="schedule safe",
            )
        reservation = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset_net_inventory_0",
            account_id=None,
            surface="feed_single",
            reserved_by="test",
            idempotency_key="net_inventory_asset_0",
        )
        same_reservation = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset_net_inventory_0",
            surface="feed_single",
            reserved_by="test",
            idempotency_key="net_inventory_asset_0",
        )
        cf.domains.campaign_overview.assign_asset_account(
            "asset_net_inventory_1", instagram_account_id="ig_1"
        )

        result = cf.domains.live_acceptance.creator_os_live_account_acceptance(
            account_target=10, content_surface="feed_single"
        )

        assert reservation["id"] == same_reservation["id"]
        assert result["grossInventory"] == 90
        assert result["reservedInventory"] == 1
        assert result["usedInventory"] == 1
        assert result["netInventory"] == 88
        assert result["availableInventory"] == 88
        assert result["actuals"]["inventoryBufferMaintained"] is False
        assert "inventory_buffer_not_maintained" in result["blockingReasons"]
        released = cf.domains.inventory_reservations.release_inventory_reservation(
            reservation["reservation_id"]
        )
        assert released["status"] == "released"
        after_release = cf.domains.live_acceptance.creator_os_live_account_acceptance(
            account_target=10, content_surface="feed_single"
        )
        assert after_release["reservedInventory"] == 0
        assert after_release["netInventory"] == 89
    finally:
        cf.close()


def test_inventory_reservation_blocks_explicit_cross_account_source_family_reuse(
    tmp_path: Path,
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
        for index in range(3):
            add_surface_asset_fixture(
                cf,
                tmp_path,
                asset_id=f"asset_uniqueness_{index}",
                content_surface="reel",
                media_type="video",
                instagram_post_caption="lmk",
            )

        first = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset_uniqueness_0",
            account_id=account_a["id"],
            surface="reel",
            reserved_by="test",
            metadata={
                "sourceFamilyId": "family_same",
                "perceptualClusterId": "cluster_same",
            },
        )
        with pytest.raises(
            ValueError, match="cross-account source/perceptual reuse cooldown conflict"
        ):
            cf.domains.inventory_reservations.reserve_inventory_asset(
                "asset_uniqueness_1",
                account_id=account_b["id"],
                surface="reel",
                reserved_by="test",
                metadata={
                    "sourceFamilyId": "family_same",
                    "perceptualClusterId": "cluster_same",
                },
            )
        override = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset_uniqueness_1",
            account_id=account_b["id"],
            surface="reel",
            reserved_by="test",
            metadata={
                "sourceFamilyId": "family_same",
                "perceptualClusterId": "cluster_same",
            },
            override_reason="manual operator approved source reuse",
        )
        assert first["source_family_id"] == "family_same"
        assert override["override_reason"] == "manual operator approved source reuse"
    finally:
        cf.close()


def test_live_account_acceptance_reports_cooldown_blocked_inventory(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"]
        )
        for index in range(90):
            add_surface_asset_fixture(
                cf,
                tmp_path,
                asset_id=f"asset_cooldown_inventory_{index}",
                content_surface="feed_single",
                media_type="image",
                instagram_post_caption="lmk",
            )
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id IN ('asset_cooldown_inventory_0', 'asset_cooldown_inventory_1')",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "lmk",
                        "sourceFamilyId": "family_cooldown",
                    }
                ),
            ),
        )
        cf.conn.commit()
        cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset_cooldown_inventory_0",
            account_id=account["id"],
            surface="feed_single",
            reserved_by="test",
            metadata={"sourceFamilyId": "family_cooldown"},
        )

        result = cf.domains.live_acceptance.creator_os_live_account_acceptance(
            account_target=10, content_surface="feed_single"
        )

        assert result["grossInventory"] == 90
        assert result["reservedInventory"] == 1
        assert result["cooldownBlockedInventory"] == 1
        assert result["netInventory"] == 88
    finally:
        cf.close()


def test_live_account_acceptance_counts_computed_pdq_cooldown_blocked_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_a", platform="instagram", external_id="ig_a", model_id=model["id"]
        )
        for index in range(3):
            add_surface_asset_fixture(
                cf,
                tmp_path,
                asset_id=f"asset_pdq_inventory_{index}",
                content_surface="feed_single",
                media_type="image",
                instagram_post_caption="lmk",
            )

        def fake_pdq(path: Path, **_: Any) -> dict[str, Any]:
            name = Path(path).name
            fingerprint = "0" * 64
            if "asset_pdq_inventory_1" in name:
                fingerprint = "0" * 63 + "1"
            if "asset_pdq_inventory_2" in name:
                fingerprint = "f" * 64
            return {
                "status": "available",
                "algorithm": "pdq_v1",
                "fingerprint": fingerprint,
                "quality": 100,
                "source": "image",
            }

        monkeypatch.setattr(core_module, "compute_pdq_fingerprint", fake_pdq)
        cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset_pdq_inventory_0",
            account_id=account["id"],
            surface="feed_single",
            reserved_by="test",
        )

        result = cf.domains.live_acceptance.creator_os_live_account_acceptance(
            account_target=1, content_surface="feed_single"
        )

        assert result["grossInventory"] == 3
        assert result["reservedInventory"] == 1
        assert result["cooldownBlockedInventory"] == 1
        assert result["netInventory"] == 1
    finally:
        cf.close()


def test_reel_factory_200_account_readiness_and_master_report_are_read_only(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        readiness = cf.domains.reel_factory_reports.reel_factory_200_account_readiness()
        master = cf.domains.reel_factory_reports.reel_factory_master_report()

        assert cf.conn.total_changes == before
        assert readiness["schema"] == "creator_os.reel_factory_200_account_readiness.v1"
        assert readiness["requiredParentsPerDay"] == 53
        assert (
            readiness["scalingAnalysis"]["200Accounts"]["requiredParentsPerDay"] == 53
        )
        assert (
            readiness["scalingAnalysis"]["200Accounts"]["requiredValidatedDraftsPerDay"]
            == 600
        )
        assert (
            readiness["scalingAnalysis"]["500Accounts"]["requiredInventoryBuffer"]
            == 4500
        )
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


def test_parent_factory_53_parent_trial_reports_measured_throughput_only(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        trial = cf.domains.parent_factory_trials.parent_factory_53_parent_trial()
        results = cf.domains.parent_factory_trials.parent_factory_trial_results()
        analysis = cf.domains.parent_factory_trials.parent_factory_trial_analysis()

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
        assert results["rankedLosses"][0] == {
            "stage": "discoverability_safety_pass",
            "count": 225,
        }
        assert analysis["schema"] == "creator_os.parent_factory_trial_analysis.v1"
        assert analysis["statement"] == (
            "The factory produced 20 accepted parents from 245 candidates. "
            "The limiting factor was discoverability_safety_pass."
        )
        assert analysis["measuredOnly"] is True
        assert all(item["wouldWrite"] is False for item in [trial, results, analysis])
    finally:
        cf.close()
