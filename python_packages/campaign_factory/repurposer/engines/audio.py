from pathlib import Path
import subprocess

try:
    from reference_factory.db import get_connection
    from reference_factory.audio import recommend_audio
except ImportError:
    get_connection = None
    recommend_audio = None

class AudioEngine:
    """Layer 2: Audio replacement and mixing."""
    
    @staticmethod
    def apply(video_path: Path, output_path: Path, music_track: Path = None, voiceover: Path = None, platform: str = "tiktok") -> Path:
        """Strips original audio and injects new audio."""
        
        # If no track is explicitly passed, try to fetch a trending one
        if not music_track and get_connection and recommend_audio:
            try:
                conn = get_connection(video_path.parent) # Root config/db lookup
                result = recommend_audio(conn, platform=platform, limit=1)
                recs = result.get("recommendations", [])
                if recs and recs[0].get("localPreviewPath"):
                    candidate_path = Path(recs[0]["localPreviewPath"])
                    if candidate_path.exists():
                        print(f"[AudioEngine] Sourced trending audio: {recs[0].get('title')} ({candidate_path.name})")
                        music_track = candidate_path
            except Exception as exc:
                print(f"[AudioEngine] Failed to source dynamic trending audio: {exc}")
                
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
