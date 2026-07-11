#!/usr/bin/env python3
"""
JPEG quantization table randomizer for ContentForge.
Re-saves JPEG images with slightly randomized quantization tables
to add forensic entropy — each variant gets a unique QT fingerprint.

Research: Identical QTs across a batch indicate common-origin processing.
Randomizing QTs makes each image appear to come from a different device/software.
"""

import json
import os
import sys

import numpy as np
from PIL import Image

# Standard JPEG luminance quantization table (Annex K)
STANDARD_QT_LUMA = np.array(
    [
        16,
        11,
        10,
        16,
        24,
        40,
        51,
        61,
        12,
        12,
        14,
        19,
        26,
        58,
        60,
        55,
        14,
        13,
        16,
        24,
        40,
        57,
        69,
        56,
        14,
        17,
        22,
        29,
        51,
        87,
        80,
        62,
        18,
        22,
        37,
        56,
        68,
        109,
        103,
        77,
        24,
        35,
        55,
        64,
        81,
        104,
        113,
        92,
        49,
        64,
        78,
        87,
        103,
        121,
        120,
        101,
        72,
        92,
        95,
        98,
        112,
        100,
        103,
        99,
    ],
    dtype=np.uint16,
).reshape(8, 8)

STANDARD_QT_CHROMA = np.array(
    [
        17,
        18,
        24,
        47,
        99,
        99,
        99,
        99,
        18,
        21,
        26,
        66,
        99,
        99,
        99,
        99,
        24,
        26,
        56,
        99,
        99,
        99,
        99,
        99,
        47,
        66,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
        99,
    ],
    dtype=np.uint16,
).reshape(8, 8)


def generate_random_qt(base_qt, quality_factor, noise_pct=0.05):
    """
    Generate a randomized quantization table based on a base table.

    quality_factor: 1-100 (higher = better quality, lower QT values)
    noise_pct: amount of random perturbation (0.05 = ±5%)
    """
    # Scale base QT by quality factor (JPEG standard scaling)
    if quality_factor < 50:
        scale = 5000 / quality_factor
    else:
        scale = 200 - 2 * quality_factor

    qt = np.floor((base_qt * scale + 50) / 100).astype(np.uint16)
    qt = np.clip(qt, 1, 255)

    # Add random perturbation (±noise_pct)
    noise = np.random.uniform(1 - noise_pct, 1 + noise_pct, qt.shape)
    qt = np.floor(qt * noise).astype(np.uint16)
    qt = np.clip(qt, 1, 255)

    return qt


def randomize_jpeg_qt(
    input_path, output_path=None, quality_range=(85, 95), noise_pct=0.05
):
    """
    Re-save a JPEG with randomized quantization tables.
    Uses PIL to re-encode with a random quality in the given range,
    which produces different QTs per image.

    Returns dict with results.
    """
    if output_path is None:
        output_path = input_path

    try:
        img = Image.open(input_path)

        # Random quality within range
        quality = np.random.randint(quality_range[0], quality_range[1] + 1)

        # Generate custom QTs
        luma_qt = generate_random_qt(STANDARD_QT_LUMA, quality, noise_pct)
        chroma_qt = generate_random_qt(STANDARD_QT_CHROMA, quality, noise_pct)

        # PIL doesn't support custom QTs directly, but we can use
        # the qtables parameter in save() with a list of QT arrays
        # Convert to flat lists as PIL expects
        qtables = [luma_qt.flatten().tolist(), chroma_qt.flatten().tolist()]

        # Re-save with custom quantization tables
        img.save(
            output_path,
            format="JPEG",
            quality=quality,
            qtables=qtables,
            optimize=False,  # Don't optimize — introduces its own fingerprint
            subsampling="4:2:0",
        )

        return {
            "file": os.path.basename(output_path),
            "quality": quality,
            "qtRandomized": True,
            "error": None,
        }
    except Exception as e:
        return {
            "file": os.path.basename(input_path),
            "quality": None,
            "qtRandomized": False,
            "error": str(e),
        }


def main():
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "error": "Usage: jpeg_randomize_qt.py <file_or_directory> [quality_min] [quality_max]"
                }
            )
        )
        sys.exit(1)

    target = sys.argv[1]
    q_min = int(sys.argv[2]) if len(sys.argv) > 2 else 85
    q_max = int(sys.argv[3]) if len(sys.argv) > 3 else 95

    results = []

    if os.path.isdir(target):
        files = sorted(
            [
                os.path.join(target, f)
                for f in os.listdir(target)
                if os.path.splitext(f)[1].lower() in (".jpg", ".jpeg")
                and not f.startswith(".")
            ]
        )
    elif os.path.isfile(target):
        files = [target]
    else:
        print(json.dumps({"error": f"Not found: {target}"}))
        sys.exit(1)

    for filepath in files:
        result = randomize_jpeg_qt(filepath, quality_range=(q_min, q_max))
        results.append(result)

    success_count = sum(1 for r in results if r.get("qtRandomized"))
    print(
        json.dumps(
            {
                "results": results,
                "summary": {
                    "total": len(results),
                    "randomized": success_count,
                    "qualityRange": [q_min, q_max],
                },
            }
        )
    )


if __name__ == "__main__":
    main()
