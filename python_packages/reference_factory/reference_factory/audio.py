from __future__ import annotations

import csv
import html as html_lib
import json
import re
import statistics
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .db import json_dump, json_load
from .fileops import atomic_write_text
from .identity import stable_id
from .timeutil import now_iso

FRESH_TREND_STATUSES = {"rising", "fresh", "current", "trending", "unknown"}
STALE_TREND_STATUSES = {"peaked", "fading", "stale", "expired"}


def analyze_audio_patterns(
    conn: Connection,
    limit: int = 300,
    output_dir: Path | None = None,
) -> dict[str, object]:
    rows = _audio_source_rows(conn, limit)
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    for row in rows:
        raw_json = json_load(row["raw_json"], {})
        signal = extract_audio_signal(raw_json, row["product_type"])
        if not signal:
            continue
        visual = row["visual_format"] or "unknown_visual"
        hook = row["hook_type"] or "unknown_hook"
        caption = row["caption_archetype"] or "unknown_caption"
        groups[(signal["platform"], signal["audioId"], visual, hook, caption)].append(
            {
                "signal": signal,
                "rank": row["rank"],
                "publicPostId": row["id"],
                "account": row["owner_username"],
                "url": row["url"],
                "caption": row["caption"],
                "plays": int(row["video_play_count"] or row["video_view_count"] or 0),
                "likes": int(row["likes_count"] or 0),
                "visualFormat": visual,
                "hookType": hook,
                "captionArchetype": caption,
            }
        )
    timestamp = now_iso()
    patterns = [
        _audio_group_to_pattern(key, items, timestamp) for key, items in groups.items()
    ]
    patterns.sort(
        key=lambda item: (
            -int(item["totalPlays"]),
            -int(item["postCount"]),
            item["audioTitle"] or "",
        )
    )
    conn.execute("DELETE FROM audio_patterns")
    for pattern in patterns:
        conn.execute(
            """
            INSERT INTO audio_patterns (
              id, platform, audio_id, audio_title, artist_name, usage_type,
              visual_format, hook_type, caption_archetype, post_count,
              total_plays, median_plays, top_accounts_json, example_posts_json,
              recommendation_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern["id"],
                pattern["platform"],
                pattern["audioId"],
                pattern["audioTitle"],
                pattern["artistName"],
                pattern["usageType"],
                pattern["visualFormat"],
                pattern["hookType"],
                pattern["captionArchetype"],
                pattern["postCount"],
                pattern["totalPlays"],
                pattern["medianPlays"],
                json_dump(pattern["topAccounts"]),
                json_dump(pattern["examplePosts"]),
                json_dump(pattern["recommendation"]),
                timestamp,
                timestamp,
            ),
        )
    conn.commit()
    paths: dict[str, str] = {}
    if output_dir:
        paths = write_audio_patterns(patterns, output_dir, limit)
    return {
        "schema": "reference_factory.analyze_audio_patterns.v1",
        "limit": limit,
        "sourceRows": len(rows),
        "audioPatternCount": len(patterns),
        "platforms": dict(
            Counter(pattern["platform"] for pattern in patterns).most_common()
        ),
        "usageTypes": dict(
            Counter(pattern["usageType"] for pattern in patterns).most_common()
        ),
        "topPatterns": patterns[:10],
        **paths,
    }


def import_audio_csv(
    conn: Connection, input_path: Path, *, preserve_manual_fields: bool = False
) -> dict[str, object]:
    input_path = Path(input_path).expanduser()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    now = now_iso()
    imported = 0
    errors: list[dict[str, object]] = []
    with input_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_no, row in enumerate(reader, 2):
            try:
                record = _catalog_record_from_row(row, now)
            except ValueError as exc:
                errors.append({"row": row_no, "error": str(exc)})
                continue
            if preserve_manual_fields:
                record = _preserve_manual_audio_fields(conn, record)
            conn.execute(
                """
                INSERT INTO audio_catalog (
                  id, title, artist_name, source, platform, native_audio_id, native_audio_url,
                  local_preview_path, mood_tags_json, best_content_types_json, account_fit_json,
                  bpm, energy, vocality, danceability, valence, trend_status, usage_count,
                  safe_usage_notes, date_discovered, expires_at, example_reels_json,
                  raw_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, native_audio_id) DO UPDATE SET
                  title = excluded.title,
                  artist_name = excluded.artist_name,
                  source = excluded.source,
                  native_audio_url = excluded.native_audio_url,
                  local_preview_path = excluded.local_preview_path,
                  mood_tags_json = excluded.mood_tags_json,
                  best_content_types_json = excluded.best_content_types_json,
                  account_fit_json = excluded.account_fit_json,
                  bpm = excluded.bpm,
                  energy = excluded.energy,
                  vocality = excluded.vocality,
                  danceability = excluded.danceability,
                  valence = excluded.valence,
                  trend_status = excluded.trend_status,
                  usage_count = excluded.usage_count,
                  safe_usage_notes = excluded.safe_usage_notes,
                  date_discovered = excluded.date_discovered,
                  expires_at = excluded.expires_at,
                  example_reels_json = excluded.example_reels_json,
                  raw_json = excluded.raw_json,
                  updated_at = excluded.updated_at
                """,
                (
                    record["id"],
                    record["title"],
                    record.get("artistName"),
                    record.get("source"),
                    record["platform"],
                    record.get("nativeAudioId"),
                    record.get("nativeAudioUrl"),
                    record.get("localPreviewPath"),
                    json_dump(record.get("moodTags") or []),
                    json_dump(record.get("bestContentTypes") or []),
                    json_dump(record.get("accountFit") or []),
                    record.get("bpm"),
                    record.get("energy"),
                    record.get("vocality"),
                    record.get("danceability"),
                    record.get("valence"),
                    record.get("trendStatus"),
                    record.get("usageCount"),
                    record.get("safeUsageNotes"),
                    record.get("dateDiscovered"),
                    record.get("expiresAt"),
                    json_dump(record.get("exampleReels") or []),
                    json_dump(record.get("raw") or {}),
                    now,
                    now,
                ),
            )
            imported += 1
    conn.commit()
    return {
        "schema": "reference_factory.import_audio_catalog.v1",
        "inputPath": str(input_path),
        "imported": imported,
        "errors": errors,
        "preserveManualFields": preserve_manual_fields,
    }


def import_example_reel_audio(
    conn: Connection,
    input_path: Path | None = None,
    *,
    limit: int = 500,
    export_path: Path | None = None,
    preserve_manual_fields: bool = True,
) -> dict[str, object]:
    """Promote audio found in existing/example reels into the operator audio catalog.

    This intentionally uses local/public metadata already present in Reference Factory
    or explicit JSON/CSV files. It does not log into Instagram, call private APIs, or
    attempt native audio attachment.
    """
    now_iso()
    source_rows = _example_reel_audio_rows(conn, input_path=input_path, limit=limit)
    result = _import_audio_rows(
        conn,
        source_rows,
        export_path=export_path,
        preserve_manual_fields=preserve_manual_fields,
    )
    return {
        "schema": "reference_factory.import_example_reel_audio.v1",
        "inputPath": str(Path(input_path).expanduser()) if input_path else None,
        "source": "file" if input_path else "reference_factory.public_posts",
        **result,
    }


def _import_audio_rows(
    conn: Connection,
    source_rows: list[dict[str, Any]],
    *,
    export_path: Path | None = None,
    preserve_manual_fields: bool = True,
) -> dict[str, object]:
    now = now_iso()
    imported = 0
    unresolved = 0
    errors: list[dict[str, object]] = []
    items: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows, start=1):
        try:
            record = _catalog_record_from_example_reel(row, now)
            if preserve_manual_fields:
                record = _preserve_manual_audio_fields(conn, record)
            saved = upsert_audio_record(conn, record)["item"]
            review_reasons = audio_catalog_review_reasons(saved)
            if (
                "missing_resolved_title" in review_reasons
                or "missing_native_locator" in review_reasons
            ):
                unresolved += 1
            items.append(_example_audio_import_summary(saved, review_reasons))
            imported += 1
        except ValueError as exc:
            errors.append({"row": index, "error": str(exc), "source": row})
    export_payload = export_audio_catalog(conn, export_path) if export_path else None
    return {
        "considered": len(source_rows),
        "imported": imported,
        "unresolved": unresolved,
        "errors": errors,
        "items": items[:25],
        "exportPath": export_payload.get("path")
        if isinstance(export_payload, dict)
        else None,
    }


def scrape_instagram_audio(
    conn: Connection,
    *,
    urls: list[str] | None = None,
    input_path: Path | None = None,
    limit: int = 50,
    export_path: Path | None = None,
    fetcher: Any | None = None,
) -> dict[str, object]:
    """Scrape public Instagram reel/post pages for audio metadata.

    This fetches only public page HTML for explicit URLs. It does not log in,
    bypass access controls, call private mobile APIs, or attach native audio.
    """
    targets = _instagram_audio_targets(
        urls=urls or [], input_path=input_path, limit=limit
    )
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, object]] = []
    open_url = fetcher or _fetch_public_page
    for index, url in enumerate(targets, start=1):
        try:
            row = _instagram_audio_row_from_stored_reference(conn, url)
            if row is None:
                page = open_url(url)
                row = _instagram_audio_row_from_html(url, page)
            rows.append(row)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            errors.append({"row": index, "url": url, "error": str(exc)})
            rows.append(_unresolved_instagram_audio_row(url, reason=str(exc)))
    import_result = _import_audio_rows(conn, rows, export_path=export_path)
    return {
        "schema": "reference_factory.scrape_instagram_audio.v1",
        "requested": len(targets),
        "scraped": len(rows),
        "errors": errors,
        **import_result,
    }


def upsert_audio_record(
    conn: Connection, payload: dict[str, object]
) -> dict[str, object]:
    now = now_iso()
    record = _catalog_record_from_row(payload, now)
    conn.execute(
        """
        INSERT INTO audio_catalog (
          id, title, artist_name, source, platform, native_audio_id, native_audio_url,
          local_preview_path, mood_tags_json, best_content_types_json, account_fit_json,
          bpm, energy, vocality, danceability, valence, trend_status, usage_count,
          safe_usage_notes, date_discovered, expires_at, example_reels_json,
          raw_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, native_audio_id) DO UPDATE SET
          title = excluded.title,
          artist_name = excluded.artist_name,
          source = excluded.source,
          native_audio_url = excluded.native_audio_url,
          local_preview_path = excluded.local_preview_path,
          mood_tags_json = excluded.mood_tags_json,
          best_content_types_json = excluded.best_content_types_json,
          account_fit_json = excluded.account_fit_json,
          bpm = excluded.bpm,
          energy = excluded.energy,
          vocality = excluded.vocality,
          danceability = excluded.danceability,
          valence = excluded.valence,
          trend_status = excluded.trend_status,
          usage_count = excluded.usage_count,
          safe_usage_notes = excluded.safe_usage_notes,
          date_discovered = excluded.date_discovered,
          expires_at = excluded.expires_at,
          example_reels_json = excluded.example_reels_json,
          raw_json = excluded.raw_json,
          updated_at = excluded.updated_at
        """,
        (
            record["id"],
            record["title"],
            record.get("artistName"),
            record.get("source"),
            record["platform"],
            record.get("nativeAudioId"),
            record.get("nativeAudioUrl"),
            record.get("localPreviewPath"),
            json_dump(record.get("moodTags") or []),
            json_dump(record.get("bestContentTypes") or []),
            json_dump(record.get("accountFit") or []),
            record.get("bpm"),
            record.get("energy"),
            record.get("vocality"),
            record.get("danceability"),
            record.get("valence"),
            record.get("trendStatus"),
            record.get("usageCount"),
            record.get("safeUsageNotes"),
            record.get("dateDiscovered"),
            record.get("expiresAt"),
            json_dump(record.get("exampleReels") or []),
            json_dump(record.get("raw") or {}),
            now,
            now,
        ),
    )
    conn.commit()
    return {"schema": "reference_factory.audio_catalog_upsert.v1", "item": record}


def resolve_audio_record(
    conn: Connection, payload: dict[str, object]
) -> dict[str, object]:
    now = now_iso()
    platform = _norm(_get(payload, "platform") or "")
    native_id = _get(
        payload,
        "native_audio_id",
        "nativeAudioId",
        "audio_id",
        "audioId",
        "platform_audio_id",
    )
    if not platform:
        raise ValueError("platform is required")
    if not native_id:
        raise ValueError("nativeAudioId is required")
    row = conn.execute(
        "SELECT * FROM audio_catalog WHERE platform = ? AND native_audio_id = ?",
        (platform, native_id),
    ).fetchone()
    if not row:
        raise ValueError("audio catalog record not found")
    existing = _catalog_payload(dict(row))
    raw = existing.get("raw") or {}
    raw["manualResolved"] = True
    raw["manualResolvedAt"] = now
    title = _get(payload, "title") or existing["title"]
    artist = _get(payload, "artist", "artist_name", "artistName") or existing.get(
        "artistName"
    )
    native_url = _get(
        payload, "native_audio_url", "nativeAudioUrl", "url", "platform_url"
    ) or existing.get("nativeAudioUrl")
    trend_status = _norm(
        _get(payload, "trend_status", "trendStatus", "freshness")
        or existing.get("trendStatus")
        or "unknown"
    )
    mood_tags = (
        _csv_tags(
            _get(payload, "mood_tags", "moodTags", "vibe_tags", "vibeTags", "tags")
        )
        or existing.get("moodTags")
        or []
    )
    best_content = (
        _csv_tags(
            _get(payload, "best_content_types", "bestContentTypes", "content_tags")
        )
        or existing.get("bestContentTypes")
        or []
    )
    account_fit = (
        _csv_tags(_get(payload, "account_fit", "accountFit", "account_tags"))
        or existing.get("accountFit")
        or []
    )
    expires_at = _get(
        payload, "expires_at", "expiresAt", "expiry", "stale_after"
    ) or existing.get("expiresAt")
    safe_notes = _get(
        payload, "safe_usage_notes", "safeUsageNotes", "notes"
    ) or existing.get("safeUsageNotes")
    usage_count = _int(_get(payload, "usage_count", "usageCount", "uses"))
    if usage_count is None:
        usage_count = existing.get("usageCount")
    conn.execute(
        """
        UPDATE audio_catalog
        SET title = ?,
            artist_name = ?,
            native_audio_url = ?,
            mood_tags_json = ?,
            best_content_types_json = ?,
            account_fit_json = ?,
            trend_status = ?,
            usage_count = ?,
            safe_usage_notes = ?,
            expires_at = ?,
            raw_json = ?,
            updated_at = ?
        WHERE platform = ? AND native_audio_id = ?
        """,
        (
            title,
            artist,
            native_url,
            json_dump(mood_tags),
            json_dump(best_content),
            json_dump(account_fit),
            trend_status,
            usage_count,
            safe_notes,
            expires_at,
            json_dump(raw),
            now,
            platform,
            native_id,
        ),
    )
    conn.commit()
    updated = conn.execute(
        "SELECT * FROM audio_catalog WHERE platform = ? AND native_audio_id = ?",
        (platform, native_id),
    ).fetchone()
    return {
        "schema": "reference_factory.audio_catalog_resolve.v1",
        "item": _catalog_payload(dict(updated)),
    }


def list_audio_catalog(
    conn: Connection,
    *,
    platform: str | None = None,
    fresh_only: bool = False,
    limit: int = 100,
) -> dict[str, object]:
    where = []
    params: list[Any] = []
    if platform:
        where.append("platform = ?")
        params.append(_norm(platform))
    sql = "SELECT * FROM audio_catalog"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, title LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    rows = [_catalog_payload(dict(row)) for row in conn.execute(sql, params).fetchall()]
    snapshots = _latest_snapshots_for_catalog(conn, [str(row["id"]) for row in rows])
    for row in rows:
        snapshot = snapshots.get(str(row["id"]))
        if snapshot:
            row["latestTrendSnapshot"] = snapshot
    if fresh_only:
        rows = [row for row in rows if _is_fresh_catalog_record(row)]
    return {
        "schema": "reference_factory.audio_catalog.v1",
        "count": len(rows),
        "items": rows,
    }


def review_audio_catalog(
    conn: Connection,
    *,
    platform: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    rows = list_audio_catalog(conn, platform=platform, fresh_only=False, limit=limit)[
        "items"
    ]
    items = []
    for row in rows:
        reasons = audio_catalog_review_reasons(row)
        if reasons:
            items.append({**row, "reviewReasons": reasons})
    return {
        "schema": "reference_factory.audio_catalog_review.v1",
        "count": len(items),
        "items": items,
    }


def audio_resolution_shortlist(
    conn: Connection,
    *,
    platform: str = "tiktok",
    limit: int = 10,
) -> dict[str, object]:
    rows = review_audio_catalog(conn, platform=platform, limit=1000)["items"]
    unresolved = [
        row
        for row in rows
        if "missing_resolved_title" in (row.get("reviewReasons") or [])
    ]

    def priority(row: dict[str, Any]) -> tuple[int, int, int, str]:
        trend = _norm(str(row.get("trendStatus") or "unknown"))
        trend_rank = {
            "rising": 6,
            "trending": 5,
            "fresh": 4,
            "current": 3,
            "unknown": 2,
            "peaked": 1,
            "fading": 0,
            "stale": -1,
            "expired": -2,
        }.get(trend, 0)
        usage = row.get("usageCount")
        if not isinstance(usage, int):
            snapshot = row.get("latestTrendSnapshot") or {}
            usage = (
                snapshot.get("usageCount")
                if isinstance(snapshot.get("usageCount"), int)
                else 0
            )
        examples = len(row.get("exampleReels") or [])
        return (trend_rank, int(usage or 0), examples, str(row.get("updatedAt") or ""))

    shortlist = sorted(unresolved, key=priority, reverse=True)[
        : max(1, min(limit, 100))
    ]
    items = []
    for index, row in enumerate(shortlist, start=1):
        examples = row.get("exampleReels") or []
        items.append(
            {
                "rank": index,
                "platform": row.get("platform"),
                "nativeAudioId": row.get("nativeAudioId"),
                "currentTitle": row.get("title"),
                "artistName": row.get("artistName"),
                "nativeAudioUrl": row.get("nativeAudioUrl"),
                "exampleUrl": examples[0] if examples else row.get("nativeAudioUrl"),
                "exampleReels": examples[:5],
                "usageCount": row.get("usageCount"),
                "trendStatus": row.get("trendStatus"),
                "reviewReasons": row.get("reviewReasons") or [],
                "resolveCommand": (
                    "reference_factory resolve-audio "
                    f"--platform {row.get('platform') or platform} "
                    f"--native-audio-id {row.get('nativeAudioId') or ''} "
                    "--title TITLE --artist ARTIST --trend-status rising"
                ),
            }
        )
    return {
        "schema": "reference_factory.audio_resolution_shortlist.v1",
        "platform": _norm(platform),
        "count": len(items),
        "unresolvedTotal": len(unresolved),
        "items": items,
    }


def audio_catalog_review_reasons(item: dict[str, Any]) -> list[str]:
    reasons = []
    if is_generic_audio_title(
        str(item.get("title") or ""), str(item.get("platform") or "")
    ):
        reasons.append("missing_resolved_title")
    trend = _norm(str(item.get("trendStatus") or "unknown"))
    if trend in STALE_TREND_STATUSES:
        reasons.append(f"trend_status:{trend}")
    expires = item.get("expiresAt")
    if isinstance(expires, str) and expires.strip():
        parsed = _parse_date(expires)
        if parsed and parsed < datetime.now(UTC):
            reasons.append("expired")
    if not (item.get("nativeAudioId") or item.get("nativeAudioUrl")):
        reasons.append("missing_native_locator")
    if not item.get("moodTags"):
        reasons.append("missing_mood_tags")
    if not item.get("bestContentTypes"):
        reasons.append("missing_content_tags")
    snapshot = item.get("latestTrendSnapshot") or {}
    if snapshot:
        snapshot_trend = _norm(str(snapshot.get("trendStatus") or "unknown"))
        if (
            snapshot_trend in STALE_TREND_STATUSES
            and f"trend_status:{snapshot_trend}" not in reasons
        ):
            reasons.append(f"snapshot_trend_status:{snapshot_trend}")
        saturation = snapshot.get("saturationScore")
        if isinstance(saturation, (int, float)) and saturation >= 0.85:
            reasons.append("high_saturation")
    return reasons


def audio_catalog_health(
    conn: Connection, *, platform: str | None = None, limit: int = 10
) -> dict[str, object]:
    rows = list_audio_catalog(conn, platform=platform, fresh_only=False, limit=1000)[
        "items"
    ]
    fresh = [row for row in rows if _is_fresh_catalog_record(row)]
    stale = [row for row in rows if not _is_fresh_catalog_record(row)]
    unresolved = [
        row
        for row in rows
        if "missing_resolved_title" in audio_catalog_review_reasons(row)
    ]
    ready = [
        row
        for row in fresh
        if "missing_resolved_title" not in audio_catalog_review_reasons(row)
    ]
    recommendations: list[dict[str, Any]] = []
    if platform:
        recommendations = [
            item
            for item in recommend_audio(
                conn,
                platform=platform,
                content_tags=["ai_ofm", "slideshow"],
                limit=100,
            )["recommendations"]
            if not is_generic_audio_title(
                str(item.get("audioTitle") or ""), str(item.get("platform") or "")
            )
        ][: max(1, limit)]
    return {
        "schema": "reference_factory.audio_catalog_health.v1",
        "platform": _norm(platform) if platform else None,
        "total": len(rows),
        "fresh": len(fresh),
        "stale": len(stale),
        "unresolvedTitles": len(unresolved),
        "ready": len(ready),
        "topRecommendations": recommendations[: max(1, limit)],
    }


def import_audio_snapshot_csv(conn: Connection, input_path: Path) -> dict[str, object]:
    input_path = Path(input_path).expanduser()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    imported = 0
    errors: list[dict[str, object]] = []
    with input_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_no, row in enumerate(reader, 2):
            try:
                upsert_audio_trend_snapshot(conn, row, commit=False)
            except ValueError as exc:
                errors.append({"row": row_no, "error": str(exc)})
                continue
            imported += 1
    conn.commit()
    return {
        "schema": "reference_factory.import_audio_trend_snapshots.v1",
        "inputPath": str(input_path),
        "imported": imported,
        "errors": errors,
    }


def upsert_audio_trend_snapshot(
    conn: Connection, payload: dict[str, object], *, commit: bool = True
) -> dict[str, object]:
    now = now_iso()
    record = _snapshot_record_from_row(conn, payload, now)
    conn.execute(
        """
        INSERT INTO audio_trend_snapshots (
          id, audio_catalog_id, platform, native_audio_id, observed_at, trend_status,
          usage_count, saturation_score, velocity_score, curator, source, notes,
          raw_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(audio_catalog_id, observed_at) DO UPDATE SET
          trend_status = excluded.trend_status,
          usage_count = excluded.usage_count,
          saturation_score = excluded.saturation_score,
          velocity_score = excluded.velocity_score,
          curator = excluded.curator,
          source = excluded.source,
          notes = excluded.notes,
          raw_json = excluded.raw_json
        """,
        (
            record["id"],
            record["audioCatalogId"],
            record["platform"],
            record.get("nativeAudioId"),
            record["observedAt"],
            record["trendStatus"],
            record.get("usageCount"),
            record.get("saturationScore"),
            record.get("velocityScore"),
            record.get("curator"),
            record.get("source"),
            record.get("notes"),
            json_dump(record.get("raw") or {}),
            now,
        ),
    )
    conn.execute(
        """
        UPDATE audio_catalog
        SET trend_status = ?,
            usage_count = COALESCE(?, usage_count),
            updated_at = ?
        WHERE id = ?
        """,
        (
            record["trendStatus"],
            record.get("usageCount"),
            now,
            record["audioCatalogId"],
        ),
    )
    if commit:
        conn.commit()
    return {
        "schema": "reference_factory.audio_trend_snapshot_upsert.v1",
        "item": record,
    }


def list_audio_trend_snapshots(
    conn: Connection,
    *,
    platform: str | None = None,
    audio_catalog_id: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    where = []
    params: list[Any] = []
    if platform:
        where.append("platform = ?")
        params.append(_norm(platform))
    if audio_catalog_id:
        where.append("audio_catalog_id = ?")
        params.append(audio_catalog_id)
    sql = "SELECT * FROM audio_trend_snapshots"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY observed_at DESC, created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    items = [
        _snapshot_payload(dict(row)) for row in conn.execute(sql, params).fetchall()
    ]
    return {
        "schema": "reference_factory.audio_trend_snapshots.v1",
        "count": len(items),
        "items": items,
    }


def recommend_audio(
    conn: Connection,
    *,
    platform: str,
    content_tags: list[str] | None = None,
    account_tags: list[str] | None = None,
    limit: int = 3,
) -> dict[str, object]:
    tags = {_norm(tag) for tag in (content_tags or []) if _norm(tag)}
    accounts = {_norm(tag) for tag in (account_tags or []) if _norm(tag)}
    rows = list_audio_catalog(conn, platform=platform, fresh_only=False, limit=1000)[
        "items"
    ]
    scored = []
    for item in rows:
        score, reasons = _score_audio_candidate(item, tags, accounts)
        if not _is_fresh_catalog_record(item):
            score -= 25
            reasons.append("stale_or_expired")
        scored.append(
            {
                **item,
                "matchScore": max(0, round(score, 3)),
                "rationale": ", ".join(reasons) or "platform match",
            }
        )
    scored.sort(
        key=lambda item: (
            -float(item["matchScore"]),
            -(int(item.get("usageCount") or 0)),
            str(item.get("title") or ""),
        )
    )
    return {
        "schema": "reference_factory.audio_recommendations.v1",
        "platform": _norm(platform),
        "contentTags": sorted(tags),
        "accountTags": sorted(accounts),
        "recommendations": [
            _catalog_to_recommendation(item) for item in scored[: max(1, limit)]
        ],
    }


def competitor_audio_leaderboard(
    conn: Connection,
    *,
    platform: str | None = None,
    accounts: list[str] | None = None,
    caption_keywords: list[str] | None = None,
    min_plays: int = 0,
    min_posts: int = 1,
    limit: int = 50,
    output_path: Path | None = None,
) -> dict[str, object]:
    account_filter = {
        _norm(account).lstrip("@") for account in (accounts or []) if _norm(account)
    }
    keyword_filter = [
        _norm(keyword) for keyword in (caption_keywords or []) if _norm(keyword)
    ]
    rows = conn.execute(
        """
        SELECT *
        FROM public_posts
        WHERE video_play_count IS NOT NULL OR video_view_count IS NOT NULL
        ORDER BY COALESCE(video_play_count, video_view_count, 0) DESC,
                 COALESCE(video_view_count, 0) DESC,
                 COALESCE(likes_count, 0) DESC
        """,
    ).fetchall()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    considered = 0
    for row in rows:
        post = dict(row)
        owner = _norm(str(post.get("owner_username") or "")).lstrip("@")
        caption = _norm(str(post.get("caption") or ""))
        if account_filter and owner not in account_filter:
            continue
        if keyword_filter and not any(keyword in caption for keyword in keyword_filter):
            continue
        raw_json = json_load(post.get("raw_json") or "{}", {})
        signal = extract_audio_signal(raw_json, post.get("product_type"))
        if not signal:
            continue
        if platform and signal["platform"] != _norm(platform):
            continue
        plays = int(post.get("video_play_count") or post.get("video_view_count") or 0)
        if plays < min_plays:
            continue
        considered += 1
        groups[(signal["platform"], signal["audioId"])].append(
            {
                "signal": signal,
                "ownerUsername": post.get("owner_username"),
                "shortCode": post.get("short_code"),
                "url": post.get("url"),
                "caption": post.get("caption"),
                "plays": plays,
                "views": int(post.get("video_view_count") or 0),
                "likes": int(post.get("likes_count") or 0),
                "comments": int(post.get("comments_count") or 0),
                "timestamp": post.get("timestamp"),
            }
        )
    items = []
    for (audio_platform, audio_id), audio_posts in groups.items():
        if len(audio_posts) < max(1, min_posts):
            continue
        signal = audio_posts[0]["signal"]
        plays = [int(post["plays"] or 0) for post in audio_posts]
        likes = [int(post["likes"] or 0) for post in audio_posts]
        accounts_used = sorted(
            {
                str(post.get("ownerUsername") or "")
                for post in audio_posts
                if post.get("ownerUsername")
            }
        )
        examples = sorted(
            audio_posts,
            key=lambda post: (
                -int(post["plays"] or 0),
                str(post.get("ownerUsername") or ""),
            ),
        )[:8]
        score = (
            sum(plays)
            + (statistics.median(plays) if plays else 0)
            + (len(accounts_used) * 5000)
            + (len(audio_posts) * 2500)
        )
        items.append(
            {
                "platform": audio_platform,
                "audioId": audio_id,
                "audioTitle": signal.get("audioTitle"),
                "artistName": signal.get("artistName"),
                "usageType": signal.get("usageType"),
                "audioVibe": signal.get("audioVibe"),
                "postCount": len(audio_posts),
                "accountCount": len(accounts_used),
                "accounts": accounts_used[:12],
                "totalPlays": sum(plays),
                "medianPlays": int(statistics.median(plays)) if plays else 0,
                "totalLikes": sum(likes),
                "score": round(float(score), 3),
                "instruction": _audio_instruction(
                    signal,
                    "competitor_reference",
                    "similar_creator",
                    "similar_creator_audio",
                ),
                "examples": [
                    {
                        "ownerUsername": post.get("ownerUsername"),
                        "url": post.get("url"),
                        "plays": post.get("plays"),
                        "likes": post.get("likes"),
                        "caption": post.get("caption"),
                        "timestamp": post.get("timestamp"),
                    }
                    for post in examples
                ],
            }
        )
    items.sort(
        key=lambda item: (
            -float(item["score"]),
            -int(item["totalPlays"]),
            str(item.get("audioTitle") or ""),
        )
    )
    payload = {
        "schema": "reference_factory.competitor_audio_leaderboard.v1",
        "platform": _norm(platform) if platform else None,
        "accounts": sorted(account_filter),
        "captionKeywords": keyword_filter,
        "minPlays": min_plays,
        "minPosts": min_posts,
        "sourcePostsConsidered": considered,
        "count": min(len(items), max(1, limit)),
        "items": items[: max(1, limit)],
        "usage": "Use this as metadata for native platform audio selection. Do not download or burn copyrighted audio.",
    }
    if output_path:
        output_path = Path(output_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            output_path,
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        payload["path"] = str(output_path)
    return payload


def export_audio_catalog(
    conn: Connection, output_path: Path | None = None
) -> dict[str, object]:
    payload = list_audio_catalog(conn, limit=1000)
    payload["schema"] = "reference_factory.audio_catalog_export.v1"
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    snapshots_by_audio = _latest_snapshots_for_catalog(
        conn,
        [
            str(item["id"])
            for item in items
            if isinstance(item, dict) and item.get("id")
        ],
    )
    for item in items:
        if not isinstance(item, dict):
            continue
        review_reasons = audio_catalog_review_reasons(item)
        latest_snapshot = snapshots_by_audio.get(str(item.get("id")))
        trend_snapshots = [latest_snapshot] if latest_snapshot else []
        item.setdefault("trendSnapshots", trend_snapshots)
        item.setdefault("exampleReels", item.get("exampleReels") or [])
        item.setdefault(
            "performanceSummary",
            {
                "postCount": len(item.get("exampleReels") or []),
                "usageCount": item.get("usageCount"),
                "source": "reference_factory.audio_catalog",
            },
        )
        item.setdefault(
            "fatigue",
            {
                "level": "high" if "high_saturation" in review_reasons else "low",
                "source": "reference_factory.review",
            },
        )
        item.setdefault(
            "resolved",
            "missing_resolved_title" not in review_reasons
            and "missing_native_locator" not in review_reasons,
        )
        item.setdefault("reviewReasons", review_reasons)
        item.setdefault(
            "sourceConfidence",
            0.8 if item.get("nativeAudioId") or item.get("nativeAudioUrl") else 0.45,
        )
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        for raw_key, export_key in (
            ("trendScore", "trendScore"),
            ("velocityScore", "velocityScore"),
            ("accountFitScore", "accountFitScore"),
            ("creatorFitScore", "creatorFitScore"),
            ("recommendationConfidence", "recommendationConfidence"),
            ("trendSources", "trendSources"),
            ("performanceSummary", "performanceSummary"),
        ):
            if raw_key in raw:
                if export_key == "performanceSummary":
                    item[export_key] = raw[raw_key]
                else:
                    item.setdefault(export_key, raw[raw_key])
        if raw.get("sourceConfidence") is not None:
            item["sourceConfidence"] = raw["sourceConfidence"]
        if raw.get("resolved") is not None:
            item["resolved"] = bool(raw["resolved"])
        if raw.get("reviewReasons") and not item.get("reviewReasons"):
            item["reviewReasons"] = raw["reviewReasons"]
    if output_path:
        output_path = Path(output_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            output_path,
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        payload["path"] = str(output_path)
    return payload


def _snapshot_record_from_row(
    conn: Connection, row: dict[str, object], now: str
) -> dict[str, Any]:
    catalog_id = _get(
        row, "audio_catalog_id", "audioCatalogId", "catalog_audio_id", "catalogAudioId"
    )
    platform = _norm(_get(row, "platform") or "")
    native_id = _get(
        row,
        "native_audio_id",
        "nativeAudioId",
        "audio_id",
        "audioId",
        "platform_audio_id",
    )
    catalog_row = None
    if catalog_id:
        catalog_row = conn.execute(
            "SELECT * FROM audio_catalog WHERE id = ?", (catalog_id,)
        ).fetchone()
    elif platform and native_id:
        catalog_row = conn.execute(
            "SELECT * FROM audio_catalog WHERE platform = ? AND native_audio_id = ?",
            (platform, native_id),
        ).fetchone()
    if not catalog_row:
        raise ValueError(
            "snapshot must reference an existing audio catalog record by audioCatalogId or platform/nativeAudioId"
        )
    catalog = _catalog_payload(dict(catalog_row))
    observed_at = (
        _get(row, "observed_at", "observedAt", "snapshot_at", "snapshotAt", "date")
        or now
    )
    trend_status = _norm(
        _get(row, "trend_status", "trendStatus", "freshness")
        or catalog.get("trendStatus")
        or "unknown"
    )
    usage_count = _int(_get(row, "usage_count", "usageCount", "uses"))
    return {
        "id": stable_id("audio_trend_snapshot", catalog["id"], observed_at),
        "audioCatalogId": catalog["id"],
        "platform": catalog["platform"],
        "nativeAudioId": catalog.get("nativeAudioId"),
        "audioTitle": catalog.get("title"),
        "observedAt": observed_at,
        "trendStatus": trend_status,
        "usageCount": usage_count,
        "saturationScore": _float(
            _get(row, "saturation_score", "saturationScore", "saturation")
        ),
        "velocityScore": _float(
            _get(
                row,
                "velocity_score",
                "velocityScore",
                "trend_velocity",
                "trendVelocity",
                "velocity",
            )
        ),
        "curator": _get(row, "curator", "operator"),
        "source": _get(row, "source"),
        "notes": _get(row, "notes", "safe_usage_notes", "safeUsageNotes"),
        "raw": row,
    }


def _preserve_manual_audio_fields(
    conn: Connection, record: dict[str, Any]
) -> dict[str, Any]:
    platform = record.get("platform")
    native_id = record.get("nativeAudioId")
    if not platform or not native_id:
        return record
    row = conn.execute(
        "SELECT * FROM audio_catalog WHERE platform = ? AND native_audio_id = ?",
        (platform, native_id),
    ).fetchone()
    if not row:
        return record
    existing = _catalog_payload(dict(row))
    existing_raw = existing.get("raw") or {}
    manually_resolved = bool(
        existing_raw.get("manualResolved")
    ) or not is_generic_audio_title(
        str(existing.get("title") or ""),
        str(existing.get("platform") or ""),
    )
    if not manually_resolved:
        return record
    for key in (
        "title",
        "artistName",
        "moodTags",
        "bestContentTypes",
        "accountFit",
        "safeUsageNotes",
    ):
        if existing.get(key):
            record[key] = existing[key]
    raw = record.get("raw") or {}
    raw["preservedManualFieldsFrom"] = existing.get("updatedAt")
    if existing_raw.get("manualResolved"):
        raw["manualResolved"] = True
        raw["manualResolvedAt"] = existing_raw.get("manualResolvedAt")
    record["raw"] = raw
    return record


def _instagram_audio_targets(
    *,
    urls: list[str],
    input_path: Path | None,
    limit: int,
) -> list[str]:
    targets = [url.strip() for url in urls if url and url.strip()]
    if input_path:
        path = Path(input_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    value = _get(row, "url", "reel_url", "reelUrl", "permalink")
                    if value:
                        targets.append(value)
        elif path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = (
                    payload.get("items")
                    or payload.get("urls")
                    or payload.get("reels")
                    or payload.get("posts")
                    or []
                )
            else:
                items = []
            for item in items:
                if isinstance(item, str):
                    targets.append(item)
                elif isinstance(item, dict):
                    value = _get(
                        item, "url", "reel_url", "reelUrl", "permalink", "sourceReelUrl"
                    )
                    if value:
                        targets.append(value)
        else:
            targets.extend(
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
    seen = set()
    deduped = []
    for target in targets:
        if "instagram.com" not in target.lower():
            continue
        if target in seen:
            continue
        seen.add(target)
        deduped.append(target)
    return deduped[: max(1, limit)]


def _fetch_public_page(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _instagram_audio_row_from_stored_reference(
    conn: Connection, url: str
) -> dict[str, Any] | None:
    shortcode = _instagram_shortcode(url)
    row = conn.execute(
        """
        SELECT *
        FROM public_posts
        WHERE url = ?
           OR short_code = ?
           OR url LIKE ?
        ORDER BY imported_at DESC
        LIMIT 1
        """,
        (url, shortcode, f"%/{shortcode}/%" if shortcode else ""),
    ).fetchone()
    if not row:
        return None
    post = dict(row)
    raw_json = json_load(post.get("raw_json") or "{}", {})
    signal = extract_audio_signal(raw_json, post.get("product_type"))
    if not signal:
        return None
    audio_id = signal.get("audioId")
    return {
        "platform": "instagram",
        "sourceReelUrl": post.get("url") or url,
        "audioTitle": signal.get("audioTitle"),
        "artistName": signal.get("artistName"),
        "nativeAudioId": audio_id,
        "nativeAudioUrl": f"https://www.instagram.com/reels/audio/{audio_id}/"
        if audio_id
        else post.get("url") or url,
        "creatorAccount": post.get("owner_username"),
        "views": post.get("video_view_count"),
        "plays": post.get("video_play_count"),
        "likes": post.get("likes_count"),
        "comments": post.get("comments_count"),
        "caption": post.get("caption"),
        "shortCode": post.get("short_code"),
        "timestamp": post.get("timestamp"),
        "contentTags": "instagram_reels,ofm_reels,ig_reference_cache",
        "moodTags": signal.get("audioVibe") or "ig_reference_audio",
        "sourceConfidence": 0.9,
        "rawSourceType": "reference_factory.public_posts.musicInfo",
    }


def _instagram_audio_row_from_html(url: str, page: str) -> dict[str, Any]:
    text = html_lib.unescape(page)
    music = (
        _json_object_after_key(text, "musicInfo")
        or _json_object_after_key(text, "clips_music_attribution_info")
        or {}
    )
    audio_id = _first_present(
        music,
        "audio_id",
        "audioId",
        "music_canonical_id",
        "original_sound_audio_asset_id",
        "audio_asset_id",
    ) or _regex_first(
        text,
        [
            r'"audio_id"\s*:\s*"([^"]+)"',
            r'"audioId"\s*:\s*"([^"]+)"',
            r'"music_canonical_id"\s*:\s*"([^"]+)"',
            r'"original_sound_audio_asset_id"\s*:\s*"([^"]+)"',
        ],
    )
    title = _first_present(
        music, "song_name", "songName", "title", "audio_title"
    ) or _regex_first(
        text,
        [
            r'"song_name"\s*:\s*"([^"]+)"',
            r'"audio_title"\s*:\s*"([^"]+)"',
            r'"title"\s*:\s*"([^"]+)"',
        ],
    )
    artist = _first_present(
        music, "artist_name", "artistName", "display_artist", "ig_artist"
    ) or _regex_first(
        text,
        [
            r'"artist_name"\s*:\s*"([^"]+)"',
            r'"display_artist"\s*:\s*"([^"]+)"',
        ],
    )
    owner = _regex_first(
        text,
        [
            r'"ownerUsername"\s*:\s*"([^"]+)"',
            r'"username"\s*:\s*"([^"]+)"',
            r'"owner_username"\s*:\s*"([^"]+)"',
        ],
    )
    views = _int(
        _regex_first(
            text,
            [
                r'"video_play_count"\s*:\s*(\d+)',
                r'"videoPlayCount"\s*:\s*(\d+)',
                r'"play_count"\s*:\s*(\d+)',
            ],
        )
    )
    native_url = (
        f"https://www.instagram.com/reels/audio/{audio_id}/" if audio_id else None
    )
    if not audio_id and not title:
        return _unresolved_instagram_audio_row(
            url, reason="audio metadata not present in public page html"
        )
    return {
        "platform": "instagram",
        "sourceReelUrl": url,
        "audioTitle": title or f"Instagram audio {audio_id}",
        "artistName": artist,
        "nativeAudioId": audio_id,
        "nativeAudioUrl": native_url,
        "creatorAccount": owner,
        "views": views,
        "contentTags": "instagram_reels,ofm_reels,ig_scrape",
        "moodTags": "ig_scraped_audio",
        "sourceConfidence": 0.72 if audio_id else 0.48,
        "rawSourceType": "instagram_public_html",
    }


def _instagram_shortcode(url: str) -> str | None:
    match = re.search(r"instagram\.com/(?:p|reel|tv)/([^/?#]+)/?", str(url))
    return match.group(1) if match else None


def _unresolved_instagram_audio_row(url: str, *, reason: str) -> dict[str, Any]:
    return {
        "platform": "instagram",
        "sourceReelUrl": url,
        "audioTitle": None,
        "nativeAudioId": None,
        "nativeAudioUrl": url,
        "contentTags": "instagram_reels,ofm_reels,ig_scrape",
        "moodTags": "ig_audio_unresolved",
        "sourceConfidence": 0.25,
        "reviewReasons": ["missing_public_audio_metadata", reason],
        "rawSourceType": "instagram_public_html",
    }


def _json_object_after_key(text: str, key: str) -> dict[str, Any] | None:
    marker = f'"{key}"'
    start = text.find(marker)
    if start < 0:
        return None
    colon = text.find(":", start + len(marker))
    brace = text.find("{", colon)
    if colon < 0 or brace < 0:
        return None
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(text[brace:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _regex_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                return match.group(1)
    return None


def _first_present(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", []):
            return str(value)
    return None


def _example_reel_audio_rows(
    conn: Connection,
    *,
    input_path: Path | None,
    limit: int,
) -> list[dict[str, Any]]:
    if input_path:
        path = Path(input_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as f:
                return [dict(row) for row in csv.DictReader(f)][: max(1, limit)]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = (
                payload.get("items")
                or payload.get("reels")
                or payload.get("posts")
                or payload.get("data")
                or payload.get("results")
                or []
            )
        else:
            rows = []
        return [row for row in rows if isinstance(row, dict)][: max(1, limit)]

    rows = []
    for row in _audio_source_rows(conn, max(1, limit)):
        post = dict(row)
        raw_json = json_load(post.get("raw_json") or "{}", {})
        signal = extract_audio_signal(raw_json, post.get("product_type"))
        if not signal:
            continue
        rows.append(
            {
                "platform": signal.get("platform"),
                "audioId": signal.get("audioId"),
                "audioTitle": signal.get("audioTitle"),
                "artistName": signal.get("artistName"),
                "usageType": signal.get("usageType"),
                "audioVibe": signal.get("audioVibe"),
                "sourceReelUrl": post.get("url"),
                "creatorAccount": post.get("owner_username"),
                "caption": post.get("caption"),
                "shortCode": post.get("short_code"),
                "views": post.get("video_view_count"),
                "plays": post.get("video_play_count"),
                "likes": post.get("likes_count"),
                "comments": post.get("comments_count"),
                "timestamp": post.get("timestamp"),
                "visualFormat": post.get("visual_format"),
                "hookType": post.get("hook_type"),
                "captionArchetype": post.get("caption_archetype"),
                "sourcePublicPostId": post.get("id"),
                "rawSourceType": "public_posts.raw_json",
            }
        )
    return rows


def _catalog_record_from_example_reel(row: dict[str, Any], now: str) -> dict[str, Any]:
    platform = _norm(
        _get(row, "platform", "sourcePlatform")
        or _infer_platform_from_url(
            _get(
                row,
                "source_reel_url",
                "sourceReelUrl",
                "reel_url",
                "reelUrl",
                "url",
                "permalink",
            )
            or ""
        )
    )
    if not platform:
        platform = "instagram"
    reel_url = _get(
        row,
        "source_reel_url",
        "sourceReelUrl",
        "reel_url",
        "reelUrl",
        "url",
        "permalink",
    )
    title = _get(
        row,
        "title",
        "audio_title",
        "audioTitle",
        "sound_name",
        "soundName",
        "music_title",
        "musicTitle",
        "song_name",
        "songName",
    )
    artist = _get(
        row,
        "artist",
        "artist_name",
        "artistName",
        "author",
        "music_author",
        "musicAuthor",
    )
    native_id = _get(
        row,
        "native_audio_id",
        "nativeAudioId",
        "audio_id",
        "audioId",
        "platform_audio_id",
        "platformAudioId",
        "sound_id",
        "soundId",
        "music_id",
        "musicId",
    )
    native_url = _get(
        row,
        "native_audio_url",
        "nativeAudioUrl",
        "audio_url",
        "audioUrl",
        "platform_url",
        "platformUrl",
        "sound_url",
        "soundUrl",
    )
    stable_source = (
        native_id
        or native_url
        or reel_url
        or json.dumps(row, sort_keys=True, default=str)
    )
    unresolved_hash = stable_id("example_reel_audio", platform, stable_source)[-12:]
    if not native_id:
        native_id = f"example_{unresolved_hash}"
    if not title:
        title = f"{platform.title()} audio {native_id}"
    account = _get(
        row,
        "creator_account",
        "creatorAccount",
        "owner_username",
        "ownerUsername",
        "account",
        "username",
    )
    views = _int(
        _get(
            row,
            "views",
            "plays",
            "video_play_count",
            "videoPlayCount",
            "video_view_count",
            "videoViewCount",
        )
    )
    likes = _int(_get(row, "likes", "likes_count", "likesCount"))
    comments = _int(_get(row, "comments", "comments_count", "commentsCount"))
    saves = _int(_get(row, "saves", "saves_count", "savesCount"))
    shares = _int(_get(row, "shares", "shares_count", "sharesCount"))
    content_tags = sorted(
        {
            "ofm_reels",
            "instagram_reels" if platform == "instagram" else f"{platform}_shorts",
            *_csv_tags(
                _get(
                    row,
                    "content_tags",
                    "contentTags",
                    "best_content_types",
                    "bestContentTypes",
                    "tags",
                )
            ),
        }
    )
    mood_tags = _csv_tags(
        _get(
            row,
            "mood_tags",
            "moodTags",
            "audio_vibe",
            "audioVibe",
            "vibe_tags",
            "vibeTags",
        )
    )
    if not mood_tags:
        mood_tags = ["ofm_winner"]
    example = {
        "url": reel_url,
        "platform": platform,
        "account": account,
        "views": views,
        "likes": likes,
        "comments": comments,
        "saves": saves,
        "shares": shares,
        "caption": _get(row, "caption"),
        "shortCode": _get(row, "short_code", "shortCode"),
        "timestamp": _get(row, "timestamp", "posted_at", "postedAt"),
    }
    example = {
        key: value for key, value in example.items() if value not in (None, "", [])
    }
    source_confidence = _float(_get(row, "source_confidence", "sourceConfidence"))
    if source_confidence is None:
        source_confidence = (
            0.82
            if native_url and title and not is_generic_audio_title(title, platform)
            else 0.68
        )
    if is_generic_audio_title(title, platform):
        source_confidence = 0.42
    trend_score = _example_reel_trend_score(views, likes)
    raw = {key: value for key, value in row.items() if key != "raw"}
    raw.update(
        {
            "sourceType": "example_reel_audio",
            "sourceConfidence": source_confidence,
            "trendScore": trend_score,
            "velocityScore": _float(_get(row, "velocity_score", "velocityScore"))
            or 0.55,
            "accountFitScore": _float(_get(row, "account_fit_score", "accountFitScore"))
            or (0.75 if account else 0.62),
            "creatorFitScore": _float(_get(row, "creator_fit_score", "creatorFitScore"))
            or 0.9,
            "trendSources": ["reference_factory_example_reels"],
            "performanceSummary": {
                "source": "example_reels",
                "postCount": 1,
                "views": views,
                "likes": likes,
                "comments": comments,
                "saves": saves,
                "shares": shares,
            },
            "reviewReasons": _csv_tags(
                row.get("reviewReasons") or _get(row, "review_reasons", "reviewReasons")
            )
            or (
                []
                if not is_generic_audio_title(title, platform)
                else ["missing_resolved_title"]
            ),
            "resolved": not is_generic_audio_title(title, platform),
        }
    )
    return {
        "title": title,
        "artistName": artist,
        "source": "reference_factory.example_reels",
        "platform": platform,
        "nativeAudioId": native_id,
        "nativeAudioUrl": native_url or reel_url,
        "moodTags": mood_tags,
        "bestContentTypes": content_tags,
        "accountFit": [account] if account else ["ofm"],
        "trendStatus": _norm(
            _get(row, "trend_status", "trendStatus")
            or ("rising" if trend_score >= 75 else "current")
        ),
        "usageCount": _int(_get(row, "usage_count", "usageCount", "uses")),
        "safeUsageNotes": (
            "Use as an audio-discovery signal only. Attach the matching native audio manually in Instagram/TikTok."
        ),
        "dateDiscovered": _get(
            row, "date_discovered", "dateDiscovered", "discovered_at"
        )
        or now,
        "exampleReels": [example] if example else [],
        "raw": raw,
    }


def _example_audio_import_summary(
    item: dict[str, Any], review_reasons: list[str]
) -> dict[str, Any]:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "artistName": item.get("artistName"),
        "platform": item.get("platform"),
        "nativeAudioId": item.get("nativeAudioId"),
        "nativeAudioUrl": item.get("nativeAudioUrl"),
        "exampleReels": item.get("exampleReels") or [],
        "trendStatus": item.get("trendStatus"),
        "trendScore": raw.get("trendScore"),
        "sourceConfidence": raw.get("sourceConfidence"),
        "resolved": raw.get("resolved"),
        "reviewReasons": review_reasons,
    }


def _infer_platform_from_url(url: str) -> str:
    lowered = str(url or "").lower()
    if "tiktok.com" in lowered:
        return "tiktok"
    if "instagram.com" in lowered:
        return "instagram"
    return ""


def _example_reel_trend_score(views: int | None, likes: int | None) -> float:
    signal = max(int(views or 0), int(likes or 0) * 20)
    if signal >= 1_000_000:
        return 92.0
    if signal >= 250_000:
        return 84.0
    if signal >= 75_000:
        return 74.0
    if signal >= 15_000:
        return 64.0
    return 55.0


def _catalog_record_from_row(row: dict[str, Any], now: str) -> dict[str, Any]:
    title = _get(row, "title", "audio_title", "audioTitle")
    platform = _norm(_get(row, "platform") or "")
    if not title:
        raise ValueError("title is required")
    if not platform:
        raise ValueError("platform is required")
    artist = _get(row, "artist", "artist_name", "artistName")
    native_id = _get(
        row,
        "native_audio_id",
        "nativeAudioId",
        "audio_id",
        "audioId",
        "platform_audio_id",
    )
    example_reels_value = (
        row.get("exampleReels") or row.get("example_reels") or row.get("examples")
    )
    if isinstance(example_reels_value, list):
        example_reels = example_reels_value
    else:
        example_reels = _csv_tags(example_reels_value)
    raw_value = row.get("raw")
    if isinstance(raw_value, dict):
        raw = dict(raw_value)
        for key in (
            "sourceType",
            "sourceConfidence",
            "trendScore",
            "velocityScore",
            "accountFitScore",
            "creatorFitScore",
            "recommendationConfidence",
            "trendSources",
            "performanceSummary",
            "reviewReasons",
            "resolved",
        ):
            if key in row and key not in raw:
                raw[key] = row[key]
    else:
        raw = row
    return {
        "id": stable_id("audio_catalog", platform, native_id or title, artist or ""),
        "title": title,
        "artistName": artist,
        "source": _get(row, "source"),
        "platform": platform,
        "nativeAudioId": native_id,
        "nativeAudioUrl": _get(
            row, "native_audio_url", "nativeAudioUrl", "url", "platform_url"
        ),
        "localPreviewPath": _get(
            row, "local_preview_path", "localPreviewPath", "preview_path"
        ),
        "moodTags": _csv_tags(
            row.get("moodTags")
            or _get(row, "mood_tags", "vibe_tags", "vibeTags", "tags")
        ),
        "bestContentTypes": _csv_tags(
            row.get("bestContentTypes")
            or _get(row, "best_content_types", "content_tags")
        ),
        "accountFit": _csv_tags(
            row.get("accountFit") or _get(row, "account_fit", "account_tags")
        ),
        "bpm": _float(_get(row, "bpm", "tempo")),
        "energy": _float(_get(row, "energy")),
        "vocality": _get(row, "vocality", "vocal_instrumental", "instrumentalness"),
        "danceability": _float(_get(row, "danceability")),
        "valence": _float(_get(row, "valence", "positivity")),
        "trendStatus": _norm(
            _get(row, "trend_status", "trendStatus", "freshness") or "unknown"
        ),
        "usageCount": _int(_get(row, "usage_count", "usageCount", "uses")),
        "safeUsageNotes": _get(row, "safe_usage_notes", "safeUsageNotes", "notes"),
        "dateDiscovered": _get(
            row, "date_discovered", "dateDiscovered", "discovered_at"
        )
        or now,
        "expiresAt": _get(row, "expires_at", "expiresAt", "expiry", "stale_after"),
        "exampleReels": example_reels,
        "raw": raw,
    }


def _catalog_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "artistName": row["artist_name"],
        "source": row["source"],
        "platform": row["platform"],
        "nativeAudioId": row["native_audio_id"],
        "nativeAudioUrl": row["native_audio_url"],
        "localPreviewPath": row["local_preview_path"],
        "moodTags": json_load(row["mood_tags_json"], []),
        "bestContentTypes": json_load(row["best_content_types_json"], []),
        "accountFit": json_load(row["account_fit_json"], []),
        "bpm": row["bpm"],
        "energy": row["energy"],
        "vocality": row["vocality"],
        "danceability": row["danceability"],
        "valence": row["valence"],
        "trendStatus": row["trend_status"],
        "usageCount": row["usage_count"],
        "safeUsageNotes": row["safe_usage_notes"],
        "dateDiscovered": row["date_discovered"],
        "expiresAt": row["expires_at"],
        "exampleReels": json_load(row["example_reels_json"], []),
        "raw": json_load(row["raw_json"], {}),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _latest_snapshots_for_catalog(
    conn: Connection, catalog_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not catalog_ids:
        return {}
    placeholders = ",".join("?" for _ in catalog_ids)
    rows = conn.execute(
        f"""
        SELECT s.*
        FROM audio_trend_snapshots s
        JOIN (
          SELECT audio_catalog_id, MAX(observed_at) AS observed_at
          FROM audio_trend_snapshots
          WHERE audio_catalog_id IN ({placeholders})
          GROUP BY audio_catalog_id
        ) latest
          ON latest.audio_catalog_id = s.audio_catalog_id
         AND latest.observed_at = s.observed_at
        """,
        catalog_ids,
    ).fetchall()
    return {str(row["audio_catalog_id"]): _snapshot_payload(dict(row)) for row in rows}


def _snapshot_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "audioCatalogId": row["audio_catalog_id"],
        "platform": row["platform"],
        "nativeAudioId": row["native_audio_id"],
        "observedAt": row["observed_at"],
        "trendStatus": row["trend_status"],
        "usageCount": row["usage_count"],
        "saturationScore": row["saturation_score"],
        "velocityScore": row["velocity_score"],
        "curator": row["curator"],
        "source": row["source"],
        "notes": row["notes"],
        "raw": json_load(row["raw_json"], {}),
        "createdAt": row["created_at"],
    }


def _catalog_to_recommendation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "reference_factory.audio_catalog",
        "catalogAudioId": item["id"],
        "platform": item["platform"],
        "audioId": item.get("nativeAudioId"),
        "audioTitle": item.get("title"),
        "artistName": item.get("artistName"),
        "platformUrl": item.get("nativeAudioUrl"),
        "audioVibe": (item.get("moodTags") or [None])[0],
        "vibeTags": item.get("moodTags") or [],
        "bestContentTypes": item.get("bestContentTypes") or [],
        "accountFit": item.get("accountFit") or [],
        "freshness": item.get("trendStatus") or "unknown",
        "trendStatus": item.get("trendStatus") or "unknown",
        "latestTrendSnapshot": item.get("latestTrendSnapshot"),
        "usageCount": item.get("usageCount"),
        "bpm": item.get("bpm"),
        "energy": item.get("energy"),
        "vocality": item.get("vocality"),
        "confidence": min(1.0, float(item.get("matchScore") or 0) / 100.0),
        "rationale": item.get("rationale"),
        "safeUsageNotes": item.get("safeUsageNotes"),
        "instruction": f"Attach native {item.get('platform')} audio: {item.get('title')}",
    }


def _score_audio_candidate(
    item: dict[str, Any], tags: set[str], accounts: set[str]
) -> tuple[float, list[str]]:
    score = 35.0
    reasons = []
    trend = _norm(str(item.get("trendStatus") or "unknown"))
    if trend in {"rising", "fresh", "trending", "current"}:
        score += 25
        reasons.append(f"trend:{trend}")
    elif trend in STALE_TREND_STATUSES:
        score -= 20
        reasons.append(f"trend:{trend}")
    item_tags = {
        _norm(tag)
        for tag in (item.get("moodTags") or []) + (item.get("bestContentTypes") or [])
    }
    overlap = tags & item_tags
    if overlap:
        score += 15 * len(overlap)
        reasons.append(f"tag_match:{'/'.join(sorted(overlap))}")
    account_overlap = accounts & {_norm(tag) for tag in item.get("accountFit") or []}
    if account_overlap:
        score += 10 * len(account_overlap)
        reasons.append(f"account_match:{'/'.join(sorted(account_overlap))}")
    if item.get("nativeAudioId") or item.get("nativeAudioUrl"):
        score += 8
        reasons.append("native_locator")
    if item.get("usageCount"):
        score += min(12, int(item["usageCount"]) / 10000)
        reasons.append("usage_signal")
    snapshot = item.get("latestTrendSnapshot") or {}
    if snapshot:
        velocity = snapshot.get("velocityScore")
        if isinstance(velocity, (int, float)):
            score += max(-10, min(10, float(velocity) * 10))
            reasons.append("trend_velocity")
        saturation = snapshot.get("saturationScore")
        if isinstance(saturation, (int, float)) and saturation >= 0.85:
            score -= 8
            reasons.append("high_saturation")
    return score, reasons


def _is_fresh_catalog_record(item: dict[str, Any]) -> bool:
    trend = _norm(str(item.get("trendStatus") or "unknown"))
    if trend in STALE_TREND_STATUSES:
        return False
    expires = item.get("expiresAt")
    if isinstance(expires, str) and expires.strip():
        parsed = _parse_date(expires)
        if parsed and parsed < datetime.now(UTC):
            return False
    return trend in FRESH_TREND_STATUSES


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _get(row: dict[str, object], *keys: str) -> str | None:
    lowered = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _csv_tags(value: object | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    if isinstance(value, (tuple, set)):
        return [str(part).strip() for part in value if str(part).strip()]
    return [
        part.strip() for part in str(value).replace("|", ",").split(",") if part.strip()
    ]


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in {None, ""} else None
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value not in {None, ""} else None
    except ValueError:
        return None


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", "_").split())


def is_generic_audio_title(title: str, platform: str | None = None) -> bool:
    normalized = str(title or "").strip().lower()
    platform_norm = _norm(platform or "")
    if not normalized:
        return True
    if platform_norm == "tiktok":
        return bool(re.fullmatch(r"tiktok audio [0-9a-z_-]+", normalized))
    if platform_norm == "instagram":
        return bool(re.fullmatch(r"instagram audio [0-9a-z_-]+", normalized))
    return bool(re.fullmatch(r"(tiktok|instagram) audio [0-9a-z_-]+", normalized))


def extract_audio_signal(
    raw_json: dict[str, Any], product_type: object | None = None
) -> dict[str, str] | None:
    music = raw_json.get("musicInfo") or {}
    if music.get("audio_id"):
        title = str(music.get("song_name") or "").strip() or None
        artist = str(music.get("artist_name") or "").strip() or None
        uses_original = bool(music.get("uses_original_audio"))
        return {
            "platform": "instagram",
            "audioId": str(music["audio_id"]),
            "audioTitle": title or f"Instagram audio {music['audio_id']}",
            "artistName": artist or "",
            "usageType": "original_audio" if uses_original else "platform_sound",
            "audioVibe": _audio_vibe(
                title,
                artist,
                "original_audio" if uses_original else "platform_sound",
                product_type,
            ),
        }
    video = raw_json.get("video") or {}
    if raw_json.get("sourcePlatform") == "tiktok" and video.get("audioId"):
        audio_id = str(video["audioId"])
        author = raw_json.get("author") or {}
        artist = _first(author.get("uniqueIds")) or str(author.get("nickname") or "")
        return {
            "platform": "tiktok",
            "audioId": audio_id,
            "audioTitle": f"TikTok audio {audio_id}",
            "artistName": artist,
            "usageType": "platform_sound",
            "audioVibe": _audio_vibe(None, artist, "platform_sound", product_type),
        }
    return None


def cluster_audio_recommendations(
    items: list[dict[str, Any]], visual: str, hook: str, caption: str
) -> dict[str, object]:
    by_audio: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        signal = item.get("audioSignal")
        if not signal:
            continue
        by_audio[(signal["platform"], signal["audioId"])].append(item)
    ranked = []
    for (platform, audio_id), audio_items in by_audio.items():
        signal = audio_items[0]["audioSignal"]
        plays = [int(item.get("plays") or 0) for item in audio_items]
        measured_scores = [
            float((item.get("measuredOutcome") or {}).get("rewardScore"))
            for item in audio_items
            if isinstance(item.get("measuredOutcome"), dict)
            and isinstance(
                (item.get("measuredOutcome") or {}).get("rewardScore"), (int, float)
            )
        ]
        performance_classes = Counter(
            str(item.get("performanceClass") or "unproven") for item in audio_items
        )
        ranked.append(
            {
                "platform": platform,
                "audioId": audio_id,
                "audioTitle": signal.get("audioTitle"),
                "artistName": signal.get("artistName"),
                "usageType": signal.get("usageType"),
                "audioVibe": signal.get("audioVibe"),
                "postCount": len(audio_items),
                "totalPlays": sum(plays),
                "measuredOutcomeSamples": len(measured_scores),
                "avgMeasuredReward": round(
                    sum(measured_scores) / len(measured_scores), 4
                )
                if measured_scores
                else None,
                "performanceClass": performance_classes.most_common(1)[0][0],
                "exampleAccounts": sorted(
                    {
                        str(item.get("account") or "")
                        for item in audio_items
                        if item.get("account")
                    }
                )[:8],
                "instruction": _audio_instruction(signal, visual, hook, caption),
            }
        )
    ranked.sort(
        key=lambda item: (
            0 if item["performanceClass"] == "performed_well" else 1,
            -float(item.get("avgMeasuredReward") or 0),
            -int(item["totalPlays"]),
            -int(item["postCount"]),
            str(item["audioTitle"] or ""),
        )
    )
    fallback = fallback_audio_strategy(visual, hook, caption)
    return {
        "schema": "reference_factory.audio_recommendations.v1",
        "primaryStrategy": fallback["strategy"],
        "fallbackInstruction": fallback["instruction"],
        "nativeAudioPreferred": True,
        "recommendations": ranked[:5],
    }


def fallback_audio_strategy(visual: str, hook: str, caption: str) -> dict[str, str]:
    if visual == "tiktok_slideshow":
        return {
            "strategy": "trending_slideshow_sound",
            "instruction": "Use a current native TikTok/Instagram slideshow sound with soft pop, sped-up, or emotional photo-dump energy.",
        }
    if visual in {"mirror_selfie", "fit_check", "walking_clip"}:
        return {
            "strategy": "confidence_pop_or_runway_sound",
            "instruction": "Use a current native confident pop, runway, or soft trap sound that matches a visual-first model clip.",
        }
    if hook == "direct_response" or caption == "question_hook":
        return {
            "strategy": "light_trending_response_sound",
            "instruction": "Use a recognizable low-volume trending sound that does not fight the short question hook.",
        }
    if caption == "captionless_visual":
        return {
            "strategy": "ambient_or_soft_trending_sound",
            "instruction": "Use ambient, soft pop, or a currently trending low-distraction sound; let the visual carry the post.",
        }
    return {
        "strategy": "current_native_trending_sound",
        "instruction": "Use a current native platform sound that matches the caption mood; avoid hard-burning unknown audio into the file.",
    }


def write_audio_patterns(
    patterns: list[dict[str, Any]], output_dir: Path, limit: int
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / f"audio_patterns_top{limit}.json"
    jsonl = output_dir / f"audio_patterns_top{limit}.jsonl"
    atomic_write_text(
        manifest,
        json.dumps(
            {
                "schema": "reference_factory.audio_patterns.v1",
                "count": len(patterns),
                "patterns": patterns,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with jsonl.open("w", encoding="utf-8") as f:
        for pattern in patterns:
            f.write(json.dumps(pattern, ensure_ascii=False, sort_keys=True) + "\n")
    return {"audioPatternsPath": str(manifest), "audioPatternsJsonlPath": str(jsonl)}


def _audio_source_rows(conn: Connection, limit: int) -> list[Any]:
    return conn.execute(
        """
        SELECT pp.*, rp.visual_format, rp.hook_type, rp.caption_archetype,
               ROW_NUMBER() OVER (
                 ORDER BY COALESCE(pp.video_play_count, pp.video_view_count, 0) DESC,
                          COALESCE(pp.video_view_count, 0) DESC,
                          COALESCE(pp.likes_count, 0) DESC
               ) AS rank
        FROM public_posts pp
        LEFT JOIN reference_patterns rp ON rp.public_post_id = pp.id
        WHERE pp.video_play_count IS NOT NULL OR pp.video_view_count IS NOT NULL
        ORDER BY COALESCE(pp.video_play_count, pp.video_view_count, 0) DESC,
                 COALESCE(pp.video_view_count, 0) DESC,
                 COALESCE(pp.likes_count, 0) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def _audio_group_to_pattern(
    key: tuple[str, str, str, str, str], items: list[dict[str, Any]], timestamp: str
) -> dict[str, Any]:
    platform, audio_id, visual, hook, caption = key
    signal = items[0]["signal"]
    plays = [int(item["plays"] or 0) for item in items]
    accounts = Counter(str(item.get("account") or "_unknown") for item in items)
    examples = sorted(
        items,
        key=lambda item: (-int(item["plays"] or 0), int(item.get("rank") or 999999)),
    )[:8]
    recommendation = {
        "audioStrategy": signal.get("audioVibe")
        or fallback_audio_strategy(visual, hook, caption)["strategy"],
        "nativeAudioPreferred": True,
        "instruction": _audio_instruction(signal, visual, hook, caption),
        "fallback": fallback_audio_strategy(visual, hook, caption)["instruction"],
    }
    return {
        "schema": "reference_factory.audio_pattern.v1",
        "id": stable_id(
            "audio_pattern", platform, audio_id, visual, hook, caption, timestamp
        ),
        "platform": platform,
        "audioId": audio_id,
        "audioTitle": signal.get("audioTitle"),
        "artistName": signal.get("artistName"),
        "usageType": signal.get("usageType"),
        "visualFormat": visual,
        "hookType": hook,
        "captionArchetype": caption,
        "postCount": len(items),
        "totalPlays": sum(plays),
        "medianPlays": int(statistics.median(plays)) if plays else 0,
        "topAccounts": [account for account, _ in accounts.most_common(8)],
        "examplePosts": [
            {
                "rank": item.get("rank"),
                "publicPostId": item.get("publicPostId"),
                "account": item.get("account"),
                "url": item.get("url"),
                "plays": item.get("plays"),
                "caption": item.get("caption"),
            }
            for item in examples
        ],
        "recommendation": recommendation,
    }


def _audio_instruction(
    signal: dict[str, Any], visual: str, hook: str, caption: str
) -> str:
    title = signal.get("audioTitle")
    artist = signal.get("artistName")
    fallback = fallback_audio_strategy(visual, hook, caption)["instruction"]
    if title and not str(title).startswith(("TikTok audio", "Instagram audio")):
        byline = f" by {artist}" if artist else ""
        return f"Try native platform audio similar to '{title}'{byline}; if unavailable, {fallback[0].lower() + fallback[1:]}"
    return fallback


def _audio_vibe(
    title: str | None, artist: str | None, usage_type: str, product_type: object | None
) -> str:
    blob = " ".join([title or "", artist or "", str(product_type or "")]).lower()
    if usage_type == "original_audio":
        return "original_creator_audio"
    if "slideshow" in blob or "tiktok" in blob:
        return "trending_slideshow_sound"
    if "sped" in blob or "speed" in blob:
        return "sped_up_pop"
    if "waltz" in blob or "flowers" in blob or "classical" in blob:
        return "soft_classical_or_dreamy"
    if "pop" in blob or "pretty" in blob or "girl" in blob:
        return "soft_pop"
    return "current_native_trending_sound"


def _first(values: object) -> str | None:
    if isinstance(values, list) and values:
        return str(values[0])
    return None
