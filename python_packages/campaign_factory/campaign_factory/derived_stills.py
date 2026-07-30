"""Campaign-owned authorization and registration for reusable derived stills."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text
from creator_os_core.runtime_guards import global_kill_switch_active
from reel_factory.worker_api import (
    DERIVED_STILL_SCHEMA,
    PILOT_COLORWAYS,
    PROMPT_BUILDER_VERSION,
    assess_edit_locality,
    assess_image_qc,
    build_edit_prompt,
    evaluate_harvest_frame,
    harvest_animation_frames,
    materialize_individual_outputs,
    provider_adapter,
    split_grid_2x3,
    verify_identity,
)

from .core import new_id, sanitize_for_storage, sha256_file
from .cost_tracker import record_ai_cost
from .persistence import utc_now
from .provider_spend import AUTHORIZATION_TABLE, ensure_authorization_table

TIER_POLICIES = {
    "canonical_identity_source": {
        "canonicalIdentityEligible": True,
        "generationEligible": True,
        "allowedOperations": [
            "static_reel",
            "soul_grounding",
            "colorway",
            "outfit_swap",
        ],
    },
    "approved_generated_still": {
        "canonicalIdentityEligible": False,
        "generationEligible": True,
        "allowedOperations": ["static_reel", "colorway", "outfit_swap"],
    },
    "approved_animation_frame": {
        "canonicalIdentityEligible": False,
        "generationEligible": True,
        "allowedOperations": ["static_reel", "colorway", "outfit_swap_review_only"],
    },
    "approved_outfit_derivative": {
        "canonicalIdentityEligible": False,
        "generationEligible": False,
        "allowedOperations": ["static_reel"],
    },
}


def enroll_still(
    factory: Any,
    *,
    campaign_slug: str,
    source_asset_id: str,
    tier: str,
    apply: bool = False,
) -> dict[str, Any]:
    if tier not in {"canonical_identity_source", "approved_generated_still"}:
        raise ValueError(
            "enroll tier must be canonical_identity_source or approved_generated_still"
        )
    source = _source_row(factory, campaign_slug, source_asset_id)
    path = _verified_image(source)
    approval = _source_approval_evidence(factory, source, tier=tier)
    receipt = _receipt(
        source=source,
        source_tier=tier,
        derivation_depth=0 if tier == "canonical_identity_source" else 1,
        parent_asset_id=None,
        root_source_asset_id=str(source["id"]),
        operation="enroll",
        source_path=path,
        output_path=path,
        provider=None,
        model=None,
        evidence={"sourceApproval": approval},
    )
    receipt["approval"] = {
        "decision": "approved",
        "approvalDecisionId": approval.get("sourceApprovalEventId"),
        "exactOutputSha256": source["content_hash"],
        "decidedAt": approval.get("sourceApprovalEventCreatedAt") or utc_now(),
    }
    if apply:
        prompt = _json_object(source.get("source_prompt"))
        prompt["derivedStillSource"] = receipt
        factory.conn.execute(
            "UPDATE source_assets SET source_prompt = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(sanitize_for_storage(prompt), sort_keys=True),
                utc_now(),
                source["id"],
            ),
        )
        factory.domains.events.record_event(
            "derived_still_enrolled",
            campaign_id=source["campaign_id"],
            source_asset_id=source["id"],
            status="success",
            message=f"Enrolled {source['filename']} as {tier}",
            metadata=receipt,
            commit=False,
        )
        factory.conn.commit()
    return {
        "schema": "campaign_factory.derived_still_enrollment.v1",
        "apply": apply,
        "sourceAssetId": source["id"],
        "receipt": receipt,
    }


def harvest_stills(
    factory: Any,
    *,
    campaign_slug: str,
    rendered_asset_id: str,
    count: int = 6,
    apply: bool = False,
    harvest_call: Callable[..., dict[str, Any]] = harvest_animation_frames,
    frame_evaluator: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parent = _approved_rendered_asset(factory, campaign_slug, rendered_asset_id)
    raw = _resolve_raw_visual(factory, parent)
    model_id = str(raw["modelId"])
    if not any(name in model_id.lower() for name in ("kling", "seedance")):
        raise ValueError("frame harvesting requires an approved Kling or Seedance Reel")
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    creator = str(raw["creator"])
    dirs = factory.domains.campaign_dirs(creator, campaign["slug"])
    persistent_root = (
        dirs["rendered"]
        / "derived_stills"
        / f"{rendered_asset_id}_{str(raw['sha256'])[:12]}"
    )
    temporary: tempfile.TemporaryDirectory[str] | None = None
    output_root = persistent_root
    if not apply:
        temporary = tempfile.TemporaryDirectory(prefix="creator-os-still-harvest-")
        output_root = Path(temporary.name)
    output_root.mkdir(parents=True, exist_ok=True)

    def evaluate(path: Path) -> dict[str, Any]:
        evidence = (
            frame_evaluator(path)
            if frame_evaluator is not None
            else _default_frame_evaluator(
                path,
                creator=creator,
                identity_root=factory.settings.reel_factory_root,
            )
        )
        return evidence

    try:
        result = harvest_call(
            Path(str(raw["path"])),
            output_root,
            count=count,
            expected_sha256=str(raw["sha256"]),
            evaluator=evaluate,
        )
        registered: list[dict[str, Any]] = []
        receipt_path: Path | None = None
        if apply:
            receipt_path = (
                dirs["audits"]
                / "derived_stills"
                / f"{rendered_asset_id}_{str(raw['sha256'])[:12]}_harvest.json"
            )
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            extraction_receipt = {
                **result,
                "parentFinalReel": {
                    "assetId": parent["id"],
                    "path": parent["output_path"],
                    "sha256": parent["content_hash"],
                },
                "parentRawVisual": {
                    "path": raw["path"],
                    "sha256": raw["sha256"],
                    "providerOutputId": raw.get("providerOutputId"),
                    "modelId": model_id,
                },
            }
            atomic_write_text(
                receipt_path,
                json.dumps(
                    sanitize_for_storage(extraction_receipt), indent=2, sort_keys=True
                )
                + "\n",
                encoding="utf-8",
            )
            receipt_sha = sha256_file(receipt_path)
            for selected in result["selectedFrames"]:
                selected_path = Path(str(selected["path"])).resolve()
                receipt = _receipt(
                    source=raw["sourceAsset"],
                    source_tier="approved_animation_frame",
                    derivation_depth=1,
                    parent_asset_id=parent["id"],
                    root_source_asset_id=str(raw["sourceAsset"]["id"]),
                    operation="frame_extract",
                    source_path=Path(str(raw["path"])),
                    output_path=selected_path,
                    provider="higgsfield",
                    model=model_id,
                    evidence={
                        "parentFinalReelSha": parent["content_hash"],
                        "parentRawVisualSha": raw["sha256"],
                        "providerOutputId": raw.get("providerOutputId"),
                        "frameTimestampSeconds": selected["timeSec"],
                        "frameScoring": selected,
                        "extractionReceipt": {
                            "path": str(receipt_path),
                            "sha256": receipt_sha,
                        },
                    },
                )
                registered.append(
                    _register_candidate(
                        factory,
                        campaign=campaign,
                        creator=creator,
                        output_path=selected_path,
                        receipt=receipt,
                        parent_asset_id=parent["id"],
                        audit_status="needs_review",
                    )
                )
            factory.domains.events.record_event(
                "derived_still_harvest_completed",
                campaign_id=campaign["id"],
                rendered_asset_id=parent["id"],
                status="success" if registered else "warning",
                message=f"Harvested {len(registered)} frame review candidates",
                metadata={
                    "parentRenderedAssetId": parent["id"],
                    "parentRawVisualSha256": raw["sha256"],
                    "harvest": result,
                    "registeredAssetIds": [item["id"] for item in registered],
                },
            )
        return {
            "schema": "campaign_factory.derived_still_harvest.v1",
            "apply": apply,
            "parentRenderedAssetId": parent["id"],
            "parentRawVisual": {
                key: raw.get(key)
                for key in ("path", "sha256", "providerOutputId", "modelId")
            },
            "harvest": result,
            "extractionReceiptPath": str(receipt_path) if receipt_path else None,
            "registeredAssets": registered,
            "operatorReviewRequired": bool(registered),
        }
    finally:
        if temporary is not None:
            temporary.cleanup()


def edit_still(
    factory: Any,
    *,
    campaign_slug: str,
    image_asset_id: str,
    operation: str,
    provider: str,
    output_format: str,
    count: int,
    max_usd: float,
    apply: bool = False,
    adapter: Any | None = None,
    image_qc_call: Callable[[Path], dict[str, Any]] | None = None,
    identity_call: Callable[[Path], dict[str, Any]] | None = None,
    locality_call: Callable[..., dict[str, Any]] = assess_edit_locality,
) -> dict[str, Any]:
    if operation not in {"colorway", "outfit_swap"}:
        raise ValueError("operation must be colorway or outfit_swap")
    if output_format not in {"individual", "grid_2x3"}:
        raise ValueError("format must be individual or grid_2x3")
    if not 1 <= count <= 6:
        raise ValueError("count must be between 1 and 6")
    if output_format == "grid_2x3" and count != 6:
        raise ValueError("grid_2x3 requires count=6")
    if isinstance(max_usd, bool) or not math.isfinite(max_usd) or max_usd <= 0:
        raise ValueError("max-usd must be finite and positive")
    source = _approved_tiered_image(factory, campaign_slug, image_asset_id)
    source_receipt = source["derivedReceipt"]
    allowed = set(source_receipt["allowedOperations"])
    required_operation = (
        "outfit_swap_review_only"
        if operation == "outfit_swap"
        and source_receipt["sourceTier"] == "approved_animation_frame"
        else operation
    )
    if required_operation not in allowed:
        raise PermissionError(
            f"{source_receipt['sourceTier']} does not allow {operation}"
        )
    source_path = Path(str(source["path"]))
    prompt = build_edit_prompt(
        operation=operation,
        output_format=output_format,
        count=count,
        colors=PILOT_COLORWAYS,
    )
    transport = adapter or provider_adapter(provider)
    if transport.provider != provider:
        raise ValueError("provider adapter identity mismatch")
    request_core = {
        "sourceSha256": source["sha256"],
        "sourceTier": source_receipt["sourceTier"],
        "provider": provider,
        "model": transport.model,
        "operation": operation,
        "format": output_format,
        "count": count,
        "colors": list(PILOT_COLORWAYS[:count]),
        "promptBuilderVersion": PROMPT_BUILDER_VERSION,
        "prompt": prompt,
    }
    request_fingerprint = _fingerprint(request_core)
    cached = _cached_edit(factory, request_fingerprint)
    if cached is not None:
        return {**cached, "cache": {"hit": True, "providerCalls": 0}}
    preflight = transport.preflight()
    quote = transport.quote(count=count, output_format=output_format)
    quote_amount = _positive_usd_quote(quote)
    if quote_amount > max_usd:
        raise PermissionError("provider quote exceeds --max-usd")
    plan = {
        "schema": "campaign_factory.derived_still_edit.v1",
        "apply": apply,
        "requestFingerprint": request_fingerprint,
        "request": request_core,
        "preflight": preflight,
        "quote": quote,
        "providerCalls": 0,
        "cache": {"hit": False},
    }
    if not apply:
        return plan
    if global_kill_switch_active():
        raise PermissionError("creator_os_global_kill_switch_active")
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    creator = str(source["creator"])
    dirs = factory.domains.campaign_dirs(creator, campaign["slug"])
    output_root = (
        dirs["rendered"] / "derived_stills" / request_fingerprint[:20]
    ).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    authorization = _authorize_spend(
        factory,
        campaign_id=campaign["id"],
        request_fingerprint=request_fingerprint,
        provider=provider,
        quote=quote,
        scope=request_core,
    )
    try:
        provider_result = transport.generate(
            source=source_path,
            prompt=prompt,
            count=count,
            output_format=output_format,
        )
        images = list(provider_result.get("images") or [])
        if output_format == "grid_2x3":
            if len(images) != 1:
                raise ValueError(
                    "grid_2x3 provider response must contain one composite"
                )
            composite_path = output_root / "provider_grid_2x3.png"
            composite_path.write_bytes(images[0])
            panels = split_grid_2x3(images[0], output_root / "panels")
            composite_evidence = {
                "path": str(composite_path),
                "sha256": sha256_file(composite_path),
            }
        else:
            panels = materialize_individual_outputs(
                images, output_root / "panels", count=count
            )
            composite_evidence = None
        source_identity = (
            identity_call(source_path)
            if identity_call
            else verify_identity(
                source_path,
                creator=creator,
                root=factory.settings.reel_factory_root,
            )
        )
        registered: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for index, panel in enumerate(panels, start=1):
            identity = (
                identity_call(panel)
                if identity_call
                else verify_identity(
                    panel,
                    creator=creator,
                    root=factory.settings.reel_factory_root,
                )
            )
            qc = (
                image_qc_call(panel)
                if image_qc_call
                else assess_image_qc(panel, root=factory.settings.reel_factory_root)
            )
            locality = locality_call(
                source_path,
                panel,
                operation=operation,
                source_identity=source_identity,
                output_identity=identity,
                output_qc=qc,
            )
            panel_evidence = {
                "index": index,
                "path": str(panel),
                "sha256": sha256_file(panel),
                "identityVerification": identity,
                "imageQc": qc,
                "editLocality": locality,
            }
            if locality.get("status") != "passed":
                rejected.append({**panel_evidence, "reason": "edit_locality_failed"})
                continue
            receipt = _receipt(
                source=source["sourceAsset"],
                source_tier="approved_outfit_derivative",
                derivation_depth=int(source_receipt["derivationDepth"]) + 1,
                parent_asset_id=source.get("renderedAssetId"),
                root_source_asset_id=str(source_receipt["rootSourceAssetId"]),
                operation=operation,
                source_path=source_path,
                output_path=panel,
                provider=provider,
                model=str(transport.model),
                evidence={
                    "requestFingerprint": request_fingerprint,
                    "requestId": provider_result.get("requestId"),
                    "promptBuilderVersion": PROMPT_BUILDER_VERSION,
                    "batchingFormat": output_format,
                    "providerSettings": request_core,
                    "usage": provider_result.get("usage"),
                    "quote": quote,
                    "authorizationId": authorization["authorizationId"],
                    "rawComposite": composite_evidence,
                    **panel_evidence,
                },
            )
            registered.append(
                _register_candidate(
                    factory,
                    campaign=campaign,
                    creator=creator,
                    output_path=panel,
                    receipt=receipt,
                    parent_asset_id=source.get("renderedAssetId"),
                    audit_status="needs_review",
                )
            )
        _consume_spend(
            factory,
            authorization=authorization,
            provider_result=provider_result,
            quote=quote,
            campaign_id=campaign["id"],
        )
        completed = {
            **plan,
            "apply": True,
            "providerCalls": 1,
            "authorization": authorization,
            "providerResult": {
                "provider": provider_result.get("provider"),
                "model": provider_result.get("model"),
                "requestId": provider_result.get("requestId"),
                "usage": provider_result.get("usage"),
            },
            "rawComposite": composite_evidence,
            "registeredAssets": registered,
            "rejectedPanels": rejected,
            "approvalYield": len(registered) / count,
            "operatorComparisonReviewRequired": bool(registered),
        }
        factory.domains.events.record_event(
            "derived_still_edit_completed",
            campaign_id=campaign["id"],
            source_asset_id=source["sourceAsset"]["id"],
            status="success" if registered else "warning",
            message=(
                f"Derived still edit produced {len(registered)} review candidates"
            ),
            metadata=completed,
        )
        return completed
    except Exception:
        _cancel_spend(factory, authorization["authorizationId"])
        raise


def sync_derived_source_review(
    conn,
    *,
    rendered_asset_id: str,
    decision: str,
    approval_decision_id: str,
    decided_at: str,
) -> None:
    row = conn.execute(
        """
        SELECT ra.content_hash, ra.source_asset_id, ra.metadata_json, sa.source_prompt
        FROM rendered_assets ra
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        WHERE ra.id = ?
        """,
        (rendered_asset_id,),
    ).fetchone()
    if row is None:
        return
    metadata = _json_object(row["metadata_json"])
    receipt = metadata.get("derivedStillSource")
    if not isinstance(receipt, dict) or receipt.get("schema") != DERIVED_STILL_SCHEMA:
        return
    prompt = _json_object(row["source_prompt"])
    updated = {
        **receipt,
        "approval": {
            "decision": decision,
            "approvalDecisionId": approval_decision_id,
            "exactOutputSha256": row["content_hash"],
            "decidedAt": decided_at,
        },
    }
    prompt["derivedStillSource"] = updated
    conn.execute(
        """
        UPDATE source_assets
        SET status = ?, source_prompt = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            decision,
            json.dumps(sanitize_for_storage(prompt), sort_keys=True),
            decided_at,
            row["source_asset_id"],
        ),
    )
    metadata["derivedStillSource"] = updated
    conn.execute(
        "UPDATE rendered_assets SET metadata_json = ? WHERE id = ?",
        (
            json.dumps(sanitize_for_storage(metadata), sort_keys=True),
            rendered_asset_id,
        ),
    )


def validate_static_source_assets(
    factory: Any, source_asset_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    validated = []
    for source_asset_id in source_asset_ids:
        row = factory.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?", (source_asset_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"derived still source not found: {source_asset_id}")
        source = dict(row)
        path = _verified_image(source)
        receipt = _derived_receipt_from_source(source)
        approval = receipt.get("approval")
        if (
            source["status"] != "approved"
            or "static_reel" not in receipt["allowedOperations"]
            or not isinstance(approval, dict)
            or approval.get("decision") != "approved"
            or approval.get("exactOutputSha256") != source["content_hash"]
        ):
            raise PermissionError(
                f"source is not an exact approved tiered still: {source_asset_id}"
            )
        validated.append(
            {
                "sourceAssetId": source_asset_id,
                "path": str(path),
                "sha256": source["content_hash"],
                "derivedStillSource": receipt,
            }
        )
    return validated


def derived_still_report(factory: Any, *, campaign_slug: str) -> dict[str, Any]:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    rows = factory.conn.execute(
        """
        SELECT ra.*, sa.source_prompt
        FROM rendered_assets ra
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        WHERE ra.campaign_id = ?
        ORDER BY ra.created_at, ra.id
        """,
        (campaign["id"],),
    ).fetchall()
    groups: dict[str, dict[str, Any]] = {}
    request_costs: dict[str, dict[str, float]] = {}
    total = approved = static_reels = 0
    for raw in rows:
        row = dict(raw)
        metadata = _json_object(row.get("metadata_json"))
        receipt = metadata.get("derivedStillSource")
        if not isinstance(receipt, dict):
            receipt = _json_object(row.get("source_prompt")).get("derivedStillSource")
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema") != DERIVED_STILL_SCHEMA
        ):
            continue
        is_candidate = row["media_type"] == "image"
        total += int(is_candidate)
        approved += int(is_candidate and row["review_state"] == "approved")
        static_reels += int(row.get("recipe") == "static_mp4")
        key_values = (
            receipt.get("sourceTier"),
            receipt.get("provider") or "local",
            (receipt.get("evidence") or {}).get("batchingFormat") or "none",
            receipt.get("operation"),
        )
        key = "|".join(str(value) for value in key_values)
        group = groups.setdefault(
            key,
            {
                "sourceTier": key_values[0],
                "provider": key_values[1],
                "format": key_values[2],
                "operation": key_values[3],
                "candidates": 0,
                "approved": 0,
                "staticReels": 0,
                "reach72h": 0,
                "watchTimeSeconds72h": 0.0,
                "saves72h": 0,
            },
        )
        group["candidates"] += int(is_candidate)
        group["approved"] += int(is_candidate and row["review_state"] == "approved")
        group["staticReels"] += int(row.get("recipe") == "static_mp4")
        evidence = receipt.get("evidence") or {}
        request_fingerprint = evidence.get("requestFingerprint")
        quote = evidence.get("quote")
        if (
            isinstance(request_fingerprint, str)
            and isinstance(quote, dict)
            and quote.get("unit") == "USD"
            and isinstance(quote.get("amount"), (int, float))
        ):
            request_costs.setdefault(key, {})[request_fingerprint] = float(
                quote["amount"]
            )
        snapshot = factory.conn.execute(
            """
            SELECT reach, watch_time_seconds, saves
            FROM performance_snapshots
            WHERE rendered_asset_id = ?
              AND julianday(snapshot_at) - julianday(published_at) >= 3
            ORDER BY snapshot_at DESC LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        if snapshot:
            group["reach72h"] += int(snapshot["reach"] or 0)
            group["watchTimeSeconds72h"] += float(snapshot["watch_time_seconds"] or 0)
            group["saves72h"] += int(snapshot["saves"] or 0)
    rejection_reasons: dict[str, int] = {}
    events = factory.conn.execute(
        """
        SELECT event_type, metadata_json FROM activity_events
        WHERE campaign_id = ? AND event_type IN (
          'derived_still_edit_completed', 'derived_still_harvest_completed'
        )
        """,
        (campaign["id"],),
    ).fetchall()
    for event in events:
        payload = _json_object(event["metadata_json"])
        reasons: list[str] = []
        if event["event_type"] == "derived_still_edit_completed":
            reasons.extend(
                str(item.get("reason"))
                for item in payload.get("rejectedPanels") or []
                if isinstance(item, dict) and item.get("reason")
            )
        else:
            reasons.extend(
                str(reason)
                for reason in (_mapping(payload.get("harvest"))).get(
                    "exhaustionReasons"
                )
                or []
            )
        for reason in reasons:
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
    for key, group in groups.items():
        cost = round(sum(request_costs.get(key, {}).values()), 4)
        group["approvalYield"] = (
            group["approved"] / group["candidates"] if group["candidates"] else None
        )
        group["staticReelProductionYield"] = (
            group["staticReels"] / group["approved"] if group["approved"] else None
        )
        group["costUsd"] = cost
        group["costPerExactShaApprovedPanelUsd"] = (
            round(cost / group["approved"], 4) if group["approved"] and cost else None
        )
    return {
        "schema": "campaign_factory.derived_still_inventory_report.v1",
        "campaign": campaign_slug,
        "candidateCount": total,
        "approvedCount": approved,
        "approvalYield": approved / total if total else None,
        "staticReelCount": static_reels,
        "rejectionReasons": rejection_reasons,
        "groups": list(groups.values()),
    }


def derived_receipt_for_source(source: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        return _derived_receipt_from_source(source)
    except (TypeError, ValueError):
        return None


def _default_frame_evaluator(
    path: Path, *, creator: str, identity_root: Path
) -> dict[str, Any]:
    result = evaluate_harvest_frame(path)
    identity = verify_identity(path, creator=creator, root=identity_root)
    rejections = list(result.get("rejections") or [])
    if identity.get("status") != "passed":
        rejections.append("missing_identity_evidence")
    return {
        **result,
        "eligible": not rejections,
        "rejections": rejections,
        "identityVerification": identity,
    }


def _register_candidate(
    factory: Any,
    *,
    campaign: Mapping[str, Any],
    creator: str,
    output_path: Path,
    receipt: dict[str, Any],
    parent_asset_id: str | None,
    audit_status: str,
) -> dict[str, Any]:
    digest = sha256_file(output_path)
    if digest != receipt["output"]["sha256"]:
        raise ValueError("derived still receipt output SHA mismatch")
    model = factory.domains.models.upsert_model(
        creator, name=creator.replace("_", " ").title()
    )
    now = utc_now()
    identity = hashlib.sha256(f"{campaign['id']}:{digest}".encode()).hexdigest()[:20]
    source_id = f"source_derived_{identity}"
    rendered_id = f"asset_derived_{identity}"
    prompt = {"derivedStillSource": receipt}
    with factory.conn:
        factory.conn.execute(
            """
            INSERT OR IGNORE INTO source_assets (
              id, campaign_id, model_id, content_hash, original_path, stored_path,
              filename, media_type, content_surface, platform, source_prompt,
              notes, account_ids_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'image', 'reel', 'instagram', ?,
                      'derived still review candidate', '[]', 'imported', ?, ?)
            """,
            (
                source_id,
                campaign["id"],
                model["id"],
                digest,
                str(output_path),
                str(output_path),
                output_path.name,
                json.dumps(sanitize_for_storage(prompt), sort_keys=True),
                now,
                now,
            ),
        )
        source_row = factory.conn.execute(
            "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], digest),
        ).fetchone()
        if source_row is None:
            raise RuntimeError("derived still source registration failed")
        source_id = str(source_row["id"])
        factory.conn.execute(
            """
            INSERT OR IGNORE INTO rendered_assets (
              id, campaign_id, source_asset_id, parent_asset_id, content_hash,
              output_path, campaign_path, filename, media_type, content_surface,
              creator_model, frame_type, length_class, format_class, recipe,
              target_ratio, metadata_json, audit_status, review_state,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'image', 'reel', ?,
                      'derived_still', 'static', 'image', 'derived_still',
                      'source', ?, ?, 'review_ready', ?, ?)
            """,
            (
                rendered_id,
                campaign["id"],
                source_id,
                parent_asset_id,
                digest,
                str(output_path),
                str(output_path),
                output_path.name,
                creator,
                json.dumps(
                    sanitize_for_storage({"derivedStillSource": receipt}),
                    sort_keys=True,
                ),
                audit_status,
                now,
                now,
            ),
        )
        row = factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], digest),
        ).fetchone()
        if row is None:
            raise RuntimeError("derived still rendered asset registration failed")
        rendered_id = str(row["id"])
        blob_id = f"blob_{digest}"
        attempt_id = new_id("generation_attempt")
        factory.conn.execute(
            """
            INSERT OR IGNORE INTO generation_output_blobs
            (id, content_sha256, byte_size, media_type, created_at)
            VALUES (?, ?, ?, 'image', ?)
            """,
            (blob_id, digest, output_path.stat().st_size, now),
        )
        factory.conn.execute(
            """
            INSERT INTO generation_attempts (
              id, campaign_id, source_asset_id, rendered_asset_id, output_blob_id,
              request_fingerprint, model_id, motion_task, source_sha256, input_json,
              worker_result_json, attempted_output_path, duplicate_disposition, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'canonical_output', ?)
            """,
            (
                attempt_id,
                campaign["id"],
                source_id,
                rendered_id,
                blob_id,
                (receipt.get("evidence") or {}).get("requestFingerprint"),
                str(receipt.get("model") or "local_frame_extraction"),
                str(receipt["operation"]),
                receipt["source"]["sha256"],
                json.dumps(sanitize_for_storage(receipt), sort_keys=True),
                json.dumps(
                    sanitize_for_storage(
                        {"output": receipt["output"], "status": "review_ready"}
                    ),
                    sort_keys=True,
                ),
                str(output_path),
                now,
            ),
        )
        factory.conn.execute(
            """
            INSERT INTO generation_lineage_edges (
              id, generation_attempt_id, source_asset_id, rendered_asset_id,
              output_blob_id, relation, lineage_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'derived_still', ?, ?)
            """,
            (
                new_id("generation_edge"),
                attempt_id,
                source_id,
                rendered_id,
                blob_id,
                json.dumps(sanitize_for_storage(receipt), sort_keys=True),
                now,
            ),
        )
        factory.domains.events.record_event(
            "derived_still_review_ready",
            campaign_id=campaign["id"],
            source_asset_id=source_id,
            rendered_asset_id=rendered_id,
            status="success",
            message=f"Derived still ready for review: {output_path.name}",
            metadata=receipt,
            commit=False,
        )
    return dict(
        factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
        ).fetchone()
    )


def _receipt(
    *,
    source: Mapping[str, Any],
    source_tier: str,
    derivation_depth: int,
    parent_asset_id: str | None,
    root_source_asset_id: str,
    operation: str,
    source_path: Path,
    output_path: Path,
    provider: str | None,
    model: str | None,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    policy = TIER_POLICIES[source_tier]
    return {
        "schema": DERIVED_STILL_SCHEMA,
        "sourceTier": source_tier,
        "derivationDepth": derivation_depth,
        "parentAssetId": parent_asset_id,
        "rootSourceAssetId": root_source_asset_id,
        **policy,
        "creator": source.get("creator_slug") or source.get("creator"),
        "campaignId": source.get("campaign_id"),
        "provider": provider,
        "model": model,
        "operation": operation,
        "source": {
            "assetId": source.get("id"),
            "path": str(source_path),
            "sha256": sha256_file(source_path),
        },
        "output": {
            "path": str(output_path),
            "sha256": sha256_file(output_path),
        },
        "evidence": dict(evidence),
        "createdAt": utc_now(),
        "approval": None,
    }


def _source_row(
    factory: Any, campaign_slug: str, source_asset_id: str
) -> dict[str, Any]:
    row = factory.conn.execute(
        """
        SELECT sa.*, c.slug AS campaign_slug, m.slug AS creator_slug
        FROM source_assets sa
        JOIN campaigns c ON c.id = sa.campaign_id
        JOIN models m ON m.id = sa.model_id
        WHERE sa.id = ? AND c.slug = ?
        """,
        (source_asset_id, campaign_slug),
    ).fetchone()
    if row is None:
        raise ValueError(f"campaign source asset not found: {source_asset_id}")
    return dict(row)


def _source_approval_evidence(
    factory: Any, source: Mapping[str, Any], *, tier: str
) -> dict[str, Any]:
    if str(source.get("status") or "").lower() != "approved":
        raise PermissionError("source must have explicit operator approval")
    event = factory.conn.execute(
        """
        SELECT id, metadata_json, created_at
        FROM activity_events
        WHERE source_asset_id = ? AND event_type = 'source_approval_decided'
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (source["id"],),
    ).fetchone()
    prompt = _json_object(source.get("source_prompt"))
    lineage = prompt.get("generatedAssetLineage")
    review = lineage.get("review") if isinstance(lineage, dict) else None
    qc = review.get("generatedImageQc") if isinstance(review, dict) else None
    generated_qc_passed = bool(
        isinstance(qc, dict)
        and qc.get("status") == "passed"
        and all(
            isinstance(item, dict) and item.get("postable") is True
            for item in qc.get("results") or []
        )
    )
    if tier == "approved_generated_still" and not generated_qc_passed:
        raise PermissionError("generated still lacks passing identity/QC lineage")
    if event is None and not generated_qc_passed:
        raise PermissionError("source lacks exact operator approval evidence")
    return {
        "sourceStatus": source["status"],
        "sourceApprovalEventId": event["id"] if event else None,
        "sourceApprovalEventCreatedAt": event["created_at"] if event else None,
        "generatedImageQcPassed": generated_qc_passed,
    }


def _approved_rendered_asset(
    factory: Any, campaign_slug: str, rendered_asset_id: str
) -> dict[str, Any]:
    row = factory.conn.execute(
        """
        SELECT ra.*, c.slug AS campaign_slug, m.slug AS creator_slug
        FROM rendered_assets ra
        JOIN campaigns c ON c.id = ra.campaign_id
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        JOIN models m ON m.id = sa.model_id
        WHERE ra.id = ? AND c.slug = ?
        """,
        (rendered_asset_id, campaign_slug),
    ).fetchone()
    if row is None:
        raise ValueError(f"campaign rendered asset not found: {rendered_asset_id}")
    asset = dict(row)
    path = Path(str(asset["output_path"])).expanduser().resolve()
    if (
        asset["review_state"] != "approved"
        or not path.is_file()
        or path.is_symlink()
        or sha256_file(path) != asset["content_hash"]
        or not _latest_approval_is(factory, asset["id"], "approved")
    ):
        raise PermissionError("rendered asset lacks exact-SHA operator approval")
    return asset


def _resolve_raw_visual(factory: Any, parent: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _json_object(parent.get("metadata_json"))
    attempt = factory.conn.execute(
        """
        SELECT ga.*, sa.*, m.slug AS creator_slug
        FROM generation_attempts ga
        JOIN source_assets sa ON sa.id = ga.source_asset_id
        JOIN models m ON m.id = sa.model_id
        WHERE ga.rendered_asset_id = ?
        ORDER BY ga.created_at DESC, ga.id DESC LIMIT 1
        """,
        (parent["id"],),
    ).fetchone()
    if attempt is None:
        raise ValueError("approved Reel has no generation lineage")
    attempt_data = dict(attempt)
    candidates = [
        metadata.get("visualInput"),
        (_mapping(metadata.get("derivation"))).get("visualInput"),
        (_mapping(metadata.get("audioEmbeddingReceipt"))).get("originalVideo"),
    ]
    raw_rendered = factory.conn.execute(
        """
        SELECT ra.output_path, ra.content_hash, ra.metadata_json
        FROM generation_lineage_edges gle
        JOIN rendered_assets ra ON ra.id = gle.rendered_asset_id
        WHERE gle.generation_attempt_id = ? AND gle.relation = 'generated_output'
        ORDER BY gle.created_at DESC LIMIT 1
        """,
        (attempt_data["id"],),
    ).fetchone()
    if raw_rendered:
        candidates.append(
            {
                "path": raw_rendered["output_path"],
                "sha256": raw_rendered["content_hash"],
            }
        )
    selected = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
            and candidate.get("path")
            and candidate.get("sha256")
            and Path(str(candidate["path"])).expanduser().resolve().is_file()
            and sha256_file(Path(str(candidate["path"])).expanduser().resolve())
            == candidate["sha256"]
        ),
        None,
    )
    if selected is None:
        raise ValueError("only captioned or untraceable final media is available")
    model_id = str(
        attempt_data.get("model_id")
        or (_mapping(metadata.get("generation"))).get("model")
        or metadata.get("recipe")
        or ""
    )
    source_asset = {
        key: attempt_data[key]
        for key in (
            "source_asset_id",
            "campaign_id",
            "model_id",
            "content_hash",
            "stored_path",
            "creator_slug",
        )
        if key in attempt_data
    }
    source_asset["id"] = attempt_data["source_asset_id"]
    source_asset["creator"] = attempt_data["creator_slug"]
    return {
        "path": str(Path(str(selected["path"])).expanduser().resolve()),
        "sha256": str(selected["sha256"]),
        "modelId": model_id,
        "creator": attempt_data["creator_slug"],
        "providerOutputId": _first_nested_string(
            metadata, ("generationId", "predictionId", "providerOutputId", "requestId")
        ),
        "sourceAsset": source_asset,
    }


def _approved_tiered_image(
    factory: Any, campaign_slug: str, image_asset_id: str
) -> dict[str, Any]:
    rendered = factory.conn.execute(
        """
        SELECT ra.*, sa.*, c.slug AS campaign_slug, m.slug AS creator_slug,
               ra.id AS rendered_id, sa.id AS source_id,
               ra.content_hash AS rendered_hash, sa.content_hash AS source_hash,
               ra.output_path AS rendered_path, sa.stored_path AS source_path
        FROM rendered_assets ra
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        JOIN campaigns c ON c.id = ra.campaign_id
        JOIN models m ON m.id = sa.model_id
        WHERE ra.id = ? AND c.slug = ?
        """,
        (image_asset_id, campaign_slug),
    ).fetchone()
    if rendered is not None:
        row = dict(rendered)
        source = factory.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?", (row["source_id"],)
        ).fetchone()
        path = Path(str(row["rendered_path"])).expanduser().resolve()
        receipt = _json_object(row.get("metadata_json")).get("derivedStillSource")
        if (
            row["review_state"] != "approved"
            or not _latest_approval_is(factory, row["rendered_id"], "approved")
            or not path.is_file()
            or sha256_file(path) != row["rendered_hash"]
        ):
            raise PermissionError("image asset lacks exact-SHA approval")
        source_asset = dict(source)
        return {
            "sourceAsset": source_asset,
            "renderedAssetId": row["rendered_id"],
            "creator": row["creator_slug"],
            "path": str(path),
            "sha256": row["rendered_hash"],
            "derivedReceipt": _validate_receipt(receipt),
        }
    source = _source_row(factory, campaign_slug, image_asset_id)
    path = _verified_image(source)
    receipt = _derived_receipt_from_source(source)
    if source["status"] != "approved":
        raise PermissionError("tiered still source is not approved")
    return {
        "sourceAsset": source,
        "renderedAssetId": None,
        "creator": source["creator_slug"],
        "path": str(path),
        "sha256": source["content_hash"],
        "derivedReceipt": receipt,
    }


def _authorize_spend(
    factory: Any,
    *,
    campaign_id: str,
    request_fingerprint: str,
    provider: str,
    quote: Mapping[str, Any],
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    ensure_authorization_table(factory.conn)
    now = datetime.now(UTC)
    authorization_id = new_id("spauth")
    reservation_id = new_id("spres")
    with factory.conn:
        existing = factory.conn.execute(
            f"SELECT status FROM {AUTHORIZATION_TABLE} WHERE request_fingerprint = ?",
            (request_fingerprint,),
        ).fetchone()
        if existing:
            raise PermissionError("provider spend request already authorized")
        factory.conn.execute(
            f"""
            INSERT INTO {AUTHORIZATION_TABLE} (
              authorization_id, reservation_id, provider, campaign_id, cohort_id,
              request_fingerprint, amount, unit, scope_json, provider_quote_json,
              status, issued_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, 'authorized', ?, ?)
            """,
            (
                authorization_id,
                reservation_id,
                provider,
                campaign_id,
                f"derived_stills:{campaign_id}",
                request_fingerprint,
                float(quote["amount"]),
                json.dumps(sanitize_for_storage(dict(scope)), sort_keys=True),
                json.dumps(sanitize_for_storage(dict(quote)), sort_keys=True),
                now.isoformat(),
                (now + timedelta(minutes=10)).isoformat(),
            ),
        )
    return {
        "authorizationId": authorization_id,
        "reservationId": reservation_id,
        "requestFingerprint": request_fingerprint,
        "provider": provider,
        "quote": dict(quote),
    }


def _consume_spend(
    factory: Any,
    *,
    authorization: Mapping[str, Any],
    provider_result: Mapping[str, Any],
    quote: Mapping[str, Any],
    campaign_id: str,
) -> None:
    now = utc_now()
    with factory.conn:
        cursor = factory.conn.execute(
            f"""
            UPDATE {AUTHORIZATION_TABLE}
            SET status = 'consumed', consumed_at = ?
            WHERE authorization_id = ? AND status = 'authorized'
            """,
            (now, authorization["authorizationId"]),
        )
        if cursor.rowcount != 1:
            raise PermissionError("derived still spend authorization is not consumable")
    record_ai_cost(
        factory.conn,
        provider=str(provider_result.get("provider")),
        operation="derived_still_edit",
        campaign_id=campaign_id,
        generations=1,
        source_event_key=(
            f"derived_still:{authorization['requestFingerprint']}:"
            f"{provider_result.get('requestId') or 'reconciled'}"
        ),
        reservation_id=str(authorization["reservationId"]),
        amount=float(quote["amount"]),
        unit="USD",
        provider_quote=dict(quote),
        metadata={
            "requestFingerprint": authorization["requestFingerprint"],
            "providerRequestId": provider_result.get("requestId"),
            "usage": provider_result.get("usage"),
        },
    )


def _cancel_spend(factory: Any, authorization_id: str) -> None:
    with factory.conn:
        factory.conn.execute(
            f"""
            UPDATE {AUTHORIZATION_TABLE}
            SET status = 'cancelled', cancelled_at = ?
            WHERE authorization_id = ? AND status = 'authorized'
            """,
            (utc_now(), authorization_id),
        )


def _cached_edit(factory: Any, request_fingerprint: str) -> dict[str, Any] | None:
    rows = factory.conn.execute(
        """
        SELECT metadata_json
        FROM activity_events
        WHERE event_type = 'derived_still_edit_completed'
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    for row in rows:
        payload = _json_object(row["metadata_json"])
        if payload.get("requestFingerprint") != request_fingerprint:
            continue
        assets = payload.get("registeredAssets")
        if not isinstance(assets, list):
            continue
        valid = True
        for asset in assets:
            if not isinstance(asset, dict):
                valid = False
                break
            path = Path(str(asset.get("output_path") or "")).expanduser().resolve()
            if not path.is_file() or sha256_file(path) != str(
                asset.get("content_hash") or ""
            ):
                valid = False
                break
        if valid:
            return payload
    return None


def _derived_receipt_from_source(source: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_receipt(
        _json_object(source.get("source_prompt")).get("derivedStillSource")
    )


def _validate_receipt(receipt: Any) -> dict[str, Any]:
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != DERIVED_STILL_SCHEMA
        or receipt.get("sourceTier") not in TIER_POLICIES
        or receipt.get("allowedOperations")
        != TIER_POLICIES[receipt["sourceTier"]]["allowedOperations"]
    ):
        raise ValueError("derived still receipt is missing or invalid")
    return receipt


def _verified_image(source: Mapping[str, Any]) -> Path:
    if source.get("media_type") != "image":
        raise ValueError("derived still source must be an image")
    raw = Path(str(source["stored_path"])).expanduser()
    if raw.is_symlink():
        raise ValueError("derived still source must not be a symlink")
    path = raw.resolve()
    if not path.is_file() or sha256_file(path) != source["content_hash"]:
        raise ValueError("derived still source SHA mismatch")
    return path


def _latest_approval_is(factory: Any, asset_id: str, decision: str) -> bool:
    row = factory.conn.execute(
        """
        SELECT decision FROM approval_decisions
        WHERE rendered_asset_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (asset_id,),
    ).fetchone()
    return row is not None and row["decision"] == decision


def _positive_usd_quote(quote: Mapping[str, Any]) -> float:
    amount = quote.get("amount")
    if (
        quote.get("unit") != "USD"
        or isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(float(amount))
        or float(amount) <= 0
    ):
        raise ValueError("provider quote must be a finite positive USD amount")
    return float(amount)


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            sanitize_for_storage(dict(value)),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _first_nested_string(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        for child in value.values():
            found = _first_nested_string(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_nested_string(child, keys)
            if found:
                return found
    return None
