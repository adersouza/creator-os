from pathlib import Path
from importlib import import_module

from .common import ensure_input_file, run_ffmpeg

class AudioEngine:
    """Layer 2: Audio replacement and mixing."""
    
    @staticmethod
    def apply(video_path: Path, output_path: Path, music_track: Path = None, voiceover: Path = None, platform: str = "tiktok") -> Path:
        """Strips original audio and injects new audio."""
        ensure_input_file(video_path, label="video")
        
        # If no track is explicitly passed, try to fetch a trending one
        get_connection, recommend_audio = _reference_audio_helpers()
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
            ensure_input_file(music_track, label="music track")
            # Map video from input 0, audio from input 1
            cmd = [
                "ffmpeg", "-i", str(video_path), "-i", str(music_track),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-shortest", "-y", str(output_path)
            ]
            return run_ffmpeg(cmd, output_path=output_path)
            
        return video_path


def _reference_audio_helpers():
    try:
        db_module = import_module("reference_factory.db")
        audio_module = import_module("reference_factory.audio")
    except ImportError:
        return None, None
    return getattr(db_module, "get_connection", None), getattr(audio_module, "recommend_audio", None)
