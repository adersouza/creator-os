#!/usr/bin/env python3
"""Reject high-risk local trust-boundary bypasses and security-workflow drift."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

PYTHON_ROOTS = ("packages", "python_packages", "scripts")
SKIP_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "fixtures",
    "node_modules",
    "tests",
}
SUBPROCESS_CALLS = {
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "subprocess.run",
}
FORBIDDEN_CALLS = {
    "os.popen": "shell command strings are forbidden",
    "os.system": "shell command strings are forbidden",
    "tempfile.mktemp": "race-prone temporary paths are forbidden",
    "urllib.request.urlretrieve": "downloads must use staged_public_download",
    "pickle.load": "untrusted pickle deserialization is forbidden",
    "pickle.loads": "untrusted pickle deserialization is forbidden",
}
ARCHIVE_METHODS = {"extract", "extractall"}
SHA_PIN = re.compile(r"^[0-9a-f]{40}$")


def dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def literal_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


class BoundaryVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[str] = []

    def report(self, node: ast.AST, message: str) -> None:
        self.violations.append(f"{self.path}:{node.lineno}: {message}")

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func)
        if reason := FORBIDDEN_CALLS.get(name):
            self.report(node, f"{name}: {reason}")
        if name in SUBPROCESS_CALLS:
            if any(
                keyword.arg == "shell" and literal_true(keyword.value)
                for keyword in node.keywords
            ):
                self.report(node, "subprocess shell=True is forbidden")
            if node.args and isinstance(node.args[0], (ast.Constant, ast.JoinedStr)):
                self.report(node, "subprocess requires an argument array")
        if isinstance(node.func, ast.Attribute) and node.func.attr in ARCHIVE_METHODS:
            self.report(
                node,
                "direct archive extraction is forbidden; use safe_extract_zip",
            )
        if name == "yaml.load":
            loader = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "Loader"),
                None,
            )
            if dotted_name(loader) not in {"yaml.SafeLoader", "SafeLoader"}:
                self.report(node, "yaml.load requires SafeLoader")
        self.generic_visit(node)


def python_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for source_root in PYTHON_ROOTS:
        for path in (root / source_root).rglob("*.py"):
            relative = path.relative_to(root)
            if any(part in SKIP_PARTS for part in relative.parts):
                continue
            try:
                tree = ast.parse(
                    path.read_text(encoding="utf-8"), filename=str(relative)
                )
            except (SyntaxError, UnicodeDecodeError) as exc:
                violations.append(f"{relative}: could not parse: {exc}")
                continue
            visitor = BoundaryVisitor(relative)
            visitor.visit(tree)
            violations.extend(visitor.violations)
    return violations


def workflow_violations(root: Path) -> list[str]:
    violations: list[str] = []
    workflow_root = root / ".github" / "workflows"
    for path in sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))):
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("- uses:") or stripped.startswith("uses:"):
                reference = stripped.split("@", 1)[-1].split()[0]
                if not SHA_PIN.fullmatch(reference):
                    violations.append(
                        f"{relative}:{line_number}: action is not pinned to a full commit SHA"
                    )
        if "step-security/harden-runner@" in text:
            if "egress-policy: audit" in text:
                violations.append(
                    f"{relative}: harden-runner may not use audit-only egress"
                )
            if "allowed-endpoints: |" in text:
                violations.append(
                    f"{relative}: harden-runner endpoints must use folded YAML so ports parse correctly"
                )
            blocks = text.split("step-security/harden-runner@")[1:]
            if any("egress-policy: block" not in block[:800] for block in blocks):
                violations.append(
                    f"{relative}: every harden-runner step must block egress"
                )

    security = (workflow_root / "security.yml").read_text(encoding="utf-8")
    if "pull_request:" not in security:
        violations.append("security workflow must run on pull requests")
    for job in ("codeql", "trivy"):
        marker = f"  {job}:"
        start = security.find(marker)
        if start < 0:
            violations.append(f"security workflow is missing {job}")
            continue
        next_job = security.find("\n  ", start + len(marker))
        block = security[start : next_job if next_job >= 0 else None]
        if "github.event_name != 'pull_request'" in block:
            violations.append(f"security workflow excludes {job} from pull requests")
    if "actions/dependency-review-action@" not in security:
        violations.append("security workflow is missing dependency review")
    if 'REQUIRE_SECRET_SCANNER: "1"' not in security:
        violations.append("security workflow does not require a secret scanner")

    monorepo = (workflow_root / "monorepo-ci.yml").read_text(encoding="utf-8")
    for artifact in (
        "javascript.cdx.json",
        "python.cdx.json",
        "toolchain-inventory.json",
    ):
        if artifact not in (
            root / "scripts" / "security" / "generate-sbom.sh"
        ).read_text(encoding="utf-8"):
            violations.append(f"SBOM generation is missing {artifact}")
    if "scripts/security/generate-sbom.sh" not in monorepo:
        violations.append("monorepo CI does not invoke canonical SBOM generation")
    return violations


def javascript_violations(root: Path) -> list[str]:
    violations: list[str] = []
    shell_true = re.compile(r"\bshell\s*:\s*true\b")
    child_exec = re.compile(
        r"\b(?:child_process\.)?(?:exec|execSync)\s*\(",
    )
    for source_root in ("packages", "scripts"):
        for suffix in ("*.js", "*.mjs", "*.ts"):
            for path in (root / source_root).rglob(suffix):
                relative = path.relative_to(root)
                if any(part in SKIP_PARTS for part in relative.parts):
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                if shell_true.search(text):
                    violations.append(
                        f"{relative}: JavaScript shell execution is forbidden"
                    )
                if child_exec.search(text):
                    violations.append(
                        f"{relative}: child_process exec strings are forbidden; use execFile/spawn argv"
                    )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    violations = [
        *python_violations(root),
        *javascript_violations(root),
        *workflow_violations(root),
    ]
    if violations:
        print("Local trust-boundary violations:")
        for violation in violations:
            print(f"  {violation}")
        return 1
    print("Local trust-boundary and CI-security architecture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
