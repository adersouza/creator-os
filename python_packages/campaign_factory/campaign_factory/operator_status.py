"""Bounded read-only operator summaries over canonical Campaign state."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from creator_os_core.sqlite import connect_sqlite

from .config import get_settings


def _counts(
    conn: sqlite3.Connection, query: str, params: Iterable[object] = ()
) -> dict[str, int]:
    return {str(row[0]): int(row[1]) for row in conn.execute(query, tuple(params))}


def _one(
    conn: sqlite3.Connection, query: str, params: Iterable[object]
) -> dict[str, Any] | None:
    row = conn.execute(query, tuple(params)).fetchone()
    return dict(row) if row else None


def audio_status(conn: sqlite3.Connection) -> dict[str, Any]:
    latest = _one(
        conn,
        """
        SELECT id, region, status, started_at, completed_at, error_summary,
               receipt_path
        FROM audio_refresh_runs ORDER BY started_at DESC LIMIT 1
        """,
        (),
    )
    return {
        "schema": "creator_os.operator_status.v1",
        "scope": "audio",
        "catalog": {
            "total": conn.execute("SELECT count(*) FROM audio_catalog").fetchone()[0],
            "active": conn.execute(
                "SELECT count(*) FROM audio_catalog WHERE active = 1"
            ).fetchone()[0],
            "resolvedActive": conn.execute(
                "SELECT count(*) FROM audio_catalog WHERE active = 1 AND resolved = 1"
            ).fetchone()[0],
            "lifecycle": _counts(
                conn,
                "SELECT lifecycle_state, count(*) FROM audio_catalog "
                "GROUP BY lifecycle_state ORDER BY lifecycle_state",
            ),
        },
        "cache": {
            "playableObjects": conn.execute(
                "SELECT count(*) FROM audio_cache_objects WHERE cached = 1"
            ).fetchone()[0],
            "bytes": conn.execute(
                "SELECT COALESCE(sum(size_bytes), 0) FROM audio_cache_objects "
                "WHERE cached = 1"
            ).fetchone()[0],
        },
        "selections": conn.execute("SELECT count(*) FROM audio_selections").fetchone()[
            0
        ],
        "performanceRollups": conn.execute(
            "SELECT count(*) FROM audio_performance_rollups"
        ).fetchone()[0],
        "latestRefresh": latest,
    }


def learning_status(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "schema": "creator_os.operator_status.v1",
        "scope": "learning",
        "performanceSnapshots": conn.execute(
            "SELECT count(*) FROM performance_snapshots"
        ).fetchone()[0],
        "knowledgePacks": conn.execute(
            "SELECT count(*) FROM reference_knowledge_packs"
        ).fetchone()[0],
        "recommendationRuns": conn.execute(
            "SELECT count(*) FROM recommendation_runs"
        ).fetchone()[0],
        "recommendations": {
            "total": conn.execute(
                "SELECT count(*) FROM recommendation_items"
            ).fetchone()[0],
            "byStatus": _counts(
                conn,
                "SELECT status, count(*) FROM recommendation_items "
                "GROUP BY status ORDER BY status",
            ),
        },
        "decisionReceipts": conn.execute(
            "SELECT count(*) FROM manager_decisions "
            "WHERE decision_type = 'learning_consumption'"
        ).fetchone()[0],
        "audioPerformanceRollups": conn.execute(
            "SELECT count(*) FROM audio_performance_rollups"
        ).fetchone()[0],
    }


def recovery_status(conn: sqlite3.Connection) -> dict[str, Any]:
    jobs = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, job_type, status, effect_state, recovery_policy,
                   work_item_id, authorization_id, attempt_id,
                   external_operation_id, reconciliation_classification,
                   error, updated_at
            FROM pipeline_jobs
            WHERE status IN ('queued', 'running')
              AND (
                effect_state IN ('AMBIGUOUS', 'EXTERNAL_ID_KNOWN')
                OR (status = 'queued' AND effect_state = 'PRE_EFFECT')
              )
            ORDER BY updated_at, id
            """
        ).fetchall()
    ]
    failed_capped = [
        dict(row)
        for row in conn.execute(
            """
            SELECT post_id, snapshot_at, destination, attempt_count,
                   source_hash, last_error, updated_at
            FROM learning_fanout_ledger
            WHERE status = 'failed_capped'
            ORDER BY updated_at, post_id, destination
            """
        ).fetchall()
    ]
    categories = {
        "ambiguousExternalEffects": [
            row for row in jobs if row["effect_state"] == "AMBIGUOUS"
        ],
        "knownProviderIdsAwaitingPolling": [
            row for row in jobs if row["effect_state"] == "EXTERNAL_ID_KNOWN"
        ],
        "preEffectJobs": [row for row in jobs if row["effect_state"] == "PRE_EFFECT"],
        "failedCappedLearning": failed_capped,
    }
    return {
        "schema": "creator_os.recovery_status.v1",
        "scope": "recovery",
        "mappingBlockers": [],
        "mappingBlockersSummary": "Mapping blockers: none.",
        "operationalRecoveryGaps": categories,
        "operationalRecoveryGapCount": sum(len(items) for items in categories.values()),
    }


def draft_freshness_status(
    conn: sqlite3.Connection, *, max_age_hours: float = 24
) -> dict[str, Any]:
    if max_age_hours <= 0:
        raise ValueError("max draft age must be positive")
    now = datetime.now(UTC)
    rows = conn.execute(
        """
        SELECT id, campaign_id, manifest_path, user_id, dry_run, status, created_at
        FROM threadsdash_exports
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    exports = []
    for raw in rows:
        row = dict(raw)
        try:
            created = datetime.fromisoformat(
                str(row["created_at"]).replace("Z", "+00:00")
            )
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age_hours = max(
                0.0,
                (now - created.astimezone(UTC)).total_seconds() / 3600,
            )
        except (TypeError, ValueError):
            age_hours = None
        stale = age_hours is None or age_hours > max_age_hours
        exports.append(
            {
                **row,
                "ageHours": round(age_hours, 3) if age_hours is not None else None,
                "freshness": "stale" if stale else "fresh",
                "schedulingAllowedByFreshness": not stale,
                "requiredAction": "reexport_and_reapprove" if stale else None,
            }
        )
    return {
        "schema": "creator_os.draft_freshness_report.v1",
        "policy": {
            "maxAgeHours": max_age_hours,
            "invalidTimestampIsStale": True,
            "staleDraftRequiresReexportAndReapproval": True,
        },
        "staleCount": sum(row["freshness"] == "stale" for row in exports),
        "exports": exports,
    }


def creator_status(conn: sqlite3.Connection, creator: str) -> dict[str, Any]:
    model = _one(
        conn,
        "SELECT id, slug, name FROM models WHERE lower(slug) = lower(?)",
        (creator,),
    )
    if model is None:
        raise ValueError(f"unknown creator: {creator}")
    model_id = model["id"]
    return {
        "schema": "creator_os.operator_status.v1",
        "scope": "creator",
        "creator": model,
        "sources": {
            "total": conn.execute(
                "SELECT count(*) FROM source_assets WHERE model_id = ?", (model_id,)
            ).fetchone()[0],
            "byStatus": _counts(
                conn,
                "SELECT status, count(*) FROM source_assets WHERE model_id = ? "
                "GROUP BY status ORDER BY status",
                (model_id,),
            ),
            "approvedImages": conn.execute(
                "SELECT count(*) FROM source_assets WHERE model_id = ? "
                "AND media_type = 'image' AND lower(status) = 'approved'",
                (model_id,),
            ).fetchone()[0],
        },
        "campaigns": conn.execute(
            "SELECT count(*) FROM campaigns c WHERE EXISTS "
            "(SELECT 1 FROM source_assets s WHERE s.campaign_id = c.id AND s.model_id = ?)",
            (model_id,),
        ).fetchone()[0],
    }


def campaign_status(conn: sqlite3.Connection, campaign: str) -> dict[str, Any]:
    row = _one(
        conn,
        "SELECT id, slug, name, platform, updated_at FROM campaigns "
        "WHERE id = ? OR slug = ?",
        (campaign, campaign),
    )
    if row is None:
        raise ValueError(f"unknown campaign: {campaign}")
    campaign_id = row["id"]
    return {
        "schema": "creator_os.operator_status.v1",
        "scope": "campaign",
        "campaign": row,
        "sources": _counts(
            conn,
            "SELECT status, count(*) FROM source_assets WHERE campaign_id = ? "
            "GROUP BY status ORDER BY status",
            (campaign_id,),
        ),
        "rendered": _counts(
            conn,
            "SELECT review_state, count(*) FROM rendered_assets WHERE campaign_id = ? "
            "GROUP BY review_state ORDER BY review_state",
            (campaign_id,),
        ),
        "exports": _counts(
            conn,
            "SELECT status, count(*) FROM threadsdash_exports WHERE campaign_id = ? "
            "GROUP BY status ORDER BY status",
            (campaign_id,),
        ),
        "performanceSnapshots": conn.execute(
            "SELECT count(*) FROM performance_snapshots WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0],
        "recommendationRuns": conn.execute(
            "SELECT count(*) FROM recommendation_runs WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()[0],
    }


def generation_status(conn: sqlite3.Connection, generation: str) -> dict[str, Any]:
    row = _one(
        conn,
        """
        SELECT id, campaign_id, pipeline_job_id, source_asset_id,
               rendered_asset_id, output_blob_id, request_fingerprint, model_id,
               motion_task, duplicate_disposition, attempted_output_path, created_at
        FROM generation_attempts
        WHERE id = ? OR request_fingerprint = ? OR rendered_asset_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (generation, generation, generation),
    )
    if row is None:
        raise ValueError(f"unknown generation: {generation}")
    return {
        "schema": "creator_os.operator_status.v1",
        "scope": "generation",
        "generation": row,
        "lineageEdges": conn.execute(
            "SELECT count(*) FROM generation_lineage_edges WHERE generation_attempt_id = ?",
            (row["id"],),
        ).fetchone()[0],
    }


def publication_status(conn: sqlite3.Connection, publication: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id, campaign_id, rendered_asset_id, content_hash, post_id,
               status, account_id, instagram_account_id, permalink,
               published_at, snapshot_at, views, likes, comments, shares, saves
        FROM performance_snapshots
        WHERE post_id = ? OR permalink = ? OR raw_json LIKE ?
        ORDER BY snapshot_at DESC
        """,
        (publication, publication, f'%"{publication}"%'),
    ).fetchall()
    return {
        "schema": "creator_os.operator_status.v1",
        "scope": "publication",
        "query": publication,
        "snapshots": [dict(row) for row in rows],
    }


def _print_plain(payload: dict[str, Any], prefix: str = "") -> None:
    for key, value in payload.items():
        label = f"{prefix}{key}"
        if isinstance(value, dict):
            _print_plain(value, f"{label}.")
        elif isinstance(value, list):
            print(f"{label}: {len(value)} item(s)")
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    _print_plain(item, f"{label}[{index}].")
        else:
            print(f"{label}: {value}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--creator")
    scope.add_argument("--campaign")
    scope.add_argument("--generation")
    scope.add_argument("--publication")
    scope.add_argument("--learning", action="store_true")
    scope.add_argument("--audio", action="store_true")
    scope.add_argument("--drafts", action="store_true")
    scope.add_argument("--recovery", action="store_true")
    parser.add_argument("--max-draft-age-hours", type=float, default=24)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    conn = connect_sqlite(get_settings().db_path, readonly=True)
    try:
        if args.creator:
            payload = creator_status(conn, args.creator)
        elif args.campaign:
            payload = campaign_status(conn, args.campaign)
        elif args.generation:
            payload = generation_status(conn, args.generation)
        elif args.publication:
            payload = publication_status(conn, args.publication)
        elif args.learning:
            payload = learning_status(conn)
        elif args.drafts:
            payload = draft_freshness_status(
                conn, max_age_hours=args.max_draft_age_hours
            )
        elif args.recovery:
            payload = recovery_status(conn)
        else:
            payload = audio_status(conn)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_plain(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
