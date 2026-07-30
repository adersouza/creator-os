from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/runtime_manifest.py"
    spec = importlib.util.spec_from_file_location("runtime_manifest_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_root(tmp_path: Path) -> Path:
    for name in (
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "pyproject.toml",
        "uv.lock",
    ):
        (tmp_path / name).write_text(f"{name}\n", encoding="utf-8")
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "steps:\n  - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )
    font = (
        tmp_path
        / "python_packages/reel_factory/fonts/InstagramSansCondensed-Regular.woff2"
    )
    font.parent.mkdir(parents=True)
    font.write_bytes(b"font")
    schemas = (
        tmp_path / "packages/pipeline_contracts/pipeline_contracts/schemas/example.json"
    )
    schemas.parent.mkdir(parents=True)
    schemas.write_text("{}\n", encoding="utf-8")
    manifest = tmp_path / "packages/pipeline_contracts/contract-manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    generated = tmp_path / "packages/pipeline_contracts/typescript/generated-schemas.ts"
    generated.parent.mkdir(parents=True)
    generated.write_text("export {};\n", encoding="utf-8")
    model = (
        tmp_path / "python_packages/reel_factory/reel_factory/video_provider_models.py"
    )
    model.parent.mkdir(parents=True)
    model.write_text(
        'MODEL_REVISION = "abc123"\n'
        'record = dict(model_id="literal-is-not-a-call-keyword")\n',
        encoding="utf-8",
    )
    return tmp_path


def _stable_runtime(monkeypatch: pytest.MonkeyPatch, module) -> None:
    monkeypatch.setattr(
        module,
        "git_identity",
        lambda _root: {
            "commitSha": "a" * 40,
            "dirty": False,
            "dirtyEntryCount": 0,
        },
    )
    monkeypatch.setattr(
        module,
        "binary_inventory",
        lambda _root: {
            "required": {"python3": {"sha256": "b" * 64}},
            "optional": {"swift": None},
            "missingOptional": ["swift"],
        },
    )
    monkeypatch.setattr(
        module,
        "brew_inventory",
        lambda _root: {"available": False, "formulae": {}},
    )


def test_manifest_is_deterministic_secret_free_and_truthful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    root = _fixture_root(tmp_path)
    model_root = tmp_path / "models"
    model_root.mkdir()
    (model_root / "weights.bin").write_bytes(b"weights")
    _stable_runtime(monkeypatch, module)
    env = {
        "OPENAI_API_KEY": "sk-must-never-appear",
        "CREATOR_OS_MODEL_ROOT": str(model_root),
    }

    first = module.build_manifest(root, env=env, model_root=model_root)
    second = module.build_manifest(root, env=env, model_root=model_root)

    assert first == second
    assert first["manifestFingerprint"] == second["manifestFingerprint"]
    assert first["claim"]["byteIdenticalMediaOutputClaimed"] is False
    assert first["environment"]["secretMaterialIncluded"] is False
    assert "sk-must-never-appear" not in json.dumps(first)
    openai = next(
        item
        for item in first["environment"]["variables"]
        if item["name"] == "OPENAI_API_KEY"
    )
    assert openai == {
        "name": "OPENAI_API_KEY",
        "configured": True,
        "sensitive": True,
        "valueRecorded": False,
    }
    assert first["workflows"]["allActionsPinned"] is True
    assert first["fonts"][0]["sha256"] == module.sha256_file(
        root / "python_packages/reel_factory/fonts/InstagramSansCondensed-Regular.woff2"
    )
    assert first["modelFiles"]["files"][0]["path"] == "weights.bin"
    assert first["modelCatalogs"][0]["declaredIdentities"] == [
        {"field": "MODEL_REVISION", "value": "abc123"},
        {"field": "model_id", "value": "literal-is-not-a-call-keyword"},
    ]


def test_manifest_fingerprint_changes_with_reproducibility_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    root = _fixture_root(tmp_path)
    _stable_runtime(monkeypatch, module)
    model_root = tmp_path / "models"
    first = module.build_manifest(root, env={}, model_root=model_root)
    font = (
        root / "python_packages/reel_factory/fonts/InstagramSansCondensed-Regular.woff2"
    )
    font.write_bytes(b"changed-font")
    second = module.build_manifest(root, env={}, model_root=model_root)
    assert first["manifestFingerprint"] != second["manifestFingerprint"]


def test_required_tool_missing_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.setattr(module, "binary_record", lambda _tool, root: None)
    with pytest.raises(module.RuntimeManifestError, match="required runtime tools"):
        module.binary_inventory(tmp_path)


def test_optional_tool_missing_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()

    def record(tool: str, *, root: Path):
        del root
        return None if tool in module.OPTIONAL_TOOLS else {"version": tool}

    monkeypatch.setattr(module, "binary_record", record)
    inventory = module.binary_inventory(tmp_path)
    assert inventory["missingOptional"] == sorted(module.OPTIONAL_TOOLS)
    assert all(value is None for value in inventory["optional"].values())


def test_unpinned_action_blocks_equivalent_input_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    root = _fixture_root(tmp_path)
    _stable_runtime(monkeypatch, module)
    (root / ".github/workflows/ci.yml").write_text(
        "steps:\n  - uses: actions/checkout@main\n", encoding="utf-8"
    )
    manifest = module.build_manifest(
        root,
        env={},
        model_root=tmp_path / "models",
    )
    assert manifest["workflows"]["allActionsPinned"] is False
    assert (
        "github_actions_not_fully_commit_pinned"
        in manifest["qualification"]["blockers"]
    )
