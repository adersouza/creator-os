from __future__ import annotations

import sqlite3
from typing import Any, Callable


class LiveScaleRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        inventory_stage_counts: Callable[[], dict[str, int]],
        inventory_production_requirements: Callable[..., dict[str, Any]],
        operator_load_audit: Callable[[], dict[str, Any]],
        exception_queue_report: Callable[[], dict[str, Any]],
        reel_factory_parent_metrics: Callable[[], dict[str, Any]],
        score_fraction: Callable[[Any, Any], float],
    ) -> None:
        self.conn = conn
        self._inventory_stage_counts = inventory_stage_counts
        self._inventory_production_requirements = inventory_production_requirements
        self._operator_load_audit = operator_load_audit
        self._exception_queue_report = exception_queue_report
        self._reel_factory_parent_metrics = reel_factory_parent_metrics
        self._score_fraction = score_fraction

    def creator_os_live_100_account_readiness(self) -> dict[str, Any]:
        accounts = self.actual_account_operational_counts()
        available_inventory = self._inventory_stage_counts()["scheduleSafeAssets"]
        required_inventory = 100 * 3 * 3
        required_parents = int(
            self._inventory_production_requirements(
                accounts=100,
                posts_per_account_per_day=3,
            ).get("requiredParentsPerDay")
            or 0
        )
        operator = self._operator_load_audit().get("scaleTiers", {}).get("100", {})
        exceptions = self._exception_queue_report()
        parent_metrics = self._reel_factory_parent_metrics()
        available_parents = int(parent_metrics.get("scheduleSafe") or 0)
        can_run = (
            accounts["totalAccounts"] >= 100
            and accounts["blockedAccounts"] == 0
            and available_inventory >= required_inventory
            and available_parents >= required_parents
        )
        blockers = []
        if accounts["totalAccounts"] < 100:
            blockers.append("fewer_than_100_actual_accounts")
        if accounts["blockedAccounts"] > 0:
            blockers.append("actual_account_blockers_present")
        if available_inventory < required_inventory:
            blockers.append("actual_schedule_safe_inventory_below_100_account_buffer")
        if available_parents < required_parents:
            blockers.append("actual_parent_inventory_below_required_daily_target")
        return {
            "schema": "creator_os.live_100_account_readiness.v1",
            "canRun100AccountsToday": can_run,
            "blockingReason": blockers[0] if blockers else "",
            "blockingReasons": blockers,
            "requiredInventory": required_inventory,
            "availableInventory": available_inventory,
            "requiredParentsPerDay": required_parents,
            "availableParents": available_parents,
            "actualAccounts": accounts["totalAccounts"],
            "eligibleAccounts": accounts["safeAccounts"],
            "restrictedAccounts": accounts["blockedAccounts"],
            "warmingAccounts": accounts["warmingAccounts"],
            "blockedAccounts": accounts["blockedAccounts"],
            "validatedDraftBuffer": available_inventory,
            "requiredBuffer": required_inventory,
            "inventoryHealthy": available_inventory >= required_inventory,
            "safeToRun100Accounts": can_run,
            "exactShortfall": "" if can_run else self.live_100_exact_shortfall(
                accounts=accounts,
                available_inventory=available_inventory,
                required_inventory=required_inventory,
                available_parents=available_parents,
                required_parents=required_parents,
            ),
            "expectedOperatorLoad": int(operator.get("estimatedHumanTouchesPerDay") or 0),
            "expectedExceptionRate": round((int(exceptions.get("exceptionCount") or 0) / max(1, accounts["totalAccounts"])) * 100, 2),
            "dataSource": "actual_current_state",
            "wouldWrite": False,
        }

    def creator_os_live_scale_runbook(self) -> dict[str, Any]:
        readiness = self.creator_os_live_100_account_readiness()
        return {
            "schema": "creator_os.live_scale_runbook.v1",
            "canRun100AccountsToday": readiness["canRun100AccountsToday"],
            "steps": [
                {
                    "step": "verify_actual_safe_accounts",
                    "status": "passed" if readiness["actualAccounts"] >= 100 else "blocked",
                    "wouldWrite": False,
                },
                {
                    "step": "verify_schedule_safe_inventory_buffer",
                    "status": "passed" if readiness["availableInventory"] >= readiness["requiredInventory"] else "blocked",
                    "wouldWrite": False,
                },
                {
                    "step": "verify_parent_factory_daily_capacity",
                    "status": "passed" if readiness["availableParents"] >= readiness["requiredParentsPerDay"] else "blocked",
                    "wouldWrite": False,
                },
                {
                    "step": "review_unified_exception_queue",
                    "status": "passed" if not readiness["blockingReasons"] else "blocked",
                    "wouldWrite": False,
                },
            ],
            "blockingReasons": readiness["blockingReasons"],
            "wouldWrite": False,
        }

    def creator_os_live_scale_scorecard(self) -> dict[str, Any]:
        readiness = self.creator_os_live_100_account_readiness()
        return {
            "schema": "creator_os.live_scale_scorecard.v1",
            "scores": {
                "actualAccounts": self._score_fraction(readiness["actualAccounts"], 100),
                "inventory": self._score_fraction(readiness["availableInventory"], readiness["requiredInventory"]),
                "parentFactory": self._score_fraction(readiness["availableParents"], readiness["requiredParentsPerDay"]),
                "exceptionRate": max(0.0, round(10 - readiness["expectedExceptionRate"], 1)),
            },
            "canRun100AccountsToday": readiness["canRun100AccountsToday"],
            "wouldWrite": False,
        }

    def actual_account_operational_counts(self) -> dict[str, int]:
        rows = [dict(row) for row in self.conn.execute("SELECT * FROM accounts").fetchall()]
        blocked = 0
        warming = 0
        for row in rows:
            status = " ".join(str(row.get(key) or "").lower() for key in ("status", "notes", "platform"))
            if any(token in status for token in ("blocked", "restricted", "disabled", "reauth")):
                blocked += 1
            if "warm" in status:
                warming += 1
        return {
            "totalAccounts": len(rows),
            "blockedAccounts": blocked,
            "safeAccounts": max(0, len(rows) - blocked),
            "warmingAccounts": warming,
        }

    def live_100_exact_shortfall(
        self,
        *,
        accounts: dict[str, int],
        available_inventory: int,
        required_inventory: int,
        available_parents: int,
        required_parents: int,
    ) -> str:
        parts = []
        if int(accounts.get("totalAccounts") or 0) < 100:
            parts.append(f"accounts:{100 - int(accounts.get('totalAccounts') or 0)}")
        if int(accounts.get("blockedAccounts") or 0) > 0:
            parts.append(f"restricted_accounts:{int(accounts.get('blockedAccounts') or 0)}")
        if available_inventory < required_inventory:
            parts.append(f"validated_draft_buffer:{required_inventory - available_inventory}")
        if available_parents < required_parents:
            parts.append(f"parent_inventory:{required_parents - available_parents}")
        return ",".join(parts)
