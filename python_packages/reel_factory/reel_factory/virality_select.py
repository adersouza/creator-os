"""Predict-and-select: rank candidate reels by predicted engagement before posting.

The winner-DNA loop already measures, per content feature, how much engagement it
historically earned (`winner_dna` table, built by `winner_dna.refresh_winner_dna`,
scored by the shared reach-plus-engagement-rate winner_score). This module runs
that loop *forward*: it matches a fresh candidate's features against that history,
confidence-weights each match, and aggregates into a predicted-engagement score.
Generate N -> rank -> post the best, instead of posting the first render.

The default predictor is data-only: deterministic, no external calls, CI-testable.
Pass `scorer=` to blend an external signal (e.g. a Higgsfield virality prediction)
on top of the data score.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from reel_factory.feature_extract import features_from_lineage

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

from intelligence_store import confidence_for_sample_size
from winner_dna import FEATURE_KEYS, connect

# Down-weight low-sample feature clusters so a single fluke outcome can't crown a
# candidate. Tunable: raise the low/medium weights as the outcome corpus grows.
_CONFIDENCE_WEIGHT = {"low": 0.3, "medium": 0.7, "high": 1.0}

# A Higgsfield virality-predictor score (0..1) attached to a candidate out-of-band
# under this key. The predictor is an interactive MCP tool that runs on rendered
# video, so the score is fetched when posting real content and stapled onto the
# candidate dict; this module only blends the two numbers.
_VIRALITY_KEY = "virality"
# ponytail: even 50/50 blend until real predictor scores land and tell us which
# signal actually tracks views. Raise toward virality as that data comes in.
_VIRALITY_WEIGHT = 0.5


def _minmax(values: list[float]) -> list[float]:
    """Scale to 0..1 within the batch; a flat batch carries no signal -> all 0."""
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def predict_engagement(
    features: dict[str, Any],
    conn: sqlite3.Connection,
    *,
    total_outcomes: int | None = None,
) -> dict[str, Any]:
    """Confidence-weighted mean of each feature's historical avg engagement.

    Unmatched / cold-start candidates score 0.0 with matched=0 (caller can treat
    that as "no signal", not "bad").
    """
    if total_outcomes is None:
        total_outcomes = int(
            conn.execute("SELECT COUNT(*) FROM reel_outcomes").fetchone()[0] or 0
        )
    num = den = 0.0
    matched = 0
    for key in FEATURE_KEYS:
        value = features.get(key)
        if not value or value == "unknown":
            continue
        row = conn.execute(
            "SELECT avg_winner_score, sample_size FROM winner_dna "
            "WHERE feature_key=? AND feature_value=?",
            (key, str(value)),
        ).fetchone()
        if row is None:
            continue
        level = confidence_for_sample_size(
            row["sample_size"], total_outcomes=total_outcomes
        )["level"]
        weight = _CONFIDENCE_WEIGHT[level]
        num += float(row["avg_winner_score"]) * weight
        den += weight
        matched += 1
    return {
        "score": round(num / den, 2) if den else 0.0,
        "matched": matched,
        "weight": round(den, 2),
    }


def rank_candidates(
    candidates: list[dict[str, Any]],
    root: Path,
    *,
    scorer: Callable[[dict[str, Any], float], float] | None = None,
) -> list[dict[str, Any]]:
    """Return candidates sorted best-first by predicted engagement.

    Each candidate is a dict with a ``features`` map (winner-DNA feature keys).
    Precedence for the final score:
      1. `scorer(candidate, data_score) -> float` if given (full override).
      2. else if any candidate carries a `virality` (0..1) predictor score,
         blend it batch-normalized with the data score (scale-free, so a
         cold-start batch where every data score is 0 falls back to virality).
      3. else the raw data score.
    """
    conn = connect(root)
    try:
        total = int(
            conn.execute("SELECT COUNT(*) FROM reel_outcomes").fetchone()[0] or 0
        )
        ranked = []
        for candidate in candidates:
            pred = predict_engagement(
                candidate.get("features") or {}, conn, total_outcomes=total
            )
            ranked.append(
                {**candidate, "predictedEngagement": pred, "score": pred["score"]}
            )
    finally:
        conn.close()

    if scorer is not None:
        for candidate in ranked:
            candidate["score"] = float(
                scorer(candidate, candidate["predictedEngagement"]["score"])
            )
    elif any(c.get(_VIRALITY_KEY) is not None for c in ranked):
        data_norm = _minmax([c["predictedEngagement"]["score"] for c in ranked])
        scored = [c for c in ranked if c.get(_VIRALITY_KEY) is not None]
        vir_values = [float(c[_VIRALITY_KEY]) for c in scored]
        vir_norm_by_id = {
            id(candidate): score
            for candidate, score in zip(scored, _minmax(vir_values))
        }
        for candidate, d in zip(ranked, data_norm):
            if candidate.get(_VIRALITY_KEY) is None:
                candidate["score"] = round(d, 4)
                continue
            candidate["score"] = round(
                (1 - _VIRALITY_WEIGHT) * d
                + _VIRALITY_WEIGHT * vir_norm_by_id[id(candidate)],
                4,
            )
    # Tie-break on number of matched features: more evidence wins.
    ranked.sort(
        key=lambda c: (c["score"], c["predictedEngagement"]["matched"]), reverse=True
    )
    return ranked


def select_best(
    candidates: list[dict[str, Any]],
    root: Path,
    *,
    scorer: Callable[[dict[str, Any], float], float] | None = None,
) -> dict[str, Any] | None:
    ranked = rank_candidates(candidates, root, scorer=scorer)
    return ranked[0] if ranked else None


def rank_kling_candidate_manifest(
    manifest: dict[str, Any], root: Path
) -> dict[str, Any]:
    """Rank a paid-Kling candidate batch and fail closed on weak evidence."""
    if manifest.get("schema") != "campaign_factory.kling_candidate_manifest.v1":
        raise ValueError("Kling candidate manifest has the wrong schema")
    batch_id = str(manifest.get("batchId") or "").strip()
    if not batch_id:
        raise ValueError("Kling candidate manifest requires batchId")
    raw_candidates = manifest.get("candidates")
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 2:
        raise ValueError("best-only Kling selection requires at least two candidates")

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            raise ValueError("Kling candidate entries must be objects")
        candidate_id = str(raw.get("id") or "").strip()
        if not candidate_id or candidate_id in seen:
            raise ValueError("Kling candidate ids must be non-empty and unique")
        seen.add(candidate_id)
        lineage = raw.get("generatedAssetLineage")
        features = raw.get("features")
        if not isinstance(features, dict):
            features = (
                features_from_lineage(lineage) if isinstance(lineage, dict) else {}
            )
        candidate = {**raw, "id": candidate_id, "features": features}
        candidates.append(candidate)

    ranked = rank_candidates(candidates, root)
    for index, candidate in enumerate(ranked, start=1):
        candidate["rank"] = index
    signal_present = any(
        int((candidate.get("predictedEngagement") or {}).get("matched") or 0) > 0
        or candidate.get(_VIRALITY_KEY) is not None
        for candidate in ranked
    )
    top_key = (
        float(ranked[0].get("score") or 0),
        int((ranked[0].get("predictedEngagement") or {}).get("matched") or 0),
    )
    runner_up_key = (
        float(ranked[1].get("score") or 0),
        int((ranked[1].get("predictedEngagement") or {}).get("matched") or 0),
    )
    if not signal_present:
        status = "insufficient_signal"
        selected_id = None
    elif top_key <= runner_up_key:
        status = "ambiguous_top"
        selected_id = None
    else:
        status = "selected"
        selected_id = ranked[0]["id"]
    return {
        "schema": "reel_factory.kling_candidate_ranking.v1",
        "batchId": batch_id,
        "status": status,
        "selectedCandidateId": selected_id,
        "candidateCount": len(ranked),
        "signalPresent": signal_present,
        "publishingAllowed": False,
        "paidGenerationAuthorized": False,
        "candidates": ranked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rank-kling-candidates")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    if not args.rank_kling_candidates:
        parser.error("--rank-kling-candidates is required")
    payload = json.loads(Path(args.rank_kling_candidates).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Kling candidate manifest must be a JSON object")
    result = rank_kling_candidate_manifest(payload, Path(args.root).resolve())
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        atomic_write_text(Path(args.out), rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
