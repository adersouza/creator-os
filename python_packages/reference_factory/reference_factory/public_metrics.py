from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .db import json_dump, json_load
from .identity import stable_id, text_hash
from .timeutil import now_iso


def import_apify_metrics(
    conn: Connection,
    input_paths: list[Path],
    top_limit: int = 300,
    output_dir: Path | None = None,
) -> dict[str, object]:
    posts = _load_unique_posts(input_paths)
    local_by_media = _local_media_index(conn)
    imported = 0
    exact_matches = 0
    for post in posts:
        owner = post.get("ownerUsername")
        apify_id = str(post.get("id") or "")
        exact = local_by_media.get((owner, apify_id)) if apify_id else None
        match_type = "exact_media_id" if exact else "external_only"
        if exact:
            exact_matches += 1
        public_post_id = stable_id("public_post", post.get("shortCode") or post.get("url") or apify_id)
        conn.execute(
            """
            INSERT INTO public_posts (
              id, owner_username, short_code, url, timestamp, product_type, post_type,
              caption, video_view_count, video_play_count, likes_count, comments_count,
              display_url, video_url, match_type, reference_id, local_path, raw_json, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              comments_count = excluded.comments_count,
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
                owner,
                post.get("shortCode"),
                post.get("url"),
                post.get("timestamp"),
                post.get("productType"),
                post.get("type"),
                post.get("caption") or "",
                _int_or_none(post.get("videoViewCount")),
                _int_or_none(post.get("videoPlayCount")),
                _int_or_none(post.get("likesCount")),
                _int_or_none(post.get("commentsCount")),
                post.get("displayUrl"),
                post.get("videoUrl"),
                match_type,
                exact["referenceId"] if exact else None,
                exact["path"] if exact else None,
                json_dump(post),
                now_iso(),
            ),
        )
        imported += 1
    conn.commit()
    top = top_public_posts(conn, top_limit)
    if output_dir:
        write_top_public_posts(top, output_dir)
    return {
        "schema": "reference_factory.import_apify_metrics.v1",
        "inputPaths": [str(path) for path in input_paths],
        "uniqueMetricPosts": len(posts),
        "imported": imported,
        "exactLocalMatches": exact_matches,
        "externalOnly": imported - exact_matches,
        "topLimit": top_limit,
        "topPosts": len(top["items"]),
    }


def top_public_posts(conn: Connection, limit: int = 300) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT *
        FROM public_posts
        WHERE video_play_count IS NOT NULL OR video_view_count IS NOT NULL
        ORDER BY COALESCE(video_play_count, video_view_count, 0) DESC,
                 COALESCE(video_view_count, 0) DESC,
                 COALESCE(likes_count, 0) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {
        "schema": "reference_factory.top_public_posts.v1",
        "limit": limit,
        "items": [_public_post_row(row, idx) for idx, row in enumerate(rows, 1)],
    }


def generate_prompt_cards(conn: Connection, limit: int = 50, output_dir: Path | None = None) -> dict[str, object]:
    top = top_public_posts(conn, limit)
    cards = []
    timestamp = now_iso()
    conn.execute("DELETE FROM prompt_cards")
    for item in top["items"]:
        card = _prompt_card_from_post(item)
        card_id = stable_id("prompt_card", item["id"])
        conn.execute(
            """
            INSERT INTO prompt_cards (id, public_post_id, rank, prompt_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (card_id, item["id"], item["rank"], json_dump(card), timestamp),
        )
        cards.append(card)
    conn.commit()
    paths: dict[str, str] = {}
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        jsonl = output_dir / f"prompt_cards_top{limit}.jsonl"
        manifest = output_dir / f"prompt_cards_top{limit}.json"
        with jsonl.open("w", encoding="utf-8") as f:
            for card in cards:
                f.write(json.dumps(card, ensure_ascii=False, sort_keys=True) + "\n")
        manifest.write_text(json.dumps({"schema": "reference_factory.prompt_cards.v1", "cards": cards}, indent=2, ensure_ascii=False) + "\n")
        paths = {"jsonlPath": str(jsonl), "manifestPath": str(manifest)}
    return {
        "schema": "reference_factory.generate_prompt_cards.v1",
        "count": len(cards),
        **paths,
        "cards": cards[:10],
    }


def export_learning_set(
    conn: Connection,
    limit: int = 300,
    output_dir: Path | None = None,
    copy_media: bool = False,
) -> dict[str, object]:
    output_dir = output_dir or Path("learning")
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = output_dir / "contentforge_references"
    if copy_media:
        media_dir.mkdir(parents=True, exist_ok=True)
    top = top_public_posts(conn, limit)
    rows = []
    prompt_cards = []
    for item in top["items"]:
        local_path = item.get("localPath")
        contentforge_name = None
        contentforge_path = None
        if local_path:
            source_path = Path(str(local_path))
            contentforge_name = f"{int(item['rank']):03d}_{item['ownerUsername']}_{item['shortCode']}{source_path.suffix}"
            contentforge_path = str(media_dir / contentforge_name)
            if copy_media and source_path.exists():
                shutil.copy2(source_path, contentforge_path)
        card = _prompt_card_from_post(item)
        prompt_cards.append(card)
        rows.append(
            {
                "rank": item["rank"],
                "publicPostId": item["id"],
                "ownerUsername": item["ownerUsername"],
                "shortCode": item["shortCode"],
                "url": item["url"],
                "plays": item["videoPlayCount"],
                "views": item["videoViewCount"],
                "likes": item["likesCount"],
                "comments": item["commentsCount"],
                "caption": item["caption"],
                "matchType": item["matchType"],
                "referenceId": item["referenceId"],
                "localPath": local_path,
                "contentforgeReferenceName": contentforge_name,
                "contentforgeReferencePath": contentforge_path,
                "promptCard": card,
            }
        )
    manifest = {
        "schema": "reference_factory.learning_set.v1",
        "limit": limit,
        "count": len(rows),
        "exactLocalMatches": sum(1 for row in rows if row["matchType"] == "exact_media_id"),
        "externalOnly": sum(1 for row in rows if row["matchType"] == "external_only"),
        "copyMedia": copy_media,
        "contentforgeReferenceDir": str(media_dir),
        "contentforgeReferenceFiles": [
            row["contentforgeReferenceName"]
            for row in rows
            if row["contentforgeReferenceName"]
        ],
        "items": rows,
    }
    manifest_path = output_dir / f"learning_set_top{limit}.json"
    jsonl_path = output_dir / f"learning_set_top{limit}.jsonl"
    prompt_path = output_dir / f"prompt_cards_top{limit}.jsonl"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with prompt_path.open("w", encoding="utf-8") as f:
        for card in prompt_cards:
            f.write(json.dumps(card, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "schema": "reference_factory.export_learning_set.v1",
        "count": len(rows),
        "exactLocalMatches": manifest["exactLocalMatches"],
        "externalOnly": manifest["externalOnly"],
        "manifestPath": str(manifest_path),
        "jsonlPath": str(jsonl_path),
        "promptCardsPath": str(prompt_path),
        "contentforgeReferenceDir": str(media_dir),
        "copiedMedia": copy_media,
    }


def write_top_public_posts(top: dict[str, object], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl = output_dir / "top_300_public_posts_matched.jsonl"
    summary = output_dir / "top_300_public_posts_matched_summary.json"
    items = top["items"]
    with jsonl.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    summary.write_text(
        json.dumps(
            {
                "schema": "reference_factory.top_public_posts_matched_summary.v1",
                "count": len(items),
                "exactLocalMatches": sum(1 for item in items if item["matchType"] == "exact_media_id"),
                "externalOnly": sum(1 for item in items if item["matchType"] == "external_only"),
                "top20": items[:20],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return {"jsonlPath": str(jsonl), "summaryPath": str(summary)}


def _load_unique_posts(input_paths: list[Path]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for path in input_paths:
        for item in json.loads(path.read_text()):
            if item.get("videoPlayCount") is None and item.get("videoViewCount") is None:
                continue
            key = str(item.get("shortCode") or item.get("url") or item.get("id"))
            score = item.get("videoPlayCount") or item.get("videoViewCount") or 0
            old = by_key.get(key)
            old_score = (old or {}).get("videoPlayCount") or (old or {}).get("videoViewCount") or 0
            if old is None or score >= old_score:
                by_key[key] = item
    return sorted(
        by_key.values(),
        key=lambda item: (item.get("videoPlayCount") or item.get("videoViewCount") or 0),
        reverse=True,
    )


def _local_media_index(conn: Connection) -> dict[tuple[str | None, str], dict[str, str]]:
    rows = conn.execute(
        "SELECT reference_id, account, file_name, path FROM source_files WHERE kind = 'video'"
    ).fetchall()
    index: dict[tuple[str | None, str], dict[str, str]] = {}
    for row in rows:
        nums = [part for part in Path(row["file_name"]).stem.split("_") if re.fullmatch(r"\d{10,}", part)]
        media_id = nums[1] if len(nums) >= 2 else None
        if media_id:
            index[(row["account"], media_id)] = {
                "referenceId": row["reference_id"],
                "path": row["path"],
                "fileName": row["file_name"],
            }
    return index


def _public_post_row(row, rank: int) -> dict[str, object]:
    raw_json = json_load(row["raw_json"], {})
    return {
        "rank": rank,
        "id": row["id"],
        "ownerUsername": row["owner_username"],
        "shortCode": row["short_code"],
        "url": row["url"],
        "timestamp": row["timestamp"],
        "productType": row["product_type"],
        "type": row["post_type"],
        "caption": row["caption"],
        "videoViewCount": row["video_view_count"],
        "videoPlayCount": row["video_play_count"],
        "likesCount": row["likes_count"],
        "commentsCount": row["comments_count"],
        "displayUrl": row["display_url"],
        "videoUrl": row["video_url"],
        "matchType": row["match_type"],
        "referenceId": row["reference_id"],
        "localPath": row["local_path"],
        "rawJson": _compact_raw_json(raw_json),
    }


def _compact_raw_json(raw_json: dict[str, Any]) -> dict[str, object]:
    return {
        key: raw_json.get(key)
        for key in ["sourcePlatform", "sourceFormat", "authorId", "videoId", "coverPath"]
        if raw_json.get(key) is not None
    }


def _prompt_card_from_post(item: dict[str, object]) -> dict[str, object]:
    caption = str(item.get("caption") or "").strip()
    archetype = _caption_archetype(caption)
    return {
        "schema": "reference_factory.prompt_card.v1",
        "source": {
            "publicPostId": item["id"],
            "rank": item["rank"],
            "account": item["ownerUsername"],
            "url": item["url"],
            "plays": item["videoPlayCount"],
            "views": item["videoViewCount"],
            "likes": item["likesCount"],
            "comments": item["commentsCount"],
            "matchType": item["matchType"],
            "referenceId": item["referenceId"],
        },
        "learnedPattern": {
            "captionArchetype": archetype,
            "captionLength": len(caption),
            "usesQuestion": "?" in caption,
            "usesEmoji": bool(re.search(r"[^\w\s#.,!?'\"]", caption)),
            "hasHashtags": "#" in caption,
            "structureNotes": _structure_notes(archetype),
        },
        "generationPrompt": {
            "format": "vertical Instagram Reel",
            "goal": "create an original reel inspired by the winning structure, not a copy",
            "visual": _visual_prompt(archetype),
            "captionOverlay": _caption_overlay_prompt(archetype),
            "camera": "phone-shot, natural movement, close framing, social reel pacing",
            "durationSeconds": "6-12",
            "negativePrompt": "no nudity, no explicit sexual acts, no copied captions, no logos, no watermark, no underage appearance",
        },
        "klingStyleJson": {
            "scene": _visual_prompt(archetype),
            "camera": "handheld vertical phone video, subtle motion, tight composition",
            "action": "one clear visual beat with an immediate hook in the first second",
            "caption_overlay": _caption_overlay_prompt(archetype),
            "style": "high-performing Instagram Reel reference, original variation",
            "duration": "6-12 seconds",
            "constraints": [
                "original content only",
                "preserve platform-safe framing",
                "avoid direct caption copying",
                "keep subject adult-presenting",
            ],
        },
    }


def _caption_archetype(caption: str) -> str:
    lowered = caption.lower().strip()
    if not caption:
        return "captionless_visual"
    if len(caption) <= 4 or all(not ch.isalnum() for ch in caption):
        return "emoji_or_minimal_bait"
    if lowered.startswith("pov"):
        return "pov_scenario"
    if "?" in caption:
        return "question_hook"
    if lowered.startswith(("when ", "me when", "how it feels")):
        return "relatable_scenario"
    if "#" in caption:
        return "hashtag_context_caption"
    return "short_tease"


def _structure_notes(archetype: str) -> str:
    return {
        "captionless_visual": "The visual has to carry the hook without text.",
        "emoji_or_minimal_bait": "Very short caption relies on curiosity and visual context.",
        "pov_scenario": "Caption frames the viewer inside a simple scenario.",
        "question_hook": "Caption invites direct response or self-identification.",
        "relatable_scenario": "Caption sets up a familiar situation before the visual payoff.",
        "hashtag_context_caption": "Caption uses broad context and discoverability tags.",
        "short_tease": "Caption is brief, suggestive, and leaves context open.",
    }[archetype]


def _visual_prompt(archetype: str) -> str:
    if archetype == "captionless_visual":
        return "strong single-subject vertical reel with a clear pose, expression, or movement hook"
    if archetype == "pov_scenario":
        return "POV-style setup with subject reacting naturally to an implied viewer situation"
    if archetype == "question_hook":
        return "direct-to-camera visual designed to make viewers answer the caption"
    return "simple high-retention creator reel with one obvious visual hook and minimal clutter"


def _caption_overlay_prompt(archetype: str) -> str:
    if archetype == "captionless_visual":
        return "optional minimal overlay; prioritize visual hook"
    if archetype == "emoji_or_minimal_bait":
        return "one to three words or emoji-style minimal bait, original wording"
    if archetype == "pov_scenario":
        return "POV: [original scenario tailored to the model/persona]"
    if archetype == "question_hook":
        return "short original question that invites comments"
    return "short original tease caption, centered and readable"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
