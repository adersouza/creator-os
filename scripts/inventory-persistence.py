#!/usr/bin/env python3
"""Emit the canonical SQLite field inventory used by the ownership checker."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from campaign_factory.db import connect as connect_campaign
from campaign_factory.db import init_db as init_campaign
from reel_factory.manifest import Manifest
from reel_factory.provider_spend_authorization import EXECUTION_RECEIPT_SQL
from reel_factory.render_queue import RenderQueue
from reference_factory.db import connect as connect_reference

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SQL_MUTATION = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)"
    r'\s+["`\[]?([A-Za-z_][A-Za-z0-9_]*)',
    flags=re.I,
)
SOURCE_STORES = {
    "python_packages/campaign_factory/campaign_factory": ("campaign_factory_sqlite",),
    "python_packages/reference_factory/reference_factory": (
        "reference_factory_sqlite",
    ),
    "python_packages/reel_factory/reel_factory": (
        "reel_factory_local_evidence",
        "reel_factory_render_queue",
    ),
}
PERSISTENT_JSON_WRITE = re.compile(
    r"(?:atomic_write_(?:text|json)|\.write_(?:text|bytes)\s*\(|"
    r"json\.dump\s*\(|\.write\s*\(\s*json\.dumps)",
)


def _records(conn: sqlite3.Connection) -> dict[str, Any]:
    records: dict[str, Any] = {}
    names = [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for name in names:
        fields: dict[str, Any] = {}
        foreign_keys: dict[str, list[dict[str, Any]]] = {}
        for row in conn.execute(f'PRAGMA foreign_key_list("{name}")'):
            foreign_keys.setdefault(str(row[3]), []).append(
                {
                    "record": str(row[2]),
                    "field": str(row[4]),
                    "onUpdate": str(row[5]),
                    "onDelete": str(row[6]),
                }
            )
        unique_constraints: list[list[str]] = []
        for index in conn.execute(f'PRAGMA index_list("{name}")'):
            if not bool(index[2]):
                continue
            columns = [
                str(row[2])
                for row in conn.execute(f'PRAGMA index_info("{index[1]}")')
                if row[2] is not None
            ]
            if columns:
                unique_constraints.append(columns)
        for row in conn.execute(f'PRAGMA table_info("{name}")'):
            field = str(row[1])
            fields[field] = {
                "type": str(row[2] or "ANY"),
                "required": bool(row[3]),
                "default": row[4],
                "primaryKey": bool(row[5]),
                "unique": [field] in unique_constraints,
                "foreignKeys": foreign_keys.get(field, []),
            }
        triggers = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name=? ORDER BY name",
                (name,),
            )
        ]
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        checks = (
            re.findall(r"\bCHECK\s*\(([^()]*)\)", str(table_sql[0]), flags=re.I)
            if table_sql and table_sql[0]
            else []
        )
        records[name] = {
            "fields": fields,
            "checks": [check.strip() for check in checks],
            "triggers": triggers,
            "uniqueConstraints": unique_constraints,
        }
    return records


def _direct_sql_writers(stores: dict[str, Any]) -> dict[str, Any]:
    writers: dict[str, dict[str, set[str]]] = {store: {} for store in stores}
    for relative_root, candidate_stores in SOURCE_STORES.items():
        for path in sorted((REPOSITORY_ROOT / relative_root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            records: set[str] = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(
                    node.value, str
                ):
                    continue
                records.update(SQL_MUTATION.findall(node.value))
            relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
            for record in records:
                owners = [
                    store
                    for store in candidate_stores
                    if record in stores.get(store, {})
                ]
                if len(owners) != 1:
                    continue
                writers[owners[0]].setdefault(record, set()).add(relative_path)
    writers["reel_factory_render_queue"].setdefault(
        "provider_execution_receipts", set()
    ).add("python_packages/reel_factory/reel_factory/provider_spend_authorization.py")
    return {
        store: {record: sorted(paths) for record, paths in sorted(records.items())}
        for store, records in writers.items()
    }


def _persistent_json_writers() -> dict[str, list[str]]:
    writers: dict[str, list[str]] = {}
    for package in (
        "python_packages/campaign_factory/campaign_factory",
        "python_packages/reference_factory/reference_factory",
        "python_packages/reel_factory/reel_factory",
    ):
        for path in sorted((REPOSITORY_ROOT / package).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if not PERSISTENT_JSON_WRITE.search(source):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            names: set[str] = set()
            for node in ast.walk(tree):
                values: list[str] = []
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    values.append(node.value)
                elif isinstance(node, ast.JoinedStr):
                    values.append(
                        "".join(
                            part.value
                            if isinstance(part, ast.Constant)
                            and isinstance(part.value, str)
                            else "{value}"
                            for part in node.values
                        )
                    )
                for value in values:
                    if ".json" not in value.lower():
                        continue
                    names.update(
                        match.group(0)
                        for match in re.finditer(
                            r"[A-Za-z0-9_./{}*-]*\.jsonl?", value, flags=re.I
                        )
                    )
            if names:
                writers[path.relative_to(REPOSITORY_ROOT).as_posix()] = sorted(names)
    return writers


def build_inventory() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="creator-os-persistence-") as directory:
        root = Path(directory)
        campaign = connect_campaign(root / "campaign.sqlite")
        init_campaign(campaign)
        reference = connect_reference(root / "reference.sqlite")
        manifest = Manifest(root / "manifest.json")
        queue = RenderQueue(root / "queue-root")
        queue.conn.execute(EXECUTION_RECEIPT_SQL)
        queue.conn.commit()
        try:
            stores = {
                "campaign_factory_sqlite": _records(campaign),
                "reference_factory_sqlite": _records(reference),
                "reel_factory_local_evidence": _records(manifest.conn),
                "reel_factory_render_queue": _records(queue.conn),
            }
            return {
                "schema": "creator_os.persistence_field_inventory.v1",
                "stores": stores,
                "directSqlWriters": _direct_sql_writers(stores),
                "persistentJsonWriters": _persistent_json_writers(),
            }
        finally:
            campaign.close()
            reference.close()
            manifest.conn.close()
            queue.conn.close()


if __name__ == "__main__":
    inventory = build_inventory()
    if "--direct-sql-writers-fingerprint" in sys.argv:
        payload = {
            "sha256": hashlib.sha256(
                json.dumps(
                    inventory["directSqlWriters"],
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            ).hexdigest()
        }
    elif "--persistent-json-writers-fingerprint" in sys.argv:
        payload = {
            "sha256": hashlib.sha256(
                json.dumps(
                    inventory["persistentJsonWriters"],
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            ).hexdigest()
        }
    elif "--persistent-json-writers" in sys.argv:
        payload = inventory["persistentJsonWriters"]
    elif "--direct-sql-writers" in sys.argv:
        payload = inventory["directSqlWriters"]
    else:
        payload = inventory
    print(json.dumps(payload, indent=2, sort_keys=True))
