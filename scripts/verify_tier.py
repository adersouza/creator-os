#!/usr/bin/env python3
"""Changed-file aware Creator OS verification tiers."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _base_ref() -> str:
    configured = os.environ.get("VERIFICATION_BASE_REF")
    if configured:
        return configured
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/main"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return "origin/main" if probe.returncode == 0 else "HEAD^"


def changed_files() -> list[str]:
    base = _base_ref()
    completed = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTD", f"{base}...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    committed = completed.stdout.splitlines() if completed.returncode == 0 else []
    working = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTD", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return sorted(set(committed + working + untracked))


def _python_files(files: list[str]) -> list[str]:
    return [path for path in files if path.endswith(".py") and (ROOT / path).is_file()]


def _focused_python_tests(files: list[str]) -> list[str]:
    selected: set[str] = set()
    for path in files:
        item = Path(path)
        if item.name.startswith("test_") and path.endswith(".py"):
            selected.add(path)
            continue
        if path.startswith("python_packages/campaign_factory/"):
            candidate = (
                ROOT
                / "python_packages/campaign_factory/tests"
                / (f"test_{item.stem}.py")
            )
        elif path.startswith("python_packages/reel_factory/"):
            candidate = (
                ROOT / "python_packages/reel_factory/tests" / (f"test_{item.stem}.py")
            )
        elif path.startswith("python_packages/reference_factory/"):
            candidate = (
                ROOT
                / "python_packages/reference_factory/tests"
                / (f"test_{item.stem}.py")
            )
        elif path.startswith("packages/creator_os_core/"):
            candidate = ROOT / "packages/creator_os_core/tests" / f"test_{item.stem}.py"
        elif path.startswith("packages/pipeline_contracts/"):
            candidate = (
                ROOT / "packages/pipeline_contracts/tests" / f"test_{item.stem}.py"
            )
        else:
            continue
        if candidate.is_file():
            selected.add(str(candidate.relative_to(ROOT)))
    if any(
        path == "scripts/check-prompt-regressions.sh"
        or path.startswith("evals/prompt_regressions/")
        for path in files
    ):
        selected.add("tests/integration/test_prompt_regression_offline.py")
    if any(
        path
        in {
            "Makefile",
            "package.json",
            "pnpm-lock.yaml",
            "pyproject.toml",
            "uv.lock",
        }
        or path == "scripts/verify_tier.py"
        or path.startswith(".github/workflows/")
        for path in files
    ):
        selected.add("tests/integration/test_tooling_guardrails.py")
    return sorted(selected)


def commands_for(tier: str, files: list[str]) -> list[list[str]]:
    python = _python_files(files)
    focused = _focused_python_tests(files)
    touches = lambda prefix: any(path.startswith(prefix) for path in files)
    contracts = touches("packages/pipeline_contracts/")
    contentforge = touches("packages/contentforge/")
    prompt_regressions = any(
        path == "scripts/check-prompt-regressions.sh"
        or path.startswith("evals/prompt_regressions/")
        for path in files
    )
    javascript_workspace = any(
        path in {"package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"}
        for path in files
    )
    cross_boundary = (
        contracts
        or touches("tests/integration/")
        or len(
            {
                path.split("/", 2)[1]
                for path in files
                if path.startswith(("packages/", "python_packages/"))
            }
        )
        > 1
    )

    fast: list[list[str]] = [["git", "diff", "--check"]]
    if python:
        fast.extend(
            [
                ["uv", "run", "ruff", "check", *python],
                ["uv", "run", "ruff", "format", "--check", *python],
            ]
        )
    if focused:
        fast.append(["uv", "run", "python", "-m", "pytest", "-q", *focused])
    if contracts:
        fast.append(["pnpm", "check:contracts"])
    if contentforge:
        fast.append(["pnpm", "--filter", "contentforge", "lint"])
    if prompt_regressions or javascript_workspace:
        fast.append(["pnpm", "check:prompts"])

    package_tests = (
        ("python_packages/campaign_factory/", "python_packages/campaign_factory/tests"),
        ("python_packages/reel_factory/", "python_packages/reel_factory/tests"),
        (
            "python_packages/reference_factory/",
            "python_packages/reference_factory/tests",
        ),
        ("packages/creator_os_core/", "packages/creator_os_core/tests"),
        ("packages/pipeline_contracts/", "packages/pipeline_contracts/tests"),
    )
    selected_package_tests = [
        tests for prefix, tests in package_tests if touches(prefix)
    ]

    def covered_by_selected_suite(test: str) -> bool:
        return any(
            test == root or test.startswith(f"{root}/")
            for root in selected_package_tests
        )

    affected = [
        command
        for command in fast
        if not (
            len(command) >= 6 and command[:5] == ["uv", "run", "python", "-m", "pytest"]
        )
    ]
    uncovered_focused = [
        test for test in focused if not covered_by_selected_suite(test)
    ]
    if cross_boundary:
        uncovered_focused = [
            test
            for test in uncovered_focused
            if not test.startswith("tests/integration/")
        ]
    if uncovered_focused:
        affected.append(
            ["uv", "run", "python", "-m", "pytest", "-q", *uncovered_focused]
        )
    for prefix, tests in package_tests:
        if touches(prefix):
            affected.append(["uv", "run", "python", "-m", "pytest", "-q", tests])
    if contentforge:
        if not javascript_workspace:
            affected.append(["pnpm", "--filter", "contentforge", "test"])
        affected.append(["pnpm", "--filter", "contentforge", "build"])
    if javascript_workspace:
        affected.append(["pnpm", "run", "test"])
    if cross_boundary:
        affected.append(
            ["uv", "run", "python", "-m", "pytest", "-q", "tests/integration"]
        )

    release = [
        ["pnpm", "run", "check:all"],
        ["pnpm", "run", "test"],
        ["uv", "run", "python", "-m", "pytest", "packages/pipeline_contracts/tests"],
        ["uv", "run", "python", "-m", "pytest", "packages/creator_os_core/tests"],
        [
            "uv",
            "run",
            "python",
            "-m",
            "pytest",
            "python_packages/campaign_factory/tests",
        ],
        [
            "uv",
            "run",
            "python",
            "-m",
            "pytest",
            "python_packages/reference_factory/tests",
        ],
        ["uv", "run", "python", "-m", "pytest", "python_packages/reel_factory/tests"],
        ["uv", "run", "python", "-m", "pytest", "tests/integration"],
    ]
    exhaustive = [
        *release,
        ["pnpm", "check:arch:fixtures"],
        ["pnpm", "audit:js-dead"],
        ["pnpm", "security:secrets"],
    ]
    return {
        "fast": fast,
        "affected": affected,
        "release": release,
        "exhaustive": exhaustive,
    }[tier]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tier", choices=["fast", "affected", "release", "exhaustive"])
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    files = changed_files()
    commands = commands_for(args.tier, files)
    print(f"verification tier={args.tier} changed_files={len(files)}")
    for command in commands:
        print("+", " ".join(command))
    if args.list:
        return 0
    started = time.monotonic()
    for command in commands:
        command_started = time.monotonic()
        print("+ running", " ".join(command), flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        elapsed = time.monotonic() - command_started
        print(f"verification command seconds={elapsed:.1f} command={' '.join(command)}")
        if completed.returncode:
            print(
                f"verification failed tier={args.tier} command={' '.join(command)}",
                file=sys.stderr,
            )
            return completed.returncode
    print(
        f"verification passed tier={args.tier} seconds={time.monotonic() - started:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
