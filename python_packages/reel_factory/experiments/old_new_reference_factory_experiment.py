#!/usr/bin/env python3
"""Run an old Reference Factory vs current Reel Factory prompt comparison.

This is an experiment runner only. It calls Grok twice per reference image:

- OLD: near-verbatim Reference Factory prompt compiler voice.
- NEW: current Reel Factory direct Higgsfield prompt compiler voice.

Both conditions produce one Higgsfield image-only Soul grid with the same
settings. No Kling jobs are started.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from asset_prompt_contract import AssetPromptSet
from generate_assets import IMAGE_MODEL, VIDEO_MODEL
from generate_prompts import (
    DEFAULT_MODEL,
    build_direct_higgsfield_prompt_instruction,
    build_xai_payload,
    call_grok,
    clean_direct_higgsfield_prompt_text,
    load_xai_api_key,
    parse_direct_higgsfield_prompt_response,
    response_text,
)
from grok_ab_experiment import (
    DEFAULT_KLING_MOTION_PROMPT,
    _create_image_grid,
    _plain_grok_text,
)


SCHEMA = "reel_factory.old_new_reference_factory_experiment.v1"


def _read_reference_factory_example() -> dict[str, Any]:
    return {
        "soul_id_2x3_prompt": (
            "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring six variations "
            "of the exact same stunning woman with a perfect face and extreme hourglass figure as seen in the reference. "
            "She is posing seductively in a bright modern luxury living room with stone fireplace, in the exact same "
            "confident three-quarter mirror selfie pose: body angled to show her curves, one hand holding smartphone with "
            "pink nails up for the selfie, other hand behind her head, strong arched back, hips pushed out, looking back "
            "over her shoulder with a flirty expression. Strong sexual body emphasis in every panel: deep plunging "
            "cleavage with full pushed-up breasts straining tightly against the fabric, massive round plump juicy ass "
            "prominently displayed and emphasized by the arched pose, tiny cinched waist flaring into wide hips and thick "
            "thighs, skin-tight dress clinging desperately to every curve, visible glute definition and ass jiggle "
            "potential, dramatic S-curve posture. Outfit variations: 1. Bright turquoise blue strapless bodycon dress. "
            "2. Pale icy blue strapless bodycon dress. 3. Crisp white strapless bodycon dress. 4. Off-white cream "
            "strapless bodycon dress. 5. Light grey strapless bodycon dress. 6. Slightly sheer white strapless bodycon "
            "dress. Soft natural daylight, photorealistic skin texture with natural sheen, realistic fabric stretch and "
            "cling, elegant luxury interior, consistent face, body, pose, and lighting across all six panels, no extra "
            "panels, vertical composition inside each panel, iPhone selfie aesthetic, high detail, sharp focus."
        ),
        "single_panel_prompt": (
            "Stunning voluptuous woman with extreme hourglass figure wearing a tight bright blue strapless bodycon maxi "
            "dress, taking a seductive mirror selfie in a luxury living room with stone fireplace. Exact reference pose: "
            "three-quarter view, strong arched back pushing out her massive round plump ass, hips cocked, one hand holding "
            "smartphone with pink nails, other hand behind head, looking back over shoulder with flirty confident "
            "expression. Intense body emphasis: deep plunging cleavage with full heavy breasts overflowing the top, tiny "
            "cinched waist, wide hips, thick juicy ass with pronounced round shape and glute definition, skin-tight fabric "
            "desperately hugging every curve. Soft natural daylight, photorealistic skin and fabric texture, realistic "
            "cling and stretch, vertical 9:16, iPhone quality, high detail."
        ),
        "kling_video_prompt": (
            "Stunning woman with extreme hourglass figure in a tight bright blue strapless bodycon maxi dress, taking a "
            "seductive mirror selfie. Start exactly from the reference image. Animate sensual, confident movement: slow "
            "rhythmic hip swaying and thrusting back to emphasize her massive round plump ass, visible glute movement "
            "under the tight fabric, strong arched back, natural bounce in her deep cleavage and full breasts, slow hand "
            "moving near her head, seductive head tilts and flirty expression changes. Realistic iPhone Reels vertical "
            "9:16, subtle handheld camera sway, soft natural daylight, photorealistic skin and fabric movement. Duration: "
            "5-6 seconds."
        ),
        "kling_negative_prompt": (
            "blurry, deformed, bad anatomy, flat chest, small breasts, flat ass, skinny body, loose clothing, baggy dress, "
            "different pose, outfit change within panel, low quality, text, watermark, cartoon, overexposed"
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


def build_old_reference_factory_instruction(reference_id: str, examples_text: str = "") -> str:
    good_example = _read_reference_factory_example()
    examples_block = f"\n\nAdditional favorite prompt examples from the user:\n{examples_text.strip()}\n" if examples_text.strip() else ""
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
        "- Soul ID handles model identity; do not over-explain model selection.\n"
        "- If an age phrase is useful, use adult wording such as at least 20 years old.\n\n"
        "structured_breakdown rules:\n"
        "- pose_lock must describe the exact pose being preserved.\n"
        "- body_emphasis must summarize the body/curve language used.\n"
        "- outfit_variations must contain exactly 6 practical panel outfit descriptions for a 2x3 grid.\n"
        "- motion_directives must summarize the motion requested for Kling.\n"
        "- key_constraints must contain at least 3 must-keep elements.\n"
        "- confidence_score should be 0-100 based on prompt quality and reference clarity.\n\n"
        "Extra user instructions: Make it very sexy with strong ass and cleavage emphasis. Keep extremely close to the reference pose. Slightly more revealing variations. Use adult age wording when useful.\n\n"
        "Example prompt style to imitate:\n"
        f"{json.dumps(good_example, indent=2, ensure_ascii=False)}"
        f"{examples_block}\n\n"
        f"reference_id: {reference_id}\n"
        "optional_existing_structured_image_analysis:\n{}\n\n"
        "optional_existing_video_prompt_record:\n{}\n\n"
        "Return only valid JSON matching the requested schema."
    )


def _prompt_from_old_response(raw_text: str) -> str:
    text = _plain_grok_text({"output": [{"content": [{"type": "output_text", "text": raw_text}]}]})
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    return str(data.get("soul_id_2x3_prompt") or data.get("higgsfieldGridPrompt") or data.get("prompt") or "").strip()


def _prompt_from_new_response(raw_text: str) -> str:
    parsed = parse_direct_higgsfield_prompt_response(
        raw_text,
        shared_motion_prompt=DEFAULT_KLING_MOTION_PROMPT,
    )
    return parsed.higgsfieldGridPrompt


def clean_old_reference_factory_prompt_text(prompt: str) -> dict[str, Any]:
    """Preserve old Reference Factory wording, removing only hair/tattoo leaks."""
    removed: list[str] = []

    patterns = [
        r"(?i)\b(?:long|short|medium-length|voluminous|wavy|curly|straight|braided|blonde|brunette|brown|black|red|auburn|dark|light|silky|flowing|styled|middle-parted|center-parted|loose|natural|bright|copper|ginger)(?:[\s-]+\w+){0,4}\s+hair\b",
        r"(?i)(?:^|[,;]\s*)[^,;.!?]*\btattoos?\b[^,;.!?]*",
        r"(?i)\b(?:hand|hands|fingers)\s+(?:resting|touching|brushing|running|pulling|playing)?\s*(?:in|through|over|near)\s+(?:her\s+|his\s+|their\s+)?(?:\w+\s+){0,4}hair\b",
        r"(?i)\b(?:hand|hands|fingers)?\s*(?:resting|touching|brushing|running|pulling|playing)\s+(?:in|through|over|near)\s+(?:her\s+|his\s+|their\s+)?(?:\w+\s+){0,4}hair\b",
        r"(?i)(?:^|[,;]\s*)[^,;.!?]*\bhair\b[^,;.!?]*",
    ]
    cleaned = prompt.strip()
    for pattern_text in patterns:
        import re

        pattern = re.compile(pattern_text)

        def repl(match: re.Match[str]) -> str:
            removed.append(match.group(0).strip(" ,;"))
            return " "

        cleaned = pattern.sub(repl, cleaned)
    import re

    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,;.!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,;])\s*([,;.!?])", r"\2", cleaned)
    cleaned = cleaned.strip(" ,;")
    return {
        "raw": prompt.strip(),
        "cleaned": cleaned,
        "removed": removed,
        "residualForbiddenTerms": [],
        "valid": True,
        "changed": prompt.strip() != cleaned,
        "policy": "old_reference_factory_cleanup_only_hair_tattoo",
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _condition_contract(prompt: str, notes: str) -> dict[str, str]:
    return asdict(AssetPromptSet(
        higgsfieldGridPrompt=prompt,
        klingMotionPrompt=DEFAULT_KLING_MOTION_PROMPT,
        notes=notes,
    ))


def _run_condition(
    *,
    root: Path,
    out_dir: Path,
    image_out_root: Path,
    stem: str,
    condition: str,
    reference_image: Path,
    instruction: str,
    parser: str,
    api_key: str,
    model: str,
    image_model: str,
    image_aspect_ratio: str,
    image_quality: str,
    soul_id: str | None,
    soul_name: str | None,
    run_images: bool,
    wait: bool,
    download: bool,
) -> dict[str, Any]:
    payload = build_xai_payload(model=model, frames=[reference_image], instruction=instruction)
    raw_response = call_grok(payload, api_key=api_key)
    raw_text = response_text(raw_response).strip()
    if parser == "old":
        raw_prompt = _prompt_from_old_response(raw_text)
        cleanup = clean_old_reference_factory_prompt_text(raw_prompt)
        cleaned_prompt = cleanup["cleaned"]
    else:
        raw_prompt = _prompt_from_new_response(raw_text)
        cleaned_prompt = clean_direct_higgsfield_prompt_text(raw_prompt)
        cleanup = {
            "raw": raw_prompt,
            "cleaned": cleaned_prompt,
            "removed": [],
            "residualForbiddenTerms": [],
            "valid": True,
            "changed": raw_prompt != cleaned_prompt,
        }
    contract = _condition_contract(
        cleaned_prompt,
        f"{condition} old-vs-new Reference Factory prompt experiment; image-only.",
    )

    prefix = f"{stem}_{condition}"
    instruction_path = out_dir / f"{prefix}_instruction.txt"
    raw_response_path = out_dir / f"{prefix}_grok_raw.json"
    raw_prompt_path = out_dir / f"{prefix}_raw_prompt.txt"
    cleaned_prompt_path = out_dir / f"{prefix}_cleaned_prompt.txt"
    cleanup_path = out_dir / f"{prefix}_cleanup_diff.json"
    prompt_json_path = out_dir / f"{prefix}_prompt.json"
    _write_text(instruction_path, instruction)
    _write_json(raw_response_path, raw_response)
    _write_text(raw_prompt_path, raw_prompt)
    _write_text(cleaned_prompt_path, cleaned_prompt)
    _write_json(cleanup_path, cleanup)
    _write_json(prompt_json_path, contract)

    generation: dict[str, Any] = {
        "status": "not_run",
        "referencePassedToHiggsfield": None,
        "promptEnhancement": False,
        "imageAspectRatio": image_aspect_ratio,
        "imageQuality": image_quality,
    }
    if run_images:
        generation = _create_image_grid(
            root=root,
            prompt_contract=contract,
            stem=prefix,
            out_dir=image_out_root,
            soul_id=soul_id,
            soul_name=soul_name,
            image_model=image_model,
            image_aspect_ratio=image_aspect_ratio,
            image_quality=image_quality,
            wait=wait,
            download=download,
        )
        generation["referencePassedToHiggsfield"] = None
        generation["promptEnhancement"] = False

    return {
        "label": "Old Reference Factory compiler" if condition == "old" else "Current cleaned Reel Factory compiler",
        "instructionPath": str(instruction_path),
        "rawResponsePath": str(raw_response_path),
        "rawPromptPath": str(raw_prompt_path),
        "cleanedPromptPath": str(cleaned_prompt_path),
        "cleanupDiffPath": str(cleanup_path),
        "promptJsonPath": str(prompt_json_path),
        "cleanup": cleanup,
        "generation": generation,
    }


def run_experiment(
    *,
    root: Path,
    references: list[Path],
    examples_file: Path | None,
    out_dir: Path | None,
    model: str,
    image_model: str,
    image_aspect_ratio: str,
    image_quality: str,
    soul_id: str | None,
    soul_name: str | None,
    run_images: bool,
    wait: bool,
    download: bool,
) -> dict[str, Any]:
    root = root.resolve()
    out_root = (out_dir.expanduser().resolve() if out_dir else root / "prompts" / "experiments" / "old_new_reference_factory")
    examples_text = examples_file.expanduser().read_text(encoding="utf-8") if examples_file else ""
    api_key = load_xai_api_key(root)
    if not api_key:
        raise RuntimeError("XAI API key is required")
    if run_images and not (soul_id or soul_name):
        raise ValueError("soul_id or soul_name is required when run_images=True")

    runs: list[dict[str, Any]] = []
    created_at = int(time.time())
    for reference in references:
        reference = reference.expanduser().resolve()
        if not reference.exists():
            raise FileNotFoundError(reference)
        stem = f"{reference.parent.name}_{reference.stem}_{created_at}"
        image_out_root = root / "project_data" / "generated_assets" / "old_new_reference_factory" / stem
        old_instruction = build_old_reference_factory_instruction(reference.stem, examples_text)
        new_instruction = build_direct_higgsfield_prompt_instruction(
            "Make it very sexy with strong ass and cleavage emphasis. Keep extremely close to the reference pose. "
            "Use adult age wording such as at least 20 years old when useful. Use clearly distinct outfit colors or materials."
        )
        conditions = {
            "old": _run_condition(
                root=root,
                out_dir=out_root,
                image_out_root=image_out_root,
                stem=stem,
                condition="old",
                reference_image=reference,
                instruction=old_instruction,
                parser="old",
                api_key=api_key,
                model=model,
                image_model=image_model,
                image_aspect_ratio=image_aspect_ratio,
                image_quality=image_quality,
                soul_id=soul_id,
                soul_name=soul_name,
                run_images=run_images,
                wait=wait,
                download=download,
            ),
            "new": _run_condition(
                root=root,
                out_dir=out_root,
                image_out_root=image_out_root,
                stem=stem,
                condition="new",
                reference_image=reference,
                instruction=new_instruction,
                parser="new",
                api_key=api_key,
                model=model,
                image_model=image_model,
                image_aspect_ratio=image_aspect_ratio,
                image_quality=image_quality,
                soul_id=soul_id,
                soul_name=soul_name,
                run_images=run_images,
                wait=wait,
                download=download,
            ),
        }
        runs.append({
            "stem": stem,
            "referenceImage": str(reference),
            "conditions": conditions,
        })

    summary = {
        "schema": SCHEMA,
        "experimental": True,
        "createdAt": created_at,
        "model": model,
        "imageModel": image_model,
        "imageAspectRatio": image_aspect_ratio,
        "imageQuality": image_quality,
        "imageReferencePolicy": "analysis_only_do_not_send_to_higgsfield",
        "promptEnhancement": False,
        "kling": "not part of this experiment",
        "runs": runs,
    }
    summary_path = out_root / f"old_new_reference_factory_{created_at}_summary.json"
    _write_json(summary_path, summary)
    return {"ok": True, "summaryPath": str(summary_path), **summary}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--reference-image", type=Path, action="append", required=True)
    ap.add_argument("--examples-file", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--image-model", default=IMAGE_MODEL)
    ap.add_argument("--image-aspect-ratio", default="16:9")
    ap.add_argument("--image-quality", default="2k")
    ap.add_argument("--soul-id")
    ap.add_argument("--soul-name")
    ap.add_argument("--run-images", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    result = run_experiment(
        root=args.root,
        references=args.reference_image,
        examples_file=args.examples_file,
        out_dir=args.out_dir,
        model=args.model,
        image_model=args.image_model,
        image_aspect_ratio=args.image_aspect_ratio,
        image_quality=args.image_quality,
        soul_id=args.soul_id,
        soul_name=args.soul_name,
        run_images=args.run_images,
        wait=not args.no_wait,
        download=not args.no_download,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
