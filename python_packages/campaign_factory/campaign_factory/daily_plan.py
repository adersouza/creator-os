from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any


class DailyPlanRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_label: Callable[[Any], str],
        creator_os_target_date: Callable[..., str],
        creator_os_draft_items: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        creator_os_account_health_report: Callable[..., dict[str, Any]],
        creator_os_account_health_decision: Callable[..., dict[str, Any]],
        creator_os_tier_posting_guidance: Callable[[str], dict[str, Any]],
        creator_os_account_surface_status: Callable[..., dict[str, Any]],
        creator_os_draft_exclusion_reason: Callable[[dict[str, Any]], str | None],
        creator_os_draft_has_instagram_post_caption: Callable[[dict[str, Any]], bool],
        creator_os_post_time: Callable[[Any], str | None],
        creator_os_recommended_post_count: Callable[[str, bool], int],
        creator_os_account_tier_summary: Callable[
            [list[dict[str, Any]]], dict[str, Any]
        ],
        creator_os_account_health_summary: Callable[
            [list[dict[str, Any]]], dict[str, Any]
        ],
        creator_os_surface_summary_for_creator: Callable[..., dict[str, Any]],
        creator_os_inventory_for_creator: Callable[..., dict[str, Any]],
        creator_os_draft_exclusion_counts: Callable[
            [str, list[dict[str, Any]]], dict[str, int]
        ],
        creator_os_winner_recommendations: Callable[..., list[dict[str, Any]]],
        creator_os_manager_decision: Callable[..., dict[str, Any]],
        creator_os_blocked_account_breakdown: Callable[
            [list[dict[str, Any]]], dict[str, int]
        ],
        recommended_story_intent_for_date: Callable[..., str],
        creator_os_recommended_inventory: Callable[..., list[dict[str, Any]]],
        recommended_story_style_for_intent: Callable[[str], str],
        creator_os_draft_inventory_gap: Callable[..., dict[str, Any]],
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self._creator_label = creator_label
        self._creator_os_target_date = creator_os_target_date
        self._creator_os_draft_items = creator_os_draft_items
        self._creator_os_account_health_report = creator_os_account_health_report
        self._creator_os_account_health_decision = creator_os_account_health_decision
        self._creator_os_tier_posting_guidance = creator_os_tier_posting_guidance
        self._creator_os_account_surface_status = creator_os_account_surface_status
        self._creator_os_draft_exclusion_reason = creator_os_draft_exclusion_reason
        self._creator_os_draft_has_instagram_post_caption = (
            creator_os_draft_has_instagram_post_caption
        )
        self._creator_os_post_time = creator_os_post_time
        self._creator_os_recommended_post_count = creator_os_recommended_post_count
        self._creator_os_account_tier_summary = creator_os_account_tier_summary
        self._creator_os_account_health_summary = creator_os_account_health_summary
        self._creator_os_surface_summary_for_creator = (
            creator_os_surface_summary_for_creator
        )
        self._creator_os_inventory_for_creator = creator_os_inventory_for_creator
        self._creator_os_draft_exclusion_counts = creator_os_draft_exclusion_counts
        self._creator_os_winner_recommendations = creator_os_winner_recommendations
        self._creator_os_manager_decision = creator_os_manager_decision
        self._creator_os_blocked_account_breakdown = (
            creator_os_blocked_account_breakdown
        )
        self._recommended_story_intent_for_date = recommended_story_intent_for_date
        self._creator_os_recommended_inventory = creator_os_recommended_inventory
        self._recommended_story_style_for_intent = recommended_story_style_for_intent
        self._creator_os_draft_inventory_gap = creator_os_draft_inventory_gap
        self._utc_now = utc_now

    def creator_os_daily_plan(
        self,
        *,
        creators: list[str] | None = None,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        winner_expansion_report: dict[str, Any] | None = None,
        winner_expansion_plan: dict[str, Any] | None = None,
        variant_metrics_rollup: dict[str, Any] | None = None,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        report = threadsdash_report or {}
        target_date = self._creator_os_target_date(date=date, generated_at=generated_at)
        accounts = [
            dict(item)
            for item in report.get("accounts") or []
            if isinstance(item, dict)
        ]
        missed_dispatches = [
            dict(item)
            for item in report.get("missedDispatches") or []
            if isinstance(item, dict)
        ]
        planner_inputs = [
            item for item in (time_plan, schedule_plan) if isinstance(item, dict)
        ]
        requested_creators = [
            self._creator_label(item)
            for item in (creators or [])
            if str(item or "").strip()
        ]
        if not requested_creators:
            requested_creators = sorted(
                {
                    self._creator_label(account.get("creator"))
                    for account in accounts
                    if account.get("creator")
                }
            ) or ["unknown"]

        missed_by_account: dict[str, list[dict[str, Any]]] = {}
        for missed in missed_dispatches:
            account_id = str(
                missed.get("accountId")
                or missed.get("instagramAccountId")
                or missed.get("instagram_account_id")
                or ""
            ).strip()
            if account_id:
                missed_by_account.setdefault(account_id, []).append(missed)

        draft_items = self._creator_os_draft_items(planner_inputs)
        health_report_by_creator = {
            creator: self._creator_os_account_health_report(
                creator=creator,
                threadsdash_report=report,
                generated_at=generated_at,
            )
            for creator in requested_creators
        }
        health_by_account = {
            str(row.get("accountId") or ""): row
            for health_report in health_report_by_creator.values()
            for row in health_report.get("accounts") or []
            if isinstance(row, dict)
        }
        account_rows = []
        for account in accounts:
            account_id = str(
                account.get("accountId")
                or account.get("id")
                or account.get("instagramAccountId")
                or ""
            ).strip()
            creator = self._creator_label(account.get("creator"))
            health = health_by_account.get(
                account_id
            ) or self._creator_os_account_health_decision(
                account, missed=missed_by_account.get(account_id, [])
            )
            blocked_reason = str(health.get("blockedReason") or "")
            state = str(health.get("state") or "safe")
            account_tier = str(health.get("accountTier") or "normal")
            tier_guidance = (
                health.get("postingGuidance")
                if isinstance(health.get("postingGuidance"), dict)
                else self._creator_os_tier_posting_guidance(account_tier)
            )
            needs_post_today = (
                bool(account.get("needsPostToday"))
                and state != "blocked"
                and not account.get("nextScheduledPost")
            )
            surface_needs = self._creator_os_account_surface_status(
                account, reel_needed=needs_post_today
            )
            eligible_drafts = []
            cooldowns = []
            draft_exclusions = []
            for draft in draft_items:
                if str(draft.get("accountId") or "") != account_id:
                    continue
                cooldown_reason = str(draft.get("variantCooldownCheck") or "clear")
                duplicate_reason = str(draft.get("duplicateCheck") or "clear")
                exclusion_reason = self._creator_os_draft_exclusion_reason(draft)
                draft_payload = {
                    "draftPostId": draft.get("postId") or draft.get("draftPostId"),
                    "renderedAssetId": draft.get("renderedAssetId"),
                    "distributionPlanId": draft.get("distributionPlanId"),
                    "variantFamilyId": draft.get("variantFamilyId"),
                    "variantId": draft.get("variantId"),
                    "scheduledFor": draft.get("scheduledFor"),
                    "qstashEligible": bool(draft.get("qstashEligible")),
                    "instagramPostCaptionPresent": self._creator_os_draft_has_instagram_post_caption(
                        draft
                    ),
                    "duplicateCheck": duplicate_reason,
                    "variantCooldownCheck": cooldown_reason,
                    "wouldWrite": False,
                }
                if exclusion_reason == "variantCooldownBlocked":
                    cooldowns.append(
                        {
                            "draftPostId": draft_payload["draftPostId"],
                            "variantFamilyId": draft_payload["variantFamilyId"],
                            "variantId": draft_payload["variantId"],
                            "reason": cooldown_reason,
                        }
                    )
                    continue
                if exclusion_reason:
                    draft_exclusions.append(
                        {
                            "draftPostId": draft_payload["draftPostId"],
                            "renderedAssetId": draft_payload["renderedAssetId"],
                            "distributionPlanId": draft_payload["distributionPlanId"],
                            "reason": exclusion_reason,
                        }
                    )
                    if exclusion_reason == "missingInstagramPostCaption":
                        cooldowns.append(
                            {
                                "draftPostId": draft_payload["draftPostId"],
                                "variantFamilyId": draft_payload["variantFamilyId"],
                                "variantId": draft_payload["variantId"],
                                "reason": "missing_instagram_post_caption",
                            }
                        )
                    continue
                if duplicate_reason and duplicate_reason != "clear":
                    continue
                if draft.get("qstashEligible") is True and state != "blocked":
                    eligible_drafts.append(draft_payload)
            account_rows.append(
                {
                    "accountId": account_id,
                    "username": account.get("username"),
                    "creator": creator,
                    "state": state,
                    "accountTier": account_tier,
                    "tierPostingGuidance": tier_guidance,
                    "needsPostToday": needs_post_today,
                    "lastPublishedAt": self._creator_os_post_time(
                        account.get("lastPublishedPost")
                    ),
                    "nextScheduledAt": self._creator_os_post_time(
                        account.get("nextScheduledPost")
                    ),
                    "blockedReason": blocked_reason,
                    "recommendedPostCount": self._creator_os_recommended_post_count(
                        state, needs_post_today
                    ),
                    "accountHealth": health,
                    "accountTrustState": health.get("accountTrustState"),
                    "recommendationEligibilityState": health.get(
                        "recommendationEligibilityState"
                    ),
                    "accountMaturityScore": health.get("accountMaturityScore"),
                    "warmingStage": health.get("warmingStage"),
                    "creativeRiskScore": health.get("creativeRiskScore"),
                    "similarityBudget": health.get("similarityBudget"),
                    "surfaceNeeds": surface_needs,
                    "eligibleDrafts": eligible_drafts,
                    "draftExclusions": draft_exclusions,
                    "variantCooldowns": cooldowns,
                    "wouldWrite": False,
                }
            )

        creator_rows = []
        for creator in requested_creators:
            creator_accounts = [
                row
                for row in account_rows
                if self._creator_label(row.get("creator")) == creator
            ]
            safe_accounts = [
                row
                for row in creator_accounts
                if row["state"] in {"safe", "warming", "high-performing"}
            ]
            blocked_accounts = [
                row for row in creator_accounts if row["state"] == "blocked"
            ]
            needing = [row for row in creator_accounts if row["needsPostToday"]]
            tier_summary = self._creator_os_account_tier_summary(creator_accounts)
            account_health_report = health_report_by_creator.get(creator) or {
                "summary": self._creator_os_account_health_summary(
                    [
                        row.get("accountHealth")
                        for row in creator_accounts
                        if isinstance(row.get("accountHealth"), dict)
                    ]
                ),
                "accounts": [
                    row.get("accountHealth")
                    for row in creator_accounts
                    if isinstance(row.get("accountHealth"), dict)
                ],
            }
            account_health_summary = account_health_report.get("summary") or {}
            surface_summary = self._creator_os_surface_summary_for_creator(
                creator=creator,
                date=target_date,
                report=report,
                creator_accounts=creator_accounts,
                draft_items=draft_items,
            )
            plan_inventory = self._creator_os_inventory_for_creator(
                creator, planner_inputs, draft_items
            )
            validated_available = plan_inventory["validatedDraftsAvailable"]
            variant_available = plan_inventory["variantDraftsAvailable"]
            draft_exclusions = self._creator_os_draft_exclusion_counts(
                creator, draft_items
            )
            shortfall = max(0, len(needing) - validated_available)
            winner_recommendations = self._creator_os_winner_recommendations(
                creator=creator,
                inventory_shortfall=shortfall,
                variant_available=variant_available,
                winner_expansion_report=winner_expansion_report,
                winner_expansion_plan=winner_expansion_plan,
                variant_metrics_rollup=variant_metrics_rollup,
            )
            manager_decision = self._creator_os_manager_decision(
                safe_accounts=len(safe_accounts),
                needs_posts=len(needing),
                validated_available=validated_available,
                shortfall=shortfall,
                missed_dispatches=missed_dispatches,
                winner_recommendations=winner_recommendations,
            )
            actions = []
            if missed_dispatches:
                actions.append("resolve_missed_dispatches_before_scheduling")
            if shortfall:
                if variant_available:
                    actions.append("fanout_existing_unused_variants")
                if winner_recommendations:
                    actions.extend(
                        [
                            "run_contentforge_variant_plan",
                            "review_variant_pack",
                            "register_recommended_variants",
                            "export_validated_drafts",
                            "rerun_campaign_schedule_plan",
                        ]
                    )
                else:
                    actions.append("create_reel_factory_or_source_inventory")
            if not shortfall and needing:
                actions.append("run_campaign_schedule_time_plan_then_campaign_schedule")
            if not needing and not blocked_accounts:
                actions.append("observe_metrics_and_inventory")
            story_inventory_available = (
                surface_summary["surfaceInventory"]["story"][
                    "threadDashScheduleSafeDrafts"
                ]
                or surface_summary["surfaceInventory"]["story"]["localScheduleSafe"]
            )
            story_inventory_shortfall = max(
                0, surface_summary["accountsNeedingStories"] - story_inventory_available
            )
            recommended_story_intent = self._recommended_story_intent_for_date(
                target_date, creator=creator
            )
            recommended_inventory = self._creator_os_recommended_inventory(
                creator=creator
            )
            creator_rows.append(
                {
                    "creator": creator,
                    "safeAccounts": len(safe_accounts),
                    "blockedAccounts": len(blocked_accounts),
                    "accountTierSummary": tier_summary,
                    "accountHealthSummary": account_health_summary,
                    "recommendationEligibilitySummary": account_health_summary.get(
                        "recommendationEligibilitySummary"
                    )
                    or {},
                    "restrictedAccounts": int(
                        account_health_summary.get("restrictedAccounts") or 0
                    ),
                    "manualReviewAccounts": int(
                        account_health_summary.get("manualReviewAccounts") or 0
                    ),
                    "maturityDistribution": account_health_summary.get(
                        "maturityDistribution"
                    )
                    or {},
                    "creativeRiskDistribution": account_health_summary.get(
                        "creativeRiskDistribution"
                    )
                    or {},
                    "similarityBudgetWarnings": account_health_summary.get(
                        "similarityBudgetWarnings"
                    )
                    or [],
                    "accountsNeedingPostsToday": len(needing),
                    "accountsNeedingReels": surface_summary["accountsNeedingReels"],
                    "accountsNeedingStories": surface_summary["accountsNeedingStories"],
                    "accountsNeedingFeedSingles": surface_summary[
                        "accountsNeedingFeedSingles"
                    ],
                    "accountsNeedingCarousels": surface_summary[
                        "accountsNeedingCarousels"
                    ],
                    "surfaceInventory": surface_summary["surfaceInventory"],
                    "surfaceShortfalls": surface_summary["surfaceShortfalls"],
                    "surfaceScheduleReadiness": surface_summary[
                        "surfaceScheduleReadiness"
                    ],
                    "storyInventoryAvailable": story_inventory_available,
                    "storyInventoryShortfall": story_inventory_shortfall,
                    "storyScheduleReadiness": "ready"
                    if story_inventory_shortfall == 0
                    else "blocked",
                    "recommendedStoryIntent": recommended_story_intent,
                    "recommendedStoryStyle": self._recommended_story_style_for_intent(
                        recommended_story_intent
                    ),
                    "recommendedInventory": recommended_inventory,
                    "creativeLearningReadiness": "ready"
                    if recommended_inventory
                    else "insufficient_data",
                    "validatedDraftsAvailable": validated_available,
                    "scheduleSafeDraftsAvailable": validated_available,
                    "variantDraftsAvailable": variant_available,
                    "inventoryShortfall": shortfall,
                    "draftsExcluded": draft_exclusions,
                    "blockedAccountBreakdown": self._creator_os_blocked_account_breakdown(
                        blocked_accounts
                    ),
                    "winnerExpansionRecommendations": winner_recommendations,
                    "nextSafeActions": actions,
                    "managerDecision": manager_decision["managerDecision"],
                    "managerReason": manager_decision["managerReason"],
                    "recommendedActions": actions,
                    "draftInventoryGap": self._creator_os_draft_inventory_gap(
                        creator=creator,
                        threadsdash_report=report,
                        schedule_plan=schedule_plan,
                        time_plan=time_plan,
                        generated_at=generated_at,
                    ),
                    "wouldWrite": False,
                }
            )

        return {
            "schema": "creator_os.daily_plan.v1",
            "generatedAt": generated_at or self._utc_now(),
            "surfaceAwareDailyPlan": True,
            "wouldWrite": False,
            "creators": creator_rows,
            "accounts": account_rows,
            "recommendedActions": sorted(
                {action for row in creator_rows for action in row["recommendedActions"]}
            ),
            "inputs": {
                "threadsdashReportSchema": report.get("schema"),
                "schedulePlanSchema": schedule_plan.get("schema")
                if isinstance(schedule_plan, dict)
                else None,
                "timePlanSchema": time_plan.get("schema")
                if isinstance(time_plan, dict)
                else None,
                "winnerExpansionReportSchema": winner_expansion_report.get("schema")
                if isinstance(winner_expansion_report, dict)
                else None,
                "winnerExpansionPlanSchema": winner_expansion_plan.get("schema")
                if isinstance(winner_expansion_plan, dict)
                else None,
                "variantMetricsRollupSchema": variant_metrics_rollup.get("schema")
                if isinstance(variant_metrics_rollup, dict)
                else None,
                "missedDispatchCount": len(missed_dispatches),
            },
        }
