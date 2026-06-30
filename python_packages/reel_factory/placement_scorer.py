"""Caption lane scoring for auto placement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LANES = ("top", "center", "bottom")


@dataclass(frozen=True)
class PlacementSummary:
    lane: str
    scores: dict[str, float]
    sample_count: int
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


def score_lanes(
    *,
    stddev_samples: list[tuple[float, float, float]],
    face_samples: list[tuple[float, float, float]] | None = None,
    focal_samples: list[tuple[float, float, float]] | None = None,
    motion_samples: list[tuple[float, float, float]] | None = None,
    pose_samples: list[tuple[float, float, float]] | None = None,
    placement_policy: str = "focal-safe",
    center_penalty: float = 8.0,
) -> PlacementSummary:
    """Score top/center/bottom lanes; lower is better."""
    normalized_policy = "legacy" if placement_policy == "legacy" else "focal-safe"
    scores = {lane: 0.0 for lane in LANES}
    components = {
        lane: {
            "busyness": 0.0,
            "face": 0.0,
            "focal": 0.0,
            "motion": 0.0,
            "pose": 0.0,
            "safe_area": 0.0,
        }
        for lane in LANES
    }
    sample_count = max(
        len(stddev_samples),
        len(face_samples or []),
        len(focal_samples or []),
        len(motion_samples or []),
        len(pose_samples or []),
    )

    if stddev_samples:
        for lane, value in zip(LANES, _mean3(stddev_samples), strict=True):
            scores[lane] += value * 1.0
            components[lane]["busyness"] = value

    if face_samples:
        max_face = max(max(sample) for sample in face_samples) or 1.0
        for lane, value in zip(LANES, _mean3(face_samples), strict=True):
            weight = 180.0 if normalized_policy == "focal-safe" else 90.0
            penalty = (value / max_face) * weight
            scores[lane] += penalty
            components[lane]["face"] = penalty

    has_body_specific_signal = bool(face_samples or pose_samples)
    if normalized_policy == "focal-safe" and focal_samples:
        max_focal = max(max(sample) for sample in focal_samples) or 1.0
        for lane, value in zip(LANES, _mean3(focal_samples), strict=True):
            penalty = (value / max_focal) * 120.0
            # ponytail: lower-lane skin/edge density is often the intended hook zone;
            # keep real face/pose blockers strict, but don't let fallback focal density
            # force text onto the face/top of close portrait reels.
            if lane == "bottom" and not has_body_specific_signal:
                penalty = min(penalty, 35.0)
            scores[lane] += penalty
            components[lane]["focal"] = penalty

    if motion_samples:
        for lane, value in zip(LANES, _mean3(motion_samples), strict=True):
            weight = 0.8 if normalized_policy == "focal-safe" else 0.45
            penalty = value * weight
            scores[lane] += penalty
            components[lane]["motion"] = penalty

    if pose_samples:
        max_pose = max(max(sample) for sample in pose_samples) or 1.0
        for lane, value in zip(LANES, _mean3(pose_samples), strict=True):
            weight = 90.0 if normalized_policy == "focal-safe" else 42.0
            penalty = (value / max_pose) * weight
            scores[lane] += penalty
            components[lane]["pose"] = penalty

    if (
        normalized_policy == "focal-safe"
        and focal_samples
        and not has_body_specific_signal
    ):
        scores["top"] += 30.0
        components["top"]["safe_area"] += 30.0
    scores["center"] += center_penalty
    components["center"]["safe_area"] = center_penalty
    lane = min(LANES, key=lambda key: (scores[key], 0 if key != "center" else 1))
    rejected_lanes: list[str] = []
    if normalized_policy == "focal-safe":
        for candidate in LANES:
            if candidate == lane:
                continue
            c = components[candidate]
            if c["face"] >= 70.0 or c["focal"] >= 70.0 or c["pose"] >= 65.0:
                rejected_lanes.append(candidate)
    reason = (
        f"{lane} lane lowest "
        f"(top={scores['top']:.1f}, center={scores['center']:.1f}, bottom={scores['bottom']:.1f})"
    )
    if normalized_policy == "focal-safe" and rejected_lanes:
        reason = (
            f"{lane} selected; rejected {', '.join(rejected_lanes)} for focal overlap"
        )
    metadata: dict[str, Any] = {
        "captionPlacementPolicy": "focal_safe_v1"
        if normalized_policy == "focal-safe"
        else "legacy",
        "captionPlacementDecision": {
            "status": "passed",
            "selectedLane": lane,
            "rejectedLanes": rejected_lanes,
            "reason": reason,
            "scores": {key: round(value, 3) for key, value in scores.items()},
            "components": {
                key: {
                    component: round(value, 3)
                    for component, value in lane_components.items()
                }
                for key, lane_components in components.items()
            },
            "sampleCount": sample_count,
        },
    }
    return PlacementSummary(
        lane=lane,
        scores={key: round(value, 3) for key, value in scores.items()},
        sample_count=sample_count,
        reason=reason,
        metadata=metadata,
    )


def _mean3(samples: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    if not samples:
        return 0.0, 0.0, 0.0
    n = len(samples)
    return (
        sum(sample[0] for sample in samples) / n,
        sum(sample[1] for sample in samples) / n,
        sum(sample[2] for sample in samples) / n,
    )
