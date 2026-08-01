from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from campaign_factory.adapters import threadsdash_owner_api
from campaign_factory.adapters.threadsdash_handoff_evidence import (
    media_preparation_evidence,
    shared_handoff_payload,
)

from pipeline_contracts import load_example


class _UploadResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return b""


def test_shared_handoff_removes_private_fields_and_absolute_paths() -> None:
    shared = shared_handoff_payload(
        {
            "_localFilePath": "/Users/operator/private.mp4",
            "drafts": [
                {
                    "debugPath": "/Users/operator/private.mp4",
                    "requiredNullableField": None,
                }
            ],
        }
    )
    assert "_localFilePath" not in shared
    assert shared["drafts"][0]["debugPath"] == "private.mp4"
    assert shared["drafts"][0]["requiredNullableField"] is None


def test_media_preparation_binds_allowed_profile_to_exact_final_bytes(
    tmp_path: Path,
) -> None:
    receipt = load_example("visual_derivative_receipt")
    receipt["profile"].update({"id": "tilt_crop_dark", "observedSource": "spoofzy"})
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    final_sha = receipt["accepted"][0]["output"]["sha256"]
    asset = {
        "_metadata": {
            "observedProfile": "tilt_crop_dark@1",
            "visualDerivativeReceipt": {
                "path": str(receipt_path),
                "sha256": receipt_sha,
                "toolchainFingerprint": receipt["toolchain"]["fingerprint"],
                "sourceSha256": receipt["source"]["sha256"],
                "outputSha256": final_sha,
                "acceptedIndex": 1,
            },
        }
    }

    evidence = media_preparation_evidence(asset, final_sha256=final_sha)

    assert evidence["observedSource"] == "spoofzy"
    assert evidence["outputSha256"] == final_sha
    asset["_metadata"]["captionRenderReceipt"] = {
        "replacesSha256": final_sha,
        "outputSha256": "5" * 64,
    }
    asset["_metadata"]["audioEmbeddingReceipt"] = {
        "schema": "creator_os.audio_embedding_receipt.v1",
        "originalVideo": {"sha256": "5" * 64},
        "finalVideo": {"sha256": "6" * 64},
        "verification": {"status": "verified"},
    }
    chained = media_preparation_evidence(asset, final_sha256="6" * 64)
    assert [item["type"] for item in chained["postProcessChain"]] == [
        "caption_render",
        "audio_embedding",
    ]
    with pytest.raises(ValueError, match="not bound"):
        media_preparation_evidence(asset, final_sha256="0" * 64)


def test_delivery_media_uses_owner_ticket_and_exact_approved_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"approved-video")
    sha = hashlib.sha256(media.read_bytes()).hexdigest()
    uploaded: dict[str, object] = {}
    monkeypatch.setenv("THREADSDASH_ALLOWED_INGEST_HOSTS", "dashboard.example.com")
    monkeypatch.setattr(
        threadsdash_owner_api,
        "_signed_json_request",
        lambda **_kwargs: {
            "uploadTicketId": "ticket_1",
            "signedUrl": "https://storage.example.com/signed",
            "publicUrl": "https://cdn.example.com/clip.mp4",
            "storagePath": f"campaign-factory/user_1/{sha}-clip.mp4",
            "bucket": "media",
        },
    )

    def upload(request, timeout):
        uploaded["body"] = request.data
        uploaded["timeout"] = timeout
        return _UploadResponse()

    monkeypatch.setattr(
        threadsdash_owner_api.threadsdash_client,
        "_open_threadsdash_ingest_request",
        upload,
    )
    payload = {
        "drafts": [
            {
                "userId": "user_1",
                "campaignFactoryExportId": "tdexp_1",
                "campaignFactoryMediaKey": "media_key_1",
                "contentHash": sha,
                "_localFilePath": str(media),
                "media": [{}],
            }
        ]
    }

    result = threadsdash_owner_api.upload_delivery_media(
        payload,
        ingest_url="https://dashboard.example.com/api/campaign-factory/drafts/ingest",
        ingest_secret="secret",
        bucket="media",
    )

    assert uploaded["body"] == b"approved-video"
    assert result[0]["sha256"] == sha
    assert payload["drafts"][0]["deliveryMedia"]["uploadTicketId"] == "ticket_1"


def test_delivery_media_rejects_changed_bytes_before_owner_api(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"changed")
    monkeypatch.setattr(
        threadsdash_owner_api,
        "_signed_json_request",
        lambda **_kwargs: pytest.fail("owner API must not receive changed bytes"),
    )

    with pytest.raises(ValueError, match="changed after creative approval"):
        threadsdash_owner_api.upload_delivery_media(
            {
                "drafts": [
                    {
                        "userId": "user_1",
                        "campaignFactoryExportId": "tdexp_1",
                        "campaignFactoryMediaKey": "media_key_1",
                        "contentHash": "0" * 64,
                        "_localFilePath": str(media),
                    }
                ]
            },
            ingest_url="https://juno33.com/api/campaign-factory/drafts/ingest",
            ingest_secret="secret",
            bucket="media",
        )


def test_reddit_library_snapshot_uses_signed_owner_api(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        threadsdash_owner_api,
        "_signed_json_request",
        lambda **kwargs: (
            captured.update(kwargs)
            or {
                "schema": "threadsdashboard.reddit_library_state.v1",
                "accounts": [],
                "subreddits": [],
                "tasks": [],
                "contentOwners": [],
            }
        ),
    )
    monkeypatch.setenv("THREADSDASH_ALLOWED_INGEST_HOSTS", "dashboard.example.com")

    result = threadsdash_owner_api.fetch_reddit_library_snapshot(
        user_id="user_1",
        ingest_url="https://dashboard.example.com/api/campaign-factory/drafts/ingest",
        ingest_secret="secret",
    )

    assert captured["body"] == {
        "operation": "library_snapshot",
        "userId": "user_1",
    }
    assert str(captured["url"]).endswith("/api/campaign-factory/reddit/handoff")
    assert result["schema"] == "threadsdashboard.reddit_library_state.v1"
