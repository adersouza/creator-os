"""Thin campaign-scoped Reel Factory pipeline orchestrator.

This module coordinates the existing stage CLIs without publishing or scheduling.
The default mode is dry and resumable: it writes a run state file with commands,
discovers any already-produced local outputs, ranks candidates, writes an
approved-export draft, and dry-runs posting ledger assignment.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from campaign_store import campaign_by_name, connect, next_batch_plan
from export_approved import _load_generated_asset_lineage_sidecar
from posting_ledger import assign_approved_reels
from virality_select import rank_candidates

PIPELINE_SCHEMA = "reel_factory.pipeline_run.v1"
STAGES = (
    "next_batch",
    "prompt",
    "assets",
    "qc",
    "rank",
    "caption_render",
    "approved_export",
    "assign",
)


@dataclass(frozen=True)
class PipelineRunConfig:
    root: Path
    campaign: str
    creator: str
    count: int = 3
    run_id: str | None = None
    reference_image: Path | None = None
    reference_reel: Path | None = None
    caption_mix: str | None = None
    prompt_mode: str = "compiled"
    execute_commands: bool = False
    write_ledger: bool = False
    force_stages: set[str] = field(default_factory=set)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "run"


def pipeline_run_dir(root: Path, campaign: str, run_id: str) -> Path:
    return root / "project_data" / "pipeline_runs" / _slug(campaign) / run_id


def _default_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())


def _load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = int(time.time())
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _stage_done(state: dict[str, Any], stage: str, force: set[str]) -> bool:
    if stage in force:
        return False
    return (state.get("stages") or {}).get(stage, {}).get("status") in {
        "completed",
        "planned",
    }


def _command(root: Path, module: str, *args: str | Path) -> dict[str, Any]:
    return {
        "cwd": str(root),
        "argv": [
            "uv",
            "run",
            "--directory",
            str(root),
            "python",
            "-m",
            module,
            *[str(arg) for arg in args if str(arg) != ""],
        ],
    }


def _run_command(command: dict[str, Any]) -> dict[str, Any]:
    proc = subprocess.run(
        command["argv"],
        cwd=command["cwd"],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = {"stdout": proc.stdout.strip()}
    return {"ok": True, "result": parsed, "stderr": proc.stderr.strip()}


def _primary_reference(config: PipelineRunConfig) -> Path | None:
    return config.reference_image or config.reference_reel


def _prompt_command(
    config: PipelineRunConfig, prompt_path: Path, reference: Path
) -> dict[str, Any]:
    reference_flag = (
        "--reference-image" if config.reference_image else "--reference-reel"
    )
    return _command(
        config.root,
        "generate_prompts",
        "--root",
        config.root,
        reference_flag,
        reference,
        "--out",
        prompt_path,
        "--campaign",
        config.campaign,
        "--creator",
        config.creator,
        "--prompt-mode",
        config.prompt_mode,
        "--dry-run",
    )


def _asset_command(
    config: PipelineRunConfig, prompt_path: Path, stem: str, reference: Path
) -> dict[str, Any]:
    return _command(
        config.root,
        "generate_assets",
        "dry-run",
        "--root",
        config.root,
        "--prompt-json",
        prompt_path,
        "--stem",
        stem,
        "--reference",
        reference,
        "--campaign",
        config.campaign,
        "--creator",
        config.creator,
        "--out-dir",
        "00_source_videos",
    )


def _caption_render_command(
    config: PipelineRunConfig, recipes: list[str]
) -> dict[str, Any]:
    args: list[str | Path] = [
        "--root",
        config.root,
        "--campaign",
        config.campaign,
        "--caption-fit",
        "auto",
        "--caption-scene-fit",
        "auto",
        "--dry-run",
        "--per-clip",
        str(config.count),
    ]
    if config.caption_mix:
        args.extend(["--caption-mix", config.caption_mix])
    if recipes:
        args.extend(["--recipes", *recipes])
    return _command(config.root, "reel_pipeline", *args)


def _candidate_features(lineage: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(lineage, dict):
        return {}
    source = lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
    generation = (
        lineage.get("generation") if isinstance(lineage.get("generation"), dict) else {}
    )
    return {
        "creator": source.get("soulName") or generation.get("soulName") or "unknown",
        "scene": source.get("scene") or generation.get("scene") or "unknown",
        "pose": source.get("pose") or generation.get("pose") or "unknown",
        "motion": source.get("motion") or generation.get("motion") or "unknown",
        "outfit": source.get("outfit") or generation.get("outfit") or "unknown",
        "caption_style": generation.get("captionStyle") or "unknown",
    }


def discover_candidates(root: Path) -> list[dict[str, Any]]:
    candidates = []
    for output_path in sorted((root / "02_processed").glob("*.mp4")):
        lineage = _load_generated_asset_lineage_sidecar(output_path) or {}
        candidates.append(
            {
                "output_path": str(output_path),
                "features": _candidate_features(lineage),
                "generated_asset_lineage": lineage,
            }
        )
    return candidates


def write_approved_export(
    run_dir: Path, ranked: list[dict[str, Any]], *, limit: int
) -> Path | None:
    selected = [row for row in ranked if Path(str(row.get("output_path"))).exists()][
        :limit
    ]
    if not selected:
        return None
    payload = {
        "schema": "reel_factory.approved_export.v1",
        "exported_at": int(time.time()),
        "source": "pipeline_run",
        "count": len(selected),
        "items": [
            {
                "index": idx,
                "output_path": row["output_path"],
                "review_state": "approved",
                "generated_asset_lineage": row.get("generated_asset_lineage") or {},
                "pipeline_rank": {
                    "score": row.get("score"),
                    "predictedEngagement": row.get("predictedEngagement"),
                },
            }
            for idx, row in enumerate(selected)
        ],
    }
    path = run_dir / "approved_export.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _campaign_id(root: Path, campaign: str) -> str | None:
    conn = connect(root)
    try:
        return str(campaign_by_name(conn, campaign)["campaign_id"])
    except ValueError:
        return None
    finally:
        conn.close()


def run_pipeline(
    config: PipelineRunConfig,
    *,
    command_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = config.root.expanduser().resolve()
    run_id = config.run_id or _default_run_id()
    run_dir = pipeline_run_dir(root, config.campaign, run_id)
    state_path = run_dir / "pipeline_run.json"
    state = _load_state(state_path) or {
        "schema": PIPELINE_SCHEMA,
        "run_id": run_id,
        "campaign": config.campaign,
        "creator": config.creator,
        "created_at": int(time.time()),
        "stages": {},
    }
    state["run_dir"] = str(run_dir)
    state["dry_run"] = not config.execute_commands
    state["publishing"] = {"publish": False, "schedule": False}
    runner = command_runner or _run_command
    run_dir.mkdir(parents=True, exist_ok=True)

    if not _stage_done(state, "next_batch", config.force_stages):
        plan = next_batch_plan(root, campaign=config.campaign, count=config.count)
        state["next_batch"] = plan
        state["stages"]["next_batch"] = {
            "status": "completed",
            "ideas": len(plan.get("ideas") or []),
        }
        _write_state(state_path, state)

    reference = _primary_reference(config)
    ideas = (state.get("next_batch") or {}).get("ideas") or []
    prompt_dir = run_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_jobs = []
    asset_jobs = []
    recipes: list[str] = []
    for idea in ideas:
        idx = int(idea.get("index") or len(prompt_jobs))
        stem = f"{_slug(config.campaign)}_{run_id}_{idx:03d}"
        recipe = str(idea.get("recipe_hint") or "").strip()
        if recipe and recipe not in recipes:
            recipes.append(recipe)
        prompt_path = prompt_dir / f"{stem}.prompt.json"
        if reference:
            prompt_jobs.append(
                {
                    "idea_index": idx,
                    "stem": stem,
                    "prompt_path": str(prompt_path),
                    "command": _prompt_command(config, prompt_path, reference),
                }
            )
            asset_jobs.append(
                {
                    "idea_index": idx,
                    "stem": stem,
                    "lineage_path": str(
                        root
                        / "00_source_videos"
                        / f"{stem}.generated_asset_lineage.json"
                    ),
                    "command": _asset_command(config, prompt_path, stem, reference),
                }
            )

    if not _stage_done(state, "prompt", config.force_stages):
        stage = {"status": "planned", "jobs": prompt_jobs}
        if config.execute_commands and prompt_jobs:
            stage["results"] = [runner(job["command"]) for job in prompt_jobs]
            stage["status"] = "completed"
        state["stages"]["prompt"] = stage
        _write_state(state_path, state)

    if not _stage_done(state, "assets", config.force_stages):
        stage = {"status": "planned", "jobs": asset_jobs}
        if config.execute_commands and asset_jobs:
            stage["results"] = [runner(job["command"]) for job in asset_jobs]
            stage["status"] = "completed"
        state["stages"]["assets"] = stage
        _write_state(state_path, state)

    if not _stage_done(state, "qc", config.force_stages):
        existing_lineages = [
            job for job in asset_jobs if Path(str(job["lineage_path"])).exists()
        ]
        state["stages"]["qc"] = {
            "status": "waiting" if not existing_lineages else "planned",
            "lineages_ready": len(existing_lineages),
            "note": "run generated_image_qc on downloaded local image paths before approving assets",
        }
        _write_state(state_path, state)

    ranked: list[dict[str, Any]] = []
    if not _stage_done(state, "rank", config.force_stages):
        candidates = discover_candidates(root)
        ranked = rank_candidates(candidates, root) if candidates else []
        state["stages"]["rank"] = {
            "status": "completed" if ranked else "waiting",
            "candidates": len(candidates),
            "ranked": ranked,
        }
        _write_state(state_path, state)
    else:
        ranked = (state.get("stages") or {}).get("rank", {}).get("ranked") or []

    if not _stage_done(state, "caption_render", config.force_stages):
        command = _caption_render_command(config, recipes)
        state["stages"]["caption_render"] = {
            "status": "planned",
            "command": command,
            "recipes": recipes,
        }
        _write_state(state_path, state)

    approved_export: Path | None = None
    if not _stage_done(state, "approved_export", config.force_stages):
        approved_export = write_approved_export(run_dir, ranked, limit=config.count)
        state["stages"]["approved_export"] = {
            "status": "completed" if approved_export else "waiting",
            "path": str(approved_export) if approved_export else None,
            "items": len(ranked[: config.count]) if approved_export else 0,
        }
        _write_state(state_path, state)
    else:
        raw_path = (state.get("stages") or {}).get("approved_export", {}).get("path")
        approved_export = Path(raw_path) if raw_path else None

    if not _stage_done(state, "assign", config.force_stages):
        campaign_id = _campaign_id(root, config.campaign)
        if approved_export and campaign_id:
            assignment = assign_approved_reels(
                root,
                campaign_id=campaign_id,
                approved_export=approved_export,
                dry_run=not config.write_ledger,
            )
            status = "completed"
        else:
            assignment = None
            status = "waiting"
        state["stages"]["assign"] = {
            "status": status,
            "dry_run": not config.write_ledger,
            "campaign_id": campaign_id,
            "result": assignment,
        }
        _write_state(state_path, state)

    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--creator", required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--run-id")
    parser.add_argument("--reference-image", type=Path)
    parser.add_argument("--reference-reel", type=Path)
    parser.add_argument("--caption-mix")
    parser.add_argument("--prompt-mode", default="compiled")
    parser.add_argument("--execute-commands", action="store_true")
    parser.add_argument("--write-ledger", action="store_true")
    parser.add_argument("--force-stage", action="append", default=[])
    args = parser.parse_args(argv)
    if not args.reference_image and not args.reference_reel:
        raise SystemExit("--reference-image or --reference-reel is required")
    config = PipelineRunConfig(
        root=Path(args.root),
        campaign=args.campaign,
        creator=args.creator,
        count=args.count,
        run_id=args.run_id,
        reference_image=args.reference_image,
        reference_reel=args.reference_reel,
        caption_mix=args.caption_mix,
        prompt_mode=args.prompt_mode,
        execute_commands=args.execute_commands,
        write_ledger=args.write_ledger,
        force_stages=set(args.force_stage or []),
    )
    result = run_pipeline(config)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
