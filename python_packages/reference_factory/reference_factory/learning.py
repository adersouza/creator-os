from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .audio import cluster_audio_recommendations, extract_audio_signal
from .audio import analyze_audio_patterns
from .db import json_dump, json_load
from .identity import stable_id
from .patterns import analyze_patterns
from .timeutil import now_iso


LEARNING_VERSION = "reference_factory.learning_system.v1"


def build_learning_system(
    conn: Connection,
    limit: int = 300,
    output_dir: Path | None = None,
    refresh_patterns: bool = False,
) -> dict[str, object]:
    output_dir = output_dir or Path("learning")
    output_dir.mkdir(parents=True, exist_ok=True)
    if refresh_patterns or _pattern_count(conn) < min(limit, 1):
        analyze_patterns(conn, limit=limit, provider="auto", output_dir=output_dir)
    cards = _pattern_cards(conn, limit)
    clusters = _cluster_cards(cards)
    timestamp = now_iso()
    run_id = stable_id("learning_run", LEARNING_VERSION, str(limit), timestamp)
    summary = _learning_summary(cards, clusters)
    audio_summary = analyze_audio_patterns(conn, limit=limit, output_dir=output_dir)
    conn.execute(
        """
        INSERT INTO learning_runs (id, analyzer_version, limit_count, output_dir, summary_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (run_id, LEARNING_VERSION, limit, str(output_dir), json_dump(summary), timestamp),
    )
    for cluster in clusters:
        conn.execute(
            """
            INSERT INTO learning_clusters (
              id, run_id, cluster_key, rank, label, visual_format, hook_type,
              caption_archetype, item_count, avg_quality_score, total_plays,
              median_plays, account_count, top_reference_id, tags_json,
              pattern_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stable_id("learning_cluster", run_id, cluster["clusterKey"]),
                run_id,
                cluster["clusterKey"],
                cluster["rank"],
                cluster["label"],
                cluster["visualFormat"],
                cluster["hookType"],
                cluster["captionArchetype"],
                cluster["itemCount"],
                cluster["avgQualityScore"],
                cluster["totalPlays"],
                cluster["medianPlays"],
                cluster["accountCount"],
                cluster["topReferenceId"],
                json_dump(cluster["tags"]),
                json_dump(cluster),
                timestamp,
            ),
        )
    conn.commit()
    paths = _write_learning_outputs(output_dir, limit, run_id, cards, clusters, summary)
    return {
        "schema": "reference_factory.build_learning_system.v1",
        "runId": run_id,
        "limit": limit,
        "references": len(cards),
        "clusters": len(clusters),
        "summary": summary,
        "audioSummary": {
            "audioPatternCount": audio_summary["audioPatternCount"],
            "platforms": audio_summary["platforms"],
            "usageTypes": audio_summary["usageTypes"],
        },
        **paths,
    }


def learning_summary(conn: Connection, limit: int = 300) -> dict[str, object]:
    cards = _pattern_cards(conn, limit)
    clusters = _cluster_cards(cards)
    return {
        "schema": "reference_factory.learning_summary.v1",
        "limit": limit,
        "references": len(cards),
        "clusters": len(clusters),
        "summary": _learning_summary(cards, clusters),
        "topClusters": clusters[:10],
    }


def _pattern_count(conn: Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM reference_patterns").fetchone()[0])


def _pattern_cards(conn: Connection, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT rp.*, pp.owner_username, pp.short_code, pp.url, pp.caption,
               pp.video_play_count, pp.video_view_count, pp.likes_count, pp.comments_count,
               pp.match_type, pp.raw_json, pp.product_type, sf.path AS local_path, sf.account, sf.file_name
        FROM reference_patterns rp
        LEFT JOIN public_posts pp ON pp.id = rp.public_post_id
        LEFT JOIN source_files sf ON sf.reference_id = rp.reference_id
        ORDER BY COALESCE(rp.rank, 999999), rp.quality_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    cards = []
    for row in rows:
        pattern = json_load(row["pattern_json"], {})
        raw_json = json_load(row["raw_json"], {})
        cards.append(
            {
                "id": row["id"],
                "rank": row["rank"],
                "referenceId": row["reference_id"],
                "publicPostId": row["public_post_id"],
                "account": row["owner_username"] or row["account"],
                "shortCode": row["short_code"],
                "url": row["url"],
                "caption": row["caption"] or (pattern.get("caption") or {}).get("text"),
                "localPath": row["local_path"],
                "fileName": row["file_name"],
                "matchType": row["match_type"],
                "plays": int(row["video_play_count"] or row["video_view_count"] or 0),
                "views": int(row["video_view_count"] or 0),
                "likes": int(row["likes_count"] or 0),
                "comments": int(row["comments_count"] or 0),
                "measuredOutcome": (pattern.get("metrics") or {}).get("measuredOutcome"),
                "publicRateScore": (pattern.get("metrics") or {}).get("publicRateScore"),
                "qualityScore": float(row["quality_score"] or 0),
                "suggestedLabel": row["suggested_label"],
                "visualFormat": row["visual_format"],
                "hookType": row["hook_type"],
                "captionArchetype": row["caption_archetype"],
                "tags": list((pattern.get("reviewTags") or [])),
                "pattern": pattern,
                "audioSignal": extract_audio_signal(raw_json, row["product_type"]),
            }
        )
    return cards


def _cluster_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        key = _cluster_key(card)
        grouped[key].append(card)
    clusters = []
    for key, items in grouped.items():
        clusters.append(_cluster_from_items(key, items))
    clusters.sort(key=lambda item: (-item["clusterScore"], -item["itemCount"], item["label"]))
    for idx, cluster in enumerate(clusters, 1):
        cluster["rank"] = idx
    return clusters


def _cluster_key(card: dict[str, Any]) -> str:
    return "::".join(
        [
            str(card.get("visualFormat") or "unknown_visual"),
            str(card.get("hookType") or "unknown_hook"),
            str(card.get("captionArchetype") or "unknown_caption"),
        ]
    )


def _cluster_from_items(key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    visual, hook, caption = key.split("::")
    ranked = sorted(items, key=lambda item: (int(item.get("rank") or 999999), -float(item.get("qualityScore") or 0)))
    top = ranked[0]
    plays = [int(item.get("plays") or 0) for item in items]
    quality = [float(item.get("qualityScore") or 0) for item in items]
    accounts = sorted(set(str(item.get("account") or "_unknown") for item in items))
    tags = Counter(tag for item in items for tag in item.get("tags", []))
    captions = [str(item.get("caption") or "").strip() for item in ranked if str(item.get("caption") or "").strip()]
    measured_scores = [
        float((item.get("measuredOutcome") or {}).get("rewardScore"))
        for item in items
        if isinstance(item.get("measuredOutcome"), dict)
        and isinstance((item.get("measuredOutcome") or {}).get("rewardScore"), (int, float))
    ]
    cluster_score = _cluster_score(items, plays, quality, accounts, measured_scores)
    label = _cluster_label(visual, hook, caption)
    return {
        "schema": "reference_factory.learning_cluster.v1",
        "patternId": key,
        "clusterKey": key,
        "rank": 0,
        "label": label,
        "visualFormat": visual,
        "hookType": hook,
        "captionArchetype": caption,
        "itemCount": len(items),
        "avgQualityScore": round(sum(quality) / max(1, len(quality)), 2),
        "clusterScore": cluster_score,
        "totalPlays": sum(plays),
        "medianPlays": int(statistics.median(plays)) if plays else 0,
        "accountCount": len(accounts),
        "accounts": accounts,
        "tags": [tag for tag, _ in tags.most_common(12)],
        "topReferenceId": top.get("referenceId"),
        "topPublicPostId": top.get("publicPostId"),
        "topUrl": top.get("url"),
        "topLocalPath": top.get("localPath"),
        "referenceFiles": [item.get("localPath") for item in ranked[:8] if item.get("localPath")],
        "topExamples": [_compact_example(item) for item in ranked[:8]],
        "captionFormulas": _caption_formulas(caption, hook, captions),
        "visualRecipeHints": _visual_recipe_hints(visual, hook, caption),
        "suggestedVariantRecipes": _suggested_variant_recipes(visual, hook, caption),
        "suggestedFormats": _suggested_formats(visual, hook, caption),
        "audioRecommendations": cluster_audio_recommendations(items, visual, hook, caption),
        "performanceSignals": {
            "medianViews": int(statistics.median(plays)) if plays else 0,
            "totalPlays": sum(plays),
            "measuredOutcomeSamples": len(measured_scores),
            "avgMeasuredReward": round(sum(measured_scores) / len(measured_scores), 4) if measured_scores else None,
            "topAccounts": accounts[:10],
        },
        "promptTemplate": _prompt_template(visual, hook, caption),
        "higgsfieldJsonTemplate": _higgsfield_json_template(visual, hook, caption),
        "operatorUse": _operator_use(label, len(items), cluster_score),
    }


def _cluster_score(
    items: list[dict[str, Any]],
    plays: list[int],
    quality: list[float],
    accounts: list[str],
    measured_scores: list[float] | None = None,
) -> float:
    avg_quality = sum(quality) / max(1, len(quality))
    total_plays = sum(plays)
    play_score = min(25.0, math.log10(max(total_plays, 1)) * 3.2)
    count_score = min(16.0, len(items) * 1.5)
    diversity_score = min(12.0, len(accounts) * 1.4)
    outcome_score = 0.0
    if measured_scores:
        avg_measured = sum(measured_scores) / len(measured_scores)
        outcome_score = max(-8.0, min(18.0, (avg_measured - 1.0) * 20.0))
    return round((avg_quality * 0.47) + play_score + count_score + diversity_score + outcome_score, 2)


def _cluster_label(visual: str, hook: str, caption: str) -> str:
    return " / ".join(
        part.replace("_", " ")
        for part in [visual, hook, caption]
        if part and part != "unknown"
    )


def _visual_recipe_hints(visual: str, hook: str, caption: str) -> list[str]:
    hints = ["vertical 9:16", "clear first-second hook"]
    if caption != "captionless_visual":
        hints.append("center caption")
    if visual == "tiktok_slideshow":
        hints.extend(["grid collage", "first slide headline", "photo sequence", "centered bold callout", "native slideshow pacing"])
    if visual == "mirror_selfie":
        hints.append("mirror shot")
    if visual == "fit_check":
        hints.append("fit check reveal")
    if visual == "walking_clip":
        hints.append("natural walking motion")
    if hook in {"curiosity_gap", "direct_response"}:
        hints.append("caption appears immediately")
    return list(dict.fromkeys(hints))


def _suggested_variant_recipes(visual: str, hook: str, caption: str) -> list[str]:
    recipes = ["v01_original", "v05_hflip", "v06_zoom"]
    if visual == "tiktok_slideshow":
        recipes.extend(["slideshow_grid", "slideshow_story_cards", "slideshow_caption_callout"])
    if caption != "captionless_visual":
        recipes.append("v09_caption_bg")
    if visual in {"walking_clip", "short_vertical_visual_hook"}:
        recipes.append("v08_colorgrade_bright")
    if visual in {"mirror_selfie", "fit_check"}:
        recipes.append("v07_tilt")
    return list(dict.fromkeys(recipes))


def _suggested_formats(visual: str, hook: str, caption: str) -> list[str]:
    if visual == "tiktok_slideshow":
        return ["slideshow", "reel"]
    formats = ["reel"]
    if visual in {"mirror_selfie", "fit_check", "caption_led_visual"} or caption != "captionless_visual":
        formats.append("slideshow")
    return formats


def _compact_example(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": item.get("rank"),
        "referenceId": item.get("referenceId"),
        "account": item.get("account"),
        "url": item.get("url"),
        "localPath": item.get("localPath"),
        "plays": item.get("plays"),
        "likes": item.get("likes"),
        "comments": item.get("comments"),
        "caption": item.get("caption"),
        "qualityScore": item.get("qualityScore"),
    }


def _caption_formulas(caption_archetype: str, hook_type: str, examples: list[str]) -> list[dict[str, object]]:
    base = {
        "short_meme_caption": [
            "{pronoun/persona} can't resist {persona/context} {emoji}",
            "{short claim} + one emoji",
            "{direct tease} with no explanation",
        ],
        "question_hook": [
            "{direct question}?",
            "can i {action/phrase}?",
            "would you {viewer action}?",
        ],
        "hashtag_context": [
            "{short tease}\\n•\\n•\\n•\\n{optional context}",
            "{one-line setup} + sparse separator lines",
        ],
        "minimal_bait": [
            "{1-3 emoji}",
            "{one word}?",
            "{two-word reaction}",
        ],
        "cta_bait": [
            "{light command}!",
            "follow {persona action}",
        ],
        "captionless_visual": [
            "no overlay",
            "one tiny reaction caption only if needed",
        ],
    }.get(caption_archetype, ["{short original hook}", "{one-line curiosity gap}"])
    return [
        {
            "formula": formula,
            "hookType": hook_type,
            "exampleCaptions": examples[:5],
        }
        for formula in base
    ]


def _prompt_template(visual: str, hook: str, caption: str) -> dict[str, str]:
    return {
        "visualBrief": {
            "caption_led_visual": "simple vertical creator shot composed around a readable centered caption",
            "walking_clip": "natural vertical walking clip with subject movement entering the hook immediately",
            "mirror_selfie": "mirror-shot phone reel with immediate outfit/body framing",
            "fit_check": "fit-check reel with direct reveal and simple background",
            "bedroom_static": "bedroom setup with close framing and one clear visual beat",
            "short_vertical_visual_hook": "short vertical clip with strong first-frame visual hook",
            "tiktok_slideshow": "TikTok-style slideshow carousel: fast hook slide, 5-9 visual cards, centered bold callouts, and native photo-dump pacing",
        }.get(visual, "vertical creator reel with clear first-second hook"),
        "hookBrief": {
            "curiosity_gap": "make the first caption/visual raise a simple unanswered question",
            "direct_response": "make the viewer want to answer immediately",
            "action_prompt": "use a light action prompt or command",
            "visual_first": "let the visual carry the hook with little or no text",
            "viewer_insert": "frame the viewer inside the scenario",
        }.get(hook, "one clear hook in the first second"),
        "captionBrief": {
            "short_meme_caption": "short meme caption with compact wording",
            "question_hook": "short direct question",
            "hashtag_context": "short tease with optional sparse separator lines",
            "minimal_bait": "tiny emoji or one-line bait",
            "cta_bait": "short action prompt",
            "captionless_visual": "no caption or minimal overlay",
        }.get(caption, "short original caption"),
    }


def _higgsfield_json_template(visual: str, hook: str, caption: str) -> dict[str, object]:
    template = _prompt_template(visual, hook, caption)
    output_format = "vertical_slideshow" if visual == "tiktok_slideshow" else "vertical_reel"
    duration = "6-10" if visual == "tiktok_slideshow" else "6-12"
    return {
        "format": output_format,
        "duration_seconds": duration,
        "scene": template["visualBrief"],
        "camera": "phone-shot vertical video, natural handheld motion, social reel pacing",
        "action": template["hookBrief"],
        "caption_overlay": template["captionBrief"],
        "audio_direction": "plan native platform audio separately; match the sound vibe to the visual format and hook instead of hard-burning unknown audio",
        "style": "high-performing Instagram Reels reference pattern",
        "reference_match_goal": "close_format_variation",
        "variation_controls": {
            "keep": ["structure", "pacing", "hook timing", "caption placement style"],
            "vary": ["model identity", "background details", "wording", "exact gesture", "wardrobe"],
        },
        "negative_prompt": "logos, watermarks, broken anatomy, unreadable text, low resolution, underage appearance",
    }


def _operator_use(label: str, item_count: int, score: float) -> dict[str, object]:
    return {
        "recommendedUse": "primary_generation_pattern" if item_count >= 8 and score >= 85 else "secondary_generation_pattern",
        "batchIdea": f"Use this cluster as a source format for {min(10, max(3, item_count // 2))} initial variants.",
        "reviewInstruction": f"Compare outputs against the '{label}' pattern with ContentForge reference match.",
    }


def _learning_summary(cards: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> dict[str, object]:
    return {
        "schema": "reference_factory.learning_system_summary.v1",
        "referenceCount": len(cards),
        "clusterCount": len(clusters),
        "topClusterLabels": [cluster["label"] for cluster in clusters[:10]],
        "captionArchetypes": dict(Counter(card.get("captionArchetype") for card in cards).most_common()),
        "hookTypes": dict(Counter(card.get("hookType") for card in cards).most_common()),
        "visualFormats": dict(Counter(card.get("visualFormat") for card in cards).most_common()),
        "topAccounts": dict(Counter(card.get("account") for card in cards).most_common(20)),
        "avgQualityScore": round(sum(float(card.get("qualityScore") or 0) for card in cards) / max(1, len(cards)), 2),
        "totalPlays": sum(int(card.get("plays") or 0) for card in cards),
    }


def _write_learning_outputs(
    output_dir: Path,
    limit: int,
    run_id: str,
    cards: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    summary: dict[str, object],
) -> dict[str, str]:
    clusters_json = output_dir / f"learning_clusters_top{limit}.json"
    clusters_jsonl = output_dir / f"learning_clusters_top{limit}.jsonl"
    playbook_json = output_dir / f"reference_playbook_top{limit}.json"
    playbook_md = output_dir / f"reference_playbook_top{limit}.md"
    prompt_pack_json = output_dir / f"higgsfield_prompt_pack_top{limit}.json"
    prompt_pack_jsonl = output_dir / f"higgsfield_prompt_pack_top{limit}.jsonl"
    campaign_bank = output_dir / "campaign_reference_bank.json"
    caption_bank = output_dir / "caption_formula_bank.json"

    clusters_payload = {
        "schema": "reference_factory.learning_clusters.v1",
        "runId": run_id,
        "limit": limit,
        "count": len(clusters),
        "clusters": clusters,
    }
    prompt_pack = _prompt_pack(run_id, clusters)
    caption_formulas = _caption_bank(clusters)
    playbook = {
        "schema": "reference_factory.reference_playbook.v1",
        "runId": run_id,
        "limit": limit,
        "summary": summary,
        "topClusters": clusters[:20],
        "captionFormulaBank": caption_formulas,
    }
    campaign_payload = _campaign_reference_bank(run_id, clusters)

    clusters_json.write_text(json.dumps(clusters_payload, indent=2, ensure_ascii=False) + "\n")
    with clusters_jsonl.open("w", encoding="utf-8") as f:
        for cluster in clusters:
            f.write(json.dumps(cluster, ensure_ascii=False, sort_keys=True) + "\n")
    playbook_json.write_text(json.dumps(playbook, indent=2, ensure_ascii=False) + "\n")
    playbook_md.write_text(_playbook_markdown(playbook), encoding="utf-8")
    prompt_pack_json.write_text(json.dumps(prompt_pack, indent=2, ensure_ascii=False) + "\n")
    with prompt_pack_jsonl.open("w", encoding="utf-8") as f:
        for prompt in prompt_pack["prompts"]:
            f.write(json.dumps(prompt, ensure_ascii=False, sort_keys=True) + "\n")
    campaign_bank.write_text(json.dumps(campaign_payload, indent=2, ensure_ascii=False) + "\n")
    caption_bank.write_text(json.dumps(caption_formulas, indent=2, ensure_ascii=False) + "\n")
    return {
        "clustersJsonPath": str(clusters_json),
        "clustersJsonlPath": str(clusters_jsonl),
        "playbookJsonPath": str(playbook_json),
        "playbookMarkdownPath": str(playbook_md),
        "promptPackJsonPath": str(prompt_pack_json),
        "promptPackJsonlPath": str(prompt_pack_jsonl),
        "campaignReferenceBankPath": str(campaign_bank),
        "captionFormulaBankPath": str(caption_bank),
    }


def _prompt_pack(run_id: str, clusters: list[dict[str, Any]]) -> dict[str, object]:
    prompts = []
    for cluster in clusters:
        prompts.append(
            {
                "schema": "reference_factory.higgsfield_prompt_card.v1",
                "runId": run_id,
                "clusterRank": cluster["rank"],
                "patternId": cluster.get("patternId") or cluster["clusterKey"],
                "clusterKey": cluster["clusterKey"],
                "clusterLabel": cluster["label"],
                "referenceIds": [
                    example["referenceId"]
                    for example in cluster["topExamples"]
                    if example.get("referenceId")
                ],
                "publicUrls": [example["url"] for example in cluster["topExamples"] if example.get("url")],
        "referenceFiles": cluster.get("referenceFiles") or [],
        "higgsfieldJson": cluster["higgsfieldJsonTemplate"],
        "audioRecommendations": cluster.get("audioRecommendations") or {},
        "captionFormulas": cluster["captionFormulas"],
                "visualRecipeHints": cluster.get("visualRecipeHints") or [],
                "suggestedVariantRecipes": cluster.get("suggestedVariantRecipes") or [],
                "suggestedFormats": cluster.get("suggestedFormats") or ["reel"],
                "performanceSignals": cluster.get("performanceSignals") or {},
                "referenceMatchGoal": "close_format_variation",
            }
        )
    return {
        "schema": "reference_factory.higgsfield_prompt_pack.v1",
        "runId": run_id,
        "count": len(prompts),
        "prompts": prompts,
    }


def _caption_bank(clusters: list[dict[str, Any]]) -> dict[str, object]:
    formulas: dict[str, list[dict[str, object]]] = defaultdict(list)
    for cluster in clusters:
        formulas[cluster["captionArchetype"]].extend(cluster["captionFormulas"])
    return {
        "schema": "reference_factory.caption_formula_bank.v1",
        "captionArchetypes": {
            archetype: values[:12]
            for archetype, values in sorted(formulas.items())
        },
    }


def _campaign_reference_bank(run_id: str, clusters: list[dict[str, Any]]) -> dict[str, object]:
    return {
        "schema": "reference_factory.campaign_reference_bank.v1",
        "runId": run_id,
        "usage": "Campaign Factory can use these clusters as selectable reference patterns.",
        "clusters": [
            {
                "clusterRank": cluster["rank"],
                "patternId": cluster.get("patternId") or cluster["clusterKey"],
                "clusterKey": cluster["clusterKey"],
                "label": cluster["label"],
                "referenceIds": [
                    example["referenceId"]
                    for example in cluster["topExamples"]
                    if example.get("referenceId")
                ],
                "localPaths": [
                    example["localPath"]
                    for example in cluster["topExamples"]
                    if example.get("localPath")
                ],
                "referenceFiles": cluster.get("referenceFiles") or [],
                "referenceMatchGoal": "close_format_variation",
                "captionArchetype": cluster["captionArchetype"],
                "hookType": cluster["hookType"],
                "visualFormat": cluster["visualFormat"],
                "captionFormulas": cluster.get("captionFormulas") or [],
                "visualRecipeHints": cluster.get("visualRecipeHints") or [],
                "suggestedVariantRecipes": cluster.get("suggestedVariantRecipes") or [],
                "suggestedFormats": cluster.get("suggestedFormats") or ["reel"],
                "performanceSignals": cluster.get("performanceSignals") or {},
                "audioRecommendations": cluster.get("audioRecommendations") or {},
                "promptTemplate": cluster["promptTemplate"],
            }
            for cluster in clusters
        ],
    }


def _playbook_markdown(playbook: dict[str, Any]) -> str:
    lines = [
        "# Reference Factory Playbook",
        "",
        f"References: {playbook['summary']['referenceCount']}",
        f"Clusters: {playbook['summary']['clusterCount']}",
        f"Total plays: {playbook['summary']['totalPlays']}",
        "",
        "## Top Clusters",
        "",
    ]
    for cluster in playbook["topClusters"]:
        lines.extend(
            [
                f"### {cluster['rank']}. {cluster['label']}",
                "",
                f"- Items: {cluster['itemCount']}",
                f"- Cluster score: {cluster['clusterScore']}",
                f"- Total plays: {cluster['totalPlays']}",
                f"- Accounts: {cluster['accountCount']}",
                f"- Tags: {', '.join(cluster['tags']) if cluster['tags'] else 'none'}",
                f"- Use: {cluster['operatorUse']['recommendedUse']}",
                f"- Audio: {cluster.get('audioRecommendations', {}).get('fallbackInstruction', 'use current native platform audio')}",
                "",
                "**Prompt template**",
                "",
                f"- Visual: {cluster['promptTemplate']['visualBrief']}",
                f"- Hook: {cluster['promptTemplate']['hookBrief']}",
                f"- Caption: {cluster['promptTemplate']['captionBrief']}",
                "",
                "**Top examples**",
                "",
            ]
        )
        for example in cluster["topExamples"][:5]:
            lines.append(
                f"- rank {example['rank']} | {example['account']} | {example['plays']} plays | {example.get('url') or example.get('localPath')}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"
