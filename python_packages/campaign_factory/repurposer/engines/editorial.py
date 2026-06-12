from pathlib import Path

from .common import ensure_input_file, run_ffmpeg

class EditorialEngine:
    """Layer 1: Structural changes. Handles re-ordering and hooking."""
    
    @staticmethod
    def extract_scenes(video_path: Path, out_dir: Path) -> list[Path]:
        """Uses PySceneDetect (mocked) to cut the video into clips."""
        # For a full implementation, we'd use: 
        # scenedetect -i video.mp4 detect-content split-video
        out_file = out_dir / f"scene_001.mp4"
        return [video_path] # Mock: return original for now
        
    @staticmethod
    def apply(master_path: Path, output_path: Path, new_hook: bool = True, reorder: bool = True) -> Path:
        """Apply structural changes."""
        ensure_input_file(master_path, label="master")
        # V1 preserves the original scene order until a real scene splitter is wired.
        cmd = ["ffmpeg", "-i", str(master_path), "-c", "copy", "-y", str(output_path)]
        return run_ffmpeg(cmd, output_path=output_path)
