from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import CREATOR_OS_ROOT, Settings


def _json_dict(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_manifest_path(package_path: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = package_path.parent / path
    return path.expanduser().resolve()


def _is_reel_review_manifest(path: Path) -> bool:
    payload = _json_dict(path)
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    if payload.get("schema") == "reel_factory.review_batch_package.v1":
        return False
    first = rows[0] if isinstance(rows[0], dict) else {}
    return bool(
        payload.get("outputDir")
        and payload.get("captionPlacementPolicy")
        and first.get("output")
        and first.get("overlayPng")
        and first.get("captionHash")
    )


def _is_guarded_review_package(path: Path) -> bool:
    payload = _json_dict(path)
    return payload.get("schema") == "reel_factory.review_batch_package.v1"


def _review_package_hash_paths(
    manifest_path: Path, manifest: dict[str, Any]
) -> list[Path]:
    paths: list[Path] = [manifest_path.resolve()]
    contentforge = manifest.get("contentForgeAuditPath")
    if contentforge:
        path = Path(str(contentforge))
        paths.append(
            (path if path.is_absolute() else manifest_path.parent / path)
            .expanduser()
            .resolve()
        )
    output_dir = (
        Path(str(manifest.get("outputDir") or manifest_path.parent))
        .expanduser()
        .resolve()
    )
    readiness = output_dir / "_readiness.json"
    if readiness.exists():
        paths.append(readiness)
    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field in ("output", "overlayPng"):
            value = row.get(field)
            if value:
                paths.append(_resolve_batch_path(manifest_path, value))
        output = row.get("output")
        if output:
            output_path = _resolve_batch_path(manifest_path, output)
            for sidecar in (
                output_path.with_name(output_path.name + ".audio_intent.json"),
                output_path.with_name(
                    output_path.name + ".generated_asset_lineage.json"
                ),
            ):
                if sidecar.exists():
                    paths.append(sidecar.resolve())
    return list(dict.fromkeys(paths))


def _resolve_batch_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.expanduser().resolve()


def _normalize_review_audio_intent(
    payload: dict[str, Any], *, platform: str, surface: str
) -> dict[str, Any]:
    intent = dict(payload) if isinstance(payload, dict) else {}
    status = str(intent.get("status") or "").strip().lower()
    allowed_statuses = {
        "not_required",
        "recommended",
        "needs_operator_selection",
        "selected",
        "attached",
        "verified",
        "skipped",
        "blocked",
        "needs_review",
        "burned",
    }
    required = bool(intent.get("required", True))
    if status not in allowed_statuses:
        status = "needs_operator_selection" if required else "not_required"

    recommendations = intent.get("recommendations")
    if not isinstance(recommendations, list):
        recommendations = []
    operator_selection = intent.get("operator_selection")
    if not isinstance(operator_selection, dict):
        operator_selection = {}
    gates = intent.get("gates")
    if not isinstance(gates, dict):
        gates = {}
    mode = str(intent.get("mode") or "native_platform_audio")
    normalized_gates = {
        "allow_draft_export": bool(gates.get("allow_draft_export", True)),
        "allow_preview_schedule": bool(gates.get("allow_preview_schedule", False)),
        "allow_live_schedule": bool(gates.get("allow_live_schedule", False)),
        "allow_publish": bool(gates.get("allow_publish", False)),
    }
    return {
        **intent,
        "schema": "pipeline.audio_intent.v1",
        "mode": mode,
        "required": required,
        "status": status,
        "platform": str(intent.get("platform") or platform),
        "surface": str(intent.get("surface") or surface),
        "recommendations": recommendations,
        "operator_selection": operator_selection,
        "gates": normalized_gates,
    }


class AssetImportRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        new_id: Callable[[str], str],
        slugify: Callable[[str], str],
        utc_now: Callable[[], str],
        media_type_for_path: Callable[[Any], str],
        sha256_file: Callable[[Path], str],
        upsert_model: Callable[..., dict[str, Any]],
        upsert_campaign: Callable[..., dict[str, Any]],
        upsert_account: Callable[..., dict[str, Any]],
        create_pipeline_job: Callable[..., dict[str, Any]],
        start_pipeline_job: Callable[..., dict[str, Any]],
        finish_pipeline_job: Callable[..., dict[str, Any]],
        fail_pipeline_job: Callable[..., dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        graph_id_for: Callable[..., str | None],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._new_id = new_id
        self._slugify = slugify
        self._utc_now = utc_now
        self._media_type_for_path = media_type_for_path
        self._sha256_file = sha256_file
        self._upsert_model = upsert_model
        self._upsert_campaign = upsert_campaign
        self._upsert_account = upsert_account
        self._create_pipeline_job = create_pipeline_job
        self._start_pipeline_job = start_pipeline_job
        self._finish_pipeline_job = finish_pipeline_job
        self._fail_pipeline_job = fail_pipeline_job
        self._record_event = record_event
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._graph_id_for = graph_id_for

    def _campaign_dirs(self, model_slug: str, campaign_slug: str) -> dict[str, Path]:
        root = self.settings.campaigns_dir / model_slug / campaign_slug
        dirs = {
            "root": root,
            "sources": root / "00_sources",
            "reel_inputs": root / "01_reel_inputs",
            "rendered": root / "02_rendered",
            "audits": root / "03_contentforge_audits",
            "approved": root / "04_approved",
            "exports": root / "05_threadsdash_exports",
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    def import_folder(
        self,
        folder: Path,
        *,
        campaign_slug: str,
        model_slug: str,
        model_name: str | None = None,
        platform: str = "instagram",
        account_handles: list[str] | None = None,
        source_prompt: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        folder = Path(folder).expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"input folder not found: {folder}")
        review_packages = self._enforce_reel_review_batch_package(folder)
        model = self._upsert_model(model_slug, model_name)
        campaign = self._upsert_campaign(
            campaign_slug, model["slug"], platform=platform
        )
        pipeline_job = self._create_pipeline_job(
            "import_folder",
            campaign["id"],
            {
                "folder": str(folder),
                "campaign": campaign_slug,
                "model": model_slug,
                "platform": platform,
                "accounts": account_handles or [],
                "source_prompt": source_prompt,
                "notes": notes,
            },
        )
        self._start_pipeline_job(pipeline_job["id"])
        accounts = [
            self._upsert_account(handle, platform=platform, model_id=model["id"])
            for handle in (account_handles or [])
            if handle.strip()
        ]
        try:
            dirs = self._campaign_dirs(model["slug"], campaign["slug"])
            imported: list[dict[str, Any]] = []
            duplicates: list[str] = []
            ignored: list[str] = []
            for src in sorted(folder.iterdir()):
                media_type = self._media_type_for_path(src)
                if not src.is_file() or media_type not in {"video", "image"}:
                    ignored.append(str(src))
                    continue
                digest = self._sha256_file(src)
                existing = self.conn.execute(
                    "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
                    (campaign["id"], digest),
                ).fetchone()
                if existing:
                    duplicates.append(str(src))
                    self._record_event(
                        "source_duplicate_ignored",
                        campaign_id=campaign["id"],
                        source_asset_id=existing["id"],
                        pipeline_job_id=pipeline_job["id"],
                        status="warning",
                        message=f"Duplicate source ignored: {src.name}",
                        metadata={
                            "path": str(src),
                            "contentHash": digest,
                            "existingSourceAssetId": existing["id"],
                        },
                        commit=False,
                    )
                    continue
                dest_name = (
                    f"{self._slugify(src.stem)}_{digest[:10]}{src.suffix.lower()}"
                )
                dest = dirs["sources"] / dest_name
                shutil.copy2(src, dest)
                now = self._utc_now()
                source_id = self._new_id("src")
                self.conn.execute(
                    """
                    INSERT INTO source_assets
                    (id, campaign_id, model_id, content_hash, original_path, stored_path, filename, media_type, platform, source_prompt,
                     notes, account_ids_json, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'imported', ?, ?)
                    """,
                    (
                        source_id,
                        campaign["id"],
                        model["id"],
                        digest,
                        str(src),
                        str(dest),
                        dest.name,
                        media_type,
                        platform,
                        source_prompt,
                        notes,
                        json.dumps([a["id"] for a in accounts]),
                        now,
                        now,
                    ),
                )
                imported_asset = dict(
                    self.conn.execute(
                        "SELECT * FROM source_assets WHERE id = ?", (source_id,)
                    ).fetchone()
                )
                source_graph_id = self._ensure_graph_node(
                    "source_asset",
                    local_table="source_assets",
                    local_id=source_id,
                    payload={
                        "campaignId": campaign["id"],
                        "contentHash": digest,
                        "filename": dest.name,
                        "mediaType": media_type,
                    },
                )
                self._ensure_graph_edge(
                    self._graph_id_for(
                        "campaigns",
                        campaign["id"],
                        entity_type="campaign",
                        payload={"slug": campaign["slug"]},
                    ),
                    source_graph_id,
                    "campaign_contains_source_asset",
                    evidence={
                        "importedFrom": str(src),
                        "pipelineJobId": pipeline_job["id"],
                    },
                )
                imported.append(imported_asset)
                self._record_event(
                    "source_imported",
                    campaign_id=campaign["id"],
                    source_asset_id=source_id,
                    pipeline_job_id=pipeline_job["id"],
                    status="success",
                    message=f"Source imported: {dest.name}",
                    metadata={
                        "originalPath": str(src),
                        "storedPath": str(dest),
                        "contentHash": digest,
                        "mediaType": media_type,
                    },
                    commit=False,
                )
            rendered = self._promote_review_packages(
                review_packages,
                campaign=campaign,
                model=model,
                dirs=dirs,
                platform=platform,
                account_ids=[a["id"] for a in accounts],
                pipeline_job_id=pipeline_job["id"],
            )
            result = {
                "imported": imported,
                "duplicates": duplicates,
                "ignored": ignored,
                "rendered": rendered,
                "renderedCount": len(rendered),
                "campaign": campaign,
                "model": model,
            }
            self._record_event(
                "source_imported",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="success"
                if imported
                else ("warning" if duplicates or ignored else "info"),
                message=f"Import complete: {len(imported)} imported, {len(duplicates)} duplicates, {len(ignored)} ignored",
                metadata={
                    "importedCount": len(imported),
                    "duplicateCount": len(duplicates),
                    "ignoredCount": len(ignored),
                    "renderedCount": len(rendered),
                },
                commit=False,
            )
            self.conn.commit()
            self._finish_pipeline_job(
                pipeline_job["id"],
                {
                    "importedCount": len(imported),
                    "duplicateCount": len(duplicates),
                    "ignoredCount": len(ignored),
                    "renderedCount": len(rendered),
                },
            )
            result["pipelineJobId"] = pipeline_job["id"]
            return result
        except Exception as exc:
            self._record_event(
                "source_imported",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Import failed: {exc}",
                metadata={"error": str(exc)},
            )
            self._fail_pipeline_job(pipeline_job["id"], str(exc))
            raise

    def _enforce_reel_review_batch_package(self, folder: Path) -> list[dict[str, Any]]:
        raw_manifests = [
            path for path in folder.glob("*.json") if _is_reel_review_manifest(path)
        ]
        if not raw_manifests:
            return []
        packages = [
            path for path in folder.glob("*.json") if _is_guarded_review_package(path)
        ]
        verified: list[dict[str, Any]] = []
        for manifest_path in raw_manifests:
            errors: list[str] = []
            for package_path in packages:
                try:
                    package = self._verify_reel_review_package(
                        package_path, manifest_path
                    )
                    verified.append(
                        {
                            "manifestPath": manifest_path.resolve(),
                            "packagePath": package_path.resolve(),
                            "manifest": _json_dict(manifest_path),
                            "package": package,
                        }
                    )
                    break
                except ValueError as exc:
                    errors.append(str(exc))
            else:
                if errors:
                    raise ValueError(errors[0])
                raise ValueError(
                    "Campaign Factory intake requires a guard-passed Reel Factory review package; "
                    "run scripts/run/reel-factory review-guard <manifest> --write-package inside the batch folder."
                )
        return verified

    def _verify_reel_review_package(
        self, package_path: Path, manifest_path: Path
    ) -> dict[str, Any]:
        package = _json_dict(package_path)
        package_manifest = _resolve_manifest_path(
            package_path, package.get("manifestPath")
        )
        if package_manifest != manifest_path.resolve():
            raise ValueError(
                "guarded Reel Factory review package does not match review manifest"
            )

        manifest = _json_dict(manifest_path)
        contentforge = manifest.get("contentForgeAuditPath")
        if not contentforge:
            raise ValueError(
                "Reel Factory review package missing ContentForge audit path"
            )
        contentforge_path = _resolve_batch_path(manifest_path, contentforge)
        if not contentforge_path.exists():
            raise ValueError(
                f"Reel Factory review package missing ContentForge audit: {contentforge_path}"
            )
        contentforge_payload = _json_dict(contentforge_path)
        if contentforge_payload.get("auditProfile") != "campaign_factory_v1":
            raise ValueError(
                "Reel Factory review package ContentForge audit must use campaign_factory_v1"
            )

        rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
        guard = self._run_reel_review_guard(manifest_path)
        if guard.get("status") != "ready" or guard.get("count") != len(rows):
            reasons = (
                ", ".join(guard.get("blockingReasons") or [])
                or "guard did not return ready"
            )
            raise ValueError(f"Reel Factory review guard failed: {reasons}")

        file_hashes = package.get("fileSha256")
        if not isinstance(file_hashes, dict):
            raise ValueError("guarded Reel Factory review package missing fileSha256")
        for path in _review_package_hash_paths(manifest_path, manifest):
            expected = file_hashes.get(str(path))
            if not expected:
                raise ValueError(
                    f"guarded Reel Factory review package missing hash for {path}"
                )
            if not path.exists() or _sha256_file(path) != expected:
                raise ValueError(f"review package hash mismatch for {path}")
        return package

    def _promote_review_packages(
        self,
        review_packages: list[dict[str, Any]],
        *,
        campaign: dict[str, Any],
        model: dict[str, Any],
        dirs: dict[str, Path],
        platform: str,
        account_ids: list[str],
        pipeline_job_id: str,
    ) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        for review_package in review_packages:
            manifest_path = Path(review_package["manifestPath"])
            package_path = Path(review_package["packagePath"])
            manifest = review_package["manifest"]
            rows = (
                manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
            )
            audit_path = _resolve_batch_path(
                manifest_path, manifest.get("contentForgeAuditPath")
            )
            audit_payload = _json_dict(audit_path)
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                output_path = _resolve_batch_path(manifest_path, row.get("output"))
                if not output_path.exists():
                    raise FileNotFoundError(
                        f"review batch output missing: {output_path}"
                    )
                media_type = self._media_type_for_path(output_path)
                if media_type not in {"video", "image"}:
                    raise ValueError(
                        f"review batch output is not importable media: {output_path}"
                    )
                digest = self._sha256_file(output_path)
                source_asset = self._ensure_review_source_asset(
                    campaign=campaign,
                    model=model,
                    dirs=dirs,
                    output_path=output_path,
                    digest=digest,
                    media_type=media_type,
                    platform=platform,
                    account_ids=account_ids,
                    pipeline_job_id=pipeline_job_id,
                )
                existing = self.conn.execute(
                    "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
                    (campaign["id"], digest),
                ).fetchone()
                if existing:
                    rendered_asset = dict(existing)
                else:
                    now = self._utc_now()
                    rendered_id = self._new_id("asset")
                    caption_text = str(
                        row.get("captionText") or row.get("caption") or ""
                    )
                    caption_hash = str(row.get("captionHash") or "")
                    caption_banks = (
                        row.get("sourceBanks")
                        if isinstance(row.get("sourceBanks"), list)
                        else []
                    )
                    overlay_path = _resolve_batch_path(
                        manifest_path, row.get("overlayPng")
                    )
                    audio_intent_path = output_path.with_name(
                        output_path.name + ".audio_intent.json"
                    )
                    lineage_path = output_path.with_name(
                        output_path.name + ".generated_asset_lineage.json"
                    )
                    surface = str(
                        manifest.get("surface")
                        or manifest.get("distributionSurface")
                        or "regular_reel"
                    )
                    audio_intent = _normalize_review_audio_intent(
                        _json_dict(audio_intent_path)
                        if audio_intent_path.exists()
                        else {},
                        platform=platform,
                        surface=surface,
                    )
                    lineage = _json_dict(lineage_path) if lineage_path.exists() else {}
                    placement_decision = (
                        lineage.get("captionPlacementDecision")
                        if isinstance(lineage.get("captionPlacementDecision"), dict)
                        else None
                    )
                    caption_context = {
                        "burned_caption_text": caption_text,
                        "burned_caption_hash": caption_hash,
                        "caption_banks": caption_banks,
                        "caption_bank": caption_banks[0] if caption_banks else None,
                        "caption_placement_policy": row.get("captionPlacementPolicy")
                        or manifest.get("captionPlacementPolicy"),
                        "captionPlacementPolicy": row.get("captionPlacementPolicy")
                        or manifest.get("captionPlacementPolicy"),
                        "caption_band": row.get("selectedBand"),
                        "selectedBand": row.get("selectedBand"),
                        "overlay_png": str(overlay_path),
                        "source_clip": output_path.name,
                    }
                    if placement_decision:
                        caption_context["captionPlacementDecision"] = placement_decision
                    caption_generation = {
                        "schema": "campaign_factory.reel_review_package_render.v1",
                        "captionHash": caption_hash,
                        "burnedCaptionText": caption_text,
                        "audioIntent": audio_intent,
                        "generatedAssetLineage": lineage,
                        "contentForgeAuditPath": str(audit_path),
                        "reviewBatchManifestPath": str(manifest_path),
                        "reviewBatchPackagePath": str(package_path),
                        "reviewBatchRowIndex": index,
                        "humanReviewRequired": True,
                    }
                    metadata = {
                        "schema": "campaign_factory.reel_review_batch_intake.v1",
                        "reviewBatchManifestPath": str(manifest_path),
                        "reviewBatchPackagePath": str(package_path),
                        "contentForgeAuditPath": str(audit_path),
                        "overlayPng": str(overlay_path),
                        "audioIntentPath": str(audio_intent_path)
                        if audio_intent_path.exists()
                        else None,
                        "generatedAssetLineagePath": str(lineage_path)
                        if lineage_path.exists()
                        else None,
                        "contentForgeAuditProfile": audit_payload.get("auditProfile"),
                    }
                    self.conn.execute(
                        """
                        INSERT INTO rendered_assets
                        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
                         media_type, content_surface, caption, caption_hash, caption_bank, caption_banks_json,
                         source_clip, caption_outcome_context_json, caption_generation_json, recipe, target_ratio,
                         metadata_json, audit_status, review_state, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reel', ?, ?, ?, ?, ?, ?, ?, 'reel_factory_review_package', ?, ?,
                                'approved_candidate', 'review_ready', ?, ?)
                        """,
                        (
                            rendered_id,
                            campaign["id"],
                            source_asset["id"],
                            digest,
                            str(output_path),
                            str(output_path),
                            output_path.name,
                            media_type,
                            caption_text,
                            caption_hash,
                            caption_context["caption_bank"],
                            json.dumps(
                                caption_banks, ensure_ascii=False, sort_keys=True
                            ),
                            output_path.name,
                            json.dumps(
                                caption_context, ensure_ascii=False, sort_keys=True
                            ),
                            json.dumps(
                                caption_generation, ensure_ascii=False, sort_keys=True
                            ),
                            str(
                                manifest.get("targetRatio")
                                or row.get("targetRatio")
                                or "9:16"
                            ),
                            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                            now,
                            now,
                        ),
                    )
                    rendered_asset = dict(
                        self.conn.execute(
                            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
                        ).fetchone()
                    )
                    rendered_graph_id = self._ensure_graph_node(
                        "rendered_asset",
                        local_table="rendered_assets",
                        local_id=rendered_id,
                        payload={
                            "campaignId": campaign["id"],
                            "sourceAssetId": source_asset["id"],
                            "contentHash": digest,
                            "filename": output_path.name,
                            "recipe": "reel_factory_review_package",
                        },
                    )
                    self._ensure_graph_edge(
                        self._graph_id_for(
                            "source_assets",
                            source_asset["id"],
                            entity_type="source_asset",
                        ),
                        rendered_graph_id,
                        "source_asset_to_rendered_asset",
                        evidence={
                            "reviewBatchPackagePath": str(package_path),
                            "pipelineJobId": pipeline_job_id,
                        },
                    )
                    self._record_event(
                        "rendered_asset_synced",
                        campaign_id=campaign["id"],
                        source_asset_id=source_asset["id"],
                        rendered_asset_id=rendered_id,
                        pipeline_job_id=pipeline_job_id,
                        status="success",
                        message=f"Review package promoted: {output_path.name}",
                        metadata={
                            "reviewBatchManifestPath": str(manifest_path),
                            "contentForgeAuditPath": str(audit_path),
                        },
                        commit=False,
                    )
                self._ensure_review_audit_report(
                    campaign=campaign,
                    rendered_asset_id=rendered_asset["id"],
                    audit_path=audit_path,
                    audit_payload=audit_payload,
                )
                rendered.append(rendered_asset)
        return rendered

    def _ensure_review_source_asset(
        self,
        *,
        campaign: dict[str, Any],
        model: dict[str, Any],
        dirs: dict[str, Path],
        output_path: Path,
        digest: str,
        media_type: str,
        platform: str,
        account_ids: list[str],
        pipeline_job_id: str,
    ) -> dict[str, Any]:
        existing = self.conn.execute(
            "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], digest),
        ).fetchone()
        if existing:
            return dict(existing)

        dest_name = f"{self._slugify(output_path.stem)}_{digest[:10]}{output_path.suffix.lower()}"
        dest = dirs["sources"] / dest_name
        if output_path.resolve() != dest.resolve():
            shutil.copy2(output_path, dest)
        now = self._utc_now()
        source_id = self._new_id("src")
        self.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path, filename, media_type, platform,
             notes, account_ids_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'guarded_review_package', ?, ?)
            """,
            (
                source_id,
                campaign["id"],
                model["id"],
                digest,
                str(output_path),
                str(dest),
                dest.name,
                media_type,
                platform,
                "Promoted from guard-passed Reel Factory review package.",
                json.dumps(account_ids),
                now,
                now,
            ),
        )
        source_asset = dict(
            self.conn.execute(
                "SELECT * FROM source_assets WHERE id = ?", (source_id,)
            ).fetchone()
        )
        self._record_event(
            "source_imported",
            campaign_id=campaign["id"],
            source_asset_id=source_id,
            pipeline_job_id=pipeline_job_id,
            status="success",
            message=f"Review package source registered: {output_path.name}",
            metadata={
                "originalPath": str(output_path),
                "storedPath": str(dest),
                "contentHash": digest,
                "mediaType": media_type,
            },
            commit=False,
        )
        return source_asset

    def _ensure_review_audit_report(
        self,
        *,
        campaign: dict[str, Any],
        rendered_asset_id: str,
        audit_path: Path,
        audit_payload: dict[str, Any],
    ) -> None:
        existing = self.conn.execute(
            "SELECT id FROM audit_reports WHERE rendered_asset_id = ? AND report_path = ?",
            (rendered_asset_id, str(audit_path)),
        ).fetchone()
        if existing:
            return
        pass_count = int((audit_payload.get("verdictCounts") or {}).get("pass") or 0)
        fail_count = int((audit_payload.get("verdictCounts") or {}).get("fail") or 0)
        blocking_codes = (
            audit_payload.get("blockingCodes")
            if isinstance(audit_payload.get("blockingCodes"), list)
            else []
        )
        status = (
            "approved_candidate"
            if fail_count == 0 and not blocking_codes
            else "blocked"
        )
        now = self._utc_now()
        audit_id = self._new_id("audit")
        self.conn.execute(
            """
            INSERT INTO audit_reports
            (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score, status,
             layers_json, verdicts_json, overall_verdict, files_analyzed, failed_checks_json, warnings_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                campaign["id"],
                rendered_asset_id,
                str(audit_payload.get("runId") or "reel_review_batch"),
                str(audit_path),
                100 if status == "approved_candidate" else 0,
                status,
                json.dumps(
                    {"source": "reel_factory_review_package"},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(audit_payload, ensure_ascii=False, sort_keys=True),
                "pass" if status == "approved_candidate" else "fail",
                int(audit_payload.get("variants") or pass_count or 0),
                json.dumps(blocking_codes, ensure_ascii=False, sort_keys=True),
                json.dumps([], ensure_ascii=False),
                now,
            ),
        )

    def _run_reel_review_guard(self, manifest_path: Path) -> dict[str, Any]:
        runner = CREATOR_OS_ROOT / "scripts" / "run" / "reel-factory"
        completed = subprocess.run(
            [str(runner), "review-guard", str(manifest_path)],
            cwd=CREATOR_OS_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            payload = {}
        if completed.returncode != 0 and not payload:
            return {
                "status": "blocked",
                "blockingReasons": [completed.stderr.strip() or "review_guard_failed"],
            }
        return payload

    def assets_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM source_assets WHERE campaign_id = ? ORDER BY created_at",
            (campaign_id,),
        ).fetchall()
        assets = []
        for row in rows:
            item = dict(row)
            item["media_type"] = item.get("media_type") or self._media_type_for_path(
                item.get("stored_path") or item.get("filename") or ""
            )
            assets.append(item)
        return assets
