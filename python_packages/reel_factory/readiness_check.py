#!/usr/bin/env python3
"""Warn-only platform readiness aggregation for rendered reel outputs."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from audio_intent import read_audio_intent
from post_render_acceptance import acceptance_from_readiness
from safe_zone import PLATFORM_SAFE_ZONES, score_safe_zone
from virality_qc import evaluate_output_virality

TIMED_CAPTION_TAIL_RESERVE_SECONDS = 0.20
CAPTION_REJECTED_LANE_OVERLAP_RATIO = 0.35


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


def load_readiness_by_name(clip_dir: Path, *, platform: str | None = None) -> dict[str, dict[str, Any]]:
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


def load_readiness_for_output(output_path: Path, *, platform: str | None = None) -> dict[str, Any] | None:
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
    db = root / "manifest.sqlite"
    if not db.exists():
        return {}
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT output_path, review_state, recipe_params_json, status FROM variations"
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
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except Exception:
        return None, None


def _probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return None


def _caption_lineage(output_path: Path) -> dict[str, Any] | None:
    return _json_sidecar(output_path, "caption_lineage")


def _segments_from_lineage(lineage: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(lineage, dict):
        return []
    segments = lineage.get("timedSegments")
    if isinstance(segments, list):
        return [row for row in segments if isinstance(row, dict)]
    context = lineage.get("captionOutcomeContext")
    text = context.get("caption_text") if isinstance(context, dict) else None
    if isinstance(text, str) and '"segments"' in text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        segments = payload.get("segments")
        if isinstance(segments, list):
            return [row for row in segments if isinstance(row, dict)]
    return []


def _caption_timing_warnings(output_path: Path, lineage: dict[str, Any] | None) -> list[str]:
    duration = _probe_duration(output_path)
    segments = _segments_from_lineage(lineage)
    if not duration or not segments:
        return []
    warnings: list[str] = []
    max_end = max((float(row.get("end") or 0.0) for row in segments), default=0.0)
    if max_end > duration + 0.02:
        warnings.append("timed_caption_exceeds_rendered_duration")
    if duration - max_end < TIMED_CAPTION_TAIL_RESERVE_SECONDS:
        warnings.append("timed_caption_no_tail_reserve")
    return warnings


def _lane_bounds(height: int) -> dict[str, tuple[float, float]]:
    third = height / 3.0
    return {
        "top": (0.0, third),
        "center": (third, third * 2.0),
        "bottom": (third * 2.0, float(height)),
    }


def _caption_box_lane_warnings(lineage: dict[str, Any] | None, *, height: int | None) -> list[str]:
    if not isinstance(lineage, dict) or not height:
        return []
    decision = lineage.get("captionPlacementDecision")
    if not isinstance(decision, dict):
        return []
    rejected = {str(lane) for lane in decision.get("rejectedLanes") or []}
    rejected = {lane for lane in rejected if lane in {"top", "center", "bottom"}}
    if not rejected:
        return []
    boxes = lineage.get("captionRenderBoxes")
    if not isinstance(boxes, list):
        return []
    lane_bounds = _lane_bounds(height)
    for row in boxes:
        if not isinstance(row, dict):
            continue
        box = row.get("box")
        if not isinstance(box, dict):
            continue
        try:
            y0 = float(box["y"])
            y1 = y0 + float(box["h"])
        except (KeyError, TypeError, ValueError):
            continue
        box_h = max(1.0, y1 - y0)
        for lane in rejected:
            lane_y0, lane_y1 = lane_bounds[lane]
            overlap = max(0.0, min(y1, lane_y1) - max(y0, lane_y0))
            if overlap / box_h >= CAPTION_REJECTED_LANE_OVERLAP_RATIO:
                return ["caption_box_over_rejected_focal_lane"]
    return []


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

    width, height = dimensions if dimensions is not None else _probe_dimensions(output_path)
    if width and height and min(width, height) < int(profile["min_resolution_px"]):
        warnings.append("resolution_below_platform_minimum")

    safe_zone = score_safe_zone(width=width, height=height, platform=platform)
    warnings.extend(safe_zone.get("warnings") or [])
    if safe_zone.get("safeZoneStatus") == "warn":
        warnings.append("safe_zone_review_needed")

    audio_intent = read_audio_intent(output_path)
    if profile["requires_audio_intent"] and not audio_intent:
        warnings.append("missing_audio_intent")

    if profile["requires_lineage"] and not _source_lineage_exists(root, clip, output_path):
        warnings.append("missing_generated_asset_lineage")

    caption_lineage = _caption_lineage(output_path)
    warnings.extend(_caption_timing_warnings(output_path, caption_lineage))
    warnings.extend(_caption_box_lane_warnings(caption_lineage, height=height))

    ai_warnings = list((ai_qc or {}).get("warnings") or [])
    warnings.extend(f"ai_qc:{w}" for w in ai_warnings)
    if profile["strict_text_review"] and any("text" in w or "watermark" in w for w in ai_warnings):
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
        "reviewState": (manifest_row or {}).get("review_state", "draft"),
        "targetRatio": target_ratio,
        "dimensions": {"width": width, "height": height},
        "audioIntent": audio_intent,
        "safeZone": safe_zone,
        "aiQc": ai_qc,
        "viralityQc": virality_qc,
        "lineagePresent": _source_lineage_exists(root, clip, output_path),
        "captionLineage": caption_lineage,
    }


def run_readiness(root: Path, *, clip: str | None = None,
                  platform: str = "instagram_reels",
                  require_virality: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    platform = normalize_platform(platform)
    proc = root / "02_processed"
    clip_dirs = [proc / clip] if clip else [p for p in sorted(proc.iterdir()) if p.is_dir() and not p.name.startswith("_")]
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
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
    ap.add_argument("--platform", default="instagram_reels", choices=sorted(PLATFORM_PROFILES))
    ap.add_argument("--require-virality", action="store_true")
    args = ap.parse_args()
    print(json.dumps(
        run_readiness(
            Path(args.root),
            clip=args.clip,
            platform=args.platform,
            require_virality=args.require_virality,
        ),
        indent=2,
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
