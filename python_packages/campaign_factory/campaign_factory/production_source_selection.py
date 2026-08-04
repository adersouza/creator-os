"""Exact approved-source selection shared by supervised production callers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from creator_os_core.fileops import sha256_file

from .production_creative_evidence import (
    prepare_source_creative_evidence,
    source_approval_binding,
)

CREATION_ENABLED_CREATORS: Final = frozenset({"larissa", "stacey"})


def require_creation_enabled_creator(creator: str) -> str:
    """Fail closed before planning any new Creator OS content."""

    creator_slug = str(creator or "").strip().lower()
    if creator_slug not in CREATION_ENABLED_CREATORS:
        allowed = ", ".join(sorted(CREATION_ENABLED_CREATORS))
        raise PermissionError(
            f"creator_creation_not_enabled:{creator_slug or 'missing'}; "
            f"allowed creators: {allowed}"
        )
    return creator_slug


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
    creator = require_creation_enabled_creator(creator)
    identity = factory.domains.creator_governance.active_identity_profile(
        creator, provider="higgsfield"
    )
    return str(identity["creator_slug"]), str(identity["provider_identity_id"])


def resolve_reference_analysis_governance(factory: Any, creator: str) -> dict[str, Any]:
    """Resolve reference-use authority before reading or analyzing reference media."""

    creator = require_creation_enabled_creator(creator)
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


def resolve_production_sources(
    factory: Any,
    *,
    creator: str,
    soul_id: str,
    campaign: str | None,
    execution: str,
    planned_anchor: Mapping[str, Any] | None,
    selected_source_asset_ids: tuple[str, ...] | None,
    accounts: str | None,
) -> list[dict[str, Any]]:
    """Resolve exact eligible inventory, including a Soul-bound recreation anchor."""

    soul_bound_anchor = planned_anchor is not None and isinstance(
        planned_anchor.get("soulIdentity"), Mapping
    )
    if soul_bound_anchor:
        _validate_current_soul_identity(
            factory,
            creator=creator,
            soul_id=soul_id,
            soul_identity=dict(planned_anchor["soulIdentity"]),
        )
        rows = []
        sources = [
            _approved_soul_anchor_source(
                factory,
                approval=planned_anchor,
                creator=creator,
                campaign=campaign,
            )
        ]
    else:
        rows = factory.conn.execute(
            """
            SELECT s.*, c.slug AS campaign_slug, m.slug AS creator_slug
            FROM source_assets s
            JOIN campaigns c ON c.id = s.campaign_id
            JOIN models m ON m.id = s.model_id
            WHERE lower(m.slug) = ? AND s.media_type = 'image'
              AND lower(COALESCE(s.status, 'imported')) = 'approved'
              AND (? IS NULL OR lower(c.slug) = lower(?) OR c.id = ?)
            ORDER BY c.updated_at DESC, s.created_at DESC, s.id
            """,
            (creator, campaign, campaign, campaign),
        ).fetchall()
        sources = []
    seen_source_hashes: set[str] = set()
    substituted_sources = 0
    incompatible_sources = 0
    for row in rows:
        source = dict(row)
        raw_path = Path(str(source["stored_path"])).expanduser()
        if raw_path.is_symlink():
            substituted_sources += 1
            continue
        path = raw_path.resolve()
        recorded_sha = str(source["content_hash"])
        if (
            planned_anchor is not None
            and recorded_sha != planned_anchor["creatorImageSha256"]
        ):
            incompatible_sources += 1
            continue
        if not path.is_file() or sha256_file(path) != recorded_sha:
            substituted_sources += 1
            continue
        if recorded_sha in seen_source_hashes:
            continue
        if execution == "cloud":
            resolution = source_image_resolution(path)
            if resolution is None:
                substituted_sources += 1
                continue
            width, height = resolution
            ratio = width / height
            source["sourceResolution"] = {
                "width": width,
                "height": height,
                "aspectRatio": round(ratio, 6),
            }
        prepare_source_creative_evidence(source)
        source["sourceApproval"] = source_approval_binding(factory, source)
        if source["compatibility"]["hardBlockers"]:
            incompatible_sources += 1
            continue
        source["stored_path"] = str(path)
        seen_source_hashes.add(recorded_sha)
        sources.append(source)
    if not sources:
        if planned_anchor is not None:
            raise ValueError(
                "approved anchor creator image is not exact approved inventory"
            )
        if incompatible_sources:
            raise ValueError(
                f"no portrait-reel approved image inventory for creator {creator}"
            )
        if substituted_sources:
            raise ValueError(
                f"approved source SHA mismatch for creator {creator}; "
                "refresh source inventory before generation"
            )
        raise ValueError(
            f"no explicitly approved image inventory for creator {creator}; "
            "review and approve sources with `creator-os sources`"
        )
    sources = select_requested_source_assets(sources, selected_source_asset_ids)
    bind_source_governance(
        factory,
        sources,
        creator=creator,
        soul_id=soul_id,
        account_id=resolved_account_id(factory.conn, accounts),
    )
    return sources


def _validate_current_soul_identity(
    factory: Any,
    *,
    creator: str,
    soul_id: str,
    soul_identity: Mapping[str, Any],
) -> None:
    active = factory.domains.creator_governance.active_identity_profile(
        creator, provider="higgsfield"
    )
    if (
        soul_identity.get("schema")
        != "campaign_factory.verified_soul_identity_binding.v1"
        or soul_identity.get("creatorSlug") != creator
        or soul_identity.get("provider") != "higgsfield"
        or soul_identity.get("soulId") != soul_id
        or soul_identity.get("soulId") != active.get("provider_identity_id")
        or soul_identity.get("identityProfileId") != active.get("id")
        or soul_identity.get("identityProfileVersion") != active.get("version")
        or soul_identity.get("identityProfileFingerprint")
        != active.get("profile_fingerprint")
    ):
        raise PermissionError("recreation_anchor_soul_identity_binding_mismatch")


def _approved_soul_anchor_source(
    factory: Any,
    *,
    approval: Mapping[str, Any],
    creator: str,
    campaign: str | None,
) -> dict[str, Any]:
    row = factory.conn.execute(
        """
        SELECT s.*, c.slug AS campaign_slug, m.slug AS creator_slug
        FROM source_assets s
        JOIN campaigns c ON c.id = s.campaign_id
        JOIN models m ON m.id = s.model_id
        WHERE lower(m.slug) = ? AND s.media_type = 'image'
          AND s.content_hash = ?
          AND lower(COALESCE(s.status, 'imported')) = 'approved_recreation_anchor'
          AND (? IS NULL OR lower(c.slug) = lower(?) OR c.id = ?)
        ORDER BY c.updated_at DESC, s.created_at DESC, s.id
        LIMIT 1
        """,
        (creator, approval["anchorFileSha256"], campaign, campaign, campaign),
    ).fetchone()
    if row is None:
        raise PermissionError("approved_recreation_anchor_registration_missing")
    anchor = Path(str(approval["anchorFilePath"])).expanduser()
    if (
        anchor.is_symlink()
        or not anchor.is_file()
        or sha256_file(anchor.resolve()) != approval["anchorFileSha256"]
    ):
        raise PermissionError("approved_recreation_anchor_sha_mismatch")
    resolution = source_image_resolution(anchor.resolve())
    if resolution is None:
        raise ValueError("approved_recreation_anchor_is_not_an_image")
    width, height = resolution
    source = {
        **dict(row),
        "stored_path": str(anchor.resolve()),
        "original_path": str(anchor.resolve()),
        "filename": anchor.name,
        "content_hash": str(approval["anchorFileSha256"]),
        "sourceResolution": {
            "width": width,
            "height": height,
            "aspectRatio": round(width / height, 6),
        },
        "sourceApproval": None,
    }
    prepare_source_creative_evidence(source)
    if source["compatibility"]["hardBlockers"]:
        raise PermissionError("approved_recreation_anchor_incompatible")
    return source
