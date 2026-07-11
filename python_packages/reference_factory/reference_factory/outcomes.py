from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .db import json_dump, json_load
from .timeutil import now_iso


def import_prompt_outcomes(
    conn: Connection, records: Iterable[dict[str, Any]]
) -> dict[str, object]:
    updated = 0
    superseded = 0
    skipped = 0
    skip_reasons: dict[str, int] = {}
    input_records = 0
    for record in records:
        input_records += 1
        result = upsert_prompt_post_outcome(conn, record, commit=False)
        status = result["status"]
        if status in {"written", "updated"}:
            updated += 1
        elif status == "superseded":
            superseded += 1
        else:
            skipped += 1
            _count(skip_reasons, str(result.get("reason") or "unknown"))
    conn.commit()
    return {
        "schema": "reference_factory.import_prompt_outcomes.v1",
        "inputRecords": input_records,
        "updated": updated,
        "superseded": superseded,
        "skipped": skipped,
        "skipReasons": skip_reasons,
    }


def upsert_prompt_post_outcome(
    conn: Connection, record: dict[str, Any], *, commit: bool = True
) -> dict[str, Any]:
    prompt_id = _optional_text(record.get("promptId", record.get("prompt_id")))
    post_id = _optional_text(record.get("postId", record.get("post_id")))
    source_snapshot_at = _optional_text(
        record.get("sourceSnapshotAt", record.get("source_snapshot_at"))
    )
    reward_score = _float_or_none(record.get("rewardScore", record.get("reward_score")))
    scoring_version = _optional_text(
        record.get("scoringVersion", record.get("scoring_version"))
    )
    baseline_provenance = record.get(
        "baselineProvenance", record.get("baseline_provenance")
    )
    if not prompt_id:
        return {"status": "skipped", "reason": "missing_prompt_id"}
    if not post_id:
        return {"status": "skipped", "reason": "missing_post_id"}
    if reward_score is None:
        return {"status": "skipped", "reason": "missing_reward_score"}
    if not source_snapshot_at:
        return {"status": "skipped", "reason": "missing_source_snapshot_at"}
    if not scoring_version:
        return {"status": "skipped", "reason": "missing_scoring_version"}
    if not isinstance(baseline_provenance, dict):
        return {"status": "skipped", "reason": "missing_baseline_provenance"}

    prompt = conn.execute(
        "SELECT id, reference_id FROM generated_video_prompts WHERE id = ?",
        (prompt_id,),
    ).fetchone()
    if not prompt:
        return {"status": "skipped", "reason": "no_matching_generated_prompt"}
    reference_id = _optional_text(record.get("referenceId", record.get("reference_id")))
    if reference_id and not _prompt_accepts_reference(
        conn,
        prompt_id=prompt_id,
        primary_reference_id=str(prompt["reference_id"]),
        reference_id=reference_id,
    ):
        return {"status": "skipped", "reason": "reference_prompt_mismatch"}
    existing = conn.execute(
        "SELECT * FROM prompt_post_outcomes WHERE prompt_id = ? AND post_id = ?",
        (prompt_id, post_id),
    ).fetchone()
    if existing and _time_key(source_snapshot_at) < _time_key(
        existing["source_snapshot_at"]
    ):
        return {
            "status": "superseded",
            "promptId": prompt_id,
            "postId": post_id,
            "sourceSnapshotAt": source_snapshot_at,
        }
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO prompt_post_outcomes (
          prompt_id, post_id, reward_score, confidence, source_snapshot_at,
          scoring_version, baseline_provenance_json, outcome_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(prompt_id, post_id) DO UPDATE SET
          reward_score = excluded.reward_score,
          confidence = excluded.confidence,
          source_snapshot_at = excluded.source_snapshot_at,
          scoring_version = excluded.scoring_version,
          baseline_provenance_json = excluded.baseline_provenance_json,
          outcome_json = excluded.outcome_json,
          updated_at = excluded.updated_at
        """,
        (
            prompt_id,
            post_id,
            float(reward_score),
            _float_or_none(record.get("confidence")),
            source_snapshot_at,
            scoring_version,
            json_dump(baseline_provenance),
            json_dump(_compact_outcome_record(record)),
            timestamp,
            timestamp,
        ),
    )
    aggregate = recompute_prompt_outcome(conn, prompt_id)
    if commit:
        conn.commit()
    return {
        "status": "updated" if existing else "written",
        "promptId": prompt_id,
        "postId": post_id,
        "referenceId": str(prompt["reference_id"]),
        "attributedReferenceIds": _attributed_reference_ids(conn, prompt_id),
        "sourceSnapshotAt": source_snapshot_at,
        "aggregate": aggregate,
    }


def _prompt_accepts_reference(
    conn: Connection,
    *,
    prompt_id: str,
    primary_reference_id: str,
    reference_id: str,
) -> bool:
    if reference_id == primary_reference_id:
        return True
    linked = conn.execute(
        """
        SELECT 1 FROM generated_prompt_reference_links
        WHERE prompt_id = ? AND reference_id = ?
        UNION ALL
        SELECT 1 FROM generated_prompt_external_references
        WHERE prompt_id = ? AND external_reference_id = ?
        LIMIT 1
        """,
        (prompt_id, reference_id, prompt_id, reference_id),
    ).fetchone()
    return linked is not None


def _attributed_reference_ids(conn: Connection, prompt_id: str) -> list[str]:
    return [
        str(row["reference_id"])
        for row in conn.execute(
            """
            SELECT reference_id
            FROM generated_prompt_reference_links
            WHERE prompt_id = ? AND role = 'pattern_member'
            ORDER BY reference_id
            """,
            (prompt_id,),
        ).fetchall()
    ]


def retract_prompt_post_outcome(
    conn: Connection, *, prompt_id: str, post_id: str, commit: bool = True
) -> dict[str, Any]:
    cursor = conn.execute(
        "DELETE FROM prompt_post_outcomes WHERE prompt_id = ? AND post_id = ?",
        (prompt_id, post_id),
    )
    aggregate = recompute_prompt_outcome(conn, prompt_id)
    if commit:
        conn.commit()
    return {
        "status": "retracted" if cursor.rowcount else "missing",
        "promptId": prompt_id,
        "postId": post_id,
        "aggregate": aggregate,
    }


def recompute_prompt_outcome(conn: Connection, prompt_id: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT * FROM prompt_post_outcomes
        WHERE prompt_id = ?
        ORDER BY source_snapshot_at DESC, post_id
        """,
        (prompt_id,),
    ).fetchall()
    timestamp = now_iso()
    if not rows:
        conn.execute(
            """
            UPDATE generated_video_prompts
            SET outcome_sample_count = 0,
                outcome_reward_score = NULL,
                outcome_confidence = NULL,
                outcome_updated_at = NULL,
                outcome_json = '{}',
                updated_at = ?
            WHERE id = ?
            """,
            (timestamp, prompt_id),
        )
        return {"sampleCount": 0, "rewardScore": None}
    newest = max(_time_key(row["source_snapshot_at"]) for row in rows)
    weights = [
        0.5
        ** (
            max(0.0, (newest - _time_key(row["source_snapshot_at"])).total_seconds())
            / (30.0 * 86400.0)
        )
        for row in rows
    ]
    weight_total = max(0.000001, sum(weights))
    reward_score = (
        sum(
            float(row["reward_score"]) * weight
            for row, weight in zip(rows, weights, strict=True)
        )
        / weight_total
    )
    confidence_rows = [
        (float(row["confidence"]), weight)
        for row, weight in zip(rows, weights, strict=True)
        if row["confidence"] is not None
    ]
    confidence = (
        sum(value * weight for value, weight in confidence_rows)
        / max(0.000001, sum(weight for _, weight in confidence_rows))
        if confidence_rows
        else None
    )
    newest_row = rows[0]
    outcome = {
        "schema": "reference_factory.prompt_outcome_aggregate.v1",
        "rewardScore": round(reward_score, 8),
        "sampleCount": len(rows),
        "sourceSnapshotAt": newest_row["source_snapshot_at"],
        "scoringVersion": newest_row["scoring_version"],
        "baselineProvenance": json_load(newest_row["baseline_provenance_json"], {}),
        "postIds": sorted(str(row["post_id"]) for row in rows),
    }
    conn.execute(
        """
        UPDATE generated_video_prompts
        SET outcome_sample_count = ?,
            outcome_reward_score = ?,
            outcome_confidence = ?,
            outcome_updated_at = ?,
            outcome_json = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            len(rows),
            reward_score,
            confidence,
            newest_row["source_snapshot_at"],
            json_dump(outcome),
            timestamp,
            prompt_id,
        ),
    )
    return outcome


def import_prompt_outcomes_file(
    conn: Connection, input_paths: Iterable[Path]
) -> dict[str, object]:
    records: list[dict[str, Any]] = []
    for path in input_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records.extend(_records_from_payload(payload))
    result = import_prompt_outcomes(conn, records)
    result["inputPaths"] = [str(path) for path in input_paths]
    return result


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("outcomes", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _compact_outcome_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if value is not None and key not in {"secret", "token", "authorization"}
    }


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _time_key(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _count(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1
