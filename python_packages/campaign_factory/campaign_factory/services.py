from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from .asset_import import AssetImportRepository
from .config import Settings
from .events import EventRepository
from .graph import GraphRepository
from .models import ModelRepository


class CoreServices:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        new_id: Callable[[str], str],
        new_graph_id: Callable[[str], str],
        slugify: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        media_type_for_path: Callable[[Any], str],
        sha256_file: Callable[[Any], str],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._new_id = new_id
        self._new_graph_id = new_graph_id
        self._slugify = slugify
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now
        self.graph = GraphRepository(
            conn,
            new_id=new_id,
            new_graph_id=new_graph_id,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
        )
        self.events = EventRepository(
            conn,
            new_id=new_id,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
        )
        self.models = ModelRepository(
            conn,
            settings,
            new_id=new_id,
            slugify=slugify,
            utc_now=utc_now,
            ensure_graph_node=self.graph.ensure_graph_node,
            record_event=self.events.record_event,
        )
        self.asset_import = AssetImportRepository(
            conn,
            settings,
            new_id=new_id,
            slugify=slugify,
            utc_now=utc_now,
            media_type_for_path=media_type_for_path,
            sha256_file=sha256_file,
            upsert_model=self.models.upsert_model,
            upsert_campaign=self.models.upsert_campaign,
            upsert_account=self.models.upsert_account,
            create_pipeline_job=self.events.create_pipeline_job,
            start_pipeline_job=self.events.start_pipeline_job,
            finish_pipeline_job=self.events.finish_pipeline_job,
            fail_pipeline_job=self.events.fail_pipeline_job,
            record_event=self.events.record_event,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            graph_id_for=self.graph.graph_id_for,
        )

    def ensure_graph_node(
        self,
        entity_type: str,
        *,
        local_table: str | None = None,
        local_id: str | None = None,
        external_system: str | None = None,
        external_id: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> str:
        return self.graph.ensure_graph_node(
            entity_type,
            local_table=local_table,
            local_id=local_id,
            external_system=external_system,
            external_id=external_id,
            payload=payload,
            commit=commit,
        )

    def graph_id_for(
        self,
        local_table: str,
        local_id: str | None,
        *,
        entity_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str | None:
        return self.graph.graph_id_for(local_table, local_id, entity_type=entity_type, payload=payload)

    def ensure_graph_edge(
        self,
        from_global_id: str | None,
        to_global_id: str | None,
        relation_type: str,
        *,
        evidence: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> str | None:
        return self.graph.ensure_graph_edge(
            from_global_id,
            to_global_id,
            relation_type,
            evidence=evidence,
            commit=commit,
        )

    def set_graph_sync_state(self, system: str, cursor: dict[str, Any]) -> None:
        self.graph.set_sync_state(system, cursor)

    def record_event(
        self,
        event_type: str,
        *,
        campaign_id: str | None = None,
        source_asset_id: str | None = None,
        rendered_asset_id: str | None = None,
        render_job_id: str | None = None,
        audit_report_id: str | None = None,
        threadsdash_export_id: str | None = None,
        pipeline_job_id: str | None = None,
        status: str = "info",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.events.record_event(
            event_type,
            campaign_id=campaign_id,
            source_asset_id=source_asset_id,
            rendered_asset_id=rendered_asset_id,
            render_job_id=render_job_id,
            audit_report_id=audit_report_id,
            threadsdash_export_id=threadsdash_export_id,
            pipeline_job_id=pipeline_job_id,
            status=status,
            message=message,
            metadata=metadata,
            commit=commit,
        )

    def event_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.events.event_payload(row)

    def events_for_campaign(self, campaign_slug: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.events.events_for_campaign(campaign_slug, limit=limit)

    def events_for_asset(self, rendered_asset_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.events.events_for_asset(rendered_asset_id, limit=limit)

    def create_pipeline_job(
        self,
        job_type: str,
        campaign_id: str | None,
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.events.create_pipeline_job(job_type, campaign_id, input_payload)

    def start_pipeline_job(self, job_id: str) -> dict[str, Any]:
        return self.events.start_pipeline_job(job_id)

    def finish_pipeline_job(self, job_id: str, result_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.events.finish_pipeline_job(job_id, result_payload)

    def fail_pipeline_job(self, job_id: str, error: str, result_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.events.fail_pipeline_job(job_id, error, result_payload)

    def set_pipeline_job_campaign(self, job_id: str, campaign_id: str) -> dict[str, Any]:
        return self.events.set_pipeline_job_campaign(job_id, campaign_id)

    def pipeline_job(self, job_id: str) -> dict[str, Any]:
        return self.events.pipeline_job(job_id)

    def pipeline_job_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.events.pipeline_job_payload(row)

    def upsert_model(self, slug: str, name: str | None = None, notes: str | None = None) -> dict[str, Any]:
        return self.models.upsert_model(slug, name=name, notes=notes)

    def upsert_campaign(self, slug: str, model_slug: str, name: str | None = None, platform: str = "instagram") -> dict[str, Any]:
        return self.models.upsert_campaign(slug, model_slug, name=name, platform=platform)

    def upsert_account(
        self,
        handle: str,
        platform: str = "instagram",
        external_id: str | None = None,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        return self.models.upsert_account(handle, platform=platform, external_id=external_id, model_id=model_id)

    def upsert_model_account_profile(
        self,
        model_slug: str,
        *,
        label: str | None = None,
        allowed_instagram_account_ids: list[str] | None = None,
        allowed_account_group_names: list[str] | None = None,
        allowed_handle_patterns: list[str] | None = None,
        default_smart_link: str | None = None,
        story_cta_text: str | None = None,
    ) -> dict[str, Any]:
        return self.models.upsert_model_account_profile(
            model_slug,
            label=label,
            allowed_instagram_account_ids=allowed_instagram_account_ids,
            allowed_account_group_names=allowed_account_group_names,
            allowed_handle_patterns=allowed_handle_patterns,
            default_smart_link=default_smart_link,
            story_cta_text=story_cta_text,
        )

    def model_account_profile(self, model_slug: str) -> dict[str, Any] | None:
        return self.models.model_account_profile(model_slug)

    def account_compatible_with_model(
        self,
        model_slug: str,
        *,
        instagram_account_id: str | None = None,
        account_handle: str | None = None,
        account_group_name: str | None = None,
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        return self.models.account_compatible_with_model(
            model_slug,
            instagram_account_id=instagram_account_id,
            account_handle=account_handle,
            account_group_name=account_group_name,
        )

    def import_folder(
        self,
        folder: Any,
        *,
        campaign_slug: str,
        model_slug: str,
        model_name: str | None = None,
        platform: str = "instagram",
        account_handles: list[str] | None = None,
        source_prompt: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.asset_import.import_folder(
            folder,
            campaign_slug=campaign_slug,
            model_slug=model_slug,
            model_name=model_name,
            platform=platform,
            account_handles=account_handles,
            source_prompt=source_prompt,
            notes=notes,
        )

    def assets_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        return self.asset_import.assets_for_campaign(campaign_id)

    def campaign_by_slug(self, slug: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM campaigns WHERE slug = ?", (self._slugify(slug),)).fetchone()
        if not row:
            raise ValueError(f"campaign not found: {slug}")
        return dict(row)

    def rendered_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)).fetchone()
        if not row:
            raise ValueError(f"rendered asset not found: {rendered_asset_id}")
        return dict(row)
