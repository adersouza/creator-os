"""Exact approved-source selection shared by supervised production callers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def optional_safe_media(path: Path | None, label: str) -> Path | None:
    if path is None:
        return None
    expanded = Path(path).expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} is missing: {resolved}")
    return resolved


def source_image_resolution(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image, UnidentifiedImageError

        with Image.open(path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        return None
    if width <= 0 or height <= 0:
        return None
    return int(width), int(height)


def active_production_identity(factory: Any, creator: str) -> tuple[str, str]:
    identity = factory.domains.creator_governance.active_identity_profile(
        creator, provider="higgsfield"
    )
    return str(identity["creator_slug"]), str(identity["provider_identity_id"])


def resolve_reference_analysis_governance(factory: Any, creator: str) -> dict[str, Any]:
    """Resolve reference-use authority before reading or analyzing reference media."""

    identity = factory.domains.creator_governance.active_identity_profile(
        creator, provider="internal"
    )
    rows = factory.conn.execute(
        """
        SELECT cg.campaign_id
        FROM campaign_governance cg
        WHERE cg.model_id = ?
          AND cg.lifecycle_status IN (
            'configured', 'reference_ready', 'source_ready', 'production_ready'
          )
        ORDER BY
          CASE cg.lifecycle_status
            WHEN 'production_ready' THEN 0
            WHEN 'source_ready' THEN 1
            WHEN 'reference_ready' THEN 2
            WHEN 'configured' THEN 3
            ELSE 4
          END,
          cg.campaign_id
        """,
        (identity["creator_id"],),
    ).fetchall()
    last_error: PermissionError | None = None
    for row in rows:
        try:
            return factory.domains.creator_governance.resolve_operation(
                creator=str(identity["creator_id"]),
                campaign=str(row["campaign_id"]),
                operation="reference_analysis",
                provider="internal",
            )
        except PermissionError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise PermissionError("reference_analysis_campaign_missing")


def resolved_account_id(conn: Any, requested: str | None) -> str | None:
    raw = str(requested or "").strip()
    if not raw or "," in raw:
        return None
    try:
        rows = conn.execute(
            """
            SELECT id FROM accounts
            WHERE id = ? OR external_id = ? OR lower(handle) = lower(?)
            ORDER BY id
            """,
            (raw, raw, raw.lstrip("@")),
        ).fetchall()
    except Exception:
        return None
    return str(rows[0]["id"]) if len(rows) == 1 else None


def bind_source_governance(
    factory: Any,
    sources: list[dict[str, Any]],
    *,
    creator: str,
    soul_id: str,
    account_id: str | None,
) -> None:
    for source in sources:
        context = factory.domains.creator_governance.resolve_operation(
            creator=creator,
            campaign=str(source["campaign_id"]),
            operation="generation",
            provider="higgsfield",
            source_asset_id=str(source["id"]),
            account_id=account_id,
        )
        if context["providerIdentityId"] != soul_id:
            raise PermissionError("creator_identity_profile_changed_during_plan")
        source["creatorGovernance"] = context


def select_requested_source_assets(
    sources: list[dict[str, Any]],
    selected_source_asset_ids: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    if selected_source_asset_ids is None:
        return sources
    requested = tuple(
        str(value).strip() for value in selected_source_asset_ids if str(value).strip()
    )
    if not requested:
        raise ValueError("selected source asset IDs cannot be empty")
    available = {str(source["id"]): source for source in sources}
    missing = [source_id for source_id in requested if source_id not in available]
    if missing:
        raise ValueError(
            "selected source is not an approved compatible creator asset: "
            + ", ".join(missing)
        )
    return [available[source_id] for source_id in requested]
