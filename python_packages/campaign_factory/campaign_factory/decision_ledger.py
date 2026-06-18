from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Callable


class DecisionLedgerRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        creator_label: Callable[[Any], str],
        creator_os_target_date: Callable[..., str],
        creator_os_daily_plan: Callable[..., dict[str, Any]],
        creator_content_needs: Callable[..., dict[str, Any]],
        recommended_story_intent_for_date: Callable[..., str],
        recommended_story_style_for_intent: Callable[[str], str],
        story_mix_plan: Callable[..., dict[str, Any]],
        story_calendar_plan: Callable[..., dict[str, Any]],
        normalize_content_surface: Callable[[str | None], str],
    ) -> None:
        self.conn = conn
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now
        self._creator_label = creator_label
        self._creator_os_target_date = creator_os_target_date
        self._creator_os_daily_plan = creator_os_daily_plan
        self._creator_content_needs = creator_content_needs
        self._recommended_story_intent_for_date = recommended_story_intent_for_date
        self._recommended_story_style_for_intent = recommended_story_style_for_intent
        self._story_mix_plan = story_mix_plan
        self._story_calendar_plan = story_calendar_plan
        self._normalize_content_surface = normalize_content_surface

    def decision_ledger_preview(
        self,
        *,
        creator: str,
        date: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        winner_expansion_report: dict[str, Any] | None = None,
        winner_expansion_plan: dict[str, Any] | None = None,
        variant_inventory_plan: dict[str, Any] | None = None,
        variant_metrics_rollup: dict[str, Any] | None = None,
        account_tiers: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        timestamp = generated_at or self._utc_now()
        target_date = self._creator_os_target_date(date=date, generated_at=timestamp)
        daily = self._creator_os_daily_plan(
            creators=[creator_label],
            threadsdash_report=threadsdash_report or {},
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            winner_expansion_report=winner_expansion_report,
            winner_expansion_plan=winner_expansion_plan,
            variant_metrics_rollup=variant_metrics_rollup,
            date=target_date,
            generated_at=timestamp,
        )
        decisions: list[dict[str, Any]] = []
        creator_row = daily["creators"][0] if daily.get("creators") else {}
        if int(creator_row.get("inventoryShortfall") or 0) > 0:
            decisions.append(self.manager_decision_entry(
                decision_type="inventory_shortfall",
                reason="insufficient_schedule_safe_drafts",
                timestamp=timestamp,
                creator=creator_label,
                source_system="creator_os.daily_plan",
                explanation=(
                    f"{creator_label} needs {creator_row.get('accountsNeedingPostsToday') or 0} posts today "
                    f"but only {creator_row.get('validatedDraftsAvailable') or 0} validated schedule-safe drafts are available."
                ),
                payload={
                    "inventoryShortfall": int(creator_row.get("inventoryShortfall") or 0),
                    "validatedDraftsAvailable": int(creator_row.get("validatedDraftsAvailable") or 0),
                    "accountsNeedingPostsToday": int(creator_row.get("accountsNeedingPostsToday") or 0),
                },
                context_snapshot={
                    "managerDecision": creator_row.get("managerDecision"),
                    "managerReason": creator_row.get("managerReason"),
                    "nextSafeActions": creator_row.get("nextSafeActions") or [],
                },
            ))

        decisions.extend(self.decision_entries_from_account_content_needs(
            creator=creator_label,
            date=target_date,
            timestamp=timestamp,
        ))
        decisions.extend(self.decision_entries_from_daily_plan_accounts(
            daily=daily,
            creator=creator_label,
            timestamp=timestamp,
        ))
        decisions.extend(self.decision_entries_from_winner_expansion_report(
            report=winner_expansion_report,
            creator=creator_label,
            timestamp=timestamp,
        ))
        decisions.extend(self.decision_entries_from_variant_inventory_plan(
            plan=variant_inventory_plan,
            creator=creator_label,
            timestamp=timestamp,
        ))
        decisions.extend(self.decision_entries_from_winner_expansion_plan(
            plan=winner_expansion_plan,
            creator=creator_label,
            timestamp=timestamp,
        ))

        story_intent = str(
            creator_row.get("recommendedStoryIntent")
            or self._recommended_story_intent_for_date(target_date, creator=creator_label)
        )
        story_style = str(creator_row.get("recommendedStoryStyle") or self._recommended_story_style_for_intent(story_intent))
        decisions.append(self.manager_decision_entry(
            decision_type="story_intent_recommended",
            reason="creator_story_mix_plan",
            timestamp=timestamp,
            creator=creator_label,
            surface="story",
            source_system="story_mix_plan",
            explanation=f"Creator OS recommends a {story_intent} Story using {story_style} styling based on the current Story mix/calendar plan.",
            payload={
                "storyIntent": story_intent,
                "storyStyle": story_style,
                "storyGoal": self.story_goal_for_intent(story_intent),
            },
            context_snapshot={
                "storyMixPlan": self._story_mix_plan(creator=creator_label).get("storyMix"),
                "storyCalendarPlan": self._story_calendar_plan(creator=creator_label).get("calendar"),
                "recommendedStoryIntent": story_intent,
                "recommendedStoryStyle": story_style,
            },
        ))

        if isinstance(account_tiers, dict):
            for account in account_tiers.get("accounts") or []:
                if not isinstance(account, dict):
                    continue
                tier = str(account.get("tier") or account.get("accountTier") or "")
                if not tier:
                    continue
                decisions.append(self.manager_decision_entry(
                    decision_type="account_tier_classified",
                    reason=f"account_tier_{tier}",
                    timestamp=timestamp,
                    creator=creator_label,
                    account_id=str(account.get("accountId") or ""),
                    source_system="account_tier_engine",
                    explanation=f"Account was classified as {tier}, which determines the recommended posting guidance.",
                    payload={"accountTier": tier, "postingGuidance": account.get("postingGuidance") or {}},
                    context_snapshot=account,
                ))

        decisions = self.dedupe_manager_decisions(decisions)
        return {
            "schema": "creator_os.decision_ledger_preview.v1",
            "generatedAt": timestamp,
            "creator": creator_label,
            "date": target_date,
            "decisionCount": len(decisions),
            "decisionTypesSupported": self.manager_decision_types_supported(),
            "decisions": decisions,
            "wouldWrite": False,
            "inputs": {
                "dailyPlanSchema": daily.get("schema"),
                "threadsdashReportSchema": (threadsdash_report or {}).get("schema") if isinstance(threadsdash_report, dict) else None,
                "schedulePlanSchema": schedule_plan.get("schema") if isinstance(schedule_plan, dict) else None,
                "timePlanSchema": time_plan.get("schema") if isinstance(time_plan, dict) else None,
                "winnerExpansionReportSchema": winner_expansion_report.get("schema") if isinstance(winner_expansion_report, dict) else None,
                "winnerExpansionPlanSchema": winner_expansion_plan.get("schema") if isinstance(winner_expansion_plan, dict) else None,
                "variantInventoryPlanSchema": variant_inventory_plan.get("schema") if isinstance(variant_inventory_plan, dict) else None,
            },
        }

    def decision_ledger_report(self, **kwargs: Any) -> dict[str, Any]:
        preview = self.query_decision_ledger(**kwargs)
        preview["schema"] = "creator_os.decision_ledger_report.v1"
        return preview

    def decision_ledger_summary(self, **kwargs: Any) -> dict[str, Any]:
        report = self.query_decision_ledger(**kwargs)
        decisions = report.get("decisions") or []
        by_type: dict[str, int] = {}
        by_surface: dict[str, int] = {}
        by_reason: dict[str, int] = {}
        for decision in decisions:
            decision_type = str(decision.get("decisionType") or "")
            reason = str(decision.get("reason") or "")
            surface = str(decision.get("surface") or "")
            if decision_type:
                by_type[decision_type] = by_type.get(decision_type, 0) + 1
            if reason:
                by_reason[reason] = by_reason.get(reason, 0) + 1
            if surface:
                by_surface[surface] = by_surface.get(surface, 0) + 1
        return {
            "schema": "creator_os.decision_ledger_summary.v1",
            "generatedAt": report.get("generatedAt"),
            "creator": report.get("creator"),
            "date": report.get("date"),
            "decisionCount": len(decisions),
            "decisionCountsByType": by_type,
            "decisionCountsBySurface": by_surface,
            "decisionCountsByReason": by_reason,
            "wouldWrite": False,
        }

    def decision_ledger_by_creator(self, *, creator: str, **kwargs: Any) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        report = self.query_decision_ledger(creator=creator_label, **kwargs)
        decisions = report.get("decisions") or []
        return self.manager_decision_filtered_report(
            schema="creator_os.decision_ledger_by_creator.v1",
            report=report,
            decisions=decisions,
            extra={"creator": creator_label},
        )

    def decision_ledger_by_account(self, *, account_id: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        account_key = str(account_id or "").strip()
        report = self.query_decision_ledger(creator=creator, account_id=account_key, **kwargs)
        decisions = report.get("decisions") or []
        return self.manager_decision_filtered_report(
            schema="creator_os.decision_ledger_by_account.v1",
            report=report,
            decisions=decisions,
            extra={"accountId": account_key},
        )

    def decision_ledger_by_surface(self, *, surface: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        normalized_surface = self._normalize_content_surface(surface)
        report = self.query_decision_ledger(creator=creator, surface=normalized_surface, **kwargs)
        decisions = report.get("decisions") or []
        return self.manager_decision_filtered_report(
            schema="creator_os.decision_ledger_by_surface.v1",
            report=report,
            decisions=decisions,
            extra={"surface": normalized_surface},
        )

    def decision_ledger_by_decision_type(self, *, decision_type: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        normalized_type = str(decision_type or "").strip()
        report = self.query_decision_ledger(creator=creator, decision_type=normalized_type, **kwargs)
        decisions = report.get("decisions") or []
        return self.manager_decision_filtered_report(
            schema="creator_os.decision_ledger_by_decision_type.v1",
            report=report,
            decisions=decisions,
            extra={"decisionType": normalized_type},
        )

    def query_decision_ledger(
        self,
        *,
        creator: str,
        account_id: str | None = None,
        surface: str | None = None,
        decision_type: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        report = self.decision_ledger_preview(creator=creator, **kwargs)
        decisions = list(report.get("decisions") or [])
        creator_label = self._creator_label(creator)
        decisions = [
            entry for entry in decisions
            if self._creator_label(entry.get("creator")) == creator_label
        ]
        if account_id is not None:
            account_key = str(account_id or "").strip()
            decisions = [entry for entry in decisions if str(entry.get("accountId") or "") == account_key]
        if surface is not None:
            normalized_surface = self._normalize_content_surface(surface)
            decisions = [
                entry for entry in decisions
                if self._normalize_content_surface(entry.get("surface")) == normalized_surface
            ]
        if decision_type is not None:
            normalized_type = str(decision_type or "").strip()
            decisions = [entry for entry in decisions if str(entry.get("decisionType") or "") == normalized_type]
        result = dict(report)
        result["decisions"] = decisions
        result["decisionCount"] = len(decisions)
        return result

    @staticmethod
    def manager_decision_filtered_report(
        *,
        schema: str,
        report: dict[str, Any],
        decisions: list[dict[str, Any]],
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": schema,
            "generatedAt": report.get("generatedAt"),
            "creator": report.get("creator"),
            "date": report.get("date"),
            **extra,
            "decisionCount": len(decisions),
            "decisions": decisions,
            "wouldWrite": False,
        }

    def decision_entries_from_account_content_needs(
        self,
        *,
        creator: str,
        date: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        try:
            needs = self._creator_content_needs(creator=creator, date=date)
        except Exception:
            return entries
        for account in needs.get("accounts") or []:
            if not isinstance(account, dict):
                continue
            for obligation in account.get("obligations") or []:
                if not isinstance(obligation, dict) or not obligation.get("needed"):
                    continue
                surface = self._normalize_content_surface(obligation.get("surface"))
                decision_type = f"account_needs_{surface}"
                reason = self.manager_obligation_reason(obligation)
                entries.append(self.manager_decision_entry(
                    decision_type=decision_type,
                    reason=reason,
                    timestamp=timestamp,
                    creator=creator,
                    account_id=str(account.get("accountId") or ""),
                    surface=surface,
                    source_system="account_content_requirements",
                    explanation=self.manager_obligation_explanation(obligation),
                    payload={
                        "account": account.get("account"),
                        "instagramAccountId": account.get("instagramAccountId"),
                        "surface": surface,
                        "required": obligation.get("required"),
                        "completed": obligation.get("completed"),
                        "scheduled": obligation.get("scheduled"),
                        "remaining": obligation.get("remaining"),
                    },
                    context_snapshot=obligation,
                ))
        return entries

    def decision_entries_from_daily_plan_accounts(
        self,
        *,
        daily: dict[str, Any],
        creator: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for account in daily.get("accounts") or []:
            if not isinstance(account, dict):
                continue
            if account.get("state") != "blocked":
                continue
            reason = str(account.get("blockedReason") or "account_blocked")
            entries.append(self.manager_decision_entry(
                decision_type="account_blocked",
                reason=reason,
                timestamp=timestamp,
                creator=creator,
                account_id=str(account.get("accountId") or ""),
                source_system="creator_os.daily_plan",
                explanation=f"Account is blocked for scheduling because {reason}.",
                payload={"accountTier": account.get("accountTier"), "username": account.get("username")},
                context_snapshot=account,
            ))
        return entries

    def decision_entries_from_winner_expansion_report(
        self,
        *,
        report: dict[str, Any] | None,
        creator: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(report, dict):
            return []
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for winner in [item for item in (report.get("winners") or report.get("recommendations") or []) if isinstance(item, dict)]:
            key = str(winner.get("postId") or winner.get("assetId") or winner.get("parentAssetId") or "")
            if key in seen:
                continue
            seen.add(key)
            reason = str(winner.get("reason") or winner.get("winnerReason") or "manual_winner")
            asset_id = str(winner.get("assetId") or winner.get("parentAssetId") or "")
            entries.append(self.manager_decision_entry(
                decision_type="winner_selected",
                reason=reason,
                timestamp=timestamp,
                creator=creator,
                rendered_asset_id=asset_id,
                parent_asset_id=asset_id,
                source_system="winner_expansion_report",
                explanation=f"Asset {asset_id or key} was selected as a winner because {reason}.",
                payload={
                    "postId": winner.get("postId"),
                    "assetId": asset_id,
                    "parentReelId": winner.get("parentReelId"),
                    "variantFamilyId": winner.get("variantFamilyId"),
                    "winnerReason": reason,
                    "recommendedAction": winner.get("recommendedAction"),
                },
                context_snapshot=winner,
            ))
        return entries

    def decision_entries_from_variant_inventory_plan(
        self,
        *,
        plan: dict[str, Any] | None,
        creator: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(plan, dict):
            return []
        entries: list[dict[str, Any]] = []
        for batch in plan.get("executionBatches") or []:
            if not isinstance(batch, dict):
                continue
            parent_asset_id = str(batch.get("parentAssetId") or "")
            entries.append(self.manager_decision_entry(
                decision_type="parent_selected",
                reason="variant_inventory_plan",
                timestamp=timestamp,
                creator=creator,
                parent_asset_id=parent_asset_id,
                source_system="variant_inventory_plan",
                explanation=f"Parent asset {parent_asset_id} was selected for ContentForge expansion to satisfy inventory planning.",
                payload={
                    "parentAssetId": parent_asset_id,
                    "requestedVariants": batch.get("requestedVariants"),
                    "minimumRecommended": batch.get("minimumRecommended"),
                    "operationFamilies": batch.get("operationFamilies") or [],
                    "preset": batch.get("preset"),
                },
                context_snapshot=batch,
            ))
        return entries

    def decision_entries_from_winner_expansion_plan(
        self,
        *,
        plan: dict[str, Any] | None,
        creator: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(plan, dict):
            return []
        parent_asset_id = str(plan.get("parentAssetId") or "")
        rejected = plan.get("rejectedExistingVariants") if isinstance(plan.get("rejectedExistingVariants"), dict) else {}
        mapping = {
            "lowQuality": ("low_quality", "caption_readability_below_threshold"),
            "duplicateSiblings": ("duplicate_sibling", "duplicate_sibling"),
            "notUploadReady": ("not_upload_ready", "not_upload_ready"),
        }
        entries: list[dict[str, Any]] = []
        for key, (reason, example_reason) in mapping.items():
            count = int(rejected.get(key) or 0)
            if count <= 0:
                continue
            entries.append(self.manager_decision_entry(
                decision_type="variant_rejected",
                reason=reason,
                timestamp=timestamp,
                creator=creator,
                parent_asset_id=parent_asset_id,
                source_system="winner_expansion_plan",
                explanation=f"{count} existing sibling variant(s) were rejected for {example_reason}.",
                payload={
                    "parentAssetId": parent_asset_id,
                    "rejectedCount": count,
                    "rejectionFamily": key,
                },
                context_snapshot=plan,
            ))
        return entries

    def manager_decision_entry(
        self,
        *,
        decision_type: str,
        reason: str,
        timestamp: str,
        source_system: str,
        explanation: str,
        creator: str | None = None,
        account_id: str | None = None,
        surface: str | None = None,
        rendered_asset_id: str | None = None,
        parent_asset_id: str | None = None,
        variant_id: str | None = None,
        payload: dict[str, Any] | None = None,
        context_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision_payload = self._sanitize_for_storage(payload or {})
        context = self._sanitize_for_storage(context_snapshot or {})
        stable_key = json.dumps({
            "decisionType": decision_type,
            "reason": reason,
            "timestamp": timestamp,
            "creator": creator,
            "accountId": account_id,
            "surface": surface,
            "renderedAssetId": rendered_asset_id,
            "parentAssetId": parent_asset_id,
            "variantId": variant_id,
            "payload": decision_payload,
        }, ensure_ascii=False, sort_keys=True)
        return {
            "decisionId": f"mdec_preview_{hashlib.sha256(stable_key.encode('utf-8')).hexdigest()[:16]}",
            "decisionType": decision_type,
            "reason": reason,
            "timestamp": timestamp,
            "creator": self._creator_label(creator) if creator else None,
            "accountId": account_id or "",
            "surface": self._normalize_content_surface(surface) if surface else "",
            "renderedAssetId": rendered_asset_id or "",
            "parentAssetId": parent_asset_id or "",
            "variantId": variant_id or "",
            "sourceSystem": source_system,
            "explanation": explanation,
            "contextSnapshot": context,
            **decision_payload,
            "wouldWrite": False,
        }

    @staticmethod
    def dedupe_manager_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for decision in decisions:
            key = str(decision.get("decisionId") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            unique.append(decision)
        return unique

    @staticmethod
    def manager_decision_types_supported() -> list[str]:
        return [
            "inventory_shortfall",
            "account_needs_reel",
            "account_needs_story",
            "account_needs_feed_single",
            "account_needs_feed_carousel",
            "account_blocked",
            "account_tier_classified",
            "winner_selected",
            "parent_selected",
            "variant_rejected",
            "story_intent_recommended",
        ]

    def manager_obligation_reason(self, obligation: dict[str, Any]) -> str:
        surface = self._normalize_content_surface(obligation.get("surface"))
        cadence = str(obligation.get("cadence") or "")
        if surface == "story" and cadence == "daily":
            return "daily_story_requirement"
        if cadence.endswith("_per_day"):
            return f"{surface}_{cadence}_requirement"
        if cadence == "weekly":
            return f"weekly_{surface}_requirement"
        if cadence == "every_other_day":
            return f"every_other_day_{surface}_requirement"
        return f"{surface}_requirement"

    def manager_obligation_explanation(self, obligation: dict[str, Any]) -> str:
        surface = self._normalize_content_surface(obligation.get("surface"))
        required = int(obligation.get("required") or 0)
        completed = int(obligation.get("completed") or 0)
        scheduled = int(obligation.get("scheduled") or 0)
        remaining = int(obligation.get("remaining") or 0)
        cadence = str(obligation.get("cadence") or "configured")
        if surface == "story" and cadence == "daily":
            return "Account requires one Story every day and none has been completed today." if remaining == 1 and completed == 0 and scheduled == 0 else f"Account has a daily Story requirement with {remaining} Story obligation(s) still remaining today."
        return f"Account requires {required} {surface} item(s) for cadence {cadence}; {completed} completed, {scheduled} scheduled, {remaining} remaining."

    @staticmethod
    def story_goal_for_intent(intent: str) -> str:
        return {
            "snapchat_promo": "traffic",
            "reel_teaser": "reel_support",
            "casual_selfie": "audience_warming",
            "mirror_selfie": "audience_warming",
            "outfit_check": "engagement",
            "gym_selfie": "audience_warming",
            "bedroom_selfie": "retention",
            "lifestyle": "retention",
            "behind_the_scenes": "retention",
            "engagement": "engagement",
            "profile_visit": "profile_visit",
        }.get(intent, "audience_warming")
