from pathlib import Path

import pytest
from reel_factory import audio_library_import
from reel_factory.audio_library_import import import_audio_track


def test_import_audio_track_writes_idempotent_audio_and_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "licensed.mp3"
    source.write_bytes(b"licensed-audio-bytes")
    monkeypatch.setattr(audio_library_import, "_validate_audio", lambda _path: None)

    kwargs = {
        "root": tmp_path / "reel-factory",
        "file": source,
        "title": "Night Drive",
        "artist": "Example Artist",
        "source": "example-library",
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "page_url": "https://example.com/night-drive",
        "attribution": "Night Drive by Example Artist",
        "tags": ["reel", "moody", "reel", ""],
    }
    first = import_audio_track(**kwargs)
    second = import_audio_track(**kwargs)

    audio_path = Path(first["audio_path"])
    sidecar_path = Path(first["sidecar_path"])
    assert first == second
    assert audio_path.read_bytes() == source.read_bytes()
    assert sidecar_path.exists()
    assert first["metadata"]["track_id"].startswith("example_library_")
    assert first["metadata"]["tags"] == ["moody", "reel"]
    assert first["metadata"]["selection_source"] == "embedded_licensed_audio"
    assert first["metadata"]["attribution"] == "Night Drive by Example Artist"


def test_import_audio_track_rejects_unsupported_or_ambiguous_sources(
    tmp_path: Path,
) -> None:
    source = tmp_path / "track.txt"
    source.write_text("not audio", encoding="utf-8")
    common = {
        "root": tmp_path,
        "title": "Track",
        "artist": "Artist",
        "source": "library",
        "license_name": "License",
        "license_url": "https://example.com/license",
        "page_url": "https://example.com/track",
        "tags": [],
    }

    with pytest.raises(ValueError, match="exactly one"):
        import_audio_track(**common)
    with pytest.raises(ValueError, match="audio source"):
        import_audio_track(**common, file=source)
