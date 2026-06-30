"""Persistent metadata for AI-generated reel hooks."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def caption_hash(text: str) -> str:
    normalized = " ".join((text or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def new_generation_id() -> str:
    return f"capgen_{uuid.uuid4().hex[:12]}"


def score_caption_quality(
    text: str,
    *,
    recent_hooks: list[str] | None = None,
    min_chars: int = 10,
    max_chars: int = 140,
) -> dict[str, Any]:
    warnings: list[str] = []
    stripped = text.strip()
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    words = re.findall(r"[a-zA-Z0-9']+", stripped.lower())
    if len(stripped) < min_chars:
        warnings.append("too_short")
    if len(stripped) > max_chars:
        warnings.append("too_long")
    if len(lines) > 6:
        warnings.append("too_many_lines")
    if lines and len(lines[0]) < 8:
        warnings.append("weak_first_line_hook")
    if len(words) >= 4:
        repeated = max((words.count(word) for word in set(words)), default=0)
        if repeated >= 4:
            warnings.append("repeated_wording")
    normalized = _normalize(stripped)
    if recent_hooks and normalized in {_normalize(hook) for hook in recent_hooks}:
        warnings.append("recent_duplicate")
    score = max(0, 100 - len(set(warnings)) * 15)
    return {
        "captionHash": caption_hash(stripped),
        "charCount": len(stripped),
        "lineCount": len(lines) or (1 if stripped else 0),
        "qualityScore": score,
        "warnings": sorted(set(warnings)),
    }


def append_generation_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def build_generation_record(
    *,
    generation_id: str,
    backend: str,
    model: str,
    prompt: str,
    base: str,
    requested_count: int,
    accepted: list[str],
    rejected: list[dict[str, Any]],
    required_terms: list[str] | None,
    seed: int,
    strict: bool,
    min_chars: int,
    max_chars: int,
    embedding_model: str | None,
    quality: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "reel_factory.caption_generation.v1",
        "generationId": generation_id,
        "createdAt": utc_now(),
        "backend": backend,
        "model": model,
        "promptHash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "promptPreview": prompt[:500],
        "baseHook": base,
        "requestedCount": requested_count,
        "acceptedHooks": [
            {"text": hook, **quality_item}
            for hook, quality_item in zip(accepted, quality)
        ],
        "rejectedHooks": rejected,
        "requiredTerms": required_terms or [],
        "seed": seed,
        "strict": strict,
        "minChars": min_chars,
        "maxChars": max_chars,
        "embeddingModel": embedding_model,
    }


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def load_generation_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def caption_library(path: Path) -> dict[str, Any]:
    records = load_generation_log(path)
    captions = []
    for record in records:
        common = {
            "generationId": record.get("generationId"),
            "createdAt": record.get("createdAt"),
            "backend": record.get("backend"),
            "model": record.get("model"),
            "promptHash": record.get("promptHash"),
            "baseHook": record.get("baseHook"),
        }
        for hook in record.get("acceptedHooks") or []:
            captions.append({"state": "accepted", **common, **_caption_payload(hook)})
        for hook in record.get("rejectedHooks") or []:
            item = _caption_payload(
                hook.get("quality") if isinstance(hook, dict) else {}
            )
            if isinstance(hook, dict):
                item["text"] = hook.get("hook") or hook.get("text") or item.get("text")
                item["reason"] = hook.get("reason")
            captions.append({"state": "rejected", **common, **item})
    return {
        "schema": "reel_factory.caption_library.v1",
        "count": len(captions),
        "captions": captions,
    }


def rank_captions(
    captions: list[str],
    *,
    recent_hooks: list[str] | None = None,
    top: int = 20,
    performance_by_caption_hash: dict[str, Any] | None = None,
    min_chars: int = 10,
    max_chars: int = 140,
) -> list[dict[str, Any]]:
    ranked = []
    seen: set[str] = set()
    for index, text in enumerate(captions):
        quality = score_caption_quality(
            text, recent_hooks=recent_hooks, min_chars=min_chars, max_chars=max_chars
        )
        warnings = set(quality["warnings"])
        normalized = _normalize(text)
        if normalized in seen:
            warnings.add("duplicate_in_batch")
        seen.add(normalized)
        performance = (performance_by_caption_hash or {}).get(
            quality["captionHash"]
        ) or {}
        perf_score = _performance_component(performance)
        quality_score = int(quality["qualityScore"])
        score = round(quality_score * 0.75 + perf_score * 0.25)
        ranked.append(
            {
                "index": index,
                "text": text,
                "captionHash": quality["captionHash"],
                "score": max(0, min(100, score)),
                "quality": {**quality, "warnings": sorted(warnings)},
                "performance": performance or None,
                "reasons": _rank_reasons(quality_score, perf_score, warnings),
            }
        )
    return sorted(ranked, key=lambda row: row["score"], reverse=True)[: max(1, top)]


def rank_clip_sidecar(
    captions_dir: Path,
    clip: str,
    *,
    recent_hooks: list[str] | None = None,
    top: int = 20,
    performance_by_caption_hash: dict[str, Any] | None = None,
    min_chars: int = 10,
    max_chars: int = 140,
) -> dict[str, Any]:
    sidecar = captions_dir / f"{clip}.json"
    if not sidecar.exists():
        raise FileNotFoundError(f"caption sidecar not found: {sidecar}")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    hooks = payload.get("hooks") or []
    captions = [_hook_text(hook) for hook in hooks]
    ranked = rank_captions(
        captions,
        recent_hooks=recent_hooks,
        top=top,
        performance_by_caption_hash=performance_by_caption_hash,
        min_chars=min_chars,
        max_chars=max_chars,
    )
    return {
        "schema": "reel_factory.caption_ranking.v1",
        "clip": clip,
        "sidecar": str(sidecar),
        "generation": payload.get("generation"),
        "ranked": ranked,
    }


def _caption_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": value.get("text"),
        "captionHash": value.get("captionHash"),
        "charCount": value.get("charCount"),
        "lineCount": value.get("lineCount"),
        "qualityScore": value.get("qualityScore"),
        "warnings": value.get("warnings") or [],
    }


def _hook_text(hook: Any) -> str:
    if isinstance(hook, str):
        return hook
    if isinstance(hook, dict):
        if isinstance(hook.get("segments"), list):
            return " ".join(
                str(seg.get("text", "")).strip()
                for seg in hook["segments"]
                if isinstance(seg, dict)
            ).strip()
        return str(hook.get("text") or "")
    return str(hook)


def _performance_component(performance: dict[str, Any]) -> int:
    if not performance:
        return 50
    metrics = (
        performance.get("metrics")
        or performance.get("totals")
        or performance.get("averages")
        or performance
    )
    views = float(metrics.get("views") or 0)
    shares = float(metrics.get("shares") or 0)
    saves = float(metrics.get("saves") or 0)
    likes = float(metrics.get("likes") or 0)
    signal = views + shares * 25 + saves * 20 + likes * 2
    if signal <= 0:
        return 45
    return int(max(35, min(100, 50 + signal / 100)))


def _rank_reasons(quality_score: int, perf_score: int, warnings: set[str]) -> list[str]:
    reasons = []
    if quality_score >= 85:
        reasons.append("strong local quality")
    if perf_score > 55:
        reasons.append("matching caption has positive history")
    if warnings:
        reasons.append("review warnings: " + ", ".join(sorted(warnings)))
    return reasons or ["neutral score; no historical performance yet"]
