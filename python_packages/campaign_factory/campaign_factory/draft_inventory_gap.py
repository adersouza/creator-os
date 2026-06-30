from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any


class DraftInventoryGapRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_label: Callable[[Any], str],
        creator_os_draft_items: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        creator_os_local_schedule_safe_assets: Callable[[str], list[dict[str, Any]]],
        creator_os_schedule_safe_drafts: Callable[
            [str, list[dict[str, Any]]], list[dict[str, Any]]
        ],
        creator_os_draft_exclusion_reason: Callable[[dict[str, Any]], str | None],
        creator_os_execution_draft_blockers: Callable[
            [str, list[dict[str, Any]]], list[str]
        ],
        creator_os_gap_blocking_reason: Callable[
            [str | None, list[str], dict[str, Any]], str
        ],
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self._creator_label = creator_label
        self._creator_os_draft_items = creator_os_draft_items
        self._creator_os_local_schedule_safe_assets = (
            creator_os_local_schedule_safe_assets
        )
        self._creator_os_schedule_safe_drafts = creator_os_schedule_safe_drafts
        self._creator_os_draft_exclusion_reason = creator_os_draft_exclusion_reason
        self._creator_os_execution_draft_blockers = creator_os_execution_draft_blockers
        self._creator_os_gap_blocking_reason = creator_os_gap_blocking_reason
        self._utc_now = utc_now

    def creator_os_draft_inventory_gap(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        planner_inputs = [
            item for item in (time_plan, schedule_plan) if isinstance(item, dict)
        ]
        draft_items = self._creator_os_draft_items(planner_inputs)
        local_items = self._creator_os_local_schedule_safe_assets(creator_label)
        local_by_asset = {str(item["renderedAssetId"]): item for item in local_items}
        exported_asset_ids = {
            str(
                item.get("renderedAssetId")
                or item.get("campaignFactoryAssetId")
                or item.get("campaign_factory_asset_id")
                or ""
            )
            for item in draft_items
            if str(
                item.get("renderedAssetId")
                or item.get("campaignFactoryAssetId")
                or item.get("campaign_factory_asset_id")
                or ""
            ).strip()
        }
        schedule_safe_drafts = self._creator_os_schedule_safe_drafts(
            creator_label, draft_items
        )
        exported_but_not_validated = []
        validated_but_not_schedule_safe = []
        blocked_reasons: dict[str, int] = {}

        for item in draft_items:
            if self._creator_label(item.get("creator")) not in {
                creator_label,
                "unknown",
            }:
                continue
            asset_id = str(
                item.get("renderedAssetId")
                or item.get("campaignFactoryAssetId")
                or item.get("campaign_factory_asset_id")
                or ""
            ).strip()
            post_id = item.get("postId") or item.get("draftPostId")
            reason = self._creator_os_draft_exclusion_reason(item)
            blockers = self._creator_os_execution_draft_blockers(creator_label, [item])
            if item.get("platformDraftValidated") is not True:
                exported_but_not_validated.append(
                    {
                        "draftPostId": post_id,
                        "renderedAssetId": asset_id,
                        "distributionPlanId": item.get("distributionPlanId"),
                        "reason": reason or "platform_draft_not_validated",
                        "wouldWrite": False,
                    }
                )
                blocked_reasons["platform_draft_not_validated"] = (
                    blocked_reasons.get("platform_draft_not_validated", 0) + 1
                )
                continue
            if item not in schedule_safe_drafts:
                normalized = self._creator_os_gap_blocking_reason(
                    reason, blockers, item
                )
                validated_but_not_schedule_safe.append(
                    {
                        "draftPostId": post_id,
                        "renderedAssetId": asset_id,
                        "distributionPlanId": item.get("distributionPlanId"),
                        "accountId": item.get("accountId"),
                        "username": item.get("username"),
                        "reason": normalized,
                        "wouldWrite": False,
                    }
                )
                blocked_reasons[normalized] = blocked_reasons.get(normalized, 0) + 1

        not_exported = [
            {
                "renderedAssetId": item["renderedAssetId"],
                "campaign": item.get("campaign"),
                "contentSurface": item.get("contentSurface"),
                "latestDistributionPlanId": item.get("latestDistributionPlanId"),
                "reason": "local_schedule_safe_asset_not_exported_to_threadsdash",
                "wouldWrite": False,
            }
            for asset_id, item in sorted(local_by_asset.items())
            if asset_id not in exported_asset_ids
        ]
        if not_exported:
            blocked_reasons["not_exported_to_threadsdash"] = len(not_exported)

        local_count = len(local_items)
        thread_dash_count = len(schedule_safe_drafts)
        if not_exported:
            next_action = "export_validated_drafts"
        elif exported_but_not_validated or validated_but_not_schedule_safe:
            next_action = "fix_validation"
        elif local_count == 0:
            next_action = "create_more_assets"
        else:
            next_action = (
                "export_validated_drafts"
                if thread_dash_count < local_count
                else "fix_validation"
            )

        return {
            "schema": "creator_os.draft_inventory_gap.v1",
            "generatedAt": generated_at or self._utc_now(),
            "creator": creator_label,
            "localScheduleSafeAssets": local_count,
            "threadDashValidatedDrafts": thread_dash_count,
            "notExportedYet": not_exported,
            "exportedButNotValidated": exported_but_not_validated,
            "validatedButNotScheduleSafe": validated_but_not_schedule_safe,
            "blockedReasons": blocked_reasons,
            "nextSafeAction": next_action,
            "wouldWrite": False,
            "inputs": {
                "threadsdashReportSchema": (threadsdash_report or {}).get("schema")
                if isinstance(threadsdash_report, dict)
                else None,
                "schedulePlanSchema": schedule_plan.get("schema")
                if isinstance(schedule_plan, dict)
                else None,
                "timePlanSchema": time_plan.get("schema")
                if isinstance(time_plan, dict)
                else None,
            },
        }
