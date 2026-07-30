from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from campaign_factory.adapters import threadsdash_owner_api
from campaign_factory.adapters.threadsdash_handoff_evidence import (
    shared_handoff_payload,
)


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
            "drafts": [{"debugPath": "/Users/operator/private.mp4"}],
        }
    )
    assert "_localFilePath" not in shared
    assert shared["drafts"][0]["debugPath"] == "private.mp4"


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
