from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from campaign_factory.learning_score import (
    LEARNING_ELIGIBLE_SQL,
    account_reward_baselines,
    aggregate_performance,
    learning_eligible,
    learning_eligible_sql,
    learning_loop_cutover,
    learning_loop_cutover_iso,
    learning_summary,
    performance_planning_score,
    performance_score,
    snapshot_normalized_reward,
)


def _snapshot(
    *,
    post_id: str,
    account: str = "ig_1",
    snapshot_at: str = "2026-06-01T00:00:00+00:00",
    views: int = 1000,
    likes: int = 50,
    comments: int = 5,
    shares: int = 5,
    saves: int = 5,
) -> dict:
    return {
        "id": f"snap_{post_id}_{snapshot_at}",
        "postId": post_id,
        "instagramAccountId": account,
        "snapshotAt": snapshot_at,
        "metrics": {
            "views": views,
            "reach": views,
            "impressions": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "saves": saves,
            "watchTimeSeconds": 0,
        },
    }


def test_aggregate_uses_latest_snapshot_per_post_for_1h_to_24h_replacement():
    summary = aggregate_performance(
        [
            _snapshot(
                post_id="post_1",
                snapshot_at="2026-06-01T01:00:00+00:00",
                views=100,
                likes=3,
            ),
            _snapshot(
                post_id="post_1",
                snapshot_at="2026-06-02T00:00:00+00:00",
                views=1000,
                likes=50,
            ),
        ]
    )

    assert summary["count"] == 1
    assert summary["totals"]["views"] == 1000
    assert summary["latest"]["snapshotAt"] == "2026-06-02T00:00:00+00:00"


def test_account_normalization_beats_raw_big_account_volume():
    snapshots = [
        _snapshot(post_id="small_baseline", account="small", views=1000, likes=50),
        _snapshot(
            post_id="small_winner",
            account="small",
            views=900,
            likes=120,
            shares=20,
            saves=20,
        ),
        _snapshot(
            post_id="big_baseline",
            account="big",
            views=50000,
            likes=2500,
            shares=100,
            saves=100,
        ),
        _snapshot(
            post_id="big_raw",
            account="big",
            views=70000,
            likes=2600,
            shares=100,
            saves=100,
        ),
    ]
    baselines = account_reward_baselines(snapshots)

    small = aggregate_performance([snapshots[1]], account_baselines=baselines)
    big = aggregate_performance([snapshots[3]], account_baselines=baselines)

    assert performance_score(small) > performance_score(big)


def test_cold_start_strong_snapshot_scores_above_neutral_without_prior_baseline():
    summary = aggregate_performance(
        [
            _snapshot(
                post_id="winner",
                views=10000,
                likes=1000,
                comments=100,
                shares=60,
                saves=60,
            ),
        ]
    )

    assert performance_score(summary) > 50
    assert summary["learning"]["baselineSourceCounts"]["default_prior"] == 1


def test_recency_decay_downweights_old_winners():
    now = datetime(2026, 6, 1, tzinfo=UTC)
    fresh = aggregate_performance(
        [
            _snapshot(
                post_id="fresh",
                snapshot_at="2026-06-01T00:00:00+00:00",
                views=1000,
                likes=80,
                shares=10,
                saves=10,
            ),
        ],
        reference_now=now,
    )
    old = aggregate_performance(
        [
            _snapshot(
                post_id="old",
                snapshot_at="2026-04-01T00:00:00+00:00",
                views=1000,
                likes=80,
                shares=10,
                saves=10,
            ),
        ],
        reference_now=now,
    )

    assert (
        fresh["learning"]["effectiveSampleSize"]
        > old["learning"]["effectiveSampleSize"]
    )


def test_unmeasured_is_explicit_not_fake_average():
    summary = aggregate_performance(
        [
            _snapshot(post_id="zero", views=0, likes=0, comments=0, shares=0, saves=0),
        ]
    )

    assert summary["learning"]["status"] == "unmeasured"
    assert performance_score(summary) is None


def test_bandit_planning_score_prefers_baseline_beating_arm():
    snapshots = [
        _snapshot(post_id="baseline_a", account="ig_1", views=1000, likes=50),
        _snapshot(post_id="baseline_b", account="ig_1", views=1000, likes=50),
        _snapshot(
            post_id="winner", account="ig_1", views=1000, likes=130, shares=20, saves=20
        ),
        _snapshot(
            post_id="loser", account="ig_1", views=1000, likes=8, shares=0, saves=0
        ),
    ]
    baselines = account_reward_baselines(snapshots)

    winner = aggregate_performance([snapshots[2]], account_baselines=baselines)
    loser = aggregate_performance([snapshots[3]], account_baselines=baselines)

    assert winner["learning"]["bandit"]["algorithm"] == "beta_bernoulli_decayed_v1"
    assert (
        winner["learning"]["bandit"]["posteriorMean"]
        > loser["learning"]["bandit"]["posteriorMean"]
    )
    assert performance_planning_score(winner) > performance_planning_score(loser)


def test_sparse_arm_carries_explicit_exploration_floor():
    summary = aggregate_performance(
        [
            _snapshot(post_id="single", views=1000, likes=55),
        ]
    )

    bandit = summary["learning"]["bandit"]
    assert bandit["explorationFloor"] == 0.15
    assert bandit["explorationPriority"] == "explore"
    assert bandit["effectiveTrials"] == summary["learning"]["effectiveSampleSize"]


def test_snapshot_normalized_reward_matches_learning_summary_relative_reward():
    snapshots = [
        _snapshot(post_id="baseline_1", views=1000, likes=50),
        _snapshot(post_id="baseline_2", views=1000, likes=70),
    ]
    baselines = account_reward_baselines(snapshots)
    target = _snapshot(
        post_id="target", views=1500, likes=180, comments=20, shares=25, saves=30
    )

    scalar = snapshot_normalized_reward(target, baselines)
    summary = learning_summary(
        [target],
        account_baselines=baselines,
        reference_now=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert summary["weightedRelativeReward"] == round(scalar, 4)


# ---------------------------------------------------------------------------
# learning_eligible predicate (S2): Python/SQL parity + fail-closed behavior
# ---------------------------------------------------------------------------

_CUTOVER = datetime(2026, 6, 1, tzinfo=UTC)
_CUTOVER_ISO = _CUTOVER.isoformat()


def _eligible_snapshot(**overrides):
    snapshot = {
        "metrics_eligible": 1,
        "history_source": "metric_history",
        "published_at": "2026-06-02T00:00:00+00:00",
        "lineage_v2_valid": 1,
    }
    snapshot.update(overrides)
    return snapshot


_PARITY_CASES = [
    _eligible_snapshot(),
    _eligible_snapshot(metrics_eligible=0),
    _eligible_snapshot(history_source="post_row_fallback"),
    _eligible_snapshot(history_source=None),
    _eligible_snapshot(published_at=None),
    _eligible_snapshot(published_at="2026-05-31T23:59:59+00:00"),
    _eligible_snapshot(published_at=_CUTOVER_ISO),  # boundary: >= is eligible
    _eligible_snapshot(
        published_at="2026-05-31T20:00:00-04:00"
    ),  # same instant as cutover
    _eligible_snapshot(published_at="not-a-timestamp"),
    _eligible_snapshot(lineage_v2_valid=0),
    _eligible_snapshot(lineage_v2_valid=None),
]


def test_learning_eligible_happy_path_and_each_gate():
    assert learning_eligible(_eligible_snapshot(), cutover=_CUTOVER)
    assert not learning_eligible(
        _eligible_snapshot(metrics_eligible=0), cutover=_CUTOVER
    )
    assert not learning_eligible(
        _eligible_snapshot(history_source="post_row_fallback"), cutover=_CUTOVER
    )
    assert not learning_eligible(
        _eligible_snapshot(published_at=None), cutover=_CUTOVER
    )
    assert not learning_eligible(
        _eligible_snapshot(published_at="2026-05-31T00:00:00+00:00"),
        cutover=_CUTOVER,
    )
    assert not learning_eligible(
        _eligible_snapshot(lineage_v2_valid=0), cutover=_CUTOVER
    )


def test_learning_eligible_boundary_at_cutover_counts():
    assert learning_eligible(
        _eligible_snapshot(published_at=_CUTOVER_ISO), cutover=_CUTOVER
    )


def test_learning_eligible_fails_closed_without_cutover(monkeypatch):
    monkeypatch.delenv("LEARNING_LOOP_CUTOVER", raising=False)
    assert learning_loop_cutover() is None
    assert learning_loop_cutover_iso() is None
    assert not learning_eligible(_eligible_snapshot())


def test_learning_eligible_reads_cutover_from_env(monkeypatch):
    monkeypatch.setenv("LEARNING_LOOP_CUTOVER", _CUTOVER_ISO)
    assert learning_loop_cutover() == _CUTOVER
    assert learning_eligible(_eligible_snapshot())
    assert not learning_eligible(
        _eligible_snapshot(published_at="2026-05-01T00:00:00+00:00")
    )


def test_learning_eligible_accepts_public_snapshot_payload_keys():
    assert learning_eligible(
        {
            "metricsEligible": True,
            "historySource": "metric_history",
            "publishedAt": "2026-06-02T00:00:00Z",
            "lineageV2Valid": True,
        },
        cutover=_CUTOVER,
    )


@pytest.mark.parametrize("snapshot", _PARITY_CASES)
def test_sql_and_python_predicates_agree(snapshot):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE performance_snapshots (
             metrics_eligible INTEGER NOT NULL DEFAULT 0,
             history_source TEXT,
             published_at TEXT,
             lineage_v2_valid INTEGER NOT NULL DEFAULT 0
           )"""
    )
    conn.execute(
        "INSERT INTO performance_snapshots VALUES (?, ?, ?, ?)",
        (
            snapshot["metrics_eligible"],
            snapshot["history_source"],
            snapshot["published_at"],
            snapshot["lineage_v2_valid"] or 0,
        ),
    )
    named = conn.execute(
        f"SELECT COUNT(*) FROM performance_snapshots WHERE {LEARNING_ELIGIBLE_SQL}",
        {"learning_loop_cutover": _CUTOVER_ISO},
    ).fetchone()[0]
    positional = conn.execute(
        "SELECT COUNT(*) FROM performance_snapshots WHERE " + learning_eligible_sql(),
        (_CUTOVER_ISO,),
    ).fetchone()[0]
    expected = 1 if learning_eligible(snapshot, cutover=_CUTOVER) else 0
    assert named == expected
    assert positional == expected
    conn.close()
