#!/usr/bin/env python3
"""Reference -> Soul original+sexy variant prep (the deterministic half).

The house recipe (AGENTS.md "Reference -> Soul Variant Generation") has two
halves. The Higgsfield generate/upload/poll calls are MCP tools an agent drives;
they can't be called from Python. THIS module owns the deterministic, testable
half that used to be done by hand and got done wrong:

  1. `clean_prompt`  - strip identity descriptors + UI/screenshot words from the
                       prompt Higgsfield auto-generates on the reference pass
                       (those fight the Soul identity / render fake app chrome).
  2. `sexy_variant`  - append-only body emphasis, house ceiling (cleavage[+butt]).
  3. `pick_aspect`   - 3:4 selfie / 2:3 full-body / 9:16 reel.
  4. `build_spec`    - reuse the reference-pass output as the original and emit
                       exactly one additional sexy generation (TEXT-ONLY so the
                       edit sticks).

The agent runs only the sexy `generate_image` call from the spec, then ranks the
existing original and the sexy result with `virality_select.select_best`.
Nothing here spends money or posts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def autocrop_reference(
    src: str,
    dst: str | None = None,
    *,
    threshold: int = 28,
    bottom_trim: float = 0.0,
    sample_step: int = 4,
) -> dict[str, Any]:
    """Trim black bars/bezel off a reference screenshot before it goes to Higgsfield.

    A row/column is "border" when its BRIGHTEST sampled pixel is below `threshold`
    (photo edges always contain a bright pixel; letterbox/pillarbox/bezel don't).
    This reliably removes the pillarbox + phone-bezel that made Higgsfield render
    fake app UI.

    `bottom_trim` (0..0.3) is cut off the bottom FIRST, for video-player overlays
    (0:01 timer / mute icon) that sit ON the photo and cannot be brightness-detected
    -- caller passes it for video-post screenshots. ponytail: overlay position
    varies, so this stays an explicit knob, not an auto-guess.
    """
    from PIL import Image  # lazy: keep the pure-text functions PIL-free

    im = Image.open(src).convert("RGB")
    w, h = im.size
    if bottom_trim:
        im = im.crop((0, 0, w, int(h * (1 - min(max(bottom_trim, 0.0), 0.3)))))
        w, h = im.size
    px = im.convert("L").load()
    ys = range(0, h, sample_step)
    xs = range(0, w, sample_step)

    def col_ok(x: int) -> bool:
        return max(px[x, y] for y in ys) >= threshold

    def row_ok(y: int) -> bool:
        return max(px[x, y] for x in xs) >= threshold

    x0 = 0
    while x0 < w - 1 and not col_ok(x0):
        x0 += 1
    x1 = w - 1
    while x1 > x0 and not col_ok(x1):
        x1 -= 1
    y0 = 0
    while y0 < h - 1 and not row_ok(y0):
        y0 += 1
    y1 = h - 1
    while y1 > y0 and not row_ok(y1):
        y1 -= 1
    clean = im.crop((x0, y0, x1 + 1, y1 + 1))
    out = Path(dst) if dst else Path(src).with_name(Path(src).stem + "_clean.jpg")
    clean.save(out, quality=95)
    return {
        "path": str(out),
        "bbox": [x0, y0, x1 + 1, y1 + 1],
        "size": list(clean.size),
        "trimmed_px": [w - clean.size[0], h - clean.size[1]],
    }


# Phrases the reference-pass enhancer injects that must go before reuse.
# Identity descriptors fight the Soul; UI/screenshot words render fake app chrome
# (see AGENTS.md "Higgsfield Prompt UI Trigger Rule"). Creator-specific identity
# guidance is appended later from an explicit allowlist.
_STRIP_PATTERNS = (
    # identity: ethnicity / age. NOTE "white" is deliberately NOT here -- it is a
    # common object color ("white lounge chairs", "blue and white sky").
    r"\byoung\b",
    r"\badults?\b",
    r"\b(?:adult\s+)?(?:woman|girl|teen)\b",
    r"\b(?:caucasian|latina|hispanic|middle[- ]eastern)\b",
    # age clause incl. the "(she) appears to be in her early 20s" lead-in
    r"\b(?:she )?appears to be(?: in her[^,.]*)?",
    r"\b(?:likely |estimated to be )?in her (?:early |mid-?|late )?(?:teens|twenties|20s|thirties|30s)\b",
    r"\bestimated to be[^,.]*",
    r"\b\d+[- ]year-old\b",
    # identity: hair -- adjective run (commas allowed) + "hair", plus an OPTIONAL
    # trailing hair-styling clause (parted/framing/...). Bounded to styling words
    # so it never runs into scene text ("...hair, posing on a beach" keeps beach).
    r"\b(?:with |her )?(?:(?:long|short|shoulder-length|medium-length|wavy|straight|curly|damp|slightly|dark|light|jet|platinum|brown|blonde?|black|red|auburn|brunette|ginger)[,\s]+)+hair\b(?:\s*,?\s*(?:parted|framing|frames|pulled|tied|swept)[^,.]*(?:,\s*framing[^,.]*)?)?",
    r"\bhair (?:parted|framing|frames|tied|pulled)[^,.]*",
    # identity: face marks (strip the whole "she has/wears ..." clause)
    r"\bshe (?:has|wears|sports) (?:a )?(?:small )?(?:hoop )?nose (?:ring|stud|piercing)\b[^,.]*",
    r"\b(?:a )?(?:small )?(?:hoop )?nose (?:ring|stud|piercing)\b",
    r"\bher nose is adorned[^,.]*",
    r"\bpiercings?\b",
    r"\bfreckl(?:e|es|ed)\b",
    r"\btattoos?\b",
    # UI / screenshot
    r"\bthe (?:image|photo|shot) is framed as[^.]*\.",
    r"\b(?:a )?(?:digital )?screenshot(?: of a social media post)?[^,.]*",
    r"\bsocial[- ]media[^,.]*",
    r"\buser interface elements?[^.]*",
    r"\bui elements?[^,.]*",
    r"\b(?:an )?(?:oversized )?blue plus (?:sign|button)[^,.]*",
    r"\bwith common social media icons?[^,.]*",
    r"\bhome, ?search[^,.]*",
    r"\bnotifications?\b",
    r"\binterface\b",
    r"\bwatermark\b",
    r"\bicons?\b",
    r"\b(?:shot |taken |captured )?(?:on |with )?a (?:smart)?phone(?: camera)?\b",
    r"\b(?:smart)?phone\b",
    r"\biphone\b",
    r"\bstory\b",
    r"\bcaption\b",
    r"\boverlay\b",
    # the trailing hex palette block enhancer always appends
    r"\bHEX VALUES:.*$",
)
_STRIP_RE = re.compile("|".join(_STRIP_PATTERNS), flags=re.IGNORECASE | re.DOTALL)

# Full-body cues -> 2:3 (fits legs/butt); reel cues -> 9:16; else 3:4 selfie.
_FULLBODY_CUES = (
    "full-body",
    "full body",
    "full length",
    "standing",
    "seated",
    "sitting",
    "legs",
    "wide shot",
    "medium-wide",
    "medium wide",
    "prow",
    "boat",
    "head to toe",
    "from head",
)
_REEL_CUES = ("reel", "story", "9:16", "vertical video", "tiktok")


def clean_prompt(captured: str) -> str:
    """Remove identity descriptors + UI/screenshot words, tidy punctuation."""
    text = _STRIP_RE.sub("", captured)
    # drop orphaned subject-verbs left when their object was stripped ("She has.")
    text = re.sub(
        r"(?i)\b(?:she|he|the woman|her)\s+(?:has|is|wears|sports)\s*(?=[.,]|$)",
        "",
        text,
    )
    text = re.sub(r"\s*,(?:\s*,)+", ",", text)  # collapse ", ," runs
    text = re.sub(r"\s{2,}", " ", text)  # collapse double spaces
    text = re.sub(r"\s+([,.])", r"\1", text)  # space-before-punct
    text = re.sub(r",\s*\.", ".", text)  # ", ." -> "."
    text = re.sub(r"\.\s*,", ".", text)  # ". ," -> "."
    text = re.sub(r"\b(?:of|featuring|showing)\s+(?:an?|the)?\s*(?=[,.])", "", text)
    text = re.sub(r"(?i)\b(?:in|with|of|as|on)\s+(?:an?|the)?\s*(?=[,.]|$)", "", text)
    text = re.sub(
        r"(?i)^\s*(?:an?|the)\s+(?=(?:taking|posing|wearing|seated|standing|sitting|leaning)\b)",
        "",
        text,
    )
    text = re.sub(r"\s+([,.])", r"\1", text)
    text = re.sub(r"(?:^|(?<=\. ))\s*,\s*", "", text)  # leading comma in a clause
    text = re.sub(r"\ba\s+(?=wearing|posing|seated|standing|leaning)", "", text)
    return text.strip(" ,.\n") + ("." if text.strip(" ,.\n") else "")


_STACEY_SOUL_IDS = {
    "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
    "5828d958-91dd-4d6d-8909-934503f47644",
}
_STACEY_IDENTITY_GUIDANCE = "19 years old, dark hair, no tattoos"


def sexy_variant(
    cleaned: str, *, include_butt: bool, identity_guidance: str | None = None
) -> str:
    """Append-only body emphasis. House ceiling: cleavage (+ butt if full-body).

    Nothing else is amplified on purpose -- pose/expression/lighting edits degrade
    Soul V2 quality (AGENTS.md house style).
    """
    emphasis = "fuller chest with deeper cleavage"
    if include_butt:
        emphasis += " and a curvier rounder butt"
    base = cleaned.rstrip(" .")
    parts = [part for part in (base, identity_guidance, emphasis) if part]
    return ", ".join(parts) + "."


def pick_aspect(prompt: str) -> str:
    low = prompt.lower()
    if any(c in low for c in _REEL_CUES):
        return "9:16"
    if any(c in low for c in _FULLBODY_CUES):
        return "2:3"
    return "3:4"


def build_spec(
    captured_prompt: str,
    *,
    soul_id: str,
    reference_media_id: str | None = None,
    identity_guidance: str | None = None,
) -> dict[str, Any]:
    """Reuse the reference result and plan one sexy text-only generation.

    `reference_media_id` is the Higgsfield media_id of the UI-free cropped ref
    used by the already-completed reference pass. It remains lineage evidence;
    it must not trigger a second original generation. The sexy variant is
    deliberately text-only because a ref image re-triggers enhancement and
    wipes the body edit.
    """
    cleaned = clean_prompt(captured_prompt)
    aspect = pick_aspect(cleaned)
    full_body = aspect == "2:3"
    guidance = (
        identity_guidance
        if identity_guidance is not None
        else _STACEY_IDENTITY_GUIDANCE
        if soul_id in _STACEY_SOUL_IDS
        else None
    )
    sexy = sexy_variant(cleaned, include_butt=full_body, identity_guidance=guidance)
    return {
        "soul_id": soul_id,
        "cleaned_prompt": cleaned,
        "identity_guidance": guidance,
        "original": {
            "source": "reference_pass_result",
            "generation_required": False,
            "aspect_ratio": aspect,
            "reference_media_id": reference_media_id,
        },
        "sexy": {
            "model": "soul_2",
            "soul_id": soul_id,
            "prompt": sexy,
            "aspect_ratio": aspect,
            "generation_required": True,
            # sexy MUST be text-only or the ref re-enhances and drops the edit.
            "reference_media_id": None,
            "text_only": True,
        },
        "provider_generation_count": 1,
        "next": "run only the sexy generate_image call, then rank the existing original and sexy result with virality_select.select_best",
    }


def _demo() -> None:
    sample = (
        "A slightly high-angle, close-up selfie of a young Caucasian woman with "
        "long dark hair, posing outdoors on a beach. She is wearing a black lace "
        "bikini top with thin straps. She has a small hoop nose ring. The image is "
        "framed as a digital screenshot of a social media post, with an oversized "
        "blue plus sign visible at the bottom.\n"
        'HEX VALUES: ["#000000", "#7f534a"]'
    )
    cleaned = clean_prompt(sample)
    assert "caucasian" not in cleaned.lower(), cleaned
    assert "nose ring" not in cleaned.lower(), cleaned
    assert "screenshot" not in cleaned.lower(), cleaned
    assert "plus sign" not in cleaned.lower(), cleaned
    assert "hex values" not in cleaned.lower(), cleaned
    assert "bikini" in cleaned.lower(), cleaned  # outfit survives
    assert "beach" in cleaned.lower(), cleaned  # scene survives
    spec = build_spec(cleaned, soul_id="soul-x", reference_media_id="ref-1")
    assert spec["sexy"]["text_only"] is True
    assert spec["original"]["generation_required"] is False
    assert spec["provider_generation_count"] == 1
    assert "cleavage" in spec["sexy"]["prompt"].lower()
    assert spec["original"]["aspect_ratio"] == "3:4"  # selfie
    boat = build_spec(
        "A medium-wide shot, seated on the prow of a boat, wearing a bikini",
        soul_id="soul-y",
    )
    assert boat["sexy"]["aspect_ratio"] == "2:3"  # full-body
    assert "butt" in boat["sexy"]["prompt"].lower()
    print("generate_variants self-check OK")
    print(json.dumps(spec, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--captured-prompt",
        help="Prompt Higgsfield returned on the reference pass (or '-' for stdin).",
    )
    ap.add_argument("--soul-id", help="Creator Soul ID.")
    ap.add_argument(
        "--reference-media-id", help="Higgsfield media_id of the UI-free crop."
    )
    ap.add_argument(
        "--identity-guidance",
        help="Explicit creator guidance appended only to the text-only variant.",
    )
    ap.add_argument(
        "--autocrop", help="Path to a reference screenshot to trim (black bars/bezel)."
    )
    ap.add_argument(
        "--bottom-trim",
        type=float,
        default=0.0,
        help="Fraction to cut off the bottom first (video UI overlays). e.g. 0.06.",
    )
    ap.add_argument("--out", help="Output path for --autocrop.")
    ap.add_argument("--demo", action="store_true", help="Run the self-check and exit.")
    args = ap.parse_args(argv)
    if args.autocrop:
        print(
            json.dumps(
                autocrop_reference(
                    args.autocrop, args.out, bottom_trim=args.bottom_trim
                ),
                indent=2,
            )
        )
        return 0
    if args.demo or not args.captured_prompt:
        _demo()
        return 0
    captured = sys.stdin.read() if args.captured_prompt == "-" else args.captured_prompt
    if not args.soul_id:
        ap.error("--soul-id is required with --captured-prompt")
    spec = build_spec(
        captured,
        soul_id=args.soul_id,
        reference_media_id=args.reference_media_id,
        identity_guidance=args.identity_guidance,
    )
    print(json.dumps(spec, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
