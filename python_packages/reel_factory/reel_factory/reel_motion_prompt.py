#!/usr/bin/env python3
"""Deterministic Kling motion prompts for accepted Reel Factory stills."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

SceneType = Literal[
    "mirror_selfie",
    "boat_bikini",
    "back_dress",
    "outdoor_standing",
    "outdoor_kneel",
    "room_selfie",
]

SCENE_TYPES = {
    "mirror_selfie",
    "boat_bikini",
    "back_dress",
    "outdoor_standing",
    "outdoor_kneel",
    "room_selfie",
}

_MOTION_BY_SCENE = {
    "mirror_selfie": (
        "Keep the mirror-selfie pose and phone framing stable. Add tiny handheld phone sway, "
        "natural breathing, a slight hip weight shift, small head and eye movement, and realistic fabric motion."
    ),
    "boat_bikini": (
        "Keep the seated boat pose, bikini, boat seat, and marina background stable. Add a small smile change, "
        "slight head turn, relaxed shoulder movement, natural breathing, tiny arm adjustment, water shimmer, "
        "and gentle handheld sway."
    ),
    "back_dress": (
        "Keep the back-facing dress pose, raised hand placement, wall or couch setting, and over-shoulder angle stable. "
        "Add slow breathing, a tiny hip and shoulder shift, a slight over-shoulder glance, natural dress movement, "
        "and a mostly locked handheld camera."
    ),
    "outdoor_standing": (
        "Keep the standing outdoor pose, outfit, background, and full-body framing stable. Add a subtle breeze, "
        "small weight shift through the hips, a tiny hand movement near the head, natural breathing, and a soft phone-style push-in."
    ),
    "outdoor_kneel": (
        "Keep the kneeling outdoor pose, outfit, camera angle, and ground setting stable. Add a subtle torso shift, "
        "natural breathing, tiny hand movement, light clothing movement, and a restrained handheld camera sway."
    ),
    "room_selfie": (
        "Keep the casual room selfie pose, room layout, outfit, and full head framing stable. Add a natural handheld feel, "
        "tiny posture shift, soft breathing, slight hip movement, and realistic body and fabric motion."
    ),
}

_COMMON_SAFETY = (
    "Use the supplied 9:16 start image as the source frame. Preserve the same person, outfit, setting, pose family, "
    "camera angle, and lighting. Keep the full head and face visible. Create a short realistic phone video, 5 seconds, "
    "with no new text, logos, UI, captions, watermarks, extra people, outfit changes, location changes, jump cuts, "
    "large camera moves, or major pose changes."
)


@dataclass(frozen=True)
class ReelMotionPrompt:
    schema: str
    startImagePath: str
    sceneType: str
    aspectRatio: str
    durationSeconds: int
    klingMotionPrompt: str


def compile_reel_motion_prompt(
    *,
    start_image_path: str | Path,
    scene_type: str,
    captured_higgsfield_prompt: str | None = None,
    aspect_ratio: str = "9:16",
    duration_seconds: int = 5,
) -> ReelMotionPrompt:
    normalized = str(scene_type or "").strip().lower().replace("-", "_")
    if normalized not in SCENE_TYPES:
        raise ValueError(
            f"unsupported scene_type {scene_type!r}; expected one of {sorted(SCENE_TYPES)}"
        )
    start_image = str(Path(start_image_path).expanduser())
    scene_motion = _MOTION_BY_SCENE[normalized]
    prompt_context = ""
    if captured_higgsfield_prompt:
        trimmed = " ".join(str(captured_higgsfield_prompt).split())
        if trimmed:
            prompt_context = (
                f" Visual context from the accepted still: {trimmed[:500]}."
            )
    return ReelMotionPrompt(
        schema="reel_factory.reel_motion_prompt.v1",
        startImagePath=start_image,
        sceneType=normalized,
        aspectRatio=aspect_ratio,
        durationSeconds=duration_seconds,
        klingMotionPrompt=f"{_COMMON_SAFETY} {scene_motion}{prompt_context}",
    )


def motion_prompt_json(prompt: ReelMotionPrompt) -> str:
    return json.dumps(asdict(prompt), indent=2, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start-image", required=True)
    ap.add_argument("--scene-type", required=True, choices=sorted(SCENE_TYPES))
    ap.add_argument("--captured-higgsfield-prompt", default="")
    ap.add_argument("--aspect-ratio", default="9:16")
    ap.add_argument("--duration-seconds", type=int, default=5)
    ap.add_argument("--out")
    args = ap.parse_args()
    prompt = compile_reel_motion_prompt(
        start_image_path=args.start_image,
        scene_type=args.scene_type,
        captured_higgsfield_prompt=args.captured_higgsfield_prompt,
        aspect_ratio=args.aspect_ratio,
        duration_seconds=args.duration_seconds,
    )
    payload = motion_prompt_json(prompt) + "\n"
    if args.out:
        path = Path(args.out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, payload, encoding="utf-8")
        print(str(path))
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
