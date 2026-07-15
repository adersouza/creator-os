from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).parents[1] / "campaign_factory"

FOCUSED_MODULES = (
    "cli.py",
    "cli_dispatch_operations.py",
    "cli_dispatch_pipeline.py",
    "cli_dispatch_scale.py",
    "cli_parser.py",
    "cli_parser_core.py",
    "cli_parser_operations.py",
    "cli_support.py",
    "creative_knowledge.py",
    "creative_knowledge_analysis.py",
    "creative_knowledge_registry.py",
    "db.py",
    "db_migrations.py",
    "db_schema.py",
    "recommendation_constants.py",
    "recommendation_lifecycle.py",
    "recommendation_planning.py",
    "recommendation_scoring.py",
    "recommendations.py",
)


def _source(name: str) -> str:
    return (PACKAGE / name).read_text(encoding="utf-8")


def test_campaign_modules_stay_below_operational_size_limit() -> None:
    module_names = {path.name for path in PACKAGE.glob("*.py")}
    assert set(FOCUSED_MODULES) <= module_names
    oversized = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in PACKAGE.glob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) >= 1500
    }
    assert oversized == {}


def test_cli_entrypoint_does_not_reabsorb_parser_or_command_handlers() -> None:
    source = _source("cli.py")
    assert "add_parser" not in source
    assert source.count("args.cmd ==") == 1
    assert 'args.cmd == "serve"' in source
    assert "__getattr__" not in source


def test_repository_composition_has_no_forwarding_methods() -> None:
    expectations = {
        "recommendations.py": (
            "RecommendationRepository",
            {
                "RecommendationPlanningMixin",
                "RecommendationLifecycleMixin",
                "RecommendationScoringMixin",
            },
        ),
        "creative_knowledge.py": (
            "CreativeKnowledgeRepository",
            {"CreativeKnowledgeAnalysisMixin", "CreativeKnowledgeRegistryMixin"},
        ),
    }
    for module_name, (class_name, expected_bases) in expectations.items():
        tree = ast.parse(_source(module_name))
        repository = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        bases = {base.id for base in repository.bases if isinstance(base, ast.Name)}
        methods = {
            node.name
            for node in repository.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert bases == expected_bases
        assert methods == {"__init__"}
        assert "__getattr__" not in _source(module_name)


def test_database_schema_and_migrations_remain_separate() -> None:
    assert "SCHEMA =" not in _source("db.py")
    assert "def _migrate_" not in _source("db.py")
    assert "def _repair_" not in _source("db.py")
    assert "SCHEMA =" in _source("db_schema.py")
    assert "def _migrate_" in _source("db_migrations.py")
