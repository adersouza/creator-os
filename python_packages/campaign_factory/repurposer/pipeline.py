from pathlib import Path
from typing import List
import shutil

from .config import RepurposeConfig
from .engines.audio import AudioEngine
from .engines.editorial import EditorialEngine
from .engines.micro import MicroEngine
from .engines.polish import PolishEngine
from .engines.visual import VisualEngine
from .qa.quality import QualityGate
from .qa.similarity import SimilarityGate


class RepurposeError(RuntimeError):
    """Raised when a repurposing run cannot produce a valid real variant."""

class VariantPipeline:
    def __init__(self, master_asset: Path, target_count: int, platform: str, output_dir: Path | None = None):
        self.master = Path(master_asset)
        self.target = target_count
        self.platform = platform
        self.output_dir = Path(output_dir) if output_dir else self.master.parent / "repurposed_variants"
        
    def generate_batch(self, preset_name: str) -> List[Path]:
        if not self.master.exists() or not self.master.is_file():
            raise FileNotFoundError(f"master asset not found: {self.master}")
        if self.target <= 0:
            raise ValueError("target_count must be positive")

        config = RepurposeConfig.from_preset(preset_name)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        variants: list[Path] = []
        
        print(f"Generating {self.target} variants for {self.platform} using preset {preset_name}")
        
        for i in range(self.target):
            try:
                variant = self._generate_one(config, i)
            except Exception as exc:
                for created in variants:
                    created.unlink(missing_ok=True)
                raise RepurposeError(f"variant {i} failed: {exc}") from exc
            variants.append(variant)

        return variants

    def _generate_one(self, config: RepurposeConfig, index: int) -> Path:
        stage_dir = self.output_dir / f".tmp_{self.master.stem}_{index:03d}"
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True)
        current = self.master
        transformed = False

        try:
            if config.enable_editorial:
                print(f"Applying Layer 1 (Editorial) to variant {index}")
                current = EditorialEngine.apply(
                    current,
                    stage_dir / "01_editorial.mp4",
                    new_hook=config.new_hook,
                    reorder=config.reorder_broll,
                )
                transformed = True

            if config.enable_audio:
                print(f"Applying Layer 2 (Audio) to variant {index}")
                current = AudioEngine.apply(
                    current,
                    stage_dir / "02_audio.mp4",
                    music_track=Path(config.music_track_path) if config.music_track_path else None,
                    voiceover=Path(config.voiceover_path) if config.voiceover_path else None,
                    platform=self.platform,
                )
                transformed = transformed or current != self.master

            if config.enable_generative:
                print(f"Applying Layer 3 (Visual Generative) to variant {index}")
                current = VisualEngine.apply(
                    current,
                    stage_dir / "03_visual.mp4",
                    prompt=config.generative_prompt,
                )
                transformed = transformed or current != self.master

            if config.enable_polish:
                print(f"Applying Layer 4 (Polish) to variant {index}")
                current = PolishEngine.apply(
                    current,
                    stage_dir / "04_polish.mp4",
                    zoom_factor=config.zoom_factor,
                    color_shift=config.color_shift,
                )
                transformed = transformed or current != self.master

            if config.enable_micro:
                print(f"Applying Layer 5 (Micro) to variant {index}")
                current = MicroEngine.apply(
                    current,
                    stage_dir / "05_micro.mp4",
                    strip_metadata=config.strip_metadata,
                    inject_noise=config.inject_noise,
                )
                transformed = transformed or current != self.master

            final = self.output_dir / f"{self.master.stem}_repurpose_{index:03d}.mp4"
            shutil.copy2(current, final)
            if not final.exists() or final.stat().st_size <= 0:
                raise RuntimeError(f"variant output missing: {final}")

            print(f"Running Similarity & Quality QA on variant {index}")
            if not QualityGate.is_quality_acceptable(final):
                final.unlink(missing_ok=True)
                raise RuntimeError("quality gate failed")
            if transformed and not SimilarityGate.is_distinct_enough(self.master, final):
                final.unlink(missing_ok=True)
                raise RuntimeError("similarity gate failed")

            return final
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)
