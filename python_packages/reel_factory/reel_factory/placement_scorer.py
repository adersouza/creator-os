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
    head_samples: list[tuple[float, float, float]] | None = None,
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
            "head": 0.0,
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
        len(head_samples or []),
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
        for lane, value in zip(LANES, _max3(face_samples), strict=True):
            weight = 180.0 if normalized_policy == "focal-safe" else 90.0
            penalty = (value / max_face) * weight
            scores[lane] += penalty
            components[lane]["face"] = penalty

    if head_samples:
        max_head = max(max(sample) for sample in head_samples) or 1.0
        for lane, value in zip(LANES, _max3(head_samples), strict=True):
            # PP-HumanSeg head slice: robust head/hair blocker for angles YuNet
            # misses. Below face weight so YuNet stays primary; union-aggregated.
            weight = 110.0 if normalized_policy == "focal-safe" else 55.0
            penalty = (value / max_head) * weight
            scores[lane] += penalty
            components[lane]["head"] = penalty

    has_body_specific_signal = bool(face_samples or head_samples or pose_samples)
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
        for lane, value in zip(LANES, _max3(pose_samples), strict=True):
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
    rejected_lanes: list[str] = []
    # ponytail: focal is documented as the FALLBACK for when pose detection is
    # unavailable -- edge density plus warm-pixel density, no anatomy. It must not
    # out-vote the real detectors, but only when those detectors demonstrably WORKED
    # on this clip. A detector returning 0.0 in every lane means "found nothing",
    # which can equally mean "blind"; that is the case focal exists to cover, so
    # focal still blocks there. Require a positive detection SOMEWHERE before
    # trusting a per-lane zero as evidence of clearance.
    anatomy_detected = any(
        max(component[key] for component in components.values()) > 0.0
        for key in ("face", "head", "pose")
    )
    if normalized_policy == "focal-safe":
        for candidate in LANES:
            c = components[candidate]
            lane_anatomy_clear = (
                c["face"] < 70.0 and c["head"] < 60.0 and c["pose"] < 65.0
            )
            # Measured on 24 stacey stills: 13 were rejected outright, and each of
            # their bottom lanes scored face=0.0 head=0.0 pose=0.0 focal=120 while
            # the top lane scored face=180 head=110 -- so the detectors plainly
            # worked and plainly said "bottom is clear". A full-body portrait puts
            # skin and edges in every band, so focal saturates everywhere, every lane
            # is rejected, burn_caption silently goes False and the reel ships with
            # no overlay. Caption over the torso is the format; caption over the face
            # is what to prevent, and face/head/pose already prevent it.
            focal_blocks = c["focal"] >= 70.0 and not (
                anatomy_detected and lane_anatomy_clear
            )
            if not lane_anatomy_clear or focal_blocks:
                rejected_lanes.append(candidate)

    # Pick the cheapest lane that survived the vetoes -- NOT the cheapest lane
    # overall. Selecting before the vetoes were computed let a "passed" decision
    # name a lane it had itself rejected: real QC row src_55f2caedfb passed with
    # selectedLane=top while rejectedLanes was ["top", "center"], because top
    # scored 140.3 against bottom's 144.4 and won a comparison the veto should
    # have removed it from.
    #
    # ponytail: same min() and same center-loses-ties key, over a filtered list.
    # When every lane is rejected `lane` stays defined for the reason string; the
    # failed_no_safe_lane branch below sets selected_lane to None regardless.
    survivors = [candidate for candidate in LANES if candidate not in rejected_lanes]
    lane = min(
        survivors or LANES, key=lambda key: (scores[key], 0 if key != "center" else 1)
    )
    decision_status = "passed"
    decision_class = "legacy_selected" if normalized_policy == "legacy" else "passed"
    reason_code = "safe_caption_lane"
    render_policy = "burn_overlay"
    selected_lane: str | None = lane
    if normalized_policy == "legacy":
        reason_code = "legacy_placement_requested"
    elif not stddev_samples or not (
        face_samples or head_samples or focal_samples or pose_samples
    ):
        decision_status = "failed"
        decision_class = "insufficient_evidence"
        reason_code = "insufficient_caption_placement_evidence"
        render_policy = "clean_without_overlay"
        selected_lane = None
    elif set(rejected_lanes) == set(LANES):
        decision_status = "failed"
        decision_class = "failed_no_safe_lane"
        reason_code = "no_safe_caption_lane"
        render_policy = "clean_without_overlay"
        selected_lane = None

    reason = (
        f"{lane} lane lowest "
        f"(top={scores['top']:.1f}, center={scores['center']:.1f}, bottom={scores['bottom']:.1f})"
    )
    if decision_class == "insufficient_evidence":
        reason = "Required placement samples are unavailable; render clean media."
    elif decision_class == "failed_no_safe_lane":
        reason = "All caption lanes violate hard subject-safety thresholds."
    elif normalized_policy == "focal-safe" and rejected_lanes:
        reason = (
            f"{lane} selected; rejected {', '.join(rejected_lanes)} for focal overlap"
        )
    metadata: dict[str, Any] = {
        "captionPlacementPolicy": "focal_safe_v1"
        if normalized_policy == "focal-safe"
        else "legacy",
        "captionPlacementDecision": {
            "status": decision_status,
            "decisionClass": decision_class,
            "reasonCode": reason_code,
            "renderPolicy": render_policy,
            "selectedLane": selected_lane,
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


def _max3(samples: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Per-lane worst-case coverage across all frames (whole-clip subject union).

    Hard blockers (face, pose) use this so a static caption is penalized in any
    lane the subject enters on ANY frame, not just on average — the subject moves
    in motion clips, the caption doesn't. Soft signals stay averaged.
    """
    if not samples:
        return 0.0, 0.0, 0.0
    return (
        max(sample[0] for sample in samples),
        max(sample[1] for sample in samples),
        max(sample[2] for sample in samples),
    )
