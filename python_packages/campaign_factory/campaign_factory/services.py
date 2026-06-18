from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from .config import Settings


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
        if not local_id and not external_id:
            raise ValueError("graph node requires a local_id or external_id")
        now = self._utc_now()
        row = None
        if local_table and local_id:
            row = self.conn.execute(
                "SELECT * FROM content_graph_nodes WHERE local_table = ? AND local_id = ?",
                (local_table, local_id),
            ).fetchone()
        if not row and external_system and external_id:
            row = self.conn.execute(
                "SELECT * FROM content_graph_nodes WHERE external_system = ? AND external_id = ?",
                (external_system, external_id),
            ).fetchone()
        payload_json = json.dumps(self._sanitize_for_storage(payload or {}), ensure_ascii=False, sort_keys=True)
        if row:
            self.conn.execute(
                """
                UPDATE content_graph_nodes
                SET entity_type = ?, local_table = COALESCE(?, local_table),
                    local_id = COALESCE(?, local_id),
                    external_system = COALESCE(?, external_system),
                    external_id = COALESCE(?, external_id),
                    payload_json = ?, updated_at = ?
                WHERE global_id = ?
                """,
                (
                    self._slugify(entity_type),
                    local_table,
                    local_id,
                    external_system,
                    external_id,
                    payload_json,
                    now,
                    row["global_id"],
                ),
            )
            graph_id = row["global_id"]
        else:
            graph_id = self._new_graph_id(entity_type)
            self.conn.execute(
                """
                INSERT INTO content_graph_nodes (
                  global_id, entity_type, local_table, local_id, external_system,
                  external_id, payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    graph_id,
                    self._slugify(entity_type),
                    local_table,
                    local_id,
                    external_system,
                    external_id,
                    payload_json,
                    now,
                    now,
                ),
            )
        if commit:
            self.conn.commit()
        return graph_id

    def graph_id_for(
        self,
        local_table: str,
        local_id: str | None,
        *,
        entity_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str | None:
        if not local_id:
            return None
        row = self.conn.execute(
            "SELECT global_id FROM content_graph_nodes WHERE local_table = ? AND local_id = ?",
            (local_table, local_id),
        ).fetchone()
        if row:
            return row["global_id"]
        if not entity_type:
            return None
        return self.ensure_graph_node(entity_type, local_table=local_table, local_id=local_id, payload=payload)

    def ensure_graph_edge(
        self,
        from_global_id: str | None,
        to_global_id: str | None,
        relation_type: str,
        *,
        evidence: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> str | None:
        if not from_global_id or not to_global_id:
            return None
        now = self._utc_now()
        edge_id = self._new_id("edge")
        self.conn.execute(
            """
            INSERT INTO content_graph_edges (
              id, from_global_id, to_global_id, relation_type, evidence_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(from_global_id, to_global_id, relation_type) DO UPDATE SET
              evidence_json = excluded.evidence_json
            """,
            (
                edge_id,
                from_global_id,
                to_global_id,
                self._slugify(relation_type),
                json.dumps(self._sanitize_for_storage(evidence or {}), ensure_ascii=False, sort_keys=True),
                now,
            ),
        )
        row = self.conn.execute(
            """
            SELECT id FROM content_graph_edges
            WHERE from_global_id = ? AND to_global_id = ? AND relation_type = ?
            """,
            (from_global_id, to_global_id, self._slugify(relation_type)),
        ).fetchone()
        if commit:
            self.conn.commit()
        return row["id"] if row else edge_id

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
