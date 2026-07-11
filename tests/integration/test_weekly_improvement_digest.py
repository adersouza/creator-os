from __future__ import annotations

import importlib.util
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
