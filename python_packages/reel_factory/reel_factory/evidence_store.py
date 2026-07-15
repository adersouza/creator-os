"""Derived-media evidence storage for Reel Factory.

Campaign Factory owns campaigns, creators, references, recommendations, and
generation plans.  Reel Factory stores only evidence produced while rendering
those explicit inputs.  The legacy module name remains import-compatible while
callers move to the narrower boundary.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from creator_os_core.sqlite import ensure_columns as _ensure_columns

from reel_factory.sqlite_utils import connect_sqlite

from .asset_prompt_contract import parse_asset_prompt_response
from .intelligence_store import ensure_intelligence_schema
from .state_paths import manifest_db_path


def db_path(root: Path) -> Path:
    return manifest_db_path(root)


def connect(root: Path) -> sqlite3.Connection:
    Path(root).resolve().mkdir(parents=True, exist_ok=True)
    conn = connect_sqlite(db_path(root))
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_evidence_schema(conn)
    return conn


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or f"evidence_{int(time.time())}"


def ensure_evidence_schema(conn: sqlite3.Connection) -> None:
    """Create only render evidence tables; never create campaign planner state."""

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS prompt_runs (
        prompt_run_id TEXT PRIMARY KEY,
        campaign_id TEXT,
        creator_id TEXT,
        reference_id TEXT,
        campaign_key TEXT,
        creator_key TEXT,
        reference_key TEXT,
        model TEXT NOT NULL,
        prompt_json_path TEXT NOT NULL,
        lineage_path TEXT,
        response_id TEXT,
        prompt_fields_json TEXT NOT NULL,
        operator_notes TEXT,
        status TEXT NOT NULL DEFAULT 'ok',
        created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS asset_generations (
        asset_generation_id TEXT PRIMARY KEY,
        campaign_id TEXT,
        creator_id TEXT,
        prompt_run_id TEXT,
        reference_id TEXT,
        campaign_key TEXT,
        creator_key TEXT,
        reference_key TEXT,
        stem TEXT NOT NULL,
        upload_id TEXT,
        image_job_id TEXT,
        image_result_url TEXT,
        video_job_id TEXT,
        video_result_url TEXT,
        local_image_path TEXT,
        local_video_path TEXT,
        selected_panel TEXT,
        start_image TEXT,
        expected_soul_id TEXT,
        actual_soul_id TEXT,
        identity_status TEXT NOT NULL DEFAULT 'unknown',
        lineage_path TEXT,
        params_json TEXT NOT NULL DEFAULT '{}',
        raw_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'created',
        created_at INTEGER NOT NULL,
        FOREIGN KEY(prompt_run_id) REFERENCES prompt_runs(prompt_run_id)
    );
    CREATE TABLE IF NOT EXISTS campaign_outputs (
        campaign_output_id TEXT PRIMARY KEY,
        campaign_id TEXT,
        campaign_key TEXT,
        creator_key TEXT,
        asset_generation_id TEXT,
        prompt_run_id TEXT,
        output_path TEXT NOT NULL UNIQUE,
        job_key TEXT,
        caption_text TEXT,
        recipe TEXT,
        readiness_status TEXT,
        export_path TEXT,
        metrics_filename TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        FOREIGN KEY(asset_generation_id) REFERENCES asset_generations(asset_generation_id),
        FOREIGN KEY(prompt_run_id) REFERENCES prompt_runs(prompt_run_id)
    );
    CREATE INDEX IF NOT EXISTS idx_campaign_outputs_metrics_filename ON campaign_outputs(metrics_filename);
    """)
    for table, columns in {
        "prompt_runs": {
            "campaign_key": "TEXT",
            "creator_key": "TEXT",
            "reference_key": "TEXT",
        },
        "asset_generations": {
            "campaign_key": "TEXT",
            "creator_key": "TEXT",
            "reference_key": "TEXT",
        },
        "campaign_outputs": {"campaign_key": "TEXT", "creator_key": "TEXT"},
    }.items():
        _ensure_columns(conn, table, columns)
    ensure_intelligence_schema(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_outputs_campaign_key ON campaign_outputs(campaign_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_generations_campaign_key ON asset_generations(campaign_key)"
    )
    conn.commit()


def record_prompt_run(
    root: Path,
    *,
    campaign: str | None,
    creator: str | None,
    prompt_json_path: Path,
    model: str,
    prompt_fields: dict[str, Any],
    lineage_path: Path | None = None,
    response_id: str | None = None,
    reference_id: str | None = None,
    operator_notes: str = "",
    status: str = "ok",
) -> dict[str, Any]:
    parse_asset_prompt_response(json.dumps(prompt_fields, ensure_ascii=False))
    conn = connect(root)
    prompt_run_id = f"prompt_{int(time.time() * 1000)}"
    conn.execute(
        """
        INSERT INTO prompt_runs (
            prompt_run_id, campaign_key, creator_key, reference_key, model,
            prompt_json_path, lineage_path, response_id, prompt_fields_json,
            operator_notes, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prompt_run_id,
            campaign,
            creator,
            reference_id,
            model,
            str(Path(prompt_json_path).resolve()),
            str(Path(lineage_path).resolve()) if lineage_path else None,
            response_id,
            json.dumps(prompt_fields, ensure_ascii=False, sort_keys=True),
            operator_notes,
            status,
            int(time.time()),
        ),
    )
    conn.commit()
    return {"ok": True, "prompt_run_id": prompt_run_id}


def prompt_run_for_path(
    conn: sqlite3.Connection, prompt_json_path: Path
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM prompt_runs WHERE prompt_json_path=? ORDER BY created_at DESC LIMIT 1",
        (str(Path(prompt_json_path).resolve()),),
    ).fetchone()


def extract_custom_reference_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        params = payload.get("params")
        if isinstance(params, dict) and isinstance(
            params.get("custom_reference_id"), str
        ):
            return params["custom_reference_id"]
        for value in payload.values():
            found = extract_custom_reference_id(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = extract_custom_reference_id(item)
            if found:
                return found
    return None


def validate_generation_soul(
    raw_image_response: Any, expected_soul_id: str | None
) -> dict[str, Any]:
    actual = extract_custom_reference_id(raw_image_response)
    if not expected_soul_id:
        return {"status": "unknown", "expected": None, "actual": actual}
    return {
        "status": "valid" if actual == expected_soul_id else "invalid",
        "expected": expected_soul_id,
        "actual": actual,
    }


def record_asset_generation(
    root: Path,
    *,
    campaign: str | None,
    creator: str | None,
    prompt_json_path: Path,
    stem: str,
    lineage_path: Path | None,
    lineage: dict[str, Any],
) -> dict[str, Any]:
    conn = connect(root)
    prompt_run = prompt_run_for_path(conn, prompt_json_path)
    generation = lineage.get("generation") or {}
    source = lineage.get("source") or {}
    assets = (lineage.get("assets") or {}).get("localPaths") or {}
    validation = validate_generation_soul(
        (generation.get("raw") or {}).get("image"), generation.get("soulId")
    )
    generation_status = str(generation.get("status") or "")
    record_status = generation_status or (
        "created" if validation["status"] != "invalid" else "invalid_identity"
    )
    reference_key = None
    if prompt_run:
        reference_key = prompt_run["reference_key"] or prompt_run["reference_id"]
    reference_key = reference_key or source.get("referenceId")
    campaign_key = campaign or (prompt_run["campaign_key"] if prompt_run else None)
    creator_key = creator or (prompt_run["creator_key"] if prompt_run else None)
    asset_generation_id = f"asset_{stem}_{int(time.time() * 1000)}"
    conn.execute(
        """
        INSERT INTO asset_generations (
            asset_generation_id, campaign_key, creator_key, prompt_run_id, reference_key,
            stem, upload_id, image_job_id, image_result_url, video_job_id, video_result_url,
            local_image_path, local_video_path, selected_panel, start_image,
            expected_soul_id, actual_soul_id, identity_status, lineage_path,
            params_json, raw_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_generation_id,
            campaign_key,
            creator_key,
            prompt_run["prompt_run_id"] if prompt_run else None,
            reference_key,
            stem,
            generation.get("uploadId"),
            generation.get("imageJobId"),
            generation.get("imageResultUrl"),
            generation.get("videoJobId"),
            generation.get("videoResultUrl"),
            assets.get("image"),
            assets.get("video"),
            source.get("selectedPanel"),
            source.get("startImage"),
            validation["expected"],
            validation["actual"],
            validation["status"],
            str(Path(lineage_path).resolve()) if lineage_path else None,
            json.dumps(
                generation.get("params") or {}, ensure_ascii=False, sort_keys=True
            ),
            json.dumps(generation.get("raw") or {}, ensure_ascii=False, sort_keys=True),
            record_status,
            int(time.time()),
        ),
    )
    conn.commit()
    return {
        "ok": True,
        "asset_generation_id": asset_generation_id,
        "identity": validation,
    }


def update_asset_generation(
    root: Path, asset_generation_id: str, **fields: Any
) -> dict[str, Any]:
    allowed = {
        "video_job_id",
        "video_result_url",
        "local_image_path",
        "local_video_path",
        "selected_panel",
        "start_image",
        "lineage_path",
        "status",
        "params_json",
        "raw_json",
    }
    for key in ("params_json", "raw_json"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False, sort_keys=True)
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return {"ok": True, "asset_generation_id": asset_generation_id, "changed": 0}
    conn = connect(root)
    assignments = ", ".join(f"{key}=?" for key in updates)
    cur = conn.execute(
        f"UPDATE asset_generations SET {assignments} WHERE asset_generation_id=?",
        [*updates.values(), asset_generation_id],
    )
    conn.commit()
    return {
        "ok": True,
        "asset_generation_id": asset_generation_id,
        "changed": cur.rowcount,
    }


def get_asset_generation(root: Path, asset_generation_id: str) -> dict[str, Any] | None:
    conn = connect(root)
    row = conn.execute(
        "SELECT * FROM asset_generations WHERE asset_generation_id=?",
        (asset_generation_id,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    for key in ("params_json", "raw_json"):
        try:
            data[key.replace("_json", "")] = json.loads(data.get(key) or "{}")
        except (TypeError, json.JSONDecodeError):
            data[key.replace("_json", "")] = {}
    return data


def link_campaign_output(
    root: Path,
    *,
    output_path: Path,
    campaign: str | None = None,
    creator: str | None = None,
    asset_generation_id: str | None = None,
    prompt_run_id: str | None = None,
    job_key: str | None = None,
    caption_text: str | None = None,
    recipe: str | None = None,
    readiness_status: str | None = None,
) -> dict[str, Any]:
    conn = connect(root)
    if asset_generation_id:
        asset = conn.execute(
            "SELECT campaign_key, creator_key FROM asset_generations WHERE asset_generation_id=?",
            (asset_generation_id,),
        ).fetchone()
        if asset:
            campaign = campaign or asset["campaign_key"]
            creator = creator or asset["creator_key"]
    output_path = Path(output_path).resolve()
    campaign_output_id = f"out_{slugify(output_path.stem)}"
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO campaign_outputs (
            campaign_output_id, campaign_key, creator_key, asset_generation_id,
            prompt_run_id, output_path, job_key, caption_text, recipe,
            readiness_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(output_path) DO UPDATE SET
            campaign_key=COALESCE(excluded.campaign_key, campaign_outputs.campaign_key),
            creator_key=COALESCE(excluded.creator_key, campaign_outputs.creator_key),
            asset_generation_id=COALESCE(excluded.asset_generation_id, campaign_outputs.asset_generation_id),
            prompt_run_id=COALESCE(excluded.prompt_run_id, campaign_outputs.prompt_run_id),
            job_key=COALESCE(excluded.job_key, campaign_outputs.job_key),
            caption_text=COALESCE(excluded.caption_text, campaign_outputs.caption_text),
            recipe=COALESCE(excluded.recipe, campaign_outputs.recipe),
            readiness_status=COALESCE(excluded.readiness_status, campaign_outputs.readiness_status),
            updated_at=excluded.updated_at
        """,
        (
            campaign_output_id,
            campaign,
            creator,
            asset_generation_id,
            prompt_run_id,
            str(output_path),
            job_key,
            caption_text,
            recipe,
            readiness_status,
            now,
            now,
        ),
    )
    conn.commit()
    return {"ok": True, "campaign_output_id": campaign_output_id}
