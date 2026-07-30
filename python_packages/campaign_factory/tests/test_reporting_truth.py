from pathlib import Path

from campaign_factory.cost_tracker import cost_summary, record_ai_cost
from campaign_learning_test_support import (
    _approve_asset_for_lifecycle,
    _threadsdash_lifecycle_post,
)
from campaign_test_support import make_factory


def test_unknown_lifecycle_state_never_becomes_approved(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        assert (
            cf.domains.lifecycle_reporting.creator_os_lifecycle_bucket(
                {"currentState": "new_unmapped_state"}
            )
            == "unknown"
        )
    finally:
        cf.close()


def test_unknown_native_cost_never_becomes_usd_zero(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        record_ai_cost(
            cf.conn,
            provider="higgsfield",
            operation="motion",
            campaign_id="campaign-1",
            amount=3,
            unit="HIGGSFIELD_CREDITS",
        )

        row = cf.conn.execute(
            "SELECT estimated_cost_usd, cost_state, usd_cost_state, unknown_reason "
            "FROM ai_cost_events"
        ).fetchone()
        assert tuple(row) == (
            0.0,
            "actual",
            "unknown",
            "provider_cost_not_attributable",
        )
        report = cost_summary(cf.conn)
        assert report["total_cost_usd"] is None
        assert report["known_cost_usd"] == 0.0
        assert report["unknown_calls"] == 1
        assert report["cost"] == {
            "amount": None,
            "currency": None,
            "state": "unknown",
            "reason": "one_or_more_provider_costs_not_attributable",
        }
        assert report["by_provider"]["higgsfield"][0]["cost_usd"] is None
        assert report["native_units"] == {"HIGGSFIELD_CREDITS": 3.0}
    finally:
        cf.close()


def test_mixed_known_and_unknown_cost_reports_partial_truth(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        record_ai_cost(
            cf.conn,
            provider="gemini",
            operation="prompt",
            estimated_cost_usd=1.25,
        )
        record_ai_cost(
            cf.conn,
            provider="higgsfield",
            operation="motion",
            amount=2,
            unit="HIGGSFIELD_CREDITS",
        )

        report = cost_summary(cf.conn)
        assert report["total_cost_usd"] is None
        assert report["known_cost_usd"] == 1.25
        assert report["unknown_calls"] == 1
        assert report["by_provider"]["gemini"][0]["cost_state"] == "known"
        assert report["by_provider"]["higgsfield"][0]["cost_state"] == "unknown"
    finally:
        cf.close()


def test_unmapped_threadsdashboard_status_needs_reconciliation(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        report = cf.domains.lifecycle_reporting.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    status="deleted",
                    plan_id=plan["id"],
                )
            ],
        )
        row = report["rows"][0]
        assert row["currentState"] == "needs_reconciliation"
        assert row["blockingReason"] == "unmapped_threadsdash_post_status:deleted"
        assert (
            cf.domains.lifecycle_reporting.creator_os_lifecycle_bucket(row) == "unknown"
        )
    finally:
        cf.close()
