from __future__ import annotations

import math
import sqlite3
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .persistence import json_load, utc_now
from .fileops import atomic_write_text


class TribeV2Repository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        slugify: Callable[[str], str],
        creator_label: Callable[[Any], str],
        normalize_content_surface: Callable[[str | None], str],
        creative_knowledge_rows: Callable[..., list[dict[str, Any]]],
        creative_knowledge_result: Callable[[dict[str, Any]], dict[str, Any]],
        image_exts: set[str],
        video_exts: set[str],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._slugify = slugify
        self._creator_label = creator_label
        self._normalize_content_surface = normalize_content_surface
        self._creative_knowledge_rows = creative_knowledge_rows
        self._creative_knowledge_result = creative_knowledge_result
        self._image_exts = image_exts
        self._video_exts = video_exts

    def tribev2_reel_analysis(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 20,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        rows = self.tribev2_reel_analysis_rows(
            creator=creator_label, campaign_slug=campaign_slug
        )
        minimum = max(1, int(minimum_sample_size or 1))
        insufficient = len(rows) < minimum
        metric_fields = ["views", "reach", "saves", "shares"]
        score_fields = ["meanAbsActivation", "peakAbsActivation", "stdActivation"]
        correlations = (
            {
                score_field: {
                    metric: self.pearson_correlation(
                        [float(row.get(score_field) or 0) for row in rows],
                        [float(row.get(metric) or 0) for row in rows],
                    )
                    for metric in metric_fields
                }
                for score_field in score_fields
            }
            if not insufficient
            else {
                score_field: {metric: None for metric in metric_fields}
                for score_field in score_fields
            }
        )
        ranked = sorted(
            rows, key=lambda row: float(row.get("meanAbsActivation") or 0), reverse=True
        )
        bucket_size = max(1, math.ceil(len(ranked) / 4)) if ranked else 0
        top_bucket = ranked[:bucket_size] if bucket_size else []
        bottom_bucket = ranked[-bucket_size:] if bucket_size else []
        top_summary = self.tribev2_bucket_summary(top_bucket)
        bottom_summary = self.tribev2_bucket_summary(bottom_bucket)
        lift = self.tribev2_bucket_lift(top_summary, bottom_summary)
        metric_quality = self.tribev2_metric_quality(rows, metric_fields)
        signal_summary = self.tribev2_signal_summary(
            correlations,
            sample_size=len(rows),
            metric_quality=metric_quality,
        )
        sample_adequate = len(rows) >= 20
        statistically_interesting = bool(
            sample_adequate
            and signal_summary["strongestAbsCorrelation"] >= 0.4
            and any(
                bool(signal_summary["correlatesWith"].get(metric))
                for metric in ["views", "reach", "saves", "shares"]
            )
        )
        recommended_role = (
            "creative_knowledge_feature"
            if statistically_interesting
            else "research_only"
        )
        return {
            "schema": "campaign_factory.tribev2_reel_analysis.v1",
            "creator": creator_label,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "modelId": "facebook/tribev2",
            "modelMode": "audio_video_cpu",
            "licenseStatus": "CC-BY-NC-4.0",
            "commercialUseAllowed": False,
            "researchUseAllowed": True,
            "licenseWarning": "CC-BY-NC-4.0 research/non-commercial only",
            "productionGate": False,
            "sampleSize": len(rows),
            "sampleSizeAdequate": sample_adequate,
            "minimumSampleSize": minimum,
            "insufficientData": insufficient,
            "reason": "not_enough_scored_published_reels" if insufficient else "",
            "scoreFields": score_fields,
            "metricFields": metric_fields,
            "metricQuality": metric_quality,
            "correlations": correlations,
            "meanAbsActivationCorrelation": correlations.get("meanAbsActivation") or {},
            "peakAbsActivationCorrelation": correlations.get("peakAbsActivation") or {},
            "stdActivationCorrelation": correlations.get("stdActivation") or {},
            "topTribeV2Quartile": top_summary,
            "bottomTribeV2Quartile": bottom_summary,
            "topQuartileLift": lift,
            "bottomQuartileLift": self.tribev2_bucket_lift(bottom_summary, top_summary),
            "topVsBottomLiftPct": lift,
            "strongestPredictiveSignal": signal_summary["strongestSignal"],
            "weakestPredictiveSignal": signal_summary["weakestSignal"],
            "strongestSignal": signal_summary["strongestSignal"],
            "weakestSignal": signal_summary["weakestSignal"],
            "correlatesWithViews": bool(signal_summary["correlatesWith"].get("views")),
            "correlatesWithReach": bool(signal_summary["correlatesWith"].get("reach")),
            "correlatesWithSaves": bool(signal_summary["correlatesWith"].get("saves")),
            "correlatesWithShares": bool(
                signal_summary["correlatesWith"].get("shares")
            ),
            "statisticallyInteresting": statistically_interesting,
            "confidenceLevel": self.tribev2_confidence_level(
                len(rows), statistically_interesting
            ),
            "recommendedRole": recommended_role,
            "futureUse": ["parent_reel_ranking", "variant_ranking", "creative_insights"]
            if recommended_role == "creative_knowledge_feature"
            else [],
            "shouldRemainAdvisoryOnly": True,
            "nextRecommendedExperiment": "score_20_to_50_published_reels_with_nonzero_metric_variance"
            if not sample_adequate
            else "hold_out_validate_against_future_25_account_pilot_metrics",
            "scoredReels": ranked[: max(0, int(limit or 0))],
            "interpretation": {
                "recommendedPipelineUse": "offline_research_sidecar",
                "doNotUseFor": [
                    "publishability",
                    "schedule_safe_gates",
                    "automatic_winner_selection",
                ],
                "nextValidationStep": "compare_against_larger_known_winner_and_loser_sets",
            },
            "wouldWrite": False,
        }

    def tribev2_reel_review(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        sort_by: str = "meanAbsActivation",
        bucket: str = "top",
        limit: int = 12,
        contact_sheet: bool = False,
        show_metrics: bool | None = None,
        show_tribe_score: bool = True,
        blind_mode: bool = False,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        if show_metrics is None:
            show_metrics = not blind_mode
        if blind_mode:
            show_tribe_score = True
        score_fields = {"meanAbsActivation", "peakAbsActivation", "stdActivation"}
        sort_field = sort_by if sort_by in score_fields else "meanAbsActivation"
        bucket_name = bucket if bucket in {"top", "bottom", "both"} else "top"
        rows = self.tribev2_reel_analysis_rows(
            creator=creator_label, campaign_slug=campaign_slug
        )
        ranked = sorted(
            rows, key=lambda row: float(row.get(sort_field) or 0), reverse=True
        )
        requested_limit = max(0, int(limit or 0))
        if bucket_name == "bottom":
            selected = (
                list(reversed(ranked[-requested_limit:])) if requested_limit else []
            )
        elif bucket_name == "both":
            selected = self.tribev2_review_both_bucket(ranked, requested_limit)
        else:
            selected = ranked[:requested_limit]
        items = [
            self.tribev2_review_item(
                row,
                rank=index,
                sort_field=sort_field,
                show_metrics=show_metrics,
                show_tribe_score=show_tribe_score,
            )
            for index, row in enumerate(selected, start=1)
        ]
        contact_sheet_path = (
            self.write_tribev2_review_contact_sheet(
                items,
                creator=creator_label,
                title="TRIBE v2 Review",
                blind_mode=blind_mode,
                show_metrics=show_metrics,
                show_tribe_score=show_tribe_score,
            )
            if contact_sheet
            else ""
        )
        return {
            "schema": "campaign_factory.tribev2_reel_review.v1",
            "creator": creator_label,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "modelId": "facebook/tribev2",
            "modelMode": "audio_video_cpu",
            "licenseStatus": "CC-BY-NC-4.0",
            "commercialUseAllowed": False,
            "researchUseAllowed": True,
            "sortBy": sort_field,
            "bucket": bucket_name,
            "blindMode": bool(blind_mode),
            "showMetrics": bool(show_metrics),
            "showTribeScore": bool(show_tribe_score),
            "reelsReviewed": len(rows),
            "items": items,
            "contactSheetPath": contact_sheet_path,
            "productionGate": False,
            "advisoryOnly": True,
            "wouldWriteProductionState": False,
            "wouldWrite": False,
        }

    def tribev2_review_both_bucket(
        self, ranked: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in ranked[:limit] + list(reversed(ranked[-limit:])):
            key = (
                row.get("renderedAssetId")
                or row.get("contentHash")
                or row.get("postId")
                or str(len(seen))
            )
            if key in seen:
                continue
            seen.add(key)
            selected.append(row)
        return selected

    def tribev2_review_item(
        self,
        row: dict[str, Any],
        *,
        rank: int,
        sort_field: str,
        show_metrics: bool = True,
        show_tribe_score: bool = True,
    ) -> dict[str, Any]:
        preview_path = self.tribev2_preview_path(row)
        tribe_score = {
            "meanAbsActivation": float(row.get("meanAbsActivation") or 0),
            "peakAbsActivation": float(row.get("peakAbsActivation") or 0),
            "stdActivation": float(row.get("stdActivation") or 0),
            "sortField": sort_field,
            "sortValue": float(row.get(sort_field) or 0),
        }
        actual_metrics = {
            "views": int(row.get("views") or 0),
            "reach": int(row.get("reach") or 0),
            "saves": int(row.get("saves") or 0),
            "shares": int(row.get("shares") or 0),
        }
        return {
            "rank": rank,
            "renderedAssetId": row.get("renderedAssetId") or "",
            "postId": row.get("postId") or "",
            "previewPath": preview_path,
            "previewAvailable": bool(preview_path and Path(preview_path).exists()),
            "contentHash": row.get("contentHash") or "",
            "publishedAt": row.get("publishedAt") or "",
            "conceptId": row.get("conceptId") or "",
            "captionAngle": row.get("captionAngle") or "",
            "audioId": row.get("audioId") or "",
            "tribeScore": tribe_score if show_tribe_score else {},
            "tribeScoreHidden": not show_tribe_score,
            "actualMetrics": actual_metrics if show_metrics else {},
            "actualMetricsHidden": not show_metrics,
            "licenseStatus": "CC-BY-NC-4.0",
            "productionGate": False,
            "advisoryOnly": True,
        }

    def tribev2_holdout_pilot_review(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        limit: int = 20,
        contact_sheet: bool = False,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        rows = self.tribev2_reel_analysis_rows(
            creator=creator_label, campaign_slug=campaign_slug
        )
        ranked = sorted(
            rows, key=lambda row: float(row.get("meanAbsActivation") or 0), reverse=True
        )
        bucket_rows = self.tribev2_holdout_bucket_rows(ranked)
        bucket_limit = max(0, int(limit or 0))
        buckets = {
            name: self.tribev2_holdout_bucket_summary(
                name, rows_for_bucket, limit=bucket_limit
            )
            for name, rows_for_bucket in bucket_rows.items()
        }
        contact_sheet_path = (
            self.write_tribev2_holdout_contact_sheet(buckets, creator=creator_label)
            if contact_sheet
            else ""
        )
        return {
            "schema": "campaign_factory.tribev2_holdout_pilot_review.v1",
            "creator": creator_label,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "modelId": "facebook/tribev2",
            "modelMode": "audio_video_cpu",
            "licenseStatus": "CC-BY-NC-4.0",
            "commercialUseAllowed": False,
            "researchUseAllowed": True,
            "bucketStrategy": "top_middle_bottom_20pct",
            "reelsReviewed": len(rows),
            "buckets": buckets,
            "contactSheetPath": contact_sheet_path,
            "productionGate": False,
            "advisoryOnly": True,
            "wouldWriteProductionState": False,
            "wouldWrite": False,
        }

    def tribev2_holdout_bucket_rows(
        self, ranked: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        count = len(ranked)
        if count == 0:
            return {"top20": [], "middle20": [], "bottom20": []}
        bucket_size = max(1, math.ceil(count * 0.2))
        middle_start = max(0, (count - bucket_size) // 2)
        return {
            "top20": ranked[:bucket_size],
            "middle20": ranked[middle_start : middle_start + bucket_size],
            "bottom20": list(reversed(ranked[-bucket_size:])),
        }

    def tribev2_holdout_bucket_summary(
        self, name: str, rows: list[dict[str, Any]], *, limit: int
    ) -> dict[str, Any]:
        selected = rows[:limit] if limit else rows
        items = [
            self.tribev2_review_item(row, rank=index, sort_field="meanAbsActivation")
            for index, row in enumerate(selected, start=1)
        ]
        return {
            "bucket": name,
            "sampleSize": len(rows),
            "items": items,
            "avgMetrics": self.tribev2_average_metrics(rows),
            "avgTribeScore": self.tribev2_average_scores(rows),
            "postIds": [row.get("postId") for row in rows if row.get("postId")],
        }

    def tribev2_average_metrics(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        return {
            "views": self.average_row_field(rows, "views"),
            "reach": self.average_row_field(rows, "reach"),
            "saves": self.average_row_field(rows, "saves"),
            "shares": self.average_row_field(rows, "shares"),
        }

    def tribev2_average_scores(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        return {
            "meanAbsActivation": self.average_row_field(rows, "meanAbsActivation"),
            "peakAbsActivation": self.average_row_field(rows, "peakAbsActivation"),
            "stdActivation": self.average_row_field(rows, "stdActivation"),
        }

    def average_row_field(self, rows: list[dict[str, Any]], field: str) -> float:
        return (
            round(sum(float(row.get(field) or 0) for row in rows) / len(rows), 4)
            if rows
            else 0.0
        )

    def tribev2_preview_path(self, row: dict[str, Any]) -> str:
        rendered_asset_id = row.get("renderedAssetId") or ""
        content_hash = row.get("contentHash") or ""
        clauses = []
        params: list[Any] = []
        if rendered_asset_id:
            clauses.append("id = ?")
            params.append(rendered_asset_id)
        if content_hash:
            clauses.append("content_hash = ?")
            params.append(content_hash)
        if not clauses:
            return ""
        asset = self.conn.execute(
            f"""
            SELECT campaign_path, output_path
            FROM rendered_assets
            WHERE {" OR ".join(clauses)}
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if not asset:
            return ""
        return str(asset["campaign_path"] or asset["output_path"] or "")

    def write_tribev2_review_contact_sheet(
        self,
        items: list[dict[str, Any]],
        *,
        creator: str,
        title: str = "TRIBE v2 Review",
        blind_mode: bool = False,
        show_metrics: bool = True,
        show_tribe_score: bool = True,
    ) -> str:
        root = Path(self.settings.campaigns_dir).parent / "tmp" / "tribev2_review"
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        html_path = (
            root / f"{self._slugify(creator)}_{self._slugify(title)}_{stamp}.html"
        )
        cards = self.tribev2_contact_sheet_cards(
            items, root, show_metrics=show_metrics, show_tribe_score=show_tribe_score
        )
        banner = (
            "<p><strong>Blind TRIBE review: metrics hidden.</strong></p>"
            if blind_mode
            else ""
        )
        html = self.tribev2_contact_sheet_html(
            title=f"{title}: {creator}",
            body=f"{banner}<section class='grid'>{''.join(cards)}</section>",
        )
        atomic_write_text(html_path, html, encoding="utf-8")
        return str(html_path)

    def write_tribev2_holdout_contact_sheet(
        self, buckets: dict[str, Any], *, creator: str
    ) -> str:
        root = Path(self.settings.campaigns_dir).parent / "tmp" / "tribev2_review"
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        html_path = (
            root / f"{self._slugify(creator)}_tribev2_holdout_pilot_review_{stamp}.html"
        )
        sections = []
        for name in ["top20", "middle20", "bottom20"]:
            bucket = buckets.get(name) or {}
            metrics = bucket.get("avgMetrics") or {}
            score = bucket.get("avgTribeScore") or {}
            cards = self.tribev2_contact_sheet_cards(
                bucket.get("items") or [],
                root,
                show_metrics=True,
                show_tribe_score=True,
            )
            sections.append(
                f"<h2>{name}</h2>"
                f"<p>sample={bucket.get('sampleSize', 0)} "
                f"mean={float(score.get('meanAbsActivation') or 0):.4f} "
                f"views={float(metrics.get('views') or 0):.1f} "
                f"reach={float(metrics.get('reach') or 0):.1f} "
                f"saves={float(metrics.get('saves') or 0):.1f} "
                f"shares={float(metrics.get('shares') or 0):.1f}</p>"
                f"<section class='grid'>{''.join(cards)}</section>"
            )
        html = self.tribev2_contact_sheet_html(
            title=f"TRIBE v2 Holdout Pilot Review: {creator}",
            body="".join(sections),
        )
        atomic_write_text(html_path, html, encoding="utf-8")
        return str(html_path)

    def tribev2_contact_sheet_cards(
        self,
        items: list[dict[str, Any]],
        root: Path,
        *,
        show_metrics: bool,
        show_tribe_score: bool,
    ) -> list[str]:
        cards = []
        for item in items:
            preview_path = item.get("previewPath") or ""
            thumb_path = self.tribev2_extract_thumbnail(preview_path, root, item)
            media_src = thumb_path or preview_path
            media_html = (
                f'<img src="{Path(media_src).as_uri()}" alt="rank {item["rank"]}">'
                if media_src and Path(media_src).exists()
                else "<div class='missing'>preview missing</div>"
            )
            tribe = item.get("tribeScore") or {}
            metrics = item.get("actualMetrics") or {}
            tribe_html = (
                f"<p>mean={float(tribe.get('meanAbsActivation') or 0):.6f} "
                f"peak={float(tribe.get('peakAbsActivation') or 0):.6f} "
                f"std={float(tribe.get('stdActivation') or 0):.6f}</p>"
                if show_tribe_score
                else "<p>TRIBE score hidden</p>"
            )
            metrics_html = (
                f"<p>views={int(metrics.get('views') or 0)} reach={int(metrics.get('reach') or 0)} "
                f"saves={int(metrics.get('saves') or 0)} shares={int(metrics.get('shares') or 0)}</p>"
                if show_metrics
                else "<p>Instagram metrics hidden</p>"
            )
            cards.append(
                "<article>"
                f"<h2>#{item['rank']} {item.get('renderedAssetId', '')}</h2>"
                f"{media_html}"
                f"{tribe_html}"
                f"{metrics_html}"
                f"<p><code>{preview_path}</code></p>"
                "</article>"
            )
        return cards

    def tribev2_contact_sheet_html(self, *, title: str, body: str) -> str:
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:24px;background:#111;color:#eee}"
            ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}"
            "article{background:#1d1d1f;border:1px solid #333;border-radius:8px;padding:12px}"
            "img{width:100%;aspect-ratio:9/16;object-fit:cover;background:#000;border-radius:4px}"
            "h1,h2,p{margin:0 0 8px}code{font-size:11px;word-break:break-all;color:#aaa}.missing{height:320px;display:grid;place-items:center;background:#222;color:#888}</style>"
            "</head><body>"
            f"<h1>{title}</h1>"
            "<p>Advisory-only offline review. Not used for scheduling, publishing, or gates.</p>"
            f"{body}"
            "</body></html>"
        )

    def tribev2_extract_thumbnail(
        self, preview_path: str, output_dir: Path, item: dict[str, Any]
    ) -> str:
        if not preview_path:
            return ""
        source = Path(preview_path)
        if not source.exists():
            return ""
        if source.suffix.lower() in self._image_exts:
            return str(source)
        if source.suffix.lower() not in self._video_exts:
            return ""
        thumb = (
            output_dir
            / f"{self._slugify(item.get('renderedAssetId') or str(item.get('rank')))}.jpg"
        )
        if thumb.exists():
            return str(thumb)
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    "00:00:00.5",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(thumb),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return ""
        return str(thumb) if thumb.exists() else ""

    def tribev2_reel_analysis_rows(
        self, *, creator: str, campaign_slug: str | None = None
    ) -> list[dict[str, Any]]:
        rows = []
        for row in self._creative_knowledge_rows(
            creator=creator, campaign_slug=campaign_slug
        ):
            if self._normalize_content_surface(row.get("content_surface")) != "reel":
                continue
            score = self.tribev2_score_for_snapshot(row)
            if not score:
                continue
            result = self._creative_knowledge_result(row)
            metrics = (
                result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
            )
            rows.append(
                {
                    "renderedAssetId": row.get("rendered_asset_id") or "",
                    "postId": row.get("post_id") or "",
                    "contentHash": row.get("content_hash") or "",
                    "conceptId": result.get("conceptId") or "",
                    "captionAngle": result.get("captionAngle") or "",
                    "audioId": result.get("audioId") or "",
                    "publishedAt": result.get("publishedAt") or "",
                    "views": int(metrics.get("views") or 0),
                    "reach": int(metrics.get("reach") or 0),
                    "saves": int(metrics.get("saves") or 0),
                    "shares": int(metrics.get("shares") or 0),
                    "tribev2ScoreId": score.get("id") or "",
                    "modelId": score.get("model_id") or "facebook/tribev2",
                    "modelMode": score.get("model_mode") or "",
                    "meanAbsActivation": round(
                        float(score.get("mean_abs_activation") or 0), 6
                    ),
                    "peakAbsActivation": round(
                        float(score.get("peak_abs_activation") or 0), 6
                    ),
                    "stdActivation": round(float(score.get("std_activation") or 0), 6),
                    "segmentsCount": int(score.get("segments_count") or 0),
                    "predsShape": json_load(score.get("preds_shape_json"), []),
                }
            )
        return rows

    def tribev2_score_for_snapshot(self, row: dict[str, Any]) -> dict[str, Any] | None:
        rendered_asset_id = row.get("rendered_asset_id") or ""
        content_hash = row.get("content_hash") or ""
        campaign_id = row.get("campaign_id") or ""
        clauses = []
        params: list[Any] = []
        if rendered_asset_id:
            clauses.append("rendered_asset_id = ?")
            params.append(rendered_asset_id)
        if content_hash:
            clauses.append("content_hash = ?")
            params.append(content_hash)
        if not clauses:
            return None
        campaign_clause = "AND campaign_id = ?" if campaign_id else ""
        if campaign_id:
            params.append(campaign_id)
        score = self.conn.execute(
            f"""
            SELECT * FROM tribev2_reel_scores
            WHERE ({" OR ".join(clauses)}) {campaign_clause}
            ORDER BY created_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        return dict(score) if score else None

    def pearson_correlation(self, xs: list[float], ys: list[float]) -> float | None:
        if len(xs) < 2 or len(xs) != len(ys):
            return None
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
        denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
        if denom_x == 0 or denom_y == 0:
            return None
        return round(numerator / (denom_x * denom_y), 4)

    def tribev2_bucket_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(rows)

        def avg(field: str) -> float:
            return (
                round(sum(float(row.get(field) or 0) for row in rows) / count, 2)
                if count
                else 0
            )

        return {
            "sampleSize": count,
            "avgMeanAbsActivation": avg("meanAbsActivation"),
            "avgPeakAbsActivation": avg("peakAbsActivation"),
            "avgViews": avg("views"),
            "avgReach": avg("reach"),
            "avgSaves": avg("saves"),
            "avgShares": avg("shares"),
            "postIds": [row.get("postId") for row in rows if row.get("postId")],
        }

    def tribev2_bucket_lift(
        self, top: dict[str, Any], bottom: dict[str, Any]
    ) -> dict[str, Any]:
        lift: dict[str, Any] = {}
        for field in ["avgViews", "avgReach", "avgSaves", "avgShares"]:
            base = float(bottom.get(field) or 0)
            observed = float(top.get(field) or 0)
            lift[field] = (
                round(((observed - base) / base * 100.0), 2)
                if base
                else (100.0 if observed else 0.0)
            )
        return lift

    def tribev2_metric_quality(
        self, rows: list[dict[str, Any]], metric_fields: list[str]
    ) -> dict[str, Any]:
        quality: dict[str, Any] = {}
        for metric in metric_fields:
            values = [float(row.get(metric) or 0) for row in rows]
            nonzero = sum(1 for value in values if value > 0)
            unique_values = len(set(values))
            quality[metric] = {
                "nonzeroCount": nonzero,
                "uniqueValues": unique_values,
                "usableForCorrelation": len(values) >= 20
                and nonzero >= 5
                and unique_values >= 5,
            }
        return quality

    def tribev2_signal_summary(
        self,
        correlations: dict[str, dict[str, float | None]],
        *,
        sample_size: int,
        metric_quality: dict[str, Any],
    ) -> dict[str, Any]:
        pairs: list[tuple[str, str, float]] = []
        for signal, metrics in correlations.items():
            for metric, value in metrics.items():
                if value is None:
                    continue
                pairs.append((signal, metric, float(value)))
        if not pairs:
            return {
                "strongestSignal": "",
                "weakestSignal": "",
                "strongestAbsCorrelation": 0.0,
                "correlatesWith": {
                    "views": False,
                    "reach": False,
                    "saves": False,
                    "shares": False,
                },
            }
        strongest = max(pairs, key=lambda item: abs(item[2]))
        weakest = min(pairs, key=lambda item: abs(item[2]))
        threshold = 0.4 if sample_size >= 20 else 0.7
        correlates_with = {
            metric: bool(metric_quality.get(metric, {}).get("usableForCorrelation"))
            and any(
                item_metric == metric and abs(value) >= threshold
                for _, item_metric, value in pairs
            )
            for metric in ["views", "reach", "saves", "shares"]
        }
        return {
            "strongestSignal": f"{strongest[0]}:{strongest[1]}",
            "weakestSignal": f"{weakest[0]}:{weakest[1]}",
            "strongestAbsCorrelation": round(abs(strongest[2]), 4),
            "correlatesWith": correlates_with,
        }

    def tribev2_confidence_level(
        self, sample_size: int, statistically_interesting: bool
    ) -> str:
        if sample_size < 20:
            return "low"
        if sample_size < 50:
            return "medium" if statistically_interesting else "low"
        return "high" if statistically_interesting else "medium"
