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

    args = parser.parse_args()
    if args.command == "scan-local":
        report = scan_local(Path(args.root), include_seed=not args.no_seed)
    elif args.command == "ocr":
        report = ocr_folder(Path(args.root), Path(args.folder))
    elif args.command == "plan-placement":
        report = plan_placement(Path(args.root))
    else:
        report = promote(Path(args.root), Path(args.approved))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
