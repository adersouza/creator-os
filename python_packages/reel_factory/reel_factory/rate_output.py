#!/usr/bin/env python3
"""Attach operator taste/quality ratings to rendered outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .campaign_store import rate_output


def _score(value: str | None) -> int | None:
    return int(value) if value not in {None, ""} else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--campaign")
    ap.add_argument("--asset-generation-id")
    ap.add_argument("--identity")
    ap.add_argument("--pose")
    ap.add_argument("--taste")
    ap.add_argument("--artifacts")
    ap.add_argument("--motion")
    ap.add_argument("--caption")
    ap.add_argument("--labels", default="")
    ap.add_argument("--retry-helper")
    ap.add_argument("--reason", default="")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()
    result = rate_output(
        Path(args.root),
        output_path=Path(args.output),
        campaign=args.campaign,
        asset_generation_id=args.asset_generation_id,
        scores={
            "identity": _score(args.identity),
            "pose": _score(args.pose),
            "taste": _score(args.taste),
            "artifacts": _score(args.artifacts),
            "motion": _score(args.motion),
            "caption": _score(args.caption),
        },
        labels=[x.strip() for x in args.labels.split(",") if x.strip()],
        retry_helper=args.retry_helper,
        reason=args.reason,
        notes=args.notes,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
