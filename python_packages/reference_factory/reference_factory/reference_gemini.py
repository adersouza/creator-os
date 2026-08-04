from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .prompt_registry import bind_reference_prompt
from .reference_analysis import _json_from_model_text
from .reference_grok import (
    _authorize_paid_action,
    _execute_paid_action,
    _require_paid_action_callbacks,
    _sha256_file,
)
from .reference_intake import import_reference_analysis, queue_reference_analysis
from .reference_intake_contracts import DEFAULT_INTAKE_PROFILE
from .reference_lifecycle import require_reference_provider_rights
from .reference_prompt_generation import (
    generate_video_prompts,
    require_creation_enabled_model_profile,
)


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
    generation_model_profile = (
        require_creation_enabled_model_profile(model_profile)
        if generate_prompts_after_import
        else None
    )
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
            model_profile=generation_model_profile,
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
    paid_action_authorizer: Callable[..., Mapping[str, Any]] | None = None,
    paid_action_reconciler: Callable[..., Mapping[str, Any]] | None = None,
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
    _require_paid_action_callbacks(
        paid_action_authorizer,
        paid_action_reconciler,
    )
    generation_model_profile = require_creation_enabled_model_profile(account_profile)

    queued = queue_reference_analysis(
        conn,
        source_root,
        data_root=data_root,
        platform=platform,
        provider_target="gemini_api",
        account_profile=generation_model_profile,
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
    queued_jobs = queued.get("jobs")
    for job in queued_jobs if isinstance(queued_jobs, list) else []:
        try:
            path = Path(str(job.get("sourcePath") or "")).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"source file missing: {path}")
            source_sha256 = _sha256_file(path)
            rights = require_reference_provider_rights(
                conn,
                reference_id=str(job["referenceId"]),
                provider="gemini",
                operation="reference_analysis",
                expected_source_sha256=source_sha256,
            )
            prompt = str(job.get("promptText") or "")
            prompt_inputs = {
                "analysisJobId": job["id"],
                "referenceId": job["referenceId"],
                "sourcePath": str(path),
                "sourceSha256": source_sha256,
                "promptStyle": prompt_style,
                "rightsEvidenceFingerprint": rights["rightsEvidenceFingerprint"],
            }
            prompt_governance = bind_reference_prompt(
                prompt_id="reference.gemini_analysis",
                version="1",
                provider="gemini",
                model=model,
                compiled_prompt=prompt,
                inputs=prompt_inputs,
            )
            paid_action = _authorize_paid_action(
                paid_action_authorizer,
                provider="gemini",
                model=model,
                action_type="reference_analysis",
                request_fingerprint=str(prompt_governance["receiptFingerprint"]),
                prompt_governance=prompt_governance,
                compiled_prompt=prompt,
                prompt_inputs=prompt_inputs,
            )

            def call_provider() -> dict[str, Any]:
                with tempfile.TemporaryDirectory(
                    prefix="creator-os-gemini-reference-"
                ) as raw_tmp:
                    snapshot = Path(raw_tmp) / f"source{path.suffix}"
                    _snapshot_exact_file(
                        path,
                        destination=snapshot,
                        expected_sha256=source_sha256,
                    )
                    current_rights = require_reference_provider_rights(
                        conn,
                        reference_id=str(job["referenceId"]),
                        provider="gemini",
                        operation="reference_analysis",
                        expected_source_sha256=source_sha256,
                    )
                    if (
                        current_rights["rightsEvidenceFingerprint"]
                        != rights["rightsEvidenceFingerprint"]
                    ):
                        raise PermissionError(
                            "reference_rights_changed_after_authorization"
                        )
                    uploaded = client.files.upload(file=str(snapshot))
                    uploaded = _wait_for_gemini_file(client, uploaded)
                    response = client.models.generate_content(
                        model=model,
                        contents=[uploaded, prompt],
                    )
                return _gemini_provider_response(response)

            response_text, paid_action_reconciliation, provider_evidence = (
                _execute_paid_action(
                    paid_action=paid_action,
                    reconciler=paid_action_reconciler,
                    external_call=call_provider,
                )
            )
            analysis = _json_from_model_text(response_text)
            analysis["analysisJobId"] = job["id"]
            analysis["referenceId"] = job["referenceId"]
            analysis["promptGovernance"] = prompt_governance
            analysis["paidAction"] = paid_action
            analysis["paidActionReconciliation"] = paid_action_reconciliation
            analysis["providerResponseEvidence"] = provider_evidence
            analysis["providerRights"] = rights
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
            model_profile=generation_model_profile,
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


def _snapshot_exact_file(
    source: Path,
    *,
    destination: Path,
    expected_sha256: str,
) -> Path:
    digest = hashlib.sha256()
    with source.open("rb") as source_handle, destination.open("xb") as output:
        for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise PermissionError("reference_provider_media_sha256_mismatch")
    return destination


def _gemini_provider_response(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if usage is not None and hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif not isinstance(usage, Mapping):
        usage = None
    cost = getattr(response, "cost", None)
    return {
        "content": str(getattr(response, "text", "") or ""),
        "providerReference": str(
            getattr(response, "response_id", None)
            or getattr(response, "id", None)
            or ""
        ).strip()
        or None,
        "usage": dict(usage) if isinstance(usage, Mapping) else None,
        "actualUsd": cost,
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
