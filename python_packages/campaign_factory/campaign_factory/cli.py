from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import uvicorn

from .adapters.contentforge import audit_campaign
from .adapters.threadsdash import (
    SupabaseRestClient,
    clear_preview_schedule,
    evaluate_export_readiness,
    export_threadsdash,
    preflight_supabase,
    promote_preview_schedule,
    safe_live_smoke_export,
    summarize_threadsdash_usage,
    sync_threadsdash_account_assignments,
    sync_performance_snapshots,
    verify_threadsdash_export,
)
from .config import get_settings
from .control import operator_control_check
from .core import CampaignFactory
from .closed_loop_proof import (
    DEFAULT_STACEY_PROMPT_PATH,
    build_account_routing_audit,
    run_stacey_closed_loop_proof,
)
from .readiness_report import build_mass_production_readiness_report
from .reel_ledger_promotion import promote_reel_ledger
from .variation_stage import run_variation_stage
from .motion_edit_stage import run_motion_edit_stage


def print_json(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def load_json_object(path: str | None) -> dict | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def decision_ledger_kwargs(args) -> dict:
    return {
        "creator": args.creator,
        "date": args.date,
        "threadsdash_report": load_json_object(args.threadsdash_report_json),
        "schedule_plan": load_json_object(args.schedule_plan_json),
        "time_plan": load_json_object(args.time_plan_json),
        "winner_expansion_report": load_json_object(args.winner_expansion_report_json),
        "winner_expansion_plan": load_json_object(args.winner_expansion_plan_json),
        "variant_inventory_plan": load_json_object(args.variant_inventory_plan_json),
        "variant_metrics_rollup": load_json_object(args.variant_metrics_rollup_json),
        "account_tiers": load_json_object(args.account_tiers_json),
    }


def load_hooks(path: str | None, values: list[str] | None) -> list[str | dict]:
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("hooks") or []
        if isinstance(data, list):
            return data
    return values or []


def main() -> int:
    parser = argparse.ArgumentParser(prog="campaign-factory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--contentforge-base-url", default=os.environ.get("CONTENTFORGE_BASE_URL"))
    doctor.add_argument("--check-http", action="store_true", help="Also check whether ContentForge is responding over HTTP")

    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8877)

    imp = sub.add_parser("import-folder")
    imp.add_argument("folder")
    imp.add_argument("--campaign", required=True)
    imp.add_argument("--model", required=True)
    imp.add_argument("--model-name")
    imp.add_argument("--platform", default="instagram")
    imp.add_argument("--account", action="append", default=[])
    imp.add_argument("--source-prompt")
    imp.add_argument("--notes")

    prep = sub.add_parser("prepare-reel")
    prep.add_argument("--campaign", required=True)
    prep.add_argument("--hooks")
    prep.add_argument("--hook", action="append", default=[])
    prep.add_argument("--recipes", nargs="*", default=None)
    prep.add_argument("--caption-color", default="auto")
    prep.add_argument("--notes")
    prep.add_argument("--force-new", action="store_true")

    run = sub.add_parser("run-reel")
    run.add_argument("--campaign", required=True)
    run.add_argument("--workers", type=int, default=3)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--band", choices=["top", "center", "bottom"], default="center")
    run.add_argument("--color", choices=["light", "dark", "auto"], default="light")
    run.add_argument("--style", choices=["classic", "meme", "ig", "thin", "soft", "bubble", "auto"], default="ig")
    run.add_argument("--font", default="Instagram Sans Condensed")
    run.add_argument("--no-phone-finalize", action="store_true")
    run.add_argument("--rerender-all", action="store_true")
    run.add_argument("--max-outputs-per-clip", type=int, default=None)

    sync = sub.add_parser("sync-reel")
    sync.add_argument("--campaign", required=True)

    variation = sub.add_parser("variation")
    variation_sub = variation.add_subparsers(dest="variation_cmd", required=True)
    variation_run = variation_sub.add_parser("run")
    variation_run.add_argument("--campaign", required=True)
    variation_run.add_argument("--preset", default="ig_subtle")
    variation_run.add_argument("--rendered-asset-id", action="append", default=[])
    variation_run.add_argument("--dry-run", action="store_true")
    variation_run.add_argument("--apply", action="store_true")

    animation = sub.add_parser("animation")
    animation_sub = animation.add_subparsers(dest="animation_cmd", required=True)
    motion_edit = animation_sub.add_parser("motion-edit")
    motion_edit.add_argument("--campaign", required=True)
    motion_edit.add_argument("--still", required=True)
    caption_group = motion_edit.add_mutually_exclusive_group(required=True)
    caption_group.add_argument("--caption")
    caption_group.add_argument("--caption-file")
    motion_edit.add_argument("--duration", type=float, default=5.0)
    motion_edit.add_argument("--dry-run", action="store_true")
    motion_edit.add_argument("--apply", action="store_true")
    motion_edit.add_argument("--allow-upscale", action="store_true")
    motion_edit.add_argument("--enable-variation", action="store_true")
    motion_edit.add_argument("--variation-preset", default="ig_subtle")

    audit = sub.add_parser("audit")
    audit.add_argument("--campaign", required=True)
    audit.add_argument("--min-score", type=int, default=85)
    audit.add_argument("--contentforge-base-url", default=os.environ.get("CONTENTFORGE_BASE_URL"))
    audit.add_argument("--layer", action="append", default=[])

    approve = sub.add_parser("approve")
    approve.add_argument("--rendered-asset-id", required=True)
    approve.add_argument("--notes")
    approve.add_argument("--force-unsafe-audit", action="store_true", help="Allow approval even when audit is missing or not an approved candidate")

    review = sub.add_parser("review-decision")
    review.add_argument("--rendered-asset-id", required=True)
    review.add_argument("--decision", choices=["approved", "rejected"], required=True)
    review.add_argument("--notes")
    review.add_argument("--force-unsafe-audit", action="store_true", help="Allow approval even when audit is missing or not an approved candidate")

    readiness = sub.add_parser("export-readiness")
    readiness.add_argument("--campaign", required=True)
    readiness.add_argument("--user-id", required=True)
    readiness.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    readiness.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    readiness.add_argument("--limit", type=int, default=1000)
    readiness.add_argument("--content-pillar")
    readiness.add_argument("--cta-type")
    readiness.add_argument("--language")
    readiness.add_argument("--schedule-mode", choices=["draft", "preview", "live"], default="draft")

    mass_ready = sub.add_parser("readiness-report")
    mass_ready.add_argument("--campaign-id", required=True)
    mass_ready.add_argument("--days", type=int, default=7)
    mass_ready.add_argument("--user-id")
    mass_ready.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    mass_ready.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    mass_ready.add_argument("--limit", type=int, default=1000)
    mass_ready.add_argument("--format", choices=["json", "markdown"], default="json")

    caption_outcome = sub.add_parser("caption-outcome-report")
    caption_outcome.add_argument("--campaign", required=True)

    routing_audit = sub.add_parser("account-routing-audit")
    routing_audit.add_argument("--creator", required=True)
    routing_audit.add_argument("--user-id", required=True)
    routing_audit.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    routing_audit.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY"),
    )

    closed_loop = sub.add_parser("closed-loop-proof")
    closed_loop.add_argument("--campaign", default="stacey_closed_loop")
    closed_loop.add_argument("--user-id", default=os.environ.get("THREADSDASH_USER_ID"))
    closed_loop.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[1]))
    closed_loop.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    closed_loop.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    closed_loop.add_argument("--supabase-storage-bucket", default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"))
    closed_loop.add_argument("--operator", default=os.environ.get("USER"))
    closed_loop.add_argument("--approval-reason")
    closed_loop.add_argument("--approved-rendered-asset-id")
    closed_loop.add_argument("--prompt-path", default=str(DEFAULT_STACEY_PROMPT_PATH))
    closed_loop.add_argument("--schedule-mode", choices=["live"], default="live")
    closed_loop.add_argument("--allow-warnings", action="store_true")
    closed_loop.add_argument("--allow-live-export", action="store_true")
    closed_loop.add_argument("--read-only-verification", action="store_true")
    closed_loop.add_argument("--existing-threadsdash-post-id")
    closed_loop.add_argument("--limit", type=int, default=1000)

    promote_reel = sub.add_parser("promote-reel-ledger")
    promote_reel.add_argument("--campaign", required=True)
    promote_reel.add_argument("--reel-factory-root", default=None)
    promote_reel.add_argument("--days", type=int, default=7)
    promote_reel.add_argument("--apply", action="store_true")
    promote_reel.add_argument("--format", choices=["json"], default="json")

    export = sub.add_parser("export-threadsdash")
    export.add_argument("--campaign", required=True)
    export.add_argument("--user-id", required=True)
    export.add_argument("--dry-run", action="store_true")
    export.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    export.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    export.add_argument("--supabase-storage-bucket", default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"))
    export.add_argument("--allow-warnings", action="store_true")
    export.add_argument("--content-pillar")
    export.add_argument("--cta-type")
    export.add_argument("--language")
    export.add_argument("--max-drafts", type=int)
    export.add_argument("--rendered-asset-id", action="append", default=[])
    export.add_argument("--schedule-mode", choices=["draft", "preview", "live"], default="draft")
    export.add_argument("--enable-variation", action="store_true")
    export.add_argument("--variation-preset", default="ig_subtle")

    preflight = sub.add_parser("supabase-preflight")
    preflight.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    preflight.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    preflight.add_argument("--supabase-storage-bucket", default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"))

    verify = sub.add_parser("verify-threadsdash-export")
    verify.add_argument("export_manifest")
    verify.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    verify.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))

    live_smoke = sub.add_parser("safe-live-smoke")
    live_smoke.add_argument("--campaign", required=True)
    live_smoke.add_argument("--user-id", required=True)
    live_smoke.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    live_smoke.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    live_smoke.add_argument("--supabase-storage-bucket", default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"))
    live_smoke.add_argument("--allow-warnings", action="store_true")

    usage = sub.add_parser("threadsdash-usage")
    usage.add_argument("--campaign", required=True)
    usage.add_argument("--user-id", required=True)
    usage.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    usage.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    usage.add_argument("--limit", type=int, default=1000)

    assignment_sync = sub.add_parser("sync-threadsdash-assignments")
    assignment_sync.add_argument("--campaign", required=True)
    assignment_sync.add_argument("--user-id", required=True)
    assignment_sync.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    assignment_sync.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    assignment_sync.add_argument("--limit", type=int, default=1000)

    perf_sync = sub.add_parser("sync-performance")
    perf_sync.add_argument("--campaign", required=True)
    perf_sync.add_argument("--user-id", required=True)
    perf_sync.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    perf_sync.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    perf_sync.add_argument("--limit", type=int, default=1000)

    perf_summary = sub.add_parser("performance-summary")
    perf_summary.add_argument("--campaign", required=True)

    surface_inventory = sub.add_parser("multi-surface-inventory-audit")
    surface_inventory.add_argument("--creator", required=True)
    surface_inventory.add_argument("--campaign")

    surface_obligations = sub.add_parser("account-surface-obligations-plan")
    surface_obligations.add_argument("--creator", required=True)
    surface_obligations.add_argument("--date", required=True)

    account_needs = sub.add_parser("account-content-needs")
    account_needs.add_argument("--account-id", required=True)
    account_needs.add_argument("--creator")
    account_needs.add_argument("--date", required=True)

    account_status = sub.add_parser("account-surface-status")
    account_status.add_argument("--account-id", required=True)
    account_status.add_argument("--creator")
    account_status.add_argument("--date", required=True)

    creator_needs = sub.add_parser("creator-content-needs")
    creator_needs.add_argument("--creator", required=True)
    creator_needs.add_argument("--date", required=True)

    surface_gap = sub.add_parser("surface-gap-report")
    surface_gap.add_argument("--creator", required=True)
    surface_gap.add_argument("--date", required=True)
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

    surface_handoff = sub.add_parser("surface-handoff-readiness-report")
    surface_handoff.add_argument("--creator")
    surface_handoff.add_argument("--campaign")
    surface_handoff.add_argument("--rendered-asset-id")

    surface_draft = sub.add_parser("surface-draft-proof")
    surface_draft.add_argument("--creator")
    surface_draft.add_argument("--campaign")
    surface_draft.add_argument("--rendered-asset-id")

    carousel_integrity = sub.add_parser("carousel-integrity-report")
    carousel_integrity.add_argument("--creator")
    carousel_integrity.add_argument("--campaign")
    carousel_integrity.add_argument("--rendered-asset-id")

    carousel_metrics = sub.add_parser("carousel-child-metrics-plan")
    carousel_metrics.add_argument("--creator")
    carousel_metrics.add_argument("--campaign")
    carousel_metrics.add_argument("--rendered-asset-id")

    register_surface = sub.add_parser("register-surface-asset")
    register_surface.add_argument("--input", nargs="+", required=True)
    register_surface.add_argument("--surface", choices=["feed_single", "story", "feed_carousel"], required=True)
    register_surface.add_argument("--creator", required=True)
    register_surface.add_argument("--campaign", required=True)
    register_surface.add_argument("--instagram-post-caption")
    register_surface.add_argument("--target-ratio")
    register_surface.add_argument("--model")
    register_surface.add_argument("--operator")
    register_surface.add_argument("--story-asset-class")
    register_surface.add_argument("--story-cta-type")
    register_surface.add_argument("--story-cta-text")
    register_surface.add_argument("--story-cta-target-url")
    register_surface.add_argument("--story-intent")
    register_surface.add_argument("--story-goal")
    register_surface.add_argument("--story-style")
    register_surface.add_argument("--snapchat-username")
    register_surface.add_argument("--snapchat-display-name")
    register_surface.add_argument("--snapchat-cta-text")

    health = sub.add_parser("campaign-health")
    health.add_argument("--campaign", required=True)

    lifecycle = sub.add_parser("lifecycle-report")
    lifecycle.add_argument("--campaign", required=True)
    lifecycle.add_argument("--user-id")
    lifecycle.add_argument("--include-threadsdash", choices=["auto", "live", "off"], default="auto")
    lifecycle.add_argument("--state")
    lifecycle.add_argument("--blocking-reason")
    lifecycle.add_argument("--rendered-asset-id")
    lifecycle.add_argument("--json", action="store_true", help="Print JSON output; retained for explicit operator intent")

    publishability = sub.add_parser("explain-publishability")
    publishability.add_argument("--rendered-asset-id", required=True)
    publishability.add_argument("--distribution-plan-id")

    parent_register = sub.add_parser("register-parent-reel")
    parent_register.add_argument("--rendered-asset-id", required=True)
    parent_register.add_argument("--operator")
    parent_register.add_argument("--status", default="active")
    parent_register.add_argument("--metadata-json")

    variant_inventory = sub.add_parser("parent-variant-inventory")
    variant_inventory.add_argument("--campaign", required=True)

    variant_plan = sub.add_parser("variant-plan")
    variant_plan.add_argument("--parent-asset-id", required=True)
    variant_plan.add_argument("--count", type=int, default=10)
    variant_plan.add_argument("--contentforge-preset", default="caption_safe")
    variant_plan.add_argument("--cooldown-days", type=int, default=14)
    variant_plan.add_argument("--dry-run", action="store_true", default=True)

    generate_variants = sub.add_parser("generate-variants")
    generate_variants.add_argument("--parent-asset-id", required=True)
    generate_variants.add_argument("--caption-version-id")
    generate_variants.add_argument("--count", type=int, default=10)
    generate_variants.add_argument("--contentforge-preset", default="caption_safe")
    generate_variants.add_argument("--contentforge-base-url", default=os.environ.get("CONTENTFORGE_BASE_URL"))
    generate_variants.add_argument("--source-media-path")
    generate_variants.add_argument("--dry-run", action="store_true")

    winner_plan = sub.add_parser("winner-expansion-plan")
    winner_plan.add_argument("--input-json", help="JSON string or path containing creator, parentAssetId, targetVariants, and preset")
    winner_plan.add_argument("--creator")
    winner_plan.add_argument("--parent-asset-id")
    winner_plan.add_argument("--target-variants", type=int)
    winner_plan.add_argument("--preset")

    caption_plan = sub.add_parser("caption-family-plan")
    caption_plan.add_argument("--input-json", help="JSON string or path containing creator, parentAssetId, requestedCaptionVersions, style, and dryRun")
    caption_plan.add_argument("--creator")
    caption_plan.add_argument("--parent-asset-id")
    caption_plan.add_argument("--requested-caption-versions", type=int)
    caption_plan.add_argument("--style")
    caption_plan.add_argument("--dry-run", action="store_true")

    caption_create = sub.add_parser("caption-family-create")
    caption_create.add_argument("--input-json", help="JSON string or path containing creator, parentAssetId, requestedCaptionVersions, style, and dryRun")
    caption_create.add_argument("--creator")
    caption_create.add_argument("--parent-asset-id")
    caption_create.add_argument("--requested-caption-versions", type=int)
    caption_create.add_argument("--style")
    caption_create.add_argument("--dry-run", action="store_true")

    inventory_plan = sub.add_parser("variant-inventory-plan")
    inventory_plan.add_argument("--input-json", help="JSON string or path containing creator, campaign, targetDraftShortfall, preset, maxVariantsPerParent, minimumRecommendedPerParent, and dryRun")
    inventory_plan.add_argument("--creator")
    inventory_plan.add_argument("--campaign")
    inventory_plan.add_argument("--target-draft-shortfall", type=int)
    inventory_plan.add_argument("--preset")
    inventory_plan.add_argument("--max-variants-per-parent", type=int)
    inventory_plan.add_argument("--minimum-recommended-per-parent", type=int)
    inventory_plan.add_argument("--dry-run", action="store_true")

    winner_expansion = sub.add_parser("winner-expansion-report")
    winner_expansion.add_argument("--campaign", required=True)
    winner_expansion.add_argument("--min-views", type=int, default=1000)
    winner_expansion.add_argument("--min-reach", type=int)
    winner_expansion.add_argument("--min-followers", type=int, default=1)

    concept_registry = sub.add_parser("concept-registry")
    concept_registry.add_argument("--creator", required=True)
    concept_registry.add_argument("--campaign")
    concept_registry.add_argument("--min-views", type=int, default=1000)
    concept_registry.add_argument("--min-reach", type=int)
    concept_registry.add_argument("--min-followers", type=int, default=1)

    winner_registry = sub.add_parser("winner-registry")
    winner_registry.add_argument("--creator", required=True)
    winner_registry.add_argument("--campaign")
    winner_registry.add_argument("--min-views", type=int, default=1000)
    winner_registry.add_argument("--min-reach", type=int)
    winner_registry.add_argument("--min-followers", type=int, default=1)

    winner_patterns = sub.add_parser("winner-patterns")
    winner_patterns.add_argument("--creator", required=True)
    winner_patterns.add_argument("--campaign")
    winner_patterns.add_argument("--min-views", type=int, default=1000)
    winner_patterns.add_argument("--min-reach", type=int)
    winner_patterns.add_argument("--min-followers", type=int, default=1)

    winner_kb = sub.add_parser("winner-knowledge-base")
    winner_kb.add_argument("--creator", required=True)
    winner_kb.add_argument("--campaign")
    winner_kb.add_argument("--min-views", type=int, default=1000)
    winner_kb.add_argument("--min-reach", type=int)
    winner_kb.add_argument("--min-followers", type=int, default=1)

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
    tribev2_review.add_argument("--sort-by", default="meanAbsActivation", choices=["meanAbsActivation", "peakAbsActivation", "stdActivation"])
    tribev2_review.add_argument("--bucket", default="top", choices=["top", "bottom", "both"])
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

    inventory_request = sub.add_parser("recommended-inventory-request-plan")
    inventory_request.add_argument("--creator", required=True)
    inventory_request.add_argument("--target-count", type=int)
    inventory_request.add_argument("--daily-plan-json")
    inventory_request.add_argument("--variant-inventory-plan-json")

    variant_rollup = sub.add_parser("variant-metrics-rollup")
    variant_rollup.add_argument("--campaign", required=True)

    asset_detail = sub.add_parser("asset-detail")
    asset_detail.add_argument("--rendered-asset-id", required=True)

    campaign_ready = sub.add_parser("campaign-readiness")
    campaign_ready.add_argument("--campaign", required=True)
    campaign_ready.add_argument("--user-id")

    assign = sub.add_parser("assign-account")
    assign.add_argument("--rendered-asset-id", required=True)
    assign.add_argument("--account-id")
    assign.add_argument("--instagram-account-id")
    assign.add_argument("--planned-window-start")
    assign.add_argument("--planned-window-end")
    assign.add_argument("--notes")

    profile = sub.add_parser("model-account-profile")
    profile.add_argument("--model", required=True)
    profile.add_argument("--label")
    profile.add_argument("--instagram-account-id", action="append", default=[])
    profile.add_argument("--account-group-name", action="append", default=[])
    profile.add_argument("--handle-pattern", action="append", default=[])
    profile.add_argument("--smart-link")
    profile.add_argument("--story-cta")

    dist = sub.add_parser("distribution-plan")
    dist.add_argument("--rendered-asset-id", required=True)
    dist.add_argument("--surface", choices=["regular_reel", "trial_reel", "story", "story_cta", "feed_single"], default="regular_reel")
    dist.add_argument("--account-id")
    dist.add_argument("--instagram-account-id")
    dist.add_argument("--planned-window-start")
    dist.add_argument("--planned-window-end")
    dist.add_argument("--paired-rendered-asset-id")
    dist.add_argument("--reason-code")
    dist.add_argument("--smart-link")
    dist.add_argument("--cta-text")
    dist.add_argument("--instagram-trial-reels", action="store_true")
    dist.add_argument("--trial-graduation-strategy", choices=["MANUAL", "SS_PERFORMANCE"])

    plan_dist = sub.add_parser("plan-distribution")
    plan_dist.add_argument("--campaign", required=True)
    plan_dist.add_argument("--user-id", required=True)
    plan_dist.add_argument("--mode", choices=["preview", "live"], default="preview")
    plan_dist.add_argument("--strategy", choices=["trial-heavy"], default="trial-heavy")
    plan_dist.add_argument("--no-replace", action="store_true")

    promote = sub.add_parser("promote-preview-schedule")
    promote.add_argument("--campaign", required=True)
    promote.add_argument("--user-id", required=True)
    promote.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    promote.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    promote.add_argument("--limit", type=int, default=1000)

    clear_schedule = sub.add_parser("clear-preview-schedule")
    clear_schedule.add_argument("--campaign", required=True)
    clear_schedule.add_argument("--user-id", required=True)
    clear_schedule.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    clear_schedule.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    clear_schedule.add_argument("--limit", type=int, default=1000)
    clear_schedule.add_argument("--reason", default="audio_workflow_not_ready")

    account_plan = sub.add_parser("account-plan")
    account_plan.add_argument("--campaign", required=True)
    account_plan.add_argument("--user-id", required=True)
    account_plan.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    account_plan.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))

    ranking = sub.add_parser("ranking")
    ranking.add_argument("--campaign", required=True)

    autonomy = sub.add_parser("autonomy-policy")
    autonomy.add_argument("--set", choices=["level_1", "level_2", "level_3"], dest="set_level")

    trust_summary = sub.add_parser("trust-summary")
    trust_summary.add_argument("--campaign", required=True)

    recommendation_accuracy = sub.add_parser("recommendation-accuracy")
    recommendation_accuracy.add_argument("--campaign", required=True)
    recommendation_accuracy.add_argument("--account")
    recommendation_accuracy.add_argument("--window-days", type=int, default=30)

    rebuild_recommendation_accuracy = sub.add_parser("rebuild-recommendation-accuracy")
    rebuild_recommendation_accuracy.add_argument("--campaign", required=True)
    rebuild_recommendation_accuracy.add_argument("--account")
    rebuild_recommendation_accuracy.add_argument("--window-days", type=int, default=30)

    recommend_next = sub.add_parser("recommend-next-batch")
    recommend_next.add_argument("--campaign", required=True)
    recommend_next.add_argument("--count", type=int, default=20)
    recommend_next.add_argument("--account")
    recommend_next.add_argument("--persist", action="store_true")

    accept_rec = sub.add_parser("accept-recommendation")
    accept_rec.add_argument("--id", required=True)
    accept_rec.add_argument("--operator")
    accept_rec.add_argument("--notes")
    accept_rec.add_argument("--admin-override", action="store_true")
    accept_rec.add_argument("--override-reason")

    reject_rec = sub.add_parser("reject-recommendation")
    reject_rec.add_argument("--id", required=True)
    reject_rec.add_argument("--reason")
    reject_rec.add_argument("--operator")
    reject_rec.add_argument("--notes")
    reject_rec.add_argument("--admin-override", action="store_true")
    reject_rec.add_argument("--override-reason")

    link_rec = sub.add_parser("link-recommendation")
    link_rec.add_argument("--id", required=True)
    link_rec.add_argument("--source-asset-id")
    link_rec.add_argument("--render-job-id")
    link_rec.add_argument("--rendered-asset-id")
    link_rec.add_argument("--post-id")
    link_rec.add_argument("--performance-snapshot-id")
    link_rec.add_argument("--evidence-json")
    link_rec.add_argument("--admin-override", action="store_true")
    link_rec.add_argument("--override-reason")

    measure_rec = sub.add_parser("measure-recommendation")
    measure_rec.add_argument("--id", required=True)
    measure_rec.add_argument("--performance-snapshot-id")
    measure_rec.add_argument("--admin-override", action="store_true")
    measure_rec.add_argument("--override-reason")

    execute_rec = sub.add_parser("execute-recommendation")
    execute_rec.add_argument("--id", required=True)
    execute_rec.add_argument("--mode", default="level_2")
    execute_rec.add_argument("--force", action="store_true")
    execute_rec.add_argument("--dry-run-render", action="store_true")
    execute_rec.add_argument("--no-audit", action="store_true")
    execute_rec.add_argument("--contentforge-base-url", default=os.environ.get("CONTENTFORGE_BASE_URL"))

    account_memory = sub.add_parser("account-memory")
    account_memory.add_argument("--campaign", required=True)
    account_memory.add_argument("--account")

    rebuild_account_memory = sub.add_parser("rebuild-account-memory")
    rebuild_account_memory.add_argument("--campaign", required=True)

    exceptions = sub.add_parser("exceptions")
    exceptions.add_argument("--campaign")
    exceptions.add_argument("--status", default="open")

    resolve_exception = sub.add_parser("resolve-exception")
    resolve_exception.add_argument("--id", required=True)
    resolve_exception.add_argument("--resolution")
    resolve_exception.add_argument("--operator")

    snooze_exception = sub.add_parser("snooze-exception")
    snooze_exception.add_argument("--id", required=True)
    snooze_exception.add_argument("--until")
    snooze_exception.add_argument("--reason")
    snooze_exception.add_argument("--operator")

    reopen_exception = sub.add_parser("reopen-exception")
    reopen_exception.add_argument("--id", required=True)
    reopen_exception.add_argument("--reason")
    reopen_exception.add_argument("--operator")

    ref_import = sub.add_parser("import-reference-bank")
    ref_import.add_argument("--path", default=os.environ.get("CAMPAIGN_REFERENCE_BANK"))
    ref_import.add_argument("--prompt-pack", default=os.environ.get("HIGGSFIELD_PROMPT_PACK"))

    audio_import = sub.add_parser("import-audio-catalog")
    audio_import.add_argument("--path", required=True)

    audio_memory_import = sub.add_parser("import-audio-memory")
    audio_memory_import.add_argument("--path", required=True)

    audio_list = sub.add_parser("audio-catalog")
    audio_list.add_argument("--platform", default=None)
    audio_list.add_argument("--limit", type=int, default=100)

    audio_memory = sub.add_parser("audio-memory")
    audio_memory.add_argument("--platform", default=None)
    audio_memory.add_argument("--account", default=None)
    audio_memory.add_argument("--limit", type=int, default=100)

    audio_recommend = sub.add_parser("recommend-audio")
    audio_recommend.add_argument("--platform", default="instagram")
    audio_recommend.add_argument("--campaign")
    audio_recommend.add_argument("--recommendation-item")
    audio_recommend.add_argument("--account")
    audio_recommend.add_argument("--content-tags", default="")
    audio_recommend.add_argument("--account-tags", default="")
    audio_recommend.add_argument("--visual-energy", choices=["low", "medium", "high"], default=None)
    audio_recommend.add_argument("--cuts-per-second", type=float, default=None)
    audio_recommend.add_argument("--avg-frame-delta", type=float, default=None)
    audio_recommend.add_argument("--limit", "--count", type=int, default=5)

    audio_decide = sub.add_parser("decide-audio")
    audio_decide.add_argument("--platform", default="instagram")
    audio_decide.add_argument("--campaign")
    audio_decide.add_argument("--recommendation-item")
    audio_decide.add_argument("--account")
    audio_decide.add_argument("--content-tags", default="")
    audio_decide.add_argument("--account-tags", default="")
    audio_decide.add_argument("--visual-energy", choices=["low", "medium", "high"], default=None)
    audio_decide.add_argument("--cuts-per-second", type=float, default=None)
    audio_decide.add_argument("--avg-frame-delta", type=float, default=None)
    audio_decide.add_argument("--limit", "--count", type=int, default=5)
    audio_decide.add_argument("--select", action="store_true")
    audio_decide.add_argument("--operator")

    select_audio = sub.add_parser("select-audio")
    select_audio.add_argument("--recommendation-item", required=True)
    select_audio.add_argument("--audio-id", required=True)
    select_audio.add_argument("--operator")
    select_audio.add_argument("--notes")

    attach_audio = sub.add_parser("attach-audio")
    attach_audio.add_argument("--distribution-plan-id", required=True)
    attach_audio.add_argument("--track-id")
    attach_audio.add_argument("--track-name")
    attach_audio.add_argument("--source", default="manual")
    attach_audio.add_argument("--audio-url")
    attach_audio.add_argument("--native-audio-id")
    attach_audio.add_argument("--local-winner-audio-id")
    attach_audio.add_argument("--selected-reason")
    attach_audio.add_argument("--segment-start-seconds", type=float)
    attach_audio.add_argument("--segment-duration-seconds", type=float)
    attach_audio.add_argument("--segment-label")
    attach_audio.add_argument("--segment-reason")
    attach_audio.add_argument("--operator")
    attach_audio.add_argument("--notes")

    attach_cover_frame = sub.add_parser("attach-cover-frame")
    attach_cover_frame.add_argument("--rendered-asset-id", required=True)
    attach_cover_frame.add_argument("--seconds", type=float, required=True)
    attach_cover_frame.add_argument("--cover-image-path")
    attach_cover_frame.add_argument("--cover-image-url")
    attach_cover_frame.add_argument("--cover-image-hash")
    attach_cover_frame.add_argument("--reason")
    attach_cover_frame.add_argument("--operator")

    verify_audio = sub.add_parser("verify-audio")
    verify_audio.add_argument("--post-id", required=True)
    verify_audio.add_argument("--proof-url", required=True)
    verify_audio.add_argument("--proof-note")
    verify_audio.add_argument("--operator")

    ref_patterns = sub.add_parser("reference-patterns")
    ref_patterns.add_argument("--limit", type=int, default=50)

    ref_select = sub.add_parser("select-reference-pattern")
    ref_select.add_argument("--campaign", required=True)
    ref_select.add_argument("--cluster-key")
    ref_select.add_argument("--reference-pattern-id")
    ref_select.add_argument("--variant-count", type=int, default=5)
    ref_select.add_argument("--notes")

    ref_plan = sub.add_parser("reference-plan")
    ref_plan.add_argument("--campaign", required=True)

    prep_ref = sub.add_parser("prepare-from-reference")
    prep_ref.add_argument("--campaign", required=True)
    prep_ref.add_argument("--cluster-key")
    prep_ref.add_argument("--reference-pattern-id")
    prep_ref.add_argument("--variant-count", type=int, default=5)
    prep_ref.add_argument("--recipes", nargs="*", default=None)
    prep_ref.add_argument("--caption-color", default="auto")
    prep_ref.add_argument("--notes")
    prep_ref.add_argument("--reuse-existing", action="store_true")

    make_batch = sub.add_parser("make-batch")
    make_batch.add_argument("--folder", required=True)
    make_batch.add_argument("--campaign", required=True)
    make_batch.add_argument("--model", required=True)
    make_batch.add_argument("--format", choices=["reel", "slideshow", "auto"], default="auto")
    make_batch.add_argument("--variant-count", type=int, default=20)
    make_batch.add_argument("--reference-pattern", default="auto")
    make_batch.add_argument("--contentforge-base-url", default=os.environ.get("CONTENTFORGE_BASE_URL"))
    make_batch.add_argument("--dry-run-export", action="store_true")
    make_batch.add_argument("--user-id")
    make_batch.add_argument("--workers", type=int, default=3)
    make_batch.add_argument("--recipes", nargs="*", default=None)
    make_batch.add_argument("--no-auto-approve", action="store_true")

    finished = sub.add_parser("intake-finished-video")
    finished.add_argument("--input", required=True)
    finished.add_argument("--model", required=True)
    finished.add_argument("--campaign")
    finished.add_argument("--platform", default="instagram")
    finished.add_argument("--goal", default="reach")
    finished.add_argument("--reference-pattern", default="auto")
    finished.add_argument("--contentforge-base-url", default=os.environ.get("CONTENTFORGE_BASE_URL"))
    finished.add_argument("--dry-run-export", action="store_true", default=True)
    finished.add_argument("--user-id")
    finished.add_argument("--variant-count", type=int, default=10)
    finished.add_argument("--workers", type=int, default=3)
    finished.add_argument("--recipes", nargs="*", default=None)
    finished.add_argument("--creative-plan", default=None)
    finished.add_argument("--style-lane", default=None)
    finished.add_argument("--source-lineage", default=None)

    register_finished = sub.add_parser("register-finished-video")
    register_finished.add_argument("--input", required=True)
    register_finished.add_argument("--campaign", required=True)
    register_finished.add_argument("--model", required=True)
    register_finished.add_argument("--caption", required=True)
    register_finished.add_argument("--caption-hash")
    register_finished.add_argument("--caption-bank")
    register_finished.add_argument("--creator-mix")
    register_finished.add_argument("--creator-model")
    register_finished.add_argument("--track-id")
    register_finished.add_argument("--track-name")
    register_finished.add_argument("--audio-source")
    register_finished.add_argument("--selected-reason")
    register_finished.add_argument("--operator")
    register_finished.add_argument("--approval-reason")
    register_finished.add_argument("--review-batch")
    register_finished.add_argument("--caption-placement-policy")
    register_finished.add_argument("--caption-placement-decision-json")

    archive_inventory = sub.add_parser("archive-inventory")
    archive_inventory.add_argument("--folder", required=True)
    archive_inventory.add_argument("--campaign", required=True)
    archive_inventory.add_argument("--creator", default="Stacey")
    archive_inventory.add_argument("--model")
    archive_inventory.add_argument("--requested-count", type=int, default=25)
    archive_inventory.add_argument("--recent-days", type=int, default=30)

    archive_quality = sub.add_parser("archive-candidate-quality")
    archive_quality.add_argument("--inventory-report", required=True)
    archive_quality.add_argument("--requested-count", type=int, default=25)
    archive_quality.add_argument("--exclude-index", type=int, action="append", default=[])

    creative_create = sub.add_parser("create-creative-plan")
    creative_create.add_argument("--name", required=True)
    creative_create.add_argument("--platform", default="instagram")
    creative_create.add_argument("--target-account", required=True)
    creative_create.add_argument("--daily-base-video-target", type=int, default=10)
    creative_create.add_argument("--style-lanes", default="amateur_native,polished_glam,slideshow_story,pov_relationship,lifestyle_scene")
    creative_create.add_argument("--model-profile", default="")
    creative_create.add_argument("--source-accounts", default="")
    creative_create.add_argument("--goal", default="views_reach")
    creative_create.add_argument("--linked-campaign", default=None)

    creative_get = sub.add_parser("creative-plan")
    creative_get.add_argument("--name", required=True)

    creative_status = sub.add_parser("update-creative-plan-status")
    creative_status.add_argument("--name", required=True)
    creative_status.add_argument("--status", required=True)

    creative_sync = sub.add_parser("sync-creative-plan-progress")
    creative_sync.add_argument("--name", required=True)
    creative_sync.add_argument("--prompt-export", required=True)

    activity = sub.add_parser("activity-log")
    activity.add_argument("--campaign", required=True)
    activity.add_argument("--limit", type=int, default=200)

    jobs = sub.add_parser("jobs")
    jobs.add_argument("--campaign", required=True)
    jobs.add_argument("--limit", type=int, default=100)

    job = sub.add_parser("job")
    job.add_argument("--id", required=True)

    smoke = sub.add_parser("pipeline-smoke")
    smoke.add_argument("--folder", required=True)
    smoke.add_argument("--campaign", required=True)
    smoke.add_argument("--model", required=True)
    smoke.add_argument("--user-id", required=True)
    smoke.add_argument("--hook", action="append", default=[])
    smoke.add_argument("--hooks")
    smoke.add_argument("--recipes", nargs="*", default=None)
    smoke.add_argument("--account", action="append", default=[])
    smoke.add_argument("--contentforge-base-url", default=os.environ.get("CONTENTFORGE_BASE_URL"))
    smoke.add_argument("--run-reel", action="store_true")
    smoke.add_argument("--workers", type=int, default=3)
    smoke.add_argument("--min-score", type=int, default=85)

    args = parser.parse_args()
    settings = get_settings()

    if args.cmd == "serve":
        uvicorn.run("campaign_factory.app:app", host=args.host, port=args.port, reload=False)
        return 0

    cf = CampaignFactory(settings)
    try:
        if args.cmd == "init":
            print_json({"ok": True, "db": str(settings.db_path), "campaigns": str(settings.campaigns_dir)})
        elif args.cmd == "doctor":
            print_json(operator_control_check(
                settings,
                contentforge_base_url=args.contentforge_base_url,
                check_http=args.check_http,
            ))
        elif args.cmd == "import-folder":
            print_json(cf.import_folder(
                Path(args.folder),
                campaign_slug=args.campaign,
                model_slug=args.model,
                model_name=args.model_name,
                platform=args.platform,
                account_handles=args.account,
                source_prompt=args.source_prompt,
                notes=args.notes,
            ))
        elif args.cmd == "prepare-reel":
            print_json(cf.prepare_reel_inputs(
                campaign_slug=args.campaign,
                hooks=load_hooks(args.hooks, args.hook),
                recipes=args.recipes,
                caption_color=args.caption_color,
                notes=args.notes,
                force_new=args.force_new,
            ))
        elif args.cmd == "run-reel":
            print_json(cf.run_reel_factory(
                campaign_slug=args.campaign,
                workers=args.workers,
                dry_run=args.dry_run,
                caption_band=args.band,
                caption_color=args.color,
                caption_style=args.style,
                caption_font=args.font,
                phone_finalize=not args.no_phone_finalize,
                rerender_all=args.rerender_all,
                max_outputs_per_clip=args.max_outputs_per_clip,
            ))
        elif args.cmd == "sync-reel":
            print_json(cf.sync_reel_outputs(campaign_slug=args.campaign))
        elif args.cmd == "variation":
            if args.variation_cmd == "run":
                print_json(run_variation_stage(
                    cf,
                    campaign_slug=args.campaign,
                    preset_name=args.preset,
                    rendered_asset_ids=args.rendered_asset_id or None,
                    dry_run=not args.apply or args.dry_run,
                ))
        elif args.cmd == "animation":
            if args.animation_cmd == "motion-edit":
                caption = args.caption if args.caption is not None else Path(args.caption_file).read_text(encoding="utf-8").strip()
                print_json(run_motion_edit_stage(
                    cf,
                    campaign_slug=args.campaign,
                    still_path=Path(args.still),
                    caption=caption,
                    duration_seconds=args.duration,
                    dry_run=not args.apply or args.dry_run,
                    apply=args.apply,
                    enable_variation=args.enable_variation,
                    variation_preset=args.variation_preset,
                    allow_upscale=args.allow_upscale,
                ))
        elif args.cmd == "audit":
            print_json(audit_campaign(
                cf,
                campaign_slug=args.campaign,
                min_score=args.min_score,
                contentforge_base_url=args.contentforge_base_url,
                layers=args.layer or None,
            ))
        elif args.cmd == "approve":
            print_json(cf.approve_rendered_asset(
                args.rendered_asset_id,
                notes=args.notes,
                require_safe_audit=not args.force_unsafe_audit,
            ))
        elif args.cmd == "review-decision":
            print_json(cf.review_rendered_asset(
                args.rendered_asset_id,
                decision=args.decision,
                notes=args.notes,
                require_safe_audit=not args.force_unsafe_audit,
            ))
        elif args.cmd == "export-readiness":
            print_json(evaluate_export_readiness(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
                content_pillar=args.content_pillar,
                cta_type=args.cta_type,
                language=args.language,
                schedule_mode=args.schedule_mode,
            ))
        elif args.cmd == "readiness-report":
            campaign_row = cf.conn.execute(
                "SELECT slug FROM campaigns WHERE id = ? OR slug = ?",
                (args.campaign_id, args.campaign_id),
            ).fetchone()
            if not campaign_row:
                raise ValueError(f"campaign not found: {args.campaign_id}")
            campaign_slug = campaign_row["slug"]
            usage = None
            export_readiness = None
            if args.user_id and args.supabase_url and args.supabase_service_role_key:
                try:
                    usage = summarize_threadsdash_usage(
                        cf,
                        campaign_slug=campaign_slug,
                        user_id=args.user_id,
                        supabase_url=args.supabase_url,
                        supabase_service_role_key=args.supabase_service_role_key,
                        limit=args.limit,
                    )
                except Exception as exc:
                    usage = {
                        "checked": False,
                        "error": str(exc),
                        "assets": [],
                    }
                try:
                    export_readiness = evaluate_export_readiness(
                        cf,
                        campaign_slug=campaign_slug,
                        user_id=args.user_id,
                        supabase_url=args.supabase_url,
                        supabase_service_role_key=args.supabase_service_role_key,
                        limit=args.limit,
                    )
                except Exception as exc:
                    export_readiness = {
                        "checked": False,
                        "liveExportAllowed": False,
                        "blockingReasons": ["threadsdash_readiness_check_failed"],
                        "warnings": [str(exc)],
                    }
            report = build_mass_production_readiness_report(
                cf,
                campaign_id=args.campaign_id,
                days=args.days,
                user_id=args.user_id,
                threadsdash_usage=usage,
                threadsdash_readiness=export_readiness,
            )
            if args.format == "markdown":
                print(report["markdownSummary"])
            else:
                print_json(report)
        elif args.cmd == "promote-reel-ledger":
            print_json(promote_reel_ledger(
                cf,
                campaign_id=args.campaign,
                reel_factory_root=Path(args.reel_factory_root) if args.reel_factory_root else settings.reel_factory_root,
                days=args.days,
                apply=args.apply,
            ))
        elif args.cmd == "export-threadsdash":
            print_json(export_threadsdash(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                dry_run=args.dry_run or not (args.supabase_url and args.supabase_service_role_key),
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                supabase_storage_bucket=args.supabase_storage_bucket,
                allow_warnings=args.allow_warnings,
                content_pillar=args.content_pillar,
                cta_type=args.cta_type,
                language=args.language,
                max_drafts=args.max_drafts,
                rendered_asset_ids=args.rendered_asset_id or None,
                schedule_mode=args.schedule_mode,
                enable_variation=args.enable_variation,
                variation_preset=args.variation_preset,
            ))
        elif args.cmd == "supabase-preflight":
            pipeline_job = cf.create_pipeline_job(
                "supabase_preflight",
                None,
                {
                    "hasSupabaseUrl": bool(args.supabase_url),
                    "hasSupabaseServiceRoleKey": bool(args.supabase_service_role_key),
                    "supabaseStorageBucket": args.supabase_storage_bucket,
                },
            )
            cf.start_pipeline_job(pipeline_job["id"])
            try:
                result = preflight_supabase(
                    supabase_url=args.supabase_url,
                    supabase_service_role_key=args.supabase_service_role_key,
                    supabase_storage_bucket=args.supabase_storage_bucket,
                )
                result["pipelineJobId"] = pipeline_job["id"]
                cf.record_event(
                    "supabase_preflight_checked",
                    pipeline_job_id=pipeline_job["id"],
                    status="success" if result["ok"] else "failure",
                    message=f"Supabase preflight {'passed' if result['ok'] else 'failed'}",
                    metadata={"ok": result["ok"], "blockingReasons": result.get("blockingReasons") or []},
                )
                if result["ok"]:
                    cf.finish_pipeline_job(pipeline_job["id"], {"ok": result["ok"], "blockingReasons": result.get("blockingReasons") or []})
                else:
                    cf.fail_pipeline_job(pipeline_job["id"], "Supabase preflight failed", {"ok": result["ok"], "blockingReasons": result.get("blockingReasons") or []})
                print_json(result)
            except Exception as exc:
                result = {
                    "schema": "campaign_factory.supabase_preflight.v1",
                    "ok": False,
                    "bucket": args.supabase_storage_bucket,
                    "checks": [],
                    "blockingReasons": [str(exc)],
                    "pipelineJobId": pipeline_job["id"],
                }
                cf.record_event(
                    "supabase_preflight_checked",
                    pipeline_job_id=pipeline_job["id"],
                    status="failure",
                    message=f"Supabase preflight failed: {exc}",
                    metadata={"error": str(exc)},
                )
                cf.fail_pipeline_job(pipeline_job["id"], str(exc))
                print_json(result)
                return 1
        elif args.cmd == "verify-threadsdash-export":
            pipeline_job = cf.create_pipeline_job("verify_threadsdash_export", None, {"exportManifest": args.export_manifest})
            cf.start_pipeline_job(pipeline_job["id"])
            try:
                result = verify_threadsdash_export(
                    export_result_or_path=Path(args.export_manifest),
                    supabase_url=args.supabase_url,
                    supabase_service_role_key=args.supabase_service_role_key,
                )
                result["pipelineJobId"] = pipeline_job["id"]
                cf.record_event(
                    "threadsdash_export_verified",
                    pipeline_job_id=pipeline_job["id"],
                    status="success" if result["ok"] else "failure",
                    message=f"ThreadsDash export {'verified' if result['ok'] else 'verification failed'}",
                    metadata={"ok": result["ok"], "campaign": result.get("campaign"), "exportPath": result.get("exportPath"), "blockingReasons": result.get("blockingReasons") or []},
                )
                if result["ok"]:
                    cf.finish_pipeline_job(pipeline_job["id"], {"ok": result["ok"], "campaign": result.get("campaign"), "blockingReasons": result.get("blockingReasons") or []})
                else:
                    cf.fail_pipeline_job(pipeline_job["id"], "ThreadsDash export verification failed", {"ok": result["ok"], "campaign": result.get("campaign"), "blockingReasons": result.get("blockingReasons") or []})
                print_json(result)
            except Exception as exc:
                cf.record_event(
                    "threadsdash_export_verified",
                    pipeline_job_id=pipeline_job["id"],
                    status="failure",
                    message=f"ThreadsDash export verification failed: {exc}",
                    metadata={"error": str(exc)},
                )
                cf.fail_pipeline_job(pipeline_job["id"], str(exc))
                raise
        elif args.cmd == "safe-live-smoke":
            print_json(safe_live_smoke_export(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                supabase_storage_bucket=args.supabase_storage_bucket,
                allow_warnings=args.allow_warnings,
            ))
        elif args.cmd == "threadsdash-usage":
            print_json(summarize_threadsdash_usage(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
            ))
        elif args.cmd == "sync-threadsdash-assignments":
            print_json(sync_threadsdash_account_assignments(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
            ))
        elif args.cmd == "sync-performance":
            print_json(sync_performance_snapshots(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
            ))
        elif args.cmd == "performance-summary":
            print_json(cf.performance_summary(args.campaign))
        elif args.cmd == "multi-surface-inventory-audit":
            print_json(cf.multi_surface_inventory_audit(
                creator=args.creator,
                campaign_slug=args.campaign,
            ))
        elif args.cmd == "account-surface-obligations-plan":
            print_json(cf.account_surface_obligations_plan(
                creator=args.creator,
                date=args.date,
            ))
        elif args.cmd == "account-content-needs":
            print_json(cf.account_content_needs(
                account_id=args.account_id,
                creator=args.creator,
                date=args.date,
            ))
        elif args.cmd == "account-surface-status":
            print_json(cf.account_surface_status(
                account_id=args.account_id,
                creator=args.creator,
                date=args.date,
            ))
        elif args.cmd == "creator-content-needs":
            print_json(cf.creator_content_needs(
                creator=args.creator,
                date=args.date,
            ))
        elif args.cmd == "surface-gap-report":
            print_json(cf.surface_gap_report(
                creator=args.creator,
                date=args.date,
            ))
        elif args.cmd in {"inventory-recovery-report", "inventory-recovery-priority-report", "inventory-recovery-by-blocker", "inventory-recovery-master-report"}:
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
        elif args.cmd in {
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
        elif args.cmd in {
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
        elif args.cmd in {
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
        elif args.cmd in {"operator-inventory-review-batch-plan", "operator-inventory-review-batch-summary"}:
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
        elif args.cmd in {
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
        elif args.cmd in {
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
        elif args.cmd == "story-inventory-report":
            print_json(cf.story_inventory_report(
                creator=args.creator,
                campaign_slug=args.campaign,
            ))
        elif args.cmd == "story-gap-report":
            print_json(cf.story_gap_report(
                creator=args.creator,
                date=args.date,
            ))
        elif args.cmd == "story-quality-report":
            print_json(cf.story_quality_report(
                creator=args.creator,
                campaign_slug=args.campaign,
            ))
        elif args.cmd == "story-intent-report":
            print_json(cf.story_intent_report(
                creator=args.creator,
                campaign_slug=args.campaign,
            ))
        elif args.cmd == "story-mix-plan":
            print_json(cf.story_mix_plan(
                creator=args.creator,
            ))
        elif args.cmd == "story-calendar-plan":
            print_json(cf.story_calendar_plan(
                creator=args.creator,
            ))
        elif args.cmd == "story-intent-summary":
            print_json(cf.story_intent_summary(
                creator=args.creator,
                campaign_slug=args.campaign,
            ))
        elif args.cmd == "decision-ledger-preview":
            print_json(cf.decision_ledger_preview(**decision_ledger_kwargs(args)))
        elif args.cmd == "decision-ledger-report":
            print_json(cf.decision_ledger_report(**decision_ledger_kwargs(args)))
        elif args.cmd == "decision-ledger-summary":
            print_json(cf.decision_ledger_summary(**decision_ledger_kwargs(args)))
        elif args.cmd == "decision-ledger-by-creator":
            print_json(cf.decision_ledger_by_creator(**decision_ledger_kwargs(args)))
        elif args.cmd == "decision-ledger-by-account":
            print_json(cf.decision_ledger_by_account(account_id=args.account_id, **decision_ledger_kwargs(args)))
        elif args.cmd == "decision-ledger-by-surface":
            print_json(cf.decision_ledger_by_surface(surface=args.surface, **decision_ledger_kwargs(args)))
        elif args.cmd == "decision-ledger-by-decision-type":
            print_json(cf.decision_ledger_by_decision_type(decision_type=args.decision_type, **decision_ledger_kwargs(args)))
        elif args.cmd == "account-story-status":
            print_json(cf.account_story_status(
                account_id=args.account_id,
                creator=args.creator,
                date=args.date,
            ))
        elif args.cmd == "creator-story-summary":
            print_json(cf.creator_story_summary(
                creator=args.creator,
                date=args.date,
            ))
        elif args.cmd == "surface-handoff-readiness-report":
            print_json(cf.surface_handoff_readiness_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
            ))
        elif args.cmd == "surface-draft-proof":
            print_json(cf.surface_draft_proof(
                creator=args.creator,
                campaign=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
            ))
        elif args.cmd == "carousel-integrity-report":
            print_json(cf.carousel_integrity_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
            ))
        elif args.cmd == "carousel-child-metrics-plan":
            print_json(cf.carousel_child_metrics_plan(
                creator=args.creator,
                campaign_slug=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
            ))
        elif args.cmd == "register-surface-asset":
            inputs = [Path(item) for item in args.input]
            print_json(cf.register_surface_asset(
                input_path=inputs if args.surface == "feed_carousel" else inputs[0],
                surface=args.surface,
                creator=args.creator,
                campaign_slug=args.campaign,
                instagram_post_caption=args.instagram_post_caption,
                target_ratio=args.target_ratio,
                model_slug=args.model,
                operator=args.operator,
                story_asset_class=args.story_asset_class,
                story_cta_type=args.story_cta_type,
                story_cta_text=args.story_cta_text,
                story_cta_target_url=args.story_cta_target_url,
                story_intent=args.story_intent,
                story_goal=args.story_goal,
                story_style=args.story_style,
                snapchat_username=args.snapchat_username,
                snapchat_display_name=args.snapchat_display_name,
                snapchat_cta_text=args.snapchat_cta_text,
            ))
        elif args.cmd == "caption-outcome-report":
            print_json(cf.caption_outcome_report(args.campaign))
        elif args.cmd == "lifecycle-report":
            print_json(cf.lifecycle_report(
                args.campaign,
                user_id=args.user_id,
                include_threadsdash=args.include_threadsdash,
                state=args.state,
                blocking_reason=args.blocking_reason,
                rendered_asset_id=args.rendered_asset_id,
            ))
        elif args.cmd == "explain-publishability":
            print_json(cf.explain_publishability(
                args.rendered_asset_id,
                distribution_plan_id=args.distribution_plan_id,
            ))
        elif args.cmd == "register-parent-reel":
            metadata = json.loads(args.metadata_json) if args.metadata_json else None
            print_json(cf.register_parent_reel(
                args.rendered_asset_id,
                operator=args.operator,
                status=args.status,
                metadata=metadata,
            ))
        elif args.cmd == "parent-variant-inventory":
            print_json(cf.parent_variant_inventory(args.campaign))
        elif args.cmd == "variant-plan":
            print_json(cf.variant_plan(
                parent_asset_id=args.parent_asset_id,
                count=args.count,
                contentforge_preset=args.contentforge_preset,
                cooldown_days=args.cooldown_days,
            ))
        elif args.cmd == "generate-variants":
            if args.dry_run or not args.contentforge_base_url:
                plan = cf.variant_plan(
                    parent_asset_id=args.parent_asset_id,
                    caption_version_id=args.caption_version_id,
                    count=args.count,
                    contentforge_preset=args.contentforge_preset,
                )
                plan["schema"] = "campaign_factory.generate_variants.preview.v1"
                plan["status"] = "dry_run" if args.dry_run else "blocked"
                plan["blockingReason"] = None if args.dry_run else "contentforge_base_url_required"
                print_json(plan)
            else:
                print_json(cf.generate_variants(
                    parent_asset_id=args.parent_asset_id,
                    caption_version_id=args.caption_version_id,
                    count=args.count,
                    contentforge_preset=args.contentforge_preset,
                    contentforge_base_url=args.contentforge_base_url,
                    source_media_path=args.source_media_path,
                ))
        elif args.cmd == "winner-expansion-plan":
            payload = {}
            if args.input_json:
                input_value = args.input_json.strip()
                if input_value.startswith("{"):
                    payload = json.loads(input_value)
                else:
                    payload = json.loads(Path(input_value).read_text(encoding="utf-8"))
            parent_asset_id = args.parent_asset_id or payload.get("parentAssetId") or payload.get("parent_asset_id")
            if not parent_asset_id:
                raise ValueError("parentAssetId is required")
            print_json(cf.winner_expansion_plan(
                creator=args.creator or payload.get("creator"),
                parent_asset_id=parent_asset_id,
                target_variants=args.target_variants or payload.get("targetVariants") or payload.get("target_variants") or 10,
                preset=args.preset or payload.get("preset") or "caption_safe_v2",
            ))
        elif args.cmd in {"caption-family-plan", "caption-family-create"}:
            payload = {}
            if args.input_json:
                input_value = args.input_json.strip()
                if input_value.startswith("{"):
                    payload = json.loads(input_value)
                else:
                    payload = json.loads(Path(input_value).read_text(encoding="utf-8"))
            parent_asset_id = args.parent_asset_id or payload.get("parentAssetId") or payload.get("parent_asset_id")
            if not parent_asset_id:
                raise ValueError("parentAssetId is required")
            common = {
                "creator": args.creator or payload.get("creator"),
                "parent_asset_id": parent_asset_id,
                "requested_caption_versions": (
                    args.requested_caption_versions
                    if args.requested_caption_versions is not None
                    else payload.get("requestedCaptionVersions") or payload.get("requested_caption_versions") or 5
                ),
                "style": args.style or payload.get("style") or "ig_short",
            }
            if args.cmd == "caption-family-plan":
                print_json(cf.caption_family_plan(
                    **common,
                    dry_run=bool(args.dry_run or payload.get("dryRun") is not False),
                ))
            else:
                print_json(cf.caption_family_create(
                    **common,
                    dry_run=bool(args.dry_run or payload.get("dryRun") is True),
                ))
        elif args.cmd == "variant-inventory-plan":
            payload = {}
            if args.input_json:
                input_value = args.input_json.strip()
                if input_value.startswith("{"):
                    payload = json.loads(input_value)
                else:
                    payload = json.loads(Path(input_value).read_text(encoding="utf-8"))
            creator = args.creator or payload.get("creator")
            campaign = args.campaign or payload.get("campaign")
            if not creator:
                raise ValueError("creator is required")
            if not campaign:
                raise ValueError("campaign is required")
            print_json(cf.variant_inventory_plan(
                creator=creator,
                campaign=campaign,
                target_draft_shortfall=(
                    args.target_draft_shortfall
                    if args.target_draft_shortfall is not None
                    else payload.get("targetDraftShortfall") or payload.get("target_draft_shortfall") or 0
                ),
                preset=args.preset or payload.get("preset") or "caption_safe_v2",
                max_variants_per_parent=(
                    args.max_variants_per_parent
                    if args.max_variants_per_parent is not None
                    else payload.get("maxVariantsPerParent") or payload.get("max_variants_per_parent") or 10
                ),
                minimum_recommended_per_parent=(
                    args.minimum_recommended_per_parent
                    if args.minimum_recommended_per_parent is not None
                    else payload.get("minimumRecommendedPerParent") or payload.get("minimum_recommended_per_parent") or 3
                ),
                dry_run=bool(args.dry_run or payload.get("dryRun") is not False),
            ))
        elif args.cmd == "winner-expansion-report":
            print_json(cf.winner_expansion_report(
                args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            ))
        elif args.cmd == "concept-registry":
            print_json(cf.concept_registry(
                creator=args.creator,
                campaign_slug=args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            ))
        elif args.cmd == "winner-registry":
            print_json(cf.winner_registry(
                creator=args.creator,
                campaign_slug=args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            ))
        elif args.cmd == "winner-patterns":
            print_json(cf.winner_patterns(
                creator=args.creator,
                campaign_slug=args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            ))
        elif args.cmd == "winner-knowledge-base":
            print_json(cf.winner_knowledge_base(
                creator=args.creator,
                campaign_slug=args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            ))
        elif args.cmd == "creative-knowledge-base":
            print_json(cf.creative_knowledge_base(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creative-pattern-report":
            print_json(cf.creative_pattern_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creative-surface-report":
            print_json(cf.creative_surface_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creative-account-tier-report":
            print_json(cf.creative_account_tier_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creative-caption-report":
            print_json(cf.creative_caption_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creative-audio-report":
            print_json(cf.creative_audio_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creative-window-report":
            print_json(cf.creative_window_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creative-performance-analysis":
            print_json(cf.creative_performance_analysis(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creator-learning-summary":
            print_json(cf.creator_learning_summary(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "next-content-recommendations":
            print_json(cf.next_content_recommendations(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "creative-learning-confidence-model":
            print_json(cf.creative_learning_confidence_model(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
            ))
        elif args.cmd == "creative-fatigue-report":
            print_json(cf.creative_fatigue_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                limit=args.limit,
            ))
        elif args.cmd == "creative-surface-comparison-report":
            print_json(cf.creative_surface_comparison_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                limit=args.limit,
            ))
        elif args.cmd == "recommendation-quality-audit":
            print_json(cf.recommendation_quality_audit(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "tribev2-reel-analysis":
            print_json(cf.tribev2_reel_analysis(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            ))
        elif args.cmd == "tribev2-reel-review":
            print_json(cf.tribev2_reel_review(
                creator=args.creator,
                campaign_slug=args.campaign,
                sort_by=args.sort_by,
                bucket=args.bucket,
                limit=args.limit,
                contact_sheet=args.contact_sheet,
                show_metrics=True if args.show_metrics or not args.blind_mode else False,
                show_tribe_score=not args.hide_tribe_score,
                blind_mode=args.blind_mode,
            ))
        elif args.cmd == "tribev2-holdout-pilot-review":
            print_json(cf.tribev2_holdout_pilot_review(
                creator=args.creator,
                campaign_slug=args.campaign,
                limit=args.limit,
                contact_sheet=args.contact_sheet,
            ))
        elif args.cmd == "caption-quality-repair-plan":
            print_json(cf.caption_quality_repair_plan(
                creator=args.creator,
                campaign_slug=args.campaign,
                content_surface=args.content_surface,
                limit=args.limit,
            ))
        elif args.cmd == "recommended-inventory-request-plan":
            print_json(cf.recommended_inventory_request_plan(
                creator=args.creator,
                target_count=args.target_count,
                daily_plan=load_json_object(args.daily_plan_json),
                variant_inventory_plan=load_json_object(args.variant_inventory_plan_json),
            ))
        elif args.cmd == "variant-metrics-rollup":
            print_json(cf.variant_metrics_rollup(args.campaign))
        elif args.cmd == "account-routing-audit":
            if not args.supabase_url or not args.supabase_service_role_key:
                print_json({
                    "schema": "campaign_factory.account_routing_audit.v1",
                    "mode": "preview",
                    "mutatesSupabase": False,
                    "creator": args.creator,
                    "userId": args.user_id,
                    "status": "blocked",
                    "blockingReasons": ["missing_supabase_credentials"],
                    "hasSupabaseUrl": bool(args.supabase_url),
                    "hasSupabaseServiceRoleKey": bool(args.supabase_service_role_key),
                    "recommendations": ["load ThreadsDashboard Supabase credentials before running the routing audit"],
                })
                return 1
            client = SupabaseRestClient(args.supabase_url.rstrip("/"), args.supabase_service_role_key)
            print_json(build_account_routing_audit(
                client,
                user_id=args.user_id,
                creator=args.creator,
            ))
        elif args.cmd == "closed-loop-proof":
            result = run_stacey_closed_loop_proof(
                campaign_slug=args.campaign,
                user_id=args.user_id,
                output_dir=args.output_dir,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                supabase_storage_bucket=args.supabase_storage_bucket,
                operator=args.operator,
                approval_reason=args.approval_reason,
                approved_rendered_asset_id=args.approved_rendered_asset_id,
                prompt_path=args.prompt_path,
                schedule_mode=args.schedule_mode,
                allow_warnings=args.allow_warnings,
                allow_live_export=args.allow_live_export,
                read_only_verification=args.read_only_verification,
                existing_threadsdash_post_id=args.existing_threadsdash_post_id,
                limit=args.limit,
            )
            print_json(result)
            if result.get("result") == "failed":
                return 1
        elif args.cmd == "campaign-health":
            print_json(cf.campaign_health(args.campaign))
        elif args.cmd == "asset-detail":
            print_json(cf.asset_detail(args.rendered_asset_id))
        elif args.cmd == "campaign-readiness":
            print_json(cf.campaign_readiness(args.campaign, user_id=args.user_id))
        elif args.cmd == "assign-account":
            print_json(cf.assign_asset_account(
                args.rendered_asset_id,
                account_id=args.account_id,
                instagram_account_id=args.instagram_account_id,
                planned_window_start=args.planned_window_start,
                planned_window_end=args.planned_window_end,
                notes=args.notes,
            ))
        elif args.cmd == "model-account-profile":
            print_json(cf.upsert_model_account_profile(
                args.model,
                label=args.label,
                allowed_instagram_account_ids=args.instagram_account_id,
                allowed_account_group_names=args.account_group_name,
                allowed_handle_patterns=args.handle_pattern,
                default_smart_link=args.smart_link,
                story_cta_text=args.story_cta,
            ))
        elif args.cmd == "distribution-plan":
            print_json(cf.create_distribution_plan(
                args.rendered_asset_id,
                surface=args.surface,
                account_id=args.account_id,
                instagram_account_id=args.instagram_account_id,
                planned_window_start=args.planned_window_start,
                planned_window_end=args.planned_window_end,
                paired_rendered_asset_id=args.paired_rendered_asset_id,
                reason_code=args.reason_code,
                smart_link=args.smart_link,
                cta_text=args.cta_text,
                instagram_trial_reels=args.instagram_trial_reels,
                trial_graduation_strategy=args.trial_graduation_strategy,
            ))
        elif args.cmd == "plan-distribution":
            print_json(cf.plan_distribution(
                args.campaign,
                user_id=args.user_id,
                mode=args.mode,
                strategy=args.strategy,
                replace=not args.no_replace,
            ))
        elif args.cmd == "promote-preview-schedule":
            print_json(promote_preview_schedule(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
            ))
        elif args.cmd == "clear-preview-schedule":
            print_json(clear_preview_schedule(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
                reason=args.reason,
            ))
        elif args.cmd == "account-plan":
            usage_result = None
            if args.supabase_url and args.supabase_service_role_key:
                usage_result = summarize_threadsdash_usage(
                    cf,
                    campaign_slug=args.campaign,
                    user_id=args.user_id,
                    supabase_url=args.supabase_url,
                    supabase_service_role_key=args.supabase_service_role_key,
                )
            print_json(cf.account_plan(args.campaign, user_id=args.user_id, usage=usage_result))
        elif args.cmd == "ranking":
            print_json(cf.ranking(args.campaign))
        elif args.cmd == "autonomy-policy":
            if args.set_level:
                print_json(cf.set_autonomy_level(args.set_level))
            else:
                print_json(cf.autonomy_policy())
        elif args.cmd == "trust-summary":
            print_json(cf.trust_summary(args.campaign))
        elif args.cmd == "recommendation-accuracy":
            print_json(cf.recommendation_accuracy(args.campaign, account=args.account, window_days=args.window_days))
        elif args.cmd == "rebuild-recommendation-accuracy":
            print_json(cf.rebuild_recommendation_accuracy(args.campaign, account=args.account, window_days=args.window_days))
        elif args.cmd == "recommend-next-batch":
            print_json(cf.recommend_next_batch(
                args.campaign,
                count=args.count,
                account=args.account,
                persist=args.persist,
            ))
        elif args.cmd == "accept-recommendation":
            print_json(cf.accept_recommendation_item(
                args.id,
                operator=args.operator,
                notes=args.notes,
                admin_override=args.admin_override,
                override_reason=args.override_reason,
            ))
        elif args.cmd == "reject-recommendation":
            print_json(cf.reject_recommendation_item(
                args.id,
                reason=args.reason,
                operator=args.operator,
                notes=args.notes,
                admin_override=args.admin_override,
                override_reason=args.override_reason,
            ))
        elif args.cmd == "link-recommendation":
            evidence = json.loads(args.evidence_json) if args.evidence_json else None
            print_json(cf.link_recommendation_item(
                args.id,
                source_asset_id=args.source_asset_id,
                render_job_id=args.render_job_id,
                rendered_asset_id=args.rendered_asset_id,
                post_id=args.post_id,
                performance_snapshot_id=args.performance_snapshot_id,
                evidence=evidence,
                admin_override=args.admin_override,
                override_reason=args.override_reason,
            ))
        elif args.cmd == "measure-recommendation":
            print_json(cf.measure_recommendation_item(
                args.id,
                performance_snapshot_id=args.performance_snapshot_id,
                admin_override=args.admin_override,
                override_reason=args.override_reason,
            ))
        elif args.cmd == "execute-recommendation":
            print_json(cf.execute_accepted_recommendation(
                args.id,
                mode=args.mode,
                force=args.force,
                dry_run_render=args.dry_run_render,
                run_audit=not args.no_audit,
                contentforge_base_url=args.contentforge_base_url,
            ))
        elif args.cmd == "account-memory":
            print_json(cf.account_memory(args.campaign, account=args.account))
        elif args.cmd == "rebuild-account-memory":
            print_json(cf.rebuild_account_memory(args.campaign))
        elif args.cmd == "exceptions":
            print_json(cf.exceptions(args.campaign, status=args.status))
        elif args.cmd == "resolve-exception":
            print_json(cf.resolve_exception(args.id, resolution=args.resolution, operator=args.operator))
        elif args.cmd == "snooze-exception":
            print_json(cf.snooze_exception(args.id, until=args.until, reason=args.reason, operator=args.operator))
        elif args.cmd == "reopen-exception":
            print_json(cf.reopen_exception(args.id, reason=args.reason, operator=args.operator))
        elif args.cmd == "import-reference-bank":
            bank_path = Path(args.path) if args.path else settings.reference_reels_root / "learning" / "campaign_reference_bank.json"
            prompt_pack = Path(args.prompt_pack) if args.prompt_pack else settings.reference_reels_root / "learning" / "higgsfield_prompt_pack_top300.json"
            print_json(cf.import_reference_bank(bank_path, prompt_pack if prompt_pack.exists() else None))
        elif args.cmd == "import-audio-catalog":
            print_json(cf.import_audio_catalog(Path(args.path)))
        elif args.cmd == "import-audio-memory":
            print_json(cf.import_audio_memory(Path(args.path)))
        elif args.cmd == "audio-catalog":
            print_json(cf.audio_catalog(platform=args.platform, limit=args.limit))
        elif args.cmd == "audio-memory":
            print_json(cf.audio_memory(platform=args.platform, account=args.account, limit=args.limit))
        elif args.cmd == "recommend-audio":
            visual_signal = {
                key: value
                for key, value in {
                    "energy": args.visual_energy,
                    "cutsPerSecond": args.cuts_per_second,
                    "avgFrameDelta": args.avg_frame_delta,
                }.items()
                if value is not None
            }
            print_json(cf.recommend_audio(
                platform=args.platform,
                campaign_slug=args.campaign,
                recommendation_item_id=args.recommendation_item,
                account=args.account,
                content_tags=[tag.strip() for tag in args.content_tags.split(",") if tag.strip()],
                account_tags=[tag.strip() for tag in args.account_tags.split(",") if tag.strip()],
                visual_signal=visual_signal or None,
                limit=args.limit,
            ))
        elif args.cmd == "select-audio":
            print_json(cf.select_audio_for_recommendation(
                args.recommendation_item,
                args.audio_id,
                operator=args.operator,
                notes=args.notes,
            ))
        elif args.cmd == "attach-audio":
            print_json(cf.attach_audio_to_distribution_plan(
                args.distribution_plan_id,
                track_id=args.track_id,
                track_name=args.track_name,
                source=args.source,
                audio_url=args.audio_url,
                native_audio_id=args.native_audio_id,
                local_winner_audio_id=args.local_winner_audio_id,
                selected_reason=args.selected_reason,
                segment_start_seconds=args.segment_start_seconds,
                segment_duration_seconds=args.segment_duration_seconds,
                segment_label=args.segment_label,
                segment_reason=args.segment_reason,
                operator=args.operator,
                notes=args.notes,
            ))
        elif args.cmd == "attach-cover-frame":
            print_json(cf.attach_cover_frame_to_rendered_asset(
                args.rendered_asset_id,
                seconds=args.seconds,
                cover_image_path=args.cover_image_path,
                cover_image_url=args.cover_image_url,
                cover_image_hash=args.cover_image_hash,
                reason=args.reason,
                operator=args.operator,
            ))
        elif args.cmd == "decide-audio":
            visual_signal = {
                key: value
                for key, value in {
                    "energy": args.visual_energy,
                    "cutsPerSecond": args.cuts_per_second,
                    "avgFrameDelta": args.avg_frame_delta,
                }.items()
                if value is not None
            }
            print_json(cf.decide_audio(
                platform=args.platform,
                campaign_slug=args.campaign,
                recommendation_item_id=args.recommendation_item,
                account=args.account,
                content_tags=[tag.strip() for tag in args.content_tags.split(",") if tag.strip()],
                account_tags=[tag.strip() for tag in args.account_tags.split(",") if tag.strip()],
                visual_signal=visual_signal or None,
                limit=args.limit,
                select=args.select,
                operator=args.operator,
            ))
        elif args.cmd == "verify-audio":
            print_json(cf.verify_audio_for_post(
                args.post_id,
                proof_url=args.proof_url,
                proof_note=args.proof_note,
                operator=args.operator,
            ))
        elif args.cmd == "reference-patterns":
            print_json(cf.reference_patterns(args.limit))
        elif args.cmd == "select-reference-pattern":
            print_json(cf.select_reference_pattern(
                args.campaign,
                cluster_key=args.cluster_key,
                reference_pattern_id=args.reference_pattern_id,
                variant_count=args.variant_count,
                notes=args.notes,
            ))
        elif args.cmd == "reference-plan":
            print_json(cf.campaign_reference_plan(args.campaign))
        elif args.cmd == "prepare-from-reference":
            print_json(cf.prepare_reel_from_reference(
                campaign_slug=args.campaign,
                cluster_key=args.cluster_key,
                reference_pattern_id=args.reference_pattern_id,
                variant_count=args.variant_count,
                recipes=args.recipes,
                caption_color=args.caption_color,
                notes=args.notes,
                force_new=not args.reuse_existing,
            ))
        elif args.cmd == "make-batch":
            print_json(cf.make_batch(
                folder=Path(args.folder),
                campaign_slug=args.campaign,
                model_slug=args.model,
                output_format=args.format,
                variant_count=args.variant_count,
                reference_pattern=args.reference_pattern,
                contentforge_base_url=args.contentforge_base_url,
                user_id=args.user_id,
                dry_run_export=args.dry_run_export or True,
                workers=args.workers,
                recipes=args.recipes,
                auto_approve_warning_only=not args.no_auto_approve,
            ))
        elif args.cmd == "intake-finished-video":
            print_json(cf.intake_finished_video(
                input_path=Path(args.input),
                model_slug=args.model,
                platform=args.platform,
                goal=args.goal,
                reference_pattern=args.reference_pattern,
                campaign_slug=args.campaign,
                contentforge_base_url=args.contentforge_base_url,
                user_id=args.user_id,
                dry_run_export=args.dry_run_export or True,
                variant_count=args.variant_count,
                workers=args.workers,
                recipes=args.recipes,
                creative_plan=args.creative_plan,
                style_lane=args.style_lane,
                source_lineage_path=Path(args.source_lineage).expanduser() if args.source_lineage else None,
            ))
        elif args.cmd == "register-finished-video":
            placement_decision = None
            if args.caption_placement_decision_json:
                placement_decision = json.loads(args.caption_placement_decision_json)
                if not isinstance(placement_decision, dict):
                    raise SystemExit("--caption-placement-decision-json must be a JSON object")
            print_json(cf.register_finished_video(
                input_path=Path(args.input),
                campaign_slug=args.campaign,
                model_slug=args.model,
                caption=args.caption,
                caption_hash=args.caption_hash,
                caption_bank=args.caption_bank,
                creator_mix=args.creator_mix,
                creator_model=args.creator_model,
                track_id=args.track_id,
                track_name=args.track_name,
                audio_source=args.audio_source,
                selected_reason=args.selected_reason,
                operator=args.operator,
                approval_reason=args.approval_reason,
                review_batch=args.review_batch,
                caption_placement_policy=args.caption_placement_policy,
                caption_placement_decision=placement_decision,
            ))
        elif args.cmd == "archive-inventory":
            print_json(cf.archive_inventory_report(
                folder=Path(args.folder),
                campaign_slug=args.campaign,
                creator=args.creator,
                requested_count=args.requested_count,
                model_slug=args.model,
                recent_days=args.recent_days,
            ))
        elif args.cmd == "archive-candidate-quality":
            print_json(cf.archive_candidate_quality_report(
                inventory_report_path=Path(args.inventory_report),
                requested_count=args.requested_count,
                exclude_indices=args.exclude_index,
            ))
        elif args.cmd == "create-creative-plan":
            print_json(cf.create_creative_plan(
                name=args.name,
                platform=args.platform,
                target_account=args.target_account,
                daily_base_video_target=args.daily_base_video_target,
                style_lanes=[lane.strip() for lane in args.style_lanes.split(",") if lane.strip()],
                model_profile=args.model_profile,
                source_accounts=[account.strip() for account in args.source_accounts.split(",") if account.strip()],
                goal=args.goal,
                linked_campaign=args.linked_campaign,
            ))
        elif args.cmd == "creative-plan":
            print_json(cf.creative_plan(args.name))
        elif args.cmd == "update-creative-plan-status":
            print_json(cf.update_creative_plan_status(name=args.name, status=args.status))
        elif args.cmd == "sync-creative-plan-progress":
            print_json(cf.sync_creative_plan_progress(name=args.name, prompt_export_path=Path(args.prompt_export)))
        elif args.cmd == "activity-log":
            print_json({"schema": "campaign_factory.activity_log.v1", "campaign": args.campaign, "events": cf.events_for_campaign(args.campaign, limit=args.limit)})
        elif args.cmd == "jobs":
            print_json({"schema": "campaign_factory.jobs.v1", "campaign": args.campaign, "jobs": cf.jobs_for_campaign(args.campaign, limit=args.limit)})
        elif args.cmd == "job":
            print_json(cf.pipeline_job(args.id))
        elif args.cmd == "pipeline-smoke":
            pipeline_job = cf.create_pipeline_job(
                "pipeline_smoke",
                None,
                {
                    "folder": args.folder,
                    "campaign": args.campaign,
                    "model": args.model,
                    "userId": args.user_id,
                    "hookCount": len(args.hook or []),
                    "hooksPath": args.hooks,
                    "recipes": args.recipes or [],
                    "accounts": args.account or [],
                    "contentforgeBaseUrl": args.contentforge_base_url,
                    "runReel": args.run_reel,
                    "workers": args.workers,
                    "minScore": args.min_score,
                },
            )
            cf.start_pipeline_job(pipeline_job["id"])
            hooks = load_hooks(args.hooks, args.hook)
            if not hooks:
                cf.fail_pipeline_job(pipeline_job["id"], "pipeline-smoke requires --hook or --hooks")
                raise SystemExit("pipeline-smoke requires --hook or --hooks")
            try:
                result = {
                    "schema": "campaign_factory.pipeline_smoke.v1",
                    "campaign": args.campaign,
                    "pipelineJobId": pipeline_job["id"],
                    "import": cf.import_folder(
                        Path(args.folder),
                        campaign_slug=args.campaign,
                        model_slug=args.model,
                        account_handles=args.account,
                        platform="instagram",
                        notes="pipeline smoke import",
                    ),
                    "prepare": None,
                    "run": None,
                    "sync": None,
                    "audit": None,
                    "dryRunExport": None,
                    "readiness": None,
                }
                cf.set_pipeline_job_campaign(pipeline_job["id"], result["import"]["campaign"]["id"])
                result["prepare"] = cf.prepare_reel_inputs(
                    campaign_slug=args.campaign,
                    hooks=hooks,
                    recipes=args.recipes,
                    caption_color="auto",
                    notes="pipeline smoke render",
                )
                if args.run_reel:
                    result["run"] = cf.run_reel_factory(
                        campaign_slug=args.campaign,
                        workers=args.workers,
                        dry_run=False,
                        caption_band="auto",
                        caption_color="light",
                        caption_style="ig",
                        caption_font="Instagram Sans Condensed",
                        phone_finalize=True,
                    )
                result["sync"] = cf.sync_reel_outputs(campaign_slug=args.campaign)
                result["audit"] = audit_campaign(
                    cf,
                    campaign_slug=args.campaign,
                    min_score=args.min_score,
                    contentforge_base_url=args.contentforge_base_url,
                )
                result["dryRunExport"] = export_threadsdash(
                    cf,
                    campaign_slug=args.campaign,
                    user_id=args.user_id,
                    dry_run=True,
                )
                result["readiness"] = evaluate_export_readiness(
                    cf,
                    campaign_slug=args.campaign,
                    user_id=args.user_id,
                )
                cf.finish_pipeline_job(pipeline_job["id"], {
                    "campaign": args.campaign,
                    "importedCount": len((result.get("import") or {}).get("imported") or []),
                    "syncedCount": len((result.get("sync") or {}).get("synced") or []),
                    "draftCount": (result.get("dryRunExport") or {}).get("draftCount"),
                })
                print_json(result)
            except Exception as exc:
                cf.record_event(
                    "pipeline_smoke_failed",
                    pipeline_job_id=pipeline_job["id"],
                    status="failure",
                    message=f"Pipeline smoke failed: {exc}",
                    metadata={"error": str(exc)},
                )
                cf.fail_pipeline_job(pipeline_job["id"], str(exc))
                raise
    finally:
        cf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
