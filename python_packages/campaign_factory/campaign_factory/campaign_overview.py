from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any

from .assignment_eligibility import asset_identity, enforce_assignment_eligibility


def _job_resolution_scope(job: dict[str, Any]) -> tuple[str, str]:
    payloads = [
        job.get("input") if isinstance(job.get("input"), dict) else {},
        job.get("result") if isinstance(job.get("result"), dict) else {},
    ]
    keys = (
        "renderedAssetId",
        "rendered_asset_id",
        "renderedAssetIds",
        "rendered_asset_ids",
        "assetId",
        "asset_id",
        "sourceAssetId",
        "source_asset_id",
    )
    values: list[str] = []
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                values.extend(str(item) for item in value if str(item).strip())
            elif value:
                values.append(str(value))
    scope = ",".join(sorted(set(values))) if values else "*"
    return (str(job.get("jobType") or ""), scope)


class CampaignOverviewRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        utc_now: Callable[[], str],
        list_campaigns: Callable[[], list[dict[str, Any]]],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        assets_for_campaign: Callable[[str], list[dict[str, Any]]],
        rendered_for_campaign: Callable[[str], list[dict[str, Any]]],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
        jobs_for_campaign: Callable[..., list[dict[str, Any]]],
        audio_workflow_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        daily_production_counters: Callable[..., dict[str, Any]],
        creative_plan_for_campaign: Callable[..., dict[str, Any] | None],
        events_for_campaign: Callable[..., list[dict[str, Any]]],
        distribution_summary: Callable[[str], dict[str, Any]],
        trust_summary: Callable[[str], dict[str, Any]],
        rendered_asset: Callable[[str], dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
        events_for_asset: Callable[..., list[dict[str, Any]]],
        performance_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        ranking: Callable[[str], dict[str, Any]],
        audit_report_payload: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._utc_now = utc_now
        self._list_campaigns = list_campaigns
        self._campaign_by_slug = campaign_by_slug
        self._assets_for_campaign = assets_for_campaign
        self._rendered_for_campaign = rendered_for_campaign
        self._dashboard_rendered_asset = dashboard_rendered_asset
        self._jobs_for_campaign = jobs_for_campaign
        self._audio_workflow_summary = audio_workflow_summary
        self._daily_production_counters = daily_production_counters
        self._creative_plan_for_campaign = creative_plan_for_campaign
        self._events_for_campaign = events_for_campaign
        self._distribution_summary = distribution_summary
        self._trust_summary = trust_summary
        self._rendered_asset = rendered_asset
        self._record_event = record_event
        self._events_for_asset = events_for_asset
        self._performance_for_asset = performance_for_asset
        self._ranking = ranking
        self._audit_report_payload = audit_report_payload

    def dashboard(self, campaign_slug: str | None = None) -> dict[str, Any]:
        campaigns = self._list_campaigns()
        selected = (
            self._campaign_by_slug(campaign_slug)
            if campaign_slug
            else self.default_dashboard_campaign(campaigns)
        )
        if not selected:
            return {
                "campaigns": [],
                "campaign": None,
                "sources": [],
                "rendered": [],
                "health": None,
                "ranking": [],
            }
        rendered = [
            self._dashboard_rendered_asset(asset)
            for asset in self._rendered_for_campaign(selected["id"])
        ]
        ranking = self._ranking(selected["slug"])
        audio_workflow = self._audio_workflow_summary(rendered)
        sources = self._assets_for_campaign(selected["id"])
        summary_dashboard = {
            "campaign": selected,
            "sources": sources,
            "rendered": rendered,
        }
        daily_production = self._daily_production_counters(
            selected["slug"], dashboard=summary_dashboard
        )
        creative_plan = self._creative_plan_for_campaign(
            selected["slug"], dashboard=summary_dashboard
        )
        return {
            "campaigns": campaigns,
            "campaign": selected,
            "sources": sources,
            "rendered": sorted(
                rendered,
                key=lambda asset: (ranking["byAsset"].get(asset["id"], {}) or {}).get(
                    "score", 0
                ),
                reverse=True,
            ),
            "activity": self._events_for_campaign(selected["slug"], limit=50),
            "jobs": self._jobs_for_campaign(selected["slug"], limit=50),
            "health": self.campaign_health(selected["slug"]),
            "audioWorkflow": audio_workflow,
            "dailyProduction": daily_production,
            "creativePlan": creative_plan,
            "distribution": self._distribution_summary(selected["slug"]),
            "trust": self._trust_summary(selected["slug"]),
            "ranking": ranking["assets"],
        }

    def default_dashboard_campaign(
        self, campaigns: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        for campaign in campaigns:
            row = self.conn.execute(
                "SELECT 1 FROM rendered_assets WHERE campaign_id = ? LIMIT 1",
                (campaign["id"],),
            ).fetchone()
            if row:
                return campaign
        return campaigns[0] if campaigns else None

    def campaign_health(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        sources = self._assets_for_campaign(campaign["id"])
        rendered = [
            self._dashboard_rendered_asset(asset)
            for asset in self._rendered_for_campaign(campaign["id"])
        ]
        jobs = self._jobs_for_campaign(campaign["slug"], limit=200)
        audited = [asset for asset in rendered if asset.get("latest_audit")]
        approved = [asset for asset in rendered if asset["review_state"] == "approved"]
        rejected = [asset for asset in rendered if asset["review_state"] == "rejected"]
        ready = [
            asset
            for asset in rendered
            if (asset.get("export_readiness") or {}).get("state") == "ready"
        ]
        warning = [
            asset
            for asset in rendered
            if (asset.get("export_readiness") or {}).get("state") == "warning"
        ]
        blocked = [
            asset
            for asset in rendered
            if (asset.get("export_readiness") or {}).get("state") == "blocked"
        ]
        audio_workflow = self._audio_workflow_summary(rendered)
        failed_jobs = self.unresolved_failed_jobs(jobs)
        identity_blocked = 0
        for raw in self._rendered_for_campaign(campaign["id"]):
            identity = asset_identity(raw)
            if raw.get("origin_account_id") and not (
                identity["sourceFamilyId"] or identity["perceptualFingerprint"]
            ):
                identity_blocked += 1
        return {
            "schema": "campaign_factory.campaign_health.v1",
            "campaign": campaign["slug"],
            "generatedAt": self._utc_now(),
            "counts": {
                "sourcesImported": len(sources),
                "renderedAssets": len(rendered),
                "auditedAssets": len(audited),
                "approvedAssets": len(approved),
                "rejectedAssets": len(rejected),
                "exportReadyAssets": len(ready),
                "warningAssets": len(warning),
                "blockedAssets": len(blocked),
                "failedJobs": len(failed_jobs),
                "audioNeedsAudio": audio_workflow["counts"]["needs_audio"],
                "audioSelectedNotAttached": audio_workflow["counts"][
                    "selected_not_attached"
                ],
                "audioBlocked": audio_workflow["counts"]["blocked"],
                "audioReady": audio_workflow["counts"]["ready"],
                "assignmentIdentityBlockedAssets": identity_blocked,
            },
            "audioWorkflow": audio_workflow,
            "failedJobs": failed_jobs[:10],
        }

    def unresolved_failed_jobs(
        self, jobs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        latest_success_by_scope: dict[tuple[str, str], str] = {}
        for job in jobs:
            if job["status"] != "succeeded":
                continue
            timestamp = (
                job.get("finishedAt")
                or job.get("updatedAt")
                or job.get("createdAt")
                or ""
            )
            scope = _job_resolution_scope(job)
            latest_success_by_scope[scope] = max(
                latest_success_by_scope.get(scope, ""), timestamp
            )
        unresolved = []
        for job in jobs:
            if job["status"] != "failed":
                continue
            failed_at = (
                job.get("finishedAt")
                or job.get("updatedAt")
                or job.get("createdAt")
                or ""
            )
            if latest_success_by_scope.get(_job_resolution_scope(job), "") > failed_at:
                continue
            unresolved.append(job)
        return unresolved

    def asset_detail(self, rendered_asset_id: str) -> dict[str, Any]:
        asset = self._dashboard_rendered_asset(self._rendered_asset(rendered_asset_id))
        campaign = dict(
            self.conn.execute(
                "SELECT * FROM campaigns WHERE id = ?", (asset["campaign_id"],)
            ).fetchone()
        )
        source = dict(
            self.conn.execute(
                "SELECT * FROM source_assets WHERE id = ?", (asset["source_asset_id"],)
            ).fetchone()
        )
        approvals = [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM approval_decisions WHERE rendered_asset_id = ? ORDER BY created_at DESC",
                (rendered_asset_id,),
            ).fetchall()
        ]
        audits = [
            self._audit_report_payload(dict(row))
            for row in self.conn.execute(
                "SELECT * FROM audit_reports WHERE rendered_asset_id = ? ORDER BY created_at DESC",
                (rendered_asset_id,),
            ).fetchall()
        ]
        exports = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM threadsdash_exports
                WHERE campaign_id = ? AND manifest_path IN (
                  SELECT manifest_path FROM threadsdash_exports WHERE campaign_id = ?
                )
                ORDER BY created_at DESC
                """,
                (campaign["id"], campaign["id"]),
            ).fetchall()
        ]
        assignments = self.assignments_for_asset(rendered_asset_id)
        return {
            "schema": "campaign_factory.asset_detail.v1",
            "campaign": campaign,
            "source": source,
            "asset": asset,
            "assignments": assignments,
            "audits": audits,
            "approvals": approvals,
            "exports": exports,
            "activity": self._events_for_asset(rendered_asset_id, limit=100),
            "performance": self._performance_for_asset(asset),
            "ranking": self._ranking(campaign["slug"])["byAsset"].get(
                rendered_asset_id
            ),
        }

    def assign_asset_account(
        self,
        rendered_asset_id: str,
        *,
        account_id: str | None = None,
        instagram_account_id: str | None = None,
        planned_window_start: str | None = None,
        planned_window_end: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        asset = self._rendered_asset(rendered_asset_id)
        if account_id:
            row = self.conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"account not found: {account_id}")
        now = self._utc_now()
        assignment_id = self._new_id("assign")
        eligibility = enforce_assignment_eligibility(
            self.conn,
            rendered_asset_id=rendered_asset_id,
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            planned_at=planned_window_start,
            surface=asset.get("content_surface"),
        )
        identity = eligibility["inputs"]
        self.conn.execute(
            """
            INSERT INTO asset_account_assignments
            (id, campaign_id, rendered_asset_id, account_id, instagram_account_id,
             source_family_id, perceptual_fingerprint, perceptual_cluster_id, account_group_id,
             assignment_eligibility_json, planned_window_start,
             planned_window_end, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assignment_id,
                asset["campaign_id"],
                rendered_asset_id,
                account_id,
                instagram_account_id,
                identity["sourceFamilyId"],
                identity["perceptualFingerprint"],
                identity["perceptualClusterId"],
                identity["accountGroupId"],
                json.dumps(eligibility, ensure_ascii=False, sort_keys=True),
                planned_window_start,
                planned_window_end,
                notes,
                now,
                now,
            ),
        )
        self._record_event(
            "asset_account_assigned",
            campaign_id=asset["campaign_id"],
            source_asset_id=asset["source_asset_id"],
            rendered_asset_id=rendered_asset_id,
            status="success",
            message=f"Assigned asset to Instagram account {instagram_account_id or account_id or 'unassigned'}",
            metadata={
                "assignmentId": assignment_id,
                "accountId": account_id,
                "instagramAccountId": instagram_account_id,
            },
            commit=False,
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM asset_account_assignments WHERE id = ?", (assignment_id,)
            ).fetchone()
        )

    def assignments_for_asset(self, rendered_asset_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM asset_account_assignments WHERE rendered_asset_id = ? ORDER BY created_at",
            (rendered_asset_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def assignments_for_campaign(self, campaign_slug: str) -> list[dict[str, Any]]:
        campaign = self._campaign_by_slug(campaign_slug)
        rows = self.conn.execute(
            "SELECT * FROM asset_account_assignments WHERE campaign_id = ? ORDER BY created_at",
            (campaign["id"],),
        ).fetchall()
        return [dict(row) for row in rows]
