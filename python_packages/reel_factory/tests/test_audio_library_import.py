import json
from pathlib import Path

from audio_library_import import import_audio


def test_import_audio_writes_audio_and_license_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"fake mp3 bytes")

    result = import_audio(
        root=tmp_path / "rf",
        url=source.as_uri(),
        title="Test Track",
        artist="Test Artist",
        source="test_source",
        license_name="Test License",
        license_url="https://example.com/license",
        page_url="https://example.com/track",
        tags=["Moody", "Reel Test"],
    )

    audio_path = Path(result["audio_path"])
    meta_path = Path(result["meta_path"])
    meta = json.loads(meta_path.read_text())
    assert audio_path.read_bytes() == b"fake mp3 bytes"
    assert meta["license"] == "Test License"
    assert meta["source_url"] == "https://example.com/track"
    assert meta["tags"] == ["moody", "reel_test"]
