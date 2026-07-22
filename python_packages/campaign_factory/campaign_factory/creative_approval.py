"""Immutable creative approval binding for the ordinary operator workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

from creator_os_core.fileops import atomic_write_json, file_lock

SCHEMA: Final = "campaign_factory.creative_approval.v1"


class CreativeApprovalError(RuntimeError):
    """The supplied approval is incomplete, unsafe, or no longer exact."""


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CreativeApprovalError(f"creative_approval_{field}_missing")
    return normalized


def _sha(value: Any, field: str) -> str:
    normalized = _required_text(value, field)
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise CreativeApprovalError(f"creative_approval_{field}_invalid")
    return normalized


def _verify_bound_file(binding: Any, field: str) -> dict[str, str]:
    if not isinstance(binding, dict):
        raise CreativeApprovalError(f"creative_approval_{field}_invalid")
    path = (
        Path(_required_text(binding.get("path"), f"{field}_path"))
        .expanduser()
        .resolve()
    )
    expected = _sha(binding.get("sha256"), f"{field}_sha256")
    if not path.is_file() or path.is_symlink() or _sha256_file(path) != expected:
        raise CreativeApprovalError(f"creative_approval_{field}_missing_or_substituted")
    return {"path": str(path), "sha256": expected}


def validate_creative_approval(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != SCHEMA:
        raise CreativeApprovalError("creative_approval_schema_mismatch")
    core = dict(payload)
    claimed = _sha(core.pop("approvalFingerprint", None), "fingerprint")
    if _fingerprint(core) != claimed:
        raise CreativeApprovalError("creative_approval_fingerprint_mismatch")
    _required_text(payload.get("approvalId"), "id")
    _required_text(payload.get("approvedBy"), "approved_by")
    _required_text(payload.get("approvedAt"), "approved_at")
    for field in ("creatorIdentity", "contentIntent", "benchmarkRecipe", "model"):
        record = payload.get(field)
        if not isinstance(record, dict):
            raise CreativeApprovalError(f"creative_approval_{field}_invalid")
        _required_text(record.get("id"), f"{field}_id")
        _sha(record.get("fingerprint"), f"{field}_fingerprint")
    _verify_bound_file(payload.get("input"), "input")
    output = _verify_bound_file(payload.get("output"), "output")
    qc = payload.get("qcEvidence")
    if not isinstance(qc, list) or not qc:
        raise CreativeApprovalError("creative_approval_qc_evidence_missing")
    identities: set[str] = set()
    for item in qc:
        if not isinstance(item, dict):
            raise CreativeApprovalError("creative_approval_qc_evidence_invalid")
        check_id = _required_text(item.get("checkId"), "qc_check_id")
        if check_id in identities:
            raise CreativeApprovalError("creative_approval_duplicate_qc_identity")
        identities.add(check_id)
        if item.get("passed") is not True:
            raise CreativeApprovalError(f"creative_approval_qc_blocked:{check_id}")
        if _sha(item.get("subjectSha256"), "qc_subject_sha256") != output["sha256"]:
            raise CreativeApprovalError(
                f"creative_approval_qc_subject_mismatch:{check_id}"
            )
        receipt = (
            Path(_required_text(item.get("receiptPath"), "qc_receipt_path"))
            .expanduser()
            .resolve()
        )
        if (
            not receipt.is_file()
            or receipt.is_symlink()
            or _sha256_file(receipt)
            != _sha(item.get("receiptSha256"), "qc_receipt_sha256")
        ):
            raise CreativeApprovalError(
                f"creative_approval_qc_receipt_substituted:{check_id}"
            )
    export = payload.get("exportPayload")
    if not isinstance(export, dict):
        raise CreativeApprovalError("creative_approval_export_payload_invalid")
    _required_text(export.get("schema"), "export_schema")
    _sha(export.get("fingerprint"), "export_fingerprint")
    semantics = payload.get("contentSemantics")
    if not isinstance(semantics, dict):
        raise CreativeApprovalError("creative_approval_content_semantics_missing")
    required_semantics = {
        "burnedOverlayText",
        "instagramPostCaption",
        "generatedAudio",
        "sourceAudio",
        "nativeInstagramAudio",
    }
    if set(semantics) != required_semantics:
        raise CreativeApprovalError("creative_approval_content_semantics_invalid")
    return payload


class CreativeApprovalStore:
    """Content-addressed approvals beside Campaign evidence, without a new database."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._lock = self.root / "creative_approvals"

    def record(self, payload: dict[str, Any]) -> Path:
        approval = validate_creative_approval(payload)
        path = self.root / f"{approval['approvalId']}.json"
        with file_lock(self._lock):
            if path.exists():
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or json.loads(path.read_text(encoding="utf-8")) != approval
                ):
                    raise CreativeApprovalError("creative_approval_identity_collision")
                return path
            atomic_write_json(path, approval)
            validate_creative_approval(json.loads(path.read_text(encoding="utf-8")))
        return path


def load_creative_approval(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise CreativeApprovalError("creative_approval_missing_or_unsafe")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CreativeApprovalError("creative_approval_invalid_json") from exc
    if not isinstance(payload, dict):
        raise CreativeApprovalError("creative_approval_invalid_json")
    return validate_creative_approval(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        approval = load_creative_approval(args.approval)
        path = CreativeApprovalStore(args.root).record(approval)
    except (CreativeApprovalError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "schema": "campaign_factory.creative_approval_recorded.v1",
                "approvalId": approval["approvalId"],
                "approvalFingerprint": approval["approvalFingerprint"],
                "path": str(path),
                "productionWrites": 0,
                "providerCalls": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
