"""Deterministic request and zero-media prompt identity for motion generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .core import sha256_file
from .persistence import utc_now


def motion_request_fingerprint(
    *,
    model_id: str,
    prompt: str,
    still: Path | None,
    duration_seconds: int | None,
    resolution: str | None,
    seed: int,
    steps: int | None,
    audio_path: Path | None,
    generate_audio: bool,
    last_image_path: Path | None,
    source_video_path: Path | None = None,
    retake_start_frame: int | None = None,
    retake_end_frame: int | None = None,
    extend_frames: int | None = None,
    extend_direction: str = "after",
    preserve_audio: bool = False,
    reference_image_paths: tuple[Path, ...],
    reference_video_paths: tuple[Path, ...],
    enable_prompt_expansion: bool,
    shot_type: str,
    local_model_dir: Path | None,
    motion_task: str,
    motion_lora_path: Path | None,
    motion_lora_strength: float,
    benchmark_recipe: Mapping[str, Any] | None = None,
    analyzer_registry: Mapping[str, Any] | None = None,
    local_motion_admission: Mapping[str, Any] | None = None,
) -> str:
    def media(path: Path | None) -> dict[str, str] | None:
        if path is None:
            return None
        resolved = Path(path).expanduser().resolve()
        return {"path": str(resolved), "sha256": sha256_file(resolved)}

    payload = {
        "modelId": model_id,
        "prompt": prompt,
        "still": media(still),
        "durationSeconds": duration_seconds,
        "resolution": resolution,
        "seed": seed,
        "steps": steps,
        "audio": media(audio_path),
        "generateAudio": generate_audio,
        "lastImage": media(last_image_path),
        "sourceVideo": media(source_video_path),
        "retakeStartFrame": retake_start_frame,
        "retakeEndFrame": retake_end_frame,
        "extendFrames": extend_frames,
        "extendDirection": extend_direction,
        "preserveAudio": preserve_audio,
        "referenceImages": [media(path) for path in reference_image_paths],
        "referenceVideos": [media(path) for path in reference_video_paths],
        "enablePromptExpansion": enable_prompt_expansion,
        "shotType": shot_type,
        "localModelDir": (
            str(Path(local_model_dir).expanduser().resolve())
            if local_model_dir is not None
            else None
        ),
        "motionTask": motion_task,
        "lora": media(motion_lora_path),
        "loraStrength": motion_lora_strength,
        "benchmarkRecipeFingerprint": (
            _canonical_fingerprint(dict(benchmark_recipe))
            if benchmark_recipe is not None
            else None
        ),
        "analyzerRegistryFingerprint": (
            _canonical_fingerprint(dict(analyzer_registry))
            if analyzer_registry is not None
            else None
        ),
        "localMotionAdmissionFingerprint": (
            local_motion_admission.get("admissionFingerprint")
            if local_motion_admission is not None
            else None
        ),
    }
    return _canonical_fingerprint(payload)


def resolve_task_media_path(path: Path | None, label: str) -> Path | None:
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def required_path(path: Path | None, label: str) -> Path:
    if path is None:
        raise RuntimeError(f"{label} missing")
    return path


def text_prompt_source_material(prompt: str) -> dict[str, str]:
    return {
        "taskKind": "text_to_video",
        "prompt": " ".join(str(prompt).split()),
    }


def text_prompt_task_fingerprint(prompt: str) -> str:
    return _canonical_fingerprint(text_prompt_source_material(prompt))


def ensure_text_prompt_source_asset(
    factory: Any,
    *,
    campaign: Mapping[str, Any],
    model_slug: str,
    prompt: str,
    prompt_task_fingerprint: str,
    evidence_dir: Path,
) -> dict[str, Any]:
    """Persist the non-media source identity for one text-to-video request."""

    material = text_prompt_source_material(prompt)
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if (
        _canonical_fingerprint(material) != prompt_task_fingerprint
        or hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        != prompt_task_fingerprint
    ):
        raise RuntimeError("text_prompt_source_fingerprint_mismatch")
    source_dir = evidence_dir.expanduser().resolve() / "prompt_sources"
    source_path = source_dir / f"{prompt_task_fingerprint}.json"
    if source_path.exists() or source_path.is_symlink():
        if (
            source_path.is_symlink()
            or not source_path.is_file()
            or source_path.read_text(encoding="utf-8") != encoded
            or sha256_file(source_path) != prompt_task_fingerprint
        ):
            raise RuntimeError("text_prompt_source_identity_collision")
    else:
        source_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(source_path, encoded, encoding="utf-8")
        if sha256_file(source_path) != prompt_task_fingerprint:
            raise RuntimeError("text_prompt_source_write_hash_mismatch")
    source_path.chmod(0o444)

    existing = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
        (campaign["id"], prompt_task_fingerprint),
    ).fetchone()
    if existing is not None:
        row = dict(existing)
        stored = Path(str(row.get("stored_path") or "")).expanduser().resolve()
        if (
            row.get("media_type") != "prompt"
            or stored != source_path
            or stored.is_symlink()
            or not stored.is_file()
            or sha256_file(stored) != prompt_task_fingerprint
        ):
            raise RuntimeError("text_prompt_existing_source_asset_mismatch")
        return row

    model = factory.conn.execute(
        "SELECT id FROM models WHERE slug = ?", (model_slug,)
    ).fetchone()
    if model is None:
        raise RuntimeError(f"text_prompt_campaign_model_missing:{model_slug}")
    source_id = (
        "src_prompt_"
        + _canonical_fingerprint(
            {
                "campaignId": campaign["id"],
                "promptTaskFingerprint": prompt_task_fingerprint,
            }
        )[:20]
    )
    now = utc_now()
    source_prompt = {
        "schema": "campaign_factory.text_prompt_source.v1",
        "sourceType": "text_prompt_generation",
        "taskKind": "text_to_video",
        "promptTaskFingerprint": prompt_task_fingerprint,
        "executionMediaInputs": [],
    }
    with factory.conn:
        factory.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, content_surface, platform, source_prompt, notes,
             account_ids_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'prompt', 'reel', 'creator_os', ?, ?,
                    '[]', 'imported', ?, ?)
            """,
            (
                source_id,
                campaign["id"],
                model["id"],
                prompt_task_fingerprint,
                str(source_path),
                str(source_path),
                source_path.name,
                json.dumps(source_prompt, ensure_ascii=False, sort_keys=True),
                "Immutable zero-media text-to-video prompt provenance.",
                now,
                now,
            ),
        )
    row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError("text_prompt_source_asset_registration_missing")
    return dict(row)


def _canonical_fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
