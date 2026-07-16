from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text


class LibraryReuseError(ValueError):
    """Fail-closed Library Reuse error with a stable operator-facing code."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class LibraryReuseSelection:
    source_path: Path
    canonical_path: Path
    source_sha256: str
    media_identity: str
    output_filename: str


class LibraryReuseRepository:
    """Promote owned MP4s byte-for-byte without invoking Reel Factory."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        slugify: Callable[[str], str],
        utc_now: Callable[[], str],
        sha256_file: Callable[[Path], str],
        upsert_model: Callable[..., dict[str, Any]],
        upsert_campaign: Callable[..., dict[str, Any]],
        campaign_dirs: Callable[[str, str], dict[str, Path]],
        audit_campaign: Callable[..., dict[str, Any]],
        create_pipeline_job: Callable[..., dict[str, Any]],
        start_pipeline_job: Callable[[str], dict[str, Any]],
        finish_pipeline_job: Callable[..., dict[str, Any]],
        fail_pipeline_job: Callable[..., dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        graph_id_for: Callable[..., str | None],
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._slugify = slugify
        self._utc_now = utc_now
        self._sha256_file = sha256_file
        self._upsert_model = upsert_model
        self._upsert_campaign = upsert_campaign
        self._campaign_dirs = campaign_dirs
        self._audit_campaign = audit_campaign
        self._create_pipeline_job = create_pipeline_job
        self._start_pipeline_job = start_pipeline_job
        self._finish_pipeline_job = finish_pipeline_job
        self._fail_pipeline_job = fail_pipeline_job
        self._record_event = record_event
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._graph_id_for = graph_id_for

    def plan(self, folder: Path) -> list[LibraryReuseSelection]:
        folder = Path(folder).expanduser().resolve()
        if not folder.is_dir():
            raise LibraryReuseError(
                "library_reuse_input_folder_missing",
                f"library folder not found: {folder}",
            )
        candidates = sorted(
            (
                path.absolute()
                for path in folder.iterdir()
                if path.suffix.lower() == ".mp4"
            ),
            key=lambda path: str(path),
        )
        if not candidates:
            raise LibraryReuseError(
                "library_reuse_input_missing",
                f"library folder contains no selected MP4s: {folder}",
            )
        selections: list[LibraryReuseSelection] = []
        seen_paths: dict[Path, Path] = {}
        seen_hashes: dict[str, Path] = {}
        seen_outputs: dict[str, Path] = {}
        for source_path in candidates:
            if not source_path.is_file():
                raise LibraryReuseError(
                    "library_reuse_input_missing",
                    f"selected MP4 is missing: {source_path}",
                )
            try:
                canonical_path = source_path.resolve(strict=True)
                digest = self._sha256_file(source_path)
            except OSError as exc:
                raise LibraryReuseError(
                    "library_reuse_input_unreadable",
                    f"cannot read selected MP4 {source_path}: {exc}",
                ) from exc
            prior_path = seen_paths.get(canonical_path)
            if prior_path is not None:
                raise LibraryReuseError(
                    "library_reuse_duplicate_source_selection",
                    f"{source_path} and {prior_path} resolve to the same file",
                )
            prior_hash = seen_hashes.get(digest)
            if prior_hash is not None:
                raise LibraryReuseError(
                    "library_reuse_duplicate_source_selection",
                    f"{source_path} and {prior_hash} have the same SHA-256 {digest}",
                )
            output_filename = self._output_filename(source_path, digest)
            prior_output = seen_outputs.get(output_filename)
            if prior_output is not None:
                raise LibraryReuseError(
                    "library_reuse_output_collision",
                    f"{source_path} and {prior_output} map to {output_filename}",
                )
            seen_paths[canonical_path] = source_path
            seen_hashes[digest] = source_path
            seen_outputs[output_filename] = source_path
            selections.append(
                LibraryReuseSelection(
                    source_path=source_path,
                    canonical_path=canonical_path,
                    source_sha256=digest,
                    media_identity=f"sha256:{digest}",
                    output_filename=output_filename,
                )
            )
        return selections

    def run(
        self,
        *,
        folder: Path,
        campaign_slug: str,
        model_slug: str,
    ) -> dict[str, Any]:
        selections = self.plan(folder)
        model = self._upsert_model(model_slug)
        campaign = self._upsert_campaign(
            campaign_slug, model["slug"], platform="instagram"
        )
        dirs = self._campaign_dirs(model["slug"], campaign["slug"])
        run_dir = dirs["reel_inputs"] / "library_reuse_runs"
        run_dir.mkdir(parents=True, exist_ok=True)
        pipeline_job = self._create_pipeline_job(
            "library_reuse",
            campaign["id"],
            {
                "campaign": campaign["slug"],
                "model": model["slug"],
                "selectedCount": len(selections),
                "sourcePaths": [str(item.source_path) for item in selections],
                "sourceSha256": [item.source_sha256 for item in selections],
                "providerCallsAllowed": False,
                "paidGenerationAllowed": False,
            },
        )
        self._start_pipeline_job(pipeline_job["id"])
        manifest_path = run_dir / f"{pipeline_job['id']}.json"
        manifest: dict[str, Any] = {
            "schema": "campaign_factory.library_reuse_run.v1",
            "runId": pipeline_job["id"],
            "campaignId": campaign["id"],
            "campaignSlug": campaign["slug"],
            "modelSlug": model["slug"],
            "status": "preparing",
            "recoverable": True,
            "providerCalls": 0,
            "paidGeneration": False,
            "renderingPerformed": False,
            "captionSidecarsWritten": 0,
            "distributionDefaults": _regular_reel_defaults(),
            "selected": [self._selection_payload(item) for item in selections],
            "mappings": [],
            "createdAt": self._utc_now(),
            "updatedAt": self._utc_now(),
        }
        try:
            self._write_manifest(manifest_path, manifest)
            rendered_ids: list[str] = []
            for selection in selections:
                self._verify_source_unchanged(selection)
                source = self._ensure_source_asset(
                    selection=selection,
                    campaign=campaign,
                    model=model,
                    dirs=dirs,
                    pipeline_job_id=pipeline_job["id"],
                )
                rendered = self._ensure_rendered_asset(
                    selection=selection,
                    source=source,
                    campaign=campaign,
                    dirs=dirs,
                    pipeline_job_id=pipeline_job["id"],
                )
                rendered_ids.append(rendered["id"])
                manifest["mappings"].append(
                    self._mapping_payload(selection, source, rendered)
                )
                manifest["status"] = "preparing"
                manifest["updatedAt"] = self._utc_now()
                self._write_manifest(manifest_path, manifest)

            if len(set(rendered_ids)) != len(selections):
                raise LibraryReuseError(
                    "library_reuse_duplicate_output_mapping",
                    "multiple selected MP4s resolved to the same rendered asset",
                )
            audit = self._audit_campaign(
                campaign_slug=campaign["slug"],
                min_score=85,
                rendered_asset_ids=rendered_ids,
            )
            reports = audit.get("reports") or []
            if len(reports) != len(rendered_ids):
                raise LibraryReuseError(
                    "library_reuse_validation_count_mismatch",
                    f"expected {len(rendered_ids)} ContentForge reports, got {len(reports)}",
                )
            manifest["status"] = "validated"
            manifest["validation"] = {
                "status": "complete",
                "hashVerifiedCount": len(rendered_ids),
                "contentForgeReportCount": len(reports),
                "failedCount": sum(
                    1 for report in reports if report.get("failedChecks")
                ),
                "warningCount": sum(
                    1
                    for report in reports
                    if report.get("warnings") or report.get("overallVerdict") == "warn"
                ),
            }
            manifest["updatedAt"] = self._utc_now()
            self._write_manifest(manifest_path, manifest)
            self._record_event(
                "library_reuse_completed",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="success",
                message=f"Library Reuse preserved {len(rendered_ids)} MP4s",
                metadata={
                    "manifestPath": str(manifest_path),
                    "selectedCount": len(selections),
                    "renderedAssetIds": rendered_ids,
                    "providerCalls": 0,
                    "paidGeneration": False,
                    "renderingPerformed": False,
                },
            )
            self._finish_pipeline_job(
                pipeline_job["id"],
                {
                    "status": "validated",
                    "manifestPath": str(manifest_path),
                    "selectedCount": len(selections),
                    "renderedAssetIds": rendered_ids,
                    "providerCalls": 0,
                    "paidGeneration": False,
                },
            )
            return {
                **manifest,
                "manifestPath": str(manifest_path),
                "humanReviewRequired": True,
                "autoApprovalAllowed": False,
                "draftExportAllowed": False,
            }
        except BaseException as exc:
            self.conn.rollback()
            interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
            manifest["status"] = "interrupted" if interrupted else "failed"
            manifest["error"] = {
                "type": type(exc).__name__,
                "code": getattr(exc, "code", None),
                "message": str(exc) or type(exc).__name__,
            }
            manifest["mappings"] = self._recoverable_mappings(
                selections=selections,
                campaign=campaign,
            )
            manifest["completedCount"] = len(manifest["mappings"])
            manifest["remainingCount"] = len(selections) - len(manifest["mappings"])
            manifest["partialFiles"] = sorted(
                str(path)
                for path in dirs["root"].rglob(f".*.{pipeline_job['id']}.partial")
            )
            manifest["updatedAt"] = self._utc_now()
            self._write_manifest(manifest_path, manifest)
            self._record_event(
                "library_reuse_interrupted" if interrupted else "library_reuse_failed",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Library Reuse {manifest['status']}: {manifest['error']['message']}",
                metadata={
                    "manifestPath": str(manifest_path),
                    "completedCount": manifest["completedCount"],
                    "remainingCount": manifest["remainingCount"],
                    "recoverable": True,
                },
                commit=False,
            )
            self._fail_pipeline_job(
                pipeline_job["id"],
                manifest["error"]["message"],
                {
                    "status": manifest["status"],
                    "manifestPath": str(manifest_path),
                    "completedCount": manifest["completedCount"],
                    "remainingCount": manifest["remainingCount"],
                    "recoverable": True,
                },
            )
            raise

    def _ensure_source_asset(
        self,
        *,
        selection: LibraryReuseSelection,
        campaign: dict[str, Any],
        model: dict[str, Any],
        dirs: dict[str, Path],
        pipeline_job_id: str,
    ) -> dict[str, Any]:
        existing = self.conn.execute(
            "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], selection.source_sha256),
        ).fetchone()
        if existing:
            source = dict(existing)
            self._verify_existing_source(selection, source, model=model)
            return source
        stored_path = dirs["sources"] / selection.output_filename
        self._copy_verified(
            selection.source_path,
            stored_path,
            selection.source_sha256,
            collision_code="library_reuse_import_output_collision",
            mismatch_code="library_reuse_import_hash_mismatch",
            run_id=pipeline_job_id,
        )
        source_id = self._new_id("src")
        now = self._utc_now()
        source_prompt = self._source_prompt(selection)
        self.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, platform, source_prompt, notes, account_ids_json,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'instagram', ?, ?, '[]',
                    'imported', ?, ?)
            """,
            (
                source_id,
                campaign["id"],
                model["id"],
                selection.source_sha256,
                str(selection.source_path),
                str(stored_path),
                stored_path.name,
                json.dumps(source_prompt, ensure_ascii=False, sort_keys=True),
                "library_reuse byte-preserving import",
                now,
                now,
            ),
        )
        source_graph_id = self._ensure_graph_node(
            "source_asset",
            local_table="source_assets",
            local_id=source_id,
            payload={
                "campaignId": campaign["id"],
                "contentHash": selection.source_sha256,
                "filename": stored_path.name,
                "mediaType": "video",
                "creativeMode": "library_reuse",
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
                "importedFrom": str(selection.source_path),
                "sourceSha256": selection.source_sha256,
                "pipelineJobId": pipeline_job_id,
            },
        )
        self._record_event(
            "source_imported",
            campaign_id=campaign["id"],
            source_asset_id=source_id,
            pipeline_job_id=pipeline_job_id,
            status="success",
            message=f"Library MP4 imported: {stored_path.name}",
            metadata={
                "originalPath": str(selection.source_path),
                "storedPath": str(stored_path),
                "contentHash": selection.source_sha256,
                "creativeMode": "library_reuse",
            },
            commit=False,
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM source_assets WHERE id = ?", (source_id,)
            ).fetchone()
        )

    def _ensure_rendered_asset(
        self,
        *,
        selection: LibraryReuseSelection,
        source: dict[str, Any],
        campaign: dict[str, Any],
        dirs: dict[str, Path],
        pipeline_job_id: str,
    ) -> dict[str, Any]:
        output_dir = dirs["rendered"] / "library_reuse"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / selection.output_filename
        existing = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], selection.source_sha256),
        ).fetchone()
        if existing:
            rendered = dict(existing)
            if (
                rendered["source_asset_id"] != source["id"]
                or rendered["recipe"] != "library_reuse_passthrough"
                or Path(rendered["campaign_path"]).resolve() != output_path.resolve()
            ):
                raise LibraryReuseError(
                    "library_reuse_output_mapping_conflict",
                    f"content hash {selection.source_sha256} is already mapped to rendered asset {rendered['id']}",
                )
            self._verify_hash(
                output_path,
                selection.source_sha256,
                "library_reuse_output_hash_mismatch",
            )
            return rendered
        self._copy_verified(
            Path(source["stored_path"]),
            output_path,
            selection.source_sha256,
            collision_code="library_reuse_output_collision",
            mismatch_code="library_reuse_output_hash_mismatch",
            run_id=pipeline_job_id,
        )
        rendered_id = self._new_id("asset")
        now = self._utc_now()
        empty_caption_hash = hashlib.sha256(b"").hexdigest()
        lineage = self._owned_library_lineage(
            selection=selection,
            source=source,
            rendered_id=rendered_id,
            output_path=output_path,
        )
        caption_context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": empty_caption_hash,
            "caption_text": None,
            "caption_bank": None,
            "caption_banks": [],
            "render_recipe": "library_reuse_passthrough",
            "source_clip": selection.source_path.name,
            "rendered_output": str(output_path),
            "burned_caption_text": None,
            "burned_caption_hash": None,
            "captionWasBurned": False,
        }
        caption_generation = {
            "schema": "campaign_factory.library_reuse_caption_state.v1",
            "burnedCaption": False,
            "burnedCaptionText": None,
            "captionSidecarPath": None,
            "captionRenderingPerformed": False,
            "generatedAssetLineage": lineage,
            "humanReviewRequired": True,
        }
        metadata = {
            "schema": "campaign_factory.library_reuse_asset.v1",
            "creativeMode": "library_reuse",
            "sourceOriginalPath": str(selection.source_path),
            "sourceCanonicalPath": str(selection.canonical_path),
            "sourceStoredPath": source["stored_path"],
            "sourceSha256": selection.source_sha256,
            "outputSha256": selection.source_sha256,
            "mediaIdentity": selection.media_identity,
            "copiedByteForByte": True,
            "renderingPerformed": False,
            "providerCalls": 0,
            "paidGeneration": False,
            "captionBurned": False,
            "captionSidecarPath": None,
            "distributionDefaults": _regular_reel_defaults(),
        }
        self.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path,
             campaign_path, filename, media_type, content_surface, caption,
             caption_hash, caption_banks_json, source_clip,
             caption_outcome_context_json, caption_generation_json, recipe,
             metadata_json, audit_status, review_state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', NULL, ?, '[]', ?,
                    ?, ?, 'library_reuse_passthrough', ?, 'pending', 'draft', ?, ?)
            """,
            (
                rendered_id,
                campaign["id"],
                source["id"],
                selection.source_sha256,
                str(output_path),
                str(output_path),
                output_path.name,
                empty_caption_hash,
                selection.source_path.name,
                json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
                json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        rendered_graph_id = self._ensure_graph_node(
            "rendered_asset",
            local_table="rendered_assets",
            local_id=rendered_id,
            payload={
                "campaignId": campaign["id"],
                "sourceAssetId": source["id"],
                "contentHash": selection.source_sha256,
                "filename": output_path.name,
                "recipe": "library_reuse_passthrough",
            },
        )
        self._ensure_graph_edge(
            self._graph_id_for(
                "source_assets", source["id"], entity_type="source_asset"
            ),
            rendered_graph_id,
            "source_asset_to_rendered_asset",
            evidence={
                "creativeMode": "library_reuse",
                "sourceSha256": selection.source_sha256,
                "outputSha256": selection.source_sha256,
                "pipelineJobId": pipeline_job_id,
            },
        )
        self._record_event(
            "rendered_asset_synced",
            campaign_id=campaign["id"],
            source_asset_id=source["id"],
            rendered_asset_id=rendered_id,
            pipeline_job_id=pipeline_job_id,
            status="success",
            message=f"Library MP4 preserved: {output_path.name}",
            metadata={
                "creativeMode": "library_reuse",
                "sourcePath": str(selection.source_path),
                "outputPath": str(output_path),
                "contentHash": selection.source_sha256,
                "captionBurned": False,
                "providerCalls": 0,
                "paidGeneration": False,
            },
            commit=False,
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
            ).fetchone()
        )

    def _verify_existing_source(
        self,
        selection: LibraryReuseSelection,
        source: dict[str, Any],
        *,
        model: dict[str, Any],
    ) -> None:
        if source["media_type"] != "video":
            raise LibraryReuseError(
                "library_reuse_source_substituted",
                f"source asset {source['id']} is not a video",
            )
        if source["model_id"] != model["id"]:
            raise LibraryReuseError(
                "library_reuse_source_substituted",
                f"source asset {source['id']} belongs to model {source['model_id']}, not {model['id']}",
            )
        if Path(source["original_path"]).absolute() != selection.source_path:
            raise LibraryReuseError(
                "library_reuse_source_substituted",
                f"source asset {source['id']} belongs to {source['original_path']}, not {selection.source_path}",
            )
        self._verify_hash(
            Path(source["stored_path"]),
            selection.source_sha256,
            "library_reuse_stored_hash_mismatch",
        )

    def _verify_source_unchanged(self, selection: LibraryReuseSelection) -> None:
        self._verify_hash(
            selection.source_path,
            selection.source_sha256,
            "library_reuse_source_hash_mismatch",
        )

    def _verify_hash(self, path: Path, expected: str, mismatch_code: str) -> None:
        if not path.is_file():
            raise LibraryReuseError(
                "library_reuse_input_missing",
                f"expected media file is missing: {path}",
            )
        try:
            actual = self._sha256_file(path)
        except OSError as exc:
            raise LibraryReuseError(
                "library_reuse_input_unreadable",
                f"cannot read media file {path}: {exc}",
            ) from exc
        if actual != expected:
            raise LibraryReuseError(
                mismatch_code,
                f"SHA-256 mismatch for {path}: expected {expected}, got {actual}",
            )

    def _copy_verified(
        self,
        source: Path,
        destination: Path,
        expected_sha256: str,
        *,
        collision_code: str,
        mismatch_code: str,
        run_id: str,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            try:
                actual = self._sha256_file(destination)
            except OSError as exc:
                raise LibraryReuseError(
                    "library_reuse_input_unreadable",
                    f"cannot read existing output {destination}: {exc}",
                ) from exc
            if actual != expected_sha256:
                raise LibraryReuseError(
                    collision_code,
                    f"existing output {destination} has SHA-256 {actual}, expected {expected_sha256}",
                )
            return
        partial = destination.with_name(f".{destination.name}.{run_id}.partial")
        if partial.exists():
            raise LibraryReuseError(
                collision_code,
                f"partial output already exists: {partial}",
            )
        try:
            with source.open("rb") as source_file, partial.open("xb") as output_file:
                shutil.copyfileobj(source_file, output_file, length=1024 * 1024)
                output_file.flush()
                os.fsync(output_file.fileno())
        except OSError as exc:
            raise LibraryReuseError(
                "library_reuse_input_unreadable",
                f"cannot copy {source} to {partial}: {exc}",
            ) from exc
        self._verify_hash(partial, expected_sha256, mismatch_code)
        try:
            os.replace(partial, destination)
        except OSError as exc:
            raise LibraryReuseError(
                "library_reuse_output_finalize_failed",
                f"cannot finalize {partial} as {destination}: {exc}",
            ) from exc
        self._verify_hash(destination, expected_sha256, mismatch_code)

    def _recoverable_mappings(
        self,
        *,
        selections: list[LibraryReuseSelection],
        campaign: dict[str, Any],
    ) -> list[dict[str, Any]]:
        mappings: list[dict[str, Any]] = []
        for selection in selections:
            source_row = self.conn.execute(
                "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
                (campaign["id"], selection.source_sha256),
            ).fetchone()
            rendered_row = self.conn.execute(
                "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
                (campaign["id"], selection.source_sha256),
            ).fetchone()
            if not source_row or not rendered_row:
                continue
            source = dict(source_row)
            rendered = dict(rendered_row)
            if (
                rendered["source_asset_id"] != source["id"]
                or rendered["recipe"] != "library_reuse_passthrough"
            ):
                continue
            try:
                stored_hash = self._sha256_file(Path(source["stored_path"]))
                output_hash = self._sha256_file(Path(rendered["campaign_path"]))
            except OSError:
                continue
            if stored_hash != selection.source_sha256 or output_hash != stored_hash:
                continue
            mappings.append(
                {
                    **self._selection_payload(selection),
                    "sourceAssetId": source["id"],
                    "storedPath": source["stored_path"],
                    "storedSha256": stored_hash,
                    "renderedAssetId": rendered["id"],
                    "outputPath": rendered["campaign_path"],
                    "outputSha256": output_hash,
                    "captionBurned": False,
                    "captionSidecarPath": None,
                    "renderingPerformed": False,
                }
            )
        return mappings

    def _output_filename(self, source_path: Path, digest: str) -> str:
        return f"{self._slugify(source_path.stem)}_{digest[:16]}.mp4"

    def _source_prompt(self, selection: LibraryReuseSelection) -> dict[str, Any]:
        return {
            "schema": "campaign_factory.owned_library_source.v1",
            "promptId": f"owned_library_asset_{selection.source_sha256}",
            "promptKind": "not_applicable_existing_media",
            "generationTool": "library_reuse",
            "providerGenerated": False,
            "mediaIdentity": selection.media_identity,
            "sourcePath": str(selection.source_path),
            "sourceSha256": selection.source_sha256,
        }

    def _owned_library_lineage(
        self,
        *,
        selection: LibraryReuseSelection,
        source: dict[str, Any],
        rendered_id: str,
        output_path: Path,
    ) -> dict[str, Any]:
        return {
            "schema": "campaign_factory.owned_library_lineage.v1",
            "sourceAssetId": source["id"],
            "renderedAssetId": rendered_id,
            "contentFingerprint": selection.source_sha256,
            "mediaIdentity": selection.media_identity,
            "source": {
                "promptId": f"owned_library_asset_{selection.source_sha256}",
                "promptKind": "not_applicable_existing_media",
                "originalPath": str(selection.source_path),
                "canonicalPath": str(selection.canonical_path),
                "storedPath": source["stored_path"],
                "sha256": selection.source_sha256,
            },
            "generation": {
                "tool": "library_reuse",
                "providerGenerated": False,
                "providerCalls": 0,
                "paidGeneration": False,
                "renderingPerformed": False,
            },
            "review": {
                "humanReviewRequired": True,
                "status": "draft",
            },
            "reuse": {
                "outputPath": str(output_path),
                "outputSha256": selection.source_sha256,
                "copiedByteForByte": True,
            },
            "caption": {
                "burned": False,
                "text": None,
                "sidecarPath": None,
                "renderingPerformed": False,
            },
            "distributionDefaults": _regular_reel_defaults(),
            "ownerAttestation": {
                "method": "local_hash_verified",
                "scope": "operator_owned_library",
                "contentSha256": selection.source_sha256,
            },
            "learningEligible": False,
            "ineligibilityReasons": ["unpublished_owned_library_asset"],
        }

    def _selection_payload(self, selection: LibraryReuseSelection) -> dict[str, Any]:
        return {
            "sourcePath": str(selection.source_path),
            "canonicalPath": str(selection.canonical_path),
            "sourceSha256": selection.source_sha256,
            "mediaIdentity": selection.media_identity,
            "outputFilename": selection.output_filename,
        }

    def _mapping_payload(
        self,
        selection: LibraryReuseSelection,
        source: dict[str, Any],
        rendered: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **self._selection_payload(selection),
            "sourceAssetId": source["id"],
            "storedPath": source["stored_path"],
            "storedSha256": selection.source_sha256,
            "renderedAssetId": rendered["id"],
            "outputPath": rendered["campaign_path"],
            "outputSha256": selection.source_sha256,
            "captionBurned": False,
            "captionSidecarPath": None,
            "renderingPerformed": False,
        }

    def _write_manifest(self, path: Path, payload: dict[str, Any]) -> None:
        atomic_write_text(
            path,
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )


def _regular_reel_defaults() -> dict[str, Any]:
    return {
        "surface": "regular_reel",
        "instagramTrialReels": False,
        "shareToFeed": True,
        "collaborators": [],
    }
