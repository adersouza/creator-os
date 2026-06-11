#!/usr/bin/env python3
"""
C2PA and IPTC AI provenance scanner for ContentForge.
Detects AI-generation metadata that would trigger Instagram's "AI Info" label.

Instagram's dual-signal approach:
1. C2PA manifests (claim_generator, digitalSourceType)
2. IPTC DigitalSourceType XMP fields

If either signals AI-generated content, Instagram adds the "AI Info" label,
which reduces algorithmic distribution.
"""

import sys
import json
import os
import subprocess

# AI-related IPTC DigitalSourceType values that trigger platform labels
AI_SOURCE_TYPES = {
    "trainedAlgorithmicMedia",           # Fully AI-generated
    "compositeWithTrainedAlgorithmicMedia",  # AI-enhanced
    "algorithmicMedia",                   # Algorithmically generated
}

# Known AI generator strings in C2PA claim_generator fields
AI_GENERATORS = [
    "dall-e", "dall·e", "openai",
    "midjourney",
    "stable diffusion", "stability",
    "firefly", "adobe firefly",
    "imagen", "google",
    "meta ai", "imagine with meta",
    "flux",
]


def check_c2pa(filepath):
    """Check for C2PA content credentials manifest."""
    try:
        import c2pa
        reader = c2pa.Reader.from_file(filepath)
        manifest = reader.get_active_manifest()
        if manifest is None:
            return {"found": False, "detail": "No C2PA manifest"}

        # Parse manifest for AI signals
        manifest_json = json.loads(manifest.json()) if hasattr(manifest, 'json') else {}
        claim_gen = manifest_json.get("claim_generator", "")
        assertions = manifest_json.get("assertions", [])

        is_ai = False
        signals = []

        # Check claim_generator for known AI tools
        claim_gen_lower = claim_gen.lower()
        for gen in AI_GENERATORS:
            if gen in claim_gen_lower:
                is_ai = True
                signals.append(f"claim_generator contains '{gen}'")

        # Check assertions for digitalSourceType
        for assertion in assertions:
            label = assertion.get("label", "")
            data = assertion.get("data", {})
            if "digitalSourceType" in str(data):
                src_type = data.get("digitalSourceType", "")
                if src_type in AI_SOURCE_TYPES:
                    is_ai = True
                    signals.append(f"digitalSourceType: {src_type}")

            # Check for c2pa.actions with AI-related actions
            if label == "c2pa.actions":
                actions = data.get("actions", [])
                for action in actions:
                    if action.get("action") == "c2pa.created":
                        software = action.get("softwareAgent", "")
                        for gen in AI_GENERATORS:
                            if gen in software.lower():
                                is_ai = True
                                signals.append(f"softwareAgent: {software}")

        return {
            "found": True,
            "isAI": is_ai,
            "claimGenerator": claim_gen,
            "signals": signals,
            "detail": "C2PA manifest found" + (" — AI generation detected" if is_ai else " — no AI signals"),
        }
    except ImportError as e:
        return {
            "found": False,
            "available": False,
            "optional": True,
            "detail": "c2pa Python package not installed",
            "error": str(e),
        }
    except Exception as e:
        err_str = str(e)
        if "from_file" in err_str or "attribute" in err_str:
            return {
                "found": False,
                "available": False,
                "optional": True,
                "detail": "c2pa Python package API unavailable",
                "error": err_str,
            }
        if "no manifest" in err_str.lower() or "not found" in err_str.lower() or "jumbf" in err_str.lower():
            return {"found": False, "detail": "No C2PA manifest"}
        return {"found": False, "detail": f"C2PA check error: {err_str}"}


def check_iptc_xmp(filepath):
    """Check IPTC/XMP metadata for AI generation signals via exiftool."""
    try:
        cmd = [
            "exiftool", "-j", "-a",
            "-DigitalSourceType",
            "-Iptc4xmpExt:DigitalSourceType",
            "-XMP-photoshop:Credit",
            "-XMP-plus:ImageCreatorName",
            "-Software",
            "-CreatorTool",
            "-Description",
            filepath
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0 or not proc.stdout.strip():
            return {"found": False, "detail": "No IPTC/XMP metadata (exiftool)"}

        data = json.loads(proc.stdout)
        if not data:
            return {"found": False, "detail": "No IPTC/XMP metadata"}

        meta = data[0]
        metadata = {k: v for k, v in meta.items() if v and k != "SourceFile"}
        if not metadata:
            return {"found": False, "detail": "No IPTC/XMP metadata"}
        is_ai = False
        signals = []

        # Check DigitalSourceType
        for key in ["DigitalSourceType", "Iptc4xmpExt:DigitalSourceType"]:
            val = meta.get(key, "")
            if val and val in AI_SOURCE_TYPES:
                is_ai = True
                signals.append(f"{key}: {val}")

        # Check Software/CreatorTool for AI tools
        for key in ["Software", "CreatorTool"]:
            val = str(meta.get(key, "")).lower()
            for gen in AI_GENERATORS:
                if gen in val:
                    is_ai = True
                    signals.append(f"{key} contains '{gen}'")

        return {
            "found": True,
            "isAI": is_ai,
            "signals": signals,
            "metadata": metadata,
            "detail": "IPTC/XMP metadata found" + (" — AI signals detected" if is_ai else " — clean"),
        }
    except FileNotFoundError:
        return {"found": False, "available": False, "optional": True, "detail": "exiftool not installed"}
    except Exception as e:
        return {"found": False, "detail": f"IPTC check error: {str(e)}"}


def check_png_chunks(filepath):
    """Check PNG text chunks for Stable Diffusion / ComfyUI generation params."""
    if not filepath.lower().endswith(".png"):
        return {"found": False, "detail": "Not a PNG file"}

    try:
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo

        img = Image.open(filepath)
        info = img.info or {}

        ai_signals = []
        sd_keys = ["parameters", "prompt", "negative_prompt", "Steps", "Sampler",
                    "CFG scale", "Seed", "Model", "workflow", "comfyui"]

        for key in sd_keys:
            if key.lower() in {k.lower() for k in info.keys()}:
                ai_signals.append(f"PNG chunk '{key}' found (Stable Diffusion/ComfyUI)")

        return {
            "found": len(ai_signals) > 0,
            "isAI": len(ai_signals) > 0,
            "signals": ai_signals,
            "detail": "SD/ComfyUI parameters detected in PNG chunks" if ai_signals else "No AI chunks in PNG",
        }
    except Exception as e:
        if isinstance(e, ImportError):
            return {"found": False, "available": False, "optional": True, "detail": "Pillow not installed", "error": str(e)}
        return {"found": False, "detail": f"PNG check error: {str(e)}"}


def check_container_metadata(filepath):
    """Inspect regular container metadata for provenance clues and contradictions."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            filepath,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0 or not proc.stdout.strip():
            return {"found": False, "available": False, "detail": "ffprobe metadata unavailable"}

        data = json.loads(proc.stdout)
        format_tags = data.get("format", {}).get("tags", {}) or {}
        stream_tags = {}
        for stream in data.get("streams", []):
            for key, value in (stream.get("tags", {}) or {}).items():
                stream_tags[f"stream_{stream.get('index', 0)}_{key}"] = value

        tags = {**format_tags, **stream_tags}
        haystack = " ".join(str(value) for value in tags.values()).lower()
        signals = []
        for generator in AI_GENERATORS:
            if generator in haystack:
                signals.append(f"metadata contains '{generator}'")

        has_creation_time = any("creation_time" in key.lower() and value for key, value in tags.items())
        has_encoder = any("encoder" in key.lower() and value for key, value in tags.items())
        has_handler = any("handler_name" in key.lower() and value for key, value in tags.items())

        return {
            "found": bool(tags),
            "isAI": bool(signals),
            "signals": signals,
            "metadataPresence": {
                "creationTime": has_creation_time,
                "encoder": has_encoder,
                "handlerName": has_handler,
            },
            "detail": "Container metadata inspected" + (" — AI signals detected" if signals else ""),
        }
    except Exception as e:
        return {"found": False, "detail": f"Container metadata check error: {str(e)}"}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: provenance_check.py <file_or_directory> [max_files]"}))
        sys.exit(1)

    target = sys.argv[1]
    max_files = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    supported = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"}

    if os.path.isdir(target):
        files = sorted([
            os.path.join(target, f) for f in os.listdir(target)
            if os.path.splitext(f)[1].lower() in supported and not f.startswith(".")
        ])[:max_files]
    elif os.path.isfile(target):
        files = [target]
    else:
        print(json.dumps({"error": f"Not found: {target}"}))
        sys.exit(1)

    results = []
    flagged_count = 0
    unavailable_count = 0
    present_count = 0
    absent_count = 0
    suspicious_count = 0

    for filepath in files:
        report = {
            "file": os.path.basename(filepath),
            "checks": [],
            "flagged": False,
        }

        # C2PA check
        c2pa_result = check_c2pa(filepath)
        report["checks"].append({"name": "c2pa", "label": "C2PA Manifest", **c2pa_result})
        if c2pa_result.get("available") is False:
            unavailable_count += 1
        if c2pa_result.get("isAI"):
            report["flagged"] = True

        # IPTC/XMP check
        iptc_result = check_iptc_xmp(filepath)
        report["checks"].append({"name": "iptc", "label": "IPTC/XMP Metadata", **iptc_result})
        if iptc_result.get("available") is False:
            unavailable_count += 1
        if iptc_result.get("isAI"):
            report["flagged"] = True

        # PNG chunks check (SD/ComfyUI)
        if filepath.lower().endswith(".png"):
            png_result = check_png_chunks(filepath)
            report["checks"].append({"name": "png_chunks", "label": "PNG AI Chunks", **png_result})
            if png_result.get("available") is False:
                unavailable_count += 1
            if png_result.get("isAI"):
                report["flagged"] = True

        # Container metadata check for video/image metadata consistency and AI generator strings.
        container_result = check_container_metadata(filepath)
        report["checks"].append({"name": "container_metadata", "label": "Container Metadata", **container_result})
        if container_result.get("available") is False:
            unavailable_count += 1
        if container_result.get("isAI"):
            report["flagged"] = True

        meaningful_checks = [
            check for check in report["checks"]
            if check.get("name") != "container_metadata" and check.get("found")
        ]
        if meaningful_checks:
            present_count += 1
        else:
            absent_count += 1

        if report["flagged"]:
            suspicious_count += 1

        if report["flagged"]:
            flagged_count += 1

        results.append(report)

    print(json.dumps({
        "results": results,
        "summary": {
            "total": len(results),
            "flagged": flagged_count,
            "clean": len(results) - flagged_count,
            "unavailable": unavailable_count,
            "present": present_count,
            "absent": absent_count,
            "suspicious": suspicious_count,
            "passRate": round(((len(results) - flagged_count) / len(results)) * 100) if results else 0,
        }
    }))


if __name__ == "__main__":
    main()
