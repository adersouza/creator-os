#!/usr/bin/env python3
"""Heuristic visual QA for AI-generated reel outputs."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
_YUNET_MODEL_PATH = (
    Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
)


@dataclass
class AiQcRecord:
    filename: str
    path: str
    warnings: list[str]
    scores: dict[str, float | int | None]
    frame_details: list[dict[str, Any]]
    visualQcStatus: str
    visualQcDependencyStatus: dict[str, str]
    visualQcWarnings: list[str]
    identityVerificationStatus: str | None = None


def record_from_scores(
    filename: str, path: str, scores: dict[str, float | int | None]
) -> AiQcRecord:
    warnings: list[str] = []
    blur = scores.get("blur_min")
    jump = scores.get("jump_max")
    text = scores.get("text_edge_score")
    face_var = scores.get("face_count_variance")
    if isinstance(blur, (int, float)) and blur < 35:
        warnings.append("possible_blur_or_low_detail")
    if isinstance(jump, (int, float)) and jump > 45:
        warnings.append("possible_frame_jump_or_flicker")
    if isinstance(text, (int, float)) and text > 0.12:
        warnings.append("possible_text_or_watermark")
    if isinstance(face_var, (int, float)) and face_var > 0:
        warnings.append("face_count_inconsistent")
    if scores.get("opencv_available") == 0:
        warnings.append("opencv_unavailable")
    dependency_status = {
        "opencv": "available" if scores.get("opencv_available") == 1 else "unavailable",
        "frames": "available"
        if int(scores.get("frame_count") or 0) > 0
        else "unavailable",
        "ocr": "available" if scores.get("ocr_available") == 1 else "unavailable",
        "faceDetection": "available"
        if scores.get("face_detection_available") == 1
        else "unavailable",
    }
    if (
        dependency_status["opencv"] == "unavailable"
        or dependency_status["frames"] == "unavailable"
    ):
        status = "unavailable"
    elif warnings:
        status = "failed"
    else:
        status = "passed"
    return AiQcRecord(
        filename=filename,
        path=path,
        warnings=warnings,
        scores=scores,
        frame_details=[],
        visualQcStatus=status,
        visualQcDependencyStatus=dependency_status,
        visualQcWarnings=warnings,
    )


def sample_positions(count: int = 6) -> list[float]:
    if count <= 1:
        return [0.0]
    return [round(v, 3) for v in (0.0, 0.2, 0.4, 0.6, 0.8, 0.95)[:count]]


def _duration(video: Path) -> float | None:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return None


def _extract_frames(
    video: Path, out_dir: Path, count: int = 6
) -> list[tuple[float, Path]]:
    duration = _duration(video) or 0.0
    frames: list[tuple[float, Path]] = []
    for idx, pos in enumerate(sample_positions(count), start=1):
        out = out_dir / f"frame_{idx:02d}.jpg"
        seek = max(0.0, duration * pos) if duration else float(idx - 1)
        cmd = [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            f"{seek:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(out),
        ]
        subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        if out.exists():
            frames.append((pos, out))
    return frames


def _ocr_text(frame_path: Path) -> str | None:
    try:
        import pytesseract  # type: ignore
    except Exception:
        return None
    try:
        text = pytesseract.image_to_string(str(frame_path), timeout=3)
    except Exception:
        return None
    return " ".join(text.split())


def _face_count(frame_path: Path) -> int | None:
    if not _YUNET_MODEL_PATH.exists():
        return None
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(
        model=str(_YUNET_MODEL_PATH),
        config="",
        input_size=(w, h),
        score_threshold=0.5,
        nms_threshold=0.3,
        top_k=10,
    )
    _, faces = det.detect(img)
    return 0 if faces is None else int(len(faces))


def analyze_video(video: Path) -> AiQcRecord:
    try:
        import cv2  # type: ignore
    except ImportError:
        return record_from_scores(video.name, str(video), {"opencv_available": 0})

    with tempfile.TemporaryDirectory(prefix="ai_qc_") as tmp:
        frames = _extract_frames(video, Path(tmp))
        if not frames:
            return record_from_scores(
                video.name, str(video), {"opencv_available": 1, "frame_count": 0}
            )

        blur_scores: list[float] = []
        jump_scores: list[float] = []
        text_scores: list[float] = []
        face_counts: list[int] = []
        frame_details: list[dict[str, Any]] = []
        ocr_hits = 0
        ocr_available = None
        prev = None
        for pos, frame in frames:
            img = cv2.imread(str(frame))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            blur_scores.append(blur_score)
            jump_score = None
            if prev is not None and prev.shape == gray.shape:
                jump_score = float(cv2.absdiff(prev, gray).mean())
                jump_scores.append(jump_score)
            prev = gray

            h, w = gray.shape
            crop = gray[int(h * 0.08) : int(h * 0.92), int(w * 0.05) : int(w * 0.95)]
            edges = cv2.Canny(crop, 80, 180)
            text_score = float((edges > 0).mean())
            text_scores.append(text_score)
            ocr_text = _ocr_text(frame)
            if ocr_text is not None:
                ocr_available = True
                if len(ocr_text) >= 4:
                    ocr_hits += 1
            elif ocr_available is None:
                ocr_available = False
            face_count = _face_count(frame)
            if face_count is not None:
                face_counts.append(face_count)
            frame_details.append(
                {
                    "position": pos,
                    "frame": frame.name,
                    "blur": round(blur_score, 3),
                    "jump": round(jump_score, 3) if jump_score is not None else None,
                    "textEdgeScore": round(text_score, 4),
                    "ocrTextDetected": bool(ocr_text and len(ocr_text) >= 4),
                    "faceCount": face_count,
                }
            )

        face_variance = None
        if face_counts:
            face_variance = max(face_counts) - min(face_counts)
        scores: dict[str, float | int | None] = {
            "opencv_available": 1,
            "frame_count": len(frames),
            "blur_min": min(blur_scores) if blur_scores else None,
            "blur_mean": sum(blur_scores) / len(blur_scores) if blur_scores else None,
            "jump_max": max(jump_scores) if jump_scores else 0,
            "text_edge_score": max(text_scores) if text_scores else None,
            "ocr_available": 1 if ocr_available else 0,
            "ocr_text_frames": ocr_hits,
            "face_detection_available": 1 if face_counts else 0,
            "face_count_variance": face_variance,
        }
        record = record_from_scores(video.name, str(video), scores)
        if ocr_hits:
            record.warnings.append("possible_ocr_text_or_watermark")
        record.frame_details = frame_details
        return record


def run_ai_qc(
    root: Path, *, clip: str | None = None, strict: bool = False
) -> dict[str, Any]:
    root = Path(root).resolve()
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
    all_records: list[dict[str, Any]] = []
    reports: list[str] = []
    for clip_dir in clip_dirs:
        if not clip_dir.exists():
            continue
        records = [
            analyze_video(path)
            for path in sorted(clip_dir.glob("*.mp4"))
            if "_audio_" not in path.stem
        ]
        payload = {
            "schema": "reel_factory.ai_visual_qc.v1",
            "clip": clip_dir.name,
            "strict": bool(strict),
            "summary": {
                "total": len(records),
                "warned": sum(1 for rec in records if rec.warnings),
                "passed": sum(1 for rec in records if rec.visualQcStatus == "passed"),
                "failed": sum(1 for rec in records if rec.visualQcStatus == "failed"),
                "unavailable": sum(
                    1 for rec in records if rec.visualQcStatus == "unavailable"
                ),
            },
            "records": [asdict(rec) for rec in records],
        }
        report = clip_dir / "_ai_qc.json"
        report.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        reports.append(str(report))
        all_records.extend(payload["records"])
    return {
        "schema": "reel_factory.ai_visual_qc_summary.v1",
        "strict": bool(strict),
        "summary": {
            "total": len(all_records),
            "warned": sum(1 for rec in all_records if rec.get("warnings")),
            "passed": sum(
                1 for rec in all_records if rec.get("visualQcStatus") == "passed"
            ),
            "failed": sum(
                1 for rec in all_records if rec.get("visualQcStatus") == "failed"
            ),
            "unavailable": sum(
                1 for rec in all_records if rec.get("visualQcStatus") == "unavailable"
            ),
        },
        "reports": reports,
        "records": all_records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--clip")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    print(
        json.dumps(
            run_ai_qc(Path(args.root), clip=args.clip, strict=args.strict),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
