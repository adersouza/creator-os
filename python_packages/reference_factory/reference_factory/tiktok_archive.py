from __future__ import annotations

import base64
import gzip
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .db import json_dump
from .identity import stable_id, stable_reference_id
from .public_metrics import top_public_posts, write_top_public_posts
from .scan import timestamp_from_stat
from .timeutil import now_iso


def import_tiktok_archive(
    conn: Connection,
    source_root: Path,
    top_limit: int = 300,
    treat_as_slideshow: bool = True,
    output_dir: Path | None = None,
) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    data_root = source_root / "data"
    appdata = data_root / ".appdata"
    authors = _load_archive_json(appdata / "db_authors.js")
    videos = _load_archive_json(appdata / "db_videos.js")
    texts = _load_archive_json(appdata / "db_texts.js")
    timestamp = now_iso()
    following_root = data_root / "Following"
    inserted = 0
    updated = 0
    imported_posts = 0
    captions = 0
    covers = 0
    accounts: Counter[str] = Counter()

    for video_path in sorted(following_root.glob("*/videos/*.mp4")):
        try:
            stat = video_path.stat()
        except OSError:
            continue
        video_id = video_path.stem
        video = videos.get(video_id) or {}
        author_id = str(video.get("authorId") or video_path.parent.parent.name)
        author = authors.get(author_id) or {}
        username = _author_username(author, author_id)
        caption = str(texts.get(video_id) or "").strip()
        if caption:
            captions += 1
        cover_path = video_path.parent.parent / "covers" / f"{video_id}.jpg"
        cover_value = str(cover_path) if cover_path.exists() else None
        if cover_value:
            covers += 1
        generated_reference_id = stable_reference_id(video_path, stat.st_size)
        existing = conn.execute(
            """
            SELECT reference_id
            FROM source_files
            WHERE reference_id = ? OR path = ?
            ORDER BY CASE WHEN reference_id = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (generated_reference_id, str(video_path), generated_reference_id),
        ).fetchone()
        reference_id = existing["reference_id"] if existing else generated_reference_id
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id, path, account, file_name, extension, kind,
              size_bytes, mtime, path_hash, content_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'mp4', 'video', ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(reference_id) DO UPDATE SET
              path = excluded.path,
              account = excluded.account,
              file_name = excluded.file_name,
              extension = excluded.extension,
              kind = excluded.kind,
              size_bytes = excluded.size_bytes,
              mtime = excluded.mtime,
              updated_at = excluded.updated_at
            """,
            (
                reference_id,
                str(video_path),
                username,
                video_path.name,
                stat.st_size,
                timestamp_from_stat(stat.st_mtime),
                reference_id.removeprefix("ref_"),
                timestamp,
                timestamp,
            ),
        )
        if existing:
            updated += 1
        else:
            inserted += 1
        accounts[username] += 1
        play_count = _int_or_none(video.get("playCount"))
        public_post_id = stable_id("public_post", "tiktok", video_id)
        raw_json = {
            "sourcePlatform": "tiktok",
            "sourceFormat": "slideshow" if treat_as_slideshow else "video",
            "authorId": author_id,
            "videoId": video_id,
            "author": author,
            "video": video,
            "caption": caption,
            "coverPath": cover_value,
            "archiveRoot": str(source_root),
        }
        conn.execute(
            """
            INSERT INTO public_posts (
              id, owner_username, short_code, url, timestamp, product_type, post_type,
              caption, video_view_count, video_play_count, likes_count, comments_count,
              display_url, video_url, match_type, reference_id, local_path, raw_json, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 'exact_media_id', ?, ?, ?, ?)
            ON CONFLICT(short_code) DO UPDATE SET
              owner_username = excluded.owner_username,
              url = excluded.url,
              timestamp = excluded.timestamp,
              product_type = excluded.product_type,
              post_type = excluded.post_type,
              caption = excluded.caption,
              video_view_count = excluded.video_view_count,
              video_play_count = excluded.video_play_count,
              likes_count = excluded.likes_count,
              display_url = excluded.display_url,
              video_url = excluded.video_url,
              match_type = excluded.match_type,
              reference_id = excluded.reference_id,
              local_path = excluded.local_path,
              raw_json = excluded.raw_json,
              imported_at = excluded.imported_at
            """,
            (
                public_post_id,
                username,
                f"tiktok_{video_id}",
                f"https://www.tiktok.com/@{username}/video/{video_id}",
                _timestamp_from_epoch(video.get("createTime")),
                "tiktok_slideshow_reference" if treat_as_slideshow else "tiktok_reference",
                "TikTok Slideshow" if treat_as_slideshow else "TikTok Video",
                caption,
                play_count,
                play_count,
                _int_or_none(video.get("diggCount")),
                cover_value,
                str(video_path),
                reference_id,
                str(video_path),
                json_dump(raw_json),
                timestamp,
            ),
        )
        imported_posts += 1
    conn.commit()
    top = top_public_posts(conn, top_limit)
    paths: dict[str, str] = {}
    if output_dir:
        paths = write_top_public_posts(top, output_dir)
    return {
        "schema": "reference_factory.import_tiktok_archive.v1",
        "sourceRoot": str(source_root),
        "videosImported": imported_posts,
        "sourceFilesInserted": inserted,
        "sourceFilesUpdated": updated,
        "authors": len(accounts),
        "captioned": captions,
        "covers": covers,
        "treatAsSlideshow": treat_as_slideshow,
        "topLimit": top_limit,
        "topPosts": len(top["items"]),
        "topAccounts": [{"account": account, "videos": count} for account, count in accounts.most_common(20)],
        **paths,
    }


def _load_archive_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'base64\s*=\s*"([^"]+)"', text)
    if not match:
        raise ValueError(f"Could not find base64 payload in {path}")
    payload = gzip.decompress(base64.b64decode(match.group(1))).decode("utf-8")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"Expected object payload in {path}")
    return value


def _author_username(author: dict[str, Any], fallback: str) -> str:
    unique_ids = author.get("uniqueIds") or []
    if unique_ids:
        return str(unique_ids[0])
    nickname = str(author.get("nickname") or "").strip()
    return nickname or fallback


def _timestamp_from_epoch(value: object) -> str | None:
    seconds = _int_or_none(value)
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def _int_or_none(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
