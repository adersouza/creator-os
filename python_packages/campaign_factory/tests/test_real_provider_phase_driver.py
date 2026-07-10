from __future__ import annotations

import sys

import pytest
from scripts.real_provider_phase_driver import command_env_name, run_phase


def test_phase_driver_forwards_json_without_putting_payload_in_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = (
        f"{sys.executable} -c "
        "'import json,sys; value=json.load(sys.stdin); "
        'print(json.dumps({"id": value["soulId"], "argc": len(sys.argv)}))\''
    )
    monkeypatch.setenv(command_env_name("verify_soul"), command)

    result = run_phase({"phase": "verify_soul", "soulId": "soul_1"})

    assert result == {"id": "soul_1", "argc": 1}


def test_phase_driver_requires_explicit_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(command_env_name("quote"), raising=False)
    with pytest.raises(RuntimeError, match=command_env_name("quote")):
        run_phase({"phase": "quote", "soulId": "soul_1"})


@pytest.mark.parametrize(
    "lineage",
    [
        {"scheduleMode": "live", "publishRequested": False},
        {"scheduleMode": "draft", "publishRequested": True},
    ],
)
def test_phase_driver_rejects_non_draft_ingest(
    monkeypatch: pytest.MonkeyPatch, lineage: dict[str, object]
) -> None:
    monkeypatch.setenv(
        command_env_name("hmac_ingest_preview_draft"),
        f"{sys.executable} -c 'print(\"{{}}\")'",
    )
    with pytest.raises(ValueError, match="draft-only|publishing"):
        run_phase(
            {
                "phase": "hmac_ingest_preview_draft",
                "mp4Path": "/tmp/static.mp4",
                "lineage": lineage,
            }
        )


def test_phase_driver_rejects_unknown_phase() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        run_phase({"phase": "publish"})
