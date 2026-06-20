from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .persistence import json_load, utc_now

OFM_AUDIO_CONTEXT_TAGS = {
    "ofm",
    "ofm_reels",
    "onlyfans",
    "onlyfans_ig_reels",
    "ig_reels",
    "instagram_reels",
    "tiktok",
    "creator_fit",
    "glam",
    "mirror",
    "fit_check",
    "thirst_trap",
    "lifestyle",
    "soft_glam",
}


class AudioRecommendationRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        new_id: Callable[[str], str],
        slugify: Callable[[str], str],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        graph_id_for: Callable[..., str],
        record_event: Callable[..., str],
        recommendation_item_row: Callable[[str], dict[str, Any]],
        reference_pattern_payload: Callable[[dict[str, Any]], dict[str, Any]],
        select_audio_for_recommendation: Callable[..., dict[str, Any]],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._new_id = new_id
        self._slugify = slugify
        self._campaign_by_slug = campaign_by_slug
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._graph_id_for = graph_id_for
        self._record_event = record_event
        self._recommendation_item_row = recommendation_item_row
        self._reference_pattern_payload = reference_pattern_payload
        self._select_audio_for_recommendation = select_audio_for_recommendation

    def import_audio_catalog(self, catalog_path: Path) -> dict[str, Any]:
        return self.import_audio_memory(catalog_path)

    def import_audio_memory(self, catalog_path: Path) -> dict[str, Any]:
        catalog_path = Path(catalog_path).expanduser().resolve()
        if not catalog_path.exists():
            raise FileNotFoundError(f"audio catalog not found: {catalog_path}")
        payload = json_load(catalog_path.read_text(encoding="utf-8"), {})
        items = payload.get("items") or payload.get("audio") or payload.get("recommendations")
        if not isinstance(items, list):
            raise ValueError("audio catalog export must contain an items array")
        now = utc_now()
        imported = 0
        snapshots_imported = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("audioTitle") or "").strip()
            platform = str(item.get("platform") or "").strip().lower()
            if not title or not platform:
                continue
            source_audio_id = (
                item.get("id")
                or item.get("catalogAudioId")
                or item.get("sourceAudioId")
                or item.get("nativeAudioId")
                or item.get("audioId")
                or hashlib.sha256(f"{platform}:{title}:{item.get('artistName') or item.get('artist_name') or item.get('artist') or ''}".encode("utf-8")).hexdigest()[:16]
            )
            native_audio_id = item.get("nativeAudioId") or item.get("audioId") or item.get("platformAudioId")
            row_id = str(source_audio_id or self._new_id("aud"))
            if native_audio_id:
                existing_audio = self.conn.execute(
                    "SELECT id, source_audio_id FROM audio_catalog WHERE platform = ? AND native_audio_id = ?",
                    (platform, native_audio_id),
                ).fetchone()
                if existing_audio:
                    row_id = existing_audio["id"]
                    source_audio_id = existing_audio["source_audio_id"] or source_audio_id
            review_reasons = item.get("reviewReasons") or []
            raw = dict(item)
            latest_snapshot = self.latest_audio_trend_snapshot_payload(item)
            trend_sources = item.get("trendSources") or item.get("sources") or []
            if isinstance(item.get("source"), str):
                trend_sources = [*trend_sources, item["source"]]
            self.conn.execute(
                """
                INSERT INTO audio_catalog (
                  id, source_audio_id, title, artist_name, platform, native_audio_id, native_audio_url,
                  mood_tags_json, best_content_types_json, account_fit_json, trend_status,
                  usage_count, bpm, energy, vocality, confidence, safe_usage_notes,
                  trend_score, velocity_score, fatigue_score, account_fit_score, creator_fit_score,
                  recommendation_confidence, performance_lift, source_confidence, trend_sources_json, resolved,
                  review_reasons_json, example_reels_json, performance_summary_json, fatigue_json,
                  raw_json, imported_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  source_audio_id = excluded.source_audio_id,
                  title = excluded.title,
                  artist_name = excluded.artist_name,
                  native_audio_id = excluded.native_audio_id,
                  native_audio_url = excluded.native_audio_url,
                  mood_tags_json = excluded.mood_tags_json,
                  best_content_types_json = excluded.best_content_types_json,
                  account_fit_json = excluded.account_fit_json,
                  trend_status = excluded.trend_status,
                  usage_count = excluded.usage_count,
                  bpm = excluded.bpm,
                  energy = excluded.energy,
                  vocality = excluded.vocality,
                  confidence = excluded.confidence,
                  safe_usage_notes = excluded.safe_usage_notes,
                  trend_score = excluded.trend_score,
                  velocity_score = excluded.velocity_score,
                  fatigue_score = excluded.fatigue_score,
                  account_fit_score = excluded.account_fit_score,
                  creator_fit_score = excluded.creator_fit_score,
                  recommendation_confidence = excluded.recommendation_confidence,
                  performance_lift = excluded.performance_lift,
                  source_confidence = excluded.source_confidence,
                  trend_sources_json = excluded.trend_sources_json,
                  resolved = excluded.resolved,
                  review_reasons_json = excluded.review_reasons_json,
                  example_reels_json = excluded.example_reels_json,
                  performance_summary_json = excluded.performance_summary_json,
                  fatigue_json = excluded.fatigue_json,
                  raw_json = excluded.raw_json,
                  updated_at = excluded.updated_at
                """,
                (
                    row_id,
                    source_audio_id,
                    title,
                    item.get("artistName") or item.get("artist_name") or item.get("artist"),
                    platform,
                    native_audio_id,
                    item.get("nativeAudioUrl") or item.get("platformUrl") or item.get("native_audio_url"),
                    json.dumps(item.get("moodTags") or item.get("vibeTags") or [], ensure_ascii=False),
                    json.dumps(item.get("bestContentTypes") or [], ensure_ascii=False),
                    json.dumps(item.get("accountFit") or [], ensure_ascii=False),
                    item.get("trendStatus") or item.get("freshness") or "unknown",
                    item.get("usageCount"),
                    item.get("bpm"),
                    item.get("energy"),
                    item.get("vocality"),
                    item.get("confidence"),
                    item.get("safeUsageNotes"),
                    item.get("trendScore"),
                    item.get("velocityScore") or latest_snapshot.get("velocityScore"),
                    item.get("fatigueScore"),
                    item.get("accountFitScore"),
                    item.get("creatorFitScore") or item.get("ofmFitScore"),
                    item.get("recommendationConfidence"),
                    item.get("performanceLift"),
                    item.get("sourceConfidence"),
                    json.dumps(sorted({str(source) for source in trend_sources if source}), ensure_ascii=False),
                    1 if item.get("resolved") is True or not review_reasons else 0,
                    json.dumps(review_reasons, ensure_ascii=False),
                    json.dumps(item.get("exampleReels") or [], ensure_ascii=False),
                    json.dumps(item.get("performanceSummary") or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(item.get("fatigue") or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(raw, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            audio_graph_id = self._ensure_graph_node(
                "audio_memory",
                local_table="audio_catalog",
                local_id=row_id,
                payload={
                    "platform": platform,
                    "nativeAudioId": native_audio_id,
                    "title": title,
                    "artistName": item.get("artistName") or item.get("artist_name") or item.get("artist"),
                },
            )
            for snapshot in item.get("trendSnapshots") or []:
                if not isinstance(snapshot, dict):
                    continue
                observed_at = str(snapshot.get("observedAt") or snapshot.get("observed_at") or now)
                snapshot_id = f"audtrend_{hashlib.sha256(f'{row_id}:{observed_at}'.encode('utf-8')).hexdigest()[:12]}"
                self.conn.execute(
                    """
                    INSERT INTO audio_trend_snapshots (
                      id, audio_catalog_id, platform, native_audio_id, observed_at,
                      trend_status, usage_count, saturation_score, velocity_score,
                      source, notes, raw_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(audio_catalog_id, observed_at) DO UPDATE SET
                      trend_status = excluded.trend_status,
                      usage_count = excluded.usage_count,
                      saturation_score = excluded.saturation_score,
                      velocity_score = excluded.velocity_score,
                      source = excluded.source,
                      notes = excluded.notes,
                      raw_json = excluded.raw_json
                    """,
                    (
                        snapshot_id,
                        row_id,
                        platform,
                        native_audio_id,
                        observed_at,
                        snapshot.get("trendStatus") or snapshot.get("trend_status") or item.get("trendStatus") or "unknown",
                        snapshot.get("usageCount") or snapshot.get("usage_count"),
                        snapshot.get("saturationScore") or snapshot.get("saturation_score"),
                        snapshot.get("velocityScore") or snapshot.get("velocity_score"),
                        snapshot.get("source"),
                        snapshot.get("notes"),
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                snapshot_graph_id = self._ensure_graph_node(
                    "audio_trend_snapshot",
                    local_table="audio_trend_snapshots",
                    local_id=snapshot_id,
                    payload={"audioCatalogId": row_id, "observedAt": observed_at},
                )
                self._ensure_graph_edge(audio_graph_id, snapshot_graph_id, "audio_memory_to_trend_snapshot")
                snapshots_imported += 1
            imported += 1
        self.conn.commit()
        self._record_event(
            "audio_memory_imported",
            status="success",
            message=f"Audio memory imported: {imported} tracks",
            metadata={"catalogPath": str(catalog_path), "tracks": imported, "trendSnapshots": snapshots_imported},
        )
        return {
            "schema": "campaign_factory.audio_memory_import.v1",
            "catalogPath": str(catalog_path),
            "tracksImported": imported,
            "trendSnapshotsImported": snapshots_imported,
        }

    def audio_catalog(self, platform: str | None = None, limit: int = 100) -> dict[str, Any]:
        params: list[Any] = []
        sql = "SELECT * FROM audio_catalog"
        if platform:
            sql += " WHERE platform = ?"
            params.append(platform.strip().lower())
        sql += " ORDER BY updated_at DESC, title LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        rows = self.conn.execute(sql, params).fetchall()
        return {"schema": "campaign_factory.audio_catalog.v1", "count": len(rows), "items": [self.audio_catalog_payload(dict(row)) for row in rows]}

    def audio_memory(self, platform: str | None = None, account: str | None = None, limit: int = 100) -> dict[str, Any]:
        requested_limit = max(1, min(int(limit), 1000))
        payload = self.audio_catalog(platform=platform, limit=max(requested_limit, min(1000, requested_limit * 10)))
        items = payload["items"]
        for item in items:
            item["performanceSummary"] = self.audio_performance_summary(item, account=account)
            item["fatigue"] = self.audio_fatigue_summary(item, account=account)
            score, reasons, components, confidence = self.score_audio_catalog_item_v2(
                item,
                set(OFM_AUDIO_CONTEXT_TAGS),
                {self.norm_tag(account)} if account else set(),
                account=account,
            )
            item["audioMemoryScore"] = score
            item["scoreComponents"] = components
            item["recommendationConfidence"] = item.get("recommendationConfidence") or confidence
            item["rationale"] = ", ".join(reasons)
        items.sort(key=lambda item: (float(item.get("audioMemoryScore") or 0), int(item.get("usageCount") or 0)), reverse=True)
        items = items[:requested_limit]
        return {
            "schema": "campaign_factory.audio_memory.v1",
            "platform": platform,
            "account": account,
            "count": len(items),
            "audioTrust": self.audio_memory_trust_summary(items),
            "items": items,
        }

    def recommend_audio(
        self,
        *,
        platform: str = "instagram",
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
        campaign_slug: str | None = None,
        recommendation_item_id: str | None = None,
        account: str | None = None,
        visual_signal: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        tags = {self.norm_tag(tag) for tag in (content_tags or []) if self.norm_tag(tag)}
        tags.update(OFM_AUDIO_CONTEXT_TAGS)
        accounts = {self.norm_tag(tag) for tag in (account_tags or []) if self.norm_tag(tag)}
        if account:
            accounts.add(self.norm_tag(account))
        campaign = self._campaign_by_slug(campaign_slug) if campaign_slug else None
        if recommendation_item_id:
            rec = self._recommendation_item_row(recommendation_item_id)
            if rec.get("target_account"):
                accounts.add(self.norm_tag(rec["target_account"]))
            if rec.get("reference_pattern_id"):
                ref = self.conn.execute("SELECT * FROM reference_patterns WHERE id = ?", (rec["reference_pattern_id"],)).fetchone()
                if ref:
                    pattern = self._reference_pattern_payload(dict(ref))
                    tags.update(self.norm_tag(tag) for tag in [pattern.get("visualFormat"), pattern.get("hookType"), pattern.get("captionArchetype")] if self.norm_tag(tag))
        platform_key = platform.strip().lower()
        if platform_key in {"instagram", "ig", "instagram_reels"}:
            candidates = [
                item for item in self.audio_catalog(platform=None, limit=1000)["items"]
                if item.get("platform") in {"instagram", "tiktok"}
            ]
        else:
            candidates = self.audio_catalog(platform=platform, limit=1000)["items"]
        scored = []
        use_contentforge_fit = bool(visual_signal) or os.environ.get("CAMPAIGN_FACTORY_AUDIO_FIT") == "1"
        for item in candidates:
            performance = self.audio_performance_summary(item, campaign_id=campaign["id"] if campaign else None, account=account)
            fatigue = self.audio_fatigue_summary(item, campaign_id=campaign["id"] if campaign else None, account=account)
            item = {**item, "performanceSummary": performance, "fatigue": fatigue}
            score, reasons, components, confidence = self.score_audio_catalog_item_v2(item, tags, accounts, account=account)
            audio_fit = self.contentforge_audio_fit_for_item(item, tags, visual_signal=visual_signal) if use_contentforge_fit else None
            if audio_fit:
                fit_score = audio_fit.get("audioFitScore")
                if isinstance(fit_score, (int, float)):
                    score += (float(fit_score) - 50.0) * 0.3
                    reasons.append(f"audio_fit:{round(float(fit_score))}")
                for warning in audio_fit.get("warnings") or []:
                    if isinstance(warning, dict) and warning.get("code"):
                        reasons.append(f"fit_warning:{warning['code']}")
            scored.append({
                **item,
                "requestedPlatform": platform_key,
                "matchScore": max(0, round(score, 3)),
                "audioMemoryScore": max(0, round(score, 3)),
                "scoreComponents": components,
                "recommendationConfidence": confidence,
                "rationale": ", ".join(reasons) or "platform match",
                "audioFit": audio_fit,
            })
        scored.sort(key=lambda item: (-float(item["matchScore"]), -(int(item.get("usageCount") or 0)), item["title"]))
        recommendations = [
            {**self.audio_catalog_recommendation(item), "selectionRank": index}
            for index, item in enumerate(scored[:max(1, limit)], start=1)
        ]
        for item in recommendations:
            decision_score, decision_reasons, risk_flags = self.audio_decision_score(item, requested_platform=platform_key)
            item["decisionScore"] = round(decision_score, 3)
            item["decisionReasons"] = decision_reasons
            item["riskFlags"] = risk_flags
            item["whenToUse"] = self.audio_when_to_use(item, risk_flags)
            item["whenNotToUse"] = self.audio_when_not_to_use(item, risk_flags)
        return {
            "schema": "campaign_factory.audio_recommendations.v1",
            "platform": platform,
            "campaign": campaign_slug,
            "recommendationItemId": recommendation_item_id,
            "contentTags": sorted(tags),
            "accountTags": sorted(accounts),
            "visualSignal": visual_signal if isinstance(visual_signal, dict) else None,
            "recommendations": recommendations,
            "decision": self.decide_audio_from_recommendations(
                recommendations,
                requested_platform=platform_key,
                content_tags=sorted(tags),
                account_tags=sorted(accounts),
            ),
        }

    def decide_audio(
        self,
        *,
        platform: str = "instagram",
        campaign_slug: str | None = None,
        recommendation_item_id: str | None = None,
        account: str | None = None,
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
        visual_signal: dict[str, Any] | None = None,
        limit: int = 5,
        select: bool = False,
        operator: str | None = None,
    ) -> dict[str, Any]:
        recommendations = self.recommend_audio(
            platform=platform,
            campaign_slug=campaign_slug,
            recommendation_item_id=recommendation_item_id,
            account=account,
            content_tags=content_tags or [],
            account_tags=account_tags or [],
            visual_signal=visual_signal,
            limit=limit,
        )
        decision = recommendations.get("decision") or {}
        selection = None
        primary = decision.get("primaryAudio") if isinstance(decision.get("primaryAudio"), dict) else None
        if select and recommendation_item_id and primary:
            audio_id = primary.get("catalogAudioId") or primary.get("catalog_audio_id") or primary.get("audioMemoryGraphId") or primary.get("platform_audio_id") or primary.get("audioId")
            if audio_id:
                selection = self._select_audio_for_recommendation(
                    recommendation_item_id,
                    str(audio_id),
                    operator=operator,
                    notes="Selected from Campaign Factory audio decision",
                )
        return {
            "schema": "campaign_factory.audio_decision.v1",
            "platform": platform,
            "campaign": campaign_slug,
            "recommendationItemId": recommendation_item_id,
            "decision": decision,
            "recommendations": recommendations.get("recommendations") or [],
            "selection": selection,
        }

    def decide_audio_from_recommendations(
        self,
        recommendations: list[dict[str, Any]],
        *,
        requested_platform: str = "instagram",
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        candidates = []
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            score, reasons, risks = self.audio_decision_score(item, requested_platform=requested_platform)
            enriched = {
                **item,
                "decisionScore": round(score, 3),
                "decisionReasons": reasons,
                "riskFlags": risks,
                "whenToUse": self.audio_when_to_use(item, risks),
                "whenNotToUse": self.audio_when_not_to_use(item, risks),
            }
            candidates.append(enriched)
        candidates.sort(key=lambda item: (-float(item.get("decisionScore") or 0), int(item.get("selectionRank") or 999999), str(item.get("audioTitle") or "")))
        do_not_use = [
            item for item in candidates
            if float(item.get("decisionScore") or 0) < 45
            or "stale_trend" in (item.get("riskFlags") or [])
            or "high_fatigue" in (item.get("riskFlags") or [])
        ]
        usable = [item for item in candidates if item not in do_not_use]
        primary = usable[0] if usable else (candidates[0] if candidates else None)
        backups = [item for item in usable if item is not primary][:2]
        confidence = self.audio_decision_confidence(primary)
        primary_risks = list((primary or {}).get("riskFlags") or [])
        return {
            "schema": "campaign_factory.audio_decision.v1",
            "primaryAudio": primary,
            "backupAudios": backups,
            "doNotUseAudios": do_not_use[:5],
            "decisionConfidence": confidence,
            "decisionReasons": list((primary or {}).get("decisionReasons") or []),
            "riskFlags": primary_risks,
            "whenToUse": (primary or {}).get("whenToUse"),
            "whenNotToUse": (primary or {}).get("whenNotToUse"),
            "operatorInstruction": self.audio_operator_instruction(primary),
            "contentTags": content_tags or [],
            "accountTags": account_tags or [],
        }

    def audio_decision_score(self, item: dict[str, Any], *, requested_platform: str) -> tuple[float, list[str], list[str]]:
        score = float(item.get("audioMemoryScore") or item.get("matchScore") or 0)
        reasons: list[str] = []
        risks: list[str] = []
        platform = str(item.get("platform") or "").strip().lower()
        title = str(item.get("audioTitle") or item.get("audio_title") or "")
        native_id = item.get("platform_audio_id") or item.get("audioId") or item.get("nativeAudioId")
        native_url = item.get("platform_url") or item.get("platformUrl") or item.get("nativeAudioUrl")
        if platform == "instagram" and (native_id or native_url):
            score += 18
            reasons.append("resolved_instagram_native_audio")
        elif requested_platform in {"instagram", "ig", "instagram_reels"} and platform == "tiktok":
            score -= 14
            risks.append("needs_ig_lookup")
            reasons.append("tiktok_cross_platform_trend_signal")
        if not (native_id or native_url):
            score -= 22
            risks.append("missing_native_locator")
        if self.is_generic_audio_title(title, platform):
            score -= 18
            risks.append("unresolved_or_generic_title")
        trend = self.norm_tag(item.get("trendStatus") or item.get("freshness") or "unknown")
        if trend in {"rising", "fresh", "trending", "current"}:
            score += 8
            reasons.append(f"trend:{trend}")
        elif trend in {"stale", "expired", "fading", "peaked"}:
            score -= 18
            risks.append("stale_trend")
        fatigue = item.get("fatigue") if isinstance(item.get("fatigue"), dict) else {}
        fatigue_level = self.norm_tag(fatigue.get("level") or "")
        if fatigue_level == "low":
            score += 6
            reasons.append("low_fatigue")
        elif fatigue_level in {"medium", "high"}:
            score -= 10 if fatigue_level == "medium" else 24
            risks.append(f"{fatigue_level}_fatigue")
        if item.get("performanceLift") is not None:
            try:
                lift = float(item.get("performanceLift") or 0)
                if lift > 0:
                    score += min(12, lift)
                    reasons.append("positive_audio_performance")
            except (TypeError, ValueError):
                pass
        account_fit = item.get("accountFitScore")
        if isinstance(account_fit, (int, float)) and account_fit >= 70:
            score += 7
            reasons.append("account_fit")
        creator_fit = item.get("creatorFitScore")
        if isinstance(creator_fit, (int, float)) and creator_fit >= 70:
            score += 7
            reasons.append("ofm_creator_fit")
        return max(0, min(100, score)), reasons or ["highest_ranked_audio_memory_match"], risks

    def audio_decision_confidence(self, primary: dict[str, Any] | None) -> str:
        if not primary:
            return "weak"
        score = float(primary.get("decisionScore") or 0)
        risks = set(primary.get("riskFlags") or [])
        if score >= 82 and not risks:
            return "strong"
        if score >= 68 and not (risks & {"missing_native_locator", "unresolved_or_generic_title", "high_fatigue"}):
            return "usable"
        if score >= 50:
            return "directional"
        return "weak"

    def audio_when_to_use(self, item: dict[str, Any], risks: list[str]) -> str:
        if "needs_ig_lookup" in risks:
            return "Use when the operator can find the matching native Instagram audio manually."
        return "Use as the default native audio for this content when the operator can attach the exact platform audio."

    def audio_when_not_to_use(self, item: dict[str, Any], risks: list[str]) -> str:
        if "high_fatigue" in risks:
            return "Avoid unless the account needs repetition more than novelty."
        if "stale_trend" in risks:
            return "Avoid for new reels unless this is intentionally nostalgic or account-proven."
        if "unresolved_or_generic_title" in risks:
            return "Do not publish until the operator resolves the exact native audio title/locator."
        return "Avoid if the native audio cannot be found or attached before publish."

    def audio_operator_instruction(self, primary: dict[str, Any] | None) -> str:
        if not primary:
            return "No audio decision available; operator must choose native audio manually."
        if "needs_ig_lookup" in (primary.get("riskFlags") or []):
            return f"Use this as a trend signal and find the closest matching native Instagram audio: {primary.get('audioTitle') or primary.get('audio_title')}"
        return f"Attach this native {primary.get('platform') or 'platform'} audio manually before publish: {primary.get('audioTitle') or primary.get('audio_title')}"

    def is_generic_audio_title(self, title: str, platform: str | None = None) -> bool:
        normalized = str(title or "").strip().lower()
        platform_norm = self.norm_tag(platform or "")
        if not normalized:
            return True
        if platform_norm == "tiktok":
            return bool(re.fullmatch(r"tiktok audio [0-9a-z_-]+", normalized))
        if platform_norm == "instagram":
            return bool(re.fullmatch(r"instagram audio [0-9a-z_-]+", normalized))
        return bool(re.fullmatch(r"(tiktok|instagram) audio [0-9a-z_-]+", normalized))

    def audio_catalog_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        raw = json_load(row["raw_json"], {})
        graph_id = self._graph_id_for(
            "audio_catalog",
            row["id"],
            entity_type="audio_memory",
            payload={"platform": row["platform"], "nativeAudioId": row["native_audio_id"], "title": row["title"]},
        )
        return {
            "id": row["id"],
            "audioMemoryGraphId": graph_id,
            "sourceAudioId": row["source_audio_id"],
            "title": row["title"],
            "artistName": row["artist_name"],
            "platform": row["platform"],
            "nativeAudioId": row["native_audio_id"],
            "nativeAudioUrl": row["native_audio_url"],
            "moodTags": json_load(row["mood_tags_json"], []),
            "bestContentTypes": json_load(row["best_content_types_json"], []),
            "accountFit": json_load(row["account_fit_json"], []),
            "trendStatus": row["trend_status"],
            "usageCount": row["usage_count"],
            "bpm": row["bpm"],
            "energy": row["energy"],
            "vocality": row["vocality"],
            "confidence": row["confidence"],
            "safeUsageNotes": row["safe_usage_notes"],
            "trendScore": row.get("trend_score"),
            "velocityScore": row.get("velocity_score"),
            "fatigueScore": row.get("fatigue_score"),
            "accountFitScore": row.get("account_fit_score"),
            "creatorFitScore": row.get("creator_fit_score"),
            "recommendationConfidence": row.get("recommendation_confidence"),
            "performanceLift": row.get("performance_lift"),
            "sourceConfidence": row.get("source_confidence"),
            "trendSources": json_load(row.get("trend_sources_json"), []),
            "resolved": bool(row.get("resolved")),
            "reviewReasons": json_load(row.get("review_reasons_json"), []),
            "exampleReels": json_load(row.get("example_reels_json"), raw.get("exampleReels") or []),
            "performanceSummary": json_load(row.get("performance_summary_json"), raw.get("performanceSummary") or {}),
            "fatigue": json_load(row.get("fatigue_json"), raw.get("fatigue") or {}),
            "trendSnapshots": raw.get("trendSnapshots") if isinstance(raw.get("trendSnapshots"), list) else [],
            "raw": raw,
            "importedAt": row["imported_at"],
            "updatedAt": row["updated_at"],
        }

    def audio_performance_summary(
        self,
        item: dict[str, Any],
        *,
        campaign_id: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        audio_key = self.audio_key(item)
        params: list[Any] = [audio_key]
        sql = "SELECT * FROM audio_performance_rollups WHERE audio_key = ?"
        if campaign_id:
            sql += " AND campaign_id = ?"
            params.append(campaign_id)
        if account:
            sql += " AND (account_id = ? OR instagram_account_id = ?)"
            params.extend([account, account])
        rows = [dict(row) for row in self.conn.execute(sql, params).fetchall()]
        if not rows:
            stored = item.get("performanceSummary") if isinstance(item.get("performanceSummary"), dict) else {}
            return {
                "sampleSize": int(stored.get("sampleSize") or 0),
                "postCount": int(stored.get("postCount") or 0),
                "avgScore": stored.get("avgScore"),
                "performanceLift": item.get("performanceLift") if item.get("performanceLift") is not None else stored.get("performanceLift"),
                "source": "catalog" if stored else "none",
            }
        post_count = sum(int(row.get("post_count") or 0) for row in rows)
        view_count = sum(int(row.get("view_count") or 0) for row in rows)
        save_count = sum(int(row.get("save_count") or 0) for row in rows)
        scores = [float(row["score"]) for row in rows if row.get("score") is not None]
        avg_score = round(sum(scores) / len(scores), 3) if scores else None
        lift = round(avg_score - 50.0, 3) if avg_score is not None else None
        return {
            "sampleSize": post_count,
            "postCount": post_count,
            "views": view_count,
            "saves": save_count,
            "avgScore": avg_score,
            "performanceLift": lift,
            "source": "performance_snapshots",
        }

    def audio_fatigue_summary(
        self,
        item: dict[str, Any],
        *,
        campaign_id: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        audio_key = self.audio_key(item)
        params: list[Any] = [audio_key]
        sql = "SELECT COALESCE(SUM(post_count), 0) AS post_count FROM audio_performance_rollups WHERE audio_key = ?"
        if campaign_id:
            sql += " AND campaign_id = ?"
            params.append(campaign_id)
        if account:
            sql += " AND (account_id = ? OR instagram_account_id = ?)"
            params.extend([account, account])
        row = self.conn.execute(sql, params).fetchone()
        post_count = int(row["post_count"] or 0) if row else 0
        stored = item.get("fatigue") if isinstance(item.get("fatigue"), dict) else {}
        level = stored.get("level") or ("high" if post_count >= 8 else "medium" if post_count >= 4 else "low")
        return {
            "level": level,
            "recentUses": post_count,
            "fatigueScore": item.get("fatigueScore") if item.get("fatigueScore") is not None else stored.get("fatigueScore"),
            "source": "performance_rollups" if post_count else "catalog",
        }

    def audio_key(self, item: dict[str, Any]) -> str:
        platform = str(item.get("platform") or "instagram").strip().lower()
        native_id = item.get("nativeAudioId") or item.get("audioId") or item.get("platformAudioId")
        if native_id:
            return f"{platform}:{native_id}"
        return f"{platform}:{self._slugify(str(item.get('title') or item.get('audioTitle') or 'unknown'))}:{self._slugify(str(item.get('artistName') or item.get('artist_name') or ''))}"

    def score_audio_catalog_item(self, item: dict[str, Any], tags: set[str], accounts: set[str]) -> tuple[float, list[str]]:
        score = 35.0
        reasons = []
        trend = self.norm_tag(item.get("trendStatus") or "unknown")
        if trend in {"rising", "fresh", "trending", "current"}:
            score += 25
            reasons.append(f"trend:{trend}")
        elif trend in {"peaked", "fading", "stale", "expired"}:
            score -= 20
            reasons.append(f"trend:{trend}")
        item_tags = {self.norm_tag(tag) for tag in (item.get("moodTags") or []) + (item.get("bestContentTypes") or [])}
        overlap = tags & item_tags
        if overlap:
            score += 15 * len(overlap)
            reasons.append(f"tag_match:{'/'.join(sorted(overlap))}")
        account_overlap = accounts & {self.norm_tag(tag) for tag in item.get("accountFit") or []}
        if account_overlap:
            score += 10 * len(account_overlap)
            reasons.append(f"account_match:{'/'.join(sorted(account_overlap))}")
        if item.get("nativeAudioId") or item.get("nativeAudioUrl"):
            score += 8
            reasons.append("native_locator")
        if item.get("usageCount"):
            score += min(12, int(item["usageCount"]) / 10000)
            reasons.append("usage_signal")
        return score, reasons

    def score_audio_catalog_item_v2(
        self,
        item: dict[str, Any],
        tags: set[str],
        accounts: set[str],
        *,
        account: str | None = None,
    ) -> tuple[float, list[str], dict[str, float], str]:
        trend_score = self.audio_trend_component(item)
        velocity_score = self.audio_velocity_component(item)
        performance_score = self.audio_performance_component(item)
        account_fit_score = self.audio_account_fit_component(item, accounts)
        creator_fit_score = self.audio_creator_fit_component(item, tags)
        fatigue_safety_score = self.audio_fatigue_safety_component(item)
        locator_score = 100.0 if item.get("nativeAudioId") or item.get("nativeAudioUrl") else 35.0
        components = {
            "trend": round(trend_score, 3),
            "velocity": round(velocity_score, 3),
            "performance": round(performance_score, 3),
            "accountFit": round(account_fit_score, 3),
            "creatorFit": round(creator_fit_score, 3),
            "fatigueSafety": round(fatigue_safety_score, 3),
            "nativeLocator": round(locator_score, 3),
        }
        score = (
            trend_score * 0.22
            + velocity_score * 0.18
            + performance_score * 0.18
            + account_fit_score * 0.14
            + creator_fit_score * 0.14
            + fatigue_safety_score * 0.10
            + locator_score * 0.04
        )
        source_confidence = item.get("sourceConfidence")
        if isinstance(source_confidence, (int, float)):
            score = score * (0.85 + min(1.0, max(0.0, float(source_confidence))) * 0.15)
        reasons = [
            f"trend:{round(trend_score)}",
            f"velocity:{round(velocity_score)}",
            f"creator_fit:{round(creator_fit_score)}",
            f"account_fit:{round(account_fit_score)}",
            f"fatigue_safety:{round(fatigue_safety_score)}",
        ]
        performance = item.get("performanceSummary") if isinstance(item.get("performanceSummary"), dict) else {}
        if performance.get("sampleSize"):
            reasons.append(f"proof_samples:{performance.get('sampleSize')}")
        if account:
            reasons.append(f"account:{account}")
        if item.get("platform") in {"instagram", "tiktok"}:
            reasons.append(f"source_platform:{item.get('platform')}")
        confidence = self.audio_recommendation_confidence(item, components)
        return round(max(0.0, min(100.0, score)), 3), reasons, components, confidence

    def audio_trend_component(self, item: dict[str, Any]) -> float:
        if isinstance(item.get("trendScore"), (int, float)):
            return max(0.0, min(100.0, float(item["trendScore"])))
        trend = self.norm_tag(item.get("trendStatus") or "unknown")
        base = {
            "rising": 92,
            "fresh": 88,
            "trending": 85,
            "current": 78,
            "unknown": 52,
            "peaked": 42,
            "fading": 28,
            "stale": 18,
            "expired": 8,
        }.get(trend, 50)
        usage = int(item.get("usageCount") or 0)
        if usage:
            base += min(8, math.log10(max(usage, 1)) * 1.5)
        return max(0.0, min(100.0, float(base)))

    def audio_velocity_component(self, item: dict[str, Any]) -> float:
        if isinstance(item.get("velocityScore"), (int, float)):
            value = float(item["velocityScore"])
            return max(0.0, min(100.0, value * 100 if value <= 1 else value))
        latest = self.latest_audio_trend_snapshot_payload(item)
        value = latest.get("velocityScore") or latest.get("velocity_score")
        if isinstance(value, (int, float)):
            return max(0.0, min(100.0, float(value) * 100 if float(value) <= 1 else float(value)))
        trend = self.norm_tag(item.get("trendStatus") or "unknown")
        return {"rising": 82.0, "fresh": 75.0, "trending": 68.0, "current": 58.0, "fading": 20.0}.get(trend, 45.0)

    def audio_performance_component(self, item: dict[str, Any]) -> float:
        performance = item.get("performanceSummary") if isinstance(item.get("performanceSummary"), dict) else {}
        if isinstance(performance.get("avgScore"), (int, float)):
            return max(0.0, min(100.0, float(performance["avgScore"])))
        lift = performance.get("performanceLift")
        if lift is None:
            lift = item.get("performanceLift")
        if isinstance(lift, (int, float)):
            return max(0.0, min(100.0, 50.0 + float(lift)))
        return 50.0

    def audio_account_fit_component(self, item: dict[str, Any], accounts: set[str]) -> float:
        if isinstance(item.get("accountFitScore"), (int, float)):
            return max(0.0, min(100.0, float(item["accountFitScore"])))
        account_fit = {self.norm_tag(tag) for tag in item.get("accountFit") or []}
        if accounts and accounts & account_fit:
            return 88.0
        if account_fit & OFM_AUDIO_CONTEXT_TAGS:
            return 70.0
        return 55.0 if not accounts else 45.0

    def audio_creator_fit_component(self, item: dict[str, Any], tags: set[str]) -> float:
        if isinstance(item.get("creatorFitScore"), (int, float)):
            return max(0.0, min(100.0, float(item["creatorFitScore"])))
        item_tags = {
            self.norm_tag(tag)
            for tag in (item.get("moodTags") or []) + (item.get("bestContentTypes") or []) + (item.get("accountFit") or [])
        }
        ofm_overlap = item_tags & OFM_AUDIO_CONTEXT_TAGS
        tag_overlap = item_tags & tags
        if ofm_overlap:
            return min(100.0, 72.0 + len(ofm_overlap) * 6.0)
        if tag_overlap:
            return min(90.0, 60.0 + len(tag_overlap) * 5.0)
        return 48.0

    def audio_fatigue_safety_component(self, item: dict[str, Any]) -> float:
        fatigue = item.get("fatigue") if isinstance(item.get("fatigue"), dict) else {}
        raw_score = item.get("fatigueScore") if item.get("fatigueScore") is not None else fatigue.get("fatigueScore")
        if isinstance(raw_score, (int, float)):
            value = float(raw_score)
            return max(0.0, min(100.0, 100.0 - (value * 100 if value <= 1 else value)))
        level = fatigue.get("level")
        if level == "high":
            return 18.0
        if level == "medium":
            return 48.0
        return 82.0

    def audio_recommendation_confidence(self, item: dict[str, Any], components: dict[str, float]) -> str:
        performance = item.get("performanceSummary") if isinstance(item.get("performanceSummary"), dict) else {}
        sample_size = int(performance.get("sampleSize") or performance.get("postCount") or 0)
        source_confidence = item.get("sourceConfidence")
        source_ok = not isinstance(source_confidence, (int, float)) or float(source_confidence) >= 0.65
        if sample_size >= 5 and min(components.get("creatorFit", 0), components.get("fatigueSafety", 0)) >= 60 and source_ok:
            return "strong"
        if sample_size >= 2 or (components.get("trend", 0) >= 70 and components.get("velocity", 0) >= 60 and components.get("creatorFit", 0) >= 60):
            return "usable"
        if components.get("trend", 0) >= 55 or components.get("creatorFit", 0) >= 55:
            return "directional"
        return "weak"

    def latest_audio_trend_snapshot_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        snapshots = item.get("trendSnapshots") if isinstance(item.get("trendSnapshots"), list) else []
        parsed = [snapshot for snapshot in snapshots if isinstance(snapshot, dict)]
        if not parsed:
            raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
            latest = raw.get("latestTrendSnapshot")
            return latest if isinstance(latest, dict) else {}
        return sorted(parsed, key=lambda snapshot: str(snapshot.get("observedAt") or snapshot.get("observed_at") or ""), reverse=True)[0]

    def audio_memory_trust_summary(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {"count": 0, "strong": 0, "usable": 0, "directional": 0, "weak": 0, "averageScore": None}
        counts = {level: 0 for level in ("strong", "usable", "directional", "weak")}
        scores = []
        for item in items:
            confidence = item.get("recommendationConfidence") or "weak"
            counts[confidence if confidence in counts else "weak"] += 1
            if item.get("audioMemoryScore") is not None:
                scores.append(float(item["audioMemoryScore"]))
        return {
            "count": len(items),
            **counts,
            "averageScore": round(sum(scores) / len(scores), 2) if scores else None,
        }

    def contentforge_audio_fit_for_item(self, item: dict[str, Any], tags: set[str], *, visual_signal: dict[str, Any] | None = None) -> dict[str, Any] | None:
        module_path = self.settings.contentforge_root / "lib" / "audio-fit.js"
        if not module_path.exists():
            return None
        payload = {
            "captionTags": sorted(tags),
            "hookTags": sorted(tags),
            "visual": visual_signal if isinstance(visual_signal, dict) else {},
            "audio": {
                "tags": (item.get("moodTags") or []) + (item.get("bestContentTypes") or []),
                "moods": item.get("moodTags") or [],
                "energy": item.get("energy"),
                "bpm": item.get("bpm"),
                "tone": (item.get("moodTags") or [None])[0],
                "trendSnapshot": {
                    "velocityScore": ((item.get("raw") or {}).get("latestTrendSnapshot") or {}).get("velocityScore"),
                    "saturationScore": ((item.get("raw") or {}).get("latestTrendSnapshot") or {}).get("saturationScore"),
                    "observedAt": ((item.get("raw") or {}).get("latestTrendSnapshot") or {}).get("observedAt"),
                } if isinstance(item.get("raw"), dict) else None,
            },
        }
        script = """
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const modulePath = process.argv[1];
const { scoreAudioFit } = await import(pathToFileURL(modulePath).href);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(scoreAudioFit(input)));
"""
        try:
            result = subprocess.run(
                ["node", "--input-type=module", "-e", script, str(module_path)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        parsed = json_load(result.stdout, None)
        return parsed if isinstance(parsed, dict) and parsed.get("available") else None

    def audio_catalog_recommendation(self, item: dict[str, Any]) -> dict[str, Any]:
        audio_fit = item.get("audioFit") if isinstance(item.get("audioFit"), dict) else None
        return {
            "source": "campaign_factory.audio_catalog",
            "catalogAudioId": item["id"],
            "audioMemoryGraphId": item.get("audioMemoryGraphId"),
            "platform": item["platform"],
            "audioId": item.get("nativeAudioId"),
            "platform_audio_id": item.get("nativeAudioId"),
            "audioTitle": item.get("title"),
            "audio_title": item.get("title"),
            "artistName": item.get("artistName"),
            "artist_name": item.get("artistName"),
            "platformUrl": item.get("nativeAudioUrl"),
            "platform_url": item.get("nativeAudioUrl"),
            "audioVibe": (item.get("moodTags") or [None])[0],
            "vibeTags": item.get("moodTags") or [],
            "vibe_tags": item.get("moodTags") or [],
            "bestContentTypes": item.get("bestContentTypes") or [],
            "accountFit": item.get("accountFit") or [],
            "freshness": item.get("trendStatus") or "unknown",
            "trendStatus": item.get("trendStatus") or "unknown",
            "usageCount": item.get("usageCount"),
            "bpm": item.get("bpm"),
            "energy": item.get("energy"),
            "vocality": item.get("vocality"),
            "confidence": min(1.0, float(item.get("matchScore") or 0) / 100.0),
            "recommendationConfidence": item.get("recommendationConfidence"),
            "rationale": item.get("rationale"),
            "audioMemoryScore": item.get("audioMemoryScore") or item.get("matchScore"),
            "scoreComponents": item.get("scoreComponents") or {},
            "audioFitScore": audio_fit.get("audioFitScore") if audio_fit else None,
            "audioFitReasons": audio_fit.get("reasons") if audio_fit else [],
            "audioFitWarnings": audio_fit.get("warnings") if audio_fit else [],
            "audioFitComponents": audio_fit.get("components") if audio_fit else {},
            "trendScore": item.get("trendScore"),
            "velocityScore": item.get("velocityScore"),
            "fatigueScore": (item.get("fatigue") or {}).get("fatigueScore") if isinstance(item.get("fatigue"), dict) else item.get("fatigueScore"),
            "accountFitScore": (item.get("scoreComponents") or {}).get("accountFit") if isinstance(item.get("scoreComponents"), dict) else item.get("accountFitScore"),
            "creatorFitScore": (item.get("scoreComponents") or {}).get("creatorFit") if isinstance(item.get("scoreComponents"), dict) else item.get("creatorFitScore"),
            "performanceLift": (item.get("performanceSummary") or {}).get("performanceLift") if isinstance(item.get("performanceSummary"), dict) else item.get("performanceLift"),
            "exampleReels": item.get("exampleReels") or [],
            "reviewReasons": item.get("reviewReasons") or [],
            "trendSources": item.get("trendSources") or [],
            "fatigue": item.get("fatigue") or {},
            "performanceSummary": item.get("performanceSummary") or {},
            "safeUsageNotes": item.get("safeUsageNotes"),
            "instruction": (
                f"Find and attach matching native Instagram audio for TikTok trend signal: {item.get('title')}"
                if item.get("requestedPlatform") in {"instagram", "ig", "instagram_reels"} and item.get("platform") == "tiktok"
                else f"Attach native {item.get('platform')} audio: {item.get('title')}"
            ),
        }

    def norm_tag(self, value: Any) -> str:
        return " ".join(str(value or "").strip().lower().replace("-", "_").split())
