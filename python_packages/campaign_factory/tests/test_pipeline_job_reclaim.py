"""Gap 2: pipeline job crash recovery — stale queued/running reclaim."""

from __future__ import annotations

from pathlib import Path

import pytest
from campaign_test_support import make_factory


def _backdate_job(cf, job_id: str, hours: float) -> None:
    cf.conn.execute(
        "UPDATE pipeline_jobs SET updated_at = datetime('now', ?), created_at = datetime('now', ?) WHERE id = ?",
        (f"-{hours} hours", f"-{hours} hours", job_id),
    )
    cf.conn.commit()


def test_reclaim_fails_stale_running_jobs(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("may", "model")
        stale = cf.domains.events.create_pipeline_job("render", campaign["id"])
        cf.domains.events.start_pipeline_job(stale["id"])
        _backdate_job(cf, stale["id"], 5)

        fresh = cf.domains.events.create_pipeline_job("render", campaign["id"])
        cf.domains.events.start_pipeline_job(fresh["id"])

        done = cf.domains.events.create_pipeline_job("render", campaign["id"])
        cf.domains.events.start_pipeline_job(done["id"])
        cf.domains.events.finish_pipeline_job(done["id"], {"ok": True})

        summary = cf.domains.events.reclaim_stale_pipeline_jobs(2.0)
        assert summary["action"] == "fail"
        assert summary["reclaimedCount"] == 1
        entry = summary["reclaimed"][0]
        assert entry["id"] == stale["id"]
        assert entry["previousStatus"] == "running"
        assert entry["outcome"] == "failed"
        assert entry["ageHours"] >= 2.0

        reloaded = cf.domains.events.pipeline_job(stale["id"])
        assert reloaded["status"] == "failed"
        assert "reclaimed as stale" in reloaded["error"]
        assert reloaded["finishedAt"] is not None

        assert cf.domains.events.pipeline_job(fresh["id"])["status"] == "running"
        assert cf.domains.events.pipeline_job(done["id"])["status"] == "succeeded"
    finally:
        cf.close()


def test_reclaim_requeue_respects_max_attempts(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("may", "model")

        retryable = cf.domains.events.create_pipeline_job("static_mp4", campaign["id"])
        cf.domains.events.start_pipeline_job(retryable["id"])  # attempt_count = 1
        _backdate_job(cf, retryable["id"], 5)

        exhausted = cf.domains.events.create_pipeline_job("static_mp4", campaign["id"])
        cf.domains.events.start_pipeline_job(exhausted["id"])
        cf.conn.execute(
            "UPDATE pipeline_jobs SET attempt_count = 3 WHERE id = ?",
            (exhausted["id"],),
        )
        cf.conn.commit()
        _backdate_job(cf, exhausted["id"], 5)

        summary = cf.domains.events.reclaim_stale_pipeline_jobs(
            2.0, action="requeue", max_attempts=3
        )
        outcomes = {item["id"]: item["outcome"] for item in summary["reclaimed"]}
        assert outcomes[retryable["id"]] == "requeued"
        assert outcomes[exhausted["id"]] == "failed"

        requeued = cf.domains.events.pipeline_job(retryable["id"])
        assert requeued["status"] == "queued"
        assert requeued["error"] is None
        assert requeued["startedAt"] is None
        # attempt count is preserved so retries stay bounded
        assert requeued["attemptCount"] == 1

        failed = cf.domains.events.pipeline_job(exhausted["id"])
        assert failed["status"] == "failed"
        assert "reclaimed as stale" in failed["error"]
    finally:
        cf.close()


def test_reclaim_requeue_holds_unknown_running_effects(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("may", "model")
        ambiguous = cf.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            campaign["id"],
            {"authorizationId": "auth-1"},
        )
        cf.domains.events.start_pipeline_job(ambiguous["id"])
        cf.domains.events.mark_pipeline_effect_state(
            ambiguous["id"], "SUBMISSION_STARTED"
        )
        _backdate_job(cf, ambiguous["id"], 5)

        summary = cf.domains.events.reclaim_stale_pipeline_jobs(2.0, action="requeue")

        entry = summary["reclaimed"][0]
        assert entry["outcome"] == "manual_hold"
        assert entry["effectState"] == "AMBIGUOUS"
        assert entry["safeReplayClass"] == "NEVER_AUTOMATIC"
        assert entry["reconciliationRequired"] is True
        assert entry["authorizationId"] == "auth-1"
        assert entry["externalOperationId"] is None
        assert entry["attemptId"] == f"{ambiguous['id']}:1"
        held = cf.domains.events.pipeline_job(ambiguous["id"])
        assert held["status"] == "running"
        assert held["recovery"]["effectState"] == "AMBIGUOUS"
        assert "manual_hold_unknown_external_effect" in held["error"]
    finally:
        cf.close()


def test_ambiguous_job_requires_reconciliation_and_fresh_authorization(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("may", "model")
        job = cf.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            campaign["id"],
            {"authorizationId": "auth-1"},
        )
        cf.domains.events.start_pipeline_job(job["id"])
        cf.domains.events.mark_pipeline_effect_state(
            job["id"], "SUBMISSION_STARTED"
        )
        cf.domains.events.fail_pipeline_job(job["id"], "provider timeout")
        held = cf.domains.events.pipeline_job(job["id"])
        assert held["status"] == "running"
        assert held["recovery"]["effectState"] == "AMBIGUOUS"

        resolved = cf.domains.events.reconcile_pipeline_external_effect(
            job["id"],
            classification="PROVIDER_PROVED_NO_EFFECT",
            operator="operator-1",
            evidence={"providerCase": "case-1"},
        )
        assert resolved["recovery"]["effectState"] == "NO_EFFECT_CONFIRMED"
        assert resolved["recovery"]["reconciliationClassification"] == (
            "PROVIDER_PROVED_NO_EFFECT"
        )

        retried = cf.domains.events.authorize_pipeline_retry(
            job["id"],
            authorization_id="auth-2",
            operator="operator-1",
        )
        assert retried["status"] == "queued"
        assert retried["recovery"]["effectState"] == "PRE_EFFECT"
        assert retried["recovery"]["authorizationId"] == "auth-2"
        assert retried["recovery"]["attemptId"].endswith(":1")
    finally:
        cf.close()


def test_known_external_id_is_held_for_polling_not_failed(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("may", "model")
        job = cf.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            campaign["id"],
            {"authorizationId": "auth-1", "generationId": "gen-1"},
        )
        cf.domains.events.start_pipeline_job(job["id"])
        _backdate_job(cf, job["id"], 5)

        result = cf.domains.events.reclaim_stale_pipeline_jobs(
            2.0, action="requeue"
        )
        assert result["reclaimed"][0]["outcome"] == "manual_hold"
        held = cf.domains.events.pipeline_job(job["id"])
        assert held["status"] == "running"
        assert held["recovery"]["effectState"] == "EXTERNAL_ID_KNOWN"
        assert held["recovery"]["externalOperationId"] == "gen-1"
        assert held["error"] == "known_external_operation_awaiting_poll"
    finally:
        cf.close()


def test_reclaim_also_covers_stale_queued_jobs(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("may", "model")
        queued = cf.domains.events.create_pipeline_job("render", campaign["id"])
        _backdate_job(cf, queued["id"], 5)

        summary = cf.domains.events.reclaim_stale_pipeline_jobs(2.0)
        assert summary["reclaimedCount"] == 1
        assert summary["reclaimed"][0]["previousStatus"] == "queued"
        assert cf.domains.events.pipeline_job(queued["id"])["status"] == "failed"
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
        campaign = cf.domains.models.upsert_campaign("may", "model")
        corrupted = cf.domains.events.create_pipeline_job("render", campaign["id"])
        cf.domains.events.start_pipeline_job(corrupted["id"])
        cf.conn.execute(
            "UPDATE pipeline_jobs SET updated_at = 'not-a-timestamp', created_at = 'garbage' WHERE id = ?",
            (corrupted["id"],),
        )
        cf.conn.commit()

        summary = cf.domains.events.reclaim_stale_pipeline_jobs(2.0)
        assert summary["reclaimedCount"] == 1
        entry = summary["reclaimed"][0]
        assert entry["id"] == corrupted["id"]
        assert entry["outcome"] == "failed"
        assert entry["ageHours"] is None

        reloaded = cf.domains.events.pipeline_job(corrupted["id"])
        assert reloaded["status"] == "failed"
        assert "unparseable" in reloaded["error"]
    finally:
        cf.close()


def test_reclaim_validates_arguments(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="must be positive"):
            cf.domains.events.reclaim_stale_pipeline_jobs(0)
        with pytest.raises(ValueError, match="unsupported reclaim action"):
            cf.domains.events.reclaim_stale_pipeline_jobs(1.0, action="explode")
    finally:
        cf.close()
