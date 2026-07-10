#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from campaign_factory.db import connect as connect_campaign_db
from campaign_factory.db import init_db as init_campaign_db
from campaign_factory.learning_readiness import closed_loop_learning_status
from campaign_factory.learning_score import (
    DEFAULT_REWARD_BASELINE,
    SCORING_VERSION,
    account_reward_baseline_provenance,
    account_reward_baselines,
    learning_eligible,
    learning_ineligibility_reasons,
    learning_loop_cutover_iso,
    snapshot_normalized_reward,
)
from campaign_factory.persistence import utc_now
from reel_factory.metrics_store import (
    connect_metrics_db,
    ensure_metrics_schema,
    retract_bridge_outcome,
    upsert_bridge_outcome,
)
from reference_factory.db import connect as connect_reference_db
from reference_factory.outcomes import (
    retract_prompt_post_outcome,
    upsert_prompt_post_outcome,
)
from reference_factory.patterns import refresh_measured_outcomes_for_references

DESTINATIONS = ("campaign", "reel", "reference")
DEFAULT_MAX_ATTEMPTS = 5


def fanout_learning_snapshots(
    *,
    campaign_factory_db: Path,
    reel_factory_root: Path,
    reference_factory_db: Path,
    campaign: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any]:
    campaign_conn = connect_campaign_db(Path(campaign_factory_db))
    init_campaign_db(campaign_conn)
    reel_conn = connect_metrics_db(Path(reel_factory_root) / "manifest.sqlite")
    ensure_metrics_schema(reel_conn)
    reference_conn = connect_reference_db(Path(reference_factory_db))
    now = utc_now()
    try:
        snapshots = _load_snapshots(campaign_conn, campaign)
        public_snapshots = [_public_snapshot(row) for row in snapshots]
        eligible_by_key = {
            _snapshot_key(row): learning_eligible(public)
            for row, public in zip(snapshots, public_snapshots, strict=True)
        }
        eligible_public = [
            public
            for row, public in zip(snapshots, public_snapshots, strict=True)
            if eligible_by_key[_snapshot_key(row)]
        ]
        baselines = account_reward_baselines(eligible_public)
        provenance_by_account = account_reward_baseline_provenance(
            eligible_public, computed_at=now
        )
        report = _empty_report(snapshots)
        report["cutover"] = learning_loop_cutover_iso()
        report["ineligibleReasons"] = dict(
            Counter(
                reason
                for row in snapshots
                for reason in learning_ineligibility_reasons(row)
                if not eligible_by_key[_snapshot_key(row)]
            )
        )
        report["fallbackRows"] = sum(
            1 for row in snapshots if row.get("history_source") == "post_row_fallback"
        )

        ledgers = _reconcile_ledgers(
            campaign_conn,
            snapshots,
            eligible_by_key=eligible_by_key,
            report=report,
            now=now,
        )
        latest_eligible = _latest_eligible_by_post(snapshots, eligible_by_key)

        changed_references: set[str] = set()
        restore_keys: set[tuple[str, str]] = set()
        for row in snapshots:
            key = _snapshot_key(row)
            if eligible_by_key[key]:
                continue
            for destination in DESTINATIONS:
                ledger = ledgers.get((*key, destination))
                if not ledger or ledger["status"] not in {"done", "superseded"}:
                    continue
                identity = _json_object(ledger.get("destination_record_id"))
                try:
                    if destination == "reel" and identity:
                        retract_bridge_outcome(
                            reel_conn,
                            outcome_id=str(identity.get("outcomeId") or ""),
                            filename=str(identity.get("filename") or ""),
                        )
                    elif destination == "reference" and identity:
                        prompt_id = str(identity.get("promptId") or "")
                        prompt = reference_conn.execute(
                            "SELECT reference_id FROM generated_video_prompts WHERE id = ?",
                            (prompt_id,),
                        ).fetchone()
                        retract_prompt_post_outcome(
                            reference_conn,
                            prompt_id=prompt_id,
                            post_id=str(identity.get("postId") or row["post_id"]),
                        )
                        if prompt:
                            changed_references.add(str(prompt["reference_id"]))
                    _set_ledger_status(
                        campaign_conn,
                        key,
                        destination,
                        status="retracted",
                        now=now,
                        last_error=None,
                    )
                    report["fanout"][destination]["retracted"] += 1
                    if (
                        destination in {"reel", "reference"}
                        and row["post_id"] in latest_eligible
                    ):
                        restore_keys.add((str(row["post_id"]), destination))
                except Exception as exc:  # destination errors remain retryable
                    _record_failure(
                        campaign_conn,
                        key,
                        destination,
                        str(exc),
                        max_attempts=max_attempts,
                        report=report,
                        now=now,
                    )

        for post_id, destination in restore_keys:
            replacement = latest_eligible.get(post_id)
            if replacement:
                _set_ledger_status(
                    campaign_conn,
                    _snapshot_key(replacement),
                    destination,
                    status="pending",
                    now=now,
                    last_error=None,
                )

        for row, public in zip(snapshots, public_snapshots, strict=True):
            key = _snapshot_key(row)
            if not eligible_by_key[key]:
                continue
            for destination in DESTINATIONS:
                ledger = _ledger_row(campaign_conn, key, destination)
                if not ledger:
                    continue
                if (
                    destination in {"reel", "reference"}
                    and latest_eligible.get(str(row["post_id"])) is not row
                ):
                    if ledger["status"] in {"pending", "done"}:
                        _set_ledger_status(
                            campaign_conn,
                            key,
                            destination,
                            status="superseded",
                            now=now,
                            last_error=None,
                        )
                        report["fanout"][destination]["superseded"] += 1
                    continue
                if ledger["status"] in {"done", "superseded", "failed_capped"}:
                    continue
                try:
                    if destination == "campaign":
                        result = {
                            "status": "written",
                            "snapshotId": row["id"],
                        }
                        baseline_provenance = None
                    elif destination == "reel":
                        previous = _previous_identity(
                            campaign_conn, row["post_id"], destination, key
                        )
                        result = upsert_bridge_outcome(
                            Path(reel_factory_root),
                            reel_conn,
                            row,
                            previous_identity=previous,
                        )
                        baseline_provenance = None
                    else:
                        previous = _previous_identity(
                            campaign_conn, row["post_id"], destination, key
                        )
                        result, baseline_provenance = _write_reference(
                            reference_conn,
                            row,
                            public,
                            baselines=baselines,
                            provenance_by_account=provenance_by_account,
                            previous_identity=previous,
                        )
                        for reference_id in result.get("changedReferenceIds") or []:
                            changed_references.add(str(reference_id))
                    status = str(result.get("status") or "skipped")
                    if status == "superseded":
                        _set_ledger_status(
                            campaign_conn,
                            key,
                            destination,
                            status="superseded",
                            now=now,
                            last_error=None,
                        )
                        report["fanout"][destination]["superseded"] += 1
                        continue
                    identity = _destination_identity(destination, result)
                    if status not in {"written", "updated"} or not identity:
                        _record_failure(
                            campaign_conn,
                            key,
                            destination,
                            str(result.get("reason") or "destination_soft_skip"),
                            max_attempts=max_attempts,
                            report=report,
                            now=now,
                        )
                        continue
                    _mark_done(
                        campaign_conn,
                        key,
                        destination,
                        identity=identity,
                        baseline_provenance=baseline_provenance,
                        now=now,
                    )
                    if destination in {"reel", "reference"}:
                        _supersede_other_snapshots(
                            campaign_conn,
                            post_id=str(row["post_id"]),
                            destination=destination,
                            keep_snapshot_at=str(row["snapshot_at"]),
                            now=now,
                        )
                    report["fanout"][destination]["done"] += 1
                except Exception as exc:
                    _record_failure(
                        campaign_conn,
                        key,
                        destination,
                        str(exc),
                        max_attempts=max_attempts,
                        report=report,
                        now=now,
                    )

        if changed_references:
            report["referencePatternRefresh"] = (
                refresh_measured_outcomes_for_references(
                    reference_conn, changed_references
                )
            )
        else:
            report["referencePatternRefresh"] = {
                "references": 0,
                "patternsChanged": 0,
            }
        report["readiness"] = closed_loop_learning_status(
            campaign_conn, campaign_slug=campaign
        )
        report["eligibleSnapshots"] = sum(eligible_by_key.values())
        report["ineligibleSnapshots"] = len(snapshots) - report["eligibleSnapshots"]
        report["ledgerStates"] = {
            destination: dict(
                Counter(
                    str(ledger["status"])
                    for row in snapshots
                    if (
                        ledger := _ledger_row(
                            campaign_conn, _snapshot_key(row), destination
                        )
                    )
                )
            )
            for destination in DESTINATIONS
        }
        _write_sync_state(campaign_conn, report, now=now)
        campaign_conn.commit()
        return report
    finally:
        reference_conn.close()
        reel_conn.close()
        campaign_conn.close()


def _load_snapshots(
    conn: sqlite3.Connection, campaign: str | None
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if campaign:
        clauses.append("(c.slug = ? OR c.id = ?)")
        params.extend([campaign, campaign])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT p.*, c.slug AS campaign_slug,
                   ra.output_path AS rendered_output_path,
                   ra.filename AS rendered_filename,
                   ra.caption AS rendered_caption,
                   ra.recipe AS rendered_recipe
            FROM performance_snapshots p
            JOIN campaigns c ON c.id = p.campaign_id
            LEFT JOIN rendered_assets ra ON ra.id = p.rendered_asset_id
            {where}
            ORDER BY p.post_id, julianday(p.snapshot_at), p.snapshot_at
            """,
            params,
        ).fetchall()
    ]


def _public_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "postId": row.get("post_id"),
        "accountId": row.get("account_id"),
        "instagramAccountId": row.get("instagram_account_id"),
        "publishedAt": row.get("published_at"),
        "snapshotAt": row.get("snapshot_at"),
        "metricsEligible": row.get("metrics_eligible"),
        "historySource": row.get("history_source"),
        "lineageV2Valid": row.get("lineage_v2_valid"),
        "metrics": {
            "views": row.get("views"),
            "likes": row.get("likes"),
            "comments": row.get("comments"),
            "shares": row.get("shares"),
            "saves": row.get("saves"),
            "impressions": row.get("impressions"),
            "reach": row.get("reach"),
            "watchTimeSeconds": row.get("watch_time_seconds"),
        },
    }


def _reconcile_ledgers(
    conn: sqlite3.Connection,
    snapshots: list[dict[str, Any]],
    *,
    eligible_by_key: dict[tuple[str, str], bool],
    report: dict[str, Any],
    now: str,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    for row in snapshots:
        key = _snapshot_key(row)
        eligible = eligible_by_key[key]
        for destination in DESTINATIONS:
            source_hash = _source_hash(row, destination, eligible=eligible)
            existing = _ledger_row(conn, key, destination)
            if not existing:
                if not eligible:
                    continue
                conn.execute(
                    """
                    INSERT INTO learning_fanout_ledger (
                      post_id, snapshot_at, destination, snapshot_id, status,
                      attempt_count, source_hash, scoring_version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
                    """,
                    (
                        *key,
                        destination,
                        row.get("id"),
                        source_hash,
                        SCORING_VERSION,
                        now,
                        now,
                    ),
                )
            elif existing["source_hash"] != source_hash:
                next_status = "pending" if eligible else existing["status"]
                next_attempt_count = 0 if eligible else existing["attempt_count"]
                conn.execute(
                    """
                    UPDATE learning_fanout_ledger
                    SET status = ?, attempt_count = ?, source_hash = ?,
                        snapshot_id = ?, scoring_version = ?, last_error = NULL,
                        updated_at = ?
                    WHERE post_id = ? AND snapshot_at = ? AND destination = ?
                    """,
                    (
                        next_status,
                        next_attempt_count,
                        source_hash,
                        row.get("id"),
                        SCORING_VERSION,
                        now,
                        *key,
                        destination,
                    ),
                )
                if eligible:
                    report["fanout"][destination]["reopenedByHash"] += 1
    conn.commit()
    return {
        (str(row["post_id"]), str(row["snapshot_at"]), str(row["destination"])): dict(
            row
        )
        for row in conn.execute("SELECT * FROM learning_fanout_ledger").fetchall()
    }


def _source_hash(row: dict[str, Any], destination: str, *, eligible: bool) -> str:
    meta = _campaign_meta(row)
    lineage = meta.get("generated_asset_lineage") if isinstance(meta, dict) else {}
    source = lineage.get("source") if isinstance(lineage, dict) else {}
    normalized = {
        "destination": destination,
        "scoringVersion": SCORING_VERSION if destination == "reference" else None,
        "postId": row.get("post_id"),
        "snapshotAt": row.get("snapshot_at"),
        "publishedAt": row.get("published_at"),
        "metrics": {
            key: row.get(key)
            for key in (
                "views",
                "likes",
                "comments",
                "shares",
                "saves",
                "impressions",
                "reach",
                "watch_time_seconds",
            )
        },
        "accountId": row.get("account_id"),
        "instagramAccountId": row.get("instagram_account_id"),
        "campaignId": meta.get("campaign_id") or row.get("campaign_slug"),
        "recipeId": meta.get("recipe") or row.get("recipe"),
        "captionHash": meta.get("caption_hash") or row.get("caption_hash"),
        "variantId": (lineage or {}).get("variantId")
        if isinstance(lineage, dict)
        else None,
        "renderedAssetId": row.get("rendered_asset_id"),
        "renderedOutputPath": row.get("rendered_output_path"),
        "renderedFilename": row.get("rendered_filename"),
        "promptId": source.get("promptId") if isinstance(source, dict) else None,
        "referenceId": source.get("referenceId") if isinstance(source, dict) else None,
        "audioId": row.get("audio_id"),
        "historySource": row.get("history_source"),
        "metricsEligible": row.get("metrics_eligible"),
        "lineageV2Valid": row.get("lineage_v2_valid"),
        "eligible": eligible,
    }
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_reference(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    public: dict[str, Any],
    *,
    baselines: dict[str, float],
    provenance_by_account: dict[str, dict[str, Any]],
    previous_identity: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    meta = _campaign_meta(row)
    lineage = meta.get("generated_asset_lineage") if isinstance(meta, dict) else {}
    source = lineage.get("source") if isinstance(lineage, dict) else {}
    prompt_id = str(source.get("promptId") or "") if isinstance(source, dict) else ""
    reference_id = (
        str(source.get("referenceId") or "") if isinstance(source, dict) else ""
    )
    account = str(public.get("instagramAccountId") or public.get("accountId") or "")
    provenance = provenance_by_account.get(account) or {
        "account": account,
        "medianValue": DEFAULT_REWARD_BASELINE,
        "sampleN": 0,
        "computedAt": utc_now(),
        "source": "default_prior",
    }
    record = {
        "promptId": prompt_id,
        "referenceId": reference_id or None,
        "postId": row.get("post_id"),
        "rewardScore": snapshot_normalized_reward(public, baselines),
        "confidence": 1.0,
        "sourceSnapshotAt": row.get("snapshot_at"),
        "scoringVersion": SCORING_VERSION,
        "baselineProvenance": provenance,
        "metrics": public.get("metrics"),
    }
    result = upsert_prompt_post_outcome(conn, record, commit=False)
    changed_reference_ids = {
        str(result.get("referenceId") or reference_id or "").strip()
    }
    if result.get("status") in {"written", "updated"}:
        old_prompt = str((previous_identity or {}).get("promptId") or "")
        old_post = str((previous_identity or {}).get("postId") or row.get("post_id"))
        if old_prompt and old_prompt != prompt_id:
            old_prompt_row = conn.execute(
                "SELECT reference_id FROM generated_video_prompts WHERE id = ?",
                (old_prompt,),
            ).fetchone()
            retract_prompt_post_outcome(
                conn, prompt_id=old_prompt, post_id=old_post, commit=False
            )
            if old_prompt_row:
                changed_reference_ids.add(str(old_prompt_row["reference_id"]))
        conn.commit()
    result["changedReferenceIds"] = sorted(
        value for value in changed_reference_ids if value
    )
    return result, provenance


def _destination_identity(
    destination: str, result: dict[str, Any]
) -> dict[str, Any] | None:
    if destination == "campaign" and result.get("snapshotId"):
        return {"snapshotId": result["snapshotId"]}
    if destination == "reel" and result.get("outcomeId") and result.get("filename"):
        return {"outcomeId": result["outcomeId"], "filename": result["filename"]}
    if destination == "reference" and result.get("promptId") and result.get("postId"):
        return {"promptId": result["promptId"], "postId": result["postId"]}
    return None


def _latest_eligible_by_post(
    snapshots: list[dict[str, Any]],
    eligible_by_key: dict[tuple[str, str], bool],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in snapshots:
        if eligible_by_key[_snapshot_key(row)]:
            result[str(row["post_id"])] = row
    return result


def _ledger_row(
    conn: sqlite3.Connection, key: tuple[str, str], destination: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM learning_fanout_ledger
        WHERE post_id = ? AND snapshot_at = ? AND destination = ?
        """,
        (*key, destination),
    ).fetchone()
    return dict(row) if row else None


def _previous_identity(
    conn: sqlite3.Connection,
    post_id: str,
    destination: str,
    current_key: tuple[str, str],
) -> dict[str, Any] | None:
    current = _ledger_row(conn, current_key, destination)
    if current and current.get("destination_record_id"):
        return _json_object(current["destination_record_id"])
    row = conn.execute(
        """
        SELECT destination_record_id
        FROM learning_fanout_ledger
        WHERE post_id = ? AND destination = ? AND destination_record_id IS NOT NULL
        ORDER BY julianday(snapshot_at) DESC, snapshot_at DESC
        LIMIT 1
        """,
        (post_id, destination),
    ).fetchone()
    return _json_object(row["destination_record_id"]) if row else None


def _mark_done(
    conn: sqlite3.Connection,
    key: tuple[str, str],
    destination: str,
    *,
    identity: dict[str, Any],
    baseline_provenance: dict[str, Any] | None,
    now: str,
) -> None:
    conn.execute(
        """
        UPDATE learning_fanout_ledger
        SET status = 'done', destination_record_id = ?, scoring_version = ?,
            baseline_provenance = ?, last_error = NULL, updated_at = ?
        WHERE post_id = ? AND snapshot_at = ? AND destination = ?
        """,
        (
            json.dumps(identity, sort_keys=True),
            SCORING_VERSION if destination == "reference" else None,
            json.dumps(baseline_provenance, sort_keys=True)
            if baseline_provenance
            else None,
            now,
            *key,
            destination,
        ),
    )
    conn.commit()


def _record_failure(
    conn: sqlite3.Connection,
    key: tuple[str, str],
    destination: str,
    error: str,
    *,
    max_attempts: int,
    report: dict[str, Any],
    now: str,
) -> None:
    row = _ledger_row(conn, key, destination)
    attempts = int((row or {}).get("attempt_count") or 0) + 1
    status = "failed_capped" if attempts >= max_attempts else "pending"
    conn.execute(
        """
        UPDATE learning_fanout_ledger
        SET status = ?, attempt_count = ?, last_error = ?, updated_at = ?
        WHERE post_id = ? AND snapshot_at = ? AND destination = ?
        """,
        (status, attempts, error[:2000], now, *key, destination),
    )
    conn.commit()
    report["fanout"][destination][
        "retryCapped" if status == "failed_capped" else "pending"
    ] += 1


def _set_ledger_status(
    conn: sqlite3.Connection,
    key: tuple[str, str],
    destination: str,
    *,
    status: str,
    now: str,
    last_error: str | None,
) -> None:
    conn.execute(
        """
        UPDATE learning_fanout_ledger
        SET status = ?, last_error = ?, updated_at = ?
        WHERE post_id = ? AND snapshot_at = ? AND destination = ?
        """,
        (status, last_error, now, *key, destination),
    )
    conn.commit()


def _supersede_other_snapshots(
    conn: sqlite3.Connection,
    *,
    post_id: str,
    destination: str,
    keep_snapshot_at: str,
    now: str,
) -> None:
    conn.execute(
        """
        UPDATE learning_fanout_ledger
        SET status = 'superseded', updated_at = ?
        WHERE post_id = ? AND destination = ? AND snapshot_at <> ?
          AND status IN ('pending', 'done')
        """,
        (now, post_id, destination, keep_snapshot_at),
    )


def _campaign_meta(row: dict[str, Any]) -> dict[str, Any]:
    raw = _json_object(row.get("raw_json"))
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    meta = metadata.get("campaign_factory") if isinstance(metadata, dict) else {}
    return meta if isinstance(meta, dict) else {}


def _empty_report(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "creator_os.learning_fanout.v1",
        "checkedAt": utc_now(),
        "postsScanned": len({str(row.get("post_id")) for row in snapshots}),
        "snapshotsScanned": len(snapshots),
        "eligibleSnapshots": 0,
        "ineligibleSnapshots": 0,
        "fallbackRows": 0,
        "ineligibleReasons": {},
        "fanout": {
            destination: {
                "done": 0,
                "pending": 0,
                "reopenedByHash": 0,
                "retryCapped": 0,
                "superseded": 0,
                "retracted": 0,
            }
            for destination in DESTINATIONS
        },
    }


def _write_sync_state(
    conn: sqlite3.Connection, report: dict[str, Any], *, now: str
) -> None:
    conn.execute(
        """
        INSERT INTO content_graph_sync_state (system, cursor_json, last_synced_at)
        VALUES ('creator_os.learning_fanout', ?, ?)
        ON CONFLICT(system) DO UPDATE SET
          cursor_json = excluded.cursor_json,
          last_synced_at = excluded.last_synced_at
        """,
        (json.dumps(report, ensure_ascii=False, sort_keys=True), now),
    )


def _snapshot_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("post_id") or ""), str(row.get("snapshot_at") or "")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fan out eligible learning outcomes")
    parser.add_argument("--campaign-factory-db", type=Path, required=True)
    parser.add_argument("--reel-factory-root", type=Path, required=True)
    parser.add_argument("--reference-factory-db", type=Path, required=True)
    parser.add_argument("--campaign")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(
            os.environ.get("LEARNING_FANOUT_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
        ),
    )
    args = parser.parse_args()
    result = fanout_learning_snapshots(
        campaign_factory_db=args.campaign_factory_db,
        reel_factory_root=args.reel_factory_root,
        reference_factory_db=args.reference_factory_db,
        campaign=args.campaign,
        max_attempts=max(1, args.max_attempts),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
