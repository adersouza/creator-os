from pathlib import Path
import subprocess
import json
import imagehash
from PIL import Image

class SimilarityGate:
    """Evaluates how visually and structurally distinct two videos are."""
    
    @staticmethod
    def extract_keyframes(video_path: Path, count: int = 5) -> list[Image.Image]:
        """Extract keyframes evenly spaced from the video."""
        # Simple implementation for now: extract first frame
        # In a real implementation we'd use FFmpeg to extract N frames
        return []

    @staticmethod
    def calculate_phash_distance(master: Path, variant: Path) -> float:
        """Compare perceptual hashes of keyframes. Higher is more distinct."""
        # Placeholder for actual pHash comparison logic
        return 0.5
        
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
