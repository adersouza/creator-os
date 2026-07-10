from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .audio import extract_audio_signal
from .caption_archetypes import caption_archetype as classify_caption_archetype
from .db import json_dump, json_load
from .fileops import atomic_write_text
from .identity import stable_id, text_hash
from .public_metrics import top_public_posts
from .timeutil import now_iso

ANALYZER_VERSION = "reference_factory.patterns.v1"

TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("mirror", ("mirror", "selfie", "fit check", "fitcheck", "reflection")),
    ("fit_check", ("fit check", "fitcheck", "outfit", "fit ", "dress", "wearing")),
    ("bedroom", ("bedroom", "bed ", "room", "pillow", "asmr")),
    ("walking", ("walking", "walk", "street", "sidewalk")),
    ("pose", ("pose", "posing", "look at", "camera caught")),
    ("slideshow", ("slideshow", "carousel", "photo dump", "swipe", "tiktok_slideshow")),
    (
        "caption_style",
        ("pov", "when ", "how it feels", "pick one", "congrats", "if u got", "99.9"),
    ),
    (
        "hook_good",
        (
            "pov",
            "when ",
            "how it feels",
            "pick one",
            "can’t",
            "can't",
            "rare",
            "if u got",
        ),
    ),
    ("no_caption", ()),
]


def analyze_patterns(
    conn: Connection,
    limit: int = 300,
    provider: str = "auto",
    ollama_model: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, object]:
    provider_used = _resolve_provider(provider)
    items = _pattern_source_rows(conn, limit)
    timestamp = now_iso()
    patterns: list[dict[str, Any]] = []
    llm_attempted = False
    llm_used = 0
    for item in items:
        heuristic = _heuristic_pattern(item)
        pattern = heuristic
        if provider_used == "ollama":
            llm_attempted = True
            llm_pattern = _ollama_pattern(item, heuristic, ollama_model)
            if llm_pattern:
                pattern = _merge_llm_pattern(heuristic, llm_pattern)
                llm_used += 1
        pattern_id = stable_id(
            "reference_pattern",
            str(item.get("referenceId") or ""),
            str(item.get("publicPostId") or ""),
            ANALYZER_VERSION,
        )
        conn.execute(
            """
            INSERT INTO reference_patterns (
              id, reference_id, public_post_id, rank, provider, model,
              analyzer_version, suggested_label, visual_format, hook_type,
              caption_archetype, quality_score, pattern_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              reference_id = excluded.reference_id,
              public_post_id = excluded.public_post_id,
              rank = excluded.rank,
              provider = excluded.provider,
              model = excluded.model,
              analyzer_version = excluded.analyzer_version,
              suggested_label = excluded.suggested_label,
              visual_format = excluded.visual_format,
              hook_type = excluded.hook_type,
              caption_archetype = excluded.caption_archetype,
              quality_score = excluded.quality_score,
              pattern_json = excluded.pattern_json,
              updated_at = excluded.updated_at
            """,
            (
                pattern_id,
                item.get("referenceId"),
                item.get("publicPostId"),
                item.get("rank"),
                pattern["provider"],
                pattern.get("model"),
                ANALYZER_VERSION,
                pattern["suggestedLabel"],
                pattern["visualFormat"],
                pattern["hookType"],
                pattern["captionArchetype"],
                pattern["qualityScore"],
                json_dump(pattern),
                timestamp,
                timestamp,
            ),
        )
        patterns.append(pattern)
    conn.commit()
    summary = pattern_summary(conn, limit=limit)
    paths: dict[str, str] = {}
    if output_dir:
        paths = export_patterns(
            conn, limit=limit, output_dir=output_dir, include_items=False
        )
    return {
        "schema": "reference_factory.analyze_patterns.v1",
        "limit": limit,
        "analyzed": len(patterns),
        "providerRequested": provider,
        "providerUsed": provider_used,
        "ollamaAttempted": llm_attempted,
        "ollamaUsed": llm_used,
        "summary": summary["summary"],
        **paths,
        "items": patterns[:10],
    }


def refresh_measured_outcomes_for_references(
    conn: Connection, reference_ids: Iterable[str], *, commit: bool = True
) -> dict[str, Any]:
    """Refresh only denormalized pattern rows affected by prompt outcome changes."""
    changed: list[str] = []
    normalized_reference_ids = sorted(
        {str(value).strip() for value in reference_ids if value}
    )
    timestamp = now_iso()
    for reference_id in normalized_reference_ids:
        prompts = conn.execute(
            """
            SELECT outcome_sample_count, outcome_reward_score, outcome_confidence,
                   outcome_updated_at
            FROM generated_video_prompts
            WHERE reference_id = ? AND outcome_reward_score IS NOT NULL
            """,
            (reference_id,),
        ).fetchall()
        sample_count = sum(int(row["outcome_sample_count"] or 0) for row in prompts)
        measured = None
        if sample_count > 0:
            reward = sum(
                float(row["outcome_reward_score"])
                * max(1, int(row["outcome_sample_count"] or 0))
                for row in prompts
            ) / sum(max(1, int(row["outcome_sample_count"] or 0)) for row in prompts)
            confidence_rows = [
                float(row["outcome_confidence"])
                for row in prompts
                if row["outcome_confidence"] is not None
            ]
            measured = {
                "rewardScore": reward,
                "sampleCount": sample_count,
                "confidence": (
                    sum(confidence_rows) / len(confidence_rows)
                    if confidence_rows
                    else None
                ),
                "updatedAt": max(
                    str(row["outcome_updated_at"] or "") for row in prompts
                ),
            }
        pattern_rows = conn.execute(
            """
            SELECT rp.id, rp.pattern_json, rp.quality_score, pp.match_type
            FROM reference_patterns rp
            LEFT JOIN public_posts pp ON pp.id = rp.public_post_id
            WHERE rp.reference_id = ?
            """,
            (reference_id,),
        ).fetchall()
        for row in pattern_rows:
            pattern = json_load(row["pattern_json"], {})
            metrics = (
                pattern.get("metrics")
                if isinstance(pattern.get("metrics"), dict)
                else {}
            )
            metrics["measuredOutcome"] = measured
            pattern["metrics"] = metrics
            performance_class = _performance_class(
                {
                    "measuredOutcome": measured,
                    "matchType": row["match_type"],
                },
                float(row["quality_score"] or 0),
            )
            pattern["performanceClass"] = performance_class
            winner_dna = (
                pattern.get("winnerDna")
                if isinstance(pattern.get("winnerDna"), dict)
                else {}
            )
            winner_dna["performanceClass"] = performance_class
            winner_dna["rewardScore"] = (
                measured.get("rewardScore") if measured else None
            )
            winner_dna["sampleCount"] = measured.get("sampleCount") if measured else 0
            pattern["winnerDna"] = winner_dna
            conn.execute(
                "UPDATE reference_patterns SET pattern_json = ?, updated_at = ? WHERE id = ?",
                (json_dump(pattern), timestamp, row["id"]),
            )
            changed.append(str(row["id"]))
    if commit:
        conn.commit()
    return {
        "schema": "reference_factory.targeted_pattern_refresh.v1",
        "references": len(normalized_reference_ids),
        "patternsChanged": len(changed),
        "patternIds": changed,
    }


def export_patterns(
    conn: Connection,
    limit: int = 300,
    output_dir: Path | None = None,
    include_items: bool = True,
) -> dict[str, object]:
    output_dir = output_dir or Path("learning")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _pattern_rows(conn, limit)
    cards = [_pattern_row_to_card(row) for row in rows]
    summary = _summary_from_cards(cards)
    jsonl_path = output_dir / f"pattern_cards_top{limit}.jsonl"
    manifest_path = output_dir / f"pattern_cards_top{limit}.json"
    summary_path = output_dir / f"pattern_summary_top{limit}.json"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for card in cards:
            f.write(json.dumps(card, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_write_text(manifest_path, 
        json.dumps(
            {
                "schema": "reference_factory.pattern_cards.v1",
                "limit": limit,
                "count": len(cards),
                "cards": cards,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    atomic_write_text(summary_path, 
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )
    payload: dict[str, object] = {
        "schema": "reference_factory.export_patterns.v1",
        "limit": limit,
        "count": len(cards),
        "jsonlPath": str(jsonl_path),
        "manifestPath": str(manifest_path),
        "summaryPath": str(summary_path),
        "summary": summary["summary"],
    }
    if include_items:
        payload["items"] = cards[:10]
    return payload


def pattern_summary(conn: Connection, limit: int = 300) -> dict[str, object]:
    cards = [_pattern_row_to_card(row) for row in _pattern_rows(conn, limit)]
    return _summary_from_cards(cards)


def apply_pattern_labels(
    conn: Connection,
    limit: int = 300,
    overwrite: bool = False,
) -> dict[str, object]:
    rows = _pattern_rows(conn, limit)
    applied = 0
    skipped = 0
    timestamp = now_iso()
    for row in rows:
        reference_id = row["reference_id"]
        pattern = json_load(row["pattern_json"], {})
        suggested = pattern.get("suggestedLabel")
        if not reference_id:
            skipped += 1
            continue
        if suggested not in {"gold", "maybe", "ignore"}:
            skipped += 1
            continue
        existing = conn.execute(
            "SELECT COUNT(*) FROM review_labels WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()[0]
        if existing and not overwrite:
            skipped += 1
            continue
        if overwrite:
            conn.execute(
                "DELETE FROM review_labels WHERE reference_id = ?", (reference_id,)
            )
        tags = sorted(set(pattern.get("reviewTags") or []))
        label_id = stable_id("label", reference_id, suggested, "pattern")
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
                suggested,
                json_dump(tags),
                "machine label from reference pattern analyzer",
                timestamp,
                timestamp,
            ),
        )
        applied += 1
    conn.commit()
    return {
        "schema": "reference_factory.apply_pattern_labels.v1",
        "limit": limit,
        "applied": applied,
        "skipped": skipped,
        "overwrite": overwrite,
    }


def _pattern_source_rows(conn: Connection, limit: int) -> list[dict[str, Any]]:
    top = top_public_posts(conn, limit)
    rows = []
    for item in top["items"]:
        reference_id = item.get("referenceId")
        source = probe = caption = label = None
        public_post = conn.execute(
            "SELECT raw_json FROM public_posts WHERE id = ?",
            (item["id"],),
        ).fetchone()
        raw_json = item.get("rawJson")
        if not raw_json and public_post:
            raw_json = json_load(public_post["raw_json"], {})
        if reference_id:
            source = conn.execute(
                "SELECT * FROM source_files WHERE reference_id = ?",
                (reference_id,),
            ).fetchone()
            probe = conn.execute(
                "SELECT * FROM video_probes WHERE reference_id = ?",
                (reference_id,),
            ).fetchone()
            caption = conn.execute(
                """
                SELECT *
                FROM caption_patterns
                WHERE reference_id = ?
                ORDER BY COALESCE(avg_confidence, 0) DESC, char_count DESC
                LIMIT 1
                """,
                (reference_id,),
            ).fetchone()
            label = conn.execute(
                """
                SELECT *
                FROM review_labels
                WHERE reference_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (reference_id,),
            ).fetchone()
        rows.append(
            {
                **item,
                "publicPostId": item["id"],
                "sourceFile": dict(source) if source else None,
                "probe": dict(probe) if probe else None,
                "captionPattern": dict(caption) if caption else None,
                "reviewLabel": dict(label) if label else None,
                "visionAnalysis": vision_context_for_reference(conn, reference_id),
                "rawJson": raw_json,
            }
        )
    return rows


def vision_context_for_reference(
    conn: Connection, reference_id: str | None
) -> dict[str, Any] | None:
    if not reference_id:
        return None
    pattern = conn.execute(
        """
        SELECT pattern_json
        FROM viral_pattern_cards
        WHERE reference_id = ?
        ORDER BY CASE status WHEN 'pattern_ready' THEN 0 ELSE 1 END, updated_at DESC
        LIMIT 1
        """,
        (reference_id,),
    ).fetchone()
    analysis = conn.execute(
        """
        SELECT provider, signals_json, analysis_json
        FROM reference_video_analyses
        WHERE reference_id = ?
        ORDER BY CASE status WHEN 'pattern_ready' THEN 0 WHEN 'analyzed' THEN 1 ELSE 2 END,
                 updated_at DESC
        LIMIT 1
        """,
        (reference_id,),
    ).fetchone()
    if not pattern and not analysis:
        return None
    return {
        "patternCard": json_load(pattern["pattern_json"], {}) if pattern else {},
        "analysis": json_load(analysis["analysis_json"], {}) if analysis else {},
        "signals": json_load(analysis["signals_json"], {}) if analysis else {},
        "provider": analysis["provider"] if analysis else None,
    }


def _pattern_rows(conn: Connection, limit: int) -> list[Any]:
    return conn.execute(
        """
        SELECT rp.*, pp.owner_username, pp.short_code, pp.url, pp.caption,
               pp.video_play_count, pp.video_view_count, pp.likes_count, pp.comments_count,
               pp.match_type, sf.path AS local_path, sf.account, sf.file_name
        FROM reference_patterns rp
        LEFT JOIN public_posts pp ON pp.id = rp.public_post_id
        LEFT JOIN source_files sf ON sf.reference_id = rp.reference_id
        ORDER BY COALESCE(rp.rank, 999999), rp.quality_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def _heuristic_pattern(item: dict[str, Any]) -> dict[str, Any]:
    public_caption = str(item.get("caption") or "").strip()
    caption_pattern = item.get("captionPattern") or {}
    ocr_caption = str(caption_pattern.get("normalized_text") or "").strip()
    caption_text = public_caption or ocr_caption
    raw_json = item.get("rawJson") or {}
    source_platform = raw_json.get("sourcePlatform")
    source_format = raw_json.get("sourceFormat")
    text_blob = " ".join(
        [
            caption_text,
            str(item.get("productType") or ""),
            str(item.get("type") or ""),
            str(source_platform or ""),
            str(source_format or ""),
            str(item.get("ownerUsername") or ""),
            str((item.get("sourceFile") or {}).get("file_name") or ""),
            str((item.get("sourceFile") or {}).get("path") or ""),
        ]
    ).lower()
    caption_archetype = classify_caption_archetype(caption_text)
    hook_type = _hook_type(caption_text, caption_archetype)
    visual_format = _visual_format(text_blob, caption_archetype, item)
    review_tags = _review_tags(
        text_blob, caption_archetype, visual_format, caption_text
    )
    quality_score = _quality_score(item, caption_archetype, visual_format, review_tags)
    performance_tier = _performance_tier(int(item.get("rank") or 999999))
    performance_class = _performance_class(item, quality_score)
    suggested_label = _suggested_label(item, quality_score)
    first_line = _first_line(caption_text)
    audio_signal = extract_audio_signal(raw_json, item.get("productType"))
    pattern = {
        "schema": "reference_factory.reference_pattern.v1",
        "analyzerVersion": ANALYZER_VERSION,
        "provider": "heuristic",
        "model": None,
        "source": {
            "publicPostId": item.get("publicPostId"),
            "rank": item.get("rank"),
            "account": item.get("ownerUsername"),
            "shortCode": item.get("shortCode"),
            "url": item.get("url"),
            "referenceId": item.get("referenceId"),
            "localPath": item.get("localPath"),
            "matchType": item.get("matchType"),
            "sourcePlatform": source_platform,
            "sourceFormat": source_format,
        },
        "metrics": {
            "plays": item.get("videoPlayCount"),
            "views": item.get("videoViewCount"),
            "likes": item.get("likesCount"),
            "comments": item.get("commentsCount"),
            "ownerFollowerCount": item.get("ownerFollowerCount"),
            "publicRateScore": item.get("publicRateScore"),
            "measuredOutcome": item.get("measuredOutcome"),
            "performanceTier": performance_tier,
        },
        "caption": {
            "source": "public_caption"
            if public_caption
            else "ocr_caption"
            if ocr_caption
            else "none",
            "text": caption_text,
            "firstLine": first_line,
            "captionHash": text_hash(caption_text) if caption_text else None,
            "lineCount": len(
                [line for line in re.split(r"\n+", caption_text) if line.strip()]
            )
            if caption_text
            else 0,
            "charCount": len(caption_text),
            "usesQuestion": "?" in caption_text,
            "usesEmoji": bool(re.search(r"[^\w\s#.,!?'\"]", caption_text)),
            "hasHashtags": "#" in caption_text,
        },
        "visualFormat": visual_format,
        "hookType": hook_type,
        "captionArchetype": caption_archetype,
        "performanceClass": performance_class,
        "winnerDna": _winner_dna(
            item,
            visual_format=visual_format,
            hook_type=hook_type,
            caption_archetype=caption_archetype,
            performance_class=performance_class,
            audio_signal=audio_signal,
        ),
        "reviewTags": review_tags,
        "promptPattern": _prompt_pattern(
            visual_format,
            hook_type,
            caption_archetype,
        ),
        "referenceUse": {
            "recommendedUse": _recommended_use(quality_score, item.get("matchType")),
            "matchGoal": "close_format" if quality_score >= 72 else "loose_inspiration",
            "whatToLearn": _what_to_learn(visual_format, hook_type, caption_archetype),
        },
        "qualityScore": quality_score,
        "suggestedLabel": suggested_label,
        "reasons": _pattern_reasons(
            item, quality_score, caption_archetype, visual_format, review_tags
        ),
    }
    return apply_vision_pattern_overrides(pattern, item.get("visionAnalysis"))


def apply_vision_pattern_overrides(
    pattern: dict[str, Any], vision: dict[str, Any] | None
) -> dict[str, Any]:
    if not isinstance(vision, dict):
        return pattern
    card = (
        vision.get("patternCard") if isinstance(vision.get("patternCard"), dict) else {}
    )
    analysis = (
        vision.get("analysis") if isinstance(vision.get("analysis"), dict) else {}
    )
    if not card and not analysis:
        return pattern

    visual_format = _vision_visual_format(card, analysis)
    hook_type = _first_nonempty(card.get("hookType"), analysis.get("hookType"))
    if visual_format:
        pattern["visualFormat"] = visual_format
        pattern["promptPattern"] = _prompt_pattern(
            visual_format,
            str(hook_type or pattern.get("hookType") or "pov"),
            str(pattern.get("captionArchetype") or "captionless_visual"),
        )
        reference_use = pattern.setdefault("referenceUse", {})
        reference_use["whatToLearn"] = _what_to_learn(
            visual_format,
            str(hook_type or pattern.get("hookType") or "pov"),
            str(pattern.get("captionArchetype") or "captionless_visual"),
        )
    if hook_type:
        pattern["hookType"] = str(hook_type)

    winner_dna = dict(pattern.get("winnerDna") or {})
    winner_dna.update(_vision_winner_dna(card, analysis, vision, pattern))
    pattern["winnerDna"] = winner_dna
    pattern["promptPattern"] = _prompt_pattern(
        str(pattern.get("visualFormat") or "visual_reference"),
        str(pattern.get("hookType") or "curiosity_gap"),
        str(pattern.get("captionArchetype") or "captionless_visual"),
        winner_dna,
    )
    reference_use = pattern.setdefault("referenceUse", {})
    reference_use["whatToLearn"] = _what_to_learn(
        str(pattern.get("visualFormat") or "visual_reference"),
        str(pattern.get("hookType") or "curiosity_gap"),
        str(pattern.get("captionArchetype") or "captionless_visual"),
        winner_dna,
    )

    reasons = list(pattern.get("reasons") or [])
    if visual_format and "vision-derived visual format" not in reasons:
        reasons.append("vision-derived visual format")
    if card or analysis:
        reasons.append("vision analysis merged into production pattern")
    pattern["reasons"] = reasons
    return pattern


def _vision_visual_format(card: dict[str, Any], analysis: dict[str, Any]) -> str | None:
    format_card = (
        analysis.get("winningFormatCard")
        if isinstance(analysis.get("winningFormatCard"), dict)
        else {}
    )
    blueprint = _vision_blueprint(analysis)
    return _first_nonempty(
        card.get("visualFormat"),
        card.get("formatType"),
        format_card.get("visualFormat"),
        analysis.get("visualFormat"),
        analysis.get("contentFormat"),
        blueprint.get("format_type"),
        blueprint.get("formatType"),
    )


def _vision_winner_dna(
    card: dict[str, Any],
    analysis: dict[str, Any],
    vision: dict[str, Any],
    pattern: dict[str, Any],
) -> dict[str, Any]:
    supplied = card.get("winnerDna") or analysis.get("winnerDna")
    dna = dict(supplied) if isinstance(supplied, dict) else {}
    blueprint = _vision_blueprint(analysis)
    first_frame = _vision_first_frame(blueprint, analysis)
    motion_beats = _vision_motion_beats(blueprint, analysis)
    format_card = (
        analysis.get("winningFormatCard")
        if isinstance(analysis.get("winningFormatCard"), dict)
        else {}
    )
    subject = (
        analysis.get("subject") if isinstance(analysis.get("subject"), dict) else {}
    )
    card_subject = card.get("subject") if isinstance(card.get("subject"), dict) else {}
    setting = (
        analysis.get("setting") if isinstance(analysis.get("setting"), dict) else {}
    )
    visual_format = str(pattern.get("visualFormat") or "other")
    hook_type = str(pattern.get("hookType") or card.get("hookType") or "pov")
    dna.update(
        {
            "visionSource": "reference_video_analysis",
            "visionProvider": vision.get("provider"),
            "visualStructure": visual_format,
            "hookType": hook_type,
            "subjectAction": _first_nonempty(
                card.get("subjectAction"),
                subject.get("action"),
                format_card.get("poseAction"),
            ),
            "pose": _first_nonempty(
                first_frame.get("pose"),
                subject.get("pose"),
                format_card.get("poseAction"),
                card.get("subjectAction"),
            ),
            "outfit": _first_nonempty(
                first_frame.get("outfit_silhouette"),
                first_frame.get("outfitSilhouette"),
                subject.get("wardrobe"),
                card_subject.get("wardrobe"),
                format_card.get("styling"),
            ),
            "setting": _first_nonempty(
                card.get("setting"),
                setting.get("location"),
                format_card.get("setting"),
            ),
            "lighting": _first_nonempty(
                first_frame.get("lighting"),
                setting.get("lighting"),
                format_card.get("lighting"),
            ),
            "framing": _vision_framing(first_frame, card, analysis, format_card),
            "subjectCount": _first_number(
                card_subject.get("count"),
                subject.get("count"),
                format_card.get("subjectCount"),
            ),
            "shotSequence": _first_list(
                card.get("shotSequence"), analysis.get("shotSequence")
            ),
            "cameraStyle": _first_dict(
                card.get("cameraStyle"),
                analysis.get("camera"),
                format_card.get("camera"),
            ),
            "textOverlayStyle": _first_dict(
                card.get("textOverlayStyle"),
                analysis.get("textOverlay"),
                format_card.get("textOverlay"),
            ),
            "pacing": _first_dict(
                card.get("pacing"),
                analysis.get("visualPacing"),
                format_card.get("pacing"),
            ),
            "audioVibe": _first_dict(
                card.get("audioVibe"),
                analysis.get("audioVibe"),
                format_card.get("audioVibe"),
            ),
            "motionBeats": motion_beats,
            "firstFrameGeometry": first_frame,
            "recreationBlueprint": blueprint,
            "transformationInstructions": _first_list(
                card.get("transformationInstructions"),
                format_card.get("transformationInstructions"),
                analysis.get("transformationNotes"),
            ),
            "copyRiskNotes": _first_list(
                card.get("copyRiskNotes"),
                format_card.get("copyRiskNotes"),
                analysis.get("copyRiskNotes"),
            ),
        }
    )
    return {key: value for key, value in dna.items() if value not in (None, "", [], {})}


def _vision_blueprint(analysis: dict[str, Any]) -> dict[str, Any]:
    for key in ("recreation_blueprint", "recreationBlueprint", "blueprint"):
        value = analysis.get(key)
        if isinstance(value, dict):
            return value
    raw = analysis.get("raw") if isinstance(analysis.get("raw"), dict) else {}
    for key in ("recreation_blueprint", "recreationBlueprint", "blueprint"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _vision_first_frame(
    blueprint: dict[str, Any], analysis: dict[str, Any]
) -> dict[str, Any]:
    for key in ("first_frame", "firstFrame", "first_frame_blueprint"):
        value = blueprint.get(key)
        if isinstance(value, dict):
            return value
    value = analysis.get("firstFrame") or analysis.get("first_frame")
    return value if isinstance(value, dict) else {}


def _vision_motion_beats(
    blueprint: dict[str, Any], analysis: dict[str, Any]
) -> list[Any]:
    for key in ("motion_beats", "motionBeats", "motion_blueprint"):
        value = blueprint.get(key)
        if isinstance(value, list) and value:
            return value
    value = analysis.get("motionBeats") or analysis.get("shotSequence")
    return value if isinstance(value, list) else []


def _vision_framing(
    first_frame: dict[str, Any],
    card: dict[str, Any],
    analysis: dict[str, Any],
    format_card: dict[str, Any],
) -> dict[str, Any]:
    framing = {
        key: value
        for key, value in {
            "subjectScale": first_frame.get("subject_scale")
            or first_frame.get("subjectScale"),
            "crop": first_frame.get("crop"),
            "bodyAngle": first_frame.get("body_angle") or first_frame.get("bodyAngle"),
            "cameraHeight": first_frame.get("camera_height")
            or first_frame.get("cameraHeight"),
            "cameraDistance": first_frame.get("camera_distance")
            or first_frame.get("cameraDistance"),
            "lensFeel": first_frame.get("lens_feel") or first_frame.get("lensFeel"),
        }.items()
        if value not in (None, "", [], {})
    }
    camera = _first_dict(
        card.get("cameraStyle"), analysis.get("camera"), format_card.get("camera")
    )
    if camera:
        framing["camera"] = camera
    return framing


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list) and value:
            return value
    return []


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def _first_number(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
    return None


def _resolve_provider(provider: str) -> str:
    if provider not in {"auto", "heuristic", "ollama"}:
        raise ValueError(f"Unsupported pattern provider: {provider}")
    if provider == "heuristic":
        return "heuristic"
    if provider == "ollama":
        return "ollama"
    return "ollama" if _ollama_has_models() else "heuristic"


def _ollama_has_models() -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=2
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
            return bool(data.get("models"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def _ollama_pattern(
    item: dict[str, Any], heuristic: dict[str, Any], model: str | None
) -> dict[str, Any] | None:
    model_name = model or _default_ollama_model()
    if not model_name:
        return None
    prompt = (
        "Return only JSON. Analyze this high-performing Instagram Reel reference as reusable pattern data. "
        "Do not copy captions; classify structure, hook, visual format, and tags.\n\n"
        f"Input JSON:\n{json.dumps({'item': _llm_item(item), 'heuristic': heuristic}, ensure_ascii=False)}\n\n"
        "Required JSON keys: visualFormat, hookType, captionArchetype, reviewTags, promptPattern, "
        "referenceUse, qualityScore, suggestedLabel, reasons."
    )
    payload = json.dumps(
        {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
    ).encode("utf-8")
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data.get("response") or "{}"
        parsed = json.loads(raw)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None
    parsed["provider"] = "ollama"
    parsed["model"] = model_name
    return parsed


def _default_ollama_model() -> str | None:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=2
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
        models = data.get("models") or []
        if not models:
            return None
        return str(models[0].get("name") or "")
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _merge_llm_pattern(
    heuristic: dict[str, Any], llm: dict[str, Any]
) -> dict[str, Any]:
    merged = {**heuristic}
    for key in [
        "visualFormat",
        "hookType",
        "captionArchetype",
        "reviewTags",
        "promptPattern",
        "referenceUse",
        "qualityScore",
        "suggestedLabel",
        "reasons",
    ]:
        if key in llm and llm[key] not in (None, "", []):
            merged[key] = llm[key]
    merged["provider"] = "ollama"
    merged["model"] = llm.get("model")
    merged["qualityScore"] = float(
        _clamp_number(merged.get("qualityScore"), 0, 100, heuristic["qualityScore"])
    )
    if merged.get("suggestedLabel") not in {"gold", "maybe", "ignore"}:
        merged["suggestedLabel"] = heuristic["suggestedLabel"]
    merged["reviewTags"] = sorted(
        set(str(tag) for tag in merged.get("reviewTags") or [])
    )
    return merged


def _hook_type(caption: str, archetype: str) -> str:
    lowered = caption.lower()
    if archetype == "captionless_visual":
        return "visual_first"
    if archetype == "challenge_or_puzzle":
        return "completion_challenge"
    if archetype == "question_hook":
        return "direct_response"
    if archetype == "choice_bait":
        return "forced_choice"
    if lowered.startswith("pov") or archetype == "pov_scenario":
        return "viewer_insert"
    if lowered.startswith(("when ", "me when", "how it feels")):
        return "relatable_setup"
    if re.search(r"\bfollow\b|\bclaim\b|\bsend\b|\btag\b", lowered):
        return "action_prompt"
    return "curiosity_gap"


def _visual_format(text_blob: str, caption_archetype: str, item: dict[str, Any]) -> str:
    probe = item.get("probe") or {}
    raw_json = item.get("rawJson") or {}
    if (
        raw_json.get("sourceFormat") == "slideshow"
        or "tiktok_slideshow" in str(item.get("productType") or "").lower()
        or "slideshow" in text_blob
        or "carousel" in text_blob
    ):
        return "tiktok_slideshow"
    if "mirror" in text_blob or "selfie" in text_blob:
        return "mirror_selfie"
    if "fit check" in text_blob or "fitcheck" in text_blob or "outfit" in text_blob:
        return "fit_check"
    if "bedroom" in text_blob or "bed " in text_blob or "pillow" in text_blob:
        return "bedroom_static"
    if "walk" in text_blob:
        return "walking_clip"
    if caption_archetype != "captionless_visual":
        return "caption_led_visual"
    width = probe.get("width") or 0
    height = probe.get("height") or 0
    duration = probe.get("duration_seconds") or 0
    if height and width and height / max(width, 1) > 1.6 and duration <= 9:
        return "short_vertical_visual_hook"
    return "visual_reference"


def _review_tags(
    text_blob: str, caption_archetype: str, visual_format: str, caption: str
) -> list[str]:
    tags = set()
    for tag, needles in TAG_RULES:
        if tag == "no_caption":
            continue
        if any(needle in text_blob for needle in needles):
            tags.add(tag)
    if not caption:
        tags.add("no_caption")
    if caption_archetype != "captionless_visual":
        tags.add("caption_style")
    if visual_format != "caption_led_visual":
        tags.add("visual_style")
    if visual_format == "tiktok_slideshow":
        tags.update({"slideshow", "caption_style", "visual_style"})
        if caption:
            tags.add("hook_good")
    if caption_archetype in {
        "pov_scenario",
        "challenge_or_puzzle",
        "question_hook",
        "choice_bait",
    }:
        tags.add("hook_good")
    if "mirror" in visual_format:
        tags.add("mirror")
    if "fit" in visual_format:
        tags.add("fit_check")
    if "bedroom" in visual_format:
        tags.add("bedroom")
    if "walking" in visual_format:
        tags.add("walking")
    return sorted(tags)


def _quality_score(
    item: dict[str, Any], caption_archetype: str, visual_format: str, tags: list[str]
) -> float:
    rank = int(item.get("rank") or 999999)
    plays = int(item.get("videoPlayCount") or item.get("videoViewCount") or 0)
    likes = int(item.get("likesCount") or 0)
    comments = int(item.get("commentsCount") or 0)
    match_type = item.get("matchType")
    probe = item.get("probe") or {}
    duration = float(probe.get("duration_seconds") or 0)
    width = int(probe.get("width") or 0)
    height = int(probe.get("height") or 0)
    score = 48.0
    score += max(0.0, 28.0 - (rank - 1) * 0.07)
    if plays:
        score += min(12.0, math.log10(max(plays, 1)) * 2.2)
    if likes:
        score += min(5.0, math.log10(max(likes, 1)) * 1.2)
    if comments:
        score += min(3.0, math.log10(max(comments, 1)))
    measured = item.get("measuredOutcome") or {}
    measured_score = measured.get("rewardScore") if isinstance(measured, dict) else None
    if isinstance(measured_score, (int, float)):
        score += max(-10.0, min(14.0, (float(measured_score) - 1.0) * 18.0))
    public_rate_score = item.get("publicRateScore")
    if isinstance(public_rate_score, (int, float)) and public_rate_score > 0:
        score += min(
            6.0,
            math.log10(max(float(public_rate_score), 0.000001) * 1000.0 + 1.0) * 2.0,
        )
    if match_type == "exact_media_id":
        score += 6
    if height > width and width >= 540:
        score += 5
    if 3 <= duration <= 18:
        score += 4
    if caption_archetype != "captionless_visual":
        score += 3
    if "hook_good" in tags:
        score += 3
    if visual_format in {
        "mirror_selfie",
        "fit_check",
        "bedroom_static",
        "short_vertical_visual_hook",
    }:
        score += 2
    if visual_format == "tiktok_slideshow":
        score += 5
    if str(item.get("productType") or "").startswith("tiktok"):
        score += 3
    return round(max(0.0, min(100.0, score)), 2)


def _suggested_label(item: dict[str, Any], quality_score: float) -> str:
    if item.get("matchType") != "exact_media_id":
        return "maybe"
    if quality_score >= 74:
        return "gold"
    if quality_score >= 58:
        return "maybe"
    return "ignore"


def _prompt_pattern(
    visual_format: str,
    hook_type: str,
    caption_archetype: str,
    winner_dna: dict[str, Any] | None = None,
) -> dict[str, str]:
    return prompt_briefs_from_winner_dna(
        visual_format, hook_type, caption_archetype, winner_dna
    )


def prompt_briefs_from_winner_dna(
    visual_format: str,
    hook_type: str,
    caption_archetype: str,
    winner_dna: dict[str, Any] | None = None,
) -> dict[str, str]:
    briefs = {
        "visualBrief": {
            "mirror_selfie": "vertical mirror-shot reel, phone visible or implied, immediate body/outfit framing",
            "fit_check": "vertical outfit or body-frame check, simple background, one clear reveal",
            "bedroom_static": "vertical bedroom setup, close framing, casual creator posture, one visual beat",
            "walking_clip": "vertical walking movement, handheld natural pacing, subject enters frame quickly",
            "caption_led_visual": "simple vertical shot designed around readable meme caption overlay",
            "short_vertical_visual_hook": "short vertical visual hook with a strong first-frame pose or movement",
            "tiktok_slideshow": "TikTok-style slideshow carousel with 5-9 stills, fast first-slide hook, bold centered text, and simple swipeable story progression",
        }.get(visual_format, "vertical creator reel with one clear visual hook"),
        "hookBrief": {
            "visual_first": "visual must communicate the hook without caption dependency",
            "completion_challenge": "caption creates an impossible or playful viewer challenge",
            "direct_response": "caption asks a short question viewers can answer instantly",
            "forced_choice": "caption forces an A/B choice",
            "viewer_insert": "caption frames viewer inside the scenario",
            "relatable_setup": "caption sets up a familiar situation before the visual payoff",
            "action_prompt": "caption gives a light viewer action",
        }.get(hook_type, "caption creates a curiosity gap"),
        "captionBrief": {
            "captionless_visual": "no overlay or very minimal overlay",
            "challenge_or_puzzle": "short challenge caption with simple line breaks",
            "pov_scenario": "POV-style original scenario",
            "relatable_scenario": "short relatable setup",
            "choice_bait": "two-choice caption with clean spacing",
            "question_hook": "short direct question",
            "minimal_bait": "one-line minimal bait",
            "cta_bait": "light CTA or send/share prompt",
        }.get(caption_archetype, "short meme-style caption"),
    }
    dna = winner_dna if isinstance(winner_dna, dict) else {}
    visual_detail = _dna_visual_brief(dna)
    if visual_detail:
        briefs["visualBrief"] = visual_detail
    first_frame = _dna_first_frame_brief(dna)
    if first_frame:
        briefs["firstFrameBrief"] = first_frame
    motion = _dna_motion_brief(dna)
    if motion:
        briefs["motionBrief"] = motion
    transformation = _dna_transformation_brief(dna)
    if transformation:
        briefs["transformationBrief"] = transformation
    return briefs


def _dna_visual_brief(dna: dict[str, Any]) -> str | None:
    parts = []
    subject_action = dna.get("subjectAction") or dna.get("pose")
    if subject_action:
        parts.append(f"pose/action: {subject_action}")
    outfit = dna.get("outfit")
    if outfit:
        parts.append(f"outfit silhouette: {outfit}")
    setting = dna.get("setting")
    if setting:
        parts.append(f"setting: {setting}")
    lighting = dna.get("lighting")
    if lighting:
        parts.append(f"lighting: {lighting}")
    framing = _compact_dict_text(dna.get("framing"))
    if framing:
        parts.append(f"framing: {framing}")
    if not parts:
        return None
    return "Source-specific creator reel blueprint; " + "; ".join(parts)


def _dna_first_frame_brief(dna: dict[str, Any]) -> str | None:
    first_frame = dna.get("firstFrameGeometry")
    if not isinstance(first_frame, dict) or not first_frame:
        return None
    return _compact_dict_text(first_frame)


def _dna_motion_brief(dna: dict[str, Any]) -> str | None:
    beats = dna.get("motionBeats")
    if not isinstance(beats, list) or not beats:
        return None
    compact = []
    for beat in beats[:4]:
        if isinstance(beat, dict):
            compact.append(_compact_dict_text(beat))
        elif str(beat).strip():
            compact.append(str(beat).strip())
    return " | ".join(item for item in compact if item)


def _dna_transformation_brief(dna: dict[str, Any]) -> str | None:
    value = dna.get("transformationInstructions")
    if isinstance(value, list):
        text = "; ".join(str(item).strip() for item in value[:4] if str(item).strip())
        return text or None
    return str(value).strip() if value else None


def _compact_dict_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return str(value).strip() if value else None
    parts = []
    for key, item in value.items():
        if item in (None, "", [], {}):
            continue
        if isinstance(item, dict):
            item_text = _compact_dict_text(item)
        elif isinstance(item, list):
            item_text = ", ".join(str(part) for part in item[:4])
        else:
            item_text = str(item)
        if item_text:
            parts.append(f"{key}: {item_text}")
    return "; ".join(parts) if parts else None


def _recommended_use(quality_score: float, match_type: object) -> str:
    if match_type != "exact_media_id":
        return "external_metric_reference_only"
    if quality_score >= 74:
        return "gold_candidate_for_close_format_pattern"
    if quality_score >= 58:
        return "maybe_candidate_for_pattern_bank"
    return "low_priority_reference"


def _what_to_learn(
    visual_format: str,
    hook_type: str,
    caption_archetype: str,
    winner_dna: dict[str, Any] | None = None,
) -> list[str]:
    learn = [
        f"visual_format:{visual_format}",
        f"hook_type:{hook_type}",
        f"caption_archetype:{caption_archetype}",
        "first_second_hook",
        "line_break_structure",
    ]
    if visual_format == "tiktok_slideshow":
        learn.extend(
            ["slide_order", "first_slide_headline", "carousel_caption_formula"]
        )
    dna = winner_dna if isinstance(winner_dna, dict) else {}
    for key in (
        "outfit",
        "pose",
        "setting",
        "lighting",
        "framing",
        "subjectCount",
        "motionBeats",
        "firstFrameGeometry",
    ):
        if dna.get(key) not in (None, "", [], {}):
            learn.append(f"winner_dna:{key}")
    return learn


def _performance_class(item: dict[str, Any], quality_score: float) -> str:
    measured = (
        item.get("measuredOutcome")
        if isinstance(item.get("measuredOutcome"), dict)
        else {}
    )
    reward = measured.get("rewardScore") if isinstance(measured, dict) else None
    if isinstance(reward, (int, float)):
        if float(reward) >= 1.05:
            return "performed_well"
        if float(reward) <= 0.85:
            return "underperformed"
    if item.get("matchType") == "exact_media_id" and quality_score >= 74:
        return "looks_good_only"
    return "unproven"


def _winner_dna(
    item: dict[str, Any],
    *,
    visual_format: str,
    hook_type: str,
    caption_archetype: str,
    performance_class: str,
    audio_signal: dict[str, Any] | None,
) -> dict[str, object]:
    measured = (
        item.get("measuredOutcome")
        if isinstance(item.get("measuredOutcome"), dict)
        else {}
    )
    return {
        "performanceClass": performance_class,
        "performanceSource": "measured_outcome"
        if measured
        else "public_or_review_signal",
        "visualStructure": visual_format,
        "hookType": hook_type,
        "captionArchetype": caption_archetype,
        "audioRole": (audio_signal or {}).get("audioVibe") or "unknown_audio",
        "rewardScore": measured.get("rewardScore")
        if isinstance(measured, dict)
        else None,
        "sampleCount": measured.get("sampleCount")
        if isinstance(measured, dict)
        else None,
    }


def _pattern_reasons(
    item: dict[str, Any],
    quality_score: float,
    caption_archetype: str,
    visual_format: str,
    tags: list[str],
) -> list[str]:
    reasons = [
        f"rank {item.get('rank')} in public metric winners",
        f"quality score {quality_score}",
        f"caption archetype {caption_archetype}",
        f"visual format {visual_format}",
        f"performance class {_performance_class(item, quality_score)}",
    ]
    if item.get("matchType") == "exact_media_id":
        reasons.append("matched to local source video")
    if tags:
        reasons.append("tags: " + ", ".join(tags[:6]))
    return reasons


def _performance_tier(rank: int) -> str:
    if rank <= 50:
        return "top_50"
    if rank <= 150:
        return "top_150"
    if rank <= 300:
        return "top_300"
    return "long_tail"


def _first_line(caption: str) -> str:
    for line in re.split(r"[\r\n]+", caption.strip()):
        if line.strip():
            return line.strip()
    return caption.strip()[:80]


def _llm_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": item.get("rank"),
        "account": item.get("ownerUsername"),
        "caption": item.get("caption"),
        "bestOcrCaption": (item.get("captionPattern") or {}).get("normalized_text"),
        "plays": item.get("videoPlayCount"),
        "views": item.get("videoViewCount"),
        "likes": item.get("likesCount"),
        "comments": item.get("commentsCount"),
        "matchType": item.get("matchType"),
        "fileName": (item.get("sourceFile") or {}).get("file_name"),
        "duration": (item.get("probe") or {}).get("duration_seconds"),
        "width": (item.get("probe") or {}).get("width"),
        "height": (item.get("probe") or {}).get("height"),
        "sourcePlatform": (item.get("rawJson") or {}).get("sourcePlatform"),
        "sourceFormat": (item.get("rawJson") or {}).get("sourceFormat"),
    }


def _pattern_row_to_card(row: Any) -> dict[str, Any]:
    pattern = json_load(row["pattern_json"], {})
    metrics = pattern.get("metrics") if isinstance(pattern.get("metrics"), dict) else {}
    return {
        "schema": "reference_factory.pattern_card.v1",
        "id": row["id"],
        "rank": row["rank"],
        "referenceId": row["reference_id"],
        "publicPostId": row["public_post_id"],
        "account": row["owner_username"] or row["account"],
        "shortCode": row["short_code"],
        "url": row["url"],
        "localPath": row["local_path"],
        "fileName": row["file_name"],
        "matchType": row["match_type"],
        "metrics": {
            "plays": row["video_play_count"],
            "views": row["video_view_count"],
            "likes": row["likes_count"],
            "comments": row["comments_count"],
            "ownerFollowerCount": metrics.get("ownerFollowerCount"),
            "publicRateScore": metrics.get("publicRateScore"),
            "measuredOutcome": metrics.get("measuredOutcome"),
        },
        "suggestedLabel": row["suggested_label"],
        "visualFormat": row["visual_format"],
        "hookType": row["hook_type"],
        "captionArchetype": row["caption_archetype"],
        "qualityScore": row["quality_score"],
        "pattern": pattern,
    }


def _summary_from_cards(cards: list[dict[str, Any]]) -> dict[str, object]:
    labels = Counter(card.get("suggestedLabel") for card in cards)
    visual = Counter(card.get("visualFormat") for card in cards)
    hooks = Counter(card.get("hookType") for card in cards)
    captions = Counter(card.get("captionArchetype") for card in cards)
    accounts = Counter(card.get("account") for card in cards)
    tags: Counter[str] = Counter()
    for card in cards:
        for tag in (card.get("pattern") or {}).get("reviewTags") or []:
            tags[tag] += 1
    return {
        "schema": "reference_factory.pattern_summary.v1",
        "summary": {
            "count": len(cards),
            "suggestedLabels": dict(labels.most_common()),
            "visualFormats": dict(visual.most_common(20)),
            "hookTypes": dict(hooks.most_common(20)),
            "captionArchetypes": dict(captions.most_common(20)),
            "topAccounts": dict(accounts.most_common(20)),
            "tags": dict(tags.most_common(30)),
            "avgQualityScore": round(
                sum(float(card.get("qualityScore") or 0) for card in cards)
                / max(1, len(cards)),
                2,
            ),
        },
    }


def _clamp_number(value: object, low: float, high: float, fallback: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, numeric))
