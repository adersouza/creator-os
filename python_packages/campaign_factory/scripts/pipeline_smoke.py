#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campaign_factory.pipeline_smoke import run_pipeline_smoke
from campaign_factory.real_provider_acceptance import (
    JsonCommandAcceptanceSeams,
    run_real_provider_acceptance,
)

DEFAULT_PROJECTS_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the opt-in local-only cross-repo pipeline smoke fixture."
    )
    parser.add_argument("--projects-root", default=str(DEFAULT_PROJECTS_ROOT))
    parser.add_argument(
        "--workspace",
        default=None,
        help="Optional temp workspace to keep smoke artifacts.",
    )
    parser.add_argument("--skip-threadsdash-validator", action="store_true")
    parser.add_argument(
        "--real-providers",
        action="store_true",
        help="Run the paid, draft-only real-provider acceptance path.",
    )
    parser.add_argument(
        "--paid-confirmation",
        action="store_true",
        help="Explicitly confirm that this run may consume provider credits.",
    )
    parser.add_argument("--target-environment", choices=["preview", "production"])
    parser.add_argument(
        "--driver-command",
        help="Operator-reviewed local JSON phase driver; secrets stay in its environment.",
    )
    parser.add_argument(
        "--max-credits",
        type=float,
        default=0.0,
        help="Hard credit cap for the real-provider smoke run.",
    )
    args = parser.parse_args()
    if args.real_providers:
        if not args.workspace:
            raise SystemExit(
                "--workspace is required for a real-provider acceptance run"
            )
        if not args.target_environment:
            raise SystemExit("--target-environment is required with --real-providers")
        result = run_real_provider_acceptance(
            workspace=Path(args.workspace),
            target_environment=args.target_environment,
            paid_confirmation=args.paid_confirmation,
            max_credits=args.max_credits,
            seams=JsonCommandAcceptanceSeams(args.driver_command),
        )
    else:
        result = run_pipeline_smoke(
            projects_root=Path(args.projects_root),
            workspace=Path(args.workspace) if args.workspace else None,
            run_threadsdash_validator=not args.skip_threadsdash_validator,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
