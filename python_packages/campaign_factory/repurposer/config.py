import dataclasses
from typing import Optional

@dataclasses.dataclass
class RepurposeConfig:
    """Constraints and logic configuration for a given variant generation run."""
    target_platform: str  # "reels", "tiktok", "shorts"
    aggressiveness: float # 0.0 to 1.0 (how heavy the spoofing and re-ordering should be)
    
    # Layer 1: Editorial
    enable_editorial: bool = True
    new_hook: bool = True
    reorder_broll: bool = True
    
    # Layer 2: Audio
    enable_audio: bool = True
    music_track_path: Optional[str] = None
    voiceover_path: Optional[str] = None
    
    # Layer 3: Visual Generative
    enable_generative: bool = False
    generative_prompt: Optional[str] = None
    
    # Layer 4: Polish
    enable_polish: bool = True
    zoom_factor: float = 1.05
    color_shift: bool = True
    
    # Layer 5: Micro
    enable_micro: bool = False
    strip_metadata: bool = True
    inject_noise: bool = True
    
    @classmethod
    def from_preset(cls, preset_name: str) -> "RepurposeConfig":
        if preset_name == "tiktok_aggressive":
            return cls(
                target_platform="tiktok",
                aggressiveness=0.9,
                enable_editorial=True,
                new_hook=True,
                reorder_broll=True,
                enable_audio=True,
                enable_generative=True,
                enable_polish=True,
                zoom_factor=1.1,
                color_shift=True,
                enable_micro=False,
                strip_metadata=True,
                inject_noise=True
            )
        elif preset_name == "ig_subtle":
            return cls(
                target_platform="reels",
                aggressiveness=0.3,
                enable_editorial=True,
                new_hook=False,
                reorder_broll=True,
                enable_audio=False,
                enable_generative=False,
                enable_polish=True,
                zoom_factor=1.02,
                color_shift=False,
                enable_micro=False,
                strip_metadata=True,
                inject_noise=False
            )
        return cls(target_platform="reels", aggressiveness=0.5, enable_micro=False)
