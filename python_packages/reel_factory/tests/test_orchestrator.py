from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from reel_factory import orchestrator


def test_asset_state_transitions_and_rejects_illegal_moves(tmp_path: Path) -> None:
    conn = orchestrator.open_manifest(tmp_path)

    created = orchestrator.create_asset(
        conn,
        asset_id="asset_1",
        campaign="campaign_a",
        run_id="run_1",
        now=100,
    )

    assert created["state"] == "planned"
    prompted = orchestrator.advance(conn, "asset_1", "prompted", now=101)
    assert prompted["state"] == "prompted"

    with pytest.raises(ValueError, match="illegal transition"):
        orchestrator.advance(conn, "asset_1", "ranked", now=102)


def test_regenerate_loops_back_to_planned_with_attempt_limit(tmp_path: Path) -> None:
    conn = orchestrator.open_manifest(tmp_path)
    orchestrator.create_asset(
        conn,
        asset_id="asset_1",
        campaign="campaign_a",
        run_id="run_1",
        now=100,
    )
    for state in (
        "prompted",
        "generated",
        "qc_passed",
        "ranked",
        "captioned",
        "export_ready",
        "awaiting_approval",
    ):
        orchestrator.advance(conn, "asset_1", state, now=101)

    regenerated = orchestrator.advance(
        conn,
        "asset_1",
        "regenerate",
        reason="bad hands",
        now=102,
    )

    assert regenerated["state"] == "planned"
    assert regenerated["attempts"] == 1
    assert regenerated["approval_decision"] == "regenerate"
    assert regenerated["approval_reason"] == "bad hands"


def test_regenerate_attempt_limit_marks_failed(tmp_path: Path) -> None:
    conn = orchestrator.open_manifest(tmp_path)
    orchestrator.create_asset(
        conn,
        asset_id="asset_1",
        campaign="campaign_a",
        run_id="run_1",
        now=100,
    )

    conn.execute(
        """
        UPDATE asset_pipeline_state
        SET state = 'awaiting_approval', attempts = ?
        WHERE asset_id = 'asset_1'
        """,
        (orchestrator.MAX_REGENERATE_ATTEMPTS,),
    )
    conn.commit()

    failed = orchestrator.advance(conn, "asset_1", "regenerate", now=101)

    assert failed["state"] == "failed"
    assert failed["last_error"] == "regenerate_attempt_limit"


def test_kill_switch_does_not_create_database_or_tick_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CREATOR_OS_ORCHESTRATOR_DISABLED", "1")

    report = orchestrator.tick(tmp_path, now=100, notify_user=False)

    assert report["disabledReason"] == "kill_switch"
    assert not (tmp_path / "manifest.sqlite").exists()
    assert not (tmp_path / "project_data" / "orchestrator_ticks").exists()


def test_disabled_tick_writes_report_without_creating_database(tmp_path: Path) -> None:
    report = orchestrator.tick(tmp_path, now=100, notify_user=False)

    assert report["enabled"] is False
    assert report["stateCounts"] == {}
    assert not (tmp_path / "manifest.sqlite").exists()
    assert Path(report["reportPath"]).exists()


def test_recover_stalled_assets_marks_old_in_flight_state_error(tmp_path: Path) -> None:
    conn = orchestrator.open_manifest(tmp_path)
    orchestrator.create_asset(
        conn,
        asset_id="asset_1",
        campaign="campaign_a",
        run_id="run_1",
        now=100,
    )
    orchestrator.advance(conn, "asset_1", "prompted", now=101)

    recovered = orchestrator.recover_stalled(
        conn,
        now=101 + orchestrator.DEFAULT_STALL_SECONDS + 1,
    )

    assert recovered == 1
    asset = orchestrator.get_asset(conn, "asset_1")
    assert asset["state"] == "error"
    assert asset["last_error"] == "stalled"


def test_recover_stalled_never_flushes_human_paced_states(tmp_path: Path) -> None:
    conn = orchestrator.open_manifest(tmp_path)
    for asset_id, state in (
        ("asset_ready", "export_ready"),
        ("asset_waiting", "awaiting_approval"),
    ):
        orchestrator.create_asset(
            conn,
            asset_id=asset_id,
            campaign="campaign_a",
            run_id="run_1",
            now=100,
        )
        conn.execute(
            "UPDATE asset_pipeline_state SET state = ? WHERE asset_id = ?",
            (state, asset_id),
        )
    conn.commit()

    recovered = orchestrator.recover_stalled(
        conn,
        now=100 + orchestrator.DEFAULT_STALL_SECONDS * 10,
    )

    assert recovered == 0
    assert orchestrator.get_asset(conn, "asset_ready")["state"] == "export_ready"
    assert orchestrator.get_asset(conn, "asset_waiting")["state"] == "awaiting_approval"


def test_error_retry_increments_attempts_and_caps_at_limit(tmp_path: Path) -> None:
    conn = orchestrator.open_manifest(tmp_path)
    orchestrator.create_asset(
        conn,
        asset_id="asset_1",
        campaign="campaign_a",
        run_id="run_1",
        now=100,
    )

    for expected_attempts in range(1, orchestrator.MAX_TOTAL_ATTEMPTS + 1):
        orchestrator.advance(conn, "asset_1", "error", reason="boom", now=101)
        retried = orchestrator.advance(conn, "asset_1", "planned", now=102)
        assert retried["state"] == "planned"
        assert retried["attempts"] == expected_attempts
        assert retried["last_error"] is None

    orchestrator.advance(conn, "asset_1", "error", reason="boom", now=103)
    failed = orchestrator.advance(conn, "asset_1", "planned", now=104)

    assert failed["state"] == "failed"
    assert failed["attempts"] == orchestrator.MAX_TOTAL_ATTEMPTS + 1
    assert failed["last_error"] == "retry_attempt_limit"


def _seed_awaiting_approval(tmp_path: Path, asset_id: str = "asset_1") -> None:
    conn = orchestrator.open_manifest(tmp_path)
    orchestrator.create_asset(
        conn,
        asset_id=asset_id,
        campaign="campaign_a",
        run_id="run_1",
        now=100,
    )
    conn.execute(
        "UPDATE asset_pipeline_state SET state = 'awaiting_approval' WHERE asset_id = ?",
        (asset_id,),
    )
    conn.commit()
    conn.close()


def test_decide_approved_records_decision(tmp_path: Path) -> None:
    _seed_awaiting_approval(tmp_path)

    result = orchestrator.decide(tmp_path, "asset_1", "approved", now=200)

    assert result["asset"]["state"] == "approved"
    assert result["asset"]["approval_decision"] == "approved"
    assert result["asset"]["approved_at"] == 200
    assert result["rejectionEvidenceRecorded"] is False


def test_decide_rejected_writes_rejection_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_awaiting_approval(tmp_path)
    cf_db = tmp_path / "campaign_factory.sqlite"
    with sqlite3.connect(cf_db) as conn:
        conn.execute("CREATE TABLE rendered_assets (id TEXT PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE asset_rejection_evidence (
              id TEXT PRIMARY KEY,
              rendered_asset_id TEXT,
              source_asset_id TEXT,
              campaign_id TEXT,
              content_surface TEXT NOT NULL DEFAULT 'reel',
              failed_stage TEXT NOT NULL,
              failure_category TEXT NOT NULL,
              matched_text TEXT NOT NULL DEFAULT '',
              source_field TEXT NOT NULL DEFAULT '',
              policy_version TEXT NOT NULL,
              repairable INTEGER NOT NULL DEFAULT 1,
              evidence_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(rendered_asset_id, failed_stage, failure_category,
                     matched_text, source_field, policy_version)
            )
            """
        )
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(cf_db))

    result = orchestrator.decide(
        tmp_path, "asset_1", "rejected", reason="off brand", now=200
    )

    assert result["asset"]["state"] == "rejected"
    assert result["rejectionEvidenceRecorded"] is True
    with sqlite3.connect(cf_db) as conn:
        row = conn.execute(
            "SELECT failed_stage, failure_category, matched_text, evidence_json"
            " FROM asset_rejection_evidence"
        ).fetchone()
    assert row[0] == "human_approval"
    assert row[1] == "operator_rejected"
    assert row[2] == "off brand"
    assert '"assetId": "asset_1"' in row[3]


def test_decide_rejected_tolerates_missing_campaign_factory_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_awaiting_approval(tmp_path)
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(tmp_path / "missing.sqlite"))

    result = orchestrator.decide(tmp_path, "asset_1", "rejected", now=200)

    assert result["asset"]["state"] == "rejected"
    assert result["rejectionEvidenceRecorded"] is False


def test_decide_rejects_unknown_decision_and_illegal_state(tmp_path: Path) -> None:
    _seed_awaiting_approval(tmp_path)

    with pytest.raises(ValueError, match="unknown decision"):
        orchestrator.decide(tmp_path, "asset_1", "exported")

    orchestrator.decide(tmp_path, "asset_1", "approved", now=200)
    with pytest.raises(ValueError, match="illegal transition"):
        orchestrator.decide(tmp_path, "asset_1", "rejected", now=201)


def test_counts_ignore_missing_state_table(tmp_path: Path) -> None:
    db_path = tmp_path / "manifest.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")

    assert orchestrator.read_counts_if_present(tmp_path) == {}
