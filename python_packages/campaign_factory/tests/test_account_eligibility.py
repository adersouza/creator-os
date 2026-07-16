from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from campaign_factory.account_eligibility import (
    AccountEligibilityError,
    enforce_account_eligibility,
    evaluate_account_eligibility,
)
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory

from pipeline_contracts import validate_account_eligibility_decision


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


def add_asset(cf: CampaignFactory, tmp_path: Path) -> str:
    campaign = cf.domains.models.upsert_campaign("eligibility", "stacey")
    model = cf.domains.models.upsert_model("stacey")
    output = tmp_path / "asset.mp4"
    output.write_bytes(b"video")
    now = "2026-07-15T12:00:00+00:00"
    cf.conn.execute(
        """
        INSERT INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path,
         filename, created_at, updated_at)
        VALUES ('source_eligibility', ?, ?, 'source-hash', ?, ?, 'asset.mp4', ?, ?)
        """,
        (campaign["id"], model["id"], str(output), str(output), now, now),
    )
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path,
         filename, metadata_json, caption_generation_json, review_state,
         created_at, updated_at)
        VALUES ('asset_eligibility', ?, 'source_eligibility', 'render-hash', ?, ?,
                'asset.mp4', '{}', ?, 'approved', ?, ?)
        """,
        (
            campaign["id"],
            str(output),
            str(output),
            json.dumps(
                {"generatedAssetLineage": {"contentFingerprint": "render-hash"}}
            ),
            now,
            now,
        ),
    )
    cf.conn.commit()
    return "asset_eligibility"


def project_account(
    cf: CampaignFactory,
    *,
    handle: str = "stacey_test",
    external_id: str = "ig_stacey_test",
    active: bool = True,
    status: str = "active",
    needs_reauth: bool = False,
    capability: str = "eligible",
    scopes: list[str] | None = None,
    projection_age_hours: float | None = 0,
) -> dict:
    account = cf.domains.models.upsert_account(handle, external_id=external_id)
    projection_observed_at = (
        None
        if projection_age_hours is None
        else (datetime.now(UTC) - timedelta(hours=projection_age_hours)).isoformat()
    )
    return cf.domains.models.project_instagram_account_evidence(
        account["id"],
        capability=capability,
        oauth_granted_scopes=scopes,
        oauth_scopes_verified_at=(
            "2026-07-15T11:55:00+00:00" if scopes is not None else None
        ),
        checked_at="2026-07-15T11:56:00+00:00",
        reason=None,
        is_active=active,
        status=status,
        needs_reauth=needs_reauth,
        sync_cohort="warm",
        projection_observed_at=projection_observed_at,
    )


def test_supervised_draft_allows_missing_projection_but_records_action(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        decision = evaluate_account_eligibility(
            cf.conn,
            instagram_account_id="not_projected",
            surface="regular_reel",
        )

        validate_account_eligibility_decision(decision)
        assert decision["allowed"] is True
        assert (
            decision["decisionReason"]
            == "account_projection_missing_supervised_draft_only"
        )
        assert decision["operatorAction"] == "sync_threadsdashboard_account_projection"
    finally:
        cf.close()


def test_trial_fails_closed_without_account_or_oauth_evidence(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        missing = evaluate_account_eligibility(
            cf.conn,
            instagram_account_id="not_projected",
            surface="trial_reel",
            requires_trial_capability=True,
            authorization="operator_canary",
        )
        account = project_account(cf, capability="unknown", scopes=None)
        no_scopes = evaluate_account_eligibility(
            cf.conn,
            account_id=account["id"],
            surface="trial_reel",
            requires_trial_capability=True,
            authorization="operator_canary",
        )

        assert missing["decisionReason"] == "account_projection_missing"
        assert no_scopes["decisionReason"] == "trial_oauth_scope_evidence_missing"
        assert missing["allowed"] is no_scopes["allowed"] is False
    finally:
        cf.close()


def test_trial_unknown_requires_bounded_canary_and_known_scope(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        account = project_account(
            cf,
            capability="unknown",
            scopes=["instagram_basic", "instagram_content_publish"],
        )
        blocked = evaluate_account_eligibility(
            cf.conn,
            account_id=account["id"],
            surface="trial_reel",
            requires_trial_capability=True,
        )
        allowed = evaluate_account_eligibility(
            cf.conn,
            account_id=account["id"],
            surface="trial_reel",
            requires_trial_capability=True,
            authorization="operator_canary",
        )

        assert (
            blocked["decisionReason"]
            == "trial_capability_unknown_requires_operator_canary"
        )
        assert blocked["allowed"] is False
        assert allowed["decisionReason"] == "trial_capability_operator_canary"
        assert allowed["allowed"] is True
    finally:
        cf.close()


@pytest.mark.parametrize(
    ("projection_age_hours", "reason"),
    [
        (None, "trial_account_projection_observed_at_missing"),
        (25, "trial_account_projection_stale"),
    ],
)
def test_trial_fails_closed_on_missing_or_stale_account_projection(
    tmp_path: Path,
    projection_age_hours: float | None,
    reason: str,
):
    cf = make_factory(tmp_path)
    try:
        account = project_account(
            cf,
            capability="eligible",
            scopes=["instagram_business_content_publish"],
            projection_age_hours=projection_age_hours,
        )

        decision = evaluate_account_eligibility(
            cf.conn,
            account_id=account["id"],
            surface="trial_reel",
            requires_trial_capability=True,
        )

        assert decision["allowed"] is False
        assert decision["decisionReason"] == reason
        assert decision["operatorAction"] == "sync_threadsdashboard_account_projection"
    finally:
        cf.close()


def test_trial_fails_closed_on_invalid_account_projection_timestamp(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        account = project_account(
            cf,
            capability="eligible",
            scopes=["instagram_business_content_publish"],
        )
        cf.conn.execute(
            "UPDATE accounts SET threadsdash_projection_observed_at = 'not-a-date' "
            "WHERE id = ?",
            (account["id"],),
        )
        cf.conn.commit()

        decision = evaluate_account_eligibility(
            cf.conn,
            account_id=account["id"],
            surface="trial_reel",
            requires_trial_capability=True,
        )

        assert decision["allowed"] is False
        assert (
            decision["decisionReason"] == "trial_account_projection_observed_at_invalid"
        )
        assert decision["account"]["projectionObservedAt"] is None
    finally:
        cf.close()


@pytest.mark.parametrize(
    ("active", "status", "needs_reauth", "reason"),
    [
        (False, "inactive", False, "account_inactive"),
        (True, "active", True, "account_reauth_required"),
        (True, "restricted", False, "account_restricted"),
    ],
)
def test_account_state_blocks_every_surface(
    tmp_path: Path,
    active: bool,
    status: str,
    needs_reauth: bool,
    reason: str,
):
    cf = make_factory(tmp_path)
    try:
        account = project_account(
            cf,
            active=active,
            status=status,
            needs_reauth=needs_reauth,
            scopes=["instagram_content_publish"],
        )
        with pytest.raises(AccountEligibilityError) as blocked:
            enforce_account_eligibility(
                cf.conn,
                account_id=account["id"],
                surface="regular_reel",
            )
        assert blocked.value.decision["decisionReason"] == reason
    finally:
        cf.close()


def test_distribution_and_account_plan_share_persisted_decision(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        asset_id = add_asset(cf, tmp_path)
        account = project_account(cf, scopes=["instagram_content_publish"])
        plan = cf.domains.distribution.create_distribution_plan(
            asset_id,
            account_id=account["id"],
            surface="regular_reel",
            planned_window_start="2026-07-16T12:00:00+00:00",
        )
        account_plan = cf.domains.account_planning.account_plan(
            "eligibility", user_id="operator"
        )

        assert plan["accountEligibility"]["allowed"] is True
        assert (
            account_plan["rows"][0]["accountEligibility"] == plan["accountEligibility"]
        )
        stored = cf.conn.execute(
            "SELECT account_eligibility_json FROM distribution_plans WHERE id = ?",
            (plan["id"],),
        ).fetchone()[0]
        assert json.loads(stored) == plan["accountEligibility"]
    finally:
        cf.close()


def test_assignment_and_reservation_persist_same_account_contract(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        asset_id = add_asset(cf, tmp_path)
        account = project_account(cf, scopes=["instagram_content_publish"])
        assignment = cf.domains.campaign_overview.assign_asset_account(
            asset_id, account_id=account["id"]
        )
        cf.conn.execute("DELETE FROM asset_account_assignments")
        cf.conn.execute(
            "UPDATE rendered_assets SET origin_account_id = NULL WHERE id = ?",
            (asset_id,),
        )
        cf.conn.commit()
        reservation = cf.domains.inventory_reservations.reserve_inventory_asset(
            asset_id, account_id=account["id"]
        )

        assert json.loads(assignment["account_eligibility_json"])["allowed"] is True
        assert json.loads(reservation["account_eligibility_json"])["allowed"] is True
    finally:
        cf.close()
