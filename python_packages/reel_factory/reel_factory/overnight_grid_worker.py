#!/usr/bin/env python3
"""Create reviewable reels from animated Higgsfield Soul grids.

The worker is intentionally operator-controlled:
it can dry-run the planned Kling jobs, or spend at most ``--max-kling``
jobs when ``--create-kling`` is provided.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asset_prompt_contract import AssetPromptSet
from campaign_store import rate_output
from caption_render import render_caption_png
from creator_os_core.media_probe import probe_video_stream as probe_video
from generate_assets import AssetGenerationPlan, create_video_asset
from PIL import Image, ImageChops

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text


def _flattened_pixels(image: Image.Image):
    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter else image.getdata()


STACEY_SOUL_ID = "5828d958-91dd-4d6d-8909-934503f47644"
DEFAULT_GRID_NAMES = [
    "iitsivyblake_v2_trimmed_bgfix_soul_image.png",
    "gwen2wild_v9_video_negative_fix_soul_image.png",
    "gwen2wild_simple_retry_v7_soul_image.png",
    "gwen2wild_trimmed_v8_soul_image.png",
]
CAPTIONS = [
    "wait for it",
    "this one feels different",
    "be honest",
    "too much?",
    "which one wins?",
    "don’t blink",
]


@dataclass(frozen=True)
class GridSpec:
    path: Path
    columns: int
    rows: int

    @property
    def panel_count(self) -> int:
        return self.columns * self.rows


def _run(cmd: list[str], *, timeout: int = 60 * 20) -> None:
    subprocess.run(cmd, check=True, timeout=timeout)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def infer_grid(
    path: Path, *, columns: int | None = None, rows: int | None = None
) -> GridSpec:
    with Image.open(path) as im:
        width, height = im.size
    if columns and rows:
        return GridSpec(path.resolve(), columns, rows)
    ratio = width / height if height else 1.0
    if 0.9 <= ratio <= 1.1:
        return GridSpec(path.resolve(), 3, 3)
    if ratio < 0.8:
        return GridSpec(path.resolve(), 2, 3)
    return GridSpec(path.resolve(), 3, 2)


def grid_assets(
    root: Path,
    explicit: list[str] | None = None,
    *,
    columns: int | None = None,
    rows: int | None = None,
) -> list[GridSpec]:
    base = root / "project_data" / "generated_assets"
    paths: list[Path] = []
    if explicit:
        paths = [Path(p).expanduser() for p in explicit]
    else:
        for name in DEFAULT_GRID_NAMES:
            p = base / name
            if p.exists():
                paths.append(p)
        for p in sorted(base.glob("*soul_image.png")):
            if p not in paths:
                paths.append(p)
    specs: list[GridSpec] = []
    for p in paths:
        p = p if p.is_absolute() else root / p
        if not p.exists():
            continue
        spec = infer_grid(p, columns=columns, rows=rows)
        if spec.panel_count >= 4:
            specs.append(spec)
    return specs


def prompt_for_grid(root: Path, grid: GridSpec) -> Path:
    prompt_dir = root / "prompts" / "_overnight_grid_worker"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    stem = grid.path.stem.replace("_soul_image", "")
    path = prompt_dir / f"{stem}_grid_video_prompt.json"
    payload = AssetPromptSet(
        higgsfieldGridPrompt=(
            "Existing Higgsfield Soul grid. Use the provided grid image as the visual source."
        ),
        klingMotionPrompt=(
            "Shared motion pass for every cropped panel from this grid. Apply the same "
            "reference-derived movement pattern to each panel separately: subtle body "
            "movement, soft breathing, light hand or phone movement where present, gentle "
            "head movement, fabric cling and stretch, and natural handheld camera motion. "
            "Preserve each supplied start image as the visual source for pose, framing, "
            "room, outfit, camera angle, and lighting."
        ),
        notes="Shared motion prompt for overnight crop-and-review workflow.",
    )
    atomic_write_text(
        path,
        json.dumps(payload.__dict__, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def prompt_for_panel(root: Path, grid: GridSpec, panel: int) -> Path:
    prompt_dir = root / "prompts" / "_overnight_grid_worker"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    stem = grid.path.stem.replace("_soul_image", "")
    path = prompt_dir / f"{stem}_shared_kling_motion_prompt.json"
    payload = AssetPromptSet(
        higgsfieldGridPrompt="Cropped Higgsfield Soul panel used as the visual source.",
        klingMotionPrompt=(
            "Shared motion pass for every cropped panel from this grid. Apply the same "
            "reference-derived movement pattern to each panel separately: subtle body "
            "movement, soft breathing, light hand or phone movement where present, gentle "
            "head movement, fabric cling and stretch, and natural handheld camera motion. "
            "Preserve each supplied start image as the visual source for pose, framing, "
            "room, outfit, camera angle, and lighting."
        ),
        notes="Shared panel fanout motion prompt.",
    )
    atomic_write_text(
        path,
        json.dumps(payload.__dict__, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def animation_path(root: Path, grid: GridSpec) -> Path:
    stem = grid.path.stem.replace("_soul_image", "")
    return (
        root
        / "project_data"
        / "generated_assets"
        / "animations"
        / f"{stem}_whole_grid_kling.mp4"
    )


def create_kling_for_grid(
    root: Path, grid: GridSpec, *, dry_run: bool
) -> dict[str, Any]:
    prompt_json = prompt_for_grid(root, grid)
    out = animation_path(root, grid)
    stem = out.stem
    with Image.open(grid.path) as im:
        image_ratio = im.width / im.height if im.height else 1.0
    plan = AssetGenerationPlan(
        prompt_json=prompt_json,
        stem=stem,
        reference=None,
        soul_id=STACEY_SOUL_ID,
        soul_name="Stacey",
        start_image=str(grid.path),
        out_dir=out.parent,
        source_dir=root / "00_source_videos",
        creator="Stacey",
        selected_panel="whole_grid",
        video_aspect_ratio="1:1" if 0.85 <= image_ratio <= 1.20 else "9:16",
        video_duration=5,
        video_sound="off",
    )
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "prompt_json": str(prompt_json),
            "would_create": str(out),
            "start_image": str(grid.path),
        }
    result = create_video_asset(plan, wait=True, download=True)
    downloaded = (
        result.get("lineage", {})
        .get("generation", {})
        .get("localPaths", {})
        .get("video")
    )
    if downloaded and Path(downloaded).exists() and Path(downloaded) != out:
        shutil.copy2(downloaded, out)
    return result | {"animation_path": str(out)}


def _even_floor(value: float) -> int:
    value = math.floor(value)
    return value if value % 2 == 0 else max(0, value - 1)


def _even_ceil(value: float, limit: int) -> int:
    value = math.ceil(value)
    if value % 2:
        value += 1
    return min(limit, value)


def detect_visible_content_box(
    image: Path, *, threshold: int = 18
) -> tuple[int, int, int, int]:
    """Find the real grid area, ignoring black/solid outer padding when present."""
    with Image.open(image) as raw:
        im = raw.convert("RGB")
        width, height = im.size
        sample = max(4, min(width, height) // 32)
        corners = [
            im.crop((0, 0, sample, sample)),
            im.crop((width - sample, 0, width, sample)),
            im.crop((0, height - sample, sample, height)),
            im.crop((width - sample, height - sample, width, height)),
        ]
        pixels = []
        for corner in corners:
            pixels.extend(_flattened_pixels(corner))
        bg = tuple(sum(px[i] for px in pixels) // len(pixels) for i in range(3))
        diff = Image.new("RGB", im.size, bg)
        mask = Image.eval(
            ImageChops.difference(im, diff).convert("L"),
            lambda px: 255 if px > threshold else 0,
        )
        box = mask.getbbox()
        if not box:
            return (0, 0, width, height)
        left, top, right, bottom = box
        if (right - left) < width * 0.5 or (bottom - top) < height * 0.5:
            return (0, 0, width, height)
        return (left, top, right, bottom)


def first_frame_path(video: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = out_dir / f"{video.stem}_first_frame.jpg"
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "0.250",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame),
        ]
    )
    return frame


def panel_crop_boxes(
    width: int,
    height: int,
    grid: GridSpec,
    *,
    content_box: tuple[int, int, int, int] | None = None,
    inset: int = 0,
) -> list[tuple[int, int, int, int]]:
    left, top, right, bottom = content_box or (0, 0, width, height)
    left = max(0, min(width - 2, left + inset))
    top = max(0, min(height - 2, top + inset))
    right = max(left + 2, min(width, right - inset))
    bottom = max(top + 2, min(height, bottom - inset))
    grid_w = right - left
    grid_h = bottom - top
    boxes: list[tuple[int, int, int, int]] = []
    for row in range(grid.rows):
        for col in range(grid.columns):
            x1 = _even_floor(left + (grid_w * col / grid.columns))
            y1 = _even_floor(top + (grid_h * row / grid.rows))
            x2 = _even_ceil(left + (grid_w * (col + 1) / grid.columns), width)
            y2 = _even_ceil(top + (grid_h * (row + 1) / grid.rows), height)
            boxes.append((x1, y1, max(2, x2 - x1), max(2, y2 - y1)))
    return boxes


def crop_grid_video(
    video: Path, grid: GridSpec, out_dir: Path, *, smart: bool = False, inset: int = 2
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    info = probe_video(video)
    width = info["width"]
    height = info["height"]
    content_box = None
    if smart:
        with tempfile.TemporaryDirectory(prefix="grid_crop_") as tmp:
            frame = first_frame_path(video, Path(tmp))
            content_box = detect_visible_content_box(frame)
    boxes = panel_crop_boxes(
        width, height, grid, content_box=content_box, inset=inset if smart else 0
    )
    outputs: list[Path] = []
    for panel, (x, y, crop_w, crop_h) in enumerate(boxes, start=1):
        out = out_dir / f"{video.stem}_panel_{panel:02d}.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"crop={crop_w}:{crop_h}:{x}:{y}",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out),
        ]
        _run(cmd)
        outputs.append(out)
    return outputs


def crop_grid_image(grid: GridSpec, panel: int, out_dir: Path) -> Path:
    if panel < 1 or panel > grid.panel_count:
        raise ValueError(f"panel must be 1-{grid.panel_count}")
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(grid.path) as im:
        width, height = im.size
        crop_w = math.floor(width / grid.columns)
        crop_h = math.floor(height / grid.rows)
        idx = panel - 1
        col = idx % grid.columns
        row = idx // grid.columns
        box = (col * crop_w, row * crop_h, (col + 1) * crop_w, (row + 1) * crop_h)
        out = out_dir / f"{grid.path.stem}_panel_{panel:02d}.png"
        im.crop(box).save(out)
        return out


def create_kling_for_panel(
    root: Path, grid: GridSpec, panel: int, *, dry_run: bool
) -> dict[str, Any]:
    panel_image = crop_grid_image(
        grid,
        panel,
        root / "project_data" / "overnight_candidates" / "individual_start_images",
    )
    prompt_json = prompt_for_panel(root, grid, panel)
    stem = f"{grid.path.stem.replace('_soul_image', '')}_panel_{panel:02d}_kling"
    out = root / "project_data" / "generated_assets" / "animations" / f"{stem}.mp4"
    plan = AssetGenerationPlan(
        prompt_json=prompt_json,
        stem=stem,
        reference=None,
        soul_id=STACEY_SOUL_ID,
        soul_name="Stacey",
        start_image=str(panel_image),
        out_dir=out.parent,
        source_dir=root / "00_source_videos",
        creator="Stacey",
        selected_panel=str(panel),
        video_aspect_ratio="1:1",
        video_duration=5,
        video_sound="off",
    )
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "prompt_json": str(prompt_json),
            "would_create": str(out),
            "start_image": str(panel_image),
            "selected_panel": panel,
        }
    result = create_video_asset(plan, wait=True, download=True)
    downloaded = (
        result.get("lineage", {})
        .get("generation", {})
        .get("localPaths", {})
        .get("video")
    )
    if downloaded and Path(downloaded).exists() and Path(downloaded) != out:
        shutil.copy2(downloaded, out)
    return result | {"animation_path": str(out), "start_image": str(panel_image)}


def simple_rating(video: Path) -> dict[str, Any]:
    try:
        info = probe_video(video)
    except Exception as exc:
        return {
            "keep": False,
            "scores": {
                "identity": 1,
                "pose": 1,
                "taste": 1,
                "artifacts": 1,
                "motion": 1,
            },
            "labels": ["probe_failed"],
            "reason": str(exc),
        }
    labels: list[str] = []
    scores = {"identity": 4, "pose": 4, "taste": 4, "artifacts": 4, "motion": 4}
    if info["width"] < 300 or info["height"] < 300:
        labels.append("low_resolution_crop")
        scores["artifacts"] = 2
    if info["duration"] < 2.0:
        labels.append("too_short")
        scores["motion"] = 2
    keep = min(scores.values()) >= 3
    return {
        "keep": keep,
        "scores": scores,
        "labels": labels or ["auto_review_pass"],
        "reason": "",
    }


def next_clip_stem(root: Path) -> str:
    raw = root / "00_source_videos"
    nums = []
    for p in raw.glob("clip_*.mp4"):
        try:
            nums.append(int(p.stem.split("_")[1]))
        except Exception:
            pass
    return f"clip_{(max(nums) + 1) if nums else 1:03d}"


def source_lineage_for_animation(root: Path, animation: Path) -> Path | None:
    lineage = (
        root / "00_source_videos" / f"{animation.stem}.generated_asset_lineage.json"
    )
    return lineage if lineage.exists() else None


def write_candidate_lineage(
    root: Path,
    *,
    source_clip: Path,
    panel_video: Path,
    grid: GridSpec,
    animation: Path,
    panel_index: int,
    rating: dict[str, Any],
) -> Path:
    source_lineage = source_lineage_for_animation(root, animation)
    payload = {
        "schema": "reel_factory.cropped_grid_candidate_lineage.v1",
        "createdAt": int(time.time()),
        "workflow": "whole_grid_kling_to_cropped_panel_reel",
        "source": {
            "sourceGridPath": str(grid.path),
            "animatedGridPath": str(animation.resolve()),
            "animatedGridLineagePath": str(source_lineage) if source_lineage else None,
            "croppedPanelPath": str(panel_video.resolve()),
            "selectedPanel": panel_index,
            "grid": {"columns": grid.columns, "rows": grid.rows},
        },
        "output": {
            "sourceClipPath": str(source_clip.resolve()),
            "sourceVideoHash": sha256_file(source_clip),
        },
        "rating": rating,
        "review": {"humanReviewRequired": True},
    }
    out = source_clip.with_suffix(".generated_asset_lineage.json")
    atomic_write_text(
        out, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out


def install_candidate(
    root: Path,
    panel_video: Path,
    caption: str,
    *,
    index: int,
    grid: GridSpec,
    animation: Path,
    panel_index: int,
    rating: dict[str, Any],
) -> dict[str, str]:
    stem = next_clip_stem(root)
    src = root / "00_source_videos" / f"{stem}.mp4"
    cap = root / "01_captions" / f"{stem}.json"
    src.parent.mkdir(parents=True, exist_ok=True)
    cap.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(panel_video, src)
    atomic_write_text(
        cap,
        json.dumps(
            {
                "hooks": [caption],
                "recipes": ["v01_original", "v09_caption_bg"],
                "caption_color": "auto",
                "source": {
                    "panel_video": str(panel_video.resolve()),
                    "overnight_index": index,
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lineage = write_candidate_lineage(
        root,
        source_clip=src,
        panel_video=panel_video,
        grid=grid,
        animation=animation,
        panel_index=panel_index,
        rating=rating,
    )
    return {
        "stem": stem,
        "source": str(src),
        "caption": str(cap),
        "lineage": str(lineage),
    }


def _fit_render_installed(root: Path, stem: str) -> Path:
    """Render a split grid panel without zoom-cropping the source.

    Reel Factory's default graph intentionally fills a 9:16 canvas with
    scale=increase+crop. That is right for ordinary sources, but wrong for
    panel crops from animated grids because it can cut off a large part of
    the already-small panel. These grid-derived clips should preserve the
    full panel and use a blurred background/pad to fill the reel canvas.
    """
    src = root / "00_source_videos" / f"{stem}.mp4"
    cap_path = root / "01_captions" / f"{stem}.json"
    if not src.exists():
        raise FileNotFoundError(src)
    if not cap_path.exists():
        raise FileNotFoundError(cap_path)

    cap_data = json.loads(cap_path.read_text(encoding="utf-8"))
    caption = str((cap_data.get("hooks") or [""])[0])
    out_dir = root / "02_processed" / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    cap_png = out_dir / "_cap_h00_fit_nocrop_light.png"
    render_caption_png(
        caption,
        font_family="Instagram Sans Condensed Bold",
        fonts_dir=root / "fonts",
        color_scheme="light",
        band="center",
        style="ig",
        out_path=cap_png,
        canvas_w=1080,
        canvas_h=1920,
        renderer="pillow",
    )
    out = out_dir / f"{stem}_h00_v09_caption_fit_nocrop_light.mp4"
    filt = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1080:1920,boxblur=24:2,eq=brightness=-0.06:saturation=0.85[bg];"
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
        "[1:v]format=rgba[cap];[base][cap]overlay=0:0:format=auto[v]"
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-loop",
            "1",
            "-i",
            str(cap_png),
            "-filter_complex",
            filt,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-t",
            "5.05",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-shortest",
            str(out),
        ],
        timeout=90,
    )
    return out


def render_installed(root: Path, stems: list[str]) -> None:
    for stem in stems:
        _fit_render_installed(root, stem)


def run_worker(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    specs = grid_assets(root, args.grid, columns=args.columns, rows=args.rows)[
        : args.max_grids
    ]
    report: dict[str, Any] = {
        "createdAt": int(time.time()),
        "maxKling": args.max_kling,
        "klingUsed": 0,
        "grids": [],
        "kept": [],
        "rejected": [],
        "rendered": [],
    }
    for spec in specs:
        grid_entry: dict[str, Any] = {
            "sourceGrid": str(spec.path),
            "columns": spec.columns,
            "rows": spec.rows,
            "panels": spec.panel_count,
        }
        anim = animation_path(root, spec)
        if args.create_kling and not anim.exists():
            if report["klingUsed"] >= args.max_kling:
                grid_entry["status"] = "skipped_max_kling"
                report["grids"].append(grid_entry)
                continue
            result = create_kling_for_grid(root, spec, dry_run=False)
            grid_entry["klingResult"] = result
            report["klingUsed"] += 1
        elif args.dry_run and not anim.exists():
            grid_entry["dryRun"] = create_kling_for_grid(root, spec, dry_run=True)
        if not anim.exists():
            grid_entry["status"] = "needs_kling_animation"
            report["grids"].append(grid_entry)
            continue
        grid_entry["animation"] = str(anim)
        crop_dir = root / "project_data" / "overnight_candidates" / anim.stem
        panels = crop_grid_video(
            anim, spec, crop_dir, smart=args.smart_crop, inset=args.crop_inset
        )
        grid_entry["croppedPanels"] = [str(p) for p in panels]
        for i, panel in enumerate(panels, start=1):
            rating = simple_rating(panel)
            record = {
                "panel": str(panel),
                "sourceGrid": str(spec.path),
                "rating": rating,
            }
            if rating["keep"] and len(report["kept"]) < args.keep_limit:
                caption = CAPTIONS[(len(report["kept"]) + i - 1) % len(CAPTIONS)]
                installed = install_candidate(
                    root,
                    panel,
                    caption,
                    index=len(report["kept"]) + 1,
                    grid=spec,
                    animation=anim,
                    panel_index=i,
                    rating=rating,
                )
                rate_output(
                    root,
                    output_path=Path(installed["source"]),
                    scores=rating["scores"],
                    labels=rating["labels"],
                    reason=rating["reason"],
                    notes=f"Auto-rated overnight cropped panel from {spec.path.name}",
                )
                record["installed"] = installed
                report["kept"].append(record)
            else:
                if rating["keep"] and len(report["kept"]) >= args.keep_limit:
                    record["rating"] = {
                        **rating,
                        "keep": False,
                        "labels": rating["labels"] + ["over_keep_limit"],
                        "reason": "candidate passed auto checks but keep_limit was reached",
                    }
                report["rejected"].append(record)
        report["grids"].append(grid_entry)
    if args.render and report["kept"]:
        stems = [
            item["installed"]["stem"] for item in report["kept"] if "installed" in item
        ]
        render_installed(root, stems)
        for stem in stems:
            out_dir = root / "02_processed" / stem
            report["rendered"].extend(str(p) for p in sorted(out_dir.glob("*.mp4")))
    out_path = (
        root
        / "project_data"
        / "overnight_candidates"
        / f"overnight_report_{int(time.time())}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        out_path, json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    report["reportPath"] = str(out_path)
    return report


def parse_panel_spec(root: Path, value: str) -> tuple[GridSpec, int]:
    if ":" not in value:
        raise ValueError("--individual-panel must look like path/to/grid.png:panel")
    path_text, panel_text = value.rsplit(":", 1)
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = root / path
    return infer_grid(path, columns=None, rows=None), int(panel_text)


def run_individual_panels(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    report: dict[str, Any] = {
        "createdAt": int(time.time()),
        "mode": "individual_panel_fallback",
        "maxKling": args.max_kling,
        "klingUsed": 0,
        "kept": [],
        "rejected": [],
        "rendered": [],
    }
    panel_specs = [
        parse_panel_spec(root, value) for value in args.individual_panel or []
    ]
    for grid, panel in panel_specs:
        if report["klingUsed"] >= args.max_kling:
            report["rejected"].append(
                {
                    "sourceGrid": str(grid.path),
                    "panel": panel,
                    "reason": "skipped_max_kling",
                }
            )
            continue
        result = create_kling_for_panel(root, grid, panel, dry_run=args.dry_run)
        if args.dry_run:
            report.setdefault("dryRuns", []).append(result)
            continue
        report["klingUsed"] += 1
        video = Path(result.get("animation_path", ""))
        if not video.exists():
            report["rejected"].append(
                {
                    "sourceGrid": str(grid.path),
                    "panel": panel,
                    "reason": "missing_downloaded_video",
                    "result": result,
                }
            )
            continue
        rating = simple_rating(video)
        caption = CAPTIONS[len(report["kept"]) % len(CAPTIONS)]
        if rating["keep"]:
            installed = install_candidate(
                root,
                video,
                caption,
                index=len(report["kept"]) + 1,
                grid=grid,
                animation=video,
                panel_index=panel,
                rating=rating,
            )
            report["kept"].append(
                {
                    "panel": str(video),
                    "sourceGrid": str(grid.path),
                    "rating": rating,
                    "installed": installed,
                }
            )
        else:
            report["rejected"].append(
                {
                    "panel": str(video),
                    "sourceGrid": str(grid.path),
                    "rating": rating,
                }
            )
    if args.render and report["kept"]:
        stems = [
            item["installed"]["stem"] for item in report["kept"] if "installed" in item
        ]
        render_installed(root, stems)
        for stem in stems:
            out_dir = root / "02_processed" / stem
            report["rendered"].extend(str(p) for p in sorted(out_dir.glob("*.mp4")))
    out_path = (
        root
        / "project_data"
        / "overnight_candidates"
        / f"individual_panel_report_{int(time.time())}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        out_path, json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    report["reportPath"] = str(out_path)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument(
        "--grid", action="append", help="specific grid image path; can be repeated"
    )
    ap.add_argument("--max-grids", type=int, default=4)
    ap.add_argument("--max-kling", type=int, default=20)
    ap.add_argument(
        "--create-kling",
        action="store_true",
        help="actually create missing Kling whole-grid animations",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="show planned missing Kling jobs without spending credits",
    )
    ap.add_argument("--columns", type=int)
    ap.add_argument("--rows", type=int)
    ap.add_argument("--keep-limit", type=int, default=12)
    ap.add_argument(
        "--render",
        action="store_true",
        help="render kept cropped panels through Reel Factory",
    )
    ap.add_argument(
        "--smart-crop",
        action="store_true",
        help="detect visible grid bounds before splitting panels",
    )
    ap.add_argument(
        "--crop-inset",
        type=int,
        default=2,
        help="pixels to inset each smart panel crop to avoid seams",
    )
    ap.add_argument(
        "--individual-panel",
        action="append",
        help="fallback mode: animate one high-quality panel crop, format grid.png:panel",
    )
    ap.add_argument(
        "--allow-individual",
        action="store_true",
        help="explicit override to allow individual-panel Kling fallback spending",
    )
    args = ap.parse_args()
    if args.individual_panel and not args.allow_individual:
        ap.error(
            "--individual-panel is disabled by default; pass --allow-individual to spend individual Kling jobs"
        )
    report = run_individual_panels(args) if args.individual_panel else run_worker(args)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
