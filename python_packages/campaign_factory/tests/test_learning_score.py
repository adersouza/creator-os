from __future__ import annotations

from datetime import UTC, datetime

from campaign_factory.learning_score import (
    account_reward_baselines,
    aggregate_performance,
    performance_planning_score,
    performance_score,
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
