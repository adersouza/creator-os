from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from sqlite3 import Connection

from .config import DEFAULT_DATA_ROOT
from .db import json_dump, json_load
from .fileops import atomic_write_text
from .identity import stable_id
from .scoring import shortlist
from .timeutil import now_iso

VALID_LABELS = {"gold", "maybe", "ignore"}
DEFAULT_GOLD_TARGET = 240
DEFAULT_ACCOUNT_CAP = 60
REVIEW_BATCH_SIZE = 25


def label_reference(
    conn: Connection,
    reference_id: str,
    label: str,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    if label not in VALID_LABELS:
        raise ValueError(f"Unsupported label: {label}")
    exists = conn.execute(
        "SELECT reference_id FROM source_files WHERE reference_id = ?",
        (reference_id,),
    ).fetchone()
    if not exists:
        raise ValueError(f"Unknown reference_id: {reference_id}")
    timestamp = now_iso()
    label_id = stable_id("label", reference_id, label)
    conn.execute(
        "DELETE FROM review_labels WHERE reference_id = ? AND label <> ?",
        (reference_id, label),
    )
    conn.execute(
        """
        INSERT INTO review_labels (id, reference_id, label, tags_json, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(reference_id, label) DO UPDATE SET
          tags_json = excluded.tags_json,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        (
            label_id,
            reference_id,
            label,
            json_dump(tags or []),
            notes,
            timestamp,
            timestamp,
        ),
    )
    conn.commit()
    return {
        "schema": "reference_factory.label.v1",
        "referenceId": reference_id,
        "label": label,
        "tags": tags or [],
    }


def set_reference_label(
    conn: Connection,
    reference_id: str,
    label: str | None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    exists = conn.execute(
        "SELECT reference_id FROM source_files WHERE reference_id = ?",
        (reference_id,),
    ).fetchone()
    if not exists:
        raise ValueError(f"Unknown reference_id: {reference_id}")
    conn.execute("DELETE FROM review_labels WHERE reference_id = ?", (reference_id,))
    if label is None:
        conn.commit()
        return {
            "schema": "reference_factory.label.v1",
            "referenceId": reference_id,
            "label": None,
            "tags": [],
        }
    return label_reference(conn, reference_id, label, tags, notes)


def reference_query(
    conn: Connection,
    label: str | None = None,
    captioned: bool | None = None,
    account: str | None = None,
    min_score: int | None = None,
    sort: str = "score",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, object]:
    rows = [_inflate_reference(row) for row in conn.execute(_REFERENCE_SQL).fetchall()]
    if label == "unreviewed":
        rows = [row for row in rows if row["label"] is None]
    elif label:
        rows = [row for row in rows if row["label"] == label]
    if captioned is True:
        rows = [row for row in rows if row["captionCount"] > 0]
    elif captioned is False:
        rows = [row for row in rows if row["captionCount"] == 0]
    if account:
        rows = [row for row in rows if row["account"] == account]
    if min_score is not None:
        rows = [row for row in rows if row["score"] >= min_score]
    rows = _sort_references(rows, sort)
    total = len(rows)
    return {
        "schema": "reference_factory.references.v1",
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": rows[offset : offset + limit],
    }


def reference_detail(conn: Connection, reference_id: str) -> dict[str, object] | None:
    row = conn.execute(
        _REFERENCE_SQL + " HAVING sf.reference_id = ?", (reference_id,)
    ).fetchone()
    if not row:
        return None
    item = _inflate_reference(row)
    item["ocr"] = [
        {
            "id": ocr["id"],
            "engine": ocr["engine"],
            "confidence": ocr["confidence"],
            "text": ocr["ocr_text"],
            "frameSampleId": ocr["frame_sample_id"],
            "createdAt": ocr["created_at"],
        }
        for ocr in conn.execute(
            """
            SELECT id, engine, confidence, ocr_text, frame_sample_id, created_at
            FROM ocr_results
            WHERE reference_id = ?
            ORDER BY confidence DESC, created_at DESC
            """,
            (reference_id,),
        ).fetchall()
    ]
    return item


def review_stats(conn: Connection) -> dict[str, object]:
    counts = {
        "total": conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0],
        "videos": conn.execute(
            "SELECT COUNT(*) FROM source_files WHERE kind = 'video'"
        ).fetchone()[0],
        "validVideos": conn.execute(
            "SELECT COUNT(*) FROM video_probes WHERE valid = 1"
        ).fetchone()[0],
        "contactThumbnails": conn.execute(
            "SELECT COUNT(*) FROM frame_samples WHERE role = 'contact'"
        ).fetchone()[0],
        "captionPatterns": conn.execute(
            "SELECT COUNT(*) FROM caption_patterns"
        ).fetchone()[0],
        "gold": conn.execute(
            "SELECT COUNT(*) FROM review_labels WHERE label = 'gold'"
        ).fetchone()[0],
        "maybe": conn.execute(
            "SELECT COUNT(*) FROM review_labels WHERE label = 'maybe'"
        ).fetchone()[0],
        "ignore": conn.execute(
            "SELECT COUNT(*) FROM review_labels WHERE label = 'ignore'"
        ).fetchone()[0],
    }
    counts["missingContactThumbnails"] = max(
        0, counts["validVideos"] - counts["contactThumbnails"]
    )
    accounts = [
        {"account": row["account"], "videos": row["videos"]}
        for row in conn.execute(
            """
            SELECT account, COUNT(*) AS videos
            FROM source_files
            WHERE kind = 'video'
            GROUP BY account
            ORDER BY videos DESC
            LIMIT 100
            """
        ).fetchall()
    ]
    gold_rows = [
        _inflate_reference(row)
        for row in conn.execute(_REFERENCE_SQL + " HAVING rl.label = 'gold'").fetchall()
    ]
    gold_accounts = Counter(str(row["account"] or "_root") for row in gold_rows)
    progress = {
        "target": DEFAULT_GOLD_TARGET,
        "gold": len(gold_rows),
        "remaining": max(0, DEFAULT_GOLD_TARGET - len(gold_rows)),
        "captionedGold": sum(1 for row in gold_rows if int(row["captionCount"]) > 0),
        "visualGold": sum(1 for row in gold_rows if int(row["captionCount"]) == 0),
        "accountCap": DEFAULT_ACCOUNT_CAP,
        "topGoldAccounts": [
            {"account": account, "gold": count}
            for account, count in gold_accounts.most_common(20)
        ],
    }
    return {
        "schema": "reference_factory.stats.v1",
        "counts": counts,
        "accounts": accounts,
        "goldProgress": progress,
    }


def export_gold(
    conn: Connection, data_root: Path = DEFAULT_DATA_ROOT
) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT
          sf.reference_id, sf.path, sf.account, sf.file_name,
          rl.label, rl.tags_json, rl.notes,
          vp.duration_seconds, vp.width, vp.height, vp.aspect_ratio,
          thumb.frame_path AS thumbnail_path,
          best.normalized_text AS best_caption,
          best.caption_hash AS best_caption_hash,
          COUNT(DISTINCT cp.caption_hash) AS caption_count
        FROM review_labels rl
        JOIN source_files sf ON sf.reference_id = rl.reference_id
        LEFT JOIN video_probes vp ON vp.reference_id = sf.reference_id
        LEFT JOIN frame_samples thumb
          ON thumb.reference_id = sf.reference_id
         AND thumb.role = 'contact'
        LEFT JOIN caption_patterns best
          ON best.caption_hash = (
            SELECT cp2.caption_hash
            FROM caption_patterns cp2
            WHERE cp2.reference_id = sf.reference_id
            ORDER BY cp2.avg_confidence DESC, cp2.char_count DESC
            LIMIT 1
          )
        LEFT JOIN caption_patterns cp ON cp.reference_id = sf.reference_id
        WHERE rl.label = 'gold'
        GROUP BY sf.reference_id
        ORDER BY sf.account, sf.file_name
        """
    ).fetchall()
    out = data_root / "curated" / "gold_manifest.jsonl"
    summary_path = data_root / "curated" / "gold_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest_items: list[dict[str, object]] = []
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            item = {
                "referenceId": row["reference_id"],
                "path": row["path"],
                "account": row["account"],
                "fileName": row["file_name"],
                "label": row["label"],
                "tags": json_load(row["tags_json"], []),
                "notes": row["notes"],
                "bestCaption": row["best_caption"],
                "bestCaptionHash": row["best_caption_hash"],
                "captionCount": row["caption_count"],
                "durationSeconds": row["duration_seconds"],
                "width": row["width"],
                "height": row["height"],
                "aspectRatio": row["aspect_ratio"],
                "thumbnailPath": row["thumbnail_path"],
                "score": reference_score_from_export_row(row),
            }
            manifest_items.append(item)
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    summary = build_gold_summary(conn, manifest_items)
    atomic_write_text(
        summary_path,
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        "schema": "reference_factory.export_gold.v1",
        "count": len(rows),
        "manifestPath": str(out),
        "summaryPath": str(summary_path),
        "summary": summary,
    }


def build_shortlist(conn: Connection, target: int = 300) -> dict[str, object]:
    return shortlist(conn, target=target)


def review_batch(
    conn: Connection,
    target: int = DEFAULT_GOLD_TARGET,
    mode: str = "balanced",
    account_cap: int = DEFAULT_ACCOUNT_CAP,
) -> dict[str, object]:
    if mode != "balanced":
        raise ValueError(f"Unsupported review batch mode: {mode}")
    rows = reference_query(conn, label="unreviewed", sort="score", limit=100000)[
        "items"
    ]
    caption_goal = min(120, target // 2)
    visual_goal = min(120, target // 2)
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    account_counts: Counter[str] = Counter()
    skipped_account_cap = 0

    def add_from(candidates: list[dict[str, object]], goal: int | None = None) -> None:
        nonlocal skipped_account_cap
        for item in candidates:
            if len(selected) >= target:
                return
            if (
                goal is not None
                and sum(1 for row in selected if _same_bucket(row, item)) >= goal
            ):
                return
            reference_id = str(item["referenceId"])
            account = str(item["account"] or "_root")
            if reference_id in selected_ids:
                continue
            if account_counts[account] >= account_cap:
                skipped_account_cap += 1
                continue
            selected.append(item)
            selected_ids.add(reference_id)
            account_counts[account] += 1

    captioned = [row for row in rows if int(row["captionCount"]) > 0]
    visual = [row for row in rows if int(row["captionCount"]) == 0]
    add_from(captioned, caption_goal)
    add_from(visual, visual_goal)
    add_from(rows, None)

    captioned_count = sum(1 for item in selected if int(item["captionCount"]) > 0)
    visual_count = sum(1 for item in selected if int(item["captionCount"]) == 0)
    for item in selected:
        item["suggestedTags"] = suggest_reference_tags(conn, str(item["referenceId"]))
    batches = [
        [
            str(item["referenceId"])
            for item in selected[offset : offset + REVIEW_BATCH_SIZE]
        ]
        for offset in range(0, len(selected), REVIEW_BATCH_SIZE)
    ]
    return {
        "schema": "reference_factory.review_batch.v1",
        "mode": mode,
        "target": target,
        "accountCap": account_cap,
        "goals": {
            "captioned": caption_goal,
            "visual": visual_goal,
        },
        "available": len(rows),
        "selected": len(selected),
        "captionedSelected": captioned_count,
        "visualSelected": visual_count,
        "skippedDueAccountCap": skipped_account_cap,
        "accountCounts": [
            {"account": account, "count": count}
            for account, count in sorted(
                account_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "batchSize": REVIEW_BATCH_SIZE,
        "approvalBatches": batches,
        "items": selected,
    }


def suggest_reference_tags(conn: Connection, reference_id: str) -> dict[str, object]:
    """Return deterministic evidence-backed suggestions without mutating labels."""
    pattern_row = conn.execute(
        """SELECT visual_format, hook_type, caption_archetype, pattern_json
        FROM reference_patterns WHERE reference_id = ?
        ORDER BY quality_score DESC, updated_at DESC LIMIT 1""",
        (reference_id,),
    ).fetchone()
    ocr_rows = conn.execute(
        """SELECT ocr_text FROM ocr_results WHERE reference_id = ?
        ORDER BY confidence DESC, created_at DESC LIMIT 3""",
        (reference_id,),
    ).fetchall()
    existing = conn.execute(
        "SELECT tags_json FROM review_labels WHERE reference_id = ? LIMIT 1",
        (reference_id,),
    ).fetchone()
    suggestions: dict[str, set[str]] = {}

    def add(tag: object, source: str) -> None:
        normalized = str(tag or "").strip().lower().replace(" ", "_")
        if normalized and normalized not in {"none", "unknown", "null"}:
            suggestions.setdefault(normalized, set()).add(source)

    for tag in json_load(existing["tags_json"], []) if existing else []:
        add(tag, "existing_metadata")
    if ocr_rows:
        add("caption_example", "ocr")
    if pattern_row:
        add(pattern_row["visual_format"], "pattern_card")
        add(pattern_row["hook_type"], "pattern_card")
        add(pattern_row["caption_archetype"], "pattern_card")
        pattern = json_load(pattern_row["pattern_json"], {})
        winner_dna = pattern.get("winnerDna") if isinstance(pattern, dict) else {}
        if isinstance(winner_dna, dict):
            for key in ("visualStructure", "hookType", "captionArchetype", "audioRole"):
                add(winner_dna.get(key), "winner_dna")
        for key in ("embeddingClusterId", "embedding_cluster_id"):
            if isinstance(pattern, dict) and pattern.get(key):
                add(f"cluster_{pattern[key]}", "embedding")
    return {
        "schema": "reference_factory.suggested_tags.v1",
        "referenceId": reference_id,
        "writeApplied": False,
        "tags": [
            {"tag": tag, "reasons": sorted(sources)}
            for tag, sources in sorted(suggestions.items())
        ],
    }


def build_gold_summary(
    conn: Connection, manifest_items: list[dict[str, object]] | None = None
) -> dict[str, object]:
    if manifest_items is None:
        manifest_items = []
    labels = Counter(
        {
            row["label"]: row["count"]
            for row in conn.execute(
                "SELECT label, COUNT(*) AS count FROM review_labels GROUP BY label"
            ).fetchall()
        }
    )
    tags: Counter[str] = Counter()
    accounts: Counter[str] = Counter()
    top_captions: Counter[str] = Counter()
    captioned = 0
    visual = 0
    for item in manifest_items:
        accounts[str(item.get("account") or "_root")] += 1
        for tag in item.get("tags") or []:
            tags[str(tag)] += 1
        if int(item.get("captionCount") or 0) > 0:
            captioned += 1
            caption = str(item.get("bestCaption") or "").strip()
            if caption:
                top_captions[caption] += 1
        else:
            visual += 1
    return {
        "schema": "reference_factory.gold_summary.v1",
        "target": DEFAULT_GOLD_TARGET,
        "labels": dict(sorted(labels.items())),
        "goldCount": len(manifest_items),
        "remainingToTarget": max(0, DEFAULT_GOLD_TARGET - len(manifest_items)),
        "captionedGold": captioned,
        "visualGold": visual,
        "tagCounts": dict(sorted(tags.items())),
        "accountDistribution": [
            {"account": account, "gold": count}
            for account, count in accounts.most_common()
        ],
        "topCaptionPatterns": [
            {"caption": caption, "count": count}
            for caption, count in top_captions.most_common(25)
        ],
    }


def _same_bucket(left: dict[str, object], right: dict[str, object]) -> bool:
    return (int(left["captionCount"]) > 0) == (int(right["captionCount"]) > 0)


_REFERENCE_SQL = """
    SELECT
      sf.reference_id, sf.path, sf.account, sf.file_name,
      vp.valid, vp.duration_seconds, vp.width, vp.height, vp.aspect_ratio,
      thumb.id AS thumbnail_frame_id,
      thumb.frame_path AS thumbnail_path,
      rl.label, rl.tags_json, rl.notes,
      COUNT(DISTINCT cp.caption_hash) AS caption_count,
      best.normalized_text AS best_caption,
      best.caption_hash AS best_caption_hash,
      best.avg_confidence AS best_caption_confidence,
      COUNT(DISTINCT fs.id) AS frame_count
    FROM source_files sf
    JOIN video_probes vp ON vp.reference_id = sf.reference_id
    LEFT JOIN frame_samples thumb
      ON thumb.reference_id = sf.reference_id
     AND thumb.role = 'contact'
    LEFT JOIN review_labels rl ON rl.reference_id = sf.reference_id
    LEFT JOIN caption_patterns cp ON cp.reference_id = sf.reference_id
    LEFT JOIN caption_patterns best
      ON best.caption_hash = (
        SELECT cp2.caption_hash
        FROM caption_patterns cp2
        WHERE cp2.reference_id = sf.reference_id
        ORDER BY cp2.avg_confidence DESC, cp2.char_count DESC
        LIMIT 1
      )
    LEFT JOIN frame_samples fs ON fs.reference_id = sf.reference_id
    WHERE sf.kind = 'video' AND vp.valid = 1
    GROUP BY sf.reference_id
"""


def _inflate_reference(row) -> dict[str, object]:
    item = dict(row)
    score_row = {
        "valid": item["valid"],
        "width": item["width"],
        "height": item["height"],
        "aspect_ratio": item["aspect_ratio"],
        "duration_seconds": item["duration_seconds"],
        "caption_count": item["caption_count"],
        "frame_count": item["frame_count"],
    }
    score, reasons = _score(score_row)
    return {
        "referenceId": item["reference_id"],
        "path": item["path"],
        "account": item["account"],
        "fileName": item["file_name"],
        "durationSeconds": item["duration_seconds"],
        "width": item["width"],
        "height": item["height"],
        "aspectRatio": item["aspect_ratio"],
        "thumbnailFrameId": item["thumbnail_frame_id"],
        "thumbnailPath": item["thumbnail_path"],
        "thumbnailUrl": f"/api/frame/{item['thumbnail_frame_id']}"
        if item["thumbnail_frame_id"]
        else None,
        "label": item["label"],
        "tags": json_load(item["tags_json"], []),
        "notes": item["notes"],
        "captionCount": int(item["caption_count"] or 0),
        "bestCaption": item["best_caption"],
        "bestCaptionHash": item["best_caption_hash"],
        "bestCaptionConfidence": item["best_caption_confidence"],
        "score": score,
        "scoreReasons": reasons,
    }


def _score(row: dict[str, object]) -> tuple[int, list[str]]:
    from .scoring import score_reference

    return score_reference(row)


def _sort_references(
    rows: list[dict[str, object]], sort: str
) -> list[dict[str, object]]:
    if sort == "random":
        import random

        rng = random.Random(1337)
        rows = rows[:]
        rng.shuffle(rows)
        return rows
    if sort == "newest":
        return sorted(rows, key=lambda row: str(row["fileName"]), reverse=True)
    if sort == "account-balanced":
        groups: dict[str, list[dict[str, object]]] = {}
        for row in sorted(rows, key=lambda item: -int(item["score"])):
            groups.setdefault(str(row["account"] or "_root"), []).append(row)
        balanced: list[dict[str, object]] = []
        while any(groups.values()):
            for account in sorted(groups):
                if groups[account]:
                    balanced.append(groups[account].pop(0))
        return balanced
    return sorted(
        rows,
        key=lambda row: (-int(row["score"]), str(row["account"]), str(row["fileName"])),
    )


def reference_score_from_export_row(row) -> int:
    score, _ = _score(
        {
            "valid": 1,
            "width": row["width"],
            "height": row["height"],
            "aspect_ratio": row["aspect_ratio"],
            "duration_seconds": row["duration_seconds"],
            "caption_count": row["caption_count"],
            "frame_count": 1 if row["thumbnail_path"] else 0,
        }
    )
    return score
