"""
CoralTicker brand asset generator (CTK-012, Session 2 Track A).
Produces seven files at C:/github/coralticker/assets/brand/.

Spec source: .claude/branding-guide.md §"Visual direction (v1)" + CTK-012 plan.
Mark A (colored full-stop) selected; design fully approved and locked.
"""

from __future__ import annotations

import os
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

BRAND_DIR = Path(r"C:\github\coralticker\assets\brand")
FONTS_DIR = BRAND_DIR / "fonts"

PLEX_SANS_BOLD = FONTS_DIR / "IBMPlexSans-Bold.ttf"
PLEX_SANS_REGULAR = FONTS_DIR / "IBMPlexSans-Regular.ttf"
PLEX_MONO_REGULAR = FONTS_DIR / "IBMPlexMono-Regular.ttf"

# Color tokens (locked in .claude/branding-guide.md §Visual direction v1)
FOREST = "#1B5E20"           # accent — wordmark dot, em-dash highlights, single-pixel jobs only
NEAR_BLACK = "#1A1814"       # text + UI, slightly warm off-black
CREAM = "#F5F0E8"            # background, paper, canvas — warm off-white


# ----------------------------------------------------------------------------
# Helpers — text-to-SVG-path extraction via fontTools
# ----------------------------------------------------------------------------


class _TextRunner:
    """Lay out a string in a TTFont and emit an SVG <path> per glyph.

    Uses the `cmap` for codepoint→glyph and `hmtx` for advances, as is standard
    when text-to-paths-ing. No kerning, no shaping — these wordmarks are simple
    Latin strings, so straightforward horizontal stacking is correct. Glyphs
    are emitted in font em units (Y down — we flip Y at SVG time).
    """

    def __init__(self, font_path: Path):
        self.font = TTFont(str(font_path))
        self.cmap = self.font.getBestCmap()
        self.hmtx = self.font["hmtx"]
        self.glyph_set = self.font.getGlyphSet()
        self.units_per_em = self.font["head"].unitsPerEm
        self.ascent = self.font["hhea"].ascent
        self.descent = self.font["hhea"].descent

    def run(self, text: str, x_em: float = 0.0):
        """Yield (svg_path_d, x_em_after, advance_em) for each glyph in text.

        x_em is the cursor position in font em units before the glyph.
        """
        cursor = x_em
        for ch in text:
            cp = ord(ch)
            if cp not in self.cmap:
                # Skip unmapped — none expected in our strings.
                continue
            glyph_name = self.cmap[cp]
            advance, _lsb = self.hmtx[glyph_name]
            pen = SVGPathPen(self.glyph_set)
            self.glyph_set[glyph_name].draw(pen)
            d = pen.getCommands()
            yield ch, glyph_name, cursor, advance, d
            cursor += advance

    def text_width_em(self, text: str) -> float:
        return sum(self.hmtx[self.cmap[ord(ch)]][0] for ch in text if ord(ch) in self.cmap)


# ----------------------------------------------------------------------------
# 1. coralticker-wordmark.svg
# ----------------------------------------------------------------------------


def build_wordmark_svg() -> None:
    """`coralticker.` — `coral` Plex Sans Bold, `ticker` Plex Sans Regular.

    Period in forest #1B5E20; the rest in near-black #1A1814.
    Glyphs converted to outlined paths so the SVG renders without Plex installed.
    """
    bold = _TextRunner(PLEX_SANS_BOLD)
    regular = _TextRunner(PLEX_SANS_REGULAR)

    # Both faces share unitsPerEm = 1000 in IBM Plex; assert so the layout
    # math below stays honest if a future font swap breaks the assumption.
    assert bold.units_per_em == regular.units_per_em == 1000, "Plex em mismatch"
    upem = bold.units_per_em

    # Build per-glyph path data with x positions.
    # Run 1: "coral"  (bold,  near-black)
    # Run 2: "ticker" (reg.,  near-black)
    # Run 3: "."      (reg.,  forest)
    paths: list[tuple[str, str, float]] = []  # (color, d, x_offset_em)

    cursor = 0.0
    for _ch, _gn, x, adv, d in bold.run("coral", x_em=cursor):
        if d:
            paths.append((NEAR_BLACK, d, x))
        cursor = x + adv

    for _ch, _gn, x, adv, d in regular.run("ticker", x_em=cursor):
        if d:
            paths.append((NEAR_BLACK, d, x))
        cursor = x + adv

    # The dot — "." — is a single glyph; drawn from regular weight to keep its
    # visual weight matched to "ticker" rather than the heavier "coral".
    for _ch, _gn, x, adv, d in regular.run(".", x_em=cursor):
        if d:
            paths.append((FOREST, d, x))
        cursor = x + adv

    total_width_em = cursor
    # Vertical extent: ascent above baseline, descent below. Add a small breath.
    ascent = max(bold.ascent, regular.ascent)
    descent = min(bold.descent, regular.descent)  # negative number
    # Tighten visual height by trimming top whitespace; Plex ascent reaches caps,
    # but lowercase-only text doesn't need full ascent margin. We still keep
    # full descent so the period sits correctly.
    cap_height = bold.font["OS/2"].sCapHeight if hasattr(bold.font["OS/2"], "sCapHeight") else int(ascent * 0.7)
    x_height = bold.font["OS/2"].sxHeight if hasattr(bold.font["OS/2"], "sxHeight") else int(ascent * 0.5)

    # Margin around the wordmark (em units)
    margin_x = 40
    margin_y_top = 60
    margin_y_bot = 60

    # Y flip: SVG path in font is Y-up from baseline; we transform to Y-down by
    # mapping baseline to (ascent + margin_y_top), then negating glyph Y.
    baseline = ascent + margin_y_top
    view_w = int(total_width_em + margin_x * 2)
    view_h = int(ascent + abs(descent) + margin_y_top + margin_y_bot)

    # Each glyph sits at (margin_x + x_offset, baseline) with a Y-flip transform.
    body_parts = []
    for color, d, x_off in paths:
        tx = margin_x + x_off
        ty = baseline
        # transform: translate then scale Y by -1 to flip
        body_parts.append(
            f'  <path fill="{color}" '
            f'transform="translate({tx:.2f} {ty:.2f}) scale(1 -1)" '
            f'd="{d}"/>'
        )

    svg = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {view_w} {view_h}" '
        f'width="{view_w}" height="{view_h}" role="img" '
        f'aria-label="coralticker">\n'
        f'  <title>coralticker</title>\n'
        + "\n".join(body_parts)
        + "\n</svg>\n"
    )

    out = BRAND_DIR / "coralticker-wordmark.svg"
    out.write_text(svg, encoding="utf-8")
    print(f"  wrote {out.name} ({out.stat().st_size:,} bytes)")


# ----------------------------------------------------------------------------
# 2. coralticker-mark.svg
# ----------------------------------------------------------------------------


def build_mark_svg() -> None:
    """Forest #1B5E20 filled circle on transparent — the brand's full-stop alone."""
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 100 100" width="100" height="100" '
        'role="img" aria-label="coralticker mark">\n'
        '  <title>coralticker mark</title>\n'
        f'  <circle cx="50" cy="50" r="42" fill="{FOREST}"/>\n'
        '</svg>\n'
    )
    out = BRAND_DIR / "coralticker-mark.svg"
    out.write_text(svg, encoding="utf-8")
    print(f"  wrote {out.name} ({out.stat().st_size:,} bytes)")


# ----------------------------------------------------------------------------
# 3-5. favicon-16.png, favicon-32.png, favicon-180.png + 6. favicon.ico
# ----------------------------------------------------------------------------


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _build_favicon_chip(
    size: int,
    *,
    rounded_radius_pct: float = 0.0,
    period_oversize_factor: float = 1.0,
) -> Image.Image:
    """`ct.` on near-black chip. `ct` cream-white #F5F0E8 Plex Sans Bold; period forest.

    Period has an over-scale factor: at 16×16 the spec calls for ~1.9× native so the
    dot survives sub-pixel rendering. At 32×32 and 180×180 we ease back toward 1.0×.
    """
    bg = _hex_to_rgb(NEAR_BLACK)
    fg = _hex_to_rgb(CREAM)
    accent = _hex_to_rgb(FOREST)

    # Render at a higher internal resolution then downsample for crisper edges
    # at 16/32 sizes. 8× supersample is plenty.
    SS = 8
    canvas_size = size * SS
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Chip — square or rounded
    if rounded_radius_pct > 0:
        radius = int(canvas_size * rounded_radius_pct)
        draw.rounded_rectangle(
            [0, 0, canvas_size - 1, canvas_size - 1],
            radius=radius,
            fill=bg,
        )
    else:
        draw.rectangle([0, 0, canvas_size - 1, canvas_size - 1], fill=bg)

    # Pick `ct` font size relative to chip; tuned so `ct.` fills horizontally
    # with comfortable breathing room. The exact ratio was selected by visual
    # match against the approved preview PDF (cap height ~52% of chip).
    ct_font_size_px = int(canvas_size * 0.62)
    ct_font = ImageFont.truetype(str(PLEX_SANS_BOLD), ct_font_size_px)

    # Period rendered as a circle (not as a glyph) so we control its size.
    # Native dot diameter in Plex Sans Bold @ this size ~ 0.16 * font_size.
    native_period_d = ct_font_size_px * 0.16
    period_d = int(native_period_d * period_oversize_factor)

    # Measure `ct` text
    ct_bbox = ct_font.getbbox("ct")
    ct_w = ct_bbox[2] - ct_bbox[0]
    ct_h = ct_bbox[3] - ct_bbox[1]

    # Total lockup width = ct_w + small gap + period_d
    gap = int(canvas_size * 0.02)
    total_w = ct_w + gap + period_d

    start_x = (canvas_size - total_w) // 2 - ct_bbox[0]
    # Vertical centering — line up `ct` baseline so the visual center of the
    # cap-height block matches chip center.
    baseline_y = (canvas_size - ct_h) // 2 - ct_bbox[1]

    draw.text((start_x, baseline_y), "ct", font=ct_font, fill=fg)

    # Period: aligned with `ct` baseline. Its bottom edge sits at the baseline.
    ct_baseline_y = baseline_y + ct_bbox[3]
    period_x = start_x + ct_bbox[0] + ct_w + gap
    period_y = ct_baseline_y - period_d  # bottom of dot at baseline
    draw.ellipse(
        [period_x, period_y, period_x + period_d, period_y + period_d],
        fill=accent,
    )

    # Downsample
    img = img.resize((size, size), Image.LANCZOS)
    return img


def build_favicons() -> None:
    # 16×16 — flush square, dot heavily over-scaled (~1.9× native)
    f16 = _build_favicon_chip(16, rounded_radius_pct=0.0, period_oversize_factor=1.9)
    p16 = BRAND_DIR / "favicon-16.png"
    f16.save(p16, format="PNG", optimize=True)
    print(f"  wrote {p16.name} ({p16.stat().st_size:,} bytes, {f16.size[0]}x{f16.size[1]})")

    # 32×32 — flush square, smaller over-scale needed
    f32 = _build_favicon_chip(32, rounded_radius_pct=0.0, period_oversize_factor=1.35)
    p32 = BRAND_DIR / "favicon-32.png"
    f32.save(p32, format="PNG", optimize=True)
    print(f"  wrote {p32.name} ({p32.stat().st_size:,} bytes, {f32.size[0]}x{f32.size[1]})")

    # 180×180 — Apple touch icon: rounded ~22%, native dot proportions
    f180 = _build_favicon_chip(180, rounded_radius_pct=0.22, period_oversize_factor=1.0)
    p180 = BRAND_DIR / "favicon-180.png"
    f180.save(p180, format="PNG", optimize=True)
    print(f"  wrote {p180.name} ({p180.stat().st_size:,} bytes, {f180.size[0]}x{f180.size[1]})")

    # ICO — multi-resolution, 16 + 32. Same artwork as PNGs above.
    ico_path = BRAND_DIR / "favicon.ico"
    # Pillow's ICO writer takes the source image and a sizes= list to embed.
    # Build a 32×32 source and let Pillow embed both.
    f32.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32)])
    print(f"  wrote {ico_path.name} ({ico_path.stat().st_size:,} bytes, multi-res 16+32)")


# ----------------------------------------------------------------------------
# 7. og-image-template.png  (1200×630)
# ----------------------------------------------------------------------------


def build_og_image() -> None:
    """1200×630 social card.

    Hero lockup centered vertically:
      [coralticker.] ─── [NEVER MISS THE DROP.]
    Footer hairline, then:
      coralticker.com  (left)         tagline copy  (right)
    """
    W, H = 1200, 630
    bg = _hex_to_rgb(CREAM)
    nb = _hex_to_rgb(NEAR_BLACK)
    fs = _hex_to_rgb(FOREST)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # Fonts
    word_bold_size = 96
    word_reg_size = 96
    tagline_size = 30
    footer_size = 22

    f_word_bold = ImageFont.truetype(str(PLEX_SANS_BOLD), word_bold_size)
    f_word_reg = ImageFont.truetype(str(PLEX_SANS_REGULAR), word_reg_size)
    f_tagline = ImageFont.truetype(str(PLEX_MONO_REGULAR), tagline_size)
    f_footer = ImageFont.truetype(str(PLEX_MONO_REGULAR), footer_size)

    # ----- Hero lockup ----------------------------------------------------
    # Compute pieces
    coral_text = "coral"
    ticker_text = "ticker"
    period_text = "."  # we'll draw a circle for crispness
    tagline_text = "NEVER MISS THE DROP."

    coral_bbox = f_word_bold.getbbox(coral_text)
    ticker_bbox = f_word_reg.getbbox(ticker_text)
    coral_w = coral_bbox[2] - coral_bbox[0]
    ticker_w = ticker_bbox[2] - ticker_bbox[0]
    # Period as circle, sized to match Plex Sans dot proportion
    period_d = int(word_reg_size * 0.18)
    period_gap = 0  # period sits right after ticker (no extra gap)

    wordmark_w = coral_w + ticker_w + period_gap + period_d

    # Rule line
    rule_pad = 50  # gap between wordmark and rule, and rule and tagline
    rule_len = 180

    # Tagline width
    tagline_bbox = f_tagline.getbbox(tagline_text)
    tagline_w = tagline_bbox[2] - tagline_bbox[0]

    lockup_w = wordmark_w + rule_pad + rule_len + rule_pad + tagline_w
    lockup_x = (W - lockup_w) // 2

    # Vertical baseline of the wordmark — center the wordmark cap-height
    # vertically slightly above the geometric mid (eye-level adjustment).
    wordmark_top = (H - (coral_bbox[3] - coral_bbox[1])) // 2 - 30

    # Draw `coral` (bold) in near-black
    coral_x = lockup_x - coral_bbox[0]
    coral_y = wordmark_top - coral_bbox[1]
    draw.text((coral_x, coral_y), coral_text, font=f_word_bold, fill=nb)

    # Draw `ticker` (regular) right after `coral`, baseline-aligned
    ticker_x = lockup_x + coral_w - ticker_bbox[0]
    # Align baselines: bottom of cap ascender — use bbox bottom of both.
    ticker_y = wordmark_top + (coral_bbox[3] - coral_bbox[1]) - (ticker_bbox[3] - ticker_bbox[1]) - ticker_bbox[1]
    draw.text((ticker_x, ticker_y), ticker_text, font=f_word_reg, fill=nb)

    # Period — forest circle, sitting on the baseline of the wordmark
    # Baseline = wordmark_top + (coral_bbox[3]) — actually we used coral_y + coral_bbox[3]
    baseline_y = wordmark_top + (coral_bbox[3] - coral_bbox[1])
    period_x = lockup_x + coral_w + ticker_w + period_gap
    period_y = baseline_y - period_d
    draw.ellipse(
        [period_x, period_y, period_x + period_d, period_y + period_d],
        fill=fs,
    )

    # Rule line — forest, vertically centered to wordmark x-height
    rule_y = wordmark_top + int((coral_bbox[3] - coral_bbox[1]) * 0.55)
    rule_x_start = lockup_x + wordmark_w + rule_pad
    rule_x_end = rule_x_start + rule_len
    rule_thickness = 4
    draw.rectangle(
        [rule_x_start, rule_y - rule_thickness // 2, rule_x_end, rule_y + rule_thickness // 2],
        fill=fs,
    )

    # Tagline — Plex Mono small caps, near-black
    # We're using already-uppercase string so any face works as small-caps.
    tagline_x = rule_x_end + rule_pad - tagline_bbox[0]
    # Vertically center the tagline to the rule line
    tagline_h = tagline_bbox[3] - tagline_bbox[1]
    tagline_y = rule_y - tagline_h // 2 - tagline_bbox[1]
    draw.text((tagline_x, tagline_y), tagline_text, font=f_tagline, fill=nb)

    # ----- Footer ---------------------------------------------------------
    footer_pad_x = 80
    footer_y_hairline = H - 90
    # Hairline rule — near-black, 1px
    draw.rectangle(
        [footer_pad_x, footer_y_hairline, W - footer_pad_x, footer_y_hairline + 1],
        fill=nb,
    )

    footer_text_y = footer_y_hairline + 28
    # Left: coralticker.com
    left_text = "coralticker.com"
    draw.text((footer_pad_x, footer_text_y), left_text, font=f_footer, fill=nb)

    # Right: tagline copy, right-aligned
    right_text = "Drop alerts & price tracking for reef hobbyists."
    right_bbox = f_footer.getbbox(right_text)
    right_w = right_bbox[2] - right_bbox[0]
    right_x = W - footer_pad_x - right_w - right_bbox[0]
    draw.text((right_x, footer_text_y), right_text, font=f_footer, fill=nb)

    out = BRAND_DIR / "og-image-template.png"
    img.save(out, format="PNG", optimize=True)
    assert img.size == (1200, 630), f"OG image size wrong: {img.size}"
    print(f"  wrote {out.name} ({out.stat().st_size:,} bytes, {img.size[0]}x{img.size[1]})")


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating CoralTicker brand v1 assets at {BRAND_DIR}\n")

    print("[1/4] Wordmark SVG...")
    build_wordmark_svg()
    print("[2/4] Mark SVG...")
    build_mark_svg()
    print("[3/4] Favicons (16/32/180/.ico)...")
    build_favicons()
    print("[4/4] OG image (1200x630)...")
    build_og_image()

    print("\nDone.")


if __name__ == "__main__":
    main()
