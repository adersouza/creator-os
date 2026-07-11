from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text


class SurfaceRegistrationRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        utc_now: Callable[[], str],
        creator_label: Callable[[Any], str],
        normalize_content_surface: Callable[[str | None], str],
        upsert_model: Callable[..., dict[str, Any]],
        upsert_campaign: Callable[..., dict[str, Any]],
        campaign_dirs: Callable[[str, str], dict[str, Path]],
        surface_handoff_readiness_report: Callable[..., dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
        media_type_for_path: Callable[[Path | str], str],
        sha256_file: Callable[[Path], str],
        probe_image_shape: Callable[[Path], dict[str, Any]],
        probe_video_shape: Callable[[Path], dict[str, Any]],
        ratio_label_from_shape: Callable[[int | None, int | None], str | None],
        story_source_blockers: Callable[[list[dict[str, Any]]], list[str]],
        normalize_story_enum: Callable[[Any, set[str]], str | None],
        story_intents: set[str],
        story_goals: set[str],
        story_styles: set[str],
        ig_media_type_by_surface: dict[str, str],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._utc_now = utc_now
        self._creator_label = creator_label
        self._normalize_content_surface = normalize_content_surface
        self._upsert_model = upsert_model
        self._upsert_campaign = upsert_campaign
        self._campaign_dirs = campaign_dirs
        self._surface_handoff_readiness_report = surface_handoff_readiness_report
        self._record_event = record_event
        self._media_type_for_path = media_type_for_path
        self._sha256_file = sha256_file
        self._probe_image_shape = probe_image_shape
        self._probe_video_shape = probe_video_shape
        self._ratio_label_from_shape = ratio_label_from_shape
        self._story_source_blockers = story_source_blockers
        self._normalize_story_enum = normalize_story_enum
        self._story_intents = story_intents
        self._story_goals = story_goals
        self._story_styles = story_styles
        self._ig_media_type_by_surface = ig_media_type_by_surface

    def register_surface_asset(
        self,
        *,
        input_path: Path | list[Path] | tuple[Path, ...],
        surface: str,
        creator: str,
        campaign_slug: str,
        instagram_post_caption: str | None = None,
        target_ratio: str | None = None,
        model_slug: str | None = None,
        operator: str | None = None,
        alt_text: list[str] | None = None,
        story_asset_class: str | None = None,
        story_cta_type: str | None = None,
        story_cta_text: str | None = None,
        story_cta_target_url: str | None = None,
        story_intent: str | None = None,
        story_goal: str | None = None,
        story_style: str | None = None,
        snapchat_username: str | None = None,
        snapchat_display_name: str | None = None,
        snapchat_cta_text: str | None = None,
    ) -> dict[str, Any]:
        content_surface = self._normalize_content_surface(surface)
        if content_surface not in {"feed_single", "story", "feed_carousel"}:
            raise ValueError(
                "register-surface-asset supports feed_single, story, and feed_carousel"
            )
        creator_label = self._creator_label(creator)
        model = self._upsert_model(
            self._slugify(model_slug or creator_label), creator_label
        )
        campaign = self._upsert_campaign(
            campaign_slug, model["slug"], platform="instagram"
        )
        dirs = self._campaign_dirs(model["slug"], campaign["slug"])
        post_caption = (instagram_post_caption or "").strip()
        if content_surface in {"feed_single", "feed_carousel"} and not post_caption:
            raise ValueError(
                "instagram_post_caption is required for feed_single and feed_carousel"
            )
        components = self.surface_registration_components(
            input_path=input_path,
            surface=content_surface,
            target_ratio=target_ratio,
        )
        if content_surface == "feed_single" and components[0]["mediaType"] != "image":
            raise ValueError("feed_single registration requires an image file")
        if content_surface == "story" and components[0]["mediaType"] not in {
            "image",
            "video",
        }:
            raise ValueError("story registration requires an image or video file")
        if content_surface == "story":
            story_source_blockers = self._story_source_blockers(components)
            if story_source_blockers:
                raise ValueError(
                    f"story source is not story-native: {', '.join(story_source_blockers)}"
                )
        if content_surface == "feed_carousel":
            if not (2 <= len(components) <= 10):
                raise ValueError("carousel requires 2 to 10 components")
            if not self.aspect_ratio_safe(
                components[0]["aspectRatio"], "feed_carousel"
            ):
                raise ValueError("carousel cover aspect ratio is not safe")

        component_hashes = [item["contentHash"] for item in components]
        content_hash = (
            component_hashes[0]
            if len(component_hashes) == 1
            else hashlib.sha256("|".join(component_hashes).encode("utf-8")).hexdigest()
        )
        staged_components = [
            {
                **item,
                "stagedPath": self.stage_surface_registration_file(
                    item["path"],
                    dirs["rendered"],
                    content_surface=content_surface,
                    content_hash=item["contentHash"],
                    component_index=index,
                ),
            }
            for index, item in enumerate(components)
        ]
        representative = staged_components[0]
        now = self._utc_now()
        scoped_key = hashlib.sha256(
            f"{campaign['id']}:{content_hash}".encode()
        ).hexdigest()[:12]
        source_asset_id = f"src_surface_{scoped_key}"
        render_job_id = f"render_surface_{scoped_key}"
        rendered_id = f"asset_surface_{scoped_key}"
        media_type = (
            representative["mediaType"]
            if content_surface != "feed_carousel"
            else "carousel"
        )
        ratio = target_ratio or representative.get("aspectRatio") or "9:16"
        caption_hash_value = (
            hashlib.sha256(post_caption.lower().encode("utf-8")).hexdigest()
            if post_caption
            else None
        )
        ig_media_type = self.ig_media_type_for_surface(content_surface, media_type)
        source_prompt = {
            "schema": "campaign_factory.surface_asset_registration.v1",
            "contentSurface": content_surface,
            "igMediaType": ig_media_type,
            "inputPaths": [str(item["path"]) for item in components],
            "stagedPaths": [str(item["stagedPath"]) for item in staged_components],
            "operator": operator,
            "instagramPostCaptionPresent": bool(post_caption),
        }
        caption_context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "creator_mix": creator_label,
            "creator_model": creator_label,
            "render_recipe": "surface_asset_registered",
            "content_surface": content_surface,
            "instagram_post_caption_hash": caption_hash_value,
            "visualQcStatus": "passed",
            "identityVerificationStatus": "passed",
            "visualQc": {"status": "passed"},
            "identityVerification": {"status": "passed"},
        }
        caption_generation = {
            "schema": "campaign_factory.surface_asset_caption_generation.v1",
            "instagram_post_caption": post_caption,
            "instagramPostCaption": post_caption,
            "instagramPostCaptionHash": caption_hash_value,
            "captionOutcomeContext": caption_context,
            "allow_empty_instagram_post_caption": content_surface == "story"
            and not post_caption,
            "operatorReview": {
                "operator": operator,
                "approvedAt": now,
            },
        }
        if content_surface == "story":
            caption_generation.update(
                {
                    "story_asset_class": (story_asset_class or "").strip() or None,
                    "story_cta_type": (story_cta_type or "").strip() or None,
                    "story_cta_text": (story_cta_text or "").strip() or None,
                    "story_cta_target_url": (story_cta_target_url or "").strip()
                    or None,
                    "story_intent": self._normalize_story_enum(
                        story_intent, self._story_intents
                    ),
                    "story_goal": self._normalize_story_enum(
                        story_goal, self._story_goals
                    ),
                    "story_style": self._normalize_story_enum(
                        story_style, self._story_styles
                    ),
                    "snapchat_username": (snapchat_username or "").strip() or None,
                    "snapchat_display_name": (snapchat_display_name or "").strip()
                    or None,
                    "snapchat_cta_text": (snapchat_cta_text or "").strip() or None,
                }
            )
        self.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path, filename,
             media_type, content_surface, platform, source_prompt, notes, account_ids_json,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'instagram', ?, ?, '[]', 'imported', ?, ?)
            ON CONFLICT(campaign_id, content_hash) DO UPDATE SET
              original_path = excluded.original_path,
              stored_path = excluded.stored_path,
              filename = excluded.filename,
              media_type = excluded.media_type,
              content_surface = excluded.content_surface,
              source_prompt = excluded.source_prompt,
              notes = excluded.notes,
              updated_at = excluded.updated_at
            """,
            (
                source_asset_id,
                campaign["id"],
                model["id"],
                content_hash,
                str(representative["path"]),
                str(representative["stagedPath"]),
                representative["stagedPath"].name,
                media_type,
                content_surface,
                json.dumps(source_prompt, ensure_ascii=False, sort_keys=True),
                "surface asset registration source",
                now,
                now,
            ),
        )
        source_row = self.conn.execute(
            "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], content_hash),
        ).fetchone()
        if not source_row:
            raise RuntimeError("registered surface source asset could not be loaded")
        source_asset_id = source_row["id"]
        self.conn.execute(
            """
            INSERT INTO render_jobs
            (id, campaign_id, source_asset_id, reel_clip_stem, hooks_json, recipes_json,
             caption_color, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'none', 'rendered', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              source_asset_id = excluded.source_asset_id,
              status = 'rendered',
              updated_at = excluded.updated_at
            """,
            (
                render_job_id,
                campaign["id"],
                source_asset_id,
                representative["stagedPath"].stem,
                json.dumps([post_caption] if post_caption else [], ensure_ascii=False),
                json.dumps(["surface_asset_registered"], ensure_ascii=False),
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, render_job_id, content_hash, output_path,
             campaign_path, filename, media_type, content_surface, caption, caption_hash,
             caption_bank, caption_banks_json, creator_mix, creator_model, frame_type,
             length_class, format_class, caption_fit_version, suitability_decision,
             suitability_reason, source_clip, caption_outcome_context_json,
             caption_generation_json, recipe, target_ratio, audit_status, review_state,
             story_asset_class, story_cta_type, story_cta_text, story_cta_target_url,
             story_intent, story_goal, story_style, snapchat_username, snapchat_display_name,
             snapchat_cta_text,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'operator_surface_asset', ?,
                    ?, ?, ?, 'static', ?, 'surface_asset_v1', 'allowed',
                    'operator registered surface asset', ?, ?, ?, 'surface_asset_registered',
                    ?, 'passed', 'approved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, content_hash) DO UPDATE SET
              source_asset_id = excluded.source_asset_id,
              render_job_id = excluded.render_job_id,
              output_path = excluded.output_path,
              campaign_path = excluded.campaign_path,
              filename = excluded.filename,
              media_type = excluded.media_type,
              content_surface = excluded.content_surface,
              caption = excluded.caption,
              caption_hash = excluded.caption_hash,
              caption_bank = excluded.caption_bank,
              caption_banks_json = excluded.caption_banks_json,
              creator_mix = excluded.creator_mix,
              creator_model = excluded.creator_model,
              frame_type = excluded.frame_type,
              length_class = excluded.length_class,
              format_class = excluded.format_class,
              caption_fit_version = excluded.caption_fit_version,
              suitability_decision = excluded.suitability_decision,
              suitability_reason = excluded.suitability_reason,
              source_clip = excluded.source_clip,
              caption_outcome_context_json = excluded.caption_outcome_context_json,
              caption_generation_json = excluded.caption_generation_json,
              recipe = excluded.recipe,
              target_ratio = excluded.target_ratio,
              audit_status = excluded.audit_status,
              review_state = excluded.review_state,
              story_asset_class = excluded.story_asset_class,
              story_cta_type = excluded.story_cta_type,
              story_cta_text = excluded.story_cta_text,
              story_cta_target_url = excluded.story_cta_target_url,
              story_intent = excluded.story_intent,
              story_goal = excluded.story_goal,
              story_style = excluded.story_style,
              snapchat_username = excluded.snapchat_username,
              snapchat_display_name = excluded.snapchat_display_name,
              snapchat_cta_text = excluded.snapchat_cta_text,
              updated_at = excluded.updated_at
            """,
            (
                rendered_id,
                campaign["id"],
                source_asset_id,
                render_job_id,
                content_hash,
                str(representative["stagedPath"]),
                str(representative["stagedPath"]),
                representative["stagedPath"].name,
                media_type,
                content_surface,
                post_caption,
                caption_hash_value,
                json.dumps(["operator_surface_asset"], ensure_ascii=False),
                creator_label,
                creator_label,
                content_surface,
                content_surface,
                str(representative["path"]),
                json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
                json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
                ratio,
                (story_asset_class or "").strip() or None,
                (story_cta_type or "").strip() or None,
                (story_cta_text or "").strip() or None,
                (story_cta_target_url or "").strip() or None,
                self._normalize_story_enum(story_intent, self._story_intents),
                self._normalize_story_enum(story_goal, self._story_goals),
                self._normalize_story_enum(story_style, self._story_styles),
                (snapchat_username or "").strip() or None,
                (snapchat_display_name or "").strip() or None,
                (snapchat_cta_text or "").strip() or None,
                now,
                now,
            ),
        )
        rendered_row = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], content_hash),
        ).fetchone()
        if not rendered_row:
            raise RuntimeError("registered surface rendered asset could not be loaded")
        rendered_id = rendered_row["id"]
        self.conn.execute(
            "DELETE FROM asset_components WHERE asset_id = ?", (rendered_id,)
        )
        if content_surface == "feed_carousel":
            for index, item in enumerate(staged_components):
                self.conn.execute(
                    """
                    INSERT INTO asset_components
                    (id, asset_id, component_index, media_path, media_hash, media_type,
                     aspect_ratio, alt_text, publishability_state, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'passed', ?, ?)
                    """,
                    (
                        f"component_{rendered_id}_{index}",
                        rendered_id,
                        index,
                        str(item["stagedPath"]),
                        item["contentHash"],
                        item["mediaType"],
                        item["aspectRatio"],
                        (alt_text or [None] * len(staged_components))[index]
                        if index < len(alt_text or [])
                        else None,
                        now,
                        now,
                    ),
                )
        audit_id = f"audit_surface_{scoped_key}"
        audit_payload = {
            "schema": "campaign_factory.surface_asset_audit.v1",
            "contentSurface": content_surface,
            "igMediaType": ig_media_type,
            "overallVerdict": "pass",
            "visualQcStatus": "passed",
            "identityVerificationStatus": "passed",
            "visualQc": {"status": "passed"},
            "identityVerification": {"status": "passed"},
            "readinessSummary": {
                "uploadReady": True,
                "blockingReasons": [],
                "blockingCodes": [],
                "warnings": [],
                "warningCodes": [],
                "visualQcStatus": "passed",
                "identityVerificationStatus": "passed",
            },
            "mediaItems": [
                {
                    "mediaPath": str(item["stagedPath"]),
                    "mediaHash": item["contentHash"],
                    "mediaType": item["mediaType"],
                    "aspectRatio": item["aspectRatio"],
                }
                for item in staged_components
            ],
        }
        audit_dir = dirs["audits"] / "surface_asset_registration"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / f"{audit_id}.json"
        atomic_write_text(
            audit_path,
            json.dumps(audit_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.conn.execute(
            """
            INSERT INTO audit_reports
            (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score,
             status, layers_json, verdicts_json, overall_verdict, files_analyzed,
             failed_checks_json, warnings_json, created_at)
            VALUES (?, ?, ?, 'surface_asset_registration', ?, 90, 'pass', '{}', '{}',
                    'pass', ?, '[]', '[]', ?)
            ON CONFLICT(id) DO UPDATE SET
              rendered_asset_id = excluded.rendered_asset_id,
              report_path = excluded.report_path,
              status = excluded.status,
              overall_verdict = excluded.overall_verdict,
              files_analyzed = excluded.files_analyzed,
              created_at = excluded.created_at
            """,
            (
                audit_id,
                campaign["id"],
                rendered_id,
                str(audit_path),
                len(staged_components),
                now,
            ),
        )
        self._record_event(
            "surface_asset_registered",
            campaign_id=campaign["id"],
            source_asset_id=source_asset_id,
            rendered_asset_id=rendered_id,
            render_job_id=render_job_id,
            audit_report_id=audit_id,
            status="success",
            message=f"Surface asset registered: {representative['stagedPath'].name}",
            metadata={
                "contentSurface": content_surface,
                "igMediaType": ig_media_type,
                "contentHash": content_hash,
            },
            commit=False,
        )
        self.conn.commit()
        readiness_report = self._surface_handoff_readiness_report(
            creator=creator_label,
            campaign_slug=campaign["slug"],
            rendered_asset_id=rendered_id,
        )
        readiness = (
            readiness_report["assets"][0]
            if readiness_report["assets"]
            else {"canHandoff": False, "igMediaType": ig_media_type}
        )
        return {
            "schema": "campaign_factory.register_surface_asset.v1",
            "campaign": campaign["slug"],
            "creator": creator_label,
            "renderedAssetId": rendered_id,
            "sourceAssetId": source_asset_id,
            "renderJobId": render_job_id,
            "auditReportId": audit_id,
            "contentHash": content_hash,
            "contentSurface": content_surface,
            "mediaType": media_type,
            "igMediaType": readiness["igMediaType"],
            "instagramPostCaptionPresent": bool(post_caption),
            "componentCount": len(staged_components),
            "mediaItems": (readiness.get("handoffManifestV2") or {}).get(
                "mediaItems", []
            ),
            "publishability": "passed" if readiness.get("canHandoff") else "blocked",
            "handoffManifestV2": readiness.get("handoffManifestV2"),
            "wouldSchedule": False,
            "wouldPublish": False,
        }

    def surface_registration_components(
        self,
        *,
        input_path: Path | list[Path] | tuple[Path, ...],
        surface: str,
        target_ratio: str | None,
    ) -> list[dict[str, Any]]:
        if surface == "feed_carousel":
            paths = (
                [Path(input_path)]
                if isinstance(input_path, (str, Path))
                else [Path(path) for path in input_path]
            )
        else:
            if isinstance(input_path, (list, tuple)):
                if len(input_path) != 1:
                    raise ValueError(
                        f"{surface} registration requires exactly one media file"
                    )
                paths = [Path(input_path[0])]
            else:
                paths = [Path(input_path)]
        return [
            self.surface_registration_component(
                path, surface=surface, target_ratio=target_ratio
            )
            for path in paths
        ]

    def surface_registration_component(
        self, path: Path, *, surface: str, target_ratio: str | None
    ) -> dict[str, Any]:
        source = path.expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"surface media not found: {source}")
        media_type = self._media_type_for_path(source)
        if media_type not in {"image", "video"}:
            raise ValueError("surface asset requires an image or video file")
        shape = (
            self._probe_image_shape(source)
            if media_type == "image"
            else self._probe_video_shape(source)
        )
        width = (
            int(shape.get("effectiveWidth") or shape.get("width") or 0)
            if isinstance(shape, dict)
            else 0
        )
        height = (
            int(shape.get("effectiveHeight") or shape.get("height") or 0)
            if isinstance(shape, dict)
            else 0
        )
        aspect_ratio = (
            target_ratio or self._ratio_label_from_shape(width, height) or ""
        ).strip()
        if media_type == "image" and (not shape.get("ok") or not width or not height):
            raise ValueError("valid image dimensions are required")
        if media_type == "video" and not aspect_ratio:
            raise ValueError("valid video dimensions or target_ratio are required")
        readiness_surface = "feed_carousel" if surface == "feed_carousel" else surface
        if aspect_ratio and not self.aspect_ratio_safe(aspect_ratio, readiness_surface):
            raise ValueError(f"{surface} aspect ratio is not safe")
        return {
            "path": source,
            "mediaType": media_type,
            "contentHash": self._sha256_file(source),
            "aspectRatio": aspect_ratio or target_ratio or "9:16",
            "shape": shape,
        }

    def stage_surface_registration_file(
        self,
        path: Path,
        rendered_dir: Path,
        *,
        content_surface: str,
        content_hash: str,
        component_index: int,
    ) -> Path:
        prefix = f"{content_surface}_{component_index}_{self._slugify(path.stem)}_{content_hash[:10]}"
        staged = rendered_dir / f"{prefix}{path.suffix.lower()}"
        if not staged.exists():
            shutil.copy2(path, staged)
        return staged

    def ig_media_type_for_surface(self, surface: str, media_type: str) -> str:
        return self._ig_media_type_by_surface.get(surface, "REELS")

    def aspect_ratio_safe(self, ratio: Any, surface: str) -> bool:
        text = str(ratio or "").strip()
        if not text:
            return True
        safe = {
            "story": {"9:16", "4:5", "1:1"},
            "feed_single": {"1:1", "4:5", "1.91:1", "9:16"},
            "feed_carousel": {"1:1", "4:5", "1.91:1", "9:16"},
        }
        return text in safe.get(surface, {text})
