from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from .creative_knowledge_analysis import CreativeKnowledgeAnalysisMixin
from .creative_knowledge_registry import CreativeKnowledgeRegistryMixin


class CreativeKnowledgeRepository(
    CreativeKnowledgeAnalysisMixin, CreativeKnowledgeRegistryMixin
):
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        creator_label: Callable[[Any], str],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        normalize_content_surface: Callable[[str | None], str],
        first_lineage_value: Callable[..., str],
        surface_from_pattern: Callable[[dict[str, Any], dict[str, Any]], str],
        ig_media_type_for_surface: Callable[[str, str], str],
        performance_metric_contract: Callable[[dict[str, Any]], dict[str, Any]],
        build_creative_knowledge_base: Callable[..., dict[str, Any]],
        build_creative_performance_analysis: Callable[..., dict[str, Any]],
        creative_knowledge_score_weights: Callable[[], dict[str, float]],
        creative_result_group: Callable[..., list[dict[str, Any]]],
        creative_knowledge_results_for_report: Callable[..., list[dict[str, Any]]],
        creative_dimension_label: Callable[[str], str],
        learning_confidence_classification: Callable[
            [list[dict[str, Any]]], dict[str, Any]
        ],
        creative_fatigue_signals: Callable[..., list[dict[str, Any]]],
        creative_surface_rows: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        recommendation_explainability: Callable[..., dict[str, Any]],
        recommendation_quality_bucket: Callable[[dict[str, Any]], str],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._creator_label = creator_label
        self._campaign_by_slug = campaign_by_slug
        self._normalize_content_surface = normalize_content_surface
        self._first_lineage_value = first_lineage_value
        self._surface_from_pattern = surface_from_pattern
        self._ig_media_type_for_surface = ig_media_type_for_surface
        self._performance_metric_contract = performance_metric_contract
        self._build_creative_knowledge_base = build_creative_knowledge_base
        self._build_creative_performance_analysis = build_creative_performance_analysis
        self._creative_knowledge_score_weights = creative_knowledge_score_weights
        self._creative_result_group = creative_result_group
        self._creative_knowledge_results_for_report = (
            creative_knowledge_results_for_report
        )
        self._creative_dimension_label = creative_dimension_label
        self._learning_confidence_classification = learning_confidence_classification
        self._creative_fatigue_signals = creative_fatigue_signals
        self._creative_surface_rows = creative_surface_rows
        self._recommendation_explainability = recommendation_explainability
        self._recommendation_quality_bucket = recommendation_quality_bucket
