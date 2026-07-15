"""Rank rendered candidates from explicit Campaign advisory signals.

Reel Factory does not own posting outcomes or winner status. Campaign Factory
must staple an advisory derived from an imported
``reference_factory.knowledge_pack.v1`` onto each candidate. An optional
provider virality score may also be supplied out-of-band; this module performs
only deterministic ranking and never discovers a metrics database.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from reel_factory.feature_extract import features_from_lineage

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

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
    *,
    knowledge_advisory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the Campaign-supplied knowledge score without inventing facts."""
    _ = features
    if not isinstance(knowledge_advisory, dict):
        return {
            "score": 0.0,
            "matched": 0,
            "weight": 0.0,
            "source": "missing_campaign_knowledge",
            "recommendationStatus": "not_run",
            "measuredExampleCount": 0,
        }
    raw_score = knowledge_advisory.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        raise ValueError("knowledgeAdvisory.score must be a finite number")
    score = float(raw_score)
    if not math.isfinite(score):
        raise ValueError("knowledgeAdvisory.score must be a finite number")
    examples = knowledge_advisory.get("measuredExampleCount", 0)
    if isinstance(examples, bool) or not isinstance(examples, int) or examples < 0:
        raise ValueError("knowledgeAdvisory.measuredExampleCount must be non-negative")
    status = str(knowledge_advisory.get("recommendationStatus") or "advisory")
    if status not in {"advisory", "eligible"}:
        raise ValueError("knowledgeAdvisory.recommendationStatus is invalid")
    return {
        "score": round(score, 4),
        "matched": int(knowledge_advisory.get("matchedPatternCount") or 1),
        "weight": 1.0,
        "source": "campaign_factory.explicit_knowledge_advisory",
        "sourcePackId": knowledge_advisory.get("sourcePackId"),
        "recommendationStatus": status,
        "measuredExampleCount": examples,
        "decisionAuthority": False,
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
    _ = root  # retained CLI compatibility; no state is read from this path
    ranked = []
    for candidate in candidates:
        pred = predict_engagement(
            candidate.get("features") or {},
            knowledge_advisory=candidate.get("knowledgeAdvisory"),
        )
        ranked.append(
            {**candidate, "predictedEngagement": pred, "score": pred["score"]}
        )

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
        "rankingOwnership": "campaign_factory.explicit_advisory",
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
