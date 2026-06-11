"""post_render.py — post-pipeline summarization.

After all variations for a clip are rendered, this module writes:
  - 02_processed/<clip_id>/_index.csv   — every output's metadata in a row
                                            so you can sort/filter/schedule
                                            from a spreadsheet.
  - 02_processed/<clip_id>/_contact_sheet.png — labeled grid of every output's
                                            mid-clip frame for spacebar QA in
                                            Finder.

Both regenerate idempotently on every full pipeline run.
"""
from __future__ import annotations
import csv, json, math, shutil, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

_FFMPEG_FULL = Path("/opt/homebrew/opt/ffmpeg-full/bin")
FF = str(_FFMPEG_FULL / "ffmpeg") if (_FFMPEG_FULL / "ffmpeg").exists() else shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = str(_FFMPEG_FULL / "ffprobe") if (_FFMPEG_FULL / "ffprobe").exists() else shutil.which("ffprobe") or "ffprobe"
PROJECT_ROOT = Path(__file__).resolve().parent


def _read_caption_meta(out_dir: Path) -> dict[str, dict]:
    """Map mp4_basename → metadata read from the manifest entry / sidecar files."""
    manifest_path = out_dir.parent.parent / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text())
    except Exception:
        return {}
    meta: dict[str, dict] = {}
    for vid_key, vid in data.get("videos", {}).items():
        for var in vid.get("variations", []):
            mp4 = Path(var.get("output_path", "")).name
            if not mp4:
                continue
            meta[mp4] = {
                "recipe": var.get("recipe"),
                "caption_text": var.get("caption_text", ""),
                "size_bytes": var.get("output_size_bytes", 0),
                "duration": var.get("duration_sec", 0),
                "review_state": var.get("review_state", "draft"),
            }
    return meta


def _aux_meta_from_filename(mp4: Path) -> dict:
    """Extract hook_idx, color from the output filename pattern
    clip_NNN_h<idx>_<recipe>_<color>_<hash>.mp4."""
    parts = mp4.stem.split("_")
    out = {}
    for p in parts:
        if p.startswith("h") and p[1:].isdigit():
            out["hook_idx"] = int(p[1:])
        elif p in ("light", "dark"):
            out["color"] = p
    return out


def _probe_duration(mp4: Path) -> float:
    try:
        out = subprocess.check_output([
            FFPROBE, "-v", "0", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(mp4),
        ], stderr=subprocess.DEVNULL).decode().strip()
        return float(out)
    except Exception:
        return 0.0


def write_csv_index(out_dir: Path) -> Path | None:
    """Write _index.csv listing every MP4 in out_dir with its metadata."""
    mp4s = sorted(out_dir.glob("*.mp4"))
    if not mp4s:
        return None
    meta = _read_caption_meta(out_dir)

    csv_path = out_dir / "_index.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "hook_idx", "recipe", "color",
                    "caption_text", "size_mb", "duration_sec"])
        for mp4 in mp4s:
            m = meta.get(mp4.name, {})
            aux = _aux_meta_from_filename(mp4)
            size_mb = round(mp4.stat().st_size / 1024 / 1024, 2)
            duration = float(m.get("duration") or _probe_duration(mp4))
            w.writerow([
                mp4.name,
                aux.get("hook_idx", ""),
                m.get("recipe", ""),
                aux.get("color", ""),
                m.get("caption_text", "").replace("\n", " / "),
                size_mb,
                round(duration, 2),
            ])
    return csv_path


def write_contact_sheet(out_dir: Path,
                        thumb_w: int = 270,
                        thumb_h: int = 480,
                        cols: int = 5) -> Path | None:
    """Generate _contact_sheet.png — labeled grid of mid-clip frames for
    every MP4 in out_dir. Frame label = "h<idx> <recipe>" so each cell
    is identifiable without opening the file."""
    mp4s = sorted(out_dir.glob("*.mp4"))
    if not mp4s:
        return None
    meta = _read_caption_meta(out_dir)

    tmp_dir = out_dir / "._sheet_tmp"
    tmp_dir.mkdir(exist_ok=True)
    for f in tmp_dir.glob("*"):
        f.unlink()

    cells: list[Path] = []
    for i, mp4 in enumerate(mp4s):
        aux = _aux_meta_from_filename(mp4)
        # Recipe extracted from filename between the hook tag and color tag.
        # e.g. clip_001_h00_v05_hflip_light_xxx.mp4 → recipe = v05_hflip
        parts = mp4.stem.split("_")
        try:
            h_pos = next(j for j, p in enumerate(parts) if p.startswith("h") and p[1:].isdigit())
            color_pos = next(j for j, p in enumerate(parts) if p in ("light", "dark"))
            recipe = "_".join(parts[h_pos + 1:color_pos])
        except StopIteration:
            recipe = ""
        review_state = meta.get(mp4.name, {}).get("review_state", "draft")
        label = (
            f"h{aux.get('hook_idx', '?'):02d} {recipe} {review_state}"
            if isinstance(aux.get('hook_idx'), int) else mp4.stem[:24]
        )

        frame = tmp_dir / f"frame_{i:03d}.png"
        thumb = tmp_dir / f"cell_{i:03d}.png"
        bar_h = 50
        subprocess.run([
            FF, "-hide_banner", "-nostdin", "-loglevel", "error",
            "-ss", "1.5", "-i", str(mp4), "-frames:v", "1",
            "-vf", f"scale={thumb_w}:{thumb_h}",
            "-y", str(frame),
        ], check=True)
        font_path = PROJECT_ROOT / "fonts" / "Onest-Variable.ttf"
        try:
            font = ImageFont.truetype(str(font_path), 18)
        except Exception:
            font = ImageFont.load_default()
        canvas = Image.new("RGB", (thumb_w, thumb_h + bar_h), (17, 17, 17))
        frame_img = Image.open(frame).convert("RGB")
        canvas.paste(frame_img, (0, bar_h))
        draw = ImageDraw.Draw(canvas)
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text(((thumb_w - (bbox[2] - bbox[0])) // 2, 14), label, fill=(255, 255, 255), font=font)
        canvas.save(thumb)
        cells.append(thumb)

    # Pad to fill grid
    rows = math.ceil(len(cells) / cols)
    while len(cells) < cols * rows:
        blank = tmp_dir / "blank.png"
        if not blank.exists():
            subprocess.run([
                FF, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c=0x111111:s={thumb_w}x{thumb_h+50}:d=1",
                "-frames:v", "1", "-y", str(blank),
            ], check=True)
        cells.append(blank)

    inputs: list[str] = []
    for c in cells:
        inputs += ["-i", str(c)]

    rows_fc = []
    for r in range(rows):
        streams = "".join(f"[{r*cols + c}:v]" for c in range(cols))
        rows_fc.append(f"{streams}hstack=inputs={cols}[r{r}]")
    if rows == 1:
        fc = rows_fc[0] + ";[r0]copy[out]"
    else:
        vstack = "".join(f"[r{r}]" for r in range(rows)) + f"vstack=inputs={rows}[out]"
        fc = ";".join(rows_fc) + ";" + vstack

    sheet_path = out_dir / "_contact_sheet.png"
    subprocess.run([
        FF, "-hide_banner", "-nostdin", "-loglevel", "error",
        *inputs, "-filter_complex", fc, "-map", "[out]", "-y", str(sheet_path),
    ], check=True)

    # Cleanup tmp cells
    for f in tmp_dir.glob("*"):
        f.unlink()
    tmp_dir.rmdir()

    return sheet_path


def summarize_clip_outputs(out_dir: Path) -> dict:
    """Generate both CSV index + contact sheet for one clip's output dir."""
    csv_path = write_csv_index(out_dir)
    sheet_path = write_contact_sheet(out_dir)
    return {
        "csv": str(csv_path) if csv_path else None,
        "sheet": str(sheet_path) if sheet_path else None,
        "count": len(list(out_dir.glob("*.mp4"))),
    }
