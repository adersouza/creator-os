from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Any


class StoryManagementRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_label: Callable[[Any], str],
        slugify: Callable[[str], str],
        json_load: Callable[[Any, Any], Any],
        normalize_content_surface: Callable[[str | None], str],
        media_type_for_path: Callable[[Path | str], str],
        probe_image_shape: Callable[[Path], dict[str, Any]],
        probe_video_shape: Callable[[Path], dict[str, Any]],
        read_png_rgb_pixels: Callable[[Path], dict[str, Any]],
        rendered_asset: Callable[[str], dict[str, Any]],
        build_surface_inventory: Callable[..., dict[str, Any]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        account_content_needs: Callable[..., dict[str, Any]],
        creator_content_needs: Callable[..., dict[str, Any]],
        last_surface_posted_at: Callable[..., str | None],
        truthy: Callable[[Any], bool],
        surface_readiness_scorecard: Callable[[], dict[str, Any]],
        certification_asset_for_surface: Callable[..., dict[str, Any] | None],
        surface_draft_proof: Callable[..., dict[str, Any]],
        latest_proof_run_for_asset: Callable[[str], dict[str, Any] | None],
        latest_surface_metric_for_asset: Callable[[str, str], dict[str, Any] | None],
        empty_surface_certification_audit: Callable[[str], dict[str, Any]],
        surface_certification_audit: Callable[..., dict[str, Any]],
        default_story_mix: dict[str, int],
        default_story_calendar: dict[str, str],
        story_intents: set[str],
        story_goals: set[str],
        story_styles: set[str],
    ) -> None:
        self.conn = conn
        self._creator_label = creator_label
        self._slugify = slugify
        self._json_load = json_load
        self._normalize_content_surface = normalize_content_surface
        self._media_type_for_path = media_type_for_path
        self._probe_image_shape = probe_image_shape
        self._probe_video_shape = probe_video_shape
        self._read_png_rgb_pixels = read_png_rgb_pixels
        self._rendered_asset = rendered_asset
        self._build_surface_inventory = build_surface_inventory
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._account_content_needs = account_content_needs
        self._creator_content_needs = creator_content_needs
        self._last_surface_posted_at = last_surface_posted_at
        self._truthy = truthy
        self._surface_readiness_scorecard = surface_readiness_scorecard
        self._certification_asset_for_surface = certification_asset_for_surface
        self._surface_draft_proof = surface_draft_proof
        self._latest_proof_run_for_asset = latest_proof_run_for_asset
        self._latest_surface_metric_for_asset = latest_surface_metric_for_asset
        self._empty_surface_certification_audit = empty_surface_certification_audit
        self._surface_certification_audit = surface_certification_audit
        self._default_story_mix = default_story_mix
        self._default_story_calendar = default_story_calendar
        self._story_intents = story_intents
        self._story_goals = story_goals
        self._story_styles = story_styles

    def story_inventory_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        inventory = self._build_surface_inventory(
            creator=creator_label, campaign_slug=campaign_slug
        )
        assets = inventory["assetsBySurface"].get("story") or []
        schedule_safe = 0
        publishable = 0
        quality_passed = 0
        classifications: dict[str, int] = {}
        cta_types: dict[str, int] = {}
        intent_counts: dict[str, int] = {}
        for asset in assets:
            readiness = self._surface_handoff_readiness_for_asset(asset)
            if readiness.get("canHandoff"):
                schedule_safe += 1
            quality = self.story_quality_gate_for_asset(asset)
            if quality.get("story_quality_gate_passed"):
                quality_passed += 1
            if str(asset.get("audit_status") or "").lower() in {
                "passed",
                "pass",
                "approved",
                "approved_candidate",
            } or str(asset.get("review_state") or "").lower() in {
                "approved",
                "review_ready",
            }:
                publishable += 1
            generation = self._json_load(asset.get("caption_generation_json"), {})
            if not isinstance(generation, dict):
                generation = {}
            story_class = str(
                asset.get("story_asset_class")
                or generation.get("story_asset_class")
                or generation.get("storyAssetClass")
                or generation.get("story_classification")
                or generation.get("storyClassification")
                or ""
            ).strip()
            if story_class:
                classifications[story_class] = classifications.get(story_class, 0) + 1
            cta_type = str(
                asset.get("story_cta_type")
                or generation.get("story_cta_type")
                or generation.get("storyCtaType")
                or ""
            ).strip()
            if cta_type:
                cta_types[cta_type] = cta_types.get(cta_type, 0) + 1
            intent = self.story_intent_value(asset)
            if intent:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
        snapchat_count = int(intent_counts.get("snapchat_promo") or 0)
        reel_teaser_count = int(intent_counts.get("reel_teaser") or 0)
        casual_count = sum(
            int(intent_counts.get(intent) or 0)
            for intent in (
                "casual_selfie",
                "mirror_selfie",
                "outfit_check",
                "gym_selfie",
                "bedroom_selfie",
                "lifestyle",
                "behind_the_scenes",
            )
        )
        return {
            "schema": "campaign_factory.story_inventory_report.v1",
            "creator": creator_label,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "storyAssetsAvailable": len(assets),
            "storyAssetsPublishable": publishable,
            "storyAssetsQualityPassed": quality_passed,
            "storyAssetsScheduleSafe": schedule_safe,
            "storyAssetsBlocked": max(0, len(assets) - schedule_safe),
            "storyClassifications": classifications,
            "storyCtaTypes": cta_types,
            "snapchatPromoStories": snapchat_count,
            "reelTeaserStories": reel_teaser_count,
            "casualStories": casual_count,
            "storyIntentCoverage": bool(assets)
            and sum(intent_counts.values()) == len(assets),
            "storyIntentCounts": intent_counts,
            "storyPublishingEnabled": False,
            "wouldWrite": False,
        }

    def story_intent_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        inventory = self._build_surface_inventory(
            creator=creator_label, campaign_slug=campaign_slug
        )
        assets = inventory["assetsBySurface"].get("story") or []
        intent_counts: dict[str, int] = {}
        goal_counts: dict[str, int] = {}
        style_counts: dict[str, int] = {}
        snapchat_rows: list[dict[str, Any]] = []
        asset_rows: list[dict[str, Any]] = []
        for asset in assets:
            intent = self.story_intent_value(asset)
            goal = self.story_goal_value(asset)
            style = self.story_style_value(asset)
            if intent:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
            if goal:
                goal_counts[goal] = goal_counts.get(goal, 0) + 1
            if style:
                style_counts[style] = style_counts.get(style, 0) + 1
            row = {
                "assetId": asset.get("id"),
                "storyIntent": intent,
                "storyGoal": goal,
                "storyStyle": style,
                "snapchatDisplayName": asset.get("snapchat_display_name"),
                "snapchatUsername": asset.get("snapchat_username"),
                "snapchatCtaText": asset.get("snapchat_cta_text"),
                "wouldWrite": False,
            }
            asset_rows.append(row)
            if intent == "snapchat_promo":
                snapchat_rows.append(row)
        return {
            "schema": "campaign_factory.story_intent_report.v1",
            "creator": creator_label,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "storyAssetsAnalyzed": len(assets),
            "intentCounts": intent_counts,
            "goalCounts": goal_counts,
            "styleCounts": style_counts,
            "snapchatPromoStories": int(intent_counts.get("snapchat_promo") or 0),
            "snapchatPromo": snapchat_rows,
            "assets": asset_rows,
            "wouldWrite": False,
        }

    def story_mix_plan(self, *, creator: str) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        return {
            "schema": "campaign_factory.story_mix_plan.v1",
            "creator": creator_label,
            "storyMix": dict(self._default_story_mix),
            "strategy": "balanced_snapchat_promo",
            "maxSnapchatPromoPercent": 25,
            "wouldWrite": False,
        }

    def story_calendar_plan(self, *, creator: str) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        return {
            "schema": "campaign_factory.story_calendar_plan.v1",
            "creator": creator_label,
            "calendar": dict(self._default_story_calendar),
            "wouldWrite": False,
        }

    def story_intent_summary(
        self, *, creator: str, campaign_slug: str | None = None
    ) -> dict[str, Any]:
        report = self.story_intent_report(creator=creator, campaign_slug=campaign_slug)
        mix = self.story_mix_plan(creator=creator)
        calendar = self.story_calendar_plan(creator=creator)
        return {
            "schema": "campaign_factory.story_intent_summary.v1",
            "creator": self._creator_label(creator),
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "storyIntentReport": report,
            "storyMixPlan": mix,
            "storyCalendarPlan": calendar,
            "storyIntentPerformance": {},
            "storyStylePerformance": {},
            "wouldWrite": False,
        }

    def story_metadata_payload(self, asset: dict[str, Any]) -> dict[str, Any]:
        generation = self._json_load(asset.get("caption_generation_json"), {})
        if not isinstance(generation, dict):
            return {}
        meta = (
            generation.get("storyIntent")
            or generation.get("story_intent")
            or generation.get("storyMetadata")
            or generation.get("story_metadata")
            or {}
        )
        return meta if isinstance(meta, dict) else {}

    def story_intent_value(self, asset: dict[str, Any]) -> str | None:
        meta = self.story_metadata_payload(asset)
        return self.normalize_story_enum(
            asset.get("story_intent")
            or meta.get("storyIntent")
            or meta.get("story_intent"),
            self._story_intents,
        )

    def story_goal_value(self, asset: dict[str, Any]) -> str | None:
        meta = self.story_metadata_payload(asset)
        return self.normalize_story_enum(
            asset.get("story_goal") or meta.get("storyGoal") or meta.get("story_goal"),
            self._story_goals,
        )

    def story_style_value(self, asset: dict[str, Any]) -> str | None:
        meta = self.story_metadata_payload(asset)
        return self.normalize_story_enum(
            asset.get("story_style")
            or meta.get("storyStyle")
            or meta.get("story_style"),
            self._story_styles,
        )

    def normalize_story_enum(self, value: Any, allowed: set[str]) -> str | None:
        normalized = (
            str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        )
        return normalized if normalized in allowed else None

    def story_quality_gate_v1(self, rendered_asset_id: str) -> dict[str, Any]:
        asset = self._rendered_asset(rendered_asset_id)
        return self.story_quality_gate_for_asset(asset)

    def story_quality_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        inventory = self._build_surface_inventory(
            creator=creator_label, campaign_slug=campaign_slug
        )
        assets = inventory["assetsBySurface"].get("story") or []
        results = [self.story_quality_gate_for_asset(asset) for asset in assets]
        failures = sorted(
            {
                reason
                for result in results
                for reason in result.get("failureReasons") or []
            }
        )
        passed = sum(1 for result in results if result.get("story_quality_gate_passed"))
        return {
            "schema": "campaign_factory.story_quality_report.v1",
            "creator": creator_label,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "storyAssetsAnalyzed": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "failureReasons": failures,
            "assets": results,
            "wouldWrite": False,
        }

    def story_quality_gate_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        surface = self._normalize_content_surface(
            asset.get("content_surface") or asset.get("source_content_surface")
        )
        media_path = Path(
            str(asset.get("campaign_path") or asset.get("output_path") or "")
        )
        media_type = str(
            asset.get("media_type") or self._media_type_for_path(media_path)
        ).lower()
        failures: list[str] = []
        warnings: list[str] = []
        if surface != "story":
            failures.append("not_story_surface")
        shape = (
            self._probe_image_shape(media_path)
            if media_type == "image"
            else self._probe_video_shape(media_path)
        )
        width = int(
            (shape or {}).get("effectiveWidth") or (shape or {}).get("width") or 0
        )
        height = int(
            (shape or {}).get("effectiveHeight") or (shape or {}).get("height") or 0
        )
        aspect = (width / height) if width and height else None
        geometry_passed = bool(
            width
            and height
            and abs((aspect or 0) - (9 / 16)) <= 0.0025
            and width >= 1080
            and height >= 1920
        )
        if not width or not height:
            failures.append("unknown_aspect_ratio")
        elif abs((aspect or 0) - (9 / 16)) > 0.0025:
            failures.append("invalid_story_aspect_ratio")
        elif width < 1080 or height < 1920:
            failures.append("low_resolution_story")
        black_bar_check = self.story_black_bar_check(media_path, media_type=media_type)
        if black_bar_check.get("blackBarsDetected"):
            failures.append("black_bars")
        if black_bar_check.get("warning"):
            warnings.append(str(black_bar_check["warning"]))
        quality = self.story_quality_metadata(asset)
        safe_zone_score = self.bounded_score(
            quality.get("story_safe_zone_score") or quality.get("storySafeZoneScore"),
            default=100,
        )
        focal_score = self.bounded_score(
            quality.get("story_focal_safety_score")
            or quality.get("storyFocalSafetyScore"),
            default=100,
        )
        text_score = self.bounded_score(
            quality.get("story_text_readability_score")
            or quality.get("storyTextReadabilityScore"),
            default=100,
        )
        contains_text = self._truthy(
            quality.get("containsRenderedText") or quality.get("contains_rendered_text")
        )
        focal_reason = str(
            quality.get("focalFailureReason")
            or quality.get("focal_failure_reason")
            or "focal_safety_violation"
        ).strip()
        if safe_zone_score < 95:
            failures.append("safe_zone_violation")
        if focal_score < 95:
            failures.append(focal_reason or "focal_safety_violation")
        if contains_text and text_score < 95:
            failures.append("text_hidden")
        source_blockers = self.story_existing_asset_source_blockers(asset)
        failures.extend(source_blockers)
        no_text_check = self.story_no_text_check(
            media_path, media_type=media_type, quality=quality
        )
        if no_text_check["required"] and not no_text_check["passed"]:
            failures.append(
                no_text_check.get("failureReason") or "story_no_text_violation"
            )
        failures = sorted(set(failures))
        return {
            "schema": "campaign_factory.story_quality_gate_v1",
            "assetId": asset.get("id"),
            "contentSurface": surface,
            "mediaType": media_type,
            "story_quality_gate_passed": not failures,
            "storyQualityGatePassed": not failures,
            "geometry": {
                "width": width,
                "height": height,
                "aspectRatio": aspect,
                "targetResolution": "1080x1920",
                "passed": geometry_passed,
            },
            "storyBlackBarCheck": black_bar_check,
            "story_safe_zone_score": safe_zone_score,
            "story_focal_safety_score": focal_score,
            "story_text_readability_score": text_score,
            "sourceLineageBlockers": source_blockers,
            "storySourceNative": not source_blockers,
            "storyNoTextRequired": no_text_check["required"],
            "storyNoTextPassed": no_text_check["passed"],
            "storyNoTextCheck": no_text_check,
            "visualQualityStatus": "passed" if not failures else "rejected",
            "failureReasons": failures,
            "warnings": sorted(set(warnings)),
            "wouldWrite": False,
        }

    def story_quality_metadata(self, asset: dict[str, Any]) -> dict[str, Any]:
        generation = self._json_load(asset.get("caption_generation_json"), {})
        if not isinstance(generation, dict):
            return {}
        quality = (
            generation.get("storyQuality") or generation.get("story_quality") or {}
        )
        return quality if isinstance(quality, dict) else {}

    def bounded_score(self, value: Any, *, default: int) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return default

    def story_black_bar_check(
        self, media_path: Path, *, media_type: str
    ) -> dict[str, Any]:
        if media_type != "image":
            return {
                "blackBarsDetected": False,
                "top": False,
                "bottom": False,
                "left": False,
                "right": False,
                "warning": "black_bar_pixel_check_only_available_for_images",
            }
        pixels = self._read_png_rgb_pixels(media_path)
        if not pixels.get("ok"):
            return {
                "blackBarsDetected": False,
                "top": False,
                "bottom": False,
                "left": False,
                "right": False,
                "warning": f"black_bar_pixel_check_unavailable:{pixels.get('error')}",
            }
        rows = pixels["pixels"]
        height = int(pixels["height"])
        width = int(pixels["width"])
        band_h = max(1, height // 12)
        band_w = max(1, width // 12)
        result = {
            "top": self.pixel_region_black(rows, x0=0, x1=width, y0=0, y1=band_h),
            "bottom": self.pixel_region_black(
                rows, x0=0, x1=width, y0=height - band_h, y1=height
            ),
            "left": self.pixel_region_black(rows, x0=0, x1=band_w, y0=0, y1=height),
            "right": self.pixel_region_black(
                rows, x0=width - band_w, x1=width, y0=0, y1=height
            ),
        }
        result["blackBarsDetected"] = any(result.values())
        return result

    def story_no_text_check(
        self, media_path: Path, *, media_type: str, quality: dict[str, Any]
    ) -> dict[str, Any]:
        required = self._truthy(
            quality.get("storyNoTextRequired")
            or quality.get("story_no_text_required")
            or quality.get("noWordsRequired")
            or quality.get("no_words_required")
        )
        if not required:
            return {
                "required": False,
                "passed": True,
                "detectedText": [],
                "checkedFrames": 0,
                "engine": "not_required",
            }
        if not media_path.exists():
            return {
                "required": True,
                "passed": False,
                "detectedText": [],
                "checkedFrames": 0,
                "engine": "tesseract",
                "error": "media_file_missing",
                "failureReason": "story_no_text_check_unavailable",
            }
        tesseract = shutil.which("tesseract")
        if not tesseract:
            return {
                "required": True,
                "passed": False,
                "detectedText": [],
                "checkedFrames": 0,
                "engine": "tesseract",
                "error": "tesseract_missing",
                "failureReason": "story_no_text_check_unavailable",
            }
        frames = self.story_ocr_frame_paths(media_path, media_type=media_type)
        if not frames:
            return {
                "required": True,
                "passed": False,
                "detectedText": [],
                "checkedFrames": 0,
                "engine": "tesseract",
                "error": "frame_extraction_failed",
                "failureReason": "story_no_text_check_unavailable",
            }
        detected: list[dict[str, Any]] = []
        try:
            for index, frame in enumerate(frames):
                detected.extend(self.story_ocr_detect_text(frame, frame_index=index))
        finally:
            for frame in frames:
                if frame != media_path:
                    try:
                        frame.unlink(missing_ok=True)
                    except OSError:
                        pass
        return {
            "required": True,
            "passed": not detected,
            "detectedText": detected,
            "checkedFrames": len(frames),
            "engine": "tesseract",
            "failureReason": "story_no_text_violation" if detected else "",
        }

    def story_ocr_frame_paths(self, media_path: Path, *, media_type: str) -> list[Path]:
        if media_type == "image":
            return [media_path]
        if media_type != "video":
            return []
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return []
        tmpdir = Path(tempfile.mkdtemp(prefix="story_ocr_"))
        frames: list[Path] = []
        for index, offset in enumerate((0, 1, 2)):
            frame = tmpdir / f"frame_{index}.png"
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss",
                    str(offset),
                    "-i",
                    str(media_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=1080:-1",
                    str(frame),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            if result.returncode == 0 and frame.exists():
                frames.append(frame)
        return frames

    def story_ocr_detect_text(
        self, image_path: Path, *, frame_index: int
    ) -> list[dict[str, Any]]:
        result = subprocess.run(
            ["tesseract", str(image_path), "stdout", "--psm", "6", "tsv"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if result.returncode != 0:
            return []
        detected: list[dict[str, Any]] = []
        for line in result.stdout.splitlines()[1:]:
            columns = line.split("\t")
            if len(columns) < 12:
                continue
            text = columns[11].strip()
            if not re.search(r"[A-Za-z0-9]{3,}", text):
                continue
            try:
                confidence = float(columns[10])
            except ValueError:
                confidence = 0.0
            if confidence >= 45:
                detected.append(
                    {"text": text, "confidence": confidence, "frameIndex": frame_index}
                )
        return detected

    def pixel_region_black(
        self,
        rows: list[list[tuple[int, int, int]]],
        *,
        x0: int,
        x1: int,
        y0: int,
        y1: int,
    ) -> bool:
        total = 0
        black = 0
        step_y = max(1, (y1 - y0) // 64)
        step_x = max(1, (x1 - x0) // 64)
        for y in range(max(0, y0), min(len(rows), y1), step_y):
            row = rows[y]
            for x in range(max(0, x0), min(len(row), x1), step_x):
                total += 1
                r, g, b = row[x]
                if r <= 8 and g <= 8 and b <= 8:
                    black += 1
        return bool(total and black / total >= 0.95)

    def story_gap_report(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        needs = self._creator_content_needs(creator=creator_label, date=date)
        inventory = self.story_inventory_report(creator=creator_label)
        accounts = []
        needs_story = 0
        satisfied = 0
        blocked = 0
        for account in needs.get("accounts") or []:
            story_obligations = [
                obligation
                for obligation in account.get("obligations") or []
                if obligation.get("surface") == "story"
            ]
            if not story_obligations:
                continue
            required = sum(int(item.get("required") or 0) for item in story_obligations)
            remaining = sum(
                int(item.get("remaining") or 0) for item in story_obligations
            )
            needed = remaining > 0
            is_satisfied = required > 0 and not needed
            is_blocked = (
                needed and int(inventory.get("storyAssetsScheduleSafe") or 0) == 0
            )
            needs_story += 1 if needed else 0
            satisfied += 1 if is_satisfied else 0
            blocked += 1 if is_blocked else 0
            accounts.append(
                {
                    "accountId": account.get("accountId"),
                    "account": account.get("account"),
                    "instagramAccountId": account.get("instagramAccountId"),
                    "storyNeededToday": needed,
                    "required": required,
                    "remaining": remaining,
                    "blocked": is_blocked,
                    "blockedReason": "story_inventory_missing" if is_blocked else "",
                    "wouldWrite": False,
                }
            )
        return {
            "schema": "campaign_factory.story_gap_report.v1",
            "creator": creator_label,
            "date": datetime.fromisoformat(date).date().isoformat(),
            "accountsAnalyzed": len(accounts),
            "needsStoryToday": needs_story,
            "alreadySatisfied": satisfied,
            "blocked": blocked,
            "accounts": accounts,
            "wouldWrite": False,
        }

    def account_story_status(
        self,
        *,
        account_id: str,
        creator: str | None = None,
        date: str,
    ) -> dict[str, Any]:
        needs = self._account_content_needs(
            account_id=account_id, creator=creator, date=date
        )
        story_obligations = [
            item
            for item in needs.get("obligations") or []
            if item.get("surface") == "story"
        ]
        required = sum(int(item.get("required") or 0) for item in story_obligations)
        remaining = sum(int(item.get("remaining") or 0) for item in story_obligations)
        cadence = story_obligations[0].get("cadence") if story_obligations else None
        target_date = datetime.fromisoformat(date).date()
        last_story = self._last_surface_posted_at(
            account_id=needs.get("accountId") or account_id,
            instagram_account_id=needs.get("instagramAccountId"),
            surface="story",
            before_date=target_date + timedelta(days=1),
        )
        hours_since = None
        if last_story:
            try:
                reference = datetime.combine(
                    target_date + timedelta(days=1), datetime_time.min, tzinfo=UTC
                )
                posted = datetime.fromisoformat(last_story.replace("Z", "+00:00"))
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=UTC)
                hours_since = round((reference - posted).total_seconds() / 3600, 2)
            except ValueError:
                hours_since = None
        story_needed = remaining > 0
        if not story_obligations:
            status = "no_story_requirement"
        elif story_needed:
            status = "needs_story"
        else:
            status = "satisfied"
        return {
            "schema": "campaign_factory.account_story_status.v1",
            "creator": needs.get("creator"),
            "date": needs.get("date"),
            "accountId": needs.get("accountId"),
            "account": needs.get("account"),
            "instagramAccountId": needs.get("instagramAccountId"),
            "storyNeededToday": story_needed,
            "lastStoryPostedAt": last_story,
            "hoursSinceStory": hours_since,
            "storyCadence": cadence,
            "required": required,
            "remaining": remaining,
            "status": status,
            "wouldWrite": False,
        }

    def creator_story_summary(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        gap = self.story_gap_report(creator=creator_label, date=date)
        inventory = self.story_inventory_report(creator=creator_label)
        available = int(inventory.get("storyAssetsScheduleSafe") or 0)
        shortfall = max(0, int(gap.get("needsStoryToday") or 0) - available)
        return {
            "schema": "campaign_factory.creator_story_summary.v1",
            "creator": creator_label,
            "date": datetime.fromisoformat(date).date().isoformat(),
            "accounts": int(gap.get("accountsAnalyzed") or 0),
            "needsStoryToday": int(gap.get("needsStoryToday") or 0),
            "alreadySatisfied": int(gap.get("alreadySatisfied") or 0),
            "blocked": int(gap.get("blocked") or 0),
            "storyInventoryAvailable": available,
            "storyInventoryShortfall": shortfall,
            "storyReadiness": "ready" if shortfall == 0 else "blocked",
            "storyPublishingEnabled": False,
            "wouldWrite": False,
        }

    def story_certification_proof(
        self, *, rendered_asset_id: str | None = None
    ) -> dict[str, Any]:
        asset = self._certification_asset_for_surface(
            "story", rendered_asset_id=rendered_asset_id
        )
        blockers: list[str] = []
        if not asset:
            blockers.append("story_asset_missing")
            return {
                "schema": "creator_os.story_certification_proof.v1",
                "storyCreated": False,
                "storyValidated": False,
                "storyScheduled": False,
                "storyPublished": False,
                "storyMetricsImported": False,
                "lifecycleReconciled": False,
                "status": "blocked",
                "blockers": blockers,
                "audit": self._empty_surface_certification_audit("story"),
                "wouldWrite": False,
            }
        readiness = self._surface_handoff_readiness_for_asset(asset)
        draft = self._surface_draft_proof(
            creator=asset.get("creator_mix")
            or asset.get("creator_model")
            or asset.get("model_name"),
            campaign=asset.get("campaign_slug"),
            rendered_asset_id=asset["id"],
        )
        proof_run = self._latest_proof_run_for_asset(asset["id"])
        metrics = self._latest_surface_metric_for_asset(asset["id"], "story")
        draft_payload = draft["drafts"][0] if draft.get("drafts") else {}
        created = (
            self._normalize_content_surface(
                asset.get("content_surface") or asset.get("source_content_surface")
            )
            == "story"
        )
        validated = bool(
            readiness.get("canHandoff") and draft.get("canProduceDraftPayload")
        )
        scheduled = bool(
            proof_run
            and (
                proof_run.get("threadsdash_draft_id")
                or proof_run.get("distribution_plan_id")
            )
        )
        published = bool(
            metrics
            or (
                proof_run
                and proof_run.get("threadsdash_post_id")
                and str(proof_run.get("current_state") or "").lower()
                in {"published", "metrics_imported", "complete", "completed"}
            )
        )
        metrics_imported = bool(metrics)
        if not validated:
            blockers.append("story_validation_failed")
            blockers.extend(
                str(reason) for reason in readiness.get("blockingReasons") or []
            )
        if not scheduled:
            blockers.append("story_schedule_evidence_missing")
        if not published:
            blockers.append("story_publish_evidence_missing")
        if not metrics_imported:
            blockers.append("story_metrics_evidence_missing")
        lifecycle = bool(
            created and validated and scheduled and published and metrics_imported
        )
        return {
            "schema": "creator_os.story_certification_proof.v1",
            "storyCreated": bool(created),
            "storyValidated": bool(validated),
            "storyScheduled": bool(scheduled),
            "storyPublished": bool(published),
            "storyMetricsImported": bool(metrics_imported),
            "lifecycleReconciled": lifecycle,
            "status": "passed" if lifecycle else "blocked",
            "blockers": sorted(set(blockers)),
            "audit": self._surface_certification_audit(
                asset=asset,
                readiness=readiness,
                draft_payload=draft_payload,
                proof_run=proof_run,
                metrics=metrics,
            ),
            "wouldWrite": False,
        }

    def story_production_readiness(self) -> dict[str, Any]:
        scorecard = self._surface_readiness_scorecard()
        story = (scorecard.get("surfaces") or {}).get("story", {})
        return {
            "schema": "creator_os.story_production_readiness.v1",
            "publishProofMissing": not bool(story.get("publishProof")),
            "metricsProofMissing": not bool(story.get("metricsProof")),
            "blockingContracts": list(story.get("blockers") or []),
            "rating": story.get("rating", 0),
            "wouldWrite": False,
        }

    def story_proof_gap_analysis(self) -> dict[str, Any]:
        readiness = self.story_production_readiness()
        return {
            **readiness,
            "schema": "creator_os.story_proof_gap_analysis.v1",
            "nextProofsRequired": ["story_publish_proof", "story_metrics_proof"]
            if readiness["publishProofMissing"] or readiness["metricsProofMissing"]
            else [],
            "wouldWrite": False,
        }

    def story_source_blockers(self, components: list[dict[str, Any]]) -> list[str]:
        blockers: list[str] = []
        for item in components:
            path = Path(str(item.get("path") or "")).expanduser()
            path_text = str(path)
            lower_path = path_text.lower()
            parts = {part.lower() for part in path.parts}
            name = path.name.lower()
            if "campaign_factory" in parts and {"02_rendered", "04_approved"} & parts:
                blockers.append("story_source_must_be_raw_not_rendered_reel_asset")
            if item.get("mediaType") == "video" and any(
                marker in lower_path
                for marker in (
                    "variant_fanout",
                    "parent_repair",
                    "asset_finished",
                    "caption_family",
                    "contentforge",
                )
            ):
                blockers.append(
                    "story_video_source_looks_like_reel_or_contentforge_output"
                )
            if any(
                marker in name
                for marker in (
                    "captioned",
                    "caption_bg",
                    "burned_caption",
                    "parent_repair",
                )
            ):
                blockers.append(
                    "story_source_appears_to_have_burned_caption_or_reel_lineage"
                )
        return sorted(set(blockers))

    def story_existing_asset_source_blockers(self, asset: dict[str, Any]) -> list[str]:
        paths = [
            asset.get("source_clip"),
            asset.get("campaign_path"),
            asset.get("output_path"),
            asset.get("filename"),
        ]
        blockers: list[str] = []
        for raw in paths:
            if not raw:
                continue
            lower = str(raw).lower()
            parts = {part.lower() for part in Path(str(raw)).parts}
            if "campaign_factory" in parts and {"04_approved"} & parts:
                blockers.append("story_source_must_be_raw_not_approved_reel_asset")
            if (
                "campaign_factory" in parts
                and "02_rendered" in parts
                and any(
                    marker in lower
                    for marker in (
                        "variant_fanout",
                        "parent_repair",
                        "asset_finished",
                        "contentforge",
                    )
                )
            ):
                blockers.append("story_source_must_be_raw_not_rendered_reel_asset")
            if any(
                marker in lower
                for marker in (
                    "captioned",
                    "caption_bg",
                    "burned_caption",
                    "parent_repair",
                )
            ):
                blockers.append(
                    "story_source_appears_to_have_burned_caption_or_reel_lineage"
                )
        return sorted(set(blockers))
