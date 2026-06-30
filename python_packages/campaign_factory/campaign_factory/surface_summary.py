from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any


class SurfaceSummaryRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_label: Callable[[Any], str],
        creator_os_target_date: Callable[..., str],
        creator_content_needs: Callable[..., dict[str, Any]],
        account_content_needs: Callable[..., dict[str, Any]],
        account_surface_obligations_plan: Callable[..., dict[str, Any]],
        multi_surface_inventory_audit: Callable[..., dict[str, Any]],
        surface_gap_report: Callable[..., dict[str, Any]],
        empty_surface_totals: Callable[[], dict[str, dict[str, int]]],
        content_surfaces: tuple[str, ...],
    ) -> None:
        self.conn = conn
        self._creator_label = creator_label
        self._creator_os_target_date = creator_os_target_date
        self._creator_content_needs = creator_content_needs
        self._account_content_needs = account_content_needs
        self._account_surface_obligations_plan = account_surface_obligations_plan
        self._multi_surface_inventory_audit = multi_surface_inventory_audit
        self._surface_gap_report = surface_gap_report
        self._empty_surface_totals = empty_surface_totals
        self._content_surfaces = content_surfaces

    def creator_surface_summary(
        self,
        *,
        creator: str,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        target_date = self._creator_os_target_date(date=date, generated_at=generated_at)
        needs = self._creator_content_needs(creator=creator_label, date=target_date)
        inventory = self._multi_surface_inventory_audit(creator=creator_label)
        gap = self._surface_gap_report(creator=creator_label, date=target_date)
        return {
            "schema": "creator_os.creator_surface_summary.v1",
            "creator": creator_label,
            "date": target_date,
            "accountsAnalyzed": needs.get("accountsAnalyzed", 0),
            "surfaceRequirementsTracked": list(self._content_surfaces),
            "totalsBySurface": needs.get("totalsBySurface")
            or self._empty_surface_totals(),
            "surfaceInventory": inventory.get("inventoryBySurface") or {},
            "surfaceShortfalls": gap.get("surfaceGaps") or {},
            "wouldWrite": False,
        }

    def account_surface_summary(
        self,
        *,
        creator: str,
        date: str | None = None,
        account_id: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        target_date = self._creator_os_target_date(date=date, generated_at=generated_at)
        if account_id:
            return self._account_content_needs(
                account_id=account_id, creator=creator_label, date=target_date
            )
        obligations = self._account_surface_obligations_plan(
            creator=creator_label, date=target_date
        )
        return {
            "schema": "creator_os.account_surface_summary.v1",
            "creator": creator_label,
            "date": target_date,
            "accounts": obligations.get("accounts") or [],
            "wouldWrite": False,
        }

    def creator_surface_gap_report(
        self,
        *,
        creator: str,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        target_date = self._creator_os_target_date(date=date, generated_at=generated_at)
        report = self._surface_gap_report(creator=creator, date=target_date)
        report = dict(report)
        report["schema"] = "creator_os.creator_surface_gap_report.v1"
        return report
