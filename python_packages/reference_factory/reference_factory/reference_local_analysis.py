from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .db import json_load
from .identity import stable_id
from .reference_analysis import (
    _classify_reference_format,
    _store_pattern_and_analysis,
)
from .reference_analysis_queue import queue_reference_analysis
from .reference_intake_contracts import (
    ANALYSIS_SCHEMA,
    DEFAULT_INTAKE_PROFILE,
    PATTERN_CARD_SCHEMA,
    _norm,
)
from .timeutil import now_iso


def analyze_reference_local(
    conn: Connection,
    source_root: Path,
    *,
    data_root: Path,
    platform: str = "instagram",
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    media_kinds: list[str] | None = None,
    limit: int | None = None,
    ffprobe: str = "ffprobe",
    ffmpeg: str = "ffmpeg",
    creative_plan_id: str | None = None,
) -> dict[str, object]:
    queued = queue_reference_analysis(
        conn,
        source_root,
        data_root=data_root,
        platform=platform,
        provider_target="local",
        intake_profile=intake_profile,
        media_kinds=media_kinds or ["video"],
        limit=limit,
        creative_plan_id=creative_plan_id,
    )
    rows = conn.execute(
        """
        SELECT raj.*, sf.path, sf.account, sf.file_name, sf.kind, sf.size_bytes
        FROM reference_analysis_jobs raj
        JOIN source_files sf ON sf.reference_id = raj.reference_id
        WHERE raj.provider_target = 'local'
          AND sf.path LIKE ?
        ORDER BY raj.updated_at DESC
        LIMIT ?
        """,
        (
            str(Path(source_root).expanduser().resolve()) + "%",
            max(1, limit or int(queued.get("queued") or 1)),
        ),
    ).fetchall()
    timestamp = now_iso()
    analyzed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in rows:
        job = dict(row)
        try:
            analysis = _local_video_analysis(
                job,
                data_root=data_root,
                platform=platform,
                ffprobe=ffprobe,
                ffmpeg=ffmpeg,
            )
            _store_pattern_and_analysis(
                conn, job=job, analysis=analysis, provider="local", timestamp=timestamp
            )
            analyzed.append(
                {
                    "referenceId": job["reference_id"],
                    "analysisId": analysis["id"],
                    "patternCardId": analysis["patternCard"]["id"],
                }
            )
        except (
            Exception
        ) as exc:  # pragma: no cover - defensive surface for operator CLI
            errors.append({"referenceId": job.get("reference_id"), "error": str(exc)})
    conn.commit()
    export = export_video_analyses(conn, data_root=data_root, provider="local")
    return {
        "schema": "reference_factory.analyze_reference_local.v1",
        "sourceRoot": str(Path(source_root).expanduser().resolve()),
        "platform": _norm(platform),
        "intakeProfile": _norm(intake_profile),
        "creativePlanId": creative_plan_id,
        "queued": queued.get("queued"),
        "analyzed": len(analyzed),
        "errors": errors,
        "export": export,
        "items": analyzed,
    }


def export_video_analyses(
    conn: Connection, *, data_root: Path, provider: str | None = None, limit: int = 100
) -> dict[str, object]:
    output_dir = data_root / "reference_intake"
    output_dir.mkdir(parents=True, exist_ok=True)
    where = "WHERE rva.provider = ?" if provider else ""
    params: tuple[Any, ...] = ((_norm(provider),) if provider else ()) + (limit,)
    rows = conn.execute(
        f"""
        SELECT rva.*, sf.path, sf.file_name, sf.account
        FROM reference_video_analyses rva
        JOIN source_files sf ON sf.reference_id = rva.reference_id
        {where}
        ORDER BY rva.updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    analyses = []
    for row in rows:
        item = dict(row)
        analysis = json_load(item["analysis_json"], {})
        analysis.setdefault("sourcePath", item.get("path"))
        analysis.setdefault("fileName", item.get("file_name"))
        analysis.setdefault("account", item.get("account"))
        analyses.append(analysis)
    payload = {
        "schema": "reference_factory.video_analysis_export.v1",
        "count": len(analyses),
        "items": analyses,
    }
    suffix = f"_{_norm(provider)}" if provider else ""
    path = output_dir / f"video_analyses{suffix}.json"
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "schema": "reference_factory.export_video_analyses.v1",
        "count": len(analyses),
        "jsonPath": str(path),
    }


def _local_video_analysis(
    job: dict[str, Any], *, data_root: Path, platform: str, ffprobe: str, ffmpeg: str
) -> dict[str, Any]:
    source = Path(job["path"]).expanduser()
    probe = _probe_media(source, ffprobe=ffprobe)
    frame_dir = data_root / "reference_intake" / "frames" / job["reference_id"]
    frames = _extract_reference_frames(
        source,
        frame_dir=frame_dir,
        duration=probe.get("durationSeconds"),
        ffmpeg=ffmpeg,
    )
    filename_text = " ".join(
        str(value or "") for value in (job.get("file_name"), job.get("account"), source)
    ).lower()
    format_type = _classify_reference_format(job, {"summary": filename_text})
    frame_analysis = _analyze_reference_frame_pixels(frames, probe)
    format_type = _format_from_local_frame_analysis(format_type, probe, frame_analysis)
    energy = str(frame_analysis.get("energy") or _energy_from_probe(probe))
    scene_cuts = _detect_scene_cuts(
        source, duration=probe.get("durationSeconds"), ffmpeg=ffmpeg
    )
    ocr_text = _sidecar_text(source)
    pattern = _pattern_card_from_local(
        job,
        platform=platform,
        probe=probe,
        frame_samples=frames,
        format_type=format_type,
        energy=energy,
        ocr_text=ocr_text,
        frame_analysis=frame_analysis,
        scene_cuts=scene_cuts,
    )
    analysis_id = stable_id(
        "reference_video_analysis",
        job["reference_id"],
        "local",
        probe.get("durationSeconds"),
        format_type,
    )
    return {
        "schema": ANALYSIS_SCHEMA,
        "id": analysis_id,
        "referenceId": job["reference_id"],
        "provider": "local",
        "status": "pattern_ready",
        "media": probe,
        "signals": {
            "frameSamples": frames,
            "framePixelAnalysis": frame_analysis,
            "sceneCuts": scene_cuts,
            "motion": {
                "energy": energy,
                "method": frame_analysis.get("method")
                if frame_analysis.get("status") == "analyzed"
                else "duration_resolution_heuristic",
                "meanFrameDelta": frame_analysis.get("meanFrameDelta"),
            },
            "ocrText": ocr_text,
            "audioPresence": {"hasAudio": probe.get("hasAudio")},
            "transcript": _sidecar_text(source.with_suffix(".transcript.txt")),
            "dedupe": {
                "frameSampleCount": len(frames),
                "method": "local_frame_manifest_v1",
            },
        },
        "patternCard": pattern,
        "raw": {"probe": probe},
    }


def _probe_media(source: Path, *, ffprobe: str) -> dict[str, Any]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(source),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), {}
    )
    duration = _float(video.get("duration")) or _float(
        (data.get("format") or {}).get("duration")
    )
    width = int(video.get("width") or 0) or None
    height = int(video.get("height") or 0) or None
    return {
        "path": str(source),
        "durationSeconds": duration,
        "width": width,
        "height": height,
        "codec": video.get("codec_name"),
        "aspectRatio": round(width / height, 4) if width and height else None,
        "hasAudio": any(stream.get("codec_type") == "audio" for stream in streams),
        "streamCount": len(streams),
    }


def _extract_reference_frames(
    source: Path, *, frame_dir: Path, duration: float | None, ffmpeg: str
) -> list[dict[str, Any]]:
    frame_dir.mkdir(parents=True, exist_ok=True)
    duration = duration if duration and duration > 0 else 6.0
    times = sorted(
        {
            round(max(0.0, min(duration * ratio, max(duration - 0.05, 0.0))), 3)
            for ratio in (0.15, 0.5, 0.85)
        }
    )
    frames: list[dict[str, Any]] = []
    for index, time_sec in enumerate(times, start=1):
        out = frame_dir / f"frame_{index:02d}.jpg"
        if not out.exists():
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss",
                    str(time_sec),
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        frames.append(
            {
                "timeSec": time_sec,
                "role": f"sample_{index}",
                "path": str(out),
                "exists": out.exists(),
            }
        )
    return frames


def _detect_scene_cuts(
    source: Path, *, duration: float | None, ffmpeg: str
) -> list[float]:
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(source),
        "-vf",
        "select='gt(scene,0.35)',showinfo",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return _scene_cut_guesses(duration)
    cuts = {0.0}
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr):
        cut = round(float(match.group(1)), 2)
        if cut > 0 and (not duration or cut < duration):
            cuts.add(cut)
    return sorted(cuts) or _scene_cut_guesses(duration)


def _analyze_reference_frame_pixels(
    frame_samples: list[dict[str, Any]], probe: dict[str, Any]
) -> dict[str, Any]:
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {
            "status": "unavailable",
            "method": "local_frame_pixel_analysis_v1",
            "reason": "Pillow is not installed for reference_factory local analysis.",
        }

    frames: list[dict[str, Any]] = []
    small_frames = []
    for sample in frame_samples:
        path = Path(str(sample.get("path") or ""))
        if not path.exists():
            continue
        try:
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                small = rgb.resize((64, 64))
                stat = ImageStat.Stat(small)
                means = [value / 255.0 for value in stat.mean]
                extrema = small.getextrema()
                luminance = 0.2126 * means[0] + 0.7152 * means[1] + 0.0722 * means[2]
                contrast = sum((high - low) / 255.0 for low, high in extrema) / 3.0
                max_channel = max(means)
                saturation = (
                    (max_channel - min(means)) / max(max_channel, 0.001)
                    if max_channel
                    else 0.0
                )
                frames.append(
                    {
                        "timeSec": sample.get("timeSec"),
                        "role": sample.get("role"),
                        "brightness": round(luminance, 4),
                        "contrast": round(contrast, 4),
                        "saturation": round(saturation, 4),
                    }
                )
                small_frames.append(small.tobytes())
        except (OSError, ValueError):
            continue

    if not frames:
        return {
            "status": "unavailable",
            "method": "local_frame_pixel_analysis_v1",
            "reason": "No extracted frames could be decoded.",
        }

    deltas = []
    for prev, cur in zip(small_frames, small_frames[1:]):
        if not prev or not cur:
            continue
        diff = sum(abs(a - b) for a, b in zip(prev, cur))
        deltas.append(diff / (len(prev) * 255.0))
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    avg_brightness = sum(frame["brightness"] for frame in frames) / len(frames)
    avg_contrast = sum(frame["contrast"] for frame in frames) / len(frames)
    avg_saturation = sum(frame["saturation"] for frame in frames) / len(frames)
    width = int(probe.get("width") or 0)
    height = int(probe.get("height") or 0)
    vertical = bool(width and height and height / max(width, 1) >= 1.45)
    if mean_delta >= 0.18:
        energy = "high"
        movement = "noticeable motion or scene changes between sampled frames"
    elif mean_delta >= 0.07:
        energy = "medium"
        movement = "moderate handheld motion or pose change"
    else:
        energy = "low"
        movement = "locked-off or near-static composition"
    lighting = (
        "bright"
        if avg_brightness >= 0.62
        else "dim"
        if avg_brightness <= 0.34
        else "balanced"
    )
    color = "colorful" if avg_saturation >= 0.38 else "neutral-toned"
    framing = "vertical phone-native" if vertical else "non-vertical or cropped"
    shot_sequence = [
        f"{frame['role']} at {frame['timeSec']}s: {lighting} {color} frame, contrast {frame['contrast']:.2f}"
        for frame in frames[:3]
    ]
    return {
        "status": "analyzed",
        "method": "local_frame_pixel_analysis_v1",
        "frameCount": len(frames),
        "averageBrightness": round(avg_brightness, 4),
        "averageContrast": round(avg_contrast, 4),
        "averageSaturation": round(avg_saturation, 4),
        "meanFrameDelta": round(mean_delta, 4),
        "energy": energy,
        "movement": movement,
        "framing": framing,
        "lighting": lighting,
        "colorPalette": color,
        "subjectCount": "unknown_without_vlm",
        "wardrobe": "unknown_without_vlm",
        "setting": f"{lighting} {color} source-inspired setting",
        "subjectAction": f"{movement}; preserve source pose/action without copying identity",
        "shotSequence": shot_sequence,
        "frames": frames,
    }


def _format_from_local_frame_analysis(
    fallback: str, probe: dict[str, Any], frame_analysis: dict[str, Any]
) -> str:
    if frame_analysis.get("status") != "analyzed":
        return fallback
    width = int(probe.get("width") or 0)
    height = int(probe.get("height") or 0)
    vertical = bool(width and height and height / max(width, 1) >= 1.45)
    if not vertical:
        return fallback
    if frame_analysis.get("energy") == "high":
        return "walking_clip"
    if fallback == "visual_reference":
        return "short_vertical_visual_hook"
    return fallback


def _pattern_card_from_local(
    job: dict[str, Any],
    *,
    platform: str,
    probe: dict[str, Any],
    frame_samples: list[dict[str, Any]],
    format_type: str,
    energy: str,
    ocr_text: str,
    frame_analysis: dict[str, Any],
    scene_cuts: list[float],
) -> dict[str, Any]:
    reference_id = job["reference_id"]
    hook_type = "relationship" if _contains_relationship_terms(job, ocr_text) else "pov"
    local_analyzed = frame_analysis.get("status") == "analyzed"
    shot_sequence = frame_analysis.get("shotSequence") if local_analyzed else None
    camera_movement = (
        frame_analysis.get("movement") if local_analyzed else "subtle handheld"
    )
    return {
        "schema": PATTERN_CARD_SCHEMA,
        "id": stable_id("viral_pattern_card", reference_id, format_type, hook_type),
        "platform": _norm(platform),
        "source": {
            "referenceId": reference_id,
            "creator": job.get("account"),
            "path": job.get("path"),
            "fileName": job.get("file_name"),
            "frameSamples": frame_samples,
        },
        "formatType": format_type,
        "hookType": hook_type,
        "visualPattern": (
            f"{format_type.replace('_', ' ')} reference measured from {len(frame_samples)} sampled frames; "
            f"{frame_analysis.get('lighting', 'unknown')} lighting, "
            f"{frame_analysis.get('colorPalette', 'unknown')} palette."
            if local_analyzed
            else f"{format_type.replace('_', ' ')} reference with phone-native composition and short-form overlay language."
        ),
        "setting": frame_analysis.get("setting")
        if local_analyzed
        else "source-inspired but original setting",
        "shotSequence": shot_sequence or _shot_sequence_for(format_type, probe),
        "cameraStyle": {
            "framing": frame_analysis.get("framing", "vertical 9:16"),
            "movement": camera_movement,
            "angle": "phone-native",
        },
        "subjectAction": frame_analysis.get(
            "subjectAction", "creator-style pose or expression shift"
        ),
        "subject": {
            "count": frame_analysis.get("subjectCount", "unknown_without_vlm"),
            "wardrobe": frame_analysis.get("wardrobe", "unknown_without_vlm"),
        },
        "textOverlayStyle": {
            "placement": "safe top or lower third",
            "fontStyle": "white text with dark stroke",
            "detectedText": ocr_text,
        },
        "pacing": {
            "energy": energy,
            "cutRhythm": "scene-change cuts" if len(scene_cuts) > 1 else "single shot",
            "sceneCuts": scene_cuts,
        },
        "audioVibe": {"energy": energy, "moodTags": ["glam", "relationship", "ai_ofm"]},
        "ctaPattern": "curiosity-first soft CTA",
        "reuseRisk": "medium",
        "copyRiskNotes": [
            "Do not copy the creator identity, username, watermark, exact room, or exact overlay copy."
        ],
        "transformationInstructions": [
            "Keep the winning format, but change model identity, wardrobe, pose details, setting, caption, and native audio."
        ],
        "viralityMetrics": {},
        "qualityWarnings": [
            "Local pixel analysis does not identify exact wardrobe, identity, or subject count; use Gemini/VLM analysis for semantic details."
        ],
    }


def _scene_cut_guesses(duration: float | None) -> list[float]:
    if not duration or duration <= 3:
        return [0.0]
    if duration <= 8:
        return [0.0, round(duration / 2, 2)]
    return [0.0, round(duration / 3, 2), round(duration * 2 / 3, 2)]


def _energy_from_probe(probe: dict[str, Any]) -> str:
    duration = probe.get("durationSeconds")
    if isinstance(duration, (int, float)) and duration <= 5:
        return "high"
    if isinstance(duration, (int, float)) and duration >= 14:
        return "low"
    return "medium"


def _sidecar_text(path: Path) -> str:
    candidate = path if path.suffix == ".txt" else path.with_suffix(".txt")
    try:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()[:1000]
    except OSError:
        return ""
    return ""


def _contains_relationship_terms(job: dict[str, Any], ocr_text: str) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            job.get("file_name"),
            job.get("account"),
            job.get("path"),
            ocr_text,
        )
    ).lower()
    return any(
        word in text
        for word in (
            "boy",
            "girl",
            "him",
            "her",
            "love",
            "dating",
            "relationship",
            "men",
            "women",
        )
    )


def _shot_sequence_for(format_type: str, probe: dict[str, Any]) -> list[str]:
    if format_type == "slideshow":
        return ["cover image hook", "supporting image beat", "final CTA image"]
    if format_type == "mirror_selfie":
        return ["mirror selfie opening", "subtle pose or expression shift"]
    if format_type == "selfie_video":
        return ["close selfie hook", "micro expression shift", "hold for caption read"]
    if format_type == "spicy_lifestyle":
        return [
            "lifestyle establishing pose",
            "small camera or body movement",
            "caption punchline hold",
        ]
    return ["vertical short-form opening", "caption read beat"]


def _float(value: object) -> float | None:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None
