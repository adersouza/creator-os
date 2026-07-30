from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from campaign_factory.cost_tracker import ensure_cost_table, record_ai_cost
from campaign_factory.production_higgsfield_authorization import (
    provider_control_reconciliation,
)
from campaign_factory.provider_spend import ensure_authorization_table
from campaign_test_support import make_factory


def _race(tmp_path: Path, job_id: str, actions):
    barrier = Barrier(len(actions))

    def invoke(action):
        factory = make_factory(tmp_path)
        try:
            barrier.wait(timeout=5)
            try:
                return ("ok", action(factory, job_id)["status"])
            except RuntimeError as exc:
                return ("conflict", str(exc))
        finally:
            factory.close()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(invoke, actions))


def test_start_is_compare_and_swap_under_concurrent_workers(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job("render", None)
    finally:
        factory.close()

    results = _race(
        tmp_path,
        job["id"],
        [lambda cf, job_id: cf.domains.events.start_pipeline_job(job_id)] * 2,
    )
    assert [result[0] for result in results].count("ok") == 1
    assert [result[0] for result in results].count("conflict") == 1

    reloaded = make_factory(tmp_path)
    try:
        row = reloaded.domains.events.pipeline_job(job["id"])
        assert row["status"] == "running"
        assert row["attemptCount"] == 1
    finally:
        reloaded.close()


def test_provider_reconciliation_reports_consumed_without_submission(
    tmp_path: Path,
) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            None,
            {"authorizationId": "authorization-1", "workItemId": "work-1"},
        )
        factory.domains.events.start_pipeline_job(job["id"])
        factory.domains.events.mark_pipeline_effect_state(
            job["id"],
            "AUTHORIZATION_CONSUMED",
            authorization_id="authorization-1",
        )

        report = provider_control_reconciliation(factory)

        assert report["ok"] is False
        assert report["automaticProviderCalls"] == 0
        assert report["issues"][0]["observedConflict"] == (
            "consumed_authorization_without_submission_receipt"
        )
    finally:
        factory.close()


def test_provider_completion_failure_remains_recoverable(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            None,
            {"authorizationId": "authorization-1", "workItemId": "work-1"},
        )
        factory.domains.events.start_pipeline_job(job["id"])
        factory.domains.events.mark_pipeline_effect_state(
            job["id"], "AUTHORIZATION_CONSUMED"
        )
        factory.domains.events.mark_pipeline_effect_state(
            job["id"], "SUBMISSION_STARTED"
        )
        factory.domains.events.mark_pipeline_effect_state(
            job["id"],
            "EXTERNAL_ID_KNOWN",
            external_operation_id="generation-1",
        )
        factory.domains.events.mark_pipeline_effect_state(
            job["id"], "PROVIDER_COMPLETED"
        )

        recovered = factory.domains.events.fail_pipeline_job(
            job["id"], "download_interrupted"
        )

        assert recovered["status"] == "running"
        assert recovered["recovery"]["effectState"] == "PROVIDER_COMPLETED"
        assert recovered["recovery"]["externalOperationId"] == "generation-1"
    finally:
        factory.close()


def test_cost_reconciled_technical_rejection_is_terminal(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            None,
            {"workItemId": "work-1"},
        )
        factory.domains.events.start_pipeline_job(job["id"])
        for state in (
            "AUTHORIZATION_CONSUMED",
            "SUBMISSION_STARTED",
            "EXTERNAL_ID_KNOWN",
            "PROVIDER_COMPLETED",
            "OUTPUT_DOWNLOADED",
            "OUTPUT_RETAINED",
            "COST_RECONCILED",
        ):
            factory.domains.events.mark_pipeline_effect_state(job["id"], state)

        rejected = factory.domains.events.fail_pipeline_job(
            job["id"],
            "higgsfield_silent_candidate_returned_audio",
            {"technicalRejection": "unexpected_provider_audio"},
            terminal_effect_reconciled=True,
        )

        assert rejected["status"] == "failed"
        assert rejected["recovery"]["effectState"] == "FINALIZED"
    finally:
        factory.close()


def test_legacy_provider_completion_can_reconcile_directly_to_retained(
    tmp_path: Path,
) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job(
            "higgsfield_motion_generation", None
        )
        factory.domains.events.start_pipeline_job(job["id"])
        for state in (
            "AUTHORIZATION_CONSUMED",
            "SUBMISSION_STARTED",
            "EXTERNAL_ID_KNOWN",
            "PROVIDER_COMPLETED",
        ):
            factory.domains.events.mark_pipeline_effect_state(job["id"], state)

        retained = factory.domains.events.mark_pipeline_effect_state(
            job["id"], "OUTPUT_RETAINED"
        )

        assert retained["recovery"]["effectState"] == "OUTPUT_RETAINED"
    finally:
        factory.close()


def test_provider_attempt_retains_identity_through_download_and_retention(
    tmp_path: Path,
) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            None,
            {"workItemId": "work-1", "provider": "higgsfield"},
        )
        factory.domains.events.start_pipeline_job(job["id"])
        factory.domains.events.mark_pipeline_effect_state(
            job["id"],
            "AUTHORIZATION_CONSUMED",
            evidence={"providerRequestFingerprint": "a" * 64},
        )
        factory.domains.events.mark_pipeline_effect_state(
            job["id"], "SUBMISSION_STARTED"
        )
        factory.domains.events.mark_pipeline_effect_state(
            job["id"],
            "EXTERNAL_ID_KNOWN",
            external_operation_id="generation-1",
        )
        factory.domains.events.mark_pipeline_effect_state(
            job["id"], "PROVIDER_COMPLETED"
        )
        factory.domains.events.mark_pipeline_effect_state(
            job["id"],
            "OUTPUT_DOWNLOADED",
            evidence={"temporaryPath": "/tmp/staged", "outputSha256": "b" * 64},
        )
        retained = factory.domains.events.mark_pipeline_effect_state(
            job["id"],
            "OUTPUT_RETAINED",
            evidence={"outputPath": "/tmp/final"},
        )

        assert retained["recovery"]["effectState"] == "OUTPUT_RETAINED"
        assert (
            retained["recovery"]["reconciliation"]["providerRequestFingerprint"]
            == "a" * 64
        )
        assert retained["recovery"]["reconciliation"]["temporaryPath"] == (
            "/tmp/staged"
        )
        assert retained["recovery"]["reconciliation"]["outputPath"] == "/tmp/final"
    finally:
        factory.close()


def test_provider_reconciliation_reports_expiry_cost_and_offline_recovery(
    tmp_path: Path,
) -> None:
    factory = make_factory(tmp_path)
    try:
        ensure_authorization_table(factory.conn)
        ensure_cost_table(factory.conn)
        rows = [
            ("expired", "res-expired", "authorized", 5.0, "2020-01-01T00:00:00Z"),
            ("overspend", "res-overspend", "consumed", 5.0, "2099-01-01T00:00:00Z"),
            ("unknown", "res-unknown", "consumed", 5.0, "2099-01-01T00:00:00Z"),
        ]
        for suffix, reservation, status, amount, expires_at in rows:
            factory.conn.execute(
                """
                INSERT INTO provider_spend_authorizations
                  (authorization_id, reservation_id, provider, campaign_id,
                   cohort_id, request_fingerprint, amount, unit, scope_json,
                   provider_quote_json, status, issued_at, expires_at)
                VALUES (?, ?, 'higgsfield', NULL, ?, ?, ?, 'higgsfield_credits',
                        '{}', '{}', ?, '2026-01-01T00:00:00Z', ?)
                """,
                (
                    f"auth-{suffix}",
                    reservation,
                    suffix,
                    (suffix[0] * 64),
                    amount,
                    status,
                    expires_at,
                ),
            )
        record_ai_cost(
            factory.conn,
            provider="higgsfield",
            operation="video_generation",
            source_event_key="overspend-event",
            reservation_id="res-overspend",
            amount=7.0,
            unit="higgsfield_credits",
            metadata={"overspend": True},
            ensure_schema=False,
        )
        record_ai_cost(
            factory.conn,
            provider="higgsfield",
            operation="video_generation",
            source_event_key="unknown-event",
            reservation_id="res-unknown",
            amount=None,
            unit=None,
            metadata={},
            ensure_schema=False,
        )
        recovered = factory.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            None,
            {"workItemId": "recovered-work"},
        )
        factory.domains.events.start_pipeline_job(recovered["id"])
        factory.domains.events.finish_pipeline_job(
            recovered["id"],
            {
                "worker": {
                    "reconciledCompletedRequest": True,
                    "providerCalls": 0,
                }
            },
        )

        report = provider_control_reconciliation(factory)
        conflicts = {issue["observedConflict"] for issue in report["issues"]}

        assert "authorized_provider_spend_expired" in conflicts
        assert "provider_actual_exceeds_authorization" in conflicts
        assert "provider_actual_credits_unknown" in conflicts
        assert report["observations"] == [
            {
                "record": recovered["id"],
                "observation": ("completed_receipt_recovered_without_provider_call"),
            }
        ]
    finally:
        factory.close()


def test_terminal_transition_is_immutable_under_finish_fail_race(
    tmp_path: Path,
) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job("render", None)
        factory.domains.events.start_pipeline_job(job["id"])
    finally:
        factory.close()

    results = _race(
        tmp_path,
        job["id"],
        [
            lambda cf, job_id: cf.domains.events.finish_pipeline_job(
                job_id, {"winner": "finish"}
            ),
            lambda cf, job_id: cf.domains.events.fail_pipeline_job(
                job_id, "failure winner", {"winner": "fail"}
            ),
        ],
    )
    assert [result[0] for result in results].count("ok") == 1
    assert [result[0] for result in results].count("conflict") == 1

    reloaded = make_factory(tmp_path)
    try:
        row = reloaded.domains.events.pipeline_job(job["id"])
        terminal = row["status"]
        assert terminal in {"succeeded", "failed"}
        with pytest.raises(RuntimeError, match="pipeline_job_transition_conflict"):
            reloaded.domains.events.finish_pipeline_job(job["id"], {"late": True})
        with pytest.raises(RuntimeError, match="pipeline_job_transition_conflict"):
            reloaded.domains.events.fail_pipeline_job(job["id"], "late")
        assert reloaded.domains.events.pipeline_job(job["id"])["status"] == terminal
        with pytest.raises(
            sqlite3.IntegrityError, match="terminal pipeline jobs are immutable"
        ):
            reloaded.conn.execute(
                "UPDATE pipeline_jobs SET error = 'direct mutation' WHERE id = ?",
                (job["id"],),
            )
    finally:
        reloaded.close()


def test_reclaim_rowcount_does_not_claim_a_concurrent_start(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job("render", None)
        factory.conn.execute(
            "UPDATE pipeline_jobs SET updated_at = datetime('now', '-5 hours'), "
            "created_at = datetime('now', '-5 hours') WHERE id = ?",
            (job["id"],),
        )
        factory.conn.commit()
    finally:
        factory.close()

    barrier = Barrier(2)

    def start():
        local = make_factory(tmp_path)
        try:
            barrier.wait(timeout=5)
            try:
                local.domains.events.start_pipeline_job(job["id"])
                return "started"
            except RuntimeError:
                return "conflict"
        finally:
            local.close()

    def reclaim():
        local = make_factory(tmp_path)
        try:
            barrier.wait(timeout=5)
            return local.domains.events.reclaim_stale_pipeline_jobs(2.0)
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        start_future = pool.submit(start)
        reclaim_future = pool.submit(reclaim)
        start_result = start_future.result()
        reclaim_result = reclaim_future.result()

    reloaded = make_factory(tmp_path)
    try:
        status = reloaded.domains.events.pipeline_job(job["id"])["status"]
        assert (start_result, status, reclaim_result["reclaimedCount"]) in {
            ("started", "running", 0),
            ("conflict", "failed", 1),
        }
    finally:
        reloaded.close()
