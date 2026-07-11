#!/usr/bin/env python3
"""Write a read-only weekly Creator OS improvement digest from real outcomes."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from campaign_factory.performance_summary import PerformanceSummaryRepository

SCHEMA = "creator_os.weekly_improvement_digest.v1"
ACTIONABLE_LABELS = {
    "make_more_like_this": "expand",
    "stop_using": "retire",
    "good_views_bad_conversion_signal": "test_conversion_variant",
}
BOARD_LABELS = {
    "hooks": "hook",
    "recipes": "recipe",
    "audioRecommendations": "audio",
    "referenceFormats": "reference_format",
    "promptPatterns": "prompt_pattern",
    "captionFormulas": "caption_formula",
    "variationPresets": "variation_preset",
    "formatAudioCombos": "format_audio_combo",
    "hookRecipeCombos": "hook_recipe_combo",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def configured_campaigns(raw: str | None) -> list[str]:
    try:
        values = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise ValueError("campaigns must be a JSON array") from exc
    if not isinstance(values, list) or not values:
        raise ValueError("campaigns must be a non-empty JSON array")
    campaigns = [str(value).strip() for value in values]
    if not all(campaigns) or len(campaigns) != len(set(campaigns)):
        raise ValueError("campaigns must contain unique non-empty names")
    return campaigns


def _campaign_lookup(conn: sqlite3.Connection, slug: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM campaigns WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        raise ValueError(f"unknown campaign: {slug}")
    return dict(row)


def collect_performance_summaries(
    db_path: Path, campaigns: list[str]
) -> list[dict[str, Any]]:
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        repository = PerformanceSummaryRepository(
            conn,
            campaign_by_slug=lambda slug: _campaign_lookup(conn, slug),
            slugify=lambda value: value,
        )
        return [repository.performance_summary(campaign) for campaign in campaigns]


def _sample_count(item: dict[str, Any]) -> int:
    try:
        return int(((item.get("performance") or {}).get("count")) or 0)
    except (TypeError, ValueError):
        return 0


def actionable_recommendations(summary: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    leaderboards = summary.get("leaderboards") or {}
    for board, dimension in BOARD_LABELS.items():
        items = leaderboards.get(board) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            label = str(item.get("recommendation") or "")
            count = _sample_count(item)
            if label not in ACTIONABLE_LABELS or count < 3:
                continue
            output.append(
                {
                    "campaign": summary.get("campaign"),
                    "dimension": dimension,
                    "key": str(item.get("key") or "unknown"),
                    "action": ACTIONABLE_LABELS[label],
                    "evidence": {
                        "samples": count,
                        "score": item.get("score"),
                        "label": label,
                    },
                }
            )
    return sorted(
        output,
        key=lambda item: (
            -int(item["evidence"].get("samples") or 0),
            str(item["dimension"]),
            str(item["key"]),
        ),
    )[:8]


def weekly_spend(db_path: Path, *, now: datetime) -> dict[str, Any]:
    cutoff = (now - timedelta(days=7)).isoformat()
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT source, amount, unit, provider_quote_json, status
               FROM higgsfield_spend_reservations
               WHERE created_at >= ?""",
            (cutoff,),
        ).fetchall()
    consumed_credits = 0.0
    kling_credits = 0.0
    consumed_calls = 0
    kling_calls = 0
    for row in rows:
        if row["status"] != "consumed":
            continue
        amount = float(row["amount"] or 0) if row["unit"] == "credits" else 0.0
        consumed_credits += amount
        consumed_calls += 1
        quote = str(row["provider_quote_json"] or "").lower()
        source = str(row["source"] or "").lower()
        if "kling" in quote or "kling" in source:
            kling_credits += amount
            kling_calls += 1
    return {
        "windowDays": 7,
        "providerCalls": consumed_calls,
        "credits": round(consumed_credits, 3),
        "klingCalls": kling_calls,
        "klingCredits": round(kling_credits, 3),
        "klingRoiStatus": "awaiting_measured_outcomes"
        if kling_calls and not consumed_credits
        else "not_measurable_without_published_outcomes",
    }


def build_digest(
    summaries: list[dict[str, Any]], spend: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    snapshot_count = sum(int(item.get("snapshotCount") or 0) for item in summaries)
    recommendations = [
        recommendation
        for summary in summaries
        for recommendation in actionable_recommendations(summary)
    ][:8]
    if snapshot_count == 0:
        status = "awaiting_real_outcomes"
        next_actions = [
            "publish_operator_approved_cohort_posts",
            "collect_1h_and_24h_metrics",
            "keep_current_creative_configuration_until_evidence_exists",
        ]
    elif not recommendations:
        status = "collecting_reliable_signal"
        next_actions = [
            "continue_current_control_and_ranked_mix",
            "wait_for_at_least_three_samples_per_pattern",
        ]
    else:
        status = "recommendations_ready"
        next_actions = ["review_bounded_recommendations_before_applying"]
    line = (
        f"weekly improvement: {snapshot_count} measured snapshots | "
        f"{len(recommendations)} evidence-backed changes | "
        f"{spend.get('klingCredits', 0)} Kling credits | {status}"
    )
    return {
        "schema": SCHEMA,
        "generatedAt": now.isoformat(),
        "status": status,
        "line": line,
        "campaigns": [
            {
                "campaign": summary.get("campaign"),
                "snapshotCount": int(summary.get("snapshotCount") or 0),
            }
            for summary in summaries
        ],
        "recommendations": recommendations,
        "nextActions": next_actions,
        "spend": spend,
        "automaticChangesApplied": 0,
        "publishingActionsTaken": 0,
    }


def render_markdown(digest: dict[str, Any]) -> str:
    lines = [
        "# Creator OS Weekly Improvement Digest",
        "",
        f"Generated: {digest['generatedAt']}",
        f"Status: {digest['status']}",
        "",
        digest["line"],
        "",
        "## Recommendations",
        "",
    ]
    if digest["recommendations"]:
        for item in digest["recommendations"]:
            evidence = item["evidence"]
            lines.append(
                f"- {item['action']} `{item['dimension']}:{item['key']}` "
                f"({evidence['samples']} samples, score {evidence['score']})"
            )
    else:
        lines.append(
            "- No creative configuration change is justified by real outcomes yet."
        )
    lines.extend(["", "## Next actions", ""])
    lines.extend(f"- {item}" for item in digest["nextActions"])
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This report is read-only.",
            "- It does not generate assets, spend credits, schedule, or publish.",
            "",
        ]
    )
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def send_notify(notify_path: Path, line: str) -> None:
    if notify_path.exists():
        subprocess.run(
            [str(notify_path), "info", "weekly-improvement", line],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("CAMPAIGN_FACTORY_DB", "")),
    )
    parser.add_argument(
        "--campaigns", default=os.environ.get("CAMPAIGN_FACTORY_SYNC_CAMPAIGNS")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / ".creator-os" / "reports",
    )
    parser.add_argument(
        "--notify", type=Path, default=Path.home() / ".creator-os" / "notify.sh"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error("CAMPAIGN_FACTORY_DB must point to an existing database")
    campaigns = configured_campaigns(args.campaigns)
    now = utc_now()
    summaries = collect_performance_summaries(args.db, campaigns)
    digest = build_digest(summaries, weekly_spend(args.db, now=now), now=now)
    print(digest["line"])
    if not args.dry_run:
        stamp = now.date().isoformat()
        atomic_write(
            args.output_dir / f"weekly-improvement-{stamp}.json",
            json.dumps(digest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )
        atomic_write(
            args.output_dir / f"weekly-improvement-{stamp}.md",
            render_markdown(digest),
        )
        send_notify(args.notify.expanduser(), digest["line"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
