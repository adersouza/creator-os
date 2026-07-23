from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from reel_factory.identity_verification import (
    build_reference_set,
    identity_health,
    identity_qc_receipt,
    main,
    verify_identity,
)


@pytest.fixture(autouse=True)
def _evidence_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", "v" * 64)


def _profile(
    creator: str = "stacey",
    *,
    profile_id: str | None = None,
    reference_paths: tuple[Path, ...] = (),
    extra_references: tuple[dict, ...] = (),
) -> dict:
    return {
        "schema": "creator_os.creator_identity_profile.v1",
        "profileId": profile_id or f"profile-{creator}",
        "creatorKey": creator,
        "displayName": creator.title(),
        "modelProfile": f"{creator}-model",
        "identityReferences": [
            *[
                {
                    "namespace": "reviewed-reference",
                    "externalId": path.name,
                    "fingerprint": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in reference_paths
            ],
            *extra_references,
        ]
        or [
            {
                "namespace": "reviewed-reference",
                "externalId": f"{creator}-reference-set",
                "fingerprint": "a" * 64,
            }
        ],
        "provenance": {
            "producer": "test.identity_verification",
            "producedAt": "2026-01-01T00:00:00+00:00",
            "sourceReferences": [
                {"recordId": "reviewed-facts", "fingerprint": "b" * 64}
            ],
        },
    }


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _image(path: Path) -> None:
    marker = sum(path.name.encode("utf-8")) % 255
    Image.new("RGB", (32, 32), (marker, (marker + 31) % 255, 99)).save(path)


class FaceProvider:
    name = "test_arcface"

    def __init__(
        self,
        by_name: dict[str, list[list[float]]] | None = None,
    ) -> None:
        self.by_name = by_name or {}

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def face_embeddings(self, image_path: Path) -> list[list[float]]:
        return self.by_name.get(image_path.name, [[1.0, 0.0]])

    def embedding(self, image_path: Path) -> list[float] | None:
        faces = self.face_embeddings(image_path)
        return faces[0] if faces else None


class UnavailableProvider(FaceProvider):
    name = "unavailable"

    def available(self) -> tuple[bool, str]:
        return False, "identity_provider_unavailable:ModuleNotFoundError"


def _build(
    tmp_path: Path,
    *,
    provider: FaceProvider | None = None,
    profile: dict | None = None,
) -> tuple[dict, Path, FaceProvider]:
    source_dir = tmp_path / "reviewed"
    source_dir.mkdir()
    _image(source_dir / "ref_a.png")
    _image(source_dir / "ref_b.png")
    exact_provider = provider or FaceProvider()
    source_paths = tuple(sorted(source_dir.iterdir()))
    result = build_reference_set(
        creator="stacey",
        input_dir=source_dir,
        root=tmp_path,
        provider=exact_provider,
        creator_identity_profile=profile or _profile(reference_paths=source_paths),
    )
    return result, tmp_path / "identity_references/stacey.json", exact_provider


@pytest.mark.parametrize(
    ("faces", "reason"),
    (
        ([], "face_embedding_missing"),
        ([[1.0, 0.0], [0.0, 1.0]], "multiple_faces_detected"),
    ),
)
def test_reference_build_requires_exactly_one_usable_face_per_source(
    tmp_path: Path, faces: list[list[float]], reason: str
) -> None:
    provider = FaceProvider({"ref_b.png": faces})

    result, reference_path, _ = _build(tmp_path, provider=provider)

    assert result["status"] == "failed"
    assert result["failureReason"] == "reference_source_face_count_invalid"
    failed = next(
        item for item in result["sourceImages"] if item["path"].endswith("ref_b.png")
    )
    assert failed["failureReason"] == reason
    assert not reference_path.exists()


def test_reference_load_rejects_edited_embedding_record(tmp_path: Path) -> None:
    result, reference_path, provider = _build(tmp_path)
    assert result["status"] == "ready"
    payload = json.loads(reference_path.read_text())
    payload["embeddings"][0][0] = 0.25
    reference_path.write_text(json.dumps(payload))
    media = tmp_path / "media.png"
    _image(media)

    verified = verify_identity(
        media, creator="stacey", root=tmp_path, provider=provider
    )

    assert verified["status"] == "unavailable"
    assert verified["failureReason"] == "reference_set_id_mismatch"


def test_reference_load_rejects_creator_mismatch(tmp_path: Path) -> None:
    result, reference_path, provider = _build(tmp_path)
    assert result["status"] == "ready"
    payload = json.loads(reference_path.read_text())
    payload["creator"] = "larissa"
    reference_path.write_text(json.dumps(payload))
    media = tmp_path / "media.png"
    _image(media)

    verified = verify_identity(
        media, creator="stacey", root=tmp_path, provider=provider
    )

    assert verified["status"] == "unavailable"
    assert verified["failureReason"] == "reference_set_schema_or_creator_mismatch"


def test_reference_load_rejects_source_substitution(tmp_path: Path) -> None:
    result, _reference_path, provider = _build(tmp_path)
    assert result["status"] == "ready"
    source = tmp_path / "reviewed/ref_a.png"
    source.write_bytes(b"substituted")
    media = tmp_path / "media.png"
    _image(media)

    verified = verify_identity(
        media, creator="stacey", root=tmp_path, provider=provider
    )

    assert verified["status"] == "unavailable"
    assert verified["failureReason"] == "reference_set_source_substituted"


def test_reference_build_rejects_embedding_outlier_from_consensus(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "reviewed"
    source_dir.mkdir()
    for name in ("ref_a.png", "ref_b.png", "wrong_person.png"):
        _image(source_dir / name)
    provider = FaceProvider(
        {
            "ref_a.png": [[1.0, 0.0]],
            "ref_b.png": [[0.99, 0.01]],
            "wrong_person.png": [[0.0, 1.0]],
        }
    )

    result = build_reference_set(
        creator="stacey",
        input_dir=source_dir,
        root=tmp_path,
        provider=provider,
        creator_identity_profile=_profile(
            reference_paths=tuple(sorted(source_dir.iterdir()))
        ),
    )

    assert result["status"] == "ready"
    assert result["acceptedSourceCount"] == 2
    outlier = next(
        item for item in result["sourceImages"] if "wrong_person" in item["path"]
    )
    assert outlier["status"] == "rejected"
    assert outlier["failureReason"] == "identity_embedding_outlier"


def test_reference_build_binds_each_source_to_exact_reviewed_identity(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "reviewed"
    source_dir.mkdir()
    for name in ("ref_a.png", "ref_b.png"):
        _image(source_dir / name)
    reference_paths = tuple(sorted(source_dir.iterdir()))
    profile = _profile(
        reference_paths=reference_paths,
        extra_references=(
            {
                "namespace": "higgsfield.soul",
                "externalId": "soul-stacey",
                "fingerprint": None,
            },
        ),
    )

    result = build_reference_set(
        creator="stacey",
        input_dir=source_dir,
        root=tmp_path,
        provider=FaceProvider(),
        creator_identity_profile=profile,
    )

    assert result["schema"] == "reel_factory.identity_reference_set.v4"
    assert result["status"] == "ready"
    assert {
        item["identityReference"]["fingerprint"] for item in result["sourceImages"]
    } == {hashlib.sha256(path.read_bytes()).hexdigest() for path in reference_paths}


def test_reference_build_rejects_coherent_wrong_person_cluster(
    tmp_path: Path,
) -> None:
    reviewed_dir = tmp_path / "reviewed"
    reviewed_dir.mkdir()
    wrong_dir = tmp_path / "coherent_wrong_person"
    wrong_dir.mkdir()
    for name in ("ref_a.png", "ref_b.png"):
        _image(reviewed_dir / name)
    for name in ("wrong_a.png", "wrong_b.png"):
        _image(wrong_dir / name)
    profile = _profile(reference_paths=tuple(sorted(reviewed_dir.iterdir())))
    provider = FaceProvider(
        {
            "wrong_a.png": [[0.0, 1.0]],
            "wrong_b.png": [[0.01, 0.99]],
        }
    )

    result = build_reference_set(
        creator="stacey",
        input_dir=wrong_dir,
        root=tmp_path,
        provider=provider,
        creator_identity_profile=profile,
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "identity_reference_unresolved"
    assert not (tmp_path / "identity_references/stacey.json").exists()


def test_reference_build_rejects_missing_reviewed_identity_source(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "reviewed"
    source_dir.mkdir()
    for name in ("ref_a.png", "ref_b.png", "ref_c.png"):
        _image(source_dir / name)
    profile = _profile(reference_paths=tuple(sorted(source_dir.iterdir())))
    (source_dir / "ref_c.png").unlink()

    result = build_reference_set(
        creator="stacey",
        input_dir=source_dir,
        root=tmp_path,
        provider=FaceProvider(),
        creator_identity_profile=profile,
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "identity_reference_missing"


def test_reference_build_rejects_duplicate_reviewed_identity(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "reviewed"
    source_dir.mkdir()
    for name in ("ref_a.png", "ref_b.png"):
        _image(source_dir / name)
    paths = tuple(sorted(source_dir.iterdir()))
    profile = _profile(reference_paths=paths)
    profile["identityReferences"].append(
        {
            "namespace": "reviewed-reference",
            "externalId": paths[0].name,
            "fingerprint": hashlib.sha256(paths[1].read_bytes()).hexdigest(),
        }
    )

    result = build_reference_set(
        creator="stacey",
        input_dir=source_dir,
        root=tmp_path,
        provider=FaceProvider(),
        creator_identity_profile=profile,
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "identity_reference_duplicate"


def test_brief_mid_interval_identity_drift_blocks_video(tmp_path: Path) -> None:
    result, _reference_path, _ = _build(tmp_path)
    assert result["status"] == "ready"
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    frames: list[Path] = []
    embeddings: dict[str, list[list[float]]] = {}
    for index in range(21):
        frame = tmp_path / f"sample_{index:02d}.png"
        _image(frame)
        frames.append(frame)
        embeddings[frame.name] = [[0.0, 1.0]] if index == 11 else [[1.0, 0.0]]

    verified = verify_identity(
        video,
        creator="stacey",
        root=tmp_path,
        provider=FaceProvider(embeddings),
        frame_extractor=lambda _path: frames,
    )

    assert verified["status"] == "failed"
    assert verified["score"] == 0.0
    assert verified["frameCount"] == 21
    assert verified["frameScores"][11] == 0.0


def test_profile_binding_mismatch_is_not_usable_identity_evidence(
    tmp_path: Path,
) -> None:
    result, _reference_path, provider = _build(tmp_path)
    assert result["status"] == "ready"
    media = tmp_path / "media.png"
    _image(media)

    verified = verify_identity(
        media,
        creator="stacey",
        root=tmp_path,
        provider=provider,
        creator_identity_profile=_profile(
            profile_id="different-profile",
            reference_paths=tuple(sorted((tmp_path / "reviewed").iterdir())),
        ),
    )

    assert verified["status"] == "unavailable"
    assert verified["failureReason"] == "identity_profile_binding_mismatch"


def test_historical_reference_set_remains_readable_but_not_promotion_eligible(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "identity_references/stacey.json"
    reference_path.parent.mkdir()
    reference_path.write_text(
        json.dumps(
            {
                "schema": "reel_factory.identity_reference_set.v2",
                "creator": "stacey",
                "status": "ready",
                "referenceSetId": "historical-stacey",
                "embeddings": [[1.0, 0.0], [0.99, 0.01]],
            }
        )
    )

    health = identity_health(creator="stacey", root=tmp_path, provider=FaceProvider())

    assert health["status"] == "unavailable"
    assert health["historicalReadable"] is True
    assert health["referenceEmbeddings"] == 2
    assert health["promotionEligible"] is False
    assert health["blockingReasons"] == ["reference_set_historical_unattested"]


def test_v3_unbound_reference_set_remains_readable_but_not_promotion_eligible(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "identity_references/stacey.json"
    reference_path.parent.mkdir()
    reference_path.write_text(
        json.dumps(
            {
                "schema": "reel_factory.identity_reference_set.v3",
                "creator": "stacey",
                "status": "ready",
                "referenceSetId": "unbound-stacey",
                "embeddings": [[1.0, 0.0], [0.99, 0.01]],
            }
        )
    )

    health = identity_health(creator="stacey", root=tmp_path, provider=FaceProvider())

    assert health["status"] == "unavailable"
    assert health["historicalReadable"] is True
    assert health["promotionEligible"] is False
    assert health["blockingReasons"] == ["reference_set_historical_unbound"]


def test_reference_load_rejects_identity_binding_profile_mismatch(
    tmp_path: Path,
) -> None:
    result, reference_path, provider = _build(tmp_path)
    assert result["status"] == "ready"
    payload = json.loads(reference_path.read_text())
    payload["sourceImages"][0]["identityReference"]["externalId"] = "wrong-person"
    reference_path.write_text(json.dumps(payload))
    media = tmp_path / "media.png"
    _image(media)

    verified = verify_identity(
        media, creator="stacey", root=tmp_path, provider=provider
    )

    assert verified["status"] == "unavailable"
    assert verified["failureReason"] == "identity_reference_profile_mismatch"


def test_reference_load_rejects_identity_binding_hash_drift(tmp_path: Path) -> None:
    result, reference_path, provider = _build(tmp_path)
    assert result["status"] == "ready"
    payload = json.loads(reference_path.read_text())
    payload["sourceImages"][0]["identityReference"]["fingerprint"] = "f" * 64
    reference_path.write_text(json.dumps(payload))
    media = tmp_path / "media.png"
    _image(media)

    verified = verify_identity(
        media, creator="stacey", root=tmp_path, provider=provider
    )

    assert verified["status"] == "unavailable"
    assert verified["failureReason"] == "identity_reference_hash_drift"


def test_future_reference_and_receipt_timestamps_fail_closed(tmp_path: Path) -> None:
    result, reference_path, provider = _build(tmp_path)
    assert result["status"] == "ready"
    media = tmp_path / "media.png"
    _image(media)
    passed = verify_identity(media, creator="stacey", root=tmp_path, provider=provider)
    assert passed["status"] == "passed"
    passed["observedAt"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="identity_qc_observed_at_invalid"):
        identity_qc_receipt(passed)

    payload = json.loads(reference_path.read_text())
    payload["createdAt"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    reference_path.write_text(json.dumps(payload))

    verified = verify_identity(
        media, creator="stacey", root=tmp_path, provider=provider
    )

    assert verified["failureReason"] == "reference_set_timestamp_invalid"


def test_identity_receipt_rejects_substituted_output(tmp_path: Path) -> None:
    result, _reference_path, provider = _build(tmp_path)
    assert result["status"] == "ready"
    media = tmp_path / "media.png"
    _image(media)
    verified = verify_identity(
        media, creator="stacey", root=tmp_path, provider=provider
    )
    assert verified["status"] == "passed"
    media.write_bytes(b"substituted-output")

    with pytest.raises(ValueError, match="identity_qc_subject_substituted"):
        identity_qc_receipt(verified)


def test_identity_reference_cli_rejects_missing_profile_binding(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "reviewed"
    source_dir.mkdir()
    _image(source_dir / "ref_a.png")
    _image(source_dir / "ref_b.png")

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "identity-reference-build",
                "--creator",
                "stacey",
                "--input-dir",
                str(source_dir),
                "--root",
                str(tmp_path),
            ]
        )

    assert exc.value.code == 2


def test_identity_reference_cli_rejects_substituted_profile_file(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "reviewed"
    source_dir.mkdir()
    _image(source_dir / "ref_a.png")
    _image(source_dir / "ref_b.png")
    original = _profile(reference_paths=tuple(sorted(source_dir.iterdir())))
    expected_fingerprint = _fingerprint(original)
    substituted = {**original, "profileId": "substituted-profile"}
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(substituted))

    with pytest.raises(SystemExit, match="identity_profile_file_substituted"):
        main(
            [
                "identity-reference-build",
                "--creator",
                "stacey",
                "--input-dir",
                str(source_dir),
                "--root",
                str(tmp_path),
                "--identity-profile",
                str(profile_path),
                "--identity-profile-fingerprint",
                expected_fingerprint,
            ]
        )


def test_identity_reference_cli_returns_nonzero_for_failed_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import reel_factory.identity_verification as identity_module

    source_dir = tmp_path / "reviewed"
    source_dir.mkdir()
    _image(source_dir / "ref_a.png")
    _image(source_dir / "ref_b.png")
    profile = _profile(reference_paths=tuple(sorted(source_dir.iterdir())))
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    monkeypatch.setattr(
        identity_module, "get_identity_provider", lambda: UnavailableProvider()
    )

    exit_code = main(
        [
            "identity-reference-build",
            "--creator",
            "stacey",
            "--input-dir",
            str(source_dir),
            "--root",
            str(tmp_path),
            "--identity-profile",
            str(profile_path),
            "--identity-profile-fingerprint",
            _fingerprint(profile),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["status"] == "failed"
    assert output["failureReason"] == (
        "identity_provider_unavailable:ModuleNotFoundError"
    )
    assert not (tmp_path / "identity_references/stacey.json").exists()
