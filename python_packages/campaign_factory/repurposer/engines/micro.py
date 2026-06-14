from pathlib import Path

from .common import ensure_input_file, run_ffmpeg

class MicroEngine:
    """Layer 5: Micro technical spoofing (metadata stripping, pixel noise)."""
    
    @staticmethod
    def apply(video_path: Path, output_path: Path, strip_metadata: bool = True, inject_noise: bool = True) -> Path:
        """Strips metadata and injects invisible pixel noise to spoof hashes."""
        ensure_input_file(video_path, label="video")
        cmd = ["ffmpeg", "-i", str(video_path)]
        
        if inject_noise:
            # Add barely visible noise to change bit-level hashes
            cmd.extend(["-vf", "noise=alls=1:allf=t"])
            
        if strip_metadata:
            cmd.extend(["-map_metadata", "-1"])
            
        # Use copy if no noise was injected to save time
        if not inject_noise:
            cmd.extend(["-c", "copy"])
            
        cmd.extend(["-y", str(output_path)])
        
        return run_ffmpeg(cmd, output_path=output_path)
