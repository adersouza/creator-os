from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter


@dataclass(frozen=True)
class MetricsRouteDeps:
    root: Path
    clip_cards_data: Callable[[], list[dict[str, Any]]]
    asset_job_counts: Callable[[], dict[str, Any]]
    render_queue_health: Callable[[], dict[str, Any]]
    campaign_factory_job_health: Callable[[Path], dict[str, Any]]
    public_failed_generations: Callable[..., dict[str, Any]]
    select_next_batch: Callable[..., dict[str, Any]]
    account_fatigue_report: Callable[..., dict[str, Any]]
    cost_analytics: Callable[[Path], dict[str, Any]]
    metrics_summary: Callable[[Path], Any]
    metrics_leaderboard: Callable[[Path], Any]
    soul_metrics_report: Callable[..., Any]
    outcomes_summary: Callable[..., Any]


def dashboard_summary(
    deps: MetricsRouteDeps, campaign: str | None = None, account: str | None = None
) -> dict[str, Any]:
    clips_data = deps.clip_cards_data()
    needs_review = sum(int(row["status"].get("draft", 0)) for row in clips_data)
    ready_to_post = sum(int(row["status"].get("approved", 0)) for row in clips_data)
    needs_metrics = sum(
        max(
            0,
            int(row["status"].get("approved", 0))
            - int(row["status"].get("outcome_count", 0)),
        )
        for row in clips_data
    )
    rec = None
    if campaign:
        try:
            plan = deps.select_next_batch(
                deps.root, campaign=campaign, count=1, persist=False
            )
            rec = ((plan.get("items") or plan.get("ideas") or [{}])[0]).get(
                "recommendation"
            )
        except Exception:
            rec = None
    account_health = None
    if account:
        try:
            account_health = deps.account_fatigue_report(deps.root, account=account)
        except Exception:
            account_health = None
    asset_job_counts = deps.asset_job_counts()
    render_queue = deps.render_queue_health()
    campaign_jobs = deps.campaign_factory_job_health(deps.root)
    failed_generations = deps.public_failed_generations(deps.root, limit=20)
    try:
        costs = deps.cost_analytics(deps.root)
    except Exception:
        costs = {"error": "cost analytics unavailable"}
    return {
        "schema": "reel_factory.dashboard_summary.v1",
        "command_center": {
            "needs_review": needs_review,
            "ready_to_post": ready_to_post,
            "needs_metrics": needs_metrics,
            "recommended_next_batch": rec,
            "in_flight_generations": int(asset_job_counts.get("queued", 0))
            + int(asset_job_counts.get("running", 0)),
            "failed_generations": int(failed_generations.get("count", 0))
            + int(asset_job_counts.get("failed", 0)),
            "failed_campaign_jobs": int(campaign_jobs.get("failed", 0)),
            "stuck_campaign_jobs": int(campaign_jobs.get("stuck", 0)),
            "render_queue_depth": int(
                (render_queue.get("counts") or {}).get("queued", 0)
            ),
        },
        "clip_statuses": {row["stem"]: row["status"] for row in clips_data},
        "next_actions": {row["stem"]: row["next_action"] for row in clips_data},
        "account_health": account_health,
        "recommendation_summary": rec,
        "pipeline_health": {
            "asset_jobs": asset_job_counts,
            "failed_generations": failed_generations,
            "render_queue": render_queue,
            "campaign_jobs": campaign_jobs,
            "costs": costs,
        },
    }


def build_metrics_router(deps: MetricsRouteDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/dashboard/summary")
    def dashboard_summary_api(
        campaign: str | None = None, account: str | None = None
    ) -> dict[str, Any]:
        return dashboard_summary(deps, campaign=campaign, account=account)

    @router.get("/api/metrics/summary")
    def get_metrics_summary() -> dict[str, Any]:
        return {"rows": deps.metrics_summary(deps.root)}

    @router.get("/api/metrics/leaderboard")
    def get_metrics_leaderboard() -> Any:
        return deps.metrics_leaderboard(deps.root)

    @router.get("/api/metrics/soul-report")
    def get_soul_metrics_report(by_account: bool = False) -> Any:
        return deps.soul_metrics_report(deps.root, by_account=by_account)

    @router.get("/api/outcomes/summary")
    def get_outcomes_summary(limit: int = 10) -> Any:
        return deps.outcomes_summary(deps.root, limit=limit)

    @router.get("/api/costs/analytics")
    def cost_analytics_api() -> dict[str, Any]:
        return deps.cost_analytics(deps.root)

    return router
