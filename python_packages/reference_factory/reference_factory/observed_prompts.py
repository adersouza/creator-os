from __future__ import annotations

import hashlib
import json
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from pipeline_contracts.validator import validate_higgsfield_soul_image_prompt

from .db import json_dump, json_load
from .identity import content_hash, stable_reference_id
from .scan import classify_file, timestamp_from_stat
from .timeutil import now_iso

OBSERVED_PROMPT_STATUS = "outcome_observed"


def register_observed_higgsfield_prompt(
    conn: Connection,
    *,
    lineage_path: Path,
    expected_prompt_id: str,
    expected_external_reference_id: str | None = None,
    pattern_reference_ids: list[str] | None = None,
    source_pattern_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Register a real provider-captured prompt without making it generation-ready.

    The generated output is the prompt's primary local artifact. Identity and
    public-pattern references are explicit links so they are not conflated.
    """
    path = Path(lineage_path).expanduser().resolve()
    lineage = _load_lineage(path)
    generation = _mapping(lineage.get("generation"))
    source = _mapping(lineage.get("source"))
    assets = _mapping(lineage.get("assets"))
    local_paths = _mapping(assets.get("localPaths"))

    captured_prompt = str(generation.get("capturedHiggsfieldPrompt") or "").strip()
    if not captured_prompt:
        raise ValueError("observed Higgsfield lineage is missing captured prompt")
    prompt_sha256 = hashlib.sha256(captured_prompt.encode("utf-8")).hexdigest()
    prompt_id = f"prompt_higgsfield_{prompt_sha256[:16]}"
    if prompt_id != str(expected_prompt_id or "").strip():
        raise ValueError("observed Higgsfield prompt ID does not match captured prompt")

    output_path = Path(str(local_paths.get("image") or "")).expanduser()
    if not output_path.is_absolute():
        output_path = path.parent / output_path
    output_reference_id = _ensure_source_file(conn, output_path.resolve())

    identity_path_value = str(source.get("referenceImage") or "").strip()
    identity_reference_id = None
    if identity_path_value:
        identity_path = Path(identity_path_value).expanduser().resolve()
        identity_reference_id = _ensure_source_file(conn, identity_path)

    pattern_ids = _existing_reference_ids(conn, pattern_reference_ids or [])
    timestamp = now_iso()
    model_profile = str(
        _mapping(generation.get("models")).get("image") or "text2image_soul_v2"
    ).strip()
    provider_job_id = str(generation.get("imageJobId") or "").strip() or None
    prompt_json = {
        "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
        "tool": "higgsfield_soul_image",
        "status": OBSERVED_PROMPT_STATUS,
        "promptSource": "higgsfield_provider_capture",
        "sourceReferenceId": output_reference_id,
        "sourcePatternId": source_pattern_id or "observed_without_pattern",
        "modelProfile": model_profile,
        "mainPrompt": captured_prompt,
        "negativePrompt": (
            "copied identity, watermark, username, platform UI, broken anatomy, "
            "underage appearance, explicit nudity, low resolution"
        ),
        "closenessControls": {
            "format_closeness": "observed",
            "identity_copy_risk": "blocked",
            "scene_variation_required": True,
        },
        "aspectRatio": str(
            _mapping(generation.get("params")).get("imageAspectRatio") or "9:16"
        ),
        "observedProviderPrompt": True,
        "providerPromptSha256": prompt_sha256,
        "providerJobId": provider_job_id,
        "lineagePath": str(path),
        "identityReferenceId": expected_external_reference_id,
        "identityReferencePath": identity_path_value or None,
        "patternReferenceIds": pattern_ids,
        "reviewNotes": [
            "Outcome evidence only. This captured provider prompt is not generation-ready."
        ],
    }
    validate_higgsfield_soul_image_prompt(prompt_json)

    existing = conn.execute(
        "SELECT prompt_json FROM generated_video_prompts WHERE id = ?", (prompt_id,)
    ).fetchone()
    if existing:
        existing_prompt = json_load(existing["prompt_json"], {})
        if str(existing_prompt.get("providerPromptSha256") or "") != prompt_sha256:
            raise ValueError("observed prompt ID is already bound to different content")
        status = "existing"
    else:
        conn.execute(
            """
            INSERT INTO generated_video_prompts (
              id, analysis_job_id, reference_id, target_tool, model_profile,
              prompt_json, status, created_at, updated_at
            ) VALUES (?, NULL, ?, 'higgsfield_soul_image', ?, ?, ?, ?, ?)
            """,
            (
                prompt_id,
                output_reference_id,
                model_profile,
                json_dump(prompt_json),
                OBSERVED_PROMPT_STATUS,
                timestamp,
                timestamp,
            ),
        )
        status = "registered"

    if identity_reference_id:
        _upsert_reference_link(
            conn,
            prompt_id=prompt_id,
            reference_id=identity_reference_id,
            role="identity_reference",
            attribution_weight=0.0,
            provenance={"lineagePath": str(path)},
            timestamp=timestamp,
        )
    for reference_id in pattern_ids:
        _upsert_reference_link(
            conn,
            prompt_id=prompt_id,
            reference_id=reference_id,
            role="pattern_member",
            attribution_weight=1.0 / len(pattern_ids),
            provenance={
                "sourcePatternId": source_pattern_id,
                "lineagePath": str(path),
            },
            timestamp=timestamp,
        )
    if expected_external_reference_id:
        conn.execute(
            """
            INSERT INTO generated_prompt_external_references (
              prompt_id, external_reference_id, role, provenance_json,
              created_at, updated_at
            ) VALUES (?, ?, 'identity_reference', ?, ?, ?)
            ON CONFLICT(prompt_id, external_reference_id, role) DO UPDATE SET
              provenance_json = excluded.provenance_json,
              updated_at = excluded.updated_at
            """,
            (
                prompt_id,
                expected_external_reference_id,
                json_dump({"lineagePath": str(path)}),
                timestamp,
                timestamp,
            ),
        )
    if commit:
        conn.commit()
    return {
        "schema": "reference_factory.register_observed_prompt.v1",
        "status": status,
        "promptId": prompt_id,
        "outputReferenceId": output_reference_id,
        "identityReferenceId": identity_reference_id,
        "externalIdentityReferenceId": expected_external_reference_id,
        "patternReferenceIds": pattern_ids,
        "providerPromptSha256": prompt_sha256,
    }


def _load_lineage(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"observed Higgsfield lineage not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"observed Higgsfield lineage is invalid JSON: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("observed Higgsfield lineage must be a JSON object")
    return payload


def _ensure_source_file(conn: Connection, path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"observed prompt artifact not found: {path}")
    stat = path.stat()
    digest = content_hash(path)
    existing = conn.execute(
        """
        SELECT reference_id FROM source_files
        WHERE path = ? OR content_hash = ?
        ORDER BY CASE WHEN path = ? THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (str(path), digest, str(path)),
    ).fetchone()
    if existing:
        return str(existing["reference_id"])
    reference_id = stable_reference_id(path, stat.st_size)
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, account, file_name, extension, kind,
          size_bytes, mtime, path_hash, content_hash, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reference_id,
            str(path),
            path.parent.name,
            path.name,
            path.suffix.lower().lstrip(".") or "_none",
            classify_file(path),
            stat.st_size,
            timestamp_from_stat(stat.st_mtime),
            reference_id.removeprefix("ref_"),
            digest,
            timestamp,
            timestamp,
        ),
    )
    return reference_id


def _existing_reference_ids(conn: Connection, values: list[str]) -> list[str]:
    reference_ids = list(dict.fromkeys(str(value).strip() for value in values if value))
    if not reference_ids:
        return []
    placeholders = ",".join("?" for _ in reference_ids)
    rows = conn.execute(
        f"SELECT reference_id FROM source_files WHERE reference_id IN ({placeholders})",
        reference_ids,
    ).fetchall()
    found = {str(row["reference_id"]) for row in rows}
    missing = [
        reference_id for reference_id in reference_ids if reference_id not in found
    ]
    if missing:
        raise ValueError(
            "observed prompt references unknown Reference Factory sources: "
            + ", ".join(missing)
        )
    return reference_ids


def _upsert_reference_link(
    conn: Connection,
    *,
    prompt_id: str,
    reference_id: str,
    role: str,
    attribution_weight: float,
    provenance: dict[str, Any],
    timestamp: str,
) -> None:
    conn.execute(
        """
        INSERT INTO generated_prompt_reference_links (
          prompt_id, reference_id, role, attribution_weight, provenance_json,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(prompt_id, reference_id, role) DO UPDATE SET
          attribution_weight = excluded.attribution_weight,
          provenance_json = excluded.provenance_json,
          updated_at = excluded.updated_at
        """,
        (
            prompt_id,
            reference_id,
            role,
            attribution_weight,
            json_dump(provenance),
            timestamp,
            timestamp,
        ),
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
