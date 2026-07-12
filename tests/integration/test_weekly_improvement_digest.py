from __future__ import annotations

import importlib.util
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "weekly_improvement_digest.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("weekly_improvement_digest", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zero_outcomes_never_invents_creative_changes() -> None:
    module = load_module()
    now = datetime(2026, 7, 11, tzinfo=UTC)
    result = module.build_digest(
        [
            {
                "campaign": "stacey_learning_cohort_v1",
                "snapshotCount": 0,
                "leaderboards": {},
            }
        ],
        {"klingCredits": 0},
        now=now,
    )

    assert result["status"] == "awaiting_real_outcomes"
    assert result["recommendations"] == []
    assert result["automaticChangesApplied"] == 0
    assert result["publishingActionsTaken"] == 0
    assert (
        "keep_current_creative_configuration_until_evidence_exists"
        in result["nextActions"]
    )


def test_recommendations_require_three_real_samples() -> None:
    module = load_module()
    summary = {
        "campaign": "stacey_learning_cohort_v1",
        "snapshotCount": 5,
        "leaderboards": {
            "hooks": [
                {
                    "key": "winner",
                    "recommendation": "make_more_like_this",
                    "score": 84,
                    "performance": {"count": 3},
                },
                {
                    "key": "thin",
                    "recommendation": "make_more_like_this",
                    "score": 92,
                    "performance": {"count": 2},
                },
            ]
        },
    }

    recommendations = module.actionable_recommendations(summary)

    assert [item["key"] for item in recommendations] == ["winner"]
    assert recommendations[0]["action"] == "expand"


def test_campaign_scope_parser_rejects_duplicates() -> None:
    module = load_module()

    assert module.configured_campaigns('["one", "two"]') == ["one", "two"]
    try:
        module.configured_campaigns('["one", "one"]')
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate campaign list was accepted")


def test_weekly_failures_distinguishes_recovered_jobs(tmp_path: Path) -> None:
    module = load_module()
    db = tmp_path / "campaign.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE pipeline_jobs (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                updated_at TEXT NOT NULL
            )"""
        )
        conn.executemany(
            "INSERT INTO pipeline_jobs VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "failed_export",
                    "threadsdash_export",
                    "failed",
                    "transient receiver failure",
                    "2026-07-10T12:00:00+00:00",
                ),
                (
                    "successful_export",
                    "threadsdash_export",
                    "succeeded",
                    None,
                    "2026-07-10T12:05:00+00:00",
                ),
                (
                    "failed_render",
                    "run_reel",
                    "failed",
                    "token=must-not-escape render failed",
                    "2026-07-11T12:00:00+00:00",
                ),
            ],
        )

    result = module.weekly_failures(db, now=datetime(2026, 7, 12, tzinfo=UTC))

    assert result["count"] == 2
    assert result["recoveredCount"] == 1
    assert result["unrecoveredCount"] == 1
    assert result["items"][1]["recoveredByLaterSuccess"] is True
    assert "must-not-escape" not in result["items"][0]["error"]


def test_digest_renders_performance_failures_and_kling_status() -> None:
    module = load_module()
    digest = module.build_digest(
        [
            {
                "campaign": "stacey_learning_cohort_v1",
                "snapshotCount": 1,
                "leaderboards": {},
            }
        ],
        {
            "providerCalls": 0,
            "credits": 0,
            "knownCredits": 0,
            "unknownCreditCalls": 0,
            "costStatus": "known",
            "klingCalls": 0,
            "klingCredits": 0,
        },
        {
            "windowDays": 7,
            "count": 1,
            "recoveredCount": 0,
            "unrecoveredCount": 1,
            "items": [
                {
                    "jobId": "job_1",
                    "jobType": "run_reel",
                    "failedAt": "2026-07-11T12:00:00+00:00",
                    "error": "render failed",
                    "recoveredByLaterSuccess": False,
                    "latestSuccessAt": None,
                }
            ],
        },
        now=datetime(2026, 7, 12, tzinfo=UTC),
    )

    markdown = module.render_markdown(digest)

    assert digest["spend"]["klingRoiStatus"] == "not_run_this_window"
    assert "review_unrecovered_pipeline_failures" in digest["nextActions"]
    assert "## Performance evidence" in markdown
    assert "## Pipeline failures" in markdown
    assert "## Spend and Kling ROI" in markdown
    assert "Kling ROI status: `not_run_this_window`" in markdown


def test_weekly_spend_never_reports_unknown_cost_as_zero(tmp_path: Path) -> None:
    module = load_module()
    db = tmp_path / "campaign.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE higgsfield_spend_reservations (
                source TEXT,
                amount REAL,
                unit TEXT,
                provider_quote_json TEXT,
                status TEXT,
                created_at TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO higgsfield_spend_reservations VALUES (?, ?, ?, ?, ?, ?)",
            (
                "reel_factory:DirectReferenceImagePlan:job_1",
                None,
                None,
                "{}",
                "consumed",
                "2026-07-11T12:00:00+00:00",
            ),
        )

    result = module.weekly_spend(db, now=datetime(2026, 7, 12, tzinfo=UTC))

    assert result["providerCalls"] == 1
    assert result["credits"] is None
    assert result["knownCredits"] == 0
    assert result["unknownCreditCalls"] == 1
    assert result["costStatus"] == "incomplete"
