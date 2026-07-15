"""hook_spinner.py — zero-API hook variation generator.

Takes a single base hook, identifies the opener pattern (POV / when_you /
me_when / etc.) and the core idea, then generates N stylistically diverse
variations using the opener-pattern menu from the OFM research blueprint.

This is a *template-based* spinner — no LLM, no API. The variations are
surface-level rewrites that preserve the core idea but vary the opener,
rhythm, and tone. Best when you write 1 strong base hook and want 8
stylistic angles for an account's content calendar.

Usage:
    python3 hook_spinner.py "POV you wear oversized clothes and he still notices"
    # → JSON list of 8-12 stylistic variations on stdout

Or from another module:
    from .hook_spinner import spin_hooks
    variations = spin_hooks("POV you wear oversized clothes and he still notices", n=10)
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys

# Opener patterns from the OFM research doc. Two slot styles:
#   {subj}  — fill with the core that retains the subject ("you wear X")
#   {verb}  — fill with the core stripped of leading subject ("wear X")
# Pick the slot that produces grammatical output for that pattern.
PATTERNS = {
    "pov": "POV {subj}",
    "pov_colon": "POV: {subj}",
    "when_you": "When you {verb}",
    "me_when": "Me when i {verb}",
    "the_way": "The way {subj}",
    "tell_me_why": "Tell me why {subj}",
    "imagine": "Imagine {subj}",
    "no_because": "no because {subj}",
    "the_fact_that": "the fact that {subj}",
    "nothing_like": "Nothing like {subj}",
    "that_thing_where": "That thing where {subj}",
    "direct": "DIRECT_MARKER",
    "question": "{subj}?",
    "ngl_suffix": "{subj} ngl",
    "fr_suffix": "{subj} fr",
}

# Subject pronouns that we strip to produce {verb} from {subj}.
_SUBJECT_RE = re.compile(r"^(?:you|i|im|i'm|i\s+am)\s+", re.I)

# Detectable existing openers — strip these to find the "core". Note we
# leave the "you" / "i" subject in the core so downstream templates that
# require it ("When you X", "Imagine X") still produce grammatical output.
# Patterns that DO subsume the subject (like "Me when X") only kick in when
# the core already lacks a subject (handled per-template below).
OPENER_RE = [
    (re.compile(r"^pov:?\s+", re.I), "pov"),
    (re.compile(r"^when\s+you\s+", re.I), "when_you"),
    (re.compile(r"^me\s+when\s+(?:i\s+)?", re.I), "me_when"),
    (re.compile(r"^the\s+way\s+", re.I), "the_way"),
    (re.compile(r"^tell\s+me\s+why\s+", re.I), "tell_me_why"),
    (re.compile(r"^imagine\s+", re.I), "imagine"),
    (re.compile(r"^no\s+because\s+", re.I), "no_because"),
    (re.compile(r"^the\s+fact\s+that\s+", re.I), "the_fact_that"),
    (re.compile(r"^nothing\s+like\s+", re.I), "nothing_like"),
    (re.compile(r"^that\s+thing\s+where\s+", re.I), "that_thing_where"),
]


def _extract_core(hook: str) -> tuple[str, str | None]:
    """Strip a known opener from `hook`. Returns (core, original_pattern_id).
    If no opener matched, original_pattern_id is None and core == hook."""
    h = hook.strip()
    for pat, name in OPENER_RE:
        m = pat.match(h)
        if m:
            return h[m.end() :].strip(), name
    return h, None


def _to_direct(core: str) -> str:
    """Reword the core into a punchy declarative sentence — drops verb-style
    openers, capitalizes first word, ensures it ends in a period or
    nothing (no question mark)."""
    s = core.strip().rstrip(".?!")
    # If starts with "i'm/im/i" make it more declarative (best-effort)
    s = re.sub(r"^(i\s+)", "", s, flags=re.I)
    # Try to capitalize first letter for declarative feel
    return s[:1].upper() + s[1:] + "."


def spin_hooks(base_hook: str, n: int = 10, seed: int | None = None) -> list[str]:
    """Return up to `n` stylistic variations of `base_hook`. Always includes
    the original as variation #0. Subsequent variations rotate through the
    opener-pattern menu, skipping whichever pattern the base hook already
    uses to avoid duplicates."""
    subj_core, original_pattern = _extract_core(base_hook)
    if not subj_core:
        return [base_hook]
    # verb_core: strip leading subject so {verb} templates don't duplicate it.
    verb_core = _SUBJECT_RE.sub("", subj_core).strip() or subj_core

    pattern_ids = [p for p in PATTERNS.keys() if p != original_pattern]
    stable_seed = int(hashlib.sha256(base_hook.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed if seed is not None else stable_seed)
    rng.shuffle(pattern_ids)

    variations = [base_hook]
    seen = {base_hook.lower().strip()}

    for pid in pattern_ids:
        tpl = PATTERNS[pid]
        try:
            if tpl == "DIRECT_MARKER":
                v = _to_direct(subj_core)
            elif "{verb}" in tpl:
                v = tpl.format(verb=verb_core.rstrip(".?!"))
            else:
                v = tpl.format(subj=subj_core.rstrip(".?!"))
        except (KeyError, ValueError):
            continue
        v = v.strip()
        key = v.lower().strip()
        if key in seen or len(v) < 8 or len(v) > 200:
            continue
        seen.add(key)
        variations.append(v)
        if len(variations) >= n:
            break

    return variations


def _cli() -> None:
    if len(sys.argv) < 2:
        print("usage: hook_spinner.py <base_hook> [count=10]", file=sys.stderr)
        sys.exit(1)
    hook = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    print(json.dumps(spin_hooks(hook, n=n), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _cli()
