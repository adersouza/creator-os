"""Review-first caption intake for Reel Factory overlay hooks."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from caption_bank import (
    DEFAULT_EXCLUDED_BANKS,
    CaptionBankStore,
    caption_hash,
    classify_caption,
)
from discoverability_safety import discoverability_safe_content_contract

from .fileops import atomic_write_text

CANDIDATE_SCHEMA = "reel_factory.caption_candidate_intake.v1"
INVENTORY_SCHEMA = "reel_factory.caption_source_inventory.v1"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
PRODUCER_KEY = re.compile(
    r"(^|\.)(rawCaptionText|caption_text|captionText|overlayText|overlay_text|"
    r"hookText|hook_text|captionLineage\.rawCaptionText|"
    r"captionBank\.rawCaptionText|captionOutcomeContext\.caption_text|caption\.text)$"
)
INVENTORY_TEXT_KEY = re.compile(
    r"(^|\.)(text|caption|captionText|caption_text|rawCaptionText|raw_caption|"
    r"normalizedCaption|normalized_caption|overlay|overlayText|hook|postCaption)$",
    re.IGNORECASE,
)
SOURCE_META_KEYS = {
    "account",
    "handle",
    "username",
    "source",
    "source_url",
    "sourceUrl",
    "screenshot",
    "screenshotPath",
    "observedViewCount",
    "views",
    "likes",
    "comments",
    "archetype",
}
UI_NOISE_LINE = re.compile(
    r"^(?:follow|following|reels|friends|posts|reply|replies|videos|photos|home|search|"
    r"liked by|view all|add comment|use template|made with edits|try licensed music|lte|"
    r"\d{1,2}:\d{2}|[0-9,.]+[kKmM]?)$",
    re.IGNORECASE,
)
RACE_OR_PERSONA_PATTERN = re.compile(
    r"\b(?:black|asian|korean|latina|hispanic|mexican|brazilian|blonde|redhead|ginger|"
    r"trans|tranny|femboy|goth girl|emo girl|freckle girl)\b",
    re.IGNORECASE,
)
GENERATED_SEED_PATTERN = re.compile(
    r"generated_seed|seed-topics|synthetic", re.IGNORECASE
)


def scan_local(root: Path, *, include_seed: bool = False) -> dict[str, Any]:
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

    return _write_candidates(
        reel_root, candidates.values(), rejected=rejected, command="scan-local"
    )


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

    return _write_candidates(
        reel_root, candidates.values(), rejected=rejected, command="ocr"
    )


def import_external(root: Path, source_path: Path) -> dict[str, Any]:
    reel_root = _reel_root(root)
    source_path = Path(source_path).resolve()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_label = str(payload.get("source") or source_path.stem)
    existing = _existing_keys(reel_root)
    candidates: dict[str, dict[str, Any]] = {}

    for row in _current_candidate_rows(reel_root):
        text = str(row.get("text") or "")
        h = str(row.get("caption_hash") or caption_hash(text))
        row["caption_hash"] = h
        candidates[h] = row
        existing.update({h, _caption_key(text)})

    added = 0
    rejected = 0
    rejected_samples: list[dict[str, Any]] = []
    rows = payload.get("captions") if isinstance(payload.get("captions"), list) else []
    for index, item in enumerate(rows, 1):
        if isinstance(item, str):
            text = item
            metadata: dict[str, Any] = {}
        elif isinstance(item, dict):
            text = str(item.get("text") or "")
            metadata = {
                "externalSource": {
                    key: item[key]
                    for key in (
                        "account",
                        "source_url",
                        "screenshot",
                        "observedViewCount",
                        "archetype",
                        "postCaption",
                    )
                    if item.get(key) not in (None, "")
                }
            }
            if item.get("archetype"):
                metadata["archetype"] = item["archetype"]
        else:
            rejected += 1
            continue
        source = f"{source_label}:{source_path.name}:{index}"
        if _add_candidate(
            candidates,
            text,
            source,
            existing,
            metadata=metadata,
            allow_excluded_review_only=True,
        ):
            added += 1
            existing.update({caption_hash(text), _caption_key(text)})
        else:
            rejected += 1
            if len(rejected_samples) < 12:
                rejected_samples.append(
                    {"index": index, "text": _clean_caption(text)[:180]}
                )

    return _write_candidates(
        reel_root,
        candidates.values(),
        rejected=rejected,
        command="import-external",
        extras={
            "importedSourceFile": str(source_path),
            "importedSource": source_label,
            "importedAt": int(time.time()),
            "added_count": added,
            "import_rejected_count": rejected,
            "rejectedSamples": rejected_samples,
        },
    )


def build_inventory(root: Path, *, stamp: str | None = None) -> dict[str, Any]:
    """Build the authoritative review-only caption source inventory.

    This intentionally does not promote anything into live caption banks. It
    consolidates local harvest files, quarantines bad/generated material, and
    writes only clean review candidates into candidate_intake.json.
    """
    reel_root = _reel_root(root)
    stamp = stamp or time.strftime("%Y%m%d")
    existing = _existing_keys(reel_root)
    current = _current_candidate_rows(reel_root)
    candidates: dict[str, dict[str, Any]] = {}
    for row in current:
        if _is_generated_seed_source(str(row.get("source") or "")):
            continue
        text = str(row.get("text") or "")
        h = str(row.get("caption_hash") or caption_hash(text))
        row["caption_hash"] = h
        candidates[h] = row
        existing.update({h, _caption_key(text)})

    raw_rows = list(_inventory_source_rows(reel_root))
    inventory_by_key: dict[str, dict[str, Any]] = {}
    adaptations_by_key: dict[str, dict[str, Any]] = {}
    quarantine_by_key: dict[str, dict[str, Any]] = {}
    accounts: dict[str, dict[str, Any]] = _inventory_account_probes(reel_root)
    accepted = 0
    adapted = 0

    for raw in raw_rows:
        text = _clean_caption(raw.get("text"))
        if not _candidate_text(text):
            continue
        source = str(raw.get("source") or "")
        source_label = str(raw.get("sourceLabel") or "")
        account = _clean_account(
            raw.get("account") or raw.get("handle") or raw.get("username")
        )
        if account:
            account_row = accounts.setdefault(
                account, {"account": account, "sourceCount": 0}
            )
            account_row["sourceCount"] = int(account_row.get("sourceCount") or 0) + 1
            account_row["status"] = "local_capture_available"
            account_row.setdefault("localStatus", "local_capture_available")

        issues = _caption_inventory_issues(text, f"{source} {source_label}")
        stacey_text, adaptation_issues = _stacey_adapted_caption(text)
        if stacey_text != text:
            adapted += 1
            issues = sorted(set(issues).union(adaptation_issues))

        contract = discoverability_safe_content_contract(stacey_text)
        if not contract["discoverabilitySafe"]:
            issues = sorted(set(issues).union({"unsafe"}))

        banks = classify_caption(stacey_text)
        row = {
            "caption_hash": caption_hash(stacey_text),
            "rawCaption": text,
            "normalizedCaption": stacey_text,
            "source": source,
            "sourceAccount": account or None,
            "sourceUrl": raw.get("source_url") or raw.get("sourceUrl"),
            "screenshot": raw.get("screenshot") or raw.get("screenshotPath"),
            "observedViews": raw.get("observedViewCount") or raw.get("views"),
            "observedLikes": raw.get("likes"),
            "observedComments": raw.get("comments"),
            "captionFamily": banks,
            "staceyFitRating": _stacey_fit_rating(stacey_text, issues, banks),
            "issues": issues,
            "timedSegments": _segments_for(stacey_text) if "\n" in stacey_text else [],
            "candidateStatus": "quarantined",
        }
        key = _caption_key(stacey_text)
        existing_row = inventory_by_key.get(key)
        if existing_row:
            existing_row.setdefault("additionalSources", []).append(
                {
                    k: row.get(k)
                    for k in ("source", "sourceAccount", "sourceUrl", "screenshot")
                    if row.get(k)
                }
            )
            continue
        inventory_by_key[key] = row

        if stacey_text != text:
            adaptations_by_key[key] = {
                "caption_hash": row["caption_hash"],
                "sourceAccount": account or None,
                "rawCaption": text,
                "staceyCaption": stacey_text,
                "preservedHookStructure": True,
                "issuesAddressed": adaptation_issues,
                "source": source,
            }

        hard_blocked = bool(
            {"generated_seed", "unsafe", "nonsense_ocr"}.intersection(issues)
        )
        if hard_blocked:
            quarantine_by_key[key] = row | {
                "quarantineReason": sorted(
                    {"generated_seed", "unsafe", "nonsense_ocr"}.intersection(issues)
                )
            }
            continue
        if row["caption_hash"] in candidates:
            row["candidateStatus"] = "accepted_for_review"
            continue

        metadata = {
            "externalSource": {
                "account": account,
                "source_url": row.get("sourceUrl"),
                "screenshot": row.get("screenshot"),
                "observedViewCount": row.get("observedViews"),
                "archetype": ",".join(banks),
            },
            "sourceInventory": {
                "schema": INVENTORY_SCHEMA,
                "stamp": stamp,
                "issues": issues,
                "staceyFitRating": row["staceyFitRating"],
                "rawCaption": text if stacey_text != text else None,
            },
        }
        if _add_candidate(
            candidates,
            stacey_text,
            f"inventory:{source}",
            existing,
            metadata=metadata,
            allow_excluded_review_only=True,
        ):
            accepted += 1
            row["candidateStatus"] = "accepted_for_review"
            existing.update({caption_hash(stacey_text), _caption_key(stacey_text)})
        else:
            row["candidateStatus"] = "deduped_or_review_rejected"

    out_dir = reel_root / "caption_banks"
    inventory_rows = sorted(
        inventory_by_key.values(),
        key=lambda item: (
            str(item.get("sourceAccount") or ""),
            item["normalizedCaption"],
        ),
    )
    quarantine_rows = sorted(
        quarantine_by_key.values(),
        key=lambda item: (
            str(item.get("sourceAccount") or ""),
            item["normalizedCaption"],
        ),
    )
    adaptation_rows = sorted(
        adaptations_by_key.values(),
        key=lambda item: (str(item.get("sourceAccount") or ""), item["staceyCaption"]),
    )
    accepted_for_review = sum(
        1
        for row in inventory_rows
        if row.get("candidateStatus") == "accepted_for_review"
    )

    inventory_json = out_dir / f"caption_source_inventory_{stamp}.json"
    inventory_csv = out_dir / f"caption_source_inventory_{stamp}.csv"
    adaptations_json = out_dir / "stacey_caption_adaptations.json"
    quarantine_json = out_dir / "bad_caption_quarantine.json"
    report_md = out_dir / f"caption_source_inventory_{stamp}_report.md"

    blocked_accounts = sorted(
        account["account"]
        for account in accounts.values()
        if account.get("liveStatus") == "blocked_or_unavailable"
    )
    successful_accounts = sorted(
        account["account"]
        for account in accounts.values()
        if account.get("liveStatus") != "blocked_or_unavailable"
    )

    inventory_payload = {
        "schema": INVENTORY_SCHEMA,
        "generatedAt": int(time.time()),
        "sourceRowsScanned": len(raw_rows),
        "uniqueCaptions": len(inventory_rows),
        "acceptedForReview": accepted_for_review,
        "adaptedForStacey": len(adaptation_rows),
        "quarantined": len(quarantine_rows),
        "accounts": sorted(accounts.values(), key=lambda item: item["account"]),
        "accountsSuccessfullyRevisited": successful_accounts,
        "accountsBlockedPrivateUnavailable": blocked_accounts,
        "captions": inventory_rows,
    }
    atomic_write_text(
        inventory_json,
        json.dumps(inventory_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_inventory_csv(inventory_csv, inventory_rows)
    atomic_write_text(
        adaptations_json,
        json.dumps(
            {
                "schema": "reel_factory.stacey_caption_adaptations.v1",
                "updatedAt": int(time.time()),
                "adaptationCount": len(adaptation_rows),
                "adaptations": adaptation_rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    atomic_write_text(
        quarantine_json,
        json.dumps(
            {
                "schema": "reel_factory.bad_caption_quarantine.v1",
                "updatedAt": int(time.time()),
                "quarantineCount": len(quarantine_rows),
                "captions": quarantine_rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_inventory_report(report_md, inventory_payload)

    intake = _write_candidates(
        reel_root,
        candidates.values(),
        rejected=len(quarantine_rows),
        command="build-inventory",
        extras={
            "sourceInventory": str(inventory_json),
            "sourceInventoryCsv": str(inventory_csv),
            "staceyAdaptations": str(adaptations_json),
            "badCaptionQuarantine": str(quarantine_json),
            "report": str(report_md),
            "acceptedForReviewFromInventory": accepted_for_review,
            "newlyAcceptedForReviewFromInventory": accepted,
            "quarantinedFromInventory": len(quarantine_rows),
            "liveBanksChanged": False,
        },
    )

    return {
        "schema": "reel_factory.caption_inventory_build_report.v1",
        "inventoryJson": str(inventory_json),
        "inventoryCsv": str(inventory_csv),
        "candidateIntake": intake["path"],
        "staceyAdaptations": str(adaptations_json),
        "badCaptionQuarantine": str(quarantine_json),
        "report": str(report_md),
        "sourceRowsScanned": len(raw_rows),
        "uniqueCaptions": len(inventory_rows),
        "acceptedForReview": accepted_for_review,
        "adaptedForStacey": len(adaptation_rows),
        "quarantined": len(quarantine_rows),
        "accountsSuccessfullyRevisited": successful_accounts,
        "accountsBlockedPrivateUnavailable": blocked_accounts,
        "wouldWriteLiveBanks": False,
    }


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
        if (
            not cleaned
            or h in existing
            or key in existing
            or not contract["discoverabilitySafe"]
        ):
            rejected.append(
                {
                    "text": cleaned,
                    "reason": "duplicate_or_unsafe",
                    "blockedTerms": contract.get("blockedTerms", []),
                }
            )
            continue
        existing.update({h, key})
        promoted.append(cleaned)

    sidecar = None
    if promoted:
        out_dir = reel_root / "01_captions"
        out_dir.mkdir(parents=True, exist_ok=True)
        sidecar = _next_sidecar_path(out_dir)
        atomic_write_text(
            sidecar,
            json.dumps({"hooks": promoted}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
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
        "Timed hooks omit explicit bands so placement.py can resolve lower_center/lower_center_alt from the actual video."
    )
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    review = reel_root / "caption_banks" / "candidate_intake_placement_review.md"
    _write_placement_review(review, rows)
    return {
        "schema": "reel_factory.caption_intake_placement_plan.v1",
        "candidateFile": str(path),
        "reviewFile": str(review),
        "planned": len(rows),
        "timedEligible": sum(
            1 for row in rows if row.get("placementIntent", {}).get("timedEligible")
        ),
    }


def swipe_review(
    root: Path,
    out_dir: Path | None = None,
    *,
    mode: str = "static",
    include_generated_seed: bool = False,
) -> dict[str, Any]:
    reel_root = _reel_root(root)
    candidate_path = reel_root / "caption_banks" / "candidate_intake.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    rows = (
        payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    )
    if not include_generated_seed:
        rows = [
            row
            for row in rows
            if not str(row.get("source") or "").startswith("generated_seed:")
        ]
    if mode not in {"static", "timed"}:
        raise ValueError("mode must be static or timed")
    if mode == "timed":
        rows = [
            row
            for row in rows
            if (
                row.get("hookVariants") or _hook_variants(str(row.get("text") or ""))
            ).get("timed")
        ]
    out_dir = Path(out_dir).resolve() if out_dir else reel_root / "caption_banks"
    out_dir.mkdir(parents=True, exist_ok=True)

    decisions = {
        "schema": "reel_factory.caption_swipe_decisions.v1",
        "reviewMode": mode,
        "sourceCandidateFile": str(candidate_path),
        "createdAt": int(time.time()),
        "count": len(rows),
        "items": [
            {
                "id": row.get("caption_hash") or str(index),
                "caption_hash": row.get("caption_hash"),
                "text": row.get("text"),
                "banks": row.get("banks") or [],
                "source": row.get("source"),
                "placementIntent": row.get("placementIntent")
                or _placement_intent(str(row.get("text") or "")),
                "hookVariants": row.get("hookVariants")
                or _hook_variants(str(row.get("text") or "")),
                "status": "pending",
                "approvedUse": [],
                "notes": "",
            }
            for index, row in enumerate(rows, 1)
        ],
    }

    json_path = out_dir / f"caption_{mode}_swipe_decisions.json"
    html_path = out_dir / f"caption_{mode}_swipe_review.html"
    atomic_write_text(
        json_path,
        json.dumps(decisions, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    atomic_write_text(html_path, _render_swipe_review_html(decisions), encoding="utf-8")
    return {
        "schema": "reel_factory.caption_swipe_review_result.v1",
        "count": len(rows),
        "boardPath": str(html_path),
        "decisionJsonPath": str(json_path),
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
    keys.update(_quarantined_caption_keys(reel_root))
    return keys


def _quarantined_caption_keys(reel_root: Path) -> set[str]:
    path = reel_root / "caption_banks" / "bad_caption_quarantine.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    rows = payload.get("captions")
    if not isinstance(rows, list):
        return set()
    keys: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(
            row.get("text") or row.get("normalizedCaption") or row.get("caption") or ""
        )
        h = str(row.get("caption_hash") or row.get("captionHash") or "")
        if text:
            keys.add(caption_hash(text))
            keys.add(_caption_key(text))
        if h:
            keys.add(h)
    return keys


def _write_candidates(
    reel_root: Path,
    rows: Iterable[dict[str, Any]],
    *,
    rejected: int,
    command: str,
    extras: dict[str, Any] | None = None,
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
    if extras:
        payload.update(extras)
    atomic_write_text(
        out, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload | {"path": str(out)}


def _current_candidate_rows(reel_root: Path) -> list[dict[str, Any]]:
    path = reel_root / "caption_banks" / "candidate_intake.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("candidates")
    return (
        [dict(row) for row in rows if isinstance(row, dict)]
        if isinstance(rows, list)
        else []
    )


def _add_candidate(
    candidates: dict[str, dict[str, Any]],
    text: str,
    source: str,
    existing: set[str],
    *,
    metadata: dict[str, Any] | None = None,
    allow_excluded_review_only: bool = False,
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
    excluded_banks = sorted(set(banks).intersection(DEFAULT_EXCLUDED_BANKS))
    excluded_only = set(banks).issubset(DEFAULT_EXCLUDED_BANKS)
    if excluded_only and (
        not allow_excluded_review_only
        or {"weird_generated_history", "winner_bank"}.intersection(excluded_banks)
    ):
        return False
    row = {
        "caption_hash": h,
        "text": cleaned,
        "banks": banks,
        "source": source,
        "status": "candidate",
        "placementIntent": _placement_intent(cleaned),
        "hookVariants": _hook_variants(cleaned),
    }
    if excluded_only:
        row["reviewOnlyReason"] = "sourced_excluded_bank_candidate"
        row["reviewOnlyExcludedBanks"] = excluded_banks
    if metadata:
        row.update(
            {
                key: value
                for key, value in metadata.items()
                if value not in (None, {}, [])
            }
        )
    candidates[h] = row
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
    if re.search(
        r"(schema|http|/Users/|\.mp4|\.png|\.json|blocked by|audit issue|\b\d{3,4}x\d{3,4}\b|#|remove the)",
        text,
        re.I,
    ):
        return False
    return bool(re.search(r"[a-zA-Z]", text))


def _clean_caption(text: Any) -> str:
    value = html.unescape(str(text or ""))
    value = value.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    value = value.replace(" / ", "\n")
    return re.sub(r"[ \t]+", " ", value.strip()).strip()


def _caption_key(text: str) -> str:
    return re.sub(
        r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _clean_caption(text).lower())
    ).strip()


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
                yield (
                    _clean_caption(
                        re.sub(r"<[^>]+>", " ", match.group(1)).split("·")[0]
                    ),
                    str(path),
                )


def _walk_producer_text(
    payload: Any, path: Path, key_path: str
) -> Iterable[tuple[str, str]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{key_path}.{key}" if key_path else str(key)
            if isinstance(value, str) and PRODUCER_KEY.search(child):
                yield (value, f"{path}:{child}")
            yield from _walk_producer_text(value, path, child)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _walk_producer_text(value, path, f"{key_path}[{index}]")


def _inventory_source_rows(reel_root: Path) -> Iterable[dict[str, Any]]:
    workspace = _workspace_root(reel_root)
    json_roots = [
        reel_root / "caption_banks" / "external_sources",
        workspace / "tmp",
    ]
    for base in json_roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.json")):
            if path.name in {
                "banks.json",
                "mixes.json",
                "performance.json",
                "candidate_intake.json",
            }:
                continue
            if path.stat().st_size > 20_000_000:
                continue
            path_text = str(path)
            if base == workspace / "tmp" and not (
                "caption_candidate_scan_" in path_text
                or "ig_caption_harvest_" in path_text
                or "ig_caption_account_harvest_" in path_text
            ):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, json.JSONDecodeError):
                continue
            yield from _walk_inventory_payload(payload, path, "")

    for base in (workspace / "tmp", reel_root / "caption_banks" / "external_sources"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.txt")):
            if path.stat().st_size > 2_000_000:
                continue
            if base == workspace / "tmp" and not (
                "ig_caption_harvest_" in str(path)
                or "caption_candidate_scan_" in str(path)
            ):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for index, caption in enumerate(_ocr_candidates(text), 1):
                yield {
                    "text": caption,
                    "source": f"{path}:ocr:{index}",
                    "account": _account_from_path(path),
                    "screenshot": str(path),
                }


def _inventory_account_probes(reel_root: Path) -> dict[str, dict[str, Any]]:
    workspace = _workspace_root(reel_root)
    probes: dict[str, dict[str, Any]] = {}
    for base in (
        workspace / "tmp",
        reel_root / "caption_banks" / "external_sources",
    ):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.json")):
            if path.stat().st_size > 20_000_000:
                continue
            if (
                "ig_caption_account_harvest_" not in str(path)
                and path.parent.name != "external_sources"
            ):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, json.JSONDecodeError):
                continue
            if not (
                isinstance(payload, dict)
                and (
                    payload.get("schema") == "reel_factory.ig_live_account_probe.v1"
                    or "ig_caption_account_harvest_" in str(path)
                )
            ):
                continue
            accounts = payload.get("accounts") if isinstance(payload, dict) else None
            if not isinstance(accounts, list):
                continue
            for item in accounts:
                if not isinstance(item, dict):
                    continue
                account = _clean_account(
                    item.get("handle") or item.get("account") or item.get("username")
                )
                if not account:
                    continue
                status = str(item.get("status") or "").lower()
                live_status = (
                    "blocked_or_unavailable"
                    if status
                    in {"blocked_or_unavailable", "blocked", "private", "unavailable"}
                    else "live_revisited"
                )
                existing = probes.setdefault(
                    account, {"account": account, "sourceCount": 0}
                )
                existing["liveStatus"] = live_status
                existing["status"] = existing.get("status") or live_status
                if item.get("profileUrl"):
                    existing["profileUrl"] = item["profileUrl"]
                if item.get("reelLinksVisible") is not None:
                    existing["reelLinksVisible"] = item["reelLinksVisible"]
                if item.get("notes"):
                    existing["notes"] = item["notes"]
                existing["probeSource"] = str(path)
    return probes


def _walk_inventory_payload(
    payload: Any,
    path: Path,
    key_path: str,
    inherited: dict[str, Any] | None = None,
) -> Iterable[dict[str, Any]]:
    inherited = inherited or {}
    if isinstance(payload, dict):
        local_meta = dict(inherited)
        for key, value in payload.items():
            if key in SOURCE_META_KEYS and value not in (None, "", [], {}):
                local_meta[key] = value
        for key, value in payload.items():
            child = f"{key_path}.{key}" if key_path else str(key)
            if isinstance(value, str) and INVENTORY_TEXT_KEY.search(child):
                yield {
                    **local_meta,
                    "text": value,
                    "source": f"{path}:{child}",
                    "sourceLabel": local_meta.get("source"),
                    "account": local_meta.get("account")
                    or local_meta.get("handle")
                    or local_meta.get("username")
                    or _account_from_path(path),
                }
            elif isinstance(value, list) and key.lower() in {
                "hooks",
                "captions",
                "texts",
            }:
                for index, item in enumerate(value):
                    if isinstance(item, str):
                        yield {
                            **local_meta,
                            "text": item,
                            "source": f"{path}:{child}[{index}]",
                            "sourceLabel": local_meta.get("source"),
                            "account": local_meta.get("account")
                            or local_meta.get("handle")
                            or local_meta.get("username")
                            or _account_from_path(path),
                        }
                    else:
                        yield from _walk_inventory_payload(
                            item, path, f"{child}[{index}]", local_meta
                        )
            else:
                yield from _walk_inventory_payload(value, path, child, local_meta)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _walk_inventory_payload(
                value, path, f"{key_path}[{index}]", inherited
            )


def _caption_inventory_issues(text: str, source: str) -> list[str]:
    issues: list[str] = []
    if _is_generated_seed_source(source):
        issues.append("generated_seed")
    if RACE_OR_PERSONA_PATTERN.search(text):
        issues.append("persona_or_race_specific")
    if len(text) > 110 or len(_segments_for(text)) > 3:
        issues.append("face_cover_risk")
    if _looks_like_ocr_noise(text):
        issues.append("nonsense_ocr")
    return sorted(set(issues))


def _is_generated_seed_source(source: str) -> bool:
    return bool(GENERATED_SEED_PATTERN.search(source))


def _looks_like_ocr_noise(text: str) -> bool:
    cleaned = _caption_key(text)
    if not cleaned:
        return True
    words = cleaned.split()
    if len(words) > 16:
        return True
    long_tokens = [word for word in words if len(word) >= 10]
    vowel_light = [
        word for word in long_tokens if len(re.findall(r"[aeiou]", word)) <= 2
    ]
    return len(vowel_light) >= 2


def _stacey_adapted_caption(text: str) -> tuple[str, list[str]]:
    replacements = {
        r"\bblack girl\b": "girl",
        r"\basian girl\b": "girl",
        r"\bkorean girl\b": "girl",
        r"\blatina\b": "girl",
        r"\bhispanic\b": "girl",
        r"\bmexican\b": "girl",
        r"\bbrazilian\b": "girl",
        r"\bblonde\b": "girl",
        r"\bredhead\b": "girl",
        r"\bginger\b": "girl",
        r"\bfreckle girl\b": "girl",
        r"\btrans\b": "girl",
        r"\btranny\b": "girl",
        r"\bfemboy\b": "girl",
        r"\bgoth girl\b": "girl",
        r"\bemo girl\b": "girl",
    }
    adapted = text
    for pattern, replacement in replacements.items():
        adapted = re.sub(pattern, replacement, adapted, flags=re.IGNORECASE)
    adapted = re.sub(r"\b(girl)\s+\1\b", r"\1", adapted, flags=re.IGNORECASE)
    adapted = re.sub(r"[ \t]+", " ", adapted).strip()
    issues = ["stacey_adapted_from_persona_specific"] if adapted != text else []
    return adapted, issues


def _stacey_fit_rating(text: str, issues: list[str], banks: list[str]) -> str:
    if {"unsafe", "generated_seed", "nonsense_ocr"}.intersection(issues):
        return "reject"
    if "face_cover_risk" in issues:
        return "review"
    if {
        "comment_bait",
        "boyfriend_bait",
        "body_attention",
        "shared_girl_next_door",
    }.intersection(banks):
        return "high"
    return "medium"


def _clean_account(value: Any) -> str | None:
    text = str(value or "").strip().lstrip("@")
    if not text:
        return None
    return re.sub(r"[^A-Za-z0-9._]+", "", text) or None


def _account_from_path(path: Path) -> str | None:
    blocked = {
        "json",
        "scan_results",
        "new_caption_candidates",
        "new_caption_candidates_deduped",
        "usable_new_caption_candidates",
        "producer_caption_candidates",
        "more_from_images_and_saved_jsons",
        "more_from_images_and_saved_jsons_clean_review",
        "more_from_images_and_saved_jsons_strict",
        "more_from_user_shared_screenshots",
        "more_ocr_needs_cleanup_candidates",
        "more_saved_jsons_safe_candidates",
        "creatoros",
        "developer",
        "reel_factory",
        "python_packages",
        "aderdesouza",
        "users",
    }
    for part in reversed(path.parts):
        raw = Path(part).stem if "." in part else part
        cleaned = _clean_account(raw.replace("_profile", "").replace("_reels", ""))
        lowered = cleaned.lower() if cleaned else ""
        if (
            cleaned
            and lowered not in blocked
            and not cleaned.startswith(
                ("caption", "instagram", "ig", "tmp", "screenshots", "external_sources")
            )
            and not re.search(r"_20\d{6}$", cleaned)
            and "candidate" not in cleaned
            and "saved_json" not in cleaned
        ):
            return cleaned
    return None


def _write_inventory_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "caption_hash",
        "sourceAccount",
        "normalizedCaption",
        "rawCaption",
        "captionFamily",
        "staceyFitRating",
        "issues",
        "observedViews",
        "observedLikes",
        "observedComments",
        "sourceUrl",
        "screenshot",
        "source",
        "candidateStatus",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(row.get(key), ensure_ascii=False)
                        if isinstance(row.get(key), (list, dict))
                        else row.get(key)
                    )
                    for key in fieldnames
                }
            )


def _write_inventory_report(path: Path, payload: dict[str, Any]) -> None:
    accounts = (
        payload.get("accounts") if isinstance(payload.get("accounts"), list) else []
    )
    blocked = (
        payload.get("accountsBlockedPrivateUnavailable")
        if isinstance(payload.get("accountsBlockedPrivateUnavailable"), list)
        else []
    )
    revisited = (
        payload.get("accountsSuccessfullyRevisited")
        if isinstance(payload.get("accountsSuccessfullyRevisited"), list)
        else []
    )
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Caption Source Inventory Report\n\n")
        handle.write(f"- source rows scanned: {payload['sourceRowsScanned']}\n")
        handle.write(f"- unique captions after dedupe: {payload['uniqueCaptions']}\n")
        handle.write(f"- accepted for review: {payload['acceptedForReview']}\n")
        handle.write(f"- adapted for Stacey: {payload['adaptedForStacey']}\n")
        handle.write(f"- quarantined: {payload['quarantined']}\n")
        handle.write(f"- accounts with local capture: {len(accounts)}\n\n")
        handle.write(f"- accounts successfully revisited: {len(revisited)}\n")
        handle.write(f"- accounts blocked/private/unavailable: {len(blocked)}\n\n")
        handle.write("## Accounts\n\n")
        for account in accounts:
            details = [
                f"{account['sourceCount']} local caption sources",
                str(account.get("status") or "unknown"),
            ]
            if account.get("liveStatus"):
                details.append(f"live={account['liveStatus']}")
            if account.get("reelLinksVisible") is not None:
                details.append(f"visible_reels={account['reelLinksVisible']}")
            handle.write(f"- {account['account']}: {', '.join(details)}\n")


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
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-ss",
                "1",
                "-i",
                str(path),
                "-frames:v",
                "1",
                str(frame),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _tesseract(frame) if frame.exists() else ""


def _ocr_candidates(text: str) -> Iterable[str]:
    lines = [_clean_caption(line) for line in text.splitlines() if _clean_caption(line)]
    lines = [line for line in lines if not UI_NOISE_LINE.match(line)]
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
        return [
            str(item.get("text") if isinstance(item, dict) else item)
            for item in payload
        ]
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            return [
                str(item.get("text"))
                for item in payload["items"]
                if isinstance(item, dict)
                and item.get("status") == "approved"
                and item.get("text")
            ]
        rows = payload.get("candidates") or payload.get("hooks") or []
        return [
            str(item.get("text") if isinstance(item, dict) else item) for item in rows
        ]
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
        "timedBandFamily": ["lower_center", "lower_center_alt"],
        "finalPlacement": "placement.py",
    }


def _hook_variants(text: str) -> dict[str, Any]:
    cleaned = _clean_caption(text)
    segments = _segments_for(cleaned)
    return {
        "static": cleaned,
        "timed": (
            {"segments": [{"text": segment} for segment in segments]}
            if len(segments) > 1
            else None
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
        handle.write(
            "- Timed: segment mode, no explicit segment bands; `placement.py` chooses safe lower-center movement.\n"
        )
        handle.write("- Background plate: false. Font: Instagram Sans Condensed.\n\n")
        for index, row in enumerate(rows, 1):
            timed = (row.get("hookVariants") or {}).get("timed")
            text = str(row.get("text") or "").replace("\n", " / ")
            handle.write(f"{index}. `{text}`\n")
            if timed:
                segments = " | ".join(segment["text"] for segment in timed["segments"])
                handle.write(f"   timed: `{segments}`\n")


def _render_swipe_review_html(decisions: dict[str, Any]) -> str:
    items = decisions.get("items") if isinstance(decisions.get("items"), list) else []
    mode = str(decisions.get("reviewMode") or "static")
    cards = "\n".join(
        _render_swipe_card(item, index, mode=mode) for index, item in enumerate(items)
    )
    data = json.dumps(decisions, ensure_ascii=True).replace("</", "<\\/")
    approve_label = "Approve timed" if mode == "timed" else "Approve static"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Caption Swipe Review</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; min-height: 100vh; background: #07070a; color: #f4f4f5; display: grid; grid-template-rows: auto 1fr; }}
    header {{ padding: 18px 20px; border-bottom: 1px solid #27272a; background: #0b0b0f; }}
    h1 {{ margin: 0 0 6px; font-size: 22px; }}
    .meta {{ color: #a1a1aa; font-size: 13px; }}
    main {{ display: grid; place-items: center; padding: 22px 22px 96px; }}
    .deck {{ width: min(760px, 100%); }}
    .card {{ display: none; border: 1px solid #34343d; border-radius: 22px; background: #111116; padding: 30px; min-height: 420px; box-shadow: 0 20px 60px rgba(0,0,0,.35); touch-action: pan-y; }}
    .card.active {{ display: grid; gap: 22px; align-content: center; }}
    .label {{ color: #a1a1aa; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; text-align: center; }}
    .caption {{ white-space: pre-wrap; text-align: center; font-family: "Instagram Sans Condensed", Impact, system-ui, sans-serif; font-size: clamp(42px, 6vw, 76px); line-height: .94; color: #fff; text-shadow: 0 4px 0 #000, 0 0 18px rgba(0,0,0,.85); overflow-wrap: anywhere; }}
    .chips, .controls {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }}
    .chip {{ border: 1px solid #3f3f46; border-radius: 999px; padding: 5px 9px; color: #d4d4d8; font-size: 12px; }}
    .beats {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }}
    .beat {{ border: 1px solid #52525b; border-radius: 12px; padding: 11px 14px; color: #fff; background: #18181b; font-size: 20px; font-weight: 700; }}
    .timed {{ color: #a1a1aa; text-align: center; font-size: 13px; }}
    .source {{ color: #71717a; font-size: 12px; overflow-wrap: anywhere; text-align: center; }}
    button {{ border: 1px solid #3f3f46; background: #18181b; color: #f4f4f5; border-radius: 999px; padding: 11px 15px; cursor: pointer; font: inherit; }}
    button.keep {{ background: #166534; border-color: #22c55e; }}
    button.reject {{ background: #7f1d1d; border-color: #ef4444; }}
    footer {{ position: fixed; left: 0; right: 0; bottom: 0; padding: 14px; background: rgba(7,7,10,.9); border-top: 1px solid #27272a; display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }}
    @media (max-width: 640px) {{ footer {{ position: static; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Caption Swipe Review · {html.escape(mode.title())}</h1>
    <div class="meta">Swipe or use keys: left = reject, right = approve {html.escape(mode)}. Download approved JSON and pass it to <code>caption_intake.py promote --approved</code>.</div>
    <div class="meta" id="progress"></div>
  </header>
  <main><section class="deck">{cards}</section></main>
  <footer>
    <button class="reject" id="reject">Reject</button>
    <button class="keep" id="approve">{html.escape(approve_label)}</button>
    <button id="skip">Skip</button>
    <button id="downloadApproved">Download approved JSON</button>
    <button id="downloadDecisions">Download decisions</button>
  </footer>
  <script type="application/json" id="data">{data}</script>
  <script>
    const key = "caption-swipe:" + location.pathname;
    const data = JSON.parse(localStorage.getItem(key) || document.getElementById("data").textContent);
    const reviewMode = data.reviewMode === "timed" ? "timed" : "normal";
    const cards = [...document.querySelectorAll(".card")];
    let index = Math.max(0, data.items.findIndex(item => item.status === "pending"));
    if (index < 0) index = 0;
    function save() {{ localStorage.setItem(key, JSON.stringify(data)); }}
    function show() {{
      cards.forEach((card, i) => card.classList.toggle("active", i === index));
      const done = data.items.filter(item => item.status !== "pending").length;
      document.getElementById("progress").textContent = `${{index + 1}}/${{data.items.length}} · ${{done}} reviewed`;
    }}
    function decide(status, uses) {{
      const item = data.items[index];
      if (!item) return;
      item.status = status;
      item.approvedUse = uses || [];
      save();
      if (index < data.items.length - 1) index += 1;
      show();
    }}
    function download(name, payload) {{
      const blob = new Blob([JSON.stringify(payload, null, 2) + "\\n"], {{type: "application/json"}});
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = name;
      link.click();
      URL.revokeObjectURL(link.href);
    }}
    document.getElementById("reject").onclick = () => decide("rejected", []);
    document.getElementById("approve").onclick = () => decide("approved", [reviewMode]);
    document.getElementById("skip").onclick = () => {{ if (index < data.items.length - 1) index += 1; show(); }};
    document.getElementById("downloadDecisions").onclick = () => download(`caption_${{data.reviewMode || "static"}}_swipe_decisions.reviewed.json`, data);
    document.getElementById("downloadApproved").onclick = () => download(`caption_${{data.reviewMode || "static"}}_swipe_approved.json`, {{
      schema: "reel_factory.caption_swipe_approved.v1",
      candidates: data.items.filter(item => item.status === "approved").map(item => ({{
        text: item.text,
        caption_hash: item.caption_hash,
        approvedUse: item.approvedUse,
        banks: item.banks,
        source: item.source
      }}))
    }});
    document.addEventListener("keydown", event => {{
      if (event.key === "ArrowLeft") decide("rejected", []);
      if (event.key === "ArrowRight" || event.key === "1" || event.key === "2" || event.key === "3") decide("approved", [reviewMode]);
    }});
    let startX = null;
    cards.forEach(card => {{
      card.addEventListener("pointerdown", event => startX = event.clientX);
      card.addEventListener("pointerup", event => {{
        if (startX == null) return;
        const dx = event.clientX - startX;
        startX = null;
        if (dx > 80) decide("approved", [reviewMode]);
        if (dx < -80) decide("rejected", []);
      }});
    }});
    show();
  </script>
</body>
</html>
"""


def _render_swipe_card(item: dict[str, Any], index: int, *, mode: str) -> str:
    text = str(item.get("text") or "")
    banks = " ".join(
        f'<span class="chip">{html.escape(str(bank))}</span>'
        for bank in item.get("banks") or []
    )
    timed = ((item.get("hookVariants") or {}).get("timed") or {}).get("segments") or []
    timed_lines = [
        str(segment.get("text") or "") for segment in timed if isinstance(segment, dict)
    ]
    beats = " ".join(
        f'<span class="beat">{html.escape(line)}</span>' for line in timed_lines
    )
    detail = (
        f'<div class="label">Timed beats</div><div class="beats">{beats}</div>'
        if mode == "timed"
        else '<div class="timed">Static review: one caption overlay.</div>'
    )
    return f"""<article class="card" data-index="{index}">
      <div class="label">Caption</div>
      <div class="caption">{html.escape(text)}</div>
      <div class="chips">{banks}</div>
      {detail}
      <div class="source">{html.escape(str(item.get("source") or ""))}</div>
    </article>"""


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
    parser.add_argument(
        "--root", default=".", help="repo root or python_packages/reel_factory"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan-local")
    scan.add_argument("--include-seed", action="store_true")

    ocr = sub.add_parser("ocr")
    ocr.add_argument("folder")

    external = sub.add_parser("import-external")
    external.add_argument("source")

    inventory = sub.add_parser("build-inventory")
    inventory.add_argument("--stamp")

    promote_cmd = sub.add_parser("promote")
    promote_cmd.add_argument("--approved", required=True)

    sub.add_parser("plan-placement")
    swipe = sub.add_parser("swipe-review")
    swipe.add_argument("--out-dir")
    swipe.add_argument("--mode", choices=["static", "timed"], default="static")
    swipe.add_argument("--include-generated-seed", action="store_true")

    args = parser.parse_args()
    if args.command == "scan-local":
        report = scan_local(Path(args.root), include_seed=args.include_seed)
    elif args.command == "ocr":
        report = ocr_folder(Path(args.root), Path(args.folder))
    elif args.command == "import-external":
        report = import_external(Path(args.root), Path(args.source))
    elif args.command == "build-inventory":
        report = build_inventory(Path(args.root), stamp=args.stamp)
    elif args.command == "plan-placement":
        report = plan_placement(Path(args.root))
    elif args.command == "swipe-review":
        report = swipe_review(
            Path(args.root),
            Path(args.out_dir) if args.out_dir else None,
            mode=args.mode,
            include_generated_seed=args.include_generated_seed,
        )
    else:
        report = promote(Path(args.root), Path(args.approved))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
