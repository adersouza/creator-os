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
  4. `build_spec`    - emit the exact two generations to run: original (reference
                       -conditioned) + sexy (TEXT-ONLY so the edit sticks).

The agent then runs the two `generate_image` calls from the spec and ranks the
results with `virality_select.select_best`. Nothing here spends money or posts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

# Phrases the reference-pass enhancer injects that must go before reuse.
# Identity descriptors fight the Soul; UI/screenshot words render fake app chrome
# (see AGENTS.md "Higgsfield Prompt UI Trigger Rule"). Nouns like "woman" are
# kept — only the offending adjective/phrase is removed.
_STRIP_PATTERNS = (
    # identity: ethnicity / age. NOTE "white" is deliberately NOT here -- it is a
    # common object color ("white lounge chairs", "blue and white sky").
    r"\byoung\b",
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
    text = re.sub(r"(?:^|(?<=\. ))\s*,\s*", "", text)  # leading comma in a clause
    text = re.sub(r"\ba\s+(?=wearing|posing|seated|standing|leaning)", "a woman ", text)
    return text.strip(" ,.\n") + ("." if text.strip(" ,.\n") else "")


def sexy_variant(cleaned: str, *, include_butt: bool) -> str:
    """Append-only body emphasis. House ceiling: cleavage (+ butt if full-body).

    Nothing else is amplified on purpose -- pose/expression/lighting edits degrade
    Soul V2 quality (AGENTS.md house style).
    """
    emphasis = "fuller chest with deeper cleavage"
    if include_butt:
        emphasis += " and a curvier rounder butt"
    base = cleaned.rstrip(" .")
    return f"{base}, {emphasis}."


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
) -> dict[str, Any]:
    """Two generations to run: original (reference-conditioned) + sexy (text-only).

    `reference_media_id` is the Higgsfield media_id of the UI-free cropped ref
    (the agent uploads it). The sexy variant is deliberately text-only: a ref
    image re-triggers enhancement that wipes the body edit.
    """
    cleaned = clean_prompt(captured_prompt)
    aspect = pick_aspect(cleaned)
    full_body = aspect == "2:3"
    sexy = sexy_variant(cleaned, include_butt=full_body)
    return {
        "soul_id": soul_id,
        "cleaned_prompt": cleaned,
        "original": {
            "model": "soul_2",
            "soul_id": soul_id,
            "prompt": cleaned,
            "aspect_ratio": aspect,
            # original keeps the reference for composition; enhancer will re-run.
            "reference_media_id": reference_media_id,
            "text_only": reference_media_id is None,
        },
        "sexy": {
            "model": "soul_2",
            "soul_id": soul_id,
            "prompt": sexy,
            "aspect_ratio": aspect,
            # sexy MUST be text-only or the ref re-enhances and drops the edit.
            "reference_media_id": None,
            "text_only": True,
        },
        "next": "run both generate_image calls, then virality_select.select_best on the results",
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
    ap.add_argument("--demo", action="store_true", help="Run the self-check and exit.")
    args = ap.parse_args(argv)
    if args.demo or not args.captured_prompt:
        _demo()
        return 0
    captured = sys.stdin.read() if args.captured_prompt == "-" else args.captured_prompt
    if not args.soul_id:
        ap.error("--soul-id is required with --captured-prompt")
    spec = build_spec(
        captured, soul_id=args.soul_id, reference_media_id=args.reference_media_id
    )
    print(json.dumps(spec, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
