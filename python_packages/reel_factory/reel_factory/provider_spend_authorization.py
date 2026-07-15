"""Worker-side validation of Campaign-issued spend authorizations."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.provider_spend import (
    SpendAuthorizationError,
    build_generate_assets_spend_scope,
    verify_authorization,
)
from creator_os_core.runtime_paths import resolve_runtime_paths

from .sqlite_utils import connect_sqlite

EXECUTION_RECEIPT_TABLE = "provider_execution_receipts"
EXECUTION_RECEIPT_SQL = f"""
CREATE TABLE IF NOT EXISTS {EXECUTION_RECEIPT_TABLE} (
    authorization_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL UNIQUE,
    request_fingerprint TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('consumed')),
    consumed_at TEXT NOT NULL
)
"""


def require_campaign_spend_authorization(
    args: Sequence[str],
    *,
    root: str | Path,
    authorization_file: str | Path | None,
    secret: str | None = None,
    receipt_db_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and consume one authorization before any provider interaction."""
    if not authorization_file:
        raise SpendAuthorizationError(
            "paid Reel Factory generation requires a Campaign-issued "
            "--spend-authorization-file"
        )
    path = Path(authorization_file).expanduser().resolve()
    if not path.is_file():
        raise SpendAuthorizationError("provider spend authorization file is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpendAuthorizationError(
            "provider spend authorization file is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise SpendAuthorizationError("provider spend authorization must be an object")
    scope = build_generate_assets_spend_scope(args, root=root)
    verified = verify_authorization(
        payload,
        expected_scope=scope,
        secret=secret or os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", ""),
        now=now,
    )
    db_path = (
        Path(receipt_db_path).expanduser().resolve()
        if receipt_db_path is not None
        else resolve_runtime_paths().reel_render_queue_db
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    consumed_at = (
        (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    )
    try:
        with connect_sqlite(db_path, wal=False) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(EXECUTION_RECEIPT_SQL)
            conn.execute(
                f"""
                INSERT INTO {EXECUTION_RECEIPT_TABLE}
                    (authorization_id, reservation_id, request_fingerprint,
                     provider, status, consumed_at)
                VALUES (?, ?, ?, 'higgsfield', 'consumed', ?)
                """,
                (
                    verified["authorizationId"],
                    verified["reservationId"],
                    verified["scope"]["requestFingerprint"],
                    consumed_at,
                ),
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SpendAuthorizationError(
            "provider spend authorization was already consumed"
        ) from exc
    return verified


def spend_scope_args_for_plan(plan: Any, *, mode: str) -> list[str]:
    """Render the exact canonical scope inputs for a generation plan."""
    args = [mode, "--stem", str(plan.stem), "--soul-id", str(plan.soul_id or "")]
    optional = (
        ("--campaign", getattr(plan, "campaign", None)),
        ("--cohort-id", getattr(plan, "cohort_id", None)),
        ("--prompt-json", getattr(plan, "prompt_json", None)),
        ("--reference", getattr(plan, "reference_image", None)),
        ("--start-image", getattr(plan, "start_image", None)),
        ("--end-image", getattr(plan, "end_image", None)),
        ("--video-reference", getattr(plan, "video_reference", None)),
        ("--image-model", getattr(plan, "image_model", None)),
        ("--video-model", getattr(plan, "video_model", None)),
        ("--image-mode", getattr(plan, "image_mode", None)),
        ("--image-aspect-ratio", getattr(plan, "image_aspect_ratio", None)),
        ("--image-quality", getattr(plan, "image_quality", None)),
        ("--video-aspect-ratio", getattr(plan, "video_aspect_ratio", None)),
        ("--video-duration", getattr(plan, "video_duration", None)),
        ("--video-mode", getattr(plan, "video_mode", None)),
        ("--video-sound", getattr(plan, "video_sound", None)),
    )
    for key, value in optional:
        if value is not None and value != "":
            args.extend([key, str(value)])
    return args
