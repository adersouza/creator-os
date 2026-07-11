from __future__ import annotations

from datetime import datetime
from pathlib import Path

from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.learning_cohort import (
    COHORT_ID,
    assign_learning_cohort_references,
    audit_learning_cohort,
    learning_cohort_assignment_metadata,
    prepare_learning_cohort,
    run_learning_cohort_day,
)
from pipeline_contracts.validator import validate_contract


def _factory(tmp_path: Path) -> CampaignFactory:
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=tmp_path / "reel_factory",
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def _reference_ready(cf: CampaignFactory) -> None:
    cf.conn.execute(
        """UPDATE learning_cohort_assignments
        SET reference_id = 'stacey_ref', source_family = 'pattern_1',
            content_fingerprint = id || '_fingerprint'"""
    )
    cf.conn.commit()


def test_prepare_is_fixed_balanced_and_idempotent(tmp_path: Path) -> None:
    cf = _factory(tmp_path)
    try:
        first = prepare_learning_cohort(
            cf.conn, start_date="2026-08-01", seed="fixed-seed"
        )
        second = prepare_learning_cohort(
            cf.conn, start_date="2026-09-01", seed="different-seed"
        )
        assert first["assignmentCount"] == 50
        assert first["rankedCount"] == 40
        assert first["controlCount"] == 10
        assert first["controlSurfaceCounts"] == {
            "regular_reel": 5,
            "trial_reel": 5,
        }
        assert second["idempotent"] is True
        rows = cf.conn.execute(
            """SELECT day_index, surface, scheduled_for FROM learning_cohort_assignments
            WHERE cohort_id = ? ORDER BY day_index, scheduled_for""",
            (COHORT_ID,),
        ).fetchall()
        for offset in range(0, 50, 2):
            early, late = rows[offset : offset + 2]
            assert (early["surface"] == "regular_reel") == (early["day_index"] % 2 == 1)
            gap = datetime.fromisoformat(
                late["scheduled_for"]
            ) - datetime.fromisoformat(early["scheduled_for"])
            assert gap.total_seconds() >= 6 * 3600
        assignment_id = cf.conn.execute(
            "SELECT id FROM learning_cohort_assignments ORDER BY day_index, surface LIMIT 1"
        ).fetchone()["id"]
        metadata = learning_cohort_assignment_metadata(cf.conn, assignment_id)
        validate_contract(metadata, "learning_cohort.v1.schema.json")
    finally:
        cf.close()


def test_run_day_is_idempotent_and_pauses_for_old_approval_backlog(
    tmp_path: Path,
) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        _reference_ready(cf)
        first = run_learning_cohort_day(cf.conn, day_index=1)
        second = run_learning_cohort_day(cf.conn, day_index=1)
        assert first["status"] == second["status"] == "queued_for_generation"
        assert {row["generationState"] for row in second["assignments"]} == {"queued"}
        cf.conn.execute(
            """UPDATE learning_cohort_assignments SET draft_id = 'draft_old'
            WHERE cohort_id = ? AND day_index = 1 AND surface = 'regular_reel'""",
            (COHORT_ID,),
        )
        cf.conn.commit()
        blocked = run_learning_cohort_day(cf.conn, day_index=4)
        assert blocked["status"] == "paused"
        assert "approval_backlog_exceeds_two_days" in blocked["blockingReasons"]
    finally:
        cf.close()


def test_reference_assignment_is_previewable_idempotent_and_identity_bound(
    tmp_path: Path,
) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        campaign_id = cf.conn.execute(
            "SELECT id FROM campaigns WHERE slug = ?", (COHORT_ID,)
        ).fetchone()["id"]
        now = "2026-07-11T00:00:00Z"
        cf.conn.execute(
            """INSERT INTO reference_patterns
            (id, cluster_key, rank, label, imported_at, updated_at)
            VALUES ('pattern_1', 'cluster_1', 1, 'Pattern 1', ?, ?)""",
            (now, now),
        )
        cf.conn.execute(
            """INSERT INTO campaign_reference_plans
            (id, campaign_id, reference_pattern_id, created_at, updated_at)
            VALUES ('plan_1', ?, 'pattern_1', ?, ?)""",
            (campaign_id, now, now),
        )
        cf.conn.commit()
        source = tmp_path / "stacey.png"
        source.write_bytes(b"stacey")
        manifest = tmp_path / "stacey.json"
        manifest.write_text(
            __import__("json").dumps(
                {
                    "creator": "Stacey",
                    "status": "ready",
                    "referenceSetId": "stacey_set",
                    "sourceImages": [
                        {
                            "path": str(source),
                            "sha256": "a" * 64,
                            "status": "embedded",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        preview = assign_learning_cohort_references(
            cf.conn, identity_manifest_path=manifest
        )
        assert preview["dryRun"] is True
        assert preview["changes"] == 50
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM learning_cohort_assignments WHERE reference_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        applied = assign_learning_cohort_references(
            cf.conn, identity_manifest_path=manifest, apply=True
        )
        repeat = assign_learning_cohort_references(
            cf.conn, identity_manifest_path=manifest
        )
        assert applied["changes"] == 50
        assert repeat["changes"] == 0
        assert (
            run_learning_cohort_day(cf.conn, day_index=1)["status"]
            == "queued_for_generation"
        )
    finally:
        cf.close()


def test_run_day_blocks_when_reference_assignment_is_missing(tmp_path: Path) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        result = run_learning_cohort_day(cf.conn, day_index=1)
        assert result["status"] == "paused"
        assert "reference_assignment_missing" in result["blockingReasons"]
    finally:
        cf.close()


def test_audit_requires_complete_evidence_and_computes_lift(tmp_path: Path) -> None:
    cf = _factory(tmp_path)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-08-01")
        assert audit_learning_cohort(cf.conn)["passed"] is False
        cf.conn.execute(
            """UPDATE learning_cohort_assignments
            SET metric_1h_state = 'complete', metric_24h_state = 'complete',
                metric_72h_state = CASE WHEN surface = 'trial_reel'
                  THEN 'complete' ELSE 'not_required' END,
                reward_24h = CASE WHEN arm = 'ranked' THEN 120.0 ELSE 100.0 END"""
        )
        cf.conn.commit()
        result = audit_learning_cohort(cf.conn)
        assert result["passed"] is True
        assert result["lift"]["overallLift"] == 0.2
        assert result["lift"]["bootstrapPositiveConfidence"] == 1.0
    finally:
        cf.close()
