from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text


def read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def record_reference_id(record: dict[str, Any]) -> str:
    return str(record.get("sourceReferenceId") or record.get("referenceId") or "")


def find_prompt_record(
    records: list[dict[str, Any]], reference_id: str
) -> dict[str, Any] | None:
    for record in records:
        if record_reference_id(record) == reference_id:
            return record
    return None
