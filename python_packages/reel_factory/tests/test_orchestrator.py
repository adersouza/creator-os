from __future__ import annotations

import json
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


def test_operator_status_and_inbox_are_headless_read_surfaces(tmp_path: Path) -> None:
    status = orchestrator.operator_status(tmp_path)
    assert status["enabled"] is False
    assert status["paidGenerationEnabled"] is False
    assert status["stateCounts"] == {}

    missing = orchestrator.operator_inbox(tmp_path)
    assert missing["available"] is False
    assert missing["items"] == []

    _seed_awaiting_approval(tmp_path, "asset_low")
    _seed_awaiting_approval(tmp_path, "asset_high")
    conn = orchestrator.open_manifest(tmp_path)
    conn.execute(
        "UPDATE asset_pipeline_state SET rank_score = 0.2 WHERE asset_id = 'asset_low'"
    )
    conn.execute(
        "UPDATE asset_pipeline_state SET rank_score = 0.9 WHERE asset_id = 'asset_high'"
    )
    conn.commit()
    conn.close()

    inbox = orchestrator.operator_inbox(tmp_path, limit=1)
    assert inbox["available"] is True
    assert inbox["count"] == 1
    assert inbox["items"][0]["asset_id"] == "asset_high"


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


def test_ingest_pipeline_state_advances_from_lineage_rank_and_output(
    tmp_path: Path,
) -> None:
    conn = orchestrator.open_manifest(tmp_path)
    lineage_path = (
        tmp_path / "00_source_videos" / "asset_1.generated_asset_lineage.json"
    )
    output_path = tmp_path / "02_processed" / "asset_1.mp4"
    lineage_path.parent.mkdir()
    output_path.parent.mkdir()
    output_path.write_bytes(b"mp4")
    lineage = {
        "source": {"stem": "asset_1"},
        "generation": {"campaign": "campaign_a", "status": "ok"},
        "review": {"generatedImageQc": {"status": "passed"}},
    }
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
    state = {
        "campaign": "campaign_a",
        "run_id": "run_1",
        "stages": {
            "assets": {
                "jobs": [{"stem": "asset_1", "lineage_path": str(lineage_path)}]
            },
            "rank": {
                "ranked": [
                    {
                        "output_path": str(output_path),
                        "score": 0.9,
                        "predictedEngagement": {"views": 100},
                        "generated_asset_lineage": lineage,
                    }
                ]
            },
        },
    }

    assert orchestrator.ingest_pipeline_state(conn, state, now=200) == 1

    asset = orchestrator.get_asset(conn, "asset_1")
    assert asset["state"] == "export_ready"
    assert asset["output_path"] == str(output_path)
    assert asset["rank_score"] == 0.9
    assert '"views": 100' in asset["predicted_engagement_json"]


def test_promote_top_k_uses_rank_and_preserves_replacements(tmp_path: Path) -> None:
    conn = orchestrator.open_manifest(tmp_path)
    for asset_id, score in (("asset_low", 0.2), ("asset_high", 0.8)):
        orchestrator.create_asset(
            conn,
            asset_id=asset_id,
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
        ):
            orchestrator.advance(conn, asset_id, state, now=101)
        orchestrator.update_asset_evidence(conn, asset_id, rank_score=score)

    promoted = orchestrator.promote_top_k(conn, campaign="campaign_a", top_k=1, now=200)

    assert promoted == 1
    assert orchestrator.get_asset(conn, "asset_high")["state"] == "awaiting_approval"
    assert orchestrator.get_asset(conn, "asset_low")["state"] == "export_ready"


def test_enabled_tick_blocks_generation_without_cost_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_data = tmp_path / "project_data"
    project_data.mkdir()
    reference = tmp_path / "reference.jpg"
    reference.write_bytes(b"reference")
    (project_data / "orchestrator.toml").write_text(
        "\n".join(
            [
                "enabled = true",
                "paid_generation_enabled = true",
                "daily_candidate_target = 1",
                'campaign = "campaign_a"',
                'creator = "Stacey"',
                f'reference_image = "{reference}"',
            ]
        ),
        encoding="utf-8",
    )

    def fake_preflight(**kwargs):
        assert kwargs["estimated_cost_usd"] is None
        return {"allowed": False, "blockingReason": "cost_estimate_missing"}

    monkeypatch.setattr(orchestrator, "check_higgsfield_cost_preflight", fake_preflight)
    monkeypatch.setattr(
        orchestrator,
        "run_pipeline",
        lambda *args, **kwargs: pytest.fail("run_pipeline should not start"),
    )

    report = orchestrator.tick(
        tmp_path,
        now=200,
        notify_user=False,
        allow_paid_generation=True,
        max_total_cost_usd=1.0,
    )

    assert report["generation"]["reason"] == "cost_estimate_missing"
    assert report["stateCounts"] == {}


def test_enabled_tick_runs_pipeline_and_ingests_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_data = tmp_path / "project_data"
    project_data.mkdir()
    reference = tmp_path / "reference.jpg"
    reference.write_bytes(b"reference")
    (project_data / "orchestrator.toml").write_text(
        "\n".join(
            [
                "enabled = true",
                "paid_generation_enabled = true",
                "daily_candidate_target = 1",
                "top_k_for_approval = 1",
                'campaign = "Campaign A"',
                'creator = "Stacey"',
                f'reference_image = "{reference}"',
                "estimated_cost_per_asset_usd = 0.5",
            ]
        ),
        encoding="utf-8",
    )

    def fake_preflight(**kwargs):
        assert kwargs["estimated_cost_usd"] == 0.5
        return {"allowed": True, "blockingReason": "", "blockingReasons": []}

    def fake_run_pipeline(config):
        lineage_path = (
            tmp_path
            / "00_source_videos"
            / f"campaign_a_{config.run_id}_000.generated_asset_lineage.json"
        )
        output_path = tmp_path / "02_processed" / f"campaign_a_{config.run_id}_000.mp4"
        lineage_path.parent.mkdir()
        output_path.parent.mkdir()
        output_path.write_bytes(b"mp4")
        lineage = {
            "source": {"stem": f"campaign_a_{config.run_id}_000"},
            "generation": {"campaign": "Campaign A", "status": "ok"},
            "review": {"generatedImageQc": {"status": "passed"}},
        }
        lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
        state = {
            "campaign": "Campaign A",
            "run_id": config.run_id,
            "stages": {
                "assets": {
                    "jobs": [
                        {
                            "stem": f"campaign_a_{config.run_id}_000",
                            "lineage_path": str(lineage_path),
                        }
                    ]
                },
                "rank": {
                    "ranked": [
                        {
                            "output_path": str(output_path),
                            "score": 0.7,
                            "predictedEngagement": {"views": 50},
                            "generated_asset_lineage": lineage,
                        }
                    ]
                },
            },
        }
        run_dir = orchestrator.pipeline_run_dir(tmp_path, "Campaign A", config.run_id)
        run_dir.mkdir(parents=True)
        (run_dir / "pipeline_run.json").write_text(json.dumps(state), encoding="utf-8")
        return state

    monkeypatch.setattr(orchestrator, "check_higgsfield_cost_preflight", fake_preflight)
    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)

    report = orchestrator.tick(
        tmp_path,
        now=200,
        notify_user=False,
        allow_paid_generation=True,
        max_total_cost_usd=1.0,
    )

    assert report["generation"]["started"] is True
    assert report["promotedToApproval"] == 1
    assert report["stateCounts"] == {"awaiting_approval": 1}


@pytest.mark.parametrize(
    ("paid_enabled", "allow_paid", "maximum", "reason"),
    [
        (False, False, None, "paid_generation_disabled"),
        (True, False, None, "paid_generation_cli_gate_missing"),
        (True, True, None, "maximum_total_cost_missing"),
        (True, True, 0.25, "maximum_total_cost_exceeded"),
    ],
)
def test_paid_generation_requires_all_independent_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paid_enabled: bool,
    allow_paid: bool,
    maximum: float | None,
    reason: str,
) -> None:
    project_data = tmp_path / "project_data"
    project_data.mkdir()
    reference = tmp_path / "reference.jpg"
    reference.write_bytes(b"reference")
    (project_data / "orchestrator.toml").write_text(
        "\n".join(
            [
                "enabled = true",
                f"paid_generation_enabled = {str(paid_enabled).lower()}",
                "daily_candidate_target = 1",
                'campaign = "Campaign A"',
                'creator = "Stacey"',
                f'reference_image = "{reference}"',
                "estimated_cost_per_asset_usd = 0.5",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        orchestrator,
        "run_pipeline",
        lambda *_args, **_kwargs: pytest.fail("provider pipeline must not start"),
    )
    monkeypatch.setattr(
        orchestrator,
        "check_higgsfield_cost_preflight",
        lambda **_kwargs: pytest.fail("preflight must not run before all gates"),
    )

    report = orchestrator.tick(
        tmp_path,
        now=200,
        notify_user=False,
        allow_paid_generation=allow_paid,
        max_total_cost_usd=maximum,
    )

    assert report["generation"]["started"] is False
    assert report["generation"]["reason"] == reason
