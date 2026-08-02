from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess

from campaign_factory import asset_evidence
from campaign_factory.adapters.contentforge import (
    _contentforge_analyzer_evidence,
    _tool_version,
)


def test_final_artifact_integrity_binds_decode_geometry_caption_and_audio(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "final.mp4"
    media.write_bytes(b"final-media")
    final_sha = hashlib.sha256(media.read_bytes()).hexdigest()
    intent = {
        "mode": "embedded_trending_audio",
        "fulfillment": {
            "proof_type": "embedded_output_audio_stream",
            "audio_present": True,
            "output_sha256": final_sha,
        },
        "lineage": {
            "finalMediaSha256": final_sha,
            "embeddingReceiptSha256": "e" * 64,
        },
    }
    asset = {
        "output_path": str(media),
        "content_hash": final_sha,
        "target_ratio": "9:16",
        "metadata_json": json.dumps({"staticMp4Render": {"durationSeconds": 5.0}}),
        "caption_outcome_context_json": json.dumps(
            {
                "captionBurnedIn": True,
                "captionPlacementDecision": {"status": "passed"},
            }
        ),
        "caption_generation_json": json.dumps({"audioIntent": intent}),
    }
    monkeypatch.setattr(asset_evidence.shutil, "which", lambda tool: f"/{tool}")

    def run(command, **_kwargs):
        if command[0] == "/ffprobe":
            return CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "format": {"duration": "5.0"},
                        "streams": [
                            {
                                "codec_type": "video",
                                "codec_name": "h264",
                                "width": 1080,
                                "height": 1920,
                            },
                            {"codec_type": "audio", "codec_name": "aac"},
                        ],
                    }
                ),
                stderr="",
            )
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(asset_evidence.subprocess, "run", run)

    receipt = asset_evidence.verify_final_artifact_integrity(asset)

    assert receipt["passed"] is True
    assert receipt["subjectSha256"] == final_sha
    assert receipt["decode"]["passed"] is True
    assert receipt["probe"]["targetRatioMatches"] is True
    assert receipt["captionBinding"]["passed"] is True
    assert receipt["audioBinding"]["passed"] is True


def test_final_artifact_integrity_rejects_audio_receipt_for_other_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "final.mp4"
    media.write_bytes(b"final-media")
    final_sha = hashlib.sha256(media.read_bytes()).hexdigest()
    monkeypatch.setattr(asset_evidence.shutil, "which", lambda tool: f"/{tool}")
    monkeypatch.setattr(
        asset_evidence.subprocess,
        "run",
        lambda command, **_kwargs: CompletedProcess(
            command,
            0,
            stdout=(
                json.dumps(
                    {
                        "format": {"duration": "1"},
                        "streams": [
                            {
                                "codec_type": "video",
                                "codec_name": "h264",
                                "width": 1080,
                                "height": 1920,
                            },
                            {"codec_type": "audio", "codec_name": "aac"},
                        ],
                    }
                )
                if command[0] == "/ffprobe"
                else ""
            ),
            stderr="",
        ),
    )
    receipt = asset_evidence.verify_final_artifact_integrity(
        {
            "output_path": str(media),
            "content_hash": final_sha,
            "caption_generation_json": json.dumps(
                {
                    "audioIntent": {
                        "mode": "embedded_trending_audio",
                        "fulfillment": {
                            "proof_type": "embedded_output_audio_stream",
                            "audio_present": True,
                            "output_sha256": "0" * 64,
                        },
                        "lineage": {
                            "finalMediaSha256": "0" * 64,
                            "embeddingReceiptSha256": "e" * 64,
                        },
                    }
                }
            ),
        }
    )

    assert receipt["passed"] is False
    assert "audio_receipt_final_sha_mismatch" in receipt["failures"]


def test_contentforge_analyzer_evidence_fingerprints_implementation(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "package.json").write_text(
        '{"name":"contentforge","version":"1.2.3"}', encoding="utf-8"
    )
    (tmp_path / "cli.mjs").write_text("export {};", encoding="utf-8")
    (tmp_path / "lib" / "similarity.js").write_text(
        "export const audit = true;", encoding="utf-8"
    )
    monkeypatch.setattr(
        "campaign_factory.adapters.contentforge._tool_version",
        lambda tool: f"{tool}-test",
    )

    evidence = _contentforge_analyzer_evidence(
        tmp_path,
        layers=["forensics", "pdq"],
        response={"auditProfile": "campaign_factory_v1"},
    )

    assert evidence["analyzerVersion"] == "1.2.3"
    assert len(evidence["implementationFingerprint"]) == 64
    assert evidence["implementationComponents"]["lib/similarity.js"]


def test_contentforge_tool_version_uses_ffmpeg_version_flag(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "campaign_factory.adapters.contentforge.shutil.which",
        lambda tool: f"/bin/{tool}",
    )

    def run(command: list[str], **_kwargs):
        calls.append(command)
        return type(
            "Result", (), {"returncode": 0, "stdout": "version 1\n", "stderr": ""}
        )()

    monkeypatch.setattr("campaign_factory.adapters.contentforge.subprocess.run", run)

    assert _tool_version("ffmpeg") == "version 1"
    assert _tool_version("ffprobe") == "version 1"
    assert _tool_version("node") == "version 1"
    assert calls == [
        ["/bin/ffmpeg", "-version"],
        ["/bin/ffprobe", "-version"],
        ["/bin/node", "--version"],
    ]
