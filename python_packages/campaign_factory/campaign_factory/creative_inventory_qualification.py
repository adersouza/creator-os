from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .asset_evidence import (
    final_artifact_integrity_for_publishability,
    verify_registered_asset_bytes,
)

PRODUCT_MODE_LINEAGE_SCHEMA = "campaign_factory.product_mode_lineage.v1"
QUALIFICATION_SCHEMA = "campaign_factory.creative_inventory_qualification.v1"
REVIEW_QUEUE_SCHEMA = "creator_os.creative_inventory_review_queue.v1"
REVIEW_MANIFEST_SCHEMA = "creator_os.creative_inventory_review_manifest.v1"
PRODUCT_MODES = {"static_reel", "calm_animation", "recreate_reel"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def product_mode_lineage(
    *,
    product_mode: str | None,
    evidence_source: str | None = None,
    evidence_sha256: str | None = None,
) -> dict[str, Any]:
    """Build explicit import lineage without deriving a mode from filenames or media."""

    mode = str(product_mode or "").strip()
    source = str(evidence_source or "").strip()
    evidence_sha = str(evidence_sha256 or "").strip().lower()
    if not mode and not source and not evidence_sha:
        return {
            "schema": PRODUCT_MODE_LINEAGE_SCHEMA,
            "status": "unclassified",
            "productMode": None,
            "evidenceSource": None,
            "evidenceSha256": None,
            "reason": "explicit_product_mode_evidence_not_supplied",
        }
    if mode not in PRODUCT_MODES:
        raise ValueError(
            "product_mode must be static_reel, calm_animation, or recreate_reel"
        )
    failure_reason: str | None = None
    verified_sha: str | None = None
    evidence_path: Path | None = None
    if not source:
        failure_reason = "product_mode_evidence_source_missing"
    elif not _SHA256_RE.fullmatch(evidence_sha):
        failure_reason = "product_mode_evidence_sha256_invalid"
    else:
        candidate = Path(source).expanduser()
        try:
            if candidate.is_symlink() or not candidate.is_file():
                failure_reason = "product_mode_evidence_artifact_unreadable"
            else:
                evidence_path = candidate.resolve(strict=True)
                with evidence_path.open("rb") as handle:
                    verified_sha = hashlib.file_digest(handle, "sha256").hexdigest()
                if verified_sha != evidence_sha:
                    failure_reason = "product_mode_evidence_sha256_mismatch"
        except OSError:
            failure_reason = "product_mode_evidence_artifact_unreadable"
    if failure_reason:
        return {
            "schema": PRODUCT_MODE_LINEAGE_SCHEMA,
            "status": "unverified",
            "productMode": mode,
            "evidenceSource": str(evidence_path or source) or None,
            "evidenceSha256": evidence_sha or None,
            "verifiedEvidenceSha256": verified_sha,
            "reason": failure_reason,
        }
    return {
        "schema": PRODUCT_MODE_LINEAGE_SCHEMA,
        "status": "verified",
        "productMode": mode,
        "evidenceSource": str(evidence_path),
        "evidenceSha256": evidence_sha,
        "verifiedEvidenceSha256": verified_sha,
        "reason": None,
    }


def extract_product_mode_lineage(asset: dict[str, Any]) -> dict[str, Any]:
    metadata = _json_object(asset.get("metadata_json"))
    caption_context = _json_object(asset.get("caption_outcome_context_json"))
    caption_generation = _json_object(asset.get("caption_generation_json"))
    source_prompt = _json_object(asset.get("source_prompt_json"))
    for payload in (metadata, caption_context, caption_generation, source_prompt):
        candidate = payload.get("productModeLineage")
        if isinstance(candidate, dict):
            try:
                return product_mode_lineage(
                    product_mode=candidate.get("productMode"),
                    evidence_source=candidate.get("evidenceSource"),
                    evidence_sha256=candidate.get("evidenceSha256"),
                )
            except ValueError as exc:
                return {
                    "schema": PRODUCT_MODE_LINEAGE_SCHEMA,
                    "status": "invalid",
                    "productMode": candidate.get("productMode"),
                    "evidenceSource": candidate.get("evidenceSource"),
                    "evidenceSha256": candidate.get("evidenceSha256"),
                    "reason": str(exc),
                }

    recipe = str(asset.get("recipe") or "").strip()
    content_intent = str(metadata.get("contentIntent") or "").strip()
    explicit_mode: str | None = None
    if recipe == "static_mp4":
        explicit_mode = "static_reel"
    elif content_intent == "passive_selfie" and recipe == "higgsfield_kling3_i2v":
        explicit_mode = "calm_animation"
    elif content_intent == "recreate_reel" and "recreate_reel" in recipe:
        explicit_mode = "recreate_reel"
    if explicit_mode:
        return {
            "schema": PRODUCT_MODE_LINEAGE_SCHEMA,
            "status": "verified_system_recipe",
            "productMode": explicit_mode,
            "evidenceSource": f"rendered_assets.recipe:{recipe}",
            "evidenceSha256": None,
            "reason": None,
        }
    return product_mode_lineage(product_mode=None)


def qualify_creative_inventory_asset(
    asset: dict[str, Any],
    *,
    audit: dict[str, Any] | None = None,
    final_integrity: dict[str, Any] | None = None,
    caption_repeat_count: int = 1,
    audio_intent_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = _json_object(asset.get("metadata_json"))
    caption_context = _json_object(asset.get("caption_outcome_context_json"))
    caption_generation = _json_object(asset.get("caption_generation_json"))
    lineage = extract_product_mode_lineage(asset)
    mode = lineage.get("productMode")
    recipe = str(asset.get("recipe") or "")
    applicable = bool(
        recipe == "finished_video_registered"
        or mode in PRODUCT_MODES
        or isinstance(metadata.get("productModeLineage"), dict)
    )
    blockers: list[str] = []
    warnings: list[str] = []
    subject_sha = str(asset.get("content_hash") or asset.get("contentHash") or "")

    if lineage.get("status") not in {"verified", "verified_system_recipe"}:
        blockers.append("product_mode_lineage_unclassified")

    integrity = final_integrity or verify_registered_asset_bytes(asset)
    if integrity.get("passed") is not True:
        blockers.append("exact_final_sha_unverified")
    audit_payload = audit if isinstance(audit, dict) else {}
    if (
        audit_payload.get("subjectSha256") != subject_sha
        or audit_payload.get("overallVerdict") != "pass"
    ):
        blockers.append("exact_final_audit_unverified")

    if mode == "recreate_reel":
        compatibility = metadata.get("recreationCharacterCompatibility")
        if (
            not isinstance(compatibility, dict)
            or compatibility.get("permissionGranted") is not True
        ):
            blockers.append("recreate_permission_not_granted")

    audio_receipt = _first_object(
        metadata.get("audioEmbeddingReceipt"),
        caption_generation.get("audioEmbeddingReceipt"),
        metadata.get("audio"),
    )
    audio_intent = _first_object(
        audio_intent_override,
        metadata.get("audioIntent"),
        caption_generation.get("audioIntent"),
        audio_receipt.get("audioIntent"),
    )
    audio_binding = _audio_binding(audio_receipt, audio_intent, subject_sha)
    if audio_binding["passed"] is not True:
        blockers.extend(audio_binding["failures"])
    rights = _first_object(audio_intent.get("rights"), audio_receipt.get("rights"))
    if not _rights_are_exact(rights):
        blockers.append("audio_rights_evidence_unverified")

    burned_caption = bool(
        caption_context.get("captionBurnedIn") is True
        or str(caption_context.get("burned_caption_text") or "").strip()
    )
    caption_lineage = _caption_lineage_evidence(caption_generation, caption_context)
    caption_variant_type = str(caption_lineage.get("variantType") or "").strip()
    placement = _first_object(
        caption_context.get("captionPlacementDecision"),
        caption_lineage.get("captionPlacementDecision"),
    )
    if burned_caption:
        if caption_variant_type == "timed":
            if not _timed_semantic_approval_is_exact(caption_lineage):
                blockers.append("timed_caption_semantic_approval_unverified")
        elif caption_variant_type == "static":
            if not _static_caption_lineage_is_exact(caption_lineage):
                blockers.append("static_caption_lineage_unverified")
        else:
            blockers.append("caption_variant_lineage_unclassified")
        if not _placement_approval_is_exact(placement, subject_sha):
            blockers.append("caption_placement_approval_unverified")

    if caption_repeat_count > 1 and str(asset.get("caption") or "").strip():
        blockers.append("caption_repeated_in_inventory")
        warnings.append(f"caption_repeat_count:{caption_repeat_count}")

    blockers = sorted(set(blockers))
    return {
        "schema": QUALIFICATION_SCHEMA,
        "applicable": applicable,
        "renderedAssetId": asset.get("id"),
        "subjectSha256": subject_sha or None,
        "productModeLineage": lineage,
        "captionRepeatCount": caption_repeat_count,
        "audioBinding": audio_binding,
        "burnedCaption": burned_caption,
        "captionVariantType": caption_variant_type or None,
        "productionQualified": applicable and not blockers,
        "blockingReasons": blockers,
        "warnings": warnings,
        "grantsApproval": False,
        "grantsPublishAuthority": False,
    }


def apply_gate(
    repository: Any,
    asset: dict[str, Any],
    audit: dict[str, Any] | None,
    checks: dict[str, bool],
    failures: list[str],
) -> dict[str, Any]:
    """Apply the final-inventory gate without growing the publishability owner."""

    audio_intent, _ = repository._audio_selection_for_asset(asset)
    result = qualify_creative_inventory_asset(
        asset,
        audit=audit,
        final_integrity=final_artifact_integrity_for_publishability(asset, audit),
        caption_repeat_count=caption_repeat_count(
            repository.conn, asset.get("caption")
        ),
        audio_intent_override=audio_intent,
    )
    checks["creative_inventory_qualified"] = bool(
        not result["applicable"] or result["productionQualified"]
    )
    if result["applicable"]:
        failures.extend(result["blockingReasons"])
    return result


def build_operator_review_queue(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    *,
    byte_verifier: Callable[
        [dict[str, Any]], dict[str, Any]
    ] = verify_registered_asset_bytes,
) -> dict[str, Any]:
    if manifest.get("schema") != REVIEW_MANIFEST_SCHEMA:
        raise ValueError("invalid creative inventory review manifest schema")
    if manifest.get("publishAuthority") is not False:
        raise ValueError("review manifest must explicitly deny publish authority")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("review manifest entries are required")

    caption_counts = _caption_counts(conn)
    queue: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, request in enumerate(entries, 1):
        if not isinstance(request, dict):
            raise ValueError("review manifest entry must be an object")
        asset_id = str(request.get("renderedAssetId") or "").strip()
        expected_sha = str(request.get("expectedSha256") or "").strip().lower()
        if not asset_id or asset_id in seen_ids:
            raise ValueError("review manifest asset ids must be non-empty and unique")
        if not _SHA256_RE.fullmatch(expected_sha):
            raise ValueError(f"invalid expected SHA-256 for {asset_id}")
        seen_ids.add(asset_id)
        row = conn.execute(
            """
            SELECT r.*, s.source_prompt AS source_prompt_json
            FROM rendered_assets r
            LEFT JOIN source_assets s ON s.id = r.source_asset_id
            WHERE r.id = ?
            """,
            (asset_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"review manifest asset not found:{asset_id}")
        asset = dict(row)
        if str(asset.get("content_hash") or "").lower() != expected_sha:
            raise ValueError(f"review manifest SHA mismatch:{asset_id}")
        byte_integrity = byte_verifier(asset)
        if byte_integrity.get("passed") is not True:
            raise ValueError(f"review manifest physical SHA mismatch:{asset_id}")
        audit = _latest_audit_payload(conn, asset_id)
        repeat_count = caption_counts.get(_normalize_caption(asset.get("caption")), 1)
        qualification = qualify_creative_inventory_asset(
            asset,
            audit=audit,
            final_integrity=byte_integrity,
            caption_repeat_count=repeat_count,
        )
        recommendation = str(
            request.get("recommendation") or "operator_review_candidate"
        )
        queue.append(
            {
                "day": int(request.get("day") or index),
                "renderedAssetId": asset_id,
                "expectedSha256": expected_sha,
                "creator": request.get("creator"),
                "declaredClassification": request.get("classification"),
                "recommendation": recommendation,
                "queueStatus": "hold"
                if recommendation in {"hold", "reject"}
                else "ready_for_operator_review",
                "operatorDecisionRequired": True,
                "productionQualified": qualification["productionQualified"],
                "qualification": qualification,
                "reviewStateUnchanged": True,
            }
        )
    return {
        "schema": REVIEW_QUEUE_SCHEMA,
        "sourceManifest": manifest.get("name"),
        "publishAuthority": False,
        "approvalAuthority": False,
        "databaseMutation": False,
        "entries": sorted(
            queue, key=lambda item: (item["day"], item["renderedAssetId"])
        ),
    }


def open_read_only_database(path: Path) -> sqlite3.Connection:
    database = path.expanduser().resolve()
    conn = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _audio_binding(
    receipt: dict[str, Any], audio_intent: dict[str, Any], subject_sha: str
) -> dict[str, Any]:
    fulfillment = _first_object(audio_intent.get("fulfillment"))
    verification = _first_object(receipt.get("verification"))
    output_sha = _first_text(
        receipt.get("outputSha256"),
        receipt.get("fulfillmentOutputSha256"),
        _nested(receipt, "output", "sha256"),
        _nested(receipt, "finalVideo", "sha256"),
        fulfillment.get("output_sha256"),
    )
    audio_present = _first_present(
        verification.get("audioPresent"),
        receipt.get("audioPresent"),
        fulfillment.get("audio_present"),
    )
    status = _first_text(
        verification.get("status"),
        receipt.get("fulfillmentStatus"),
        fulfillment.get("status"),
    )
    failures: list[str] = []
    if audio_present is not True or status != "verified":
        failures.append("embedded_audio_unverified")
    if output_sha != subject_sha:
        failures.append("audio_final_sha_unbound")
    return {
        "passed": not failures,
        "outputSha256": output_sha,
        "audioPresent": audio_present is True,
        "status": status,
        "failures": sorted(set(failures)),
    }


def _rights_are_exact(rights: dict[str, Any]) -> bool:
    status = str(rights.get("usageRightsStatus") or "")
    receipt = _first_object(rights.get("evidenceReceipt"))
    receipt_sha = str(receipt.get("sha256") or "").lower()
    return bool(
        status
        in {
            "platform_native_authorized",
            "operator_supplied_authorized",
            "licensed",
        }
        and rights.get("commercialUseAllowed") is True
        and all(
            str(rights.get(key) or "").strip()
            for key in ("rightsSource", "territory", "accountScope")
        )
        and str(receipt.get("id") or "").strip()
        and _SHA256_RE.fullmatch(receipt_sha)
    )


def _caption_lineage_evidence(
    caption_generation: dict[str, Any], caption_context: dict[str, Any]
) -> dict[str, Any]:
    return _first_object(
        caption_generation.get("captionLineage"),
        caption_context.get("captionLineage"),
        _nested(caption_generation, "captionHook", "captionLineage"),
    )


def _timed_semantic_approval_is_exact(lineage: dict[str, Any]) -> bool:
    if lineage.get("variantType") != "timed":
        return False
    if any(
        not str(lineage.get(key) or "").strip()
        for key in ("approvalId", "approvalReviewer", "approvalDecidedAt")
    ):
        return False
    if not _SHA256_RE.fullmatch(str(lineage.get("approvalFileSha") or "").lower()):
        return False
    match = _first_object(lineage.get("contentMatch"))
    if any(
        not str(match.get(key) or "").strip()
        for key in ("family", "visual_intensity", "delivery")
    ):
        return False
    for key in ("scene_tags", "action_tags", "required_context_tags"):
        tags = match.get(key)
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) or not tag.strip() for tag in tags
        ):
            return False
    return bool(match.get("scene_tags") and match.get("action_tags"))


def _static_caption_lineage_is_exact(lineage: dict[str, Any]) -> bool:
    if (
        lineage.get("schema") != "reel_factory.caption_lineage.v1"
        or lineage.get("variantType") != "static"
    ):
        return False
    hashes = {
        key: str(lineage.get(key) or "").strip().lower()
        for key in (
            "captionHash",
            "staticTextHash",
            "captionPayloadHash",
            "captionBankSourceHash",
        )
    }
    if any(not _SHA256_RE.fullmatch(value) for value in hashes.values()):
        return False
    if hashes["captionHash"] != hashes["staticTextHash"]:
        return False
    if any(
        not str(lineage.get(key) or "").strip()
        for key in ("rawCaptionText", "captionBankVersion")
    ):
        return False
    selected_banks = lineage.get("selectedBanks")
    return bool(
        isinstance(selected_banks, list)
        and selected_banks
        and all(isinstance(bank, str) and bank.strip() for bank in selected_banks)
    )


def _placement_approval_is_exact(decision: dict[str, Any], subject_sha: str) -> bool:
    bound_sha = _first_text(
        decision.get("subjectSha256"), decision.get("finalMediaSha256")
    )
    sample_count = decision.get("sampleCount")
    return bool(
        decision.get("status") == "passed"
        and str(decision.get("selectedLane") or "").strip()
        and isinstance(sample_count, int)
        and sample_count > 0
        and bound_sha == subject_sha
    )


def _latest_audit_payload(conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM audit_reports WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
        (asset_id,),
    ).fetchone()
    if not row:
        return {}
    stored = dict(row)
    report_path = Path(str(stored.get("report_path") or ""))
    payload: dict[str, Any] = {}
    if report_path.is_file() and not report_path.is_symlink():
        try:
            decoded = json.loads(report_path.read_text(encoding="utf-8"))
            payload = decoded if isinstance(decoded, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = {}
    return {
        **stored,
        **payload,
        "subjectSha256": payload.get("subjectSha256") or stored.get("subject_sha256"),
        "overallVerdict": payload.get("overallVerdict")
        or stored.get("overall_verdict"),
    }


def _caption_counts(conn: sqlite3.Connection) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in conn.execute(
        "SELECT caption FROM rendered_assets WHERE caption IS NOT NULL"
    ):
        normalized = _normalize_caption(row[0])
        if normalized:
            counts[normalized] += 1
    return counts


def caption_repeat_count(conn: sqlite3.Connection, caption: Any) -> int:
    normalized = _normalize_caption(caption)
    if not normalized:
        return 1
    return _caption_counts(conn).get(normalized, 1)


def _normalize_caption(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _first_object(*values: Any) -> dict[str, Any]:
    return next((value for value in values if isinstance(value, dict) and value), {})


def _first_text(*values: Any) -> str | None:
    return next(
        (str(value) for value in values if isinstance(value, str) and value.strip()),
        None,
    )


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _load_manifest(path: Path) -> dict[str, Any]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("creative inventory manifest must be a JSON object")
    return decoded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a read-only creative inventory review queue"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    conn = open_read_only_database(args.db)
    try:
        queue = build_operator_review_queue(conn, _load_manifest(args.manifest))
    finally:
        conn.close()
    print(json.dumps(queue, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
