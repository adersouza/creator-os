from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .config import Settings


def _json_dict(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
    if payload.get("schema") != "reel_factory.review_batch_package.v1":
        return False
    rows = payload.get("rows")
    guard = payload.get("guard") if isinstance(payload.get("guard"), dict) else {}
    return bool(
        isinstance(rows, list)
        and guard.get("status") == "ready"
        and not guard.get("blockingReasons")
        and payload.get("count") == len(rows)
        and guard.get("count") == len(rows)
    )


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
        self._enforce_reel_review_batch_package(folder)
        model = self._upsert_model(model_slug, model_name)
        campaign = self._upsert_campaign(campaign_slug, model["slug"], platform=platform)
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
                        metadata={"path": str(src), "contentHash": digest, "existingSourceAssetId": existing["id"]},
                        commit=False,
                    )
                    continue
                dest_name = f"{self._slugify(src.stem)}_{digest[:10]}{src.suffix.lower()}"
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
                imported_asset = dict(self.conn.execute("SELECT * FROM source_assets WHERE id = ?", (source_id,)).fetchone())
                source_graph_id = self._ensure_graph_node(
                    "source_asset",
                    local_table="source_assets",
                    local_id=source_id,
                    payload={"campaignId": campaign["id"], "contentHash": digest, "filename": dest.name, "mediaType": media_type},
                )
                self._ensure_graph_edge(
                    self._graph_id_for("campaigns", campaign["id"], entity_type="campaign", payload={"slug": campaign["slug"]}),
                    source_graph_id,
                    "campaign_contains_source_asset",
                    evidence={"importedFrom": str(src), "pipelineJobId": pipeline_job["id"]},
                )
                imported.append(imported_asset)
                self._record_event(
                    "source_imported",
                    campaign_id=campaign["id"],
                    source_asset_id=source_id,
                    pipeline_job_id=pipeline_job["id"],
                    status="success",
                    message=f"Source imported: {dest.name}",
                    metadata={"originalPath": str(src), "storedPath": str(dest), "contentHash": digest, "mediaType": media_type},
                    commit=False,
                )
            result = {"imported": imported, "duplicates": duplicates, "ignored": ignored, "campaign": campaign, "model": model}
            self._record_event(
                "source_imported",
                campaign_id=campaign["id"],
                pipeline_job_id=pipeline_job["id"],
                status="success" if imported else ("warning" if duplicates or ignored else "info"),
                message=f"Import complete: {len(imported)} imported, {len(duplicates)} duplicates, {len(ignored)} ignored",
                metadata={"importedCount": len(imported), "duplicateCount": len(duplicates), "ignoredCount": len(ignored)},
                commit=False,
            )
            self.conn.commit()
            self._finish_pipeline_job(pipeline_job["id"], {
                "importedCount": len(imported),
                "duplicateCount": len(duplicates),
                "ignoredCount": len(ignored),
            })
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

    def _enforce_reel_review_batch_package(self, folder: Path) -> None:
        raw_manifests = [path for path in folder.glob("*.json") if _is_reel_review_manifest(path)]
        if not raw_manifests:
            return
        packages = [path for path in folder.glob("*.json") if _is_guarded_review_package(path)]
        if packages:
            return
        raise ValueError(
            "Campaign Factory intake requires a guard-passed Reel Factory review package; "
            "run scripts/run/reel-factory review-guard <manifest> --write-package inside the batch folder."
        )

    def assets_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM source_assets WHERE campaign_id = ? ORDER BY created_at", (campaign_id,)).fetchall()
        assets = []
        for row in rows:
            item = dict(row)
            item["media_type"] = item.get("media_type") or self._media_type_for_path(item.get("stored_path") or item.get("filename") or "")
            assets.append(item)
        return assets
