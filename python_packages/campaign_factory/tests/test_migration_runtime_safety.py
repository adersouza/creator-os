from __future__ import annotations

import io
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from campaign_asset_test_support import add_surface_asset_fixture
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.db import _repair_source_asset_fk_references
from campaign_test_support import make_factory


def test_db_repair_restores_source_asset_foreign_key_table_names():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        CREATE TABLE source_assets (id TEXT PRIMARY KEY);
        CREATE TABLE source_assets_old_global_hash (id TEXT PRIMARY KEY);
        CREATE TABLE render_jobs (
          id TEXT PRIMARY KEY,
          source_asset_id TEXT NOT NULL,
          FOREIGN KEY(source_asset_id) REFERENCES "source_assets_old_global_hash"(id)
        );
        INSERT INTO render_jobs (id, source_asset_id) VALUES ('job_1', 'src_1');
        """
    )

    _repair_source_asset_fk_references(conn)

    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'render_jobs'"
    ).fetchone()["sql"]
    assert "source_assets_old_global_hash" not in sql
    assert "source_assets" in sql
    assert conn.execute("SELECT COUNT(*) AS c FROM render_jobs").fetchone()["c"] == 1


def test_activity_and_pipeline_job_tables_initialize_and_helpers_work(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        tables = {
            row["name"]
            for row in cf.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "activity_events" in tables
        assert "pipeline_jobs" in tables

        campaign = cf.domains.models.upsert_campaign("may", "model")
        job = cf.domains.events.create_pipeline_job(
            "import_folder", campaign["id"], {"supabaseServiceRoleKey": "secret"}
        )
        assert job["status"] == "queued"
        assert job["input"]["supabaseServiceRoleKey"] == "<redacted>"
        cf.domains.events.start_pipeline_job(job["id"])
        cf.domains.events.record_event(
            "source_imported",
            campaign_id=campaign["id"],
            pipeline_job_id=job["id"],
            status="success",
            message="test event",
            metadata={"service_role_key": "secret", "count": 1},
        )
        finished = cf.domains.events.finish_pipeline_job(job["id"], {"ok": True})
        assert finished["status"] == "succeeded"
        events = cf.domains.events.events_for_campaign("may")
        assert events[0]["message"] == "test event"
        assert events[0]["metadata"]["service_role_key"] == "<redacted>"
        assert cf.domains.events.jobs_for_campaign("may")[0]["id"] == job["id"]
    finally:
        cf.close()


def test_run_reel_failure_records_failed_job_and_event(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 7, stdout="", stderr="render failed")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may", hooks=["hook"]
        )
        result = cf.domains.reel_execution.run_reel_factory(campaign_slug="may")
        assert result["returncode"] == 7
        job = cf.domains.events.pipeline_job(result["pipelineJobId"])
        assert job["status"] == "failed"
        events = cf.domains.events.events_for_campaign("may")
        assert any(event["eventType"] == "reel_render_failed" for event in events)
    finally:
        cf.close()


def test_creator_os_final_certification_proofs_are_read_only_and_evidence_based(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        live = cf.domains.live_scale.creator_os_live_100_account_readiness()
        runbook = cf.domains.live_scale.creator_os_live_scale_runbook()
        live_scorecard = cf.domains.live_scale.creator_os_live_scale_scorecard()
        production_trial = (
            cf.domains.parent_factory_trials.parent_factory_production_trial()
        )
        production_scorecard = (
            cf.domains.parent_factory_trials.parent_factory_production_scorecard()
        )
        real_yield = cf.domains.parent_factory_trials.parent_factory_real_yield_report()
        prevention = cf.domains.discoverability.discoverability_prevention_audit()
        prevention_scorecard = (
            cf.domains.discoverability.discoverability_prevention_scorecard()
        )
        story = cf.domains.story_management.story_production_readiness()
        story_gap = cf.domains.story_management.story_proof_gap_analysis()
        story_certification = cf.domains.story_management.story_certification_proof()
        carousel = cf.domains.carousel_integrity.carousel_production_readiness()
        carousel_gap = cf.domains.carousel_integrity.carousel_proof_gap_analysis()
        carousel_certification = (
            cf.domains.carousel_integrity.carousel_certification_proof()
        )
        certification = cf.domains.certification.creator_os_certification_report()

        assert cf.conn.total_changes == before
        assert live["schema"] == "creator_os.live_100_account_readiness.v1"
        assert {
            "canRun100AccountsToday",
            "blockingReason",
            "requiredInventory",
            "requiredParentsPerDay",
            "expectedOperatorLoad",
            "expectedExceptionRate",
        } <= set(live)
        assert {
            "eligibleAccounts",
            "restrictedAccounts",
            "warmingAccounts",
            "validatedDraftBuffer",
            "safeToRun100Accounts",
        } <= set(live)
        assert live["dataSource"] == "actual_current_state"
        assert runbook["schema"] == "creator_os.live_scale_runbook.v1"
        assert runbook["steps"]
        assert live_scorecard["schema"] == "creator_os.live_scale_scorecard.v1"
        assert (
            production_trial["schema"]
            == "creator_os.parent_factory_production_trial.v1"
        )
        assert {
            "rawCandidates",
            "qualityPassed",
            "discoverabilityPassed",
            "publishabilityPassed",
            "acceptedParents",
            "yieldPct",
            "operatorMinutes",
        } <= set(production_trial)
        assert (
            production_scorecard["schema"]
            == "creator_os.parent_factory_production_scorecard.v1"
        )
        assert real_yield["schema"] == "creator_os.parent_factory_real_yield_report.v1"
        assert prevention["schema"] == "creator_os.discoverability_prevention_audit.v1"
        assert {
            "violationsCaughtBeforeRender",
            "violationsCaughtAfterRender",
            "violationsCaughtAtPublishability",
        } <= set(prevention)
        assert (
            prevention_scorecard["schema"]
            == "creator_os.discoverability_prevention_scorecard.v1"
        )
        assert story["schema"] == "creator_os.story_production_readiness.v1"
        assert story["publishProofMissing"] is True
        assert story_gap["schema"] == "creator_os.story_proof_gap_analysis.v1"
        assert (
            story_certification["schema"] == "creator_os.story_certification_proof.v1"
        )
        assert story_certification["storyCreated"] is False
        assert story_certification["storyPublished"] is False
        assert story_certification["status"] == "blocked"
        assert "story_asset_missing" in story_certification["blockers"]
        assert carousel["schema"] == "creator_os.carousel_production_readiness.v1"
        assert carousel["publishProofMissing"] is True
        assert carousel_gap["schema"] == "creator_os.carousel_proof_gap_analysis.v1"
        assert (
            carousel_certification["schema"]
            == "creator_os.carousel_certification_proof.v1"
        )
        assert carousel_certification["carouselCreated"] is False
        assert carousel_certification["carouselPublished"] is False
        assert carousel_certification["status"] == "blocked"
        assert "carousel_asset_missing" in carousel_certification["blockers"]
        assert certification["schema"] == "creator_os.certification_report.v1"
        assert certification["storyCertified"] is False
        assert certification["carouselCertified"] is False
        assert certification["100AccountCertified"] is False
        assert 0 <= certification["finalRating"] <= 10
        assert "maximumAchievableRating" not in certification
        assert "singleHighestROITask" not in certification
        assert "projectedRating" not in certification
        assert all(
            item["wouldWrite"] is False
            for item in [
                live,
                runbook,
                live_scorecard,
                production_trial,
                production_scorecard,
                real_yield,
                prevention,
                prevention_scorecard,
                story,
                story_gap,
                story_certification,
                carousel,
                carousel_gap,
                carousel_certification,
                certification,
            ]
        )
    finally:
        cf.close()


def test_creator_os_staged_operational_acceptance_uses_actual_evidence_and_is_read_only(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        stage_10 = cf.domains.live_acceptance.creator_os_live_account_acceptance(
            account_target=10
        )
        staged = cf.domains.live_acceptance.creator_os_staged_live_acceptance()

        assert cf.conn.total_changes == before
        assert stage_10["schema"] == "creator_os.live_account_acceptance.v1"
        assert stage_10["accountTarget"] == 10
        assert stage_10["passCriteria"] == {
            "missedDispatches": 0,
            "duplicatePublishes": 0,
            "restrictedAccountsScheduled": 0,
            "surfaceContractViolations": 0,
            "inventoryBufferMaintained": True,
            "metricsImported": True,
            "exceptionQueueWithinThreshold": True,
        }
        assert {
            "missedDispatches",
            "duplicatePublishes",
            "restrictedAccountsScheduled",
            "surfaceContractViolations",
            "inventoryBufferMaintained",
            "metricsImported",
            "exceptionQueueWithinThreshold",
        } <= set(stage_10["actuals"])
        assert stage_10["dataSource"] == "actual_current_state"
        assert stage_10["wouldWrite"] is False
        assert staged["schema"] == "creator_os.staged_live_acceptance.v1"
        assert [row["accountTarget"] for row in staged["stages"]] == [10, 25, 50, 100]
        assert staged["currentCertifiedStage"] in [0, 10, 25, 50, 100]
        assert staged["nextStageTarget"] in [10, 25, 50, 100, None]
        assert staged["wouldWrite"] is False
    finally:
        cf.close()


def test_creator_os_staged_operational_acceptance_can_pass_with_clean_actual_state(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        for index in range(10):
            cf.domains.models.upsert_account(
                f"stacey_{index}",
                platform="instagram",
                external_id=f"ig_{index}",
                model_id=model["id"],
            )
        for index in range(90):
            add_surface_asset_fixture(
                cf,
                tmp_path,
                asset_id=f"asset_scale_inventory_{index}",
                content_surface="feed_single",
                media_type="image",
                instagram_post_caption="schedule safe",
            )
        campaign_id = cf.domains.campaign_by_slug("stacey_surface_inventory_20260606")[
            "id"
        ]
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, post_id, account_id, instagram_account_id, platform,
             content_surface, metrics_eligible, snapshot_at, created_at, raw_json)
            VALUES ('snap_scale_1', ?, 'asset_scale_inventory_0', 'post_scale_1', 'ig_0', 'ig_0',
                    'instagram', 'reel', 1,
                    '2026-06-09T00:00:00+00:00', '2026-06-09T00:00:00+00:00', '{}')
            """,
            (campaign_id,),
        )
        cf.conn.commit()

        result = cf.domains.live_acceptance.creator_os_live_account_acceptance(
            account_target=10
        )
        reel_result = cf.domains.live_acceptance.creator_os_live_account_acceptance(
            account_target=10, content_surface="reel"
        )

        assert result["actuals"]["missedDispatches"] == 0
        assert result["actuals"]["duplicatePublishes"] == 0
        assert result["actuals"]["restrictedAccountsScheduled"] == 0
        assert result["actuals"]["surfaceContractViolations"] == 0
        assert result["actuals"]["inventoryBufferMaintained"] is True
        assert result["actuals"]["metricsImported"] is True
        assert result["actuals"]["exceptionQueueWithinThreshold"] is True
        assert result["acceptancePassed"] is True
        assert result["blockingReasons"] == []
        assert result["contentSurface"] == "all"
        assert reel_result["contentSurface"] == "reel"
        assert reel_result["availableInventory"] == 0
        assert reel_result["acceptancePassed"] is False
        assert "inventory_buffer_not_maintained" in reel_result["blockingReasons"]
    finally:
        cf.close()


def test_failure_injection_and_idempotency_proofs_are_simulation_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        failures = cf.domains.operational_proofs.failure_injection_suite()
        idempotency = cf.domains.operational_proofs.idempotency_proof()

        assert cf.conn.total_changes == before
        assert failures["schema"] == "creator_os.failure_injection_suite.v1"
        assert failures["failureInjectionPassed"] is False
        assert failures["evidenceStatus"] == "simulation_catalog_only"
        assert {item["scenario"] for item in failures["scenarios"]} == {
            "duplicate_publish_callback",
            "double_qstash_dispatch",
            "late_dispatch",
            "missed_dispatch",
            "expired_publish_token",
            "partial_metrics_sync",
            "missing_performance_snapshot",
            "duplicate_performance_snapshot",
            "invalid_handoff_manifest",
            "stale_account_restriction",
        }
        assert all(
            item["evidenceStatus"] == "not_executed" for item in failures["scenarios"]
        )
        assert all(
            item["detected"] is None
            and item["contained"] is None
            and item["recovered"] is None
            for item in failures["scenarios"]
        )
        assert failures["wouldWrite"] is False
        assert idempotency["schema"] == "creator_os.idempotency_proof.v1"
        assert idempotency["idempotent"] is False
        assert idempotency["idempotencyProven"] is False
        assert idempotency["evidenceStatus"] == "simulation_catalog_only"
        assert idempotency["unsafePaths"] == []
        assert set(idempotency["unverifiedPaths"]) == {
            item["path"] for item in idempotency["paths"]
        }
        assert all(item["idempotent"] is None for item in idempotency["paths"])
        assert idempotency["wouldWrite"] is False
    finally:
        cf.close()


def test_jobs_for_campaign_filters_by_status(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        cf.domains.models.upsert_model("model", "Model")
        campaign = cf.domains.models.upsert_campaign("may", "model")
        running = cf.domains.events.create_pipeline_job(
            "threadsdash_export", campaign["id"], {}
        )
        failed = cf.domains.events.create_pipeline_job(
            "threadsdash_export", campaign["id"], {}
        )
        cf.domains.events.start_pipeline_job(running["id"])
        cf.domains.events.start_pipeline_job(failed["id"])
        cf.domains.events.fail_pipeline_job(failed["id"], "boom")

        rows = cf.domains.events.jobs_for_campaign("may", statuses=["failed"])

        assert [row["id"] for row in rows] == [failed["id"]]
    finally:
        cf.close()


def test_jobs_can_scan_all_campaigns_and_mark_stuck_jobs(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        cf.domains.models.upsert_model("model", "Model")
        may = cf.domains.models.upsert_campaign("may", "model")
        june = cf.domains.models.upsert_campaign("june", "model")
        old_job = cf.domains.events.create_pipeline_job(
            "threadsdash_export", may["id"], {}
        )
        fresh_job = cf.domains.events.create_pipeline_job(
            "threadsdash_export", june["id"], {}
        )
        old_ts = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
        cf.conn.execute(
            "UPDATE pipeline_jobs SET created_at = ?, updated_at = ? WHERE id = ?",
            (old_ts, old_ts, old_job["id"]),
        )
        cf.conn.commit()

        rows = cf.domains.events.jobs_for_campaign(
            None, statuses=["queued"], limit=10, stuck_hours=24
        )

        by_id = {row["id"]: row for row in rows}
        assert by_id[old_job["id"]]["campaignSlug"] == "may"
        assert by_id[fresh_job["id"]]["campaignSlug"] == "june"
        assert by_id[old_job["id"]]["stuck"] is True
        assert by_id[fresh_job["id"]]["stuck"] is False
    finally:
        cf.close()


def test_jobs_stuck_hours_threshold_is_respected(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        cf.domains.models.upsert_model("model", "Model")
        campaign = cf.domains.models.upsert_campaign("may", "model")
        job = cf.domains.events.create_pipeline_job(
            "threadsdash_export", campaign["id"], {}
        )
        ts = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
        cf.conn.execute(
            "UPDATE pipeline_jobs SET created_at = ?, updated_at = ? WHERE id = ?",
            (ts, ts, job["id"]),
        )
        cf.conn.commit()

        assert (
            cf.domains.events.jobs_for_campaign(None, stuck_hours=5)[0]["stuck"] is True
        )
        assert (
            cf.domains.events.jobs_for_campaign(None, stuck_hours=7)[0]["stuck"]
            is False
        )
    finally:
        cf.close()


def test_failed_job_resolution_is_scoped_to_asset_identity(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        jobs = [
            {
                "id": "failed_a",
                "jobType": "threadsdash_export",
                "status": "failed",
                "input": {"renderedAssetId": "asset_a"},
                "result": {},
                "finishedAt": "2026-06-01T10:00:00Z",
                "updatedAt": "2026-06-01T10:00:00Z",
                "createdAt": "2026-06-01T10:00:00Z",
            },
            {
                "id": "success_b",
                "jobType": "threadsdash_export",
                "status": "succeeded",
                "input": {"renderedAssetId": "asset_b"},
                "result": {},
                "finishedAt": "2026-06-01T11:00:00Z",
                "updatedAt": "2026-06-01T11:00:00Z",
                "createdAt": "2026-06-01T11:00:00Z",
            },
        ]

        unresolved = cf.domains.campaign_overview.unresolved_failed_jobs(jobs)

        assert [job["id"] for job in unresolved] == ["failed_a"]
    finally:
        cf.close()


def test_supabase_rest_client_retries_transient_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(_request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(
                "https://example.supabase.co",
                503,
                "temporary",
                {},
                io.BytesIO(b"try again"),
            )
        return FakeResponse()

    monkeypatch.setattr(threadsdash_client_adapter, "urlopen", fake_urlopen)
    monkeypatch.setattr(threadsdash_client_adapter.time, "sleep", lambda *_args: None)
    client = threadsdash_client_adapter.SupabaseRestClient(
        "https://example.supabase.co", "service-role"
    )

    result = client.get_storage_bucket("media")

    assert result == {"ok": True}
    assert calls["count"] == 2


def test_supabase_rest_client_insert_does_not_retry_ambiguous_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def fake_urlopen(_request, timeout):
        calls["count"] += 1
        raise HTTPError(
            "https://example.supabase.co",
            503,
            "temporary",
            {},
            io.BytesIO(b"maybe committed"),
        )

    monkeypatch.setattr(threadsdash_client_adapter, "urlopen", fake_urlopen)
    monkeypatch.setattr(threadsdash_client_adapter.time, "sleep", lambda *_args: None)
    client = threadsdash_client_adapter.SupabaseRestClient(
        "https://example.supabase.co", "service-role"
    )

    with pytest.raises(RuntimeError, match="Supabase request failed 503"):
        client.insert("posts", {"content": "hello"})

    assert calls["count"] == 1


def test_supabase_rest_client_insert_retries_safe_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'[{"id": "post_1"}]'

    def fake_urlopen(_request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(
                "https://example.supabase.co",
                429,
                "rate limited",
                {},
                io.BytesIO(b"slow down"),
            )
        return FakeResponse()

    monkeypatch.setattr(threadsdash_client_adapter, "urlopen", fake_urlopen)
    monkeypatch.setattr(threadsdash_client_adapter.time, "sleep", lambda *_args: None)
    client = threadsdash_client_adapter.SupabaseRestClient(
        "https://example.supabase.co", "service-role"
    )

    result = client.insert("posts", {"content": "hello"})

    assert result == [{"id": "post_1"}]
    assert calls["count"] == 2


def test_supabase_rest_client_insert_does_not_retry_network_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def fake_urlopen(_request, timeout):
        calls["count"] += 1
        raise URLError("timed out")

    monkeypatch.setattr(threadsdash_client_adapter, "urlopen", fake_urlopen)
    monkeypatch.setattr(threadsdash_client_adapter.time, "sleep", lambda *_args: None)
    client = threadsdash_client_adapter.SupabaseRestClient(
        "https://example.supabase.co", "service-role"
    )

    with pytest.raises(RuntimeError, match="Supabase request failed"):
        client.insert("posts", {"content": "hello"})

    assert calls["count"] == 1
