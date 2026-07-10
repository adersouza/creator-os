"""Gap 2: pipeline job crash recovery — stale queued/running reclaim."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_core import make_factory


def _backdate_job(cf, job_id: str, hours: float) -> None:
    cf.conn.execute(
        "UPDATE pipeline_jobs SET updated_at = datetime('now', ?), created_at = datetime('now', ?) WHERE id = ?",
        (f"-{hours} hours", f"-{hours} hours", job_id),
    )
    cf.conn.commit()


def test_reclaim_fails_stale_running_jobs(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("may", "model")
        stale = cf.create_pipeline_job("render", campaign["id"])
        cf.start_pipeline_job(stale["id"])
        _backdate_job(cf, stale["id"], 5)

        fresh = cf.create_pipeline_job("render", campaign["id"])
        cf.start_pipeline_job(fresh["id"])

        done = cf.create_pipeline_job("render", campaign["id"])
        cf.start_pipeline_job(done["id"])
        cf.finish_pipeline_job(done["id"], {"ok": True})
        _backdate_job(cf, done["id"], 10)

        summary = cf.reclaim_stale_pipeline_jobs(2.0)
        assert summary["action"] == "fail"
        assert summary["reclaimedCount"] == 1
        entry = summary["reclaimed"][0]
        assert entry["id"] == stale["id"]
        assert entry["previousStatus"] == "running"
        assert entry["outcome"] == "failed"
        assert entry["ageHours"] >= 2.0

        reloaded = cf.pipeline_job(stale["id"])
        assert reloaded["status"] == "failed"
        assert "reclaimed as stale" in reloaded["error"]
        assert reloaded["finishedAt"] is not None

        assert cf.pipeline_job(fresh["id"])["status"] == "running"
        assert cf.pipeline_job(done["id"])["status"] == "succeeded"
    finally:
        cf.close()


def test_reclaim_requeue_respects_max_attempts(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("may", "model")

        retryable = cf.create_pipeline_job("render", campaign["id"])
        cf.start_pipeline_job(retryable["id"])  # attempt_count = 1
        _backdate_job(cf, retryable["id"], 5)

        exhausted = cf.create_pipeline_job("render", campaign["id"])
        for _ in range(3):
            cf.start_pipeline_job(exhausted["id"])  # attempt_count = 3
        _backdate_job(cf, exhausted["id"], 5)

        summary = cf.reclaim_stale_pipeline_jobs(2.0, action="requeue", max_attempts=3)
        outcomes = {item["id"]: item["outcome"] for item in summary["reclaimed"]}
        assert outcomes[retryable["id"]] == "requeued"
        assert outcomes[exhausted["id"]] == "failed"

        requeued = cf.pipeline_job(retryable["id"])
        assert requeued["status"] == "queued"
        assert requeued["error"] is None
        assert requeued["startedAt"] is None
        # attempt count is preserved so retries stay bounded
        assert requeued["attemptCount"] == 1

        failed = cf.pipeline_job(exhausted["id"])
        assert failed["status"] == "failed"
        assert "reclaimed as stale" in failed["error"]
    finally:
        cf.close()


def test_reclaim_also_covers_stale_queued_jobs(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("may", "model")
        queued = cf.create_pipeline_job("render", campaign["id"])
        _backdate_job(cf, queued["id"], 5)

        summary = cf.reclaim_stale_pipeline_jobs(2.0)
        assert summary["reclaimedCount"] == 1
        assert summary["reclaimed"][0]["previousStatus"] == "queued"
        assert cf.pipeline_job(queued["id"])["status"] == "failed"
    finally:
        cf.close()


def test_reclaim_recovers_jobs_with_corrupted_timestamps(tmp_path: Path):
    """A running job with unparseable timestamps must not be stranded forever.

    Before the fix, _job_is_stuck() returned (False, None) for corrupted
    updated_at/created_at, so the job could never age past the threshold and
    stayed 'running' silently — a permanent invisible wedge. Reclaim must fail
    it loudly with an explicit unknown-age message.
    """
    cf = make_factory(tmp_path)
    try:
        campaign = cf.upsert_campaign("may", "model")
        corrupted = cf.create_pipeline_job("render", campaign["id"])
        cf.start_pipeline_job(corrupted["id"])
        cf.conn.execute(
            "UPDATE pipeline_jobs SET updated_at = 'not-a-timestamp', created_at = 'garbage' WHERE id = ?",
            (corrupted["id"],),
        )
        cf.conn.commit()

        summary = cf.reclaim_stale_pipeline_jobs(2.0)
        assert summary["reclaimedCount"] == 1
        entry = summary["reclaimed"][0]
        assert entry["id"] == corrupted["id"]
        assert entry["outcome"] == "failed"
        assert entry["ageHours"] is None

        reloaded = cf.pipeline_job(corrupted["id"])
        assert reloaded["status"] == "failed"
        assert "unparseable" in reloaded["error"]
    finally:
        cf.close()


def test_reclaim_validates_arguments(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="must be positive"):
            cf.reclaim_stale_pipeline_jobs(0)
        with pytest.raises(ValueError, match="unsupported reclaim action"):
            cf.reclaim_stale_pipeline_jobs(1.0, action="explode")
    finally:
        cf.close()
