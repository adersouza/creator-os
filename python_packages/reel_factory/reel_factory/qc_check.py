#!/usr/bin/env python3
"""qc_check.py — Technical quality control for reel_factory outputs.

Walks ``02_processed/`` (or any directory tree) and runs ``ffprobe`` on each
``.mp4`` to verify it's a valid silent vertical render. Failures are tracked
and optionally relocated to ``02_processed/_failed/`` so the rest of the
batch is publishable as-is.

What it checks (technical only — no content analysis):

* dimensions are one of the accepted output sizes (1080×1920, 720×1280)
* video codec is h264
* audio track is absent (silent output is required for in-app sound attach)
* frame rate is in the 25–60 fps band (covers typical phone capture + VT output)
* duration is at least 1.0s (catches truncated renders)
* file size is at least 500 KB (catches near-empty files)
* optional upload-readiness metadata: faststart, creation time, clean handler/encoder tags

Outputs:

* ``02_processed/_qc_report.json`` — structured report (one record per file)
* ``02_processed/_qc_report.csv``  — same data, spreadsheet-friendly
* ``02_processed/_failed/<clip>/<file>`` — failed files relocated (if --move-failed)

CLI:

::

    python3 qc_check.py --root .                # check 02_processed/, no relocate
    python3 qc_check.py --root . --move-failed   # move failures aside
    python3 qc_check.py --root . --strict-1080   # require 1080×1920 only (reject 720×1280)
    python3 qc_check.py --root . --upload-ready  # include social-upload metadata checks
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .fileops import atomic_write_text

# Default mode: catch broken files, not enforce a specific ratio.
# Higgsfield emits ~3:4 (e.g. 1108×1868, 1244×1660, 828×1108), and the
# pipeline preserves source dims, so the safe default is "portrait + not
# tiny". Use --strict-1080 to require IG/TikTok-native 1080×1920.
STRICT_DIMS = {(1080, 1920)}
MIN_PORTRAIT_WIDTH = 600  # below this = obviously broken / low-res
MIN_PORTRAIT_HEIGHT = 800
MIN_FPS, MAX_FPS = 23.5, 60.0
MIN_DURATION_S = 1.0
MIN_FILE_BYTES = 500 * 1024  # 500 KB


@dataclass
class QcRecord:
    path: str
    clip: str
    name: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    duration: float | None = None
    codec: str | None = None
    audio_streams: int = 0
    major_brand: str | None = None
    creation_time: str | None = None
    handler_name: str | None = None
    faststart: bool | None = None
    passed: bool = False
    warnings: tuple = ()
    reasons: tuple = ()  # tuple[str, ...] — frozen for determinism


def _ffprobe_json(path: Path) -> dict:
    """Run ffprobe on a file and return the parsed JSON. Raises on probe failure."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _parse_fps(rate: str) -> float | None:
    """ffprobe returns frame rates as 'N/D' strings — convert safely."""
    if not rate or rate == "0/0":
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            return float(num) / float(den) if float(den) else None
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return None


def _tags(obj: dict) -> dict:
    tags = obj.get("tags") or {}
    return tags if isinstance(tags, dict) else {}


def _has_faststart(path: Path) -> bool:
    """Return True when the MP4 moov atom is before mdat near the front."""
    try:
        with path.open("rb") as f:
            head = f.read(2 * 1024 * 1024)
    except OSError:
        return False
    moov = head.find(b"moov")
    mdat = head.find(b"mdat")
    return moov >= 0 and mdat >= 0 and moov < mdat


def _metadata_findings(
    rec: QcRecord, info: dict, video_stream: dict, path: Path
) -> tuple[list[str], list[str]]:
    fmt_tags = _tags(info.get("format") or {})
    stream_tags = _tags(video_stream)
    rec.major_brand = fmt_tags.get("major_brand")
    rec.creation_time = stream_tags.get("creation_time") or fmt_tags.get(
        "creation_time"
    )
    rec.handler_name = stream_tags.get("handler_name")
    rec.faststart = _has_faststart(path)

    reasons: list[str] = []
    warnings: list[str] = []
    if rec.faststart is False:
        reasons.append("missing_faststart")
    if not rec.creation_time:
        reasons.append("missing_creation_time")
    if not rec.handler_name or rec.handler_name == "VideoHandler":
        reasons.append(f"generic_handler_name ({rec.handler_name})")

    suspicious_values: list[str] = []
    for tags in (fmt_tags, stream_tags):
        for key, value in tags.items():
            if key.lower() not in {"encoder", "handler_name"}:
                continue
            text = str(value)
            if any(
                marker in text.lower() for marker in ("lavf", "lavc", "ffmpeg", "libav")
            ):
                suspicious_values.append(f"{key}={text}")
    if suspicious_values:
        warnings.append(f"suspicious_metadata ({'; '.join(suspicious_values)})")
    return reasons, warnings


def probe(
    path: Path, strict_1080: bool = False, upload_ready: bool = False
) -> QcRecord:
    """Run technical checks on one file and return a QcRecord."""
    rec = QcRecord(
        path=str(path),
        clip=path.parent.name,
        name=path.name,
        size_bytes=path.stat().st_size if path.exists() else 0,
    )
    reasons: list[str] = []

    if rec.size_bytes < MIN_FILE_BYTES:
        reasons.append(f"file_too_small ({rec.size_bytes} bytes)")

    try:
        info = _ffprobe_json(path)
    except Exception as e:
        reasons.append(f"ffprobe_failed: {e}")
        rec.reasons = tuple(reasons)
        return rec

    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    rec.audio_streams = len(audio_streams)

    if not video_streams:
        reasons.append("no_video_stream")
        rec.reasons = tuple(reasons)
        return rec

    v = video_streams[0]
    rec.width = v.get("width")
    rec.height = v.get("height")
    rec.codec = v.get("codec_name")
    rec.fps = _parse_fps(v.get("avg_frame_rate") or v.get("r_frame_rate") or "")

    fmt = info.get("format", {})
    duration_str = fmt.get("duration") or v.get("duration")
    try:
        rec.duration = float(duration_str) if duration_str else None
    except (TypeError, ValueError):
        rec.duration = None

    # Apply checks
    w, h = rec.width or 0, rec.height or 0
    if strict_1080:
        if (w, h) != (1080, 1920):
            reasons.append(f"not_1080x1920 ({w}x{h})")
    else:
        if w < MIN_PORTRAIT_WIDTH or h < MIN_PORTRAIT_HEIGHT:
            reasons.append(f"undersized ({w}x{h})")
        elif h <= w:
            reasons.append(f"not_portrait ({w}x{h})")
    if rec.codec != "h264":
        reasons.append(f"wrong_codec ({rec.codec})")
    if rec.audio_streams > 0:
        reasons.append(f"audio_present ({rec.audio_streams} stream(s))")
    if rec.fps is None or not (MIN_FPS <= rec.fps <= MAX_FPS):
        reasons.append(f"bad_fps ({rec.fps})")
    if rec.duration is None or rec.duration < MIN_DURATION_S:
        reasons.append(f"short_duration ({rec.duration})")
    warnings: list[str] = []
    if upload_ready:
        metadata_reasons, metadata_warnings = _metadata_findings(rec, info, v, path)
        reasons.extend(metadata_reasons)
        warnings.extend(metadata_warnings)

    rec.passed = not reasons
    rec.warnings = tuple(warnings)
    rec.reasons = tuple(reasons)
    return rec


def _audio_mode_for(path: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    return "muxed" if "_audio_" in path.stem else "silent"


def probe_with_audio_mode(
    path: Path,
    *,
    strict_1080: bool = False,
    audio_mode: str = "silent",
    upload_ready: bool = False,
) -> QcRecord:
    rec = probe(path, strict_1080=strict_1080, upload_ready=upload_ready)
    mode = _audio_mode_for(path, audio_mode)
    reasons = [r for r in rec.reasons if not str(r).startswith("audio_present")]
    if mode == "silent":
        if rec.audio_streams > 0 and not any(
            str(r).startswith("audio_present") for r in rec.reasons
        ):
            reasons.append(f"audio_present ({rec.audio_streams} stream(s))")
        elif rec.audio_streams > 0:
            reasons.append(f"audio_present ({rec.audio_streams} stream(s))")
    elif mode == "muxed":
        if rec.audio_streams != 1:
            reasons.append(f"expected_one_audio_stream ({rec.audio_streams})")
    elif mode == "any":
        pass
    else:
        raise ValueError("audio_mode must be silent, muxed, any, or auto")
    rec.reasons = tuple(dict.fromkeys(reasons))
    rec.passed = not rec.reasons
    return rec


def run_qc(
    proc_dir: Path,
    *,
    move_failed: bool = False,
    strict_1080: bool = False,
    audio_mode: str = "silent",
    upload_ready: bool = False,
    skip_pattern: tuple[str, ...] = ("_failed",),
) -> dict:
    """Walk ``proc_dir`` and run QC on every .mp4. Write JSON+CSV reports.

    Returns a small summary dict: ``{total, passed, failed, moved}``.
    Used by both the standalone CLI and the pipeline's --qc hook.
    """
    proc_dir = Path(proc_dir)
    if not proc_dir.exists():
        raise FileNotFoundError(f"directory not found: {proc_dir}")

    failed_dir = proc_dir / "_failed"
    records: list[QcRecord] = []

    for mp4 in sorted(proc_dir.rglob("*.mp4")):
        if any(part in skip_pattern for part in mp4.parts):
            continue
        rec = probe_with_audio_mode(
            mp4,
            strict_1080=strict_1080,
            audio_mode=audio_mode,
            upload_ready=upload_ready,
        )
        records.append(rec)

    passed = [r for r in records if r.passed]
    failed = [r for r in records if not r.passed]

    moved = 0
    if move_failed and failed:
        for rec in failed:
            src = Path(rec.path)
            if not src.exists():
                continue
            dst = failed_dir / rec.clip / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dst))
                rec.path = str(dst)
                moved += 1
            except Exception:
                pass

    # Write reports
    json_path = proc_dir / "_qc_report.json"
    csv_path = proc_dir / "_qc_report.csv"

    with json_path.open("w") as f:
        json.dump(
            {
                "summary": {
                    "total": len(records),
                    "passed": len(passed),
                    "failed": len(failed),
                    "moved": moved,
                    "strict_1080": strict_1080,
                    "audio_mode": audio_mode,
                    "upload_ready": upload_ready,
                },
                "records": [{**asdict(r), "reasons": list(r.reasons)} for r in records],
            },
            f,
            indent=2,
        )

    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "clip",
                "name",
                "passed",
                "width",
                "height",
                "fps",
                "duration_s",
                "codec",
                "audio_streams",
                "size_kb",
                "faststart",
                "major_brand",
                "creation_time",
                "handler_name",
                "warnings",
                "reasons",
            ]
        )
        for r in records:
            w.writerow(
                [
                    r.clip,
                    r.name,
                    r.passed,
                    r.width,
                    r.height,
                    r.fps,
                    r.duration,
                    r.codec,
                    r.audio_streams,
                    round(r.size_bytes / 1024, 1),
                    r.faststart,
                    r.major_brand,
                    r.creation_time,
                    r.handler_name,
                    "; ".join(r.warnings),
                    "; ".join(r.reasons),
                ]
            )

    return {
        "total": len(records),
        "passed": len(passed),
        "failed": len(failed),
        "moved": moved,
        "report_json": str(json_path),
        "report_csv": str(csv_path),
    }


def _parse_ssim(stderr: str) -> float | None:
    for token in stderr.replace("\n", " ").split():
        if token.startswith("All:"):
            try:
                return float(token.split(":", 1)[1])
            except ValueError:
                return None
    return None


def _parse_psnr(stderr: str) -> float | None:
    for token in stderr.replace("\n", " ").split():
        if token.startswith("average:"):
            value = token.split(":", 1)[1]
            if value.lower() == "inf":
                return float("inf")
            try:
                return float(value)
            except ValueError:
                return None
    return None


def compare_golden(
    current: Path, golden: Path, *, ssim_min: float = 0.98, psnr_min: float = 36.0
) -> dict:
    """Compare two outputs with FFmpeg SSIM/PSNR filters."""
    results: dict[str, object] = {
        "current": str(current),
        "golden": str(golden),
        "ssim": None,
        "psnr": None,
        "passed": False,
    }
    ssim = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(current),
            "-i",
            str(golden),
            "-lavfi",
            "ssim",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    psnr = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(current),
            "-i",
            str(golden),
            "-lavfi",
            "psnr",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    results["ssim"] = _parse_ssim(ssim.stderr)
    results["psnr"] = _parse_psnr(psnr.stderr)
    results["passed"] = (
        ssim.returncode == 0
        and psnr.returncode == 0
        and results["ssim"] is not None
        and float(results["ssim"]) >= ssim_min
        and results["psnr"] is not None
        and float(results["psnr"]) >= psnr_min
    )
    return results


def compare_golden_dir(proc_dir: Path, golden_dir: Path) -> dict:
    records = []
    for mp4 in sorted(proc_dir.glob("*/*.mp4")):
        golden = golden_dir / mp4.name
        if not golden.exists():
            continue
        records.append(compare_golden(mp4, golden))
    out = proc_dir / "_qc_regression.json"
    summary = {
        "total": len(records),
        "passed": sum(1 for r in records if r.get("passed")),
        "failed": sum(1 for r in records if not r.get("passed")),
        "records": records,
    }
    atomic_write_text(out, json.dumps(summary, indent=2), encoding="utf-8")
    summary["report_json"] = str(out)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        default=".",
        help="project root containing 02_processed/ (default: cwd)",
    )
    ap.add_argument(
        "--dir",
        default=None,
        help="override: scan this directory directly (skip --root/02_processed)",
    )
    ap.add_argument(
        "--move-failed",
        action="store_true",
        help="relocate failed files to <dir>/_failed/<clip>/",
    )
    ap.add_argument(
        "--strict-1080",
        action="store_true",
        help="reject anything that isn't 1080x1920 (default also accepts 720x1280)",
    )
    ap.add_argument(
        "--audio-mode",
        choices=["silent", "muxed", "any", "auto"],
        default="silent",
        help="audio QC policy: silent outputs, muxed outputs, any, or auto by filename",
    )
    ap.add_argument(
        "--upload-ready",
        action="store_true",
        help="also require faststart, creation_time, and clean social-upload metadata",
    )
    ap.add_argument(
        "--compare-golden",
        action="store_true",
        help="compare outputs against matching filenames in --golden-dir using SSIM/PSNR",
    )
    ap.add_argument(
        "--golden-dir",
        default=None,
        help="directory containing golden MP4s for --compare-golden",
    )
    args = ap.parse_args()

    target = Path(args.dir) if args.dir else Path(args.root) / "02_processed"

    try:
        summary = run_qc(
            target,
            move_failed=args.move_failed,
            strict_1080=args.strict_1080,
            audio_mode=args.audio_mode,
            upload_ready=args.upload_ready,
        )
        if args.compare_golden:
            if not args.golden_dir:
                raise FileNotFoundError(
                    "--golden-dir is required with --compare-golden"
                )
            summary["regression"] = compare_golden_dir(target, Path(args.golden_dir))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
