#!/usr/bin/env python3
"""Deterministic Prompt Builder output contract.

The active Reel Factory path now treats Higgsfield stills and Kling motion as
separate compiler outputs. Legacy field names are kept for compatibility, but
new operator workflows should generate one standalone image prompt and one
start-image Kling motion prompt.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

REQUIRED_PROMPT_FIELDS = ("higgsfieldGridPrompt", "klingMotionPrompt")
HIGGSFIELD_GRID_PROMPT_REJECTS = (
    "no",
    "avoid",
    "without",
    "do not",
    "bad hands",
    "extra limbs",
    "warped face",
    "identity",
    "hair",
    "hairstyle",
    "hair color",
    "eye color",
    "ethnicity",
    "tattoo",
    "freckle",
    "freckles",
    "skin texture",
    "skin sheen",
    "natural sheen",
    "perfect face",
    "high detail",
    "sharp focus",
    "caption",
    "text",
    "overlay",
    "text overlay",
    "on-screen text",
    "hook",
    "hook text",
    "ui",
    "interface",
    "instagram",
    "social-media",
    "creator-reel",
    "username",
    "comment",
    "button",
    "watermark",
)
_FINAL_PROMPT_RE = re.compile(
    r"\b(?:no|avoid|without)\b|\bdo\s+not\b|\bbad\s+hands\b|\bextra\s+limbs\b|\bwarped\s+face\b"
    r"|\bidentity\b"
    r"|\bhair\b|\bhairstyle\b|\bhair\s+color\b|\beye\s+color\b|\bethnicity\b|\btattoos?\b"
    r"|\bfreckles?\b|\bfreckled\b|\bskin\s+texture\b|\bskin\s+sheen\b|\bnatural\s+sheen\b"
    r"|\bperfect\s+face\b|\bhigh\s+detail\b|\bsharp\s+focus\b"
    r"|\bcaption\b|\btext\b|\boverlay\b|\btext\s+overlay\b|\bon-screen\s+text\b|\bhook\b|\bhook\s+text\b"
    r"|\bui\b|\binterface\b|\binstagram\b|\bsocial-media\b|\bcreator-reel\b"
    r"|\busername\b|\bcomment\b|\bbutton\b|\bwatermark\b",
    flags=re.IGNORECASE,
)
_MOTION_PROMPT_RE = re.compile(
    r"\bbad\s+hands\b|\bextra\s+limbs\b|\bwarped\s+face\b"
    r"|\bidentity\b"
    r"|\bhair\s+color\b|\beye\s+color\b|\bethnicity\b|\btattoos?\b"
    r"|\bperfect\s+face\b|\bhigh\s+detail\b|\bsharp\s+focus\b"
    r"|\bui\b|\binterface\b|\binstagram\b|\bsocial-media\b|\bcreator-reel\b"
    r"|\busername\b|\bcomment\b|\bbutton\b|\bwatermark\b",
    flags=re.IGNORECASE,
)


PROMPT_BUILDER_SPEC = """Prompt Builder contract:

Runtime behavior:
- Deterministic compiler only.
- No LLM calls.
- No randomness unless an explicit seed is supplied.
- Same normalized visual formula, motion timeline, enhancement profile, and seed must produce identical output.
- Normalized visual formula may include Grok's structured sexierVisualDirection, visualEmphasisSignals, and enhancementSuggestions.
- Output exactly one standalone Higgsfield Soul ID prompt and one shared Kling motion prompt.

Higgsfield/Soul ID still prompt:
- One prompt only.
- The active prompt requests one standalone 9:16 image.
- Legacy grid/fanout tooling must be explicitly selected and is not the default operator path.
- The externally provided Soul ID handles identity.
- The prompt describes the desired visible result: outfit, garment fit, garment placement, pose, framing, camera, lighting, environment, style, and generic panel consistency.
- The prompt can apply the selected deterministic enhancement profile to body emphasis and garment fit.
- The prompt does not describe detailed reference identity traits such as hair, ethnicity, or tattoos. Adult age wording is allowed when useful; Soul ID handles identity externally.
- Generic consistency language such as same adult woman and consistent body proportions is allowed when it helps the image stay coherent.
- The prompt does not spend budget on face polish such as perfect face, freckles, skin texture, skin sheen, natural sheen, high detail, or sharp focus.
- The prompt has no negative prompt field.
- The prompt uses positive desired-result language only.
- The prompt contains no negative language: avoid, without, do not, no.
- The prompt contains no defect-control terms such as extra limbs, bad hands, warped face, text, watermark, low quality, or similar rejection language.
- The prompt contains only subject, wardrobe, garment fit, pose, framing, camera, lighting, environment, and style details.

Kling motion prompt:
- One shared motion prompt only.
- The shared motion prompt is applied to the accepted 9:16 start image.
- The shared prompt describes camera movement, body movement, transition behavior, pacing, and loop feel using positive desired-motion language.
- The shared prompt may include explicit safety boundaries for no text/logos, no outfit change, and no head/face crop.

Required output contract:
{
  "higgsfieldGridPrompt": "One prompt for the standalone Higgsfield Soul ID still...",
  "klingMotionPrompt": "One shared Kling motion prompt for the accepted start image...",
  "notes": "Short operator note, optional but useful."
}
"""


@dataclass(frozen=True)
class AssetPromptSet:
    higgsfieldGridPrompt: str
    klingMotionPrompt: str
    notes: str = ""


EMPTY_ASSET_PROMPT_SET = AssetPromptSet(
    higgsfieldGridPrompt="",
    klingMotionPrompt="",
    notes="",
)


def build_grok_simple_prompt(
    reference_context: str = "", creative_direction: str = ""
) -> str:
    """Build the operator-facing Prompt Builder contract text."""
    parts = [PROMPT_BUILDER_SPEC.strip()]
    if reference_context.strip():
        parts.append(f"Reference context:\n{reference_context.strip()}")
    if creative_direction.strip():
        parts.append(f"Extra creative direction:\n{creative_direction.strip()}")
    return "\n\n".join(parts) + "\n"


def validate_higgsfield_grid_prompt_text(text: str) -> None:
    match = _FINAL_PROMPT_RE.search(text)
    if match:
        raise ValueError(
            f"higgsfieldGridPrompt contains rejected v1 language: {match.group(0)!r}"
        )


def validate_kling_motion_prompt_text(text: str) -> None:
    match = _MOTION_PROMPT_RE.search(text)
    if match:
        raise ValueError(
            f"klingMotionPrompt contains rejected v1 language: {match.group(0)!r}"
        )


def parse_asset_prompt_response(raw: str) -> AssetPromptSet:
    """Parse and validate the deterministic Prompt Builder JSON response."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("prompt response must be strict JSON") from e
    if not isinstance(data, dict):
        raise ValueError("prompt response must be a JSON object")
    unknown = sorted(set(data) - {*REQUIRED_PROMPT_FIELDS, "notes"})
    if unknown:
        raise ValueError(f"prompt response contains unsupported fields: {unknown}")
    missing = [
        field
        for field in REQUIRED_PROMPT_FIELDS
        if not str(data.get(field, "")).strip()
    ]
    if missing:
        raise ValueError(f"prompt response missing required fields: {missing}")
    validate_higgsfield_grid_prompt_text(str(data["higgsfieldGridPrompt"]))
    validate_kling_motion_prompt_text(str(data["klingMotionPrompt"]))
    return AssetPromptSet(
        higgsfieldGridPrompt=str(data["higgsfieldGridPrompt"]).strip(),
        klingMotionPrompt=str(data["klingMotionPrompt"]).strip(),
        notes=str(data.get("notes", "")).strip(),
    )


def prompt_response_json(prompt_set: AssetPromptSet) -> str:
    return json.dumps(asdict(prompt_set), indent=2, ensure_ascii=False)


def write_prompt_template(path: str) -> None:
    out_path = Path(path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        prompt_response_json(EMPTY_ASSET_PROMPT_SET) + "\n", encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print-system-prompt", action="store_true")
    ap.add_argument("--reference-context", default="")
    ap.add_argument("--creative-direction", default="")
    ap.add_argument("--validate-response", help="Validate a Grok JSON response string.")
    ap.add_argument(
        "--new", help="Create an empty clean prompt JSON template at this path."
    )
    args = ap.parse_args()

    if args.print_system_prompt:
        print(build_grok_simple_prompt(args.reference_context, args.creative_direction))
        return 0
    if args.validate_response:
        print(prompt_response_json(parse_asset_prompt_response(args.validate_response)))
        return 0
    if args.new:
        write_prompt_template(args.new)
        print(args.new)
        return 0
    raise SystemExit("--print-system-prompt, --validate-response, or --new is required")


if __name__ == "__main__":
    raise SystemExit(main())
