from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .db import json_dump, json_load
from .identity import stable_id
from .reference_analysis import (
    _json_from_model_text,
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
from .reference_prompt_generation import gemini_analysis_prompt, generate_video_prompts
from .scan import scan_source
from .timeutil import now_iso


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
