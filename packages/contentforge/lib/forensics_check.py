#!/usr/bin/env python3
"""
Compression forensics checker for ContentForge.
Reports advisory double-compression, encoder-fingerprint, and GOP signals.
These heuristics are useful operator-review signals, not deterministic proof.
"""

import json
import os
import subprocess
import sys

try:
    import numpy as np
except ImportError as exc:
    np = None
    NUMPY_IMPORT_ERROR = str(exc)
else:
    NUMPY_IMPORT_ERROR = None

# ─── JPEG Forensics ───


def first_significant_digits(values):
    """Return first significant base-10 digits for non-zero numeric values."""
    digits = []
    for value in values:
        try:
            numeric = abs(int(value))
        except (TypeError, ValueError):
            continue
        if numeric == 0:
            continue
        while numeric >= 10:
            numeric //= 10
        digits.append(numeric)
    return digits


def advisory_check(payload):
    payload["advisory"] = True
    payload.setdefault("confidence", "heuristic")
    return payload


def analyze_jpeg(image_path):
    """Analyze a JPEG image for double compression artifacts."""
    results = {
        "file": os.path.basename(image_path),
        "type": "image",
        "checks": [],
    }

    # 1. DCT coefficient histogram periodicity (double compression "combing")
    try:
        import jpegio as jio

        jpg = jio.read(image_path)
        dct_y = jpg.coef_arrays[0].flatten()

        # Histogram of DCT coefficients
        hist, _ = np.histogram(dct_y, bins=range(-50, 51))
        hist = hist.astype(float)

        # DFT to detect periodic combing pattern
        if len(hist) > 4:
            spectrum = np.abs(np.fft.fft(hist - hist.mean()))
            # Skip DC component (index 0) and very low frequencies
            peak = float(np.max(spectrum[2:20]))
            mean = float(np.mean(spectrum[2:20]))
            periodicity_score = peak / mean if mean > 0 else 0

            results["checks"].append(
                advisory_check(
                    {
                        "name": "dct_periodicity",
                        "label": "Advisory DCT Histogram Periodicity",
                        "score": round(periodicity_score, 2),
                        "threshold": 3.0,
                        "pass": periodicity_score < 3.0,
                        "detail": "Heuristic score < 3.0 is typical; > 3.0 may warrant double-compression review",
                    }
                )
            )

        # 2. Benford's law on AC DCT coefficients
        ac_coeffs = dct_y[dct_y != 0]  # Exclude zeros
        if len(ac_coeffs) > 100:
            first_digits = np.array(first_significant_digits(ac_coeffs))
            if len(first_digits) > 100:
                # Expected Benford distribution
                expected = np.array([np.log10(1 + 1 / d) for d in range(1, 10)])
                # Observed distribution
                observed = np.array(
                    [np.sum(first_digits == d) for d in range(1, 10)], dtype=float
                )
                observed = observed / observed.sum() if observed.sum() > 0 else observed

                # Chi-squared divergence
                chi_sq = float(np.sum((observed - expected) ** 2 / (expected + 1e-10)))

                # Threshold calibrated empirically: normal single-compress JPEG scores 0.2-0.5
                # Double compression shifts to 0.4-0.8. Only flag extreme outliers (>1.0)
                results["checks"].append(
                    advisory_check(
                        {
                            "name": "benford_law",
                            "label": "Advisory Benford Leading-Digit Check",
                            "score": round(chi_sq, 4),
                            "threshold": 1.0,
                            "pass": chi_sq < 1.0,
                            "detail": "Chi-sq < 1.0 is typical; > 1.0 is an advisory manipulation-review signal",
                        }
                    )
                )

        # 3. Quantization table analysis
        qt = jpg.quant_tables[0] if len(jpg.quant_tables) > 0 else None
        if qt is not None:
            qt_flat = qt.flatten()
            # Standard JPEG luminance QT (Annex K)
            standard_qt = np.array(
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
                ]
            )

            if len(qt_flat) == 64:
                # Check if it's a scaled standard table
                ratios = qt_flat / (standard_qt + 1e-10)
                ratio_std = float(np.std(ratios))
                is_standard = ratio_std < 0.15  # Low variance = scaled standard table
                estimated_quality = max(1, min(100, int(100 - np.mean(qt_flat) * 0.8)))

                results["checks"].append(
                    advisory_check(
                        {
                            "name": "quantization_table",
                            "label": "Advisory Quantization Table",
                            "isStandard": is_standard,
                            "estimatedQuality": estimated_quality,
                            "pass": True,  # Informational
                            "detail": (
                                "Standard scaled table"
                                if is_standard
                                else "Custom table"
                            )
                            + ", est. quality "
                            + str(estimated_quality),
                        }
                    )
                )

    except ImportError:
        results["checks"].append(
            advisory_check(
                {
                    "name": "dct_periodicity",
                    "label": "Advisory DCT Analysis",
                    "pass": None,
                    "detail": "jpegio not installed",
                }
            )
        )
    except Exception as e:
        results["checks"].append(
            advisory_check(
                {
                    "name": "dct_error",
                    "label": "Advisory DCT Analysis",
                    "pass": None,
                    "detail": "Error: " + str(e),
                }
            )
        )

    return results


# ─── Video Forensics ───


def analyze_video(video_path):
    """Analyze H.264/H.265 video for double compression and encoder fingerprints."""
    results = {
        "file": os.path.basename(video_path),
        "type": "video",
        "checks": [],
    }

    # 1. GOP structure analysis + periodicity detection
    try:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-show_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=pict_type,pkt_size,key_frame",
            "-print_format",
            "json",
            video_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(proc.stdout)
        frames = data.get("frames", [])

        if len(frames) > 30:
            # Find I-frame positions
            i_positions = [
                i
                for i, f in enumerate(frames)
                if f.get("key_frame") == 1 or f.get("pict_type") == "I"
            ]
            gop_sizes = [
                i_positions[i + 1] - i_positions[i] for i in range(len(i_positions) - 1)
            ]

            avg_gop = float(np.mean(gop_sizes)) if gop_sizes else 0
            gop_std = float(np.std(gop_sizes)) if gop_sizes else 0

            results["checks"].append(
                advisory_check(
                    {
                        "name": "gop_structure",
                        "label": "Advisory GOP Structure",
                        "avgGop": round(avg_gop, 1),
                        "gopStd": round(gop_std, 1),
                        "isFixed": gop_std < 2.0,
                        "pass": True,  # Informational
                        "detail": "Avg GOP: "
                        + str(round(avg_gop, 1))
                        + " (std: "
                        + str(round(gop_std, 1))
                        + ")"
                        + (
                            " — fixed interval (device-like)"
                            if gop_std < 2.0
                            else " — variable (software encoder)"
                        ),
                    }
                )
            )

            # DFT of frame sizes to detect original GOP periodicity
            sizes = np.array([int(f.get("pkt_size", 0)) for f in frames], dtype=float)
            if len(sizes) > 64:
                spectrum = np.abs(np.fft.fft(sizes - sizes.mean()))
                freqs = np.fft.fftfreq(len(sizes))
                # Look for peaks in the spectrum (skip DC and very low freq)
                half = len(sizes) // 2
                if half > 3:
                    peak_idx = np.argmax(spectrum[2:half]) + 2
                    peak_freq = abs(freqs[peak_idx])
                    implied_gop = int(round(1.0 / peak_freq)) if peak_freq > 0 else 0
                    peak_strength = float(
                        spectrum[peak_idx] / np.mean(spectrum[2:half])
                    )

                    # If implied GOP differs significantly from actual, suggests re-encoding
                    gop_mismatch = (
                        implied_gop > 0
                        and len(gop_sizes) > 0
                        and abs(implied_gop - avg_gop) > 3
                    )

                    results["checks"].append(
                        advisory_check(
                            {
                                "name": "gop_periodicity",
                                "label": "Advisory GOP Periodicity",
                                "impliedOriginalGop": implied_gop,
                                "currentGop": round(avg_gop, 1),
                                "peakStrength": round(peak_strength, 2),
                                "mismatch": gop_mismatch,
                                "pass": not gop_mismatch,
                                "detail": (
                                    "Heuristic GOP mismatch signal: implied original="
                                    + str(implied_gop)
                                    + ", current="
                                    + str(round(avg_gop, 1))
                                    + " — review for possible re-encoding"
                                )
                                if gop_mismatch
                                else "No advisory GOP mismatch signal",
                            }
                        )
                    )

            # Frame type distribution
            pict_types = [f.get("pict_type", "?") for f in frames]
            type_counts = {}
            for t in pict_types:
                type_counts[t] = type_counts.get(t, 0) + 1

            has_b_frames = type_counts.get("B", 0) > 0

            results["checks"].append(
                advisory_check(
                    {
                        "name": "frame_types",
                        "label": "Advisory Frame Type Distribution",
                        "distribution": type_counts,
                        "hasBFrames": has_b_frames,
                        "pass": True,  # Informational
                        "detail": "I:"
                        + str(type_counts.get("I", 0))
                        + " P:"
                        + str(type_counts.get("P", 0))
                        + " B:"
                        + str(type_counts.get("B", 0))
                        + (
                            " — B-frames present (iPhone-like)"
                            if has_b_frames
                            else " — No B-frames (Android-like)"
                        ),
                    }
                )
            )

    except Exception as e:
        results["checks"].append(
            advisory_check(
                {
                    "name": "gop_error",
                    "label": "Advisory GOP Analysis",
                    "pass": None,
                    "detail": "Error: " + str(e),
                }
            )
        )

    # 2. Encoder identification via mediainfo
    try:
        cmd = ["mediainfo", "--Output=JSON", video_path]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.stdout:
            mi_data = json.loads(proc.stdout)
            for track in mi_data.get("media", {}).get("track", []):
                if track.get("@type") == "Video":
                    encoder = track.get("Encoded_Library", "")
                    encoder_settings = track.get("Encoded_Library_Settings", "")
                    writing_lib = track.get("Writing_library", "")

                    # Check for x264/FFmpeg signatures
                    all_encoder_info = (
                        encoder + " " + encoder_settings + " " + writing_lib
                    ).lower()
                    has_x264 = "x264" in all_encoder_info
                    has_ffmpeg = (
                        "lavf" in all_encoder_info
                        or "lavc" in all_encoder_info
                        or "ffmpeg" in all_encoder_info
                    )

                    results["checks"].append(
                        advisory_check(
                            {
                                "name": "encoder_id",
                                "label": "Advisory Encoder Identification",
                                "encoder": encoder or "Unknown",
                                "hasX264Sig": has_x264,
                                "hasFFmpegSig": has_ffmpeg,
                                "pass": not has_x264 and not has_ffmpeg,
                                "detail": (
                                    "x264/FFmpeg encoder signal detected: "
                                    + (encoder or writing_lib)
                                )
                                if (has_x264 or has_ffmpeg)
                                else ("Encoder: " + (encoder or "Unknown/Hardware")),
                            }
                        )
                    )

                    # Check encoding settings for x264 parameter string
                    if encoder_settings:
                        results["checks"].append(
                            advisory_check(
                                {
                                    "name": "encoder_settings",
                                    "label": "Advisory Encoder Settings",
                                    "settings": encoder_settings[
                                        :200
                                    ],  # Truncate for readability
                                    "pass": False,
                                    "detail": "x264 parameter string exposed via SEI; review as an encoder fingerprint signal",
                                }
                            )
                        )
                    break

                if track.get("@type") == "Audio":
                    audio_rate = track.get("SamplingRate", "")
                    audio_codec = track.get("Format", "")
                    results["checks"].append(
                        advisory_check(
                            {
                                "name": "audio_format",
                                "label": "Advisory Audio Format",
                                "sampleRate": audio_rate,
                                "codec": audio_codec,
                                "pass": True,
                                "detail": audio_codec + " @ " + str(audio_rate) + " Hz",
                            }
                        )
                    )

    except Exception as e:
        results["checks"].append(
            advisory_check(
                {
                    "name": "mediainfo_error",
                    "label": "Advisory MediaInfo Analysis",
                    "pass": None,
                    "detail": "Error: " + str(e),
                }
            )
        )

    # 3. Check for x264 UUID SEI in binary
    try:
        # The x264 UUID: dc45e9bd-e6d9-48b7-962c-d820d923eeef
        with open(video_path, "rb") as f:
            # Read first 50KB where SEI typically lives
            data = f.read(50 * 1024)
            x264_uuid = bytes(
                [
                    0xDC,
                    0x45,
                    0xE9,
                    0xBD,
                    0xE6,
                    0xD9,
                    0x48,
                    0xB7,
                    0x96,
                    0x2C,
                    0xD8,
                    0x20,
                    0xD9,
                    0x23,
                    0xEE,
                    0xEF,
                ]
            )
            has_sei_uuid = x264_uuid in data

            results["checks"].append(
                advisory_check(
                    {
                        "name": "x264_sei",
                        "label": "Advisory x264 SEI UUID",
                        "found": has_sei_uuid,
                        "pass": not has_sei_uuid,
                        "detail": (
                            "x264 UUID SEI found in bitstream; review as a software-encoding signal"
                        )
                        if has_sei_uuid
                        else "No x264 SEI UUID detected",
                    }
                )
            )
    except Exception as e:
        results["checks"].append(
            advisory_check(
                {
                    "name": "sei_error",
                    "label": "Advisory SEI Analysis",
                    "pass": None,
                    "detail": "Error: " + str(e),
                }
            )
        )

    return results


# ─── Main ───


def main():
    if len(sys.argv) < 2:
        print(
            json.dumps({"error": "Usage: forensics_check.py <output_dir> [max_files]"})
        )
        sys.exit(1)

    output_dir = sys.argv[1]
    max_files = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    if not os.path.isdir(output_dir):
        print(json.dumps({"error": f"Directory not found: {output_dir}"}))
        sys.exit(1)

    if np is None:
        print(
            json.dumps(
                {
                    "available": False,
                    "error": "Missing Python dependency: numpy",
                    "reason": "Install ContentForge Python audit dependencies.",
                    "detail": NUMPY_IMPORT_ERROR,
                    "reports": [],
                    "summary": {
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "warnings": 1,
                        "unavailable": 1,
                        "passRate": 0,
                    },
                }
            )
        )
        sys.exit(0)

    supported_video = {".mp4", ".mov", ".webm"}
    supported_image = {".jpg", ".jpeg"}
    all_supported = supported_video | supported_image | {".png"}

    files = sorted(
        [
            f
            for f in os.listdir(output_dir)
            if os.path.splitext(f)[1].lower() in all_supported and not f.startswith(".")
        ]
    )[:max_files]

    reports = []
    summary = {"total": 0, "passed": 0, "failed": 0, "warnings": 0}

    for fname in files:
        fpath = os.path.join(output_dir, fname)
        ext = os.path.splitext(fname)[1].lower()

        if ext in supported_image:
            report = analyze_jpeg(fpath)
        elif ext in supported_video:
            report = analyze_video(fpath)
        else:
            continue

        # Compute per-file verdict
        checks = report.get("checks", [])
        fails = sum(1 for c in checks if c.get("pass") is False)
        passes = sum(1 for c in checks if c.get("pass") is True)

        report["verdict"] = "fail" if fails > 0 else "pass"
        report["failCount"] = fails
        report["passCount"] = passes
        reports.append(report)

        summary["total"] += 1
        if fails > 0:
            summary["failed"] += 1
        else:
            summary["passed"] += 1

    summary["passRate"] = (
        round((summary["passed"] / summary["total"]) * 100)
        if summary["total"] > 0
        else 0
    )

    print(json.dumps({"reports": reports, "summary": summary}))


if __name__ == "__main__":
    main()
