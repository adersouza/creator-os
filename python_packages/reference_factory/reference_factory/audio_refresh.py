from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .audio import (
    audio_catalog_health,
    competitor_audio_leaderboard,
    import_audio_csv,
    recommend_audio,
)
from .tiktok_archive import import_tiktok_archive

CATALOG_FIELDS = [
    "title",
    "artist",
    "platform",
    "native_audio_id",
    "native_audio_url",
    "mood_tags",
    "best_content_types",
    "account_fit",
    "bpm",
    "energy",
    "vocality",
    "danceability",
    "valence",
    "trend_status",
    "usage_count",
    "safe_usage_notes",
    "date_discovered",
    "expires_at",
    "example_reels",
    "raw_json",
]


def refresh_tiktok_audio(
    conn: Connection,
    *,
    source_root: Path,
    data_root: Path,
    top_limit: int = 500,
    catalog_limit: int = 80,
    recommend_limit: int = 10,
    content_tags: list[str] | None = None,
    account_tags: list[str] | None = None,
    preserve_manual_fields: bool = True,
) -> dict[str, object]:
    learning_dir = data_root / "learning"
    learning_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = {
        str(row["native_audio_id"])
        for row in conn.execute(
            "SELECT native_audio_id FROM audio_catalog WHERE platform = 'tiktok' AND native_audio_id IS NOT NULL"
        )
        if row["native_audio_id"]
    }

    imported = import_tiktok_archive(
        conn,
        source_root,
        top_limit=top_limit,
        treat_as_slideshow=True,
        output_dir=data_root / "tiktok",
    )
    leaderboard_path = learning_dir / "tiktok_audio_from_latest_downloads.json"
    leaderboard = competitor_audio_leaderboard(
        conn,
        platform="tiktok",
        min_posts=1,
        limit=catalog_limit,
        output_path=leaderboard_path,
    )
    catalog_path = learning_dir / "audio_catalog_from_latest_tiktok_downloads.csv"
    catalog_rows = leaderboard_to_catalog_rows(leaderboard, limit=catalog_limit)
    write_audio_catalog_csv(catalog_rows, catalog_path)
    new_audio_ids = [
        row["native_audio_id"]
        for row in catalog_rows
        if row.get("native_audio_id") and row["native_audio_id"] not in existing_ids
    ]
    catalog_import = import_audio_csv(
        conn, catalog_path, preserve_manual_fields=preserve_manual_fields
    )
    recommendations = recommend_audio(
        conn,
        platform="tiktok",
        content_tags=content_tags or ["ai_ofm", "slideshow", "glowup"],
        account_tags=account_tags or [],
        limit=recommend_limit,
    )
    health = audio_catalog_health(conn, platform="tiktok", limit=10)
    summary = {
        "schema": "reference_factory.refresh_tiktok_audio.v1",
        "sourceRoot": str(Path(source_root).expanduser()),
        "videosImported": imported.get("videosImported"),
        "authors": imported.get("authors"),
        "topAccounts": imported.get("topAccounts") or [],
        "leaderboardCount": leaderboard.get("count"),
        "sourcePostsConsidered": leaderboard.get("sourcePostsConsidered"),
        "catalogCsvPath": str(catalog_path),
        "leaderboardPath": str(leaderboard_path),
        "catalogImported": catalog_import.get("imported"),
        "catalogErrors": catalog_import.get("errors") or [],
        "preserveManualFields": preserve_manual_fields,
        "newAudioCount": len(new_audio_ids),
        "newAudioIds": new_audio_ids[:20],
        "unresolvedTitleCount": health.get("unresolvedTitles"),
        "staleCount": health.get("stale"),
        "freshCount": health.get("fresh"),
        "readyCount": health.get("ready"),
        "catalogHealth": health,
        "recommendations": recommendations.get("recommendations") or [],
    }
    summary_path = learning_dir / "tiktok_audio_latest_downloads_summary.json"
    summary["summaryPath"] = str(summary_path)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def leaderboard_to_catalog_rows(
    payload: dict[str, Any], *, limit: int | None = None
) -> list[dict[str, str]]:
    now = datetime.now(UTC)
    expires = (now + timedelta(days=10)).isoformat()
    rows: list[dict[str, str]] = []
    items = payload.get("items") or []
    for item in items[: limit or len(items)]:
        examples = item.get("examples") or []
        example_urls = [
            str(example.get("url")) for example in examples if example.get("url")
        ]
        captions = " | ".join(
            str(example.get("caption") or "").strip()
            for example in examples[:3]
            if str(example.get("caption") or "").strip()
        )
        accounts = [str(account) for account in (item.get("accounts") or []) if account]
        tags = _catalog_tags(item, captions)
        usage_count = int(item.get("totalPlays") or item.get("medianPlays") or 0)
        rows.append(
            {
                "title": str(
                    item.get("audioTitle") or f"TikTok audio {item.get('audioId')}"
                ),
                "artist": str(
                    item.get("artistName") or (accounts[0] if accounts else "")
                ),
                "platform": "tiktok",
                "native_audio_id": str(item.get("audioId") or ""),
                "native_audio_url": example_urls[0] if example_urls else "",
                "mood_tags": "|".join(sorted(tags)),
                "best_content_types": "slideshow|ai_ofm|reel|captioned_reference",
                "account_fit": "|".join(accounts),
                "bpm": "",
                "energy": "8"
                if {"dance", "high_energy"} & tags or usage_count >= 100000
                else "6",
                "vocality": "unknown",
                "danceability": "",
                "valence": "",
                "trend_status": _trend_status_for_usage(usage_count),
                "usage_count": str(usage_count),
                "safe_usage_notes": "Reference only. Attach natively in TikTok; do not burn licensed audio into rendered file.",
                "date_discovered": now.isoformat(),
                "expires_at": expires,
                "example_reels": "|".join(example_urls[:5]),
                "raw_json": json.dumps(
                    {
                        "source": "reference_factory.competitor_audio_leaderboard",
                        "score": item.get("score"),
                        "postCount": item.get("postCount"),
                        "captions": captions,
                        "examples": examples[:5],
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return rows


def write_audio_catalog_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _catalog_tags(item: dict[str, Any], captions: str) -> set[str]:
    tags = {"ai_ofm", "slideshow", "similar_creator", "tiktok_reference"}
    vibe = item.get("audioVibe")
    if vibe:
        tags.add(str(vibe))
    caption_text = captions.lower()
    if any(
        word in caption_text
        for word in ["glowup", "different", "resemblance", "transformation", "before"]
    ):
        tags.update(["glowup", "transformation"])
    if any(word in caption_text for word in ["dancer", "dance", "cardio", "strut"]):
        tags.update(["dance", "high_energy"])
    if any(
        word in caption_text for word in ["older men", "date", "single", "boy", "men"]
    ):
        tags.update(["dating", "relationship"])
    return tags


def _trend_status_for_usage(usage_count: int) -> str:
    if usage_count >= 100000:
        return "rising"
    if usage_count >= 10000:
        return "fresh"
    return "unknown"
