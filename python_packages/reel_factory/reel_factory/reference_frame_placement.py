"""Read-only MediaPipe Tasks placement/body evidence for reference frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .placement import _pose_coverages_from_frame, _pose_tasks_provenance


def analyze_frames(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    provenance = _pose_tasks_provenance()
    if provenance.get("available") is not True:
        return {"available": False, "provenance": provenance, "frames": []}
    frames = []
    for item in manifest:
        result = _pose_coverages_from_frame(Path(str(item["path"])))
        frames.append(
            {
                "identifier": int(item["identifier"]),
                "available": result is not None,
                "verticalCoverage": list(result[0]) if result else None,
                "sideCoverage": list(result[1]) if result else None,
            }
        )
    return {"available": True, "provenance": provenance, "frames": frames}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(json.dumps(analyze_frames(manifest), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
