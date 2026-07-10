"""Generate timed caption segments from local speech transcription."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text


def transcribe_clip(
    root: Path,
    clip: str,
    *,
    backend: str = "mlx-whisper",
    model: str = "mlx-community/whisper-tiny",
    overwrite: bool = False,
) -> dict[str, Any]:
    if backend != "mlx-whisper":
        raise ValueError("only mlx-whisper is supported in this version")
    root = Path(root).resolve()
    src = root / "00_source_videos" / f"{clip}.mp4"
    if not src.exists():
        raise FileNotFoundError(f"source clip not found: {src}")
    if not _has_audio_stream(src):
        return {
            "ok": False,
            "error": "source clip has no audio stream to transcribe",
            "code": "no_audio",
        }
    if not _module_available("mlx_whisper"):
        return {
            "ok": False,
            "error": "mlx-whisper is not installed. Install with: pip install mlx-whisper",
        }
    try:
        import mlx_whisper  # type: ignore

        data = mlx_whisper.transcribe(
            str(src),
            path_or_hf_repo=model,
            word_timestamps=True,
            verbose=False,
        )
    except Exception as e:
        return {"ok": False, "error": f"mlx-whisper transcription failed: {e}"}
    segments = _segments_from_whisper(data)
    hook = {"segments": segments}
    spoken_hook = spoken_hook_from_segments(segments)
    if spoken_hook:
        hook["spokenHook"] = spoken_hook
    if not hook["segments"]:
        return {"ok": False, "error": "no speech segments found"}
    out_path = root / "01_captions" / f"{clip}.whisper.json"
    if out_path.exists() and not overwrite:
        return {"ok": True, "path": str(out_path), "hook": hook, "written": False}
    atomic_write_text(
        out_path,
        json.dumps(
            {"hooks": [hook], "caption_color": "auto"}, indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return {"ok": True, "path": str(out_path), "hook": hook, "written": True}


def _segments_from_whisper(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("segments") or []
    segments: list[dict[str, Any]] = []
    for seg in raw:
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start + 1.5)
        pieces = _phrase_chunks(text, max_chars=54)
        if len(pieces) == 1:
            segments.append(
                {"text": pieces[0], "start": round(start, 2), "end": round(end, 2)}
            )
            continue
        dur = max(0.1, end - start)
        step = dur / len(pieces)
        for idx, piece in enumerate(pieces):
            segments.append(
                {
                    "text": piece,
                    "start": round(start + step * idx, 2),
                    "end": round(start + step * (idx + 1), 2),
                }
            )
    return segments


def spoken_hook_from_segments(
    segments: list[dict[str, Any]], *, first_seconds: float = 3.0
) -> str:
    parts = [
        str(segment.get("text") or "").strip()
        for segment in segments
        if float(segment.get("start") or 0.0) < first_seconds
        and str(segment.get("text") or "").strip()
    ]
    return " ".join(parts).strip()


def _phrase_chunks(text: str, max_chars: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > max_chars:
            chunks.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _module_available(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def _has_audio_stream(path: Path) -> bool:
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    try:
        out = (
            subprocess.check_output(
                [
                    ffprobe,
                    "-v",
                    "0",
                    "-select_streams",
                    "a",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "csv=p=0",
                    str(path),
                ],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return False
    return bool(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--clip", required=True)
    parser.add_argument("--backend", choices=["mlx-whisper"], default="mlx-whisper")
    parser.add_argument("--model", default="mlx-community/whisper-tiny")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            transcribe_clip(
                Path(args.root),
                args.clip,
                backend=args.backend,
                model=args.model,
                overwrite=args.overwrite,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
