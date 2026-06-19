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
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._creator_label = creator_label
        self._build_creative_knowledge_base = build_creative_knowledge_base

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
