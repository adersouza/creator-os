"""Approved Creator OS assets -> manual Reddit handoff contracts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from creator_os_core.evidence_attestation import payload_fingerprint
from creator_os_core.fileops import atomic_write_json, sha256_file

from pipeline_contracts import validate_reddit_manual_handoff

from .adapters.threadsdash_owner_api import submit_reddit_handoff
from .assignment_eligibility import asset_identity

SCHEMA = "reddit.manual_handoff.v1"
APPROVAL_SCHEMA = "campaign_factory.reddit_task_approval.v1"
BRIEF_SCHEMA = "campaign_factory.reddit_trend_brief.v1"
PROPOSED_ASSIGNMENT_SCHEMA = "campaign_factory.reddit_proposed_assignment.v1"
RESERVATION_RECEIPT_SCHEMA = "threadsdashboard.reddit_reservation_receipt.v1"

ORGANIC_AMATEUR_STYLE = (
    "casual handheld selfie, slightly imperfect framing and natural crop, "
    "ordinary lived-in setting, believable practical lighting, clean identity, "
    "face, hands, anatomy, and background"
)
REDDIT_ACCOUNT_ROTATION = (
    ("Larissa", "u/Serious_material571"),
    ("Stacey", "u/staceylazy"),
    ("Larissa", "u/Adventurous-bill-745"),
)


def _fingerprint(value: dict[str, Any]) -> str:
    return payload_fingerprint(value)


def _required_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name}_must_be_an_object")
    return dict(value)


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name}_required")
    return text


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _metadata(asset: dict[str, Any]) -> dict[str, Any]:
    raw = asset.get("metadata_json")
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        value = {}
    return dict(value) if isinstance(value, dict) else {}


def _enforce_family_account_ownership(
    factory: Any,
    *,
    campaign_id: str,
    asset_id: str,
    identity: dict[str, str],
    account_username: str,
) -> None:
    identity_values = {
        value
        for key, value in identity.items()
        if key != "contentFingerprint" and value
    }
    for row in factory.conn.execute(
        "SELECT * FROM rendered_assets WHERE campaign_id = ? AND id <> ?",
        (campaign_id, asset_id),
    ).fetchall():
        related = asset_identity(dict(row))
        if not identity_values.intersection(
            value
            for key, value in related.items()
            if key != "contentFingerprint" and value
        ):
            continue
        metadata = _metadata(dict(row))
        proposed = metadata.get("redditProposedAssignment")
        owner = metadata.get("redditCommittedAccount") or (
            proposed.get("newAccount") if isinstance(proposed, dict) else None
        )
        if owner and _normalize_account(owner) != account_username:
            raise ValueError("reddit_family_account_ownership_conflict")


def set_reddit_proposed_assignment(
    factory: Any,
    *,
    campaign_slug: str,
    rendered_asset_id: str,
    account_username: str,
    operator: str,
    reason: str,
    assigned_at: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    asset = factory.domains.publishability.rendered_asset(rendered_asset_id)
    if not asset or str(asset.get("campaign_id") or "") != str(campaign["id"]):
        raise ValueError("reddit_asset_campaign_mismatch")
    path = _asset_path(asset)
    media_sha = sha256_file(path)
    if media_sha != _required_text(asset.get("content_hash"), "asset_content_hash"):
        raise ValueError("reddit_asset_sha_mismatch")
    identity = asset_identity(asset)
    if not identity.get("sourceFamilyId") or not identity.get("perceptualClusterId"):
        raise ValueError("reddit_asset_lineage_missing")
    normalized = _normalize_account(account_username)
    _enforce_family_account_ownership(
        factory,
        campaign_id=str(campaign["id"]),
        asset_id=rendered_asset_id,
        identity=identity,
        account_username=normalized,
    )
    metadata = _metadata(asset)
    if metadata.get("redditReservationReceipt") or metadata.get(
        "redditCommittedAccount"
    ):
        raise ValueError("reddit_account_ownership_already_committed")

    previous = metadata.get("redditProposedAssignment")
    previous = previous if isinstance(previous, dict) else {}
    if previous.get("newAccount") == normalized:
        return previous
    core = {
        "schema": PROPOSED_ASSIGNMENT_SCHEMA,
        "renderedAssetId": rendered_asset_id,
        "sourceFamilyId": identity["sourceFamilyId"],
        "perceptualClusterId": identity["perceptualClusterId"],
        "mediaSha256": media_sha,
        "oldAccount": previous.get("newAccount"),
        "newAccount": normalized,
        "reason": _required_text(reason, "assignment_reason"),
        "operator": _required_text(operator, "assignment_operator"),
        "assignedAt": assigned_at or _utc_now(),
    }
    receipt = {**core, "receiptFingerprint": _fingerprint(core)}
    if not apply:
        return receipt

    metadata["redditProposedAssignment"] = receipt
    with factory.conn:
        factory.conn.execute(
            """
            UPDATE rendered_assets
            SET metadata_json = ?, updated_at = ?
            WHERE id = ? AND campaign_id = ?
            """,
            (
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                receipt["assignedAt"],
                rendered_asset_id,
                campaign["id"],
            ),
        )
        factory.domains.events.record_event(
            "reddit_proposed_assignment_changed",
            campaign_id=str(campaign["id"]),
            rendered_asset_id=rendered_asset_id,
            status="success",
            message="Reddit proposed account assignment recorded",
            metadata=receipt,
            commit=False,
        )
    return receipt


def record_reddit_reservation_receipt(
    factory: Any,
    *,
    campaign_slug: str,
    payload: dict[str, Any],
    delivery: dict[str, Any],
) -> dict[str, Any]:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    receipt = _required_object(
        delivery.get("reservationReceipt"), "reservation_receipt"
    )
    if receipt.get("schema") != RESERVATION_RECEIPT_SCHEMA:
        raise ValueError("reddit_reservation_receipt_schema_invalid")
    fingerprint = _required_text(
        receipt.get("receiptFingerprint"), "reservation_receipt_fingerprint"
    )
    core = dict(receipt)
    core.pop("receiptFingerprint", None)
    if _fingerprint(core) != fingerprint:
        raise ValueError("reddit_reservation_receipt_fingerprint_mismatch")
    expected = {
        "idempotencyKey": payload["idempotencyKey"],
        "assetId": payload["asset"]["id"],
        "mediaSha256": payload["asset"]["mediaSha256"],
        "sourceFamilyId": payload["asset"]["sourceFamilyId"],
        "perceptualClusterId": payload["asset"]["perceptualClusterId"],
        "accountUsername": payload["account"]["username"],
        "subreddit": payload["destination"]["subreddit"],
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("reddit_reservation_receipt_binding_mismatch")

    asset = factory.domains.publishability.rendered_asset(payload["asset"]["id"])
    if not asset or str(asset.get("campaign_id") or "") != str(campaign["id"]):
        raise ValueError("reddit_asset_campaign_mismatch")
    metadata = _metadata(asset)
    existing = metadata.get("redditReservationReceipt")
    if isinstance(existing, dict):
        if existing.get("receiptFingerprint") != fingerprint:
            raise ValueError("reddit_reservation_receipt_conflict")
        return existing
    proposed = metadata.get("redditProposedAssignment")
    if isinstance(proposed, dict) and proposed.get("newAccount") != receipt.get(
        "accountUsername"
    ):
        raise ValueError("reddit_reservation_account_differs_from_proposal")

    metadata["redditReservationReceipt"] = receipt
    metadata["redditCommittedAccount"] = receipt["accountUsername"]
    with factory.conn:
        factory.conn.execute(
            """
            UPDATE rendered_assets
            SET metadata_json = ?, updated_at = ?
            WHERE id = ? AND campaign_id = ?
            """,
            (
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                receipt["committedAt"],
                payload["asset"]["id"],
                campaign["id"],
            ),
        )
        factory.domains.events.record_event(
            "reddit_reservation_committed",
            campaign_id=str(campaign["id"]),
            rendered_asset_id=payload["asset"]["id"],
            status="success",
            message="ThreadsDashboard Reddit reservation receipt recorded",
            metadata=receipt,
            commit=False,
        )
    return receipt


def build_reddit_daily_schedule(
    posting_date: str,
    *,
    include_optional: bool = False,
    timezone: str = "America/New_York",
) -> dict[str, Any]:
    day = date.fromisoformat(posting_date)
    zone = ZoneInfo(timezone)
    rounds = (9, 12, 15, 18)
    slots: list[dict[str, Any]] = []
    account_positions = {username: 0 for _, username in REDDIT_ACCOUNT_ROTATION}
    for round_index, base_hour in enumerate(rounds):
        for account_index, (creator, username) in enumerate(REDDIT_ACCOUNT_ROTATION):
            hour = base_hour + account_index
            window_start = datetime.combine(day, time(hour), tzinfo=zone)
            for minute in (0, 15):
                account_positions[username] += 1
                scheduled = window_start + timedelta(minutes=minute)
                slots.append(
                    {
                        "creator": creator,
                        "accountUsername": username,
                        "queuePosition": account_positions[username],
                        "dailyTarget": 10 if include_optional else 8,
                        "scheduledFor": scheduled.isoformat(),
                        "windowStart": window_start.isoformat(),
                        "windowEnd": (window_start + timedelta(minutes=30)).isoformat(),
                        "spacingMinutes": 15,
                        "round": round_index + 1,
                    }
                )
    if include_optional:
        for account_index, (creator, username) in enumerate(REDDIT_ACCOUNT_ROTATION):
            window_start = datetime.combine(day, time(21 + account_index), tzinfo=zone)
            for minute in (0, 15):
                account_positions[username] += 1
                scheduled = window_start + timedelta(minutes=minute)
                slots.append(
                    {
                        "creator": creator,
                        "accountUsername": username,
                        "queuePosition": account_positions[username],
                        "dailyTarget": 10,
                        "scheduledFor": scheduled.isoformat(),
                        "windowStart": window_start.isoformat(),
                        "windowEnd": (window_start + timedelta(minutes=30)).isoformat(),
                        "spacingMinutes": 15,
                        "round": 5,
                    }
                )
    return {
        "schema": "campaign_factory.reddit_daily_schedule.v1",
        "postingDate": posting_date,
        "timezone": timezone,
        "optionalSlotsIncluded": include_optional,
        "slots": sorted(slots, key=lambda slot: slot["scheduledFor"]),
    }


def _normalize_account(value: Any) -> str:
    username = _required_text(value, "reddit_account")
    return username if username.startswith("u/") else f"u/{username.lstrip('@')}"


def _normalize_subreddit(value: Any) -> str:
    subreddit = _required_text(value, "subreddit")
    return subreddit if subreddit.startswith("r/") else f"r/{subreddit}"


def _asset_path(asset: dict[str, Any]) -> Path:
    value = asset.get("output_path") or asset.get("campaign_path")
    if not value:
        raise ValueError("reddit_asset_path_missing")
    path = Path(str(value)).expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise ValueError("reddit_asset_file_missing_or_unsafe")
    return path


def _approval_binding(
    *,
    user_id: str,
    source_approval_fingerprint: str,
    account_username: str,
    subreddit: str,
    title: str,
    first_comment: str | None,
    media_sha256: str,
    rule_snapshot_hash: str,
    nsfw: bool,
    spoiler: bool,
    flair: str | None,
    reuse_exception: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "userId": user_id,
        "sourceCreativeApprovalFingerprint": source_approval_fingerprint,
        "accountUsername": account_username,
        "subreddit": subreddit,
        "title": title,
        "firstComment": first_comment,
        "mediaSha256": media_sha256,
        "ruleSnapshotHash": rule_snapshot_hash,
        "nsfw": nsfw,
        "spoiler": spoiler,
        "flair": flair,
        "reuseException": reuse_exception,
    }


def build_reddit_handoff_review(
    factory: Any,
    *,
    campaign_slug: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    asset_id = _required_text(spec.get("renderedAssetId"), "rendered_asset_id")
    asset = factory.domains.publishability.rendered_asset(asset_id)
    if str(asset.get("campaign_id") or "") != str(campaign["id"]):
        raise ValueError("reddit_asset_campaign_mismatch")

    creative_approval = factory.domains.publishability.creative_approval_for_asset(
        asset_id
    )
    if creative_approval.get("state") != "approved":
        raise ValueError(
            str(
                creative_approval.get("blockingReason")
                or "reddit_creative_approval_required"
            )
        )
    source_approval = _required_object(
        creative_approval.get("approval"), "creative_approval"
    )
    source_approval_fingerprint = _required_text(
        creative_approval.get("approvalFingerprint"),
        "creative_approval_fingerprint",
    )

    path = _asset_path(asset)
    actual_sha = sha256_file(path)
    if actual_sha != _required_text(asset.get("content_hash"), "asset_content_hash"):
        raise ValueError("reddit_asset_sha_mismatch")

    identity = asset_identity(asset)
    missing = [
        key
        for key in (
            "sourceFamilyId",
            "perceptualFingerprint",
            "perceptualClusterId",
        )
        if not identity.get(key)
    ]
    if missing:
        raise ValueError("reddit_asset_lineage_missing:" + ",".join(missing))

    creator = _required_object(spec.get("creator"), "creator")
    account = _required_object(spec.get("account"), "account")
    destination = _required_object(spec.get("destination"), "destination")
    content = _required_object(spec.get("content"), "content")
    rules = _required_object(spec.get("rules"), "rules")
    scheduling = _required_object(spec.get("scheduling"), "scheduling")
    snapshot = _required_object(rules.get("snapshot"), "rule_snapshot")
    snapshot_hash = _fingerprint(snapshot)
    claimed_snapshot_hash = str(rules.get("snapshotHash") or snapshot_hash).lower()
    if claimed_snapshot_hash != snapshot_hash:
        raise ValueError("reddit_rule_snapshot_hash_mismatch")
    if rules.get("reviewApproved") is not True:
        raise ValueError("reddit_rule_review_approval_required")
    if rules.get("accountRestrictionState") != "active":
        raise ValueError("reddit_account_not_active")
    if not isinstance(rules.get("verificationEvidence"), dict):
        raise ValueError("reddit_verification_evidence_required")

    account_username = _normalize_account(account.get("username"))
    _enforce_family_account_ownership(
        factory,
        campaign_id=str(campaign["id"]),
        asset_id=asset_id,
        identity=identity,
        account_username=account_username,
    )
    metadata = _metadata(asset)
    proposed = metadata.get("redditProposedAssignment")
    committed = metadata.get("redditCommittedAccount")
    if committed and committed != account_username:
        raise ValueError("reddit_account_ownership_already_committed")
    if isinstance(proposed, dict) and proposed.get("newAccount") != account_username:
        raise ValueError("reddit_account_differs_from_proposed_assignment")
    subreddit = _normalize_subreddit(destination.get("subreddit"))
    title = _required_text(content.get("title"), "reddit_title")
    first_comment = content.get("firstComment")
    if first_comment is not None:
        first_comment = str(first_comment).strip() or None
    flair = content.get("flair")
    if flair is not None:
        flair = str(flair).strip() or None
    reuse_exception = (
        _required_object(spec.get("reuseException"), "reuse_exception")
        if spec.get("reuseException") is not None
        else None
    )
    if reuse_exception is not None:
        exception_core = {
            "approvedBy": _required_text(
                reuse_exception.get("approvedBy"), "reuse_exception_approved_by"
            ),
            "approvedAt": _required_text(
                reuse_exception.get("approvedAt"), "reuse_exception_approved_at"
            ),
            "reason": _required_text(
                reuse_exception.get("reason"), "reuse_exception_reason"
            ),
            "priorTaskId": _required_text(
                reuse_exception.get("priorTaskId"), "reuse_exception_prior_task_id"
            ),
            "derivedMediaSha256": _required_text(
                reuse_exception.get("derivedMediaSha256"),
                "reuse_exception_derived_media_sha256",
            ).lower(),
            "derivedPerceptualFingerprint": _required_text(
                reuse_exception.get("derivedPerceptualFingerprint"),
                "reuse_exception_derived_perceptual_fingerprint",
            ),
            "transformReceiptFingerprint": _required_text(
                reuse_exception.get("transformReceiptFingerprint"),
                "reuse_exception_transform_receipt_fingerprint",
            ).lower(),
        }
        if exception_core["derivedMediaSha256"] != actual_sha:
            raise ValueError("reddit_reuse_exception_media_sha_mismatch")
        if (
            exception_core["derivedPerceptualFingerprint"]
            != identity["perceptualFingerprint"]
        ):
            raise ValueError("reddit_reuse_exception_perceptual_fingerprint_mismatch")
        if reuse_exception.get("approvalFingerprint") != _fingerprint(exception_core):
            raise ValueError("reddit_reuse_exception_approval_mismatch")
        reuse_exception = {
            **exception_core,
            "approvalFingerprint": reuse_exception["approvalFingerprint"],
        }
    user_id = _required_text(spec.get("userId"), "user_id")
    binding = _approval_binding(
        user_id=user_id,
        source_approval_fingerprint=source_approval_fingerprint,
        account_username=account_username,
        subreddit=subreddit,
        title=title,
        first_comment=first_comment,
        media_sha256=actual_sha,
        rule_snapshot_hash=snapshot_hash,
        nsfw=bool(content.get("nsfw")),
        spoiler=bool(content.get("spoiler")),
        flair=flair,
        reuse_exception=reuse_exception,
    )
    approval_fingerprint = _fingerprint(binding)
    return {
        "schema": "campaign_factory.reddit_handoff_review.v1",
        "userId": user_id,
        "campaign": {"id": str(campaign["id"]), "slug": str(campaign["slug"])},
        "renderedAssetId": asset_id,
        "mediaPath": str(path),
        "mediaSha256": actual_sha,
        "creator": {
            "id": _required_text(creator.get("id"), "creator_id"),
            "name": _required_text(creator.get("name"), "creator_name"),
        },
        "account": {
            "id": str(account.get("id")).strip() if account.get("id") else None,
            "username": account_username,
        },
        "destination": {
            "subreddit": subreddit,
            "canonicalUrl": str(
                destination.get("canonicalUrl")
                or f"https://www.reddit.com/{subreddit}/"
            ),
        },
        "assetIdentity": identity,
        "content": {
            "title": title,
            "firstComment": first_comment,
            "nsfw": bool(content.get("nsfw")),
            "spoiler": bool(content.get("spoiler")),
            "flair": flair,
        },
        "rules": {
            "snapshot": snapshot,
            "snapshotHash": snapshot_hash,
            "reviewedAt": _required_text(rules.get("reviewedAt"), "rules_reviewed_at"),
            "reviewedBy": _required_text(rules.get("reviewedBy"), "rules_reviewed_by"),
            "reviewApproved": True,
            "verificationEvidence": rules["verificationEvidence"],
            "accountRestrictionState": "active",
        },
        "scheduling": scheduling,
        "trendBrief": spec.get("trendBrief"),
        "mediaUrl": _required_text(spec.get("mediaUrl"), "media_url"),
        "mediaType": _required_text(spec.get("mediaType"), "media_type"),
        "sourceCreativeApproval": source_approval,
        "sourceCreativeApprovalId": creative_approval.get("approvalId"),
        "sourceCreativeApprovalFingerprint": source_approval_fingerprint,
        "approvalBinding": binding,
        "approvalFingerprint": approval_fingerprint,
    }


def build_reddit_manual_handoff(
    factory: Any,
    *,
    campaign_slug: str,
    spec: dict[str, Any],
    exported_at: str | None = None,
) -> dict[str, Any]:
    review = build_reddit_handoff_review(
        factory, campaign_slug=campaign_slug, spec=spec
    )
    approval = _required_object(spec.get("redditApproval"), "reddit_approval")
    if approval.get("decision") != "approved":
        raise ValueError("reddit_task_approval_required")
    if approval.get("bindingFingerprint") != review["approvalFingerprint"]:
        raise ValueError("reddit_task_approval_binding_mismatch")

    receipt = {
        "schema": APPROVAL_SCHEMA,
        "decision": "approved",
        "approvedBy": _required_text(approval.get("approvedBy"), "approved_by"),
        "approvedAt": _required_text(approval.get("approvedAt"), "approved_at"),
        "binding": review["approvalBinding"],
        "bindingFingerprint": review["approvalFingerprint"],
        "sourceCreativeApprovalId": review["sourceCreativeApprovalId"],
        "sourceCreativeApprovalFingerprint": review[
            "sourceCreativeApprovalFingerprint"
        ],
    }
    scheduled = review["scheduling"]
    idempotency_key = _fingerprint(
        {
            "schema": SCHEMA,
            "approvalFingerprint": review["approvalFingerprint"],
            "scheduledFor": scheduled.get("scheduledFor"),
            "queuePosition": scheduled.get("queuePosition"),
        }
    )
    core = {
        "schema": SCHEMA,
        "userId": review["userId"],
        "creator": review["creator"],
        "account": review["account"],
        "destination": review["destination"],
        "asset": {
            "id": review["renderedAssetId"],
            "sourceFamilyId": review["assetIdentity"]["sourceFamilyId"],
            "perceptualFingerprint": review["assetIdentity"]["perceptualFingerprint"],
            "perceptualClusterId": review["assetIdentity"]["perceptualClusterId"],
            "mediaUrl": review["mediaUrl"],
            "mediaSha256": review["mediaSha256"],
            "mediaType": review["mediaType"],
        },
        "content": review["content"],
        "rules": review["rules"],
        "scheduling": scheduled,
        "approval": {
            "fingerprint": review["approvalFingerprint"],
            "receipt": receipt,
        },
        "trendBrief": review["trendBrief"],
        "reuseException": review["approvalBinding"]["reuseException"],
        "idempotencyKey": idempotency_key,
        "exportedAt": exported_at or _utc_now(),
    }
    payload = {**core, "exportFingerprint": _fingerprint(core)}
    validate_reddit_manual_handoff(payload)
    return payload


def write_reddit_manual_handoff(
    factory: Any,
    *,
    campaign_slug: str,
    payload: dict[str, Any],
) -> Path:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    output_dir = (
        factory.domains.campaign_dirs(model_slug, campaign_slug)["exports"] / "reddit"
    )
    output = output_dir / f"{payload['idempotencyKey']}.json"
    atomic_write_json(output, payload)
    asset = factory.domains.publishability.rendered_asset(payload["asset"]["id"])
    if not asset:
        raise ValueError("reddit_asset_missing_after_export")
    metadata = _metadata(asset)
    ready_exports = [
        item
        for item in metadata.get("redditReadyExports") or []
        if isinstance(item, dict)
        and item.get("exportFingerprint") != payload["exportFingerprint"]
    ]
    ready_exports.append(
        {
            "assetId": payload["asset"]["id"],
            "accountUsername": payload["account"]["username"],
            "subreddit": payload["destination"]["subreddit"],
            "mediaSha256": payload["asset"]["mediaSha256"],
            "mediaType": payload["asset"]["mediaType"],
            "title": payload["content"]["title"],
            "firstComment": payload["content"]["firstComment"],
            "nsfw": payload["content"]["nsfw"],
            "spoiler": payload["content"]["spoiler"],
            "flair": payload["content"]["flair"],
            "ruleSnapshotHash": payload["rules"]["snapshotHash"],
            "approvalFingerprint": payload["approval"]["fingerprint"],
            "exportFingerprint": payload["exportFingerprint"],
            "idempotencyKey": payload["idempotencyKey"],
            "scheduledFor": payload["scheduling"]["scheduledFor"],
            "windowStart": payload["scheduling"]["windowStart"],
            "windowEnd": payload["scheduling"]["windowEnd"],
            "spacingMinutes": payload["scheduling"]["spacingMinutes"],
            "artifactPath": str(output),
            "exportedAt": payload["exportedAt"],
        }
    )
    metadata["redditReadyExports"] = ready_exports
    with factory.conn:
        factory.conn.execute(
            """
            UPDATE rendered_assets
            SET metadata_json = ?, updated_at = ?
            WHERE id = ? AND campaign_id = ?
            """,
            (
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                payload["exportedAt"],
                payload["asset"]["id"],
                campaign["id"],
            ),
        )
        factory.domains.events.record_event(
            "reddit_handoff_export_ready",
            campaign_id=str(campaign["id"]),
            rendered_asset_id=payload["asset"]["id"],
            status="success",
            message="Exact Reddit handoff export recorded on working shelf",
            metadata={
                "exportFingerprint": payload["exportFingerprint"],
                "idempotencyKey": payload["idempotencyKey"],
                "mediaSha256": payload["asset"]["mediaSha256"],
                "accountUsername": payload["account"]["username"],
                "subreddit": payload["destination"]["subreddit"],
                "artifactPath": str(output),
            },
            commit=False,
        )
    return output


def build_reddit_trend_brief(
    spec: dict[str, Any], *, created_at: str | None = None
) -> dict[str, Any]:
    subreddit = _normalize_subreddit(spec.get("subreddit"))
    rules = _required_object(spec.get("rules"), "rules")
    patterns = spec.get("patterns")
    concepts = spec.get("concepts")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError("reddit_brief_patterns_required")
    if not isinstance(concepts, list) or len(concepts) != 3:
        raise ValueError("reddit_brief_requires_three_concepts")
    core = {
        "schema": BRIEF_SCHEMA,
        "subreddit": subreddit,
        "snapshotDate": _required_text(spec.get("snapshotDate"), "snapshot_date"),
        "ruleSourceUrl": _required_text(spec.get("ruleSourceUrl"), "rule_source_url"),
        "rules": rules,
        "rulesFingerprint": _fingerprint(rules),
        "eligibleCreators": list(spec.get("eligibleCreators") or []),
        "eligibleAccounts": list(spec.get("eligibleAccounts") or []),
        "requiredContentTags": list(spec.get("requiredContentTags") or []),
        "disallowedElements": list(spec.get("disallowedElements") or []),
        "patterns": patterns,
        "titlePattern": spec.get("titlePattern"),
        "promotionPolicy": spec.get("promotionPolicy"),
        "firstCommentPolicy": spec.get("firstCommentPolicy"),
        "concepts": concepts,
        "referencePostIds": list(spec.get("referencePostIds") or []),
        "researchEvidence": dict(spec.get("researchEvidence") or {}),
        "ruleChange": dict(spec.get("ruleChange") or {}),
        "generationStyle": ORGANIC_AMATEUR_STYLE,
        "createdAt": created_at or _utc_now(),
    }
    return {**core, "briefFingerprint": _fingerprint(core)}


def write_reddit_trend_brief(
    factory: Any,
    *,
    campaign_slug: str,
    brief: dict[str, Any],
) -> Path:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    output_dir = (
        factory.domains.campaign_dirs(model_slug, campaign_slug)["sources"]
        / "reddit_trend_briefs"
    )
    subreddit = str(brief["subreddit"]).removeprefix("r/")
    output = output_dir / f"{subreddit}-{brief['briefFingerprint'][:16]}.json"
    atomic_write_json(output, brief)
    return output


def deliver_reddit_manual_handoff(
    payload: dict[str, Any],
    *,
    ingest_url: str | None,
    ingest_secret: str | None,
) -> dict[str, Any]:
    return submit_reddit_handoff(
        payload,
        ingest_url=ingest_url,
        ingest_secret=ingest_secret,
    )
