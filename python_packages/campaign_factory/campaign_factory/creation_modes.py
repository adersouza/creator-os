from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from .account_eligibility import evaluate_account_eligibility
from .assignment_eligibility import evaluate_assignment_eligibility
from .derived_stills import validate_static_source_assets
from .production_batch_results import (
    finalize_production_batch as _finalize_production_batch,
)
from .production_lane import (
    _SUPPORTED_PASSIVE_INTENTS,
    _audio_policy,
    _sha256_file,
    fulfill_production_audio,
    plan_production_batch,
    run_production_batch,
)
from .static_mp4_stage import run_static_mp4_stage

CREATE_MODES: Final = ("static_reel", "calm_animation", "recreate_reel")
CALM_STYLES: Final = tuple(sorted(_SUPPORTED_PASSIVE_INTENTS))
REUSE_POLICIES: Final = ("prefer_exact", "require_fresh")


def run_creation_batch(
    factory: Any,
    *,
    creator: str,
    mode: str,
    style: str,
    count: int,
    execution: str,
    accounts: str | None,
    audio_preference: str,
    apply: bool,
    max_total_credits: float = 100.0,
    max_concurrency: int = 2,
    reference_video_path: Path | None = None,
    reference_platform: str | None = None,
    reference_authorized: bool = False,
    reference_talking: bool = False,
    prompt_pack_provider: Callable[..., dict[str, Any]] | None = None,
    reuse_policy: str = "prefer_exact",
    recreation_anchor_approval_path: Path | None = None,
    recreation_attempt_id: str | None = None,
    source_asset_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run one of the three product modes, reusing qualified media first."""

    if mode not in CREATE_MODES:
        raise ValueError(f"unsupported Creator OS mode: {mode}")
    if style not in CALM_STYLES:
        raise ValueError(f"unsupported calm animation style: {style}")
    if reuse_policy not in REUSE_POLICIES:
        raise ValueError(f"unsupported reuse policy: {reuse_policy}")
    if recreation_anchor_approval_path is not None and mode != "recreate_reel":
        raise ValueError("--recreation-anchor-approval is only valid for recreate_reel")
    if recreation_attempt_id is not None and mode != "recreate_reel":
        raise ValueError("--recreation-attempt-id is only valid for recreate_reel")
    if source_asset_ids and mode != "static_reel":
        raise ValueError("--source-asset-id is only valid for static_reel")
    if source_asset_ids:
        validate_static_source_assets(factory, source_asset_ids)
    intent = "recreate_reel" if mode == "recreate_reel" else style
    reference_sha = (
        _sha256_file(reference_video_path.expanduser().resolve())
        if reference_video_path is not None
        else None
    )
    destination = _resolve_destination_account(factory, accounts)
    if destination["status"] != "not_requested":
        if destination["status"] != "resolved":
            raise PermissionError(f"destination_account_{destination['status']}")
        identity = factory.domains.creator_governance.active_identity_profile(
            creator, provider="internal"
        )
        if not destination.get("modelId"):
            raise PermissionError("destination_account_creator_missing")
        if str(destination["modelId"]) != str(identity["creator_id"]):
            raise PermissionError("cross_creator_account_blocked")
    reusable = (
        _qualified_reusable_assets(
            factory,
            creator=creator,
            mode=mode,
            intent=intent,
            audio_policy=_audio_policy(audio_preference),
            reference_sha256=reference_sha,
            account_id=destination.get("accountId"),
        )
        if reuse_policy == "prefer_exact" and not source_asset_ids
        else []
    )
    reservation = _select_destination_reuse(
        factory,
        candidates=reusable,
        count=count,
        destination=destination,
        creator=creator,
        mode=mode,
        intent=intent,
        apply=apply,
    )
    selected = reservation["assets"]
    if len(selected) == count:
        return _reuse_batch(
            creator=creator,
            mode=mode,
            intent=intent,
            assets=selected,
            apply=apply,
            reuse_policy=reuse_policy,
            reservation=reservation,
        )
    fresh_count = count - len(selected) if destination.get("accountId") else count
    try:
        if mode == "static_reel":
            result = _run_static_reel_batch(
                factory,
                creator=creator,
                intent=intent,
                count=fresh_count,
                execution=execution,
                accounts=accounts,
                audio_preference=audio_preference,
                apply=apply,
                source_asset_ids=source_asset_ids,
            )
        else:
            result = run_production_batch(
                factory,
                creator=creator,
                intent=intent,
                count=fresh_count,
                execution=execution,
                accounts=accounts,
                audio_preference=audio_preference,
                apply=apply,
                max_total_credits=max_total_credits,
                max_concurrency=max_concurrency,
                reference_video_path=reference_video_path,
                reference_platform=reference_platform,
                reference_authorized=reference_authorized,
                reference_talking=reference_talking,
                prompt_pack_provider=prompt_pack_provider,
                recreation_anchor_approval_path=recreation_anchor_approval_path,
                recreation_attempt_id=recreation_attempt_id,
            )
    except Exception:
        _release_new_reservations(factory, reservation)
        raise
    result["reusePolicy"] = reuse_policy
    if selected and destination.get("accountId"):
        return _hybrid_batch(
            fresh=result,
            creator=creator,
            mode=mode,
            intent=intent,
            requested=count,
            reused=selected,
            apply=apply,
            reuse_policy=reuse_policy,
            reservation=reservation,
        )
    result["reuseCandidatesFound"] = len(reusable)
    result["reuseShortfall"] = count
    result["fallbackDecision"] = (
        "require_fresh"
        if reuse_policy == "require_fresh"
        else "fresh_full_batch_destination_unresolved"
        if accounts and not destination.get("accountId")
        else "fresh_full_batch_no_qualified_reuse"
    )
    result["destination"] = destination
    result["reservationStatus"] = "not_created"
    result["destinationReady"] = False
    result["reuseBlockers"] = reservation["blockers"]
    return result


def _qualified_reusable_assets(
    factory: Any,
    *,
    creator: str,
    mode: str,
    intent: str,
    audio_policy: str,
    reference_sha256: str | None,
    account_id: str | None,
) -> list[dict[str, Any]]:
    identity = factory.domains.creator_governance.active_identity_profile(
        creator, provider="internal"
    )
    creator_slug = str(identity["creator_slug"])
    rows = factory.conn.execute(
        """
        SELECT ra.*, c.slug AS campaign_slug
        FROM rendered_assets ra
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        JOIN models m ON m.id = sa.model_id
        JOIN campaigns c ON c.id = ra.campaign_id
        WHERE lower(m.slug) = ? AND ra.media_type = 'video'
          AND ra.content_surface = 'reel'
          AND ra.review_state = 'approved'
          AND ra.audit_status IN ('approved_candidate', 'needs_review')
          AND EXISTS (
            SELECT 1
            FROM approval_decisions ad
            WHERE ad.rendered_asset_id = ra.id AND ad.decision = 'approved'
          )
        ORDER BY ra.updated_at DESC, ra.created_at DESC, ra.id
        """,
        (creator_slug,),
    ).fetchall()
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        asset = dict(row)
        try:
            metadata = json.loads(str(asset.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(metadata, dict):
            continue
        if metadata.get("contentIntent") != intent:
            continue
        try:
            factory.domains.creator_governance.resolve_operation(
                creator=creator_slug,
                campaign=str(asset["campaign_id"]),
                operation="reuse",
                provider="internal",
                source_asset_id=str(asset["source_asset_id"]),
                account_id=account_id,
            )
        except PermissionError:
            continue
        if mode == "static_reel" and asset.get("recipe") != "static_mp4":
            continue
        if mode == "recreate_reel":
            reference = metadata.get("referenceVideo")
            if (
                not isinstance(reference, dict)
                or _mapping_sha(reference) != reference_sha256
            ):
                continue
        raw_path = Path(str(asset.get("output_path") or "")).expanduser()
        if raw_path.is_symlink():
            continue
        path = raw_path.resolve()
        digest = str(asset.get("content_hash") or "")
        if not digest or digest in seen or not path.is_file():
            continue
        if _sha256_file(path) != digest:
            continue
        if not _exact_final_binding(
            metadata,
            path=path,
            digest=digest,
            audio_policy=audio_policy,
        ):
            continue
        approval = _creative_approval_for_asset(factory, str(asset["id"]))
        if approval.get("state") != "approved":
            continue
        asset["output_path"] = str(path)
        selected.append(asset)
        seen.add(digest)
    return selected


def _creative_approval_for_asset(factory: Any, asset_id: str) -> dict[str, Any]:
    """Read the exact-SHA Creative Approval v2 decision for reuse."""

    return factory.domains.publishability.creative_approval_for_asset(asset_id)


def _mapping_sha(reference: Mapping[str, Any]) -> str | None:
    source = reference.get("originalLocalFile") or reference.get("source")
    return str(source.get("sha256") or "") if isinstance(source, Mapping) else None


def _reuse_batch(
    *,
    creator: str,
    mode: str,
    intent: str,
    assets: list[dict[str, Any]],
    apply: bool,
    reuse_policy: str,
    reservation: dict[str, Any],
) -> dict[str, Any]:
    reservations = {
        str(item["assetId"]): item for item in reservation.get("reservations") or []
    }
    results = [
        {
            "jobId": f"reuse_{asset['id']}",
            "index": index,
            "status": "reused",
            "renderedAssetId": asset["id"],
            "campaign": asset["campaign_slug"],
            "outputPath": asset["output_path"],
            "outputSha256": asset["content_hash"],
            "providerCalls": 0,
            "route": "exact_final_reuse",
            "reason": "approved_exact_creator_intent_audio_match",
            "reservationId": (reservations.get(str(asset["id"])) or {}).get(
                "reservationId"
            ),
        }
        for index, asset in enumerate(assets)
    ]
    return {
        "schema": "campaign_factory.production_batch.v1",
        "creator": creator.strip().lower().replace(" ", "_"),
        "mode": mode,
        "intent": intent,
        "execution": "library_reuse",
        "reusePolicy": reuse_policy,
        "route": "exact_final_reuse",
        "requested": len(assets),
        "provider": None,
        "providerQuoteStatus": "not_required",
        "quotedProviderCredits": 0,
        "paidGenerationAuthorized": False,
        "apply": apply,
        "destination": reservation["destination"],
        "destinationReady": reservation["destinationReady"],
        "destinationEligibilityStatus": reservation["eligibilityStatus"],
        "reservationStatus": reservation["status"],
        "reservations": reservation["reservations"],
        "reuseBlockers": reservation["blockers"],
        "fallbackDecision": "not_required",
        "results": results,
        "summary": {
            "requested": len(assets),
            "created": 0,
            "reused": len(assets),
            "submitted": 0,
            "completed": len(assets),
            "blocked": 0,
            "failed": 0,
            "scheduled": 0,
            "published": 0,
            "totalProviderCredits": 0,
        },
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }


def _resolve_destination_account(factory: Any, requested: str | None) -> dict[str, Any]:
    raw = str(requested or "").strip()
    if not raw:
        return {
            "requested": None,
            "accountId": None,
            "handle": None,
            "status": "not_requested",
        }
    if "," in raw:
        return {
            "requested": raw,
            "accountId": None,
            "handle": None,
            "status": "multiple_destinations_unsupported",
        }
    handle = raw.lstrip("@")
    rows = factory.conn.execute(
        """
        SELECT *
        FROM accounts
        WHERE id = ? OR external_id = ? OR lower(handle) = lower(?)
        ORDER BY id
        """,
        (raw, raw, handle),
    ).fetchall()
    unique = {str(row["id"]): dict(row) for row in rows}
    if len(unique) != 1:
        return {
            "requested": raw,
            "accountId": None,
            "handle": None,
            "status": "unresolved" if not unique else "ambiguous",
        }
    account = next(iter(unique.values()))
    return {
        "requested": raw,
        "accountId": str(account["id"]),
        "handle": account.get("handle"),
        "externalId": account.get("external_id"),
        "accountGroupId": account.get("account_group_id") or account.get("model_id"),
        "modelId": account.get("model_id"),
        "status": "resolved",
    }


def _select_destination_reuse(
    factory: Any,
    *,
    candidates: list[dict[str, Any]],
    count: int,
    destination: dict[str, Any],
    creator: str,
    mode: str,
    intent: str,
    apply: bool,
) -> dict[str, Any]:
    account_id = destination.get("accountId")
    if not account_id:
        assets = candidates[:count]
        return {
            "assets": assets,
            "destination": destination,
            "destinationReady": False,
            "eligibilityStatus": "not_evaluated",
            "status": "not_requested",
            "reservations": [],
            "blockers": (
                []
                if destination["status"] == "not_requested"
                else [{"reason": f"destination_{destination['status']}"}]
            ),
        }

    account = evaluate_account_eligibility(
        factory.conn,
        account_id=str(account_id),
        surface="reel",
    )
    if not account["allowed"]:
        return {
            "assets": [],
            "destination": destination,
            "destinationReady": False,
            "eligibilityStatus": "blocked",
            "status": "not_created",
            "reservations": [],
            "blockers": [
                {
                    "reason": str(account["decisionReason"]),
                    "operatorAction": account.get("operatorAction"),
                }
            ],
        }

    if apply:
        factory.domains.inventory_reservations.expire_inventory_reservations()
    selected: list[dict[str, Any]] = []
    reservations: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for asset in candidates:
        active = factory.conn.execute(
            """
            SELECT *
            FROM asset_inventory_reservations
            WHERE asset_id = ? AND status IN ('pending', 'committed')
            ORDER BY reserved_at DESC
            LIMIT 1
            """,
            (asset["id"],),
        ).fetchone()
        if active is not None:
            row = dict(active)
            stored_eligibility = _json_object(row.get("assignment_eligibility_json"))
            if (
                row.get("account_id") == account_id
                and stored_eligibility.get("variantCooldownCheck") == "clear"
            ):
                selected.append(asset)
                reservations.append(_reservation_summary(row, created=False))
            else:
                blockers.append(
                    {
                        "assetId": asset["id"],
                        "reason": (
                            "active_reservation_for_other_destination"
                            if row.get("account_id") != account_id
                            else "variant_cooldown_unproven"
                        ),
                    }
                )
            if len(selected) == count:
                break
            continue

        eligibility = evaluate_assignment_eligibility(
            factory.conn,
            rendered_asset_id=str(asset["id"]),
            account_id=str(account_id),
            surface="reel",
        )
        if not eligibility["allowed"]:
            blockers.append(
                {
                    "assetId": asset["id"],
                    "reason": "assignment_ineligible",
                    "reasonCodes": eligibility["reasonCodes"],
                    "variantCooldownCheck": eligibility["variantCooldownCheck"],
                }
            )
            continue
        if not apply:
            selected.append(asset)
            reservations.append(
                {
                    "assetId": asset["id"],
                    "accountId": account_id,
                    "reservationId": None,
                    "status": "eligible_unreserved",
                    "variantCooldownCheck": eligibility["variantCooldownCheck"],
                }
            )
        else:
            try:
                row = factory.domains.inventory_reservations.reserve_inventory_asset(
                    str(asset["id"]),
                    account_id=str(account_id),
                    surface="reel",
                    metadata={
                        "creator": creator,
                        "mode": mode,
                        "intent": intent,
                        "accountGroupId": destination.get("accountGroupId"),
                        "selection": "exact_final_reuse",
                    },
                )
            except (ValueError, sqlite3.IntegrityError) as exc:
                blockers.append(
                    {
                        "assetId": asset["id"],
                        "reason": "reservation_failed",
                        "detail": str(exc),
                    }
                )
                continue
            selected.append(asset)
            reservations.append(_reservation_summary(row, created=True))
        if len(selected) == count:
            break
    return {
        "assets": selected,
        "destination": destination,
        "destinationReady": bool(apply and len(selected) == count),
        "eligibilityStatus": "passed" if len(selected) == count else "shortfall",
        "status": (
            "pending"
            if apply and selected
            else "preview"
            if selected
            else "not_created"
        ),
        "reservations": reservations,
        "blockers": blockers,
    }


def _reservation_summary(row: Mapping[str, Any], *, created: bool) -> dict[str, Any]:
    eligibility = _json_object(row.get("assignment_eligibility_json"))
    return {
        "assetId": row.get("asset_id"),
        "accountId": row.get("account_id"),
        "reservationId": row.get("reservation_id"),
        "status": row.get("status"),
        "reservedAt": row.get("reserved_at"),
        "expiresAt": row.get("expires_at"),
        "variantCooldownCheck": eligibility.get("variantCooldownCheck") or "unproven",
        "createdByThisRequest": created,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _release_new_reservations(factory: Any, reservation: dict[str, Any]) -> None:
    for item in reservation.get("reservations") or []:
        if item.get("createdByThisRequest") and item.get("reservationId"):
            factory.domains.inventory_reservations.release_inventory_reservation(
                str(item["reservationId"])
            )


def _hybrid_batch(
    *,
    fresh: dict[str, Any],
    creator: str,
    mode: str,
    intent: str,
    requested: int,
    reused: list[dict[str, Any]],
    apply: bool,
    reuse_policy: str,
    reservation: dict[str, Any],
) -> dict[str, Any]:
    reuse = _reuse_batch(
        creator=creator,
        mode=mode,
        intent=intent,
        assets=reused,
        apply=apply,
        reuse_policy=reuse_policy,
        reservation=reservation,
    )
    offset = len(reused)
    fresh_results = [dict(item) for item in fresh.get("results") or []]
    for item in fresh_results:
        item["index"] = int(item.get("index") or 0) + offset
    summary = dict(fresh.get("summary") or {})
    summary.update(
        {
            "requested": requested,
            "reused": offset,
            "completed": int(summary.get("completed") or 0) + offset,
            "approved": int(summary.get("approved") or 0) + offset,
        }
    )
    return {
        **fresh,
        "creator": creator.strip().lower().replace(" ", "_"),
        "mode": mode,
        "intent": intent,
        "execution": "hybrid_reuse_and_fresh_generation",
        "reusePolicy": reuse_policy,
        "route": "partial_exact_reuse_fresh_fill",
        "requested": requested,
        "results": [*reuse["results"], *fresh_results],
        "summary": summary,
        "destination": reservation["destination"],
        "destinationReady": False,
        "reusedDestinationReady": reservation["destinationReady"],
        "destinationEligibilityStatus": "partial",
        "reservationStatus": ("partial_pending" if apply else "partial_preview"),
        "reservations": reservation["reservations"],
        "reuseCandidatesFound": len(reused) + len(reservation["blockers"]),
        "reuseShortfall": requested - len(reused),
        "reuseBlockers": reservation["blockers"],
        "fallbackDecision": "generate_fresh_shortfall",
    }


def _exact_final_binding(
    metadata: Mapping[str, Any],
    *,
    path: Path,
    digest: str,
    audio_policy: str,
) -> bool:
    output = metadata.get("output")
    if not isinstance(output, Mapping) or str(output.get("sha256") or "") != digest:
        return False
    output_path = Path(str(output.get("path") or "")).expanduser()
    if output_path.is_symlink() or output_path.resolve() != path:
        return False
    if audio_policy == "silent_allowed":
        return metadata.get("audioBurned") is not True
    receipt = metadata.get("audioEmbeddingReceipt")
    if not isinstance(receipt, Mapping) or metadata.get("audioBurned") is not True:
        return False
    final_video = receipt.get("finalVideo")
    verification = receipt.get("verification")
    return bool(
        isinstance(final_video, Mapping)
        and str(final_video.get("sha256") or "") == digest
        and isinstance(verification, Mapping)
        and verification.get("status") == "verified"
        and verification.get("audioPresent") is True
        and verification.get("audioCodec") == "aac"
    )


def _run_static_reel_batch(
    factory: Any,
    *,
    creator: str,
    intent: str,
    count: int,
    execution: str,
    accounts: str | None,
    audio_preference: str,
    apply: bool,
    source_asset_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    plan = plan_production_batch(
        factory,
        creator=creator,
        intent=intent,
        count=count,
        execution=execution,
        accounts=accounts,
        audio_preference=audio_preference,
        selected_source_asset_ids=source_asset_ids,
    )
    plan.update(
        {
            "mode": "static_reel",
            "provider": None,
            "providerQuoteStatus": "not_required",
            "quotedProviderCredits": 0,
        }
    )
    results: list[dict[str, Any]] = []
    for job in plan["jobs"]:
        if not apply:
            results.append(
                {"jobId": job["jobId"], "index": job["index"], "status": "created"}
            )
            continue
        try:
            stage = run_static_mp4_stage(
                factory,
                campaign_slug=str(job["campaign"]),
                still_path=Path(str(job["sourcePath"])),
                content_intent=intent,
                dry_run=False,
                apply=True,
            )
            stage["audioFulfillment"] = fulfill_production_audio(
                factory,
                job=job,
                generation_result=stage,
            )
            results.append(
                {
                    "jobId": job["jobId"],
                    "index": job["index"],
                    "status": "completed",
                    "providerCalls": 0,
                    "result": stage,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "jobId": job["jobId"],
                    "index": job["index"],
                    "status": "failed",
                    "error": str(exc),
                    "providerCalls": 0,
                }
            )
    finalized = _finalize_production_batch(plan, results, apply=apply)
    finalized["mode"] = "static_reel"
    finalized["summary"]["reused"] = sum(
        bool((item.get("result") or {}).get("reused")) for item in results
    )
    finalized["summary"]["totalProviderCredits"] = 0
    return finalized
