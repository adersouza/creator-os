#!/usr/bin/env python3
"""Derived media-feature persistence for Reel Factory worker outputs.

Winner computation and experiment ownership belong to Campaign Factory.
This module stores only features derived from local render evidence.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from reel_factory.sqlite_utils import connect_sqlite

from .audio_intent import read_audio_intent
from .caption_bank import caption_static_metadata
from .evidence_store import ensure_evidence_schema
from .feature_extract import FEATURE_KEYS, extract_features, features_from_lineage
from .intelligence_store import ensure_intelligence_schema
from .state_paths import manifest_db_path


def connect(root: Path) -> sqlite3.Connection:
    conn = connect_sqlite(manifest_db_path(root))
    ensure_intelligence_schema(conn)
    ensure_evidence_schema(conn)
    return conn


def infer_features_from_text(text: str) -> dict[str, Any]:
    features = extract_features(text)
    low = text.lower()
    features["grid_source"] = 1 if "grid" in low or "panel" in low else 0
    return features


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def video_analysis_features_for_output(
    root: Path, output_path: Path
) -> dict[str, Any] | None:
    _ = root
    candidates = (
        output_path.with_suffix(output_path.suffix + ".video_analysis.json"),
        output_path.with_suffix(".video_analysis.json"),
        output_path.parent / f"{output_path.stem}.video_analysis.json",
    )
    for path in candidates:
        report = _read_json(path)
        if not report:
            continue
        explicit = report.get("winner_dna_features")
        if not isinstance(explicit, dict):
            explicit = report.get("winnerDnaFeatures")
        if not isinstance(explicit, dict):
            explicit = (report.get("signals") or {}).get("winner_dna_features")
        if not isinstance(explicit, dict):
            explicit = (report.get("raw") or {}).get("winner_dna_features")
        if not isinstance(explicit, dict):
            continue
        features = {
            key: explicit.get(key)
            or explicit.get(
                "".join(
                    [key.split("_")[0], *[part.title() for part in key.split("_")[1:]]]
                )
            )
            or "unknown"
            for key in FEATURE_KEYS
        }
        features["grid_source"] = int(bool(explicit.get("grid_source")))
        features["feature_source"] = "video_analysis"
        return features
    return None


def feature_text_for_output(root: Path, output_path: Path) -> str:
    parts = [output_path.stem.replace("_", " ")]
    for path in (
        output_path.with_suffix(output_path.suffix + ".generated_asset_lineage.json"),
        output_path.with_suffix(".generated_asset_lineage.json"),
        root / "00_source_videos" / f"{output_path.stem}.generated_asset_lineage.json",
    ):
        payload = _read_json(path)
        if payload:
            parts.append(json.dumps(features_from_lineage(payload), ensure_ascii=False))
            parts.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(parts)


def upsert_reel_feature(
    root: Path,
    output_path: Path,
    *,
    asset_generation_id: str | None = None,
    campaign_id: str | None = None,
    source_reference_id: str | None = None,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    output_path = Path(output_path).expanduser().resolve()
    conn = connect(root)
    resolved = features or video_analysis_features_for_output(root, output_path)
    if resolved is None:
        resolved = infer_features_from_text(feature_text_for_output(root, output_path))
    row = conn.execute(
        """
        SELECT creator_key, caption_text FROM campaign_outputs
        WHERE output_path = ? ORDER BY updated_at DESC LIMIT 1
        """,
        (str(output_path),),
    ).fetchone()
    if row:
        if resolved.get("creator") in (None, "", "unknown") and row["creator_key"]:
            resolved["creator"] = str(row["creator_key"]).lower()
        if (
            resolved.get("caption_style") in (None, "", "unknown")
            and row["caption_text"]
        ):
            caption_lineage = _read_json(
                output_path.with_suffix(output_path.suffix + ".caption_lineage.json")
            )
            context = (
                caption_lineage.get("captionOutcomeContext")
                if isinstance(caption_lineage, dict)
                else None
            )
            if (
                isinstance(context, dict)
                and context.get("length_class")
                and context.get("format_class")
            ):
                resolved["caption_style"] = (
                    f"{context['length_class']}_{context['format_class']}"
                )
            else:
                caption = caption_static_metadata(str(row["caption_text"]))
                resolved["caption_style"] = (
                    f"{caption['length_class']}_{caption['format_class']}"
                )
    audio_intent = read_audio_intent(output_path)
    selection = (
        audio_intent.get("audio_selection") if isinstance(audio_intent, dict) else None
    )
    if isinstance(selection, dict) and selection.get("track_id"):
        resolved["audio_track_id"] = str(selection["track_id"])
    now = int(time.time())
    feature_id = f"feat_{abs(hash(str(output_path))) & 0xFFFFFFFF:x}"
    conn.execute(
        """
        INSERT INTO reel_features (
            feature_id, output_path, asset_generation_id, campaign_id, source_reference_id,
            scene, camera, pose, motion, outfit, creator, grid_source, caption_style,
            hook_type, audio_track_id, body_style, features_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(output_path) DO UPDATE SET
            asset_generation_id=COALESCE(excluded.asset_generation_id, reel_features.asset_generation_id),
            campaign_id=COALESCE(excluded.campaign_id, reel_features.campaign_id),
            source_reference_id=COALESCE(excluded.source_reference_id, reel_features.source_reference_id),
            scene=excluded.scene, camera=excluded.camera, pose=excluded.pose,
            motion=excluded.motion, outfit=excluded.outfit, creator=excluded.creator,
            grid_source=excluded.grid_source, caption_style=excluded.caption_style,
            hook_type=excluded.hook_type, audio_track_id=excluded.audio_track_id,
            body_style=excluded.body_style, features_json=excluded.features_json,
            updated_at=excluded.updated_at
        """,
        (
            feature_id,
            str(output_path),
            asset_generation_id,
            campaign_id,
            source_reference_id,
            resolved.get("scene"),
            resolved.get("camera"),
            resolved.get("pose"),
            resolved.get("motion"),
            resolved.get("outfit"),
            resolved.get("creator"),
            int(bool(resolved.get("grid_source"))),
            resolved.get("caption_style"),
            resolved.get("hook_type"),
            resolved.get("audio_track_id"),
            resolved.get("body_style"),
            json.dumps(resolved, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    conn.commit()
    return {"ok": True, "feature_id": feature_id, "features": resolved}


def refresh_features(root: Path, *, limit: int | None = None) -> dict[str, Any]:
    conn = connect(root)
    rows = conn.execute(
        "SELECT output_path, asset_generation_id, campaign_key FROM campaign_outputs ORDER BY created_at DESC"
    ).fetchall()
    refreshed = 0
    for row in rows[:limit] if limit else rows:
        if conn.execute(
            "SELECT 1 FROM reel_features WHERE output_path = ?", (row["output_path"],)
        ).fetchone():
            continue
        upsert_reel_feature(
            root,
            Path(row["output_path"]),
            asset_generation_id=row["asset_generation_id"],
            campaign_id=row["campaign_key"],
        )
        refreshed += 1
    return {"ok": True, "features_refreshed": refreshed}
