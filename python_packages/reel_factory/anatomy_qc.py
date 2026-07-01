#!/usr/bin/env python3
"""Anatomy/defect QC gate for generated stills.

The failure mode that matters -- a butt on the wrong side, a merged limb, six
fingers -- is exactly what MediaPipe/pose geometry CANNOT catch: it force-fits a
skeleton to garbage and reports "fine". A vision model catches it. This reuses
the Grok-vision seam already wired for reference analysis
(`generate_prompts.build_xai_payload`/`call_grok`) -- no new deps -- and asks one
tight question: is the anatomy physically plausible?

Fail-closed: if the provider is missing or the call fails, the image is NOT
auto-approved (`available=False`, `plausible=None`, `is_postable=False`). An
unverifiable image goes to a human / re-roll, never straight to the feed.

CLI: `python anatomy_qc.py --image out.png --root .`  -> exit 0 pass / 1 reject.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from generate_prompts import (
    DEFAULT_MODEL,
    build_xai_payload,
    call_grok,
    load_xai_api_key,
    response_text,
    strip_json_fence,
)

_PROMPT = (
    "You are an anatomy-defect detector for AI-generated photos of ONE person. "
    "Look ONLY for physical impossibilities a human eye catches instantly: extra "
    "or missing limbs/hands/feet, wrong finger or toe count, fused fingers, a body "
    "part on the wrong side of the body or duplicated/merged, impossible joint "
    "bends, a warped or melted face/eyes/teeth. IGNORE style, pose, lighting, "
    "attractiveness, clothing, background, and cropping. Reply with ONLY JSON, no "
    'prose: {"plausible": true|false, "severity": "none"|"minor"|"severe", '
    '"defects": ["short phrase", ...]}. severe = a defect that makes the image '
    "unpostable; minor = subtle/arguable; none = clean."
)

# (frames, instruction) -> raw model text. Injectable so tests never spend.
VisionCall = Callable[[list[Path], str], str]


def _grok_vision(root: Path, model: str) -> VisionCall:
    api_key = load_xai_api_key(root)
    if not api_key:
        raise RuntimeError(
            "XAI_API_KEY or project_data/secrets.toml xai_api_key required for anatomy QC"
        )

    def _call(frames: list[Path], instruction: str) -> str:
        payload = build_xai_payload(model=model, frames=frames, instruction=instruction)
        return response_text(call_grok(payload, api_key=api_key))

    return _call


def assess_anatomy(
    image_path: Path | str,
    *,
    root: Path | str = ".",
    model: str = DEFAULT_MODEL,
    vision_call: VisionCall | None = None,
) -> dict[str, Any]:
    """Score one still for anatomy plausibility. Fail-closed on any failure."""
    image_path = Path(image_path)
    if not image_path.exists():
        return {
            "available": True,
            "plausible": False,
            "severity": "severe",
            "defects": ["missing file"],
            "error": "file not found",
        }
    if vision_call is None:
        try:
            vision_call = _grok_vision(Path(root), model)
        except Exception as exc:  # provider unavailable -> fail-closed
            return {
                "available": False,
                "plausible": None,
                "severity": None,
                "defects": [],
                "error": str(exc),
            }
    try:
        raw = vision_call([image_path], _PROMPT)
        data = json.loads(strip_json_fence(raw))
    except Exception as exc:  # call/parse failed -> fail-closed
        return {
            "available": False,
            "plausible": None,
            "severity": None,
            "defects": [],
            "error": f"vision call/parse failed: {exc}",
        }
    plausible = bool(data.get("plausible"))
    severity = str(data.get("severity") or ("none" if plausible else "severe"))
    defects = [str(d) for d in (data.get("defects") or [])]
    return {
        "available": True,
        "plausible": plausible,
        "severity": severity,
        "defects": defects,
    }


def is_postable(assessment: dict[str, Any]) -> bool:
    """Gate. Postable only if the check RAN and found plausible, non-severe anatomy.

    Fail-closed: an unverifiable image (available False) is never postable.
    """
    if not assessment.get("available"):
        return False
    return bool(assessment.get("plausible")) and assessment.get("severity") != "severe"


def filter_plausible(
    paths: list[Path | str],
    root: Path | str = ".",
    *,
    vision_call: VisionCall | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split image paths into (kept, rejected) — reject anything not postable."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for p in paths:
        a = assess_anatomy(p, root=root, vision_call=vision_call)
        (kept if is_postable(a) else rejected).append({"path": str(p), **a})
    return kept, rejected


def _demo() -> None:
    clean = lambda f, i: '{"plausible": true, "severity": "none", "defects": []}'
    broken = lambda f, i: (
        '```json\n{"plausible": false, "severity": "severe", '
        '"defects": ["butt on wrong side", "6 fingers"]}\n```'
    )
    boom = lambda f, i: (_ for _ in ()).throw(RuntimeError("network down"))
    here = Path(__file__)

    ok = assess_anatomy(here, vision_call=clean)
    assert ok["available"] and ok["plausible"] and is_postable(ok), ok

    bad = assess_anatomy(here, vision_call=broken)  # fence-wrapped JSON parses
    assert bad["available"] and not bad["plausible"], bad
    assert bad["defects"] == ["butt on wrong side", "6 fingers"], bad
    assert not is_postable(bad), bad

    down = assess_anatomy(here, vision_call=boom)  # provider throws -> fail-closed
    assert down["available"] is False and not is_postable(down), down

    missing = assess_anatomy(here.parent / "does_not_exist.png", vision_call=clean)
    assert not is_postable(missing), missing

    kept, rej = filter_plausible([here, here], vision_call=broken)
    assert len(kept) == 0 and len(rej) == 2, (kept, rej)

    print("anatomy_qc self-check OK")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", help="generated still to check")
    ap.add_argument("--root", default=".", help="project root (for XAI key lookup)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--demo", action="store_true", help="run self-check and exit")
    args = ap.parse_args(argv)
    if args.demo or not args.image:
        _demo()
        return 0
    result = assess_anatomy(args.image, root=args.root, model=args.model)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # exit 0 = postable, 1 = reject/unverifiable (fail-closed)
    return 0 if is_postable(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
