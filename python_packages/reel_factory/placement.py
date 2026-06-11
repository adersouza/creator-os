"""Media probing and caption placement for reel_factory."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from placement_scorer import PlacementSummary, score_lanes

_FFMPEG_FULL = Path("/opt/homebrew/opt/ffmpeg-full/bin")
FFMPEG = str(_FFMPEG_FULL / "ffmpeg") if (_FFMPEG_FULL / "ffmpeg").exists() else shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = str(_FFMPEG_FULL / "ffprobe") if (_FFMPEG_FULL / "ffprobe").exists() else shutil.which("ffprobe") or "ffprobe"
log = logging.getLogger("reel")


@dataclass(frozen=True)
class CaptionSegmentPlan:
    png_path: Path
    start: float
    end: float | None
    text: str
    band: str
    explicit_band: bool = False


# ────────────────────────────────────────────────────────────────────────────
# ffprobe — get duration
# ────────────────────────────────────────────────────────────────────────────
async def probe_duration(path: Path) -> float:
    p = await asyncio.create_subprocess_exec(
        FFPROBE, "-v", "0", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await p.communicate()
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {err.decode()}")
    return float(out.strip())


async def probe_dimensions(path: Path) -> tuple[int, int]:
    p = await asyncio.create_subprocess_exec(
        FFPROBE, "-v", "0", "-show_entries", "stream=width,height",
        "-select_streams", "v:0", "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await p.communicate()
    if p.returncode != 0:
        return 1080, 1920
    try:
        parts = out.strip().split(b",")
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return 1080, 1920


async def probe_source_bitrate(path: Path) -> int | None:
    """Read source bitrate (Mbps, rounded). Used to size the re-encoder so
    we never drop below source quality. Returns None if ffprobe can't
    surface a bitrate (e.g. some VBR mp4s only expose container-level)."""
    # Try video stream first, then fall back to format-level bitrate.
    for entry in ("stream=bit_rate", "format=bit_rate"):
        select = ["-select_streams", "v:0"] if entry.startswith("stream") else []
        p = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "0", "-show_entries", entry,
            *select, "-of", "csv=p=0", str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await p.communicate()
        s = out.strip().decode().replace("N/A", "").strip()
        if s.isdigit():
            mbps = round(int(s) / 1_000_000)
            if mbps > 0:
                return mbps
    return None


async def probe_caption_region_luminance(path: Path, src_duration: float) -> float:
    """Sample center regions across several frames and return mean luminance.

    Returns 0.5 on any failure (caller falls back to "light").
    """
    frames: list[Path] = []
    try:
        frames = await _extract_probe_frames(path, src_duration, count=5)
        vals = [v for f in frames if (v := _center_luminance_from_frame(f)) is not None]
        if vals:
            lum = sum(vals) / len(vals)
            log.info(f"luminance probe: {len(vals)} frame(s) mean={lum:.3f}")
            return lum
    except Exception as e:
        log.warning(f"luminance probe failed for {path.name}: {e}")
    finally:
        for frame in frames:
            try:
                frame.unlink(missing_ok=True)
            except Exception:
                pass
    return 0.5


def pick_caption_color(luminance: float) -> str:
    """luminance > 0.6 → bright background → use dark text;
       otherwise → use light text (white + black stroke)."""
    return "dark" if luminance > 0.6 else "light"


def _sample_times(src_duration: float, count: int = 5) -> list[float]:
    """Stable frame sample points, avoiding the very start/end of the clip."""
    if src_duration <= 0:
        return [0.1]
    ratios = [0.18, 0.32, 0.5, 0.68, 0.82]
    return [max(0.1, min(src_duration - 0.1, src_duration * r)) for r in ratios[:count]]


async def _extract_probe_frame(path: Path, sample_t: float, tag: str) -> Path | None:
    import tempfile

    tmp = Path(tempfile.gettempdir()) / f"_probe_{tag}_{int(sample_t * 1000)}.png"
    cmd = [
        FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error",
        "-ss", f"{sample_t:.2f}", "-i", str(path), "-frames:v", "1",
        "-y", str(tmp),
    ]
    try:
        p = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(p.communicate(), timeout=10.0)
        return tmp if tmp.exists() else None
    except Exception as e:
        log.warning(f"frame extract failed for {path.name} at {sample_t:.2f}s: {e}")
        return None


async def _extract_probe_frames(path: Path, src_duration: float, count: int = 5) -> list[Path]:
    src_tag = hashlib.md5(str(path).encode()).hexdigest()[:10]
    frames = []
    for sample_t in _sample_times(src_duration, count=count):
        frame = await _extract_probe_frame(path, sample_t, src_tag)
        if frame:
            frames.append(frame)
    return frames


async def _extract_probe_frames_window(path: Path, start: float, end: float,
                                       count: int = 3) -> list[Path]:
    src_tag = hashlib.md5(f"{path}|{start:.3f}|{end:.3f}".encode()).hexdigest()[:10]
    frames = []
    start = max(0.0, start)
    end = max(start + 0.01, end)
    step = (end - start) / (count + 1)
    for i in range(count):
        frame = await _extract_probe_frame(path, start + step * (i + 1), src_tag)
        if frame:
            frames.append(frame)
    return frames


def _center_luminance_from_frame(frame_path: Path) -> float | None:
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    crop = gray[int(h * 0.35):int(h * 0.65), int(w * 0.2):int(w * 0.8)]
    if crop.size == 0:
        return None
    return float(crop.mean()) / 255.0


_YUNET_MODEL_PATH = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"


def _detect_face_band(frame_path: Path) -> str | None:
    """Run OpenCV YuNet face detection on a single frame. Returns the OUTER
    band ("top" or "bottom") with the lowest face-area coverage, or None if
    no face is detected (or OpenCV/the YuNet ONNX isn't available).

    YuNet is much more robust to off-angle / tilted poses than Haar cascades
    — handles selfies, three-quarter, side-on, lying-down poses. ~80-150ms
    per frame on M-series.
    """
    if not _YUNET_MODEL_PATH.exists():
        return None
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None

    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(
        model=str(_YUNET_MODEL_PATH), config="",
        input_size=(w, h),
        score_threshold=0.5,
        nms_threshold=0.3,
        top_k=10,
    )
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return None

    # Sum face area within each vertical third.
    third = h / 3.0
    cov = [0.0, 0.0, 0.0]   # top, middle, bottom
    for f in faces:
        x, y, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        for i in range(3):
            band_top = i * third
            band_bot = (i + 1) * third
            overlap = max(0.0, min(y + fh, band_bot) - max(y, band_top))
            cov[i] += overlap * fw
    log.info(
        f"face probe: {len(faces)} face(s), "
        f"coverage top={cov[0]:.0f} mid={cov[1]:.0f} bot={cov[2]:.0f}"
    )
    return "top" if cov[0] <= cov[2] else "bottom"


def _face_coverage_from_frame(frame_path: Path) -> tuple[float, float, float] | None:
    if not _YUNET_MODEL_PATH.exists():
        return None
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(
        model=str(_YUNET_MODEL_PATH), config="",
        input_size=(w, h),
        score_threshold=0.5,
        nms_threshold=0.3,
        top_k=10,
    )
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return None
    third = h / 3.0
    cov = [0.0, 0.0, 0.0]
    for f in faces:
        x, y, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        for i in range(3):
            band_top = i * third
            band_bot = (i + 1) * third
            overlap = max(0.0, min(y + fh, band_bot) - max(y, band_top))
            cov[i] += overlap * fw
    return cov[0], cov[1], cov[2]


def _face_side_coverage_from_frame(frame_path: Path) -> tuple[float, float] | None:
    if not _YUNET_MODEL_PATH.exists():
        return None
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(
        model=str(_YUNET_MODEL_PATH), config="",
        input_size=(w, h),
        score_threshold=0.5,
        nms_threshold=0.3,
        top_k=10,
    )
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return None
    mid = w / 2.0
    cov = [0.0, 0.0]
    for f in faces:
        x, y, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        left_overlap = max(0.0, min(x + fw, mid) - max(x, 0.0))
        right_overlap = max(0.0, min(x + fw, float(w)) - max(x, mid))
        cov[0] += left_overlap * fh
        cov[1] += right_overlap * fh
    return cov[0], cov[1]


def _band_stddev_from_frame(frame_path: Path) -> tuple[float, float, float] | None:
    """Compute spatial luminance stddev for top/middle/bottom thirds of an
    extracted frame. Returns (top_std, mid_std, bot_std) or None on failure.

    Replaces the old YDIF-based probe — YDIF needs >1 frame and can't run on
    a single sampled image. Spatial stddev is the right "busyness" metric
    for a single frame (high stddev = lots of detail = subject likely).
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, _ = gray.shape
    return (
        float(gray[:h // 3, :].std()),
        float(gray[h // 3:2 * h // 3, :].std()),
        float(gray[2 * h // 3:, :].std()),
    )


def _side_stddev_from_frame(frame_path: Path) -> tuple[float, float] | None:
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    y0, y1 = int(h * 0.18), int(h * 0.82)
    return (
        float(gray[y0:y1, :w // 2].std()),
        float(gray[y0:y1, w // 2:].std()),
    )


def _side_subject_score_from_frame(frame_path: Path) -> tuple[float, float] | None:
    """Cheap subject heuristic for side placement.

    Combines edge density and warm skin-like pixels. It is intentionally simple
    and deterministic; the goal is to avoid placing captions over people when
    face detection misses a frame, not to classify identity or content.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    y0, y1 = int(h * 0.12), int(h * 0.88)
    crop = img[y0:y1, :]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 140)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Broad warm range: enough to catch skin/arms/face without being brittle.
    skin = cv2.inRange(hsv, (0, 22, 45), (28, 190, 255))
    mid = w // 2

    def score(x0: int, x1: int) -> float:
        area = max(1, (x1 - x0) * crop.shape[0])
        edge_density = float(edges[:, x0:x1].sum()) / (255.0 * area)
        skin_density = float(skin[:, x0:x1].sum()) / (255.0 * area)
        return edge_density * 100.0 + skin_density * 180.0

    return score(0, mid), score(mid, w)


def _band_motion_from_frames(frames: list[Path]) -> list[tuple[float, float, float]]:
    try:
        import cv2  # type: ignore
    except ImportError:
        return []
    samples: list[tuple[float, float, float]] = []
    prev = None
    for frame in frames:
        img = cv2.imread(str(frame))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if prev is not None and prev.shape == gray.shape:
            diff = cv2.absdiff(prev, gray)
            h, _ = diff.shape
            samples.append((
                float(diff[:h // 3, :].mean()),
                float(diff[h // 3:2 * h // 3, :].mean()),
                float(diff[2 * h // 3:, :].mean()),
            ))
        prev = gray
    return samples


def _focal_coverage_from_frame(frame_path: Path) -> tuple[float, float, float] | None:
    """Estimate where the visual focal area sits across top/center/bottom.

    This is a deterministic fallback for clips where pose detection is not
    installed. It combines edge density with broad warm-pixel density inside
    the centered caption-safe area, which is enough to avoid covering faces,
    arms, torso, and mirror-selfie body lines in the archive clips.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    x0, x1 = int(w * 0.12), int(w * 0.88)
    crop = img[:, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 140)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    skin = cv2.inRange(hsv, (0, 22, 45), (28, 190, 255))

    scores = []
    for y0, y1 in ((0, h // 3), (h // 3, 2 * h // 3), (2 * h // 3, h)):
        area = max(1, (y1 - y0) * (x1 - x0))
        edge_density = float(edges[y0:y1, :].sum()) / (255.0 * area)
        skin_density = float(skin[y0:y1, :].sum()) / (255.0 * area)
        scores.append(edge_density * 100.0 + skin_density * 180.0)
    return scores[0], scores[1], scores[2]


def _pose_coverage_from_frame(frame_path: Path) -> tuple[float, float, float] | None:
    """Optional MediaPipe Pose signal for upper-body-aware placement."""
    try:
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore
        if not hasattr(mp, "solutions"):
            return None
    except (ImportError, AttributeError):
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    pose = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=0)
    try:
        result = pose.process(rgb)
    finally:
        pose.close()
    if not result.pose_landmarks:
        return None
    landmarks = result.pose_landmarks.landmark
    idxs = [11, 12, 23, 24]  # shoulders and hips
    visible = [
        lm for i, lm in enumerate(landmarks)
        if i in idxs and getattr(lm, "visibility", 1.0) >= 0.4
    ]
    if len(visible) < 2:
        return None
    y0 = max(0.0, min(lm.y for lm in visible) * h)
    y1 = min(float(h), max(lm.y for lm in visible) * h)
    if y1 <= y0:
        return None
    third = h / 3.0
    cov = [0.0, 0.0, 0.0]
    body_h = max(1.0, y1 - y0)
    for i in range(3):
        band_top = i * third
        band_bot = (i + 1) * third
        overlap = max(0.0, min(y1, band_bot) - max(y0, band_top))
        cov[i] = (overlap / body_h) * w
    return cov[0], cov[1], cov[2]


def _pose_side_coverage_from_frame(frame_path: Path) -> tuple[float, float] | None:
    try:
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore
        if not hasattr(mp, "solutions"):
            return None
    except (ImportError, AttributeError):
        return None
    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    pose = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=0)
    try:
        result = pose.process(rgb)
    finally:
        pose.close()
    if not result.pose_landmarks:
        return None
    landmarks = result.pose_landmarks.landmark
    idxs = [11, 12, 23, 24]
    visible = [
        lm for i, lm in enumerate(landmarks)
        if i in idxs and getattr(lm, "visibility", 1.0) >= 0.4
    ]
    if len(visible) < 2:
        return None
    x0 = max(0.0, min(lm.x for lm in visible) * w)
    x1 = min(float(w), max(lm.x for lm in visible) * w)
    if x1 <= x0:
        return None
    mid = w / 2.0
    body_w = max(1.0, x1 - x0)
    return (
        max(0.0, min(x1, mid) - max(x0, 0.0)) / body_w * h,
        max(0.0, min(x1, float(w)) - max(x0, mid)) / body_w * h,
    )


def _pick_free_side_zone(
    *,
    side_std_samples: list[tuple[float, float]],
    face_side_samples: list[tuple[float, float]],
    subject_side_samples: list[tuple[float, float]] | None = None,
    pose_side_samples: list[tuple[float, float]] | None = None,
) -> tuple[str, dict[str, float], str] | None:
    if not side_std_samples:
        return None

    def mean2(samples: list[tuple[float, float]]) -> tuple[float, float]:
        if not samples:
            return 0.0, 0.0
        n = len(samples)
        return sum(s[0] for s in samples) / n, sum(s[1] for s in samples) / n

    left_std, right_std = mean2(side_std_samples)
    left_face, right_face = mean2(face_side_samples)
    left_subject, right_subject = mean2(subject_side_samples or [])
    left_pose, right_pose = mean2(pose_side_samples or [])
    max_face = max(left_face, right_face, 1.0)
    max_pose = max(left_pose, right_pose, 1.0)
    scores = {
        "left": left_std + left_subject * 4.0 + (left_face / max_face) * 45.0 + (left_pose / max_pose) * 45.0,
        "right": right_std + right_subject * 4.0 + (right_face / max_face) * 45.0 + (right_pose / max_pose) * 45.0,
    }
    side = min(scores, key=scores.get)
    other = "right" if side == "left" else "left"
    # Only use side placement when it is meaningfully clearer than the other
    # side. This avoids random side captions on centered or low-signal clips.
    if scores[side] > scores[other] * 0.95:
        return None
    reason = f"{side} side clearest (left={scores['left']:.1f}, right={scores['right']:.1f})"
    return side, {k: round(v, 3) for k, v in scores.items()}, reason


def mirror_side_band_for_recipe(band: str, recipe: Any) -> str:
    return band


def _score_placement_from_frames(
    frames: list[Path],
    *,
    placement_signals: str = "basic",
    caption_placement_policy: str = "focal-safe",
    manifest: Any | None = None,
    src_hash: str | None = None,
    cache_pose: bool = False,
) -> tuple[PlacementSummary, list[tuple[float, float, float]]]:
    std_samples = [s for f in frames if (s := _band_stddev_from_frame(f)) is not None]
    if not std_samples:
        return score_lanes(stddev_samples=[]), []

    face_samples = [c for f in frames if (c := _face_coverage_from_frame(f)) is not None]
    focal_samples = [c for f in frames if (c := _focal_coverage_from_frame(f)) is not None]
    side_std_samples = [s for f in frames if (s := _side_stddev_from_frame(f)) is not None]
    face_side_samples = [c for f in frames if (c := _face_side_coverage_from_frame(f)) is not None]
    subject_side_samples = [s for f in frames if (s := _side_subject_score_from_frame(f)) is not None]
    motion_samples = _band_motion_from_frames(frames)
    pose_samples = None
    pose_side_samples = None
    if placement_signals == "pose":
        cached = (
            manifest.get_analysis(src_hash, "mediapipe_pose_v1")
            if cache_pose and manifest and src_hash else None
        )
        if cached and isinstance(cached.get("pose_samples"), list):
            pose_samples = [tuple(sample) for sample in cached["pose_samples"]]
            pose_side_samples = [tuple(sample) for sample in cached.get("pose_side_samples", [])]
        else:
            pose_samples = [c for f in frames if (c := _pose_coverage_from_frame(f)) is not None]
            pose_side_samples = [c for f in frames if (c := _pose_side_coverage_from_frame(f)) is not None]
            if cache_pose and manifest and src_hash:
                manifest.set_analysis(src_hash, "mediapipe_pose_v1", {
                    "pose_samples": pose_samples,
                    "pose_side_samples": pose_side_samples,
                })

    summary = score_lanes(
        stddev_samples=std_samples,
        face_samples=face_samples,
        focal_samples=focal_samples,
        motion_samples=motion_samples,
        pose_samples=pose_samples,
        placement_policy=caption_placement_policy,
    )
    metadata = {
        "face_coverage_mean": round(
            sum(sum(sample) for sample in face_samples) / len(face_samples), 5
        ) if face_samples else 0.0,
        "pose_coverage_mean": round(
            sum(sum(sample) for sample in pose_samples) / len(pose_samples), 5
        ) if pose_samples else 0.0,
        "top_stddev_mean": round(sum(sample[0] for sample in std_samples) / len(std_samples), 3),
        "center_stddev_mean": round(sum(sample[1] for sample in std_samples) / len(std_samples), 3),
        "bottom_stddev_mean": round(sum(sample[2] for sample in std_samples) / len(std_samples), 3),
    }
    metadata.update(summary.metadata)
    summary = PlacementSummary(
        lane=summary.lane,
        scores=summary.scores,
        sample_count=summary.sample_count,
        reason=summary.reason,
        metadata=metadata,
    )
    side_pick = None
    if caption_placement_policy == "legacy":
        side_pick = _pick_free_side_zone(
            side_std_samples=side_std_samples,
            face_side_samples=face_side_samples,
            subject_side_samples=subject_side_samples,
            pose_side_samples=pose_side_samples,
        )
    if side_pick:
        side, side_scores, side_reason = side_pick
        scores = dict(summary.scores)
        scores.update({f"side_{k}": v for k, v in side_scores.items()})
        summary = PlacementSummary(
            lane=side,
            scores=scores,
            sample_count=summary.sample_count,
            reason=side_reason,
            metadata=metadata,
        )
    return summary, std_samples


async def probe_caption_layout_for_window(
    path: Path,
    *,
    start: float,
    end: float,
    placement_signals: str = "basic",
    caption_placement_policy: str = "focal-safe",
) -> PlacementSummary:
    frames: list[Path] = []
    try:
        frames = await _extract_probe_frames_window(path, start, end, count=3)
        summary, _ = _score_placement_from_frames(
            frames,
            placement_signals=placement_signals,
            caption_placement_policy=caption_placement_policy,
        )
        return summary
    finally:
        for frame in frames:
            try:
                frame.unlink(missing_ok=True)
            except Exception:
                pass


async def resolve_segment_bands(
    src: Path,
    *,
    segments: list[CaptionSegmentPlan],
    source_band: str,
    placement_mode: str,
    placement_signals: str,
    caption_placement_policy: str = "focal-safe",
    recipe: Any,
    duration: float,
    placement_debug: bool = False,
    probe_func=None,
) -> list[CaptionSegmentPlan]:
    if placement_mode != "segment" or len(segments) <= 1:
        return [
            CaptionSegmentPlan(s.png_path, s.start, s.end, s.text,
                               s.band if s.explicit_band else source_band,
                               s.explicit_band)
            for s in segments
        ]

    resolved: list[CaptionSegmentPlan] = []
    previous_band: str | None = None
    effective_end = max(0.1, duration - recipe.trim_tail)
    probe = probe_func or probe_caption_layout_for_window

    for idx, seg in enumerate(segments):
        if seg.explicit_band:
            band = seg.band
            previous_band = band
            resolved.append(seg)
            continue

        seg_end = seg.end if seg.end is not None else max(seg.start, effective_end - recipe.trim_head)
        seg_duration = max(0.0, seg_end - seg.start)
        if seg_duration < 0.75:
            band = source_band
            reason = "segment too short; using source placement"
        else:
            src_start = min(duration, recipe.trim_head + seg.start)
            src_end = min(duration, recipe.trim_head + seg_end)
            probe_kwargs = {
                "start": src_start,
                "end": src_end,
                "placement_signals": placement_signals,
            }
            if probe_func is None:
                probe_kwargs["caption_placement_policy"] = caption_placement_policy
            summary = await probe(src, **probe_kwargs)
            candidate = summary.lane
            if candidate in {"left", "right"} and _too_tall_for_side(seg.text):
                candidate = _lane_fallback(summary, source_band)
            smoothed = _smooth_segment_band(previous_band, candidate, summary, seg_duration)
            band = _retention_alternate_band(
                previous_band,
                smoothed,
                summary,
                seg_duration,
                idx,
            )
            reason = summary.reason
            if placement_debug:
                log.info(
                    f"segment placement {src.stem}: idx={idx} "
                    f"start={seg.start:.2f} end={seg_end:.2f} "
                    f"band={band} candidate={summary.lane} scores={summary.scores} reason={reason}"
                )

        previous_band = band
        resolved.append(CaptionSegmentPlan(seg.png_path, seg.start, seg.end, seg.text, band, False))
        if placement_debug and seg_duration < 0.75:
            log.info(
                f"segment placement {src.stem}: idx={idx} "
                f"start={seg.start:.2f} end={seg_end:.2f} band={band} reason={reason}"
            )
    return resolved


async def probe_caption_layout(path: Path, src_duration: float,
                               placement_debug: bool = False,
                               placement_signals: str = "basic",
                               caption_placement_policy: str = "focal-safe",
                               manifest: Any | None = None,
                               src_hash: str | None = None,
                               ) -> tuple[str, str, str, PlacementSummary]:
    """Sample several frames and decide placement, visual style, and font.

    Returns (band, style, font):
      band  ∈ {"top", "bottom"}                — the calmer outer third.
      style ∈ {"classic", "ig", "meme"}        — chosen from scene busyness.
      font  ∈ Instagram caption fonts:
                  stddev < 35 → ig      + Instagram Sans Condensed
                  < 50        → ig      + Instagram Sans Condensed
                  < 65        → classic + Instagram Sans Condensed
                  >= 65       → meme    + Instagram Sans Condensed Bold

    Falls back to ("top", "ig", "Instagram Sans Condensed") on any probe failure.
    """
    frames: list[Path] = []
    try:
        frames = await _extract_probe_frames(path, src_duration, count=5)
        summary, std_samples = _score_placement_from_frames(
            frames,
            placement_signals=placement_signals,
            caption_placement_policy=caption_placement_policy,
            manifest=manifest,
            src_hash=src_hash,
            cache_pose=True,
        )
        if not std_samples:
            summary = score_lanes(stddev_samples=[])
            return "top", "ig", "Instagram Sans Condensed", summary
        top_std = sum(s[0] for s in std_samples) / len(std_samples)
        mid_std = sum(s[1] for s in std_samples) / len(std_samples)
        bot_std = sum(s[2] for s in std_samples) / len(std_samples)

        overall_std = (top_std + mid_std + bot_std) / 3
        log.info(
            f"layout stddev: frames={len(std_samples)} top={top_std:.1f} mid={mid_std:.1f} bot={bot_std:.1f} "
            f"overall={overall_std:.1f}"
        )

        # Style + font driven by overall scene busyness (8-bit luma stddev).
        # Calibrated against typical clips: clean indoor ≈ 30-40, busy
        # outdoor / cluttered ≈ 60-80.
        if overall_std < 35:
            style, font = "ig", "Instagram Sans Condensed"
        elif overall_std < 50:
            style, font = "ig", "Instagram Sans Condensed"
        elif overall_std < 65:
            style, font = "classic", "Instagram Sans Condensed"
        else:
            style, font = "meme", "Instagram Sans Condensed Bold"

        if placement_debug:
            log.info(
                f"placement scores {path.stem}: lane={summary.lane} "
                f"samples={summary.sample_count} scores={summary.scores} reason={summary.reason}"
            )
        else:
            log.info(f"placement: {summary.reason}")

        return summary.lane, style, font, summary
    except Exception as e:
        log.warning(f"layout probe failed for {path.name}: {e}")
        summary = score_lanes(stddev_samples=[(0.0, 8.0, 1.0)])
        return "top", "ig", "Instagram Sans Condensed", summary
    finally:
        for frame in frames:
            try:
                frame.unlink(missing_ok=True)
            except Exception:
                pass


def _zone_score(summary: PlacementSummary, zone: str) -> float | None:
    key = f"side_{zone}" if zone in {"left", "right"} else zone
    value = summary.scores.get(key)
    return float(value) if value is not None else None


def _too_tall_for_side(text: str) -> bool:
    estimated_lines = 0
    for line in text.splitlines() or [text]:
        estimated_lines += max(1, (len(line.strip()) + 17) // 18)
    return estimated_lines >= 4


def _lane_fallback(summary: PlacementSummary, default: str) -> str:
    candidates = [z for z in ("top", "bottom") if z in summary.scores]
    if not candidates:
        return default
    return min(candidates, key=lambda z: summary.scores[z])


def _smooth_segment_band(previous: str | None, candidate: str,
                         summary: PlacementSummary,
                         segment_duration: float) -> str:
    if not previous or previous == candidate:
        return candidate
    if previous in {"left", "right"} and candidate in {"left", "right"} and segment_duration < 1.25:
        return previous
    prev_score = _zone_score(summary, previous)
    cand_score = _zone_score(summary, candidate)
    if prev_score is None or cand_score is None:
        return candidate
    return candidate if cand_score <= prev_score * 0.85 else previous


def _retention_alternate_band(previous: str | None, current: str,
                              summary: PlacementSummary,
                              segment_duration: float,
                              segment_index: int) -> str:
    """Nudge timed captions to move when a nearby-safe zone exists.

    Source-level captions should be stable, but timed multi-part captions can
    earn retention by moving the viewer's eye. We still avoid reckless jumps:
    the alternate zone has to have a comparable placement score and short
    segments never ping-pong between side zones.
    """
    if not previous or previous != current or segment_duration < 1.25:
        return current

    current_score = _zone_score(summary, current)
    if current_score is None:
        return current

    preferred_orders = [
        ("top", "right", "bottom", "left", "center"),
        ("bottom", "left", "top", "right", "center"),
        ("right", "top", "left", "bottom", "center"),
        ("left", "bottom", "right", "top", "center"),
        ("top", "bottom", "right", "left", "center"),
    ]
    order = preferred_orders[segment_index % len(preferred_orders)]
    candidates: list[tuple[str, float]] = []
    for zone in order:
        if zone == current:
            continue
        if current in {"left", "right"} and zone in {"left", "right"} and segment_duration < 1.75:
            continue
        score = _zone_score(summary, zone)
        if score is not None:
            candidates.append((zone, score))
    if not candidates:
        return current

    # Scores are penalties, so lower is better. Allow a moderate trade-off for
    # retention movement, but do not place over a visibly busy/covered region.
    max_allowed = max(current_score * 1.75, current_score + 18.0)
    for zone, score in sorted(candidates, key=lambda item: order.index(item[0])):
        if score <= max_allowed:
            return zone
    return current
