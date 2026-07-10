from __future__ import annotations

import json
from pathlib import Path

import pytest
from campaign_factory.assignment_eligibility import (
    AssignmentEligibilityError,
    evaluate_assignment_eligibility,
    write_assignment_eligibility_artifact,
)
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.trial_reels import (
    graduate_trial_reel,
    record_trial_observation,
    trial_reel_ranking_report,
)

from pipeline_contracts import validate_assignment_eligibility


def make_factory(tmp_path: Path) -> CampaignFactory:
    reel_root = tmp_path / "reel_factory"
    reel_root.mkdir()
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign.sqlite",
            reel_factory_root=reel_root,
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "threadsdash",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def add_asset(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    asset_id: str,
    content_hash: str,
    source_family_id: str | None = None,
    perceptual_fingerprint: str | None = None,
) -> dict:
    campaign = cf.upsert_campaign("scheduler", "stacey")
    model = cf.upsert_model("stacey")
    now = "2026-07-09T12:00:00+00:00"
    source_id = f"source_{asset_id}"
    output = tmp_path / f"{asset_id}.mp4"
    output.write_bytes(content_hash.encode())
    cf.conn.execute(
        """
        INSERT INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path,
         filename, platform, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'instagram', ?, ?)
        """,
        (
            source_id,
            campaign["id"],
            model["id"],
            f"source-hash-{asset_id}",
            str(output),
            str(output),
            output.name,
            now,
            now,
        ),
    )
    metadata = {
        "sourceFamilyId": source_family_id,
        "perceptualFingerprint": perceptual_fingerprint,
        "perceptualClusterId": perceptual_fingerprint,
    }
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path,
         filename, metadata_json, review_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)
        """,
        (
            asset_id,
            campaign["id"],
            source_id,
            content_hash,
            str(output),
            str(output),
            output.name,
            json.dumps(metadata),
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


def test_missing_identity_is_fail_closed_to_first_persisted_origin(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        asset = add_asset(cf, tmp_path, asset_id="asset_missing", content_hash="hash-a")
        first = cf.upsert_account("first", account_group_id="stacey")
        second = cf.upsert_account("second", account_group_id="stacey")

        cf.assign_asset_account(asset["id"], account_id=first["id"])
        persisted = cf.rendered_asset(asset["id"])
        assert persisted["origin_account_id"] == first["id"]

        with pytest.raises(AssignmentEligibilityError) as blocked:
            cf.assign_asset_account(asset["id"], account_id=second["id"])
        assert blocked.value.decision["reasonCodes"] == ["missing_identity_metadata"]
    finally:
        cf.close()


def test_source_family_reuse_gate_is_shared_by_plan_and_reservation(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        first_asset = add_asset(
            cf,
            tmp_path,
            asset_id="asset_first",
            content_hash="hash-first",
            source_family_id="gold-family-1",
            perceptual_fingerprint="phash64:1111",
        )
        second_asset = add_asset(
            cf,
            tmp_path,
            asset_id="asset_second",
            content_hash="hash-second",
            source_family_id="gold-family-1",
            perceptual_fingerprint="phash64:2222",
        )
        first = cf.upsert_account("first", account_group_id="stacey")
        second = cf.upsert_account("second", account_group_id="stacey")
        cf.create_distribution_plan(
            first_asset["id"],
            account_id=first["id"],
            planned_window_start="2026-07-10T12:00:00+00:00",
        )

        with pytest.raises(AssignmentEligibilityError) as planned:
            cf.create_distribution_plan(
                second_asset["id"],
                account_id=second["id"],
                planned_window_start="2026-07-11T12:00:00+00:00",
            )
        assert "source_family_reuse_window" in planned.value.decision["reasonCodes"]

        with pytest.raises(AssignmentEligibilityError):
            cf.reserve_inventory_asset(
                second_asset["id"],
                account_id=second["id"],
                reuse_cooldown_days=14,
            )
    finally:
        cf.close()


def test_contract_artifact_is_valid_and_deterministic(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        asset = add_asset(
            cf,
            tmp_path,
            asset_id="asset_artifact",
            content_hash="a" * 64,
            source_family_id="family-a",
            perceptual_fingerprint="phash64:aaaa",
        )
        account = cf.upsert_account("first", account_group_id="stacey")
        decision = evaluate_assignment_eligibility(
            cf.conn,
            rendered_asset_id=asset["id"],
            account_id=account["id"],
            planned_at="2026-07-10T12:00:00+00:00",
            surface="regular_reel",
        )
        validate_assignment_eligibility(decision)
        first = write_assignment_eligibility_artifact(decision, tmp_path / "first.json")
        second = write_assignment_eligibility_artifact(
            decision, tmp_path / "second.json"
        )
        assert first.read_bytes() == second.read_bytes()
        assert decision["auto_posting"] is False
    finally:
        cf.close()


def test_manual_trial_graduation_is_same_account_idempotent_and_not_queued(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        asset = add_asset(
            cf,
            tmp_path,
            asset_id="asset_trial",
            content_hash="c" * 64,
            source_family_id="family-trial",
            perceptual_fingerprint="phash64:cccc",
        )
        account = cf.upsert_account("trial-account", account_group_id="stacey")
        trial = cf.create_distribution_plan(
            asset["id"],
            surface="trial_reel",
            account_id=account["id"],
            instagram_trial_reels=True,
            trial_graduation_strategy="MANUAL",
            trial_group_id="trial-group-1",
        )
        cadence = cf.conn.execute(
            "SELECT * FROM account_content_requirements WHERE account_id = ?",
            (account["id"],),
        ).fetchone()
        assert cadence["main_reels_per_day"] == 1
        assert cadence["trial_reels_per_day"] == 2

        first = graduate_trial_reel(
            cf,
            trial_post_id="instagram-trial-post-1",
            distribution_plan_id=trial["id"],
            approved_by="operator@example.com",
        )
        second = graduate_trial_reel(
            cf,
            trial_post_id="instagram-trial-post-1",
            distribution_plan_id=trial["id"],
            approved_by="operator@example.com",
        )
        regular = cf.distribution_plan(first["distributionPlanId"])

        assert first["sameAccount"] is True
        assert first["autoQueued"] is False
        assert second["idempotent"] is True
        assert second["promotionId"] == first["promotionId"]
        assert regular["accountId"] == account["id"]
        assert regular["surface"] == "regular_reel"
        assert regular["plannedWindowStart"] is None
    finally:
        cf.close()


def test_trial_ranking_report_has_one_and_twenty_four_hour_windows(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        asset = add_asset(
            cf,
            tmp_path,
            asset_id="asset_trial_report",
            content_hash="d" * 64,
            source_family_id="family-report",
            perceptual_fingerprint="phash64:dddd",
        )
        account = cf.upsert_account("report-account", account_group_id="stacey")
        trial = cf.create_distribution_plan(
            asset["id"],
            surface="trial_reel",
            account_id=account["id"],
            instagram_trial_reels=True,
            trial_graduation_strategy="MANUAL",
            trial_group_id="trial-group-report",
        )
        for hours, views, engagement in ((1, 100, 4), (24, 900, 40)):
            record_trial_observation(
                cf,
                trial_post_id="trial-report-1",
                distribution_plan_id=trial["id"],
                account_id=account["id"],
                observed_hours=hours,
                views=views,
                engagement=engagement,
            )

        report = trial_reel_ranking_report(cf)
        assert report["cadence"] == "nightly"
        assert report["windowsHours"] == [1, 24]
        assert report["items"][0]["oneHour"]["views"] == 100
        assert report["items"][0]["twentyFourHour"]["views"] == 900
        assert report["autoPromotion"] is False
    finally:
        cf.close()
