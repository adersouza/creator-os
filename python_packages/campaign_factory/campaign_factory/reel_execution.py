from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .caption_outcome import build_caption_outcome_context, load_context_json
from .config import Settings
from .persistence import json_load


def _normalized_ids(values: list[str], name: str) -> list[str]:
    normalized = [str(value).strip() for value in values]
    if not normalized or any(not value for value in normalized):
        raise ValueError(f"{name} must contain at least one non-empty id")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicate ids")
    return normalized


class ReelExecutionRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        new_id: Callable[[str], str],
        utc_now: Callable[[], str],
        sha256_file: Callable[[Any], str],
        sanitize_for_storage: Callable[[Any], Any],
        text_hash: Callable[[str], str],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        assets_for_campaign: Callable[[str], list[dict[str, Any]]],
        campaign_dirs: Callable[[str, str], dict[str, Any]],
        reel_factory_python: Callable[[Path], str],
        create_pipeline_job: Callable[..., dict[str, Any]],
        start_pipeline_job: Callable[[str], dict[str, Any]],
        finish_pipeline_job: Callable[..., dict[str, Any]],
        fail_pipeline_job: Callable[..., dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        graph_id_for: Callable[..., str | None],
        discoverability_generation_gate: Callable[[dict[str, Any]], dict[str, Any]],
        capture_discoverability_gate_rejection_evidence: Callable[..., dict[str, Any]],
        suggest_simple_instagram_post_caption: Callable[..., str],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._new_id = new_id
        self._utc_now = utc_now
        self._sha256_file = sha256_file
        self._sanitize_for_storage = sanitize_for_storage
        self._text_hash = text_hash
        self._campaign_by_slug = campaign_by_slug
        self._assets_for_campaign = assets_for_campaign
        self._campaign_dirs = campaign_dirs
        self._reel_factory_python = reel_factory_python
        self._create_pipeline_job = create_pipeline_job
        self._start_pipeline_job = start_pipeline_job
        self._finish_pipeline_job = finish_pipeline_job
        self._fail_pipeline_job = fail_pipeline_job
        self._record_event = record_event
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._graph_id_for = graph_id_for
        self._discoverability_generation_gate = discoverability_generation_gate
        self._capture_discoverability_gate_rejection_evidence = (
            capture_discoverability_gate_rejection_evidence
        )
        self._suggest_simple_instagram_post_caption = (
            suggest_simple_instagram_post_caption
        )

    def prepare_reel_inputs(
        self,
        *,
        campaign_slug: str,
        hooks: list[str | dict[str, Any]],
        recipes: list[str] | None = None,
        caption_color: str | None = None,
        notes: str | None = None,
        force_new: bool = False,
        source_asset_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if not hooks:
            raise ValueError("at least one hook is required")
        campaign = self._campaign_by_slug(campaign_slug)
        pipeline_job = self._create_pipeline_job(
            "prepare_reel",
            campaign["id"],
            {
                "campaign": campaign_slug,
                "hookCount": len(hooks),
                "recipes": recipes or [],
                "captionColor": caption_color or "auto",
                "notes": notes,
                "forceNew": force_new,
                "sourceAssetIds": source_asset_ids or [],
            },
        )
        self._start_pipeline_job(pipeline_job["id"])
        try:
            sources = [
                source
                for source in self._assets_for_campaign(campaign["id"])
                if source.get("media_type") == "video"
            ]
            if source_asset_ids is not None:
                requested = _normalized_ids(source_asset_ids, "source_asset_ids")
                by_id = {str(source["id"]): source for source in sources}
                missing = [
                    source_id for source_id in requested if source_id not in by_id
                ]
                if missing:
                    raise ValueError(
                        "video source assets not found in campaign: "
                        + ", ".join(missing)
                    )
                sources = [by_id[source_id] for source_id in requested]
            if not sources:
                raise ValueError(
                    "no video sources available for reel input preparation"
                )
            raw_dir = self.settings.reel_factory_root / "00_source_videos"
            cap_dir = self.settings.reel_factory_root / "01_captions"
            raw_dir.mkdir(parents=True, exist_ok=True)
            cap_dir.mkdir(parents=True, exist_ok=True)
            prepared = []
            reused_existing = []
            next_num = self.next_reel_clip_number(raw_dir)
            for source_index, source in enumerate(sources):
                existing = self.conn.execute(
                    """SELECT * FROM render_jobs WHERE source_asset_id = ?
                    ORDER BY created_at DESC LIMIT 1""",
                    (source["id"],),
                ).fetchone()
                if existing and not force_new:
                    reused_existing.append(dict(existing))
                    continue
                clip_stem = f"clip_{next_num:03d}"
                next_num += 1
                src_path = Path(source["stored_path"])
                source_hooks = self.rotate_hooks_for_source(hooks, source_index)
                generation_gate = self._discoverability_generation_gate(
                    {"hook": source_hooks}
                )
                if not generation_gate["canProceed"]:
                    capture = self._capture_discoverability_gate_rejection_evidence(
                        gate_result=generation_gate,
                        failed_stage="discoverability_generation_gate",
                        campaign_id=campaign["id"],
                        source_asset_id=source["id"],
                        content_surface="reel",
                        commit=False,
                    )
                    self._record_event(
                        "discoverability_generation_blocked",
                        campaign_id=campaign["id"],
                        source_asset_id=source["id"],
                        pipeline_job_id=pipeline_job["id"],
                        status="warning",
                        message=f"Render input blocked by discoverability generation gate: {source['id']}",
                        metadata={"capturedCount": capture["capturedCount"]},
                        commit=False,
                    )
                    self.conn.commit()
                    self._finish_pipeline_job(
                        pipeline_job["id"],
                        {
                            "preparedCount": len(prepared),
                            "blockedAt": "discoverability_generation_gate",
                        },
                    )
                    return {
                        "campaign": campaign,
                        "prepared": prepared,
                        "reusedExisting": reused_existing,
                        "canProceed": False,
                        "blockedAt": "discoverability_generation_gate",
                        "discoverabilityGate": generation_gate,
                        "rejectionEvidenceCapture": capture,
                        "pipelineJobId": pipeline_job["id"],
                    }
                reel_video = raw_dir / f"{clip_stem}.mp4"
                shutil.copy2(src_path, reel_video)
                render_hooks, hook_metadata = self.reel_sidecar_hooks(source_hooks)
                sidecar = {
                    "hooks": render_hooks,
                    "recipes": recipes or None,
                    "caption_color": caption_color or "auto",
                    "notes": notes or f"campaign_factory source {source['id']}",
                }
                if hook_metadata:
                    sidecar["hook_metadata"] = hook_metadata
                atomic_write_text(
                    (cap_dir / f"{clip_stem}.json"),
                    json.dumps(sidecar, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                job_id = self._new_id("render")
                now = self._utc_now()
                self.conn.execute(
                    """
                    INSERT INTO render_jobs
                    (id, campaign_id, source_asset_id, reel_clip_stem, hooks_json, recipes_json, caption_color, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)
                    """,
                    (
                        job_id,
                        campaign["id"],
                        source["id"],
                        clip_stem,
                        json.dumps(source_hooks, ensure_ascii=False),
                        json.dumps(recipes or []),
                        caption_color,
                        now,
                        now,
                    ),
                )
                render_graph_id = self._ensure_graph_node(
                    "render_job",
                    local_table="render_jobs",
                    local_id=job_id,
                    payload={
                        "campaignId": campaign["id"],
                        "sourceAssetId": source["id"],
                        "clip": clip_stem,
                        "recipes": recipes or [],
                    },
                )
                self._ensure_graph_edge(
                    self._graph_id_for(
                        "source_assets", source["id"], entity_type="source_asset"
                    ),
                    render_graph_id,
                    "source_asset_to_render_job",
                    evidence={"clip": clip_stem, "pipelineJobId": pipeline_job["id"]},
                )
                prepared.append(
                    dict(
                        self.conn.execute(
                            "SELECT * FROM render_jobs WHERE id = ?", (job_id,)
                        ).fetchone()
                    )
                )
            result = {
                "campaign": campaign,
                "prepared": prepared,
                "reusedExisting": reused_existing,
            }
            self._record_event(
                "reel_inputs_prepared",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="success",
                message=f"Prepared reel inputs for {len(prepared)} sources",
                metadata={
                    "sourceCount": len(sources),
                    "preparedCount": len(prepared),
                    "reusedExistingCount": len(reused_existing),
                    "hookCount": len(hooks),
                    "recipes": recipes or [],
                    "captionColor": caption_color or "auto",
                    "forceNew": force_new,
                    "sourceAssetIds": source_asset_ids or [],
                },
                commit=False,
            )
            self.conn.commit()
            self._finish_pipeline_job(
                pipeline_job["id"],
                {
                    "preparedCount": len(prepared),
                    "reusedExistingCount": len(reused_existing),
                    "sourceCount": len(sources),
                },
            )
            result["pipelineJobId"] = pipeline_job["id"]
            return result
        except Exception as exc:
            self._record_event(
                "reel_inputs_prepared",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Prepare reel inputs failed: {exc}",
                metadata={"error": str(exc)},
            )
            self._fail_pipeline_job(pipeline_job["id"], str(exc))
            raise

    def rotate_hooks_for_source(
        self, hooks: list[str | dict[str, Any]], source_index: int
    ) -> list[str | dict[str, Any]]:
        if len(hooks) <= 1:
            return list(hooks)
        offset = source_index % len(hooks)
        return [*hooks[offset:], *hooks[:offset]]

    def reel_sidecar_hooks(
        self, hooks: list[str | dict[str, Any]]
    ) -> tuple[list[str | dict[str, Any]], list[dict[str, Any]]]:
        render_hooks: list[str | dict[str, Any]] = []
        hook_metadata: list[dict[str, Any]] = []
        for idx, hook in enumerate(hooks):
            if isinstance(hook, dict):
                if "segments" in hook:
                    render_hooks.append(hook)
                else:
                    render_hooks.append(str(hook.get("text") or "").strip())
                metadata = dict(hook)
                metadata["hookIndex"] = idx
                hook_metadata.append(metadata)
            else:
                render_hooks.append(hook)
        return render_hooks, hook_metadata

    def next_reel_clip_number(self, raw_dir: Path) -> int:
        nums = []
        for path in raw_dir.glob("clip_*.mp4"):
            try:
                nums.append(int(path.stem.split("_")[-1]))
            except ValueError:
                pass
        return max(nums, default=0) + 1

    def run_reel_factory(
        self,
        *,
        campaign_slug: str,
        workers: int = 3,
        dry_run: bool = False,
        caption_band: str = "auto",
        caption_color: str = "light",
        caption_style: str = "ig",
        caption_font: str = "Instagram Sans Condensed",
        caption_placement_qc: bool = True,
        phone_finalize: bool = True,
        rerender_all: bool = False,
        max_outputs_per_clip: int | None = None,
        render_job_ids: list[str] | None = None,
        caption_mix: str | None = None,
        creator_style_preset: str | None = None,
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        pipeline_job = self._create_pipeline_job(
            "run_reel",
            campaign["id"],
            {
                "campaign": campaign_slug,
                "workers": workers,
                "dryRun": dry_run,
                "captionBand": caption_band,
                "captionColor": caption_color,
                "captionStyle": caption_style,
                "captionFont": caption_font,
                "captionPlacementQc": caption_placement_qc,
                "phoneFinalize": phone_finalize,
                "rerenderAll": rerender_all,
                "maxOutputsPerClip": max_outputs_per_clip,
                "renderJobIds": render_job_ids or [],
                "captionMix": caption_mix,
                "creatorStylePreset": creator_style_preset,
            },
        )
        self._start_pipeline_job(pipeline_job["id"])
        started = time.time()
        try:
            all_jobs = self.conn.execute(
                "SELECT * FROM render_jobs WHERE campaign_id = ? ORDER BY created_at",
                (campaign["id"],),
            ).fetchall()
            if render_job_ids is not None:
                requested = _normalized_ids(render_job_ids, "render_job_ids")
                by_id = {str(job["id"]): job for job in all_jobs}
                missing = [job_id for job_id in requested if job_id not in by_id]
                if missing:
                    raise ValueError(
                        "render jobs not found in campaign: " + ", ".join(missing)
                    )
                jobs = [by_id[job_id] for job_id in requested]
                if not rerender_all:
                    invalid = [
                        str(job["id"])
                        for job in jobs
                        if job["status"] not in ("prepared", "failed")
                    ]
                    if invalid:
                        raise ValueError(
                            "render jobs are not runnable without rerender_all: "
                            + ", ".join(invalid)
                        )
            elif rerender_all:
                jobs = all_jobs
            else:
                jobs = [
                    job for job in all_jobs if job["status"] in ("prepared", "failed")
                ]
            runs: list[dict[str, Any]] = []
            for job in jobs:
                cmd = [
                    self._reel_factory_python(self.settings.reel_factory_root),
                    "-m",
                    "reel_factory.reel_pipeline",
                    "--root",
                    str(self.settings.reel_factory_root),
                    "--workers",
                    str(workers),
                    "--only-clip",
                    job["reel_clip_stem"],
                ]
                recipes = json_load(job["recipes_json"], [])
                if recipes:
                    cmd.extend(["--recipes", *recipes])
                color = caption_color or job["caption_color"]
                if color:
                    cmd.extend(["--color", color])
                if caption_band:
                    cmd.extend(["--band", caption_band])
                if caption_style:
                    cmd.extend(["--style", caption_style])
                if caption_font:
                    cmd.extend(["--font", caption_font])
                if caption_mix:
                    cmd.extend(["--caption-mix", caption_mix])
                if creator_style_preset:
                    cmd.extend(["--creator-style-preset", creator_style_preset])
                if caption_placement_qc:
                    cmd.append("--caption-placement-qc")
                if max_outputs_per_clip is not None:
                    cmd.extend(["--per-clip", str(max(1, int(max_outputs_per_clip)))])
                cmd.append(
                    "--phone-finalize" if phone_finalize else "--no-phone-finalize"
                )
                if dry_run:
                    cmd.append("--dry-run")
                if rerender_all:
                    cmd.append("--rerender-all")
                self._record_event(
                    "reel_render_started",
                    campaign_id=campaign["id"],
                    source_asset_id=job["source_asset_id"],
                    render_job_id=job["id"],
                    pipeline_job_id=pipeline_job["id"],
                    status="info",
                    message=f"Started reel render for {job['reel_clip_stem']}",
                    metadata={"clip": job["reel_clip_stem"], "command": cmd},
                    commit=False,
                )
                result = subprocess.run(
                    cmd,
                    cwd=self.settings.reel_factory_root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                status = (
                    job["status"]
                    if dry_run and result.returncode == 0
                    else ("rendered" if result.returncode == 0 else "failed")
                )
                error = result.stderr[-2000:] or None
                now = self._utc_now()
                self.conn.execute(
                    "UPDATE render_jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                    (status, error, now, job["id"]),
                )
                self._record_event(
                    "reel_render_completed"
                    if result.returncode == 0
                    else "reel_render_failed",
                    campaign_id=campaign["id"],
                    source_asset_id=job["source_asset_id"],
                    render_job_id=job["id"],
                    pipeline_job_id=pipeline_job["id"],
                    status="success" if result.returncode == 0 else "failure",
                    message=f"{'Completed' if result.returncode == 0 else 'Failed'} reel render for {job['reel_clip_stem']}",
                    metadata={
                        "clip": job["reel_clip_stem"],
                        "returncode": result.returncode,
                        "stderr": error,
                    },
                    commit=False,
                )
                runs.append(
                    {
                        "renderJobId": job["id"],
                        "clip": job["reel_clip_stem"],
                        "command": cmd,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
            self.conn.commit()
            returncode = next(
                (run["returncode"] for run in runs if run["returncode"] != 0), 0
            )
            result_payload = {
                "campaign": campaign,
                "returncode": returncode,
                "runs": runs,
                "elapsed_seconds": round(time.time() - started, 2),
                "pipelineJobId": pipeline_job["id"],
            }
            if returncode == 0:
                self._finish_pipeline_job(
                    pipeline_job["id"],
                    {
                        "returncode": returncode,
                        "runCount": len(runs),
                        "elapsed_seconds": result_payload["elapsed_seconds"],
                    },
                )
            else:
                self._fail_pipeline_job(
                    pipeline_job["id"],
                    f"reel_factory returned {returncode}",
                    {
                        "returncode": returncode,
                        "runCount": len(runs),
                        "elapsed_seconds": result_payload["elapsed_seconds"],
                    },
                )
            return result_payload
        except Exception as exc:
            self._record_event(
                "reel_render_failed",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Run reel_factory failed: {exc}",
                metadata={"error": str(exc)},
            )
            self._fail_pipeline_job(pipeline_job["id"], str(exc))
            raise

    def sync_reel_outputs(
        self, *, campaign_slug: str, render_job_ids: list[str] | None = None
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        pipeline_job = self._create_pipeline_job(
            "sync_reel",
            campaign["id"],
            {"campaign": campaign_slug, "renderJobIds": render_job_ids or []},
        )
        self._start_pipeline_job(pipeline_job["id"])
        model_slug = self.model_slug_for_campaign(campaign["id"])
        dirs = self._campaign_dirs(model_slug, campaign["slug"])
        manifest_db = self.settings.reel_manifest_db
        reel_conn: sqlite3.Connection | None = None
        try:
            if not manifest_db.exists():
                raise FileNotFoundError(
                    f"reel_factory manifest not found: {manifest_db}"
                )
            reel_conn = sqlite3.connect(manifest_db)
            reel_conn.row_factory = sqlite3.Row
            variation_cols = {
                row["name"]
                for row in reel_conn.execute("PRAGMA table_info(variations)").fetchall()
            }
            clip_col = "video_id" if "video_id" in variation_cols else "clip"
            jobs = self.conn.execute(
                "SELECT * FROM render_jobs WHERE campaign_id = ?", (campaign["id"],)
            ).fetchall()
            if render_job_ids is not None:
                requested = _normalized_ids(render_job_ids, "render_job_ids")
                by_id = {str(job["id"]): job for job in jobs}
                missing = [job_id for job_id in requested if job_id not in by_id]
                if missing:
                    raise ValueError(
                        "render jobs not found in campaign: " + ", ".join(missing)
                    )
                jobs = [by_id[job_id] for job_id in requested]
            synced = []
            new_synced = 0
            for job in jobs:
                rows = reel_conn.execute(
                    f"""
                    SELECT job_key, recipe, recipe_params_json, caption_text, output_path
                    FROM variations
                    WHERE {clip_col} = ? AND status = 'ok'
                    ORDER BY encoded_at, output_path
                    """,
                    (job["reel_clip_stem"],),
                ).fetchall()
                for row in rows:
                    output_path = Path(row["output_path"])
                    if not output_path.exists():
                        continue
                    digest = self._sha256_file(output_path)
                    params = json_load(row["recipe_params_json"], {})
                    reel_lineage = (
                        params.get("_lineage")
                        if isinstance(params.get("_lineage"), dict)
                        else {}
                    )
                    existing = self.conn.execute(
                        "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
                        (campaign["id"], digest),
                    ).fetchone()
                    if existing:
                        self.backfill_synced_reel_output_lineage(
                            asset=dict(existing),
                            clip_stem=job["reel_clip_stem"],
                            caption_text=str(row["caption_text"] or "").strip(),
                            recipe=str(row["recipe"] or ""),
                            output_path=str(output_path),
                            rendered_path=str(
                                existing["campaign_path"]
                                or existing["output_path"]
                                or output_path
                            ),
                            creator_model=model_slug,
                            lineage=reel_lineage,
                        )
                        refreshed = self.conn.execute(
                            "SELECT * FROM rendered_assets WHERE id = ?",
                            (existing["id"],),
                        ).fetchone()
                        synced.append(dict(refreshed or existing))
                        continue
                    dest = dirs["rendered"] / output_path.name
                    if output_path.resolve() != dest.resolve():
                        shutil.copy2(output_path, dest)
                    rendered_id = self._new_id("asset")
                    now = self._utc_now()
                    caption_text = str(row["caption_text"] or "").strip()
                    caption_hash_value = (
                        self._text_hash(caption_text) if caption_text else None
                    )
                    caption_generation = self.caption_generation_for_clip(
                        job["reel_clip_stem"]
                    )
                    lineage = {**caption_generation, **reel_lineage}
                    caption_context = self.caption_outcome_context_for_reel_output(
                        clip_stem=job["reel_clip_stem"],
                        caption_text=caption_text,
                        caption_hash=caption_hash_value,
                        recipe=str(row["recipe"] or ""),
                        source_path=str(output_path),
                        rendered_path=str(dest),
                        creator_model=model_slug,
                        lineage=lineage,
                    )
                    if caption_generation.get("audioIntent") is None:
                        audio_intent = self.audio_intent_from_reference_recommendations(
                            caption_generation, now=now
                        )
                        if audio_intent:
                            caption_generation["audioIntent"] = audio_intent
                    if caption_text:
                        post_caption = self._suggest_simple_instagram_post_caption(
                            asset_id=rendered_id,
                            current_caption="",
                            burned_caption=caption_text,
                        )
                        caption_context["instagram_post_caption"] = post_caption
                        caption_context["instagram_post_caption_hash"] = (
                            self._text_hash(post_caption)
                        )
                        caption_context["burned_caption_text"] = caption_text
                        caption_context["burned_caption_hash"] = caption_hash_value
                        caption_generation["instagramPostCaption"] = {
                            "instagram_post_caption": post_caption,
                            "instagramPostCaption": post_caption,
                            "instagram_post_caption_hash": self._text_hash(
                                post_caption
                            ),
                            "post_caption_style": "simple_native",
                            "hashtags": [],
                        }
                    caption_generation["captionHash"] = caption_hash_value
                    caption_generation["captionOutcomeContext"] = caption_context
                    self.conn.execute(
                        """
                        INSERT INTO rendered_assets
                        (id, campaign_id, source_asset_id, render_job_id, content_hash, output_path, campaign_path, filename,
                         caption, caption_hash, caption_bank, caption_banks_json, creator_mix, creator_model, frame_type,
                         length_class, format_class, caption_fit_version, suitability_decision, suitability_reason,
                         source_clip, caption_outcome_context_json, caption_generation_json, recipe, target_ratio,
                         review_state, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rendered_id,
                            campaign["id"],
                            job["source_asset_id"],
                            job["id"],
                            digest,
                            str(output_path),
                            str(dest),
                            dest.name,
                            caption_text,
                            caption_hash_value,
                            caption_context.get("caption_bank"),
                            json.dumps(
                                caption_context.get("caption_banks") or [],
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            caption_context.get("creator_mix"),
                            caption_context.get("creator_model"),
                            caption_context.get("frame_type"),
                            caption_context.get("length_class"),
                            caption_context.get("format_class"),
                            caption_context.get("caption_fit_version"),
                            caption_context.get("suitability_decision"),
                            caption_context.get("suitability_reason"),
                            caption_context.get("source_clip"),
                            json.dumps(
                                caption_context, ensure_ascii=False, sort_keys=True
                            ),
                            json.dumps(
                                self._sanitize_for_storage(caption_generation),
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            row["recipe"],
                            params.get("_target_ratio")
                            or self.ratio_from_filename(dest.name),
                            "draft",
                            now,
                            now,
                        ),
                    )
                    synced_asset = dict(
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
                            "sourceAssetId": job["source_asset_id"],
                            "renderJobId": job["id"],
                            "contentHash": digest,
                            "filename": dest.name,
                            "recipe": row["recipe"],
                        },
                    )
                    self._ensure_graph_edge(
                        self._graph_id_for(
                            "render_jobs", job["id"], entity_type="render_job"
                        ),
                        rendered_graph_id,
                        "render_job_to_rendered_asset",
                        evidence={
                            "jobKey": row["job_key"],
                            "pipelineJobId": pipeline_job["id"],
                        },
                    )
                    self._ensure_graph_edge(
                        self._graph_id_for(
                            "source_assets",
                            job["source_asset_id"],
                            entity_type="source_asset",
                        ),
                        rendered_graph_id,
                        "source_asset_to_rendered_asset",
                        evidence={
                            "recipe": row["recipe"],
                            "pipelineJobId": pipeline_job["id"],
                        },
                    )
                    synced.append(synced_asset)
                    new_synced += 1
                    self._record_event(
                        "rendered_asset_synced",
                        campaign_id=campaign["id"],
                        source_asset_id=job["source_asset_id"],
                        rendered_asset_id=rendered_id,
                        render_job_id=job["id"],
                        pipeline_job_id=pipeline_job["id"],
                        status="success",
                        message=f"Rendered asset synced: {dest.name}",
                        metadata={
                            "filename": dest.name,
                            "contentHash": digest,
                            "recipe": row["recipe"],
                            "outputPath": str(output_path),
                        },
                        commit=False,
                    )
            result = {
                "campaign": campaign,
                "synced": synced,
                "pipelineJobId": pipeline_job["id"],
            }
            self.conn.commit()
            self._finish_pipeline_job(
                pipeline_job["id"],
                {"syncedCount": len(synced), "newSyncedCount": new_synced},
            )
            return result
        except Exception as exc:
            self._record_event(
                "rendered_asset_synced",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Sync rendered outputs failed: {exc}",
                metadata={"error": str(exc)},
            )
            self._fail_pipeline_job(pipeline_job["id"], str(exc))
            raise
        finally:
            if reel_conn:
                reel_conn.close()

    def model_slug_for_campaign(self, campaign_id: str) -> str:
        row = self.conn.execute(
            """
            SELECT m.slug FROM source_assets s
            JOIN models m ON m.id = s.model_id
            WHERE s.campaign_id = ?
            LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        return row["slug"] if row else "unassigned"

    def ratio_from_filename(self, filename: str) -> str:
        return "4:5" if "_4x5_" in filename else "9:16"

    def caption_generation_for_clip(self, clip_stem: str) -> dict[str, Any]:
        sidecar = self.settings.reel_factory_root / "01_captions" / f"{clip_stem}.json"
        if not sidecar.exists():
            return {}
        try:
            payload = json_load(sidecar.read_text(encoding="utf-8"), {})
        except OSError:
            return {}
        if not isinstance(payload, dict):
            return {}
        hook_metadata = (
            payload.get("hook_metadata")
            if isinstance(payload.get("hook_metadata"), list)
            else []
        )
        generation = payload.get("generation")
        if not isinstance(generation, dict):
            generation_payload = {}
        else:
            generation_payload = {
                "generationId": generation.get("generation_id")
                or generation.get("generationId"),
                "model": generation.get("model"),
                "backend": generation.get("backend"),
                "createdAt": generation.get("created_at")
                or generation.get("createdAt"),
                "promptHash": generation.get("prompt_hash")
                or generation.get("promptHash"),
                "captionHashes": generation.get("caption_hashes")
                or generation.get("captionHashes")
                or [],
                "quality": generation.get("quality") or [],
            }
        reference_meta = next(
            (
                item
                for item in hook_metadata
                if isinstance(item, dict) and item.get("referenceClusterKey")
            ),
            None,
        )
        if reference_meta:
            generation_payload["referencePattern"] = {
                "clusterKey": reference_meta.get("referenceClusterKey"),
                "label": reference_meta.get("referenceLabel"),
                "hookType": reference_meta.get("hookType"),
                "captionArchetype": reference_meta.get("captionArchetype"),
            }
            generation_payload["audioRecommendations"] = (
                reference_meta.get("audioRecommendations") or {}
            )
        return generation_payload

    def caption_outcome_context_for_reel_output(
        self,
        *,
        clip_stem: str,
        caption_text: str,
        caption_hash: str | None,
        recipe: str,
        source_path: str,
        rendered_path: str,
        creator_model: str,
        lineage: dict[str, Any],
    ) -> dict[str, Any]:
        context = build_caption_outcome_context(
            caption_text=caption_text,
            caption_hash=caption_hash,
            render_recipe=recipe,
            source_clip=source_path,
            rendered_output=rendered_path,
            creator_model=creator_model,
            lineage=lineage,
        )
        lineage_placement_decision = self.lineage_placement_decision(lineage)
        placement_policy = (
            context.get("captionPlacementPolicy")
            or self.lineage_first_present(lineage, "captionPlacementPolicy")
            or "focal_safe_v1"
        )
        placement_decision = context.get("captionPlacementDecision")
        if isinstance(
            lineage_placement_decision, dict
        ) and lineage_placement_decision.get("status") in {"passed", "failed"}:
            placement_decision = lineage_placement_decision
        elif not isinstance(placement_decision, dict) or not placement_decision.get(
            "status"
        ):
            placement_decision = lineage_placement_decision
        if not isinstance(placement_decision, dict) or not placement_decision.get(
            "status"
        ):
            placement_decision = {
                "status": "pending",
                "selectedLane": self.caption_lane_from_render_recipe(recipe),
                "reason": "ContentForge safe-zone review must pass before schedule-safe handoff.",
            }
        elif not placement_decision.get("selectedLane"):
            placement_decision = {
                **placement_decision,
                "selectedLane": self.caption_lane_from_render_recipe(recipe),
            }
        context.update(
            {
                "caption_bank": context.get("caption_bank") or "reel_factory_reference",
                "caption_banks": context.get("caption_banks")
                or ["reel_factory_reference"],
                "creator_mix": context.get("creator_mix") or creator_model,
                "creator_model": context.get("creator_model") or creator_model,
                "frame_type": context.get("frame_type") or "selfie_video",
                "length_class": context.get("length_class") or "short",
                "format_class": context.get("format_class") or "reel",
                "caption_fit_version": context.get("caption_fit_version")
                or "reel_factory_sync_v1",
                "suitability_decision": context.get("suitability_decision")
                or "allowed",
                "suitability_reason": context.get("suitability_reason")
                or "synced from Reel Factory output",
                "reel_clip_stem": clip_stem,
                "captionPlacementPolicy": placement_policy,
                "captionPlacementDecision": placement_decision,
            }
        )
        return context

    def lineage_first_present(self, lineage: dict[str, Any] | None, key: str) -> Any:
        if not isinstance(lineage, dict):
            return None
        candidates = [
            lineage,
            lineage.get("captionBank"),
            lineage.get("captionOutcomeContext"),
            lineage.get("captionLineage"),
            lineage.get("caption_lineage"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get(key) is not None:
                return candidate.get(key)
        return None

    def lineage_placement_decision(
        self, lineage: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not isinstance(lineage, dict):
            return None
        decisions: list[dict[str, Any]] = []
        for candidate in (
            lineage,
            lineage.get("captionBank"),
            lineage.get("captionOutcomeContext"),
            lineage.get("captionLineage"),
            lineage.get("caption_lineage"),
        ):
            if not isinstance(candidate, dict):
                continue
            decision = candidate.get("captionPlacementDecision")
            if isinstance(decision, dict):
                decisions.append(decision)
        for decision in decisions:
            if decision.get("status") in {"passed", "failed"}:
                return decision
        return decisions[0] if decisions else None

    def caption_lane_from_render_recipe(self, recipe: str | None) -> str:
        raw = str(recipe or "").lower()
        if "top" in raw:
            return "top"
        if "caption_bg" in raw or "bottom" in raw:
            return "bottom"
        return "center"

    def audio_intent_from_reference_recommendations(
        self, payload: dict[str, Any], *, now: str
    ) -> dict[str, Any]:
        recommendations = (payload.get("audioRecommendations") or {}).get(
            "recommendations"
        )
        if not isinstance(recommendations, list):
            recommendations = []
        selected = next(
            (
                item
                for item in recommendations
                if isinstance(item, dict) and str(item.get("audioId") or "").strip()
            ),
            None,
        )
        if not selected:
            return {
                "schema": "pipeline.audio_intent.v1",
                "mode": "native_platform_audio",
                "required": True,
                "status": "missing",
                "platform": "instagram",
                "source": "reference_audio_recommendations",
                "operator_selection": {},
            }
        audio_id = str(selected.get("audioId") or "").strip()
        audio_title = str(
            selected.get("audioTitle") or selected.get("title") or ""
        ).strip()
        artist = str(
            selected.get("artistName") or selected.get("artist_name") or ""
        ).strip()
        return {
            "schema": "pipeline.audio_intent.v1",
            "mode": "native_platform_audio",
            "required": True,
            "status": "attached",
            "platform": "instagram",
            "source": "reference_audio_recommendations",
            "operator_selection": {
                "audio_id": audio_id,
                "track_id": audio_id,
                "platform_audio_id": audio_id,
                "native_audio_id": audio_id,
                "audio_title": audio_title,
                "track_name": audio_title,
                "artist_name": artist,
                "source": "reference_audio_recommendations",
                "selection_source": "reference_audio_recommendations",
                "selected_reason": str(
                    selected.get("instruction")
                    or "reference pattern audio recommendation"
                ).strip(),
                "selected_at": now,
                "attached_at": now,
            },
            "gates": {
                "allow_draft_export": True,
                "allow_preview_schedule": True,
                "allow_live_schedule": False,
                "allow_publish": False,
            },
        }

    def backfill_synced_reel_output_lineage(
        self,
        *,
        asset: dict[str, Any],
        clip_stem: str,
        caption_text: str,
        recipe: str,
        output_path: str,
        rendered_path: str,
        creator_model: str,
        lineage: dict[str, Any] | None = None,
    ) -> bool:
        existing_context = load_context_json(asset.get("caption_outcome_context_json"))
        existing_generation = json_load(asset.get("caption_generation_json"), {})
        if not isinstance(existing_generation, dict):
            existing_generation = {}
        existing_decision = (
            existing_context.get("captionPlacementDecision")
            if isinstance(existing_context, dict)
            else {}
        )
        if (
            asset.get("caption_hash")
            and existing_context
            and isinstance(existing_generation.get("audioIntent"), dict)
            and isinstance(existing_decision, dict)
            and existing_decision.get("status") in {"passed", "failed"}
        ):
            return False
        now = self._utc_now()
        caption_hash_value = asset.get("caption_hash") or (
            self._text_hash(caption_text) if caption_text else None
        )
        reel_lineage = lineage if isinstance(lineage, dict) else {}
        caption_generation = {
            **self.caption_generation_for_clip(clip_stem),
            **reel_lineage,
            **existing_generation,
        }
        caption_context = self.caption_outcome_context_for_reel_output(
            clip_stem=clip_stem,
            caption_text=caption_text or str(asset.get("caption") or "").strip(),
            caption_hash=caption_hash_value,
            recipe=recipe or str(asset.get("recipe") or ""),
            source_path=output_path,
            rendered_path=rendered_path,
            creator_model=creator_model,
            lineage={**caption_generation, **existing_context},
        )
        if not isinstance(caption_generation.get("audioIntent"), dict):
            audio_intent = self.audio_intent_from_reference_recommendations(
                caption_generation, now=now
            )
            if audio_intent:
                caption_generation["audioIntent"] = audio_intent
        burned_caption = caption_text or str(asset.get("caption") or "").strip()
        if burned_caption:
            post_caption = self._suggest_simple_instagram_post_caption(
                asset_id=str(asset["id"]),
                current_caption="",
                burned_caption=burned_caption,
            )
            caption_context["instagram_post_caption"] = post_caption
            caption_context["instagram_post_caption_hash"] = self._text_hash(
                post_caption
            )
            caption_context["burned_caption_text"] = burned_caption
            caption_context["burned_caption_hash"] = caption_hash_value
            caption_generation["instagramPostCaption"] = {
                "instagram_post_caption": post_caption,
                "instagramPostCaption": post_caption,
                "instagram_post_caption_hash": self._text_hash(post_caption),
                "post_caption_style": "simple_native",
                "hashtags": [],
            }
        caption_generation["captionHash"] = caption_hash_value
        caption_generation["captionOutcomeContext"] = caption_context
        self.conn.execute(
            """
            UPDATE rendered_assets
            SET caption = COALESCE(NULLIF(caption, ''), ?),
                caption_hash = COALESCE(caption_hash, ?),
                caption_bank = COALESCE(NULLIF(caption_bank, ''), ?),
                caption_banks_json = CASE WHEN caption_banks_json IS NULL OR caption_banks_json = '' OR caption_banks_json = '[]' THEN ? ELSE caption_banks_json END,
                creator_mix = COALESCE(NULLIF(creator_mix, ''), ?),
                creator_model = COALESCE(NULLIF(creator_model, ''), ?),
                frame_type = COALESCE(NULLIF(frame_type, ''), ?),
                length_class = COALESCE(NULLIF(length_class, ''), ?),
                format_class = COALESCE(NULLIF(format_class, ''), ?),
                caption_fit_version = COALESCE(NULLIF(caption_fit_version, ''), ?),
                suitability_decision = COALESCE(NULLIF(suitability_decision, ''), ?),
                suitability_reason = COALESCE(NULLIF(suitability_reason, ''), ?),
                source_clip = COALESCE(NULLIF(source_clip, ''), ?),
                caption_outcome_context_json = ?,
                caption_generation_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                burned_caption,
                caption_hash_value,
                caption_context.get("caption_bank"),
                json.dumps(
                    caption_context.get("caption_banks") or [],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                caption_context.get("creator_mix"),
                caption_context.get("creator_model"),
                caption_context.get("frame_type"),
                caption_context.get("length_class"),
                caption_context.get("format_class"),
                caption_context.get("caption_fit_version"),
                caption_context.get("suitability_decision"),
                caption_context.get("suitability_reason"),
                caption_context.get("source_clip"),
                json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
                json.dumps(
                    self._sanitize_for_storage(caption_generation),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
                asset["id"],
            ),
        )
        return True
