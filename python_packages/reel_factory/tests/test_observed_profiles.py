from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from reel_factory.observed_profiles import (
    CONTENTFORGE_QC_POLICY_FILES,
    PROFILES,
    build_ffmpeg_command,
    contentforge_qc_policy_sha256,
    default_attempt_limit,
    probe_media_identity,
    qualify_renderer_equivalence,
    render_observed_profile,
    sample_profile_parameters,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_contentforge_qc_policy_fingerprint_binds_policy_bytes(tmp_path: Path) -> None:
    root = tmp_path / "contentforge"
    for relative in CONTENTFORGE_QC_POLICY_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    before = contentforge_qc_policy_sha256(root)
    (root / CONTENTFORGE_QC_POLICY_FILES[0]).write_text("changed", encoding="utf-8")
    assert contentforge_qc_policy_sha256(root) != before


def _image(path: Path, *, size: tuple[int, int] = (320, 240)) -> Path:
    image = Image.new("RGB", size, (80, 120, 160))
    exif = Image.Exif()
    exif[0x010E] = "inherited metadata"
    image.save(path, quality=95, exif=exif)
    return path


def _video(path: Path, *, audio: bool = False) -> Path:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=30:duration=1.2",
    ]
    if audio:
        command.extend(
            ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1.2"]
        )
    command.extend(
        [
            "-metadata",
            "comment=inherited metadata",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if audio:
        command.extend(["-c:a", "aac", "-shortest"])
    command.append(str(path))
    subprocess.run(command, check=True)
    return path


def _render(
    source: Path,
    output_dir: Path,
    *,
    profile: str,
    count: int = 1,
    **kwargs,
):
    return render_observed_profile(
        source_path=source,
        output_dir=output_dir,
        parent_asset_id="asset_control",
        expected_source_sha256=_sha(source),
        profile=profile,
        target_accepted_count=count,
        caption_state=kwargs.pop("caption_state", "uncaptioned_verified"),
        audio_state=kwargs.pop("audio_state", "none"),
        passive_content=kwargs.pop("passive_content", True),
        synchronized_content=kwargs.pop("synchronized_content", False),
        visible_text=kwargs.pop("visible_text", False),
        **kwargs,
    )


def test_profiles_are_deterministic_and_inside_v1_envelopes():
    media = {"fps": 30.0}
    for profile in PROFILES.values():
        first = sample_profile_parameters(profile, seed="a" * 64, media=media)
        assert first == sample_profile_parameters(profile, seed="a" * 64, media=media)
    mirror = sample_profile_parameters(
        PROFILES["mirror_crop_tone"], seed="b" * 64, media=media
    )
    assert 0.02 <= mirror["horizontalCropTotal"] <= 0.06
    assert 1.01 <= mirror["zoom"] <= 1.05
    dark = sample_profile_parameters(
        PROFILES["tilt_crop_dark"], seed="c" * 64, media=media
    )
    assert 0.15 <= abs(dark["rotationDegrees"]) <= 0.45
    assert -0.04 <= dark["brightness"] <= -0.015
    editorial = sample_profile_parameters(
        PROFILES["light_editorial"], seed="d" * 64, media=media
    )
    assert abs(editorial["positionShiftX"]) <= 0.01
    trim = sample_profile_parameters(
        PROFILES["opening_trim"], seed="e" * 64, media=media
    )
    assert 2 <= trim["openingFrames"] <= 4
    assert default_attempt_limit(1) == 4
    assert default_attempt_limit(10) == 40
    assert default_attempt_limit(25) == 40


def test_crop_and_zoom_are_both_applied():
    command = build_ffmpeg_command(
        source=Path("/tmp/source.jpg"),
        output=Path("/tmp/output.jpg"),
        media={"mediaType": "image", "width": 320, "height": 240},
        profile_id="mirror_crop_tone",
        sampled={
            "horizontalMirror": True,
            "horizontalCropTotal": 0.02,
            "verticalCropTotal": 0.02,
            "zoom": 1.05,
            "brightness": 0.0,
            "contrast": 1.0,
            "saturation": 1.0,
        },
    )
    filters = command[command.index("-vf") + 1]
    assert "crop=298:222" in filters


@pytest.mark.parametrize(
    ("profile", "kwargs", "reason"),
    [
        (
            "mirror_crop_tone@1",
            {"visible_text": True},
            "mirror_visible_text_ineligible",
        ),
        (
            "light_editorial@1",
            {"caption_state": "captioned"},
            "uncaptioned_source_evidence_missing",
        ),
        (
            "opening_trim@1",
            {"synchronized_content": True},
            "synchronized_content_ineligible",
        ),
        (
            "opening_trim@1",
            {"passive_content": False},
            "passive_content_required",
        ),
    ],
)
def test_ineligible_inputs_do_not_render(
    tmp_path: Path, profile: str, kwargs: dict, reason: str
):
    source = _image(tmp_path / "source.jpg")
    receipt = _render(source, tmp_path / "out", profile=profile, **kwargs)
    assert receipt["actualAcceptedCount"] == 0
    assert reason in receipt["exhaustionReasons"]


def test_jpeg_and_png_preserve_source_and_strip_inherited_metadata(tmp_path: Path):
    for extension in ("jpg", "png"):
        source = _image(tmp_path / f"source.{extension}")
        before = source.read_bytes()
        receipt = _render(
            source,
            tmp_path / extension,
            profile="light_editorial@1",
        )
        assert receipt["actualAcceptedCount"] == 1
        assert source.read_bytes() == before
        output = Path(receipt["accepted"][0]["output"]["path"])
        with Image.open(output) as image:
            assert not image.getexif()
        assert probe_media_identity(output)["width"] == 320


def test_rejected_attempt_does_not_consume_requested_count(tmp_path: Path):
    source = _image(tmp_path / "source.jpg")
    calls = 0

    def qc(_source: Path, _candidate: Path, _siblings: list[Path]):
        nonlocal calls
        calls += 1
        return {
            "status": "failed" if calls == 1 else "passed",
            "blockingCodes": ["fixture_rejection"] if calls == 1 else [],
        }

    receipt = _render(
        source,
        tmp_path / "out",
        profile="light_editorial@1",
        count=2,
        attempt_limit=4,
        qc_callback=qc,
    )
    assert receipt["actualAcceptedCount"] == 2
    assert [row["acceptedIndex"] for row in receipt["accepted"]] == [1, 2]
    assert receipt["attempts"][0]["status"] == "rejected"
    assert len(receipt["attempts"]) == 3


def test_retry_exhaustion_returns_exact_reasons(tmp_path: Path):
    source = _image(tmp_path / "source.jpg")
    receipt = _render(
        source,
        tmp_path / "out",
        profile="light_editorial@1",
        count=2,
        attempt_limit=2,
        qc_callback=lambda *_: {
            "status": "failed",
            "blockingCodes": ["focal_safety_failed"],
        },
    )
    assert receipt["actualAcceptedCount"] == 0
    assert receipt["exhaustionReasons"] == [
        "focal_safety_failed",
        "contentforge_qc_failed",
    ]


def test_static_and_passive_video_paths_preserve_shape_fps_and_strip_audio(
    tmp_path: Path,
):
    for profile, audio in (
        ("light_editorial@1", False),
        ("opening_trim@1", True),
    ):
        source = _video(tmp_path / f"{profile.split('@')[0]}.mp4", audio=audio)
        source_media = probe_media_identity(source)
        receipt = _render(
            source,
            tmp_path / profile.split("@")[0],
            profile=profile,
            audio_state="pre_final" if audio else "none",
        )
        assert receipt["actualAcceptedCount"] == 1
        output = receipt["accepted"][0]["output"]
        assert (output["width"], output["height"], output["fps"]) == (
            source_media["width"],
            source_media["height"],
            source_media["fps"],
        )
        assert output["audioPresent"] is False
        if profile.startswith("opening_trim"):
            assert output["durationSeconds"] < source_media["durationSeconds"]


def test_missing_sha_mismatch_and_unsupported_dimensions_fail_closed(tmp_path: Path):
    source = _image(tmp_path / "small.jpg", size=(32, 32))
    receipt = _render(
        source,
        tmp_path / "small",
        profile="light_editorial@1",
    )
    assert receipt["exhaustionReasons"] == ["unsupported_dimensions"]
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        render_observed_profile(
            source_path=source,
            output_dir=tmp_path / "bad",
            parent_asset_id="asset",
            expected_source_sha256="0" * 64,
            profile="light_editorial@1",
            target_accepted_count=1,
            caption_state="uncaptioned_verified",
            audio_state="none",
            passive_content=True,
            synchronized_content=False,
            visible_text=False,
        )
    with pytest.raises(FileNotFoundError):
        render_observed_profile(
            source_path=tmp_path / "missing.jpg",
            output_dir=tmp_path / "missing",
            parent_asset_id="asset",
            expected_source_sha256="0" * 64,
            profile="light_editorial@1",
            target_accepted_count=1,
            caption_state="uncaptioned_verified",
            audio_state="none",
            passive_content=True,
            synchronized_content=False,
            visible_text=False,
        )


def test_renderer_equivalence_receipt_qualifies_png_identity(tmp_path: Path):
    source = _image(tmp_path / "source.png")
    baseline = tmp_path / "baseline.json"
    identity = tmp_path / "identity.json"
    baseline.write_text('{"status":"pass"}', encoding="utf-8")
    identity.write_text('{"status":"pass"}', encoding="utf-8")
    receipt = qualify_renderer_equivalence(
        source_path=source,
        output_path=tmp_path / "identity.png",
        receipt_path=tmp_path / "equivalence.json",
        qc_regression_callback=lambda *_: {
            "regressed": False,
            "baselineReport": {
                "path": str(baseline),
                "sha256": _sha(baseline),
            },
            "identityReport": {
                "path": str(identity),
                "sha256": _sha(identity),
            },
            "newBlockingCodes": [],
        },
    )
    assert receipt["status"] == "qualified"
    assert receipt["schema"] == "creator_os.renderer_equivalence_receipt.v2"
    assert receipt["measurements"]["ssim"] >= 0.995
    assert (
        receipt["equivalencePolicy"]["crossMachineByteReproducibility"] == "not_claimed"
    )
    assert receipt["equivalencePolicy"]["byteIdentityRequired"] is False
    assert receipt["toolchain"]["ffmpeg"]["sha256"]
    assert receipt["toolchain"]["ffprobe"]["sha256"]
    assert receipt["toolchain"]["fonts"]
    assert receipt["toolchain"]["hostFingerprint"]
    assert receipt["toolchain"]["codecPolicyFingerprint"]
    assert receipt["qcEvidence"]["evaluated"] is True
    assert receipt["qcEvidence"]["baselineReport"]["sha256"] == _sha(baseline)


def test_renderer_equivalence_rejects_qc_regression(tmp_path: Path):
    source = _image(tmp_path / "source.png")
    receipt = qualify_renderer_equivalence(
        source_path=source,
        output_path=tmp_path / "identity.png",
        receipt_path=tmp_path / "equivalence.json",
        qc_regression_callback=lambda *_: True,
    )
    assert receipt["qcRegression"] is True
    assert receipt["status"] == "failed"
