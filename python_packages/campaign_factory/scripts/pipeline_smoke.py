#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campaign_factory.pipeline_smoke import run_pipeline_smoke


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the opt-in local-only cross-repo pipeline smoke fixture.")
    parser.add_argument("--projects-root", default="/Users/adercialonedesouza/Projects")
    parser.add_argument("--workspace", default=None, help="Optional temp workspace to keep smoke artifacts.")
    parser.add_argument("--skip-threadsdash-validator", action="store_true")
    parser.add_argument("--real-providers", action="store_true", help="Reserved for a future paid-provider acceptance smoke; current default is mocked/no credits.")
    parser.add_argument("--max-credits", type=float, default=0.0, help="Credit cap for future real-provider smoke runs.")
    args = parser.parse_args()
    if args.real_providers:
        raise SystemExit("--real-providers is not implemented yet; run the mocked no-credit smoke first.")
    result = run_pipeline_smoke(
        projects_root=Path(args.projects_root),
        workspace=Path(args.workspace) if args.workspace else None,
        run_threadsdash_validator=not args.skip_threadsdash_validator,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
