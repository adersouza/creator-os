from __future__ import annotations

from typing import Any

from ..core import CampaignFactory


def active_inventory_reservation(
    factory: CampaignFactory,
    *,
    rendered_asset_id: str,
    account_id: str | None,
) -> dict[str, Any] | None:
    if not account_id:
        return None
    row = factory.conn.execute(
        """
        SELECT *
        FROM asset_inventory_reservations
        WHERE asset_id = ? AND account_id = ?
          AND status IN ('pending', 'committed')
        ORDER BY reserved_at DESC
        LIMIT 1
        """,
        (rendered_asset_id, account_id),
    ).fetchone()
    return dict(row) if row else None
