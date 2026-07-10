from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_assignment_eligibility

SCHEMA = "campaign_factory.assignment_eligibility.v1"
DEFAULT_REUSE_WINDOW_DAYS = 14


class AssignmentEligibilityError(ValueError):
    def __init__(self, decision: dict[str, Any]) -> None:
        self.decision = decision
        reasons = ",".join(decision.get("reasonCodes") or ["assignment_ineligible"])
        super().__init__(f"assignment eligibility blocked: {reasons}")


def asset_identity(asset: dict[str, Any]) -> dict[str, str]:
    metadata = _json_object(asset.get("metadata_json"))
    generation = _json_object(asset.get("caption_generation_json"))
    lineage = generation.get("generatedAssetLineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    source_family = _first(
        metadata.get("sourceFamilyId"),
        metadata.get("source_family_id"),
        generation.get("sourceFamilyId"),
        generation.get("source_family_id"),
        _recursive_value(lineage, "sourceFamilyId", "source_family_id"),
        asset.get("parent_asset_id"),
        asset.get("parent_reel_id"),
    )
    perceptual = _first(
        metadata.get("perceptualFingerprint"),
        metadata.get("perceptual_fingerprint"),
        generation.get("perceptualFingerprint"),
        generation.get("perceptual_fingerprint"),
        _recursive_value(lineage, "perceptualFingerprint", "perceptual_fingerprint"),
    )
    cluster = _first(
        metadata.get("perceptualClusterId"),
        metadata.get("perceptual_cluster_id"),
        generation.get("perceptualClusterId"),
        generation.get("perceptual_cluster_id"),
        _recursive_value(lineage, "perceptualClusterId", "perceptual_cluster_id"),
        perceptual,
    )
    return {
        "contentFingerprint": _first(
            _recursive_value(lineage, "contentFingerprint", "content_fingerprint"),
            asset.get("content_hash"),
        ),
        "sourceFamilyId": source_family,
        "perceptualFingerprint": perceptual,
        "perceptualClusterId": cluster,
    }


def evaluate_assignment_eligibility(
    conn: sqlite3.Connection,
    *,
    rendered_asset_id: str,
    account_id: str | None,
    instagram_account_id: str | None = None,
    planned_at: str | None = None,
    surface: str | None = None,
    account_group_id: str | None = None,
    reuse_window_days: int = DEFAULT_REUSE_WINDOW_DAYS,
) -> dict[str, Any]:
    asset_row = conn.execute(
        "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
    ).fetchone()
    if not asset_row:
        raise ValueError(f"rendered asset not found: {rendered_asset_id}")
    asset = dict(asset_row)
    destination = _destination_account_id(
        conn, account_id=account_id, instagram_account_id=instagram_account_id
    )
    group_id = _account_group_id(
        conn,
        account_id=account_id,
        destination_account_id=destination,
        explicit=account_group_id,
        fallback=str(asset.get("campaign_id") or ""),
    )
    identity = asset_identity(asset)
    origin = _canonical_account_id(conn, str(asset.get("origin_account_id") or ""))
    when = _parse_time(planned_at) or datetime.now(UTC)
    reason_codes: list[str] = []
    matches: list[dict[str, Any]] = []

    if destination and not (
        identity["sourceFamilyId"] or identity["perceptualFingerprint"]
    ):
        if origin and origin != destination:
            reason_codes.append("missing_identity_metadata")
    elif destination:
        matches = _reuse_matches(
            conn,
            asset=asset,
            destination_account_id=destination,
            account_group_id=group_id,
            identity=identity,
            planned_at=when,
            reuse_window_days=reuse_window_days,
        )
        for match in matches:
            reason = str(match["reason"])
            if reason not in reason_codes:
                reason_codes.append(reason)

    return {
        "schema": SCHEMA,
        "allowed": not reason_codes,
        "reasonCodes": reason_codes,
        "inputs": {
            "renderedAssetId": rendered_asset_id,
            "campaignId": asset["campaign_id"],
            "accountId": destination or None,
            "instagramAccountId": instagram_account_id,
            "accountGroupId": group_id,
            "surface": surface,
            "plannedAt": when.replace(microsecond=0).isoformat(),
            "reuseWindowDays": int(reuse_window_days),
            **identity,
            "originAccountId": origin or (destination if destination else None),
        },
        "matches": matches,
        "policy": {
            "missingIdentity": "origin_account_only",
            "crossAccountReuseWindowDays": int(reuse_window_days),
        },
        "auto_posting": False,
    }


def enforce_assignment_eligibility(
    conn: sqlite3.Connection,
    **kwargs: Any,
) -> dict[str, Any]:
    decision = evaluate_assignment_eligibility(conn, **kwargs)
    if not decision["allowed"]:
        raise AssignmentEligibilityError(decision)
    destination = str(decision["inputs"].get("accountId") or "")
    rendered_asset_id = str(decision["inputs"]["renderedAssetId"])
    if destination:
        conn.execute(
            """
            UPDATE rendered_assets
            SET origin_account_id = COALESCE(NULLIF(origin_account_id, ''), ?)
            WHERE id = ?
            """,
            (destination, rendered_asset_id),
        )
    return decision


def write_assignment_eligibility_artifact(
    decision: dict[str, Any], output_path: Path
) -> Path:
    validate_assignment_eligibility(decision)
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(decision, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _reuse_matches(
    conn: sqlite3.Connection,
    *,
    asset: dict[str, Any],
    destination_account_id: str,
    account_group_id: str,
    identity: dict[str, str],
    planned_at: datetime,
    reuse_window_days: int,
) -> list[dict[str, Any]]:
    cutoff_start = planned_at - timedelta(days=max(0, int(reuse_window_days)))
    cutoff_end = planned_at + timedelta(days=max(0, int(reuse_window_days)))
    candidates: list[dict[str, Any]] = []
    table_queries = (
        (
            "asset_account_assignments",
            """
            SELECT a.id record_id, a.rendered_asset_id, a.account_id,
                   a.instagram_account_id, a.account_group_id, a.created_at event_at
            FROM asset_account_assignments a
            WHERE a.campaign_id = ?
            """,
        ),
        (
            "distribution_plans",
            """
            SELECT d.id record_id, d.rendered_asset_id, d.account_id,
                   d.instagram_account_id, d.account_group_id,
                   COALESCE(d.planned_window_start, d.created_at) event_at
            FROM distribution_plans d
            WHERE d.campaign_id = ?
            """,
        ),
        (
            "asset_inventory_reservations",
            """
            SELECT r.id record_id, r.asset_id rendered_asset_id, r.account_id,
                   NULL instagram_account_id, r.account_group_id, r.reserved_at event_at
            FROM asset_inventory_reservations r
            WHERE r.campaign_id = ?
              AND r.status IN ('pending', 'committed')
            """,
        ),
        (
            "promotions",
            """
            SELECT p.id record_id, p.rendered_asset_id, p.account_id,
                   NULL instagram_account_id, NULL account_group_id, p.created_at event_at
            FROM promotions p
            WHERE p.campaign_id = ?
            """,
        ),
    )
    for source, query in table_queries:
        for row in conn.execute(query, (asset["campaign_id"],)).fetchall():
            item = dict(row)
            item["source"] = source
            candidates.append(item)

    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        prior_destination = _destination_account_id(
            conn,
            account_id=candidate.get("account_id"),
            instagram_account_id=candidate.get("instagram_account_id"),
        )
        if not prior_destination or prior_destination == destination_account_id:
            continue
        prior_time = _parse_time(candidate.get("event_at"))
        if not prior_time or not cutoff_start <= prior_time <= cutoff_end:
            continue
        prior_group = str(candidate.get("account_group_id") or "")
        if prior_group and account_group_id and prior_group != account_group_id:
            continue
        prior_row = conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?",
            (candidate["rendered_asset_id"],),
        ).fetchone()
        if not prior_row:
            continue
        prior_identity = asset_identity(dict(prior_row))
        reasons: list[str] = []
        if (
            identity["contentFingerprint"]
            and prior_identity["contentFingerprint"] == identity["contentFingerprint"]
        ):
            reasons.append("exact_content_reuse_window")
        if (
            identity["sourceFamilyId"]
            and prior_identity["sourceFamilyId"] == identity["sourceFamilyId"]
        ):
            reasons.append("source_family_reuse_window")
        if identity["perceptualFingerprint"] and (
            prior_identity["perceptualFingerprint"] == identity["perceptualFingerprint"]
            or (
                identity["perceptualClusterId"]
                and prior_identity["perceptualClusterId"]
                == identity["perceptualClusterId"]
            )
        ):
            reasons.append("perceptual_reuse_window")
        for reason in reasons:
            key = (reason, str(candidate["source"]), str(candidate["record_id"]))
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                {
                    "reason": reason,
                    "source": candidate["source"],
                    "recordId": candidate["record_id"],
                    "renderedAssetId": candidate["rendered_asset_id"],
                    "accountId": prior_destination,
                    "eventAt": prior_time.replace(microsecond=0).isoformat(),
                }
            )
    return matches


def _destination_account_id(
    conn: sqlite3.Connection,
    *,
    account_id: Any,
    instagram_account_id: Any,
) -> str:
    account = str(account_id or "").strip()
    if account:
        return account
    external = str(instagram_account_id or "").strip()
    if not external:
        return ""
    row = conn.execute(
        "SELECT id FROM accounts WHERE external_id = ? LIMIT 1", (external,)
    ).fetchone()
    return str(row["id"] if row else external)


def _canonical_account_id(conn: sqlite3.Connection, value: str) -> str:
    if not value:
        return ""
    row = conn.execute(
        "SELECT id FROM accounts WHERE id = ? OR external_id = ? LIMIT 1",
        (value, value),
    ).fetchone()
    return str(row["id"] if row else value)


def _account_group_id(
    conn: sqlite3.Connection,
    *,
    account_id: str | None,
    destination_account_id: str,
    explicit: str | None,
    fallback: str,
) -> str:
    if explicit:
        return str(explicit)
    lookup = str(account_id or destination_account_id or "")
    row = conn.execute(
        "SELECT account_group_id, model_id FROM accounts WHERE id = ?", (lookup,)
    ).fetchone()
    if row:
        return str(row["account_group_id"] or row["model_id"] or fallback)
    return fallback


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _recursive_value(value: Any, *keys: str) -> Any:
    stack = [value]
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        for key in keys:
            if current.get(key) not in (None, ""):
                return current[key]
        stack.extend(item for item in current.values() if isinstance(item, dict))
    return None


def _first(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
