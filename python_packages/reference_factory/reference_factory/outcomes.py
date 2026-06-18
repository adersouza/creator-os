from __future__ import annotations

import json
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Iterable

from .db import json_dump
from .timeutil import now_iso


def import_prompt_outcomes(conn: Connection, records: Iterable[dict[str, Any]]) -> dict[str, object]:
    timestamp = now_iso()
    updated = 0
    skipped = 0
    skip_reasons: dict[str, int] = {}
    input_records = 0
    for record in records:
        input_records += 1
        reference_id = str(record.get("referenceId") or record.get("reference_id") or "").strip()
        prompt_id = str(record.get("promptId") or record.get("prompt_id") or "").strip()
        reward_score = _float_or_none(record.get("rewardScore", record.get("reward_score")))
        if reward_score is None:
            skipped += 1
            _count(skip_reasons, "missing_reward_score")
            continue
        if not reference_id and not prompt_id:
            skipped += 1
            _count(skip_reasons, "missing_reference_or_prompt_id")
            continue
        sample_count = max(0, _int_or_none(record.get("sampleCount", record.get("sample_count"))) or 0)
        confidence = _float_or_none(record.get("confidence"))
        target_tool = _optional_text(record.get("targetTool", record.get("target_tool")))
        model_profile = _optional_text(record.get("modelProfile", record.get("model_profile")))
        clauses: list[str] = []
        params: list[object] = []
        if prompt_id:
            clauses.append("id = ?")
            params.append(prompt_id)
        if reference_id:
            clauses.append("reference_id = ?")
            params.append(reference_id)
        if target_tool:
            clauses.append("target_tool = ?")
            params.append(target_tool)
        if model_profile:
            clauses.append("COALESCE(model_profile, '') = ?")
            params.append(model_profile)
        where = " AND ".join(clauses)
        cursor = conn.execute(
            f"""
            UPDATE generated_video_prompts
            SET outcome_sample_count = ?,
                outcome_reward_score = ?,
                outcome_confidence = ?,
                outcome_updated_at = ?,
                outcome_json = ?,
                updated_at = ?
            WHERE {where}
            """,
            [
                sample_count,
                float(reward_score),
                confidence,
                timestamp,
                json_dump(_compact_outcome_record(record)),
                timestamp,
                *params,
            ],
        )
        if cursor.rowcount:
            updated += cursor.rowcount
        else:
            skipped += 1
            _count(skip_reasons, "no_matching_generated_prompt")
    conn.commit()
    return {
        "schema": "reference_factory.import_prompt_outcomes.v1",
        "inputRecords": input_records,
        "updated": updated,
        "skipped": skipped,
        "skipReasons": skip_reasons,
    }


def import_prompt_outcomes_file(conn: Connection, input_paths: Iterable[Path]) -> dict[str, object]:
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


def _count(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1
