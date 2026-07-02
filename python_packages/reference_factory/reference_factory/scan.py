from __future__ import annotations

from collections import Counter
from datetime import UTC
from pathlib import Path
from sqlite3 import Connection

from .config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from .identity import content_hash, stable_reference_id
from .timeutil import now_iso


def classify_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "other"


def scan_source(conn: Connection, source_root: Path) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    counts: Counter[str] = Counter()
    by_account: Counter[str] = Counter()
    inserted = 0
    updated = 0
    timestamp = now_iso()

    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        kind = classify_file(path)
        account = path.parent.name if path.parent != source_root else None
        reference_id = stable_reference_id(path, stat.st_size)
        try:
            file_content_hash = content_hash(path)
        except OSError:
            continue
        ext = path.suffix.lower().lstrip(".") or "_none"
        existing = conn.execute(
            """
            SELECT reference_id
            FROM source_files
            WHERE content_hash = ? OR reference_id = ? OR path = ?
            ORDER BY CASE
                WHEN content_hash = ? THEN 0
                WHEN reference_id = ? THEN 1
                ELSE 2
            END
            LIMIT 1
            """,
            (
                file_content_hash,
                reference_id,
                str(path),
                file_content_hash,
                reference_id,
            ),
        ).fetchone()
        stored_reference_id = existing["reference_id"] if existing else reference_id
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id, path, account, file_name, extension, kind,
              size_bytes, mtime, path_hash, content_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reference_id) DO UPDATE SET
              path = excluded.path,
              account = excluded.account,
              file_name = excluded.file_name,
              extension = excluded.extension,
              kind = excluded.kind,
              size_bytes = excluded.size_bytes,
              mtime = excluded.mtime,
              content_hash = excluded.content_hash,
              updated_at = excluded.updated_at
            """,
            (
                stored_reference_id,
                str(path),
                account,
                path.name,
                ext,
                kind,
                stat.st_size,
                timestamp_from_stat(stat.st_mtime),
                stored_reference_id.removeprefix("ref_"),
                file_content_hash,
                timestamp,
                timestamp,
            ),
        )
        counts[kind] += 1
        by_account[account or "_root"] += 1
        if existing:
            updated += 1
        else:
            inserted += 1

    conn.commit()
    return {
        "schema": "reference_factory.scan.v1",
        "sourceRoot": str(source_root),
        "totalFiles": sum(counts.values()),
        "inserted": inserted,
        "updated": updated,
        "byKind": dict(counts),
        "topAccounts": [
            {"account": account, "files": files}
            for account, files in by_account.most_common(50)
        ],
    }


def timestamp_from_stat(mtime: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(mtime, UTC).isoformat()
