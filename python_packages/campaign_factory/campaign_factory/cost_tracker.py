"""AI cost tracking for Creator OS pipeline.

Records per-call cost estimates for Grok, Higgsfield, Kling, and Gemini.
All data lives in the Campaign Factory SQLite database.
"""

from __future__ import annotations

import datetime
import json
import math
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
    source_event_key TEXT,
    reservation_id  TEXT,
    campaign_id     TEXT,
    provider        TEXT NOT NULL,
    operation       TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    generations     INTEGER,
    amount          REAL,
    unit            TEXT,
    provider_quote_json TEXT,
    cohort_id       TEXT,
    estimated_cost_usd REAL NOT NULL,
    cost_state      TEXT NOT NULL DEFAULT 'estimated'
        CHECK(cost_state IN ('actual', 'estimated', 'unknown')),
    usd_cost_state  TEXT NOT NULL DEFAULT 'known'
        CHECK(usd_cost_state IN ('known', 'unknown')),
    unknown_reason  TEXT,
    metadata_json   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

CREATE_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_ai_cost_events_campaign
    ON ai_cost_events (campaign_id, created_at)
"""

CREATE_SOURCE_KEY_INDEX_SQL = """\
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_cost_events_source_key
    ON ai_cost_events (source_event_key)
    WHERE source_event_key IS NOT NULL
"""


def ensure_cost_table(conn: sqlite3.Connection) -> None:
    """Create the ai_cost_events table if it doesn't exist."""
    conn.executescript(f"{CREATE_TABLE_SQL};\n{CREATE_INDEX_SQL};")
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(ai_cost_events)").fetchall()
    }
    if "source_event_key" not in columns:
        conn.execute("ALTER TABLE ai_cost_events ADD COLUMN source_event_key TEXT")
    if "reservation_id" not in columns:
        conn.execute("ALTER TABLE ai_cost_events ADD COLUMN reservation_id TEXT")
    for column, column_type in (
        ("amount", "REAL"),
        ("unit", "TEXT"),
        ("provider_quote_json", "TEXT"),
        ("cohort_id", "TEXT"),
        (
            "cost_state",
            "TEXT NOT NULL DEFAULT 'estimated' "
            "CHECK(cost_state IN ('actual', 'estimated', 'unknown'))",
        ),
        (
            "usd_cost_state",
            "TEXT NOT NULL DEFAULT 'known' "
            "CHECK(usd_cost_state IN ('known', 'unknown'))",
        ),
        ("unknown_reason", "TEXT"),
    ):
        if column not in columns:
            conn.execute(
                f"ALTER TABLE ai_cost_events ADD COLUMN {column} {column_type}"
            )
    conn.execute(
        """
        UPDATE ai_cost_events
        SET cost_state = 'actual',
            usd_cost_state = 'unknown',
            unknown_reason = COALESCE(
                unknown_reason, 'provider_cost_not_attributable'
            )
        WHERE estimated_cost_usd = 0
          AND amount IS NOT NULL
          AND upper(COALESCE(unit, '')) <> 'USD'
        """
    )
    conn.execute(
        """
        UPDATE ai_cost_events
        SET cost_state = 'unknown',
            usd_cost_state = 'unknown',
            unknown_reason = COALESCE(
                unknown_reason, 'provider_cost_not_attributable'
            )
        WHERE estimated_cost_usd = 0
          AND amount IS NULL
          AND input_tokens IS NULL
          AND output_tokens IS NULL
          AND generations IS NULL
        """
    )
    conn.execute(CREATE_SOURCE_KEY_INDEX_SQL)


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
    source_event_key: str | None = None,
    reservation_id: str | None = None,
    amount: float | None = None,
    unit: str | None = None,
    provider_quote: dict[str, Any] | None = None,
    cohort_id: str | None = None,
    ensure_schema: bool = True,
) -> str:
    """Record an AI cost event and return the event ID."""
    if ensure_schema:
        ensure_cost_table(conn)
    if source_event_key:
        existing = conn.execute(
            "SELECT id FROM ai_cost_events WHERE source_event_key = ?",
            (source_event_key,),
        ).fetchone()
        if existing:
            return existing[0]

    if amount is not None:
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(float(amount))
            or float(amount) < 0
        ):
            raise ValueError("amount must be finite and non-negative")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError("unit is required when amount is provided")
        amount = float(amount)
        unit = unit.strip()
    elif unit is not None:
        raise ValueError("amount is required when unit is provided")

    cost_state = "actual" if amount is not None else "estimated"
    usd_cost_state = "known"
    unknown_reason: str | None = None
    if estimated_cost_usd is None:
        if input_tokens is not None or output_tokens is not None:
            pricing = PROVIDER_PRICING.get(provider, {})
            if "input_per_1m" in pricing or "output_per_1m" in pricing:
                estimated_cost_usd = estimate_token_cost(
                    provider,
                    input_tokens=input_tokens or 0,
                    output_tokens=output_tokens or 0,
                )
            else:
                cost_state = "unknown"
                usd_cost_state = "unknown"
                unknown_reason = "provider_pricing_unavailable"
        elif generations is not None:
            if "per_generation" in PROVIDER_PRICING.get(provider, {}):
                estimated_cost_usd = estimate_generation_cost(provider, generations)
            else:
                cost_state = "unknown"
                usd_cost_state = "unknown"
                unknown_reason = "provider_pricing_unavailable"
        elif amount is not None and unit == "USD":
            estimated_cost_usd = amount
        else:
            cost_state = "actual" if amount is not None else "unknown"
            usd_cost_state = "unknown"
            unknown_reason = "provider_cost_not_attributable"
        # Compatibility: historical schemas require a numeric sentinel. Reports
        # must consult cost_state and never present this as a known zero cost.
        if estimated_cost_usd is None:
            estimated_cost_usd = 0.0
    if (
        isinstance(estimated_cost_usd, bool)
        or not isinstance(estimated_cost_usd, (int, float))
        or not math.isfinite(float(estimated_cost_usd))
        or float(estimated_cost_usd) < 0
    ):
        raise ValueError("estimated_cost_usd must be finite and non-negative")
    estimated_cost_usd = float(estimated_cost_usd)

    event_id = (
        f"cost_{uuid.uuid5(uuid.NAMESPACE_URL, source_event_key).hex[:12]}"
        if source_event_key
        else f"cost_{uuid.uuid4().hex[:12]}"
    )
    created_at = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute(
        """\
        INSERT OR IGNORE INTO ai_cost_events
            (id, source_event_key, reservation_id, campaign_id, provider, operation,
             input_tokens, output_tokens, generations,
             amount, unit, provider_quote_json, cohort_id,
             estimated_cost_usd, cost_state, usd_cost_state, unknown_reason,
             metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            source_event_key,
            reservation_id,
            campaign_id,
            provider,
            operation,
            input_tokens,
            output_tokens,
            generations,
            amount,
            unit,
            json.dumps(provider_quote, sort_keys=True) if provider_quote else None,
            cohort_id,
            estimated_cost_usd,
            cost_state,
            usd_cost_state,
            unknown_reason,
            json.dumps(metadata) if metadata else None,
            created_at,
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
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
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
            SUM(CASE WHEN usd_cost_state = 'known'
                THEN estimated_cost_usd ELSE 0 END)
                as known_cost_usd,
            SUM(CASE WHEN usd_cost_state = 'unknown' THEN 1 ELSE 0 END)
                as unknown_calls,
            SUM(CASE WHEN cost_state = 'actual' THEN 1 ELSE 0 END)
                as actual_calls,
            SUM(CASE WHEN cost_state = 'estimated' THEN 1 ELSE 0 END)
                as estimated_calls
        FROM ai_cost_events
        {where}
        GROUP BY provider, operation
        ORDER BY known_cost_usd DESC
        """,
        params,
    ).fetchall()

    total_cost = 0.0
    by_provider: dict[str, Any] = {}

    for row in rows:
        provider = row[0]
        known_cost = round(float(row[6] or 0.0), 4)
        unknown_calls = int(row[7] or 0)
        state = (
            "unknown"
            if unknown_calls == int(row[2])
            else ("partial_unknown" if unknown_calls else "known")
        )
        entry = {
            "operation": row[1],
            "calls": row[2],
            "input_tokens": row[3],
            "output_tokens": row[4],
            "generations": row[5],
            "cost_usd": None if unknown_calls else known_cost,
            "known_cost_usd": known_cost,
            "unknown_calls": unknown_calls,
            "cost_state": state,
            "actual_calls": int(row[8] or 0),
            "estimated_calls": int(row[9] or 0),
        }
        total_cost += known_cost
        by_provider.setdefault(provider, []).append(entry)

    # Grand total
    grand = conn.execute(
        f"""SELECT COUNT(*),
                   SUM(CASE WHEN usd_cost_state = 'known'
                       THEN estimated_cost_usd ELSE 0 END),
                   SUM(CASE WHEN usd_cost_state = 'unknown' THEN 1 ELSE 0 END)
            FROM ai_cost_events {where}""",
        params,
    ).fetchone()
    unknown_calls = int(grand[2] or 0)
    known_cost = round(float(grand[1] or 0.0), 4)

    return {
        "schema": "campaign_factory.cost_summary.v1",
        "total_calls": grand[0] or 0,
        "total_cost_usd": None if unknown_calls else known_cost,
        "known_cost_usd": known_cost,
        "unknown_calls": unknown_calls,
        "cost": {
            "amount": None if unknown_calls else known_cost,
            "currency": "USD" if not unknown_calls else None,
            "state": "unknown" if unknown_calls else "known",
            "reason": (
                "one_or_more_provider_costs_not_attributable" if unknown_calls else None
            ),
        },
        "by_provider": by_provider,
        "filters": {
            "campaign_id": campaign_id,
            "days": days,
        },
        "native_units": _native_unit_summary(conn, where=where, params=params),
    }


def _native_unit_summary(
    conn: sqlite3.Connection, *, where: str, params: list[Any]
) -> dict[str, float]:
    rows = conn.execute(
        f"""SELECT unit, SUM(amount) FROM ai_cost_events {where}
        {"AND" if where else "WHERE"} amount IS NOT NULL AND unit IS NOT NULL
        GROUP BY unit""",
        params,
    ).fetchall()
    return {str(row[0]): round(float(row[1] or 0.0), 4) for row in rows}
