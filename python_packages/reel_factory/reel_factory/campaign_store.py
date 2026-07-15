"""Campaign, creator, taste, and generation tracking for reel_factory."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.sqlite import ensure_columns as _ensure_columns

from pipeline_contracts import validate_recommendation_next_batch
from reel_factory.sqlite_utils import connect_sqlite

from .asset_prompt_contract import parse_asset_prompt_response
from .feature_extract import FEATURE_KEYS
from .intelligence_store import (
    confidence_for_sample_size,
    data_quality_from_connection,
    ensure_intelligence_schema,
    low_data_warning,
    validate_review,
)
from .state_paths import manifest_db_path

DEFAULT_CREATORS = {
    "Stacey": {
        "soul_id": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
        "default_settings": {
            "image_model": "text2image_soul_v2",
            "video_model": "kling3_0",
            "accepted_soul_ids": ["d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"],
        },
    },
    "Stacey1": {
        "soul_id": "5828d958-91dd-4d6d-8909-934503f47644",
        "default_settings": {
            "image_model": "text2image_soul_v2",
            "video_model": "kling3_0",
            "accepted_soul_ids": ["5828d958-91dd-4d6d-8909-934503f47644"],
        },
    },
    "Larissa": {
        "soul_id": "44326567-b12c-410c-95b7-31891bb0629b",
        "default_settings": {
            "image_model": "text2image_soul_v2",
            "video_model": "kling3_0",
            "accepted_soul_ids": ["44326567-b12c-410c-95b7-31891bb0629b"],
        },
    },
    "Lola": {
        "soul_id": "4c86c548-7aa5-4ad1-bc03-b94aa4ce8385",
        "default_settings": {
            "image_model": "text2image_soul_v2",
            "video_model": "kling3_0",
            "accepted_soul_ids": ["4c86c548-7aa5-4ad1-bc03-b94aa4ce8385"],
        },
    },
}

RATING_FIELDS = ("identity", "pose", "taste", "artifacts", "motion", "caption")
VALID_RETRY_HELPERS = {
    "fix_pose",
    "fix_hands",
    "less_smile",
    "more_reference_fidelity",
    "more_body_emphasis",
    "more_cleavage",
}

DEFAULT_RECIPE_HINTS = ("v01_original", "v09_caption_bg")

RETRY_HELPER_DIRECTIONS = {
    "fix_pose": (
        "Retry focus: pose fidelity. Preserve the exact body orientation, crop, camera angle, "
        "limb placement, phone/support-hand placement, and seated/standing relationship from the reference. "
        "Keep the reference rotation and original non-generic body angle."
    ),
    "fix_hands": (
        "Retry focus: hand placement. Keep visible hands simple, anatomically plausible, relaxed, "
        "and close to the reference placement with clean support-hand shapes."
    ),
    "less_smile": (
        "Retry focus: sultry expression. Use sultry eye contact, teasing expression, confident gaze, "
        "and subtle parted lips as the expression direction."
    ),
    "more_reference_fidelity": (
        "Retry focus: increase reference fidelity. Match the reference room, lighting, framing, lens feel, outfit silhouette, "
        "pose, body angle, and camera distance more tightly while keeping the amplified body style: much larger pushed-up breasts, "
        "deep cleavage, thicker curvier frame, tiny waist, wide hips, thick thighs, round ass, and tight fabric tension. Vary only outfit color/material "
        "or cleavage-supporting cut details when making image variations."
    ),
    "more_body_emphasis": (
        "Retry focus: make the image much sexier while preserving the exact reference pose, framing, room, and camera angle. "
        "Use stronger body amplification with a curvier frame: much larger pushed-up full breasts, "
        "deep plunging cleavage as the focal point, smaller/tighter tops, visible fabric tension, thicker curvier frame, "
        "tiny waist, wider hips, thicker thighs, rounder ass, dramatic S-curve, and skin-tight fabric cling."
    ),
    "more_cleavage": (
        "Retry focus: make cleavage the strongest visual focal point while preserving the reference pose, framing, room, and camera angle. "
        "Use lower necklines, smaller/tighter tops, much larger pushed-up full breasts, deep plunging cleavage, visible fabric tension, "
        "and realistic stretch/cling with amplified curves."
    ),
}


def retry_helper_direction(helper: str | None) -> str:
    if not helper:
        return ""
    if helper not in RETRY_HELPER_DIRECTIONS:
        raise ValueError(
            f"retry_helper must be one of {sorted(RETRY_HELPER_DIRECTIONS)}"
        )
    return RETRY_HELPER_DIRECTIONS[helper]


def db_path(root: Path) -> Path:
    return manifest_db_path(root)


def connect(root: Path) -> sqlite3.Connection:
    Path(root).resolve().mkdir(parents=True, exist_ok=True)
    conn = connect_sqlite(db_path(root))
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_campaign_schema(conn)
    return conn


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or f"campaign_{int(time.time())}"


def ensure_campaign_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS creators (
        creator_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        soul_id TEXT NOT NULL,
        default_settings_json TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS campaigns (
        campaign_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        creator_id TEXT NOT NULL,
        account TEXT NOT NULL,
        platform TEXT NOT NULL,
        content_angle TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        notes TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        FOREIGN KEY(creator_id) REFERENCES creators(creator_id)
    );
    CREATE TABLE IF NOT EXISTS campaign_references (
        reference_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        source_path TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_views INTEGER,
        source_likes INTEGER,
        source_comments INTEGER,
        source_posted_at TEXT,
        extracted_frames_json TEXT NOT NULL DEFAULT '[]',
        visual_tags_json TEXT NOT NULL DEFAULT '[]',
        intended_pose TEXT,
        intended_outfit TEXT,
        intended_scene TEXT,
        notes TEXT,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id)
    );
    CREATE TABLE IF NOT EXISTS prompt_runs (
        prompt_run_id TEXT PRIMARY KEY,
        campaign_id TEXT,
        creator_id TEXT,
        reference_id TEXT,
        model TEXT NOT NULL,
        prompt_json_path TEXT NOT NULL,
        lineage_path TEXT,
        response_id TEXT,
        prompt_fields_json TEXT NOT NULL,
        operator_notes TEXT,
        status TEXT NOT NULL DEFAULT 'ok',
        created_at INTEGER NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id),
        FOREIGN KEY(creator_id) REFERENCES creators(creator_id),
        FOREIGN KEY(reference_id) REFERENCES campaign_references(reference_id)
    );
    CREATE TABLE IF NOT EXISTS asset_generations (
        asset_generation_id TEXT PRIMARY KEY,
        campaign_id TEXT,
        creator_id TEXT,
        prompt_run_id TEXT,
        reference_id TEXT,
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
        FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id),
        FOREIGN KEY(creator_id) REFERENCES creators(creator_id),
        FOREIGN KEY(prompt_run_id) REFERENCES prompt_runs(prompt_run_id),
        FOREIGN KEY(reference_id) REFERENCES campaign_references(reference_id)
    );
    CREATE TABLE IF NOT EXISTS operator_ratings (
        rating_id TEXT PRIMARY KEY,
        output_path TEXT,
        asset_generation_id TEXT,
        campaign_id TEXT,
        identity_score INTEGER,
        pose_score INTEGER,
        taste_score INTEGER,
        artifact_score INTEGER,
        motion_score INTEGER,
        caption_score INTEGER,
        labels_json TEXT NOT NULL DEFAULT '[]',
        retry_helper TEXT,
        approve_reject_reason TEXT,
        notes TEXT,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(asset_generation_id) REFERENCES asset_generations(asset_generation_id),
        FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id)
    );
    CREATE TABLE IF NOT EXISTS campaign_outputs (
        campaign_output_id TEXT PRIMARY KEY,
        campaign_id TEXT,
        asset_generation_id TEXT,
        prompt_run_id TEXT,
        output_path TEXT NOT NULL UNIQUE,
        job_key TEXT,
        caption_text TEXT,
        recipe TEXT,
        review_state TEXT,
        readiness_status TEXT,
        export_path TEXT,
        metrics_filename TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id),
        FOREIGN KEY(asset_generation_id) REFERENCES asset_generations(asset_generation_id),
        FOREIGN KEY(prompt_run_id) REFERENCES prompt_runs(prompt_run_id)
    );
    CREATE TABLE IF NOT EXISTS publish_metrics (
        filename TEXT PRIMARY KEY,
        platform TEXT,
        account TEXT,
        uploaded_at TEXT,
        views INTEGER,
        likes INTEGER,
        comments INTEGER,
        shares INTEGER,
        saves INTEGER,
        manual_score REAL,
        notes TEXT,
        soul_id TEXT,
        campaign_output_id TEXT,
        job_key TEXT,
        imported_at INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_publish_metrics_campaign_output ON publish_metrics(campaign_output_id);
    CREATE INDEX IF NOT EXISTS idx_publish_metrics_job_key ON publish_metrics(job_key);
    CREATE INDEX IF NOT EXISTS idx_campaign_outputs_campaign ON campaign_outputs(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_campaign_outputs_metrics_filename ON campaign_outputs(metrics_filename);
    CREATE INDEX IF NOT EXISTS idx_operator_ratings_output ON operator_ratings(output_path);
    CREATE INDEX IF NOT EXISTS idx_asset_generations_campaign ON asset_generations(campaign_id);
    """)
    ensure_intelligence_schema(conn)
    _ensure_columns(
        conn,
        "publish_metrics",
        {"soul_id": "TEXT", "campaign_output_id": "TEXT", "job_key": "TEXT"},
    )
    _ensure_columns(
        conn,
        "campaign_references",
        {
            "source_views": "INTEGER",
            "source_likes": "INTEGER",
            "source_comments": "INTEGER",
            "source_posted_at": "TEXT",
        },
    )
    _backfill_campaign_reference_source_metrics(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_publish_metrics_campaign_output ON publish_metrics(campaign_output_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_publish_metrics_job_key ON publish_metrics(job_key)"
    )
    now = int(time.time())
    for name, cfg in DEFAULT_CREATORS.items():
        conn.execute(
            """
            INSERT INTO creators (creator_id, name, soul_id, default_settings_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                soul_id = excluded.soul_id,
                default_settings_json = excluded.default_settings_json
            """,
            (
                slugify(name),
                name,
                cfg["soul_id"],
                json.dumps(cfg["default_settings"], sort_keys=True),
                now,
            ),
        )
    conn.commit()


def creator_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM creators WHERE lower(name)=lower(?)", (name,)
    ).fetchone()
    if not row:
        raise ValueError(f"unknown creator: {name}")
    return row


def campaign_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM campaigns WHERE name=? OR campaign_id=?", (name, name)
    ).fetchone()
    if not row:
        raise ValueError(f"unknown campaign: {name}")
    return row


def create_campaign(
    root: Path,
    *,
    name: str,
    creator: str,
    account: str,
    platform: str,
    content_angle: str = "",
    notes: str = "",
) -> dict[str, Any]:
    conn = connect(root)
    creator_row = creator_by_name(conn, creator)
    campaign_id = slugify(name)
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO campaigns (
            campaign_id, name, creator_id, account, platform, content_angle,
            status, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            creator_id = excluded.creator_id,
            account = excluded.account,
            platform = excluded.platform,
            content_angle = excluded.content_angle,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (
            campaign_id,
            name,
            creator_row["creator_id"],
            account,
            platform,
            content_angle,
            notes,
            now,
            now,
        ),
    )
    conn.commit()
    return {"ok": True, "campaign_id": campaign_id, "name": name, "creator": creator}


def add_reference(
    root: Path,
    *,
    campaign: str,
    source_path: Path,
    source_type: str | None = None,
    frames: list[str] | None = None,
    visual_tags: list[str] | None = None,
    intended_pose: str = "",
    intended_outfit: str = "",
    intended_scene: str = "",
    notes: str = "",
    source_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = connect(root)
    campaign_row = campaign_by_name(conn, campaign)
    source_path = Path(source_path).expanduser().resolve()
    inferred = source_type or (
        "video" if source_path.suffix.lower() in {".mp4", ".mov", ".m4v"} else "image"
    )
    reference_id = f"{campaign_row['campaign_id']}_{slugify(source_path.stem)}"
    normalized_metrics = _normalize_source_metrics(source_metrics or {})
    conn.execute(
        """
        INSERT INTO campaign_references (
            reference_id, campaign_id, source_path, source_type, source_views,
            source_likes, source_comments, source_posted_at, extracted_frames_json,
            visual_tags_json, intended_pose, intended_outfit, intended_scene, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(reference_id) DO UPDATE SET
            source_path = excluded.source_path,
            source_type = excluded.source_type,
            source_views = COALESCE(excluded.source_views, campaign_references.source_views),
            source_likes = COALESCE(excluded.source_likes, campaign_references.source_likes),
            source_comments = COALESCE(excluded.source_comments, campaign_references.source_comments),
            source_posted_at = COALESCE(excluded.source_posted_at, campaign_references.source_posted_at),
            extracted_frames_json = excluded.extracted_frames_json,
            visual_tags_json = excluded.visual_tags_json,
            intended_pose = excluded.intended_pose,
            intended_outfit = excluded.intended_outfit,
            intended_scene = excluded.intended_scene,
            notes = excluded.notes
        """,
        (
            reference_id,
            campaign_row["campaign_id"],
            str(source_path),
            inferred,
            normalized_metrics["source_views"],
            normalized_metrics["source_likes"],
            normalized_metrics["source_comments"],
            normalized_metrics["source_posted_at"],
            json.dumps(frames or [], ensure_ascii=False),
            json.dumps(visual_tags or [], ensure_ascii=False),
            intended_pose,
            intended_outfit,
            intended_scene,
            notes,
            int(time.time()),
        ),
    )
    conn.commit()
    return {
        "ok": True,
        "reference_id": reference_id,
        "campaign_id": campaign_row["campaign_id"],
    }


def _normalize_source_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_views": _int_or_none(
            metrics.get("source_views")
            or metrics.get("view_count")
            or metrics.get("views")
        ),
        "source_likes": _int_or_none(
            metrics.get("source_likes")
            or metrics.get("like_count")
            or metrics.get("likes")
        ),
        "source_comments": _int_or_none(
            metrics.get("source_comments")
            or metrics.get("comment_count")
            or metrics.get("comments")
        ),
        "source_posted_at": _posted_at_from_metrics(metrics),
    }


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _posted_at_from_metrics(metrics: dict[str, Any]) -> str | None:
    value = (
        metrics.get("source_posted_at")
        or metrics.get("posted_at")
        or metrics.get("upload_date")
    )
    if value:
        text = str(value)
        if re.fullmatch(r"\d{8}", text):
            return datetime(
                int(text[0:4]),
                int(text[4:6]),
                int(text[6:8]),
                tzinfo=UTC,
            ).isoformat()
        return text
    timestamp = _int_or_none(metrics.get("timestamp"))
    if timestamp is not None:
        return datetime.fromtimestamp(timestamp, UTC).isoformat()
    return None


def _backfill_campaign_reference_source_metrics(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT reference_id, source_path
        FROM campaign_references
        WHERE source_views IS NULL
           OR source_likes IS NULL
           OR source_comments IS NULL
           OR source_posted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        metrics = _source_metrics_for_reference(Path(str(row["source_path"])))
        if not any(value is not None for value in metrics.values()):
            continue
        conn.execute(
            """
            UPDATE campaign_references
            SET source_views = COALESCE(source_views, ?),
                source_likes = COALESCE(source_likes, ?),
                source_comments = COALESCE(source_comments, ?),
                source_posted_at = COALESCE(source_posted_at, ?)
            WHERE reference_id = ?
            """,
            (
                metrics["source_views"],
                metrics["source_likes"],
                metrics["source_comments"],
                metrics["source_posted_at"],
                row["reference_id"],
            ),
        )


def _source_metrics_for_reference(source_path: Path) -> dict[str, Any]:
    sidecar = source_path.with_suffix(".reel_url_import.json")
    if sidecar.exists():
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            metrics = (
                payload.get("sourceMetrics") or payload.get("source_metrics") or {}
            )
            if isinstance(metrics, dict):
                normalized = _normalize_source_metrics(metrics)
                if any(value is not None for value in normalized.values()):
                    return normalized
        except (OSError, json.JSONDecodeError):
            pass
    info_json = source_path.with_suffix(".info.json")
    if info_json.exists():
        try:
            payload = json.loads(info_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            return _normalize_source_metrics(payload)
    return _normalize_source_metrics({})


def latest_reference_for_campaign(
    conn: sqlite3.Connection, campaign_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM campaign_references WHERE campaign_id=? ORDER BY created_at DESC LIMIT 1",
        (campaign_id,),
    ).fetchone()


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
    campaign_row = campaign_by_name(conn, campaign) if campaign else None
    creator_row = creator_by_name(conn, creator) if creator else None
    if campaign_row and not creator_row:
        creator_row = conn.execute(
            "SELECT * FROM creators WHERE creator_id=?", (campaign_row["creator_id"],)
        ).fetchone()
    reference_row = None
    if reference_id:
        reference_row = conn.execute(
            "SELECT * FROM campaign_references WHERE reference_id=?", (reference_id,)
        ).fetchone()
    elif campaign_row:
        reference_row = latest_reference_for_campaign(conn, campaign_row["campaign_id"])
    prompt_run_id = f"prompt_{int(time.time() * 1000)}"
    conn.execute(
        """
        INSERT INTO prompt_runs (
            prompt_run_id, campaign_id, creator_id, reference_id, model,
            prompt_json_path, lineage_path, response_id, prompt_fields_json,
            operator_notes, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prompt_run_id,
            campaign_row["campaign_id"] if campaign_row else None,
            creator_row["creator_id"] if creator_row else None,
            reference_row["reference_id"] if reference_row else None,
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
    resolved = str(Path(prompt_json_path).resolve())
    return conn.execute(
        "SELECT * FROM prompt_runs WHERE prompt_json_path=? ORDER BY created_at DESC LIMIT 1",
        (resolved,),
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
    campaign_row = campaign_by_name(conn, campaign) if campaign else None
    creator_row = creator_by_name(conn, creator) if creator else None
    if campaign_row and not creator_row:
        creator_row = conn.execute(
            "SELECT * FROM creators WHERE creator_id=?", (campaign_row["creator_id"],)
        ).fetchone()
    prompt_run = prompt_run_for_path(conn, prompt_json_path)
    generation = lineage.get("generation") or {}
    source = lineage.get("source") or {}
    assets = (lineage.get("assets") or {}).get("localPaths") or {}
    validation = validate_generation_soul(
        (generation.get("raw") or {}).get("image"), generation.get("soulId")
    )
    generation_status = str(generation.get("status") or "")
    record_status = (
        generation_status
        if generation_status
        else ("created" if validation["status"] != "invalid" else "invalid_identity")
    )
    asset_generation_id = f"asset_{stem}_{int(time.time() * 1000)}"
    conn.execute(
        """
        INSERT INTO asset_generations (
            asset_generation_id, campaign_id, creator_id, prompt_run_id, reference_id,
            stem, upload_id, image_job_id, image_result_url, video_job_id, video_result_url,
            local_image_path, local_video_path, selected_panel, start_image,
            expected_soul_id, actual_soul_id, identity_status, lineage_path,
            params_json, raw_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_generation_id,
            campaign_row["campaign_id"] if campaign_row else None,
            creator_row["creator_id"] if creator_row else None,
            prompt_run["prompt_run_id"] if prompt_run else None,
            prompt_run["reference_id"] if prompt_run else None,
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
    if "params_json" in fields and not isinstance(fields["params_json"], str):
        fields["params_json"] = json.dumps(
            fields["params_json"], ensure_ascii=False, sort_keys=True
        )
    if "raw_json" in fields and not isinstance(fields["raw_json"], str):
        fields["raw_json"] = json.dumps(
            fields["raw_json"], ensure_ascii=False, sort_keys=True
        )
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return {"ok": True, "asset_generation_id": asset_generation_id, "changed": 0}
    conn = connect(root)
    assignments = ", ".join(f"{key}=?" for key in updates)
    values = list(updates.values()) + [asset_generation_id]
    cur = conn.execute(
        f"UPDATE asset_generations SET {assignments} WHERE asset_generation_id=?",
        values,
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
        except Exception:
            data[key.replace("_json", "")] = {}
    return data


def link_campaign_output(
    root: Path,
    *,
    output_path: Path,
    campaign: str | None = None,
    asset_generation_id: str | None = None,
    prompt_run_id: str | None = None,
    job_key: str | None = None,
    caption_text: str | None = None,
    recipe: str | None = None,
    review_state: str | None = None,
    readiness_status: str | None = None,
) -> dict[str, Any]:
    conn = connect(root)
    campaign_row = campaign_by_name(conn, campaign) if campaign else None
    output_path = Path(output_path).resolve()
    campaign_output_id = f"out_{slugify(output_path.stem)}"
    conn.execute(
        """
        INSERT INTO campaign_outputs (
            campaign_output_id, campaign_id, asset_generation_id, prompt_run_id,
            output_path, job_key, caption_text, recipe, review_state, readiness_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(output_path) DO UPDATE SET
            campaign_id = COALESCE(excluded.campaign_id, campaign_outputs.campaign_id),
            asset_generation_id = COALESCE(excluded.asset_generation_id, campaign_outputs.asset_generation_id),
            prompt_run_id = COALESCE(excluded.prompt_run_id, campaign_outputs.prompt_run_id),
            job_key = COALESCE(excluded.job_key, campaign_outputs.job_key),
            caption_text = COALESCE(excluded.caption_text, campaign_outputs.caption_text),
            recipe = COALESCE(excluded.recipe, campaign_outputs.recipe),
            review_state = COALESCE(excluded.review_state, campaign_outputs.review_state),
            readiness_status = COALESCE(excluded.readiness_status, campaign_outputs.readiness_status),
            updated_at = excluded.updated_at
        """,
        (
            campaign_output_id,
            campaign_row["campaign_id"] if campaign_row else None,
            asset_generation_id,
            prompt_run_id,
            str(output_path),
            job_key,
            caption_text,
            recipe,
            review_state,
            readiness_status,
            int(time.time()),
            int(time.time()),
        ),
    )
    conn.commit()
    return {"ok": True, "campaign_output_id": campaign_output_id}


def rate_output(
    root: Path,
    *,
    output_path: Path,
    campaign: str | None = None,
    asset_generation_id: str | None = None,
    scores: dict[str, int | None] | None = None,
    labels: list[str] | None = None,
    retry_helper: str | None = None,
    reason: str = "",
    notes: str = "",
    decision: str | None = None,
    primary_reason: str | None = None,
    secondary_reasons: list[str] | None = None,
) -> dict[str, Any]:
    if retry_helper and retry_helper not in VALID_RETRY_HELPERS:
        raise ValueError(f"retry_helper must be one of {sorted(VALID_RETRY_HELPERS)}")
    scores = scores or {}
    decision, primary_reason, secondary_reasons = validate_review(
        decision, primary_reason, secondary_reasons
    )
    for field, value in scores.items():
        if value is not None and (int(value) < 1 or int(value) > 5):
            raise ValueError(f"{field} score must be 1-5")
    conn = connect(root)
    campaign_row = campaign_by_name(conn, campaign) if campaign else None
    rating_id = f"rating_{int(time.time() * 1000)}"
    output_path = Path(output_path).resolve()
    conn.execute(
        """
        INSERT INTO operator_ratings (
            rating_id, output_path, asset_generation_id, campaign_id,
            identity_score, pose_score, taste_score, artifact_score,
            motion_score, caption_score, labels_json, retry_helper,
            approve_reject_reason, notes, created_at, decision, primary_reason,
            secondary_reasons_json, face_score, eyes_score, hands_score,
            pose_accuracy_score, body_taste_score, background_score, crop_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rating_id,
            str(output_path),
            asset_generation_id,
            campaign_row["campaign_id"] if campaign_row else None,
            scores.get("identity"),
            scores.get("pose"),
            scores.get("taste"),
            scores.get("artifacts"),
            scores.get("motion"),
            scores.get("caption"),
            json.dumps(labels or [], ensure_ascii=False),
            retry_helper,
            reason,
            notes,
            int(time.time()),
            decision,
            primary_reason,
            json.dumps(secondary_reasons or [], ensure_ascii=False),
            scores.get("face"),
            scores.get("eyes"),
            scores.get("hands"),
            scores.get("pose_accuracy"),
            scores.get("body_taste"),
            scores.get("background"),
            scores.get("crop"),
        ),
    )
    conn.commit()
    link_campaign_output(
        root,
        output_path=output_path,
        campaign=campaign,
        asset_generation_id=asset_generation_id,
    )
    return {"ok": True, "rating_id": rating_id}


def list_campaigns(root: Path) -> list[dict[str, Any]]:
    conn = connect(root)
    rows = conn.execute(
        """
        SELECT c.*, cr.name AS creator_name
        FROM campaigns c JOIN creators cr ON cr.creator_id = c.creator_id
        ORDER BY c.updated_at DESC, c.name
        """
    ).fetchall()
    return [dict(row) | {"creator": row["creator_name"]} for row in rows]


def taste_memory(root: Path, *, campaign: str | None = None, limit: int = 8) -> str:
    conn = connect(root)
    params: list[Any] = []
    where = ""
    if campaign:
        campaign_row = campaign_by_name(conn, campaign)
        where = "WHERE r.campaign_id=?"
        params.append(campaign_row["campaign_id"])
    rows = conn.execute(
        f"""
        SELECT r.*, co.caption_text, co.recipe
        FROM operator_ratings r
        LEFT JOIN campaign_outputs co ON co.output_path = r.output_path
        {where}
        ORDER BY r.created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    if not rows:
        return ""
    lessons = []
    for row in rows:
        labels = ", ".join(json.loads(row["labels_json"] or "[]")) or "no_labels"
        scores = ", ".join(
            f"{name}={row[col]}"
            for name, col in [
                ("identity", "identity_score"),
                ("pose", "pose_score"),
                ("taste", "taste_score"),
                ("artifacts", "artifact_score"),
                ("motion", "motion_score"),
                ("caption", "caption_score"),
            ]
            if row[col] is not None
        )
        lessons.append(
            f"- labels: {labels}; scores: {scores}; notes: {row['notes'] or row['approve_reject_reason'] or ''}".strip()
        )
    return "Recent operator taste lessons:\n" + "\n".join(lessons)


def campaign_leaderboard(root: Path, *, campaign: str) -> dict[str, Any]:
    conn = connect(root)
    campaign_row = campaign_by_name(conn, campaign)
    rows = conn.execute(
        """
        SELECT co.recipe, co.caption_text, co.output_path, r.labels_json,
               r.identity_score, r.pose_score, r.taste_score, r.artifact_score,
               r.motion_score, r.caption_score, o.views, o.likes, o.comments,
               o.shares, o.saves, o.manual_score
        FROM campaign_outputs co
        LEFT JOIN operator_ratings r ON r.output_path = co.output_path
        LEFT JOIN reel_outcomes o
          ON o.campaign_output_id = co.campaign_output_id
          OR (
              o.campaign_output_id IS NULL
              AND o.job_key IS NOT NULL
              AND co.job_key IS NOT NULL
              AND o.job_key = co.job_key
          )
          OR (
              o.campaign_output_id IS NULL
              AND (o.job_key IS NULL OR co.job_key IS NULL)
              AND (
                  o.filename = co.metrics_filename
                  OR substr(co.output_path, length(co.output_path) - length(o.filename) + 1) = o.filename
              )
          )
        WHERE co.campaign_id=?
        """,
        (campaign_row["campaign_id"],),
    ).fetchall()
    label_counts: dict[str, int] = {}
    recipe_scores: dict[str, list[float]] = {}
    outputs = []
    for row in rows:
        labels = json.loads(row["labels_json"] or "[]") if row["labels_json"] else []
        for label in labels:
            label_counts[label] = label_counts.get(label, 0) + 1
        score = row["manual_score"] if row["manual_score"] is not None else row["views"]
        if score is None:
            score = sum(
                v
                for v in [
                    row["identity_score"],
                    row["pose_score"],
                    row["taste_score"],
                    row["motion_score"],
                ]
                if v
            )
        score = float(score or 0)
        if row["recipe"]:
            recipe_scores.setdefault(row["recipe"], []).append(score)
        outputs.append(
            {
                "output_path": row["output_path"],
                "recipe": row["recipe"],
                "score": score,
                "labels": labels,
            }
        )
    return {
        "campaign": campaign_row["name"],
        "best_recipes": sorted(
            [
                {"recipe": k, "score": round(sum(v) / len(v), 2), "count": len(v)}
                for k, v in recipe_scores.items()
            ],
            key=lambda item: item["score"],
            reverse=True,
        ),
        "labels": sorted(label_counts.items(), key=lambda item: item[1], reverse=True),
        "top_outputs": sorted(outputs, key=lambda item: item["score"], reverse=True)[
            :10
        ],
        "worst_failure_patterns": [
            {"label": label, "count": count}
            for label, count in sorted(
                label_counts.items(), key=lambda item: item[1], reverse=True
            )
            if label.endswith("_bad")
            or label
            in {
                "pose_drift",
                "too_smiley",
                "too_generic",
                "not_sexy_enough",
                "artifact_bad",
                "hand_bad",
            }
        ],
    }


def _default_recipe_names(root: Path) -> list[str]:
    path = Path(root).resolve() / "recipes" / "default.json"
    if not path.exists():
        path = Path(__file__).resolve().parent / "recipes" / "default.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(DEFAULT_RECIPE_HINTS)
    recipes = [
        item.get("name")
        for item in data
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    return recipes or list(DEFAULT_RECIPE_HINTS)


def _engagement_rate_reward(row: sqlite3.Row) -> float:
    views = max(float(row["views"] or 0), 1.0)
    engagements = sum(
        float(row[metric] or 0) for metric in ("likes", "comments", "shares", "saves")
    )
    return max(0.0, min(1.0, engagements / views))


def _recipe_bandit_state(
    conn: sqlite3.Connection, root: Path, *, campaign_id: str
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT co.recipe, o.views, o.likes, o.comments, o.shares, o.saves
        FROM campaign_outputs co
        JOIN reel_outcomes o
          ON o.campaign_output_id = co.campaign_output_id
          OR (
              o.campaign_output_id IS NULL
              AND o.job_key IS NOT NULL
              AND co.job_key IS NOT NULL
              AND o.job_key = co.job_key
          )
          OR (
              o.campaign_output_id IS NULL
              AND (o.job_key IS NULL OR co.job_key IS NULL)
              AND (
                  o.filename = co.metrics_filename
                  OR substr(co.output_path, length(co.output_path) - length(o.filename) + 1) = o.filename
              )
          )
        WHERE co.campaign_id=? AND co.recipe IS NOT NULL
        """,
        (campaign_id,),
    ).fetchall()
    recipes = {
        str(row["recipe"])
        for row in conn.execute(
            """
            SELECT DISTINCT recipe
            FROM campaign_outputs
            WHERE campaign_id=? AND recipe IS NOT NULL AND recipe != ''
            """,
            (campaign_id,),
        ).fetchall()
    }
    recipes.update(_default_recipe_names(root))
    rewards: dict[str, list[float]] = {recipe: [] for recipe in recipes}
    for row in rows:
        rewards.setdefault(str(row["recipe"]), []).append(_engagement_rate_reward(row))
    arms = []
    for recipe in sorted(rewards):
        rates = rewards[recipe]
        alpha = 1.0 + sum(rates)
        beta = 1.0 + sum(1.0 - rate for rate in rates)
        arms.append(
            {
                "recipe": recipe,
                "alpha": round(alpha, 6),
                "beta": round(beta, 6),
                "post_count": len(rates),
                "mean_reward": round(sum(rates) / len(rates), 6) if rates else None,
            }
        )
    return {
        "mode": "thompson_beta_engagement_rate",
        "metric_posts": len(rows),
        "arms": arms,
    }


def _draw_recipe_from_bandit(
    state: dict[str, Any], rng: random.Random
) -> tuple[str, dict[str, Any]]:
    samples = {
        arm["recipe"]: rng.betavariate(float(arm["alpha"]), float(arm["beta"]))
        for arm in state["arms"]
    }
    chosen = max(sorted(samples), key=lambda recipe: samples[recipe])
    chosen_arm = next(arm for arm in state["arms"] if arm["recipe"] == chosen)
    metadata = {
        "mode": state["mode"],
        "chosen_recipe": chosen,
        "chosen_alpha": chosen_arm["alpha"],
        "chosen_beta": chosen_arm["beta"],
        "chosen_post_count": chosen_arm["post_count"],
        "sampled_theta": round(samples[chosen], 6),
        "samples": {recipe: round(theta, 6) for recipe, theta in samples.items()},
        "arms": state["arms"],
    }
    return chosen, metadata


def next_batch_plan(
    root: Path,
    *,
    campaign: str,
    count: int = 20,
    persist: bool = False,
    rng: random.Random | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    if rng is None:
        rng = random.Random(seed)
    board = campaign_leaderboard(root, campaign=campaign)
    reject_labels = {item["label"] for item in board["worst_failure_patterns"]}
    best_recipes = [item["recipe"] for item in board["best_recipes"][:3]] or list(
        DEFAULT_RECIPE_HINTS
    )
    conn = connect(root)
    campaign_row = campaign_by_name(conn, campaign)
    bandit_state = _recipe_bandit_state(
        conn, root, campaign_id=campaign_row["campaign_id"]
    )
    use_bandit = bool(bandit_state["metric_posts"] and bandit_state["arms"])
    total_outcomes = int(
        conn.execute("SELECT COUNT(*) AS n FROM reel_outcomes").fetchone()["n"] or 0
    )
    feature_placeholders = ",".join("?" for _ in FEATURE_KEYS)
    dna_rows = conn.execute(
        f"""
        SELECT feature_key, feature_value, avg_winner_score, sample_size
        FROM winner_dna
        WHERE feature_key IN ({feature_placeholders})
        ORDER BY avg_winner_score DESC, sample_size DESC
        LIMIT 8
        """,
        FEATURE_KEYS,
    ).fetchall()
    winner_dna_focus = [
        dict(row)
        | {
            "confidence": confidence_for_sample_size(
                row["sample_size"], total_outcomes=total_outcomes
            )
        }
        for row in dna_rows
    ]
    recommendation = _next_batch_recommendation(winner_dna_focus, total_outcomes)
    data_quality = data_quality_from_connection(
        conn, matched_sample_size=int(recommendation["sample_size"] or 0)
    )
    recommendation["data_quality"] = data_quality
    items = []
    for idx in range(count):
        retry_focus = "more_reference_fidelity"
        if "hands_bad" in reject_labels or "hand_bad" in reject_labels:
            retry_focus = "fix_hands"
        elif "pose_drift" in reject_labels:
            retry_focus = "fix_pose"
        elif "too_smiley" in reject_labels:
            retry_focus = "less_smile"
        elif "not_sexy_enough" in reject_labels:
            retry_focus = "more_body_emphasis"
        if use_bandit:
            recipe_hint, recipe_bandit = _draw_recipe_from_bandit(bandit_state, rng)
        else:
            recipe_hint = best_recipes[idx % len(best_recipes)]
            recipe_bandit = {
                "mode": "cold_start_round_robin",
                "chosen_recipe": recipe_hint,
                "arms": bandit_state["arms"],
                "metric_posts": bandit_state["metric_posts"],
            }
        recommendation_id = f"local_next_batch_{campaign_row['campaign_id']}_{idx + 1}"
        item = {
            "recommendationId": recommendation_id,
            "recommendationGraphId": None,
            "status": "proposed",
            "campaignGraphId": None,
            "rank": idx + 1,
            "score": int(recommendation.get("score") or 0),
            "confidence": recommendation["confidence"],
            "confidenceReason": recommendation.get("reason") or "",
            "targetAccount": None,
            "suggestedRecipe": recipe_hint,
            "hookGuidance": retry_focus,
            "captionGuidance": _next_batch_brief(winner_dna_focus),
            "reasons": [str(recommendation.get("reason") or "local winner DNA")],
            "risks": [low_data_warning(total_outcomes)]
            if low_data_warning(total_outcomes)
            else [],
            "scoreBreakdown": {
                "winnerDnaScore": int(recommendation.get("score") or 0),
                "sampleSize": int(recommendation.get("sample_size") or 0),
            },
            "graphEvidence": {
                "source": "reel_factory.local_next_batch",
                "recipeBandit": recipe_bandit,
                "winnerDnaFocus": winner_dna_focus,
            },
        }
        item.update(
            {
                "index": idx,
                "campaign": campaign,
                "recipe_hint": recipe_hint,
                "recipe_bandit": recipe_bandit,
                "prompt_focus": retry_focus,
                "avoid_labels": sorted(reject_labels),
                "winner_dna_focus": winner_dna_focus,
                "recommendation": recommendation,
                "confidence": recommendation["confidence"],
                "data_quality": data_quality,
                "low_data_warning": low_data_warning(total_outcomes),
                "brief": _next_batch_brief(winner_dna_focus),
            }
        )
        items.append(item)
    input_hash = hashlib.sha256(
        json.dumps(items, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    plan = {
        "schema": "campaign_factory.recommendations.next_batch.v1",
        "campaign": campaign,
        "campaignGraphId": None,
        "persisted": bool(persist),
        "scoringVersion": "reel_factory.local_next_batch.v3",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(items),
        "requestedCount": count,
        "inputHash": input_hash,
        "items": items,
        "ideas": items,
        "recipe_bandit": bandit_state
        | {"active": use_bandit, "fallback_recipes": best_recipes},
    }
    validate_recommendation_next_batch(plan)
    if persist:
        from .winner_dna import persist_recommendation_decision

        decision_id = persist_recommendation_decision(
            root,
            campaign=campaign,
            plan=plan,
            rejection_patterns=board["worst_failure_patterns"],
        )
        if decision_id:
            plan["decision_id"] = decision_id
            for idea in items:
                idea["decision_id"] = decision_id
                idea["recommendation"]["decision_id"] = decision_id
    return plan


def _next_batch_brief(winner_dna_focus: list[dict[str, Any]]) -> str:
    if not winner_dna_focus:
        return "Use proven reference-faithful Stacey generation patterns with exact pose and recent winner labels."
    by_key: dict[str, str] = {}
    for row in winner_dna_focus:
        if row.get("feature_key") and row.get("feature_value"):
            by_key.setdefault(row["feature_key"], row["feature_value"])
    parts = [
        by_key.get(key)
        for key in ("scene", "pose", "motion", "outfit")
        if by_key.get(key)
    ]
    if not parts:
        return "Use proven reference-faithful Stacey generation patterns with exact pose and recent winner labels."
    return (
        "Lean into Winner DNA: "
        + " / ".join(parts)
        + ". Keep the selected Soul ID and recent winner labels."
    )


def _next_batch_recommendation(
    winner_dna_focus: list[dict[str, Any]], total_outcomes: int
) -> dict[str, Any]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in winner_dna_focus:
        if row.get("feature_key") and row.get("feature_value"):
            by_key.setdefault(row["feature_key"], row)
    ordered = [
        by_key.get(key)
        for key in ("scene", "pose", "motion", "outfit")
        if by_key.get(key)
    ]
    sample_size = min((int(row["sample_size"] or 0) for row in ordered), default=0)
    confidence = confidence_for_sample_size(sample_size, total_outcomes=total_outcomes)
    return {
        "pattern": " / ".join(str(row["feature_value"]) for row in ordered)
        if ordered
        else "",
        "confidence": confidence["level"],
        "confidence_reason": confidence["reason"],
        "sample_size": sample_size,
        "total_outcomes": total_outcomes,
    }


def cli_main() -> int:
    ap = argparse.ArgumentParser(description="Campaign Factory database utilities.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create")
    create.add_argument("--root", default=".")
    create.add_argument("--name", required=True)
    create.add_argument("--creator", required=True)
    create.add_argument("--account", required=True)
    create.add_argument("--platform", required=True)
    create.add_argument("--content-angle", default="")
    create.add_argument("--notes", default="")
    ref = sub.add_parser("add-reference")
    ref.add_argument("--root", default=".")
    ref.add_argument("--campaign", required=True)
    ref.add_argument("--reference-reel")
    ref.add_argument("--reference-image")
    ref.add_argument("--visual-tags", default="")
    ref.add_argument("--intended-pose", default="")
    ref.add_argument("--intended-outfit", default="")
    ref.add_argument("--intended-scene", default="")
    ref.add_argument("--notes", default="")
    list_p = sub.add_parser("list")
    list_p.add_argument("--root", default=".")
    board = sub.add_parser("leaderboard")
    board.add_argument("--root", default=".")
    board.add_argument("--campaign", required=True)
    args = ap.parse_args()

    root = Path(getattr(args, "root", "."))
    if args.cmd == "create":
        result = create_campaign(
            root,
            name=args.name,
            creator=args.creator,
            account=args.account,
            platform=args.platform,
            content_angle=args.content_angle,
            notes=args.notes,
        )
    elif args.cmd == "add-reference":
        source = args.reference_reel or args.reference_image
        if not source:
            raise SystemExit("--reference-reel or --reference-image is required")
        result = add_reference(
            root,
            campaign=args.campaign,
            source_path=Path(source),
            visual_tags=[x.strip() for x in args.visual_tags.split(",") if x.strip()],
            intended_pose=args.intended_pose,
            intended_outfit=args.intended_outfit,
            intended_scene=args.intended_scene,
            notes=args.notes,
        )
    elif args.cmd == "list":
        result = {"campaigns": list_campaigns(root)}
    else:
        result = campaign_leaderboard(root, campaign=args.campaign)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
