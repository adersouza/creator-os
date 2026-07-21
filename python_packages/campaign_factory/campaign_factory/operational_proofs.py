from __future__ import annotations

import math
import sqlite3
from typing import Any


class OperationalProofRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def failure_injection_suite(self) -> dict[str, Any]:
        scenarios = [
            ("duplicate_publish_callback", "idempotency_key_dedupes_status_transition"),
            ("double_qstash_dispatch", "publish_job_lock_prevents_duplicate_publish"),
            ("late_dispatch", "lifecycle_marks_past_due_and_requires_recovery"),
            ("missed_dispatch", "daily_plan_blocks_new_scheduling_until_resolved"),
            ("expired_publish_token", "account_health_blocks_account"),
            ("partial_metrics_sync", "metrics_contract_marks_snapshot_incomplete"),
            ("missing_performance_snapshot", "lifecycle_marks_awaiting_metrics"),
            (
                "duplicate_performance_snapshot",
                "unique_snapshot_keys_preserve_final_state",
            ),
            ("invalid_handoff_manifest", "publishability_and_readiness_block_export"),
            ("stale_account_restriction", "restriction_end_time_prevents_stale_block"),
        ]
        rows = [
            {
                "scenario": scenario,
                "detected": None,
                "contained": None,
                "recovered": None,
                "mechanism": mechanism,
                "evidenceStatus": "not_executed",
                "wouldWrite": False,
            }
            for scenario, mechanism in scenarios
        ]
        return {
            "schema": "creator_os.failure_injection_suite.v1",
            "failureInjectionPassed": False,
            "evidenceStatus": "simulation_catalog_only",
            "scenarios": rows,
            "wouldWrite": False,
        }

    def idempotency_proof(self) -> dict[str, Any]:
        path_names = [
            "schedule",
            "publish",
            "metrics_sync",
            "performance_snapshot_ingestion",
            "restriction_event_ingestion",
            "decision_ledger_writes",
        ]
        rows = []
        for name in path_names:
            row = {
                "path": name,
                "sameRequestOnce": None,
                "sameRequestTwice": None,
                "sameRequestTenTimes": None,
                "idempotent": None,
                "evidence": self.idempotency_evidence_for_path(name),
                "evidenceStatus": "not_executed",
                "wouldWrite": False,
            }
            rows.append(row)
        return {
            "schema": "creator_os.idempotency_proof.v1",
            "idempotent": False,
            "idempotencyProven": False,
            "unsafePaths": [],
            "unverifiedPaths": path_names,
            "evidenceStatus": "simulation_catalog_only",
            "paths": rows,
            "wouldWrite": False,
        }

    def surface_maturity_audit(self) -> dict[str, Any]:
        surfaces = {
            "reel": {
                "draftProof": True,
                "scheduleProof": True,
                "publishProof": True,
                "metricsProof": True,
                "learningProof": True,
            },
            "story": {
                "draftProof": True,
                "scheduleProof": False,
                "publishProof": False,
                "metricsProof": False,
                "learningProof": True,
            },
            "feed_single": {
                "draftProof": True,
                "scheduleProof": True,
                "publishProof": True,
                "metricsProof": True,
                "learningProof": True,
            },
            "feed_carousel": {
                "draftProof": True,
                "scheduleProof": False,
                "publishProof": False,
                "metricsProof": False,
                "learningProof": True,
            },
            "trial_reel": {
                "draftProof": True,
                "scheduleProof": False,
                "publishProof": False,
                "metricsProof": False,
                "learningProof": False,
            },
        }
        blockers = {
            "reel": [],
            "story": [
                "story_publish_proof_not_live_enabled",
                "story_metrics_proof_missing",
            ],
            "feed_single": [],
            "feed_carousel": [
                "carousel_publish_proof_missing",
                "carousel_metrics_proof_missing",
            ],
            "trial_reel": ["trial_reel_requires_explicit_manual_graduation_policy"],
        }
        scored = {}
        for surface, checks in surfaces.items():
            declared_checks = dict(checks)
            unverified_checks = {name: None for name in checks}
            scored[surface] = {
                **unverified_checks,
                "declaredCapabilities": declared_checks,
                "maturityScore": 0,
                "blockers": sorted(
                    set([*blockers[surface], "live_surface_evidence_not_supplied"])
                ),
                "evidenceStatus": "not_verified_from_live_receipts",
                "wouldWrite": False,
            }
        return {
            "schema": "creator_os.surface_maturity_audit.v1",
            "surfaces": scored,
            "evidenceStatus": "planning_model_only",
            "wouldWrite": False,
        }

    def operator_load_audit(self) -> dict[str, Any]:
        tiers = {}
        first_breaking_point = ""
        for accounts in (25, 50, 100, 200, 500, 1000):
            posts = accounts * 3
            restriction_cases = math.ceil(accounts * 0.05)
            manual_reviews = math.ceil(accounts * 0.04)
            inventory_repairs = math.ceil(posts * 0.03)
            operator_items = restriction_cases + manual_reviews + inventory_repairs
            largest = (
                "manual_review"
                if manual_reviews >= restriction_cases
                and manual_reviews >= inventory_repairs
                else (
                    "inventory_repair"
                    if inventory_repairs >= restriction_cases
                    else "account_restrictions"
                )
            )
            if not first_breaking_point and operator_items > 25:
                first_breaking_point = f"{accounts}_accounts"
            tiers[str(accounts)] = {
                "accounts": accounts,
                "postsPerDay": posts,
                "estimatedHumanTouchesPerDay": operator_items,
                "restrictionBottlenecks": restriction_cases,
                "manualReviewBottlenecks": manual_reviews,
                "inventoryBottlenecks": inventory_repairs,
                "accountHealthBottlenecks": math.ceil(accounts * 0.03),
                "publishingBottlenecks": math.ceil(posts * 0.01),
                "learningBottlenecks": math.ceil(posts * 0.005),
                "largestBottleneck": largest,
            }
        return {
            "schema": "creator_os.operator_load_audit.v1",
            "scaleTiers": tiers,
            "largestBottleneck": tiers["200"]["largestBottleneck"],
            "firstBreakingPoint": first_breaking_point or "1000_accounts",
            "requiredAutomationBeforeNextScaleTier": "exception_queue_slo_and_inventory_buffer_discipline",
            "wouldWrite": False,
        }

    def idempotency_evidence_for_path(self, name: str) -> str:
        return {
            "schedule": "stable campaignFactoryDraftKey and schedule plan item identity",
            "publish": "post/draft identifiers and QStash job identity should dedupe repeated dispatches",
            "metrics_sync": "performance snapshot uniqueness by post/rendered asset/snapshot window",
            "performance_snapshot_ingestion": "snapshot IDs and content hashes preserve final state",
            "restriction_event_ingestion": "latest restriction status supersedes stale duplicate events",
            "decision_ledger_writes": "future ledger writes should use deterministic decision context hashes",
        }.get(name, "deterministic request identity")
