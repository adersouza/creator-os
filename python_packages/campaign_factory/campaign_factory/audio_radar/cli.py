"""Audio Radar discovery and provider-free local embedding commands."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text
from creator_os_core.sqlite import connect_sqlite

from ..audio_policy import build_embedded_trending_audio_intent
from ..db import connect
from .acquisition import AudioCache
from .binding import bind_embedding_receipt
from .embedding import EmbeddingSettings
from .models import AudioLocator, PlatformSoundId, TrendCandidate
from .normalization import normalize_candidates
from .pipeline import fulfill_embedded_trending
from .providers import SocialCrawlInstagramProvider, TokchartTrendProvider
from .ranking import AudioMatchContext, rank_candidates
from .refresh import RefreshPaths, refresh_audio_library


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    discover = commands.add_parser("discover")
    discover.add_argument(
        "--provider",
        required=True,
        choices=["socialcrawl-instagram", "tokchart-tiktok"],
    )
    discover.add_argument("--region")
    discover.add_argument("--limit", type=int, default=25)

    refresh = commands.add_parser("refresh")
    refresh.add_argument("--region", default="US")
    refresh.add_argument("--max-new", type=int, default=20)
    refresh.add_argument("--max-active", type=int, default=75)
    refresh_mode = refresh.add_mutually_exclusive_group(required=True)
    refresh_mode.add_argument("--dry-run", action="store_true")
    refresh_mode.add_argument("--apply", action="store_true")
    refresh.add_argument("--database", type=Path)
    refresh.add_argument("--cache-dir", type=Path)
    refresh.add_argument("--receipts-dir", type=Path)
    refresh.add_argument("--lock-file", type=Path)

    bind = commands.add_parser("bind-receipt")
    bind.add_argument("--database", type=Path, required=True)
    bind.add_argument("--rendered-asset-id", required=True)
    bind.add_argument("--receipt", type=Path, required=True)

    explain = commands.add_parser("explain")
    explain.add_argument("--final-sha", required=True)
    explain.add_argument("--database", type=Path)

    embed = commands.add_parser("embed-local")
    embed.add_argument("--video", type=Path, required=True)
    embed.add_argument("--audio", type=Path, required=True)
    embed.add_argument("--output", type=Path, required=True)
    embed.add_argument("--cache-dir", type=Path, required=True)
    embed.add_argument("--receipt", type=Path, required=True)
    embed.add_argument("--track-id", required=True)
    embed.add_argument("--track-name", required=True)
    embed.add_argument("--artist", required=True)
    embed.add_argument("--provider", default="operator_local_file")
    embed.add_argument("--platform", default="local")
    embed.add_argument("--creator", required=True)
    embed.add_argument("--account", required=True)
    embed.add_argument("--visual-tag", action="append", default=[])
    embed.add_argument("--motion-tag", action="append", default=[])
    embed.add_argument("--caption-tag", action="append", default=[])
    embed.add_argument("--speaking", action="store_true")
    embed.add_argument("--volume", type=float, default=0.82)
    embed.add_argument("--preferred-offset", type=float, action="append", default=[])
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "discover":
        provider = (
            SocialCrawlInstagramProvider()
            if args.provider == "socialcrawl-instagram"
            else TokchartTrendProvider()
        )
        candidates = normalize_candidates(
            provider.discover(region=args.region, limit=args.limit)
        )
        return {
            "schema": "creator_os.audio_radar_discovery.v1",
            "provider": provider.provider_name,
            "candidates": [value.as_dict() for value in candidates],
        }
    if args.command == "refresh":
        defaults = RefreshPaths.defaults()
        return refresh_audio_library(
            region=args.region,
            max_new=args.max_new,
            max_active=args.max_active,
            apply=args.apply,
            paths=RefreshPaths(
                database=(args.database or defaults.database).expanduser().resolve(),
                cache=(args.cache_dir or defaults.cache).expanduser().resolve(),
                receipts=(args.receipts_dir or defaults.receipts)
                .expanduser()
                .resolve(),
                lock=(args.lock_file or defaults.lock).expanduser().resolve(),
            ),
        )
    if args.command == "bind-receipt":
        raw_database = args.database.expanduser()
        raw_receipt = args.receipt.expanduser()
        if raw_database.is_symlink():
            raise ValueError("Campaign Factory database is missing or unsafe")
        if raw_receipt.is_symlink():
            raise ValueError("embedding receipt is missing or unsafe")
        database = raw_database.resolve()
        receipt_path = raw_receipt.resolve()
        if not database.is_file():
            raise ValueError("Campaign Factory database is missing or unsafe")
        if not receipt_path.is_file():
            raise ValueError("embedding receipt is missing or unsafe")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("embedding receipt must be a JSON object")
        with connect(database) as conn:
            return bind_embedding_receipt(
                conn,
                rendered_asset_id=args.rendered_asset_id,
                embedding_receipt=receipt,
                bound_at=_now(),
            )
    if args.command == "explain":
        database = (args.database or RefreshPaths.defaults().database).expanduser()
        return _explain_audio(database, args.final_sha)

    now = _now()
    candidate = TrendCandidate(
        candidate_id=f"{args.provider}:{args.platform}:{args.track_id}",
        provider=args.provider,
        title=args.track_name,
        artist=args.artist,
        platform_sound_ids=(
            PlatformSoundId(
                platform=args.platform,
                sound_id=args.track_id,
            ),
        ),
        observed_at=now,
        current_rank=1,
        usage_velocity=1,
        freshness_hours=0,
        mood_tags=tuple(
            dict.fromkeys((*args.visual_tag, *args.motion_tag, *args.caption_tag))
        ),
        locator=AudioLocator(
            provider=args.provider,
            platform=args.platform,
            track_id=args.track_id,
            kind="local_file",
            value=str(args.audio),
        ),
        advisory_labels={
            "source": "operator_supplied_local_file",
            "preferred_offsets_seconds": args.preferred_offset,
        },
    )
    normalized = normalize_candidates([candidate])
    context = AudioMatchContext(
        creator=args.creator,
        account=args.account,
        visual_tags=tuple(args.visual_tag),
        motion_tags=tuple(args.motion_tag),
        caption_tags=tuple(args.caption_tag),
        speaking=args.speaking,
        advisory_labels={"source": "operator"},
    )
    ranked = rank_candidates(normalized, context)
    result = fulfill_embedded_trending(
        video_path=args.video,
        ranked_candidates=ranked,
        cache=AudioCache(args.cache_dir),
        output_path=args.output,
        retrieved_at=now,
        settings=EmbeddingSettings(volume=args.volume),
        speaking=args.speaking,
        max_candidates=1,
    )
    receipt = result.embedding_receipt
    receipt["creativeContext"] = {
        "creator": args.creator,
        "account": args.account,
        "visualTags": args.visual_tag,
        "motionTags": args.motion_tag,
        "captionTags": args.caption_tag,
        "speaking": args.speaking,
    }
    receipt["audioIntent"] = build_embedded_trending_audio_intent(
        receipt,
        selected_at=now,
    )
    atomic_write_text(
        args.receipt,
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "schema": "creator_os.audio_radar_local_proof.v1",
        "output": str(args.output.resolve()),
        "receipt": str(args.receipt.resolve()),
        "finalVideoSha256": receipt["finalVideo"]["sha256"],
        "audioFingerprint": receipt["finalVideo"]["audioFingerprint"],
        "verification": receipt["verification"],
    }


def _explain_audio(database: Path, final_sha: str) -> dict[str, Any]:
    digest = str(final_sha or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("--final-sha must be a lowercase SHA-256")
    if database.is_symlink() or not database.resolve().is_file():
        raise ValueError("Campaign Factory database is missing or unsafe")
    conn = connect_sqlite(database, readonly=True, wal=False)
    try:
        assets = conn.execute(
            """
            SELECT id, campaign_id, content_hash, output_path, audit_status,
                   review_state, metadata_json, updated_at
            FROM rendered_assets
            WHERE lower(content_hash) = ?
            ORDER BY updated_at DESC, id
            """,
            (digest,),
        ).fetchall()
        if not assets:
            raise ValueError(f"no rendered asset found for final SHA: {digest}")
        matches = []
        for asset in assets:
            metadata = _json_object(asset["metadata_json"])
            receipt = _json_object(metadata.get("audioEmbeddingReceipt"))
            selection = _json_object(receipt.get("selection"))
            labels = _json_object(selection.get("advisoryLabels"))
            selected_track = _json_object(receipt.get("selectedTrack"))
            final_video = _json_object(receipt.get("finalVideo"))
            intent = _json_object(receipt.get("audioIntent"))
            lineage = _json_object(intent.get("lineage"))
            approval = conn.execute(
                """
                SELECT id, decision, notes, created_at
                FROM approval_decisions
                WHERE rendered_asset_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (asset["id"],),
            ).fetchone()
            publications = conn.execute(
                """
                SELECT DISTINCT post_id, platform, status, account_id,
                       instagram_account_id, permalink, published_at
                FROM performance_snapshots
                WHERE rendered_asset_id = ? OR lower(content_hash) = ?
                ORDER BY published_at DESC, post_id
                """,
                (asset["id"], digest),
            ).fetchall()
            matches.append(
                {
                    "renderedAssetId": asset["id"],
                    "campaignId": asset["campaign_id"],
                    "outputPath": asset["output_path"],
                    "track": {
                        "canonicalTrackId": selection.get("canonicalTrackId"),
                        "title": selection.get("canonicalTitle"),
                        "artists": selection.get("canonicalArtists"),
                        "platformSoundIds": selection.get("platformSoundIds"),
                        "provider": selected_track.get("provider"),
                    },
                    "cachedAudioSha256": selected_track.get("acquiredAudioSha256"),
                    "selectedSegment": receipt.get("selectedSegment"),
                    "finalAudioFingerprint": final_video.get("audioFingerprint"),
                    "embeddingReceiptSha256": lineage.get("embeddingReceiptSha256"),
                    "cooldownEvidence": {
                        key: labels.get(key)
                        for key in (
                            "accountTrackCooldownDays",
                            "absoluteMinimumGapHours",
                            "creatorSegmentCooldownDays",
                            "excludedSegmentOffsetsSeconds",
                            "cooldownOverrideApplied",
                        )
                        if labels.get(key) is not None
                    },
                    "rankingExplanation": {
                        "trendScore": labels.get("trendScore"),
                        "performanceAdjustment": labels.get("performanceAdjustment"),
                        "fitScore": labels.get("fitScore"),
                        "fatiguePenalty": labels.get("fatiguePenalty"),
                        "overrideApplied": labels.get("cooldownOverrideApplied"),
                        "finalRank": selection.get("trendRank"),
                        "rankedScore": selection.get("rankedScore"),
                        "bucket": selection.get("bucket"),
                        "selectedReason": selection.get("selectedReason"),
                    },
                    "rights": intent.get("rights"),
                    "approval": {
                        "auditStatus": asset["audit_status"],
                        "reviewState": asset["review_state"],
                        "latestDecision": dict(approval) if approval else None,
                    },
                    "publicationLinkage": [dict(row) for row in publications],
                }
            )
        return {
            "schema": "creator_os.audio_explanation.v1",
            "finalMediaSha256": digest,
            "matches": matches,
        }
    finally:
        conn.close()


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def main() -> int:
    result = run(build_parser().parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
