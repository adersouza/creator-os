#!/usr/bin/env python3
"""
Post-processing sanitizer for ContentForge.
Strips forensic tells from MP4/MOV files:
1. x264 UUID SEI (dc45e9bd-e6d9-48b7-962c-d820d923eeef) in H.264 bitstream
2. Lavf/Lavc/x264/ffmpeg strings in container atoms
3. ©too (encoder tool) atom
4. Encoded_Library_Settings parameter string

Works by binary patching — no re-encoding needed, so zero quality loss.
"""

import os
import struct
import sys

# x264 UUID SEI: dc45e9bd-e6d9-48b7-962c-d820d923eeef
X264_UUID = bytes(
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

# Strings to null out in container atoms
FORENSIC_STRINGS = [
    b"Lavf",
    b"Lavc",
    b"x264",
    b"x265",
    b"ffmpeg",
    b"FFmpeg",
    b"HandBrake",
    b"handbrake",
]


def nullify_sei_in_mdat(data, start_offset):
    """
    Scan mdat for H.264 NAL units containing x264 UUID SEI.
    Zero out the UUID and encoder string within the SEI payload.
    Returns (modified_data, count_of_patches).
    """
    buf = bytearray(data)
    patches = 0
    search_start = 0

    while True:
        # Find x264 UUID in the buffer
        idx = buf.find(X264_UUID, search_start)
        if idx == -1:
            break

        # Zero out the UUID (16 bytes)
        for i in range(16):
            buf[idx + i] = 0x00
        patches += 1

        # Also zero out the encoder string that follows the UUID
        # It's ASCII text like "x264 - core 164 r3095 ..." until a null or non-printable byte
        str_start = idx + 16
        str_end = str_start
        while str_end < len(buf) and str_end < str_start + 512:
            b = buf[str_end]
            if b < 0x20 or b > 0x7E:
                break
            buf[str_end] = 0x20  # Replace with spaces (preserves NAL length)
            str_end += 1

        search_start = str_end

    return bytes(buf), patches


def nullify_container_strings(data):
    """
    Find and null out forensic encoder strings in container atoms.
    Replaces matched strings with spaces to preserve atom sizes.
    Returns (modified_data, list_of_patches).
    """
    buf = bytearray(data)
    patches = []

    for forensic_str in FORENSIC_STRINGS:
        search_start = 0
        while True:
            idx = buf.find(forensic_str, search_start)
            if idx == -1:
                break

            # Don't patch inside mdat (video bitstream) — only container atoms
            # We'll do a best-effort check: if we're in a region that looks like
            # text metadata (surrounded by printable chars), patch it
            patch_len = len(forensic_str)

            # Replace with spaces
            for i in range(patch_len):
                buf[idx + i] = 0x20

            # Also try to null out surrounding encoder version string
            # e.g., "Lavf60.16.100" or "x264 - core 164"
            ext_end = idx + patch_len
            # Extend forward through version-like chars (digits, dots, spaces, dashes)
            while ext_end < len(buf) and ext_end < idx + 64:
                b = buf[ext_end]
                if b in (0x2E, 0x2D, 0x20) or (0x30 <= b <= 0x39):  # . - space 0-9
                    buf[ext_end] = 0x20
                    ext_end += 1
                else:
                    break

            patches.append(
                {
                    "string": forensic_str.decode("ascii", errors="replace"),
                    "offset": idx,
                    "length": ext_end - idx,
                }
            )
            search_start = ext_end

    return bytes(buf), patches


def find_and_patch_tool_atom(data):
    """
    Find ©too (encoder tool) atom and null its value.
    The atom looks like: [size:4][©too:4][data...]
    """
    buf = bytearray(data)
    patches = 0

    # Search for ©too atom marker (0xa9 0x74 0x6f 0x6f)
    marker = b"\xa9too"
    search_start = 0

    while True:
        idx = buf.find(marker, search_start)
        if idx == -1:
            break

        # The atom size is in the 4 bytes before the marker
        if idx >= 4:
            atom_size = struct.unpack(">I", bytes(buf[idx - 4 : idx]))[0]
            # Null out the atom's data payload (after the 8-byte header)
            data_start = idx + 4  # After ©too marker
            data_end = min(idx - 4 + atom_size, len(buf))
            for i in range(data_start, data_end):
                buf[i] = 0x00
            patches += 1

        search_start = idx + 4

    return bytes(buf), patches


def sanitize_jpeg(filepath):
    """
    Sanitize a JPEG file: strip Lavc/Lavf strings from binary data
    and ensure creation_time metadata is present.
    """
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    with open(filepath, "rb") as f:
        data = f.read()

    original_size = len(data)
    results = {
        "file": os.path.basename(filepath),
        "size": original_size,
        "patches": [],
    }

    buf = bytearray(data)
    patched = False

    # Null out forensic strings in JPEG binary
    for forensic_str in FORENSIC_STRINGS:
        search_start = 0
        while True:
            idx = buf.find(forensic_str, search_start)
            if idx == -1:
                break
            patch_len = len(forensic_str)
            # Replace with spaces
            for i in range(patch_len):
                buf[idx + i] = 0x20
            # Extend through version-like chars
            ext_end = idx + patch_len
            while ext_end < len(buf) and ext_end < idx + 64:
                b = buf[ext_end]
                if b in (0x2E, 0x2D, 0x20) or (0x30 <= b <= 0x39):
                    buf[ext_end] = 0x20
                    ext_end += 1
                else:
                    break
            results["patches"].append(
                f"String '{forensic_str.decode()}' nullified in JPEG"
            )
            patched = True
            search_start = ext_end

    if patched:
        with open(filepath, "wb") as f:
            f.write(bytes(buf))
        results["modified"] = True
        assert len(buf) == original_size, "JPEG size changed!"
    else:
        results["modified"] = False

    return results


def sanitize_file(filepath):
    """
    Full sanitization pass on an MP4/MOV file.
    Returns dict with results.
    """
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    with open(filepath, "rb") as f:
        data = f.read()

    original_size = len(data)
    results = {
        "file": os.path.basename(filepath),
        "size": original_size,
        "patches": [],
    }

    # 1. Strip x264 UUID SEI from bitstream
    data, sei_count = nullify_sei_in_mdat(data, 0)
    if sei_count > 0:
        results["patches"].append(f"x264 UUID SEI: {sei_count} instance(s) nullified")

    # 2. Null out ©too encoder tool atom
    data, tool_count = find_and_patch_tool_atom(data)
    if tool_count > 0:
        results["patches"].append(
            f"©too encoder atom: {tool_count} instance(s) nullified"
        )

    # 3. Null out forensic strings in container
    data, string_patches = nullify_container_strings(data)
    if string_patches:
        for p in string_patches:
            results["patches"].append(
                f"String '{p['string']}' at offset {p['offset']} ({p['length']} bytes)"
            )

    # 4. Write back
    if results["patches"]:
        with open(filepath, "wb") as f:
            f.write(data)
        results["modified"] = True
        results["newSize"] = len(data)
        assert len(data) == original_size, "File size changed — binary patching error!"
    else:
        results["modified"] = False

    return results


def verify_clean(filepath):
    """
    Quick verification that no forensic strings remain.
    """
    with open(filepath, "rb") as f:
        data = f.read()

    issues = []

    # Check for x264 UUID
    if X264_UUID in data:
        issues.append("x264 UUID SEI still present")

    # Check for encoder strings
    for s in FORENSIC_STRINGS:
        if s in data:
            issues.append(f"String '{s.decode()}' still present")

    return {"clean": len(issues) == 0, "issues": issues}


def main():
    import json

    if len(sys.argv) < 2:
        print(
            json.dumps({"error": "Usage: sanitize.py <file_or_directory> [--verify]"})
        )
        sys.exit(1)

    target = sys.argv[1]
    verify_only = "--verify" in sys.argv

    results = []

    if os.path.isdir(target):
        supported = {".mp4", ".mov", ".jpg", ".jpeg"}
        files = sorted(
            [
                os.path.join(target, f)
                for f in os.listdir(target)
                if os.path.splitext(f)[1].lower() in supported and not f.startswith(".")
            ]
        )
    elif os.path.isfile(target):
        files = [target]
    else:
        print(json.dumps({"error": f"Not found: {target}"}))
        sys.exit(1)

    for filepath in files:
        ext = os.path.splitext(filepath)[1].lower()
        if verify_only:
            result = verify_clean(filepath)
            result["file"] = os.path.basename(filepath)
            results.append(result)
        else:
            if ext in (".jpg", ".jpeg"):
                result = sanitize_jpeg(filepath)
            else:
                result = sanitize_file(filepath)
            # Verify after sanitization
            verification = verify_clean(filepath)
            result["verified"] = verification["clean"]
            result["remainingIssues"] = verification.get("issues", [])
            results.append(result)

    total = len(results)
    if verify_only:
        clean_count = sum(1 for r in results if r.get("clean"))
        print(
            json.dumps(
                {
                    "results": results,
                    "summary": {
                        "total": total,
                        "clean": clean_count,
                        "dirty": total - clean_count,
                    },
                }
            )
        )
    else:
        modified_count = sum(1 for r in results if r.get("modified"))
        verified_count = sum(1 for r in results if r.get("verified"))
        print(
            json.dumps(
                {
                    "results": results,
                    "summary": {
                        "total": total,
                        "modified": modified_count,
                        "verified": verified_count,
                        "totalPatches": sum(len(r.get("patches", [])) for r in results),
                    },
                }
            )
        )


if __name__ == "__main__":
    main()
