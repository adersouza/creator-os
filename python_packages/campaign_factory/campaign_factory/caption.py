from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from typing import Any

from .caption_outcome import load_context_json
from .persistence import json_load

CAPTION_FAMILY_ANGLES = [
    "question_bait",
    "flirty_tease",
    "pov",
    "outfit_vote",
    "validation_hook",
    "reply_bait",
    "soft_cta",
]
CAPTION_FAMILY_CTA_BY_ANGLE = {
    "question_bait": "tell me yes or no",
    "flirty_tease": "save this for later",
    "pov": "send this to someone",
    "outfit_vote": "vote in the comments",
    "validation_hook": "drop a yes if this is you",
    "reply_bait": "be honest in the comments",
    "soft_cta": "follow for more",
}
CAPTION_FAMILY_BURNED_TEMPLATES = {
    "question_bait": "{base}?",
    "flirty_tease": "{base} but softer",
    "pov": "pov: {base}",
    "outfit_vote": "{base} - which one?",
    "validation_hook": "{base} if you needed a sign",
    "reply_bait": "{base} - be honest",
    "soft_cta": "{base} if this is your vibe",
}
CAPTION_FAMILY_POST_TEMPLATES = {
    "question_bait": "quick question: {base}",
    "flirty_tease": "this one felt too good not to post",
    "pov": "pov: you needed this reminder today",
    "outfit_vote": "which look wins?",
    "validation_hook": "if this is your sign, take it",
    "reply_bait": "be honest, would you post this?",
    "soft_cta": "more like this soon",
}


class CaptionFamilyRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        utc_now: Callable[[], str],
        normalize_content_surface: Callable[[str | None], str],
        rendered_asset: Callable[[str], dict[str, Any]],
        concept_for_parent_asset: Callable[[str], dict[str, Any] | None],
        explain_publishability: Callable[[str], dict[str, Any]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        instagram_post_caption_for_asset: Callable[..., dict[str, Any]],
        text_hash: Callable[[str], str],
    ) -> None:
        self.conn = conn
        self._utc_now = utc_now
        self._normalize_content_surface = normalize_content_surface
        self._rendered_asset = rendered_asset
        self._concept_for_parent_asset = concept_for_parent_asset
        self._explain_publishability = explain_publishability
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._instagram_post_caption_for_asset = instagram_post_caption_for_asset
        self._text_hash = text_hash

    def caption_family_plan(
        self,
        *,
        creator: str | None,
        parent_asset_id: str,
        requested_caption_versions: int = 5,
        style: str = "ig_short",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        requested = max(1, min(10, int(requested_caption_versions or 5)))
        parent = self._rendered_asset(parent_asset_id)
        concept = self._concept_for_parent_asset(parent_asset_id)
        content_surface = self._normalize_content_surface(parent.get("content_surface"))
        publishability = (
            self._explain_publishability(parent_asset_id)
            if content_surface == "reel"
            else {
                "publishableCandidate": self._surface_handoff_readiness_for_asset(
                    parent
                ).get("canHandoff")
            }
        )
        caption_context = load_context_json(parent.get("caption_outcome_context_json"))
        post_caption = self._instagram_post_caption_for_asset(parent, caption_context)
        base_burned = str(
            post_caption.get("burned_caption_text") or parent.get("caption") or ""
        ).strip()
        camp_id = parent.get("campaign_id", "")
        caption_family_id = f"cfam_{hashlib.sha256(f'{camp_id}:{parent_asset_id}:{style}'.encode()).hexdigest()[:12]}"
        caption_bank = (
            parent.get("caption_bank")
            or caption_context.get("caption_bank")
            or "unknown_caption_bank"
        )
        caption_source = f"existing_caption_bank:{caption_bank}"
        base_hashtags = self.caption_family_hashtags(post_caption.get("hashtags") or [])
        planned_versions = [
            self.planned_caption_version(
                caption_family_id=caption_family_id,
                parent=parent,
                concept=concept,
                index=index,
                angle=CAPTION_FAMILY_ANGLES[(index - 1) % len(CAPTION_FAMILY_ANGLES)],
                base_burned=base_burned,
                base_hashtags=base_hashtags,
                style=style,
                caption_source=caption_source,
            )
            for index in range(1, requested + 1)
        ]
        blocking: list[str] = []
        if not concept:
            blocking.append("parent_reel_not_registered")
        if not publishability.get("publishableCandidate"):
            blocking.append(
                str(
                    publishability.get("blockingReason")
                    or "parent_reel_not_publishable"
                )
            )
        if any(not version.get("burnedCaptionText") for version in planned_versions):
            blocking.append("blank_burned_caption")
        if any(not version.get("instagramPostCaption") for version in planned_versions):
            blocking.append("blank_instagram_post_caption")
        can_proceed = not blocking
        return {
            "schema": "campaign_factory.caption_family_plan.v1",
            "creator": creator,
            "parentAssetId": parent_asset_id,
            "parentReelId": concept.get("parentReelId")
            if concept
            else parent.get("parent_reel_id"),
            "conceptId": concept.get("conceptId")
            if concept
            else parent.get("concept_id"),
            "captionFamilyId": caption_family_id,
            "requestedCaptionVersions": requested,
            "style": style,
            "plannedVersions": planned_versions,
            "canProceed": can_proceed,
            "blockingReason": blocking[0] if blocking else "",
            "blockingReasons": blocking,
            "wouldWrite": False,
            "dryRun": bool(dry_run),
        }

    def caption_family_create(
        self,
        *,
        creator: str | None,
        parent_asset_id: str,
        requested_caption_versions: int = 5,
        style: str = "ig_short",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        plan = self.caption_family_plan(
            creator=creator,
            parent_asset_id=parent_asset_id,
            requested_caption_versions=requested_caption_versions,
            style=style,
            dry_run=True,
        )
        if dry_run or not plan.get("canProceed"):
            return {
                **plan,
                "schema": "campaign_factory.caption_family_create.v1",
                "createdCaptionVersions": 0,
                "wouldWrite": False,
            }
        parent = self._rendered_asset(parent_asset_id)
        now = self._utc_now()
        self.conn.execute(
            """
            INSERT INTO caption_families
            (id, campaign_id, concept_id, parent_reel_id, parent_asset_id, creator,
             requested_count, style, status, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            ON CONFLICT(parent_asset_id, style) DO UPDATE SET
              requested_count = MAX(requested_count, excluded.requested_count),
              status = 'active',
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                plan["captionFamilyId"],
                parent["campaign_id"],
                plan["conceptId"],
                plan["parentReelId"],
                parent_asset_id,
                creator,
                plan["requestedCaptionVersions"],
                style,
                json.dumps(
                    {"source": "caption_family_create", "dryRun": False},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
                now,
            ),
        )
        created = 0
        for version in plan["plannedVersions"]:
            self.conn.execute(
                """
                INSERT INTO caption_versions
                (id, caption_family_id, campaign_id, concept_id, parent_reel_id, parent_asset_id,
                 variant_family_id, caption_family_index, burned_caption_text, burned_caption_hash,
                 instagram_post_caption, instagram_post_caption_hash, caption_cta, hashtags_json,
                 post_caption_style, caption_angle, caption_source, status, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(caption_family_id, caption_family_index) DO UPDATE SET
                  burned_caption_text = excluded.burned_caption_text,
                  burned_caption_hash = excluded.burned_caption_hash,
                  instagram_post_caption = excluded.instagram_post_caption,
                  instagram_post_caption_hash = excluded.instagram_post_caption_hash,
                  caption_cta = excluded.caption_cta,
                  hashtags_json = excluded.hashtags_json,
                  post_caption_style = excluded.post_caption_style,
                  caption_angle = excluded.caption_angle,
                  caption_source = excluded.caption_source,
                  status = 'active',
                  metadata_json = excluded.metadata_json,
                  updated_at = excluded.updated_at
                """,
                (
                    version["captionVersionId"],
                    plan["captionFamilyId"],
                    parent["campaign_id"],
                    plan["conceptId"],
                    plan["parentReelId"],
                    parent_asset_id,
                    None,
                    version["captionFamilyIndex"],
                    version["burnedCaptionText"],
                    version["burnedCaptionHash"],
                    version["instagramPostCaption"],
                    version["instagramPostCaptionHash"],
                    version["captionCta"],
                    json.dumps(version["hashtags"], ensure_ascii=False, sort_keys=True),
                    version["postCaptionStyle"],
                    version["captionAngle"],
                    version["captionSource"],
                    json.dumps(
                        {
                            "wouldRender": False,
                            "wouldExport": False,
                            "wouldSchedule": False,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                    now,
                ),
            )
            created += 1
        self.conn.commit()
        return {
            **plan,
            "schema": "campaign_factory.caption_family_create.v1",
            "createdCaptionVersions": created,
            "wouldWrite": True,
            "dryRun": False,
        }

    def planned_caption_version(
        self,
        *,
        caption_family_id: str,
        parent: dict[str, Any],
        concept: dict[str, Any] | None,
        index: int,
        angle: str,
        base_burned: str,
        base_hashtags: list[str],
        style: str,
        caption_source: str,
    ) -> dict[str, Any]:
        if style == "blank_instagram_post_caption":
            burned_caption = base_burned
            instagram_caption = ""
            caption_cta = ""
            hashtags: list[str] = []
        else:
            burned_caption = (
                CAPTION_FAMILY_BURNED_TEMPLATES[angle].format(base=base_burned).strip()
            )
            instagram_base = (
                CAPTION_FAMILY_POST_TEMPLATES[angle].format(base=base_burned).strip()
            )
            caption_cta = CAPTION_FAMILY_CTA_BY_ANGLE[angle]
            hashtags = base_hashtags[:5]
            synthetic = {
                **parent,
                "caption": burned_caption,
                "captionGeneration": {
                    "instagram_post_caption": instagram_base,
                    "caption_cta": caption_cta,
                    "hashtags": hashtags,
                    "post_caption_style": style,
                },
            }
            normalized = self._instagram_post_caption_for_asset(
                synthetic, {"caption_text": burned_caption}
            )
            instagram_caption = str(
                normalized.get("instagram_post_caption") or ""
            ).strip()
            hashtags = list(normalized.get("hashtags") or [])[:5]
        burned_hash = self._text_hash(burned_caption) if burned_caption else ""
        instagram_hash = self._text_hash(instagram_caption) if instagram_caption else ""
        version_key = ":".join(
            str(part or "")
            for part in (caption_family_id, index, burned_hash, instagram_hash, angle)
        )
        return {
            "captionVersionId": f"cver_{hashlib.sha256(version_key.encode('utf-8')).hexdigest()[:12]}",
            "captionFamilyId": caption_family_id,
            "captionFamilyIndex": index,
            "parentAssetId": parent["id"],
            "parentReelId": concept.get("parentReelId")
            if concept
            else parent.get("parent_reel_id"),
            "burnedCaptionText": burned_caption,
            "burnedCaptionHash": burned_hash,
            "instagramPostCaption": instagram_caption,
            "instagramPostCaptionHash": instagram_hash,
            "captionCta": caption_cta or "",
            "hashtags": hashtags,
            "postCaptionStyle": style,
            "captionAngle": angle,
            "captionSource": caption_source,
            "wouldWrite": False,
        }

    def caption_family_hashtags(self, raw_tags: Any) -> list[str]:
        if not isinstance(raw_tags, list):
            return []
        hashtags: list[str] = []
        for tag in raw_tags:
            if not isinstance(tag, str):
                continue
            cleaned = re.sub(r"[^A-Za-z0-9_]", "", tag.strip().lstrip("#"))
            value = f"#{cleaned}" if cleaned else ""
            if value and value not in hashtags:
                hashtags.append(value)
            if len(hashtags) >= 5:
                break
        return hashtags

    def caption_version_by_id(
        self, caption_version_id: str | None
    ) -> dict[str, Any] | None:
        if not caption_version_id:
            return None
        row = self.conn.execute(
            "SELECT * FROM caption_versions WHERE id = ?", (caption_version_id,)
        ).fetchone()
        if not row:
            return None
        return self.caption_version_payload(row)

    def caption_version_payload(
        self, row: sqlite3.Row | dict[str, Any] | None
    ) -> dict[str, Any]:
        if row is None:
            return {}
        data = dict(row)
        return {
            "captionVersionId": data["id"],
            "captionFamilyId": data["caption_family_id"],
            "campaignId": data["campaign_id"],
            "conceptId": data["concept_id"],
            "parentReelId": data["parent_reel_id"],
            "parentAssetId": data["parent_asset_id"],
            "variantFamilyId": data.get("variant_family_id"),
            "captionFamilyIndex": data["caption_family_index"],
            "burnedCaptionText": data["burned_caption_text"],
            "burnedCaptionHash": data["burned_caption_hash"],
            "instagramPostCaption": data["instagram_post_caption"],
            "instagramPostCaptionHash": data["instagram_post_caption_hash"],
            "captionCta": data.get("caption_cta") or "",
            "hashtags": json_load(data.get("hashtags_json"), []),
            "postCaptionStyle": data.get("post_caption_style"),
            "captionAngle": data.get("caption_angle"),
            "captionSource": data.get("caption_source"),
            "status": data.get("status"),
            "metadata": json_load(data.get("metadata_json"), {}),
        }
