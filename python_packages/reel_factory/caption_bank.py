"""Reusable caption banks and creator-weighted caption selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ACTIVE_BANKS = [
    "shared_girl_next_door",
    "dm_follow_bait",
    "comment_bait",
    "choice_poll",
    "coded_fill_ins",
    "read_backwards_puzzle",
    "boyfriend_bait",
    "body_attention",
    "bedroom_mirror",
    "gym_body",
    "goth_dark_alt",
    "experimental_edge",
    "weird_generated_history",
    "winner_bank",
]

DEFAULT_EXCLUDED_BANKS = {
    "goth_dark_alt",
    "experimental_edge",
    "weird_generated_history",
    "winner_bank",
}


def caption_hash(text: str) -> str:
    normalized = " ".join((text or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def default_mixes() -> dict[str, dict[str, int]]:
    return {
        "Larissa": {
            "shared_girl_next_door": 30,
            "body_attention": 20,
            "bedroom_mirror": 20,
            "dm_follow_bait": 15,
            "comment_bait": 10,
            "choice_poll": 5,
        },
        "Stacey": {
            # Weighted from real posted-view outcomes (2026-06-30): cipher/acronym
            # fill-ins (42K/27K/12K), toxic-relatable boyfriend bait (30K), and
            # backwards-decode puzzles (11.5K) are the top drivers. winner_bank
            # holds the promoted proven-archetype captions (age-coded excluded).
            "winner_bank": 20,
            "coded_fill_ins": 18,
            "boyfriend_bait": 15,
            "read_backwards_puzzle": 13,
            "shared_girl_next_door": 10,
            "comment_bait": 10,
            "choice_poll": 7,
            "bedroom_mirror": 7,
        },
        "Lola": {
            "shared_girl_next_door": 25,
            "gym_body": 25,
            "body_attention": 20,
            "bedroom_mirror": 15,
            "dm_follow_bait": 10,
            "comment_bait": 5,
        },
    }


def empty_performance_payload() -> dict[str, Any]:
    return {
        "schema": "reel_factory.caption_performance.v1",
        "updated_at": None,
        "notes": "Manual-ready caption performance metadata keyed by caption_hash. Selection uses approvedWeights only when an operator writes them.",
        "approvedWeights": {"captionHashes": {}},
        "captions": {},
    }


def _hook_text(hook: Any) -> str:
    if isinstance(hook, str):
        return hook.strip()
    if isinstance(hook, dict):
        segments = hook.get("segments")
        if isinstance(segments, list):
            return "\n".join(
                str(seg.get("text", "")).strip()
                for seg in segments
                if isinstance(seg, dict) and str(seg.get("text", "")).strip()
            ).strip()
        return str(hook.get("text") or "").strip()
    return str(hook).strip()


def caption_static_metadata(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    words = re.findall(r"\b[\w']+\b", value)
    word_count = len(words)
    char_count = len(value)
    line_count = len(lines) or (1 if value else 0)
    lower = value.lower()

    if word_count <= 4 and line_count <= 2:
        length_class = "very_short"
    elif word_count <= 9 and line_count <= 3:
        length_class = "short"
    elif word_count <= 14 and line_count <= 5:
        length_class = "medium"
    else:
        length_class = "long"

    numbered = bool(re.search(r"(^|\n)\s*\d+[\).]", value))
    coded = any(
        token in lower
        for token in (
            "without",
            "replace",
            "swap",
            "fill in",
            "if you f my",
            "if you e my",
        )
    )
    puzzle = any(
        token in lower
        for token in (
            "backwards",
            "read every",
            "bottom to top",
            "third word",
            "fourth word",
        )
    )
    if numbered:
        format_class = "numbered_list"
    elif coded:
        format_class = "coded"
    elif puzzle:
        format_class = "puzzle"
    elif word_count > 22 or char_count > 120:
        format_class = "paragraph"
    elif line_count > 1:
        format_class = "multiline"
    else:
        format_class = "single_line"

    return {
        "word_count": word_count,
        "char_count": char_count,
        "line_count": line_count,
        "length_class": length_class,
        "format_class": format_class,
    }


def classify_caption(text: str, *, history_only: bool = False) -> list[str]:
    if history_only:
        return ["weird_generated_history"]
    value = f" {text.lower()} "
    banks: set[str] = set()

    def has_any(words: list[str]) -> bool:
        return any(word in value for word in words)

    if has_any(
        [
            "follow",
            "dm",
            "message",
            "send me",
            "send this",
            "account so small",
            "text me",
        ]
    ):
        banks.add("dm_follow_bait")
    if has_any(
        ["leave a", "drop a", "comment", "like ", "say hi", "heart", "respond", "reply"]
    ):
        banks.add("comment_bait")
    if has_any(
        [
            "choose",
            "pick",
            "options",
            "option",
            "which one",
            "rank",
            "order",
            "only pick",
        ]
    ):
        banks.add("choice_poll")
    if has_any(
        [
            "replace",
            "without",
            "swap",
            "fill in",
            "fill the blank",
            "if you f my",
            "if you e my",
        ]
    ):
        banks.add("coded_fill_ins")
    if has_any(
        [
            "backwards",
            "read every",
            "read this",
            "bottom to top",
            "third word",
            "fourth word",
        ]
    ):
        banks.add("read_backwards_puzzle")
    if has_any(
        [
            "boyfriend",
            "date",
            "dating",
            "crush",
            "relationship",
            "good boy",
            "nerd",
            "single",
            "wife",
            "girlfriend",
        ]
    ):
        banks.add("boyfriend_bait")
    if has_any(
        [
            "tits",
            "boobs",
            "cleavage",
            "ass",
            "butt",
            "kiss",
            "lips",
            "body",
            "curves",
            "legs",
            "thigh",
            "panties",
            "bra",
            "bikini",
            "strip",
            "make out",
            "bed",
        ]
    ):
        banks.add("body_attention")
    if has_any(
        ["bed", "mirror", "selfie", "room", "wake up", "bathroom", "in my bed", "sleep"]
    ):
        banks.add("bedroom_mirror")
    if has_any(
        [
            "gym",
            "coach",
            "workout",
            "leggings",
            "protein",
            "fitness",
            "squat",
            "gymgirl",
        ]
    ):
        banks.add("gym_body")
    if has_any(["goth", "dark", "black lipstick", "alt ", "emo", "depressed goth"]):
        banks.add("goth_dark_alt")

    default_fit = has_any(
        [
            "girl",
            "single",
            "date",
            "crush",
            "selfie",
            "mirror",
            "bed",
            "room",
            "type",
            "pretty",
        ]
    ) or bool(
        banks.intersection(
            {"dm_follow_bait", "comment_bait", "boyfriend_bait", "bedroom_mirror"}
        )
    )
    if default_fit and not banks.intersection({"goth_dark_alt"}):
        banks.add("shared_girl_next_door")

    if not banks:
        banks.add("experimental_edge")
    return sorted(banks, key=ACTIVE_BANKS.index)


@dataclass
class CaptionBankStore:
    banks: dict[str, list[dict[str, Any]]]
    mixes: dict[str, dict[str, int]]
    performance: dict[str, Any]
    version: str
    source_hash: str

    @classmethod
    def build(cls, root: Path) -> CaptionBankStore:
        root = Path(root).resolve()
        by_hash: dict[str, dict[str, Any]] = {}
        sidecar_hashes: set[str] = set()

        for path in sorted((root / "01_captions").glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for index, hook in enumerate(payload.get("hooks") or []):
                text = _hook_text(hook)
                if not text:
                    continue
                item = _caption_item(
                    text=text,
                    banks=classify_caption(text),
                    source_type="sidecar",
                    source_file=str(path.relative_to(root)),
                    source_clip=path.stem,
                    source_index=index,
                )
                _merge_item(by_hash, item)
                sidecar_hashes.add(item["caption_hash"])

        for text, source in _history_captions(root):
            h = caption_hash(text)
            if h in sidecar_hashes:
                continue
            item = _caption_item(
                text=text,
                banks=classify_caption(text, history_only=True),
                source_type=source,
                source_file=source,
                source_clip=None,
                source_index=None,
            )
            _merge_item(by_hash, item)

        banks = {bank: [] for bank in ACTIVE_BANKS}
        for item in sorted(
            by_hash.values(), key=lambda row: (row["source_type"], row["text"])
        ):
            for bank in item["banks"]:
                banks.setdefault(bank, []).append(item)
        banks["winner_bank"] = []

        source_hash = _source_hash(banks, default_mixes())
        return cls(
            banks=banks,
            mixes=default_mixes(),
            performance=empty_performance_payload(),
            version="caption_banks_v1",
            source_hash=source_hash,
        )

    @classmethod
    def from_root(cls, root: Path) -> CaptionBankStore:
        root = Path(root).resolve()
        base = root / "caption_banks"
        banks_payload = json.loads((base / "banks.json").read_text(encoding="utf-8"))
        mixes_payload = json.loads((base / "mixes.json").read_text(encoding="utf-8"))
        perf_path = base / "performance.json"
        performance = (
            json.loads(perf_path.read_text(encoding="utf-8"))
            if perf_path.exists()
            else empty_performance_payload()
        )
        return cls(
            banks=_hydrate_bank_metadata(banks_payload.get("banks") or {}),
            mixes=mixes_payload.get("mixes") or default_mixes(),
            performance=performance,
            version=banks_payload.get("version", "caption_banks_v1"),
            source_hash=banks_payload.get("source_hash")
            or _source_hash(
                banks_payload.get("banks") or {}, mixes_payload.get("mixes") or {}
            ),
        )

    def write(self, root: Path) -> None:
        root = Path(root).resolve()
        base = root / "caption_banks"
        base.mkdir(parents=True, exist_ok=True)
        source_hash = _source_hash(self.banks, self.mixes)
        self.source_hash = source_hash
        banks_payload = {
            "schema": "reel_factory.caption_banks.v1",
            "version": self.version,
            "source_hash": source_hash,
            "updated_at": int(time.time()),
            "banks": self.banks,
        }
        mixes_payload = {
            "schema": "reel_factory.caption_mixes.v1",
            "version": self.version,
            "source_hash": source_hash,
            "mixes": self.mixes,
        }
        (base / "banks.json").write_text(
            json.dumps(banks_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (base / "mixes.json").write_text(
            json.dumps(mixes_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if not (base / "performance.json").exists():
            (base / "performance.json").write_text(
                json.dumps(empty_performance_payload(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        readme = base / "README.md"
        if not readme.exists():
            readme.write_text(_readme_text(), encoding="utf-8")

    def all_items(self) -> list[dict[str, Any]]:
        seen: set[str] = set()
        items = []
        for bank in ACTIVE_BANKS:
            for item in self.banks.get(bank, []):
                h = item["caption_hash"]
                if h in seen:
                    continue
                seen.add(h)
                items.append(item)
        return items

    def bank_items(self, bank: str) -> list[dict[str, Any]]:
        return list(self.banks.get(bank, []))

    def resolve_mix(
        self, creator: str, *, limit: int | None = None, seed: int = 42
    ) -> list[dict[str, Any]]:
        mix = self.mixes.get(creator) or self.mixes.get(creator.capitalize())
        if not mix:
            raise ValueError(f"unknown caption mix: {creator}")
        return self._weighted_select(mix, limit=limit, seed=seed)

    def resolve_banks(
        self, banks: list[str], *, limit: int | None = None, seed: int = 42
    ) -> list[dict[str, Any]]:
        unknown = [bank for bank in banks if bank not in ACTIVE_BANKS]
        if unknown:
            raise ValueError(f"unknown caption bank(s): {', '.join(unknown)}")
        return self._weighted_select(
            {bank: 1 for bank in banks}, limit=limit, seed=seed
        )

    def lineage_for(
        self,
        item: dict[str, Any],
        *,
        selected_mix: str | None,
        selected_banks: list[str],
    ) -> dict[str, Any]:
        h = item["caption_hash"]
        return {
            "schema": "reel_factory.caption_lineage.v1",
            "captionHash": h,
            "rawCaptionText": item["text"],
            "sourceBanks": item.get("banks") or [],
            "selectedBanks": selected_banks,
            "selectedBankWeight": (
                self.mixes.get(selected_mix, {}).get(selected_banks[0])
                if selected_mix and selected_banks
                else None
            ),
            "selectedMix": selected_mix,
            "sourceFile": item.get("source_file"),
            "sourceType": item.get("source_type"),
            "sourceClip": item.get("source_clip"),
            "captionBankVersion": self.version,
            "captionBankSourceHash": self.source_hash,
            "wordCount": item.get("word_count"),
            "charCount": item.get("char_count"),
            "lineCount": item.get("line_count"),
            "lengthClass": item.get("length_class"),
            "formatClass": item.get("format_class"),
            "performanceSnapshot": (self.performance.get("captions") or {}).get(h),
            "weightSource": item.get("caption_weight_source") or "static",
            "outcomeWeight": item.get("outcome_weight"),
        }

    def _weighted_select(
        self, weights: dict[str, int], *, limit: int | None, seed: int
    ) -> list[dict[str, Any]]:
        usable_weights = {
            bank: int(weight)
            for bank, weight in weights.items()
            if int(weight) > 0 and self.banks.get(bank)
        }
        if not usable_weights:
            return []
        if limit is None:
            selected = []
            seen: set[str] = set()
            for bank in usable_weights:
                for item in self.banks.get(bank, []):
                    if item["caption_hash"] in seen:
                        continue
                    seen.add(item["caption_hash"])
                    selected.append({**item, "selected_banks": [bank]})
            return selected

        rng = random.Random(seed)
        selected = []
        seen: set[str] = set()
        bank_names = list(usable_weights)
        bank_weights = [usable_weights[bank] for bank in bank_names]
        max_unique = len(
            {
                item["caption_hash"]
                for bank in bank_names
                for item in self.banks.get(bank, [])
            }
        )
        target = min(limit, max_unique)
        attempts = 0
        while len(selected) < target and attempts < target * 100:
            attempts += 1
            bank = rng.choices(bank_names, weights=bank_weights, k=1)[0]
            item = self._weighted_bank_item(bank, rng)
            h = item["caption_hash"]
            if h in seen:
                continue
            seen.add(h)
            selected.append({**item, "selected_banks": [bank]})
        if len(selected) < target:
            for bank in bank_names:
                for item in self.banks[bank]:
                    h = item["caption_hash"]
                    if h in seen:
                        continue
                    seen.add(h)
                    selected.append({**item, "selected_banks": [bank]})
                    if len(selected) >= target:
                        break
                if len(selected) >= target:
                    break
        return selected

    def _approved_caption_weights(self) -> dict[str, float]:
        approved = (
            self.performance.get("approvedWeights")
            if isinstance(self.performance, dict)
            else {}
        )
        caption_hashes = (
            approved.get("captionHashes") if isinstance(approved, dict) else {}
        )
        if not isinstance(caption_hashes, dict):
            return {}
        out: dict[str, float] = {}
        for key, value in caption_hashes.items():
            try:
                out[str(key)] = max(0.05, float(value))
            except (TypeError, ValueError):
                continue
        return out

    def _weighted_bank_item(self, bank: str, rng: random.Random) -> dict[str, Any]:
        items = self.banks[bank]
        approved_weights = self._approved_caption_weights()
        if not approved_weights:
            return rng.choice(items)
        weights = [
            approved_weights.get(str(item.get("caption_hash")), 1.0) for item in items
        ]
        item = rng.choices(items, weights=weights, k=1)[0]
        weight = approved_weights.get(str(item.get("caption_hash")))
        if weight is None:
            return item
        return {
            **item,
            "caption_weight_source": "approved_outcome_weights",
            "outcome_weight": weight,
        }


def load_or_build_caption_bank_store(root: Path) -> CaptionBankStore:
    base = Path(root).resolve() / "caption_banks"
    if (base / "banks.json").exists() and (base / "mixes.json").exists():
        return CaptionBankStore.from_root(root)
    store = CaptionBankStore.build(root)
    return store


def _caption_item(
    *,
    text: str,
    banks: list[str],
    source_type: str,
    source_file: str,
    source_clip: str | None,
    source_index: int | None,
) -> dict[str, Any]:
    h = caption_hash(text)
    return {
        "caption_hash": h,
        "text": text,
        "banks": banks,
        **caption_static_metadata(text),
        "source_type": source_type,
        "source_file": source_file,
        "source_clip": source_clip,
        "source_index": source_index,
    }


def _hydrate_bank_metadata(
    banks: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    hydrated: dict[str, list[dict[str, Any]]] = {}
    for bank, items in banks.items():
        hydrated[bank] = []
        for item in items:
            if "length_class" in item and "format_class" in item:
                hydrated[bank].append(item)
                continue
            hydrated[bank].append(
                {**item, **caption_static_metadata(str(item.get("text") or ""))}
            )
    for bank in ACTIVE_BANKS:
        hydrated.setdefault(bank, [])
    return hydrated


def _merge_item(by_hash: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
    h = item["caption_hash"]
    existing = by_hash.get(h)
    if not existing:
        by_hash[h] = item
        return
    existing["banks"] = sorted(
        set(existing.get("banks", [])) | set(item.get("banks", [])),
        key=ACTIVE_BANKS.index,
    )
    sources = existing.setdefault("additional_sources", [])
    sources.append(
        {
            "source_type": item.get("source_type"),
            "source_file": item.get("source_file"),
            "source_clip": item.get("source_clip"),
            "source_index": item.get("source_index"),
        }
    )


def _history_captions(root: Path) -> list[tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    db_path = root / "manifest.sqlite"
    if db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            for (text,) in conn.execute(
                "SELECT DISTINCT caption_text FROM variations WHERE caption_text != ''"
            ):
                clean = str(text).strip()
                if clean:
                    rows[caption_hash(clean)] = (clean, "manifest.sqlite")
            conn.close()
        except Exception:
            pass
    json_path = root / "manifest.json"
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            for video in (payload.get("videos") or {}).values():
                for variation in video.get("variations") or []:
                    clean = str(variation.get("caption_text") or "").strip()
                    if clean:
                        rows.setdefault(caption_hash(clean), (clean, "manifest.json"))
        except Exception:
            pass
    return list(rows.values())


def _source_hash(banks: dict[str, list[dict[str, Any]]], mixes: dict[str, Any]) -> str:
    payload = {"banks": banks, "mixes": mixes}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _readme_text() -> str:
    return """# Caption Banks

Caption banks organize Reel Factory hooks for weighted rotation. They do not delete, censor, or suppress captions based on style.

- `banks.json` stores reusable caption banks with source metadata and bank membership.
- `mixes.json` stores creator-level weights for Larissa, Stacey, and Lola.
- `performance.json` is intentionally manual-ready scaffolding for future caption performance metadata keyed by `caption_hash`.
- `winner_bank` starts empty and is reserved for future manually promoted captions.

Default mixes target hot adult girl-next-door, mirror selfie, bedroom selfie, and body-forward content. Goth/dark/alt, experimental edge, weird generated history, and winner bank are selectable but off by default.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    store = CaptionBankStore.build(root)
    if args.write:
        store.write(root)
    print(
        json.dumps(
            {
                "schema": "reel_factory.caption_bank_summary.v1",
                "banks": {bank: len(items) for bank, items in store.banks.items()},
                "mixes": store.mixes,
                "source_hash": store.source_hash,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
