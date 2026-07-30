from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/legacy_reachability.py"
    spec = importlib.util.spec_from_file_location(
        "legacy_reachability_under_test", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_root(tmp_path: Path) -> Path:
    package = tmp_path / "python_packages/demo/demo"
    package.mkdir(parents=True)
    (tmp_path / "python_packages/demo/pyproject.toml").write_text(
        "[project]\n"
        'name = "demo"\n'
        'version = "1"\n'
        "[project.scripts]\n"
        'demo = "demo.cli:main"\n',
        encoding="utf-8",
    )
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "from . import worker\n"
        "def main():\n"
        "    return worker.run()\n"
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    (package / "worker.py").write_text(
        "import importlib\n"
        'importlib.import_module("demo.compat")\n'
        "def run():\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (package / "compat.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "unused.py").write_text("VALUE = 2\n", encoding="utf-8")
    return tmp_path


def test_import_call_and_entrypoint_reachability_is_reported_read_only(
    tmp_path: Path,
) -> None:
    module = _module()
    root = _fixture_root(tmp_path)
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    report = module.build_report(root)

    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert report["readOnly"] is True
    assert report["safeToRemove"] == []
    rows = {row["module"]: row for row in report["modules"]}
    assert rows["demo.cli"]["entrypoints"] == ["__main__", "project-script:demo"]
    assert rows["demo.worker"]["reachability"] == "reachable_from_entrypoint"
    assert rows["demo.compat"]["reachability"] == "reachable_from_entrypoint"
    assert rows["demo.unused"]["reachability"] == "statically_unreferenced"
    assert rows["demo.unused"]["classification"] == "unknown"
    assert rows["demo.unused"]["safeToRemove"] is False
    assert "worker.run" in rows["demo.cli"]["calls"]


def test_evidence_backed_classifications_never_infer_safe_removal() -> None:
    module = _module()
    assert module._classification("campaign_factory.provider_spend")[0] == (
        "active_required"
    )
    assert module._classification("reel_factory.legacy_outcome_evidence")[0] == (
        "historical_read_only_compatibility"
    )
    assert module._classification("repurposer.pipeline")[0] == "unknown"
    assert module._classification("unmapped.module")[0] == "unknown"
    assert not any(
        surface["classification"] == "safe_to_remove"
        for surface in module.LEGACY_SURFACES
    )


def test_current_repository_report_preserves_known_legacy_surfaces() -> None:
    module = _module()
    report = module.build_report(ROOT)
    surfaces = {surface["id"]: surface for surface in report["legacySurfaces"]}
    assert surfaces["provider_spend_authorization_v1"]["classification"] == (
        "active_required"
    )
    assert surfaces["creative_approval_v1"]["classification"] == (
        "historical_read_only_compatibility"
    )
    assert report["summary"]["classificationCounts"]["safe_to_remove"] == 0
    assert report["safeToRemove"] == []
