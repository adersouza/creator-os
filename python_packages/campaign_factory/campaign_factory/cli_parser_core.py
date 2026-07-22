from __future__ import annotations

import os
from pathlib import Path

from .closed_loop_proof import DEFAULT_STACEY_PROMPT_PATH
from .creative_modes import creative_workflow_mode_ids


def register_core_commands(sub) -> None:
    sub.add_parser("init")
    sub.add_parser(
        "control-check",
        help="check Campaign Factory's local component/tooling dependencies",
    )
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
    imp.add_argument(
        "--storage-mode",
        choices=["copy", "reference"],
        default="copy",
        help="copy media into the campaign or catalog the original paths in place",
    )
    prep = sub.add_parser("prepare-reel")
    prep.add_argument("--campaign", required=True)
    prep.add_argument("--hooks")
    prep.add_argument("--hook", action="append", default=[])
    prep.add_argument("--recipes", nargs="*", default=None)
    prep.add_argument("--caption-color", default="auto")
    prep.add_argument("--notes")
    prep.add_argument("--force-new", action="store_true")
    prep.add_argument("--source-asset-id", action="append", default=[])
    run = sub.add_parser("run-reel")
    run.add_argument("--campaign", required=True)
    run.add_argument("--workers", type=int, default=3)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--band", choices=["top", "center", "bottom"], default="center")
    run.add_argument("--color", choices=["light", "dark", "auto"], default="light")
    run.add_argument(
        "--style",
        choices=["classic", "meme", "ig", "thin", "soft", "bubble", "auto"],
        default="ig",
    )
    run.add_argument("--font", default="Instagram Sans Condensed")
    run.add_argument("--no-phone-finalize", action="store_true")
    run.add_argument("--rerender-all", action="store_true")
    run.add_argument("--max-outputs-per-clip", type=int, default=None)
    run.add_argument("--render-job-id", action="append", default=[])
    run.add_argument("--caption-mix", choices=["Larissa", "Stacey", "Lola"])
    run.add_argument(
        "--creator-style-preset", choices=["auto", "none", "stacey_static_center"]
    )
    sync = sub.add_parser("sync-reel")
    sync.add_argument("--campaign", required=True)
    sync.add_argument("--render-job-id", action="append", default=[])
    daily_library = sub.add_parser("daily-library")
    daily_library.add_argument("--day", type=int, required=True)
    daily_library.add_argument("--cohort", default="stacey_learning_cohort_v1")
    daily_library.add_argument("--campaign", default="stacey_learning_cohort_v1")
    daily_library.add_argument("--workers", type=int, default=2)
    daily_library.add_argument("--library-root", type=Path)
    daily_library.add_argument("--contentforge-base-url", default="cli://local")
    daily_library.add_argument("--apply", action="store_true")
    variation = sub.add_parser("variation")
    variation_sub = variation.add_subparsers(dest="variation_cmd", required=True)
    variation_run = variation_sub.add_parser("run")
    variation_run.add_argument("--campaign", required=True)
    variation_run.add_argument("--preset", default="ig_subtle")
    variation_run.add_argument("--rendered-asset-id", action="append", default=[])
    variation_run.add_argument("--contentforge-base-url", default="cli://local")
    variation_run.add_argument("--dry-run", action="store_true")
    variation_run.add_argument("--apply", action="store_true")
    generation = sub.add_parser("generation")
    generation_sub = generation.add_subparsers(dest="generation_cmd", required=True)
    generation_sub.add_parser("modes")
    generation_run = generation_sub.add_parser(
        "run", help="run exactly one explicit generation mode; never publishes"
    )
    generation_run.add_argument(
        "--mode", choices=creative_workflow_mode_ids(), required=True
    )
    generation_run.add_argument("--campaign", required=True)
    generation_execution = generation_run.add_mutually_exclusive_group(required=True)
    generation_execution.add_argument("--dry-run", action="store_true")
    generation_execution.add_argument("--apply", action="store_true")
    generation_run.add_argument("--reference-image", type=Path)
    generation_run.add_argument("--accepted-still", type=Path)
    generation_run.add_argument("--kling-selection-receipt", type=Path)
    generation_run.add_argument("--reference-video", type=Path)
    generation_run.add_argument("--target", dest="creator")
    generation_run.add_argument("--soul-id")
    generation_run.add_argument("--workspace", type=Path)
    generation_run.add_argument("--confirm-paid", action="store_true")
    generation_run.add_argument("--max-credits", type=float)
    generation_run.add_argument("--max-usd", type=float)
    generation_run.add_argument("--caption")
    generation_run.add_argument("--duration", type=float)
    generation_run.add_argument("--motion-model")
    generation_run.add_argument("--motion-prompt")
    generation_run.add_argument("--audio", type=Path)
    generation_run.add_argument("--last-image", type=Path)
    generation_run.add_argument(
        "--motion-reference-image", type=Path, action="append", default=[]
    )
    generation_run.add_argument(
        "--motion-reference-video", type=Path, action="append", default=[]
    )
    generation_run.add_argument("--resolution")
    generation_run.add_argument("--seed", type=int, default=42)
    generation_run.add_argument("--steps", type=int, default=40)
    generation_run.add_argument("--enable-prompt-expansion", action="store_true")
    generation_run.add_argument(
        "--shot-type", choices=["single", "multi"], default="single"
    )
    generation_run.add_argument("--local-wan-model-dir", type=Path)
    generation_run.add_argument("--count", type=int, default=3)
    generation_run.add_argument("--account")
    generation_run.add_argument("--folder", type=Path)
    generation_run.add_argument("--model")
    generation_run.add_argument(
        "--format", choices=["reel", "slideshow", "auto"], default="auto"
    )
    generation_run.add_argument("--variant-count", type=int, default=20)
    generation_run.add_argument("--workers", type=int, default=3)
    generation_run.add_argument("--first-frame-approval-id")
    generation_run.add_argument("--last-frame-approval-id")
    generation_run.add_argument("--operator-selected", action="store_true")
    generation_run.add_argument("--rights-confirmed", action="store_true")
    generation_run.add_argument(
        "--preferred-provider", choices=["auto", "seedance", "kling"], default="auto"
    )
    generation_run.add_argument(
        "--available-provider",
        choices=["seedance", "kling"],
        action="append",
        default=[],
    )
    generation_run.add_argument("--allow-upscale", action="store_true")
    generation_run.add_argument("--wait", action="store_true")
    generation_run.add_argument("--download", action="store_true")
    select_kling = generation_sub.add_parser("select-kling")
    select_kling.add_argument("--campaign", required=True)
    select_kling.add_argument("--rendered-asset-id", action="append", required=True)
    select_kling.add_argument("--batch-id")
    select_kling.add_argument("--dry-run", action="store_true")
    select_kling.add_argument("--apply", action="store_true")
    audit = sub.add_parser("audit")
    audit.add_argument("--campaign", required=True)
    audit.add_argument("--min-score", type=int, default=85)
    audit.add_argument("--contentforge-base-url", default="cli://local")
    audit.add_argument("--layer", action="append", default=[])
    audit.add_argument("--rendered-asset-id", action="append", default=[])
    approve = sub.add_parser("approve")
    approve.add_argument("--rendered-asset-id", required=True)
    approve.add_argument("--notes")
    approve.add_argument(
        "--force-unsafe-audit",
        action="store_true",
        help="Allow approval even when audit is missing or not an approved candidate",
    )
    review = sub.add_parser("review-decision")
    review.add_argument("--rendered-asset-id", required=True)
    review.add_argument("--decision", choices=["approved", "rejected"], required=True)
    review.add_argument("--notes")
    review.add_argument(
        "--force-unsafe-audit",
        action="store_true",
        help="Allow approval even when audit is missing or not an approved candidate",
    )
    attest = sub.add_parser("attest-publishability")
    attest.add_argument("--rendered-asset-id", required=True)
    attest.add_argument("--instagram-post-caption")
    attest.add_argument(
        "--visual-qc-status", choices=["passed", "failed", "unavailable"]
    )
    attest.add_argument(
        "--identity-verification-status", choices=["passed", "failed", "unavailable"]
    )
    attest.add_argument("--operator")
    attest.add_argument("--notes")
    readiness = sub.add_parser("export-readiness")
    readiness.add_argument("--campaign", required=True)
    readiness.add_argument("--user-id", required=True)
    readiness.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    readiness.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    readiness.add_argument("--limit", type=int, default=1000)
    readiness.add_argument("--content-pillar")
    readiness.add_argument("--cta-type")
    readiness.add_argument("--language")
    readiness.add_argument(
        "--schedule-mode", choices=["draft", "preview", "live"], default="draft"
    )
    mass_ready = sub.add_parser("readiness-report")
    mass_ready.add_argument("--campaign-id", required=True)
    mass_ready.add_argument("--days", type=int, default=7)
    mass_ready.add_argument("--user-id")
    mass_ready.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    mass_ready.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    mass_ready.add_argument("--limit", type=int, default=1000)
    mass_ready.add_argument("--format", choices=["json", "markdown"], default="json")
    caption_outcome = sub.add_parser("caption-outcome-report")
    caption_outcome.add_argument("--campaign", required=True)
    reference_outcome = sub.add_parser("reference-outcome-report")
    reference_outcome.add_argument("--campaign", required=True)
    track_q_calibration = sub.add_parser("track-q-calibration-status")
    track_q_calibration.add_argument("--campaign")
    track_q_calibration.add_argument("--min-reviewed-reels", type=int, default=30)
    track_q_calibration.add_argument(
        "--min-low-score-or-rejected-samples", type=int, default=10
    )
    track_q_calibration.add_argument("--low-score-threshold", type=int, default=70)
    closed_loop_status = sub.add_parser("closed-loop-learning-status")
    closed_loop_status.add_argument("--campaign")
    closed_loop_status.add_argument("--min-posts-with-1h-and-24h", type=int, default=50)
    learning_cohort = sub.add_parser("learning-cohort")
    learning_cohort_sub = learning_cohort.add_subparsers(
        dest="learning_cohort_cmd", required=True
    )
    cohort_prepare = learning_cohort_sub.add_parser("prepare")
    cohort_prepare.add_argument("--start-date", required=True)
    cohort_prepare.add_argument("--seed", default="stacey_learning_cohort_v1")
    cohort_run_day = learning_cohort_sub.add_parser("run-day")
    cohort_run_day.add_argument("--day", type=int, required=True)
    cohort_assign = learning_cohort_sub.add_parser("assign-references")
    cohort_assign.add_argument("--identity-manifest", type=Path, required=True)
    cohort_assign.add_argument("--apply", action="store_true")
    cohort_generation = learning_cohort_sub.add_parser("record-generation")
    cohort_generation.add_argument("--assignment", required=True)
    cohort_generation.add_argument("--rendered-asset-id", required=True)
    cohort_generation.add_argument("--lineage", type=Path, required=True)
    cohort_generation.add_argument("--artifact", type=Path, required=True)
    cohort_generation.add_argument("--provider-reservation-id")
    cohort_draft = learning_cohort_sub.add_parser("record-draft")
    cohort_draft.add_argument("--assignment", required=True)
    cohort_draft.add_argument("--draft-id", required=True)
    cohort_approval = learning_cohort_sub.add_parser("record-approval")
    cohort_approval.add_argument("--assignment", required=True)
    cohort_approval.add_argument(
        "--decision", choices=["approved", "rejected"], required=True
    )
    cohort_publish = learning_cohort_sub.add_parser("record-publish")
    cohort_publish.add_argument("--assignment", required=True)
    cohort_publish.add_argument("--post-id", required=True)
    cohort_publish.add_argument("--published-at", required=True)
    learning_cohort_sub.add_parser("status")
    learning_cohort_sub.add_parser("audit")
    routing_audit = sub.add_parser("account-routing-audit")
    routing_audit.add_argument("--creator", required=True)
    routing_audit.add_argument("--user-id", required=True)
    routing_audit.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    routing_audit.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY"),
    )
    closed_loop = sub.add_parser("closed-loop-proof")
    closed_loop.add_argument("--campaign", default="stacey_closed_loop")
    closed_loop.add_argument("--user-id", default=os.environ.get("THREADSDASH_USER_ID"))
    closed_loop.add_argument(
        "--output-dir", default=str(Path(__file__).resolve().parents[1])
    )
    closed_loop.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    closed_loop.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    closed_loop.add_argument(
        "--supabase-storage-bucket",
        default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"),
    )
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
    graduate_trial = sub.add_parser("graduate-trial-reel")
    graduate_trial.add_argument("--trial-post-id", required=True)
    graduate_trial.add_argument("--distribution-plan-id", required=True)
    graduate_trial.add_argument("--approved-by", required=True)
    observe_trial = sub.add_parser("record-trial-observation")
    observe_trial.add_argument("--trial-post-id", required=True)
    observe_trial.add_argument("--distribution-plan-id", required=True)
    observe_trial.add_argument("--account-id", required=True)
    observe_trial.add_argument(
        "--observed-hours", type=int, choices=[1, 24], required=True
    )
    observe_trial.add_argument("--views", type=int, required=True)
    observe_trial.add_argument("--engagement", type=int, required=True)
    observe_trial.add_argument("--metrics-json")
    sub.add_parser("trial-reel-ranking-report")
    export = sub.add_parser("export-threadsdash")
    export.add_argument("--campaign", required=True)
    export.add_argument("--user-id", required=True)
    export.add_argument("--dry-run", action="store_true")
    export.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    export.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    export.add_argument(
        "--supabase-storage-bucket",
        default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"),
    )
    export.add_argument("--allow-warnings", action="store_true")
    export.add_argument("--content-pillar")
    export.add_argument("--cta-type")
    export.add_argument("--language")
    export.add_argument("--max-drafts", type=int)
    export.add_argument("--rendered-asset-id", action="append", default=[])
    export.add_argument(
        "--surface",
        choices=[
            "regular_reel",
            "trial_reel",
            "story",
            "story_cta",
            "feed_single",
            "feed_carousel",
        ],
        default="regular_reel",
        help="Export only the selected distribution surface",
    )
    export.add_argument(
        "--schedule-mode", choices=["draft", "preview", "live"], default="draft"
    )
    export.add_argument(
        "--publish-mode",
        choices=["auto", "notify"],
        default=None,
        help="Override per-draft publish mode; default is notify for reels, auto otherwise",
    )
    export.add_argument("--enable-variation", action="store_true")
    export.add_argument("--variation-preset", default="ig_subtle")
    export.add_argument(
        "--draft-payload-schema",
        choices=["v3", "v2"],
        default="v3",
        help=(
            "ThreadsDashboard draft contract. v3 is current; use v2 only for an "
            "explicit compatibility rollback."
        ),
    )
    export.add_argument(
        "--review-only",
        action="store_true",
        help="Export review_ready assets as unapproved, unscheduled review drafts",
    )
    preflight = sub.add_parser("supabase-preflight")
    preflight.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    preflight.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    preflight.add_argument(
        "--supabase-storage-bucket",
        default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"),
    )
    verify = sub.add_parser("verify-threadsdash-export")
    verify.add_argument("export_manifest")
    verify.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    verify.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    usage = sub.add_parser("threadsdash-usage")
    usage.add_argument("--campaign", required=True)
    usage.add_argument("--user-id", required=True)
    usage.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    usage.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    usage.add_argument("--limit", type=int, default=1000)
    assignment_sync = sub.add_parser("sync-threadsdash-assignments")
    assignment_sync.add_argument("--campaign", required=True)
    assignment_sync.add_argument("--user-id", required=True)
    assignment_sync.add_argument(
        "--supabase-url", default=os.environ.get("SUPABASE_URL")
    )
    assignment_sync.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    assignment_sync.add_argument("--limit", type=int, default=1000)
    perf_sync = sub.add_parser("sync-performance")
    perf_sync.add_argument("--campaign", required=True)
    perf_sync.add_argument("--user-id", required=True)
    perf_sync.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    perf_sync.add_argument(
        "--supabase-service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
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
    register_surface.add_argument(
        "--surface", choices=["feed_single", "story", "feed_carousel"], required=True
    )
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
    lifecycle.add_argument(
        "--include-threadsdash", choices=["auto", "live", "off"], default="auto"
    )
    lifecycle.add_argument("--state")
    lifecycle.add_argument("--blocking-reason")
    lifecycle.add_argument("--rendered-asset-id")
    lifecycle.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output; retained for explicit operator intent",
    )
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
    generate_variants.add_argument("--contentforge-base-url", default="cli://local")
    generate_variants.add_argument("--source-media-path")
    generate_variants.add_argument("--dry-run", action="store_true")
    winner_plan = sub.add_parser("winner-expansion-plan")
    winner_plan.add_argument(
        "--input-json",
        help="JSON string or path containing creator, parentAssetId, targetVariants, and preset",
    )
    winner_plan.add_argument("--creator")
    winner_plan.add_argument("--parent-asset-id")
    winner_plan.add_argument("--target-variants", type=int)
    winner_plan.add_argument("--preset")
    caption_plan = sub.add_parser("caption-family-plan")
    caption_plan.add_argument(
        "--input-json",
        help="JSON string or path containing creator, parentAssetId, requestedCaptionVersions, style, and dryRun",
    )
    caption_plan.add_argument("--creator")
    caption_plan.add_argument("--parent-asset-id")
    caption_plan.add_argument("--requested-caption-versions", type=int)
    caption_plan.add_argument("--style")
    caption_plan.add_argument("--dry-run", action="store_true")
    caption_create = sub.add_parser("caption-family-create")
    caption_create.add_argument(
        "--input-json",
        help="JSON string or path containing creator, parentAssetId, requestedCaptionVersions, style, and dryRun",
    )
    caption_create.add_argument("--creator")
    caption_create.add_argument("--parent-asset-id")
    caption_create.add_argument("--requested-caption-versions", type=int)
    caption_create.add_argument("--style")
    caption_create.add_argument("--dry-run", action="store_true")
    inventory_plan = sub.add_parser("variant-inventory-plan")
    inventory_plan.add_argument(
        "--input-json",
        help="JSON string or path containing creator, campaign, targetDraftShortfall, preset, maxVariantsPerParent, minimumRecommendedPerParent, and dryRun",
    )
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
