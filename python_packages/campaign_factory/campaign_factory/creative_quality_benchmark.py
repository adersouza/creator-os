"""Read-only validation for the small future creative-quality cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from creator_os_core.sqlite import connect_sqlite

from .config import get_settings

SCHEMA = "campaign_factory.creative_quality_benchmark.v1"
REVIEW_FIELDS = (
    "identity",
    "anatomy",
    "motion",
    "naturalness",
    "phoneNativeAppearance",
    "attractiveness",
    "wouldPost",
    "rejectionReasons",
    "notes",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("benchmark manifest must be an object")
    return value


def _valid_sha(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def validate_benchmark_manifest(
    conn: Any,
    manifest: dict[str, Any],
    *,
    future_max_credits: float | None,
) -> dict[str, Any]:
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"benchmark schema must be {SCHEMA}")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 10 <= len(cases) <= 15:
        raise ValueError("benchmark requires 10 to 15 cases")
    before = conn.total_changes
    normalized: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(cases):
        if not isinstance(raw, dict):
            raise ValueError(f"benchmark case {index + 1} must be an object")
        case_id = str(raw.get("benchmarkCaseId") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError("benchmark case IDs must be non-empty and unique")
        seen.add(case_id)
        source_id = str(raw.get("sourceAssetId") or "")
        source_sha = str(raw.get("sourceSha256") or "").lower()
        row = conn.execute(
            "SELECT id, content_hash, status FROM source_assets WHERE id = ?",
            (source_id,),
        ).fetchone()
        case_blockers: list[str] = []
        if row is None:
            case_blockers.append("source_missing")
        else:
            if str(row["content_hash"]).lower() != source_sha or not _valid_sha(
                source_sha
            ):
                case_blockers.append("source_sha_mismatch")
            if str(row["status"] or "").lower() != "approved":
                case_blockers.append("source_not_approved")
        if not _valid_sha(raw.get("promptCardFingerprint")):
            case_blockers.append("prompt_card_fingerprint_invalid")
        incumbent = str(raw.get("incumbentRecipe") or "")
        challenger = str(raw.get("challengerRecipe") or "")
        if (
            incumbent not in {"higgsfield_kling3_i2v", "higgsfield_seedance2_i2v"}
            or challenger not in {"higgsfield_kling3_i2v", "higgsfield_seedance2_i2v"}
            or incumbent == challenger
        ):
            case_blockers.append("recipe_pair_invalid")
        reviews = raw.get("outputs") or []
        if not isinstance(reviews, list):
            raise ValueError("benchmark outputs must be a list")
        for output in reviews:
            if not isinstance(output, dict):
                case_blockers.append("output_review_invalid")
                continue
            scores_present = any(
                output.get(field) not in (None, "") for field in REVIEW_FIELDS
            )
            if scores_present and not _valid_sha(output.get("finalSha256")):
                case_blockers.append("human_scores_require_exact_output_sha")
        if case_blockers:
            blockers.append({"benchmarkCaseId": case_id, "reasons": case_blockers})
        normalized.append(
            {
                "benchmarkCaseId": case_id,
                "creator": raw.get("creator"),
                "sourceAssetId": source_id,
                "sourceSha256": source_sha,
                "intent": raw.get("intent"),
                "sceneClass": raw.get("sceneClass"),
                "expectedDurationSeconds": raw.get("expectedDurationSeconds"),
                "promptCardFingerprint": raw.get("promptCardFingerprint"),
                "incumbentRecipe": incumbent,
                "challengerRecipe": challenger,
                "comparableInputRequirements": raw.get("comparableInputRequirements"),
                "outputs": reviews,
            }
        )
    manifest_core = {"schema": SCHEMA, "cases": normalized}
    fingerprint = hashlib.sha256(
        json.dumps(manifest_core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        **manifest_core,
        "manifestFingerprint": fingerprint,
        "dryRun": True,
        "readOnly": True,
        "projectedPaidJobs": len(cases) * 2,
        "futureSpendAuthorization": {
            "requiredBeforeExecution": True,
            "maxCredits": future_max_credits,
            "present": future_max_credits is not None,
        },
        "blockers": blockers,
        "providerCalls": 0,
        "databaseWrites": conn.total_changes - before,
        "productionDefaultsChanged": False,
        "operatorVisualReviewRequired": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--future-max-credits", type=float)
    parser.add_argument("--dry-run", action="store_true", required=True)
    args = parser.parse_args(argv)
    conn = connect_sqlite(args.db or get_settings().db_path, readonly=True)
    try:
        result = validate_benchmark_manifest(
            conn,
            _load(args.manifest.expanduser().resolve()),
            future_max_credits=args.future_max_credits,
        )
    finally:
        conn.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
