from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from .media import ffprobe_video


ProbeVideo = Callable[[Path], dict[str, Any]]
ProbeImage = Callable[[Path], dict[str, Any]]
DetectBlack = Callable[[Path], list[dict[str, float]]]


REQUIRED_BUNDLE_FILES = [
    "assets/01_reference_frames.jpg",
    "assets/02_soul_base_still.png",
    "assets/03_best_2x3_image.png",
    "assets/04_best_2x3_grid_video.mp4",
    "assets/05_best_2x3_vertical_sequence.mp4",
    "assets/06_kling_single_outfit_motion.mp4",
    "assets/07_campaign_passthrough.mp4",
    "assets/08_motion_sequence_frames.jpg",
    "assets/09_campaign_passthrough_frames.jpg",
    "final_visual_audit_sheet.jpg",
    "generated_asset_lineage.json",
    "proof_completion_report.json",
    "goal_completion_audit.json",
    "index.html",
]


EXPECTED_VIDEOS = {
    "assets/04_best_2x3_grid_video.mp4": {
        "width": 1620,
        "height": 1920,
        "duration": 5.0,
        "durationTolerance": 0.35,
        "audio": False,
    },
    "assets/05_best_2x3_vertical_sequence.mp4": {
        "width": 1080,
        "height": 1920,
        "duration": 6.0,
        "durationTolerance": 0.35,
        "audio": False,
    },
    "assets/06_kling_single_outfit_motion.mp4": {
        "width": 720,
        "height": 1280,
        "duration": 5.04,
        "durationTolerance": 0.5,
        "audio": False,
    },
    "assets/07_campaign_passthrough.mp4": {
        "width": 1080,
        "height": 1920,
        "duration": 6.0,
        "durationTolerance": 0.35,
        "audio": False,
    },
}


EXPECTED_IMAGES = {
    "assets/03_best_2x3_image.png": {"width": 1620, "height": 1920},
    "final_visual_audit_sheet.jpg": {"width": 1620, "minHeight": 5000},
}


def verify_proof_bundle(
    bundle: Path,
    *,
    probe_video: ProbeVideo = ffprobe_video,
    probe_image: ProbeImage | None = None,
    detect_black: DetectBlack | None = None,
) -> dict[str, Any]:
    bundle = bundle.expanduser()
    image_probe = probe_image or probe_image_dimensions
    black_detector = detect_black or detect_black_segments
    checks: list[dict[str, Any]] = []

    _check(bundle.exists() and bundle.is_dir(), "bundle.exists", checks, path=str(bundle))
    for relative in REQUIRED_BUNDLE_FILES:
        path = bundle / relative
        _check(path.exists(), f"file.{relative}", checks, path=str(path))

    if not _checks_ok(checks):
        return _result(bundle, checks)

    for relative, expected in EXPECTED_IMAGES.items():
        path = bundle / relative
        image = image_probe(path)
        _check(bool(image.get("valid")), f"image.{relative}.valid", checks, probe=image)
        if not image.get("valid"):
            continue
        width = int(image.get("width") or 0)
        height = int(image.get("height") or 0)
        min_height = int(expected.get("minHeight") or expected.get("height") or 0)
        _check(
            width == int(expected["width"]) and height >= min_height,
            f"image.{relative}.dimensions",
            checks,
            expected=expected,
            actual={"width": width, "height": height},
        )

    for relative, expected in EXPECTED_VIDEOS.items():
        path = bundle / relative
        probe = probe_video(path)
        _check(bool(probe.get("valid")), f"video.{relative}.valid", checks, probe=_probe_summary(probe))
        if not probe.get("valid"):
            continue
        _check(
            int(probe.get("width") or 0) == int(expected["width"])
            and int(probe.get("height") or 0) == int(expected["height"]),
            f"video.{relative}.dimensions",
            checks,
            expected={"width": expected["width"], "height": expected["height"]},
            actual={"width": probe.get("width"), "height": probe.get("height")},
        )
        duration = float(probe.get("duration_seconds") or 0)
        _check(
            abs(duration - float(expected["duration"])) <= float(expected["durationTolerance"]),
            f"video.{relative}.duration",
            checks,
            expected=expected["duration"],
            actual=duration,
        )
        has_audio = _probe_has_audio(probe)
        _check(
            has_audio is bool(expected["audio"]),
            f"video.{relative}.audio",
            checks,
            expectedAudio=expected["audio"],
            actualAudio=has_audio,
        )
        black_segments = black_detector(path)
        _check(
            not black_segments,
            f"video.{relative}.no_black_segments",
            checks,
            segments=black_segments,
        )

    lineage = _read_json(bundle / "generated_asset_lineage.json")
    score = lineage.get("quality", {}).get("promptScore", {}) if isinstance(lineage, dict) else {}
    _check(
        score.get("status") == "pass",
        "lineage.prompt_score.pass",
        checks,
        actual=score.get("status"),
    )
    _check(
        score.get("warnings") in ([], None),
        "lineage.prompt_score.no_warnings",
        checks,
        actual=score.get("warnings"),
    )

    report = _read_json(bundle / "proof_completion_report.json")
    accepted_assets = report.get("acceptedAssets") or report.get("accepted_assets")
    _check(
        bool(accepted_assets) if isinstance(report, dict) else False,
        "report.accepted_assets.present",
        checks,
    )

    audit = _read_json(bundle / "goal_completion_audit.json")
    audit_status = str(audit.get("status") or "") if isinstance(audit, dict) else ""
    _check(
        audit_status.startswith("ready_for_user_visual_acceptance"),
        "audit.visual_acceptance_pending",
        checks,
        actual=audit_status,
    )

    return _result(bundle, checks)


def _check(ok: bool, name: str, checks: list[dict[str, Any]], **details: Any) -> None:
    item = {"name": name, "status": "pass" if ok else "fail"}
    if details:
        item["details"] = details
    checks.append(item)


def _checks_ok(checks: list[dict[str, Any]]) -> bool:
    return all(check["status"] == "pass" for check in checks)


def _result(bundle: Path, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [check for check in checks if check["status"] != "pass"]
    return {
        "schema": "reference_factory.proof_bundle_verification.v1",
        "status": "ok" if not failures else "failed",
        "bundlePath": str(bundle),
        "passed": len(checks) - len(failures),
        "failed": len(failures),
        "checks": checks,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _probe_summary(probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": probe.get("valid"),
        "width": probe.get("width"),
        "height": probe.get("height"),
        "duration_seconds": probe.get("duration_seconds"),
        "error": probe.get("error"),
    }


def _probe_has_audio(probe: dict[str, Any]) -> bool:
    raw = probe.get("probe_json")
    if not isinstance(raw, dict):
        return False
    return any(stream.get("codec_type") == "audio" for stream in raw.get("streams") or [])


def probe_image_dimensions(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return {"valid": False, "error": (result.stderr or result.stdout).strip()[:1000]}
    width: int | None = None
    height: int | None = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("pixelWidth:"):
            width = _safe_int(line.split(":", 1)[1])
        elif line.startswith("pixelHeight:"):
            height = _safe_int(line.split(":", 1)[1])
    return {
        "valid": bool(width and height),
        "width": width,
        "height": height,
        "error": None if width and height else "sips did not report dimensions",
    }


def detect_black_segments(path: Path) -> list[dict[str, float]]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-vf",
        "blackdetect=d=0.25:pix_th=0.10",
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    output = "\n".join([result.stdout or "", result.stderr or ""])
    segments: list[dict[str, float]] = []
    for line in output.splitlines():
        if "black_start:" not in line:
            continue
        segment: dict[str, float] = {}
        for token in line.split():
            if token.startswith("black_start:"):
                segment["start"] = _safe_float(token.split(":", 1)[1])
            elif token.startswith("black_end:"):
                segment["end"] = _safe_float(token.split(":", 1)[1])
            elif token.startswith("black_duration:"):
                segment["duration"] = _safe_float(token.split(":", 1)[1])
        if segment:
            segments.append(segment)
    return segments


def _safe_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None


def _safe_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0
