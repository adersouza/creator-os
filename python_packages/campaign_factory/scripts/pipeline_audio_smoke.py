#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campaign_factory.audio_smoke import run_pipeline_audio_smoke


DEFAULT_PROJECTS_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local cross-repo native-audio smoke fixture.")
    parser.add_argument("--projects-root", default=str(DEFAULT_PROJECTS_ROOT))
    parser.add_argument("--workspace", default=None, help="Optional temp workspace to keep smoke artifacts.")
    parser.add_argument("--skip-threadsdash-validator", action="store_true")
    args = parser.parse_args()
    result = run_pipeline_audio_smoke(
        projects_root=Path(args.projects_root),
        workspace=Path(args.workspace) if args.workspace else None,
        run_threadsdash_validator=not args.skip_threadsdash_validator,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
