from __future__ import annotations

import ast
from pathlib import Path

ADAPTERS = Path(__file__).parents[1] / "campaign_factory" / "adapters"


def _tree(name: str) -> ast.Module:
    return ast.parse((ADAPTERS / name).read_text(encoding="utf-8"))


def _definitions(name: str) -> set[str]:
    return {
        node.name
        for node in _tree(name).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_threadsdash_compatibility_surface_contains_no_implementation() -> None:
    assert _definitions("threadsdash.py") == set()


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
