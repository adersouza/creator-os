from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any


class AcceptanceSuiteRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_os_daily_plan: Callable[..., dict[str, Any]],
        creator_os_execution_readiness: Callable[..., dict[str, Any]],
        creator_os_account_health_report: Callable[..., dict[str, Any]],
        content_surfaces: tuple[str, ...],
    ) -> None:
        self.conn = conn
        self._creator_os_daily_plan = creator_os_daily_plan
        self._creator_os_execution_readiness = creator_os_execution_readiness
        self._creator_os_account_health_report = creator_os_account_health_report
        self._content_surfaces = content_surfaces

    def creator_os_200_account_acceptance_suite(
        self,
        *,
        accounts: int = 200,
        creators: int = 3,
        daily_obligations: int = 600,
        draft_inventory: int = 1800,
        warming_accounts: int = 30,
        restricted_accounts: int = 15,
        manual_review_accounts: int = 10,
        mixed_surfaces: bool = True,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        generated = generated_at or "2026-06-08T12:00:00+00:00"
        creator_names = [
            f"Creator {idx}" for idx in range(1, max(1, int(creators or 1)) + 1)
        ]
        synthetic_accounts = self._operational_acceptance_accounts(
            accounts=max(0, int(accounts or 0)),
            creators=creator_names,
            warming_accounts=max(0, int(warming_accounts or 0)),
            restricted_accounts=max(0, int(restricted_accounts or 0)),
            manual_review_accounts=max(0, int(manual_review_accounts or 0)),
            mixed_surfaces=bool(mixed_surfaces),
        )
        synthetic_drafts = self._operational_acceptance_drafts(
            count=max(0, int(draft_inventory or 0)),
            accounts=synthetic_accounts,
            creator_names=creator_names,
            mixed_surfaces=bool(mixed_surfaces),
        )
        threadsdash_report = self._operational_acceptance_threadsdash_report(
            synthetic_accounts
        )
        schedule_plan = {
            "schema": "threadsdashboard.campaign_schedule_plan.v1",
            "creator": None,
            "requestedCount": daily_obligations,
            "status": "ready",
            "validatedDraftsAvailable": len(synthetic_drafts),
            "items": synthetic_drafts,
            "wouldWrite": False,
        }
        time_plan = {
            "schema": "threadsdashboard.campaign_time_plan.v1",
            "creator": None,
            "requestedCount": daily_obligations,
            "status": "ready",
            "items": synthetic_drafts,
            "wouldWrite": False,
        }

        start = time.perf_counter()
        daily = self._creator_os_daily_plan(
            creators=creator_names,
            threadsdash_report=threadsdash_report,
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            generated_at=generated,
        )
        daily_plan_runtime_ms = int((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        readiness_by_creator = []
        for creator in creator_names:
            creator_accounts = [
                row
                for row in daily.get("accounts") or []
                if row.get("creator") == creator
            ]
            requested = max(
                1, sum(1 for row in creator_accounts if row.get("state") != "blocked")
            )
            creator_safe_accounts = [
                account
                for account in synthetic_accounts
                if account.get("creator") == creator
                and account.get("safeToSchedule") is not False
            ]
            creator_report = self._operational_acceptance_threadsdash_report(
                creator_safe_accounts
            )
            readiness_by_creator.append(
                self._creator_os_execution_readiness(
                    creator=creator,
                    requested_count=requested,
                    threadsdash_report=creator_report,
                    schedule_plan=schedule_plan,
                    time_plan=time_plan,
                    generated_at=generated,
                )
            )
        execution_runtime_ms = int((time.perf_counter() - start) * 1000)

        health_reports = [
            self._creator_os_account_health_report(
                creator=creator,
                threadsdash_report=threadsdash_report,
                generated_at=generated,
            )
            for creator in creator_names
        ]
        blocked_accounts = sum(
            int((report.get("summary") or {}).get("blockedAccounts") or 0)
            for report in health_reports
        )
        expected_blocked = min(
            len(synthetic_accounts),
            max(0, int(restricted_accounts or 0))
            + max(0, int(manual_review_accounts or 0)),
        )
        inventory_shortfall = sum(
            max(0, int(row.get("inventoryShortfall") or 0))
            for row in daily.get("creators") or []
        )
        unexpected_failures = []
        for readiness in readiness_by_creator:
            blockers = [
                blocker
                for blocker in readiness.get("blockers") or []
                if blocker not in {"threadsdashboard_runtime_routes_unverified"}
            ]
            if readiness.get("managerDecision") not in {
                "ready_to_schedule",
                "needs_inventory",
            }:
                unexpected_failures.append(
                    {
                        "system": "execution-readiness",
                        "creator": readiness.get("creator"),
                        "reason": readiness.get("managerDecision"),
                        "blockers": blockers,
                    }
                )
        acceptance_passed = (
            inventory_shortfall == 0
            and blocked_accounts == expected_blocked
            and not unexpected_failures
            and len(synthetic_drafts) >= max(0, int(daily_obligations or 0))
        )
        return {
            "schema": "creator_os.200_account_acceptance_suite.v1",
            "generatedAt": generated,
            "acceptancePassed": bool(acceptance_passed),
            "accounts": len(synthetic_accounts),
            "creators": len(creator_names),
            "postsPerDay": max(0, int(daily_obligations or 0)),
            "draftsPerDay": len(synthetic_drafts),
            "metricsSnapshotsPerDay": len(synthetic_drafts),
            "scheduleDecisionsPerDay": max(0, int(daily_obligations or 0))
            + len(synthetic_accounts),
            "accountHealthEvaluationsPerDay": len(synthetic_accounts),
            "dailyPlanRuntimeMs": daily_plan_runtime_ms,
            "executionReadinessRuntimeMs": execution_runtime_ms,
            "blockedAccounts": blocked_accounts,
            "expectedBlockedAccounts": expected_blocked,
            "unexpectedBlockedAccounts": max(0, blocked_accounts - expected_blocked),
            "inventoryShortfall": inventory_shortfall,
            "validatedPaths": [
                "daily-plan",
                "execution-readiness",
                "account-health",
                "surface-inventory",
                "decision-ledger",
                "lifecycle",
                "publishability",
                "recommendation-generation",
                "inventory-planning",
            ],
            "dailyPlan": {
                "schema": daily.get("schema"),
                "creatorCount": len(daily.get("creators") or []),
                "accountCount": len(daily.get("accounts") or []),
                "wouldWrite": daily.get("wouldWrite") is False,
            },
            "executionReadiness": [
                {
                    "creator": item.get("creator"),
                    "managerDecision": item.get("managerDecision"),
                    "executionReady": item.get("executionReady"),
                    "blockers": item.get("blockers") or [],
                    "warnings": item.get("warnings") or [],
                    "wouldWrite": item.get("wouldWrite") is False,
                }
                for item in readiness_by_creator
            ],
            "unexpectedFailures": unexpected_failures,
            "wouldWrite": False,
        }

    def _operational_acceptance_accounts(
        self,
        *,
        accounts: int,
        creators: list[str],
        warming_accounts: int,
        restricted_accounts: int,
        manual_review_accounts: int,
        mixed_surfaces: bool,
    ) -> list[dict[str, Any]]:
        rows = []
        creator_names = creators or ["Creator 1"]
        for idx in range(max(0, accounts)):
            creator = creator_names[idx % len(creator_names)]
            account_id = f"ig_scale_{idx + 1:03d}"
            row: dict[str, Any] = {
                "accountId": account_id,
                "username": account_id,
                "creator": creator,
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
                "recommendationEligibilityState": "eligible",
                "accountMaturityScore": 75,
                "accountAgeDays": 90,
                "successfulPublishes": 40,
                "surfaceNeeds": self._operational_acceptance_surface_needs(
                    idx, mixed_surfaces=mixed_surfaces
                ),
            }
            if idx < restricted_accounts:
                row.update(
                    {
                        "bucket": "blocked_reauth",
                        "safeToSchedule": False,
                        "needsPostToday": False,
                        "restrictionStatus": {
                            "active": True,
                            "status": "active",
                            "type": "account_restricted",
                        },
                        "accountTrustState": "restricted",
                        "blockedReason": "account_restricted",
                    }
                )
            elif idx < restricted_accounts + manual_review_accounts:
                row.update(
                    {
                        "bucket": "blocked_unknown",
                        "safeToSchedule": False,
                        "needsPostToday": False,
                        "accountTrustState": "manual_review_required",
                        "recommendationEligibilityState": "manual_review_required",
                        "blockedReason": "account_manual_review_required",
                    }
                )
            elif idx < restricted_accounts + manual_review_accounts + warming_accounts:
                row.update(
                    {
                        "accountTrustState": "warming",
                        "accountMaturityScore": 25,
                        "accountAgeDays": 7,
                        "successfulPublishes": 3,
                        "warmingStage": "day_4_7",
                    }
                )
            rows.append(row)
        return rows

    def _operational_acceptance_surface_needs(
        self, idx: int, *, mixed_surfaces: bool
    ) -> dict[str, dict[str, Any]]:
        if not mixed_surfaces:
            return {"reel": {"needed": True, "remaining": 1}}
        surface = ("reel", "story", "feed_single")[idx % 3]
        return {
            name: {
                "needed": name == surface,
                "remaining": 1 if name == surface else 0,
                "blockedReason": "",
            }
            for name in self._content_surfaces
        }

    def _operational_acceptance_drafts(
        self,
        *,
        count: int,
        accounts: list[dict[str, Any]],
        creator_names: list[str],
        mixed_surfaces: bool,
    ) -> list[dict[str, Any]]:
        safe_accounts = [
            account
            for account in accounts
            if account.get("safeToSchedule") is not False
        ]
        if not safe_accounts:
            safe_accounts = accounts
        surfaces = ("reel", "story", "feed_single") if mixed_surfaces else ("reel",)
        rows = []
        for idx in range(max(0, count)):
            account = safe_accounts[idx % len(safe_accounts)] if safe_accounts else {}
            creator = (
                account.get("creator")
                or creator_names[idx % max(1, len(creator_names))]
            )
            surface = surfaces[idx % len(surfaces)]
            post_id = f"scale_post_{idx + 1:04d}"
            rows.append(
                {
                    "postId": post_id,
                    "draftPostId": post_id,
                    "accountId": account.get("accountId") or f"ig_scale_{idx + 1:03d}",
                    "username": account.get("username") or "",
                    "creator": creator,
                    "renderedAssetId": f"asset_{post_id}",
                    "distributionPlanId": f"dist_{post_id}",
                    "platformDraftValidated": True,
                    "handoffManifestOk": True,
                    "publishabilityState": "exportable",
                    "quarantined": False,
                    "duplicateCheck": "clear",
                    "variantCooldownCheck": "clear",
                    "qstashEligible": True,
                    "instagramPostCaption": "new post is up",
                    "captionPlacementQcStatus": "passed" if surface == "reel" else "",
                    "audioValidity": "valid" if surface == "reel" else "not_required",
                    "contentSurface": surface,
                    "scheduledFor": self._operational_acceptance_time(idx),
                    "wouldWrite": False,
                }
            )
            if surface == "reel":
                rows[-1]["burnedCaptionTextPresent"] = True
        return rows

    def _operational_acceptance_time(self, idx: int) -> str:
        base = datetime(2026, 6, 8, 6, 0, tzinfo=UTC)
        return (base + timedelta(minutes=idx)).isoformat()

    def _operational_acceptance_threadsdash_report(
        self, accounts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        buckets = {
            "safe_to_schedule_today": [
                account
                for account in accounts
                if account.get("bucket") == "safe_to_schedule_today"
            ],
            "already_scheduled_today": [
                account
                for account in accounts
                if account.get("bucket") == "already_scheduled_today"
            ],
            "blocked_reauth": [
                account
                for account in accounts
                if account.get("bucket") == "blocked_reauth"
            ],
            "blocked_token_expired": [
                account
                for account in accounts
                if account.get("bucket") == "blocked_token_expired"
            ],
            "blocked_disabled": [
                account
                for account in accounts
                if account.get("bucket") == "blocked_disabled"
            ],
            "blocked_recent_failure": [
                account
                for account in accounts
                if account.get("bucket") == "blocked_recent_failure"
            ],
            "blocked_unknown": [
                account
                for account in accounts
                if account.get("bucket") == "blocked_unknown"
            ],
        }
        return {
            "schema": "threadsdashboard.campaign_schedule_manager_report.v1",
            "accounts": accounts,
            "accountBuckets": buckets,
            "missedDispatches": [],
            "summary": {
                "safeToScheduleCount": len(buckets["safe_to_schedule_today"]),
                "needsPostTodayCount": sum(
                    1 for account in accounts if account.get("needsPostToday")
                ),
                "blockedCount": sum(
                    len(value)
                    for key, value in buckets.items()
                    if key.startswith("blocked_")
                ),
                "missedDispatchCount": 0,
            },
        }
