"""Computed Reddit working-shelf views over canonical assets and task snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from creator_os_core.evidence_attestation import payload_fingerprint
from creator_os_core.fileops import sha256_file

from .assignment_eligibility import asset_identity

ACTIVE_TASK_STATES = {
    "pending",
    "scheduled",
    "notification_pending",
    "notified",
    "notification_unavailable",
    "opened",
    "prepared",
    "title_copied",
    "media_downloaded",
    "media_shared",
    "correct_account_confirmed",
}


def _record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        parsed = {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _value(row: dict[str, Any], snake: str, camel: str | None = None) -> Any:
    return row.get(snake, row.get(camel or snake))


def _when(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _matches(task: dict[str, Any], identity: dict[str, str], media_sha: str) -> bool:
    return bool(
        _value(task, "source_family_id", "sourceFamilyId") == identity["sourceFamilyId"]
        or _value(task, "perceptual_cluster_id", "perceptualClusterId")
        == identity["perceptualClusterId"]
        or _value(task, "media_sha256", "mediaSha256") == media_sha
    )


def _current_rule(subreddits: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    normalized = name.lower()
    return next(
        (
            row
            for row in subreddits
            if str(_value(row, "name") or "").lower() == normalized
        ),
        None,
    )


def _current_account(
    accounts: list[dict[str, Any]], username: str
) -> dict[str, Any] | None:
    normalized = username.lower()
    return next(
        (
            row
            for row in accounts
            if str(_value(row, "username") or "").lower() == normalized
        ),
        None,
    )


def _permanent_owner(
    owners: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    identity: dict[str, str],
    media_sha: str,
) -> tuple[str | None, bool]:
    values = {
        ("source_family", identity["sourceFamilyId"]),
        ("perceptual_cluster", identity["perceptualClusterId"]),
        ("perceptual_fingerprint", identity["perceptualFingerprint"]),
        ("media_sha256", media_sha),
    }
    account_ids = {
        str(_value(owner, "reddit_account_id", "redditAccountId"))
        for owner in owners
        if (
            str(_value(owner, "identity_type", "identityType")),
            str(_value(owner, "identity_value", "identityValue")),
        )
        in values
    }
    if not account_ids:
        return None, False
    if len(account_ids) != 1:
        return None, True
    account_id = next(iter(account_ids))
    account = next(
        (row for row in accounts if str(_value(row, "id") or "") == account_id),
        None,
    )
    return (
        str(_value(account, "username") or "") if account else None,
        account is None,
    )


def _ready_export_eligible(
    export: dict[str, Any],
    *,
    identity: dict[str, str],
    media_sha: str,
    creator_id: str,
    media_type: str,
    accounts: list[dict[str, Any]],
    subreddits: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    permanent_owner: str | None,
    ownership_conflict: bool,
    as_of: datetime,
) -> bool:
    account_name = str(_value(export, "account_username", "accountUsername") or "")
    subreddit_name = str(_value(export, "subreddit") or "")
    account = _current_account(accounts, account_name)
    subreddit = _current_rule(subreddits, subreddit_name)
    if (
        not account
        or not subreddit
        or ownership_conflict
        or (permanent_owner and permanent_owner.lower() != account_name.lower())
    ):
        return False
    if (
        _value(account, "is_active", "isActive") is not True
        or _value(account, "account_health", "accountHealth") != "active"
        or _value(subreddit, "status") != "active"
        or _value(subreddit, "rule_review_approved", "ruleReviewApproved") is not True
        or _value(subreddit, "account_restriction_state", "accountRestrictionState")
        != "active"
        or not _record(
            _value(subreddit, "verification_evidence", "verificationEvidence")
        )
    ):
        return False
    expected_creator = creator_id or str(
        _value(account, "creator_id", "creatorId") or ""
    )
    if account_name not in list(
        _value(subreddit, "eligible_accounts", "eligibleAccounts") or []
    ) or expected_creator not in list(
        _value(subreddit, "eligible_creators", "eligibleCreators") or []
    ):
        return False
    if media_type not in list(
        _value(subreddit, "allowed_media_types", "allowedMediaTypes") or []
    ):
        return False
    if (
        _value(subreddit, "nsfw_required", "nsfwRequired")
        and export.get("nsfw") is not True
    ) or (
        _value(subreddit, "spoiler_required", "spoilerRequired")
        and export.get("spoiler") is not True
    ):
        return False
    if (
        _value(subreddit, "flair_required", "flairRequired")
        and not str(export.get("flair") or "").strip()
    ):
        return False
    if (
        _value(subreddit, "first_comment_allowed", "firstCommentAllowed") is False
        and str(export.get("firstComment") or "").strip()
    ):
        return False
    if _value(export, "media_sha256", "mediaSha256") != media_sha:
        return False
    if _value(export, "rule_snapshot_hash", "ruleSnapshotHash") != _value(
        subreddit, "rule_snapshot_hash", "ruleSnapshotHash"
    ):
        return False
    scheduled = _when(_value(export, "scheduled_for", "scheduledFor"))
    window_start = _when(_value(export, "window_start", "windowStart"))
    window_end = _when(_value(export, "window_end", "windowEnd"))
    if (
        not scheduled
        or not window_start
        or not window_end
        or not window_start <= scheduled <= window_end
        or not as_of <= scheduled <= as_of + timedelta(days=7)
    ):
        return False
    spacing = int(export.get("spacingMinutes") or 1)
    frequency = int(
        _value(subreddit, "frequency_limit_minutes", "frequencyLimitMinutes") or 1
    )
    eastern = ZoneInfo("America/New_York")
    account_tasks_on_day = 0
    for task in tasks:
        if _value(task, "handoff_status", "handoffStatus") == "cancelled":
            continue
        task_scheduled = _when(_value(task, "scheduled_for", "scheduledFor"))
        task_account = str(_value(task, "account_username", "accountUsername") or "")
        if task_scheduled and task_account == account_name:
            if (
                task_scheduled.astimezone(eastern).date()
                == scheduled.astimezone(eastern).date()
            ):
                account_tasks_on_day += 1
            task_spacing = int(_value(task, "spacing_minutes", "spacingMinutes") or 1)
            if (
                abs((task_scheduled - scheduled).total_seconds())
                < max(spacing, task_spacing) * 60
            ):
                return False
            if (
                str(_value(task, "subreddit_name", "subreddit") or "").lower()
                == subreddit_name.lower()
                and abs((task_scheduled - scheduled).total_seconds()) < frequency * 60
            ):
                return False
        if not _matches(task, identity, media_sha):
            continue
        if (
            _value(task, "publication_status", "publicationStatus")
            == "operator_reported"
            and _value(task, "moderation_status", "moderationStatus") == "unknown"
        ):
            return False
        if str(_value(task, "subreddit_name", "subreddit") or "").lower() == (
            subreddit_name.lower()
        ):
            return False
    if account_tasks_on_day >= int(_value(account, "daily_target", "dailyTarget") or 8):
        return False
    return True


def build_reddit_library_report(
    factory: Any,
    *,
    campaign_slug: str,
    state: dict[str, Any],
    as_of: str | None = None,
) -> dict[str, Any]:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    creator_id = str(state.get("creatorId") or "")
    accounts = [dict(row) for row in state.get("accounts") or []]
    subreddits = [dict(row) for row in state.get("subreddits") or []]
    tasks = [dict(row) for row in state.get("tasks") or []]
    owners = [dict(row) for row in state.get("contentOwners") or []]
    now = _when(as_of or state.get("asOf")) or datetime.now(UTC)
    rows = factory.conn.execute(
        "SELECT * FROM rendered_assets WHERE campaign_id = ? ORDER BY created_at, id",
        (campaign["id"],),
    ).fetchall()
    cards: list[dict[str, Any]] = []
    for raw in rows:
        asset = dict(raw)
        metadata = _record(asset.get("metadata_json"))
        identity = asset_identity(asset)
        path = Path(str(asset.get("output_path") or asset.get("campaign_path") or ""))
        media_sha = (
            sha256_file(path)
            if path.is_file()
            else str(asset.get("content_hash") or "")
        )
        approval = factory.domains.publishability.creative_approval_for_asset(
            asset["id"]
        )
        exact_approved = approval.get("state") == "approved" and media_sha == str(
            asset.get("content_hash") or ""
        )
        permanent_owner, ownership_conflict = _permanent_owner(
            owners, accounts, identity, media_sha
        )
        matching_tasks = [task for task in tasks if _matches(task, identity, media_sha)]
        active = [
            task
            for task in matching_tasks
            if _value(task, "handoff_status", "handoffStatus") in ACTIVE_TASK_STATES
        ]
        hold = [
            task
            for task in matching_tasks
            if _value(task, "publication_status", "publicationStatus")
            == "operator_reported"
            and _value(task, "moderation_status", "moderationStatus") == "unknown"
        ]
        published = [
            task
            for task in matching_tasks
            if _value(task, "publication_status", "publicationStatus")
            in {"operator_reported", "reconciled"}
        ]
        ready_exports = [
            item
            for item in metadata.get("redditReadyExports") or []
            if isinstance(item, dict)
            and _ready_export_eligible(
                item,
                identity=identity,
                media_sha=media_sha,
                creator_id=creator_id,
                media_type=str(item.get("mediaType") or ""),
                accounts=accounts,
                subreddits=subreddits,
                tasks=tasks,
                permanent_owner=permanent_owner,
                ownership_conflict=ownership_conflict,
                as_of=now,
            )
        ]
        if asset.get("review_state") == "rejected" or metadata.get("quarantined"):
            view = "Rejected/Quarantined"
        elif metadata.get("redditArchived"):
            view = "Archived"
        elif not exact_approved:
            view = "Inbox"
        elif hold:
            view = "Reconciliation Hold"
        elif active:
            view = "Reserved"
        elif published and ready_exports:
            view = "Used"
        elif ready_exports:
            view = "Ready"
        else:
            view = "Exhausted"
        used_subreddits = sorted(
            {
                str(_value(task, "subreddit_name", "subreddit"))
                for task in published
                if _value(task, "subreddit_name", "subreddit")
            }
        )
        card = {
            "assetId": asset["id"],
            "sourceAssetId": asset.get("source_asset_id"),
            "mediaSha256": media_sha,
            **identity,
            "creatorId": creator_id,
            "accountUsername": permanent_owner
            or metadata.get("redditCommittedAccount")
            or _record(metadata.get("redditProposedAssignment")).get("newAccount"),
            "ownershipConflict": ownership_conflict,
            "view": view,
            "contentTags": list(metadata.get("contentTags") or []),
            "compositionTags": list(metadata.get("compositionTags") or []),
            "usedSubreddits": used_subreddits,
            "eligibleSubreddits": sorted(
                {str(item["subreddit"]) for item in ready_exports}
            ),
            "remainingEligibleSubredditCount": len(
                {str(item["subreddit"]) for item in ready_exports}
            ),
            "activeTaskIds": [
                str(_value(task, "id")) for task in active if _value(task, "id")
            ],
            "approvalState": approval.get("state"),
            "approvalFingerprint": approval.get("approvalFingerprint"),
            "createdAt": asset.get("created_at"),
            "lastUsedAt": max(
                (
                    str(_value(task, "completed_at", "completedAt") or "")
                    for task in published
                ),
                default="",
            )
            or None,
            "generationSource": metadata.get("generationSource"),
            "thumbnailPath": metadata.get("thumbnailPath")
            or asset.get("thumbnail_path"),
            "nextReservation": min(
                (
                    str(_value(task, "scheduled_for", "scheduledFor"))
                    for task in active
                    if _value(task, "scheduled_for", "scheduledFor")
                ),
                default=None,
            ),
            "outputPath": str(path) if path else None,
            "cleanupEligible": bool(
                view == "Rejected/Quarantined"
                and not active
                and not published
                and (
                    metadata.get("temporary")
                    or metadata.get("redundantPreview")
                    or metadata.get("cleanupEligible")
                )
            ),
            "readyExports": ready_exports,
        }
        cards.append(card)

    priority = {
        "Reconciliation Hold": 0,
        "Reserved": 1,
        "Used": 2,
        "Ready": 3,
        "Archived": 4,
        "Inbox": 5,
        "Exhausted": 6,
        "Rejected/Quarantined": 7,
    }
    exact_groups: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        exact_groups.setdefault(card["mediaSha256"], []).append(card)
    visible: list[dict[str, Any]] = []
    for group in exact_groups.values():
        group.sort(key=lambda item: (priority[item["view"]], item["assetId"]))
        canonical, *duplicates = group
        canonical["exactDuplicateAssetIds"] = [item["assetId"] for item in duplicates]
        visible.append(canonical)
    visible.sort(key=lambda item: (priority[item["view"]], item["assetId"]))

    near_duplicate_groups: dict[str, list[str]] = {}
    for card in cards:
        cluster = str(card["perceptualClusterId"] or "")
        if cluster:
            near_duplicate_groups.setdefault(cluster, []).append(card["assetId"])
    near_duplicate_groups = {
        key: sorted(values)
        for key, values in near_duplicate_groups.items()
        if len(values) > 1
    }

    coverage: dict[str, Any] = {}
    for account in accounts:
        username = str(_value(account, "username") or "")
        target = int(_value(account, "daily_target", "dailyTarget") or 8) * 7
        scheduled: set[str] = set()
        claimed: list[tuple[datetime, int, str]] = []
        for task in tasks:
            if (
                str(_value(task, "account_username", "accountUsername") or "")
                != username
                or _value(task, "handoff_status", "handoffStatus") == "cancelled"
            ):
                continue
            task_scheduled = _when(_value(task, "scheduled_for", "scheduledFor"))
            if task_scheduled is None:
                continue
            if _value(
                task, "handoff_status", "handoffStatus"
            ) != "completed" and now <= task_scheduled <= now + timedelta(days=7):
                scheduled.add(str(_value(task, "id")))
            claimed.append(
                (
                    task_scheduled,
                    int(_value(task, "spacing_minutes", "spacingMinutes") or 1),
                    str(_value(task, "subreddit_name", "subreddit") or ""),
                )
            )
        ready_candidates = sorted(
            (
                {
                    "assetId": card["assetId"],
                    **item,
                }
                for card in visible
                for item in card["readyExports"]
                if item.get("accountUsername") == username
            ),
            key=lambda item: (
                str(item.get("scheduledFor") or ""),
                str(item.get("assetId") or ""),
                str(item.get("subreddit") or ""),
            ),
        )
        ready_slots = 0
        for item in ready_candidates:
            scheduled_at = _when(item.get("scheduledFor"))
            if not scheduled_at:
                continue
            spacing = int(item.get("spacingMinutes") or 1)
            subreddit_name = str(item.get("subreddit") or "")
            rule = _current_rule(subreddits, subreddit_name) or {}
            frequency = int(
                _value(rule, "frequency_limit_minutes", "frequencyLimitMinutes") or 1
            )
            if any(
                (
                    abs((existing_time - scheduled_at).total_seconds())
                    < max(spacing, existing_spacing) * 60
                    or (
                        existing_subreddit.lower() == subreddit_name.lower()
                        and abs((existing_time - scheduled_at).total_seconds())
                        < frequency * 60
                    )
                )
                for existing_time, existing_spacing, existing_subreddit in claimed
            ):
                continue
            claimed.append((scheduled_at, spacing, subreddit_name))
            ready_slots += 1
        total = len(scheduled) + ready_slots
        coverage[username] = {
            "targetSlots": target,
            "scheduledSlots": len(scheduled),
            "readySlots": ready_slots,
            "totalSchedulableSlots": total,
            "healthy": total >= target,
            "uncoveredSlots": max(0, target - total),
        }

    cleanup_candidates = [
        {
            "assetId": card["assetId"],
            "path": card["outputPath"],
            "mediaSha256": card["mediaSha256"],
            "reason": "rejected_or_redundant_intermediate",
        }
        for card in cards
        if card["cleanupEligible"]
    ]
    core = {
        "schema": "campaign_factory.reddit_library_report.v1",
        "campaignId": str(campaign["id"]),
        "campaignSlug": campaign_slug,
        "asOf": now.isoformat().replace("+00:00", "Z"),
        "views": {
            name: [card for card in visible if card["view"] == name]
            for name in priority
        },
        "coverage": coverage,
        "nearDuplicateGroups": near_duplicate_groups,
        "cleanupManifest": {
            "schema": "campaign_factory.reddit_cleanup_manifest.v1",
            "requiresOperatorApproval": True,
            "automaticDeletion": False,
            "candidates": cleanup_candidates,
        },
    }
    return {**core, "reportFingerprint": payload_fingerprint(core)}


def archive_reddit_assets(
    factory: Any,
    *,
    campaign_slug: str,
    state: dict[str, Any],
    asset_ids: list[str],
    operator: str,
    reason: str,
    as_of: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    requested = sorted(
        {str(value).strip() for value in asset_ids if str(value).strip()}
    )
    if not requested:
        raise ValueError("reddit_archive_asset_ids_required")
    actor = str(operator or "").strip()
    why = str(reason or "").strip()
    if not actor or not why:
        raise ValueError("reddit_archive_operator_and_reason_required")
    report = build_reddit_library_report(
        factory,
        campaign_slug=campaign_slug,
        state=state,
        as_of=as_of,
    )
    cards = {
        card["assetId"]: (view, card)
        for view, values in report["views"].items()
        for card in values
    }
    allowed = {"Used", "Exhausted", "Rejected/Quarantined"}
    blocked = {
        asset_id: cards.get(asset_id, ("missing", {}))[0]
        for asset_id in requested
        if cards.get(asset_id, ("missing", {}))[0] not in allowed
    }
    if blocked:
        raise ValueError(
            "reddit_archive_assets_not_eligible:"
            + ",".join(f"{asset_id}={view}" for asset_id, view in blocked.items())
        )
    receipt_core = {
        "schema": "campaign_factory.reddit_archive_receipt.v1",
        "campaignSlug": campaign_slug,
        "assetIds": requested,
        "operator": actor,
        "reason": why,
        "archivedAt": as_of or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    receipt = {
        **receipt_core,
        "receiptFingerprint": payload_fingerprint(receipt_core),
        "applied": bool(apply),
    }
    if not apply:
        return receipt
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    with factory.conn:
        for asset_id in requested:
            row = factory.conn.execute(
                "SELECT metadata_json FROM rendered_assets "
                "WHERE id = ? AND campaign_id = ?",
                (asset_id, campaign["id"]),
            ).fetchone()
            if not row:
                raise ValueError(f"reddit_archive_asset_missing:{asset_id}")
            metadata = _record(row["metadata_json"])
            metadata["redditArchived"] = receipt
            factory.conn.execute(
                "UPDATE rendered_assets SET metadata_json = ?, updated_at = ? "
                "WHERE id = ? AND campaign_id = ?",
                (
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    receipt_core["archivedAt"],
                    asset_id,
                    campaign["id"],
                ),
            )
            factory.domains.events.record_event(
                "reddit_asset_archived",
                campaign_id=str(campaign["id"]),
                rendered_asset_id=asset_id,
                status="success",
                message="Reddit working-shelf asset archived",
                metadata=receipt,
                commit=False,
            )
    return receipt
