"""Owned offline adapter for LongCat Avatar MLX.

The upstream CLI is an e2e smoke script with hard-coded demo inputs and a
silent MP4.  Creator OS owns this boundary so the exact portrait, audio, and
prompt are explicit, the source audio is muxed, and every missing artifact
fails closed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--weights-root", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--num-frames", type=int, required=True)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--output-audio", type=Path)
    return parser


def _upstream_module(runtime_root: Path):
    script = runtime_root / "scripts/run_inference.py"
    if not script.is_file():
        raise FileNotFoundError("longcat_upstream_inference_module_missing")
    spec = importlib.util.spec_from_file_location("longcat_upstream_inference", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("longcat_upstream_inference_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _audio_mel(path: Path):
    import librosa
    import mlx.core as mx
    import numpy as np
    from transformers import WhisperFeatureExtractor

    waveform, _sample_rate = librosa.load(str(path), sr=16_000, mono=True)
    extractor = WhisperFeatureExtractor(
        feature_size=128,
        sampling_rate=16_000,
        hop_length=160,
        chunk_length=30,
        n_fft=400,
        padding_value=0.0,
        return_attention_mask=False,
    )
    features = extractor(
        waveform, sampling_rate=16_000, return_tensors="np"
    ).input_features
    return mx.array(np.asarray(features, dtype=np.float32))


def _run_checked(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed")[-3000:]
        raise RuntimeError(f"longcat_media_finalize_failed: {detail}")


def run(args: argparse.Namespace) -> dict[str, object]:
    import imageio.v2 as imageio
    import mlx.core as mx
    import numpy as np

    runtime_root = args.runtime_root.expanduser().resolve()
    weights_root = args.weights_root.expanduser().resolve()
    image_path = args.image.expanduser().resolve()
    audio_path = args.audio.expanduser().resolve()
    output_path = args.output_path.expanduser().resolve()
    output_audio = (
        args.output_audio.expanduser().resolve()
        if args.output_audio is not None
        else output_path.with_suffix(output_path.suffix + ".audio.wav")
    )
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise RuntimeError("longcat_offline_mode_required")
    for path, code in (
        (image_path, "longcat_input_image_missing"),
        (audio_path, "longcat_input_audio_missing"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{code}:{path}")
    if output_path.exists() or output_audio.exists():
        raise FileExistsError("longcat_output_collision")
    if args.height % 32 or args.width % 32:
        raise ValueError("longcat_dimensions_must_be_multiples_of_32")
    if args.num_frames < 29 or (args.num_frames - 1) % 4:
        raise ValueError("longcat_num_frames_must_be_4n_plus_1")

    upstream = _upstream_module(runtime_root)
    pipeline = upstream.build_pipeline(weights_root, variant="q4-merged")
    image = upstream.preprocess_image(image_path, args.height, args.width)
    audio_mel = _audio_mel(audio_path)
    ids, mask = upstream.tokenize_prompt(
        args.prompt, weights_root / upstream.VARIANT_DIRNAMES["q4-merged"]
    )
    text_hidden = pipeline.text_encoder(ids, mask=mask)
    text_embeds = text_hidden[:, None, :, :]
    text_mask = mask[:, None, None, :]
    empty_ids = mx.zeros_like(ids)
    empty_mask = mx.zeros_like(mask)
    uncond_hidden = pipeline.text_encoder(empty_ids, mask=empty_mask)
    video = pipeline(
        image=image,
        audio_mel=audio_mel,
        text_embeds=text_embeds,
        text_mask=text_mask,
        uncond_embeds=uncond_hidden[:, None, :, :],
        uncond_mask=empty_mask[:, None, None, :],
        height=args.height,
        width=args.width,
        num_frames=args.num_frames,
        seed=args.seed,
    )
    mx.eval(video)
    frames = (
        (np.asarray(video).transpose(0, 2, 3, 4, 1)[0] * 127.5 + 127.5)
        .clip(0, 255)
        .astype(np.uint8)
    )
    duration = len(frames) / args.fps

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="longcat-finalize-", dir=output_path.parent
    ) as temp_dir:
        silent = Path(temp_dir) / "silent.mp4"
        writer = imageio.get_writer(
            str(silent), fps=args.fps, codec="libx264", quality=8
        )
        try:
            for frame in frames:
                writer.append_data(frame)
        finally:
            writer.close()
        _run_checked(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(audio_path),
                "-t",
                f"{duration:.6f}",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(output_audio),
            ]
        )
        _run_checked(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(silent),
                "-i",
                str(output_audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                f"{duration:.6f}",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
    if not output_path.is_file() or not output_audio.is_file():
        raise RuntimeError("longcat_final_media_missing")
    return {
        "schema": "reel_factory.longcat_mlx_adapter.v1",
        "frames": len(frames),
        "fps": args.fps,
        "durationSeconds": duration,
        "audioMuxed": True,
    }


def main() -> int:
    try:
        payload = run(_parser().parse_args())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
