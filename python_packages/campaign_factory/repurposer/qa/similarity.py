from pathlib import Path
import subprocess
import tempfile
import imagehash
from PIL import Image

class SimilarityGate:
    """Evaluates how visually and structurally distinct two videos are."""
    
    @staticmethod
    def extract_keyframes(video_path: Path, count: int = 5) -> list[Image.Image]:
        """Extract keyframes evenly spaced from the video."""
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"video not found: {video_path}")
        count = max(1, count)
        with tempfile.TemporaryDirectory(prefix="repurpose_keyframes_") as tmp:
            out_pattern = Path(tmp) / "frame_%03d.jpg"
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-vf",
                f"fps={count},scale=320:-1",
                "-frames:v",
                str(count),
                "-q:v",
                "3",
                str(out_pattern),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "ffmpeg keyframe extraction failed").strip()
                raise RuntimeError(detail)
            frames: list[Image.Image] = []
            for frame_path in sorted(Path(tmp).glob("frame_*.jpg"))[:count]:
                with Image.open(frame_path) as image:
                    frames.append(image.convert("RGB").copy())
            if not frames:
                raise RuntimeError(f"no keyframes extracted from {video_path}")
            return frames

    @staticmethod
    def calculate_phash_distance(master: Path, variant: Path) -> float:
        """Compare perceptual hashes of keyframes. Higher is more distinct."""
        master_frames = SimilarityGate.extract_keyframes(master)
        variant_frames = SimilarityGate.extract_keyframes(variant)
        distances: list[float] = []
        for left, right in zip(master_frames, variant_frames):
            distances.append(float(imagehash.phash(left) - imagehash.phash(right)))
        if not distances:
            raise RuntimeError("no comparable keyframes for pHash distance")
        return sum(distances) / len(distances)
        
    @staticmethod
    def calculate_ssim(master: Path, variant: Path) -> float:
        """Calculate Structural Similarity Index between two videos using FFmpeg."""
        cmd = [
            "ffmpeg", "-i", str(master), "-i", str(variant),
            "-filter_complex", "ssim", "-f", "null", "-"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            # Parse SSIM from stderr (e.g., "SSIM Y:0.89 U:0.92 V:0.93 All:0.90")
            for line in result.stderr.split('\n'):
                if "SSIM" in line and "All:" in line:
                    parts = line.split("All:")
                    return float(parts[1].split()[0])
            return 1.0 # If identical or failed
        except Exception:
            return 1.0

    @classmethod
    def is_distinct_enough(cls, master: Path, variant: Path, threshold: float = 0.85) -> bool:
        """
        Check if the variant is different enough from the master.
        For SSIM, lower means MORE distinct. We want SSIM < threshold.
        """
        ssim_score = cls.calculate_ssim(master, variant)
        print(f"Similarity SSIM Score: {ssim_score} (Threshold: {threshold})")
        return ssim_score < threshold
