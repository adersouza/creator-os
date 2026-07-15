"""Read-only export of retired Reel Factory posting evidence.

Campaign Factory owns measured facts in ``performance_snapshots``.  This module
exists only to preserve old Reel databases as migration/audit evidence.  It
opens the source with SQLite ``mode=ro`` and never creates, updates, or deletes
tables or rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from reel_factory.sqlite_utils import connect_sqlite

LEGACY_TABLES = (
    "reel_outcomes",
    "publish_metrics",
    "winner_dna",
    "review_decisions",
    "review_decision_history",
    "operator_ratings",
    "experiments",
    "experiment_assignments",
    "cost_events",
)


def export_legacy_outcome_evidence(
    source_db: Path, *, output_path: Path | None = None
) -> dict[str, Any]:
    source = Path(source_db).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    conn = connect_sqlite(source, readonly=True, wal=False)
    try:
        available = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        tables = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in LEGACY_TABLES
            if table in available
        }
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()
    payload = {
        "schema": "reel_factory.legacy_outcome_evidence.v1",
        "sourceDatabase": str(source),
        "readOnly": True,
        "canonicalMeasuredFactsSource": "campaign_factory.performance_snapshots",
        "canonicalWinnerSource": "reference_factory.knowledge_pack.v1",
        "integrity": integrity,
        "tables": tables,
        "rowCounts": {name: len(rows) for name, rows in tables.items()},
    }
    if output_path is not None:
        atomic_write_text(
            Path(output_path),
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_db", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    payload = export_legacy_outcome_evidence(args.source_db, output_path=args.out)
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
