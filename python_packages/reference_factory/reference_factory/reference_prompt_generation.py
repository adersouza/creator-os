from __future__ import annotations

import json
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from creator_os_core.fileops import atomic_write_text

from pipeline_contracts.validator import (
    validate_higgsfield_soul_image_prompt,
    validate_kling_3_video_prompt,
)

from .db import json_dump, json_load
from .identity import stable_id
from .reference_analysis import (
    _analysis_value,
    _blueprint_first_frame,
    _blueprint_first_frame_text,
    _blueprint_list,
    _blueprint_motion_beats,
    _blueprint_motion_text,
    _build_image_prompt_json_from_analysis,
    _classify_reference_format,
    _clean_prompt_text,
    _compose_higgsfield_from_image_json,
    _kling_scenes,
    _pattern_card_from_analysis,
    _recreation_blueprint,
    _style_tags,
    _winning_format_card,
)
from .reference_intake_contracts import (
    ANALYSIS_SCHEMA,
    DEFAULT_INTAKE_PROFILE,
    FORMAT_PRIORITY,
    IG_OFM_CLOSENESS_CONTROLS,
    PROMPT_READY_STATUS,
    _canonical_tool,
    _closeness_controls,
    _norm,
)
from .timeutil import now_iso


def generate_video_prompts(
    conn: Connection,
    *,
    data_root: Path,
    target_tools: list[str] | None = None,
    model_profile: str | None = None,
    limit: int = 50,
    include_pending: bool = True,
    creative_plan_id: str | None = None,
) -> dict[str, object]:
    tools = [
        _canonical_tool(tool)
        for tool in (target_tools or ["higgsfield_soul_image", "kling_3_video"])
    ]
    model_key = model_profile or ""
    rows = conn.execute(
        """
        WITH eligible AS (
          SELECT *
          FROM reference_analysis_jobs
          WHERE status IN ('analyzed', 'pattern_ready')
             OR (? = 1 AND status = 'needs_analysis')
        )
        SELECT raj.*, sf.path, sf.account, sf.file_name, sf.kind
        FROM eligible raj
        JOIN source_files sf ON sf.reference_id = raj.reference_id
        WHERE NOT EXISTS (
          SELECT 1
          FROM eligible newer
          WHERE newer.reference_id = raj.reference_id
            AND (
              newer.updated_at > raj.updated_at
              OR (newer.updated_at = raj.updated_at AND newer.id > raj.id)
            )
        )
        ORDER BY raj.updated_at DESC
        LIMIT ?
        """,
        (1 if include_pending else 0, limit),
    ).fetchall()
    timestamp = now_iso()
    prompts: list[dict[str, Any]] = []
    for row in rows:
        job = dict(row)
        analysis = json_load(job.get("analysis_json"), {})
        if not analysis:
            analysis = _heuristic_analysis(job)
        for target_tool in tools:
            prompt_json = _prompt_for_tool(target_tool, job, analysis, model_profile)
            if creative_plan_id:
                prompt_json["creativePlanId"] = creative_plan_id
            prompt_id = stable_id(
                "generated_video_prompt",
                job["reference_id"],
                target_tool,
                model_key,
            )
            prompt_json["id"] = prompt_id
            conn.execute(
                """
                INSERT INTO generated_video_prompts (
                  id, analysis_job_id, reference_id, target_tool, model_profile,
                  prompt_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reference_id, target_tool, model_profile) DO UPDATE SET
                  analysis_job_id = excluded.analysis_job_id,
                  prompt_json = excluded.prompt_json,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    prompt_id,
                    job["id"],
                    job["reference_id"],
                    target_tool,
                    model_key,
                    json_dump(prompt_json),
                    PROMPT_READY_STATUS,
                    timestamp,
                    timestamp,
                ),
            )
            prompts.append(
                {
                    "id": prompt_id,
                    "analysisJobId": job["id"],
                    "referenceId": job["reference_id"],
                    "targetTool": target_tool,
                    "status": PROMPT_READY_STATUS,
                    "creativePlanId": creative_plan_id,
                    "prompt": prompt_json,
                }
            )
    conn.commit()
    export = export_video_prompts(
        conn,
        data_root=data_root,
        limit=max(limit * max(1, len(tools)), 1),
        creative_plan_id=creative_plan_id,
    )
    return {
        "schema": "reference_factory.generate_video_prompts.v1",
        "count": len(prompts),
        "targetTools": tools,
        "modelProfile": model_key,
        "includePending": include_pending,
        "creativePlanId": creative_plan_id,
        "export": export,
        "prompts": prompts[:10],
    }


def export_video_prompts(
    conn: Connection,
    *,
    data_root: Path,
    limit: int = 100,
    creative_plan_id: str | None = None,
) -> dict[str, object]:
    output_dir = data_root / "reference_intake"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """
        SELECT gvp.*, sf.path, sf.account, sf.file_name
        FROM generated_video_prompts gvp
        JOIN source_files sf ON sf.reference_id = gvp.reference_id
        WHERE gvp.status = ?
        ORDER BY gvp.updated_at DESC
        LIMIT ?
        """,
        (PROMPT_READY_STATUS, limit),
    ).fetchall()
    prompts = []
    for row in rows:
        item = dict(row)
        prompt_json = json_load(item["prompt_json"], {})
        if creative_plan_id:
            prompt_json["creativePlanId"] = creative_plan_id
        prompts.append(
            {
                "id": item["id"],
                "referenceId": item["reference_id"],
                "analysisJobId": item["analysis_job_id"],
                "targetTool": item["target_tool"],
                "modelProfile": item.get("model_profile"),
                "status": item["status"],
                "sourcePath": item["path"],
                "account": item.get("account"),
                "fileName": item["file_name"],
                "creativePlanId": creative_plan_id or prompt_json.get("creativePlanId"),
                "prompt": prompt_json,
            }
        )
    manifest = {
        "schema": "reference_factory.generated_video_prompts.v1",
        "count": len(prompts),
        "creativePlanId": creative_plan_id,
        "prompts": prompts,
    }
    json_path = output_dir / "generated_video_prompts.json"
    jsonl_path = output_dir / "generated_video_prompts.jsonl"
    md_path = output_dir / "generated_video_prompts.md"
    image_jsonl_path = output_dir / "daily_higgsfield_image_prompts.jsonl"
    kling_jsonl_path = output_dir / "daily_kling_video_prompts.jsonl"
    review_path = output_dir / "daily_prompt_review.md"
    for prompt in prompts:
        _validate_prompt_contract(prompt["targetTool"], prompt["prompt"])
    atomic_write_text(
        json_path,
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with jsonl_path.open("w", encoding="utf-8") as f:
        for prompt in prompts:
            f.write(json.dumps(prompt, ensure_ascii=False, sort_keys=True) + "\n")
    with image_jsonl_path.open("w", encoding="utf-8") as f:
        for prompt in prompts:
            if prompt["targetTool"] == "higgsfield_soul_image":
                f.write(
                    json.dumps(prompt["prompt"], ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
    with kling_jsonl_path.open("w", encoding="utf-8") as f:
        for prompt in prompts:
            if prompt["targetTool"] == "kling_3_video":
                f.write(
                    json.dumps(prompt["prompt"], ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
    atomic_write_text(md_path, _video_prompts_markdown(prompts), encoding="utf-8")
    atomic_write_text(
        review_path, _daily_prompt_review_markdown(prompts), encoding="utf-8"
    )
    return {
        "schema": "reference_factory.export_video_prompts.v1",
        "count": len(prompts),
        "creativePlanId": creative_plan_id,
        "jsonPath": str(json_path),
        "jsonlPath": str(jsonl_path),
        "markdownPath": str(md_path),
        "dailyHiggsfieldImageJsonlPath": str(image_jsonl_path),
        "dailyKlingVideoJsonlPath": str(kling_jsonl_path),
        "dailyPromptReviewPath": str(review_path),
    }


def gemini_analysis_prompt(
    source: dict[str, Any],
    *,
    platform: str = "unknown",
    account_profile: str | None = None,
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    prompt_style: str = "guided",
) -> str:
    profile = _norm(intake_profile)
    if _norm(prompt_style) == "minimal":
        return _minimal_gemini_analysis_prompt(source, platform=platform)
    closeness = _closeness_controls(profile)
    profile_rules = ""
    if profile == DEFAULT_INTAKE_PROFILE:
        profile_rules = f"""
IG-first OFM-coded profile:
- Prioritize formats in this order: {", ".join(FORMAT_PRIORITY)}.
- Preserve the winning format closely while changing the person, scene details, styling, overlay copy, and audio.
- Keep it spicy/social-coded without explicit nudity or direct identity copying.
- Closeness controls: {json.dumps(closeness, sort_keys=True)}.
- Filename/metadata format hint: {_classify_reference_format(source, {})}.
"""
    return f"""Analyze this short-form reference video/image for original AI video generation.

Source file: {source.get("path")}
Platform/source: {_norm(platform)}
Reference account/folder: {source.get("account") or "unknown"}
Target account/model profile: {account_profile or "not specified"}
Intake profile: {profile}
{profile_rules}

Rules:
- Do not copy the exact person, face, identity, watermark, username, or copyrighted audio.
- Extract reusable creative direction only.
- Treat trending audio as native/manual attach guidance, not burned-in audio.
- Output strict JSON only.

Return this JSON shape:
{{
  "schema": "{ANALYSIS_SCHEMA}",
  "referenceId": "{source.get("reference_id")}",
  "summary": "one sentence",
  "platformStyle": "tiktok|instagram|unknown",
  "contentFormat": "mirror_selfie|selfie_video|spicy_lifestyle|slideshow|talking_head|fit_check|other",
  "hookType": "relationship|glowup|confession|pov|question|other",
  "captionStyle": "short text overlay style",
  "closenessControls": {json.dumps(closeness, ensure_ascii=False, sort_keys=True)},
  "winningFormatCard": {{
    "visualFormat": "mirror_selfie|selfie_video|spicy_lifestyle|slideshow|other",
    "formatPriorityRank": 1,
    "poseAction": "...",
    "camera": {{"framing": "...", "angle": "...", "movement": "..."}},
    "lighting": "...",
    "setting": "...",
    "styling": "...",
    "textOverlay": {{"copy": "...", "placement": "...", "fontStyle": "..."}},
    "pacing": {{"energy": "low|medium|high", "cutRhythm": "...", "durationFeel": "..."}},
    "audioVibe": {{"energy": "low|medium|high", "bpmFeel": "...", "moodTags": ["..."]}},
    "hookMechanics": ["why the hook pulls attention"],
    "copyRiskNotes": ["what would be too close to copy"],
    "transformationInstructions": ["specific changes for a new original version"]
  }},
  "shotSequence": ["shot 1", "shot 2"],
  "camera": {{"framing": "...", "angle": "...", "movement": "..."}},
  "subject": {{"action": "...", "pose": "...", "expression": "...", "wardrobe": "..."}},
  "setting": {{"location": "...", "lighting": "...", "background": "..."}},
  "visualPacing": {{"energy": "low|medium|high", "cutRhythm": "...", "motion": "..."}},
  "audioVibe": {{"energy": "low|medium|high", "bpmFeel": "...", "moodTags": ["..."]}},
  "textOverlay": {{"placement": "...", "fontStyle": "...", "safeZoneNotes": "..."}},
  "viralMechanics": ["why it works"],
  "reuseRisk": "low|medium|high",
  "transformationNotes": ["how to make a new original version"],
  "qualityWarnings": ["anything to avoid"]
}}
"""


def _minimal_gemini_analysis_prompt(
    source: dict[str, Any], *, platform: str = "unknown"
) -> str:
    return f"""You are analyzing one short-form social video/image that I uploaded.

Watch the media carefully. Your job is not to summarize or make a loose inspired prompt. Your job is to reverse-engineer a recreation blueprint that preserves the exact winning format: first-frame composition, crop, body angle, pose geometry, phone/hand placement, camera distance, room layout, lighting, motion timing, and native social-media feel.

Important: describe the starting frame like an image-to-JSON converter. Prefer concrete visual facts over creative prose. The structured `image_prompt_json` is the primary source for Higgsfield, so it must look like the example format below: nested subject/composition/hair/clothing/body/skin/expression/environment/lighting/constraints fields, not a flattened paragraph.

Source file: {source.get("path")}
Platform/source: {_norm(platform)}
Reference account/folder: {source.get("account") or "unknown"}

Goal:
- Produce a practical Higgsfield Soul ID first-frame image prompt that can recreate the STARTING FRAME composition.
- Produce a practical Kling 3.0 video prompt that uses that generated Higgsfield image as the first/reference frame and recreates the observed motion beats.
- Copy the winning format, pose, framing, and motion closely, but replace the person with "my Soul ID model" and change enough identity-specific details to avoid direct copying.

Rules:
- Do not copy the original person's identity, face, username, watermark, logos, exact text, or uniquely identifying details.
- Do not add new body markings or identity traits. If hair is visible, describe the observed hair only inside the `hair` field.
- Do not invent objects, actions, outfits, or settings that are not visible or strongly implied by the video.
- Do not upgrade the video into a polished cinematic ad. Keep amateur, phone-shot, platform-native realism unless the source itself is polished.
- Preserve outfit silhouette and fit category, but change exact color/pattern/branding.
- For spicy influencer/OOTD references, keep the sensual framing and fitted outfit category when safe, but keep it non-explicit and social-platform safe.
- Preserve the room/location type and composition, but change unique decor and identifying details.
- If mirror selfie: describe exact mirror composition, crop, subject scale, body angle, phone position, facial visibility, visible limbs, and background layout.
- If POV/selfie: describe exact camera distance, lens feel, walking path, hand gestures, lean-in timing, and expression changes.
- Kling prompt must be beat/timestamp based, not a vague paragraph.
- If audio is available, infer only the vibe/energy; do not recommend burning copyrighted/trending audio into the file.
- Output strict JSON only. No markdown. No explanation outside JSON.

Example `image_prompt_json` style to imitate:
{{
  "promptMode": "structured_json",
  "subject": "Stunning young woman with an alluring, confident presence taking a mirror selfie in a bright minimalist bedroom.",
  "composition": {{
    "shot_type": "Full-body mirror selfie",
    "angle": "Side profile with slight twist toward the mirror, emphasizing the outfit silhouette",
    "pose": "Standing with arched back and pushed-out hips to create a strong hourglass S-curve. Right hand holds a white phone up covering most of her face, left arm slightly extended behind her. Flirty, confident body language."
  }},
  "hair": {{
    "style": "Long, voluminous curls",
    "color": "Honey brown with golden highlights",
    "texture": "Thick coiled ringlets cascading down her back and over one shoulder."
  }},
  "clothing": {{
    "item": "Very short strapless mini dress",
    "pattern": "Leopard print with brown and black rosettes",
    "fit": "Skin-tight bodycon fabric that closely follows the waist, hips, and thighs."
  }},
  "body": {{
    "build": "Slim-thick, toned yet curvaceous figure with pronounced hips and long smooth legs",
    "pose_details": "Weight shifted to one leg, creating a strong S-curve posture that highlights the waist-to-hip shape."
  }},
  "skin": {{
    "tone": "Fair with warm golden undertones",
    "texture": "Smooth, soft, and realistic with natural daylight highlights."
  }},
  "expression_mood": {{
    "vibe": "Playful, flirty, confident",
    "details": "Teasing outfit-check body language, realistic social-media selfie mood."
  }},
  "environment": {{
    "setting": "Bright, clean minimalist bedroom",
    "details": ["White tufted headboard bed", "messy striped sheets", "fluffy white rug", "plain white walls", "black vertical mirror frame"]
  }},
  "lighting_and_camera": {{
    "lighting": "Soft bright natural daylight from the side with gentle flattering shadows.",
    "camera_feel": "Casual smartphone mirror selfie aesthetic, vertical composition, realistic phone photography with slight grain."
  }},
  "constraints": {{
    "must_keep": ["Mirror selfie pose with phone covering face", "side-profile body emphasis", "fitted outfit silhouette", "minimalist bedroom setting"],
    "avoid": ["visible copied face", "loose clothing", "professional studio lighting", "cluttered background", "watermark", "platform UI"]
  }},
  "negative_prompt": "blurry, low quality, deformed body, bad anatomy, extra limbs, visible copied face, baggy outfit, dark lighting, professional photoshoot, text, watermark, oversaturated, cartoonish"
}}

Return exactly this JSON-compatible shape:
{{
  "schema": "{ANALYSIS_SCHEMA}",
  "referenceId": "{source.get("reference_id")}",
  "summary": "one sentence describing what happens in the video",
  "contentFormat": "infer the format, e.g. mirror_selfie, selfie_video, slideshow, pov, lifestyle_scene, talking_head, other",
  "recreation_blueprint": {{
    "format_type": "mirror_selfie|selfie_video|slideshow|pov|lifestyle_scene|talking_head|other",
    "first_frame": {{
      "subject_scale": "how large the subject appears in frame",
      "crop": "head/torso/legs crop and edge cutoffs",
      "body_angle": "front/profile/three-quarter angle and hip/shoulder orientation",
      "pose": "exact starting pose geometry",
      "phone_or_hand_position": "phone/hand placement relative to face/body/lens",
      "facial_visibility": "face visible, partly hidden, fully hidden by phone, etc.",
      "outfit_silhouette": "fit category and silhouette without exact copying",
      "room_or_location_layout": "visible background layout and object placement",
      "lighting": "source direction, brightness, shadows, color temperature",
      "camera_height": "low/chest/eye/mirror height",
      "camera_distance": "close/medium/far and mirror/lens distance",
      "lens_feel": "phone wide/normal/selfie lens feel"
    }},
    "motion_beats": [
      {{
        "time_range": "0.0-1.0s",
        "subject_motion": "observed body/face/hand movement",
        "camera_motion": "observed camera movement",
        "pose_change": "how the pose changes",
        "notes": "timing or realism notes"
      }}
    ],
    "native_style_constraints": ["specific rules to keep this looking like a real IG/TikTok post"],
    "copy_risk_notes": ["what would be too close to copy"],
    "required_changes": ["what to change while preserving the format"]
  }},
  "image_prompt_json": {{
    "promptMode": "structured_json",
    "subject": "one sentence in the same ImageAt-style tone as the example; describe the generated subject without naming the source person",
    "composition": {{
      "shot_type": "full-body mirror selfie, close selfie, POV, etc.",
      "aspect_ratio": "9:16",
      "framing": "exact crop and frame edges",
      "angle": "front/profile/three-quarter/POV angle",
      "pose": "exact starting pose and limb placement",
      "face_visibility": "face visible, partly obscured, or fully covered"
    }},
    "hair": {{
      "style": "visible hair style from the source frame, if relevant",
      "color": "visible hair color from the source frame, if relevant",
      "texture": "visible hair texture and polish level from the source frame, if relevant"
    }},
    "clothing": {{
      "item": "specific clothing item/category",
      "pattern": "pattern/color/vibe to preserve or adapt",
      "fit": "fit and silhouette",
      "constraints": "non-explicit, platform-safe notes"
    }},
    "body": {{
      "build": "body silhouette only, adapted to my model/Soul ID; keep 19 years old and non-explicit",
      "pose_details": "how the pose emphasizes shape or movement without explicit nudity"
    }},
    "environment": {{
      "setting": "location type",
      "details": ["visible room/location details to preserve as a format"]
    }},
    "lighting_and_camera": {{
      "lighting": "lighting quality and direction",
      "camera_feel": "phone/pro/cinematic/mirror quality",
      "quality": "realistic texture/detail notes"
    }},
    "expression_mood": {{
      "vibe": "flirty/confident/playful/casual/etc. inferred from source",
      "details": "body language and social-native mood; keep platform-safe"
    }},
    "constraints": {{
      "must_keep": ["visual facts that matter most for matching the source format"],
      "avoid": ["visible copied face", "usernames", "watermarks", "platform UI", "explicit nudity", "model errors", "professional studio lighting unless the source has it"]
    }},
    "must_change": ["identity, username, watermark, exact protected details, and small scene variations"],
    "prompt": "paste-ready Higgsfield image prompt written from the structured visual facts; use my Soul ID model; slightly sexier/spicier if the source supports it, but non-explicit",
    "negative_prompt": "things to avoid in the image"
  }},
  "higgsfield_soul_image_prompt": "first-frame image prompt for Higgsfield Soul ID using my Soul ID model, with pose, outfit, setting, lighting, expression, framing, and style",
  "higgsfield_negative_prompt": "things to avoid in the image",
  "kling_3_video_prompt": "beat/timestamp based video prompt for Kling 3.0 using the generated Higgsfield image as first/reference frame; include subject motion, camera movement, pacing, duration/aspect ratio, and continuity",
  "kling_negative_prompt": "things to avoid in the video",
  "motion_notes": "observed subject motion, camera motion, timing, cuts, speed, and pacing",
  "camera_notes": "framing, angle, lens feel, camera distance, movement, stabilization/handheld feel",
  "style_notes": "lighting, setting, wardrobe/style, mood, platform-native vibe, text overlay if present, audio vibe if available",
  "copy_risk_notes": "what would be too close to the original and must be changed",
  "what_to_change": "specific scene/person/text/audio details to change while preserving the winning format"
}}
"""


def _heuristic_analysis(job: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        str(value or "")
        for value in (job.get("file_name"), job.get("account"), job.get("path"))
    ).lower()
    content_format = _classify_reference_format(job, {})
    hook_type = (
        "relationship"
        if any(word in text for word in ("boy", "girl", "relationship", "love"))
        else "pov"
    )
    analysis = {
        "schema": ANALYSIS_SCHEMA,
        "referenceId": job.get("reference_id"),
        "summary": "Short-form creator reference needing Gemini review.",
        "platformStyle": job.get("source_platform") or "unknown",
        "contentFormat": content_format,
        "hookType": hook_type,
        "captionStyle": "short high-contrast text overlay",
        "shotSequence": ["single vertical reference composition"],
        "camera": {
            "framing": "vertical 9:16",
            "angle": "phone-style",
            "movement": "subtle handheld or still",
        },
        "subject": {
            "action": "pose naturally",
            "pose": "casual confident pose",
            "expression": "soft confident",
            "wardrobe": "account-appropriate outfit",
        },
        "setting": {
            "location": "bedroom, mirror, car, or lifestyle setting",
            "lighting": "soft flattering light",
            "background": "clean lifestyle background",
        },
        "visualPacing": {
            "energy": "medium",
            "cutRhythm": "short-form native",
            "motion": "subtle",
        },
        "audioVibe": {
            "energy": "medium",
            "bpmFeel": "current native sound",
            "moodTags": ["glam", "relationship", "ai_ofm"],
        },
        "textOverlay": {
            "placement": "safe top or lower third",
            "fontStyle": "white text with dark stroke",
            "safeZoneNotes": "avoid face and app UI",
        },
        "viralMechanics": ["clear visual identity", "simple hook", "native audio fit"],
        "reuseRisk": "medium",
        "transformationNotes": [
            "change setting, styling, pose, caption, and audio while preserving only the format"
        ],
        "qualityWarnings": [
            "needs manual Gemini analysis before high-confidence reuse"
        ],
    }
    analysis["closenessControls"] = dict(IG_OFM_CLOSENESS_CONTROLS)
    analysis["winningFormatCard"] = _winning_format_card(analysis, job)
    return analysis


def _prompt_for_tool(
    target_tool: str,
    job: dict[str, Any],
    analysis: dict[str, Any],
    model_profile: str | None,
) -> dict[str, Any]:
    target_tool = _canonical_tool(target_tool)
    if target_tool == "higgsfield_soul_image":
        return _higgsfield_prompt(job, analysis, model_profile)
    if target_tool == "kling_3_video":
        return _kling_prompt(job, analysis, model_profile)
    raise ValueError(f"unsupported target tool: {target_tool}")


def _compose_higgsfield_main_prompt(
    *,
    analysis_prompt: Any,
    analysis: dict[str, Any],
    model_profile: str | None,
    fallback_prompt: str,
) -> str:
    image_card = _build_image_prompt_json_from_analysis(
        analysis, model_profile=model_profile
    )
    if image_card:
        return _compose_higgsfield_from_image_json(
            image_card, model_profile=model_profile, fallback_prompt=fallback_prompt
        )
    body = _clean_prompt_text(analysis_prompt) or _clean_prompt_text(fallback_prompt)
    blueprint = _blueprint_first_frame_text(analysis)
    native_constraints = "; ".join(
        _blueprint_list(analysis, "native_style_constraints")
    )
    required_changes = "; ".join(_blueprint_list(analysis, "required_changes"))
    profile = _clean_prompt_text(model_profile) or "the selected Soul ID profile"
    return (
        "Higgsfield Soul ID first-frame image prompt. "
        f"Use {profile} as the subject identity. "
        "Generate one vertical 9:16 reference image only, not a video. "
        "Match the reference STARTING FRAME composition closely: same crop, subject scale, body angle, pose geometry, camera height, camera distance, lens feel, phone/hand placement, facial visibility, lighting type, and room/location layout. "
        "Replace the person with my Soul ID model. Preserve the outfit silhouette and fit category, but change exact color/pattern/branding. Preserve the room/location type, but change unique decor and identifying details. "
        "Keep amateur phone-shot Instagram Reels realism; do not make it cinematic, polished, or fashion-editorial unless the source is. "
        f"Observed first-frame blueprint: {blueprint or body}. "
        f"Scene prompt: {body}. "
        f"Native constraints: {native_constraints or 'realistic iPhone/social camera, imperfect natural framing, believable anatomy'}. "
        f"Required changes: {required_changes or 'new identity, no copied face, no exact outfit, no username, no watermark, no exact text'}. "
        "This image must be a clean first/reference frame that Kling can animate without reframing."
    )


def _compose_kling_main_prompt(
    *,
    analysis_prompt: Any,
    analysis: dict[str, Any],
    model_profile: str | None,
    fallback_prompt: str,
) -> str:
    body = _clean_prompt_text(analysis_prompt) or _clean_prompt_text(fallback_prompt)
    first_frame = _blueprint_first_frame_text(analysis)
    directives = _motion_directives(analysis, fallback_motion=body)
    must_preserve = "; ".join(directives["must_preserve"])
    avoid = "; ".join(directives["avoid"])
    return (
        "Kling 3.0 image-to-video prompt. "
        "Use the generated image as the first/reference frame. "
        "Preserve the starting image; animate it without redesigning it. "
        "Create a vertical 9:16 Instagram Reels clip with realistic phone-native motion and no audio. "
        f"Frame-0 blueprint to preserve: {first_frame or 'preserve the generated first-frame composition exactly'}. "
        f"Subject motion: {directives['subject_motion']}. "
        f"Camera motion: {directives['camera_motion']}. "
        f"Duration: {directives['duration_seconds']} seconds. "
        f"Must preserve: {must_preserve}. "
        f"Avoid: {avoid}."
    )


def _motion_directives(
    analysis: dict[str, Any], *, fallback_motion: str = ""
) -> dict[str, Any]:
    first = _blueprint_first_frame(analysis)
    beats = _blueprint_motion_beats(analysis)
    first_beat = beats[0] if beats and isinstance(beats[0], dict) else {}
    subject_motion = (
        fallback_motion
        or _clean_prompt_text(first_beat.get("subject_motion"))
        or _blueprint_motion_text(analysis)
        or "subtle natural body movement and relaxed breathing"
    )
    camera_motion = (
        _clean_prompt_text(first_beat.get("camera_motion"))
        or "tiny handheld phone sway, no zoom, no cinematic pan"
    )
    preserve = [
        "same first-frame crop",
        "same pose geometry",
        "same outfit continuity",
        "same room/background layout",
        "same phone/camera placement",
        "same lighting",
    ]
    if first.get("phone_or_hand_position"):
        preserve.append(f"phone/hand placement: {first['phone_or_hand_position']}")
    if first.get("facial_visibility"):
        preserve.append(f"facial visibility: {first['facial_visibility']}")
    return {
        "duration_seconds": 5,
        "camera_motion": camera_motion,
        "subject_motion": subject_motion,
        "must_preserve": preserve,
        "avoid": [
            "zoom",
            "cinematic camera move",
            "face reveal",
            "outfit change",
            "room change",
            "platform UI",
            "username",
            "watermark",
        ],
        "fallback_provider": "grok_imagine",
    }


def _higgsfield_prompt(
    job: dict[str, Any], analysis: dict[str, Any], model_profile: str | None
) -> dict[str, Any]:
    subject = analysis.get("subject") or {}
    setting = analysis.get("setting") or {}
    camera = analysis.get("camera") or {}
    card = _winning_format_card(analysis, job)
    pattern = (
        analysis.get("patternCard")
        if isinstance(analysis.get("patternCard"), dict)
        else _pattern_card_from_analysis(job, analysis)
    )
    pattern_id = str(
        pattern.get("id")
        or stable_id(
            "viral_pattern_card", job.get("reference_id"), card.get("visualFormat")
        )
    )
    pacing = analysis.get("visualPacing") or card.get("pacing") or {}
    text_overlay = analysis.get("textOverlay") or {}
    fallback_prompt = (
        f"Create a high-quality first-frame image for an Instagram Reel in the {card.get('visualFormat', analysis.get('contentFormat', 'selfie_video'))} format. "
        f"The Soul ID model {subject.get('action') or card.get('poseAction') or 'poses naturally'} in {setting.get('location') or card.get('setting') or 'a clean lifestyle setting'}, "
        f"wearing {subject.get('wardrobe') or card.get('styling') or 'model-appropriate styling'}, with {setting.get('lighting') or card.get('lighting') or 'soft flattering lighting'}. "
        f"Keep the winning format close, but make the scene original: new wardrobe, new room/details, new pose micro-variation, and no copied identity."
    )
    return {
        "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
        "tool": "higgsfield_soul_image",
        "status": PROMPT_READY_STATUS,
        "promptSource": "gemini_import"
        if _analysis_value(analysis, "higgsfield_soul_image_prompt")
        else "heuristic",
        "sourceReferenceId": job.get("reference_id"),
        "sourcePatternId": pattern_id,
        "modelProfile": model_profile,
        "intakeProfile": DEFAULT_INTAKE_PROFILE,
        "closenessControls": dict(IG_OFM_CLOSENESS_CONTROLS),
        "formatCard": card,
        "soulIdInstruction": "Replace the source identity. Do not copy face, username, watermark, or distinctive personal likeness.",
        "mainPrompt": _compose_higgsfield_main_prompt(
            analysis_prompt=_analysis_value(analysis, "higgsfield_soul_image_prompt"),
            analysis=analysis,
            model_profile=model_profile,
            fallback_prompt=fallback_prompt,
        ),
        "imagePromptJson": _build_image_prompt_json_from_analysis(
            analysis, model_profile=model_profile
        ),
        "cameraPrompt": f"{camera.get('framing', 'vertical 9:16 close framing')}; {camera.get('angle', 'phone-style angle')}; {camera.get('movement', 'subtle natural motion')}.",
        "motionPrompt": f"{subject.get('pose', 'confident casual pose')}; expression: {subject.get('expression', 'soft confident')}; pacing: {pacing.get('cutRhythm', 'short-form native rhythm')}.",
        "lightingPrompt": f"{setting.get('lighting', 'soft flattering light')}; background: {setting.get('background', 'clean lifestyle background')}.",
        "captionDirection": f"{analysis.get('captionStyle', 'short high-contrast overlay')}; placement: {text_overlay.get('placement', 'safe top or lower third')}.",
        "audioDirection": "Recommend native platform audio separately; do not burn trending/licensed audio into the generated file.",
        "negativePrompt": _analysis_value(analysis, "higgsfield_negative_prompt")
        or "copied face, copied identity, watermark, username, platform UI, unreadable text, broken anatomy, underage appearance, explicit nudity, low resolution",
        "recreationBlueprint": _recreation_blueprint(analysis),
        "aspectRatio": "9:16",
        "durationSeconds": 6,
        "styleTags": _style_tags(analysis),
        "operatorNotes": analysis.get("transformationNotes")
        or (
            [_analysis_value(analysis, "what_to_change")]
            if _analysis_value(analysis, "what_to_change")
            else []
        ),
        "reviewNotes": card.get("copyRiskNotes")
        or (
            [_analysis_value(analysis, "copy_risk_notes")]
            if _analysis_value(analysis, "copy_risk_notes")
            else []
        ),
    }


def _kling_prompt(
    job: dict[str, Any], analysis: dict[str, Any], model_profile: str | None
) -> dict[str, Any]:
    subject = analysis.get("subject") or {}
    setting = analysis.get("setting") or {}
    camera = analysis.get("camera") or {}
    card = _winning_format_card(analysis, job)
    pattern = (
        analysis.get("patternCard")
        if isinstance(analysis.get("patternCard"), dict)
        else _pattern_card_from_analysis(job, analysis)
    )
    pattern_id = str(
        pattern.get("id")
        or stable_id(
            "viral_pattern_card", job.get("reference_id"), card.get("visualFormat")
        )
    )
    pacing = analysis.get("visualPacing") or card.get("pacing") or {}
    fallback_prompt = (
        f"Original vertical Instagram Reels style video, {card.get('visualFormat', analysis.get('contentFormat', 'creator reference'))} format, "
        f"fictional creator/model, {subject.get('wardrobe', 'stylish casual wardrobe')}, "
        f"{subject.get('action', 'natural pose and subtle movement')} in {setting.get('location', 'a lifestyle setting')}. "
        f"Mood: {analysis.get('summary', 'viral short-form visual pattern')}. Copy the format closely, but avoid copying the source identity, exact scene, text, or watermark."
    )
    return {
        "schema": "reference_factory.kling_3_video_prompt.v1",
        "tool": "kling_3_video",
        "status": PROMPT_READY_STATUS,
        "promptSource": "gemini_import"
        if _analysis_value(analysis, "kling_3_video_prompt")
        else "heuristic",
        "sourceReferenceId": job.get("reference_id"),
        "sourcePatternId": pattern_id,
        "modelProfile": model_profile,
        "intakeProfile": DEFAULT_INTAKE_PROFILE,
        "closenessControls": dict(IG_OFM_CLOSENESS_CONTROLS),
        "formatCard": card,
        "firstFrameInstruction": "Use the generated Higgsfield image as the first/reference frame. Preserve that image, not the reference creator.",
        "mainPrompt": _compose_kling_main_prompt(
            analysis_prompt=_analysis_value(analysis, "kling_3_video_prompt"),
            analysis=analysis,
            model_profile=model_profile,
            fallback_prompt=fallback_prompt,
        ),
        "camera": {
            "framing": camera.get("framing", "vertical 9:16"),
            "angle": camera.get("angle", "phone-style angle"),
            "movement": camera.get("movement", "subtle handheld movement"),
        },
        "motion": {
            "subject": subject.get("pose", "confident natural pose"),
            "expression": subject.get("expression", "soft confident expression"),
            "pacing": pacing.get("cutRhythm", "short-form native rhythm"),
        },
        "motion_directives": _motion_directives(
            analysis,
            fallback_motion=_analysis_value(analysis, "kling_3_video_prompt")
            or fallback_prompt,
        ),
        "lighting": setting.get("lighting", "soft flattering lighting"),
        "negativePrompt": _analysis_value(analysis, "kling_negative_prompt")
        or "watermark, username, exact likeness, copied person, distorted hands, distorted face, bad text, extra limbs, low quality, platform UI",
        "aspectRatio": "9:16",
        "durationSeconds": 5,
        "scenes": _kling_scenes(analysis, card),
        "recreationBlueprint": _recreation_blueprint(analysis),
        "styleTags": _style_tags(analysis),
        "nativeAudioPlan": analysis.get("audioVibe") or {},
        "reviewNotes": card.get("copyRiskNotes")
        or (
            [_analysis_value(analysis, "copy_risk_notes")]
            if _analysis_value(analysis, "copy_risk_notes")
            else []
        ),
    }


def _validate_prompt_contract(target_tool: str, prompt: dict[str, Any]) -> None:
    tool = _canonical_tool(target_tool)
    if tool == "higgsfield_soul_image":
        validate_higgsfield_soul_image_prompt(prompt)
        return
    if tool == "kling_3_video":
        validate_kling_3_video_prompt(prompt)


def _video_prompts_markdown(prompts: list[dict[str, Any]]) -> str:
    lines = ["# Generated AI Video Prompt Drafts", ""]
    for index, item in enumerate(prompts, start=1):
        prompt = item.get("prompt") or {}
        main = prompt.get("mainPrompt") or ""
        lines.extend(
            [
                f"## {index}. {item['targetTool']} - {item['fileName']}",
                f"- Source: `{item['sourcePath']}`",
                f"- Status: `{item['status']}`",
                "",
                "```text",
                str(main),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _daily_prompt_review_markdown(prompts: list[dict[str, Any]]) -> str:
    grouped: dict[str, dict[str, Any]] = {}
    for item in prompts:
        prompt = item.get("prompt") or {}
        if prompt.get("promptSource") != "gemini_import":
            continue
        if not str(prompt.get("mainPrompt") or "").strip():
            continue
        ref = item["referenceId"]
        grouped.setdefault(
            ref,
            {
                "fileName": item["fileName"],
                "sourcePath": item["sourcePath"],
                "account": item.get("account"),
                "prompts": {},
            },
        )
        grouped[ref]["prompts"][item["targetTool"]] = prompt
    lines = [
        "# Daily Higgsfield + Kling Prompt Review",
        "",
        "Use this for the manual Gemini Pro -> Higgsfield Soul ID -> Kling 3.0 workflow.",
        "Identity copying is blocked; copy the winning format, not the person.",
        "",
        "Only actual Gemini-imported prompt pairs are shown here. Heuristic placeholders are hidden.",
        "",
    ]
    for index, bundle in enumerate(grouped.values(), start=1):
        image_prompt = bundle["prompts"].get("higgsfield_soul_image") or {}
        kling_prompt = bundle["prompts"].get("kling_3_video") or {}
        if not image_prompt or not kling_prompt:
            continue
        card = image_prompt.get("formatCard") or kling_prompt.get("formatCard") or {}
        lines.extend(
            [
                f"## {index}. {bundle['fileName']}",
                f"- Source: `{bundle['sourcePath']}`",
                f"- Account/folder: `{bundle.get('account') or 'unknown'}`",
                f"- Format: `{card.get('visualFormat', 'unknown')}`",
                f"- Status: `{image_prompt.get('status') or kling_prompt.get('status') or PROMPT_READY_STATUS}`",
                "",
                "### Higgsfield Soul ID Image Prompt",
                "```text",
                str(image_prompt.get("mainPrompt") or ""),
                "```",
                "",
                "### Kling 3.0 Video Prompt",
                "```text",
                str(kling_prompt.get("mainPrompt") or ""),
                "```",
                "",
                "### Copy-Risk Notes",
            ]
        )
        for note in card.get("copyRiskNotes") or ["Do not copy source identity."]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)
