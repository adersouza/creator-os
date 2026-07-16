from __future__ import annotations

import json
from sqlite3 import Connection
from typing import Any

from pipeline_contracts import (
    validate_pattern_card,
    validate_video_analysis,
)

from .db import json_dump
from .identity import stable_id
from .reference_intake_contracts import (
    ANALYSIS_SCHEMA,
    FORMAT_PRIORITY,
    IG_OFM_CLOSENESS_CONTROLS,
    PATTERN_CARD_SCHEMA,
    _norm,
)


def _normalize_analysis(item: dict[str, Any]) -> dict[str, Any]:
    analysis = dict(item.get("analysis") or item)
    analysis["schema"] = str(analysis.get("schema") or ANALYSIS_SCHEMA)
    if analysis["schema"] == "reference_factory.reference_video_analysis.v1":
        analysis["schema"] = ANALYSIS_SCHEMA
    if analysis["schema"] == "reference_factory.video_recreation_blueprint.v1":
        analysis["schema"] = ANALYSIS_SCHEMA
    analysis = _expand_minimal_prompt_analysis(analysis)
    analysis["closenessControls"] = {
        **IG_OFM_CLOSENESS_CONTROLS,
        **(
            analysis.get("closenessControls")
            if isinstance(analysis.get("closenessControls"), dict)
            else {}
        ),
    }
    analysis["winningFormatCard"] = _winning_format_card(analysis, {})
    return analysis


def _expand_minimal_prompt_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    if not any(
        key in analysis
        for key in (
            "higgsfield_soul_image_prompt",
            "kling_3_video_prompt",
            "motion_notes",
            "camera_notes",
        )
    ):
        return analysis
    blueprint = _recreation_blueprint(analysis)
    first_frame = (
        blueprint.get("first_frame")
        if isinstance(blueprint.get("first_frame"), dict)
        else {}
    )
    motion_beats = (
        blueprint.get("motion_beats")
        if isinstance(blueprint.get("motion_beats"), list)
        else []
    )
    camera_notes = str(analysis.get("camera_notes") or "")
    motion_notes = str(analysis.get("motion_notes") or "")
    style_notes = str(analysis.get("style_notes") or "")
    copy_risk_notes = str(analysis.get("copy_risk_notes") or "")
    what_to_change = str(analysis.get("what_to_change") or "")
    analysis.setdefault("platformStyle", "instagram")
    analysis.setdefault("hookType", "other")
    analysis.setdefault("captionStyle", "inferred from source; avoid exact copy")
    analysis.setdefault(
        "shotSequence",
        [str(beat.get("subject_motion") or beat) for beat in motion_beats]
        or [motion_notes or "inferred source motion"],
    )
    analysis.setdefault(
        "camera",
        {
            "framing": first_frame.get("crop") or camera_notes,
            "angle": first_frame.get("body_angle") or camera_notes,
            "movement": "; ".join(
                str(beat.get("camera_motion") or "")
                for beat in motion_beats
                if isinstance(beat, dict)
            ).strip("; ")
            or motion_notes,
            "distance": first_frame.get("camera_distance"),
            "height": first_frame.get("camera_height"),
            "lensFeel": first_frame.get("lens_feel"),
        },
    )
    analysis.setdefault(
        "subject",
        {
            "action": "; ".join(
                str(beat.get("subject_motion") or "")
                for beat in motion_beats
                if isinstance(beat, dict)
            ).strip("; ")
            or motion_notes,
            "pose": first_frame.get("pose") or motion_notes,
            "expression": first_frame.get("facial_visibility") or style_notes,
            "wardrobe": first_frame.get("outfit_silhouette") or style_notes,
            "bodyAngle": first_frame.get("body_angle"),
            "phoneOrHandPosition": first_frame.get("phone_or_hand_position"),
        },
    )
    analysis.setdefault(
        "setting",
        {
            "location": first_frame.get("room_or_location_layout") or style_notes,
            "lighting": first_frame.get("lighting") or style_notes,
            "background": first_frame.get("room_or_location_layout") or style_notes,
        },
    )
    analysis.setdefault(
        "visualPacing",
        {"energy": "medium", "cutRhythm": motion_notes, "motion": motion_notes},
    )
    analysis.setdefault(
        "audioVibe", {"energy": "medium", "bpmFeel": style_notes, "moodTags": []}
    )
    analysis.setdefault(
        "textOverlay",
        {
            "placement": "infer from source",
            "fontStyle": "infer from source",
            "safeZoneNotes": "do not copy exact text",
        },
    )
    analysis.setdefault(
        "viralMechanics", [analysis.get("summary") or "format inferred by Gemini"]
    )
    analysis.setdefault("reuseRisk", "medium")
    analysis.setdefault(
        "transformationNotes", [what_to_change] if what_to_change else []
    )
    analysis.setdefault("qualityWarnings", [copy_risk_notes] if copy_risk_notes else [])
    return analysis


def _recreation_blueprint(analysis: dict[str, Any]) -> dict[str, Any]:
    for key in ("recreation_blueprint", "recreationBlueprint", "blueprint"):
        value = analysis.get(key)
        if isinstance(value, dict):
            return value
    raw = analysis.get("raw") if isinstance(analysis.get("raw"), dict) else {}
    for key in ("recreation_blueprint", "recreationBlueprint", "blueprint"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _blueprint_first_frame(analysis: dict[str, Any]) -> dict[str, Any]:
    blueprint = _recreation_blueprint(analysis)
    value = (
        blueprint.get("first_frame")
        or blueprint.get("firstFrame")
        or blueprint.get("first_frame_blueprint")
    )
    return value if isinstance(value, dict) else {}


def _blueprint_motion_beats(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    blueprint = _recreation_blueprint(analysis)
    value = (
        blueprint.get("motion_beats")
        or blueprint.get("motionBeats")
        or blueprint.get("motion_blueprint")
    )
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _blueprint_list(analysis: dict[str, Any], key: str) -> list[str]:
    blueprint = _recreation_blueprint(analysis)
    value = blueprint.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _blueprint_first_frame_text(analysis: dict[str, Any]) -> str:
    first = _blueprint_first_frame(analysis)
    if not first:
        return ""
    parts = [
        ("subject scale", first.get("subject_scale")),
        ("crop", first.get("crop")),
        ("body angle", first.get("body_angle")),
        ("pose", first.get("pose")),
        ("phone/hand placement", first.get("phone_or_hand_position")),
        ("facial visibility", first.get("facial_visibility")),
        ("outfit silhouette", first.get("outfit_silhouette")),
        ("location layout", first.get("room_or_location_layout")),
        ("lighting", first.get("lighting")),
        ("camera height", first.get("camera_height")),
        ("camera distance", first.get("camera_distance")),
        ("lens feel", first.get("lens_feel")),
    ]
    return "; ".join(f"{label}: {value}" for label, value in parts if value)


def _blueprint_motion_text(analysis: dict[str, Any]) -> str:
    beats = _blueprint_motion_beats(analysis)
    lines = []
    for beat in beats:
        time_range = beat.get("time_range") or beat.get("timeRange") or "beat"
        detail = "; ".join(
            str(value)
            for value in (
                beat.get("subject_motion"),
                beat.get("camera_motion"),
                beat.get("pose_change"),
                beat.get("notes"),
            )
            if value
        )
        if detail:
            lines.append(f"{time_range}: {detail}")
    return " ".join(lines)


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _image_prompt_json(analysis: dict[str, Any]) -> dict[str, Any]:
    for key in ("image_prompt_json", "imagePromptJson", "image_json", "imageJson"):
        value = analysis.get(key)
        if isinstance(value, dict):
            return value
    raw = analysis.get("raw") if isinstance(analysis.get("raw"), dict) else {}
    nested = raw.get("analysis") if isinstance(raw.get("analysis"), dict) else raw
    for key in ("image_prompt_json", "imagePromptJson", "image_json", "imageJson"):
        value = nested.get(key) if isinstance(nested, dict) else None
        if isinstance(value, dict):
            return value
    return {}


def _stringify_prompt_section(label: str, value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key, inner in value.items():
            if inner in (None, "", [], {}):
                continue
            if isinstance(inner, list):
                text = ", ".join(str(item) for item in inner if str(item).strip())
            else:
                text = str(inner)
            if text.strip():
                parts.append(f"{str(key).replace('_', ' ')}: {text}")
        return f"{label}: " + "; ".join(parts) if parts else ""
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value if str(item).strip())
        return f"{label}: {text}" if text else ""
    text = str(value or "").strip()
    return f"{label}: {text}" if text else ""


def _build_image_prompt_json_from_analysis(
    analysis: dict[str, Any], *, model_profile: str | None
) -> dict[str, Any]:
    existing = _image_prompt_json(analysis)
    if existing:
        return _sanitize_image_prompt_json(existing, model_profile=model_profile)
    first = _blueprint_first_frame(analysis)
    setting = (
        analysis.get("setting") if isinstance(analysis.get("setting"), dict) else {}
    )
    subject = (
        analysis.get("subject") if isinstance(analysis.get("subject"), dict) else {}
    )
    profile = _clean_prompt_text(model_profile) or "my Soul ID model"
    clothing = (
        first.get("outfit_silhouette")
        or subject.get("wardrobe")
        or "fitted social-safe outfit matching the source silhouette"
    )
    environment = (
        first.get("room_or_location_layout")
        or setting.get("location")
        or setting.get("background")
        or "source-matched lifestyle setting"
    )
    lighting = (
        first.get("lighting")
        or setting.get("lighting")
        or "source-matched natural lighting"
    )
    pose = (
        first.get("pose")
        or subject.get("pose")
        or subject.get("action")
        or "source-matched starting pose"
    )
    prompt = _clean_prompt_text(
        _analysis_value(analysis, "higgsfield_soul_image_prompt")
    )
    return _sanitize_image_prompt_json(
        {
            "subject": f"{profile} posing in the observed short-form format.",
            "composition": {
                "shot_type": analysis.get("contentFormat")
                or "vertical short-form reference frame",
                "aspect_ratio": "9:16",
                "framing": first.get("crop") or "match source crop and subject scale",
                "angle": first.get("body_angle") or "match source body/camera angle",
                "pose": pose,
                "face_visibility": first.get("facial_visibility")
                or subject.get("expression")
                or "match source facial visibility",
            },
            "clothing": {
                "item": clothing,
                "pattern": "preserve source outfit vibe when safe; change exact branding or identifiers",
                "fit": clothing,
                "constraints": "slightly sexier/spicier if the source supports it, non-explicit and platform-safe",
            },
            "body": {
                "build": "adapt to the selected Soul ID/model identity; preserve the source silhouette emphasis without copying the original person",
                "pose_details": first.get("body_angle")
                or first.get("pose")
                or "source-matched confident pose",
            },
            "environment": {
                "setting": environment,
                "details": [environment],
            },
            "lighting_and_camera": {
                "lighting": lighting,
                "camera_feel": first.get("lens_feel")
                or "real phone-native social media image",
                "quality": "sharp realistic phone photo, believable skin texture, not overprocessed",
            },
            "must_keep": [
                item
                for item in (
                    f"subject scale: {first.get('subject_scale')}"
                    if first.get("subject_scale")
                    else "",
                    f"crop: {first.get('crop')}" if first.get("crop") else "",
                    f"body angle: {first.get('body_angle')}"
                    if first.get("body_angle")
                    else "",
                    f"phone/hand placement: {first.get('phone_or_hand_position')}"
                    if first.get("phone_or_hand_position")
                    else "",
                    f"environment layout: {first.get('room_or_location_layout')}"
                    if first.get("room_or_location_layout")
                    else "",
                )
                if item
            ],
            "constraints": {
                "must_keep": [
                    item
                    for item in (
                        first.get("outfit_silhouette"),
                        first.get("phone_or_hand_position"),
                        first.get("facial_visibility"),
                        first.get("room_or_location_layout"),
                    )
                    if item
                ],
                "avoid": [
                    "visible copied identity",
                    "username",
                    "watermark",
                    "platform UI",
                    "explicit nudity",
                    "professional studio lighting unless source has it",
                    "cluttered background unless source has it",
                ],
            },
            "must_change": _blueprint_list(analysis, "required_changes")
            or [
                "replace original identity with my Soul ID model",
                "remove username, watermark, platform UI, and exact unique identifiers",
            ],
            "prompt": prompt,
            "negative_prompt": _clean_prompt_text(
                _analysis_value(analysis, "higgsfield_negative_prompt")
            ),
        },
        model_profile=model_profile,
    )


def _sanitize_image_prompt_json(
    card: dict[str, Any], *, model_profile: str | None
) -> dict[str, Any]:
    profile = _clean_prompt_text(model_profile) or "my Soul ID model"
    cleaned = _sanitize_prompt_value(json.loads(json.dumps(card)), profile=profile)
    cleaned["prompt_schema_version"] = (
        cleaned.get("prompt_schema_version") or "imageat_higgsfield.v1"
    )

    subject = _clean_prompt_text(cleaned.get("subject"))
    if subject:
        legacy_profile = "Adult " + profile
        subject = subject.replace(legacy_profile + " Soul ID model", profile)
        subject = subject.replace(legacy_profile, profile)
        subject = subject.replace("adult " + profile, profile)
        subject = subject.replace("adult my Soul ID model", profile)
        cleaned["subject"] = subject

    constraints = (
        cleaned.get("constraints")
        if isinstance(cleaned.get("constraints"), dict)
        else {}
    )
    avoid = constraints.get("avoid")
    if isinstance(avoid, list):
        banned = {
            "changed " + "hair color",
            "forced new " + "hairstyle",
            "tat" + "toos",
            "body markings",
            "scars",
            "new piercings",
        }
        constraints["avoid"] = [
            item for item in avoid if str(item).strip().lower() not in banned
        ]
        cleaned["constraints"] = constraints

    cleaned.setdefault(
        "skin",
        {
            "texture": "Realistic natural skin texture, believable phone-photo detail.",
        },
    )
    cleaned.setdefault(
        "expression_mood",
        {
            "vibe": "Confident, flirty, social-safe outfit-check energy.",
        },
    )

    return cleaned


def _sanitize_prompt_value(value: Any, *, profile: str) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_prompt_value(inner, profile=profile)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_prompt_value(item, profile=profile) for item in value]
    if not isinstance(value, str):
        return value
    legacy_profile = "Adult " + profile
    replacements = {
        legacy_profile + " Soul ID model": profile,
        legacy_profile: profile,
        "adult " + profile: profile,
        "adult my Soul ID model": profile,
        profile + "'s adult Soul ID figure": profile + "'s Soul ID figure",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _imageat_prompt_payload(card: dict[str, Any]) -> dict[str, Any]:
    ordered_keys = [
        "prompt_schema_version",
        "subject",
        "prompt",
        "composition",
        "hair",
        "clothing",
        "body",
        "skin",
        "expression_mood",
        "environment",
        "lighting_and_camera",
        "constraints",
        "must_keep",
        "must_change",
        "negative_prompt",
        "motion",
    ]
    return {
        key: card[key]
        for key in ordered_keys
        if card.get(key) not in (None, "", [], {})
    }


def _compose_higgsfield_from_image_json(
    card: dict[str, Any], *, model_profile: str | None, fallback_prompt: str
) -> str:
    card = _sanitize_image_prompt_json(card, model_profile=model_profile)
    if card.get("promptMode") == "structured_json" or (
        isinstance(card.get("composition"), dict)
        and isinstance(card.get("clothing"), dict)
    ):
        prompt_card = _imageat_prompt_payload(card)
        return json.dumps(prompt_card, indent=2, ensure_ascii=False)
    profile = _clean_prompt_text(model_profile) or "my Soul ID model"
    base_prompt = _clean_prompt_text(card.get("prompt")) or _clean_prompt_text(
        fallback_prompt
    )
    sections = [
        _stringify_prompt_section(
            "Subject", card.get("subject") or f"{profile} as the subject"
        ),
        _stringify_prompt_section("Composition", card.get("composition")),
        _stringify_prompt_section("Hair", card.get("hair")),
        _stringify_prompt_section("Clothing", card.get("clothing")),
        _stringify_prompt_section("Body", card.get("body")),
        _stringify_prompt_section("Skin", card.get("skin")),
        _stringify_prompt_section(
            "Expression and mood",
            card.get("expression_mood") or card.get("expressionMood"),
        ),
        _stringify_prompt_section("Environment", card.get("environment")),
        _stringify_prompt_section(
            "Lighting and camera",
            card.get("lighting_and_camera") or card.get("lightingAndCamera"),
        ),
        _stringify_prompt_section("Constraints", card.get("constraints")),
        _stringify_prompt_section(
            "Must keep", card.get("must_keep") or card.get("mustKeep")
        ),
        _stringify_prompt_section(
            "Must change", card.get("must_change") or card.get("mustChange")
        ),
    ]
    facts = ". ".join(section for section in sections if section)
    return (
        f"{base_prompt}. "
        f"{facts}. "
        "Keep the result slightly sexier/spicier only through pose, fitted styling, confidence, and framing; keep it non-explicit and social-platform safe. "
        "Do not copy the original person's identity, username, watermark, platform UI, or uniquely identifying details. "
        "Prioritize source-format accuracy over cinematic beauty."
    )


def _store_pattern_and_analysis(
    conn: Connection,
    *,
    job: dict[str, Any],
    analysis: dict[str, Any],
    provider: str,
    timestamp: str,
) -> None:
    pattern = (
        analysis.get("patternCard")
        if isinstance(analysis.get("patternCard"), dict)
        else {}
    )
    pattern_id = str(
        pattern.get("id")
        or stable_id("viral_pattern_card", job["reference_id"], provider)
    )
    pattern["id"] = pattern_id
    analysis["patternCard"] = pattern
    validate_pattern_card(pattern)
    validate_video_analysis(analysis)
    conn.execute(
        """
        INSERT INTO viral_pattern_cards (
          id, reference_id, analysis_job_id, platform, status, pattern_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'pattern_ready', ?, ?, ?)
        ON CONFLICT(reference_id, analysis_job_id) DO UPDATE SET
          platform = excluded.platform,
          status = excluded.status,
          pattern_json = excluded.pattern_json,
          updated_at = excluded.updated_at
        """,
        (
            pattern_id,
            job["reference_id"],
            job.get("id"),
            str(pattern.get("platform") or job.get("source_platform") or "unknown"),
            json_dump(pattern),
            timestamp,
            timestamp,
        ),
    )
    conn.execute(
        """
        INSERT INTO reference_video_analyses (
          id, reference_id, analysis_job_id, provider, status, media_json,
          signals_json, pattern_card_id, analysis_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(reference_id, provider) DO UPDATE SET
          analysis_job_id = excluded.analysis_job_id,
          status = excluded.status,
          media_json = excluded.media_json,
          signals_json = excluded.signals_json,
          pattern_card_id = excluded.pattern_card_id,
          analysis_json = excluded.analysis_json,
          updated_at = excluded.updated_at
        """,
        (
            analysis["id"],
            job["reference_id"],
            job.get("id"),
            _norm(provider),
            analysis.get("status") or "pattern_ready",
            json_dump(analysis.get("media") or {}),
            json_dump(analysis.get("signals") or {}),
            pattern_id,
            json_dump(analysis),
            timestamp,
            timestamp,
        ),
    )
    job_analysis = _analysis_from_pattern(analysis)
    raw_analysis = (
        (analysis.get("raw") or {}).get("analysis")
        if isinstance(analysis.get("raw"), dict)
        else {}
    )
    direct_prompt_fields = (
        "higgsfield_soul_image_prompt",
        "higgsfield_negative_prompt",
        "kling_3_video_prompt",
        "kling_negative_prompt",
        "motion_notes",
        "camera_notes",
        "style_notes",
        "copy_risk_notes",
        "what_to_change",
        "image_prompt_json",
    )
    for key in direct_prompt_fields:
        value = analysis.get(key) or (
            raw_analysis.get(key) if isinstance(raw_analysis, dict) else None
        )
        if value:
            job_analysis[key] = value
    blueprint = _recreation_blueprint(analysis) or (
        _recreation_blueprint(raw_analysis) if isinstance(raw_analysis, dict) else {}
    )
    if blueprint:
        job_analysis["recreation_blueprint"] = blueprint
    conn.execute(
        "UPDATE reference_analysis_jobs SET status = 'pattern_ready', analysis_json = ?, updated_at = ? WHERE id = ?",
        (json_dump(job_analysis), timestamp, job.get("id")),
    )


def _pattern_card_from_analysis(
    job: dict[str, Any], analysis: dict[str, Any]
) -> dict[str, Any]:
    card = _winning_format_card(analysis, job)
    visual_format = str(
        card.get("visualFormat") or analysis.get("contentFormat") or "other"
    )
    hook_type = str(analysis.get("hookType") or "pov")
    return {
        "schema": PATTERN_CARD_SCHEMA,
        "id": stable_id(
            "viral_pattern_card", job.get("reference_id"), visual_format, hook_type
        ),
        "platform": _norm(
            analysis.get("platformStyle") or job.get("source_platform") or "instagram"
        ),
        "source": {
            "referenceId": job.get("reference_id"),
            "creator": job.get("account"),
            "path": job.get("path"),
            "fileName": job.get("file_name"),
        },
        "formatType": visual_format,
        "hookType": hook_type,
        "visualPattern": str(
            analysis.get("summary")
            or f"{visual_format.replace('_', ' ')} creator reference"
        ),
        "setting": card.get("setting"),
        "shotSequence": analysis.get("shotSequence")
        if isinstance(analysis.get("shotSequence"), list)
        else ["short-form opening beat"],
        "cameraStyle": analysis.get("camera")
        if isinstance(analysis.get("camera"), dict)
        else card.get("camera") or {},
        "subjectAction": str(
            (analysis.get("subject") or {}).get("action")
            if isinstance(analysis.get("subject"), dict)
            else card.get("poseAction") or "creator-style pose"
        ),
        "textOverlayStyle": analysis.get("textOverlay")
        if isinstance(analysis.get("textOverlay"), dict)
        else card.get("textOverlay") or {},
        "pacing": analysis.get("visualPacing")
        if isinstance(analysis.get("visualPacing"), dict)
        else card.get("pacing") or {},
        "audioVibe": analysis.get("audioVibe")
        if isinstance(analysis.get("audioVibe"), dict)
        else card.get("audioVibe") or {},
        "ctaPattern": analysis.get("ctaPattern"),
        "reuseRisk": str(analysis.get("reuseRisk") or "medium")
        if str(analysis.get("reuseRisk") or "medium") in {"low", "medium", "high"}
        else "medium",
        "copyRiskNotes": card.get("copyRiskNotes")
        or analysis.get("copyRiskNotes")
        or [
            "Do not copy creator identity, exact overlay copy, watermark, or username."
        ],
        "transformationInstructions": card.get("transformationInstructions")
        or analysis.get("transformationNotes")
        or ["Change model identity, scene details, outfit, caption, and audio."],
        "viralityMetrics": analysis.get("viralityMetrics")
        if isinstance(analysis.get("viralityMetrics"), dict)
        else {},
        "qualityWarnings": analysis.get("qualityWarnings")
        if isinstance(analysis.get("qualityWarnings"), list)
        else [],
    }


def _analysis_from_pattern(analysis: dict[str, Any]) -> dict[str, Any]:
    pattern = analysis.get("patternCard") or {}
    return {
        "schema": ANALYSIS_SCHEMA,
        "referenceId": analysis.get("referenceId"),
        "summary": pattern.get("visualPattern") or "Local reference analysis",
        "platformStyle": pattern.get("platform") or "instagram",
        "contentFormat": pattern.get("formatType") or "other",
        "hookType": pattern.get("hookType") or "pov",
        "captionStyle": (pattern.get("textOverlayStyle") or {}).get("fontStyle")
        or "white text with dark stroke",
        "closenessControls": dict(IG_OFM_CLOSENESS_CONTROLS),
        "winningFormatCard": _format_card_from_pattern(pattern),
        "shotSequence": pattern.get("shotSequence") or [],
        "camera": pattern.get("cameraStyle") or {},
        "subject": {"action": pattern.get("subjectAction")},
        "setting": {
            "location": (
                _format_card_from_pattern(pattern).get("setting")
                or "source-inspired but original setting"
            )
        },
        "visualPacing": pattern.get("pacing") or {},
        "audioVibe": pattern.get("audioVibe") or {},
        "textOverlay": pattern.get("textOverlayStyle") or {},
        "viralMechanics": [
            "format familiarity",
            "fast-readable overlay",
            "native audio slot",
        ],
        "reuseRisk": pattern.get("reuseRisk") or "medium",
        "transformationNotes": pattern.get("transformationInstructions") or [],
        "qualityWarnings": pattern.get("qualityWarnings") or [],
        "patternCard": pattern,
    }


def _format_card_from_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    return {
        "visualFormat": pattern.get("formatType") or "other",
        "formatPriorityRank": FORMAT_PRIORITY.index(pattern.get("formatType")) + 1
        if pattern.get("formatType") in FORMAT_PRIORITY
        else len(FORMAT_PRIORITY),
        "poseAction": pattern.get("subjectAction"),
        "camera": pattern.get("cameraStyle") or {},
        "lighting": "source-matched flattering light",
        "setting": pattern.get("setting") or "source-inspired but original setting",
        "styling": "model-appropriate spicy OFM-coded styling",
        "textOverlay": pattern.get("textOverlayStyle") or {},
        "pacing": pattern.get("pacing") or {},
        "audioVibe": pattern.get("audioVibe") or {},
        "hookMechanics": ["clear premise", "fast recognition"],
        "copyRiskNotes": pattern.get("copyRiskNotes") or [],
        "transformationInstructions": pattern.get("transformationInstructions") or [],
    }


def _kling_scenes(
    analysis: dict[str, Any], card: dict[str, Any]
) -> list[dict[str, Any]]:
    beats = _blueprint_motion_beats(analysis)
    if beats:
        return [
            {
                "timeRange": str(beat.get("time_range") or beat.get("timeRange") or ""),
                "durationSeconds": None,
                "action": str(beat.get("subject_motion") or ""),
                "camera": str(
                    beat.get("camera_motion")
                    or "preserve first-frame phone-native camera"
                ),
                "poseChange": str(beat.get("pose_change") or ""),
                "notes": str(beat.get("notes") or ""),
            }
            for beat in beats[:4]
        ]
    sequence = (
        analysis.get("shotSequence")
        if isinstance(analysis.get("shotSequence"), list)
        else []
    )
    if not sequence:
        sequence = (
            card.get("transformationInstructions")
            if isinstance(card.get("transformationInstructions"), list)
            else []
        )
    if not sequence:
        sequence = [
            "open on the Soul ID model in the source-inspired format",
            "hold for readable caption and subtle expression shift",
        ]
    duration = 5
    per_scene = max(1, round(duration / min(len(sequence), 4), 2))
    return [
        {
            "durationSeconds": per_scene,
            "action": str(item),
            "camera": (card.get("camera") or {}).get("movement")
            if isinstance(card.get("camera"), dict)
            else "phone-native subtle motion",
        }
        for item in sequence[:4]
    ]


def _json_from_model_text(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Gemini response did not contain a JSON object")
        parsed = json.loads(clean[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Gemini response JSON must be an object")
    return parsed


def _analysis_value(analysis: dict[str, Any], key: str) -> Any:
    if analysis.get(key) is not None:
        return analysis.get(key)
    raw = analysis.get("raw") if isinstance(analysis.get("raw"), dict) else {}
    nested = raw.get("analysis") if isinstance(raw.get("analysis"), dict) else {}
    return nested.get(key)


def _clean_prompt_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _classify_reference_format(
    source: dict[str, Any], analysis: dict[str, Any] | None = None
) -> str:
    analysis = analysis or {}
    explicit = _norm(
        analysis.get("contentFormat") or analysis.get("visualFormat") or ""
    )
    aliases = {
        "mirror": "mirror_selfie",
        "mirror_selfie": "mirror_selfie",
        "selfie": "selfie_video",
        "selfie_video": "selfie_video",
        "pov": "pov",
        "pov_style": "pov",
        "lifestyle": "spicy_lifestyle",
        "lifestyle_scene": "spicy_lifestyle",
        "travel": "spicy_lifestyle",
        "travel_scene": "spicy_lifestyle",
        "slide": "slideshow",
        "slides": "slideshow",
        "slideshow": "slideshow",
    }
    if explicit in aliases:
        return aliases[explicit]
    if explicit in FORMAT_PRIORITY:
        return explicit
    text = " ".join(
        str(value or "")
        for value in (
            source.get("file_name"),
            source.get("fileName"),
            source.get("account"),
            source.get("path"),
            analysis.get("summary"),
        )
    ).lower()
    if "mirror" in text:
        return "mirror_selfie"
    if "selfie" in text:
        return "selfie_video"
    if any(
        word in text for word in ("bedroom", "car", "lifestyle", "fit", "glam", "ofm")
    ):
        return "spicy_lifestyle"
    if "slide" in text or source.get("kind") == "image":
        return "slideshow"
    return "selfie_video" if source.get("kind") == "video" else "other"


def _winning_format_card(
    analysis: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    existing = (
        analysis.get("winningFormatCard")
        if isinstance(analysis.get("winningFormatCard"), dict)
        else {}
    )
    visual_format = _classify_reference_format(source, {**analysis, **existing})
    camera = (
        existing.get("camera")
        if isinstance(existing.get("camera"), dict)
        else analysis.get("camera") or {}
    )
    text_overlay = (
        existing.get("textOverlay")
        if isinstance(existing.get("textOverlay"), dict)
        else analysis.get("textOverlay") or {}
    )
    pacing = (
        existing.get("pacing")
        if isinstance(existing.get("pacing"), dict)
        else analysis.get("visualPacing") or {}
    )
    audio = (
        existing.get("audioVibe")
        if isinstance(existing.get("audioVibe"), dict)
        else analysis.get("audioVibe") or {}
    )
    subject = analysis.get("subject") or {}
    setting = analysis.get("setting") or {}
    priority_rank = (
        FORMAT_PRIORITY.index(visual_format) + 1
        if visual_format in FORMAT_PRIORITY
        else len(FORMAT_PRIORITY)
    )
    return {
        "visualFormat": visual_format,
        "formatPriorityRank": int(existing.get("formatPriorityRank") or priority_rank),
        "poseAction": existing.get("poseAction")
        or subject.get("action")
        or subject.get("pose")
        or "confident phone-native pose",
        "camera": camera
        or {"framing": "vertical 9:16", "angle": "phone-native", "movement": "subtle"},
        "lighting": existing.get("lighting")
        or setting.get("lighting")
        or "soft flattering light",
        "setting": existing.get("setting")
        or setting.get("location")
        or "creator-style lifestyle setting",
        "styling": existing.get("styling")
        or subject.get("wardrobe")
        or "model-appropriate spicy OFM-coded styling",
        "textOverlay": text_overlay
        or {
            "copy": "",
            "placement": "safe top or lower third",
            "fontStyle": "white text with dark stroke",
        },
        "pacing": pacing
        or {
            "energy": "medium",
            "cutRhythm": "single native shot",
            "durationFeel": "short reel",
        },
        "audioVibe": audio
        or {
            "energy": "medium",
            "bpmFeel": "current native sound",
            "moodTags": ["glam", "relationship"],
        },
        "hookMechanics": existing.get("hookMechanics")
        or analysis.get("viralMechanics")
        or [],
        "copyRiskNotes": existing.get("copyRiskNotes")
        or [
            "Do not copy face, username, exact overlay copy, watermark, or distinctive personal identity."
        ],
        "transformationInstructions": existing.get("transformationInstructions")
        or analysis.get("transformationNotes")
        or [
            "Keep the format and hook mechanics, but change the model identity, outfit, scene, overlay text, and audio choice."
        ],
    }


def _style_tags(analysis: dict[str, Any]) -> list[str]:
    tags = [
        str(analysis.get("platformStyle") or "short_form"),
        str(analysis.get("contentFormat") or "creator"),
        str(analysis.get("hookType") or "pov"),
    ]
    audio = analysis.get("audioVibe") or {}
    tags.extend(str(tag) for tag in audio.get("moodTags") or [])
    return sorted({tag for tag in (_norm(tag) for tag in tags) if tag})
