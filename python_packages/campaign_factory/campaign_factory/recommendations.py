from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from .recommendation_constants import (
    AUTONOMY_LEVELS,
    DEFAULT_AUTONOMY_LEVEL,
    RECOMMENDATION_ITEM_STATUSES,
    RECOMMENDATION_MEASUREMENT_THRESHOLD,
    RECOMMENDATION_MEASUREMENT_VERSION,
    RECOMMENDATION_STATUS_TRANSITIONS,
    REFERENCE_PATTERN_MIN_MEASURED_EXAMPLES,
)
from .recommendation_lifecycle import RecommendationLifecycleMixin
from .recommendation_planning import RecommendationPlanningMixin
from .recommendation_scoring import RecommendationScoringMixin

__all__ = [
    "AUTONOMY_LEVELS",
    "DEFAULT_AUTONOMY_LEVEL",
    "RECOMMENDATION_ITEM_STATUSES",
    "RECOMMENDATION_MEASUREMENT_THRESHOLD",
    "RECOMMENDATION_MEASUREMENT_VERSION",
    "RECOMMENDATION_STATUS_TRANSITIONS",
    "REFERENCE_PATTERN_MIN_MEASURED_EXAMPLES",
    "RecommendationRepository",
]


class RecommendationRepository(
    RecommendationPlanningMixin,
    RecommendationLifecycleMixin,
    RecommendationScoringMixin,
):
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        graph_id_for: Callable[..., str | None],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        ensure_graph_edge_strict: Callable[..., str | None],
        record_event: Callable[..., dict[str, Any]],
        performance_summary: Callable[[str], dict[str, Any]],
        ranking: Callable[[str], dict[str, Any]],
        active_reference_pattern_for_campaign: Callable[[str], dict[str, Any] | None],
        reference_pattern_payload: Callable[[dict[str, Any]], dict[str, Any]],
        performance_snapshot_payload: Callable[[dict[str, Any]], dict[str, Any]],
        account_reward_baselines: Callable[[list[dict[str, Any]]], dict[str, float]],
        aggregate_performance: Callable[..., dict[str, Any]],
        performance_quality_score: Callable[[dict[str, Any]], int | None],
        performance_planning_score: Callable[[dict[str, Any]], int | None],
        rendered_asset: Callable[[str], dict[str, Any]],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
        assignments_for_asset: Callable[[str], list[dict[str, Any]]],
        account_memory_for: Callable[[str, str | None], dict[str, Any] | None],
        recommend_audio: Callable[..., dict[str, Any]],
        autonomy_level: Callable[[], str],
        create_exception: Callable[..., dict[str, Any]],
        exception_payload: Callable[[dict[str, Any]], dict[str, Any]],
        create_pipeline_job: Callable[..., dict[str, Any]],
        start_pipeline_job: Callable[[str], dict[str, Any]],
        finish_pipeline_job: Callable[..., dict[str, Any]],
        fail_pipeline_job: Callable[..., dict[str, Any]],
        prepare_reel_from_reference: Callable[..., dict[str, Any]],
        run_reel_factory: Callable[..., dict[str, Any]],
        sync_reel_outputs: Callable[..., dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now
        self.campaign_by_slug = campaign_by_slug
        self.graph_id_for = graph_id_for
        self.ensure_graph_node = ensure_graph_node
        self.ensure_graph_edge = ensure_graph_edge
        self.ensure_graph_edge_strict = ensure_graph_edge_strict
        self.record_event = record_event
        self.performance_summary = performance_summary
        self.ranking = ranking
        self.active_reference_pattern_for_campaign = (
            active_reference_pattern_for_campaign
        )
        self._reference_pattern_payload = reference_pattern_payload
        self._performance_snapshot_payload = performance_snapshot_payload
        self._account_reward_baselines = account_reward_baselines
        self._aggregate_performance = aggregate_performance
        self._performance_quality_score = performance_quality_score
        self._performance_planning_score = performance_planning_score
        self.rendered_asset = rendered_asset
        self._dashboard_rendered_asset = dashboard_rendered_asset
        self.assignments_for_asset = assignments_for_asset
        self._account_memory_for = account_memory_for
        self.recommend_audio = recommend_audio
        self.autonomy_level = autonomy_level
        self.create_exception = create_exception
        self._exception_payload = exception_payload
        self.create_pipeline_job = create_pipeline_job
        self.start_pipeline_job = start_pipeline_job
        self.finish_pipeline_job = finish_pipeline_job
        self.fail_pipeline_job = fail_pipeline_job
        self.prepare_reel_from_reference = prepare_reel_from_reference
        self.run_reel_factory = run_reel_factory
        self.sync_reel_outputs = sync_reel_outputs
