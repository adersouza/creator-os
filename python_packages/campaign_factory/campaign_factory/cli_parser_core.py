from __future__ import annotations

import os
from pathlib import Path

from .closed_loop_proof import DEFAULT_STACEY_PROMPT_PATH


def register_core_commands(sub) -> None:
    sub.add_parser("init")
    reconcile = sub.add_parser(
        "reconcile",
        help="report or explicitly repair database/filesystem byte drift",
    )
    reconcile_sub = reconcile.add_subparsers(dest="reconcile_cmd", required=True)
    reconcile_report = reconcile_sub.add_parser("report")
    reconcile_report.add_argument(
        "--summary",
        action="store_true",
        help="emit bounded counts and examples instead of every finding",
    )
    reconcile_report.add_argument(
        "--examples-per-class",
        type=int,
        default=3,
        help="bounded examples retained per finding class in --summary output",
    )
    reconcile_repair = reconcile_sub.add_parser("repair")
    reconcile_repair.add_argument("--case", required=True)
    reconcile_repair.add_argument(
        "--fingerprint",
        help="exact fingerprint from the preview; blocks stale repair input",
    )
    reconcile_repair.add_argument("--operator", required=True)
    reconcile_repair.add_argument("--reason", required=True)
    reconcile_repair.add_argument("--apply", action="store_true")
    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="state_cmd", required=True)
    state_explain = state_sub.add_parser("explain")
    state_explain.add_argument("record_or_id")
    bridge = sub.add_parser("bridge")
    bridge_sub = bridge.add_subparsers(dest="bridge_cmd", required=True)
    bridge_reconcile = bridge_sub.add_parser("reconcile")
    bridge_reconcile.add_argument("--export-id")
    bridge_reconcile.add_argument(
        "--threadsdash-ingest-url",
        default=os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
        or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL"),
    )
    bridge_reconcile.add_argument(
        "--threadsdash-ingest-secret",
        default=os.environ.get("CAMPAIGN_FACTORY_INGEST_SECRET"),
    )
    provider = sub.add_parser("provider")
    provider_sub = provider.add_subparsers(dest="provider_cmd", required=True)
    provider_sub.add_parser("reconcile")
    create = sub.add_parser(
        "create",
        help="create an independent production batch from operator intent",
    )
    create.add_argument("--creator", required=True)
    create.add_argument(
        "--mode",
        required=True,
        choices=["static_reel", "calm_animation", "recreate_reel"],
    )
    create.add_argument(
        "--style",
        choices=[
            "passive_selfie",
            "flirty_portrait",
            "outfit",
            "lifestyle",
            "animate_existing",
        ],
        default="passive_selfie",
    )
    create.add_argument("--count", type=int, default=1)
    create.add_argument("--execution", choices=["cloud"], default="cloud")
    create.add_argument("--max-credits", type=float, default=100.0)
    create.add_argument("--concurrency", type=int, default=2)
    create.add_argument("--accounts")
    create.add_argument(
        "--source-asset-id",
        action="append",
        default=[],
        help="exact approved tiered still to use for static_reel; repeatable",
    )
    create.add_argument(
        "--reuse-policy",
        choices=["prefer_exact", "require_fresh"],
        default="prefer_exact",
    )
    reference_input = create.add_mutually_exclusive_group()
    reference_input.add_argument("--reference-video", type=Path)
    reference_input.add_argument("--reference-url")
    create.add_argument("--creator-image", type=Path)
    create.add_argument(
        "--recreation-anchor-approval",
        type=Path,
        help="exact-SHA Soul anchor approval required for paid recreate execution",
    )
    create.add_argument(
        "--recreation-attempt-id",
        help="explicit new paid-attempt identity; changing it requires fresh authorization",
    )
    create.add_argument("--reference-platform")
    create.add_argument("--reference-authorized", action="store_true")
    create.add_argument("--reference-talking", action="store_true")
    create.add_argument("--reference-non-talking", action="store_true")
    create.add_argument(
        "--reference-classification",
        choices=[
            "passive_single_shot",
            "simple_pose_motion",
            "walking",
            "dance",
            "first_last_transition",
            "structural_reference",
            "talking",
            "lip_sync",
            "multi_shot",
            "multi_person",
            "heavy_occlusion",
            "unsupported",
        ],
    )
    create.add_argument(
        "--reference-warning",
        action="append",
        choices=[
            "secondary_person_interaction",
            "heavy_occlusion",
            "identity_reset_required",
        ],
        default=[],
    )
    create.add_argument(
        "--recreate-mode",
        choices=["auto", "calm", "structural"],
        default="auto",
    )
    create.add_argument("--through", choices=["analyze", "anchor"])
    create.add_argument(
        "--audio",
        dest="audio_preference",
        choices=[
            "embedded_trending",
            "embedded_trending_required",
            "native_trending_required",
            "original_embedded",
            "creator_voice",
            "royalty_free",
            "silent_allowed",
            "reference_audio_required",
            "auto",
        ],
        default="embedded_trending_required",
    )
    create.add_argument("--apply", action="store_true")
    anchor_approval = sub.add_parser(
        "recreation-anchor-approve",
        help="approve exact downloaded Soul 2 anchor bytes for recreate execution",
    )
    anchor_approval.add_argument("--creator", required=True)
    anchor_approval.add_argument("--anchor-file", type=Path, required=True)
    anchor_approval.add_argument("--anchor-generation-id", required=True)
    anchor_approval.add_argument("--prompt-pack", type=Path, required=True)
    anchor_approval.add_argument(
        "--selected-composition-frame-sha256",
        required=True,
    )
    anchor_approval.add_argument("--approved-by", required=True)
    anchor_approval.add_argument("--output-dir", type=Path)
    recreation = sub.add_parser(
        "recreation",
        help="review or explain one recreation lineage chain",
    )
    recreation_sub = recreation.add_subparsers(dest="recreation_cmd", required=True)
    recreation_explain = recreation_sub.add_parser("explain")
    recreation_explain.add_argument("--job", required=True)
    recreation_review = recreation_sub.add_parser("review")
    recreation_review.add_argument("--job", required=True)
    recreation_review.add_argument(
        "--stage", required=True, choices=["anchor", "final_video"]
    )
    recreation_review.add_argument(
        "--decision", required=True, choices=["approved", "rejected"]
    )
    recreation_review.add_argument("--reviewed-by", required=True)
    recreation_review.add_argument("--notes")
    asset = sub.add_parser(
        "asset",
        help="explain exact asset lineage and inspect reuse inventory",
    )
    asset_sub = asset.add_subparsers(dest="asset_cmd", required=True)
    asset_explain = asset_sub.add_parser("explain")
    asset_explain.add_argument("--sha", required=True)
    asset_inventory = asset_sub.add_parser("inventory")
    asset_inventory.add_argument("--campaign")
    asset_inventory.add_argument(
        "--surface",
        choices=["reel", "story", "feed_single", "feed_carousel"],
    )
    asset_reservations = asset_sub.add_parser("reservations")
    reservation_sub = asset_reservations.add_subparsers(
        dest="reservation_cmd", required=True
    )
    reservation_reconcile = reservation_sub.add_parser("reconcile")
    reservation_reconcile.add_argument("--apply", action="store_true")
    reservation_cancel = reservation_sub.add_parser("cancel")
    reservation_cancel.add_argument("--reservation", required=True)
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
    run.add_argument("--apply", action="store_true")
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
    orchestrate = sub.add_parser(
        "orchestrate-daily",
        help="fairly plan or execute Creator OS creation without publishing",
    )
    orchestrate.add_argument("--run-key", required=True)
    orchestrate.add_argument("--max-items", type=int, required=True)
    orchestrate.add_argument("--per-creator-cap", type=int, default=2)
    orchestrate.add_argument("--per-campaign-cap", type=int, default=1)
    orchestrate.add_argument("--provider-cap", type=int, default=0)
    orchestrate.add_argument("--max-attempts", type=int, default=3)
    orchestrate.add_argument("--apply", action="store_true")
    orchestrate.add_argument("--execute", action="store_true")
    stills = sub.add_parser(
        "stills",
        help="enroll, harvest, edit, and report reusable derived still inventory",
    )
    stills_sub = stills.add_subparsers(dest="stills_cmd", required=True)
    stills_enroll = stills_sub.add_parser("enroll")
    stills_enroll.add_argument("--campaign", required=True)
    stills_enroll.add_argument("--source-asset-id", required=True)
    stills_enroll.add_argument(
        "--tier",
        required=True,
        choices=["canonical_identity_source", "approved_generated_still"],
    )
    stills_enroll.add_argument("--apply", action="store_true")
    stills_harvest = stills_sub.add_parser("harvest")
    stills_harvest.add_argument("--campaign", required=True)
    stills_harvest.add_argument("--rendered-asset-id", required=True)
    stills_harvest.add_argument("--count", type=int, default=6)
    stills_harvest.add_argument("--apply", action="store_true")
    stills_edit = stills_sub.add_parser("edit")
    stills_edit.add_argument("--campaign", required=True)
    stills_edit.add_argument("--image-asset-id", required=True)
    stills_edit.add_argument(
        "--operation", required=True, choices=["colorway", "outfit_swap"]
    )
    stills_edit.add_argument("--provider", required=True, choices=["gemini", "openai"])
    stills_edit.add_argument(
        "--format",
        dest="output_format",
        required=True,
        choices=["individual", "grid_2x3"],
    )
    stills_edit.add_argument("--count", type=int, default=6)
    stills_edit.add_argument("--max-usd", type=float, required=True)
    stills_edit.add_argument("--apply", action="store_true")
    stills_report = stills_sub.add_parser("report")
    stills_report.add_argument("--campaign", required=True)
    variation = sub.add_parser("variation")
    variation_sub = variation.add_subparsers(dest="variation_cmd", required=True)
    variation_run = variation_sub.add_parser("run")
    variation_run.add_argument("--campaign", required=True)
    variation_run.add_argument("--preset", default="ig_subtle")
    variation_run.add_argument("--rendered-asset-id", action="append", default=[])
    variation_run.add_argument("--contentforge-base-url", default="cli://local")
    variation_run.add_argument("--dry-run", action="store_true")
    variation_run.add_argument("--apply", action="store_true")
    creative_approval = sub.add_parser(
        "creative-approval-build",
        help="build and sign one exact v2 approval from a generated review draft",
    )
    creative_approval.add_argument("--campaign", required=True)
    creative_approval.add_argument("--rendered-asset-id", required=True)
    creative_approval.add_argument("--user-id", required=True)
    creative_approval.add_argument("--approved-by", required=True)
    creative_approval.add_argument("--review-decision", type=Path, required=True)
    creative_approval.add_argument("--root", type=Path)
    creative_approval.add_argument(
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
    )
    creative_approval.add_argument(
        "--publish-mode", choices=["auto", "notify"], default=None
    )
    approval_hygiene = sub.add_parser(
        "creative-approval-evidence-hygiene",
        help="inventory or quarantine test/fixture approval evidence without deletion",
    )
    approval_hygiene.add_argument("--root", type=Path)
    approval_hygiene.add_argument("--quarantine-root", type=Path)
    approval_hygiene.add_argument("--limit", type=int, default=500)
    approval_hygiene.add_argument("--apply", action="store_true")
    audit = sub.add_parser("audit")
    audit.add_argument("--campaign", required=True)
    audit.add_argument("--min-score", type=int, default=85)
    audit.add_argument("--contentforge-base-url", default="cli://local")
    audit.add_argument("--layer", action="append", default=[])
    audit.add_argument("--rendered-asset-id", action="append", default=[])
    qc_explain = sub.add_parser("qc-explain")
    qc_explain.add_argument("--asset", required=True)
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
    export.add_argument(
        "--threadsdash-ingest-url",
        default=os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
        or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL"),
    )
    export.add_argument(
        "--threadsdash-ingest-secret",
        default=os.environ.get("CAMPAIGN_FACTORY_INGEST_SECRET"),
    )
    export.add_argument(
        "--supabase-storage-bucket",
        default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"),
    )
    export.add_argument("--allow-warnings", action="store_true")
    export.add_argument("--warning-override-reason")
    export.add_argument("--warning-override-by")
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
    reddit_brief = sub.add_parser(
        "reddit-brief",
        help="build a versioned Reddit rules/trend brief from reviewed research",
    )
    reddit_brief.add_argument("--campaign", required=True)
    reddit_brief.add_argument("--spec", type=Path, required=True)
    reddit_brief.add_argument("--apply", action="store_true")
    reddit_assign = sub.add_parser(
        "reddit-assign",
        help="preview or audit a proposed Reddit account assignment",
    )
    reddit_assign.add_argument("--campaign", required=True)
    reddit_assign.add_argument("--asset", required=True)
    reddit_assign.add_argument("--account", required=True)
    reddit_assign.add_argument("--operator", required=True)
    reddit_assign.add_argument("--reason", required=True)
    reddit_assign.add_argument("--apply", action="store_true")
    reddit_handoff = sub.add_parser(
        "reddit-handoff",
        help="review or export one approved manual Reddit task",
    )
    reddit_handoff.add_argument("--campaign", required=True)
    reddit_handoff.add_argument("--spec", type=Path, required=True)
    reddit_handoff.add_argument("--apply", action="store_true")
    reddit_handoff.add_argument("--deliver", action="store_true")
    reddit_handoff.add_argument(
        "--threadsdash-ingest-url",
        default=os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
        or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL"),
    )
    reddit_handoff.add_argument(
        "--threadsdash-ingest-secret",
        default=os.environ.get("CAMPAIGN_FACTORY_INGEST_SECRET"),
    )
    reddit_schedule = sub.add_parser(
        "reddit-schedule",
        help="show the fixed Eastern-time Reddit manual posting windows",
    )
    reddit_schedule.add_argument("--date", required=True)
    reddit_schedule.add_argument("--include-optional", action="store_true")
    reddit_library = sub.add_parser(
        "reddit-library",
        help="derive Reddit working-shelf views and seven-day coverage",
    )
    reddit_library.add_argument("--campaign", required=True)
    reddit_library.add_argument("--state", type=Path, required=True)
    reddit_library.add_argument("--as-of")
    reddit_archive = sub.add_parser(
        "reddit-library-archive",
        help="preview or archive eligible assets without deleting media or history",
    )
    reddit_archive.add_argument("--campaign", required=True)
    reddit_archive.add_argument("--state", type=Path, required=True)
    reddit_archive.add_argument("--asset", action="append", required=True)
    reddit_archive.add_argument("--operator", required=True)
    reddit_archive.add_argument("--reason", required=True)
    reddit_archive.add_argument("--as-of")
    reddit_archive.add_argument("--apply", action="store_true")
    reddit_weekly = sub.add_parser(
        "reddit-weekly",
        help="research active subreddits and prepare the next seven-day content plan",
    )
    reddit_weekly.add_argument("--campaign", required=True)
    reddit_weekly.add_argument("--state", type=Path)
    reddit_weekly.add_argument("--user-id")
    reddit_weekly.add_argument("--as-of")
    reddit_weekly.add_argument("--limit", type=int, default=25)
    reddit_weekly.add_argument(
        "--no-download-references",
        action="store_false",
        dest="download_references",
    )
    reddit_weekly.set_defaults(download_references=True)
    reddit_weekly.add_argument(
        "--threadsdash-ingest-url",
        default=os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
        or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL"),
    )
    reddit_weekly.add_argument(
        "--threadsdash-ingest-secret",
        default=os.environ.get("CAMPAIGN_FACTORY_INGEST_SECRET"),
    )
    reddit_weekly_generate = sub.add_parser(
        "reddit-weekly-generate",
        help="dry-run or execute one reviewed weekly Reddit generation request",
    )
    reddit_weekly_generate.add_argument("--plan", type=Path, required=True)
    reddit_weekly_generate.add_argument("--request-id", required=True)
    reddit_weekly_generate.add_argument("--reviewed-by", required=True)
    reddit_weekly_generate.add_argument("--apply", action="store_true")
    reddit_weekly_generate.add_argument("--enable-paid-generation", action="store_true")
    reddit_weekly_generate.add_argument("--budget-cap-credits", type=float)
    reddit_weekly_generate.add_argument("--wait", action="store_true")
    reddit_weekly_generate.add_argument("--download", action="store_true")
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
    register_motion_qc = sub.add_parser(
        "register-motion-qc-receipt",
        help="register immutable, media-bound ContentForge motion-QC evidence",
    )
    register_motion_qc.add_argument("--rendered-asset-id", required=True)
    register_motion_qc.add_argument("--receipt", type=Path, required=True)
    register_motion_qc.add_argument("--operator")
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
    generate_variants.add_argument("--count", type=int, required=True)
    generate_variants.add_argument(
        "--profile",
        required=True,
        choices=[
            "mirror_crop_tone@1",
            "tilt_crop_dark@1",
            "light_editorial@1",
            "opening_trim@1",
            "auto",
        ],
    )
    generate_variants.add_argument("--attempt-limit", type=int)
    generate_variants.add_argument("--contentforge-base-url", default="cli://local")
    generate_variants.add_argument("--source-media-path")
    generate_variants.add_argument("--dry-run", action="store_true")
    bind_caption = sub.add_parser("bind-observed-caption")
    bind_caption.add_argument("--rendered-asset-id", required=True)
    bind_caption.add_argument("--output", type=Path, required=True)
    qualify_control = sub.add_parser("qualify-observed-renderer-control")
    qualify_control.add_argument("--rendered-asset-id", required=True)
    assign_pair = sub.add_parser("assign-experiment-pair")
    assign_pair.add_argument(
        "--input-json",
        type=Path,
        required=True,
        help="pair assignment request JSON; creates no schedule or publication",
    )
    experiment_report = sub.add_parser("observed-experiment-report")
    experiment_report.add_argument("--experiment-id", required=True)
    experiment_report.add_argument(
        "--record-interpretation",
        action="store_true",
        help="persist the report only; never changes production usage",
    )
    experiment_decision = sub.add_parser("observed-experiment-decision")
    experiment_decision.add_argument("--experiment-id", required=True)
    experiment_decision.add_argument("--operator", required=True)
    experiment_decision.add_argument(
        "--decision",
        required=True,
        choices=["continue_sequence", "stop", "adopt", "reject"],
    )
    experiment_decision.add_argument("--reason", required=True)
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
