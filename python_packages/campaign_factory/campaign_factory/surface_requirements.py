from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import date as Date
from datetime import datetime, timedelta
from typing import Any

from .persistence import json_load


class SurfaceRequirementsRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_label: Callable[[Any], str],
        normalize_content_surface: Callable[[str | None], str],
        multi_surface_inventory_audit: Callable[..., dict[str, Any]],
        build_surface_inventory: Callable[..., dict[str, Any]],
        content_surfaces: tuple[str, ...],
    ) -> None:
        self.conn = conn
        self._creator_label = creator_label
        self._normalize_content_surface = normalize_content_surface
        self._multi_surface_inventory_audit = multi_surface_inventory_audit
        self._build_surface_inventory = build_surface_inventory
        self._content_surfaces = content_surfaces

    def account_surface_obligations_plan(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        target_date = datetime.fromisoformat(date).date()
        rows = self.conn.execute(
            """
            SELECT r.*, a.handle, a.external_id
            FROM account_content_requirements r
            LEFT JOIN accounts a ON a.id = r.account_id
            WHERE r.active = 1 AND LOWER(r.creator) = LOWER(?)
            ORDER BY r.account_id, r.content_surface
            """,
            (creator_label,),
        ).fetchall()
        by_account: dict[str, dict[str, Any]] = {}
        for row in rows:
            req = dict(row)
            account_id = req["account_id"]
            account = by_account.setdefault(
                account_id,
                {
                    "accountId": account_id,
                    "instagramAccountId": req.get("external_id"),
                    "username": req.get("handle"),
                    "surfaceStatus": {
                        surface: {
                            "needed": False,
                            "scheduled": False,
                            "completed": False,
                            "blockedReason": "",
                        }
                        for surface in self._content_surfaces
                    },
                },
            )
            surface = self._normalize_content_surface(req.get("content_surface"))
            if surface not in self._content_surfaces:
                continue
            active_today = self.requirement_active_on_date(req, target_date)
            scheduled = self.surface_scheduled_for_account(
                account_id, req.get("external_id"), surface, target_date
            )
            completed = self.surface_completed_for_account(
                account_id, req.get("external_id"), surface, target_date
            )
            needed = active_today and not scheduled and not completed
            blocked = ""
            if (
                needed
                and self._multi_surface_inventory_audit(creator=creator_label)[
                    "inventoryBySurface"
                ][surface]["scheduleSafe"]
                == 0
            ):
                blocked = "inventory_missing"
            account["surfaceStatus"][surface] = {
                "needed": bool(needed),
                "scheduled": bool(scheduled),
                "completed": bool(completed),
                "blockedReason": blocked,
            }
        return {
            "schema": "campaign_factory.account_surface_obligations_plan.v1",
            "creator": creator_label,
            "date": target_date.isoformat(),
            "accounts": list(by_account.values()),
            "wouldWrite": False,
        }

    def account_content_needs(
        self,
        *,
        account_id: str,
        creator: str | None = None,
        date: str,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator) if creator else None
        target_date = datetime.fromisoformat(date).date()
        rows = self.account_content_requirement_rows(
            creator=creator_label,
            account_id=account_id,
        )
        obligations = [
            self.content_obligation_for_requirement(dict(row), target_date)
            for row in rows
        ]
        surface_status = {
            surface: {
                "needed": False,
                "scheduled": 0,
                "completed": 0,
                "blocked": False,
                "overdue": False,
                "blockedReason": "",
            }
            for surface in self._content_surfaces
        }
        for obligation in obligations:
            surface_status[obligation["surface"]] = {
                "needed": obligation["needed"],
                "scheduled": obligation["scheduled"],
                "completed": obligation["completed"],
                "blocked": obligation["blocked"],
                "overdue": obligation["overdue"],
                "blockedReason": obligation["blockedReason"],
            }
        account_row = self.account_row_for_requirement_account(account_id)
        return {
            "schema": "campaign_factory.account_content_needs.v1",
            "creator": creator_label,
            "date": target_date.isoformat(),
            "accountId": account_row.get("id") if account_row else account_id,
            "account": account_row.get("handle") if account_row else account_id,
            "instagramAccountId": account_row.get("external_id")
            if account_row
            else None,
            "surfaceRequirementsTracked": list(self._content_surfaces),
            "obligations": obligations,
            "surfaceStatus": surface_status,
            "wouldWrite": False,
        }

    def account_surface_status(
        self,
        *,
        account_id: str,
        creator: str | None = None,
        date: str,
    ) -> dict[str, Any]:
        needs = self.account_content_needs(
            account_id=account_id,
            creator=creator,
            date=date,
        )
        return {
            "schema": "campaign_factory.account_surface_status.v1",
            "creator": needs.get("creator"),
            "date": needs.get("date"),
            "accountId": needs.get("accountId"),
            "account": needs.get("account"),
            "instagramAccountId": needs.get("instagramAccountId"),
            "trackedStates": list(self._content_surfaces),
            "surfaceStatus": needs.get("surfaceStatus") or {},
            "obligations": needs.get("obligations") or [],
            "wouldWrite": False,
        }

    def creator_content_needs(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        target_date = datetime.fromisoformat(date).date()
        rows = self.account_content_requirement_rows(creator=creator_label)
        by_account: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_account.setdefault(row["account_id"], []).append(dict(row))
        accounts: list[dict[str, Any]] = []
        totals = self.empty_surface_totals()
        for account_id in sorted(by_account):
            obligations = [
                self.content_obligation_for_requirement(req, target_date)
                for req in sorted(
                    by_account[account_id],
                    key=lambda item: self._normalize_content_surface(
                        item.get("content_surface")
                    ),
                )
            ]
            account_row = self.account_row_for_requirement_account(account_id)
            for obligation in obligations:
                self.add_obligation_to_totals(totals, obligation)
            accounts.append(
                {
                    "accountId": account_row.get("id") if account_row else account_id,
                    "account": account_row.get("handle") if account_row else account_id,
                    "instagramAccountId": account_row.get("external_id")
                    if account_row
                    else None,
                    "obligations": obligations,
                }
            )
        return {
            "schema": "campaign_factory.creator_content_needs.v1",
            "creator": creator_label,
            "date": target_date.isoformat(),
            "accountsAnalyzed": len(accounts),
            "surfaceRequirementsTracked": list(self._content_surfaces),
            "accounts": accounts,
            "totalsBySurface": totals,
            "wouldWrite": False,
        }

    def surface_gap_report(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        status = self.build_surface_status(creator=creator_label, date=date)
        needs = status["needs"]
        inventory = status["inventoryBySurface"]
        gaps: dict[str, dict[str, Any]] = {}
        for surface in self._content_surfaces:
            totals = needs["totalsBySurface"].get(surface) or {}
            needed = int(totals.get("remaining") or 0)
            available = int((inventory.get(surface) or {}).get("scheduleSafe") or 0)
            shortfall = max(0, needed - available)
            gaps[surface] = {
                "surface": surface,
                "required": int(totals.get("required") or 0),
                "completed": int(totals.get("completed") or 0),
                "scheduled": int(totals.get("scheduled") or 0),
                "needed": needed,
                "available": available,
                "shortfall": shortfall,
                "blocked": shortfall > 0,
                "blockedReason": "inventory_shortfall" if shortfall > 0 else "",
            }
        return {
            "schema": "campaign_factory.surface_gap_report.v1",
            "creator": creator_label,
            "date": datetime.fromisoformat(date).date().isoformat(),
            "accountsAnalyzed": needs["accountsAnalyzed"],
            "surfaceRequirementsTracked": list(self._content_surfaces),
            "surfaceGaps": gaps,
            "wouldWrite": False,
        }

    def build_surface_status(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        needs = self.creator_content_needs(creator=creator_label, date=date)
        inventory = (
            self._build_surface_inventory(creator=creator_label).get(
                "inventoryBySurface"
            )
            or {}
        )
        return {
            "creator": creator_label,
            "date": datetime.fromisoformat(date).date().isoformat(),
            "needs": needs,
            "inventoryBySurface": inventory,
            "wouldWrite": False,
        }

    def account_content_requirement_rows(
        self,
        *,
        creator: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["r.active = 1"]
        params: list[Any] = []
        if creator:
            clauses.append("LOWER(r.creator) = LOWER(?)")
            params.append(creator)
        if account_id:
            clauses.append("(r.account_id = ? OR a.external_id = ? OR a.handle = ?)")
            params.extend([account_id, account_id, account_id])
        rows = self.conn.execute(
            f"""
            SELECT r.*, a.handle, a.external_id
            FROM account_content_requirements r
            LEFT JOIN accounts a ON a.id = r.account_id
            WHERE {" AND ".join(clauses)}
            ORDER BY r.account_id, r.content_surface
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def account_row_for_requirement_account(
        self, account_id: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM accounts
            WHERE id = ? OR external_id = ? OR handle = ?
            LIMIT 1
            """,
            (account_id, account_id, account_id),
        ).fetchone()
        return dict(row) if row else None

    def content_obligation_for_requirement(
        self, requirement: dict[str, Any], target_date: Date
    ) -> dict[str, Any]:
        surface = self._normalize_content_surface(requirement.get("content_surface"))
        required = self.required_content_count(requirement, target_date)
        completed = self.surface_completed_count(
            requirement["account_id"],
            requirement.get("external_id"),
            surface,
            target_date,
        )
        scheduled = self.surface_scheduled_count(
            requirement["account_id"],
            requirement.get("external_id"),
            surface,
            target_date,
        )
        remaining = max(0, required - completed - scheduled)
        return {
            "account": requirement.get("handle")
            or requirement.get("external_id")
            or requirement["account_id"],
            "accountId": requirement["account_id"],
            "instagramAccountId": requirement.get("external_id"),
            "surface": surface,
            "cadence": requirement.get("cadence") or "daily",
            "required": required,
            "completed": completed,
            "scheduled": scheduled,
            "remaining": remaining,
            "needed": remaining > 0,
            "blocked": False,
            "overdue": False,
            "blockedReason": "",
        }

    def required_content_count(
        self, requirement: dict[str, Any], target_date: Date
    ) -> int:
        if not self.requirement_active_on_date(requirement, target_date):
            return 0
        cadence = str(requirement.get("cadence") or "daily").strip().lower()
        per_day = re.fullmatch(r"(\d+)[_-]per[_-]day", cadence)
        if per_day:
            return max(0, int(per_day.group(1)))
        if cadence in {
            "every_other_day",
            "alternate_days",
            "every_2_days",
            "every-other-day",
        }:
            if target_date.toordinal() % 2:
                return 0
        try:
            return max(0, int(requirement.get("max_per_day") or 0))
        except (TypeError, ValueError):
            return 0

    def empty_surface_totals(self) -> dict[str, dict[str, int]]:
        return {
            surface: {
                "required": 0,
                "completed": 0,
                "scheduled": 0,
                "remaining": 0,
                "accountsNeeding": 0,
            }
            for surface in self._content_surfaces
        }

    def add_obligation_to_totals(
        self, totals: dict[str, dict[str, int]], obligation: dict[str, Any]
    ) -> None:
        surface = obligation["surface"]
        if surface not in totals:
            return
        totals[surface]["required"] += int(obligation.get("required") or 0)
        totals[surface]["completed"] += int(obligation.get("completed") or 0)
        totals[surface]["scheduled"] += int(obligation.get("scheduled") or 0)
        totals[surface]["remaining"] += int(obligation.get("remaining") or 0)
        if obligation.get("needed"):
            totals[surface]["accountsNeeding"] += 1

    def requirement_active_on_date(
        self, requirement: dict[str, Any], target_date: Date
    ) -> bool:
        allowed_days = json_load(requirement.get("allowed_days"), [])
        if isinstance(allowed_days, list) and allowed_days:
            normalized_days = {int(day) for day in allowed_days if str(day).isdigit()}
            if (
                target_date.weekday() not in normalized_days
                and ((target_date.weekday() + 1) % 7) not in normalized_days
            ):
                return False
        cadence = str(requirement.get("cadence") or "daily").lower()
        if cadence in {"daily", "every_day"}:
            return True
        if cadence in {"weekly", "once_weekly"}:
            return True
        return True

    def surface_scheduled_count(
        self,
        account_id: str,
        instagram_account_id: str | None,
        surface: str,
        target_date: Date,
    ) -> int:
        start = f"{target_date.isoformat()}T00:00:00"
        end = f"{(target_date + timedelta(days=1)).isoformat()}T00:00:00"
        row = self.conn.execute(
            """
            SELECT COUNT(DISTINCT id) AS count FROM distribution_plans
            WHERE content_surface = ?
              AND (account_id = ? OR instagram_account_id = ?)
              AND planned_window_start >= ? AND planned_window_start < ?
            """,
            (surface, account_id, instagram_account_id, start, end),
        ).fetchone()
        return int(row["count"] or 0) if row else 0

    def surface_completed_count(
        self,
        account_id: str,
        instagram_account_id: str | None,
        surface: str,
        target_date: Date,
    ) -> int:
        start = f"{target_date.isoformat()}T00:00:00"
        end = f"{(target_date + timedelta(days=1)).isoformat()}T00:00:00"
        row = self.conn.execute(
            """
            SELECT COUNT(DISTINCT post_id) AS count FROM performance_snapshots
            WHERE content_surface = ?
              AND (account_id = ? OR instagram_account_id = ?)
              AND published_at >= ? AND published_at < ?
            """,
            (surface, account_id, instagram_account_id, start, end),
        ).fetchone()
        return int(row["count"] or 0) if row else 0

    def last_surface_posted_at(
        self,
        *,
        account_id: str,
        instagram_account_id: str | None,
        surface: str,
        before_date: Date,
    ) -> str | None:
        end = f"{before_date.isoformat()}T00:00:00"
        row = self.conn.execute(
            """
            SELECT published_at FROM performance_snapshots
            WHERE content_surface = ?
              AND (account_id = ? OR instagram_account_id = ?)
              AND published_at < ?
            ORDER BY published_at DESC
            LIMIT 1
            """,
            (surface, account_id, instagram_account_id, end),
        ).fetchone()
        return str(row["published_at"]) if row and row["published_at"] else None

    def surface_scheduled_for_account(
        self,
        account_id: str,
        instagram_account_id: str | None,
        surface: str,
        target_date: Date,
    ) -> bool:
        start = f"{target_date.isoformat()}T00:00:00"
        end = f"{(target_date + timedelta(days=1)).isoformat()}T00:00:00"
        row = self.conn.execute(
            """
            SELECT 1 FROM distribution_plans
            WHERE content_surface = ?
              AND (account_id = ? OR instagram_account_id = ?)
              AND planned_window_start >= ? AND planned_window_start < ?
            LIMIT 1
            """,
            (surface, account_id, instagram_account_id, start, end),
        ).fetchone()
        return bool(row)

    def surface_completed_for_account(
        self,
        account_id: str,
        instagram_account_id: str | None,
        surface: str,
        target_date: Date,
    ) -> bool:
        start = f"{target_date.isoformat()}T00:00:00"
        end = f"{(target_date + timedelta(days=1)).isoformat()}T00:00:00"
        row = self.conn.execute(
            """
            SELECT 1 FROM performance_snapshots
            WHERE content_surface = ?
              AND (account_id = ? OR instagram_account_id = ?)
              AND published_at >= ? AND published_at < ?
            LIMIT 1
            """,
            (surface, account_id, instagram_account_id, start, end),
        ).fetchone()
        return bool(row)
