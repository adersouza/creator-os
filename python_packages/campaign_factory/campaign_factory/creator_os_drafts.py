from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

_PUBLISHABILITY_EXECUTION_BLOCKERS = {
    "missing_audio": "native_audio_proof_missing",
    "missing_burned_captions": "missing_burned_captions",
    "missing_caption_hash": "missing_caption_hash",
    "missing_caption_outcome_context": "missing_caption_outcome_context",
    "missing_content_fingerprint": "missing_content_fingerprint",
    "not_approved": "not_approved",
    "readiness_failed": "readiness_failed",
    "wrong_visual": "wrong_visual",
    "caption_placement_qc_failed": "caption_placement_qc_failed",
    "missing_instagram_post_caption": "missing_instagram_post_caption",
    "instagram_post_caption_quality_failed": "instagram_post_caption_quality_failed",
    "visual_qc_failed": "visual_qc_failed",
    "visual_qc_unavailable": "visual_qc_unavailable",
    "identity_verification_failed": "identity_verification_failed",
    "identity_verification_unavailable": "identity_verification_unavailable",
}


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
        multi_surface_inventory_audit: Callable[..., dict[str, Any]],
        creator_content_needs: Callable[..., dict[str, Any]],
        story_intent_report: Callable[..., dict[str, Any]],
        utc_now: Callable[[], str],
        content_surfaces: tuple[str, ...],
        creative_risk_block_threshold: int,
        default_story_calendar: dict[str, str],
    ) -> None:
        self._sanitize_for_storage = sanitize_for_storage
        self._normalize_content_surface = normalize_content_surface
        self._creator_label = creator_label
        self._truthy = truthy
        self._creator_os_numeric = creator_os_numeric
        self._surface_report_assets = surface_report_assets
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._multi_surface_inventory_audit = multi_surface_inventory_audit
        self._creator_content_needs = creator_content_needs
        self._story_intent_report = story_intent_report
        self._utc_now = utc_now
        self._content_surfaces = content_surfaces
        self._creative_risk_block_threshold = creative_risk_block_threshold
        self._default_story_calendar = default_story_calendar

    def creator_os_local_schedule_safe_assets(
        self, creator: str
    ) -> list[dict[str, Any]]:
        items = []
        for asset in self._surface_report_assets(creator=creator):
            readiness = self._surface_handoff_readiness_for_asset(asset)
            if not readiness.get("canHandoff"):
                continue
            items.append(
                {
                    "renderedAssetId": asset["id"],
                    "campaign": asset.get("campaign_slug"),
                    "contentSurface": readiness.get("contentSurface"),
                    "latestDistributionPlanId": (
                        readiness.get("handoffManifest", {}).get("distribution_plan_id")
                        if isinstance(readiness.get("handoffManifest"), dict)
                        else None
                    ),
                }
            )
        return items

    def creator_os_target_date(
        self, *, date: str | None = None, generated_at: str | None = None
    ) -> str:
        raw = (date or generated_at or "").strip()
        if raw:
            try:
                return (
                    datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    .date()
                    .isoformat()
                )
            except ValueError:
                return raw[:10]
        return (
            datetime.fromisoformat(self._utc_now().replace("Z", "+00:00"))
            .date()
            .isoformat()
        )

    def creator_os_account_surface_status(
        self, account: dict[str, Any], *, reel_needed: bool
    ) -> dict[str, dict[str, Any]]:
        status = {
            surface: {
                "needed": False,
                "scheduled": False,
                "completed": False,
                "blockedReason": "",
            }
            for surface in self._content_surfaces
        }
        raw_status = account.get("surfaceStatus")
        raw_needs = account.get("surfaceNeeds") or account.get("needsBySurface")
        if isinstance(raw_status, dict):
            for raw_surface, raw_value in raw_status.items():
                surface = self._normalize_content_surface(str(raw_surface))
                if surface not in status:
                    continue
                value = (
                    raw_value
                    if isinstance(raw_value, dict)
                    else {"needed": bool(raw_value)}
                )
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
                    needed = bool(
                        raw_value.get("needed")
                        or int(raw_value.get("remaining") or 0) > 0
                    )
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

    def creator_os_surface_summary_for_creator(
        self,
        *,
        creator: str,
        date: str,
        report: dict[str, Any],
        creator_accounts: list[dict[str, Any]],
        draft_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        inventory_report = self._multi_surface_inventory_audit(creator=creator)
        local_inventory = inventory_report.get("inventoryBySurface") or {}
        schedule_safe_drafts = self.creator_os_schedule_safe_drafts(
            creator, draft_items
        )
        thread_dash_inventory = {surface: 0 for surface in self._content_surfaces}
        for item in schedule_safe_drafts:
            surface = self._normalize_content_surface(
                str(
                    item.get("contentSurface")
                    or item.get("content_surface")
                    or item.get("surface")
                    or item.get("distributionSurface")
                    or "reel"
                )
            )
            if surface in thread_dash_inventory:
                thread_dash_inventory[surface] += 1

        needs_by_surface = {surface: 0 for surface in self._content_surfaces}
        try:
            needs_report = self._creator_content_needs(creator=creator, date=date)
        except Exception:
            needs_report = {}
        totals_by_surface = (
            needs_report.get("totalsBySurface")
            if isinstance(needs_report, dict)
            else None
        )
        has_requirement_data = (
            bool(needs_report.get("accountsAnalyzed"))
            if isinstance(needs_report, dict)
            else False
        )
        if isinstance(totals_by_surface, dict) and has_requirement_data:
            for surface in self._content_surfaces:
                needs_by_surface[surface] = int(
                    (totals_by_surface.get(surface) or {}).get("remaining") or 0
                )
        else:
            for account in creator_accounts:
                surface_status = (
                    account.get("surfaceNeeds")
                    if isinstance(account.get("surfaceNeeds"), dict)
                    else {}
                )
                for surface in self._content_surfaces:
                    if (surface_status.get(surface) or {}).get("needed"):
                        needs_by_surface[surface] += 1

        surface_inventory: dict[str, dict[str, int]] = {}
        surface_shortfalls: dict[str, dict[str, Any]] = {}
        surface_readiness: dict[str, dict[str, Any]] = {}
        for surface in self._content_surfaces:
            local = local_inventory.get(surface) or {}
            schedule_safe = int(thread_dash_inventory.get(surface) or 0)
            needed = int(needs_by_surface.get(surface) or 0)
            shortfall = max(0, needed - schedule_safe)
            surface_inventory[surface] = {
                "localTotal": int(local.get("total") or 0),
                "localScheduleSafe": int(local.get("scheduleSafe") or 0),
                "threadDashScheduleSafeDrafts": schedule_safe,
            }
            surface_shortfalls[surface] = {
                "needed": needed,
                "scheduleSafeDraftsAvailable": schedule_safe,
                "shortfall": shortfall,
            }
            surface_readiness[surface] = {
                "needed": needed,
                "scheduleSafeDraftsAvailable": schedule_safe,
                "ready": needed == 0 or schedule_safe >= needed,
                "blockedReason": "surface_inventory_shortfall" if shortfall else "",
                "wouldWrite": False,
            }
        return {
            "accountsNeedingReels": needs_by_surface["reel"],
            "accountsNeedingStories": needs_by_surface["story"],
            "accountsNeedingFeedSingles": needs_by_surface["feed_single"],
            "accountsNeedingCarousels": needs_by_surface["feed_carousel"],
            "surfaceInventory": surface_inventory,
            "surfaceShortfalls": surface_shortfalls,
            "surfaceScheduleReadiness": surface_readiness,
            "wouldWrite": False,
        }

    def creator_os_gap_blocking_reason(
        self, reason: str, blockers: list[str], item: dict[str, Any]
    ) -> str:
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

    def creator_os_draft_items(
        self, planner_inputs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for plan in planner_inputs:
            for raw in plan.get("items") or plan.get("inventory") or []:
                if not isinstance(raw, dict):
                    continue
                post_id = str(raw.get("postId") or raw.get("draftPostId") or "")
                key = post_id or json.dumps(
                    self._sanitize_for_storage(raw), sort_keys=True
                )
                if key in seen:
                    continue
                seen.add(key)
                items.append(dict(raw))
        return items

    def creator_os_draft_has_instagram_post_caption(
        self, draft: dict[str, Any]
    ) -> bool:
        explicit_keys = {
            "instagram_post_caption",
            "instagramPostCaption",
            "post_caption",
            "postCaption",
            "content",
        }
        metadata = (
            draft.get("metadata") if isinstance(draft.get("metadata"), dict) else {}
        )
        campaign_meta = (
            metadata.get("campaign_factory")
            if isinstance(metadata.get("campaign_factory"), dict)
            else {}
        )
        manifest = (
            campaign_meta.get("handoff_manifest")
            if isinstance(campaign_meta.get("handoff_manifest"), dict)
            else {}
        )
        containers = [draft, metadata, campaign_meta, manifest]
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in explicit_keys:
                if key in container and str(container.get(key) or "").strip():
                    return True
        return False

    def creator_os_inventory_for_creator(
        self,
        creator: str,
        planner_inputs: list[dict[str, Any]],
        draft_items: list[dict[str, Any]],
    ) -> dict[str, int]:
        matching_plans = [
            plan
            for plan in planner_inputs
            if self._creator_label(plan.get("creator")) == creator
            or not plan.get("creator")
        ]
        validated = 0
        for plan in matching_plans:
            validated = max(validated, int(plan.get("validatedDraftsAvailable") or 0))
        item_validated = sum(
            1
            for item in draft_items
            if item.get("qstashEligible") is True
            and self._creator_label(item.get("creator")) in {creator, "unknown"}
            and not self.creator_os_draft_exclusion_reason(item)
        )
        if draft_items:
            validated = item_validated
        elif not validated:
            validated = sum(
                1
                for item in draft_items
                if item.get("qstashEligible") is True
                and self._creator_label(item.get("creator")) in {creator, "unknown"}
                and not self.creator_os_draft_exclusion_reason(item)
            )
        variant = sum(
            1
            for item in draft_items
            if item.get("qstashEligible") is True
            and (item.get("variantId") or item.get("variantFamilyId"))
            and self._creator_label(item.get("creator")) in {creator, "unknown"}
            and not self.creator_os_draft_exclusion_reason(item)
        )
        return {
            "validatedDraftsAvailable": validated,
            "variantDraftsAvailable": variant,
        }

    def creator_os_blocked_account_breakdown(
        self, blocked_accounts: list[dict[str, Any]]
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for account in blocked_accounts:
            reason = str(account.get("blockedReason") or "blocked_unknown")
            counts[reason] = counts.get(reason, 0) + 1
        return dict(sorted(counts.items()))

    def creator_os_manager_decision(
        self,
        *,
        safe_accounts: int,
        needs_posts: int,
        validated_available: int,
        shortfall: int,
        missed_dispatches: list[dict[str, Any]],
        winner_recommendations: list[dict[str, Any]],
    ) -> dict[str, str]:
        if missed_dispatches:
            return {
                "managerDecision": "blocked",
                "managerReason": "missed_dispatches_must_be_resolved_before_new_scheduling",
            }
        if needs_posts and safe_accounts <= 0:
            return {
                "managerDecision": "blocked",
                "managerReason": "no_safe_accounts_available",
            }
        if needs_posts and shortfall <= 0 and validated_available >= needs_posts:
            return {
                "managerDecision": "ready_to_schedule",
                "managerReason": "enough_validated_drafts_and_safe_accounts_exist",
            }
        if shortfall > 0 and winner_recommendations:
            return {
                "managerDecision": "needs_variants",
                "managerReason": "validated_draft_inventory_short_and_winner_family_can_expand",
            }
        if shortfall > 0:
            return {
                "managerDecision": "needs_reel_factory_inventory",
                "managerReason": "validated_draft_inventory_short_and_no_winner_expansion_available",
            }
        return {
            "managerDecision": "ready_to_schedule" if needs_posts else "blocked",
            "managerReason": "no_accounts_need_posts_today"
            if not needs_posts
            else "ready",
        }

    def creator_os_account_state(
        self, account: dict[str, Any], blocked_reason: str
    ) -> str:
        if blocked_reason:
            return "blocked"
        raw = (
            str(account.get("accountState") or account.get("state") or "")
            .strip()
            .lower()
        )
        if raw in {"warming", "resting", "high-performing", "blocked"}:
            return raw
        bucket = str(account.get("bucket") or "").strip().lower()
        if bucket == "blocked_recent_failure":
            return "resting"
        if bucket.startswith("blocked_"):
            return "blocked"
        if bucket in {"safe_to_schedule_today", "already_scheduled_today"}:
            return "safe"
        if account.get("safeToSchedule") is False and not account.get(
            "nextScheduledPost"
        ):
            return "blocked"
        return "safe"

    def creator_os_post_time(self, value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        return str(
            value.get("scheduledFor")
            or value.get("scheduled_for")
            or value.get("publishedAt")
            or value.get("published_at")
            or ""
        )

    def creator_os_recommended_post_count(
        self, state: str, needs_post_today: bool
    ) -> int:
        if not needs_post_today:
            return 0
        if state == "high-performing":
            return 2
        if state in {"safe", "warming"}:
            return 1
        return 0

    def recommended_story_intent_for_date(
        self, target_date: str, *, creator: str | None = None
    ) -> str:
        if creator:
            try:
                intent_counts = (
                    self._story_intent_report(creator=creator).get("intentCounts") or {}
                )
            except Exception:
                intent_counts = {}
            if intent_counts:
                return sorted(
                    intent_counts.items(),
                    key=lambda item: (-int(item[1] or 0), str(item[0])),
                )[0][0]
        try:
            day_name = datetime.fromisoformat(target_date).strftime("%A")
        except ValueError:
            day_name = "Monday"
        return self._default_story_calendar.get(day_name, "casual_selfie")

    def recommended_story_style_for_intent(self, intent: str) -> str:
        return {
            "snapchat_promo": "casual_selfie",
            "reel_teaser": "raw_phone",
            "casual_selfie": "casual_selfie",
            "mirror_selfie": "mirror",
            "outfit_check": "mirror",
            "gym_selfie": "selfie",
            "bedroom_selfie": "selfie",
            "lifestyle": "lifestyle",
            "behind_the_scenes": "raw_phone",
            "engagement": "casual",
            "profile_visit": "casual",
        }.get(intent, "casual_selfie")

    def creator_os_draft_exclusion_reason(self, draft: dict[str, Any]) -> str:
        if not self.creator_os_draft_has_instagram_post_caption(draft):
            return "missingInstagramPostCaption"
        if draft.get("handoffManifestOk") is not True:
            return "missingHandoffManifest"
        if draft.get("platformDraftValidated") is not True:
            return "notPlatformDraftValidated"
        if self._truthy(
            draft.get("quarantined")
            or draft.get("assetQuarantined")
            or draft.get("campaignFactoryQuarantined")
        ):
            return "quarantined"
        publishability_state = str(
            draft.get("publishabilityState") or draft.get("assetState") or ""
        ).strip()
        if publishability_state not in {
            "exportable",
            "publishable_candidate",
            "platform_draft_validated",
        }:
            return "publishabilityFailed"
        cooldown_reason = str(draft.get("variantCooldownCheck") or "clear")
        if cooldown_reason and cooldown_reason != "clear":
            return "variantCooldownBlocked"
        return ""

    def creator_os_draft_exclusion_counts(
        self, creator: str, draft_items: list[dict[str, Any]]
    ) -> dict[str, int]:
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

    def creator_os_schedule_safe_drafts(
        self, creator: str, draft_items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            item
            for item in draft_items
            if self._creator_label(item.get("creator")) in {creator, "unknown"}
            and item.get("qstashEligible") is True
            and not self.creator_os_draft_exclusion_reason(item)
            and not self.creator_os_execution_draft_blockers(creator, [item])
        ]

    def creator_os_execution_draft_blockers(
        self, creator: str, draft_items: list[dict[str, Any]]
    ) -> list[str]:
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
            if not (
                item.get("renderedAssetId")
                or item.get("campaignFactoryAssetId")
                or item.get("campaign_factory_asset_id")
            ):
                blockers.add("missing_campaign_factory_asset_id")
            if not (
                item.get("distributionPlanId")
                or item.get("campaignFactoryDistributionPlanId")
                or item.get("campaign_factory_distribution_plan_id")
            ):
                blockers.add("missing_campaign_factory_distribution_plan_id")
            duplicate_reason = str(item.get("duplicateCheck") or "clear")
            if duplicate_reason and duplicate_reason != "clear":
                blockers.add("duplicate_schedule_risk")
            failure_reasons = {
                str(reason)
                for reason in item.get("publishability_failure_reasons")
                or item.get("publishabilityFailureReasons")
                or []
            }
            blockers.update(
                _PUBLISHABILITY_EXECUTION_BLOCKERS[reason]
                for reason in failure_reasons
                if reason in _PUBLISHABILITY_EXECUTION_BLOCKERS
            )
            if self.creator_os_explicit_false(
                item,
                "burnedCaptionTextPresent",
                "burned_caption_text_present",
                "burnedCaptionPresent",
            ):
                blockers.add("missing_burned_caption_text")
            placement_status = str(
                item.get("captionPlacementQcStatus")
                or item.get("captionPlacementStatus")
                or item.get("caption_placement_qc_status")
                or ""
            ).lower()
            if placement_status and placement_status not in {"passed", "pass", "ok"}:
                blockers.add("caption_placement_qc_failed")
            post_caption_quality = item.get("instagramPostCaptionQuality") or item.get(
                "instagram_post_caption_quality"
            )
            if (
                isinstance(post_caption_quality, dict)
                and post_caption_quality.get("passed") is False
            ) or self.creator_os_explicit_false(
                item,
                "instagramPostCaptionQualityPassed",
                "instagram_post_caption_quality_passed",
            ):
                blockers.add("instagram_post_caption_quality_failed")
            audio_status = str(
                item.get("audioValidity")
                or item.get("audio_validity")
                or item.get("audioStatus")
                or item.get("audio_status")
                or ""
            ).lower()
            audio_proof_status = str(
                item.get("nativeAudioProofStatus")
                or item.get("audioProofStatus")
                or item.get("native_audio_proof_status")
                or item.get("audio_proof_status")
                or ""
            ).lower()
            if audio_status in {"failed", "invalid", "mismatch"}:
                blockers.add("embedded_audio_invalid")
            elif audio_proof_status in {
                "missing",
                "unverified",
                "pending",
                "failed",
            } or (
                audio_status in {"selected", "recommended", "missing"}
                and audio_proof_status
                not in {"attached", "ok", "pass", "passed", "valid", "verified"}
            ):
                blockers.add("native_audio_proof_missing")
            creative_risk = int(
                self._creator_os_numeric(
                    item.get("creativeRiskScore")
                    or item.get("creative_risk_score")
                    or (
                        (item.get("creativeRisk") or {}).get("score")
                        if isinstance(item.get("creativeRisk"), dict)
                        else 0
                    )
                )
            )
            if creative_risk >= self._creative_risk_block_threshold:
                blockers.add("creative_risk_score_exceeded")
            budget = (
                item.get("similarityBudget")
                if isinstance(item.get("similarityBudget"), dict)
                else {}
            )
            if (
                budget.get("blocked")
                or item.get("similarityBudgetExceeded")
                or item.get("similarity_budget_exceeded")
            ):
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
