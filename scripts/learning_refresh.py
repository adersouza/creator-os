#!/usr/bin/env python3
"""Refresh and review measured Creator OS learning without scheduling it."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from campaign_factory.config import get_settings
from campaign_factory.core import CampaignFactory
from campaign_factory.learning_consumption import (
    LEARNING_RECOMMENDATION_SCOPE,
    build_audio_recommendations,
    build_measured_recommendations,
    persist_measured_recommendations,
    recommendation_state,
    validate_pack_fingerprint,
)
from campaign_factory.persistence import json_load
from creator_os_core.fileops import atomic_write_text
from creator_os_core.runtime_paths import resolve_runtime_paths
from reference_factory.config import DEFAULT_DB_PATH as REFERENCE_DB_PATH
from reference_factory.db import connect as connect_reference
from reference_factory.knowledge_pack import export_knowledge_pack
from reference_factory.preference_outcomes import refresh_preference_outcome_weights


def _state_root() -> Path:
    return Path(
        os.environ.get(
            "CREATOR_OS_LEARNING_STATE",
            Path.home() / ".creator-os/state/learning",
        )
    ).expanduser()


def _load_or_build_pack(*, apply: bool) -> tuple[dict[str, Any], Path | None, bool]:
    if apply:
        conn = connect_reference(REFERENCE_DB_PATH)
    else:
        conn = sqlite3.connect(f"file:{REFERENCE_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    try:
        preview = export_knowledge_pack(conn, output_path=None)
    finally:
        conn.close()
    validate_pack_fingerprint(preview)
    if not apply:
        return preview, None, False
    path = _state_root() / "knowledge_packs" / f"{preview['packId']}.json"
    if path.exists():
        persisted = json_load(path.read_text(encoding="utf-8"), {})
        validate_pack_fingerprint(persisted)
        if persisted.get("sourceFingerprint") != preview.get("sourceFingerprint"):
            raise ValueError("persisted knowledge pack ID collision")
        return persisted, path, False
    atomic_write_text(
        path,
        json.dumps(preview, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return preview, path, True


def _preference_profile_path() -> Path:
    configured = os.environ.get("CREATOR_OS_OPERATOR_PREFERENCE_PROFILE")
    if configured:
        return Path(configured).expanduser()
    return (
        resolve_runtime_paths().reference_data_root
        / "learning"
        / "operator_preference_profile.json"
    )


def _refresh_preference_weights(*, apply: bool) -> dict[str, Any]:
    """Push measured post outcomes into the operator preference profile.

    This is the production caller that closes the preference loop: published
    outcomes become `outcomeWeights`, which Campaign Factory's reference
    selection reads on the next creation.
    """

    path = _preference_profile_path()
    if not path.exists():
        return {"status": "no_profile", "path": str(path)}
    if not apply:
        return {"status": "would_refresh", "path": str(path)}
    conn = sqlite3.connect(f"file:{REFERENCE_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        summary = refresh_preference_outcome_weights(conn, path)
    finally:
        conn.close()
    return {"status": "refreshed", "path": str(path), **summary}


def refresh(*, apply: bool) -> dict[str, Any]:
    pack, pack_path, pack_written = _load_or_build_pack(apply=apply)
    recommendations = build_measured_recommendations(pack)
    if not apply:
        settings = get_settings()
        campaign_conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
        campaign_conn.row_factory = sqlite3.Row
        try:
            recommendations.extend(
                build_audio_recommendations(campaign_conn, pack=pack)
            )
        finally:
            campaign_conn.close()
    result: dict[str, Any] = {
        "schema": "creator_os.learning_refresh.v1",
        "apply": apply,
        "operatorPreferenceWeights": _refresh_preference_weights(apply=apply),
        "knowledgePack": {
            "id": pack["packId"],
            "sourceFingerprint": pack["sourceFingerprint"],
            "path": str(pack_path) if pack_path else None,
            "wouldPersist": not apply,
            "persisted": apply,
            "newArtifact": pack_written,
        },
        "recommendations": recommendations,
        "databaseWrites": 0,
        "persistentArtifactsWritten": 0,
        "idempotent": False,
    }
    if not apply:
        return result
    if pack_path is None:
        raise AssertionError("apply requires a persisted pack path")
    factory = CampaignFactory(get_settings())
    try:
        recommendations.extend(build_audio_recommendations(factory.conn, pack=pack))
        expected_fingerprints = {
            item["recommendationFingerprint"] for item in recommendations
        }
        existing_pack = factory.conn.execute(
            "SELECT 1 FROM reference_knowledge_packs WHERE id = ?",
            (pack["packId"],),
        ).fetchone()
        existing_fingerprints = {
            str(json_load(row["evidence_json"], {}).get("recommendationFingerprint"))
            for row in factory.conn.execute(
                """
                SELECT ri.evidence_json FROM recommendation_items ri
                JOIN recommendation_runs rr ON rr.id = ri.run_id
                WHERE rr.scope = ?
                """,
                (LEARNING_RECOMMENDATION_SCOPE,),
            ).fetchall()
        }
        already_imported = existing_pack is not None and expected_fingerprints.issubset(
            existing_fingerprints
        )
        if already_imported:
            result["campaignImport"] = {"status": "unchanged"}
            result["recommendationPersistence"] = {
                "runsInserted": 0,
                "itemsInserted": 0,
                "itemsUnchanged": len(recommendations),
            }
            result["idempotent"] = True
        else:
            before = factory.conn.total_changes
            imported = factory.domains.reference.import_reference_bank(pack_path)
            persistence = persist_measured_recommendations(
                factory.conn, recommendations, pack=pack
            )
            result["campaignImport"] = imported
            result["recommendationPersistence"] = persistence
            result["databaseWrites"] = factory.conn.total_changes - before
    finally:
        factory.close()
    receipt_path = (
        _state_root()
        / "refresh_receipts"
        / (f"learning_refresh_{pack['sourceFingerprint'][:16]}.json")
    )
    receipt = {
        "schema": "creator_os.learning_refresh_receipt.v1",
        "knowledgePackId": pack["packId"],
        "sourceFingerprint": pack["sourceFingerprint"],
        "recommendationFingerprints": sorted(
            item["recommendationFingerprint"] for item in recommendations
        ),
        "knowledgePackPath": str(pack_path),
    }
    receipt_written = False
    if not receipt_path.exists():
        atomic_write_text(
            receipt_path,
            json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt_written = True
    result["refreshReceipt"] = str(receipt_path)
    result["persistentArtifactsWritten"] = int(pack_written) + int(receipt_written)
    result["idempotent"] = result["idempotent"] or (
        not pack_written and not receipt_written and result["databaseWrites"] == 0
    )
    return result


def review(
    *,
    action: str,
    recommendation_id: str | None,
    operator: str | None,
    reason: str | None,
) -> dict[str, Any]:
    factory = CampaignFactory(get_settings())
    try:
        current_pack = factory.conn.execute(
            """
            SELECT id FROM reference_knowledge_packs
            ORDER BY generated_at DESC, imported_at DESC, id DESC LIMIT 1
            """
        ).fetchone()
        current_pack_id = str(current_pack["id"]) if current_pack else None
        if action == "list":
            rows = factory.conn.execute(
                """
                SELECT ri.* FROM recommendation_items ri
                JOIN recommendation_runs rr ON rr.id = ri.run_id
                WHERE rr.scope = ?
                ORDER BY ri.created_at DESC, ri.id
                """,
                (LEARNING_RECOMMENDATION_SCOPE,),
            ).fetchall()
            return {
                "schema": "creator_os.learning_review.v1",
                "items": [
                    {
                        "id": row["id"],
                        "storedStatus": row["status"],
                        "state": recommendation_state(
                            str(row["status"]),
                            json_load(row["evidence_json"], {}),
                            current_pack_id=current_pack_id,
                        ),
                        "evidence": json_load(row["evidence_json"], {}),
                    }
                    for row in rows
                ],
            }
        if not recommendation_id:
            raise ValueError("--id is required for this action")
        row = factory.conn.execute(
            "SELECT * FROM recommendation_items WHERE id = ?",
            (recommendation_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"recommendation not found: {recommendation_id}")
        evidence = json_load(row["evidence_json"], {})
        state = recommendation_state(
            str(row["status"]), evidence, current_pack_id=current_pack_id
        )
        if action == "approve":
            if not evidence.get("eligibleForOperatorApproval"):
                raise ValueError("recommendation is not eligible for operator approval")
            if state not in {"ADVISORY", "SUPERVISED_ACTIVE"}:
                raise ValueError(f"recommendation cannot be approved from {state}")
            if state == "SUPERVISED_ACTIVE":
                return {"id": recommendation_id, "state": state, "unchanged": True}
            changed = factory.domains.recommendations.accept_recommendation_item(
                recommendation_id,
                operator=operator,
                notes=reason or "explicit supervised learning approval",
            )
        else:
            decision_reason = reason or (
                "pin_existing_behavior" if action == "pin" else action
            )
            changed = factory.domains.recommendations.reject_recommendation_item(
                recommendation_id,
                reason=decision_reason,
                operator=operator,
                notes=decision_reason,
            )
        updated = factory.conn.execute(
            "SELECT * FROM recommendation_items WHERE id = ?",
            (recommendation_id,),
        ).fetchone()
        return {
            "schema": "creator_os.learning_review.v1",
            "action": action,
            "item": changed,
            "state": recommendation_state(
                str(updated["status"]),
                json_load(updated["evidence_json"], {}),
                current_pack_id=current_pack_id,
            ),
        }
    finally:
        factory.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    refresh_cmd = sub.add_parser("refresh")
    mode = refresh_cmd.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    review_cmd = sub.add_parser("review")
    review_cmd.add_argument(
        "action", choices=["list", "approve", "reject", "pin", "revoke"]
    )
    review_cmd.add_argument("--id")
    review_cmd.add_argument("--operator")
    review_cmd.add_argument("--reason")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "refresh":
        payload = refresh(apply=args.apply)
    else:
        payload = review(
            action=args.action,
            recommendation_id=args.id,
            operator=args.operator,
            reason=args.reason,
        )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
