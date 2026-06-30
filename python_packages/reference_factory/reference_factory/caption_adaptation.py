from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import DEFAULT_DATA_ROOT
from .identity import text_hash

DEFAULT_PROFILE: dict[str, object] = {
    "schema": "reference_factory.caption_adaptation_profile.v1",
    "name": "default_our_models",
    "singular": "our girl",
    "plural": "our girls",
    "self_singular": "one of our girls",
    "self_plural": "our kind of girls",
    "neutral_person": "this girl",
    "notes": "Generic profile used when a caption references a trait that may not match the production model.",
    "replace_terms": {
        "indian girl": "our girl",
        "indian girls": "our girls",
        "asian girl": "our girl",
        "asian girls": "our girls",
        "slavic girl": "our girl",
        "slavic girls": "our girls",
        "ginger girl": "our girl",
        "ginger girls": "our girls",
        "redhead": "our girl",
        "redheads": "our girls",
        "blonde girl": "our girl",
        "blonde girls": "our girls",
        "brunette girl": "our girl",
        "brunette girls": "our girls",
        "latina girl": "our girl",
        "latina girls": "our girls",
        "white girl": "our girl",
        "white girls": "our girls",
        "black girl": "our girl",
        "black girls": "our girls",
    },
}


SELF_TRAITS = "indian|asian|slavic|ginger|redhead|blonde|brunette|latina|white|black"
HASHTAG_RE = re.compile(r"#[\w._-]+")
DESCRIPTOR_TRAITS = "skinny|petite|thick|curvy|tall|short|fit|cute|shy|older|younger"


SELF_PATTERNS = [
    (
        re.compile(rf"\b(we(?:'re| are))\s+({SELF_TRAITS})\s+girls\b", re.I),
        "self_plural",
    ),
    (
        re.compile(rf"\b(i(?:'m| am))\s+(?:a|an)?\s*({SELF_TRAITS})\s+girl\b", re.I),
        "self_singular",
    ),
]


DESCRIPTOR_PATTERNS = [
    (
        re.compile(rf"\b({DESCRIPTOR_TRAITS})\s+({SELF_TRAITS})\s+girls\b", re.I),
        "descriptor_plural",
    ),
    (
        re.compile(rf"\b({DESCRIPTOR_TRAITS})\s+({SELF_TRAITS})\s+girl\b", re.I),
        "descriptor_singular",
    ),
    (
        re.compile(
            rf"\b(\d\s*['’\"]?\s*\d|\d\s*ft\s*\d|5[\"']4)\s+({SELF_TRAITS})\s+girl\b",
            re.I,
        ),
        "descriptor_singular",
    ),
]


TRAIT_PATTERNS = [
    (re.compile(rf"\b({SELF_TRAITS})\s+girls\b", re.I), "plural_trait"),
    (re.compile(rf"\b({SELF_TRAITS})\s+girl\b", re.I), "singular_trait"),
    (
        re.compile(r"\ba\s+(ginger|redhead|blonde|brunette|latina)\b", re.I),
        "a_trait_person",
    ),
]


def ensure_default_profile(data_root: Path = DEFAULT_DATA_ROOT) -> Path:
    profile_path = data_root / "captions" / "caption_adaptation_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if not profile_path.exists():
        profile_path.write_text(
            json.dumps(DEFAULT_PROFILE, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return profile_path


def adapt_caption_library(
    data_root: Path = DEFAULT_DATA_ROOT,
    profile_path: Path | None = None,
    input_path: Path | None = None,
) -> dict[str, object]:
    captions_dir = data_root / "captions"
    input_path = input_path or captions_dir / "caption_library_unique.jsonl"
    profile_path = profile_path or ensure_default_profile(data_root)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    rows = _read_jsonl(input_path)

    adapted = []
    changed = 0
    for row in rows:
        original = str(row.get("text") or "")
        adapted_text, rules = adapt_caption_text(original, profile)
        item = {
            "schema": "reference_factory.adapted_caption.v1",
            "captionHash": row.get("captionHash"),
            "adaptedCaptionHash": text_hash(adapted_text),
            "sourceType": row.get("sourceType"),
            "reviewLabel": row.get("reviewLabel"),
            "account": row.get("account"),
            "referenceId": row.get("referenceId"),
            "localPath": row.get("localPath"),
            "publicPostId": row.get("publicPostId"),
            "shortCode": row.get("shortCode"),
            "url": row.get("url"),
            "plays": row.get("plays"),
            "flags": row.get("flags") or [],
            "originalText": original,
            "adaptedText": adapted_text,
            "changed": adapted_text != original,
            "rulesApplied": rules,
        }
        if item["changed"]:
            changed += 1
        adapted.append(item)

    outputs = _write_outputs(captions_dir, adapted, profile)
    return {
        "schema": "reference_factory.adapt_caption_library.v1",
        "inputPath": str(input_path),
        "profilePath": str(profile_path),
        "total": len(adapted),
        "changed": changed,
        "unchanged": len(adapted) - changed,
        "outputs": outputs,
    }


def adapt_caption_text(
    text: str, profile: dict[str, Any] | None = None
) -> tuple[str, list[str]]:
    profile = profile or DEFAULT_PROFILE
    singular = str(profile.get("singular") or "our girl")
    plural = str(profile.get("plural") or "our girls")
    self_singular = str(profile.get("self_singular") or "one of our girls")
    self_plural = str(profile.get("self_plural") or "our kind of girls")
    neutral = str(profile.get("neutral_person") or "this girl")
    replace_terms = dict(profile.get("replace_terms") or {})
    adapted, protected = _protect_hashtags(text)
    rules: list[str] = []

    def self_plural_repl(match: re.Match[str]) -> str:
        rules.append(f"self_plural:{match.group(2)}->{self_plural}")
        return f"{match.group(1)} {self_plural}"

    def self_singular_repl(match: re.Match[str]) -> str:
        rules.append(f"self_singular:{match.group(2)}->{self_singular}")
        return f"{match.group(1)} {self_singular}"

    self_replacements = {
        "self_plural": self_plural_repl,
        "self_singular": self_singular_repl,
    }
    for pattern, key in SELF_PATTERNS:
        adapted = pattern.sub(self_replacements[key], adapted)

    def descriptor_plural_repl(match: re.Match[str]) -> str:
        rules.append(f"descriptor_plural:{match.group(1)} {match.group(2)}->{plural}")
        return _preserve_case(match.group(0), plural)

    def descriptor_singular_repl(match: re.Match[str]) -> str:
        rules.append(
            f"descriptor_singular:{match.group(1)} {match.group(2)}->{singular}"
        )
        return _preserve_case(match.group(0), singular)

    descriptor_replacements = {
        "descriptor_plural": descriptor_plural_repl,
        "descriptor_singular": descriptor_singular_repl,
    }
    for pattern, key in DESCRIPTOR_PATTERNS:
        adapted = pattern.sub(descriptor_replacements[key], adapted)

    def article_trait_repl(match: re.Match[str]) -> str:
        rules.append(f"trait_person:{match.group(1)}->{neutral}")
        return _preserve_case(match.group(0), neutral)

    for pattern, key in TRAIT_PATTERNS:
        if key == "a_trait_person":
            adapted = pattern.sub(article_trait_repl, adapted)

    for source, target in sorted(
        replace_terms.items(), key=lambda item: len(item[0]), reverse=True
    ):
        pattern = re.compile(rf"\b{re.escape(source)}\b", re.I)
        adapted, count = pattern.subn(str(target), adapted)
        if count:
            rules.append(f"term:{source}->{target}")

    def plural_repl(match: re.Match[str]) -> str:
        rules.append(f"trait_plural:{match.group(1)}->{plural}")
        return _preserve_case(match.group(0), plural)

    def singular_repl(match: re.Match[str]) -> str:
        rules.append(f"trait_singular:{match.group(1)}->{singular}")
        return _preserve_case(match.group(0), singular)

    replacements = {
        "plural_trait": plural_repl,
        "singular_trait": singular_repl,
    }
    for pattern, key in TRAIT_PATTERNS:
        if key == "a_trait_person":
            continue
        adapted = pattern.sub(replacements[key], adapted)

    adapted = re.sub(
        rf"\b(an?|one)\s+{re.escape(singular)}\b", self_singular, adapted, flags=re.I
    )
    adapted = _restore_protected(adapted, protected)
    return _clean_spacing(adapted), _dedupe_rules(rules)


def _protect_hashtags(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"@@RF_HASHTAG_{len(protected)}@@"
        protected[token] = match.group(0)
        return token

    return HASHTAG_RE.sub(replace, text), protected


def _restore_protected(text: str, protected: dict[str, str]) -> str:
    restored = text
    for token, value in protected.items():
        restored = restored.replace(token, value)
    return restored


def _write_outputs(
    captions_dir: Path, adapted: list[dict[str, object]], profile: dict[str, Any]
) -> dict[str, str]:
    out_dir = captions_dir / "adapted"
    out_dir.mkdir(parents=True, exist_ok=True)
    all_jsonl = out_dir / "adapted_captions.jsonl"
    changed_jsonl = out_dir / "adapted_captions_changed.jsonl"
    all_txt = out_dir / "adapted_captions.txt"
    changed_txt = out_dir / "adapted_captions_changed.txt"
    gold_txt = out_dir / "adapted_captions_gold.txt"
    maybe_txt = out_dir / "adapted_captions_maybe.txt"
    summary_path = out_dir / "adapted_caption_summary.json"

    _write_jsonl(all_jsonl, adapted)
    changed = [row for row in adapted if row["changed"]]
    _write_jsonl(changed_jsonl, changed)
    _write_text_lines(all_txt, [str(row["adaptedText"]) for row in adapted])
    _write_text_lines(changed_txt, [str(row["adaptedText"]) for row in changed])
    _write_text_lines(
        gold_txt,
        [
            str(row["adaptedText"])
            for row in adapted
            if row.get("reviewLabel") == "gold"
        ],
    )
    _write_text_lines(
        maybe_txt,
        [
            str(row["adaptedText"])
            for row in adapted
            if row.get("reviewLabel") == "maybe"
        ],
    )

    rule_counts: dict[str, int] = {}
    for row in changed:
        for rule in row.get("rulesApplied") or []:
            rule_counts[str(rule)] = rule_counts.get(str(rule), 0) + 1
    summary = {
        "schema": "reference_factory.adapted_caption_summary.v1",
        "profile": {
            "name": profile.get("name"),
            "singular": profile.get("singular"),
            "plural": profile.get("plural"),
        },
        "total": len(adapted),
        "changed": len(changed),
        "unchanged": len(adapted) - len(changed),
        "byLabel": _count_by(adapted, "reviewLabel"),
        "changedByLabel": _count_by(changed, "reviewLabel"),
        "ruleCounts": dict(
            sorted(rule_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "outputs": {
            "allJsonl": str(all_jsonl),
            "changedJsonl": str(changed_jsonl),
            "allTxt": str(all_txt),
            "changedTxt": str(changed_txt),
            "goldTxt": str(gold_txt),
            "maybeTxt": str(maybe_txt),
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {**summary["outputs"], "summary": str(summary_path)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_text_lines(path: Path, values: list[str]) -> None:
    seen: set[str] = set()
    with path.open("w", encoding="utf-8") as f:
        for value in values:
            text = value.strip()
            key = re.sub(r"\s+", " ", text.lower())
            if not text or key in seen:
                continue
            seen.add(key)
            f.write(text + "\n---\n")


def _preserve_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _clean_spacing(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _dedupe_rules(rules: list[str]) -> list[str]:
    seen: set[str] = set()
    unique = []
    for rule in rules:
        if rule in seen:
            continue
        seen.add(rule)
        unique.append(rule)
    return unique


def _count_by(rows: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unlabeled")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
