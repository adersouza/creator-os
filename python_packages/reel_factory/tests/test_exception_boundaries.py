from __future__ import annotations

import ast
from pathlib import Path

import hook_ai
import preflight
import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = (
    Path(__file__).resolve().parent / "fixtures" / "broad_exception_allowlist.txt"
)


def _broad_exception_handlers() -> list[str]:
    entries: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        stack: list[str] = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
                broad = isinstance(node.type, ast.Name) and node.type.id == "Exception"
                broad_tuple = isinstance(node.type, ast.Tuple) and any(
                    isinstance(item, ast.Name) and item.id == "Exception"
                    for item in node.type.elts
                )
                if broad or broad_tuple:
                    entries.append(
                        f"{path.relative_to(PACKAGE_ROOT)}:{stack[-1] if stack else '<module>'}:{node.lineno}"
                    )
                self.generic_visit(node)

        Visitor().visit(tree)
    return entries


def test_broad_exception_boundaries_are_explicitly_allowlisted() -> None:
    expected = [
        line.strip()
        for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert _broad_exception_handlers() == expected


def test_preflight_narrowed_probe_boundary_propagates_unexpected_errors(
    monkeypatch, tmp_path: Path
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")

    def unexpected_probe(*args, **kwargs):
        raise AssertionError("programmer error")

    monkeypatch.setattr(preflight, "_probe_video", unexpected_probe)

    with pytest.raises(AssertionError, match="programmer error"):
        preflight.check_clip_readiness(video, None, ffprobe="ffprobe")


def test_hook_generation_narrowed_boundary_propagates_unexpected_errors(
    monkeypatch,
) -> None:
    class BrokenProvider:
        def __init__(self, *args, **kwargs):
            pass

        def available(self):
            return True, "ok"

        def rewrite(self, *args, **kwargs):
            raise AssertionError("unexpected provider bug")

    monkeypatch.setattr(hook_ai, "OllamaHookProvider", BrokenProvider)

    with pytest.raises(AssertionError, match="unexpected provider bug"):
        hook_ai.generate_hooks(backend="ollama", model="model", base="base hook")
