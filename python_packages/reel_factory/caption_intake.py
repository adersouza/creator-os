"""Review-first caption intake for Reel Factory overlay hooks."""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from caption_bank import CaptionBankStore, DEFAULT_EXCLUDED_BANKS, caption_hash, classify_caption
from discoverability_safety import discoverability_safe_content_contract


CANDIDATE_SCHEMA = "reel_factory.caption_candidate_intake.v1"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
PRODUCER_KEY = re.compile(
    r"(^|\.)(rawCaptionText|caption_text|captionText|overlayText|overlay_text|"
    r"hookText|hook_text|captionLineage\.rawCaptionText|"
    r"captionBank\.rawCaptionText|captionOutcomeContext\.caption_text|caption\.text)$"
)

TOPIC_EDGE_LEVEL = "edgier_safe"

TOPIC_CAPTION_SEEDS: list[dict[str, Any]] = [
    {"id": "spider_peter_parker", "topic": "spider hero", "propCue": "red-blue spider hero plush", "angleFamily": "fandom dating bait", "stance": "mask over normal guy", "timedSegments": ["every girl wants\nspider-man", "nobody wants\npeter parker"]},
    {"id": "spider_nice_guy", "topic": "spider hero", "propCue": "red-blue spider hero plush", "angleFamily": "nice guy bait", "stance": "against nice-guy cope", "timedSegments": ["he saved the city", "still got left on read"]},
    {"id": "spider_mask", "topic": "spider hero", "propCue": "red-blue spider hero plush", "angleFamily": "identity bait", "stance": "pro fantasy", "timedSegments": ["it's not the suit", "okay maybe it is"]},
    {"id": "bat_rich_red_flag", "topic": "bat hero", "propCue": "black bat hero plush", "angleFamily": "controversial dating take", "stance": "red flags win", "timedSegments": ["batman is just\na rich red flag", "and somehow\nthat works on me"]},
    {"id": "bat_never_texts", "topic": "bat hero", "propCue": "black bat hero plush", "angleFamily": "avoidant dating bait", "stance": "calling out fantasy", "timedSegments": ["girls say they\nwant batman", "then complain he\nnever texts back"]},
    {"id": "bat_trauma_hot", "topic": "bat hero", "propCue": "black bat hero plush", "angleFamily": "money versus trauma", "stance": "pro toxic fantasy", "timedSegments": ["trauma is not hot", "unless he has\na mansion"]},
    {"id": "ps5_broke", "topic": "gaming", "propCue": "white game-controller plush", "angleFamily": "provider bait", "stance": "girl buys console", "timedSegments": ["when he's broke", "so I buy him\na PS5"]},
    {"id": "ps5_xbox", "topic": "gaming", "propCue": "white game-controller plush", "angleFamily": "console war", "stance": "anti PS5", "timedSegments": ["cute controller", "sucks xbox is\nstill better"]},
    {"id": "ps5_press_x", "topic": "gaming", "propCue": "white game-controller plush", "angleFamily": "flirty game command", "stance": "comment bait", "timedSegments": ["press X", "if you'd fold"]},
    {"id": "anime_waifu", "topic": "anime mascot", "propCue": "yellow electric anime mascot plush", "angleFamily": "waifu bait", "stance": "pro delusion", "timedSegments": ["anime guys say\nwaifu", "then fold for\na real girl"]},
    {"id": "anime_sub_dub", "topic": "anime mascot", "propCue": "yellow electric anime mascot plush", "angleFamily": "sub versus dub", "stance": "fan war", "timedSegments": ["sub or dub?", "wrong answers\nget blocked"]},
    {"id": "anime_touch_grass", "topic": "anime mascot", "propCue": "yellow electric anime mascot plush", "angleFamily": "fanboy bait", "stance": "tease fanboys", "timedSegments": ["he said touch grass", "I brought\npikachu instead"]},
    {"id": "pirate_crew", "topic": "pirate anime", "propCue": "straw-hat pirate anime plush", "angleFamily": "crew bait", "stance": "join my side", "timedSegments": ["would you join\nmy crew", "or just stare\nat the captain?"]},
    {"id": "pirate_loyal", "topic": "pirate anime", "propCue": "straw-hat pirate anime plush", "angleFamily": "loyalty bait", "stance": "commitment test", "timedSegments": ["loyal like zoro", "or useless like\nmy ex?"]},
    {"id": "pirate_devil_fruit", "topic": "pirate anime", "propCue": "straw-hat pirate anime plush", "angleFamily": "power fantasy", "stance": "flirty test", "timedSegments": ["devil fruit power?", "making men\ncomment twice"]},
    {"id": "shark_bite", "topic": "shark plush", "propCue": "blue shark plush", "angleFamily": "cute danger", "stance": "bite back", "timedSegments": ["he said he bites", "I said same"]},
    {"id": "shark_soft_menace", "topic": "shark plush", "propCue": "blue shark plush", "angleFamily": "soft versus menace", "stance": "split identity", "timedSegments": ["soft girl era", "with shark\nbehavior"]},
    {"id": "shark_safe", "topic": "shark plush", "propCue": "blue shark plush", "angleFamily": "fake innocence", "stance": "not innocent", "timedSegments": ["looks harmless", "that's how\nI get you"]},
    {"id": "antihero_red_flag", "topic": "comic antihero", "propCue": "red-black antihero plush", "angleFamily": "red flag pride", "stance": "pro chaos", "timedSegments": ["red flag?", "I thought you\nliked those"]},
    {"id": "antihero_therapy", "topic": "comic antihero", "propCue": "red-black antihero plush", "angleFamily": "chaos bait", "stance": "anti therapy", "timedSegments": ["therapy is cute", "but have you tried\nbad decisions?"]},
    {"id": "antihero_good_girls", "topic": "comic antihero", "propCue": "red-black antihero plush", "angleFamily": "good girl bait", "stance": "subvert innocent", "timedSegments": ["good girls scare me", "I trust the ones\nwith problems"]},
    {"id": "church_pray", "topic": "patriotic religious", "propCue": "patriotic red-cap teddy with small cross necklace cue", "angleFamily": "church girl bait", "stance": "needs prayer", "timedSegments": ["church girl era", "pray for me\nquick"]},
    {"id": "church_sundress", "topic": "patriotic religious", "propCue": "patriotic red-cap teddy with small cross necklace cue", "angleFamily": "religion dating bait", "stance": "playful hypocrisy", "timedSegments": ["he wants a\nchurch girl", "until she dresses\nlike this"]},
    {"id": "patriot_comments", "topic": "patriotic religious", "propCue": "patriotic red-cap teddy with small cross necklace cue", "angleFamily": "comment war", "stance": "mild political bait", "timedSegments": ["this outfit starts\narguments", "good, comment\nfirst"]},
]

STACEY_TOPIC_PROMPTS: list[dict[str, str]] = [
    {"id": "car_dashboard_gamer", "setting": "car", "topicCue": "white game controller", "prompt": "Adult woman in her mid-20s, arm's-length front-facing portrait in a parked car at night, dashboard glow and warm streetlight, sharp face detail, natural skin texture, opaque low-cut fitted top, strong cleavage, controller held clearly near her chest, playful confident gaze, intimate private mood."},
    {"id": "car_red_racing_top", "setting": "car", "topicCue": "red racing-inspired fitted tee", "prompt": "Adult woman in her mid-20s, close front-facing car portrait at night, black leather passenger seat, warm parking-lot light, sharp face detail, fitted red racing-inspired opaque top with deep neckline, strong cleavage, confident smirk, centered face and chest framing."},
    {"id": "bed_spider_plush", "setting": "bed", "topicCue": "red-blue spider hero plush", "prompt": "Adult woman in her mid-20s, intimate bedroom portrait on pillows, warm bedside lamp, sharp face detail, opaque black low-cut top, strong cleavage, small red-blue spider hero plush held beside cheek and upper chest, flirty serious gaze, centered framing."},
    {"id": "bed_black_bat_plush", "setting": "bed", "topicCue": "black bat hero plush", "prompt": "Adult woman in her mid-20s, seated on bed in a dark cozy bedroom with a warm lamp, sharp face detail, opaque black deep-neckline top, strong cleavage, small black bat hero plush held separately near her shoulder, serious seductive expression, centered face and chest framing."},
    {"id": "bed_yellow_anime", "setting": "bed", "topicCue": "yellow electric anime mascot plush", "prompt": "Adult woman in her mid-20s, close bedroom portrait with warm lamp and soft pillows, sharp face detail, opaque fitted top with deep neckline, strong cleavage, small yellow electric anime mascot plush held near her cheek, playful teasing gaze, intimate framing."},
    {"id": "bathroom_vanity_antihero", "setting": "bathroom", "topicCue": "red-black antihero plush", "prompt": "Adult woman in her mid-20s, dim bathroom vanity portrait with warm mirror lights, sharp face detail, opaque fitted black top with deep neckline, strong cleavage, small red-black antihero plush held near her chest, confident mischievous expression, clean private setting."},
    {"id": "bathroom_black_dress_bat", "setting": "bathroom", "topicCue": "black bat hero plush", "prompt": "Adult woman in her mid-20s, private bathroom portrait near a vanity, warm light, sharp face detail, opaque black fitted dress with deep neckline, strong cleavage, tiny black bat hero plush visible in one hand, composed serious gaze, centered crop."},
    {"id": "private_doorway_shark", "setting": "private doorway", "topicCue": "blue shark plush", "prompt": "Adult woman in her mid-20s, intimate doorway portrait in a dark apartment hallway, warm room light behind her, sharp face detail, opaque low-cut top, strong cleavage, cute blue shark plush held against her shoulder and separate from body, playful smirk, centered framing."},
    {"id": "private_kitchen_church", "setting": "private kitchen", "topicCue": "small cross necklace", "prompt": "Adult woman in her mid-20s, private kitchen counter portrait at night, warm under-cabinet light, sharp face detail, opaque fitted white top with deep neckline, strong cleavage, small cross necklace visible, confident sweet-but-trouble expression, centered crop."},
    {"id": "gaming_room_ps5", "setting": "gaming room", "topicCue": "white controller", "prompt": "Adult woman in her mid-20s, cozy bedroom gaming corner portrait, soft monitor glow and warm lamp, sharp face detail, opaque fitted top with deep neckline, strong cleavage, white game controller held clearly near chest, teasing gamer-girl expression, clean background."},
    {"id": "sporty_gray_tank_shark", "setting": "bedroom", "topicCue": "blue shark plush", "prompt": "Adult woman in her mid-20s, close bedroom portrait, warm lamp, sharp face detail, opaque sporty gray tank with deep neckline, strong cleavage, blue shark plush near cheek, confident playful expression, centered face and chest framing."},
    {"id": "patriotic_teddy_bed", "setting": "bedroom", "topicCue": "patriotic teddy and cross necklace", "prompt": "Adult woman in her mid-20s, intimate bed portrait with warm bedside lamp, sharp face detail, opaque red fitted top with deep neckline, strong cleavage, small patriotic teddy and subtle cross necklace cue, playful controversial smirk, centered framing."},
]


def scan_local(root: Path, *, include_seed: bool = True) -> dict[str, Any]:
    reel_root = _reel_root(root)
    existing = _existing_keys(reel_root)
    candidates: dict[str, dict[str, Any]] = {}
    rejected = 0

    for text, source in _local_caption_strings(reel_root):
        if _add_candidate(candidates, text, source, existing):
            continue
        rejected += 1

    if include_seed:
        for index, text in enumerate(_seed_caption_texts()):
            if _add_candidate(candidates, text, f"generated_seed:{index}", existing):
                continue
            rejected += 1

    return _write_candidates(reel_root, candidates.values(), rejected=rejected, command="scan-local")


def ocr_folder(root: Path, folder: Path) -> dict[str, Any]:
    reel_root = _reel_root(root)
    existing = _existing_keys(reel_root)
    candidates: dict[str, dict[str, Any]] = {}
    rejected = 0
    folder = Path(folder).resolve()

    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            text = _tesseract(path)
        elif suffix in VIDEO_SUFFIXES:
            text = _ocr_video_frame(path)
        else:
            continue
        for value in _ocr_candidates(text):
            if _add_candidate(candidates, value, f"ocr:{path}", existing):
                continue
            rejected += 1

    return _write_candidates(reel_root, candidates.values(), rejected=rejected, command="ocr")


def promote(root: Path, approved_path: Path) -> dict[str, Any]:
    reel_root = _reel_root(root)
    existing = _existing_keys(reel_root)
    approved = _approved_texts(Path(approved_path))
    promoted: list[str] = []
    rejected: list[dict[str, Any]] = []

    for text in approved:
        cleaned = _clean_caption(text)
        h = caption_hash(cleaned)
        key = _caption_key(cleaned)
        contract = discoverability_safe_content_contract(cleaned)
        if not cleaned or h in existing or key in existing or not contract["discoverabilitySafe"]:
            rejected.append({
                "text": cleaned,
                "reason": "duplicate_or_unsafe",
                "blockedTerms": contract.get("blockedTerms", []),
            })
            continue
        existing.update({h, key})
        promoted.append(cleaned)

    sidecar = None
    if promoted:
        out_dir = reel_root / "01_captions"
        out_dir.mkdir(parents=True, exist_ok=True)
        sidecar = _next_sidecar_path(out_dir)
        sidecar.write_text(json.dumps({"hooks": promoted}, indent=2, ensure_ascii=False), encoding="utf-8")
        CaptionBankStore.build(reel_root).write(reel_root)

    return {
        "schema": "reel_factory.caption_intake_promote.v1",
        "approvedFile": str(Path(approved_path).resolve()),
        "promoted": len(promoted),
        "rejected": rejected,
        "sidecar": str(sidecar) if sidecar else None,
    }


def plan_placement(root: Path) -> dict[str, Any]:
    reel_root = _reel_root(root)
    path = reel_root / "caption_banks" / "candidate_intake.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("candidates") or []
    for row in rows:
        text = str(row.get("text") or "")
        row["placementIntent"] = _placement_intent(text)
        row["hookVariants"] = _hook_variants(text)
    payload["placementPlannedAt"] = int(time.time())
    payload["placementNotes"] = (
        "Stacey/Larissa overlay text uses stacey_static_center. Static hooks use lower_center. "
        "Timed hooks omit explicit bands so placement.py can resolve lower_center/center/lower_center_alt from the actual video."
    )
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    review = reel_root / "caption_banks" / "candidate_intake_placement_review.md"
    _write_placement_review(review, rows)
    return {
        "schema": "reel_factory.caption_intake_placement_plan.v1",
        "candidateFile": str(path),
        "reviewFile": str(review),
        "planned": len(rows),
        "timedEligible": sum(1 for row in rows if row.get("placementIntent", {}).get("timedEligible")),
    }


def seed_topics(root: Path) -> dict[str, Any]:
    reel_root = _reel_root(root)
    existing = _existing_keys(reel_root)
    preserved = _preserved_candidate_rows(reel_root)
    for row in preserved:
        text = str(row.get("text") or "")
        if text:
            existing.update({str(row.get("caption_hash") or caption_hash(text)), _caption_key(text)})
    candidates: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []

    for row in TOPIC_CAPTION_SEEDS:
        candidate = _topic_candidate(row, existing)
        if candidate is None:
            rejected.append({"id": row["id"], "text": _topic_text(row), "reason": "duplicate_or_unsafe"})
            continue
        candidates[candidate["caption_hash"]] = candidate
        existing.update({candidate["caption_hash"], _caption_key(candidate["text"])})

    payload = _write_candidates(reel_root, [*preserved, *candidates.values()], rejected=len(rejected), command="seed-topics")
    out_dir = reel_root / "caption_banks"
    pack_path = out_dir / "topic_caption_pack.json"
    review_path = out_dir / "candidate_intake_topic_review.md"
    prompt_json_path = out_dir / "stacey_topic_prompt_board.json"
    prompt_md_path = out_dir / "stacey_topic_prompt_board.md"
    _write_topic_caption_pack(pack_path, list(candidates.values()), rejected)
    _write_topic_review(review_path, list(candidates.values()), rejected)
    _write_prompt_board(prompt_json_path, prompt_md_path)
    return payload | {
        "schema": "reel_factory.caption_topic_seed.v1",
        "candidateCount": len(candidates),
        "totalCandidateCount": len(preserved) + len(candidates),
        "rejected": rejected,
        "wouldWriteLiveBanks": False,
        "topicCaptionPack": str(pack_path),
        "reviewFile": str(review_path),
        "promptBoardJson": str(prompt_json_path),
        "promptBoardMarkdown": str(prompt_md_path),
    }


def _preserved_candidate_rows(reel_root: Path) -> list[dict[str, Any]]:
    path = reel_root / "caption_banks" / "candidate_intake.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("candidates") or []
    return [
        row for row in rows
        if isinstance(row, dict)
        and not str(row.get("source") or "").startswith("generated_topic_seed:")
        and not row.get("topicSeedId")
    ]


def _reel_root(root: Path) -> Path:
    root = Path(root).resolve()
    nested = root / "python_packages" / "reel_factory"
    if (nested / "caption_bank.py").exists():
        return nested
    return root


def _workspace_root(reel_root: Path) -> Path:
    if reel_root.name == "reel_factory" and reel_root.parent.name == "python_packages":
        return reel_root.parent.parent
    return reel_root


def _existing_keys(reel_root: Path) -> set[str]:
    if (reel_root / "caption_banks" / "banks.json").exists():
        store = CaptionBankStore.from_root(reel_root)
    else:
        store = CaptionBankStore.build(reel_root)
    keys: set[str] = set()
    for item in store.all_items():
        text = str(item.get("text") or "")
        keys.add(str(item.get("caption_hash")))
        keys.add(_caption_key(text))
    return keys


def _write_candidates(
    reel_root: Path,
    rows: Iterable[dict[str, Any]],
    *,
    rejected: int,
    command: str,
) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: (row["source"], row["text"]))
    out = reel_root / "caption_banks" / "candidate_intake.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": CANDIDATE_SCHEMA,
        "updated_at": int(time.time()),
        "command": command,
        "candidate_count": len(rows),
        "rejected_count": rejected,
        "candidates": rows,
        "wouldWriteLiveBanks": False,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload | {"path": str(out)}


def _add_candidate(
    candidates: dict[str, dict[str, Any]],
    text: str,
    source: str,
    existing: set[str],
) -> bool:
    cleaned = _clean_caption(text)
    if not _candidate_text(cleaned):
        return False
    h = caption_hash(cleaned)
    key = _caption_key(cleaned)
    if h in existing or key in existing or h in candidates or key in candidates:
        return False
    contract = discoverability_safe_content_contract(cleaned)
    if not contract["discoverabilitySafe"]:
        return False
    banks = classify_caption(cleaned)
    if set(banks).issubset(DEFAULT_EXCLUDED_BANKS):
        return False
    candidates[h] = {
        "caption_hash": h,
        "text": cleaned,
        "banks": banks,
        "source": source,
        "status": "candidate",
        "placementIntent": _placement_intent(cleaned),
        "hookVariants": _hook_variants(cleaned),
    }
    return True


def _candidate_text(text: str) -> bool:
    if not (5 <= len(text) <= 140):
        return False
    if text.startswith("{") or text.startswith("["):
        return False
    if text.count('"') % 2:
        return False
    if " " not in text and not re.search(r"[?!]", text):
        return False
    if len(text.split()) > 18:
        return False
    if re.search(r"(schema|http|/Users/|\.mp4|\.png|\.json|blocked by|audit issue|\b\d{3,4}x\d{3,4}\b|#|remove the)", text, re.I):
        return False
    return bool(re.search(r"[a-zA-Z]", text))


def _topic_text(row: dict[str, Any]) -> str:
    return "\n".join(str(segment).strip() for segment in row["timedSegments"] if str(segment).strip())


def _topic_candidate(row: dict[str, Any], existing: set[str]) -> dict[str, Any] | None:
    text = _clean_caption(_topic_text(row))
    h = caption_hash(text)
    key = _caption_key(text)
    contract = discoverability_safe_content_contract(text)
    if not _candidate_text(text) or h in existing or key in existing or not contract["discoverabilitySafe"]:
        return None
    return {
        "caption_hash": h,
        "text": text,
        "banks": classify_caption(text),
        "source": f"generated_topic_seed:{row['id']}",
        "status": "candidate",
        "topicSeedId": row["id"],
        "topic": row["topic"],
        "propCue": row["propCue"],
        "angleFamily": row["angleFamily"],
        "stance": row["stance"],
        "edgeLevel": TOPIC_EDGE_LEVEL,
        "timedSegments": list(row["timedSegments"]),
        "placementIntent": _placement_intent(text),
        "hookVariants": {
            "static": text,
            "timed": {"segments": [{"text": segment} for segment in row["timedSegments"]]},
        },
    }


def _write_topic_caption_pack(path: Path, rows: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "reel_factory.topic_caption_pack.v1",
                "purpose": "review_only_topic_caption_candidates",
                "edgeLevel": TOPIC_EDGE_LEVEL,
                "rules": [
                    "candidate intake only; do not render or promote without approval",
                    "timed captions use stacey_static_center placement",
                    "regular Instagram Sans Condensed, no background plate",
                ],
                "count": len(rows),
                "rejected": rejected,
                "variants": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_topic_review(path: Path, rows: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Topic Caption Candidate Review\n\n")
        handle.write("- Status: review-only candidates; live banks are unchanged.\n")
        handle.write("- Placement: `stacey_static_center`, lower-center family, no background plate.\n")
        handle.write("- Font: Instagram Sans Condensed.\n")
        handle.write("- Edge: fandom/dating/gaming/religion bait without slurs, threats, or protected-class attacks.\n\n")
        for index, row in enumerate(rows, 1):
            segments = " | ".join(str(segment).replace("\n", " / ") for segment in row["timedSegments"])
            handle.write(f"{index}. **{row['topic']}** — {row['angleFamily']} / {row['stance']}\n")
            handle.write(f"   timed: `{segments}`\n")
            handle.write(f"   cue: {row['propCue']}\n\n")
        if rejected:
            handle.write("## Rejected\n\n")
            for row in rejected:
                handle.write(f"- `{row['id']}`: {row['reason']}\n")


def _write_prompt_board(json_path: Path, markdown_path: Path) -> None:
    payload = {
        "schema": "reel_factory.stacey_topic_prompt_board.v1",
        "soulId": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
        "rules": [
            "review prompts before generation",
            "use positive scene wording only",
            "use clean full-bleed camera portrait wording",
            "use sharp face detail and natural skin texture wording",
            "still prompt review only before any generation step",
        ],
        "items": STACEY_TOPIC_PROMPTS,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with markdown_path.open("w", encoding="utf-8") as handle:
        handle.write("# Stacey Topic Prompt Board\n\n")
        handle.write("Review-only still prompts. Do not animate, convert to MP4, or render captions from this board yet.\n\n")
        for index, row in enumerate(STACEY_TOPIC_PROMPTS, 1):
            handle.write(f"{index}. **{row['id']}** ({row['setting']}, {row['topicCue']})\n")
            handle.write(f"   {row['prompt']}\n\n")


def _clean_caption(text: Any) -> str:
    value = html.unescape(str(text or ""))
    value = value.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    value = value.replace(" / ", "\n")
    return re.sub(r"[ \t]+", " ", value.strip()).strip()


def _caption_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _clean_caption(text).lower())).strip()


def _local_caption_strings(reel_root: Path) -> Iterable[tuple[str, str]]:
    workspace = _workspace_root(reel_root)
    roots = [
        workspace / "tmp",
        workspace / "docs" / "examples",
        reel_root,
        workspace / "python_packages" / "campaign_factory",
    ]
    for base in roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.json")):
            if path.name == "candidate_intake.json" or path.stat().st_size > 20_000_000:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, json.JSONDecodeError):
                continue
            yield from _walk_producer_text(payload, path, "")

    for base in (workspace / "tmp", workspace / "docs" / "examples"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.html")):
            if path.stat().st_size > 20_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r'<div class="facts">(.*?)</div>', text, re.S):
                yield (_clean_caption(re.sub(r"<[^>]+>", " ", match.group(1)).split("·")[0]), str(path))


def _walk_producer_text(payload: Any, path: Path, key_path: str) -> Iterable[tuple[str, str]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{key_path}.{key}" if key_path else str(key)
            if isinstance(value, str) and PRODUCER_KEY.search(child):
                yield (value, f"{path}:{child}")
            yield from _walk_producer_text(value, path, child)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _walk_producer_text(value, path, f"{key_path}[{index}]")


def _tesseract(path: Path) -> str:
    proc = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "6"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _ocr_video_frame(path: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.png"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(path), "-frames:v", "1", str(frame)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _tesseract(frame) if frame.exists() else ""


def _ocr_candidates(text: str) -> Iterable[str]:
    lines = [_clean_caption(line) for line in text.splitlines() if _clean_caption(line)]
    yield from lines
    if 1 < len(lines) <= 4:
        yield "\n".join(lines)


def _approved_texts(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if isinstance(payload, list):
        return [str(item.get("text") if isinstance(item, dict) else item) for item in payload]
    if isinstance(payload, dict):
        rows = payload.get("candidates") or payload.get("hooks") or []
        return [str(item.get("text") if isinstance(item, dict) else item) for item in rows]
    return []


def _placement_intent(text: str) -> dict[str, Any]:
    segments = _segments_for(text)
    return {
        "schema": "reel_factory.caption_placement_intent.v1",
        "creatorStylePreset": "stacey_static_center",
        "fontFamily": "Instagram Sans Condensed",
        "style": "ig",
        "backgroundPlate": False,
        "staticBand": "lower_center",
        "timedEligible": len(segments) > 1,
        "timedPlacementMode": "segment",
        "timedBandFamily": ["lower_center", "center_if_safe", "lower_center_alt"],
        "finalPlacement": "placement.py",
    }


def _hook_variants(text: str) -> dict[str, Any]:
    cleaned = _clean_caption(text)
    segments = _segments_for(cleaned)
    return {
        "static": cleaned,
        "timed": (
            {"segments": [{"text": segment} for segment in segments]}
            if len(segments) > 1 else None
        ),
    }


def _segments_for(text: str) -> list[str]:
    lines = [line.strip() for line in _clean_caption(text).splitlines() if line.strip()]
    if len(lines) > 1:
        return lines[:4]
    value = lines[0] if lines else ""
    match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", value)
    if match and match.group(1).strip() and match.group(2).strip():
        return [match.group(1).strip(), match.group(2).strip()]
    if " or " in value.lower():
        parts = re.split(r"\s+or\s+", value, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2 and all(part.strip() for part in parts):
            return [parts[0].strip(), f"or {parts[1].strip()}"]
    words = value.split()
    if len(words) >= 5:
        mid = (len(words) + 1) // 2
        return [" ".join(words[:mid]), " ".join(words[mid:])]
    return [value] if value else []


def _write_placement_review(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Candidate Caption Placement Review\n\n")
        handle.write("- Static: lower_center through `stacey_static_center`.\n")
        handle.write("- Timed: segment mode, no explicit segment bands; `placement.py` chooses safe lower-center movement.\n")
        handle.write("- Background plate: false. Font: Instagram Sans Condensed.\n\n")
        for index, row in enumerate(rows, 1):
            timed = (row.get("hookVariants") or {}).get("timed")
            text = str(row.get("text") or "").replace("\n", " / ")
            handle.write(f"{index}. `{text}`\n")
            if timed:
                segments = " | ".join(segment["text"] for segment in timed["segments"])
                handle.write(f"   timed: `{segments}`\n")


def _next_sidecar_path(out_dir: Path) -> Path:
    stamp = time.strftime("%Y%m%d")
    path = out_dir / f"approved_intake_{stamp}.json"
    index = 1
    while path.exists():
        path = out_dir / f"approved_intake_{stamp}_{index}.json"
        index += 1
    return path


def _seed_caption_texts() -> list[str]:
    starts = [
        "be honest am I your type",
        "pick one for date night",
        "which outfit wins",
        "would you date me",
        "comment one word",
        "first thought when you see me",
        "wife or girlfriend energy",
        "sweet girl or trouble",
        "mirror selfie check",
        "pool day question",
    ]
    middles = [
        "sweet or dangerous",
        "angel energy or trouble",
        "soft girl or problem",
        "date night or stay home",
        "mirror selfie or beach day",
        "black outfit or white outfit",
        "pool day or bedroom mirror",
        "cute smile or serious face",
        "jeans or bikini",
        "sunlight or blue lights",
    ]
    ends = [
        "answer fast",
        "no lying",
        "one word only",
        "choose wisely",
        "I can tell",
        "say it nicely",
        "don't be shy",
        "prove me wrong",
        "you know the answer",
        "I'll wait",
    ]
    # ponytail: deterministic cartesian seed; replace with real performance winners after enough posts exist.
    return [f"{a}\n{b}\n{c}" for a in starts for b in middles for c in ends][:200]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root or python_packages/reel_factory")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan-local")
    scan.add_argument("--no-seed", action="store_true")

    ocr = sub.add_parser("ocr")
    ocr.add_argument("folder")

    promote_cmd = sub.add_parser("promote")
    promote_cmd.add_argument("--approved", required=True)

    sub.add_parser("plan-placement")
    sub.add_parser("seed-topics")

    args = parser.parse_args()
    if args.command == "scan-local":
        report = scan_local(Path(args.root), include_seed=not args.no_seed)
    elif args.command == "ocr":
        report = ocr_folder(Path(args.root), Path(args.folder))
    elif args.command == "plan-placement":
        report = plan_placement(Path(args.root))
    elif args.command == "seed-topics":
        report = seed_topics(Path(args.root))
    else:
        report = promote(Path(args.root), Path(args.approved))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
