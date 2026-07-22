from __future__ import annotations

import json
import re
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from creator_os_core.fileops import atomic_write_text as _atomic_write_text

from .db import json_dump as _json_dump
from .db import json_load as _json_load
from .identity import stable_id as _stable_id
from .reference_analysis import (
    _normalize_analysis,
    _pattern_card_from_analysis,
    _store_pattern_and_analysis,
)
from .reference_intake_contracts import (
    ANALYSIS_SCHEMA,
    DEFAULT_INTAKE_PROFILE,
    FORMAT_PRIORITY,
    GEMINI_PROMPT_OUTPUT_SCHEMA,
    GEMINI_PROMPT_SCORING_RUBRIC,
    _closeness_controls,
    _norm,
)
from .reference_local_analysis import _local_video_analysis
from .reference_prompt_generation import (
    gemini_analysis_prompt as _gemini_analysis_prompt,
)
from .scan import scan_source as _scan_source
from .timeutil import now_iso as _now_iso

__all__ = [
    "analyze_reference_local",
    "export_analysis_queue",
    "export_video_analyses",
    "import_reference_analysis",
    "queue_reference_analysis",
]

_SAFE_FILENAME_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


def _safe_filename_token(value: object, *, field: str) -> str:
    token = _norm(value)
    if not _SAFE_FILENAME_TOKEN.fullmatch(token):
        raise ValueError(f"{field} must contain only letters, numbers, and underscores")
    return token


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
    scan = _scan_source(conn, source_root)
    timestamp = _now_iso()
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
        job_id = _stable_id(
            "reference_analysis_job",
            source["reference_id"],
            provider_target,
            profile_key,
        )
        prompt_text = _gemini_analysis_prompt(
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
    provider_key = _safe_filename_token(provider_target, field="provider_target")
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
        (provider_key, limit),
    ).fetchall()
    jobs = [_job_row_to_export(dict(row)) for row in rows]
    manifest = {
        "schema": "reference_factory.reference_analysis_queue.v1",
        "providerTarget": provider_key,
        "count": len(jobs),
        "jobs": jobs,
    }
    json_path = output_dir / f"{provider_key}_analysis_queue.json"
    jsonl_path = output_dir / f"{provider_key}_analysis_queue.jsonl"
    md_path = output_dir / f"{provider_key}_analysis_queue.md"
    schema_path = output_dir / f"{provider_key}_prompt_output_schema.json"
    rubric_path = output_dir / f"{provider_key}_prompt_scoring_rubric.json"
    rubric_md_path = output_dir / f"{provider_key}_prompt_scoring_rubric.md"
    _atomic_write_text(
        json_path,
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with jsonl_path.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job, ensure_ascii=False, sort_keys=True) + "\n")
    _atomic_write_text(md_path, _analysis_queue_markdown(jobs), encoding="utf-8")
    _atomic_write_text(
        schema_path,
        json.dumps(GEMINI_PROMPT_OUTPUT_SCHEMA, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _atomic_write_text(
        rubric_path,
        json.dumps(GEMINI_PROMPT_SCORING_RUBRIC, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _atomic_write_text(
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
    timestamp = _now_iso()
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
            (_json_dump(analysis), timestamp, job_id),
        )
        stored_analysis = {
            "schema": ANALYSIS_SCHEMA,
            "id": _stable_id(
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
    timestamp = _now_iso()
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
    provider_key = _safe_filename_token(provider, field="provider") if provider else ""
    output_dir = data_root / "reference_intake"
    output_dir.mkdir(parents=True, exist_ok=True)
    where = "WHERE rva.provider = ?" if provider else ""
    params: tuple[Any, ...] = ((provider_key,) if provider else ()) + (limit,)
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
        analysis = _json_load(item["analysis_json"], {})
        analysis.setdefault("sourcePath", item.get("path"))
        analysis.setdefault("fileName", item.get("file_name"))
        analysis.setdefault("account", item.get("account"))
        analyses.append(analysis)
    payload = {
        "schema": "reference_factory.video_analysis_export.v1",
        "count": len(analyses),
        "items": analyses,
    }
    suffix = f"_{provider_key}" if provider else ""
    path = output_dir / f"video_analyses{suffix}.json"
    _atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "schema": "reference_factory.export_video_analyses.v1",
        "count": len(analyses),
        "jsonPath": str(path),
    }


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
        "analysis": _json_load(row.get("analysis_json"), {}),
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
