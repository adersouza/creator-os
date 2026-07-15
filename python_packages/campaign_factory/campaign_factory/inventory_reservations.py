from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from .account_eligibility import enforce_account_eligibility
from .assignment_eligibility import (
    enforce_assignment_eligibility,
    persist_assignment_origin,
)

DEFAULT_REUSE_COOLDOWN_DAYS = 14


class InventoryReservationRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        utc_now: Callable[[], str],
        normalize_content_surface: Callable[[str | None], str],
        rendered_asset: Callable[[str], dict[str, Any]],
        ensure_rendered_asset_perceptual_metadata: Callable[..., dict[str, Any]],
        asset_uniqueness_values: Callable[..., dict[str, str]],
        default_reservation_ttl_days: int,
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._utc_now = utc_now
        self._normalize_content_surface = normalize_content_surface
        self._rendered_asset = rendered_asset
        self._ensure_rendered_asset_perceptual_metadata = (
            ensure_rendered_asset_perceptual_metadata
        )
        self._asset_uniqueness_values = asset_uniqueness_values
        self._default_reservation_ttl_days = default_reservation_ttl_days

    def reserve_inventory_asset(
        self,
        asset_id: str,
        *,
        account_id: str | None = None,
        surface: str | None = None,
        reserved_by: str = "campaign_factory",
        expires_at: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        reuse_cooldown_days: int = DEFAULT_REUSE_COOLDOWN_DAYS,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        asset = self._ensure_rendered_asset_perceptual_metadata(asset_id)
        normalized_surface = self._normalize_content_surface(
            surface or asset.get("content_surface") or "reel"
        )
        uniqueness = self._asset_uniqueness_values(asset, metadata=metadata)
        now = self._utc_now()
        expires_at = (
            expires_at
            or (
                datetime.fromisoformat(now)
                + timedelta(days=self._default_reservation_ttl_days)
            ).isoformat()
        )
        self.expire_inventory_reservations(now=now)
        if idempotency_key:
            existing = self.conn.execute(
                "SELECT * FROM asset_inventory_reservations WHERE idempotency_key = ? AND status IN ('pending', 'committed')",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return dict(existing)
        if account_id:
            account = self.conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if not account:
                raise ValueError(f"account not found: {account_id}")
        account_eligibility = enforce_account_eligibility(
            self.conn,
            account_id=account_id,
            surface=normalized_surface,
            planned_at=now,
        )
        eligibility = enforce_assignment_eligibility(
            self.conn,
            rendered_asset_id=asset_id,
            account_id=account_id,
            planned_at=now,
            surface=normalized_surface,
            reuse_window_days=reuse_cooldown_days,
        )
        reservation_id = self._new_id("invres")
        row_id = self._new_id("invresrow")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "within a transaction" not in str(exc).lower():
                raise
        self.expire_inventory_reservations(now=now, commit=False)
        active = self.conn.execute(
            """
            SELECT * FROM asset_inventory_reservations
            WHERE asset_id = ? AND status IN ('pending', 'committed')
            ORDER BY reserved_at DESC
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if active:
            self.conn.rollback()
            raise ValueError(f"asset already has an active reservation: {asset_id}")
        reuse_conflicts = self.inventory_uniqueness_conflicts(
            asset,
            uniqueness=uniqueness,
            surface=normalized_surface,
            cooldown_days=reuse_cooldown_days,
            account_id=account_id,
        )
        if reuse_conflicts and not override_reason:
            self.conn.rollback()
            raise ValueError(
                "cross-account source/perceptual reuse cooldown conflict: "
                + ",".join(item["assetId"] for item in reuse_conflicts[:5])
            )
        self.conn.execute(
            """
            INSERT INTO asset_inventory_reservations
            (id, asset_id, campaign_id, account_id, surface, reservation_id, reserved_by,
             reserved_at, expires_at, status, idempotency_key, source_family_id,
             perceptual_fingerprint, perceptual_cluster_id, account_group_id,
             reuse_cooldown_days, override_reason, account_eligibility_json,
             assignment_eligibility_json,
             metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                asset_id,
                asset["campaign_id"],
                account_id,
                normalized_surface,
                reservation_id,
                reserved_by,
                now,
                expires_at,
                idempotency_key,
                uniqueness["sourceFamilyId"],
                uniqueness["perceptualFingerprint"],
                uniqueness["perceptualClusterId"],
                uniqueness["accountGroupId"],
                reuse_cooldown_days,
                override_reason,
                json.dumps(account_eligibility, ensure_ascii=False, sort_keys=True),
                json.dumps(eligibility, ensure_ascii=False, sort_keys=True),
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        persist_assignment_origin(self.conn, eligibility)
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM asset_inventory_reservations WHERE id = ?", (row_id,)
            ).fetchone()
        )

    def expire_inventory_reservations(
        self, *, now: str | None = None, commit: bool = True
    ) -> int:
        current = now or self._utc_now()
        cursor = self.conn.execute(
            """
            UPDATE asset_inventory_reservations
            SET status = 'expired', updated_at = ?
            WHERE status IN ('pending', 'committed')
              AND expires_at IS NOT NULL
              AND expires_at != ''
              AND expires_at <= ?
            """,
            (current, current),
        )
        if commit and cursor.rowcount:
            self.conn.commit()
        return int(cursor.rowcount or 0)

    def release_inventory_reservation(
        self,
        reservation_id: str,
        *,
        status: str = "released",
    ) -> dict[str, Any]:
        if status not in {"released", "expired", "cancelled"}:
            raise ValueError("status must be released, expired, or cancelled")
        row = self.conn.execute(
            "SELECT * FROM asset_inventory_reservations WHERE reservation_id = ? OR id = ?",
            (reservation_id, reservation_id),
        ).fetchone()
        if not row:
            raise ValueError(f"reservation not found: {reservation_id}")
        now = self._utc_now()
        self.conn.execute(
            "UPDATE asset_inventory_reservations SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, row["id"]),
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM asset_inventory_reservations WHERE id = ?", (row["id"],)
            ).fetchone()
        )

    def inventory_uniqueness_conflicts(
        self,
        asset: dict[str, Any],
        *,
        uniqueness: dict[str, str],
        surface: str,
        cooldown_days: int,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        keys = {
            "sourceFamilyId": uniqueness.get("sourceFamilyId") or "",
            "perceptualClusterId": uniqueness.get("perceptualClusterId") or "",
        }
        if not any(keys.values()):
            return []
        now = datetime.fromisoformat(self._utc_now())
        cutoff = (now - timedelta(days=max(0, int(cooldown_days or 0)))).isoformat()
        conflicts: list[dict[str, Any]] = []
        for key_name, value in keys.items():
            if not value:
                continue
            column = (
                "source_family_id"
                if key_name == "sourceFamilyId"
                else "perceptual_cluster_id"
            )
            rows = self.conn.execute(
                f"""
                SELECT asset_id, account_id, reserved_at, status
                FROM asset_inventory_reservations
                WHERE campaign_id = ? AND surface = ? AND {column} = ?
                  AND status IN ('pending', 'committed')
                  AND asset_id <> ?
                  AND reserved_at >= ?
                """,
                (asset["campaign_id"], surface, value, asset["id"], cutoff),
            ).fetchall()
            for row in rows:
                if account_id and row["account_id"] == account_id:
                    continue
                conflicts.append(
                    {
                        "assetId": row["asset_id"],
                        "reason": f"active_reservation_{column}",
                        "status": row["status"],
                    }
                )
            assigned = self.conn.execute(
                """
                SELECT a.rendered_asset_id, a.account_id, a.created_at
                FROM asset_account_assignments a
                JOIN rendered_assets r ON r.id = a.rendered_asset_id
                WHERE a.campaign_id = ? AND r.content_surface = ? AND r.id <> ?
                  AND a.created_at >= ?
                """,
                (asset["campaign_id"], surface, asset["id"], cutoff),
            ).fetchall()
            for row in assigned:
                other = self._rendered_asset(row["rendered_asset_id"])
                other_values = self._asset_uniqueness_values(other)
                if other_values.get(key_name) != value:
                    continue
                if account_id and row["account_id"] == account_id:
                    continue
                conflicts.append(
                    {
                        "assetId": row["rendered_asset_id"],
                        "reason": f"assigned_{column}",
                        "status": "assigned",
                    }
                )
        return conflicts

    def reservation_adjusted_inventory(
        self,
        readiness_rows: list[dict[str, Any]],
        *,
        content_surface: str | None = None,
    ) -> dict[str, int]:
        self.expire_inventory_reservations()
        active_asset_ids = [
            str(row.get("assetId"))
            for row in readiness_rows
            if row.get("canHandoff")
            and row.get("assetId")
            and (
                content_surface is None or row.get("contentSurface") == content_surface
            )
        ]
        if not active_asset_ids:
            return {
                "grossInventory": 0,
                "reservedInventory": 0,
                "usedInventory": 0,
                "cooldownBlockedInventory": 0,
                "netInventory": 0,
            }
        placeholders = ",".join("?" for _ in active_asset_ids)
        params = sorted(active_asset_ids)
        reserved_rows = self.conn.execute(
            f"""
            SELECT DISTINCT asset_id
            FROM asset_inventory_reservations
            WHERE asset_id IN ({placeholders})
              AND status IN ('pending', 'committed')
            """,
            params,
        ).fetchall()
        assignment_rows = self.conn.execute(
            f"""
            SELECT DISTINCT rendered_asset_id
            FROM asset_account_assignments
            WHERE rendered_asset_id IN ({placeholders})
            """,
            params,
        ).fetchall()
        reserved = {str(row["asset_id"]) for row in reserved_rows}
        used = {str(row["rendered_asset_id"]) for row in assignment_rows}
        reserved_or_used = reserved | used
        assets_by_id = {
            str(row["id"]): dict(row)
            for row in self.conn.execute(
                f"SELECT * FROM rendered_assets WHERE id IN ({placeholders})",
                params,
            ).fetchall()
        }
        blocked_keys: set[tuple[str, str]] = set()
        for asset_id in reserved_or_used:
            asset = assets_by_id.get(asset_id)
            if not asset:
                continue
            asset = self._ensure_rendered_asset_perceptual_metadata(asset_id)
            assets_by_id[asset_id] = asset
            values = self._asset_uniqueness_values(asset)
            for key_name in ("sourceFamilyId", "perceptualClusterId"):
                value = values.get(key_name) or ""
                if value:
                    blocked_keys.add((key_name, value))
        cooldown_blocked: set[str] = set()
        for asset_id, asset in assets_by_id.items():
            if asset_id in reserved_or_used:
                continue
            asset = self._ensure_rendered_asset_perceptual_metadata(asset_id)
            assets_by_id[asset_id] = asset
            values = self._asset_uniqueness_values(asset)
            if any(
                (key_name, values.get(key_name) or "") in blocked_keys
                for key_name in ("sourceFamilyId", "perceptualClusterId")
            ):
                cooldown_blocked.add(asset_id)
        unavailable = reserved | used
        unavailable |= cooldown_blocked
        return {
            "grossInventory": len(active_asset_ids),
            "reservedInventory": len(reserved),
            "usedInventory": len(used),
            "cooldownBlockedInventory": len(cooldown_blocked),
            "netInventory": max(0, len(active_asset_ids) - len(unavailable)),
        }
