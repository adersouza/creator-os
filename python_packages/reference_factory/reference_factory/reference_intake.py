from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from pipeline_contracts.llm_resilience import urlopen_json_with_retry

from pipeline_contracts import (
    validate_higgsfield_soul_image_prompt,
    validate_kling_3_video_prompt,
    validate_pattern_card,
    validate_video_analysis,
)

from .db import json_dump, json_load
from .fileops import atomic_write_text
from .identity import stable_id
from .prompt_records import (
    find_prompt_record as _find_prompt_record,
)
from .prompt_records import (
    read_jsonl_records as _read_jsonl_records,
)
from .prompt_records import (
    record_reference_id as _record_reference_id,
)
from .prompt_records import (
    write_jsonl_records as _write_jsonl_records,
)
from .scan import scan_source
from .timeutil import now_iso

ANALYSIS_SCHEMA = "reference_factory.video_analysis.v1"
PATTERN_CARD_SCHEMA = "reference_factory.pattern_card.v1"
DEFAULT_INTAKE_PROFILE = "ig_ofm"
PROMPT_READY_STATUS = "prompt_ready"

IG_OFM_CLOSENESS_CONTROLS = {
    "format_closeness": "high",
    "identity_copy_risk": "blocked",
    "scene_variation_required": True,
    "spicy_ofm_coded": True,
}

FORMAT_PRIORITY = [
    "mirror_selfie",
    "selfie_video",
    "pov",
    "spicy_lifestyle",
    "slideshow",
    "other",
]

GEMINI_PROMPT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema": {"type": "string"},
        "referenceId": {"type": "string"},
        "summary": {"type": "string"},
        "contentFormat": {"type": "string"},
        "recreation_blueprint": {
            "type": "object",
            "properties": {
                "format_type": {"type": "string"},
                "first_frame": {"type": "object"},
                "motion_beats": {"type": "array"},
                "native_style_constraints": {"type": "array"},
                "copy_risk_notes": {"type": "array"},
                "required_changes": {"type": "array"},
            },
            "required": [
                "format_type",
                "first_frame",
                "motion_beats",
                "native_style_constraints",
                "copy_risk_notes",
                "required_changes",
            ],
            "additionalProperties": True,
        },
        "image_prompt_json": {"type": "object"},
        "higgsfield_soul_image_prompt": {"type": "string"},
        "higgsfield_negative_prompt": {"type": "string"},
        "kling_3_video_prompt": {"type": "string"},
        "kling_negative_prompt": {"type": "string"},
        "motion_notes": {"type": "string"},
        "camera_notes": {"type": "string"},
        "style_notes": {"type": "string"},
        "copy_risk_notes": {"type": "string"},
        "what_to_change": {"type": "string"},
    },
    "required": [
        "schema",
        "referenceId",
        "summary",
        "contentFormat",
        "recreation_blueprint",
        "image_prompt_json",
        "higgsfield_soul_image_prompt",
        "higgsfield_negative_prompt",
        "kling_3_video_prompt",
        "kling_negative_prompt",
        "motion_notes",
        "camera_notes",
        "style_notes",
        "copy_risk_notes",
        "what_to_change",
    ],
    "additionalProperties": True,
}

GEMINI_PROMPT_SCORING_RUBRIC: dict[str, Any] = {
    "schema": "reference_factory.gemini_prompt_scoring_rubric.v1",
    "scale": "1-10",
    "criteria": [
        {"key": "format_closeness", "label": "Format closeness", "weight": 1.2},
        {
            "key": "first_frame_geometry",
            "label": "First-frame crop / pose / subject scale accuracy",
            "weight": 1.4,
        },
        {
            "key": "originality_identity_safety",
            "label": "Originality / no identity copying",
            "weight": 1.2,
        },
        {"key": "soul_id_consistency", "label": "Soul ID consistency", "weight": 1.0},
        {
            "key": "image_prompt_usefulness",
            "label": "Higgsfield image prompt usefulness",
            "weight": 1.0,
        },
        {
            "key": "video_prompt_usefulness",
            "label": "Kling prompt usefulness",
            "weight": 1.0,
        },
        {"key": "motion_accuracy", "label": "Motion accuracy", "weight": 1.2},
        {
            "key": "amateur_native_feel",
            "label": "Amateur native phone-shot feel",
            "weight": 1.2,
        },
        {
            "key": "platform_native_realism",
            "label": "Instagram/TikTok native realism",
            "weight": 1.0,
        },
        {
            "key": "performance_potential",
            "label": "Likely Reels performance",
            "weight": 0.8,
        },
    ],
    "failureModes": [
        "over_describes",
        "misses_motion",
        "too_cinematic",
        "copies_identity_too_closely",
        "ignores_first_frame_needs",
        "vague_prompts",
        "invents_unseen_details",
        "loses_pose_or_fit",
        "changes_camera_distance",
    ],
}

GROK_PROMPT_MODEL_DEFAULT = "grok-4"
XAI_CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"


def analyze_reference_local(
    conn: Connection,
    source_root: Path,
    *,
    data_root: Path,
    platform: str = "instagram",
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    media_kinds: list[str] | None = None,
    limit: int | None = None,
    ffprobe: str = "ffprobe",
    ffmpeg: str = "ffmpeg",
    creative_plan_id: str | None = None,
) -> dict[str, object]:
    queued = queue_reference_analysis(
        conn,
        source_root,
        data_root=data_root,
        platform=platform,
        provider_target="local",
        intake_profile=intake_profile,
        media_kinds=media_kinds or ["video"],
        limit=limit,
        creative_plan_id=creative_plan_id,
    )
    rows = conn.execute(
        """
        SELECT raj.*, sf.path, sf.account, sf.file_name, sf.kind, sf.size_bytes
        FROM reference_analysis_jobs raj
        JOIN source_files sf ON sf.reference_id = raj.reference_id
        WHERE raj.provider_target = 'local'
          AND sf.path LIKE ?
        ORDER BY raj.updated_at DESC
        LIMIT ?
        """,
        (
            str(Path(source_root).expanduser().resolve()) + "%",
            max(1, limit or int(queued.get("queued") or 1)),
        ),
    ).fetchall()
    timestamp = now_iso()
    analyzed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in rows:
        job = dict(row)
        try:
            analysis = _local_video_analysis(
                job,
                data_root=data_root,
                platform=platform,
                ffprobe=ffprobe,
                ffmpeg=ffmpeg,
            )
            _store_pattern_and_analysis(
                conn, job=job, analysis=analysis, provider="local", timestamp=timestamp
            )
            analyzed.append(
                {
                    "referenceId": job["reference_id"],
                    "analysisId": analysis["id"],
                    "patternCardId": analysis["patternCard"]["id"],
                }
            )
        except (
            Exception
        ) as exc:  # pragma: no cover - defensive surface for operator CLI
            errors.append({"referenceId": job.get("reference_id"), "error": str(exc)})
    conn.commit()
    export = export_video_analyses(conn, data_root=data_root, provider="local")
    return {
        "schema": "reference_factory.analyze_reference_local.v1",
        "sourceRoot": str(Path(source_root).expanduser().resolve()),
        "platform": _norm(platform),
        "intakeProfile": _norm(intake_profile),
        "creativePlanId": creative_plan_id,
        "queued": queued.get("queued"),
        "analyzed": len(analyzed),
        "errors": errors,
        "export": export,
        "items": analyzed,
    }


def export_video_analyses(
    conn: Connection, *, data_root: Path, provider: str | None = None, limit: int = 100
) -> dict[str, object]:
    output_dir = data_root / "reference_intake"
    output_dir.mkdir(parents=True, exist_ok=True)
    where = "WHERE rva.provider = ?" if provider else ""
    params: tuple[Any, ...] = ((_norm(provider),) if provider else ()) + (limit,)
    rows = conn.execute(
        f"""
        SELECT rva.*, sf.path, sf.file_name, sf.account
        FROM reference_video_analyses rva
        JOIN source_files sf ON sf.reference_id = rva.reference_id
        {where}
        ORDER BY rva.updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    analyses = []
    for row in rows:
        item = dict(row)
        analysis = json_load(item["analysis_json"], {})
        analysis.setdefault("sourcePath", item.get("path"))
        analysis.setdefault("fileName", item.get("file_name"))
        analysis.setdefault("account", item.get("account"))
        analyses.append(analysis)
    payload = {
        "schema": "reference_factory.video_analysis_export.v1",
        "count": len(analyses),
        "items": analyses,
    }
    suffix = f"_{_norm(provider)}" if provider else ""
    path = output_dir / f"video_analyses{suffix}.json"
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "schema": "reference_factory.export_video_analyses.v1",
        "count": len(analyses),
        "jsonPath": str(path),
    }


def queue_reference_analysis(
    conn: Connection,
    source_root: Path,
    *,
    data_root: Path,
    platform: str = "unknown",
    provider_target: str = "gemini",
    account_profile: str | None = None,
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    media_kinds: list[str] | None = None,
    limit: int | None = None,
    creative_plan_id: str | None = None,
    prompt_style: str = "guided",
) -> dict[str, object]:
    scan = scan_source(conn, source_root)
    timestamp = now_iso()
    kinds = [
        _norm(kind)
        for kind in (media_kinds or ["video", "image"])
        if _norm(kind) in {"video", "image"}
    ]
    if not kinds:
        kinds = ["video", "image"]
    placeholders = ",".join("?" for _ in kinds)
    rows = conn.execute(
        f"""
        SELECT *
        FROM source_files
        WHERE kind IN ({placeholders})
          AND path LIKE ?
          AND path NOT LIKE '%/Avatars/%'
        ORDER BY CASE WHEN kind = 'video' THEN 0 ELSE 1 END, updated_at DESC, file_name
        """,
        (*kinds, str(Path(source_root).expanduser().resolve()) + "%"),
    ).fetchall()
    if limit is not None:
        rows = rows[: max(0, limit)]

    created = 0
    updated = 0
    jobs: list[dict[str, Any]] = []
    profile_key = account_profile or ""
    for row in rows:
        source = dict(row)
        job_id = stable_id(
            "reference_analysis_job",
            source["reference_id"],
            provider_target,
            profile_key,
        )
        prompt_text = gemini_analysis_prompt(
            source,
            platform=platform,
            account_profile=account_profile,
            intake_profile=intake_profile,
            prompt_style=prompt_style,
        )
        existing = conn.execute(
            "SELECT id FROM reference_analysis_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        conn.execute(
            """
            INSERT INTO reference_analysis_jobs (
              id, reference_id, source_platform, provider_target, account_profile,
              status, prompt_text, analysis_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'needs_analysis', ?, '{}', ?, ?)
            ON CONFLICT(reference_id, provider_target, account_profile) DO UPDATE SET
              source_platform = excluded.source_platform,
              prompt_text = excluded.prompt_text,
              updated_at = excluded.updated_at
            """,
            (
                job_id,
                source["reference_id"],
                _norm(platform),
                _norm(provider_target),
                profile_key,
                prompt_text,
                timestamp,
                timestamp,
            ),
        )
        if existing:
            updated += 1
        else:
            created += 1
        jobs.append(_job_payload(conn, job_id))
    conn.commit()

    export = export_analysis_queue(
        conn, data_root=data_root, provider_target=provider_target, limit=len(jobs) or 1
    )
    return {
        "schema": "reference_factory.queue_reference_analysis.v1",
        "sourceRoot": str(Path(source_root).expanduser().resolve()),
        "platform": _norm(platform),
        "providerTarget": _norm(provider_target),
        "accountProfile": account_profile,
        "intakeProfile": _norm(intake_profile),
        "promptStyle": _norm(prompt_style),
        "creativePlanId": creative_plan_id,
        "closenessControls": _closeness_controls(intake_profile),
        "formatPriority": FORMAT_PRIORITY
        if _norm(intake_profile) == DEFAULT_INTAKE_PROFILE
        else [],
        "mediaKinds": kinds,
        "scan": scan,
        "queued": len(jobs),
        "created": created,
        "updated": updated,
        "export": export,
        "jobs": jobs[:10],
    }


def export_analysis_queue(
    conn: Connection,
    *,
    data_root: Path,
    provider_target: str = "gemini",
    limit: int = 50,
) -> dict[str, object]:
    output_dir = data_root / "reference_intake"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """
        SELECT raj.*, sf.path, sf.account, sf.file_name, sf.kind
        FROM reference_analysis_jobs raj
        JOIN source_files sf ON sf.reference_id = raj.reference_id
        WHERE raj.provider_target = ?
          AND raj.status IN ('needs_analysis', 'analyzed')
        ORDER BY raj.updated_at DESC
        LIMIT ?
        """,
        (_norm(provider_target), limit),
    ).fetchall()
    jobs = [_job_row_to_export(dict(row)) for row in rows]
    manifest = {
        "schema": "reference_factory.reference_analysis_queue.v1",
        "providerTarget": _norm(provider_target),
        "count": len(jobs),
        "jobs": jobs,
    }
    json_path = output_dir / f"{_norm(provider_target)}_analysis_queue.json"
    jsonl_path = output_dir / f"{_norm(provider_target)}_analysis_queue.jsonl"
    md_path = output_dir / f"{_norm(provider_target)}_analysis_queue.md"
    schema_path = output_dir / f"{_norm(provider_target)}_prompt_output_schema.json"
    rubric_path = output_dir / f"{_norm(provider_target)}_prompt_scoring_rubric.json"
    rubric_md_path = output_dir / f"{_norm(provider_target)}_prompt_scoring_rubric.md"
    atomic_write_text(
        json_path,
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with jsonl_path.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_write_text(md_path, _analysis_queue_markdown(jobs), encoding="utf-8")
    atomic_write_text(
        schema_path,
        json.dumps(GEMINI_PROMPT_OUTPUT_SCHEMA, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    atomic_write_text(
        rubric_path,
        json.dumps(GEMINI_PROMPT_SCORING_RUBRIC, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    atomic_write_text(
        rubric_md_path, _prompt_scoring_rubric_markdown(), encoding="utf-8"
    )
    return {
        "schema": "reference_factory.export_reference_analysis_queue.v1",
        "count": len(jobs),
        "jsonPath": str(json_path),
        "jsonlPath": str(jsonl_path),
        "markdownPath": str(md_path),
        "outputSchemaPath": str(schema_path),
        "scoringRubricPath": str(rubric_path),
        "scoringRubricMarkdownPath": str(rubric_md_path),
    }


def import_reference_analysis(
    conn: Connection,
    input_path: Path,
) -> dict[str, object]:
    payload = json.loads(Path(input_path).expanduser().read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError(
            "analysis input must be a list or an object with an items list"
        )
    timestamp = now_iso()
    imported = 0
    errors: list[dict[str, object]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append({"index": index, "error": "item must be an object"})
            continue
        job_id = str(item.get("analysisJobId") or item.get("jobId") or "")
        reference_id = str(item.get("referenceId") or "")
        if not job_id and reference_id:
            row = conn.execute(
                "SELECT id FROM reference_analysis_jobs WHERE reference_id = ? ORDER BY updated_at DESC LIMIT 1",
                (reference_id,),
            ).fetchone()
            job_id = row["id"] if row else ""
        if not job_id:
            errors.append(
                {"index": index, "error": "analysisJobId or referenceId is required"}
            )
            continue
        row = conn.execute(
            """
            SELECT raj.*, sf.path, sf.account, sf.file_name, sf.kind, sf.size_bytes
            FROM reference_analysis_jobs raj
            JOIN source_files sf ON sf.reference_id = raj.reference_id
            WHERE raj.id = ?
            """,
            (job_id,),
        ).fetchone()
        if not row:
            errors.append({"index": index, "error": f"unknown analysis job: {job_id}"})
            continue
        analysis = _normalize_analysis(item)
        pattern = _pattern_card_from_analysis(dict(row), analysis)
        analysis["patternCard"] = pattern
        conn.execute(
            """
            UPDATE reference_analysis_jobs
            SET status = 'analyzed',
                analysis_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (json_dump(analysis), timestamp, job_id),
        )
        stored_analysis = {
            "schema": ANALYSIS_SCHEMA,
            "id": stable_id(
                "reference_video_analysis",
                row["reference_id"],
                row["provider_target"],
                "import",
            ),
            "referenceId": row["reference_id"],
            "provider": row["provider_target"],
            "status": "pattern_ready",
            "media": {},
            "signals": {"providerAnalysis": True},
            "patternCard": pattern,
            "raw": {"analysis": analysis},
        }
        _store_pattern_and_analysis(
            conn,
            job=dict(row),
            analysis=stored_analysis,
            provider=row["provider_target"],
            timestamp=timestamp,
        )
        imported += 1
    conn.commit()
    return {
        "schema": "reference_factory.import_reference_analysis.v1",
        "inputPath": str(Path(input_path).expanduser()),
        "imported": imported,
        "errors": errors,
    }


def import_gemini_app_response(
    conn: Connection,
    *,
    queue_path: Path,
    response_path: Path | None = None,
    data_root: Path,
    job_index: int = 1,
    generate_prompts_after_import: bool = True,
    model_profile: str | None = None,
) -> dict[str, object]:
    queue = json.loads(Path(queue_path).expanduser().read_text(encoding="utf-8"))
    jobs = queue.get("jobs") if isinstance(queue, dict) else None
    if not isinstance(jobs, list) or not jobs:
        raise ValueError(
            "queue must be an exported analysis queue with at least one job"
        )
    if job_index < 1 or job_index > len(jobs):
        raise ValueError(f"job_index must be between 1 and {len(jobs)}")
    job = jobs[job_index - 1]

    if response_path:
        raw_text = Path(response_path).expanduser().read_text(encoding="utf-8")
    else:
        try:
            raw_text = subprocess.run(
                ["pbpaste"], check=True, capture_output=True, text=True
            ).stdout
        except Exception as exc:
            raise RuntimeError(
                "Could not read Gemini response from the macOS clipboard. Pass --response instead."
            ) from exc
    analysis = _json_from_model_text(raw_text)
    analysis["analysisJobId"] = job["id"]
    analysis["referenceId"] = job["referenceId"]

    output_dir = data_root / "reference_intake"
    output_dir.mkdir(parents=True, exist_ok=True)
    import_path = output_dir / "gemini_app_import_latest.json"
    atomic_write_text(
        import_path,
        json.dumps({"items": [analysis]}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    imported = import_reference_analysis(conn, import_path)
    generated = None
    if generate_prompts_after_import and imported.get("imported"):
        generated = generate_video_prompts(
            conn,
            data_root=data_root,
            target_tools=["higgsfield_soul_image", "kling_3_video"],
            model_profile=model_profile,
            limit=10,
            include_pending=False,
        )
    return {
        "schema": "reference_factory.import_gemini_app_response.v1",
        "queuePath": str(Path(queue_path).expanduser()),
        "responsePath": str(Path(response_path).expanduser())
        if response_path
        else "clipboard",
        "jobIndex": job_index,
        "analysisJobId": job["id"],
        "referenceId": job["referenceId"],
        "importPath": str(import_path),
        "import": imported,
        "promptGeneration": generated,
    }


def analyze_reference_with_gemini_api(
    conn: Connection,
    *,
    source_root: Path,
    data_root: Path,
    platform: str = "instagram",
    account_profile: str | None = None,
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    media_kinds: list[str] | None = None,
    limit: int = 1,
    model: str = "gemini-2.5-flash",
    api_key: str | None = None,
    prompt_style: str = "minimal",
) -> dict[str, object]:
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "Gemini API analysis requires `pip install google-genai`. Manual Gemini import still works."
        ) from exc
    resolved_key = (
        api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    if not resolved_key:
        raise RuntimeError(
            "Set GEMINI_API_KEY or GOOGLE_API_KEY before running Gemini API analysis."
        )

    queued = queue_reference_analysis(
        conn,
        source_root,
        data_root=data_root,
        platform=platform,
        provider_target="gemini_api",
        account_profile=account_profile,
        intake_profile=intake_profile,
        media_kinds=media_kinds or ["video"],
        limit=limit,
        prompt_style=prompt_style,
    )
    try:
        client = genai.Client(api_key=resolved_key, http_options={"timeout": 120_000})
    except TypeError:
        client = genai.Client(api_key=resolved_key)
    analyzed = 0
    errors: list[dict[str, object]] = []
    imported_items: list[dict[str, Any]] = []
    for job in queued.get("jobs") or []:
        try:
            path = Path(str(job.get("sourcePath") or "")).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"source file missing: {path}")
            uploaded = client.files.upload(file=str(path))
            _wait_for_gemini_file(client, uploaded)
            response = client.models.generate_content(
                model=model,
                contents=[uploaded, str(job.get("promptText") or "")],
            )
            analysis = _json_from_model_text(str(getattr(response, "text", "") or ""))
            analysis["analysisJobId"] = job["id"]
            analysis["referenceId"] = job["referenceId"]
            imported_items.append(analysis)
            analyzed += 1
        except Exception as exc:
            errors.append(
                {
                    "analysisJobId": job.get("id"),
                    "sourcePath": job.get("sourcePath"),
                    "error": str(exc),
                }
            )
    import_path = data_root / "reference_intake" / "gemini_api_import_latest.json"
    import_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        import_path,
        json.dumps({"items": imported_items}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    imported = (
        import_reference_analysis(conn, import_path)
        if imported_items
        else {"imported": 0, "errors": []}
    )
    generated = (
        generate_video_prompts(
            conn,
            data_root=data_root,
            target_tools=["higgsfield_soul_image", "kling_3_video"],
            model_profile=account_profile,
            limit=max(1, analyzed),
            include_pending=False,
        )
        if imported.get("imported")
        else None
    )
    return {
        "schema": "reference_factory.gemini_api_analysis.v1",
        "model": model,
        "queued": queued.get("queued"),
        "analyzed": analyzed,
        "errors": errors,
        "importPath": str(import_path),
        "import": imported,
        "promptGeneration": generated,
    }


def analyze_reference_with_grok_api(
    conn: Connection,
    *,
    source_root: Path,
    data_root: Path,
    platform: str = "instagram",
    account_profile: str | None = None,
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    media_kinds: list[str] | None = None,
    limit: int = 1,
    model: str = GROK_PROMPT_MODEL_DEFAULT,
    api_key: str | None = None,
    prompt_style: str = "imageat",
    ffmpeg: str = "ffmpeg",
) -> dict[str, object]:
    resolved_key = (
        api_key or os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
    )
    if not resolved_key:
        raise RuntimeError(
            "Set XAI_API_KEY or GROK_API_KEY before running Grok API analysis."
        )

    queued = queue_reference_analysis(
        conn,
        source_root,
        data_root=data_root,
        platform=platform,
        provider_target="grok_api",
        account_profile=account_profile,
        intake_profile=intake_profile,
        media_kinds=media_kinds or ["video", "image"],
        limit=limit,
        prompt_style="minimal",
    )
    analyzed = 0
    errors: list[dict[str, object]] = []
    imported_items: list[dict[str, Any]] = []
    frame_dir = data_root / "reference_intake" / "grok_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for job in queued.get("jobs") or []:
        try:
            source = Path(str(job.get("sourcePath") or "")).expanduser()
            if not source.exists():
                raise FileNotFoundError(f"source file missing: {source}")
            image_path = _grok_reference_image(
                source,
                frame_dir=frame_dir,
                reference_id=str(job.get("referenceId") or "reference"),
                ffmpeg=ffmpeg,
            )
            prompt = _grok_prompt_builder(job, prompt_style=prompt_style)
            response = _xai_chat_completion(
                api_key=resolved_key,
                model=model,
                prompt=prompt,
                image_path=image_path,
            )
            analysis = _json_from_model_text(response)
            analysis["analysisJobId"] = job["id"]
            analysis["referenceId"] = job["referenceId"]
            analysis.setdefault("schema", ANALYSIS_SCHEMA)
            analysis.setdefault("provider", "grok_api")
            image_json = analysis.get("image_prompt_json")
            if isinstance(image_json, dict):
                image_json.setdefault("promptMode", "structured_json")
            imported_items.append(analysis)
            analyzed += 1
        except Exception as exc:
            errors.append(
                {
                    "analysisJobId": job.get("id"),
                    "sourcePath": job.get("sourcePath"),
                    "error": str(exc),
                }
            )
    import_path = data_root / "reference_intake" / "grok_api_import_latest.json"
    import_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        import_path,
        json.dumps({"items": imported_items}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    imported = (
        import_reference_analysis(conn, import_path)
        if imported_items
        else {"imported": 0, "errors": []}
    )
    generated = (
        generate_video_prompts(
            conn,
            data_root=data_root,
            target_tools=["higgsfield_soul_image", "kling_3_video"],
            model_profile=account_profile,
            limit=max(1, analyzed),
            include_pending=False,
        )
        if imported.get("imported")
        else None
    )
    return {
        "schema": "reference_factory.grok_api_analysis.v1",
        "model": model,
        "queued": queued.get("queued"),
        "analyzed": analyzed,
        "errors": errors,
        "importPath": str(import_path),
        "import": imported,
        "promptGeneration": generated,
    }


def compile_prompts_with_grok_api(
    *,
    data_root: Path,
    reference_id: str,
    reference_media: Path,
    model: str = GROK_PROMPT_MODEL_DEFAULT,
    api_key: str | None = None,
    ffmpeg: str = "ffmpeg",
    instructions: str | None = None,
) -> dict[str, object]:
    resolved_key = (
        api_key or os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
    )
    if not resolved_key:
        raise RuntimeError(
            "Set XAI_API_KEY or GROK_API_KEY before running Grok prompt compilation."
        )

    prompt_dir = data_root / "reference_intake"
    image_path = prompt_dir / "daily_higgsfield_image_prompts.jsonl"
    video_path = prompt_dir / "daily_kling_video_prompts.jsonl"
    image_rows = _read_jsonl_records(image_path)
    video_rows = _read_jsonl_records(video_path)
    image_prompt = _find_prompt_record(image_rows, reference_id)
    video_prompt = _find_prompt_record(video_rows, reference_id)
    if image_prompt is None or video_prompt is None:
        raise RuntimeError(
            f"Missing paired Higgsfield/Kling prompt records for reference_id={reference_id}"
        )

    frame_dir = prompt_dir / "grok_prompt_compiler_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    reference_image = _grok_reference_image(
        reference_media, frame_dir=frame_dir, reference_id=reference_id, ffmpeg=ffmpeg
    )
    response = _xai_chat_completion(
        api_key=resolved_key,
        model=model,
        prompt=_grok_prompt_compiler_prompt(
            reference_id=reference_id,
            image_prompt=image_prompt,
            video_prompt=video_prompt,
            instructions=instructions,
        ),
        image_path=reference_image,
        response_format=_grok_prompt_compiler_response_format(),
    )
    compiled = _normalize_compiled_prompt_set(_json_from_model_text(response))
    _validate_compiled_prompt_set(compiled)

    metadata = {
        "schema": "reference_factory.grok_prompt_compiler_metadata.v1",
        "provider": "grok_api",
        "model": model,
        "referenceId": reference_id,
        "referenceImage": str(reference_image),
        "compiledAt": now_iso(),
    }
    for row in image_rows:
        if _record_reference_id(row) == reference_id:
            row["compiledPrompts"] = {
                "provider": "grok_api",
                "model": model,
                "soul_id_2x3_prompt": compiled["soul_id_2x3_prompt"],
                "single_panel_prompt": compiled["single_panel_prompt"],
                "structured_breakdown": compiled["structured_breakdown"],
                "confidence_score": compiled["confidence_score"],
                "notes": compiled.get("notes") or "",
            }
            row["compiledPromptMetadata"] = metadata
    for row in video_rows:
        if _record_reference_id(row) == reference_id:
            row["compiledPrompts"] = {
                "provider": "grok_api",
                "model": model,
                "kling_video_prompt": compiled["kling_video_prompt"],
                "kling_negative_prompt": compiled.get("kling_negative_prompt") or "",
                "structured_breakdown": compiled["structured_breakdown"],
                "confidence_score": compiled["confidence_score"],
                "notes": compiled.get("notes") or "",
            }
            row["compiledPromptMetadata"] = metadata

    _write_jsonl_records(image_path, image_rows)
    _write_jsonl_records(video_path, video_rows)
    out_path = prompt_dir / f"grok_compiled_prompts_{reference_id}.json"
    atomic_write_text(
        out_path,
        json.dumps(
            {
                "schema": "reference_factory.grok_compiled_prompts.v1",
                "referenceId": reference_id,
                "model": model,
                "referenceImage": str(reference_image),
                "compiledPrompts": compiled,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "schema": "reference_factory.grok_prompt_compiler.v1",
        "referenceId": reference_id,
        "model": model,
        "referenceImage": str(reference_image),
        "compiledPath": str(out_path),
        "updated": {
            "higgsfieldImagePrompts": str(image_path),
            "klingVideoPrompts": str(video_path),
        },
        "compiledPrompts": compiled,
    }


def generate_video_prompts(
    conn: Connection,
    *,
    data_root: Path,
    target_tools: list[str] | None = None,
    model_profile: str | None = None,
    limit: int = 50,
    include_pending: bool = True,
    creative_plan_id: str | None = None,
) -> dict[str, object]:
    tools = [
        _canonical_tool(tool)
        for tool in (target_tools or ["higgsfield_soul_image", "kling_3_video"])
    ]
    model_key = model_profile or ""
    rows = conn.execute(
        """
        WITH eligible AS (
          SELECT *
          FROM reference_analysis_jobs
          WHERE status IN ('analyzed', 'pattern_ready')
             OR (? = 1 AND status = 'needs_analysis')
        )
        SELECT raj.*, sf.path, sf.account, sf.file_name, sf.kind
        FROM eligible raj
        JOIN source_files sf ON sf.reference_id = raj.reference_id
        WHERE NOT EXISTS (
          SELECT 1
          FROM eligible newer
          WHERE newer.reference_id = raj.reference_id
            AND (
              newer.updated_at > raj.updated_at
              OR (newer.updated_at = raj.updated_at AND newer.id > raj.id)
            )
        )
        ORDER BY raj.updated_at DESC
        LIMIT ?
        """,
        (1 if include_pending else 0, limit),
    ).fetchall()
    timestamp = now_iso()
    prompts: list[dict[str, Any]] = []
    for row in rows:
        job = dict(row)
        analysis = json_load(job.get("analysis_json"), {})
        if not analysis:
            analysis = _heuristic_analysis(job)
        for target_tool in tools:
            prompt_json = _prompt_for_tool(target_tool, job, analysis, model_profile)
            if creative_plan_id:
                prompt_json["creativePlanId"] = creative_plan_id
            prompt_id = stable_id(
                "generated_video_prompt",
                job["reference_id"],
                target_tool,
                model_key,
            )
            prompt_json["id"] = prompt_id
            conn.execute(
                """
                INSERT INTO generated_video_prompts (
                  id, analysis_job_id, reference_id, target_tool, model_profile,
                  prompt_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reference_id, target_tool, model_profile) DO UPDATE SET
                  analysis_job_id = excluded.analysis_job_id,
                  prompt_json = excluded.prompt_json,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    prompt_id,
                    job["id"],
                    job["reference_id"],
                    target_tool,
                    model_key,
                    json_dump(prompt_json),
                    PROMPT_READY_STATUS,
                    timestamp,
                    timestamp,
                ),
            )
            prompts.append(
                {
                    "id": prompt_id,
                    "analysisJobId": job["id"],
                    "referenceId": job["reference_id"],
                    "targetTool": target_tool,
                    "status": PROMPT_READY_STATUS,
                    "creativePlanId": creative_plan_id,
                    "prompt": prompt_json,
                }
            )
    conn.commit()
    export = export_video_prompts(
        conn,
        data_root=data_root,
        limit=max(limit * max(1, len(tools)), 1),
        creative_plan_id=creative_plan_id,
    )
    return {
        "schema": "reference_factory.generate_video_prompts.v1",
        "count": len(prompts),
        "targetTools": tools,
        "modelProfile": model_key,
        "includePending": include_pending,
        "creativePlanId": creative_plan_id,
        "export": export,
        "prompts": prompts[:10],
    }


def export_video_prompts(
    conn: Connection,
    *,
    data_root: Path,
    limit: int = 100,
    creative_plan_id: str | None = None,
) -> dict[str, object]:
    output_dir = data_root / "reference_intake"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """
        SELECT gvp.*, sf.path, sf.account, sf.file_name
        FROM generated_video_prompts gvp
        JOIN source_files sf ON sf.reference_id = gvp.reference_id
        ORDER BY gvp.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    prompts = []
    for row in rows:
        item = dict(row)
        prompt_json = json_load(item["prompt_json"], {})
        if creative_plan_id:
            prompt_json["creativePlanId"] = creative_plan_id
        prompts.append(
            {
                "id": item["id"],
                "referenceId": item["reference_id"],
                "analysisJobId": item["analysis_job_id"],
                "targetTool": item["target_tool"],
                "modelProfile": item.get("model_profile"),
                "status": item["status"],
                "sourcePath": item["path"],
                "account": item.get("account"),
                "fileName": item["file_name"],
                "creativePlanId": creative_plan_id or prompt_json.get("creativePlanId"),
                "prompt": prompt_json,
            }
        )
    manifest = {
        "schema": "reference_factory.generated_video_prompts.v1",
        "count": len(prompts),
        "creativePlanId": creative_plan_id,
        "prompts": prompts,
    }
    json_path = output_dir / "generated_video_prompts.json"
    jsonl_path = output_dir / "generated_video_prompts.jsonl"
    md_path = output_dir / "generated_video_prompts.md"
    image_jsonl_path = output_dir / "daily_higgsfield_image_prompts.jsonl"
    kling_jsonl_path = output_dir / "daily_kling_video_prompts.jsonl"
    review_path = output_dir / "daily_prompt_review.md"
    for prompt in prompts:
        _validate_prompt_contract(prompt["targetTool"], prompt["prompt"])
    atomic_write_text(
        json_path,
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with jsonl_path.open("w", encoding="utf-8") as f:
        for prompt in prompts:
            f.write(json.dumps(prompt, ensure_ascii=False, sort_keys=True) + "\n")
    with image_jsonl_path.open("w", encoding="utf-8") as f:
        for prompt in prompts:
            if prompt["targetTool"] == "higgsfield_soul_image":
                f.write(
                    json.dumps(prompt["prompt"], ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
    with kling_jsonl_path.open("w", encoding="utf-8") as f:
        for prompt in prompts:
            if prompt["targetTool"] == "kling_3_video":
                f.write(
                    json.dumps(prompt["prompt"], ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
    atomic_write_text(md_path, _video_prompts_markdown(prompts), encoding="utf-8")
    atomic_write_text(
        review_path, _daily_prompt_review_markdown(prompts), encoding="utf-8"
    )
    return {
        "schema": "reference_factory.export_video_prompts.v1",
        "count": len(prompts),
        "creativePlanId": creative_plan_id,
        "jsonPath": str(json_path),
        "jsonlPath": str(jsonl_path),
        "markdownPath": str(md_path),
        "dailyHiggsfieldImageJsonlPath": str(image_jsonl_path),
        "dailyKlingVideoJsonlPath": str(kling_jsonl_path),
        "dailyPromptReviewPath": str(review_path),
    }


def gemini_analysis_prompt(
    source: dict[str, Any],
    *,
    platform: str = "unknown",
    account_profile: str | None = None,
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    prompt_style: str = "guided",
) -> str:
    profile = _norm(intake_profile)
    if _norm(prompt_style) == "minimal":
        return _minimal_gemini_analysis_prompt(source, platform=platform)
    closeness = _closeness_controls(profile)
    profile_rules = ""
    if profile == DEFAULT_INTAKE_PROFILE:
        profile_rules = f"""
IG-first OFM-coded profile:
- Prioritize formats in this order: {", ".join(FORMAT_PRIORITY)}.
- Preserve the winning format closely while changing the person, scene details, styling, overlay copy, and audio.
- Keep it spicy/social-coded without explicit nudity or direct identity copying.
- Closeness controls: {json.dumps(closeness, sort_keys=True)}.
- Filename/metadata format hint: {_classify_reference_format(source, {})}.
"""
    return f"""Analyze this short-form reference video/image for original AI video generation.

Source file: {source.get("path")}
Platform/source: {_norm(platform)}
Reference account/folder: {source.get("account") or "unknown"}
Target account/model profile: {account_profile or "not specified"}
Intake profile: {profile}
{profile_rules}

Rules:
- Do not copy the exact person, face, identity, watermark, username, or copyrighted audio.
- Extract reusable creative direction only.
- Treat trending audio as native/manual attach guidance, not burned-in audio.
- Output strict JSON only.

Return this JSON shape:
{{
  "schema": "{ANALYSIS_SCHEMA}",
  "referenceId": "{source.get("reference_id")}",
  "summary": "one sentence",
  "platformStyle": "tiktok|instagram|unknown",
  "contentFormat": "mirror_selfie|selfie_video|spicy_lifestyle|slideshow|talking_head|fit_check|other",
  "hookType": "relationship|glowup|confession|pov|question|other",
  "captionStyle": "short text overlay style",
  "closenessControls": {json.dumps(closeness, ensure_ascii=False, sort_keys=True)},
  "winningFormatCard": {{
    "visualFormat": "mirror_selfie|selfie_video|spicy_lifestyle|slideshow|other",
    "formatPriorityRank": 1,
    "poseAction": "...",
    "camera": {{"framing": "...", "angle": "...", "movement": "..."}},
    "lighting": "...",
    "setting": "...",
    "styling": "...",
    "textOverlay": {{"copy": "...", "placement": "...", "fontStyle": "..."}},
    "pacing": {{"energy": "low|medium|high", "cutRhythm": "...", "durationFeel": "..."}},
    "audioVibe": {{"energy": "low|medium|high", "bpmFeel": "...", "moodTags": ["..."]}},
    "hookMechanics": ["why the hook pulls attention"],
    "copyRiskNotes": ["what would be too close to copy"],
    "transformationInstructions": ["specific changes for a new original version"]
  }},
  "shotSequence": ["shot 1", "shot 2"],
  "camera": {{"framing": "...", "angle": "...", "movement": "..."}},
  "subject": {{"action": "...", "pose": "...", "expression": "...", "wardrobe": "..."}},
  "setting": {{"location": "...", "lighting": "...", "background": "..."}},
  "visualPacing": {{"energy": "low|medium|high", "cutRhythm": "...", "motion": "..."}},
  "audioVibe": {{"energy": "low|medium|high", "bpmFeel": "...", "moodTags": ["..."]}},
  "textOverlay": {{"placement": "...", "fontStyle": "...", "safeZoneNotes": "..."}},
  "viralMechanics": ["why it works"],
  "reuseRisk": "low|medium|high",
  "transformationNotes": ["how to make a new original version"],
  "qualityWarnings": ["anything to avoid"]
}}
"""


def _minimal_gemini_analysis_prompt(
    source: dict[str, Any], *, platform: str = "unknown"
) -> str:
    return f"""You are analyzing one short-form social video/image that I uploaded.

Watch the media carefully. Your job is not to summarize or make a loose inspired prompt. Your job is to reverse-engineer a recreation blueprint that preserves the exact winning format: first-frame composition, crop, body angle, pose geometry, phone/hand placement, camera distance, room layout, lighting, motion timing, and native social-media feel.

Important: describe the starting frame like an image-to-JSON converter. Prefer concrete visual facts over creative prose. The structured `image_prompt_json` is the primary source for Higgsfield, so it must look like the example format below: nested subject/composition/hair/clothing/body/skin/expression/environment/lighting/constraints fields, not a flattened paragraph.

Source file: {source.get("path")}
Platform/source: {_norm(platform)}
Reference account/folder: {source.get("account") or "unknown"}

Goal:
- Produce a practical Higgsfield Soul ID first-frame image prompt that can recreate the STARTING FRAME composition.
- Produce a practical Kling 3.0 video prompt that uses that generated Higgsfield image as the first/reference frame and recreates the observed motion beats.
- Copy the winning format, pose, framing, and motion closely, but replace the person with "my Soul ID model" and change enough identity-specific details to avoid direct copying.

Rules:
- Do not copy the original person's identity, face, username, watermark, logos, exact text, or uniquely identifying details.
- Do not add new body markings or identity traits. If hair is visible, describe the observed hair only inside the `hair` field.
- Do not invent objects, actions, outfits, or settings that are not visible or strongly implied by the video.
- Do not upgrade the video into a polished cinematic ad. Keep amateur, phone-shot, platform-native realism unless the source itself is polished.
- Preserve outfit silhouette and fit category, but change exact color/pattern/branding.
- For spicy influencer/OOTD references, keep the sensual framing and fitted outfit category when safe, but keep it non-explicit and social-platform safe.
- Preserve the room/location type and composition, but change unique decor and identifying details.
- If mirror selfie: describe exact mirror composition, crop, subject scale, body angle, phone position, facial visibility, visible limbs, and background layout.
- If POV/selfie: describe exact camera distance, lens feel, walking path, hand gestures, lean-in timing, and expression changes.
- Kling prompt must be beat/timestamp based, not a vague paragraph.
- If audio is available, infer only the vibe/energy; do not recommend burning copyrighted/trending audio into the file.
- Output strict JSON only. No markdown. No explanation outside JSON.

Example `image_prompt_json` style to imitate:
{{
  "promptMode": "structured_json",
  "subject": "Stunning young woman with an alluring, confident presence taking a mirror selfie in a bright minimalist bedroom.",
  "composition": {{
    "shot_type": "Full-body mirror selfie",
    "angle": "Side profile with slight twist toward the mirror, emphasizing the outfit silhouette",
    "pose": "Standing with arched back and pushed-out hips to create a strong hourglass S-curve. Right hand holds a white phone up covering most of her face, left arm slightly extended behind her. Flirty, confident body language."
  }},
  "hair": {{
    "style": "Long, voluminous curls",
    "color": "Honey brown with golden highlights",
    "texture": "Thick coiled ringlets cascading down her back and over one shoulder."
  }},
  "clothing": {{
    "item": "Very short strapless mini dress",
    "pattern": "Leopard print with brown and black rosettes",
    "fit": "Skin-tight bodycon fabric that closely follows the waist, hips, and thighs."
  }},
  "body": {{
    "build": "Slim-thick, toned yet curvaceous figure with pronounced hips and long smooth legs",
    "pose_details": "Weight shifted to one leg, creating a strong S-curve posture that highlights the waist-to-hip shape."
  }},
  "skin": {{
    "tone": "Fair with warm golden undertones",
    "texture": "Smooth, soft, and realistic with natural daylight highlights."
  }},
  "expression_mood": {{
    "vibe": "Playful, flirty, confident",
    "details": "Teasing outfit-check body language, realistic social-media selfie mood."
  }},
  "environment": {{
    "setting": "Bright, clean minimalist bedroom",
    "details": ["White tufted headboard bed", "messy striped sheets", "fluffy white rug", "plain white walls", "black vertical mirror frame"]
  }},
  "lighting_and_camera": {{
    "lighting": "Soft bright natural daylight from the side with gentle flattering shadows.",
    "camera_feel": "Casual smartphone mirror selfie aesthetic, vertical composition, realistic phone photography with slight grain."
  }},
  "constraints": {{
    "must_keep": ["Mirror selfie pose with phone covering face", "side-profile body emphasis", "fitted outfit silhouette", "minimalist bedroom setting"],
    "avoid": ["visible copied face", "loose clothing", "professional studio lighting", "cluttered background", "watermark", "platform UI"]
  }},
  "negative_prompt": "blurry, low quality, deformed body, bad anatomy, extra limbs, visible copied face, baggy outfit, dark lighting, professional photoshoot, text, watermark, oversaturated, cartoonish"
}}

Return exactly this JSON-compatible shape:
{{
  "schema": "{ANALYSIS_SCHEMA}",
  "referenceId": "{source.get("reference_id")}",
  "summary": "one sentence describing what happens in the video",
  "contentFormat": "infer the format, e.g. mirror_selfie, selfie_video, slideshow, pov, lifestyle_scene, talking_head, other",
  "recreation_blueprint": {{
    "format_type": "mirror_selfie|selfie_video|slideshow|pov|lifestyle_scene|talking_head|other",
    "first_frame": {{
      "subject_scale": "how large the subject appears in frame",
      "crop": "head/torso/legs crop and edge cutoffs",
      "body_angle": "front/profile/three-quarter angle and hip/shoulder orientation",
      "pose": "exact starting pose geometry",
      "phone_or_hand_position": "phone/hand placement relative to face/body/lens",
      "facial_visibility": "face visible, partly hidden, fully hidden by phone, etc.",
      "outfit_silhouette": "fit category and silhouette without exact copying",
      "room_or_location_layout": "visible background layout and object placement",
      "lighting": "source direction, brightness, shadows, color temperature",
      "camera_height": "low/chest/eye/mirror height",
      "camera_distance": "close/medium/far and mirror/lens distance",
      "lens_feel": "phone wide/normal/selfie lens feel"
    }},
    "motion_beats": [
      {{
        "time_range": "0.0-1.0s",
        "subject_motion": "observed body/face/hand movement",
        "camera_motion": "observed camera movement",
        "pose_change": "how the pose changes",
        "notes": "timing or realism notes"
      }}
    ],
    "native_style_constraints": ["specific rules to keep this looking like a real IG/TikTok post"],
    "copy_risk_notes": ["what would be too close to copy"],
    "required_changes": ["what to change while preserving the format"]
  }},
  "image_prompt_json": {{
    "promptMode": "structured_json",
    "subject": "one sentence in the same ImageAt-style tone as the example; describe the generated subject without naming the source person",
    "composition": {{
      "shot_type": "full-body mirror selfie, close selfie, POV, etc.",
      "aspect_ratio": "9:16",
      "framing": "exact crop and frame edges",
      "angle": "front/profile/three-quarter/POV angle",
      "pose": "exact starting pose and limb placement",
      "face_visibility": "face visible, partly obscured, or fully covered"
    }},
    "hair": {{
      "style": "visible hair style from the source frame, if relevant",
      "color": "visible hair color from the source frame, if relevant",
      "texture": "visible hair texture and polish level from the source frame, if relevant"
    }},
    "clothing": {{
      "item": "specific clothing item/category",
      "pattern": "pattern/color/vibe to preserve or adapt",
      "fit": "fit and silhouette",
      "constraints": "non-explicit, platform-safe notes"
    }},
    "body": {{
      "build": "body silhouette only, adapted to my model/Soul ID; keep adult and non-explicit",
      "pose_details": "how the pose emphasizes shape or movement without explicit nudity"
    }},
    "environment": {{
      "setting": "location type",
      "details": ["visible room/location details to preserve as a format"]
    }},
    "lighting_and_camera": {{
      "lighting": "lighting quality and direction",
      "camera_feel": "phone/pro/cinematic/mirror quality",
      "quality": "realistic texture/detail notes"
    }},
    "expression_mood": {{
      "vibe": "flirty/confident/playful/casual/etc. inferred from source",
      "details": "body language and social-native mood; keep platform-safe"
    }},
    "constraints": {{
      "must_keep": ["visual facts that matter most for matching the source format"],
      "avoid": ["visible copied face", "usernames", "watermarks", "platform UI", "explicit nudity", "model errors", "professional studio lighting unless the source has it"]
    }},
    "must_change": ["identity, username, watermark, exact protected details, and small scene variations"],
    "prompt": "paste-ready Higgsfield image prompt written from the structured visual facts; use my Soul ID model; slightly sexier/spicier if the source supports it, but non-explicit",
    "negative_prompt": "things to avoid in the image"
  }},
  "higgsfield_soul_image_prompt": "first-frame image prompt for Higgsfield Soul ID using my Soul ID model, with pose, outfit, setting, lighting, expression, framing, and style",
  "higgsfield_negative_prompt": "things to avoid in the image",
  "kling_3_video_prompt": "beat/timestamp based video prompt for Kling 3.0 using the generated Higgsfield image as first/reference frame; include subject motion, camera movement, pacing, duration/aspect ratio, and continuity",
  "kling_negative_prompt": "things to avoid in the video",
  "motion_notes": "observed subject motion, camera motion, timing, cuts, speed, and pacing",
  "camera_notes": "framing, angle, lens feel, camera distance, movement, stabilization/handheld feel",
  "style_notes": "lighting, setting, wardrobe/style, mood, platform-native vibe, text overlay if present, audio vibe if available",
  "copy_risk_notes": "what would be too close to the original and must be changed",
  "what_to_change": "specific scene/person/text/audio details to change while preserving the winning format"
}}
"""


def _normalize_analysis(item: dict[str, Any]) -> dict[str, Any]:
    analysis = dict(item.get("analysis") or item)
    analysis["schema"] = str(analysis.get("schema") or ANALYSIS_SCHEMA)
    if analysis["schema"] == "reference_factory.reference_video_analysis.v1":
        analysis["schema"] = ANALYSIS_SCHEMA
    if analysis["schema"] == "reference_factory.video_recreation_blueprint.v1":
        analysis["schema"] = ANALYSIS_SCHEMA
    analysis = _expand_minimal_prompt_analysis(analysis)
    analysis["closenessControls"] = {
        **IG_OFM_CLOSENESS_CONTROLS,
        **(
            analysis.get("closenessControls")
            if isinstance(analysis.get("closenessControls"), dict)
            else {}
        ),
    }
    analysis["winningFormatCard"] = _winning_format_card(analysis, {})
    return analysis


def _expand_minimal_prompt_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    if not any(
        key in analysis
        for key in (
            "higgsfield_soul_image_prompt",
            "kling_3_video_prompt",
            "motion_notes",
            "camera_notes",
        )
    ):
        return analysis
    blueprint = _recreation_blueprint(analysis)
    first_frame = (
        blueprint.get("first_frame")
        if isinstance(blueprint.get("first_frame"), dict)
        else {}
    )
    motion_beats = (
        blueprint.get("motion_beats")
        if isinstance(blueprint.get("motion_beats"), list)
        else []
    )
    camera_notes = str(analysis.get("camera_notes") or "")
    motion_notes = str(analysis.get("motion_notes") or "")
    style_notes = str(analysis.get("style_notes") or "")
    copy_risk_notes = str(analysis.get("copy_risk_notes") or "")
    what_to_change = str(analysis.get("what_to_change") or "")
    analysis.setdefault("platformStyle", "instagram")
    analysis.setdefault("hookType", "other")
    analysis.setdefault("captionStyle", "inferred from source; avoid exact copy")
    analysis.setdefault(
        "shotSequence",
        [str(beat.get("subject_motion") or beat) for beat in motion_beats]
        or [motion_notes or "inferred source motion"],
    )
    analysis.setdefault(
        "camera",
        {
            "framing": first_frame.get("crop") or camera_notes,
            "angle": first_frame.get("body_angle") or camera_notes,
            "movement": "; ".join(
                str(beat.get("camera_motion") or "")
                for beat in motion_beats
                if isinstance(beat, dict)
            ).strip("; ")
            or motion_notes,
            "distance": first_frame.get("camera_distance"),
            "height": first_frame.get("camera_height"),
            "lensFeel": first_frame.get("lens_feel"),
        },
    )
    analysis.setdefault(
        "subject",
        {
            "action": "; ".join(
                str(beat.get("subject_motion") or "")
                for beat in motion_beats
                if isinstance(beat, dict)
            ).strip("; ")
            or motion_notes,
            "pose": first_frame.get("pose") or motion_notes,
            "expression": first_frame.get("facial_visibility") or style_notes,
            "wardrobe": first_frame.get("outfit_silhouette") or style_notes,
            "bodyAngle": first_frame.get("body_angle"),
            "phoneOrHandPosition": first_frame.get("phone_or_hand_position"),
        },
    )
    analysis.setdefault(
        "setting",
        {
            "location": first_frame.get("room_or_location_layout") or style_notes,
            "lighting": first_frame.get("lighting") or style_notes,
            "background": first_frame.get("room_or_location_layout") or style_notes,
        },
    )
    analysis.setdefault(
        "visualPacing",
        {"energy": "medium", "cutRhythm": motion_notes, "motion": motion_notes},
    )
    analysis.setdefault(
        "audioVibe", {"energy": "medium", "bpmFeel": style_notes, "moodTags": []}
    )
    analysis.setdefault(
        "textOverlay",
        {
            "placement": "infer from source",
            "fontStyle": "infer from source",
            "safeZoneNotes": "do not copy exact text",
        },
    )
    analysis.setdefault(
        "viralMechanics", [analysis.get("summary") or "format inferred by Gemini"]
    )
    analysis.setdefault("reuseRisk", "medium")
    analysis.setdefault(
        "transformationNotes", [what_to_change] if what_to_change else []
    )
    analysis.setdefault("qualityWarnings", [copy_risk_notes] if copy_risk_notes else [])
    return analysis


def _recreation_blueprint(analysis: dict[str, Any]) -> dict[str, Any]:
    for key in ("recreation_blueprint", "recreationBlueprint", "blueprint"):
        value = analysis.get(key)
        if isinstance(value, dict):
            return value
    raw = analysis.get("raw") if isinstance(analysis.get("raw"), dict) else {}
    for key in ("recreation_blueprint", "recreationBlueprint", "blueprint"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _blueprint_first_frame(analysis: dict[str, Any]) -> dict[str, Any]:
    blueprint = _recreation_blueprint(analysis)
    value = (
        blueprint.get("first_frame")
        or blueprint.get("firstFrame")
        or blueprint.get("first_frame_blueprint")
    )
    return value if isinstance(value, dict) else {}


def _blueprint_motion_beats(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    blueprint = _recreation_blueprint(analysis)
    value = (
        blueprint.get("motion_beats")
        or blueprint.get("motionBeats")
        or blueprint.get("motion_blueprint")
    )
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _blueprint_list(analysis: dict[str, Any], key: str) -> list[str]:
    blueprint = _recreation_blueprint(analysis)
    value = blueprint.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _blueprint_first_frame_text(analysis: dict[str, Any]) -> str:
    first = _blueprint_first_frame(analysis)
    if not first:
        return ""
    parts = [
        ("subject scale", first.get("subject_scale")),
        ("crop", first.get("crop")),
        ("body angle", first.get("body_angle")),
        ("pose", first.get("pose")),
        ("phone/hand placement", first.get("phone_or_hand_position")),
        ("facial visibility", first.get("facial_visibility")),
        ("outfit silhouette", first.get("outfit_silhouette")),
        ("location layout", first.get("room_or_location_layout")),
        ("lighting", first.get("lighting")),
        ("camera height", first.get("camera_height")),
        ("camera distance", first.get("camera_distance")),
        ("lens feel", first.get("lens_feel")),
    ]
    return "; ".join(f"{label}: {value}" for label, value in parts if value)


def _blueprint_motion_text(analysis: dict[str, Any]) -> str:
    beats = _blueprint_motion_beats(analysis)
    lines = []
    for beat in beats:
        time_range = beat.get("time_range") or beat.get("timeRange") or "beat"
        detail = "; ".join(
            str(value)
            for value in (
                beat.get("subject_motion"),
                beat.get("camera_motion"),
                beat.get("pose_change"),
                beat.get("notes"),
            )
            if value
        )
        if detail:
            lines.append(f"{time_range}: {detail}")
    return " ".join(lines)


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _image_prompt_json(analysis: dict[str, Any]) -> dict[str, Any]:
    for key in ("image_prompt_json", "imagePromptJson", "image_json", "imageJson"):
        value = analysis.get(key)
        if isinstance(value, dict):
            return value
    raw = analysis.get("raw") if isinstance(analysis.get("raw"), dict) else {}
    nested = raw.get("analysis") if isinstance(raw.get("analysis"), dict) else raw
    for key in ("image_prompt_json", "imagePromptJson", "image_json", "imageJson"):
        value = nested.get(key) if isinstance(nested, dict) else None
        if isinstance(value, dict):
            return value
    return {}


def _stringify_prompt_section(label: str, value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key, inner in value.items():
            if inner in (None, "", [], {}):
                continue
            if isinstance(inner, list):
                text = ", ".join(str(item) for item in inner if str(item).strip())
            else:
                text = str(inner)
            if text.strip():
                parts.append(f"{str(key).replace('_', ' ')}: {text}")
        return f"{label}: " + "; ".join(parts) if parts else ""
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value if str(item).strip())
        return f"{label}: {text}" if text else ""
    text = str(value or "").strip()
    return f"{label}: {text}" if text else ""


def _build_image_prompt_json_from_analysis(
    analysis: dict[str, Any], *, model_profile: str | None
) -> dict[str, Any]:
    existing = _image_prompt_json(analysis)
    if existing:
        return _sanitize_image_prompt_json(existing, model_profile=model_profile)
    first = _blueprint_first_frame(analysis)
    setting = (
        analysis.get("setting") if isinstance(analysis.get("setting"), dict) else {}
    )
    subject = (
        analysis.get("subject") if isinstance(analysis.get("subject"), dict) else {}
    )
    profile = _clean_prompt_text(model_profile) or "my Soul ID model"
    clothing = (
        first.get("outfit_silhouette")
        or subject.get("wardrobe")
        or "fitted social-safe outfit matching the source silhouette"
    )
    environment = (
        first.get("room_or_location_layout")
        or setting.get("location")
        or setting.get("background")
        or "source-matched lifestyle setting"
    )
    lighting = (
        first.get("lighting")
        or setting.get("lighting")
        or "source-matched natural lighting"
    )
    pose = (
        first.get("pose")
        or subject.get("pose")
        or subject.get("action")
        or "source-matched starting pose"
    )
    prompt = _clean_prompt_text(
        _analysis_value(analysis, "higgsfield_soul_image_prompt")
    )
    return _sanitize_image_prompt_json(
        {
            "subject": f"{profile} posing in the observed short-form format.",
            "composition": {
                "shot_type": analysis.get("contentFormat")
                or "vertical short-form reference frame",
                "aspect_ratio": "9:16",
                "framing": first.get("crop") or "match source crop and subject scale",
                "angle": first.get("body_angle") or "match source body/camera angle",
                "pose": pose,
                "face_visibility": first.get("facial_visibility")
                or subject.get("expression")
                or "match source facial visibility",
            },
            "clothing": {
                "item": clothing,
                "pattern": "preserve source outfit vibe when safe; change exact branding or identifiers",
                "fit": clothing,
                "constraints": "slightly sexier/spicier if the source supports it, non-explicit and platform-safe",
            },
            "body": {
                "build": "adapt to the selected Soul ID/model identity; preserve the source silhouette emphasis without copying the original person",
                "pose_details": first.get("body_angle")
                or first.get("pose")
                or "source-matched confident pose",
            },
            "environment": {
                "setting": environment,
                "details": [environment],
            },
            "lighting_and_camera": {
                "lighting": lighting,
                "camera_feel": first.get("lens_feel")
                or "real phone-native social media image",
                "quality": "sharp realistic phone photo, believable skin texture, not overprocessed",
            },
            "must_keep": [
                item
                for item in (
                    f"subject scale: {first.get('subject_scale')}"
                    if first.get("subject_scale")
                    else "",
                    f"crop: {first.get('crop')}" if first.get("crop") else "",
                    f"body angle: {first.get('body_angle')}"
                    if first.get("body_angle")
                    else "",
                    f"phone/hand placement: {first.get('phone_or_hand_position')}"
                    if first.get("phone_or_hand_position")
                    else "",
                    f"environment layout: {first.get('room_or_location_layout')}"
                    if first.get("room_or_location_layout")
                    else "",
                )
                if item
            ],
            "constraints": {
                "must_keep": [
                    item
                    for item in (
                        first.get("outfit_silhouette"),
                        first.get("phone_or_hand_position"),
                        first.get("facial_visibility"),
                        first.get("room_or_location_layout"),
                    )
                    if item
                ],
                "avoid": [
                    "visible copied identity",
                    "username",
                    "watermark",
                    "platform UI",
                    "explicit nudity",
                    "professional studio lighting unless source has it",
                    "cluttered background unless source has it",
                ],
            },
            "must_change": _blueprint_list(analysis, "required_changes")
            or [
                "replace original identity with my Soul ID model",
                "remove username, watermark, platform UI, and exact unique identifiers",
            ],
            "prompt": prompt,
            "negative_prompt": _clean_prompt_text(
                _analysis_value(analysis, "higgsfield_negative_prompt")
            ),
        },
        model_profile=model_profile,
    )


def _sanitize_image_prompt_json(
    card: dict[str, Any], *, model_profile: str | None
) -> dict[str, Any]:
    profile = _clean_prompt_text(model_profile) or "my Soul ID model"
    cleaned = _sanitize_prompt_value(json.loads(json.dumps(card)), profile=profile)
    cleaned["prompt_schema_version"] = (
        cleaned.get("prompt_schema_version") or "imageat_higgsfield.v1"
    )

    subject = _clean_prompt_text(cleaned.get("subject"))
    if subject:
        legacy_profile = "Adult " + profile
        subject = subject.replace(legacy_profile + " Soul ID model", profile)
        subject = subject.replace(legacy_profile, profile)
        subject = subject.replace("adult " + profile, profile)
        subject = subject.replace("adult my Soul ID model", profile)
        cleaned["subject"] = subject

    constraints = (
        cleaned.get("constraints")
        if isinstance(cleaned.get("constraints"), dict)
        else {}
    )
    avoid = constraints.get("avoid")
    if isinstance(avoid, list):
        banned = {
            "changed " + "hair color",
            "forced new " + "hairstyle",
            "tat" + "toos",
            "body markings",
            "scars",
            "new piercings",
        }
        constraints["avoid"] = [
            item for item in avoid if str(item).strip().lower() not in banned
        ]
        cleaned["constraints"] = constraints

    cleaned.setdefault(
        "skin",
        {
            "texture": "Realistic natural skin texture, believable phone-photo detail.",
        },
    )
    cleaned.setdefault(
        "expression_mood",
        {
            "vibe": "Confident, flirty, social-safe outfit-check energy.",
        },
    )

    return cleaned


def _sanitize_prompt_value(value: Any, *, profile: str) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_prompt_value(inner, profile=profile)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_prompt_value(item, profile=profile) for item in value]
    if not isinstance(value, str):
        return value
    legacy_profile = "Adult " + profile
    replacements = {
        legacy_profile + " Soul ID model": profile,
        legacy_profile: profile,
        "adult " + profile: profile,
        "adult my Soul ID model": profile,
        profile + "'s adult Soul ID figure": profile + "'s Soul ID figure",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _imageat_prompt_payload(card: dict[str, Any]) -> dict[str, Any]:
    ordered_keys = [
        "prompt_schema_version",
        "subject",
        "prompt",
        "composition",
        "hair",
        "clothing",
        "body",
        "skin",
        "expression_mood",
        "environment",
        "lighting_and_camera",
        "constraints",
        "must_keep",
        "must_change",
        "negative_prompt",
        "motion",
    ]
    return {
        key: card[key]
        for key in ordered_keys
        if card.get(key) not in (None, "", [], {})
    }


def _compose_higgsfield_from_image_json(
    card: dict[str, Any], *, model_profile: str | None, fallback_prompt: str
) -> str:
    card = _sanitize_image_prompt_json(card, model_profile=model_profile)
    if card.get("promptMode") == "structured_json" or (
        isinstance(card.get("composition"), dict)
        and isinstance(card.get("clothing"), dict)
    ):
        prompt_card = _imageat_prompt_payload(card)
        return json.dumps(prompt_card, indent=2, ensure_ascii=False)
    profile = _clean_prompt_text(model_profile) or "my Soul ID model"
    base_prompt = _clean_prompt_text(card.get("prompt")) or _clean_prompt_text(
        fallback_prompt
    )
    sections = [
        _stringify_prompt_section(
            "Subject", card.get("subject") or f"{profile} as the subject"
        ),
        _stringify_prompt_section("Composition", card.get("composition")),
        _stringify_prompt_section("Hair", card.get("hair")),
        _stringify_prompt_section("Clothing", card.get("clothing")),
        _stringify_prompt_section("Body", card.get("body")),
        _stringify_prompt_section("Skin", card.get("skin")),
        _stringify_prompt_section(
            "Expression and mood",
            card.get("expression_mood") or card.get("expressionMood"),
        ),
        _stringify_prompt_section("Environment", card.get("environment")),
        _stringify_prompt_section(
            "Lighting and camera",
            card.get("lighting_and_camera") or card.get("lightingAndCamera"),
        ),
        _stringify_prompt_section("Constraints", card.get("constraints")),
        _stringify_prompt_section(
            "Must keep", card.get("must_keep") or card.get("mustKeep")
        ),
        _stringify_prompt_section(
            "Must change", card.get("must_change") or card.get("mustChange")
        ),
    ]
    facts = ". ".join(section for section in sections if section)
    return (
        f"{base_prompt}. "
        f"{facts}. "
        "Keep the result slightly sexier/spicier only through pose, fitted styling, confidence, and framing; keep it non-explicit and social-platform safe. "
        "Do not copy the original person's identity, username, watermark, platform UI, or uniquely identifying details. "
        "Prioritize source-format accuracy over cinematic beauty."
    )


def _local_video_analysis(
    job: dict[str, Any], *, data_root: Path, platform: str, ffprobe: str, ffmpeg: str
) -> dict[str, Any]:
    source = Path(job["path"]).expanduser()
    probe = _probe_media(source, ffprobe=ffprobe)
    frame_dir = data_root / "reference_intake" / "frames" / job["reference_id"]
    frames = _extract_reference_frames(
        source,
        frame_dir=frame_dir,
        duration=probe.get("durationSeconds"),
        ffmpeg=ffmpeg,
    )
    filename_text = " ".join(
        str(value or "") for value in (job.get("file_name"), job.get("account"), source)
    ).lower()
    format_type = _classify_reference_format(job, {"summary": filename_text})
    frame_analysis = _analyze_reference_frame_pixels(frames, probe)
    format_type = _format_from_local_frame_analysis(format_type, probe, frame_analysis)
    energy = str(frame_analysis.get("energy") or _energy_from_probe(probe))
    scene_cuts = _detect_scene_cuts(
        source, duration=probe.get("durationSeconds"), ffmpeg=ffmpeg
    )
    ocr_text = _sidecar_text(source)
    pattern = _pattern_card_from_local(
        job,
        platform=platform,
        probe=probe,
        frame_samples=frames,
        format_type=format_type,
        energy=energy,
        ocr_text=ocr_text,
        frame_analysis=frame_analysis,
        scene_cuts=scene_cuts,
    )
    analysis_id = stable_id(
        "reference_video_analysis",
        job["reference_id"],
        "local",
        probe.get("durationSeconds"),
        format_type,
    )
    return {
        "schema": ANALYSIS_SCHEMA,
        "id": analysis_id,
        "referenceId": job["reference_id"],
        "provider": "local",
        "status": "pattern_ready",
        "media": probe,
        "signals": {
            "frameSamples": frames,
            "framePixelAnalysis": frame_analysis,
            "sceneCuts": scene_cuts,
            "motion": {
                "energy": energy,
                "method": frame_analysis.get("method")
                if frame_analysis.get("status") == "analyzed"
                else "duration_resolution_heuristic",
                "meanFrameDelta": frame_analysis.get("meanFrameDelta"),
            },
            "ocrText": ocr_text,
            "audioPresence": {"hasAudio": probe.get("hasAudio")},
            "transcript": _sidecar_text(source.with_suffix(".transcript.txt")),
            "dedupe": {
                "frameSampleCount": len(frames),
                "method": "local_frame_manifest_v1",
            },
        },
        "patternCard": pattern,
        "raw": {"probe": probe},
    }


def _store_pattern_and_analysis(
    conn: Connection,
    *,
    job: dict[str, Any],
    analysis: dict[str, Any],
    provider: str,
    timestamp: str,
) -> None:
    pattern = (
        analysis.get("patternCard")
        if isinstance(analysis.get("patternCard"), dict)
        else {}
    )
    pattern_id = str(
        pattern.get("id")
        or stable_id("viral_pattern_card", job["reference_id"], provider)
    )
    pattern["id"] = pattern_id
    analysis["patternCard"] = pattern
    validate_pattern_card(pattern)
    validate_video_analysis(analysis)
    conn.execute(
        """
        INSERT INTO viral_pattern_cards (
          id, reference_id, analysis_job_id, platform, status, pattern_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'pattern_ready', ?, ?, ?)
        ON CONFLICT(reference_id, analysis_job_id) DO UPDATE SET
          platform = excluded.platform,
          status = excluded.status,
          pattern_json = excluded.pattern_json,
          updated_at = excluded.updated_at
        """,
        (
            pattern_id,
            job["reference_id"],
            job.get("id"),
            str(pattern.get("platform") or job.get("source_platform") or "unknown"),
            json_dump(pattern),
            timestamp,
            timestamp,
        ),
    )
    conn.execute(
        """
        INSERT INTO reference_video_analyses (
          id, reference_id, analysis_job_id, provider, status, media_json,
          signals_json, pattern_card_id, analysis_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(reference_id, provider) DO UPDATE SET
          analysis_job_id = excluded.analysis_job_id,
          status = excluded.status,
          media_json = excluded.media_json,
          signals_json = excluded.signals_json,
          pattern_card_id = excluded.pattern_card_id,
          analysis_json = excluded.analysis_json,
          updated_at = excluded.updated_at
        """,
        (
            analysis["id"],
            job["reference_id"],
            job.get("id"),
            _norm(provider),
            analysis.get("status") or "pattern_ready",
            json_dump(analysis.get("media") or {}),
            json_dump(analysis.get("signals") or {}),
            pattern_id,
            json_dump(analysis),
            timestamp,
            timestamp,
        ),
    )
    job_analysis = _analysis_from_pattern(analysis)
    raw_analysis = (
        (analysis.get("raw") or {}).get("analysis")
        if isinstance(analysis.get("raw"), dict)
        else {}
    )
    direct_prompt_fields = (
        "higgsfield_soul_image_prompt",
        "higgsfield_negative_prompt",
        "kling_3_video_prompt",
        "kling_negative_prompt",
        "motion_notes",
        "camera_notes",
        "style_notes",
        "copy_risk_notes",
        "what_to_change",
        "image_prompt_json",
    )
    for key in direct_prompt_fields:
        value = analysis.get(key) or (
            raw_analysis.get(key) if isinstance(raw_analysis, dict) else None
        )
        if value:
            job_analysis[key] = value
    blueprint = _recreation_blueprint(analysis) or (
        _recreation_blueprint(raw_analysis) if isinstance(raw_analysis, dict) else {}
    )
    if blueprint:
        job_analysis["recreation_blueprint"] = blueprint
    conn.execute(
        "UPDATE reference_analysis_jobs SET status = 'pattern_ready', analysis_json = ?, updated_at = ? WHERE id = ?",
        (json_dump(job_analysis), timestamp, job.get("id")),
    )


def _probe_media(source: Path, *, ffprobe: str) -> dict[str, Any]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(source),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), {}
    )
    duration = _float(video.get("duration")) or _float(
        (data.get("format") or {}).get("duration")
    )
    width = int(video.get("width") or 0) or None
    height = int(video.get("height") or 0) or None
    return {
        "path": str(source),
        "durationSeconds": duration,
        "width": width,
        "height": height,
        "codec": video.get("codec_name"),
        "aspectRatio": round(width / height, 4) if width and height else None,
        "hasAudio": any(stream.get("codec_type") == "audio" for stream in streams),
        "streamCount": len(streams),
    }


def _extract_reference_frames(
    source: Path, *, frame_dir: Path, duration: float | None, ffmpeg: str
) -> list[dict[str, Any]]:
    frame_dir.mkdir(parents=True, exist_ok=True)
    duration = duration if duration and duration > 0 else 6.0
    times = sorted(
        {
            round(max(0.0, min(duration * ratio, max(duration - 0.05, 0.0))), 3)
            for ratio in (0.15, 0.5, 0.85)
        }
    )
    frames: list[dict[str, Any]] = []
    for index, time_sec in enumerate(times, start=1):
        out = frame_dir / f"frame_{index:02d}.jpg"
        if not out.exists():
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss",
                    str(time_sec),
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        frames.append(
            {
                "timeSec": time_sec,
                "role": f"sample_{index}",
                "path": str(out),
                "exists": out.exists(),
            }
        )
    return frames


def _detect_scene_cuts(
    source: Path, *, duration: float | None, ffmpeg: str
) -> list[float]:
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(source),
        "-vf",
        "select='gt(scene,0.35)',showinfo",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return _scene_cut_guesses(duration)
    cuts = {0.0}
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr):
        cut = round(float(match.group(1)), 2)
        if cut > 0 and (not duration or cut < duration):
            cuts.add(cut)
    return sorted(cuts) or _scene_cut_guesses(duration)


def _analyze_reference_frame_pixels(
    frame_samples: list[dict[str, Any]], probe: dict[str, Any]
) -> dict[str, Any]:
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {
            "status": "unavailable",
            "method": "local_frame_pixel_analysis_v1",
            "reason": "Pillow is not installed for reference_factory local analysis.",
        }

    frames: list[dict[str, Any]] = []
    small_frames = []
    for sample in frame_samples:
        path = Path(str(sample.get("path") or ""))
        if not path.exists():
            continue
        try:
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                small = rgb.resize((64, 64))
                stat = ImageStat.Stat(small)
                means = [value / 255.0 for value in stat.mean]
                extrema = small.getextrema()
                luminance = 0.2126 * means[0] + 0.7152 * means[1] + 0.0722 * means[2]
                contrast = sum((high - low) / 255.0 for low, high in extrema) / 3.0
                max_channel = max(means)
                saturation = (
                    (max_channel - min(means)) / max(max_channel, 0.001)
                    if max_channel
                    else 0.0
                )
                frames.append(
                    {
                        "timeSec": sample.get("timeSec"),
                        "role": sample.get("role"),
                        "brightness": round(luminance, 4),
                        "contrast": round(contrast, 4),
                        "saturation": round(saturation, 4),
                    }
                )
                small_frames.append(small.tobytes())
        except (OSError, ValueError):
            continue

    if not frames:
        return {
            "status": "unavailable",
            "method": "local_frame_pixel_analysis_v1",
            "reason": "No extracted frames could be decoded.",
        }

    deltas = []
    for prev, cur in zip(small_frames, small_frames[1:]):
        if not prev or not cur:
            continue
        diff = sum(abs(a - b) for a, b in zip(prev, cur))
        deltas.append(diff / (len(prev) * 255.0))
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    avg_brightness = sum(frame["brightness"] for frame in frames) / len(frames)
    avg_contrast = sum(frame["contrast"] for frame in frames) / len(frames)
    avg_saturation = sum(frame["saturation"] for frame in frames) / len(frames)
    width = int(probe.get("width") or 0)
    height = int(probe.get("height") or 0)
    vertical = bool(width and height and height / max(width, 1) >= 1.45)
    if mean_delta >= 0.18:
        energy = "high"
        movement = "noticeable motion or scene changes between sampled frames"
    elif mean_delta >= 0.07:
        energy = "medium"
        movement = "moderate handheld motion or pose change"
    else:
        energy = "low"
        movement = "locked-off or near-static composition"
    lighting = (
        "bright"
        if avg_brightness >= 0.62
        else "dim"
        if avg_brightness <= 0.34
        else "balanced"
    )
    color = "colorful" if avg_saturation >= 0.38 else "neutral-toned"
    framing = "vertical phone-native" if vertical else "non-vertical or cropped"
    shot_sequence = [
        f"{frame['role']} at {frame['timeSec']}s: {lighting} {color} frame, contrast {frame['contrast']:.2f}"
        for frame in frames[:3]
    ]
    return {
        "status": "analyzed",
        "method": "local_frame_pixel_analysis_v1",
        "frameCount": len(frames),
        "averageBrightness": round(avg_brightness, 4),
        "averageContrast": round(avg_contrast, 4),
        "averageSaturation": round(avg_saturation, 4),
        "meanFrameDelta": round(mean_delta, 4),
        "energy": energy,
        "movement": movement,
        "framing": framing,
        "lighting": lighting,
        "colorPalette": color,
        "subjectCount": "unknown_without_vlm",
        "wardrobe": "unknown_without_vlm",
        "setting": f"{lighting} {color} source-inspired setting",
        "subjectAction": f"{movement}; preserve source pose/action without copying identity",
        "shotSequence": shot_sequence,
        "frames": frames,
    }


def _format_from_local_frame_analysis(
    fallback: str, probe: dict[str, Any], frame_analysis: dict[str, Any]
) -> str:
    if frame_analysis.get("status") != "analyzed":
        return fallback
    width = int(probe.get("width") or 0)
    height = int(probe.get("height") or 0)
    vertical = bool(width and height and height / max(width, 1) >= 1.45)
    if not vertical:
        return fallback
    if frame_analysis.get("energy") == "high":
        return "walking_clip"
    if fallback == "visual_reference":
        return "short_vertical_visual_hook"
    return fallback


def _pattern_card_from_local(
    job: dict[str, Any],
    *,
    platform: str,
    probe: dict[str, Any],
    frame_samples: list[dict[str, Any]],
    format_type: str,
    energy: str,
    ocr_text: str,
    frame_analysis: dict[str, Any],
    scene_cuts: list[float],
) -> dict[str, Any]:
    reference_id = job["reference_id"]
    hook_type = "relationship" if _contains_relationship_terms(job, ocr_text) else "pov"
    local_analyzed = frame_analysis.get("status") == "analyzed"
    shot_sequence = frame_analysis.get("shotSequence") if local_analyzed else None
    camera_movement = (
        frame_analysis.get("movement") if local_analyzed else "subtle handheld"
    )
    return {
        "schema": PATTERN_CARD_SCHEMA,
        "id": stable_id("viral_pattern_card", reference_id, format_type, hook_type),
        "platform": _norm(platform),
        "source": {
            "referenceId": reference_id,
            "creator": job.get("account"),
            "path": job.get("path"),
            "fileName": job.get("file_name"),
            "frameSamples": frame_samples,
        },
        "formatType": format_type,
        "hookType": hook_type,
        "visualPattern": (
            f"{format_type.replace('_', ' ')} reference measured from {len(frame_samples)} sampled frames; "
            f"{frame_analysis.get('lighting', 'unknown')} lighting, "
            f"{frame_analysis.get('colorPalette', 'unknown')} palette."
            if local_analyzed
            else f"{format_type.replace('_', ' ')} reference with phone-native composition and short-form overlay language."
        ),
        "setting": frame_analysis.get("setting")
        if local_analyzed
        else "source-inspired but original setting",
        "shotSequence": shot_sequence or _shot_sequence_for(format_type, probe),
        "cameraStyle": {
            "framing": frame_analysis.get("framing", "vertical 9:16"),
            "movement": camera_movement,
            "angle": "phone-native",
        },
        "subjectAction": frame_analysis.get(
            "subjectAction", "creator-style pose or expression shift"
        ),
        "subject": {
            "count": frame_analysis.get("subjectCount", "unknown_without_vlm"),
            "wardrobe": frame_analysis.get("wardrobe", "unknown_without_vlm"),
        },
        "textOverlayStyle": {
            "placement": "safe top or lower third",
            "fontStyle": "white text with dark stroke",
            "detectedText": ocr_text,
        },
        "pacing": {
            "energy": energy,
            "cutRhythm": "scene-change cuts" if len(scene_cuts) > 1 else "single shot",
            "sceneCuts": scene_cuts,
        },
        "audioVibe": {"energy": energy, "moodTags": ["glam", "relationship", "ai_ofm"]},
        "ctaPattern": "curiosity-first soft CTA",
        "reuseRisk": "medium",
        "copyRiskNotes": [
            "Do not copy the creator identity, username, watermark, exact room, or exact overlay copy."
        ],
        "transformationInstructions": [
            "Keep the winning format, but change model identity, wardrobe, pose details, setting, caption, and native audio."
        ],
        "viralityMetrics": {},
        "qualityWarnings": [
            "Local pixel analysis does not identify exact wardrobe, identity, or subject count; use Gemini/VLM analysis for semantic details."
        ],
    }


def _pattern_card_from_analysis(
    job: dict[str, Any], analysis: dict[str, Any]
) -> dict[str, Any]:
    card = _winning_format_card(analysis, job)
    visual_format = str(
        card.get("visualFormat") or analysis.get("contentFormat") or "other"
    )
    hook_type = str(analysis.get("hookType") or "pov")
    return {
        "schema": PATTERN_CARD_SCHEMA,
        "id": stable_id(
            "viral_pattern_card", job.get("reference_id"), visual_format, hook_type
        ),
        "platform": _norm(
            analysis.get("platformStyle") or job.get("source_platform") or "instagram"
        ),
        "source": {
            "referenceId": job.get("reference_id"),
            "creator": job.get("account"),
            "path": job.get("path"),
            "fileName": job.get("file_name"),
        },
        "formatType": visual_format,
        "hookType": hook_type,
        "visualPattern": str(
            analysis.get("summary")
            or f"{visual_format.replace('_', ' ')} creator reference"
        ),
        "setting": card.get("setting"),
        "shotSequence": analysis.get("shotSequence")
        if isinstance(analysis.get("shotSequence"), list)
        else ["short-form opening beat"],
        "cameraStyle": analysis.get("camera")
        if isinstance(analysis.get("camera"), dict)
        else card.get("camera") or {},
        "subjectAction": str(
            (analysis.get("subject") or {}).get("action")
            if isinstance(analysis.get("subject"), dict)
            else card.get("poseAction") or "creator-style pose"
        ),
        "textOverlayStyle": analysis.get("textOverlay")
        if isinstance(analysis.get("textOverlay"), dict)
        else card.get("textOverlay") or {},
        "pacing": analysis.get("visualPacing")
        if isinstance(analysis.get("visualPacing"), dict)
        else card.get("pacing") or {},
        "audioVibe": analysis.get("audioVibe")
        if isinstance(analysis.get("audioVibe"), dict)
        else card.get("audioVibe") or {},
        "ctaPattern": analysis.get("ctaPattern"),
        "reuseRisk": str(analysis.get("reuseRisk") or "medium")
        if str(analysis.get("reuseRisk") or "medium") in {"low", "medium", "high"}
        else "medium",
        "copyRiskNotes": card.get("copyRiskNotes")
        or analysis.get("copyRiskNotes")
        or [
            "Do not copy creator identity, exact overlay copy, watermark, or username."
        ],
        "transformationInstructions": card.get("transformationInstructions")
        or analysis.get("transformationNotes")
        or ["Change model identity, scene details, outfit, caption, and audio."],
        "viralityMetrics": analysis.get("viralityMetrics")
        if isinstance(analysis.get("viralityMetrics"), dict)
        else {},
        "qualityWarnings": analysis.get("qualityWarnings")
        if isinstance(analysis.get("qualityWarnings"), list)
        else [],
    }


def _analysis_from_pattern(analysis: dict[str, Any]) -> dict[str, Any]:
    pattern = analysis.get("patternCard") or {}
    return {
        "schema": ANALYSIS_SCHEMA,
        "referenceId": analysis.get("referenceId"),
        "summary": pattern.get("visualPattern") or "Local reference analysis",
        "platformStyle": pattern.get("platform") or "instagram",
        "contentFormat": pattern.get("formatType") or "other",
        "hookType": pattern.get("hookType") or "pov",
        "captionStyle": (pattern.get("textOverlayStyle") or {}).get("fontStyle")
        or "white text with dark stroke",
        "closenessControls": dict(IG_OFM_CLOSENESS_CONTROLS),
        "winningFormatCard": _format_card_from_pattern(pattern),
        "shotSequence": pattern.get("shotSequence") or [],
        "camera": pattern.get("cameraStyle") or {},
        "subject": {"action": pattern.get("subjectAction")},
        "setting": {
            "location": (
                _format_card_from_pattern(pattern).get("setting")
                or "source-inspired but original setting"
            )
        },
        "visualPacing": pattern.get("pacing") or {},
        "audioVibe": pattern.get("audioVibe") or {},
        "textOverlay": pattern.get("textOverlayStyle") or {},
        "viralMechanics": [
            "format familiarity",
            "fast-readable overlay",
            "native audio slot",
        ],
        "reuseRisk": pattern.get("reuseRisk") or "medium",
        "transformationNotes": pattern.get("transformationInstructions") or [],
        "qualityWarnings": pattern.get("qualityWarnings") or [],
        "patternCard": pattern,
    }


def _format_card_from_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    return {
        "visualFormat": pattern.get("formatType") or "other",
        "formatPriorityRank": FORMAT_PRIORITY.index(pattern.get("formatType")) + 1
        if pattern.get("formatType") in FORMAT_PRIORITY
        else len(FORMAT_PRIORITY),
        "poseAction": pattern.get("subjectAction"),
        "camera": pattern.get("cameraStyle") or {},
        "lighting": "source-matched flattering light",
        "setting": pattern.get("setting") or "source-inspired but original setting",
        "styling": "model-appropriate spicy OFM-coded styling",
        "textOverlay": pattern.get("textOverlayStyle") or {},
        "pacing": pattern.get("pacing") or {},
        "audioVibe": pattern.get("audioVibe") or {},
        "hookMechanics": ["clear premise", "fast recognition"],
        "copyRiskNotes": pattern.get("copyRiskNotes") or [],
        "transformationInstructions": pattern.get("transformationInstructions") or [],
    }


def _kling_scenes(
    analysis: dict[str, Any], card: dict[str, Any]
) -> list[dict[str, Any]]:
    beats = _blueprint_motion_beats(analysis)
    if beats:
        return [
            {
                "timeRange": str(beat.get("time_range") or beat.get("timeRange") or ""),
                "durationSeconds": None,
                "action": str(beat.get("subject_motion") or ""),
                "camera": str(
                    beat.get("camera_motion")
                    or "preserve first-frame phone-native camera"
                ),
                "poseChange": str(beat.get("pose_change") or ""),
                "notes": str(beat.get("notes") or ""),
            }
            for beat in beats[:4]
        ]
    sequence = (
        analysis.get("shotSequence")
        if isinstance(analysis.get("shotSequence"), list)
        else []
    )
    if not sequence:
        sequence = (
            card.get("transformationInstructions")
            if isinstance(card.get("transformationInstructions"), list)
            else []
        )
    if not sequence:
        sequence = [
            "open on the Soul ID model in the source-inspired format",
            "hold for readable caption and subtle expression shift",
        ]
    duration = 5
    per_scene = max(1, round(duration / min(len(sequence), 4), 2))
    return [
        {
            "durationSeconds": per_scene,
            "action": str(item),
            "camera": (card.get("camera") or {}).get("movement")
            if isinstance(card.get("camera"), dict)
            else "phone-native subtle motion",
        }
        for item in sequence[:4]
    ]


def _scene_cut_guesses(duration: float | None) -> list[float]:
    if not duration or duration <= 3:
        return [0.0]
    if duration <= 8:
        return [0.0, round(duration / 2, 2)]
    return [0.0, round(duration / 3, 2), round(duration * 2 / 3, 2)]


def _energy_from_probe(probe: dict[str, Any]) -> str:
    duration = probe.get("durationSeconds")
    if isinstance(duration, (int, float)) and duration <= 5:
        return "high"
    if isinstance(duration, (int, float)) and duration >= 14:
        return "low"
    return "medium"


def _sidecar_text(path: Path) -> str:
    candidate = path if path.suffix == ".txt" else path.with_suffix(".txt")
    try:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()[:1000]
    except OSError:
        return ""
    return ""


def _contains_relationship_terms(job: dict[str, Any], ocr_text: str) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            job.get("file_name"),
            job.get("account"),
            job.get("path"),
            ocr_text,
        )
    ).lower()
    return any(
        word in text
        for word in (
            "boy",
            "girl",
            "him",
            "her",
            "love",
            "dating",
            "relationship",
            "men",
            "women",
        )
    )


def _shot_sequence_for(format_type: str, probe: dict[str, Any]) -> list[str]:
    if format_type == "slideshow":
        return ["cover image hook", "supporting image beat", "final CTA image"]
    if format_type == "mirror_selfie":
        return ["mirror selfie opening", "subtle pose or expression shift"]
    if format_type == "selfie_video":
        return ["close selfie hook", "micro expression shift", "hold for caption read"]
    if format_type == "spicy_lifestyle":
        return [
            "lifestyle establishing pose",
            "small camera or body movement",
            "caption punchline hold",
        ]
    return ["vertical short-form opening", "caption read beat"]


def _float(value: object) -> float | None:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _wait_for_gemini_file(
    client: Any, uploaded: Any, *, timeout_seconds: int = 300
) -> Any:
    name = getattr(uploaded, "name", None)
    if not name:
        return uploaded
    deadline = time.time() + timeout_seconds
    current = uploaded
    while time.time() < deadline:
        state = str(
            getattr(
                getattr(current, "state", None), "name", getattr(current, "state", "")
            )
        ).upper()
        if state in {"ACTIVE", "SUCCEEDED", ""}:
            return current
        if state in {"FAILED", "ERROR"}:
            raise RuntimeError(f"Gemini file processing failed for {name}")
        time.sleep(2)
        current = client.files.get(name=name)
    raise TimeoutError(f"Gemini file processing timed out for {name}")


def _json_from_model_text(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Gemini response did not contain a JSON object")
        parsed = json.loads(clean[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Gemini response JSON must be an object")
    return parsed


def _heuristic_analysis(job: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        str(value or "")
        for value in (job.get("file_name"), job.get("account"), job.get("path"))
    ).lower()
    content_format = _classify_reference_format(job, {})
    hook_type = (
        "relationship"
        if any(word in text for word in ("boy", "girl", "relationship", "love"))
        else "pov"
    )
    analysis = {
        "schema": ANALYSIS_SCHEMA,
        "referenceId": job.get("reference_id"),
        "summary": "Short-form creator reference needing Gemini review.",
        "platformStyle": job.get("source_platform") or "unknown",
        "contentFormat": content_format,
        "hookType": hook_type,
        "captionStyle": "short high-contrast text overlay",
        "shotSequence": ["single vertical reference composition"],
        "camera": {
            "framing": "vertical 9:16",
            "angle": "phone-style",
            "movement": "subtle handheld or still",
        },
        "subject": {
            "action": "pose naturally",
            "pose": "casual confident pose",
            "expression": "soft confident",
            "wardrobe": "account-appropriate outfit",
        },
        "setting": {
            "location": "bedroom, mirror, car, or lifestyle setting",
            "lighting": "soft flattering light",
            "background": "clean lifestyle background",
        },
        "visualPacing": {
            "energy": "medium",
            "cutRhythm": "short-form native",
            "motion": "subtle",
        },
        "audioVibe": {
            "energy": "medium",
            "bpmFeel": "current native sound",
            "moodTags": ["glam", "relationship", "ai_ofm"],
        },
        "textOverlay": {
            "placement": "safe top or lower third",
            "fontStyle": "white text with dark stroke",
            "safeZoneNotes": "avoid face and app UI",
        },
        "viralMechanics": ["clear visual identity", "simple hook", "native audio fit"],
        "reuseRisk": "medium",
        "transformationNotes": [
            "change setting, styling, pose, caption, and audio while preserving only the format"
        ],
        "qualityWarnings": [
            "needs manual Gemini analysis before high-confidence reuse"
        ],
    }
    analysis["closenessControls"] = dict(IG_OFM_CLOSENESS_CONTROLS)
    analysis["winningFormatCard"] = _winning_format_card(analysis, job)
    return analysis


def _prompt_for_tool(
    target_tool: str,
    job: dict[str, Any],
    analysis: dict[str, Any],
    model_profile: str | None,
) -> dict[str, Any]:
    target_tool = _canonical_tool(target_tool)
    if target_tool == "higgsfield_soul_image":
        return _higgsfield_prompt(job, analysis, model_profile)
    if target_tool == "kling_3_video":
        return _kling_prompt(job, analysis, model_profile)
    raise ValueError(f"unsupported target tool: {target_tool}")


def _analysis_value(analysis: dict[str, Any], key: str) -> Any:
    if analysis.get(key) is not None:
        return analysis.get(key)
    raw = analysis.get("raw") if isinstance(analysis.get("raw"), dict) else {}
    nested = raw.get("analysis") if isinstance(raw.get("analysis"), dict) else {}
    return nested.get(key)


def _clean_prompt_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _compose_higgsfield_main_prompt(
    *,
    analysis_prompt: Any,
    analysis: dict[str, Any],
    model_profile: str | None,
    fallback_prompt: str,
) -> str:
    image_card = _build_image_prompt_json_from_analysis(
        analysis, model_profile=model_profile
    )
    if image_card:
        return _compose_higgsfield_from_image_json(
            image_card, model_profile=model_profile, fallback_prompt=fallback_prompt
        )
    body = _clean_prompt_text(analysis_prompt) or _clean_prompt_text(fallback_prompt)
    blueprint = _blueprint_first_frame_text(analysis)
    native_constraints = "; ".join(
        _blueprint_list(analysis, "native_style_constraints")
    )
    required_changes = "; ".join(_blueprint_list(analysis, "required_changes"))
    profile = _clean_prompt_text(model_profile) or "the selected Soul ID profile"
    return (
        "Higgsfield Soul ID first-frame image prompt. "
        f"Use {profile} as the subject identity. "
        "Generate one vertical 9:16 reference image only, not a video. "
        "Match the reference STARTING FRAME composition closely: same crop, subject scale, body angle, pose geometry, camera height, camera distance, lens feel, phone/hand placement, facial visibility, lighting type, and room/location layout. "
        "Replace the person with my Soul ID model. Preserve the outfit silhouette and fit category, but change exact color/pattern/branding. Preserve the room/location type, but change unique decor and identifying details. "
        "Keep amateur phone-shot Instagram Reels realism; do not make it cinematic, polished, or fashion-editorial unless the source is. "
        f"Observed first-frame blueprint: {blueprint or body}. "
        f"Scene prompt: {body}. "
        f"Native constraints: {native_constraints or 'realistic iPhone/social camera, imperfect natural framing, believable anatomy'}. "
        f"Required changes: {required_changes or 'new identity, no copied face, no exact outfit, no username, no watermark, no exact text'}. "
        "This image must be a clean first/reference frame that Kling can animate without reframing."
    )


def _compose_kling_main_prompt(
    *,
    analysis_prompt: Any,
    analysis: dict[str, Any],
    model_profile: str | None,
    fallback_prompt: str,
) -> str:
    body = _clean_prompt_text(analysis_prompt) or _clean_prompt_text(fallback_prompt)
    first_frame = _blueprint_first_frame_text(analysis)
    directives = _motion_directives(analysis, fallback_motion=body)
    must_preserve = "; ".join(directives["must_preserve"])
    avoid = "; ".join(directives["avoid"])
    return (
        "Kling 3.0 image-to-video prompt. "
        "Use the generated image as the first/reference frame. "
        "Preserve the starting image; animate it without redesigning it. "
        "Create a vertical 9:16 Instagram Reels clip with realistic phone-native motion and no audio. "
        f"Frame-0 blueprint to preserve: {first_frame or 'preserve the generated first-frame composition exactly'}. "
        f"Subject motion: {directives['subject_motion']}. "
        f"Camera motion: {directives['camera_motion']}. "
        f"Duration: {directives['duration_seconds']} seconds. "
        f"Must preserve: {must_preserve}. "
        f"Avoid: {avoid}."
    )


def _motion_directives(
    analysis: dict[str, Any], *, fallback_motion: str = ""
) -> dict[str, Any]:
    first = _blueprint_first_frame(analysis)
    beats = _blueprint_motion_beats(analysis)
    first_beat = beats[0] if beats and isinstance(beats[0], dict) else {}
    subject_motion = (
        fallback_motion
        or _clean_prompt_text(first_beat.get("subject_motion"))
        or _blueprint_motion_text(analysis)
        or "subtle natural body movement and relaxed breathing"
    )
    camera_motion = (
        _clean_prompt_text(first_beat.get("camera_motion"))
        or "tiny handheld phone sway, no zoom, no cinematic pan"
    )
    preserve = [
        "same first-frame crop",
        "same pose geometry",
        "same outfit continuity",
        "same room/background layout",
        "same phone/camera placement",
        "same lighting",
    ]
    if first.get("phone_or_hand_position"):
        preserve.append(f"phone/hand placement: {first['phone_or_hand_position']}")
    if first.get("facial_visibility"):
        preserve.append(f"facial visibility: {first['facial_visibility']}")
    return {
        "duration_seconds": 5,
        "camera_motion": camera_motion,
        "subject_motion": subject_motion,
        "must_preserve": preserve,
        "avoid": [
            "zoom",
            "cinematic camera move",
            "face reveal",
            "outfit change",
            "room change",
            "platform UI",
            "username",
            "watermark",
        ],
        "fallback_provider": "grok_imagine",
    }


def _higgsfield_prompt(
    job: dict[str, Any], analysis: dict[str, Any], model_profile: str | None
) -> dict[str, Any]:
    subject = analysis.get("subject") or {}
    setting = analysis.get("setting") or {}
    camera = analysis.get("camera") or {}
    card = _winning_format_card(analysis, job)
    pattern = (
        analysis.get("patternCard")
        if isinstance(analysis.get("patternCard"), dict)
        else _pattern_card_from_analysis(job, analysis)
    )
    pattern_id = str(
        pattern.get("id")
        or stable_id(
            "viral_pattern_card", job.get("reference_id"), card.get("visualFormat")
        )
    )
    pacing = analysis.get("visualPacing") or card.get("pacing") or {}
    text_overlay = analysis.get("textOverlay") or {}
    fallback_prompt = (
        f"Create a high-quality first-frame image for an Instagram Reel in the {card.get('visualFormat', analysis.get('contentFormat', 'selfie_video'))} format. "
        f"The Soul ID model {subject.get('action') or card.get('poseAction') or 'poses naturally'} in {setting.get('location') or card.get('setting') or 'a clean lifestyle setting'}, "
        f"wearing {subject.get('wardrobe') or card.get('styling') or 'model-appropriate styling'}, with {setting.get('lighting') or card.get('lighting') or 'soft flattering lighting'}. "
        f"Keep the winning format close, but make the scene original: new wardrobe, new room/details, new pose micro-variation, and no copied identity."
    )
    return {
        "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
        "tool": "higgsfield_soul_image",
        "status": PROMPT_READY_STATUS,
        "promptSource": "gemini_import"
        if _analysis_value(analysis, "higgsfield_soul_image_prompt")
        else "heuristic",
        "sourceReferenceId": job.get("reference_id"),
        "sourcePatternId": pattern_id,
        "modelProfile": model_profile,
        "intakeProfile": DEFAULT_INTAKE_PROFILE,
        "closenessControls": dict(IG_OFM_CLOSENESS_CONTROLS),
        "formatCard": card,
        "soulIdInstruction": "Replace the source identity. Do not copy face, username, watermark, or distinctive personal likeness.",
        "mainPrompt": _compose_higgsfield_main_prompt(
            analysis_prompt=_analysis_value(analysis, "higgsfield_soul_image_prompt"),
            analysis=analysis,
            model_profile=model_profile,
            fallback_prompt=fallback_prompt,
        ),
        "imagePromptJson": _build_image_prompt_json_from_analysis(
            analysis, model_profile=model_profile
        ),
        "cameraPrompt": f"{camera.get('framing', 'vertical 9:16 close framing')}; {camera.get('angle', 'phone-style angle')}; {camera.get('movement', 'subtle natural motion')}.",
        "motionPrompt": f"{subject.get('pose', 'confident casual pose')}; expression: {subject.get('expression', 'soft confident')}; pacing: {pacing.get('cutRhythm', 'short-form native rhythm')}.",
        "lightingPrompt": f"{setting.get('lighting', 'soft flattering light')}; background: {setting.get('background', 'clean lifestyle background')}.",
        "captionDirection": f"{analysis.get('captionStyle', 'short high-contrast overlay')}; placement: {text_overlay.get('placement', 'safe top or lower third')}.",
        "audioDirection": "Recommend native platform audio separately; do not burn trending/licensed audio into the generated file.",
        "negativePrompt": _analysis_value(analysis, "higgsfield_negative_prompt")
        or "copied face, copied identity, watermark, username, platform UI, unreadable text, broken anatomy, underage appearance, explicit nudity, low resolution",
        "recreationBlueprint": _recreation_blueprint(analysis),
        "aspectRatio": "9:16",
        "durationSeconds": 6,
        "styleTags": _style_tags(analysis),
        "operatorNotes": analysis.get("transformationNotes")
        or (
            [_analysis_value(analysis, "what_to_change")]
            if _analysis_value(analysis, "what_to_change")
            else []
        ),
        "reviewNotes": card.get("copyRiskNotes")
        or (
            [_analysis_value(analysis, "copy_risk_notes")]
            if _analysis_value(analysis, "copy_risk_notes")
            else []
        ),
    }


def _kling_prompt(
    job: dict[str, Any], analysis: dict[str, Any], model_profile: str | None
) -> dict[str, Any]:
    subject = analysis.get("subject") or {}
    setting = analysis.get("setting") or {}
    camera = analysis.get("camera") or {}
    card = _winning_format_card(analysis, job)
    pattern = (
        analysis.get("patternCard")
        if isinstance(analysis.get("patternCard"), dict)
        else _pattern_card_from_analysis(job, analysis)
    )
    pattern_id = str(
        pattern.get("id")
        or stable_id(
            "viral_pattern_card", job.get("reference_id"), card.get("visualFormat")
        )
    )
    pacing = analysis.get("visualPacing") or card.get("pacing") or {}
    fallback_prompt = (
        f"Original vertical Instagram Reels style video, {card.get('visualFormat', analysis.get('contentFormat', 'creator reference'))} format, "
        f"fictional creator/model, {subject.get('wardrobe', 'stylish casual wardrobe')}, "
        f"{subject.get('action', 'natural pose and subtle movement')} in {setting.get('location', 'a lifestyle setting')}. "
        f"Mood: {analysis.get('summary', 'viral short-form visual pattern')}. Copy the format closely, but avoid copying the source identity, exact scene, text, or watermark."
    )
    return {
        "schema": "reference_factory.kling_3_video_prompt.v1",
        "tool": "kling_3_video",
        "status": PROMPT_READY_STATUS,
        "promptSource": "gemini_import"
        if _analysis_value(analysis, "kling_3_video_prompt")
        else "heuristic",
        "sourceReferenceId": job.get("reference_id"),
        "sourcePatternId": pattern_id,
        "modelProfile": model_profile,
        "intakeProfile": DEFAULT_INTAKE_PROFILE,
        "closenessControls": dict(IG_OFM_CLOSENESS_CONTROLS),
        "formatCard": card,
        "firstFrameInstruction": "Use the generated Higgsfield image as the first/reference frame. Preserve that image, not the reference creator.",
        "mainPrompt": _compose_kling_main_prompt(
            analysis_prompt=_analysis_value(analysis, "kling_3_video_prompt"),
            analysis=analysis,
            model_profile=model_profile,
            fallback_prompt=fallback_prompt,
        ),
        "camera": {
            "framing": camera.get("framing", "vertical 9:16"),
            "angle": camera.get("angle", "phone-style angle"),
            "movement": camera.get("movement", "subtle handheld movement"),
        },
        "motion": {
            "subject": subject.get("pose", "confident natural pose"),
            "expression": subject.get("expression", "soft confident expression"),
            "pacing": pacing.get("cutRhythm", "short-form native rhythm"),
        },
        "motion_directives": _motion_directives(
            analysis,
            fallback_motion=_analysis_value(analysis, "kling_3_video_prompt")
            or fallback_prompt,
        ),
        "lighting": setting.get("lighting", "soft flattering lighting"),
        "negativePrompt": _analysis_value(analysis, "kling_negative_prompt")
        or "watermark, username, exact likeness, copied person, distorted hands, distorted face, bad text, extra limbs, low quality, platform UI",
        "aspectRatio": "9:16",
        "durationSeconds": 5,
        "scenes": _kling_scenes(analysis, card),
        "recreationBlueprint": _recreation_blueprint(analysis),
        "styleTags": _style_tags(analysis),
        "nativeAudioPlan": analysis.get("audioVibe") or {},
        "reviewNotes": card.get("copyRiskNotes")
        or (
            [_analysis_value(analysis, "copy_risk_notes")]
            if _analysis_value(analysis, "copy_risk_notes")
            else []
        ),
    }


def _validate_prompt_contract(target_tool: str, prompt: dict[str, Any]) -> None:
    tool = _canonical_tool(target_tool)
    if tool == "higgsfield_soul_image":
        validate_higgsfield_soul_image_prompt(prompt)
        return
    if tool == "kling_3_video":
        validate_kling_3_video_prompt(prompt)


def _canonical_tool(target_tool: object) -> str:
    tool = _norm(target_tool)
    if tool in {"higgsfield", "higgsfield_soul", "higgsfield_soul_image", "soul_id"}:
        return "higgsfield_soul_image"
    if tool in {"kling", "kling_3", "kling_3_0", "kling_3_video"}:
        return "kling_3_video"
    return tool


def _closeness_controls(intake_profile: str | None) -> dict[str, Any]:
    if _norm(intake_profile) == DEFAULT_INTAKE_PROFILE:
        return dict(IG_OFM_CLOSENESS_CONTROLS)
    return {
        "format_closeness": "medium",
        "identity_copy_risk": "blocked",
        "scene_variation_required": True,
        "spicy_ofm_coded": False,
    }


def _classify_reference_format(
    source: dict[str, Any], analysis: dict[str, Any] | None = None
) -> str:
    analysis = analysis or {}
    explicit = _norm(
        analysis.get("contentFormat") or analysis.get("visualFormat") or ""
    )
    aliases = {
        "mirror": "mirror_selfie",
        "mirror_selfie": "mirror_selfie",
        "selfie": "selfie_video",
        "selfie_video": "selfie_video",
        "pov": "pov",
        "pov_style": "pov",
        "lifestyle": "spicy_lifestyle",
        "lifestyle_scene": "spicy_lifestyle",
        "travel": "spicy_lifestyle",
        "travel_scene": "spicy_lifestyle",
        "slide": "slideshow",
        "slides": "slideshow",
        "slideshow": "slideshow",
    }
    if explicit in aliases:
        return aliases[explicit]
    if explicit in FORMAT_PRIORITY:
        return explicit
    text = " ".join(
        str(value or "")
        for value in (
            source.get("file_name"),
            source.get("fileName"),
            source.get("account"),
            source.get("path"),
            analysis.get("summary"),
        )
    ).lower()
    if "mirror" in text:
        return "mirror_selfie"
    if "selfie" in text:
        return "selfie_video"
    if any(
        word in text for word in ("bedroom", "car", "lifestyle", "fit", "glam", "ofm")
    ):
        return "spicy_lifestyle"
    if "slide" in text or source.get("kind") == "image":
        return "slideshow"
    return "selfie_video" if source.get("kind") == "video" else "other"


def _winning_format_card(
    analysis: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    existing = (
        analysis.get("winningFormatCard")
        if isinstance(analysis.get("winningFormatCard"), dict)
        else {}
    )
    visual_format = _classify_reference_format(source, {**analysis, **existing})
    camera = (
        existing.get("camera")
        if isinstance(existing.get("camera"), dict)
        else analysis.get("camera") or {}
    )
    text_overlay = (
        existing.get("textOverlay")
        if isinstance(existing.get("textOverlay"), dict)
        else analysis.get("textOverlay") or {}
    )
    pacing = (
        existing.get("pacing")
        if isinstance(existing.get("pacing"), dict)
        else analysis.get("visualPacing") or {}
    )
    audio = (
        existing.get("audioVibe")
        if isinstance(existing.get("audioVibe"), dict)
        else analysis.get("audioVibe") or {}
    )
    subject = analysis.get("subject") or {}
    setting = analysis.get("setting") or {}
    priority_rank = (
        FORMAT_PRIORITY.index(visual_format) + 1
        if visual_format in FORMAT_PRIORITY
        else len(FORMAT_PRIORITY)
    )
    return {
        "visualFormat": visual_format,
        "formatPriorityRank": int(existing.get("formatPriorityRank") or priority_rank),
        "poseAction": existing.get("poseAction")
        or subject.get("action")
        or subject.get("pose")
        or "confident phone-native pose",
        "camera": camera
        or {"framing": "vertical 9:16", "angle": "phone-native", "movement": "subtle"},
        "lighting": existing.get("lighting")
        or setting.get("lighting")
        or "soft flattering light",
        "setting": existing.get("setting")
        or setting.get("location")
        or "creator-style lifestyle setting",
        "styling": existing.get("styling")
        or subject.get("wardrobe")
        or "model-appropriate spicy OFM-coded styling",
        "textOverlay": text_overlay
        or {
            "copy": "",
            "placement": "safe top or lower third",
            "fontStyle": "white text with dark stroke",
        },
        "pacing": pacing
        or {
            "energy": "medium",
            "cutRhythm": "single native shot",
            "durationFeel": "short reel",
        },
        "audioVibe": audio
        or {
            "energy": "medium",
            "bpmFeel": "current native sound",
            "moodTags": ["glam", "relationship"],
        },
        "hookMechanics": existing.get("hookMechanics")
        or analysis.get("viralMechanics")
        or [],
        "copyRiskNotes": existing.get("copyRiskNotes")
        or [
            "Do not copy face, username, exact overlay copy, watermark, or distinctive personal identity."
        ],
        "transformationInstructions": existing.get("transformationInstructions")
        or analysis.get("transformationNotes")
        or [
            "Keep the format and hook mechanics, but change the model identity, outfit, scene, overlay text, and audio choice."
        ],
    }


def _style_tags(analysis: dict[str, Any]) -> list[str]:
    tags = [
        str(analysis.get("platformStyle") or "short_form"),
        str(analysis.get("contentFormat") or "creator"),
        str(analysis.get("hookType") or "pov"),
    ]
    audio = analysis.get("audioVibe") or {}
    tags.extend(str(tag) for tag in audio.get("moodTags") or [])
    return sorted({tag for tag in (_norm(tag) for tag in tags) if tag})


def _job_payload(conn: Connection, job_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT raj.*, sf.path, sf.account, sf.file_name, sf.kind
        FROM reference_analysis_jobs raj
        JOIN source_files sf ON sf.reference_id = raj.reference_id
        WHERE raj.id = ?
        """,
        (job_id,),
    ).fetchone()
    return _job_row_to_export(dict(row)) if row else {}


def _job_row_to_export(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "referenceId": row["reference_id"],
        "status": row["status"],
        "providerTarget": row["provider_target"],
        "sourcePlatform": row["source_platform"],
        "accountProfile": row.get("account_profile"),
        "sourcePath": row.get("path"),
        "account": row.get("account"),
        "fileName": row.get("file_name"),
        "kind": row.get("kind"),
        "promptText": row.get("prompt_text"),
        "analysis": json_load(row.get("analysis_json"), {}),
    }


def _analysis_queue_markdown(jobs: list[dict[str, Any]]) -> str:
    lines = [
        "# Reference Analysis Queue",
        "",
        "Paste each source file into Gemini or another video-capable model with the prompt below.",
        "Store the returned JSON and import it with `reference_factory import-reference-analysis --input analysis.json`.",
        "",
    ]
    for index, job in enumerate(jobs, start=1):
        lines.extend(
            [
                f"## {index}. {job['fileName']}",
                f"- Job: `{job['id']}`",
                f"- Source: `{job['sourcePath']}`",
                f"- Status: `{job['status']}`",
                "",
                "```text",
                job["promptText"],
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _prompt_scoring_rubric_markdown() -> str:
    lines = [
        "# Gemini Prompt Scoring Rubric",
        "",
        "Score each criterion from 1-10 after generating the Higgsfield image and Kling video.",
        "",
    ]
    for item in GEMINI_PROMPT_SCORING_RUBRIC["criteria"]:
        lines.append(
            f"- **{item['label']}** (`{item['key']}`), weight {item['weight']}"
        )
    lines.extend(
        [
            "",
            "Common failure modes to tag:",
            "",
        ]
    )
    for failure in GEMINI_PROMPT_SCORING_RUBRIC["failureModes"]:
        lines.append(f"- `{failure}`")
    lines.extend(
        [
            "",
            "Overall rating guide: 9-10 means paste-ready and source-faithful; 7-8 means usable with edits; 5-6 means directionally useful but weak; below 5 should be regenerated.",
            "",
        ]
    )
    return "\n".join(lines)


def _video_prompts_markdown(prompts: list[dict[str, Any]]) -> str:
    lines = ["# Generated AI Video Prompt Drafts", ""]
    for index, item in enumerate(prompts, start=1):
        prompt = item.get("prompt") or {}
        main = prompt.get("mainPrompt") or ""
        lines.extend(
            [
                f"## {index}. {item['targetTool']} - {item['fileName']}",
                f"- Source: `{item['sourcePath']}`",
                f"- Status: `{item['status']}`",
                "",
                "```text",
                str(main),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _daily_prompt_review_markdown(prompts: list[dict[str, Any]]) -> str:
    grouped: dict[str, dict[str, Any]] = {}
    for item in prompts:
        prompt = item.get("prompt") or {}
        if prompt.get("promptSource") != "gemini_import":
            continue
        if not str(prompt.get("mainPrompt") or "").strip():
            continue
        ref = item["referenceId"]
        grouped.setdefault(
            ref,
            {
                "fileName": item["fileName"],
                "sourcePath": item["sourcePath"],
                "account": item.get("account"),
                "prompts": {},
            },
        )
        grouped[ref]["prompts"][item["targetTool"]] = prompt
    lines = [
        "# Daily Higgsfield + Kling Prompt Review",
        "",
        "Use this for the manual Gemini Pro -> Higgsfield Soul ID -> Kling 3.0 workflow.",
        "Identity copying is blocked; copy the winning format, not the person.",
        "",
        "Only actual Gemini-imported prompt pairs are shown here. Heuristic placeholders are hidden.",
        "",
    ]
    for index, bundle in enumerate(grouped.values(), start=1):
        image_prompt = bundle["prompts"].get("higgsfield_soul_image") or {}
        kling_prompt = bundle["prompts"].get("kling_3_video") or {}
        if not image_prompt or not kling_prompt:
            continue
        card = image_prompt.get("formatCard") or kling_prompt.get("formatCard") or {}
        lines.extend(
            [
                f"## {index}. {bundle['fileName']}",
                f"- Source: `{bundle['sourcePath']}`",
                f"- Account/folder: `{bundle.get('account') or 'unknown'}`",
                f"- Format: `{card.get('visualFormat', 'unknown')}`",
                f"- Status: `{image_prompt.get('status') or kling_prompt.get('status') or PROMPT_READY_STATUS}`",
                "",
                "### Higgsfield Soul ID Image Prompt",
                "```text",
                str(image_prompt.get("mainPrompt") or ""),
                "```",
                "",
                "### Kling 3.0 Video Prompt",
                "```text",
                str(kling_prompt.get("mainPrompt") or ""),
                "```",
                "",
                "### Copy-Risk Notes",
            ]
        )
        for note in card.get("copyRiskNotes") or ["Do not copy source identity."]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def _grok_reference_image(
    source: Path, *, frame_dir: Path, reference_id: str, ffmpeg: str
) -> Path:
    source = source.expanduser().resolve()
    suffix = source.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return source
    output = frame_dir / f"{reference_id}_grok_frame.jpg"
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "1",
            "-i",
            str(source),
            "-frames:v",
            "1",
            str(output),
        ],
        check=True,
    )
    return output


def _xai_chat_completion(
    *,
    api_key: str,
    model: str,
    prompt: str,
    image_path: Path,
    response_format: dict[str, Any] | None = None,
) -> str:
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{encoded}"},
                    },
                ],
            }
        ],
        "temperature": 0.2,
        "response_format": response_format or {"type": "json_object"},
    }
    request = urllib.request.Request(
        XAI_CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    data = urlopen_json_with_retry(request, timeout=120)
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise RuntimeError(f"xAI API response did not include choices: {data}")
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("xAI API response did not include text content")
    return content


def _grok_prompt_compiler_response_format() -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "soul_id_2x3_prompt": {"type": "string"},
            "single_panel_prompt": {"type": "string"},
            "kling_video_prompt": {"type": "string"},
            "kling_negative_prompt": {"type": "string"},
            "structured_breakdown": {
                "type": "object",
                "properties": {
                    "pose_lock": {"type": "string"},
                    "body_emphasis": {"type": "string"},
                    "outfit_variations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 6,
                    },
                    "motion_directives": {"type": "string"},
                    "key_constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 3,
                    },
                },
                "required": [
                    "pose_lock",
                    "body_emphasis",
                    "outfit_variations",
                    "motion_directives",
                    "key_constraints",
                ],
                "additionalProperties": False,
            },
            "notes": {"type": "string"},
            "confidence_score": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": [
            "soul_id_2x3_prompt",
            "single_panel_prompt",
            "kling_video_prompt",
            "kling_negative_prompt",
            "structured_breakdown",
            "confidence_score",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "grok_prompt_compiler_v1",
            "schema": schema,
            "strict": True,
        },
    }


def _grok_prompt_compiler_prompt(
    *,
    reference_id: str,
    image_prompt: dict[str, Any],
    video_prompt: dict[str, Any],
    instructions: str | None = None,
) -> str:
    good_example = {
        "soul_id_2x3_prompt": (
            "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring six variations of the exact same stunning woman with a perfect face "
            "and extreme hourglass figure as seen in the reference. She is posing seductively in a bright modern luxury "
            "living room with stone fireplace, in the exact same confident three-quarter mirror selfie pose: body angled to show her curves, "
            "one hand holding smartphone with pink nails up for the selfie, other hand behind her head, strong arched back, "
            "hips pushed out, looking back over her shoulder with a flirty expression. Strong sexual body emphasis in every panel: deep "
            "plunging cleavage with full pushed-up breasts straining tightly against the fabric, massive round plump juicy ass prominently "
            "displayed and emphasized by the arched pose, tiny cinched waist flaring into wide hips and thick thighs, skin-tight dress "
            "clinging desperately to every curve, visible glute definition and ass jiggle potential, dramatic S-curve posture. Outfit "
            "variations: 1. Bright turquoise blue strapless bodycon dress. 2. Pale icy blue strapless bodycon dress. 3. Crisp white "
            "strapless bodycon dress. 4. Off-white cream strapless bodycon dress. 5. Light grey strapless bodycon dress. 6. Slightly sheer "
            "white strapless bodycon dress. Soft natural daylight, photorealistic skin texture with natural sheen, realistic fabric stretch "
            "and cling, elegant luxury interior, consistent face, body, pose, and lighting across all six panels, no extra panels, vertical composition inside each panel, iPhone "
            "selfie aesthetic, high detail, sharp focus."
        ),
        "single_panel_prompt": (
            "Stunning voluptuous woman with extreme hourglass figure wearing a tight bright blue strapless bodycon "
            "maxi dress, taking a seductive mirror selfie in a luxury living room with stone fireplace. Exact reference pose: three-quarter "
            "view, strong arched back pushing out her massive round plump ass, hips cocked, one hand holding smartphone with pink nails, "
            "other hand behind head, looking back over shoulder with flirty confident expression. Intense body emphasis: deep plunging cleavage "
            "with full heavy breasts overflowing the top, tiny cinched waist, wide hips, thick juicy ass with pronounced round shape and "
            "glute definition, skin-tight fabric desperately hugging every curve. Soft natural daylight, photorealistic skin and fabric "
            "texture, realistic cling and stretch, vertical 9:16, iPhone quality, high detail."
        ),
        "kling_video_prompt": (
            "Stunning woman with extreme hourglass figure in a tight bright blue strapless bodycon maxi dress, "
            "taking a seductive mirror selfie. Start exactly from the reference image. Animate sensual, confident movement: slow rhythmic "
            "hip swaying and thrusting back to emphasize her massive round plump ass, visible glute movement under the tight fabric, strong "
            "arched back, natural bounce in her deep cleavage and full breasts, slow hand moving near her head, seductive head tilts and "
            "flirty expression changes. Realistic iPhone Reels vertical 9:16, subtle handheld camera sway, soft natural daylight, "
            "photorealistic skin and fabric movement. Duration: 5-6 seconds."
        ),
        "kling_negative_prompt": (
            "blurry, deformed, bad anatomy, flat chest, small breasts, flat ass, skinny body, loose clothing, baggy dress, different pose, "
            "outfit change within panel, low quality, text, watermark, cartoon, overexposed"
        ),
        "structured_breakdown": {
            "pose_lock": "three-quarter mirror selfie pose, phone raised with pink nails, other hand behind head, arched back, hips pushed out, looking back over shoulder",
            "body_emphasis": "deep cleavage, pushed-up full breasts, tiny cinched waist, wide hips, thick thighs, massive round plump ass, S-curve posture, skin-tight fabric cling",
            "outfit_variations": [
                "Bright turquoise blue strapless bodycon dress",
                "Pale icy blue strapless bodycon dress",
                "Crisp white strapless bodycon dress",
                "Off-white cream strapless bodycon dress",
                "Light grey strapless bodycon dress",
                "Slightly sheer white strapless bodycon dress",
            ],
            "motion_directives": "slow rhythmic hip sway, arched back, glute movement under tight fabric, natural breast bounce, hand near head, head tilts",
            "key_constraints": [
                "same pose",
                "same room lighting",
                "same phone selfie aesthetic",
                "one native 2x3 grid",
                "Kling animates one selected panel",
            ],
        },
        "confidence_score": 90,
        "notes": "Use the prose prompts directly; structured_breakdown is for validation and debugging.",
    }
    return (
        "You are the Grok Prompt Compiler for a premium short-form seductive content pipeline.\n\n"
        "Given a reference image, analyze it carefully and generate the highest quality prompts possible. "
        "Use the image as the source of truth. Optional structured analysis below is only supporting context and must not override what you see.\n\n"
        "Return ONLY a valid JSON object with this exact schema:\n"
        "{ soul_id_2x3_prompt, single_panel_prompt, kling_video_prompt, kling_negative_prompt, structured_breakdown, notes, confidence_score }\n\n"
        "Core Rules:\n"
        "- Stay very faithful to the reference pose, lighting, room, phone position, camera framing, and overall vibe.\n"
        "- Make it highly seductive: deep cleavage, pushed-up breasts, tiny cinched waist, wide hips, thick thighs, round plump juicy ass, S-curve posture, skin-tight fabric clinging to curves.\n"
        "- 2x3 prompt must be one native six-panel image: exactly three columns and two rows, no extra panels, with slight outfit variations in the same dress/outfit family.\n"
        "- Kling prompt must animate only the single best panel with sensual movement: hip sway, back arch, hand near head, fabric movement, natural bounce, subtle handheld phone motion.\n"
        "- Keep everything visually sexy and generation-friendly.\n"
        "- Clean, direct, high-signal prose. No meta language, no legacy junk, no JSON-as-prompt.\n"
        "- Do not mention app interfaces, screenshots, logos, platform UI, usernames, watermarks, or prompt-safety boilerplate in Soul ID prompts.\n"
        "- Do not mention hair, hair color, hairstyle, tattoos, or tattoo absence anywhere in the final prompts or structured_breakdown.\n"
        "- If the reference pose has a hand touching hair, describe it as hand near head or hand behind head.\n"
        "- Soul ID handles model identity; do not over-explain model selection.\n\n"
        "structured_breakdown rules:\n"
        "- pose_lock must describe the exact pose being preserved.\n"
        "- body_emphasis must summarize the body/curve language used.\n"
        "- outfit_variations must contain exactly 6 practical panel outfit descriptions for a 2x3 grid.\n"
        "- motion_directives must summarize the motion requested for Kling.\n"
        "- key_constraints must contain at least 3 must-keep elements.\n"
        "- confidence_score should be 0-100 based on prompt quality and reference clarity.\n\n"
        f"Extra user instructions: {instructions or 'Make it very sexy with strong ass and cleavage emphasis. Keep extremely close to the reference pose. Slightly more revealing variations.'}\n\n"
        "Example prompt style to imitate:\n"
        f"{json.dumps(good_example, indent=2, ensure_ascii=False)}\n\n"
        f"reference_id: {reference_id}\n"
        "optional_existing_structured_image_analysis:\n"
        f"{json.dumps(image_prompt, indent=2, ensure_ascii=False)}\n\n"
        "optional_existing_video_prompt_record:\n"
        f"{json.dumps(video_prompt, indent=2, ensure_ascii=False)}\n\n"
        "Return only valid JSON matching the requested schema."
    )


def _validate_compiled_prompt_set(compiled: dict[str, Any]) -> None:
    required = (
        "soul_id_2x3_prompt",
        "single_panel_prompt",
        "kling_video_prompt",
        "kling_negative_prompt",
    )
    missing = [
        key
        for key in required
        if not isinstance(compiled.get(key), str) or not compiled[key].strip()
    ]
    if missing:
        raise RuntimeError(
            f"Grok prompt compiler response missing required prompt fields: {', '.join(missing)}"
        )
    breakdown = compiled.get("structured_breakdown")
    if not isinstance(breakdown, dict):
        raise RuntimeError("Grok prompt compiler response missing structured_breakdown")
    breakdown_required = (
        "pose_lock",
        "body_emphasis",
        "outfit_variations",
        "motion_directives",
        "key_constraints",
    )
    breakdown_missing = [key for key in breakdown_required if not breakdown.get(key)]
    if breakdown_missing:
        raise RuntimeError(
            f"Grok prompt compiler structured_breakdown missing fields: {', '.join(breakdown_missing)}"
        )
    outfits = breakdown.get("outfit_variations")
    if (
        not isinstance(outfits, list)
        or len(outfits) != 6
        or not all(isinstance(item, str) and item.strip() for item in outfits)
    ):
        raise RuntimeError(
            "Grok prompt compiler structured_breakdown.outfit_variations must contain exactly 6 strings"
        )
    constraints = breakdown.get("key_constraints")
    if not isinstance(constraints, list) or len(constraints) < 3:
        raise RuntimeError(
            "Grok prompt compiler structured_breakdown.key_constraints must contain at least 3 items"
        )
    confidence = compiled.get("confidence_score")
    if not isinstance(confidence, int) or confidence < 70:
        raise RuntimeError(
            "Grok prompt compiler confidence_score must be an integer >= 70 before generation"
        )
    forbidden = ("platform ui", "screenshot", "username", "watermark", "tattoo", "hair")
    soul_text = (
        f"{compiled['soul_id_2x3_prompt']} "
        f"{compiled['single_panel_prompt']} "
        f"{compiled['kling_video_prompt']} "
        f"{json.dumps(compiled.get('structured_breakdown') or {}, ensure_ascii=False)}"
    ).lower()
    leaked = [term for term in forbidden if term in soul_text]
    if leaked:
        raise RuntimeError(
            f"Grok prompt compiler produced forbidden Soul prompt terms: {', '.join(leaked)}"
        )


def _normalize_compiled_prompt_set(compiled: dict[str, Any]) -> dict[str, Any]:
    """Post-process Grok output without changing creative intent."""
    prompt = compiled.get("soul_id_2x3_prompt")
    if isinstance(prompt, str):
        prompt = prompt.replace(
            "Create one high-quality 2x3 grid featuring",
            "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring",
        )
        prompt = prompt.replace(
            "Create one high-quality 2x3 grid image featuring",
            "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring",
        )
        if "exactly three columns and two rows" not in prompt:
            prompt = (
                "Create one high-quality six-panel grid image, exactly three columns and two rows, no extra panels. "
                + prompt
            )
        if "no extra panels" not in prompt.lower():
            prompt += " No extra panels."
        compiled["soul_id_2x3_prompt"] = prompt
    return compiled


def _grok_prompt_builder(job: dict[str, Any], *, prompt_style: str = "imageat") -> str:
    file_name = str(job.get("fileName") or job.get("file_name") or "")
    reference_id = str(job.get("referenceId") or job.get("reference_id") or "")
    example = {
        "schema": ANALYSIS_SCHEMA,
        "referenceId": reference_id or "example_reference.mp4",
        "summary": "A mirror selfie video of a woman posing in a bright minimalist bedroom.",
        "contentFormat": "mirror_selfie",
        "image_prompt_json": {
            "promptMode": "structured_json",
            "subject": "Stunning young woman with an alluring, seductive figure taking a confident mirror selfie in a bright minimalist bedroom.",
            "composition": {
                "shot_type": "Full-body mirror selfie",
                "angle": "Side profile with slight twist toward the mirror, emphasizing curves",
                "pose": "Standing with arched back and pushed-out hips to accentuate her round butt and hourglass silhouette. Right hand holding white iPhone up covering most of her face, left arm slightly extended behind her. Seductive and teasing body language.",
            },
            "hair": {
                "style": "Long, voluminous, wild tight curls",
                "color": "Rich honey brown with golden highlights",
                "texture": "Thick, bouncy coiled ringlets cascading down her back and over one shoulder, with natural movement and volume.",
            },
            "clothing": {
                "item": "Extremely short, sheer strapless mini dress",
                "pattern": "Leopard print with brown and black rosettes on semi-transparent fabric",
                "fit": "Skin-tight, bodycon, stretchy sheer material that clings to every curve, barely covering her ass, with visible skin tone underneath. Deep plunging back and sides, strapless neckline pushing up her cleavage.",
            },
            "body": {
                "build": "Slim-thick, toned yet curvaceous figure with pronounced hips, round perky butt, and long smooth legs",
                "pose_details": "Weight shifted to one leg, creating a strong S-curve posture that highlights her waist-to-hip ratio and buttocks.",
            },
            "skin": {
                "tone": "Fair with warm golden undertones",
                "texture": "Smooth, soft, and glowing with natural sheen. Subtle muscle definition on legs and arms.",
            },
            "expression_mood": {
                "vibe": "Playful yet highly seductive and confident",
                "details": "Teasing body language, sensual posture designed to highlight her sexuality and feminine curves.",
            },
            "environment": {
                "setting": "Bright, clean minimalist bedroom",
                "details": [
                    "White tufted headboard bed with messy striped sheets",
                    "Fluffy white shag rug",
                    "White vintage-style radiator",
                    "Plain white walls with subtle texture",
                    "Black vertical mirror frame visible on the right",
                ],
            },
            "lighting_and_camera": {
                "lighting": "Soft, bright natural daylight from the side creating gentle highlights on her skin, legs, and curves with subtle shadows that accentuate her body shape.",
                "camera_feel": "Casual smartphone mirror selfie aesthetic, vertical composition, realistic phone photography style with slight grain.",
            },
            "constraints": {
                "must_keep": [
                    "Leopard print sheer strapless mini dress",
                    "Long voluminous curly hair",
                    "Mirror selfie pose with white iPhone covering face",
                    "Side profile body emphasis",
                    "Minimalist white bedroom setting",
                ],
                "avoid": [
                    "Visible face",
                    "Loose clothing",
                    "Professional studio lighting",
                    "Heavy makeup",
                    "Cluttered background",
                    "Conservative pose",
                ],
            },
            "negative_prompt": "blurry, low quality, deformed body, bad anatomy, extra limbs, face visible, modest clothing, baggy dress, dark lighting, professional photoshoot, text, watermark, oversaturated, cartoonish.",
        },
        "higgsfield_soul_image_prompt": "Use this structured JSON creative brief exactly as the image prompt.",
        "higgsfield_negative_prompt": "Use image_prompt_json.negative_prompt.",
        "kling_3_video_prompt": "Use the generated image as the first frame. Create a realistic 5-second iPhone mirror selfie video. Keep the same pose, outfit, mirror angle, room lighting, and phone position. Add only subtle body movement, relaxed breathing, tiny phone sway, and a small pose adjustment. 9:16, no audio.",
        "kling_negative_prompt": "warped phone, extra limbs, distorted face, glitchy motion, changing outfit, changing room, cinematic camera move",
        "motion_notes": "Subtle pose-check motion, tiny phone sway, relaxed breathing, small hip/shoulder adjustment.",
        "camera_notes": "Vertical phone mirror selfie, mostly steady, same camera distance and angle.",
        "style_notes": "Casual bedroom mirror selfie, flirty fitted outfit, realistic phone-photo texture.",
        "copy_risk_notes": "Do not copy username, watermark, exact overlay text, or the source person's identity.",
        "what_to_change": "Replace the person with the selected model identity while preserving the winning pose, fit, camera, room, and movement format.",
    }
    return (
        "Analyze the provided reference image/frame and output ONLY valid JSON.\n"
        "Use the example JSON structure and style below. Match its level of detail and its field names.\n"
        "The output must be practical for Higgsfield Soul ID image generation and Kling 3.0 image-to-video.\n\n"
        "Important output rules:\n"
        "- Write an ImageAt-style `image_prompt_json` with strong composition, clothing fit, body pose, environment, lighting, and camera details.\n"
        "- Keep the image prompt spicy, flirty, fitted, and close to the source format while staying non-explicit.\n"
        "- Do not add generic safety boilerplate.\n"
        "- Do not flatten the image JSON into a weak paragraph.\n"
        "- The Kling prompt should describe motion only: body movement, phone/camera movement, pacing, duration, and what stays consistent.\n"
        "- Do not copy usernames, watermarks, exact overlay text, or the source person's identity.\n"
        f"- referenceId must be `{reference_id}`.\n"
        f"- Source file name: `{file_name}`.\n\n"
        "Example format to imitate:\n"
        f"{json.dumps(example, indent=2, ensure_ascii=False)}\n\n"
        "Now output the same JSON shape for the provided reference frame."
    )


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", "_").split())
