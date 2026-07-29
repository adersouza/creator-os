"""OpenAI-authored, evidence-bound prompts for Soul and short-form video."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from creator_os_core.fileops import atomic_write_text
from creator_os_core.runtime_paths import resolve_runtime_paths

from .cli_support import _load_env_file

SCHEMA: Final = "campaign_factory.recreation_prompt_pack.v1"
PROMPT_BUILDER_VERSION: Final = "creator_os_openai_prompt_builder.v3"
_API_URL: Final = "https://api.openai.com/v1/responses"
_ANCHOR_FORBIDDEN: Final = (
    "phone",
    "iphone",
    "smartphone",
    "story",
    "screenshot",
    "social media",
    "interface",
    "icon",
    "watermark",
    "caption",
    "overlay",
    "tattoo",
    "hair color",
    "blonde",
    "brunette",
)
_NEGATIVE_LANGUAGE = re.compile(
    r"\bnegative[_ -]?prompts?\b"
    r"|\b(?:no|not|avoid|without|never|exclude|prevent|prohibit)\b"
    r"|\bdo\s+not\b|\bdon['’]t\b|\bmustn['’]t\b|\bshouldn['’]t\b",
    flags=re.IGNORECASE,
)


def build_openai_prompt_pack(
    *,
    creator: str,
    creator_image: Path,
    intent: str,
    reference_video: Path | None = None,
    model: str | None = None,
    api_key: str | None = None,
    cache_root: Path | None = None,
    external_call_authorized: bool = False,
) -> dict[str, Any]:
    """Ask one vision model for a Soul anchor and exact provider prompts."""

    image = _regular_file(creator_image, "creator image")
    video = (
        _regular_file(reference_video, "reference video")
        if reference_video is not None
        else None
    )
    selected_model = model or os.environ.get("CREATOR_OS_OPENAI_PROMPT_MODEL", "gpt-5")
    instruction = _instruction(intent, bool(video))
    request_core = {
        "schema": "campaign_factory.openai_prompt_request.v1",
        "builderVersion": PROMPT_BUILDER_VERSION,
        "creator": creator.strip().lower(),
        "intent": intent,
        "model": selected_model,
        "creatorImageSha256": _sha256(image),
        "referenceVideoSha256": _sha256(video) if video else None,
        "instruction": instruction,
        "responseSchema": _response_schema(),
    }
    request_fingerprint = _fingerprint(request_core)
    cache_path = _prompt_cache_path(request_fingerprint, cache_root=cache_root)
    cached = _load_cached_prompt_pack(cache_path, request_fingerprint)
    if cached is not None:
        return {
            **cached,
            "cache": {
                "status": "hit",
                "path": str(cache_path),
                "providerCallMade": False,
                "promptCallAuthorization": {
                    "authorized": bool(external_call_authorized),
                    "scope": "request_fingerprint",
                    "requestFingerprint": request_fingerprint,
                    "maximumCalls": 1,
                    "cacheCheckedFirst": True,
                    "currentRunCalls": 0,
                },
            },
        }

    if not external_call_authorized:
        raise PermissionError("openai_prompt_call_authorization_required")
    key = api_key or _openai_api_key()
    if not key:
        raise RuntimeError("openai_prompt_generation_key_missing")
    authorization = _authorize_openai_prompt_call(
        request_core,
        request_fingerprint=request_fingerprint,
        cache_path=cache_path,
    )

    with tempfile.TemporaryDirectory(prefix="creator-os-prompt-frames-") as raw_tmp:
        frames = _sample_frames(video, Path(raw_tmp)) if video else []
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": instruction},
            {
                "type": "input_image",
                "detail": "high",
                "image_url": _data_url(image),
            },
        ]
        content.extend(
            {
                "type": "input_image",
                "detail": "high",
                "image_url": _data_url(frame),
            }
            for frame in frames
        )
        response = _post_responses(
            {
                "model": selected_model,
                "store": False,
                "max_output_tokens": 4000,
                "input": [{"role": "user", "content": content}],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "creator_os_prompt_pack",
                        "strict": True,
                        "schema": _response_schema(),
                    }
                },
            },
            api_key=key,
        )

    value = _response_json(response)
    anchor_prompt = _validated_anchor_prompt(str(value["anchorPrompt"]))
    seedance_prompt = _validated_positive_prompt(
        str(value["seedancePrompt"]), "seedance"
    )
    kling_prompt = _validated_positive_prompt(str(value["klingPrompt"]), "kling")
    if not kling_prompt or len(kling_prompt) > 2500:
        raise ValueError("openai_kling_prompt_must_be_1_to_2500_characters")
    timeline = [
        {
            **item,
            "action": _validated_positive_prompt(
                str(item["action"]), f"timeline_action_{index}"
            ),
            "camera": _validated_positive_prompt(
                str(item["camera"]), f"timeline_camera_{index}"
            ),
        }
        for index, item in enumerate(value["timeline"])
    ]
    core = {
        "schema": SCHEMA,
        "creator": creator.strip().lower(),
        "intent": intent,
        "provider": "openai",
        "model": selected_model,
        "promptPlanning": {
            "builderVersion": PROMPT_BUILDER_VERSION,
            "requestFingerprint": request_fingerprint,
            "responseId": str(response.get("id") or "") or None,
            "usage": _json_record(response.get("usage")),
            "cost": _response_cost(response),
            "authorization": authorization,
        },
        "creatorImage": {
            "sha256": _sha256(image),
            "path": str(image),
        },
        "referenceVideo": (
            {"sha256": _sha256(video), "path": str(video)} if video else None
        ),
        "anchorPrompt": anchor_prompt,
        "seedancePrompt": seedance_prompt,
        "klingPrompt": kling_prompt,
        "timeline": timeline,
        "identityPolicy": {
            "identitySource": "approved_creator_image_or_soul",
            "hairColorInvented": False,
            "tattoosInvented": False,
            "permanentFeaturesInvented": False,
        },
        "providerPlans": {
            "seedance": {
                "model": "seedance_2_0",
                "resolution": "480p",
                "mode": "fast",
                "bitrateMode": "high",
                "generateAudio": False,
                "conditioning": (
                    "approved_anchor_image_reference_plus_authorized_video_reference"
                    "_and_creator_element_prompt_token"
                    if video
                    else "approved_anchor_image_and_prompt"
                ),
            },
            "kling": {
                "model": "kling3_0_turbo",
                "resolution": "720p",
                "generateAudio": False,
                "conditioning": "approved_anchor_image_and_prompt",
                "promptCharacterLimit": 2500,
                "executionStatus": "planning_only_not_connected_for_recreation",
            },
        },
    }
    pack = {**core, "promptPackFingerprint": _fingerprint(core)}
    _write_prompt_cache(cache_path, pack)
    return {
        **pack,
        "cache": {
            "status": "miss",
            "path": str(cache_path),
            "providerCallMade": True,
            "promptCallAuthorization": {
                "authorized": True,
                "scope": "request_fingerprint",
                "requestFingerprint": request_fingerprint,
                "maximumCalls": 1,
                "cacheCheckedFirst": True,
                "currentRunCalls": 1,
            },
        },
    }


def validate_prompt_pack(value: dict[str, Any]) -> dict[str, Any]:
    core = {
        key: item
        for key, item in value.items()
        if key not in {"promptPackFingerprint", "cache"}
    }
    if core.get("schema") != SCHEMA or value.get(
        "promptPackFingerprint"
    ) != _fingerprint(core):
        raise ValueError("recreation_prompt_pack_invalid")
    _validated_anchor_prompt(str(core.get("anchorPrompt") or ""))
    _validated_positive_prompt(str(core.get("seedancePrompt") or ""), "seedance")
    kling = _validated_positive_prompt(str(core.get("klingPrompt") or ""), "kling")
    if not kling or len(kling) > 2500:
        raise ValueError("recreation_kling_prompt_invalid")
    for index, item in enumerate(core.get("timeline") or []):
        _validated_positive_prompt(
            str(item.get("action") or ""), f"timeline_action_{index}"
        )
        _validated_positive_prompt(
            str(item.get("camera") or ""), f"timeline_camera_{index}"
        )
    planning = core.get("promptPlanning")
    if (
        not isinstance(planning, dict)
        or planning.get("builderVersion") != PROMPT_BUILDER_VERSION
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(planning.get("requestFingerprint") or "")
        )
    ):
        raise ValueError("recreation_prompt_planning_lineage_invalid")
    return value


def compile_video_prompt(
    prompt_pack: dict[str, Any],
    provider_model: str,
    prompt_card: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind the provider-specific prompt and pack fingerprint to one job."""

    prompt_text = str(
        prompt_pack[
            "klingPrompt" if provider_model == "kling3_0_turbo" else "seedancePrompt"
        ]
    )
    card = {
        **prompt_card,
        "openaiPromptPackFingerprint": prompt_pack["promptPackFingerprint"],
    }
    card["promptCardFingerprint"] = _fingerprint(card)
    return card, {
        "schema": "campaign_factory.openai_video_prompt.v1",
        "text": prompt_text,
        "compiledPromptFingerprint": _fingerprint(
            {
                "text": prompt_text,
                "promptPackFingerprint": prompt_pack["promptPackFingerprint"],
                "providerModel": provider_model,
            }
        ),
    }


def _instruction(intent: str, has_reference_video: bool) -> str:
    source = (
        "The first image is the approved creator identity. The remaining images are "
        "chronological samples from one authorized reference Reel."
        if has_reference_video
        else "The image is the approved creator identity for a calm short animation."
    )
    action = (
        "Copy the reference Reel's chronological actions, timing, framing, camera "
        "behavior, setting category, wardrobe category, and performance energy."
        if has_reference_video
        else "Invent one attractive, realistic 9:16 scene and pose that will animate "
        "well with calm eye, head, breathing, hair, and small hand movements."
    )
    return (
        f"{source} {action} Return an anchorPrompt for Higgsfield Soul 2, a detailed "
        "Seedance 2 Fast prompt, a Kling 3 Turbo prompt with a 2500-character "
        f"maximum, and a chronological timeline. Intent: {intent}. "
        "The anchor prompt describes adult-coded pose, wardrobe, setting, lighting, "
        "framing, and composition using affirmative desired-result language. The "
        "approved creator image exclusively supplies identity, face, skin tone, "
        "hair, tattoos, beauty marks, and permanent body details, so the anchor "
        "prompt stays focused on the scene and composition. Video prompts explicitly "
        "use the approved anchor as the exact person, preserve every visible identity "
        "and permanent feature, and describe only desired visuals, movement, timing, "
        "and camera behavior in affirmative language. Provider settings control "
        "audio separately. Source writing stays outside the generated prompts."
    )


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "anchorPrompt",
            "seedancePrompt",
            "klingPrompt",
            "timeline",
        ],
        "properties": {
            "anchorPrompt": {"type": "string"},
            "seedancePrompt": {"type": "string"},
            "klingPrompt": {"type": "string", "maxLength": 2500},
            "timeline": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["startSeconds", "endSeconds", "action", "camera"],
                    "properties": {
                        "startSeconds": {"type": "number"},
                        "endSeconds": {"type": "number"},
                        "action": {"type": "string"},
                        "camera": {"type": "string"},
                    },
                },
            },
        },
    }


def _post_responses(payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        _API_URL,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", "replace")
        raise RuntimeError(
            f"openai_prompt_generation_failed:{exc.code}:{detail}"
        ) from None
    if not isinstance(value, dict):
        raise RuntimeError("openai_prompt_generation_returned_non_object")
    return value


def _response_json(response: dict[str, Any]) -> dict[str, Any]:
    for item in response.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict) or content.get("type") != "output_text":
                continue
            value = json.loads(str(content.get("text") or ""))
            if isinstance(value, dict):
                return value
    raise RuntimeError("openai_prompt_generation_output_missing")


def _prompt_cache_path(request_fingerprint: str, *, cache_root: Path | None) -> Path:
    root = (
        cache_root
        if cache_root is not None
        else resolve_runtime_paths().state_root / "openai_prompt_packs"
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root.resolve() / f"{request_fingerprint}.json"


def _load_cached_prompt_pack(
    path: Path, request_fingerprint: str
) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    planning = value.get("promptPlanning")
    if (
        not isinstance(planning, dict)
        or planning.get("requestFingerprint") != request_fingerprint
    ):
        return None
    try:
        validate_prompt_pack(value)
    except ValueError:
        return None
    return value


def _write_prompt_cache(path: Path, pack: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(pack, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _authorize_openai_prompt_call(
    request_core: dict[str, Any],
    *,
    request_fingerprint: str,
    cache_path: Path,
) -> dict[str, Any]:
    """Persist and verify a signed one-call maximum before a paid API request."""

    secret = str(os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET") or "")
    if len(secret.encode()) < 32:
        raise RuntimeError("openai_prompt_spend_authorization_secret_missing")
    quote_raw = str(os.environ.get("CREATOR_OS_OPENAI_PROMPT_QUOTE_USD") or "")
    try:
        quote_usd = float(quote_raw)
    except ValueError as exc:
        raise RuntimeError("openai_prompt_spend_quote_missing") from exc
    if not math.isfinite(quote_usd) or quote_usd <= 0:
        raise RuntimeError("openai_prompt_spend_quote_missing")
    issued = datetime.now(UTC)
    authorization_id = f"openaiauth_{uuid.uuid4().hex}"
    attempt_id = f"openaiattempt_{uuid.uuid4().hex}"
    core = {
        "schema": "campaign_factory.openai_prompt_spend_authorization.v1",
        "authorizationId": authorization_id,
        "attemptId": attempt_id,
        "issuer": "campaign_factory",
        "status": "authorized",
        "issuedAt": issued.isoformat(),
        "expiresAt": (issued + timedelta(minutes=5)).isoformat(),
        "scope": {
            "provider": "openai",
            "model": request_core["model"],
            "operation": "recreation_prompt_pack",
            "requestFingerprint": request_fingerprint,
            "maximumCalls": 1,
            "creatorImageSha256": request_core["creatorImageSha256"],
            "referenceVideoSha256": request_core["referenceVideoSha256"],
        },
        "quote": {
            "provider": "openai",
            "model": request_core["model"],
            "amount": quote_usd,
            "unit": "USD",
            "quoteClass": "operator_configured_maximum",
            "source": "CREATOR_OS_OPENAI_PROMPT_QUOTE_USD",
        },
    }
    signature = hmac.new(
        secret.encode(),
        _canonical_json(core).encode(),
        hashlib.sha256,
    ).hexdigest()
    receipt = {
        **core,
        "signature": {
            "algorithm": "HMAC-SHA256",
            "value": signature,
        },
    }
    _verify_openai_prompt_authorization(
        receipt,
        secret=secret,
        request_fingerprint=request_fingerprint,
    )
    authorization_root = cache_path.parent / "authorizations"
    authorization_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(authorization_root, 0o700)
    receipt_path = authorization_root / f"{request_fingerprint}.{authorization_id}.json"
    receipt_text = json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n"
    atomic_write_text(receipt_path, receipt_text, encoding="utf-8")
    os.chmod(receipt_path, 0o600)
    return {
        "authorizationId": authorization_id,
        "attemptId": attempt_id,
        "status": "authorized",
        "requestFingerprint": request_fingerprint,
        "maximumCalls": 1,
        "quote": core["quote"],
        "receiptPath": str(receipt_path),
        "receiptSha256": hashlib.sha256(receipt_text.encode()).hexdigest(),
        "signatureAlgorithm": "HMAC-SHA256",
    }


def _verify_openai_prompt_authorization(
    receipt: dict[str, Any],
    *,
    secret: str,
    request_fingerprint: str,
) -> None:
    signature = receipt.get("signature")
    if not isinstance(signature, dict) or signature.get("algorithm") != "HMAC-SHA256":
        raise PermissionError("openai_prompt_spend_authorization_invalid")
    core = {key: value for key, value in receipt.items() if key != "signature"}
    expected = hmac.new(
        secret.encode(),
        _canonical_json(core).encode(),
        hashlib.sha256,
    ).hexdigest()
    scope = core.get("scope")
    if (
        not hmac.compare_digest(str(signature.get("value") or ""), expected)
        or not isinstance(scope, dict)
        or core.get("status") != "authorized"
        or scope.get("requestFingerprint") != request_fingerprint
        or scope.get("maximumCalls") != 1
        or datetime.fromisoformat(str(core.get("expiresAt"))) <= datetime.now(UTC)
    ):
        raise PermissionError("openai_prompt_spend_authorization_invalid")


def _json_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return json.loads(json.dumps(value))


def _response_cost(response: dict[str, Any]) -> dict[str, Any]:
    raw = response.get("cost")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return {"status": "reported", "usd": float(raw)}
    if isinstance(raw, dict):
        usd = raw.get("usd")
        if isinstance(usd, (int, float)) and not isinstance(usd, bool):
            return {"status": "reported", "usd": float(usd)}
    return {"status": "not_exposed", "usd": None}


def _sample_frames(video: Path, output_dir: Path, *, count: int = 6) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg_and_ffprobe_required_for_openai_reel_prompting")
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("openai_reel_duration_probe_failed") from exc
    if probe.returncode != 0 or duration <= 0:
        raise RuntimeError("openai_reel_duration_probe_failed")
    pattern = output_dir / "frame-%02d.jpg"
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={count / duration},scale=512:-2",
            "-frames:v",
            str(count),
            str(pattern),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    frames = sorted(output_dir.glob("frame-*.jpg"))
    if completed.returncode != 0 or len(frames) < 2:
        raise RuntimeError("openai_reel_frame_sampling_failed")
    return frames


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _validated_anchor_prompt(value: str) -> str:
    prompt = _validated_positive_prompt(value, "anchor")
    lower = prompt.lower()
    found = [
        token
        for token in _ANCHOR_FORBIDDEN
        if re.search(rf"\b{re.escape(token)}\b", lower)
    ]
    if found:
        raise ValueError(f"openai_anchor_prompt_contains_identity_or_ui_terms:{found}")
    return prompt


def _validated_positive_prompt(value: str, label: str) -> str:
    prompt = " ".join(value.split())
    if not prompt:
        raise ValueError(f"openai_{label}_prompt_missing")
    match = _NEGATIVE_LANGUAGE.search(prompt)
    if match:
        raise ValueError(
            f"openai_{label}_prompt_contains_negative_language:{match.group(0)}"
        )
    return prompt


def _openai_api_key() -> str | None:
    runtime = resolve_runtime_paths()
    return os.environ.get("OPENAI_API_KEY") or _load_env_file(
        runtime.config_root / "generation.env"
    ).get("OPENAI_API_KEY")


def _regular_file(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
