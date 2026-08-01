#!/usr/bin/env python3
"""Report Python reachability and legacy classifications without mutating state.

Static reachability is evidence, not deletion authority.  This report never
classifies an unreferenced module as safe to remove: retained database rows,
receipt files, dynamic callers, and external operator scripts must be measured
before a compatibility reader or command can be deleted.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
import tomllib
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Final

SCHEMA: Final = "creator_os.python_legacy_reachability.v1"
SKIP_PARTS: Final = frozenset(
    {".git", ".venv", "__pycache__", "fixtures", "node_modules", "tests"}
)
CLASSIFICATION_RULES: Final = (
    (
        "campaign_factory.creative_approval",
        "active_required",
        "v2 approval is active while v1 is preserved as non-operational evidence",
    ),
    (
        "campaign_factory.adapters.threadsdash_handshake",
        "active_required",
        "v1 handshake remains selected for draft payload v2",
    ),
    (
        "campaign_factory.lineage_v2",
        "active_required",
        "upgrades Reel Factory lineage before final draft assembly",
    ),
    (
        "campaign_factory.provider_spend",
        "active_required",
        "Campaign-owned Higgsfield spend authorization path",
    ),
    (
        "creator_os_core.provider_spend",
        "active_required",
        "shared signed provider-spend wire verification",
    ),
    (
        "reel_factory.provider_spend_authorization",
        "active_required",
        "worker consumes Campaign authorization before provider execution",
    ),
    (
        "reel_factory.legacy_outcome_evidence",
        "historical_read_only_compatibility",
        "read-only export of retired Reel outcome tables",
    ),
    (
        "campaign_factory.adapters.threadsdash",
        "compatibility_surface",
        "supported external boundary facade; repository callers use the owning adapters directly",
    ),
    (
        "campaign_factory.audio_radar.__main__",
        "compatibility_surface",
        "python -m compatibility entrypoint for the active Audio Radar CLI",
    ),
    (
        "repurposer",
        "experimental_research",
        "packaged and tested experimental subsystem isolated from production orchestration",
    ),
    (
        "reel_factory.local_model_",
        "experimental_research",
        "experimental operator tooling outside the three public creation modes",
    ),
    (
        "reel_factory.local_video",
        "experimental_research",
        "experimental local-video tooling with internal plan references",
    ),
    (
        "reel_factory.local_wan",
        "experimental_research",
        "experimental local-Wan compatibility and worker tooling",
    ),
    (
        "reel_factory.media_features",
        "experimental_research",
        "advanced outcome-feature utility with tests but no active production caller",
    ),
    (
        "reel_factory.prompt_guidance",
        "experimental_research",
        "advanced prompt helper with tests but no active production caller",
    ),
)
DYNAMIC_ENTRYPOINTS: Final = {
    "campaign_factory.app": ("uvicorn-string:campaign-factory serve",),
}
LEGACY_SURFACES: Final = (
    {
        "id": "creative_approval_v1",
        "classification": "historical_read_only_compatibility",
        "evidence": [
            "campaign_factory.creative_approval.validate_creative_approval",
            "campaign_factory.creative_approval.CreativeApprovalStore.legacy_inventory",
            "campaign_factory.creative_approval.CreativeApprovalStore.status_for_asset",
        ],
        "removalBlockedBy": [
            "retained creative-approval v1 file census",
            "historical audit-retention decision",
        ],
    },
    {
        "id": "threadsdash_handshake_v1",
        "classification": "active_required",
        "evidence": [
            "campaign_factory.adapters.threadsdash_handshake.HANDSHAKE_SCHEMA_V1",
            "campaign_factory.adapters.threadsdash_draft_delivery._negotiate_threadsdash_draft_payload",
        ],
        "removalBlockedBy": [
            "ThreadsDashboard draft payload v2 retirement",
            "retained and external consumer inventory",
        ],
    },
    {
        "id": "generated_asset_lineage_v1",
        "classification": "active_required",
        "evidence": [
            "reel_factory.still_to_reel._write_lineage",
            "reel_factory.reel_pipeline_support.write_generated_asset_lineage_sidecar",
            "campaign_factory.lineage_v2.build_lineage_v2_core",
        ],
        "removalBlockedBy": [
            "v1 producer migration",
            "retained v1 sidecar and database census",
        ],
    },
    {
        "id": "provider_spend_authorization_v1",
        "classification": "active_required",
        "evidence": [
            "creator_os_core.provider_spend.verify_authorization",
            "campaign_factory.provider_spend.issue_provider_spend_authorization",
            "reel_factory.provider_spend_authorization.require_campaign_spend_authorization",
        ],
        "removalBlockedBy": [
            "Higgsfield production authorization migration",
            "retained authorization and execution-receipt census",
        ],
    },
    {
        "id": "reel_outcome_legacy_tables",
        "classification": "historical_read_only_compatibility",
        "evidence": [
            "reel_factory.legacy_outcome_evidence.export_legacy_outcome_evidence"
        ],
        "removalBlockedBy": [
            "retained Reel database census",
            "historical outcome migration and retention proof",
        ],
    },
    {
        "id": "reference_paid_cli_shims",
        "classification": "historical_read_only_compatibility",
        "evidence": [
            "reference_factory.cli:analyze-reference-with-gemini-api",
            "reference_factory.cli:analyze-reference-with-grok-api",
            "reference_factory.cli:compile-prompts-with-grok-api",
        ],
        "removalBlockedBy": ["external operator command and script inventory"],
    },
    {
        "id": "reference_sample_frames_videos_alias",
        "classification": "compatibility_surface",
        "evidence": ["reference_factory.cli:sample-frames --videos"],
        "removalBlockedBy": ["external operator command and script inventory"],
    },
    {
        "id": "repurposer",
        "classification": "experimental_research",
        "evidence": ["repurposer package", "campaign_factory AGENTS isolation rule"],
        "removalBlockedBy": [
            "external import inventory",
            "explicit product retirement decision",
        ],
    },
    {
        "id": "local_model_and_wan_tools",
        "classification": "experimental_research",
        "evidence": [
            "reel_factory.local_model_manager",
            "reel_factory.local_model_arena",
            "reel_factory.local_model_router",
            "reel_factory.local_video",
            "reel_factory.local_wan",
        ],
        "removalBlockedBy": [
            "direct CLI and operator workflow inventory",
            "internal generation-plan reachability retirement",
            "retained model/runtime evidence census",
        ],
    },
)
UNKNOWNS: Final = (
    "retained production database rows and WAL state",
    "retained receipt and sidecar files outside the repository",
    "external operator scripts, shell history, and scheduled commands",
    "dynamic imports whose module name is not a string literal",
    "subprocess invocations assembled dynamically",
    "ThreadsDashboard historical consumers and retained payloads",
    "historical provider responses and reference/audio evidence",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _module_name(path: Path, root: Path) -> tuple[str, bool] | None:
    relative = path.relative_to(root)
    if relative.parts[0] == "scripts":
        name = ".".join(relative.with_suffix("").parts)
        return name, False
    if (
        relative.parts[0] not in {"python_packages", "packages"}
        or len(relative.parts) < 4
    ):
        return None
    distribution_root = root.joinpath(*relative.parts[:2])
    inner = path.relative_to(distribution_root).with_suffix("")
    if inner.name == "__init__":
        return ".".join(inner.parts[:-1]), True
    return ".".join(inner.parts), False


def source_modules(root: Path) -> dict[str, dict[str, Any]]:
    modules: dict[str, dict[str, Any]] = {}
    paths = [
        *root.glob("python_packages/*/**/*.py"),
        *root.glob("packages/*/**/*.py"),
        *root.glob("scripts/**/*.py"),
    ]
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if path.is_symlink() or any(part in SKIP_PARTS for part in relative.parts):
            continue
        identity = _module_name(path, root)
        if identity is None:
            continue
        module, is_package = identity
        modules[module] = {
            "module": module,
            "path": relative.as_posix(),
            "isPackage": is_package,
            "sha256": sha256_file(path),
        }
    return modules


def _resolve_relative_import(
    current: str, *, is_package: bool, level: int, module: str | None
) -> str:
    base = current.split(".") if is_package else current.split(".")[:-1]
    if level > 1:
        base = base[: -(level - 1)]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


class ReachabilityVisitor(ast.NodeVisitor):
    def __init__(self, module: str, *, is_package: bool) -> None:
        self.module = module
        self.is_package = is_package
        self.imports: set[str] = set()
        self.dynamic_imports: set[str] = set()
        self.calls: set[str] = set()
        self.has_main_guard = False

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.update(alias.name for alias in node.names)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            resolved = _resolve_relative_import(
                self.module,
                is_package=self.is_package,
                level=node.level,
                module=node.module,
            )
        else:
            resolved = node.module or ""
        if resolved:
            self.imports.add(resolved)
            self.imports.update(
                f"{resolved}.{alias.name}" for alias in node.names if alias.name != "*"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func)
        if name:
            self.calls.add(name)
        if name in {"importlib.import_module", "__import__"} and node.args:
            try:
                value = ast.literal_eval(node.args[0])
            except (ValueError, TypeError):
                value = None
            if isinstance(value, str):
                self.dynamic_imports.add(value)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            self.has_main_guard = True
        self.generic_visit(node)


def _entrypoints_from_pyproject(root: Path) -> dict[str, list[str]]:
    entrypoints: dict[str, list[str]] = defaultdict(list)
    for path in sorted(
        [root / "pyproject.toml", *root.glob("python_packages/*/pyproject.toml")]
    ):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            project = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        scripts = project.get("scripts") if isinstance(project, dict) else None
        if not isinstance(scripts, dict):
            continue
        for command, target in scripts.items():
            if not isinstance(target, str):
                continue
            module = target.split(":", 1)[0]
            entrypoints[module].append(f"project-script:{command}")
    return entrypoints


def _internal_target(name: str, known: set[str]) -> str | None:
    candidate = name
    while candidate:
        if candidate in known:
            return candidate
        candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
    return None


def _internal_targets(name: str, modules: dict[str, dict[str, Any]]) -> set[str]:
    """Return the imported module plus package initializers Python loads implicitly."""

    target = _internal_target(name, set(modules))
    if target is None:
        return set()
    targets = {target}
    parts = target.split(".")
    for size in range(1, len(parts)):
        parent = ".".join(parts[:size])
        if modules.get(parent, {}).get("isPackage"):
            targets.add(parent)
    return targets


def _classification(module: str, *, reachability: str | None = None) -> tuple[str, str]:
    if module == "reel_factory.local_wan":
        return (
            "compatibility_surface",
            "compatibility adapter preserving the original local-Wan worker API",
        )
    for prefix, classification, evidence in CLASSIFICATION_RULES:
        if (
            module == prefix
            or module.startswith(prefix + ".")
            or (prefix.endswith("_") and module.startswith(prefix))
        ):
            return classification, evidence
    if reachability == "reachable_from_entrypoint":
        return (
            "active_reachable",
            "statically reachable from a known operator, package-script, or module entrypoint",
        )
    return (
        "unknown",
        "static reachability alone cannot establish production role or deletion safety",
    )


def build_report(root: Path) -> dict[str, Any]:
    resolved = root.expanduser().resolve()
    modules = source_modules(resolved)
    declared_entrypoints = _entrypoints_from_pyproject(resolved)
    edges: dict[str, set[str]] = defaultdict(set)
    imported_by: dict[str, set[str]] = defaultdict(set)
    entrypoints: dict[str, set[str]] = defaultdict(set)

    for module, record in modules.items():
        path = resolved / record["path"]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=record["path"])
        visitor = ReachabilityVisitor(module, is_package=record["isPackage"])
        visitor.visit(tree)
        internal_imports = set().union(
            *(
                _internal_targets(value, modules)
                for value in (*visitor.imports, *visitor.dynamic_imports)
            )
        )
        edges[module].update(internal_imports)
        for target in internal_imports:
            imported_by[target].add(module)
        if visitor.has_main_guard:
            entrypoints[module].add("__main__")
        if module.endswith(".__main__"):
            entrypoints[module].add("python-module")
        if module.startswith("scripts."):
            entrypoints[module].add("operator-script")
        if declared := declared_entrypoints.get(module):
            entrypoints[module].update(declared)
        if declared := DYNAMIC_ENTRYPOINTS.get(module):
            entrypoints[module].update(declared)
        record.update(
            {
                "imports": sorted(visitor.imports),
                "dynamicLiteralImports": sorted(visitor.dynamic_imports),
                "internalImports": sorted(internal_imports),
                "calls": sorted(visitor.calls),
            }
        )

    roots = sorted(entrypoints)
    reachable: set[str] = set()
    queue: deque[str] = deque(roots)
    while queue:
        module = queue.popleft()
        if module in reachable:
            continue
        reachable.add(module)
        queue.extend(sorted(edges.get(module, ())))

    module_rows: list[dict[str, Any]] = []
    for module in sorted(modules):
        record = modules[module]
        if module in reachable:
            reachability = "reachable_from_entrypoint"
        elif imported_by[module]:
            reachability = "referenced_but_not_from_known_entrypoint"
        else:
            reachability = "statically_unreferenced"
        classification, evidence = _classification(module, reachability=reachability)
        module_rows.append(
            {
                **record,
                "importedBy": sorted(imported_by[module]),
                "entrypoints": sorted(entrypoints.get(module, ())),
                "reachability": reachability,
                "classification": classification,
                "classificationEvidence": evidence,
                "safeToRemove": False,
            }
        )

    core = {
        "schema": SCHEMA,
        "repositoryRoot": str(resolved),
        "readOnly": True,
        "staticAnalysisLimitationsAcknowledged": True,
        "modules": module_rows,
        "legacySurfaces": list(LEGACY_SURFACES),
        "safeToRemove": [],
        "unknowns": list(UNKNOWNS),
        "summary": {
            "moduleCount": len(module_rows),
            "knownEntrypointCount": len(roots),
            "reachableModuleCount": len(reachable),
            "staticallyUnreferencedModuleCount": sum(
                row["reachability"] == "statically_unreferenced" for row in module_rows
            ),
            "referencedButNotFromKnownEntrypointCount": sum(
                row["reachability"] == "referenced_but_not_from_known_entrypoint"
                for row in module_rows
            ),
            "classificationCounts": {
                classification: sum(
                    row["classification"] == classification for row in module_rows
                )
                for classification in (
                    "active_required",
                    "active_reachable",
                    "compatibility_surface",
                    "experimental_research",
                    "historical_read_only_compatibility",
                    "migration_only",
                    "safe_to_migrate",
                    "safe_to_remove",
                    "unknown",
                )
            },
        },
    }
    return {**core, "reportFingerprint": fingerprint(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.root)
    except (OSError, SyntaxError, tomllib.TOMLDecodeError) as exc:
        print(f"legacy reachability failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            report,
            indent=None if args.compact else 2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
