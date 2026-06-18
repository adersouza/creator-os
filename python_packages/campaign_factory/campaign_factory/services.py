from __future__ import annotations

import sqlite3
from typing import Any, Callable

from .asset_import import AssetImportRepository
from .caption import CaptionFamilyRepository
from .config import Settings
from .creative_planning import CreativePlanningRepository
from .events import EventRepository
from .graph import GraphRepository
from .models import ModelRepository
from .reference import ReferenceRepository


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
        rendered_for_campaign: Callable[[str], list[dict[str, Any]]],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
        prepare_reel_inputs: Callable[..., dict[str, Any]],
        discoverability_safe_content_contract: Callable[..., dict[str, Any]],
        reference_hook_fallbacks: tuple[str, ...],
        normalize_content_surface: Callable[[str | None], str],
        concept_for_parent_asset: Callable[[str], dict[str, Any] | None],
        explain_publishability: Callable[[str], dict[str, Any]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        instagram_post_caption_for_asset: Callable[..., dict[str, Any]],
        text_hash: Callable[[str], str],
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
        self.creative_planning = CreativePlanningRepository(
            conn,
            new_id=new_id,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            graph_id_for=self.graph.graph_id_for,
            campaign_by_slug=self.campaign_by_slug,
            assets_for_campaign=self.asset_import.assets_for_campaign,
            rendered_for_campaign=rendered_for_campaign,
            dashboard_rendered_asset=dashboard_rendered_asset,
        )
        self.reference = ReferenceRepository(
            conn,
            settings,
            new_id=new_id,
            utc_now=utc_now,
            record_event=self.events.record_event,
            campaign_by_slug=self.campaign_by_slug,
            prepare_reel_inputs=prepare_reel_inputs,
            discoverability_safe_content_contract=discoverability_safe_content_contract,
            reference_hook_fallbacks=reference_hook_fallbacks,
        )
        self.caption_family = CaptionFamilyRepository(
            conn,
            utc_now=utc_now,
            normalize_content_surface=normalize_content_surface,
            rendered_asset=self.rendered_asset,
            concept_for_parent_asset=concept_for_parent_asset,
            explain_publishability=explain_publishability,
            surface_handoff_readiness_for_asset=surface_handoff_readiness_for_asset,
            instagram_post_caption_for_asset=instagram_post_caption_for_asset,
            text_hash=text_hash,
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

    def create_creative_plan(
        self,
        *,
        name: str,
        platform: str = "instagram",
        target_account: str,
        daily_base_video_target: int = 10,
        style_lanes: list[str] | None = None,
        model_profile: str = "",
        source_accounts: list[str] | None = None,
        goal: str = "views_reach",
        linked_campaign: str | None = None,
    ) -> dict[str, Any]:
        return self.creative_planning.create_creative_plan(
            name=name,
            platform=platform,
            target_account=target_account,
            daily_base_video_target=daily_base_video_target,
            style_lanes=style_lanes,
            model_profile=model_profile,
            source_accounts=source_accounts,
            goal=goal,
            linked_campaign=linked_campaign,
        )

    def creative_plan(self, name: str) -> dict[str, Any]:
        return self.creative_planning.creative_plan(name)

    def update_creative_plan_status(self, *, name: str, status: str) -> dict[str, Any]:
        return self.creative_planning.update_creative_plan_status(name=name, status=status)

    def sync_creative_plan_progress(self, *, name: str, prompt_export_path: Any) -> dict[str, Any]:
        return self.creative_planning.sync_creative_plan_progress(name=name, prompt_export_path=prompt_export_path)

    def creative_plan_for_campaign(self, campaign_slug: str, *, dashboard: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.creative_planning.creative_plan_for_campaign(campaign_slug, dashboard=dashboard)

    def record_creative_plan_event(
        self,
        plan_id: str,
        event_type: str,
        *,
        status: str = "info",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> None:
        self.creative_planning.record_creative_plan_event(
            plan_id,
            event_type,
            status=status,
            message=message,
            metadata=metadata,
            commit=commit,
        )

    def creative_plan_payload(self, row: dict[str, Any], *, dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.creative_planning.creative_plan_payload(row, dashboard=dashboard)

    def source_prompt_creative_plan_id(self, source: dict[str, Any]) -> str | None:
        return self.creative_planning.source_prompt_creative_plan_id(source)

    def asset_creative_plan_id(self, asset: dict[str, Any]) -> str | None:
        return self.creative_planning.asset_creative_plan_id(asset)

    def import_reference_bank(self, bank_path: Any, prompt_pack_path: Any | None = None) -> dict[str, Any]:
        return self.reference.import_reference_bank(bank_path, prompt_pack_path)

    def reference_prompt_pack_by_cluster(self, prompt_pack_path: Any | None) -> dict[str, dict[str, Any]]:
        return self.reference.reference_prompt_pack_by_cluster(prompt_pack_path)

    def reference_patterns(self, limit: int = 50) -> dict[str, Any]:
        return self.reference.reference_patterns(limit=limit)

    def reference_pattern_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.reference.reference_pattern_payload(row)

    def select_reference_pattern(
        self,
        campaign_slug: str,
        *,
        cluster_key: str | None = None,
        reference_pattern_id: str | None = None,
        variant_count: int = 5,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.reference.select_reference_pattern(
            campaign_slug,
            cluster_key=cluster_key,
            reference_pattern_id=reference_pattern_id,
            variant_count=variant_count,
            notes=notes,
        )

    def campaign_reference_plan(self, campaign_slug: str) -> dict[str, Any]:
        return self.reference.campaign_reference_plan(campaign_slug)

    def prepare_reel_from_reference(
        self,
        *,
        campaign_slug: str,
        cluster_key: str | None = None,
        reference_pattern_id: str | None = None,
        variant_count: int = 5,
        recipes: list[str] | None = None,
        caption_color: str | None = "auto",
        notes: str | None = None,
        force_new: bool = True,
    ) -> dict[str, Any]:
        return self.reference.prepare_reel_from_reference(
            campaign_slug=campaign_slug,
            cluster_key=cluster_key,
            reference_pattern_id=reference_pattern_id,
            variant_count=variant_count,
            recipes=recipes,
            caption_color=caption_color,
            notes=notes,
            force_new=force_new,
        )

    def active_reference_pattern_for_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        return self.reference.active_reference_pattern_for_campaign(campaign_id)

    def reference_hooks(self, pattern: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
        return self.reference.reference_hooks(pattern, count=count)

    def reference_hook_is_schedule_safe(self, text: str) -> bool:
        return self.reference.reference_hook_is_schedule_safe(text)

    def caption_family_plan(
        self,
        *,
        creator: str | None,
        parent_asset_id: str,
        requested_caption_versions: int = 5,
        style: str = "ig_short",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return self.caption_family.caption_family_plan(
            creator=creator,
            parent_asset_id=parent_asset_id,
            requested_caption_versions=requested_caption_versions,
            style=style,
            dry_run=dry_run,
        )

    def caption_family_create(
        self,
        *,
        creator: str | None,
        parent_asset_id: str,
        requested_caption_versions: int = 5,
        style: str = "ig_short",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.caption_family.caption_family_create(
            creator=creator,
            parent_asset_id=parent_asset_id,
            requested_caption_versions=requested_caption_versions,
            style=style,
            dry_run=dry_run,
        )

    def planned_caption_version(
        self,
        *,
        caption_family_id: str,
        parent: dict[str, Any],
        concept: dict[str, Any] | None,
        index: int,
        angle: str,
        base_burned: str,
        base_hashtags: list[str],
        style: str,
        caption_source: str,
    ) -> dict[str, Any]:
        return self.caption_family.planned_caption_version(
            caption_family_id=caption_family_id,
            parent=parent,
            concept=concept,
            index=index,
            angle=angle,
            base_burned=base_burned,
            base_hashtags=base_hashtags,
            style=style,
            caption_source=caption_source,
        )

    def caption_family_hashtags(self, raw_tags: Any) -> list[str]:
        return self.caption_family.caption_family_hashtags(raw_tags)

    def caption_version_by_id(self, caption_version_id: str | None) -> dict[str, Any] | None:
        return self.caption_family.caption_version_by_id(caption_version_id)

    def caption_version_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        return self.caption_family.caption_version_payload(row)

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
