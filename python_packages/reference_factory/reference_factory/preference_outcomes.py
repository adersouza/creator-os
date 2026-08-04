"""Feed published post outcomes back into the operator preference profile.

Reference Factory owns published outcomes, and Campaign Factory is forbidden
from importing it, so measured performance reaches prompt authoring by being
written into the operator preference profile artifact as ``outcomeWeights``.
Campaign Factory's reference selection then reorders items the operator already
rated selectable.

The operator's own score and written note always dominate: weights are clamped
to a band narrower than one rating step, so measured performance can reorder
items inside a score tier but can never promote a rejected reference or demote
a master below a weaker one.
"""

from __future__ import annotations

import json
from pathlib import Path
from sqlite3 import Connection
from typing import Any

WEIGHT_LIMIT = 0.9
MINIMUM_SAMPLES = 3


def _item_reference_key(item_id: str) -> str:
    """``reel:Dbjps06N5c2`` -> ``Dbjps06N5c2`` (kind prefix stripped)."""

    _, _, remainder = item_id.partition(":")
    return remainder or item_id


def preference_outcome_weights(
    conn: Connection, profile: dict[str, Any]
) -> dict[str, float]:
    """Return itemId -> clamped reward delta, from measured post outcomes.

    Only references with at least ``MINIMUM_SAMPLES`` published samples earn a
    weight; anything thinner stays at the operator's prior alone.
    """

    rows = conn.execute(
        """
        SELECT reference_id,
               AVG(outcome_reward_score) AS reward,
               SUM(outcome_sample_count) AS samples
          FROM generated_video_prompts
         WHERE outcome_reward_score IS NOT NULL
         GROUP BY reference_id
        """
    ).fetchall()
    measured: dict[str, tuple[float, int]] = {}
    for row in rows:
        reference_id = str(row[0] or "")
        if not reference_id:
            continue
        measured[reference_id] = (float(row[1] or 0.0), int(row[2] or 0))
    if not measured:
        return {}
    rewards = [
        reward for reward, samples in measured.values() if samples >= MINIMUM_SAMPLES
    ]
    if not rewards:
        return {}
    midpoint = sum(rewards) / len(rewards)
    spread = max(max(rewards) - midpoint, midpoint - min(rewards)) or 1.0
    weights: dict[str, float] = {}
    for item in profile.get("items", []):
        key = _item_reference_key(str(item.get("itemId") or ""))
        entry = measured.get(key)
        if entry is None:
            continue
        reward, samples = entry
        if samples < MINIMUM_SAMPLES:
            continue
        delta = (reward - midpoint) / spread * WEIGHT_LIMIT
        weights[str(item["itemId"])] = round(
            max(-WEIGHT_LIMIT, min(WEIGHT_LIMIT, delta)), 4
        )
    return weights


def refresh_preference_outcome_weights(
    conn: Connection, profile_path: Path
) -> dict[str, Any]:
    """Recompute and persist ``outcomeWeights`` on the preference profile.

    The operator's raw ratings and notes are never rewritten; only the derived
    weight map is replaced.
    """

    path = Path(profile_path).expanduser()
    profile = json.loads(path.read_text(encoding="utf-8"))
    weights = preference_outcome_weights(conn, profile)
    if weights:
        profile["outcomeWeights"] = weights
    else:
        profile.pop("outcomeWeights", None)
    path.write_text(
        json.dumps(profile, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "collectionId": profile.get("collectionId"),
        "sourceFingerprint": profile.get("sourceFingerprint"),
        "weightedItems": len(weights),
    }
