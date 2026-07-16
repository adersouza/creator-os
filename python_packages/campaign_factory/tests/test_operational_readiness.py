from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from campaign_asset_test_support import (
    add_audit_report,
    add_schedule_safe_production_asset,
    add_story_quality_asset,
    add_surface_asset_fixture,
    ensure_exportable_distribution_plan,
)
from campaign_factory.readiness_report import build_mass_production_readiness_report
from campaign_learning_test_support import _draft_item, _manager_report_fixture
from campaign_test_support import (
    add_rendered_asset,
    isolate_account_groups,
    make_factory,
)


def test_mass_production_readiness_report_flags_blockers(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            "UPDATE source_assets SET source_prompt = '{}' WHERE id = ?",
            (source["id"],),
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()

        report = build_mass_production_readiness_report(cf, campaign_id="may", days=7)

        assert (
            report["schema"] == "campaign_factory.mass_production_readiness_report.v1"
        )
        assert report["counts"]["approvedAssets"] == 1
        assert report["counts"]["missingCanonicalIds"] == 1
        assert report["counts"]["missingLineage"] == 1
        assert report["counts"]["missingAccountAssignment"] == 1
        assert report["schedule"]["scheduleGaps"]["pilot"]["gap"] == 105
        assert report["readinessScore"] == "NOT_READY"
        assert any(
            item["code"] == "missing_account_assignment"
            for item in report["blockerRanking"]["preventsProduction"]
        )
        assert any(
            item["code"] == "missing_canonical_ids"
            for item in report["blockerRanking"]["risksLosingTracking"]
        )
        assert "# Mass Production Readiness: may" in report["markdownSummary"]
    finally:
        cf.close()


def test_mass_production_readiness_report_can_mark_pilot_ready(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, rendered_path = add_rendered_asset(cf, tmp_path)
        cf.domains.graph.ensure_graph_node(
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
                json.dumps(
                    {
                        "generatedAssetLineage": {
                            "schema": "pipeline.generated_asset_lineage.v1",
                            "source": {"referenceId": "ref_couch"},
                            "generation": {"system": "reel_factory"},
                            "quality": {"contentFingerprint": "fingerprint_couch"},
                        }
                    }
                ),
                source["id"],
            ),
        )
        start = (datetime.now(UTC) + timedelta(hours=1)).replace(
            second=0, microsecond=0
        )
        isolate_account_groups(cf, [f"stacey_{index}" for index in range(1, 6)])
        projected_at = datetime.now(UTC).isoformat()
        for account_idx in range(5):
            instagram_account_id = f"stacey_{account_idx + 1}"
            account_row = cf.conn.execute(
                "SELECT id FROM accounts WHERE external_id = ?",
                (instagram_account_id,),
            ).fetchone()
            cf.domains.models.project_instagram_account_evidence(
                account_row["id"],
                capability="eligible",
                oauth_granted_scopes=["instagram_business_content_publish"],
                oauth_scopes_verified_at=projected_at,
                checked_at=projected_at,
                reason="test_fixture_eligible",
                is_active=True,
                status="active",
                needs_reauth=False,
                projection_observed_at=projected_at,
            )
        for day in range(7):
            for account_idx in range(5):
                account = f"stacey_{account_idx + 1}"
                base = start + timedelta(days=day)
                for slot_idx, surface in enumerate(
                    ("regular_reel", "trial_reel", "trial_reel")
                ):
                    slot = base + timedelta(hours=slot_idx * 3)
                    cf.domains.distribution.create_distribution_plan(
                        "asset_1",
                        surface=surface,
                        instagram_account_id=account,
                        planned_window_start=slot.isoformat(),
                        planned_window_end=(slot + timedelta(minutes=30)).isoformat(),
                        instagram_trial_reels=surface == "trial_reel",
                        trial_graduation_strategy=(
                            "MANUAL" if surface == "trial_reel" else None
                        ),
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


def test_mass_production_readiness_report_detects_duplicate_content_risk(
    tmp_path: Path,
):
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
                json.dumps(
                    {
                        "audioIntent": {"status": "not_required"},
                        "generatedAssetLineage": {
                            "source": {"referenceId": "same_ref"},
                            "quality": {"contentFingerprint": "same_fp"},
                        },
                    }
                ),
                now,
                now,
            ),
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved', caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "audioIntent": {"status": "not_required"},
                        "generatedAssetLineage": {
                            "source": {"referenceId": "same_ref"},
                            "quality": {"contentFingerprint": "same_fp"},
                        },
                    }
                ),
            ),
        )
        cf.conn.execute(
            "UPDATE source_assets SET source_prompt = '{}' WHERE id = ?",
            (source["id"],),
        )
        cf.conn.commit()

        report = build_mass_production_readiness_report(cf, campaign_id="may", days=7)

        assert report["duplicateRisk"]["byContentFingerprint"] == [
            {"key": "same_fp", "count": 2, "renderedAssetIds": ["asset_1", "asset_2"]}
        ]
        assert report["duplicateRisk"]["bySourceReferenceOrFamily"] == [
            {"key": "same_ref", "count": 2, "renderedAssetIds": ["asset_1", "asset_2"]}
        ]
        assert any(
            item["code"] == "content_fingerprint_reuse"
            for item in report["blockerRanking"]["risksDuplicatePosting"]
        )
    finally:
        cf.close()


def test_mass_production_readiness_reports_canonical_state_owners(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)

        report = build_mass_production_readiness_report(cf, campaign_id="may", days=7)

        assert report["externalPostingLedgerAudit"]["ownership"] == "retired"
        assert report["externalPostingLedgerAudit"]["matchingSlotCount"] == 0
        assert report["stateOwnership"]["assetLifecycle"] == "Campaign Factory"
        assert (
            report["stateOwnership"]["schedulingPublishingMetrics"]
            == "ThreadsDashboard"
        )
    finally:
        cf.close()


def test_inventory_recovery_report_ranks_repair_classes_without_writing(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
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
                    }
                ),
            ),
        )
        rendered_path = tmp_path / "asset_operator_audio_preview_test.mp4"
        rendered_path.write_bytes(b"operator-review")
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
                json.dumps(
                    {**context, "caption_hash": "caption_hash_operator"}, sort_keys=True
                ),
                json.dumps(
                    {
                        "instagram_post_caption": "new fit today",
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
        add_audit_report(
            cf, rendered_asset_id="asset_operator", audit_id="audit_operator"
        )
        cf.conn.commit()
        before_changes = cf.conn.total_changes

        report = cf.domains.inventory_recovery.inventory_recovery_report(
            creator="Test", content_surface="reel", required_inventory=3
        )
        by_class = {row["repairClass"]: row for row in report["repairClasses"]}

        assert report["schema"] == "creator_os.inventory_recovery_report.v1"
        assert report["wouldWrite"] is False
        assert report["currentScheduleSafeAssets"] == 0
        assert report["requiredInventory"] == 3
        assert report["shortfall"] == 3
        assert by_class["caption_only"]["blockedAssets"] == 1
        assert by_class["caption_only"]["scheduleSafeAssetsRecoverable"] == 1
        assert by_class["operator_visual_review_required"]["blockedAssets"] == 1
        assert (
            by_class["operator_visual_review_required"]["scheduleSafeAssetsRecoverable"]
            == 1
        )
        assert report["highestROIRepairClass"] == "caption_only"
        assert report["inventoryGateImpact"]["inventoryAfterTop3Repairs"] == 2
        assert report["inventoryGateImpact"]["wouldPass25AccountGate"] is False
        assert cf.conn.total_changes == before_changes
    finally:
        cf.close()


def test_schedule_safe_production_report_measures_fresh_waterfall_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        parent = add_schedule_safe_production_asset(
            cf, tmp_path, asset_id="parent_fresh", source=source
        )
        now = datetime.now(UTC).isoformat()
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
                parent["campaign_id"],
                "concept_prod",
                "parent_reel_prod",
                now,
                now,
                parent["campaign_id"],
                "concept_prod",
                "parent_reel_prod",
                now,
                now,
            ),
        )
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="variant_pass",
            source=source,
            parent_asset_id="parent_fresh",
        )
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
        old_time = (datetime.now(UTC) - timedelta(days=5)).isoformat()
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

        report = cf.domains.schedule_safe_production.schedule_safe_production_report(
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


def test_schedule_safe_production_capacity_zero_production_is_blocked(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        report = (
            cf.domains.schedule_safe_production.schedule_safe_production_capacity_model(
                creator="Test",
                content_surface="reel",
                lookback_days=1,
                required_inventory=225,
                current_inventory=11,
            )
        )

        assert (
            report["schema"] == "creator_os.schedule_safe_production_capacity_model.v1"
        )
        assert report["scheduleSafeAssetsProducedPerDay"] == 0
        assert report["daysToReach25AccountBuffer"] is None
        assert (
            report["capacityProjections"]["25Accounts"]["blockedReason"]
            == "no_schedule_safe_production_observed"
        )
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_multi_blocker_inventory_unlock_report_finds_combined_repairs_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        add_schedule_safe_production_asset(
            cf, tmp_path, asset_id="asset_single_caption", source=source
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_single_caption'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "this caption is too long and keeps going because it is not the simple native style we want under Instagram posts when the asset should be safe for scheduling and it keeps adding more unnecessary words",
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

        report = cf.domains.multi_blocker_unlock.multi_blocker_inventory_unlock_report(
            creator="Test",
            content_surface="reel",
            required_inventory=3,
            current_inventory=0,
        )

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.multi_blocker_inventory_unlock_report.v1"
        assert report["currentScheduleSafeAssets"] == 0
        assert report["shortfall"] == 3
        assert (
            report["bestSingleRepair"]["repairClass"]
            == "instagram_post_caption_quality_failed"
        )
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


def test_fresh_schedule_safe_production_plan_calculates_reel_only_buffer_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        report = cf.domains.fresh_reel_production.fresh_schedule_safe_production_plan(
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
        assert (
            report["largestProductionRisk"]
            == "variant_to_schedule_safe_yield_not_yet_proven"
        )
        assert (
            report["downstreamYieldEvidenceStatus"]
            == "insufficient_schedule_safe_variant_production_evidence"
        )
        assert report["wouldWrite"] is False
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

        readiness = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey", rendered_asset_id="asset_story_missing_style"
        )

        assert readiness["assets"][0]["canHandoff"] is False
        assert "story_style_not_approved" in readiness["assets"][0]["blockingReasons"]
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_creative_risk_and_similarity_budget(
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
                "recommendationEligibilityState": "eligible",
                "accountMaturityScore": 70,
            },
        ]
        risky = _draft_item("post_risky", "ig_safe")
        risky["creativeRiskScore"] = 80
        risky["similarityBudget"] = {
            "blocked": True,
            "reason": "visual_similarity_cluster_budget_exceeded",
        }
        schedule_plan = {
            "schema": "threadsdashboard.campaign_schedule_plan.v1",
            "status": "ready",
            "items": [risky],
        }
        time_plan = {
            "schema": "threadsdashboard.campaign_schedule_time_plan.v1",
            "status": "ready",
            "items": [risky],
        }

        readiness = cf.domains.execution_readiness.creator_os_execution_readiness(
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


def test_creator_os_execution_readiness_blocks_when_inventory_is_zero(tmp_path: Path):
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
        before = cf.conn.total_changes

        result = cf.domains.execution_readiness.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=2,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 2,
                "status": "blocked",
                "blockingReason": "insufficient_validated_drafts",
                "validatedDraftsAvailable": 0,
                "items": [],
            },
            time_plan={
                "creator": "Stacey",
                "requestedCount": 2,
                "status": "blocked",
                "blockingReason": "insufficient_validated_drafts",
                "items": [],
            },
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


def test_phase2_surface_and_readiness_reports_share_helpers(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_phase2_story",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )
        cf.conn.commit()
        inventory_calls = 0
        readiness_calls = 0
        original_inventory = cf.domains.surface_inventory.build_surface_inventory
        original_readiness = cf.domains.surface_handoff.build_surface_readiness

        def tracking_inventory(*args, **kwargs):
            nonlocal inventory_calls
            inventory_calls += 1
            return original_inventory(*args, **kwargs)

        def tracking_readiness(*args, **kwargs):
            nonlocal readiness_calls
            readiness_calls += 1
            return original_readiness(*args, **kwargs)

        monkeypatch.setattr(
            cf.domains.surface_inventory,
            "build_surface_inventory",
            tracking_inventory,
        )
        monkeypatch.setattr(
            cf.domains.surface_handoff,
            "build_surface_readiness",
            tracking_readiness,
        )

        inventory = cf.domains.story_management.story_inventory_report(creator="Stacey")
        audit = cf.domains.surface_inventory.multi_surface_inventory_audit(
            creator="Stacey"
        )
        readiness = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey"
        )
        proof = cf.domains.surface_handoff.surface_draft_proof(creator="Stacey")

        assert inventory["schema"] == "campaign_factory.story_inventory_report.v1"
        assert audit["schema"] == "campaign_factory.multi_surface_inventory_audit.v1"
        assert (
            readiness["schema"]
            == "campaign_factory.surface_handoff_readiness_report.v1"
        )
        assert proof["schema"] == "campaign_factory.surface_draft_proof.v1"
        assert inventory_calls >= 2
        assert readiness_calls >= 2
        assert inventory["wouldWrite"] is False
        assert audit["wouldWrite"] is False
        assert readiness["wouldWrite"] is False
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_unverified_native_audio(tmp_path: Path):
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
        ]
        item = _draft_item(
            "post_audio_selected", "ig_1", scheduled_for="2026-06-06T16:00:00+00:00"
        )
        item["audioStatus"] = "selected"
        item["nativeAudioProofStatus"] = "missing"

        result = cf.domains.execution_readiness.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "validatedDraftsAvailable": 1,
                "items": [item],
            },
            time_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "items": [item],
            },
        )

        assert result["executionReady"] is False
        assert result["preCommitChecklist"]["audioReadiness"] == "fail"
        assert "native_audio_proof_missing" in result["blockers"]
        details = {item["code"]: item for item in result["blockerDetails"]}
        assert details["native_audio_proof_missing"]["category"] == "audio"
        assert (
            details["native_audio_proof_missing"]["nextAction"]
            == "select_or_verify_native_audio"
        )
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_variant_cooldown_missed_dispatch_and_time_slots(
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
        ]
        missed = [
            {
                "postId": "post_missed",
                "accountId": "ig_1",
                "blockingReason": "overdue_dispatch_no_publish_attempt",
            }
        ]

        result = cf.domains.execution_readiness.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(
                accounts=accounts, missed=missed
            ),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "validatedDraftsAvailable": 1,
                "items": [
                    _draft_item(
                        "post_1",
                        "ig_1",
                        variant_family_id="vfam_1",
                        variant_id="var_1",
                        cooldown="same_variant_family_within_14_days",
                    )
                ],
            },
            time_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "items": [],
            },
        )

        assert result["managerDecision"] == "blocked"
        assert result["preCommitChecklist"]["publishRuntimeReadiness"] == "fail"
        assert result["preCommitChecklist"]["timePlanReadiness"] == "fail"
        assert "missed_dispatches_unresolved" in result["blockers"]
        assert "variant_cooldown_violation" in result["blockers"]
        assert "insufficient_time_plan_items" in result["blockers"]
        assert (
            "resolve_missed_dispatches_before_scheduling" in result["nextSafeActions"]
        )
    finally:
        cf.close()


def test_inventory_slo_and_buffer_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        slo = cf.domains.inventory_planning.inventory_slo_report(
            accounts=200,
            posts_per_account_per_day=3,
            creators=3,
            minimum_inventory_days=3,
        )
        buffer_report = cf.domains.inventory_planning.inventory_buffer_report(
            accounts=200,
            posts_per_account_per_day=3,
            creators=3,
            current_validated_drafts=1800,
            current_drafts_by_surface={
                "reel": 900,
                "story": 600,
                "feed_single": 300,
                "feed_carousel": 0,
            },
        )

        assert cf.conn.total_changes == before
        assert slo["minimumInventoryDays"] == 3
        assert slo["minimumValidatedDraftBuffer"] == 1800
        assert slo["minimumDraftsPerCreator"] == {
            "Creator 1": 600,
            "Creator 2": 600,
            "Creator 3": 600,
        }
        assert slo["minimumDraftsPerSurface"]["reel"] > 0
        assert slo["inventoryHealth"] == "critical"
        assert slo["wouldWrite"] is False
        assert buffer_report["inventoryHealth"] == "healthy"
        assert buffer_report["currentValidatedDrafts"] == 1800
        assert buffer_report["draftSurplus"] == 0
        assert buffer_report["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_maturity_operator_ownership_complexity_and_final_readiness_are_read_only(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        surface = cf.domains.operational_proofs.surface_maturity_audit()
        operator = cf.domains.operational_proofs.operator_load_audit()
        ownership = cf.domains.core_complexity.single_source_of_truth_audit()
        complexity = cf.domains.core_complexity.core_complexity_reduction_plan()
        final = cf.domains.readiness_report.creator_os_9_5_readiness_report()

        assert cf.conn.total_changes == before
        assert surface["schema"] == "creator_os.surface_maturity_audit.v1"
        assert set(surface["surfaces"]) == {
            "reel",
            "story",
            "feed_single",
            "feed_carousel",
            "trial_reel",
        }
        assert surface["surfaces"]["reel"]["publishProof"] is True
        assert surface["surfaces"]["story"]["publishProof"] is False
        assert surface["surfaces"]["feed_carousel"]["metricsProof"] is False
        assert surface["wouldWrite"] is False
        assert operator["schema"] == "creator_os.operator_load_audit.v1"
        assert operator["firstBreakingPoint"] in {"100_accounts", "200_accounts"}
        assert operator["scaleTiers"]["200"]["largestBottleneck"]
        assert operator["wouldWrite"] is False
        assert ownership["schema"] == "creator_os.single_source_of_truth_audit.v1"
        assert (
            ownership["recommendedOwners"]["performance metrics"]
            == "performance_snapshots"
        )
        assert ownership["recommendedOwners"]["account eligibility"].endswith(
            "creator_os_account_health_decision"
        )
        assert (
            ownership["recommendedOwners"]["winner status"]
            == "imported reference_factory.knowledge_pack.v1"
        )
        assert ownership["ownershipConflicts"] == []
        assert ownership["duplicateTruths"] == []
        assert ownership["wouldWrite"] is False
        assert complexity["schema"] == "creator_os.core_complexity_reduction_plan.v1"
        assert any(
            row["file"].endswith("campaign_factory/core.py")
            for row in complexity["largestFiles"]
        )
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


def test_inventory_buffer_policy_and_slo_enforcement_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        buffer_plan = cf.domains.inventory_planning.inventory_buffer_policy_plan(
            creator="Stacey",
            surface="reel",
            daily_demand=600,
            buffer_target_days=3,
            available_inventory=900,
        )
        slo = cf.domains.inventory_planning.inventory_slo_enforcement_audit(
            creators=["Stacey", "Lola"],
            accounts=200,
            posts_per_account_per_day=3,
            minimum_inventory_days=3,
            available_by_creator_surface={
                "Stacey": {
                    "reel": 900,
                    "story": 500,
                    "feed_single": 100,
                    "feed_carousel": 0,
                },
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

        exceptions = cf.domains.inventory_planning.inventory_exception_audit(
            execution_readiness=readiness
        )
        readiness_report = (
            cf.domains.inventory_planning.inventory_factory_readiness_report(
                accounts=200,
                posts_per_account_per_day=3,
                available_inventory=1800,
                execution_readiness=readiness,
            )
        )
        master = cf.domains.inventory_planning.inventory_factory_master_report(
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
        assert (
            readiness_report["schema"]
            == "creator_os.inventory_factory_readiness_report.v1"
        )
        assert 0 <= readiness_report["overallInventoryReadiness"] <= 10
        assert readiness_report["inventoryBufferScore"] == 10
        assert readiness_report["wouldWrite"] is False
        assert master["schema"] == "creator_os.inventory_factory_master_report.v1"
        assert (
            master["currentInventoryReadiness"]["overallInventoryReadiness"]
            == readiness_report["overallInventoryReadiness"]
        )
        assert (
            master["requirementsFor200Accounts"]["requiredInventoryBuffer"]
            == "1800 schedule-safe drafts"
        )
        assert (
            master["requirementsFor500Accounts"]["requiredInventoryBuffer"]
            == "4500 schedule-safe drafts"
        )
        assert master["wouldWrite"] is False
    finally:
        cf.close()
