#!/usr/bin/env python3
"""Fail-closed guard for Reel Factory review batches."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audio_intent import read_audio_intent


FOCAL_SAFE = {"focal-safe", "focal_safe_v1"}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contentforge_payload(path: Path) -> dict[str, Any] | None:
    return _load_json(path)


def _contentforge_count(payload: dict[str, Any]) -> int:
    return int(payload.get("variants") or payload.get("groups") or 0)


def _contentforge_passed(payload: dict[str, Any]) -> bool:
    verdicts = payload.get("verdictCounts") or {}
    if int(verdicts.get("fail") or 0) > 0:
        return False
    if payload.get("blockingCodes"):
        return False
    groups = _contentforge_count(payload)
    http_ok = int(payload.get("httpOk") or 0)
    if groups <= 0 or http_ok < groups:
        return False
    return int(verdicts.get("pass") or 0) > 0 or groups > 0


def _contentforge_profile(payload: dict[str, Any]) -> str:
    return str(payload.get("profile") or payload.get("auditProfile") or "")


def _lineage_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".generated_asset_lineage.json")


def _readiness_path(output_dir: Path) -> Path:
    return output_dir / "_readiness.json"


def _contentforge_path(manifest_path: Path, manifest: dict[str, Any]) -> Path | None:
    value = manifest.get("contentForgeAuditPath")
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else manifest_path.parent / path


def _hash_paths(manifest_path: Path, manifest: dict[str, Any], rows: list[Any]) -> dict[str, str]:
    output_dir = Path(str(manifest.get("outputDir") or manifest_path.parent))
    paths: list[Path] = [manifest_path, _readiness_path(output_dir)]
    contentforge_path = _contentforge_path(manifest_path, manifest)
    if contentforge_path:
        paths.append(contentforge_path)
    for row in rows:
        if not isinstance(row, dict):
            continue
        output = Path(str(row.get("output") or ""))
        overlay = Path(str(row.get("overlayPng") or ""))
        paths.extend([
            output,
            overlay,
            output.with_suffix(output.suffix + ".audio_intent.json"),
            _lineage_path(output),
        ])
    return {str(path.resolve()): _sha256(path.resolve()) for path in dict.fromkeys(paths) if path.exists()}


def validate_review_batch(manifest_path: str | Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_json(manifest_path)
    blocking: list[str] = []
    if not manifest:
        return {"schema": "reel_factory.review_batch_guard.v1", "status": "blocked", "blockingReasons": ["missing_or_invalid_manifest"]}

    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    output_dir = Path(str(manifest.get("outputDir") or manifest_path.parent))
    if not rows:
        blocking.append("manifest_has_no_rows")
    if manifest.get("backgroundPlate") is not False:
        blocking.append("background_plate_enabled")
    if str(manifest.get("font") or "").lower().find("instagram sans condensed") < 0:
        blocking.append("font_not_instagram_sans_condensed")
    if manifest.get("renderer") != "reel_factory.caption_render" or manifest.get("style") != "ig":
        blocking.append("not_reel_factory_instagram_renderer")
    if str((manifest.get("captionSelection") or {}).get("source") or "").lower().find("caption bank") < 0:
        blocking.append("not_from_caption_bank")
    if str(manifest.get("captionPlacementPolicy") or "") not in FOCAL_SAFE:
        blocking.append("caption_placement_not_focal_safe")

    contentforge_path = Path(str(manifest.get("contentForgeAuditPath") or ""))
    if not contentforge_path.is_absolute():
        contentforge_path = manifest_path.parent / contentforge_path
    if not manifest.get("contentForgeAuditPath") or not contentforge_path.exists():
        blocking.append("missing_contentforge_audit")
    else:
        contentforge = _contentforge_payload(contentforge_path)
        if not contentforge:
            blocking.append("contentforge_audit_not_passing")
        elif _contentforge_profile(contentforge) != "campaign_factory_v1":
            blocking.append("contentforge_audit_not_campaign_profile")
        elif _contentforge_count(contentforge) != len(rows):
            blocking.append("contentforge_audit_count_mismatch")
        elif int(contentforge.get("httpOk") or 0) != len(rows):
            blocking.append("contentforge_audit_count_mismatch")
        elif int((contentforge.get("verdictCounts") or {}).get("pass") or 0) != len(rows):
            blocking.append("contentforge_audit_count_mismatch")
        elif not _contentforge_passed(contentforge):
            blocking.append("contentforge_audit_not_passing")

    readiness = _load_json(_readiness_path(output_dir))
    summary = (readiness or {}).get("summary") or {}
    if not readiness:
        blocking.append("missing_readiness_report")
    elif summary.get("total") != len(rows) or summary.get("ready") != len(rows) or summary.get("warn") or summary.get("not_ready"):
        blocking.append("readiness_not_all_ready")

    for row in rows:
        output = Path(str(row.get("output") or ""))
        overlay = Path(str(row.get("overlayPng") or ""))
        if not output.exists():
            blocking.append("missing_output")
        if not overlay.exists():
            blocking.append("missing_overlay")
        if not row.get("captionText") or not row.get("captionHash") or not row.get("sourceBanks"):
            blocking.append("caption_bank_lineage_missing")
        if not row.get("selectedBand") or str(row.get("captionPlacementPolicy") or "") not in FOCAL_SAFE:
            blocking.append("caption_placement_not_focal_safe")
        if not read_audio_intent(output):
            blocking.append("missing_audio_intent")
        lineage = _load_json(_lineage_path(output))
        if not lineage:
            blocking.append("missing_generated_asset_lineage")
        elif str(lineage.get("captionPlacementPolicy") or row.get("captionPlacementPolicy") or "") not in FOCAL_SAFE:
            blocking.append("caption_placement_not_focal_safe")

    reasons = sorted(set(blocking))
    return {
        "schema": "reel_factory.review_batch_guard.v1",
        "manifestPath": str(manifest_path),
        "status": "ready" if not reasons else "blocked",
        "blockingReasons": reasons,
        "count": len(rows),
    }


def promote_review_batch(manifest_path: str | Path, *, package_path: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    guard = validate_review_batch(manifest_path)
    if guard["status"] != "ready":
        return guard
    manifest = _load_json(manifest_path) or {}
    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    output_path = Path(package_path).resolve() if package_path else manifest_path.with_suffix(".review_package.json")
    package = {
        "schema": "reel_factory.review_batch_package.v1",
        "manifestPath": str(manifest_path),
        "outputDir": manifest.get("outputDir"),
        "contentForgeAuditPath": manifest.get("contentForgeAuditPath"),
        "count": len(rows),
        "guard": guard,
        "fileSha256": _hash_paths(manifest_path, manifest, rows),
        "rows": rows,
    }
    output_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    return {**guard, "packagePath": str(output_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--write-package", nargs="?", const="", help="write a review package only if the guard passes")
    args = parser.parse_args()
    if args.write_package is not None:
        result = promote_review_batch(args.manifest, package_path=args.write_package or None)
    else:
        result = validate_review_batch(args.manifest)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
