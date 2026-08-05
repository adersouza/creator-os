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
import statistics
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from creator_os_core.fileops import atomic_write_text, file_lock

WEIGHT_LIMIT = 0.9
MINIMUM_SAMPLES = 3
# Operator rule: never learn from bad performing posts. A reference is only
# promoted by evidence that it performed at or above the measured median; weak
# performers are dropped from the calculation entirely rather than being used to
# demote a reference. A flop is usually the caption, audio, or timing, not the
# reference structure, so treating it as evidence against the reference teaches
# the wrong lesson. Weights are therefore non-negative by construction.
# Qualifying floor: the median measured reward.


def _item_reference_key(item_id: str) -> str:
    """``reel:Dbjps06N5c2`` -> ``Dbjps06N5c2`` (kind prefix stripped)."""

    _, _, remainder = item_id.partition(":")
    return remainder or item_id


def preference_outcome_weights(
    conn: Connection, profile: dict[str, Any]
) -> dict[str, float]:
    """Return itemId -> non-negative reward boost, from measured post outcomes.

    Only references with at least ``MINIMUM_SAMPLES`` published samples earn a
    weight; anything thinner stays at the operator's prior alone. Only
    at-or-above-median performers earn anything at all - bad posts are excluded,
    never used to push a reference down.
    """

    # Preference itemIds carry the platform shortcode (``reel:DbV65c5sn2b``),
    # but generated_video_prompts is keyed by the internal reference_id
    # (``ref_url_<hash>``). The shortcode lives in source_files.native_media_id,
    # so the join has to go through source_files or it can never match.
    rows = conn.execute(
        """
        SELECT gvp.reference_id,
               sf.native_media_id,
               AVG(gvp.outcome_reward_score) AS reward,
               SUM(gvp.outcome_sample_count) AS samples
          FROM generated_video_prompts AS gvp
          LEFT JOIN source_files AS sf
                 ON sf.reference_id = gvp.reference_id
         WHERE gvp.outcome_reward_score IS NOT NULL
         GROUP BY gvp.reference_id, sf.native_media_id
        """
    ).fetchall()
    measured: dict[str, tuple[float, int]] = {}
    for row in rows:
        reward, samples = float(row[2] or 0.0), int(row[3] or 0)
        # Index under both keys so items keyed by shortcode and items keyed by
        # the internal reference id both resolve.
        for key in (str(row[0] or ""), str(row[1] or "")):
            if key:
                measured[key] = (reward, samples)
    if not measured:
        return {}
    rewards = [
        reward for reward, samples in measured.values() if samples >= MINIMUM_SAMPLES
    ]
    if not rewards:
        return {}
    floor = statistics.median(rewards)
    ceiling = max(rewards)
    spread = ceiling - floor
    weights: dict[str, float] = {}
    for item in profile.get("items", []):
        key = _item_reference_key(str(item.get("itemId") or ""))
        entry = measured.get(key)
        if entry is None:
            continue
        reward, samples = entry
        if samples < MINIMUM_SAMPLES:
            continue
        if reward < floor:
            # Underperformed: contributes nothing. The operator's own rating
            # continues to stand on its own for this reference.
            continue
        # At or above median. Scale within the qualifying band; when every
        # qualifier ties, they all earn the same modest boost.
        boost = (
            (reward - floor) / spread * WEIGHT_LIMIT if spread > 0 else WEIGHT_LIMIT / 2
        )
        weights[str(item["itemId"])] = round(min(WEIGHT_LIMIT, max(0.0, boost)), 4)
    return weights


def refresh_preference_outcome_weights(
    conn: Connection, profile_path: Path
) -> dict[str, Any]:
    """Recompute and persist ``outcomeWeights`` on the preference profile.

    The operator's raw ratings and notes are never rewritten; only the derived
    weight map is replaced.
    """

    path = Path(profile_path).expanduser()
    # The profile holds the operator's hand-written ratings and notes, which exist
    # nowhere else. Take the lock before reading so a concurrent refresh cannot
    # interleave, and replace the file atomically so an interrupted write cannot
    # leave it truncated.
    # file_lock appends ".lock" itself; pass the profile path directly.
    with file_lock(path):
        profile = json.loads(path.read_text(encoding="utf-8"))
        weights = preference_outcome_weights(conn, profile)
        if weights:
            profile["outcomeWeights"] = weights
        else:
            profile.pop("outcomeWeights", None)
        atomic_write_text(path, json.dumps(profile, indent=1, sort_keys=True) + "\n")
    return {
        "collectionId": profile.get("collectionId"),
        "sourceFingerprint": profile.get("sourceFingerprint"),
        "weightedItems": len(weights),
    }
