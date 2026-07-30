"""Operator approval command for exact recreation-anchor bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from creator_os_core.recreation_anchor_approval import (
    write_recreation_anchor_approval,
)
from PIL import Image, UnidentifiedImageError

from .production_prompts import require_creator_soul_id
from .production_source_selection import active_production_identity
from .recreation_prompting import validate_prompt_pack


def approve_recreation_anchor(
    *,
    factory: Any | None = None,
    creator: str,
    anchor_file: Path,
    anchor_generation_id: str,
    prompt_pack_path: Path,
    selected_composition_frame_sha256: str,
    approved_by: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Approve one downloaded Soul 2 anchor against its full prompt lineage."""

    creator_slug, soul_id = (
        active_production_identity(factory, creator)
        if factory is not None
        else require_creator_soul_id(creator)
    )
    anchor = _regular_file(anchor_file, "anchor file")
    try:
        with Image.open(anchor) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("recreation_anchor_file_is_not_an_image") from exc
    prompt_path = _regular_file(prompt_pack_path, "prompt pack")
    try:
        prompt_pack = json.loads(prompt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("recreation_prompt_pack_invalid") from exc
    if not isinstance(prompt_pack, dict):
        raise ValueError("recreation_prompt_pack_invalid")
    prompt_pack = validate_prompt_pack(prompt_pack)
    creator_image = prompt_pack.get("creatorImage")
    reference_video = prompt_pack.get("referenceVideo")
    if (
        prompt_pack.get("creator") != creator_slug
        or not isinstance(creator_image, dict)
        or not isinstance(reference_video, dict)
    ):
        raise PermissionError("recreation_anchor_prompt_pack_binding_mismatch")
    prompt_pack_id = str(
        (prompt_pack.get("promptPlanning") or {}).get("responseId") or ""
    ).strip() or str(prompt_pack["promptPackFingerprint"])
    candidate_source_id: str | None = None
    if factory is not None:
        digest = hashlib.sha256(anchor.read_bytes()).hexdigest()
        row = factory.conn.execute(
            """
            SELECT id, source_prompt, higgsfield_job_id, status FROM source_assets
            WHERE content_hash = ? AND media_type = 'image'
            ORDER BY created_at DESC LIMIT 1
            """,
            (digest,),
        ).fetchone()
        if (
            row is None
            or str(row["higgsfield_job_id"] or "") != anchor_generation_id
            or str(row["status"] or "") == "rejected"
        ):
            raise PermissionError("recreation_anchor_generation_registration_missing")
        lineage = json.loads(str(row["source_prompt"] or "{}"))
        if (
            lineage.get("schema") != "campaign_factory.recreation_anchor_candidate.v1"
            or lineage.get("promptPackFingerprint")
            != prompt_pack["promptPackFingerprint"]
            or lineage.get("creatorImageSha256")
            != str(creator_image.get("sha256") or "")
            or lineage.get("referenceVideoSha256")
            != str(reference_video.get("sha256") or "")
            or lineage.get("anchorSha256") != digest
        ):
            raise PermissionError("recreation_anchor_generation_lineage_mismatch")
        candidate_source_id = str(row["id"])
    receipt = write_recreation_anchor_approval(
        output_dir=output_dir,
        creator=creator_slug,
        soul_id=soul_id,
        anchor_generation_id=anchor_generation_id,
        anchor_file=anchor,
        prompt_pack_id=prompt_pack_id,
        prompt_pack_fingerprint=str(prompt_pack["promptPackFingerprint"]),
        anchor_prompt_fingerprint=hashlib.sha256(
            str(prompt_pack["anchorPrompt"]).encode("utf-8")
        ).hexdigest(),
        creator_image_sha256=str(creator_image.get("sha256") or ""),
        reference_video_sha256=str(reference_video.get("sha256") or ""),
        selected_composition_frame_sha256=selected_composition_frame_sha256,
        approved_by=approved_by,
    )
    if factory is not None:
        assert candidate_source_id is not None
        factory.conn.execute(
            """
            UPDATE source_assets SET status = 'approved_recreation_anchor',
                updated_at = ? WHERE id = ?
            """,
            (receipt["approvedAt"], candidate_source_id),
        )
        factory.conn.commit()
    return receipt


def _regular_file(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise PermissionError(f"{label} must not be a symlink")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved
