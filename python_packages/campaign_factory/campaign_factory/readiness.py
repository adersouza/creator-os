from __future__ import annotations

from typing import Any

from .execution_readiness import ExecutionReadinessRepository
from .persistence import utc_now


def creator_os_execution_readiness(
    self,
    *,
    creator: str,
    requested_count: int,
    threadsdash_report: dict[str, Any] | None = None,
    schedule_plan: dict[str, Any] | None = None,
    time_plan: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    repository = ExecutionReadinessRepository(
        self.conn,
        self.settings,
        creator_label=self._creator_label,
        creator_os_daily_plan=self.creator_os_daily_plan,
        creator_os_draft_items=self._creator_os_draft_items,
        creator_os_schedule_safe_drafts=self._creator_os_schedule_safe_drafts,
        creator_os_account_health_report=self.creator_os_account_health_report,
        creator_os_execution_draft_blockers=self._creator_os_execution_draft_blockers,
        creator_os_execution_account_health_blockers=self._creator_os_execution_account_health_blockers,
        creator_os_execution_account_health_warnings=self._creator_os_execution_account_health_warnings,
        utc_now=utc_now,
    )
    return repository.creator_os_execution_readiness(
        creator=creator,
        requested_count=requested_count,
        threadsdash_report=threadsdash_report,
        schedule_plan=schedule_plan,
        time_plan=time_plan,
        generated_at=generated_at,
    )
