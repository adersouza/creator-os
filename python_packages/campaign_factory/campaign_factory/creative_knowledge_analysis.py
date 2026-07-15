from __future__ import annotations

from typing import Any

from .persistence import utc_now


class CreativeKnowledgeAnalysisMixin:
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
        self, *, creator: str, campaign_slug: str | None = None, limit: int = 20
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
        self, *, creator: str, campaign_slug: str | None = None, limit: int = 20
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
        averages = {key: value / count if count else 0 for key, value in totals.items()}
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
            (score - base_score) / base_score * 100.0
            if base_score > 0
            else 100.0
            if score > 0
            else 0.0
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
                and (item.get("key") == "snapchat_promo")
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
