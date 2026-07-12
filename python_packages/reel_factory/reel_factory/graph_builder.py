"""FFmpeg graph construction for reel renders."""

from __future__ import annotations

import random
from dataclasses import dataclass

from render_plan import RenderPlan


@dataclass(frozen=True)
class EncoderProfile:
    name: str
    codec: str
    description: str
    runnable: bool = True


ENCODER_PROFILES: dict[str, EncoderProfile] = {
    "social_h264": EncoderProfile(
        "social_h264",
        "h264_videotoolbox",
        "Backward-compatible alias for mac_h264_videotoolbox.",
    ),
    "mac_h264_videotoolbox": EncoderProfile(
        "mac_h264_videotoolbox",
        "h264_videotoolbox",
        "Apple VideoToolbox H.264 social delivery profile.",
    ),
    "prores_lt": EncoderProfile(
        "prores_lt",
        "prores_ks",
        "Apple ProRes LT mezzanine/review profile.",
    ),
    "cpu_h264_x264": EncoderProfile(
        "cpu_h264_x264",
        "libx264",
        "CPU H.264 fallback profile for portability.",
    ),
    "linux_nvenc": EncoderProfile(
        "linux_nvenc",
        "h264_nvenc",
        "Linux/NVIDIA H.264 profile; requires FFmpeg with NVENC.",
    ),
    "linux_vaapi": EncoderProfile(
        "linux_vaapi",
        "h264_vaapi",
        "Declared Linux/VAAPI profile; needs a VAAPI-specific upload graph.",
        runnable=False,
    ),
}


COLOR_PRESETS: dict[str, list[str]] = {
    "none": [],
    "bright_pop": [
        "eq=contrast=1.06:saturation=1.14:brightness=0.015",
        "colorbalance=rs=0.010:gs=0.004:bs=-0.006",
    ],
    "warm": [
        "eq=contrast=1.04:saturation=1.08:brightness=0.010",
        "colorbalance=rs=0.030:gs=0.008:bs=-0.020",
    ],
    "cool": [
        "eq=contrast=1.03:saturation=1.04:brightness=-0.004",
        "colorbalance=rs=-0.018:gs=0.000:bs=0.026",
    ],
    "cinematic": [
        "eq=contrast=1.10:saturation=0.94:brightness=-0.012",
        "colorbalance=rs=0.012:gs=-0.004:bs=-0.018",
    ],
}


TARGET_DIMS = {
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
}

# Keep short-form H.264 delivery files comfortably below the 50 MB upload
# boundary used by the production media bucket. At 18 Mbps, a 15-second reel
# is roughly 34 MB before container overhead. ProRes mezzanine outputs are not
# delivery files and intentionally bypass this ceiling.
MAX_SOCIAL_VIDEO_BITRATE_MBPS = 18


def target_dimensions(target_ratio: str) -> tuple[int, int]:
    if target_ratio not in TARGET_DIMS:
        raise ValueError(f"unknown target ratio: {target_ratio}")
    return TARGET_DIMS[target_ratio]


def target_social_bitrate_mbps(plan: RenderPlan) -> int:
    """Return the bounded H.264 delivery bitrate for a render plan."""
    target_mbps = plan.bitrate_mbps
    if plan.src_bitrate_mbps and plan.src_bitrate_mbps > 0:
        target_mbps = max(target_mbps, round(plan.src_bitrate_mbps * 1.05))
    return min(target_mbps, MAX_SOCIAL_VIDEO_BITRATE_MBPS)


def caption_overlay_enable(start: float, end: float | None) -> str:
    if end is None:
        return f"gte(t\\,{start:.3f})"
    # FFmpeg's between() includes both endpoints; half-open timing prevents adjacent captions from stacking.
    return f"gte(t\\,{start:.3f})*lt(t\\,{end:.3f})"


def _camera_variation_pre_scale(
    recipe_name: str, src_hash: str, account_scope: str = "local_review"
) -> list[str]:
    scope = (account_scope or "local_review").strip() or "local_review"
    rng = random.Random(f"camera|{recipe_name}|{src_hash}|{scope}")
    chain: list[str] = []

    crop_w = rng.uniform(0.95, 0.97)
    crop_h = rng.uniform(0.95, 0.97)
    crop_x = rng.uniform(0, 1 - crop_w)
    crop_y = rng.uniform(0, 1 - crop_h)
    chain.append(
        f"crop=iw*{crop_w:.4f}:ih*{crop_h:.4f}:iw*{crop_x:.4f}:ih*{crop_y:.4f}"
    )

    rot_deg = rng.uniform(0.2, 0.5) * (1 if rng.random() > 0.5 else -1)
    rot_rad = rot_deg * 0.0174533
    chain.append(f"rotate={rot_rad:.5f}:fillcolor=black:bilinear=1")
    rot_crop = max(0.96, 1 - abs(rot_deg) * 0.04)
    chain.append(
        f"crop=iw*{rot_crop:.4f}:ih*{rot_crop:.4f}"
        f":iw*(1-{rot_crop:.4f})/2:ih*(1-{rot_crop:.4f})/2"
    )

    hue_shift = rng.uniform(-3, 3)
    chain.append(f"hue=h={hue_shift:.1f}")
    cb_r = rng.uniform(-0.015, 0.015)
    cb_g = rng.uniform(-0.015, 0.015)
    cb_b = rng.uniform(-0.015, 0.015)
    chain.append(f"colorbalance=rs={cb_r:.3f}:gs={cb_g:.3f}:bs={cb_b:.3f}")

    sharp_str = rng.uniform(0.3, 0.5)
    chain.append(f"unsharp=3:3:{sharp_str:.2f}:3:3:0.0")
    noise_str = rng.randint(2, 4)
    chain.append(f"noise=c0s={noise_str}:c0f=t+u")
    return chain


def build_video_filter(plan: RenderPlan) -> str:
    recipe = plan.recipe
    head = recipe.trim_head
    effective_dur = max(0.1, plan.duration - recipe.trim_head - recipe.trim_tail)

    chain: list[str] = []

    if head > 0 or recipe.trim_tail > 0:
        chain.append(f"trim=start={head:.3f}:duration={effective_dur:.3f}")
    chain.append("setpts=PTS-STARTPTS")

    if recipe.speed != 1.0:
        chain.append(f"setpts=PTS/{recipe.speed:.4f}")
    if recipe.reverse:
        chain.append("reverse")
    if recipe.hflip:
        chain.append("hflip")

    if recipe.tilt_deg:
        rot_rad = recipe.tilt_deg * 0.0174533
        chain.append(f"rotate={rot_rad:.5f}:fillcolor=black:bilinear=1")
        rot_crop = max(0.94, 1 - abs(recipe.tilt_deg) * 0.035)
        chain.append(
            f"crop=iw*{rot_crop:.4f}:ih*{rot_crop:.4f}"
            f":iw*(1-{rot_crop:.4f})/2:ih*(1-{rot_crop:.4f})/2"
        )

    if recipe.zoom != 1.0:
        inv = 1.0 / recipe.zoom
        chain.append(f"crop=iw*{inv:.4f}:ih*{inv:.4f}")

    if recipe.camera_variation:
        chain.extend(
            _camera_variation_pre_scale(recipe.name, plan.src_hash, plan.account_scope)
        )

    src_w, src_h = plan.src_dims
    target_w, target_h = target_dimensions(plan.target_ratio)
    if plan.target_ratio == "9:16" and (target_w, target_h) == (src_w, src_h):
        chain.append(f"scale={src_w}:{src_h}:flags=lanczos")
    else:
        chain.append(
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos"
        )
        chain.append(f"crop={target_w}:{target_h}")
    chain.append("unsharp=3:3:0.4:3:3:0.0")

    if recipe.color_preset != "none":
        chain.extend(COLOR_PRESETS.get(recipe.color_preset, COLOR_PRESETS["none"]))
    if (recipe.eq_contrast, recipe.eq_saturation, recipe.eq_brightness) != (
        1.0,
        1.0,
        0.0,
    ):
        chain.append(
            f"eq=contrast={recipe.eq_contrast}"
            f":saturation={recipe.eq_saturation}"
            f":brightness={recipe.eq_brightness}"
        )

    return ",".join(chain)


def _encode_args(plan: RenderPlan, target_mbps: int) -> tuple[str, list[str]]:
    profile = plan.output_profile
    if profile not in ENCODER_PROFILES:
        raise ValueError(f"unknown output profile: {profile}")
    if not ENCODER_PROFILES[profile].runnable:
        raise ValueError(
            f"output profile requires a platform-specific graph: {profile}"
        )

    if profile == "prores_lt":
        return "yuv422p10le", [
            "-c:v",
            "prores_ks",
            "-profile:v",
            "1",
            "-pix_fmt",
            "yuv422p10le",
            "-vendor",
            "apl0",
        ]

    if profile == "cpu_h264_x264":
        return "yuv420p", [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-profile:v",
            "high",
            "-level",
            "4.2",
            "-maxrate",
            f"{target_mbps + 2}M",
            "-bufsize",
            f"{target_mbps * 2}M",
            "-movflags",
            "+faststart",
        ]

    if profile == "linux_nvenc":
        return "yuv420p", [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-profile:v",
            "high",
            "-b:v",
            f"{target_mbps}M",
            "-maxrate",
            f"{target_mbps + 2}M",
            "-bufsize",
            f"{target_mbps * 2}M",
            "-movflags",
            "+faststart",
        ]

    return "yuv420p", [
        "-c:v",
        "h264_videotoolbox",
        "-profile:v",
        "high",
        "-level",
        "4.2",
        "-b:v",
        f"{target_mbps}M",
        "-maxrate",
        f"{target_mbps + 2}M",
        "-bufsize",
        f"{target_mbps * 2}M",
        "-realtime",
        "0",
        "-allow_sw",
        "0",
        "-coder",
        "cabac",
        "-movflags",
        "+faststart",
    ]


def build_ffmpeg_cmd(plan: RenderPlan, ffmpeg: str) -> list[str]:
    target_mbps = target_social_bitrate_mbps(plan)

    vf = build_video_filter(plan)
    pix_fmt, encode_args = _encode_args(plan, target_mbps)
    recipe = plan.recipe
    if recipe.burn_caption and plan.caption_pngs:
        inputs = ["-i", str(plan.src)]
        for png_path, _, _ in plan.caption_pngs:
            inputs += ["-loop", "1", "-i", str(png_path)]

        fc_parts = [f"[0:v]{vf}[vs0]"]
        for i in range(len(plan.caption_pngs)):
            fc_parts.append(f"[{i + 1}:v]format=rgba[cap{i}]")
        for i, (_, start, end) in enumerate(plan.caption_pngs):
            enable = caption_overlay_enable(start, end)
            in_s = f"vs{i}"
            out_s = f"vs{i + 1}" if i < len(plan.caption_pngs) - 1 else "vsf"
            fc_parts.append(
                f"[{in_s}][cap{i}]overlay=0:0"
                f":enable={enable}:eof_action=pass:format=auto[{out_s}]"
            )
        fc_parts.append(f"[vsf]format={pix_fmt}[v]")
        fc = ";".join(fc_parts)
    else:
        fc = f"[0:v]{vf},format={pix_fmt}[v]"
        inputs = ["-i", str(plan.src)]

    return [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-nostdin",
        *inputs,
        "-filter_complex",
        fc,
        "-map",
        "[v]",
        "-an",
        *encode_args,
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-shortest",
        "-map_metadata",
        "-1",
        str(plan.out),
    ]
