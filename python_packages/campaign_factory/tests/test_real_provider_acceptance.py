from __future__ import annotations

import json
from pathlib import Path

import pytest
from campaign_factory.real_provider_acceptance import (
    STACEY_SOUL_ID,
    run_real_provider_acceptance,
)


class FakeAcceptanceSeams:
    def __init__(self, *, consume_ok: bool = True, qc_ok: bool = True) -> None:
        self.consume_ok = consume_ok
        self.qc_ok = qc_ok
        self.calls: list[str] = []

    def verify_soul(self, soul_id: str) -> dict:
        self.calls.append("verify_soul")
        return {"id": soul_id, "name": "Stacey", "access_token": "secret"}

    def quote(self, soul_id: str) -> dict:
        self.calls.append("quote")
        return {
            "schema": "reel_factory.higgsfield_provider_quote.v1",
            "provider": "higgsfield",
            "model": "soul_2",
            "amount": 1.0,
            "unit": "higgsfield_credits",
            "raw": {"token": "secret"},
        }

    def reserve(self, quote: dict, max_credits: float) -> dict:
        self.calls.append("reserve")
        return {
            "allowed": True,
            "reservation": {"id": "hfr_1", "status": "reserved"},
        }

    def consume(self, reservation_id: str) -> bool:
        self.calls.append("consume")
        return self.consume_ok

    def cancel(self, reservation_id: str) -> bool:
        self.calls.append("cancel")
        return True

    def generate(self, soul_id: str, workspace: Path) -> dict:
        self.calls.append("generate")
        image = workspace / "provider.png"
        image.write_bytes(b"provider-image")
        return {"jobId": "job_1", "imagePath": str(image)}

    def render_static_mp4(self, image_path: Path, workspace: Path) -> dict:
        self.calls.append("render")
        mp4 = workspace / "static.mp4"
        mp4.write_bytes(b"static-mp4")
        return {"mp4Path": str(mp4)}

    def reel_qc(self, mp4_path: Path, lineage: dict) -> dict:
        self.calls.append("reel_qc")
        return {"ok": self.qc_ok, "lineagePreserved": True}

    def contentforge_qc(self, mp4_path: Path) -> dict:
        self.calls.append("contentforge_qc")
        return {"ok": self.qc_ok, "profile": "campaign_factory_v1"}

    def hmac_ingest_preview_draft(self, mp4_path: Path, lineage: dict) -> dict:
        self.calls.append("ingest")
        return {
            "statusCode": 200,
            "postIds": ["draft_post_1"],
            "attempts": 1,
            "signature": "secret",
        }

    def verify_draft(self, ingest: dict, lineage: dict) -> dict:
        self.calls.append("verify_draft")
        return {"ok": True, "postId": "draft_post_1", "lineageMatch": True}


def test_real_provider_acceptance_runs_paid_call_once_and_writes_redacted_artifact(
    tmp_path: Path,
) -> None:
    seams = FakeAcceptanceSeams()

    result = run_real_provider_acceptance(
        workspace=tmp_path,
        target_environment="preview",
        paid_confirmation=True,
        max_credits=1.0,
        seams=seams,
    )

    assert result["ok"] is True
    assert seams.calls == [
        "verify_soul",
        "quote",
        "reserve",
        "consume",
        "generate",
        "render",
        "reel_qc",
        "contentforge_qc",
        "ingest",
        "verify_draft",
    ]
    assert result["lineage"]["soulId"] == STACEY_SOUL_ID
    assert result["scheduleRequested"] is False
    assert result["publishRequested"] is False
    artifact_text = Path(result["artifactPath"]).read_text(encoding="utf-8")
    assert "secret" not in artifact_text
    assert json.loads(artifact_text)["hmacIngest"]["postIds"] == ["draft_post_1"]


def test_real_provider_acceptance_cancels_unused_reservation(
    tmp_path: Path,
) -> None:
    seams = FakeAcceptanceSeams(consume_ok=False)

    with pytest.raises(RuntimeError, match="failed to consume"):
        run_real_provider_acceptance(
            workspace=tmp_path,
            target_environment="preview",
            paid_confirmation=True,
            max_credits=1.0,
            seams=seams,
        )

    assert seams.calls[-1] == "cancel"
    assert "generate" not in seams.calls


def test_real_provider_acceptance_requires_explicit_paid_confirmation(
    tmp_path: Path,
) -> None:
    seams = FakeAcceptanceSeams()
    with pytest.raises(ValueError, match="paid confirmation"):
        run_real_provider_acceptance(
            workspace=tmp_path,
            target_environment="preview",
            paid_confirmation=False,
            max_credits=1.0,
            seams=seams,
        )
    assert seams.calls == []
