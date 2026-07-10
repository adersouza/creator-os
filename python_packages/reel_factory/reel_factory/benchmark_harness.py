#!/usr/bin/env python3
"""10-reel neutral-vs-enhanced visual direction benchmark harness.

This file plans and records benchmark runs. It does not introduce a new
generation service and does not change the final prompt contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from generate_assets import AssetGenerationPlan, dry_run, load_prompt

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

SCHEMA = "reel_factory.visual_direction_benchmark.v1"
DEFAULT_BENCHMARK_ID = "visual_direction_v1"
CONDITIONS = ("neutral", "enhanced")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def benchmark_dir(root: Path, benchmark_id: str = DEFAULT_BENCHMARK_ID) -> Path:
    return Path(root).resolve() / "project_data" / "benchmarks" / benchmark_id


def benchmark_plan_path(root: Path, benchmark_id: str = DEFAULT_BENCHMARK_ID) -> Path:
    return benchmark_dir(root, benchmark_id) / "benchmark_plan.json"


def benchmark_results_path(
    root: Path, benchmark_id: str = DEFAULT_BENCHMARK_ID
) -> Path:
    return benchmark_dir(root, benchmark_id) / "results.jsonl"


def _variant_plan(
    root: Path,
    *,
    reel_id: str,
    condition: str,
    reference_path: Path,
    prompt_json: Path,
    shared_motion_hash: str,
    creator: str | None,
    soul_name: str | None,
    soul_id: str | None,
    max_panels: int,
    benchmark_id: str,
) -> dict[str, Any]:
    stem = f"{reel_id}_{condition}_grid"
    plan = AssetGenerationPlan(
        prompt_json=prompt_json,
        stem=stem,
        reference=str(reference_path),
        soul_id=soul_id,
        soul_name=soul_name,
        start_image=None,
        out_dir=root
        / "project_data"
        / "generated_assets"
        / "benchmarks"
        / reel_id
        / condition,
        source_dir=root / "00_source_videos",
        campaign=f"benchmark:{benchmark_id}",
        creator=creator,
        image_mode="single",
        image_aspect_ratio="2:3",
        video_aspect_ratio="9:16",
    )
    planned = dry_run(plan, wait=True)
    crop_dir = (
        root
        / "project_data"
        / "generated_assets"
        / "start_images"
        / "benchmarks"
        / reel_id
        / condition
    )
    return {
        "condition": condition,
        "promptJsonPath": str(prompt_json),
        "gridStem": stem,
        "expectedGridImagePath": str(plan.out_dir / f"{stem}_soul_image.png"),
        "cropOutputDir": str(crop_dir),
        "panelAnimationStems": [
            f"{reel_id}_{condition}_panel_{idx:02d}_kling"
            for idx in range(1, max_panels + 1)
        ],
        "sharedMotionHash": shared_motion_hash,
        "dryRunCommands": planned["commands"],
        "lineagePath": planned["lineage_path"],
    }


def create_benchmark_plan(
    root: Path,
    reels: list[dict[str, Any]],
    *,
    benchmark_id: str = DEFAULT_BENCHMARK_ID,
    creator: str | None = "Stacey",
    soul_name: str | None = "Stacey",
    soul_id: str | None = None,
    max_panels: int = 6,
) -> dict[str, Any]:
    """Create a benchmark plan for real neutral/enhanced reel tests."""
    root = Path(root).resolve()
    if not reels:
        raise ValueError("at least one reel is required")
    if len(reels) > 20:
        raise ValueError("benchmark supports at most 20 reels per plan")
    out_path = benchmark_plan_path(root, benchmark_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    planned_reels: list[dict[str, Any]] = []
    for idx, reel in enumerate(reels, start=1):
        reel_id = str(reel.get("reel_id") or f"reel_{idx:03d}").strip()
        reference_path = Path(str(reel["reference_path"])).expanduser().resolve()
        neutral_prompt_json = (
            Path(str(reel["neutral_prompt_json"])).expanduser().resolve()
        )
        enhanced_prompt_json = (
            Path(str(reel["enhanced_prompt_json"])).expanduser().resolve()
        )
        neutral_prompt = load_prompt(neutral_prompt_json)
        enhanced_prompt = load_prompt(enhanced_prompt_json)
        if neutral_prompt.klingMotionPrompt != enhanced_prompt.klingMotionPrompt:
            raise ValueError(
                f"{reel_id} neutral/enhanced prompts must use the same klingMotionPrompt"
            )
        motion_hash = _sha256_text(neutral_prompt.klingMotionPrompt)
        variants = {
            "neutral": _variant_plan(
                root,
                reel_id=reel_id,
                condition="neutral",
                reference_path=reference_path,
                prompt_json=neutral_prompt_json,
                shared_motion_hash=motion_hash,
                creator=creator,
                soul_name=soul_name,
                soul_id=soul_id,
                max_panels=max_panels,
                benchmark_id=benchmark_id,
            ),
            "enhanced": _variant_plan(
                root,
                reel_id=reel_id,
                condition="enhanced",
                reference_path=reference_path,
                prompt_json=enhanced_prompt_json,
                shared_motion_hash=motion_hash,
                creator=creator,
                soul_name=soul_name,
                soul_id=soul_id,
                max_panels=max_panels,
                benchmark_id=benchmark_id,
            ),
        }
        planned_reels.append(
            {
                "reelId": reel_id,
                "referencePath": str(reference_path),
                "sharedKlingMotionPrompt": neutral_prompt.klingMotionPrompt,
                "sharedMotionHash": motion_hash,
                "variants": variants,
                "reviewFields": [
                    "winner",
                    "selectedPanels",
                    "scores",
                    "reason",
                    "notes",
                ],
            }
        )

    payload = {
        "schema": SCHEMA,
        "benchmarkId": benchmark_id,
        "createdAt": int(time.time()),
        "conditions": list(CONDITIONS),
        "maxPanels": max_panels,
        "creator": creator,
        "soulName": soul_name,
        "soulId": soul_id,
        "rules": {
            "finalPromptContract": ["higgsfieldGridPrompt", "klingMotionPrompt"],
            "compare": "neutral Higgsfield grid versus enhanced Grok visual direction grid",
            "motion": "same shared klingMotionPrompt for both conditions and every cropped panel",
            "identity": "Soul ID owns identity; benchmark prompt contracts contain no identity fields",
        },
        "reels": planned_reels,
    }
    atomic_write_text(
        out_path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"ok": True, "path": str(out_path), "benchmark": payload}


def record_benchmark_result(
    root: Path,
    *,
    benchmark_id: str,
    reel_id: str,
    winner: str,
    reason: str,
    selected_panels: dict[str, int] | None = None,
    scores: dict[str, int] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    if winner not in {"neutral", "enhanced", "tie", "reject_both"}:
        raise ValueError("winner must be neutral, enhanced, tie, or reject_both")
    path = benchmark_results_path(root, benchmark_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": SCHEMA + ".result",
        "benchmarkId": benchmark_id,
        "reelId": reel_id,
        "winner": winner,
        "reason": reason,
        "selectedPanels": selected_panels or {},
        "scores": scores or {},
        "notes": notes,
        "createdAt": int(time.time()),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "path": str(path), "result": row}


def _load_reels(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("reels")
    if not isinstance(data, list):
        raise ValueError("reel file must be a JSON list or object with reels")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init")
    init.add_argument("--root", type=Path, default=Path("."))
    init.add_argument("--reels-json", type=Path, required=True)
    init.add_argument("--benchmark-id", default=DEFAULT_BENCHMARK_ID)
    init.add_argument("--creator", default="Stacey")
    init.add_argument("--soul-name", default="Stacey")
    init.add_argument("--soul-id")
    init.add_argument("--max-panels", type=int, default=6)

    record = sub.add_parser("record")
    record.add_argument("--root", type=Path, default=Path("."))
    record.add_argument("--benchmark-id", default=DEFAULT_BENCHMARK_ID)
    record.add_argument("--reel-id", required=True)
    record.add_argument(
        "--winner", required=True, choices=["neutral", "enhanced", "tie", "reject_both"]
    )
    record.add_argument("--reason", required=True)
    record.add_argument("--selected-panels-json", default="{}")
    record.add_argument("--scores-json", default="{}")
    record.add_argument("--notes", default="")
    args = ap.parse_args()

    if args.cmd == "init":
        result = create_benchmark_plan(
            args.root,
            _load_reels(args.reels_json),
            benchmark_id=args.benchmark_id,
            creator=args.creator,
            soul_name=args.soul_name,
            soul_id=args.soul_id,
            max_panels=args.max_panels,
        )
    else:
        result = record_benchmark_result(
            args.root,
            benchmark_id=args.benchmark_id,
            reel_id=args.reel_id,
            winner=args.winner,
            reason=args.reason,
            selected_panels=json.loads(args.selected_panels_json),
            scores=json.loads(args.scores_json),
            notes=args.notes,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
