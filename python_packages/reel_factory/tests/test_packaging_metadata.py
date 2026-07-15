from __future__ import annotations

import pathlib
import tomllib

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())


def _is_bounded(requirement: str) -> bool:
    return (">=" in requirement or "~=" in requirement or "==" in requirement) and (
        "<" in requirement or "~=" in requirement or "==" in requirement
    )


def test_flat_compatibility_modules_are_not_packaged() -> None:
    setuptools = _pyproject()["tool"]["setuptools"]

    assert "py-modules" not in setuptools
    assert list(PACKAGE_ROOT.glob("*.py")) == []


def test_canonical_packages_are_discovered() -> None:
    includes = _pyproject()["tool"]["setuptools"]["packages"]["find"]["include"]

    assert includes == ["experiments*", "reel_factory*"]
    assert (PACKAGE_ROOT / "reel_factory/__init__.py").exists()
    assert (PACKAGE_ROOT / "experiments/__init__.py").exists()


def test_standalone_dependencies_are_pinned_and_resolvable() -> None:
    project = _pyproject()["project"]

    dependencies = project["dependencies"]
    assert "pipeline-contracts" not in {
        dep.split(";", 1)[0].split("[", 1)[0].split(">=", 1)[0] for dep in dependencies
    }
    assert all(_is_bounded(dependency) for dependency in dependencies)

    optional_dependencies = _pyproject()["project"]["optional-dependencies"]
    for requirements in optional_dependencies.values():
        assert all(_is_bounded(requirement) for requirement in requirements)


def test_requirements_file_delegates_to_pyproject() -> None:
    lines = [
        line.strip()
        for line in (PACKAGE_ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert lines == ["-e .[vision]"]
