"""Deterministic caption text variation.

The renderer calls this module only when text variation is enabled. The
default pack keeps changes surface-level: casual spelling, abbreviation, and
case shifts while preserving the original hook shape.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass


DEFAULT_SLANG_PACK: dict[str, list[str]] = {
    "you": ["u", "u", "you"],
    "your": ["ur", "ur", "your"],
    "you're": ["ur", "you're"],
    "youre": ["ur", "youre"],
    "what": ["wat", "wht", "what"],
    "that": ["tht", "that", "that"],
    "this": ["dis", "this", "this"],
    "the": ["the", "the", "the", "da"],
    "with": ["w/", "with", "with"],
    "are": ["r", "are", "are"],
    "for": ["4", "for", "for"],
    "to": ["2", "to", "to", "to"],
    "and": ["&", "n", "and", "and"],
    "because": ["bc", "cuz", "because"],
    "people": ["ppl", "people", "people"],
    "really": ["rly", "really"],
    "though": ["tho", "though"],
    "about": ["abt", "about"],
    "would": ["wud", "would"],
    "could": ["cud", "could"],
    "should": ["shud", "should"],
    "okay": ["ok", "okay"],
    "something": ["smth", "something"],
    "nothing": ["nothin", "nothing"],
    "love": ["luv", "love", "love"],
    "before": ["b4", "before"],
    "right": ["rite", "right", "right"],
    "like": ["like", "like", "lyk"],
    "never": ["nvr", "never"],
    "ever": ["evr", "ever"],
    "have": ["hv", "have", "have"],
    "having": ["havin", "having"],
    "going": ["goin", "going"],
    "doing": ["doin", "doing"],
    "looking": ["lookin", "looking"],
    "making": ["makin", "making"],
    "saying": ["sayin", "saying"],
    "wearing": ["wearin", "wearing"],
    "thinking": ["thinkin", "thinking"],
    "everything": ["evrythng", "everything"],
    "everyone": ["evry1", "everyone"],
    "someone": ["sm1", "someone"],
    "anyone": ["any1", "anyone"],
    "when": ["wen", "when", "when"],
    "where": ["wer", "where"],
    "why": ["y", "why", "why"],
    "well": ["wel", "well"],
    "friend": ["frnd", "friend"],
    "girl": ["gurl", "girl", "girl"],
    "be": ["b", "be", "be", "be"],
    "see": ["c", "see", "see"],
    "literally": ["lowkey", "literally", "fr"],
    "honestly": ["fr", "lowkey", "honestly"],
}

SLANG_PACKS = {
    "default": DEFAULT_SLANG_PACK,
}

PACK_VERSIONS = {
    "default": "default@1",
}

_WORD_RE = re.compile(r"[A-Za-z']+")


@dataclass(frozen=True)
class VariationConfig:
    mode: str = "off"
    pack: str = "default"
    lowercase_probability: float = 0.55

    @property
    def version(self) -> str:
        return get_pack_version(self.pack)


def get_pack_version(pack: str = "default") -> str:
    if pack not in PACK_VERSIONS:
        raise ValueError(f"unknown slang pack: {pack}")
    return PACK_VERSIONS[pack]


def _preserve_case(original: str, replacement: str) -> str:
    if not replacement or not replacement[0].isalpha():
        return replacement
    if len(original) > 1 and original.isupper():
        return replacement.upper()
    if original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def vary_caption_text(
    text: str,
    seed_str: str,
    mode: str = "auto",
    *,
    pack: str = "default",
    lowercase_probability: float = 0.55,
) -> str:
    """Apply deterministic slang substitutions and optional case changes."""
    if mode == "off" or not text:
        return text
    if mode != "auto":
        raise ValueError(f"unknown text variation mode: {mode}")
    slang_map = SLANG_PACKS.get(pack)
    if slang_map is None:
        raise ValueError(f"unknown slang pack: {pack}")

    rng = random.Random(seed_str)

    def _replace(match: re.Match) -> str:
        word = match.group(0)
        key = word.lower()
        if key not in slang_map:
            return word
        return _preserve_case(word, rng.choice(slang_map[key]))

    out = _WORD_RE.sub(_replace, text)
    if rng.random() < lowercase_probability:
        out = out.lower()
    return out
