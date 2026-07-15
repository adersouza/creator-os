from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .config import Settings
from .persistence import json_load


class MakeBatchRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        audit_campaign: Callable[..., dict[str, Any]],
        evaluate_export_readiness: Callable[..., dict[str, Any]],
        export_threadsdash: Callable[..., dict[str, Any]],
        new_id: Callable[[str], str],
        utc_now: Callable[[], str],
        sha256_file: Callable[[Any], str],
        media_type_for_path: Callable[[Any], str],
        reel_factory_python: Callable[[Any], str],
        subprocess_run: Callable[..., Any],
        create_pipeline_job: Callable[..., dict[str, Any]],
        start_pipeline_job: Callable[[str], dict[str, Any]],
        set_pipeline_job_campaign: Callable[[str, str], None],
        finish_pipeline_job: Callable[..., dict[str, Any]],
        fail_pipeline_job: Callable[..., dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
        import_folder: Callable[..., dict[str, Any]],
        reference_patterns: Callable[..., dict[str, Any]],
        import_reference_bank: Callable[..., dict[str, Any]],
        select_reference_pattern: Callable[..., dict[str, Any]],
        prepare_reel_from_reference: Callable[..., dict[str, Any]],
        finished_video_hooks: Callable[..., list[dict[str, Any]]],
        finished_video_caption_band: Callable[[str], str],
        finished_video_caption_font: Callable[[str], str],
        prepare_reel_inputs: Callable[..., dict[str, Any]],
        run_reel_factory: Callable[..., dict[str, Any]],
        sync_reel_outputs: Callable[..., dict[str, Any]],
        dashboard: Callable[[str], dict[str, Any]],
        campaign_health: Callable[[str], dict[str, Any]],
        ranking: Callable[[str], dict[str, Any]],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        model_slug_for_campaign: Callable[[str], str],
        campaign_dirs: Callable[[str, str], dict[str, Path]],
        assets_for_campaign: Callable[[str], list[dict[str, Any]]],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._audit_campaign = audit_campaign
        self._evaluate_export_readiness = evaluate_export_readiness
        self._export_threadsdash = export_threadsdash
        self._new_id = new_id
        self._utc_now = utc_now
        self._sha256_file = sha256_file
        self._media_type_for_path = media_type_for_path
        self._reel_factory_python = reel_factory_python
        self._subprocess_run = subprocess_run
        self._create_pipeline_job = create_pipeline_job
        self._start_pipeline_job = start_pipeline_job
        self._set_pipeline_job_campaign = set_pipeline_job_campaign
        self._finish_pipeline_job = finish_pipeline_job
        self._fail_pipeline_job = fail_pipeline_job
        self._record_event = record_event
        self._import_folder = import_folder
        self._reference_patterns = reference_patterns
        self._import_reference_bank = import_reference_bank
        self._select_reference_pattern = select_reference_pattern
        self._prepare_reel_from_reference = prepare_reel_from_reference
        self._finished_video_hooks = finished_video_hooks
        self._finished_video_caption_band = finished_video_caption_band
        self._finished_video_caption_font = finished_video_caption_font
        self._prepare_reel_inputs = prepare_reel_inputs
        self._run_reel_factory = run_reel_factory
        self._sync_reel_outputs = sync_reel_outputs
        self._dashboard = dashboard
        self._campaign_health = campaign_health
        self._ranking = ranking
        self._campaign_by_slug = campaign_by_slug
        self._model_slug_for_campaign = model_slug_for_campaign
        self._campaign_dirs = campaign_dirs
        self._assets_for_campaign = assets_for_campaign

    def make_batch(
        self,
        *,
        folder: Path,
        campaign_slug: str,
        model_slug: str,
        output_format: str = "auto",
        variant_count: int = 20,
        reference_pattern: str | None = "auto",
        contentforge_base_url: str | None = None,
        user_id: str | None = None,
        dry_run_export: bool = True,
        workers: int = 3,
        recipes: list[str] | None = None,
        auto_approve_warning_only: bool = True,
        source_prompt: str | None = None,
        import_notes: str | None = None,
    ) -> dict[str, Any]:
        selected_format = (
            output_format if output_format in {"reel", "slideshow", "auto"} else "auto"
        )
        pipeline_job = self._create_pipeline_job(
            "make_batch",
            None,
            {
                "folder": str(folder),
                "campaign": campaign_slug,
                "model": model_slug,
                "format": selected_format,
                "variantCount": variant_count,
                "referencePattern": reference_pattern,
                "contentforgeBaseUrl": contentforge_base_url,
                "hasUserId": bool(user_id),
                "dryRunExport": dry_run_export,
                "workers": workers,
                "recipes": recipes or [],
                "autoApproveWarningOnly": auto_approve_warning_only,
                "hasSourcePrompt": bool(source_prompt),
            },
        )
        self._start_pipeline_job(pipeline_job["id"])
        try:
            result: dict[str, Any] = {
                "schema": "campaign_factory.make_batch.v1",
                "campaign": campaign_slug,
                "pipelineJobId": pipeline_job["id"],
                "import": None,
                "referenceImport": None,
                "referenceSelection": None,
                "prepare": None,
                "run": None,
                "sync": None,
                "audit": None,
                "autoApproved": [],
                "readiness": None,
                "dryRunExport": None,
                "dashboard": None,
                "format": selected_format,
                "reviewReady": [],
            }
            imported = self._import_folder(
                Path(folder),
                campaign_slug=campaign_slug,
                model_slug=model_slug,
                platform="instagram",
                source_prompt=source_prompt,
                notes=import_notes or "make-batch source import",
            )
            result["import"] = {
                "importedCount": len(imported.get("imported") or []),
                "duplicateCount": len(imported.get("duplicates") or []),
                "ignoredCount": len(imported.get("ignored") or []),
                "campaignId": imported["campaign"]["id"],
                "campaignSlug": imported["campaign"]["slug"],
                "modelSlug": imported["model"]["slug"],
            }
            self._set_pipeline_job_campaign(
                pipeline_job["id"], imported["campaign"]["id"]
            )

            if not self._reference_patterns(limit=1)["patterns"]:
                bank_path = (
                    self.settings.reference_reels_root
                    / "learning"
                    / "campaign_reference_bank.json"
                )
                prompt_pack_path = (
                    self.settings.reference_reels_root
                    / "learning"
                    / "higgsfield_prompt_pack_top300.json"
                )
                if bank_path.exists():
                    reference_import = self._import_reference_bank(
                        bank_path,
                        prompt_pack_path if prompt_pack_path.exists() else None,
                    )
                    result["referenceImport"] = {
                        "patternsImported": reference_import.get("patternsImported"),
                        "bankPath": reference_import.get("bankPath"),
                    }

            cluster_key = (
                None
                if not reference_pattern or reference_pattern == "auto"
                else reference_pattern
            )
            source_mix = self.campaign_source_media_summary(imported["campaign"]["id"])
            formats_to_run = self.formats_for_batch(selected_format, source_mix)
            result["sourceMix"] = source_mix
            result["formatsRun"] = formats_to_run
            source_prompt_payload = (
                json_load(source_prompt, {}) if source_prompt else {}
            )
            finished_format_type = (
                source_prompt_payload.get("formatType")
                if isinstance(source_prompt_payload, dict)
                and source_prompt_payload.get("schema")
                == "campaign_factory.finished_video_intake.v1"
                else None
            )
            reel_caption_band = (
                self._finished_video_caption_band(str(finished_format_type))
                if finished_format_type
                else "auto"
            )
            reel_caption_font = (
                self._finished_video_caption_font(str(finished_format_type))
                if finished_format_type
                else "Instagram Sans Condensed"
            )

            prepared_by_format: dict[str, Any] = {}
            pattern: dict[str, Any] = {}
            for format_name in formats_to_run:
                if format_name == "slideshow":
                    prepared = self.run_slideshow_pack(
                        campaign_slug=campaign_slug,
                        variant_count=max(1, min(int(variant_count or 20), 100)),
                        title=campaign_slug.replace("_", " ").title(),
                        cluster_key=cluster_key,
                        media_types={"image"}
                        if source_mix.get("image", 0)
                        else {"video"},
                    )
                    prepared_by_format["slideshow"] = prepared
                else:
                    if finished_format_type:
                        selection = self._select_reference_pattern(
                            campaign_slug,
                            cluster_key=cluster_key,
                            variant_count=max(1, min(int(variant_count or 20), 100)),
                            notes="make-batch finished-video reference render",
                        )
                        pattern = selection["pattern"]
                        hooks = self._finished_video_hooks(
                            str(finished_format_type),
                            pattern,
                            count=max(1, min(int(variant_count or 20), 100)),
                        )
                        prepare = self._prepare_reel_inputs(
                            campaign_slug=campaign_slug,
                            hooks=hooks,
                            recipes=recipes,
                            caption_color="auto",
                            notes="finished-video native caption render",
                            force_new=True,
                        )
                        prepared = {
                            "schema": "campaign_factory.prepare_from_reference.v1",
                            "campaign": campaign_slug,
                            "selection": {**selection, "hooks": hooks},
                            "prepare": prepare,
                        }
                    else:
                        prepared = self._prepare_reel_from_reference(
                            campaign_slug=campaign_slug,
                            cluster_key=cluster_key,
                            variant_count=max(1, min(int(variant_count or 20), 100)),
                            recipes=recipes,
                            caption_color="auto",
                            notes="make-batch reference render",
                            force_new=True,
                        )
                    prepared_by_format["reel"] = prepared
                    run_result = self._run_reel_factory(
                        campaign_slug=campaign_slug,
                        workers=workers,
                        dry_run=False,
                        caption_band=reel_caption_band,
                        caption_color="light",
                        caption_style="ig",
                        caption_font=reel_caption_font,
                        phone_finalize=True,
                        max_outputs_per_clip=max(1, min(int(variant_count or 20), 100)),
                    )
                    sync_result = self._sync_reel_outputs(campaign_slug=campaign_slug)
                    sync_retries: list[dict[str, Any]] = []
                    prepared_jobs = (
                        (prepared.get("prepare") or {}).get("prepared")
                        or prepared.get("prepared")
                        or []
                    )
                    expected_sync_count = max(1, len(prepared_jobs))
                    if (
                        run_result.get("returncode") == 0
                        and len(sync_result.get("synced") or []) < expected_sync_count
                    ):
                        time.sleep(1.0)
                        sync_retry = self._sync_reel_outputs(
                            campaign_slug=campaign_slug
                        )
                        sync_retry_count = len(sync_retry.get("synced") or [])
                        sync_retries.append(
                            {
                                "kind": "poll",
                                "expectedSyncedCount": expected_sync_count,
                                "syncedCount": sync_retry_count,
                            }
                        )
                        if sync_retry_count >= expected_sync_count:
                            sync_result = sync_retry
                        else:
                            rerun_result = self._run_reel_factory(
                                campaign_slug=campaign_slug,
                                workers=workers,
                                dry_run=False,
                                caption_band=reel_caption_band,
                                caption_color="light",
                                caption_style="ig",
                                caption_font=reel_caption_font,
                                phone_finalize=True,
                                rerender_all=True,
                                max_outputs_per_clip=max(
                                    1, min(int(variant_count or 20), 100)
                                ),
                            )
                            sync_retry = self._sync_reel_outputs(
                                campaign_slug=campaign_slug
                            )
                            sync_retry_count = len(sync_retry.get("synced") or [])
                            sync_retries.append(
                                {
                                    "kind": "rerun",
                                    "returncode": rerun_result.get("returncode"),
                                    "expectedSyncedCount": expected_sync_count,
                                    "syncedCount": sync_retry_count,
                                }
                            )
                            if sync_retry_count > len(sync_result.get("synced") or []):
                                sync_result = sync_retry
                    prepared["run"] = {
                        "returncode": run_result.get("returncode"),
                        "runCount": len(run_result.get("runs") or []),
                        "elapsedSeconds": run_result.get("elapsed_seconds"),
                    }
                    prepared["sync"] = {
                        "syncedCount": len(sync_result.get("synced") or []),
                        "retries": sync_retries,
                    }
                if not pattern:
                    pattern = (prepared.get("selection") or {}).get("pattern") or {}

            result["referenceSelection"] = {
                "label": pattern.get("label"),
                "clusterKey": pattern.get("clusterKey"),
                "variantCount": max(1, min(int(variant_count or 20), 100)),
                "recipes": recipes
                or ((pattern.get("raw") or {}).get("bank") or {}).get(
                    "suggestedVariantRecipes"
                )
                or [],
            }
            prepare_payloads = [
                item.get("prepare") or {} for item in prepared_by_format.values()
            ]
            result["prepare"] = {
                "preparedCount": sum(
                    len(payload.get("prepared") or []) for payload in prepare_payloads
                ),
                "reusedExistingCount": sum(
                    len(payload.get("reusedExisting") or [])
                    for payload in prepare_payloads
                ),
                "sourceCount": sum(source_mix.values()),
                "byFormat": {
                    format_name: {
                        "preparedCount": len(
                            (payload.get("prepare") or {}).get("prepared") or []
                        ),
                        "reusedExistingCount": len(
                            (payload.get("prepare") or {}).get("reusedExisting") or []
                        ),
                    }
                    for format_name, payload in prepared_by_format.items()
                },
            }
            result["run"] = {
                "runCount": sum(
                    (payload.get("run") or {}).get("runCount") or 0
                    for payload in prepared_by_format.values()
                ),
                "byFormat": {
                    format_name: payload.get("run")
                    for format_name, payload in prepared_by_format.items()
                },
            }
            result["sync"] = {
                "syncedCount": sum(
                    (payload.get("sync") or {}).get("syncedCount")
                    or len((payload.get("prepare") or {}).get("prepared") or [])
                    for payload in prepared_by_format.values()
                ),
                "byFormat": {
                    format_name: payload.get("sync")
                    or {
                        "syncedCount": len(
                            (payload.get("prepare") or {}).get("prepared") or []
                        )
                    }
                    for format_name, payload in prepared_by_format.items()
                },
            }
            audit_result = self._audit_campaign(
                campaign_slug=campaign_slug,
                min_score=85,
                contentforge_base_url=contentforge_base_url,
            )
            reports = audit_result.get("reports") or []
            result["audit"] = {
                "reportCount": len(reports),
                "failedCount": sum(
                    1 for report in reports if report.get("failedChecks")
                ),
                "warningCount": sum(
                    1
                    for report in reports
                    if report.get("warnings") or report.get("overallVerdict") == "warn"
                ),
            }

            if auto_approve_warning_only:
                for asset in self._dashboard(campaign_slug).get("rendered") or []:
                    if asset.get("review_state") == "approved":
                        continue
                    latest = asset.get("latest_audit") or {}
                    readiness = latest.get("readinessSummary") or {}
                    blocking = list(latest.get("failedChecks") or []) + list(
                        readiness.get("blockingReasons") or []
                    )
                    if latest and not blocking:
                        self.conn.execute(
                            "UPDATE rendered_assets SET review_state = ?, updated_at = ? WHERE id = ?",
                            ("review_ready", self._utc_now(), asset["id"]),
                        )
                        self._record_event(
                            "asset_review_ready",
                            campaign_id=asset["campaign_id"],
                            source_asset_id=asset["source_asset_id"],
                            rendered_asset_id=asset["id"],
                            pipeline_job_id=pipeline_job["id"],
                            status="success",
                            message=f"Asset marked review-ready: {asset['filename']}",
                            metadata={"reason": "warning_only_or_ready"},
                            commit=False,
                        )
                        result["reviewReady"].append(
                            {
                                "renderedAssetId": asset["id"],
                                "filename": asset["filename"],
                            }
                        )
                self.conn.commit()

            if user_id:
                readiness_result = self._evaluate_export_readiness(
                    campaign_slug=campaign_slug, user_id=user_id
                )
                result["readiness"] = {
                    "expectedDraftCount": readiness_result.get("expectedDraftCount"),
                    "liveExportAllowed": readiness_result.get("liveExportAllowed"),
                    "blockingReasonCount": len(
                        readiness_result.get("blockingReasons") or []
                    ),
                    "warningCount": len(readiness_result.get("warnings") or []),
                }
                if dry_run_export:
                    export_result = self._export_threadsdash(
                        campaign_slug=campaign_slug,
                        user_id=user_id,
                        dry_run=True,
                    )
                    result["dryRunExport"] = {
                        "draftCount": export_result.get("draftCount"),
                        "path": export_result.get("path"),
                        "dryRun": export_result.get("dryRun"),
                    }
            health = self._campaign_health(campaign_slug)
            ranking = self._ranking(campaign_slug)["assets"][:5]
            result["dashboard"] = {
                "health": health,
                "topRanked": [
                    {
                        "renderedAssetId": item.get("renderedAssetId"),
                        "filename": item.get("filename"),
                        "score": item.get("score"),
                        "exportState": item.get("exportState"),
                    }
                    for item in ranking
                ],
            }
            self._record_event(
                "make_batch_completed",
                campaign_id=imported["campaign"]["id"],
                pipeline_job_id=pipeline_job["id"],
                status="success",
                message=f"Make batch completed: {campaign_slug}",
                metadata={
                    "importedCount": len(imported.get("imported") or []),
                    "syncedCount": (result.get("sync") or {}).get("syncedCount"),
                    "reviewReadyCount": len(result["reviewReady"]),
                    "draftCount": (result.get("dryRunExport") or {}).get("draftCount"),
                },
            )
            self._finish_pipeline_job(
                pipeline_job["id"],
                {
                    "campaign": campaign_slug,
                    "importedCount": len(imported.get("imported") or []),
                    "syncedCount": (result.get("sync") or {}).get("syncedCount"),
                    "reviewReadyCount": len(result["reviewReady"]),
                    "draftCount": (result.get("dryRunExport") or {}).get("draftCount"),
                },
            )
            return result
        except Exception as exc:
            self._record_event(
                "make_batch_failed",
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Make batch failed: {exc}",
                metadata={"error": str(exc)},
            )
            self._fail_pipeline_job(pipeline_job["id"], str(exc))
            raise

    def run_slideshow_pack(
        self,
        *,
        campaign_slug: str,
        variant_count: int,
        title: str,
        cluster_key: str | None = None,
        media_types: set[str] | None = None,
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        model_slug = self._model_slug_for_campaign(campaign["id"])
        dirs = self._campaign_dirs(model_slug, campaign["slug"])
        desired_types = media_types or {"image", "video"}
        sources = [
            asset
            for asset in self._assets_for_campaign(campaign["id"])
            if asset.get("media_type") in desired_types
        ]
        if not sources:
            raise ValueError(
                "no imported image/video sources available for slideshow pack"
            )
        selection = self._select_reference_pattern(
            campaign_slug,
            cluster_key=cluster_key,
            variant_count=variant_count,
            notes="make-batch slideshow reference pattern",
        )
        hooks = [str(item.get("text") or item) for item in selection.get("hooks") or []]
        stamp = re.sub(r"[^0-9A-Za-z]+", "_", self._utc_now()).strip("_")
        out_dir = dirs["rendered"] / f"slideshow_pack_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        media_dir = out_dir / "input_media"
        media_dir.mkdir(parents=True, exist_ok=True)
        for source in sources:
            src_path = Path(source["stored_path"])
            if src_path.exists():
                shutil.copy2(src_path, media_dir / src_path.name)
        hooks_file = out_dir / "hooks.json"
        atomic_write_text(
            hooks_file,
            json.dumps({"hooks": hooks}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        seed = int(
            hashlib.sha256(
                f"{campaign_slug}:{variant_count}:{selection['pattern']['clusterKey']}".encode()
            ).hexdigest()[:8],
            16,
        )
        generation_id = self._new_id("slidegen")
        cmd = [
            self._reel_factory_python(self.settings.reel_factory_root),
            "-m",
            "reel_factory.slideshow_factory",
            "--media-dir",
            str(media_dir),
            "--out-dir",
            str(out_dir),
            "--title",
            title,
            "--hooks-file",
            str(hooks_file),
            "--count",
            str(max(1, variant_count)),
            "--seed",
            str(seed),
            "--reference-pattern-id",
            selection["pattern"]["id"],
            "--generation-id",
            generation_id,
        ]
        started = time.time()
        result = self._subprocess_run(
            cmd,
            cwd=self.settings.reel_factory_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-2000:] or "slideshow_factory failed")
        manifest_path = out_dir / "slideshow_manifest.json"
        manifest = json_load(manifest_path.read_text(encoding="utf-8"), {})
        reel_path = Path(manifest.get("reel_path") or "")
        if not reel_path.exists():
            raise FileNotFoundError(f"slideshow reel missing: {reel_path}")
        digest = self._sha256_file(reel_path)
        existing = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], digest),
        ).fetchone()
        now = self._utc_now()
        source = sources[0]
        job_id = self._new_id("render")
        self.conn.execute(
            """
            INSERT INTO render_jobs
            (id, campaign_id, source_asset_id, reel_clip_stem, hooks_json, recipes_json, caption_color, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'rendered', ?, ?)
            """,
            (
                job_id,
                campaign["id"],
                source["id"],
                out_dir.name,
                json.dumps(hooks, ensure_ascii=False),
                json.dumps(["slideshow_pack"], ensure_ascii=False),
                "light",
                now,
                now,
            ),
        )
        prepared_assets = []
        if existing:
            prepared_assets.append(dict(existing))
        else:
            rendered_id = self._new_id("asset")
            self.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, render_job_id, content_hash, output_path, campaign_path, filename,
                 caption, caption_generation_json, recipe, target_ratio, review_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    rendered_id,
                    campaign["id"],
                    source["id"],
                    job_id,
                    digest,
                    str(reel_path),
                    str(reel_path),
                    reel_path.name,
                    title,
                    json.dumps(
                        {
                            "format": "slideshow_pack",
                            "schema": manifest.get("schema"),
                            "manifestPath": str(manifest_path),
                            "generationId": manifest.get("generation_id")
                            or generation_id,
                            "referencePattern": selection.get("pattern"),
                            "sourceHashes": [
                                item.get("source_hash")
                                for item in manifest.get("items", [])
                            ],
                            "captionHashes": [
                                hashlib.sha256(
                                    str(item.get("hook") or "")
                                    .strip()
                                    .lower()
                                    .encode("utf-8")
                                ).hexdigest()
                                for item in manifest.get("items", [])
                            ],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "slideshow_pack",
                    "9:16",
                    now,
                    now,
                ),
            )
            prepared_assets.append(
                dict(
                    self.conn.execute(
                        "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
                    ).fetchone()
                )
            )
            self._record_event(
                "rendered_asset_synced",
                campaign_id=campaign["id"],
                source_asset_id=source["id"],
                rendered_asset_id=rendered_id,
                render_job_id=job_id,
                status="success",
                message=f"Slideshow pack rendered: {reel_path.name}",
                metadata={
                    "format": "slideshow_pack",
                    "manifestPath": str(manifest_path),
                    "contentHash": digest,
                },
                commit=False,
            )
        self.conn.commit()
        return {
            "schema": "campaign_factory.slideshow_pack.v1",
            "campaign": campaign_slug,
            "selection": selection,
            "prepare": {"prepared": prepared_assets, "reusedExisting": []},
            "run": {
                "returncode": result.returncode,
                "runCount": 1,
                "elapsedSeconds": round(time.time() - started, 2),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "manifestPath": str(manifest_path),
            },
        }

    def campaign_source_media_summary(self, campaign_id: str) -> dict[str, int]:
        summary = {"video": 0, "image": 0}
        for source in self._assets_for_campaign(campaign_id):
            media_type = source.get("media_type") or self._media_type_for_path(
                source.get("stored_path") or source.get("filename") or ""
            )
            if media_type in summary:
                summary[media_type] += 1
        return summary

    def formats_for_batch(
        self, selected_format: str, source_mix: dict[str, int]
    ) -> list[str]:
        if selected_format == "reel":
            if not source_mix.get("video"):
                raise ValueError("reel format requires at least one imported video")
            return ["reel"]
        if selected_format == "slideshow":
            if not (source_mix.get("image") or source_mix.get("video")):
                raise ValueError(
                    "slideshow format requires at least one imported image or video"
                )
            return ["slideshow"]
        formats: list[str] = []
        if source_mix.get("video"):
            formats.append("reel")
        if source_mix.get("image"):
            formats.append("slideshow")
        if not formats:
            raise ValueError("no supported video or image sources imported")
        return formats
