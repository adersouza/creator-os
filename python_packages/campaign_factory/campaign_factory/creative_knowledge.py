from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Callable

from .caption_outcome import load_context_json
from .persistence import json_load, utc_now


class CreativeKnowledgeRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        creator_label: Callable[[Any], str],
        build_creative_knowledge_base: Callable[..., dict[str, Any]],
        build_creative_performance_analysis: Callable[..., dict[str, Any]],
        creative_knowledge_score_weights: Callable[[], dict[str, float]],
        creative_result_group: Callable[..., list[dict[str, Any]]],
        creative_knowledge_results_for_report: Callable[..., list[dict[str, Any]]],
        creative_dimension_label: Callable[[str], str],
        learning_confidence_classification: Callable[[list[dict[str, Any]]], dict[str, Any]],
        creative_fatigue_signals: Callable[..., list[dict[str, Any]]],
        creative_surface_rows: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        recommendation_explainability: Callable[..., dict[str, Any]],
        recommendation_quality_bucket: Callable[[dict[str, Any]], str],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._creator_label = creator_label
        self._build_creative_knowledge_base = build_creative_knowledge_base
        self._build_creative_performance_analysis = build_creative_performance_analysis
        self._creative_knowledge_score_weights = creative_knowledge_score_weights
        self._creative_result_group = creative_result_group
        self._creative_knowledge_results_for_report = creative_knowledge_results_for_report
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
                "visibleMetricFields": ["views", "reach", "likes", "comments", "shares", "saves", "followers", "profile_visits"],
                "optionalStoryMetricFields": ["exits", "replies", "taps_forward", "taps_back"],
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
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
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
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
        rows = [] if kb["insufficientData"] else [
            self._creative_result_group(self._creative_knowledge_results_for_report(kb, creator, campaign_slug), "captionHash", limit=limit),
            self._creative_result_group(self._creative_knowledge_results_for_report(kb, creator, campaign_slug), "instagramPostCaptionHash", limit=limit),
        ]
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
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
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
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
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
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
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
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
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
            summary.append("Not enough published Instagram-visible metrics yet to identify reliable creative patterns.")
        else:
            for item in analysis["bestPerformingPatterns"][:3]:
                label = self._creative_dimension_label(str(item.get("dimension") or ""))
                summary.append(f"{item.get('key')} {label} is performing above the creator baseline.")
            if analysis["underperformingPatterns"]:
                weak = analysis["underperformingPatterns"][0]
                label = self._creative_dimension_label(str(weak.get("dimension") or ""))
                summary.append(f"{weak.get('key')} {label} is below the creator baseline and should be reworked or used carefully.")
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
            "avoidOrRework": list(analysis.get("recommendedLessOf") or [])[: max(1, int(limit or 10))],
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
                "lowConfidenceSignals": ["small_sample_size", "new_surface", "new_concept", "new_caption_angle", "single_account_evidence"],
                "mediumConfidenceSignals": ["ten_or_more_posts", "repeated_pattern", "multiple_surface_or_account_evidence"],
                "highConfidenceSignals": ["fifty_or_more_posts", "repeated_wins", "consistent_metrics", "multiple_accounts", "multiple_posts"],
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
        built = self._build_creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=1, limit=100)
        results = list(built.get("results") or [])
        signals: list[dict[str, Any]] = []
        for fatigue_type, field in [
            ("concept_fatigue", "conceptId"),
            ("caption_fatigue", "captionAngle"),
            ("audio_fatigue", "audioId"),
            ("posting_window_fatigue", "postingWindow"),
        ]:
            signals.extend(self._creative_fatigue_signals(results, field=field, fatigue_type=fatigue_type))
        signals = sorted(signals, key=lambda item: (float(item.get("reachDeclinePct") or 0), str(item.get("key") or "")))[: max(1, int(limit or 20))]
        return {
            "schema": "campaign_factory.creative_fatigue_report.v1",
            "creator": built["creator"],
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "fatigueSignals": signals,
            "signalRules": ["reach_decline", "impression_decline", "engagement_decline"],
            "wouldWrite": False,
        }

    def creative_surface_comparison_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=1, limit=100)
        results = list(built.get("results") or [])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            concept_id = str(item.get("conceptId") or "").strip()
            if concept_id:
                grouped.setdefault(concept_id, []).append(item)
        concepts: list[dict[str, Any]] = []
        for concept_id, items in grouped.items():
            surfaces = self._creative_surface_rows(items)
            concepts.append({
                "conceptId": concept_id,
                "sampleSize": len(items),
                "surfaces": surfaces,
                "bestSurface": surfaces[0]["surface"] if surfaces else "",
                "wouldWrite": False,
            })
        concepts = sorted(concepts, key=lambda item: (-int(item.get("sampleSize") or 0), str(item.get("conceptId") or "")))[: max(1, int(limit or 20))]
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
        recommendations = list(analysis.get("recommendedMoreOf") or []) + list(analysis.get("recommendedLessOf") or [])
        rows = []
        buckets = {"high_confidence": 0, "medium_confidence": 0, "low_confidence": 0, "insufficient_data": 0}
        if analysis.get("insufficientData"):
            buckets["insufficient_data"] += 1
        for rec in recommendations:
            explainability = rec.get("explainability") if isinstance(rec.get("explainability"), dict) else self._recommendation_explainability(rec, confidence=analysis.get("confidence"))
            classification = self._recommendation_quality_bucket(explainability)
            buckets[classification] = buckets.get(classification, 0) + 1
            rows.append({
                "recommendation": rec.get("recommendation") or rec.get("recommendedAction") or "",
                "surface": rec.get("surface") or "",
                "reason": explainability.get("reason") or "",
                "classification": classification,
                "explainability": explainability,
                "wouldWrite": False,
            })
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
                "totalViews": sum(int((item.get("metrics") or {}).get("views") or 0) for item in winners),
                "totalReach": sum(int((item.get("metrics") or {}).get("reach") or 0) for item in winners),
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

    def winner_memory_rows(self, *, creator: str, campaign_slug: str | None = None) -> list[dict[str, Any]]:
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
                "visibleMetricFields": ["views", "reach", "followers", "likes", "comments", "shares", "saves"],
            },
            "metrics": metrics,
            "wouldWrite": False,
        }

    def winner_concept_name(self, row: dict[str, Any]) -> str:
        metadata = json_load(row.get("concept_metadata_json"), {})
        if isinstance(metadata, dict):
            for key in ("conceptName", "concept_name", "concept", "label", "name", "title"):
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
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
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
