#!/usr/bin/env python3
"""Build IG-style slideshow/carousel assets from local media.

This is for the cheap content format shown in many "AI UGC slideshow" reels:
one folder of model/reference photos or video frames becomes a batch of still
slides plus an optional stitched MP4 preview. The source media is never edited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .fileops import atomic_write_text

CANVAS_W = 1080
CANVAS_H = 1920
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


DEFAULT_HOOKS = [
    "People think my diet is weird...",
    "What I eat to stop the food noise",
    "How I look...",
    "pov: people think your diet is weird",
    '"Where are the carbs?"',
    "What I eat to stop me overeating",
    "What I eat to become the healthiest version of myself",
    '"Why don\'t you just eat normal food?"',
]


@dataclass(frozen=True)
class SlideshowItem:
    source_path: str
    kind: str
    source_hash: str
    caption_hash: str
    slide_path: str
    hook: str
    view_count_label: str | None = None


@dataclass(frozen=True)
class SlideshowManifest:
    schema: str
    created_at: str
    title: str
    preset: str
    format: str
    reference_pattern_id: str | None
    generation_id: str | None
    output_width: int
    output_height: int
    duration_seconds: float | None
    media_dir: str
    out_dir: str
    slide_count: int
    reel_path: str | None
    grid_path: str | None
    items: list[SlideshowItem]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_media(media_dir: Path) -> list[Path]:
    media_dir = media_dir.expanduser().resolve()
    if not media_dir.exists():
        raise FileNotFoundError(media_dir)
    return sorted(
        p
        for p in media_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS
    )


def _load_font(
    fonts_dir: Path, *, bold: bool = True, size: int = 54
) -> ImageFont.FreeTypeFont:
    candidates = [
        fonts_dir
        / (
            "InstagramSansCondensed-Bold.woff2"
            if bold
            else "InstagramSansCondensed-Regular.woff2"
        ),
        fonts_dir / "SofiaSansCondensed-Medium.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def _fit_cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(
        img.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )


def _extract_video_frame(
    video_path: Path, out_path: Path, *, at_seconds: float = 1.0, ffmpeg: str = "ffmpeg"
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or f"ffmpeg failed extracting {video_path}"
        )
    return out_path


def _source_image_for(path: Path, scratch_dir: Path, *, ffmpeg: str = "ffmpeg") -> Path:
    if path.suffix.lower() in IMAGE_EXTS:
        return path
    return _extract_video_frame(path, scratch_dir / f"{path.stem}.jpg", ffmpeg=ffmpeg)


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join([*current, word])
        bbox = draw.textbbox((0, 0), trial, font=font, stroke_width=2)
        if current and bbox[2] - bbox[0] > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines[:3]


def render_slide(
    source_image: Path,
    out_path: Path,
    *,
    hook: str,
    fonts_dir: Path,
    view_count_label: str | None = None,
    preset: str = "mirror_feed",
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_image) as original:
        canvas = _fit_cover(original, (CANVAS_W, CANVAS_H))

    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(fonts_dir, bold=True, size=54)
    stat_font = _load_font(fonts_dir, bold=True, size=64)
    small_font = _load_font(fonts_dir, bold=True, size=40)

    # A tiny vignette keeps white text readable without adding a visible card.
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((0, 0, CANVAS_W, 230), fill=(0, 0, 0, 72))
    od.rectangle((0, CANVAS_H - 230, CANVAS_W, CANVAS_H), fill=(0, 0, 0, 58))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(canvas)

    lines = _wrap_text(draw, hook, title_font, 820)
    line_h = 56
    y = 118 if preset != "minimal" else 92
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=title_font, stroke_width=3)
        x = (CANVAS_W - (bbox[2] - bbox[0])) // 2
        draw.text(
            (x, y),
            line,
            font=title_font,
            fill=(255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )
        y += line_h

    if view_count_label:
        draw.polygon(
            [(42, CANVAS_H - 118), (42, CANVAS_H - 54), (96, CANVAS_H - 86)],
            fill=(255, 255, 255),
        )
        draw.text(
            (118, CANVAS_H - 127),
            view_count_label,
            font=stat_font,
            fill=(255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )

    # Small carousel cue like IG grid screenshots.
    draw.rounded_rectangle(
        (CANVAS_W - 104, 50, CANVAS_W - 50, 104),
        radius=12,
        outline=(255, 255, 255),
        width=5,
    )
    draw.rounded_rectangle(
        (CANVAS_W - 86, 32, CANVAS_W - 32, 86), radius=12, fill=(255, 255, 255)
    )
    if preset == "minimal":
        draw.text(
            (40, CANVAS_H - 78),
            "slideshow",
            font=small_font,
            fill=(255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )

    canvas.convert("RGB").save(out_path, quality=94)
    return out_path


def _format_fake_views(index: int, rng: random.Random) -> str:
    if index == 0:
        return f"{rng.randint(1400, 9900):,}"
    if index % 3 == 0:
        return f"{rng.randint(70, 420)}.{rng.randint(1, 9)}K"
    return f"{rng.randint(18, 160)}.{rng.randint(1, 9)}K"


def render_grid_preview(
    slides: list[Path], out_path: Path, *, title: str, fonts_dir: Path, columns: int = 3
) -> Path:
    if not slides:
        raise ValueError("slides cannot be empty")
    columns = max(1, columns)
    rows = math.ceil(len(slides) / columns)
    cell_w = 360
    cell_h = 640
    grid = Image.new("RGB", (cell_w * columns, cell_h * rows), (0, 0, 0))
    for idx, slide in enumerate(slides):
        with Image.open(slide) as img:
            thumb = _fit_cover(img, (cell_w, cell_h))
        x = (idx % columns) * cell_w
        y = (idx // columns) * cell_h
        grid.paste(thumb, (x, y))

    draw = ImageDraw.Draw(grid)
    font = _load_font(fonts_dir, bold=True, size=78)
    lines = _wrap_text(draw, title, font, cell_w * columns - 160)
    box_h = 96 + len(lines) * 86
    box_w = cell_w * columns - 220
    x0 = (cell_w * columns - box_w) // 2
    y0 = max(70, min(grid.height - box_h - 80, grid.height // 3 - box_h // 2))
    draw.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=24, fill=(0, 0, 0))
    y = y0 + 44
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (cell_w * columns - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += 86

    out_path.parent.mkdir(parents=True, exist_ok=True)
    grid.save(out_path, quality=94)
    return out_path


def render_slideshow_video(
    slides: list[Path],
    out_path: Path,
    *,
    seconds_per_slide: float = 1.15,
    ffmpeg: str = "ffmpeg",
) -> Path:
    if not slides:
        raise ValueError("slides cannot be empty")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        list_path = tmp_dir / "slides.txt"
        lines: list[str] = []
        for slide in slides:
            lines.append(f"file '{slide.resolve()}'")
            lines.append(f"duration {seconds_per_slide:.3f}")
        lines.append(f"file '{slides[-1].resolve()}'")
        atomic_write_text(list_path, "\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-r",
            "30",
            "-an",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or "ffmpeg slideshow render failed"
            )
    return out_path


def build_slideshow(
    media_dir: Path,
    out_dir: Path,
    *,
    title: str,
    hooks: list[str] | None = None,
    count: int = 12,
    seed: int = 7,
    preset: str = "mirror_feed",
    reference_pattern_id: str | None = None,
    generation_id: str | None = None,
    render_video: bool = True,
    render_grid: bool = True,
    seconds_per_slide: float = 1.15,
    ffmpeg: str | None = None,
) -> SlideshowManifest:
    media = discover_media(media_dir)
    if not media:
        raise ValueError(f"no supported media found in {media_dir}")
    rng = random.Random(seed)
    selected = media[:]
    rng.shuffle(selected)
    selected = selected[: max(1, min(count, len(selected)))]
    hook_pool = [h.strip() for h in (hooks or DEFAULT_HOOKS) if h.strip()]
    if not hook_pool:
        hook_pool = DEFAULT_HOOKS

    out_dir = out_dir.expanduser().resolve()
    slides_dir = out_dir / "slides"
    scratch_dir = out_dir / ".frames"
    fonts_dir = Path(__file__).parent / "fonts"
    ffmpeg_bin = ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
    items: list[SlideshowItem] = []
    slide_paths: list[Path] = []

    for idx, source in enumerate(selected, start=1):
        src_image = _source_image_for(source, scratch_dir, ffmpeg=ffmpeg_bin)
        hook = hook_pool[(idx - 1) % len(hook_pool)]
        slide_path = slides_dir / f"slide_{idx:03d}.jpg"
        views = _format_fake_views(idx - 1, rng)
        render_slide(
            src_image,
            slide_path,
            hook=hook,
            fonts_dir=fonts_dir,
            view_count_label=views,
            preset=preset,
        )
        slide_paths.append(slide_path)
        items.append(
            SlideshowItem(
                source_path=str(source.resolve()),
                kind="image" if source.suffix.lower() in IMAGE_EXTS else "video_frame",
                source_hash=sha256_file(source),
                caption_hash=hashlib.sha256(
                    " ".join(hook.strip().lower().split()).encode("utf-8")
                ).hexdigest(),
                slide_path=str(slide_path),
                hook=hook,
                view_count_label=views,
            )
        )

    grid_path: Path | None = None
    if render_grid:
        grid_path = render_grid_preview(
            slide_paths, out_dir / "grid_preview.jpg", title=title, fonts_dir=fonts_dir
        )

    reel_path: Path | None = None
    if render_video:
        reel_path = render_slideshow_video(
            slide_paths,
            out_dir / "slideshow_reel.mp4",
            seconds_per_slide=seconds_per_slide,
            ffmpeg=ffmpeg_bin,
        )
    duration_seconds = (
        round(len(slide_paths) * seconds_per_slide, 3) if render_video else None
    )

    manifest = SlideshowManifest(
        schema="reel_factory.slideshow.v1",
        created_at=datetime.now(UTC).isoformat(),
        title=title,
        preset=preset,
        format="slideshow_pack",
        reference_pattern_id=reference_pattern_id,
        generation_id=generation_id,
        output_width=CANVAS_W,
        output_height=CANVAS_H,
        duration_seconds=duration_seconds,
        media_dir=str(media_dir.expanduser().resolve()),
        out_dir=str(out_dir),
        slide_count=len(items),
        reel_path=str(reel_path) if reel_path else None,
        grid_path=str(grid_path) if grid_path else None,
        items=items,
    )
    atomic_write_text((out_dir / "slideshow_manifest.json"), 
        json.dumps(asdict(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def _load_hooks(path: Path | None) -> list[str] | None:
    if not path:
        return None
    data = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        loaded = json.loads(data)
        if isinstance(loaded, list):
            return [str(x) for x in loaded]
        if isinstance(loaded, dict):
            hooks = loaded.get("hooks") or loaded.get("captions") or []
            return [str(x) for x in hooks]
    return [line.strip() for line in data.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--media-dir", required=True, help="Folder of source images/videos."
    )
    ap.add_argument(
        "--out-dir", required=True, help="Output folder for slides, MP4, and manifest."
    )
    ap.add_argument("--title", default="AI slideshow pack", help="Grid preview title.")
    ap.add_argument(
        "--hooks-file", type=Path, default=None, help="Optional .txt/.json hook list."
    )
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument(
        "--preset", choices=["mirror_feed", "minimal"], default="mirror_feed"
    )
    ap.add_argument("--reference-pattern-id", default=None)
    ap.add_argument("--generation-id", default=None)
    ap.add_argument("--seconds-per-slide", type=float, default=1.15)
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--no-grid", action="store_true")
    args = ap.parse_args(argv)

    manifest = build_slideshow(
        Path(args.media_dir),
        Path(args.out_dir),
        title=args.title,
        hooks=_load_hooks(args.hooks_file),
        count=args.count,
        seed=args.seed,
        preset=args.preset,
        reference_pattern_id=args.reference_pattern_id,
        generation_id=args.generation_id,
        render_video=not args.no_video,
        render_grid=not args.no_grid,
        seconds_per_slide=args.seconds_per_slide,
    )
    print(json.dumps(asdict(manifest), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
