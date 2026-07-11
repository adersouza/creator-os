from __future__ import annotations

import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..contentforge_cli import run_contentforge
from ..core import CampaignFactory, new_id, utc_now

SUPPORTED_EXTS = {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png"}
DEFAULT_LAYERS = [
    "pdq",
    "sscd",
    "audio",
    "forensics",
    "compression",
    "provenance",
    "temporal",
    "ssim",
]
DEFAULT_AUDIT_PROFILE = "campaign_factory_v1"


def audit_campaign(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    min_score: int = 85,
    contentforge_base_url: str | None = None,
    layers: list[str] | None = None,
) -> dict[str, Any]:
    campaign = factory.campaign_by_slug(campaign_slug)
    pipeline_job = factory.create_pipeline_job(
        "contentforge_audit",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "minScore": min_score,
            "contentforgeBaseUrl": contentforge_base_url
            or factory.settings.contentforge_base_url,
            "layers": layers or DEFAULT_LAYERS,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    try:
        rendered = factory.rendered_for_campaign(campaign["id"])
        reference_pattern = factory.active_reference_pattern_for_campaign(
            campaign["id"]
        )
        reference_paths = _existing_reference_paths(reference_pattern)
        audit_layers = layers or DEFAULT_LAYERS
        if reference_paths and "originality" not in audit_layers:
            audit_layers = [*audit_layers, "originality"]
        reports = []
        for asset in rendered:
            factory.record_event(
                "contentforge_audit_started",
                campaign_id=campaign["id"],
                source_asset_id=asset["source_asset_id"],
                rendered_asset_id=asset["id"],
                pipeline_job_id=pipeline_job["id"],
                status="info",
                message=f"Started ContentForge audit: {asset['filename']}",
                metadata={
                    "filename": asset["filename"],
                    "contentforgeBaseUrl": contentforge_base_url
                    or factory.settings.contentforge_base_url,
                },
                commit=False,
            )
            report = _audit_asset(
                factory,
                campaign=campaign,
                dirs=dirs,
                asset=asset,
                min_score=min_score,
                contentforge_base_url=contentforge_base_url
                or factory.settings.contentforge_base_url,
                layers=audit_layers,
                reference_pattern=reference_pattern,
                reference_paths=reference_paths,
            )
            reports.append(report)
            failed = report.get("failedChecks") or []
            warnings = report.get("warnings") or []
            failed_event = bool(report.get("error")) or "contentforge_cli" in failed
            factory.record_event(
                "contentforge_audit_failed"
                if failed_event
                else "contentforge_audit_completed",
                campaign_id=campaign["id"],
                source_asset_id=asset["source_asset_id"],
                rendered_asset_id=asset["id"],
                audit_report_id=report.get("auditReportId"),
                pipeline_job_id=pipeline_job["id"],
                status="failure"
                if failed_event
                else (
                    "warning"
                    if failed or warnings or report.get("overallVerdict") == "warn"
                    else "success"
                ),
                message=f"ContentForge audit {'failed' if failed_event else 'completed'}: {asset['filename']}",
                metadata={
                    "auditReportId": report.get("auditReportId"),
                    "overallVerdict": report.get("overallVerdict"),
                    "score": report.get("score"),
                    "status": report.get("status"),
                    "failedChecks": failed,
                    "warnings": warnings,
                    "reportPath": report.get("reportPath"),
                    "error": report.get("error"),
                },
                commit=False,
            )
        factory.conn.commit()
        result = {
            "campaign": campaign,
            "reports": reports,
            "pipelineJobId": pipeline_job["id"],
        }
        factory.finish_pipeline_job(
            pipeline_job["id"],
            {
                "reportCount": len(reports),
                "failedCount": sum(
                    1
                    for report in reports
                    if report.get("error")
                    or "contentforge_cli" in (report.get("failedChecks") or [])
                ),
                "warningCount": sum(
                    1
                    for report in reports
                    if report.get("warnings") or report.get("overallVerdict") == "warn"
                ),
            },
        )
        return result
    except Exception as exc:
        factory.record_event(
            "contentforge_audit_failed",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"ContentForge audit failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def audit_variation_batch(
    *,
    contentforge_root: Path,
    source_path: Path,
    variant_paths: list[Path],
    contentforge_base_url: str,
    report_path: Path,
) -> dict[str, Any]:
    if len(variant_paths) < 1:
        raise ValueError("variation batch requires at least one variant")
    with _stage_contentforge_variation_batch(
        contentforge_root,
        source_path,
        variant_paths,
    ) as (staged_source, staged_variants):
        response = _post_similarity(
            contentforge_root,
            source=staged_source.name,
            target_file=staged_variants[0].name,
            comparison_files=[path.name for path in staged_variants[1:]],
            audit_profile=DEFAULT_AUDIT_PROFILE,
            layers=["pdq", "sscd"],
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        **response,
        "schema": "campaign_factory.variation_perceptual_audit.v1",
        "sourceFile": str(source_path),
        "variantFiles": [str(path) for path in variant_paths],
        "reportPath": str(report_path),
        "createdAt": utc_now(),
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def audit_review_batch_manifest(
    *,
    contentforge_root: Path,
    manifest_path: Path,
    source_path: Path,
    contentforge_base_url: str,
    report_path: Path | None = None,
    layers: list[str] | None = None,
    animation_mode: str | None = None,
    allow_static_opening: bool = False,
    update_manifest: bool = True,
    per_file: bool = True,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    source_path = Path(source_path).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("review batch manifest must be a JSON object")
    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    variant_paths: list[Path] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("output"):
            continue
        output = Path(str(row["output"]))
        if not output.is_absolute():
            output = manifest_path.parent / output
        variant_paths.append(output.expanduser().resolve())
    if not variant_paths:
        raise ValueError("review batch manifest has no output rows to audit")

    report_path = (
        (
            report_path
            or manifest_path.with_name(f"{manifest_path.stem}.contentforge_audit.json")
        )
        .expanduser()
        .resolve()
    )
    file_results: list[dict[str, Any]] = []
    with _stage_contentforge_variation_batch(
        contentforge_root, source_path, variant_paths
    ) as (staged_source, staged_variants):
        response = _post_similarity(
            contentforge_root,
            source=staged_source.name,
            target_file=staged_variants[0].name,
            comparison_files=[path.name for path in staged_variants[1:]],
            audit_profile=DEFAULT_AUDIT_PROFILE,
            layers=layers or ["pdq", "sscd", "forensics"],
            animation_mode=animation_mode,
            allow_static_opening=allow_static_opening,
        )
        if per_file:
            for original_path, staged_path in zip(
                variant_paths, staged_variants, strict=True
            ):
                try:
                    file_response = _post_similarity(
                        contentforge_root,
                        source=staged_source.name,
                        target_file=staged_path.name,
                        comparison_files=[],
                        audit_profile=DEFAULT_AUDIT_PROFILE,
                        layers=layers or ["pdq", "sscd", "forensics"],
                        animation_mode=animation_mode,
                        allow_static_opening=allow_static_opening,
                    )
                    file_results.append(
                        _review_file_result(original_path, file_response)
                    )
                except Exception as exc:
                    file_results.append(
                        _missing_review_file_result(original_path, str(exc))
                    )

    readiness = (
        response.get("readinessSummary")
        if isinstance(response.get("readinessSummary"), dict)
        else {}
    )
    blocking = (
        readiness.get("blockingCodes")
        or readiness.get("blockingReasons")
        or response.get("blockingCodes")
        or []
    )
    passed = not blocking and (
        response.get("overallVerdict") == "pass" or readiness.get("uploadReady") is True
    )
    report = {
        **response,
        "schema": "campaign_factory.review_batch_contentforge_audit.v1",
        "auditProfile": response.get("auditProfile") or DEFAULT_AUDIT_PROFILE,
        "variants": len(variant_paths),
        "httpOk": len(variant_paths),
        "verdictCounts": {
            "pass": len(variant_paths) if passed else 0,
            "fail": 0 if passed else len(variant_paths),
        },
        "sourceFile": str(source_path),
        "variantFiles": [str(path) for path in variant_paths],
        "animationMode": animation_mode,
        "allowStaticOpening": allow_static_opening,
        "reportPath": str(report_path),
        "createdAt": utc_now(),
    }
    if per_file:
        report["fileResults"] = file_results
        report["fileStatusCounts"] = _frequency(
            result.get("status") for result in file_results
        )
        report["fileOverallVerdictCounts"] = _frequency(
            result.get("overallVerdict") for result in file_results
        )
        report["warningCodeFrequency"] = _code_frequency(file_results, "warningCodes")
        report["blockingCodeFrequency"] = _code_frequency(file_results, "blockingCodes")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    if update_manifest:
        manifest["contentForgeAuditPath"] = str(report_path)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
    return report


def _review_file_result(output_path: Path, response: dict[str, Any]) -> dict[str, Any]:
    readiness = (
        response.get("readinessSummary")
        if isinstance(response.get("readinessSummary"), dict)
        else {}
    )
    warning_codes = _string_list(
        readiness.get("warningCodes") or response.get("warningCodes")
    )
    blocking_codes = _string_list(
        readiness.get("blockingCodes")
        or readiness.get("blockingReasons")
        or response.get("blockingCodes")
    )
    top_warnings = (
        readiness.get("topWarnings")
        if isinstance(readiness.get("topWarnings"), list)
        else []
    )
    overall = str(response.get("overallVerdict") or "fail")
    upload_ready = bool(readiness.get("uploadReady"))
    if blocking_codes or overall == "fail":
        status = "blocked"
    elif warning_codes or overall == "warn" or not upload_ready:
        status = "review"
    else:
        status = "ready"
    ocr = response.get("ocr") if isinstance(response.get("ocr"), dict) else {}
    timings = (
        response.get("timings") if isinstance(response.get("timings"), dict) else {}
    )
    return {
        "outputPath": str(output_path),
        "status": status,
        "overallVerdict": overall,
        "uploadReady": upload_ready,
        "recommendedAction": readiness.get("recommendedAction")
        or (
            "block"
            if status == "blocked"
            else "review"
            if status == "review"
            else "approve"
        ),
        "warningCodes": warning_codes,
        "blockingCodes": blocking_codes,
        "topWarnings": top_warnings,
        "safeZoneScore": response.get("safeZoneScore"),
        "readabilityScore": response.get("readabilityScore"),
        "hookVisibilityScore": response.get("hookVisibilityScore"),
        "ocr": {
            "available": ocr.get("available"),
            "engine": ocr.get("engine"),
            "fallbackUsed": ocr.get("fallbackUsed"),
            "avgConfidence": ocr.get("avgConfidence"),
            "sampleCount": ocr.get("sampleCount"),
            "frameSamples": ocr.get("results"),
        },
        "timings": timings,
    }


def _missing_review_file_result(output_path: Path, error: str) -> dict[str, Any]:
    return {
        "outputPath": str(output_path),
        "status": "blocked",
        "overallVerdict": "fail",
        "uploadReady": False,
        "recommendedAction": "block",
        "warningCodes": [],
        "blockingCodes": ["contentforge_cli"],
        "topWarnings": [
            {"code": "contentforge_cli", "severity": "block", "message": error}
        ],
        "safeZoneScore": None,
        "readabilityScore": None,
        "hookVisibilityScore": None,
        "ocr": {"available": False, "error": error},
        "timings": {},
        "error": error,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _frequency(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _code_frequency(results: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for code in result.get(key) or []:
            code_key = str(code)
            counts[code_key] = counts.get(code_key, 0) + 1
    return dict(sorted(counts.items()))


def _audit_asset(
    factory: CampaignFactory,
    *,
    campaign: dict[str, Any],
    dirs: dict[str, Path],
    asset: dict[str, Any],
    min_score: int,
    contentforge_base_url: str,
    layers: list[str],
    reference_pattern: dict[str, Any] | None = None,
    reference_paths: list[Path] | None = None,
) -> dict[str, Any]:
    media_path = Path(asset["campaign_path"])
    source_path = _source_path_for_asset(factory, asset)
    run_id = uuid.uuid4().hex[:8]
    failed: list[str] = []
    warnings: list[str] = []
    response: dict[str, Any] = {}
    error_message: str | None = None
    staged_name: str | None = None
    staged_source_name: str | None = None
    try:
        with _stage_contentforge_asset(
            factory.settings.contentforge_root,
            source_path,
            media_path,
            reference_paths or [],
        ) as (staged_source, staged_path, staged_references):
            staged_source_name = staged_source.name
            staged_name = staged_path.name
            post_kwargs = {
                "source": staged_source.name,
                "target_file": staged_path.name,
                "audit_profile": DEFAULT_AUDIT_PROFILE,
                "layers": layers,
            }
            if staged_references:
                post_kwargs["originality_reference_files"] = [
                    path.name for path in staged_references
                ]
            response = _post_similarity(
                factory.settings.contentforge_root, **post_kwargs
            )
        failed, warnings = _extract_checks(response)
        overall = response.get("overallVerdict")
        if overall not in {"pass", "warn", "fail"}:
            failed.append("contentforge_malformed_response")
            overall = "fail"
            response["overallVerdict"] = overall
    except Exception as exc:
        overall = "fail"
        error_message = str(exc)
        failed.append("contentforge_cli")
        warnings.append(f"contentforge_cli: {error_message}")
        response = {
            "error": error_message,
            "layers": {},
            "verdicts": {},
            "overallVerdict": overall,
            "filesAnalyzed": 0,
        }
    score = _score_from_verdict(response.get("overallVerdict"), min_score=min_score)
    status = (
        "approved_candidate"
        if response.get("overallVerdict") == "pass"
        and score >= min_score
        and not failed
        else "needs_review"
    )
    report = {
        "schema": "campaign_factory.contentforge_audit.v1",
        "contentForgeMode": "http_similarity",
        "contentForgeBaseUrl": contentforge_base_url,
        "contentForgeRunId": run_id,
        "auditProfile": response.get("auditProfile") or DEFAULT_AUDIT_PROFILE,
        "renderedAssetId": asset["id"],
        "sourceFile": str(source_path),
        "stagedSourceFile": staged_source_name,
        "file": str(media_path),
        "stagedFile": staged_name,
        "targetFile": response.get("targetFile") or staged_name,
        "score": score,
        "status": status,
        "overallVerdict": response.get("overallVerdict"),
        "filesAnalyzed": int(response.get("filesAnalyzed") or 0),
        "failedChecks": failed,
        "warnings": warnings,
        "error": error_message,
        "readinessSummary": response.get("readinessSummary"),
        "layers": response.get("layers") or {},
        "verdicts": response.get("verdicts") or {},
        "verdictCodes": response.get("verdictCodes") or {},
        "referencePattern": reference_pattern,
        "referenceMatch": response.get("referenceMatch")
        or response.get("multiAccountOriginalityAudit"),
        "createdAt": utc_now(),
    }
    report_path = dirs["audits"] / f"{asset['id']}_{run_id}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if status == "approved_candidate":
        approved_dest = dirs["approved"] / media_path.name
        if media_path.exists() and not approved_dest.exists():
            shutil.copy2(media_path, approved_dest)
    audit_id = new_id("audit")
    factory.conn.execute(
        """
        INSERT INTO audit_reports
        (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score, status,
         layers_json, verdicts_json, overall_verdict, files_analyzed, failed_checks_json, warnings_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            campaign["id"],
            asset["id"],
            run_id,
            str(report_path),
            score,
            status,
            json.dumps(report["layers"]),
            json.dumps(report["verdicts"]),
            report["overallVerdict"],
            report["filesAnalyzed"],
            json.dumps(failed),
            json.dumps(warnings),
            utc_now(),
        ),
    )
    audit_graph_id = factory.ensure_graph_node(
        "audit_report",
        local_table="audit_reports",
        local_id=audit_id,
        payload={
            "renderedAssetId": asset["id"],
            "contentForgeRunId": run_id,
            "overallVerdict": report.get("overallVerdict"),
            "status": status,
            "reportPath": str(report_path),
        },
    )
    factory.ensure_graph_edge(
        factory.graph_id_for(
            "rendered_assets", asset["id"], entity_type="rendered_asset"
        ),
        audit_graph_id,
        "rendered_asset_to_audit_report",
        evidence={
            "contentForgeRunId": run_id,
            "auditProfile": report.get("auditProfile"),
        },
    )
    factory.conn.execute(
        "UPDATE rendered_assets SET audit_status = ?, updated_at = ? WHERE id = ?",
        (status, utc_now(), asset["id"]),
    )
    report["auditReportId"] = audit_id
    report["reportPath"] = str(report_path)
    return report


def _source_path_for_asset(factory: CampaignFactory, asset: dict[str, Any]) -> Path:
    source = factory.conn.execute(
        "SELECT * FROM source_assets WHERE id = ?", (asset["source_asset_id"],)
    ).fetchone()
    if not source:
        raise ValueError(f"source asset not found: {asset['source_asset_id']}")
    path = Path(source["stored_path"])
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _existing_reference_paths(reference_pattern: dict[str, Any] | None) -> list[Path]:
    paths: list[Path] = []
    for value in (reference_pattern or {}).get("localPaths") or []:
        path = Path(str(value)).expanduser()
        if path.exists() and path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
            paths.append(path)
    return paths[:8]


@contextmanager
def _stage_contentforge_asset(
    contentforge_root: Path,
    source_path: Path,
    media_path: Path,
    reference_paths: list[Path] | None = None,
):
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if not media_path.exists():
        raise FileNotFoundError(media_path)
    uploads_dir = contentforge_root / "uploads"
    final_dir = contentforge_root / "output" / "final"
    backup_dir = (
        contentforge_root
        / "output"
        / f".campaign_factory_backup_{uuid.uuid4().hex[:8]}"
    )
    uploads_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    staged_source = (
        uploads_dir / f"campaign_factory_source_{token}{source_path.suffix.lower()}"
    )
    staged_path = (
        final_dir / f"campaign_factory_variant_{token}{media_path.suffix.lower()}"
    )
    staged_references: list[Path] = []
    moved: list[tuple[Path, Path]] = []
    try:
        for path in sorted(final_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
                backup_path = backup_dir / path.name
                shutil.move(str(path), str(backup_path))
                moved.append((path, backup_path))
        shutil.copy2(source_path, staged_source)
        shutil.copy2(media_path, staged_path)
        for idx, reference_path in enumerate(reference_paths or [], 1):
            if (
                not reference_path.exists()
                or reference_path.resolve() == media_path.resolve()
            ):
                continue
            staged_reference = (
                final_dir
                / f"campaign_factory_reference_{token}_{idx:02d}{reference_path.suffix.lower()}"
            )
            shutil.copy2(reference_path, staged_reference)
            staged_references.append(staged_reference)
        yield staged_source, staged_path, staged_references
    finally:
        try:
            for staged_reference in staged_references:
                if staged_reference.exists():
                    staged_reference.unlink()
            if staged_path.exists():
                staged_path.unlink()
            if staged_source.exists():
                staged_source.unlink()
        finally:
            for original, backup in reversed(moved):
                if backup.exists():
                    shutil.move(str(backup), str(original))
            try:
                backup_dir.rmdir()
            except OSError:
                pass


@contextmanager
def _stage_contentforge_variation_batch(
    contentforge_root: Path,
    source_path: Path,
    variant_paths: list[Path],
):
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if any(not path.exists() for path in variant_paths):
        missing = next(path for path in variant_paths if not path.exists())
        raise FileNotFoundError(missing)
    uploads_dir = contentforge_root / "uploads"
    final_dir = contentforge_root / "output" / "final"
    backup_dir = (
        contentforge_root
        / "output"
        / f".campaign_factory_backup_{uuid.uuid4().hex[:8]}"
    )
    uploads_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    staged_source = (
        uploads_dir / f"campaign_factory_source_{token}{source_path.suffix.lower()}"
    )
    staged_variants: list[Path] = []
    moved: list[tuple[Path, Path]] = []
    try:
        for path in sorted(final_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
                backup_path = backup_dir / path.name
                shutil.move(str(path), str(backup_path))
                moved.append((path, backup_path))
        shutil.copy2(source_path, staged_source)
        for index, variant_path in enumerate(variant_paths, 1):
            staged_variant = (
                final_dir
                / f"campaign_factory_variant_{token}_{index:03d}{variant_path.suffix.lower()}"
            )
            shutil.copy2(variant_path, staged_variant)
            staged_variants.append(staged_variant)
        yield staged_source, staged_variants
    finally:
        try:
            for staged_variant in staged_variants:
                staged_variant.unlink(missing_ok=True)
            staged_source.unlink(missing_ok=True)
        finally:
            for original, backup in reversed(moved):
                if backup.exists():
                    shutil.move(str(backup), str(original))
            try:
                backup_dir.rmdir()
            except OSError:
                pass


def _post_similarity(
    contentforge_root: Path | str,
    *,
    source: str,
    target_file: str | None = None,
    audit_profile: str = DEFAULT_AUDIT_PROFILE,
    layers: list[str],
    originality_reference_files: list[str] | None = None,
    comparison_files: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": source,
        "layers": layers,
        "auditProfile": audit_profile,
    }
    if target_file:
        payload["targetFile"] = target_file
    if originality_reference_files:
        payload["originalityReferenceFiles"] = originality_reference_files
    if comparison_files:
        payload["comparisonFiles"] = comparison_files
    return run_contentforge(contentforge_root, "similarity", payload, timeout=240)


def _extract_checks(response: dict[str, Any]) -> tuple[list[str], list[str]]:
    failed: list[str] = []
    warnings: list[str] = []
    readiness = response.get("readinessSummary") or {}
    blocking_codes: set[str] = set()
    if isinstance(readiness, dict):
        blocking_codes = {str(item) for item in readiness.get("blockingCodes") or []}
        failed.extend(sorted(blocking_codes))
        warnings.extend(str(item) for item in readiness.get("warningCodes") or [])
    verdicts = response.get("verdicts") or {}
    if isinstance(verdicts, dict):
        for name, verdict in verdicts.items():
            if verdict == "fail":
                if str(name) in blocking_codes or f"{name}_failed" in blocking_codes:
                    failed.append(str(name))
                else:
                    warnings.append(f"{name}_review")
            elif verdict == "warn":
                warnings.append(str(name))
    layers = response.get("layers") or {}
    if isinstance(layers, dict):
        for name, layer in layers.items():
            if isinstance(layer, dict) and layer.get("error"):
                warnings.append(f"{name}: {layer['error']}")
    return sorted(set(failed)), sorted(set(warnings))


def _score_from_verdict(verdict: Any, *, min_score: int) -> int:
    if verdict == "pass":
        return 100
    if verdict == "warn":
        return max(1, min_score - 1)
    return 0
