from __future__ import annotations

import json
from typing import Any, Callable


class CreatorOSDraftRepository:
    def __init__(
        self,
        *,
        sanitize_for_storage: Callable[[Any], Any],
        normalize_content_surface: Callable[[str | None], str],
        creator_label: Callable[[Any], str],
        truthy: Callable[[Any], bool],
        creator_os_numeric: Callable[[Any], float],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        content_surfaces: tuple[str, ...],
        creative_risk_block_threshold: int,
    ) -> None:
        self._sanitize_for_storage = sanitize_for_storage
        self._normalize_content_surface = normalize_content_surface
        self._creator_label = creator_label
        self._truthy = truthy
        self._creator_os_numeric = creator_os_numeric
        self._surface_report_assets = surface_report_assets
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._content_surfaces = content_surfaces
        self._creative_risk_block_threshold = creative_risk_block_threshold

    def creator_os_local_schedule_safe_assets(self, creator: str) -> list[dict[str, Any]]:
        items = []
        for asset in self._surface_report_assets(creator=creator):
            readiness = self._surface_handoff_readiness_for_asset(asset)
            if not readiness.get("canHandoff"):
                continue
            items.append({
                "renderedAssetId": asset["id"],
                "campaign": asset.get("campaign_slug"),
                "contentSurface": readiness.get("contentSurface"),
                "latestDistributionPlanId": (
                    readiness.get("handoffManifest", {}).get("distribution_plan_id")
                    if isinstance(readiness.get("handoffManifest"), dict)
                    else None
                ),
            })
        return items

    def creator_os_account_surface_status(self, account: dict[str, Any], *, reel_needed: bool) -> dict[str, dict[str, Any]]:
        status = {
            surface: {"needed": False, "scheduled": False, "completed": False, "blockedReason": ""}
            for surface in self._content_surfaces
        }
        raw_status = account.get("surfaceStatus")
        raw_needs = account.get("surfaceNeeds") or account.get("needsBySurface")
        if isinstance(raw_status, dict):
            for raw_surface, raw_value in raw_status.items():
                surface = self._normalize_content_surface(str(raw_surface))
                if surface not in status:
                    continue
                value = raw_value if isinstance(raw_value, dict) else {"needed": bool(raw_value)}
                status[surface] = {
                    "needed": bool(value.get("needed")),
                    "scheduled": bool(value.get("scheduled")),
                    "completed": bool(value.get("completed")),
                    "blockedReason": str(value.get("blockedReason") or ""),
                }
            return status
        if isinstance(raw_needs, dict):
            for raw_surface, raw_value in raw_needs.items():
                surface = self._normalize_content_surface(str(raw_surface))
                if surface not in status:
                    continue
                if isinstance(raw_value, dict):
                    needed = bool(raw_value.get("needed") or int(raw_value.get("remaining") or 0) > 0)
                    blocked = str(raw_value.get("blockedReason") or "")
                else:
                    try:
                        needed = int(raw_value or 0) > 0
                    except (TypeError, ValueError):
                        needed = bool(raw_value)
                    blocked = ""
                status[surface]["needed"] = needed
                status[surface]["blockedReason"] = blocked
            return status
        status["reel"]["needed"] = bool(reel_needed)
        return status

    def creator_os_gap_blocking_reason(self, reason: str, blockers: list[str], item: dict[str, Any]) -> str:
        if reason == "missingInstagramPostCaption":
            return "missing_instagram_post_caption"
        if reason == "missingHandoffManifest":
            return "missing_handoff_manifest"
        if reason == "notPlatformDraftValidated":
            return "platform_draft_not_validated"
        if reason == "quarantined":
            return "quarantined"
        if reason == "publishabilityFailed":
            return "publishability_failed"
        if reason == "variantCooldownBlocked":
            return str(item.get("variantCooldownCheck") or "variant_cooldown_blocked")
        duplicate = str(item.get("duplicateCheck") or "clear")
        if duplicate and duplicate != "clear":
            return duplicate
        if blockers:
            return blockers[0]
        if item.get("qstashEligible") is not True:
            return "not_qstash_eligible"
        return "unknown_not_schedule_safe"

    def creator_os_draft_items(self, planner_inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for plan in planner_inputs:
            for raw in plan.get("items") or plan.get("inventory") or []:
                if not isinstance(raw, dict):
                    continue
                post_id = str(raw.get("postId") or raw.get("draftPostId") or "")
                key = post_id or json.dumps(self._sanitize_for_storage(raw), sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                items.append(dict(raw))
        return items

    def creator_os_draft_has_instagram_post_caption(self, draft: dict[str, Any]) -> bool:
        explicit_keys = {
            "instagram_post_caption",
            "instagramPostCaption",
            "post_caption",
            "postCaption",
            "content",
        }
        metadata = draft.get("metadata") if isinstance(draft.get("metadata"), dict) else {}
        campaign_meta = metadata.get("campaign_factory") if isinstance(metadata.get("campaign_factory"), dict) else {}
        manifest = campaign_meta.get("handoff_manifest") if isinstance(campaign_meta.get("handoff_manifest"), dict) else {}
        containers = [draft, metadata, campaign_meta, manifest]
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in explicit_keys:
                if key in container and str(container.get(key) or "").strip():
                    return True
        return False

    def creator_os_draft_exclusion_reason(self, draft: dict[str, Any]) -> str:
        if not self.creator_os_draft_has_instagram_post_caption(draft):
            return "missingInstagramPostCaption"
        if draft.get("handoffManifestOk") is not True:
            return "missingHandoffManifest"
        if draft.get("platformDraftValidated") is not True:
            return "notPlatformDraftValidated"
        if self._truthy(draft.get("quarantined") or draft.get("assetQuarantined") or draft.get("campaignFactoryQuarantined")):
            return "quarantined"
        publishability_state = str(draft.get("publishabilityState") or draft.get("assetState") or "").strip()
        if publishability_state not in {"exportable", "publishable_candidate", "platform_draft_validated"}:
            return "publishabilityFailed"
        cooldown_reason = str(draft.get("variantCooldownCheck") or "clear")
        if cooldown_reason and cooldown_reason != "clear":
            return "variantCooldownBlocked"
        return ""

    def creator_os_draft_exclusion_counts(self, creator: str, draft_items: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            "missingInstagramPostCaption": 0,
            "missingHandoffManifest": 0,
            "notPlatformDraftValidated": 0,
            "quarantined": 0,
            "publishabilityFailed": 0,
            "variantCooldownBlocked": 0,
        }
        for item in draft_items:
            if self._creator_label(item.get("creator")) not in {creator, "unknown"}:
                continue
            reason = self.creator_os_draft_exclusion_reason(item)
            if reason in counts:
                counts[reason] += 1
        return counts

    def creator_os_schedule_safe_drafts(self, creator: str, draft_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            item
            for item in draft_items
            if self._creator_label(item.get("creator")) in {creator, "unknown"}
            and item.get("qstashEligible") is True
            and not self.creator_os_draft_exclusion_reason(item)
            and not self.creator_os_execution_draft_blockers(creator, [item])
        ]

    def creator_os_execution_draft_blockers(self, creator: str, draft_items: list[dict[str, Any]]) -> list[str]:
        blockers: set[str] = set()
        for item in draft_items:
            if self._creator_label(item.get("creator")) not in {creator, "unknown"}:
                continue
            reason = self.creator_os_draft_exclusion_reason(item)
            if reason == "missingInstagramPostCaption":
                blockers.add("missing_instagram_post_caption")
            elif reason == "missingHandoffManifest":
                blockers.add("missing_handoff_manifest")
            elif reason == "notPlatformDraftValidated":
                blockers.add("platform_draft_not_validated")
            elif reason == "quarantined":
                blockers.add("quarantined_draft_present")
            elif reason == "publishabilityFailed":
                blockers.add("publishability_failed_draft_present")
            elif reason == "variantCooldownBlocked":
                blockers.add("variant_cooldown_violation")
            if not (item.get("renderedAssetId") or item.get("campaignFactoryAssetId") or item.get("campaign_factory_asset_id")):
                blockers.add("missing_campaign_factory_asset_id")
            if not (item.get("distributionPlanId") or item.get("campaignFactoryDistributionPlanId") or item.get("campaign_factory_distribution_plan_id")):
                blockers.add("missing_campaign_factory_distribution_plan_id")
            duplicate_reason = str(item.get("duplicateCheck") or "clear")
            if duplicate_reason and duplicate_reason != "clear":
                blockers.add("duplicate_schedule_risk")
            if self.creator_os_explicit_false(item, "burnedCaptionTextPresent", "burned_caption_text_present", "burnedCaptionPresent"):
                blockers.add("missing_burned_caption_text")
            placement_status = str(item.get("captionPlacementQcStatus") or item.get("captionPlacementStatus") or item.get("caption_placement_qc_status") or "").lower()
            if placement_status and placement_status not in {"passed", "pass", "ok"}:
                blockers.add("caption_placement_qc_failed")
            audio_status = str(item.get("audioValidity") or item.get("audio_validity") or item.get("audioStatus") or "").lower()
            if audio_status in {"failed", "invalid", "mismatch"}:
                blockers.add("embedded_audio_invalid")
            creative_risk = int(self._creator_os_numeric(item.get("creativeRiskScore") or item.get("creative_risk_score") or ((item.get("creativeRisk") or {}).get("score") if isinstance(item.get("creativeRisk"), dict) else 0)))
            if creative_risk >= self._creative_risk_block_threshold:
                blockers.add("creative_risk_score_exceeded")
            budget = item.get("similarityBudget") if isinstance(item.get("similarityBudget"), dict) else {}
            if budget.get("blocked") or item.get("similarityBudgetExceeded") or item.get("similarity_budget_exceeded"):
                blockers.add("similarity_budget_exceeded")
        return sorted(blockers)

    def creator_os_explicit_false(self, item: dict[str, Any], *keys: str) -> bool:
        for key in keys:
            if key not in item:
                continue
            value = item.get(key)
            if isinstance(value, bool):
                return value is False
            if str(value).strip().lower() in {"0", "false", "no"}:
                return True
        return False
