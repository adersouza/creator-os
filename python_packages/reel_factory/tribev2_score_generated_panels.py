from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


DEFAULT_BATCH_DIR = Path(
    "/Users/aderdesouza/Developer/reel_factory/output/reference_grok_grids_20260611"
)
DEFAULT_TRIBE_DIR = Path("/Users/aderdesouza/Developer/_spikes/tribev2")
DEFAULT_FFMPEG = Path("/opt/homebrew/bin/ffmpeg")


@dataclass(frozen=True)
class PanelRecord:
    path: Path
    creator: str
    reference_slug: str
    profile: str
    panel: int
    status: str
    flags: tuple[str, ...]
    reference_image: str
    comparison_sheet: str


def _stable_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load_summary_records(batch_dir: Path) -> dict[str, dict[str, Any]]:
    summary_path = batch_dir / "summary.json"
    if not summary_path.exists():
        return {}
    data = json.loads(summary_path.read_text())
    by_path: dict[str, dict[str, Any]] = {}
    for record in data.get("records", []):
        creator = record.get("creator", "")
        job_dir = Path(record.get("jobDir", ""))
        reference = record.get("reference", {}) or {}
        reference_slug = f"{reference.get('username', '')}_{reference.get('shortcode', '')}".strip("_")
        profile = record.get("profile", "") or (job_dir.name if job_dir.name else "")
        crop = record.get("crop", {}) or {}
        review = record.get("review", {}) or {}
        for panel in review.get("panels", []):
            panel_path = str(panel.get("path", ""))
            if not panel_path:
                continue
            by_path[panel_path] = {
                "creator": creator,
                "reference_slug": reference_slug,
                "profile": profile,
                "panel": int(panel.get("panel") or 0),
                "status": panel.get("status", ""),
                "flags": list(panel.get("flags") or []),
                "reference_image": record.get("referenceCopy", ""),
                "comparison_sheet": crop.get("comparisonSheetPath", ""),
            }
    return by_path


def collect_panels(batch_dir: Path, include_all_crops: bool) -> list[PanelRecord]:
    summary_by_path = _load_summary_records(batch_dir)
    paths = set(summary_by_path.keys())
    if include_all_crops:
        paths.update(str(path) for path in batch_dir.glob("**/crops/*.png"))

    records: list[PanelRecord] = []
    for raw_path in sorted(paths):
        path = Path(raw_path)
        if not path.exists():
            continue
        info = summary_by_path.get(str(path), {})
        try:
            rel = path.relative_to(batch_dir)
            creator = rel.parts[0]
            reference_slug = rel.parts[1]
            profile = rel.parts[2]
        except Exception:
            creator = info.get("creator", "")
            reference_slug = info.get("reference_slug", "")
            profile = info.get("profile", "")
        panel_num = info.get("panel")
        if not panel_num:
            stem = path.stem
            panel_num = int(stem.rsplit("_panel_", 1)[-1]) if "_panel_" in stem else 0
        job_dir = path.parent.parent
        records.append(
            PanelRecord(
                path=path,
                creator=info.get("creator") or creator,
                reference_slug=info.get("reference_slug") or reference_slug,
                profile=info.get("profile") or profile,
                panel=int(panel_num),
                status=info.get("status", "unknown"),
                flags=tuple(info.get("flags") or []),
                reference_image=info.get("reference_image", str(job_dir / "reference.jpg")),
                comparison_sheet=info.get(
                    "comparison_sheet", str(job_dir / "reference_comparison_sheet.jpg")
                ),
            )
        )
    return records


def make_silent_clip(
    panel_path: Path,
    clip_path: Path,
    ffmpeg: Path,
    duration: float,
    scale_size: int,
) -> None:
    if clip_path.exists() and clip_path.stat().st_size > 0:
        return
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = clip_path.with_suffix(".tmp.mp4")
    if tmp_path.exists():
        tmp_path.unlink()
    cmd = [
        str(ffmpeg),
        "-y",
        "-loop",
        "1",
        "-i",
        str(panel_path),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t",
        str(duration),
        "-vf",
        f"scale={scale_size}:{scale_size}:force_original_aspect_ratio=decrease,pad={scale_size}:{scale_size}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-shortest",
        str(tmp_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tmp_path.replace(clip_path)


def load_tribe_model(tribe_dir: Path, feature_mode: str):
    if str(tribe_dir) not in sys.path:
        sys.path.insert(0, str(tribe_dir))
    from tribev2 import TribeModel

    if feature_mode == "video":
        features = ["video"]
    else:
        features = ["audio", "video"]
    config_update = {
        "data.features_to_use": features,
        "data.audio_feature.device": "cpu",
        "data.video_feature.image.device": "cpu",
        "data.audio_feature.infra.cluster": None,
        "data.video_feature.infra.cluster": None,
        "data.video_feature.image.infra.cluster": None,
        "data.num_workers": 0,
    }
    return TribeModel.from_pretrained(
        "facebook/tribev2",
        cache_folder=str(tribe_dir / f"cache_panel_{feature_mode}"),
        config_update=config_update,
    )


def score_clip(model: Any, clip_path: Path, direct_video_events: bool) -> dict[str, Any]:
    started = time.time()
    if direct_video_events:
        events = pd.DataFrame(
            [
                {
                    "type": "Video",
                    "filepath": str(clip_path),
                    "start": 0,
                    "timeline": "default",
                    "subject": "default",
                }
            ]
        )
    else:
        events = model.get_events_dataframe(video_path=str(clip_path))
    preds, segments = model.predict(events=events)
    arr = preds.detach().cpu().numpy() if hasattr(preds, "detach") else np.asarray(preds)
    return {
        "status": "ok",
        "seconds": round(time.time() - started, 2),
        "eventsShape": list(events.shape),
        "predsShape": list(arr.shape),
        "meanAbsActivation": float(np.mean(np.abs(arr))),
        "peakAbsActivation": float(np.max(np.abs(arr))),
        "stdActivation": float(np.std(arr)),
        "segmentsCount": len(segments),
    }


def score_clip_batch(model: Any, clip_paths: list[Path]) -> dict[str, dict[str, Any]]:
    started = time.time()
    rows = []
    timeline_to_path = {}
    for clip_path in clip_paths:
        timeline = _stable_id(str(clip_path))
        rows.append(
            {
                "type": "Video",
                "filepath": str(clip_path),
                "start": 0,
                "timeline": timeline,
                "subject": "default",
            }
        )
        timeline_to_path[timeline] = str(clip_path)
    preds, segments = model.predict(events=pd.DataFrame(rows))
    arr = preds.detach().cpu().numpy() if hasattr(preds, "detach") else np.asarray(preds)
    out: dict[str, dict[str, Any]] = {}
    for idx, segment in enumerate(segments):
        timeline = getattr(segment, "timeline", "")
        clip_path = timeline_to_path.get(timeline, "")
        if not clip_path:
            continue
        segment_arr = arr[idx]
        out[clip_path] = {
            "status": "ok",
            "seconds": round(time.time() - started, 2),
            "eventsShape": [len(rows), len(rows[0]) if rows else 0],
            "predsShape": list(segment_arr.shape),
            "meanAbsActivation": float(np.mean(np.abs(segment_arr))),
            "peakAbsActivation": float(np.max(np.abs(segment_arr))),
            "stdActivation": float(np.std(segment_arr)),
            "segmentsCount": 1,
        }
    for clip_path in clip_paths:
        out.setdefault(
            str(clip_path),
            {
                "status": "error",
                "seconds": round(time.time() - started, 2),
                "error": "TRIBE returned no segment for clip",
            },
        )
    return out


def _load_existing(result_path: Path) -> dict[str, dict[str, Any]]:
    if not result_path.exists():
        return {}
    try:
        data = json.loads(result_path.read_text())
    except Exception:
        return {}
    existing: dict[str, dict[str, Any]] = {}
    for item in data.get("items", []):
        existing[item.get("panelPath", "")] = item
    return existing


def _percentile_scores(items: list[dict[str, Any]]) -> None:
    ok_items = [item for item in items if item.get("tribeScore", {}).get("status") == "ok"]
    values = sorted(
        (item["tribeScore"].get("meanAbsActivation", 0.0), item.get("panelPath", ""))
        for item in ok_items
    )
    if not values:
        return
    denom = max(len(values) - 1, 1)
    ranks = {panel_path: round((idx / denom) * 100, 2) for idx, (_, panel_path) in enumerate(values)}
    for item in ok_items:
        item["tribeVisualRating"] = ranks.get(item.get("panelPath", ""), 0.0)


def _write_csv(items: list[dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "tribeVisualRating",
        "meanAbsActivation",
        "peakAbsActivation",
        "stdActivation",
        "creator",
        "referenceSlug",
        "profile",
        "panel",
        "reviewStatus",
        "reviewFlags",
        "panelPath",
        "comparisonSheetPath",
    ]
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for idx, item in enumerate(items, start=1):
            score = item.get("tribeScore", {})
            writer.writerow(
                {
                    "rank": idx,
                    "tribeVisualRating": item.get("tribeVisualRating", ""),
                    "meanAbsActivation": score.get("meanAbsActivation", ""),
                    "peakAbsActivation": score.get("peakAbsActivation", ""),
                    "stdActivation": score.get("stdActivation", ""),
                    "creator": item.get("creator", ""),
                    "referenceSlug": item.get("referenceSlug", ""),
                    "profile": item.get("profile", ""),
                    "panel": item.get("panel", ""),
                    "reviewStatus": item.get("reviewStatus", ""),
                    "reviewFlags": ",".join(item.get("reviewFlags", [])),
                    "panelPath": item.get("panelPath", ""),
                    "comparisonSheetPath": item.get("comparisonSheetPath", ""),
                }
            )


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _fit_image(path: Path, size: tuple[int, int]) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, (20, 20, 20))
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def build_contact_sheet(items: list[dict[str, Any]], output_path: Path, title: str, limit: int) -> None:
    selected = items[:limit]
    if not selected:
        return
    cols = 4
    tile_w, tile_h = 260, 360
    header_h = 54
    rows = (len(selected) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, header_h + rows * tile_h), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    font = _load_font(16)
    small = _load_font(12)
    draw.text((16, 16), title, fill=(255, 255, 255), font=font)
    for idx, item in enumerate(selected):
        x = (idx % cols) * tile_w
        y = header_h + (idx // cols) * tile_h
        panel_path = Path(item["panelPath"])
        try:
            thumb = _fit_image(panel_path, (tile_w, tile_h - 74))
        except Exception:
            thumb = Image.new("RGB", (tile_w, tile_h - 74), (45, 20, 20))
        sheet.paste(thumb, (x, y))
        score = item.get("tribeScore", {})
        label = (
            f"#{idx + 1} {item.get('creator')} rating {item.get('tribeVisualRating', 0):.1f}\n"
            f"mean {score.get('meanAbsActivation', 0):.4f} peak {score.get('peakAbsActivation', 0):.4f}\n"
            f"{item.get('referenceSlug')} p{item.get('panel')}"
        )
        draw.multiline_text((x + 8, y + tile_h - 68), label, fill=(245, 245, 245), font=small, spacing=3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def score_panels(args: argparse.Namespace) -> dict[str, Any]:
    batch_dir = Path(args.batch_dir)
    output_dir = Path(args.output_dir) if args.output_dir else batch_dir / "tribev2_panel_review"
    clips_dir = output_dir / "clips"
    result_path = output_dir / "tribev2_panel_scores.json"
    csv_path = output_dir / "tribev2_panel_scores.csv"
    output_dir.mkdir(parents=True, exist_ok=True)

    panels = collect_panels(batch_dir, include_all_crops=args.include_all_crops)
    if args.creator:
        panels = [panel for panel in panels if panel.creator.lower() == args.creator.lower()]
    if args.limit:
        panels = panels[: args.limit]

    existing = _load_existing(result_path) if args.resume else {}
    items: list[dict[str, Any]] = []
    pending: list[tuple[PanelRecord, dict[str, Any], Path]] = []

    for index, panel in enumerate(panels, start=1):
        panel_key = str(panel.path)
        if panel_key in existing and not args.force:
            items.append(existing[panel_key])
            continue
        clip_path = clips_dir / f"{_stable_id(panel_key)}.mp4"
        item = {
            "panelPath": panel_key,
            "clipPath": str(clip_path),
            "creator": panel.creator,
            "referenceSlug": panel.reference_slug,
            "profile": panel.profile,
            "panel": panel.panel,
            "reviewStatus": panel.status,
            "reviewFlags": list(panel.flags),
            "referenceImagePath": panel.reference_image,
            "comparisonSheetPath": panel.comparison_sheet,
            "advisoryOnly": True,
            "productionGate": False,
        }
        try:
            make_silent_clip(panel.path, clip_path, Path(args.ffmpeg), args.duration, args.scale_size)
        except Exception as exc:
            item["tribeScore"] = {
                "status": "error",
                "error": repr(exc),
            }
            items.append(item)
            continue
        pending.append((panel, item, clip_path))

        if args.save_every and len(items) % args.save_every == 0:
            partial = build_report(items, batch_dir, args, complete=False)
            result_path.write_text(json.dumps(partial, indent=2))

    model = load_tribe_model(Path(args.tribe_dir), args.feature_mode) if pending else None
    for offset in range(0, len(pending), args.batch_size):
        batch = pending[offset : offset + args.batch_size]
        print(
            f"TRIBE scoring batch {offset // args.batch_size + 1} "
            f"({offset + 1}-{offset + len(batch)} / {len(pending)})",
            flush=True,
        )
        try:
            if args.direct_video_events:
                batch_scores = score_clip_batch(model, [clip_path for _, _, clip_path in batch])
                for _, item, clip_path in batch:
                    item["tribeScore"] = batch_scores[str(clip_path)]
                    items.append(item)
            else:
                for _, item, clip_path in batch:
                    item["tribeScore"] = score_clip(model, clip_path, args.direct_video_events)
                    items.append(item)
        except Exception as exc:
            for _, item, _ in batch:
                item["tribeScore"] = {"status": "error", "error": repr(exc)}
                items.append(item)
        if args.save_every:
            partial = build_report(items, batch_dir, args, complete=False)
            result_path.write_text(json.dumps(partial, indent=2))

    report = build_report(items, batch_dir, args, complete=True)
    result_path.write_text(json.dumps(report, indent=2))
    ranked_items = report["items"]
    _write_csv(ranked_items, csv_path)
    build_contact_sheet(
        ranked_items,
        output_dir / "tribev2_top_panels_contact_sheet.jpg",
        "TRIBE v2 top generated panels (advisory only)",
        args.contact_sheet_limit,
    )
    build_contact_sheet(
        list(reversed(ranked_items)),
        output_dir / "tribev2_bottom_panels_contact_sheet.jpg",
        "TRIBE v2 bottom generated panels (advisory only)",
        args.contact_sheet_limit,
    )
    report["csvPath"] = str(csv_path)
    report["topContactSheetPath"] = str(output_dir / "tribev2_top_panels_contact_sheet.jpg")
    report["bottomContactSheetPath"] = str(output_dir / "tribev2_bottom_panels_contact_sheet.jpg")
    result_path.write_text(json.dumps(report, indent=2))
    return report


def build_report(
    items: list[dict[str, Any]],
    batch_dir: Path,
    args: argparse.Namespace,
    complete: bool,
) -> dict[str, Any]:
    _percentile_scores(items)
    ranked = sorted(
        items,
        key=lambda item: (
            item.get("tribeScore", {}).get("status") == "ok",
            item.get("tribeScore", {}).get(args.sort_by, float("-inf")),
        ),
        reverse=True,
    )
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    scored = [item for item in ranked if item.get("tribeScore", {}).get("status") == "ok"]
    errors = [item for item in ranked if item.get("tribeScore", {}).get("status") != "ok"]
    by_creator: dict[str, int] = {}
    for item in scored:
        by_creator[item.get("creator", "")] = by_creator.get(item.get("creator", ""), 0) + 1
    return {
        "schema": "reel_factory.tribev2_generated_panel_scores.v1",
        "batchDir": str(batch_dir),
        "createdAt": int(time.time()),
        "complete": complete,
        "inputKind": "cropped_png_panels_converted_to_silent_video_stimuli",
        "model": "facebook/tribev2",
        "featureMode": args.feature_mode,
        "directVideoEvents": args.direct_video_events,
        "sortBy": args.sort_by,
        "panelsFound": len(items),
        "panelsScored": len(scored),
        "panelsErrored": len(errors),
        "scoredByCreator": by_creator,
        "licenseStatus": "CC-BY-NC-4.0",
        "advisoryOnly": True,
        "productionGate": False,
        "wouldWriteProductionState": False,
        "items": ranked,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score generated reference-grid crop panels with local TRIBE v2."
    )
    parser.add_argument("--batch-dir", default=str(DEFAULT_BATCH_DIR))
    parser.add_argument("--tribe-dir", default=str(DEFAULT_TRIBE_DIR))
    parser.add_argument("--ffmpeg", default=str(DEFAULT_FFMPEG))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--creator", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--scale-size", type=int, default=512)
    parser.add_argument("--feature-mode", choices=("video", "audio_video"), default="video")
    parser.add_argument("--sort-by", default="meanAbsActivation")
    parser.add_argument("--contact-sheet-limit", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--save-every", type=int, default=5)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--include-all-crops", action="store_true", default=True)
    parser.add_argument("--summary-only", dest="include_all_crops", action="store_false")
    parser.add_argument("--direct-video-events", action="store_true", default=True)
    parser.add_argument("--full-video-helper", dest="direct_video_events", action="store_false")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = score_panels(args)
    print(json.dumps({k: v for k, v in report.items() if k != "items"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
