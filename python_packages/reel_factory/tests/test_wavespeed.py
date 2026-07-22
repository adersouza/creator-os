from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

import pytest
import requests
from creator_os_core.provider_spend import sign_authorization
from reel_factory.wavespeed import (
    AmbiguousWaveSpeedSubmission,
    WaveSpeedClient,
    WaveSpeedRequest,
    build_wavespeed_spend_scope,
    execute_wavespeed,
)

SECRET = "test-only " * 8


def _request(tmp_path: Path) -> WaveSpeedRequest:
    image = tmp_path / "source.jpg"
    image.write_bytes(b"source")
    return WaveSpeedRequest(
        model_id="wavespeed_wan27_i2v_pro",
        prompt="Natural breathing, a subtle head turn, and a slow camera push",
        output_path=tmp_path / "output.mp4",
        image_path=image,
        resolution="1080p",
        duration_seconds=5,
        seed=71,
        enable_prompt_expansion=True,
    )


def _authorization(scope: dict[str, object]) -> dict[str, object]:
    now = datetime.datetime.now(datetime.UTC)
    return sign_authorization(
        {
            "schema": "campaign_factory.provider_spend_authorization.v2",
            "authorizationId": "spauth_test",
            "reservationId": "spres_test",
            "issuer": "campaign_factory",
            "status": "authorized",
            "issuedAt": (now - datetime.timedelta(seconds=1)).isoformat(),
            "expiresAt": (now + datetime.timedelta(minutes=5)).isoformat(),
            "scope": scope,
            "providerQuote": {
                "provider": "wavespeed",
                "model": scope["providerModel"],
                "amount": 0.6,
                "unit": "USD",
                "pricingVersion": "test",
                "pricingFingerprint": "a" * 64,
                "catalogBasePrice": 0.6,
                "catalogModelId": scope["providerModel"],
                "liveQuotedAmount": 0.6,
                "livePriceSource": "wavespeed_model_pricing_api",
            },
        },
        secret=SECRET,
    )


class FakeClient:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.calls: list[str] = []

    def upload(self, path: Path) -> str:
        self.calls.append(f"upload:{path.name}")
        return f"https://media.example/{path.name}"

    def submit_once(self, _model, payload):
        self.calls.append("submit")
        assert payload["shot_type"] == "single"
        return {"id": "pred_123", "status": "created"}

    def poll(self, prediction_id: str, *, result_url=None, timeout_seconds=0):
        self.calls.append(f"poll:{prediction_id}")
        assert timeout_seconds == 60 * 30
        return {
            "id": prediction_id,
            "status": "completed",
            "outputs": ["https://outputs.example/signed.mp4?token=secret"],
        }

    def download(self, _url: str, destination: Path) -> str:
        self.calls.append("download")
        data = b"x" * 2048
        destination.write_bytes(data)
        return hashlib.sha256(data).hexdigest()


def test_authorization_is_verified_before_upload(tmp_path: Path) -> None:
    request = _request(tmp_path)
    scope = build_wavespeed_spend_scope(
        request, campaign="campaign", cohort_id="cohort"
    )
    client = FakeClient(request.output_path)
    authorization = _authorization(scope)
    authorization["signature"] = "0" * 64
    with pytest.raises(PermissionError, match="signature is invalid"):
        execute_wavespeed(
            request,
            campaign="campaign",
            cohort_id="cohort",
            authorization=authorization,
            secret=SECRET,
            evidence_dir=tmp_path / "evidence",
            client=client,
        )
    assert client.calls == []


def test_wavespeed_one_submit_retains_output_and_hides_signed_url(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    scope = build_wavespeed_spend_scope(
        request, campaign="campaign", cohort_id="cohort"
    )
    client = FakeClient(request.output_path)
    result = execute_wavespeed(
        request,
        campaign="campaign",
        cohort_id="cohort",
        authorization=_authorization(scope),
        secret=SECRET,
        evidence_dir=tmp_path / "evidence",
        client=client,
    )
    assert client.calls.count("submit") == 1
    assert request.output_path.is_file()
    evidence = Path(result["evidencePath"]).read_text(encoding="utf-8")
    assert "token=secret" not in evidence
    assert result["predictionId"] == "pred_123"


def test_submission_network_error_is_ambiguous_and_never_retried() -> None:
    class Session:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, *_args, **_kwargs):
            self.calls += 1
            raise requests.ConnectionError("socket closed")

    session = Session()
    client = WaveSpeedClient(api_key="test", session=session)
    with pytest.raises(AmbiguousWaveSpeedSubmission, match="do not retry POST"):
        client.submit_once(
            type("Model", (), {"provider_model": "model"})(), {"prompt": "test"}
        )
    assert session.calls == 1


def test_submission_5xx_is_ambiguous_and_never_retried() -> None:
    class Response:
        status_code = 503

    class Session:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, *_args, **_kwargs):
            self.calls += 1
            return Response()

    session = Session()
    client = WaveSpeedClient(api_key="test", session=session)
    with pytest.raises(AmbiguousWaveSpeedSubmission, match="do not retry POST"):
        client.submit_once(
            type("Model", (), {"provider_model": "model"})(), {"prompt": "test"}
        )
    assert session.calls == 1


def test_submission_malformed_2xx_is_ambiguous_and_never_retried() -> None:
    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            raise ValueError("truncated response")

    class Session:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, *_args, **_kwargs):
            self.calls += 1
            return Response()

    session = Session()
    client = WaveSpeedClient(api_key="test", session=session)
    with pytest.raises(AmbiguousWaveSpeedSubmission, match="do not retry POST"):
        client.submit_once(
            type("Model", (), {"provider_model": "model"})(), {"prompt": "test"}
        )
    assert session.calls == 1


def test_reference_model_requires_a_video_and_never_silently_changes_model(
    tmp_path: Path,
) -> None:
    image = tmp_path / "reference.jpg"
    image.write_bytes(b"reference")
    request = WaveSpeedRequest(
        model_id="wavespeed_wan27_reference",
        prompt="Video 1 turns naturally while image 2 preserves the exact identity",
        output_path=tmp_path / "out.mp4",
        reference_image_paths=(image,),
        resolution="1080p",
        duration_seconds=5,
        seed=42,
    )
    with pytest.raises(ValueError, match="requires a reference video"):
        build_wavespeed_spend_scope(request, campaign="campaign", cohort_id="cohort")


def test_duplicate_media_mapping_is_rejected(tmp_path: Path) -> None:
    video = tmp_path / "reference.mp4"
    video.write_bytes(b"video")
    request = WaveSpeedRequest(
        model_id="wavespeed_wan27_reference",
        prompt="Video 1 turns naturally while Video 2 preserves exact identity",
        output_path=tmp_path / "out.mp4",
        reference_video_paths=(video, video),
        resolution="1080p",
        duration_seconds=5,
        seed=42,
    )
    with pytest.raises(ValueError, match="duplicate media"):
        build_wavespeed_spend_scope(request, campaign="campaign", cohort_id="cohort")


def test_existing_output_blocks_before_any_provider_call(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request.output_path.write_bytes(b"existing")
    scope = build_wavespeed_spend_scope(
        request, campaign="campaign", cohort_id="cohort"
    )
    client = FakeClient(request.output_path)
    with pytest.raises(FileExistsError, match="output_collision"):
        execute_wavespeed(
            request,
            campaign="campaign",
            cohort_id="cohort",
            authorization=_authorization(scope),
            secret=SECRET,
            evidence_dir=tmp_path / "evidence",
            client=client,
        )
    assert client.calls == []


def test_poll_failure_preserves_prediction_identity_for_recovery(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    scope = build_wavespeed_spend_scope(
        request, campaign="campaign", cohort_id="cohort"
    )

    class PollFailureClient(FakeClient):
        def poll(self, prediction_id: str, *, result_url=None, timeout_seconds=0):
            self.calls.append(f"poll:{prediction_id}")
            raise TimeoutError("provider still processing")

    client = PollFailureClient(request.output_path)
    with pytest.raises(TimeoutError):
        execute_wavespeed(
            request,
            campaign="campaign",
            cohort_id="cohort",
            authorization=_authorization(scope),
            secret=SECRET,
            evidence_dir=tmp_path / "evidence",
            client=client,
        )
    evidence = list((tmp_path / "evidence").glob("*.wavespeed_submission.json"))
    assert len(evidence) == 1
    payload = json.loads(evidence[0].read_text(encoding="utf-8"))
    assert payload["predictionId"] == "pred_123"
    assert payload["status"] == "poll_timeout"
