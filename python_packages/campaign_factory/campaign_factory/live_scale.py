from __future__ import annotations

import sqlite3
from typing import Any, Callable


class LiveScaleRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_os_live_100_account_readiness: Callable[[], dict[str, Any]],
        score_fraction: Callable[[Any, Any], float],
    ) -> None:
        self.conn = conn
        self._creator_os_live_100_account_readiness = creator_os_live_100_account_readiness
        self._score_fraction = score_fraction

    def creator_os_live_scale_runbook(self) -> dict[str, Any]:
        readiness = self._creator_os_live_100_account_readiness()
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
        readiness = self._creator_os_live_100_account_readiness()
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
