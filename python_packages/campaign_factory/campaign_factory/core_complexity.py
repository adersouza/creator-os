from __future__ import annotations

import sqlite3
from typing import Any

from .config import Settings


class CoreComplexityRepository:
    def __init__(self, conn: sqlite3.Connection, settings: Settings) -> None:
        self.conn = conn
        self.settings = settings

    def single_source_of_truth_audit(self) -> dict[str, Any]:
        recommended = {
            "account health": "creator_os_account_health_report",
            "restriction status": "ThreadsDashboard account state -> Campaign Factory health projection",
            "content surface": "rendered_assets.content_surface",
            "publishability": "_publishability_check",
            "caption version": "caption_versions",
            "variant lineage": "variant_assets",
            "winner status": "Creative Knowledge Base",
            "performance metrics": "performance_snapshots",
            "inventory state": "Campaign Factory surface inventory/readiness",
            "lifecycle state": "lifecycle_report",
        }
        conflicts = [
            {
                "concept": "account eligibility",
                "owners": ["account tiers", "account health", "recommendation eligibility"],
                "risk": "eligibility can be interpreted differently across manager views",
            },
            {
                "concept": "learning/winner status",
                "owners": ["winner reports", "Creative Knowledge Base", "creative performance analysis"],
                "risk": "winner definitions can drift unless Creative KB remains canonical",
            },
        ]
        return {
            "schema": "creator_os.single_source_of_truth_audit.v1",
            "ownershipConflicts": conflicts,
            "duplicateTruths": [item["concept"] for item in conflicts],
            "recommendedOwners": recommended,
            "recommendedFixes": [
                "keep old reports as wrappers over canonical helpers",
                "treat performance_snapshots as the only measured-facts source",
                "treat Campaign Factory readiness as the only inventory/schedule-safe truth",
            ],
            "wouldWrite": False,
        }

    def core_complexity_reduction_plan(self) -> dict[str, Any]:
        files = self.largest_project_files()
        return {
            "schema": "creator_os.core_complexity_reduction_plan.v1",
            "largestFiles": files,
            "highestCouplingAreas": [
                "campaign_factory/core.py: daily-plan, readiness, lifecycle, surface, learning, inventory, and publishability share one class",
                "ThreadsDashboard adapter: draft payload, handoff manifest validation, export readiness, and Supabase writes share one path",
                "account health logic: trust state, warming, restriction, recommendation eligibility, and cadence are tightly coupled",
                "surface readiness logic: publishability, handoff manifest v2, story quality, and carousel components intersect",
            ],
            "recommendedExtractions": [
                {"module": "campaign_factory/operations/readiness.py", "reason": "isolate execution-readiness and inventory SLO proofs"},
                {"module": "campaign_factory/operations/exceptions.py", "reason": "centralize blocker-to-operator-action mapping"},
                {"module": "campaign_factory/operations/scale_acceptance.py", "reason": "keep synthetic scale harness out of core.py"},
                {"module": "campaign_factory/learning/reports.py", "reason": "keep Creative KB views behind one learning boundary"},
            ],
            "expectedComplexityReductionPct": 25,
            "wouldWrite": False,
        }

    def largest_project_files(self) -> list[dict[str, Any]]:
        root = self.settings.root
        candidates = [
            root / "campaign_factory" / "core.py",
            root / "campaign_factory" / "cli.py",
            root / "campaign_factory" / "creator_os_cli.py",
            root / "campaign_factory" / "adapters" / "threadsdash.py",
            root / "campaign_factory" / "adapters" / "contentforge.py",
        ]
        rows = []
        for path in candidates:
            try:
                lines = len(path.read_text(encoding="utf-8").splitlines())
            except OSError:
                lines = 0
            rows.append({
                "file": str(path),
                "lines": lines,
                "risk": "high" if lines > 5000 else ("medium" if lines > 1000 else "low"),
            })
        return sorted(rows, key=lambda row: (-int(row["lines"]), row["file"]))
