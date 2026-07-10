#!/usr/bin/env python3
"""Manual grid-crop plans for animated Higgsfield grid videos."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from caption_render import render_caption_png
from PIL import Image, ImageChops

from .fileops import atomic_write_text


def _flattened_pixels(image: Image.Image):
    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter else image.getdata()


DEFAULT_CAPTIONS = [
    "wait for it",
    "be honest",
    "which one wins?",
    "too much?",
    "don’t blink",
    "this one feels different",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_video(path: Path) -> dict[str, Any]:
    raw = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    streams = json.loads(raw).get("streams") or []
    if not streams:
        raise ValueError(f"no video stream found: {path}")
    stream = streams[0]
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration": float(stream.get("duration") or 0.0),
    }


def crop_plan_path(root: Path, stem: str) -> Path:
    return root / "project_data" / "grid_crop_plans" / f"{stem}.crop_plan.json"


def frame_path(root: Path, stem: str, time_sec: float) -> Path:
    ms = max(0, int(round(time_sec * 1000)))
    return root / "project_data" / "grid_crop_frames" / f"{stem}_{ms:06d}.jpg"


def extract_frame(
    source_video: Path, out_path: Path, *, time_sec: float = 0.25
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, time_sec):.3f}",
            "-i",
            str(source_video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_path),
        ],
        check=True,
    )
    return out_path


def preset_boxes(
    width: int, height: int, *, columns: int, rows: int, inset: int = 0
) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    for row in range(rows):
        for col in range(columns):
            x1 = math.floor(width * col / columns) + inset
            y1 = math.floor(height * row / rows) + inset
            x2 = math.floor(width * (col + 1) / columns) - inset
            y2 = math.floor(height * (row + 1) / rows) - inset
            if col == columns - 1:
                x2 = width - inset
            if row == rows - 1:
                y2 = height - inset
            boxes.append(
                {
                    "id": len(boxes) + 1,
                    "label": f"panel {len(boxes) + 1}",
                    "x": max(0, int(x1)),
                    "y": max(0, int(y1)),
                    "w": max(2, int(x2 - x1)),
                    "h": max(2, int(y2 - y1)),
                    "enabled": True,
                }
            )
    return boxes


def infer_grid_preset(width: int, height: int) -> tuple[int, int]:
    ratio = width / height if height else 1.0
    if ratio > 1.45:
        return (4, 2)
    if ratio > 1.05:
        return (3, 2)
    if ratio < 0.85:
        return (2, 3)
    return (3, 3)


def detect_visible_content_box(
    image_path: Path, *, threshold: int = 18
) -> tuple[int, int, int, int]:
    """Find the non-padding image area by comparing against sampled corner color."""
    with Image.open(image_path) as raw:
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


def infer_image_grid(
    width: int, height: int, *, columns: int | None = None, rows: int | None = None
) -> dict[str, Any]:
    if columns and rows:
        return {
            "columns": int(columns),
            "rows": int(rows),
            "confidence": "operator_override",
        }
    ratio = width / height if height else 1.0
    candidates = [(1, 1), (2, 2), (3, 2), (2, 3), (4, 2), (3, 3)]
    columns, rows = min(candidates, key=lambda item: abs((item[0] / item[1]) - ratio))
    expected = columns / rows
    error = abs(expected - ratio) / expected if expected else 1.0
    confidence = "high" if error <= 0.18 else "review"
    return {"columns": columns, "rows": rows, "confidence": confidence, "ratio": ratio}


def _pixel_diff(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return (abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])) / 3.0


def _grid_boundary_score(
    image: Image.Image,
    content_box: tuple[int, int, int, int],
    *,
    columns: int,
    rows: int,
) -> float:
    left, top, right, bottom = content_box
    width = right - left
    height = bottom - top
    if width < 8 or height < 8:
        return 0.0
    pixels = image.load()
    samples: list[float] = []
    y_step = max(1, height // 80)
    x_step = max(1, width // 80)
    for col in range(1, columns):
        x = int(round(left + width * col / columns))
        x = max(left + 1, min(right - 1, x))
        for y in range(top, bottom, y_step):
            samples.append(_pixel_diff(pixels[x - 1, y], pixels[x, y]))
    for row in range(1, rows):
        y = int(round(top + height * row / rows))
        y = max(top + 1, min(bottom - 1, y))
        for x in range(left, right, x_step):
            samples.append(_pixel_diff(pixels[x, y - 1], pixels[x, y]))
    return sum(samples) / len(samples) if samples else 0.0


def infer_image_grid_from_pixels(
    image: Image.Image,
    content_box: tuple[int, int, int, int],
    *,
    columns: int | None = None,
    rows: int | None = None,
) -> dict[str, Any]:
    content_w = content_box[2] - content_box[0]
    content_h = content_box[3] - content_box[1]
    ratio_grid = infer_image_grid(content_w, content_h, columns=columns, rows=rows)
    if columns and rows:
        return ratio_grid
    candidates = [(1, 1), (2, 2), (3, 2), (2, 3), (4, 2), (3, 3)]
    scored = []
    for candidate_columns, candidate_rows in candidates:
        if candidate_columns == 1 and candidate_rows == 1:
            score = 0.0
        else:
            seams = detect_grid_seams(
                image,
                content_box,
                columns=candidate_columns,
                rows=candidate_rows,
            )
            seam_score = float(seams.get("minScore") or 0.0)
            seam_scores = [
                float(item.get("score") or 0.0)
                for item in (seams.get("verticalSeams") or [])
                + (seams.get("horizontalSeams") or [])
            ]
            average_seam_score = (
                sum(seam_scores) / len(seam_scores) if seam_scores else 0.0
            )
            boundary_score = _grid_boundary_score(
                image,
                content_box,
                columns=candidate_columns,
                rows=candidate_rows,
            )
            seam_count_reward = (
                len(seam_scores) * 2.0 if seams.get("confidence") == "high" else 0.0
            )
            panel_penalty = (candidate_columns * candidate_rows) * 0.05
            score = (
                max(seam_score, boundary_score)
                + (average_seam_score * 0.25)
                + seam_count_reward
                - panel_penalty
            )
        scored.append((score, candidate_columns, candidate_rows))
    score, best_columns, best_rows = max(scored, key=lambda item: item[0])
    if score < 8:
        ratio_grid["boundaryScore"] = score
        return ratio_grid
    return {
        "columns": best_columns,
        "rows": best_rows,
        "confidence": "high" if score >= 15 else "review",
        "ratio": content_w / content_h if content_h else 1.0,
        "boundaryScore": score,
    }


def _projection_profile(
    image: Image.Image, content_box: tuple[int, int, int, int], *, axis: str
) -> np.ndarray:
    left, top, right, bottom = content_box
    cropped = image.crop((left, top, right, bottom)).convert("RGB")
    arr = np.asarray(cropped).astype(np.int16)
    if axis == "vertical":
        if arr.shape[1] < 2:
            return np.zeros((0,), dtype=float)
        return np.mean(np.abs(arr[:, 1:] - arr[:, :-1]), axis=(0, 2))
    if arr.shape[0] < 2:
        return np.zeros((0,), dtype=float)
    return np.mean(np.abs(arr[1:, :] - arr[:-1, :]), axis=(1, 2))


def _best_seam_near(
    profile: np.ndarray, *, expected: int, window: int
) -> dict[str, Any]:
    if profile.size == 0:
        return {"position": expected, "score": 0.0, "expected": expected, "delta": 0}
    start = max(0, expected - window)
    end = min(profile.size - 1, expected + window)
    if end < start:
        return {"position": expected, "score": 0.0, "expected": expected, "delta": 0}
    segment = profile[start : end + 1]
    local = int(np.argmax(segment))
    index = start + local
    # Profile index x means the difference between columns x and x+1, so the
    # crop boundary should sit at x+1 in image coordinates.
    position = index + 1
    return {
        "position": position,
        "score": float(profile[index]),
        "expected": int(expected),
        "delta": int(position - expected),
    }


def detect_grid_seams(
    image: Image.Image,
    content_box: tuple[int, int, int, int],
    *,
    columns: int,
    rows: int,
) -> dict[str, Any]:
    left, top, right, bottom = content_box
    width = right - left
    height = bottom - top
    x_profile = _projection_profile(image, content_box, axis="vertical")
    y_profile = _projection_profile(image, content_box, axis="horizontal")
    x_window = max(12, min(96, int(round(width / max(columns, 1) * 0.20))))
    y_window = max(12, min(96, int(round(height / max(rows, 1) * 0.20))))
    vertical = []
    for col in range(1, columns):
        expected = int(round(width * col / columns))
        seam = _best_seam_near(x_profile, expected=expected, window=x_window)
        seam["position"] += left
        seam["expected"] += left
        vertical.append(seam)
    horizontal = []
    for row in range(1, rows):
        expected = int(round(height * row / rows))
        seam = _best_seam_near(y_profile, expected=expected, window=y_window)
        seam["position"] += top
        seam["expected"] += top
        horizontal.append(seam)
    scores = [float(item["score"]) for item in vertical + horizontal]
    min_score = min(scores) if scores else 999.0
    snapped = bool(scores and min_score >= 8.0)
    confidence = "high" if min_score >= 12.0 else ("review" if scores else "high")
    x_lines = [left] + [int(item["position"]) for item in vertical] + [right]
    y_lines = [top] + [int(item["position"]) for item in horizontal] + [bottom]
    expected_x_lines = [
        int(round(left + width * col / columns)) for col in range(columns + 1)
    ]
    expected_y_lines = [
        int(round(top + height * row / rows)) for row in range(rows + 1)
    ]
    if not snapped:
        x_lines = expected_x_lines
        y_lines = expected_y_lines
    return {
        "method": "projection_profile",
        "confidence": confidence,
        "snapped": snapped,
        "minScore": min_score if scores else None,
        "verticalSeams": vertical,
        "horizontalSeams": horizontal,
        "expectedXLines": expected_x_lines,
        "expectedYLines": expected_y_lines,
        "xLines": x_lines,
        "yLines": y_lines,
    }


def _adaptive_crop_inset(width: int, height: int, requested: int) -> int:
    if requested <= 0:
        return 0
    adaptive = int(round(max(8, width * 0.005)))
    cap = max(2, min(width, height) // 30)
    return max(requested, min(adaptive, cap))


def _manifest_confidence(grid_confidence: str, seam_detection: dict[str, Any]) -> str:
    if grid_confidence == "operator_override":
        return "operator_override"
    if seam_detection.get("confidence") == "review":
        return "review"
    return grid_confidence


def image_panel_crop_boxes(
    width: int,
    height: int,
    *,
    columns: int,
    rows: int,
    content_box: tuple[int, int, int, int] | None = None,
    inset: int = 2,
    seam_lines: dict[str, list[int]] | None = None,
) -> list[dict[str, Any]]:
    left, top, right, bottom = content_box or (0, 0, width, height)
    left = max(0, min(width - 2, left + inset))
    top = max(0, min(height - 2, top + inset))
    right = max(left + 2, min(width, right - inset))
    bottom = max(top + 2, min(height, bottom - inset))
    if seam_lines:
        x_lines = [
            max(0, min(width, int(value))) for value in seam_lines.get("xLines", [])
        ]
        y_lines = [
            max(0, min(height, int(value))) for value in seam_lines.get("yLines", [])
        ]
        if len(x_lines) != columns + 1 or len(y_lines) != rows + 1:
            x_lines = []
            y_lines = []
    else:
        x_lines = []
        y_lines = []
    grid_w = right - left
    grid_h = bottom - top
    boxes: list[dict[str, Any]] = []
    for row in range(rows):
        for col in range(columns):
            if x_lines and y_lines:
                x1 = x_lines[col] + inset
                y1 = y_lines[row] + inset
                x2 = x_lines[col + 1] - inset
                y2 = y_lines[row + 1] - inset
            else:
                x1 = math.floor(left + (grid_w * col / columns))
                y1 = math.floor(top + (grid_h * row / rows))
                x2 = math.ceil(left + (grid_w * (col + 1) / columns))
                y2 = math.ceil(top + (grid_h * (row + 1) / rows))
            boxes.append(
                {
                    "id": len(boxes) + 1,
                    "label": f"panel {len(boxes) + 1}",
                    "x": max(0, int(x1)),
                    "y": max(0, int(y1)),
                    "w": max(2, min(width, int(x2)) - max(0, int(x1))),
                    "h": max(2, min(height, int(y2)) - max(0, int(y1))),
                }
            )
    return boxes


def crop_image_grid_panels(
    image_path: Path,
    out_dir: Path,
    *,
    columns: int | None = None,
    rows: int | None = None,
    smart: bool = True,
    inset: int = 2,
    prefix: str | None = None,
) -> dict[str, Any]:
    image_path = image_path.resolve()
    # lgtm[py/path-injection] out_dir is the caller-selected output root for
    # this local crop utility; generated filenames below are derived safely.
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as raw:
        im = raw.convert("RGB")
        width, height = im.size
        content_box = (
            detect_visible_content_box(image_path) if smart else (0, 0, width, height)
        )
        grid = infer_image_grid_from_pixels(im, content_box, columns=columns, rows=rows)
        crop_inset = _adaptive_crop_inset(width, height, inset) if smart else 0
        seam_detection = (
            detect_grid_seams(
                im,
                content_box,
                columns=grid["columns"],
                rows=grid["rows"],
            )
            if smart
            else {
                "method": "disabled",
                "confidence": "high",
                "snapped": False,
                "xLines": [
                    int(round(width * col / grid["columns"]))
                    for col in range(grid["columns"] + 1)
                ],
                "yLines": [
                    int(round(height * row / grid["rows"]))
                    for row in range(grid["rows"] + 1)
                ],
            }
        )
        crop_boxes = image_panel_crop_boxes(
            width,
            height,
            columns=grid["columns"],
            rows=grid["rows"],
            content_box=content_box,
            inset=crop_inset,
            seam_lines=seam_detection if seam_detection.get("snapped") else None,
        )
        confidence = _manifest_confidence(
            str(grid.get("confidence") or "review"), seam_detection
        )
        panel_crops = []
        stem = prefix or image_path.stem
        for box in crop_boxes:
            panel = int(box["id"])
            out = out_dir / f"{stem}_panel_{panel:02d}.png"
            im.crop(
                (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
            ).save(out)
            panel_crops.append(
                {
                    "panel": panel,
                    "label": box["label"],
                    "cropBox": [box["x"], box["y"], box["w"], box["h"]],
                    "path": str(out),
                    "startImagePath": str(out),
                }
            )
    return {
        "schema": "reel_factory.image_grid_fanout.v1",
        "sourceImagePath": str(image_path),
        "sourceDimensions": {"width": width, "height": height},
        "contentBox": list(content_box),
        "gridPreset": {"columns": grid["columns"], "rows": grid["rows"]},
        "confidence": confidence,
        "seamDetection": seam_detection,
        "cropInset": crop_inset,
        "reviewRequired": confidence not in {"high", "operator_override"},
        "panelCrops": panel_crops,
    }


def validate_boxes(
    boxes: list[dict[str, Any]], *, width: int, height: int
) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for idx, box in enumerate(boxes, start=1):
        x = int(round(float(box.get("x", 0))))
        y = int(round(float(box.get("y", 0))))
        w = int(round(float(box.get("w", 0))))
        h = int(round(float(box.get("h", 0))))
        x = max(0, min(width - 2, x))
        y = max(0, min(height - 2, y))
        w = max(2, min(width - x, w))
        h = max(2, min(height - y, h))
        clean.append(
            {
                "id": int(box.get("id") or idx),
                "label": str(box.get("label") or f"panel {idx}"),
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "enabled": bool(box.get("enabled", True)),
            }
        )
    return clean


def build_crop_plan(
    root: Path,
    *,
    stem: str,
    source_video: Path,
    frame_time: float = 0.25,
    columns: int | None = None,
    rows: int | None = None,
    boxes: list[dict[str, Any]] | None = None,
    render_mode: str = "fit_nocrop",
) -> dict[str, Any]:
    info = probe_video(source_video)
    if columns is None or rows is None:
        columns, rows = infer_grid_preset(info["width"], info["height"])
    box_list = (
        boxes
        if boxes is not None
        else preset_boxes(info["width"], info["height"], columns=columns, rows=rows)
    )
    now = int(time.time())
    return {
        "schema": "reel_factory.grid_crop_plan.v1",
        "createdAt": now,
        "updatedAt": now,
        "stem": stem,
        "sourceVideoPath": str(source_video.resolve()),
        "sourceVideoHash": sha256_file(source_video),
        "sourceDimensions": {
            "width": info["width"],
            "height": info["height"],
            "duration": info["duration"],
        },
        "frameTime": frame_time,
        "gridPreset": {"columns": columns, "rows": rows},
        "boxes": validate_boxes(box_list, width=info["width"], height=info["height"]),
        "renderMode": render_mode,
    }


def load_crop_plan(root: Path, stem: str) -> dict[str, Any] | None:
    path = crop_plan_path(root, stem)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_crop_plan(root: Path, plan: dict[str, Any]) -> Path:
    stem = str(plan["stem"])
    out = crop_plan_path(root, stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    plan = dict(plan)
    plan["updatedAt"] = int(time.time())
    atomic_write_text(
        out, json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out


def crop_video_with_box(
    source_video: Path, out_path: Path, box: dict[str, Any]
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    x, y, w, h = int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])
    if w % 2:
        w -= 1
    if h % 2:
        h -= 1
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_video),
            "-vf",
            f"crop={w}:{h}:{x}:{y}",
            "-an",
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
            str(out_path),
        ],
        check=True,
    )
    return out_path


def render_fit_nocrop(
    root: Path, *, source_video: Path, caption: str, out_path: Path
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cap_png = out_path.with_name(f"_{out_path.stem}_caption.png")
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
    filt = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1080:1920,boxblur=24:2,eq=brightness=-0.06:saturation=0.85[bg];"
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
        "[1:v]format=rgba[cap];[base][cap]overlay=0:0:format=auto[v]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_video),
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
            str(out_path),
        ],
        check=True,
        timeout=90,
    )
    return out_path


def next_clip_stem(root: Path) -> str:
    nums = []
    for path in (root / "00_source_videos").glob("clip_*.mp4"):
        try:
            nums.append(int(path.stem.split("_")[1]))
        except Exception:
            pass
    return f"clip_{(max(nums) + 1) if nums else 1:03d}"


def write_panel_lineage(
    root: Path,
    *,
    clip_path: Path,
    plan: dict[str, Any],
    plan_path: Path,
    panel_video: Path,
    box: dict[str, Any],
    panel_index: int,
) -> Path:
    payload = {
        "schema": "reel_factory.grid_panel_lineage.v1",
        "createdAt": int(time.time()),
        "workflow": "manual_grid_crop_to_reel",
        "source": {
            "animatedGridPath": plan["sourceVideoPath"],
            "sourceVideoHash": plan["sourceVideoHash"],
            "cropPlanPath": str(plan_path.resolve()),
            "selectedPanel": panel_index,
            "cropBox": box,
            "croppedPanelPath": str(panel_video.resolve()),
        },
        "output": {
            "sourceClipPath": str(clip_path.resolve()),
            "sourceVideoHash": sha256_file(clip_path),
        },
        "review": {"humanReviewRequired": True},
    }
    out = clip_path.with_suffix(".generated_asset_lineage.json")
    atomic_write_text(
        out, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out


def install_cropped_panel(
    root: Path,
    *,
    plan: dict[str, Any],
    plan_path: Path,
    panel_video: Path,
    box: dict[str, Any],
    panel_index: int,
    caption: str,
) -> dict[str, Any]:
    stem = next_clip_stem(root)
    raw_dir = root / "00_source_videos"
    cap_dir = root / "01_captions"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cap_dir.mkdir(parents=True, exist_ok=True)
    clip_path = raw_dir / f"{stem}.mp4"
    shutil.copy2(panel_video, clip_path)
    cap_path = cap_dir / f"{stem}.json"
    atomic_write_text(
        cap_path,
        json.dumps(
            {
                "hooks": [caption],
                "recipes": ["v01_original", "v09_caption_bg"],
                "caption_color": "auto",
                "source": {
                    "workflow": "manual_grid_crop",
                    "animated_grid": plan["sourceVideoPath"],
                    "crop_plan": str(plan_path.resolve()),
                    "panel": panel_index,
                    "crop_box": box,
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lineage_path = write_panel_lineage(
        root,
        clip_path=clip_path,
        plan=plan,
        plan_path=plan_path,
        panel_video=panel_video,
        box=box,
        panel_index=panel_index,
    )
    return {
        "stem": stem,
        "source_path": str(clip_path),
        "caption_path": str(cap_path),
        "lineage_path": str(lineage_path),
    }


def write_review_sheet(
    root: Path, *, source_stem: str, installed: list[dict[str, Any]]
) -> Path | None:
    if not installed:
        return None
    thumb_dir = (
        root / "project_data" / "grid_crop_outputs" / source_stem / "_review_frames"
    )
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumbs: list[Path] = []
    for idx, row in enumerate(installed, start=1):
        src = Path(row["source_path"])
        thumb = thumb_dir / f"{src.stem}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "0.250",
                "-i",
                str(src),
                "-frames:v",
                "1",
                "-vf",
                "scale=360:-1",
                "-q:v",
                "3",
                str(thumb),
            ],
            check=True,
        )
        thumbs.append(thumb)
    images = [Image.open(p).convert("RGB") for p in thumbs]
    tile_w = max(im.width for im in images)
    tile_h = max(im.height for im in images)
    cols = min(4, len(images))
    rows = math.ceil(len(images) / cols)
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), (8, 8, 10))
    for idx, im in enumerate(images):
        x = (idx % cols) * tile_w
        y = (idx // cols) * tile_h
        sheet.paste(im, (x + (tile_w - im.width) // 2, y + (tile_h - im.height) // 2))
        im.close()
    out = (
        root
        / "project_data"
        / "grid_crop_outputs"
        / source_stem
        / "_manual_grid_crop_review_sheet.jpg"
    )
    sheet.save(out, quality=92)
    return out


def render_plan(
    root: Path,
    *,
    stem: str,
    captions: list[str] | None = None,
    render_captions: bool = True,
) -> dict[str, Any]:
    plan = load_crop_plan(root, stem)
    if not plan:
        raise FileNotFoundError(crop_plan_path(root, stem))
    plan_path = crop_plan_path(root, stem)
    source_video = Path(plan["sourceVideoPath"])
    crop_dir = root / "project_data" / "grid_crop_outputs" / stem
    captions = captions or DEFAULT_CAPTIONS
    installed: list[dict[str, Any]] = []
    rendered: list[str] = []
    for box in plan.get("boxes") or []:
        if not box.get("enabled", True):
            continue
        panel_index = int(box.get("id") or (len(installed) + 1))
        panel_video = crop_video_with_box(
            source_video, crop_dir / f"{stem}_panel_{panel_index:02d}.mp4", box
        )
        caption = captions[(len(installed) + panel_index - 1) % len(captions)]
        record = install_cropped_panel(
            root,
            plan=plan,
            plan_path=plan_path,
            panel_video=panel_video,
            box=box,
            panel_index=panel_index,
            caption=caption,
        )
        if render_captions:
            out = (
                root
                / "02_processed"
                / record["stem"]
                / f"{record['stem']}_h00_v09_caption_fit_nocrop_light.mp4"
            )
            render_fit_nocrop(
                root,
                source_video=Path(record["source_path"]),
                caption=caption,
                out_path=out,
            )
            rendered.append(str(out))
        installed.append(record)
    review_sheet = write_review_sheet(root, source_stem=stem, installed=installed)
    return {
        "ok": True,
        "crop_plan_path": str(plan_path),
        "installed": installed,
        "rendered": rendered,
        "review_sheet": str(review_sheet) if review_sheet else None,
    }


def preview_panel_image(root: Path, *, stem: str, panel_id: int) -> Path:
    plan = load_crop_plan(root, stem)
    if not plan:
        raise FileNotFoundError(crop_plan_path(root, stem))
    frame = frame_path(root, stem, float(plan.get("frameTime") or 0.25))
    if not frame.exists():
        extract_frame(
            Path(plan["sourceVideoPath"]),
            frame,
            time_sec=float(plan.get("frameTime") or 0.25),
        )
    boxes = {int(b.get("id")): b for b in plan.get("boxes") or []}
    box = boxes[panel_id]
    out = (
        root
        / "project_data"
        / "grid_crop_previews"
        / f"{stem}_panel_{panel_id:02d}.jpg"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(frame) as im:
        im.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])).save(
            out, quality=92
        )
    return out
