"""reel_gui.py — local web UI for the reel_factory pipeline.

Runs a FastAPI server on http://localhost:8765 with:
  - Drag-and-drop video upload (saves to 00_source_videos/)
  - Per-clip hook editor (with one-click "spin variations from base hook")
  - Full-bleed generation viewer with filtering by hook + recipe
  - Live pipeline run with streaming log
  - Account profile picker

Usage:
    python3 reel_gui.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent))
from hook_ai import OllamaHookProvider, generate_hooks  # noqa
from caption_generation_log import caption_library, rank_clip_sidecar  # noqa
from hook_tools import (
    embedding_status,
    find_near_duplicates,
    find_semantic_duplicates,
    read_hook_library,
    save_hook_to_library,
)  # noqa
from hook_spinner import spin_hooks  # noqa
from export_approved import export_approved  # noqa
from metrics_store import (
    import_metrics_csv,
    import_outcomes_csv,
    metrics_leaderboard,
    metrics_summary,
    outcomes_summary,
)  # noqa
from manifest import Manifest  # noqa
from project_config import load_config, save_config  # noqa
from preflight import check_clip_readiness  # noqa
from reel_pipeline import FFMPEG, FFPROBE  # noqa
from whisper_sync import transcribe_clip  # noqa
from thumbnail_gen import generate_thumbnails, thumbnail_path_for  # noqa
from audio_mux import audio_stream_count, mux_root  # noqa
from audio_intent import AUDIO_INTENT_MODES, read_audio_intent, write_audio_intent  # noqa
from local_api_auth import install_local_api_auth_middleware, require_local_api_auth  # noqa
from readiness_check import load_readiness_by_name, run_readiness  # noqa
from deprecated_generators import DeprecatedGeneratorError, guard_deprecated_generator  # noqa
from generate_assets import (  # noqa
    AssetGenerationPlan,
    DEFAULT_GRID_IMAGE_ASPECT_RATIO,
    DirectReferenceImagePlan,
    HiggsfieldCommandError,
    create_direct_reference_image_asset,
    create_image_asset,
    create_video_asset,
    dry_run as asset_dry_run,
    dry_run_direct_reference_image,
    load_prompt,
    probe_higgsfield_capabilities,
)
from generate_prompts import generate_prompt  # noqa
from reference_analyzer import analyze_reference  # noqa
from embedding_index import duplicate_risk, similar as similar_media  # noqa
from winner_dna import (
    account_fatigue_report,
    assign_experiment,
    baseline_vs_recommended_report,
    cost_analytics,
    decision_log,
    experiment_report,
    refresh_winner_dna,
    winner_dna_leaderboard,
)  # noqa
from reel_url_import import download_reel_url, write_url_sidecar  # noqa
from grid_crop import (
    build_crop_plan,
    crop_image_grid_panels,
    crop_plan_path,
    extract_frame,
    frame_path,
    infer_grid_preset,
    load_crop_plan,
    preset_boxes,
    preview_panel_image,
    render_plan as render_grid_crop_plan,
    save_crop_plan,
    validate_boxes,
)  # noqa
from campaign_store import (
    add_reference,
    campaign_leaderboard,
    connect as campaign_connect,
    create_campaign,
    get_asset_generation,
    link_campaign_output,
    list_campaigns,
    next_batch_plan,
    rate_output,
    update_asset_generation,
)  # noqa
from posting_ledger import (
    assign_approved_reels as ledger_assign_approved_reels,
    create_posting_plan,
    export_schedule_package as ledger_export_schedule_package,
    ledger_conflicts,
    review_queue as ledger_review_queue,
    transition_slot as ledger_transition_slot,
)  # noqa

ROOT = Path(__file__).parent.resolve()
RAW_DIR = ROOT / "00_source_videos"
CAP_DIR = ROOT / "01_captions"
PROC_DIR = ROOT / "02_processed"
ACCT_DIR = ROOT / "accounts"
DATA_DIR = ROOT / "project_data"
AUD_DIR = ROOT / "03_audio_library"
HOOK_LIBRARY = DATA_DIR / "hook_library.json"
SAFE_ZONE_DEFAULTS = {
    "top_pct": 14.6,
    "bottom_pct": 25.0,
    "left_pct": 5.0,
    "right_pct": 5.0,
    "source": "renderer_default_safe_margins",
}
_FFMPEG_FULL = Path("/opt/homebrew/opt/ffmpeg-full/bin")
STEM_RE = re.compile(r"^clip_\d{3,}$")

for d in (RAW_DIR, CAP_DIR, PROC_DIR, ACCT_DIR, DATA_DIR, AUD_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="reel_factory", dependencies=[Depends(require_local_api_auth)])
install_local_api_auth_middleware(app)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def guard_deprecated_generator_api(feature: str) -> None:
    try:
        guard_deprecated_generator(feature)
    except DeprecatedGeneratorError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc


_run_state: dict[str, Any] = {
    "running": False,
    "log": [],
    "started": 0.0,
    "finished": 0.0,
    "summary": None,
    "account": None,
    "completed": 0,
    "total": 0,
    "failed": 0,
}
_run_lock = threading.Lock()

# Auto-shutdown state. The browser tab sends a heartbeat every few seconds.
# If we don't see one for HEARTBEAT_TIMEOUT seconds (or get an explicit
# /api/shutdown ping from the tab's pagehide handler), the server exits.
HEARTBEAT_TIMEOUT = 15.0
_last_heartbeat = time.time()
_shutdown_requested = False
_auto_shutdown_enabled = False


def _safe_in_root(p: Path) -> Path:
    p = p.resolve()
    root = ROOT.resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise HTTPException(403, "path outside project")
    return p


def _safe_stem(stem: str) -> str:
    if not STEM_RE.fullmatch(stem):
        raise HTTPException(400, "invalid clip id")
    return stem


def _grid_layout_dimensions(value: Any) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"\s*(\d+)x(\d+)\s*", str(value or ""))
    if not match:
        return None, None
    columns = int(match.group(1))
    rows = int(match.group(2))
    if columns < 1 or rows < 1 or columns * rows > 12:
        return None, None
    return columns, rows


def _normalize_hook(hook: Any) -> str | dict:
    """Validate one hook from the browser editor.

    Plain blocks stay strings. Blocks that start with ``{`` may contain a
    timed hook object, so parse and validate them instead of flattening them
    into text.
    """
    if isinstance(hook, dict):
        if not isinstance(hook.get("segments"), list):
            raise HTTPException(400, "hook object must include a segments list")
        return hook
    text = str(hook).strip()
    if not text:
        raise HTTPException(400, "empty hook")
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"invalid hook JSON: {e}") from e
        if not isinstance(parsed, dict) or not isinstance(parsed.get("segments"), list):
            raise HTTPException(
                400, "timed hook JSON must be an object with a segments list"
            )
        return parsed
    return text


def _hook_dedupe_key(hook: str | dict) -> str:
    if isinstance(hook, dict):
        text = " ".join(
            str(seg.get("text", ""))
            for seg in hook.get("segments", [])
            if isinstance(seg, dict)
        )
    else:
        text = hook
    return re.sub(r"\s+", " ", text.strip().lower())


AUTO_HOOKS = [
    "POV you said this was going to be casual",
    "this was supposed to be a normal video",
    "the outfit did most of the work",
    "when you act normal but the camera disagrees",
    "not me pretending this was accidental",
    "the part where everyone suddenly pays attention",
    "this is why drafts are dangerous",
    "one quick video turned into this",
]


def _auto_hooks_for_clip(stem: str, count: int = 8) -> list[str]:
    count = max(1, min(int(count or 8), len(AUTO_HOOKS)))
    offset = int(hashlib.sha256(stem.encode("utf-8")).hexdigest()[:2], 16) % len(
        AUTO_HOOKS
    )
    ordered = AUTO_HOOKS[offset:] + AUTO_HOOKS[:offset]
    return ordered[:count]


def _manifest() -> Manifest:
    return Manifest(ROOT / "manifest.json")


def _review_states_by_filename() -> dict[str, str]:
    manifest_path = ROOT / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        manifest_data = json.loads(manifest_path.read_text())
    except Exception:
        return {}
    out: dict[str, str] = {}
    for vid in manifest_data.get("videos", {}).values():
        for var in vid.get("variations", []):
            out[Path(var.get("output_path", "")).name] = var.get(
                "review_state", "draft"
            )
    return out


def _outcome_filenames() -> set[str]:
    db = ROOT / "manifest.sqlite"
    if not db.exists():
        return set()
    try:
        conn = campaign_connect(ROOT)
        return {
            row["filename"]
            for row in conn.execute("SELECT filename FROM reel_outcomes").fetchall()
        }
    except Exception:
        return set()


def _asset_state_by_stem() -> dict[str, dict[str, Any]]:
    db = ROOT / "manifest.sqlite"
    if not db.exists():
        return {}
    try:
        conn = campaign_connect(ROOT)
        rows = conn.execute(
            """
            SELECT stem, image_job_id, image_result_url, local_image_path,
                   selected_panel, start_image, video_job_id, video_result_url, local_video_path
            FROM asset_generations
            ORDER BY created_at DESC
            """
        ).fetchall()
    except Exception:
        return {}
    states: dict[str, dict[str, Any]] = {}
    for row in rows:
        stem = row["stem"]
        if stem in states:
            continue
        states[stem] = {
            "has_image": bool(
                row["image_job_id"]
                or row["image_result_url"]
                or row["local_image_path"]
            ),
            "has_start_image": bool(row["selected_panel"] or row["start_image"]),
            "has_video": bool(
                row["video_job_id"]
                or row["video_result_url"]
                or row["local_video_path"]
            ),
        }
    return states


def _prompt_stems() -> set[str]:
    # Legacy prompt files still count for older clips, but new operator flows
    # should use direct reference-image generation rather than prompt-json prep.
    stems = {
        p.name.removesuffix("_legacy_prompt.json")
        for p in (ROOT / "prompts").glob("*_legacy_prompt.json")
    }
    stems |= {
        p.name.removesuffix("_grok.json")
        for p in (ROOT / "prompts").glob("*_grok.json")
    }
    stems |= {p.stem for p in (ROOT / "prompts").glob("clip_*.json")}
    return stems


def clip_status_from_evidence(
    *,
    stem: str,
    output_count: int,
    review_states: list[str],
    outcome_count: int,
    has_prompt: bool,
    hook_count: int = 0,
    asset_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset_state = asset_state or {}
    approved = sum(1 for state in review_states if state == "approved")
    draft = sum(1 for state in review_states if state == "draft")
    rejected = sum(1 for state in review_states if state == "rejected")
    if outcome_count and approved:
        status = "Learning Complete"
        tone = "green"
    elif approved and not outcome_count:
        status = "Needs Metrics"
        tone = "amber"
    elif output_count and draft:
        status = "Needs Review"
        tone = "amber"
    elif output_count and approved:
        status = "Approved"
        tone = "green"
    elif asset_state.get("has_video"):
        status = "Ready to Render"
        tone = "blue"
    elif asset_state.get("has_start_image") or asset_state.get("has_image"):
        status = "Needs Kling"
        tone = "amber"
    elif has_prompt:
        status = "Needs Soul"
        tone = "amber"
    elif hook_count:
        status = "Ready to Render"
        tone = "blue"
    else:
        status = "Needs Captions"
        tone = "amber"
    return {
        "status": status,
        "tone": tone,
        "approved": approved,
        "draft": draft,
        "rejected": rejected,
        "output_count": output_count,
        "outcome_count": outcome_count,
        "hook_count": hook_count,
    }


def next_action_for_status(status: str) -> dict[str, str]:
    return {
        "Needs Captions": {
            "label": "Auto-caption + render",
            "action": "autoCaptionAndRender()",
            "mode": "Render",
        },
        "Needs Soul": {
            "label": "Create reference still",
            "action": "createReferenceStill()",
            "mode": "Create",
        },
        "Needs Kling": {
            "label": "Create Kling video",
            "action": "createKlingVideo()",
            "mode": "Create",
        },
        "Ready to Render": {
            "label": "Run pipeline",
            "action": "startRun()",
            "mode": "Render",
        },
        "Needs Review": {
            "label": "Review outputs",
            "action": "setCockpitMode('Review')",
            "mode": "Review",
        },
        "Approved": {
            "label": "Export approved",
            "action": "exportApproved()",
            "mode": "Review",
        },
        "Needs Metrics": {
            "label": "Import metrics",
            "action": "focusOutcomeImport()",
            "mode": "Learn",
        },
        "Learning Complete": {
            "label": "Refresh Winner DNA",
            "action": "refreshWinnerDnaUi()",
            "mode": "Learn",
        },
    }.get(
        status,
        {
            "label": "Open create mode",
            "action": "setCockpitMode('Create')",
            "mode": "Create",
        },
    )


def _clip_cards_data() -> list[dict[str, Any]]:
    review_by_name = _review_states_by_filename()
    outcome_names = _outcome_filenames()
    asset_states = _asset_state_by_stem()
    prompt_stems = _prompt_stems()
    out = []
    for mp4 in sorted(RAW_DIR.glob("*.mp4")):
        stem = mp4.stem
        json_side = CAP_DIR / f"{stem}.json"
        txt_side = CAP_DIR / f"{stem}.txt"
        proc_dir = PROC_DIR / stem
        if json_side.exists():
            try:
                hooks = json.loads(json_side.read_text()).get("hooks", [])
                cap_count = len(hooks)
                cap_preview = hooks[0] if hooks else ""
            except Exception:
                hooks, cap_count, cap_preview = [], 0, "(json parse error)"
        elif txt_side.exists():
            t = txt_side.read_text().strip()
            hooks, cap_count, cap_preview = (
                ([t] if t else []),
                (1 if t else 0),
                (t.splitlines()[0] if t else ""),
            )
        else:
            hooks, cap_count, cap_preview = [], 0, ""
        outputs = list(proc_dir.glob("*.mp4")) if proc_dir.exists() else []
        review_states = [review_by_name.get(path.name, "draft") for path in outputs]
        outcome_count = sum(1 for path in outputs if path.name in outcome_names)
        status = clip_status_from_evidence(
            stem=stem,
            output_count=len(outputs),
            review_states=review_states,
            outcome_count=outcome_count,
            has_prompt=stem in prompt_stems,
            hook_count=cap_count,
            asset_state=asset_states.get(stem),
        )
        thumb = proc_dir / "_thumb.png"
        out.append(
            {
                "stem": stem,
                "path": str(mp4),
                "size_mb": round(mp4.stat().st_size / 1024 / 1024, 1),
                "hook_count": cap_count,
                "hook_preview": cap_preview,
                "output_count": len(outputs),
                "thumb_url": f"/file/02_processed/{stem}/_thumb.png"
                if thumb.exists()
                else None,
                "video_url": f"/file/00_source_videos/{stem}.mp4",
                "has_contact_sheet": (proc_dir / "_contact_sheet.png").exists(),
                "preflight": [],
                "status": status,
                "next_action": next_action_for_status(status["status"]),
            }
        )
    return out


def _rating_row_to_dict(row) -> dict:
    return {
        "identity": row["identity_score"],
        "pose": row["pose_score"],
        "taste": row["taste_score"],
        "artifacts": row["artifact_score"],
        "motion": row["motion_score"],
        "caption": row["caption_score"],
        "face": row["face_score"] if "face_score" in row.keys() else None,
        "eyes": row["eyes_score"] if "eyes_score" in row.keys() else None,
        "hands": row["hands_score"] if "hands_score" in row.keys() else None,
        "pose_accuracy": row["pose_accuracy_score"]
        if "pose_accuracy_score" in row.keys()
        else None,
        "body_taste": row["body_taste_score"]
        if "body_taste_score" in row.keys()
        else None,
        "background": row["background_score"]
        if "background_score" in row.keys()
        else None,
        "crop": row["crop_score"] if "crop_score" in row.keys() else None,
        "labels": json.loads(row["labels_json"] or "[]"),
        "retry_helper": row["retry_helper"],
        "reason": row["approve_reject_reason"],
        "decision": row["decision"] if "decision" in row.keys() else "unreviewed",
        "primary_reason": row["primary_reason"]
        if "primary_reason" in row.keys()
        else None,
        "secondary_reasons": json.loads(row["secondary_reasons_json"] or "[]")
        if "secondary_reasons_json" in row.keys()
        else [],
        "notes": row["notes"],
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _recent_saved_hooks(limit: int = 200) -> list[str]:
    hooks: list[str] = []
    for path in sorted(
        CAP_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        for hook in data.get("hooks") or []:
            if isinstance(hook, str):
                hooks.append(hook)
            elif isinstance(hook, dict):
                hooks.extend(
                    str(seg.get("text", "")).strip()
                    for seg in hook.get("segments") or []
                    if isinstance(seg, dict) and str(seg.get("text", "")).strip()
                )
            if len(hooks) >= limit:
                return hooks[:limit]
    return hooks


def _update_run_progress_from_line(line: str) -> None:
    text = line
    try:
        payload = json.loads(line)
        text = str(payload.get("msg", line))
    except Exception:
        pass
    if text.startswith("queued ") and " render tasks" in text:
        m = re.search(r"queued\s+(\d+)\s+render tasks", text)
        if m:
            _run_state["total"] = int(m.group(1))
    if (
        text.startswith("done ")
        or text.startswith("skip ")
        or text.startswith("DRY ")
        or text.startswith("preview ")
    ):
        _run_state["completed"] = int(_run_state.get("completed", 0)) + 1
    if text.startswith("FAIL ") or "task exception" in text:
        _run_state["failed"] = int(_run_state.get("failed", 0)) + 1


def _ensure_thumb(clip: Path, thumb: Path) -> None:
    if thumb.exists():
        return
    thumb.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            "1.0",
            "-i",
            str(clip),
            "-frames:v",
            "1",
            "-vf",
            "scale=240:-1",
            "-y",
            str(thumb),
        ],
        check=False,
    )


def _latest_preview_url(stem: str) -> str | None:
    preview_dir = PROC_DIR / stem / "_previews"
    if not preview_dir.exists():
        return None
    previews = sorted(
        preview_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not previews:
        return None
    return f"/file/02_processed/{stem}/_previews/{previews[0].name}"


def _load_ai_qc_by_name(proc_dir: Path) -> dict[str, dict[str, Any]]:
    report = proc_dir / "_ai_qc.json"
    if not report.exists():
        return {}
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("records") or []:
        if isinstance(row, dict) and row.get("filename"):
            out[str(row["filename"])] = row
    return out


def _find_output_file(filename: str) -> Path:
    if "/" in filename or "\\" in filename:
        raise HTTPException(400, "invalid filename")
    for path in PROC_DIR.glob(f"*/{Path(filename).name}"):
        if path.is_file():
            return path
    raise HTTPException(404, "output not found")


def _copy_unique(src: Path, out_dir: Path, prefix: str | None = None) -> Path:
    src = src.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    stem = f"{prefix}_{stamp}" if prefix else f"{src.stem}_{stamp}"
    dest = out_dir / f"{stem}{src.suffix.lower() or '.bin'}"
    n = 1
    while dest.exists():
        dest = out_dir / f"{stem}_{n}{src.suffix.lower() or '.bin'}"
        n += 1
    shutil.copy2(src, dest)
    return dest


def save_photo_post_asset(
    root: Path,
    *,
    source_image: str,
    account: str = "default",
    caption: str = "",
    notes: str = "",
) -> dict[str, Any]:
    src = Path(_resolve_project_path(source_image) or "")
    _safe_in_root(src)
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "source image not found")
    out_dir = root / "05_photo_posts" / account
    dest = _copy_unique(src, out_dir, prefix=src.stem)
    record = {
        "schema": "reel_factory.photo_post.v1",
        "created_at": _utc_now(),
        "account": account,
        "source_image": str(src.resolve()),
        "photo_path": str(dest),
        "filename": dest.name,
        "caption": caption,
        "notes": notes,
        "status": "saved",
    }
    sidecar = dest.with_suffix(dest.suffix + ".photo_post.json")
    sidecar.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "ok": True,
        "photo": record,
        "path": str(dest),
        "sidecar": str(sidecar),
        "url": _file_url(dest),
    }


def queue_threadsdashboard_post(
    root: Path,
    *,
    output_path: str,
    account: str = "default",
    caption: str = "",
    scheduled_at: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    src = (
        _find_output_file(Path(output_path).name)
        if not Path(output_path).is_absolute()
        else Path(output_path)
    )
    _safe_in_root(src)
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "output not found")
    out_dir = root / "04_exports" / "threadsdashboard"
    asset_dir = out_dir / "media"
    dest = _copy_unique(src, asset_dir, prefix=src.stem)
    post_id = hashlib.sha256(f"{dest}:{time.time()}".encode()).hexdigest()[:16]
    record = {
        "schema": "reel_factory.threadsdashboard_queue.v1",
        "post_id": post_id,
        "created_at": _utc_now(),
        "scheduled_at": scheduled_at,
        "account": account,
        "platform": "threads",
        "source_output_path": str(src.resolve()),
        "media_path": str(dest),
        "filename": dest.name,
        "caption": caption,
        "notes": notes,
        "status": "queued",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    item_path = out_dir / f"{post_id}.json"
    item_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (out_dir / "queue.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "queued": record,
        "path": str(item_path),
        "queue_path": str(out_dir / "queue.jsonl"),
    }


def _next_clip_id() -> str:
    """Pick the next clip_NNN id (zero-padded 3 digits)."""
    existing = [m.stem for m in RAW_DIR.glob("clip_*.mp4")]
    nums = []
    for s in existing:
        try:
            nums.append(int(s.split("_")[-1]))
        except Exception:
            pass
    n = (max(nums) + 1) if nums else 1
    return f"clip_{n:03d}"


def _file_url(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        return ""
    return f"/file/{rel.as_posix()}"


def _resolve_project_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return str(path.resolve())


def _direct_reference_plan_from_body(body: dict[str, Any]) -> DirectReferenceImagePlan:
    reference = (
        body.get("reference")
        or body.get("reference_image")
        or body.get("referenceImage")
        or body.get("image")
    )
    if not reference:
        raise HTTPException(400, "reference image is required")
    reference_path = _resolve_project_path(str(reference))
    if not reference_path or not Path(reference_path).exists():
        raise HTTPException(404, "reference image not found")
    return DirectReferenceImagePlan(
        reference_image=reference_path,
        stem=str(body.get("stem") or _next_clip_id()),
        soul_id=body.get("soul_id"),
        soul_name=body.get("soul_name") or body.get("creator") or "Stacey",
        out_dir=DATA_DIR / "generated_assets",
        source_dir=RAW_DIR,
        creator=body.get("creator") or "Stacey",
        image_aspect_ratio=str(
            body.get("image_aspect_ratio") or body.get("imageAspectRatio") or "3:4"
        ),
        image_quality=str(
            body.get("image_quality") or body.get("imageQuality") or "2k"
        ),
        image_model=str(
            body.get("image_model") or body.get("imageModel") or "text2image_soul_v2"
        ),
    )


def _crop_grid_panel(
    image_path: Path, panel: str, out_path: Path, columns: int = 3, rows: int = 2
) -> dict[str, Any]:
    image_path = _safe_in_root(image_path)
    out_path = _safe_in_root(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if panel == "full_image":
        shutil.copyfile(image_path, out_path)
        from PIL import Image

        with Image.open(image_path) as im:
            width, height = im.size
        return {
            "selected_panel": "full_image",
            "crop_box": [0, 0, width, height],
            "path": str(out_path),
            "start_image_path": str(out_path),
        }
    panel_no = int(panel)
    if panel_no < 1 or panel_no > columns * rows:
        raise HTTPException(400, f"panel must be 1-{columns * rows} or full_image")
    from PIL import Image

    with Image.open(image_path) as im:
        width, height = im.size
        cell_w = width // columns
        cell_h = height // rows
        idx = panel_no - 1
        col = idx % columns
        row = idx // columns
        box = [
            col * cell_w,
            row * cell_h,
            (col + 1) * cell_w if col < columns - 1 else width,
            (row + 1) * cell_h if row < rows - 1 else height,
        ]
        im.crop(tuple(box)).save(out_path)
    return {
        "selected_panel": panel,
        "crop_box": box,
        "path": str(out_path),
        "start_image_path": str(out_path),
    }


def _update_source_lineage_with_fanout(
    lineage_path: Path | None, manifest: dict[str, Any], panels: list[dict[str, Any]]
) -> str | None:
    if not lineage_path:
        return None
    lineage_path = Path(lineage_path).expanduser().resolve()
    if not lineage_path.exists():
        return None
    payload = json.loads(lineage_path.read_text(encoding="utf-8"))
    generation = payload.setdefault("generation", {})
    assets = payload.setdefault("assets", {}).setdefault("localPaths", {})
    generation["gridDetection"] = {
        "schema": manifest.get("schema"),
        "sourceDimensions": manifest.get("sourceDimensions"),
        "contentBox": manifest.get("contentBox"),
        "gridPreset": manifest.get("gridPreset"),
        "confidence": manifest.get("confidence"),
        "seamDetection": manifest.get("seamDetection"),
        "cropInset": manifest.get("cropInset"),
        "reviewRequired": manifest.get("reviewRequired"),
    }
    generation["gridPreset"] = manifest.get("gridPreset")
    generation["contentBox"] = manifest.get("contentBox")
    generation["panelCrops"] = manifest.get("panelCrops") or []
    generation["panelFanout"] = {
        "schema": "reel_factory.higgsfield_panel_fanout.v1",
        "panels": panels,
    }
    assets["panelStartImages"] = {
        f"panel_{int(panel['panel']):02d}": panel.get("startImagePath")
        or panel.get("path")
        for panel in manifest.get("panelCrops") or []
    }
    lineage_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return str(lineage_path)


def _shared_motion_prompt_path(stem: str) -> Path:
    return ROOT / "prompts" / "_fanout" / f"{stem}_shared_kling_motion_prompt.json"


def _write_shared_motion_prompt(source_prompt: Path, stem: str) -> Path:
    prompt = load_prompt(source_prompt)
    out = _shared_motion_prompt_path(stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "higgsfieldGridPrompt": prompt.higgsfieldGridPrompt,
        "klingMotionPrompt": prompt.klingMotionPrompt,
        "notes": f"Shared fanout motion prompt for {stem}. {prompt.notes}".strip(),
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _aspect_ratio_for_crop(crop_box: list[int]) -> str:
    width = max(1, int(crop_box[2]))
    height = max(1, int(crop_box[3]))
    ratio = width / height
    if ratio > 1.20:
        return "16:9"
    if ratio >= 0.85:
        return "1:1"
    return "9:16"


def _attach_panel_lineage(
    lineage_path_value: str | None,
    *,
    parent_image_job_id: str | None,
    parent_asset_generation_id: str | None,
    panel: dict[str, Any],
) -> None:
    if not lineage_path_value:
        return
    path = Path(lineage_path_value).expanduser().resolve()
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    generation = payload.setdefault("generation", {})
    generation["parentImageJobId"] = parent_image_job_id
    generation["parentAssetGenerationId"] = parent_asset_generation_id
    generation["selectedPanel"] = panel.get("panel")
    generation["panelCrop"] = {
        "panel": panel.get("panel"),
        "label": panel.get("label"),
        "cropBox": panel.get("cropBox"),
        "startImagePath": panel.get("startImagePath") or panel.get("path"),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _higgsfield_cli_error(exc: Exception) -> dict[str, Any]:
    message = str(exc)
    action = (
        "Run: hf auth login"
        if "auth" in message.lower() or "login" in message.lower()
        else None
    )
    return {
        "ok": False,
        "error": message,
        "action": action,
    }


def _source_video_for_stem(stem: str) -> Path:
    stem = _safe_stem(stem)
    source = RAW_DIR / f"{stem}.mp4"
    if not source.exists():
        raise HTTPException(404, "source video not found")
    return source


# ─────────────────────────────────────────────────────────────────────
# API — clips, hooks, accounts, run, upload
# ─────────────────────────────────────────────────────────────────────
@app.get("/api/clips")
def list_clips(probe_preflight: bool = False, ensure_thumbs: bool = False):
    out = _clip_cards_data()
    if not probe_preflight and not ensure_thumbs:
        return out
    by_stem = {row["stem"]: row for row in out}
    for mp4 in sorted(RAW_DIR.glob("*.mp4")):
        stem = mp4.stem
        row = by_stem.get(stem)
        if not row:
            continue
        proc_dir = PROC_DIR / stem
        thumb = proc_dir / "_thumb.png"
        if ensure_thumbs:
            _ensure_thumb(mp4, thumb)
            row["thumb_url"] = (
                f"/file/02_processed/{stem}/_thumb.png" if thumb.exists() else None
            )
        if probe_preflight:
            json_side = CAP_DIR / f"{stem}.json"
            txt_side = CAP_DIR / f"{stem}.txt"
            if json_side.exists():
                try:
                    hooks = json.loads(json_side.read_text()).get("hooks", [])
                except Exception:
                    hooks = []
            elif txt_side.exists():
                t = txt_side.read_text().strip()
                hooks = [t] if t else []
            else:
                hooks = []
            cap_set = type("_CapSet", (), {"hooks": hooks})()
            row["preflight"] = [
                w.__dict__ for w in check_clip_readiness(mp4, cap_set, ffprobe=FFPROBE)
            ]
    return out


@app.get("/api/dashboard/summary")
def dashboard_summary_api(campaign: str | None = None, account: str | None = None):
    clips_data = _clip_cards_data()
    needs_review = sum(int(row["status"].get("draft", 0)) for row in clips_data)
    ready_to_post = sum(int(row["status"].get("approved", 0)) for row in clips_data)
    needs_metrics = sum(
        max(
            0,
            int(row["status"].get("approved", 0))
            - int(row["status"].get("outcome_count", 0)),
        )
        for row in clips_data
    )
    rec = None
    if campaign:
        try:
            plan = next_batch_plan(ROOT, campaign=campaign, count=1, persist=False)
            rec = (plan.get("ideas") or [{}])[0].get("recommendation")
        except Exception:
            rec = None
    account_health = None
    if account:
        try:
            account_health = account_fatigue_report(ROOT, account=account)
        except Exception:
            account_health = None
    return {
        "schema": "reel_factory.dashboard_summary.v1",
        "command_center": {
            "needs_review": needs_review,
            "ready_to_post": ready_to_post,
            "needs_metrics": needs_metrics,
            "recommended_next_batch": rec,
        },
        "clip_statuses": {row["stem"]: row["status"] for row in clips_data},
        "next_actions": {row["stem"]: row["next_action"] for row in clips_data},
        "account_health": account_health,
        "recommendation_summary": rec,
    }


@app.get("/api/next-clip-id")
def next_clip_id_api():
    return {"stem": _next_clip_id()}


@app.get("/api/clips/{stem}")
def get_clip(stem: str, probe_audio: bool = False):
    stem = _safe_stem(stem)
    json_side = CAP_DIR / f"{stem}.json"
    txt_side = CAP_DIR / f"{stem}.txt"
    proc_dir = PROC_DIR / stem

    if json_side.exists():
        side = json.loads(json_side.read_text())
    elif txt_side.exists():
        side = {
            "hooks": [txt_side.read_text().strip()],
            "recipes": None,
            "caption_color": "auto",
        }
    else:
        side = {"hooks": [], "recipes": None, "caption_color": "auto"}

    # Build outputs grouped by hook_idx → list of (recipe, mp4)
    outputs = []
    review_by_name: dict[str, str] = {}
    manifest_path = ROOT / "manifest.json"
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text())
            for vid in manifest_data.get("videos", {}).values():
                for var in vid.get("variations", []):
                    review_by_name[Path(var.get("output_path", "")).name] = var.get(
                        "review_state", "draft"
                    )
        except Exception:
            review_by_name = {}
    similarity_by_name: dict[str, dict] = {}
    sim_path = proc_dir / "_similarity.json"
    if sim_path.exists():
        try:
            for row in json.loads(sim_path.read_text(encoding="utf-8")):
                similarity_by_name[row.get("filename", "")] = row
        except Exception:
            similarity_by_name = {}
    ai_qc_by_name = _load_ai_qc_by_name(proc_dir)
    readiness_by_name = load_readiness_by_name(proc_dir, platform="instagram_reels")
    if proc_dir.exists():
        mp4s = sorted(proc_dir.glob("*.mp4"))
        rating_by_path: dict[str, dict[str, Any]] = {}
        if mp4s:
            conn = campaign_connect(ROOT)
            paths = [str(mp4.resolve()) for mp4 in mp4s]
            placeholders = ",".join("?" for _ in paths)
            rows = conn.execute(
                f"""
                SELECT *
                FROM operator_ratings
                WHERE output_path IN ({placeholders})
                ORDER BY output_path, created_at DESC
                """,
                paths,
            ).fetchall()
            seen: set[str] = set()
            for row in rows:
                if row["output_path"] in seen:
                    continue
                seen.add(row["output_path"])
                rating_by_path[row["output_path"]] = _rating_row_to_dict(row)
        for mp4 in mp4s:
            parts = mp4.stem.split("_")
            try:
                h_pos = next(
                    i
                    for i, p in enumerate(parts)
                    if p.startswith("h") and p[1:].isdigit()
                )
                color_pos = next(
                    i for i, p in enumerate(parts) if p in ("light", "dark")
                )
                hook_idx = int(parts[h_pos][1:])
                recipe = "_".join(parts[h_pos + 1 : color_pos])
                color = parts[color_pos]
            except (StopIteration, ValueError):
                hook_idx, recipe, color = -1, "", ""
            proc_dir / "_previews" / f"{mp4.stem}.png"
            outputs.append(
                {
                    "name": mp4.name,
                    "size_mb": round(mp4.stat().st_size / 1024 / 1024, 2),
                    "url": f"/file/02_processed/{stem}/{mp4.name}",
                    "thumbnail_url": (
                        f"/file/02_processed/{stem}/{thumbnail_path_for(mp4).name}"
                        if thumbnail_path_for(mp4).exists()
                        else None
                    ),
                    "hook_idx": hook_idx,
                    "recipe": recipe,
                    "color": color,
                    "review_state": review_by_name.get(mp4.name, "draft"),
                    "audio_present": audio_stream_count(mp4) > 0
                    if probe_audio
                    else "_audio_" in mp4.stem,
                    "target_ratio": "4:5" if "_4x5_" in mp4.name else "9:16",
                    "similarity": similarity_by_name.get(mp4.name),
                    "ai_qc": ai_qc_by_name.get(mp4.name),
                    "audio_intent": read_audio_intent(mp4),
                    "readiness": readiness_by_name.get(mp4.name),
                    "safe_zone": (readiness_by_name.get(mp4.name) or {}).get(
                        "safeZone"
                    ),
                    "operator_rating": rating_by_path.get(str(mp4.resolve())),
                }
            )

    return {
        "stem": stem,
        "sidecar": side,
        "outputs": outputs,
        "video_url": f"/file/00_source_videos/{stem}.mp4",
        "grid_crop": {
            "plan_path": str(crop_plan_path(ROOT, stem))
            if crop_plan_path(ROOT, stem).exists()
            else None,
            "plan": load_crop_plan(ROOT, stem),
        },
        "latest_preview": _latest_preview_url(stem),
        "safe_zones": SAFE_ZONE_DEFAULTS,
        "contact_sheet": f"/file/02_processed/{stem}/_contact_sheet.png"
        if (proc_dir / "_contact_sheet.png").exists()
        else None,
        "csv": f"/file/02_processed/{stem}/_index.csv"
        if (proc_dir / "_index.csv").exists()
        else None,
    }


@app.put("/api/clips/{stem}/hooks")
def save_hooks(stem: str, body: dict = Body(...)):
    stem = _safe_stem(stem)
    hooks = body.get("hooks", [])
    if not isinstance(hooks, list):
        raise HTTPException(400, "hooks must be a list")
    parsed_hooks = [_normalize_hook(h) for h in hooks]
    duplicates = find_near_duplicates(parsed_hooks)
    semantic_duplicates = find_semantic_duplicates(parsed_hooks)
    json_side = CAP_DIR / f"{stem}.json"
    side = json.loads(json_side.read_text()) if json_side.exists() else {}
    side["hooks"] = parsed_hooks
    if "recipes" in body:
        side["recipes"] = body["recipes"]
    if "caption_color" in body:
        side["caption_color"] = body["caption_color"]
    generation = body.get("generation")
    if isinstance(generation, dict):
        side["generation"] = generation
    elif isinstance(side.get("generation"), dict):
        side["generation"]["updated_at"] = _utc_now()
    json_side.write_text(json.dumps(side, indent=2, ensure_ascii=False))
    return {
        "ok": True,
        "hook_count": len(parsed_hooks),
        "generation": side.get("generation"),
        "duplicates": duplicates,
        "semantic_duplicates": semantic_duplicates,
    }


@app.post("/api/clips/{stem}/auto-hooks")
def auto_hooks_api(stem: str, body: dict = Body(default={})):
    stem = _safe_stem(stem)
    json_side = CAP_DIR / f"{stem}.json"
    side = json.loads(json_side.read_text()) if json_side.exists() else {}
    existing = side.get("hooks") or []
    if existing and not body.get("force"):
        return {
            "ok": True,
            "stem": stem,
            "hook_count": len(existing),
            "hooks": existing,
            "generated": False,
        }
    hooks = _auto_hooks_for_clip(stem, count=int(body.get("count") or 8))
    side["hooks"] = hooks
    side.setdefault("recipes", None)
    side.setdefault("caption_color", "auto")
    side["generation"] = {
        "source": "auto_hooks_v1",
        "created_at": _utc_now(),
        "note": "Generated automatically for the simple make-reels flow.",
    }
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    json_side.write_text(json.dumps(side, indent=2, ensure_ascii=False))
    return {
        "ok": True,
        "stem": stem,
        "hook_count": len(hooks),
        "hooks": hooks,
        "generated": True,
    }


@app.get("/api/hook-library")
def hook_library(
    tag: str | None = None, semantic_group: str | None = None, min_use_count: int = 0
):
    hooks = read_hook_library(HOOK_LIBRARY)
    if tag:
        hooks = [h for h in hooks if tag in (h.get("tags") or [])]
    if semantic_group:
        hooks = [h for h in hooks if h.get("semantic_group") == semantic_group]
    if min_use_count:
        hooks = [h for h in hooks if int(h.get("use_count", 0)) >= min_use_count]
    return {"hooks": hooks, "embedding": embedding_status()}


@app.post("/api/hook-library")
def add_hook_library(body: dict = Body(...)):
    hook = _normalize_hook(body.get("hook", ""))
    tags = body.get("tags") or []
    if not isinstance(tags, list):
        raise HTTPException(400, "tags must be a list")
    return {"ok": True, "hook": save_hook_to_library(HOOK_LIBRARY, hook, tags=tags)}


@app.post("/api/ai-hooks")
def ai_hooks(body: dict = Body(...)):
    base = str(body.get("base", "")).strip()
    if not base:
        raise HTTPException(400, "base hook is required")
    return generate_hooks(
        backend=body.get("backend", "ollama"),
        model=body.get("model", "llama3.2:3b"),
        base=base,
        n=int(body.get("n", 8)),
        min_chars=int(body.get("min_chars", 10)),
        max_chars=int(body.get("max_chars", 140)),
        strict=bool(body.get("strict", True)),
        required_terms=body.get("required_terms") or [],
        reject_identical=bool(body.get("reject_identical", True)),
        min_similarity=float(body["min_similarity"])
        if body.get("min_similarity") is not None
        else None,
        embedding_model=body.get("embedding_model", "hash-v1"),
        log_path=DATA_DIR / "caption_generations.jsonl",
        recent_hooks=_recent_saved_hooks(),
    )


@app.get("/api/ai-hooks/status")
def ai_hooks_status(model: str = "llama3.2:3b"):
    ok, reason = OllamaHookProvider(model=model).available()
    return {"ok": ok, "message": reason, "model": model}


@app.get("/api/caption-library")
def caption_library_api():
    return caption_library(DATA_DIR / "caption_generations.jsonl")


@app.get("/api/caption-ranking/{stem}")
def caption_ranking_api(stem: str, top: int = 20):
    stem = _safe_stem(stem)
    return rank_clip_sidecar(
        CAP_DIR,
        stem,
        recent_hooks=_recent_saved_hooks(),
        top=top,
    )


@app.post("/api/preview/selection")
def preview_selection(body: dict = Body(...)):
    stem = _safe_stem(str(body.get("stem", "")))
    names = body.get("names", [])
    if not isinstance(names, list):
        raise HTTPException(400, "names must be a list")
    names = [Path(str(n)).name for n in names][:4]
    clip = get_clip(stem)
    by_name = {o["name"]: o for o in clip["outputs"]}
    return {"outputs": [by_name[name] for name in names if name in by_name]}


@app.post("/api/thumbnails")
def thumbnails(body: dict = Body(...)):
    clip = body.get("clip")
    if clip is not None:
        clip = _safe_stem(str(clip))
    return {"ok": True, **generate_thumbnails(ROOT, clip=clip)}


@app.post("/api/audio-mux")
def audio_mux(body: dict = Body(...)):
    if not bool(load_config(ROOT).get("audio_enabled", False)):
        return {"ok": False, "error": "audio muxing is temporarily disabled"}
    clip = body.get("clip")
    if clip is not None:
        clip = _safe_stem(str(clip))
    return {"ok": True, **mux_root(ROOT, clip=clip, audio_tag=body.get("audio_tag"))}


@app.put("/api/outputs/{filename}/audio-intent")
def update_audio_intent(filename: str, body: dict = Body(...)):
    output = _find_output_file(filename)
    mode = str(body.get("mode") or "")
    platform = body.get("platform")
    notes = body.get("notes")
    if mode not in AUDIO_INTENT_MODES:
        raise HTTPException(400, f"mode must be one of {sorted(AUDIO_INTENT_MODES)}")
    path = write_audio_intent(
        output,
        mode=mode,
        platform=str(platform) if platform else None,
        notes=str(notes) if notes else None,
    )
    return {"ok": True, "path": str(path), "audio_intent": read_audio_intent(output)}


@app.post("/api/readiness")
def run_readiness_api(body: dict = Body(...)):
    clip = body.get("clip")
    if clip is not None:
        clip = _safe_stem(str(clip))
        clip_dir = PROC_DIR / clip
        if not (clip_dir / "_ai_qc.json").exists():
            from ai_visual_qc import run_ai_qc

            run_ai_qc(ROOT, clip=clip)
    platform = str(body.get("platform") or "instagram_reels")
    return {"ok": True, **run_readiness(ROOT, clip=clip, platform=platform)}


@app.put("/api/outputs/{filename}/review")
def update_output_review(filename: str, body: dict = Body(...)):
    if "/" in filename or "\\" in filename:
        raise HTTPException(400, "invalid filename")
    state = body.get("review_state", "draft")
    manifest = _manifest()
    try:
        found = manifest.record_review_decision(
            filename,
            state,
            reviewer=str(body.get("reviewer") or body.get("operator") or "operator"),
            reason=str(body.get("reason") or ""),
            deck_id=body.get("deckId") or body.get("deck_id"),
            reference_hash=body.get("referenceHash") or body.get("reference_hash"),
            generated_asset_hash=body.get("generatedAssetHash")
            or body.get("generated_asset_hash"),
            soul_id=body.get("soulId") or body.get("soul_id"),
            aspect_ratio=body.get("aspectRatio") or body.get("aspect_ratio"),
            visual_qc_status=body.get("visualQcStatus") or body.get("visual_qc_status"),
            identity_verification_status=body.get("identityVerificationStatus")
            or body.get("identity_verification_status"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not found:
        raise HTTPException(404, "output not found in manifest")
    try:
        output = _find_output_file(filename)
        link_campaign_output(
            ROOT, output_path=output, campaign=body.get("campaign"), review_state=state
        )
    except Exception:
        pass
    manifest.save()
    return {"ok": True, "review_state": state}


@app.get("/api/campaigns")
def campaigns_api():
    return {"campaigns": list_campaigns(ROOT)}


@app.post("/api/campaigns")
def create_campaign_api(body: dict = Body(...)):
    return create_campaign(
        ROOT,
        name=str(body.get("name") or ""),
        creator=str(body.get("creator") or "Stacey"),
        account=str(body.get("account") or "default"),
        platform=str(body.get("platform") or "instagram_reels"),
        content_angle=str(body.get("content_angle") or ""),
        notes=str(body.get("notes") or ""),
    )


@app.post("/api/campaigns/{campaign}/references")
def add_campaign_reference_api(campaign: str, body: dict = Body(...)):
    source = (
        body.get("reference_reel")
        or body.get("reference_image")
        or body.get("source_path")
    )
    if not source:
        raise HTTPException(400, "reference_reel or reference_image is required")
    return add_reference(
        ROOT,
        campaign=campaign,
        source_path=Path(_resolve_project_path(source) or source),
        visual_tags=body.get("visual_tags") or [],
        intended_pose=str(body.get("intended_pose") or ""),
        intended_outfit=str(body.get("intended_outfit") or ""),
        intended_scene=str(body.get("intended_scene") or ""),
        notes=str(body.get("notes") or ""),
    )


@app.post("/api/reels/import")
def import_reel_url_api(body: dict = Body(...)):
    url = str(body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")
    campaign = str(body.get("campaign") or "").strip() or None
    creator = str(body.get("creator") or "Stacey")
    stem = str(body.get("stem") or _next_clip_id())
    _safe_stem(stem)
    try:
        download = download_reel_url(url, out_dir=RAW_DIR, stem=stem)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

    cap = CAP_DIR / f"{stem}.json"
    cap.write_text(
        json.dumps(
            {
                "_downloaded_from_url": url,
                "hooks": [],
                "recipes": None,
                "caption_color": "auto",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    url_meta_path = RAW_DIR / f"{stem}.reel_url_import.json"
    write_url_sidecar(
        url_meta_path,
        {
            "schema": "reel_factory.reel_url_import.v1",
            "url": url,
            "stem": stem,
            "sourceVideoPath": download["path"],
            "campaign": campaign,
        },
    )

    reference_record = None
    if campaign:
        reference_record = add_reference(
            ROOT,
            campaign=campaign,
            source_path=Path(str(download["path"])),
            source_type="reel",
            visual_tags=["reel_url_import"],
            notes=f"Imported from URL: {url}",
        )

    prompt_result = None
    if body.get("generate_prompt", False):
        prompt_path = Path(
            body.get("prompt_out") or ROOT / "prompts" / f"{stem}_legacy_prompt.json"
        )
        try:
            prompt_result = generate_prompt(
                out_path=prompt_path.expanduser().resolve(),
                root=ROOT,
                reference_reel=Path(str(download["path"])),
                reference_images=[],
                campaign=campaign,
                creator=creator,
                retry_helper=body.get("retry_helper"),
                reference_frame_mode=str(
                    body.get("reference_frame_mode") or "first-visible"
                ),
                creative_direction=str(body.get("creative_direction") or ""),
                reference_context=str(body.get("reference_context") or ""),
                operator_notes=str(
                    body.get("operator_notes") or f"Imported from URL: {url}"
                ),
                dry_run=True,
                grid_layout=str(
                    body.get("grid_layout") or body.get("gridLayout") or "single"
                ),
            )
            prompt_result["legacy"] = True
        except Exception as exc:
            prompt_result = {
                "ok": False,
                "error": str(exc),
                "prompt_json_path": str(prompt_path),
            }

    return {
        "ok": True,
        "stem": stem,
        "path": download["path"],
        "video_url": _file_url(Path(str(download["path"]))),
        "url_import_path": str(url_meta_path.resolve()),
        "reference_record": reference_record,
        "prompt": prompt_result,
    }


@app.put("/api/outputs/{filename}/rating")
def rate_output_api(filename: str, body: dict = Body(...)):
    output = _find_output_file(filename)
    return rate_output(
        ROOT,
        output_path=output,
        campaign=body.get("campaign"),
        asset_generation_id=body.get("asset_generation_id"),
        scores={
            "identity": body.get("identity"),
            "pose": body.get("pose"),
            "taste": body.get("taste"),
            "artifacts": body.get("artifacts"),
            "motion": body.get("motion"),
            "caption": body.get("caption"),
            "face": body.get("face"),
            "eyes": body.get("eyes"),
            "hands": body.get("hands"),
            "pose_accuracy": body.get("pose_accuracy"),
            "body_taste": body.get("body_taste"),
            "background": body.get("background"),
            "crop": body.get("crop"),
        },
        labels=body.get("labels") or [],
        retry_helper=body.get("retry_helper"),
        reason=str(body.get("reason") or ""),
        notes=str(body.get("notes") or ""),
        decision=body.get("decision"),
        primary_reason=body.get("primary_reason"),
        secondary_reasons=body.get("secondary_reasons") or [],
    )


@app.get("/api/campaigns/{campaign}/leaderboard")
def campaign_leaderboard_api(campaign: str):
    return campaign_leaderboard(ROOT, campaign=campaign)


@app.get("/api/campaigns/{campaign}/next-batch")
def next_batch_api(campaign: str, count: int = 20, persist: bool = False):
    return next_batch_plan(ROOT, campaign=campaign, count=count, persist=persist)


@app.get("/api/grid-crop/{stem}/frame")
def grid_crop_frame_api(stem: str, time_sec: float = 0.25):
    guard_deprecated_generator_api("grid_crop")
    source = _source_video_for_stem(stem)
    info_raw = subprocess.check_output(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(source),
        ],
        text=True,
    )
    stream = (json.loads(info_raw).get("streams") or [{}])[0]
    frame = frame_path(ROOT, stem, time_sec)
    extract_frame(source, frame, time_sec=time_sec)
    plan = load_crop_plan(ROOT, stem)
    return {
        "ok": True,
        "stem": stem,
        "source_video": str(source.resolve()),
        "frame_path": str(frame.resolve()),
        "frame_url": _file_url(frame),
        "source_dimensions": {
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "duration": float(stream.get("duration") or 0.0),
        },
        "plan": plan,
        "plan_path": str(crop_plan_path(ROOT, stem)) if plan else None,
    }


@app.post("/api/grid-crop/{stem}/suggest")
def grid_crop_suggest_api(stem: str, body: dict = Body(default={})):
    guard_deprecated_generator_api("grid_crop")
    source = _source_video_for_stem(stem)
    info_raw = subprocess.check_output(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(source),
        ],
        text=True,
    )
    stream = (json.loads(info_raw).get("streams") or [{}])[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    columns = body.get("columns")
    rows = body.get("rows")
    if not (columns and rows):
        layout_columns, layout_rows = _grid_layout_dimensions(body.get("grid_layout"))
        columns = columns or layout_columns
        rows = rows or layout_rows
    if not columns or not rows:
        columns, rows = infer_grid_preset(width, height)
    boxes = preset_boxes(
        width,
        height,
        columns=int(columns),
        rows=int(rows),
        inset=int(body.get("inset") or 0),
    )
    return {
        "ok": True,
        "stem": stem,
        "grid_preset": {"columns": int(columns), "rows": int(rows)},
        "boxes": boxes,
        "source_dimensions": {
            "width": width,
            "height": height,
            "duration": float(stream.get("duration") or 0.0),
        },
    }


@app.put("/api/grid-crop/{stem}/plan")
def grid_crop_save_plan_api(stem: str, body: dict = Body(...)):
    guard_deprecated_generator_api("grid_crop")
    source = _source_video_for_stem(stem)
    columns = body.get("columns") or (body.get("grid_preset") or {}).get("columns")
    rows = body.get("rows") or (body.get("grid_preset") or {}).get("rows")
    frame_time = float(body.get("frame_time") or body.get("frameTime") or 0.25)
    plan = build_crop_plan(
        ROOT,
        stem=stem,
        source_video=source,
        frame_time=frame_time,
        columns=int(columns) if columns else None,
        rows=int(rows) if rows else None,
        boxes=body.get("boxes") or None,
        render_mode=str(
            body.get("render_mode") or body.get("renderMode") or "fit_nocrop"
        ),
    )
    dims = plan["sourceDimensions"]
    plan["boxes"] = validate_boxes(
        plan["boxes"], width=int(dims["width"]), height=int(dims["height"])
    )
    path = save_crop_plan(ROOT, plan)
    return {
        "ok": True,
        "plan": plan,
        "plan_path": str(path),
        "plan_url": _file_url(path),
    }


@app.post("/api/grid-crop/{stem}/preview")
def grid_crop_preview_api(stem: str, body: dict = Body(...)):
    guard_deprecated_generator_api("grid_crop")
    _source_video_for_stem(stem)
    panel_id = int(body.get("panel_id") or body.get("panel") or 1)
    try:
        preview = preview_panel_image(ROOT, stem=stem, panel_id=panel_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(400, f"panel {panel_id} not found") from exc
    return {
        "ok": True,
        "panel_id": panel_id,
        "preview_path": str(preview),
        "preview_url": _file_url(preview),
    }


@app.post("/api/grid-crop/{stem}/render")
def grid_crop_render_api(stem: str, body: dict = Body(default={})):
    guard_deprecated_generator_api("grid_crop")
    _source_video_for_stem(stem)
    try:
        result = render_grid_crop_plan(
            ROOT,
            stem=stem,
            captions=body.get("captions") or None,
            render_captions=bool(body.get("render_captions", True)),
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@app.get("/api/higgsfield/capabilities")
def higgsfield_capabilities_api(force: bool = False):
    try:
        return probe_higgsfield_capabilities(ROOT, force=force)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/assets/reference-image/dry-run")
def asset_reference_image_dry_run_api(body: dict = Body(...)):
    plan = _direct_reference_plan_from_body(body)
    return dry_run_direct_reference_image(plan, wait=bool(body.get("wait")))


@app.post("/api/assets/reference-image/create")
def asset_reference_image_create_api(body: dict = Body(...)):
    plan = _direct_reference_plan_from_body(body)
    try:
        result = create_direct_reference_image_asset(
            plan,
            wait=bool(body.get("wait", True)),
            download=bool(body.get("download", True)),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except HiggsfieldCommandError as exc:
        return _higgsfield_cli_error(exc)
    lineage = result.get("lineage") or {}
    generation = lineage.get("generation") or {}
    assets = (lineage.get("assets") or {}).get("localPaths") or {}
    image_path = assets.get("image")
    result.update(
        {
            "workflow": "higgsfield_direct_reference_image",
            "image_job_id": generation.get("imageJobId"),
            "image_result_url": generation.get("imageResultUrl"),
            "captured_higgsfield_prompt": generation.get("capturedHiggsfieldPrompt"),
            "local_image_path": image_path,
            "lineage_path": result.get("path"),
        }
    )
    if image_path:
        result["image_url"] = _file_url(Path(image_path))
        result["local_image_url"] = result["image_url"]
    return result


@app.post("/api/assets/dry-run")
def asset_dry_run_api(body: dict = Body(...)):
    prompt_json = body.get("prompt_json")
    stem = body.get("stem")
    creator = body.get("creator") or "Stacey"
    if not prompt_json or not stem:
        raise HTTPException(400, "prompt_json and stem are required")
    plan = AssetGenerationPlan(
        prompt_json=Path(prompt_json).expanduser().resolve(),
        stem=str(stem),
        reference=_resolve_project_path(body.get("reference")),
        soul_id=body.get("soul_id"),
        soul_name=body.get("soul_name") or creator,
        start_image=body.get("start_image"),
        out_dir=RAW_DIR,
        source_dir=RAW_DIR,
        video_reference=_resolve_project_path(body.get("video_reference")),
        campaign=body.get("campaign"),
        creator=creator,
        selected_panel=body.get("selected_panel"),
        image_mode=body.get("image_mode") or "single",
        image_aspect_ratio=body.get("image_aspect_ratio")
        or body.get("imageAspectRatio")
        or DEFAULT_GRID_IMAGE_ASPECT_RATIO,
        image_quality=body.get("image_quality") or body.get("imageQuality") or "2k",
        video_aspect_ratio=body.get("video_aspect_ratio")
        or body.get("videoAspectRatio")
        or "9:16",
        video_duration=int(
            body.get("video_duration") or body.get("videoDuration") or 5
        ),
        video_sound=body.get("video_sound") or body.get("videoSound") or "off",
        image_model=body.get("image_model")
        or body.get("imageModel")
        or "text2image_soul_v2",
        video_model=body.get("video_model") or body.get("videoModel") or "kling3_0",
    )
    return asset_dry_run(plan, wait=bool(body.get("wait")))


@app.post("/api/prompts/generate")
def prompt_generate_api(body: dict = Body(...)):
    stem = str(body.get("stem") or _next_clip_id())
    out_path = Path(body.get("out") or ROOT / "prompts" / f"{stem}_legacy_prompt.json")
    reference_reel = body.get("reference_reel")
    reference_image = body.get("reference_image")
    if not reference_reel and not reference_image:
        raise HTTPException(400, "reference_reel or reference_image is required")
    result = generate_prompt(
        out_path=out_path.expanduser().resolve(),
        root=ROOT,
        reference_reel=Path(_resolve_project_path(reference_reel))
        if reference_reel
        else None,
        reference_images=[Path(_resolve_project_path(reference_image))]
        if reference_image
        else [],
        campaign=body.get("campaign"),
        creator=body.get("creator") or "Stacey",
        retry_helper=body.get("retry_helper"),
        creative_direction=str(body.get("creative_direction") or ""),
        reference_context=str(body.get("reference_context") or ""),
        operator_notes=str(body.get("operator_notes") or ""),
        dry_run=True,
        grid_layout=str(body.get("grid_layout") or body.get("gridLayout") or "single"),
        image_aspect_ratio=str(
            body.get("image_aspect_ratio")
            or body.get("imageAspectRatio")
            or DEFAULT_GRID_IMAGE_ASPECT_RATIO
        ),
    )
    result["legacy"] = True
    return result


@app.post("/api/assets/create-image")
def asset_create_image_api(body: dict = Body(...)):
    prompt_json = body.get("prompt_json")
    stem = body.get("stem")
    if not prompt_json or not stem:
        raise HTTPException(400, "prompt_json and stem are required")
    plan = AssetGenerationPlan(
        prompt_json=Path(prompt_json).expanduser().resolve(),
        stem=str(stem),
        reference=_resolve_project_path(body.get("reference")),
        soul_id=body.get("soul_id"),
        soul_name=body.get("soul_name") or body.get("creator") or "Stacey",
        start_image=None,
        out_dir=DATA_DIR / "generated_assets",
        source_dir=RAW_DIR,
        campaign=body.get("campaign"),
        creator=body.get("creator") or "Stacey",
        image_mode=body.get("image_mode") or "single",
        image_aspect_ratio=body.get("image_aspect_ratio")
        or body.get("imageAspectRatio")
        or DEFAULT_GRID_IMAGE_ASPECT_RATIO,
        image_quality=body.get("image_quality") or body.get("imageQuality") or "2k",
    )
    try:
        result = create_image_asset(
            plan,
            wait=bool(body.get("wait", True)),
            download=bool(body.get("download", True)),
        )
    except HiggsfieldCommandError as exc:
        return _higgsfield_cli_error(exc)
    lineage = result.get("lineage") or {}
    generation = lineage.get("generation") or {}
    assets = (lineage.get("assets") or {}).get("localPaths") or {}
    campaign_record = result.get("campaign_record") or {}
    image_path = assets.get("image")
    result.update(
        {
            "image_job_id": generation.get("imageJobId"),
            "image_job_ids": generation.get("imageJobIds")
            or ([generation.get("imageJobId")] if generation.get("imageJobId") else []),
            "image_result_url": generation.get("imageResultUrl"),
            "image_result_urls": generation.get("imageResultUrls")
            or (
                [generation.get("imageResultUrl")]
                if generation.get("imageResultUrl")
                else []
            ),
            "local_image_path": image_path,
            "six_pack_paths": {
                k: v for k, v in assets.items() if str(k).startswith("variation_")
            },
            "six_pack_urls": {
                k: _file_url(Path(v))
                for k, v in assets.items()
                if str(k).startswith("variation_")
            },
            "grid": generation.get("grid"),
            "grid_status": (generation.get("grid") or {}).get("status"),
            "asset_generation_id": campaign_record.get("asset_generation_id"),
            "lineage_path": result.get("path"),
        }
    )
    if image_path:
        result["image_url"] = _file_url(Path(image_path))
        result["local_image_url"] = result["image_url"]
    return result


@app.post("/api/assets/select-panel")
def asset_select_panel_api(body: dict = Body(...)):
    source_image = _resolve_project_path(body.get("source_image"))
    stem = str(body.get("stem") or _next_clip_id())
    panel = str(body.get("panel") or "full_image")
    if not source_image:
        raise HTTPException(400, "source_image is required")
    out = DATA_DIR / "start_images" / f"{stem}_panel_{panel}.png"
    result = _crop_grid_panel(Path(source_image), panel, out)
    if body.get("asset_generation_id"):
        existing = get_asset_generation(ROOT, str(body["asset_generation_id"])) or {}
        raw_meta = existing.get("raw") or {}
        raw_meta["selection"] = {
            "selectedPanel": result["selected_panel"],
            "cropBox": result["crop_box"],
            "sourceImage": str(Path(source_image).resolve()),
            "startImage": result["path"],
        }
        update_asset_generation(
            ROOT,
            str(body["asset_generation_id"]),
            selected_panel=result["selected_panel"],
            start_image=result["path"],
            local_image_path=str(Path(source_image).resolve()),
            raw_json=raw_meta,
            status="needs_video",
        )
    result["url"] = _file_url(Path(result["path"]))
    result["start_image_url"] = result["url"]
    return {"ok": True, **result}


@app.post("/api/assets/create-video")
def asset_create_video_api(body: dict = Body(...)):
    prompt_json = body.get("prompt_json")
    stem = body.get("stem")
    start_image = body.get("start_image")
    if not prompt_json or not stem or not start_image:
        raise HTTPException(400, "prompt_json, stem, and start_image are required")
    plan = AssetGenerationPlan(
        prompt_json=Path(prompt_json).expanduser().resolve(),
        stem=str(stem),
        reference=_resolve_project_path(body.get("reference")),
        soul_id=body.get("soul_id"),
        soul_name=body.get("soul_name") or body.get("creator") or "Stacey",
        start_image=str(_resolve_project_path(start_image) or start_image),
        out_dir=RAW_DIR,
        source_dir=RAW_DIR,
        video_reference=_resolve_project_path(body.get("video_reference")),
        campaign=None if body.get("asset_generation_id") else body.get("campaign"),
        creator=None
        if body.get("asset_generation_id")
        else (body.get("creator") or "Stacey"),
        selected_panel=body.get("selected_panel"),
        video_aspect_ratio=body.get("video_aspect_ratio")
        or body.get("videoAspectRatio")
        or "9:16",
        video_duration=int(
            body.get("video_duration") or body.get("videoDuration") or 5
        ),
        video_sound=body.get("video_sound") or body.get("videoSound") or "off",
        video_model=body.get("video_model") or body.get("videoModel") or "kling3_0",
    )
    try:
        result = create_video_asset(
            plan,
            wait=bool(body.get("wait", True)),
            download=bool(body.get("download", False)),
        )
    except HiggsfieldCommandError as exc:
        return _higgsfield_cli_error(exc)
    lineage = result.get("lineage") or {}
    generation = lineage.get("generation") or {}
    campaign_record = result.get("campaign_record") or {}
    video_url = generation.get("videoResultUrl")
    if body.get("asset_generation_id") and video_url:
        existing = get_asset_generation(ROOT, str(body["asset_generation_id"])) or {}
        raw_meta = existing.get("raw") or {}
        raw_meta["video"] = generation.get("raw") or {}
        raw_meta["videoSteps"] = generation.get("steps") or []
        update_asset_generation(
            ROOT,
            str(body["asset_generation_id"]),
            video_job_id=generation.get("videoJobId"),
            video_result_url=video_url,
            raw_json=raw_meta,
            status="video_created",
        )
        campaign_record["asset_generation_id"] = body["asset_generation_id"]
    result.update(
        {
            "video_job_id": generation.get("videoJobId"),
            "video_result_url": video_url,
            "asset_generation_id": campaign_record.get("asset_generation_id"),
            "lineage_path": result.get("path"),
        }
    )
    return result


@app.post("/api/assets/fanout-panels")
def asset_fanout_panels_api(body: dict = Body(...)):
    prompt_json_value = body.get("prompt_json")
    stem = _safe_stem(str(body.get("stem") or _next_clip_id()))
    source_image_value = body.get("source_image")
    if not prompt_json_value or not source_image_value:
        raise HTTPException(400, "prompt_json and source_image are required")
    prompt_json = Path(prompt_json_value).expanduser()
    if not prompt_json.is_absolute():
        prompt_json = ROOT / prompt_json
    prompt_json = prompt_json.resolve()
    if not prompt_json.exists():
        raise HTTPException(404, "prompt_json not found")
    source_image = Path(_resolve_project_path(source_image_value) or "")
    source_image = _safe_in_root(source_image)
    if not source_image.exists():
        raise HTTPException(404, "source_image not found")

    columns = body.get("columns")
    rows = body.get("rows")
    if not (columns and rows):
        layout_columns, layout_rows = _grid_layout_dimensions(body.get("grid_layout"))
        columns = columns or layout_columns
        rows = rows or layout_rows
    crop_root = DATA_DIR / "generated_assets" / "start_images" / stem
    manifest = crop_image_grid_panels(
        source_image,
        crop_root,
        columns=int(columns) if columns else None,
        rows=int(rows) if rows else None,
        smart=True,
        prefix=stem,
    )
    for panel in manifest["panelCrops"]:
        panel["url"] = _file_url(Path(panel["path"]))
        panel["startImageUrl"] = panel["url"]

    detected_count = len(manifest["panelCrops"])
    max_jobs = int(body.get("max_jobs") or detected_count)
    max_jobs = max(0, min(max_jobs, detected_count))
    dry_run = bool(body.get("dry_run", False))
    selected_panels = manifest["panelCrops"][:max_jobs]
    parent_image_job_id = body.get("image_job_id")
    parent_asset_generation_id = body.get("asset_generation_id")
    panels: list[dict[str, Any]] = []
    shared_prompt_path = (
        _write_shared_motion_prompt(prompt_json, stem) if selected_panels else None
    )

    for panel in selected_panels:
        panel_no = int(panel["panel"])
        planned = {
            "panel": panel_no,
            "label": panel.get("label"),
            "status": "planned" if dry_run else "pending",
            "cropBox": panel.get("cropBox"),
            "startImagePath": panel.get("startImagePath") or panel.get("path"),
            "startImageUrl": panel.get("startImageUrl") or panel.get("url"),
            "promptJsonPath": str(shared_prompt_path) if shared_prompt_path else None,
            "sharedMotionPrompt": True,
        }
        if dry_run:
            panels.append(planned)
            continue

        try:
            plan = AssetGenerationPlan(
                prompt_json=shared_prompt_path if shared_prompt_path else prompt_json,
                stem=f"{stem}_panel_{panel_no:02d}_kling",
                reference=None,
                soul_id=body.get("soul_id"),
                soul_name=body.get("soul_name") or body.get("creator") or "Stacey",
                start_image=planned["startImagePath"],
                out_dir=RAW_DIR,
                source_dir=RAW_DIR,
                campaign=None,
                creator=None,
                selected_panel=str(panel_no),
                video_aspect_ratio=_aspect_ratio_for_crop(
                    panel.get("cropBox") or [0, 0, 9, 16]
                ),
            )
            result = create_video_asset(
                plan,
                wait=bool(body.get("wait", True)),
                download=bool(body.get("download", False)),
            )
            generation = (result.get("lineage") or {}).get("generation") or {}
            status = "created" if result.get("ok") else "failed"
            created = {
                **planned,
                "status": status,
                "videoJobId": generation.get("videoJobId"),
                "videoResultUrl": generation.get("videoResultUrl"),
                "lineagePath": result.get("path"),
                "error": result.get("error"),
            }
            _attach_panel_lineage(
                result.get("path"),
                parent_image_job_id=parent_image_job_id,
                parent_asset_generation_id=parent_asset_generation_id,
                panel=panel,
            )
            panels.append(created)
        except Exception as exc:
            panels.append({**planned, "status": "failed", "error": str(exc)})

    lineage_path = body.get("lineage_path")
    if not lineage_path and stem:
        candidate = RAW_DIR / f"{stem}.generated_asset_lineage.json"
        lineage_path = str(candidate) if candidate.exists() else None
    updated_lineage_path = _update_source_lineage_with_fanout(
        Path(lineage_path) if lineage_path else None,
        manifest,
        panels,
    )

    if parent_asset_generation_id:
        existing = get_asset_generation(ROOT, str(parent_asset_generation_id)) or {}
        raw_meta = existing.get("raw") or {}
        raw_meta["gridFanout"] = {
            "gridDetection": {
                "sourceDimensions": manifest.get("sourceDimensions"),
                "contentBox": manifest.get("contentBox"),
                "gridPreset": manifest.get("gridPreset"),
                "confidence": manifest.get("confidence"),
                "seamDetection": manifest.get("seamDetection"),
                "cropInset": manifest.get("cropInset"),
                "reviewRequired": manifest.get("reviewRequired"),
            },
            "panels": panels,
        }
        try:
            update_asset_generation(
                ROOT,
                str(parent_asset_generation_id),
                raw_json=raw_meta,
                status="fanout_planned" if dry_run else "fanout_created",
            )
        except Exception:
            pass

    failed = sum(1 for panel in panels if panel.get("status") == "failed")
    created = sum(1 for panel in panels if panel.get("status") == "created")
    planned = sum(1 for panel in panels if panel.get("status") == "planned")
    return {
        "ok": failed == 0,
        "schema": "reel_factory.higgsfield_panel_fanout.v1",
        "stem": stem,
        "dry_run": dry_run,
        "detectedPanelCount": detected_count,
        "maxJobs": max_jobs,
        "created": created,
        "failed": failed,
        "planned": planned,
        "gridDetection": {
            "sourceDimensions": manifest.get("sourceDimensions"),
            "contentBox": manifest.get("contentBox"),
            "gridPreset": manifest.get("gridPreset"),
            "confidence": manifest.get("confidence"),
            "seamDetection": manifest.get("seamDetection"),
            "cropInset": manifest.get("cropInset"),
            "reviewRequired": manifest.get("reviewRequired"),
        },
        "cropManifest": manifest,
        "panels": panels,
        "lineage_path": updated_lineage_path,
    }


@app.post("/api/assets/download-video")
def asset_download_video_api(body: dict = Body(...)):
    url = body.get("video_url")
    asset_generation = None
    if body.get("asset_generation_id"):
        asset_generation = get_asset_generation(ROOT, str(body["asset_generation_id"]))
        if not asset_generation:
            raise HTTPException(404, "asset_generation_id not found")
    if not url and asset_generation:
        url = asset_generation.get("video_result_url")
    if not url:
        raise HTTPException(
            400,
            "video_url or asset_generation_id with stored video_result_url is required",
        )
    stem = str(body.get("stem") or _next_clip_id())
    out = RAW_DIR / f"{stem}.mp4"
    urllib.request.urlretrieve(str(url), out)
    prompt_json = (
        Path(body.get("prompt_json")).expanduser().resolve()
        if body.get("prompt_json")
        else None
    )
    lineage = {
        "schema": "campaign_factory.generated_asset_lineage.v2",
        "createdAt": int(time.time()),
        "source": {
            "stem": stem,
            "promptSourcePath": str(prompt_json) if prompt_json else None,
            "sourceVideoPath": str(out.resolve()),
            "soulName": body.get("creator") or "Stacey",
            "selectedPanel": body.get("selected_panel")
            or (asset_generation or {}).get("selected_panel"),
            "startImage": body.get("start_image")
            or (asset_generation or {}).get("start_image"),
        },
        "generation": {
            "tool": "higgsfield_cli",
            "workflow": "operator_cockpit_kling_download",
            "models": {"video": "kling3_0"},
            "videoJobId": body.get("video_job_id")
            or (asset_generation or {}).get("video_job_id"),
            "videoResultUrl": url,
            "assetGenerationId": body.get("asset_generation_id"),
            "steps": [
                {
                    "name": "download_video",
                    "url": url,
                    "localPath": str(out.resolve()),
                }
            ],
        },
        "assets": {"localPaths": {"video": str(out.resolve())}},
        "review": {"humanReviewRequired": True},
    }
    lineage_path = RAW_DIR / f"{stem}.generated_asset_lineage.json"
    lineage_path.write_text(
        json.dumps(lineage, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    cap = CAP_DIR / f"{stem}.json"
    if not cap.exists():
        cap.write_text(
            json.dumps(
                {
                    "hooks": body.get("hooks")
                    or [
                        "when the room gets quiet",
                        "he noticed before i said anything",
                        "just a little too casual",
                    ],
                    "recipes": None,
                    "caption_color": "auto",
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if body.get("asset_generation_id"):
        raw_meta = (asset_generation or {}).get("raw") or {}
        raw_meta["download"] = {
            "videoResultUrl": url,
            "localVideoPath": str(out.resolve()),
            "lineagePath": str(lineage_path.resolve()),
        }
        update_asset_generation(
            ROOT,
            str(body["asset_generation_id"]),
            local_video_path=str(out.resolve()),
            lineage_path=str(lineage_path.resolve()),
            raw_json=raw_meta,
            status="downloaded",
        )
    return {
        "ok": True,
        "stem": stem,
        "downloaded_stem": stem,
        "path": str(out),
        "source_path": str(out),
        "source_url": _file_url(out),
        "lineage_path": str(lineage_path),
    }


@app.post("/api/campaigns/{campaign}/render-pack")
def campaign_render_pack_api(campaign: str, body: dict = Body(...)):
    stem = body.get("stem")
    if not stem:
        raise HTTPException(400, "stem is required")
    cmd = [
        sys.executable,
        "reel_pipeline.py",
        "--root",
        str(ROOT),
        "--only-clip",
        _safe_stem(str(stem)),
        "--campaign",
        campaign,
        "--ai-qc",
        "--readiness",
    ]
    if body.get("asset_generation_id"):
        cmd += ["--asset-generation-id", str(body["asset_generation_id"])]
    if body.get("asset_prompt_json"):
        cmd += [
            "--asset-prompt-json",
            str(Path(body["asset_prompt_json"]).expanduser().resolve()),
        ]
    if body.get("recipes"):
        recipes = body["recipes"]
        if isinstance(recipes, str):
            recipes = [recipes]
        cmd += ["--recipes", *[str(r) for r in recipes]]
    if body.get("max_hooks"):
        cmd += ["--max-hooks", str(int(body["max_hooks"]))]
    if body.get("target_ratios"):
        ratios = body["target_ratios"]
        if isinstance(ratios, str):
            ratios = [ratios]
        cmd += ["--target-ratios", *[str(r) for r in ratios]]
    if body.get("workers"):
        cmd += ["--workers", str(int(body["workers"]))]
    proc = subprocess.run(
        cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if proc.returncode != 0:
        raise HTTPException(500, proc.stdout[-2000:])
    return {"ok": True, "log": proc.stdout[-4000:]}


@app.put("/api/outputs/review/batch")
def batch_output_review(body: dict = Body(...)):
    state = body.get("review_state", "draft")
    filenames = body.get("filenames") or []
    hook = body.get("hook")
    recipe = body.get("recipe")
    stem = body.get("stem")
    if state not in {"draft", "maybe", "approved", "rejected"}:
        raise HTTPException(
            400, "review_state must be draft, maybe, approved, or rejected"
        )
    if not filenames:
        clip = get_clip(_safe_stem(stem)) if stem else None
        if clip:
            for output in clip["outputs"]:
                if hook is not None and output["hook_idx"] != int(hook):
                    continue
                if recipe is not None and output["recipe"] != recipe:
                    continue
                filenames.append(output["name"])
    manifest = _manifest()
    changed = 0
    for filename in filenames:
        if manifest.record_review_decision(
            str(filename),
            state,
            reviewer=str(body.get("reviewer") or body.get("operator") or "operator"),
            reason=str(body.get("reason") or ""),
            deck_id=body.get("deckId") or body.get("deck_id"),
        ):
            changed += 1
    manifest.save()
    return {"ok": True, "changed": changed, "review_state": state}


@app.get("/api/metrics/summary")
def get_metrics_summary():
    return {"rows": metrics_summary(ROOT)}


@app.get("/api/metrics/leaderboard")
def get_metrics_leaderboard():
    return metrics_leaderboard(ROOT)


@app.post("/api/metrics/import")
def import_metrics(body: dict = Body(...)):
    path = body.get("path")
    if not path:
        raise HTTPException(400, "path is required")
    csv_path = _safe_in_root(Path(path))
    return {"ok": True, **import_metrics_csv(ROOT, csv_path)}


@app.post("/api/outcomes/import")
async def import_outcomes(
    body: dict | None = Body(default=None), file: UploadFile | None = File(default=None)
):
    if file is not None:
        tmp = (
            DATA_DIR
            / "imports"
            / f"{int(time.time())}_{Path(file.filename or 'outcomes.csv').name}"
        )
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(await file.read())
        csv_path = tmp
    else:
        path = (body or {}).get("path")
        if not path:
            raise HTTPException(400, "path or file is required")
        csv_path = _safe_in_root(Path(path))
    return {"ok": True, **import_outcomes_csv(ROOT, csv_path)}


@app.get("/api/outcomes/summary")
def get_outcomes_summary(limit: int = 10):
    return outcomes_summary(ROOT, limit=limit)


@app.post("/api/references/analyze")
def analyze_reference_api(body: dict = Body(...)):
    reference = body.get("reference") or body.get("path")
    if not reference:
        raise HTTPException(400, "reference is required")
    model = str(body.get("model") or "").strip()
    if not model:
        raise HTTPException(400, "model is required")
    if model.lower().startswith("grok"):
        guard_deprecated_generator_api("grok_reference_analysis")
    return analyze_reference(
        ROOT,
        Path(_resolve_project_path(reference)),
        model=model,
        dry_run=bool(body.get("dry_run")),
    )


@app.get("/api/similar")
def similar_api(path: str, limit: int = 10):
    resolved = Path(_resolve_project_path(path))
    if not resolved.exists():
        resolved = _find_output_file(Path(path).name)
    return similar_media(ROOT, resolved, limit=limit)


@app.get("/api/reports/duplicate-risk")
def duplicate_risk_api(
    path: str, account: str, platform: str | None = None, limit: int = 20
):
    resolved = Path(_resolve_project_path(path))
    if not resolved.exists():
        resolved = _find_output_file(Path(path).name)
    return duplicate_risk(
        ROOT, resolved, account=account, platform=platform, limit=limit
    )


@app.post("/api/winner-dna/refresh")
def refresh_winner_dna_api():
    return refresh_winner_dna(ROOT)


@app.get("/api/winner-dna/leaderboard")
def winner_dna_leaderboard_api(limit: int = 50):
    return winner_dna_leaderboard(ROOT, limit=limit)


@app.post("/api/winner-dna/select")
def winner_dna_select_api(payload: dict):
    """Rank candidate reels by predicted engagement (best-first) before posting.

    Body: {"candidates": [{"id": ..., "features": {"scene": ..., "hook_type": ...}}]}
    """
    from virality_select import rank_candidates

    ranked = rank_candidates(payload.get("candidates") or [], ROOT)
    return {"ranked": ranked, "best": ranked[0] if ranked else None}


@app.get("/api/reports/baseline-vs-recommended")
def baseline_vs_recommended_api(experiment: str = "baseline_vs_recommended"):
    return baseline_vs_recommended_report(ROOT, experiment=experiment)


@app.get("/api/reports/account-fatigue")
def account_fatigue_api(account: str, window: int = 30):
    return account_fatigue_report(ROOT, account=account, window=window)


@app.get("/api/recommendations/decisions")
def recommendation_decisions_api(campaign: str | None = None, limit: int = 50):
    return decision_log(ROOT, campaign=campaign, limit=limit)


@app.get("/api/costs/analytics")
def cost_analytics_api():
    return cost_analytics(ROOT)


@app.post("/api/costs/record")
def record_cost_api(body: dict = Body(...)):
    from winner_dna import record_cost

    output_path = body.get("output_path")
    if output_path:
        try:
            output_path = str(
                _find_output_file(
                    Path(output_path).name
                    if not Path(output_path).is_absolute()
                    else output_path
                )
            )
        except HTTPException:
            output_path = str(_resolve_project_path(output_path))
    return record_cost(
        ROOT,
        entity_type=str(body.get("entity_type") or "final_reel"),
        entity_id=body.get("entity_id"),
        output_path=output_path,
        asset_generation_id=body.get("asset_generation_id"),
        soul_jobs=int(body.get("soul_jobs") or 0),
        kling_jobs=int(body.get("kling_jobs") or 0),
        estimated_generation_cost=body.get("estimated_generation_cost"),
        render_time_sec=body.get("render_time_sec"),
        operator_seconds=body.get("operator_seconds"),
        notes=str(body.get("notes") or ""),
    )


@app.get("/api/experiments/report")
def experiment_report_api(name: str | None = None):
    return experiment_report(ROOT, name)


@app.post("/api/experiments/assign")
def assign_experiment_api(body: dict = Body(...)):
    output_path = body.get("output_path")
    if output_path:
        try:
            output_path = str(
                _find_output_file(
                    Path(output_path).name
                    if not Path(output_path).is_absolute()
                    else output_path
                )
            )
        except HTTPException:
            output_path = str(_resolve_project_path(output_path))
    return assign_experiment(
        ROOT,
        name=str(body.get("name") or "untitled_experiment"),
        group=str(body.get("group") or body.get("group_name") or "control"),
        output_path=output_path,
        asset_generation_id=body.get("asset_generation_id"),
        hypothesis=str(body.get("hypothesis") or ""),
        notes=str(body.get("notes") or ""),
    )


@app.post("/api/export-approved")
def export_approved_api(body: dict = Body(...)):
    account = str(body.get("account") or "default")
    platform = str(body.get("platform") or "ig")
    date = str(body.get("date") or time.strftime("%Y-%m-%d"))
    return export_approved(
        ROOT, account=account, platform=platform, date=date, notes=body.get("notes")
    )


@app.post("/api/posting-ledger/plan")
def posting_ledger_plan_api(body: dict = Body(...)):
    accounts = body.get("accounts") or []
    campaign_id = body.get("campaign_id") or body.get("campaign")
    if not isinstance(accounts, list) or not accounts:
        raise HTTPException(400, "accounts must be a non-empty list")
    if not campaign_id:
        raise HTTPException(400, "campaign_id is required")
    return create_posting_plan(
        ROOT,
        creator=str(body.get("creator") or "Stacey"),
        campaign_id=str(campaign_id),
        accounts=accounts,
        start_date=str(body.get("start_date") or time.strftime("%Y-%m-%d")),
        days=int(body.get("days") or 7),
        platform=str(body.get("platform") or "ig"),
        dry_run=bool(body.get("dry_run", False)),
    )


@app.post("/api/posting-ledger/assign-approved")
def posting_ledger_assign_approved_api(body: dict = Body(...)):
    approved_export = body.get("approved_export") or body.get("path")
    campaign_id = body.get("campaign_id") or body.get("campaign")
    if not approved_export or not campaign_id:
        raise HTTPException(400, "campaign_id and approved_export are required")
    return ledger_assign_approved_reels(
        ROOT,
        campaign_id=str(campaign_id),
        approved_export=Path(str(approved_export)),
        dry_run=bool(body.get("dry_run", False)),
    )


@app.get("/api/posting-ledger/review-queue")
def posting_ledger_review_queue_api(campaign_id: str | None = None):
    return ledger_review_queue(ROOT, campaign_id=campaign_id)


@app.get("/api/posting-ledger/conflicts")
def posting_ledger_conflicts_api(campaign_id: str | None = None):
    return ledger_conflicts(ROOT, campaign_id=campaign_id)


@app.post("/api/posting-ledger/export-schedule")
def posting_ledger_export_schedule_api(body: dict = Body(...)):
    return ledger_export_schedule_package(
        ROOT,
        campaign_id=body.get("campaign_id") or body.get("campaign"),
        date_from=body.get("date_from"),
        date_to=body.get("date_to"),
        dry_run=bool(body.get("dry_run", False)),
    )


@app.post("/api/posting-ledger/transition")
def posting_ledger_transition_api(body: dict = Body(...)):
    slot_id = body.get("posting_slot_id") or body.get("slot_id")
    status = body.get("post_status") or body.get("status")
    if not slot_id or not status:
        raise HTTPException(400, "posting_slot_id and status are required")
    return ledger_transition_slot(
        ROOT,
        str(slot_id),
        str(status),
        actor=str(body.get("actor") or ""),
        notes=str(body.get("notes") or ""),
        approved_by=body.get("approved_by"),
        scheduled_at=body.get("scheduled_at"),
        posted_at=body.get("posted_at"),
        post_url=body.get("post_url"),
        metrics=body.get("metrics") if isinstance(body.get("metrics"), dict) else None,
    )


@app.post("/api/photos/save")
def save_photo_api(body: dict = Body(...)):
    return save_photo_post_asset(
        ROOT,
        source_image=str(body.get("source_image") or body.get("path") or ""),
        account=str(body.get("account") or "default"),
        caption=str(body.get("caption") or ""),
        notes=str(body.get("notes") or ""),
    )


@app.post("/api/threadsdashboard/queue")
def threadsdashboard_queue_api(body: dict = Body(...)):
    output = body.get("output_path") or body.get("filename")
    if not output:
        raise HTTPException(400, "output_path or filename is required")
    return queue_threadsdashboard_post(
        ROOT,
        output_path=str(output),
        account=str(body.get("account") or "default"),
        caption=str(body.get("caption") or ""),
        scheduled_at=body.get("scheduled_at"),
        notes=str(body.get("notes") or ""),
    )


@app.post("/api/clips/{stem}/preview")
def preview_clip(stem: str, body: dict = Body(default={})):
    stem = _safe_stem(stem)
    cmd = [
        sys.executable,
        "reel_pipeline.py",
        "--root",
        str(ROOT),
        "--only-clip",
        stem,
        "--preview",
        "--max-hooks",
        "1",
        "--max-recipes",
        "1",
        "--hook-select",
        "first",
        "--caption-renderer",
        body.get("caption_renderer") or "pillow",
        "--placement-mode",
        body.get("placement_mode") or "source",
    ]
    if body.get("target_ratio"):
        cmd += ["--target-ratios", body["target_ratio"]]
    proc = subprocess.run(
        cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if proc.returncode != 0:
        raise HTTPException(500, proc.stdout[-1500:])
    return {
        "ok": True,
        "preview_url": _latest_preview_url(stem),
        "log": proc.stdout[-2000:],
    }


@app.post("/api/clips/{stem}/whisper-sync")
def whisper_sync_api(stem: str, body: dict = Body(default={})):
    stem = _safe_stem(stem)
    return transcribe_clip(
        ROOT,
        stem,
        backend=body.get("backend") or "mlx-whisper",
        model=body.get("model") or "mlx-community/whisper-small-mlx",
        overwrite=bool(body.get("overwrite")),
    )


@app.get("/api/config")
def get_config():
    return load_config(ROOT)


@app.put("/api/config")
def put_config(body: dict = Body(...)):
    return save_config(ROOT, body)


@app.delete("/api/clips/{stem}")
def delete_clip(stem: str):
    """Remove the source video, its caption sidecar, and any processed outputs."""
    stem = _safe_stem(stem)
    src = RAW_DIR / f"{stem}.mp4"
    if not src.exists():
        raise HTTPException(404, "clip not found")
    src.unlink()
    for ext in ("json", "txt"):
        s = CAP_DIR / f"{stem}.{ext}"
        if s.exists():
            s.unlink()
    proc = PROC_DIR / stem
    if proc.exists():
        shutil.rmtree(proc, ignore_errors=True)
    return {"ok": True}


@app.post("/api/upload")
async def upload_clip(file: UploadFile = File(...)):
    """Accept a dropped video file. Saves as the next clip_NNN.mp4 and creates
    a stub caption JSON so it shows up in the UI ready for hook entry."""
    if not file.filename.lower().endswith((".mp4", ".mov", ".m4v")):
        raise HTTPException(400, "must be .mp4 / .mov / .m4v")

    stem = _next_clip_id()
    dest = RAW_DIR / f"{stem}.mp4"

    # Save uploaded bytes to disk (stream, no full read into memory)
    with dest.open("wb") as out_f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out_f.write(chunk)

    # Stub caption sidecar so the clip appears with an editable hook list
    sidecar = CAP_DIR / f"{stem}.json"
    if not sidecar.exists():
        sidecar.write_text(
            json.dumps(
                {
                    "_uploaded_from": file.filename,
                    "hooks": [],
                    "recipes": None,
                    "caption_color": "auto",
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    return {"ok": True, "stem": stem, "filename": file.filename}


@app.post("/api/spin")
def spin(body: dict = Body(...)):
    base = body.get("base", "")
    n = int(body.get("n", 8))
    return {"variations": spin_hooks(base, n=n)}


@app.get("/api/accounts")
def list_accounts():
    if not ACCT_DIR.exists():
        return []
    out = []
    for j in sorted(ACCT_DIR.glob("*.json")):
        if j.stem.startswith("_"):
            continue
        try:
            data = json.loads(j.read_text())
            out.append(
                {
                    "id": j.stem,
                    "handle": data.get("handle", ""),
                    "voice": data.get("voice", ""),
                    "fonts": data.get("preferred_fonts", []),
                    "styles": data.get("preferred_styles", []),
                }
            )
        except Exception:
            continue
    return out


@app.post("/api/run")
def trigger_run(body: dict = Body(...)):
    with _run_lock:
        if _run_state["running"]:
            return {"ok": False, "error": "already running"}
        _run_state["running"] = True
        _run_state["log"] = []
        _run_state["started"] = time.time()
        _run_state["finished"] = 0.0
        _run_state["summary"] = None
        _run_state["account"] = body.get("account")
        _run_state["completed"] = 0
        _run_state["total"] = 0
        _run_state["failed"] = 0

    cmd = [sys.executable, "reel_pipeline.py", "--root", str(ROOT)]
    if body.get("account"):
        cmd += ["--account", body["account"]]
    if body.get("recipes"):
        cmd += ["--recipes", *body["recipes"]]
    if body.get("text_variation"):
        if body["text_variation"] not in {"off", "auto"}:
            raise HTTPException(400, "text_variation must be off or auto")
        cmd += ["--text-variation", body["text_variation"]]
    if body.get("workers"):
        workers = int(body["workers"])
        if workers < 1 or workers > 8:
            raise HTTPException(400, "workers must be between 1 and 8")
        cmd += ["--workers", str(workers)]
    if body.get("mezzanine"):
        cmd += ["--mezzanine"]
    if body.get("caption_renderer"):
        if body["caption_renderer"] not in {"pillow", "pango"}:
            raise HTTPException(400, "caption_renderer must be pillow or pango")
        cmd += ["--caption-renderer", body["caption_renderer"]]
    if body.get("placement_mode"):
        if body["placement_mode"] not in {"source", "segment"}:
            raise HTTPException(400, "placement_mode must be source or segment")
        cmd += ["--placement-mode", body["placement_mode"]]
    if body.get("output_profile"):
        cmd += ["--output-profile", body["output_profile"]]
    if body.get("target_ratios"):
        ratios = body["target_ratios"]
        if isinstance(ratios, str):
            ratios = [ratios]
        cmd += ["--target-ratios", *[str(r) for r in ratios if r in {"9:16", "4:5"}]]
    if body.get("strict_preflight"):
        cmd += ["--strict-preflight"]
    if body.get("ai_qc"):
        cmd += ["--ai-qc"]
    if body.get("readiness"):
        cmd += ["--readiness"]
    if body.get("campaign"):
        cmd += ["--campaign", str(body.get("campaign"))]
    if body.get("asset_generation_id"):
        cmd += ["--asset-generation-id", str(body.get("asset_generation_id"))]
    if body.get("only_clip"):
        cmd += ["--only-clip", _safe_stem(str(body.get("only_clip")))]

    def runner():
        try:
            p = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in p.stdout:
                _run_state["log"].append(line.rstrip())
                _update_run_progress_from_line(line.rstrip())
                if len(_run_state["log"]) > 1000:
                    _run_state["log"] = _run_state["log"][-1000:]
            p.wait()
            for line in reversed(_run_state["log"]):
                if "summary:" in line:
                    try:
                        j = line[line.index("{") :]
                        _run_state["summary"] = json.loads(
                            j.replace("\\\\", "\\").replace('\\"', '"')
                        )
                    except Exception:
                        pass
                    break
        except Exception as e:
            _run_state["log"].append(f"ERROR: {e}")
        finally:
            _run_state["running"] = False
            _run_state["finished"] = time.time()

    threading.Thread(target=runner, daemon=True).start()
    return {"ok": True}


@app.get("/api/run/status")
def run_status():
    return {
        "running": _run_state["running"],
        "started": _run_state["started"],
        "finished": _run_state["finished"],
        "elapsed": (_run_state["finished"] or time.time()) - _run_state["started"]
        if _run_state["started"]
        else 0,
        "log_tail": _run_state["log"][-60:],
        "summary": _run_state["summary"],
        "completed": _run_state.get("completed", 0),
        "total": _run_state.get("total", 0),
        "failed": _run_state.get("failed", 0),
    }


@app.post("/api/heartbeat")
def heartbeat():
    """Tab tells us it's still open. Resets the auto-shutdown countdown."""
    global _last_heartbeat
    _last_heartbeat = time.time()
    return {"ok": True}


@app.post("/api/shutdown")
def request_shutdown():
    """Tab is closing — exit immediately (sent as a Beacon on pagehide)."""
    global _shutdown_requested
    if not _auto_shutdown_enabled:
        return {"ok": True, "ignored": True}
    _shutdown_requested = True
    # Give the response a chance to flush, then ask uvicorn's process to stop.
    threading.Timer(0.5, _terminate_process).start()
    return {"ok": True}


def _terminate_process() -> None:
    import os
    import signal

    os.kill(os.getpid(), signal.SIGTERM)


@app.get("/file/{path:path}")
def serve_file(path: str):
    full = _safe_in_root(ROOT / path)
    if not full.exists():
        raise HTTPException(404, "not found")
    return FileResponse(full)


# ─────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────
HTML_PATH = ROOT / "static" / "index.html"


@app.get("/")
def home():
    return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))


def _heartbeat_watchdog():
    """Background thread: if the browser tab stops sending heartbeats for
    longer than HEARTBEAT_TIMEOUT, exit the server. Lets the user just
    close the tab to shut everything down."""
    # Initial grace period — give the tab time to load and send its first beat
    time.sleep(HEARTBEAT_TIMEOUT * 1.5)
    while True:
        time.sleep(2)
        if _shutdown_requested:
            print("\n  reel_factory GUI → tab closed, shutting down")
            _terminate_process()
        if time.time() - _last_heartbeat > HEARTBEAT_TIMEOUT:
            print(
                f"\n  reel_factory GUI → no heartbeat for {HEARTBEAT_TIMEOUT}s, shutting down"
            )
            _terminate_process()


def main() -> None:
    global _auto_shutdown_enabled
    _auto_shutdown_enabled = True
    port = 8765
    url = f"http://localhost:{port}"
    print(f"\n  reel_factory GUI → {url}")
    print("  (auto-shuts down when you close the browser tab)\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    threading.Thread(target=_heartbeat_watchdog, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
