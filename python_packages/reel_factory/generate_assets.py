#!/usr/bin/env python3
"""Generate and track Higgsfield/Kling source assets from clean prompt JSON."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from anatomy_qc import assess_image_qc, is_image_postable
from asset_prompt_contract import AssetPromptSet, parse_asset_prompt_response
from campaign_store import (
    connect,
    creator_by_name,
    record_asset_generation,
    validate_generation_soul,
)
from deprecated_generators import guard_deprecated_generator
from higgsfield_cost_preflight import check_higgsfield_cost_preflight
from PIL import Image

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
    video_reference: str | None = None
    campaign: str | None = None
    creator: str | None = None
    selected_panel: str | None = None
    image_mode: str = "single"
    image_aspect_ratio: str = DEFAULT_GRID_IMAGE_ASPECT_RATIO
    image_quality: str = "2k"
    video_aspect_ratio: str = "9:16"
    video_duration: int = 5
    video_sound: str = "off"
    image_model: str = IMAGE_MODEL
    video_model: str = VIDEO_MODEL
    estimated_cost_usd: float | None = None
    allow_unbudgeted_local_test: bool = False


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
    estimated_cost_usd: float | None = None
    allow_unbudgeted_local_test: bool = False


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
    video_reference: str | None = None,
    model: str = VIDEO_MODEL,
    aspect_ratio: str = "9:16",
    duration: int = 5,
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
    if video_reference:
        cmd += ["--video", video_reference]
    if aspect_ratio:
        cmd += ["--aspect_ratio", aspect_ratio]
    if duration:
        cmd += ["--duration", str(duration)]
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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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


def download_result(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, out_path)
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
        video_reference=plan.video_reference,
        model=plan.video_model,
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
        sound=plan.video_sound,
        wait=wait,
    )
    return {
        "ok": True,
        "dry_run": True,
        "commands": image_cmds + [video_cmd],
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
        video_reference=plan.video_reference,
        model=plan.video_model,
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
    include_video: bool = False,
    asset_count: int | None = None,
) -> dict[str, Any]:
    count = asset_count if asset_count is not None else (2 if include_video else 1)
    return check_higgsfield_cost_preflight(
        asset_count=count,
        estimated_cost_usd=plan.estimated_cost_usd,
        allow_unbudgeted_local_test=plan.allow_unbudgeted_local_test,
    )


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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
    cost_preflight = _cost_preflight_for_plan(plan, include_video=True)
    if not cost_preflight.get("allowed"):
        return _record_cost_preflight_block(
            plan,
            prompt=prompt,
            cost_preflight=cost_preflight,
            soul_id=soul_id,
            soul_name=plan.soul_name,
        )

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
        )
    steps.append(_step("image_create", image_cmd, raw["image"]))
    identity_validation = validate_generation_soul(raw["image"], soul_id)
    image_job_id = extract_id(raw["image"])
    image_url = extract_url(raw["image"])

    video_start = plan.start_image or image_job_id or image_url
    video_cmd = build_video_cmd(
        prompt,
        start_image=video_start,
        video_reference=plan.video_reference,
        model=resolved["videoModel"],
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
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
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if video_status and video_status != "completed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["error"],
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
    local_paths: dict[str, str], *, root: Path | str, required: bool = False
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
        assessment = assess_image_qc(path, root=root)
        results.append(
            {
                "key": key,
                "path": str(path),
                "postable": is_image_postable(assessment),
                **assessment,
            }
        )
    return {
        "schema": "reel_factory.generated_image_qc.v1",
        "status": "passed" if all(row["postable"] for row in results) else "failed",
        "results": results,
    }


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
    cost_preflight = _cost_preflight_for_plan(plan, include_video=False)
    if not cost_preflight.get("allowed"):
        return _record_cost_preflight_block(
            plan,
            prompt=prompt,
            cost_preflight=cost_preflight,
            soul_id=soul_id,
            soul_name=plan.soul_name,
        )
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
    qc = generated_image_qc(local_paths, root=plan.source_dir.parent, required=download)
    payload["review"]["generatedImageQc"] = qc
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    if qc["status"] == "failed":
        payload["generation"]["status"] = "image_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_image_qc",
            "reason": "generated image failed anatomy/exposure QC",
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"],
        }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
    cost_preflight = _cost_preflight_for_plan(plan, asset_count=1)
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
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"],
        }
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
        path = direct_reference_lineage_path(plan)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
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
    qc = generated_image_qc(local_paths, root=plan.source_dir.parent, required=download)
    payload["review"]["generatedImageQc"] = qc
    path = direct_reference_lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    if qc["status"] == "failed":
        payload["generation"]["status"] = "image_qc_rejected"
        payload["generation"]["failure"] = {
            "stage": "generated_image_qc",
            "reason": "generated image failed anatomy/exposure QC",
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["failure"],
        }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
    cost_preflight = _cost_preflight_for_plan(plan, asset_count=1)
    if not cost_preflight.get("allowed"):
        return _record_cost_preflight_block(
            plan,
            prompt=prompt,
            cost_preflight=cost_preflight,
            soul_id=plan.soul_id,
            soul_name=plan.soul_name,
        )
    video_cmd = build_video_cmd(
        prompt,
        start_image=plan.start_image,
        video_reference=plan.video_reference,
        model=resolved["videoModel"],
        aspect_ratio=plan.video_aspect_ratio,
        duration=plan.video_duration,
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
    path = lineage_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if video_status and video_status != "completed":
        return {
            "ok": False,
            "path": str(path),
            "lineage": payload,
            "campaign_record": None,
            "error": payload["generation"]["error"],
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
    return {
        "schema": "campaign_factory.generated_asset_lineage.v2",
        "createdAt": int(time.time()),
        "source": {
            "stem": plan.stem,
            "promptSourcePath": str(plan.prompt_json),
            "reference": plan.reference,
            "soulId": soul_id or plan.soul_id,
            "soulName": soul_name or plan.soul_name,
            "selectedPanel": plan.selected_panel,
            "startImage": plan.start_image,
            "videoReference": plan.video_reference,
        },
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
    lineage.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
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
        video_duration=args.video_duration,
        video_sound=args.video_sound,
        image_model=args.image_model,
        video_model=args.video_model,
        estimated_cost_usd=args.estimated_cost_usd,
        allow_unbudgeted_local_test=args.allow_unbudgeted_local_test,
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
        estimated_cost_usd=args.estimated_cost_usd,
        allow_unbudgeted_local_test=args.allow_unbudgeted_local_test,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "mode",
        choices=[
            "create",
            "dry-run",
            "reference-image",
            "reference-image-dry-run",
            "video",
            "video-dry-run",
            "wait",
            "status",
            "capabilities",
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
    ap.add_argument("--video-duration", type=int, default=5)
    ap.add_argument("--video-sound", default="off")
    ap.add_argument("--image-model", default=IMAGE_MODEL)
    ap.add_argument("--video-model", default=VIDEO_MODEL)
    ap.add_argument("--estimated-cost-usd", type=float)
    ap.add_argument("--allow-unbudgeted-local-test", action="store_true")
    ap.add_argument("--lineage")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.mode == "capabilities":
        result = probe_higgsfield_capabilities(
            Path(args.root).resolve(), force=args.force
        )
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
