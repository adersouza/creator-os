from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from typing import Any


class LiveAcceptanceRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        normalize_content_surface: Callable[[str | None], str],
        actual_account_operational_counts: Callable[[], dict[str, int]],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        reservation_adjusted_inventory: Callable[..., dict[str, int]],
        exception_queue_report: Callable[[], dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._normalize_content_surface = normalize_content_surface
        self._actual_account_operational_counts = actual_account_operational_counts
        self._surface_report_assets = surface_report_assets
        self._build_surface_readiness = build_surface_readiness
        self._reservation_adjusted_inventory = reservation_adjusted_inventory
        self._exception_queue_report = exception_queue_report

    def creator_os_live_account_acceptance(
        self,
        *,
        account_target: int,
        posts_per_account_per_day: int = 3,
        buffer_days: int = 3,
        content_surface: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = max(1, int(account_target or 1))
        posts_per_day = target * max(0, int(posts_per_account_per_day or 0))
        required_inventory = posts_per_day * max(1, int(buffer_days or 1))
        accounts = self._actual_account_operational_counts()
        surface = (
            self._normalize_content_surface(content_surface)
            if content_surface
            else None
        )
        if surface:
            assets = self._surface_report_assets()
            inventory_accounting = self._reservation_adjusted_inventory(
                self._build_surface_readiness(assets),
                content_surface=surface,
            )
            available_inventory = inventory_accounting["netInventory"]
        else:
            inventory_accounting = self._reservation_adjusted_inventory(
                self._build_surface_readiness(self._surface_report_assets()),
            )
            available_inventory = inventory_accounting["netInventory"]
        exceptions = self._exception_queue_report()
        actuals = self.live_acceptance_actuals(
            account_target=target,
            threadsdash_report=threadsdash_report or {},
            required_inventory=required_inventory,
            available_inventory=available_inventory,
            exception_count=int(exceptions.get("exceptionCount") or 0),
        )
        criteria = {
            "missedDispatches": 0,
            "duplicatePublishes": 0,
            "restrictedAccountsScheduled": 0,
            "surfaceContractViolations": 0,
            "inventoryBufferMaintained": True,
            "metricsImported": True,
            "exceptionQueueWithinThreshold": True,
        }
        blockers: list[str] = []
        if accounts["safeAccounts"] < target:
            blockers.append("not_enough_safe_accounts")
        for key, expected in criteria.items():
            if actuals.get(key) != expected:
                blockers.append(self.live_acceptance_blocker_for(key))
        return {
            "schema": "creator_os.live_account_acceptance.v1",
            "accountTarget": target,
            "contentSurface": surface or "all",
            "postsPerDay": posts_per_day,
            "requiredInventory": required_inventory,
            "availableInventory": available_inventory,
            "grossInventory": inventory_accounting["grossInventory"],
            "reservedInventory": inventory_accounting["reservedInventory"],
            "usedInventory": inventory_accounting["usedInventory"],
            "cooldownBlockedInventory": inventory_accounting.get(
                "cooldownBlockedInventory", 0
            ),
            "netInventory": inventory_accounting["netInventory"],
            "actualAccounts": accounts["totalAccounts"],
            "eligibleAccounts": accounts["safeAccounts"],
            "restrictedAccounts": accounts["blockedAccounts"],
            "warmingAccounts": accounts["warmingAccounts"],
            "passCriteria": criteria,
            "actuals": actuals,
            "acceptancePassed": not blockers,
            "blockingReasons": sorted(set(blockers)),
            "dataSource": "actual_current_state",
            "wouldWrite": False,
        }

    def creator_os_staged_live_acceptance(
        self,
        *,
        stages: list[int] | None = None,
        content_surface: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        targets = stages or [10, 25, 50, 100]
        stage_rows = [
            self.creator_os_live_account_acceptance(
                account_target=target,
                content_surface=content_surface,
                threadsdash_report=threadsdash_report,
            )
            for target in targets
        ]
        passed = [
            row["accountTarget"] for row in stage_rows if row.get("acceptancePassed")
        ]
        current = max(passed) if passed else 0
        next_target = next(
            (
                row["accountTarget"]
                for row in stage_rows
                if not row.get("acceptancePassed")
            ),
            None,
        )
        return {
            "schema": "creator_os.staged_live_acceptance.v1",
            "stages": stage_rows,
            "currentCertifiedStage": current,
            "nextStageTarget": next_target,
            "readyForNextStage": next_target is None,
            "wouldWrite": False,
        }

    def live_acceptance_actuals(
        self,
        *,
        account_target: int,
        threadsdash_report: dict[str, Any],
        required_inventory: int,
        available_inventory: int,
        exception_count: int,
    ) -> dict[str, Any]:
        return {
            "missedDispatches": self.live_acceptance_missed_dispatches(
                threadsdash_report
            ),
            "duplicatePublishes": self.live_acceptance_duplicate_publishes(
                threadsdash_report
            ),
            "restrictedAccountsScheduled": self.live_acceptance_restricted_scheduled(
                threadsdash_report
            ),
            "surfaceContractViolations": self.live_acceptance_surface_contract_violations(
                threadsdash_report
            ),
            "inventoryBufferMaintained": available_inventory >= required_inventory,
            "metricsImported": self.live_acceptance_metrics_imported(),
            "exceptionQueueWithinThreshold": exception_count
            <= max(5, math.ceil(account_target * 0.05)),
        }

    def live_acceptance_missed_dispatches(self, report: dict[str, Any]) -> int:
        if isinstance(report.get("missedDispatches"), list):
            return len(report.get("missedDispatches") or [])
        return int(report.get("missedDispatchCount") or 0)

    def live_acceptance_duplicate_publishes(self, report: dict[str, Any]) -> int:
        explicit = report.get("duplicatePublishes")
        if isinstance(explicit, list):
            return len(explicit)
        if explicit is not None:
            return int(explicit or 0)
        rows = self.conn.execute(
            """
            SELECT post_id, COUNT(DISTINCT rendered_asset_id) AS c
            FROM performance_snapshots
            WHERE post_id IS NOT NULL AND post_id != ''
            GROUP BY post_id
            HAVING c > 1
            """
        ).fetchall()
        return len(rows)

    def live_acceptance_restricted_scheduled(self, report: dict[str, Any]) -> int:
        explicit = report.get("restrictedAccountsScheduled")
        if isinstance(explicit, list):
            return len(explicit)
        if explicit is not None:
            return int(explicit or 0)
        count = 0
        for account in report.get("accounts") or []:
            if not isinstance(account, dict):
                continue
            scheduled = bool(
                account.get("nextScheduledPost")
                or account.get("scheduled")
                or account.get("scheduledFor")
            )
            status = " ".join(
                str(account.get(key) or "").lower()
                for key in ("state", "status", "blockedReason", "restrictionStatus")
            )
            restricted = any(
                token in status
                for token in ("blocked", "restricted", "reauth", "disabled")
            )
            if scheduled and restricted:
                count += 1
        return count

    def live_acceptance_surface_contract_violations(
        self, report: dict[str, Any]
    ) -> int:
        explicit = report.get("surfaceContractViolations")
        if isinstance(explicit, list):
            return len(explicit)
        if explicit is not None:
            return int(explicit or 0)
        return int(report.get("surfaceContractViolationCount") or 0)

    def live_acceptance_metrics_imported(self) -> bool:
        return bool(
            self.conn.execute(
                "SELECT 1 FROM performance_snapshots WHERE metrics_eligible = 1 LIMIT 1"
            ).fetchone()
        )

    def live_acceptance_blocker_for(self, key: str) -> str:
        return {
            "missedDispatches": "missed_dispatches_present",
            "duplicatePublishes": "duplicate_publishes_present",
            "restrictedAccountsScheduled": "restricted_accounts_scheduled",
            "surfaceContractViolations": "surface_contract_violations_present",
            "inventoryBufferMaintained": "inventory_buffer_not_maintained",
            "metricsImported": "metrics_not_imported",
            "exceptionQueueWithinThreshold": "exception_queue_above_threshold",
        }.get(key, f"{key}_failed")
