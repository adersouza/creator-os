from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from reel_factory.ai_visual_qc import record_from_scores
from reel_factory.generate_assets import (
    download_result,
    generated_image_qc,
    generated_image_qc_failure_reason,
    generated_video_qc,
    generated_video_qc_failure_reason,
)
from reel_factory.hook_ai import hook_similarity_mode
from reel_factory.identity_verification import (
    build_reference_set,
    delete_reference_set,
    identity_health,
    identity_model_root,
    identity_qc_receipt,
    verify_identity,
)
from reel_factory.local_model_benchmark import _validate_identity_receipt
from reel_factory.media_metadata import normalize_media_metadata


@pytest.fixture(autouse=True)
def _evidence_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", "i" * 64)


class FakeIdentityProvider:
    name = "fake_identity"

    def __init__(self, embedding: list[float] | None = None, available: bool = True):
        self._embedding = embedding or [1.0, 0.0]
        self._available = available

    def available(self) -> tuple[bool, str]:
        return (True, "ok") if self._available else (False, "fake_unavailable")

    def embedding(self, image_path: Path) -> list[float] | None:
        return self._embedding


class PathIdentityProvider(FakeIdentityProvider):
    def __init__(self, embeddings_by_name: dict[str, list[float]]):
        super().__init__([1.0, 0.0])
        self._embeddings_by_name = embeddings_by_name

    def embedding(self, image_path: Path) -> list[float] | None:
        return self._embeddings_by_name.get(image_path.name, [1.0, 0.0])


class FakeDownloadResponse:
    def __init__(self, chunks: list[bytes], content_type: str = "image/png"):
        self._chunks = list(chunks)
        self.headers = self
        self._content_type = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get_content_type(self) -> str:
        return self._content_type

    def read(self, _size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def _identity_profile(
    creator: str, reference_paths: list[Path] | tuple[Path, ...]
) -> dict[str, object]:
    profile: dict[str, object] = {
        "schema": "creator_os.creator_identity_profile.v1",
        "profileId": f"identity-{creator.lower()}",
        "creatorKey": creator.lower(),
        "displayName": creator,
        "modelProfile": f"{creator.lower()}-model",
        "identityReferences": [
            {
                "namespace": "test",
                "externalId": path.name,
                "fingerprint": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in reference_paths
        ],
        "provenance": {
            "producer": "test.identity_fixture",
            "producedAt": "2026-01-01T00:00:00+00:00",
            "sourceReferences": [
                {"recordId": "reviewed-facts", "fingerprint": "c" * 64}
            ],
        },
    }
    return profile


def _profile_fingerprint(profile: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            profile,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_reference_set(
    root: Path, creator: str, embeddings: list[list[float]]
) -> tuple[dict[str, object], str]:
    available_images = [
        path
        for path in sorted(root.rglob("*"))
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        and "identity_references" not in path.parts
    ]
    if len(available_images) < 2:
        extra = root / "identity_reference_fixture_2.png"
        _write_image(extra)
        available_images.append(extra)
    profile = _identity_profile(creator, available_images)
    built = build_reference_set(
        creator=creator,
        input_dir=root,
        root=root,
        provider=FakeIdentityProvider(embeddings[0]),
        creator_identity_profile=profile,
    )
    assert built["status"] == "ready"
    profile_fingerprint = _profile_fingerprint(profile)
    return profile, profile_fingerprint


def _write_image(path: Path) -> None:
    marker = hashlib.sha256(path.name.encode("utf-8")).digest()
    Image.new("RGB", (24, 24), (marker[0], marker[1], marker[2])).save(path)


def test_identity_model_root_reuses_standard_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root = tmp_path / "package"
    home = tmp_path / "home"
    standard = home / ".insightface" / "models" / "buffalo_l"
    standard.mkdir(parents=True)
    (standard / "w600k_r50.onnx").write_bytes(b"model")
    monkeypatch.setattr(
        "reel_factory.identity_verification.PACKAGE_IDENTITY_MODEL_ROOT", package_root
    )
    monkeypatch.setattr(Path, "home", lambda: home)

    assert identity_model_root() == home / ".insightface"


def test_identity_model_root_prefers_explicit_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured"
    model_dir = configured / "models" / "buffalo_l"
    model_dir.mkdir(parents=True)
    (model_dir / "det_10g.onnx").write_bytes(b"model")
    monkeypatch.setenv("REEL_FACTORY_IDENTITY_MODEL_ROOT", str(configured))

    assert identity_model_root() == configured


def test_download_result_rejects_truncated_response_without_partial_file(
    tmp_path: Path, monkeypatch
) -> None:
    import reel_factory.generate_assets as generate_assets

    monkeypatch.setattr(
        generate_assets.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeDownloadResponse([b"tiny"], "image/png"),
    )

    out = tmp_path / "asset.png"
    try:
        download_result("https://example.test/asset.png", out)
    except RuntimeError as exc:
        assert "downloaded result too small" in str(exc)
    else:
        raise AssertionError("truncated download was accepted")

    assert not out.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_download_result_timeout_leaves_no_asset_file(
    tmp_path: Path, monkeypatch
) -> None:
    import reel_factory.generate_assets as generate_assets

    def timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(generate_assets.urllib.request, "urlopen", timeout)

    out = tmp_path / "asset.mp4"
    try:
        download_result("https://example.test/asset.mp4", out)
    except TimeoutError:
        pass
    else:
        raise AssertionError("timeout was accepted")

    assert not out.exists()


def test_identity_verification_pass_fail_and_unavailable(tmp_path: Path) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    profile, profile_fingerprint = _write_reference_set(
        tmp_path, "Stacey", [[1.0, 0.0]]
    )

    passed = verify_identity(
        image,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider([1.0, 0.0]),
        creator_identity_profile=profile,
        identity_profile_id=str(profile["profileId"]),
        identity_profile_fingerprint=profile_fingerprint,
    )
    failed = verify_identity(
        image,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider([0.0, 1.0]),
        identity_profile_id=str(profile["profileId"]),
        identity_profile_fingerprint=profile_fingerprint,
    )
    unavailable = verify_identity(
        image,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider(available=False),
    )

    assert passed["status"] == "passed"
    assert failed["status"] == "failed"
    assert failed["failureReason"] == "identity_similarity_below_threshold"
    assert unavailable["status"] == "unavailable"
    assert unavailable["failureReason"] == "fake_unavailable"
    assert unavailable["score"] is None
    assert passed["frameCount"] == 1
    assert passed["subjectSha256"]
    assert passed["referenceSetFingerprint"]
    assert passed["analyzer"]["analyzerId"] == "reel_factory.identity_preservation"
    assert passed["analyzer"]["analyzerVersion"] == "2.0.0"
    assert passed["observations"]["frames"][0]["frameSha256"]
    receipt = identity_qc_receipt(passed)
    assert receipt["passed"] is True
    assert receipt["subjectSha256"] == passed["subjectSha256"]
    assert receipt["producerAttestation"]["issuer"] == (
        "reel_factory.identity_verification"
    )
    assert receipt["producerAttestation"]["issuedAt"] == passed["observedAt"]
    _validate_identity_receipt(receipt, expected_subject_sha256=passed["subjectSha256"])
    forged_receipt = dict(receipt)
    forged_receipt["passed"] = False
    with pytest.raises(RuntimeError, match="identity_attestation_invalid"):
        _validate_identity_receipt(
            forged_receipt, expected_subject_sha256=passed["subjectSha256"]
        )
    blocked = identity_qc_receipt(failed)
    assert blocked["passed"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema", "reel_factory.identity_reference_set.v0"),
        ("creator", "Larissa"),
    ),
)
def test_identity_rejects_edited_reference_set_identity(
    tmp_path: Path, field: str, value: str
) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])
    reference = tmp_path / "identity_references/stacey.json"
    payload = json.loads(reference.read_text())
    payload[field] = value
    reference.write_text(json.dumps(payload))

    result = verify_identity(
        image,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider(),
    )
    assert result["status"] == "unavailable"
    assert result["failureReason"] == "reference_set_schema_or_creator_mismatch"


def test_identity_rejects_same_size_substituted_reference_source(
    tmp_path: Path,
) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])
    original = image.read_bytes()
    image.write_bytes(bytes([original[0] ^ 1]) + original[1:])

    result = verify_identity(
        image,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider(),
    )
    assert result["status"] == "unavailable"
    assert result["failureReason"] == "reference_set_source_substituted"


def test_video_identity_uses_worst_sampled_frame(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    early = tmp_path / "early.png"
    late = tmp_path / "late.png"
    _write_image(early)
    _write_image(late)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])

    result = verify_identity(
        video,
        creator="Stacey",
        root=tmp_path,
        provider=PathIdentityProvider(
            {"early.png": [1.0, 0.0], "late.png": [0.0, 1.0]}
        ),
        frame_extractor=lambda _path: [early, late],
    )

    assert result["status"] == "failed"
    assert result["score"] == 0.0
    assert result["frameScores"] == [1.0, 0.0]


def test_default_video_identity_sampling_covers_full_duration_with_twenty_one_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reel_factory.identity_verification as identity_module

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    timestamps: list[float] = []
    monkeypatch.setattr(identity_module, "_probe_duration", lambda _path: 10.0)
    monkeypatch.setattr(
        identity_module.shutil, "which", lambda _name: "/usr/bin/ffmpeg"
    )

    def fake_run(command, **_kwargs):
        timestamps.append(float(command[command.index("-ss") + 1]))
        Path(command[-1]).write_bytes(b"frame")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(identity_module.subprocess, "run", fake_run)

    frames = identity_module._media_frames_for_embedding(video)

    assert len(frames) == 21
    assert timestamps[0] == pytest.approx(0.2)
    assert timestamps[-1] == pytest.approx(9.8)
    assert timestamps == sorted(timestamps)


def test_video_identity_passes_when_all_sampled_frames_match(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    early = tmp_path / "early.png"
    late = tmp_path / "late.png"
    _write_image(early)
    _write_image(late)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])

    result = verify_identity(
        video,
        creator="Stacey",
        root=tmp_path,
        provider=PathIdentityProvider(
            {"early.png": [1.0, 0.0], "late.png": [0.9, 0.1]}
        ),
        frame_extractor=lambda _path: [early, late],
    )

    assert result["status"] == "passed"
    assert result["score"] == 0.9
    assert result["frameCount"] == 2
    assert result["faceStabilityScore"] == 0.9


def test_video_identity_rejects_multiple_faces(tmp_path: Path) -> None:
    class MultipleFaceProvider(FakeIdentityProvider):
        def face_embeddings(self, _image_path: Path) -> list[list[float]]:
            return [[1.0, 0.0], [0.9, 0.1]]

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    frame = tmp_path / "frame.png"
    _write_image(frame)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])

    result = verify_identity(
        video,
        creator="Stacey",
        root=tmp_path,
        provider=MultipleFaceProvider(),
        frame_extractor=lambda _path: [frame],
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "multiple_faces_detected"
    assert result["score"] is None
    assert result["observations"]["frames"][0]["facesDetected"] == 2


def test_video_identity_cleans_owned_temporary_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reel_factory.identity_verification as identity_module

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    generated_root = tmp_path / "identity_verify_owned"
    generated_root.mkdir()
    frame = generated_root / "frame_0.jpg"
    _write_image(frame)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])
    monkeypatch.setattr(
        identity_module, "_media_frames_for_embedding", lambda _path: [frame]
    )
    monkeypatch.setattr(identity_module, "_probe_duration", lambda _path: 6.0)

    result = verify_identity(
        video,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider([1.0, 0.0]),
    )

    assert result["status"] == "passed"
    assert not generated_root.exists()


def test_identity_reference_build_and_health_use_provider_seam(tmp_path: Path) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")
    _write_image(input_dir / "ref_b.png")

    built = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        provider=FakeIdentityProvider([1.0, 0.0]),
        creator_identity_profile=_identity_profile(
            "Stacey", tuple(sorted(input_dir.iterdir()))
        ),
    )
    health = identity_health(
        creator="Stacey", root=tmp_path, provider=FakeIdentityProvider([1.0, 0.0])
    )

    assert built["schema"] == "reel_factory.identity_reference_set.v4"
    assert built["status"] == "ready"
    assert len(built["embeddings"]) == 2
    assert all(item["status"] == "embedded" for item in built["sourceImages"])
    assert health["status"] == "ready"
    assert health["referenceEmbeddings"] == 2


def test_identity_reference_build_rejects_output_outside_reference_root(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")

    result = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        output=tmp_path / "tracked.json",
        provider=FakeIdentityProvider(),
        creator_identity_profile=_identity_profile(
            "Stacey", tuple(sorted(input_dir.iterdir()))
        ),
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "output_must_be_under_identity_references"
    assert not (tmp_path / "tracked.json").exists()


def test_identity_reference_build_writes_private_file_and_delete_removes_it(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")
    _write_image(input_dir / "ref_b.png")

    result = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        provider=FakeIdentityProvider(),
        creator_identity_profile=_identity_profile(
            "Stacey", tuple(sorted(input_dir.iterdir()))
        ),
    )
    target = Path(result["outputPath"])

    assert result["status"] == "ready"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    deleted = delete_reference_set(creator="Stacey", root=tmp_path)
    assert deleted["deleted"] is True
    assert not target.exists()


def test_identity_reference_cli_redacts_embeddings_by_default(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    import reel_factory.identity_verification as identity_verification

    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")
    _write_image(input_dir / "ref_b.png")
    profile_path = tmp_path / "profile.json"
    profile = _identity_profile("Stacey", tuple(sorted(input_dir.iterdir())))
    profile_path.write_text(json.dumps(profile))
    monkeypatch.setattr(
        identity_verification,
        "get_identity_provider",
        lambda: FakeIdentityProvider(),
    )

    exit_code = identity_verification.main(
        [
            "identity-reference-build",
            "--creator",
            "Stacey",
            "--input-dir",
            str(input_dir),
            "--root",
            str(tmp_path),
            "--identity-profile",
            str(profile_path),
            "--identity-profile-fingerprint",
            _profile_fingerprint(profile),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"referenceSetId"' in output
    assert '"embeddings"' not in output


def test_identity_reference_build_fails_closed_when_provider_missing(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")

    result = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        provider=FakeIdentityProvider(available=False),
        creator_identity_profile=_identity_profile(
            "Stacey", tuple(sorted(input_dir.iterdir()))
        ),
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "fake_unavailable"
    assert not (tmp_path / "identity_references" / "stacey.json").exists()


def test_identity_reference_build_rejects_any_source_with_multiple_faces(
    tmp_path: Path,
) -> None:
    class MultipleFaceReferenceProvider(FakeIdentityProvider):
        def face_embeddings(self, image_path: Path) -> list[list[float]]:
            if image_path.name == "bad.png":
                return [[1.0, 0.0], [0.9, 0.1]]
            return [[1.0, 0.0]]

    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    for name in ("good_a.png", "good_b.png", "bad.png"):
        _write_image(input_dir / name)

    result = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        provider=MultipleFaceReferenceProvider(),
        creator_identity_profile=_identity_profile(
            "Stacey", tuple(sorted(input_dir.iterdir()))
        ),
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "reference_source_face_count_invalid"
    bad = next(
        item for item in result["sourceImages"] if item["path"].endswith("bad.png")
    )
    assert bad["faceCount"] == 2
    assert bad["failureReason"] == "multiple_faces_detected"
    assert not (tmp_path / "identity_references/stacey.json").exists()


def test_identity_reference_build_excludes_embedding_outlier_with_evidence(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    for name in ("good_a.png", "good_b.png", "outlier.png"):
        _write_image(input_dir / name)
    provider = PathIdentityProvider(
        {
            "good_a.png": [1.0, 0.0],
            "good_b.png": [0.98, 0.02],
            "outlier.png": [0.0, 1.0],
        }
    )

    result = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        provider=provider,
        creator_identity_profile=_identity_profile(
            "Stacey", tuple(sorted(input_dir.iterdir()))
        ),
    )

    assert result["status"] == "ready"
    assert result["acceptedSourceCount"] == 2
    assert result["rejectedSourceCount"] == 1
    outlier = next(
        item for item in result["sourceImages"] if item["path"].endswith("outlier.png")
    )
    assert outlier["status"] == "rejected"
    assert outlier["failureReason"] == "identity_embedding_outlier"
    assert outlier["consensusScore"] < 0.35
    assert len(result["embeddings"]) == 2


def test_generated_image_qc_gates_identity_with_injected_provider(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])
    monkeypatch.setattr(
        "reel_factory.generate_assets.assess_image_qc",
        lambda *args, **kwargs: {
            "available": True,
            "anatomy": {"plausible": True, "severity": "none", "defects": []},
            "exposure": {"safe": True, "severity": "none", "issues": []},
        },
    )

    passed = generated_image_qc(
        {"image": str(image)},
        root=tmp_path,
        required=True,
        creator="Stacey",
        identity_provider=FakeIdentityProvider([1.0, 0.0]),
    )
    failed = generated_image_qc(
        {"image": str(image)},
        root=tmp_path,
        required=True,
        creator="Stacey",
        identity_provider=FakeIdentityProvider([0.0, 1.0]),
    )

    assert passed["status"] == "passed"
    assert passed["results"][0]["identityVerification"]["status"] == "passed"
    assert failed["status"] == "failed"
    assert failed["results"][0]["postable"] is False
    assert (
        failed["results"][0]["identityVerification"]["failureReason"]
        == "identity_similarity_below_threshold"
    )


def test_generated_image_qc_names_identity_reference_seeding_remedy(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    monkeypatch.setattr(
        "reel_factory.generate_assets.assess_image_qc",
        lambda *args, **kwargs: {
            "available": True,
            "anatomy": {"plausible": True, "severity": "none", "defects": []},
            "exposure": {"safe": True, "severity": "none", "issues": []},
        },
    )

    result = generated_image_qc(
        {"image": str(image)},
        root=tmp_path,
        required=True,
        creator="Stacey",
        identity_provider=FakeIdentityProvider([1.0, 0.0]),
    )

    failure = result["results"][0]["identityVerification"]["failureReason"]
    assert result["status"] == "failed"
    assert (
        failure == "no identity reference set for Stacey - run identity-reference-build"
    )
    assert generated_image_qc_failure_reason(result) == (
        "generated image failed identity QC: "
        "no identity reference set for Stacey - run identity-reference-build"
    )


def test_generated_video_qc_passes_clean_sampled_frames(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    frame = tmp_path / "frame_ok.png"
    _write_image(frame)

    result = generated_video_qc(
        {"video": str(video)},
        root=tmp_path,
        required=True,
        frame_sampler=lambda _path: [frame],
        vision_call=lambda _frames, _prompt: json.dumps(
            {
                "anatomy": {"plausible": True, "severity": "none", "defects": []},
                "exposure": {"safe": True, "severity": "none", "issues": []},
            }
        ),
    )

    assert result["status"] == "passed"
    assert result["results"][0]["frames"][0]["postable"] is True


def test_generated_video_qc_rejects_bad_sampled_frame(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    frame = tmp_path / "frame_bad.png"
    _write_image(frame)

    result = generated_video_qc(
        {"video": str(video)},
        root=tmp_path,
        required=True,
        frame_sampler=lambda _path: [frame],
        vision_call=lambda _frames, _prompt: json.dumps(
            {
                "anatomy": {
                    "plausible": False,
                    "severity": "severe",
                    "defects": ["warped hand"],
                },
                "exposure": {"safe": True, "severity": "none", "issues": []},
            }
        ),
    )

    assert result["status"] == "failed"
    assert "warped hand" in generated_video_qc_failure_reason(result)


def test_generated_video_qc_fails_closed_when_provider_unavailable(
    tmp_path: Path,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    frame = tmp_path / "frame_unknown.png"
    _write_image(frame)

    def unavailable(_frames, _prompt):
        raise RuntimeError("provider missing")

    result = generated_video_qc(
        {"video": str(video)},
        root=tmp_path,
        required=True,
        frame_sampler=lambda _path: [frame],
        vision_call=unavailable,
    )

    assert result["status"] == "failed"
    assert result["results"][0]["frames"][0]["available"] is False


def test_ai_visual_qc_status_marks_dependency_unavailable() -> None:
    record = record_from_scores("x.mp4", "/tmp/x.mp4", {"opencv_available": 0})

    assert record.visualQcStatus == "unavailable"
    assert record.visualQcDependencyStatus["opencv"] == "unavailable"
    assert "opencv_unavailable" in record.visualQcWarnings


def test_hook_similarity_hash_mode_is_named_lexical_fallback() -> None:
    assert hook_similarity_mode("hash-v1") == "lexical_fallback_similarity"


class FakeBalanceProvider:
    name = "fake_balance"

    def __init__(self, balance: float | None, reason: str | None = None):
        self._balance = balance
        self._reason = reason

    def balance(self) -> tuple[float | None, str | None]:
        return self._balance, self._reason


def test_metadata_normalization_reports_missing_exiftool_without_spoofing(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake media")
    monkeypatch.setattr("reel_factory.media_metadata.shutil.which", lambda name: None)

    result = normalize_media_metadata(media, dry_run=False)

    assert result["metadataNormalized"] is False
    assert "exiftool_unavailable" in result["metadataWarnings"]
    assert result["spoofedDeviceMetadata"] is False
    assert result["spoofedPlatformMetadata"] is False


def test_metadata_normalization_strips_mp4_metadata_tags(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake media")
    calls: list[list[str]] = []

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Proc()

    monkeypatch.setattr(
        "reel_factory.media_metadata.shutil.which", lambda name: "/usr/bin/exiftool"
    )
    monkeypatch.setattr("reel_factory.media_metadata.subprocess.run", fake_run)

    result = normalize_media_metadata(media, dry_run=False)

    assert result["metadataNormalized"] is True
    assert calls
    assert "-all=" in calls[0]
    assert str(media.resolve()) == calls[0][-1]
