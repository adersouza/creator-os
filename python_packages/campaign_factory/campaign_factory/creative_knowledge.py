from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .caption_outcome import load_context_json
from .persistence import json_load, utc_now


class CreativeKnowledgeRepository:
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

    def creative_knowledge_base(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_knowledge_base.v1",
            "creator": built["creator"],
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "sampleSize": built["sampleSize"],
            "minimumSampleSize": built["minimumSampleSize"],
            "insufficientData": built["insufficientData"],
            "reason": built["reason"],
            "scoreFormula": "views*0.35 + reach*0.25 + saves*4 + shares*5 + followers*10",
            "scoreWeights": self._creative_knowledge_score_weights(),
            "metricsContract": {
                "revenueExcluded": True,
                "visibleMetricFields": [
                    "views",
                    "reach",
                    "likes",
                    "comments",
                    "shares",
                    "saves",
                    "followers",
                    "profile_visits",
                ],
                "optionalStoryMetricFields": [
                    "exits",
                    "replies",
                    "taps_forward",
                    "taps_back",
                ],
            },
            "topConcepts": built["topConcepts"],
            "topCaptionAngles": built["topCaptionAngles"],
            "topCaptionVersions": built["topCaptionVersions"],
            "topAudioIds": built["topAudioIds"],
            "topSurfaces": built["topSurfaces"],
            "topStoryIntents": built["topStoryIntents"],
            "topAccountTiers": built["topAccountTiers"],
            "topPostingWindows": built["topPostingWindows"],
            "wouldWrite": False,
        }

    def creative_pattern_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_pattern_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "concepts": kb.get("topConcepts") or [],
            "captionAngles": kb.get("topCaptionAngles") or [],
            "postingWindows": kb.get("topPostingWindows") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_caption_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        rows = (
            []
            if kb["insufficientData"]
            else [
                self._creative_result_group(
                    self._creative_knowledge_results_for_report(
                        kb, creator, campaign_slug
                    ),
                    "captionHash",
                    limit=limit,
                ),
                self._creative_result_group(
                    self._creative_knowledge_results_for_report(
                        kb, creator, campaign_slug
                    ),
                    "instagramPostCaptionHash",
                    limit=limit,
                ),
            ]
        )
        caption_hashes = rows[0] if rows else []
        instagram_post_caption_hashes = rows[1] if len(rows) > 1 else []
        return {
            "schema": "campaign_factory.creative_caption_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "captionAngles": kb.get("topCaptionAngles") or [],
            "captionVersions": kb.get("topCaptionVersions") or [],
            "captionHashes": caption_hashes,
            "instagramPostCaptionHashes": instagram_post_caption_hashes,
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_audio_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_audio_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "audioIds": kb.get("topAudioIds") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_surface_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_surface_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "surfaces": kb.get("topSurfaces") or [],
            "storyIntents": kb.get("topStoryIntents") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_account_tier_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_account_tier_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "accountTiers": kb.get("topAccountTiers") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_window_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_window_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "postingWindows": kb.get("topPostingWindows") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_performance_analysis(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_performance_analysis.v1",
            "creator": analysis["creator"],
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "sampleSize": analysis["sampleSize"],
            "minimumSampleSize": analysis["minimumSampleSize"],
            "confidence": analysis["confidence"],
            "creatorBaseline": analysis["creatorBaseline"],
            "insufficientData": analysis["insufficientData"],
            "reason": analysis["reason"],
            "bestPerformingPatterns": analysis["bestPerformingPatterns"],
            "underperformingPatterns": analysis["underperformingPatterns"],
            "recommendedMoreOf": analysis["recommendedMoreOf"],
            "recommendedLessOf": analysis["recommendedLessOf"],
            "surfacesAnalyzed": ["reel", "story", "feed_single", "feed_carousel"],
            "wouldWrite": False,
        }

    def creator_learning_summary(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        summary: list[str] = []
        if analysis["insufficientData"]:
            summary.append(
                "Not enough published Instagram-visible metrics yet to identify reliable creative patterns."
            )
        else:
            for item in analysis["bestPerformingPatterns"][:3]:
                label = self._creative_dimension_label(str(item.get("dimension") or ""))
                summary.append(
                    f"{item.get('key')} {label} is performing above the creator baseline."
                )
            if analysis["underperformingPatterns"]:
                weak = analysis["underperformingPatterns"][0]
                label = self._creative_dimension_label(str(weak.get("dimension") or ""))
                summary.append(
                    f"{weak.get('key')} {label} is below the creator baseline and should be reworked or used carefully."
                )
        return {
            "schema": "campaign_factory.creator_learning_summary.v1",
            "creator": analysis["creator"],
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "summary": summary,
            "recommendations": analysis.get("recommendedMoreOf") or [],
            "confidence": analysis["confidence"],
            "insufficientData": analysis["insufficientData"],
            "reason": analysis["reason"],
            "wouldWrite": False,
        }

    def next_content_recommendations(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        recommendations = list(analysis.get("recommendedMoreOf") or [])
        return {
            "schema": "campaign_factory.next_content_recommendations.v1",
            "creator": analysis["creator"],
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "recommendations": recommendations[: max(1, int(limit or 10))],
            "avoidOrRework": list(analysis.get("recommendedLessOf") or [])[
                : max(1, int(limit or 10))
            ],
            "confidence": analysis["confidence"],
            "insufficientData": analysis["insufficientData"],
            "reason": analysis["reason"],
            "wouldWrite": False,
        }

    def creative_learning_confidence_model(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=1,
            limit=100,
        )
        results = list(built.get("results") or [])
        classification = self._learning_confidence_classification(results)
        return {
            "schema": "campaign_factory.creative_learning_confidence_model.v1",
            "creator": built["creator"],
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "sampleSize": len(results),
            "minimumSampleSize": max(1, int(minimum_sample_size or 1)),
            "confidenceModel": {
                "lowConfidenceSignals": [
                    "small_sample_size",
                    "new_surface",
                    "new_concept",
                    "new_caption_angle",
                    "single_account_evidence",
                ],
                "mediumConfidenceSignals": [
                    "ten_or_more_posts",
                    "repeated_pattern",
                    "multiple_surface_or_account_evidence",
                ],
                "highConfidenceSignals": [
                    "fifty_or_more_posts",
                    "repeated_wins",
                    "consistent_metrics",
                    "multiple_accounts",
                    "multiple_posts",
                ],
                "scoringRule": "simple measured coverage only; no ML and no predictions",
            },
            "currentConfidence": classification,
            "wouldWrite": False,
        }

    def creative_fatigue_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=1,
            limit=100,
        )
        results = list(built.get("results") or [])
        signals: list[dict[str, Any]] = []
        for fatigue_type, field in [
            ("concept_fatigue", "conceptId"),
            ("caption_fatigue", "captionAngle"),
            ("audio_fatigue", "audioId"),
            ("posting_window_fatigue", "postingWindow"),
        ]:
            signals.extend(
                self._creative_fatigue_signals(
                    results, field=field, fatigue_type=fatigue_type
                )
            )
        signals = sorted(
            signals,
            key=lambda item: (
                float(item.get("reachDeclinePct") or 0),
                str(item.get("key") or ""),
            ),
        )[: max(1, int(limit or 20))]
        return {
            "schema": "campaign_factory.creative_fatigue_report.v1",
            "creator": built["creator"],
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "fatigueSignals": signals,
            "signalRules": [
                "reach_decline",
                "impression_decline",
                "engagement_decline",
            ],
            "wouldWrite": False,
        }

    def creative_surface_comparison_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=1,
            limit=100,
        )
        results = list(built.get("results") or [])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            concept_id = str(item.get("conceptId") or "").strip()
            if concept_id:
                grouped.setdefault(concept_id, []).append(item)
        concepts: list[dict[str, Any]] = []
        for concept_id, items in grouped.items():
            surfaces = self._creative_surface_rows(items)
            concepts.append(
                {
                    "conceptId": concept_id,
                    "sampleSize": len(items),
                    "surfaces": surfaces,
                    "bestSurface": surfaces[0]["surface"] if surfaces else "",
                    "wouldWrite": False,
                }
            )
        concepts = sorted(
            concepts,
            key=lambda item: (
                -int(item.get("sampleSize") or 0),
                str(item.get("conceptId") or ""),
            ),
        )[: max(1, int(limit or 20))]
        return {
            "schema": "campaign_factory.creative_surface_comparison_report.v1",
            "creator": built["creator"],
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "concepts": concepts,
            "wouldWrite": False,
        }

    def recommendation_quality_audit(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 20,
    ) -> dict[str, Any]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        recommendations = list(analysis.get("recommendedMoreOf") or []) + list(
            analysis.get("recommendedLessOf") or []
        )
        rows = []
        buckets = {
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0,
            "insufficient_data": 0,
        }
        if analysis.get("insufficientData"):
            buckets["insufficient_data"] += 1
        for rec in recommendations:
            explainability = (
                rec.get("explainability")
                if isinstance(rec.get("explainability"), dict)
                else self._recommendation_explainability(
                    rec, confidence=analysis.get("confidence")
                )
            )
            classification = self._recommendation_quality_bucket(explainability)
            buckets[classification] = buckets.get(classification, 0) + 1
            rows.append(
                {
                    "recommendation": rec.get("recommendation")
                    or rec.get("recommendedAction")
                    or "",
                    "surface": rec.get("surface") or "",
                    "reason": explainability.get("reason") or "",
                    "classification": classification,
                    "explainability": explainability,
                    "wouldWrite": False,
                }
            )
        return {
            "schema": "campaign_factory.recommendation_quality_audit.v1",
            "creator": self._creator_label(creator),
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "recommendationsAudited": len(rows),
            "qualityBuckets": buckets,
            "recommendations": rows,
            "wouldWrite": False,
        }

    def build_creative_knowledge_base(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        rows = self.creative_knowledge_rows(
            creator=creator_label, campaign_slug=campaign_slug
        )
        results = [self.creative_knowledge_result(row) for row in rows]
        minimum = max(1, int(minimum_sample_size or 1))
        insufficient = len(results) < minimum
        reason = "not_enough_published_metrics" if insufficient else ""
        top_concepts = self.creative_result_group(results, "conceptId", limit=limit)
        top_caption_angles = self.creative_result_group(
            results, "captionAngle", limit=limit
        )
        top_caption_versions = self.creative_result_group(
            results, "captionVersionId", limit=limit
        )
        top_audio_ids = self.creative_result_group(results, "audioId", limit=limit)
        top_surfaces = self.creative_result_group(
            results, "contentSurface", limit=limit
        )
        top_story_intents = self.creative_result_group(
            results, "storyIntent", limit=limit
        )
        top_account_tiers = self.creative_result_group(
            results, "accountTier", limit=limit
        )
        top_posting_windows = self.creative_result_group(
            results, "postingWindow", limit=limit
        )
        if insufficient:
            top_concepts = []
            top_caption_angles = []
            top_caption_versions = []
            top_audio_ids = []
            top_surfaces = []
            top_story_intents = []
            top_account_tiers = []
            top_posting_windows = []
        return {
            "creator": creator_label,
            "rows": rows,
            "results": results,
            "sampleSize": len(results),
            "minimumSampleSize": minimum,
            "insufficientData": insufficient,
            "reason": reason,
            "topConcepts": top_concepts,
            "topCaptionAngles": top_caption_angles,
            "topCaptionVersions": top_caption_versions,
            "topAudioIds": top_audio_ids,
            "topSurfaces": top_surfaces,
            "topStoryIntents": top_story_intents,
            "topAccountTiers": top_account_tiers,
            "topPostingWindows": top_posting_windows,
            "wouldWrite": False,
        }

    def build_creative_performance_analysis(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        built = self.build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=1,
            limit=max(limit, 25),
        )
        results = list(built.get("results") or [])
        minimum = max(1, int(minimum_sample_size or 1))
        baseline = self.creative_performance_baseline(results)
        insufficient = len(results) < minimum
        reason = "not_enough_published_metrics" if insufficient else ""
        best: list[dict[str, Any]] = []
        weak: list[dict[str, Any]] = []
        if not insufficient:
            for dimension, key_field in [
                ("concept", "conceptId"),
                ("contentSurface", "contentSurface"),
                ("captionAngle", "captionAngle"),
                ("audioId", "audioId"),
                ("storyIntent", "storyIntent"),
                ("storyStyle", "storyStyle"),
                ("accountTier", "accountTier"),
                ("postingWindow", "postingWindow"),
            ]:
                for group in self.creative_result_group(
                    results, key_field, limit=max(limit, 25)
                ):
                    assessment = self.creative_performance_assessment(
                        group, baseline, dimension=dimension
                    )
                    if assessment["comparison"] == "above_creator_baseline":
                        best.append(assessment)
                    elif assessment["comparison"] == "below_creator_baseline":
                        weak.append(assessment)
        best = sorted(
            best,
            key=lambda item: (
                self.creative_pattern_priority(str(item.get("dimension") or "")),
                -float(item.get("scoreLiftPct") or 0),
                -float(item.get("score") or 0),
                str(item.get("key") or ""),
            ),
        )[: max(1, int(limit or 10))]
        weak = sorted(
            weak,
            key=lambda item: (
                self.creative_pattern_priority(str(item.get("dimension") or "")),
                float(item.get("scoreLiftPct") or 0),
                float(item.get("score") or 0),
                str(item.get("key") or ""),
            ),
        )[: max(1, int(limit or 10))]
        confidence = self.creative_analysis_confidence(len(results))
        return {
            "creator": built["creator"],
            "sampleSize": len(results),
            "minimumSampleSize": minimum,
            "confidence": confidence,
            "creatorBaseline": baseline,
            "insufficientData": insufficient,
            "reason": reason,
            "bestPerformingPatterns": [] if insufficient else best,
            "underperformingPatterns": [] if insufficient else weak,
            "recommendedMoreOf": []
            if insufficient
            else self.creative_more_recommendations(best, confidence, limit=limit),
            "recommendedLessOf": []
            if insufficient
            else self.creative_less_recommendations(weak, confidence, limit=limit),
            "wouldWrite": False,
        }

    def creative_performance_baseline(
        self, results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        count = len(results)
        totals = {
            "views": sum(
                int((item.get("metrics") or {}).get("views") or 0) for item in results
            ),
            "reach": sum(
                int((item.get("metrics") or {}).get("reach") or 0) for item in results
            ),
            "saves": sum(
                int((item.get("metrics") or {}).get("saves") or 0) for item in results
            ),
            "shares": sum(
                int((item.get("metrics") or {}).get("shares") or 0) for item in results
            ),
            "followers": sum(
                int((item.get("metrics") or {}).get("followers") or 0)
                for item in results
            ),
        }
        averages = {
            key: (value / count if count else 0) for key, value in totals.items()
        }
        return {
            "postCount": count,
            "avgViews": round(averages["views"], 2),
            "avgReach": round(averages["reach"], 2),
            "avgSaves": round(averages["saves"], 2),
            "avgShares": round(averages["shares"], 2),
            "avgFollowers": round(averages["followers"], 2),
            "score": self.creative_knowledge_score(averages),
        }

    def creative_performance_assessment(
        self, group: dict[str, Any], baseline: dict[str, Any], *, dimension: str
    ) -> dict[str, Any]:
        base_score = float(baseline.get("score") or 0)
        score = float(group.get("score") or 0)
        lift_pct = (
            ((score - base_score) / base_score * 100.0)
            if base_score > 0
            else (100.0 if score > 0 else 0.0)
        )
        if lift_pct >= 15.0:
            comparison = "above_creator_baseline"
            reason = f"{group.get('key')} is {round(lift_pct, 1)}% above creator baseline using Instagram-visible metrics."
        elif lift_pct <= -15.0:
            comparison = "below_creator_baseline"
            reason = f"{group.get('key')} is {abs(round(lift_pct, 1))}% below creator baseline using Instagram-visible metrics."
        else:
            comparison = "near_creator_baseline"
            reason = f"{group.get('key')} is near creator baseline using Instagram-visible metrics."
        return {
            **group,
            "dimension": dimension,
            "comparison": comparison,
            "sampleSize": int(group.get("sampleSize") or 0),
            "baselineMetric": "score",
            "observedMetric": "score",
            "baselineValue": round(base_score, 2),
            "observedValue": round(score, 2),
            "scoreLiftPct": round(lift_pct, 2),
            "reason": reason,
        }

    def creative_more_recommendations(
        self, best: list[dict[str, Any]], confidence: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for item in best:
            lineage = (
                item.get("lineage") if isinstance(item.get("lineage"), dict) else {}
            )
            surface = self._surface_from_pattern(item, lineage)
            recommendation = (
                "make_more_variants"
                if surface == "reel"
                else "make_more_similar_assets"
            )
            if (
                surface == "story"
                and item.get("dimension") == "storyIntent"
                and item.get("key") == "snapchat_promo"
            ):
                recommendation = "make_more_snapchat_promo_stories"
            payload = {
                "surface": surface,
                "recommendation": recommendation,
                "reason": item.get("reason")
                or "Pattern outperformed creator baseline.",
                "parentAssetId": self._first_lineage_value(lineage, "parentAssetIds"),
                "captionAngle": item.get("key")
                if item.get("dimension") == "captionAngle"
                else self._first_lineage_value(lineage, "captionAngles", fallback=""),
                "audioId": item.get("key")
                if item.get("dimension") == "audioId"
                else self._first_lineage_value(lineage, "audioIds"),
                "storyIntent": item.get("key")
                if item.get("dimension") == "storyIntent"
                else "",
                "confidence": confidence,
                "sampleSize": int(item.get("sampleSize") or 0),
                "baselineMetric": item.get("baselineMetric") or "score",
                "observedMetric": item.get("observedMetric") or "score",
                "scoreLiftPct": item.get("scoreLiftPct") or 0,
            }
            payload["explainability"] = self.recommendation_explainability(
                payload, item=item, confidence=confidence
            )
            recommendations.append(payload)
        recommendations = sorted(
            recommendations,
            key=lambda item: (
                0
                if item.get("recommendation") == "make_more_snapchat_promo_stories"
                else 1,
                0 if item.get("recommendation") == "make_more_variants" else 1,
                str(item.get("surface") or ""),
            ),
        )
        return recommendations[: max(1, int(limit or 10))]

    def creative_less_recommendations(
        self, weak: list[dict[str, Any]], confidence: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for item in weak:
            lineage = (
                item.get("lineage") if isinstance(item.get("lineage"), dict) else {}
            )
            payload = {
                "surface": self._surface_from_pattern(item, lineage),
                "recommendation": "avoid_or_rework_pattern",
                "reason": item.get("reason")
                or "Pattern underperformed creator baseline.",
                "patternDimension": item.get("dimension") or "",
                "patternKey": item.get("key") or "",
                "confidence": confidence,
                "sampleSize": int(item.get("sampleSize") or 0),
                "baselineMetric": item.get("baselineMetric") or "score",
                "observedMetric": item.get("observedMetric") or "score",
                "scoreLiftPct": item.get("scoreLiftPct") or 0,
            }
            payload["explainability"] = self.recommendation_explainability(
                payload, item=item, confidence=confidence
            )
            recommendations.append(payload)
        return recommendations[: max(1, int(limit or 10))]

    def recommendation_explainability(
        self,
        recommendation: dict[str, Any],
        *,
        item: dict[str, Any] | None = None,
        confidence: Any = None,
    ) -> dict[str, Any]:
        source = item if isinstance(item, dict) else recommendation
        return {
            "reason": str(recommendation.get("reason") or source.get("reason") or ""),
            "confidence": self.confidence_score(
                confidence
                if confidence is not None
                else recommendation.get("confidence")
            ),
            "confidenceLabel": str(
                confidence
                if confidence is not None
                else recommendation.get("confidence") or "low"
            ),
            "sampleSize": int(
                recommendation.get("sampleSize") or source.get("sampleSize") or 0
            ),
            "baselineMetric": str(
                recommendation.get("baselineMetric")
                or source.get("baselineMetric")
                or "score"
            ),
            "observedMetric": str(
                recommendation.get("observedMetric")
                or source.get("observedMetric")
                or "score"
            ),
            "baselineValue": round(
                float(
                    source.get("baselineValue")
                    or recommendation.get("baselineValue")
                    or 0
                ),
                2,
            ),
            "observedValue": round(
                float(
                    source.get("observedValue")
                    or recommendation.get("observedValue")
                    or source.get("score")
                    or 0
                ),
                2,
            ),
            "scoreLiftPct": round(
                float(
                    recommendation.get("scoreLiftPct")
                    or source.get("scoreLiftPct")
                    or 0
                ),
                2,
            ),
        }

    def confidence_score(self, confidence: Any) -> int:
        if isinstance(confidence, (int, float)):
            return max(0, min(100, int(confidence)))
        return {"high": 90, "medium": 65, "low": 35}.get(str(confidence or "low"), 35)

    def learning_confidence_classification(
        self, results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        sample_size = len(results)
        account_count = len(
            {
                str(item.get("accountId") or "")
                for item in results
                if item.get("accountId")
            }
        )
        surface_count = len(
            {
                str(item.get("contentSurface") or "")
                for item in results
                if item.get("contentSurface")
            }
        )
        concept_count = len(
            {
                str(item.get("conceptId") or "")
                for item in results
                if item.get("conceptId")
            }
        )
        caption_angle_count = len(
            {
                str(item.get("captionAngle") or "")
                for item in results
                if item.get("captionAngle")
            }
        )
        signals: list[str] = []
        if sample_size < 10:
            signals.append("small_sample_size")
        if surface_count <= 1:
            signals.append("new_surface_or_single_surface")
        if concept_count <= 1:
            signals.append("new_concept_or_single_concept")
        if caption_angle_count <= 1:
            signals.append("new_caption_angle_or_single_angle")
        if account_count <= 1:
            signals.append("single_account_evidence")
        if sample_size >= 50 and account_count >= 3:
            classification = "high_confidence"
            score = 90
        elif sample_size >= 10 and account_count >= 2:
            classification = "medium_confidence"
            score = 65
        else:
            classification = "low_confidence"
            score = 35
        return {
            "classification": classification,
            "confidence": score,
            "sampleSize": sample_size,
            "accountCount": account_count,
            "surfaceCount": surface_count,
            "conceptCount": concept_count,
            "captionAngleCount": caption_angle_count,
            "limitingSignals": signals,
        }

    def creative_fatigue_signals(
        self, results: list[dict[str, Any]], *, field: str, fatigue_type: str
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            key = str(item.get(field) or "").strip()
            if key:
                grouped.setdefault(key, []).append(item)
        signals: list[dict[str, Any]] = []
        for key, items in grouped.items():
            if len(items) < 3:
                continue
            ordered = sorted(items, key=lambda item: str(item.get("publishedAt") or ""))
            midpoint = max(1, len(ordered) // 2)
            early = ordered[:midpoint]
            recent = ordered[midpoint:]
            if not recent:
                continue
            reach_decline = self.metric_decline_pct(early, recent, "reach")
            view_decline = self.metric_decline_pct(early, recent, "views")
            engagement_decline = self.engagement_decline_pct(early, recent)
            if min(reach_decline, view_decline, engagement_decline) <= -20:
                signals.append(
                    {
                        "fatigueType": fatigue_type,
                        "key": key,
                        "sampleSize": len(items),
                        "reachDeclinePct": reach_decline,
                        "impressionDeclinePct": view_decline,
                        "engagementDeclinePct": engagement_decline,
                        "reason": f"{key} shows measured decline across recent posts.",
                        "wouldWrite": False,
                    }
                )
        return signals

    def metric_decline_pct(
        self, early: list[dict[str, Any]], recent: list[dict[str, Any]], metric: str
    ) -> float:
        early_avg = self.avg_result_metric(early, metric)
        recent_avg = self.avg_result_metric(recent, metric)
        if early_avg <= 0:
            return 0.0
        return round((recent_avg - early_avg) / early_avg * 100.0, 2)

    def engagement_decline_pct(
        self, early: list[dict[str, Any]], recent: list[dict[str, Any]]
    ) -> float:
        def engagement(items: list[dict[str, Any]]) -> float:
            if not items:
                return 0.0
            total = 0
            for item in items:
                metrics = (
                    item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
                )
                total += (
                    int(metrics.get("likes") or 0)
                    + int(metrics.get("comments") or 0)
                    + int(metrics.get("shares") or 0)
                    + int(metrics.get("saves") or 0)
                )
            return total / len(items)

        early_avg = engagement(early)
        recent_avg = engagement(recent)
        if early_avg <= 0:
            return 0.0
        return round((recent_avg - early_avg) / early_avg * 100.0, 2)

    def avg_result_metric(self, items: list[dict[str, Any]], metric: str) -> float:
        if not items:
            return 0.0
        return sum(
            int((item.get("metrics") or {}).get(metric) or 0) for item in items
        ) / len(items)

    def creative_surface_rows(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            surface = self._normalize_content_surface(
                item.get("contentSurface") or "reel"
            )
            grouped.setdefault(surface, []).append(item)
        rows = []
        for surface, surface_items in grouped.items():
            metric_totals = {
                "views": self.avg_result_metric(surface_items, "views"),
                "reach": self.avg_result_metric(surface_items, "reach"),
                "saves": self.avg_result_metric(surface_items, "saves"),
                "shares": self.avg_result_metric(surface_items, "shares"),
                "followers": self.avg_result_metric(surface_items, "followers"),
            }
            rows.append(
                {
                    "surface": surface,
                    "sampleSize": len(surface_items),
                    "avgViews": round(metric_totals["views"], 2),
                    "avgReach": round(metric_totals["reach"], 2),
                    "avgSaves": round(metric_totals["saves"], 2),
                    "avgShares": round(metric_totals["shares"], 2),
                    "score": self.creative_knowledge_score(metric_totals),
                    "sourcePostIds": sorted(
                        {
                            str(item.get("postId") or "")
                            for item in surface_items
                            if item.get("postId")
                        }
                    ),
                }
            )
        return sorted(
            rows,
            key=lambda item: (
                -float(item.get("score") or 0),
                str(item.get("surface") or ""),
            ),
        )

    def recommendation_quality_bucket(self, explainability: dict[str, Any]) -> str:
        sample_size = int(explainability.get("sampleSize") or 0)
        confidence = int(explainability.get("confidence") or 0)
        if sample_size <= 0:
            return "insufficient_data"
        if confidence >= 80 and sample_size >= 10:
            return "high_confidence"
        if confidence >= 60 and sample_size >= 3:
            return "medium_confidence"
        return "low_confidence"

    def creative_analysis_confidence(self, sample_size: int) -> str:
        if sample_size >= 50:
            return "high"
        if sample_size >= 10:
            return "medium"
        return "low"

    def creative_dimension_label(self, dimension: str) -> str:
        return {
            "concept": "concept",
            "contentSurface": "surface",
            "captionAngle": "caption angle",
            "audioId": "audio family",
            "storyIntent": "story intent",
            "storyStyle": "story style",
            "accountTier": "account tier",
            "postingWindow": "posting window",
        }.get(dimension, "pattern")

    def creative_pattern_priority(self, dimension: str) -> int:
        return {
            "concept": 0,
            "storyIntent": 1,
            "captionAngle": 2,
            "audioId": 3,
            "storyStyle": 4,
            "contentSurface": 5,
            "accountTier": 6,
            "postingWindow": 7,
        }.get(dimension, 99)

    def creative_knowledge_results_for_report(
        self, kb: dict[str, Any], creator: str, campaign_slug: str | None
    ) -> list[dict[str, Any]]:
        if kb.get("insufficientData"):
            return []
        return [
            self.creative_knowledge_result(row)
            for row in self.creative_knowledge_rows(
                creator=kb["creator"] or self._creator_label(creator),
                campaign_slug=campaign_slug,
            )
        ]

    def creative_knowledge_rows(
        self, *, creator: str, campaign_slug: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["p.metrics_eligible = 1"]
        params: list[Any] = []
        if campaign_slug:
            campaign = self._campaign_by_slug(campaign_slug)
            clauses.append("p.campaign_id = ?")
            params.append(campaign["id"])
        clauses.append(
            """
            (
              LOWER(COALESCE(p.creator_mix, '')) = LOWER(?)
              OR LOWER(COALESCE(p.creator_model, '')) = LOWER(?)
              OR LOWER(COALESCE(c.creator, '')) = LOWER(?)
              OR LOWER(COALESCE(m.name, '')) = LOWER(?)
              OR LOWER(COALESCE(m.slug, '')) = LOWER(?)
            )
            """
        )
        params.extend([creator, creator, creator, creator, self._slugify(creator)])
        rows = self.conn.execute(
            f"""
            SELECT p.*, campaigns.slug AS campaign_slug, campaigns.platform AS campaign_platform,
                   c.metadata_json AS concept_metadata_json, c.creator AS concept_creator,
                   c.parent_asset_id AS concept_parent_asset_id,
                   a.handle AS account_username, a.external_id AS account_external_id,
                   m.slug AS model_slug, m.name AS model_name
            FROM performance_snapshots p
            JOIN campaigns ON campaigns.id = p.campaign_id
            LEFT JOIN concepts c ON c.id = p.concept_id
            LEFT JOIN accounts a ON a.id = p.account_id OR a.external_id = p.instagram_account_id
            LEFT JOIN models m ON m.id = a.model_id
            WHERE {" AND ".join(clauses)}
            ORDER BY p.snapshot_at DESC, p.created_at DESC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def creative_knowledge_result(self, row: dict[str, Any]) -> dict[str, Any]:
        raw = json_load(row.get("raw_json"), {})
        if not isinstance(raw, dict):
            raw = {}
        context = load_context_json(row.get("caption_outcome_context_json"))
        metrics = {
            "views": int(row.get("views") or 0),
            "reach": int(row.get("reach") or 0),
            "likes": int(row.get("likes") or 0),
            "comments": int(row.get("comments") or 0),
            "shares": int(row.get("shares") or 0),
            "saves": int(row.get("saves") or 0),
            "followers": int(raw.get("followers") or raw.get("follows") or 0),
            "profile_visits": int(
                raw.get("profile_visits") or raw.get("profileVisits") or 0
            ),
            "story_exits": int(raw.get("story_exits") or raw.get("exits") or 0),
            "story_replies": int(raw.get("story_replies") or raw.get("replies") or 0),
            "story_taps": int(
                raw.get("story_taps") or raw.get("taps") or raw.get("taps_forward") or 0
            ),
        }
        content_surface = self._normalize_content_surface(row.get("content_surface"))
        published_at = row.get("published_at")
        instagram_hash = (
            context.get("instagram_post_caption_hash")
            or context.get("instagramPostCaptionHash")
            or raw.get("instagram_post_caption_hash")
            or raw.get("instagramPostCaptionHash")
            or ""
        )
        story_intent = (
            context.get("storyIntent")
            or context.get("story_intent")
            or raw.get("story_intent")
            or raw.get("storyIntent")
            or ""
        )
        story_style = (
            context.get("storyStyle")
            or context.get("story_style")
            or raw.get("story_style")
            or raw.get("storyStyle")
            or ""
        )
        story_goal = (
            context.get("storyGoal")
            or context.get("story_goal")
            or raw.get("story_goal")
            or raw.get("storyGoal")
            or ""
        )
        return {
            "creator": self._creator_label(
                row.get("creator_mix")
                or row.get("creator_model")
                or row.get("concept_creator")
                or row.get("model_name")
                or row.get("model_slug")
            ),
            "campaign": row.get("campaign_slug") or "",
            "contentSurface": content_surface,
            "igMediaType": raw.get("ig_media_type")
            or raw.get("igMediaType")
            or self._ig_media_type_for_surface(content_surface, "video"),
            "accountId": row.get("account_id") or "",
            "accountUsername": row.get("account_username")
            or raw.get("account_username")
            or raw.get("accountUsername")
            or "",
            "accountTier": raw.get("account_tier") or raw.get("accountTier") or "",
            "conceptId": row.get("concept_id") or "",
            "parentAssetId": row.get("concept_parent_asset_id")
            or row.get("rendered_asset_id")
            or "",
            "parentReelId": row.get("parent_reel_id") or "",
            "variantFamilyId": row.get("variant_family_id") or "",
            "variantId": row.get("variant_id") or "",
            "captionFamilyId": context.get("caption_family_id")
            or context.get("captionFamilyId")
            or "",
            "captionVersionId": context.get("caption_version_id")
            or context.get("captionVersionId")
            or "",
            "captionAngle": row.get("caption_angle")
            or context.get("caption_angle")
            or context.get("captionAngle")
            or "",
            "captionHash": row.get("caption_hash") or "",
            "instagramPostCaptionHash": instagram_hash,
            "audioId": row.get("audio_id") or "",
            "storyIntent": str(story_intent or ""),
            "storyStyle": str(story_style or ""),
            "storyGoal": str(story_goal or ""),
            "postingWindow": self.posting_window_label(published_at),
            "publishedAt": published_at,
            "postId": row.get("post_id") or "",
            "metrics": metrics,
            "metricsContract": self._performance_metric_contract(row),
            "score": self.creative_knowledge_score(metrics),
        }

    def creative_knowledge_score_weights(self) -> dict[str, float]:
        return {
            "views": 0.35,
            "reach": 0.25,
            "saves": 4.0,
            "shares": 5.0,
            "followers": 10.0,
        }

    def creative_knowledge_score(self, metrics: dict[str, Any]) -> float:
        weights = self.creative_knowledge_score_weights()
        score = sum(
            float(metrics.get(key) or 0) * weight for key, weight in weights.items()
        )
        return round(score, 2)

    def creative_result_group(
        self, results: list[dict[str, Any]], key_field: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for result in results:
            key = str(result.get(key_field) or "").strip()
            if not key:
                continue
            entry = grouped.setdefault(key, {"key": key, "items": []})
            entry["items"].append(result)
        output: list[dict[str, Any]] = []
        for key, entry in grouped.items():
            items = entry["items"]
            sample_size = len(items)
            metric_totals = {
                "views": sum(
                    int((item.get("metrics") or {}).get("views") or 0) for item in items
                ),
                "reach": sum(
                    int((item.get("metrics") or {}).get("reach") or 0) for item in items
                ),
                "saves": sum(
                    int((item.get("metrics") or {}).get("saves") or 0) for item in items
                ),
                "shares": sum(
                    int((item.get("metrics") or {}).get("shares") or 0)
                    for item in items
                ),
                "followers": sum(
                    int((item.get("metrics") or {}).get("followers") or 0)
                    for item in items
                ),
            }
            avg_metrics = {
                name: (value / sample_size if sample_size else 0)
                for name, value in metric_totals.items()
            }
            output.append(
                {
                    "key": key,
                    "sampleSize": sample_size,
                    "avgViews": round(avg_metrics["views"], 2),
                    "avgReach": round(avg_metrics["reach"], 2),
                    "avgSaves": round(avg_metrics["saves"], 2),
                    "avgShares": round(avg_metrics["shares"], 2),
                    "avgFollowers": round(avg_metrics["followers"], 2),
                    "score": self.creative_knowledge_score(avg_metrics),
                    "sourcePostIds": sorted(
                        {
                            str(item.get("postId") or "")
                            for item in items
                            if item.get("postId")
                        }
                    ),
                    "lineage": self.creative_result_lineage(items),
                }
            )
        return sorted(
            output,
            key=lambda item: (
                -float(item.get("score") or 0),
                -int(item.get("sampleSize") or 0),
                str(item.get("key") or ""),
            ),
        )[: max(1, int(limit or 10))]

    def creative_result_lineage(
        self, items: list[dict[str, Any]]
    ) -> dict[str, list[str]]:
        fields = {
            "campaigns": "campaign",
            "accountIds": "accountId",
            "accountUsernames": "accountUsername",
            "conceptIds": "conceptId",
            "parentAssetIds": "parentAssetId",
            "parentReelIds": "parentReelId",
            "variantFamilyIds": "variantFamilyId",
            "variantIds": "variantId",
            "captionFamilyIds": "captionFamilyId",
            "captionVersionIds": "captionVersionId",
            "captionAngles": "captionAngle",
            "captionHashes": "captionHash",
            "instagramPostCaptionHashes": "instagramPostCaptionHash",
            "audioIds": "audioId",
            "contentSurfaces": "contentSurface",
            "postingWindows": "postingWindow",
        }
        return {
            output_key: sorted(
                {str(item.get(field) or "") for item in items if item.get(field)}
            )
            for output_key, field in fields.items()
        }

    def winner_registry(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        knowledge = self._build_creative_knowledge_base(
            creator=creator_label,
            campaign_slug=campaign_slug,
            minimum_sample_size=1,
            limit=10,
        )
        rows = knowledge["rows"]
        reach_floor = min_reach if min_reach is not None else min_views
        winners: list[dict[str, Any]] = []
        seen_posts: set[str] = set()
        for row in rows:
            post_id = str(row.get("post_id") or "").strip()
            if not post_id or post_id in seen_posts:
                continue
            winner = self.winner_memory_item(
                row,
                min_views=min_views,
                min_reach=reach_floor,
                min_followers=min_followers,
            )
            seen_posts.add(post_id)
            if winner:
                winners.append(winner)
        return {
            "schema": "campaign_factory.winner_registry.v1",
            "creator": creator_label,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "minViews": min_views,
            "minReach": reach_floor,
            "minFollowers": min_followers,
            "summary": {
                "winnerCount": len(winners),
                "totalViews": sum(
                    int((item.get("metrics") or {}).get("views") or 0)
                    for item in winners
                ),
                "totalReach": sum(
                    int((item.get("metrics") or {}).get("reach") or 0)
                    for item in winners
                ),
            },
            "winners": winners,
            "wouldWrite": False,
        }

    def concept_registry(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        winners = self.winner_registry(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )
        concepts = self.winner_pattern_group(
            winners.get("winners") or [],
            key_field="conceptId",
            label_field="conceptName",
            output_key="conceptId",
            output_label="conceptName",
        )
        return {
            "schema": "campaign_factory.concept_registry.v1",
            "creator": winners["creator"],
            "campaign": winners.get("campaign"),
            "generatedAt": utc_now(),
            "concepts": concepts,
            "wouldWrite": False,
        }

    def winner_patterns(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        winners = self.winner_registry(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )
        items = winners.get("winners") or []
        patterns = {
            "topConcepts": self.winner_pattern_group(
                items,
                key_field="conceptId",
                label_field="conceptName",
                output_key="conceptId",
                output_label="conceptName",
            ),
            "topAudioFamilies": self.winner_pattern_group(
                items,
                key_field="audioId",
                label_field=None,
                output_key="audioId",
                output_label=None,
            ),
            "topCaptionAngles": self.winner_pattern_group(
                items,
                key_field="captionAngle",
                label_field=None,
                output_key="captionAngle",
                output_label=None,
            ),
            "topPostingWindows": self.winner_pattern_group(
                items,
                key_field="postingWindow",
                label_field=None,
                output_key="postingWindow",
                output_label=None,
            ),
        }
        return {
            "schema": "campaign_factory.winner_patterns.v1",
            "creator": winners["creator"],
            "campaign": winners.get("campaign"),
            "generatedAt": utc_now(),
            "winnerCount": winners["summary"]["winnerCount"],
            **patterns,
            "wouldWrite": False,
        }

    def winner_knowledge_base(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        registry = self.winner_registry(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )
        concepts = self.concept_registry(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )
        patterns = self.winner_patterns(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )
        return {
            "schema": "campaign_factory.winner_knowledge_base.v1",
            "creator": registry["creator"],
            "campaign": registry.get("campaign"),
            "generatedAt": utc_now(),
            "conceptRegistry": concepts.get("concepts") or [],
            "winnerRegistry": registry,
            "winnerPatterns": {
                "topConcepts": patterns.get("topConcepts") or [],
                "topAudioFamilies": patterns.get("topAudioFamilies") or [],
                "topCaptionAngles": patterns.get("topCaptionAngles") or [],
                "topPostingWindows": patterns.get("topPostingWindows") or [],
            },
            "wouldWrite": False,
        }

    def winner_memory_rows(
        self, *, creator: str, campaign_slug: str | None = None
    ) -> list[dict[str, Any]]:
        return self._build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=1,
            limit=10,
        )["rows"]

    def winner_memory_item(
        self,
        row: dict[str, Any],
        *,
        min_views: int,
        min_reach: int,
        min_followers: int,
    ) -> dict[str, Any] | None:
        raw = json_load(row.get("raw_json"), {})
        metrics = {
            "views": int(row.get("views") or 0),
            "reach": int(row.get("reach") or 0),
            "likes": int(row.get("likes") or 0),
            "comments": int(row.get("comments") or 0),
            "shares": int(row.get("shares") or 0),
            "saves": int(row.get("saves") or 0),
            "followers": int(raw.get("followers") or 0) if isinstance(raw, dict) else 0,
        }
        reason = ""
        primary_metric = ""
        threshold = 0
        if metrics["views"] >= min_views:
            reason = "high_views"
            primary_metric = "views"
            threshold = min_views
        elif metrics["reach"] >= min_reach:
            reason = "high_reach"
            primary_metric = "reach"
            threshold = min_reach
        elif metrics["followers"] >= min_followers:
            reason = "follower_growth"
            primary_metric = "followers"
            threshold = min_followers
        if not reason:
            return None
        concept_name = self.winner_concept_name(row)
        posting_window = self.posting_window_label(row.get("published_at"))
        return {
            "postId": row.get("post_id") or "",
            "assetId": row.get("rendered_asset_id") or "",
            "sourceAssetId": row.get("source_asset_id") or "",
            "campaign": row.get("campaign_slug"),
            "conceptId": row.get("concept_id") or "",
            "conceptName": concept_name,
            "parentReelId": row.get("parent_reel_id") or "",
            "variantFamilyId": row.get("variant_family_id") or "",
            "variantId": row.get("variant_id") or "",
            "audioId": row.get("audio_id") or "",
            "captionAngle": row.get("caption_angle") or "",
            "captionHash": row.get("caption_hash") or "",
            "captionFamilyId": row.get("caption_family_id") or "",
            "captionVersionId": row.get("caption_version_id") or "",
            "postingWindow": posting_window,
            "publishedAt": row.get("published_at"),
            "reason": reason,
            "why": {
                "reason": reason,
                "primaryMetric": primary_metric,
                "primaryMetricValue": metrics[primary_metric],
                "threshold": threshold,
                "visibleMetricFields": [
                    "views",
                    "reach",
                    "followers",
                    "likes",
                    "comments",
                    "shares",
                    "saves",
                ],
            },
            "metrics": metrics,
            "wouldWrite": False,
        }

    def winner_concept_name(self, row: dict[str, Any]) -> str:
        metadata = json_load(row.get("concept_metadata_json"), {})
        if isinstance(metadata, dict):
            for key in (
                "conceptName",
                "concept_name",
                "concept",
                "label",
                "name",
                "title",
            ):
                value = str(metadata.get(key) or "").strip()
                if value:
                    return value
        context = load_context_json(row.get("caption_outcome_context_json"))
        if isinstance(context, dict):
            for key in ("conceptName", "concept_name", "concept", "caption_angle"):
                value = str(context.get(key) or "").strip()
                if value:
                    return value
        return str(row.get("concept_id") or "unknown").strip() or "unknown"

    def posting_window_label(self, published_at: Any) -> str:
        text = str(published_at or "").strip()
        if not text:
            return ""
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
        hour = parsed.hour
        suffix = "am" if hour < 12 else "pm"
        display_hour = hour % 12 or 12
        return f"{display_hour}{suffix}"

    def winner_pattern_group(
        self,
        items: list[dict[str, Any]],
        *,
        key_field: str,
        label_field: str | None,
        output_key: str,
        output_label: str | None,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for item in items:
            key = str(item.get(key_field) or "").strip()
            if not key:
                continue
            entry = grouped.setdefault(
                key,
                {
                    output_key: key,
                    "winnerCount": 0,
                    "totalViews": 0,
                    "totalReach": 0,
                    "postIds": [],
                },
            )
            if output_label:
                label = str(item.get(label_field or "") or key).strip() or key
                entry[output_label] = label
            metrics = (
                item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            )
            entry["winnerCount"] += 1
            entry["totalViews"] += int(metrics.get("views") or 0)
            entry["totalReach"] += int(metrics.get("reach") or 0)
            entry["postIds"].append(item.get("postId"))
        for entry in grouped.values():
            count = max(1, int(entry["winnerCount"]))
            entry["averageViews"] = round(int(entry["totalViews"]) / count, 2)
        return sorted(
            grouped.values(),
            key=lambda item: (
                -int(item.get("winnerCount") or 0),
                -int(item.get("totalViews") or 0),
                str(item.get(output_label or output_key) or item.get(output_key) or ""),
            ),
        )
