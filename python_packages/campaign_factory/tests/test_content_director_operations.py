from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_factory import content_director_operations as operations
from campaign_factory.content_director import build_plan, persist_plan
from campaign_factory.content_director_operations import (
    create_metric_cohorts,
    design_experiment,
    export_manifest_preview,
    plan_execution,
    propose_schedule,
    review_plan_item,
)
from test_content_director import _conn, _request


def _persisted(tmp_path: Path, *, count: int = 5):
    conn = _conn(tmp_path)
    stored = persist_plan(conn, build_plan(conn, _request(output_count=count)))
    conn.execute(
        """
        UPDATE creative_plan_items
        SET execution_state = 'APPROVED', blocking_reasons_json = '[]'
        WHERE plan_version_id = ?
        """,
        (stored["planId"],),
    )
    conn.commit()
    return conn, stored["planId"]


def test_schedule_is_deterministic_account_safe_and_advisory(tmp_path: Path) -> None:
    conn, plan_id = _persisted(tmp_path)
    first = propose_schedule(
        conn,
        plan_id,
        apply=False,
        blackout_dates=frozenset({"2026-07-28"}),
    )
    second = propose_schedule(
        conn,
        plan_id,
        apply=False,
        blackout_dates=frozenset({"2026-07-28"}),
    )
    assert first == second
    assert first["externalSchedulesCreated"] == 0
    assert all(
        proposal["sourceLayer"] == "safe_deterministic_default"
        and proposal["threadsdashboardFinalAuthority"] is True
        and proposal["learnedTiming"] is False
        for proposal in first["proposals"]
    )
    starts = [
        datetime.fromisoformat(proposal["windowStart"])
        for proposal in first["proposals"]
    ]
    assert all(
        later - earlier >= operations.timedelta(hours=20)
        for earlier, later in zip(starts, starts[1:], strict=False)
    )
    assert [start.date().isoformat() for start in starts[:3]] == [
        "2026-07-29",
        "2026-07-30",
        "2026-07-31",
    ]


def test_schedule_advances_each_account_independently(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    plan = build_plan(
        conn,
        _request(
            accounts=("stacey-main", "stacey-alt"),
            output_count=4,
        ),
    )
    stored = persist_plan(conn, plan)
    result = propose_schedule(conn, stored["planId"], apply=False)
    by_account: dict[str, list[datetime]] = {}
    for proposal in result["proposals"]:
        by_account.setdefault(proposal["targetAccount"], []).append(
            datetime.fromisoformat(proposal["windowStart"])
        )
    assert set(by_account) == {"stacey-main", "stacey-alt"}
    assert all(
        windows[0].date().isoformat() == "2026-07-28" for windows in by_account.values()
    )
    assert all(
        [window.date().isoformat() for window in windows]
        == ["2026-07-28", "2026-07-29"]
        for windows in by_account.values()
    )


def test_constrained_minimum_gap_can_use_every_other_day(tmp_path: Path) -> None:
    conn, plan_id = _persisted(tmp_path, count=3)
    result = propose_schedule(conn, plan_id, apply=False, minimum_gap_hours=48)
    starts = [
        datetime.fromisoformat(proposal["windowStart"])
        for proposal in result["proposals"]
    ]
    assert [start.date().isoformat() for start in starts] == [
        "2026-07-28",
        "2026-07-30",
        "2026-08-02",
    ]
    assert all(
        later - earlier >= operations.timedelta(hours=48)
        for earlier, later in zip(starts, starts[1:], strict=False)
    )


def test_schedule_apply_persists_proposals_but_creates_no_schedule(
    tmp_path: Path,
) -> None:
    conn, plan_id = _persisted(tmp_path)
    result = propose_schedule(conn, plan_id, apply=True)
    persisted = conn.execute(
        "SELECT proposed_window_json FROM creative_plan_items WHERE plan_version_id = ?",
        (plan_id,),
    ).fetchall()
    assert result["externalSchedulesCreated"] == 0
    assert all(json.loads(row[0])["status"] == "PROPOSED" for row in persisted)


def test_experiment_changes_exactly_one_variable_and_is_idempotent(
    tmp_path: Path,
) -> None:
    conn, plan_id = _persisted(tmp_path)
    first_two = [
        row[0]
        for row in conn.execute(
            """
            SELECT id FROM creative_plan_items
            WHERE plan_version_id = ? ORDER BY item_index LIMIT 2
            """,
            (plan_id,),
        ).fetchall()
    ]
    conn.executemany(
        "UPDATE creative_plan_items SET content_intent = 'passive_selfie' WHERE id = ?",
        [(item_id,) for item_id in first_two],
    )
    first = design_experiment(
        conn,
        plan_id=plan_id,
        changed_variable="hook_family",
        variants=("curiosity", "confessional"),
        hypothesis="A concise observed-difference test.",
        apply=True,
    )
    second = design_experiment(
        conn,
        plan_id=plan_id,
        changed_variable="hook_family",
        variants=("curiosity", "confessional"),
        hypothesis="A concise observed-difference test.",
        apply=True,
    )
    assert first["experimentId"] == second["experimentId"]
    assert (
        conn.execute("SELECT count(*) FROM creative_plan_experiments").fetchone()[0]
        == 1
    )
    classes = [
        row[0]
        for row in conn.execute(
            """
            SELECT exploration_class FROM creative_plan_items
            WHERE experiment_id = ? ORDER BY item_index
            """,
            (first["experimentId"],),
        ).fetchall()
    ]
    assert classes == ["CONTROL", "CONTROLLED_VARIATION"]
    assert "not causal proof" in first["minimumSampleWarning"]
    with pytest.raises(ValueError, match="unsupported"):
        design_experiment(
            conn,
            plan_id=plan_id,
            changed_variable="source_and_timing",
            variants=("a", "b"),
            hypothesis="invalid",
            apply=False,
        )


def test_execution_dry_run_uses_normal_lane_and_exact_planned_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, plan_id = _persisted(tmp_path, count=2)
    calls: list[dict] = []

    def fake_plan(**kwargs):
        calls.append(kwargs)
        return {
            "schema": "creator_os.production_batch.v1",
            "jobs": [{"jobId": f"job_{len(calls)}"}],
        }

    monkeypatch.setattr(operations, "plan_production_batch", fake_plan)
    result = plan_execution(
        conn,
        SimpleNamespace(conn=conn),
        plan_id=plan_id,
        apply=False,
        signed_spend_credits=None,
    )
    assert result["estimatedProviderCalls"] == 2
    assert all(call["count"] == 1 for call in calls)
    assert all(
        call["selected_source_asset_ids"]
        == (
            conn.execute(
                "SELECT source_asset_id FROM creative_plan_items WHERE id = ?",
                (item_id,),
            ).fetchone()[0],
        )
        for call, item_id in zip(calls, result["eligibleItems"], strict=True)
    )


def test_execution_apply_requires_signed_cap_and_is_idempotent(tmp_path: Path) -> None:
    conn, plan_id = _persisted(tmp_path, count=1)
    with pytest.raises(PermissionError, match="signed spend"):
        plan_execution(
            conn,
            SimpleNamespace(conn=conn),
            plan_id=plan_id,
            apply=True,
            signed_spend_credits=None,
        )
    calls = 0

    def fake_runner(**kwargs):
        nonlocal calls
        calls += 1
        return {
            "completed": 1,
            "quotedProviderCredits": 5,
            "actualProviderCredits": 5,
            "jobs": [{"jobId": "normal_job"}],
        }

    first = plan_execution(
        conn,
        SimpleNamespace(conn=conn),
        plan_id=plan_id,
        apply=True,
        signed_spend_credits=20,
        runner=fake_runner,
    )
    second = plan_execution(
        conn,
        SimpleNamespace(conn=conn),
        plan_id=plan_id,
        apply=True,
        signed_spend_credits=20,
        runner=fake_runner,
    )
    assert first["eligibleItems"]
    assert second["eligibleItems"] == []
    assert calls == 1


def test_review_is_output_granular_and_blank_is_not_a_rejection(tmp_path: Path) -> None:
    conn, plan_id = _persisted(tmp_path, count=1)
    item_id = conn.execute(
        "SELECT id FROM creative_plan_items WHERE plan_version_id = ?", (plan_id,)
    ).fetchone()[0]
    conn.execute(
        "UPDATE creative_plan_items SET execution_state = 'REVIEW_READY' WHERE id = ?",
        (item_id,),
    )
    receipt = review_plan_item(
        conn,
        plan_item_id=item_id,
        action="REJECT",
        operator="fixture-operator",
        reason="hand artifact",
    )
    assert receipt["granularity"] == "output_only"
    assert "provider" in receipt["doesNotReject"]
    assert (
        conn.execute(
            "SELECT execution_state FROM creative_plan_items WHERE id = ?", (item_id,)
        ).fetchone()[0]
        == "REJECTED"
    )
    with pytest.raises(ValueError, match="unsupported"):
        review_plan_item(
            conn,
            plan_item_id=item_id,
            action="",
            operator="fixture-operator",
            reason="",
        )


def test_metric_cohorts_keep_missing_as_missing_and_one_hour_advisory(
    tmp_path: Path,
) -> None:
    conn, plan_id = _persisted(tmp_path, count=1)
    item_id = conn.execute(
        "SELECT id FROM creative_plan_items WHERE plan_version_id = ?", (plan_id,)
    ).fetchone()[0]
    cohorts = create_metric_cohorts(
        conn,
        plan_item_id=item_id,
        published_at=datetime(2026, 7, 28, 16, tzinfo=UTC),
    )
    assert [row["observationBucket"] for row in cohorts] == ["1h", "24h", "72h"]
    assert cohorts[0]["learningEligible"] is False
    assert all(row["observationState"] == "MISSING" for row in cohorts)


def test_metric_windows_overlap_and_bind_each_actual_publication_time(
    tmp_path: Path,
) -> None:
    conn, plan_id = _persisted(tmp_path, count=2)
    item_ids = [
        row[0]
        for row in conn.execute(
            """
            SELECT id FROM creative_plan_items
            WHERE plan_version_id = ? ORDER BY item_index
            """,
            (plan_id,),
        )
    ]
    first_published = datetime(2026, 7, 28, 22, 30, tzinfo=UTC)
    second_published = datetime(2026, 7, 29, 22, 30, tzinfo=UTC)
    first = create_metric_cohorts(
        conn, plan_item_id=item_ids[0], published_at=first_published
    )
    second = create_metric_cohorts(
        conn, plan_item_id=item_ids[1], published_at=second_published
    )
    assert [row["expectedEarliestAt"] for row in first] == [
        "2026-07-28T23:30:00Z",
        "2026-07-29T22:30:00Z",
        "2026-07-31T22:30:00Z",
    ]
    assert [row["expectedEarliestAt"] for row in second] == [
        "2026-07-29T23:30:00Z",
        "2026-07-30T22:30:00Z",
        "2026-08-01T22:30:00Z",
    ]
    assert datetime.fromisoformat(
        second[0]["expectedEarliestAt"].replace("Z", "+00:00")
    ) < datetime.fromisoformat(first[2]["expectedEarliestAt"].replace("Z", "+00:00"))


def test_export_preview_preserves_plan_lineage_without_exporting(
    tmp_path: Path,
) -> None:
    conn, plan_id = _persisted(tmp_path, count=1)
    item_id = conn.execute(
        "SELECT id FROM creative_plan_items WHERE plan_version_id = ?", (plan_id,)
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE creative_plan_items
        SET execution_state = 'CREATIVE_APPROVED',
            generation_identity_json = '{"finalMediaSha256":"abc"}',
            review_identity_json = '{"action":"APPROVE"}'
        WHERE id = ?
        """,
        (item_id,),
    )
    manifest = export_manifest_preview(conn, plan_id)
    assert manifest["dryRun"] is True
    assert manifest["exportsCreated"] == 0
    assert manifest["items"][0]["planItemId"] == item_id
    assert (
        "exact_final_media_sha256"
        in manifest["items"][0]["threadsdashboardVerificationRequired"]
    )
