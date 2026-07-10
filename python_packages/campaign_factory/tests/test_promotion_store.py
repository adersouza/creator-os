from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.reel_ledger_promotion import (
    backfill_promotions,
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
    finally:
        cf.close()


def test_unique_promotion_constraint_allows_one_concurrent_winner(tmp_path: Path):
    cf = make_factory(tmp_path)
    seed_legacy_promotion(cf, tmp_path)
    db_path = cf.settings.db_path
    campaign_id = cf.campaign_by_slug("scheduler")["id"]
    cf.close()

    def insert(promotion_id: str, slot_id: str) -> str:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO promotions
                (id, promotion_type, campaign_id, rendered_asset_id, account_id,
                 posting_slot_id, content_fingerprint, source_system, created_at, updated_at)
                VALUES (?, 'reel_ledger', ?, 'asset_1', 'account_concurrent', ?, ?,
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
