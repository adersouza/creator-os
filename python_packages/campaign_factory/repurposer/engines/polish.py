from pathlib import Path
import subprocess

class PolishEngine:
    """Layer 4: Light technical polish (zoom, crop, color grade)."""
    
    @staticmethod
    def apply(video_path: Path, output_path: Path, zoom_factor: float = 1.05, color_shift: bool = True) -> Path:
        """Applies a subtle zoom and color grade using FFmpeg."""
        vf_filters = []
        
        if zoom_factor > 1.0:
            vf_filters.append(f"zoompan=z='{zoom_factor}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1")
            
        if color_shift:
            vf_filters.append("eq=contrast=1.05:brightness=0.02")
            
        if not vf_filters:
            return video_path
            
        filter_str = ",".join(vf_filters)
        cmd = [
            "ffmpeg", "-i", str(video_path), 
            "-vf", filter_str,
            "-c:a", "copy", "-y", str(output_path)
        ]
        
        subprocess.run(cmd, capture_output=True)
        return output_path
