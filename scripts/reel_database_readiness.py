#!/usr/bin/env python3
"""Prove Reel manifest and queue migrations on temporary database copies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/creator_os_core"))
sys.path.insert(0, str(ROOT / "python_packages/reel_factory"))

from creator_os_core.runtime_paths import resolve_runtime_paths
from reel_factory.db_migrations import migration_readiness_report


def main() -> int:
    paths = resolve_runtime_paths(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=paths.reel_manifest_db)
    parser.add_argument("--queue", type=Path, default=paths.reel_render_queue_db)
    args = parser.parse_args()

    results = []
    failed = False
    for kind, path in (("manifest", args.manifest), ("queue", args.queue)):
        try:
            results.append(
                migration_readiness_report(path, database_kind=kind)  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001 - diagnostic boundary
            failed = True
            results.append(
                {
                    "schema": "creator_os.reel_database_migration_readiness.v1",
                    "mode": "copied_database_only",
                    "databaseKind": kind,
                    "sourcePath": str(path.expanduser()),
                    "status": "blocked",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
    print(json.dumps(results, indent=2, sort_keys=True))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
