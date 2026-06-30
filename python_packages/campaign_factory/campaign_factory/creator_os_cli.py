from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .adapters.contentforge import audit_review_batch_manifest
from .adapters.threadsdash import sync_threadsdash_instagram_accounts
from .config import get_settings
from .core import CampaignFactory


def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _threadsdash_supabase_args(args) -> tuple[str | None, str | None]:
    settings = get_settings()
    env_file = (
        Path(args.threadsdash_env_file)
        if getattr(args, "threadsdash_env_file", None)
        else settings.threadsdash_root / ".env.local"
    )
    env_values = _load_env_file(env_file)
    url = (
        getattr(args, "supabase_url", None)
        or os.environ.get("SUPABASE_URL")
        or os.environ.get("VITE_SUPABASE_URL")
        or env_values.get("SUPABASE_URL")
        or env_values.get("VITE_SUPABASE_URL")
        or env_values.get("NEXT_PUBLIC_SUPABASE_URL")
    )
    key = (
        getattr(args, "supabase_service_role_key", None)
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or env_values.get("SUPABASE_SERVICE_ROLE_KEY")
        or env_values.get("SUPABASE_SERVICE_KEY")
    )
    return url, key


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _decision_ledger_kwargs(args) -> dict[str, Any]:
    return {
        "creator": args.creator,
        "date": args.date,
        "threadsdash_report": _load_json(args.threadsdash_report_json),
        "schedule_plan": _load_json(args.schedule_plan_json),
        "time_plan": _load_json(args.time_plan_json),
        "winner_expansion_report": _load_json(args.winner_expansion_report_json),
        "winner_expansion_plan": _load_json(args.winner_expansion_plan_json),
        "variant_inventory_plan": _load_json(args.variant_inventory_plan_json),
        "variant_metrics_rollup": _load_json(args.variant_metrics_rollup_json),
        "account_tiers": _load_json(args.account_tiers_json),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="creator-os")
    sub = parser.add_subparsers(dest="cmd", required=True)

    daily = sub.add_parser("daily-plan")
    daily.add_argument("--creator", action="append", default=[])
    daily.add_argument("--threadsdash-report-json")
    daily.add_argument("--schedule-plan-json")
    daily.add_argument("--time-plan-json")
    daily.add_argument("--winner-expansion-report-json")
    daily.add_argument("--winner-expansion-plan-json")
    daily.add_argument("--variant-metrics-rollup-json")
    daily.add_argument("--date")

    inventory_request = sub.add_parser("recommended-inventory-request-plan")
    inventory_request.add_argument("--creator", required=True)
    inventory_request.add_argument("--target-count", type=int)
    inventory_request.add_argument("--daily-plan-json")
    inventory_request.add_argument("--variant-inventory-plan-json")

    acceptance_200 = sub.add_parser("200-account-acceptance-suite")
    acceptance_200.add_argument("--accounts", type=int, default=200)
    acceptance_200.add_argument("--creators", type=int, default=3)
    acceptance_200.add_argument("--daily-obligations", type=int, default=600)
    acceptance_200.add_argument("--draft-inventory", type=int, default=1800)
    acceptance_200.add_argument("--warming-accounts", type=int, default=30)
    acceptance_200.add_argument("--restricted-accounts", type=int, default=15)
    acceptance_200.add_argument("--manual-review-accounts", type=int, default=10)
    acceptance_200.add_argument("--single-surface", action="store_true")

    review_batch_audit = sub.add_parser("review-batch-contentforge-audit")
    review_batch_audit.add_argument("--manifest", required=True)
    review_batch_audit.add_argument("--source", required=True)
    review_batch_audit.add_argument("--contentforge-base-url")
    review_batch_audit.add_argument("--report-path")
    review_batch_audit.add_argument("--layer", action="append", dest="layers")
    review_batch_audit.add_argument("--animation-mode")
    review_batch_audit.add_argument("--allow-static-opening", action="store_true")
    review_batch_audit.add_argument("--per-file", action="store_true", default=True)
    review_batch_audit.add_argument(
        "--no-per-file", action="store_false", dest="per_file"
    )
    review_batch_audit.add_argument("--no-update-manifest", action="store_true")

    inventory_slo = sub.add_parser("inventory-slo-report")
    inventory_slo.add_argument("--accounts", type=int, default=200)
    inventory_slo.add_argument("--posts-per-account-per-day", type=int, default=3)
    inventory_slo.add_argument("--creators", type=int, default=3)
    inventory_slo.add_argument("--minimum-inventory-days", type=int, default=3)
    inventory_slo.add_argument("--current-validated-drafts", type=int, default=0)

    inventory_buffer = sub.add_parser("inventory-buffer-report")
    inventory_buffer.add_argument("--accounts", type=int, default=200)
    inventory_buffer.add_argument("--posts-per-account-per-day", type=int, default=3)
    inventory_buffer.add_argument("--creators", type=int, default=3)
    inventory_buffer.add_argument("--minimum-inventory-days", type=int, default=3)
    inventory_buffer.add_argument("--current-validated-drafts", type=int, default=0)

    inventory_factory_audit = sub.add_parser("inventory-factory-audit")
    inventory_factory_audit.add_argument("--creator")
    inventory_factory_audit.add_argument("--campaign")
    inventory_factory_audit.add_argument("--accounts", type=int, default=200)
    inventory_factory_audit.add_argument(
        "--posts-per-account-per-day", type=int, default=3
    )

    inventory_yield = sub.add_parser("inventory-yield-analysis")
    inventory_yield.add_argument("--creator")
    inventory_yield.add_argument("--campaign")

    inventory_buffer_policy = sub.add_parser("inventory-buffer-policy-plan")
    inventory_buffer_policy.add_argument("--creator", required=True)
    inventory_buffer_policy.add_argument("--surface", required=True)
    inventory_buffer_policy.add_argument("--daily-demand", type=int, required=True)
    inventory_buffer_policy.add_argument("--buffer-target-days", type=int, default=3)
    inventory_buffer_policy.add_argument("--available-inventory", type=int)

    inventory_slo_enforcement = sub.add_parser("inventory-slo-enforcement-audit")
    inventory_slo_enforcement.add_argument("--creator", action="append", default=[])
    inventory_slo_enforcement.add_argument("--accounts", type=int, default=200)
    inventory_slo_enforcement.add_argument(
        "--posts-per-account-per-day", type=int, default=3
    )
    inventory_slo_enforcement.add_argument(
        "--minimum-inventory-days", type=int, default=3
    )

    inventory_consumption = sub.add_parser("inventory-consumption-simulation")
    inventory_consumption.add_argument("--available-inventory", type=int, default=0)
    inventory_consumption.add_argument(
        "--posts-per-account-per-day", type=int, default=3
    )

    inventory_production = sub.add_parser("inventory-production-requirements")
    inventory_production.add_argument("--accounts", type=int, default=200)
    inventory_production.add_argument(
        "--posts-per-account-per-day", type=int, default=3
    )

    inventory_exception = sub.add_parser("inventory-exception-audit")
    inventory_exception.add_argument("--execution-readiness-json")

    inventory_readiness = sub.add_parser("inventory-factory-readiness-report")
    inventory_readiness.add_argument("--accounts", type=int, default=200)
    inventory_readiness.add_argument("--posts-per-account-per-day", type=int, default=3)
    inventory_readiness.add_argument("--available-inventory", type=int, default=0)
    inventory_readiness.add_argument("--execution-readiness-json")

    inventory_master = sub.add_parser("inventory-factory-master-report")
    inventory_master.add_argument("--accounts", type=int, default=200)
    inventory_master.add_argument("--posts-per-account-per-day", type=int, default=3)
    inventory_master.add_argument("--available-inventory", type=int, default=0)
    inventory_master.add_argument("--execution-readiness-json")

    inventory_autopilot = sub.add_parser("inventory-autopilot-plan")
    inventory_autopilot.add_argument("--accounts", type=int, default=200)
    inventory_autopilot.add_argument("--posts-per-account-per-day", type=int, default=3)
    inventory_autopilot.add_argument("--available-inventory", type=int, default=0)
    inventory_autopilot.add_argument("--buffer-target-days", type=int, default=3)
    inventory_autopilot.add_argument("--surface", default="reel")

    inventory_repair = sub.add_parser("inventory-shortage-repair-plan")
    inventory_repair.add_argument("--accounts", type=int, default=200)
    inventory_repair.add_argument("--posts-per-account-per-day", type=int, default=3)
    inventory_repair.add_argument("--available-inventory", type=int, default=0)
    inventory_repair.add_argument("--buffer-target-days", type=int, default=3)
    inventory_repair.add_argument("--surface", default="reel")

    inventory_protection = sub.add_parser("inventory-buffer-protection-report")
    inventory_protection.add_argument("--accounts", type=int, default=200)
    inventory_protection.add_argument(
        "--posts-per-account-per-day", type=int, default=3
    )
    inventory_protection.add_argument("--available-inventory", type=int, default=0)
    inventory_protection.add_argument("--buffer-target-days", type=int, default=3)
    inventory_protection.add_argument("--surface", default="reel")

    def add_inventory_recovery_args(command):
        command.add_argument("--creator")
        command.add_argument("--campaign")
        command.add_argument("--content-surface")
        command.add_argument("--required-inventory", type=int)
        command.add_argument("--account-target", type=int, default=25)
        command.add_argument("--posts-per-account-per-day", type=int, default=3)
        command.add_argument("--buffer-days", type=int, default=3)

    inventory_recovery = sub.add_parser("inventory-recovery-report")
    add_inventory_recovery_args(inventory_recovery)
    inventory_recovery_priority = sub.add_parser("inventory-recovery-priority-report")
    add_inventory_recovery_args(inventory_recovery_priority)
    inventory_recovery_by_blocker = sub.add_parser("inventory-recovery-by-blocker")
    add_inventory_recovery_args(inventory_recovery_by_blocker)
    inventory_recovery_master = sub.add_parser("inventory-recovery-master-report")
    add_inventory_recovery_args(inventory_recovery_master)

    def add_schedule_safe_production_args(command):
        command.add_argument("--creator")
        command.add_argument("--campaign")
        command.add_argument("--content-surface", default="reel")
        command.add_argument("--lookback-days", type=int, default=1)
        command.add_argument("--required-inventory", type=int)
        command.add_argument("--current-inventory", type=int)

    production_report = sub.add_parser("schedule-safe-production-report")
    add_schedule_safe_production_args(production_report)
    production_waterfall = sub.add_parser("schedule-safe-production-waterfall")
    add_schedule_safe_production_args(production_waterfall)
    production_loss = sub.add_parser("schedule-safe-production-loss-analysis")
    add_schedule_safe_production_args(production_loss)
    production_capacity = sub.add_parser("schedule-safe-production-capacity-model")
    add_schedule_safe_production_args(production_capacity)
    production_master = sub.add_parser("schedule-safe-production-master-report")
    add_schedule_safe_production_args(production_master)
    visual_qc_report = sub.add_parser("contentforge-visual-qc-failure-report")
    add_schedule_safe_production_args(visual_qc_report)
    visual_qc_loss = sub.add_parser("contentforge-visual-qc-loss-analysis")
    add_schedule_safe_production_args(visual_qc_loss)
    visual_qc_waterfall = sub.add_parser("contentforge-visual-qc-waterfall")
    add_schedule_safe_production_args(visual_qc_waterfall)
    visual_qc_repair = sub.add_parser("contentforge-visual-qc-repair-plan")
    add_schedule_safe_production_args(visual_qc_repair)
    visual_qc_master = sub.add_parser("contentforge-visual-qc-master-report")
    add_schedule_safe_production_args(visual_qc_master)

    def add_inventory_unlock_args(command):
        command.add_argument("--creator")
        command.add_argument("--campaign")
        command.add_argument("--content-surface", default="reel")
        command.add_argument("--required-inventory", type=int, default=225)
        command.add_argument("--current-inventory", type=int)

    multi_unlock = sub.add_parser("multi-blocker-inventory-unlock-report")
    add_inventory_unlock_args(multi_unlock)
    multi_unlock_plan = sub.add_parser("multi-blocker-inventory-unlock-plan")
    add_inventory_unlock_args(multi_unlock_plan)
    minimal_unlock = sub.add_parser("inventory-unlock-minimal-fix-set")
    add_inventory_unlock_args(minimal_unlock)
    unlock_master = sub.add_parser("inventory-unlock-master-report")
    add_inventory_unlock_args(unlock_master)
    review_batch = sub.add_parser("operator-inventory-review-batch-plan")
    add_inventory_unlock_args(review_batch)
    review_batch.add_argument("--target-unlock", type=int)
    review_batch.add_argument("--max-batch-size", type=int)
    review_summary = sub.add_parser("operator-inventory-review-batch-summary")
    add_inventory_unlock_args(review_summary)
    review_summary.add_argument("--target-unlock", type=int)
    review_summary.add_argument("--max-batch-size", type=int)
    review_sim = sub.add_parser("operator-review-simulator")
    add_inventory_unlock_args(review_sim)
    review_scenarios = sub.add_parser("operator-review-scenarios")
    add_inventory_unlock_args(review_scenarios)
    review_efficiency = sub.add_parser("operator-review-efficiency-report")
    add_inventory_unlock_args(review_efficiency)
    review_minimum = sub.add_parser("operator-review-minimum-certification-path")
    add_inventory_unlock_args(review_minimum)
    review_master = sub.add_parser("operator-review-master-report")
    add_inventory_unlock_args(review_master)

    def add_fresh_reel_production_args(command):
        command.add_argument("--creator")
        command.add_argument("--campaign")
        command.add_argument("--target-schedule-safe-inventory", type=int, default=270)
        command.add_argument("--current-inventory", type=int)
        command.add_argument("--caption-versions-per-parent", type=int, default=5)
        command.add_argument("--variants-per-caption", type=int, default=3)
        command.add_argument("--batch-schedule-safe-target", type=int, default=90)

    fresh_plan = sub.add_parser("fresh-schedule-safe-production-plan")
    add_fresh_reel_production_args(fresh_plan)
    fresh_batch = sub.add_parser("fresh-reel-production-batch-plan")
    add_fresh_reel_production_args(fresh_batch)
    fresh_capacity = sub.add_parser("fresh-reel-production-capacity-plan")
    add_fresh_reel_production_args(fresh_capacity)
    fresh_master = sub.add_parser("fresh-reel-production-master-report")
    add_fresh_reel_production_args(fresh_master)

    sub.add_parser("road-to-200-accounts")

    reel_parent_proof = sub.add_parser("reel-factory-parent-throughput-proof")
    reel_parent_proof.add_argument("--required-parents-per-day", type=int, default=53)
    reel_parent_proof.add_argument("--lookback-days", type=int, default=1)

    sub.add_parser("reel-factory-yield-analysis")
    sub.add_parser("reel-factory-failure-analysis")

    reel_capacity = sub.add_parser("reel-factory-capacity-model")
    reel_capacity.add_argument("--required-parents-per-day", type=int, default=53)

    sub.add_parser("reel-factory-200-account-readiness")
    sub.add_parser("reel-factory-master-report")

    parent_waterfall = sub.add_parser("parent-factory-yield-waterfall")
    parent_waterfall.add_argument("--required-parents-per-day", type=int, default=53)
    parent_loss = sub.add_parser("parent-factory-loss-analysis")
    parent_loss.add_argument("--required-parents-per-day", type=int, default=53)
    sub.add_parser("parent-factory-rejection-report")
    sub.add_parser("parent-factory-discoverability-loss-analysis")
    gate_intake = sub.add_parser("discoverability-intake-gate")
    gate_intake.add_argument("--payload-json", required=True)
    gate_generation = sub.add_parser("discoverability-generation-gate")
    gate_generation.add_argument("--payload-json", required=True)
    gate_pre_render = sub.add_parser("discoverability-pre-render-gate")
    gate_pre_render.add_argument("--payload-json", required=True)
    sub.add_parser("discoverability-violation-origin-map")
    sub.add_parser("parent-factory-recoverable-yield")
    sub.add_parser("parent-factory-throughput-recovery-plan")
    sub.add_parser("parent-factory-53-parent-feasibility")
    sub.add_parser("parent-factory-secondary-loss-analysis")
    sub.add_parser("parent-factory-waterfall-after-discoverability")
    sub.add_parser("parent-factory-true-yield-model")
    sub.add_parser("parent-factory-realistic-53-parent-plan")
    capture_rejection = sub.add_parser("capture-publishability-rejection-evidence")
    capture_rejection.add_argument("--asset-id", required=True)
    sub.add_parser("parent-factory-quality-gate-analysis")
    parent_optimization = sub.add_parser("parent-factory-optimization-plan")
    parent_optimization.add_argument("--required-parents-per-day", type=int, default=53)
    parent_master = sub.add_parser("parent-factory-master-optimization-report")
    parent_master.add_argument("--required-parents-per-day", type=int, default=53)

    parent_autopilot = sub.add_parser("parent-factory-autopilot-plan")
    parent_autopilot.add_argument("--accounts", type=int, default=200)
    parent_autopilot.add_argument("--posts-per-account-per-day", type=int, default=3)
    parent_shortfall = sub.add_parser("parent-factory-shortfall-report")
    parent_shortfall.add_argument("--accounts", type=int, default=200)
    parent_shortfall.add_argument("--posts-per-account-per-day", type=int, default=3)
    parent_targets = sub.add_parser("parent-factory-production-targets")
    parent_targets.add_argument("--accounts", type=int, default=200)
    parent_targets.add_argument("--posts-per-account-per-day", type=int, default=3)

    exception_queue = sub.add_parser("exception-queue-report")
    exception_queue.add_argument("--daily-plan-json")
    exception_queue.add_argument("--execution-readiness-json")

    exception_summary = sub.add_parser("exception-queue-summary")
    exception_summary.add_argument("--daily-plan-json")
    exception_summary.add_argument("--execution-readiness-json")
    exception_priority = sub.add_parser("exception-queue-priority-report")
    exception_priority.add_argument("--daily-plan-json")
    exception_priority.add_argument("--execution-readiness-json")
    exception_owner = sub.add_parser("exception-queue-owner-report")
    exception_owner.add_argument("--daily-plan-json")
    exception_owner.add_argument("--execution-readiness-json")

    sub.add_parser("failure-injection-suite")
    sub.add_parser("idempotency-proof")
    sub.add_parser("surface-maturity-audit")
    sub.add_parser("surface-readiness-scorecard")
    sub.add_parser("operator-load-audit")
    sub.add_parser("single-source-of-truth-audit")
    sub.add_parser("core-complexity-reduction-plan")
    sub.add_parser("creator-os-100-account-proof")
    sub.add_parser("creator-os-volume-acceptance-suite")
    sub.add_parser("creator-os-9.5-readiness-report")
    sub.add_parser("creator-os-10.0-readiness-report")
    sub.add_parser("creator-os-live-100-account-readiness")
    live_acceptance = sub.add_parser("creator-os-live-account-acceptance")
    live_acceptance.add_argument("--account-target", type=int, default=10)
    live_acceptance.add_argument(
        "--content-surface", choices=["reel", "story", "feed_single", "feed_carousel"]
    )
    staged_acceptance = sub.add_parser("creator-os-staged-live-acceptance")
    staged_acceptance.add_argument(
        "--content-surface", choices=["reel", "story", "feed_single", "feed_carousel"]
    )
    sync_accounts = sub.add_parser("sync-threadsdash-instagram-accounts")
    sync_accounts.add_argument("--creator", required=True)
    sync_accounts.add_argument("--match")
    sync_accounts.add_argument("--user-id")
    sync_accounts.add_argument("--limit", type=int, default=500)
    sync_accounts.add_argument("--supabase-url")
    sync_accounts.add_argument("--supabase-service-role-key")
    sync_accounts.add_argument("--threadsdash-env-file")
    sub.add_parser("creator-os-live-scale-runbook")
    sub.add_parser("creator-os-live-scale-scorecard")
    sub.add_parser("parent-factory-production-trial")
    sub.add_parser("parent-factory-production-scorecard")
    sub.add_parser("parent-factory-real-yield-report")
    sub.add_parser("parent-factory-53-parent-trial")
    sub.add_parser("parent-factory-trial-results")
    sub.add_parser("parent-factory-trial-analysis")
    sub.add_parser("parent-factory-post-gate-fresh-batch-proof")
    sub.add_parser("discoverability-prevention-audit")
    sub.add_parser("discoverability-prevention-scorecard")
    story_certification = sub.add_parser("story-certification-proof")
    story_certification.add_argument("--rendered-asset-id")
    sub.add_parser("story-production-readiness")
    sub.add_parser("story-proof-gap-analysis")
    carousel_certification = sub.add_parser("carousel-certification-proof")
    carousel_certification.add_argument("--rendered-asset-id")
    sub.add_parser("carousel-production-readiness")
    sub.add_parser("carousel-proof-gap-analysis")
    sub.add_parser("creator-os-certification-report")

    gap = sub.add_parser("draft-inventory-gap")
    gap.add_argument("--creator", required=True)
    gap.add_argument("--threadsdash-report-json")
    gap.add_argument("--schedule-plan-json")
    gap.add_argument("--time-plan-json")

    readiness = sub.add_parser("execution-readiness")
    readiness.add_argument("--creator", required=True)
    readiness.add_argument("--requested-count", type=int, required=True)
    readiness.add_argument("--threadsdash-report-json")
    readiness.add_argument("--schedule-plan-json")
    readiness.add_argument("--time-plan-json")

    tiers = sub.add_parser("account-tiers")
    tiers.add_argument("--creator", required=True)
    tiers.add_argument("--threadsdash-report-json")

    account_health = sub.add_parser("account-health-report")
    account_health.add_argument("--creator", required=True)
    account_health.add_argument("--threadsdash-report-json")

    restricted_accounts = sub.add_parser("restricted-account-report")
    restricted_accounts.add_argument("--creator", required=True)
    restricted_accounts.add_argument("--threadsdash-report-json")

    manual_review = sub.add_parser("manual-review-queue")
    manual_review.add_argument("--creator", required=True)
    manual_review.add_argument("--threadsdash-report-json")

    warmup = sub.add_parser("account-warmup-report")
    warmup.add_argument("--creator", required=True)
    warmup.add_argument("--threadsdash-report-json")

    lifecycle = sub.add_parser("lifecycle-dashboard")
    lifecycle.add_argument("--campaign", required=True)
    lifecycle.add_argument("--user-id")
    lifecycle.add_argument("--threadsdash-posts-json")
    lifecycle.add_argument(
        "--include-threadsdash", choices=["auto", "live", "off"], default="auto"
    )

    creator_surface = sub.add_parser("creator-surface-summary")
    creator_surface.add_argument("--creator", required=True)
    creator_surface.add_argument("--date")

    account_surface = sub.add_parser("account-surface-summary")
    account_surface.add_argument("--creator", required=True)
    account_surface.add_argument("--date")
    account_surface.add_argument("--account-id")

    surface_gap = sub.add_parser("creator-surface-gap-report")
    surface_gap.add_argument("--creator", required=True)
    surface_gap.add_argument("--date")

    carousel_integrity = sub.add_parser("carousel-integrity-report")
    carousel_integrity.add_argument("--creator")
    carousel_integrity.add_argument("--campaign")
    carousel_integrity.add_argument("--rendered-asset-id")

    carousel_metrics = sub.add_parser("carousel-child-metrics-plan")
    carousel_metrics.add_argument("--creator")
    carousel_metrics.add_argument("--campaign")
    carousel_metrics.add_argument("--rendered-asset-id")

    def add_creative_kb_args(command):
        command.add_argument("--creator", required=True)
        command.add_argument("--campaign")
        command.add_argument("--minimum-sample-size", type=int, default=3)
        command.add_argument("--limit", type=int, default=10)

    creative_kb = sub.add_parser("creative-knowledge-base")
    add_creative_kb_args(creative_kb)
    creative_pattern = sub.add_parser("creative-pattern-report")
    add_creative_kb_args(creative_pattern)
    creative_surface = sub.add_parser("creative-surface-report")
    add_creative_kb_args(creative_surface)
    creative_tier = sub.add_parser("creative-account-tier-report")
    add_creative_kb_args(creative_tier)
    creative_caption = sub.add_parser("creative-caption-report")
    add_creative_kb_args(creative_caption)
    creative_audio = sub.add_parser("creative-audio-report")
    add_creative_kb_args(creative_audio)
    creative_window = sub.add_parser("creative-window-report")
    add_creative_kb_args(creative_window)
    creative_performance = sub.add_parser("creative-performance-analysis")
    add_creative_kb_args(creative_performance)
    creator_learning = sub.add_parser("creator-learning-summary")
    add_creative_kb_args(creator_learning)
    next_content = sub.add_parser("next-content-recommendations")
    add_creative_kb_args(next_content)
    confidence_model = sub.add_parser("creative-learning-confidence-model")
    add_creative_kb_args(confidence_model)
    fatigue_report = sub.add_parser("creative-fatigue-report")
    add_creative_kb_args(fatigue_report)
    surface_comparison = sub.add_parser("creative-surface-comparison-report")
    add_creative_kb_args(surface_comparison)
    recommendation_audit = sub.add_parser("recommendation-quality-audit")
    add_creative_kb_args(recommendation_audit)
    tribev2_analysis = sub.add_parser("tribev2-reel-analysis")
    add_creative_kb_args(tribev2_analysis)
    tribev2_review = sub.add_parser("tribev2-reel-review")
    tribev2_review.add_argument("--creator", required=True)
    tribev2_review.add_argument("--campaign")
    tribev2_review.add_argument(
        "--sort-by",
        default="meanAbsActivation",
        choices=["meanAbsActivation", "peakAbsActivation", "stdActivation"],
    )
    tribev2_review.add_argument(
        "--bucket", default="top", choices=["top", "bottom", "both"]
    )
    tribev2_review.add_argument("--limit", type=int, default=12)
    tribev2_review.add_argument("--contact-sheet", action="store_true")
    tribev2_review.add_argument("--show-metrics", action="store_true")
    tribev2_review.add_argument("--hide-tribe-score", action="store_true")
    tribev2_review.add_argument("--blind-mode", action="store_true")
    tribev2_holdout = sub.add_parser("tribev2-holdout-pilot-review")
    tribev2_holdout.add_argument("--creator", required=True)
    tribev2_holdout.add_argument("--campaign")
    tribev2_holdout.add_argument("--limit", type=int, default=20)
    tribev2_holdout.add_argument("--contact-sheet", action="store_true")
    caption_repair = sub.add_parser("caption-quality-repair-plan")
    caption_repair.add_argument("--creator", required=True)
    caption_repair.add_argument("--campaign")
    caption_repair.add_argument("--content-surface")
    caption_repair.add_argument("--limit", type=int, default=200)

    story_inventory = sub.add_parser("story-inventory-report")
    story_inventory.add_argument("--creator", required=True)
    story_inventory.add_argument("--campaign")

    story_gap = sub.add_parser("story-gap-report")
    story_gap.add_argument("--creator", required=True)
    story_gap.add_argument("--date", required=True)

    story_quality = sub.add_parser("story-quality-report")
    story_quality.add_argument("--creator", required=True)
    story_quality.add_argument("--campaign")

    story_intent = sub.add_parser("story-intent-report")
    story_intent.add_argument("--creator", required=True)
    story_intent.add_argument("--campaign")

    story_mix = sub.add_parser("story-mix-plan")
    story_mix.add_argument("--creator", required=True)

    story_calendar = sub.add_parser("story-calendar-plan")
    story_calendar.add_argument("--creator", required=True)

    story_intent_summary = sub.add_parser("story-intent-summary")
    story_intent_summary.add_argument("--creator", required=True)
    story_intent_summary.add_argument("--campaign")

    def add_decision_ledger_args(command):
        command.add_argument("--creator", required=True)
        command.add_argument("--date")
        command.add_argument("--threadsdash-report-json")
        command.add_argument("--schedule-plan-json")
        command.add_argument("--time-plan-json")
        command.add_argument("--winner-expansion-report-json")
        command.add_argument("--winner-expansion-plan-json")
        command.add_argument("--variant-inventory-plan-json")
        command.add_argument("--variant-metrics-rollup-json")
        command.add_argument("--account-tiers-json")

    decision_preview = sub.add_parser("decision-ledger-preview")
    add_decision_ledger_args(decision_preview)

    decision_report = sub.add_parser("decision-ledger-report")
    add_decision_ledger_args(decision_report)

    decision_summary = sub.add_parser("decision-ledger-summary")
    add_decision_ledger_args(decision_summary)

    decision_by_creator = sub.add_parser("decision-ledger-by-creator")
    add_decision_ledger_args(decision_by_creator)

    decision_by_account = sub.add_parser("decision-ledger-by-account")
    add_decision_ledger_args(decision_by_account)
    decision_by_account.add_argument("--account-id", required=True)

    decision_by_surface = sub.add_parser("decision-ledger-by-surface")
    add_decision_ledger_args(decision_by_surface)
    decision_by_surface.add_argument("--surface", required=True)

    decision_by_type = sub.add_parser("decision-ledger-by-decision-type")
    add_decision_ledger_args(decision_by_type)
    decision_by_type.add_argument("--decision-type", required=True)

    account_story = sub.add_parser("account-story-status")
    account_story.add_argument("--account-id", required=True)
    account_story.add_argument("--creator")
    account_story.add_argument("--date", required=True)

    creator_story = sub.add_parser("creator-story-summary")
    creator_story.add_argument("--creator", required=True)
    creator_story.add_argument("--date", required=True)

    args = parser.parse_args()
    cf = CampaignFactory(get_settings())
    try:
        if args.cmd == "daily-plan":
            print_json(
                cf.creator_os_daily_plan(
                    creators=args.creator,
                    threadsdash_report=_load_json(args.threadsdash_report_json),
                    schedule_plan=_load_json(args.schedule_plan_json),
                    time_plan=_load_json(args.time_plan_json),
                    winner_expansion_report=_load_json(
                        args.winner_expansion_report_json
                    ),
                    winner_expansion_plan=_load_json(args.winner_expansion_plan_json),
                    variant_metrics_rollup=_load_json(args.variant_metrics_rollup_json),
                    date=args.date,
                )
            )
            return 0
        if args.cmd == "recommended-inventory-request-plan":
            print_json(
                cf.recommended_inventory_request_plan(
                    creator=args.creator,
                    target_count=args.target_count,
                    daily_plan=_load_json(args.daily_plan_json),
                    variant_inventory_plan=_load_json(args.variant_inventory_plan_json),
                )
            )
            return 0
        if args.cmd == "200-account-acceptance-suite":
            print_json(
                cf.creator_os_200_account_acceptance_suite(
                    accounts=args.accounts,
                    creators=args.creators,
                    daily_obligations=args.daily_obligations,
                    draft_inventory=args.draft_inventory,
                    warming_accounts=args.warming_accounts,
                    restricted_accounts=args.restricted_accounts,
                    manual_review_accounts=args.manual_review_accounts,
                    mixed_surfaces=not args.single_surface,
                )
            )
            return 0
        if args.cmd == "review-batch-contentforge-audit":
            print_json(
                audit_review_batch_manifest(
                    contentforge_root=cf.settings.contentforge_root,
                    manifest_path=Path(args.manifest),
                    source_path=Path(args.source),
                    contentforge_base_url=args.contentforge_base_url
                    or cf.settings.contentforge_base_url,
                    report_path=Path(args.report_path) if args.report_path else None,
                    layers=args.layers,
                    animation_mode=args.animation_mode,
                    allow_static_opening=args.allow_static_opening,
                    per_file=args.per_file,
                    update_manifest=not args.no_update_manifest,
                )
            )
            return 0
        if args.cmd == "inventory-slo-report":
            print_json(
                cf.inventory_slo_report(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                    creators=args.creators,
                    minimum_inventory_days=args.minimum_inventory_days,
                    current_validated_drafts=args.current_validated_drafts,
                )
            )
            return 0
        if args.cmd == "inventory-buffer-report":
            print_json(
                cf.inventory_buffer_report(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                    creators=args.creators,
                    minimum_inventory_days=args.minimum_inventory_days,
                    current_validated_drafts=args.current_validated_drafts,
                )
            )
            return 0
        if args.cmd == "inventory-factory-audit":
            print_json(
                cf.inventory_factory_audit(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                )
            )
            return 0
        if args.cmd == "inventory-yield-analysis":
            print_json(
                cf.inventory_yield_analysis(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                )
            )
            return 0
        if args.cmd == "inventory-buffer-policy-plan":
            print_json(
                cf.inventory_buffer_policy_plan(
                    creator=args.creator,
                    surface=args.surface,
                    daily_demand=args.daily_demand,
                    buffer_target_days=args.buffer_target_days,
                    available_inventory=args.available_inventory,
                )
            )
            return 0
        if args.cmd == "inventory-slo-enforcement-audit":
            print_json(
                cf.inventory_slo_enforcement_audit(
                    creators=args.creator,
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                    minimum_inventory_days=args.minimum_inventory_days,
                )
            )
            return 0
        if args.cmd == "inventory-consumption-simulation":
            print_json(
                cf.inventory_consumption_simulation(
                    available_inventory=args.available_inventory,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                )
            )
            return 0
        if args.cmd == "inventory-production-requirements":
            print_json(
                cf.inventory_production_requirements(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                )
            )
            return 0
        if args.cmd == "inventory-exception-audit":
            print_json(
                cf.inventory_exception_audit(
                    execution_readiness=_load_json(args.execution_readiness_json),
                )
            )
            return 0
        if args.cmd == "inventory-factory-readiness-report":
            print_json(
                cf.inventory_factory_readiness_report(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                    available_inventory=args.available_inventory,
                    execution_readiness=_load_json(args.execution_readiness_json),
                )
            )
            return 0
        if args.cmd == "inventory-factory-master-report":
            print_json(
                cf.inventory_factory_master_report(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                    available_inventory=args.available_inventory,
                    execution_readiness=_load_json(args.execution_readiness_json),
                )
            )
            return 0
        if args.cmd == "inventory-autopilot-plan":
            print_json(
                cf.inventory_autopilot_plan(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                    available_inventory=args.available_inventory,
                    buffer_target_days=args.buffer_target_days,
                    surface=args.surface,
                )
            )
            return 0
        if args.cmd == "inventory-shortage-repair-plan":
            print_json(
                cf.inventory_shortage_repair_plan(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                    available_inventory=args.available_inventory,
                    buffer_target_days=args.buffer_target_days,
                    surface=args.surface,
                )
            )
            return 0
        if args.cmd == "inventory-buffer-protection-report":
            print_json(
                cf.inventory_buffer_protection_report(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                    available_inventory=args.available_inventory,
                    buffer_target_days=args.buffer_target_days,
                    surface=args.surface,
                )
            )
            return 0
        if args.cmd in {
            "inventory-recovery-report",
            "inventory-recovery-priority-report",
            "inventory-recovery-by-blocker",
            "inventory-recovery-master-report",
        }:
            payload = {
                "creator": args.creator,
                "campaign_slug": args.campaign,
                "content_surface": args.content_surface,
                "required_inventory": args.required_inventory,
                "account_target": args.account_target,
                "posts_per_account_per_day": args.posts_per_account_per_day,
                "buffer_days": args.buffer_days,
            }
            if args.cmd == "inventory-recovery-report":
                print_json(cf.inventory_recovery_report(**payload))
            elif args.cmd == "inventory-recovery-priority-report":
                print_json(cf.inventory_recovery_priority_report(**payload))
            elif args.cmd == "inventory-recovery-by-blocker":
                print_json(cf.inventory_recovery_by_blocker(**payload))
            else:
                print_json(cf.inventory_recovery_master_report(**payload))
            return 0
        if args.cmd in {
            "schedule-safe-production-report",
            "schedule-safe-production-waterfall",
            "schedule-safe-production-loss-analysis",
            "schedule-safe-production-capacity-model",
            "schedule-safe-production-master-report",
        }:
            payload = {
                "creator": args.creator,
                "campaign_slug": args.campaign,
                "content_surface": args.content_surface,
                "lookback_days": args.lookback_days,
                "required_inventory": args.required_inventory,
                "current_inventory": args.current_inventory,
            }
            if args.cmd == "schedule-safe-production-report":
                print_json(cf.schedule_safe_production_report(**payload))
            elif args.cmd == "schedule-safe-production-waterfall":
                print_json(cf.schedule_safe_production_waterfall(**payload))
            elif args.cmd == "schedule-safe-production-loss-analysis":
                print_json(cf.schedule_safe_production_loss_analysis(**payload))
            elif args.cmd == "schedule-safe-production-capacity-model":
                print_json(cf.schedule_safe_production_capacity_model(**payload))
            else:
                print_json(cf.schedule_safe_production_master_report(**payload))
            return 0
        if args.cmd in {
            "contentforge-visual-qc-failure-report",
            "contentforge-visual-qc-loss-analysis",
            "contentforge-visual-qc-waterfall",
            "contentforge-visual-qc-repair-plan",
            "contentforge-visual-qc-master-report",
        }:
            payload = {
                "creator": args.creator,
                "campaign_slug": args.campaign,
                "content_surface": args.content_surface,
                "lookback_days": args.lookback_days,
                "required_inventory": args.required_inventory or 225,
                "current_inventory": args.current_inventory,
            }
            if args.cmd == "contentforge-visual-qc-failure-report":
                print_json(cf.contentforge_visual_qc_failure_report(**payload))
            elif args.cmd == "contentforge-visual-qc-loss-analysis":
                print_json(cf.contentforge_visual_qc_loss_analysis(**payload))
            elif args.cmd == "contentforge-visual-qc-waterfall":
                print_json(cf.contentforge_visual_qc_waterfall(**payload))
            elif args.cmd == "contentforge-visual-qc-repair-plan":
                print_json(cf.contentforge_visual_qc_repair_plan(**payload))
            else:
                print_json(cf.contentforge_visual_qc_master_report(**payload))
            return 0
        if args.cmd in {
            "multi-blocker-inventory-unlock-report",
            "multi-blocker-inventory-unlock-plan",
            "inventory-unlock-minimal-fix-set",
            "inventory-unlock-master-report",
        }:
            payload = {
                "creator": args.creator,
                "campaign_slug": args.campaign,
                "content_surface": args.content_surface,
                "required_inventory": args.required_inventory,
                "current_inventory": args.current_inventory,
            }
            if args.cmd == "multi-blocker-inventory-unlock-report":
                print_json(cf.multi_blocker_inventory_unlock_report(**payload))
            elif args.cmd == "multi-blocker-inventory-unlock-plan":
                print_json(cf.multi_blocker_inventory_unlock_plan(**payload))
            elif args.cmd == "inventory-unlock-minimal-fix-set":
                print_json(cf.inventory_unlock_minimal_fix_set(**payload))
            else:
                print_json(cf.inventory_unlock_master_report(**payload))
            return 0
        if args.cmd in {
            "operator-inventory-review-batch-plan",
            "operator-inventory-review-batch-summary",
        }:
            payload = {
                "creator": args.creator,
                "campaign_slug": args.campaign,
                "content_surface": args.content_surface,
                "required_inventory": args.required_inventory,
                "current_inventory": args.current_inventory,
                "target_unlock": args.target_unlock,
                "max_batch_size": args.max_batch_size,
            }
            if args.cmd == "operator-inventory-review-batch-plan":
                print_json(cf.operator_inventory_review_batch_plan(**payload))
            else:
                print_json(cf.operator_inventory_review_batch_summary(**payload))
            return 0
        if args.cmd in {
            "operator-review-simulator",
            "operator-review-scenarios",
            "operator-review-efficiency-report",
            "operator-review-minimum-certification-path",
            "operator-review-master-report",
        }:
            payload = {
                "creator": args.creator,
                "campaign_slug": args.campaign,
                "content_surface": args.content_surface,
                "required_inventory": args.required_inventory,
                "current_inventory": args.current_inventory,
            }
            if args.cmd == "operator-review-simulator":
                print_json(cf.operator_review_simulator(**payload))
            elif args.cmd == "operator-review-scenarios":
                print_json(cf.operator_review_scenarios(**payload))
            elif args.cmd == "operator-review-efficiency-report":
                print_json(cf.operator_review_efficiency_report(**payload))
            elif args.cmd == "operator-review-minimum-certification-path":
                print_json(cf.operator_review_minimum_certification_path(**payload))
            else:
                print_json(cf.operator_review_master_report(**payload))
            return 0
        if args.cmd in {
            "fresh-schedule-safe-production-plan",
            "fresh-reel-production-batch-plan",
            "fresh-reel-production-capacity-plan",
            "fresh-reel-production-master-report",
        }:
            payload = {
                "creator": args.creator,
                "campaign_slug": args.campaign,
                "target_schedule_safe_inventory": args.target_schedule_safe_inventory,
                "current_inventory": args.current_inventory,
                "caption_versions_per_parent": args.caption_versions_per_parent,
                "variants_per_caption": args.variants_per_caption,
                "batch_schedule_safe_target": args.batch_schedule_safe_target,
            }
            if args.cmd == "fresh-schedule-safe-production-plan":
                print_json(cf.fresh_schedule_safe_production_plan(**payload))
            elif args.cmd == "fresh-reel-production-batch-plan":
                print_json(cf.fresh_reel_production_batch_plan(**payload))
            elif args.cmd == "fresh-reel-production-capacity-plan":
                print_json(cf.fresh_reel_production_capacity_plan(**payload))
            else:
                print_json(cf.fresh_reel_production_master_report(**payload))
            return 0
        if args.cmd == "road-to-200-accounts":
            print_json(cf.road_to_200_accounts())
            return 0
        if args.cmd == "reel-factory-parent-throughput-proof":
            print_json(
                cf.reel_factory_parent_throughput_proof(
                    required_parents_per_day=args.required_parents_per_day,
                    lookback_days=args.lookback_days,
                )
            )
            return 0
        if args.cmd == "reel-factory-yield-analysis":
            print_json(cf.reel_factory_yield_analysis())
            return 0
        if args.cmd == "reel-factory-failure-analysis":
            print_json(cf.reel_factory_failure_analysis())
            return 0
        if args.cmd == "reel-factory-capacity-model":
            print_json(
                cf.reel_factory_capacity_model(
                    required_parents_per_day=args.required_parents_per_day,
                )
            )
            return 0
        if args.cmd == "reel-factory-200-account-readiness":
            print_json(cf.reel_factory_200_account_readiness())
            return 0
        if args.cmd == "reel-factory-master-report":
            print_json(cf.reel_factory_master_report())
            return 0
        if args.cmd == "parent-factory-yield-waterfall":
            print_json(
                cf.parent_factory_yield_waterfall(
                    required_parents_per_day=args.required_parents_per_day,
                )
            )
            return 0
        if args.cmd == "parent-factory-loss-analysis":
            print_json(
                cf.parent_factory_loss_analysis(
                    required_parents_per_day=args.required_parents_per_day,
                )
            )
            return 0
        if args.cmd == "parent-factory-rejection-report":
            print_json(cf.parent_factory_rejection_report())
            return 0
        if args.cmd == "parent-factory-discoverability-loss-analysis":
            print_json(cf.parent_factory_discoverability_loss_analysis())
            return 0
        if args.cmd == "discoverability-intake-gate":
            print_json(
                cf.discoverability_intake_gate(_load_json(args.payload_json) or {})
            )
            return 0
        if args.cmd == "discoverability-generation-gate":
            print_json(
                cf.discoverability_generation_gate(_load_json(args.payload_json) or {})
            )
            return 0
        if args.cmd == "discoverability-pre-render-gate":
            print_json(
                cf.discoverability_pre_render_gate(_load_json(args.payload_json) or {})
            )
            return 0
        if args.cmd == "discoverability-violation-origin-map":
            print_json(cf.discoverability_violation_origin_map())
            return 0
        if args.cmd == "parent-factory-recoverable-yield":
            print_json(cf.parent_factory_recoverable_yield())
            return 0
        if args.cmd == "parent-factory-throughput-recovery-plan":
            print_json(cf.parent_factory_throughput_recovery_plan())
            return 0
        if args.cmd == "parent-factory-53-parent-feasibility":
            print_json(cf.parent_factory_53_parent_feasibility())
            return 0
        if args.cmd == "parent-factory-secondary-loss-analysis":
            print_json(cf.parent_factory_secondary_loss_analysis())
            return 0
        if args.cmd == "parent-factory-waterfall-after-discoverability":
            print_json(cf.parent_factory_waterfall_after_discoverability())
            return 0
        if args.cmd == "parent-factory-true-yield-model":
            print_json(cf.parent_factory_true_yield_model())
            return 0
        if args.cmd == "parent-factory-realistic-53-parent-plan":
            print_json(cf.parent_factory_realistic_53_parent_plan())
            return 0
        if args.cmd == "capture-publishability-rejection-evidence":
            print_json(cf.capture_publishability_rejection_evidence(args.asset_id))
            return 0
        if args.cmd == "parent-factory-quality-gate-analysis":
            print_json(cf.parent_factory_quality_gate_analysis())
            return 0
        if args.cmd == "parent-factory-optimization-plan":
            print_json(
                cf.parent_factory_optimization_plan(
                    required_parents_per_day=args.required_parents_per_day,
                )
            )
            return 0
        if args.cmd == "parent-factory-master-optimization-report":
            print_json(
                cf.parent_factory_master_optimization_report(
                    required_parents_per_day=args.required_parents_per_day,
                )
            )
            return 0
        if args.cmd == "parent-factory-autopilot-plan":
            print_json(
                cf.parent_factory_autopilot_plan(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                )
            )
            return 0
        if args.cmd == "parent-factory-shortfall-report":
            print_json(
                cf.parent_factory_shortfall_report(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                )
            )
            return 0
        if args.cmd == "parent-factory-production-targets":
            print_json(
                cf.parent_factory_production_targets(
                    accounts=args.accounts,
                    posts_per_account_per_day=args.posts_per_account_per_day,
                )
            )
            return 0
        if args.cmd == "exception-queue-report":
            print_json(
                cf.exception_queue_report(
                    daily_plan=_load_json(args.daily_plan_json),
                    execution_readiness=_load_json(args.execution_readiness_json),
                )
            )
            return 0
        if args.cmd == "exception-queue-summary":
            print_json(
                cf.exception_queue_summary(
                    daily_plan=_load_json(args.daily_plan_json),
                    execution_readiness=_load_json(args.execution_readiness_json),
                )
            )
            return 0
        if args.cmd == "exception-queue-priority-report":
            print_json(
                cf.exception_queue_priority_report(
                    daily_plan=_load_json(args.daily_plan_json),
                    execution_readiness=_load_json(args.execution_readiness_json),
                )
            )
            return 0
        if args.cmd == "exception-queue-owner-report":
            print_json(
                cf.exception_queue_owner_report(
                    daily_plan=_load_json(args.daily_plan_json),
                    execution_readiness=_load_json(args.execution_readiness_json),
                )
            )
            return 0
        if args.cmd == "failure-injection-suite":
            print_json(cf.failure_injection_suite())
            return 0
        if args.cmd == "idempotency-proof":
            print_json(cf.idempotency_proof())
            return 0
        if args.cmd == "surface-maturity-audit":
            print_json(cf.surface_maturity_audit())
            return 0
        if args.cmd == "surface-readiness-scorecard":
            print_json(cf.surface_readiness_scorecard())
            return 0
        if args.cmd == "operator-load-audit":
            print_json(cf.operator_load_audit())
            return 0
        if args.cmd == "single-source-of-truth-audit":
            print_json(cf.single_source_of_truth_audit())
            return 0
        if args.cmd == "core-complexity-reduction-plan":
            print_json(cf.core_complexity_reduction_plan())
            return 0
        if args.cmd == "creator-os-9.5-readiness-report":
            print_json(cf.creator_os_9_5_readiness_report())
            return 0
        if args.cmd == "creator-os-100-account-proof":
            print_json(cf.creator_os_100_account_proof())
            return 0
        if args.cmd == "creator-os-volume-acceptance-suite":
            print_json(cf.creator_os_volume_acceptance_suite())
            return 0
        if args.cmd == "creator-os-10.0-readiness-report":
            print_json(cf.creator_os_10_0_readiness_report())
            return 0
        if args.cmd == "creator-os-live-100-account-readiness":
            print_json(cf.creator_os_live_100_account_readiness())
            return 0
        if args.cmd == "creator-os-live-account-acceptance":
            print_json(
                cf.creator_os_live_account_acceptance(
                    account_target=args.account_target,
                    content_surface=args.content_surface,
                )
            )
            return 0
        if args.cmd == "creator-os-staged-live-acceptance":
            print_json(
                cf.creator_os_staged_live_acceptance(
                    content_surface=args.content_surface
                )
            )
            return 0
        if args.cmd == "sync-threadsdash-instagram-accounts":
            supabase_url, service_key = _threadsdash_supabase_args(args)
            print_json(
                sync_threadsdash_instagram_accounts(
                    cf,
                    creator=args.creator,
                    match=args.match,
                    user_id=args.user_id,
                    limit=args.limit,
                    supabase_url=supabase_url,
                    supabase_service_role_key=service_key,
                )
            )
            return 0
        if args.cmd == "creator-os-live-scale-runbook":
            print_json(cf.creator_os_live_scale_runbook())
            return 0
        if args.cmd == "creator-os-live-scale-scorecard":
            print_json(cf.creator_os_live_scale_scorecard())
            return 0
        if args.cmd == "parent-factory-production-trial":
            print_json(cf.parent_factory_production_trial())
            return 0
        if args.cmd == "parent-factory-production-scorecard":
            print_json(cf.parent_factory_production_scorecard())
            return 0
        if args.cmd == "parent-factory-real-yield-report":
            print_json(cf.parent_factory_real_yield_report())
            return 0
        if args.cmd == "parent-factory-53-parent-trial":
            print_json(cf.parent_factory_53_parent_trial())
            return 0
        if args.cmd == "parent-factory-trial-results":
            print_json(cf.parent_factory_trial_results())
            return 0
        if args.cmd == "parent-factory-trial-analysis":
            print_json(cf.parent_factory_trial_analysis())
            return 0
        if args.cmd == "parent-factory-post-gate-fresh-batch-proof":
            print_json(cf.parent_factory_post_gate_fresh_batch_proof())
            return 0
        if args.cmd == "discoverability-prevention-audit":
            print_json(cf.discoverability_prevention_audit())
            return 0
        if args.cmd == "discoverability-prevention-scorecard":
            print_json(cf.discoverability_prevention_scorecard())
            return 0
        if args.cmd == "story-certification-proof":
            print_json(
                cf.story_certification_proof(rendered_asset_id=args.rendered_asset_id)
            )
            return 0
        if args.cmd == "story-production-readiness":
            print_json(cf.story_production_readiness())
            return 0
        if args.cmd == "story-proof-gap-analysis":
            print_json(cf.story_proof_gap_analysis())
            return 0
        if args.cmd == "carousel-certification-proof":
            print_json(
                cf.carousel_certification_proof(
                    rendered_asset_id=args.rendered_asset_id
                )
            )
            return 0
        if args.cmd == "carousel-production-readiness":
            print_json(cf.carousel_production_readiness())
            return 0
        if args.cmd == "carousel-proof-gap-analysis":
            print_json(cf.carousel_proof_gap_analysis())
            return 0
        if args.cmd == "creator-os-certification-report":
            print_json(cf.creator_os_certification_report())
            return 0
        if args.cmd == "draft-inventory-gap":
            print_json(
                cf.creator_os_draft_inventory_gap(
                    creator=args.creator,
                    threadsdash_report=_load_json(args.threadsdash_report_json),
                    schedule_plan=_load_json(args.schedule_plan_json),
                    time_plan=_load_json(args.time_plan_json),
                )
            )
            return 0
        if args.cmd == "execution-readiness":
            print_json(
                cf.creator_os_execution_readiness(
                    creator=args.creator,
                    requested_count=args.requested_count,
                    threadsdash_report=_load_json(args.threadsdash_report_json),
                    schedule_plan=_load_json(args.schedule_plan_json),
                    time_plan=_load_json(args.time_plan_json),
                )
            )
            return 0
        if args.cmd == "account-tiers":
            print_json(
                cf.creator_os_account_tiers(
                    creator=args.creator,
                    threadsdash_report=_load_json(args.threadsdash_report_json),
                )
            )
            return 0
        if args.cmd == "account-health-report":
            print_json(
                cf.creator_os_account_health_report(
                    creator=args.creator,
                    threadsdash_report=_load_json(args.threadsdash_report_json),
                )
            )
            return 0
        if args.cmd == "restricted-account-report":
            print_json(
                cf.creator_os_restricted_account_report(
                    creator=args.creator,
                    threadsdash_report=_load_json(args.threadsdash_report_json),
                )
            )
            return 0
        if args.cmd == "manual-review-queue":
            print_json(
                cf.creator_os_manual_review_queue(
                    creator=args.creator,
                    threadsdash_report=_load_json(args.threadsdash_report_json),
                )
            )
            return 0
        if args.cmd == "account-warmup-report":
            print_json(
                cf.creator_os_account_warmup_report(
                    creator=args.creator,
                    threadsdash_report=_load_json(args.threadsdash_report_json),
                )
            )
            return 0
        if args.cmd == "lifecycle-dashboard":
            posts_payload = _load_json(args.threadsdash_posts_json)
            posts = None
            if isinstance(posts_payload, dict):
                raw_posts = (
                    posts_payload.get("posts")
                    or posts_payload.get("rows")
                    or posts_payload.get("items")
                )
                if isinstance(raw_posts, list):
                    posts = [item for item in raw_posts if isinstance(item, dict)]
            print_json(
                cf.creator_os_lifecycle_dashboard(
                    campaign=args.campaign,
                    user_id=args.user_id,
                    threadsdash_posts=posts,
                    include_threadsdash=args.include_threadsdash,
                )
            )
            return 0
        if args.cmd == "creator-surface-summary":
            print_json(
                cf.creator_surface_summary(
                    creator=args.creator,
                    date=args.date,
                )
            )
            return 0
        if args.cmd == "account-surface-summary":
            print_json(
                cf.account_surface_summary(
                    creator=args.creator,
                    date=args.date,
                    account_id=args.account_id,
                )
            )
            return 0
        if args.cmd == "creator-surface-gap-report":
            print_json(
                cf.creator_surface_gap_report(
                    creator=args.creator,
                    date=args.date,
                )
            )
            return 0
        if args.cmd == "carousel-integrity-report":
            print_json(
                cf.carousel_integrity_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    rendered_asset_id=args.rendered_asset_id,
                )
            )
            return 0
        if args.cmd == "carousel-child-metrics-plan":
            print_json(
                cf.carousel_child_metrics_plan(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    rendered_asset_id=args.rendered_asset_id,
                )
            )
            return 0
        if args.cmd == "creative-knowledge-base":
            print_json(
                cf.creative_knowledge_base(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-pattern-report":
            print_json(
                cf.creative_pattern_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-surface-report":
            print_json(
                cf.creative_surface_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-account-tier-report":
            print_json(
                cf.creative_account_tier_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-caption-report":
            print_json(
                cf.creative_caption_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-audio-report":
            print_json(
                cf.creative_audio_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-window-report":
            print_json(
                cf.creative_window_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-performance-analysis":
            print_json(
                cf.creative_performance_analysis(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creator-learning-summary":
            print_json(
                cf.creator_learning_summary(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "next-content-recommendations":
            print_json(
                cf.next_content_recommendations(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-learning-confidence-model":
            print_json(
                cf.creative_learning_confidence_model(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                )
            )
            return 0
        if args.cmd == "creative-fatigue-report":
            print_json(
                cf.creative_fatigue_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "creative-surface-comparison-report":
            print_json(
                cf.creative_surface_comparison_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "recommendation-quality-audit":
            print_json(
                cf.recommendation_quality_audit(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "tribev2-reel-analysis":
            print_json(
                cf.tribev2_reel_analysis(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    minimum_sample_size=args.minimum_sample_size,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "tribev2-reel-review":
            print_json(
                cf.tribev2_reel_review(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    sort_by=args.sort_by,
                    bucket=args.bucket,
                    limit=args.limit,
                    contact_sheet=args.contact_sheet,
                    show_metrics=True
                    if args.show_metrics or not args.blind_mode
                    else False,
                    show_tribe_score=not args.hide_tribe_score,
                    blind_mode=args.blind_mode,
                )
            )
            return 0
        if args.cmd == "tribev2-holdout-pilot-review":
            print_json(
                cf.tribev2_holdout_pilot_review(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    limit=args.limit,
                    contact_sheet=args.contact_sheet,
                )
            )
            return 0
        if args.cmd == "caption-quality-repair-plan":
            print_json(
                cf.caption_quality_repair_plan(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                    content_surface=args.content_surface,
                    limit=args.limit,
                )
            )
            return 0
        if args.cmd == "story-inventory-report":
            print_json(
                cf.story_inventory_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                )
            )
            return 0
        if args.cmd == "story-gap-report":
            print_json(
                cf.story_gap_report(
                    creator=args.creator,
                    date=args.date,
                )
            )
            return 0
        if args.cmd == "story-quality-report":
            print_json(
                cf.story_quality_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                )
            )
            return 0
        if args.cmd == "story-intent-report":
            print_json(
                cf.story_intent_report(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                )
            )
            return 0
        if args.cmd == "story-mix-plan":
            print_json(
                cf.story_mix_plan(
                    creator=args.creator,
                )
            )
            return 0
        if args.cmd == "story-calendar-plan":
            print_json(
                cf.story_calendar_plan(
                    creator=args.creator,
                )
            )
            return 0
        if args.cmd == "story-intent-summary":
            print_json(
                cf.story_intent_summary(
                    creator=args.creator,
                    campaign_slug=args.campaign,
                )
            )
            return 0
        if args.cmd == "decision-ledger-preview":
            print_json(cf.decision_ledger_preview(**_decision_ledger_kwargs(args)))
            return 0
        if args.cmd == "decision-ledger-report":
            print_json(cf.decision_ledger_report(**_decision_ledger_kwargs(args)))
            return 0
        if args.cmd == "decision-ledger-summary":
            print_json(cf.decision_ledger_summary(**_decision_ledger_kwargs(args)))
            return 0
        if args.cmd == "decision-ledger-by-creator":
            print_json(cf.decision_ledger_by_creator(**_decision_ledger_kwargs(args)))
            return 0
        if args.cmd == "decision-ledger-by-account":
            print_json(
                cf.decision_ledger_by_account(
                    account_id=args.account_id, **_decision_ledger_kwargs(args)
                )
            )
            return 0
        if args.cmd == "decision-ledger-by-surface":
            print_json(
                cf.decision_ledger_by_surface(
                    surface=args.surface, **_decision_ledger_kwargs(args)
                )
            )
            return 0
        if args.cmd == "decision-ledger-by-decision-type":
            print_json(
                cf.decision_ledger_by_decision_type(
                    decision_type=args.decision_type, **_decision_ledger_kwargs(args)
                )
            )
            return 0
        if args.cmd == "account-story-status":
            print_json(
                cf.account_story_status(
                    account_id=args.account_id,
                    creator=args.creator,
                    date=args.date,
                )
            )
            return 0
        if args.cmd == "creator-story-summary":
            print_json(
                cf.creator_story_summary(
                    creator=args.creator,
                    date=args.date,
                )
            )
            return 0
    finally:
        cf.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
