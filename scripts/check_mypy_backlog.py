#!/usr/bin/env python3
"""Prevent the acknowledged factory mypy backlog from growing or being hidden."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BacklogTarget:
    path: str
    expected_errors: int
    minimum_source_files: int


TARGETS = {
    "campaign_factory": BacklogTarget(
        "python_packages/campaign_factory/campaign_factory", 855, 134
    ),
    "reference_factory": BacklogTarget(
        "python_packages/reference_factory/reference_factory", 168, 35
    ),
    "reel_factory": BacklogTarget("python_packages/reel_factory/reel_factory", 85, 79),
}

ERROR_SUMMARY = re.compile(
    r"Found (?P<errors>\d+) errors? in \d+ files? \(checked (?P<checked>\d+) source files?\)"
)
SUCCESS_SUMMARY = re.compile(
    r"Success: no issues found in (?P<checked>\d+) source files?"
)


def parse_summary(output: str, returncode: int) -> tuple[int, int]:
    if match := ERROR_SUMMARY.search(output):
        return int(match.group("errors")), int(match.group("checked"))
    if returncode == 0 and (match := SUCCESS_SUMMARY.search(output)):
        return 0, int(match.group("checked"))
    raise ValueError("mypy did not emit a recognized terminal summary")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []

    for name, target in TARGETS.items():
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                target.path,
                "--no-color-output",
                "--no-pretty",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        )
        try:
            errors, checked = parse_summary(output, completed.returncode)
        except ValueError as exc:
            tail = "\n".join(output.splitlines()[-20:])
            failures.append(f"{name}: {exc}\n{tail}")
            continue

        print(
            f"{name}: {errors}/{target.expected_errors} errors; "
            f"{checked} source files checked"
        )
        if checked < target.minimum_source_files:
            failures.append(
                f"{name}: checked only {checked} source files; "
                f"expected at least {target.minimum_source_files}"
            )
        if errors > target.expected_errors:
            failures.append(
                f"{name}: mypy backlog grew from {target.expected_errors} to {errors}"
            )
        if errors < target.expected_errors:
            failures.append(
                f"{name}: mypy backlog improved from {target.expected_errors} to "
                f"{errors}; lower the recorded ceiling in the same change"
            )

    if failures:
        print("\nMypy backlog gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
