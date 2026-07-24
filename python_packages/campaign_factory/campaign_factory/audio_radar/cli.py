"""Audio Radar discovery and provider-free local embedding commands."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from ..audio_policy import build_embedded_trending_audio_intent
from .acquisition import AudioCache
from .binding import bind_embedding_receipt
from .embedding import EmbeddingSettings
from .models import AudioLocator, PlatformSoundId, TrendCandidate
from .normalization import normalize_candidates
from .pipeline import fulfill_embedded_trending
from .providers import SocialCrawlInstagramProvider, TokchartTrendProvider
from .ranking import AudioMatchContext, rank_candidates


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

    bind = commands.add_parser("bind-receipt")
    bind.add_argument("--database", type=Path, required=True)
    bind.add_argument("--rendered-asset-id", required=True)
    bind.add_argument("--receipt", type=Path, required=True)

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
    if args.command == "bind-receipt":
        database = args.database.expanduser().resolve()
        receipt_path = args.receipt.expanduser().resolve()
        if database.is_symlink() or not database.is_file():
            raise ValueError("Campaign Factory database is missing or unsafe")
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("embedding receipt is missing or unsafe")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("embedding receipt must be a JSON object")
        with sqlite3.connect(database) as conn:
            return bind_embedding_receipt(
                conn,
                rendered_asset_id=args.rendered_asset_id,
                embedding_receipt=receipt,
                bound_at=_now(),
            )

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


def main() -> int:
    result = run(build_parser().parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
