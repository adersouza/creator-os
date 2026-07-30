from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.evidence_attestation import payload_fingerprint
from creator_os_core.fileops import atomic_write_text, file_lock

LEGACY_INVENTORY_SCHEMA = "campaign_factory.creative_approval_legacy_inventory.v1"


class CreativeApprovalError(RuntimeError):
    """The supplied approval is incomplete, unsafe, or no longer exact."""


def fingerprint(payload: dict[str, Any]) -> str:
    return payload_fingerprint(payload)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CreativeApprovalError(f"creative_approval_{field}_missing")
    return normalized


def sha(value: Any, field: str) -> str:
    normalized = required_text(value, field)
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise CreativeApprovalError(f"creative_approval_{field}_invalid")
    return normalized


def is_sha(value: Any) -> bool:
    normalized = str(value or "")
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def timestamp(value: Any, field: str) -> datetime:
    normalized = required_text(value, field)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CreativeApprovalError(f"creative_approval_{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise CreativeApprovalError(f"creative_approval_{field}_timezone_missing")
    return parsed.astimezone(UTC)


def verify_bound_file(binding: Any, field: str) -> dict[str, str]:
    if not isinstance(binding, dict):
        raise CreativeApprovalError(f"creative_approval_{field}_invalid")
    path = (
        Path(required_text(binding.get("path"), f"{field}_path")).expanduser().resolve()
    )
    expected = sha(binding.get("sha256"), f"{field}_sha256")
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
        raise CreativeApprovalError(f"creative_approval_{field}_missing_or_substituted")
    return {"path": str(path), "sha256": expected}


def load_bound_json(binding: Any, field: str) -> tuple[dict[str, Any], dict[str, str]]:
    verified = verify_bound_file(binding, field)
    try:
        decoded = json.loads(Path(verified["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CreativeApprovalError(f"creative_approval_{field}_invalid_json") from exc
    if not isinstance(decoded, dict):
        raise CreativeApprovalError(f"creative_approval_{field}_invalid_json")
    return decoded, verified


def write_content_addressed_json(
    root: Path, *, label: str, payload: dict[str, Any]
) -> dict[str, str]:
    directory = root.expanduser().resolve() / label
    if directory.exists() and directory.is_symlink():
        raise CreativeApprovalError(f"creative_approval_{label}_directory_unsafe")
    directory.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    path = directory / f"{digest}.json"
    with file_lock(directory / ".lock"):
        if path.exists() or path.is_symlink():
            if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
                raise CreativeApprovalError(
                    f"creative_approval_{label}_identity_collision"
                )
        else:
            atomic_write_text(path, encoded, encoding="utf-8")
            path.chmod(0o444)
    return {"path": str(path), "sha256": digest}


def creative_export_projection(
    draft: dict[str, Any],
    *,
    campaign_slug: str,
    schema: str,
    prompt_source: dict[str, str] | None = None,
) -> dict[str, Any]:
    draft_content = draft.get("content")
    post_caption = draft.get("instagramPostCaption")
    if not isinstance(draft_content, str) or not isinstance(post_caption, str):
        raise CreativeApprovalError("creative_approval_draft_content_missing")
    if draft_content != post_caption:
        raise CreativeApprovalError("creative_approval_draft_content_caption_mismatch")
    volatile_keys = {
        "createdAt",
        "updatedAt",
        "uploadedAt",
        "exported_at",
        "campaignFactoryExportId",
        "url",
        "thumbnailUrl",
    }

    def stable(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: stable(item)
                for key, item in sorted(value.items())
                if key not in volatile_keys
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    def bound(value: Any) -> str | None:
        return fingerprint(stable(value)) if isinstance(value, dict) else None

    core = {
        "schema": schema,
        "campaignId": draft.get("campaignId"),
        "campaignSlug": campaign_slug,
        "renderedAssetId": draft.get("renderedAssetId"),
        "sourceAssetId": draft.get("sourceAssetId"),
        "contentSha256": draft.get("contentHash"),
        "accountId": draft.get("accountId"),
        "instagramAccountId": draft.get("instagramAccountId"),
        "distributionPlanId": draft.get("distributionPlanId"),
        "distributionSurface": draft.get("distributionSurface"),
        "contentSurface": draft.get("contentSurface"),
        "content": draft_content,
        "instagramPostCaption": post_caption,
        "instagramPostCaptionHash": draft.get("instagramPostCaptionHash"),
        "burnedCaptionText": draft.get("burnedCaptionText"),
        "burnedCaptionHash": draft.get("burnedCaptionHash"),
        "captionFallbackReason": (
            (draft.get("captionOutcomeContext") or {})
            .get("captionFallback", {})
            .get("reasonCode")
            if isinstance(
                (draft.get("captionOutcomeContext") or {}).get("captionFallback"),
                dict,
            )
            else (draft.get("captionOutcomeContext") or {}).get(
                "caption_fallback_reason"
            )
        ),
        "overlaySemanticQcFingerprint": bound(draft.get("overlaySemanticQc")),
        "captionTimingQcFingerprint": bound(draft.get("captionTimingQc")),
        "publishMode": draft.get("publishMode"),
        "instagramTrialReels": draft.get("instagramTrialReels") is True,
        "trialGraduationStrategy": draft.get("trialGraduationStrategy"),
        "shareToFeed": draft.get("shareToFeed") is True,
        "collaborators": list(draft.get("collaborators") or []),
        "audioIntentFingerprint": bound(draft.get("audioIntent")),
        "variationAssignmentFingerprint": bound(draft.get("variantAssignment")),
    }
    if prompt_source is not None:
        core["promptSourceSha256"] = sha(
            prompt_source.get("sha256"), "prompt_source_sha256"
        )
    return {**core, "fingerprint": fingerprint(core)}


def operator_media_review_receipt(
    decision: dict[str, Any],
    *,
    rendered_asset_id: str,
    final_sha256: str,
    review_manifest_sha256: str,
    reviewed_by: str,
    reviewed_at: str,
    schema: str,
) -> dict[str, Any]:
    fields = (
        "identityAcceptable",
        "faceStable",
        "bodyConsistent",
        "anatomyAcceptable",
        "motionAcceptable",
        "captionAcceptable",
        "audioAcceptable",
        "intentSatisfied",
        "wouldPost",
    )
    verdicts: dict[str, bool] = {}
    for field in fields:
        if not isinstance(decision.get(field), bool):
            raise CreativeApprovalError(f"operator_media_review_{field}_missing")
        verdicts[field] = decision[field]
    if not all(verdicts.values()):
        failed = ",".join(field for field, passed in verdicts.items() if not passed)
        raise CreativeApprovalError(f"operator_media_review_rejected:{failed}")
    core = {
        "schema": schema,
        "reviewId": "media-review-"
        + fingerprint(
            {
                "renderedAssetId": rendered_asset_id,
                "finalSha256": final_sha256,
                "reviewManifestSha256": review_manifest_sha256,
                "reviewedBy": reviewed_by,
                "reviewedAt": reviewed_at,
                **verdicts,
                "notes": decision.get("notes"),
            }
        )[:24],
        "renderedAssetId": rendered_asset_id,
        "finalSha256": final_sha256,
        "reviewManifestSha256": review_manifest_sha256,
        "reviewedBy": reviewed_by,
        "reviewedAt": reviewed_at,
        **verdicts,
        "notes": decision.get("notes"),
    }
    return {**core, "reviewFingerprint": fingerprint(core)}


def validate_operator_media_review(
    binding: Any,
    *,
    rendered_asset_id: str,
    final_sha256: str,
    review_manifest_sha256: str,
    approved_by: str,
    approved_at: datetime,
    schema: str,
) -> dict[str, Any]:
    receipt, _ = load_bound_json(binding, "operator_review")
    if receipt.get("schema") != schema:
        raise CreativeApprovalError("operator_media_review_schema_invalid")
    core = dict(receipt)
    claimed = sha(core.pop("reviewFingerprint", None), "operator_review_fingerprint")
    if fingerprint(core) != claimed:
        raise CreativeApprovalError("operator_media_review_fingerprint_mismatch")
    if (
        receipt.get("renderedAssetId") != rendered_asset_id
        or receipt.get("finalSha256") != final_sha256
        or receipt.get("reviewManifestSha256") != review_manifest_sha256
        or receipt.get("reviewedBy") != approved_by
        or timestamp(receipt.get("reviewedAt"), "operator_review_reviewed_at")
        > approved_at
    ):
        raise CreativeApprovalError("operator_media_review_binding_mismatch")
    required = (
        "identityAcceptable",
        "faceStable",
        "bodyConsistent",
        "anatomyAcceptable",
        "motionAcceptable",
        "captionAcceptable",
        "audioAcceptable",
        "intentSatisfied",
        "wouldPost",
    )
    if any(receipt.get(field) is not True for field in required):
        raise CreativeApprovalError("operator_media_review_not_approved")
    return receipt
