"""AI cost tracking for Creator OS pipeline.

Records per-call cost estimates for Grok, Higgsfield, Kling, and Gemini.
All data lives in the Campaign Factory SQLite database.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from typing import Any

# ── Provider pricing (USD estimates, updated June 2026) ──────────────
# These are approximate and should be updated as provider pricing changes.

PROVIDER_PRICING: dict[str, dict[str, float]] = {
    "grok": {
        # xAI Grok 4.3 — per 1M tokens
        "input_per_1m": 3.00,
        "output_per_1m": 15.00,
    },
    "gemini": {
        # Google Gemini 2.5 Pro — per 1M tokens
        "input_per_1m": 1.25,
        "output_per_1m": 10.00,
    },
    "higgsfield": {
        # Higgsfield Soul v2 — per image grid
        "per_generation": 0.05,
    },
    "kling": {
        # Kling 3.0 — per 5s video
        "per_generation": 0.10,
    },
}

# ── Schema ───────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS ai_cost_events (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT,
    provider        TEXT NOT NULL,
    operation       TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    generations     INTEGER,
    estimated_cost_usd REAL NOT NULL,
    metadata_json   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

CREATE_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_ai_cost_events_campaign
    ON ai_cost_events (campaign_id, created_at)
"""


def ensure_cost_table(conn: sqlite3.Connection) -> None:
    """Create the ai_cost_events table if it doesn't exist."""
    conn.executescript(f"{CREATE_TABLE_SQL};\n{CREATE_INDEX_SQL};")


# ── Cost estimation ──────────────────────────────────────────────────

def estimate_token_cost(
    provider: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """Estimate cost in USD for a token-based provider call."""
    pricing = PROVIDER_PRICING.get(provider, {})
    input_rate = pricing.get("input_per_1m", 0.0)
    output_rate = pricing.get("output_per_1m", 0.0)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def estimate_generation_cost(
    provider: str,
    generations: int = 1,
) -> float:
    """Estimate cost in USD for a per-generation provider call."""
    pricing = PROVIDER_PRICING.get(provider, {})
    per_gen = pricing.get("per_generation", 0.0)
    return generations * per_gen


# ── Recording ────────────────────────────────────────────────────────

def record_ai_cost(
    conn: sqlite3.Connection,
    *,
    provider: str,
    operation: str,
    campaign_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    generations: int | None = None,
    estimated_cost_usd: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Record an AI cost event and return the event ID."""
    ensure_cost_table(conn)

    if estimated_cost_usd is None:
        if input_tokens is not None or output_tokens is not None:
            estimated_cost_usd = estimate_token_cost(
                provider,
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
            )
        elif generations is not None:
            estimated_cost_usd = estimate_generation_cost(provider, generations)
        else:
            estimated_cost_usd = 0.0

    event_id = f"cost_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """\
        INSERT INTO ai_cost_events
            (id, campaign_id, provider, operation,
             input_tokens, output_tokens, generations,
             estimated_cost_usd, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            campaign_id,
            provider,
            operation,
            input_tokens,
            output_tokens,
            generations,
            estimated_cost_usd,
            json.dumps(metadata) if metadata else None,
        ),
    )
    conn.commit()
    return event_id


# ── Reporting ────────────────────────────────────────────────────────

def cost_summary(
    conn: sqlite3.Connection,
    *,
    campaign_id: str | None = None,
    days: int | None = None,
) -> dict[str, Any]:
    """Generate a cost summary grouped by provider and operation."""
    ensure_cost_table(conn)

    clauses: list[str] = []
    params: list[Any] = []

    if campaign_id:
        clauses.append("campaign_id = ?")
        params.append(campaign_id)
    if days:
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%S")
        clauses.append("created_at >= ?")
        params.append(cutoff)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = conn.execute(
        f"""\
        SELECT
            provider,
            operation,
            COUNT(*) as call_count,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(generations) as total_generations,
            SUM(estimated_cost_usd) as total_cost_usd
        FROM ai_cost_events
        {where}
        GROUP BY provider, operation
        ORDER BY total_cost_usd DESC
        """,
        params,
    ).fetchall()

    total_cost = 0.0
    by_provider: dict[str, Any] = {}

    for row in rows:
        provider = row[0]
        entry = {
            "operation": row[1],
            "calls": row[2],
            "input_tokens": row[3],
            "output_tokens": row[4],
            "generations": row[5],
            "cost_usd": round(row[6], 4),
        }
        total_cost += row[6]
        by_provider.setdefault(provider, []).append(entry)

    # Grand total
    grand = conn.execute(
        f"SELECT COUNT(*), SUM(estimated_cost_usd) FROM ai_cost_events {where}",
        params,
    ).fetchone()

    return {
        "total_calls": grand[0] or 0,
        "total_cost_usd": round(grand[1] or 0.0, 4),
        "by_provider": by_provider,
        "filters": {
            "campaign_id": campaign_id,
            "days": days,
        },
    }


def format_cost_report(summary: dict[str, Any]) -> str:
    """Format a cost summary as a human-readable report."""
    lines = [
        "═══ AI Cost Report ═══",
        f"Total calls: {summary['total_calls']}",
        f"Total cost:  ${summary['total_cost_usd']:.4f} USD",
    ]

    filters = summary.get("filters", {})
    if filters.get("campaign_id"):
        lines.append(f"Campaign:    {filters['campaign_id']}")
    if filters.get("days"):
        lines.append(f"Period:      last {filters['days']} days")

    lines.append("")

    for provider, ops in summary.get("by_provider", {}).items():
        provider_total = sum(o["cost_usd"] for o in ops)
        lines.append(f"── {provider} (${provider_total:.4f}) ──")
        for op in ops:
            tokens_str = ""
            if op.get("input_tokens"):
                tokens_str = f"  [{op['input_tokens']:,} in / {op['output_tokens'] or 0:,} out tokens]"
            elif op.get("generations"):
                tokens_str = f"  [{op['generations']:,} generations]"
            lines.append(
                f"  {op['operation']}: {op['calls']} calls = ${op['cost_usd']:.4f}{tokens_str}"
            )
        lines.append("")

    return "\n".join(lines)
