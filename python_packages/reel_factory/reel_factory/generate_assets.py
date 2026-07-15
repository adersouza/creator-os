#!/usr/bin/env python3
"""Generate and track Higgsfield/Kling source assets from clean prompt JSON."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from reel_factory.feature_extract import extract_features
from reel_factory.sqlite_utils import connect_sqlite

from .anatomy_qc import assess_image_qc, is_image_postable
from .asset_prompt_contract import AssetPromptSet, parse_asset_prompt_response
from .campaign_store import (
    connect,
    creator_by_name,
    record_asset_generation,
    validate_generation_soul,
)
from .deprecated_generators import guard_deprecated_generator
from .higgsfield_cost_preflight import (
    consume_higgsfield_spend_reservation,
    nonnegative_float_arg,
    quote_higgsfield_generation,
    reserve_higgsfield_credits,
)
from .identity_verification import verify_identity

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

IMAGE_MODEL = "text2image_soul_v2"
VIDEO_MODEL = "kling3_0"
DEFAULT_GRID_IMAGE_ASPECT_RATIO = "9:16"
DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO = "3:4"
DIRECT_REFERENCE_SEED_PROMPT = (
    "Use the supplied reference image as the visual guide. Recreate the same pose, clothing, setting, "
    "camera framing, lighting, and social-photo mood for this Soul ID model as one realistic {aspect_ratio} image."
)
IMAGE_MODEL_CANDIDATES = ("soul_2", "soul_v2", IMAGE_MODEL)
VIDEO_MODEL_CANDIDATES = (VIDEO_MODEL,)
CAPABILITY_SCHEMA = "reel_factory.higgsfield_capabilities.v1"
VIDEO_SOUND_MODELS = {"kling2_6", "kling3_0"}
DOWNLOAD_TIMEOUT_SECONDS = 60
MIN_IMAGE_RESULT_BYTES = 10_000
MIN_VIDEO_RESULT_BYTES = 100_000
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


class HiggsfieldCommandError(RuntimeError):
    """Raised when the local Higgsfield CLI rejects or fails a command."""

    def __init__(
        self,
        cmd: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
        failure_kind: str = "command_failed",
    ):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.failure_kind = failure_kind
        message = stderr[-2000:] or stdout[-2000:] or f"command failed: {' '.join(cmd)}"
        super().__init__(message)


@dataclass(frozen=True)
class AssetGenerationPlan:
    prompt_json: Path
    stem: str
    reference: str | None
    soul_id: str | None
    soul_name: str | None
    start_image: str | None
    out_dir: Path
    source_dir: Path
    end_image: str | None = None
    video_reference: str | None = None
    campaign: str | None = None
    creator: str | None = None
    selected_panel: str | None = None
    image_mode: str = "single"
    image_aspect_ratio: str = DEFAULT_GRID_IMAGE_ASPECT_RATIO
    image_quality: str = "2k"
    video_aspect_ratio: str = "9:16"
    video_duration: int = 5
    video_mode: str | None = "pro"
    video_sound: str = "off"
    image_model: str = IMAGE_MODEL
    video_model: str = VIDEO_MODEL
    cohort_id: str = "creator_os_default"
    max_credits: float | None = None
    # Compatibility-only report field. Paid provider authorization uses native
    # Higgsfield credits and never this estimate.
    estimated_cost_usd: float | None = None
    allow_unbudgeted_local_test: bool = False
    budget_override_ledger_error: bool = False


@dataclass(frozen=True)
class DirectReferenceImagePlan:
    reference_image: str
    stem: str
    soul_id: str | None
    soul_name: str | None
    out_dir: Path
    source_dir: Path
    creator: str | None = None
    image_aspect_ratio: str = DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO
    image_quality: str = "2k"
    image_model: str = IMAGE_MODEL
    cohort_id: str = "creator_os_default"
    max_credits: float | None = None
    # Compatibility-only report field; see AssetGenerationPlan.
    estimated_cost_usd: float | None = None
    allow_unbudgeted_local_test: bool = False
    budget_override_ledger_error: bool = False


def load_prompt(path: Path) -> AssetPromptSet:
    return parse_asset_prompt_response(path.read_text(encoding="utf-8"))


def lineage_path(plan: AssetGenerationPlan) -> Path:
    return plan.source_dir / f"{plan.stem}.generated_asset_lineage.json"


def build_upload_cmd(reference: str) -> list[str]:
    return ["higgsfield", "upload", "create", reference, "--json"]


def build_image_cmd(
    prompt: AssetPromptSet,
    *,
    reference: str | None,
    soul_id: str | None = None,
    model: str = IMAGE_MODEL,
    identity_flag: str = "--custom_reference_id",
    aspect_ratio: str = DEFAULT_GRID_IMAGE_ASPECT_RATIO,
    quality: str = "2k",
    wait: bool = False,
) -> list[str]:
    cmd = [
        "higgsfield",
        "generate",
        "create",
        model,
        "--prompt",
        prompt.higgsfieldGridPrompt,
    ]
    if soul_id:
        cmd += [identity_flag, soul_id]
    if reference:
        cmd += ["--image", reference]
    if aspect_ratio:
        cmd += ["--aspect_ratio", aspect_ratio]
    if quality:
        cmd += ["--quality", quality]
    if wait:
        cmd.append("--wait")
    cmd.append("--json")
    return cmd


def build_video_cmd(
    prompt: AssetPromptSet,
    *,
    start_image: str | None,
    end_image: str | None = None,
    video_reference: str | None = None,
    model: str = VIDEO_MODEL,
    aspect_ratio: str = "9:16",
    duration: int = 5,
    mode: str | None = "pro",
    sound: str = "off",
    wait: bool = False,
) -> list[str]:
    cmd = [
        "higgsfield",
        "generate",
        "create",
        model,
        "--prompt",
        prompt.klingMotionPrompt,
    ]
    if start_image:
        cmd += ["--start-image", start_image]
    if end_image:
        cmd += ["--end-image", end_image]
    if video_reference:
        cmd += ["--video", video_reference]
    if aspect_ratio:
        cmd += ["--aspect_ratio", aspect_ratio]
    if duration:
        cmd += ["--duration", str(duration)]
    if mode:
        cmd += ["--mode", mode]
    if sound and model in VIDEO_SOUND_MODELS:
        cmd += ["--sound", sound]
    if wait:
        cmd.append("--wait")
    cmd.append("--json")
    return cmd


def build_wait_cmd(job_id: str) -> list[str]:
    return ["higgsfield", "generate", "wait", job_id, "--json"]


def build_get_cmd(job_id: str) -> list[str]:
    return ["higgsfield", "generate", "get", job_id, "--json"]


def reference_matched_video_duration(
    reference: str | Path | None,
    *,
    default: int = 5,
    cap: int = 8,
) -> int:
    if not reference:
        return default
    path = Path(reference)
    if not path.exists() or path.suffix.lower() not in {
        ".mp4",
        ".mov",
        ".m4v",
        ".webm",
    }:
        return default
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        raw = subprocess.check_output(
            [
                ffprobe,
                "-v",
                "0",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        duration = float(raw.decode().strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return default
    if duration <= 0:
        return default
    return max(1, min(cap, round(duration)))


def build_soul_list_cmd() -> list[str]:
    return ["higgsfield", "soul-id", "list", "--json"]


def build_model_list_cmd(kind: str) -> list[str]:
    return ["higgsfield", "model", "list", f"--{kind}", "--json"]


def capabilities_path(root: Path) -> Path:
    return Path(root).resolve() / "project_data" / "higgsfield_capabilities.json"


def _stringify_process_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _classify_higgsfield_failure(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if any(
        token in text
        for token in (
            "quota",
            "credit",
            "billing",
            "rate limit",
            "429",
            "insufficient funds",
        )
    ):
        return "quota"
    if any(token in text for token in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(token in text for token in ("partial", "incomplete", "processing")):
        return "partial"
    return "command_failed"


def _adapter_primary_item(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        if data.get("job_set_type") or data.get("status") or data.get("id"):
            return data
    return None


def _mark_partial_generation(data: dict[str, Any]) -> dict[str, Any]:
    item = _adapter_primary_item(data)
    status = str(item.get("status") or "").lower() if item else ""
    if not status or status == "completed":
        return data
    marked = dict(data)
    marked["_adapter"] = {
        "failureKind": "partial",
        "status": status,
        "message": "Higgsfield returned a non-completed generation response.",
    }
    return marked


class HiggsfieldCliAdapter:
    """Small subprocess boundary for paid Higgsfield/Kling CLI calls."""

    def __init__(self, runner: Any = subprocess.run, timeout_seconds: int = 60 * 30):
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def run_json(self, cmd: list[str]) -> dict[str, Any]:
        try:
            result = self.runner(
                cmd, capture_output=True, text=True, timeout=self.timeout_seconds
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _stringify_process_output(exc.output or exc.stdout)
            stderr = (
                _stringify_process_output(exc.stderr)
                or f"Higgsfield command timed out after {exc.timeout} seconds"
            )
            raise HiggsfieldCommandError(cmd, -1, stdout, stderr, "timeout") from exc
        stdout = _stringify_process_output(getattr(result, "stdout", ""))
        stderr = _stringify_process_output(getattr(result, "stderr", ""))
        returncode = int(getattr(result, "returncode", 1))
        if returncode != 0:
            raise HiggsfieldCommandError(
                cmd,
                returncode,
                stdout,
                stderr,
                _classify_higgsfield_failure(stdout, stderr),
            )
        text = stdout.strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
        payload = data if isinstance(data, dict) else {"items": data}
        return _mark_partial_generation(payload)


def _run_json(cmd: list[str]) -> dict[str, Any]:
    return HiggsfieldCliAdapter().run_json(cmd)


def _run_text(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        stdout = _stringify_process_output(exc.output or exc.stdout)
        stderr = (
            _stringify_process_output(exc.stderr)
            or f"Higgsfield command timed out after {exc.timeout} seconds"
        )
        raise HiggsfieldCommandError(cmd, -1, stdout, stderr, "timeout") from exc
    if result.returncode != 0:
        raise HiggsfieldCommandError(
            cmd,
            result.returncode,
            result.stdout,
            result.stderr,
            _classify_higgsfield_failure(result.stdout, result.stderr),
        )
    return result.stdout


def probe_higgsfield_capabilities(root: Path, *, force: bool = False) -> dict[str, Any]:
    path = capabilities_path(root)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    image_models = _run_json(build_model_list_cmd("image")).get("items", [])
    video_models = _run_json(build_model_list_cmd("video")).get("items", [])
    payload = {
        "schema": CAPABILITY_SCHEMA,
        "createdAt": int(time.time()),
        "commands": {
            "imageModels": build_model_list_cmd("image"),
            "videoModels": build_model_list_cmd("video"),
            "generateCreateHelp": ["higgsfield", "generate", "create", "--help"],
            "generateWaitHelp": ["higgsfield", "generate", "wait", "--help"],
            "generateGetHelp": ["higgsfield", "generate", "get", "--help"],
        },
        "imageModels": image_models,
        "videoModels": video_models,
        "help": {
            "generateCreate": _run_text(["higgsfield", "generate", "create", "--help"]),
            "generateWait": _run_text(["higgsfield", "generate", "wait", "--help"]),
            "generateGet": _run_text(["higgsfield", "generate", "get", "--help"]),
        },
    }
    payload["validation"] = validate_required_capabilities(payload)
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


def _model_types(rows: Any) -> set[str]:
    if not isinstance(rows, list):
        return set()
    keys = {"job_set_type", "id", "model_id"}
    found: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in keys:
            value = row.get(key)
            if value:
                found.add(str(value))
    return found


def _model_row(
    capabilities: dict[str, Any], model: str, *, kind: str
) -> dict[str, Any]:
    rows = capabilities.get("imageModels" if kind == "image" else "videoModels") or []
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ids = {
            str(row.get(key))
            for key in ("job_set_type", "id", "model_id")
            if row.get(key)
        }
        if model in ids:
            return row
    return {}


def _model_params(row: dict[str, Any]) -> set[str]:
    params = row.get("parameters") or row.get("params") or []
    names: set[str] = set()
    if isinstance(params, list):
        for item in params:
            if isinstance(item, dict) and item.get("name"):
                names.add(str(item["name"]))
            elif isinstance(item, str):
                names.add(item)
    elif isinstance(params, dict):
        names.update(str(key) for key in params)
    return names


def select_supported_model(
    capabilities: dict[str, Any],
    candidates: tuple[str, ...],
    fallback: str,
    *,
    kind: str,
) -> str:
    available = _model_types(
        capabilities.get("imageModels" if kind == "image" else "videoModels")
    )
    for candidate in candidates:
        if candidate in available:
            return candidate
    return fallback


def image_identity_flag(capabilities: dict[str, Any], image_model: str) -> str:
    row = _model_row(capabilities, image_model, kind="image")
    params = _model_params(row)
    if "soul_id" in params:
        return "--soul_id"
    return "--custom_reference_id"


def resolve_generation_models(
    capabilities: dict[str, Any],
    image_model: str = IMAGE_MODEL,
    video_model: str = VIDEO_MODEL,
) -> dict[str, str]:
    image_candidates = (
        IMAGE_MODEL_CANDIDATES
        if image_model == IMAGE_MODEL
        else (image_model, *IMAGE_MODEL_CANDIDATES)
    )
    video_candidates = (
        VIDEO_MODEL_CANDIDATES
        if video_model == VIDEO_MODEL
        else (video_model, *VIDEO_MODEL_CANDIDATES)
    )
    resolved_image = select_supported_model(
        capabilities, image_candidates, image_model, kind="image"
    )
    resolved_video = select_supported_model(
        capabilities, video_candidates, video_model, kind="video"
    )
    return {
        "imageModel": resolved_image,
        "videoModel": resolved_video,
        "imageIdentityFlag": image_identity_flag(capabilities, resolved_image),
    }


def validate_required_capabilities(
    capabilities: dict[str, Any],
    image_model: str = IMAGE_MODEL,
    video_model: str = VIDEO_MODEL,
) -> dict[str, Any]:
    resolved = resolve_generation_models(capabilities, image_model, video_model)
    image_ok = resolved["imageModel"] in _model_types(capabilities.get("imageModels"))
    video_ok = resolved["videoModel"] in _model_types(capabilities.get("videoModels"))
    missing = []
    if not image_ok:
        missing.append(image_model)
    if not video_ok:
        missing.append(video_model)
    return {
        "ok": not missing,
        "missing": missing,
        "imageModel": resolved["imageModel"],
        "videoModel": resolved["videoModel"],
        "requestedImageModel": image_model,
        "requestedVideoModel": video_model,
        "imageIdentityFlag": resolved["imageIdentityFlag"],
    }


def ensure_required_capabilities(
    root: Path, image_model: str = IMAGE_MODEL, video_model: str = VIDEO_MODEL
) -> dict[str, Any]:
    capabilities = probe_higgsfield_capabilities(root)
    validation = validate_required_capabilities(capabilities, image_model, video_model)
    if not validation["ok"]:
        raise RuntimeError(
            f"missing required Higgsfield model(s): {', '.join(validation['missing'])}"
        )
    return capabilities


def _looks_like_uuid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F-]{24,}", value))


def _extract_first(data: Any, keys: set[str]) -> str | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in keys and isinstance(value, str) and value:
                return value
        for value in data.values():
            found = _extract_first(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_first(item, keys)
            if found:
                return found
    return None


def _primary_generation_item(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        if data.get("job_set_type") or data.get("status"):
            return data
    return None


def extract_id(data: dict[str, Any]) -> str | None:
    item = _primary_generation_item(data)
    if item and item.get("id"):
        return str(item["id"])
    return _extract_first(data, {"id", "job_id", "jobid", "upload_id", "uploadid"})


def extract_url(data: dict[str, Any]) -> str | None:
    item = _primary_generation_item(data)
    if item:
        status = str(item.get("status") or "").lower()
        if status and status != "completed":
            return None
        for key in ("result_url", "download_url", "url"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
        return None
    return _extract_first(
        data, {"url", "result_url", "resulturl", "download_url", "downloadurl"}
    )


def extract_status(data: dict[str, Any]) -> str | None:
    item = _primary_generation_item(data)
    if item and item.get("status"):
        return str(item["status"]).lower()
    return None


def _result_credits(data: dict[str, Any]) -> float | None:
    item = _primary_generation_item(data) or data
    for key in ("credits", "creditCost", "costCredits", "cost"):
        value = item.get(key) if isinstance(item, dict) else None
        try:
            if value is not None and value != "":
                return float(value)
        except (TypeError, ValueError):
            pass
    usage = item.get("usage") if isinstance(item, dict) else None
    if isinstance(usage, dict):
        return _result_credits(usage)
    return None


def _generation_completed(data: dict[str, Any]) -> bool:
    if not data:
        return False
    status = extract_status(data)
    return bool(extract_id(data)) and (status in {None, "", "completed"})


def _campaign_cost_db_path(root: Path) -> Path:
    env_path = os.environ.get("CAMPAIGN_FACTORY_DB")
    if env_path:
        return Path(env_path).expanduser()
    root = Path(root).expanduser().resolve()
    candidates = [
        root / "campaign_factory.sqlite",
        root.parent / "campaign_factory" / "campaign_factory.sqlite",
        Path(__file__).resolve().parents[2]
        / "campaign_factory"
        / "campaign_factory.sqlite",
    ]
    return candidates[0] if candidates[0].exists() else candidates[-1]


def _load_cost_tracker_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "campaign_factory"
        / "campaign_factory"
        / "cost_tracker.py"
    )
    spec = importlib.util.spec_from_file_location("_creator_os_cost_tracker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load cost tracker from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record_ai_cost_event(
    conn,
    cost_tracker,
    *,
    provider: str,
    operation: str,
    campaign_id: str | None,
    model: str,
    job_id: str,
    actual_credits: float | None,
    lineage_path_text: str,
    stem: str,
    reservation_id: str | None,
    cohort_id: str | None,
) -> str:
    metadata = {
        "schema": "reel_factory.ai_cost_metadata.v1",
        "actualCredits": actual_credits,
        "creditCurrency": "higgsfield_credits",
        "model": model,
        "jobId": job_id,
        "lineagePath": lineage_path_text,
        "stem": stem,
        "spendReservationId": reservation_id,
    }
    return cost_tracker.record_ai_cost(
        conn,
        provider=provider,
        operation=operation,
        campaign_id=campaign_id,
        generations=1,
        metadata=metadata,
        source_event_key=f"reel_factory:{provider}:{operation}:{job_id}",
        reservation_id=reservation_id,
        amount=actual_credits,
        unit="higgsfield_credits" if actual_credits is not None else None,
        cohort_id=cohort_id,
        ensure_schema=False,
    )


def _record_generation_costs(
    plan: AssetGenerationPlan | DirectReferenceImagePlan,
    *,
    lineage_path_text: str,
    records: list[dict[str, Any]],
    reservation_id: str | None = None,
) -> dict[str, Any]:
    events = []
    cost_tracker = _load_cost_tracker_module()
    db_path = _campaign_cost_db_path(plan.source_dir.parent)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(db_path) as conn:
        cost_tracker.ensure_cost_table(conn)
        for record in records:
            raw = record.get("raw")
            if not isinstance(raw, dict) or not _generation_completed(raw):
                continue
            job_id = extract_id(raw)
            if not job_id:
                continue
            provider = str(record["provider"])
            operation = str(record["operation"])
            actual_credits = _result_credits(raw)
            event_id = _record_ai_cost_event(
                conn,
                cost_tracker,
                provider=provider,
                operation=operation,
                campaign_id=getattr(plan, "campaign", None),
                model=str(record["model"]),
                job_id=job_id,
                actual_credits=actual_credits,
                lineage_path_text=lineage_path_text,
                stem=plan.stem,
                reservation_id=reservation_id,
                cohort_id=plan.cohort_id,
            )
            events.append(
                {
                    "eventId": event_id,
                    "provider": provider,
                    "operation": operation,
                    "jobId": job_id,
                    "actualCredits": actual_credits,
                }
            )
    return {"schema": "reel_factory.ai_cost_ledger.v1", "events": events}


def extract_higgsfield_generated_prompt(data: dict[str, Any]) -> str | None:
    item = _primary_generation_item(data)
    if item:
        params = item.get("params")
        if (
            isinstance(params, dict)
            and isinstance(params.get("prompt"), str)
            and params["prompt"].strip()
        ):
            return params["prompt"].strip()
    return _extract_first(data, {"prompt"})


def resolve_soul_id(name: str) -> str:
    data = _run_json(build_soul_list_cmd())
    items = data.get("items", data)
    if not isinstance(items, list):
        raise RuntimeError("unexpected soul-id list response")
    matches = [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("name", "")).lower() == name.lower()
        and str(item.get("status", "")).lower() == "completed"
    ]
    if not matches:
        raise RuntimeError(f"no completed Higgsfield Soul ID named {name!r}")
    if len(matches) > 1:
        ids = ", ".join(str(item.get("id")) for item in matches)
        raise RuntimeError(
            f"multiple completed Higgsfield Soul IDs named {name!r}: {ids}"
        )
    soul_id = matches[0].get("id")
    if not isinstance(soul_id, str) or not soul_id:
        raise RuntimeError(f"Higgsfield Soul ID named {name!r} had no id")
    return soul_id


def _soul_id_for_plan(plan: AssetGenerationPlan, *, dry: bool) -> str | None:
    if plan.soul_id:
        return plan.soul_id
    name = plan.soul_name or plan.creator
    if not name:
        return None
    if dry:
        if name.lower() == "stacey":
            return "5828d958-91dd-4d6d-8909-934503f47644"
        try:
            conn = connect(Path.cwd())
            return str(creator_by_name(conn, name)["soul_id"])
        except Exception:
            return f"<soul_id:{name}>"
    try:
        conn = connect(plan.source_dir.parent)
        return str(creator_by_name(conn, name)["soul_id"])
    except Exception:
        return resolve_soul_id(name)


def _soul_id_for_direct_plan(
    plan: DirectReferenceImagePlan, *, dry: bool
) -> str | None:
    if plan.soul_id:
        return plan.soul_id
    name = plan.soul_name or plan.creator
    if not name:
        return None
    if dry:
        if name.lower() == "stacey":
            return "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
        try:
            conn = connect(Path.cwd())
            return str(creator_by_name(conn, name)["soul_id"])
        except Exception:
            return f"<soul_id:{name}>"
    try:
        conn = connect(plan.source_dir.parent)
        return str(creator_by_name(conn, name)["soul_id"])
    except Exception:
        return resolve_soul_id(name)


def direct_reference_prompt(
    aspect_ratio: str = DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO,
) -> str:
    """Return the only active direct-reference seed prompt.

    Higgsfield receives the reference image through ``--image`` and owns the
    visual interpretation. The active Stacey workflow intentionally does not
    append cleavage/body-emphasis text or feed captured prompts back in.
    """
    prompt = DIRECT_REFERENCE_SEED_PROMPT.format(aspect_ratio=aspect_ratio)
    return " ".join(prompt.split())


def _six_pack_prompts(prompt: AssetPromptSet) -> list[AssetPromptSet]:
    guard_deprecated_generator("six_pack")
    return [
        AssetPromptSet(
            higgsfieldGridPrompt=(
                f"{prompt.higgsfieldGridPrompt}\n\nRender only outfit variation {idx} from the six listed variations. "
                "Same pose, camera angle, room, framing, vertical composition, outfit family, lighting, and body emphasis."
            ),
            klingMotionPrompt=prompt.klingMotionPrompt,
            notes=prompt.notes,
        )
        for idx in range(1, 7)
    ]


def _download_min_bytes(out_path: Path, content_type: str | None) -> int:
    if content_type and content_type.lower().startswith("video/"):
        return MIN_VIDEO_RESULT_BYTES
    if out_path.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm"}:
        return MIN_VIDEO_RESULT_BYTES
    return MIN_IMAGE_RESULT_BYTES


def download_result(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {None, "", "application/octet-stream"} and not (
                content_type.startswith("image/") or content_type.startswith("video/")
            ):
                raise RuntimeError(f"unexpected result content type: {content_type}")
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=out_path.parent,
                prefix=f".{out_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                    tmp.write(chunk)
        min_bytes = _download_min_bytes(out_path, content_type)
        size = tmp_path.stat().st_size if tmp_path else 0
        if size < min_bytes:
            raise RuntimeError(
                f"downloaded result too small: {size} bytes < {min_bytes} bytes"
            )
        tmp_path.replace(out_path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise
    return out_path


def detect_grid_status(image_path: str | Path | None) -> dict[str, Any]:
    guard_deprecated_generator("grid_status_detection")
    if not image_path:
        return {"status": "missing", "isGrid": False}
    path = Path(image_path)
    try:
        with Image.open(path) as im:
            width, height = im.size
    except Exception as exc:
        return {"status": "unreadable", "isGrid": False, "error": str(exc)}
    ratio = width / height if height else 0.0
    is_grid = 0.85 <= ratio <= 1.20 and width >= 900 and height >= 900
    return {
        "status": "native_2x3_grid" if is_grid else "single_image_or_invalid_grid",
        "isGrid": is_grid,
        "width": width,
        "height": height,
        "ratio": ratio,
    }


def single_image_layout_status(image_path: str | Path | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "single_image_layout", "isGrid": False}
    if not image_path:
        return payload
    try:
        with Image.open(Path(image_path)) as im:
            width, height = im.size
    except Exception:
        return payload
    payload.update(
        {
            "width": width,
            "height": height,
            "ratio": width / height if height else 0.0,
        }
    )
    return payload


def dry_run(plan: AssetGenerationPlan, *, wait: bool) -> dict[str, Any]:
    prompt = load_prompt(plan.prompt_json)
    soul_id = _soul_id_for_plan(plan, dry=True)
    image_prompts = (
        _six_pack_prompts(prompt) if plan.image_mode == "six-pack" else [prompt]
    )
    image_cmds = [
        build_image_cmd(
            image_prompt,
            reference=None,
            soul_id=soul_id,
            model=plan.image_model,
            aspect_ratio=plan.image_aspect_ratio,
            quality=plan.image_quality,
            wait=wait,
        )
        for image_prompt in image_prompts
    ]
    video_start = plan.start_image or "<image_job_id>"
    video_cmd = build_video_cmd(
        prompt,
        start_image=video_start,
        end_image=plan.end_image,
        video_reference=plan.video_reference,
        model=plan.video_model,
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        mode=plan.video_mode,
        sound=plan.video_sound,
        wait=wait,
    )
    return {
        "ok": True,
        "dry_run": True,
        "commands": image_cmds + [video_cmd],
        "lineage_path": str(lineage_path(plan)),
    }


def dry_run_image_asset(plan: AssetGenerationPlan, *, wait: bool) -> dict[str, Any]:
    prompt = load_prompt(plan.prompt_json)
    soul_id = _soul_id_for_plan(plan, dry=True)
    image_prompts = (
        _six_pack_prompts(prompt) if plan.image_mode == "six-pack" else [prompt]
    )
    commands = [
        build_image_cmd(
            image_prompt,
            reference=None,
            soul_id=soul_id,
            model=plan.image_model,
            aspect_ratio=plan.image_aspect_ratio,
            quality=plan.image_quality,
            wait=wait,
        )
        for image_prompt in image_prompts
    ]
    return {
        "ok": True,
        "dry_run": True,
        "workflow": "higgsfield_soul_v2_image_only",
        "commands": commands,
        "lineage_path": str(lineage_path(plan)),
    }


def direct_reference_lineage_path(plan: DirectReferenceImagePlan) -> Path:
    return plan.source_dir / f"{plan.stem}.direct_reference_lineage.json"


def dry_run_direct_reference_image(
    plan: DirectReferenceImagePlan, *, wait: bool
) -> dict[str, Any]:
    soul_id = _soul_id_for_direct_plan(plan, dry=True)
    prompt = AssetPromptSet(
        higgsfieldGridPrompt=direct_reference_prompt(plan.image_aspect_ratio),
        klingMotionPrompt="",
        notes="Direct Higgsfield reference-image still; no prompt rewriting, appending, or VLM prompt writing.",
    )
    image_cmd = build_image_cmd(
        prompt,
        reference=plan.reference_image,
        soul_id=soul_id,
        model=plan.image_model,
        aspect_ratio=plan.image_aspect_ratio,
        quality=plan.image_quality,
        wait=wait,
    )
    return {
        "ok": True,
        "dry_run": True,
        "workflow": "higgsfield_direct_reference_image",
        "commands": [image_cmd],
        "lineage_path": str(direct_reference_lineage_path(plan)),
    }


def dry_run_video_asset(plan: AssetGenerationPlan, *, wait: bool) -> dict[str, Any]:
    prompt = load_prompt(plan.prompt_json)
    if not plan.start_image:
        raise ValueError("start_image is required for Kling video dry-run")
    video_cmd = build_video_cmd(
        prompt,
        start_image=plan.start_image,
        end_image=plan.end_image,
        video_reference=plan.video_reference,
        model=plan.video_model,
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        mode=plan.video_mode,
        sound=plan.video_sound,
        wait=wait,
    )
    return {
        "ok": True,
        "dry_run": True,
        "workflow": "kling3_0_video_from_accepted_still",
        "commands": [video_cmd],
        "lineage_path": str(lineage_path(plan)),
    }


def _step(
    name: str, cmd: list[str], response: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"name": name, "command": cmd, "raw": response or {}}


def _failure_raw(exc: HiggsfieldCommandError) -> dict[str, Any]:
    return {
        "error": "higgsfield_command_failed",
        "failureKind": exc.failure_kind,
        "message": str(exc),
        "returnCode": exc.returncode,
        "stdoutTail": exc.stdout[-4000:],
        "stderrTail": exc.stderr[-4000:],
    }


def _record_cost_preflight_block(
    plan: AssetGenerationPlan,
    *,
    prompt: AssetPromptSet,
    cost_preflight: dict[str, Any],
    soul_id: str | None = None,
    soul_name: str | None = None,
) -> dict[str, Any]:
    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=[],
        soul_id=soul_id or plan.soul_id,
        soul_name=soul_name or plan.soul_name,
        local_paths={},
        raw={},
    )
    payload["generation"]["status"] = "cost_preflight_blocked"
    payload["generation"]["failure"] = {
        "stage": "cost_preflight",
        "reason": cost_preflight.get("blockingReason")
        or "higgsfield_cost_preflight_blocked",
    }
    payload["generation"]["costPreflight"] = cost_preflight
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _append_failed_generation(plan, lineage_path=path, lineage=payload)
    return {
        "ok": False,
        "path": str(path),
        "lineage": payload,
        "campaign_record": None,
        "error": payload["generation"]["failure"],
    }


def _cost_preflight_for_plan(
    plan: AssetGenerationPlan | DirectReferenceImagePlan,
    *,
    prompt: AssetPromptSet,
    generation_kind: str,
    resolved_models: dict[str, str],
    asset_count: int = 1,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """Quote the exact request in provider credits, then reserve atomically."""
    if generation_kind not in {"image", "video", "image_and_video"}:
        raise ValueError("generation_kind must be image, video, or image_and_video")
    if asset_count <= 0:
        raise ValueError("asset_count must be positive")
    run_cap = plan.max_credits
    if run_cap is None:
        try:
            run_cap = float(os.environ.get("HIGGSFIELD_RUN_MAX_CREDITS", ""))
        except ValueError:
            run_cap = None
    if run_cap is None or not math.isfinite(run_cap) or not (run_cap > 0):
        return _blocked_credit_preflight("missing_provider_credit_cap")

    try:
        quotes: list[dict[str, Any]] = []
        if generation_kind in {"image", "image_and_video"}:
            image_params = {
                "prompt": prompt.higgsfieldGridPrompt,
                "aspect_ratio": plan.image_aspect_ratio,
                "quality": plan.image_quality,
            }
            if soul_id:
                identity_key = (
                    resolved_models["imageIdentityFlag"].lstrip("-").replace("-", "_")
                )
                image_params[identity_key] = soul_id
            image_quote = quote_higgsfield_generation(
                resolved_models["imageModel"],
                params=image_params,
            )
            image_count = asset_count if generation_kind == "image" else 1
            quotes.extend([image_quote] * image_count)
        if generation_kind in {"video", "image_and_video"}:
            if not isinstance(plan, AssetGenerationPlan):
                raise ValueError("video generation requires AssetGenerationPlan")
            video_params = {
                "prompt": prompt.klingMotionPrompt,
                "aspect_ratio": plan.video_aspect_ratio,
                "duration": str(plan.video_duration),
            }
            if plan.video_mode:
                video_params["mode"] = plan.video_mode
            if plan.video_sound and resolved_models["videoModel"] in VIDEO_SOUND_MODELS:
                video_params["sound"] = plan.video_sound
            quotes.append(
                quote_higgsfield_generation(
                    resolved_models["videoModel"], params=video_params
                )
            )
        provider_quote = _aggregate_provider_quotes(quotes)
        if float(provider_quote["amount"]) > run_cap:
            blocked = _blocked_credit_preflight("provider_quote_exceeds_run_cap")
            blocked["providerQuote"] = provider_quote
            blocked["runCapCredits"] = run_cap
            return blocked
        return reserve_higgsfield_credits(
            provider_quote=provider_quote,
            asset_count=len(quotes),
            cohort_id=plan.cohort_id,
            source=(
                f"reel_factory:{type(plan).__name__}:{generation_kind}:{plan.stem}"
            ),
            root=plan.source_dir.parent,
            cost_db_path=_campaign_cost_db_path(plan.source_dir.parent),
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        return _blocked_credit_preflight(str(exc) or "provider_credit_preflight_failed")


def _aggregate_provider_quotes(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    if not quotes:
        raise ValueError("provider quote set is empty")
    amount = sum(float(quote["amount"]) for quote in quotes)
    return {
        "schema": "reel_factory.higgsfield_provider_quote.v1",
        "provider": "higgsfield",
        "model": "+".join(str(quote.get("model") or "unknown") for quote in quotes),
        "amount": round(amount, 4),
        "unit": "higgsfield_credits",
        "items": quotes,
    }


def _blocked_credit_preflight(reason: str) -> dict[str, Any]:
    return {
        "schema": "reel_factory.higgsfield_cost_preflight.v1",
        "allowed": False,
        "blockingReason": reason,
        "blockingReasons": [reason],
        "reservation": {
            "schema": "reel_factory.higgsfield_spend_reservation.v1",
            "id": None,
            "status": "not_created",
        },
    }


def _cost_reservation_id(cost_preflight: dict[str, Any]) -> str:
    reservation = cost_preflight.get("reservation")
    reservation_id = reservation.get("id") if isinstance(reservation, dict) else None
    if not isinstance(reservation_id, str) or not reservation_id:
        raise RuntimeError(
            "paid generation allowed without an atomic spend reservation"
        )
    return reservation_id


def _consume_cost_reservation(
    plan: AssetGenerationPlan | DirectReferenceImagePlan,
    cost_preflight: dict[str, Any],
) -> str:
    reservation_id = _cost_reservation_id(cost_preflight)
    if not consume_higgsfield_spend_reservation(
        reservation_id,
        root=plan.source_dir.parent,
        cost_db_path=_campaign_cost_db_path(plan.source_dir.parent),
    ):
        raise RuntimeError(
            "spend reservation could not be consumed before provider call"
        )
    reservation = cost_preflight["reservation"]
    reservation["status"] = "consumed"
    return reservation_id


def _record_generation_failure(
    plan: AssetGenerationPlan,
    *,
    prompt: AssetPromptSet,
    commands: list[list[str]],
    steps: list[dict[str, Any]],
    raw: dict[str, Any],
    error: HiggsfieldCommandError,
    stage: str,
    capabilities: dict[str, Any] | None = None,
    soul_id: str | None = None,
    soul_name: str | None = None,
    cost_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failure = _failure_raw(error)
    raw.setdefault("failure", failure)
    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        soul_id=soul_id or plan.soul_id,
        soul_name=soul_name or plan.soul_name,
        local_paths={},
        raw=raw,
    )
    payload["generation"]["status"] = "generation_rejected_or_failed"
    if cost_preflight is not None:
        payload["generation"]["costPreflight"] = cost_preflight
    payload["generation"]["failure"] = {
        "stage": stage,
        "command": error.cmd,
        **failure,
    }
    payload["generation"]["steps"] = steps + [_step(stage, error.cmd, failure)]
    if capabilities:
        payload["generation"]["capabilities"] = {
            "schema": capabilities.get("schema"),
            "createdAt": capabilities.get("createdAt"),
            "validation": validate_required_capabilities(
                capabilities, plan.image_model, plan.video_model
            ),
        }
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _append_failed_generation(plan, lineage_path=path, lineage=payload)
    campaign_record = None
    if plan.campaign or plan.creator:
        campaign_record = record_asset_generation(
            plan.source_dir.parent,
            campaign=plan.campaign,
            creator=plan.creator or soul_name or plan.soul_name,
            prompt_json_path=plan.prompt_json,
            stem=plan.stem,
            lineage_path=path,
            lineage=payload,
        )
    return {
        "ok": False,
        "path": str(path),
        "lineage": payload,
        "campaign_record": campaign_record,
        "error": failure,
    }


def failed_generations_path(root: Path | str) -> Path:
    return Path(root).resolve() / "failed_generations.jsonl"


def _append_failed_generation(
    plan: AssetGenerationPlan | DirectReferenceImagePlan,
    *,
    lineage_path: Path,
    lineage: dict[str, Any],
) -> None:
    generation = lineage.get("generation") if isinstance(lineage, dict) else {}
    failure = generation.get("failure") if isinstance(generation, dict) else {}
    record = {
        "schema": "reel_factory.failed_generation.v1",
        "createdAt": int(time.time()),
        "stem": plan.stem,
        "creator": getattr(plan, "creator", None),
        "campaign": getattr(plan, "campaign", None),
        "status": generation.get("status") if isinstance(generation, dict) else None,
        "failure": failure if isinstance(failure, dict) else {},
        "lineagePath": str(lineage_path),
    }
    path = failed_generations_path(plan.source_dir.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def list_failed_generations(root: Path | str, *, limit: int = 100) -> dict[str, Any]:
    path = failed_generations_path(root)
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows = rows[-max(1, limit) :]
    return {
        "schema": "reel_factory.failed_generations.v1",
        "path": str(path),
        "count": len(rows),
        "items": rows,
    }


def create_assets(
    plan: AssetGenerationPlan, *, wait: bool = False, download: bool = False
) -> dict[str, Any]:
    capabilities = ensure_required_capabilities(
        plan.source_dir.parent, plan.image_model, plan.video_model
    )
    resolved = resolve_generation_models(
        capabilities, plan.image_model, plan.video_model
    )
    prompt = load_prompt(plan.prompt_json)
    commands: list[list[str]] = []
    steps: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    soul_id = _soul_id_for_plan(plan, dry=False)
    cost_preflight = _cost_preflight_for_plan(
        plan,
        prompt=prompt,
        generation_kind="image_and_video",
        resolved_models=resolved,
        soul_id=soul_id,
    )
    if not cost_preflight.get("allowed"):
        return _record_cost_preflight_block(
            plan,
            prompt=prompt,
            cost_preflight=cost_preflight,
            soul_id=soul_id,
            soul_name=plan.soul_name,
        )
    reservation_id = _consume_cost_reservation(plan, cost_preflight)

    upload_id = None

    image_cmd = build_image_cmd(
        prompt,
        reference=None,
        soul_id=soul_id,
        model=resolved["imageModel"],
        identity_flag=resolved["imageIdentityFlag"],
        aspect_ratio=plan.image_aspect_ratio,
        quality=plan.image_quality,
        wait=wait,
    )
    commands.append(image_cmd)
    try:
        raw["image"] = _run_json(image_cmd)
    except HiggsfieldCommandError as exc:
        return _record_generation_failure(
            plan,
            prompt=prompt,
            commands=commands,
            steps=steps,
            raw=raw,
            error=exc,
            stage="image_create",
            capabilities=capabilities,
            soul_id=soul_id,
            soul_name=plan.soul_name,
            cost_preflight=cost_preflight,
        )
    steps.append(_step("image_create", image_cmd, raw["image"]))
    identity_validation = validate_generation_soul(raw["image"], soul_id)
    image_job_id = extract_id(raw["image"])
    image_url = extract_url(raw["image"])

    video_start = plan.start_image or image_job_id or image_url
    video_cmd = build_video_cmd(
        prompt,
        start_image=video_start,
        end_image=plan.end_image,
        video_reference=plan.video_reference,
        model=resolved["videoModel"],
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        mode=plan.video_mode,
        sound=plan.video_sound,
        wait=wait,
    )
    commands.append(video_cmd)
    try:
        raw["video"] = _run_json(video_cmd)
    except HiggsfieldCommandError as exc:
        return _record_generation_failure(
            plan,
            prompt=prompt,
            commands=commands,
            steps=steps,
            raw=raw,
            error=exc,
            stage="video_create",
            capabilities=capabilities,
            soul_id=soul_id,
            soul_name=plan.soul_name,
            cost_preflight=cost_preflight,
        )
    steps.append(_step("video_create", video_cmd, raw["video"]))
    video_job_id = extract_id(raw["video"])
    video_status = extract_status(raw["video"])
    video_url = extract_url(raw["video"])

    local_paths: dict[str, str] = {}
    if download and image_url:
        local_paths["image"] = str(
            download_result(image_url, plan.out_dir / f"{plan.stem}_soul_image")
        )
    if download and video_url:
        local_paths["video"] = str(
            download_result(video_url, plan.out_dir / f"{plan.stem}.mp4")
        )

    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        upload_id=upload_id,
        soul_id=soul_id,
        soul_name=plan.soul_name,
        image_job_id=image_job_id,
        image_result_url=image_url,
        video_job_id=video_job_id,
        video_result_url=video_url,
        local_paths=local_paths,
        raw=raw,
        actual_models=resolved,
    )
    payload["generation"]["identityValidation"] = identity_validation
    payload["generation"]["costPreflight"] = cost_preflight
    payload["generation"]["steps"] = steps
    payload["generation"]["capabilities"] = {
        "schema": capabilities.get("schema"),
        "createdAt": capabilities.get("createdAt"),
        "validation": validate_required_capabilities(
            capabilities, plan.image_model, plan.video_model
        ),
    }
    if identity_validation["status"] == "invalid":
        payload["generation"]["status"] = "invalid_identity"
    if video_status and video_status != "completed":
        payload["generation"]["status"] = "video_failed"
        payload["generation"]["error"] = (
            f"video job {video_job_id or ''} returned status {video_status}".strip()
        )
    video_qc = (
        {"status": "skipped", "reason": "video_job_not_completed", "results": []}
        if video_status and video_status != "completed"
        else generated_video_qc(
            local_paths,
            root=plan.source_dir.parent,
            required=download,
        )
    )
    payload["review"]["generatedVideoQc"] = video_qc
    path = lineage_path(plan)
    payload["generation"]["costLedger"] = _record_generation_costs(
        plan,
        lineage_path_text=str(path),
        records=[
            {
                "provider": "higgsfield",
                "operation": "image_create",
                "model": resolved["imageModel"],
                "raw": raw.get("image"),
            },
            {
                "provider": "kling",
                "operation": "video_create",
                "model": resolved["videoModel"],
                "raw": raw.get("video"),
            },
        ],
        reservation_id=reservation_id,
    )
    if video_qc["status"] == "failed":
        payload["generation"]["status"] = "video_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_video_qc",
            "reason": generated_video_qc_failure_reason(video_qc),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if video_status and video_status != "completed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["error"],
        }
    if video_qc["status"] == "failed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"]["reason"],
        }
    campaign_record = None
    if plan.campaign or plan.creator:
        campaign_record = record_asset_generation(
            plan.source_dir.parent,
            campaign=plan.campaign,
            creator=plan.creator or plan.soul_name,
            prompt_json_path=plan.prompt_json,
            stem=plan.stem,
            lineage_path=path,
            lineage=payload,
        )
    return {
        "ok": True,
        "path": str(path),
        "lineage": payload,
        "campaign_record": campaign_record,
    }


def generated_image_qc(
    local_paths: dict[str, str],
    *,
    root: Path | str,
    required: bool = False,
    creator: str | None = None,
    identity_provider: Any | None = None,
    vision_call=None,
) -> dict[str, Any]:
    image_items = [
        (key, Path(value))
        for key, value in sorted(local_paths.items())
        if key == "image" or key.startswith("variation_")
    ]
    if not image_items:
        return {
            "schema": "reel_factory.generated_image_qc.v1",
            "status": "failed" if required else "skipped",
            "reason": "no_downloaded_images",
            "results": [],
        }
    results = []
    for key, path in image_items:
        assessment = assess_image_qc(path, root=root, vision_call=vision_call)
        identity = (
            verify_identity(
                path, creator=creator, root=root, provider=identity_provider
            )
            if creator
            else {
                "schema": "reel_factory.identity_verification.v1",
                "creator": "",
                "status": "unavailable",
                "score": 0.0,
                "threshold": 0.42,
                "provider": "unavailable",
                "referenceSetId": "",
                "failureReason": "creator_missing",
            }
        )
        identity_postable = identity.get("status") == "passed"
        results.append(
            {
                "key": key,
                "path": str(path),
                "postable": is_image_postable(assessment) and identity_postable,
                "identityVerification": identity,
                **assessment,
            }
        )
    return {
        "schema": "reel_factory.generated_image_qc.v1",
        "status": "passed" if all(row["postable"] for row in results) else "failed",
        "results": results,
    }


def generated_image_qc_failure_reason(qc: dict[str, Any]) -> str:
    for row in qc.get("results") or []:
        if not isinstance(row, dict) or row.get("postable"):
            continue
        identity = row.get("identityVerification")
        if isinstance(identity, dict) and identity.get("status") != "passed":
            reason = identity.get("failureReason") or "identity verification failed"
            return f"generated image failed identity QC: {reason}"
        exposure = row.get("exposure")
        if isinstance(exposure, dict) and not exposure.get("safe", True):
            issues = exposure.get("issues") or []
            return "generated image failed exposure QC" + (
                f": {', '.join(str(item) for item in issues)}" if issues else ""
            )
        anatomy = row.get("anatomy")
        if isinstance(anatomy, dict) and not anatomy.get("plausible", True):
            defects = anatomy.get("defects") or []
            return "generated image failed anatomy QC" + (
                f": {', '.join(str(item) for item in defects)}" if defects else ""
            )
    return "generated image failed anatomy/exposure/identity QC"


def generated_video_qc(
    local_paths: dict[str, str],
    *,
    root: Path | str,
    required: bool = False,
    vision_call=None,
    frame_sampler=None,
) -> dict[str, Any]:
    video_items = [
        (key, Path(value))
        for key, value in sorted(local_paths.items())
        if key == "video"
    ]
    if not video_items:
        return {
            "schema": "reel_factory.generated_video_qc.v1",
            "status": "failed" if required else "skipped",
            "reason": "no_downloaded_video",
            "results": [],
        }
    results = []
    for key, path in video_items:
        try:
            frames = (
                [Path(frame) for frame in frame_sampler(path)]
                if frame_sampler
                else _sample_video_frames(path)
            )
        except Exception as exc:
            results.append(
                {
                    "key": key,
                    "path": str(path),
                    "postable": False,
                    "frames": [],
                    "error": f"video frame sampling failed: {exc}",
                }
            )
            continue
        frame_results = []
        for frame in frames:
            assessment = assess_image_qc(frame, root=root, vision_call=vision_call)
            frame_results.append(
                {
                    "path": str(frame),
                    "postable": is_image_postable(assessment),
                    **assessment,
                }
            )
        results.append(
            {
                "key": key,
                "path": str(path),
                "postable": bool(frame_results)
                and all(row["postable"] for row in frame_results),
                "frames": frame_results,
            }
        )
    return {
        "schema": "reel_factory.generated_video_qc.v1",
        "status": "passed" if all(row["postable"] for row in results) else "failed",
        "results": results,
    }


def _sample_video_frames(path: Path) -> list[Path]:
    from .sscd_video import extract_frames

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        frames = extract_frames(path, temp_dir)
        copied: list[Path] = []
        for idx, frame in enumerate(frames):
            target = path.with_suffix(path.suffix + f".qc_frame_{idx}.jpg")
            target.write_bytes(frame.read_bytes())
            copied.append(target)
        return copied


def generated_video_qc_failure_reason(qc: dict[str, Any]) -> str:
    for row in qc.get("results") or []:
        if not isinstance(row, dict) or row.get("postable"):
            continue
        if row.get("error"):
            return f"generated video failed frame QC: {row['error']}"
        for frame in row.get("frames") or []:
            if not isinstance(frame, dict) or frame.get("postable"):
                continue
            exposure = frame.get("exposure")
            if isinstance(exposure, dict) and not exposure.get("safe", True):
                issues = exposure.get("issues") or []
                return "generated video failed exposure QC" + (
                    f": {', '.join(str(item) for item in issues)}" if issues else ""
                )
            anatomy = frame.get("anatomy")
            if isinstance(anatomy, dict) and not anatomy.get("plausible", True):
                defects = anatomy.get("defects") or []
                return "generated video failed anatomy QC" + (
                    f": {', '.join(str(item) for item in defects)}" if defects else ""
                )
    return "generated video failed anatomy/exposure QC"


def create_image_asset(
    plan: AssetGenerationPlan, *, wait: bool = False, download: bool = True
) -> dict[str, Any]:
    capabilities = ensure_required_capabilities(
        plan.source_dir.parent, plan.image_model, plan.video_model
    )
    resolved = resolve_generation_models(
        capabilities, plan.image_model, plan.video_model
    )
    prompt = load_prompt(plan.prompt_json)
    commands: list[list[str]] = []
    steps: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    soul_id = _soul_id_for_plan(plan, dry=False)
    image_count = 6 if plan.image_mode == "six-pack" else 1
    cost_preflight = _cost_preflight_for_plan(
        plan,
        prompt=prompt,
        generation_kind="image",
        resolved_models=resolved,
        asset_count=image_count,
        soul_id=soul_id,
    )
    if not cost_preflight.get("allowed"):
        return _record_cost_preflight_block(
            plan,
            prompt=prompt,
            cost_preflight=cost_preflight,
            soul_id=soul_id,
            soul_name=plan.soul_name,
        )
    reservation_id = _consume_cost_reservation(plan, cost_preflight)
    upload_id = None
    image_prompts = (
        _six_pack_prompts(prompt) if plan.image_mode == "six-pack" else [prompt]
    )
    image_job_ids: list[str] = []
    image_urls: list[str] = []
    local_paths: dict[str, str] = {}
    raw_images: list[dict[str, Any]] = []
    for idx, image_prompt in enumerate(image_prompts, start=1):
        image_cmd = build_image_cmd(
            image_prompt,
            reference=None,
            soul_id=soul_id,
            model=resolved["imageModel"],
            identity_flag=resolved["imageIdentityFlag"],
            aspect_ratio=plan.image_aspect_ratio,
            quality=plan.image_quality,
            wait=wait,
        )
        commands.append(image_cmd)
        try:
            image_raw = _run_json(image_cmd)
        except HiggsfieldCommandError as exc:
            return _record_generation_failure(
                plan,
                prompt=prompt,
                commands=commands,
                steps=steps,
                raw=raw,
                error=exc,
                stage=f"image_create_{idx:02d}"
                if plan.image_mode == "six-pack"
                else "image_create",
                capabilities=capabilities,
                soul_id=soul_id,
                soul_name=plan.soul_name,
                cost_preflight=cost_preflight,
            )
        raw_images.append(image_raw)
        steps.append(
            _step(
                f"image_create_{idx:02d}"
                if plan.image_mode == "six-pack"
                else "image_create",
                image_cmd,
                image_raw,
            )
        )
        image_job_id = extract_id(image_raw)
        image_url = extract_url(image_raw)
        if image_job_id:
            image_job_ids.append(image_job_id)
        if image_url:
            image_urls.append(image_url)
        if download and image_url:
            if plan.image_mode == "six-pack":
                image_path = (
                    plan.out_dir / f"{plan.stem}_six_pack" / f"variation_{idx:02d}.png"
                )
                key = f"variation_{idx:02d}"
            else:
                image_path = plan.out_dir / f"{plan.stem}_soul_image.png"
                key = "image"
            local_paths[key] = str(download_result(image_url, image_path))
    raw["image"] = (
        raw_images
        if plan.image_mode == "six-pack"
        else (raw_images[0] if raw_images else {})
    )
    image_job_id = image_job_ids[0] if image_job_ids else None
    image_url = image_urls[0] if image_urls else None
    if plan.image_mode == "six-pack":
        first_image = local_paths.get("variation_01")
        if first_image:
            local_paths["image"] = first_image
    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        upload_id=upload_id,
        soul_id=soul_id,
        soul_name=plan.soul_name,
        image_job_id=image_job_id,
        image_result_url=image_url,
        local_paths=local_paths,
        raw=raw,
        actual_models=resolved,
    )
    payload["generation"]["workflow"] = "higgsfield_soul_v2_image_only"
    payload["generation"]["identityValidation"] = validate_generation_soul(
        raw["image"], soul_id
    )
    payload["generation"]["costPreflight"] = cost_preflight
    payload["generation"]["imageJobIds"] = image_job_ids
    payload["generation"]["imageResultUrls"] = image_urls
    payload["generation"]["steps"] = steps
    payload["generation"]["capabilities"] = {
        "schema": capabilities.get("schema"),
        "createdAt": capabilities.get("createdAt"),
        "validation": validate_required_capabilities(
            capabilities, plan.image_model, plan.video_model
        ),
    }
    payload["generation"]["grid"] = (
        single_image_layout_status(local_paths.get("image"))
        if plan.image_mode != "six-pack"
        else {
            "status": "six_pack_separate_images",
            "isGrid": False,
            "count": len([k for k in local_paths if k.startswith("variation_")]),
        }
    )
    qc = generated_image_qc(
        local_paths,
        root=plan.source_dir.parent,
        required=download,
        creator=plan.creator or plan.soul_name,
    )
    payload["review"]["generatedImageQc"] = qc
    path = lineage_path(plan)
    payload["generation"]["costLedger"] = _record_generation_costs(
        plan,
        lineage_path_text=str(path),
        records=[
            {
                "provider": "higgsfield",
                "operation": "image_create",
                "model": resolved["imageModel"],
                "raw": image_raw,
            }
            for image_raw in raw_images
        ],
        reservation_id=reservation_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if qc["status"] == "failed":
        payload["generation"]["status"] = "image_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_image_qc",
            "reason": generated_image_qc_failure_reason(qc),
        }
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"],
        }
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    campaign_record = None
    if plan.campaign or plan.creator:
        campaign_record = record_asset_generation(
            plan.source_dir.parent,
            campaign=plan.campaign,
            creator=plan.creator or plan.soul_name,
            prompt_json_path=plan.prompt_json,
            stem=plan.stem,
            lineage_path=path,
            lineage=payload,
        )
    return {
        "ok": True,
        "path": str(path),
        "lineage": payload,
        "campaign_record": campaign_record,
    }


def create_direct_reference_image_asset(
    plan: DirectReferenceImagePlan,
    *,
    wait: bool = False,
    download: bool = True,
) -> dict[str, Any]:
    capabilities = ensure_required_capabilities(
        plan.source_dir.parent, plan.image_model, VIDEO_MODEL
    )
    resolved = resolve_generation_models(capabilities, plan.image_model, VIDEO_MODEL)
    soul_id = _soul_id_for_direct_plan(plan, dry=False)
    prompt_text = direct_reference_prompt(plan.image_aspect_ratio)
    prompt = AssetPromptSet(
        higgsfieldGridPrompt=prompt_text,
        klingMotionPrompt="",
        notes="Direct Higgsfield reference-image still; no prompt rewriting, appending, or VLM prompt writing.",
    )
    commands: list[list[str]] = []
    steps: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    cost_preflight = _cost_preflight_for_plan(
        plan,
        prompt=prompt,
        generation_kind="image",
        resolved_models=resolved,
        soul_id=soul_id,
    )
    if not cost_preflight.get("allowed"):
        payload = _direct_reference_lineage(
            plan,
            prompt=prompt,
            commands=[],
            steps=[],
            raw={},
            soul_id=soul_id,
            actual_models=resolved,
            status="cost_preflight_blocked",
            failure={
                "stage": "cost_preflight",
                "reason": cost_preflight.get("blockingReason")
                or "higgsfield_cost_preflight_blocked",
            },
        )
        payload["generation"]["costPreflight"] = cost_preflight
        path = direct_reference_lineage_path(plan)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _append_failed_generation(plan, lineage_path=path, lineage=payload)
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"],
        }
    reservation_id = _consume_cost_reservation(plan, cost_preflight)
    image_cmd = build_image_cmd(
        prompt,
        reference=plan.reference_image,
        soul_id=soul_id,
        model=resolved["imageModel"],
        identity_flag=resolved["imageIdentityFlag"],
        aspect_ratio=plan.image_aspect_ratio,
        quality=plan.image_quality,
        wait=wait,
    )
    commands.append(image_cmd)
    try:
        raw["image"] = _run_json(image_cmd)
    except HiggsfieldCommandError as exc:
        failure = _failure_raw(exc)
        payload = _direct_reference_lineage(
            plan,
            prompt=prompt,
            commands=commands,
            steps=steps + [_step("image_create", image_cmd, failure)],
            raw={"image": failure},
            soul_id=soul_id,
            actual_models=resolved,
            status="generation_rejected_or_failed",
            failure={"stage": "image_create", "command": exc.cmd, **failure},
        )
        payload["generation"]["costPreflight"] = cost_preflight
        path = direct_reference_lineage_path(plan)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _append_failed_generation(plan, lineage_path=path, lineage=payload)
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": failure,
        }
    steps.append(_step("image_create", image_cmd, raw["image"]))
    image_job_id = extract_id(raw["image"])
    image_url = extract_url(raw["image"])
    captured_prompt = extract_higgsfield_generated_prompt(raw["image"])
    local_paths: dict[str, str] = {}
    if download and image_url:
        aspect_slug = plan.image_aspect_ratio.replace(":", "x").replace("/", "_")
        local_paths["image"] = str(
            download_result(
                image_url,
                plan.out_dir / f"{plan.stem}_direct_reference_{aspect_slug}.png",
            )
        )
    payload = _direct_reference_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        steps=steps,
        raw=raw,
        soul_id=soul_id,
        actual_models=resolved,
        image_job_id=image_job_id,
        image_result_url=image_url,
        local_paths=local_paths,
        captured_prompt=captured_prompt,
        status="image_completed",
    )
    payload["generation"]["costPreflight"] = cost_preflight
    qc = generated_image_qc(
        local_paths,
        root=plan.source_dir.parent,
        required=download,
        creator=plan.creator or plan.soul_name,
    )
    payload["review"]["generatedImageQc"] = qc
    path = direct_reference_lineage_path(plan)
    payload["generation"]["costLedger"] = _record_generation_costs(
        plan,
        lineage_path_text=str(path),
        records=[
            {
                "provider": "higgsfield",
                "operation": "direct_reference_image_create",
                "model": resolved["imageModel"],
                "raw": raw.get("image"),
            }
        ],
        reservation_id=reservation_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if qc["status"] == "failed":
        payload["generation"]["status"] = "image_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_image_qc",
            "reason": generated_image_qc_failure_reason(qc),
        }
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _append_failed_generation(plan, lineage_path=path, lineage=payload)
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"],
        }
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"ok": True, "path": str(path), "lineage": payload, "campaign_record": None}


def _direct_reference_lineage(
    plan: DirectReferenceImagePlan,
    *,
    prompt: AssetPromptSet,
    commands: list[list[str]],
    steps: list[dict[str, Any]],
    raw: dict[str, Any],
    soul_id: str | None,
    actual_models: dict[str, str],
    status: str,
    image_job_id: str | None = None,
    image_result_url: str | None = None,
    local_paths: dict[str, str] | None = None,
    captured_prompt: str | None = None,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = extract_features(captured_prompt or prompt.higgsfieldGridPrompt)
    creator = (plan.creator or plan.soul_name or "").strip().lower()
    if creator:
        features["creator"] = creator
    return {
        "schema": "reel_factory.direct_reference_image_lineage.v1",
        "createdAt": int(time.time()),
        "source": {
            "stem": plan.stem,
            "referenceImage": plan.reference_image,
            "soulId": soul_id or plan.soul_id,
            "soulName": plan.soul_name,
            "creator": plan.creator,
        },
        "features": features,
        "generation": {
            "tool": "higgsfield_cli",
            "workflow": "higgsfield_direct_reference_image",
            "status": status,
            "models": {"image": actual_models.get("imageModel", plan.image_model)},
            "requestedModels": {"image": plan.image_model},
            "imageIdentityFlag": actual_models.get("imageIdentityFlag"),
            "imageJobId": image_job_id,
            "imageResultUrl": image_result_url,
            "prompts": asdict(prompt),
            "capturedHiggsfieldPrompt": captured_prompt,
            "promptPolicy": {
                "grokUsed": False,
                "qwenUsed": False,
                "ollamaUsed": False,
                "florenceUsed": False,
                "visualSchemaUsed": False,
                "promptAppendUsed": False,
                "capturedPromptReused": False,
                "policy": "reference_image_only",
            },
            "params": {
                "imageAspectRatio": plan.image_aspect_ratio,
                "imageQuality": plan.image_quality,
            },
            "commands": commands,
            "steps": steps,
            "raw": raw,
            "failure": failure,
        },
        "assets": {"localPaths": local_paths or {}},
        "review": {"humanReviewRequired": True},
    }


def create_video_asset(
    plan: AssetGenerationPlan, *, wait: bool = False, download: bool = True
) -> dict[str, Any]:
    capabilities = ensure_required_capabilities(
        plan.source_dir.parent, plan.image_model, plan.video_model
    )
    resolved = resolve_generation_models(
        capabilities, plan.image_model, plan.video_model
    )
    prompt = load_prompt(plan.prompt_json)
    if not plan.start_image:
        raise ValueError("start_image is required for Kling video creation")
    commands: list[list[str]] = []
    steps: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    cost_preflight = _cost_preflight_for_plan(
        plan,
        prompt=prompt,
        generation_kind="video",
        resolved_models=resolved,
    )
    if not cost_preflight.get("allowed"):
        return _record_cost_preflight_block(
            plan,
            prompt=prompt,
            cost_preflight=cost_preflight,
            soul_id=plan.soul_id,
            soul_name=plan.soul_name,
        )
    reservation_id = _consume_cost_reservation(plan, cost_preflight)
    video_cmd = build_video_cmd(
        prompt,
        start_image=plan.start_image,
        end_image=plan.end_image,
        video_reference=plan.video_reference,
        model=resolved["videoModel"],
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        mode=plan.video_mode,
        sound=plan.video_sound,
        wait=wait,
    )
    commands.append(video_cmd)
    try:
        raw["video"] = _run_json(video_cmd)
    except HiggsfieldCommandError as exc:
        return _record_generation_failure(
            plan,
            prompt=prompt,
            commands=commands,
            steps=steps,
            raw=raw,
            error=exc,
            stage="video_create",
            capabilities=capabilities,
            soul_id=plan.soul_id,
            soul_name=plan.soul_name,
            cost_preflight=cost_preflight,
        )
    steps.append(_step("video_create", video_cmd, raw["video"]))
    video_job_id = extract_id(raw["video"])
    video_status = extract_status(raw["video"])
    video_url = extract_url(raw["video"])
    local_paths: dict[str, str] = {}
    if download and video_url:
        local_paths["video"] = str(
            download_result(video_url, plan.out_dir / f"{plan.stem}.mp4")
        )
    payload = build_source_lineage(
        plan,
        prompt=prompt,
        commands=commands,
        soul_id=plan.soul_id,
        soul_name=plan.soul_name,
        video_job_id=video_job_id,
        video_result_url=video_url,
        local_paths=local_paths,
        raw=raw,
        actual_models=resolved,
    )
    payload["generation"]["workflow"] = "kling3_0_video_from_selected_panel"
    payload["generation"]["costPreflight"] = cost_preflight
    payload["generation"]["steps"] = steps
    payload["generation"]["capabilities"] = {
        "schema": capabilities.get("schema"),
        "createdAt": capabilities.get("createdAt"),
        "validation": validate_required_capabilities(
            capabilities, plan.image_model, plan.video_model
        ),
    }
    if video_status and video_status != "completed":
        payload["generation"]["status"] = "video_failed"
        payload["generation"]["error"] = (
            f"video job {video_job_id or ''} returned status {video_status}".strip()
        )
    video_qc = (
        {"status": "skipped", "reason": "video_job_not_completed", "results": []}
        if video_status and video_status != "completed"
        else generated_video_qc(
            local_paths,
            root=plan.source_dir.parent,
            required=download,
        )
    )
    payload["review"]["generatedVideoQc"] = video_qc
    if video_qc["status"] == "failed":
        payload["generation"]["status"] = "video_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_video_qc",
            "reason": generated_video_qc_failure_reason(video_qc),
        }
    path = lineage_path(plan)
    payload["generation"]["costLedger"] = _record_generation_costs(
        plan,
        lineage_path_text=str(path),
        records=[
            {
                "provider": "kling",
                "operation": "video_create",
                "model": resolved["videoModel"],
                "raw": raw.get("video"),
            }
        ],
        reservation_id=reservation_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if video_status and video_status != "completed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["error"],
        }
    if video_qc["status"] == "failed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"]["reason"],
        }
    campaign_record = None
    if plan.campaign or plan.creator:
        campaign_record = record_asset_generation(
            plan.source_dir.parent,
            campaign=plan.campaign,
            creator=plan.creator or plan.soul_name,
            prompt_json_path=plan.prompt_json,
            stem=plan.stem,
            lineage_path=path,
            lineage=payload,
        )
    return {
        "ok": True,
        "path": str(path),
        "lineage": payload,
        "campaign_record": campaign_record,
    }


def build_source_lineage(
    plan: AssetGenerationPlan,
    *,
    prompt: AssetPromptSet,
    commands: list[list[str]],
    upload_id: str | None = None,
    soul_id: str | None = None,
    soul_name: str | None = None,
    image_job_id: str | None = None,
    image_result_url: str | None = None,
    video_job_id: str | None = None,
    video_result_url: str | None = None,
    local_paths: dict[str, str] | None = None,
    raw: dict[str, Any] | None = None,
    actual_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    actual_models = actual_models or {}
    prompt_text = "\n".join(
        value
        for value in (
            prompt.higgsfieldGridPrompt,
            prompt.klingMotionPrompt,
            prompt.notes,
        )
        if value
    )
    features = extract_features(prompt_text)
    creator = (plan.creator or plan.soul_name or "").strip().lower()
    if creator:
        features["creator"] = creator
    return {
        "schema": "reel_factory.generated_asset_lineage.v2",
        "createdAt": int(time.time()),
        "source": {
            "stem": plan.stem,
            "promptSourcePath": str(plan.prompt_json),
            "reference": plan.reference,
            "soulId": soul_id or plan.soul_id,
            "soulName": soul_name or plan.soul_name,
            "selectedPanel": plan.selected_panel,
            "startImage": plan.start_image,
            "endImage": plan.end_image,
            "videoReference": plan.video_reference,
        },
        "features": features,
        "generation": {
            "tool": "higgsfield_cli",
            "workflow": "higgsfield_soul_v2_to_kling3_0",
            "campaign": plan.campaign,
            "creator": plan.creator,
            "models": {
                "image": actual_models.get("imageModel", plan.image_model),
                "video": actual_models.get("videoModel", plan.video_model),
            },
            "requestedModels": {
                "image": plan.image_model,
                "video": plan.video_model,
            },
            "imageIdentityFlag": actual_models.get("imageIdentityFlag"),
            "uploadId": upload_id,
            "soulId": soul_id or plan.soul_id,
            "soulName": soul_name or plan.soul_name,
            "imageJobId": image_job_id,
            "imageResultUrl": image_result_url,
            "videoJobId": video_job_id,
            "videoResultUrl": video_result_url,
            "prompts": asdict(prompt),
            "params": {
                "imageAspectRatio": plan.image_aspect_ratio,
                "imageQuality": plan.image_quality,
                "videoAspectRatio": plan.video_aspect_ratio,
                "videoDuration": plan.video_duration,
                "videoMode": plan.video_mode,
                "videoSound": plan.video_sound,
            },
            "commands": commands,
            "raw": raw or {},
        },
        "assets": {
            "localPaths": local_paths or {},
        },
        "review": {
            "humanReviewRequired": True,
        },
    }


def read_lineage(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def wait_or_status(lineage: Path, *, wait: bool) -> dict[str, Any]:
    data = read_lineage(lineage)
    generation = data.get("generation") or {}
    job_ids = [generation.get("imageJobId"), generation.get("videoJobId")]
    results = {}
    for job_id in [j for j in job_ids if j]:
        cmd = build_wait_cmd(job_id) if wait else build_get_cmd(job_id)
        results[job_id] = _run_json(cmd)
        data.setdefault("generation", {}).setdefault("steps", []).append(
            _step("generate_wait" if wait else "generate_get", cmd, results[job_id])
        )
    data.setdefault("generation", {})["statusResults"] = results
    atomic_write_text(
        lineage, json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"ok": True, "path": str(lineage), "results": results}


def _plan_from_args(args) -> AssetGenerationPlan:
    root = Path(args.root).resolve()
    soul_id = args.soul_id
    soul_name = args.soul_name
    if args.creator and not soul_id and not soul_name:
        soul_name = args.creator
    return AssetGenerationPlan(
        prompt_json=Path(args.prompt_json).expanduser().resolve(),
        stem=args.stem,
        reference=args.reference,
        soul_id=soul_id,
        soul_name=soul_name,
        start_image=args.start_image,
        end_image=args.end_image,
        video_reference=args.video_reference,
        out_dir=(root / args.out_dir).resolve(),
        source_dir=(root / "00_source_videos").resolve(),
        campaign=args.campaign,
        creator=args.creator,
        selected_panel=args.selected_panel,
        image_mode=args.image_mode,
        image_aspect_ratio=args.image_aspect_ratio or DEFAULT_GRID_IMAGE_ASPECT_RATIO,
        image_quality=args.image_quality,
        video_aspect_ratio=args.video_aspect_ratio,
        video_duration=args.video_duration
        if args.video_duration is not None
        else reference_matched_video_duration(
            args.video_reference or args.reference,
            cap=args.max_video_duration,
        ),
        video_mode=None if args.video_mode == "off" else args.video_mode,
        video_sound=args.video_sound,
        image_model=args.image_model,
        video_model=args.video_model,
        cohort_id=args.cohort_id,
        max_credits=args.max_credits,
        estimated_cost_usd=args.estimated_cost_usd,
        allow_unbudgeted_local_test=args.allow_unbudgeted_local_test,
        budget_override_ledger_error=args.budget_override_ledger_error,
    )


def _direct_plan_from_args(args) -> DirectReferenceImagePlan:
    root = Path(args.root).resolve()
    soul_id = args.soul_id
    soul_name = args.soul_name
    if args.creator and not soul_id and not soul_name:
        soul_name = args.creator
    return DirectReferenceImagePlan(
        reference_image=str(Path(args.reference).expanduser().resolve())
        if args.reference
        else "",
        stem=args.stem,
        soul_id=soul_id,
        soul_name=soul_name,
        creator=args.creator,
        out_dir=(root / args.out_dir).resolve(),
        source_dir=(root / "00_source_videos").resolve(),
        image_aspect_ratio=args.image_aspect_ratio
        or DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO,
        image_quality=args.image_quality,
        image_model=args.image_model,
        cohort_id=args.cohort_id,
        max_credits=args.max_credits,
        estimated_cost_usd=args.estimated_cost_usd,
        allow_unbudgeted_local_test=args.allow_unbudgeted_local_test,
        budget_override_ledger_error=args.budget_override_ledger_error,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "mode",
        choices=[
            "create",
            "dry-run",
            "image",
            "image-dry-run",
            "reference-image",
            "reference-image-dry-run",
            "video",
            "video-dry-run",
            "wait",
            "status",
            "capabilities",
            "failed-generations",
        ],
    )
    ap.add_argument("--root", default=".")
    ap.add_argument("--prompt-json")
    ap.add_argument("--stem")
    ap.add_argument("--reference")
    ap.add_argument("--campaign")
    ap.add_argument("--creator")
    ap.add_argument(
        "--soul-id",
        help="Higgsfield Soul ID custom_reference_id, e.g. Stacey's trained Soul ref",
    )
    ap.add_argument(
        "--soul-name",
        help="Resolve a completed Higgsfield Soul ID by name, e.g. Stacey",
    )
    ap.add_argument("--start-image")
    ap.add_argument("--end-image")
    ap.add_argument(
        "--video-reference",
        help="Reference reel/video for models that accept --video, e.g. Seedance 2.0",
    )
    ap.add_argument("--selected-panel")
    ap.add_argument("--image-mode", choices=["single", "six-pack"], default="single")
    ap.add_argument("--out-dir", default="00_source_videos")
    ap.add_argument("--image-aspect-ratio")
    ap.add_argument("--image-quality", default="2k")
    ap.add_argument("--video-aspect-ratio", default="9:16")
    ap.add_argument("--video-duration", type=int, default=None)
    ap.add_argument("--max-video-duration", type=int, default=8)
    ap.add_argument(
        "--video-mode",
        choices=["std", "pro", "4k", "off"],
        default="pro",
        help="Kling quality mode; use 'off' to omit --mode for compatibility",
    )
    ap.add_argument("--video-sound", default="off")
    ap.add_argument("--image-model", default=IMAGE_MODEL)
    ap.add_argument("--video-model", default=VIDEO_MODEL)
    ap.add_argument(
        "--cohort-id",
        default="creator_os_default",
        help="Credit-ledger cohort used for the hard provider cap.",
    )
    ap.add_argument(
        "--max-credits",
        type=nonnegative_float_arg,
        help="Required per-run native-credit ceiling for every paid call.",
    )
    # Retained only so older callers fail over cleanly while reports migrate.
    ap.add_argument("--estimated-cost-usd", type=nonnegative_float_arg)
    ap.add_argument("--allow-unbudgeted-local-test", action="store_true")
    ap.add_argument("--budget-override-ledger-error", action="store_true")
    ap.add_argument("--lineage")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument(
        "--download",
        action="store_true",
        help="download created assets now; generated-video QC runs only on local downloaded video",
    )
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.mode == "capabilities":
        result = probe_higgsfield_capabilities(
            Path(args.root).resolve(), force=args.force
        )
    elif args.mode == "failed-generations":
        result = list_failed_generations(Path(args.root).resolve())
    elif args.mode in {"reference-image", "reference-image-dry-run"}:
        if not args.reference or not args.stem:
            raise SystemExit("--reference and --stem are required")
        if not args.soul_id and not args.soul_name and not args.creator:
            raise SystemExit(
                "--creator, --soul-id, or --soul-name is required so Soul V2 uses the creator identity"
            )
        plan = _direct_plan_from_args(args)
        result = (
            dry_run_direct_reference_image(plan, wait=args.wait)
            if args.mode == "reference-image-dry-run"
            else create_direct_reference_image_asset(
                plan,
                wait=args.wait,
                download=args.download,
            )
        )
    elif args.mode in {"create", "dry-run"}:
        if not args.prompt_json or not args.stem:
            raise SystemExit("--prompt-json and --stem are required")
        if not args.soul_id and not args.soul_name and not args.creator:
            raise SystemExit(
                "--creator, --soul-id, or --soul-name is required so Soul V2 uses the creator identity"
            )
        plan = _plan_from_args(args)
        result = (
            dry_run(plan, wait=args.wait)
            if args.mode == "dry-run"
            else create_assets(
                plan,
                wait=args.wait,
                download=args.download,
            )
        )
    elif args.mode in {"image", "image-dry-run"}:
        if not args.prompt_json or not args.stem:
            raise SystemExit("--prompt-json and --stem are required")
        if not args.soul_id and not args.soul_name and not args.creator:
            raise SystemExit(
                "--creator, --soul-id, or --soul-name is required so Soul V2 uses the creator identity"
            )
        plan = _plan_from_args(args)
        result = (
            dry_run_image_asset(plan, wait=args.wait)
            if args.mode == "image-dry-run"
            else create_image_asset(
                plan,
                wait=args.wait,
                download=args.download,
            )
        )
    elif args.mode in {"video", "video-dry-run"}:
        if not args.prompt_json or not args.stem or not args.start_image:
            raise SystemExit("--prompt-json, --stem, and --start-image are required")
        plan = _plan_from_args(args)
        result = (
            dry_run_video_asset(plan, wait=args.wait)
            if args.mode == "video-dry-run"
            else create_video_asset(
                plan,
                wait=args.wait,
                download=args.download,
            )
        )
    else:
        if not args.lineage:
            raise SystemExit("--lineage is required")
        result = wait_or_status(Path(args.lineage), wait=args.mode == "wait")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
