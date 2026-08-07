"""Inventory and safely quarantine non-production creative-approval evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_json
from creator_os_core.fileops import sha256_file as _sha256_file

SCHEMA = "campaign_factory.creative_approval_evidence_hygiene.v1"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def fixture_evidence_reasons(
    payload: dict[str, Any],
    *,
    path: Path | None = None,
    known_rendered_asset_ids: set[str] | None = None,
) -> list[str]:
    """Return explicit fixture/test markers without inferring from timestamps."""

    reasons: set[str] = set()
    analyzer = payload.get("analyzerEvidence")
    if isinstance(analyzer, dict) and str(
        analyzer.get("analyzerVersion") or ""
    ).strip().lower() in {"test", "fixture", "pytest"}:
        reasons.add("test_analyzer_version")

    schema = str(payload.get("schema") or "")
    if schema == "creator_os.operator_media_review.v1":
        reviewer = str(payload.get("reviewedBy") or "").strip().lower()
        review_id = str(payload.get("reviewId") or "").strip().lower()
        if reviewer in {"test", "pytest", "fixture", "fixture-reviewer"}:
            reasons.add("test_operator_identity")
        if review_id.startswith(("fixture-", "pytest-", "test-")):
            reasons.add("test_review_identity")
        asset_id = str(payload.get("renderedAssetId") or "").strip()
        if (
            known_rendered_asset_ids is not None
            and asset_id not in known_rendered_asset_ids
        ):
            reasons.add("operator_review_subject_missing")

    for key, value in _walk(payload):
        text = str(value or "").strip().lower()
        if key in {"registryid", "authorityid"} and text.startswith(
            "contentforge.unit_test_authority"
        ):
            reasons.add("unit_test_analyzer_authority")
        if key in {"reviewid", "reviewer"} and text.startswith(
            ("fixture-", "pytest-", "unit-test-")
        ):
            reasons.add("fixture_human_review")
        if key.endswith("path") and _looks_like_test_path(text):
            reasons.add("test_temporary_path")

    if path is not None and _looks_like_test_path(str(path).lower()):
        reasons.add("test_temporary_path")
    return sorted(reasons)


def assert_production_evidence(
    payload: dict[str, Any],
    *,
    label: str,
    path: Path | None = None,
) -> None:
    reasons = fixture_evidence_reasons(payload, path=path)
    if reasons:
        raise ValueError(f"{label}_test_or_fixture_evidence:" + ",".join(reasons))


def production_evidence_guard_enabled(root: Path) -> bool:
    """Only isolated temporary test roots may contain fixture authority."""

    return not _looks_like_test_path(str(root.expanduser().resolve()).lower())


def validate_bound_approval_evidence(approval: dict[str, Any]) -> None:
    bindings = list(approval.get("qcEvidence") or [])
    bindings.extend(
        value
        for value in (approval.get("operatorReview"), approval.get("reviewManifest"))
        if isinstance(value, dict)
    )
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            continue
        path = Path(str(binding.get("receiptPath") or binding.get("path") or ""))
        if not path.is_file() or path.is_symlink():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("production_evidence_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("production_evidence_invalid")
        assert_production_evidence(
            payload,
            label=f"creative_approval_evidence_{index}",
            path=path,
        )


def legacy_approval_inventory(
    root: Path,
    *,
    historical_schema: str,
    inventory_schema: str,
    validate_historical: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    """Preserve v1 records as non-operational historical evidence."""

    if root.exists() and root.is_symlink():
        raise ValueError("creative_approval_directory_unsafe")
    records: list[dict[str, Any]] = []
    unsafe_paths: list[str] = []
    if root.exists():
        for path in sorted(root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                unsafe_paths.append(str(path.absolute()))
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or raw.get("schema") != historical_schema:
                continue
            records.append(
                {
                    "approvalId": str(raw.get("approvalId") or ""),
                    "path": str(path.resolve()),
                    "fileSha256": _sha256_file(path),
                    "classification": (
                        "valid_historical_v1"
                        if validate_historical(raw)
                        else "invalid_historical_v1"
                    ),
                    "operationallyEligible": False,
                    "automaticallyMigratable": False,
                    "blockingReason": "creative_approval_v1_not_operational",
                    "missingV2Bindings": [
                        "campaign",
                        "renderedAsset",
                        "generationRecipe",
                        "routerDecision",
                        "executionEvidence",
                        "reviewManifest",
                        "exportProjection",
                        "operatorAttestation",
                    ],
                }
            )
    core = {
        "schema": inventory_schema,
        "records": records,
        "summary": {
            "historicalV1Records": len(records),
            "operationallyEligible": 0,
            "automaticallyMigratable": 0,
            "unsafeJsonPaths": len(unsafe_paths),
        },
        "unsafePaths": unsafe_paths,
    }
    return {**core, "inventoryFingerprint": _fingerprint(core)}


def approval_evidence_hygiene(
    conn: Any,
    *,
    root: Path,
    quarantine_root: Path | None = None,
    apply: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    """Bounded dry-run/apply inventory. Apply only moves bytes; it never deletes."""

    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    root = root.expanduser().resolve()
    if root.is_symlink():
        raise ValueError("creative approval root must not be a symlink")
    quarantine_root = (
        quarantine_root.expanduser().resolve()
        if quarantine_root is not None
        else root.parent / "quarantine" / "creative_approval_evidence"
    )
    if quarantine_root == root or root in quarantine_root.parents:
        raise ValueError("quarantine root must be outside creative approval root")

    asset_ids = {
        str(row[0]) for row in conn.execute("SELECT id FROM rendered_assets").fetchall()
    }
    candidates: list[dict[str, Any]] = []
    scanned = 0
    if root.exists():
        for path in sorted(root.rglob("*.json")):
            if scanned >= limit:
                break
            scanned += 1
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            reasons = fixture_evidence_reasons(
                payload,
                known_rendered_asset_ids=asset_ids,
            )
            if not reasons:
                continue
            candidates.append(
                {
                    "path": str(path),
                    "relativePath": str(path.relative_to(root)),
                    "sha256": _sha256_file(path),
                    "schema": str(payload.get("schema") or "unknown"),
                    "reasons": reasons,
                }
            )

    fingerprint = _fingerprint(
        {
            "root": str(root),
            "candidates": candidates,
            "limit": limit,
        }
    )
    moved: list[dict[str, Any]] = []
    receipt_path: str | None = None
    if apply and candidates:
        batch_root = quarantine_root / fingerprint[:24]
        for candidate in candidates:
            source = Path(candidate["path"])
            destination = batch_root / str(candidate["relativePath"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if _sha256_file(destination) != candidate["sha256"]:
                    raise ValueError("quarantine destination collision")
                source.unlink()
            else:
                os.replace(source, destination)
            moved.append(
                {
                    **candidate,
                    "quarantinePath": str(destination),
                }
            )
        receipt = {
            "schema": SCHEMA,
            "operation": "quarantine",
            "applied": True,
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "sourceRoot": str(root),
            "quarantineRoot": str(batch_root),
            "inventoryFingerprint": fingerprint,
            "moved": moved,
            "deleted": 0,
        }
        receipt_file = batch_root / "quarantine_receipt.json"
        atomic_write_json(receipt_file, receipt)
        receipt_path = str(receipt_file)

    return {
        "schema": SCHEMA,
        "operation": "quarantine" if apply else "inventory",
        "applied": apply,
        "root": str(root),
        "scanned": scanned,
        "scanLimit": limit,
        "scanExhausted": scanned >= limit,
        "candidateCount": len(candidates),
        "candidates": candidates,
        "movedCount": len(moved),
        "inventoryFingerprint": fingerprint,
        "receiptPath": receipt_path,
        "deleted": 0,
    }


def _walk(value: Any, key: str = ""):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk(child, str(child_key).lower())
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, key)
    else:
        yield key, value


def _looks_like_test_path(value: str) -> bool:
    return any(
        marker in value
        for marker in (
            "/pytest-of-",
            "/pytest-",
            "/private/var/folders/",
            "/tmp/pytest",
            "/fixture/",
        )
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
