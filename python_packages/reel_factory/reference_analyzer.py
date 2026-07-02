#!/usr/bin/env python3
"""Lightweight reference reel analysis before prompt generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from generate_prompts import (
    DEFAULT_MODEL,
    build_xai_payload,
    call_grok,
    extract_first_visible_frame,
    extract_reference_frames,
    load_xai_api_key,
    response_text,
    strip_json_fence,
    video_duration,
)
from intelligence_store import ensure_intelligence_schema
from pipeline_contracts.llm_resilience import decode_json_object
from reel_factory.sqlite_utils import connect_sqlite

ANALYSIS_FIELDS = {
    "baseVisualFormula": {},
    "viralVisualStructure": {},
    "outfit": {},
    "garmentFit": {},
    "garmentPlacement": {},
    "pose": {},
    "framing": {},
    "cameraAngle": {},
    "lighting": {},
    "environment": {},
    "sexierVisualDirection": {},
    "visualEmphasisSignals": {},
    "enhancementSuggestions": [],
    "scene_type": "",
    "shot_type": "",
    "camera_motion": "",
    "subject_motion": "",
    "pose_type": "",
    "background_elements": [],
    "outfit_type": "",
    "motion_prompt_hint": "",
}
FORBIDDEN_PERCEPTION_FIELDS = {
    "higgsfieldGridPrompt",
    "klingMotionPrompt",
    "negative_prompt",
    "image_prompt",
    "video_prompt",
    "hook_type",
    "caption",
    "captionText",
    "textOverlay",
    "overlayText",
    "ui",
    "interface",
    "platform",
    "identity",
    "identityDescription",
    "faceShape",
    "eyeColor",
    "hairColor",
    "ethnicity",
    "tattoos",
    "exactAge",
    "age",
}
PERCEPTION_TEXT_REJECT_RE = re.compile(
    r"\bcaption\b|\boverlay\b|\btext\s+overlay\b|\bon-screen\s+text\b|\bhook\b|\bhook\s+text\b"
    r"|\bui\b|\binterface\b|\binstagram\b|\bsocial-media\b|\bcreator-reel\b"
    r"|\busername\b|\bcomment\b|\bbutton\b|\bwatermark\b",
    flags=re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecar_path(root: Path, reference: Path) -> Path:
    digest = sha256_file(reference)[:16]
    return (
        root
        / "project_data"
        / "reference_analysis"
        / f"{reference.stem}_{digest}.reference_analysis.json"
    )


def build_analysis_instruction() -> str:
    return """Analyze the attached reference reel frames as a visual formula and enhancement system.

Grok may decide what makes the reference reel work visually and what should be made sexier. Output structured JSON only.

Return only strict JSON with these fields:
{
  "baseVisualFormula": {},
  "viralVisualStructure": {},
  "outfit": {},
  "garmentFit": {},
  "garmentPlacement": {},
  "pose": {},
  "framing": {},
  "cameraAngle": {},
  "lighting": {},
  "environment": {},
  "sexierVisualDirection": {},
  "visualEmphasisSignals": {},
  "enhancementSuggestions": [],
  "scene_type": "",
  "shot_type": "",
  "camera_motion": "",
  "subject_motion": "",
  "pose_type": "",
  "background_elements": [],
  "outfit_type": "",
  "motion_prompt_hint": ""
}

Allowed enhanced direction:
- identify outfit, fit, garment placement, pose, framing, camera angle, lighting, and environment
- identify visual emphasis signals such as cleavage, breasts, ass, hips, waist, thighs, skin exposure, fabric cling, and silhouette
- suggest how to push the visual formula sexier through stronger curves, deeper cleavage, fuller breasts, rounder ass, wider hips, tighter waist, tighter fabric cling, confident pose, stronger framing, and better lighting
- ignore all non-subject screen artifacts, app chrome, labels, usernames, reactions, controls, and other screen artifacts

Forbidden output:
- final Higgsfield prompt text
- final Kling prompt text
- negative prompts
- source writing, screen artifacts, app chrome, labels, usernames, reactions, controls, or watermark descriptions
- identity description, face shape, eye color, hair color, ethnicity, tattoos, or exact age
- free-form prompt prose outside the JSON object

Keep it compact and operational. Gemini owns long motion timeline extraction; include only concise motion and camera hints here."""


def normalize_analysis(data: dict[str, Any]) -> dict[str, Any]:
    forbidden = sorted(set(data) & FORBIDDEN_PERCEPTION_FIELDS)
    if forbidden:
        raise ValueError(f"unsupported Grok perception fields: {forbidden}")

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, subvalue in value.items():
                if PERCEPTION_TEXT_REJECT_RE.search(str(key)):
                    continue
                cleaned_value = scrub(subvalue)
                if cleaned_value not in ("", [], {}):
                    cleaned[str(key)] = cleaned_value
            return cleaned
        if isinstance(value, list):
            cleaned_list = []
            for item in value:
                cleaned_item = scrub(item)
                if cleaned_item not in ("", [], {}):
                    cleaned_list.append(cleaned_item)
            return cleaned_list
        text = str(value or "").strip()
        if not text or PERCEPTION_TEXT_REJECT_RE.search(text):
            return ""
        return text

    out = dict(ANALYSIS_FIELDS)
    for key in out:
        if key in data:
            out[key] = scrub(data[key])
    if not isinstance(out["background_elements"], list):
        out["background_elements"] = [str(out["background_elements"])]
    out["background_elements"] = [
        str(x) for x in out["background_elements"] if str(x).strip()
    ]
    if not isinstance(out["enhancementSuggestions"], list):
        out["enhancementSuggestions"] = [str(out["enhancementSuggestions"])]
    out["enhancementSuggestions"] = [
        str(x) for x in out["enhancementSuggestions"] if str(x).strip()
    ]
    for key, value in list(out.items()):
        if key not in {
            "background_elements",
            "enhancementSuggestions",
            "visualEmphasisSignals",
        } and not isinstance(value, dict):
            out[key] = str(value or "").strip()
    return out


def heuristic_analysis(reference: Path) -> dict[str, Any]:
    name = reference.stem.lower()
    scene = "unknown_scene"
    if "bath" in name or "mirror" in name:
        scene = "bathroom_mirror"
    elif "beach" in name:
        scene = "beach"
    elif "living" in name or "harper" in name:
        scene = "living_room"
    return {
        "scene_type": scene,
        "shot_type": "reference_reel"
        if reference.suffix.lower() in {".mp4", ".mov", ".m4v"}
        else "reference_image",
        "camera_motion": "unknown",
        "subject_motion": "unknown",
        "pose_type": "unknown",
        "background_elements": [],
        "outfit_type": "unknown",
        "motion_prompt_hint": "reference-matched simple steady movement with full-frame composition",
    }


def media_dimensions(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".mp4", ".mov", ".m4v"}:
        import subprocess

        from generate_prompts import FFPROBE

        result = subprocess.run(
            [
                FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        try:
            stream = (json.loads(result.stdout).get("streams") or [{}])[0]
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
        except Exception:
            width = height = 0
    else:
        try:
            from PIL import Image

            with Image.open(path) as im:
                width, height = im.size
        except Exception:
            width = height = 0
    aspect_ratio = round(width / height, 4) if width and height else None
    return {
        "width": width or None,
        "height": height or None,
        "aspect_ratio": aspect_ratio,
    }


def analyze_reference(
    root: Path, reference: Path, *, model: str = DEFAULT_MODEL, dry_run: bool = False
) -> dict[str, Any]:
    root = Path(root).resolve()
    reference = Path(reference).expanduser().resolve()
    out_path = sidecar_path(root, reference)
    frame_dir = out_path.parent / "_frames" / out_path.stem
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    if reference.suffix.lower() in {".mp4", ".mov", ".m4v"}:
        first = extract_first_visible_frame(reference, frame_dir)
        if first:
            frames.append(first)
        frames.extend(extract_reference_frames(reference, frame_dir))
    else:
        frames.append(reference)
    if dry_run:
        analysis = heuristic_analysis(reference)
        raw_response: dict[str, Any] | None = None
    else:
        payload = build_xai_payload(
            model=model, frames=frames, instruction=build_analysis_instruction()
        )
        api_key = load_xai_api_key(root)
        if not api_key:
            raise RuntimeError(
                "XAI_API_KEY or project_data/secrets.toml xai_api_key is required to call Grok"
            )
        raw_response = call_grok(payload, api_key=api_key)
        text = strip_json_fence(response_text(raw_response))
        analysis = normalize_analysis(
            decode_json_object(text, fallback=heuristic_analysis(reference))
        )
    reference_hash = sha256_file(reference)
    payload = {
        "schema": "reel_factory.reference_analysis.v1",
        "analysisId": f"analysis_{reference_hash[:16]}",
        "referencePath": str(reference),
        "referenceHash": reference_hash,
        "model": model,
        "duration": video_duration(reference)
        if reference.suffix.lower() in {".mp4", ".mov", ".m4v"}
        else None,
        "dimensions": media_dimensions(reference),
        "frames": [str(p) for p in frames],
        "analysis": normalize_analysis(analysis),
        "rawResponse": raw_response,
        "createdAt": int(time.time()),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    db = root / "manifest.sqlite"
    conn = connect_sqlite(db)
    ensure_intelligence_schema(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO reference_analysis (
            analysis_id, reference_path, reference_hash, sidecar_path, model,
            frame_paths_json, analysis_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["analysisId"],
            str(reference),
            reference_hash,
            str(out_path),
            model,
            json.dumps(payload["frames"], ensure_ascii=False),
            json.dumps(payload["analysis"], ensure_ascii=False),
            payload["createdAt"],
        ),
    )
    conn.commit()
    return {"ok": True, "path": str(out_path), **payload}


def latest_analysis_for_reference(root: Path, reference: Path) -> dict[str, Any] | None:
    record = latest_analysis_record(root, reference)
    return record["analysis"] if record else None


def latest_analysis_record(root: Path, reference: Path) -> dict[str, Any] | None:
    reference = Path(reference).expanduser().resolve()
    try:
        ref_hash = sha256_file(reference)
    except FileNotFoundError:
        return None
    db = Path(root).resolve() / "manifest.sqlite"
    if not db.exists():
        return None
    conn = connect_sqlite(db)
    ensure_intelligence_schema(conn)
    row = conn.execute(
        "SELECT * FROM reference_analysis WHERE reference_hash=? ORDER BY created_at DESC LIMIT 1",
        (ref_hash,),
    ).fetchone()
    if not row:
        return None
    try:
        return {
            "analysis_id": row["analysis_id"],
            "reference_path": row["reference_path"],
            "reference_hash": row["reference_hash"],
            "sidecar_path": row["sidecar_path"],
            "model": row["model"],
            "frame_paths": json.loads(row["frame_paths_json"] or "[]"),
            "analysis": json.loads(row["analysis_json"]),
            "created_at": row["created_at"],
        }
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--reference", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = analyze_reference(
        Path(args.root), Path(args.reference), model=args.model, dry_run=args.dry_run
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
