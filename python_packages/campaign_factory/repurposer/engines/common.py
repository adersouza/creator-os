from __future__ import annotations

import subprocess
from pathlib import Path


def ensure_input_file(path: Path, *, label: str = "input") -> Path:
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} file not found: {path}")
    if path.stat().st_size <= 0:
        raise ValueError(f"{label} file is empty: {path}")
    return path


def run_ffmpeg(cmd: list[str], *, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg command failed").strip()
        raise RuntimeError(detail)
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"ffmpeg completed but did not create output: {output_path}")
    return output_path
