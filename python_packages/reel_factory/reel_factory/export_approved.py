"""Export approved outputs into a local posting manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from campaign_store import ensure_campaign_schema
from readiness_check import load_readiness_for_output, normalize_platform

from reel_factory.perceptual import enrich_lineage_identity
from reel_factory.sqlite_utils import connect_sqlite


def export_approved(
    root: Path,
    *,
    account: str,
    platform: str,
    date: str,
    notes: str | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    db_path = root / "manifest.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"manifest.sqlite not found under {root}")
    conn = connect_sqlite(db_path)
    ensure_campaign_schema(conn)
    _ensure_variations_filename(conn)
    rows = conn.execute("""
        SELECT
            v.job_key,
            v.recipe,
            v.recipe_params_json,
            v.caption_text,
            v.output_path,
            v.review_state,
            co.campaign_id,
            co.asset_generation_id,
            m.views,
            m.likes,
            m.comments,
            m.shares,
            m.saves,
            m.manual_score,
            m.notes AS metric_notes
        FROM variations v
        LEFT JOIN campaign_outputs co
            ON co.output_path = v.output_path
        LEFT JOIN publish_metrics m
            ON m.campaign_output_id = co.campaign_output_id
            OR (
                m.campaign_output_id IS NULL
                AND m.job_key IS NOT NULL
                AND v.job_key IS NOT NULL
                AND m.job_key = v.job_key
            )
            OR (
                m.campaign_output_id IS NULL
                AND (m.job_key IS NULL OR v.job_key IS NULL)
                AND (
                    m.filename = v.filename
                    OR (
                        (v.filename IS NULL OR v.filename = '')
                        AND substr(v.output_path, length(v.output_path) - length(m.filename) + 1) = m.filename
                    )
                )
            )
        WHERE v.status = 'ok' AND v.review_state = 'approved'
        ORDER BY v.encoded_at, v.output_path
    """).fetchall()
    items = []
    for idx, row in enumerate(rows):
        output_path = Path(row["output_path"])
        recipe_params = json.loads(row["recipe_params_json"])
        audio_intent = _load_audio_intent_sidecar(output_path)
        generated_asset_lineage = _ensure_generated_asset_lineage(output_path)
        fingerprint = generated_asset_lineage["contentFingerprint"]
        try:
            platform_readiness = load_readiness_for_output(
                output_path, platform=normalize_platform(platform)
            )
        except ValueError:
            platform_readiness = load_readiness_for_output(output_path)
        audio_workflow = {
            "final_audio_mode": "native_platform_audio",
            "local_muxing_is_preview_only": True,
        }
        if audio_intent:
            audio_workflow["audio_intent_preserved"] = True
        else:
            audio_workflow["warning"] = "missing_audio_intent"
        items.append(
            {
                "index": idx,
                "account": account,
                "platform": platform,
                "scheduled_date": date,
                "scheduled_time": None,
                "filename": output_path.name,
                "output_path": str(output_path),
                "content_fingerprint": fingerprint,
                "job_key": row["job_key"],
                "hook_index": _hook_idx(output_path.name),
                "hook_text": row["caption_text"],
                "recipe": row["recipe"],
                "target_ratio": recipe_params.get("_target_ratio")
                or _ratio_from_filename(output_path.name),
                "review_state": row["review_state"],
                "metrics": {
                    "views": row["views"],
                    "likes": row["likes"],
                    "comments": row["comments"],
                    "shares": row["shares"],
                    "saves": row["saves"],
                    "manual_score": row["manual_score"],
                },
                "audio_intent": audio_intent,
                "audio_workflow": audio_workflow,
                "generated_asset_lineage": generated_asset_lineage,
                "platform_readiness": platform_readiness,
                "campaign": {
                    "campaign_id": row["campaign_id"],
                    "asset_generation_id": row["asset_generation_id"],
                }
                if row["campaign_id"] or row["asset_generation_id"]
                else None,
                "notes": row["metric_notes"] or notes,
            }
        )
    out_dir = root / "04_exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"approved_{platform}_{account}_{date}_{int(time.time())}.json"
    payload = {
        "schema": "reel_factory.approved_export.v1",
        "exported_at": int(time.time()),
        "account": account,
        "platform": platform,
        "date": date,
        "count": len(items),
        "items": items,
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"ok": True, "count": len(items), "path": str(out_path), "items": items}


def _ensure_variations_filename(conn) -> None:
    existing = {
        row["name"] for row in conn.execute("PRAGMA table_info(variations)").fetchall()
    }
    if "filename" not in existing:
        conn.execute("ALTER TABLE variations ADD COLUMN filename TEXT")
    rows = conn.execute(
        "SELECT job_key, output_path FROM variations WHERE filename IS NULL OR filename = ''"
    ).fetchall()
    conn.executemany(
        "UPDATE variations SET filename = ? WHERE job_key = ?",
        [(Path(row["output_path"]).name, row["job_key"]) for row in rows],
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_variations_filename ON variations(filename)"
    )


def _hook_idx(filename: str) -> int:
    for part in Path(filename).stem.split("_"):
        if part.startswith("h") and part[1:].isdigit():
            return int(part[1:])
    return -1


def _ratio_from_filename(filename: str) -> str:
    return "4:5" if "_4x5_" in filename else "9:16"


def _load_audio_intent_sidecar(output_path: Path) -> dict[str, Any] | None:
    return _load_json_sidecar(output_path, "audio_intent")


def _load_generated_asset_lineage_sidecar(output_path: Path) -> dict[str, Any] | None:
    return _load_json_sidecar(output_path, "generated_asset_lineage")


def _ensure_generated_asset_lineage(output_path: Path) -> dict[str, Any]:
    existing = _load_generated_asset_lineage_sidecar(output_path) or {
        "schema": "reel_factory.generated_asset_lineage.v1",
        "pipelineTraceId": "trace_reel_export_"
        + hashlib.sha256(str(output_path.resolve()).encode()).hexdigest()[:16],
        "source": {},
        "generation": {"tool": "reel_factory.export_approved"},
        "review": {"humanReviewRequired": True},
    }
    enriched = enrich_lineage_identity(existing, output_path)
    sidecar = output_path.with_suffix(
        output_path.suffix + ".generated_asset_lineage.json"
    )
    sidecar.write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return enriched


def _load_json_sidecar(output_path: Path, suffix: str) -> dict[str, Any] | None:
    candidates = [
        output_path.with_suffix(output_path.suffix + f".{suffix}.json"),
        output_path.with_suffix(f".{suffix}.json"),
        output_path.parent / f"{output_path.stem}.{suffix}.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--account", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()
    print(
        json.dumps(
            export_approved(
                Path(args.root),
                account=args.account,
                platform=args.platform,
                date=args.date,
                notes=args.notes,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
