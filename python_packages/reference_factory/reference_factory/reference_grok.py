from __future__ import annotations

import base64
import json
import mimetypes
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from creator_os_core.fileops import atomic_write_text

from pipeline_contracts.llm_resilience import urlopen_json_with_retry

from .prompt_records import (
    find_prompt_record as _find_prompt_record,
)
from .prompt_records import (
    read_jsonl_records as _read_jsonl_records,
)
from .prompt_records import (
    record_reference_id as _record_reference_id,
)
from .prompt_records import (
    write_jsonl_records as _write_jsonl_records,
)
from .reference_analysis import _json_from_model_text
from .reference_intake import (
    import_reference_analysis,
    queue_reference_analysis,
)
from .reference_intake_contracts import (
    ANALYSIS_SCHEMA,
    DEFAULT_INTAKE_PROFILE,
    GROK_PROMPT_MODEL_DEFAULT,
    XAI_CHAT_COMPLETIONS_URL,
)
from .reference_prompt_generation import generate_video_prompts
from .timeutil import now_iso


def analyze_reference_with_grok_api(
    conn: Connection,
    *,
    source_root: Path,
    data_root: Path,
    platform: str = "instagram",
    account_profile: str | None = None,
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    media_kinds: list[str] | None = None,
    limit: int = 1,
    model: str = GROK_PROMPT_MODEL_DEFAULT,
    api_key: str | None = None,
    prompt_style: str = "imageat",
    ffmpeg: str = "ffmpeg",
) -> dict[str, object]:
    resolved_key = (
        api_key or os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
    )
    if not resolved_key:
        raise RuntimeError(
            "Set XAI_API_KEY or GROK_API_KEY before running Grok API analysis."
        )

    queued = queue_reference_analysis(
        conn,
        source_root,
        data_root=data_root,
        platform=platform,
        provider_target="grok_api",
        account_profile=account_profile,
        intake_profile=intake_profile,
        media_kinds=media_kinds or ["video", "image"],
        limit=limit,
        prompt_style="minimal",
    )
    analyzed = 0
    errors: list[dict[str, object]] = []
    imported_items: list[dict[str, Any]] = []
    frame_dir = data_root / "reference_intake" / "grok_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for job in queued.get("jobs") or []:
        try:
            source = Path(str(job.get("sourcePath") or "")).expanduser()
            if not source.exists():
                raise FileNotFoundError(f"source file missing: {source}")
            image_path = _grok_reference_image(
                source,
                frame_dir=frame_dir,
                reference_id=str(job.get("referenceId") or "reference"),
                ffmpeg=ffmpeg,
            )
            prompt = _grok_prompt_builder(job, prompt_style=prompt_style)
            response = _xai_chat_completion(
                api_key=resolved_key,
                model=model,
                prompt=prompt,
                image_path=image_path,
            )
            analysis = _json_from_model_text(response)
            analysis["analysisJobId"] = job["id"]
            analysis["referenceId"] = job["referenceId"]
            analysis.setdefault("schema", ANALYSIS_SCHEMA)
            analysis.setdefault("provider", "grok_api")
            image_json = analysis.get("image_prompt_json")
            if isinstance(image_json, dict):
                image_json.setdefault("promptMode", "structured_json")
            imported_items.append(analysis)
            analyzed += 1
        except Exception as exc:
            errors.append(
                {
                    "analysisJobId": job.get("id"),
                    "sourcePath": job.get("sourcePath"),
                    "error": str(exc),
                }
            )
    import_path = data_root / "reference_intake" / "grok_api_import_latest.json"
    import_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        import_path,
        json.dumps({"items": imported_items}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    imported = (
        import_reference_analysis(conn, import_path)
        if imported_items
        else {"imported": 0, "errors": []}
    )
    generated = (
        generate_video_prompts(
            conn,
            data_root=data_root,
            target_tools=["higgsfield_soul_image", "kling_3_video"],
            model_profile=account_profile,
            limit=max(1, analyzed),
            include_pending=False,
        )
        if imported.get("imported")
        else None
    )
    return {
        "schema": "reference_factory.grok_api_analysis.v1",
        "model": model,
        "queued": queued.get("queued"),
        "analyzed": analyzed,
        "errors": errors,
        "importPath": str(import_path),
        "import": imported,
        "promptGeneration": generated,
    }


def compile_prompts_with_grok_api(
    *,
    data_root: Path,
    reference_id: str,
    reference_media: Path,
    model: str = GROK_PROMPT_MODEL_DEFAULT,
    api_key: str | None = None,
    ffmpeg: str = "ffmpeg",
    instructions: str | None = None,
) -> dict[str, object]:
    resolved_key = (
        api_key or os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
    )
    if not resolved_key:
        raise RuntimeError(
            "Set XAI_API_KEY or GROK_API_KEY before running Grok prompt compilation."
        )

    prompt_dir = data_root / "reference_intake"
    image_path = prompt_dir / "daily_higgsfield_image_prompts.jsonl"
    video_path = prompt_dir / "daily_kling_video_prompts.jsonl"
    image_rows = _read_jsonl_records(image_path)
    video_rows = _read_jsonl_records(video_path)
    image_prompt = _find_prompt_record(image_rows, reference_id)
    video_prompt = _find_prompt_record(video_rows, reference_id)
    if image_prompt is None or video_prompt is None:
        raise RuntimeError(
            f"Missing paired Higgsfield/Kling prompt records for reference_id={reference_id}"
        )

    frame_dir = prompt_dir / "grok_prompt_compiler_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    reference_image = _grok_reference_image(
        reference_media, frame_dir=frame_dir, reference_id=reference_id, ffmpeg=ffmpeg
    )
    response = _xai_chat_completion(
        api_key=resolved_key,
        model=model,
        prompt=_grok_prompt_compiler_prompt(
            reference_id=reference_id,
            image_prompt=image_prompt,
            video_prompt=video_prompt,
            instructions=instructions,
        ),
        image_path=reference_image,
        response_format=_grok_prompt_compiler_response_format(),
    )
    compiled = _normalize_compiled_prompt_set(_json_from_model_text(response))
    _validate_compiled_prompt_set(compiled)

    metadata = {
        "schema": "reference_factory.grok_prompt_compiler_metadata.v1",
        "provider": "grok_api",
        "model": model,
        "referenceId": reference_id,
        "referenceImage": str(reference_image),
        "compiledAt": now_iso(),
    }
    for row in image_rows:
        if _record_reference_id(row) == reference_id:
            row["compiledPrompts"] = {
                "provider": "grok_api",
                "model": model,
                "soul_id_2x3_prompt": compiled["soul_id_2x3_prompt"],
                "single_panel_prompt": compiled["single_panel_prompt"],
                "structured_breakdown": compiled["structured_breakdown"],
                "confidence_score": compiled["confidence_score"],
                "notes": compiled.get("notes") or "",
            }
            row["compiledPromptMetadata"] = metadata
    for row in video_rows:
        if _record_reference_id(row) == reference_id:
            row["compiledPrompts"] = {
                "provider": "grok_api",
                "model": model,
                "kling_video_prompt": compiled["kling_video_prompt"],
                "kling_negative_prompt": compiled.get("kling_negative_prompt") or "",
                "structured_breakdown": compiled["structured_breakdown"],
                "confidence_score": compiled["confidence_score"],
                "notes": compiled.get("notes") or "",
            }
            row["compiledPromptMetadata"] = metadata

    _write_jsonl_records(image_path, image_rows)
    _write_jsonl_records(video_path, video_rows)
    out_path = prompt_dir / f"grok_compiled_prompts_{reference_id}.json"
    atomic_write_text(
        out_path,
        json.dumps(
            {
                "schema": "reference_factory.grok_compiled_prompts.v1",
                "referenceId": reference_id,
                "model": model,
                "referenceImage": str(reference_image),
                "compiledPrompts": compiled,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "schema": "reference_factory.grok_prompt_compiler.v1",
        "referenceId": reference_id,
        "model": model,
        "referenceImage": str(reference_image),
        "compiledPath": str(out_path),
        "updated": {
            "higgsfieldImagePrompts": str(image_path),
            "klingVideoPrompts": str(video_path),
        },
        "compiledPrompts": compiled,
    }


def _grok_reference_image(
    source: Path, *, frame_dir: Path, reference_id: str, ffmpeg: str
) -> Path:
    source = source.expanduser().resolve()
    suffix = source.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return source
    output = frame_dir / f"{reference_id}_grok_frame.jpg"
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "1",
            "-i",
            str(source),
            "-frames:v",
            "1",
            str(output),
        ],
        check=True,
    )
    return output


def _xai_chat_completion(
    *,
    api_key: str,
    model: str,
    prompt: str,
    image_path: Path,
    response_format: dict[str, Any] | None = None,
) -> str:
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{encoded}"},
                    },
                ],
            }
        ],
        "temperature": 0.2,
        "response_format": response_format or {"type": "json_object"},
    }
    request = urllib.request.Request(
        XAI_CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    data = urlopen_json_with_retry(request, timeout=120)
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise RuntimeError(f"xAI API response did not include choices: {data}")
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("xAI API response did not include text content")
    return content


def _grok_prompt_compiler_response_format() -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "soul_id_2x3_prompt": {"type": "string"},
            "single_panel_prompt": {"type": "string"},
            "kling_video_prompt": {"type": "string"},
            "kling_negative_prompt": {"type": "string"},
            "structured_breakdown": {
                "type": "object",
                "properties": {
                    "pose_lock": {"type": "string"},
                    "body_emphasis": {"type": "string"},
                    "outfit_variations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 6,
                    },
                    "motion_directives": {"type": "string"},
                    "key_constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 3,
                    },
                },
                "required": [
                    "pose_lock",
                    "body_emphasis",
                    "outfit_variations",
                    "motion_directives",
                    "key_constraints",
                ],
                "additionalProperties": False,
            },
            "notes": {"type": "string"},
            "confidence_score": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": [
            "soul_id_2x3_prompt",
            "single_panel_prompt",
            "kling_video_prompt",
            "kling_negative_prompt",
            "structured_breakdown",
            "confidence_score",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "grok_prompt_compiler_v1",
            "schema": schema,
            "strict": True,
        },
    }


def _grok_prompt_compiler_prompt(
    *,
    reference_id: str,
    image_prompt: dict[str, Any],
    video_prompt: dict[str, Any],
    instructions: str | None = None,
) -> str:
    good_example = {
        "soul_id_2x3_prompt": (
            "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring six variations of the exact same stunning woman with a perfect face "
            "and extreme hourglass figure as seen in the reference. She is posing seductively in a bright modern luxury "
            "living room with stone fireplace, in the exact same confident three-quarter mirror selfie pose: body angled to show her curves, "
            "one hand holding smartphone with pink nails up for the selfie, other hand behind her head, strong arched back, "
            "hips pushed out, looking back over her shoulder with a flirty expression. Strong sexual body emphasis in every panel: deep "
            "plunging cleavage with full pushed-up breasts straining tightly against the fabric, massive round plump juicy ass prominently "
            "displayed and emphasized by the arched pose, tiny cinched waist flaring into wide hips and thick thighs, skin-tight dress "
            "clinging desperately to every curve, visible glute definition and ass jiggle potential, dramatic S-curve posture. Outfit "
            "variations: 1. Bright turquoise blue strapless bodycon dress. 2. Pale icy blue strapless bodycon dress. 3. Crisp white "
            "strapless bodycon dress. 4. Off-white cream strapless bodycon dress. 5. Light grey strapless bodycon dress. 6. Slightly sheer "
            "white strapless bodycon dress. Soft natural daylight, photorealistic skin texture with natural sheen, realistic fabric stretch "
            "and cling, elegant luxury interior, consistent face, body, pose, and lighting across all six panels, no extra panels, vertical composition inside each panel, iPhone "
            "selfie aesthetic, high detail, sharp focus."
        ),
        "single_panel_prompt": (
            "Stunning voluptuous woman with extreme hourglass figure wearing a tight bright blue strapless bodycon "
            "maxi dress, taking a seductive mirror selfie in a luxury living room with stone fireplace. Exact reference pose: three-quarter "
            "view, strong arched back pushing out her massive round plump ass, hips cocked, one hand holding smartphone with pink nails, "
            "other hand behind head, looking back over shoulder with flirty confident expression. Intense body emphasis: deep plunging cleavage "
            "with full heavy breasts overflowing the top, tiny cinched waist, wide hips, thick juicy ass with pronounced round shape and "
            "glute definition, skin-tight fabric desperately hugging every curve. Soft natural daylight, photorealistic skin and fabric "
            "texture, realistic cling and stretch, vertical 9:16, iPhone quality, high detail."
        ),
        "kling_video_prompt": (
            "Stunning woman with extreme hourglass figure in a tight bright blue strapless bodycon maxi dress, "
            "taking a seductive mirror selfie. Start exactly from the reference image. Animate sensual, confident movement: slow rhythmic "
            "hip swaying and thrusting back to emphasize her massive round plump ass, visible glute movement under the tight fabric, strong "
            "arched back, natural bounce in her deep cleavage and full breasts, slow hand moving near her head, seductive head tilts and "
            "flirty expression changes. Realistic iPhone Reels vertical 9:16, subtle handheld camera sway, soft natural daylight, "
            "photorealistic skin and fabric movement. Duration: 5-6 seconds."
        ),
        "kling_negative_prompt": (
            "blurry, deformed, bad anatomy, flat chest, small breasts, flat ass, skinny body, loose clothing, baggy dress, different pose, "
            "outfit change within panel, low quality, text, watermark, cartoon, overexposed"
        ),
        "structured_breakdown": {
            "pose_lock": "three-quarter mirror selfie pose, phone raised with pink nails, other hand behind head, arched back, hips pushed out, looking back over shoulder",
            "body_emphasis": "deep cleavage, pushed-up full breasts, tiny cinched waist, wide hips, thick thighs, massive round plump ass, S-curve posture, skin-tight fabric cling",
            "outfit_variations": [
                "Bright turquoise blue strapless bodycon dress",
                "Pale icy blue strapless bodycon dress",
                "Crisp white strapless bodycon dress",
                "Off-white cream strapless bodycon dress",
                "Light grey strapless bodycon dress",
                "Slightly sheer white strapless bodycon dress",
            ],
            "motion_directives": "slow rhythmic hip sway, arched back, glute movement under tight fabric, natural breast bounce, hand near head, head tilts",
            "key_constraints": [
                "same pose",
                "same room lighting",
                "same phone selfie aesthetic",
                "one native 2x3 grid",
                "Kling animates one selected panel",
            ],
        },
        "confidence_score": 90,
        "notes": "Use the prose prompts directly; structured_breakdown is for validation and debugging.",
    }
    return (
        "You are the Grok Prompt Compiler for a premium short-form seductive content pipeline.\n\n"
        "Given a reference image, analyze it carefully and generate the highest quality prompts possible. "
        "Use the image as the source of truth. Optional structured analysis below is only supporting context and must not override what you see.\n\n"
        "Return ONLY a valid JSON object with this exact schema:\n"
        "{ soul_id_2x3_prompt, single_panel_prompt, kling_video_prompt, kling_negative_prompt, structured_breakdown, notes, confidence_score }\n\n"
        "Core Rules:\n"
        "- Stay very faithful to the reference pose, lighting, room, phone position, camera framing, and overall vibe.\n"
        "- Make it highly seductive: deep cleavage, pushed-up breasts, tiny cinched waist, wide hips, thick thighs, round plump juicy ass, S-curve posture, skin-tight fabric clinging to curves.\n"
        "- 2x3 prompt must be one native six-panel image: exactly three columns and two rows, no extra panels, with slight outfit variations in the same dress/outfit family.\n"
        "- Kling prompt must animate only the single best panel with sensual movement: hip sway, back arch, hand near head, fabric movement, natural bounce, subtle handheld phone motion.\n"
        "- Keep everything visually sexy and generation-friendly.\n"
        "- Clean, direct, high-signal prose. No meta language, no legacy junk, no JSON-as-prompt.\n"
        "- Do not mention app interfaces, screenshots, logos, platform UI, usernames, watermarks, or prompt-safety boilerplate in Soul ID prompts.\n"
        "- Do not mention hair, hair color, hairstyle, tattoos, or tattoo absence anywhere in the final prompts or structured_breakdown.\n"
        "- If the reference pose has a hand touching hair, describe it as hand near head or hand behind head.\n"
        "- Soul ID handles model identity; do not over-explain model selection.\n\n"
        "structured_breakdown rules:\n"
        "- pose_lock must describe the exact pose being preserved.\n"
        "- body_emphasis must summarize the body/curve language used.\n"
        "- outfit_variations must contain exactly 6 practical panel outfit descriptions for a 2x3 grid.\n"
        "- motion_directives must summarize the motion requested for Kling.\n"
        "- key_constraints must contain at least 3 must-keep elements.\n"
        "- confidence_score should be 0-100 based on prompt quality and reference clarity.\n\n"
        f"Extra user instructions: {instructions or 'Make it very sexy with strong ass and cleavage emphasis. Keep extremely close to the reference pose. Slightly more revealing variations.'}\n\n"
        "Example prompt style to imitate:\n"
        f"{json.dumps(good_example, indent=2, ensure_ascii=False)}\n\n"
        f"reference_id: {reference_id}\n"
        "optional_existing_structured_image_analysis:\n"
        f"{json.dumps(image_prompt, indent=2, ensure_ascii=False)}\n\n"
        "optional_existing_video_prompt_record:\n"
        f"{json.dumps(video_prompt, indent=2, ensure_ascii=False)}\n\n"
        "Return only valid JSON matching the requested schema."
    )


def _validate_compiled_prompt_set(compiled: dict[str, Any]) -> None:
    required = (
        "soul_id_2x3_prompt",
        "single_panel_prompt",
        "kling_video_prompt",
        "kling_negative_prompt",
    )
    missing = [
        key
        for key in required
        if not isinstance(compiled.get(key), str) or not compiled[key].strip()
    ]
    if missing:
        raise RuntimeError(
            f"Grok prompt compiler response missing required prompt fields: {', '.join(missing)}"
        )
    breakdown = compiled.get("structured_breakdown")
    if not isinstance(breakdown, dict):
        raise RuntimeError("Grok prompt compiler response missing structured_breakdown")
    breakdown_required = (
        "pose_lock",
        "body_emphasis",
        "outfit_variations",
        "motion_directives",
        "key_constraints",
    )
    breakdown_missing = [key for key in breakdown_required if not breakdown.get(key)]
    if breakdown_missing:
        raise RuntimeError(
            f"Grok prompt compiler structured_breakdown missing fields: {', '.join(breakdown_missing)}"
        )
    outfits = breakdown.get("outfit_variations")
    if (
        not isinstance(outfits, list)
        or len(outfits) != 6
        or not all(isinstance(item, str) and item.strip() for item in outfits)
    ):
        raise RuntimeError(
            "Grok prompt compiler structured_breakdown.outfit_variations must contain exactly 6 strings"
        )
    constraints = breakdown.get("key_constraints")
    if not isinstance(constraints, list) or len(constraints) < 3:
        raise RuntimeError(
            "Grok prompt compiler structured_breakdown.key_constraints must contain at least 3 items"
        )
    confidence = compiled.get("confidence_score")
    if not isinstance(confidence, int) or confidence < 70:
        raise RuntimeError(
            "Grok prompt compiler confidence_score must be an integer >= 70 before generation"
        )
    forbidden = ("platform ui", "screenshot", "username", "watermark", "tattoo", "hair")
    soul_text = (
        f"{compiled['soul_id_2x3_prompt']} "
        f"{compiled['single_panel_prompt']} "
        f"{compiled['kling_video_prompt']} "
        f"{json.dumps(compiled.get('structured_breakdown') or {}, ensure_ascii=False)}"
    ).lower()
    leaked = [term for term in forbidden if term in soul_text]
    if leaked:
        raise RuntimeError(
            f"Grok prompt compiler produced forbidden Soul prompt terms: {', '.join(leaked)}"
        )


def _normalize_compiled_prompt_set(compiled: dict[str, Any]) -> dict[str, Any]:
    """Post-process Grok output without changing creative intent."""
    prompt = compiled.get("soul_id_2x3_prompt")
    if isinstance(prompt, str):
        prompt = prompt.replace(
            "Create one high-quality 2x3 grid featuring",
            "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring",
        )
        prompt = prompt.replace(
            "Create one high-quality 2x3 grid image featuring",
            "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring",
        )
        if "exactly three columns and two rows" not in prompt:
            prompt = (
                "Create one high-quality six-panel grid image, exactly three columns and two rows, no extra panels. "
                + prompt
            )
        if "no extra panels" not in prompt.lower():
            prompt += " No extra panels."
        compiled["soul_id_2x3_prompt"] = prompt
    return compiled


def _grok_prompt_builder(job: dict[str, Any], *, prompt_style: str = "imageat") -> str:
    file_name = str(job.get("fileName") or job.get("file_name") or "")
    reference_id = str(job.get("referenceId") or job.get("reference_id") or "")
    example = {
        "schema": ANALYSIS_SCHEMA,
        "referenceId": reference_id or "example_reference.mp4",
        "summary": "A mirror selfie video of a woman posing in a bright minimalist bedroom.",
        "contentFormat": "mirror_selfie",
        "image_prompt_json": {
            "promptMode": "structured_json",
            "subject": "Stunning young woman with an alluring, seductive figure taking a confident mirror selfie in a bright minimalist bedroom.",
            "composition": {
                "shot_type": "Full-body mirror selfie",
                "angle": "Side profile with slight twist toward the mirror, emphasizing curves",
                "pose": "Standing with arched back and pushed-out hips to accentuate her round butt and hourglass silhouette. Right hand holding white iPhone up covering most of her face, left arm slightly extended behind her. Seductive and teasing body language.",
            },
            "hair": {
                "style": "Long, voluminous, wild tight curls",
                "color": "Rich honey brown with golden highlights",
                "texture": "Thick, bouncy coiled ringlets cascading down her back and over one shoulder, with natural movement and volume.",
            },
            "clothing": {
                "item": "Extremely short, sheer strapless mini dress",
                "pattern": "Leopard print with brown and black rosettes on semi-transparent fabric",
                "fit": "Skin-tight, bodycon, stretchy sheer material that clings to every curve, barely covering her ass, with visible skin tone underneath. Deep plunging back and sides, strapless neckline pushing up her cleavage.",
            },
            "body": {
                "build": "Slim-thick, toned yet curvaceous figure with pronounced hips, round perky butt, and long smooth legs",
                "pose_details": "Weight shifted to one leg, creating a strong S-curve posture that highlights her waist-to-hip ratio and buttocks.",
            },
            "skin": {
                "tone": "Fair with warm golden undertones",
                "texture": "Smooth, soft, and glowing with natural sheen. Subtle muscle definition on legs and arms.",
            },
            "expression_mood": {
                "vibe": "Playful yet highly seductive and confident",
                "details": "Teasing body language, sensual posture designed to highlight her sexuality and feminine curves.",
            },
            "environment": {
                "setting": "Bright, clean minimalist bedroom",
                "details": [
                    "White tufted headboard bed with messy striped sheets",
                    "Fluffy white shag rug",
                    "White vintage-style radiator",
                    "Plain white walls with subtle texture",
                    "Black vertical mirror frame visible on the right",
                ],
            },
            "lighting_and_camera": {
                "lighting": "Soft, bright natural daylight from the side creating gentle highlights on her skin, legs, and curves with subtle shadows that accentuate her body shape.",
                "camera_feel": "Casual smartphone mirror selfie aesthetic, vertical composition, realistic phone photography style with slight grain.",
            },
            "constraints": {
                "must_keep": [
                    "Leopard print sheer strapless mini dress",
                    "Long voluminous curly hair",
                    "Mirror selfie pose with white iPhone covering face",
                    "Side profile body emphasis",
                    "Minimalist white bedroom setting",
                ],
                "avoid": [
                    "Visible face",
                    "Loose clothing",
                    "Professional studio lighting",
                    "Heavy makeup",
                    "Cluttered background",
                    "Conservative pose",
                ],
            },
            "negative_prompt": "blurry, low quality, deformed body, bad anatomy, extra limbs, face visible, modest clothing, baggy dress, dark lighting, professional photoshoot, text, watermark, oversaturated, cartoonish.",
        },
        "higgsfield_soul_image_prompt": "Use this structured JSON creative brief exactly as the image prompt.",
        "higgsfield_negative_prompt": "Use image_prompt_json.negative_prompt.",
        "kling_3_video_prompt": "Use the generated image as the first frame. Create a realistic 5-second iPhone mirror selfie video. Keep the same pose, outfit, mirror angle, room lighting, and phone position. Add only subtle body movement, relaxed breathing, tiny phone sway, and a small pose adjustment. 9:16, no audio.",
        "kling_negative_prompt": "warped phone, extra limbs, distorted face, glitchy motion, changing outfit, changing room, cinematic camera move",
        "motion_notes": "Subtle pose-check motion, tiny phone sway, relaxed breathing, small hip/shoulder adjustment.",
        "camera_notes": "Vertical phone mirror selfie, mostly steady, same camera distance and angle.",
        "style_notes": "Casual bedroom mirror selfie, flirty fitted outfit, realistic phone-photo texture.",
        "copy_risk_notes": "Do not copy username, watermark, exact overlay text, or the source person's identity.",
        "what_to_change": "Replace the person with the selected model identity while preserving the winning pose, fit, camera, room, and movement format.",
    }
    return (
        "Analyze the provided reference image/frame and output ONLY valid JSON.\n"
        "Use the example JSON structure and style below. Match its level of detail and its field names.\n"
        "The output must be practical for Higgsfield Soul ID image generation and Kling 3.0 image-to-video.\n\n"
        "Important output rules:\n"
        "- Write an ImageAt-style `image_prompt_json` with strong composition, clothing fit, body pose, environment, lighting, and camera details.\n"
        "- Keep the image prompt spicy, flirty, fitted, and close to the source format while staying non-explicit.\n"
        "- Do not add generic safety boilerplate.\n"
        "- Do not flatten the image JSON into a weak paragraph.\n"
        "- The Kling prompt should describe motion only: body movement, phone/camera movement, pacing, duration, and what stays consistent.\n"
        "- Do not copy usernames, watermarks, exact overlay text, or the source person's identity.\n"
        f"- referenceId must be `{reference_id}`.\n"
        f"- Source file name: `{file_name}`.\n\n"
        "Example format to imitate:\n"
        f"{json.dumps(example, indent=2, ensure_ascii=False)}\n\n"
        "Now output the same JSON shape for the provided reference frame."
    )
