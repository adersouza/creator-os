from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from sqlite3 import Connection, Row
from typing import Any

from creator_os_core.fileops import atomic_write_text
from pipeline_contracts.validator import validate_reference_factory_knowledge_pack

from .db import json_load
from .timeutil import now_iso

KNOWLEDGE_PACK_SCHEMA = "reference_factory.knowledge_pack.v1"
MEASURED_FACTS_SOURCE = "campaign_factory.performance_snapshots"
MINIMUM_MEASURED_EXAMPLES = 3


def export_knowledge_pack(
    conn: Connection,
    *,
    output_path: Path | None = None,
    minimum_measured_examples: int = MINIMUM_MEASURED_EXAMPLES,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the versioned, read-only Reference -> Campaign knowledge handoff."""

    minimum = max(MINIMUM_MEASURED_EXAMPLES, int(minimum_measured_examples))
    gold_rows = _gold_reference_rows(conn)
    gold_ids = [str(row["reference_id"]) for row in gold_rows]
    prompt_rows = _rows_for_ids(
        conn,
        """
        SELECT * FROM generated_video_prompts
        WHERE reference_id IN ({placeholders})
        ORDER BY reference_id, target_tool, id
        """,
        gold_ids,
    )
    pattern_rows = _rows_for_ids(
        conn,
        """
        SELECT * FROM reference_patterns
        WHERE reference_id IN ({placeholders})
        ORDER BY COALESCE(rank, 999999), quality_score DESC, id
        """,
        gold_ids,
    )
    caption_rows = _rows_for_ids(
        conn,
        """
        SELECT * FROM caption_patterns
        WHERE reference_id IN ({placeholders})
        ORDER BY reference_id, caption_hash
        """,
        gold_ids,
    )
    prompt_ids = [str(row["id"]) for row in prompt_rows]
    outcome_rows = _rows_for_ids(
        conn,
        """
        SELECT * FROM prompt_post_outcomes
        WHERE prompt_id IN ({placeholders})
        ORDER BY source_snapshot_at, prompt_id, post_id
        """,
        prompt_ids,
    )
    audio_rows = conn.execute(
        """
        SELECT * FROM audio_patterns
        ORDER BY total_plays DESC, post_count DESC, id
        """
    ).fetchall()

    outcomes_by_prompt = _outcomes_by_prompt(outcome_rows)
    prompts_by_reference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prompt_cards: list[dict[str, Any]] = []
    for row in prompt_rows:
        prompt_id = str(row["id"])
        outcomes = outcomes_by_prompt.get(prompt_id, [])
        card = {
            "id": prompt_id,
            "referenceId": str(row["reference_id"]),
            "targetTool": str(row["target_tool"]),
            "modelProfile": row["model_profile"],
            "status": str(row["status"]),
            "prompt": json_load(row["prompt_json"], {}),
            "measuredExampleCount": _measured_example_count(outcomes),
            "recommendationStatus": _recommendation_status(outcomes, minimum),
            "measuredOutcomeProvenance": outcomes,
        }
        prompt_cards.append(card)
        prompts_by_reference[card["referenceId"]].append(card)

    caption_patterns = [_caption_pattern(row) for row in caption_rows]
    captions_by_reference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for caption in caption_patterns:
        captions_by_reference[caption["referenceId"]].append(caption)

    audio_patterns = [_audio_pattern(row) for row in audio_rows]
    pattern_cards: list[dict[str, Any]] = []
    patterns_by_reference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pattern_rows:
        reference_id = str(row["reference_id"])
        pattern = json_load(row["pattern_json"], {})
        prompt_cards_for_reference = prompts_by_reference.get(reference_id, [])
        outcomes = _dedupe_outcomes(
            outcome
            for prompt in prompt_cards_for_reference
            for outcome in prompt["measuredOutcomeProvenance"]
        )
        card = {
            "id": str(row["id"]),
            "clusterKey": _cluster_key(row, pattern),
            "rank": int(row["rank"]) if row["rank"] is not None else None,
            "label": str(
                row["suggested_label"]
                or pattern.get("label")
                or _cluster_key(row, pattern).replace("::", " / ")
            ),
            "visualFormat": pattern.get("visualFormat") or row["visual_format"],
            "hookType": pattern.get("hookType") or row["hook_type"],
            "captionArchetype": pattern.get("captionArchetype")
            or row["caption_archetype"],
            "qualityScore": float(row["quality_score"] or 0.0),
            "referenceIds": [reference_id],
            "promptCardIds": [item["id"] for item in prompt_cards_for_reference],
            "captionPatternIds": [
                item["id"] for item in captions_by_reference.get(reference_id, [])
            ],
            "audioPatternIds": _matching_audio_pattern_ids(
                row, pattern, audio_patterns
            ),
            "pattern": pattern,
            "measuredExampleCount": _measured_example_count(outcomes),
            "recommendationStatus": _recommendation_status(outcomes, minimum),
            "measuredOutcomeProvenance": outcomes,
        }
        pattern_cards.append(card)
        patterns_by_reference[reference_id].append(card)

    gold_references: list[dict[str, Any]] = []
    for row in gold_rows:
        reference_id = str(row["reference_id"])
        prompts = prompts_by_reference.get(reference_id, [])
        patterns = patterns_by_reference.get(reference_id, [])
        outcomes = _dedupe_outcomes(
            outcome
            for prompt in prompts
            for outcome in prompt["measuredOutcomeProvenance"]
        )
        gold_references.append(
            {
                "referenceId": reference_id,
                "label": "gold",
                "account": row["account"],
                "localPath": row["path"],
                "contentHash": row["content_hash"],
                "tags": json_load(row["tags_json"], []),
                "notes": row["notes"],
                "promptCardIds": [item["id"] for item in prompts],
                "patternCardIds": [item["id"] for item in patterns],
                "captionPatternIds": [
                    item["id"] for item in captions_by_reference.get(reference_id, [])
                ],
                "measuredExampleCount": _measured_example_count(outcomes),
                "measuredOutcomeProvenance": outcomes,
            }
        )

    all_outcomes = _dedupe_outcomes(
        outcome
        for prompt in prompt_cards
        for outcome in prompt["measuredOutcomeProvenance"]
    )
    core = {
        "policy": {
            "humanGoldLabelsAuthoritative": True,
            "measuredFactsSource": MEASURED_FACTS_SOURCE,
            "minimumMeasuredExamplesForRecommendation": minimum,
        },
        "summary": {
            "goldReferenceCount": len(gold_references),
            "promptCardCount": len(prompt_cards),
            "patternCardCount": len(pattern_cards),
            "captionPatternCount": len(caption_patterns),
            "audioPatternCount": len(audio_patterns),
            "measuredExampleCount": _measured_example_count(all_outcomes),
            "eligiblePatternCount": sum(
                card["recommendationStatus"] == "eligible" for card in pattern_cards
            ),
            "advisoryPatternCount": sum(
                card["recommendationStatus"] == "advisory" for card in pattern_cards
            ),
        },
        "goldReferences": gold_references,
        "promptCards": prompt_cards,
        "patternCards": pattern_cards,
        "captionPatterns": caption_patterns,
        "audioPatterns": audio_patterns,
        "provenance": {
            "producer": "reference_factory",
            "sourceTables": [
                "audio_patterns",
                "caption_patterns",
                "generated_video_prompts",
                "prompt_post_outcomes",
                "reference_patterns",
                "review_labels",
                "source_files",
            ],
            "measuredFactsSource": MEASURED_FACTS_SOURCE,
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    pack = {
        "schema": KNOWLEDGE_PACK_SCHEMA,
        "packId": f"kp_{fingerprint[:16]}",
        "sourceFingerprint": fingerprint,
        "generatedAt": generated_at or now_iso(),
        **core,
    }
    validate_reference_factory_knowledge_pack(pack)
    if output_path is not None:
        path = Path(output_path).expanduser()
        atomic_write_text(
            path,
            json.dumps(pack, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return pack


def _gold_reference_rows(conn: Connection) -> list[Row]:
    return conn.execute(
        """
        SELECT sf.reference_id, sf.path, sf.account, sf.content_hash,
               rl.tags_json, rl.notes
        FROM source_files sf
        JOIN review_labels rl ON rl.reference_id = sf.reference_id
        WHERE rl.label = 'gold'
        ORDER BY sf.reference_id
        """
    ).fetchall()


def _rows_for_ids(conn: Connection, sql_template: str, ids: list[str]) -> list[Row]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.execute(
        sql_template.format(placeholders=placeholders), tuple(ids)
    ).fetchall()


def _outcomes_by_prompt(rows: list[Row]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(row["prompt_id"])].append(
            {
                "promptId": str(row["prompt_id"]),
                "postId": str(row["post_id"]),
                "rewardScore": float(row["reward_score"]),
                "confidence": (
                    float(row["confidence"]) if row["confidence"] is not None else None
                ),
                "sourceSnapshotAt": str(row["source_snapshot_at"]),
                "scoringVersion": str(row["scoring_version"]),
                "baselineProvenance": json_load(row["baseline_provenance_json"], {}),
                "outcome": json_load(row["outcome_json"], {}),
            }
        )
    return dict(result)


def _dedupe_outcomes(outcomes: Any) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for outcome in outcomes:
        key = (str(outcome["promptId"]), str(outcome["postId"]))
        by_key[key] = outcome
    return [by_key[key] for key in sorted(by_key)]


def _measured_example_count(outcomes: list[dict[str, Any]]) -> int:
    return len({str(outcome["postId"]) for outcome in outcomes})


def _recommendation_status(
    outcomes: list[dict[str, Any]], minimum_measured_examples: int
) -> str:
    return (
        "eligible"
        if _measured_example_count(outcomes) >= minimum_measured_examples
        else "advisory"
    )


def _cluster_key(row: Row, pattern: dict[str, Any]) -> str:
    explicit = pattern.get("clusterKey") or pattern.get("cluster_key")
    if explicit:
        return str(explicit)
    parts = [
        pattern.get("visualFormat") or row["visual_format"],
        pattern.get("hookType") or row["hook_type"],
        pattern.get("captionArchetype") or row["caption_archetype"],
    ]
    compact = [str(part).strip() for part in parts if str(part or "").strip()]
    return "::".join(compact) if compact else str(row["id"])


def _caption_pattern(row: Row) -> dict[str, Any]:
    return {
        "id": str(row["caption_hash"]),
        "referenceId": str(row["reference_id"]),
        "normalizedText": str(row["normalized_text"]),
        "firstLine": row["first_line"],
        "lineCount": int(row["line_count"] or 0),
        "characterCount": int(row["char_count"] or 0),
        "averageConfidence": (
            float(row["avg_confidence"]) if row["avg_confidence"] is not None else None
        ),
        "placement": json_load(row["placement_json"], {}),
    }


def _audio_pattern(row: Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "platform": str(row["platform"]),
        "audioId": str(row["audio_id"]),
        "audioTitle": row["audio_title"],
        "artistName": row["artist_name"],
        "usageType": str(row["usage_type"]),
        "visualFormat": row["visual_format"],
        "hookType": row["hook_type"],
        "captionArchetype": row["caption_archetype"],
        "postCount": int(row["post_count"] or 0),
        "recommendation": json_load(row["recommendation_json"], {}),
        "sourceSignal": {
            "totalPlays": int(row["total_plays"] or 0),
            "medianPlays": (
                int(row["median_plays"]) if row["median_plays"] is not None else None
            ),
        },
    }


def _matching_audio_pattern_ids(
    row: Row, pattern: dict[str, Any], audio_patterns: list[dict[str, Any]]
) -> list[str]:
    dimensions = (
        pattern.get("visualFormat") or row["visual_format"],
        pattern.get("hookType") or row["hook_type"],
        pattern.get("captionArchetype") or row["caption_archetype"],
    )
    return [
        item["id"]
        for item in audio_patterns
        if any(
            expected and expected == actual
            for expected, actual in zip(
                dimensions,
                (
                    item.get("visualFormat"),
                    item.get("hookType"),
                    item.get("captionArchetype"),
                ),
                strict=True,
            )
        )
    ]
