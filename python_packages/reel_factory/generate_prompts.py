#!/usr/bin/env python3
"""Prepare reference context for deterministic Prompt Builder V1.

This module may still prepare sampled frames and request previews for operator
review, but V1 does not allow an LLM to write the final prompt contract.
"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from asset_prompt_contract import (
    AssetPromptSet,
    build_grok_simple_prompt,
    parse_asset_prompt_response,
)
from campaign_store import retry_helper_direction, taste_memory
from PIL import Image, ImageStat
from project_config import config_path

XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"
GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DEFAULT_MODEL = "grok-4.3"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
REFERENCE_FACTORY_SEXY_REALISTIC_MODE = "reference_factory_sexy_realistic"
GROK_DIRECT_COMPAT_MODE = "grok-direct"
JSON_STRUCTURED_RECREATION_MODE = "json-structured"
HIGGSFIELD_REFERENCE_PROMPT_MODE = "higgsfield-reference"
DEFAULT_PROMPT_IMAGE_ASPECT_RATIO = "4:3"
HIGGSFIELD_PROMPT_ENHANCEMENT_ENABLED = False
HIGGSFIELD_REFERENCE_IMAGE_PASSED = False

_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}


def _number_word(value: int) -> str:
    return _NUMBER_WORDS.get(value, str(value))


def normalize_grid_layout(value: str | None = None) -> dict[str, Any]:
    raw = str(value or "").strip().lower().replace(" ", "")
    if raw in {"", "2x3", "3x2", "six", "six-panel", "sixpanel"}:
        columns, rows = 3, 2
    elif raw in {"1", "single", "single-image", "singleimage", "1x1"}:
        return {
            "kind": "single",
            "value": "single",
            "columns": 1,
            "rows": 1,
            "panel_count": 1,
            "panel_count_word": "one",
            "layout_phrase": "one standalone image",
            "prompt_opening": "Create one high-quality standalone raw smartphone image",
            "variation_phrase": "one final image",
            "key_constraint": "one standalone image",
        }
    else:
        match = re.fullmatch(r"([1-6])x([1-6])", raw)
        if not match:
            raise ValueError(
                f"unsupported grid_layout {value!r}; use single, 3x2, 2x3, 4x2, 2x4, 3x3, etc."
            )
        columns, rows = int(match.group(1)), int(match.group(2))
    panel_count = columns * rows
    return {
        "kind": "grid",
        "value": f"{columns}x{rows}",
        "columns": columns,
        "rows": rows,
        "panel_count": panel_count,
        "panel_label": f"{_number_word(panel_count)}-panel",
        "panel_count_word": _number_word(panel_count),
        "columns_word": _number_word(columns),
        "rows_word": _number_word(rows),
        "layout_phrase": f"exactly {_number_word(columns)} columns and {_number_word(rows)} rows",
        "prompt_opening": (
            f"Create one high-quality {_number_word(panel_count)}-panel grid image, exactly "
            f"{_number_word(columns)} columns and {_number_word(rows)} rows"
        ),
        "variation_phrase": f"{_number_word(panel_count)} variations",
        "key_constraint": f"one native {panel_count}-panel grid",
    }


def media_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed in {"image/jpeg", "image/png"}:
        return guessed
    return "image/png" if path.suffix.lower() == ".png" else "image/jpeg"


def data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{encoded}"


def video_mime_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed and guessed.startswith("video/"):
        return guessed
    return "video/mp4"


def video_duration(path: Path) -> float | None:
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
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
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return None


def reference_positions(count: int = 4) -> list[float]:
    return [0.08, 0.33, 0.66, 0.92][:count]


def frame_is_visible(
    path: Path, *, min_mean: float = 12.0, min_stddev: float = 4.0
) -> bool:
    try:
        with Image.open(path) as im:
            stat = ImageStat.Stat(im.convert("L"))
            return stat.mean[0] >= min_mean and stat.stddev[0] >= min_stddev
    except Exception:
        return False


def extract_first_visible_frame(
    reference_reel: Path,
    out_dir: Path,
    *,
    max_scan_seconds: float = 3.0,
    step_seconds: float = 0.25,
) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = video_duration(reference_reel) or 0.0
    scan_limit = min(max_scan_seconds, duration) if duration else max_scan_seconds
    attempts = int(scan_limit / step_seconds) + 1
    for idx in range(max(1, attempts)):
        seek = idx * step_seconds
        out = out_dir / "reference_00_first_visible.jpg"
        cmd = [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            f"{seek:.3f}",
            "-i",
            str(reference_reel),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(1280,iw)':-2",
            "-q:v",
            "3",
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
        if out.exists() and out.stat().st_size and frame_is_visible(out):
            return out
    return out if out.exists() and out.stat().st_size else None


def extract_reference_frames(
    reference_reel: Path, out_dir: Path, *, count: int = 4
) -> list[Path]:
    duration = video_duration(reference_reel) or 0.0
    frames: list[Path] = []
    for idx, pos in enumerate(reference_positions(count), start=1):
        out = out_dir / f"reference_{idx:02d}.jpg"
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
            str(reference_reel),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(1280,iw)':-2",
            "-q:v",
            "3",
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
        if out.exists() and out.stat().st_size:
            frames.append(out)
    return frames


def build_user_instruction(
    reference_context: str = "", creative_direction: str = ""
) -> str:
    return build_grok_simple_prompt(
        reference_context
        or "The attached frames are sampled from the reference reel in chronological order.",
        creative_direction,
    )


_PROMPT_FRAGMENT_REJECT_RE = re.compile(
    r"\b(?:no|avoid|without)\b|\bdo\s+not\b|\bbad\s+hands\b|\bextra\s+limbs\b|\bwarped\s+face\b"
    r"|\bidentity\b"
    r"|\bhair\b|\bhairstyle\b|\bhair\s+color\b|\beye\s+color\b|\bethnicity\b|\btattoos?\b"
    r"|\bcaption\b|\btext\b|\boverlay\b|\btext\s+overlay\b|\bon-screen\s+text\b|\bhook\b|\bhook\s+text\b"
    r"|\bui\b|\binterface\b|\binstagram\b|\bsocial-media\b|\bcreator-reel\b"
    r"|\busername\b|\bcomment\b|\bbutton\b|\bwatermark\b",
    flags=re.IGNORECASE,
)

_MOTION_FRAGMENT_REJECT_RE = re.compile(
    r"\bidentity\b|\bethnicity\b|\btattoos?\b"
    r"|\bcaption\b|\btext\s+overlay\b|\bon-screen\s+text\b|\bhook\s+text\b"
    r"|\bui\b|\binterface\b|\binstagram\b|\busername\b|\bcomment\b|\bbutton\b|\bwatermark\b",
    flags=re.IGNORECASE,
)


def _safe_fragment(value: Any) -> str:
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed_value = ast.literal_eval(value.strip())
            if isinstance(parsed_value, list):
                value = parsed_value
        except Exception:
            pass

    def flatten(item: Any) -> list[str]:
        if isinstance(item, dict):
            out: list[str] = []
            for subvalue in item.values():
                out.extend(flatten(subvalue))
            return out
        if isinstance(item, list):
            out = []
            for subvalue in item:
                out.extend(flatten(subvalue))
            return out
        text = str(item or "").strip()
        return [text] if text else []

    if isinstance(value, dict):
        raw = ", ".join(flatten(value))
    elif isinstance(value, list):
        raw = ", ".join(flatten(value))
    else:
        raw = str(value or "")
    raw = raw.replace("_", " ").replace("\n", " ").strip(" .,")
    if not raw or raw.lower() in {
        "unknown",
        "unknown scene",
        "unknown motion",
        "reference reel",
        "reference image",
        "hook",
        "text hook",
        "text question",
    }:
        return ""
    if _PROMPT_FRAGMENT_REJECT_RE.search(raw):
        return ""
    return re.sub(r"\s+", " ", raw)


def _safe_motion_fragment(value: Any) -> str:
    if isinstance(value, dict):
        raw = " ".join(str(item or "") for item in value.values())
    elif isinstance(value, list):
        raw = " ".join(str(item or "") for item in value)
    else:
        raw = str(value or "")
    raw = raw.replace("_", " ").replace("\n", " ").strip(" .,")
    if not raw or raw.lower() in {"unknown", "unknown motion"}:
        return ""
    replacements = [
        (
            r"\bhair\s+blows?\s+in\s+(?:the\s+)?wind\b",
            "subtle wind movement around subject",
        ),
        (
            r"\bhair\s+(?:is\s+)?blowing\s+in\s+(?:the\s+)?wind\b",
            "subtle wind movement around subject",
        ),
        (
            r"\b(hands?|fingers|both hands)\s+move\s+through\s+(?:her\s+|his\s+|their\s+)?hair\b",
            r"\1 move near head",
        ),
        (
            r"\b(hands?|fingers|both hands)\s+moving\s+through\s+(?:her\s+|his\s+|their\s+)?hair\b",
            r"\1 moving near head",
        ),
        (
            r"\b(hands?|fingers|both hands)\s+run\s+through\s+(?:her\s+|his\s+|their\s+)?hair\b",
            r"\1 move near head",
        ),
        (
            r"\braises\s+both\s+hands\s+to\s+touch\s+(?:her\s+|his\s+|their\s+)?hair\b",
            "raises both hands near head",
        ),
        (
            r"\braise\s+both\s+hands\s+to\s+touch\s+(?:her\s+|his\s+|their\s+)?hair\b",
            "raise both hands near head",
        ),
        (
            r"\braises\s+hands\s+to\s+touch\s+(?:her\s+|his\s+|their\s+)?hair\b",
            "raises hands near head",
        ),
        (
            r"\braise\s+hands\s+to\s+touch\s+(?:her\s+|his\s+|their\s+)?hair\b",
            "raise hands near head",
        ),
        (r"\bsubject\s+is\s+completely\s+still\b", "subject holds a still pose"),
        (r"\bno\s+camera\s+movement\b", "locked camera framing"),
        (r"\bno\s+body\s+movement\b", "still body hold"),
        (r"\bno\s+movement\b", "locked framing"),
        (r"\bno\s+motion\b", "static hold"),
        (r"\bhair\s+movement\b", "subtle head-area movement"),
        (
            r"\b(hands?|fingers|both hands)\s+(?:raise|raises|move|moves|go|goes)\s+to\s+touch\s+(?:her\s+|his\s+|their\s+)?hair\b",
            r"\1 raise near head",
        ),
        (
            r"\b(hands?|fingers|both hands)\s+to\s+(?:her\s+|his\s+|their\s+)?hair\b",
            r"\1 near head",
        ),
        (
            r"\b(hands?|fingers|both hands)\s+(?:in|through|over|near)\s+(?:her\s+|his\s+|their\s+)?hair\b",
            r"\1 near head",
        ),
        (r"\btouch(?:es|ing)?\s+(?:her\s+|his\s+|their\s+)?hair\b", "raise near head"),
        (r"\bbrush(?:es|ing)?\s+(?:her\s+|his\s+|their\s+)?hair\b", "move near head"),
        (r"\bhand-in-hair\b", "hand near head"),
    ]
    for pattern, replacement in replacements:
        raw = re.sub(pattern, replacement, raw, flags=re.IGNORECASE)
    raw = re.sub(r"\bhair\b", "head area", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+", " ", raw).strip(" .,")
    if _MOTION_FRAGMENT_REJECT_RE.search(raw):
        return ""
    return raw


_SCENE_JSON_SKIP_KEYS = {
    "negative_prompt",
    "negative",
    "avoid",
    "constraints",
    "must_avoid",
    "must_not",
    "identity",
    "ethnicity",
    "hair",
    "hair_color",
    "hairstyle",
    "eye_color",
    "tattoo",
    "tattoos",
}


def _safe_json_key(key: Any) -> str:
    text = str(key or "").strip()
    lowered = text.lower().replace("-", "_").replace(" ", "_")
    if not text or lowered in _SCENE_JSON_SKIP_KEYS:
        return ""
    if _PROMPT_FRAGMENT_REJECT_RE.search(text):
        return ""
    return text


def _safe_scene_fragment(value: Any) -> str:
    raw = str(value or "").replace("_", " ").replace("\n", " ").strip(" .,")
    if not raw:
        return ""
    raw = re.sub(r"\bhand-in-hair\b", "hand-near-head", raw, flags=re.IGNORECASE)
    raw = re.sub(
        r"\bfingers\s+in\s+hair\b", "fingers near head", raw, flags=re.IGNORECASE
    )
    raw = re.sub(
        r"\bhand\s+resting\s+in\s+hair\b",
        "hand raised near head",
        raw,
        flags=re.IGNORECASE,
    )
    raw = re.sub(r"\bhand\s+in\s+hair\b", "hand near head", raw, flags=re.IGNORECASE)
    raw = re.sub(
        r"\bresting\s+in\s+hair\b", "raised near head", raw, flags=re.IGNORECASE
    )
    raw = re.sub(r"\bin\s+hair\b", "near head", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\bhair\b", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+", " ", raw).strip(" .,")
    if _PROMPT_FRAGMENT_REJECT_RE.search(raw):
        return ""
    return raw


def _flatten_scene_value(value: Any) -> list[str]:
    if isinstance(value, dict):
        parts: list[str] = []
        for key, subvalue in value.items():
            if not _safe_json_key(key):
                continue
            parts.extend(_flatten_scene_value(subvalue))
        return parts
    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(_flatten_scene_value(item))
        return parts
    safe = _safe_scene_fragment(value)
    return [safe] if safe else []


def _scene_section_text(label: str, value: Any) -> str:
    safe_label = _safe_json_key(label)
    if not safe_label:
        return ""
    parts = _flatten_scene_value(value)
    if not parts:
        return ""
    return f"{safe_label.replace('_', ' ').title()}: {', '.join(parts)}."


def scene_json_to_higgsfield_prompt(data: dict[str, Any]) -> str:
    sections = [
        ("subject", data.get("subject")),
        ("body", data.get("body")),
        ("clothing", data.get("clothing")),
        ("environment", data.get("environment")),
        (
            "lighting_and_camera",
            data.get("lighting_and_camera") or data.get("camera_technical"),
        ),
        ("framing", data.get("framing")),
        ("scene_details", data.get("scene_details")),
    ]
    body = [_scene_section_text(label, value) for label, value in sections]
    variations = data.get("outfit_variations") or data.get("outfitVariations")
    variations_text = _scene_section_text("Outfit variations (1-6)", variations)
    if variations_text:
        body.append(variations_text)
    consistency = _safe_fragment(data.get("consistency")) or (
        "same room, same camera angle, same framing, same pose geometry, same body proportions across all six panels"
    )
    body.append(f"Consistency: {consistency}.")
    prompt = " ".join(part for part in body if part)
    return (
        f"Create one high-quality native 2x3 grid featuring six variations. {prompt}"
    ).strip()


def _join_parts(parts: list[str], *, limit: int | None = None) -> str:
    cleaned = [part.strip(" .,") for part in parts if part and part.strip(" .,")]
    if limit is not None:
        cleaned = cleaned[:limit]
    return ", ".join(cleaned)


def _visual_emphasis_phrase(value: Any) -> str:
    if isinstance(value, dict):
        parts: list[str] = []
        for key, raw_value in value.items():
            safe_key = _safe_fragment(str(key))
            safe_value = _safe_fragment(raw_value)
            if not safe_key or not safe_value:
                continue
            if safe_key == "ass" and safe_value.lower() == "partial":
                parts.append("subtle ass curve")
                continue
            if safe_key in safe_value.lower().split():
                parts.append(safe_value)
            else:
                parts.append(f"{safe_value} {safe_key}")
        return _join_parts(parts, limit=8)
    if isinstance(value, list):
        return _join_parts([_safe_fragment(item) for item in value], limit=8)
    return _safe_fragment(value)


def _garment_fit_phrase(value: Any) -> str:
    if not isinstance(value, dict):
        return _safe_fragment(value)
    fit = _safe_fragment(value.get("fit"))
    cling = _safe_fragment(value.get("cling"))
    stretch = _safe_fragment(value.get("stretch"))
    compression = _safe_fragment(value.get("compression"))
    parts: list[str] = []
    if fit:
        parts.append(f"{fit} fit" if "fit" not in fit.lower().split() else fit)
    if cling:
        parts.append(
            f"{cling} fabric cling" if "cling" not in cling.lower().split() else cling
        )
    if stretch:
        parts.append(
            f"{stretch} stretch"
            if "stretch" not in stretch.lower().split()
            else stretch
        )
    if compression:
        parts.append(
            f"{compression} compression"
            if "compression" not in compression.lower().split()
            else compression
        )
    for key, raw_value in value.items():
        if key in {"fit", "cling", "stretch", "compression"}:
            continue
        extra = _safe_fragment(raw_value)
        if extra:
            parts.append(extra)
    return " with ".join(parts[:4])


_TOPIC_WORDS = {
    "cleavage": {"cleavage"},
    "breasts": {"breast", "breasts", "bust"},
    "ass": {"ass", "butt"},
    "hips": {"hip", "hips"},
    "waist": {"waist"},
    "thighs": {"thigh", "thighs"},
    "fabric": {"fabric", "cling", "stretch", "tension"},
    "silhouette": {"silhouette", "hourglass", "curve", "curves"},
}


def _topics_in_text(text: str) -> set[str]:
    lowered = text.lower()
    topics: set[str] = set()
    for topic, words in _TOPIC_WORDS.items():
        if any(re.search(r"\b" + re.escape(word) + r"\b", lowered) for word in words):
            topics.add(topic)
    return topics


def _compressed_enhancement_phrase(
    value: Any, *, covered_topics: set[str], extra_direction: str = ""
) -> str:
    fragments: list[str] = []
    if isinstance(value, list):
        fragments.extend(_safe_fragment(item) for item in value)
    elif isinstance(value, dict):
        fragments.extend(_safe_fragment(item) for item in value.values())
    else:
        fragments.append(_safe_fragment(value))
    if extra_direction:
        fragments.append(extra_direction)

    selected: list[str] = []
    used_topics = set(covered_topics)
    for fragment in fragments:
        fragment = fragment.strip(" .,")
        if not fragment:
            continue
        topics = _topics_in_text(fragment)
        if topics and topics <= used_topics:
            continue
        if topics:
            used_topics.update(topics)
        selected.append(fragment)
        if len(selected) >= 3:
            break
    return _join_parts(selected)


def _sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .,")
    return f"{text}." if text else ""


def _example_outfit_variations(panel_count: int) -> list[str]:
    base = [
        "Bright turquoise blue strapless bodycon dress",
        "Deep black strapless bodycon dress",
        "Crisp white strapless bodycon dress",
        "Soft lavender strapless bodycon dress",
        "Mint green strapless bodycon dress",
        "Deep burgundy strapless bodycon dress",
        "Hot pink strapless bodycon dress",
        "Charcoal satin strapless bodycon dress",
        "Cream ribbed strapless bodycon dress",
        "Emerald green velvet strapless bodycon dress",
        "Navy metallic strapless bodycon dress",
        "Blush pink sheer-mesh strapless bodycon dress",
    ]
    return base[: max(1, min(panel_count, len(base)))]


def _numbered_variation_text(variations: list[str]) -> str:
    return " ".join(f"{idx}. {value}." for idx, value in enumerate(variations, start=1))


def build_direct_higgsfield_prompt_instruction(
    creative_direction: str = "", *, grid_layout: str = "3x2"
) -> str:
    direction = creative_direction.strip() or (
        "make the visual formula sexier with stronger curves, larger cleavage, "
        "rounder ass emphasis, tighter garment cling, confident pose geometry, "
        "and amateur iPhone capture realism"
    )
    layout = normalize_grid_layout(grid_layout)
    panel_count = int(layout["panel_count"])
    variations = _example_outfit_variations(panel_count)
    if layout["kind"] == "single":
        grid_requirement = "For the final image: create one standalone image in the same old structured prompt style."
        example_prompt = (
            "Create one high-quality Soul ID image featuring the same adult woman at least 20 years old with a voluptuous "
            "extreme hourglass figure from the reference image. She is seated looking over her shoulder in a casual indoor "
            "setting. Exact reference pose: seated position, turned to look over her shoulder, strong arched back pushing "
            "out her backside, seductive over-the-shoulder gaze. Strong sexual body emphasis: massive round plump juicy ass "
            "taking center focus, deep side cleavage, tiny cinched waist, wide hips, thick thighs, dramatic S-curve posture, "
            "skin-tight fabric clinging tightly to her curves. Natural daylight, realistic fabric cling, consistent body "
            "proportions and pose, vertical smartphone aesthetic."
        )
    else:
        grid_requirement = (
            f"For the {layout['panel_count_word']}-panel grid: vary only outfit color and material, keep the same garment "
            f"style/cut, and request one native {layout['panel_label']} image, {layout['layout_phrase']}."
        )
        example_prompt = (
            f"Create one high-quality native {layout['panel_label']} grid featuring {layout['variation_phrase']} of the "
            "exact same stunning woman with a voluptuous extreme hourglass figure from the reference image. She is seated "
            "looking over her shoulder in a casual indoor setting. Exact reference pose in all panels: seated position, "
            "turned to look over her shoulder, strong arched back pushing out her backside, seductive over-the-shoulder gaze. "
            "Strong sexual body emphasis in every panel: massive round plump juicy ass taking center focus, deep side cleavage, "
            "tiny cinched waist, wide hips, thick thighs, dramatic S-curve posture, skin-tight fabric clinging tightly to her curves. "
            f"Outfit variations (same garment style/cut as reference): {_numbered_variation_text(variations)} Natural daylight, "
            "realistic fabric cling, consistent body proportions and pose across all panels, vertical smartphone aesthetic."
        )
    return (
        "Reference image/reel attached.\n\n"
        "Create a high-quality image prompt for Higgsfield Soul V2.\n\n"
        "Requirements:\n"
        "- Stay extremely faithful to the exact pose, body angle, hand placement, setting, lighting, framing, and overall vibe from the reference.\n"
        "- Strongly amplify the sexiness: bigger pushed-up breasts with deep plunging cleavage, massive round plump juicy ass, tiny cinched waist, wide hips, thick thighs, dramatic S-curve posture, and skin-tight fabric clinging to every curve.\n"
        "- Do NOT mention hair, hairstyle, hair color, or tattoos at all.\n"
        f"- {grid_requirement}\n"
        "- Make the language detailed and descriptive like the old structured prompts.\n"
        "- If the reference pose has a hand touching hair, describe it as hand near head or hand behind head.\n"
        "- Do not mention captions, usernames, UI, watermarks, negative prompts, or that the reference image will be passed to Higgsfield.\n\n"
        f"Extra user instructions: {direction}\n\n"
        "Example prompt style to imitate:\n"
        f"{example_prompt}\n\n"
        "Return only this JSON:\n"
        "{\n"
        '  "image_prompt": "...",\n'
        '  "notes": "..."\n'
        "}"
    )


def build_higgsfield_reference_prompt_instruction(creative_direction: str = "") -> str:
    direction = creative_direction.strip()
    extra = f"\nExtra direction from operator: {direction}\n" if direction else ""
    return (
        "Reference image attached.\n\n"
        "Make a prompt similar to this reference image for me to use in Higgsfield with Soul ID on my AI model.\n"
        "Make sure to get the pose down correctly, including body angle, camera angle, hand placement, crop, clothing, lighting, and setting.\n"
        "Make sure the prompt is sexy, body-forward, realistic, and amateur smartphone-style, while staying faithful to the reference pose, outfit, and setting.\n"
        "Do not mention hair, hairstyle, hair color, tattoos, identity traits, usernames, captions, UI, watermarks, or negative prompts.\n"
        "Do not make a grid, panel sheet, collage, or variation set. Write for exactly one standalone image.\n"
        "Do not say the reference image will be passed into Higgsfield. The final prompt must stand on its own.\n"
        f"{extra}\n"
        "Return only this JSON:\n"
        "{\n"
        '  "image_prompt": "...",\n'
        '  "notes": "..."\n'
        "}"
    )


def build_json_structured_recreation_instruction(
    creative_direction: str = "",
    *,
    grid_layout: str = "3x2",
    image_aspect_ratio: str = DEFAULT_PROMPT_IMAGE_ASPECT_RATIO,
) -> str:
    """Ask Grok for a schema-first reference recreation plan.

    The final Higgsfield prompt is compiled locally from these fields so that
    reference, wardrobe, pose, camera, and QC constraints stay auditable.
    """
    direction = creative_direction.strip() or (
        "make the result adult, confident, body-forward, amateur smartphone realistic, "
        "with fitted wardrobe and tasteful glamour while preserving the reference pose and scene"
    )
    layout = normalize_grid_layout(grid_layout)
    if layout["kind"] == "single":
        output_goal = "one standalone image"
        variation_goal = "one faithful variation"
    else:
        output_goal = (
            f"one native {layout['panel_count']}-panel grid, {layout['layout_phrase']}"
        )
        variation_goal = (
            f"{layout['panel_count']} practical outfit/color/fabric variations with the same garment family, "
            "same scene, same camera angle, and same pose geometry"
        )
    return (
        "Reference image attached.\n\n"
        "Analyze the reference image and return a strict JSON object that can be used to recreate the image formula. "
        "Do not return prose outside JSON.\n\n"
        "Hard rules:\n"
        "- The subject must be an adult woman, age 20+.\n"
        "- Soul ID owns the identity. Do not describe identity-locked details like hair color, hairstyle, eye color, ethnicity, tattoos, exact face, freckles, or skin texture.\n"
        "- Do not include captions, usernames, watermarks, UI, buttons, timestamps, app interface, text overlays, logos, or negative prompts.\n"
        "- Preserve the reference scene, camera angle, framing, pose, lighting, outfit family, and amateur smartphone feel.\n"
        "- Add tasteful glamour through fitted clothing, confident pose mechanics, flattering silhouette, fabric cling, waist/hip shape, and camera-ready styling. Do not make it explicit.\n"
        f"- Output target: {output_goal}, image aspect ratio {image_aspect_ratio}.\n"
        f"- Variation target: {variation_goal}.\n\n"
        "Return only this JSON shape:\n"
        "{\n"
        '  "schema": "reel_factory.reference_recreation_prompt.v1",\n'
        '  "adultSubject": true,\n'
        '  "referenceSummary": "",\n'
        '  "scene": {\n'
        '    "environment": "",\n'
        '    "background": "",\n'
        '    "props": [],\n'
        '    "captureStyle": "amateur smartphone|mirror selfie|outdoor lifestyle|room selfie|outfit check"\n'
        "  },\n"
        '  "subject": {\n'
        '    "bodyPose": "",\n'
        '    "cameraFacing": "",\n'
        '    "gaze": "",\n'
        '    "crop": "",\n'
        '    "silhouetteEmphasis": []\n'
        "  },\n"
        '  "wardrobe": {\n'
        '    "garmentFamily": "",\n'
        '    "upperGarment": "",\n'
        '    "lowerGarment": "",\n'
        '    "fabric": [],\n'
        '    "fit": "",\n'
        '    "colorPalette": [],\n'
        '    "variationPlan": []\n'
        "  },\n"
        '  "lighting": {\n'
        '    "quality": "",\n'
        '    "direction": "",\n'
        '    "colorTemperature": ""\n'
        "  },\n"
        '  "camera": {\n'
        '    "shotType": "",\n'
        '    "perspective": "",\n'
        '    "lensFeel": ""\n'
        "  },\n"
        '  "glamourDirection": {\n'
        '    "style": "tasteful_glamour",\n'
        '    "bodyForwardCues": [],\n'
        '    "garmentCues": [],\n'
        '    "poseCues": []\n'
        "  },\n"
        '  "qualityConstraints": {\n'
        '    "noText": true,\n'
        '    "noUi": true,\n'
        '    "noWatermarks": true,\n'
        '    "keepHeadVisible": true,\n'
        '    "avoidBadHandsDominatingFrame": true\n'
        "  },\n"
        '  "notes": ""\n'
        "}\n\n"
        f"Extra operator direction:\n{direction}\n"
    )


_STRUCTURED_ALLOWED_TOP_KEYS = {
    "schema",
    "adultSubject",
    "referenceSummary",
    "scene",
    "subject",
    "wardrobe",
    "lighting",
    "camera",
    "glamourDirection",
    "qualityConstraints",
    "notes",
}


def _clean_structured_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, subvalue in value.items():
            safe_key = _safe_json_key(key)
            if not safe_key:
                continue
            cleaned[safe_key] = _clean_structured_value(subvalue)
        return cleaned
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            cleaned_item = _clean_structured_value(item)
            if cleaned_item not in ("", [], {}):
                out.append(cleaned_item)
        return out[:12]
    return _safe_scene_fragment(value)


def normalize_structured_recreation_spec(raw_text: str) -> dict[str, Any]:
    try:
        data = json.loads(strip_json_fence(raw_text))
    except json.JSONDecodeError as exc:
        raise ValueError("json-structured Grok response must be strict JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("json-structured Grok response must be a JSON object")
    normalized: dict[str, Any] = {
        "schema": "reel_factory.reference_recreation_prompt.v1",
        "adultSubject": bool(data.get("adultSubject", True)),
    }
    for key, value in data.items():
        if key == "schema":
            continue
        if key not in _STRUCTURED_ALLOWED_TOP_KEYS:
            continue
        normalized[key] = _clean_structured_value(value)
    normalized["schema"] = "reel_factory.reference_recreation_prompt.v1"
    normalized["adultSubject"] = bool(normalized.get("adultSubject", True))
    if not normalized["adultSubject"]:
        raise ValueError("json-structured prompt must confirm adultSubject=true")
    return normalized


def _structured_parts(spec: dict[str, Any], dotted_path: str) -> Any:
    current: Any = spec
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def structured_recreation_spec_to_prompt(
    spec: dict[str, Any], *, grid_layout: str = "3x2"
) -> str:
    layout = normalize_grid_layout(grid_layout)
    scene_bits = _join_parts(
        [
            _safe_fragment(_structured_parts(spec, "scene.captureStyle")),
            _safe_fragment(_structured_parts(spec, "scene.environment")),
            _safe_fragment(_structured_parts(spec, "scene.background")),
            _safe_fragment(_structured_parts(spec, "scene.props")),
        ],
        limit=8,
    )
    pose_bits = _join_parts(
        [
            _safe_fragment(_structured_parts(spec, "subject.bodyPose")),
            _safe_fragment(_structured_parts(spec, "subject.cameraFacing")),
            _safe_fragment(_structured_parts(spec, "subject.gaze")),
            _safe_fragment(_structured_parts(spec, "subject.crop")),
        ],
        limit=8,
    )
    wardrobe_bits = _join_parts(
        [
            _safe_fragment(_structured_parts(spec, "wardrobe.garmentFamily")),
            _safe_fragment(_structured_parts(spec, "wardrobe.upperGarment")),
            _safe_fragment(_structured_parts(spec, "wardrobe.lowerGarment")),
            _safe_fragment(_structured_parts(spec, "wardrobe.fabric")),
            _safe_fragment(_structured_parts(spec, "wardrobe.fit")),
            _safe_fragment(_structured_parts(spec, "wardrobe.colorPalette")),
        ],
        limit=12,
    )
    lighting_bits = _join_parts(
        [
            _safe_fragment(_structured_parts(spec, "lighting.quality")),
            _safe_fragment(_structured_parts(spec, "lighting.direction")),
            _safe_fragment(_structured_parts(spec, "lighting.colorTemperature")),
        ],
        limit=6,
    )
    camera_bits = _join_parts(
        [
            _safe_fragment(_structured_parts(spec, "camera.shotType")),
            _safe_fragment(_structured_parts(spec, "camera.perspective")),
            _safe_fragment(_structured_parts(spec, "camera.lensFeel")),
        ],
        limit=6,
    )
    glamour_bits = _join_parts(
        [
            _safe_fragment(_structured_parts(spec, "glamourDirection.bodyForwardCues")),
            _safe_fragment(_structured_parts(spec, "glamourDirection.garmentCues")),
            _safe_fragment(_structured_parts(spec, "glamourDirection.poseCues")),
            _safe_fragment(_structured_parts(spec, "subject.silhouetteEmphasis")),
        ],
        limit=10,
    )
    variation_plan = _structured_parts(spec, "wardrobe.variationPlan")
    variation_bits = _join_parts([_safe_fragment(variation_plan)], limit=12)
    if not variation_bits and layout["kind"] != "single":
        variation_bits = _numbered_variation_text(
            _example_outfit_variations(int(layout["panel_count"]))
        )

    opening = layout["prompt_opening"]
    scene_props_text = str(_structured_parts(spec, "scene.props") or "").lower()
    has_multi_subject_scene = (
        "two people" in scene_props_text or "second person" in scene_props_text
    )
    subject_opening = (
        f"{opening} featuring the main adult woman age 20+ in a two-person casual snapshot."
        if layout["kind"] == "single" and has_multi_subject_scene
        else f"{opening} featuring one adult woman age 20+."
        if layout["kind"] == "single"
        else f"{opening} featuring the same adult woman age 20+ from the Soul ID."
    )
    sentences = [
        subject_opening,
        _sentence(f"Camera: {camera_bits}") if camera_bits else "",
        _sentence(f"Body mechanics: {pose_bits}") if pose_bits else "",
        _sentence(f"Wardrobe: {wardrobe_bits}") if wardrobe_bits else "",
        _sentence(f"Lighting and environment: {lighting_bits}; {scene_bits}")
        if lighting_bits and scene_bits
        else "",
        _sentence(f"Lighting: {lighting_bits}")
        if lighting_bits and not scene_bits
        else "",
        _sentence(f"Environment: {scene_bits}")
        if scene_bits and not lighting_bits
        else "",
        _sentence(f"Tasteful glamour cues: {glamour_bits}") if glamour_bits else "",
        "Frame the subject with the complete head visible inside the image and natural full upper-body composition.",
    ]
    if layout["kind"] != "single":
        sentences.append(
            _sentence(
                f"Panel variations: {variation_bits}; keep the same scene, same camera angle, same framing, "
                "same pose geometry, consistent body proportions, and clean image-only composition in every panel"
            )
        )
    else:
        sentences.append(
            "Use head-to-thigh portrait framing with the full head and face fully inside the frame, clear top margin above the head, shoulders and torso visible, balanced vertical smartphone composition."
        )
        sentences.append(
            "Compose exactly one uninterrupted camera frame from one scene, as a single natural photo with one continuous foreground-and-background composition."
        )
        sentences.append(
            "Make it a borderless edge-to-edge raw camera photo filling the entire canvas with plain camera-output styling, one full-frame image, one continuous scene, one natural smartphone capture, repeated-sample-free composition, label-free composition."
        )
    return " ".join(sentence for sentence in sentences if sentence).strip()


def _direct_prompt_from_response_text(raw_text: str) -> str:
    try:
        data = json.loads(strip_json_fence(raw_text))
    except json.JSONDecodeError as exc:
        raise ValueError("direct Grok prompt response must be strict JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("direct Grok prompt response must be a JSON object")
    prompt = str(
        data.get("higgsfieldGridPrompt")
        or data.get("image_prompt")
        or data.get("soul_id_2x3_prompt")
        or data.get("prompt")
        or ""
    ).strip()
    if not prompt:
        prompt = scene_json_to_higgsfield_prompt(data)
    if not prompt:
        raise ValueError("direct Grok prompt response missing Higgsfield prompt")
    return prompt


_DIRECT_FORBIDDEN_RESIDUAL_RE = re.compile(
    r"(?i)\b(?:hair|hairstyle|hair\s+color|tattoos?|eye\s+color|ethnicity|"
    r"blue eyes?|green eyes?|brown eyes?|hazel eyes?|gray eyes?|grey eyes?|"
    r"freckles?|freckled|perfect face|skin texture|skin sheen|natural sheen|"
    r"high detail|sharp focus)\b"
)
_DIRECT_PROMPT_REPLACEMENTS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "hair_contact_pose_to_hand_near_head",
        re.compile(
            r"(?i)\b(?:with\s+)?(?:(?:one|other|left|right)\s+)?(?:hand|hands|fingers)\s+"
            r"(?:(?:running|run|brushing|brush|touching|touch|holding|hold|gripping|grip|"
            r"combing|comb|threading|thread|pulling|pull|playing|resting|rest)\s+)?"
            r"(?:(?:in|through|over|near)\s+)?(?:her\s+|his\s+|their\s+)?(?:\w+\s+){0,4}hair\b"
        ),
        "hand near head",
    ),
)
_DIRECT_PROMPT_REMOVALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "hair_descriptor",
        re.compile(
            r"(?i)\b(?:long|short|medium-length|voluminous|wavy|curly|straight|braided|"
            r"blonde|brunette|brown|black|red|auburn|dark|light|silky|flowing|styled|"
            r"middle-parted|center-parted|loose|natural|bright|copper|ginger)(?:[\s-]+\w+){0,4}\s+hair\b"
        ),
    ),
    ("hair_word", re.compile(r"(?i)\b(?:hair|hairstyle|hair\s+color)\b")),
    (
        "tattoo",
        re.compile(
            r"(?i)\b(?:visible\s+|small\s+|wrist\s+|arm\s+|shoulder\s+|back\s+)?tattoos?\b"
        ),
    ),
    (
        "eye_color",
        re.compile(
            r"(?i)\b(?:(?:bright|piercing|striking|soft|almond-shaped|round)\s+)*(?:blue|green|brown|hazel|gray|grey)\s+eyes?\b|\beye\s+color\b"
        ),
    ),
    (
        "freckles",
        re.compile(
            r"(?i)\b(?:scattered\s+|light\s+|visible\s+)?freckles?(?:\s+across\s+(?:nose|face|cheeks))?\b|\bfreckled\b"
        ),
    ),
    (
        "skin_polish",
        re.compile(
            r"(?i)\b(?:photorealistic\s+)?skin\s+texture(?:\s+with\s+natural\s+sheen)?\b|\bskin\s+sheen\b|\bnatural\s+sheen\b"
        ),
    ),
    ("perfect_face", re.compile(r"(?i)\bperfect\s+face\b")),
    ("quality_polish", re.compile(r"(?i)\bhigh\s+detail\b|\bsharp\s+focus\b")),
    ("ethnicity_word", re.compile(r"(?i)\bethnicity\b")),
    (
        "ethnicity_descriptor",
        re.compile(
            r"(?i)\b(?:latina|latino|hispanic|caucasian|asian|african|middle eastern|indian|white|black)\s+(?=woman|person|model|girl)\b"
        ),
    ),
    ("face_consistency_prefix", re.compile(r"(?i)\bface\s+and\s+")),
    ("face_consistency_list_item", re.compile(r"(?i)(,\s*)face\s*,?\s*(and\s+)?")),
    (
        "face_consistency_tail",
        re.compile(r"(?i)\s+and\s+face(?=\s+across|\s*,|\s+and|\.)"),
    ),
)


def _repair_cleanup_punctuation(text: str) -> str:
    cleaned = re.sub(r"\s{2,}", " ", text)
    cleaned = re.sub(r"\s+([,;.!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,;])\s*([,;])+", r"\1", cleaned)
    cleaned = re.sub(r"\s*,\s*([.!?])", r"\1", cleaned)
    cleaned = re.sub(r"(?i)\b(with|has|have)\s*,\s*", r"\1 ", cleaned)
    cleaned = re.sub(r"(?i)\b(with|has|have)\s+and\s+", r"\1 ", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" ,;")


def clean_direct_higgsfield_prompt(prompt: str) -> dict[str, Any]:
    """Removal-only cleanup for Grok's final prompt, with an auditable diff."""
    raw = prompt.strip()
    cleaned = raw
    diff: list[dict[str, str]] = []

    def replace_matches(
        label: str, pattern: re.Pattern[str], replacement: str, value: str
    ) -> str:
        def repl(match: re.Match[str]) -> str:
            original = match.group(0)
            diff.append(
                {
                    "action": "replace" if replacement.strip() else "remove",
                    "label": label,
                    "text": original.strip(" ,;"),
                    "replacement": replacement,
                }
            )
            return replacement

        return pattern.sub(repl, value)

    for label, pattern, replacement in _DIRECT_PROMPT_REPLACEMENTS:
        cleaned = replace_matches(label, pattern, replacement, cleaned)
    for label, pattern in _DIRECT_PROMPT_REMOVALS:
        cleaned = replace_matches(label, pattern, " ", cleaned)
    repaired = _repair_cleanup_punctuation(cleaned)
    if repaired != cleaned:
        diff.append(
            {
                "action": "repair_punctuation",
                "label": "spacing_punctuation",
                "text": cleaned.strip(),
                "replacement": repaired,
            }
        )
    residual = sorted(
        set(m.group(0) for m in _DIRECT_FORBIDDEN_RESIDUAL_RE.finditer(repaired))
    )
    return {
        "raw": raw,
        "cleaned": repaired,
        "diff": diff,
        "removed": [item["text"] for item in diff if item["action"] == "remove"],
        "residualForbiddenTerms": residual,
        "valid": not residual,
        "changed": raw != repaired,
        "policy": f"{REFERENCE_FACTORY_SEXY_REALISTIC_MODE}_removal_only",
    }


def clean_direct_higgsfield_prompt_text(prompt: str) -> str:
    """Return cleaned prompt text while preserving Grok wording except forbidden removals."""
    return clean_direct_higgsfield_prompt(prompt)["cleaned"]


def parse_direct_higgsfield_prompt_response(
    raw_text: str, *, shared_motion_prompt: str, notes: str = ""
) -> AssetPromptSet:
    prompt = clean_direct_higgsfield_prompt(
        _direct_prompt_from_response_text(raw_text)
    )["cleaned"]
    return parse_asset_prompt_response(
        json.dumps(
            {
                "higgsfieldGridPrompt": prompt,
                "klingMotionPrompt": shared_motion_prompt,
                "notes": notes
                or "Live Grok direct Higgsfield prompt; image compiler bypassed.",
            },
            ensure_ascii=False,
        )
    )


_DRIFT_CONCEPT_PHRASES = (
    "2x3 grid",
    "six variations",
    "Outfit variations (1-6)",
    "mirror selfie",
    "close-up selfie",
    "phone selfie",
    "bathroom counter",
    "kitchen",
    "window",
    "white cabinets",
    "wooden ceiling beams",
    "arched back",
    "over-the-shoulder gaze",
    "deep neckline",
    "deep cleavage",
    "tight fabric cling",
    "skin-tight fabric",
    "tiny waist",
    "wide hips",
    "thick thighs",
    "round ass",
    "hourglass silhouette",
    "same camera angle",
    "same framing",
    "same room",
    "same lighting",
)


def _concepts_in_prompt(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for phrase in _DRIFT_CONCEPT_PHRASES:
        if phrase.lower() in lowered:
            found.append(phrase)
    return found


def _forbidden_drift_concept(concept: str) -> bool:
    return bool(_PROMPT_FRAGMENT_REJECT_RE.search(concept))


def prompt_drift_report(raw_prompt: str, final_prompt: str) -> dict[str, Any]:
    raw_concepts = _concepts_in_prompt(raw_prompt)
    final_concepts = _concepts_in_prompt(final_prompt)
    raw_set = set(raw_concepts)
    final_set = set(final_concepts)
    removed = [concept for concept in raw_concepts if concept not in final_set]
    added = [concept for concept in final_concepts if concept not in raw_set]
    visual_loss = any(not _forbidden_drift_concept(concept) for concept in removed)
    return {
        "preservedConcepts": [
            concept for concept in raw_concepts if concept in final_set
        ],
        "removedConcepts": removed,
        "addedConcepts": added,
        "visualMechanicsLoss": visual_loss,
    }


def compile_prompt_contract(
    *,
    reference_analysis: dict[str, Any] | None = None,
    reference_context: str = "",
    creative_direction: str = "",
    operator_notes: str = "",
) -> AssetPromptSet:
    """Compile a deterministic v1 prompt contract from existing extracted fields."""
    analysis = reference_analysis or {}
    outfit = _safe_fragment(analysis.get("outfit") or analysis.get("outfit_type"))
    garment_fit = _garment_fit_phrase(analysis.get("garmentFit"))
    garment_placement = _safe_fragment(analysis.get("garmentPlacement"))
    pose = _safe_fragment(analysis.get("pose") or analysis.get("pose_type"))
    framing = _safe_fragment(analysis.get("framing") or analysis.get("shot_type"))
    camera_angle = _safe_fragment(analysis.get("cameraAngle"))
    lighting = _safe_fragment(analysis.get("lighting"))
    environment = _safe_fragment(
        analysis.get("environment") or analysis.get("scene_type")
    )
    emphasis = _visual_emphasis_phrase(analysis.get("visualEmphasisSignals"))
    enhanced_direction = _safe_fragment(analysis.get("sexierVisualDirection"))
    extra_direction = _safe_fragment(creative_direction)
    visual_context = _join_parts([framing, camera_angle, lighting, environment])
    wardrobe_context = _join_parts([outfit, garment_fit, garment_placement])
    covered_topics = _topics_in_text(emphasis)
    enhancement_context = _compressed_enhancement_phrase(
        analysis.get("enhancementSuggestions"),
        covered_topics=covered_topics,
        extra_direction=extra_direction,
    )
    if not enhancement_context:
        enhancement_context = _compressed_enhancement_phrase(
            enhanced_direction,
            covered_topics=covered_topics,
            extra_direction=extra_direction,
        )
    if not enhancement_context and (
        enhanced_direction or analysis.get("enhancementSuggestions") or extra_direction
    ):
        enhancement_context = "stronger visual impact and confident glamour"

    camera_motion = _safe_fragment(analysis.get("camera_motion"))
    subject_motion = _safe_fragment(analysis.get("subject_motion"))
    motion_hint = _safe_fragment(analysis.get("motion_prompt_hint"))
    motion_bits = [bit for bit in [camera_motion, subject_motion] if bit]
    if motion_hint:
        current_motion = " ".join(motion_bits).lower()
        hint_probe = motion_hint[:80].lower()
        if not current_motion or hint_probe not in current_motion:
            if (
                not subject_motion
                or "sway" not in subject_motion.lower()
                or "sway" not in motion_hint.lower()
            ):
                motion_bits.append(motion_hint)
    motion_bits = [bit for bit in motion_bits if bit]
    if motion_bits:
        motion_formula = ". ".join(motion_bits[:4])
    else:
        motion_formula = (
            "subtle natural phone-camera movement, soft breathing, slight head movement, "
            "small posture shift, confident body language, and realistic fabric/body motion"
        )

    style_parts = _join_parts([wardrobe_context, visual_context])
    grid_sentences = [
        "Create one standalone 9:16 vertical portrait image.",
        _sentence(f"Style the subject in {style_parts}")
        if style_parts
        else (
            "Style the subject with fitted wardrobe, clean vertical framing, and soft natural lighting."
        ),
        _sentence(f"Pose and frame the image around {pose}") if pose else "",
        _sentence(f"Emphasize {emphasis}")
        if emphasis
        else (
            _sentence(f"Shape the image toward {enhancement_context}")
            if enhancement_context
            else ""
        ),
        (
            "Keep the full head and face visible with stable phone-photo composition, clear wardrobe, "
            "and natural social-photo realism."
        ),
    ]
    grid_prompt = " ".join(sentence for sentence in grid_sentences if sentence)
    motion_prompt = (
        "Animate the supplied 9:16 start image as a short realistic phone video. "
        "Keep the accepted still framing, room, outfit feel, camera angle, lighting, and start-image composition stable. "
        f"Apply this motion pattern: {motion_formula}."
    )
    notes = (
        operator_notes
        or reference_context
        or "Deterministic v1 prompt contract compiled from reference context."
    )
    parsed = parse_asset_prompt_response(
        json.dumps(
            {
                "higgsfieldGridPrompt": grid_prompt,
                "klingMotionPrompt": motion_prompt,
                "notes": notes,
            },
            ensure_ascii=False,
        )
    )
    return parsed


def build_gemini_motion_instruction() -> str:
    return """Analyze the attached short reference reel for motion only.

Return strict JSON only with:
{
  "camera_motion": "",
  "subject_motion": "",
  "motion_prompt_hint": ""
}

Rules:
- describe camera movement, body movement, timing, and pacing
- keep it compact and operational for one shared Kling image-to-video prompt
- output motion facts only
- leave outfit, identity, face, and final prompt writing to other stages
- use positive desired-motion language"""


def response_text_from_gemini(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            if part.get("text"):
                parts.append(str(part["text"]))
    return "\n".join(parts).strip()


def normalize_motion_analysis(data: dict[str, Any]) -> dict[str, str]:
    return {
        "camera_motion": _safe_motion_fragment(data.get("camera_motion")),
        "subject_motion": _safe_motion_fragment(data.get("subject_motion")),
        "motion_prompt_hint": _safe_motion_fragment(data.get("motion_prompt_hint")),
    }


def call_gemini_motion(
    reference_reel: Path,
    *,
    api_key: str,
    model: str = DEFAULT_GEMINI_MODEL,
    timeout: int = 120,
) -> dict[str, Any]:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": build_gemini_motion_instruction()},
                    {
                        "inline_data": {
                            "mime_type": video_mime_type(reference_reel),
                            "data": base64.b64encode(
                                reference_reel.read_bytes()
                            ).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "response_mime_type": "application/json",
        },
    }
    url = (
        GEMINI_GENERATE_URL.format(model=model) + "?key=" + urllib.parse.quote(api_key)
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    text = strip_json_fence(response_text_from_gemini(raw))
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini motion response must be a JSON object")
    return {
        "model": model,
        "analysis": normalize_motion_analysis(parsed),
        "rawResponse": raw,
    }


def build_xai_payload(
    *, model: str, frames: list[Path], instruction: str
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": instruction,
        }
    ]
    for frame in frames:
        content.append(
            {
                "type": "input_image",
                "image_url": data_uri(frame),
                "detail": "high",
            }
        )
    return {
        "model": model,
        "store": False,
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
    }


def response_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                parts.append(str(content.get("text") or ""))
    if parts:
        return "\n".join(parts).strip()
    choices = payload.get("choices") or []
    if choices:
        return str((choices[0].get("message") or {}).get("content") or "").strip()
    return ""


def strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_prompt_text(text: str) -> AssetPromptSet:
    text = strip_json_fence(text)
    try:
        return parse_asset_prompt_response(text)
    except ValueError:
        decoder = json.JSONDecoder(strict=False)
        try:
            data, _ = decoder.raw_decode(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                raise
            data, _ = decoder.raw_decode(match.group(0))
        return parse_asset_prompt_response(json.dumps(data, ensure_ascii=False))


def call_grok(
    payload: dict[str, Any], *, api_key: str, timeout: int = 3600
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        XAI_RESPONSES_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_secret_value(
    root: Path, names: tuple[str, ...], env_names: tuple[str, ...]
) -> str | None:
    for env_name in env_names:
        env_key = os.getenv(env_name)
        if env_key:
            return env_key
    for path in (
        root / "project_data" / "secrets.toml",
        config_path(root).with_suffix(".secrets.toml"),
    ):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() in names:
                return value.strip().strip('"').strip("'") or None
    return None


def load_xai_api_key(root: Path) -> str | None:
    return _load_secret_value(root, ("xai_api_key",), ("XAI_API_KEY",))


def load_gemini_api_key(root: Path) -> str | None:
    return _load_secret_value(
        root,
        ("gemini_api_key", "google_api_key"),
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )


def write_prompt_lineage(
    out_path: Path,
    *,
    reference_reel: Path | None,
    reference_images: list[Path],
    model: str,
    response: dict[str, Any] | None,
    prompt_set: AssetPromptSet | None,
    reference_analysis: dict[str, Any] | None = None,
    prompt_mode: str | None = None,
    raw_grok_prompt: str | None = None,
    cleaned_prompt: str | None = None,
    cleanup_diff: list[dict[str, Any]] | None = None,
    aspect_ratio: str | None = None,
    grid_layout: dict[str, Any] | None = None,
    prompt_enhancement: bool = HIGGSFIELD_PROMPT_ENHANCEMENT_ENABLED,
    reference_image_passed_to_higgsfield: bool = HIGGSFIELD_REFERENCE_IMAGE_PASSED,
    structured_prompt_spec: dict[str, Any] | None = None,
) -> Path:
    lineage = {
        "schema": "reel_factory.grok_prompt_lineage.v1",
        "createdAt": int(time.time()),
        "tool": "xai_grok_responses_api",
        "model": model,
        "prompt_mode": prompt_mode,
        "raw_grok_prompt": raw_grok_prompt,
        "cleaned_prompt": cleaned_prompt,
        "cleanup_diff": cleanup_diff or [],
        "aspect_ratio": aspect_ratio,
        "grid_layout": grid_layout,
        "prompt_enhancement": prompt_enhancement,
        "reference_image_passed_to_higgsfield": reference_image_passed_to_higgsfield,
        "structured_prompt_spec": structured_prompt_spec,
        "promptPath": str(out_path),
        "referenceReel": str(reference_reel) if reference_reel else None,
        "referenceImages": [str(p) for p in reference_images],
        "responseId": (response or {}).get("id"),
        "responseModel": (response or {}).get("model"),
        "usage": (response or {}).get("usage"),
        "promptFields": asdict(prompt_set) if prompt_set else None,
        "referenceAnalysis": reference_analysis,
        "humanReviewRequired": True,
    }
    path = out_path.with_suffix(out_path.suffix + ".grok_lineage.json")
    path.write_text(json.dumps(lineage, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def generate_prompt(
    *,
    out_path: Path,
    root: Path | None = None,
    reference_reel: Path | None = None,
    reference_images: list[Path] | None = None,
    model: str = DEFAULT_MODEL,
    creative_direction: str = "",
    reference_context: str = "",
    campaign: str | None = None,
    creator: str | None = None,
    retry_helper: str | None = None,
    operator_notes: str = "",
    dry_run: bool = False,
    reference_frame_mode: str = "first-visible",
    prompt_mode: str = GROK_DIRECT_COMPAT_MODE,
    grid_layout: str = "3x2",
    image_aspect_ratio: str = DEFAULT_PROMPT_IMAGE_ASPECT_RATIO,
) -> dict[str, Any]:
    root = (root or Path.cwd()).resolve()
    frames: list[Path] = []
    temp_ctx = None
    try:
        if reference_reel:
            frame_dir = out_path.parent / "_references" / out_path.stem
            frame_dir.mkdir(parents=True, exist_ok=True)
            if reference_frame_mode == "first-visible":
                first = extract_first_visible_frame(reference_reel, frame_dir)
                if first:
                    frames.append(first)
            frames.extend(extract_reference_frames(reference_reel, frame_dir))
        frames.extend(reference_images or [])
        if not frames:
            raise ValueError(
                "at least one reference reel or reference image is required"
            )
        memory = taste_memory(root, campaign=campaign) if campaign else ""
        retry_direction = retry_helper_direction(retry_helper)
        analysis_context = ""
        reference_analysis_record = None
        motion_analysis_record = None
        analysis_target = reference_reel or (reference_images or [None])[0]
        if analysis_target:
            from reference_analyzer import latest_analysis_record

            reference_analysis_record = latest_analysis_record(root, analysis_target)
            if reference_analysis_record:
                analysis_context = "Reference analysis:\n" + json.dumps(
                    reference_analysis_record["analysis"], indent=2, ensure_ascii=False
                )
            else:
                try:
                    from reference_analyzer import heuristic_analysis

                    reference_analysis_record = {
                        "analysis_id": None,
                        "reference_path": str(analysis_target),
                        "analysis": heuristic_analysis(Path(analysis_target)),
                    }
                except Exception:
                    reference_analysis_record = None
        if reference_reel:
            gemini_key = load_gemini_api_key(root)
            if gemini_key:
                try:
                    motion_analysis_record = call_gemini_motion(
                        reference_reel, api_key=gemini_key
                    )
                    if not reference_analysis_record:
                        reference_analysis_record = {
                            "analysis_id": None,
                            "reference_path": str(reference_reel),
                            "analysis": {},
                        }
                    merged_analysis = dict(
                        reference_analysis_record.get("analysis") or {}
                    )
                    merged_analysis.update(motion_analysis_record["analysis"])
                    reference_analysis_record["analysis"] = merged_analysis
                    analysis_context = "Reference analysis:\n" + json.dumps(
                        merged_analysis, indent=2, ensure_ascii=False
                    )
                except Exception as exc:
                    motion_analysis_record = {
                        "model": DEFAULT_GEMINI_MODEL,
                        "error": str(exc),
                    }
        merged_direction = "\n".join(
            filter(
                None, [creative_direction, analysis_context, retry_direction, memory]
            )
        )
        direct_prompt_mode = prompt_mode == GROK_DIRECT_COMPAT_MODE
        higgsfield_reference_mode = prompt_mode == HIGGSFIELD_REFERENCE_PROMPT_MODE
        structured_prompt_mode = prompt_mode == JSON_STRUCTURED_RECREATION_MODE
        reported_prompt_mode = (
            REFERENCE_FACTORY_SEXY_REALISTIC_MODE if direct_prompt_mode else prompt_mode
        )
        effective_grid_layout = "single" if higgsfield_reference_mode else grid_layout
        normalized_layout = normalize_grid_layout(effective_grid_layout)
        if higgsfield_reference_mode:
            instruction = build_higgsfield_reference_prompt_instruction(
                merged_direction
            )
        elif direct_prompt_mode:
            instruction = build_direct_higgsfield_prompt_instruction(
                merged_direction, grid_layout=effective_grid_layout
            )
        elif structured_prompt_mode:
            instruction = build_json_structured_recreation_instruction(
                merged_direction,
                grid_layout=effective_grid_layout,
                image_aspect_ratio=image_aspect_ratio,
            )
        else:
            instruction = build_user_instruction(reference_context, merged_direction)
        payload = build_xai_payload(model=model, frames=frames, instruction=instruction)
        if dry_run:
            motion_seed = compile_prompt_contract(
                reference_analysis=(reference_analysis_record or {}).get("analysis")
                if reference_analysis_record
                else None,
                reference_context=reference_context,
                creative_direction="\n".join(
                    filter(None, [creative_direction, retry_direction])
                ),
                operator_notes=operator_notes,
            )
            cleanup = {
                "raw": "",
                "cleaned": "",
                "diff": [],
                "removed": [],
                "residualForbiddenTerms": [],
                "valid": True,
                "changed": False,
                "policy": f"{reported_prompt_mode}_no_cleanup_needed",
            }
            structured_spec = None
            if (
                direct_prompt_mode
                or higgsfield_reference_mode
                or structured_prompt_mode
            ):
                api_key = load_xai_api_key(root)
                if not api_key:
                    raise RuntimeError(
                        "XAI_API_KEY or project_data/secrets.toml xai_api_key is required for live Grok prompt modes"
                    )
                response = None
                compiled = None
                raw_higgsfield_prompt = ""
                last_error = ""
                for attempt in range(2):
                    attempt_instruction = instruction
                    if last_error:
                        attempt_instruction += (
                            "\nPrevious prompt was rejected by the v1 validator: "
                            f"{last_error}. Rewrite with the same visual intent while satisfying the hard rules.\n"
                        )
                    attempt_payload = build_xai_payload(
                        model=model, frames=frames, instruction=attempt_instruction
                    )
                    response = call_grok(attempt_payload, api_key=api_key)
                    raw_text = response_text(response)
                    try:
                        if structured_prompt_mode:
                            structured_spec = normalize_structured_recreation_spec(
                                raw_text
                            )
                            raw_higgsfield_prompt = (
                                structured_recreation_spec_to_prompt(
                                    structured_spec,
                                    grid_layout=effective_grid_layout,
                                )
                            )
                        else:
                            raw_higgsfield_prompt = _direct_prompt_from_response_text(
                                raw_text
                            )
                        cleanup = clean_direct_higgsfield_prompt(raw_higgsfield_prompt)
                        compiled = parse_asset_prompt_response(
                            json.dumps(
                                {
                                    "higgsfieldGridPrompt": cleanup["cleaned"],
                                    "klingMotionPrompt": motion_seed.klingMotionPrompt,
                                    "notes": operator_notes
                                    or "Live Grok direct Higgsfield prompt; image compiler bypassed.",
                                },
                                ensure_ascii=False,
                            )
                        )
                        payload = attempt_payload
                        instruction = attempt_instruction
                        break
                    except ValueError as exc:
                        last_error = str(exc)
                if compiled is None:
                    raise ValueError(
                        f"direct Grok prompt rejected after retry: {last_error}"
                    )
            else:
                response = None
                compiled = motion_seed
                raw_higgsfield_prompt = compiled.higgsfieldGridPrompt
                cleanup = {
                    "raw": raw_higgsfield_prompt,
                    "cleaned": compiled.higgsfieldGridPrompt,
                    "diff": [],
                    "removed": [],
                    "residualForbiddenTerms": [],
                    "valid": True,
                    "changed": False,
                    "policy": "deterministic_compiler_no_cleanup_needed",
                }
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(asdict(compiled), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            raw_path = None
            if response is not None:
                raw_path = out_path.with_suffix(out_path.suffix + ".grok_raw.json")
                raw_path.write_text(
                    json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            lineage = {
                "prompt_mode": reported_prompt_mode,
                "raw_grok_prompt": raw_higgsfield_prompt,
                "cleaned_prompt": compiled.higgsfieldGridPrompt,
                "cleanup_diff": cleanup.get("diff", []),
                "aspect_ratio": image_aspect_ratio,
                "grid_layout": normalized_layout,
                "prompt_enhancement": HIGGSFIELD_PROMPT_ENHANCEMENT_ENABLED,
                "reference_image_passed_to_higgsfield": HIGGSFIELD_REFERENCE_IMAGE_PASSED,
                "structured_prompt_spec": structured_spec,
            }
            lineage_path = write_prompt_lineage(
                out_path,
                reference_reel=reference_reel,
                reference_images=frames,
                model=model,
                response=response,
                prompt_set=compiled,
                reference_analysis=reference_analysis_record,
                prompt_mode=reported_prompt_mode,
                raw_grok_prompt=raw_higgsfield_prompt,
                cleaned_prompt=compiled.higgsfieldGridPrompt,
                cleanup_diff=cleanup.get("diff", []),
                aspect_ratio=image_aspect_ratio,
                grid_layout=normalized_layout,
                prompt_enhancement=HIGGSFIELD_PROMPT_ENHANCEMENT_ENABLED,
                reference_image_passed_to_higgsfield=HIGGSFIELD_REFERENCE_IMAGE_PASSED,
                structured_prompt_spec=structured_spec,
            )
            return {
                "ok": True,
                "dry_run": True,
                "prompt_mode": reported_prompt_mode,
                "prompt_source": (
                    "live_grok_structured_reference_schema"
                    if structured_prompt_mode
                    else "live_grok_higgsfield_reference_prompt"
                    if higgsfield_reference_mode
                    else "live_grok_direct_higgsfield_prompt"
                    if direct_prompt_mode
                    else "deterministic_compiler"
                ),
                "model": model,
                "reference_images": [str(p) for p in frames],
                "output": str(out_path),
                "prompt_json_path": str(out_path),
                "raw_response_path": str(raw_path) if raw_path else None,
                "lineage_path": str(lineage_path),
                "lineage": lineage,
                "cleanup": cleanup,
                "prompt": asdict(compiled),
                "prompt_drift": prompt_drift_report(
                    raw_higgsfield_prompt, compiled.higgsfieldGridPrompt
                ),
                "structured_prompt_spec": structured_spec,
                "instruction_preview": instruction,
                "grid_layout": normalized_layout,
                "reference_analysis": reference_analysis_record,
                "motion_analysis": motion_analysis_record,
                "payload_preview": {
                    "model": payload["model"],
                    "store": payload["store"],
                    "input_parts": len(payload["input"][0]["content"]),
                },
            }
        raise RuntimeError(
            "Prompt generation is currently exposed as dry-run prompt JSON creation only; "
            "run with dry_run=True to write the prompt contract."
        )
    finally:
        if temp_ctx:
            temp_ctx.cleanup()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference-reel", type=Path)
    ap.add_argument("--reference-image", type=Path, action="append", default=[])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--creative-direction", default="")
    ap.add_argument("--reference-context", default="")
    ap.add_argument("--campaign")
    ap.add_argument("--creator")
    ap.add_argument(
        "--retry-helper",
        choices=[
            "fix_pose",
            "fix_hands",
            "less_smile",
            "more_reference_fidelity",
            "more_body_emphasis",
            "more_cleavage",
        ],
    )
    ap.add_argument(
        "--reference-frame-mode",
        choices=["first-visible", "sampled"],
        default="first-visible",
    )
    ap.add_argument(
        "--prompt-mode",
        choices=[
            GROK_DIRECT_COMPAT_MODE,
            HIGGSFIELD_REFERENCE_PROMPT_MODE,
            JSON_STRUCTURED_RECREATION_MODE,
            "compiled",
        ],
        default=GROK_DIRECT_COMPAT_MODE,
    )
    ap.add_argument(
        "--grid-layout",
        default="3x2",
        help="Prompt layout goal: single, 3x2, 2x3, 4x2, 2x4, 3x3, etc.",
    )
    ap.add_argument("--image-aspect-ratio", default=DEFAULT_PROMPT_IMAGE_ASPECT_RATIO)
    ap.add_argument("--operator-notes", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = generate_prompt(
        out_path=args.out.expanduser().resolve(),
        root=args.root.expanduser().resolve(),
        reference_reel=args.reference_reel.expanduser().resolve()
        if args.reference_reel
        else None,
        reference_images=[p.expanduser().resolve() for p in args.reference_image],
        model=args.model,
        creative_direction=args.creative_direction,
        reference_context=args.reference_context,
        campaign=args.campaign,
        creator=args.creator,
        retry_helper=args.retry_helper,
        operator_notes=args.operator_notes,
        dry_run=args.dry_run,
        reference_frame_mode=args.reference_frame_mode,
        prompt_mode=args.prompt_mode,
        grid_layout=args.grid_layout,
        image_aspect_ratio=args.image_aspect_ratio,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
