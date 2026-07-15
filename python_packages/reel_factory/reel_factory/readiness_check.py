#!/usr/bin/env python3
"""Warn-only platform readiness aggregation for rendered reel outputs."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from reel_factory.sqlite_utils import connect_sqlite

from .audio_intent import read_audio_intent
from .post_render_acceptance import acceptance_from_readiness
from .safe_zone import score_safe_zone
from .state_paths import manifest_db_path
from .virality_qc import evaluate_output_virality

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "instagram_reels": {
        "preferred_ratio": "9:16",
        "min_resolution_px": 720,
        "requires_audio_intent": True,
        "requires_lineage": True,
        "strict_text_review": False,
    },
    "instagram_feed": {
        "preferred_ratio": "4:5",
        "min_resolution_px": 720,
        "requires_audio_intent": False,
        "requires_lineage": True,
        "strict_text_review": False,
    },
    "instagram_square": {
        "preferred_ratio": "1:1",
        "min_resolution_px": 720,
        "requires_audio_intent": False,
        "requires_lineage": True,
        "strict_text_review": False,
    },
    "tiktok": {
        "preferred_ratio": "9:16",
        "min_resolution_px": 720,
        "requires_audio_intent": True,
        "requires_lineage": True,
        "strict_text_review": True,
    },
}


def normalize_platform(platform: str) -> str:
    aliases = {
        "ig": "instagram_reels",
        "instagram": "instagram_reels",
        "reels": "instagram_reels",
        "feed": "instagram_feed",
        "instagram_portrait": "instagram_feed",
        "square": "instagram_square",
        "carousel": "instagram_square",
    }
    value = aliases.get(platform, platform)
    if value not in PLATFORM_PROFILES:
        raise ValueError(f"platform must be one of {sorted(PLATFORM_PROFILES)}")
    return value


def readiness_path(clip_dir: Path) -> Path:
    return clip_dir / "_readiness.json"


def load_readiness_by_name(
    clip_dir: Path, *, platform: str | None = None
) -> dict[str, dict[str, Any]]:
    path = readiness_path(clip_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    payload_platform = payload.get("platform")
    rows = payload.get("records") or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("filename"):
            continue
        row_platform = row.get("platform") or payload_platform
        if platform and row_platform != platform:
            continue
        if row_platform and "platform" not in row:
            row = {**row, "platform": row_platform}
        out[str(row["filename"])] = row
    return out


def load_readiness_for_output(
    output_path: Path, *, platform: str | None = None
) -> dict[str, Any] | None:
    rows = load_readiness_by_name(output_path.parent, platform=platform)
    return rows.get(output_path.name)


def _json_sidecar(output_path: Path, suffix: str) -> dict[str, Any] | None:
    for candidate in (
        output_path.with_suffix(output_path.suffix + f".{suffix}.json"),
        output_path.with_suffix(f".{suffix}.json"),
        output_path.parent / f"{output_path.stem}.{suffix}.json",
    ):
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _source_lineage_exists(root: Path, clip: str, output_path: Path) -> bool:
    source_lineage = root / "00_source_videos" / f"{clip}.generated_asset_lineage.json"
    if source_lineage.exists():
        return True
    per_output = _json_sidecar(output_path, "generated_asset_lineage")
    if not per_output:
        return False
    linked = (per_output.get("source") or {}).get("sourceLineagePath")
    return bool(linked and Path(str(linked)).exists())


def _load_ai_qc(clip_dir: Path) -> dict[str, dict[str, Any]]:
    path = clip_dir / "_ai_qc.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(row["filename"]): row
        for row in payload.get("records") or []
        if isinstance(row, dict) and row.get("filename")
    }


def _manifest_rows(root: Path) -> dict[str, dict[str, Any]]:
    db = manifest_db_path(root)
    if not db.exists():
        return {}
    conn = connect_sqlite(db)
    try:
        rows = conn.execute(
            "SELECT output_path, recipe_params_json, status FROM variations"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[Path(row["output_path"]).name] = dict(row)
    return out


def _ratio_from_filename(filename: str) -> str:
    if "_1x1_" in filename:
        return "1:1"
    return "4:5" if "_4x5_" in filename else "9:16"


def _probe_dimensions(path: Path) -> tuple[int, int] | tuple[None, None]:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except Exception:
        return None, None


def evaluate_output(
    *,
    root: Path,
    clip: str,
    output_path: Path,
    platform: str,
    manifest_row: dict[str, Any] | None = None,
    ai_qc: dict[str, Any] | None = None,
    dimensions: tuple[int | None, int | None] | None = None,
    require_virality: bool = False,
) -> dict[str, Any]:
    platform = normalize_platform(platform)
    profile = PLATFORM_PROFILES[platform]
    warnings: list[str] = []
    not_ready = False
    if not output_path.exists():
        warnings.append("missing_output_file")
        not_ready = True

    recipe_params: dict[str, Any] = {}
    if manifest_row:
        try:
            recipe_params = json.loads(manifest_row.get("recipe_params_json") or "{}")
        except Exception:
            recipe_params = {}
    surface = recipe_params.get("_surface") or recipe_params.get("surface") or platform
    target_ratio = (
        recipe_params.get("_target_ratio")
        or recipe_params.get("aspect_ratio")
        or _ratio_from_filename(output_path.name)
    )
    if target_ratio != profile["preferred_ratio"]:
        warnings.append(f"non_preferred_ratio_{target_ratio.replace(':', 'x')}")

    width, height = (
        dimensions if dimensions is not None else _probe_dimensions(output_path)
    )
    if width and height and min(width, height) < int(profile["min_resolution_px"]):
        warnings.append("resolution_below_platform_minimum")

    safe_zone = score_safe_zone(width=width, height=height, platform=platform)
    warnings.extend(safe_zone.get("warnings") or [])
    if safe_zone.get("safeZoneStatus") == "warn":
        warnings.append("safe_zone_review_needed")

    audio_intent = read_audio_intent(output_path)
    if profile["requires_audio_intent"] and not audio_intent:
        warnings.append("missing_audio_intent")

    if profile["requires_lineage"] and not _source_lineage_exists(
        root, clip, output_path
    ):
        warnings.append("missing_generated_asset_lineage")

    ai_warnings = list((ai_qc or {}).get("warnings") or [])
    warnings.extend(f"ai_qc:{w}" for w in ai_warnings)
    if profile["strict_text_review"] and any(
        "text" in w or "watermark" in w for w in ai_warnings
    ):
        warnings.append("tiktok_text_watermark_review")

    virality_qc = evaluate_output_virality(output_path, required=require_virality)
    if virality_qc:
        warnings.extend(virality_qc.get("warnings") or [])
        if virality_qc.get("status") == "failed":
            not_ready = True

    warnings = sorted(set(warnings))
    status = "not_ready" if not_ready else ("warn" if warnings else "ready")
    score = max(0, 100 - 10 * len(warnings) - (30 if not_ready else 0))
    return {
        "filename": output_path.name,
        "path": str(output_path),
        "platform": platform,
        "surface": surface,
        "status": status,
        "score": score,
        "warnings": warnings,
        "reviewAuthority": "campaign_factory",
        "targetRatio": target_ratio,
        "dimensions": {"width": width, "height": height},
        "audioIntent": audio_intent,
        "safeZone": safe_zone,
        "aiQc": ai_qc,
        "viralityQc": virality_qc,
        "lineagePresent": _source_lineage_exists(root, clip, output_path),
    }


def run_readiness(
    root: Path,
    *,
    clip: str | None = None,
    platform: str = "instagram_reels",
    require_virality: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    platform = normalize_platform(platform)
    proc = root / "02_processed"
    clip_dirs = (
        [proc / clip]
        if clip
        else [
            p
            for p in sorted(proc.iterdir())
            if p.is_dir() and not p.name.startswith("_")
        ]
    )
    manifest = _manifest_rows(root)
    reports: list[str] = []
    all_records: list[dict[str, Any]] = []
    for clip_dir in clip_dirs:
        if not clip_dir.exists():
            continue
        ai_qc = _load_ai_qc(clip_dir)
        records = [
            evaluate_output(
                root=root,
                clip=clip_dir.name,
                output_path=path,
                platform=platform,
                manifest_row=manifest.get(path.name),
                ai_qc=ai_qc.get(path.name),
                require_virality=require_virality,
            )
            for path in sorted(clip_dir.glob("*.mp4"))
            if "_audio_" not in path.stem
        ]
        for record in records:
            record["postRenderAcceptance"] = acceptance_from_readiness(record)
        payload = {
            "schema": "reel_factory.readiness.v1",
            "createdAt": int(time.time()),
            "clip": clip_dir.name,
            "platform": platform,
            "profile": PLATFORM_PROFILES[platform],
            "requireVirality": bool(require_virality),
            "summary": {
                "total": len(records),
                "ready": sum(1 for row in records if row["status"] == "ready"),
                "warn": sum(1 for row in records if row["status"] == "warn"),
                "not_ready": sum(1 for row in records if row["status"] == "not_ready"),
            },
            "records": records,
        }
        path = readiness_path(clip_dir)
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        reports.append(str(path))
        all_records.extend(records)
    return {
        "schema": "reel_factory.readiness_summary.v1",
        "platform": platform,
        "requireVirality": bool(require_virality),
        "summary": {
            "total": len(all_records),
            "ready": sum(1 for row in all_records if row["status"] == "ready"),
            "warn": sum(1 for row in all_records if row["status"] == "warn"),
            "not_ready": sum(1 for row in all_records if row["status"] == "not_ready"),
        },
        "reports": reports,
        "records": all_records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--clip")
    ap.add_argument(
        "--platform", default="instagram_reels", choices=sorted(PLATFORM_PROFILES)
    )
    ap.add_argument("--require-virality", action="store_true")
    args = ap.parse_args()
    print(
        json.dumps(
            run_readiness(
                Path(args.root),
                clip=args.clip,
                platform=args.platform,
                require_virality=args.require_virality,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
