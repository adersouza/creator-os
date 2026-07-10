from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.reel_ledger_promotion import (
    _existing_promotion,
    _promotion_constraint_conflict,
    _record_rejected_promotion_event,
    backfill_promotions,
    promotion_current_state,
    promotion_reconciliation_report,
)


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


def seed_legacy_promotion(cf: CampaignFactory, tmp_path: Path) -> None:
    campaign = cf.upsert_campaign("scheduler", "stacey")
    model = cf.upsert_model("stacey")
    account = cf.upsert_account("legacy-account")
    now = "2026-07-09T12:00:00+00:00"
    output = tmp_path / "render.mp4"
    output.write_bytes(b"render")
    fingerprint = "a" * 64
    cf.conn.execute(
        """
        INSERT INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path,
         filename, created_at, updated_at)
        VALUES ('source_1', ?, ?, 'source-hash', ?, ?, 'render.mp4', ?, ?)
        """,
        (campaign["id"], model["id"], str(output), str(output), now, now),
    )
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path,
         filename, caption_generation_json, created_at, updated_at)
        VALUES ('asset_1', ?, 'source_1', ?, ?, ?, 'render.mp4', ?, ?, ?)
        """,
        (
            campaign["id"],
            fingerprint,
            str(output),
            str(output),
            json.dumps({"generatedAssetLineage": {"contentFingerprint": fingerprint}}),
            now,
            now,
        ),
    )
    cf.conn.execute(
        """
        INSERT INTO distribution_plans
        (id, campaign_id, rendered_asset_id, account_id, surface, reason_code,
         created_at, updated_at)
        VALUES ('dist_1', ?, 'asset_1', ?, 'regular_reel',
                'reel_ledger:slot_1', ?, ?)
        """,
        (campaign["id"], account["id"], now, now),
    )
    cf.conn.commit()


def test_backfill_is_idempotent_and_csv_is_byte_stable(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        seed_legacy_promotion(cf, tmp_path)
        first = backfill_promotions(cf)
        second = backfill_promotions(cf)
        assert first["created"] == 1
        assert second["created"] == 0
        assert second["existing"] == 1
        assert first["csv"].replace(",created,", ",existing,") == second["csv"]
        assert promotion_reconciliation_report(cf)["mismatchCount"] == 0
        event = cf.conn.execute(
            "SELECT * FROM promotion_events WHERE action = 'backfilled'"
        ).fetchone()
        assert event["rendered_asset_id"] == "asset_1"
        assert event["content_fingerprint"] == "a" * 64
        assert event["posting_slot_id"] == "slot_1"
        assert event["reason"] == "legacy_distribution_plan_backfill"
        account_id = cf.conn.execute(
            "SELECT id FROM accounts WHERE handle = 'legacy-account'"
        ).fetchone()["id"]
        current = promotion_current_state(
            cf,
            content_fingerprint="a" * 64,
            account_id=account_id,
            posting_slot_id="slot_1",
        )
        assert current is not None
        assert current["action"] == "backfilled"
        assert _existing_promotion(cf, "slot_1")["stateAction"] == "backfilled"
    finally:
        cf.close()


def test_backfill_quarantines_duplicate_identity_instead_of_raising(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        seed_legacy_promotion(cf, tmp_path)
        first = backfill_promotions(cf)
        assert first["created"] == 1
        campaign_id = cf.campaign_by_slug("scheduler")["id"]
        account_id = cf.conn.execute(
            "SELECT id FROM accounts WHERE handle = 'legacy-account'"
        ).fetchone()["id"]
        now = "2026-07-09T13:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO distribution_plans
            (id, campaign_id, rendered_asset_id, account_id, surface,
             planned_window_start, reason_code, created_at, updated_at)
            VALUES ('dist_duplicate', ?, 'asset_1', ?, 'regular_reel',
                    ?, 'reel_ledger:slot_duplicate', ?, ?)
            """,
            (campaign_id, account_id, now, now, now),
        )
        cf.conn.commit()

        result = backfill_promotions(cf)

        blocked = next(
            row for row in result["rows"] if row["posting_slot_id"] == "slot_duplicate"
        )
        assert blocked["status"] == "blocked"
        assert blocked["reason"] == "duplicate_content_fingerprint_for_account"
        event = promotion_current_state(
            cf,
            content_fingerprint="a" * 64,
            account_id=account_id,
            posting_slot_id="slot_duplicate",
        )
        assert event is not None
        assert event["action"] == "rejected"
        assert event["reason"] == "duplicate_content_fingerprint_for_account"
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM promotions WHERE posting_slot_id = 'slot_duplicate'"
            ).fetchone()[0]
            == 0
        )
        repeated = backfill_promotions(cf)
        assert repeated["csv"] == result["csv"]
        assert (
            cf.conn.execute(
                """
                SELECT COUNT(*) FROM promotion_events
                WHERE posting_slot_id = 'slot_duplicate' AND action = 'rejected'
                """
            ).fetchone()[0]
            == 1
        )
    finally:
        cf.close()


def test_unique_promotion_constraint_allows_one_concurrent_winner(tmp_path: Path):
    cf = make_factory(tmp_path)
    seed_legacy_promotion(cf, tmp_path)
    db_path = cf.settings.db_path
    settings = cf.settings
    campaign_id = cf.campaign_by_slug("scheduler")["id"]
    cf.close()

    def insert(promotion_id: str, slot_id: str) -> str:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO promotions
                (id, promotion_type, campaign_id, rendered_asset_id, account_id, account_group_id,
                 posting_slot_id, content_fingerprint, source_system, created_at, updated_at)
                VALUES (?, 'reel_ledger', ?, 'asset_1', 'account_concurrent', 'stacey', ?, ?,
                        'test', '2026-07-09T13:00:00+00:00', '2026-07-09T13:00:00+00:00')
                """,
                (promotion_id, campaign_id, slot_id, "b" * 64),
            )
            conn.commit()
            return "won"
        except sqlite3.IntegrityError:
            conn.rollback()
            return "lost"
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda args: insert(*args),
                [("promotion_a", "slot_a"), ("promotion_b", "slot_b")],
            )
        )
    assert sorted(outcomes) == ["lost", "won"]
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM promotions WHERE content_fingerprint = ? AND account_id = ?",
            ("b" * 64, "account_concurrent"),
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()

    winner_factory = CampaignFactory(settings)
    try:
        rejected_action = {
            "postingSlotId": "slot_rejected",
            "account": {"id": "account_concurrent"},
            "renderedAsset": {
                "contentHash": "b" * 64,
                "campaignFactoryId": "asset_1",
            },
            "existing": {},
        }
        conflict = _promotion_constraint_conflict(winner_factory, rejected_action)
        assert conflict is not None
        assert conflict["reason"] == "duplicate_content_fingerprint_for_account"
        _record_rejected_promotion_event(winner_factory, rejected_action, conflict)
        winner_factory.conn.commit()
        event = winner_factory.conn.execute(
            "SELECT * FROM promotion_events WHERE action = 'rejected'"
        ).fetchone()
        assert event["reason"] == "duplicate_content_fingerprint_for_account"
        assert event["posting_slot_id"] == "slot_rejected"
    finally:
        winner_factory.close()
