"""Higgsfield CLI transport, capability discovery, and result handling."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .asset_prompt_contract import AssetPromptSet
from .generation_asset_models import (
    CAPABILITY_SCHEMA,
    DOWNLOAD_CHUNK_BYTES,
    DOWNLOAD_TIMEOUT_SECONDS,
    IMAGE_MODEL,
    IMAGE_MODEL_CANDIDATES,
    MIN_IMAGE_RESULT_BYTES,
    MIN_VIDEO_RESULT_BYTES,
    VIDEO_MODEL,
    VIDEO_MODEL_CANDIDATES,
    VIDEO_SOUND_MODELS,
)

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text


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


def build_upload_cmd(reference: str) -> list[str]:
    return ["higgsfield", "upload", "create", reference, "--json"]


def build_image_cmd(
    prompt: AssetPromptSet,
    *,
    reference: str | None,
    soul_id: str | None = None,
    model: str = IMAGE_MODEL,
    identity_flag: str = "--custom_reference_id",
    aspect_ratio: str = "9:16",
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


def run_json(cmd: list[str]) -> dict[str, Any]:
    return HiggsfieldCliAdapter().run_json(cmd)


def run_text(cmd: list[str]) -> str:
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


def probe_higgsfield_capabilities(
    root: Path,
    *,
    force: bool = False,
    run_json_call: Callable[[list[str]], dict[str, Any]] = run_json,
    run_text_call: Callable[[list[str]], str] = run_text,
) -> dict[str, Any]:
    path = capabilities_path(root)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    image_models = run_json_call(build_model_list_cmd("image")).get("items", [])
    video_models = run_json_call(build_model_list_cmd("video")).get("items", [])
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
            "generateCreate": run_text_call(
                ["higgsfield", "generate", "create", "--help"]
            ),
            "generateWait": run_text_call(["higgsfield", "generate", "wait", "--help"]),
            "generateGet": run_text_call(["higgsfield", "generate", "get", "--help"]),
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
    root: Path,
    image_model: str = IMAGE_MODEL,
    video_model: str = VIDEO_MODEL,
    *,
    probe_call: Callable[..., dict[str, Any]] = probe_higgsfield_capabilities,
) -> dict[str, Any]:
    capabilities = probe_call(root)
    validation = validate_required_capabilities(capabilities, image_model, video_model)
    if not validation["ok"]:
        raise RuntimeError(
            f"missing required Higgsfield model(s): {', '.join(validation['missing'])}"
        )
    return capabilities


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


def result_credits(data: dict[str, Any]) -> float | None:
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
        return result_credits(usage)
    return None


def generation_completed(data: dict[str, Any]) -> bool:
    if not data:
        return False
    status = extract_status(data)
    return bool(extract_id(data)) and (status in {None, "", "completed"})


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


def resolve_soul_id(
    name: str,
    *,
    run_json_call: Callable[[list[str]], dict[str, Any]] = run_json,
) -> str:
    data = run_json_call(build_soul_list_cmd())
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
