from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from campaign_factory.adapters.threadsdash_metrics_ingestion import (
    _record_immutable_performance_observation,
)
from campaign_factory.operator_status import recovery_status
from campaign_test_support import make_factory


def _snapshot(*, views: int, created_at: str) -> dict[str, object]:
    raw = {
        "id": "post-1",
        "snapshot_at": "2026-07-29T12:00:00Z",
        "views": views,
    }
    return {
        "id": f"snapshot-{views}",
        "post_id": "post-1",
        "snapshot_at": "2026-07-29T12:00:00Z",
        "views": views,
        "metrics_eligible": 1,
        "raw_json": json.dumps(raw, sort_keys=True),
        "created_at": created_at,
    }


def test_metric_corrections_append_and_never_rewrite_raw_observations(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        first = _record_immutable_performance_observation(
            cf.conn,
            _snapshot(views=10, created_at="2026-07-29T12:01:00Z"),
        )
        duplicate = _record_immutable_performance_observation(
            cf.conn,
            _snapshot(views=10, created_at="2026-07-29T12:02:00Z"),
        )
        corrected = _record_immutable_performance_observation(
            cf.conn,
            _snapshot(views=12, created_at="2026-07-29T12:03:00Z"),
        )
        cf.conn.commit()

        assert duplicate == first
        assert corrected != first
        rows = cf.conn.execute(
            """
            SELECT id, supersedes_observation_id, correction_reason
            FROM performance_snapshot_observations
            ORDER BY created_at
            """
        ).fetchall()
        assert len(rows) == 2
        assert rows[1]["supersedes_observation_id"] == first
        assert rows[1]["correction_reason"] == "source_payload_changed"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            cf.conn.execute(
                "UPDATE performance_snapshot_observations SET raw_json = '{}'"
            )
    finally:
        cf.close()


def test_recovery_status_uses_scoped_blocker_language(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("may", "model")
        job = cf.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            campaign["id"],
            {"authorizationId": "auth-1"},
        )
        cf.domains.events.start_pipeline_job(job["id"])
        cf.domains.events.mark_pipeline_effect_state(job["id"], "SUBMISSION_STARTED")
        cf.domains.events.fail_pipeline_job(job["id"], "timeout")

        report = recovery_status(cf.conn)
        assert report["mappingBlockersSummary"] == "Mapping blockers: none."
        assert report["operationalRecoveryGapCount"] == 1
        assert (
            report["operationalRecoveryGaps"]["ambiguousExternalEffects"][0]["id"]
            == job["id"]
        )
    finally:
        cf.close()
