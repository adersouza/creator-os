from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text
from .persistence import json_load


class ArchiveQualityRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        utc_now: Callable[[], str],
        sha256_file: Callable[[Any], str],
        probe_video_metadata: Callable[[Path], dict[str, Any]],
        upsert_model: Callable[..., dict[str, Any]],
        upsert_campaign: Callable[..., dict[str, Any]],
        campaign_dirs: Callable[[str, str], dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._utc_now = utc_now
        self._sha256_file = sha256_file
        self._probe_video_metadata = probe_video_metadata
        self.upsert_model = upsert_model
        self.upsert_campaign = upsert_campaign
        self.campaign_dirs = campaign_dirs
        self.record_event = record_event

    def archive_inventory_report(
        self,
        *,
        folder: Path,
        campaign_slug: str,
        creator: str = "Stacey",
        requested_count: int = 25,
        model_slug: str | None = None,
        recent_days: int = 30,
    ) -> dict[str, Any]:
        archive = Path(folder).expanduser().resolve()
        if not archive.exists() or not archive.is_dir():
            raise FileNotFoundError(f"archive folder not found: {archive}")
        if requested_count <= 0:
            raise ValueError("requested_count must be positive")

        creator_slug = self._slugify(creator)
        model_slug_value = model_slug or creator_slug
        model = self.upsert_model(model_slug_value, creator)
        campaign = self.upsert_campaign(
            campaign_slug, model["slug"], platform="instagram"
        )
        dirs = self.campaign_dirs(model["slug"], campaign["slug"])
        report_dir = dirs["root"] / "06_reports" / "archive_inventory"
        report_dir.mkdir(parents=True, exist_ok=True)

        video_paths = sorted(
            path
            for path in archive.iterdir()
            if path.is_file() and path.suffix.lower() == ".mp4"
        )
        seen_source_fingerprints: set[str] = set()
        items: list[dict[str, Any]] = []
        duplicate_source_fingerprint = 0
        duplicate_content_hash = 0
        duplicate_recent_publish = 0
        corrupted_or_invalid = 0
        clean_stacey_candidates = 0
        audio_present_count = 0
        audio_missing_count = 0

        recent_cutoff = datetime.now(UTC) - timedelta(days=recent_days)
        for index, path in enumerate(video_paths, start=1):
            digest = self._sha256_file(path)
            probe = self._probe_video_metadata(path)
            blocking_reasons: list[str] = []
            warnings: list[str] = []

            if digest in seen_source_fingerprints:
                blocking_reasons.append("duplicate_source_fingerprint")
                duplicate_source_fingerprint += 1
            else:
                seen_source_fingerprints.add(digest)

            existing_duplicate = self.archive_existing_content_duplicate(digest)
            if existing_duplicate:
                blocking_reasons.append("duplicate_existing_campaign_asset")
                duplicate_content_hash += 1

            recent_duplicate = self.archive_recent_publish_duplicate(
                digest, recent_cutoff
            )
            if recent_duplicate:
                blocking_reasons.append("duplicate_recent_publish")
                duplicate_recent_publish += 1

            if not probe.get("ok"):
                blocking_reasons.append(str(probe.get("error") or "probe_failed"))
                corrupted_or_invalid += 1
            elif (
                not isinstance(probe.get("durationSeconds"), (int, float))
                or float(probe.get("durationSeconds") or 0) <= 0
            ):
                blocking_reasons.append("invalid_duration")
                corrupted_or_invalid += 1

            audio_present = bool(probe.get("audioPresent"))
            if audio_present:
                audio_present_count += 1
                audio_status = "present"
            else:
                audio_missing_count += 1
                audio_status = "missing_needs_campaign_audio"

            aspect = probe.get("effectiveAspectRatio")
            if (
                isinstance(aspect, (int, float))
                and aspect > 0
                and (aspect < 0.35 or aspect > 0.9)
            ):
                warnings.append("source_aspect_ratio_needs_reels_render")

            creator_match = {
                "required": True,
                "creator": creator,
                "decision": "operator_source_required",
                "reason": "Archive folder is treated as operator-supplied Stacey inventory until source review approves candidates.",
            }

            status = "blocked" if blocking_reasons else "clean_source_candidate"
            if status == "clean_source_candidate":
                clean_stacey_candidates += 1

            items.append(
                {
                    "index": index,
                    "filename": path.name,
                    "sourcePath": str(path),
                    "sourceFingerprint": digest,
                    "contentHash": digest,
                    "status": status,
                    "blockingReasons": blocking_reasons,
                    "warnings": warnings,
                    "creatorMatch": creator_match,
                    "audioStatus": audio_status,
                    "audioPresent": audio_present,
                    "probe": probe,
                    "duplicate": {
                        "sourceFingerprint": "duplicate"
                        if "duplicate_source_fingerprint" in blocking_reasons
                        else "clear",
                        "existingCampaignAsset": existing_duplicate,
                        "recentPublish": recent_duplicate,
                    },
                }
            )

        status = (
            "ready_for_source_approval"
            if clean_stacey_candidates >= requested_count
            else "blocked"
        )
        blocking_reason = (
            None
            if status == "ready_for_source_approval"
            else "insufficient_clean_archive_inventory"
        )
        now = self._utc_now()
        result = {
            "schema": "campaign_factory.archive_inventory_report.v1",
            "campaign": campaign["slug"],
            "campaignId": campaign["id"],
            "creator": creator,
            "creatorMatchRequired": True,
            "archiveFolder": str(archive),
            "generatedAt": now,
            "requestedCount": requested_count,
            "archiveVideosFound": len(video_paths),
            "cleanStaceyCandidates": clean_stacey_candidates,
            "duplicateContentHash": duplicate_content_hash,
            "duplicateSourceFingerprint": duplicate_source_fingerprint,
            "duplicateRecentPublish": duplicate_recent_publish,
            "corruptedOrInvalid": corrupted_or_invalid,
            "audioPresent": audio_present_count,
            "audioMissingNeedsCampaignAudio": audio_missing_count,
            "status": status,
            "blockingReason": blocking_reason,
            "wouldProceedToRendering": False,
            "canProceedAfterOperatorSourceApproval": status
            == "ready_for_source_approval",
            "nextOperatorAction": "approve_25_source_candidates_before_caption_rendering"
            if status == "ready_for_source_approval"
            else "provide_more_clean_stacey_archive_inventory",
            "items": items,
        }
        report_path = (
            report_dir
            / f"archive_inventory_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        result["reportPath"] = str(report_path)
        atomic_write_text(
            report_path,
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        self.record_event(
            "archive_inventory_report",
            campaign_id=campaign["id"],
            status="success" if status == "ready_for_source_approval" else "warning",
            message=f"Archive inventory report: {clean_stacey_candidates}/{requested_count} clean {creator} source candidates",
            metadata={
                "reportPath": str(report_path),
                "archiveVideosFound": len(video_paths),
                "cleanCandidates": clean_stacey_candidates,
                "blockingReason": blocking_reason,
            },
            commit=False,
        )
        self.conn.commit()
        return result

    def archive_existing_content_duplicate(self, digest: str) -> dict[str, Any] | None:
        source = self.conn.execute(
            """
            SELECT source_assets.id, source_assets.campaign_id, campaigns.slug AS campaign_slug
            FROM source_assets
            JOIN campaigns ON campaigns.id = source_assets.campaign_id
            WHERE source_assets.content_hash = ?
            LIMIT 1
            """,
            (digest,),
        ).fetchone()
        if source:
            return {
                "table": "source_assets",
                "id": source["id"],
                "campaignId": source["campaign_id"],
                "campaign": source["campaign_slug"],
            }
        rendered = self.conn.execute(
            """
            SELECT rendered_assets.id, rendered_assets.campaign_id, campaigns.slug AS campaign_slug
            FROM rendered_assets
            JOIN campaigns ON campaigns.id = rendered_assets.campaign_id
            WHERE rendered_assets.content_hash = ?
            LIMIT 1
            """,
            (digest,),
        ).fetchone()
        if rendered:
            return {
                "table": "rendered_assets",
                "id": rendered["id"],
                "campaignId": rendered["campaign_id"],
                "campaign": rendered["campaign_slug"],
            }
        return None

    def archive_recent_publish_duplicate(
        self, digest: str, recent_cutoff: datetime
    ) -> dict[str, Any] | None:
        rows = self.conn.execute(
            """
            SELECT performance_snapshots.id, performance_snapshots.post_id, performance_snapshots.published_at,
                   performance_snapshots.campaign_id, campaigns.slug AS campaign_slug
            FROM performance_snapshots
            JOIN campaigns ON campaigns.id = performance_snapshots.campaign_id
            WHERE performance_snapshots.content_hash = ?
               OR performance_snapshots.source_content_hash = ?
            ORDER BY performance_snapshots.published_at DESC
            LIMIT 5
            """,
            (digest, digest),
        ).fetchall()
        for row in rows:
            published_at = row["published_at"]
            if not published_at:
                continue
            try:
                parsed = datetime.fromisoformat(
                    str(published_at).replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            if parsed >= recent_cutoff:
                return {
                    "table": "performance_snapshots",
                    "id": row["id"],
                    "postId": row["post_id"],
                    "campaignId": row["campaign_id"],
                    "campaign": row["campaign_slug"],
                    "publishedAt": published_at,
                }
        return None

    def archive_candidate_quality_report(
        self,
        *,
        inventory_report_path: Path,
        requested_count: int = 25,
        exclude_indices: list[int] | None = None,
    ) -> dict[str, Any]:
        path = Path(inventory_report_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"archive inventory report not found: {path}")
        if requested_count <= 0:
            raise ValueError("requested_count must be positive")
        inventory = json_load(path.read_text(encoding="utf-8"), {})
        if (
            not isinstance(inventory, dict)
            or inventory.get("schema") != "campaign_factory.archive_inventory_report.v1"
        ):
            raise ValueError(f"not an archive inventory report: {path}")

        excluded = set(exclude_indices or [])
        clean_items = [
            item
            for item in inventory.get("items", [])
            if isinstance(item, dict) and item.get("status") == "clean_source_candidate"
        ]
        ranked: list[dict[str, Any]] = []
        for item in clean_items:
            index = int(item.get("index") or 0)
            probe = item.get("probe") if isinstance(item.get("probe"), dict) else {}
            severity, crop_score, crop_delta = self.archive_crop_severity(probe)
            visual_score = self.archive_visual_quality_score(
                probe, item.get("warnings") or [], crop_score
            )
            duplicate_confidence = self.archive_duplicate_confidence(item)
            recommendation = (
                "excluded_by_operator" if index in excluded else "candidate"
            )
            ranked.append(
                {
                    "index": index,
                    "filename": item.get("filename"),
                    "sourcePath": item.get("sourcePath"),
                    "contentHash": item.get("contentHash"),
                    "sourceFingerprint": item.get("sourceFingerprint"),
                    "aspectRatio": probe.get("effectiveAspectRatio"),
                    "durationSeconds": probe.get("durationSeconds"),
                    "resolution": f"{probe.get('effectiveWidth') or probe.get('width')}x{probe.get('effectiveHeight') or probe.get('height')}",
                    "bitrate": probe.get("bitrate"),
                    "audioStatus": item.get("audioStatus"),
                    "warnings": item.get("warnings") or [],
                    "estimatedCropSeverity": severity,
                    "cropDeviationFrom9x16": crop_delta,
                    "cropSeverityScore": crop_score,
                    "visualQualityScore": visual_score,
                    "duplicateConfidence": duplicate_confidence,
                    "recommendation": recommendation,
                    "selectionReason": None,
                }
            )

        selectable = [
            item for item in ranked if item["recommendation"] != "excluded_by_operator"
        ]
        selectable.sort(
            key=lambda item: (
                -item["visualQualityScore"],
                item["cropSeverityScore"],
                item["index"],
            )
        )
        selected = selectable[:requested_count]
        selected_indices = {item["index"] for item in selected}
        for item in ranked:
            if item["recommendation"] == "excluded_by_operator":
                item["selectionReason"] = "operator excluded before rendering"
            elif item["index"] in selected_indices:
                item["recommendation"] = "selected_for_source_approval"
                item["selectionReason"] = "top ranked clean source candidate"
            else:
                item["recommendation"] = "alternate"
                item["selectionReason"] = (
                    "clean but lower ranked than requested pilot count"
                )

        ranked.sort(key=lambda item: item["index"])
        recommended_indices = [item["index"] for item in selected]
        recommended_indices.sort()
        status = (
            "ready_for_source_approval"
            if len(selected) >= requested_count
            else "blocked"
        )
        blocking_reason = (
            None
            if status == "ready_for_source_approval"
            else "insufficient_ranked_archive_inventory"
        )
        report_dir = path.parent.parent / "candidate_quality"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = (
            report_dir
            / f"archive_candidate_quality_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        result = {
            "schema": "campaign_factory.archive_candidate_quality_report.v1",
            "campaign": inventory.get("campaign"),
            "campaignId": inventory.get("campaignId"),
            "creator": inventory.get("creator"),
            "inventoryReportPath": str(path),
            "generatedAt": self._utc_now(),
            "requestedCount": requested_count,
            "cleanCandidatesAvailable": len(clean_items),
            "rankedCandidatesAvailable": len(selectable),
            "recommendedCount": len(selected),
            "recommendedIndices": recommended_indices,
            "excludedIndices": sorted(excluded),
            "status": status,
            "blockingReason": blocking_reason,
            "wouldProceedToRendering": False,
            "nextOperatorAction": "approve_recommended_source_indices_before_caption_rendering"
            if status == "ready_for_source_approval"
            else "provide_more_clean_stacey_archive_inventory",
            "items": ranked,
        }
        result["reportPath"] = str(report_path)
        atomic_write_text(
            report_path,
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return result

    def archive_crop_severity(
        self, probe: dict[str, Any]
    ) -> tuple[str, int, float | None]:
        target = 9 / 16
        aspect = probe.get("effectiveAspectRatio")
        if not isinstance(aspect, (int, float)) or aspect <= 0:
            return "unknown", 50, None
        delta = abs(float(aspect) - target) / target
        if delta <= 0.04:
            return "low", 0, round(delta, 4)
        if delta <= 0.18:
            return "moderate", 18, round(delta, 4)
        if delta <= 0.35:
            return "high", 32, round(delta, 4)
        return "severe", 48, round(delta, 4)

    def archive_visual_quality_score(
        self, probe: dict[str, Any], warnings: list[Any], crop_score: int
    ) -> int:
        score = 100 - crop_score
        height = probe.get("effectiveHeight") or probe.get("height")
        width = probe.get("effectiveWidth") or probe.get("width")
        bitrate = probe.get("bitrate")
        duration = probe.get("durationSeconds")
        if isinstance(height, (int, float)):
            if height < 1000:
                score -= 14
            elif height < 1200:
                score -= 7
        else:
            score -= 12
        if isinstance(width, (int, float)) and width < 700:
            score -= 5
        if isinstance(bitrate, (int, float)):
            if bitrate < 3_000_000:
                score -= 8
            elif bitrate < 4_500_000:
                score -= 3
        if isinstance(duration, (int, float)):
            if duration < 4:
                score -= 5
            elif duration > 12:
                score -= 4
        else:
            score -= 5
        score -= min(12, len(warnings) * 6)
        return max(0, min(100, int(round(score))))

    def archive_duplicate_confidence(self, item: dict[str, Any]) -> str:
        duplicate = (
            item.get("duplicate") if isinstance(item.get("duplicate"), dict) else {}
        )
        if duplicate.get("recentPublish"):
            return "recent_publish_duplicate"
        if duplicate.get("existingCampaignAsset"):
            return "existing_campaign_duplicate"
        if duplicate.get("sourceFingerprint") == "duplicate":
            return "source_fingerprint_duplicate"
        return "clear"
