"""caption_render.py — PIL+Pilmoji caption renderer.

Replaces libass for subtitle burn-in. Why: libass on this ffmpeg build can't
fully render color-emoji COLR/CBDT layers — they come out as monochrome
silhouettes. Pillow + Pilmoji renders captions to a transparent PNG with
full-color Apple-style emojis baked in; ffmpeg's overlay filter then composites
the PNG onto the video. Net result:
  - real color emojis (Apple-style)
  - identical text styling to the old libass output (white fill, black stroke,
    drop shadow for "soft", white box for "bubble")
  - same auto-pick logic (font / color / style / band)
"""
from __future__ import annotations
import argparse
import ctypes
import json
import os
import sys
import tempfile
from pathlib import Path
from PIL import Image, ImageFont, ImageDraw, ImageFilter
import pilmoji
from pilmoji.source import AppleEmojiSource

# Map our font-family names → bundled TTF basenames in fonts/
FONT_FILE = {
    "Onest":       "Onest-Variable.ttf",
    "Inter":       "Inter-Black.ttf",
    "Montserrat":  "Montserrat-Black.ttf",
    "TikTok Sans": "TikTokSans-Black.ttf",
    "Instagram Sans Condensed": "InstagramSansCondensed-Regular.woff2",
    "Instagram Sans Condensed Bold": "InstagramSansCondensed-Bold.woff2",
    "Sofia Sans Condensed Medium": "SofiaSansCondensed-Medium.ttf",
    "Arial Narrow": "/System/Library/Fonts/Supplemental/Arial Narrow.ttf",
}

CANVAS_W, CANVAS_H = 1080, 1920
MAX_TEXT_W = 960
REELS_SAFE_TEXT_W = 600
LOWER_CENTER_Y_RATIO = 0.54
LOWER_CENTER_ALT_Y_RATIO = 0.58


def caption_alpha_box(path: Path) -> dict[str, int] | None:
    """Return the visible alpha bounds for a rendered full-canvas caption PNG."""
    img = Image.open(path).convert("RGBA")
    bbox = img.getbbox()
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _resolve_font_path(font_family: str, fonts_dir: Path) -> Path:
    configured = FONT_FILE.get(font_family, FONT_FILE["Arial Narrow"])
    path = Path(configured)
    if path.is_absolute():
        return path
    candidate = fonts_dir / path
    if candidate.exists() or fonts_dir.is_absolute():
        return candidate
    package_candidate = Path(__file__).resolve().parent / fonts_dir / path
    return package_candidate if package_candidate.exists() else candidate


def _ensure_homebrew_gi_library_path() -> None:
    """Let PyGObject find Homebrew GLib/Pango dylibs on Apple Silicon."""
    brew_lib = "/opt/homebrew/lib"
    current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if Path(brew_lib).exists() and brew_lib not in current.split(":"):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
            f"{brew_lib}:{current}" if current else brew_lib
        )
    for dylib in (
        "libintl.8.dylib",
        "libffi.8.dylib",
        "libpcre2-8.0.dylib",
        "libglib-2.0.0.dylib",
        "libgmodule-2.0.0.dylib",
        "libgobject-2.0.0.dylib",
        "libgio-2.0.0.dylib",
        "libpango-1.0.0.dylib",
        "libpangocairo-1.0.0.dylib",
    ):
        path = Path(brew_lib) / dylib
        if path.exists():
            try:
                ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def _reexec_with_homebrew_gi_env_if_needed() -> None:
    """Restart once with Homebrew dylib paths visible to macOS' loader."""
    brew_lib = "/opt/homebrew/lib"
    if os.environ.get("REEL_FACTORY_GI_ENV_READY") == "1" or not Path(brew_lib).exists():
        return
    env = dict(os.environ)
    for key in ("DYLD_FALLBACK_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        current = env.get(key, "")
        if brew_lib not in current.split(":"):
            env[key] = f"{brew_lib}:{current}" if current else brew_lib
    env["REEL_FACTORY_GI_ENV_READY"] = "1"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)


def _homebrew_gi_env_is_ready() -> bool:
    if os.environ.get("REEL_FACTORY_GI_ENV_READY") == "1":
        return True
    brew_lib = "/opt/homebrew/lib"
    return any(
        brew_lib in os.environ.get(key, "").split(":")
        for key in ("DYLD_FALLBACK_LIBRARY_PATH", "DYLD_LIBRARY_PATH")
    )

# Platform UI safe zones (in px, on a 1920-tall canvas):
#   - IG Reels:  top ~200 (status bar + 'Reels' header), bottom ~280 (caption + buttons)
#   - TikTok:    top ~80 (status bar),                   bottom ~360 (caption + buttons)
#   - Cross-safe (works on both platforms): top 280, bottom 480
# Captions placed inside these zones risk being half-hidden by platform UI.
SAFE_TOP    = 280
SAFE_BOTTOM = 480


def _font_for_lines(font_path: Path, line_count: int, scale: float = 1.0) -> ImageFont.FreeTypeFont:
    fontsize_table = {1: 88, 2: 76, 3: 66, 4: 58}
    fs = round(fontsize_table.get(line_count, 52) * scale)
    return ImageFont.truetype(str(font_path), max(fs, 20))


def _text_width(draw: ImageDraw.ImageDraw, text: str,
                font: ImageFont.FreeTypeFont, stroke_width: int = 4) -> int:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return bbox[2] - bbox[0]


def _split_long_word(word: str, draw: ImageDraw.ImageDraw,
                     font: ImageFont.FreeTypeFont,
                     max_width: int) -> list[str]:
    """Break a single over-wide token at glyph boundaries."""
    if _text_width(draw, word, font) <= max_width:
        return [word]
    chunks: list[str] = []
    cur = ""
    for ch in word:
        candidate = cur + ch
        if cur and _text_width(draw, candidate, font) > max_width:
            chunks.append(cur)
            cur = ch
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks or [word]


def _wrap_lines(text: str, font: ImageFont.FreeTypeFont,
                max_width: int = MAX_TEXT_W) -> list[str]:
    """Wrap each user-provided line by measured pixel width."""
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    wrapped: list[str] = []
    for raw_line in text.split("\n"):
        tokens = raw_line.split()
        if not tokens:
            wrapped.append("")
            continue

        words: list[str] = []
        for token in tokens:
            words.extend(_split_long_word(token, draw, font, max_width))

        line = ""
        for word in words:
            if not line:
                line = word
                continue
            candidate = f"{line} {word}"
            if _text_width(draw, candidate, font) <= max_width:
                line = candidate
            else:
                wrapped.append(line)
                line = word
        if line:
            wrapped.append(line)
    return wrapped


def _layout_text(text: str, font_path: Path, scale: float,
                 max_width: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Pick a font size and measured lines that fit the caption canvas."""
    explicit_lines = max(1, text.count("\n") + 1)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    shrink_steps = (1.0, 0.95, 0.90, 0.85, 0.80, 0.74, 0.68, 0.62, 0.56, 0.50, 0.44, 0.38)
    max_lines = 5 if max_width < 700 * scale else 6
    for shrink in shrink_steps:
        font = _font_for_lines(font_path, explicit_lines, scale=scale * shrink)
        lines = _wrap_lines(text, font, max_width=max_width)
        font = _font_for_lines(font_path, max(1, len(lines)), scale=scale * shrink)
        lines = _wrap_lines(text, font, max_width=max_width)
        if (
            lines
            and len(lines) <= max_lines
            and max(_text_width(draw, line, font) for line in lines) <= max_width
        ):
            return font, lines
    return font, lines


def _contains_emoji_like(text: str) -> bool:
    return any(
        ord(ch) >= 0x1F000 or ch in {"\ufe0f", "\u200d"}
        for ch in text
    )


def _caption_xy(
    *,
    band: str,
    canvas_w: int,
    canvas_h: int,
    content_w: int,
    content_h: int,
    safe_top: int,
    safe_bottom: int,
) -> tuple[int, int]:
    margin_x = max(56, round(canvas_w * 0.055))
    if band == "bottom":
        y = canvas_h - content_h - safe_bottom
    elif band == "lower_center":
        y = round(canvas_h * LOWER_CENTER_Y_RATIO) - content_h // 2
    elif band == "lower_center_alt":
        y = round(canvas_h * LOWER_CENTER_ALT_Y_RATIO) - content_h // 2
    elif band in {"center", "left", "right"}:
        y = (canvas_h - content_h) // 2
    else:
        y = safe_top

    if band == "left":
        x = margin_x
    elif band == "right":
        x = canvas_w - content_w - margin_x
    else:
        x = (canvas_w - content_w) // 2
    return max(0, x), max(0, y)


def render_caption_png(
    text: str,
    *,
    font_family: str,
    fonts_dir: Path,
    color_scheme: str,
    band: str,
    style: str,
    out_path: Path,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    renderer: str = "pillow",
) -> None:
    """Render `text` to a transparent 1080x1920 PNG at out_path. The PNG is
    designed to be overlaid on the video at (0, 0) — position is already
    baked in based on the band.
    """
    if renderer == "pango":
        try:
            if Path("/opt/homebrew/lib").exists() and not _homebrew_gi_env_is_ready():
                raise RuntimeError("Pango environment not ready; falling back to Pillow")
            return _render_caption_png_pango(
                text,
                font_family=font_family,
                fonts_dir=fonts_dir,
                color_scheme=color_scheme,
                band=band,
                style=style,
                out_path=out_path,
                canvas_w=canvas_w,
                canvas_h=canvas_h,
            )
        except Exception:
            # Pango/Cairo is an opt-in spike. Missing native deps should not
            # break the production Pillow path.
            pass
    elif renderer != "pillow":
        raise ValueError("renderer must be pillow or pango")

    # ── font + size table (mirrors caption_to_ass) ──
    scale = canvas_w / 1080
    safe_top    = round(280 * canvas_h / 1920)
    safe_bottom = round(480 * canvas_h / 1920)
    max_text_w  = round((520 if band in {"left", "right"} else REELS_SAFE_TEXT_W) * scale)
    canvas_w_   = canvas_w
    canvas_h_   = canvas_h
    font_path = _resolve_font_path(font_family, fonts_dir)
    text = text.strip()
    font, lines = _layout_text(text, font_path, scale, max_text_w)
    fs = font.size
    line_count = len(lines)
    line_h = int(fs * 1.18)

    # ── style → stroke + shadow + box ──
    style_def = {
        "classic": {"outline_mult": 0.06,  "shadow": 0, "box": False},
        "meme":    {"outline_mult": 0.062, "shadow": 2, "box": False},
        "ig":      {
            "outline_mult": 0.0,
            "outline_px": 2,
            "shadow": 0,
            "box": False,
            "light_text": (245, 245, 245, 255),
            "light_stroke": (26, 26, 26, 235),
            "x_scale": 1.02,
            "soften": 0.2,
        },
        "thin":    {"outline_mult": 0.010, "shadow": 2, "box": False},
        "soft":    {"outline_mult": 0.020, "shadow": 5, "box": False},
        "bubble":  {"outline_mult": 0.0,   "shadow": 0, "box": True},
    }
    sd = style_def.get(style, style_def["classic"])
    outline_px = sd.get("outline_px")
    if outline_px is None:
        outline_px = max(1, round(fs * sd["outline_mult"])) if not sd["box"] else 0
    shadow_radius = sd["shadow"]
    use_box = sd["box"]

    # ── colors ──
    if use_box:
        text_color   = (0, 0, 0, 255)
        stroke_color = (0, 0, 0, 0)
        box_color    = (255, 255, 255, 240)
    elif color_scheme == "dark":
        text_color   = (0, 0, 0, 255)
        stroke_color = (255, 255, 255, 255)
        box_color    = None
    else:  # light (default)
        text_color   = sd.get("light_text", (255, 255, 255, 255))
        stroke_color = sd.get("light_stroke", (0, 0, 0, 255))
        box_color    = None

    canvas = Image.new("RGBA", (canvas_w_, canvas_h_), (0, 0, 0, 0))
    block_h = line_h * line_count

    # Render each line: temp wide canvas, measure, crop, center, composite.
    pad_x = max(40, outline_px * 2 + 4)
    line_canvas_w = canvas_w_ * 2  # generous so emoji+stroke don't clip

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        line_img = Image.new("RGBA", (line_canvas_w, line_h * 3), (0, 0, 0, 0))

        with pilmoji.Pilmoji(line_img, source=AppleEmojiSource) as p:
            # ── drop shadow (soft style) ──
            if shadow_radius > 0:
                shadow = Image.new("RGBA", line_img.size, (0, 0, 0, 0))
                with pilmoji.Pilmoji(shadow, source=AppleEmojiSource) as ps:
                    ps.text(
                        (pad_x, line_h // 2), line,
                        (0, 0, 0, 200), font,
                    )
                shadow = shadow.filter(ImageFilter.GaussianBlur(radius=shadow_radius))
                line_img.alpha_composite(shadow, (3, 4))

            # ── main text (with stroke if applicable) ──
            kwargs = {}
            if outline_px > 0:
                kwargs["stroke_width"] = outline_px
                kwargs["stroke_fill"] = stroke_color
            p.text(
                (pad_x, line_h // 2), line,
                text_color, font, **kwargs,
            )

        # Crop to actual content
        bbox = line_img.getbbox()
        if bbox is None:
            continue
        content = line_img.crop(bbox)
        x_scale = sd.get("x_scale", 1.0)
        if abs(x_scale - 1.0) > 0.001:
            content = content.resize(
                (round(content.width * x_scale), content.height),
                Image.Resampling.BICUBIC,
            )
        soften = sd.get("soften", 0)
        if soften:
            content = content.filter(ImageFilter.GaussianBlur(radius=soften))

        x, block_y = _caption_xy(
            band=band,
            canvas_w=canvas_w_,
            canvas_h=canvas_h_,
            content_w=content.width,
            content_h=block_h,
            safe_top=safe_top,
            safe_bottom=safe_bottom,
        )
        y = block_y + i * line_h

        # Bubble: round-rect background underneath
        if use_box:
            pad_l = max(24, fs // 4)
            pad_v = max(8, fs // 8)
            bx0, by0 = x - pad_l, y - pad_v
            bx1, by1 = x + content.width + pad_l, y + content.height + pad_v
            box_layer = Image.new("RGBA", (canvas_w_, canvas_h_), (0, 0, 0, 0))
            ImageDraw.Draw(box_layer).rounded_rectangle(
                (bx0, by0, bx1, by1),
                radius=int(fs * 0.35),
                fill=box_color,
            )
            canvas = Image.alpha_composite(canvas, box_layer)

        canvas.alpha_composite(content, (x, y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def _render_caption_png_pango(
    text: str,
    *,
    font_family: str,
    fonts_dir: Path,
    color_scheme: str,
    band: str,
    style: str,
    out_path: Path,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
) -> None:
    """Experimental Pango/Cairo renderer.

    The function deliberately falls back to Pillow unless the host already has
    PyGObject + Cairo available. The real implementation can grow here without
    changing CLI/recipe interfaces.
    """
    if _contains_emoji_like(text):
        raise ValueError("pango emoji path is disabled; falling back to Pillow")
    _ensure_homebrew_gi_library_path()
    import cairo  # type: ignore
    import gi  # type: ignore

    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo  # type: ignore

    scale = canvas_w / 1080
    safe_top = round(280 * canvas_h / 1920)
    safe_bottom = round(480 * canvas_h / 1920)
    max_text_w = round((520 if band in {"left", "right"} else 960) * scale)
    font_path = _resolve_font_path(font_family, fonts_dir)
    text = text.strip()
    pil_font, lines = _layout_text(text, font_path, scale, max_text_w)
    font_size = pil_font.size
    line_height = int(font_size * 1.18)
    block_h = line_height * max(1, len(lines))
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas_w, canvas_h)
    ctx = cairo.Context(surface)
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    layout = PangoCairo.create_layout(ctx)
    layout.set_alignment(Pango.Alignment.CENTER)
    layout.set_width(max_text_w * Pango.SCALE)
    layout.set_text("\n".join(lines), -1)
    desc = Pango.FontDescription(f"{font_family} {font_size}")
    layout.set_font_description(desc)
    _, logical = layout.get_pixel_extents()
    layout_w = min(max_text_w, max(1, logical.width))
    x, y = _caption_xy(
        band=band,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        content_w=layout_w,
        content_h=max(1, logical.height),
        safe_top=safe_top,
        safe_bottom=safe_bottom,
    )

    if style == "bubble":
        pad_x = max(24, font_size // 4)
        pad_y = max(10, font_size // 8)
        ctx.set_source_rgba(1, 1, 1, 0.94)
        _rounded_rect(ctx, x - pad_x, y - pad_y,
                      logical.width + pad_x * 2, logical.height + pad_y * 2,
                      font_size * 0.35)
        ctx.fill()
        ctx.set_source_rgba(0, 0, 0, 1)
    else:
        # Pango path intentionally uses a simple readability shadow/stroke
        # approximation; Pillow remains the pixel-golden default.
        if style == "soft":
            ctx.move_to(x + 3, y + 4)
            ctx.set_source_rgba(0, 0, 0, 0.45)
            PangoCairo.show_layout(ctx, layout)
        ctx.set_source_rgba(0, 0, 0, 1 if color_scheme != "dark" else 0.0)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            ctx.move_to(x + dx, y + dy)
            PangoCairo.show_layout(ctx, layout)
        if color_scheme == "dark":
            ctx.set_source_rgba(0, 0, 0, 1)
        else:
            ctx.set_source_rgba(1, 1, 1, 1)
    ctx.move_to(x, y)
    PangoCairo.show_layout(ctx, layout)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    surface.write_to_png(str(out_path))


def _rounded_rect(ctx, x: float, y: float, w: float, h: float, r: float) -> None:
    import math

    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def compare_renderers(text: str, *, fonts_dir: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    pillow = out_dir / "caption_pillow.png"
    pango = out_dir / "caption_pango.png"
    for renderer, path in (("pillow", pillow), ("pango", pango)):
        render_caption_png(
            text,
            font_family="Onest",
            fonts_dir=fonts_dir,
            color_scheme="light",
            band="top",
            style="classic",
            out_path=path,
            renderer=renderer,
        )
    return {"pillow": str(pillow), "pango": str(pango)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Render caption PNGs or compare renderers.")
    ap.add_argument("--compare-renderers", action="store_true")
    ap.add_argument("--text", default="hello world")
    ap.add_argument("--fonts-dir", default="fonts")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    if args.compare_renderers:
        _reexec_with_homebrew_gi_env_if_needed()
        out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="caption_compare_"))
        print(json.dumps(compare_renderers(args.text, fonts_dir=Path(args.fonts_dir), out_dir=out_dir), indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
