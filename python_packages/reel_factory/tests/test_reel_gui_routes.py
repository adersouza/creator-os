from __future__ import annotations

from pathlib import Path

import reel_gui
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"


def _route_inventory() -> list[str]:
    rows: list[str] = []
    for route in reel_gui.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        if not path:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            rows.append(f"{method} {path}")
    return sorted(rows)


def test_reel_gui_route_inventory_matches_snapshot() -> None:
    expected = (FIXTURES / "reel_gui_routes.txt").read_text().splitlines()
    assert _route_inventory() == expected


def test_read_only_metrics_routes_return_golden_json(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    monkeypatch.setattr(
        reel_gui,
        "metrics_summary",
        lambda root: [{"stem": "clip_001", "views": 100}],
    )
    monkeypatch.setattr(
        reel_gui,
        "metrics_leaderboard",
        lambda root: {"leaders": [{"stem": "clip_001", "score": 9.5}]},
    )
    monkeypatch.setattr(
        reel_gui,
        "soul_metrics_report",
        lambda root, by_account=False: {
            "by_account": by_account,
            "souls": [{"soul_id": "stacey", "wins": 2}],
        },
    )
    monkeypatch.setattr(
        reel_gui,
        "outcomes_summary",
        lambda root, limit=10: {"limit": limit, "rows": [{"stem": "clip_001"}]},
    )
    monkeypatch.setattr(
        reel_gui,
        "cost_analytics",
        lambda root: {"total": 12.5, "assets": [{"stem": "clip_001"}]},
    )
    client = TestClient(reel_gui.app, client=("127.0.0.1", 50000))

    assert client.get("/api/metrics/summary").json() == {
        "rows": [{"stem": "clip_001", "views": 100}]
    }
    assert client.get("/api/metrics/leaderboard").json() == {
        "leaders": [{"stem": "clip_001", "score": 9.5}]
    }
    assert client.get("/api/metrics/soul-report?by_account=true").json() == {
        "by_account": True,
        "souls": [{"soul_id": "stacey", "wins": 2}],
    }
    assert client.get("/api/outcomes/summary?limit=1").json() == {
        "limit": 1,
        "rows": [{"stem": "clip_001"}],
    }
    assert client.get("/api/costs/analytics").json() == {
        "total": 12.5,
        "assets": [{"stem": "clip_001"}],
    }


def test_dashboard_summary_route_returns_golden_json(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    monkeypatch.setattr(
        reel_gui,
        "_clip_cards_data",
        lambda: [
            {
                "stem": "clip_001",
                "status": {"draft": 1, "approved": 2, "outcome_count": 1},
                "next_action": {"label": "Review"},
            }
        ],
    )
    monkeypatch.setattr(
        reel_gui,
        "select_next_batch",
        lambda root, **kwargs: {"items": [{"recommendation": {"stem": "clip_002"}}]},
    )
    monkeypatch.setattr(
        reel_gui,
        "account_fatigue_report",
        lambda root, **kwargs: {"account": kwargs["account"], "fatigue": "low"},
    )
    monkeypatch.setattr(
        reel_gui,
        "_asset_job_counts",
        lambda: {"queued": 1, "running": 2, "failed": 3},
    )
    monkeypatch.setattr(
        reel_gui,
        "_render_queue_health",
        lambda: {"counts": {"queued": 4}},
    )
    monkeypatch.setattr(
        reel_gui,
        "_campaign_factory_job_health",
        lambda root: {"failed": 5, "stuck": 6},
    )
    monkeypatch.setattr(
        reel_gui,
        "_public_failed_generations",
        lambda root, limit=20: {"count": 7, "items": []},
    )
    monkeypatch.setattr(
        reel_gui,
        "cost_analytics",
        lambda root: {"total": 9.0},
    )
    client = TestClient(reel_gui.app, client=("127.0.0.1", 50000))

    response = client.get("/api/dashboard/summary?campaign=may&account=acct_1")

    assert response.json() == {
        "schema": "reel_factory.dashboard_summary.v1",
        "command_center": {
            "needs_review": 1,
            "ready_to_post": 2,
            "needs_metrics": 1,
            "recommended_next_batch": {"stem": "clip_002"},
            "in_flight_generations": 3,
            "failed_generations": 10,
            "failed_campaign_jobs": 5,
            "stuck_campaign_jobs": 6,
            "render_queue_depth": 4,
        },
        "clip_statuses": {"clip_001": {"draft": 1, "approved": 2, "outcome_count": 1}},
        "next_actions": {"clip_001": {"label": "Review"}},
        "account_health": {"account": "acct_1", "fatigue": "low"},
        "recommendation_summary": {"stem": "clip_002"},
        "pipeline_health": {
            "asset_jobs": {"queued": 1, "running": 2, "failed": 3},
            "failed_generations": {"count": 7, "items": []},
            "render_queue": {"counts": {"queued": 4}},
            "campaign_jobs": {"failed": 5, "stuck": 6},
            "costs": {"total": 9.0},
        },
    }
