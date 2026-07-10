"""Gap 4 regression tests: uniqueness/idempotency for distribution plans and assignments."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from campaign_factory.db import init_db
from test_core import add_rendered_asset, isolate_account_groups, make_factory


def _plan_count(cf, rendered_asset_id: str = "asset_1") -> int:
    row = cf.conn.execute(
        "SELECT COUNT(*) AS n FROM distribution_plans WHERE rendered_asset_id = ?",
        (rendered_asset_id,),
    ).fetchone()
    return int(row["n"])


def test_create_distribution_plan_is_idempotent_for_same_target(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1"])

        first = cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_1",
            planned_window_start="2026-01-02T10:00:00+00:00",
        )
        second = cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_1",
            planned_window_start="2026-01-02T10:00:00+00:00",
        )

        assert first["id"] == second["id"]
        assert _plan_count(cf) == 1
    finally:
        cf.conn.close()


def test_create_distribution_plan_distinct_targets_create_distinct_plans(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1", "ig_2"])

        a = cf.create_distribution_plan("asset_1", instagram_account_id="ig_1")
        b = cf.create_distribution_plan("asset_1", instagram_account_id="ig_2")

        assert a["id"] != b["id"]
        assert _plan_count(cf) == 2
    finally:
        cf.conn.close()


def test_distribution_plan_unique_index_rejects_raw_duplicate_insert(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1"])
        plan = cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_1",
            planned_window_start="2026-01-02T10:00:00+00:00",
        )
        row = cf.conn.execute(
            "SELECT * FROM distribution_plans WHERE id = ?", (plan["id"],)
        ).fetchone()

        duplicate = dict(row)
        duplicate["id"] = "dist_duplicate"
        columns = ", ".join(duplicate.keys())
        placeholders = ", ".join("?" for _ in duplicate)
        with pytest.raises(sqlite3.IntegrityError):
            cf.conn.execute(
                f"INSERT INTO distribution_plans ({columns}) VALUES ({placeholders})",
                tuple(duplicate.values()),
            )
    finally:
        cf.conn.close()


def test_asset_account_assignment_unique_index_rejects_duplicates(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        isolate_account_groups(cf, ["ig_1"])
        campaign_id = cf.campaign_by_slug("may")["id"]

        def insert_assignment(row_id: str) -> None:
            cf.conn.execute(
                """
                INSERT INTO asset_account_assignments
                (id, campaign_id, rendered_asset_id, account_id, instagram_account_id,
                 planned_window_start, created_at, updated_at)
                VALUES (?, ?, 'asset_1', NULL, 'ig_1',
                        '2026-01-02T10:00:00+00:00',
                        '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """,
                (row_id, campaign_id),
            )

        insert_assignment("assign_1")
        with pytest.raises(sqlite3.IntegrityError):
            insert_assignment("assign_duplicate")
    finally:
        cf.conn.close()


def test_migration_dedupes_preexisting_duplicate_plans(tmp_path: Path):
    """Simulates a pre-migration DB with duplicate plan rows and verifies the
    schema migration keeps exactly one row per logical target."""
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1"])
        plan = cf.create_distribution_plan(
            "asset_1",
            instagram_account_id="ig_1",
            planned_window_start="2026-01-02T10:00:00+00:00",
        )
        # Drop the unique index to emulate a legacy DB, insert a duplicate,
        # then re-run migrations.
        cf.conn.execute("DROP INDEX IF EXISTS idx_distribution_plans_uniqueness")
        row = dict(
            cf.conn.execute(
                "SELECT * FROM distribution_plans WHERE id = ?", (plan["id"],)
            ).fetchone()
        )
        row["id"] = "dist_legacy_duplicate"
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        cf.conn.execute(
            f"INSERT INTO distribution_plans ({columns}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        cf.conn.commit()

        init_db(cf.conn)

        assert _plan_count(cf) == 1
        remaining = cf.conn.execute(
            "SELECT id FROM distribution_plans WHERE rendered_asset_id = 'asset_1'"
        ).fetchone()["id"]
        assert remaining == plan["id"], "migration should keep the oldest row"
    finally:
        cf.conn.close()
