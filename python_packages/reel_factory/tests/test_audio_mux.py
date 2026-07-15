from pathlib import Path

import reel_factory.audio_mux as audio_mux
from reel_factory.audio_intent import write_audio_intent
from reel_factory.audio_mux import build_mux_cmd, mux_root


def test_build_mux_cmd_uses_hook_offset_and_loudnorm(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "track.m4a"
    out = tmp_path / "out.mp4"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    audio.with_suffix(".json").write_text('{"hook_offset": 12.5}', encoding="utf-8")

    cmd = build_mux_cmd(video, audio, out=out, duration=5.0)

    assert cmd[cmd.index("-ss") + 1] == "12.500"
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in cmd[cmd.index("-af") + 1]
    assert cmd[cmd.index("-t") + 1] == "5.000"
    assert "-shortest" not in cmd


def test_build_mux_cmd_omits_offset_when_absent(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "track.m4a"
    out = tmp_path / "out.mp4"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")

    cmd = build_mux_cmd(video, audio, out=out, duration=5.0)

    assert "-ss" not in cmd
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in cmd[cmd.index("-af") + 1]


def test_mux_root_uses_selected_audio_path(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path
    video = root / "02_processed" / "clip" / "render.mp4"
    audio = root / "selected.m4a"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    used: list[Path] = []

    monkeypatch.setattr(audio_mux, "audio_stream_count", lambda _path: 0)
    monkeypatch.setattr(audio_mux, "duration_seconds", lambda _path: 5.0)

    def fake_mux(video_path, audio_path, **_kwargs):
        used.append(Path(audio_path))
        return video_path.with_name("render_audio_selected.mp4")

    monkeypatch.setattr(audio_mux, "mux_audio", fake_mux)

    result = mux_root(root, selected_audio_path=audio)

    assert result["count"] == 1
    assert used == [audio]
    assert result["tracks"][0]["audio_path"] == str(audio)


def test_mux_root_selected_audio_path_overrides_sidecar(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path
    video = root / "02_processed" / "clip" / "render.mp4"
    manual = root / "manual.m4a"
    sidecar = root / "sidecar.m4a"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    manual.write_bytes(b"manual")
    sidecar.write_bytes(b"sidecar")
    write_audio_intent(
        video,
        mode="native_trending_audio",
        audio_selection={"track_id": "sidecar", "local_path": str(sidecar)},
    )
    used: list[Path] = []

    monkeypatch.setattr(audio_mux, "audio_stream_count", lambda _path: 0)
    monkeypatch.setattr(audio_mux, "duration_seconds", lambda _path: 5.0)

    def fake_mux(video_path, audio_path, **_kwargs):
        used.append(Path(audio_path))
        return video_path.with_name("render_audio_manual.mp4")

    monkeypatch.setattr(audio_mux, "mux_audio", fake_mux)

    result = mux_root(root, selected_audio_path=manual)

    assert result["count"] == 1
    assert used == [manual]
