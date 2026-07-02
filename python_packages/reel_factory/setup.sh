#!/usr/bin/env bash
# setup.sh — one-time setup on Mac Studio M4 Max
set -e

echo "→ checking ffmpeg with VideoToolbox support"
if ! command -v ffmpeg &>/dev/null; then
    echo "installing ffmpeg via homebrew..."
    brew install ffmpeg
fi

ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_videotoolbox || {
    echo "ERROR: your ffmpeg lacks h264_videotoolbox. brew reinstall ffmpeg."; exit 1; }

echo "✓ ffmpeg OK"

# Python dependencies
echo "→ checking Python dependencies"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "$PYTHON_BIN" &>/dev/null; then
    PYTHON_BIN="python3"
fi
if [ ! -x ".venv/bin/python" ]; then
    "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt

if [ "${REEL_FACTORY_OPTIONAL_DEPS:-0}" = "1" ]; then
    echo "→ installing optional AI / vision / typography dependencies"
    if command -v brew &>/dev/null; then
        brew install pkg-config cairo pango gobject-introspection pygobject3 gtk+3 redis
    fi
    export PKG_CONFIG_PATH="/opt/homebrew/lib/pkgconfig:/opt/homebrew/share/pkgconfig:${PKG_CONFIG_PATH:-}"
    .venv/bin/python -m pip install -r requirements-optional.txt
fi
echo "✓ Python dependencies OK"

# Fonts — drop TikTok Sans Black + Montserrat Black into ./fonts/
echo "→ checking fonts/"
mkdir -p fonts
if [ ! -f "fonts/TikTokSans-Black.ttf" ] && [ ! -f "fonts/Montserrat-Black.ttf" ]; then
    cat <<EOF

⚠ no fonts found in ./fonts/ — download at minimum one of:
  • TikTok Sans Black 900 → https://fonts.google.com/specimen/TikTok+Sans
  • Montserrat Black 900  → https://fonts.google.com/specimen/Montserrat
  drop the .ttf files into ./fonts/ then rerun this script.
EOF
    exit 1
fi

# Install into ~/Library/Fonts so local preview/render tools can find families.
echo "→ installing fonts into ~/Library/Fonts"
cp -n fonts/*.ttf ~/Library/Fonts/ 2>/dev/null || true
fc-cache -fv 2>/dev/null || true

# Pick the font name to use in ASS
if fc-match "TikTok Sans:weight=900" 2>/dev/null | grep -qi "tiktok"; then
    echo "✓ TikTok Sans available"
elif fc-match "Montserrat:weight=900" 2>/dev/null | grep -qi "montserrat"; then
    echo "✓ Montserrat available (caption font will use this)"
fi

# Project skeleton
mkdir -p 00_source_videos 01_captions 02_processed 03_audio_library project_data
echo "✓ project tree ready"
echo
echo "next:"
echo "  1. drop a .mp4 into 00_source_videos/  (e.g. clip_001.mp4)"
echo "  2. drop a matching .txt or .json into 01_captions/  (e.g. clip_001.txt)"
echo "  3. .venv/bin/python reel_pipeline.py --root . --dry-run"
echo "  4. .venv/bin/python reel_pipeline.py --root ."
echo "  5. ALLOW_INSECURE_LOCAL=1 .venv/bin/python reel_gui.py  # loopback-only GUI dev"
