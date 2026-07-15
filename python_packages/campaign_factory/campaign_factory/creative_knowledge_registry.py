from __future__ import annotations

from datetime import datetime
from typing import Any

from campaign_factory.learning_score import (
    learning_eligible_sql,
    learning_loop_cutover_iso,
)

from .caption_outcome import load_context_json
from .persistence import json_load, utc_now


class CreativeKnowledgeRegistryMixin:
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
        cutover_iso = learning_loop_cutover_iso()
        if cutover_iso is None:
            return []
        clauses = [learning_eligible_sql(prefix="p.")]
        params: list[Any] = [cutover_iso]
        if campaign_slug:
            campaign = self._campaign_by_slug(campaign_slug)
            clauses.append("p.campaign_id = ?")
            params.append(campaign["id"])
        clauses.append(
            "\n            (\n              LOWER(COALESCE(p.creator_mix, '')) = LOWER(?)\n              OR LOWER(COALESCE(p.creator_model, '')) = LOWER(?)\n              OR LOWER(COALESCE(c.creator, '')) = LOWER(?)\n              OR LOWER(COALESCE(m.name, '')) = LOWER(?)\n              OR LOWER(COALESCE(m.slug, '')) = LOWER(?)\n            )\n            "
        )
        params.extend([creator, creator, creator, creator, self._slugify(creator)])
        rows = self.conn.execute(
            f"\n            SELECT p.*, campaigns.slug AS campaign_slug, campaigns.platform AS campaign_platform,\n                   c.metadata_json AS concept_metadata_json, c.creator AS concept_creator,\n                   c.parent_asset_id AS concept_parent_asset_id,\n                   a.handle AS account_username, a.external_id AS account_external_id,\n                   m.slug AS model_slug, m.name AS model_name\n            FROM performance_snapshots p\n            JOIN campaigns ON campaigns.id = p.campaign_id\n            LEFT JOIN concepts c ON c.id = p.concept_id\n            LEFT JOIN accounts a ON a.id = p.account_id OR a.external_id = p.instagram_account_id\n            LEFT JOIN models m ON m.id = a.model_id\n            WHERE {' AND '.join(clauses)}\n            ORDER BY p.snapshot_at DESC, p.created_at DESC\n            ",
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
            (float(metrics.get(key) or 0) * weight for key, weight in weights.items())
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
                name: value / sample_size if sample_size else 0
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
        self, row: dict[str, Any], *, min_views: int, min_reach: int, min_followers: int
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
