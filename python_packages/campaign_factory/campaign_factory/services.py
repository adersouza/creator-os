from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from .config import Settings
from .graph import GraphRepository


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
        if status not in {"info", "success", "warning", "failure"}:
            raise ValueError("activity event status must be info, success, warning, or failure")
        event_id = self._new_id("evt")
        now = self._utc_now()
        self.conn.execute(
            """
            INSERT INTO activity_events
            (id, event_type, campaign_id, source_asset_id, rendered_asset_id, render_job_id,
             audit_report_id, threadsdash_export_id, pipeline_job_id, status, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_type,
                campaign_id,
                source_asset_id,
                rendered_asset_id,
                render_job_id,
                audit_report_id,
                threadsdash_export_id,
                pipeline_job_id,
                status,
                message or event_type.replace("_", " "),
                json.dumps(self._sanitize_for_storage(metadata or {}), ensure_ascii=False, sort_keys=True),
                now,
            ),
        )
        if commit:
            self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM activity_events WHERE id = ?", (event_id,)).fetchone())

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
