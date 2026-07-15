from __future__ import annotations

import ast
from inspect import Signature, signature
from pathlib import Path

from campaign_factory.adapters import threadsdash as threadsdash_port
from campaign_factory.adapters import (
    threadsdash_account_projection,
    threadsdash_draft_delivery,
    threadsdash_draft_readiness,
    threadsdash_handshake,
    threadsdash_metrics_ingestion,
)

ADAPTERS = Path(__file__).parents[1] / "campaign_factory" / "adapters"
PACKAGE = ADAPTERS.parent
REPO_ROOT = Path(__file__).parents[3]
SUPPORTED_PORT = {
    "export_drafts",
    "handshake",
    "sync_accounts",
    "sync_metrics",
    "verify_export",
}


def _tree(name: str) -> ast.Module:
    return ast.parse((ADAPTERS / name).read_text(encoding="utf-8"))


def _definitions(name: str) -> set[str]:
    return {
        node.name
        for node in _tree(name).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_threadsdash_port_contains_no_implementation_or_private_exports() -> None:
    assert _definitions("threadsdash.py") == set()
    assert set(threadsdash_port.__all__) == SUPPORTED_PORT
    assert not {
        name
        for name in vars(threadsdash_port)
        if name.startswith("_") and not name.startswith("__")
    }
    assert threadsdash_port.handshake is threadsdash_handshake.run_threadsdash_handshake
    assert (
        threadsdash_port.sync_accounts
        is threadsdash_account_projection.sync_threadsdash_instagram_accounts
    )
    assert (
        threadsdash_port.export_drafts is threadsdash_draft_delivery.export_threadsdash
    )
    assert (
        threadsdash_port.verify_export
        is threadsdash_draft_readiness.verify_threadsdash_export
    )
    assert (
        threadsdash_port.sync_metrics
        is threadsdash_metrics_ingestion.sync_performance_snapshots
    )
    assert all(
        signature(getattr(threadsdash_port, operation)).return_annotation
        is not Signature.empty
        for operation in SUPPORTED_PORT
    )


def test_campaign_internals_do_not_import_the_public_threadsdash_port() -> None:
    offenders: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        if path == ADAPTERS / "threadsdash.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports_port = module == "adapters.threadsdash" or module.endswith(
                    ".adapters.threadsdash"
                )
                imports_module = module.endswith(".adapters") and any(
                    alias.name == "threadsdash" for alias in node.names
                )
                if imports_port or imports_module:
                    offenders.append(str(path.relative_to(PACKAGE)))
            elif isinstance(node, ast.Import) and any(
                alias.name.endswith(".adapters.threadsdash") for alias in node.names
            ):
                offenders.append(str(path.relative_to(PACKAGE)))
    assert offenders == []


def test_repository_callers_use_only_supported_threadsdash_port_names() -> None:
    offenders: list[str] = []
    search_roots = (
        REPO_ROOT / "python_packages",
        REPO_ROOT / "packages",
        REPO_ROOT / "scripts",
        REPO_ROOT / "tests",
    )
    for root in search_roots:
        for path in root.rglob("*.py"):
            if path in {ADAPTERS / "threadsdash.py", Path(__file__)}:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                module = node.module or ""
                if module == "adapters.threadsdash" or module.endswith(
                    ".adapters.threadsdash"
                ):
                    unsupported = {alias.name for alias in node.names} - SUPPORTED_PORT
                    if unsupported:
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}:{sorted(unsupported)}"
                        )
    assert offenders == []


def test_removed_threadsdash_compatibility_handoff_has_no_file() -> None:
    assert not (ADAPTERS / "threadsdash_draft_handoff.py").exists()


def test_threadsdash_adapter_ownership_stays_split() -> None:
    assert "SupabaseRestClient" in _definitions("threadsdash_client.py")
    assert {
        "build_draft_payloads",
        "export_threadsdash",
        "evaluate_export_readiness",
    } <= (
        _definitions("threadsdash_draft_payload.py")
        | _definitions("threadsdash_draft_delivery.py")
        | _definitions("threadsdash_draft_readiness.py")
    )
    assert {
        "sync_threadsdash_account_assignments",
        "sync_threadsdash_instagram_accounts",
    } <= _definitions("threadsdash_account_projection.py")
    assert "sync_performance_snapshots" in _definitions(
        "threadsdash_metrics_ingestion.py"
    )

    owned_modules = (
        "threadsdash_client.py",
        "threadsdash_handshake.py",
        "threadsdash_draft_payload.py",
        "threadsdash_draft_delivery.py",
        "threadsdash_draft_readiness.py",
        "threadsdash_account_projection.py",
        "threadsdash_metrics_ingestion.py",
    )
    assert all(
        len((ADAPTERS / name).read_text(encoding="utf-8").splitlines()) < 1500
        for name in owned_modules
    )


def test_creator_os_threadsdash_adapter_remains_draft_only() -> None:
    source = "\n".join(
        (ADAPTERS / name).read_text(encoding="utf-8")
        for name in (
            "threadsdash_draft_payload.py",
            "threadsdash_draft_delivery.py",
            "threadsdash_draft_readiness.py",
        )
    )
    assert "Campaign Factory exports are draft-only" in source
    definitions = set().union(
        *(
            _definitions(name)
            for name in (
                "threadsdash_draft_payload.py",
                "threadsdash_draft_delivery.py",
                "threadsdash_draft_readiness.py",
            )
        )
    )
    assert not definitions & {
        "preview_threadsdash_schedule",
        "promote_threadsdash_schedule",
        "schedule_post",
        "publish_post",
    }
