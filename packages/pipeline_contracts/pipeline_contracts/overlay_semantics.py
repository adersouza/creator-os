from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

SCHEMA = "pipeline.overlay_semantic_qc.v1"
POLICY_VERSION = "overlay_payoff_v3"
TIMING_SCHEMA = "pipeline.overlay_timing_qc.v1"

_GENERIC_STOP_SETUP = re.compile(
    r"^(?:(?:men|guys|boys|girls|women|ladies|people|y['’]?all)\s*[,!—-]?\s*)?"
    r"(?:please\s+)?(?:stop|quit)\s+"
    r"(?:doing|saying|sending|wearing|posting|using|asking|calling|texting|"
    r"watching|liking|following|trying)\s+(?:this|that|it|these)"
    r"\s*(?::|…|\.\.\.)?\s*$",
    re.IGNORECASE,
)
_UNRESOLVED_LABEL_SETUP = re.compile(
    r"^(?:here(?:'s|’s| is)(?:\s+why)?|these are|the reasons?|the truth|"
    r"the problem|signs?|mistakes?|red flags?|turn[- ]?offs?|rules?|things?)"
    r"\s*(?::|…|\.\.\.)\s*$",
    re.IGNORECASE,
)
_UNRESOLVED_ACTION_SETUP = re.compile(
    r"^(?:watch this|wait for it|guess what|what happens next)"
    r"\s*(?::|…|\.\.\.)?\s*$",
    re.IGNORECASE,
)
_DANGLING_CLAUSE = re.compile(
    r"\b(?:because|but|and|or|so|if|when|unless|that|to)"
    r"\s*(?:…|\.\.\.)?\s*$",
    re.IGNORECASE,
)
_ENUMERATED_PROMISE = re.compile(
    r"^(?P<count>[2-9])\s+(?:reasons?|ways?|things?|signs?|mistakes?|rules?|tips?)\b",
    re.IGNORECASE,
)


def evaluate_overlay_semantic_completeness(
    value: Any, *, require_overlay: bool = False
) -> dict[str, Any]:
    """Fail closed only for objectively unfinished burned-overlay copy.

    The policy deliberately does not impose arbitrary length, word-count, ASCII,
    or punctuation preferences. A static hook may be short, slangy, provocative,
    or visually resolved. We block only a dangling clause or an explicit setup
    that promises missing follow-up text. A real timed sequence passes when it
    contains at least two distinct, non-empty caption segments.
    """

    segments = _caption_segments(value)
    distinct_segments = list(dict.fromkeys(segments))
    caption_hash = _caption_hash(segments)
    base = {
        "schema": SCHEMA,
        "policy_version": POLICY_VERSION,
        "caption_hash": caption_hash,
        "segment_count": len(segments),
        "distinct_segment_count": len(distinct_segments),
        "timed_sequence": _timed_caption_payload(value),
    }

    if not segments:
        if require_overlay:
            return {
                **base,
                "passed": False,
                "decision": "blocked",
                "reason": "missing_burned_overlay_text",
                "failure_reasons": ["missing_burned_overlay_text"],
            }
        return {
            **base,
            "passed": True,
            "decision": "no_burned_overlay",
            "reason": "no_overlay_text_to_validate",
            "failure_reasons": [],
        }

    text = distinct_segments[0]
    enumerated_promise = _ENUMERATED_PROMISE.match(text)
    if enumerated_promise:
        required_payoff_count = int(enumerated_promise.group("count"))
        payoff_segments = distinct_segments[1:]
        complete_payoffs = [
            segment
            for segment in payoff_segments
            if _incomplete_reason(segment) is None
        ]
        if len(complete_payoffs) < required_payoff_count:
            return {
                **base,
                "passed": False,
                "decision": "blocked",
                "reason": "missing_enumerated_overlay_payoffs",
                "failure_reasons": ["missing_enumerated_overlay_payoffs"],
                "required_payoff_count": required_payoff_count,
                "payoff_segment_count": len(complete_payoffs),
            }
        return {
            **base,
            "passed": True,
            "decision": "timed_payoff_present",
            "reason": "promised_overlay_payoff_count_is_complete",
            "failure_reasons": [],
            "required_payoff_count": required_payoff_count,
            "payoff_segment_count": len(complete_payoffs),
        }

    failure_reason = _incomplete_reason(text)

    if len(distinct_segments) >= 2:
        final_failure = _incomplete_reason(distinct_segments[-1])
        if final_failure is None:
            return {
                **base,
                "passed": True,
                "decision": "timed_payoff_present",
                "reason": "distinct_final_caption_segment_resolves_sequence",
                "failure_reasons": [],
            }
        failure_reason = final_failure

    if failure_reason:
        return {
            **base,
            "passed": False,
            "decision": "blocked",
            "reason": failure_reason,
            "failure_reasons": [failure_reason],
        }

    return {
        **base,
        "passed": True,
        "decision": "self_contained_overlay",
        "reason": "single_overlay_is_self_contained_or_visually_resolved",
        "failure_reasons": [],
    }


def evaluate_overlay_timing(
    segments: list[dict[str, Any]], *, duration_seconds: float
) -> dict[str, Any]:
    """Validate the resolved on-screen timing plan against the rendered clip.

    Callers must pass the post-redistribution plan actually given to FFmpeg, not
    the raw authoring input. Overlap is allowed for persistent headers, but each
    segment must have a finite, positive visible interval and starts must remain
    ordered.
    """

    failures: list[str] = []
    resolved: list[dict[str, Any]] = []
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        duration = math.nan
    if not math.isfinite(duration) or duration <= 0:
        failures.append("invalid_overlay_media_duration")
    if not segments:
        failures.append("missing_burned_overlay_text")

    previous_start = -math.inf
    for index, segment in enumerate(segments):
        text = _normalize_text(str(segment.get("text") or ""))
        try:
            start = float(segment.get("start", 0.0))
            raw_end = segment.get("end")
            end = duration if raw_end is None else float(raw_end)
        except (TypeError, ValueError):
            start = math.nan
            end = math.nan
        segment_failures: list[str] = []
        if not text:
            segment_failures.append("missing_burned_overlay_text")
        if not math.isfinite(start) or not math.isfinite(end):
            segment_failures.append("non_finite_overlay_timing")
        else:
            if start < 0:
                segment_failures.append("negative_overlay_start")
            if start < previous_start:
                segment_failures.append("non_monotonic_overlay_start")
            if end <= start:
                segment_failures.append("non_positive_overlay_interval")
            if math.isfinite(duration) and (start >= duration or end > duration + 1e-6):
                segment_failures.append("overlay_segment_outside_media_duration")
            previous_start = start
        failures.extend(segment_failures)
        resolved.append(
            {
                "index": index,
                "text": text,
                "start": start if math.isfinite(start) else None,
                "end": end if math.isfinite(end) else None,
                "failure_reasons": sorted(set(segment_failures)),
            }
        )

    unique_failures = sorted(set(failures))
    return {
        "schema": TIMING_SCHEMA,
        "policy_version": "resolved_overlay_timing_v1",
        "passed": not unique_failures,
        "duration_seconds": duration if math.isfinite(duration) else None,
        "segment_count": len(segments),
        "segments": resolved,
        "failure_reasons": unique_failures,
        "reason": "resolved_overlay_timing_visible"
        if not unique_failures
        else unique_failures[0],
    }


def _incomplete_reason(text: str) -> str | None:
    if _GENERIC_STOP_SETUP.fullmatch(text):
        return "missing_overlay_payoff_after_setup"
    if _UNRESOLVED_LABEL_SETUP.fullmatch(text):
        return "missing_overlay_payoff_after_setup"
    if _UNRESOLVED_ACTION_SETUP.fullmatch(text):
        return "missing_overlay_payoff_after_setup"
    if _DANGLING_CLAUSE.search(text):
        return "dangling_overlay_clause"
    return None


def _caption_segments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        raw_segments = value.get("segments")
        if isinstance(raw_segments, list):
            return _normalize_segment_values(raw_segments)
        for key in ("text", "caption_text", "captionText"):
            if key in value:
                return _caption_segments(value.get(key))
        return []
    if isinstance(value, list):
        return _normalize_segment_values(value)
    if not isinstance(value, str):
        return _caption_segments(str(value))

    stripped = value.strip()
    if not stripped:
        return []
    if stripped[:1] in {"{", "["}:
        try:
            decoded = json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, (dict, list)):
            return _caption_segments(decoded)
    normalized = _normalize_text(stripped)
    return [normalized] if normalized else []


def _timed_caption_payload(value: Any) -> bool:
    if isinstance(value, dict):
        return isinstance(value.get("segments"), list)
    if isinstance(value, list):
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in {"{", "["}:
            try:
                return _timed_caption_payload(json.loads(stripped))
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
    return False


def _normalize_segment_values(values: list[Any]) -> list[str]:
    segments: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("text")
        if value is None:
            continue
        normalized = _normalize_text(str(value))
        if normalized:
            segments.append(normalized)
    return segments


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _caption_hash(segments: list[str]) -> str | None:
    if not segments:
        return None
    canonical = json.dumps(
        segments,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
