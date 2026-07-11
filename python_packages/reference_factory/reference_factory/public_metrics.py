from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .caption_archetypes import caption_archetype
from .db import json_dump, json_load
from .identity import stable_id
from .timeutil import now_iso

DEFAULT_REFERENCE_ACCOUNT_CAP = 60
DEFAULT_CAPTION_SHARE = 0.5


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
        public_post_id = stable_id(
            "public_post", post.get("shortCode") or post.get("url") or apify_id
        )
        conn.execute(
            """
            INSERT INTO public_posts (
              id, owner_username, short_code, url, timestamp, product_type, post_type,
              caption, video_view_count, video_play_count, likes_count, comments_count,
              owner_follower_count, public_rate_score, public_follower_engagement_rate,
              display_url, video_url, match_type,
              reference_id, local_path, raw_json, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              owner_follower_count = excluded.owner_follower_count,
              public_rate_score = excluded.public_rate_score,
              public_follower_engagement_rate = excluded.public_follower_engagement_rate,
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
                _follower_count(post),
                _public_rate_score(post),
                _public_follower_engagement_rate(post),
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


def backfill_follower_metrics(
    conn: Connection,
    *,
    apply: bool = False,
) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT id, owner_username, video_view_count, video_play_count,
               likes_count, comments_count, owner_follower_count,
               public_rate_score, public_follower_engagement_rate, raw_json
        FROM public_posts
        ORDER BY id
        """
    ).fetchall()
    updates: list[tuple[int, float | None, float, str]] = []
    accounts: set[str] = set()
    for row in rows:
        raw_json = json_load(row["raw_json"], {})
        followers = _follower_count(raw_json)
        if not followers:
            continue
        accounts.add(str(row["owner_username"] or "_unknown"))
        public_rate = _rate_from_counts(
            followers,
            row["video_play_count"] or row["video_view_count"],
        )
        follower_engagement = _engagement_rate_from_counts(
            followers,
            row["likes_count"],
            row["comments_count"],
        )
        current = (
            _int_or_none(row["owner_follower_count"]),
            _float_or_none(row["public_rate_score"]),
            _float_or_none(row["public_follower_engagement_rate"]),
        )
        desired = (followers, public_rate, follower_engagement)
        if current != desired:
            updates.append((*desired, str(row["id"])))

    if apply and updates:
        conn.executemany(
            """
            UPDATE public_posts
            SET owner_follower_count = ?,
                public_rate_score = ?,
                public_follower_engagement_rate = ?
            WHERE id = ?
            """,
            updates,
        )
        conn.commit()

    return {
        "schema": "reference_factory.backfill_follower_metrics.v1",
        "apply": apply,
        "publicPosts": len(rows),
        "rowsWithFollowerSource": sum(
            1 for row in rows if _follower_count(json_load(row["raw_json"], {}))
        ),
        "accountsWithFollowerSource": len(accounts),
        "rowsChanged": len(updates),
    }


def top_public_posts(
    conn: Connection,
    limit: int = 300,
    *,
    account_cap: int | None = None,
    caption_share: float | None = None,
    strict_balance: bool = False,
) -> dict[str, object]:
    rows = conn.execute(
        """
        WITH prompt_outcomes AS (
          SELECT reference_id,
                 MAX(outcome_reward_score) AS measured_outcome_score,
                 MAX(outcome_confidence) AS measured_outcome_confidence,
                 SUM(outcome_sample_count) AS measured_outcome_sample_count,
                 MAX(outcome_updated_at) AS measured_outcome_updated_at
          FROM generated_video_prompts
          WHERE outcome_reward_score IS NOT NULL
          GROUP BY reference_id
        )
        SELECT public_posts.*,
               (SELECT COUNT(*) FROM caption_patterns cp
                WHERE cp.reference_id = public_posts.reference_id) AS caption_pattern_count,
               prompt_outcomes.measured_outcome_score,
               prompt_outcomes.measured_outcome_confidence,
               prompt_outcomes.measured_outcome_sample_count,
               prompt_outcomes.measured_outcome_updated_at
        FROM public_posts
        LEFT JOIN prompt_outcomes ON prompt_outcomes.reference_id = public_posts.reference_id
        WHERE video_play_count IS NOT NULL OR video_view_count IS NOT NULL
        """,
    ).fetchall()
    ranked = sorted(rows, key=_public_post_sort_key, reverse=True)
    selected, selection = _balanced_public_rows(
        ranked,
        limit=max(0, int(limit)),
        account_cap=_reference_account_cap(account_cap),
        caption_share=_reference_caption_share(caption_share),
        strict_balance=strict_balance,
    )
    return {
        "schema": "reference_factory.top_public_posts.v1",
        "limit": limit,
        "selection": selection,
        "items": [_public_post_row(row, idx) for idx, row in enumerate(selected, 1)],
    }


def generate_prompt_cards(
    conn: Connection, limit: int = 50, output_dir: Path | None = None
) -> dict[str, object]:
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
        atomic_write_text(
            manifest,
            json.dumps(
                {"schema": "reference_factory.prompt_cards.v1", "cards": cards},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
        )
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
        "exactLocalMatches": sum(
            1 for row in rows if row["matchType"] == "exact_media_id"
        ),
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
    atomic_write_text(
        manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
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
    atomic_write_text(
        summary,
        json.dumps(
            {
                "schema": "reference_factory.top_public_posts_matched_summary.v1",
                "count": len(items),
                "exactLocalMatches": sum(
                    1 for item in items if item["matchType"] == "exact_media_id"
                ),
                "externalOnly": sum(
                    1 for item in items if item["matchType"] == "external_only"
                ),
                "top20": items[:20],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )
    return {"jsonlPath": str(jsonl), "summaryPath": str(summary)}


def _load_unique_posts(input_paths: list[Path]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for path in input_paths:
        for item in json.loads(path.read_text()):
            if (
                item.get("videoPlayCount") is None
                and item.get("videoViewCount") is None
            ):
                continue
            key = str(item.get("shortCode") or item.get("url") or item.get("id"))
            score = item.get("videoPlayCount") or item.get("videoViewCount") or 0
            old = by_key.get(key)
            old_score = (
                (old or {}).get("videoPlayCount")
                or (old or {}).get("videoViewCount")
                or 0
            )
            if old is None or score >= old_score:
                by_key[key] = item
    return sorted(
        by_key.values(),
        key=lambda item: item.get("videoPlayCount") or item.get("videoViewCount") or 0,
        reverse=True,
    )


def _local_media_index(
    conn: Connection,
) -> dict[tuple[str | None, str], dict[str, str]]:
    rows = conn.execute(
        "SELECT reference_id, account, file_name, path FROM source_files WHERE kind = 'video'"
    ).fetchall()
    index: dict[tuple[str | None, str], dict[str, str]] = {}
    for row in rows:
        nums = [
            part
            for part in Path(row["file_name"]).stem.split("_")
            if re.fullmatch(r"\d{10,}", part)
        ]
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
        "ownerFollowerCount": row["owner_follower_count"],
        "publicRateScore": row["public_rate_score"],
        "publicFollowerEngagementRate": row["public_follower_engagement_rate"],
        "publicEngagementRecencyScore": _public_engagement_recency_score(row),
        "referenceSignalType": _reference_signal_bucket(row),
        "displayUrl": row["display_url"],
        "videoUrl": row["video_url"],
        "matchType": row["match_type"],
        "referenceId": row["reference_id"],
        "localPath": row["local_path"],
        "rawJson": _compact_raw_json(raw_json),
        "measuredOutcome": _measured_outcome(row),
    }


def _measured_outcome(row) -> dict[str, object] | None:
    reward_score = row["measured_outcome_score"]
    if reward_score is None:
        return None
    return {
        "schema": "reference_factory.prompt_outcome_summary.v1",
        "rewardScore": reward_score,
        "confidence": row["measured_outcome_confidence"],
        "sampleCount": row["measured_outcome_sample_count"] or 0,
        "updatedAt": row["measured_outcome_updated_at"],
        "source": "generated_video_prompts",
    }


def _compact_raw_json(raw_json: dict[str, Any]) -> dict[str, object]:
    return {
        key: raw_json.get(key)
        for key in [
            "sourcePlatform",
            "sourceFormat",
            "authorId",
            "videoId",
            "coverPath",
        ]
        if raw_json.get(key) is not None
    }


def _follower_count(post: dict[str, Any]) -> int | None:
    for key in (
        "ownerFollowersCount",
        "followersCount",
        "followerCount",
        "owner_follower_count",
        "followers",
    ):
        value = _int_or_none(post.get(key))
        if value:
            return value
    for container_key in ("owner", "author", "user"):
        container = post.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in (
            "ownerFollowersCount",
            "followersCount",
            "followerCount",
            "owner_follower_count",
            "followers_count",
            "followers",
        ):
            value = _int_or_none(container.get(key))
            if value:
                return value
    return None


def _public_rate_score(post: dict[str, Any]) -> float | None:
    followers = _follower_count(post)
    if not followers:
        return None
    exposure = (
        _int_or_none(post.get("videoPlayCount"))
        or _int_or_none(post.get("videoViewCount"))
        or 0
    )
    return _rate_from_counts(followers, exposure)


def _public_follower_engagement_rate(post: dict[str, Any]) -> float | None:
    followers = _follower_count(post)
    if not followers:
        return None
    return _engagement_rate_from_counts(
        followers,
        post.get("likesCount"),
        post.get("commentsCount"),
    )


def _rate_from_counts(followers: int, exposure: object) -> float | None:
    exposure_count = _int_or_none(exposure) or 0
    if exposure_count <= 0:
        return None
    return round(exposure_count / followers, 6)


def _engagement_rate_from_counts(
    followers: int,
    likes: object,
    comments: object,
) -> float:
    engagements = (_int_or_none(likes) or 0) + (_int_or_none(comments) or 0)
    return round(engagements / followers, 8)


def _float_or_none(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _public_post_sort_key(
    row,
) -> tuple[float, float, float, float, float, float, float, int, int, int]:
    follower_engagement = row["public_follower_engagement_rate"]
    return (
        1.0 if row["measured_outcome_score"] is not None else 0.0,
        float(row["measured_outcome_score"] or 0),
        float(row["measured_outcome_confidence"] or 0),
        1.0 if follower_engagement is not None else 0.0,
        _follower_engagement_recency_score(row),
        float(row["public_rate_score"] or 0),
        _public_engagement_recency_score(row),
        int(row["video_play_count"] or row["video_view_count"] or 0),
        int(row["video_view_count"] or 0),
        int(row["likes_count"] or 0),
    )


def _follower_engagement_recency_score(row) -> float:
    rate = row["public_follower_engagement_rate"]
    if rate is None:
        return 0.0
    return round(float(rate) * _recency_weight(row["timestamp"]), 8)


def _reference_account_cap(value: int | None) -> int:
    if value is None:
        value = _int_or_none(os.environ.get("REFERENCE_BANK_ACCOUNT_CAP"))
    return max(1, int(value or DEFAULT_REFERENCE_ACCOUNT_CAP))


def _reference_caption_share(value: float | None) -> float:
    if value is None:
        try:
            value = float(os.environ.get("REFERENCE_BANK_CAPTION_SHARE", ""))
        except ValueError:
            value = None
    if value is None:
        value = DEFAULT_CAPTION_SHARE
    return min(1.0, max(0.0, float(value)))


def _reference_signal_bucket(row: Any) -> str:
    return (
        "caption_driven"
        if int(row["caption_pattern_count"] or 0) > 0
        else "visual_driven"
    )


def _balanced_public_rows(
    rows: list[Any],
    *,
    limit: int,
    account_cap: int,
    caption_share: float,
    strict_balance: bool = False,
) -> tuple[list[Any], dict[str, Any]]:
    caption_goal = round(limit * caption_share)
    visual_goal = max(0, limit - caption_goal)
    selected: list[Any] = []
    selected_ids: set[str] = set()
    account_counts: Counter[str] = Counter()
    skipped_due_account_cap = 0

    def add(candidates: list[Any], goal: int | None) -> None:
        nonlocal skipped_due_account_cap
        added = 0
        for row in candidates:
            if len(selected) >= limit or (goal is not None and added >= goal):
                return
            row_id = str(row["id"])
            if row_id in selected_ids:
                continue
            account = str(row["owner_username"] or "_unknown")
            if account_counts[account] >= account_cap:
                skipped_due_account_cap += 1
                continue
            selected.append(row)
            selected_ids.add(row_id)
            account_counts[account] += 1
            added += 1

    add(
        [row for row in rows if _reference_signal_bucket(row) == "caption_driven"],
        caption_goal,
    )
    add(
        [row for row in rows if _reference_signal_bucket(row) == "visual_driven"],
        visual_goal,
    )
    if not strict_balance:
        add(rows, None)
    counts = Counter(_reference_signal_bucket(row) for row in selected)
    return selected, {
        "accountCap": account_cap,
        "captionShareTarget": caption_share,
        "strictBalance": strict_balance,
        "captionDrivenGoal": caption_goal,
        "visualDrivenGoal": visual_goal,
        "captionDrivenSelected": counts["caption_driven"],
        "visualDrivenSelected": counts["visual_driven"],
        "skippedDueAccountCap": skipped_due_account_cap,
        "accountCounts": dict(sorted(account_counts.items())),
    }


def _public_engagement_recency_score(row) -> float:
    exposure = max(int(row["video_play_count"] or row["video_view_count"] or 0), 1)
    engagements = int(row["likes_count"] or 0) + int(row["comments_count"] or 0)
    engagement_rate = engagements / exposure
    recency = _recency_weight(row["timestamp"])
    return round(engagement_rate * recency, 8)


def _recency_weight(timestamp: str | None) -> float:
    if not timestamp:
        return 0.5
    value = str(timestamp).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return 0.5
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    age_days = max(0.0, (datetime.now(UTC) - dt.astimezone(UTC)).days)
    return 1.0 / (1.0 + (age_days / 90.0))


def _prompt_card_from_post(item: dict[str, object]) -> dict[str, object]:
    caption = str(item.get("caption") or "").strip()
    archetype = caption_archetype(caption)
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
                "keep subject 19 years old",
            ],
        },
    }


def _structure_notes(archetype: str) -> str:
    return {
        "captionless_visual": "The visual has to carry the hook without text.",
        "challenge_or_puzzle": "Caption challenges the viewer to complete or solve a simple prompt.",
        "pov_scenario": "Caption frames the viewer inside a simple scenario.",
        "question_hook": "Caption invites direct response or self-identification.",
        "relatable_scenario": "Caption sets up a familiar situation before the visual payoff.",
        "choice_bait": "Caption forces a quick choice that encourages comments.",
        "minimal_bait": "Very short caption relies on curiosity and visual context.",
        "hashtag_context": "Caption uses broad context and discoverability tags.",
        "cta_bait": "Caption uses a direct call to action to trigger response.",
        "short_meme_caption": "Caption is brief, suggestive, and leaves context open.",
    }.get(
        archetype,
        "Caption structure is broad; keep the variation original and visually legible.",
    )


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
