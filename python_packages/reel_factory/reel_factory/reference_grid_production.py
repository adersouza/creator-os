#!/usr/bin/env python3
"""Run Grok-direct reference image grids through crop review only.

Boundary:
reference image -> Grok prompt -> Soul image grid -> cropped panels -> stop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from generate_assets import AssetGenerationPlan, create_image_asset
from generate_prompts import (
    JSON_STRUCTURED_RECREATION_MODE,
    generate_prompt,
    load_xai_api_key,
)
from grid_crop import crop_image_grid_panels
from PIL import Image, ImageDraw
from .fileops import atomic_write_text

DEFAULT_REFERENCE_ROOT = Path("/tmp/creator_os_reference_accounts")
DEFAULT_OUTPUT_ROOT = Path("output/reference_grok_grids_20260611")
SUMMARY_SCHEMA = "reel_factory.reference_grok_grid_production.v1"
XAI_MODELS_URL = "https://api.x.ai/v1/models"

CREATORS = {
    "Stacey": "5828d958-91dd-4d6d-8909-934503f47644",
    "Lola": "4c86c548-7aa5-4ad1-bc03-b94aa4ce8385",
    "Larissa": "44326567-b12c-410c-95b7-31891bb0629b",
}

PROFILES = {
    "six_4x3": {
        "image_aspect_ratio": "4:3",
        "grid_layout": "3x2",
        "columns": 3,
        "rows": 2,
    },
    "four_3x4": {
        "image_aspect_ratio": "3:4",
        "grid_layout": "2x2",
        "columns": 2,
        "rows": 2,
    },
    "four_4x3": {
        "image_aspect_ratio": "4:3",
        "grid_layout": "2x2",
        "columns": 2,
        "rows": 2,
    },
}

REFERENCE_TYPE_PROFILES = {
    "mirror_room": "six_4x3",
    "fitted_outfit": "six_4x3",
    "outdoor_lifestyle": "six_4x3",
    "unknown": "six_4x3",
}


@dataclass(frozen=True)
class ReferenceItem:
    username: str
    shortcode: str
    local_path: Path
    is_video: bool
    duplicate_of: str | None = None
    content_hash: str = ""
    reference_type: str = "unknown"

    @property
    def slug(self) -> str:
        name = f"{self.username}_{self.shortcode}".replace(".", "_")
        return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in name)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_reference_items(
    reference_root: Path,
) -> tuple[list[ReferenceItem], list[dict[str, Any]]]:
    items_path = reference_root / "items.json"
    data = json.loads(items_path.read_text(encoding="utf-8"))
    unique: list[ReferenceItem] = []
    duplicate_rows: list[dict[str, Any]] = []
    seen: dict[str, ReferenceItem] = {}
    for idx, row in enumerate(data, start=1):
        path = Path(row.get("local_path") or row.get("path") or "")
        if not path.exists():
            continue
        shortcode = str(row.get("shortcode") or row.get("id") or f"item_{idx:03d}")
        username = str(row.get("username") or "unknown")
        digest = sha256_file(path)
        dedupe_key = f"{shortcode}:{digest}"
        ref_type = classify_reference(username=username, shortcode=shortcode, index=idx)
        if dedupe_key in seen:
            duplicate_rows.append(
                {
                    "username": username,
                    "shortcode": shortcode,
                    "path": str(path),
                    "duplicateOf": seen[dedupe_key].slug,
                    "contentHash": digest,
                }
            )
            continue
        item = ReferenceItem(
            username=username,
            shortcode=shortcode,
            local_path=path,
            is_video=bool(row.get("is_video")),
            content_hash=digest,
            reference_type=ref_type,
        )
        seen[dedupe_key] = item
        unique.append(item)
    return unique, duplicate_rows


def classify_reference(*, username: str, shortcode: str, index: int) -> str:
    # Simple deterministic mapping for the current downloaded public reference set.
    if username == "reese.vuitton":
        return "outdoor_lifestyle"
    if username == "clomarol":
        return (
            "fitted_outfit" if index in {11, 12, 13, 14, 15, 16, 17} else "mirror_room"
        )
    if username == "alarahbelle":
        return "outdoor_lifestyle" if index in {4, 5, 6, 7, 8, 9} else "mirror_room"
    return "unknown"


def representative_references(items: list[ReferenceItem]) -> list[ReferenceItem]:
    selected: list[ReferenceItem] = []
    for ref_type in ("mirror_room", "fitted_outfit", "outdoor_lifestyle"):
        match = next((item for item in items if item.reference_type == ref_type), None)
        if match:
            selected.append(match)
    return selected


def prompt_creative_direction(item: ReferenceItem) -> str:
    return (
        "Use the reference image for scene, pose, camera angle, framing, outfit family, and lighting. "
        "Write in the approved Reference Factory sexy realistic voice with strong body-forward pose mechanics, "
        "garment cling, cleavage, tiny waist, wide hips, thick thighs, round ass, amateur iPhone realism, "
        "and exact room or outdoor context fidelity. Soul ID owns the identity."
    )


def safe_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def run_prompt(
    root: Path, item: ReferenceItem, creator: str, profile_name: str, job_dir: Path
) -> dict[str, Any]:
    profile = PROFILES[profile_name]
    prompt_path = job_dir / "prompt.json"
    lineage_path = prompt_path.with_suffix(prompt_path.suffix + ".lineage.json")
    existing = safe_json(lineage_path)
    if (
        prompt_path.exists()
        and existing
        and existing.get("prompt_mode") == JSON_STRUCTURED_RECREATION_MODE
    ):
        return {
            "ok": True,
            "skipped": True,
            "prompt_json_path": str(prompt_path),
            "lineage_path": str(lineage_path),
            "lineage": existing,
        }
    job_dir.mkdir(parents=True, exist_ok=True)
    return generate_prompt(
        out_path=prompt_path,
        root=root,
        reference_images=[item.local_path.resolve()],
        dry_run=True,
        prompt_mode=JSON_STRUCTURED_RECREATION_MODE,
        grid_layout=str(profile["grid_layout"]),
        image_aspect_ratio=str(profile["image_aspect_ratio"]),
        creative_direction=prompt_creative_direction(item),
        operator_notes=f"{creator} Grok-direct grid from {item.username}/{item.shortcode}",
    )


def run_image_grid(
    root: Path, item: ReferenceItem, creator: str, profile_name: str, job_dir: Path
) -> dict[str, Any]:
    prompt_path = job_dir / "prompt.json"
    stem = f"{creator.lower()}_{item.slug}_{profile_name}"
    lineage_path = job_dir / f"{stem}.generated_asset_lineage.json"
    existing = safe_json(lineage_path)
    if existing and ((existing.get("assets") or {}).get("localPaths") or {}).get(
        "image"
    ):
        return {
            "ok": True,
            "skipped": True,
            "path": str(lineage_path),
            "lineage": existing,
        }
    profile = PROFILES[profile_name]
    plan = AssetGenerationPlan(
        prompt_json=prompt_path.resolve(),
        stem=stem,
        reference=str(item.local_path.resolve()),
        soul_id=CREATORS[creator],
        soul_name=creator,
        start_image=None,
        out_dir=job_dir.resolve(),
        source_dir=job_dir.resolve(),
        image_aspect_ratio=str(profile["image_aspect_ratio"]),
        image_quality="2k",
        image_model="text2image_soul_v2",
        video_model="kling3_0",
    )
    return create_image_asset(plan, wait=True, download=True)


def run_crop(
    item: ReferenceItem,
    creator: str,
    profile_name: str,
    image_path: Path,
    job_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    crops_dir = job_dir / "crops"
    manifest_path = job_dir / "crop_manifest.json"
    existing = safe_json(manifest_path)
    if existing and existing.get("panelCrops") and not force:
        return existing
    manifest = crop_image_grid_panels(
        image_path=image_path,
        out_dir=crops_dir,
        smart=True,
        prefix=f"{creator.lower()}_{item.slug}_{profile_name}",
    )
    manifest["requestedProfile"] = {
        "name": profile_name,
        **PROFILES[profile_name],
    }
    atomic_write_text(manifest_path, 
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def ocr_text(path: Path) -> str:
    if not shutil.which("tesseract"):
        return ""
    try:
        raw = subprocess.check_output(
            ["tesseract", str(path), "stdout", "--psm", "6"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        )
    except Exception:
        return ""
    return "\n".join(line.strip() for line in raw.splitlines() if line.strip())


def build_contact_sheet(job_dir: Path, manifest: dict[str, Any]) -> Path:
    panels = manifest.get("panelCrops") or []
    thumbs: list[Image.Image] = []
    for panel in panels:
        path = Path(panel["path"])
        im = Image.open(path).convert("RGB")
        im.thumbnail((240, 320))
        tile = Image.new("RGB", (260, 360), "white")
        tile.paste(im, ((260 - im.width) // 2, 30))
        draw = ImageDraw.Draw(tile)
        draw.text((10, 8), f"panel {panel['panel']:02d}", fill=(0, 0, 0))
        thumbs.append(tile)
    if not thumbs:
        raise ValueError(f"no panels for contact sheet in {job_dir}")
    preset_columns = int(((manifest.get("gridPreset") or {}).get("columns")) or 3)
    columns = min(max(1, preset_columns), len(thumbs))
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 260, rows * 360), "white")
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((idx % columns) * 260, (idx // columns) * 360))
    out = job_dir / "panel_contact_sheet.jpg"
    sheet.save(out, quality=92)
    return out


def _fit_on_tile(path: Path, size: tuple[int, int], *, label: str) -> Image.Image:
    im = Image.open(path).convert("RGB")
    im.thumbnail((size[0] - 20, size[1] - 42))
    tile = Image.new("RGB", size, "white")
    tile.paste(im, ((size[0] - im.width) // 2, 34 + (size[1] - 42 - im.height) // 2))
    draw = ImageDraw.Draw(tile)
    draw.text((10, 10), label, fill=(0, 0, 0))
    return tile


def build_reference_comparison_sheet(
    job_dir: Path,
    reference_copy: Path,
    image_path: Path,
    manifest: dict[str, Any],
    review: dict[str, Any],
) -> Path:
    panels = manifest.get("panelCrops") or []
    grid_columns = int(((manifest.get("gridPreset") or {}).get("columns")) or 3)
    panel_tile = (240, 330)
    header_h = 460
    panel_rows = (len(panels) + grid_columns - 1) // grid_columns if panels else 0
    width = max(920, grid_columns * panel_tile[0])
    height = header_h + panel_rows * panel_tile[1] + 30
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 10), "Reference vs generated grid and smart crops", fill=(0, 0, 0))
    sheet.paste(
        _fit_on_tile(reference_copy, (300, 420), label="original reference"), (16, 36)
    )
    sheet.paste(
        _fit_on_tile(image_path, (width - 360, 420), label="generated grid"), (340, 36)
    )
    y0 = header_h
    by_panel = {
        int(item.get("panel") or 0): item for item in review.get("panels") or []
    }
    for idx, panel in enumerate(panels):
        panel_no = int(panel.get("panel") or idx + 1)
        x = (idx % grid_columns) * panel_tile[0]
        y = y0 + (idx // grid_columns) * panel_tile[1]
        status = (by_panel.get(panel_no) or {}).get("status") or "unknown"
        tile = _fit_on_tile(
            Path(panel["path"]), panel_tile, label=f"panel {panel_no:02d} - {status}"
        )
        sheet.paste(tile, (x, y))
    out = job_dir / "reference_comparison_sheet.jpg"
    sheet.save(out, quality=92)
    return out


def review_panels(manifest: dict[str, Any]) -> dict[str, Any]:
    panels = []
    accepted = 0
    review_required = 0
    rejected = 0
    for panel in manifest.get("panelCrops") or []:
        path = Path(panel["path"])
        text = ocr_text(path)
        flags = []
        status = "accepted"
        if text:
            flags.append("ocr_text_detected")
            status = "review_required"
        if manifest.get("reviewRequired"):
            flags.append("crop_review_required")
            status = "review_required"
        if not path.exists():
            flags.append("panel_missing")
            status = "rejected"
        if status == "accepted":
            accepted += 1
        elif status == "review_required":
            review_required += 1
        else:
            rejected += 1
        panels.append(
            {
                "panel": panel.get("panel"),
                "path": str(path),
                "status": status,
                "flags": flags,
                "ocrText": text,
            }
        )
    return {
        "acceptedPanels": accepted,
        "reviewRequiredPanels": review_required,
        "rejectedPanels": rejected,
        "panels": panels,
    }


def image_path_from_generation(result: dict[str, Any]) -> Path:
    image = (
        ((result.get("lineage") or {}).get("assets") or {}).get("localPaths") or {}
    ).get("image")
    if not image:
        raise ValueError("image grid generation did not produce a local image")
    return Path(image)


def run_one(
    root: Path,
    output_root: Path,
    item: ReferenceItem,
    creator: str,
    profile_name: str,
    *,
    force_recrop: bool = False,
) -> dict[str, Any]:
    job_dir = output_root / creator / item.slug / profile_name
    reference_copy = job_dir / f"reference{item.local_path.suffix.lower() or '.jpg'}"
    job_dir.mkdir(parents=True, exist_ok=True)
    if not reference_copy.exists():
        shutil.copy2(item.local_path, reference_copy)
    prompt = run_prompt(root, item, creator, profile_name, job_dir)
    generation = run_image_grid(root, item, creator, profile_name, job_dir)
    image_path = image_path_from_generation(generation)
    crop = run_crop(
        item, creator, profile_name, image_path, job_dir, force=force_recrop
    )
    review = review_panels(crop)
    contact_sheet = build_contact_sheet(job_dir, crop)
    comparison_sheet = build_reference_comparison_sheet(
        job_dir, reference_copy, image_path, crop, review
    )
    record = {
        "creator": creator,
        "reference": reference_record(item),
        "profile": profile_name,
        "jobDir": str(job_dir),
        "referenceCopy": str(reference_copy),
        "prompt": {
            "ok": bool(prompt.get("ok")),
            "skipped": bool(prompt.get("skipped")),
            "promptMode": ((prompt.get("lineage") or {}).get("prompt_mode")),
            "promptJsonPath": prompt.get("prompt_json_path")
            or str(job_dir / "prompt.json"),
            "lineagePath": prompt.get("lineage_path")
            or str(job_dir / "prompt.json.lineage.json"),
        },
        "generation": {
            "ok": bool(generation.get("ok")),
            "skipped": bool(generation.get("skipped")),
            "lineagePath": generation.get("path"),
            "imagePath": str(image_path),
        },
        "crop": {
            "manifestPath": str(job_dir / "crop_manifest.json"),
            "contactSheetPath": str(contact_sheet),
            "comparisonSheetPath": str(comparison_sheet),
            "panelCount": len(crop.get("panelCrops") or []),
            "reviewRequired": bool(crop.get("reviewRequired")),
            "confidence": crop.get("confidence"),
            "gridPreset": crop.get("gridPreset"),
            "requestedProfile": crop.get("requestedProfile"),
        },
        "review": review,
        "animated": 0,
        "scheduled": 0,
        "published": 0,
    }
    atomic_write_text((job_dir / "job_summary.json"), 
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return record


def recrop_one(
    output_root: Path, item: ReferenceItem, creator: str, profile_name: str
) -> dict[str, Any]:
    job_dir = output_root / creator / item.slug / profile_name
    existing = safe_json(job_dir / "job_summary.json")
    if not existing:
        raise FileNotFoundError(f"missing job summary for recrop: {job_dir}")
    image_path = Path(((existing.get("generation") or {}).get("imagePath")) or "")
    if not image_path.exists():
        raise FileNotFoundError(
            f"missing generated grid image for recrop: {image_path}"
        )
    reference_copy = Path(
        existing.get("referenceCopy")
        or (job_dir / f"reference{item.local_path.suffix.lower() or '.jpg'}")
    )
    if not reference_copy.exists():
        job_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.local_path, reference_copy)
    crop = run_crop(item, creator, profile_name, image_path, job_dir, force=True)
    review = review_panels(crop)
    contact_sheet = build_contact_sheet(job_dir, crop)
    comparison_sheet = build_reference_comparison_sheet(
        job_dir, reference_copy, image_path, crop, review
    )
    record = dict(existing)
    record["crop"] = {
        "manifestPath": str(job_dir / "crop_manifest.json"),
        "contactSheetPath": str(contact_sheet),
        "comparisonSheetPath": str(comparison_sheet),
        "panelCount": len(crop.get("panelCrops") or []),
        "reviewRequired": bool(crop.get("reviewRequired")),
        "confidence": crop.get("confidence"),
        "gridPreset": crop.get("gridPreset"),
        "requestedProfile": crop.get("requestedProfile"),
    }
    record["review"] = review
    record["animated"] = 0
    record["scheduled"] = 0
    record["published"] = 0
    atomic_write_text((job_dir / "job_summary.json"), 
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return record


def reference_record(item: ReferenceItem) -> dict[str, Any]:
    data = asdict(item)
    data["local_path"] = str(item.local_path)
    return data


def summarize(
    records: list[dict[str, Any]], duplicates: list[dict[str, Any]], output_root: Path
) -> dict[str, Any]:
    summary = {
        "schema": SUMMARY_SCHEMA,
        "createdAt": int(time.time()),
        "referencesProcessed": len({r["reference"]["content_hash"] for r in records}),
        "duplicateReferencesSkipped": len(duplicates),
        "creatorsProcessed": sorted({r["creator"] for r in records}),
        "gridsGenerated": sum(1 for r in records if r["generation"]["ok"]),
        "panelsCropped": sum(int(r["crop"]["panelCount"]) for r in records),
        "acceptedPanels": sum(int(r["review"]["acceptedPanels"]) for r in records),
        "reviewRequiredPanels": sum(
            int(r["review"]["reviewRequiredPanels"]) for r in records
        ),
        "rejectedPanels": sum(int(r["review"]["rejectedPanels"]) for r in records),
        "animated": 0,
        "scheduled": 0,
        "published": 0,
        "duplicates": duplicates,
        "records": records,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    atomic_write_text((output_root / "summary.json"), 
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def write_blocked_summary(
    output_root: Path,
    *,
    reason: str,
    detail: str,
    duplicates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    summary = {
        "schema": SUMMARY_SCHEMA,
        "createdAt": int(time.time()),
        "blocked": True,
        "blockingReason": reason,
        "blockingDetail": detail,
        "referencesProcessed": 0,
        "duplicateReferencesSkipped": len(duplicates or []),
        "creatorsProcessed": [],
        "gridsGenerated": 0,
        "panelsCropped": 0,
        "acceptedPanels": 0,
        "reviewRequiredPanels": 0,
        "rejectedPanels": 0,
        "animated": 0,
        "scheduled": 0,
        "published": 0,
        "duplicates": duplicates or [],
        "records": [],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    atomic_write_text((output_root / "summary.json"), 
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def check_xai_access(root: Path) -> dict[str, Any]:
    key = load_xai_api_key(root)
    if not key:
        return {
            "ok": False,
            "reason": "xai_api_key_missing",
            "detail": "XAI_API_KEY or project_data/secrets.toml xai_api_key is required.",
        }
    req = urllib.request.Request(
        XAI_MODELS_URL, headers={"Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "ok": True,
                "status": resp.status,
                "models": [
                    str(item.get("id")) for item in (data.get("data") or [])[:20]
                ],
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        return {
            "ok": False,
            "reason": "xai_api_unavailable",
            "status": exc.code,
            "detail": body,
        }
    except Exception as exc:
        return {
            "ok": False,
            "reason": "xai_api_unavailable",
            "detail": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--reference-root", type=Path, default=DEFAULT_REFERENCE_ROOT)
    ap.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    ap.add_argument(
        "--mode", choices=["calibration", "full", "recrop"], default="calibration"
    )
    ap.add_argument("--creators", nargs="+", default=list(CREATORS))
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-xai-preflight", action="store_true")
    ap.add_argument("--force-recrop", action="store_true")
    args = ap.parse_args()

    root = args.root.resolve()
    output_root = (
        (root / args.output_root).resolve()
        if not args.output_root.is_absolute()
        else args.output_root.resolve()
    )
    items, duplicates = load_reference_items(args.reference_root.resolve())
    if args.mode != "recrop" and not args.skip_xai_preflight:
        xai = check_xai_access(root)
        if not xai.get("ok"):
            print(
                json.dumps(
                    write_blocked_summary(
                        output_root,
                        reason=str(xai.get("reason") or "xai_api_unavailable"),
                        detail=str(xai.get("detail") or xai),
                        duplicates=duplicates,
                    ),
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 2
    if args.mode == "calibration":
        items = representative_references(items)
        profiles = args.profiles
    else:
        profiles = []
    if args.limit:
        items = items[: args.limit]

    records: list[dict[str, Any]] = []
    for item in items:
        for creator in args.creators:
            if creator not in CREATORS:
                raise ValueError(
                    f"unknown creator {creator!r}; expected one of {sorted(CREATORS)}"
                )
            run_profiles = profiles or [
                REFERENCE_TYPE_PROFILES.get(item.reference_type, "six_4x3")
            ]
            for profile_name in run_profiles:
                if profile_name not in PROFILES:
                    raise ValueError(
                        f"unknown profile {profile_name!r}; expected one of {sorted(PROFILES)}"
                    )
                if args.mode == "recrop":
                    records.append(recrop_one(output_root, item, creator, profile_name))
                else:
                    records.append(
                        run_one(
                            root,
                            output_root,
                            item,
                            creator,
                            profile_name,
                            force_recrop=args.force_recrop,
                        )
                    )
                summary = summarize(records, duplicates, output_root)
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "last": {
                                "creator": creator,
                                "reference": item.slug,
                                "profile": profile_name,
                                "acceptedPanels": records[-1]["review"][
                                    "acceptedPanels"
                                ],
                                "reviewRequiredPanels": records[-1]["review"][
                                    "reviewRequiredPanels"
                                ],
                                "contactSheetPath": records[-1]["crop"][
                                    "contactSheetPath"
                                ],
                                "comparisonSheetPath": records[-1]["crop"].get(
                                    "comparisonSheetPath"
                                ),
                                "gridPreset": records[-1]["crop"].get("gridPreset"),
                            },
                            "summary": {
                                k: summary[k]
                                for k in (
                                    "referencesProcessed",
                                    "gridsGenerated",
                                    "panelsCropped",
                                    "acceptedPanels",
                                    "reviewRequiredPanels",
                                    "rejectedPanels",
                                    "animated",
                                    "scheduled",
                                    "published",
                                )
                            },
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    print(
        json.dumps(
            summarize(records, duplicates, output_root), indent=2, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
