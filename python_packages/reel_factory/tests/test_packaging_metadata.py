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


def test_declared_py_modules_exist() -> None:
    modules = _pyproject()["tool"]["setuptools"]["py-modules"]

    missing = [
        module for module in modules if not (PACKAGE_ROOT / f"{module}.py").exists()
    ]

    assert missing == []


def test_top_level_modules_are_declared_for_wheel_imports() -> None:
    modules = set(_pyproject()["tool"]["setuptools"]["py-modules"])
    actual = {path.stem for path in PACKAGE_ROOT.glob("*.py")}

    assert sorted(actual - modules) == []


def test_declared_packages_exist() -> None:
    packages = _pyproject()["tool"]["setuptools"]["packages"]

    missing = [
        package
        for package in packages
        if not (PACKAGE_ROOT / package.replace(".", "/") / "__init__.py").exists()
    ]

    assert missing == []


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
