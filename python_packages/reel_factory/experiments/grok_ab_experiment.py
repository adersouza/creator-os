#!/usr/bin/env python3
"""Experimental few-shot Grok prompt A/B path.

This module deliberately bypasses the production prompt compiler. It tests two
plain-language Grok instructions against the same reference image and examples:

- A: explicit attention/body-emphasis instruction.
- B: example-led instruction with softer steering.

Grok returns final Higgsfield prompt text only. The experiment records exactly
what was sent, exactly what Grok returned, the minimal cleanup diff, and
optionally creates two image-only Soul grid jobs with matching settings.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from asset_prompt_contract import AssetPromptSet
from generate_assets import (
    IMAGE_MODEL,
    VIDEO_MODEL,
    build_image_cmd,
    download_result,
    ensure_required_capabilities,
    extract_id,
    extract_url,
    image_identity_flag,
    resolve_generation_models,
)
from generate_prompts import DEFAULT_MODEL, build_xai_payload, call_grok, load_xai_api_key, response_text


SCHEMA = "reel_factory.grok_few_shot_ab_experiment.v1"
DEFAULT_AB_IMAGE_ASPECT_RATIO = "4:3"
DEFAULT_KLING_MOTION_PROMPT = "Shared motion prompt intentionally not used in this image-only A/B test."


def build_explicit_emphasis_instruction(examples_text: str) -> str:
    return f"""Look at the reference image.

Here are examples of Higgsfield prompts I liked:

{examples_text.strip()}

Write a new Higgsfield prompt in the same style as those examples that recreates the reference image.

For this experiment, write the prompt as one high-quality native 2x3 grid/contact sheet with six slight outfit variations.

If the image supports it, make the result sexier and more attention-grabbing by emphasizing things like large cleavage, curves, a nice round ass, body-hugging clothing, flattering pose mechanics, and a body shape that makes viewers stop and look.

If appropriate, create six slight outfit variations.

Return only the final Higgsfield prompt.
"""


def build_example_led_instruction(examples_text: str) -> str:
    return f"""Look at the reference image.

Here are examples of Higgsfield prompts I liked:

{examples_text.strip()}

Write a new Higgsfield prompt in the same style as those examples that recreates the reference image.

For this experiment, write the prompt as one high-quality six-panel grid image, exactly three columns and two rows, with six slight outfit variations.

The examples are more important than the instructions. Learn the writing style, level of detail, scene description style, pose description style, environment detail, framing detail, clothing detail, and overall visual direction from the examples.

Use this older Reference Factory compiler voice, but return only the final Higgsfield prompt text:
- "Create one high-quality six-panel grid image, exactly three columns and two rows..."
- Use the image as the source of truth.
- Stay very faithful to the reference pose, lighting, room, phone position, camera framing, and overall vibe.
- Start with the scene/capture: real room, mirror/selfie/phone/camera behavior, lighting, framing, visible furniture or background anchors.
- Then lock the exact pose: body angle, arm/hand placement, torso angle, hip/waist posture, expression, crop, and eye-line when visible.
- Then describe concrete body and garment mechanics: deep cleavage, pushed-up breasts, tiny cinched waist, wide hips, thick thighs, round ass, S-curve posture, skin-tight fabric clinging to curves, fabric stretch and fit when supported by the reference.
- Include six practical outfit/color/fabric variations in the same outfit family.
- End by locking the same room, same camera angle, same framing, same lighting, same pose geometry, and same body proportions across all six panels.
- Keep the prose clean, direct, high-signal, and generation-friendly.

If the image naturally supports it, make the result more visually compelling and attention-grabbing in the same way the example prompts do.

If appropriate, create six slight outfit variations while preserving the overall visual formula of the reference.

Do not spend prompt budget describing face quality, perfect face, eye color, freckles, exact age, ethnicity, skin texture, skin sheen, natural sheen, high detail, or sharp focus. Soul ID handles identity and face realism.

Return only the final Higgsfield prompt.

Do not return:
- analysis
- metadata
- JSON
- scene breakdowns
- extraction results
- attribute reports

Return only the final Higgsfield prompt text.
"""


def build_variant_instruction(variant: str, examples_text: str) -> str:
    key = variant.upper()
    if key == "A":
        return build_explicit_emphasis_instruction(examples_text)
    if key == "B":
        return build_example_led_instruction(examples_text)
    raise ValueError(f"unsupported A/B variant: {variant!r}")


def _plain_grok_text(raw_response: dict[str, Any]) -> str:
    text = response_text(raw_response).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:text|json|markdown)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        for key in ("prompt", "higgsfieldGridPrompt"):
            value = str(data.get(key) or "").strip() if isinstance(data, dict) else ""
            if value:
                return value
    return text


_FORBIDDEN_CLEANUP_RE = re.compile(
    r"(?i)\b(?:tattoos?|hair(?:style|\s+color)?|hairstyle|hair\s+color|[a-z]+-haired|"
    r"redhead|blue eyes?|green eyes?|brown eyes?|hazel eyes?|freckles?|freckled|"
    r"perfect face|skin texture|skin sheen|natural sheen|sharp focus|high detail)\b"
)
_REDHEAD_DESCRIPTOR_RE = re.compile(r"(?i)\bredhead\s+")
_HAIRED_DESCRIPTOR_RE = re.compile(r"(?i)\b(?:red|blonde|brown|black|dark|light|auburn|brunette|copper|ginger)-haired\s+")
_EYE_DESCRIPTOR_RE = re.compile(
    r"(?i)\b(?:(?:bright|piercing|striking|soft|almond-shaped|round)\s+)*"
    r"(?:blue|green|brown|hazel|gray|grey)\s+eyes?\b"
)
_FRECKLE_DESCRIPTOR_RE = re.compile(r"(?i)(?:^|[,;]\s*)[^,;.!?]*\b(?:freckles?|freckled)\b[^,;.!?]*")
_FACE_POLISH_RE = re.compile(r"(?i)(?:^|[,;]\s*)[^,;.!?]*\bperfect face\b[^,;.!?]*")
_FACE_CONSISTENCY_RE = re.compile(r"(?i)\bconsistent\s+face\s+and\s+")
_FACE_LIST_ITEM_RE = re.compile(r"(?i)(,\s*)face\s*,?\s*(and\s+)?")
_FACE_CONSISTENCY_TAIL_RE = re.compile(r"(?i)\s+and\s+face(?=\s+across|\s*,|\s+and|\.)")
_SKIN_POLISH_RE = re.compile(
    r"(?i)(?:^|[,;]\s*)[^,;.!?]*\b(?:photorealistic\s+)?skin texture\b[^,;.!?]*"
)
_QUALITY_POLISH_RE = re.compile(r"(?i)(?:^|[,;]\s*)\s*(?:high detail|sharp focus)\s*")
_WITH_HAIR_PHRASE_RE = re.compile(
    r"(?i)(?<=with\s)(?:long|short|medium-length|voluminous|wavy|curly|straight|"
    r"braided|blonde|brunette|brown|black|red|auburn|dark|light|silky|flowing|"
    r"styled|middle-parted|center-parted|loose|natural|vibrant|copper|copper-red|"
    r"bright|,|\s|-)+\bhair\b\s*(?:,|and)?\s*"
)
_HAIR_ACTION_RE = re.compile(
    r"(?i)\s*(?:with\s+)?(?:hand|hands|fingers)?\s*"
    r"(?:running|run|brushing|brush|touching|touch|holding|hold|gripping|grip|"
    r"combing|comb|threading|thread|pulling|pull|playing|resting|rest)\s+"
    r"(?:(?:in|through|over|near)\s+)?(?:her\s+|his\s+|their\s+)?(?:\w+\s+){0,4}hair\b"
)
_HAND_IN_HAIR_RE = re.compile(
    r"(?i)\s*(?:with\s+)?(?:hand|hands|fingers)\s+"
    r"(?:in|through|over|near)\s+(?:her\s+|his\s+|their\s+)?(?:\w+\s+){0,4}hair\b"
)
_HAIR_PREP_RE = re.compile(r"(?i)\s+(?:in|through|near)\s+(?:her\s+|his\s+|their\s+)?hair\b")
_HAIR_LEADING_CLAUSE_RE = re.compile(
    r"(?i)(?:^|[,;]\s*)(?:long|short|medium-length|voluminous|wavy|curly|straight|"
    r"braided|blonde|brunette|brown|black|red|auburn|dark|light|silky|flowing|"
    r"styled|middle-parted|center-parted|loose|natural)[^,;.!?]*\bhair\b[^,;.!?]*"
)
_TATTOO_CLAUSE_RE = re.compile(r"(?i)(?:^|[,;]\s*)[^,;.!?]*\btattoos?\b[^,;.!?]*")
_RESIDUAL_HAIR_CLAUSE_RE = re.compile(r"(?i)(?:^|[,;]\s*)[^,;.!?]*\bhair\b[^,;.!?]*")


def _remove_forbidden_clauses(text: str) -> tuple[str, list[str]]:
    """Remove only hair/tattoo references while preserving surrounding prompt text."""
    removed: list[str] = []

    def remove_matches(pattern: re.Pattern[str], value: str) -> str:
        def repl(match: re.Match[str]) -> str:
            removed.append(match.group(0).strip(" ,;"))
            return " "
        return pattern.sub(repl, value)

    cleaned = text
    cleaned = remove_matches(_REDHEAD_DESCRIPTOR_RE, cleaned)
    cleaned = remove_matches(_HAIRED_DESCRIPTOR_RE, cleaned)
    cleaned = remove_matches(_EYE_DESCRIPTOR_RE, cleaned)
    cleaned = remove_matches(_FRECKLE_DESCRIPTOR_RE, cleaned)
    cleaned = remove_matches(_FACE_POLISH_RE, cleaned)
    cleaned = _FACE_CONSISTENCY_RE.sub("consistent ", cleaned)
    cleaned = _FACE_LIST_ITEM_RE.sub(lambda m: m.group(1) + (m.group(2) or ""), cleaned)
    cleaned = _FACE_CONSISTENCY_TAIL_RE.sub("", cleaned)
    cleaned = remove_matches(_SKIN_POLISH_RE, cleaned)
    cleaned = remove_matches(_QUALITY_POLISH_RE, cleaned)
    cleaned = remove_matches(_WITH_HAIR_PHRASE_RE, cleaned)
    cleaned = remove_matches(_HAIR_ACTION_RE, cleaned)
    cleaned = remove_matches(_HAND_IN_HAIR_RE, cleaned)
    cleaned = remove_matches(_HAIR_PREP_RE, cleaned)
    cleaned = remove_matches(_HAIR_LEADING_CLAUSE_RE, cleaned)
    cleaned = remove_matches(_TATTOO_CLAUSE_RE, cleaned)

    # Final fallback for any remaining compact hair phrase. This is intentionally
    # narrow so non-hair prompt mechanics stay intact.
    cleaned = re.sub(
        r"(?i)\b(?:long|short|medium-length|voluminous|wavy|curly|straight|braided|"
        r"blonde|brunette|brown|black|red|auburn|dark|light|silky|flowing|styled|"
        r"middle-parted|center-parted|loose|natural)\s+(?:\w+\s+){0,4}hair\b",
        lambda m: removed.append(m.group(0).strip()) or " ",
        cleaned,
    )
    cleaned = remove_matches(_RESIDUAL_HAIR_CLAUSE_RE, cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"(?i)\bwith\s+(seated|standing|posing|taking|wearing)\b", r"\1", cleaned)
    cleaned = re.sub(r"(?i)\b(with|has|have)\s*,\s*and\s+", r"\1 ", cleaned)
    cleaned = re.sub(r"(?i)\bwith\s+and\s+", "with ", cleaned)
    cleaned = re.sub(r"(?i)\b(right|left)\s*,\s*((?:right|left)\s+arm\b)", r"\1 arm raised, \2", cleaned)
    cleaned = re.sub(r"(?i)\b(has|have)\s*,\s*", r"\1 ", cleaned)
    cleaned = re.sub(r"(?i)\b(has|have)\s+and\s+", r"\1 ", cleaned)
    cleaned = re.sub(r"\s+([,;.!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,;])\s*([,;.!?])", r"\2", cleaned)
    cleaned = re.sub(r"(?i)\b(with|has|have)\s*,\s*and\s+", r"\1 ", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = cleaned.strip(" ,;")
    return cleaned, removed


def clean_grok_prompt(raw_prompt: str) -> dict[str, Any]:
    cleaned, removed = _remove_forbidden_clauses(raw_prompt.strip())
    residual = sorted(set(m.group(0) for m in _FORBIDDEN_CLEANUP_RE.finditer(cleaned)))
    return {
        "raw": raw_prompt.strip(),
        "cleaned": cleaned,
        "removed": removed,
        "residualForbiddenTerms": residual,
        "valid": not residual,
        "changed": raw_prompt.strip() != cleaned,
    }


def prompt_contract_from_cleaned(cleaned_prompt: str,
                                 motion_prompt: str = DEFAULT_KLING_MOTION_PROMPT) -> dict[str, str]:
    prompt_set = AssetPromptSet(
        higgsfieldGridPrompt=cleaned_prompt.strip(),
        klingMotionPrompt=motion_prompt,
        notes="Experimental few-shot Grok A/B prompt; no compiler, no retry, minimal hair/tattoo cleanup only.",
    )
    return asdict(prompt_set)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _run_json(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:] or proc.stdout[-2000:] or f"command failed: {' '.join(cmd)}")
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command returned non-JSON output: {' '.join(cmd)}") from exc


def _resolve_soul_id(root: Path, *, soul_id: str | None, soul_name: str | None) -> str | None:
    if soul_id:
        return soul_id
    if not soul_name:
        return None
    try:
        from campaign_store import connect, creator_by_name

        conn = connect(root)
        return str(creator_by_name(conn, soul_name)["soul_id"])
    except Exception:
        from generate_assets import resolve_soul_id

        return resolve_soul_id(soul_name)


def _create_image_grid(*, root: Path, prompt_contract: dict[str, str], stem: str,
                       out_dir: Path, soul_id: str | None, soul_name: str | None,
                       image_model: str, image_aspect_ratio: str, image_quality: str,
                       wait: bool, download: bool) -> dict[str, Any]:
    capabilities = ensure_required_capabilities(root, image_model, VIDEO_MODEL)
    resolved = resolve_generation_models(capabilities, image_model, VIDEO_MODEL)
    resolved_soul_id = _resolve_soul_id(root, soul_id=soul_id, soul_name=soul_name)
    prompt = AssetPromptSet(
        higgsfieldGridPrompt=prompt_contract["higgsfieldGridPrompt"],
        klingMotionPrompt=prompt_contract.get("klingMotionPrompt", DEFAULT_KLING_MOTION_PROMPT),
        notes=prompt_contract.get("notes", ""),
    )
    identity_flag = image_identity_flag(capabilities, resolved["imageModel"])
    image_cmd = build_image_cmd(
        prompt,
        reference=None,
        soul_id=resolved_soul_id,
        model=resolved["imageModel"],
        identity_flag=identity_flag,
        aspect_ratio=image_aspect_ratio,
        quality=image_quality,
        wait=wait,
    )
    raw = _run_json(image_cmd)
    image_job_id = extract_id(raw)
    image_url = extract_url(raw)
    local_path = None
    if download and image_url:
        local_path = str(download_result(image_url, out_dir / f"{stem}_soul_grid.png"))
    return {
        "ok": True,
        "stem": stem,
        "command": image_cmd,
        "model": resolved["imageModel"],
        "identityFlag": identity_flag,
        "soulId": resolved_soul_id,
        "aspectRatio": image_aspect_ratio,
        "quality": image_quality,
        "imageJobId": image_job_id,
        "imageResultUrl": image_url,
        "localPath": local_path,
        "raw": raw,
    }


def run_ab_images_from_sidecar(*, sidecar_path: Path, root: Path | None = None,
                               soul_id: str | None = None, soul_name: str | None = None,
                               image_model: str | None = None,
                               image_aspect_ratio: str | None = None,
                               image_quality: str | None = None,
                               wait: bool = True,
                               download: bool = True) -> dict[str, Any]:
    sidecar_path = Path(sidecar_path).expanduser().resolve()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    run_root = Path(root).resolve() if root else sidecar_path.parent.parent.parent.resolve()
    stem = str(sidecar["stem"])
    image_out_root = run_root / "project_data" / "generated_assets" / "grok_ab" / stem
    model = image_model or str(sidecar.get("imageModel") or IMAGE_MODEL)
    aspect_ratio = image_aspect_ratio or str(sidecar.get("imageAspectRatio") or DEFAULT_AB_IMAGE_ASPECT_RATIO)
    quality = image_quality or str(sidecar.get("imageQuality") or "2k")
    if not (soul_id or soul_name):
        raise ValueError("soul_id or soul_name is required to run images from sidecar")

    for variant, condition in (sidecar.get("conditions") or {}).items():
        prompt_json_path = Path(condition["promptJsonPath"]).expanduser().resolve()
        prompt_contract = json.loads(prompt_json_path.read_text(encoding="utf-8"))
        generation = _create_image_grid(
            root=run_root,
            prompt_contract=prompt_contract,
            stem=f"{stem}_{variant}",
            out_dir=image_out_root,
            soul_id=soul_id,
            soul_name=soul_name,
            image_model=model,
            image_aspect_ratio=aspect_ratio,
            image_quality=quality,
            wait=wait,
            download=download,
        )
        generation["referencePassedToHiggsfield"] = None
        generation["promptEnhancement"] = False
        condition["generation"] = generation
    sidecar["imageModel"] = model
    sidecar["imageAspectRatio"] = aspect_ratio
    sidecar["imageQuality"] = quality
    sidecar["promptEnhancement"] = False
    _write_json(sidecar_path, sidecar)
    return {"ok": True, "sidecarPath": str(sidecar_path), **sidecar}


def create_ab_prompt_experiment(*, root: Path, stem: str, reference_image: Path,
                                examples_text: str, out_dir: Path | None = None,
                                model: str = DEFAULT_MODEL,
                                image_model: str = IMAGE_MODEL,
                                image_aspect_ratio: str = DEFAULT_AB_IMAGE_ASPECT_RATIO,
                                image_quality: str = "2k",
                                soul_id: str | None = None,
                                soul_name: str | None = None,
                                run_images: bool = False,
                                wait: bool = True,
                                download: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    reference_image = Path(reference_image).expanduser().resolve()
    if not reference_image.exists():
        raise FileNotFoundError(reference_image)
    if not examples_text.strip():
        raise ValueError("examples_text is required")
    if run_images and not (soul_id or soul_name):
        raise ValueError("soul_id or soul_name is required when run_images=True")

    out_root = Path(out_dir).expanduser().resolve() if out_dir else root / "prompts" / "experiments"
    out_root.mkdir(parents=True, exist_ok=True)
    image_out_root = root / "project_data" / "generated_assets" / "grok_ab" / stem
    api_key = load_xai_api_key(root)
    if not api_key:
        raise RuntimeError("XAI_API_KEY or project_data/secrets.toml xai_api_key is required")

    conditions: dict[str, Any] = {}
    for variant in ("A", "B"):
        instruction = build_variant_instruction(variant, examples_text)
        payload = build_xai_payload(model=model, frames=[reference_image], instruction=instruction)
        raw_response = call_grok(payload, api_key=api_key)
        raw_prompt = _plain_grok_text(raw_response)
        cleanup = clean_grok_prompt(raw_prompt)
        if not cleanup["valid"]:
            raise ValueError(
                f"variant {variant} still contains forbidden cleanup terms: "
                f"{cleanup['residualForbiddenTerms']}"
            )
        contract = prompt_contract_from_cleaned(cleanup["cleaned"])

        variant_prefix = f"{stem}_{variant}"
        instruction_path = out_root / f"{variant_prefix}_instruction.txt"
        raw_response_path = out_root / f"{variant_prefix}_grok_raw.json"
        raw_prompt_path = out_root / f"{variant_prefix}_raw_prompt.txt"
        cleaned_prompt_path = out_root / f"{variant_prefix}_cleaned_prompt.txt"
        cleanup_path = out_root / f"{variant_prefix}_cleanup_diff.json"
        prompt_json_path = out_root / f"{variant_prefix}_prompt.json"

        instruction_path.write_text(instruction, encoding="utf-8")
        _write_json(raw_response_path, raw_response)
        raw_prompt_path.write_text(raw_prompt + "\n", encoding="utf-8")
        cleaned_prompt_path.write_text(cleanup["cleaned"] + "\n", encoding="utf-8")
        _write_json(cleanup_path, cleanup)
        _write_json(prompt_json_path, contract)

        generation = {
            "status": "not_run",
            "referencePassedToHiggsfield": None,
            "promptEnhancement": False,
            "imageAspectRatio": image_aspect_ratio,
            "imageQuality": image_quality,
        }
        if run_images:
            try:
                generation = _create_image_grid(
                    root=root,
                    prompt_contract=contract,
                    stem=variant_prefix,
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
            except Exception as exc:
                generation = {
                    "ok": False,
                    "status": "failed",
                    "error": str(exc),
                    "referencePassedToHiggsfield": None,
                    "promptEnhancement": False,
                    "imageAspectRatio": image_aspect_ratio,
                    "imageQuality": image_quality,
                }

        conditions[variant] = {
            "label": "Explicit emphasis" if variant == "A" else "Example-led",
            "instructionPath": str(instruction_path),
            "rawResponsePath": str(raw_response_path),
            "rawPromptPath": str(raw_prompt_path),
            "cleanedPromptPath": str(cleaned_prompt_path),
            "cleanupDiffPath": str(cleanup_path),
            "promptJsonPath": str(prompt_json_path),
            "cleanup": cleanup,
            "generation": generation,
        }

    sidecar_path = out_root / f"{stem}_grok_few_shot_ab_experiment.json"
    payload = {
        "schema": SCHEMA,
        "experimental": True,
        "createdAt": int(time.time()),
        "stem": stem,
        "referenceImage": str(reference_image),
        "examplesLength": len(examples_text),
        "model": model,
        "imageModel": image_model,
        "imageAspectRatio": image_aspect_ratio,
        "imageQuality": image_quality,
        "imageReferencePolicy": "analysis_only_do_not_send_to_higgsfield",
        "promptEnhancement": False,
        "kling": "not part of this experiment",
        "conditions": conditions,
    }
    _write_json(sidecar_path, payload)
    return {"ok": True, "sidecarPath": str(sidecar_path), **payload}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--sidecar", type=Path, help="Run image jobs from an existing A/B sidecar without re-calling Grok.")
    ap.add_argument("--stem")
    ap.add_argument("--reference-image", type=Path)
    ap.add_argument("--examples-file", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--image-model", default=IMAGE_MODEL)
    ap.add_argument("--image-aspect-ratio", default=DEFAULT_AB_IMAGE_ASPECT_RATIO)
    ap.add_argument("--image-quality", default="2k")
    ap.add_argument("--soul-id")
    ap.add_argument("--soul-name")
    ap.add_argument("--run-images", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    if args.sidecar:
        if not args.run_images:
            raise SystemExit("--sidecar requires --run-images")
        result = run_ab_images_from_sidecar(
            sidecar_path=args.sidecar,
            root=args.root,
            soul_id=args.soul_id,
            soul_name=args.soul_name,
            image_model=args.image_model,
            image_aspect_ratio=args.image_aspect_ratio,
            image_quality=args.image_quality,
            wait=not args.no_wait,
            download=not args.no_download,
        )
    else:
        if not args.stem or not args.reference_image or not args.examples_file:
            raise SystemExit("--stem, --reference-image, and --examples-file are required unless --sidecar is used")
        examples_text = args.examples_file.expanduser().read_text(encoding="utf-8")
        result = create_ab_prompt_experiment(
            root=args.root,
            stem=args.stem,
            reference_image=args.reference_image,
            examples_text=examples_text,
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
