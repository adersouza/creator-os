from __future__ import annotations

import re
from typing import Any

from .persistence import json_load

AI_DISCLOSURE_POLICY = "creator_os.ai_generated_media_disclosure.v1"
AI_DISCLOSURE_TEXT = "AI-generated media."
AI_DISCLOSURE_BLOCKER = "ai_generated_media_disclosure_required"


class AiDisclosurePublishabilityMixin:
    @staticmethod
    def _caption_discloses_ai(caption: str) -> bool:
        return bool(
            re.search(
                r"\b(?:ai[- ]generated|generated (?:with|by) ai|"
                r"made (?:with|by) ai|synthetic media)\b",
                caption,
                re.IGNORECASE,
            )
        )

    def ai_disclosure_requirement(self, asset: dict[str, Any]) -> dict[str, Any]:
        metadata = asset.get("metadata")
        if not isinstance(metadata, dict):
            metadata = json_load(asset.get("metadata_json"), {})
        metadata = metadata if isinstance(metadata, dict) else {}
        worker = metadata.get("worker")
        worker = worker if isinstance(worker, dict) else {}
        result = worker.get("result")
        result = result if isinstance(result, dict) else {}
        publishability = metadata.get("publishability")
        publishability = publishability if isinstance(publishability, dict) else {}
        blockers = publishability.get("blockingIssues")
        blockers = blockers if isinstance(blockers, list) else []
        sources: list[str] = []
        if metadata.get("aiDisclosureRequired") is True:
            sources.append("motion_generation_asset")
        if result.get("aiDisclosureRequired") is True:
            sources.append("worker_result")
        if AI_DISCLOSURE_BLOCKER in blockers:
            sources.append("publishability_blocker")
        return {
            "required": bool(sources),
            "policy": AI_DISCLOSURE_POLICY,
            "requirementSources": sorted(set(sources)),
            "requiredText": AI_DISCLOSURE_TEXT if sources else None,
        }

    def append_ai_disclosure(
        self, caption: str, asset: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        requirement = self.ai_disclosure_requirement(asset)
        appended = requirement["required"] and not self._caption_discloses_ai(caption)
        if appended:
            caption = f"{caption}\n{AI_DISCLOSURE_TEXT}".strip()
        return caption, {
            "ai_disclosure_required": requirement["required"],
            "ai_disclosure_policy": AI_DISCLOSURE_POLICY,
            "ai_disclosure_text": AI_DISCLOSURE_TEXT
            if requirement["required"]
            else None,
            "ai_disclosure_appended": appended,
        }

    def ai_disclosure_status(
        self,
        *,
        asset: dict[str, Any],
        post_caption: dict[str, Any],
        creative_approval: dict[str, Any],
    ) -> dict[str, Any]:
        requirement = self.ai_disclosure_requirement(asset)
        if not requirement["required"]:
            return {**requirement, "state": "not_required", "resolved": True}
        caption = str(post_caption.get("instagram_post_caption") or "").strip()
        caption_hash = post_caption.get("instagram_post_caption_hash")
        if not self._caption_discloses_ai(caption):
            return {
                **requirement,
                "state": "disclosure_text_missing",
                "resolved": False,
            }
        if creative_approval.get("state") != "approved":
            return {
                **requirement,
                "state": "awaiting_creative_approval_v2",
                "resolved": False,
                "captionHash": caption_hash,
            }
        approval = creative_approval.get("approval")
        approval = approval if isinstance(approval, dict) else {}
        semantics = approval.get("contentSemantics")
        semantics = semantics if isinstance(semantics, dict) else {}
        projection = approval.get("exportProjection")
        projection = projection if isinstance(projection, dict) else {}
        if (
            semantics.get("instagramPostCaption") != caption
            or projection.get("instagramPostCaptionHash") != caption_hash
        ):
            return {
                **requirement,
                "state": "creative_approval_disclosure_binding_mismatch",
                "resolved": False,
                "captionHash": caption_hash,
            }
        return {
            **requirement,
            "state": "resolved_by_creative_approval_v2",
            "resolved": True,
            "method": "instagram_post_caption",
            "captionHash": caption_hash,
            "approvalId": approval.get("approvalId"),
            "approvalFingerprint": approval.get("approvalFingerprint"),
        }
