from pathlib import Path
import subprocess

class AudioEngine:
    """Layer 2: Audio replacement and mixing."""
    
    @staticmethod
    def apply(video_path: Path, output_path: Path, music_track: Path = None, voiceover: Path = None) -> Path:
        """Strips original audio and injects new audio."""
        if not music_track and not voiceover:
            return video_path # Nothing to do
            
        if music_track:
            # Map video from input 0, audio from input 1
            cmd = [
                "ffmpeg", "-i", str(video_path), "-i", str(music_track),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-shortest", "-y", str(output_path)
            ]
            subprocess.run(cmd, capture_output=True)
            return output_path
            
        return video_path
