from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_creative_plan

from .persistence import json_load

CREATIVE_PLAN_STATUSES = {
    "planned",
    "references_selected",
    "prompts_ready",
    "generated",
    "ingested",
    "rendered",
    "audited",
    "reviewed",
    "exported",
    "posted",
    "measured",
}
DEFAULT_STYLE_LANES = [
    "amateur_native",
    "polished_glam",
    "slideshow_story",
    "pov_relationship",
    "lifestyle_scene",
]


class CreativePlanningRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        slugify: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        graph_id_for: Callable[..., str | None],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        assets_for_campaign: Callable[[str], list[dict[str, Any]]],
        rendered_for_campaign: Callable[[str], list[dict[str, Any]]],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._slugify = slugify
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._graph_id_for = graph_id_for
        self._campaign_by_slug = campaign_by_slug
        self._assets_for_campaign = assets_for_campaign
        self._rendered_for_campaign = rendered_for_campaign
        self._dashboard_rendered_asset = dashboard_rendered_asset

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
        plan_name = self._slugify(name)
        now = self._utc_now()
        lanes = [
            self._slugify(lane)
            for lane in (style_lanes or DEFAULT_STYLE_LANES)
            if str(lane).strip()
        ]
        accounts = [
            str(account).strip().lstrip("@")
            for account in (source_accounts or [])
            if str(account).strip()
        ]
        row = self.conn.execute(
            "SELECT id FROM creative_plans WHERE name = ?", (plan_name,)
        ).fetchone()
        if row:
            self.conn.execute(
                """
                UPDATE creative_plans
                SET platform = ?, goal = ?, target_account = ?, daily_base_video_target = ?,
                    style_lanes_json = ?, model_profile = ?, source_accounts_json = ?,
                    linked_campaign_slug = COALESCE(?, linked_campaign_slug), updated_at = ?
                WHERE id = ?
                """,
                (
                    platform,
                    goal,
                    target_account.strip().lstrip("@"),
                    max(1, int(daily_base_video_target)),
                    json.dumps(lanes),
                    model_profile or "",
                    json.dumps(accounts),
                    self._slugify(linked_campaign) if linked_campaign else None,
                    now,
                    row["id"],
                ),
            )
            plan_id = row["id"]
            event_type = "creative_plan_updated"
        else:
            plan_id = self._new_id("cplan")
            self.conn.execute(
                """
                INSERT INTO creative_plans (
                  id, name, platform, goal, target_account, daily_base_video_target,
                  style_lanes_json, model_profile, source_accounts_json, status,
                  linked_campaign_slug, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)
                """,
                (
                    plan_id,
                    plan_name,
                    platform,
                    goal,
                    target_account.strip().lstrip("@"),
                    max(1, int(daily_base_video_target)),
                    json.dumps(lanes),
                    model_profile or "",
                    json.dumps(accounts),
                    self._slugify(linked_campaign) if linked_campaign else None,
                    now,
                    now,
                ),
            )
            event_type = "creative_plan_created"
        plan_graph_id = self._ensure_graph_node(
            "creative_plan",
            local_table="creative_plans",
            local_id=plan_id,
            payload={
                "name": plan_name,
                "platform": platform,
                "linkedCampaign": self._slugify(linked_campaign)
                if linked_campaign
                else None,
            },
        )
        if linked_campaign:
            campaign_row = self.conn.execute(
                "SELECT id FROM campaigns WHERE slug = ?",
                (self._slugify(linked_campaign),),
            ).fetchone()
            if campaign_row:
                self._ensure_graph_edge(
                    plan_graph_id,
                    self._graph_id_for(
                        "campaigns", campaign_row["id"], entity_type="campaign"
                    ),
                    "plans_campaign",
                    evidence={"linkedCampaign": self._slugify(linked_campaign)},
                )
        self.record_creative_plan_event(
            plan_id,
            event_type,
            status="success",
            message=f"Creative plan saved: {plan_name}",
            commit=False,
        )
        self.conn.commit()
        return self.creative_plan(plan_name)

    def creative_plan(self, name: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM creative_plans WHERE name = ?", (self._slugify(name),)
        ).fetchone()
        if not row:
            raise ValueError(f"creative plan not found: {name}")
        return self.creative_plan_payload(dict(row))

    def update_creative_plan_status(self, *, name: str, status: str) -> dict[str, Any]:
        normalized = status.strip().lower()
        if normalized not in CREATIVE_PLAN_STATUSES:
            raise ValueError(
                f"creative plan status must be one of: {', '.join(sorted(CREATIVE_PLAN_STATUSES))}"
            )
        plan_row = self.conn.execute(
            "SELECT * FROM creative_plans WHERE name = ?", (self._slugify(name),)
        ).fetchone()
        if not plan_row:
            raise ValueError(f"creative plan not found: {name}")
        now = self._utc_now()
        self.conn.execute(
            "UPDATE creative_plans SET status = ?, updated_at = ? WHERE id = ?",
            (normalized, now, plan_row["id"]),
        )
        self.record_creative_plan_event(
            plan_row["id"],
            "creative_plan_status_updated",
            status="success",
            message=f"Status set to {normalized}",
            metadata={"status": normalized},
            commit=False,
        )
        self.conn.commit()
        return self.creative_plan(name)

    def sync_creative_plan_progress(
        self, *, name: str, prompt_export_path: Path
    ) -> dict[str, Any]:
        plan_row = self.conn.execute(
            "SELECT * FROM creative_plans WHERE name = ?", (self._slugify(name),)
        ).fetchone()
        if not plan_row:
            raise ValueError(f"creative plan not found: {name}")
        path = Path(prompt_export_path).expanduser()
        if not path.exists():
            raise ValueError(f"prompt export not found: {path}")
        counts = self.creative_plan_prompt_export_counts(
            path, plan_id=plan_row["id"], plan_name=plan_row["name"]
        )
        self.record_creative_plan_event(
            plan_row["id"],
            "creative_plan_progress_synced",
            status="success",
            message=f"Synced creative plan progress from {path.name}",
            metadata={"sourcePath": str(path), "counts": counts},
            commit=False,
        )
        if counts.get("image_prompts", 0) > 0 or counts.get("video_prompts", 0) > 0:
            self.conn.execute(
                "UPDATE creative_plans SET status = ?, updated_at = ? WHERE id = ? AND status = 'planned'",
                ("prompts_ready", self._utc_now(), plan_row["id"]),
            )
        else:
            self.conn.execute(
                "UPDATE creative_plans SET updated_at = ? WHERE id = ?",
                (self._utc_now(), plan_row["id"]),
            )
        self.conn.commit()
        plan = self.creative_plan(name)
        return {
            "schema": "campaign_factory.creative_plan_progress_sync.v1",
            "plan": plan,
            "sourcePath": str(path),
            "counts": counts,
        }

    def creative_plan_for_campaign(
        self, campaign_slug: str, *, dashboard: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM creative_plans WHERE linked_campaign_slug = ? ORDER BY updated_at DESC LIMIT 1",
            (self._slugify(campaign_slug),),
        ).fetchone()
        if not row:
            return None
        return self.creative_plan_payload(dict(row), dashboard=dashboard)

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
        self.conn.execute(
            """
            INSERT INTO creative_plan_events (id, creative_plan_id, event_type, status, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._new_id("cpevt"),
                plan_id,
                event_type,
                status,
                message,
                json.dumps(self._sanitize_for_storage(metadata or {}), sort_keys=True),
                self._utc_now(),
            ),
        )
        if commit:
            self.conn.commit()

    def creative_plan_payload(
        self, row: dict[str, Any], *, dashboard: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        linked_campaign = row.get("linked_campaign_slug")
        if not linked_campaign and dashboard and dashboard.get("campaign"):
            linked_campaign = dashboard["campaign"].get("slug")
        counts = self.creative_plan_counts(
            row, linked_campaign=linked_campaign, dashboard=dashboard
        )
        next_actions = self.creative_plan_next_actions(row, counts)
        payload = {
            "schema": "campaign_factory.creative_plan.v1",
            "id": row["id"],
            "name": row["name"],
            "platform": row["platform"],
            "goal": row["goal"],
            "target_account": row["target_account"],
            "daily_base_video_target": int(row["daily_base_video_target"] or 10),
            "style_lanes": json_load(row.get("style_lanes_json"), []),
            "model_profile": row.get("model_profile") or "",
            "source_accounts": json_load(row.get("source_accounts_json"), []),
            "status": row["status"],
            "counts": counts,
            "next_actions": next_actions,
            "linked_campaign": linked_campaign,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        validate_creative_plan(payload)
        return payload

    def creative_plan_counts(
        self,
        row: dict[str, Any],
        *,
        linked_campaign: str | None,
        dashboard: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        plan_id = row["id"]
        target = int(row.get("daily_base_video_target") or 10)
        references = self.count_reference_prompts(plan_id, "referenceId")
        analyses = self.count_reference_prompts(plan_id, "sourcePatternId")
        image_prompts = self.count_reference_prompts(
            plan_id, "higgsfield_soul_image_prompt"
        )
        video_prompts = self.count_reference_prompts(plan_id, "kling_3_video_prompt")
        synced_counts = self.latest_creative_plan_synced_counts(plan_id)
        references = max(references, int(synced_counts.get("references", 0) or 0))
        analyses = max(analyses, int(synced_counts.get("analyses", 0) or 0))
        image_prompts = max(
            image_prompts, int(synced_counts.get("image_prompts", 0) or 0)
        )
        video_prompts = max(
            video_prompts, int(synced_counts.get("video_prompts", 0) or 0)
        )
        sources = (dashboard or {}).get("sources") or []
        rendered = (dashboard or {}).get("rendered") or []
        if linked_campaign and not dashboard:
            try:
                campaign = self._campaign_by_slug(linked_campaign)
                sources = self._assets_for_campaign(campaign["id"])
                rendered = [
                    self._dashboard_rendered_asset(asset)
                    for asset in self._rendered_for_campaign(campaign["id"])
                ]
            except ValueError:
                sources = []
                rendered = []
        plan_sources = [
            source
            for source in sources
            if self.source_prompt_creative_plan_id(source) == plan_id
        ]
        plan_rendered = [
            asset for asset in rendered if self.asset_creative_plan_id(asset) == plan_id
        ]
        reviewed_states = {"approved", "rejected", "review_ready"}
        posted_states = {"exported", "scheduled", "posted", "published"}
        measured = sum(
            1
            for asset in plan_rendered
            if asset.get("latestPerformance")
            or asset.get("performanceScore") is not None
        )
        return {
            "references": min(
                max(references, analyses, image_prompts, video_prompts), target
            )
            if target
            else references,
            "analyses": analyses,
            "image_prompts": image_prompts,
            "video_prompts": video_prompts,
            "generated_videos": len(plan_sources),
            "ingested_videos": len(plan_sources),
            "rendered_outputs": len(plan_rendered),
            "reviewed_outputs": sum(
                1
                for asset in plan_rendered
                if asset.get("review_state") in reviewed_states
            ),
            "exported_drafts": sum(
                1 for asset in plan_rendered if asset.get("review_state") == "approved"
            ),
            "posted_items": sum(
                1
                for asset in plan_rendered
                if (asset.get("export_state") or asset.get("exportState") or "").lower()
                in posted_states
            ),
            "measured_items": measured,
        }

    def creative_plan_next_actions(
        self, row: dict[str, Any], counts: dict[str, int]
    ) -> list[str]:
        target = int(row.get("daily_base_video_target") or 10)
        actions: list[str] = []
        if counts["references"] < target:
            actions.append(f"Select {target - counts['references']} more references")
        if counts["analyses"] < target:
            actions.append(f"Analyze {target - counts['analyses']} more references")
        if counts["image_prompts"] < target:
            actions.append(
                f"Generate {target - counts['image_prompts']} more Higgsfield image prompts"
            )
        if counts["video_prompts"] < target:
            actions.append(
                f"Generate {target - counts['video_prompts']} more Kling video prompts"
            )
        if counts["generated_videos"] < target:
            actions.append(
                f"Generate {target - counts['generated_videos']} more finished videos"
            )
        if counts["ingested_videos"] < counts["generated_videos"]:
            actions.append(
                f"Intake {counts['generated_videos'] - counts['ingested_videos']} finished videos"
            )
        if counts["reviewed_outputs"] < counts["rendered_outputs"]:
            actions.append(
                f"Review {counts['rendered_outputs'] - counts['reviewed_outputs']} rendered outputs"
            )
        if counts["measured_items"] < counts["posted_items"]:
            actions.append("Import reach/views for posted drafts")
        return actions[:5] or ["Creative plan is caught up"]

    def count_reference_prompts(self, plan_id: str, key: str) -> int:
        rows = self.conn.execute(
            "SELECT source_prompt FROM source_assets WHERE source_prompt LIKE ?",
            (f"%{plan_id}%",),
        ).fetchall()
        seen: set[str] = set()
        for row in rows:
            payload = json_load(row["source_prompt"], {})
            value = payload.get(key) or (
                (payload.get("generatedAssetLineage") or {}).get("source") or {}
            ).get(key)
            if value:
                seen.add(str(value))
        return len(seen)

    def latest_creative_plan_synced_counts(self, plan_id: str) -> dict[str, int]:
        row = self.conn.execute(
            """
            SELECT metadata_json FROM creative_plan_events
            WHERE creative_plan_id = ? AND event_type = 'creative_plan_progress_synced'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (plan_id,),
        ).fetchone()
        if not row:
            return {}
        metadata = json_load(row["metadata_json"], {})
        counts = (
            metadata.get("counts") if isinstance(metadata.get("counts"), dict) else {}
        )
        return {
            str(key): int(value or 0)
            for key, value in counts.items()
            if isinstance(value, (int, float))
        }

    def creative_plan_prompt_export_counts(
        self, path: Path, *, plan_id: str, plan_name: str | None = None
    ) -> dict[str, int]:
        records = self.load_prompt_export_records(path)
        reference_ids: set[str] = set()
        pattern_ids: set[str] = set()
        image_prompt_ids: set[str] = set()
        video_prompt_ids: set[str] = set()
        for index, record in enumerate(records):
            prompts = self.prompt_records_from_export_record(record)
            for prompt in prompts:
                if not isinstance(prompt, dict):
                    continue
                prompt_plan_id = (
                    prompt.get("creativePlanId")
                    or prompt.get("creative_plan_id")
                    or record.get("creativePlanId")
                    or record.get("creative_plan_id")
                )
                allowed_plan_ids = {plan_id}
                if plan_name:
                    allowed_plan_ids.add(str(plan_name))
                if prompt_plan_id and str(prompt_plan_id) not in allowed_plan_ids:
                    continue
                reference_id = (
                    prompt.get("referenceId")
                    or prompt.get("reference_id")
                    or record.get("referenceId")
                    or record.get("reference_id")
                )
                pattern_id = (
                    prompt.get("sourcePatternId")
                    or prompt.get("source_pattern_id")
                    or record.get("sourcePatternId")
                    or record.get("source_pattern_id")
                )
                prompt_id = (
                    prompt.get("id")
                    or prompt.get("promptId")
                    or prompt.get("prompt_id")
                    or f"{path.name}:{index}:{prompt.get('targetTool') or prompt.get('target_tool')}"
                )
                target_tool = str(
                    prompt.get("targetTool")
                    or prompt.get("target_tool")
                    or record.get("targetTool")
                    or ""
                ).lower()
                schema = str(prompt.get("schema") or "").lower()
                if reference_id:
                    reference_ids.add(str(reference_id))
                if pattern_id:
                    pattern_ids.add(str(pattern_id))
                if (
                    "higgsfield" in target_tool
                    or "higgsfield_soul_image_prompt" in schema
                ):
                    image_prompt_ids.add(str(prompt_id))
                if "kling" in target_tool or "kling_3_video_prompt" in schema:
                    video_prompt_ids.add(str(prompt_id))
        return {
            "references": len(reference_ids or pattern_ids),
            "analyses": len(pattern_ids),
            "image_prompts": len(image_prompt_ids),
            "video_prompts": len(video_prompt_ids),
        }

    def load_prompt_export_records(self, path: Path) -> list[dict[str, Any]]:
        if path.suffix.lower() == ".jsonl":
            records: list[dict[str, Any]] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                parsed = json_load(line, {})
                if isinstance(parsed, dict):
                    records.append(parsed)
            return records
        parsed = json_load(path.read_text(encoding="utf-8"), {})
        if isinstance(parsed, dict):
            items = (
                parsed.get("items") or parsed.get("prompts") or parsed.get("records")
            )
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
            return [parsed]
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        return []

    def prompt_records_from_export_record(
        self, record: dict[str, Any]
    ) -> list[dict[str, Any]]:
        prompts: list[dict[str, Any]] = []
        for key in (
            "imagePrompt",
            "image_prompt",
            "higgsfieldPrompt",
            "higgsfield_prompt",
            "klingPrompt",
            "kling_prompt",
            "prompt",
        ):
            value = record.get(key)
            if isinstance(value, dict):
                prompts.append(value)
        if not prompts:
            prompts.append(record)
        return prompts

    def source_prompt_creative_plan_id(self, source: dict[str, Any]) -> str | None:
        payload = source.get("sourcePrompt") or source.get("source_prompt")
        parsed = (
            json_load(payload, {})
            if isinstance(payload, str)
            else (payload if isinstance(payload, dict) else {})
        )
        return parsed.get("creativePlanId") or parsed.get("creative_plan_id")

    def asset_creative_plan_id(self, asset: dict[str, Any]) -> str | None:
        source_prompt = asset.get("sourcePrompt") or asset.get("source_prompt")
        parsed = (
            json_load(source_prompt, {})
            if isinstance(source_prompt, str)
            else (source_prompt if isinstance(source_prompt, dict) else {})
        )
        return parsed.get("creativePlanId") or parsed.get("creative_plan_id")
