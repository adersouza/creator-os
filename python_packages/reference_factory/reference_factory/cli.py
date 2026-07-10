from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .audio import (
    analyze_audio_patterns,
    audio_catalog_health,
    audio_resolution_shortlist,
    competitor_audio_leaderboard,
    export_audio_catalog,
    import_audio_csv,
    import_audio_snapshot_csv,
    import_example_reel_audio,
    list_audio_catalog,
    list_audio_trend_snapshots,
    recommend_audio,
    resolve_audio_record,
    review_audio_catalog,
    scrape_instagram_audio,
    upsert_audio_trend_snapshot,
)
from .audio_refresh import refresh_tiktok_audio
from .caption_adaptation import adapt_caption_library, ensure_default_profile
from .config import (
    DEFAULT_DATA_ROOT,
    DEFAULT_DB_PATH,
    DEFAULT_SOURCE_ROOT,
    DEFAULT_TIKTOK_SOURCE_ROOT,
    ensure_data_dirs,
)
from .contact_sheet import generate_contact_sheet
from .db import connect
from .embeddings import DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_THRESHOLD
from .fileops import atomic_write_text
from .higgsfield_runner import generate_with_higgsfield, run_daily_generation
from .learning import build_learning_system, learning_summary
from .media import probe_videos, sample_frames, thumbnail_batch
from .ocr import ocr_cleanup, run_ocr
from .outcomes import import_prompt_outcomes_file
from .patterns import (
    analyze_patterns,
    apply_pattern_labels,
    export_patterns,
    pattern_summary,
)
from .proof_verifier import verify_proof_bundle
from .provider_doctor import provider_doctor
from .public_metrics import (
    export_learning_set,
    generate_prompt_cards,
    import_apify_metrics,
    top_public_posts,
)
from .reference_intake import (
    analyze_reference_local,
    analyze_reference_with_gemini_api,
    analyze_reference_with_grok_api,
    compile_prompts_with_grok_api,
    export_analysis_queue,
    export_video_analyses,
    export_video_prompts,
    generate_video_prompts,
    import_gemini_app_response,
    import_reference_analysis,
    queue_reference_analysis,
)
from .review import build_shortlist, export_gold, label_reference, review_batch
from .scan import scan_source
from .tiktok_archive import import_tiktok_archive


def parse_limit(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if value.lower() == "all":
        return None
    return int(value)


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reference_factory")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument(
        "--data-root", default=str(DEFAULT_DATA_ROOT), help="Derived data root"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Index source files without modifying them")
    scan.add_argument("--source", default=str(DEFAULT_SOURCE_ROOT))

    probe = sub.add_parser("probe", help="Probe indexed videos with ffprobe")
    probe.add_argument("--limit", default="all")

    frames = sub.add_parser(
        "sample-frames", help="Extract frame samples from valid videos"
    )
    frames.add_argument("--videos", default="all", help="Compatibility alias; use all")
    frames.add_argument("--limit", default=None)

    thumbs = sub.add_parser(
        "thumbnail-batch", help="Extract missing contact thumbnails"
    )
    thumbs.add_argument("--limit", default="all")

    ocr = sub.add_parser("ocr", help="Run OCR on sampled frames")
    ocr.add_argument(
        "--engine",
        default="auto",
        choices=["auto", "apple_vision", "tesseract", "heuristic"],
    )
    ocr.add_argument("--likely-captioned-only", action="store_true")
    ocr.add_argument("--limit", default=None)

    sub.add_parser("ocr-cleanup", help="Remove low-value OCR caption patterns")

    sheet = sub.add_parser("contact-sheet", help="Generate HTML/image contact sheet")
    sheet.add_argument(
        "--mode",
        default="random",
        choices=["random", "top-accounts", "captioned", "visual", "best", "unreviewed"],
    )
    sheet.add_argument("--count", type=int, default=100)
    sheet.add_argument("--per-account", type=int, default=25)

    shortlist = sub.add_parser("shortlist", help="Print ranked candidate shortlist")
    shortlist.add_argument("--target", type=int, default=300)

    review_batch_parser = sub.add_parser(
        "review-batch", help="Print a balanced guided review batch"
    )
    review_batch_parser.add_argument("--target", type=int, default=300)
    review_batch_parser.add_argument("--mode", default="balanced", choices=["balanced"])
    review_batch_parser.add_argument("--account-cap", type=int, default=30)

    label = sub.add_parser("label", help="Persist a manual review label")
    label.add_argument("--reference-id", required=True)
    label.add_argument("--label", required=True, choices=["gold", "maybe", "ignore"])
    label.add_argument("--tags", default="")
    label.add_argument("--notes", default=None)

    sub.add_parser("export-gold", help="Export gold label manifest")

    adapt_captions = sub.add_parser(
        "adapt-captions", help="Rewrite reference captions for the active model profile"
    )
    adapt_captions.add_argument(
        "--profile", default=None, help="Optional caption adaptation profile JSON path"
    )
    adapt_captions.add_argument(
        "--input", default=None, help="Optional caption library JSONL input path"
    )
    adapt_captions.add_argument(
        "--init-profile",
        action="store_true",
        help="Create the default profile and exit",
    )

    apify_import = sub.add_parser(
        "import-apify-metrics", help="Import Apify public post metrics"
    )
    apify_import.add_argument(
        "--input",
        action="append",
        required=True,
        help="Apify JSON output path; repeatable",
    )
    apify_import.add_argument("--top-limit", type=int, default=300)

    tiktok_import = sub.add_parser(
        "import-tiktok-archive",
        help="Import a local TikTok archive as slideshow references",
    )
    tiktok_import.add_argument("--source", default=str(DEFAULT_TIKTOK_SOURCE_ROOT))
    tiktok_import.add_argument("--top-limit", type=int, default=300)
    tiktok_import.add_argument(
        "--as-slideshow", action=argparse.BooleanOptionalAction, default=True
    )

    top_posts = sub.add_parser(
        "top-public-posts", help="Print top public posts by plays/views"
    )
    top_posts.add_argument("--limit", type=int, default=300)

    prompts = sub.add_parser(
        "generate-prompt-cards",
        help="Generate original prompt cards from public winners",
    )
    prompts.add_argument("--limit", type=int, default=50)

    learning = sub.add_parser(
        "export-learning-set",
        help="Export top public winners with prompt cards and ContentForge references",
    )
    learning.add_argument("--limit", type=int, default=300)
    learning.add_argument(
        "--copy-media",
        action="store_true",
        help="Copy matched local videos into the learning set reference folder",
    )

    patterns = sub.add_parser(
        "analyze-patterns",
        help="Analyze top public winners into reusable pattern labels",
    )
    patterns.add_argument("--limit", type=int, default=300)
    patterns.add_argument(
        "--provider", default="auto", choices=["auto", "heuristic", "ollama"]
    )
    patterns.add_argument("--ollama-model", default=None)

    outcome_import = sub.add_parser(
        "import-prompt-outcomes",
        help="Import Campaign Factory measured outcomes for generated Reference Factory prompts",
    )
    outcome_import.add_argument(
        "--input",
        action="append",
        required=True,
        help="JSON outcome file path; repeatable",
    )

    audio_patterns = sub.add_parser(
        "analyze-audio-patterns",
        help="Analyze top public winners into reusable audio recommendations",
    )
    audio_patterns.add_argument("--limit", type=int, default=300)

    competitor_audio = sub.add_parser(
        "competitor-audio", help="Rank audios used by similar creator public posts"
    )
    competitor_audio.add_argument("--platform", default=None)
    competitor_audio.add_argument(
        "--accounts",
        default="",
        help="Comma-separated creator usernames to filter, without scraping",
    )
    competitor_audio.add_argument(
        "--caption-keywords",
        default="",
        help="Comma-separated caption keywords such as ai, model, ofm",
    )
    competitor_audio.add_argument("--min-plays", type=int, default=0)
    competitor_audio.add_argument("--min-posts", type=int, default=1)
    competitor_audio.add_argument("--limit", type=int, default=50)
    competitor_audio.add_argument("--export", default=None)

    audio_import = sub.add_parser(
        "import-audio-csv", help="Import manually curated trending audio catalog CSV"
    )
    audio_import.add_argument("--input", required=True)

    example_audio_import = sub.add_parser(
        "import-example-reel-audio",
        help="Import audio signals from existing/reference reel metadata",
    )
    example_audio_import.add_argument(
        "--input",
        default=None,
        help="Optional JSON/CSV of example reels; defaults to imported public_posts",
    )
    example_audio_import.add_argument("--limit", type=int, default=500)
    example_audio_import.add_argument(
        "--export",
        default=None,
        help="Optional Campaign Factory audio catalog export path",
    )
    example_audio_import.add_argument(
        "--preserve-manual-fields", action=argparse.BooleanOptionalAction, default=True
    )

    ig_audio_scrape = sub.add_parser(
        "scrape-instagram-audio",
        help="Scrape public Instagram reel/post URLs for audio metadata",
    )
    ig_audio_scrape.add_argument(
        "--url", action="append", default=[], help="Instagram reel/post URL; repeatable"
    )
    ig_audio_scrape.add_argument(
        "--input",
        default=None,
        help="Optional text/JSON/CSV file of Instagram reel URLs",
    )
    ig_audio_scrape.add_argument("--limit", type=int, default=50)
    ig_audio_scrape.add_argument(
        "--export",
        default=None,
        help="Optional Campaign Factory audio catalog export path",
    )

    audio_list = sub.add_parser(
        "list-audio", help="List operator-curated audio catalog"
    )
    audio_list.add_argument("--platform")
    audio_list.add_argument("--fresh-only", action="store_true")
    audio_list.add_argument("--needs-review", action="store_true")
    audio_list.add_argument("--limit", type=int, default=100)
    audio_list.add_argument("--export", default=None, help="Optional JSON export path")

    audio_recommend = sub.add_parser(
        "recommend-audio", help="Recommend catalog audio by platform and tags"
    )
    audio_recommend.add_argument("--platform", required=True)
    audio_recommend.add_argument("--content-tags", default="")
    audio_recommend.add_argument("--account-tags", default="")
    audio_recommend.add_argument("--limit", type=int, default=3)

    audio_refresh = sub.add_parser(
        "refresh-tiktok-audio",
        help="Import local TikTok downloads and refresh audio recommendations",
    )
    audio_refresh.add_argument("--source", default=str(DEFAULT_TIKTOK_SOURCE_ROOT))
    audio_refresh.add_argument("--top-limit", type=int, default=500)
    audio_refresh.add_argument("--catalog-limit", type=int, default=80)
    audio_refresh.add_argument("--recommend-limit", type=int, default=10)
    audio_refresh.add_argument("--content-tags", default="ai_ofm,slideshow,glowup")
    audio_refresh.add_argument("--account-tags", default="")
    audio_refresh.add_argument(
        "--preserve-manual-fields", action=argparse.BooleanOptionalAction, default=True
    )

    audio_resolve = sub.add_parser(
        "resolve-audio",
        help="Resolve a generic native audio ID into an operator-ready catalog record",
    )
    audio_resolve.add_argument("--platform", required=True)
    audio_resolve.add_argument("--native-audio-id", required=True)
    audio_resolve.add_argument("--title", required=True)
    audio_resolve.add_argument("--artist", default=None)
    audio_resolve.add_argument("--url", default=None)
    audio_resolve.add_argument("--mood-tags", default=None)
    audio_resolve.add_argument("--content-tags", default=None)
    audio_resolve.add_argument("--account-tags", default=None)
    audio_resolve.add_argument("--trend-status", default=None)
    audio_resolve.add_argument("--usage-count", type=int, default=None)
    audio_resolve.add_argument("--expires-at", default=None)
    audio_resolve.add_argument("--safe-usage-notes", default=None)

    audio_health = sub.add_parser(
        "audio-health", help="Summarize catalog readiness for Campaign Factory"
    )
    audio_health.add_argument("--platform")
    audio_health.add_argument("--limit", type=int, default=10)
    audio_health.add_argument("--export", default=None)

    audio_shortlist = sub.add_parser(
        "audio-resolution-shortlist",
        help="Show the top unresolved native audio IDs to resolve today",
    )
    audio_shortlist.add_argument("--platform", default="tiktok")
    audio_shortlist.add_argument("--limit", type=int, default=10)
    audio_shortlist.add_argument("--export", default=None)

    audio_snapshot_import = sub.add_parser(
        "import-audio-snapshot-csv",
        help="Import manually curated audio trend snapshot CSV",
    )
    audio_snapshot_import.add_argument("--input", required=True)

    audio_snapshot_add = sub.add_parser(
        "add-audio-snapshot", help="Add one manually curated audio trend snapshot"
    )
    audio_snapshot_add.add_argument("--audio-catalog-id")
    audio_snapshot_add.add_argument("--platform")
    audio_snapshot_add.add_argument("--native-audio-id")
    audio_snapshot_add.add_argument("--observed-at")
    audio_snapshot_add.add_argument("--trend-status", default="unknown")
    audio_snapshot_add.add_argument("--usage-count", type=int)
    audio_snapshot_add.add_argument("--saturation-score", type=float)
    audio_snapshot_add.add_argument("--velocity-score", type=float)
    audio_snapshot_add.add_argument("--curator")
    audio_snapshot_add.add_argument("--source")
    audio_snapshot_add.add_argument("--notes")

    audio_snapshot_list = sub.add_parser(
        "list-audio-snapshots", help="List manually curated audio trend snapshots"
    )
    audio_snapshot_list.add_argument("--platform")
    audio_snapshot_list.add_argument("--audio-catalog-id")
    audio_snapshot_list.add_argument("--limit", type=int, default=100)

    doctor = sub.add_parser(
        "provider-doctor",
        help="Check local provider readiness without printing secrets",
    )
    doctor.add_argument(
        "--require-gemini",
        action="store_true",
        help="Treat missing Gemini API key as blocked",
    )
    doctor.add_argument(
        "--skip-xai-check",
        action="store_true",
        help="Skip xAI API reachability/billing check",
    )
    doctor.add_argument(
        "--skip-higgsfield-auth",
        action="store_true",
        help="Skip Higgsfield auth and Soul ID checks",
    )

    pattern_summary_parser = sub.add_parser(
        "pattern-summary", help="Summarize analyzed reference patterns"
    )
    pattern_summary_parser.add_argument("--limit", type=int, default=300)

    export_patterns_parser = sub.add_parser(
        "export-patterns", help="Export pattern cards for learning/prompt use"
    )
    export_patterns_parser.add_argument("--limit", type=int, default=300)
    export_patterns_parser.add_argument(
        "--for-campaign-factory",
        action="store_true",
        help="Also write the stable Campaign Factory handoff bank",
    )

    apply_labels = sub.add_parser(
        "apply-pattern-labels",
        help="Write machine-suggested gold/maybe/ignore labels into review labels",
    )
    apply_labels.add_argument("--limit", type=int, default=300)
    apply_labels.add_argument("--overwrite", action="store_true")

    learning_system = sub.add_parser(
        "build-learning-system",
        help="Build clusters, playbook, prompt pack, and campaign reference bank",
    )
    learning_system.add_argument("--limit", type=int, default=300)
    learning_system.add_argument("--refresh-patterns", action="store_true")
    learning_system.add_argument(
        "--embedding-clusters", action=argparse.BooleanOptionalAction, default=True
    )
    learning_system.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    learning_system.add_argument(
        "--embedding-threshold", type=float, default=DEFAULT_EMBEDDING_THRESHOLD
    )

    learning_summary_parser = sub.add_parser(
        "learning-summary",
        help="Summarize the current learning clusters from reference patterns",
    )
    learning_summary_parser.add_argument("--limit", type=int, default=300)

    queue_analysis = sub.add_parser(
        "queue-reference-analysis",
        help="Queue local TikTok/Reels downloads for Gemini or VLM analysis",
    )
    queue_analysis.add_argument("--source", required=True)
    queue_analysis.add_argument("--platform", default="unknown")
    queue_analysis.add_argument("--provider-target", default="gemini")
    queue_analysis.add_argument("--account-profile", default=None)
    queue_analysis.add_argument("--intake-profile", default="ig_ofm")
    queue_analysis.add_argument(
        "--prompt-style", choices=["guided", "minimal"], default="guided"
    )
    queue_analysis.add_argument(
        "--media-kinds",
        default="video,image",
        help="Comma-separated media kinds to queue: video,image",
    )
    queue_analysis.add_argument("--limit", type=int, default=None)
    queue_analysis.add_argument("--creative-plan-id", default=None)

    export_analysis = sub.add_parser(
        "export-reference-analysis-queue",
        help="Export pending reference-analysis prompts",
    )
    export_analysis.add_argument("--provider-target", default="gemini")
    export_analysis.add_argument("--limit", type=int, default=50)

    local_analysis = sub.add_parser(
        "analyze-reference-local",
        help="Run deterministic local preprocessing for reference videos",
    )
    local_analysis.add_argument("--input", "--source", dest="source", required=True)
    local_analysis.add_argument("--platform", default="instagram")
    local_analysis.add_argument("--intake-profile", default="ig_ofm")
    local_analysis.add_argument("--media-kinds", default="video")
    local_analysis.add_argument("--limit", type=int, default=None)
    local_analysis.add_argument("--ffprobe", default="ffprobe")
    local_analysis.add_argument("--ffmpeg", default="ffmpeg")
    local_analysis.add_argument("--creative-plan-id", default=None)

    export_video_analysis = sub.add_parser(
        "export-video-analyses", help="Export local/Gemini video analysis records"
    )
    export_video_analysis.add_argument("--provider", default=None)
    export_video_analysis.add_argument("--limit", type=int, default=100)

    import_analysis = sub.add_parser(
        "import-reference-analysis",
        help="Import Gemini/VLM JSON analysis for queued references",
    )
    import_analysis.add_argument("--input", required=True)

    import_gemini_app = sub.add_parser(
        "import-gemini-app-response",
        help="Import the copied Gemini app/Chrome JSON response for an exported queue job",
    )
    import_gemini_app.add_argument(
        "--queue", required=True, help="Exported Gemini analysis queue JSON"
    )
    import_gemini_app.add_argument(
        "--response",
        default=None,
        help="Optional response JSON/text path; defaults to macOS clipboard",
    )
    import_gemini_app.add_argument(
        "--job-index", type=int, default=1, help="1-based job index in the queue"
    )
    import_gemini_app.add_argument("--model-profile", default=None)
    import_gemini_app.add_argument(
        "--generate-prompts", action=argparse.BooleanOptionalAction, default=True
    )

    generate_prompts = sub.add_parser(
        "generate-video-prompts",
        help="Generate Higgsfield/Kling prompt drafts from reference analysis",
    )
    generate_prompts.add_argument("--tools", default="higgsfield_soul,kling_3")
    generate_prompts.add_argument("--model-profile", default=None)
    generate_prompts.add_argument("--limit", type=int, default=50)
    generate_prompts.add_argument(
        "--include-pending", action=argparse.BooleanOptionalAction, default=True
    )
    generate_prompts.add_argument("--creative-plan-id", default=None)

    export_prompts = sub.add_parser(
        "export-video-prompts", help="Export generated AI video prompt drafts"
    )
    export_prompts.add_argument("--limit", type=int, default=100)
    export_prompts.add_argument("--creative-plan-id", default=None)

    higgsfield = sub.add_parser(
        "generate-with-higgsfield",
        help="Generate Higgsfield Soul images and Kling 3.0 videos from daily prompt exports",
    )
    higgsfield.add_argument(
        "--data-root",
        default=argparse.SUPPRESS,
        help="Derived data root; accepted here for command-local ergonomics",
    )
    higgsfield.add_argument("--limit", type=int, default=1)
    higgsfield.add_argument(
        "--reference-id",
        default=None,
        help="Generate only the prompt pair for this source reference id",
    )
    higgsfield.add_argument("--soul-id", default="Stacey")
    higgsfield.add_argument("--kling-mode", default="std", choices=["std", "pro", "4k"])
    higgsfield.add_argument("--wait", action="store_true")
    higgsfield.add_argument("--dry-run", action="store_true")
    higgsfield.add_argument("--max-credits", type=float, default=8.0)
    higgsfield.add_argument(
        "--min-prompt-score",
        type=int,
        default=72,
        help="Block Higgsfield generation below this prompt quality score; use 0 to disable",
    )
    higgsfield.add_argument("--image-candidates", type=int, default=1)
    higgsfield.add_argument("--variation-grid", action="store_true")
    higgsfield.add_argument("--variation-model", default="grok_image")
    higgsfield.add_argument("--variation-layout", default="2x3", choices=["2x3", "3x3"])
    higgsfield.add_argument(
        "--variation-strategy",
        default="individual",
        choices=["individual", "grid", "soul_grid"],
    )
    higgsfield.add_argument(
        "--animate-variation-panels",
        action="store_true",
        help="Animate each individual 2x3/3x3 panel with Kling before assembling a video grid",
    )
    higgsfield.add_argument(
        "--variation-panel-dir",
        default=None,
        help="Reuse an existing ordered panel image folder instead of regenerating variation stills",
    )
    higgsfield.add_argument("--selected-image", default=None)
    higgsfield.add_argument("--no-video", action="store_true")
    higgsfield.add_argument("--no-campaign-intake", action="store_true")
    higgsfield.add_argument("--campaign-factory-root", default=None)
    higgsfield.add_argument("--campaign", default=None)
    higgsfield.add_argument("--model", default=None)
    higgsfield.add_argument("--creative-plan", default=None)

    daily_generation = sub.add_parser(
        "run-daily-generation",
        help="Generate a daily Higgsfield/Kling batch and intake finished videos into Campaign Factory",
    )
    daily_generation.add_argument(
        "--data-root",
        default=argparse.SUPPRESS,
        help="Derived data root; accepted here for command-local ergonomics",
    )
    daily_generation.add_argument("--creative-plan", required=True)
    daily_generation.add_argument("--limit", type=int, default=10)
    daily_generation.add_argument("--campaign", required=True)
    daily_generation.add_argument("--model", required=True)
    daily_generation.add_argument("--campaign-factory-root", required=True)
    daily_generation.add_argument("--soul-id", default="Stacey")
    daily_generation.add_argument(
        "--kling-mode", default="std", choices=["std", "pro", "4k"]
    )
    daily_generation.add_argument("--wait", action="store_true")
    daily_generation.add_argument("--dry-run", action="store_true")
    daily_generation.add_argument("--max-credits", type=float, default=80.0)

    verify_proof = sub.add_parser(
        "verify-proof-bundle",
        help="Verify an accepted A-to-Z proof bundle with ffprobe and lineage checks",
    )
    verify_proof.add_argument(
        "--bundle", required=True, help="Accepted proof bundle folder"
    )

    gemini_api = sub.add_parser(
        "analyze-reference-with-gemini-api",
        help="Use the official Gemini API to analyze queued local reference videos",
    )
    gemini_api.add_argument("--source", required=True)
    gemini_api.add_argument("--platform", default="instagram")
    gemini_api.add_argument("--account-profile", default=None)
    gemini_api.add_argument("--intake-profile", default="ig_ofm")
    gemini_api.add_argument("--media-kinds", default="video")
    gemini_api.add_argument("--limit", type=int, default=1)
    gemini_api.add_argument("--model", default="gemini-2.5-flash")
    gemini_api.add_argument("--api-key", default=None)
    gemini_api.add_argument(
        "--prompt-style", choices=["guided", "minimal"], default="minimal"
    )

    grok_api = sub.add_parser(
        "analyze-reference-with-grok-api",
        help="Use xAI/Grok vision to draft ImageAt-style JSON prompts from local references",
    )
    grok_api.add_argument("--source", required=True)
    grok_api.add_argument("--platform", default="instagram")
    grok_api.add_argument("--account-profile", default=None)
    grok_api.add_argument("--intake-profile", default="ig_ofm")
    grok_api.add_argument("--media-kinds", default="video,image")
    grok_api.add_argument("--limit", type=int, default=1)
    grok_api.add_argument("--model", default="grok-4")
    grok_api.add_argument("--api-key", default=None)
    grok_api.add_argument("--prompt-style", default="imageat")
    grok_api.add_argument("--ffmpeg", default="ffmpeg")

    grok_compile = sub.add_parser(
        "compile-prompts-with-grok-api",
        help="Use xAI/Grok vision to compile final clean Higgsfield/Kling prose prompts",
    )
    grok_compile.add_argument("--reference-id", required=True)
    grok_compile.add_argument("--reference-media", required=True)
    grok_compile.add_argument("--model", default="grok-4")
    grok_compile.add_argument("--api-key", default=None)
    grok_compile.add_argument("--ffmpeg", default="ffmpeg")
    grok_compile.add_argument("--instructions", default=None)

    server = sub.add_parser("review-server", help="Run local review UI")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db).expanduser()
    data_root = Path(args.data_root or DEFAULT_DATA_ROOT).expanduser()
    ensure_data_dirs(data_root)
    conn = connect(db_path)
    try:
        if args.command == "scan":
            print_json(scan_source(conn, Path(args.source)))
        elif args.command == "probe":
            print_json(probe_videos(conn, parse_limit(args.limit)))
        elif args.command == "sample-frames":
            print_json(sample_frames(conn, data_root, parse_limit(args.limit)))
        elif args.command == "thumbnail-batch":
            print_json(thumbnail_batch(conn, data_root, parse_limit(args.limit)))
        elif args.command == "ocr":
            print_json(
                run_ocr(
                    conn,
                    engine=args.engine,
                    likely_captioned_only=args.likely_captioned_only,
                    limit=parse_limit(args.limit),
                )
            )
        elif args.command == "ocr-cleanup":
            print_json(ocr_cleanup(conn))
        elif args.command == "contact-sheet":
            print_json(
                generate_contact_sheet(
                    conn,
                    mode=args.mode,
                    count=args.count,
                    per_account=args.per_account,
                    data_root=data_root,
                )
            )
        elif args.command == "shortlist":
            print_json(build_shortlist(conn, args.target))
        elif args.command == "review-batch":
            print_json(
                review_batch(
                    conn,
                    target=args.target,
                    mode=args.mode,
                    account_cap=args.account_cap,
                )
            )
        elif args.command == "label":
            tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
            print_json(
                label_reference(conn, args.reference_id, args.label, tags, args.notes)
            )
        elif args.command == "export-gold":
            print_json(export_gold(conn, data_root))
        elif args.command == "adapt-captions":
            profile_path = Path(args.profile).expanduser() if args.profile else None
            if args.init_profile:
                print_json(
                    {
                        "schema": "reference_factory.caption_adaptation_profile_init.v1",
                        "profilePath": str(ensure_default_profile(data_root)),
                    }
                )
            else:
                print_json(
                    adapt_caption_library(
                        data_root=data_root,
                        profile_path=profile_path,
                        input_path=Path(args.input).expanduser()
                        if args.input
                        else None,
                    )
                )
        elif args.command == "import-apify-metrics":
            print_json(
                import_apify_metrics(
                    conn,
                    input_paths=[Path(path).expanduser() for path in args.input],
                    top_limit=args.top_limit,
                    output_dir=data_root / "apify",
                )
            )
        elif args.command == "import-tiktok-archive":
            print_json(
                import_tiktok_archive(
                    conn,
                    Path(args.source),
                    top_limit=args.top_limit,
                    treat_as_slideshow=args.as_slideshow,
                    output_dir=data_root / "tiktok",
                )
            )
        elif args.command == "top-public-posts":
            print_json(top_public_posts(conn, args.limit))
        elif args.command == "generate-prompt-cards":
            print_json(generate_prompt_cards(conn, args.limit, data_root / "apify"))
        elif args.command == "export-learning-set":
            print_json(
                export_learning_set(
                    conn, args.limit, data_root / "learning", copy_media=args.copy_media
                )
            )
        elif args.command == "analyze-patterns":
            print_json(
                analyze_patterns(
                    conn,
                    limit=args.limit,
                    provider=args.provider,
                    ollama_model=args.ollama_model,
                    output_dir=data_root / "learning",
                )
            )
        elif args.command == "import-prompt-outcomes":
            print_json(
                import_prompt_outcomes_file(
                    conn,
                    [Path(path).expanduser() for path in args.input],
                )
            )
        elif args.command == "analyze-audio-patterns":
            print_json(
                analyze_audio_patterns(
                    conn, limit=args.limit, output_dir=data_root / "learning"
                )
            )
        elif args.command == "competitor-audio":
            print_json(
                competitor_audio_leaderboard(
                    conn,
                    platform=args.platform,
                    accounts=[
                        item.strip()
                        for item in args.accounts.split(",")
                        if item.strip()
                    ],
                    caption_keywords=[
                        item.strip()
                        for item in args.caption_keywords.split(",")
                        if item.strip()
                    ],
                    min_plays=args.min_plays,
                    min_posts=args.min_posts,
                    limit=args.limit,
                    output_path=Path(args.export).expanduser() if args.export else None,
                )
            )
        elif args.command == "import-audio-csv":
            print_json(import_audio_csv(conn, Path(args.input)))
        elif args.command == "import-example-reel-audio":
            print_json(
                import_example_reel_audio(
                    conn,
                    Path(args.input) if args.input else None,
                    limit=args.limit,
                    export_path=Path(args.export) if args.export else None,
                    preserve_manual_fields=args.preserve_manual_fields,
                )
            )
        elif args.command == "scrape-instagram-audio":
            print_json(
                scrape_instagram_audio(
                    conn,
                    urls=args.url,
                    input_path=Path(args.input) if args.input else None,
                    limit=args.limit,
                    export_path=Path(args.export) if args.export else None,
                )
            )
        elif args.command == "list-audio":
            if args.export:
                print_json(export_audio_catalog(conn, Path(args.export)))
            elif args.needs_review:
                print_json(
                    review_audio_catalog(conn, platform=args.platform, limit=args.limit)
                )
            else:
                print_json(
                    list_audio_catalog(
                        conn,
                        platform=args.platform,
                        fresh_only=args.fresh_only,
                        limit=args.limit,
                    )
                )
        elif args.command == "recommend-audio":
            print_json(
                recommend_audio(
                    conn,
                    platform=args.platform,
                    content_tags=[
                        tag.strip()
                        for tag in args.content_tags.split(",")
                        if tag.strip()
                    ],
                    account_tags=[
                        tag.strip()
                        for tag in args.account_tags.split(",")
                        if tag.strip()
                    ],
                    limit=args.limit,
                )
            )
        elif args.command == "refresh-tiktok-audio":
            print_json(
                refresh_tiktok_audio(
                    conn,
                    source_root=Path(args.source),
                    data_root=data_root,
                    top_limit=args.top_limit,
                    catalog_limit=args.catalog_limit,
                    recommend_limit=args.recommend_limit,
                    content_tags=[
                        tag.strip()
                        for tag in args.content_tags.split(",")
                        if tag.strip()
                    ],
                    account_tags=[
                        tag.strip()
                        for tag in args.account_tags.split(",")
                        if tag.strip()
                    ],
                    preserve_manual_fields=args.preserve_manual_fields,
                )
            )
        elif args.command == "resolve-audio":
            print_json(
                resolve_audio_record(
                    conn,
                    {
                        "platform": args.platform,
                        "nativeAudioId": args.native_audio_id,
                        "title": args.title,
                        "artistName": args.artist,
                        "nativeAudioUrl": args.url,
                        "moodTags": args.mood_tags,
                        "bestContentTypes": args.content_tags,
                        "accountFit": args.account_tags,
                        "trendStatus": args.trend_status,
                        "usageCount": args.usage_count,
                        "expiresAt": args.expires_at,
                        "safeUsageNotes": args.safe_usage_notes,
                    },
                )
            )
        elif args.command == "audio-health":
            health = audio_catalog_health(
                conn, platform=args.platform, limit=args.limit
            )
            if args.export:
                path = Path(args.export).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, 
                    json.dumps(health, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                health["path"] = str(path)
            print_json(health)
        elif args.command == "audio-resolution-shortlist":
            shortlist = audio_resolution_shortlist(
                conn, platform=args.platform, limit=args.limit
            )
            if args.export:
                path = Path(args.export).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, 
                    json.dumps(shortlist, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                shortlist["path"] = str(path)
            print_json(shortlist)
        elif args.command == "import-audio-snapshot-csv":
            print_json(import_audio_snapshot_csv(conn, Path(args.input)))
        elif args.command == "add-audio-snapshot":
            print_json(
                upsert_audio_trend_snapshot(
                    conn,
                    {
                        "audioCatalogId": args.audio_catalog_id,
                        "platform": args.platform,
                        "nativeAudioId": args.native_audio_id,
                        "observedAt": args.observed_at,
                        "trendStatus": args.trend_status,
                        "usageCount": args.usage_count,
                        "saturationScore": args.saturation_score,
                        "velocityScore": args.velocity_score,
                        "curator": args.curator,
                        "source": args.source,
                        "notes": args.notes,
                    },
                )
            )
        elif args.command == "list-audio-snapshots":
            print_json(
                list_audio_trend_snapshots(
                    conn,
                    platform=args.platform,
                    audio_catalog_id=args.audio_catalog_id,
                    limit=args.limit,
                )
            )
        elif args.command == "provider-doctor":
            print_json(
                provider_doctor(
                    require_gemini=args.require_gemini,
                    check_xai=not args.skip_xai_check,
                    check_higgsfield_auth=not args.skip_higgsfield_auth,
                )
            )
        elif args.command == "pattern-summary":
            print_json(pattern_summary(conn, args.limit))
        elif args.command == "export-patterns":
            if args.for_campaign_factory:
                print_json(
                    build_learning_system(
                        conn, limit=args.limit, output_dir=data_root / "learning"
                    )
                )
            else:
                print_json(export_patterns(conn, args.limit, data_root / "learning"))
        elif args.command == "apply-pattern-labels":
            print_json(apply_pattern_labels(conn, args.limit, overwrite=args.overwrite))
        elif args.command == "build-learning-system":
            print_json(
                build_learning_system(
                    conn,
                    limit=args.limit,
                    output_dir=data_root / "learning",
                    refresh_patterns=args.refresh_patterns,
                    embedding_clusters=args.embedding_clusters,
                    embedding_model=args.embedding_model,
                    embedding_threshold=args.embedding_threshold,
                )
            )
        elif args.command == "learning-summary":
            print_json(learning_summary(conn, args.limit))
        elif args.command == "queue-reference-analysis":
            print_json(
                queue_reference_analysis(
                    conn,
                    Path(args.source),
                    data_root=data_root,
                    platform=args.platform,
                    provider_target=args.provider_target,
                    account_profile=args.account_profile,
                    intake_profile=args.intake_profile,
                    media_kinds=[
                        kind.strip()
                        for kind in args.media_kinds.split(",")
                        if kind.strip()
                    ],
                    limit=args.limit,
                    creative_plan_id=args.creative_plan_id,
                    prompt_style=args.prompt_style,
                )
            )
        elif args.command == "export-reference-analysis-queue":
            print_json(
                export_analysis_queue(
                    conn,
                    data_root=data_root,
                    provider_target=args.provider_target,
                    limit=args.limit,
                )
            )
        elif args.command == "analyze-reference-local":
            print_json(
                analyze_reference_local(
                    conn,
                    Path(args.source),
                    data_root=data_root,
                    platform=args.platform,
                    intake_profile=args.intake_profile,
                    media_kinds=[
                        kind.strip()
                        for kind in args.media_kinds.split(",")
                        if kind.strip()
                    ],
                    limit=args.limit,
                    ffprobe=args.ffprobe,
                    ffmpeg=args.ffmpeg,
                    creative_plan_id=args.creative_plan_id,
                )
            )
        elif args.command == "export-video-analyses":
            print_json(
                export_video_analyses(
                    conn, data_root=data_root, provider=args.provider, limit=args.limit
                )
            )
        elif args.command == "import-reference-analysis":
            print_json(import_reference_analysis(conn, Path(args.input)))
        elif args.command == "import-gemini-app-response":
            print_json(
                import_gemini_app_response(
                    conn,
                    queue_path=Path(args.queue),
                    response_path=Path(args.response).expanduser()
                    if args.response
                    else None,
                    data_root=data_root,
                    job_index=args.job_index,
                    generate_prompts_after_import=args.generate_prompts,
                    model_profile=args.model_profile,
                )
            )
        elif args.command == "generate-video-prompts":
            print_json(
                generate_video_prompts(
                    conn,
                    data_root=data_root,
                    target_tools=[
                        tool.strip() for tool in args.tools.split(",") if tool.strip()
                    ],
                    model_profile=args.model_profile,
                    limit=args.limit,
                    include_pending=args.include_pending,
                    creative_plan_id=args.creative_plan_id,
                )
            )
        elif args.command == "export-video-prompts":
            print_json(
                export_video_prompts(
                    conn,
                    data_root=data_root,
                    limit=args.limit,
                    creative_plan_id=args.creative_plan_id,
                )
            )
        elif args.command == "generate-with-higgsfield":
            print_json(
                generate_with_higgsfield(
                    data_root=data_root,
                    limit=args.limit,
                    reference_id=args.reference_id,
                    soul_id=args.soul_id,
                    kling_mode=args.kling_mode,
                    wait=args.wait,
                    dry_run=args.dry_run,
                    max_credits=args.max_credits,
                    min_prompt_score=None
                    if args.min_prompt_score <= 0
                    else args.min_prompt_score,
                    image_candidates=args.image_candidates,
                    variation_grid=args.variation_grid,
                    variation_model=args.variation_model,
                    variation_layout=args.variation_layout,
                    variation_strategy=args.variation_strategy,
                    animate_variation_panels=args.animate_variation_panels,
                    variation_panel_dir=Path(args.variation_panel_dir).expanduser()
                    if args.variation_panel_dir
                    else None,
                    selected_image=Path(args.selected_image).expanduser()
                    if args.selected_image
                    else None,
                    no_video=args.no_video,
                    no_campaign_intake=args.no_campaign_intake,
                    campaign_factory_root=Path(args.campaign_factory_root).expanduser()
                    if args.campaign_factory_root
                    else None,
                    campaign=args.campaign,
                    model=args.model,
                    creative_plan=args.creative_plan,
                )
            )
        elif args.command == "run-daily-generation":
            print_json(
                run_daily_generation(
                    data_root=data_root,
                    creative_plan=args.creative_plan,
                    limit=args.limit,
                    campaign=args.campaign,
                    model=args.model,
                    campaign_factory_root=Path(args.campaign_factory_root).expanduser(),
                    soul_id=args.soul_id,
                    kling_mode=args.kling_mode,
                    wait=args.wait,
                    dry_run=args.dry_run,
                    max_credits=args.max_credits,
                )
            )
        elif args.command == "verify-proof-bundle":
            print_json(verify_proof_bundle(Path(args.bundle).expanduser()))
        elif args.command == "analyze-reference-with-gemini-api":
            print_json(
                analyze_reference_with_gemini_api(
                    conn,
                    source_root=Path(args.source),
                    data_root=data_root,
                    platform=args.platform,
                    account_profile=args.account_profile,
                    intake_profile=args.intake_profile,
                    media_kinds=[
                        kind.strip()
                        for kind in args.media_kinds.split(",")
                        if kind.strip()
                    ],
                    limit=args.limit,
                    model=args.model,
                    api_key=args.api_key,
                    prompt_style=args.prompt_style,
                )
            )
        elif args.command == "analyze-reference-with-grok-api":
            print_json(
                analyze_reference_with_grok_api(
                    conn,
                    source_root=Path(args.source),
                    data_root=data_root,
                    platform=args.platform,
                    account_profile=args.account_profile,
                    intake_profile=args.intake_profile,
                    media_kinds=[
                        kind.strip()
                        for kind in args.media_kinds.split(",")
                        if kind.strip()
                    ],
                    limit=args.limit,
                    model=args.model,
                    api_key=args.api_key,
                    prompt_style=args.prompt_style,
                    ffmpeg=args.ffmpeg,
                )
            )
        elif args.command == "compile-prompts-with-grok-api":
            print_json(
                compile_prompts_with_grok_api(
                    data_root=data_root,
                    reference_id=args.reference_id,
                    reference_media=Path(args.reference_media).expanduser(),
                    model=args.model,
                    api_key=args.api_key,
                    ffmpeg=args.ffmpeg,
                    instructions=args.instructions,
                )
            )
        elif args.command == "review-server":
            from .server import run_server

            conn.close()
            run_server(args.host, args.port, db_path)
            return 0
        else:
            parser.error(f"Unknown command: {args.command}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
